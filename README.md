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
- Provides DB views and a chat interface powered by the full extraction JSON context.
- Supports search and CSV/JSON download in UI.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## SQLite workflow

- DB path is configurable from sidebar (default: `data/ssi.sqlite`).
- On upload, extraction output is written into three normalized tables:
  - `standard_ssi`
  - `us_ssi`
  - `cash_settlement_ssi`
- The run metadata table stores both:
  - `extracted_json` (LLM-structured output)
  - `raw_pdf_payload` (raw `pdfplumber` page/table payload sent to LLM)
- You can choose whether new upload refreshes DB (`Refresh DB when uploading a new PDF`).
- After extraction, users can query existing DB without re-uploading PDF.
- Chat uses full extraction JSON (latest in-memory run, or latest persisted run payload from SQLite).
- Database Views includes:
  - latest-run cross-check section with download buttons for both payloads
  - split views for standard SSI / US SSI variants / cash settlement
  - search by account number, account name, BIC, country, currency, and details

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
  "records": [{
    "country_market": "",
    "agent_or_clearing_organization": "",
    "swift_address": "",
    "location": "",
    "account_name": "",
    "account_number": "",
    "beneficiary_bic": "",
    "miscellaneous_details": "",
    "source": {"page_number": 0, "table_index": 0, "row_index": 0}
  }],
  "us_securities_settlement": [{
    "instruction_type": "",
    "details": "",
    "location": "",
    "account_name": "",
    "account_number": "",
    "beneficiary_bic": "",
    "miscellaneous_details": "",
    "source": {"page_number": 0, "table_index": 0, "row_index": 0}
  }],
  "cash_settlement": [{
    "currency": "",
    "intermediate_institution_56a": "",
    "account_with_institution_57a": "",
    "beneficiary_59a_or_59f": "",
    "location": "",
    "account_name": "",
    "account_number": "",
    "beneficiary_bic": "",
    "miscellaneous_details": "",
    "source": {"page_number": 0, "table_index": 0, "row_index": 0}
  }],
  "notes": []
}
```

## Notes

- Designed for airgapped usage with local model serving.
- If your endpoint does not support `response_format`, the client automatically retries without it.
- If model output contains partially malformed JSON, the parser salvages valid records and logs parse warnings instead of aborting the entire run.
- Stage logs are printed in the Streamlit terminal output for:
  - PDF extraction start/completion and per-page table counts
  - LLM preflight connectivity check (`/models`)
  - LLM request start and completion timings for each chunk
  - Streaming diagnostics (`events`, `first_token_s`) when `stream=true`
  - Explicit timeout and HTTP error details per chunk
  - SQLite initialization, refresh, and persistence stats

## Chat examples

- `list down all the SSIs and break it down by type of SSI, country, currency, account number, swift code, beneficiary bank and BIC code, beneficiary bank account number and additional info if any`
- `which countries have most account numbers listed?`
- `show all records with beneficiary bic containing BOFA`
- `summarize cash settlement instructions for AUD and CAD`
