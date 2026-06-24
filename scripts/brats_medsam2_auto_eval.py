from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agents.vision_agent import VisionAgent
from scripts.brats_vision_test_line import DEFAULT_MANIFEST
from tools.brats_evaluation_tool import BratsEvaluationTool
from tools.medsam2_segmentation_tool import (
    MedSAM2CommandRunner,
    MedSAM2SegmentationTool,
    inspect_medsam2_configuration,
)
from tools.nifti_mask_reader_tool import NiftiMaskReaderTool
from tools.nifti_overlay_generation_tool import NiftiOverlayGenerationTool
from tools.segmentation_tool import SegmentationTool
from tools.knowledge_builder_tool import KnowledgeBuilderTool


DEFAULT_OUTPUT_DIR = Path("output/fake/brats_medsam2_auto_eval")
DISEASE_KEY = "diffuse_glioma_brats"
REFERENCE_PROMPT_SOURCES = {"reference_mask_bbox", "ground_truth_mask_bbox"}


def run_brats_medsam2_auto_eval(
    *,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    case_id: str = "brats2021_00030",
    prompt_path: Path | str | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    medsam2_runner: Any | None = None,
    allow_reference_prompt: bool = False,
) -> dict[str, Any]:
    manifest = Path(manifest_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    case = _load_case(manifest, case_id)

    if prompt_path is None:
        return _write_summary(output, {
            "status": "needs_prompt",
            "case_id": case_id,
            "disease_key": DISEASE_KEY,
            "real_call_attempted": False,
            "action_items": [
                "Provide a non-reference prompt, ideally source=vision_model_bbox, before running MedSAM2 auto evaluation.",
                "The reference mask may be used only after inference for Dice/QC evaluation.",
            ],
            "data_boundary": _data_boundary(),
        })

    prompt_file = Path(prompt_path)
    prompt = json.loads(prompt_file.read_text(encoding="utf-8"))
    prompt_source = str(prompt.get("source") or "unknown")
    if prompt_source in REFERENCE_PROMPT_SOURCES and not allow_reference_prompt:
        return _write_summary(output, {
            "status": "rejected_reference_prompt",
            "case_id": case_id,
            "disease_key": DISEASE_KEY,
            "prompt_path": str(prompt_file),
            "prompt_source": prompt_source,
            "reason": "reference-mask-derived prompts are not allowed for automatic segmentation evaluation.",
            "real_call_attempted": False,
            "data_boundary": _data_boundary(),
        })

    if medsam2_runner is None:
        readiness = inspect_medsam2_configuration()
        if not readiness.get("real_call_ready"):
            return _write_summary(output, {
                "status": "not_ready",
                "case_id": case_id,
                "disease_key": DISEASE_KEY,
                "prompt_path": str(prompt_file),
                "prompt_source": prompt_source,
                "real_call_attempted": False,
                "medsam2_configuration": readiness,
                "action_items": [
                    "Configure MEDSAM2_COMMAND_TEMPLATE before running automatic segmentation.",
                    "Use a prompt whose source is not reference_mask_bbox.",
                ],
                "data_boundary": _data_boundary(),
            })
        medsam2_runner = MedSAM2CommandRunner.from_env()

    knowledge = KnowledgeBuilderTool().load_guideline_knowledge(DISEASE_KEY)
    mask_path = output / f"{case_id}_medsam2_auto_mask.nii.gz"
    overlay_path = output / f"{case_id}_medsam2_auto_overlay.png"
    result_json_path = output / f"{case_id}_medsam2_auto_eval_result.json"
    segmentation_tool = SegmentationTool(
        mask_reader=NiftiMaskReaderTool(),
        overlay_generator=NiftiOverlayGenerationTool(),
        model_backend=MedSAM2SegmentationTool(runner=medsam2_runner),
    )
    result = VisionAgent(segmentation_tool=segmentation_tool).analyze_brats_with_segmentation_model(
        image_path=case["image_path"],
        prompt=prompt,
        mask_path=str(mask_path),
        overlay_path=str(overlay_path),
        disease_knowledge=knowledge,
    )
    evaluation = BratsEvaluationTool().evaluate(
        prediction_mask_path=result["image_outputs"]["mask_path"],
        reference_mask_path=case["reference_mask_path"],
    )
    payload = {
        "status": "ok",
        "case_id": case_id,
        "disease_key": DISEASE_KEY,
        "prompt_path": str(prompt_file),
        "prompt_source": prompt_source,
        "real_call_attempted": True,
        "result_json_path": str(result_json_path),
        "image_outputs": result["image_outputs"],
        "evaluation": evaluation,
        "result": result,
        "data_boundary": _data_boundary(),
    }
    result_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return _write_summary(output, payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate BraTS MedSAM2 auto segmentation with a non-reference prompt."
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--case-id", default="brats2021_00030")
    parser.add_argument("--prompt", dest="prompt_path")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--allow-reference-prompt", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_brats_medsam2_auto_eval(
        manifest_path=args.manifest,
        case_id=args.case_id,
        prompt_path=args.prompt_path,
        output_dir=args.output_dir,
        allow_reference_prompt=args.allow_reference_prompt,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") in {"ok", "needs_prompt", "not_ready"} else 1


def _load_case(manifest_path: Path, case_id: str) -> dict[str, str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for raw_case in manifest.get("cases", []):
        if raw_case.get("case_id") != case_id:
            continue
        base = manifest_path.parent
        return {
            "case_id": case_id,
            "image_path": str(_resolve_manifest_path(raw_case["image_path"], base)),
            "mask_path": str(_resolve_manifest_path(raw_case["mask_path"], base)),
            "reference_mask_path": str(
                _resolve_manifest_path(
                    raw_case.get("reference_mask_path") or raw_case["mask_path"],
                    base,
                )
            ),
        }
    raise ValueError(f"Case not found in BraTS manifest: {case_id}")


def _resolve_manifest_path(path_value: str, manifest_dir: Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else manifest_dir / path


def _data_boundary() -> dict[str, str]:
    return {
        "prompt_role": "non_reference_candidate_localization_required",
        "reference_mask_role": "evaluation_only",
        "model_mask_role": "automatic_candidate_segmentation",
        "diagnostic_claim": "not_clinical_grade_until_overlay_qc_and_metric_review",
    }


def _write_summary(output_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
