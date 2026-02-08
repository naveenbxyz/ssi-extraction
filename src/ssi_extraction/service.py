from __future__ import annotations

from itertools import islice
from typing import Iterable

from .llm_client import LocalOpenAICompatibleClient
from .models import CanonicalExtraction, ExtractedPage, LLMSettings
from .pdf_extractor import extract_pdf_payload, pages_to_prompt_payload


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
    pages = extract_pdf_payload(pdf_path)
    payload_chunks: list[list[dict]] = []
    for page_chunk in _chunked(pages, settings.pages_per_chunk):
        payload_chunks.append(pages_to_prompt_payload(page_chunk))

    client = LocalOpenAICompatibleClient(settings)
    results: list[dict] = []
    for payload in payload_chunks:
        results.append(client.extract_chunk(payload))

    merged = merge_results(results)
    return pages, merged
