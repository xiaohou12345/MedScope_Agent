from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.brats_vision_test_line import (
    DEFAULT_MANIFEST,
    generate_brats_prompts_from_manifest,
    run_brats_vision_manifest,
    validate_brats_manifest,
)
from scripts.end_to_end_demo import (
    DEFAULT_IMAGE_PATH,
    DEFAULT_MASK_PATH,
    run_end_to_end_demo,
)


DEFAULT_OUTPUT_DIR = Path("output/fake/mainline_real_dataset")
DEFAULT_PATIENT_MESSAGE = "请基于这次 FLAIR MRI 做胶质瘤辅助分析"


def run_mainline_real_dataset_demo(
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    image_path: Path | str = DEFAULT_IMAGE_PATH,
    mask_path: Path | str = DEFAULT_MASK_PATH,
    patient_message: str = DEFAULT_PATIENT_MESSAGE,
) -> dict[str, Any]:
    output = _resolve_output_dir(Path(output_dir))
    output.mkdir(parents=True, exist_ok=True)

    manifest_validation = json.loads(validate_brats_manifest(manifest_path))
    prompt_generation = json.loads(
        generate_brats_prompts_from_manifest(
            manifest_path=manifest_path,
            output_dir=output / "prompts",
        )
    )
    vision_ground_truth = json.loads(
        run_brats_vision_manifest(
            manifest_path=manifest_path,
            output_dir=output / "vision_ground_truth",
            mode="ground_truth",
        )
    )
    end_to_end = run_end_to_end_demo(
        output_dir=output / "full_e2e",
        image_path=image_path,
        mask_path=mask_path,
        patient_message=patient_message,
        patient_info={
            "patient_id": "mainline_glioma_001",
            "age": 58,
            "sex": "male",
            "symptoms": ["头痛"],
        },
    )

    status = (
        "ok"
        if manifest_validation.get("status") == "ok"
        and prompt_generation.get("status") == "ok"
        and vision_ground_truth.get("status") == "ok"
        and end_to_end.get("routing_decision", {}).get("selected_skill")
        == "diffuse_glioma_brats"
        else "partial_error"
    )
    summary_path = output / "summary.json"
    run_markdown_path = output / "MAINLINE_RUN.md"
    payload: dict[str, Any] = {
        "status": status,
        "demo_name": "mainline_real_dataset_demo",
        "dataset": "BraTS2021",
        "disease_key": "diffuse_glioma_brats",
        "output_dir": str(output),
        "summary_path": str(summary_path),
        "run_markdown_path": str(run_markdown_path),
        "manifest_validation": manifest_validation,
        "prompt_generation": prompt_generation,
        "vision_ground_truth": vision_ground_truth,
        "end_to_end": end_to_end,
        "data_boundary": {
            "image_role": "real_public_medical_image",
            "mask_role": "BraTS ground-truth mask for contract validation and evaluation",
            "model_claim": "This run does not prove MedSAM2 automatic segmentation accuracy.",
        },
        "next_step_gate": {
            "required_for_automatic_lesion_claim": [
                "run MedSAM2 or a disease-specific segmentation backend without reference mask",
                "compare generated mask against reference mask",
                "review overlay quality before moving artifacts to output/real",
            ]
        },
    }
    _write_json(summary_path, payload)
    run_markdown_path.write_text(_render_run_markdown(payload), encoding="utf-8")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the reproducible mainline real dataset demo."
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--image-path", default=str(DEFAULT_IMAGE_PATH))
    parser.add_argument("--mask-path", default=str(DEFAULT_MASK_PATH))
    parser.add_argument("--message", default=DEFAULT_PATIENT_MESSAGE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_mainline_real_dataset_demo(
        output_dir=args.output_dir,
        manifest_path=args.manifest,
        image_path=args.image_path,
        mask_path=args.mask_path,
        patient_message=args.message,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_run_markdown(payload: dict[str, Any]) -> str:
    vision = payload.get("vision_ground_truth", {})
    end_to_end = payload.get("end_to_end", {})
    routing = end_to_end.get("routing_decision", {})
    aggregate = vision.get("aggregate", {})
    lines = [
        "# Mainline Real Dataset Demo",
        "",
        "## 目标",
        "",
        "用一条真实数据闭环固定当前主线：真实医学图像、guideline skill、skill-driven vision、结构化数值、诊断报告、evidence bundle 和 memory audit。",
        "",
        "## 数据边界",
        "",
        "- 数据集：BraTS2021 glioma MRI segmentation benchmark",
        "- 本轮图像是公开真实医学影像。",
        "- 本轮使用 ground-truth mask 验证 Agent 契约和证据流。",
        "- 这不是 MedSAM2 真实自动分割结果，也不证明自动分割模型达到人工标注精度。",
        "",
        "## 关键结果",
        "",
        f"- status: `{payload.get('status')}`",
        f"- selected_skill: `{routing.get('selected_skill')}`",
        f"- selected_vision_mode: `{routing.get('selected_vision_mode')}`",
        f"- manifest cases: `{vision.get('case_count')}`",
        f"- vision ok cases: `{vision.get('ok_count')}`",
        f"- mean_whole_tumor_dice: `{aggregate.get('mean_whole_tumor_dice')}`",
        f"- evidence_bundle: `{end_to_end.get('evidence_bundle_path')}`",
        f"- memory_audit: `{end_to_end.get('audit_path')}`",
        "",
        "## 主要产物",
        "",
        f"- summary: `{payload.get('summary_path')}`",
        f"- prompt summary: `{payload.get('prompt_generation', {}).get('summary_path')}`",
        f"- vision summary: `{vision.get('summary_path')}`",
        f"- e2e summary: `{end_to_end.get('summary_path')}`",
        "",
        "## 下一步门槛",
        "",
        "只有在不使用 reference mask 的情况下跑通 MedSAM2 或专病分割模型，并与 reference mask 做 Dice/QC 对比后，才能把它称为自动病灶分割能力。",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
