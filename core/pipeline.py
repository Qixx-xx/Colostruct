"""End-to-end orchestration for one ColoStruct case.

The production pipeline will eventually replace the mock ASR and mock LLM
stages with real providers.  This module fixes the sequencing and payload
contract now:

1. stitch uploaded audio with :mod:`core.audio_merge`;
2. produce ordered ASR segments (mock in this MVP);
3. de-noise them with :mod:`core.cleanup`;
4. obtain an extraction (mock or caller-supplied);
5. audit it with :mod:`core.validate`;
6. return the front-end payload.

The mock ASR transcript is intentionally fixed so the default mock extraction
can reference quotes that really exist.  A caller-supplied ``mock_llm_dict``
must reference the generated ``segment_id`` values and matching quotes, or the
audit will (correctly) flag it.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

if __package__:
    from . import audio_merge, cleanup, validate
    from .pathology_schema import (
        ColoStructExtraction,
        Evidence,
        FieldModel,
        FullClinicalReport,
        NarrativeSection,
    )
else:  # pragma: no cover - exercised when running ``python core/pipeline.py``
    import audio_merge
    import cleanup
    import validate
    from pathology_schema import (
        ColoStructExtraction,
        Evidence,
        FieldModel,
        FullClinicalReport,
        NarrativeSection,
    )

__all__ = [
    "STORAGE_AUDIO_DIR",
    "process_case",
    "process_case_real",
    "process_full_report",
]

logger = logging.getLogger(__name__)

#: Root of the project, resolved from this file so the pipeline does not depend
#: on the caller's current working directory.
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: Stitched audio is persisted here; one sub-directory per case.  Set
#: ``STORAGE_DIR`` to relocate the root (for example to a Docker volume).
_STORAGE_SETTING: Final[str] = os.environ.get("STORAGE_DIR", "").strip()
STORAGE_AUDIO_DIR: Final[Path] = (
    Path(_STORAGE_SETTING).expanduser()
    if _STORAGE_SETTING
    else PROJECT_ROOT / "storage"
) / "audio"


@dataclass(frozen=True)
class _MockCase:
    """One canned ASR/extraction pair used by the local MVP.

    Attributes:
        text: Raw ASR text for the segment, including fillers to exercise the
            cleanup layer.
        field_key: Canonical 15-field key supported by this segment.
        value: Mock extracted value.
        quote: Quote that must survive cleanup and support ``value``.
    """

    text: str
    field_key: str
    value: str
    quote: str


#: Ordered mock segments.  The first N cases are used for N uploaded segments;
#: additional segments cycle through the texts without duplicating fields.
_MOCK_ASR_CASES: Final[tuple[_MockCase, ...]] = (
    _MockCase(
        text="呃...呢個 tumour 呢，um...大概 3 cm 啦",
        field_key="tumour_dimension",
        value="3 cm",
        quote="大概 3 cm",
    ),
    _MockCase(
        text="但係我睇到 4 cm，其實 5 cm，遠端切緣 5 cm",
        field_key="proximal_and_distal_margins",
        value="5 cm",
        quote="遠端切緣 5 cm",
    ),
    _MockCase(
        text="淋巴結 2/14 有轉移",
        field_key="lymph_node_status",
        value="2/14",
        quote="淋巴結 2/14 有轉移",
    ),
)


def _mock_asr_from_offsets(offsets: list[dict]) -> list[dict]:
    """Build deterministic mock ASR segments from the audio offset table.

    One transcript segment is created per successfully merged audio segment.
    ``segment_id`` follows the original upload index (``seg-001`` for index 0),
    so skipped corrupt files leave visible gaps rather than renumbering the
    remaining segments.

    Args:
        offsets: Offset table returned by
            :func:`core.audio_merge.merge_audio_segments`.

    Returns:
        Ordered ASR-like segments with ``segment_id``, ``text``, ``start``, and
        ``end``.
    """
    segments: list[dict] = []

    for position, offset in enumerate(offsets):
        case = _MOCK_ASR_CASES[position % len(_MOCK_ASR_CASES)]
        segment_index = int(offset["segment_index"])
        start = float(offset["offset_sec"])
        duration = float(offset["duration_sec"])

        segments.append(
            {
                "segment_id": f"seg-{segment_index + 1:03d}",
                "text": case.text,
                "start": start,
                "end": round(start + duration, 3),
            }
        )

    return segments


def _default_mock_extraction(
    clean_segments: list[dict],
) -> ColoStructExtraction:
    """Build the local fallback extraction from the cleaned mock transcript.

    The mock deliberately omits ``status``: the Pydantic default is
    ``ABSENT``, and :func:`core.validate.audit_extraction` must promote verified
    fields to ``POPULATED``.  This mirrors the real LLM contract where final
    status is back-end-owned.

    Args:
        clean_segments: Cleaned ASR segments in timeline order.

    Returns:
        A partial :class:`ColoStructExtraction`; the schema fills the remaining
        fields as absent.
    """
    fields: dict[str, FieldModel] = {}

    for position, segment in enumerate(clean_segments):
        case = _MOCK_ASR_CASES[position % len(_MOCK_ASR_CASES)]
        if case.field_key in fields:
            continue

        fields[case.field_key] = FieldModel(
            value=case.value,
            evidence=[
                Evidence(
                    segment_id=str(segment["segment_id"]),
                    quote=case.quote,
                )
            ],
        )

    return ColoStructExtraction(fields=fields)


def process_case(
    audio_file_paths: list[str],
    mock_llm_dict: dict | None = None,
) -> dict:
    """Run the complete mock-backed ColoStruct pipeline for one case.

    Args:
        audio_file_paths: Uploaded audio files in submission order.
        mock_llm_dict: Optional extraction-shaped dictionary.  When it is
            non-empty, it is validated into a
            :class:`~core.pathology_schema.ColoStructExtraction`; otherwise a
            built-in mock extraction is used.  A supplied dictionary must use
            the generated ``segment_id`` values and quotes that occur in the
            cleaned mock transcript.

    Returns:
        The front-end payload::

            {
                "audio_url": str,
                "clean_segments": list[dict],
                "fields": dict,
                "override_logs": list[dict],
                "has_block": bool,
            }

    Raises:
        ValueError: If no audio paths are supplied or none can be merged.
        pydantic.ValidationError: If ``mock_llm_dict`` is not a valid
            extraction.
    """
    if not audio_file_paths:
        raise ValueError("audio_file_paths must contain at least one audio file")

    case_id = uuid.uuid4().hex
    stitched_path = STORAGE_AUDIO_DIR / case_id / "stitched.wav"

    # Fresh clones do not have storage/audio yet.  Create the case directory
    # explicitly before audio_merge writes the stitched WAV.
    stitched_path.parent.mkdir(parents=True, exist_ok=True)

    offsets = audio_merge.merge_audio_segments(
        audio_file_paths,
        str(stitched_path),
    )
    mock_asr = _mock_asr_from_offsets(offsets)
    clean_segments = cleanup.clean_transcript(mock_asr)

    if mock_llm_dict:
        llm_result = ColoStructExtraction.model_validate(mock_llm_dict)
    else:
        llm_result = _default_mock_extraction(clean_segments)

    audited_result = validate.audit_extraction(llm_result, clean_segments)
    dumped = audited_result.model_dump(mode="json")

    logger.info(
        "Processed case %s: segments=%d fields=%d has_block=%s",
        case_id,
        len(clean_segments),
        len(dumped["fields"]),
        audited_result.has_block,
    )

    return {
        "audio_url": str(stitched_path),
        "clean_segments": clean_segments,
        "fields": dumped["fields"],
        "override_logs": dumped["override_logs"],
        "has_block": audited_result.has_block,
    }


def _build_real_asr_engine() -> Any:
    """Build the configured real ASR engine.

    ``COLOSTRUCT_ASR_BACKEND=hf`` selects the optional Hugging Face checkpoint;
    any other value keeps the A-group faster-whisper default.
    """
    backend_name = (
        os.environ.get(
            "COLOSTRUCT_ASR_BACKEND",
            "faster-whisper",
        )
        .strip()
        .lower()
    )
    device = (
        (os.environ.get("WHISPER_DEVICE") or os.environ.get("ASR_DEVICE") or "cpu")
        .strip()
        .lower()
    )
    if device not in {"cpu", "cuda"}:
        logger.warning("Unsupported ASR device %r; falling back to cpu", device)
        device = "cpu"
    language = (
        os.environ.get("WHISPER_LANGUAGE") or os.environ.get("ASR_LANGUAGE") or ""
    ).strip() or None

    if backend_name in {"hf", "huggingface", "transformers"}:
        from .asr import ASRConfig, ASREngine
        from .asr_hf_whisper import (
            DEFAULT_MODEL_ID,
            DEFAULT_MODEL_REVISION,
            HFWhisperBackend,
        )

        model_path = (
            os.environ.get("WHISPER_MODEL_PATH")
            or os.environ.get("WHISPER_MODEL_ID")
            or DEFAULT_MODEL_ID
        )
        revision = os.environ.get("WHISPER_REVISION") or DEFAULT_MODEL_REVISION
        local_only = os.environ.get(
            "WHISPER_LOCAL_FILES_ONLY",
            "0",
        ).strip().lower() in {"1", "true", "yes", "on"}
        backend = HFWhisperBackend(
            model_path=model_path,
            revision=revision,
            device=device,
            language=language or "en",
            local_files_only=local_only,
        )
        return ASREngine(
            ASRConfig(device=device, language=language or "en"),
            backend=backend,
        )

    from .asr import ASRConfig, ASREngine

    return ASREngine(
        ASRConfig(
            model_size=os.environ.get("ASR_MODEL", "base"),
            device=device,
            compute_type=os.environ.get("ASR_COMPUTE_TYPE", "int8"),
            language=language,
        )
    )


def process_case_real(
    audio_file_paths: list[str],
    *,
    asr_engine: Any | None = None,
    llm_client: Any | None = None,
    skip_pass_a: bool = False,
) -> dict:
    """Run the real ASR → Pass A → Pass B → audit pipeline for one case.

    The function stitches the uploaded files (preserving the existing global
    timestamp contract), transcribes the stitched audio, cleans the adapted
    segments, runs the A-group LLM service, and audits the resulting 15-field
    extraction.  It returns the same front-end payload shape as
    :func:`process_case`.

    Args:
        audio_file_paths: Uploaded audio file paths in submission order.
        asr_engine: Optional injected ASR engine (for tests or custom models).
        llm_client: Optional injected Ollama-compatible client.
        skip_pass_a: Skip Pass A and feed the original cleaned text to Pass B.

    Raises:
        ValueError: No input files.
        ASRIntegrationError: ASR failed or produced no usable speech.
        AGroupPipelineError: Pass B failed.
    """
    if not audio_file_paths:
        raise ValueError("audio_file_paths must contain at least one audio file")

    case_id = uuid.uuid4().hex
    stitched_path = STORAGE_AUDIO_DIR / case_id / "stitched.wav"
    stitched_path.parent.mkdir(parents=True, exist_ok=True)

    audio_merge.merge_audio_segments(
        audio_file_paths,
        str(stitched_path),
    )

    engine = asr_engine or _build_real_asr_engine()
    asr_result = engine.transcribe(str(stitched_path))

    if __package__:
        from .asr_adapter import adapt_asr_result
        from .llm.service import extract_clinical_info_result
    else:  # pragma: no cover - exercised when running ``python core/pipeline.py``
        from asr_adapter import adapt_asr_result
        from llm.service import extract_clinical_info_result

    adapted = adapt_asr_result(asr_result)
    clean_segments = cleanup.clean_transcript(adapted.segments)
    if not clean_segments:
        raise ValueError("clean_transcript returned no usable segments")

    agroup_result = extract_clinical_info_result(
        clean_segments=clean_segments,
        client=llm_client,
        skip_pass_a=skip_pass_a,
    )
    audited_result = validate.audit_extraction(
        agroup_result.extraction,
        clean_segments,
    )
    dumped = audited_result.model_dump(mode="json")

    logger.info(
        "Real case %s: ASR=%s model=%s segments=%d fields=%d has_block=%s",
        case_id,
        asr_result.status,
        asr_result.model,
        len(clean_segments),
        len(dumped["fields"]),
        audited_result.has_block,
    )

    return {
        "audio_url": str(stitched_path),
        "clean_segments": clean_segments,
        "fields": dumped["fields"],
        "override_logs": dumped["override_logs"],
        "has_block": audited_result.has_block,
    }


#: Reference narrative text imported from the 36800.docx sample report.  It is
#: used only when ``COLOSTRUCT_NARRATIVE_MOCK=1`` so that the full-report flow
#: can be exercised without ASR or a running LLM.
MOCK_NARRATIVE_TEXT: Final[dict[str, str]] = {
    "macro": (
        "1) Cut opened large intestine, 18.0 cm in length, 6.9 cm in transverse "
        "dimension, with attached mesentery about 17 x 8 x 3 cm in size. There "
        "is a malignant-looking tumour mass at the middle portion of the mucosa. "
        "It is 4.0 cm in longitudinal dimension, 4.0 cm in transverse dimension "
        "and more than 6.0 cm from proximal and distal resection margins. It is "
        "located at the anti-mesenteric aspect. Cut surface of the tumour shows "
        "firm pinkish tumour tissue invading to the muscle wall and there is "
        "focal extension close to the peritoneal surface (inked black). Multiple "
        "lymph nodes can be found in the mesentery with one of them showing "
        "suspected tumour tissue on cut surface. (A) 2 tissue blocks, resection "
        "margins. (B) Multiple tissue blocks, apical lymph node and vascular "
        "apex. (C)to(F) Multiple tissue blocks, lymph nodes (suspicious lymph "
        "node in 2 tissue blocks in C). (G)to(J) Multiple tissue blocks, tumour "
        "with peritoneal surface. Figure 1 shows the submitted specimen. Figure "
        "2 shows cut surface of tumour.\n\n"
        "2) Distal margin. A ring of large intestinal wall 2.0 x 1.5 x 0.6 cm. "
        "No obvious tumour tissue is found. All embedded in multiple tissue "
        "blocks in 1 cassette. Figure 3 shows the submitted specimen."
    ),
    "micro": (
        "1&2) Sections on the sigmoid tumour show moderately differentiated "
        "adenocarcinoma. There are infiltrative complex and fused glandular "
        "structure and surface villi that are lined by columnar epithelial "
        "cells exhibiting moderate marked nuclear pleomorphism with prominent "
        "mitosis. Desmoplastic stromal reaction is present. The tumour show "
        "extension through the submucosa and muscularis propria into the "
        "subserosa, with no evidence of peritoneal involvement. There is no "
        "vascular permeation by tumour. No perineural invasion by tumour is "
        "seen. The resection margins are clear. 16 lymph nodes are found. 2 of "
        "them show metastatic carcinoma. The apical lymph nodes show no "
        "metastasis."
    ),
}

#: Prompt used for the A-group long-text polishing call.
_NARRATIVE_SYSTEM_PROMPT: Final[str] = (
    "You are a pathology report editor. Rewrite the raw ASR transcript into "
    "clean, readable narrative text for the requested section. Preserve every "
    "clinical fact, number, specimen identifier, and the original order. Do "
    "not add, remove, summarise, or reinterpret findings. Keep numbered items "
    "such as '1)' at the beginning of their lines. Return only a JSON object "
    'of the form {"text": "<narrative>"}.'
)

#: Whisper is not thread-safe; serialise narrative transcription while the
#: three report sections still run as separate worker threads.
_NARRATIVE_ASR_LOCK = threading.Lock()
_NARRATIVE_ASR_ENGINE: Any = None
_NARRATIVE_ASR_CREATE_LOCK = threading.Lock()


class _LockedASREngine:
    """Serialise access to one ASR engine shared by all report threads.

    Loading two Whisper models concurrently fails on some CUDA/Hugging Face
    combinations, and a single ``ASREngine`` is not thread-safe. Wrapping the
    shared engine keeps one model in memory and makes ``load``/``transcribe``
    mutually exclusive.
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def load(self, config: Any) -> None:
        with _NARRATIVE_ASR_LOCK:
            self._engine.load(config)

    def transcribe(self, audio_path: str) -> Any:
        with _NARRATIVE_ASR_LOCK:
            return self._engine.transcribe(audio_path)


def _narrative_mock_enabled() -> bool:
    """Return whether narrative processing should use the 36800 mock text."""
    return os.environ.get("COLOSTRUCT_NARRATIVE_MOCK", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _get_narrative_asr_engine() -> Any:
    """Return a lazily-created, lock-wrapped ASR engine for all sections."""
    global _NARRATIVE_ASR_ENGINE
    if _NARRATIVE_ASR_ENGINE is None:
        with _NARRATIVE_ASR_CREATE_LOCK:
            if _NARRATIVE_ASR_ENGINE is None:
                real_builder = globals().get("_build_real_asr_engine")
                if callable(real_builder):
                    engine = real_builder()
                else:
                    if __package__:
                        from .asr import ASRConfig, ASREngine
                    else:  # pragma: no cover
                        from asr import ASRConfig, ASREngine

                    engine = ASREngine(
                        ASRConfig(
                            model_size=os.environ.get("ASR_MODEL", "base"),
                            device=(
                                os.environ.get("ASR_DEVICE") or "cpu"
                            ).strip().lower(),
                            compute_type=os.environ.get("ASR_COMPUTE_TYPE", "int8"),
                        )
                    )
                _NARRATIVE_ASR_ENGINE = _LockedASREngine(engine)
    return _NARRATIVE_ASR_ENGINE


def _transcribe_narrative(audio_path: str) -> str:
    """Transcribe one macro/micro audio file into a single raw text block."""
    engine = _get_narrative_asr_engine()
    result = engine.transcribe(str(audio_path))

    if result.status == "failed":
        raise RuntimeError(f"ASR failed ({result.error_code or 'unknown error'})")

    text = " ".join(
        segment.text.strip() for segment in result.segments if segment.text.strip()
    ).strip()
    if not text:
        raise ValueError("ASR produced no narrative text")
    return text


def _polish_narrative(section: str, raw_text: str) -> str:
    """Call the A-group Ollama client to polish one narrative section."""
    if __package__:
        from .llm.client import OllamaClient
    else:  # pragma: no cover
        from llm.client import OllamaClient

    client = OllamaClient()
    response = client.generate_json(
        system=_NARRATIVE_SYSTEM_PROMPT,
        user=f"Section: {section}\n\nRaw ASR transcript:\n{raw_text}",
    )
    text = response.get("text") if isinstance(response, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ValueError("LLM narrative response has no usable 'text'")
    return text


def _process_narrative(section: str, audio_path: str | None) -> NarrativeSection:
    """Produce one narrative section, converting every failure to ``failed``."""
    if not audio_path:
        return NarrativeSection(status="absent")

    try:
        if _narrative_mock_enabled():
            raw_text = MOCK_NARRATIVE_TEXT[section]
            polished = raw_text
        else:
            raw_text = _transcribe_narrative(str(audio_path))
            polished = _polish_narrative(section, raw_text)

        cleaned = cleanup.clean_narrative_output(polished)
        validate.validate_narrative(cleaned, raw_text)
        return NarrativeSection(text=cleaned, status="success")
    except Exception:
        logger.exception("Narrative processing failed for section %s", section)
        return NarrativeSection(status="failed")


def _process_diagnosis(audio_path: str) -> ColoStructExtraction:
    """Run the diagnosis path and return its structured extraction."""
    real_processor = globals().get("process_case_real")
    if callable(real_processor):
        # Reuse the single shared engine instead of loading a second Whisper
        # model concurrently with the narrative threads.
        payload = real_processor(
            [str(audio_path)], asr_engine=_get_narrative_asr_engine()
        )
    else:
        payload = process_case([str(audio_path)])

    return ColoStructExtraction.model_validate(
        {
            "fields": payload.get("fields", {}),
            "override_logs": payload.get("override_logs", []),
            "has_block": payload.get("has_block", False),
        }
    )


def process_full_report(
    diag_file: str,
    macro_file: str | None = None,
    micro_file: str | None = None,
) -> FullClinicalReport:
    """Build the complete report from diagnosis, macro, and micro audio.

    The three sections are processed concurrently with a
    :class:`~concurrent.futures.ThreadPoolExecutor`.  Diagnosis runs the
    structured 15-field pipeline, while macro and micro are transcribed and
    polished into narrative sections.

    Args:
        diag_file: Path to the diagnosis audio (required).
        macro_file: Optional path to the macroscopic examination audio.
        micro_file: Optional path to the microscopic examination audio.

    Returns:
        A :class:`~core.pathology_schema.FullClinicalReport` containing the
        diagnosis extraction and both narrative sections.  A failed section is
        represented by ``status="failed"`` rather than raising.

    Raises:
        ValueError: If ``diag_file`` is empty.
    """
    if not diag_file:
        raise ValueError("diag_file is required")

    with ThreadPoolExecutor(
        max_workers=3, thread_name_prefix="colostruct-report"
    ) as executor:
        diagnosis_future = executor.submit(_process_diagnosis, diag_file)
        macro_future = executor.submit(_process_narrative, "macro", macro_file)
        micro_future = executor.submit(_process_narrative, "micro", micro_file)

        try:
            diagnosis = diagnosis_future.result()
        except Exception:
            logger.exception("Diagnosis pipeline failed; returning empty extraction")
            diagnosis = ColoStructExtraction()
            # Fail closed: an empty diagnosis must not be exportable.
            diagnosis.has_block = True

        macro = macro_future.result()
        micro = micro_future.result()

    return FullClinicalReport(diagnosis=diagnosis, macro=macro, micro=micro)


if __name__ == "__main__":
    import json
    import math
    import struct
    import tempfile
    import wave

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    def _write_test_tone(
        path: Path,
        *,
        duration_sec: float,
        frequency: float,
        frame_rate: int,
        channels: int,
    ) -> None:
        """Write a short PCM WAV tone with a deliberately non-target format."""
        frame_count = round(duration_sec * frame_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(
                32767 * 0.2 * math.sin(2 * math.pi * frequency * index / frame_rate)
            )
            frames.extend(struct.pack("<h", sample) * channels)

        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(frame_rate)
            wav_file.writeframes(bytes(frames))

    with tempfile.TemporaryDirectory(prefix="colostruct-pipeline-") as tmp:
        work_dir = Path(tmp)
        first = work_dir / "segment-1.wav"
        second = work_dir / "segment-2.wav"

        _write_test_tone(
            first,
            duration_sec=0.8,
            frequency=440.0,
            frame_rate=44100,
            channels=2,
        )
        _write_test_tone(
            second,
            duration_sec=0.5,
            frequency=880.0,
            frame_rate=22050,
            channels=1,
        )

        payload = process_case([str(first), str(second)])

        print(
            json.dumps(
                {
                    "audio_url": payload["audio_url"],
                    "clean_segments": payload["clean_segments"],
                    "populated_fields": {
                        key: {
                            "value": value["value"],
                            "status": value["status"],
                            "evidence": value["evidence"],
                        }
                        for key, value in payload["fields"].items()
                        if value["value"] is not None
                    },
                    "override_logs": payload["override_logs"],
                    "has_block": payload["has_block"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        assert Path(payload["audio_url"]).exists()
        assert len(payload["clean_segments"]) == 2
        assert payload["fields"]["tumour_dimension"]["status"] == "populated"
        assert payload["fields"]["proximal_and_distal_margins"]["status"] == "populated"
        assert payload["has_block"] is False
        assert payload["override_logs"] == []

        print("\nAll pipeline assertions passed.")
        print(f"Stitched audio kept at: {payload['audio_url']}")
