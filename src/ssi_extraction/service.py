from __future__ import annotations

from itertools import islice
import logging
import time
from typing import Iterable

from .llm_client import LocalOpenAICompatibleClient
from .models import CanonicalExtraction, ExtractedPage, LLMSettings
from .pdf_extractor import extract_pdf_payload, pages_to_prompt_payload

logger = logging.getLogger(__name__)


def _chunked(iterable: list[ExtractedPage], size: int) -> Iterable[list[ExtractedPage]]:
    iterator = iter(iterable)
    while True:
        chunk = list(islice(iterator, size))
        if not chunk:
            break
        yield chunk


def merge_results(chunks: list[dict]) -> CanonicalExtraction:
    records: list[dict] = []
    us_rows: list[dict] = []
    cash_rows: list[dict] = []
    notes: list[str] = []

    for chunk in chunks:
        records.extend(chunk.get("records", []))
        us_rows.extend(chunk.get("us_securities_settlement", []))
        cash_rows.extend(chunk.get("cash_settlement", []))
        notes.extend(chunk.get("notes", []))

    return CanonicalExtraction(
        records=records,
        us_securities_settlement=us_rows,
        cash_settlement=cash_rows,
        notes=notes,
    )


def run_extraction_pipeline(pdf_path: str, settings: LLMSettings) -> tuple[list[ExtractedPage], CanonicalExtraction]:
    started = time.perf_counter()
    logger.info(
        "Pipeline started pdf_path=%s model=%s base_url=%s pages_per_chunk=%d timeout_s=%d stream=%s",
        pdf_path,
        settings.model,
        settings.base_url,
        settings.pages_per_chunk,
        settings.request_timeout_s,
        settings.stream,
    )
    pages = extract_pdf_payload(pdf_path)
    total_tables = sum(len(page.tables) for page in pages)
    logger.info("Pipeline stage complete=pdf_extraction pages=%d tables=%d", len(pages), total_tables)

    payload_chunks: list[list[dict]] = []
    for page_chunk in _chunked(pages, settings.pages_per_chunk):
        payload_chunks.append(pages_to_prompt_payload(page_chunk))
    logger.info(
        "Pipeline stage complete=chunk_building total_chunks=%d pages_per_chunk=%d",
        len(payload_chunks),
        settings.pages_per_chunk,
    )

    client = LocalOpenAICompatibleClient(settings)
    try:
        client.log_connectivity()

        results: list[dict] = []
        total_chunks = len(payload_chunks)
        for idx, payload in enumerate(payload_chunks, start=1):
            page_numbers = [int(page.get("page_number", -1)) for page in payload]
            logger.info(
                "Pipeline stage=llm_chunk_start chunk=%d/%d pages=%s",
                idx,
                total_chunks,
                page_numbers,
            )
            chunk_result = client.extract_chunk(payload, chunk_index=idx, total_chunks=total_chunks)
            logger.info(
                "Pipeline stage=llm_chunk_done chunk=%d/%d records=%d us_rows=%d cash_rows=%d notes=%d",
                idx,
                total_chunks,
                len(chunk_result.get("records", [])),
                len(chunk_result.get("us_securities_settlement", [])),
                len(chunk_result.get("cash_settlement", [])),
                len(chunk_result.get("notes", [])),
            )
            results.append(chunk_result)
    finally:
        client.close()

    merged = merge_results(results)
    elapsed_s = time.perf_counter() - started
    logger.info(
        "Pipeline completed elapsed_s=%.2f records=%d us_rows=%d cash_rows=%d notes=%d",
        elapsed_s,
        len(merged.records),
        len(merged.us_securities_settlement),
        len(merged.cash_settlement),
        len(merged.notes),
    )
    return pages, merged
