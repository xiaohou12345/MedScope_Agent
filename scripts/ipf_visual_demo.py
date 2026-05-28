from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.osic_ipf_dataset import DEFAULT_OSIC_MANIFEST, validate_osic_manifest
from tools.alignment_planner import AlignmentPlanner
from tools.skill_builder_tool import SkillBuilderTool


DEFAULT_OUTPUT_DIR = Path("output/fake/ipf_visual_demo")
DISEASE_KEY = "idiopathic_pulmonary_fibrosis_hrct"
DEFAULT_PATIENT_MESSAGE = "长期干咳气短，上传 HRCT chest CT，评估是否存在 IPF/UIP 相关影像证据。"


def run_ipf_visual_demo(
    manifest_path: Path | str = DEFAULT_OSIC_MANIFEST,
    case_id: str | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    patient_message: str = DEFAULT_PATIENT_MESSAGE,
) -> str:
    manifest = Path(manifest_path)
    output = Path(output_dir)
    manifest_validation = json.loads(validate_osic_manifest(manifest))
    status = manifest_validation.get("status")
    if status == "pending_download":
        return json.dumps(
            {
                "status": "pending_download",
                "disease_key": DISEASE_KEY,
                "manifest_path": str(manifest),
                "manifest_validation": manifest_validation,
                "action_items": list(manifest_validation.get("action_items") or []),
                "evidence_bundle_path": None,
            },
            ensure_ascii=False,
            indent=2,
        )
    if status != "ok":
        return json.dumps(
            {
                "status": "invalid_manifest",
                "disease_key": DISEASE_KEY,
                "manifest_path": str(manifest),
                "manifest_validation": manifest_validation,
                "evidence_bundle_path": None,
            },
            ensure_ascii=False,
            indent=2,
        )

    case = _select_valid_case(manifest_validation, case_id)
    skill = SkillBuilderTool().load_guideline_skill(DISEASE_KEY)
    payload = {
        "patient_message": patient_message,
        "image_path": case["resolved_paths"]["ct_path"],
        "patient_info": {"symptoms": ["dry cough", "dyspnea"]},
    }
    routing_decision = {
        "selected_skill": DISEASE_KEY,
        "selected_vision_mode": None,
        "source": "demo_manifest",
        "reason": "OSIC/IPF manifest case selected for visual protocol dry-run.",
        "confidence": 1.0,
        "matched_clues": ["HRCT", "IPF", "OSIC"],
    }
    alignment_plan = AlignmentPlanner().build_plan(
        payload=payload,
        routing_decision=routing_decision,
        disease_skill=skill,
    )
    bundle = _build_ipf_evidence_bundle(
        case=case,
        skill=skill,
        alignment_plan=alignment_plan,
        manifest_validation=manifest_validation,
    )
    output.mkdir(parents=True, exist_ok=True)
    bundle_path = output / f"{case['case_id']}_ipf_evidence_bundle.json"
    result_path = output / f"{case['case_id']}_ipf_visual_demo_result.json"
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    result = {
        "status": "ok",
        "case_id": case["case_id"],
        "disease_key": DISEASE_KEY,
        "manifest_path": str(manifest),
        "alignment_plan": alignment_plan,
        "evidence_bundle_path": str(bundle_path),
        "result_path": str(result_path),
        "image_outputs": {
            "mask_path": None,
            "overlay_path": None,
            "status": "not_generated_in_dry_run",
        },
        "quality_warnings": list(bundle["quality_warnings"]),
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.dumps(result, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an IPF visual protocol dry-run from an OSIC CT manifest."
    )
    parser.add_argument("--manifest", default=str(DEFAULT_OSIC_MANIFEST))
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--patient-message", default=DEFAULT_PATIENT_MESSAGE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(
        run_ipf_visual_demo(
            manifest_path=args.manifest,
            case_id=args.case_id,
            output_dir=args.output_dir,
            patient_message=args.patient_message,
        )
    )
    return 0


def _select_valid_case(
    manifest_validation: dict[str, Any],
    case_id: str | None,
) -> dict[str, Any]:
    valid_cases = [
        case for case in manifest_validation.get("cases", []) if case.get("status") == "ok"
    ]
    if not valid_cases:
        raise ValueError("No valid OSIC/IPF cases are available.")
    if not case_id:
        return valid_cases[0]
    for case in valid_cases:
        if case.get("case_id") == case_id:
            return case
    raise ValueError(f"Case not found in valid OSIC/IPF manifest cases: {case_id}")


def _build_ipf_evidence_bundle(
    *,
    case: dict[str, Any],
    skill: dict[str, Any],
    alignment_plan: dict[str, Any],
    manifest_validation: dict[str, Any],
) -> dict[str, Any]:
    protocol = skill.get("visual_protocol") or {}
    measurements = {
        measurement: None for measurement in protocol.get("measurements", [])
    }
    completeness = {
        target: {
            "status": "unassessed",
            "reason": "IPF visual demo has not run a fibrosis candidate segmentation model; no fibrosis mask is available.",
        }
        for target in (protocol.get("required_modalities") or {})
    }
    anatomy_status = case.get("label_boundary", {}).get("lung_mask_status", "not_available")
    if anatomy_status == "available_anatomy_only":
        anatomy_reason = "Lung mask is available for anatomy normalization only."
    else:
        anatomy_reason = "No lung anatomy mask is available."

    return {
        "schema_version": "ipf_visual_evidence_bundle.v1",
        "case_id": case["case_id"],
        "disease_target": DISEASE_KEY,
        "skill_id": skill.get("skill_id"),
        "image_context": alignment_plan.get("image_context", {}),
        "visual_tasks": alignment_plan.get("visual_tasks", []),
        "present_findings": [],
        "findings": [],
        "measurements": measurements,
        "completeness": completeness,
        "anatomy_evidence": {
            "lung_mask_path": case.get("resolved_paths", {}).get("lung_mask_path"),
            "lung_mask_status": anatomy_status,
            "reason": anatomy_reason,
        },
        "image_outputs": {
            "mask_path": None,
            "overlay_path": None,
            "status": "not_generated_in_dry_run",
        },
        "data_boundary": manifest_validation.get("data_boundary", {}),
        "missing_or_unassessed": {
            "fibrosis_candidate_mask": "missing",
            "pixel_level_fibrosis_ground_truth": "not_available",
            "clinical_mdd": "not_available",
            "pulmonary_function_tests": "not_available",
        },
        "quality_warnings": [
            "Lung masks can normalize anatomy and distribution only; they are not fibrosis lesion labels.",
            "No honeycombing, reticulation, traction bronchiectasis, or fibrosis candidate mask is asserted in this dry-run.",
            "Do not diagnose IPF from this evidence bundle alone; guideline context requires clinical correlation and ILD multidisciplinary discussion.",
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
