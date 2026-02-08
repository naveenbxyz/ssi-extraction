from __future__ import annotations

import json
import logging
import re
from typing import Any

from .isda_config import load_isda_config
from .isda_docx_extractor import extract_docx_payload
from .llm_client import LocalOpenAICompatibleClient
from .models import LLMSettings
from .parser import extract_json_object

logger = logging.getLogger(__name__)


def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _build_alias_index(field_aliases: dict[str, list[str]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for canonical, aliases in field_aliases.items():
        index[_normalize_key(canonical)] = canonical
        for alias in aliases:
            index[_normalize_key(alias)] = canonical
    return index


def _match_canonical_field(key: str, alias_index: dict[str, str]) -> str | None:
    normalized = _normalize_key(key)
    if normalized in alias_index:
        return alias_index[normalized]

    for alias_norm, canonical in alias_index.items():
        if alias_norm and alias_norm in normalized:
            return canonical
    return None


def _rule_based_seed(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    field_aliases = config.get("field_aliases", {})
    alias_index = _build_alias_index(field_aliases)

    merged_values: dict[str, dict[str, str]] = {}
    additional_fields: list[dict[str, str]] = []

    for item in payload.get("key_value_candidates", []):
        key = str(item.get("key", "")).strip()
        value = str(item.get("value", "")).strip()
        if not key or not value:
            continue

        canonical = _match_canonical_field(key, alias_index)
        if canonical:
            existing = merged_values.get(canonical)
            if existing and value not in existing["value"]:
                existing["value"] = f"{existing['value']} ; {value}"
            elif not existing:
                merged_values[canonical] = {
                    "field_name": canonical,
                    "value": value,
                    "source": "table",
                    "notes": f"Derived from table key: {key}",
                }
        else:
            additional_fields.append(
                {
                    "field_name": key,
                    "value": value,
                    "source": "table",
                    "notes": "Unmapped table key",
                }
            )

    normalized_fields = list(merged_values.values())

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
            }
        ],
        "additional_fields": [
            {
                "field_name": "string",
                "value": "string",
                "source": "table | narrative | inferred",
                "notes": "string",
            }
        ],
        "notes": ["string"],
    }

    canonical_fields = config.get("canonical_fields", [])
    field_aliases = config.get("field_aliases", {})

    return (
        "Extract ISDA Netting Review data into JSON. Use table values as primary source of truth. "
        "Use narrative only if table value is missing.\n\n"
        "Important table interpretation rules:\n"
        "- Column 1 is typically only a serial number and must be ignored as an attribute key.\n"
        "- Column 2 usually contains attribute/question text (this is the key).\n"
        "- Column 3 (and any following columns) contain the value.\n"
        "- Do not produce numeric field names like '1', '2', etc.\n\n"
        f"Target schema:\n{json.dumps(schema, ensure_ascii=True)}\n\n"
        f"Canonical field names to prefer:\n{json.dumps(canonical_fields, ensure_ascii=True)}\n\n"
        f"Field alias mapping:\n{json.dumps(field_aliases, ensure_ascii=True)}\n\n"
        f"Rule-based seed:\n{json.dumps(seed, ensure_ascii=True)}\n\n"
        f"DOCX raw payload:\n{json.dumps(raw_payload, ensure_ascii=True)}"
    )


def _normalize_field_entries(entries: Any) -> list[dict[str, str]]:
    if not isinstance(entries, list):
        return []

    normalized: list[dict[str, str]] = []
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
            }
        )
    return normalized


def _dedupe_fields(fields: list[dict[str, str]]) -> list[dict[str, str]]:
    by_name: dict[str, dict[str, str]] = {}
    for field in fields:
        name = field["field_name"]
        if name not in by_name:
            by_name[name] = field
            continue

        current = by_name[name]
        if field["value"] not in current["value"]:
            current["value"] = f"{current['value']} ; {field['value']}"
            if current.get("notes") and field.get("notes"):
                current["notes"] = f"{current['notes']} | {field['notes']}"
    return list(by_name.values())


def _merge_llm_and_seed(llm_payload: dict[str, Any] | None, seed: dict[str, Any]) -> dict[str, Any]:
    if llm_payload is None:
        return seed

    llm_fields = _normalize_field_entries(llm_payload.get("normalized_fields"))
    llm_additional = _normalize_field_entries(llm_payload.get("additional_fields"))

    seed_fields = _normalize_field_entries(seed.get("normalized_fields"))
    seed_additional = _normalize_field_entries(seed.get("additional_fields"))

    merged_fields = _dedupe_fields(seed_fields + llm_fields)
    merged_additional = _dedupe_fields(seed_additional + llm_additional)

    country = str(llm_payload.get("country", "")).strip() or str(seed.get("country", "")).strip()
    jurisdiction = str(llm_payload.get("jurisdiction", "")).strip() or str(seed.get("jurisdiction", "")).strip()
    summary = str(llm_payload.get("summary", "")).strip()

    notes: list[str] = []
    raw_notes = llm_payload.get("notes", [])
    if isinstance(raw_notes, list):
        notes.extend([str(n) for n in raw_notes if str(n).strip()])
    raw_seed_notes = seed.get("notes", [])
    if isinstance(raw_seed_notes, list):
        notes.extend([str(n) for n in raw_seed_notes if str(n).strip()])

    return {
        "country": country,
        "jurisdiction": jurisdiction,
        "summary": summary,
        "normalized_fields": merged_fields,
        "additional_fields": merged_additional,
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

    llm_payload: dict[str, Any] | None = None
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

    merged = _merge_llm_and_seed(llm_payload, seed)

    if not merged.get("country"):
        for field in merged.get("normalized_fields", []):
            if field.get("field_name") == "country" and field.get("value"):
                merged["country"] = field["value"]

    if not merged.get("jurisdiction"):
        for field in merged.get("normalized_fields", []):
            if field.get("field_name") == "jurisdiction" and field.get("value"):
                merged["jurisdiction"] = field["value"]

    logger.info(
        "ISDA extraction pipeline completed country=%s jurisdiction=%s field_count=%d additional_field_count=%d",
        merged.get("country", ""),
        merged.get("jurisdiction", ""),
        len(merged.get("normalized_fields", [])),
        len(merged.get("additional_fields", [])),
    )
    return raw_payload, merged
