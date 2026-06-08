from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


STAGE_ORDER = {"normal": 0, "I/II": 1, "III+": 2}


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    instance_df = pd.read_csv(args.mock_dir / "instance_level_visual_outputs.csv")
    side_df = pd.read_csv(args.mock_dir / "side_level_eval.csv")
    roi_index_df = pd.read_csv(args.roi_index_csv)

    instance_df.to_csv(args.output_dir / "mock_roi_instance_rows.csv", index=False)
    roi_side_df = _build_mock_roi_rows(roi_index_df, side_df, instance_df)
    roi_side_df.to_csv(args.output_dir / "mock_roi_side_rows.csv", index=False)

    dedup_df = _dedupe_patient_side(roi_side_df, "pred_stage_from_mock_mask")
    dedup_df.to_csv(args.output_dir / "mock_roi_patient_side_dedup_rows.csv", index=False)

    metrics_rows = []
    metrics_rows.extend(_metric_rows("mock_roi_visible_side", roi_side_df, "pred_stage_from_mock_mask"))
    metrics_rows.extend(
        _metric_rows("mock_patient_side_dedup_max_pred_severity", dedup_df, "pred_stage")
    )
    metrics_df = pd.DataFrame(metrics_rows)
    metrics_df.to_csv(args.output_dir / "mock_roi_metrics_summary.csv", index=False)

    comparison_df = _comparison_summary(args.output_dir, args.roi_eval_dirs)
    comparison_df.to_csv(args.output_dir / "roi_experiment_summary.csv", index=False)

    summary = {
        "status": "ok",
        "mode": "mock_roi_level_eval",
        "mock_dir": str(args.mock_dir),
        "roi_index_csv": str(args.roi_index_csv),
        "output_dir": str(args.output_dir),
        "left_right_source": {
            "mask_side": "instance_level_visual_outputs.csv patient_side, derived from reviewed COCO mask image_side mapping",
            "gt_side": "side_level_eval.csv gt_mri_stage / gt_tag_labels, derived from MRI tags by patient_side",
            "roi_cases": "roi_index_csv rows; same visible femoral-head ROI components as ROI-crop VLM experiments",
        },
        "outputs": {
            "instance_rows_csv": str(args.output_dir / "mock_roi_instance_rows.csv"),
            "side_rows_csv": str(args.output_dir / "mock_roi_side_rows.csv"),
            "patient_side_dedup_rows_csv": str(
                args.output_dir / "mock_roi_patient_side_dedup_rows.csv"
            ),
            "mock_metrics_csv": str(args.output_dir / "mock_roi_metrics_summary.csv"),
            "roi_experiment_summary_csv": str(args.output_dir / "roi_experiment_summary.csv"),
        },
        "mock_metrics": _metrics_summary_dict(metrics_df),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build explicit mock ROI/side-level ONFH evaluation tables."
    )
    parser.add_argument(
        "--mock-dir",
        type=Path,
        default=Path("output/fake/onfh_coco_mock_api_eval_no_mri_gt_visual"),
    )
    parser.add_argument(
        "--roi-index-csv",
        type=Path,
        default=Path("output/fake/onfh_coco_roi_crop_real_visual_eval/roi_side_level_eval.csv"),
        help="The visible femoral-head ROI components used by ROI-crop VLM experiments.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/fake/onfh_mock_roi_level_eval_20260608"),
    )
    parser.add_argument(
        "--roi-eval-dir",
        dest="roi_eval_dirs",
        type=Path,
        action="append",
        default=[
            Path("output/fake/onfh_coco_roi_crop_real_visual_eval"),
            Path("output/fake/onfh_coco_roi_crop_real_visual_eval_blinded"),
            Path("output/fake/onfh_roi_formal_service_blinded_eval"),
        ],
    )
    return parser.parse_args()


def _build_mock_roi_rows(
    roi_index_df: pd.DataFrame,
    side_df: pd.DataFrame,
    instance_df: pd.DataFrame,
) -> pd.DataFrame:
    side_lookup = {
        (int(row["image_id"]), str(row["patient_side"])): row
        for _, row in side_df.iterrows()
    }
    rows: list[dict[str, Any]] = []
    for _, roi in roi_index_df.iterrows():
        image_id = int(roi["image_id"])
        patient_side = str(roi["patient_side"])
        side_row = side_lookup.get((image_id, patient_side))
        inst = instance_df[
            (pd.to_numeric(instance_df["image_id"], errors="coerce") == image_id)
            & (instance_df["patient_side"].astype(str) == patient_side)
        ].copy()
        pred_stage = _normalize_stage(
            side_row.get("pred_stage_from_xray_mask", "normal")
            if isinstance(side_row, pd.Series)
            else "normal"
        )
        gt_stage = _normalize_stage(roi.get("gt_mri_stage"))
        rows.append(
            {
                "roi_component_id": roi.get("roi_component_id"),
                "case_id": side_row.get("case_id", "") if isinstance(side_row, pd.Series) else "",
                "image_id": image_id,
                "patient_key": roi.get("patient_key"),
                "patient_side": patient_side,
                "original_roi_patient_side": roi.get("original_roi_patient_side"),
                "image_side": roi.get("image_side"),
                "visible_side_rule": roi.get("visible_side_rule"),
                "image_path": roi.get("image_path"),
                "crop_path": roi.get("crop_path"),
                "debug_overlay_path": roi.get("debug_overlay_path"),
                "crop_box_x1": roi.get("crop_box_x1"),
                "crop_box_y1": roi.get("crop_box_y1"),
                "crop_box_x2": roi.get("crop_box_x2"),
                "crop_box_y2": roi.get("crop_box_y2"),
                "roi_bbox_x1": roi.get("roi_bbox_x1"),
                "roi_bbox_y1": roi.get("roi_bbox_y1"),
                "roi_bbox_x2": roi.get("roi_bbox_x2"),
                "roi_bbox_y2": roi.get("roi_bbox_y2"),
                "gt_mri_stage": gt_stage,
                "gt_stage_values": roi.get("gt_stage_values"),
                "gt_tag_labels": roi.get("gt_tag_labels"),
                "gt_frame_count": roi.get("gt_frame_count"),
                "pred_stage_from_mock_mask": pred_stage,
                "correct_stage": pred_stage == gt_stage,
                "pred_binary": _binary(pred_stage),
                "gt_binary": _binary(gt_stage),
                "correct_binary": _binary(pred_stage) == _binary(gt_stage),
                "has_mock_side_mask": bool(
                    side_row.get("has_xray_side_mask", False)
                    if isinstance(side_row, pd.Series)
                    else False
                ),
                "mock_xray_targets": side_row.get("xray_targets", "")
                if isinstance(side_row, pd.Series)
                else "",
                "mock_xray_labels": side_row.get("xray_labels", "")
                if isinstance(side_row, pd.Series)
                else "",
                "mock_xray_instance_count": int(len(inst)),
                "mock_xray_side_area_px": float(inst["area_px"].fillna(0).sum())
                if not inst.empty
                else 0.0,
                "mock_xray_side_area_ratio": float(inst["area_ratio_in_image"].fillna(0).sum())
                if not inst.empty
                else 0.0,
                "mock_annotation_ids": "|".join(str(int(v)) for v in inst["annotation_id"].dropna()),
                "mock_finding_ids": "|".join(str(v) for v in inst["finding_id"].dropna()),
                "mock_instance_targets": _pipe_union(inst.get("target", pd.Series(dtype=str))),
                "mock_instance_labels": _pipe_union(inst.get("label", pd.Series(dtype=str))),
                "mask_path": side_row.get("mask_path", "") if isinstance(side_row, pd.Series) else "",
                "overlay_path": side_row.get("overlay_path", "")
                if isinstance(side_row, pd.Series)
                else "",
            }
        )
    return pd.DataFrame(rows)


def _dedupe_patient_side(side_df: pd.DataFrame, pred_col: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (patient_key, patient_side), group in side_df.groupby(["patient_key", "patient_side"]):
        pred_stage = _max_stage(group[pred_col])
        gt_stage = _max_stage(group["gt_mri_stage"])
        rows.append(
            {
                "patient_key": patient_key,
                "patient_side": patient_side,
                "pred_stage": pred_stage,
                "gt_mri_stage": gt_stage,
                "correct": pred_stage == gt_stage,
                "source_side_row_count": len(group),
                "image_ids": "|".join(str(int(v)) for v in group["image_id"].dropna().unique()),
                "case_ids": "|".join(str(v) for v in group["case_id"].dropna().unique()),
                "has_any_xray_side_mask": bool(group["has_mock_side_mask"].fillna(False).any()),
                "xray_targets_union": _pipe_union(
                    group.get("mock_xray_targets", pd.Series(dtype=str))
                ),
                "gt_tag_labels_union": _pipe_union(group.get("gt_tag_labels", pd.Series(dtype=str))),
                "max_xray_side_area_ratio": float(
                    pd.to_numeric(group["mock_xray_side_area_ratio"], errors="coerce")
                    .fillna(0)
                    .max()
                ),
            }
        )
    return pd.DataFrame(rows)


def _max_stage(values: Any) -> str:
    best = "normal"
    best_rank = -1
    for value in values:
        stage = _normalize_stage(value)
        rank = STAGE_ORDER.get(stage, -1)
        if rank > best_rank:
            best = stage
            best_rank = rank
    return best


def _normalize_stage(value: Any) -> str:
    text = str(value or "").strip()
    if text in STAGE_ORDER:
        return text
    if "III" in text or "塌陷" in text or "新月" in text or "软骨下" in text:
        return "III+"
    if "I/II" in text or "I /II" in text or "II" in text or "硬化" in text or "囊" in text:
        return "I/II"
    return "normal"


def _binary(stage: str) -> str:
    return "ONFH" if _normalize_stage(stage) != "normal" else "normal"


def _pipe_union(values: pd.Series) -> str:
    items: list[str] = []
    for value in values.fillna(""):
        for item in str(value).split("|"):
            item = item.strip()
            if item and item not in items:
                items.append(item)
    return "|".join(items)


def _metric_rows(scope: str, df: pd.DataFrame, pred_col: str) -> list[dict[str, Any]]:
    evaluable = df[df["gt_mri_stage"].map(_normalize_stage).isin(STAGE_ORDER)].copy()
    total = len(evaluable)
    if total == 0:
        return [{"scope": scope, "metric": "total", "value": 0}]

    pred = evaluable[pred_col].map(_normalize_stage)
    gt = evaluable["gt_mri_stage"].map(_normalize_stage)
    stage_correct = int((pred == gt).sum())
    pred_binary = pred.ne("normal")
    gt_binary = gt.ne("normal")
    tp = int((pred_binary & gt_binary).sum())
    fp = int((pred_binary & ~gt_binary).sum())
    tn = int((~pred_binary & ~gt_binary).sum())
    fn = int((~pred_binary & gt_binary).sum())
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    specificity = _safe_div(tn, tn + fp)
    f1 = _safe_div(2 * precision * recall, precision + recall)

    confusion = _confusion(pred, gt)
    return [
        {"scope": scope, "metric": "total", "value": total},
        {"scope": scope, "metric": "stage_correct", "value": stage_correct},
        {"scope": scope, "metric": "stage_accuracy", "value": _safe_div(stage_correct, total)},
        {"scope": scope, "metric": "binary_accuracy", "value": _safe_div(tp + tn, total)},
        {"scope": scope, "metric": "binary_TP", "value": tp},
        {"scope": scope, "metric": "binary_FP", "value": fp},
        {"scope": scope, "metric": "binary_TN", "value": tn},
        {"scope": scope, "metric": "binary_FN", "value": fn},
        {"scope": scope, "metric": "binary_onfh_precision", "value": precision},
        {"scope": scope, "metric": "binary_onfh_recall", "value": recall},
        {"scope": scope, "metric": "binary_specificity", "value": specificity},
        {"scope": scope, "metric": "binary_f1", "value": f1},
        {
            "scope": scope,
            "metric": "gt_stage_counts",
            "value": json.dumps(gt.value_counts().to_dict(), ensure_ascii=False),
        },
        {
            "scope": scope,
            "metric": "pred_stage_counts",
            "value": json.dumps(pred.value_counts().to_dict(), ensure_ascii=False),
        },
        {
            "scope": scope,
            "metric": "stage_confusion",
            "value": json.dumps(confusion, ensure_ascii=False),
        },
    ]


def _confusion(pred: pd.Series, gt: pd.Series) -> dict[str, dict[str, int]]:
    payload: dict[str, dict[str, int]] = {}
    for gt_stage, pred_stage in zip(gt, pred, strict=False):
        payload.setdefault(str(gt_stage), {})
        payload[str(gt_stage)][str(pred_stage)] = payload[str(gt_stage)].get(str(pred_stage), 0) + 1
    return payload


def _safe_div(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def _metrics_summary_dict(metrics_df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for _, row in metrics_df.iterrows():
        summary.setdefault(str(row["scope"]), {})[str(row["metric"])] = row["value"]
    return summary


def _comparison_summary(output_dir: Path, roi_eval_dirs: list[Path]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    mock_metrics = pd.read_csv(output_dir / "mock_roi_metrics_summary.csv")
    for scope in mock_metrics["scope"].drop_duplicates():
        rows.append(_comparison_row(f"mock::{scope}", mock_metrics[mock_metrics["scope"] == scope]))

    for roi_dir in roi_eval_dirs:
        metrics_path = roi_dir / "metrics_summary.csv"
        if not metrics_path.exists():
            continue
        metrics_df = pd.read_csv(metrics_path)
        for scope in metrics_df["scope"].drop_duplicates():
            rows.append(_comparison_row(f"{roi_dir.name}::{scope}", metrics_df[metrics_df["scope"] == scope]))
    return pd.DataFrame(rows)


def _comparison_row(name: str, metrics_df: pd.DataFrame) -> dict[str, Any]:
    values = {str(row["metric"]): row["value"] for _, row in metrics_df.iterrows()}
    return {
        "experiment_scope": name,
        "total": values.get("total") or values.get("evaluable_visible_side_cases"),
        "stage_accuracy": values.get("stage_accuracy"),
        "stage_correct": values.get("stage_correct"),
        "binary_accuracy": values.get("binary_accuracy"),
        "binary_onfh_precision": values.get("binary_onfh_precision"),
        "binary_onfh_recall": values.get("binary_onfh_recall"),
        "binary_specificity": values.get("binary_specificity"),
        "binary_f1": values.get("binary_f1"),
        "binary_TP": values.get("binary_TP"),
        "binary_FP": values.get("binary_FP"),
        "binary_TN": values.get("binary_TN"),
        "binary_FN": values.get("binary_FN"),
        "gt_stage_counts": values.get("gt_stage_counts"),
        "pred_stage_counts": values.get("pred_stage_counts"),
        "stage_confusion": values.get("stage_confusion"),
    }


if __name__ == "__main__":
    main()
