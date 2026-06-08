from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_SUMMARY_DIR = Path("output/fake/onfh_eval_summary_20260608")
DEFAULT_MOCK_ROI_AGENT_DIR = Path("output/fake/onfh_mock_roi_diagnosis_agent_eval_20260608")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    roi_wide = pd.read_csv(args.roi_wide_csv).fillna("")
    mock_agent_roi = pd.read_csv(args.mock_roi_agent_metrics_csv).fillna("")
    mock_agent_patient = pd.read_csv(args.mock_roi_agent_patient_metrics_csv).fillna("")

    rows = [
        _row_roi_setting(
            setting="roi_crop_blinded",
            input_scope="roi_crop_blinded",
            standalone=_metrics_from_roi_wide(roi_wide, "onfh_coco_roi_crop_real_visual_eval_blinded"),
            agent=_metrics_from_roi_wide(roi_wide, "onfh_roi_formal_service_blinded_eval"),
            reference=_metrics_from_roi_wide(roi_wide, "mock_gt_mask"),
            notes="Main ROI comparison: blinded standalone VLM vs blinded formal service/agent.",
        ),
        _row_roi_setting(
            setting="combined_gtmask_roi_vlm",
            input_scope="roi_crop_plus_gt_mask",
            standalone={},
            agent=_metrics_from_roi_wide(roi_wide, "combined_gtmask_roi_vlm"),
            reference=_metrics_from_roi_wide(roi_wide, "mock_gt_mask"),
            notes="Formal agent using both ROI/VLM visual evidence and doctor GT-mask mock evidence.",
        ),
        _row_mock_gt_mask_setting(mock_agent_roi, mock_agent_patient),
    ]

    detailed = pd.DataFrame(rows)
    detailed_csv = args.output_dir / "onfh_experiment_summary_final_detailed_20260608.csv"
    detailed.to_csv(detailed_csv, index=False)

    brief_cols = [
        "setting",
        "input_scope",
        "standalone_vlm_roi_stage_acc",
        "standalone_vlm_roi_binary_acc",
        "agent_roi_stage_acc",
        "agent_roi_binary_acc",
        "agent_roi_coverage",
        "mock_gt_mask_direct_roi_stage_acc",
        "mock_gt_mask_direct_roi_binary_acc",
        "mock_gt_mask_agent_final_roi_stage_acc",
        "mock_gt_mask_agent_final_roi_coverage",
        "mock_gt_mask_agent_candidate_roi_stage_acc",
        "agent_patient_side_stage_acc",
        "agent_patient_side_binary_acc",
        "agent_patient_side_coverage",
        "notes",
    ]
    brief = detailed.reindex(columns=brief_cols)
    brief_csv = args.output_dir / "onfh_experiment_summary_final_brief_20260608.csv"
    brief.to_csv(brief_csv, index=False)

    print(f"wrote detailed: {detailed_csv}")
    print(f"wrote brief: {brief_csv}")
    print(detailed[["setting", "input_scope"]].to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build final ONFH experiment summary tables.")
    parser.add_argument(
        "--roi-wide-csv",
        type=Path,
        default=DEFAULT_SUMMARY_DIR / "onfh_roi_experiment_summary_wide_20260608.csv",
    )
    parser.add_argument(
        "--mock-roi-agent-metrics-csv",
        type=Path,
        default=DEFAULT_MOCK_ROI_AGENT_DIR / "mock_roi_diagnosis_agent_metrics.csv",
    )
    parser.add_argument(
        "--mock-roi-agent-patient-metrics-csv",
        type=Path,
        default=DEFAULT_MOCK_ROI_AGENT_DIR / "mock_roi_diagnosis_agent_patient_side_metrics.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_SUMMARY_DIR)
    return parser.parse_args()


def _row_roi_setting(
    *,
    setting: str,
    input_scope: str,
    standalone: dict[str, Any],
    agent: dict[str, Any],
    reference: dict[str, Any],
    notes: str,
) -> dict[str, Any]:
    row = {"setting": setting, "input_scope": input_scope, "notes": notes}
    _add_prefix(row, "standalone_vlm", standalone)
    _add_prefix(row, "agent", agent)
    _add_prefix(row, "mock_gt_mask_direct", reference)
    return row


def _row_mock_gt_mask_setting(
    mock_agent_roi: pd.DataFrame,
    mock_agent_patient: pd.DataFrame,
) -> dict[str, Any]:
    direct_roi = _metrics_from_long(mock_agent_roi, "mock_mask_stage")
    final_roi = _metrics_from_long(mock_agent_roi, "diagnosis_agent_stage")
    candidate_roi = _metrics_from_long(mock_agent_roi, "diagnosis_agent_candidate_stage")
    direct_patient = _metrics_from_long(mock_agent_patient, "mock_mask_stage")
    final_patient = _metrics_from_long(mock_agent_patient, "diagnosis_agent_stage")
    candidate_patient = _metrics_from_long(mock_agent_patient, "diagnosis_agent_candidate_stage")

    row = {
        "setting": "mock_gt_mask",
        "input_scope": "roi_crop_gt_mask_mock",
        "notes": (
            "Direct is stage derived from doctor GT masks; agent_final is conservative final "
            "diagnosis and abstains here; agent_candidate is the candidate stage exposed inside "
            "the diagnosis agent."
        ),
    }
    _add_prefix(row, "mock_gt_mask_direct", _combine_scopes(direct_roi, direct_patient))
    _add_prefix(row, "mock_gt_mask_agent_final", _combine_scopes(final_roi, final_patient))
    _add_prefix(row, "mock_gt_mask_agent_candidate", _combine_scopes(candidate_roi, candidate_patient))
    return row


def _metrics_from_roi_wide(df: pd.DataFrame, experiment: str) -> dict[str, Any]:
    row = _one(df[df["experiment"] == experiment])
    if not row:
        return {}
    return {
        "roi_total": _value(row, "roi_visible_side_total"),
        "roi_stage_acc": _value(row, "roi_visible_side_stage_accuracy"),
        "roi_binary_acc": _value(row, "roi_visible_side_binary_accuracy"),
        "roi_precision": _value(row, "roi_visible_side_binary_onfh_precision"),
        "roi_recall": _value(row, "roi_visible_side_binary_onfh_recall"),
        "roi_f1": _value(row, "roi_visible_side_binary_f1"),
        "patient_side_total": _value(row, "patient_side_dedup_total"),
        "patient_side_stage_acc": _value(row, "patient_side_dedup_stage_accuracy"),
        "patient_side_binary_acc": _value(row, "patient_side_dedup_binary_accuracy"),
        "patient_side_precision": _value(row, "patient_side_dedup_binary_onfh_precision"),
        "patient_side_recall": _value(row, "patient_side_dedup_binary_onfh_recall"),
        "patient_side_f1": _value(row, "patient_side_dedup_binary_f1"),
    }


def _metrics_from_long(df: pd.DataFrame, prediction: str) -> dict[str, Any]:
    row = _one(df[df["prediction"] == prediction])
    if not row:
        return {}
    return {
        "total": _value(row, "total"),
        "stage_acc": _value(row, "stage_accuracy"),
        "stage_acc_non_abstain": _value(row, "stage_accuracy_non_abstain"),
        "binary_acc": _value(row, "binary_accuracy"),
        "precision": _value(row, "binary_onfh_precision"),
        "recall": _value(row, "binary_onfh_recall"),
        "f1": _value(row, "binary_f1"),
        "coverage": _value(row, "coverage_rate"),
        "abstain": _value(row, "abstain_count"),
    }


def _combine_scopes(roi: dict[str, Any], patient: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in roi.items():
        out[f"roi_{key}"] = value
    for key, value in patient.items():
        out[f"patient_side_{key}"] = value
    return out


def _add_prefix(row: dict[str, Any], prefix: str, metrics: dict[str, Any]) -> None:
    for key, value in metrics.items():
        row[f"{prefix}_{key}"] = value


def _one(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def _value(row: dict[str, Any], key: str) -> Any:
    value = row.get(key, "")
    if pd.isna(value):
        return ""
    return value


if __name__ == "__main__":
    main()
