from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib import request


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
        route_data.update(
            {
                key: value
                for key, value in {
                    "active_route": os.environ.get("MEDSCOPE_ACTIVE_ROUTE"),
                    "dmx_model": os.environ.get("DMX_MODEL"),
                    "ky_model": os.environ.get("KY_MODEL"),
                    "dmx_vision_model": os.environ.get("DMX_VISION_MODEL"),
                    "ky_vision_model": os.environ.get("KY_VISION_MODEL"),
                    "dmx_base_url": os.environ.get("DMX_BASE_URL"),
                    "ky_base_url": os.environ.get("KY_BASE_URL"),
                    "dmx_api_endpoint": os.environ.get("DMX_API_ENDPOINT"),
                    "ky_api_endpoint": os.environ.get("KY_API_ENDPOINT"),
                    "dmx_user_agent": os.environ.get("DMX_USER_AGENT"),
                    "ky_user_agent": os.environ.get("KY_USER_AGENT"),
                }.items()
                if value
            }
        )
        return cls(
            active_route=route_data.get("active_route", "dmx"),
            dmx_model=route_data.get("dmx_model", cls.dmx_model),
            ky_model=route_data.get("ky_model", cls.ky_model),
            dmx_vision_model=route_data.get("dmx_vision_model") or None,
            ky_vision_model=route_data.get("ky_vision_model") or None,
            dmx_base_url=route_data.get("dmx_base_url", cls.dmx_base_url),
            ky_base_url=route_data.get("ky_base_url", cls.ky_base_url),
            dmx_api_endpoint=route_data.get("dmx_api_endpoint", cls.dmx_api_endpoint),
            ky_api_endpoint=route_data.get("ky_api_endpoint", cls.ky_api_endpoint),
            dmx_user_agent=route_data.get("dmx_user_agent", cls.dmx_user_agent),
            ky_user_agent=route_data.get("ky_user_agent", cls.ky_user_agent),
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

    def __init__(self, route_log: ApiRouteLog | None = None, timeout_seconds: int = 60) -> None:
        self.route_log = route_log or ApiRouteLog.from_file()
        self.timeout_seconds = timeout_seconds

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
            return self._chat_with_responses_api(
                messages=messages,
                task=task,
                api_key=api_key,
            )
        return self._chat_with_chat_completions_api(
            messages=messages,
            task=task,
            api_key=api_key,
        )

    def _chat_with_chat_completions_api(
        self,
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

    def _chat_with_responses_api(
        self,
        messages: list[dict[str, str]],
        task: str,
        api_key: str,
    ) -> ChatResponse:
        payload = {
            "model": self.route_log.model_for_active_route(),
            "input": self._responses_input_from_messages(messages),
            "store": False,
            "stream": False,
        }
        req = request.Request(
            self.responses_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": self.route_log.user_agent_for_active_route(),
            },
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
        return ChatResponse(
            content=self._content_from_responses_api(raw),
            model=self.route_log.model_for_active_route(),
            route=self.route_log.active_route,
            raw=raw,
        )

    def _responses_input_from_messages(self, messages: list[dict[str, str]]) -> str:
        lines: list[str] = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    def _content_from_responses_api(self, raw: dict[str, Any]) -> str:
        output_text = raw.get("output_text")
        if isinstance(output_text, str):
            return output_text
        texts: list[str] = []
        for item in raw.get("output") or []:
            for content in item.get("content") or []:
                text = content.get("text")
                if isinstance(text, str):
                    texts.append(text)
        if texts:
            return "\n".join(texts)
        raise ValueError("Responses API payload did not contain output text")


class RecordingModelClient:
    """Deterministic test client that records calls and never touches network."""

    def __init__(self, response: ChatResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, str]], task: str) -> ChatResponse:
        self.calls.append({"messages": messages, "task": task})
        return self.response
