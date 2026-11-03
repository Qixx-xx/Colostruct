# Research: Colorectal Surgery Outpatient AI Doctor Assistant — Project Operations Research (Client Review Version)

> English Version

## Q1. What's your app idea? Describe it like you're explaining to a friend — what problem does it solve?

It is a web-based AI clinical documentation assistant for colorectal surgery outpatient clinics in Hong Kong public hospitals. After a doctor sees a patient, they can record or upload a 1–5 minute voice note. The system uses multilingual ASR to transcribe Cantonese, English, and medical abbreviations, then uses an LLM to extract clinical elements into a structured SOAP draft. The doctor reviews and edits the draft in a dual-column UI and exports it as Markdown or JSON. It solves the problem of doctors spending too much time handwriting or formatting formal records, such as outpatient notes and discharge summaries.

## Q2. Who needs this most? Describe your ideal user.

The ideal user is a busy colorectal surgery doctor in a Hong Kong public hospital, especially those working in high-volume outpatient clinics. They need to document diagnosis, pathology, colonoscopy/imaging results, and follow-up plans efficiently. Secondary users may include residents/registrars and clinic support staff who help prepare medical records.

## Q3. What's out there already? Name any similar apps or current solutions people use.

Current alternatives include manual typing into HA EHR/eHR templates, handwriting notes, generic dictation software, and general AI scribes. The source document does not name a specific competitor. However, existing tools are not described as optimized for Cantonese–English–medical abbreviation code-mixing or colorectal surgery SOAP documentation.

## Q4. What would make someone choose YOUR app? What's the special sauce?

The special sauce is specialty-specific and compliance-aware:

- Colorectal surgery ASR hotwords, such as CRC, CEA, CT, MRI, colonoscopy, anastomosis, stoma, TNM, and neoadjuvant therapy.
- Strong handling of Cantonese, English, and medical abbreviations.
- Temporal correction: later statements override earlier ones.
- Hallucination guard: unsupported items are marked as `[not mentioned]` instead of being invented.
- Human-in-the-loop dual-column review.
- Safe export only: no direct write-back to the hospital core database.
- Local/private deployment options for Hong Kong hospital compliance.

## Q5. What are the 3 absolute must-have features for launch? Just the essentials!

1. Web-based audio recording/upload + multilingual ASR with colorectal surgery hotwords.
2. LLM-based SOAP structuring with rule/hallucination validation and temporal correction.
3. Dual-column doctor review UI + one-click Markdown/JSON export with an "AI-assisted draft" watermark.

## Q6. How do you imagine people using this — phone app, website, or both?

Website/web app first. It should run in a desktop or laptop browser in the clinic, because doctors need a dual-column review interface. Mobile or tablet support can be a later extension, but it is not essential for launch.

## Q7. What's your timeline? Days, weeks, or months to launch?

Recommended phased timeline:

- 2–4 weeks: Streamlit prototype.
- 6–8 weeks: pilot-ready product.
- About 3 months: clinical validation and workflow pilot.

This is a planning estimate, not a fixed source commitment.

## Q8. Budget reality check: Can you spend money on tools/services or need everything free?

Hybrid approach. The prototype can start with free or low-cost tools such as Streamlit and open-source models. However, to meet CER ≤15%, structure accuracy ≥85%, latency ≤15 seconds, and medical privacy requirements, budget is needed for ASR/LLM APIs or local GPU infrastructure. On-premises/private deployment will likely require infrastructure and model licensing costs.

## Q9. Should the research evaluate AI product features, automation, ChatGPT/MCP surfaces, local/private model options, or only AI-assisted development?

The research should evaluate AI product features and automation, including ASR, SOAP extraction, hallucination guard, temporal correction, dual-column review, and export. It should also evaluate local/private model options and on-premises deployment for compliance. It should not be limited to AI-assisted development. ChatGPT/MCP surfaces can be explored as optional integration patterns, but local/private models should be the primary research track for Hong Kong public hospital use.

## Research Conclusion

The operations research should confirm whether the workflow can reduce documentation time by ≥50% while meeting accuracy, latency, and compliance targets, using a 4-case golden dataset and Python-based CER/F1 evaluation.
