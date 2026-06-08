from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.no_mask_vision_prompt_demo import _load_dotenv_local
from scripts.xray_mask_mock_eval import DEFAULT_EXPORT_DIR, OnfhCocoMockVisualRunner
from tools.vision_prompt_generator import OpenAICompatibleVisionClient


DEFAULT_ROI_DIR = Path(
    "/data/gongwenxin/workspace/onfh/outputs/"
    "onfh_xray_14cases_femoral_head_roi_evidence_20260607_sam3only_00031"
)
DEFAULT_OUTPUT_DIR = Path("output/fake/onfh_coco_roi_crop_real_visual_eval")
STAGE_VALUES = ("normal", "I/II", "III+")
ONFH_TARGETS = {
    "sclerotic_band",
    "cystic_change",
    "subchondral_fracture",
    "mixed_density_region",
    "collapse",
    "trabecular_blurring",
}


def run_eval(
    *,
    roi_dir: Path,
    export_dir: Path,
    output_dir: Path,
    limit: int | None,
    continue_on_error: bool,
    force: bool,
    max_retries: int,
    blinded_prompt: bool,
) -> dict[str, Any]:
    _load_dotenv_local()
    output_dir.mkdir(parents=True, exist_ok=True)
    crop_dir = output_dir / "roi_crops"
    debug_dir = output_dir / "debug_overlays"
    crop_dir.mkdir(exist_ok=True)
    debug_dir.mkdir(exist_ok=True)

    gt = OnfhCocoMockVisualRunner(export_dir=export_dir, side_mapping="ap_flip")
    roi_rows = pd.read_csv(roi_dir / "roi_components.csv").to_dict(orient="records")
    if limit is not None:
        roi_rows = roi_rows[:limit]

    client = OpenAICompatibleVisionClient(timeout_seconds=180, responses_stream=True)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    existing_by_roi = _load_existing_results(output_dir / "roi_crop_predictions.jsonl") if not force else {}

    for index, row in enumerate(roi_rows, start=1):
        roi_id = str(row["roi_component_id"])
        patient_side = _visible_patient_side(row, roi_rows)
        patient_key = str(row["patient_key"])
        gt_stage_payload = gt.mri_stage_by_patient_side.get(patient_key, {}).get(patient_side) or {}
        gt_stage = gt_stage_payload.get("stage")

        if roi_id in existing_by_roi:
            result = dict(existing_by_roi[roi_id])
            result["resumed_from_existing"] = True
            results.append(result)
            print(f"[{index}/{len(roi_rows)}] resumed roi={roi_id}", flush=True)
            continue

        print(
            f"[{index}/{len(roi_rows)}] VLM ROI crop image_id={int(row['image_id'])} "
            f"roi={roi_id} side={patient_side} patient={patient_key}",
            flush=True,
        )
        try:
            crop_path, debug_overlay_path, crop_box = _write_roi_crop_and_debug(
                row=row,
                visible_patient_side=patient_side,
                crop_dir=crop_dir,
                debug_dir=debug_dir,
            )
            raw_text = _call_vlm_with_retries(
                client=client,
                crop_path=crop_path,
                row=row,
                patient_side=patient_side,
                gt_stage_present=bool(gt_stage),
                max_retries=max_retries,
                blinded_prompt=blinded_prompt,
            )
            parsed = _parse_model_json(raw_text)
            pred_stage = _normalize_stage(parsed.get("stage"))
            if pred_stage is None:
                pred_stage = _stage_from_findings(parsed)
            result = {
                "roi_component_id": roi_id,
                "image_id": int(row["image_id"]),
                "patient_key": patient_key,
                "patient_side": patient_side,
                "original_roi_patient_side": row.get("patient_side"),
                "image_side": row.get("image_side"),
                "visible_side_rule": _visible_side_rule(row, roi_rows),
                "image_path": row.get("image_path"),
                "crop_path": str(crop_path),
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
                "model_findings": parsed.get("findings") or [],
                "model_confidence": parsed.get("confidence"),
                "model_reasoning": parsed.get("reasoning"),
                "raw_model_text": raw_text,
                "parsed_model_json": parsed,
            }
            results.append(result)
            _append_jsonl(output_dir / "roi_crop_predictions.jsonl", result)
        except Exception as exc:
            failure = {
                "roi_component_id": roi_id,
                "image_id": int(row.get("image_id") or 0),
                "patient_key": patient_key,
                "patient_side": patient_side,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
            failures.append(failure)
            _append_jsonl(output_dir / "failures.jsonl", failure)
            if not continue_on_error:
                break

    roi_side_df = pd.DataFrame(results)
    dedup_side_df = pd.DataFrame(_dedupe_roi_results_for_metrics(results))
    pred_df = pd.DataFrame(results)
    failures_df = pd.DataFrame(failures)
    pred_csv = output_dir / "roi_crop_predictions.csv"
    side_csv = output_dir / "roi_side_level_eval.csv"
    dedup_side_csv = output_dir / "patient_side_dedup_eval.csv"
    metrics_csv = output_dir / "metrics_summary.csv"
    pred_df.to_csv(pred_csv, index=False)
    roi_side_df.to_csv(side_csv, index=False)
    dedup_side_df.to_csv(dedup_side_csv, index=False)
    if not failures_df.empty:
        failures_df.to_csv(output_dir / "failures.csv", index=False)

    metrics = {
        "roi_visible_side": _metrics(roi_side_df.to_dict(orient="records")),
        "patient_side_dedup_max_pred_severity": _metrics(dedup_side_df.to_dict(orient="records")),
    }
    pd.DataFrame(_metrics_rows(metrics)).to_csv(metrics_csv, index=False)
    summary = {
        "status": "ok" if not failures else "completed_with_failures",
        "mode": "roi_crop_real_vlm",
        "blinded_prompt": blinded_prompt,
        "roi_dir": str(roi_dir),
        "export_dir": str(export_dir),
        "output_dir": str(output_dir),
        "attempted_roi_components": len(roi_rows),
        "evaluated_roi_components": len(results),
        "failed_roi_components": len(failures),
        "metric_unit": "primary: visible_femoral_head_roi_crop_side; secondary: patient_side_dedup_max_pred_severity",
        "note": (
            "Each visible femoral-head ROI crop is evaluated as one side case. "
            "Single-side Xray crops use path laterality hints when present, so a single visible right hip is not scored as image-right->patient-left."
        ),
        "prediction_csv": str(pred_csv),
        "side_level_eval_csv": str(side_csv),
        "patient_side_dedup_eval_csv": str(dedup_side_csv),
        "metrics_csv": str(metrics_csv),
        "metrics": metrics,
        "failures": failures,
    }
    summary_path = output_dir / "summary.json"
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _system_prompt() -> str:
    return (
        "你是骨关节影像辅助分析模型。你只根据给定的单个股骨头 ROI crop 判断这一个髋侧。"
        "不要推断图像外未显示的对侧。请输出严格 JSON。"
    )


def _user_payload(
    *,
    row: dict[str, Any],
    patient_side: str,
    gt_stage_present: bool,
    blinded_prompt: bool = False,
) -> dict[str, Any]:
    if blinded_prompt:
        return {
            "task": "Single femoral-head ROI crop radiographic assessment",
            "roi_semantics": "femoral_head_roi_crop_only",
            "instructions": [
                "只评估图中显示的这个股骨头 ROI crop。",
                "不要推断图像外未显示的对侧。",
                "不要依赖任何临床、路径、病人或队列信息；本请求不提供这些信息。",
                "判断是否存在股骨头坏死相关 Xray 征象：硬化带、囊性变、软骨下骨折/新月征、混杂密度区、塌陷、骨小梁紊乱。",
                "stage 只能取 normal、I/II、III+。",
                "如果看到明确软骨下骨折/新月征或塌陷，stage 取 III+。",
                "如果有硬化带、囊性变、混杂密度区但无明确塌陷/骨折，stage 取 I/II。",
                "如果未见明确相关征象，stage 取 normal。",
            ],
            "output_json_schema": {
                "stage": "normal | I/II | III+",
                "findings": [
                    "sclerotic_band",
                    "cystic_change",
                    "subchondral_fracture",
                    "mixed_density_region",
                    "collapse",
                    "trabecular_blurring",
                ],
                "confidence": "0-1 number",
                "reasoning": "short Chinese explanation based only on visible crop",
            },
        }
    return {
        "task": "ONFH Xray ROI crop finding and ARCO-stage tendency",
        "roi_semantics": "femoral_head_roi_crop_only_not_lesion_mask",
        "patient_key": row.get("patient_key"),
        "patient_side_to_assess": patient_side,
        "image_path_context": row.get("image_path"),
        "instructions": [
            "只评估 crop 中显示的这个股骨头 ROI。",
            "判断是否有股骨头坏死相关 Xray 征象：硬化带、囊性变、软骨下骨折/新月征、混杂密度区、塌陷、骨小梁紊乱。",
            "stage 只能取 normal、I/II、III+。",
            "如果看到明确软骨下骨折/新月征或塌陷，stage 取 III+。",
            "如果有硬化带、囊性变、混杂密度区但无明确塌陷/骨折，stage 取 I/II。",
            "如果未见明确 ONFH 征象，stage 取 normal。",
            "不要因为原图路径或临床文字里有 ONFH 就直接判阳性，必须基于 crop 影像表现。",
        ],
        "output_json_schema": {
            "stage": "normal | I/II | III+",
            "findings": [
                "sclerotic_band",
                "cystic_change",
                "subchondral_fracture",
                "mixed_density_region",
                "collapse",
                "trabecular_blurring",
            ],
            "confidence": "0-1 number",
            "reasoning": "short Chinese explanation based on visible crop",
        },
        "gt_stage_available_for_evaluation_only_not_for_model": gt_stage_present,
    }


def _call_vlm_with_retries(
    *,
    client: OpenAICompatibleVisionClient,
    crop_path: Path,
    row: dict[str, Any],
    patient_side: str,
    gt_stage_present: bool,
    max_retries: int,
    blinded_prompt: bool,
) -> str:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            raw_text = client.chat_with_image(
                image_path=crop_path,
                system_prompt=_system_prompt(),
                user_payload=_user_payload(
                    row=row,
                    patient_side=patient_side,
                    gt_stage_present=gt_stage_present,
                    blinded_prompt=blinded_prompt,
                ),
                task="onfh_xray_roi_crop_stage_eval",
            )
            if _clean_model_text(raw_text):
                return raw_text
            raise ValueError("empty VLM response text")
        except Exception as exc:
            last_error = exc
            print(
                f"  retryable VLM failure attempt={attempt}/{max_retries}: "
                f"{exc.__class__.__name__}: {exc}",
                flush=True,
            )
    assert last_error is not None
    raise last_error


def _write_roi_crop_and_debug(
    *,
    row: dict[str, Any],
    visible_patient_side: str,
    crop_dir: Path,
    debug_dir: Path,
) -> tuple[Path, Path, tuple[int, int, int, int]]:
    image_path = Path(str(row["image_path"]))
    with Image.open(image_path) as raw:
        image = raw.convert("RGB")
    width, height = image.size
    x1, y1, x2, y2 = [int(row[key]) for key in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2")]
    margin = int(max(x2 - x1, y2 - y1) * 0.35)
    crop_box = (
        max(0, x1 - margin),
        max(0, y1 - margin),
        min(width, x2 + margin),
        min(height, y2 + margin),
    )
    crop = image.crop(crop_box)
    safe_roi = _safe_name(str(row["roi_component_id"]))
    crop_path = crop_dir / f"{int(row['image_id']):04d}_{safe_roi}_{visible_patient_side}.jpg"
    crop.save(crop_path, quality=95)

    debug = image.copy()
    draw = ImageDraw.Draw(debug)
    draw.rectangle((x1, y1, x2, y2), outline=(255, 0, 0), width=4)
    draw.rectangle(crop_box, outline=(0, 210, 255), width=3)
    debug_path = debug_dir / f"{int(row['image_id']):04d}_{safe_roi}_debug.jpg"
    debug.save(debug_path, quality=92)
    return crop_path, debug_path, crop_box


def _visible_patient_side(row: dict[str, Any], all_rows: list[dict[str, Any]]) -> str:
    rule = _visible_side_rule(row, all_rows)
    if rule in {"path_right_single_roi", "path_left_single_roi"}:
        return "右" if rule == "path_right_single_roi" else "左"
    return str(row.get("patient_side") or "")


def _visible_side_rule(row: dict[str, Any], all_rows: list[dict[str, Any]]) -> str:
    image_id = int(row["image_id"])
    same_image = [item for item in all_rows if int(item["image_id"]) == image_id]
    path = str(row.get("image_path") or "")
    if len(same_image) == 1:
        if "右髋" in path and "左髋" not in path:
            return "path_right_single_roi"
        if "左髋" in path and "右髋" not in path:
            return "path_left_single_roi"
    return "roi_ap_flip_or_multiroi"


def _parse_model_json(raw_text: str) -> dict[str, Any]:
    text = _clean_model_text(raw_text)
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("model JSON is not an object")
    return payload


def _clean_model_text(raw_text: str) -> str:
    return (
        raw_text.replace("\u200b", "")
        .replace("\ufeff", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .strip()
    )


def _normalize_stage(value: Any) -> str | None:
    text = str(value or "").strip()
    replacements = {
        "I-II": "I/II",
        "I/Ⅱ": "I/II",
        "Ⅰ/Ⅱ": "I/II",
        "ARCO I/II": "I/II",
        "ARCO III+": "III+",
        "III": "III+",
        "IV": "III+",
        "正常": "normal",
        "阴性": "normal",
    }
    text = replacements.get(text, text)
    return text if text in STAGE_VALUES else None


def _stage_from_findings(payload: dict[str, Any]) -> str:
    findings = {str(item) for item in payload.get("findings") or []}
    if findings & {"subchondral_fracture", "collapse"}:
        return "III+"
    if findings & {"sclerotic_band", "cystic_change", "mixed_density_region", "trabecular_blurring"}:
        return "I/II"
    return "normal"


def _binary(stage: Any) -> str | None:
    normalized = _normalize_stage(stage)
    if normalized is None:
        return None
    return "normal" if normalized == "normal" else "ONFH"


def _dedupe_roi_results_for_metrics(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Multiple Xray views can show the same patient side. For side-level metrics, keep
    # the max-severity VLM prediction per patient side so one patient side is counted once.
    best: dict[tuple[str, str], dict[str, Any]] = {}
    severity = {"normal": 0, "I/II": 1, "III+": 2}
    for row in results:
        key = (str(row["patient_key"]), str(row["patient_side"]))
        current = best.get(key)
        if current is None or severity.get(str(row.get("pred_stage")), -1) > severity.get(
            str(current.get("pred_stage")), -1
        ):
            best[key] = dict(row)
    return list(best.values())


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluable = [row for row in rows if row.get("gt_mri_stage") in STAGE_VALUES]
    correct_stage = [row for row in evaluable if row.get("correct_stage")]
    correct_binary = [row for row in evaluable if row.get("correct_binary")]
    confusion: dict[str, dict[str, int]] = {}
    binary_confusion = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    for row in evaluable:
        gt_stage = str(row.get("gt_mri_stage"))
        pred_stage = str(row.get("pred_stage"))
        confusion.setdefault(gt_stage, {})
        confusion[gt_stage][pred_stage] = confusion[gt_stage].get(pred_stage, 0) + 1
        gt_bin = row.get("gt_binary")
        pred_bin = row.get("pred_binary")
        if gt_bin == "ONFH" and pred_bin == "ONFH":
            binary_confusion["TP"] += 1
        elif gt_bin == "normal" and pred_bin == "ONFH":
            binary_confusion["FP"] += 1
        elif gt_bin == "normal" and pred_bin == "normal":
            binary_confusion["TN"] += 1
        elif gt_bin == "ONFH" and pred_bin == "normal":
            binary_confusion["FN"] += 1
    tp, fp, tn, fn = (
        binary_confusion["TP"],
        binary_confusion["FP"],
        binary_confusion["TN"],
        binary_confusion["FN"],
    )
    return {
        "roi_component_predictions": len(rows),
        "evaluable_visible_side_cases": len(evaluable),
        "stage_correct": len(correct_stage),
        "stage_accuracy": len(correct_stage) / len(evaluable) if evaluable else None,
        "stage_confusion": confusion,
        "binary_normal_vs_onfh": {
            **binary_confusion,
            "accuracy": len(correct_binary) / len(evaluable) if evaluable else None,
            "onfh_precision": tp / (tp + fp) if (tp + fp) else None,
            "onfh_recall": tp / (tp + fn) if (tp + fn) else None,
            "specificity": tn / (tn + fp) if (tn + fp) else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else None,
        },
    }


def _metrics_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope, payload in metrics.items():
        binary = payload.get("binary_normal_vs_onfh") or {}
        rows.extend(
            [
                {"scope": scope, "metric": "stage_accuracy", "value": payload.get("stage_accuracy")},
                {"scope": scope, "metric": "stage_correct", "value": payload.get("stage_correct")},
                {
                    "scope": scope,
                    "metric": "evaluable_visible_side_cases",
                    "value": payload.get("evaluable_visible_side_cases"),
                },
                {"scope": scope, "metric": "binary_accuracy", "value": binary.get("accuracy")},
                {"scope": scope, "metric": "binary_onfh_precision", "value": binary.get("onfh_precision")},
                {"scope": scope, "metric": "binary_onfh_recall", "value": binary.get("onfh_recall")},
                {"scope": scope, "metric": "binary_specificity", "value": binary.get("specificity")},
                {"scope": scope, "metric": "binary_f1", "value": binary.get("f1")},
                {"scope": scope, "metric": "binary_TP", "value": binary.get("TP")},
                {"scope": scope, "metric": "binary_FP", "value": binary.get("FP")},
                {"scope": scope, "metric": "binary_TN", "value": binary.get("TN")},
                {"scope": scope, "metric": "binary_FN", "value": binary.get("FN")},
            ]
        )
    return rows


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_existing_results(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        result[str(row["roi_component_id"])] = row
    return result


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value).strip("_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate ONFH Xray with real VLM on femoral-head ROI crops."
    )
    parser.add_argument("--roi-dir", type=Path, default=DEFAULT_ROI_DIR)
    parser.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--force", action="store_true", help="Ignore existing jsonl predictions.")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument(
        "--blinded-prompt",
        action="store_true",
        help="Do not send patient/path/side metadata to VLM; image crop only plus generic instructions.",
    )
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
        max_retries=args.max_retries,
        blinded_prompt=args.blinded_prompt,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
