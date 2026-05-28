from __future__ import annotations

import json
from typing import Any

from llm.model_client import ModelClient


class PromptRunner:
    """Thin wrapper so agents depend on prompts, not provider-specific APIs."""

    def __init__(self, model_client: ModelClient) -> None:
        self.model_client = model_client

    def run(self, task: str, system_prompt: str, user_payload: dict[str, Any]) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
            },
        ]
        return self.model_client.chat(messages=messages, task=task).content
