# Technical Design Document: ColoStruct MVP

**Version:** 0.3.0 (supersedes the SOAP-based v0.2) — architecture revised 2026-10-20
**User level:** **C** (A = vibe coder, B = developer, C = in-between) — same level declared in the PRD and the flowchart document.

## Overview

This document explains how we'll build ColoStruct using an approach that balances simplicity with learning opportunities.

ColoStruct is a web-based AI documentation assistant for colorectal surgery outpatient and pathology workflow in Hong Kong public hospitals. The full chain is: the doctor uploads the audio segments recorded for one case → the backend stitches them into a single stream (pydub, 16 kHz mono, 0.5 s silence between segments) → multilingual ASR transcription (Cantonese + English + medical abbreviations mixed) → deterministic rule-layer de-noising → LLM preprocessing (slip-of-the-tongue correction and temporal override, where a later statement replaces an earlier one) → LLM extraction into the 15-field colorectal pathology report structure → doctor reviews in a dual-column UI with evidence traceback and edits → one-click export of Markdown/JSON (carrying the "AI-assisted draft" watermark).

**Revision note — what changed in v0.3.0 (2026-10-20):**

1. **Target output changed.** The document target is no longer a SOAP-framework note. It is the **15 fields of the Colorectal cancer reporting checklist** supplied by the client. The SOAP schema module and the SOAP draft table are removed and replaced (`pathology_schema.py`, `pathology_extractions`).
2. **Field count corrected.** The task brief said "14 fields"; the checklist lists **15**. The checklist is authoritative; all documents state 15 and the correction is recorded here.
3. **Layered preprocessing.** The rule layer (`cleanup.py`) performs **de-noising only** (spoken fillers, invalid fragments, empty spans). Slip-of-the-tongue correction and temporal override are performed by the **LLM preprocessing pass**, not by rules.
4. **Stitching replaces recording.** Audio capture is **upload-only, multi-segment and ordered**; the in-browser recorder component (`ui/recorder.py`) is deleted. Segments are merged on the backend into one continuous timeline with per-segment offsets, and boundary handling is no longer a separate processing step: the stitched timeline plus its offsets cover segment edges on their own.
5. **Validation redefined.** `validate.py` becomes a **post-hoc audit**: schema conformance, evidence existence, hallucination whitelist, deterministic field rules, and verification of the LLM's own temporal-override decisions.

This design is trimmed to the PRD and your real constraints:

- **Platform:** Web (opened in a browser, desktop/laptop first). No mobile app.
- **Technical route:** small full-code project (Python + Streamlit), written with AI assistance, matching the "in-between" level; no v0 / Lovable / Bolt / Replit Agent builders.
- **Budget:** free/open-source components only (Whisper, Streamlit, Python). Compute is provided by the institution; no SaaS subscription.
- **Timeline:** as fast as possible — a runnable MVP in about 2 weeks (aligned with the PRD milestone 10.27).
- **Explicitly out:** no accounts, no payment, no analytics tracking, no public hosting, and **no write of any kind to the HA EHR/eHR production database**.

> The PRD launch goal originally read "Integrate with EHR/eHR", which conflicted with Out of Scope; it was revised on 2026-10-20 to "reserve an adapter interface (stub), no write-back". This design is consistent with the revised PRD.
>
> The PRD metric "structured draft accuracy ≥85%" was likewise revised to **"field-level F1-Score ≥85% for the 15 specified pathology fields"**, which is the metric this document designs and measures against.

## Recommended Approach

### Best Path for You: Balanced Learning Approach (Python + Streamlit monolith)

Based on your skills and goals, here's the optimal strategy:

**Primary Approach: full-code route — a single-process Streamlit app written with AI assistance**

- **Why this works:** the stack matches the constraints the PRD already fixed (Python Streamlit + Whisper + an LLM that supports structured JSON output), so no additional technology selection is needed; a single process means no front/back separation, no API auth, and no CORS, which is the fastest shape to get running while still genuinely learning Python engineering and audio processing.
- **Time to MVP:** about 2 weeks (environment → stitching + ASR → LLM extraction → dual-column UI → export).
- **Learning curve:** Moderate but manageable. Streamlit takes about a day; the real cost is audio processing and Whisper parameter tuning.
- **Cost:** 0 in software per month (open-source components only); compute must be provided.

### Alternatives Considered (alternatives and trade-offs for each main decision)

**Decision 1: overall technical route**

| Option | Pros | Cons | Cost | Time to MVP |
|------|------|------|------|-----------|
| **A. Python + Streamlit monolith (chosen)** | Consistent with the PRD; simplest single process; AI-generated code stays stable; local deployment is compliant by default | Limited UI customisation; unsuitable for many concurrent users; limited scalability | 0 (own compute) | ~2 weeks |
| B. Next.js frontend + Python/FastAPI backend | UI freedom and concurrency; closer to production shape | Two projects to maintain, API contracts, CORS and auth; learning cost doubles | 0 (own compute) + time | ~4–6 weeks |
| C. No-code/low-code builder (v0/Lovable) + external ASR API | Fastest to a visible interface | Conflicts with "free tier only"; audio and records leave the institution, violating privacy constraints; cannot satisfy in-hospital private deployment | Usually subscription | ~1–2 weeks, but unusable on real data |

**Trade-off:** B is more "correct" engineering but directly threatens the 10.27 runnable-MVP target and is over-engineering for the current level; C cannot touch real case data, which conflicts with the hard "in-hospital private deployment" constraint. **A** is chosen.

**Decision 2: ASR engine**

| Option | Pros | Cons |
|------|------|------|
| **faster-whisper (chosen)** | Faster and lighter than the reference implementation at the same accuracy; supports CPU int8; fully local | Parameters and version behaviour need empirical calibration |
| openai-whisper (PyTorch) | Reference implementation, most documentation | Slower, more VRAM; unfriendly for "free + local" |
| Cloud ASR API | Cantonese recognition is usually steadier; no local compute | Paid; audio leaves the institution (conflicts with privacy) |

**Trade-off:** privacy and budget are hard constraints, so the local engine is used, with a terminology dictionary and post-processing to compensate for recognition quality.

**Decision 3: how the LLM is supplied**

| Option | Pros | Cons |
|------|------|------|
| **Local open-source model (chosen; specific model TBD)** | Case data never leaves the institution; zero API cost | Extraction quality below top cloud models; needs stricter prompts and rule fallbacks |
| Cloud LLM API | Better and steadier structured output | Real clinical records cannot be used; metered billing |
| Hybrid (local primary + cloud switch) | Balances quality and privacy | Needs an extra switch and compliance review; the switch must default to off |

**Trade-off:** ship "local primary, with a cloud switch that defaults to off", so quality never overrides the privacy floor.

**Decision 4: how multiple audio segments are combined**

| Option | Pros | Cons |
|------|------|------|
| **Backend stitching with pydub (chosen)** | One ASR call over one timeline; global timestamps; segment count is unlimited; no cross-segment context loss | Requires resampling every segment to 16 kHz mono; boundary handling must be validated on real multi-device recordings |
| Browser-side recording of one long take | Single file, no stitching | Forces the doctor to record everything in one sitting, which does not match how real addenda arrive; recording components are version-fragile |
| Transcribe each segment separately and concatenate the text | No audio merging needed | Segment-relative timestamps, lost cross-segment context, and unstable ordering; evidence traceback becomes ambiguous |

**Trade-off:** the client's real case folders already contain several segments per case recorded at different times (e.g. a specimen macro description in the morning and an addendum after histology review), so segment count is a fact of the data, not a preference. Backend stitching is the only option that keeps a single reliable timeline.

### Tech Stack (Balanced for Learning)

#### Frontend

- **Framework:** Streamlit (pure Python, browser access)
  - *Why:* no HTML/CSS/JS needed; `st.columns` is a natural fit for the "audio + transcript | 15-field draft" dual-column layout; abundant community examples and AI training corpus
  - *Learning time:* 1 day for the basics, about 3 days to be fluent with `session_state`
- **Audio input:** `st.file_uploader` with `accept_multiple_files=True` — **upload only, no recording component**
  - *Why:* the doctor uploads the segments recorded for a case; the UI must preserve and display the submission order explicitly, since the order defines the stitched timeline
  - *Learning time:* half a day
  - *Note:* the removed recorder dependency (`streamlit-audiorecorder`) also removes its Streamlit version-compatibility risk

#### Backend

This project has **no separate backend service** — the pipeline runs inside the Streamlit process, a deliberate simplification that removes the API layer, authentication, and deployment complexity.

- **Service:** Python 3.11 modular pipeline (`core/`)
  - *Why:* single process, no CORS, and an AI assistant can reliably rewrite a single file
  - *Learning time:* 1–2 weeks (including audio and LLM calls)
- **Audio stitching:** `pydub` (+ `ffmpeg` for container decoding), producing one 16 kHz mono WAV with 0.5 s of silence between segments and a recorded cumulative offset per segment
  - *Why:* `pydub` is the shortest path to "merge N files in a known order and know where each one starts"; offsets are what makes global timestamps and segment-level traceback possible
  - *Learning time:* half a day
- **ASR:** `faster-whisper` (CTranslate2 implementation, local)
  - *Why:* runs on CPU int8 and faster on GPU; provides word-level timestamps, which support field-level evidence traceback
  - *Learning time:* half a day (model size, `compute_type`, `beam_size`)
- **LLM:** local open-source model (served via Ollama or llama.cpp), output constrained by Pydantic / JSON Schema
  - *Why:* data stays in the institution; constrained decoding sharply reduces JSON parse failures
  - *Learning time:* 1–2 days (including structured output and retry logic)
- **Preprocessing (two distinct layers):**
  - *Rule layer* — pure Python (`re`, self-maintained dictionaries): removes spoken fillers, duplicated fragments, and empty spans, and normalises surface forms (digits/units, spelled-out abbreviations). It performs **de-noising only** and never rewrites clinical meaning.
  - *LLM layer* — slip-of-the-tongue correction and **temporal override** (a later statement replaces an earlier one). This is a language-understanding task, so it belongs to the model, not to regexes.
- **Storage:** SQLite + local file system
  - *Why:* single machine, single operator; zero operations; backup = copy one file
  - *Learning time:* half a day

#### Deployment

- **Platform:** institutional intranet server or local workstation, containerised with Docker
  - *Why:* satisfies "data never leaves the hospital"; no public network dependency, no domain or TLS certificate management
  - *Learning time:* half a day (about an hour if Docker is already familiar)
- **Explicitly not used:** public hosting such as Streamlit Community Cloud (it would move data outside the institution)

#### AI Assistance

- **Primary:** undecided (TBD) — you did not specify an AI coding assistant in Q6 and chose "recommend free-first and mark it as TBD"
- **Recommended start:** VS Code + Continue (or Cline) + a local model
  - *Why:* completely free; data can stay on the machine; the same runtime can serve the production local LLM, so the learning carries over

**Free-first comparison** (check each vendor's current pricing page for quotas):

| Tool | Free tier | Privacy fit | Notes |
|------|-----------|-------------|-------|
| VS Code + Continue / Cline + local model | Fully free (open-source tooling) | Data can stay entirely on the machine | Best fit for in-hospital private deployment and zero budget |
| VS Code + GitHub Copilot | Free tier available, subscription beyond it | Cloud completions; confirm acceptability | Smoothest fit with the VS Code ecosystem |
| Cursor | Limited free tier; paid for heavy use | Cloud | In tension with the "free tier only" budget |

## Project Structure

```
colostruct/
├── app.py                      # Streamlit entry: routing, dual-column layout
├── ui/
│   ├── upload_panel.py         # Ordered multi-segment upload + stitch status
│   ├── review_panel.py         # Dual-column review (audio/transcript ↔ 15 fields)
│   └── export_panel.py         # Export button and format selection
├── core/
│   ├── pipeline.py             # Orchestration: upload → stitch → transcribe → clean → LLM preprocess → extract → validate
│   ├── audio_merge.py          # Segment stitching (pydub), 16 kHz mono, 0.5 s silence, per-segment offsets
│   ├── asr.py                  # faster-whisper wrapper (model loading, parameters, timestamps)
│   ├── hotwords.py             # Colorectal term dictionary and bias prompt construction
│   ├── cleanup.py              # De-noising only: filler words, duplicated fragments, empty spans, surface-form normalisation
│   ├── preprocess.py           # LLM preprocessing: slip-of-the-tongue correction + temporal override
│   ├── align.py                # Timestamp alignment and evidence traceback (field → audio span)
│   ├── llm.py                  # LLM call wrapper + JSON Schema constraint + retry
│   ├── pathology_schema.py     # 15-field colorectal pathology JSON Schema and Pydantic models
│   ├── validate.py             # Post-hoc audit: schema, evidence existence, whitelist, field rules, override verification
│   ├── export.py               # Markdown / JSON export + AI watermark
│   └── ehr_adapter.py          # EHR adapter layer (stub, never connects to a real system)
├── data/
│   ├── golden/                 # Golden test set (de-identified synthetic data)
│   ├── field_rules.yaml        # Per-field allowed values and deterministic rules (15 fields)
│   ├── hotwords.csv            # Term dictionary (term + aliases/weight)
│   └── corrections.csv         # Surface-form mappings (units, abbreviations)
├── storage/
│   ├── colostruct.db           # SQLite
│   ├── audio/                  # Uploaded segments + stitched audio
│   └── exports/                # Exported artifacts
├── eval/
│   ├── run_cer.py              # CER calculation
│   ├── run_f1.py               # Per-field F1 over the 15 pathology fields
│   └── report.md               # Evaluation report output
├── tests/
│   ├── test_audio_merge.py
│   ├── test_cleanup.py
│   ├── test_validate.py
│   └── test_export.py
├── .env.example
├── .gitignore
├── Dockerfile
├── requirements.txt
└── README.md
```

**Why this structure:**

- Layered as "interface / core logic / data / evaluation / tests" so an AI assistant with `AGENTS.md` in context can change one file without disturbing the rest
- Each module under `core/` has a single responsibility and can be tested alone, which makes failures fast to locate
- `eval/` and `tests/` are separate: the former evaluates *model quality*, the latter protects *code correctness*; mixing them makes both untrustworthy
- `.gitignore` must include `storage/`, `data/golden/`, `.env`, `*.wav`, `*.db`
- `data/field_rules.yaml` is new: the 15-field definitions, allowed values, and per-field rules live as data, so field tuning does not require code changes

## Building Each Feature

Based on your PRD, here's the implementation plan:

### Feature 1: Ordered multi-segment audio upload with automatic backend stitching

**Complexity:** Simple–Medium (the stitching itself is easy; order and offset correctness are what need care)

#### Implementation Steps

1. **Accept multiple segments in order**
   - `st.file_uploader(..., accept_multiple_files=True)`; the UI lists the files in submission order with an index and a duration, and lets the doctor reorder or remove a segment before submitting
   - AI Prompt: "Create a Streamlit multi-file audio upload component that lists uploaded segments in submission order with index, filename, and duration, supports reorder and removal before submit, validates the container format (wav/mp3/m4a/wma), and reports a clear error for unsupported or oversized files."

2. **Normalise each segment**
   - Every segment is decoded and resampled to 16 kHz mono into `storage/audio/{session_id}/{index:02d}.wav`
   - Reject unreadable files with a per-file message rather than failing the whole batch

3. **Stitch into one timeline**
   - `core/audio_merge.py` concatenates the normalised segments in order, inserting **0.5 s of silence** between consecutive segments, and writes `storage/audio/{session_id}/stitched.wav`
   - The function returns a cumulative **offset table**: `[{segment_index, source_file, offset_sec, duration_sec}]`, which is persisted and later used to render global timestamps and to map any field's evidence back to the segment it came from

4. **Persist and continue**
   - Write one `audio_assets` row per segment plus one `stitched_audio` row; set `sessions.status = 'draft'`
   - If the doctor re-uploads, create a new stitched asset and supersede the previous transcript (history is kept for traceability)

#### Data Model (SQLite)

```sql
CREATE TABLE sessions (
    id            TEXT PRIMARY KEY,        -- uuid4
    created_at    TEXT NOT NULL,           -- ISO8601
    patient_ref   TEXT,                    -- de-identified reference, may be null
    language_hint TEXT,                    -- 'yue' / 'en' / 'mixed'
    status        TEXT NOT NULL            -- draft | reviewed | exported
);

CREATE TABLE audio_assets (                -- one row per uploaded segment
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    segment_index INTEGER NOT NULL,        -- submission order, 0-based
    source_file   TEXT NOT NULL,           -- original filename as uploaded
    file_path     TEXT NOT NULL,           -- normalised 16 kHz mono segment
    duration_sec  REAL,
    created_at    TEXT NOT NULL
);

CREATE TABLE stitched_audio (
    id                 TEXT PRIMARY KEY,
    session_id         TEXT NOT NULL REFERENCES sessions(id),
    file_path          TEXT NOT NULL,      -- concatenated stream
    sample_rate        INTEGER NOT NULL DEFAULT 16000,
    channels           INTEGER NOT NULL DEFAULT 1,
    silence_ms         INTEGER NOT NULL DEFAULT 500,
    total_duration_sec REAL,
    offsets_json       TEXT NOT NULL,      -- [{segment_index, source_file, offset_sec, duration_sec}]
    created_at         TEXT NOT NULL
);
```

**Learning Points:**

- Why sample rate and channel count must be unified before concatenation (mixed-device segments otherwise produce drift and pitch artifacts)
- How a cumulative offset table turns N files into one addressable timeline
- How Streamlit's `session_state` keeps upload order and processing state across interactions

---

### Feature 2: Multilingual ASR transcription

**Complexity:** Medium

#### Implementation Steps

1. **Model loading**
   - `core/asr.py` lazily loads the faster-whisper model (cached to avoid reloading on every interaction)
   - Choose `compute_type` by machine capability: GPU → `float16`; CPU only → `int8`

2. **Word-level timestamps**
   - Enable word-level timestamps and emit `segments_json`, which is the basis for evidence traceback. Timestamps are **global to the stitched stream**, so a span always resolves to a real position in `stitched.wav`

3. **Language strategy**
   - Auto-detect by default; if confidence is low, or the text hits both the Chinese and English dictionaries, mark `language_hint = 'mixed'` and show "manual review recommended" in the UI

4. **Record the version for attribution**
   - Store the transcript together with the `asr_model` version so CER changes can be traced to a specific model version

#### Data Model

```sql
CREATE TABLE transcripts (
    id                TEXT PRIMARY KEY,
    stitched_audio_id TEXT NOT NULL REFERENCES stitched_audio(id),
    asr_model         TEXT NOT NULL,       -- e.g. 'faster-whisper:large-v3'
    raw_text          TEXT NOT NULL,
    segments_json     TEXT NOT NULL,       -- [{start,end,text,words:[...]}]  global timestamps
    cer_estimate      REAL                 -- written only when the sample is part of the golden set
);
```

#### Implementation Approach

- First get "one stitched audio → text + timestamps" working; optimise later, and do not tune parameters before there is a baseline
- Establish the first CER baseline on goldens G1/G2
- Verify explicitly that a span taken from the second or third segment resolves to the correct position in the stitched timeline

**AI Assistance Strategy:**
- Use the local model assistant to explain faster-whisper parameters
- Have the AI generate the parsing and display code for `segments_json`; you check the field names

**Learning Points:**
- The ASR input/output structure (segment and word level timestamps)
- What quantisation does to speed and accuracy
- How a fixed test set tells you whether a change made things better or worse

---

### Feature 3: ASR optimisation and domain adaptation (rule-layer de-noising)

**Complexity:** Medium-High

> **Scope boundary (this revision):** this feature performs **de-noising only**. Slip-of-the-tongue correction and temporal override are *not* here — they are LLM tasks (Feature 4). Any rule that rewrites clinical meaning breaks the safety story, so the boundary is enforced in code review and covered by `tests/test_cleanup.py`.

#### Implementation Steps

1. **Upstream biasing (term injection)**
   - Assemble the terms in `data/hotwords.csv` (for example: rectum, sigmoid, mesorectal, anterior peritoneal reflection, circumferential margin, tumour deposit, perineural, lymphovascular, adenocarcinoma, mucinous, poorly differentiated, neoadjuvant) into a prompt injected via `initial_prompt` / `hotwords`
   - Before implementing, confirm whether the installed faster-whisper version supports the parameter and how it behaves; if not, degrade to `initial_prompt` plus a post-processing replacement table

2. **Rule-layer de-noising**
   - Remove spoken fillers and discourse particles, duplicated fragments produced by ASR looping, and empty spans
   - Normalise surface forms: digits and units ("three point five centimetres" → "3.5 cm"), spelled-out abbreviations ("C-M" style letter sequences → their standard form), and the mappings in `data/corrections.csv`
   - **Explicitly not in scope:** deciding what the dictation meant, resolving contradictions, correcting a misstated value, or dropping a repeated clinical statement — the rule layer must leave all of these intact for the LLM

3. **Removal log**
   - Every rule-layer removal is written to a log with its span, so a reviewer can see exactly what was taken out and can confirm nothing clinical was removed

4. **Regression verification (the only acceptance method for this feature)**
   - Every change to a dictionary or parameter re-runs the golden CER; this prevents "fixing one word and breaking the sentence"

#### Implementation Approach

- Dictionary and parameters are **configurable data** (CSV), never hard-coded, so iteration does not require code changes and a risky choice stays revertible
- Keep the "dictionary off / dictionary on" comparison results as the evidence for the selection
- Assert in tests that the cleaner never changes a clinical term or removes a value that a field depends on

**Learning Points:**
- Why domain adaptation is a better return than swapping models
- Data-driven parameter tuning versus tuning by feel
- Where the boundary between deterministic cleaning and model-based understanding actually sits

---

### Feature 4: LLM-driven extraction of the 15 colorectal pathology fields

**Complexity:** Medium-High (depends on the local model's JSON stability)

This feature has **two LLM passes** with distinct contracts.

#### Pass A — preprocessing (correction + temporal override)

1. **Slip-of-the-tongue correction** — fix mispronounced or mistyped specialty terms using the corrected context, without inventing content that was never said
2. **Temporal override** — scan statements about the same field in timestamp order and let the **later** statement win; every replacement is recorded in `override_log` with the field, the old value, the new value, and the source time of the winning statement
3. Output: a corrected transcript plus `override_log`, both retained as evidence for the audit stage

#### Pass B — field extraction

4. **Field extraction** — populate the 15 checklist fields from the corrected transcript

#### Data Model

```json
{
  "fields": {
    "tumour_site": { "value": "", "evidence": [{ "start": 0.0, "end": 0.0 }], "status": "populated" },
    "operative_procedure": { "value": "", "evidence": [], "status": "populated" },
    "tumour_dimension": { "value": "", "evidence": [], "status": "populated" },
    "tumour_perforation": { "value": "", "evidence": [], "status": "populated" },
    "relation_to_anterior_peritoneal_reflection": { "value": "", "evidence": [], "status": "populated" },
    "plane_of_mesorectal_excision": { "value": "", "evidence": [], "status": "populated" },
    "histological_tumour_type": { "value": "", "evidence": [], "status": "populated" },
    "histological_tumour_grade": { "value": "", "evidence": [], "status": "populated" },
    "extent_of_invasion": { "value": "", "evidence": [], "status": "populated" },
    "lymphatic_and_venous_invasion": { "value": "", "evidence": [], "status": "populated" },
    "perineural_invasion": { "value": "", "evidence": [], "status": "populated" },
    "lymph_node_status": { "value": "", "evidence": [], "status": "populated" },
    "tumour_deposits": { "value": "", "evidence": [], "status": "populated" },
    "proximal_and_distal_margins": { "value": "", "evidence": [], "status": "populated" },
    "circumferential_margin": { "value": "", "evidence": [], "status": "populated" }
  },
  "flags": [{ "field": "", "reason": "not_mentioned" }],
  "meta": {
    "prompt_version": "",
    "prepass_version": "",
    "override_log": [{ "field": "", "from": "", "to": "", "source_time": 0.0 }],
    "segment_offsets": [{ "segment_index": 0, "offset_sec": 0.0 }]
  }
}
```

> **Key convention:** every non-empty field must carry `evidence` timestamps resolvable in the stitched audio. A field with no audio support stays empty and is listed in `flags` with **`reason = "not_mentioned"`**. This is the verifiable implementation of the PRD's "hallucination guard".

#### Implementation Approach

1. **Turn the schema into a constraint**
   - `core/pathology_schema.py` defines the 15-field Pydantic models and exports the JSON Schema handed to the LLM runtime for constrained decoding
   - `status` is `populated | absent | flagged`, and `absent` is the only legal state for an undictated field

2. **Wrap the calls**
   - `core/llm.py`: prompt assembly (system prompt + field definitions from `field_rules.yaml` + dictionary summary + transcript + output contract) → call → JSON parse → Pydantic validation
   - Both passes go through the same wrapper but with different contracts: Pass A returns corrected text + `override_log`; Pass B returns the 15 fields + evidence

3. **Retry and degradation**
   - Retry a failed parse at most twice; on the second retry append "your previous output was invalid because: …"
   - If it still fails, degrade to a read-only rule-extracted draft with a **prominent warning**; never silently return an empty shell

4. **Version traceability**
   - `prompt_version`, `prepass_version`, and `llm_model` are written to `pathology_extractions` so A/B comparisons are possible

5. **Extract only, never infer**
   - The prompt states explicitly: "use only information that appears in the transcript; if a field was not stated, return `status: absent`"

```sql
CREATE TABLE pathology_extractions (
    id                 TEXT PRIMARY KEY,
    session_id         TEXT NOT NULL REFERENCES sessions(id),
    transcript_id      TEXT NOT NULL REFERENCES transcripts(id),
    extraction_json    TEXT NOT NULL,       -- conforms to pathology_schema (15 fields)
    edited_json        TEXT,                -- doctor-edited version
    preprocess_json    TEXT,                -- Pass A output: corrected transcript + override_log
    llm_model          TEXT NOT NULL,
    prompt_version     TEXT NOT NULL,
    created_at         TEXT NOT NULL
);
```

**AI Assistance Strategy:**
- Have the assistant generate the JSON Schema and examples from the Pydantic models; you verify that field semantics match clinical habit (especially `plane_of_mesorectal_excision`, `extent_of_invasion`, and the two margin fields)
- For every prompt iteration, re-run the golden set and record per-field F1; never judge by impression

**Learning Points:**
- Why structured output (constrained decoding) beats "asking a model to output JSON"
- How to design a fallback path for an LLM call
- Why a two-pass design (correction before extraction) is easier to audit than one prompt that does both

---

### Feature 5: Hallucination guard and post-hoc audit

**Complexity:** Medium

> **Scope boundary (this revision):** the LLM performs temporal override in Feature 4; this feature **audits** those decisions rather than making them. A deterministic audit of a model decision is what makes the result reviewable.

#### Implementation Steps

1. **Schema conformance**
   - Every extraction is validated against the 15-field schema before display: unknown keys, wrong types, illegal enum values, and missing fields all fail loudly

2. **Evidence existence check**
   - For every field whose `value` is non-empty, its `evidence` must resolve to a real span in `segments_json`; if it cannot be located → `warn`, and the doctor must confirm
   - A field that is `absent` but has evidence → `warn` (the model contradicted itself)

3. **Term whitelist check**
   - Specialty terms in histological type, procedure, and margin fields must hit the dictionary or appear in the corrected transcript; otherwise it is flagged as a suspected hallucination (`block` severity)

4. **Temporal-override verification (post-hoc)**
   - Replay `override_log` against the transcript: the winning statement must really be later than the overridden one, and both must exist verbatim at their recorded times
   - If an override cannot be reproduced, raise a `warn` showing both competing spans and the timestamps, and ask the doctor to choose

5. **Deterministic field rules**
   - Examples: a margin value without a unit; a lymph node status that does not carry a counted fraction; a grade value outside the allowed list; tumour dimension inconsistent between two statements that were never reconciled

6. **Persist and display**
   - All results are written to `validations`, and the UI shows a badge next to the affected field

```sql
CREATE TABLE validations (
    id            TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL REFERENCES pathology_extractions(id),
    severity      TEXT NOT NULL,           -- info | warn | block
    rule_id       TEXT NOT NULL,
    field_path    TEXT,                    -- e.g. 'fields.circumferential_margin'
    message       TEXT NOT NULL,
    evidence_json TEXT                     -- associated timestamp spans
);
```

**Learning Points:**
- Why deterministic rules are the reliable fallback in a clinical setting
- How auditing a model's own correction decisions keeps "the doctor changed their mind" from losing information

---

### Feature 6: Dual-column review UI + one-click export

**Complexity:** Medium

#### Implementation Steps

1. **Dual-column layout**
   - `st.columns([1, 1])`: the left column is the stitched audio player plus the timestamped transcript (clickable to highlight); the right column is the editable 15-field form (`st.text_area` / `st.data_editor`), grouped as tumour & specimen (1–6), histology (7–11), nodes & deposits (12–13), margins (14–15)

2. **Evidence traceback interaction**
   - Each field shows an evidence link: clicking highlights the matching span in the left column and seeks playback there; a field whose evidence lies in the third segment also shows "segment 3"

3. **Field states**
   - *populated with evidence* (normal), *flagged* (amber badge, competing spans shown), *`[not mentioned]`* (grey, read-only until the doctor types), *doctor-edited* (marked so the override is visible)

4. **Visible validation**
   - info / warn / block badges plus the "AI-generated" notice are always present, and the export button is disabled while any `block` issue is open

5. **Export**
   - `core/export.py` generates Markdown and JSON; the Markdown file starts with a watermark block:

   ```markdown
   > ⚠️ AI-assisted draft — generated by ColoStruct, reviewed and confirmed by the doctor.
   > Generated: {timestamp}　Model: {llm_model}　Prompt version: {prompt_version}
   ```

   - The JSON export contains `edited_json` (the doctor's final version) plus audit information (validation results and the override log)

6. **EHR adapter layer (stub, no write capability)**

   ```python
   # core/ehr_adapter.py
   class EhrAdapter(Protocol):
       """Contract only. The MVP contains no implementation and imports no hospital-system SDK."""
       def validate(self, extraction: EhrExtraction) -> list[str]: ...
       def preview(self, extraction: EhrExtraction) -> str: ...   # human-readable preview only
       # Note: no write/submit method is defined here, deliberately.
   ```

   Boundary statement (written into README and the UI): the MVP makes no network request to the HA EHR/eHR; no submit/write method exists; any future integration requires institutional approval and a separate security review.

```sql
CREATE TABLE exports (
    id            TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL REFERENCES pathology_extractions(id),
    format        TEXT NOT NULL,           -- markdown | json
    file_path     TEXT NOT NULL,
    watermark     TEXT NOT NULL DEFAULT 'AI-assisted draft',
    exported_at   TEXT NOT NULL
);
```

**Learning Points:**
- How state synchronisation works in a dual-column layout
- Why a watermark and version traceability are the minimum compliance requirement

## Development Setup

### Required Tools

1. **Code Editor: VS Code**
   - Install from: code.visualstudio.com
   - Essential extensions:
     - Python
     - Pylance (type hints)
     - Ruff (lint and format)
     - Prettier (markdown/json only)

2. **AI Assistant: undecided (TBD)**
   - Default recommendation: VS Code + Continue or Cline + a local model
   - After installation, add `AGENTS.md` pointing at the project context so the assistant reads the project instead of guessing (Part 4 generates that file)

3. **Version Control: Git**
   ```bash
   git init
   git add .
   git commit -m "chore: initial ColoStruct scaffold"
   ```
   Optional: configure a pre-commit hook to run lint and tests before commit.

4. **Runtime: Python 3.11 + Docker** (Docker is only needed for deployment)
   - Also required: `ffmpeg` on `PATH` (used by `pydub` to decode mp3/m4a/wma)

### Environment Setup

```bash
# 1. Create the project directory (this design does not depend on an external template repo)
mkdir colostruct && cd colostruct

# 2. Create a virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

# 3. Configure environment variables
copy .env.example .env            # fill in the local model endpoint, etc.
# Example local model endpoint (use your actual runtime):
# LLM_BASE_URL=http://127.0.0.1:11434

# 4. Run the development environment
streamlit run app.py
```

## AI Prompting Guide

### Effective Prompts for Your Level

#### For New Features

```
I'm building ColoStruct (a Python + Streamlit colorectal surgery documentation assistant).
Current structure: core/ holds the pipeline, ui/ holds Streamlit components, eval/ holds evaluation scripts.
Requirement:
- [requirement 1 from the PRD]
- [requirement 2 from the PRD]
Explain your approach first, then give code I can drop into [target file], and tell me how to verify it.
Constraints: open-source dependencies only; no external network write operations; the rule layer must not rewrite clinical meaning.
```

#### For Debugging

```
Error: [full error]
I was doing: [action]
Relevant code: [paste]
Stack: Python 3.11 + Streamlit + pydub + faster-whisper + local LLM
Explain the root cause and give the minimal fix. Do not rewrite the whole file.
```

#### For Learning

```
I implemented [feature] with this code: [paste]
It runs, but please explain:
1. How does [some part] work?
2. Is there a simpler or more robust way?
3. What should I learn next?
```

## Simplified Architecture

### How Your App Works

```
Doctor uploads the case's audio segments in order → Streamlit normalises each to 16 kHz mono
→ pydub stitches them into one stream (0.5 s silence between segments) with a cumulative offset table
→ faster-whisper transcribes the stitched stream (global timestamps)
→ rule layer de-noises only (fillers, duplicated fragments, surface forms) and logs removals
→ local LLM pass A: slip-of-the-tongue correction + temporal override (override_log)
→ local LLM pass B: extraction of the 15 colorectal pathology fields (JSON Schema constrained)
→ post-hoc audit: schema, evidence existence, whitelist, field rules, override verification
→ dual-column human review and edits
→ one-click export of Markdown/JSON (with the AI watermark)
```

Concretely split into:

1. User action (Streamlit UI)
2. Stitching (`core/audio_merge.py`)
3. Local processing (orchestrated by `core/pipeline.py`)
4. ASR inference (faster-whisper, local)
5. Rule processing (`cleanup.py` / `align.py`, pure Python)
6. LLM preprocessing (`preprocess.py`, Pass A)
7. LLM extraction (`llm.py` + `pathology_schema.py`, Pass B)
8. Validation (`validate.py`, post-hoc audit)
9. Persistence and display (SQLite + Streamlit dual column)
10. Export (Markdown / JSON + watermark)

### Key Concepts to Understand

1. **In-process pipeline:** the whole chain runs in order within one interaction
   - Think: one conveyor belt, each station doing exactly one thing

2. **Segment offsets:** every uploaded segment knows where it starts inside the stitched audio
   - Think: page numbers in a book made by stapling several chapters together

3. **Session state:** data Streamlit keeps across interactions
   - Think: variables that do not vanish when the page refreshes

4. **Structured output (schema):** the schema constrains the shape of the LLM's output
   - Think: handing the model a form it must fill in, instead of letting it free-write

5. **Evidence traceback:** every field points at an audio time span
   - Think: every line of the report can be clicked and heard in the doctor's own voice

6. **Temporal override:** a later statement replaces an earlier one, and the replacement is logged
   - Think: when the doctor changes their mind, the last word wins — and the change is written down

7. **Two-layer preprocessing:** rules clean the surface, the model interprets the meaning
   - Think: a proofreader who only removes noise versus an editor who understands the sentence

## AI Feature Integration (Optional)

> In this project AI is **required**, not optional: it is the product's core workflow.

- **Use cases:** multilingual ASR transcription; rule-independent preprocessing (slip-of-the-tongue correction, temporal override); extraction of the 15 colorectal pathology fields; support for the validation stage; export watermarking
- **Provider options:** local open-source models by default (Whisper + local LLM); a cloud API as an **off-by-default** optional switch
- **Data sensitivity:** high (personal health information). Real data is processed locally / in-hospital only
- **Data boundary:** only the current case's corrected transcript is sent to the LLM; no patient identity fields; no cross-session history
- **Retention/training:** local models leave nothing externally; if the cloud API switch is ever enabled, the endpoint must be confirmed as non-training with the shortest retention window (verify against vendor documentation)
- **Latency/cost targets:** ≤15 seconds end to end for 1–3 minutes of audio (PRD target); cost target is 0 subscription fees
- **Fallback behaviour:** stitching fails → keep the uploaded segments and offer retry, never proceed with a partial timeline; ASR fails → keep the audio and offer retry; Pass A fails → fall back to the rule-cleaned transcript and flag "correction pass unavailable"; Pass B fails → degrade to a rule-extracted draft with a `block` warning; validation fails → block export
- **Human confirmation:** export, final field sign-off, and any call to the EHR adapter layer
- **Telemetry:** local structured logs only (model version, timings, error types); **no audio content and no patient identifiers**; no third-party analytics

## Step-by-Step Implementation

The week labels below follow the agreed 2-week-to-MVP timeline (PRD milestones 10.13–12.15).

### Week 1: Foundation

- [ ] Create the repository, virtual environment, `requirements.txt` (including `pydub`, `ffmpeg` availability check)
- [ ] Get `streamlit run app.py` showing a Hello World
- [ ] `ui/upload_panel.py`: ordered multi-segment upload with reorder/remove and format validation
- [ ] `core/audio_merge.py`: stitching to 16 kHz mono with a 0.5 s silence gap and a correct offset table; test on the client's real multi-segment case folders
- [ ] `core/asr.py`: faster-whisper running on the stitched stream, producing `segments_json` with global timestamps
- [ ] Transcribe the first golden cases and establish the initial CER baseline

### Week 2: Core Features — Runnable MVP (10.27)

- [ ] `core/hotwords.py` + `core/cleanup.py`: term dictionary and de-noising-only cleaning with a removal log
- [ ] `core/preprocess.py` + `core/llm.py` + `core/pathology_schema.py`: Pass A correction/override and Pass B extraction of the 15 fields
- [ ] `data/field_rules.yaml`: the 15 field definitions, allowed values, and deterministic rules
- [ ] `core/validate.py`: schema conformance, evidence existence, whitelist, field rules, override verification
- [ ] `ui/review_panel.py`: dual-column interface with field states and evidence traceback
- [ ] `core/export.py`: Markdown/JSON export with the watermark
- [ ] `eval/run_cer.py` + `eval/run_f1.py`: first CER and per-field F1 baseline
- [ ] **10.27: Runnable MVP reached**

### Week 3: Polish & Launch — Beta (11.10–12.01)

- [ ] 2–3 rounds of dictionary and prompt iteration, recording CER and per-field F1 each round
- [ ] Collect doctor feedback and record "the fields that get edited most"
- [ ] Complete the failure fallback paths (stitching, ASR, Pass A, Pass B)
- [ ] Latency optimisation (model size / quantisation / cached loading)
- [ ] Automated tests covering `audio_merge`, `cleanup`, `validate`, `export`
- [ ] Privacy and dependency audit
- [ ] **12.01: Beta**

### Week 4: Demo & Archive (12.08–12.15)

- [ ] Prepare the demo script and demo data (**12.08 Demo Day**)
- [ ] Archive: design documents, evaluation report, known-limitations list (**12.15**)

## Common Challenges & Solutions

### "I don't understand this error"

**Solution:**
1. Copy the complete error (not just one line)
2. Ask the AI: "Explain this error in plain language and tell me which line of my code triggers it: [error]"
3. If still stuck, search: "[error] Streamlit faster-whisper"

### "Feature seems too complex"

**Solution:**
1. Split it into smaller pieces (for example, split "dual-column review" into "left column shows the transcript" and "right column shows the form")
2. Build the simplest thing that runs first
3. Add complexity gradually (ignore styling first, then edge cases)
4. Ask the AI: "Give me a simpler implementation that still works"

### "Code works but I don't understand it"

**Solution:**
1. Ask the AI to comment it: "Add detailed comments to this code explaining what each step does"
2. Ask for a line-by-line explanation: "Explain this code line by line as if teaching a beginner"
3. Close the code and rewrite it yourself; look only when stuck — this is the only way it really sticks

### "A segment seems to be missing or the timestamps look shifted"

**Solution:**
1. Check the `offsets_json` table for the case: the last offset plus its duration must equal the stitched total
2. Confirm every uploaded file produced a normalised 16 kHz mono file (a decode failure that was reported as a warning is the usual cause)
3. Re-run the stitching on the same files and compare the offset table before touching any ASR settings

## Deployment Guide

### Example: deploying to an intranet Docker host (the chosen option for this project)

1. **Prepare the image**
   - Write a `Dockerfile` based on `python:3.11-slim`, installing `requirements.txt` plus `ffmpeg`, and exposing the Streamlit port
   - Do not bake model weights into the image (too large); mount a volume, or download once inside the image and persist

2. **Configure the environment**
   ```
   LLM_BASE_URL=http://127.0.0.1:11434
   STORAGE_DIR=/data/colostruct
   ```

3. **Deploy**
   - `docker compose up -d` on the intranet host
   - Verify the intranet address responds (**do not** expose the port to the public internet)

### Custom Domain (Optional)

**Not applicable.** The deployment constraint is "intranet access only", so no domain is purchased and no public TLS is configured. If in-hospital multi-machine access is needed later, institutional IT should provide the intranet domain and certificate — this project does not procure them itself.

## Cost Breakdown

### Development Phase

| Service | Free Tier | Paid Tier | Notes |
|---------|-----------|-----------|-------|
| Python / Streamlit | Open-source, free | — | Free licence |
| pydub / ffmpeg | Open-source, free | — | Local decode and stitching |
| faster-whisper / local LLM runtime | Open-source, free | — | Compute must be provided |
| SQLite | Open-source, free | — | No service fee |
| AI coding assistant | Depends on the chosen tool (**TBD**) | Depends on the chosen tool | See Tech Stack → AI Assistance |
| Code hosting (private repo) | Free tier available | Vendor-dependent | Check the current pricing page |
| **Total** | **Estimated 0 per month** | **Varies** | **Verify current vendor pages** |

> Last verified: not verified — every number in this table is a planning estimate, not a quotation. Check each vendor's current pricing page before budgeting.

### After Launch (Production)

| Usage scale | Cost trend | Notes |
|---------|------------|-------|
| Single doctor, single machine | Low | Software layer close to 0; the cost is compute |
| Multi-workstation outpatient clinic | Moderate | Needs stronger local inference hardware; still no subscription |
| Hospital-wide, multi-department | Higher | Needs server-grade GPU and operations effort; model licensing cost may appear |

## Maintenance & Updates

- Pin dependency versions; upgrade deliberately and re-run the golden-set evaluation afterwards
- Run `pip-audit` or an equivalent tool periodically for dependency security
- Update `AGENTS.md`, `docs/`, and pre-commit hooks as the project grows
- Keep one evaluation record for every prompt, dictionary, or field-rule change, so quality cannot silently degrade
- Treat `data/field_rules.yaml` as clinical content: a change to an allowed value or rule is reviewed with the doctor, not by the developer alone

## Learning Resources

### Your Learning Path

#### This Week: Python and Streamlit basics

- **Docs:** docs.python.org/3/tutorial/, docs.streamlit.io
- **Practice:** build a small page that uploads files and displays content, then add a dual-column layout

#### Next Week: Whisper and audio processing

- **Repos:** github.com/SYSTRAN/faster-whisper, github.com/openai/whisper, github.com/jiaaro/pydub
- **Practice:** compare different model sizes and `compute_type` values on the same audio, for time and text differences; stitch three short clips and verify the offset table by playing a marked span

#### Week 3: Structured output and evaluation

- **Docs:** Pydantic documentation; the "structured output / grammar" section of your LLM runtime
- **Practice:** write a script that computes CER and per-field F1 on a fixed test set and emits a report

### When Stuck

1. **Communities:**
   - Streamlit official forum: discuss.streamlit.io
   - faster-whisper / CTranslate2 GitHub Issues
   - pydub / ffmpeg documentation and Stack Overflow
   - The community of your chosen AI coding assistant

2. **AI Assistants:**
   - Architecture and concepts: a local model assistant or a general chat assistant
   - Debugging: give the full error plus the relevant code
   - Code generation: your coding assistant (with `AGENTS.md` context)

## Growing Beyond MVP

### Signs You're Ready for More

- Someone in the clinic is genuinely using it every day
- You can read and modify any module under `core/` yourself
- Adding a field or a rule already feels routine
- Performance or concurrency problems start appearing (several doctors using it at once)

### Next Steps

1. **Add Testing:** wire `eval/` and `tests/` into CI so every commit runs them
2. **Improve Performance:** model quantisation, cached loading, asynchronous ASR, streaming stitching for long cases
3. **Better Architecture:** only if multiple users really exist, extract the pipeline into a standalone service with authentication
4. **Team Growth:** onboard a new member yourself and see whether the documentation holds up

### Skills to Develop

- **Immediate:** Python basics, Streamlit components and state management
- **3 months:** audio processing, prompt engineering and structured output, evaluation method
- **6 months:** containers and deployment, system design, medical data compliance practice

## Success Metrics

Your technical implementation succeeds when:

- [ ] "upload segments → stitch → transcribe → preprocess → extract 15 fields → review → export" runs end to end without crashing
- [ ] Golden-set ASR CER ≤15% (with the sample-size limitation stated honestly)
- [ ] Field-level F1-Score ≥85% for the 15 specified fields
- [ ] End-to-end latency ≤15 seconds for 1–3 minutes of audio (if missed, record the actual value explicitly)
- [ ] A field that was never dictated renders as `not_mentioned`, with no invented finding
- [ ] A case where the doctor corrects themselves ends with the later statement as the final value, and the change is logged in `override_log`
- [ ] Every exported artifact carries the watermark and contains no write to any EHR
- [ ] Missing or misordered segments are detected and reported rather than silently stitched
- [ ] You can add one field or one rule yourself
- [ ] After deployment on the intranet, you can complete an update yourself
- [ ] Software-layer monthly cost is 0 (compute only)

## Open Questions

1. **LLM and runtime selection (TBD):** which local model and which runtime (Ollama / llama.cpp / vLLM)? Your target machine's VRAM/RAM specification is needed to decide. This design only fixes the constraint "local + JSON-constrainable".
2. **Type-checking tool (TBD):** should mypy be added? If so, the JSON metadata in this document needs a `typecheck` command.
3. **AI coding assistant (TBD):** you deferred this. The default suggestion is the free route (Continue/Cline + local model); once confirmed, write it back to the Handoff Context `AI coding tool` field.
4. **Segment ordering guarantees (TBD):** the stitched timeline is only as correct as the upload order. Do we rely on the doctor's ordering alone, or add a sanity check (recording timestamps in the filename, a duration-based warning) before stitching?
5. **Mixed-device segment quality (TBD):** what is the accepted behaviour when segments differ in sample rate, channel count, or loudness — normalise silently, or warn the doctor and let them confirm?
6. **Multi-user access and authentication (TBD):** the MVP has no account system. If Beta needs several doctors, do we accept adding authentication and an audit trail? Without it, that gap cannot be closed.
7. **Realism of the latency target (TBD):** ≤15 seconds is the PRD target; two LLM passes plus stitching must be measured on the target machine before confirming, and before accepting a downgrade.
8. **Compliance review path (institution to confirm):** who reviews the local deployment and the de-identification process, and when?
9. **Golden-set expansion (TBD):** the current set is only enough for anti-regression checks; expand if statistically meaningful conclusions are needed. Per-field F1 needs per-field sample counts to be reportable.

---

*Created for: ColoStruct*
*Your Path: Balanced Learning Approach*
*Estimated Time: about 2 weeks to a runnable MVP (10.27)*
*Support: Available through AI + communities*

## Handoff Context
<!-- Summary for the next workflow step. Keep this block with the saved document. -->
- Stage: techdesign
- App name: ColoStruct
- User level: C  (A = vibe coder, B = developer, C = in-between)
- Target platform: Web (browser, desktop/laptop first)
- Budget: free/open-source components only; 0 software subscription; compute provided by the institution
- Timeline: as fast as possible (about 2 weeks to run, aligned with 10.27 Runnable MVP; 12.01 Beta; 12.08 Demo Day; 12.15 archive)
- AI in product scope: yes (multilingual ASR transcription, rule-independent preprocessing with slip-of-the-tongue correction and temporal override, extraction of the 15 colorectal pathology fields, post-hoc validation support, export watermarking)
- Chosen stack: frontend Streamlit (ordered multi-segment audio upload, no recording component); processing pipeline as a Python 3.11 module tree inside the Streamlit process (no separate backend service); audio stitching pydub + ffmpeg to 16 kHz mono with 0.5 s silence between segments; ASR faster-whisper (local) with global timestamps; LLM local open-source model with Pydantic/JSON Schema constraint (specific model TBD); storage SQLite + local file system; deployment intranet Docker. **Not included:** account authentication, payment, analytics tracking, public hosting, cloud database, any write to the HA EHR/eHR
- AI coding tool: undecided (default suggestion Continue/Cline + local model, awaiting user confirmation)
- Constraints: data must not leave the institution; all testing on de-identified synthetic data; Hong Kong Hospital Authority (HA) standards and ICD-10 coding; no write of any kind to the HA EHR/eHR production database; ≤15 seconds latency for 1–3 minutes of audio; CER ≤15%; field-level F1-Score ≥85% for the 15 specified pathology fields
- Decisions: Python + Streamlit monolith rather than a split frontend/backend or a no-code builder; multiple ordered audio segments are stitched on the backend with pydub into one 16 kHz mono timeline with a recorded offset per segment, and the in-browser recorder is removed; the rule layer performs de-noising only (fillers, duplicated fragments, surface forms) and logs every removal, while slip-of-the-tongue correction and temporal override are performed by the LLM preprocessing pass and recorded in `override_log`; LLM output is constrained by Pydantic/JSON Schema with at most 2 retries before a warned degradation; fields without evidence must be `not_mentioned`; the schema module is `pathology_schema.py` and the draft table is `pathology_extractions` (foreign key `extraction_id` in `validations` and `exports`); `validate.py` is a post-hoc audit that verifies the model's override decisions against the transcript; the EHR adapter remains a stub with no write/submit method; the MVP has no account system and relies on OS- and session-level access control, with that audit gap recorded as open
- Open questions: LLM and runtime selection (needs the target machine's VRAM/RAM); type-checking tool; AI coding assistant; segment ordering guarantees before stitching; mixed-device segment normalisation behaviour; whether Beta needs authentication and an audit trail; whether ≤15 seconds is achievable in practice; compliance review owner and timing; expansion of the golden set beyond anti-regression size; per-field F1 sample counts
- Research status: Part 1 operational research is available (session file `colorectal-surgery-ai-doctor-assistant-ops-research.md`); its conclusion is that "≥50% documentation time saving" must be verified with a golden set plus Python CER/F1 evaluation; project-level verification has not yet been run
- Source files: part3-tech-design-mvp.md (Part 3 generator prompt), colostruct-mvp-prd.md (Part 2 PRD), prd-clarifying-questions-answers.md (Q1–Q11 answers), colorectal-surgery-ai-doctor-assistant-ops-research.md (Part 1 research), Colorectal cancer reporting checklist (field authority, 15 items) → docs/TechDesign-ColoStruct-MVP.md

```json
{
  "schemaVersion": 1,
  "documentType": "techdesign",
  "appName": "ColoStruct",
  "stack": {
    "frontend": "Streamlit",
    "backend": "Python 3.11 modular pipeline (inside the Streamlit process, no separate service)",
    "database": "SQLite + local file system",
    "styling": "Streamlit built-in theme + a small amount of custom CSS",
    "deployment": "Intranet Docker (institutional server / local workstation)"
  },
  "commands": {
    "setup": "pip install -r requirements.txt",
    "dev": "streamlit run app.py",
    "test": "pytest -q",
    "typecheck": "",
    "lint": "ruff check .",
    "build": ""
  },
  "aiScope": "in-app AI"
}
```
