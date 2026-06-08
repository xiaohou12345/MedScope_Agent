from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.model_client import ApiRouteLog, OpenAICompatibleModelClient
from llm.response_stream import parse_openai_compatible_sse_response
from scripts.no_mask_vision_prompt_demo import _load_dotenv_local
from tools.vision_prompt_generator import OpenAICompatibleVisionClient


DEFAULT_OUTPUT_DIR = Path("output/fake/dmx_route_smoke_test")


def run_smoke_test(
    *,
    env_file: Path,
    output_dir: Path,
    skip_text: bool,
    skip_vision: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    _load_dotenv_local(env_file)
    output_dir.mkdir(parents=True, exist_ok=True)
    route = ApiRouteLog.from_file()
    if route.active_route != "dmx":
        return {
            "status": "skipped",
            "reason": "MEDSCOPE_ACTIVE_ROUTE is not dmx",
            "active_route": route.active_route,
        }
    config = _dmx_config_summary(route)
    results: dict[str, Any] = {
        "status": "ok",
        "active_route": route.active_route,
        "config": config,
        "checks": {},
    }
    if not skip_text:
        results["checks"]["text"] = _check_text(timeout_seconds=timeout_seconds)
    if not skip_vision:
        image_path = output_dir / "dmx_route_vision_test.png"
        _write_test_image(image_path)
        results["checks"]["vision"] = _check_vision(
            image_path=image_path,
            timeout_seconds=timeout_seconds,
        )
    accepted_statuses = {"ok", "ok_with_minimal_fallback"}
    if any(check.get("status") not in accepted_statuses for check in results["checks"].values()):
        results["status"] = "completed_with_failures"
    summary_path = output_dir / "summary.json"
    results["summary_path"] = str(summary_path)
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def _dmx_config_summary(route: ApiRouteLog) -> dict[str, Any]:
    return {
        "DMX_API_KEY_present": bool(os.environ.get("DMX_API_KEY")),
        "DMX_BASE_URL": route.dmx_base_url,
        "DMX_MODEL": route.dmx_model,
        "DMX_VISION_MODEL": route.dmx_vision_model or route.dmx_model,
        "DMX_API_ENDPOINT": route.dmx_api_endpoint,
        "DMX_USER_AGENT": route.dmx_user_agent,
        "MEDSCOPE_RESPONSES_STREAM": os.environ.get("MEDSCOPE_RESPONSES_STREAM"),
        "MEDSCOPE_VISION_RESPONSES_STREAM": os.environ.get("MEDSCOPE_VISION_RESPONSES_STREAM"),
    }


def _check_text(*, timeout_seconds: int) -> dict[str, Any]:
    try:
        client = OpenAICompatibleModelClient(timeout_seconds=timeout_seconds, responses_stream=True)
        response = client.chat(
            messages=[
                {
                    "role": "user",
                    "content": "Reply with exactly: dmx_text_ok",
                }
            ],
            task="dmx_route_text_smoke_test",
        )
        content = response.content.strip()
        return {
            "status": "ok" if "dmx_text_ok" in content else "unexpected_content",
            "model": response.model,
            "route": response.route,
            "content_excerpt": content[:200],
        }
    except Exception as exc:
        return {
            "status": "error",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }


def _check_vision(*, image_path: Path, timeout_seconds: int) -> dict[str, Any]:
    try:
        client = OpenAICompatibleVisionClient(timeout_seconds=timeout_seconds, responses_stream=True)
        content = client.chat_with_image(
            image_path=image_path,
            system_prompt="You are a concise vision smoke-test assistant.",
            user_payload={
                "task": "vision route smoke test",
                "instruction": "Describe the simple test image in one short sentence.",
            },
            task="dmx_route_vision_smoke_test",
        ).strip()
        return {
            "status": "ok" if content else "empty_content",
            "image_path": str(image_path),
            "content_excerpt": content[:300],
        }
    except Exception as exc:
        fallback = _check_vision_minimal_responses(
            image_path=image_path,
            timeout_seconds=timeout_seconds,
        )
        if fallback.get("status") == "ok":
            return {
                "status": "ok_with_minimal_fallback",
                "image_path": str(image_path),
                "primary_client_error_type": exc.__class__.__name__,
                "primary_client_error": str(exc),
                "minimal_responses_fallback": fallback,
            }
        return {
            "status": "error",
            "image_path": str(image_path),
            "error_type": exc.__class__.__name__,
            "error": str(exc),
            "minimal_responses_fallback": fallback,
        }


def _check_vision_minimal_responses(*, image_path: Path, timeout_seconds: int) -> dict[str, Any]:
    route = ApiRouteLog.from_file()
    api_key = os.environ.get(route.api_key_env_for_active_route())
    if not api_key:
        return {"status": "error", "error": f"Missing {route.api_key_env_for_active_route()}"}
    data_url = _image_data_url(image_path)
    payload = {
        "model": route.vision_model_for_active_route(),
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "请用一句话描述这张测试图片。",
                    },
                    {
                        "type": "input_image",
                        "image_url": data_url,
                    },
                ],
            }
        ],
        "stream": True,
        "store": False,
    }
    req = request.Request(
        _responses_url(route),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": route.user_agent_for_active_route(),
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            content, _raw = parse_openai_compatible_sse_response(response)
        return {
            "status": "ok" if content else "empty_content",
            "content_excerpt": content[:300],
        }
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "status": "error",
            "error_type": exc.__class__.__name__,
            "http_status": exc.code,
            "error": str(exc),
            "response_body_excerpt": body[:1000],
        }
    except Exception as exc:
        return {
            "status": "error",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }


def _responses_url(route: ApiRouteLog) -> str:
    base_url = route.base_url_for_active_route().rstrip("/")
    if base_url.endswith("/v1/responses"):
        return base_url
    if base_url.endswith("/responses"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/responses"
    return f"{base_url}/v1/responses"


def _image_data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _write_test_image(path: Path) -> None:
    image = Image.new("RGB", (160, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 25, 90, 95), outline=(220, 40, 40), width=4)
    draw.ellipse((105, 35, 145, 75), fill=(40, 120, 220))
    draw.text((24, 100), "DMX", fill=(0, 0, 0))
    image.save(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test the DMX API route configured by .env.local."
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env.local"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-text", action="store_true")
    parser.add_argument("--skip-vision", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_smoke_test(
        env_file=args.env_file,
        output_dir=args.output_dir,
        skip_text=args.skip_text,
        skip_vision=args.skip_vision,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
