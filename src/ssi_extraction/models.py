from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
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
    """Runtime settings for OpenAI-compatible model endpoint."""

    base_url: str = "https://internal-llm/v1"
    api_key: str = "xxxxxxx"
    model: str = "internalLM"
    temperature: float = 0.0
    max_tokens: int = 4096
    request_timeout_s: int = 120
    pages_per_chunk: int = 3
    stream: bool = True
    verify_ssl: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMSettings":
        known_fields = {f.name for f in fields(cls)}
        payload = {key: value for key, value in data.items() if key in known_fields}
        return cls(**payload)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "LLMSettings":
        config_path = Path(path)
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Config file must contain a JSON object: {config_path}")
        return cls.from_dict(raw)

    def to_redacted_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        api_key = payload.get("api_key", "")
        if isinstance(api_key, str) and api_key:
            payload["api_key"] = f"{api_key[:2]}***{api_key[-2:]}" if len(api_key) > 4 else "***"
        return payload


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
