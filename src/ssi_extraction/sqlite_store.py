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
NUMERIC_ACCOUNT_PATTERN = re.compile(r"\b\d{6,24}\b")


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


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _normalize_standard_record(record: dict[str, Any], run_id: int) -> dict[str, Any]:
    country_market = _coalesce_text(
        record.get("country_market") or record.get("country") or record.get("market")
    )
    agent = _coalesce_text(
        record.get("agent_or_clearing_organization") or record.get("agent_or_clearing_org")
    )
    swift_address = _coalesce_text(record.get("swift_address"))
    location = _coalesce_text(record.get("location"))
    account_name = _coalesce_text(record.get("account_name"))
    account_number = _coalesce_text(record.get("account_number"))
    beneficiary_bic = _coalesce_text(record.get("beneficiary_bic"))
    misc = _coalesce_text(record.get("miscellaneous_details") or record.get("account_details"))
    source_page, source_table, source_row = _build_source(record.get("source"))

    if not account_number:
        account_number = _find_first_account_number(misc, swift_address, agent)
    if not beneficiary_bic:
        beneficiary_bic = _find_first_bic(swift_address, agent, misc)

    return {
        "run_id": run_id,
        "country_market": country_market,
        "agent_or_clearing_organization": agent,
        "swift_address": swift_address,
        "location": location,
        "account_name": account_name,
        "account_number": account_number,
        "beneficiary_bic": beneficiary_bic,
        "miscellaneous_details": misc,
        "source_page": source_page,
        "source_table": source_table,
        "source_row": source_row,
        "raw_details": json.dumps(record, ensure_ascii=True),
    }


def _normalize_us_record(record: dict[str, Any], run_id: int) -> dict[str, Any]:
    instruction_type = _coalesce_text(record.get("instruction_type"))
    details = _coalesce_text(record.get("details"))
    location = _coalesce_text(record.get("location"))
    account_name = _coalesce_text(record.get("account_name"))
    account_number = _coalesce_text(record.get("account_number"))
    beneficiary_bic = _coalesce_text(record.get("beneficiary_bic"))
    misc = _coalesce_text(record.get("miscellaneous_details") or details)
    source_page, source_table, source_row = _build_source(record.get("source"))

    if not account_number:
        account_number = _find_first_account_number(details, misc)
    if not beneficiary_bic:
        beneficiary_bic = _find_first_bic(details, misc)

    return {
        "run_id": run_id,
        "instruction_type": instruction_type,
        "details": details,
        "location": location,
        "account_name": account_name,
        "account_number": account_number,
        "beneficiary_bic": beneficiary_bic,
        "miscellaneous_details": misc,
        "source_page": source_page,
        "source_table": source_table,
        "source_row": source_row,
        "raw_details": json.dumps(record, ensure_ascii=True),
    }


def _normalize_cash_record(record: dict[str, Any], run_id: int) -> dict[str, Any]:
    currency = _coalesce_text(record.get("currency"))
    intermediate = _coalesce_text(record.get("intermediate_institution_56a"))
    account_with = _coalesce_text(record.get("account_with_institution_57a"))
    beneficiary = _coalesce_text(record.get("beneficiary_59a_or_59f"))
    location = _coalesce_text(record.get("location"))
    account_name = _coalesce_text(record.get("account_name"))
    account_number = _coalesce_text(record.get("account_number"))
    beneficiary_bic = _coalesce_text(record.get("beneficiary_bic"))
    misc = _coalesce_text(record.get("miscellaneous_details"))
    source_page, source_table, source_row = _build_source(record.get("source"))

    combined = "\n".join([intermediate, account_with, beneficiary, misc]).strip()
    if not account_number:
        account_number = _find_first_account_number(beneficiary, account_with, intermediate, misc)
    if not beneficiary_bic:
        beneficiary_bic = _find_first_bic(beneficiary, account_with, intermediate, misc)
    if not misc:
        misc = combined

    return {
        "run_id": run_id,
        "currency": currency,
        "intermediate_institution_56a": intermediate,
        "account_with_institution_57a": account_with,
        "beneficiary_59a_or_59f": beneficiary,
        "location": location,
        "account_name": account_name,
        "account_number": account_number,
        "beneficiary_bic": beneficiary_bic,
        "miscellaneous_details": misc,
        "source_page": source_page,
        "source_table": source_table,
        "source_row": source_row,
        "raw_details": json.dumps(record, ensure_ascii=True),
    }


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
                notes_count INTEGER NOT NULL,
                extracted_json TEXT NOT NULL DEFAULT '{}',
                raw_pdf_payload TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        if not _column_exists(conn, "extraction_runs", "extracted_json"):
            conn.execute("ALTER TABLE extraction_runs ADD COLUMN extracted_json TEXT NOT NULL DEFAULT '{}' ")
        if not _column_exists(conn, "extraction_runs", "raw_pdf_payload"):
            conn.execute("ALTER TABLE extraction_runs ADD COLUMN raw_pdf_payload TEXT NOT NULL DEFAULT '[]' ")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS standard_ssi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                country_market TEXT,
                agent_or_clearing_organization TEXT,
                swift_address TEXT,
                location TEXT,
                account_name TEXT,
                account_number TEXT,
                beneficiary_bic TEXT,
                miscellaneous_details TEXT,
                source_page INTEGER,
                source_table INTEGER,
                source_row INTEGER,
                raw_details TEXT,
                FOREIGN KEY(run_id) REFERENCES extraction_runs(run_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS us_ssi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                instruction_type TEXT,
                details TEXT,
                location TEXT,
                account_name TEXT,
                account_number TEXT,
                beneficiary_bic TEXT,
                miscellaneous_details TEXT,
                source_page INTEGER,
                source_table INTEGER,
                source_row INTEGER,
                raw_details TEXT,
                FOREIGN KEY(run_id) REFERENCES extraction_runs(run_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cash_settlement_ssi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                currency TEXT,
                intermediate_institution_56a TEXT,
                account_with_institution_57a TEXT,
                beneficiary_59a_or_59f TEXT,
                location TEXT,
                account_name TEXT,
                account_number TEXT,
                beneficiary_bic TEXT,
                miscellaneous_details TEXT,
                source_page INTEGER,
                source_table INTEGER,
                source_row INTEGER,
                raw_details TEXT,
                FOREIGN KEY(run_id) REFERENCES extraction_runs(run_id)
            )
            """
        )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_standard_country ON standard_ssi(country_market)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_standard_account_number ON standard_ssi(account_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_standard_account_name ON standard_ssi(account_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_standard_bic ON standard_ssi(beneficiary_bic)")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_us_instruction_type ON us_ssi(instruction_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_us_account_number ON us_ssi(account_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_us_bic ON us_ssi(beneficiary_bic)")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_cash_currency ON cash_settlement_ssi(currency)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cash_account_number ON cash_settlement_ssi(account_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cash_account_name ON cash_settlement_ssi(account_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cash_bic ON cash_settlement_ssi(beneficiary_bic)")

        conn.commit()
    logger.info("SQLite initialize completed db_path=%s", db_path)


def refresh_db(db_path: str | Path) -> None:
    logger.info("SQLite refresh started db_path=%s", db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM standard_ssi")
        conn.execute("DELETE FROM us_ssi")
        conn.execute("DELETE FROM cash_settlement_ssi")
        conn.execute("DELETE FROM extraction_runs")
        if _table_exists(conn, "ssi_records"):
            conn.execute("DELETE FROM ssi_records")
        conn.commit()
    logger.info("SQLite refresh completed db_path=%s", db_path)


def persist_extraction(
    db_path: str | Path,
    source_file: str,
    result: CanonicalExtraction,
    page_count: int,
    raw_pdf_payload: list[dict[str, Any]] | None = None,
    replace_existing: bool = True,
) -> dict[str, int]:
    initialize_db(db_path)
    if replace_existing:
        refresh_db(db_path)

    with _connect(db_path) as conn:
        inserted = conn.execute(
            """
            INSERT INTO extraction_runs(
                source_file, extracted_at, page_count,
                standard_count, us_count, cash_count, notes_count,
                extracted_json, raw_pdf_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_file,
                datetime.now(timezone.utc).isoformat(),
                page_count,
                len(result.records),
                len(result.us_securities_settlement),
                len(result.cash_settlement),
                len(result.notes),
                json.dumps(result.to_dict(), ensure_ascii=True),
                json.dumps(raw_pdf_payload or [], ensure_ascii=True),
            ),
        )
        run_id = int(inserted.lastrowid)

        standard_rows = [_normalize_standard_record(record, run_id=run_id) for record in result.records]
        us_rows = [_normalize_us_record(record, run_id=run_id) for record in result.us_securities_settlement]
        cash_rows = [_normalize_cash_record(record, run_id=run_id) for record in result.cash_settlement]

        conn.executemany(
            """
            INSERT INTO standard_ssi(
                run_id, country_market, agent_or_clearing_organization, swift_address, location,
                account_name, account_number, beneficiary_bic, miscellaneous_details,
                source_page, source_table, source_row, raw_details
            ) VALUES (
                :run_id, :country_market, :agent_or_clearing_organization, :swift_address, :location,
                :account_name, :account_number, :beneficiary_bic, :miscellaneous_details,
                :source_page, :source_table, :source_row, :raw_details
            )
            """,
            standard_rows,
        )
        conn.executemany(
            """
            INSERT INTO us_ssi(
                run_id, instruction_type, details, location, account_name, account_number,
                beneficiary_bic, miscellaneous_details, source_page, source_table, source_row, raw_details
            ) VALUES (
                :run_id, :instruction_type, :details, :location, :account_name, :account_number,
                :beneficiary_bic, :miscellaneous_details, :source_page, :source_table, :source_row, :raw_details
            )
            """,
            us_rows,
        )
        conn.executemany(
            """
            INSERT INTO cash_settlement_ssi(
                run_id, currency, intermediate_institution_56a, account_with_institution_57a,
                beneficiary_59a_or_59f, location, account_name, account_number,
                beneficiary_bic, miscellaneous_details,
                source_page, source_table, source_row, raw_details
            ) VALUES (
                :run_id, :currency, :intermediate_institution_56a, :account_with_institution_57a,
                :beneficiary_59a_or_59f, :location, :account_name, :account_number,
                :beneficiary_bic, :miscellaneous_details,
                :source_page, :source_table, :source_row, :raw_details
            )
            """,
            cash_rows,
        )
        conn.commit()

    stats = {
        "run_id": run_id,
        "standard_rows": len(standard_rows),
        "us_rows": len(us_rows),
        "cash_rows": len(cash_rows),
        "rows_written": len(standard_rows) + len(us_rows) + len(cash_rows),
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
              (SELECT COUNT(*) FROM standard_ssi) AS standard_rows,
              (SELECT COUNT(*) FROM us_ssi) AS us_rows,
              (SELECT COUNT(*) FROM cash_settlement_ssi) AS cash_rows
            """
        ).fetchone()

    if row is None:
        return {"runs": 0, "total_rows": 0, "standard_rows": 0, "us_rows": 0, "cash_rows": 0}

    standard_rows = int(row["standard_rows"] or 0)
    us_rows = int(row["us_rows"] or 0)
    cash_rows = int(row["cash_rows"] or 0)
    return {
        "runs": int(row["runs"] or 0),
        "total_rows": standard_rows + us_rows + cash_rows,
        "standard_rows": standard_rows,
        "us_rows": us_rows,
        "cash_rows": cash_rows,
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


def _build_search_clause(columns: list[str], search_term: str) -> tuple[str, tuple[Any, ...]]:
    if not search_term.strip():
        return "", ()

    like_term = f"%{search_term.strip()}%"
    conditions = [f"{column} LIKE ?" for column in columns]
    clause = " WHERE " + " OR ".join(conditions)
    params = tuple(like_term for _ in columns)
    return clause, params


def get_standard_ssi_view(db_path: str | Path, search_term: str = "") -> list[dict[str, Any]]:
    search_clause, params = _build_search_clause(
        [
            "country_market",
            "agent_or_clearing_organization",
            "swift_address",
            "location",
            "account_name",
            "account_number",
            "beneficiary_bic",
            "miscellaneous_details",
        ],
        search_term,
    )

    rows = execute_select_query(
        db_path,
        f"""
        SELECT
            country_market,
            agent_or_clearing_organization,
            swift_address,
            location,
            account_name,
            account_number,
            beneficiary_bic,
            miscellaneous_details,
            source_page,
            source_table,
            source_row
        FROM standard_ssi
        {search_clause}
        ORDER BY country_market, account_name, account_number
        """,
        params,
    )
    return rows_to_dicts(rows)


def get_us_ssi_view(db_path: str | Path, search_term: str = "") -> list[dict[str, Any]]:
    search_clause, params = _build_search_clause(
        [
            "instruction_type",
            "details",
            "location",
            "account_name",
            "account_number",
            "beneficiary_bic",
            "miscellaneous_details",
        ],
        search_term,
    )

    rows = execute_select_query(
        db_path,
        f"""
        SELECT
            instruction_type,
            details,
            location,
            account_name,
            account_number,
            beneficiary_bic,
            miscellaneous_details,
            source_page,
            source_table,
            source_row
        FROM us_ssi
        {search_clause}
        ORDER BY instruction_type, account_name, account_number
        """,
        params,
    )
    return rows_to_dicts(rows)


def get_cash_settlement_view(db_path: str | Path, search_term: str = "") -> list[dict[str, Any]]:
    search_clause, params = _build_search_clause(
        [
            "currency",
            "intermediate_institution_56a",
            "account_with_institution_57a",
            "beneficiary_59a_or_59f",
            "location",
            "account_name",
            "account_number",
            "beneficiary_bic",
            "miscellaneous_details",
        ],
        search_term,
    )

    rows = execute_select_query(
        db_path,
        f"""
        SELECT
            currency,
            intermediate_institution_56a,
            account_with_institution_57a,
            beneficiary_59a_or_59f,
            location,
            account_name,
            account_number,
            beneficiary_bic,
            miscellaneous_details,
            source_page,
            source_table,
            source_row
        FROM cash_settlement_ssi
        {search_clause}
        ORDER BY currency, account_name, account_number
        """,
        params,
    )
    return rows_to_dicts(rows)


def get_latest_extraction_payload(db_path: str | Path) -> dict[str, Any] | None:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT extracted_json
            FROM extraction_runs
            ORDER BY run_id DESC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None

    payload = row["extracted_json"]
    if not payload:
        return None

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("Stored extracted_json is malformed in latest run")
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def get_latest_raw_pdf_payload(db_path: str | Path) -> list[dict[str, Any]] | None:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT raw_pdf_payload
            FROM extraction_runs
            ORDER BY run_id DESC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None

    payload = row["raw_pdf_payload"]
    if not payload:
        return None

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("Stored raw_pdf_payload is malformed in latest run")
        return None
    if not isinstance(parsed, list):
        return None
    return parsed


def get_latest_run_metadata(db_path: str | Path) -> dict[str, Any] | None:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT run_id, source_file, extracted_at, page_count,
                   standard_count, us_count, cash_count, notes_count
            FROM extraction_runs
            ORDER BY run_id DESC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None
    return dict(row)
