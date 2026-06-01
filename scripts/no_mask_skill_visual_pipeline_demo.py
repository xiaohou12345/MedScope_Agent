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
    finding_targets = [
        dict(target)
        for target in visual_protocol.get("finding_targets") or []
        if isinstance(target, dict)
    ]
    segmentable_targets = [
        target for target in finding_targets if _target_runs_segmenter(target)
    ]
    observation_only_targets = [
        target for target in finding_targets if not _target_runs_segmenter(target)
    ]
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
        anatomy_summary_path = str(anatomy_summary.get("summary_path") or "")
        if anatomy_summary.get("status") == "ok":
            anatomy_mask_path = str(anatomy_summary["mask_path"])
            anatomy_candidates = _anatomy_candidates_from_summary(
                anatomy_summary=anatomy_summary,
                default_anatomy_name=str(anatomy_reference.get("target") or "anatomy"),
            )

    finding_prompt: dict[str, Any] | None = None
    finding_summary: dict[str, Any] = {
        "status": "not_run_no_segmentable_findings",
        "summary_path": str(output / "finding_segmentation" / "summary.json"),
        "findings": [],
        "segmentation_results": [],
        "quality_warnings": [],
    }
    observation_prompt: dict[str, Any] | None = None
    observation_findings: list[dict[str, Any]] = []
    if segmentable_targets or not finding_targets:
        prompt_targets = (
            finding_targets
            if segmentable_targets and observation_only_targets
            else segmentable_targets or finding_targets
        )
        segment_skill = _skill_with_finding_targets(
            skill=skill,
            finding_targets=prompt_targets,
        )
        finding_prompt = run_no_mask_vision_prompt_demo(
            image_path=image,
            output_dir=output / "finding_prompt",
            patient_message=patient_message,
            disease_skill=segment_skill,
            client=client,
            source_metadata={
                "source": "skill.visual_protocol.finding_targets.segmentable",
                "disease_target": visual_protocol.get("disease_target"),
            },
        )
        _decorate_prompt_result_with_target_specs(
            prompt_result_path=Path(finding_prompt["prompt_result_path"]),
            finding_targets=prompt_targets,
        )
        segmentation_prompt_result_path = Path(finding_prompt["prompt_result_path"])
        if segmentable_targets and observation_only_targets:
            finding_prompt_result = _read_json(segmentation_prompt_result_path)
            observation_findings.extend(
                _observation_findings_from_prompt_result(
                    prompt_result=finding_prompt_result,
                    finding_targets=observation_only_targets,
                )
            )
            segmentation_prompt_result_path = _write_prompt_result_for_targets(
                source_path=segmentation_prompt_result_path,
                output_path=output / "finding_prompt" / "vision_prompt_result_segmentable.json",
                finding_targets=segmentable_targets,
            )
        finding_summary = run_no_mask_medsam2_segmentation_demo(
            prompt_result_path=segmentation_prompt_result_path,
            output_dir=output / "finding_segmentation",
            segmentation_tool=segmentation_tool,
            anatomy_mask_path=anatomy_mask_path,
            anatomy_name=str(anatomy_reference.get("target") or "anatomy"),
            anatomy_candidates=anatomy_candidates,
        )
        if finding_summary.get("status") != "ok":
            finding_prompt_result = _read_json(Path(finding_prompt["prompt_result_path"]))
            observation_findings.extend(
                _observation_findings_from_prompt_result(
                    prompt_result=finding_prompt_result,
                    finding_targets=segmentable_targets or finding_targets,
                )
            )
    if observation_only_targets and not observation_findings:
        observation_prompt = run_no_mask_vision_prompt_demo(
            image_path=image,
            output_dir=output / "observation_prompt",
            patient_message=patient_message,
            disease_skill=_skill_with_finding_targets(
                skill=skill,
                finding_targets=observation_only_targets,
            ),
            client=client,
            source_metadata={
                "source": "skill.visual_protocol.finding_targets.observation_only",
                "disease_target": visual_protocol.get("disease_target"),
            },
        )
        _decorate_prompt_result_with_target_specs(
            prompt_result_path=Path(observation_prompt["prompt_result_path"]),
            finding_targets=observation_only_targets,
        )
        observation_prompt_result = _read_json(Path(observation_prompt["prompt_result_path"]))
        observation_findings = _observation_findings_from_prompt_result(
            prompt_result=observation_prompt_result,
            finding_targets=observation_only_targets,
        )

    status = (
        "ok"
        if finding_summary.get("status") == "ok" or observation_findings
        else "finding_segmentation_not_ready"
    )
    visual_analysis_result: dict[str, Any] | None = None
    visual_evidence_bundle: dict[str, Any] | None = None
    if status == "ok":
        context_prompt = finding_prompt or observation_prompt
        context_prompt = _merge_prompt_summaries(context_prompt, observation_prompt)
        finding_prompt_result = _read_json(Path(context_prompt["prompt_result_path"]))
        if finding_summary.get("status") == "ok":
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
            _append_observation_findings(
                visual_analysis_result=visual_analysis_result,
                observation_findings=observation_findings,
            )
        else:
            visual_analysis_result = _observation_only_visual_analysis_result(
                image_path=image,
                prompt_result=finding_prompt_result,
                disease_target=str(
                    visual_protocol.get("disease_target")
                    or disease_key
                    or "candidate_visual_evidence"
                ),
                findings=observation_findings,
            )
        _attach_visual_output_mode_metadata(
            visual_analysis_result=visual_analysis_result,
            finding_prompt_summary=context_prompt,
            finding_segmentation_summary=finding_summary,
        )
        visual_evidence_bundle = _build_visual_evidence_bundle(
            visual_analysis_result=visual_analysis_result,
            finding_prompt_summary=context_prompt,
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
            "finding_prompt_summary_path": str(finding_prompt["summary_path"])
            if finding_prompt
            else None,
            "finding_prompt_result_path": str(finding_prompt["prompt_result_path"])
            if finding_prompt
            else None,
            "observation_prompt_summary_path": str(observation_prompt["summary_path"])
            if observation_prompt
            else None,
            "observation_prompt_result_path": str(observation_prompt["prompt_result_path"])
            if observation_prompt
            else None,
            "finding_segmentation_summary_path": str(finding_summary.get("summary_path")),
            "finding_segmentation_status": finding_summary.get("status"),
            "visual_analysis_result": visual_analysis_result,
            "visual_evidence_bundle": visual_evidence_bundle,
        },
    )


def _merge_prompt_summaries(
    primary_prompt: dict[str, Any] | None,
    secondary_prompt: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(primary_prompt or {})
    overlays: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for prompt in (primary_prompt, secondary_prompt):
        for item in (prompt or {}).get("target_overlay_paths") or []:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("target") or ""), str(item.get("overlay_path") or ""))
            if key in seen:
                continue
            seen.add(key)
            overlays.append(dict(item))
    if overlays:
        merged["target_overlay_paths"] = overlays
    return merged


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


def _target_runs_segmenter(finding_target: dict[str, Any]) -> bool:
    execution_mode = str(finding_target.get("execution_mode") or "vlm_plus_segmenter")
    return execution_mode in {"vlm_plus_segmenter", "specialist_segmenter"}


def _skill_with_finding_targets(
    *,
    skill: dict[str, Any],
    finding_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    visual_protocol = dict(skill.get("visual_protocol") or {})
    visual_protocol["finding_targets"] = [dict(target) for target in finding_targets]
    return {
        **skill,
        "visual_protocol": visual_protocol,
    }


def _decorate_prompt_result_with_target_specs(
    *,
    prompt_result_path: Path,
    finding_targets: list[dict[str, Any]],
) -> None:
    prompt_result = _read_json(prompt_result_path)
    target_specs = {
        str(target.get("target")): _target_execution_spec(target)
        for target in finding_targets
        if target.get("target")
    }
    decorated_regions = []
    for region in prompt_result.get("suspected_regions") or []:
        if not isinstance(region, dict):
            continue
        target = str(region.get("target") or "")
        decorated = dict(region)
        decorated.update(target_specs.get(target, {}))
        decorated_regions.append(decorated)
    prompt_result["suspected_regions"] = decorated_regions
    prompt_result_path.write_text(
        json.dumps(prompt_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_prompt_result_for_targets(
    *,
    source_path: Path,
    output_path: Path,
    finding_targets: list[dict[str, Any]],
) -> Path:
    prompt_result = _read_json(source_path)
    allowed_targets = {
        str(target.get("target"))
        for target in finding_targets
        if target.get("target")
    }
    prompt_result["suspected_regions"] = [
        dict(region)
        for region in prompt_result.get("suspected_regions") or []
        if isinstance(region, dict) and str(region.get("target") or "") in allowed_targets
    ]
    prompt_result["segmentation_prompt"] = {
        **dict(prompt_result.get("segmentation_prompt") or {}),
        "boxes": [
            list(region["bbox"])
            for region in prompt_result["suspected_regions"]
            if isinstance(region.get("bbox"), list) and len(region["bbox"]) == 4
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(prompt_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def _target_execution_spec(finding_target: dict[str, Any]) -> dict[str, Any]:
    execution_mode = str(finding_target.get("execution_mode") or "vlm_plus_segmenter")
    segmentation_mode = str(finding_target.get("segmentation_mode") or "")
    if not segmentation_mode:
        segmentation_mode = "none" if execution_mode in {"vlm_only", "measurement_only"} else "candidate_mask"
    diagnosis_usable_level = str(finding_target.get("diagnosis_usable_level") or "")
    if not diagnosis_usable_level:
        diagnosis_usable_level = (
            "observation_only"
            if execution_mode == "vlm_only"
            else "measurement_support"
            if execution_mode == "measurement_only"
            else "candidate_support"
        )
    return {
        "display_name": finding_target.get("display_name") or finding_target.get("target"),
        "execution_mode": execution_mode,
        "localization_mode": str(finding_target.get("localization_mode") or "bbox"),
        "segmentation_mode": segmentation_mode,
        "diagnosis_usable_level": diagnosis_usable_level,
        "measurements_requested": list(finding_target.get("measurements") or []),
    }


def _observation_findings_from_prompt_result(
    *,
    prompt_result: dict[str, Any],
    finding_targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    target_specs = {
        str(target.get("target")): _target_execution_spec(target)
        for target in finding_targets
        if target.get("target")
    }
    findings = []
    for index, region in enumerate(prompt_result.get("suspected_regions") or [], start=1):
        if not isinstance(region, dict):
            continue
        target = str(region.get("target") or f"observation_{index}")
        if target_specs and target not in target_specs:
            continue
        spec = {**target_specs.get(target, {}), **dict(region)}
        polygon = [
            list(point)
            for point in region.get("polygon") or []
            if isinstance(point, (list, tuple)) and len(point) == 2
        ]
        evidence_text = str(region.get("evidence_text") or region.get("rationale") or "")
        findings.append(
            {
                "finding_id": f"finding_{index}_{target}",
                "target": target,
                "display_name": str(spec.get("display_name") or target),
                "status": "candidate_observed",
                "polygon": polygon,
                "evidence_text": evidence_text,
                "needs_next_imaging": bool(prompt_result.get("needs_next_imaging")),
                "required_next_images": [
                    dict(item)
                    for item in prompt_result.get("required_next_images") or []
                    if isinstance(item, dict)
                ],
                "regions": [
                    {
                        "region_id": f"obs{index}",
                        "mask_path": "not_generated",
                        "overlay_path": "not_generated",
                        "comparison_path": "not_generated",
                        "bbox": list(region.get("bbox") or []),
                        "polygon": polygon,
                        "centroid": _bbox_centroid(region.get("bbox")),
                        "area_px": 0,
                        "area_ratio_in_image": None,
                        "area_ratio_in_anatomy": None,
                        "laterality": "unknown",
                        "anatomical_zone": "not_segmented",
                        "measurements": {
                            "bbox": list(region.get("bbox") or []),
                            "polygon": polygon,
                            "confidence": float(region.get("confidence") or 0.0),
                        },
                    }
                ],
                "independent_evidence": True,
                "overlap_qc": {"status": "not_assessed_no_mask"},
                "confidence": float(region.get("confidence") or 0.0),
                "evidence_basis": evidence_text,
                "measurements": {
                    "area_px": 0,
                    "area_ratio_in_image": None,
                    "bbox": list(region.get("bbox") or []),
                    "polygon": polygon,
                    "centroid": _bbox_centroid(region.get("bbox")),
                    "laterality": "unknown",
                },
                "execution_mode": str(spec.get("execution_mode") or "vlm_only"),
                "localization_mode": str(spec.get("localization_mode") or "bbox"),
                "segmentation_mode": str(spec.get("segmentation_mode") or "none"),
                "diagnosis_usable_level": str(
                    spec.get("diagnosis_usable_level") or "observation_only"
                ),
                "diagnosis_usable": False,
                "segmentation_ref": {
                    "status": "not_run",
                    "reason": "execution_mode does not request a lesion mask",
                    "selected_tool": {
                        "tool_name": "vision_model",
                        "role": "observation_localizer",
                    },
                    "quality": {
                        "score": float(region.get("confidence") or 0.0),
                        "level": "observation_only",
                        "warnings": ["VLM-only observation is not measurement-grade evidence"],
                    },
                },
            }
        )
    return findings


def _bbox_centroid(bbox: Any) -> list[float] | None:
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
    except (TypeError, ValueError):
        return None
    return [round((x1 + x2) / 2, 3), round((y1 + y2) / 2, 3)]


def _append_observation_findings(
    *,
    visual_analysis_result: dict[str, Any],
    observation_findings: list[dict[str, Any]],
) -> None:
    if not observation_findings:
        return
    evidence = visual_analysis_result.setdefault("visual_evidence", {})
    findings = [
        dict(finding)
        for finding in evidence.get("findings") or []
        if isinstance(finding, dict)
    ]
    findings.extend(observation_findings)
    evidence["findings"] = findings
    evidence["structured_visual_facts"] = build_structured_visual_facts(findings)
    evidence.setdefault("suspected_visual_findings", [])
    evidence["suspected_visual_findings"].extend(
        [
            (
                f"{finding['display_name']}："
                f"{finding.get('evidence_text') or 'VLM-only 候选观察'}；未生成测量级 mask。"
            )
            for finding in observation_findings
        ]
    )
    required_next_images = [
        dict(item)
        for finding in observation_findings
        for item in finding.get("required_next_images") or []
        if isinstance(item, dict)
    ]
    if required_next_images:
        evidence["required_next_images"] = required_next_images
        evidence["needs_next_imaging"] = True
    evidence.setdefault("visual_tool_plan", [])
    evidence["visual_tool_plan"].append(
        {
            "step": "vlm_only_observation",
            "tool_name": "vision_model",
            "output": "bbox_text_observation",
        }
    )


def _observation_only_visual_analysis_result(
    *,
    image_path: Path,
    prompt_result: dict[str, Any],
    disease_target: str,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "image_path": str(image_path),
        "modality": str(prompt_result.get("modality") or "unknown"),
        "body_part": str(prompt_result.get("body_part") or "unknown"),
        "requested_targets": [
            str(finding.get("target"))
            for finding in findings
            if str(finding.get("target") or "").strip()
        ],
        "requested_features": [
            "vlm_observation",
            "bbox",
            "polygon",
            "rationale",
            "required_next_images",
        ],
        "image_outputs": {
            "original_image_path": str(image_path),
            "mask_path": "not_generated",
            "overlay_path": "not_generated",
            "comparison_path": "not_generated",
        },
        "visual_evidence": {
            "collapse": False,
            "sclerosis": "未评估",
            "cystic_change": "未评估",
            "joint_space_narrowing": False,
            "lesion_mask": "not_generated",
            "confidence": max(
                [float(finding.get("confidence") or 0.0) for finding in findings] or [0.0]
            ),
            "texture_abnormality_score": 0.0,
            "lesion_area_ratio": 0.0,
            "collapse_ratio": 0.0,
            "joint_space_width": "not_applicable",
            "lesion_detected": False,
            "lesion_location": "VLM-only candidate observation",
            "segmentation_quality": "not_run_vlm_only",
            "visual_output_mode": "vlm_only",
            "segmentation_status": "not_run",
            "segmentation_status_reason": "Current execution mode did not request a segmentation mask.",
            "disease_target": disease_target,
            "needs_next_imaging": bool(prompt_result.get("needs_next_imaging")),
            "required_next_images": [
                dict(item)
                for item in prompt_result.get("required_next_images") or []
                if isinstance(item, dict)
            ],
            "quality_warnings": [
                {
                    "code": "vlm_only_no_mask",
                    "severity": "warning",
                    "message": "VLM-only findings are observations and are not measurement-grade segmentation evidence.",
                }
            ],
            "suspected_visual_findings": [
                (
                    f"{finding['display_name']}："
                    f"{finding.get('evidence_text') or 'VLM-only 候选观察'}；未生成测量级 mask。"
                )
                for finding in findings
            ],
            "measurements": {},
            "completeness": {
                "clinical_visual_observation": {
                    "status": "supported",
                    "reason": "VLM produced bounded candidate observations.",
                },
                "measurement_grade_mask": {
                    "status": "unassessed",
                    "reason": "Current execution mode did not request segmentation.",
                },
            },
            "findings": findings,
            "structured_visual_facts": build_structured_visual_facts(findings),
            "segmentation_results": [],
            "visual_tool_plan": [
                {
                    "step": "vlm_only_observation",
                    "tool_name": "vision_model",
                    "output": "bbox_text_observation",
                }
            ],
        },
    }


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
        bbox_overlay_path = str(finding_prompt_summary["bbox_overlay_path"])
        image_outputs["bbox_overlay_path"] = bbox_overlay_path
        image_outputs.setdefault("vlm_annotation_path", bbox_overlay_path)
        image_outputs.setdefault("localization_overlay_path", bbox_overlay_path)
    if finding_prompt_summary.get("target_overlay_paths"):
        image_outputs["target_overlay_paths"] = [
            dict(item)
            for item in finding_prompt_summary.get("target_overlay_paths") or []
            if isinstance(item, dict)
        ]
    visual_mode = evidence.get("visual_output_mode") or _visual_output_mode_from_summary(
        finding_segmentation_summary
    )
    segmentation_state = _segmentation_display_state(
        finding_segmentation_summary=finding_segmentation_summary,
        evidence=evidence,
    )
    return {
        "schema_version": "visual_evidence_bundle.v1",
        "disease_target": evidence.get("disease_target"),
        "visual_output_mode": visual_mode,
        "segmentation_status": segmentation_state["segmentation_status"],
        "fallback_mode": segmentation_state.get("fallback_mode"),
        "segmentation_status_reason": segmentation_state["reason"],
        "segmentation_display_allowed": segmentation_state["segmentation_display_allowed"],
        "image_context": {
            "image_path": visual_analysis_result.get("image_path"),
            "modality": visual_analysis_result.get("modality"),
            "body_part": visual_analysis_result.get("body_part"),
        },
        "image_outputs": image_outputs,
        "needs_next_imaging": bool(evidence.get("needs_next_imaging")),
        "required_next_images": [
            dict(item)
            for item in evidence.get("required_next_images") or []
            if isinstance(item, dict)
        ],
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


def _attach_visual_output_mode_metadata(
    *,
    visual_analysis_result: dict[str, Any],
    finding_prompt_summary: dict[str, Any],
    finding_segmentation_summary: dict[str, Any],
) -> None:
    evidence = visual_analysis_result.setdefault("visual_evidence", {})
    image_outputs = visual_analysis_result.setdefault("image_outputs", {})
    if finding_prompt_summary.get("bbox_overlay_path"):
        bbox_overlay_path = str(finding_prompt_summary["bbox_overlay_path"])
        image_outputs.setdefault("bbox_overlay_path", bbox_overlay_path)
        image_outputs.setdefault("vlm_annotation_path", bbox_overlay_path)
        image_outputs.setdefault("localization_overlay_path", bbox_overlay_path)
    if finding_prompt_summary.get("target_overlay_paths"):
        image_outputs["target_overlay_paths"] = [
            dict(item)
            for item in finding_prompt_summary.get("target_overlay_paths") or []
            if isinstance(item, dict)
        ]
    state = _segmentation_display_state(
        finding_segmentation_summary=finding_segmentation_summary,
        evidence=evidence,
    )
    evidence["visual_output_mode"] = _visual_output_mode_from_summary(
        finding_segmentation_summary
    )
    evidence["segmentation_status"] = state["segmentation_status"]
    evidence["segmentation_status_reason"] = state["reason"]
    if state.get("fallback_mode"):
        evidence["fallback_mode"] = state["fallback_mode"]
    else:
        evidence.pop("fallback_mode", None)
    evidence.setdefault("completeness", {})["segmentation_display"] = {
        "status": "supported" if state["segmentation_display_allowed"] else "missing",
        "reason": state["reason"],
    }


def _visual_output_mode_from_summary(finding_segmentation_summary: dict[str, Any]) -> str:
    if finding_segmentation_summary.get("status") == "not_run_no_segmentable_findings":
        return "vlm_only"
    if finding_segmentation_summary.get("status") in {
        "segmentation_error",
        "medsam2_not_ready",
        "not_ready",
    }:
        return "vlm_plus_segmenter"
    if finding_segmentation_summary.get("segmentation_results"):
        return "vlm_plus_segmenter"
    return "vlm_only"


def _segmentation_display_state(
    *,
    finding_segmentation_summary: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if finding_segmentation_summary.get("status") == "not_run_no_segmentable_findings":
        return {
            "segmentation_status": "not_run",
            "fallback_mode": "vlm_only",
            "segmentation_display_allowed": False,
            "reason": "No segmentable finding target was configured; VLM observations are shown instead.",
        }
    if finding_segmentation_summary.get("status") != "ok":
        return {
            "segmentation_status": "not_ready",
            "fallback_mode": "vlm_only",
            "segmentation_display_allowed": False,
            "reason": f"Segmentation did not complete: {finding_segmentation_summary.get('status', 'unknown')}.",
        }
    segmentation_results = [
        dict(item)
        for item in finding_segmentation_summary.get("segmentation_results") or []
        if isinstance(item, dict)
    ]
    if not segmentation_results:
        return {
            "segmentation_status": "not_run",
            "fallback_mode": "vlm_only",
            "segmentation_display_allowed": False,
            "reason": "No segmentation result was generated.",
        }
    fake_sources = [
        str((result.get("selected_tool") or {}).get("segmentation_source") or "")
        for result in segmentation_results
        if str((result.get("selected_tool") or {}).get("segmentation_source") or "").startswith("fake_")
    ]
    if fake_sources:
        return {
            "segmentation_status": "failed_qc",
            "fallback_mode": "vlm_only",
            "segmentation_display_allowed": False,
            "reason": "Segmentation source is a fake/demo backend; show VLM annotation instead of lesion mask.",
        }
    quality_warnings = [
        dict(item)
        for item in finding_segmentation_summary.get("quality_warnings") or evidence.get("quality_warnings") or []
        if isinstance(item, dict)
    ]
    blocking_warning = next(
        (
            warning
            for warning in quality_warnings
            if warning.get("severity") in {"error", "critical"}
            or warning.get("code") in {"box_mask_misalignment", "overlapping_candidate_masks"}
        ),
        None,
    )
    if blocking_warning:
        return {
            "segmentation_status": "failed_qc",
            "fallback_mode": "vlm_only",
            "segmentation_display_allowed": False,
            "reason": str(
                blocking_warning.get("message")
                or blocking_warning.get("reason")
                or blocking_warning.get("code")
                or "Segmentation quality check failed."
            ),
        }
    if not any(result.get("diagnosis_usable") for result in segmentation_results):
        return {
            "segmentation_status": "failed_qc",
            "fallback_mode": "vlm_only",
            "segmentation_display_allowed": False,
            "reason": "No segmentation result passed the diagnosis usability gate.",
        }
    return {
        "segmentation_status": "candidate_passed_qc",
        "fallback_mode": None,
        "segmentation_display_allowed": True,
        "reason": "Candidate segmentation passed configured quality gates.",
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
