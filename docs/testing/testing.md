# Testing — ColoStruct

## Rules
- Use de-identified or synthetic audio/transcripts unless an approved environment explicitly permits otherwise.
- Do not claim a target is met until the test was run; report sample size and conditions.
- Validation failures must be visible. Blocking audit issues prevent export.
- This is a test plan, not evidence that the application or tests currently exist.

## Proposed Windows commands
Run from repository root and verify paths first:
```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests\test_audio_merge.py
```
The test filename is illustrative until the actual suite is inspected. Do not report success unless the command was actually run.

## Functional test matrix
| Area | Test | Expected result |
|---|---|---|
| Ordered upload | Upload 2+ synthetic segments | Intended order is preserved and visible |
| Stitching | Inspect format, duration, silence, offsets | 16 kHz mono WAV; 0.5 s silence between segments; offsets align |
| Stitching failure | Provide corrupt/unsupported segment | Clear error/retry; no silent partial processing |
| ASR/timestamps | Compare with reference transcript | Global timestamps align; compute CER |
| CER target | Evaluate golden dataset | CER ≤15%; report sample size and language mix |
| Rule cleanup | Include fillers, duplicates, empty spans, negation and measurements | Only permitted noise removed; meaning preserved; removals logged |
| LLM preprocessing | Include a spoken self-correction | Later statement overrides earlier one; override log retained |
| 15-field extraction | Compare with clinician reference labels | All 15 fields represented; populated values have evidence/timestamps; absent fields are `[not mentioned]` |
| Extraction metric | Compute per-field precision/recall/F1 | Field-level F1 target ≥85%; report each field and sample counts |
| Schema validation | Missing/unknown keys, wrong types, invalid values | Invalid output flagged, not silently accepted |
| Evidence audit | Populate a field with no transcript support | Value flagged; audit does not rewrite it |
| Contradictions | Include competing statements | Competing evidence and review flag displayed |
| Review UI | Inspect transcript/audio and editable draft side by side | Evidence navigation works and flags are visible |
| Human edits | Edit a field before export | Export reflects the edited value |
| Export | Generate Markdown and JSON | Both valid and based on the same reviewed draft |
| Watermark | Inspect both formats | Both include `AI-assisted draft — not for clinical use without review`; cannot be omitted |
| Blocking issues | Trigger blocking validation/audit failure | Export is blocked with a clear explanation |
| Privacy/retention | Inspect database, files and logs | Raw audio not retained by default; logs de-identified; no external send/EHR write |
| Runtime failure | Simulate timeout/malformed output | Clear failure state; no invented facts; blocking issues prevent export |

## PRD targets (targets, not achieved results)
- ASR CER ≤15%.
- Field-level F1-Score ≥85% for the 15 pathology fields.
- End-to-end latency ≤15 seconds for 1–3 minutes of stitched audio, measured on target hardware.
- 100% of fields without transcript evidence rendered as `[not mentioned]`.
- ≥50% reduction in repetitive documentation time, assessed through doctor feedback if that study is performed.

## Golden dataset
Create a clinician-reviewed reference set including mixed Cantonese/English, medical abbreviations, corrections, absent fields and contradictions. Use approved/de-identified or synthetic samples. Report dataset size, per-field sample counts, model/runtime settings and limitations. A tiny anti-regression set is not sufficient evidence of clinical readiness.

## Completion report
List tests/commands actually run and results, metrics actually measured, browser checks if applicable, known gaps, untested cases, and any remaining blocking issue.
