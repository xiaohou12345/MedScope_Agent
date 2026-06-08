from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.model_client import ApiRouteLog
from scripts.no_mask_vision_prompt_demo import _load_dotenv_local
from scripts.xray_mask_mock_eval import DEFAULT_EXPORT_DIR, OnfhCocoMockVisualRunner


DEFAULT_OUTPUT_DIR = Path("output/fake/vision_model_route_debug")


def default_image_path() -> Path:
    return Path(OnfhCocoMockVisualRunner(DEFAULT_EXPORT_DIR).runnable_xray_rows()[0].absolute_path)


def run_debug(*, image_path: Path, output_dir: Path, models: list[str] | None = None) -> dict[str, Any]:
    _load_dotenv_local()
    route_log = ApiRouteLog.from_file()
    output_dir.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get(route_log.api_key_env_for_active_route())
    if not api_key:
        raise RuntimeError(f"missing {route_log.api_key_env_for_active_route()}")
    model_candidates = models or _model_candidates(route_log)
    image_data_url = _image_data_url(image_path)
    tests = []
    for model in model_candidates:
        tests.extend(
            [
                _responses_text_payload(model),
                _responses_text_payload(model, structured=True),
                _responses_image_payload(model, image_data_url),
                _responses_image_payload(model, image_data_url, structured=True),
                _chat_text_payload(model),
                _chat_image_payload(model, image_data_url),
            ]
        )

    results = []
    for index, spec in enumerate(tests, start=1):
        print(f"[{index}/{len(tests)}] {spec['name']} model={spec['model']}", flush=True)
        started_at = time.time()
        result = _post_json(
            url=spec["url"],
            payload=spec["payload"],
            api_key=api_key,
            timeout=90,
        )
        result.update(
            {
                "name": spec["name"],
                "model": spec["model"],
                "endpoint": spec["endpoint"],
                "duration_ms": int(round((time.time() - started_at) * 1000)),
                "request_payload_summary": _sanitize_payload(spec["payload"]),
                "extracted_text": _extract_text(result.get("json")),
                "raw_text_preview": (result.get("raw_text") or "")[:2000],
            }
        )
        results.append(result)

    summary = {
        "status": "ok",
        "active_route": route_log.active_route,
        "base_url": route_log.base_url_for_active_route(),
        "configured_chat_model": route_log.model_for_active_route(),
        "configured_vision_model": route_log.vision_model_for_active_route(),
        "configured_endpoint": route_log.api_endpoint_for_active_route(),
        "image_path": str(image_path),
        "models_tested": model_candidates,
        "results": results,
        "summary_table": [
            {
                "name": item["name"],
                "model": item["model"],
                "endpoint": item["endpoint"],
                "http_status": item.get("http_status"),
                "error": item.get("error"),
                "json_status": (item.get("json") or {}).get("status") if isinstance(item.get("json"), dict) else None,
                "text_len": len(item.get("extracted_text") or ""),
                "text_preview": (item.get("extracted_text") or "")[:200],
                "duration_ms": item.get("duration_ms"),
            }
            for item in results
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "summary_table.json").write_text(
        json.dumps(summary["summary_table"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _model_candidates(route_log: ApiRouteLog) -> list[str]:
    seen = []
    for model in [
        route_log.vision_model_for_active_route(),
        route_log.model_for_active_route(),
        "gpt-5.5",
        "gpt-5.4-mini",
        "gpt-5.4",
        "gpt-5.2",
        "gpt-5.1",
        "gpt-5",
        "gpt-5.5-share2",
    ]:
        if model and model not in seen:
            seen.append(model)
    return seen


def _base_url() -> str:
    return ApiRouteLog.from_file().base_url_for_active_route().rstrip("/")


def _responses_url() -> str:
    base_url = _base_url()
    if base_url.endswith("/responses"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/responses"
    return f"{base_url}/v1/responses"


def _chat_url() -> str:
    base_url = _base_url()
    if base_url.endswith("/chat/completions"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/chat/completions"
    return f"{base_url}/v1/chat/completions"


def _responses_text_payload(model: str, *, structured: bool = False) -> dict[str, Any]:
    payload = {
        "name": "responses_text_structured" if structured else "responses_text",
        "endpoint": "responses",
        "model": model,
        "url": _responses_url(),
        "payload": {
            "model": model,
            "input": "Return JSON only: {\"ok\": true, \"message\": \"pong\"}",
            "store": False,
            "stream": False,
            "reasoning": {"effort": "low"},
            "max_output_tokens": 256,
        },
    }
    if structured:
        payload["payload"]["text"] = {"format": {"type": "json_object"}, "verbosity": "low"}
    return payload


def _responses_image_payload(model: str, image_data_url: str, *, structured: bool = False) -> dict[str, Any]:
    payload = {
        "name": "responses_image_structured" if structured else "responses_image",
        "endpoint": "responses",
        "model": model,
        "url": _responses_url(),
        "payload": {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Look at this medical image and return JSON only: "
                                "{\"ok\": true, \"modality\": \"xray_or_unknown\", \"visible\": true}"
                            ),
                        },
                        {"type": "input_image", "image_url": image_data_url},
                    ],
                }
            ],
            "store": False,
            "stream": False,
            "reasoning": {"effort": "low"},
            "max_output_tokens": 256,
        },
    }
    if structured:
        payload["payload"]["text"] = {"format": {"type": "json_object"}, "verbosity": "low"}
    return payload


def _chat_text_payload(model: str) -> dict[str, Any]:
    return {
        "name": "chat_text",
        "endpoint": "chat_completions",
        "model": model,
        "url": _chat_url(),
        "payload": {
            "model": model,
            "messages": [{"role": "user", "content": "Return JSON only: {\"ok\": true, \"message\": \"pong\"}"}],
            "temperature": 0,
            "stream": False,
            "max_tokens": 256,
        },
    }


def _chat_image_payload(model: str, image_data_url: str) -> dict[str, Any]:
    return {
        "name": "chat_image",
        "endpoint": "chat_completions",
        "model": model,
        "url": _chat_url(),
        "payload": {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Look at this medical image and return JSON only: "
                                "{\"ok\": true, \"modality\": \"xray_or_unknown\", \"visible\": true}"
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }
            ],
            "temperature": 0,
            "stream": False,
            "max_tokens": 256,
        },
    }


def _post_json(*, url: str, payload: dict[str, Any], api_key: str, timeout: int) -> dict[str, Any]:
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw_text = response.read().decode("utf-8", "replace")
            return {
                "http_status": response.status,
                "raw_text": raw_text,
                "json": _loads_json_or_none(raw_text),
            }
    except error.HTTPError as exc:
        raw_text = exc.read().decode("utf-8", "replace")
        return {
            "http_status": exc.code,
            "error": f"HTTPError: {exc.code}",
            "raw_text": raw_text,
            "json": _loads_json_or_none(raw_text),
        }
    except Exception as exc:
        return {
            "http_status": None,
            "error": f"{exc.__class__.__name__}: {exc}",
            "raw_text": "",
            "json": None,
        }


def _loads_json_or_none(raw_text: str) -> Any:
    try:
        return json.loads(raw_text)
    except Exception:
        return None


def _extract_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    texts = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                texts.append(content["text"])
    if texts:
        return "\n".join(texts)
    choices = payload.get("choices") or []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            texts.append(content)
        delta = choice.get("delta") or {}
        if isinstance(delta.get("content"), str):
            texts.append(delta["content"])
    return "\n".join(texts)


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False)
    if ";base64," not in text:
        return payload
    return json.loads(_replace_data_urls(text))


def _replace_data_urls(text: str) -> str:
    marker = "data:"
    result = []
    index = 0
    while True:
        start = text.find(marker, index)
        if start < 0:
            result.append(text[index:])
            break
        b64_marker = ";base64,"
        b64_start = text.find(b64_marker, start)
        if b64_start < 0:
            result.append(text[index:])
            break
        end = text.find('"', b64_start)
        if end < 0:
            result.append(text[index:])
            break
        result.append(text[index:start])
        mime_type = text[start + len(marker):b64_start]
        b64_len = end - (b64_start + len(b64_marker))
        result.append(f"data:{mime_type};base64,<omitted {b64_len} chars>")
        index = end
    return "".join(result)


def _image_data_url(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug active vision model route with text and image calls.")
    parser.add_argument("--image", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--models", nargs="*", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_path = args.image or default_image_path()
    summary = run_debug(image_path=image_path, output_dir=args.output_dir, models=args.models)
    print(json.dumps(summary["summary_table"], ensure_ascii=False, indent=2))
    print(f"saved: {args.output_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
