from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AgentTraceRecorder:
    """Writes case-level agent input/output traces for evaluation runners."""

    def __init__(self, output_dir: Path | str, *, experiment_name: str) -> None:
        self.output_dir = Path(output_dir)
        self.case_dir = self.output_dir / "cases"
        self.experiment_name = experiment_name
        self.records: list[dict[str, Any]] = []

    def add_case(
        self,
        *,
        trace_id: str,
        case_id: str | None,
        patient_key: str | None,
        image_path: str | None,
        source: str,
        service_payload: dict[str, Any],
        visual_runner_input: dict[str, Any],
        visual_runner_output: dict[str, Any],
        service_result: dict[str, Any],
        evaluation: dict[str, Any],
        model_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        events = [
            {
                "order": 1,
                "agent": "MedScopeService",
                "event": "handle_request_input",
                "input": service_payload,
                "output": {
                    "routing_expected_from_payload": {
                        "disease_key": service_payload.get("disease_key"),
                        "vision_mode": service_payload.get("vision_mode"),
                    }
                },
            },
            {
                "order": 2,
                "agent": "GaoDoctorAgent",
                "event": "orchestration_request",
                "input": {
                    "patient_message": service_payload.get("patient_message"),
                    "patient_info": service_payload.get("patient_info"),
                    "image_path": service_payload.get("image_path"),
                    "disease_key": service_payload.get("disease_key"),
                    "vision_mode": service_payload.get("vision_mode"),
                },
                "output": {
                    "case_id": case_id,
                    "analysis_status": service_result.get("analysis_status"),
                    "routing_decision": service_result.get("routing_decision"),
                    "alignment_plan": service_result.get("alignment_plan"),
                },
            },
            {
                "order": 3,
                "agent": "VisionAgent|NoMaskVisualRunner",
                "event": "visual_evidence_generation",
                "input": visual_runner_input,
                "output": visual_runner_output,
            },
            {
                "order": 4,
                "agent": "DiagnosisDoctorAgent",
                "event": "diagnosis_generation",
                "input": {
                    "visual_input_contract": service_result.get("visual_input_contract"),
                    "routing_decision": service_result.get("routing_decision"),
                    "alignment_plan": service_result.get("alignment_plan"),
                },
                "output": {
                    "report": service_result.get("report"),
                    "reply_to_patient": service_result.get("reply_to_patient"),
                    "analysis_status": service_result.get("analysis_status"),
                },
            },
            {
                "order": 5,
                "agent": "EvaluationRunner",
                "event": "xray_gt_scoring",
                "input": {
                    "prediction_source": "DiagnosisDoctorAgent final report",
                    "ground_truth_source": "Xray GT tag",
                },
                "output": evaluation,
            },
        ]
        if model_calls is not None:
            events.append(
                {
                    "order": 6,
                    "agent": "ModelCallLogger",
                    "event": "llm_prompt_response_records",
                    "input": {
                        "matching_scope": "records explicitly attached by runner",
                    },
                    "output": {
                        "model_call_count": len(model_calls),
                        "model_calls": model_calls,
                    },
                }
            )

        record = {
            "schema_version": "medscope_agent_case_trace.v1",
            "created_at": _utc_now(),
            "experiment_name": self.experiment_name,
            "trace_id": trace_id,
            "case_id": case_id,
            "patient_key": patient_key,
            "image_path": image_path,
            "source": source,
            "events": events,
        }
        self.records.append(_sanitize(record))

    def write(self) -> dict[str, str | int]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.case_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = self.output_dir / "case_traces.jsonl"
        index_path = self.output_dir / "case_trace_index.csv"
        summary_path = self.output_dir / "summary.json"

        index_rows = []
        with jsonl_path.open("w", encoding="utf-8") as jsonl:
            for order, record in enumerate(self.records, start=1):
                case_path = self.case_dir / f"{_safe_filename(record['trace_id'])}.json"
                case_path.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                jsonl.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                evaluation = _last_event_output(record, "EvaluationRunner")
                index_rows.append(
                    {
                        "order": order,
                        "experiment_name": record.get("experiment_name"),
                        "trace_id": record.get("trace_id"),
                        "case_id": record.get("case_id"),
                        "patient_key": record.get("patient_key"),
                        "source": record.get("source"),
                        "image_path": record.get("image_path"),
                        "gt_xray_stage": evaluation.get("gt_xray_stage"),
                        "agent_final_stage": evaluation.get("agent_final_stage"),
                        "agent_loose_stage": evaluation.get("agent_loose_stage"),
                        "agent_xray_3class_stage": evaluation.get("agent_xray_3class_stage"),
                        "correct": evaluation.get("correct"),
                        "loose_correct": evaluation.get("loose_correct"),
                        "xray_3class_correct": evaluation.get("xray_3class_correct"),
                        "model_call_count": _model_call_count(record),
                        "case_trace_path": str(case_path),
                    }
                )

        with index_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "order",
                    "experiment_name",
                    "trace_id",
                    "case_id",
                    "patient_key",
                    "source",
                    "image_path",
                    "gt_xray_stage",
                    "agent_final_stage",
                    "agent_loose_stage",
                    "agent_xray_3class_stage",
                    "correct",
                    "loose_correct",
                    "xray_3class_correct",
                    "model_call_count",
                    "case_trace_path",
                ],
            )
            writer.writeheader()
            writer.writerows(index_rows)

        summary = {
            "schema_version": "medscope_agent_trace_export_summary.v1",
            "experiment_name": self.experiment_name,
            "case_count": len(self.records),
            "case_traces_jsonl": str(jsonl_path),
            "case_trace_index_csv": str(index_path),
            "case_trace_dir": str(self.case_dir),
            "notes": [
                "Events are ordered by the evaluation runner's original-flow call sequence.",
                "Pure mock runs may have no LLM prompt/response because the visual evidence is injected from COCO GT.",
                "Image base64 payloads and secret-like fields are omitted from trace records.",
            ],
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "case_count": len(self.records),
            "case_traces_jsonl": str(jsonl_path),
            "case_trace_index_csv": str(index_path),
            "case_trace_dir": str(self.case_dir),
            "summary_path": str(summary_path),
        }


def make_trace_id(*parts: Any) -> str:
    text = "::".join(str(part) for part in parts if part is not None)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    readable = "_".join(str(part) for part in parts if part is not None)[:90]
    return f"{_safe_filename(readable)}_{digest}"


def _last_event_output(record: dict[str, Any], agent: str) -> dict[str, Any]:
    for event in reversed(record.get("events") or []):
        if event.get("agent") == agent:
            output = event.get("output")
            return output if isinstance(output, dict) else {}
    return {}


def _model_call_count(record: dict[str, Any]) -> int:
    for event in record.get("events") or []:
        if event.get("agent") != "ModelCallLogger":
            continue
        output = event.get("output")
        if isinstance(output, dict):
            try:
                return int(output.get("model_call_count") or 0)
            except Exception:
                return 0
    return 0


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("api_key", "apikey", "authorization", "bearer", "secret", "token")):
                sanitized[key] = "***REDACTED***"
            elif lowered in {"image_url"} and isinstance(item, str) and item.startswith("data:"):
                sanitized[key] = _summarize_data_url(item)
            else:
                sanitized[key] = _sanitize(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and value.startswith("data:") and ";base64," in value:
        return _summarize_data_url(value)
    return value


def _summarize_data_url(value: str) -> dict[str, Any]:
    header, encoded = value.split(";base64,", 1)
    return {
        "type": "data_url_omitted",
        "mime_type": header.removeprefix("data:"),
        "base64_chars": len(encoded),
        "reason": "base64 image payload omitted from agent trace",
    }


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)
    return cleaned.strip("._") or "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
