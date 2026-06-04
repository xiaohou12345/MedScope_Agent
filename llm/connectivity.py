from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from llm.model_client import ModelClient
from llm.model_client import ApiRouteLog


DEFAULT_EXTERNAL_SCRIPT = Path("/Users/4paradigm/Documents/project/cloudgpt_client_example.py")


class ApiConnectivityChecker:
    """Inspects API route readiness and runs explicit smoke calls when requested."""

    def __init__(
        self,
        route_log: ApiRouteLog | None = None,
        external_script_path: Path | str = DEFAULT_EXTERNAL_SCRIPT,
    ) -> None:
        self.route_log = route_log or ApiRouteLog.from_file()
        self.external_script_path = Path(external_script_path)

    def inspect(self) -> dict[str, Any]:
        api_key_env = self.route_log.api_key_env_for_active_route()
        api_key_present = bool(os.environ.get(api_key_env))
        external_script_found = self.external_script_path.exists()
        return {
            "active_route": self.route_log.active_route,
            "model": self.route_log.model_for_active_route(),
            "vision_model": self.route_log.vision_model_for_active_route(),
            "base_url": self.route_log.base_url_for_active_route(),
            "api_key_env": api_key_env,
            "api_key_present": api_key_present,
            "external_script_path": str(self.external_script_path),
            "external_script_found": external_script_found,
            "real_call_ready": api_key_present,
            "real_call_attempted": False,
        }

    def inspect_real_vlm_validation(self) -> dict[str, Any]:
        api_key_env = self.route_log.api_key_env_for_active_route()
        api_key_present = bool(os.environ.get(api_key_env))
        base_url = self.route_log.base_url_for_active_route()
        vision_model = self.route_log.vision_model_for_active_route()
        reasons = []
        if not api_key_present:
            reasons.append("api_key_missing")
        if not base_url:
            reasons.append("base_url_missing")
        if not vision_model:
            reasons.append("vision_model_missing")
        return {
            "status": "ready" if not reasons else "not_ready",
            "workflow": "fhn_real_vlm_validation",
            "active_route": self.route_log.active_route,
            "vision_model": vision_model,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "api_key_present": api_key_present,
            "reasons": reasons,
            "network_call_attempted": False,
            "secret_values_returned": False,
        }

    def run_model_smoke(self, model_client: ModelClient) -> dict[str, Any]:
        response = model_client.chat(
            task="api_smoke_test",
            messages=[
                {
                    "role": "system",
                    "content": "你是 MedScope API 连通性测试助手，只回复 pong。",
                },
                {"role": "user", "content": "ping"},
            ],
        )
        return {
            "active_route": self.route_log.active_route,
            "model": response.model,
            "route": response.route,
            "content": response.content,
            "real_call_attempted": True,
        }
