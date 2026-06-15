import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.service import MedScopeService
from agents.gaodoctor_agent import GaoDoctorAgent
from scripts.agent_trace_recorder import AgentTraceRecorder, make_trace_id
from scripts.no_mask_vision_prompt_demo import _load_dotenv_local
from scripts.xray_mask_mock_eval import (
    _has_structural_collapse_target,
    _stage_from_agent_report,
    _stage_from_agent_report_xray_3class,
    normalize_structural_collapse_findings,
)

DEFAULT_OUTPUT_DIR = Path("output/fake/xray_cached_mixed_original_flow_eval")
DEFAULT_MODEL_LOG_DIRS: list[Path] = []
DEFAULT_MOCK_ROWS_CSV = Path(
    "output/fake/xray_34tag_side_mock_roi_level_20260609/mock_roi_side_rows.csv"
)
DEFAULT_REAL_VLM_CSV = Path(
    "output/fake/xray_34tag_side_real_vlm_agent_20260609/formal_service_predictions.csv"
)


class CachedFindingsVisualRunner:
    def __init__(self):
        self.current_findings = []
        self.current_visual_output_mode = "unknown"

    def set_findings(self, findings: list[dict[str, Any]], visual_output_mode: str):
        self.current_findings = normalize_structural_collapse_findings(findings)
        self.current_visual_output_mode = visual_output_mode

    def __call__(
        self,
        *,
        image_path: str | Path,
        vision_skill: dict[str, Any] | None = None,
        requested_targets: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        positive_targets = {
            str(finding.get("target"))
            for finding in self.current_findings
            if str(finding.get("status") or "") != "negative"
        }
        suspected = []
        for finding in self.current_findings:
            text = (
                finding.get("summary_text")
                or finding.get("evidence_text")
                or finding.get("evidence_basis")
                or finding.get("display_name")
                or finding.get("target")
            )
            if text:
                suspected.append(str(text))
        if not suspected:
            suspected = ["当前 ROI 未发现明确候选征象"]

        return {
            "status": "ok",
            "image_path": str(image_path),
            "visual_analysis_result": {
                "image_path": str(image_path),
                "image_outputs": {
                    "original_image_path": str(image_path),
                    "mask_path": "roi.png",
                    "overlay_path": "roi.png",
                },
                "modality": "xray",
                "body_part": "hip",
                "disease_target": "femoral_head_necrosis",
                "measurements": {},
                "completeness": {},
                "visual_pipeline_outputs": [],
                "visual_evidence": {
                    "findings": self.current_findings,
                    "structured_visual_facts": self.current_findings,
                    "suspected_visual_findings": suspected,
                    "collapse": _has_structural_collapse_target(self.current_findings),
                    "sclerosis": bool("sclerotic_band" in positive_targets),
                    "cystic_change": bool("cystic_change" in positive_targets),
                    "joint_space_narrowing": False,
                    "joint_space": "未评估",
                    "texture_abnormality_score": 1.0 if positive_targets else 0.0,
                    "lesion_detected": bool(positive_targets),
                    "segmentation_quality": self.current_visual_output_mode,
                    "visual_output_mode": self.current_visual_output_mode,
                    "segmentation_status": "completed" if self.current_findings else "no_stage_relevant_findings",
                }
            }
        }


def _parse_model_findings(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    text = str(value or "").strip()
    if not text or text == "nan":
        return []
    try:
        payload = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _mock_visual_result_from_row(row: dict[str, Any]) -> dict[str, Any]:
    findings = []
    targets = [item for item in str(row.get("mock_instance_targets") or "").split("|") if item]
    labels = [item for item in str(row.get("mock_instance_labels") or "").split("|") if item]
    for index, target in enumerate(targets):
        label = labels[index] if index < len(labels) else target
        findings.append(
            {
                "finding_id": f"mock_roi_{row.get('roi_component_id')}_{index}",
                "target": target,
                "display_name": label,
                "status": "detected",
                "diagnosis_usable": True,
                "independent_evidence": True,
                "measurements": {
                    "patient_side": row.get("patient_side"),
                    "area_px": _float(row.get("mock_xray_side_area_px")),
                    "area_ratio_in_image": _float(row.get("mock_xray_side_area_ratio")),
                },
                "summary_text": f"{row.get('patient_side')} {label} from reviewed mock GT mask",
            }
        )
    findings = normalize_structural_collapse_findings(findings)
    image_path = str(row.get("crop_path") or row.get("image_path") or "mock_roi.png")
    suspected = [finding["summary_text"] for finding in findings]
    if not suspected:
        suspected = ["当前 ROI 未匹配到同侧 Xray GT mask 候选征象"]
    return {
        "image_path": image_path,
        "modality": "xray",
        "body_part": "hip",
        "image_outputs": {
            "original_image_path": image_path,
            "mask_path": str(row.get("mask_path") or image_path),
            "overlay_path": str(row.get("overlay_path") or image_path),
        },
        "requested_targets": sorted({finding["target"] for finding in findings}),
        "visual_evidence": {
            "collapse": _has_structural_collapse_target(findings),
            "sclerosis": any(f["target"] == "sclerotic_band" for f in findings),
            "cystic_change": any(f["target"] == "cystic_change" for f in findings),
            "joint_space_narrowing": False,
            "joint_space": "未评估",
            "texture_abnormality_score": 0.0,
            "lesion_detected": bool(findings),
            "segmentation_quality": "reviewed_gt_mask_mock",
            "visual_output_mode": "mock_gt_mask_roi",
            "segmentation_status": "completed" if findings else "no_same_side_mock_mask",
            "suspected_visual_findings": suspected,
            "findings": findings,
            "structured_visual_facts": findings,
        },
    }


def _mock_findings_for_xray_schema(source_row: dict[str, Any]) -> list[dict[str, Any]]:
    visual_result = _mock_visual_result_from_row(source_row)
    findings = list((visual_result.get("visual_evidence") or {}).get("findings") or [])
    if findings or _normalize_gt_xray(source_row.get("xray_tag_stage")) != "未发现异常":
        return findings
    return [
        {
            "finding_id": f"mock_roi_{source_row.get('roi_component_id')}_negative_xray",
            "target": "no_xray_onfh_finding",
            "display_name": "Xray 未见明确 ONFH 征象",
            "status": "negative",
            "diagnosis_usable": True,
            "independent_evidence": True,
            "summary_text": (
                f"{source_row.get('patient_side')} reviewed Xray mask 未标出硬化带、"
                "囊性变、软骨下骨折或塌陷候选征象"
            ),
            "measurements": {
                "patient_side": source_row.get("patient_side"),
                "roi_component_id": source_row.get("roi_component_id"),
                "mock_xray_instance_count": 0,
            },
        }
    ]


class CachedModelCallIndex:
    def __init__(self, log_dirs: list[Path] | None = None) -> None:
        self.records_by_image_path: dict[str, list[dict[str, Any]]] = {}
        self.records_by_text_key: dict[str, list[dict[str, Any]]] = {}
        for log_dir in DEFAULT_MODEL_LOG_DIRS if log_dirs is None else log_dirs:
            self._load_log_dir(log_dir)

    def calls_for_row(self, row: pd.Series | dict[str, Any] | None) -> list[dict[str, Any]]:
        if row is None:
            return []
        get = row.get
        image_keys = [
            str(get("sanitized_image_path") or ""),
            str(get("source_crop_path") or ""),
        ]
        text_keys = [str(get("service_case_id") or "")]
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for key in image_keys:
            if not key:
                continue
            for record in self.records_by_image_path.get(key, []):
                call_id = str(record.get("call_id") or id(record))
                if call_id not in seen:
                    seen.add(call_id)
                    records.append(record)
        for key in text_keys:
            if not key:
                continue
            for record in self.records_by_text_key.get(key, []):
                call_id = str(record.get("call_id") or id(record))
                if call_id not in seen:
                    seen.add(call_id)
                    records.append(record)
        return sorted(records, key=lambda item: str(item.get("logged_at") or ""))

    def _load_log_dir(self, log_dir: Path) -> None:
        jsonl_path = log_dir / "model_calls.jsonl"
        if not jsonl_path.exists():
            return
        for line_no, line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            record = _compact_model_call_record(raw, jsonl_path=jsonl_path, line_no=line_no)
            image_path = str((raw.get("image") or {}).get("image_path") or "")
            if image_path:
                self.records_by_image_path.setdefault(image_path, []).append(record)
            text = json.dumps(raw, ensure_ascii=False)
            for key in _extract_text_keys(text):
                self.records_by_text_key.setdefault(key, []).append(record)


def _compact_model_call_record(raw: dict[str, Any], *, jsonl_path: Path, line_no: int) -> dict[str, Any]:
    request_payload = (raw.get("request") or {}).get("payload")
    response = raw.get("response") or {}
    raw_response = response.get("raw") if isinstance(response, dict) else None
    return {
        "schema_version": "cached_model_call_reference.v1",
        "source": "cached_model_call_log",
        "task": raw.get("task"),
        "call_id": raw.get("call_id"),
        "logged_at": raw.get("logged_at"),
        "client": raw.get("client"),
        "model": raw.get("model"),
        "route": raw.get("route"),
        "endpoint": raw.get("endpoint"),
        "status": raw.get("status"),
        "duration_ms": raw.get("duration_ms"),
        "image": raw.get("image"),
        "request_payload": request_payload,
        "response_content": response.get("content") if isinstance(response, dict) else None,
        "response_raw_summary": _raw_response_summary(raw_response),
        "source_jsonl_path": str(jsonl_path),
        "source_jsonl_line": line_no,
        "source_json_path": _per_call_json_path(raw, jsonl_path.parent),
    }


def _raw_response_summary(raw_response: Any) -> dict[str, Any] | None:
    if not isinstance(raw_response, dict):
        return None
    events = raw_response.get("events")
    return {
        "stream": raw_response.get("stream"),
        "event_count": len(events) if isinstance(events, list) else raw_response.get("event_count"),
        "raw_text_present": bool(raw_response.get("raw_text")),
    }


def _per_call_json_path(raw: dict[str, Any], log_dir: Path) -> str | None:
    task = str(raw.get("task") or "unknown_task")
    call_id = str(raw.get("call_id") or "")
    if not call_id:
        return None
    safe_task = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in task).strip("._")
    candidate = log_dir / f"{safe_task}_{call_id}.json"
    return str(candidate) if candidate.exists() else None


def _extract_text_keys(text: str) -> set[str]:
    keys = set()
    import re

    keys.update(re.findall(r"roi_case_\d{4}", text))
    keys.update(re.findall(r"case_\d{8}_\d{6}_\d{6}", text))
    keys.update(re.findall(r"image_\d+_(?:side|roi)_[A-Za-z0-9_]+", text))
    return keys


def _vlm_findings_for_side(vlm_row: pd.Series, mock_row: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = _parse_model_findings(vlm_row.get("model_findings"))
    patient_side = str(mock_row.get("patient_side") or vlm_row.get("patient_side") or "")
    findings = []
    for index, finding in enumerate(parsed, start=1):
        target = str(finding.get("target") or "")
        if not target:
            continue
        display_name = str(finding.get("display_name") or target)
        text = str(
            finding.get("evidence_text")
            or finding.get("evidence_basis")
            or finding.get("summary_text")
            or ""
        )
        findings.append(
            {
                "finding_id": f"real_vlm_{vlm_row.get('roi_component_id')}_{index}_{target}",
                "target": target,
                "display_name": display_name,
                "status": "detected",
                "source": "real_vlm_roi_crop",
                "diagnosis_usable": True,
                "independent_evidence": True,
                "summary_text": f"{patient_side} {display_name} from real ROI VLM: {text}",
                "evidence_text": text,
                "measurements": {
                    "patient_side": patient_side,
                    "roi_component_id": vlm_row.get("roi_component_id"),
                    "confidence": _float(finding.get("confidence")),
                    "source": "real_vlm_roi_crop",
                },
            }
        )
    return normalize_structural_collapse_findings(findings)


def _normalize_gt_xray(value: Any) -> str:
    text = str(value or "")
    if "III" in text or "3期" in text or "三期" in text:
        return "3期"
    if "II" in text or "2期" in text or "二期" in text or "I/II" in text or "I-II" in text:
        return "2期"
    return "未发现异常"


def _compute_metrics(evaluable: list[dict[str, Any]], pred_col: str, correct_col: str, abstain_col: str) -> dict[str, Any]:
    correct = [row for row in evaluable if row.get(correct_col)]
    non_abstain = [row for row in evaluable if not row.get(abstain_col)]
    non_abstain_correct = [row for row in non_abstain if row.get(correct_col)]
    by_stage: dict[str, dict[str, int]] = {}
    confusion: dict[str, dict[str, int]] = {}
    for row in evaluable:
        gt_stage = str(row.get("gt_xray_stage"))
        pred_stage = str(row.get(pred_col))
        bucket = by_stage.setdefault(gt_stage, {"total": 0, "correct": 0})
        bucket["total"] += 1
        if row.get(correct_col):
            bucket["correct"] += 1
        confusion.setdefault(gt_stage, {})
        confusion[gt_stage][pred_stage] = confusion[gt_stage].get(pred_stage, 0) + 1
    for payload in by_stage.values():
        payload["accuracy"] = payload["correct"] / payload["total"] if payload["total"] else 0.0
    return {
        "evaluable_side_cases": len(evaluable),
        "correct": len(correct),
        "accuracy": len(correct) / len(evaluable) if evaluable else None,
        "abstained": len(evaluable) - len(non_abstain),
        "coverage": len(non_abstain) / len(evaluable) if evaluable else None,
        "non_abstain_correct": len(non_abstain_correct),
        "non_abstain_accuracy": (
            len(non_abstain_correct) / len(non_abstain) if non_abstain else None
        ),
        "by_gt_stage": by_stage,
        "confusion": confusion,
    }


def _service_request(mock_row: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "patient_message": "请根据提供的 X光髋关节 ROI 图像特征进行 ONFH 诊断。",
        "image_path": "roi.png",
        "patient_info": {
            "patient_id": mock_row.get("patient_key"),
            "symptoms": ["髋关节疼痛"],
            "source": source,
            "image_series": [
                {
                    "image_id": "image_001",
                    "image_path": "roi.png",
                    "view_hint": "xray_roi",
                    "modality": "X-ray",
                }
            ],
        },
        "disease_key": "femoral_head_necrosis",
        "vision_mode": "no_mask_skill",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mock-rows-csv",
        type=Path,
        default=DEFAULT_MOCK_ROWS_CSV,
        help="ROI-side mock finding table used as the Xray GT/mock evidence source.",
    )
    parser.add_argument(
        "--real-vlm-csv",
        type=Path,
        default=DEFAULT_REAL_VLM_CSV,
        help="ROI-side real VLM findings table.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--row-start", type=int, default=0, help="Start offset in mock ROI rows.")
    parser.add_argument("--row-count", type=int, default=None, help="Number of mock ROI rows to evaluate.")
    parser.add_argument(
        "--mode",
        choices=["real-vlm", "mixed", "both"],
        default="both",
        help="Select which findings source to evaluate. 'both' reproduces the summary table.",
    )
    parser.add_argument("--use-llm", action="store_true", help="Use DiagnosisDoctorAgent LLM inference path.")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Record failed route/case service calls and continue the batch.",
    )
    parser.add_argument(
        "--model-log-dir",
        type=Path,
        action="append",
        default=None,
        help="Optional model-call log directory containing model_calls.jsonl. Can be repeated.",
    )
    args = parser.parse_args()

    _load_dotenv_local()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    mock_df = pd.read_csv(args.mock_rows_csv).fillna("")
    vlm_df = pd.read_csv(args.real_vlm_csv).fillna("")
    vlm_by_roi = {
        str(row["roi_component_id"]): row
        for _, row in vlm_df.iterrows()
        if str(row.get("roi_component_id") or "")
    }
    model_call_index = CachedModelCallIndex(args.model_log_dir)

    runner = CachedFindingsVisualRunner()
    
    from agents.diagnosis_agent import DiagnosisDoctorAgent
    from llm.model_client import OpenAICompatibleModelClient
    from scripts.recording_prompt_runner import RecordingPromptRunner
    
    prompt_runner = RecordingPromptRunner(OpenAICompatibleModelClient()) if args.use_llm else None
    diag_agent = DiagnosisDoctorAgent(
        prompt_runner=prompt_runner
    )
    gao_agent = GaoDoctorAgent(
        no_mask_visual_pipeline_runner=runner,
        diagnosis_agent=diag_agent,
        prompt_runner=prompt_runner,
    )
    service = MedScopeService(gaodoctor_agent=gao_agent)
    trace_recorder = AgentTraceRecorder(
        args.output_dir / "agent_traces",
        experiment_name=f"xray_cached_original_flow_{args.mode}",
    )

    rows = []
    failed_service_units: list[dict[str, Any]] = []
    source_rows = mock_df.to_dict(orient="records")
    if args.row_start:
        source_rows = source_rows[args.row_start:]
    if args.row_count is not None:
        source_rows = source_rows[:args.row_count]
    if args.limit:
        source_rows = source_rows[:args.limit]

    for mock_row in source_rows:
        roi_id = str(mock_row.get("roi_component_id") or "")
        vlm_row = vlm_by_roi.get(roi_id)
        mock_findings = _mock_findings_for_xray_schema(mock_row)
        vlm_findings = _vlm_findings_for_side(vlm_row, mock_row) if vlm_row is not None else []
        cached_vlm_model_calls = model_call_index.calls_for_row(vlm_row)
        combined_findings = mock_findings + vlm_findings

        gt_xray_stage = mock_row.get("xray_tag_stage")
        if not gt_xray_stage:
            print(f"Skipping {roi_id} because no xray_tag_stage")
            continue

        gt_xray_stage_norm = _normalize_gt_xray(gt_xray_stage)

        real_report = {}
        mixed_report = {}
        real_result = {}
        mixed_result = {}
        real_success = False
        mixed_success = False
        if args.mode in {"real-vlm", "both"}:
            runner.set_findings(vlm_findings, "real_vlm_roi_findings")
            real_payload = _service_request(mock_row, source="xray_roi_real_vlm")
            call_start = len(prompt_runner.calls) if prompt_runner else 0
            try:
                real_result = service.handle_request(real_payload)
            except Exception as exc:
                real_live_model_calls = prompt_runner.take_new_calls(call_start) if prompt_runner else []
                failed_service_units.append(
                    {
                        "route": "real_vlm",
                        "roi_component_id": roi_id,
                        "patient_key": mock_row.get("patient_key"),
                        "patient_side": mock_row.get("patient_side"),
                        "gt_xray_stage": gt_xray_stage_norm,
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                        "cached_model_call_count": len(cached_vlm_model_calls),
                        "live_model_call_count": len(real_live_model_calls),
                    }
                )
                if not args.continue_on_error:
                    raise
            else:
                real_success = True
                real_live_model_calls = prompt_runner.take_new_calls(call_start) if prompt_runner else []
                real_report = real_result.get("report") or {}
                real_final_stage = _stage_from_agent_report(real_report, loose=False)
                real_loose_stage = _stage_from_agent_report(real_report, loose=True)
                real_xray_3class_stage = _stage_from_agent_report_xray_3class(
                    real_report,
                    patient_side=str(mock_row.get("patient_side") or ""),
                )
                trace_recorder.add_case(
                    trace_id=make_trace_id("real_vlm", roi_id, mock_row.get("patient_key"), mock_row.get("patient_side")),
                    case_id=real_result.get("case_id"),
                    patient_key=str(mock_row.get("patient_key") or ""),
                    image_path=str(real_payload.get("image_path") or ""),
                    source="real_vlm_roi_findings",
                    service_payload=real_payload,
                    visual_runner_input={
                        "runner": "CachedFindingsVisualRunner",
                        "roi_component_id": roi_id,
                        "patient_side": mock_row.get("patient_side"),
                        "visual_output_mode": "real_vlm_roi_findings",
                        "finding_count": len(vlm_findings),
                        "findings": vlm_findings,
                        "cached_model_call_count": len(cached_vlm_model_calls),
                    },
                    visual_runner_output={
                        "visual_analysis_result": real_result.get("visual_input_contract"),
                        "report": real_report,
                    },
                    service_result=real_result,
                    evaluation={
                        "roi_component_id": roi_id,
                        "patient_side": mock_row.get("patient_side"),
                        "gt_xray_stage": gt_xray_stage_norm,
                        "agent_final_stage": real_final_stage,
                        "agent_loose_stage": real_loose_stage,
                        "agent_xray_3class_stage": real_xray_3class_stage,
                        "correct": bool(real_final_stage == gt_xray_stage_norm),
                        "loose_correct": bool(real_loose_stage == gt_xray_stage_norm),
                        "xray_3class_correct": bool(real_xray_3class_stage == gt_xray_stage_norm),
                        "abstained": real_final_stage == "abstain",
                        "loose_abstained": real_loose_stage == "abstain",
                        "xray_3class_abstained": real_xray_3class_stage == "abstain",
                    },
                    model_calls=cached_vlm_model_calls + real_live_model_calls,
                )

        if args.mode in {"mixed", "both"}:
            runner.set_findings(combined_findings, "mixed_real_vlm_plus_mock_findings")
            mixed_payload = _service_request(mock_row, source="xray_roi_mixed")
            call_start = len(prompt_runner.calls) if prompt_runner else 0
            try:
                mixed_result = service.handle_request(mixed_payload)
            except Exception as exc:
                mixed_live_model_calls = prompt_runner.take_new_calls(call_start) if prompt_runner else []
                failed_service_units.append(
                    {
                        "route": "mixed",
                        "roi_component_id": roi_id,
                        "patient_key": mock_row.get("patient_key"),
                        "patient_side": mock_row.get("patient_side"),
                        "gt_xray_stage": gt_xray_stage_norm,
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                        "cached_model_call_count": len(cached_vlm_model_calls),
                        "live_model_call_count": len(mixed_live_model_calls),
                    }
                )
                if not args.continue_on_error:
                    raise
            else:
                mixed_success = True
                mixed_live_model_calls = prompt_runner.take_new_calls(call_start) if prompt_runner else []
                mixed_report = mixed_result.get("report") or {}
                mixed_final_stage = _stage_from_agent_report(mixed_report, loose=False)
                mixed_loose_stage = _stage_from_agent_report(mixed_report, loose=True)
                mixed_xray_3class_stage = _stage_from_agent_report_xray_3class(
                    mixed_report,
                    patient_side=str(mock_row.get("patient_side") or ""),
                )
                trace_recorder.add_case(
                    trace_id=make_trace_id("mixed", roi_id, mock_row.get("patient_key"), mock_row.get("patient_side")),
                    case_id=mixed_result.get("case_id"),
                    patient_key=str(mock_row.get("patient_key") or ""),
                    image_path=str(mixed_payload.get("image_path") or ""),
                    source="mixed_real_vlm_plus_mock_findings",
                    service_payload=mixed_payload,
                    visual_runner_input={
                        "runner": "CachedFindingsVisualRunner",
                        "roi_component_id": roi_id,
                        "patient_side": mock_row.get("patient_side"),
                        "visual_output_mode": "mixed_real_vlm_plus_mock_findings",
                        "mock_finding_count": len(mock_findings),
                        "vlm_finding_count": len(vlm_findings),
                        "combined_finding_count": len(combined_findings),
                        "cached_model_call_count": len(cached_vlm_model_calls),
                        "mock_findings": mock_findings,
                        "vlm_findings": vlm_findings,
                        "combined_findings": combined_findings,
                    },
                    visual_runner_output={
                        "visual_analysis_result": mixed_result.get("visual_input_contract"),
                        "report": mixed_report,
                    },
                    service_result=mixed_result,
                    evaluation={
                        "roi_component_id": roi_id,
                        "patient_side": mock_row.get("patient_side"),
                        "gt_xray_stage": gt_xray_stage_norm,
                        "agent_final_stage": mixed_final_stage,
                        "agent_loose_stage": mixed_loose_stage,
                        "agent_xray_3class_stage": mixed_xray_3class_stage,
                        "correct": bool(mixed_final_stage == gt_xray_stage_norm),
                        "loose_correct": bool(mixed_loose_stage == gt_xray_stage_norm),
                        "xray_3class_correct": bool(mixed_xray_3class_stage == gt_xray_stage_norm),
                        "abstained": mixed_final_stage == "abstain",
                        "loose_abstained": mixed_loose_stage == "abstain",
                        "xray_3class_abstained": mixed_xray_3class_stage == "abstain",
                    },
                    model_calls=cached_vlm_model_calls + mixed_live_model_calls,
                )

        real_final = _stage_from_agent_report(real_report, loose=False)
        real_loose = _stage_from_agent_report(real_report, loose=True)
        real_xray_3class = _stage_from_agent_report_xray_3class(
            real_report,
            patient_side=str(mock_row.get("patient_side") or ""),
        )
        mixed_final = _stage_from_agent_report(mixed_report, loose=False)
        mixed_loose = _stage_from_agent_report(mixed_report, loose=True)
        mixed_xray_3class = _stage_from_agent_report_xray_3class(
            mixed_report,
            patient_side=str(mock_row.get("patient_side") or ""),
        )

        rows.append({
            "roi_component_id": roi_id,
            "patient_key": mock_row.get("patient_key"),
            "patient_side": mock_row.get("patient_side"),
            "gt_xray_stage": gt_xray_stage_norm,
            "mock_finding_count": len(mock_findings),
            "vlm_finding_count": len(vlm_findings),
            "combined_finding_count": len(combined_findings),
            "real_success": real_success,
            "mixed_success": mixed_success,

            "real_final": real_final,
            "real_final_correct": bool(real_final == gt_xray_stage_norm),
            "real_final_abstained": real_final == "abstain",

            "real_loose": real_loose,
            "real_loose_correct": bool(real_loose == gt_xray_stage_norm),
            "real_loose_abstained": real_loose == "abstain",

            "real_xray_3class": real_xray_3class,
            "real_xray_3class_correct": bool(real_xray_3class == gt_xray_stage_norm),
            "real_xray_3class_abstained": real_xray_3class == "abstain",

            "mixed_final": mixed_final,
            "mixed_final_correct": bool(mixed_final == gt_xray_stage_norm),
            "mixed_final_abstained": mixed_final == "abstain",

            "mixed_loose": mixed_loose,
            "mixed_loose_correct": bool(mixed_loose == gt_xray_stage_norm),
            "mixed_loose_abstained": mixed_loose == "abstain",

            "mixed_xray_3class": mixed_xray_3class,
            "mixed_xray_3class_correct": bool(mixed_xray_3class == gt_xray_stage_norm),
            "mixed_xray_3class_abstained": mixed_xray_3class == "abstain",
        })

    out_df = pd.DataFrame(rows)
    evaluable = out_df.to_dict(orient="records")

    summary = {
        "side_cases": len(evaluable),
        "mode": args.mode,
        "use_llm": args.use_llm,
        "row_start": args.row_start,
        "row_count": args.row_count,
        "failed_service_units": failed_service_units,
        "failed_service_unit_count": len(failed_service_units),
    }
    if args.mode in {"real-vlm", "both"}:
        real_evaluable = [row for row in evaluable if row.get("real_success")]
        summary["real_vlm_final_metrics"] = _compute_metrics(
            real_evaluable, "real_final", "real_final_correct", "real_final_abstained"
        )
        summary["real_vlm_loose_metrics"] = _compute_metrics(
            real_evaluable, "real_loose", "real_loose_correct", "real_loose_abstained"
        )
        summary["real_vlm_xray_3class_metrics"] = _compute_metrics(
            real_evaluable,
            "real_xray_3class",
            "real_xray_3class_correct",
            "real_xray_3class_abstained",
        )
    if args.mode in {"mixed", "both"}:
        mixed_evaluable = [row for row in evaluable if row.get("mixed_success")]
        summary["mixed_final_metrics"] = _compute_metrics(
            mixed_evaluable, "mixed_final", "mixed_final_correct", "mixed_final_abstained"
        )
        summary["mixed_loose_metrics"] = _compute_metrics(
            mixed_evaluable, "mixed_loose", "mixed_loose_correct", "mixed_loose_abstained"
        )
        summary["mixed_xray_3class_metrics"] = _compute_metrics(
            mixed_evaluable,
            "mixed_xray_3class",
            "mixed_xray_3class_correct",
            "mixed_xray_3class_abstained",
        )
    summary["agent_trace_export"] = trace_recorder.write()

    out_df.to_csv(args.output_dir / "eval_rows.csv", index=False)
    with open(args.output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
