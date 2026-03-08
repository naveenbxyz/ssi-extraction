from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from .isda_config import load_isda_config
from .isda_docx_extractor import extract_docx_payload
from .llm_client import LocalOpenAICompatibleClient
from .models import LLMSettings
from .parser import extract_json_object

logger = logging.getLogger(__name__)

FIELD_CATALOG_KEYS = [
    "attributeId",
    "attributeArea",
    "attributeName",
    "formType",
    "allowedValuesRaw",
    "allowedValues",
    "populationMethod",
    "category",
]


def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _infer_field_name(raw_key: str) -> str:
    key = raw_key.strip().lower()
    key = re.sub(r"[\r\n\t]+", " ", key)
    key = re.sub(r"[^a-z0-9]+", "_", key)
    key = re.sub(r"_+", "_", key).strip("_")
    if not key or re.fullmatch(r"\d+", key) or len(key) < 3:
        return ""
    return key[:120]


def _normalize_allowed_values(value: Any) -> Optional[list[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        normalized = [str(item).strip() for item in value if str(item).strip()]
        return normalized or None
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else None
    cleaned = str(value).strip()
    return [cleaned] if cleaned else None


def _extract_catalog_metadata(entry: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    metadata: dict[str, Any] = {}
    for key in FIELD_CATALOG_KEYS:
        if key == "allowedValues":
            metadata[key] = _normalize_allowed_values(entry.get(key))
        else:
            metadata[key] = entry.get(key)
    return metadata


def _build_field_catalog_index(field_catalog: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for entry in field_catalog:
        attribute_name = str(entry.get("attributeName", "")).strip()
        if not attribute_name:
            continue
        index[_normalize_key(attribute_name)] = entry
    return index


def _match_field_catalog_entry(
    key: str,
    field_catalog_index: dict[str, dict[str, Any]],
) -> Optional[dict[str, Any]]:
    normalized = _normalize_key(key)
    if not normalized:
        return None
    if normalized in field_catalog_index:
        return field_catalog_index[normalized]

    best_match: Optional[dict[str, Any]] = None
    best_score = 0
    for catalog_key, entry in field_catalog_index.items():
        if not catalog_key:
            continue
        if catalog_key in normalized or normalized in catalog_key:
            score = len(catalog_key)
            if score > best_score:
                best_match = entry
                best_score = score
    return best_match


def _merge_field_value(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    if incoming["value"] not in target["value"]:
        target["value"] = f"{target['value']} ; {incoming['value']}"

    incoming_notes = str(incoming.get("notes", "")).strip()
    if incoming_notes and incoming_notes not in str(target.get("notes", "")):
        if target.get("notes"):
            target["notes"] = f"{target['notes']} | {incoming_notes}"
        else:
            target["notes"] = incoming_notes

    for key in FIELD_CATALOG_KEYS:
        if (not target.get(key)) and incoming.get(key):
            target[key] = incoming.get(key)


def _dedupe_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for field in fields:
        field_name = str(field.get("field_name", "")).strip()
        value = str(field.get("value", "")).strip()
        if not field_name or not value:
            continue
        if field_name not in by_name:
            by_name[field_name] = field
            continue
        _merge_field_value(by_name[field_name], field)
    return list(by_name.values())


def _normalize_field_entries(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("field_name", "")).strip()
        value = str(item.get("value", "")).strip()
        source = str(item.get("source", "")).strip() or "inferred"
        notes = str(item.get("notes", "")).strip()
        if not field_name or not value:
            continue
        normalized.append(
            {
                "field_name": field_name,
                "value": value,
                "source": source,
                "notes": notes,
                "attributeId": str(item.get("attributeId", "")).strip(),
                "attributeArea": str(item.get("attributeArea", "")).strip(),
                "attributeName": str(item.get("attributeName", "")).strip(),
                "formType": str(item.get("formType", "")).strip(),
                "allowedValuesRaw": str(item.get("allowedValuesRaw", "")).strip(),
                "allowedValues": _normalize_allowed_values(item.get("allowedValues")),
                "populationMethod": str(item.get("populationMethod", "")).strip(),
                "category": str(item.get("category", "")).strip(),
            }
        )
    return normalized


def _annotate_with_catalog(
    fields: list[dict[str, Any]],
    field_catalog_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for field in fields:
        catalog_entry = None
        if field.get("attributeName"):
            catalog_entry = _match_field_catalog_entry(str(field.get("attributeName", "")), field_catalog_index)
        if catalog_entry is None:
            catalog_entry = _match_field_catalog_entry(str(field.get("field_name", "")), field_catalog_index)

        if catalog_entry is not None:
            normalized_field_name = _infer_field_name(str(catalog_entry.get("attributeName", "")))
            if normalized_field_name:
                field["field_name"] = normalized_field_name
            for key, value in _extract_catalog_metadata(catalog_entry).items():
                if key == "allowedValues":
                    field[key] = _normalize_allowed_values(value)
                elif not field.get(key):
                    field[key] = value
        annotated.append(field)
    return annotated


def _partition_fields_by_catalog_match(
    fields: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for field in fields:
        if str(field.get("attributeName", "")).strip():
            matched.append(field)
        else:
            unmatched.append(field)
    return matched, unmatched


def _build_mapping_summary(
    normalized_fields: list[dict[str, Any]],
    additional_fields: list[dict[str, Any]],
    field_catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    catalog_attribute_names = {
        _normalize_key(str(entry.get("attributeName", "")))
        for entry in field_catalog
        if str(entry.get("attributeName", "")).strip()
    }
    mapped_attribute_names = {
        _normalize_key(str(field.get("attributeName", "")))
        for field in normalized_fields
        if str(field.get("attributeName", "")).strip()
    }
    mapped_attribute_count = len(mapped_attribute_names)
    catalog_attribute_count = len(catalog_attribute_names)
    coverage_percent = 0.0
    if catalog_attribute_count > 0:
        coverage_percent = round((mapped_attribute_count / catalog_attribute_count) * 100, 1)

    return {
        "catalog_attribute_count": catalog_attribute_count,
        "mapped_attribute_count": mapped_attribute_count,
        "unmapped_catalog_attribute_count": max(catalog_attribute_count - mapped_attribute_count, 0),
        "unmatched_document_field_count": len(additional_fields),
        "extracted_field_count": len(normalized_fields) + len(additional_fields),
        "coverage_percent": coverage_percent,
    }


def _rule_based_seed(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    field_catalog = config.get("field_catalog", [])
    field_catalog_index = (
        _build_field_catalog_index(field_catalog) if isinstance(field_catalog, list) else {}
    )

    matched_fields: dict[str, dict[str, Any]] = {}
    additional_fields: list[dict[str, Any]] = []

    for item in payload.get("key_value_candidates", []):
        key = str(item.get("key", "")).strip()
        value = str(item.get("value", "")).strip()
        question_number_raw = item.get("question_number")
        question_number = question_number_raw if isinstance(question_number_raw, int) else None
        if not key or not value:
            continue

        source_note = f"Derived from table key: {key}"
        if question_number is not None:
            source_note = f"Derived from question {question_number}: {key}"

        catalog_entry = _match_field_catalog_entry(key, field_catalog_index)
        if catalog_entry is not None:
            field_name = _infer_field_name(str(catalog_entry.get("attributeName", "")))
            if not field_name:
                continue
            incoming = {
                "field_name": field_name,
                "value": value,
                "source": "table",
                "notes": f"{source_note} | matched_field_catalog",
                **_extract_catalog_metadata(catalog_entry),
            }
            existing = matched_fields.get(field_name)
            if existing is None:
                matched_fields[field_name] = incoming
            else:
                _merge_field_value(existing, incoming)
            continue

        additional_fields.append(
            {
                "field_name": _infer_field_name(key) or key,
                "value": value,
                "source": "table",
                "notes": f"{source_note} | no_field_catalog_match",
            }
        )

    normalized_fields = list(matched_fields.values())

    country = ""
    jurisdiction = ""
    for field in normalized_fields:
        if field["field_name"] == "country" and field.get("value"):
            country = field["value"]
        if field["field_name"] == "jurisdiction" and field.get("value"):
            jurisdiction = field["value"]

    return {
        "country": country,
        "jurisdiction": jurisdiction,
        "summary": "",
        "normalized_fields": normalized_fields,
        "additional_fields": additional_fields,
        "notes": ["rule_based_seed_generated"],
    }


def _build_extraction_user_prompt(raw_payload: dict[str, Any], seed: dict[str, Any], config: dict[str, Any]) -> str:
    schema = {
        "country": "string",
        "jurisdiction": "string",
        "summary": "string",
        "normalized_fields": [
            {
                "field_name": "string",
                "value": "string",
                "source": "table | narrative | inferred",
                "notes": "string",
                "attributeId": "string | empty",
                "attributeArea": "string | empty",
                "attributeName": "string | empty",
                "formType": "string | empty",
                "allowedValuesRaw": "string | empty",
                "allowedValues": ["string"] or None,
                "populationMethod": "string | empty",
                "category": "string | empty",
            }
        ],
        "additional_fields": [
            {
                "field_name": "string",
                "value": "string",
                "source": "table | narrative | inferred",
                "notes": "string",
                "attributeId": "string | empty",
                "attributeArea": "string | empty",
                "attributeName": "string | empty",
                "formType": "string | empty",
                "allowedValuesRaw": "string | empty",
                "allowedValues": ["string"] or None,
                "populationMethod": "string | empty",
                "category": "string | empty",
            }
        ],
        "notes": ["string"],
    }

    field_catalog = config.get("field_catalog", [])

    return (
        "Extract ISDA Netting Review data into JSON. Use table values as primary source of truth. "
        "Use narrative only if table value is missing.\n\n"
        "Important table interpretation rules:\n"
        "- Column 1 is typically only a serial number and must be ignored as an attribute key.\n"
        "- Column 2 usually contains attribute/question text (this is the key).\n"
        "- Column 3 (and any following columns) contain the value.\n"
        "- Do not produce numeric field names like '1', '2', etc.\n\n"
        f"Target schema:\n{json.dumps(schema, ensure_ascii=True)}\n\n"
        "The field catalog is the primary and only canonical attribute-definition source.\n"
        "Match extracted fields to the closest field catalog entry using attributeName.\n"
        "Do not use attributeId for matching because it may include category prefixes such as "
        "'Collateral:', 'ISDA:', or 'Generic:'.\n"
        "Do not constrain extraction to any legacy 23-question template or question-number map.\n"
        "If a confident field catalog match exists, place the item in normalized_fields and populate "
        "attributeId, attributeArea, attributeName, formType, allowedValuesRaw, allowedValues, "
        "populationMethod, and category from the catalog entry.\n"
        "If no confident field catalog match exists, place the item in additional_fields instead of "
        "inventing a canonical field.\n"
        "Keep field_name as a meaningful snake_case identifier derived from the matched attributeName "
        "for normalized_fields, or from the document label for additional_fields.\n\n"
        f"Field catalog entries (if available):\n{json.dumps(field_catalog, ensure_ascii=True)}\n\n"
        f"Rule-based seed:\n{json.dumps(seed, ensure_ascii=True)}\n\n"
        f"DOCX raw payload:\n{json.dumps(raw_payload, ensure_ascii=True)}"
    )


def _merge_llm_and_seed(
    llm_payload: Optional[dict[str, Any]],
    seed: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    field_catalog = config.get("field_catalog", [])
    field_catalog_index = (
        _build_field_catalog_index(field_catalog) if isinstance(field_catalog, list) else {}
    )

    llm_fields = _normalize_field_entries(llm_payload.get("normalized_fields") if llm_payload else None)
    llm_additional = _normalize_field_entries(llm_payload.get("additional_fields") if llm_payload else None)
    seed_fields = _normalize_field_entries(seed.get("normalized_fields"))
    seed_additional = _normalize_field_entries(seed.get("additional_fields"))

    combined_fields = _annotate_with_catalog(
        _dedupe_fields(seed_fields + llm_fields + llm_additional + seed_additional),
        field_catalog_index,
    )
    normalized_fields, additional_fields = _partition_fields_by_catalog_match(combined_fields)
    normalized_fields = _dedupe_fields(normalized_fields)
    additional_fields = _dedupe_fields(additional_fields)

    country = ""
    jurisdiction = ""
    summary = ""
    notes: list[str] = []

    if llm_payload is not None:
        country = str(llm_payload.get("country", "")).strip()
        jurisdiction = str(llm_payload.get("jurisdiction", "")).strip()
        summary = str(llm_payload.get("summary", "")).strip()
        raw_notes = llm_payload.get("notes", [])
        if isinstance(raw_notes, list):
            notes.extend([str(item) for item in raw_notes if str(item).strip()])

    if not country:
        country = str(seed.get("country", "")).strip()
    if not jurisdiction:
        jurisdiction = str(seed.get("jurisdiction", "")).strip()

    raw_seed_notes = seed.get("notes", [])
    if isinstance(raw_seed_notes, list):
        notes.extend([str(item) for item in raw_seed_notes if str(item).strip()])

    return {
        "country": country,
        "jurisdiction": jurisdiction,
        "summary": summary,
        "normalized_fields": normalized_fields,
        "additional_fields": additional_fields,
        "mapping_summary": _build_mapping_summary(normalized_fields, additional_fields, field_catalog),
        "notes": notes,
    }


def run_isda_extraction_pipeline(
    docx_path: str,
    settings: LLMSettings,
    isda_config_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    logger.info("ISDA extraction pipeline started docx_path=%s", docx_path)
    config = load_isda_config(isda_config_path)
    raw_payload = extract_docx_payload(docx_path)
    seed = _rule_based_seed(raw_payload, config)

    llm_payload: Optional[dict[str, Any]] = None
    client = LocalOpenAICompatibleClient(settings)
    try:
        client.log_connectivity()
        content = client.ask_text(
            system_prompt=str(config.get("extraction_system_prompt", "")),
            user_prompt=_build_extraction_user_prompt(raw_payload, seed, config),
            task_label="isda_extraction",
        )
        try:
            parsed = extract_json_object(content)
            if isinstance(parsed, dict):
                llm_payload = parsed
        except Exception as exc:
            seed_notes = seed.get("notes")
            if isinstance(seed_notes, list):
                seed_notes.append(f"llm_parse_error: {exc}")
            logger.warning("ISDA LLM parse failed; using seed data error=%s", exc)
    finally:
        client.close()

    merged = _merge_llm_and_seed(llm_payload, seed, config)

    if not merged.get("country"):
        for field in merged.get("normalized_fields", []):
            if field.get("field_name") == "country" and field.get("value"):
                merged["country"] = field["value"]
                break
    if not merged.get("country"):
        for field in merged.get("additional_fields", []):
            if field.get("field_name") == "country" and field.get("value"):
                merged["country"] = field["value"]
                break

    if not merged.get("jurisdiction"):
        for field in merged.get("normalized_fields", []):
            if field.get("field_name") == "jurisdiction" and field.get("value"):
                merged["jurisdiction"] = field["value"]
                break
    if not merged.get("jurisdiction"):
        for field in merged.get("additional_fields", []):
            if field.get("field_name") == "jurisdiction" and field.get("value"):
                merged["jurisdiction"] = field["value"]
                break

    if not merged.get("country") and merged.get("jurisdiction"):
        merged["country"] = str(merged["jurisdiction"])

    logger.info(
        "ISDA extraction pipeline completed country=%s jurisdiction=%s mapped_attribute_count=%d unmatched_document_field_count=%d",
        merged.get("country", ""),
        merged.get("jurisdiction", ""),
        int(merged.get("mapping_summary", {}).get("mapped_attribute_count", 0)),
        int(merged.get("mapping_summary", {}).get("unmatched_document_field_count", 0)),
    )
    return raw_payload, merged
