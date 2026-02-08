# SSI Extraction App

Minimal UI application to extract securities settlement instructions from PDF files.

## What it does

- Extracts per-page text and tables using `pdfplumber`.
- Sends chunked payloads to an OpenAI-compatible endpoint using the OpenAI Python SDK.
- Normalizes results into three buckets:
  - `records` (standard market SSI rows)
  - `us_securities_settlement` (USA 2-column table variants)
  - `cash_settlement` (currency/bank details)
- Persists normalized output into SQLite for one-time extraction and repeated querying.
- Provides DB views and chat-style question interface over extracted SSI data.
- Supports search and CSV/JSON download in UI.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## SQLite workflow

- DB path is configurable from sidebar (default: `data/ssi.sqlite`).
- On upload, extraction output is written into normalized table `ssi_records`.
- You can choose whether new upload refreshes DB (`Refresh DB when uploading a new PDF`).
- After extraction, users can query existing DB without re-uploading PDF.

## LLM config file

LLM settings are loaded from `config/llm_config.json`.

Example:

```json
{
  "base_url": "https://internal-llm/v1",
  "api_key": "xxxxxxx",
  "model": "internalLM",
  "temperature": 0.0,
  "max_tokens": 4096,
  "request_timeout_s": 120,
  "pages_per_chunk": 3,
  "stream": true,
  "verify_ssl": false
}
```

You can point the UI to a different JSON config path from the sidebar.

## Output schema

```json
{
  "records": [{"market": "", "agent_or_clearing_org": "", "swift_address": "", "account_details": [], "source": {"page_number": 0, "table_index": 0, "row_index": 0}}],
  "us_securities_settlement": [{"instruction_type": "", "details": "", "source": {"page_number": 0, "table_index": 0, "row_index": 0}}],
  "cash_settlement": [{"currency": "", "intermediate_institution_56a": "", "account_with_institution_57a": "", "beneficiary_59a_or_59f": "", "source": {"page_number": 0, "table_index": 0, "row_index": 0}}],
  "notes": []
}
```

## Notes

- Designed for airgapped usage with local model serving.
- If your endpoint does not support `response_format`, the client automatically retries without it.
- Stage logs are printed in the Streamlit terminal output for:
  - PDF extraction start/completion and per-page table counts
  - LLM preflight connectivity check (`/models`)
  - LLM request start and completion timings for each chunk
  - Streaming diagnostics (`events`, `first_token_s`) when `stream=true`
  - Explicit timeout and HTTP error details per chunk
  - SQLite initialization, refresh, and persistence stats

## Chat examples

- `list down all the SSIs and break it down by type of SSI, country, currency, account number, swift code, beneficiary bank and BIC code, beneficiary bank account number and additional info if any`
- `count by type`
- `count by country`
- `show cash settlement`
- `list rows for AUD`
