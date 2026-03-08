# SSI + ISDA Extraction App

This project runs as a split application:

- FastAPI backend for SSI and ISDA extraction, SQLite persistence, read-only SQL, and chat endpoints
- Vite + React frontend with Tailwind and shadcn-style UI primitives for uploads, review flows, and database exploration

## What changed

The original Streamlit UI has been replaced with:

- a Python API layer that exposes the existing extraction workflows over HTTP
- a React frontend that owns the interaction state, layout, search, review surfaces, and chat flows

The extraction logic in `src/ssi_extraction/` remains the core of the system.

## Repository layout

```text
.
├── app.py                     # local backend launcher
├── backend/                   # FastAPI app and HTTP endpoints
├── config/                    # LLM and ISDA config JSON files
├── frontend/                  # Vite + React + Tailwind app
├── src/ssi_extraction/        # extraction, LLM, parsing, and SQLite logic
└── README.md
```

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
- Production build output: `frontend/dist`

## Quick start

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

### 5. Open the app

- Frontend: `http://127.0.0.1:5173`
- Backend docs: `http://127.0.0.1:8000/docs`

## Development workflow

### Backend only

```bash
python3 app.py
```

### Frontend only

```bash
cd frontend
npm run dev
```

### Frontend production build

```bash
cd frontend
npm run build
```

## Configuration

### LLM config

Path: `config/llm_config.json`

This file controls the OpenAI-compatible endpoint settings used by both workflows:

- `base_url`
- `api_key`
- `model`
- `temperature`
- `max_tokens`
- `request_timeout_s`
- `pages_per_chunk`
- `stream`
- `verify_ssl`

### ISDA extraction config

Path: `config/isda_extraction_config.json`

This file controls:

- canonical field names
- alias mapping
- question-number mapping
- extraction prompt behavior
- chat prompt behavior

## SSI workflow

- Upload a PDF with SSI tables
- Extract and normalize data via the configured OpenAI-compatible endpoint
- Persist results into SQLite at `data/ssi.sqlite` by default
- Review:
  - latest extraction payload returned by the API
  - normalized standard, US, and cash settlement views
  - raw page payload from `pdfplumber`
  - read-only SQL query results
  - chat answers grounded in extraction JSON

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
- Review:
  - latest extracted document
  - saved document inventory
  - searchable field rows
  - read-only SQL query results
  - chat answers grounded in structured and raw document context

ISDA SQLite tables:

- `isda_documents`
- `isda_fields`

## Backend API surface

The backend exposes endpoints for:

- bootstrap and health checks
- config inspection
- SSI extract, summary, latest payload, table views, SQL, and chat
- ISDA extract, summary, document list, document fields, SQL, and chat

The easiest way to inspect the current API is the FastAPI docs page at `http://127.0.0.1:8000/docs`.

## Design reference

See `design.md` for the current UI and architecture decisions, visual direction, workflow layout, and iteration notes.

## Troubleshooting

### `python3` fails on macOS because of Xcode license

If the local Python binary is blocked by the Xcode command line tools license prompt, accept it once:

```bash
sudo xcodebuild -license
```

Then rerun:

```bash
python3 app.py
```

### Frontend package install

If frontend packages are missing:

```bash
cd frontend
npm install
```

## Notes

- Table values are still prioritized over narrative content for ISDA extraction.
- Both workflows persist structured JSON and raw extraction payloads for auditability.
- Chat answers are grounded in extracted JSON context rather than inferred from SQLite rows alone.
- The current frontend is intentionally structured for iteration; use `design.md` as the source of truth for UI changes.
