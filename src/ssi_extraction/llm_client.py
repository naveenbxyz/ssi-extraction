from __future__ import annotations

import logging
import time
from typing import Any

import httpx

try:
    from openai import OpenAI as OpenAIClient
except Exception:  # pragma: no cover - compatibility guard
    try:
        from openai import Client as OpenAIClient  # type: ignore
    except Exception:  # pragma: no cover - compatibility guard
        OpenAIClient = None  # type: ignore[assignment]

try:  # pragma: no cover - import compatibility
    import openai as openai_legacy
except Exception:  # pragma: no cover - import compatibility
    openai_legacy = None

from .models import LLMSettings
from .parser import extract_json_object, normalize_chunk_result
from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


class LocalOpenAICompatibleClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings
        self._http_client = httpx.Client(
            verify=self.settings.verify_ssl,
            timeout=self.settings.request_timeout_s,
        )
        self._use_modern_client = OpenAIClient is not None

        if self._use_modern_client:
            self.client = OpenAIClient(  # type: ignore[misc]
                base_url=self.settings.base_url,
                api_key=self.settings.api_key,
                http_client=self._http_client,
            )
            logger.info("LLM client initialized sdk=modern")
        else:
            if openai_legacy is None:
                raise RuntimeError("No usable openai client found. Install openai>=1.60.0")
            self.client = None
            openai_legacy.api_base = self.settings.base_url
            openai_legacy.api_key = self.settings.api_key
            if hasattr(openai_legacy, "verify_ssl_certs"):
                openai_legacy.verify_ssl_certs = self.settings.verify_ssl
            logger.warning("LLM client initialized sdk=legacy; upgrade recommended for full compatibility")

    @property
    def chat_endpoint(self) -> str:
        return self.settings.base_url.rstrip("/") + "/chat/completions"

    @property
    def models_endpoint(self) -> str:
        return self.settings.base_url.rstrip("/") + "/models"

    def close(self) -> None:
        self._http_client.close()

    def log_connectivity(self) -> None:
        started = time.perf_counter()
        logger.info("LLM preflight started endpoint=%s", self.models_endpoint)
        headers = {"Authorization": f"Bearer {self.settings.api_key}"} if self.settings.api_key else {}
        try:
            response = self._http_client.get(self.models_endpoint, headers=headers)
            elapsed_s = time.perf_counter() - started
            logger.info(
                "LLM preflight completed status=%d elapsed_s=%.2f",
                response.status_code,
                elapsed_s,
            )
            if response.status_code >= 400:
                logger.warning("LLM preflight body=%s", response.text[:500])
        except Exception as exc:
            elapsed_s = time.perf_counter() - started
            logger.warning(
                "LLM preflight failed elapsed_s=%.2f endpoint=%s error=%s",
                elapsed_s,
                self.models_endpoint,
                exc,
            )

    def _build_request_body(self, page_payload: list[dict], include_response_format: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(page_payload)},
            ],
        }
        if include_response_format:
            body["response_format"] = {"type": "json_object"}
        return body

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return isinstance(exc, httpx.TimeoutException) or "timed out" in text or "timeout" in text

    @staticmethod
    def _is_response_format_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "response_format" in text and (
            "unsupported" in text
            or "invalid" in text
            or "not supported" in text
            or "unknown" in text
            or "extra inputs are not permitted" in text
            or "unexpected keyword" in text
        )

    @staticmethod
    def _get_field(payload: Any, field: str, default: Any = None) -> Any:
        if payload is None:
            return default
        if isinstance(payload, dict):
            return payload.get(field, default)
        if hasattr(payload, field):
            return getattr(payload, field)
        return default

    def _collect_text_from_modern_stream(self, stream: Any) -> tuple[str, int, float | None]:
        parts: list[str] = []
        events = 0
        first_token_s: float | None = None
        started = time.perf_counter()

        for chunk in stream:
            events += 1
            choices = self._get_field(chunk, "choices", []) or []
            if not choices:
                continue
            delta = self._get_field(choices[0], "delta")
            content = self._get_field(delta, "content")
            if isinstance(content, str) and content:
                if first_token_s is None:
                    first_token_s = time.perf_counter() - started
                parts.append(content)
            elif isinstance(content, list):
                text_items: list[str] = []
                for item in content:
                    text = self._get_field(item, "text")
                    if isinstance(text, str):
                        text_items.append(text)
                if text_items and first_token_s is None:
                    first_token_s = time.perf_counter() - started
                parts.extend(text_items)

        return "".join(parts), events, first_token_s

    def _collect_text_from_legacy_stream(self, stream: Any) -> tuple[str, int, float | None]:
        parts: list[str] = []
        events = 0
        first_token_s: float | None = None
        started = time.perf_counter()

        for chunk in stream:
            events += 1
            choices = self._get_field(chunk, "choices", []) or []
            if not choices:
                continue
            delta = self._get_field(choices[0], "delta")
            content = self._get_field(delta, "content")
            if isinstance(content, str) and content:
                if first_token_s is None:
                    first_token_s = time.perf_counter() - started
                parts.append(content)

        return "".join(parts), events, first_token_s

    def _extract_content_from_non_stream_response(self, completion: Any) -> str:
        choices = self._get_field(completion, "choices", []) or []
        if not choices:
            return ""

        message = self._get_field(choices[0], "message")
        content = self._get_field(message, "content")

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_items: list[str] = []
            for item in content:
                text = self._get_field(item, "text")
                if isinstance(text, str):
                    text_items.append(text)
            return "".join(text_items)
        return ""

    def _request_completion_text(
        self,
        body: dict[str, Any],
        chunk_index: int,
        total_chunks: int,
        page_numbers: list[int],
        fallback: bool,
    ) -> str:
        request_label = "fallback" if fallback else "primary"
        started = time.perf_counter()

        if self._use_modern_client:
            if self.settings.stream:
                stream = self.client.chat.completions.create(**body, stream=True)
                content, events, first_token_s = self._collect_text_from_modern_stream(stream)
                elapsed_s = time.perf_counter() - started
                logger.info(
                    "LLM stream completed mode=%s chunk=%d/%d pages=%s events=%d first_token_s=%s elapsed_s=%.2f",
                    request_label,
                    chunk_index,
                    total_chunks,
                    page_numbers,
                    events,
                    f"{first_token_s:.2f}" if first_token_s is not None else "none",
                    elapsed_s,
                )
                return content

            completion = self.client.chat.completions.create(**body, stream=False)
            elapsed_s = time.perf_counter() - started
            logger.info(
                "LLM response completed mode=%s chunk=%d/%d pages=%s elapsed_s=%.2f",
                request_label,
                chunk_index,
                total_chunks,
                page_numbers,
                elapsed_s,
            )
            return self._extract_content_from_non_stream_response(completion)

        request_payload = dict(body)
        request_payload["stream"] = self.settings.stream
        request_payload["request_timeout"] = self.settings.request_timeout_s

        if self.settings.stream:
            stream = openai_legacy.ChatCompletion.create(**request_payload)
            content, events, first_token_s = self._collect_text_from_legacy_stream(stream)
            elapsed_s = time.perf_counter() - started
            logger.info(
                "LLM stream completed mode=%s chunk=%d/%d pages=%s events=%d first_token_s=%s elapsed_s=%.2f",
                request_label,
                chunk_index,
                total_chunks,
                page_numbers,
                events,
                f"{first_token_s:.2f}" if first_token_s is not None else "none",
                elapsed_s,
            )
            return content

        completion = openai_legacy.ChatCompletion.create(**request_payload)
        elapsed_s = time.perf_counter() - started
        logger.info(
            "LLM response completed mode=%s chunk=%d/%d pages=%s elapsed_s=%.2f",
            request_label,
            chunk_index,
            total_chunks,
            page_numbers,
            elapsed_s,
        )
        return self._extract_content_from_non_stream_response(completion)

    def extract_chunk(self, page_payload: list[dict], chunk_index: int, total_chunks: int) -> dict:
        page_numbers = [int(page.get("page_number", -1)) for page in page_payload]
        logger.info(
            "LLM request started chunk=%d/%d pages=%s endpoint=%s timeout_s=%d model=%s stream=%s",
            chunk_index,
            total_chunks,
            page_numbers,
            self.chat_endpoint,
            self.settings.request_timeout_s,
            self.settings.model,
            self.settings.stream,
        )

        body = self._build_request_body(page_payload=page_payload, include_response_format=True)
        try:
            content = self._request_completion_text(
                body=body,
                chunk_index=chunk_index,
                total_chunks=total_chunks,
                page_numbers=page_numbers,
                fallback=False,
            )
        except Exception as exc:
            if self._is_timeout_error(exc):
                logger.error(
                    "LLM request timeout chunk=%d/%d pages=%s timeout_s=%d error=%s",
                    chunk_index,
                    total_chunks,
                    page_numbers,
                    self.settings.request_timeout_s,
                    exc,
                )
                raise TimeoutError(
                    f"LLM request timed out for chunk {chunk_index}/{total_chunks} after "
                    f"{self.settings.request_timeout_s}s (pages={page_numbers})"
                ) from exc

            if self._is_response_format_error(exc):
                logger.warning(
                    "LLM response_format unsupported chunk=%d/%d; retrying without response_format",
                    chunk_index,
                    total_chunks,
                )
                fallback_body = self._build_request_body(
                    page_payload=page_payload,
                    include_response_format=False,
                )
                try:
                    content = self._request_completion_text(
                        body=fallback_body,
                        chunk_index=chunk_index,
                        total_chunks=total_chunks,
                        page_numbers=page_numbers,
                        fallback=True,
                    )
                except Exception as fallback_exc:
                    if self._is_timeout_error(fallback_exc):
                        logger.error(
                            "LLM fallback timeout chunk=%d/%d pages=%s timeout_s=%d error=%s",
                            chunk_index,
                            total_chunks,
                            page_numbers,
                            self.settings.request_timeout_s,
                            fallback_exc,
                        )
                        raise TimeoutError(
                            f"LLM fallback request timed out for chunk {chunk_index}/{total_chunks} after "
                            f"{self.settings.request_timeout_s}s (pages={page_numbers})"
                        ) from fallback_exc
                    logger.exception(
                        "LLM fallback request failed chunk=%d/%d pages=%s",
                        chunk_index,
                        total_chunks,
                        page_numbers,
                    )
                    raise RuntimeError(
                        f"LLM fallback request failed for chunk {chunk_index}/{total_chunks} "
                        f"(pages={page_numbers}): {fallback_exc}"
                    ) from fallback_exc
            else:
                logger.exception(
                    "LLM request failed chunk=%d/%d pages=%s",
                    chunk_index,
                    total_chunks,
                    page_numbers,
                )
                raise RuntimeError(
                    f"LLM request failed for chunk {chunk_index}/{total_chunks} "
                    f"(pages={page_numbers}): {exc}"
                ) from exc

        try:
            parsed = extract_json_object(content)
        except Exception as exc:
            logger.error(
                "LLM parse error chunk=%d/%d content_preview=%s",
                chunk_index,
                total_chunks,
                str(content)[:500],
            )
            raise RuntimeError(
                f"LLM returned non-JSON content for chunk {chunk_index}/{total_chunks}"
            ) from exc

        normalized = normalize_chunk_result(parsed)
        logger.info(
            "LLM parse success chunk=%d/%d records=%d us_rows=%d cash_rows=%d",
            chunk_index,
            total_chunks,
            len(normalized["records"]),
            len(normalized["us_securities_settlement"]),
            len(normalized["cash_settlement"]),
        )
        return normalized
