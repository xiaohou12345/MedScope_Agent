from __future__ import annotations

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

from agents.gaodoctor_agent import GaoDoctorAgent
from api.service import MedScopeService
from scripts.xray_mask_mock_eval import (
    DEFAULT_EXPORT_DIR,
    OnfhCocoMockVisualRunner,
    _build_instance_level_visual_outputs,
    _build_side_level_eval,
    _side_level_metrics,
)
from tools.structured_visual_fact_builder import build_structured_visual_facts


DEFAULT_ROI_VLM_CSV = Path(
    "output/fake/onfh_roi_formal_service_blinded_eval/formal_service_predictions.csv"
)
DEFAULT_OUTPUT_DIR = Path("output/fake/onfh_combined_gtmask_roi_vlm_service_eval")


class CombinedGtMaskRoiVlmRunner:
    """Use doctor Xray masks plus cached real ROI-VLM findings as one visual output."""

    def __init__(
        self,
        *,
        export_dir: Path,
        roi_vlm_csv: Path,
        side_mapping: str,
    ) -> None:
        self.gtmask_runner = OnfhCocoMockVisualRunner(
            export_dir=export_dir,
            side_mapping=side_mapping,
            include_mri_gt_in_visual=False,
        )
        self.roi_rows_by_image_id = self._load_roi_rows(roi_vlm_csv)
        self.mri_tags_by_patient_key = self.gtmask_runner.mri_tags_by_patient_key
        self.mri_stage_by_patient_side = self.gtmask_runner.mri_stage_by_patient_side

    def runnable_xray_rows(self) -> list[Any]:
        return self.gtmask_runner.runnable_xray_rows()

    def skipped_xray_rows(self) -> list[dict[str, Any]]:
        return self.gtmask_runner.skipped_xray_rows()

    def __call__(
        self,
        *,
        image_path: Path | str,
        output_dir: Path | str,
        disease_skill: dict[str, Any],
        disease_key: str,
        patient_message: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        summary = self.gtmask_runner(
            image_path=image_path,
            output_dir=output_dir,
            disease_skill=disease_skill,
            disease_key=disease_key,
            patient_message=patient_message,
            **kwargs,
        )
        visual = summary.get("visual_analysis_result")
        if not isinstance(visual, dict):
            return summary
        row = self.gtmask_runner._row_for_image_path(image_path)
        image_id = int(row.image_id)
        evidence = dict(visual.get("visual_evidence") or {})
        gt_findings = [
            dict(item)
            for item in evidence.get("findings") or []
            if isinstance(item, dict)
        ]
        roi_findings = self._roi_vlm_findings_for_image(image_id)
        findings = gt_findings + roi_findings
        evidence["findings"] = findings
        evidence["structured_visual_facts"] = build_structured_visual_facts(findings)
        evidence["visual_output_mode"] = "combined_gt_xray_mask_plus_cached_real_roi_vlm"
        evidence["fusion_sources"] = {
            "gt_xray_mask_finding_count": len(gt_findings),
            "roi_vlm_finding_count": len(roi_findings),
            "roi_vlm_source": str(DEFAULT_ROI_VLM_CSV),
        }
        evidence["requested_targets"] = sorted(
            {str(item.get("target")) for item in findings if item.get("target")}
        )
        evidence["suspected_visual_findings"] = self._suspected_visual_findings(findings)
        evidence["lesion_detected"] = bool(findings)
        visual["visual_evidence"] = evidence
        visual["requested_targets"] = evidence["requested_targets"]
        visual["visual_output_mode"] = evidence["visual_output_mode"]
        summary["visual_analysis_result"] = visual
        summary["fusion_sources"] = evidence["fusion_sources"]
        return summary

    def _load_roi_rows(self, roi_vlm_csv: Path) -> dict[int, list[dict[str, Any]]]:
        df = pd.read_csv(roi_vlm_csv)
        rows_by_image_id: dict[int, list[dict[str, Any]]] = {}
        for row in df.to_dict(orient="records"):
            rows_by_image_id.setdefault(int(row["image_id"]), []).append(row)
        return rows_by_image_id

    def _roi_vlm_findings_for_image(self, image_id: int) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for row in self.roi_rows_by_image_id.get(image_id, []):
            patient_side = str(row.get("patient_side") or "")
            parsed_findings = self._parse_model_findings(row.get("model_findings"))
            for index, finding in enumerate(parsed_findings, start=1):
                target = str(finding.get("target") or "")
                if not target:
                    continue
                bbox = [
                    float(row.get("roi_bbox_x1") or 0),
                    float(row.get("roi_bbox_y1") or 0),
                    float((row.get("roi_bbox_x2") or 0) - (row.get("roi_bbox_x1") or 0)),
                    float((row.get("roi_bbox_y2") or 0) - (row.get("roi_bbox_y1") or 0)),
                ]
                confidence = float(finding.get("confidence") or row.get("model_confidence") or 0.0)
                display_name = str(finding.get("display_name") or target)
                evidence_text = str(
                    finding.get("evidence_text")
                    or finding.get("evidence_basis")
                    or finding.get("rationale")
                    or ""
                )
                findings.append(
                    {
                        "finding_id": (
                            f"roi_vlm_{row.get('roi_component_id')}_{index}_{target}"
                        ),
                        "target": target,
                        "display_name": display_name,
                        "status": "candidate_observed",
                        "source": "cached_real_roi_vlm",
                        "regions": [
                            {
                                "region_id": f"roi_vlm_{row.get('roi_component_id')}_{index}",
                                "mask_path": "not_generated",
                                "overlay_path": str(row.get("debug_overlay_path") or ""),
                                "bbox": bbox,
                                "centroid": [bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2],
                                "area_px": 0,
                                "area_ratio_in_image": None,
                                "patient_side": patient_side,
                            }
                        ],
                        "confidence": confidence,
                        "evidence_basis": evidence_text,
                        "diagnosis_usable": False,
                        "diagnosis_usable_level": "observation_only",
                        "execution_mode": "vlm_only",
                        "localization_mode": "roi_crop_observation",
                        "segmentation_mode": "none",
                        "measurements": {
                            "area_px": 0,
                            "bbox": bbox,
                            "centroid": [bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2],
                            "patient_side": patient_side,
                            "laterality": patient_side,
                            "roi_component_id": row.get("roi_component_id"),
                            "roi_vlm_pred_stage": row.get("pred_stage"),
                        },
                        "segmentation_ref": {
                            "status": "not_run",
                            "reason": "cached real ROI VLM observation, no lesion mask",
                            "quality": {"level": "observation_only"},
                        },
                    }
                )
        return findings

    def _parse_model_findings(self, value: Any) -> list[dict[str, Any]]:
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

    def _suspected_visual_findings(self, findings: list[dict[str, Any]]) -> list[str]:
        result = []
        for finding in findings:
            display_name = str(finding.get("display_name") or finding.get("target") or "")
            source = str(finding.get("source") or "gt_xray_mask")
            result.append(f"{display_name}：{finding.get('status')}，source={source}")
        return result


def run_eval(
    *,
    export_dir: Path,
    roi_vlm_csv: Path,
    output_dir: Path,
    limit: int | None,
    side_mapping: str,
) -> dict[str, Any]:
    runner = CombinedGtMaskRoiVlmRunner(
        export_dir=export_dir,
        roi_vlm_csv=roi_vlm_csv,
        side_mapping=side_mapping,
    )
    service = MedScopeService(
        gaodoctor_agent=GaoDoctorAgent(no_mask_visual_pipeline_runner=runner)
    )
    rows = runner.runnable_xray_rows()
    if limit is not None:
        rows = rows[:limit]
    output_dir.mkdir(parents=True, exist_ok=True)
    case_results = []
    for row in rows:
        patient_key = f"{row.category}-{row.patient}"
        result = service.handle_request(
            {
                "patient_message": (
                    "请同时使用医生 Xray GT mask 视觉证据和真实 ROI VLM 观察证据，"
                    "按正式股骨头坏死流程生成结构化影像证据和报告。"
                ),
                "image_path": str(row.absolute_path),
                "patient_info": {
                    "patient_id": patient_key,
                    "symptoms": ["髋关节疼痛"],
                    "source": "onfh_combined_gtmask_roi_vlm_eval",
                },
                "disease_key": "femoral_head_necrosis",
                "vision_mode": "no_mask_skill",
            }
        )
        evidence = result.get("visual_input_contract", {}).get("visual_evidence", {})
        case_results.append(
            {
                "case_id": result.get("case_id"),
                "analysis_status": result.get("analysis_status"),
                "patient_key": patient_key,
                "image_id": int(row.image_id),
                "image_path": str(row.absolute_path),
                "image_width": int(row.width),
                "image_height": int(row.height),
                "image_area_px": int(row.width) * int(row.height),
                "case_memory_path": result.get("case_memory_path"),
                "diagnostic_tendency": (result.get("report") or {}).get("diagnostic_tendency"),
                "report_stage_text": (result.get("report") or {}).get("分期判断"),
                "finding_count": len(evidence.get("findings", [])),
                "fusion_sources": evidence.get("fusion_sources", {}),
                "gt_mri_tags": runner.mri_tags_by_patient_key.get(patient_key, []),
                "gt_mri_stage_by_side": runner.mri_stage_by_patient_side.get(patient_key, {}),
                "mask_path": result.get("image_outputs", {}).get("mask_path")
                or result.get("visual_input_contract", {}).get("image_outputs", {}).get("mask_path"),
                "overlay_path": result.get("image_outputs", {}).get("overlay_path")
                or result.get("visual_input_contract", {}).get("image_outputs", {}).get("overlay_path"),
                "findings": evidence.get("findings", []),
            }
        )
    side_level_rows = _build_side_level_eval(case_results)
    instance_level_rows = _build_instance_level_visual_outputs(case_results)
    side_level_csv_path = output_dir / "side_level_eval.csv"
    instance_level_csv_path = output_dir / "instance_level_visual_outputs.csv"
    pd.DataFrame(side_level_rows).to_csv(side_level_csv_path, index=False)
    pd.DataFrame(instance_level_rows).to_csv(instance_level_csv_path, index=False)
    (output_dir / "side_level_eval.json").write_text(
        json.dumps(side_level_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "instance_level_visual_outputs.json").write_text(
        json.dumps(instance_level_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    side_level_metrics = _side_level_metrics(side_level_rows, side_mapping=side_mapping)
    summary = {
        "status": "ok",
        "mode": "formal_service_combined_gtmask_plus_cached_real_roi_vlm",
        "export_dir": str(export_dir),
        "roi_vlm_csv": str(roi_vlm_csv),
        "output_dir": str(output_dir),
        "side_mapping": side_mapping,
        "runnable_xray_images": len(runner.runnable_xray_rows()),
        "evaluated_images": len(case_results),
        "skipped_xray_images": runner.skipped_xray_rows(),
        "side_level_eval_csv": str(side_level_csv_path),
        "instance_level_visual_outputs_csv": str(instance_level_csv_path),
        "side_level_metrics": side_level_metrics,
        "cases": [
            {key: value for key, value in case.items() if key != "findings"}
            for case in case_results
        ],
    }
    summary_path = output_dir / "summary.json"
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MedScope flow with both doctor Xray GT masks and cached real ROI-VLM findings."
    )
    parser.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--roi-vlm-csv", type=Path, default=DEFAULT_ROI_VLM_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--side-mapping", choices=["no_flip", "ap_flip"], default="ap_flip")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_eval(
        export_dir=args.export_dir,
        roi_vlm_csv=args.roi_vlm_csv,
        output_dir=args.output_dir,
        limit=args.limit,
        side_mapping=args.side_mapping,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
