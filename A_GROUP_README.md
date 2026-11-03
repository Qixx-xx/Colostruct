# ColoStruct A Group — ASR / LLM Module Interface

This document describes the **actual current implementation** of the A-group
module tree. It is the integration interface for the backend and does not
describe planned or unconfirmed behavior.

---

## 1. Scope and responsibilities

### A group owns

- ASR wrapper around faster-whisper: `core/asr.py`;
- ASR result → backend clean-segment adapter: `core/asr_adapter.py`;
- Pass A (transcript correction + temporal override candidates): `core/llm/preprocessing.py`;
- Pass B (15-field extraction): `core/llm/extraction.py`;
- `AGroupResult` contract: `core/llm/result.py`;
- Service orchestration and public entries: `core/llm/service.py`,
  `core/extract_clinical_info.py`;
- Ollama client / prompts / parsing: `core/llm/client.py`, `prompts.py`, `parsing.py`;
- A-group tests under `tests/`.

### A group does NOT own

- the official pipeline (`pipeline.py`) or its mock/real provider wiring;
- `cleanup.py`, `pathology_schema.py`, `validate.py` (owned by B group);
- evidence audit decisions, `has_block` UI behavior, doctor review;
- clinical approval, accuracy claims, or model-quality validation;
- the formal ASR lifecycle inside the production pipeline (M1, see §15).

The Pass A corrected text is contextual assistance only. Pass B evidence quotes
must be verbatim against the original `clean_segments` supplied by the backend.
The backend audit remains authoritative.

---

## 2. Expected merged layout and runtime prerequisites

A modules import sibling modules with relative imports (`..pathology_schema`,
`..cleanup`), so they must be merged into the official `core/` package; the dev
copy is not a standalone installable package.

Expected merged layout:

```text
core/
├── asr.py                     # A
├── asr_adapter.py             # A
├── extract_clinical_info.py   # A
├── cleanup.py                 # B
├── validate.py                # B
├── pathology_schema.py        # B
├── pipeline.py                # B
└── llm/                       # A
    ├── __init__.py
    ├── client.py
    ├── parsing.py
    ├── prompts.py
    ├── preprocessing.py
    ├── extraction.py
    ├── result.py
    └── service.py
```

Runtime prerequisites:

- Python 3.11.x, `pydantic >= 2, < 3`;
- real ASR: `faster-whisper`, `ctranslate2`, `av`, `numpy`, plus a cached
  Whisper model;
- real Pass A/B: a running Ollama endpoint (default `http://127.0.0.1:11434`)
  and the configured model (default `qwen3:8b`);
- `audio_path` mode additionally needs B's `core.cleanup` (and `pydub`/`ffmpeg`
  for non-WAV files in B's audio merge path);
- `AGroupResult` / service cannot run in the A-group development tree without
  the official `core.pathology_schema` on `PYTHONPATH`; `audio_path` mode
  additionally needs `core.cleanup` (or an injected cleaner).

Ollama settings can be overridden without code changes:

- `COLOSTRUCT_OLLAMA_URL` (default `http://127.0.0.1:11434`)
- `COLOSTRUCT_LLM_MODEL` (default `qwen3:8b`)
- `COLOSTRUCT_LLM_TIMEOUT` (default `180`)
- `COLOSTRUCT_LLM_TEMPERATURE` (default `0`)

`qwen3:8b` is an initial candidate, not a quality-validated model. Real
inference requires Ollama to be running and the model to be available
(`ollama pull qwen3:8b`). These commands were **not** run in this documentation
update.

---

## 3. ASR interface

### 3.1 `ASRConfig`

`core/asr.py`

| Field | Type | Default |
|---|---|---|
| `model_size` | `str` | `"base"` |
| `device` | `Literal["cpu","cuda"]` | `"cpu"` |
| `compute_type` | `str` | `"int8"` |
| `beam_size` | `int` | `5` |
| `vad_filter` | `bool` | `True` |
| `condition_on_previous_text` | `bool` | `False` |
| `language` | `str \| None` | `None` |
| `initial_prompt` | `str \| None` | `None` |
| `word_timestamps` | `bool` | `False` |
| `cpu_threads` | `int \| None` | `None` |

`language=None` means auto-detect; a non-empty string pins the language. The
model is `extra="forbid"` and validates on construction.

### 3.2 `ASRSegment`

| Field | Type | Constraint |
|---|---|---|
| `segment_id` | `str` | matches `^seg-\d{3,}$` |
| `start` | `float` | finite, ≥ 0 |
| `end` | `float` | finite, ≥ start |
| `text` | `str` | **raw faster-whisper text; not stripped/rewritten** |

### 3.3 `ASRResult`

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `Literal["asr_result/v1"]` | fixed |
| `status` | `success / partial / failed` | see below |
| `error_code` | `str \| None` | set for partial/failed |
| `error` | `str \| None` | human-readable |
| `warnings` | `list[str]` | dropped segments/metadata warnings |
| `segments` | `list[ASRSegment]` | failed → `[]` |
| `language` | `str \| None` | — |
| `language_probability` | `float \| None` | 0–1 |
| `duration` | `float \| None` | seconds; metadata only |
| `duration_after_vad` | `float \| None` | seconds; metadata only |
| `model` | `str` | e.g. `"base"` |
| `config` | `ASRConfig` | effective snapshot |
| `elapsed_seconds` | `float` | wall clock |
| `run_metadata` | `dict` | hashes/versions/timings, no audio path/text |

Status rules:

- `success`: at least one segment with non-empty text, valid timestamps;
- `partial`: usable segments may continue (`PARTIAL_TRANSCRIPT`), or no usable
  speech (`NO_SPEECH`, `segments=[]`/all-empty text);
- `failed`: `AUDIO_NOT_FOUND`, `EMPTY_AUDIO`, `UNSUPPORTED_FORMAT`,
  `DECODE_ERROR`, `MODEL_LOAD_FAILED`, `INFERENCE_ERROR`,
  `INVALID_BACKEND_OUTPUT`;
- `duration` / `duration_after_vad` are **never** used to judge completeness.

### 3.4 `ASREngine`

```python
ASREngine(config: ASRConfig | None = None, backend: ASRBackend | None = None)
ASREngine.transcribe(audio_path: str) -> ASRResult
```

- constructor stores config, does **not** load the model;
- first `transcribe` loads lazily, then reuses;
- a model-load failure is cached; the same engine does not retry it;
- `transcribe` returns `ASRResult` (including `status="failed"`); it does not
  raise business exceptions;
- one engine is not thread-safe; callers serialise access.

---

## 4. Adapter: ASRResult → clean segments

```python
core.asr_adapter.adapt_asr_result(result: ASRResult) -> AdaptedASR
```

`AdaptedASR`:

| Field | Type |
|---|---|
| `segments` | `list[dict]` — `{"segment_id","start","end","text"}` |
| `status` | `str` |
| `error_code` | `str \| None` |
| `error` | `str \| None` |
| `warnings` | `list[str]` |
| `run_metadata` | `dict` |
| `has_speech` | `bool` |

Behavior:

- success / partial-with-usable-text → `AdaptedASR`; status/metadata are
  preserved and warnings pass through the same adapter allowlist as the
  exception path (unknown/free-text warnings are dropped);
- failed → raises `ASRIntegrationError` (carries `.status`, `.error_code`,
  `.warnings`; it deliberately does not expose the full `ASRResult` or raw
  `error` text);
- no usable speech (`NO_SPEECH` / all-empty text) → raises `NoSpeechError`
  (subclass of `ASRIntegrationError`);
- text is copied verbatim; no strip/rewrite; no segment is fabricated.

The adapter does not call cleanup, Pass A/B, or validate.

---

## 5. Public service entries

### 5.1 New entry

```python
extract_clinical_info_result(
    audio_path: str | None = None,
    *,
    clean_segments: list[dict] | None = None,
    asr_engine: ASREngine | None = None,
    cleaner: Callable[[list[dict]], list[dict]] | None = None,
    client: OllamaClient | None = None,
    skip_pass_a: bool = False,
) -> AGroupResult
```

Exactly one of `audio_path` / `clean_segments` must be supplied.

- `audio_path` mode: ASR → adapter → cleaner → Pass A → Pass B → `AGroupResult`;
  default cleaner is B's `core.cleanup.clean_transcript`;
- `clean_segments` mode: skips ASR and cleanup; runs Pass A/B only
  (the mode used by the old entry and by B when B already owns cleanup).

**Important:** `audio_path` mode does not return the cleaned segments. B's
`validate.audit_extraction` needs the same `clean_segments` list, so a production
caller must own cleanup (M1) or use another path; do not assume the returned
`AGroupResult` contains `clean_segments`.

### 5.2 Old entry

```python
extract_clinical_info(
    clean_segments: list[dict],
    client: OllamaClient | None = None,
) -> ColoStructExtraction
```

- returns `.extraction` from the new entry;
- override logs are preserved;
- Pass A exceptions propagate unchanged and **Pass B is not called**;
- Pass B exceptions are re-raised as the original exception object/type.

---

## 6. `AGroupResult` — five parts

`core/llm/result.py`

| Field | Type | Notes |
|---|---|---|
| `extraction` | official `ColoStructExtraction` | B consumes this after unpacking |
| `pass_a_result` | `PassAResult` | per-segment original/corrected text + candidates |
| `field_uncertainties` | `dict[str, FieldUncertainty]` | **currently always `{}`** |
| `diagnostics` | `Diagnostics` | stages `pass_a` / `pass_b` only |
| `schema_version` | `Literal["a_group_result/v1"]` | fixed |

`AGroupResult.has_failed_stage` is an auxiliary property; it is not the sole
basis for pipeline blocking.

`PassAResult` status is `success / skipped / failed`; `skipped` requires
`skip_reason`. Pass A currently never produces `partial`.

---

## 7. Pass A / Pass B behavior

### Pass A (`core/llm/preprocessing.py`)

Input: `clean_segments: list[dict]`, each with at least `segment_id` and `text`.
Output:

```python
{
  "corrected_segments": [{"segment_id": str, "corrected_text": str}, ...],
  "override_logs": [
     {"field_name": str,
      "old_evidence": {"segment_id": str, "quote": str},
      "new_evidence": {"segment_id": str, "quote": str}}
  ],
}
```

- validates unique ids, order, verbatim override quotes, later-segment ordering;
- raises `ValueError` for input-contract problems;
- raises `LLMError` for LLM/parse/override failures.

### Pass B (`core/llm/extraction.py`)

Input: `original_clean_segments` (full list) + `corrected_segments` (Pass A
context). Pass B always receives the **full original clean_segments**.

Output: official `ColoStructExtraction` with 15 fields and evidence containing
`segment_id` + `quote` only (timestamps rejected).

### Fallback rules

- Pass A `LLMError` (new API): recorded as `pass_a: failed`; Pass B still runs
  with the full original clean_segments (P2 D13);
- Pass A `ValueError` / unexpected exception: propagates, no fallback;
- Pass A skipped (`skip_pass_a=True`): diagnostics `pass_a: skipped`,
  `PassAResult(status="skipped", skip_reason=...)`, Pass B uses original text;
- Pass B failure: new API raises `AGroupPipelineError` (carries sanitized
  diagnostics and `cause_type`, no fake extraction); old API re-raises the
  original cause (historical behaviour).

---

## 8. override_logs conversion

Only Pass A's checked temporal-override records are converted to B's contract:

```python
OverrideLog(
    field_name=...,
    old_evidence=Evidence(segment_id=..., quote=...),
    new_evidence=Evidence(segment_id=..., quote=...),
)
```

`CorrectionCandidate.candidate_type == "doctor_self_correction"` is **never**
converted to `OverrideLog`; candidates are not part of the current Pass A output
path at all. The old entry also preserves override logs.

---

## 9. `field_uncertainties` — current state

The field exists in `AGroupResult` for the agreed five-part contract, but it is
**always `{}`** today; Pass B does not produce uncertainty data yet. No stable
generation mechanism exists. Do not build UI/backend features that assume
non-empty uncertainty values without a separate agreement.

---

## 10. `skip_pass_a`

`skip_pass_a=True` is an explicit caller request; there is no automatic/product
skip rule. Effects:

- Pass A is not called;
- diagnostics records `pass_a: skipped`;
- `PassAResult.status == "skipped"`, `skip_reason` is set;
- Pass B receives the original clean_segments as corrected context.

The caller owns the decision and any product semantics around skipping.

---

## 11. Exception contract

| Situation | New API | Old API |
|---|---|---|
| ASR failed | `ASRIntegrationError` | not applicable (no audio_path) |
| ASR no usable speech | `NoSpeechError` | not applicable |
| Pass A `LLMError` | fallback; `pass_a: failed`; continues | raises original `LLMError`; Pass B not called |
| Pass A `ValueError`/unexpected | propagates | propagates |
| Pass B failure | `AGroupPipelineError` with sanitized diagnostics and `cause_type` | re-raises original cause (historical) |
| `clean_segments=[]` | `ValueError` before Pass A/B | same |
| default cleaner unavailable | `RuntimeError` | not applicable |

`AGroupPipelineError` is a public exception (`core.llm.service`,
`core.llm.__init__`). It exposes `stage`, `diagnostics` and `cause_type`; it
does **not** retain or expose the original exception, its text, or any private
reference to it. The historical entry `extract_clinical_info()` handles the
original exception locally and re-raises it for compatibility.
`ASRIntegrationError` / `NoSpeechError` live in `core.asr_adapter`.

> Old-API caveat: `extract_clinical_info()` still re-raises the original
> exception object (including its message) for historical compatibility. Do not
> forward that exception text or its traceback to users, the frontend, or
> external logging systems.

---

## 12. Recommended keyword usage

The first positional parameter of `extract_clinical_info_result` is
`audio_path`, not `clean_segments`. Use keyword arguments:

```python
# Good
extract_clinical_info_result(clean_segments=segments, client=client)
extract_clinical_info_result(audio_path=wav_path, asr_engine=engine, client=client)

# Avoid: the list would be interpreted as audio_path
# extract_clinical_info_result(segments)
```

---

## 13. Diagnostics and privacy

Diagnostics are intentionally free of raw exception text:

- `StageDiagnostic.warnings` contains only stable labels such as `LLMError` or
  `RuntimeError`; it does not contain exception messages, transcript text or
  model output.
- Pass A / Pass B logs record only stable categories (for example
  `Pass A failed (LLMError)`) and ASR warning counts, not free exception text.
- `AGroupPipelineError` exposes `stage`, `diagnostics` and `cause_type`; its
  message does not include the cause, and the exception holds no reference to
  the original exception. The old entry re-raises the original exception
  locally for compatibility (see the caveat above).
- `LLMError` for Ollama HTTP failures reports the HTTP status only; the response
  body is discarded.
- ASR warnings use fixed reason labels and retain the segment index;
  `ASRResult.error` uses exception type labels. `core/asr.py` `_redact` covers
  audio paths only, not clinical text.
- Both normal `AdaptedASR.warnings` and `ASRIntegrationError.warnings` use the
  same adapter allowlist: stable engine labels and structured warning patterns
  are kept, while unknown/free-text warnings are dropped.
- `ASRIntegrationError` exposes `status`, `error_code` and the allowlisted
  `warnings`; it does not expose the full `ASRResult` or raw `error` text.
- `run_metadata` stores hashes/versions/timings, not audio paths or transcript
  text. `ASRResult.config` may contain `initial_prompt` text by configuration;
  treat it as configuration, not transcript output.
- These rules do not change the fact that `AGroupResult.extraction` and
  `pass_a_result` contain clinical text by design; the B payload boundary still
  applies to them.
- Detailed debugging should use an explicit, controlled mechanism. Do not
  re-enable raw exception logging in normal runs.
- A group does not decide B's final frontend payload privacy policy.

---

## 14. Examples (actual signatures)

### ASREngine standalone

```python
from core.asr import ASRConfig, ASREngine

engine = ASREngine(ASRConfig(model_size="base", device="cpu", compute_type="int8"))
result = engine.transcribe(r"<authorised-audio.wma>")

if result.status == "failed":
    print(result.error_code, result.error)
else:
    for segment in result.segments:
        print(segment.segment_id, segment.start, segment.end, segment.text)
```

### ASRResult → Adapter

```python
from core.asr_adapter import ASRIntegrationError, NoSpeechError, adapt_asr_result

try:
    adapted = adapt_asr_result(result)
except NoSpeechError as exc:
    print("no speech", exc.error_code, exc.warnings)
except ASRIntegrationError as exc:
    print("asr failed", exc.status, exc.error_code, exc.warnings)
else:
    clean_segments = adapted.segments   # list[dict]
```

### `audio_path` mode

```python
from core.extract_clinical_info import extract_clinical_info_result

result = extract_clinical_info_result(
    audio_path=r"<authorised-stitched.wav>",
    # asr_engine=None -> default ASREngine()
    # cleaner=None   -> B core.cleanup.clean_transcript
    # client=None    -> default OllamaClient()
)
```

### `clean_segments` mode

```python
result = extract_clinical_info_result(
    clean_segments=clean_segments,   # already cleaned by B
    client=client,
)
```

### Old entry

```python
from core.extract_clinical_info import extract_clinical_info

extraction = extract_clinical_info(clean_segments, client=client)
```

### Unpack and call B validate

```python
from core.validate import audit_extraction

extraction = result.extraction          # official ColoStructExtraction
audited = audit_extraction(extraction, clean_segments)
# audit_extraction mutates and returns the same object
```

`AGroupResult` itself must not be passed to `audit_extraction`.

---

## 15. Open decision M1

The following are **not decided** and this implementation does not choose them:

- who owns the ASR lifecycle in the production pipeline;
- whether ASR status/warnings/run_metadata are stored by A's `AGroupResult`,
  by B's pipeline, or delivered through a separate channel;
- whether an `asr_sink` callback is added.

Current fact: success/partial `AdaptedASR` metadata is only logged (counts) by
the service; ASR failed/no-speech details are available as `status`,
`error_code` and sanitised `warnings` on `ASRIntegrationError`; the full
`ASRResult` is not exposed on the exception. No ASR metadata outlet exists in
`AGroupResult`. The future approach must be agreed by both groups before code
changes.

---

## 16. Verified vs unverified

### Verified (historical test runs; this README does not claim they were rerun now)

- Fake ASR/fake LLM contract and service tests;
- real `core.pathology_schema` integration (9 tests);
- real cleanup + service + validate in-memory integration (7 tests);
- privacy marker tests proving synthetic exception text does not reach
  diagnostics, public exception attributes, logs, ASR warnings or HTTP errors;
  normal and exception adapter paths use the same warning allowlist
  (11 tests);
- P2/Pass A/B contract tests.

### Not verified

- real faster-whisper model load/transcription (`test_asr_real_model.py`
  requires `ASR_REAL_MODEL=1` / `ASR_REAL_TRANSCRIBE=1`);
- real Ollama/LLM output quality;
- real audio, real clinical quality, or clinical accuracy;
- B's official pipeline integration and payload;
- ASR metadata ownership / M1;
- `field_uncertainties` data.

Do not describe fake/stub tests as real model validation. Do not claim clinical
accuracy from these tests.

---

## 17. Test commands

The tests use the real backend schema. Run from the official checkout root, or
from the A-group development tree with both roots on `PYTHONPATH`.

```powershell
# Standard case: run from the official Colostruct checkout root.
$env:COLOSTRUCT_REPO_ROOT = (Resolve-Path .).Path
$env:PYTHONDONTWRITEBYTECODE = '1'
$python = Join-Path $env:COLOSTRUCT_REPO_ROOT '.venv\Scripts\python.exe'

# Development tree variant: replace the first line with the official checkout
# path and prepend this A-group tree to PYTHONPATH.
# $env:COLOSTRUCT_REPO_ROOT = '<path-to-Colostruct-checkout>'
# $env:PYTHONPATH = (Resolve-Path .).Path + ';' + $env:COLOSTRUCT_REPO_ROOT

# ASR-only unit tests (no backend schema dependency)
& $python -m unittest tests.test_asr_contract tests.test_asr_engine_fake tests.test_asr_offline -v
& $python -m unittest tests.test_asr_adapter -v

# LLM/service contract tests (real backend schema)
& $python -m unittest tests.test_a_group_llm_contract tests.test_service_result tests.test_result_contract tests.test_privacy_redaction -v

# Real schema / cleanup / validate integration (subprocess-isolated)
& $python -m unittest tests.test_service_real_schema tests.test_cleanup_validate_integration -v

# Existing real-schema AGroupResult wrapper
& $python -m unittest tests.test_result_backend_integration -v
```

When `COLOSTRUCT_REPO_ROOT` is unset, integration tests first try the parent of
the `tests` package; if no checkout containing `core/pathology_schema.py` is
found, they skip with an actionable message.

Real-model tests are intentionally skipped unless explicitly enabled:

```powershell
$env:ASR_RUN_REAL_MODEL = '1'         # R1 load smoke
$env:ASR_RUN_REAL_TRANSCRIBE = '1'    # R2 transcription
$env:ASR_REAL_AUDIO = '<authorised-audio-path>'
```

Real patient audio must only be used with authorisation. Dependency installation
and model downloads are not part of normal test runs.
