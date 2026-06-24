from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agents.gaodoctor_agent import GaoDoctorAgent
from api.service import MedScopeService
from memory.memory_manager import MemoryManager
from PIL import Image, ImageDraw


DEFAULT_OUTPUT_DIR = Path("output/fake/public_demo_fixture")
DEFAULT_PUBLIC_SUITE_OUTPUT_DIR = Path("output/fake/public_safe_demo_suite")


def prepare_public_demo_fixture(output_dir: Path | str = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    """Create a deterministic, public-safe demo fixture for fresh clones.

    The generated image is synthetic and intentionally not a medical record. It is
    only meant to exercise upload, routing, knowledge selection, and bounded evidence
    flow without depending on local private datasets.
    """

    fixture_dir = Path(output_dir)
    fixture_dir.mkdir(parents=True, exist_ok=True)
    image_path = fixture_dir / "synthetic_hip_xray_public_safe.png"
    manifest_path = fixture_dir / "public_demo_fixture_manifest.json"

    _draw_synthetic_hip_xray(image_path)

    payload = {
        "patient_message": "右髋疼痛，走路加重，请分析这张髋关节 X 光样例。",
        "image_path": str(image_path),
        "disease_key": "femoral_head_necrosis",
        "vision_mode": "no_mask_knowledge",
        "patient_info": {
            "patient_id": "public_demo_patient_001",
            "age": 45,
            "sex": "unknown",
            "symptoms": ["髋关节疼痛", "行走加重"],
        },
    }
    manifest = {
        "fixture_name": "public_safe_fhn_xray_fixture",
        "status": "ready",
        "safety": [
            "public_safe",
            "synthetic_image",
            "not_real_patient_data",
            "not_clinical_ground_truth",
        ],
        "image_path": str(image_path),
        "service_payload": payload,
        "recommended_command": (
            "python -m scripts.prepare_public_demo_fixture "
            f"--output-dir {fixture_dir}"
        ),
        "notes": [
            "Use this fixture to verify fresh-clone routing and frontend upload behavior.",
            "Do not use this synthetic image as a segmentation or diagnostic benchmark.",
        ],
    }
    _write_json(manifest_path, manifest)
    return {
        "fixture_name": manifest["fixture_name"],
        "status": manifest["status"],
        "safety": manifest["safety"],
        "image_path": str(image_path),
        "manifest_path": str(manifest_path),
        "service_payload": payload,
    }


def run_public_safe_demo_suite(output_dir: Path | str = DEFAULT_PUBLIC_SUITE_OUTPUT_DIR) -> dict[str, Any]:
    """Run a public-safe MVP demo without real patient data or external backends."""

    suite_dir = Path(output_dir)
    fixture_dir = suite_dir / "fixture"
    artifacts_dir = suite_dir / "artifacts"
    memory_dir = suite_dir / "memory"
    for directory in (fixture_dir, artifacts_dir, memory_dir):
        directory.mkdir(parents=True, exist_ok=True)

    fixture = prepare_public_demo_fixture(output_dir=fixture_dir)
    memory_manager = MemoryManager(base_dir=memory_dir)
    doctor = GaoDoctorAgent(
        memory_manager=memory_manager,
        no_mask_visual_pipeline_runner=PublicSafeNoMaskVisualRunner(),
    )
    service = MedScopeService(gaodoctor_agent=doctor)

    response = service.handle_request(fixture["service_payload"])
    case_id = response["case_id"]
    qa_response = service.handle_request(
        {
            "case_id": case_id,
            "patient_message": "下一步应该做什么？",
        }
    )
    evidence_bundle = memory_manager.get_evidence_bundle(case_id)
    memory_audit = memory_manager.build_audit_summary(case_id)

    response_path = artifacts_dir / "public_safe_response.json"
    evidence_bundle_path = artifacts_dir / "public_safe_evidence_bundle.json"
    memory_audit_path = artifacts_dir / "public_safe_memory_audit.json"
    qa_response_path = artifacts_dir / "public_safe_qa_response.json"
    summary_path = suite_dir / "public_safe_demo_summary.json"
    summary_markdown_path = suite_dir / "public_safe_demo_summary.md"

    _write_json(response_path, response)
    _write_json(evidence_bundle_path, evidence_bundle)
    _write_json(memory_audit_path, memory_audit)
    _write_json(qa_response_path, qa_response)

    summary = {
        "demo_name": "public_safe_medscope_mvp_demo",
        "status": "ok",
        "case_id": case_id,
        "suite_output_dir": str(suite_dir),
        "fixture_manifest_path": fixture["manifest_path"],
        "response_path": str(response_path),
        "evidence_bundle_path": str(evidence_bundle_path),
        "memory_audit_path": str(memory_audit_path),
        "qa_response_path": str(qa_response_path),
        "summary_path": str(summary_path),
        "summary_markdown_path": str(summary_markdown_path),
        "routing_decision": response.get("routing_decision", {}),
        "analysis_status": response.get("analysis_status"),
        "safety": {
            "public_safe": True,
            "synthetic_image": True,
            "real_fhn_data_required": False,
            "real_mask_required": False,
            "not_clinical_diagnosis": True,
            "not_segmentation_benchmark": True,
        },
        "steps": {
            "fixture_generation": {
                "status": "completed",
                "manifest_path": fixture["manifest_path"],
                "image_path": fixture["image_path"],
            },
            "upload_and_routing": {
                "status": "completed",
                "selected_knowledge": response.get("routing_decision", {}).get("selected_knowledge"),
                "selected_vision_mode": response.get("routing_decision", {}).get("selected_vision_mode"),
            },
            "visual_evidence": {
                "status": "completed",
                "image_outputs": response.get("image_outputs", {}),
            },
            "diagnosis_report": {
                "status": "completed",
                "analysis_status": response.get("analysis_status"),
            },
            "evidence_bundle": {
                "status": "completed",
                "path": str(evidence_bundle_path),
            },
            "memory_audit": {
                "status": "completed",
                "path": str(memory_audit_path),
            },
            "follow-up QA": {
                "status": "completed",
                "path": str(qa_response_path),
            },
        },
    }
    _write_json(summary_path, summary)
    summary_markdown_path.write_text(_render_public_safe_suite_markdown(summary), encoding="utf-8")
    return summary


class PublicSafeNoMaskVisualRunner:
    """Deterministic no-mask runner for public-safe architecture demos."""

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        image_path = str(kwargs["image_path"])
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        mask_path = output_dir / "public_safe_candidate_mask.png"
        overlay_path = output_dir / "public_safe_candidate_overlay.png"
        comparison_path = output_dir / "public_safe_candidate_comparison.png"
        _draw_public_safe_visual_artifact(mask_path, mode="mask")
        _draw_public_safe_visual_artifact(overlay_path, mode="overlay")
        _draw_public_safe_visual_artifact(comparison_path, mode="comparison")

        findings = [
            _public_safe_finding(
                target="sclerotic_band",
                display_name="硬化带",
                area_px=120,
                area_ratio_in_image=0.02,
                area_ratio_in_anatomy=0.12,
            ),
            _public_safe_finding(
                target="cystic_change",
                display_name="囊性变",
                area_px=80,
                area_ratio_in_image=0.01,
                area_ratio_in_anatomy=0.08,
            ),
        ]
        visual_result = {
            "image_path": image_path,
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": image_path,
                "mask_path": str(mask_path),
                "overlay_path": str(overlay_path),
                "comparison_path": str(comparison_path),
            },
            "requested_targets": ["sclerotic_band", "cystic_change"],
            "requested_features": ["area_ratio_in_anatomy", "anatomy_match"],
            "visual_evidence": {
                "collapse": False,
                "sclerosis": "candidate_demo_only",
                "cystic_change": "candidate_demo_only",
                "joint_space_narrowing": False,
                "lesion_mask": str(mask_path),
                "confidence": 0.5,
                "texture_abnormality_score": 0.0,
                "lesion_area_ratio": 0.03,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "lesion_detected": True,
                "lesion_location": "synthetic femoral head region",
                "disease_target": "femoral_head_necrosis",
                "segmentation_quality": "public_safe_candidate_demo",
                "suspected_visual_findings": [
                    "硬化带：candidate_demo_only；公开安全合成样例候选区",
                    "囊性变：candidate_demo_only；公开安全合成样例候选区",
                ],
                "measurements": {"lesion_area_ratio": 0.03},
                "completeness": {
                    "candidate_lesion_mask": {
                        "status": "supported",
                        "reason": "Deterministic public-safe demo artifact, not real segmentation.",
                    }
                },
                "findings": findings,
                "segmentation_results": [],
                "visual_tool_plan": [
                    {"step": "public_safe_demo_localization", "tool_name": "deterministic_fixture"},
                    {"step": "public_safe_demo_overlay", "tool_name": "deterministic_fixture"},
                ],
            },
        }
        return {
            "status": "ok",
            "summary_path": str(output_dir / "public_safe_visual_summary.json"),
            "visual_analysis_result": visual_result,
            "visual_evidence_bundle": {
                "schema_version": "visual_evidence_bundle.v1",
                "present_findings": ["sclerotic_band", "cystic_change"],
                "numeric_evidence": {"finding_count": 2, "total_area_px": 200},
                "findings": findings,
            },
        }


def _public_safe_finding(
    *,
    target: str,
    display_name: str,
    area_px: int,
    area_ratio_in_image: float,
    area_ratio_in_anatomy: float,
) -> dict[str, Any]:
    return {
        "finding_id": f"public_safe_{target}",
        "target": target,
        "display_name": display_name,
        "status": "candidate_present",
        "regions": [],
        "confidence": 0.5,
        "evidence_basis": "public-safe synthetic demo candidate",
        "measurements": {
            "area_px": area_px,
            "area_ratio_in_image": area_ratio_in_image,
            "area_ratio_in_anatomy": area_ratio_in_anatomy,
            "anatomy_match": {
                "anatomy_name": "femoral_head",
                "candidate_index": 0,
                "overlap_anatomy_px": int(area_px * 0.7),
            },
        },
        "diagnosis_usable": False,
        "diagnosis_usable_level": "not_usable",
        "limitations": [
            "Synthetic public-safe fixture; not real patient data.",
            "Not a validated segmentation result.",
        ],
    }


def _draw_public_safe_visual_artifact(path: Path, *, mode: str) -> None:
    image = Image.new("RGB", (320, 240), (24, 28, 32))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 280, 200), outline=(180, 180, 180), width=2)
    if mode in {"overlay", "comparison"}:
        draw.rectangle((126, 92, 196, 150), outline=(255, 210, 0), width=4)
        draw.text((52, 18), "PUBLIC SAFE DEMO - NOT MEDICAL DATA", fill=(255, 210, 80))
    if mode == "mask":
        draw.rectangle((126, 92, 196, 150), fill=(255, 255, 255))
    if mode == "comparison":
        draw.line((160, 0, 160, 240), fill=(80, 120, 180), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _render_public_safe_suite_markdown(summary: dict[str, Any]) -> str:
    routing = summary.get("routing_decision", {})
    safety = summary.get("safety", {})
    lines = [
        "# Public-Safe MedScope MVP Demo",
        "",
        f"- status: {summary.get('status')}",
        f"- case_id: `{summary.get('case_id')}`",
        f"- selected_knowledge: `{routing.get('selected_knowledge')}`",
        f"- selected_vision_mode: `{routing.get('selected_vision_mode')}`",
        f"- public_safe: {safety.get('public_safe')}",
        f"- not clinical diagnosis: {safety.get('not_clinical_diagnosis')}",
        f"- real_fhn_data_required: {safety.get('real_fhn_data_required')}",
        "",
        "## Artifacts",
        "",
        f"- response: `{summary.get('response_path')}`",
        f"- evidence bundle: `{summary.get('evidence_bundle_path')}`",
        f"- memory audit: `{summary.get('memory_audit_path')}`",
        f"- follow-up QA: `{summary.get('qa_response_path')}`",
        "",
        "This demo uses a synthetic public_safe image and deterministic candidate visual evidence.",
        "It is not clinical diagnosis and not a segmentation benchmark.",
        "",
    ]
    return "\n".join(lines)


def _draw_synthetic_hip_xray(path: Path) -> None:
    width, height = 640, 520
    image = Image.new("L", (width, height), 20)
    draw = ImageDraw.Draw(image)

    # Pelvis-like anatomy sketch. This is deliberately schematic, not a real X-ray.
    draw.ellipse((86, 72, 274, 260), outline=118, width=8)
    draw.ellipse((366, 72, 554, 260), outline=118, width=8)
    draw.arc((130, 170, 300, 380), 205, 335, fill=132, width=10)
    draw.arc((340, 170, 510, 380), 205, 335, fill=132, width=10)
    draw.ellipse((214, 210, 304, 300), outline=150, width=7)
    draw.ellipse((336, 210, 426, 300), outline=150, width=7)
    draw.line((258, 288, 224, 500), fill=125, width=26)
    draw.line((382, 288, 416, 500), fill=125, width=26)
    draw.line((294, 260, 346, 260), fill=96, width=8)
    draw.rectangle((260, 232, 292, 256), outline=190, width=4)
    draw.rectangle((348, 232, 380, 256), outline=190, width=4)
    draw.arc((240, 214, 302, 278), 25, 150, fill=220, width=4)
    draw.arc((338, 214, 400, 278), 25, 150, fill=220, width=4)

    rgb = image.convert("RGB")
    marker = ImageDraw.Draw(rgb)
    marker.text((18, 18), "SYNTHETIC PUBLIC DEMO - NOT MEDICAL DATA", fill=(255, 210, 80))
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a public-safe synthetic demo fixture for MedScope Agent."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated fixture files.",
    )
    parser.add_argument(
        "--suite",
        action="store_true",
        help="Run the public-safe service, memory audit, and follow-up QA demo suite.",
    )
    args = parser.parse_args(argv)
    if args.suite:
        result = run_public_safe_demo_suite(output_dir=args.output_dir)
    else:
        result = prepare_public_demo_fixture(output_dir=args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
