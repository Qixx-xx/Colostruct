# ColoStruct — MVP Product Requirements Document

**Project:** Colorectal Surgery Outpatient AI Doctor Assistant ("ColoStruct")
**Owner:** Project-Based CST & AI Foundations team (client: colorectal surgery doctor, Hong Kong public hospital)
**Status:** Draft for build — architecture revised 2026-10-20
**Version:** 0.3.0 (supersedes the SOAP-based v0.2)
**Audience / User level:** **C** — reads Markdown and JSON fluently and understands clinical and product terminology, but is not expected to run or debug the stack unassisted. All three project documents (PRD, Technical Design, Flowchart) use the same level **C**.

---

## 1. Product Overview

**Tagline:** Upload your dictation — get a reviewable, watermarked colorectal pathology report draft, not a transcript to rewrite.

ColoStruct is a local-first web app for colorectal surgery outpatient and pathology documentation. The doctor uploads the audio segments recorded for one case, and the app returns a **structured draft of the 15 key colorectal cancer pathology fields**, side by side with the transcript, for review and one-click export.

End-to-end pipeline (MVP):

```
ordered multi-segment audio
  -> backend stitching (pydub, 16 kHz mono WAV, 0.5 s silence between segments)
  -> multilingual ASR (Whisper-class, global timestamps)
  -> rule-layer cleaning (spoken fillers / invalid fragments only)
  -> LLM preprocessing (slip-of-the-tongue correction + temporal override: later statement wins)
  -> LLM extraction of the 15 colorectal pathology fields
  -> rule + schema validation and evidence audit
  -> dual-column review
  -> one-click export (Markdown + JSON, AI-assisted draft watermark)
```

**What changed in this revision.** The product no longer produces a SOAP-framework note. The target is the **Colorectal cancer reporting checklist** definition supplied by the client. Two follow-up decisions are folded in:

1. **Layered preprocessing.** The deterministic rule layer performs *de-noising only* (filler words, duplicated fragments, empty spans). Slip-of-the-tongue correction and temporal overrides are done by the **LLM**.
2. **Stitching replaces recording.** Multiple segmented audio files are uploaded in order and merged on the backend. The in-browser recording component is **removed**, and boundary handling is no longer a separate processing step: the stitched timeline and its per-segment offsets cover segment edges on their own.

**Field-count note.** The task brief said "14 fields"; the client's checklist lists **15**. The checklist is authoritative, so every document states **15 fields** and this correction is recorded here for traceability.

---

## 2. Who It's For

- **Ideal user:** A busy colorectal surgery doctor in a Hong Kong public hospital.
- **Use case:** The doctor dictates specimen macro descriptions, operative details, and pathology findings, then needs a standardized structured pathology record with minimal extra typing.
- **Environment:** Clinic desktop or laptop browser, inside the hospital network, working under HA standards.
- **Language reality:** Cantonese colloquial speech mixed with English medical abbreviations in a single dictation.
- **Documentation reality:** Dictation for one case often arrives in **several short segments** recorded at different times (initial macro description in the morning, addendum after histology review later the same day).

**Pain points**

1. Dictation exists, but the structured document still has to be assembled by hand.
2. The same 15 checklist fields are re-typed for every case, with high cognitive load on staging and margin details.
3. Mixed Cantonese/English/abbreviation dictation destabilises generic ASR.
4. Later corrections are spoken out of order ("actually the margin is 2 mm, not 5"), and a naive transcript keeps both versions.
5. Anything that is not dictated must be visibly absent, not guessed — clinical safety.

---

## 3. The Problem We're Solving

A colorectal pathology report is not a narrative. It is a **checklist of 15 items** that must be complete, internally consistent, and traceable to what the doctor actually said. Today the doctor dictates and then re-keys those items into a structured form, or leaves them in free text where downstream readers cannot rely on them.

ColoStruct removes the re-keying step: it turns the dictation into a **draft 15-field record**, keeps the transcript visible for verification, and never invents a value.

The 15 fields, as defined by the client's **Colorectal cancer reporting checklist**:

| # | Field key | Field label |
| --- | --- | --- |
| 1 | `tumour_site` | Tumour site |
| 2 | `operative_procedure` | Operative procedure |
| 3 | `tumour_dimension` | Tumour dimension |
| 4 | `tumour_perforation` | Tumour perforation |
| 5 | `relation_to_anterior_peritoneal_reflection` | Relation of tumour to anterior peritoneal reflection |
| 6 | `plane_of_mesorectal_excision` | Plane of mesorectal excision |
| 7 | `histological_tumour_type` | Histological tumour type |
| 8 | `histological_tumour_grade` | Histological tumour grade |
| 9 | `extent_of_invasion` | Extent of invasion |
| 10 | `lymphatic_and_venous_invasion` | Lymphatic and venous invasion |
| 11 | `perineural_invasion` | Perineural invasion |
| 12 | `lymph_node_status` | Lymph node status |
| 13 | `tumour_deposits` | Tumour deposits |
| 14 | `proximal_and_distal_margins` | Proximal and distal margins |
| 15 | `circumferential_margin` | Circumferential margin |

---

## 4. User Journey

1. The doctor finishes a case and selects the audio segments recorded for it (e.g. three segments for one specimen).
2. The doctor **uploads the segments in order** in the web app. The UI preserves the order; no recording happens in the browser.
3. The backend **stitches the segments into one audio stream** (16 kHz mono WAV), inserting 0.5 s of silence between segments, and reports the segment offsets.
4. ASR transcribes the stitched audio with **global timestamps** covering the whole stream.
5. The rule layer removes spoken fillers and invalid fragments only — clinical content, hesitations, and repetitions are left untouched so the LLM can interpret them.
6. The LLM **corrects slips of the tongue and resolves temporal conflicts** ("no, make that 2 mm") so the latest statement wins.
7. The LLM **extracts the 15 checklist fields** into a structured draft and marks absent items as `[not mentioned]`.
8. The draft is validated against the schema, and an evidence audit checks each populated field against the transcript.
9. The doctor reviews the dual-column view: transcript (with timestamps, audio playback) on the left, the 15-field draft form on the right; low-evidence fields are flagged.
10. The doctor edits what is needed and exports **Markdown + JSON** with the AI-assisted draft watermark. Nothing is written to any hospital system.

**Success story:** As a colorectal surgery doctor, I want to upload my case dictation and get a complete 15-field draft I can verify against the transcript in seconds, so that repetitive pathology documentation stops eating my clinic time.

---

## 5. MVP Features (P0)

### Feature 1 — Ordered multi-segment audio upload with automatic backend stitching

- **User Story:** As a colorectal surgery doctor, I want to upload the several audio segments I recorded for one case in order, so that I do not need to re-record or merge anything myself.
- **Success Criteria:**
  - [ ] The upload control accepts multiple audio files per case and preserves the doctor's submission order
  - [ ] Submitting starts a backend stitch that produces a single 16 kHz mono WAV with 0.5 s of silence inserted between segments
  - [ ] The app reports each segment's offset in the stitched timeline
  - [ ] Supported containers are validated on upload (`.wav`, `.mp3`, `.m4a`, `.wma`); unsupported files are rejected with a clear message
  - [ ] A failed stitch surfaces a retry path and never silently drops a segment
- **Priority:** P0 (Critical)

### Feature 2 — Multilingual ASR with global timestamps

- **User Story:** As a colorectal surgery doctor, I want my mixed Cantonese/English dictation transcribed with timestamps across the whole stitched recording, so that I can verify the draft against the audio.
- **Success Criteria:**
  - [ ] Whisper-class multilingual model transcribes the stitched stream with word/segment timestamps
  - [ ] Timestamps are **global** to the stitched audio, so any segment can be located and replayed
  - [ ] Transcript is shown in the review UI before extraction completes
  - [ ] Mixed Cantonese + English + medical abbreviations remain readable; CER ≤15% at launch
- **Priority:** P0 (Critical)

### Feature 3 — ASR optimization and domain adaptation (rule-layer de-noising)

- **User Story:** As a colorectal surgery doctor, I want filler words and noise out of the way, without losing any clinical content, so that the text I read is clean but complete.
- **Success Criteria:**
  - [ ] A deterministic rule layer removes spoken fillers, duplicated fragments, and empty spans
  - [ ] The rule layer performs **de-noising only** — it does not rewrite, summarise, or reorder clinical meaning
  - [ ] A colorectal hotword dictionary biases the ASR toward specialty terms (mesorectal, anterior peritoneal reflection, circumferential margin, deposits)
  - [ ] Rule-layer changes are logged so a reviewer can see what was removed
- **Priority:** P0 (Critical)

### Feature 4 — LLM-driven extraction of the 15 colorectal pathology fields

- **User Story:** As a colorectal surgery doctor, I want the dictation turned into the 15 checklist fields, so that I get a structured record instead of a paragraph to reorganize.
- **Success Criteria:**
  - [ ] The LLM preprocessing stage corrects slips of the tongue and applies **temporal override** (a later statement replaces an earlier one)
  - [ ] The LLM extracts all 15 fields into the schema: `tumour_site`, `operative_procedure`, `tumour_dimension`, `tumour_perforation`, `relation_to_anterior_peritoneal_reflection`, `plane_of_mesorectal_excision`, `histological_tumour_type`, `histological_tumour_grade`, `extent_of_invasion`, `lymphatic_and_venous_invasion`, `perineural_invasion`, `lymph_node_status`, `tumour_deposits`, `proximal_and_distal_margins`, `circumferential_margin`
  - [ ] Every field that was not dictated is rendered as `[not mentioned]` — never a plausible guess
  - [ ] Each populated field carries the supporting transcript span and its timestamp
  - [ ] Field-level F1-Score ≥85% for the 15 fields on the golden dataset
- **Priority:** P0 (Critical)

### Feature 5 — Hallucination guard, schema validation, and evidence audit

- **User Story:** As a colorectal surgery doctor, I want confidence that every value came from my own dictation, so that I can sign off without re-reading every line.
- **Success Criteria:**
  - [ ] The draft is validated against the 15-field schema before it is shown (types, allowed values, required-vs-absent)
  - [ ] A rule-based audit checks that each populated field has a matching transcript span; unmatched values are flagged, not silently kept
  - [ ] Contradictory or unresolved statements surface as review flags with the competing spans
  - [ ] The audit runs as a post-hoc check over the draft and never rewrites clinical content
  - [ ] Guardrail: 100% of fields without transcript evidence render as `[not mentioned]`
- **Priority:** P0 (Critical)

### Feature 6 — Dual-column review and one-click export

- **User Story:** As a colorectal surgery doctor, I want to compare the transcript against the draft and export the result in one click so that the review step costs me seconds, not minutes.
- **Success Criteria:**
  - [ ] Both columns stay visible and scroll independently on the clinic desktop browser
  - [ ] Clicking a flagged field jumps to the matching audio/transcript span and plays it
  - [ ] Edits made in the review column are what get exported
  - [ ] Export produces valid Markdown and valid JSON from the same reviewed draft
  - [ ] The exported artifact carries the AI-assisted draft watermark and cannot be exported without it
  - [ ] Nothing is written to any hospital system; export is a user-initiated download only
- **Priority:** P0 (Critical)

### Nice to Have (If Time Allows)

- **Field-level history:** a session list of previous drafts with their saved Markdown/JSON.
- **Tablet/mobile-responsive review layout:** the MVP targets a clinic desktop/laptop browser; responsive review is an extension.
- **ICD-10 suggestion chips** on the histological type and site fields, aligned with HA standards.
- **Segment-level audio player:** replay a single uploaded segment rather than the stitched stream.
- **Batch mode:** process several cases queued from the same upload session.
- **Hotword dictionary editor:** let the doctor maintain the colorectal term list without editing code.

---

## 6. Metrics

**Launch goals**

| Metric | Target | How measured |
| --- | --- | --- |
| ASR accuracy | CER ≤15% in mixed Cantonese + English + medical abbreviation contexts | Python CER over the golden dataset |
| **Field extraction quality** | **Field-level F1-Score ≥85% for the 15 specified pathology fields** | Python per-field precision/recall/F1 against the clinician reference standard |
| Extraction maturity path | ≥95% field-level F1 long-term | Same harness, larger dataset |
| End-to-end latency | ≤15 seconds for 1–3 minutes of stitched audio | Instrumented timing from upload to draft |
| Absence discipline | 100% of fields with no transcript evidence rendered as `[not mentioned]` | Automated check on every draft |
| Review efficiency | ≥50% reduction in repetitive documentation time | Doctor self-report at mid-term review |

Per-field F1 is reported for all 15 fields, with `tumour_site`, `lymph_node_status`, `proximal_and_distal_margins`, and `circumferential_margin` tracked as the four critical fields.

**Guardrails (must never regress)**

- No fabricated clinical value, in any field, at any confidence level.
- No export without the AI-assisted draft watermark.
- No write path to any hospital system.
- Raw audio is not retained by default; session logs are de-identified.

---

## 7. Look & Feel

**Overall:** Fast, professional, easy to understand. Zero learning cost for a doctor who has never seen the tool.

**Review screen (primary screen)**

- **Left column — Transcript:** the stitched transcript with global timestamps, a single audio player for the stitched stream, and a timestamp rail. Fields with evidence highlight the corresponding span when focused.
- **Right column — 15-field draft:** the checklist rendered as a form in clinical review order: tumour & specimen (fields 1–6), histology (7–11), nodes & deposits (12–13), margins (14–15).
- **Field states:** *populated with evidence* (normal), *low evidence / flagged* (amber, with the competing spans shown), *`[not mentioned]`* (grey, read-only until the doctor types a value), *doctor-edited* (marked so the doctor can see they overrode the draft).
- **Header:** case identifier (de-identified), segment count, stitched duration, watermark "AI-assisted draft — not for clinical use without review".

**Behaviour and states**

- Empty state: drop zone with "Upload the audio segments for one case, in the order they were recorded."
- Loading: staged progress — stitching → transcribing → correcting → extracting → validating — with the transcript appearing as soon as ASR finishes.
- Error: a failed stage shows what succeeded, keeps the transcript visible, and offers retry; the app never shows a fabricated draft.
- Export: one action produces both files; the watermark is embedded in the Markdown header and in the JSON metadata.

**Typography and layout:** clean clinical neutral palette, one accent colour for interactive elements, generous whitespace, monospace for timestamps and field keys, no decorative animation.

---

## 8. Technical Considerations

- **Platform:** Web app, Python + Streamlit, hospital-network local deployment.
- **Audio stitching:** the backend merges uploaded segments in submission order with `pydub` into a single 16 kHz mono WAV, inserting 0.5 s of silence at each boundary, and records the cumulative offset of every segment.
- **ASR:** multilingual Whisper-class model with word/segment timestamps, plus a colorectal hotword dictionary.
- **Preprocessing split:** rule layer = de-noising only; LLM = slip-of-the-tongue correction, temporal override, and field extraction. This split is deliberate, so that clinical meaning is never rewritten by a regex.
- **Structured output:** the LLM must return JSON conforming to the 15-field pathology schema, so the draft is machine-checkable before display.
- **Validation:** schema validation plus a rule-based evidence audit over transcript spans; failed checks become review flags rather than silent edits.
- **Storage:** local SQLite for drafts, validations, and export records; audio is not retained by default.
- **Privacy:** de-identified simulated data during development; no live hospital-system connection; the EHR/eHR adapter stays contract-only.
- **Known risks:**
  1. ASR stability on Cantonese colloquialisms mixed with complex English abbreviations.
  2. Stitch quality when segments were recorded with different devices or sample rates (resampling to 16 kHz mono is mandatory).
  3. Extraction ambiguity where dictation is implicit rather than explicit (e.g. a margin described only as "close").
  4. Latency: stitching + ASR + two LLM passes must stay inside 15 seconds for a 1–3 minute case.

---

## 9. AI Scope

**AI is used for**

- Multilingual ASR of the stitched audio.
- Slip-of-the-tongue correction and temporal override on the transcript.
- Extraction of the 15 colorectal pathology fields from the corrected transcript.
- Flagging low-evidence fields for human review.

**AI is not used for**

- Deciding clinical meaning, staging, or treatment.
- Writing anything to a hospital system.
- Filling a field that was not dictated.

**Output contract:** one JSON object per case whose payload is the 15 fields plus provenance:

```json
{
  "caseId": "de-identified-id",
  "segments": [
    { "index": 0, "sourceFile": "segment-1.wav", "offsetSeconds": 0.0 },
    { "index": 1, "sourceFile": "segment-2.wav", "offsetSeconds": 92.5 }
  ],
  "audio": { "sampleRate": 16000, "channels": 1, "stitchSilenceSeconds": 0.5 },
  "fields": {
    "tumour_site": { "value": "mid rectum", "evidence": [{ "start": 12.4, "end": 15.1 }], "status": "populated" },
    "operative_procedure": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "tumour_dimension": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "tumour_perforation": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "relation_to_anterior_peritoneal_reflection": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "plane_of_mesorectal_excision": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "histological_tumour_type": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "histological_tumour_grade": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "extent_of_invasion": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "lymphatic_and_venous_invasion": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "perineural_invasion": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "lymph_node_status": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "tumour_deposits": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "proximal_and_distal_margins": { "value": "[not mentioned]", "evidence": [], "status": "absent" },
    "circumferential_margin": { "value": "[not mentioned]", "evidence": [], "status": "absent" }
  },
  "watermark": "AI-assisted draft",
  "reviewState": "unreviewed"
}
```

**Evaluation:** agreed method is Python-based ASR CER plus per-field F1 over a golden dataset of real de-identified cases. Scenarios to verify:

- Direct: clear, well-formed dictation of a field.
- Indirect: implicit findings that require structuring rather than verbatim copying.
- Negative: content that was never said must render `[not mentioned]`.
- Temporal: a later correction must override an earlier statement.
- Multi-segment: a field whose only evidence sits in the second or third uploaded segment.
- Failure: ASR or LLM unavailable → keep the transcript visible and offer retry; never fabricate a draft.

**Telemetry / Cost:** session logs must be de-identified; audio is not retained by default. Cost ceiling is TBD and depends on the local-GPU versus hosted-API decision. Fallback behaviour: if the LLM step fails, the user still gets the transcript and a clear failure state.

---

## 10. Open Questions

1. **Local vs hosted inference:** does the clinic allow hosted API calls for de-identified text, or is local GPU inference mandatory from day one?
2. **Cost ceiling per case:** what is the acceptable spend per stitched case if hosted APIs are used (stitching + ASR + correction pass + extraction pass)?
3. **Field extraction accuracy baseline:** which of the 15 fields is hardest to extract without the LLM, and where should the deterministic rule layer stop so that rule and LLM responsibilities stay clean?
4. **Multi-device stitching:** what is the acceptable behaviour when segments differ in sample rate, channel count, or loudness?
5. **Segment boundary wording:** how should the transcript present the inserted silence (visible marker vs silent gap) so the doctor knows segments were stitched?
6. **Temporal override policy:** when two statements conflict and neither is clearly "later", should the app flag both, or prefer the most explicit one?
7. **EHR adapter scope:** the adapter is contract-only in the MVP — which future integration (file drop vs API) should the contract anticipate?
8. **Ready for Outpatient?** How smooth is the dual-column review for a full 15-field case in a real clinic window?
9. **Ready with current quality?** Is the documentation quality sufficient for clinical use, and what does the doctor still have to edit by hand?
10. **Ready to save time?** What is the measured working-time reduction per case once the doctor has used the tool for a week?
11. **Hotword dictionary ownership:** who maintains the colorectal term list, and how often is it reviewed?
12. **Failure transparency:** should a failed stage be logged in the exported artifact, so a reader knows the draft may be incomplete?

---

## 11. Quality Standards

**What this app will NOT accept:**

- Placeholder content in a delivered artifact ("Lorem ipsum", dummy clinical values presented as real output).
- Invented clinical content — a field with no transcript evidence must read `[not mentioned]`, never a plausible guess.
- A value that carries no supporting transcript span.
- A draft that shows a SOAP-style narrative instead of the 15 checklist fields.
- An export path that can drop the AI-assisted draft watermark.
- Any write to a hospital system, or any real patient data in prototype testing.
- Silent segment loss: every uploaded segment must be present in the stitched timeline.
- Features that half-work: a listed P0 either works end-to-end or is cut from the release.
- Skipping the agreed desktop browser test before Demo Day.

*These standards are enforced by the AI coding assistant through the project's build and review workflow.*

---

## 12. Out of Scope (Not in MVP)

- Write-back to the Hong Kong Hospital Authority EHR/eHR production database (the adapter is a contract stub only).
- Any live hospital-system connection, including read-only integrations.
- Browser-side audio recording.
- Any separate processing step for segment boundaries — boundaries are covered by the stitched timeline and its offsets.
- Multi-specialty expansion beyond colorectal surgery outpatient and pathology workflow.
- Autonomous diagnosis, staging decisions, or treatment recommendations.
- Real patient data in development or demo environments.

---

## 13. Definition of Done

- [ ] A doctor can upload the 2–4 segments of a real case, in order, and get one stitched timeline with correct per-segment offsets.
- [ ] ASR produces a global-timestamped transcript over the stitched stream.
- [ ] The rule layer removes fillers without deleting clinical content, and logs what it removed.
- [ ] The LLM corrects slips of the tongue and applies temporal override, demonstrably on a multi-segment and a "later correction" test case.
- [ ] All 15 fields appear in the draft; absent items render as `[not mentioned]`.
- [ ] Every populated field carries a transcript span and timestamp, and the evidence audit flags mismatches.
- [ ] The dual-column review screen meets the Feature 6 success criteria on the clinic desktop browser.
- [ ] Export produces valid Markdown and valid JSON, both watermarked.
- [ ] Field-level F1 ≥85% for the 15 fields on the golden dataset; CER ≤15%.
- [ ] End-to-end latency ≤15 seconds for a 1–3 minute case.
- [ ] No hospital-system write path exists in the codebase.

---

## 14. Next Steps

1. Freeze the 15-field schema module and its JSON contract with the client (field keys, allowed values, absent-state rules).
2. Build the stitching utility and validate it against the client's real multi-segment cases (variable device, variable sample rate).
3. Establish the golden dataset and the CER + per-field F1 harness before tuning prompts.
4. Implement the rule layer with de-noising scope only, and record its removal log.
5. Implement the LLM preprocessing + extraction passes against the checklist prompt chain.
6. Build the dual-column review UI with field states, evidence traceback, and playback.
7. Run the desktop browser test and the mid-term review with the doctor.
8. Target dates: **10.27** runnable MVP, **11.10** user feedback / mid-term review, **12.01** beta, **12.08** Demo Day, **12.15** reflection and archive.

---

## 15. Handoff

**Source files**

- This PRD: `docs/PRD-ColoStruct-MVP.md` (English, authoritative)
- Q&A-form PRD: `outputs/colostruct-mvp-prd.md`
- Technical Design: `docs/TechDesign-ColoStruct-MVP.md`
- Flowchart / pipeline description: `outputs/flowchart-colostruct-reporting.md` (+ `outputs/flowchart-colostruct-reporting.png`)
- Client checklist (field authority): `Sample2/Colorectal cancer reporting checklist.pdf`
- Superseded drafts: `docs/PRD-ColoStruct-MVP.zh.md`, `docs/PRD-ColoStruct-MVP.en.md` (SOAP-based, retained for history)

**Build order**

1. `core/audio_merge.py` — stitching + offsets.
2. `core/transcribe.py` — ASR with global timestamps + hotwords.
3. `core/cleanup.py` — rule-layer de-noising only.
4. `core/pathology_schema.py` — the 15-field schema and JSON contract.
5. LLM preprocessing pass — slip-of-the-tongue correction + temporal override.
6. LLM extraction pass — 15 fields with evidence spans.
7. `core/validate.py` — schema validation + post-hoc evidence audit.
8. Streamlit review UI — dual column, field states, export.

**Handoff risks**

- The 15-field schema must be frozen *before* prompt tuning, or the F1 harness is meaningless.
- Stitching must be validated on the client's real multi-device segments, not just synthetic files.
- The rule/LLM split is a hard boundary: any rule that rewrites meaning breaks the safety story.

```json
{
  "schemaVersion": 1,
  "documentType": "prd",
  "projectName": "ColoStruct – Colorectal Cancer Analysis Assistant",
  "tagline": "Upload your dictation — get a reviewable, watermarked colorectal pathology draft, not a transcript to rewrite",
  "oneLineProblem": "Helps colorectal surgery doctors in Hong Kong public hospitals reduce the time spent handwriting or organizing standardized, structured formal medical documents such as pathology reports, outpatient progress notes, and discharge summaries.",
  "targetUser": "Busy colorectal surgery doctors in Hong Kong public hospitals who dictate patient diagnosis and pathology test-result analysis",
  "audience": "C",
  "primaryGoal": "Extract the 15 key colorectal cancer pathology fields from ordered multi-segment dictation into a reviewable, watermarked structured draft",
  "keyFeatures": [
    "Ordered multi-segment audio upload with automatic backend stitching (16 kHz mono, 0.5 s silence between segments)",
    "Multilingual ASR with global timestamps",
    "ASR optimization and domain adaptation (rule-layer de-noising only)",
    "LLM-driven extraction of the 15 colorectal pathology checklist fields",
    "LLM preprocessing: slip-of-the-tongue correction and temporal override (later statement wins)",
    "Hallucination guard, schema validation, and post-hoc evidence audit",
    "Dual-column review UI with one-click Markdown and JSON export"
  ],
  "extractionFields": [
    "tumour_site",
    "operative_procedure",
    "tumour_dimension",
    "tumour_perforation",
    "relation_to_anterior_peritoneal_reflection",
    "plane_of_mesorectal_excision",
    "histological_tumour_type",
    "histological_tumour_grade",
    "extent_of_invasion",
    "lymphatic_and_venous_invasion",
    "perineural_invasion",
    "lymph_node_status",
    "tumour_deposits",
    "proximal_and_distal_margins",
    "circumferential_margin"
  ],
  "outOfScope": [
    "Write-back to the Hong Kong Hospital Authority EHR/eHR production database (contract stub only)",
    "Any live hospital-system connection",
    "Browser-side audio recording",
    "Separate processing step for segment boundaries",
    "Multi-specialty expansion beyond colorectal surgery outpatient workflow"
  ],
  "successMetrics": [
    "ASR CER ≤15% in mixed Cantonese + English + medical abbreviation contexts",
    "Field-level F1-Score ≥85% for the 15 specified pathology fields (≥95% long-term)",
    "End-to-end latency ≤15 seconds for 1–3 minute audio",
    "100% of unsupported fields rendered as [not mentioned]",
    "≥50% reduction in repetitive documentation writing time",
    "Doctor edit ratio below 20% of draft tokens"
  ]
}
```
