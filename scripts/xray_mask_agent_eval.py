from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.candidate_diagnosis_agent import CandidateDiagnosisAgent
from llm.model_client import OpenAICompatibleModelClient
from llm.prompt_runner import PromptRunner
from tools.skill_builder_tool import SkillBuilderTool


STAGES = {"normal", "I/II", "III+"}
ABSTAIN_STAGE = "evidence_insufficient"
REPORTABLE_STAGES = STAGES | {ABSTAIN_STAGE}
XRAY_STAGES = {"normal", "II", "III"}


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows_df = pd.read_csv(args.mock_roi_rows_csv).fillna("")
    normalizer = _normalizer_for_schema(args.stage_schema)
    agent = _build_agent(use_prompt_runner=args.use_prompt_runner, timeout_seconds=args.llm_timeout_seconds)
    disease_skill = SkillBuilderTool().load_guideline_skill("femoral_head_necrosis")

    rows: list[dict[str, Any]] = []
    source_rows = rows_df.to_dict(orient="records")
    if args.limit is not None:
        source_rows = source_rows[: args.limit]

    for source_row in source_rows:
        visual_result = _visual_result_from_row(source_row)
        patient_info = {
            "patient_id": source_row.get("patient_key"),
            "patient_side": source_row.get("patient_side"),
        }
        if args.lite:
            report = agent.generate_lite_report(
                case_id=str(source_row.get("roi_component_id") or source_row.get("case_id") or ""),
                patient_info=patient_info,
                findings=_findings_for_stage_schema(
                    source_row=source_row,
                    visual_result=visual_result,
                    stage_schema=args.stage_schema,
                ),
                modality=str(visual_result.get("modality") or "xray"),
                stage_schema=args.stage_schema,
            )
        else:
            report = agent.generate_report(
                case_id=str(source_row.get("roi_component_id") or source_row.get("case_id") or ""),
                patient_info=patient_info,
                visual_result=visual_result,
                disease_skill=disease_skill,
                stage_schema=args.stage_schema,
                final_stage_mode=args.final_stage_mode,
            )
        agent_dx = report.get("onfh_agent_diagnosis") or {}
        visual_model = report.get("onfh_visual_model_result") or {}
        gt_stage = normalizer(source_row.get(args.gt_stage_column))
        rows.append(
            {
                "roi_component_id": source_row.get("roi_component_id"),
                "case_id": source_row.get("case_id"),
                "image_id": source_row.get("image_id"),
                "patient_key": source_row.get("patient_key"),
                "patient_side": source_row.get("patient_side"),
                "crop_path": source_row.get("crop_path"),
                "gt_mri_stage": gt_stage,
                "gt_stage_column": args.gt_stage_column,
                "stage_schema": args.stage_schema,
                "final_stage_mode": args.final_stage_mode,
                "xray_tag_stage": source_row.get("xray_tag_stage"),
                "xray_tag_labels": source_row.get("xray_tag_labels"),
                "mock_mask_stage": normalizer(source_row.get("pred_stage_from_mock_mask")),
                "visual_model_stage": normalizer(visual_model.get("stage")),
                "diagnosis_agent_stage": normalizer(agent_dx.get("stage")),
                "diagnosis_agent_candidate_stage": normalizer(agent_dx.get("candidate_stage")),
                "diagnosis_agent_abstained": bool(agent_dx.get("abstained")),
                "diagnosis_agent_confidence": agent_dx.get("confidence"),
                "diagnosis_agent_uncertainty_status": agent_dx.get("uncertainty_status"),
                "diagnosis_agent_report_stage_text": agent_dx.get("report_stage_text"),
                "diagnosis_agent_diagnostic_tendency": agent_dx.get("diagnostic_tendency"),
                "lite_mode": bool(report.get("lite_mode")),
                "basis_targets": "|".join(visual_model.get("basis_targets") or []),
                "basis_text": "|".join(visual_model.get("basis_text") or [])[:1000],
                "mock_xray_targets": source_row.get("mock_xray_targets"),
                "mock_xray_labels": source_row.get("mock_xray_labels"),
                "mock_xray_instance_count": source_row.get("mock_xray_instance_count"),
                "mock_mask_stage_correct": normalizer(source_row.get("pred_stage_from_mock_mask")) == gt_stage,
                "visual_model_stage_correct": normalizer(visual_model.get("stage")) == gt_stage,
                "diagnosis_agent_stage_correct": normalizer(agent_dx.get("stage")) == gt_stage,
                "diagnosis_agent_candidate_stage_correct": normalizer(
                    agent_dx.get("candidate_stage")
                )
                == gt_stage,
                "report_json": json.dumps(report, ensure_ascii=False),
            }
        )

    out_rows = pd.DataFrame(rows)
    rows_csv = args.output_dir / "mock_roi_diagnosis_agent_rows.csv"
    out_rows.to_csv(rows_csv, index=False)

    metrics_df = _metrics_table(out_rows, normalizer=normalizer)
    metrics_csv = args.output_dir / "mock_roi_diagnosis_agent_metrics.csv"
    metrics_df.to_csv(metrics_csv, index=False)

    patient_rows, patient_metrics = _patient_side_tables(out_rows, normalizer=normalizer)
    patient_rows_csv = args.output_dir / "mock_roi_diagnosis_agent_patient_side_rows.csv"
    patient_metrics_csv = args.output_dir / "mock_roi_diagnosis_agent_patient_side_metrics.csv"
    patient_rows.to_csv(patient_rows_csv, index=False)
    patient_metrics.to_csv(patient_metrics_csv, index=False)

    summary = {
        "status": "ok",
        "mode": "mock_roi_diagnosis_agent_eval",
        "lite_mode": bool(args.lite),
        "use_prompt_runner": bool(args.use_prompt_runner),
        "stage_schema": args.stage_schema,
        "final_stage_mode": args.final_stage_mode,
        "gt_stage_column": args.gt_stage_column,
        "mock_roi_rows_csv": str(args.mock_roi_rows_csv),
        "output_dir": str(args.output_dir),
        "rows_csv": str(rows_csv),
        "metrics_csv": str(metrics_csv),
        "patient_side_rows_csv": str(patient_rows_csv),
        "patient_side_metrics_csv": str(patient_metrics_csv),
        "metrics": metrics_df.to_dict(orient="records"),
        "patient_side_metrics": patient_metrics.to_dict(orient="records"),
    }
    summary_path = args.output_dir / "summary.json"
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run diagnosis agent on mock GT-mask ROI evidence.")
    parser.add_argument(
        "--mock-roi-rows-csv",
        type=Path,
        default=Path("output/fake/onfh_mock_roi_level_eval_20260608/mock_roi_side_rows.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/fake/onfh_mock_roi_diagnosis_agent_eval_20260608"),
    )
    parser.add_argument(
        "--lite",
        action="store_true",
        help="Use findings-only CandidateDiagnosisAgent lite mode instead of the full base report path.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--use-prompt-runner",
        action="store_true",
        help="Inject PromptRunner(OpenAICompatibleModelClient) for full mode. Lite mode remains local findings-only.",
    )
    parser.add_argument("--llm-timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--stage-schema",
        choices=["mri_arco_3class", "xray_arco_3class"],
        default="mri_arco_3class",
    )
    parser.add_argument(
        "--gt-stage-column",
        choices=["gt_mri_stage", "xray_tag_stage"],
        default="gt_mri_stage",
    )
    parser.add_argument(
        "--final-stage-mode",
        choices=["conservative", "llm_final"],
        default="conservative",
        help="Only affects full mode. llm_final scores provisional stages parsed from the full diagnosis report.",
    )
    return parser.parse_args()


def _build_agent(*, use_prompt_runner: bool, timeout_seconds: int) -> CandidateDiagnosisAgent:
    if not use_prompt_runner:
        return CandidateDiagnosisAgent()
    return CandidateDiagnosisAgent(
        prompt_runner=PromptRunner(
            model_client=OpenAICompatibleModelClient(
                timeout_seconds=timeout_seconds,
                responses_stream=True,
            )
        )
    )


def _visual_result_from_row(row: dict[str, Any]) -> dict[str, Any]:
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
            "visualization_path": str(row.get("overlay_path") or image_path),
        },
        "requested_targets": sorted({finding["target"] for finding in findings}),
        "visual_evidence": {
            "femoral_head_shape": "未评估",
            "collapse": any(f["target"] in {"collapse", "subchondral_fracture"} for f in findings),
            "sclerosis": any(f["target"] == "sclerotic_band" for f in findings),
            "cystic_change": any(f["target"] == "cystic_change" for f in findings),
            "joint_space_narrowing": False,
            "joint_space": "未评估",
            "lesion_mask": str(row.get("mask_path") or "mock_gt_mask"),
            "confidence": 1.0 if findings else 0.0,
            "texture_abnormality_score": 0.0,
            "lesion_area_ratio": _float(row.get("mock_xray_side_area_ratio")),
            "collapse_ratio": 0.0,
            "joint_space_width": "unknown",
            "lesion_detected": bool(findings),
            "lesion_location": str(row.get("patient_side") or "未定位"),
            "segmentation_quality": "reviewed_gt_mask_mock",
            "visual_output_mode": "mock_gt_mask_roi",
            "segmentation_status": "completed" if findings else "no_same_side_mock_mask",
            "suspected_visual_findings": suspected,
            "disease_target": "femoral_head_necrosis",
            "measurements": {
                "patient_side": row.get("patient_side"),
                "roi_component_id": row.get("roi_component_id"),
                "mock_xray_side_area_px": _float(row.get("mock_xray_side_area_px")),
                "mock_xray_side_area_ratio": _float(row.get("mock_xray_side_area_ratio")),
            },
            "findings": findings,
            "structured_visual_facts": findings,
        },
    }


def _findings_for_stage_schema(
    *,
    source_row: dict[str, Any],
    visual_result: dict[str, Any],
    stage_schema: str,
) -> list[dict[str, Any]]:
    findings = list((visual_result.get("visual_evidence") or {}).get("findings") or [])
    if findings or stage_schema != "xray_arco_3class":
        return findings
    if _normalize_xray_stage(source_row.get("xray_tag_stage")) != "normal":
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


def _metrics_table(rows_df: pd.DataFrame, *, normalizer=None) -> pd.DataFrame:
    normalizer = normalizer or _normalize_stage
    rows = []
    for field in [
        "mock_mask_stage",
        "visual_model_stage",
        "diagnosis_agent_stage",
        "diagnosis_agent_candidate_stage",
    ]:
        rows.append({"scope": "roi_visible_side", "prediction": field, **_metrics(rows_df, field, normalizer=normalizer)})
    return pd.DataFrame(rows)


def _patient_side_tables(
    rows_df: pd.DataFrame,
    *,
    normalizer=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalizer = normalizer or _normalize_stage
    records = []
    for (patient_key, patient_side), group in rows_df.groupby(["patient_key", "patient_side"]):
        record = {
            "patient_key": patient_key,
            "patient_side": patient_side,
            "gt_mri_stage": _max_stage(group["gt_mri_stage"], normalizer=normalizer),
            "source_roi_count": len(group),
            "roi_component_ids": "|".join(str(v) for v in group["roi_component_id"].dropna()),
        }
        for field in [
            "mock_mask_stage",
            "visual_model_stage",
            "diagnosis_agent_stage",
            "diagnosis_agent_candidate_stage",
        ]:
            record[field] = _max_stage(group[field], normalizer=normalizer)
            record[f"{field}_correct"] = record[field] == record["gt_mri_stage"]
        records.append(record)
    patient_rows = pd.DataFrame(records)
    metric_rows = []
    for field in [
        "mock_mask_stage",
        "visual_model_stage",
        "diagnosis_agent_stage",
        "diagnosis_agent_candidate_stage",
    ]:
        metric_rows.append(
            {
                "scope": "patient_side_dedup",
                "prediction": field,
                **_metrics(patient_rows, field, normalizer=normalizer),
            }
        )
    return patient_rows, pd.DataFrame(metric_rows)


def _metrics(rows_df: pd.DataFrame, pred_col: str, *, normalizer=None) -> dict[str, Any]:
    normalizer = normalizer or _normalize_stage
    total = len(rows_df)
    pred = rows_df[pred_col].map(normalizer)
    gt = rows_df["gt_mri_stage"].map(normalizer)
    abstain = pred.eq(ABSTAIN_STAGE)
    covered = ~abstain
    covered_total = int(covered.sum())
    gt_binary = gt.ne("normal")
    pred_binary = pred.ne("normal") & ~abstain
    tp = int((pred_binary & gt_binary).sum())
    fp = int((pred_binary & ~gt_binary).sum())
    tn = int((covered & ~pred_binary & ~gt_binary).sum())
    fn = int((covered & ~pred_binary & gt_binary).sum())
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    covered_stage_correct = int(((pred == gt) & covered).sum())
    return {
        "total": total,
        "abstain_count": int(abstain.sum()),
        "coverage_count": covered_total,
        "coverage_rate": _safe_div(covered_total, total),
        "stage_correct": int((pred == gt).sum()),
        "stage_accuracy": float((pred == gt).mean()) if total else 0.0,
        "stage_accuracy_non_abstain": _safe_div(covered_stage_correct, covered_total),
        "binary_accuracy": _safe_div(tp + tn, covered_total),
        "binary_TP": tp,
        "binary_FP": fp,
        "binary_TN": tn,
        "binary_FN": fn,
        "binary_onfh_precision": precision,
        "binary_onfh_recall": recall,
        "binary_specificity": _safe_div(tn, tn + fp),
        "binary_f1": _safe_div(2 * precision * recall, precision + recall),
        "gt_stage_counts": json.dumps(gt.value_counts().to_dict(), ensure_ascii=False),
        "pred_stage_counts": json.dumps(pred.value_counts().to_dict(), ensure_ascii=False),
    }


def _max_stage(values: Any, *, normalizer=None) -> str:
    normalizer = normalizer or _normalize_stage
    best = ABSTAIN_STAGE
    best_rank = -1
    rank_map = _rank_for_normalizer(normalizer)
    for value in values:
        stage = normalizer(value)
        rank = rank_map.get(stage, -1)
        if rank > best_rank:
            best = stage
            best_rank = rank
    return best


def _normalize_stage(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"normal", "I/II", "III+"}:
        return text
    if "III" in text or "塌陷" in text or "新月" in text or "软骨下" in text:
        return "III+"
    if "I/II" in text or "I /II" in text or "II" in text or "硬化" in text or "囊" in text:
        return "I/II"
    return "normal" if text == "normal" else "evidence_insufficient"


def _normalize_xray_stage(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"normal", "II", "III", "evidence_insufficient"}:
        return text
    if "III" in text or "塌陷" in text or "新月" in text or "软骨下" in text:
        return "III"
    if "I/II" in text or "I /II" in text or "II" in text or "硬化" in text or "囊" in text:
        return "II"
    if text == "normal" or "无明显异常" in text or "未见" in text:
        return "normal"
    return "evidence_insufficient"


def _normalizer_for_schema(stage_schema: str):
    if stage_schema == "xray_arco_3class":
        return _normalize_xray_stage
    return _normalize_stage


def _rank_for_normalizer(normalizer) -> dict[str, int]:
    if normalizer is _normalize_xray_stage:
        return {ABSTAIN_STAGE: -1, "normal": 0, "II": 1, "III": 2}
    return {ABSTAIN_STAGE: -1, "normal": 0, "I/II": 1, "III+": 2}


def _float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _safe_div(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


if __name__ == "__main__":
    main()
