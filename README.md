# SSI + ISDA Extraction App

This project now runs as a split application:

- FastAPI backend for SSI and ISDA extraction, SQLite persistence, read-only SQL, and chat endpoints
- Vite + React frontend with Tailwind and shadcn-style UI primitives for uploads, review flows, and database exploration

## Architecture

### Backend

- Entry point: `python3 app.py`
- FastAPI app: `backend/main.py`
- Existing extraction logic remains under `src/ssi_extraction`
- Default API base URL: `http://127.0.0.1:8000`
- Interactive docs: `http://127.0.0.1:8000/docs`

### Frontend

- App source: `frontend/`
- Dev server: `http://127.0.0.1:5173`

## Run

### 1. Install Python dependencies

```bash
python3 -m pip install -r requirements.txt
```

### 2. Start the FastAPI backend

```bash
python3 app.py
```

### 3. Install frontend dependencies

```bash
cd frontend
npm install
```

### 4. Start the frontend

```bash
cd frontend
npm run dev
```

## SSI workflow

- Upload a PDF with SSI tables
- Extract and normalize data via the configured OpenAI-compatible endpoint
- Persist results into SQLite at `data/ssi.sqlite` by default
- Inspect:
  - latest extraction payload
  - normalized standard, US, and cash settlement views
  - raw page payload from `pdfplumber`
  - read-only SQL query results
  - chat answers grounded in the extraction JSON

SSI SQLite tables:

- `extraction_runs`
- `standard_ssi`
- `us_ssi`
- `cash_settlement_ssi`

## ISDA workflow

- Upload one DOCX at a time
- Extract paragraphs, tables, and key/value candidates with `python-docx`
- Merge rule-based field seeding with LLM normalization
- Persist results into `data/isda_netting.sqlite` by default
- Upsert per `country_key`:
  - new country key inserts a new document
  - existing country key replaces the stored document and its field rows

ISDA SQLite tables:

- `isda_documents`
- `isda_fields`

## Config files

### LLM config

`config/llm_config.json`

### ISDA extraction config

`config/isda_extraction_config.json`

This file controls:

- canonical field names
- alias mapping
- extraction prompt behavior
- chat prompt behavior

## API surface

The backend exposes endpoints for:

- bootstrap and health checks
- SSI extract, summary, latest payload, table views, SQL, and chat
- ISDA extract, summary, document list, document fields, SQL, and chat

## Notes

- Table values are still prioritized over narrative content for ISDA extraction.
- Both workflows persist structured JSON and raw extraction payloads for auditability.
- Chat answers are grounded in extracted JSON context rather than inferred from SQLite rows alone.
