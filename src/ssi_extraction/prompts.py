from __future__ import annotations

import json


SYSTEM_PROMPT = """
You are an expert coding agent running on a Sonnet model, and you also specialize in high-precision structured data extraction.
You are an expert at extracting Securities Settlement Instructions (SSI) from noisy table/text data.
Return strict JSON only.

Extraction target schema:
{
  "records": [
    {
      "market": "string",
      "agent_or_clearing_org": "string",
      "swift_address": "string",
      "account_details": ["string"],
      "source": {"page_number": 0, "table_index": 0, "row_index": 0}
    }
  ],
  "us_securities_settlement": [
    {
      "instruction_type": "Delivery vs Payment | Free of Payment | other",
      "details": "string",
      "source": {"page_number": 0, "table_index": 0, "row_index": 0}
    }
  ],
  "cash_settlement": [
    {
      "currency": "string",
      "intermediate_institution_56a": "string",
      "account_with_institution_57a": "string",
      "beneficiary_59a_or_59f": "string",
      "source": {"page_number": 0, "table_index": 0, "row_index": 0}
    }
  ],
  "notes": ["string"]
}

Rules:
- Preserve original values; do not fabricate missing fields.
- If field is unknown, use empty string.
- If a row contains extra account lines (BSB, customer account, address), include them in the nearest relevant field as newline-separated text.
- Map known variants:
  - Standard market SSI rows -> records.
  - USA 2-column securities settlement table -> us_securities_settlement.
  - Currency + bank detail rows -> cash_settlement.
- Ignore decorative titles/footers/page numbers.
- Never return markdown code fences.
""".strip()


def build_user_prompt(page_payload: list[dict]) -> str:
    return (
        "Extract structured SSI JSON from the following page payload. "
        "Input JSON:\n"
        f"{json.dumps(page_payload, ensure_ascii=True)}"
    )
