from __future__ import annotations

import json
from typing import Any

from .llm_client import LocalOpenAICompatibleClient
from .models import LLMSettings

JSON_CHAT_SYSTEM_PROMPT = """
You are a data assistant for Securities Settlement Instructions (SSI).
Answer using only the provided extraction JSON context.
If answer is not present in context, say that explicitly.
When useful, format results as a markdown table.
Be concise and accurate.
""".strip()


def _build_user_prompt(question: str, extraction_payload: dict[str, Any]) -> str:
    context_json = json.dumps(extraction_payload, ensure_ascii=True)
    return (
        "Question:\n"
        f"{question}\n\n"
        "Extraction JSON context:\n"
        f"{context_json}"
    )


def answer_question_from_json(
    settings: LLMSettings,
    extraction_payload: dict[str, Any],
    question: str,
    system_prompt: str | None = None,
    task_label: str = "json_chat",
) -> str:
    client = LocalOpenAICompatibleClient(settings)
    try:
        client.log_connectivity()
        return client.ask_text(
            system_prompt=system_prompt or JSON_CHAT_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(question=question, extraction_payload=extraction_payload),
            task_label=task_label,
        )
    finally:
        client.close()
