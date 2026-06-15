from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib import request

from llm.response_stream import parse_openai_compatible_sse_response


@dataclass(frozen=True)
class ChatResponse:
    content: str
    model: str
    route: str
    raw: dict[str, Any] | None = None


class ModelClient(Protocol):
    def chat(self, messages: list[dict[str, str]], task: str) -> ChatResponse:
        """Send chat messages to the configured model route."""


@dataclass(frozen=True)
class ApiRouteLog:
    active_route: str
    dmx_model: str = "dmx-medical-chat"
    ky_model: str = "ky-self-hosted-medical"
    dmx_vision_model: str | None = None
    ky_vision_model: str | None = None
    dmx_base_url: str = "https://api.dmx.local/v1/chat/completions"
    ky_base_url: str = "http://127.0.0.1:8000/v1/chat/completions"
    dmx_api_endpoint: str = "chat_completions"
    ky_api_endpoint: str = "chat_completions"
    dmx_user_agent: str = "MedScope-Agent/0.1"
    ky_user_agent: str = "MedScope-Agent/0.1"

    @classmethod
    def from_file(cls, path: Path | str = "docs/API_ROUTE_LOG.md") -> "ApiRouteLog":
        route_data: dict[str, str] = {}
        log_path = Path(path)
        if log_path.exists():
            for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                route_data[key.strip()] = value.strip()
        return cls(
            active_route=os.environ.get(
                "MEDSCOPE_ACTIVE_ROUTE", route_data.get("active_route", "dmx")
            ),
            dmx_model=os.environ.get("DMX_MODEL", route_data.get("dmx_model", cls.dmx_model)),
            ky_model=os.environ.get("KY_MODEL", route_data.get("ky_model", cls.ky_model)),
            dmx_vision_model=os.environ.get("DMX_VISION_MODEL", route_data.get("dmx_vision_model") or None),
            ky_vision_model=os.environ.get("KY_VISION_MODEL", route_data.get("ky_vision_model") or None),
            dmx_base_url=os.environ.get("DMX_BASE_URL", route_data.get("dmx_base_url", cls.dmx_base_url)),
            ky_base_url=os.environ.get("KY_BASE_URL", route_data.get("ky_base_url", cls.ky_base_url)),
            dmx_api_endpoint=os.environ.get(
                "DMX_API_ENDPOINT",
                route_data.get("dmx_api_endpoint", cls.dmx_api_endpoint),
            ),
            ky_api_endpoint=os.environ.get(
                "KY_API_ENDPOINT",
                route_data.get("ky_api_endpoint", cls.ky_api_endpoint),
            ),
            dmx_user_agent=os.environ.get(
                "DMX_USER_AGENT",
                route_data.get("dmx_user_agent", cls.dmx_user_agent),
            ),
            ky_user_agent=os.environ.get(
                "KY_USER_AGENT",
                route_data.get("ky_user_agent", cls.ky_user_agent),
            ),
        )

    def model_for_active_route(self) -> str:
        if self.active_route == "ky":
            return self.ky_model
        return self.dmx_model

    def vision_model_for_active_route(self) -> str:
        if self.active_route == "ky":
            return self.ky_vision_model or self.ky_model
        return self.dmx_vision_model or self.dmx_model

    def base_url_for_active_route(self) -> str:
        if self.active_route == "ky":
            return self.ky_base_url
        return self.dmx_base_url

    def api_endpoint_for_active_route(self) -> str:
        if self.active_route == "ky":
            return self.ky_api_endpoint
        return self.dmx_api_endpoint

    def user_agent_for_active_route(self) -> str:
        if self.active_route == "ky":
            return self.ky_user_agent
        return self.dmx_user_agent

    def api_key_env_for_active_route(self) -> str:
        if self.active_route == "ky":
            return "KY_API_KEY"
        return "DMX_API_KEY"


class OpenAICompatibleModelClient:
    """Minimal OpenAI-compatible client used by DMX or self-hosted KY routes."""

    def __init__(
        self,
        route_log: ApiRouteLog | None = None,
        timeout_seconds: int = 60,
        responses_stream: bool | None = None,
    ) -> None:
        self.route_log = route_log or ApiRouteLog.from_file()
        self.timeout_seconds = timeout_seconds
        self.responses_stream = (
            _env_flag("MEDSCOPE_RESPONSES_STREAM", default=True)
            if responses_stream is None
            else responses_stream
        )

    def chat_completions_url(self) -> str:
        base_url = self.route_log.base_url_for_active_route().rstrip("/")
        if base_url.endswith("/v1/chat/completions"):
            return base_url
        if base_url.endswith("/chat/completions"):
            return base_url
        if base_url.endswith("/v1"):
            return f"{base_url}/chat/completions"
        return f"{base_url}/v1/chat/completions"

    def responses_url(self) -> str:
        base_url = self.route_log.base_url_for_active_route().rstrip("/")
        if base_url.endswith("/v1/responses"):
            return base_url
        if base_url.endswith("/responses"):
            return base_url
        if base_url.endswith("/v1"):
            return f"{base_url}/responses"
        return f"{base_url}/v1/responses"

    def chat(self, messages: list[dict[str, str]], task: str) -> ChatResponse:
        api_key_env = self.route_log.api_key_env_for_active_route()
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Missing {api_key_env}; run API connectivity test before real model calls."
            )

        if self.route_log.api_endpoint_for_active_route() == "responses":
            return self._responses_chat(messages=messages, task=task, api_key=api_key)
        return self._chat_completions_chat(messages=messages, task=task, api_key=api_key)

    def _chat_completions_chat(
        self,
        *,
        messages: list[dict[str, str]],
        task: str,
        api_key: str,
    ) -> ChatResponse:
        payload = {
            "model": self.route_log.model_for_active_route(),
            "messages": messages,
            "metadata": {"task": task},
        }
        req = request.Request(
            self.chat_completions_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": self.route_log.user_agent_for_active_route(),
            },
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
        content = raw["choices"][0]["message"]["content"]
        return ChatResponse(
            content=content,
            model=self.route_log.model_for_active_route(),
            route=self.route_log.active_route,
            raw=raw,
        )

    def _responses_chat(
        self,
        *,
        messages: list[dict[str, str]],
        task: str,
        api_key: str,
    ) -> ChatResponse:
        payload = {
            "model": self.route_log.model_for_active_route(),
            "input": _responses_input_from_messages(messages),
            "store": False,
            "metadata": {"task": task},
        }
        instructions = _responses_instructions_from_messages(messages)
        if instructions:
            payload["instructions"] = instructions
        if self.responses_stream:
            payload["stream"] = True
        req = request.Request(
            self.responses_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if self.responses_stream else "application/json",
                "User-Agent": self.route_log.user_agent_for_active_route(),
            },
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            if self.responses_stream:
                content, raw = parse_openai_compatible_sse_response(response)
            else:
                raw = json.loads(response.read().decode("utf-8"))
                content = _content_from_responses_payload(raw)
        return ChatResponse(
            content=content,
            model=self.route_log.model_for_active_route(),
            route=self.route_log.active_route,
            raw=raw,
        )


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _responses_instructions_from_messages(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(
        str(message.get("content") or "")
        for message in messages
        if message.get("role") == "system" and message.get("content")
    )


def _responses_input_from_messages(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        if role == "system":
            continue
        content = message.get("content") or ""
        items.append(
            {
                "role": role if role in {"user", "assistant"} else "user",
                "content": [{"type": "input_text", "text": str(content)}],
            }
        )
    return items or [{"role": "user", "content": [{"type": "input_text", "text": ""}]}]


def _content_from_responses_payload(raw: dict[str, Any]) -> str:
    if isinstance(raw.get("output_text"), str):
        return raw["output_text"]
    texts: list[str] = []
    for item in raw.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                texts.append(content["text"])
    return "\n".join(texts)


class RecordingModelClient:
    """Deterministic test client that records calls and never touches network."""

    def __init__(self, response: ChatResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, str]], task: str) -> ChatResponse:
        self.calls.append({"messages": messages, "task": task})
        return self.response
