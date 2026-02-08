from __future__ import annotations

import logging
import re
from typing import Any

from .sqlite_store import execute_select_query, rows_to_dicts

logger = logging.getLogger(__name__)


def _contains_all(text: str, terms: list[str]) -> bool:
    return all(term in text for term in terms)


def _extract_filter_term(question: str) -> str:
    match = re.search(r"\b(?:for|where|with)\s+(.+)$", question, flags=re.IGNORECASE)
    if not match:
        return ""
    term = match.group(1).strip()
    term = term.strip('"\'')
    return term[:80]


def question_to_sql(question: str) -> tuple[str, tuple[Any, ...], str]:
    q = question.strip()
    lowered = q.lower()

    if not q:
        raise ValueError("Question cannot be empty")

    if _contains_all(
        lowered,
        ["ssi", "type", "country", "currency", "account", "swift", "beneficiary"],
    ) or "breakdown" in lowered:
        return (
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
            ORDER BY type_of_ssi, country, currency
            """,
            (),
            "Complete SSI breakdown by type/country/currency/account/swift/beneficiary fields.",
        )

    if "count" in lowered and "type" in lowered:
        return (
            """
            SELECT ssi_type, COUNT(*) AS row_count
            FROM ssi_records
            GROUP BY ssi_type
            ORDER BY row_count DESC
            """,
            (),
            "Row count grouped by SSI type.",
        )

    if "count" in lowered and "country" in lowered:
        return (
            """
            SELECT COALESCE(NULLIF(country, ''), NULLIF(market, ''), 'UNKNOWN') AS country,
                   COUNT(*) AS row_count
            FROM ssi_records
            GROUP BY COALESCE(NULLIF(country, ''), NULLIF(market, ''), 'UNKNOWN')
            ORDER BY row_count DESC, country
            """,
            (),
            "Row count grouped by country.",
        )

    if "count" in lowered and "currency" in lowered:
        return (
            """
            SELECT COALESCE(NULLIF(currency, ''), 'N/A') AS currency,
                   COUNT(*) AS row_count
            FROM ssi_records
            GROUP BY COALESCE(NULLIF(currency, ''), 'N/A')
            ORDER BY row_count DESC, currency
            """,
            (),
            "Row count grouped by currency.",
        )

    if "us" in lowered and ("settlement" in lowered or "dvp" in lowered or "fop" in lowered):
        return (
            """
            SELECT
                instruction_type,
                account_number,
                beneficiary_bank,
                bic_code,
                additional_info,
                source_page,
                source_table,
                source_row
            FROM ssi_records
            WHERE ssi_type = 'us_securities_settlement'
            ORDER BY source_page, source_table, source_row
            """,
            (),
            "US securities settlement instructions.",
        )

    if "cash" in lowered and "settlement" in lowered:
        return (
            """
            SELECT
                currency,
                beneficiary_bank,
                beneficiary_bank_account_number,
                bic_code,
                additional_info,
                source_page,
                source_table,
                source_row
            FROM ssi_records
            WHERE ssi_type = 'cash_settlement'
            ORDER BY currency, source_page
            """,
            (),
            "Cash settlement instructions.",
        )

    filter_term = _extract_filter_term(q)
    if filter_term:
        like_term = f"%{filter_term}%"
        return (
            """
            SELECT
                ssi_type,
                COALESCE(NULLIF(country, ''), NULLIF(market, ''), 'UNKNOWN') AS country,
                currency,
                account_number,
                swift_code,
                bic_code,
                beneficiary_bank,
                beneficiary_bank_account_number,
                additional_info
            FROM ssi_records
            WHERE
                ssi_type LIKE ? OR
                country LIKE ? OR
                market LIKE ? OR
                currency LIKE ? OR
                account_number LIKE ? OR
                swift_code LIKE ? OR
                bic_code LIKE ? OR
                beneficiary_bank LIKE ? OR
                beneficiary_bank_account_number LIKE ? OR
                additional_info LIKE ?
            ORDER BY ssi_type, country, currency
            """,
            (like_term, like_term, like_term, like_term, like_term, like_term, like_term, like_term, like_term, like_term),
            f"Rows matching filter: {filter_term}",
        )

    return (
        """
        SELECT
            ssi_type,
            COALESCE(NULLIF(country, ''), NULLIF(market, ''), 'UNKNOWN') AS country,
            COALESCE(NULLIF(currency, ''), 'N/A') AS currency,
            account_number,
            swift_code,
            bic_code,
            beneficiary_bank,
            beneficiary_bank_account_number,
            additional_info
        FROM ssi_records
        ORDER BY ssi_type, country, currency
        LIMIT 200
        """,
        (),
        "Default view: first 200 SSI rows.",
    )


def answer_question(db_path: str, question: str) -> dict[str, Any]:
    sql, params, intent = question_to_sql(question)
    logger.info("DB chat query intent=%s", intent)
    rows = execute_select_query(db_path, sql, params)
    payload = rows_to_dicts(rows)
    return {
        "intent": intent,
        "sql": sql,
        "row_count": len(payload),
        "rows": payload,
    }


SAFE_SQL_HELP = (
    "Use natural-language prompts like: \n"
    "- list all SSIs by type, country, currency, account and swift\n"
    "- count by type\n"
    "- count by country\n"
    "- show cash settlement\n"
    "- list rows for AUD"
)
