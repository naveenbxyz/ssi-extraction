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


def _find_matching_bracket(text: str, start_idx: int, open_char: str, close_char: str) -> int:
    depth = 0
    in_string = False
    escaped = False

    for idx in range(start_idx, len(text)):
        ch = text[idx]

        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return idx

    return -1


def _extract_array_text(text: str, key: str) -> str | None:
    pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*\[', re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None

    array_start = text.find("[", match.start())
    if array_start == -1:
        return None

    array_end = _find_matching_bracket(text, array_start, "[", "]")
    if array_end == -1:
        return None

    return text[array_start : array_end + 1]


def _split_top_level_objects(array_body: str) -> list[str]:
    objects: list[str] = []
    depth = 0
    in_string = False
    escaped = False
    obj_start = -1

    for idx, ch in enumerate(array_body):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            if depth == 0:
                obj_start = idx
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and obj_start != -1:
                objects.append(array_body[obj_start : idx + 1])
                obj_start = -1

    return objects


def _parse_notes_with_recovery(text: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    notes_text = _extract_array_text(text, "notes")
    if notes_text is None:
        return [], warnings

    try:
        parsed = json.loads(notes_text)
        if isinstance(parsed, list):
            notes = [str(item) for item in parsed if isinstance(item, (str, int, float))]
            return notes, warnings
    except json.JSONDecodeError as exc:
        warnings.append(f"notes parse failed: {exc.msg}")

    # Fallback: string literal extraction inside notes array text
    notes = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', notes_text)
    notes = [n.encode("utf-8").decode("unicode_escape") for n in notes]
    if not notes:
        warnings.append("notes recovery found no valid entries")
    return notes, warnings


def _recover_array_objects(text: str, key: str) -> tuple[list[dict[str, Any]], list[str]]:
    recovered: list[dict[str, Any]] = []
    warnings: list[str] = []

    array_text = _extract_array_text(text, key)
    if array_text is None:
        warnings.append(f"{key}: array not found")
        return recovered, warnings

    inner = array_text[1:-1]
    object_candidates = _split_top_level_objects(inner)
    if not object_candidates:
        try:
            parsed = json.loads(array_text)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        recovered.append(item)
                    else:
                        warnings.append(f"{key}: skipped non-object entry")
                return recovered, warnings
        except json.JSONDecodeError as exc:
            warnings.append(f"{key}: array parse failed: {exc.msg}")
            return recovered, warnings

        return recovered, warnings

    for idx, candidate in enumerate(object_candidates, start=1):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                recovered.append(parsed)
            else:
                warnings.append(f"{key}[{idx}]: skipped non-object entry")
        except json.JSONDecodeError as exc:
            warnings.append(f"{key}[{idx}]: skipped malformed object ({exc.msg})")

    return recovered, warnings


def parse_chunk_result_with_recovery(
    text: str,
) -> tuple[dict[str, list[dict[str, Any]] | list[str]], list[str]]:
    """
    Parse model output with tolerant recovery.

    Strategy:
    1) Try strict object parse first.
    2) On failure, recover each array key independently and skip malformed items.
    3) Return warnings rather than raising, so pipeline can continue.
    """
    warnings: list[str] = []

    try:
        strict = extract_json_object(text)
        normalized = normalize_chunk_result(strict)
        return normalized, warnings
    except Exception as exc:
        warnings.append(f"strict parse failed: {exc}")

    records, record_warnings = _recover_array_objects(text, "records")
    us_rows, us_warnings = _recover_array_objects(text, "us_securities_settlement")
    cash_rows, cash_warnings = _recover_array_objects(text, "cash_settlement")
    notes, note_warnings = _parse_notes_with_recovery(text)

    warnings.extend(record_warnings)
    warnings.extend(us_warnings)
    warnings.extend(cash_warnings)
    warnings.extend(note_warnings)

    payload: dict[str, list[dict[str, Any]] | list[str]] = {
        "records": records,
        "us_securities_settlement": us_rows,
        "cash_settlement": cash_rows,
        "notes": notes,
    }
    return payload, warnings
