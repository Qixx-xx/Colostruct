# Project Brief — ColoStruct

## Product
ColoStruct is a local-first web app for a colorectal surgery doctor to turn ordered audio segments for one case into a reviewable draft of the 15 colorectal cancer pathology fields, with the transcript available for evidence checking.

Authoritative sources: `PRD-ColoStruct-MVP.md` and `TechDesign-ColoStruct-MVP.md` at repository root. Flag conflicts instead of silently choosing a source.

## MVP workflow
1. Upload multiple audio segments in their intended order; no browser recording component.
2. Stitch them on the backend with pydub into 16 kHz mono WAV, insert 0.5 seconds of silence between segments, and record segment offsets.
3. Transcribe with local faster-whisper and global timestamps.
4. Apply deterministic de-noising only; do not alter clinical meaning.
5. Use LLM preprocessing for slips of the tongue and temporal override (a later correction replaces an earlier statement).
6. Extract the 15 fields with supporting transcript spans and timestamps.
7. Run schema validation and a post-hoc evidence audit.
8. Let the doctor review and edit the transcript-linked draft, then export Markdown and JSON.

## The 15 fields
1. `tumour_site`
2. `operative_procedure`
3. `tumour_dimension`
4. `tumour_perforation`
5. `relation_to_anterior_peritoneal_reflection`
6. `plane_of_mesorectal_excision`
7. `histological_tumour_type`
8. `histological_tumour_grade`
9. `extent_of_invasion`
10. `lymphatic_and_venous_invasion`
11. `perineural_invasion`
12. `lymph_node_status`
13. `tumour_deposits`
14. `proximal_and_distal_margins`
15. `circumferential_margin`

Fields without transcript evidence must be `[not mentioned]`. Never invent clinical facts.

## In scope
- Ordered multi-segment upload; local ASR; layered preprocessing; 15-field extraction; schema/evidence audit.
- Dual-column review with timestamps/audio playback, visible flags, and editable fields.
- Markdown and JSON export from the reviewed draft, with exact watermark: `AI-assisted draft — not for clinical use without review`.
- Local SQLite for drafts, validation results, and export records.

## Out of scope and safety
- No SOAP notes, neurology-specific workflow, browser recording, EHR/eHR writes, or public hosting.
- No external transmission of clinical data, accounts, payments, or analytics tracking in MVP.
- Raw audio is not retained by default.
- Failed schema/evidence checks must remain visible; blocking failures prevent export.
- Human review is mandatory; AI output is a draft, not clinical sign-off.
