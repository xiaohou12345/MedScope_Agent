from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agents.diagnosis_agent import DiagnosisDoctorAgent
from tools.structured_visual_fact_builder import build_structured_visual_facts
from tools.knowledge_builder_tool import KnowledgeBuilderTool


DEFAULT_SEGMENTATION_SUMMARY = Path(
    "output/fake/no_mask_medsam2_segmentation_demo/summary.json"
)
DEFAULT_OUTPUT_DIR = Path("output/fake/no_mask_candidate_diagnosis_demo")


def run_no_mask_candidate_diagnosis_demo(
    *,
    segmentation_summary_path: Path | str = DEFAULT_SEGMENTATION_SUMMARY,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    disease_key: str | None = None,
    case_id: str | None = None,
    patient_message: str = "上传胸部 X 光，想评估是否存在疑似肺部感染影像表现。",
    symptoms: list[str] | None = None,
    modality: str = "xray",
    body_part: str = "chest",
    hypothesis_validation_mode: bool | None = None,
) -> dict[str, Any]:
    summary_path = Path(segmentation_summary_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    segmentation_summary = json.loads(summary_path.read_text(encoding="utf-8"))

    if segmentation_summary.get("status") != "ok":
        return _write_json(
            output / "summary.json",
            {
                "status": "segmentation_not_ready",
                "segmentation_summary_path": str(summary_path),
                "reason": segmentation_summary.get("status", "unknown"),
            },
        )

    disease_knowledge = (
        KnowledgeBuilderTool().load_guideline_knowledge(disease_key)
        if disease_key
        else build_pneumonia_candidate_knowledge()
    )
    visual_result = build_candidate_visual_analysis_result(
        segmentation_summary,
        modality=modality,
        body_part=body_part,
        disease_target=str(
            (disease_knowledge.get("visual_protocol") or {}).get("disease_target")
            or disease_key
            or "pneumonia_or_lung_opacity_candidate"
        ),
    )
    effective_hypothesis_mode = (
        hypothesis_validation_mode
        if hypothesis_validation_mode is not None
        else disease_knowledge.get("knowledge_type") == "data_mined_hypothesis"
    )
    report = DiagnosisDoctorAgent().generate_report(
        case_id=case_id or f"case_no_mask_{disease_key or 'pneumonia_candidate'}",
        patient_info={
            "symptoms": symptoms or ["咳嗽", "发热"],
            "patient_message": patient_message,
        },
        visual_result=visual_result,
        disease_knowledge=disease_knowledge,
        hypothesis_validation_mode=effective_hypothesis_mode,
    )

    report_path = output / "candidate_diagnosis_report.json"
    _write_json(report_path, report)
    return _write_json(
        output / "summary.json",
        {
            "status": "ok",
            "segmentation_summary_path": str(summary_path),
            "report_path": str(report_path),
            "diagnosis_scope": "candidate_visual_evidence_only",
            "disease_key": disease_key or "pneumonia_candidate",
            "warning": disease_knowledge.get("warning", "Guideline report generated from candidate visual evidence."),
        },
    )


def build_candidate_visual_analysis_result(
    segmentation_summary: dict[str, Any],
    *,
    modality: str = "xray",
    body_part: str = "chest",
    disease_target: str = "pneumonia_or_lung_opacity_candidate",
) -> dict[str, Any]:
    measurements = dict(segmentation_summary.get("measurements") or {})
    mask_path = str(segmentation_summary.get("mask_path") or "not_generated")
    overlay_path = str(segmentation_summary.get("overlay_path") or "not_generated")
    comparison_path = str(segmentation_summary.get("comparison_path") or "")
    image_path = str(segmentation_summary["image_path"])
    lesion_area_ratio = float(measurements.get("lesion_area_ratio") or 0.0)
    lesion_area_px = int(measurements.get("lesion_area_px") or 0)
    lesion_bbox = measurements.get("lesion_bbox") or []
    lesion_centroid = measurements.get("lesion_centroid") or []
    segmentation_result = dict(segmentation_summary["segmentation_result"])
    findings = [
        dict(finding)
        for finding in segmentation_summary.get("findings") or []
        if isinstance(finding, dict)
    ] or _build_structured_findings(
        measurements=measurements,
        mask_path=mask_path,
        overlay_path=overlay_path,
        comparison_path=comparison_path,
        segmentation_result=segmentation_result,
    )
    requested_targets = [
        str(finding.get("target"))
        for finding in findings
        if str(finding.get("target") or "").strip()
    ] or ["candidate_lung_opacity"]
    segmentation_results = [
        dict(result)
        for result in segmentation_summary.get("segmentation_results") or []
        if isinstance(result, dict)
    ] or [segmentation_result]
    quality_warnings = [
        dict(warning)
        for warning in segmentation_summary.get("quality_warnings") or []
        if isinstance(warning, dict)
    ]
    present_targets = {
        str(finding.get("target"))
        for finding in findings
        if finding.get("status") in {"candidate_present", "supported", "detected"}
        and finding.get("diagnosis_usable", True)
    }
    has_fhn_xray_candidate = bool(
        present_targets & {"sclerotic_band", "cystic_change", "trabecular_blurring"}
    )
    suspected_visual_findings = _suspected_visual_findings_from_findings(
        findings=findings,
        lesion_area_px=lesion_area_px,
        lesion_area_ratio=lesion_area_ratio,
    )

    return {
        "image_path": image_path,
        "modality": modality,
        "body_part": body_part,
        "requested_targets": requested_targets,
        "requested_features": [
            "candidate_lesion_mask",
            "lesion_area_ratio",
            "lesion_bbox",
            "lesion_centroid",
        ],
        "image_outputs": {
            "original_image_path": image_path,
            "mask_path": mask_path,
            "overlay_path": overlay_path,
            "comparison_path": comparison_path,
        },
        "visual_evidence": {
            "collapse": False,
            "sclerosis": "候选阳性" if "sclerotic_band" in present_targets else "未评估",
            "cystic_change": "候选阳性" if "cystic_change" in present_targets else "未评估",
            "joint_space_narrowing": False,
            "lesion_mask": mask_path,
            "confidence": 0.6,
            "texture_abnormality_score": 0.75 if has_fhn_xray_candidate else 0.0,
            "lesion_area_ratio": lesion_area_ratio,
            "collapse_ratio": 0.0,
            "joint_space_width": "not_applicable",
            "lesion_detected": lesion_area_px > 0,
            "lesion_location": _format_lesion_location(lesion_bbox, lesion_centroid),
            "segmentation_quality": "medium_candidate",
            "disease_target": disease_target,
            "quality_warnings": quality_warnings,
            "suspected_visual_findings": suspected_visual_findings,
            "measurements": measurements,
            "completeness": {
                "candidate_lesion_mask": {
                    "status": "supported",
                    "reason": "Gemini box prompt plus MedSAM2 2D segmentation produced a candidate mask.",
                },
                "clinical_diagnosis": {
                    "status": "unassessed",
                    "reason": "Vision Agent only provides candidate visual evidence; Diagnosis Agent must apply the selected disease knowledge and safety gates.",
                },
            },
            "findings": findings,
            "structured_visual_facts": build_structured_visual_facts(findings),
            "segmentation_results": segmentation_results,
            "visual_tool_plan": [
                {
                    "step": "vision_model_localization",
                    "tool_name": "gemini-3.5-flash",
                    "output": "box_prompt",
                },
                {
                    "step": "segmentation",
                    "tool_name": "medsam2",
                    "output": "candidate_mask",
                },
                {
                    "step": "measurement",
                    "tool_name": "generic_mask_measurement_tool",
                    "output": "area_bbox_centroid",
                },
            ],
        },
    }


def _build_structured_findings(
    *,
    measurements: dict[str, Any],
    mask_path: str,
    overlay_path: str,
    comparison_path: str,
    segmentation_result: dict[str, Any],
) -> list[dict[str, Any]]:
    area_px = int(measurements.get("lesion_area_px") or 0)
    area_ratio = float(measurements.get("lesion_area_ratio") or 0.0)
    bbox = measurements.get("lesion_bbox")
    centroid = measurements.get("lesion_centroid")
    status = "candidate_present" if area_px > 0 else "candidate_absent"
    diagnosis_usable = bool(segmentation_result.get("diagnosis_usable")) and area_px > 0
    regions = [
        {
            "region_id": str(region.get("region_id") or f"r{index}"),
            "mask_path": mask_path,
            "overlay_path": overlay_path,
            "comparison_path": comparison_path,
            "bbox": region.get("bbox"),
            "centroid": region.get("centroid"),
            "area_px": int(region.get("area_px") or 0),
            "area_ratio_in_image": float(region.get("area_ratio_in_image") or 0.0),
            "area_ratio_in_anatomy": None,
            "laterality": "unknown",
            "anatomical_zone": "candidate_lung_zone",
            "measurements": dict(region),
        }
        for index, region in enumerate(measurements.get("regions") or [], start=1)
        if int(region.get("area_px") or 0) > 0
    ]
    if area_px > 0 and not regions:
        regions = [
            {
                "region_id": "r1",
                "mask_path": mask_path,
                "overlay_path": overlay_path,
                "comparison_path": comparison_path,
                "bbox": bbox,
                "centroid": centroid,
                "area_px": area_px,
                "area_ratio_in_image": area_ratio,
                "area_ratio_in_anatomy": None,
                "laterality": "unknown",
                "anatomical_zone": "candidate_lung_zone",
                "measurements": dict(measurements),
            }
        ]
    return [
        {
            "finding_id": "f1",
            "target": "lung_opacity",
            "display_name": "肺部浸润影/实变影候选区域",
            "status": status,
            "regions": regions,
            "confidence": 0.6,
            "evidence_basis": "Gemini localized a candidate opacity box; MedSAM2 generated a candidate mask from that prompt.",
            "measurements": {
                "area_px": area_px,
                "area_ratio_in_image": area_ratio,
                "bbox": bbox,
                "centroid": centroid,
            },
            "diagnosis_usable": diagnosis_usable,
            "segmentation_ref": {
                "task_name": segmentation_result.get("task_name"),
                "selected_tool": dict(segmentation_result.get("selected_tool") or {}),
                "quality": dict(segmentation_result.get("quality") or {}),
            },
        }
    ]


def _suspected_visual_findings_from_findings(
    *,
    findings: list[dict[str, Any]],
    lesion_area_px: int,
    lesion_area_ratio: float,
) -> list[str]:
    visual_findings = [
        "Gemini 视觉模型先定位 knowledge 约束的候选异常区域，MedSAM2 根据 box prompt 生成候选 mask。",
        f"候选 mask 面积为 {lesion_area_px} px，约占图像面积 {lesion_area_ratio:.4f}。",
    ]
    for finding in findings:
        display_name = _display_name_for_target(
            str(finding.get("display_name") or finding.get("target") or "候选征象")
        )
        status = str(finding.get("status") or "unknown")
        basis = str(finding.get("evidence_basis") or "").strip()
        if basis:
            visual_findings.append(f"{display_name}：{status}；{basis}")
        else:
            visual_findings.append(f"{display_name}：{status}")
    visual_findings.append("该结果是候选影像证据，需要临床医生或更合适的专病模型复核。")
    return visual_findings


def _display_name_for_target(value: str) -> str:
    display_names = {
        "sclerotic_band": "硬化带",
        "cystic_change": "囊性变",
        "trabecular_blurring": "骨小梁模糊或局灶性骨质疏松",
        "collapse": "股骨头塌陷",
        "lung_opacity": "肺部浸润影/实变影候选区域",
    }
    return display_names.get(value, value)


def build_pneumonia_candidate_knowledge() -> dict[str, Any]:
    return {
        "disease_name": "肺部浸润影候选提示",
        "knowledge_id": "pneumonia_opacity_candidate_v0.1",
        "knowledge_type": "data_mined_hypothesis",
        "evidence_level": "low",
        "source": "No-mask demo: Gemini visual localization plus MedSAM2 candidate segmentation",
        "warning": "该输出只验证视觉 Agent 到诊断 Agent 的证据传递，不能作为确定诊断依据。",
        "candidate_observation_rules": [
            "胸片局部候选 mask 面积、位置和边界可作为低证据影像提示。",
            "候选阴影需要结合症状、实验室检查、放射科医生阅片或更高质量影像复核。",
        ],
        "safety_gate": {
            "clinical_use": "not_for_diagnosis",
            "requires_review": True,
            "allowed_output": "candidate_evidence_report",
        },
    }


def _format_lesion_location(bbox: Any, centroid: Any) -> str:
    if bbox and centroid:
        return f"bbox={bbox}; centroid={centroid}"
    if bbox:
        return f"bbox={bbox}"
    if centroid:
        return f"centroid={centroid}"
    return "未定位"


def _write_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a diagnosis-agent candidate report from no-mask MedSAM2 output."
    )
    parser.add_argument("--segmentation-summary", default=str(DEFAULT_SEGMENTATION_SUMMARY))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--disease-key", default="")
    parser.add_argument("--case-id", default="")
    parser.add_argument("--patient-message", default="上传胸部 X 光，想评估是否存在疑似肺部感染影像表现。")
    parser.add_argument("--symptom", action="append", default=[])
    parser.add_argument("--modality", default="xray")
    parser.add_argument("--body-part", default="chest")
    parser.add_argument(
        "--hypothesis-validation-mode",
        action="store_true",
        help="Force hypothesis validation mode for data-mined candidate knowledge.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_no_mask_candidate_diagnosis_demo(
        segmentation_summary_path=Path(args.segmentation_summary),
        output_dir=Path(args.output_dir),
        disease_key=args.disease_key or None,
        case_id=args.case_id or None,
        patient_message=args.patient_message,
        symptoms=args.symptom or None,
        modality=args.modality,
        body_part=args.body_part,
        hypothesis_validation_mode=True if args.hypothesis_validation_mode else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
