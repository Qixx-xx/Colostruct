# Tech Stack — ColoStruct

**Source of truth:** `TechDesign-ColoStruct-MVP.md` v0.3.0. Choices below are design decisions, not proof of an installed or tested environment.

## Stack
| Area | Choice | Notes |
|---|---|---|
| Language | Python 3.11 | Target version |
| UI | Streamlit | Single-process app; ordered upload and dual-column review |
| Audio | pydub + ffmpeg | 16 kHz mono WAV; 0.5 s silence between segments; cumulative offsets |
| ASR | local faster-whisper | Global/word-level timestamps; model settings require calibration |
| Rule cleanup | Python regex/dictionaries | De-noising only; no semantic rewrite |
| LLM preprocessing | Local open-source model | Slip-of-the-tongue correction and temporal override; exact model/runtime TBD |
| Extraction | Pydantic / JSON Schema-constrained LLM output | Exactly 15 pathology fields with evidence |
| Validation | Python schema checks + post-hoc evidence audit | Flag unsupported values and contradictions; never silently rewrite clinical content |
| Storage | SQLite + local filesystem | Drafts, validation results, export records; raw audio not retained by default |
| Export | Markdown + JSON | Reviewed values and exact AI-assisted draft watermark |
| Deployment direction | Local workstation / institutional intranet; Docker in Technical Design | No public hosting in MVP |

## Windows setup (proposed; not yet run)
From repository root:
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
.\.venv\Scripts\python.exe -m pytest
```
Install ffmpeg separately and ensure it is available on `PATH`. Run pytest only if the suite exists.

## Pipeline boundaries
1. Preserve upload order; if stitching fails, show an error and do not process a partial timeline.
2. Local ASR returns a timestamped transcript.
3. Rule cleanup removes only defined noise and logs removals.
4. LLM preprocessing corrects slips of the tongue and applies temporal override; retain the override log.
5. Extract exactly these fields: `tumour_site`, `operative_procedure`, `tumour_dimension`, `tumour_perforation`, `relation_to_anterior_peritoneal_reflection`, `plane_of_mesorectal_excision`, `histological_tumour_type`, `histological_tumour_grade`, `extent_of_invasion`, `lymphatic_and_venous_invasion`, `perineural_invasion`, `lymph_node_status`, `tumour_deposits`, `proximal_and_distal_margins`, `circumferential_margin`.
6. Audit schema, evidence existence, field rules, and override decisions. Blocking failures prevent export.
7. Review and edit before exporting; exported values must reflect doctor edits.

## PRD launch targets
- ASR CER ≤15% on mixed Cantonese + English + medical abbreviations.
- Field-level F1-Score ≥85% for the 15 specified pathology fields.
- End-to-end latency ≤15 seconds for 1–3 minutes of audio; measure on target hardware.
- 100% of fields without transcript evidence render as `[not mentioned]`.
- Exact watermark: `AI-assisted draft — not for clinical use without review`.

## Privacy and unresolved decisions
- Use de-identified/synthetic data unless an approved environment explicitly permits otherwise.
- No external transmission of clinical data and no EHR/eHR writes.
- Exact LLM model, runtime, quantization, dependency versions, target hardware, and achievable latency remain TBD.
- Do not commit raw audio, patient identifiers, clinical exports, secrets, or sensitive logs.
