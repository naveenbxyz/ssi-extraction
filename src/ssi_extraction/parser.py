from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(text: str) -> dict[str, Any]:
    """Best-effort parser for model outputs that may include prose."""
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("Model response does not contain a valid JSON object")


def normalize_chunk_result(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]] | list[str]]:
    return {
        "records": payload.get("records") or [],
        "us_securities_settlement": payload.get("us_securities_settlement") or [],
        "cash_settlement": payload.get("cash_settlement") or [],
        "notes": payload.get("notes") or [],
    }
