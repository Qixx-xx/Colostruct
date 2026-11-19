"""FastAPI gateway for the ColoStruct backend.

This module is the only file added for the front-end/back-end split. ``core/``
and ``ui/`` are treated as read-only dependencies.

Contract implemented for the Streamlit front end (``ui/upload_panel.py``):

    POST http://127.0.0.1:8000/api/process
    multipart/form-data, any subset of:
        diag_audio  -> diagnosis pipeline (real ASR -> Pass A -> Pass B -> audit)
        macro_audio -> speech-to-text only
        micro_audio -> speech-to-text only

    JSON response (always well formed, even on failure):
        {
          "status": "success" | "partial" | "failed",
          "error": str | null,
          "diagnosis": {"status": "success"|"failed"|"not_uploaded", "data": {...}|null, "error": str|null},
          "macro":     {...same shape...},
          "micro":     {...same shape...}
        }

Safety rules followed here:
* every request is wrapped in try/except, per-stage and global;
* uploaded bytes go to a per-request temporary directory removed in ``finally``;
* CORS is open because the page is served from a different port (8501);
* pipeline/model work is serialised with a lock (Whisper is not thread-safe);
* every step logs, so the front end's "stuck" point is visible in the console.

Run from the repository root::

    python api.py
    # or
    python -m uvicorn api:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

PROJECT_ROOT = Path(__file__).resolve().parent

# Load local configuration before anything from core/ reads the environment.
load_dotenv(PROJECT_ROOT / ".env")

# core.pipeline resolves a relative STORAGE_DIR against the process CWD. Anchor
# it to the repository so ``uvicorn api:app`` behaves the same from any folder.
_storage_setting = os.environ.get("STORAGE_DIR", "").strip()
if _storage_setting and not Path(_storage_setting).expanduser().is_absolute():
    os.environ["STORAGE_DIR"] = str((PROJECT_ROOT / _storage_setting).resolve())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("colostruct.api")

#: Serialise pipeline work: one Whisper model + one Ollama server.
_PIPELINE_LOCK = threading.Lock()

#: Lazily-created ASR engine, reused across requests (model load is ~6 s).
_ASR_ENGINE: Any = None

#: Accepted upload suffixes; anything else is stored with a neutral suffix.
_ALLOWED_SUFFIXES = {".wav", ".mp3", ".wma", ".m4a", ".flac", ".aac", ".ogg", ".webm"}

app = FastAPI(
    title="ColoStruct Backend API",
    version="1.0.0",
    description="ASR -> Pass A -> Pass B -> validation gateway for the ColoStruct front end.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _error_text(exc: BaseException, limit: int = 500) -> str:
    """Return a short, log-safe description of an exception."""
    message = str(exc).strip() or exc.__class__.__name__
    text = f"{exc.__class__.__name__}: {message}"
    return text[:limit]


def _module(status: str, data: Any = None, error: str | None = None) -> dict:
    return {"status": status, "data": data, "error": error}


def _pipeline_audio_dir() -> Path:
    """Return the directory core.pipeline writes stitched audio into."""
    from core.pipeline import STORAGE_AUDIO_DIR

    return Path(STORAGE_AUDIO_DIR).resolve()


def _public_audio_url(request: Request, file_path: str) -> str:
    """Turn a local stitched-audio path into a URL the browser can play."""
    if not file_path:
        return ""
    try:
        relative = Path(file_path).resolve().relative_to(_pipeline_audio_dir())
    except (ValueError, OSError):
        return file_path
    base = str(request.base_url).rstrip("/")
    return f"{base}/storage/audio/{relative.as_posix()}"


def _save_upload(upload: UploadFile, directory: Path, stem: str) -> Path:
    """Write one UploadFile to disk and return its absolute path."""
    raw_name = upload.filename or ""
    suffix = Path(raw_name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        suffix = ".wav"
    target = directory / f"{stem}{suffix}"

    size = 0
    with target.open("wb") as handle:
        while True:
            chunk = upload.file.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            handle.write(chunk)

    if size == 0:
        raise ValueError(f"uploaded file for '{stem}' is empty")

    logger.info(
        "saved upload | field=%s original=%r bytes=%d -> %s",
        stem,
        raw_name,
        size,
        target.name,
    )
    return target


def _get_engine() -> Any:
    """Return the cached real ASR engine (created once, reused per request)."""
    global _ASR_ENGINE
    if _ASR_ENGINE is None:
        from core.pipeline import _build_real_asr_engine

        logger.info(
            "building ASR engine | backend=%s model=%s device=%s",
            os.environ.get("COLOSTRUCT_ASR_BACKEND", "faster-whisper"),
            os.environ.get("WHISPER_MODEL_PATH")
            or os.environ.get("WHISPER_MODEL_ID", "<default>"),
            os.environ.get("WHISPER_DEVICE") or os.environ.get("ASR_DEVICE", "cpu"),
        )
        _ASR_ENGINE = _build_real_asr_engine()
        logger.info("ASR engine ready and cached")
    else:
        logger.info("reusing cached ASR engine")
    return _ASR_ENGINE


def _run_diagnosis(engine: Any, path: Path, request: Request) -> dict:
    """Run the full real pipeline for the diagnosis audio."""
    from core.pipeline import process_case_real

    started = time.perf_counter()
    logger.info("pipeline start | case=diagnosis | input=%s", path.name)
    payload = process_case_real([str(path)], asr_engine=engine)
    payload["audio_url"] = _public_audio_url(request, str(payload.get("audio_url", "")))
    logger.info(
        "pipeline done | case=diagnosis | segments=%d fields=%d has_block=%s elapsed=%.1fs",
        len(payload.get("clean_segments") or []),
        len(payload.get("fields") or {}),
        payload.get("has_block"),
        time.perf_counter() - started,
    )
    return _module("success", payload)


def _run_transcription(engine: Any, path: Path, case: str) -> dict:
    """Speech-to-text only (macro / micro sections)."""
    from core import cleanup
    from core.asr_adapter import adapt_asr_result

    started = time.perf_counter()
    logger.info("pipeline start | case=%s | input=%s", case, path.name)
    result = engine.transcribe(str(path))
    if result.status == "failed":
        raise RuntimeError(f"ASR failed ({result.error_code or 'unknown error'})")

    adapted = adapt_asr_result(result)
    segments = cleanup.clean_transcript(adapted.segments)
    if not segments:
        raise RuntimeError("ASR produced no usable speech")

    text = " ".join(str(segment.get("text", "")).strip() for segment in segments).strip()
    data = {
        # The upload lives in the per-request temp dir and is deleted afterwards,
        # so there is no playable artifact to expose for macro/micro.
        "audio_url": "",
        "clean_segments": segments,
        "text": text,
    }
    logger.info(
        "pipeline done | case=%s | segments=%d chars=%d elapsed=%.1fs",
        case,
        len(segments),
        len(text),
        time.perf_counter() - started,
    )
    return _module("success", data)


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict:
    """Lightweight liveness probe; never loads a model."""
    return {
        "status": "ok",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "storage_audio_dir": str(_pipeline_audio_dir()),
    }


@app.get("/storage/audio/{case_dir}/{filename}")
def get_stitched_audio(case_dir: str, filename: str) -> FileResponse:
    """Serve stitched audio so the front end timeline can play it."""
    base = _pipeline_audio_dir()
    target = (base / case_dir / filename).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=404, detail="audio not found") from None
    if not target.is_file():
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(target)


@app.post("/api/process")
def process_audio(
    request: Request,
    diag_audio: UploadFile | None = File(default=None),
    macro_audio: UploadFile | None = File(default=None),
    micro_audio: UploadFile | None = File(default=None),
) -> JSONResponse:
    """Accept up to three audio files and return the front-end payload."""
    started = time.perf_counter()
    logger.info(
        "request received | POST /api/process | diag=%s macro=%s micro=%s",
        getattr(diag_audio, "filename", None),
        getattr(macro_audio, "filename", None),
        getattr(micro_audio, "filename", None),
    )

    response: dict[str, Any] = {
        "status": "success",
        "error": None,
        "diagnosis": _module("not_uploaded"),
        "macro": _module("not_uploaded"),
        "micro": _module("not_uploaded"),
    }

    requested: dict[str, UploadFile] = {}
    if diag_audio is not None:
        requested["diagnosis"] = diag_audio
    if macro_audio is not None:
        requested["macro"] = macro_audio
    if micro_audio is not None:
        requested["micro"] = micro_audio

    workdir = Path(tempfile.mkdtemp(prefix="colostruct-api-"))
    logger.info("temp workspace | %s", workdir)
    saved: dict[str, Path] = {}

    try:
        if not requested:
            raise ValueError(
                "no audio file provided; send diag_audio, macro_audio or micro_audio"
            )

        for case, upload in requested.items():
            saved[case] = _save_upload(upload, workdir, case)

        # Model work is serialised; one request at a time is plenty for a
        # single clinician workstation and avoids concurrent model loads.
        with _PIPELINE_LOCK:
            engine = _get_engine()

            for case, path in saved.items():
                try:
                    if case == "diagnosis":
                        response[case] = _run_diagnosis(engine, path, request)
                    else:
                        response[case] = _run_transcription(engine, path, case)
                except Exception as exc:  # one bad module must not sink the rest
                    logger.exception("stage failed | case=%s", case)
                    response[case] = _module("failed", None, _error_text(exc))
    except Exception as exc:  # unhandled setup/validation error
        logger.exception("request failed before/around pipeline")
        response["error"] = _error_text(exc)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        logger.info("temp workspace removed | %s", workdir.name)

    requested_states = [response[case]["status"] for case in saved]
    failed = [state for state in requested_states if state == "failed"]
    succeeded = [state for state in requested_states if state == "success"]
    if failed and succeeded:
        response["status"] = "partial"
    elif failed:
        response["status"] = "failed"
    elif succeeded:
        response["status"] = "success"
    else:
        response["status"] = "failed"

    if response["error"] is None and failed:
        response["error"] = next(
            response[case]["error"] for case in saved if response[case]["status"] == "failed"
        )

    elapsed = time.perf_counter() - started
    logger.info(
        "response ready | status=%s diagnosis=%s macro=%s micro=%s elapsed=%.2fs",
        response["status"],
        response["diagnosis"]["status"],
        response["macro"]["status"],
        response["micro"]["status"],
        elapsed,
    )
    return JSONResponse(status_code=200, content=response)


@app.exception_handler(Exception)
def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: never let uvicorn return a non-JSON crash."""
    logger.exception("unhandled exception | path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "status": "failed",
            "error": _error_text(exc),
            "diagnosis": None,
            "macro": None,
            "micro": None,
        },
    )


if __name__ == "__main__":
    import uvicorn

    # Bind address is configuration, not code: 127.0.0.1 for a single-machine
    # demo, 0.0.0.0 only when another machine must reach this API over a
    # trusted network (that exposes clinical audio, so it stays opt-in).
    api_host = os.environ.get("API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        api_port = int(os.environ.get("API_PORT", "8000"))
    except ValueError:
        api_port = 8000

    logger.info(
        "starting ColoStruct API | cwd=%s | host=%s port=%d | ollama=%s | model=%s",
        Path.cwd(),
        api_host,
        api_port,
        os.environ.get("COLOSTRUCT_OLLAMA_URL", "http://127.0.0.1:11434"),
        os.environ.get("COLOSTRUCT_LLM_MODEL", "qwen3:8b"),
    )
    uvicorn.run(app, host=api_host, port=api_port)
