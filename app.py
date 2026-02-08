from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

import sys

ROOT = Path(__file__).parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ssi_extraction.chat_engine import SAFE_SQL_HELP, answer_question
from ssi_extraction.models import LLMSettings
from ssi_extraction.service import run_extraction_pipeline
from ssi_extraction.sqlite_store import (
    execute_select_query,
    get_breakdown_view,
    get_db_summary,
    initialize_db,
    persist_extraction,
    rows_to_dicts,
)

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
root_logger = logging.getLogger()
if not root_logger.handlers:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
else:
    root_logger.setLevel(logging.INFO)

logger = logging.getLogger(__name__)


def _init_session_state() -> None:
    if "latest_pages" not in st.session_state:
        st.session_state.latest_pages = None
    if "latest_result" not in st.session_state:
        st.session_state.latest_result = None
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []


def _rows_to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _run_select_as_df(db_path: str, sql: str) -> pd.DataFrame:
    rows = execute_select_query(db_path, sql)
    return _rows_to_df(rows_to_dicts(rows))


def _render_latest_extraction() -> None:
    pages = st.session_state.latest_pages
    result = st.session_state.latest_result

    if result is None or pages is None:
        st.info("Run an extraction to see in-memory latest results.")
        return

    st.subheader("Latest Extraction")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pages", len(pages))
    c2.metric("Standard SSI rows", len(result.records))
    c3.metric("US SSI rows", len(result.us_securities_settlement))
    c4.metric("Cash settlement rows", len(result.cash_settlement))

    search = st.text_input("Search extracted values", value="", key="latest_search")

    records_df = pd.DataFrame(result.records)
    us_df = pd.DataFrame(result.us_securities_settlement)
    cash_df = pd.DataFrame(result.cash_settlement)

    if search:
        needle = search.lower()
        if not records_df.empty:
            records_df = records_df[
                records_df.apply(lambda row: needle in " ".join(row.astype(str)).lower(), axis=1)
            ]
        if not us_df.empty:
            us_df = us_df[us_df.apply(lambda row: needle in " ".join(row.astype(str)).lower(), axis=1)]
        if not cash_df.empty:
            cash_df = cash_df[cash_df.apply(lambda row: needle in " ".join(row.astype(str)).lower(), axis=1)]

    tab1, tab2, tab3, tab4 = st.tabs(["Standard SSI", "US SSI", "Cash Settlement", "Raw Pages"])

    with tab1:
        st.dataframe(records_df, use_container_width=True)

    with tab2:
        st.dataframe(us_df, use_container_width=True)

    with tab3:
        st.dataframe(cash_df, use_container_width=True)

    with tab4:
        for page in pages:
            with st.expander(f"Page {page.page_number}"):
                st.text(page.text[:2500] + ("..." if len(page.text) > 2500 else ""))
                for table in page.tables:
                    st.markdown(f"Table {table.table_index}")
                    st.dataframe(pd.DataFrame(table.rows, columns=table.header), use_container_width=True)

    st.subheader("Downloads")
    output = result.to_dict()
    st.download_button(
        "Download full JSON",
        data=json.dumps(output, indent=2),
        file_name="ssi_extraction.json",
        mime="application/json",
        key="download_json_latest",
    )

    if not records_df.empty:
        st.download_button(
            "Download standard SSI CSV",
            data=records_df.to_csv(index=False),
            file_name="standard_ssi.csv",
            mime="text/csv",
            key="download_csv_standard_latest",
        )
    if not us_df.empty:
        st.download_button(
            "Download US SSI CSV",
            data=us_df.to_csv(index=False),
            file_name="us_ssi.csv",
            mime="text/csv",
            key="download_csv_us_latest",
        )
    if not cash_df.empty:
        st.download_button(
            "Download cash settlement CSV",
            data=cash_df.to_csv(index=False),
            file_name="cash_settlement.csv",
            mime="text/csv",
            key="download_csv_cash_latest",
        )

    if result.notes:
        st.subheader("Notes")
        for note in result.notes:
            st.write(f"- {note}")


def _render_database_views(db_path: str) -> None:
    summary = get_db_summary(db_path)

    st.subheader("SQLite Data")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Runs", summary["runs"])
    c2.metric("Total rows", summary["total_rows"])
    c3.metric("Standard", summary["standard_rows"])
    c4.metric("US SSI", summary["us_rows"])
    c5.metric("Cash", summary["cash_rows"])

    if summary["total_rows"] == 0:
        st.info("No rows in database yet. Run extraction to populate SQLite.")
        return

    view_name = st.selectbox(
        "View",
        options=[
            "Breakdown view",
            "Count by SSI type",
            "Count by country",
            "Count by currency",
            "Raw normalized rows",
        ],
    )

    if view_name == "Breakdown view":
        view_df = _rows_to_df(get_breakdown_view(db_path))
    elif view_name == "Count by SSI type":
        view_df = _run_select_as_df(
            db_path,
            """
            SELECT ssi_type, COUNT(*) AS row_count
            FROM ssi_records
            GROUP BY ssi_type
            ORDER BY row_count DESC
            """,
        )
    elif view_name == "Count by country":
        view_df = _run_select_as_df(
            db_path,
            """
            SELECT COALESCE(NULLIF(country, ''), NULLIF(market, ''), 'UNKNOWN') AS country,
                   COUNT(*) AS row_count
            FROM ssi_records
            GROUP BY COALESCE(NULLIF(country, ''), NULLIF(market, ''), 'UNKNOWN')
            ORDER BY row_count DESC, country
            """,
        )
    elif view_name == "Count by currency":
        view_df = _run_select_as_df(
            db_path,
            """
            SELECT COALESCE(NULLIF(currency, ''), 'N/A') AS currency,
                   COUNT(*) AS row_count
            FROM ssi_records
            GROUP BY COALESCE(NULLIF(currency, ''), 'N/A')
            ORDER BY row_count DESC, currency
            """,
        )
    else:
        view_df = _run_select_as_df(
            db_path,
            """
            SELECT
                id, ssi_type, market, country, currency, instruction_type,
                account_number, swift_code, bic_code,
                beneficiary_bank, beneficiary_bank_account_number,
                additional_info, source_page, source_table, source_row
            FROM ssi_records
            ORDER BY id
            LIMIT 1000
            """,
        )

    st.dataframe(view_df, use_container_width=True)
    if not view_df.empty:
        st.download_button(
            "Download current view CSV",
            data=view_df.to_csv(index=False),
            file_name="ssi_db_view.csv",
            mime="text/csv",
            key="download_db_view",
        )

    st.subheader("Custom SQL (Read-Only)")
    custom_sql = st.text_area(
        "Run SELECT/WITH query",
        value="SELECT * FROM ssi_records LIMIT 50",
        height=120,
    )
    if st.button("Run custom SQL", key="run_custom_sql"):
        try:
            custom_rows = execute_select_query(db_path, custom_sql)
            custom_df = _rows_to_df(rows_to_dicts(custom_rows))
            st.success(f"Returned {len(custom_df)} rows")
            st.dataframe(custom_df, use_container_width=True)
        except Exception as exc:
            st.error(f"Query failed: {exc}")


def _render_chat(db_path: str) -> None:
    summary = get_db_summary(db_path)
    if summary["total_rows"] == 0:
        st.info("Populate SQLite first by running extraction.")
        return

    c1, c2 = st.columns([4, 1])
    with c1:
        st.caption("Chat with the extracted SQLite data")
    with c2:
        if st.button("Clear chat", key="clear_chat"):
            st.session_state.chat_history = []

    st.caption(SAFE_SQL_HELP)

    for idx, message in enumerate(st.session_state.chat_history):
        with st.chat_message(message["role"]):
            st.write(message["content"])
            if message["role"] == "assistant" and message.get("sql"):
                st.code(message["sql"], language="sql")
            if message["role"] == "assistant" and message.get("rows"):
                df = _rows_to_df(message["rows"])
                st.dataframe(df, use_container_width=True)
                if message.get("truncated"):
                    st.caption("Showing first 200 rows")

    user_question = st.chat_input("Ask about SSI data in SQLite")
    if not user_question:
        return

    st.session_state.chat_history.append({"role": "user", "content": user_question})

    try:
        answer = answer_question(db_path=db_path, question=user_question)
        all_rows = answer["rows"]
        preview_rows = all_rows[:200]
        assistant_text = f"{answer['intent']} Returned {answer['row_count']} rows."

        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": assistant_text,
                "sql": answer["sql"],
                "rows": preview_rows,
                "truncated": len(all_rows) > len(preview_rows),
            }
        )
    except Exception as exc:
        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": f"I could not answer that query: {exc}",
            }
        )

    st.rerun()


st.set_page_config(page_title="SSI Extractor", layout="wide")
_init_session_state()

st.title("Securities Settlement Instructions Extractor")
st.caption("One-time extraction -> persist to SQLite -> query/chat over structured SSI data.")
st.caption("Runtime stage logs are emitted to terminal output.")

with st.sidebar:
    st.subheader("LLM Config")
    config_path = st.text_input("Config file", value="config/llm_config.json")
    try:
        loaded_settings = LLMSettings.from_json_file(config_path)
        st.caption("Loaded config (redacted):")
        st.code(json.dumps(loaded_settings.to_redacted_dict(), indent=2), language="json")
    except Exception as exc:
        loaded_settings = None
        st.error(f"Failed to load config: {exc}")

    st.subheader("SQLite")
    db_path = st.text_input("DB file", value="data/ssi.sqlite")
    refresh_db_on_upload = st.checkbox("Refresh DB when uploading a new PDF", value=True)
    initialize_db(db_path)

uploaded = st.file_uploader("Upload SSI PDF", type=["pdf"])

if uploaded and st.button("Run Extraction", type="primary"):
    if loaded_settings is None:
        st.error("Cannot run extraction until a valid config file is loaded.")
        st.stop()

    logger.info(
        "UI extraction started filename=%s size_bytes=%d db_path=%s refresh_db=%s",
        uploaded.name,
        uploaded.size,
        db_path,
        refresh_db_on_upload,
    )

    with st.spinner("Extracting tables, calling LLM, and writing SQLite..."):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp:
            temp.write(uploaded.read())
            temp_path = temp.name

        try:
            pages, result = run_extraction_pipeline(temp_path, loaded_settings)
            stats = persist_extraction(
                db_path=db_path,
                source_file=uploaded.name,
                result=result,
                page_count=len(pages),
                replace_existing=refresh_db_on_upload,
            )
        except Exception as exc:  # pragma: no cover - UI path
            st.error(f"Extraction failed: {exc}")
            logger.exception("UI extraction failed temp_path=%s", temp_path)
            st.stop()

    st.session_state.latest_pages = pages
    st.session_state.latest_result = result
    if refresh_db_on_upload:
        st.session_state.chat_history = []

    logger.info("UI extraction completed stats=%s", stats)
    st.success(f"Extraction complete. Persisted {stats['rows_written']} normalized rows to SQLite.")

main_tab1, main_tab2, main_tab3 = st.tabs(["Latest Extraction", "Database Views", "DB Chat"])

with main_tab1:
    _render_latest_extraction()

with main_tab2:
    _render_database_views(db_path)

with main_tab3:
    _render_chat(db_path)
