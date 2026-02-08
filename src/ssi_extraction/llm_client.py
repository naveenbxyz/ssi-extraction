from __future__ import annotations

import logging
import time

import requests

from .models import LLMSettings
from .parser import extract_json_object, normalize_chunk_result
from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


class LocalOpenAICompatibleClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    @property
    def endpoint(self) -> str:
        return self.settings.base_url.rstrip("/") + "/v1/chat/completions"

    @property
    def models_endpoint(self) -> str:
        return self.settings.base_url.rstrip("/") + "/v1/models"

    def log_connectivity(self) -> None:
        started = time.perf_counter()
        logger.info("LLM preflight started endpoint=%s", self.models_endpoint)
        try:
            response = requests.get(self.models_endpoint, timeout=min(10, self.settings.request_timeout_s))
            elapsed_s = time.perf_counter() - started
            logger.info(
                "LLM preflight completed status=%d elapsed_s=%.2f",
                response.status_code,
                elapsed_s,
            )
        except requests.RequestException as exc:
            elapsed_s = time.perf_counter() - started
            logger.warning(
                "LLM preflight failed elapsed_s=%.2f endpoint=%s error=%s",
                elapsed_s,
                self.models_endpoint,
                exc,
            )

    def extract_chunk(self, page_payload: list[dict], chunk_index: int, total_chunks: int) -> dict:
        page_numbers = [int(page.get("page_number", -1)) for page in page_payload]
        body = {
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(page_payload)},
            ],
            "response_format": {"type": "json_object"},
        }

        logger.info(
            "LLM request started chunk=%d/%d pages=%s endpoint=%s timeout_s=%d model=%s",
            chunk_index,
            total_chunks,
            page_numbers,
            self.endpoint,
            self.settings.request_timeout_s,
            self.settings.model,
        )
        started = time.perf_counter()
        try:
            response = requests.post(
                self.endpoint,
                json=body,
                timeout=self.settings.request_timeout_s,
            )
        except requests.Timeout as exc:
            elapsed_s = time.perf_counter() - started
            logger.error(
                "LLM request timeout chunk=%d/%d pages=%s elapsed_s=%.2f timeout_s=%d error=%s",
                chunk_index,
                total_chunks,
                page_numbers,
                elapsed_s,
                self.settings.request_timeout_s,
                exc,
            )
            raise TimeoutError(
                f"LLM request timed out for chunk {chunk_index}/{total_chunks} after "
                f"{self.settings.request_timeout_s}s (pages={page_numbers})"
            ) from exc
        except requests.RequestException as exc:
            elapsed_s = time.perf_counter() - started
            logger.exception(
                "LLM request failed chunk=%d/%d pages=%s elapsed_s=%.2f",
                chunk_index,
                total_chunks,
                page_numbers,
                elapsed_s,
            )
            raise RuntimeError(
                f"LLM request failed for chunk {chunk_index}/{total_chunks} (pages={page_numbers}): {exc}"
            ) from exc

        elapsed_s = time.perf_counter() - started
        logger.info(
            "LLM response received chunk=%d/%d status=%d elapsed_s=%.2f",
            chunk_index,
            total_chunks,
            response.status_code,
            elapsed_s,
        )
        if response.status_code >= 400 and "response_format" in response.text:
            logger.warning(
                "LLM response_format unsupported chunk=%d/%d; retrying without response_format",
                chunk_index,
                total_chunks,
            )
            fallback_body = dict(body)
            fallback_body.pop("response_format", None)
            fallback_started = time.perf_counter()
            try:
                response = requests.post(
                    self.endpoint,
                    json=fallback_body,
                    timeout=self.settings.request_timeout_s,
                )
            except requests.Timeout as exc:
                fallback_elapsed_s = time.perf_counter() - fallback_started
                logger.error(
                    "LLM fallback timeout chunk=%d/%d pages=%s elapsed_s=%.2f timeout_s=%d error=%s",
                    chunk_index,
                    total_chunks,
                    page_numbers,
                    fallback_elapsed_s,
                    self.settings.request_timeout_s,
                    exc,
                )
                raise TimeoutError(
                    f"LLM fallback request timed out for chunk {chunk_index}/{total_chunks} after "
                    f"{self.settings.request_timeout_s}s (pages={page_numbers})"
                ) from exc
            except requests.RequestException as exc:
                fallback_elapsed_s = time.perf_counter() - fallback_started
                logger.exception(
                    "LLM fallback request failed chunk=%d/%d pages=%s elapsed_s=%.2f",
                    chunk_index,
                    total_chunks,
                    page_numbers,
                    fallback_elapsed_s,
                )
                raise RuntimeError(
                    f"LLM fallback request failed for chunk {chunk_index}/{total_chunks} "
                    f"(pages={page_numbers}): {exc}"
                ) from exc
            fallback_elapsed_s = time.perf_counter() - fallback_started
            logger.info(
                "LLM fallback response received chunk=%d/%d status=%d elapsed_s=%.2f",
                chunk_index,
                total_chunks,
                response.status_code,
                fallback_elapsed_s,
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            logger.error(
                "LLM HTTP error chunk=%d/%d status=%d body=%s",
                chunk_index,
                total_chunks,
                response.status_code,
                response.text[:500],
            )
            raise RuntimeError(
                f"LLM returned HTTP {response.status_code} for chunk {chunk_index}/{total_chunks}"
            ) from exc

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
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
