from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional, Union


def _connect(db_path: Union[str, Path]) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_isda_db(db_path: Union[str, Path]) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS isda_documents (
                doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_key TEXT NOT NULL UNIQUE,
                country TEXT,
                jurisdiction TEXT,
                source_file TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                summary TEXT,
                extraction_json TEXT NOT NULL,
                raw_docx_payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS isda_fields (
                field_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                field_name TEXT NOT NULL,
                field_value TEXT,
                source TEXT,
                notes TEXT,
                FOREIGN KEY(doc_id) REFERENCES isda_documents(doc_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_isda_country_key ON isda_documents(country_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_isda_field_name ON isda_fields(field_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_isda_field_value ON isda_fields(field_value)")
        conn.commit()


def _normalize_field_entries(payload: dict[str, Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []

    for field in payload.get("normalized_fields", []):
        if not isinstance(field, dict):
            continue
        field_name = str(field.get("field_name", "")).strip()
        field_value = str(field.get("value", "")).strip()
        if not field_name:
            continue
        normalized.append(
            {
                "field_name": field_name,
                "field_value": field_value,
                "source": str(field.get("source", "")).strip() or "unknown",
                "notes": str(field.get("notes", "")).strip(),
            }
        )

    for field in payload.get("additional_fields", []):
        if not isinstance(field, dict):
            continue
        field_name = str(field.get("field_name", "")).strip()
        field_value = str(field.get("value", "")).strip()
        if not field_name:
            continue
        normalized.append(
            {
                "field_name": field_name,
                "field_value": field_value,
                "source": str(field.get("source", "")).strip() or "unknown",
                "notes": str(field.get("notes", "")).strip() or "additional_field",
            }
        )

    return normalized


def upsert_isda_document(
    db_path: Union[str, Path],
    source_file: str,
    country_key: str,
    extraction_payload: dict[str, Any],
    raw_docx_payload: dict[str, Any],
) -> dict[str, Any]:
    initialize_isda_db(db_path)

    normalized_fields = _normalize_field_entries(extraction_payload)
    country = str(extraction_payload.get("country", "")).strip()
    jurisdiction = str(extraction_payload.get("jurisdiction", "")).strip()
    summary = str(extraction_payload.get("summary", "")).strip()

    replaced = False
    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT doc_id FROM isda_documents WHERE country_key = ?",
            (country_key,),
        ).fetchone()
        if existing is not None:
            replaced = True
            conn.execute("DELETE FROM isda_documents WHERE doc_id = ?", (existing["doc_id"],))

        inserted = conn.execute(
            """
            INSERT INTO isda_documents(
                country_key, country, jurisdiction, source_file, uploaded_at,
                summary, extraction_json, raw_docx_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                country_key,
                country,
                jurisdiction,
                source_file,
                datetime.now(timezone.utc).isoformat(),
                summary,
                json.dumps(extraction_payload, ensure_ascii=True),
                json.dumps(raw_docx_payload, ensure_ascii=True),
            ),
        )
        doc_id = int(inserted.lastrowid)

        conn.executemany(
            """
            INSERT INTO isda_fields(doc_id, field_name, field_value, source, notes)
            VALUES (:doc_id, :field_name, :field_value, :source, :notes)
            """,
            [
                {
                    "doc_id": doc_id,
                    "field_name": entry["field_name"],
                    "field_value": entry["field_value"],
                    "source": entry["source"],
                    "notes": entry["notes"],
                }
                for entry in normalized_fields
            ],
        )
        conn.commit()

    return {
        "doc_id": doc_id,
        "country_key": country_key,
        "replaced": replaced,
        "field_rows": len(normalized_fields),
    }


def get_isda_summary(db_path: Union[str, Path]) -> dict[str, int]:
    initialize_isda_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM isda_documents) AS document_count,
                (SELECT COUNT(*) FROM isda_fields) AS field_count
            """
        ).fetchone()

    if row is None:
        return {"document_count": 0, "field_count": 0}
    return {
        "document_count": int(row["document_count"] or 0),
        "field_count": int(row["field_count"] or 0),
    }


def list_isda_documents(db_path: Union[str, Path]) -> list[dict[str, Any]]:
    initialize_isda_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT doc_id, country_key, country, jurisdiction, source_file, uploaded_at, summary
            FROM isda_documents
            ORDER BY country_key, uploaded_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_isda_document_context(db_path: Union[str, Path], doc_id: int) -> Optional[dict[str, Any]]:
    initialize_isda_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT doc_id, country_key, country, jurisdiction, source_file, uploaded_at,
                   summary, extraction_json, raw_docx_payload
            FROM isda_documents
            WHERE doc_id = ?
            """,
            (doc_id,),
        ).fetchone()

    if row is None:
        return None

    extraction_json = json.loads(row["extraction_json"])
    raw_docx_payload = json.loads(row["raw_docx_payload"])
    payload = dict(row)
    payload["extraction_json"] = extraction_json
    payload["raw_docx_payload"] = raw_docx_payload
    return payload


def get_isda_fields_view(db_path: Union[str, Path], doc_id: int, search_term: str = "") -> list[dict[str, Any]]:
    initialize_isda_db(db_path)
    search_term = search_term.strip()

    query = """
        SELECT field_name, field_value, source, notes
        FROM isda_fields
        WHERE doc_id = ?
    """
    params: tuple[Any, ...]
    if search_term:
        query += " AND (field_name LIKE ? OR field_value LIKE ? OR notes LIKE ?)"
        like_term = f"%{search_term}%"
        params = (doc_id, like_term, like_term, like_term)
    else:
        params = (doc_id,)

    query += " ORDER BY field_name"

    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


def execute_isda_select_query(
    db_path: Union[str, Path],
    query: str,
    params: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    stripped = query.strip().lower()
    if not (stripped.startswith("select") or stripped.startswith("with")):
        raise ValueError("Only SELECT queries are allowed")

    initialize_isda_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
