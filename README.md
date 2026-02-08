# SSI Extraction App

Minimal UI application to extract securities settlement instructions from PDF files.

## What it does

- Extracts per-page text and tables using `pdfplumber`.
- Sends chunked payloads to a local OpenAI-compatible endpoint (`/v1/chat/completions`).
- Normalizes results into three buckets:
  - `records` (standard market SSI rows)
  - `us_securities_settlement` (USA 2-column table variants)
  - `cash_settlement` (currency/bank details)
- Supports search and CSV/JSON download in UI.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Default endpoint settings:

- Base URL: `http://localhost:8080`
- Model: `Qwen/Qwen3-8B-Instruct`

You can change both from the sidebar.

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
- If your endpoint does not support `response_format`, adjust `src/ssi_extraction/llm_client.py` accordingly.
- Stage logs are printed in the Streamlit terminal output for:
  - PDF extraction start/completion and per-page table counts
  - LLM preflight connectivity check (`/v1/models`)
  - LLM request start/response timings for each chunk
  - Explicit timeout and HTTP error details per chunk
