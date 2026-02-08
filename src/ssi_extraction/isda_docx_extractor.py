from __future__ import annotations

import logging
from pathlib import Path
import re

logger = logging.getLogger(__name__)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").strip().split())


def _is_serial_number(text: str) -> bool:
    token = text.strip()
    if not token:
        return False
    return re.fullmatch(r"\d+[.)]?", token) is not None


def _row_to_key_value(cells: list[str]) -> tuple[str, str] | None:
    if not any(cells):
        return None

    # ISDA table convention (primary): col1 = serial number, col2 = attribute/question, col3+ = value.
    if len(cells) >= 3 and _is_serial_number(cells[0]):
        key = cells[1].strip()
        value = " | ".join([c.strip() for c in cells[2:] if c.strip()]).strip()
        if value:
            return key, value

    # Some documents may have blank first cell with key/value shifted right.
    if len(cells) >= 3 and not cells[0].strip() and cells[1].strip():
        key = cells[1].strip()
        value = " | ".join([c.strip() for c in cells[2:] if c.strip()]).strip()
        if value:
            return key, value

    populated = [c for c in cells if c]
    if len(populated) >= 2 and populated[0]:
        key = populated[0]
        value = " | ".join(populated[1:]).strip()
        if value:
            return key, value

    if len(populated) == 1 and ":" in populated[0]:
        left, right = populated[0].split(":", 1)
        key = _clean(left)
        value = _clean(right)
        if key and value:
            return key, value

    return None


def extract_docx_payload(docx_path: str | Path) -> dict:
    logger.info("ISDA DOCX extraction started path=%s", docx_path)
    try:
        from docx import Document  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "python-docx is required for ISDA extraction. Install with: pip install python-docx"
        ) from exc

    document = Document(str(docx_path))

    paragraphs: list[dict] = []
    for idx, para in enumerate(document.paragraphs, start=1):
        text = _clean(para.text)
        if text:
            paragraphs.append({"paragraph_index": idx, "text": text})

    tables: list[dict] = []
    key_value_candidates: list[dict] = []
    for t_idx, table in enumerate(document.tables, start=1):
        row_payloads: list[dict] = []
        for r_idx, row in enumerate(table.rows, start=1):
            cells = [_clean(cell.text) for cell in row.cells]
            if not any(cells):
                continue
            row_payloads.append({"row_index": r_idx, "cells": cells})
            kv = _row_to_key_value(cells)
            if kv:
                key_value_candidates.append(
                    {
                        "table_index": t_idx,
                        "row_index": r_idx,
                        "key": kv[0],
                        "value": kv[1],
                    }
                )

        if row_payloads:
            tables.append({"table_index": t_idx, "rows": row_payloads})

    payload = {
        "paragraphs": paragraphs,
        "tables": tables,
        "key_value_candidates": key_value_candidates,
        "stats": {
            "paragraph_count": len(paragraphs),
            "table_count": len(tables),
            "candidate_count": len(key_value_candidates),
        },
    }
    logger.info(
        "ISDA DOCX extraction completed paragraphs=%d tables=%d kv_candidates=%d",
        len(paragraphs),
        len(tables),
        len(key_value_candidates),
    )
    return payload
