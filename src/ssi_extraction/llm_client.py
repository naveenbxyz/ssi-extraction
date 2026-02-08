from __future__ import annotations

import requests

from .models import LLMSettings
from .parser import extract_json_object, normalize_chunk_result
from .prompts import SYSTEM_PROMPT, build_user_prompt


class LocalOpenAICompatibleClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    @property
    def endpoint(self) -> str:
        return self.settings.base_url.rstrip("/") + "/v1/chat/completions"

    def extract_chunk(self, page_payload: list[dict]) -> dict:
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

        response = requests.post(self.endpoint, json=body, timeout=self.settings.request_timeout_s)
        if response.status_code >= 400 and "response_format" in response.text:
            fallback_body = dict(body)
            fallback_body.pop("response_format", None)
            response = requests.post(
                self.endpoint,
                json=fallback_body,
                timeout=self.settings.request_timeout_s,
            )
        response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        parsed = extract_json_object(content)
        return normalize_chunk_result(parsed)
