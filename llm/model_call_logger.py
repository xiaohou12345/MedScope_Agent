from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LOG_DIR = Path("output/fake/model_call_logs")
_LOCK = threading.Lock()


def new_call_id() -> str:
    return f"llmcall_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}"


def log_model_call(record: dict[str, Any], *, log_dir: Path | str | None = None) -> dict[str, Any]:
    """Append one model-call audit record to JSONL and task-specific JSON files."""
    if os.environ.get("MEDSCOPE_DISABLE_MODEL_CALL_LOG", "").lower() in {"1", "true", "yes"}:
        return record

    output_dir = Path(log_dir or os.environ.get("MEDSCOPE_MODEL_CALL_LOG_DIR") or DEFAULT_LOG_DIR)
    record = dict(record)
    record.setdefault("schema_version", "model_call_log.v1")
    record.setdefault("logged_at", _utc_now())
    record = sanitize_for_model_log(record)

    task = _safe_filename(str(record.get("task") or "unknown_task"))
    call_id = _safe_filename(str(record.get("call_id") or new_call_id()))
    with _LOCK:
        output_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = output_dir / "model_calls.jsonl"
        with jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        (output_dir / f"{task}_{call_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return record


def sanitize_for_model_log(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if _is_secret_key(str(key)):
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = sanitize_for_model_log(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_model_log(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_model_log(item) for item in value]
    if isinstance(value, str):
        if value.startswith("data:") and ";base64," in value:
            return _summarize_data_url(value)
        return value
    return value


def _summarize_data_url(value: str) -> dict[str, Any]:
    header, encoded = value.split(";base64,", 1)
    mime_type = header.removeprefix("data:")
    byte_length = None
    sha256 = None
    try:
        raw = base64.b64decode(encoded, validate=False)
        byte_length = len(raw)
        sha256 = hashlib.sha256(raw).hexdigest()
    except Exception:
        byte_length = int(len(encoded) * 0.75)
    return {
        "type": "data_url_omitted",
        "mime_type": mime_type,
        "base64_chars": len(encoded),
        "byte_length": byte_length,
        "sha256": sha256,
        "reason": "base64 image payload omitted from model call log",
    }


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("api_key", "apikey", "authorization", "bearer", "secret", "token"))


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)
    return cleaned.strip("._") or "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_ms(started_at: float) -> int:
    return int(round((time.time() - started_at) * 1000))
