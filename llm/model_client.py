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
        env_overrides = {
            "active_route": os.environ.get("MEDSCOPE_ACTIVE_ROUTE"),
            "dmx_model": os.environ.get("DMX_MODEL"),
            "ky_model": os.environ.get("KY_MODEL"),
            "dmx_vision_model": os.environ.get("DMX_VISION_MODEL"),
            "ky_vision_model": os.environ.get("KY_VISION_MODEL"),
            "dmx_base_url": os.environ.get("DMX_BASE_URL"),
            "ky_base_url": os.environ.get("KY_BASE_URL"),
        }
        route_data.update(
            {
                key: value
                for key, value in env_overrides.items()
                if value is not None and value.strip()
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

    def chat(self, messages: list[dict[str, str]], task: str) -> ChatResponse:
        api_key_env = self.route_log.api_key_env_for_active_route()
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Missing {api_key_env}; run API connectivity test before real model calls."
            )

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


class RecordingModelClient:
    """Deterministic test client that records calls and never touches network."""

    def __init__(self, response: ChatResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, str]], task: str) -> ChatResponse:
        self.calls.append({"messages": messages, "task": task})
        return self.response
