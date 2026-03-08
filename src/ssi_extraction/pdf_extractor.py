from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Union

import pdfplumber

from .models import ExtractedPage, ExtractedTable

logger = logging.getLogger(__name__)


def _clean_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").strip()
    return " ".join(text.split())


def _header_from_table(table: list[list[object]]) -> list[str]:
    if not table:
        return []
    first_row = [_clean_cell(c) for c in table[0]]
    populated = [c for c in first_row if c]
    if len(populated) >= max(1, len(first_row) // 2):
        return first_row
    return [f"column_{idx + 1}" for idx in range(len(first_row))]


def _rows_from_table(table: list[list[object]], has_header: bool) -> list[list[str]]:
    rows = table[1:] if has_header and len(table) > 1 else table
    normalized: list[list[str]] = []
    for row in rows:
        clean = [_clean_cell(cell) for cell in row]
        if any(clean):
            normalized.append(clean)
    return normalized


def extract_pdf_payload(pdf_path: Union[str, Path]) -> list[ExtractedPage]:
    """Extract page text and tables from the full PDF."""
    logger.info("PDF extraction started path=%s", pdf_path)
    started = time.perf_counter()
    pages: list[ExtractedPage] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        logger.info("PDF opened successfully total_pages=%d", len(pdf.pages))
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            raw_tables = page.extract_tables() or []
            extracted_tables: list[ExtractedTable] = []
            total_rows = 0
            for t_idx, table in enumerate(raw_tables, start=1):
                if not table:
                    continue
                header = _header_from_table(table)
                has_header = bool(table and header == [_clean_cell(c) for c in table[0]])
                rows = _rows_from_table(table, has_header=has_header)
                total_rows += len(rows)
                extracted_tables.append(
                    ExtractedTable(
                        page_number=idx,
                        table_index=t_idx,
                        header=header,
                        rows=rows,
                    )
                )
            pages.append(
                ExtractedPage(
                    page_number=idx,
                    text=text,
                    tables=extracted_tables,
                )
            )
            logger.info(
                "PDF page extracted page=%d text_chars=%d tables=%d table_rows=%d",
                idx,
                len(text),
                len(extracted_tables),
                total_rows,
            )
    elapsed_s = time.perf_counter() - started
    logger.info("PDF extraction completed pages=%d elapsed_s=%.2f", len(pages), elapsed_s)
    return pages


def pages_to_prompt_payload(pages: list[ExtractedPage]) -> list[dict]:
    payload: list[dict] = []
    for page in pages:
        payload.append(
            {
                "page_number": page.page_number,
                "text": page.text,
                "tables": [
                    {
                        "table_index": t.table_index,
                        "header": t.header,
                        "rows": t.rows,
                    }
                    for t in page.tables
                ],
            }
        )
    return payload
