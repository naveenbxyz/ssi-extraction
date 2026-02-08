from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

import sys

ROOT = Path(__file__).parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ssi_extraction.isda_config import load_isda_config
from ssi_extraction.isda_service import run_isda_extraction_pipeline
from ssi_extraction.isda_sqlite_store import (
    execute_isda_select_query,
    get_isda_document_context,
    get_isda_fields_view,
    get_isda_summary,
    initialize_isda_db,
    list_isda_documents,
    upsert_isda_document,
)
from ssi_extraction.json_chat import answer_question_from_json
from ssi_extraction.models import LLMSettings
from ssi_extraction.pdf_extractor import pages_to_prompt_payload
from ssi_extraction.service import run_extraction_pipeline
from ssi_extraction.sqlite_store import (
    execute_select_query,
    get_cash_settlement_view,
    get_db_summary,
    get_latest_extraction_payload,
    get_latest_raw_pdf_payload,
    get_latest_run_metadata,
    get_standard_ssi_view,
    get_us_ssi_view,
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
    defaults = {
        "workflow_mode": "SSI Extraction",
        "active_ssi_section": "Latest Extraction",
        "active_isda_section": "Upload & Extract",
        "latest_pages": None,
        "latest_result": None,
        "ssi_chat_history": [],
        "latest_isda_raw_payload": None,
        "latest_isda_extraction": None,
        "latest_isda_country_key": "",
        "isda_chat_history": [],
        "isda_chat_doc_id": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _rows_to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _render_table_with_download(title: str, df: pd.DataFrame, filename: str, key_suffix: str) -> None:
    st.markdown(f"**{title}**")
    st.dataframe(df, use_container_width=True)
    if not df.empty:
        st.download_button(
            f"Download {title} CSV",
            data=df.to_csv(index=False),
            file_name=filename,
            mime="text/csv",
            key=f"download_{key_suffix}",
        )


def _render_ssi_latest_extraction() -> None:
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


def _render_ssi_database_views(db_path: str) -> None:
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

    latest_meta = get_latest_run_metadata(db_path)
    latest_structured = get_latest_extraction_payload(db_path)
    latest_raw = get_latest_raw_pdf_payload(db_path)

    with st.expander("Latest run payloads for cross-check"):
        if latest_meta:
            st.write(
                f"Run #{latest_meta['run_id']} | File: {latest_meta['source_file']} | "
                f"Extracted at: {latest_meta['extracted_at']} | Pages: {latest_meta['page_count']}"
            )
        if latest_structured is not None:
            st.download_button(
                "Download latest structured JSON (LLM output)",
                data=json.dumps(latest_structured, indent=2),
                file_name="latest_structured_extraction.json",
                mime="application/json",
                key="download_latest_structured_db",
            )
        if latest_raw is not None:
            st.download_button(
                "Download latest raw pdfplumber payload",
                data=json.dumps(latest_raw, indent=2),
                file_name="latest_raw_pdfplumber_payload.json",
                mime="application/json",
                key="download_latest_raw_db",
            )

    search_term = st.text_input(
        "Search across account number / account name / BIC / country / currency / details",
        value="",
        key="ssi_db_search_term",
    )

    standard_df = _rows_to_df(get_standard_ssi_view(db_path, search_term=search_term))
    us_df = _rows_to_df(get_us_ssi_view(db_path, search_term=search_term))
    cash_df = _rows_to_df(get_cash_settlement_view(db_path, search_term=search_term))

    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "Standard SSI Table",
            "US SSI Variants Table",
            "Cash Settlement Table",
            "Custom SQL",
        ]
    )

    with tab1:
        _render_table_with_download("Standard SSI", standard_df, "standard_ssi_db.csv", "standard_db")

    with tab2:
        _render_table_with_download("US SSI Variants", us_df, "us_ssi_db.csv", "us_db")

    with tab3:
        _render_table_with_download("Cash Settlement", cash_df, "cash_settlement_db.csv", "cash_db")

    with tab4:
        st.caption("Read-only SQL allowed (SELECT / WITH only)")
        custom_sql = st.text_area(
            "Run query",
            value="SELECT * FROM standard_ssi LIMIT 50",
            height=120,
            key="ssi_custom_sql_text",
        )
        if st.button("Run custom SQL", key="ssi_run_custom_sql"):
            try:
                custom_rows = execute_select_query(db_path, custom_sql)
                custom_df = _rows_to_df(rows_to_dicts(custom_rows))
                st.success(f"Returned {len(custom_df)} rows")
                st.dataframe(custom_df, use_container_width=True)
            except Exception as exc:
                st.error(f"Query failed: {exc}")


def _render_ssi_json_chat(db_path: str, settings: LLMSettings | None) -> None:
    if settings is None:
        st.error("Valid LLM config is required for chat.")
        return

    summary = get_db_summary(db_path)
    if summary["total_rows"] == 0:
        st.info("Populate SQLite first by running extraction.")
        return

    extraction_payload = None
    if st.session_state.latest_result is not None:
        extraction_payload = st.session_state.latest_result.to_dict()
    else:
        extraction_payload = get_latest_extraction_payload(db_path)

    if extraction_payload is None:
        st.info("No extraction JSON payload available for chat.")
        return

    c1, c2 = st.columns([4, 1])
    with c1:
        st.caption("Chat with full extracted JSON context")
    with c2:
        if st.button("Clear chat", key="clear_ssi_chat"):
            st.session_state.ssi_chat_history = []

    st.caption("Responses are generated from full extraction JSON context, not DB rows.")

    for message in st.session_state.ssi_chat_history:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    user_question = st.chat_input("Ask about SSI data in extracted JSON", key="ssi_chat_input")
    if not user_question:
        return

    st.session_state.ssi_chat_history.append({"role": "user", "content": user_question})
    with st.chat_message("user"):
        st.write(user_question)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing extracted JSON..."):
            try:
                answer = answer_question_from_json(
                    settings=settings,
                    extraction_payload=extraction_payload,
                    question=user_question,
                    task_label="ssi_json_chat",
                )
            except Exception as exc:
                answer = f"I could not answer that query: {exc}"
        st.write(answer)

    st.session_state.ssi_chat_history.append({"role": "assistant", "content": answer})


def _render_ssi_mode(loaded_settings: LLMSettings | None, ssi_db_path: str, refresh_db_on_upload: bool) -> None:
    uploaded = st.file_uploader("Upload SSI PDF", type=["pdf"], key="ssi_pdf_uploader")

    if uploaded and st.button("Run SSI Extraction", type="primary", key="ssi_extract_button"):
        if loaded_settings is None:
            st.error("Cannot run extraction until a valid LLM config is loaded.")
            st.stop()

        logger.info(
            "UI SSI extraction started filename=%s size_bytes=%d db_path=%s refresh_db=%s",
            uploaded.name,
            uploaded.size,
            ssi_db_path,
            refresh_db_on_upload,
        )

        with st.spinner("Extracting tables, calling LLM, and writing SSI SQLite..."):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp:
                temp.write(uploaded.read())
                temp_path = temp.name

            try:
                pages, result = run_extraction_pipeline(temp_path, loaded_settings)
                raw_payload = pages_to_prompt_payload(pages)
                stats = persist_extraction(
                    db_path=ssi_db_path,
                    source_file=uploaded.name,
                    result=result,
                    page_count=len(pages),
                    raw_pdf_payload=raw_payload,
                    replace_existing=refresh_db_on_upload,
                )
            except Exception as exc:
                st.error(f"Extraction failed: {exc}")
                logger.exception("UI SSI extraction failed temp_path=%s", temp_path)
                st.stop()

        st.session_state.latest_pages = pages
        st.session_state.latest_result = result
        if refresh_db_on_upload:
            st.session_state.ssi_chat_history = []

        logger.info("UI SSI extraction completed stats=%s", stats)
        st.success(f"SSI extraction complete. Persisted {stats['rows_written']} normalized rows to SQLite.")

    section = st.radio(
        "SSI Section",
        options=["Latest Extraction", "Database Views", "JSON Chat"],
        horizontal=True,
        key="active_ssi_section",
    )

    if section == "Latest Extraction":
        _render_ssi_latest_extraction()
    elif section == "Database Views":
        _render_ssi_database_views(ssi_db_path)
    else:
        _render_ssi_json_chat(ssi_db_path, loaded_settings)


def _safe_country_key(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip())
    cleaned = cleaned.strip("_")
    return cleaned[:120]


def _render_isda_latest_extraction() -> None:
    extraction = st.session_state.latest_isda_extraction
    raw_payload = st.session_state.latest_isda_raw_payload
    country_key = st.session_state.latest_isda_country_key

    if extraction is None or raw_payload is None:
        st.info("Upload and extract an ISDA DOCX to see latest results.")
        return

    st.subheader("Latest ISDA Extraction")
    st.caption(f"Country key: {country_key or 'N/A'}")

    summary_text = str(extraction.get("summary", "")).strip()
    if summary_text:
        st.markdown("**Summary**")
        st.write(summary_text)

    fields_df = _rows_to_df(extraction.get("normalized_fields", []))
    additional_df = _rows_to_df(extraction.get("additional_fields", []))

    tab1, tab2, tab3 = st.tabs(["Normalized Fields", "Additional Fields", "Raw Payload Stats"])

    with tab1:
        st.dataframe(fields_df, use_container_width=True)
    with tab2:
        st.dataframe(additional_df, use_container_width=True)
    with tab3:
        stats = raw_payload.get("stats", {})
        c1, c2, c3 = st.columns(3)
        c1.metric("Paragraphs", int(stats.get("paragraph_count", 0)))
        c2.metric("Tables", int(stats.get("table_count", 0)))
        c3.metric("KV Candidates", int(stats.get("candidate_count", 0)))

    st.download_button(
        "Download latest ISDA structured JSON",
        data=json.dumps(extraction, indent=2),
        file_name="isda_extraction.json",
        mime="application/json",
        key="download_latest_isda_structured",
    )
    st.download_button(
        "Download latest ISDA raw DOCX payload",
        data=json.dumps(raw_payload, indent=2),
        file_name="isda_raw_payload.json",
        mime="application/json",
        key="download_latest_isda_raw",
    )


def _render_isda_upload_extract(
    loaded_settings: LLMSettings | None,
    isda_config_path: str,
    isda_db_path: str,
) -> None:
    uploaded = st.file_uploader("Upload ISDA Netting Review DOCX", type=["docx"], key="isda_docx_uploader")
    country_override = st.text_input(
        "Country key override (optional)",
        value="",
        key="isda_country_override",
        help="If provided, this key is used for upsert. Otherwise country/jurisdiction/filename will be used.",
    )

    if uploaded and st.button("Extract ISDA Summary", type="primary", key="isda_extract_button"):
        if loaded_settings is None:
            st.error("Cannot run extraction until a valid LLM config is loaded.")
            st.stop()

        with st.spinner("Extracting DOCX tables/text, running hybrid extraction, and writing ISDA SQLite..."):
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp:
                temp.write(uploaded.read())
                temp_path = temp.name

            try:
                raw_payload, extraction = run_isda_extraction_pipeline(
                    docx_path=temp_path,
                    settings=loaded_settings,
                    isda_config_path=isda_config_path,
                )
            except Exception as exc:
                st.error(f"ISDA extraction failed: {exc}")
                logger.exception("ISDA extraction failed temp_path=%s", temp_path)
                st.stop()

            country_candidate = (
                country_override.strip()
                or str(extraction.get("country", "")).strip()
                or str(extraction.get("jurisdiction", "")).strip()
                or Path(uploaded.name).stem
            )
            country_key = _safe_country_key(country_candidate) or _safe_country_key(Path(uploaded.name).stem)

            stats = upsert_isda_document(
                db_path=isda_db_path,
                source_file=uploaded.name,
                country_key=country_key,
                extraction_payload=extraction,
                raw_docx_payload=raw_payload,
            )

        st.session_state.latest_isda_raw_payload = raw_payload
        st.session_state.latest_isda_extraction = extraction
        st.session_state.latest_isda_country_key = country_key
        st.session_state.isda_chat_history = []

        status = "replaced existing country document" if stats["replaced"] else "inserted new country document"
        st.success(
            f"ISDA extraction complete. {status}. "
            f"Country key: {stats['country_key']} | Field rows: {stats['field_rows']}"
        )

    _render_isda_latest_extraction()


def _render_isda_database_views(isda_db_path: str) -> None:
    summary = get_isda_summary(isda_db_path)
    st.subheader("ISDA SQLite Data")

    c1, c2 = st.columns(2)
    c1.metric("Documents", summary["document_count"])
    c2.metric("Field rows", summary["field_count"])

    documents = list_isda_documents(isda_db_path)
    if not documents:
        st.info("No ISDA documents in database yet.")
        return

    docs_df = _rows_to_df(documents)
    st.dataframe(docs_df, use_container_width=True)

    options = {f"{doc['country_key']} | {doc['source_file']} | {doc['uploaded_at']}": doc for doc in documents}
    selected_label = st.selectbox("Select document", options=list(options.keys()), key="isda_doc_select_db")
    selected_doc = options[selected_label]

    context = get_isda_document_context(isda_db_path, int(selected_doc["doc_id"]))
    if context is None:
        st.warning("Selected document could not be loaded.")
        return

    st.markdown("**Selected Document Summary**")
    st.write(context.get("summary") or "No summary")

    search_term = st.text_input(
        "Search fields by field name/value",
        value="",
        key="isda_db_search_term",
    )
    fields = get_isda_fields_view(isda_db_path, int(selected_doc["doc_id"]), search_term=search_term)
    fields_df = _rows_to_df(fields)
    st.dataframe(fields_df, use_container_width=True)

    st.download_button(
        "Download selected document structured JSON",
        data=json.dumps(context["extraction_json"], indent=2),
        file_name=f"isda_{context['country_key']}_structured.json",
        mime="application/json",
        key="download_selected_isda_structured",
    )
    st.download_button(
        "Download selected document raw DOCX payload",
        data=json.dumps(context["raw_docx_payload"], indent=2),
        file_name=f"isda_{context['country_key']}_raw_payload.json",
        mime="application/json",
        key="download_selected_isda_raw",
    )

    st.subheader("Custom SQL (Read-Only)")
    custom_sql = st.text_area(
        "Run query",
        value="SELECT * FROM isda_fields LIMIT 50",
        height=120,
        key="isda_custom_sql_text",
    )
    if st.button("Run custom SQL", key="isda_run_custom_sql"):
        try:
            rows = execute_isda_select_query(isda_db_path, custom_sql)
            st.success(f"Returned {len(rows)} rows")
            st.dataframe(_rows_to_df(rows), use_container_width=True)
        except Exception as exc:
            st.error(f"Query failed: {exc}")


def _render_isda_json_chat(
    isda_db_path: str,
    loaded_settings: LLMSettings | None,
    isda_config: dict,
) -> None:
    if loaded_settings is None:
        st.error("Valid LLM config is required for chat.")
        return

    documents = list_isda_documents(isda_db_path)
    if not documents:
        st.info("No ISDA documents available. Upload and extract first.")
        return

    options = {f"{doc['country_key']} | {doc['source_file']} | {doc['uploaded_at']}": doc for doc in documents}
    selected_label = st.selectbox("Select document for chat", options=list(options.keys()), key="isda_doc_select_chat")
    selected_doc = options[selected_label]
    selected_doc_id = int(selected_doc["doc_id"])

    if st.session_state.isda_chat_doc_id != selected_doc_id:
        st.session_state.isda_chat_doc_id = selected_doc_id
        st.session_state.isda_chat_history = []

    context = get_isda_document_context(isda_db_path, selected_doc_id)
    if context is None:
        st.warning("Selected document context could not be loaded.")
        return

    chat_context_payload = {
        "metadata": {
            "country_key": context["country_key"],
            "country": context.get("country", ""),
            "jurisdiction": context.get("jurisdiction", ""),
            "source_file": context.get("source_file", ""),
            "uploaded_at": context.get("uploaded_at", ""),
        },
        "extraction_json": context["extraction_json"],
        "raw_docx_payload": context["raw_docx_payload"],
    }

    c1, c2 = st.columns([4, 1])
    with c1:
        st.caption("Chat with full ISDA document context (structured + raw DOCX extract)")
    with c2:
        if st.button("Clear ISDA chat", key="clear_isda_chat"):
            st.session_state.isda_chat_history = []

    for message in st.session_state.isda_chat_history:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    user_question = st.chat_input("Ask about this ISDA document", key="isda_chat_input")
    if not user_question:
        return

    st.session_state.isda_chat_history.append({"role": "user", "content": user_question})
    with st.chat_message("user"):
        st.write(user_question)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing ISDA document context..."):
            try:
                answer = answer_question_from_json(
                    settings=loaded_settings,
                    extraction_payload=chat_context_payload,
                    question=user_question,
                    system_prompt=str(isda_config.get("chat_system_prompt", "")),
                    task_label="isda_json_chat",
                )
            except Exception as exc:
                answer = f"I could not answer that query: {exc}"
        st.write(answer)

    st.session_state.isda_chat_history.append({"role": "assistant", "content": answer})


def _render_isda_mode(
    loaded_settings: LLMSettings | None,
    isda_config_path: str,
    isda_db_path: str,
    isda_config: dict,
) -> None:
    section = st.radio(
        "ISDA Section",
        options=["Upload & Extract", "Database Views", "JSON Chat"],
        horizontal=True,
        key="active_isda_section",
    )

    if section == "Upload & Extract":
        _render_isda_upload_extract(loaded_settings, isda_config_path, isda_db_path)
    elif section == "Database Views":
        _render_isda_database_views(isda_db_path)
    else:
        _render_isda_json_chat(isda_db_path, loaded_settings, isda_config)


st.set_page_config(page_title="SSI + ISDA Extractor", layout="wide")
_init_session_state()

st.title("Securities Settlement + ISDA Netting Extractor")
st.caption("Airgapped workflow for SSI PDF extraction and ISDA Netting Review DOCX extraction.")
st.caption("Runtime stage logs are emitted to terminal output.")

with st.sidebar:
    st.subheader("Workflow")
    workflow_mode = st.radio(
        "Choose workflow",
        options=["SSI Extraction", "ISDA Netting Review"],
        key="workflow_mode",
    )

    st.subheader("LLM Config")
    llm_config_path = st.text_input("LLM config file", value="config/llm_config.json")
    try:
        loaded_settings = LLMSettings.from_json_file(llm_config_path)
        st.caption("Loaded LLM config (redacted):")
        st.code(json.dumps(loaded_settings.to_redacted_dict(), indent=2), language="json")
    except Exception as exc:
        loaded_settings = None
        st.error(f"Failed to load LLM config: {exc}")

    if workflow_mode == "SSI Extraction":
        st.subheader("SSI SQLite")
        ssi_db_path = st.text_input("SSI DB file", value="data/ssi.sqlite")
        refresh_ssi_db = st.checkbox("Refresh SSI DB on new upload", value=True)
        initialize_db(ssi_db_path)

        # Placeholders for non-active mode
        isda_db_path = "data/isda_netting.sqlite"
        isda_config_path = "config/isda_extraction_config.json"
        isda_config = {"chat_system_prompt": ""}
    else:
        st.subheader("ISDA Config")
        isda_config_path = st.text_input("ISDA config file", value="config/isda_extraction_config.json")
        try:
            isda_config = load_isda_config(isda_config_path)
            st.caption(f"Loaded ISDA config. Canonical fields: {len(isda_config.get('canonical_fields', []))}")
        except Exception as exc:
            isda_config = {"chat_system_prompt": "", "canonical_fields": [], "field_aliases": {}}
            st.error(f"Failed to load ISDA config: {exc}")

        st.subheader("ISDA SQLite")
        isda_db_path = st.text_input("ISDA DB file", value="data/isda_netting.sqlite")
        initialize_isda_db(isda_db_path)

        # Placeholders for non-active mode
        ssi_db_path = "data/ssi.sqlite"
        refresh_ssi_db = True

if workflow_mode == "SSI Extraction":
    _render_ssi_mode(loaded_settings, ssi_db_path=ssi_db_path, refresh_db_on_upload=refresh_ssi_db)
else:
    _render_isda_mode(
        loaded_settings,
        isda_config_path=isda_config_path,
        isda_db_path=isda_db_path,
        isda_config=isda_config,
    )
