from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedTable:
    """Raw table payload extracted by pdfplumber."""

    page_number: int
    table_index: int
    header: list[str]
    rows: list[list[str]]


@dataclass
class ExtractedPage:
    """Raw page payload for prompt context and debugging."""

    page_number: int
    text: str
    tables: list[ExtractedTable] = field(default_factory=list)


@dataclass
class LLMSettings:
    """Runtime settings for local OpenAI-compatible model endpoint."""

    base_url: str = "http://localhost:8080"
    model: str = "Qwen/Qwen3-8B-Instruct"
    temperature: float = 0.0
    max_tokens: int = 4096
    request_timeout_s: int = 120
    pages_per_chunk: int = 3


@dataclass
class CanonicalExtraction:
    """Final structured output merged across all chunks."""

    records: list[dict[str, Any]]
    us_securities_settlement: list[dict[str, Any]]
    cash_settlement: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": self.records,
            "us_securities_settlement": self.us_securities_settlement,
            "cash_settlement": self.cash_settlement,
            "notes": self.notes,
        }
