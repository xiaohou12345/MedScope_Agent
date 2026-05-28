from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.ipf_guideline_skill_demo import run_ipf_guideline_skill_demo
from scripts.ipf_visual_demo import run_ipf_visual_demo
from tools.visual_protocol_validator import VisualProtocolValidator


DEFAULT_OUTPUT_DIR = Path("output/fake/new_disease_guideline_skill_validation")
DISEASE_KEY = "idiopathic_pulmonary_fibrosis_hrct"
DISEASE_NAME = "特发性肺纤维化 HRCT 评估"


def run_new_disease_guideline_skill_validation(
    *,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    guideline_dir = output / "ipf_guideline_skill"
    visual_dir = output / "ipf_visual_demo"
    manifest_path = _write_local_ipf_manifest(output / "local_osic_case")

    guideline_result = run_ipf_guideline_skill_demo(
        output_dir=guideline_dir,
        collect_sources=False,
    )
    skill = _read_json(Path(guideline_result["skill_output_path"]))
    visual_protocol_status = VisualProtocolValidator().validate_skill(skill)

    visual_result = json.loads(
        run_ipf_visual_demo(
            manifest_path=manifest_path,
            case_id="ipf_demo_patient001",
            output_dir=visual_dir,
        )
    )
    evidence_bundle = (
        _read_json(Path(visual_result["evidence_bundle_path"]))
        if visual_result.get("evidence_bundle_path")
        else {}
    )
    payload = _build_summary_payload(
        guideline_result=guideline_result,
        skill=skill,
        visual_protocol_status=visual_protocol_status,
        visual_result=visual_result,
        evidence_bundle=evidence_bundle,
        manifest_path=manifest_path,
    )
    json_path = output / "new_disease_guideline_skill_validation.json"
    markdown_path = output / "new_disease_guideline_skill_validation.md"
    payload["output_paths"] = {
        "summary_json_path": str(json_path),
        "summary_markdown_path": str(markdown_path),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    return {
        "status": payload["status"],
        "disease_key": payload["disease_key"],
        "summary_json_path": str(json_path),
        "summary_markdown_path": str(markdown_path),
    }


def _write_local_ipf_manifest(root: Path) -> Path:
    case_dir = root / "ipf_demo_patient001"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "slice001.dcm").write_bytes(b"fake local HRCT DICOM placeholder")
    lung_mask_path = root / "ipf_demo_patient001_lung_mask.nrrd"
    lung_mask_path.write_text("fake lung anatomy mask placeholder", encoding="utf-8")
    manifest_path = root / "osic_ipf_local_manifest.json"
    manifest = {
        "dataset": "OSIC Pulmonary Fibrosis Progression",
        "disease_key": DISEASE_KEY,
        "disease_name": DISEASE_NAME,
        "modality": "HRCT chest / chest CT",
        "access": {"requires_kaggle_login": False},
        "data_boundary": {
            "ct_role": "raw_medical_image_input",
            "lung_mask_role": "anatomy_mask_not_fibrosis_ground_truth",
            "fibrosis_mask_role": "not_available_by_default",
            "clinical_labels": "not_available_in_local_validation_placeholder",
        },
        "cases": [
            {
                "case_id": "ipf_demo_patient001",
                "ct_path": str(case_dir.relative_to(root)),
                "lung_mask_path": str(lung_mask_path.relative_to(root)),
                "disease_name": DISEASE_NAME,
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_summary_payload(
    *,
    guideline_result: dict[str, Any],
    skill: dict[str, Any],
    visual_protocol_status: dict[str, Any],
    visual_result: dict[str, Any],
    evidence_bundle: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    completeness = dict(evidence_bundle.get("completeness") or {})
    unassessed_targets = [
        target
        for target, state in completeness.items()
        if isinstance(state, dict) and state.get("status") == "unassessed"
    ]
    anatomy_evidence = dict(evidence_bundle.get("anatomy_evidence") or {})
    visual_protocol = dict(skill.get("visual_protocol") or {})
    diagnosis_allowed = bool(evidence_bundle.get("present_findings")) and not unassessed_targets
    return {
        "schema_version": "new_disease_guideline_skill_validation.v1",
        "status": "ok" if visual_result.get("status") == "ok" else visual_result.get("status"),
        "disease_key": DISEASE_KEY,
        "disease_name": DISEASE_NAME,
        "source_paths": {
            "manifest_path": str(manifest_path),
            "skill_output_path": guideline_result.get("skill_output_path"),
            "visual_result_path": visual_result.get("result_path"),
            "evidence_bundle_path": visual_result.get("evidence_bundle_path"),
        },
        "guideline_skill": {
            "generated": True,
            "skill_type": skill.get("skill_type"),
            "path_type": skill.get("path_type"),
            "source_count": guideline_result.get("source_count"),
            "visual_protocol_status": visual_protocol_status.get("status"),
            "visual_protocol_errors": visual_protocol_status.get("errors") or [],
            "required_image_views": list(skill.get("required_image_views") or []),
            "segmentation_targets": list(
                (skill.get("vision_agent_tasks") or {}).get("segmentation_targets") or []
            ),
            "measurements": list(visual_protocol.get("measurements") or []),
        },
        "visual_evidence": {
            "status": visual_result.get("status"),
            "case_id": visual_result.get("case_id"),
            "alignment_status": (visual_result.get("alignment_plan") or {}).get(
                "analysis_status"
            ),
            "evidence_bundle_schema": evidence_bundle.get("schema_version"),
            "anatomy_mask_role": (evidence_bundle.get("data_boundary") or {}).get(
                "lung_mask_role"
            ),
            "lung_mask_status": anatomy_evidence.get("lung_mask_status"),
            "present_finding_count": len(evidence_bundle.get("present_findings") or []),
            "unassessed_target_count": len(unassessed_targets),
            "unassessed_targets": unassessed_targets,
            "image_outputs": evidence_bundle.get("image_outputs") or {},
            "quality_warnings": list(evidence_bundle.get("quality_warnings") or []),
        },
        "safety_boundary": {
            "diagnosis_allowed": diagnosis_allowed,
            "reason": (
                "visual_protocol_executed_but_no_fibrosis_lesion_mask_or_clinical_mdd"
                if not diagnosis_allowed
                else "all_required_visual_targets_supported"
            ),
            "formal_skill_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "candidate_artifacts_only": True,
        },
        "claims": {
            "can_claim": [
                "new_disease_guideline_skill_generated",
                "visual_protocol_validated",
                "visual_protocol_can_build_evidence_bundle",
                "missing_visual_evidence_is_explicitly_unassessed",
            ],
            "cannot_claim": [
                "cannot_diagnose_ipf_from_dry_run_bundle",
                "cannot_treat_lung_mask_as_fibrosis_ground_truth",
                "cannot_claim_universal_guideline_skill_generation_without_review",
            ],
        },
        "next_actions": [
            "Replace placeholder local CT with confirmed OSIC/clinical CT under allowed data terms.",
            "Add fibrosis candidate segmentation or manual review labels for honeycombing/reticulation/traction bronchiectasis.",
            "Run evidence-bounded diagnosis eval after visual targets have supported evidence.",
        ],
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    guideline = payload.get("guideline_skill") or {}
    visual = payload.get("visual_evidence") or {}
    safety = payload.get("safety_boundary") or {}
    claims = payload.get("claims") or {}
    lines = [
        "# 新病种 guideline skill 端到端验证",
        "",
        f"- `disease_key`: `{payload.get('disease_key')}`",
        f"- `status`: `{payload.get('status')}`",
        f"- `skill_type`: `{guideline.get('skill_type')}`",
        f"- `visual_protocol_status`: `{guideline.get('visual_protocol_status')}`",
        f"- `evidence_bundle_schema`: `{visual.get('evidence_bundle_schema')}`",
        f"- `diagnosis_allowed=false`: `{safety.get('diagnosis_allowed') is False}`",
        "",
        "## 已验证",
        "",
    ]
    for claim in claims.get("can_claim") or []:
        lines.append(f"- {claim}")
    lines.extend(["", "## 不能宣称", ""])
    for claim in claims.get("cannot_claim") or []:
        lines.append(f"- {claim}")
    lines.extend(
        [
            "",
            "## Visual Evidence Boundary",
            "",
            f"- `anatomy_mask_role`: `{visual.get('anatomy_mask_role')}`",
            f"- `present_finding_count`: `{visual.get('present_finding_count')}`",
            f"- `unassessed_target_count`: `{visual.get('unassessed_target_count')}`",
            f"- `unassessed_targets`: `{visual.get('unassessed_targets')}`",
            "",
            "## Next Actions",
            "",
        ]
    )
    for action in payload.get("next_actions") or []:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    result = run_new_disease_guideline_skill_validation(output_dir=args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
