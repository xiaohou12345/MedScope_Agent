from __future__ import annotations

import json
from typing import Any, BinaryIO


def parse_openai_compatible_sse_response(response: BinaryIO) -> tuple[str, dict[str, Any]]:
    """Parse OpenAI-compatible SSE chunks and return assembled text plus raw events.

    Some local gateways return an empty non-streaming Responses payload but emit
    valid `response.output_text.delta` events when `stream=true`.
    """
    event_name = ""
    events: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for raw_line in _iter_response_lines(response):
        line = raw_line.decode("utf-8", "replace").strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                events.append({"event": "raw_json_parse_error", "raw_data": line})
                continue
            events.append({"event": str(payload.get("type") or payload.get("object") or "json"), "data": payload})
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
            continue
        if not line.startswith("data:"):
            continue
        data = line.split(":", 1)[1].strip()
        if data == "[DONE]":
            events.append({"event": event_name or "done", "data": "[DONE]"})
            break
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            events.append({"event": event_name or "unknown", "raw_data": data})
            continue
        event_type = str(payload.get("type") or event_name or payload.get("object") or "")
        events.append({"event": event_name or event_type, "data": payload})
        delta = _text_delta_from_stream_payload(payload)
        if delta:
            text_parts.append(delta)

    content = "".join(text_parts)
    if not content:
        content = _final_text_from_events(events)
    return content, {
        "stream": True,
        "event_count": len(events),
        "events": events,
    }


def _iter_response_lines(response: BinaryIO) -> list[bytes] | BinaryIO:
    try:
        iter(response)
        return response
    except TypeError:
        payload = response.read()
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        return payload.splitlines()


def _text_delta_from_stream_payload(payload: dict[str, Any]) -> str:
    event_type = payload.get("type")
    if event_type == "response.output_text.delta" and isinstance(payload.get("delta"), str):
        return payload["delta"]
    if event_type == "response.refusal.delta" and isinstance(payload.get("delta"), str):
        return payload["delta"]
    choices = payload.get("choices") or []
    parts: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        if isinstance(delta.get("content"), str):
            parts.append(delta["content"])
        message = choice.get("message") or {}
        if isinstance(message.get("content"), str):
            parts.append(message["content"])
    return "".join(parts)


def _final_text_from_events(events: list[dict[str, Any]]) -> str:
    texts: list[str] = []
    for event in events:
        payload = event.get("data")
        if not isinstance(payload, dict):
            continue
        if isinstance(payload.get("output_text"), str):
            texts.append(payload["output_text"])
        response = payload.get("response")
        if isinstance(response, dict) and isinstance(response.get("output_text"), str):
            texts.append(response["output_text"])
        for item in payload.get("output") or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    texts.append(content["text"])
        if isinstance(response, dict):
            for item in response.get("output") or []:
                if not isinstance(item, dict):
                    continue
                for content in item.get("content") or []:
                    if isinstance(content, dict) and isinstance(content.get("text"), str):
                        texts.append(content["text"])
    return "\n".join(texts)
