from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.service import MedScopeReadinessError, MedScopeService
from scripts.no_mask_vision_prompt_demo import _load_dotenv_local
from scripts.xray_mask_mock_eval import DEFAULT_EXPORT_DIR, OnfhCocoMockVisualRunner
from scripts.xray_roi_vlm_eval import (
    DEFAULT_ROI_DIR,
    STAGE_VALUES,
    _binary,
    _dedupe_roi_results_for_metrics,
    _metrics,
    _metrics_rows,
    _stage_from_findings,
    _visible_patient_side,
    _visible_side_rule,
    _write_roi_crop_and_debug,
)
from tools.medsam2_segmentation_tool import inspect_medsam2_configuration


DEFAULT_OUTPUT_DIR = Path("output/fake/onfh_roi_formal_service_blinded_eval")
PATIENT_MESSAGE = (
    "请按正式股骨头坏死视觉取证流程评估这张匿名单个股骨头 ROI Xray 图像。"
    "请定位并结构化股骨头坏死相关影像征象。"
)
ONFH_STAGE_TARGETS = {
    "sclerotic_band": "I/II",
    "cystic_change": "I/II",
    "mixed_density_region": "I/II",
    "trabecular_blurring": "I/II",
    "subchondral_fracture": "III+",
    "collapse": "III+",
}


def run_eval(
    *,
    roi_dir: Path,
    export_dir: Path,
    output_dir: Path,
    limit: int | None,
    continue_on_error: bool,
    force: bool,
) -> dict[str, Any]:
    _load_dotenv_local()
    os.environ.setdefault("MEDSCOPE_VISION_RESPONSES_STREAM", "1")
    os.environ.setdefault("MEDSCOPE_RESPONSES_STREAM", "1")

    output_dir.mkdir(parents=True, exist_ok=True)
    source_crop_dir = output_dir / "source_roi_crops"
    debug_dir = output_dir / "debug_overlays"
    sanitized_dir = output_dir / "sanitized_roi_images"
    source_crop_dir.mkdir(exist_ok=True)
    debug_dir.mkdir(exist_ok=True)
    sanitized_dir.mkdir(exist_ok=True)

    gt = OnfhCocoMockVisualRunner(export_dir=export_dir, side_mapping="ap_flip")
    roi_rows = pd.read_csv(roi_dir / "roi_components.csv").to_dict(orient="records")
    if limit is not None:
        roi_rows = roi_rows[:limit]

    existing = _load_existing(output_dir / "formal_service_predictions.jsonl") if not force else {}
    service = MedScopeService()
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for index, row in enumerate(roi_rows, start=1):
        roi_id = str(row["roi_component_id"])
        anonymous_id = f"roi_case_{index:04d}"
        patient_key = str(row["patient_key"])
        patient_side = _visible_patient_side(row, roi_rows)
        gt_stage_payload = gt.mri_stage_by_patient_side.get(patient_key, {}).get(patient_side) or {}
        gt_stage = gt_stage_payload.get("stage")

        if roi_id in existing:
            resumed = dict(existing[roi_id])
            resumed["resumed_from_existing"] = True
            results.append(resumed)
            print(f"[{index}/{len(roi_rows)}] resumed anonymous_id={anonymous_id}", flush=True)
            continue

        print(f"[{index}/{len(roi_rows)}] formal service blinded ROI anonymous_id={anonymous_id}", flush=True)
        try:
            source_crop_path, debug_overlay_path, crop_box = _write_roi_crop_and_debug(
                row=row,
                visible_patient_side=patient_side,
                crop_dir=source_crop_dir,
                debug_dir=debug_dir,
            )
            sanitized_path = sanitized_dir / f"{anonymous_id}.jpg"
            shutil.copyfile(source_crop_path, sanitized_path)

            service_result = service.handle_request(
                {
                    "patient_message": PATIENT_MESSAGE,
                    "image_path": str(sanitized_path),
                    "patient_info": {
                        "patient_id": anonymous_id,
                        "symptoms": [],
                        "source": "anonymous_roi_formal_service_eval",
                        "image_series": [
                            {
                                "image_id": "image_001",
                                "image_path": str(sanitized_path),
                                "view_hint": "xray_roi",
                            }
                        ],
                    },
                    "disease_key": "femoral_head_necrosis",
                    "vision_mode": "no_mask_skill",
                }
            )
            findings = _extract_findings(service_result)
            pred_stage = _stage_from_formal_findings(findings)
            result = {
                "roi_component_id": roi_id,
                "anonymous_id": anonymous_id,
                "service_case_id": service_result.get("case_id"),
                "analysis_status": service_result.get("analysis_status"),
                "image_id": int(row["image_id"]),
                "patient_key": patient_key,
                "patient_side": patient_side,
                "original_roi_patient_side": row.get("patient_side"),
                "image_side": row.get("image_side"),
                "visible_side_rule": _visible_side_rule(row, roi_rows),
                "image_path": row.get("image_path"),
                "sanitized_image_path": str(sanitized_path),
                "source_crop_path": str(source_crop_path),
                "debug_overlay_path": str(debug_overlay_path),
                "crop_box_x1": crop_box[0],
                "crop_box_y1": crop_box[1],
                "crop_box_x2": crop_box[2],
                "crop_box_y2": crop_box[3],
                "roi_bbox_x1": int(row["bbox_x1"]),
                "roi_bbox_y1": int(row["bbox_y1"]),
                "roi_bbox_x2": int(row["bbox_x2"]),
                "roi_bbox_y2": int(row["bbox_y2"]),
                "gt_mri_stage": gt_stage,
                "gt_stage_values": "|".join(gt_stage_payload.get("stage_values") or []),
                "gt_tag_labels": "|".join(gt_stage_payload.get("tag_labels") or []),
                "gt_frame_count": gt_stage_payload.get("frame_count", 0),
                "pred_stage": pred_stage,
                "pred_binary": _binary(pred_stage),
                "gt_binary": _binary(gt_stage),
                "correct_stage": bool(pred_stage == gt_stage) if gt_stage else False,
                "correct_binary": bool(_binary(pred_stage) == _binary(gt_stage)) if gt_stage else False,
                "finding_count": len(findings),
                "model_findings": findings,
                "report_stage_text": (service_result.get("report") or {}).get("分期判断"),
                "diagnostic_tendency": (service_result.get("report") or {}).get("diagnostic_tendency"),
                "case_memory_path": service_result.get("case_memory_path"),
                "service_result_path": str(output_dir / "service_results" / f"{anonymous_id}.json"),
            }
            result_path = Path(result["service_result_path"])
            result_path.parent.mkdir(exist_ok=True)
            result_path.write_text(json.dumps(service_result, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(result)
            _append_jsonl(output_dir / "formal_service_predictions.jsonl", result)
        except Exception as exc:
            failure = {
                "roi_component_id": roi_id,
                "anonymous_id": anonymous_id,
                "image_id": int(row.get("image_id") or 0),
                "error_type": getattr(exc, "error_type", exc.__class__.__name__),
                "error": str(exc),
                "readiness": exc.readiness if isinstance(exc, MedScopeReadinessError) else None,
                "traceback": traceback.format_exc(),
            }
            failures.append(failure)
            _append_jsonl(output_dir / "failures.jsonl", failure)
            if not continue_on_error:
                break

    predictions_csv = output_dir / "formal_service_predictions.csv"
    side_eval_csv = output_dir / "roi_side_level_eval.csv"
    dedup_csv = output_dir / "patient_side_dedup_eval.csv"
    metrics_csv = output_dir / "metrics_summary.csv"
    pd.DataFrame(results).to_csv(predictions_csv, index=False)
    pd.DataFrame(results).to_csv(side_eval_csv, index=False)
    pd.DataFrame(_dedupe_roi_results_for_metrics(results)).to_csv(dedup_csv, index=False)
    if failures:
        pd.DataFrame(failures).to_csv(output_dir / "failures.csv", index=False)

    metrics = {
        "roi_visible_side": _metrics(results),
        "patient_side_dedup_max_pred_severity": _metrics(_dedupe_roi_results_for_metrics(results)),
    }
    pd.DataFrame(_metrics_rows(metrics)).to_csv(metrics_csv, index=False)
    summary = {
        "status": "ok" if not failures else "completed_with_failures",
        "mode": "formal_service_no_mask_skill_blinded_roi",
        "leakage_controls": [
            "VLM receives only an anonymous ROI crop path under sanitized_roi_images.",
            "patient_message is generic and contains no patient name, side, original path, or GT.",
            "patient_info.patient_id is an anonymous id.",
            "Original metadata is used only after service.handle_request returns, for local scoring.",
        ],
        "roi_dir": str(roi_dir),
        "export_dir": str(export_dir),
        "output_dir": str(output_dir),
        "attempted_roi_components": len(roi_rows),
        "evaluated_roi_components": len(results),
        "failed_roi_components": len(failures),
        "medsam2_configuration": inspect_medsam2_configuration(),
        "predictions_csv": str(predictions_csv),
        "side_level_eval_csv": str(side_eval_csv),
        "patient_side_dedup_eval_csv": str(dedup_csv),
        "metrics_csv": str(metrics_csv),
        "metrics": metrics,
        "failures": failures,
    }
    summary_path = output_dir / "summary.json"
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _extract_findings(service_result: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = (
        service_result.get("visual_input_contract", {}).get("visual_evidence")
        or service_result.get("image_memory", {}).get("visual_evidence")
        or {}
    )
    findings = evidence.get("findings") or []
    if isinstance(findings, list):
        return [dict(item) for item in findings if isinstance(item, dict)]
    return []


def _stage_from_formal_findings(findings: list[dict[str, Any]]) -> str:
    targets = {str(item.get("target") or item.get("finding_id") or "") for item in findings}
    evidence_text = " ".join(
        str(item.get("evidence_text") or item.get("rationale") or item.get("description") or "")
        for item in findings
    ).lower()
    simple_payload = {"findings": sorted(targets)}
    stage = _stage_from_findings(simple_payload)
    if stage != "normal":
        return stage
    if any(target in evidence_text for target in ["collapse", "subchondral", "fracture", "新月", "塌陷", "骨折"]):
        return "III+"
    if any(
        target in evidence_text
        for target in ["sclerotic", "cystic", "mixed", "trabecular", "硬化", "囊", "混杂", "骨小梁"]
    ):
        return "I/II"
    return "normal"


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[str(row["roi_component_id"])] = row
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run official MedScopeService no-mask ONFH flow on blinded anonymous ROI crops."
    )
    parser.add_argument("--roi-dir", type=Path, default=DEFAULT_ROI_DIR)
    parser.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--force", action="store_true", help="Ignore existing jsonl predictions.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_eval(
        roi_dir=args.roi_dir,
        export_dir=args.export_dir,
        output_dir=args.output_dir,
        limit=args.limit,
        continue_on_error=not args.stop_on_error,
        force=args.force,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
