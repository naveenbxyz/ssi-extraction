# SSI + ISDA Extraction App

Minimal Streamlit application for two airgapped workflows:

- SSI extraction from PDF (`pdfplumber` + LLM normalization)
- ISDA Netting Review extraction from DOCX (`python-docx` + hybrid rule/LLM extraction)

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Workflow 1: SSI Extraction

- Upload a PDF with SSI tables.
- Extract + normalize into structured JSON via LLM.
- Persist into SQLite (default: `data/ssi.sqlite`).
- DB model is split into 3 tables:
  - `standard_ssi`
  - `us_ssi`
  - `cash_settlement_ssi`
- JSON Chat uses full extraction JSON context.

## Workflow 2: ISDA Netting Review

- Upload one DOCX at a time.
- DOCX is parsed with `python-docx` (paragraphs + tables + key/value candidates).
- Hybrid extraction:
  - rule-based field seeding from table rows
  - LLM normalization into flexible JSON field list
- Persist into separate SQLite DB (default: `data/isda_netting.sqlite`) with country-level upsert:
  - new country -> insert as new document
  - same country key -> replace only that country document

ISDA DB tables:
- `isda_documents`
- `isda_fields`

## Config files

### LLM config
`config/llm_config.json`

### ISDA extraction config
`config/isda_extraction_config.json`

This file contains:
- `canonical_fields`
- `field_aliases`
- `extraction_system_prompt`
- `chat_system_prompt`

You can edit this file to adjust mapping/prompt behavior without code changes.

## Notes

- Table values are prioritized over narrative content for ISDA extraction.
- Both workflows persist:
  - LLM structured JSON
  - raw extraction payload (for audit/cross-check)
- Chat features are context-based on full extracted JSON payloads.
