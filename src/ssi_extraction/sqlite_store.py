from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any

from .models import CanonicalExtraction

logger = logging.getLogger(__name__)

BIC_PATTERN = re.compile(r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")
LABELED_ACCOUNT_PATTERN = re.compile(
    r"(?i)\b(?:a/c|acct|account(?:\s*number)?|acc(?:ount)?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/ ]{4,})"
)
NUMERIC_ACCOUNT_PATTERN = re.compile(r"\b\d{6,18}\b")
CURRENCY_PATTERN = re.compile(r"\b[A-Z]{3}\b")
LABELED_CURRENCY_PATTERN = re.compile(r"(?i)\bcurrency\b\s*[:#-]?\s*([A-Z]{3})\b")


def _coalesce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if item is not None).strip()
    return str(value).strip()


def _find_first_bic(*texts: str) -> str:
    for text in texts:
        if not text:
            continue
        match = BIC_PATTERN.search(text)
        if match:
            return match.group(0)
    return ""


def _find_first_account_number(*texts: str) -> str:
    for text in texts:
        if not text:
            continue
        labeled = LABELED_ACCOUNT_PATTERN.search(text)
        if labeled:
            return " ".join(labeled.group(1).split())

    for text in texts:
        if not text:
            continue
        numeric = NUMERIC_ACCOUNT_PATTERN.search(text)
        if numeric:
            return numeric.group(0)

    return ""


def _find_currency(*texts: str) -> str:
    for text in texts:
        if not text:
            continue
        labeled_match = LABELED_CURRENCY_PATTERN.search(text)
        if labeled_match:
            return labeled_match.group(1).upper()

    for text in texts:
        if not text:
            continue
        if len(text.strip()) > 8:
            continue
        match = CURRENCY_PATTERN.search(text.strip().upper())
        if match:
            code = match.group(0)
            if code not in {"DVP", "FOP", "USA"}:
                return code
    return ""


def _build_source(source: Any) -> tuple[int | None, int | None, int | None]:
    if not isinstance(source, dict):
        return None, None, None
    page = source.get("page_number")
    table = source.get("table_index")
    row = source.get("row_index")
    return (
        int(page) if isinstance(page, int) else None,
        int(table) if isinstance(table, int) else None,
        int(row) if isinstance(row, int) else None,
    )


def _extract_beneficiary_bank(text: str) -> str:
    if not text:
        return ""
    first_line = text.splitlines()[0].strip()
    if "," in first_line:
        return first_line.split(",", 1)[0].strip()
    return first_line


def _normalize_standard_record(record: dict[str, Any], run_id: int) -> dict[str, Any]:
    market = _coalesce_text(record.get("market"))
    agent = _coalesce_text(record.get("agent_or_clearing_org"))
    swift_address = _coalesce_text(record.get("swift_address"))
    account_details = _coalesce_text(record.get("account_details"))
    source_page, source_table, source_row = _build_source(record.get("source"))

    bic_code = _find_first_bic(swift_address, agent, account_details)
    account_number = _find_first_account_number(account_details, swift_address, agent)
    currency = _find_currency(market, account_details)

    return {
        "run_id": run_id,
        "ssi_type": "standard",
        "market": market,
        "country": market,
        "currency": currency,
        "instruction_type": "",
        "agent_or_clearing_org": agent,
        "swift_address": swift_address,
        "swift_code": bic_code,
        "bic_code": bic_code,
        "account_number": account_number,
        "beneficiary_bank": _extract_beneficiary_bank(agent),
        "beneficiary": "",
        "beneficiary_bank_account_number": account_number,
        "additional_info": account_details,
        "raw_details": json.dumps(record, ensure_ascii=True),
        "source_page": source_page,
        "source_table": source_table,
        "source_row": source_row,
    }


def _normalize_us_record(record: dict[str, Any], run_id: int) -> dict[str, Any]:
    instruction_type = _coalesce_text(record.get("instruction_type"))
    details = _coalesce_text(record.get("details"))
    source_page, source_table, source_row = _build_source(record.get("source"))

    bic_code = _find_first_bic(details)
    account_number = _find_first_account_number(details)

    return {
        "run_id": run_id,
        "ssi_type": "us_securities_settlement",
        "market": "USA",
        "country": "USA",
        "currency": "",
        "instruction_type": instruction_type,
        "agent_or_clearing_org": "",
        "swift_address": "",
        "swift_code": bic_code,
        "bic_code": bic_code,
        "account_number": account_number,
        "beneficiary_bank": _extract_beneficiary_bank(details),
        "beneficiary": "",
        "beneficiary_bank_account_number": account_number,
        "additional_info": details,
        "raw_details": json.dumps(record, ensure_ascii=True),
        "source_page": source_page,
        "source_table": source_table,
        "source_row": source_row,
    }


def _normalize_cash_record(record: dict[str, Any], run_id: int) -> dict[str, Any]:
    currency = _coalesce_text(record.get("currency"))
    intermediate = _coalesce_text(record.get("intermediate_institution_56a"))
    account_with = _coalesce_text(record.get("account_with_institution_57a"))
    beneficiary = _coalesce_text(record.get("beneficiary_59a_or_59f"))
    source_page, source_table, source_row = _build_source(record.get("source"))

    combined = "\n".join([intermediate, account_with, beneficiary]).strip()
    bic_code = _find_first_bic(combined)
    beneficiary_account = _find_first_account_number(beneficiary, account_with, intermediate)

    return {
        "run_id": run_id,
        "ssi_type": "cash_settlement",
        "market": "",
        "country": "",
        "currency": currency,
        "instruction_type": "",
        "agent_or_clearing_org": account_with,
        "swift_address": combined,
        "swift_code": bic_code,
        "bic_code": bic_code,
        "account_number": beneficiary_account,
        "beneficiary_bank": _extract_beneficiary_bank(account_with or intermediate),
        "beneficiary": beneficiary,
        "beneficiary_bank_account_number": beneficiary_account,
        "additional_info": combined,
        "raw_details": json.dumps(record, ensure_ascii=True),
        "source_page": source_page,
        "source_table": source_table,
        "source_row": source_row,
    }


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db(db_path: str | Path) -> None:
    logger.info("SQLite initialize started db_path=%s", db_path)
    with _connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extraction_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT NOT NULL,
                extracted_at TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                standard_count INTEGER NOT NULL,
                us_count INTEGER NOT NULL,
                cash_count INTEGER NOT NULL,
                notes_count INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ssi_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                ssi_type TEXT NOT NULL,
                market TEXT,
                country TEXT,
                currency TEXT,
                instruction_type TEXT,
                agent_or_clearing_org TEXT,
                swift_address TEXT,
                swift_code TEXT,
                bic_code TEXT,
                account_number TEXT,
                beneficiary_bank TEXT,
                beneficiary TEXT,
                beneficiary_bank_account_number TEXT,
                additional_info TEXT,
                raw_details TEXT,
                source_page INTEGER,
                source_table INTEGER,
                source_row INTEGER,
                FOREIGN KEY(run_id) REFERENCES extraction_runs(run_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ssi_type ON ssi_records(ssi_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_country ON ssi_records(country)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_currency ON ssi_records(currency)")
        conn.commit()
    logger.info("SQLite initialize completed db_path=%s", db_path)


def refresh_db(db_path: str | Path) -> None:
    logger.info("SQLite refresh started db_path=%s", db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM ssi_records")
        conn.execute("DELETE FROM extraction_runs")
        conn.commit()
    logger.info("SQLite refresh completed db_path=%s", db_path)


def persist_extraction(
    db_path: str | Path,
    source_file: str,
    result: CanonicalExtraction,
    page_count: int,
    replace_existing: bool = True,
) -> dict[str, int]:
    initialize_db(db_path)
    if replace_existing:
        refresh_db(db_path)

    normalized_rows: list[dict[str, Any]] = []

    with _connect(db_path) as conn:
        inserted = conn.execute(
            """
            INSERT INTO extraction_runs(
                source_file, extracted_at, page_count,
                standard_count, us_count, cash_count, notes_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_file,
                datetime.now(timezone.utc).isoformat(),
                page_count,
                len(result.records),
                len(result.us_securities_settlement),
                len(result.cash_settlement),
                len(result.notes),
            ),
        )
        run_id = int(inserted.lastrowid)

        for record in result.records:
            normalized_rows.append(_normalize_standard_record(record, run_id=run_id))
        for record in result.us_securities_settlement:
            normalized_rows.append(_normalize_us_record(record, run_id=run_id))
        for record in result.cash_settlement:
            normalized_rows.append(_normalize_cash_record(record, run_id=run_id))

        conn.executemany(
            """
            INSERT INTO ssi_records(
                run_id, ssi_type, market, country, currency, instruction_type,
                agent_or_clearing_org, swift_address, swift_code, bic_code,
                account_number, beneficiary_bank, beneficiary,
                beneficiary_bank_account_number, additional_info, raw_details,
                source_page, source_table, source_row
            ) VALUES (
                :run_id, :ssi_type, :market, :country, :currency, :instruction_type,
                :agent_or_clearing_org, :swift_address, :swift_code, :bic_code,
                :account_number, :beneficiary_bank, :beneficiary,
                :beneficiary_bank_account_number, :additional_info, :raw_details,
                :source_page, :source_table, :source_row
            )
            """,
            normalized_rows,
        )
        conn.commit()

    stats = {
        "run_id": run_id,
        "rows_written": len(normalized_rows),
        "standard_rows": len(result.records),
        "us_rows": len(result.us_securities_settlement),
        "cash_rows": len(result.cash_settlement),
    }
    logger.info("SQLite persist completed stats=%s", stats)
    return stats


def get_db_summary(db_path: str | Path) -> dict[str, int]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM extraction_runs) AS runs,
              (SELECT COUNT(*) FROM ssi_records) AS total_rows,
              (SELECT COUNT(*) FROM ssi_records WHERE ssi_type='standard') AS standard_rows,
              (SELECT COUNT(*) FROM ssi_records WHERE ssi_type='us_securities_settlement') AS us_rows,
              (SELECT COUNT(*) FROM ssi_records WHERE ssi_type='cash_settlement') AS cash_rows
            """
        ).fetchone()

    if row is None:
        return {"runs": 0, "total_rows": 0, "standard_rows": 0, "us_rows": 0, "cash_rows": 0}

    return {
        "runs": int(row["runs"] or 0),
        "total_rows": int(row["total_rows"] or 0),
        "standard_rows": int(row["standard_rows"] or 0),
        "us_rows": int(row["us_rows"] or 0),
        "cash_rows": int(row["cash_rows"] or 0),
    }


def execute_select_query(db_path: str | Path, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    stripped = query.strip().lower()
    if not (stripped.startswith("select") or stripped.startswith("with")):
        raise ValueError("Only SELECT queries are allowed")

    initialize_db(db_path)
    with _connect(db_path) as conn:
        return conn.execute(query, params).fetchall()


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def get_breakdown_view(db_path: str | Path) -> list[dict[str, Any]]:
    rows = execute_select_query(
        db_path,
        """
        SELECT
            ssi_type AS type_of_ssi,
            COALESCE(NULLIF(country, ''), NULLIF(market, ''), 'UNKNOWN') AS country,
            COALESCE(NULLIF(currency, ''), 'N/A') AS currency,
            COALESCE(account_number, '') AS account_number,
            COALESCE(swift_code, '') AS swift_code,
            COALESCE(bic_code, '') AS bic_code,
            COALESCE(beneficiary_bank, '') AS beneficiary_bank,
            COALESCE(beneficiary_bank_account_number, '') AS beneficiary_bank_account_number,
            COALESCE(additional_info, '') AS additional_info
        FROM ssi_records
        ORDER BY type_of_ssi, country, currency, beneficiary_bank
        """,
    )
    return rows_to_dicts(rows)
