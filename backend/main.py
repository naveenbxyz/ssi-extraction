from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
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

DEFAULT_LLM_CONFIG = "config/llm_config.json"
DEFAULT_ISDA_CONFIG = "config/isda_extraction_config.json"
DEFAULT_SSI_DB = "data/ssi.sqlite"
DEFAULT_ISDA_DB = "data/isda_netting.sqlite"


def _reset_sqlite_db(db_path: Path) -> None:
    for candidate in (
        db_path,
        db_path.with_name(f"{db_path.name}-wal"),
        db_path.with_name(f"{db_path.name}-shm"),
    ):
        if candidate.exists():
            candidate.unlink()
            logger.info("Removed SQLite file on startup path=%s", candidate)


class SqlRequest(BaseModel):
    db_path: str
    query: str


class SsiChatRequest(BaseModel):
    llm_config_path: str = DEFAULT_LLM_CONFIG
    db_path: str = DEFAULT_SSI_DB
    question: str = Field(min_length=1)
    extraction_payload: Optional[dict[str, Any]] = None


class IsdaChatRequest(BaseModel):
    llm_config_path: str = DEFAULT_LLM_CONFIG
    isda_config_path: str = DEFAULT_ISDA_CONFIG
    db_path: str = DEFAULT_ISDA_DB
    question: str = Field(min_length=1)
    doc_id: int


class FrontendDefaults(BaseModel):
    llm_config_path: str
    isda_config_path: str
    ssi_db_path: str
    isda_db_path: str


class BootstrapResponse(BaseModel):
    defaults: FrontendDefaults
    llm_config: Optional[dict[str, Any]]
    isda_config_summary: dict[str, Any]
    ssi_summary: dict[str, int]
    isda_summary: dict[str, int]


def _resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return ROOT / path


def _load_llm_settings(config_path: str) -> LLMSettings:
    try:
        return LLMSettings.from_json_file(_resolve_path(config_path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load LLM config: {exc}") from exc


def _load_isda_app_config(config_path: str) -> dict[str, Any]:
    try:
        return load_isda_config(str(_resolve_path(config_path)))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load ISDA config: {exc}") from exc


def _safe_country_key(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text.strip())
    cleaned = cleaned.strip("_")
    return cleaned[:120]


def _ssi_latest_payload(db_path: str) -> dict[str, Any]:
    return {
        "metadata": get_latest_run_metadata(db_path),
        "structured": get_latest_extraction_payload(db_path),
        "raw_pages": get_latest_raw_pdf_payload(db_path),
    }


def _isda_context_payload(db_path: str, doc_id: int) -> dict[str, Any]:
    context = get_isda_document_context(db_path, doc_id)
    if context is None:
        raise HTTPException(status_code=404, detail="ISDA document not found")
    return context


app = FastAPI(title="SSI Extraction API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    resolved_ssi_db = _resolve_path(DEFAULT_SSI_DB)
    resolved_isda_db = _resolve_path(DEFAULT_ISDA_DB)
    _reset_sqlite_db(resolved_ssi_db)
    _reset_sqlite_db(resolved_isda_db)
    initialize_db(str(resolved_ssi_db))
    initialize_isda_db(str(resolved_isda_db))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/bootstrap", response_model=BootstrapResponse)
def bootstrap(
    llm_config_path: str = Query(DEFAULT_LLM_CONFIG),
    isda_config_path: str = Query(DEFAULT_ISDA_CONFIG),
    ssi_db_path: str = Query(DEFAULT_SSI_DB),
    isda_db_path: str = Query(DEFAULT_ISDA_DB),
) -> BootstrapResponse:
    llm_config: Optional[dict[str, Any]]
    try:
        llm_config = _load_llm_settings(llm_config_path).to_redacted_dict()
    except HTTPException:
        llm_config = None

    isda_config_summary: dict[str, Any]
    try:
        isda_config = _load_isda_app_config(isda_config_path)
        isda_config_summary = {
            "field_catalog_count": len(isda_config.get("field_catalog", [])),
            "field_catalog_path": str(isda_config.get("field_catalog_path", "")),
        }
    except HTTPException:
        isda_config_summary = {"field_catalog_count": 0, "field_catalog_path": ""}

    resolved_ssi_db_path = str(_resolve_path(ssi_db_path))
    resolved_isda_db_path = str(_resolve_path(isda_db_path))
    initialize_db(resolved_ssi_db_path)
    initialize_isda_db(resolved_isda_db_path)

    return BootstrapResponse(
        defaults=FrontendDefaults(
            llm_config_path=llm_config_path,
            isda_config_path=isda_config_path,
            ssi_db_path=ssi_db_path,
            isda_db_path=isda_db_path,
        ),
        llm_config=llm_config,
        isda_config_summary=isda_config_summary,
        ssi_summary=get_db_summary(resolved_ssi_db_path),
        isda_summary=get_isda_summary(resolved_isda_db_path),
    )


@app.get("/api/config/llm")
def get_llm_config(config_path: str = Query(DEFAULT_LLM_CONFIG)) -> dict[str, Any]:
    settings = _load_llm_settings(config_path)
    return {"config_path": config_path, "settings": settings.to_redacted_dict()}


@app.get("/api/config/isda")
def get_isda_config(config_path: str = Query(DEFAULT_ISDA_CONFIG)) -> dict[str, Any]:
    config = _load_isda_app_config(config_path)
    return {
        "config_path": config_path,
        "field_catalog_path": config.get("field_catalog_path", ""),
        "field_catalog_count": len(config.get("field_catalog", [])),
    }


@app.post("/api/ssi/extract")
async def extract_ssi(
    file: UploadFile = File(...),
    llm_config_path: str = Form(DEFAULT_LLM_CONFIG),
    db_path: str = Form(DEFAULT_SSI_DB),
    refresh_db_on_upload: bool = Form(True),
) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="SSI extraction requires a PDF upload")

    settings = _load_llm_settings(llm_config_path)
    resolved_db_path = str(_resolve_path(db_path))
    initialize_db(resolved_db_path)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp:
        temp.write(await file.read())
        temp_path = temp.name

    try:
        pages, result = run_extraction_pipeline(temp_path, settings)
        raw_pages = pages_to_prompt_payload(pages)
        stats = persist_extraction(
            db_path=resolved_db_path,
            source_file=file.filename,
            result=result,
            page_count=len(pages),
            raw_pdf_payload=raw_pages,
            replace_existing=refresh_db_on_upload,
        )
    finally:
        Path(temp_path).unlink(missing_ok=True)
    return {
        "stats": stats,
        "latest": {
            "metadata": get_latest_run_metadata(resolved_db_path),
            "structured": result.to_dict(),
            "raw_pages": raw_pages,
        },
    }


@app.get("/api/ssi/latest")
def get_ssi_latest(db_path: str = Query(DEFAULT_SSI_DB)) -> dict[str, Any]:
    resolved_db_path = str(_resolve_path(db_path))
    initialize_db(resolved_db_path)
    return _ssi_latest_payload(resolved_db_path)


@app.get("/api/ssi/summary")
def get_ssi_summary(db_path: str = Query(DEFAULT_SSI_DB)) -> dict[str, Any]:
    resolved_db_path = str(_resolve_path(db_path))
    initialize_db(resolved_db_path)
    return {"summary": get_db_summary(resolved_db_path)}


@app.get("/api/ssi/views/{view_name}")
def get_ssi_view(
    view_name: Literal["standard", "us", "cash"],
    db_path: str = Query(DEFAULT_SSI_DB),
    search_term: str = Query(""),
) -> dict[str, Any]:
    resolved_db_path = str(_resolve_path(db_path))
    initialize_db(resolved_db_path)

    if view_name == "standard":
        rows = get_standard_ssi_view(resolved_db_path, search_term=search_term)
    elif view_name == "us":
        rows = get_us_ssi_view(resolved_db_path, search_term=search_term)
    else:
        rows = get_cash_settlement_view(resolved_db_path, search_term=search_term)

    return {"rows": rows}


@app.post("/api/ssi/query")
def query_ssi(request: SqlRequest) -> dict[str, Any]:
    resolved_db_path = str(_resolve_path(request.db_path))
    initialize_db(resolved_db_path)
    rows = execute_select_query(resolved_db_path, request.query)
    return {"rows": rows_to_dicts(rows)}


@app.post("/api/ssi/chat")
def ssi_chat(request: SsiChatRequest) -> dict[str, str]:
    settings = _load_llm_settings(request.llm_config_path)
    resolved_db_path = str(_resolve_path(request.db_path))
    initialize_db(resolved_db_path)
    extraction_payload = request.extraction_payload or get_latest_extraction_payload(resolved_db_path)
    if extraction_payload is None:
        raise HTTPException(status_code=404, detail="No SSI extraction payload available for chat")

    answer = answer_question_from_json(
        settings=settings,
        extraction_payload=extraction_payload,
        question=request.question,
        task_label="ssi_json_chat",
    )
    return {"answer": answer}


@app.post("/api/isda/extract")
async def extract_isda(
    file: UploadFile = File(...),
    llm_config_path: str = Form(DEFAULT_LLM_CONFIG),
    isda_config_path: str = Form(DEFAULT_ISDA_CONFIG),
    db_path: str = Form(DEFAULT_ISDA_DB),
    country_override: str = Form(""),
) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="ISDA extraction requires a DOCX upload")

    settings = _load_llm_settings(llm_config_path)
    resolved_db_path = str(_resolve_path(db_path))
    resolved_isda_config_path = str(_resolve_path(isda_config_path))
    initialize_isda_db(resolved_db_path)

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp:
        temp.write(await file.read())
        temp_path = temp.name

    try:
        raw_payload, extraction = run_isda_extraction_pipeline(
            docx_path=temp_path,
            settings=settings,
            isda_config_path=resolved_isda_config_path,
        )
    finally:
        Path(temp_path).unlink(missing_ok=True)
    country_candidate = (
        country_override.strip()
        or str(extraction.get("country", "")).strip()
        or str(extraction.get("jurisdiction", "")).strip()
        or Path(file.filename).stem
    )
    country_key = _safe_country_key(country_candidate) or _safe_country_key(Path(file.filename).stem)
    stats = upsert_isda_document(
        db_path=resolved_db_path,
        source_file=file.filename,
        country_key=country_key,
        extraction_payload=extraction,
        raw_docx_payload=raw_payload,
    )

    return {
        "stats": stats,
        "document": {
            "country_key": country_key,
            "structured": extraction,
            "raw_payload": raw_payload,
        },
    }


@app.get("/api/isda/summary")
def get_isda_summary_endpoint(db_path: str = Query(DEFAULT_ISDA_DB)) -> dict[str, Any]:
    resolved_db_path = str(_resolve_path(db_path))
    initialize_isda_db(resolved_db_path)
    return {"summary": get_isda_summary(resolved_db_path)}


@app.get("/api/isda/documents")
def get_isda_documents(db_path: str = Query(DEFAULT_ISDA_DB)) -> dict[str, Any]:
    resolved_db_path = str(_resolve_path(db_path))
    initialize_isda_db(resolved_db_path)
    return {"documents": list_isda_documents(resolved_db_path)}


@app.get("/api/isda/documents/{doc_id}")
def get_isda_document(doc_id: int, db_path: str = Query(DEFAULT_ISDA_DB)) -> dict[str, Any]:
    resolved_db_path = str(_resolve_path(db_path))
    initialize_isda_db(resolved_db_path)
    return _isda_context_payload(resolved_db_path, doc_id)


@app.get("/api/isda/documents/{doc_id}/fields")
def get_isda_document_fields(
    doc_id: int,
    db_path: str = Query(DEFAULT_ISDA_DB),
    search_term: str = Query(""),
) -> dict[str, Any]:
    resolved_db_path = str(_resolve_path(db_path))
    initialize_isda_db(resolved_db_path)
    return {"rows": get_isda_fields_view(resolved_db_path, doc_id, search_term=search_term)}


@app.post("/api/isda/query")
def query_isda(request: SqlRequest) -> dict[str, Any]:
    resolved_db_path = str(_resolve_path(request.db_path))
    initialize_isda_db(resolved_db_path)
    return {"rows": execute_isda_select_query(resolved_db_path, request.query)}


@app.post("/api/isda/chat")
def isda_chat(request: IsdaChatRequest) -> dict[str, str]:
    settings = _load_llm_settings(request.llm_config_path)
    isda_config = _load_isda_app_config(request.isda_config_path)
    resolved_db_path = str(_resolve_path(request.db_path))
    initialize_isda_db(resolved_db_path)
    context = _isda_context_payload(resolved_db_path, request.doc_id)

    payload = {
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
    answer = answer_question_from_json(
        settings=settings,
        extraction_payload=payload,
        question=request.question,
        system_prompt=str(isda_config.get("chat_system_prompt", "")),
        task_label="isda_json_chat",
    )
    return {"answer": answer}
