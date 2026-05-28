from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.no_mask_candidate_diagnosis_demo import build_candidate_visual_analysis_result
from scripts.no_mask_medsam2_segmentation_demo import run_no_mask_medsam2_segmentation_demo
from scripts.no_mask_vision_prompt_demo import (
    _load_dotenv_local,
    run_no_mask_vision_prompt_demo,
)
from tools.structured_visual_fact_builder import build_structured_visual_facts
from tools.skill_builder_tool import SkillBuilderTool


DEFAULT_OUTPUT_DIR = Path("output/fake/no_mask_skill_visual_pipeline_demo")


def run_no_mask_skill_visual_pipeline_demo(
    *,
    image_path: Path | str,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    disease_skill: dict[str, Any] | None = None,
    disease_key: str | None = None,
    patient_message: str,
    client: Any | None = None,
    segmentation_tool: Any | None = None,
) -> dict[str, Any]:
    image = Path(image_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    skill = disease_skill or SkillBuilderTool().load_guideline_skill(
        disease_key or "femoral_head_necrosis"
    )
    visual_protocol = skill.get("visual_protocol") or {}
    anatomy_reference = dict(visual_protocol.get("anatomy_reference") or {})
    anatomy_mask_path: str | None = None
    anatomy_summary_path: str | None = None
    anatomy_candidates: list[dict[str, Any]] = []

    if anatomy_reference:
        anatomy_prompt = run_no_mask_vision_prompt_demo(
            image_path=image,
            output_dir=output / "anatomy_prompt",
            patient_message=_anatomy_prompt_message(
                patient_message=patient_message,
                anatomy_reference=anatomy_reference,
            ),
            disease_skill=_anatomy_reference_skill(skill, anatomy_reference),
            client=client,
            source_metadata={
                "source": "skill.visual_protocol.anatomy_reference",
                "target": anatomy_reference.get("target"),
            },
        )
        anatomy_summary = run_no_mask_medsam2_segmentation_demo(
            prompt_result_path=Path(anatomy_prompt["prompt_result_path"]),
            output_dir=output / "anatomy_segmentation",
            segmentation_tool=segmentation_tool,
        )
        if anatomy_summary.get("status") != "ok":
            return _write_json(
                output / "summary.json",
                {
                    "status": "anatomy_reference_not_ready",
                    "anatomy_prompt_summary": anatomy_prompt,
                    "anatomy_segmentation_summary": anatomy_summary,
                },
            )
        anatomy_mask_path = str(anatomy_summary["mask_path"])
        anatomy_summary_path = str(anatomy_summary["summary_path"])
        anatomy_candidates = _anatomy_candidates_from_summary(
            anatomy_summary=anatomy_summary,
            default_anatomy_name=str(anatomy_reference.get("target") or "anatomy"),
        )

    finding_prompt = run_no_mask_vision_prompt_demo(
        image_path=image,
        output_dir=output / "finding_prompt",
        patient_message=patient_message,
        disease_skill=skill,
        client=client,
        source_metadata={
            "source": "skill.visual_protocol.finding_targets",
            "disease_target": visual_protocol.get("disease_target"),
        },
    )
    finding_summary = run_no_mask_medsam2_segmentation_demo(
        prompt_result_path=Path(finding_prompt["prompt_result_path"]),
        output_dir=output / "finding_segmentation",
        segmentation_tool=segmentation_tool,
        anatomy_mask_path=anatomy_mask_path,
        anatomy_name=str(anatomy_reference.get("target") or "anatomy"),
        anatomy_candidates=anatomy_candidates,
    )
    status = "ok" if finding_summary.get("status") == "ok" else "finding_segmentation_not_ready"
    visual_analysis_result: dict[str, Any] | None = None
    visual_evidence_bundle: dict[str, Any] | None = None
    if status == "ok":
        finding_prompt_result = _read_json(Path(finding_prompt["prompt_result_path"]))
        visual_analysis_result = build_candidate_visual_analysis_result(
            finding_summary,
            modality=str(finding_prompt_result.get("modality") or "unknown"),
            body_part=str(finding_prompt_result.get("body_part") or "unknown"),
            disease_target=str(
                visual_protocol.get("disease_target")
                or disease_key
                or "candidate_visual_evidence"
            ),
        )
        visual_evidence_bundle = _build_visual_evidence_bundle(
            visual_analysis_result=visual_analysis_result,
            finding_prompt_summary=finding_prompt,
            finding_segmentation_summary=finding_summary,
        )
    return _write_json(
        output / "summary.json",
        {
            "status": status,
            "image_path": str(image),
            "disease_key": disease_key or visual_protocol.get("disease_target"),
            "output_dir": str(output),
            "anatomy_reference": {
                "target": anatomy_reference.get("target"),
                "display_name": anatomy_reference.get("display_name"),
                "mask_path": anatomy_mask_path,
                "summary_path": anatomy_summary_path,
                "candidates": anatomy_candidates,
            }
            if anatomy_reference
            else None,
            "finding_prompt_summary_path": str(finding_prompt["summary_path"]),
            "finding_prompt_result_path": str(finding_prompt["prompt_result_path"]),
            "finding_segmentation_summary_path": str(finding_summary.get("summary_path")),
            "finding_segmentation_status": finding_summary.get("status"),
            "visual_analysis_result": visual_analysis_result,
            "visual_evidence_bundle": visual_evidence_bundle,
        },
    )


def _anatomy_reference_skill(
    disease_skill: dict[str, Any],
    anatomy_reference: dict[str, Any],
) -> dict[str, Any]:
    return {
        "disease_name": f"{disease_skill.get('disease_name', '目标疾病')}解剖参照",
        "visual_protocol": {
            "disease_target": f"{(disease_skill.get('visual_protocol') or {}).get('disease_target', 'disease')}_anatomy_reference",
            "finding_targets": [anatomy_reference],
        },
    }


def _anatomy_prompt_message(
    *,
    patient_message: str,
    anatomy_reference: dict[str, Any],
) -> str:
    target = anatomy_reference.get("target", "anatomy")
    display_name = anatomy_reference.get("display_name", target)
    description = anatomy_reference.get("description", "")
    return (
        f"{patient_message}\n"
        f"请先定位 {display_name} ({target}) 作为解剖参照区域。"
        f"{description} 只输出该解剖区域的候选 bbox，不做诊断。"
    )


def _build_visual_evidence_bundle(
    *,
    visual_analysis_result: dict[str, Any],
    finding_prompt_summary: dict[str, Any],
    finding_segmentation_summary: dict[str, Any],
) -> dict[str, Any]:
    evidence = dict(visual_analysis_result.get("visual_evidence") or {})
    findings = [
        dict(finding)
        for finding in evidence.get("findings") or []
        if isinstance(finding, dict)
    ]
    present_findings = [
        str(finding.get("target"))
        for finding in findings
        if finding.get("status") in {"candidate_present", "supported", "detected"}
        and finding.get("diagnosis_usable", True)
        and str(finding.get("target") or "").strip()
    ]
    numeric_evidence = _summarize_numeric_evidence(findings)
    quality_warnings = [
        dict(warning)
        for warning in evidence.get("quality_warnings") or []
        if isinstance(warning, dict)
    ]
    image_outputs = dict(visual_analysis_result.get("image_outputs") or {})
    if finding_prompt_summary.get("bbox_overlay_path"):
        image_outputs["bbox_overlay_path"] = str(finding_prompt_summary["bbox_overlay_path"])
    return {
        "schema_version": "visual_evidence_bundle.v1",
        "disease_target": evidence.get("disease_target"),
        "image_context": {
            "image_path": visual_analysis_result.get("image_path"),
            "modality": visual_analysis_result.get("modality"),
            "body_part": visual_analysis_result.get("body_part"),
        },
        "image_outputs": image_outputs,
        "present_findings": present_findings,
        "findings": findings,
        "numeric_evidence": numeric_evidence,
        "structured_visual_facts": build_structured_visual_facts(findings),
        "text_evidence": list(evidence.get("suspected_visual_findings") or []),
        "quality_warnings": quality_warnings,
        "completeness": dict(evidence.get("completeness") or {}),
        "segmentation_results": [
            dict(result)
            for result in evidence.get("segmentation_results") or []
            if isinstance(result, dict)
        ],
        "visual_tool_plan": [
            dict(step)
            for step in evidence.get("visual_tool_plan") or []
            if isinstance(step, dict)
        ],
        "diagnosis_payload": visual_analysis_result,
        "source_paths": {
            "finding_prompt_summary_path": str(finding_prompt_summary.get("summary_path")),
            "finding_segmentation_summary_path": str(
                finding_segmentation_summary.get("summary_path")
            ),
        },
        "aggregation_note": (
            "total_area_px is the sum of per-finding candidate masks and can double-count "
            "overlapping findings; Diagnosis Agent should reason per finding."
        ),
    }


def _anatomy_candidates_from_summary(
    *,
    anatomy_summary: dict[str, Any],
    default_anatomy_name: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for finding in anatomy_summary.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        mask_path = _mask_path_from_finding(finding)
        if not mask_path:
            continue
        candidates.append(
            {
                "anatomy_name": str(finding.get("target") or default_anatomy_name),
                "display_name": str(finding.get("display_name") or finding.get("target") or default_anatomy_name),
                "mask_path": mask_path,
                "measurements": dict(finding.get("measurements") or {}),
            }
        )
    if not candidates and anatomy_summary.get("mask_path"):
        candidates.append(
            {
                "anatomy_name": default_anatomy_name,
                "display_name": default_anatomy_name,
                "mask_path": str(anatomy_summary["mask_path"]),
                "measurements": dict(anatomy_summary.get("measurements") or {}),
            }
        )
    return candidates


def _mask_path_from_finding(finding: dict[str, Any]) -> str | None:
    for region in finding.get("regions") or []:
        if isinstance(region, dict) and region.get("mask_path"):
            return str(region["mask_path"])
    measurements = finding.get("measurements") or {}
    if measurements.get("mask_path"):
        return str(measurements["mask_path"])
    return None


def _summarize_numeric_evidence(findings: list[dict[str, Any]]) -> dict[str, Any]:
    total_area_px = 0
    total_diagnosis_usable_area_px = 0
    total_region_count = 0
    independent_finding_count = 0
    non_independent_finding_count = 0
    diagnosis_usable_finding_count = 0
    diagnosis_unusable_finding_count = 0
    area_ratios_in_image: list[float] = []
    area_ratios_in_anatomy: list[float] = []
    for finding in findings:
        diagnosis_usable = bool(finding.get("diagnosis_usable", True))
        if diagnosis_usable:
            diagnosis_usable_finding_count += 1
        else:
            diagnosis_unusable_finding_count += 1

        if diagnosis_usable and finding.get("independent_evidence", True):
            independent_finding_count += 1
        elif diagnosis_usable:
            non_independent_finding_count += 1
        measurements = finding.get("measurements") or {}
        area_px = int(measurements.get("area_px") or 0)
        total_area_px += area_px
        if diagnosis_usable:
            total_diagnosis_usable_area_px += area_px
        ratio_in_image = measurements.get("area_ratio_in_image")
        if ratio_in_image is not None:
            area_ratios_in_image.append(float(ratio_in_image))
        ratio_in_anatomy = measurements.get("area_ratio_in_anatomy")
        if ratio_in_anatomy is not None:
            area_ratios_in_anatomy.append(float(ratio_in_anatomy))
        total_region_count += len(finding.get("regions") or [])
    return {
        "finding_count": len(findings),
        "independent_finding_count": independent_finding_count,
        "non_independent_finding_count": non_independent_finding_count,
        "diagnosis_usable_finding_count": diagnosis_usable_finding_count,
        "diagnosis_unusable_finding_count": diagnosis_unusable_finding_count,
        "region_count": total_region_count,
        "total_area_px": total_area_px,
        "total_diagnosis_usable_area_px": total_diagnosis_usable_area_px,
        "sum_area_ratio_in_image": round(sum(area_ratios_in_image), 6),
        "max_area_ratio_in_anatomy": (
            round(max(area_ratios_in_anatomy), 6) if area_ratios_in_anatomy else None
        ),
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run skill-driven no-mask vision localization, anatomy reference segmentation, and finding segmentation."
    )
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--disease-key", default="femoral_head_necrosis")
    parser.add_argument("--message", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_dotenv_local()
    args = build_parser().parse_args(argv)
    result = run_no_mask_skill_visual_pipeline_demo(
        image_path=Path(args.image),
        output_dir=Path(args.output_dir),
        disease_key=args.disease_key,
        patient_message=args.message,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
