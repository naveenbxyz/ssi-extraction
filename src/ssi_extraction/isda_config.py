from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union


DEFAULT_EXTRACTION_SYSTEM_PROMPT = (
    "You are an expert legal operations analyst for ISDA netting reviews. "
    "Extract structured information from table-first DOCX data. "
    "Prefer table values over narrative text when conflicts exist. "
    "The external field catalog is the primary attribute-definition source. "
    "Use attributeName as the matching key, not attributeId. "
    "Return strict JSON only."
)

DEFAULT_CHAT_SYSTEM_PROMPT = (
    "You are an expert legal operations assistant for ISDA netting review documents. "
    "Answer only from the provided extracted JSON and raw DOCX payload context. "
    "If data is missing, say so clearly."
)

DEFAULT_CONFIG = {
    "field_catalog_path": "config/isda_field_catalog.json",
    "field_catalog": [],
    "extraction_system_prompt": DEFAULT_EXTRACTION_SYSTEM_PROMPT,
    "chat_system_prompt": DEFAULT_CHAT_SYSTEM_PROMPT,
}


def _normalize_allowed_values(value: Any) -> Optional[list[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned or None
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else None
    cleaned = str(value).strip()
    return [cleaned] if cleaned else None


def _normalize_allowed_values_raw(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=True)


def _normalize_field_catalog_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "attributeId": str(entry.get("attributeId") or entry.get("attribute_id") or "").strip(),
        "attributeArea": str(entry.get("attributeArea") or entry.get("attribute_area") or "").strip(),
        "attributeName": str(entry.get("attributeName") or entry.get("attribute_name") or "").strip(),
        "formType": str(entry.get("formType") or entry.get("form_type") or "").strip(),
        "allowedValuesRaw": _normalize_allowed_values_raw(
            entry.get("allowedValuesRaw", entry.get("allowed_values_raw"))
        ),
        "allowedValues": _normalize_allowed_values(entry.get("allowedValues", entry.get("allowed_values"))),
        "populationMethod": str(entry.get("populationMethod") or entry.get("population_method") or "").strip(),
        "category": str(entry.get("category") or "").strip(),
    }


def _load_field_catalog_entries(config_path: Path, catalog_path_value: Any) -> list[dict[str, Any]]:
    if not isinstance(catalog_path_value, str) or not catalog_path_value.strip():
        return []

    raw_catalog_path = Path(catalog_path_value.strip())
    candidate_paths: list[Path]
    if raw_catalog_path.is_absolute():
        candidate_paths = [raw_catalog_path]
    else:
        candidate_paths = [
            raw_catalog_path.resolve(),
            (config_path.parent / raw_catalog_path).resolve(),
        ]

    catalog_path = next((candidate for candidate in candidate_paths if candidate.exists()), candidate_paths[0])

    if not catalog_path.exists():
        return []

    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("fields", [])

    if not isinstance(raw, list):
        raise ValueError(f"ISDA field catalog must be a JSON array or object with a 'fields' array: {catalog_path}")

    normalized_entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_field_catalog_entry(item)
        if normalized["attributeName"]:
            normalized_entries.append(normalized)

    return normalized_entries


def load_isda_config(config_path: Union[str, Path]) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return dict(DEFAULT_CONFIG)

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"ISDA config must be a JSON object: {path}")

    merged = dict(DEFAULT_CONFIG)
    merged.update(raw)

    field_catalog_path = merged.get("field_catalog_path", "")
    merged["field_catalog"] = _load_field_catalog_entries(path, field_catalog_path)

    return merged
