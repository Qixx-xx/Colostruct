# Memory

Keep this file brief. Distinguish design decisions from implementation evidence.

## Current State
- Current task: Align project setup documentation with PRD and Technical Design v0.3.0.
- Current phase: Requirements/design documentation alignment.
- Product direction: A reviewable draft of 15 colorectal cancer pathology fields from ordered multi-segment audio; no SOAP output.
- Next step: Apply the updated documentation, review the diff, then validate the local environment and implement the pipeline in testable stages.
- Status warning: This documentation update does **not** prove the app, pipeline, evaluation harness, or tests are implemented or working.

## Decisions from PRD / Technical Design v0.3.0 (2026-10-20)
- Output is the 15-field Colorectal cancer reporting checklist, not SOAP.
- Input is ordered multi-segment upload only; no in-browser recording.
- Stitch with pydub to 16 kHz mono WAV, 0.5 s silence between segments, and per-segment offsets.
- Use local faster-whisper ASR with global timestamps; calibrate model/runtime settings empirically.
- Rule layer performs de-noising only. LLM preprocessing handles slips of the tongue and temporal override.
- Extract 15 fields with evidence and timestamps; unsupported fields are `[not mentioned]`.
- Post-hoc audit checks schema/evidence and flags contradictions; it must not silently approve unsupported values.
- Export reviewed Markdown and JSON with `AI-assisted draft — not for clinical use without review`.
- Use local SQLite for drafts, validations, and export records. Raw audio is not retained by default.
- No EHR/eHR writes, public hosting, accounts, payments, analytics tracking, or external transmission of clinical data in MVP.

## Open Decisions / Blockers
- Exact local open-source LLM and runtime: TBD; decide based on target machine RAM/VRAM and measured quality.
- Segment-order guarantees and mixed-device audio normalization: verify during implementation.
- ≤15-second latency target: measure on target hardware before claiming success.
- Golden dataset size and per-field sample counts: define with clinical owner; use approved/de-identified or synthetic data.
- Authentication/audit trail for a future multi-user beta: outside MVP; revisit only with approval.
- Environment startup, dependencies, and tests have not been verified by this documentation update.

## Completion
- [x] PRD / Technical Design v0.3.0 reviewed for documentation alignment
- [x] Product direction and constraints recorded
- [ ] Updated files applied and diff reviewed in repository
- [ ] Local startup verified
- [ ] Audio stitching and offsets tested
- [ ] ASR CER and extraction F1 evaluated
- [ ] Watermark and blocking-audit behavior tested
