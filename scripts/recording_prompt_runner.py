from __future__ import annotations

import json
import time
from typing import Any

from llm.model_client import ModelClient


class RecordingPromptRunner:
    """PromptRunner-compatible wrapper that records every model call."""

    def __init__(
        self,
        model_client: ModelClient,
        *,
        max_retries: int = 2,
        retry_sleep_seconds: float = 5.0,
    ) -> None:
        self.model_client = model_client
        self.max_retries = max_retries
        self.retry_sleep_seconds = retry_sleep_seconds
        self.calls: list[dict[str, Any]] = []

    def run(self, task: str, system_prompt: str, user_payload: dict[str, Any]) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
            },
        ]
        started = time.time()
        call_record: dict[str, Any] = {
            "schema_version": "recording_prompt_runner_call.v1",
            "source": "live_prompt_runner",
            "task": task,
            "messages": messages,
            "request_payload": {
                "messages": messages,
                "metadata": {"task": task},
            },
        }
        errors: list[dict[str, Any]] = []
        response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.model_client.chat(messages=messages, task=task)
                break
            except Exception as exc:
                errors.append(
                    {
                        "attempt": attempt + 1,
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                    }
                )
                if attempt >= self.max_retries:
                    call_record.update(
                        {
                            "status": "error",
                            "duration_ms": int(round((time.time() - started) * 1000)),
                            "retry_count": attempt,
                            "errors": errors,
                            "error": str(exc),
                        }
                    )
                    self.calls.append(call_record)
                    raise
                time.sleep(self.retry_sleep_seconds)
        if response is None:
            raise RuntimeError("model client returned no response")
        call_record.update(
            {
                "status": "ok",
                "duration_ms": int(round((time.time() - started) * 1000)),
                "retry_count": len(errors),
                "errors": errors,
                "model": response.model,
                "route": response.route,
                "response_content": response.content,
                "response_raw_summary": _raw_summary(response.raw),
            }
        )
        self.calls.append(call_record)
        return response.content

    def take_new_calls(self, start_index: int) -> list[dict[str, Any]]:
        return list(self.calls[start_index:])


def _raw_summary(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "top_level_keys": sorted(raw.keys()),
        "choice_count": len(raw.get("choices") or []) if isinstance(raw.get("choices"), list) else None,
        "usage": raw.get("usage"),
    }
