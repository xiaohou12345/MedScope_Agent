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
from scripts.no_mask_vision_prompt_demo import _load_dotenv_local
from scripts.xray_mask_agent_eval import _findings_for_stage_schema, _visual_result_from_row
from scripts.xray_mask_mock_eval import _stage_from_agent_report

DEFAULT_MOCK_ROWS_CSV = Path(
    "output/fake/xray_34tag_side_mock_roi_level_20260609/mock_roi_side_rows.csv"
)
DEFAULT_REAL_VLM_CSV = Path(
    "output/fake/xray_34tag_side_real_vlm_agent_20260609/formal_service_predictions.csv"
)
DEFAULT_OUTPUT_DIR = Path("output/fake/xray_34tag_side_mixed_original_flow_20260609")


class CachedFindingsVisualRunner:
    def __init__(self):
        self.current_findings = []
        self.current_visual_output_mode = "unknown"

    def set_findings(self, findings: list[dict[str, Any]], visual_output_mode: str):
        self.current_findings = findings
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
                    "collapse": bool(positive_targets & {"collapse", "subchondral_fracture", "crescent_sign"}),
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
    return findings


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock-rows-csv", type=Path, default=DEFAULT_MOCK_ROWS_CSV)
    parser.add_argument("--real-vlm-csv", type=Path, default=DEFAULT_REAL_VLM_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--use-llm", action="store_true", help="Use DiagnosisDoctorAgent LLM inference path.")
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

    runner = CachedFindingsVisualRunner()
    
    # Configure diagnosis agent with prompt runner if --use-llm is set
    from agents.diagnosis_agent import DiagnosisDoctorAgent
    from llm.model_client import OpenAICompatibleModelClient
    from llm.prompt_runner import PromptRunner
    
    diag_agent = DiagnosisDoctorAgent(
        prompt_runner=PromptRunner(model_client=OpenAICompatibleModelClient()) if args.use_llm else None
    )
    gao_agent = GaoDoctorAgent(
        no_mask_visual_pipeline_runner=runner,
        diagnosis_agent=diag_agent
    )
    service = MedScopeService(gaodoctor_agent=gao_agent)

    rows = []
    source_rows = mock_df.to_dict(orient="records")
    if args.limit:
        source_rows = source_rows[:args.limit]

    for mock_row in source_rows:
        roi_id = str(mock_row.get("roi_component_id") or "")
        vlm_row = vlm_by_roi.get(roi_id)
        mock_visual = _visual_result_from_row(mock_row)
        mock_findings = _findings_for_stage_schema(
            source_row=mock_row,
            visual_result=mock_visual,
            stage_schema="xray_arco_3class",
        )
        vlm_findings = _vlm_findings_for_side(vlm_row, mock_row) if vlm_row is not None else []
        combined_findings = mock_findings + vlm_findings

        gt_xray_stage = mock_row.get("xray_tag_stage")
        if not gt_xray_stage:
            print(f"Skipping {roi_id} because no xray_tag_stage")
            continue
        
        def _normalize_gt_xray(text: str) -> str:
            if "III" in text or "3期" in text or "三期" in text: return "3期"
            if "II" in text or "2期" in text or "二期" in text or "I/II" in text or "I-II" in text: return "2期"
            return "未发现异常"
        
        gt_xray_stage_norm = _normalize_gt_xray(gt_xray_stage)

        # 1. Real VLM Only
        runner.set_findings(vlm_findings, "real_vlm_roi_findings")
        real_result = service.handle_request({
            "patient_message": "请根据提供的 X光髋关节 ROI 图像特征进行 ONFH 诊断。",
            "image_path": "roi.png",
            "patient_info": {
                "patient_id": mock_row.get("patient_key"),
                "symptoms": ["髋关节疼痛"],
                "source": "xray_roi_real_vlm_cached",
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
        })
        real_report = real_result.get("report") or {}
        
        # 2. Mixed Findings
        runner.set_findings(combined_findings, "mixed_real_vlm_plus_mock_findings")
        mixed_result = service.handle_request({
            "patient_message": "请根据提供的 X光髋关节 ROI 图像特征进行 ONFH 诊断。",
            "image_path": "roi.png",
            "patient_info": {
                "patient_id": mock_row.get("patient_key"),
                "symptoms": ["髋关节疼痛"],
                "source": "xray_roi_mixed_cached",
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
        })
        mixed_report = mixed_result.get("report") or {}

        real_final = _stage_from_agent_report(real_report, loose=False)
        real_loose = _stage_from_agent_report(real_report, loose=True)
        mixed_final = _stage_from_agent_report(mixed_report, loose=False)
        mixed_loose = _stage_from_agent_report(mixed_report, loose=True)

        rows.append({
            "roi_component_id": roi_id,
            "patient_key": mock_row.get("patient_key"),
            "patient_side": mock_row.get("patient_side"),
            "gt_xray_stage": gt_xray_stage_norm,
            "mock_finding_count": len(mock_findings),
            "vlm_finding_count": len(vlm_findings),
            "combined_finding_count": len(combined_findings),

            "real_final": real_final,
            "real_final_correct": bool(real_final == gt_xray_stage_norm),
            "real_final_abstained": real_final == "abstain",

            "real_loose": real_loose,
            "real_loose_correct": bool(real_loose == gt_xray_stage_norm),
            "real_loose_abstained": real_loose == "abstain",

            "mixed_final": mixed_final,
            "mixed_final_correct": bool(mixed_final == gt_xray_stage_norm),
            "mixed_final_abstained": mixed_final == "abstain",

            "mixed_loose": mixed_loose,
            "mixed_loose_correct": bool(mixed_loose == gt_xray_stage_norm),
            "mixed_loose_abstained": mixed_loose == "abstain",
        })

    out_df = pd.DataFrame(rows)
    evaluable = out_df.to_dict(orient="records")

    summary = {
        "side_cases": len(evaluable),
        "real_vlm_final_metrics": _compute_metrics(evaluable, "real_final", "real_final_correct", "real_final_abstained"),
        "real_vlm_loose_metrics": _compute_metrics(evaluable, "real_loose", "real_loose_correct", "real_loose_abstained"),
        "mixed_final_metrics": _compute_metrics(evaluable, "mixed_final", "mixed_final_correct", "mixed_final_abstained"),
        "mixed_loose_metrics": _compute_metrics(evaluable, "mixed_loose", "mixed_loose_correct", "mixed_loose_abstained"),
    }

    out_df.to_csv(args.output_dir / "eval_rows.csv", index=False)
    with open(args.output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
