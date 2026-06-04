from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from api.service import MedScopeService
from llm.connectivity import ApiConnectivityChecker


DEFAULT_OUTPUT_DIR = Path("output/fake/fhn_real_vlm_multiview_demo")
DEFAULT_MESSAGE = "左髋疼痛，上传髋关节多体位 X 光，请根据股骨头坏死 skill 提取候选视觉证据。"


def run_demo(
    *,
    ap_image: Path | str,
    lateral_image: Path | str,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    frog_lateral_image: Path | str | None = None,
    message: str = DEFAULT_MESSAGE,
    dry_run: bool = False,
    service_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    demo_dir = Path(output_dir)
    demo_dir.mkdir(parents=True, exist_ok=True)

    image_paths = [str(ap_image), str(lateral_image)]
    if frog_lateral_image:
        image_paths.append(str(frog_lateral_image))

    readiness = ApiConnectivityChecker().inspect_real_vlm_validation()
    _write_json(demo_dir / "readiness.json", readiness)
    input_manifest = {
        "ap_image": str(ap_image),
        "lateral_image": str(lateral_image),
        "frog_lateral_image": str(frog_lateral_image) if frog_lateral_image else None,
        "image_paths": image_paths,
        "message": message,
        "vision_mode": "real_vlm_validation",
    }
    _write_json(demo_dir / "input_manifest.json", input_manifest)

    if dry_run:
        summary = {
            "status": "dry_run",
            "demo_name": "fhn_real_vlm_multiview_demo",
            "vision_mode": "real_vlm_validation",
            "output_dir": str(demo_dir),
            "readiness_path": str(demo_dir / "readiness.json"),
            "input_manifest_path": str(demo_dir / "input_manifest.json"),
            "readiness": readiness,
            "network_call_attempted": False,
        }
        _write_json(demo_dir / "summary.json", summary)
        return summary

    service = service_factory() if service_factory else MedScopeService()
    service_result = service.handle_request(
        {
            "patient_message": message,
            "image_paths": image_paths,
            "patient_info": {"symptoms": ["髋关节疼痛"]},
            "vision_mode": "real_vlm_validation",
        }
    )
    evidence_bundle = service_result.get("evidence_bundle", {})
    visual_bundle = service_result.get("visual_evidence_bundle", {})
    report = service_result.get("report", {})
    audit = service_result.get("memory_audit", {})

    _write_json(demo_dir / "response.json", service_result)
    _write_json(demo_dir / "evidence_bundle.json", evidence_bundle)
    _write_json(demo_dir / "visual_evidence_bundle.json", visual_bundle)
    _write_json(demo_dir / "diagnosis_report.json", report)
    _write_json(demo_dir / "audit.json", audit)

    routing = service_result.get("routing_decision") or {}
    evidence_items = visual_bundle.get("evidence_items") or []
    summary = {
        "status": "ok",
        "demo_name": "fhn_real_vlm_multiview_demo",
        "case_id": service_result.get("case_id"),
        "selected_skill": routing.get("selected_skill"),
        "selected_vision_mode": routing.get("selected_vision_mode"),
        "evidence_item_count": len(evidence_items),
        "reply_to_patient": service_result.get("reply_to_patient"),
        "output_dir": str(demo_dir),
        "summary_path": str(demo_dir / "summary.json"),
        "readiness_path": str(demo_dir / "readiness.json"),
        "input_manifest_path": str(demo_dir / "input_manifest.json"),
        "response_path": str(demo_dir / "response.json"),
        "evidence_bundle_path": str(demo_dir / "evidence_bundle.json"),
        "visual_evidence_bundle_path": str(demo_dir / "visual_evidence_bundle.json"),
        "diagnosis_report_path": str(demo_dir / "diagnosis_report.json"),
        "audit_path": str(demo_dir / "audit.json"),
        "readiness": readiness,
        "safety_boundary": {
            "vlm_output_role": "candidate_visual_evidence",
            "segmentation_claim": "not_claimed",
            "measurement_claim": "not_claimed",
        },
    }
    _write_json(demo_dir / "summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run FHN real VLM multi-view validation demo."
    )
    parser.add_argument("--ap-image", required=True)
    parser.add_argument("--lateral-image", required=True)
    parser.add_argument("--frog-lateral-image")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_demo(
        ap_image=args.ap_image,
        lateral_image=args.lateral_image,
        frog_lateral_image=args.frog_lateral_image,
        output_dir=args.output_dir,
        message=args.message,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
