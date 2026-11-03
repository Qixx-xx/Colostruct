# AGENTS.md — ColoStruct

## Source of truth
Use `PRD-ColoStruct-MVP.md` indocs/product/PRD-ColoStruct-MVP.md and `TechDesign-ColoStruct-MVP.md` in docs/tech/TechDesign-ColoStruct-MVP.md as the authoritative product and architecture sources. This is a colorectal pathology-report drafting project, **not** a SOAP-note or neurology project.

## Product pipeline
Ordered multi-segment audio upload → backend stitching with pydub (16 kHz mono WAV, 0.5 s silence between segments, per-segment offsets) → local faster-whisper ASR with global timestamps → deterministic de-noising → LLM preprocessing for slips of the tongue and temporal override → extraction of the 15 pathology fields → schema validation and post-hoc evidence audit → dual-column human review → Markdown and JSON export.

## Required 15 fields
`tumour_site`, `operative_procedure`, `tumour_dimension`, `tumour_perforation`, `relation_to_anterior_peritoneal_reflection`, `plane_of_mesorectal_excision`, `histological_tumour_type`, `histological_tumour_grade`, `extent_of_invasion`, `lymphatic_and_venous_invasion`, `perineural_invasion`, `lymph_node_status`, `tumour_deposits`, `proximal_and_distal_margins`, `circumferential_margin`.

## Non-negotiable constraints
- A field without transcript evidence must be exactly `[not mentioned]`. Never invent clinical facts.
- Rule-based cleanup is de-noising only (fillers, duplicated fragments, empty spans, explicitly specified surface-form normalization). It must not rewrite, summarize, reorder, or infer clinical meaning.
- LLM preprocessing handles slips of the tongue and temporal override (later correction supersedes earlier statement); retain an override log.
- Every populated field needs transcript evidence and a timestamp. The post-hoc audit flags unsupported values and contradictions; it does not rewrite clinical content. Blocking failures must remain visible and prevent export.
- The exact export watermark is `AI-assisted draft — not for clinical use without review`.
- Export only the clinician-reviewed values. No write/submit to hospital EHR/eHR; any adapter remains a non-writing stub.
- Raw audio is not retained by default. SQLite is for local drafts, validation results, and export records.
- Use de-identified or synthetic data unless an approved environment explicitly permits otherwise. Do not commit secrets, patient identifiers, raw audio, clinical exports, or sensitive logs.
- No public hosting, external transmission of clinical data, accounts, payments, or analytics tracking in the MVP unless separately approved.

## Windows setup (proposed; not yet verified)
Run from repository root. Target Python version is 3.11.
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
.\.venv\Scripts\python.exe -m pytest
```
Install ffmpeg separately and ensure it is on `PATH`. Only run pytest if the test suite exists. Do not claim commands or tests passed unless actually run.

## Read first
- `PRD-ColoStruct-MVP.md`
- `TechDesign-ColoStruct-MVP.md`
- `MEMORY.md`
- `project_brief.md`
- `tech_stack.md`
- `testing.md`
- `REVIEW-CHECKLIST.md`

## Completion
Inspect the current repository and preserve unrelated changes. Re-read edited files and review the diff. Report actual changes, checks run, blockers, and limitations honestly. Documentation alignment does not mean the app has been implemented or tested.
