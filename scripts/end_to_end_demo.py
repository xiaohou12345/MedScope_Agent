from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from agents.gaodoctor_agent import GaoDoctorAgent
from api.service import MedScopeService
from memory.memory_manager import MemoryManager


DEFAULT_OUTPUT_DIR = Path("output/fake/end_to_end_demo")
DEFAULT_STANDARD_DEMO_DIR = Path("output/fake/standard_demo")
DEFAULT_IMAGE_PATH = Path("data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz")
DEFAULT_MASK_PATH = Path("data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz")
DEFAULT_FHN_NO_MASK_IMAGE_PATH = Path(
    "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png"
)


def run_end_to_end_demo(
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    image_path: Path | str = DEFAULT_IMAGE_PATH,
    mask_path: Path | str | None = DEFAULT_MASK_PATH,
    patient_message: str = "请基于这次 FLAIR MRI 做胶质瘤辅助分析",
    patient_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    demo_dir = _resolve_output_dir(Path(output_dir))
    upload_dir = demo_dir / "uploads"
    memory_dir = demo_dir / "memory"
    artifacts_dir = demo_dir / "artifacts"
    for directory in (upload_dir, memory_dir, artifacts_dir):
        directory.mkdir(parents=True, exist_ok=True)

    uploaded_image_path = _copy_uploaded_image(Path(image_path), upload_dir)
    memory_manager = MemoryManager(base_dir=memory_dir)
    service = MedScopeService(
        gaodoctor_agent=GaoDoctorAgent(memory_manager=memory_manager),
    )
    payload = {
        "patient_message": patient_message,
        "image_path": str(uploaded_image_path),
        "patient_info": patient_info
        or {
            "patient_id": "demo_patient_001",
            "age": 58,
            "sex": "male",
            "symptoms": ["头痛"],
        },
    }
    if mask_path:
        payload["mask_path"] = str(mask_path)
    service_result = service.handle_request(payload)
    case_id = service_result["case_id"]
    evidence_bundle = memory_manager.get_evidence_bundle(case_id)
    audit = memory_manager.build_audit_summary(case_id)

    evidence_bundle_path = artifacts_dir / f"{case_id}_evidence_bundle.json"
    local_audit_path = artifacts_dir / f"{case_id}_audit.json"
    summary_path = demo_dir / "end_to_end_demo_summary.json"
    case_memory_path = Path(service_result["case_memory_path"])

    _write_json(evidence_bundle_path, evidence_bundle)
    _write_json(local_audit_path, audit)

    summary = {
        "demo_name": "medscope_standard_end_to_end_demo",
        "case_id": case_id,
        "demo_output_dir": str(demo_dir),
        "uploaded_image_path": str(uploaded_image_path),
        "case_memory_path": str(case_memory_path),
        "evidence_bundle_path": str(evidence_bundle_path),
        "audit_path": str(local_audit_path),
        "reply_to_patient": service_result.get("reply_to_patient"),
        "routing_decision": service_result.get("routing_decision", {}),
        "image_outputs": service_result.get("image_outputs", {}),
        "report": service_result.get("report", {}),
        "steps": {
            "upload": {
                "status": "completed",
                "input_path": str(image_path),
                "uploaded_image_path": str(uploaded_image_path),
                "reference_mask_path": str(mask_path) if mask_path else None,
            },
            "auto_skill_routing": service_result.get("routing_decision", {}),
            "visual_segmentation": {
                "status": "completed",
                "image_outputs": service_result.get("image_outputs", {}),
                "segmentation_quality": evidence_bundle["image_evidence"].get(
                    "segmentation_quality"
                ),
            },
            "diagnosis_report": {
                "status": "completed",
                "diagnostic_tendency": evidence_bundle["reasoning_evidence"].get(
                    "diagnostic_tendency"
                ),
            },
            "evidence_bundle": {
                "status": "completed",
                "path": str(evidence_bundle_path),
            },
            "memory_audit": {
                "status": "completed",
                "path": str(local_audit_path),
                "global_audit_path": str(Path("output/fake/memory_audit") / f"{case_id}_audit.json"),
            },
        },
    }
    _write_json(summary_path, summary)
    return {
        "case_id": case_id,
        "demo_output_dir": str(demo_dir),
        "uploaded_image_path": str(uploaded_image_path),
        "case_memory_path": str(case_memory_path),
        "summary_path": str(summary_path),
        "evidence_bundle_path": str(evidence_bundle_path),
        "audit_path": str(local_audit_path),
        "reply_to_patient": summary["reply_to_patient"],
        "routing_decision": summary["routing_decision"],
        "image_outputs": summary["image_outputs"],
        "report": summary["report"],
    }


def run_standard_demo_suite(
    output_dir: Path | str = DEFAULT_STANDARD_DEMO_DIR,
    *,
    include_fhn_no_mask: bool = False,
    no_mask_visual_pipeline_runner: Any | None = None,
) -> dict[str, Any]:
    demo_dir = _resolve_output_dir(Path(output_dir))
    demo_dir.mkdir(parents=True, exist_ok=True)

    case_summaries = [
        _run_demo_case(
            case_key="glioma_ground_truth",
            case_dir=demo_dir / "cases" / "glioma_ground_truth",
            input_image_path=DEFAULT_IMAGE_PATH,
            payload={
                "patient_message": "请基于这次 FLAIR MRI 做胶质瘤辅助分析",
                "mask_path": str(DEFAULT_MASK_PATH),
                "patient_info": {
                    "patient_id": "demo_glioma_001",
                    "age": 58,
                    "sex": "male",
                    "symptoms": ["头痛"],
                },
            },
        ),
        _run_demo_case(
            case_key="xray_insufficient_evidence",
            case_dir=demo_dir / "cases" / "xray_insufficient_evidence",
            input_image_path=None,
            payload={
                "patient_message": "左髋疼痛，X光能不能判断有没有早期股骨头坏死？",
                "patient_info": {
                    "patient_id": "demo_xray_001",
                    "age": 45,
                    "sex": "male",
                    "symptoms": ["髋关节疼痛"],
                },
            },
            placeholder_image_name="hip_xray_placeholder.png",
        ),
    ]
    if include_fhn_no_mask:
        case_summaries.append(
            _run_demo_case(
                case_key="fhn_no_mask_multifinding",
                case_dir=demo_dir / "cases" / "fhn_no_mask_multifinding",
                input_image_path=DEFAULT_FHN_NO_MASK_IMAGE_PATH
                if DEFAULT_FHN_NO_MASK_IMAGE_PATH.exists()
                else None,
                payload={
                    "patient_message": "右髋疼痛，上传 X 光，请根据股骨头坏死 skill 自动圈出候选征象",
                    "disease_key": "femoral_head_necrosis",
                    "vision_mode": "no_mask_skill",
                    "patient_info": {
                        "patient_id": "demo_fhn_no_mask_001",
                        "age": 45,
                        "sex": "male",
                        "symptoms": ["髋关节疼痛"],
                    },
                },
                placeholder_image_name="fhn_xray_placeholder.png",
                no_mask_visual_pipeline_runner=no_mask_visual_pipeline_runner,
            )
        )
    payload = {
        "demo_name": "medscope_standard_demo_suite",
        "status": "ok" if all(case["status"] == "ok" for case in case_summaries) else "partial_error",
        "case_count": len(case_summaries),
        "demo_output_dir": str(demo_dir),
        "summary_path": str(demo_dir / "standard_demo_summary.json"),
        "summary_markdown_path": str(demo_dir / "demo_summary.md"),
        "cases": case_summaries,
    }
    _write_json(Path(payload["summary_path"]), payload)
    Path(payload["summary_markdown_path"]).write_text(
        _render_standard_demo_markdown(payload),
        encoding="utf-8",
    )
    return payload


def _run_demo_case(
    *,
    case_key: str,
    case_dir: Path,
    input_image_path: Path | None,
    payload: dict[str, Any],
    placeholder_image_name: str | None = None,
    no_mask_visual_pipeline_runner: Any | None = None,
) -> dict[str, Any]:
    upload_dir = case_dir / "uploads"
    memory_dir = case_dir / "memory"
    artifacts_dir = case_dir / "artifacts"
    for directory in (upload_dir, memory_dir, artifacts_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if input_image_path is not None:
        uploaded_image_path = _copy_uploaded_image(input_image_path, upload_dir)
    else:
        uploaded_image_path = _create_placeholder_xray(upload_dir / (placeholder_image_name or "upload.png"))

    service_payload = dict(payload)
    service_payload["image_path"] = str(uploaded_image_path)
    memory_manager = MemoryManager(base_dir=memory_dir)
    service = MedScopeService(
        gaodoctor_agent=GaoDoctorAgent(
            memory_manager=memory_manager,
            no_mask_visual_pipeline_runner=no_mask_visual_pipeline_runner,
        ),
    )
    service_result = service.handle_request(service_payload)
    case_id = service_result["case_id"]
    evidence_bundle = memory_manager.get_evidence_bundle(case_id)
    audit = memory_manager.build_audit_summary(case_id)

    response_path = artifacts_dir / f"{case_key}_response.json"
    evidence_bundle_path = artifacts_dir / f"{case_key}_evidence_bundle.json"
    audit_path = artifacts_dir / f"{case_key}_audit.json"
    _write_json(response_path, service_result)
    _write_json(evidence_bundle_path, evidence_bundle)
    _write_json(audit_path, audit)

    image_outputs = service_result.get("image_outputs", {})
    analysis_status = service_result.get("analysis_status")
    visual_status = (
        "skipped_insufficient_evidence"
        if analysis_status in {"insufficient_evidence", "contraindicated_or_wrong_modality"}
        or image_outputs.get("mask_path") == "not_generated"
        else "completed"
    )
    return {
        "case_key": case_key,
        "status": "ok",
        "case_id": case_id,
        "case_dir": str(case_dir),
        "uploaded_image_path": str(uploaded_image_path),
        "response_path": str(response_path),
        "evidence_bundle_path": str(evidence_bundle_path),
        "audit_path": str(audit_path),
        "case_memory_path": service_result.get("case_memory_path"),
        "analysis_status": analysis_status,
        "routing_decision": service_result.get("routing_decision", {}),
        "alignment_plan": service_result.get("alignment_plan", {}),
        "image_outputs": image_outputs,
        "required_next_images": service_result.get("required_next_images", []),
        "reply_to_patient": service_result.get("reply_to_patient"),
        "steps": {
            "upload": {
                "status": "completed",
                "uploaded_image_path": str(uploaded_image_path),
            },
            "auto_skill_routing": service_result.get("routing_decision", {}),
            "visual_segmentation": {
                "status": visual_status,
                "image_outputs": image_outputs,
                "segmentation_quality": evidence_bundle["image_evidence"].get("segmentation_quality"),
            },
            "diagnosis_report": {
                "status": "completed",
                "diagnostic_tendency": evidence_bundle["reasoning_evidence"].get("diagnostic_tendency"),
            },
            "evidence_bundle": {
                "status": "completed",
                "path": str(evidence_bundle_path),
            },
            "memory_audit": {
                "status": "completed",
                "path": str(audit_path),
            },
        },
    }


def _resolve_output_dir(output_dir: Path) -> Path:
    output_fake = Path("output/fake")
    if output_dir.is_absolute():
        try:
            output_dir.relative_to(output_fake.resolve())
            return output_dir
        except ValueError:
            return output_fake / output_dir.name
    if output_dir.parts[:2] == ("output", "fake"):
        return output_dir
    return output_fake / output_dir


def _copy_uploaded_image(image_path: Path, upload_dir: Path) -> Path:
    if not image_path.exists():
        raise FileNotFoundError(f"demo image does not exist: {image_path}")
    uploaded_image_path = upload_dir / image_path.name
    shutil.copyfile(image_path, uploaded_image_path)
    return uploaded_image_path


def _create_placeholder_xray(path: Path) -> Path:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        path.write_bytes(b"placeholder xray image")
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("L", (96, 96), 28)
    draw = ImageDraw.Draw(image)
    draw.ellipse((22, 22, 74, 74), outline=140, width=3)
    draw.line((48, 74, 48, 94), fill=110, width=5)
    image.save(path)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_standard_demo_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# MedScope Standard Demo",
        "",
        f"- status: {payload['status']}",
        f"- case_count: {payload['case_count']}",
        f"- output_dir: `{payload['demo_output_dir']}`",
        "",
        "| case_key | analysis_status | selected_skill | vision | response | evidence | audit |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in payload["cases"]:
        routing = case.get("routing_decision", {})
        steps = case.get("steps", {})
        vision = steps.get("visual_segmentation", {})
        lines.append(
            "| "
            + " | ".join(
                [
                    str(case.get("case_key", "")),
                    str(case.get("analysis_status", "")),
                    str(routing.get("selected_skill", "")),
                    str(vision.get("status", "")),
                    f"`{case.get('response_path', '')}`",
                    f"`{case.get('evidence_bundle_path', '')}`",
                    f"`{case.get('audit_path', '')}`",
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the standard MedScope end-to-end demo."
    )
    parser.add_argument("--suite", action="store_true", help="Run both standard demo cases.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--image-path", default=str(DEFAULT_IMAGE_PATH))
    parser.add_argument("--mask-path", default=str(DEFAULT_MASK_PATH))
    parser.add_argument("--message", default="请基于这次 FLAIR MRI 做胶质瘤辅助分析")
    parser.add_argument("--patient-id", default="demo_patient_001")
    parser.add_argument("--age", type=int, default=58)
    parser.add_argument("--sex", default="male")
    parser.add_argument("--symptom", action="append", default=["头痛"])
    parser.add_argument("--risk-factor", action="append", default=[])
    parser.add_argument(
        "--include-fhn-no-mask",
        action="store_true",
        help="Include the experimental FHN no-mask VLM + MedSAM2 demo case in --suite.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.suite:
        output_dir = (
            DEFAULT_STANDARD_DEMO_DIR
            if args.output_dir == str(DEFAULT_OUTPUT_DIR)
            else Path(args.output_dir)
        )
        result = run_standard_demo_suite(
            output_dir=output_dir,
            include_fhn_no_mask=args.include_fhn_no_mask,
        )
    else:
        result = run_end_to_end_demo(
            output_dir=Path(args.output_dir),
            image_path=Path(args.image_path),
            mask_path=Path(args.mask_path) if args.mask_path else None,
            patient_message=args.message,
            patient_info={
                "patient_id": args.patient_id,
                "age": args.age,
                "sex": args.sex,
                "symptoms": args.symptom,
                "risk_factors": args.risk_factor,
            },
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
