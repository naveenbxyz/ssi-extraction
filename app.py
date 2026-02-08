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

from ssi_extraction.models import LLMSettings
from ssi_extraction.service import run_extraction_pipeline

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
root_logger = logging.getLogger()
if not root_logger.handlers:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
else:
    root_logger.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

st.set_page_config(page_title="SSI Extractor", layout="wide")
st.title("Securities Settlement Instructions Extractor")
st.caption("Upload SSI PDF, extract tables with pdfplumber, normalize using local Qwen endpoint.")
st.caption("Runtime stage logs are emitted to the Streamlit terminal output.")

with st.sidebar:
    st.subheader("Model Settings")
    base_url = st.text_input("Base URL", value="http://localhost:8080")
    model = st.text_input("Model", value="Qwen/Qwen3-8B-Instruct")
    temperature = st.number_input("Temperature", min_value=0.0, max_value=1.0, value=0.0, step=0.1)
    max_tokens = st.number_input("Max tokens", min_value=256, max_value=32768, value=4096, step=256)
    timeout_s = st.number_input("Request timeout (s)", min_value=5, max_value=600, value=120, step=5)
    pages_per_chunk = st.number_input("Pages per chunk", min_value=1, max_value=10, value=3, step=1)

uploaded = st.file_uploader("Upload SSI PDF", type=["pdf"])


if uploaded:
    if st.button("Run Extraction", type="primary"):
        logger.info("UI run started filename=%s size_bytes=%d", uploaded.name, uploaded.size)
        with st.spinner("Extracting tables and calling local model..."):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp:
                temp.write(uploaded.read())
                temp_path = temp.name
            logger.info("Uploaded PDF buffered to temp_path=%s", temp_path)

            settings = LLMSettings(
                base_url=base_url,
                model=model,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                request_timeout_s=int(timeout_s),
                pages_per_chunk=int(pages_per_chunk),
            )

            try:
                pages, result = run_extraction_pipeline(temp_path, settings)
            except Exception as exc:  # pragma: no cover - UI path
                st.error(f"Extraction failed: {exc}")
                logger.exception("UI run failed temp_path=%s", temp_path)
                st.stop()

        logger.info(
            "UI run completed filename=%s pages=%d records=%d us_rows=%d cash_rows=%d",
            uploaded.name,
            len(pages),
            len(result.records),
            len(result.us_securities_settlement),
            len(result.cash_settlement),
        )
        st.success("Extraction complete")

        st.subheader("Summary")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pages", len(pages))
        c2.metric("Standard SSI rows", len(result.records))
        c3.metric("US SSI rows", len(result.us_securities_settlement))
        c4.metric("Cash settlement rows", len(result.cash_settlement))

        search = st.text_input("Search extracted values", value="")

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

        tab1, tab2, tab3, tab4 = st.tabs(
            ["Standard SSI", "US Securities Settlement", "Cash Settlement", "Raw Pages"]
        )

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
        )

        if not records_df.empty:
            st.download_button(
                "Download standard SSI CSV",
                data=records_df.to_csv(index=False),
                file_name="standard_ssi.csv",
                mime="text/csv",
            )
        if not us_df.empty:
            st.download_button(
                "Download US SSI CSV",
                data=us_df.to_csv(index=False),
                file_name="us_ssi.csv",
                mime="text/csv",
            )
        if not cash_df.empty:
            st.download_button(
                "Download cash settlement CSV",
                data=cash_df.to_csv(index=False),
                file_name="cash_settlement.csv",
                mime="text/csv",
            )

        if result.notes:
            st.subheader("Notes")
            for note in result.notes:
                st.write(f"- {note}")
else:
    st.info("Upload a PDF to begin.")
