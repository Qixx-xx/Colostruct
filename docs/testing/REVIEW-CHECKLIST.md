# Review Checklist — ColoStruct

Do not mark work complete until relevant checks have actually passed or limitations are explicitly recorded.

## Scope and repository hygiene
- [ ] Change matches `PRD-ColoStruct-MVP.md` and `TechDesign-ColoStruct-MVP.md` v0.3.0.
- [ ] No unrelated files or another contributor's work were modified.
- [ ] No SOAP-note or neurology requirements were reintroduced.
- [ ] No secrets, patient identifiers, raw clinical audio, private logs, or clinical exports were committed.
- [ ] `MEMORY.md` reflects actual progress and blockers.

## Audio and transcription
- [ ] Ordered multi-segment upload is preserved; no browser recorder added.
- [ ] Stitching creates 16 kHz mono WAV with 0.5 s silence between segments.
- [ ] Segment offsets and global timestamps align.
- [ ] Stitching failures are visible and do not silently continue with a partial timeline.
- [ ] CER measured on a golden dataset; target ≤15%, with sample size and conditions reported.

## Preprocessing and extraction
- [ ] Rule cleanup is de-noising only and does not alter clinical meaning.
- [ ] Removed noise is logged.
- [ ] LLM preprocessing handles slips of the tongue and temporal override; override log retained.
- [ ] Output schema contains exactly the 15 fields specified in the PRD.
- [ ] Unsupported fields use exactly `[not mentioned]`.
- [ ] Each populated field has transcript evidence and a timestamp.
- [ ] Per-field precision/recall/F1 reported; overall field-level F1 target ≥85%.
- [ ] Schema failures, unsupported values, and contradictions are visibly flagged.

## Review and export
- [ ] Transcript/audio and editable 15-field draft are shown side by side.
- [ ] Reviewer can navigate to supporting or competing evidence.
- [ ] Export uses doctor-edited values.
- [ ] Markdown and JSON are valid and represent the same reviewed draft.
- [ ] Both include exact watermark: `AI-assisted draft — not for clinical use without review`.
- [ ] Blocking validation/evidence-audit issues prevent export.

## Privacy and safety
- [ ] Raw audio is not retained by default.
- [ ] SQLite stores intended local drafts, validation results and export records only.
- [ ] Logs are de-identified.
- [ ] No clinical data sent externally without explicit approval and an approved policy.
- [ ] No EHR/eHR write or submit action exists; any adapter remains a non-writing stub.
- [ ] No public hosting, accounts, payments, analytics tracking, or other excluded scope was added without approval.

## Final evidence
- [ ] Files changed and purpose.
- [ ] Commands/tests actually run, including failures.
- [ ] Browser/manual workflow results if app is runnable.
- [ ] Metrics measured and dataset limitations.
- [ ] Remaining risks, TBD decisions and rollback considerations.
