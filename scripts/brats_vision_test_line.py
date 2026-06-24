from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from agents.vision_agent import VisionAgent
from tools.brats_evaluation_tool import BratsEvaluationTool
from tools.medsam2_segmentation_tool import (
    MedSAM2CommandRunner,
    MedSAM2SegmentationTool,
    inspect_medsam2_configuration,
)
from tools.nifti_mask_reader_tool import NibabelLoader, NiftiMaskReaderTool
from tools.nifti_overlay_generation_tool import NiftiOverlayGenerationTool
from tools.segmentation_tool import SegmentationTool
from tools.knowledge_builder_tool import KnowledgeBuilderTool


DEFAULT_IMAGE = Path("data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz")
DEFAULT_MASK = Path("data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz")
DEFAULT_MANIFEST = Path("data/external/brats_manifest.json")
DEFAULT_OUTPUT_DIR = Path("output/fake/brats_vision_test_line")


def run_brats_vision_test_line(
    image_path: Path | str = DEFAULT_IMAGE,
    mask_path: Path | str | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    result_json_path: Path | str | None = None,
    disease_name: str = "成人弥漫性胶质瘤",
    mode: str = "ground_truth",
    prompt: dict[str, Any] | None = None,
    reference_mask_path: Path | str | None = None,
    manifest_path: Path | str | None = None,
    case_id: str | None = None,
    prompt_from_reference_mask: bool = False,
) -> str:
    selected_case_id = case_id
    if manifest_path:
        case = _load_manifest_case(manifest_path, case_id)
        selected_case_id = case["case_id"]
        image_path = case["image_path"]
        if mask_path is None and mode == "ground_truth":
            mask_path = case.get("mask_path")
        if reference_mask_path is None:
            reference_mask_path = case.get("reference_mask_path") or case.get("mask_path")
        if disease_name == "成人弥漫性胶质瘤":
            disease_name = case.get("disease_name", disease_name)

    image = Path(image_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    if not image.exists():
        return json.dumps(
            {"status": "error", "error": f"Image not found: {image}"},
            ensure_ascii=False,
            indent=2,
        )
    if mode not in {"ground_truth", "medsam2"}:
        return json.dumps(
            {"status": "error", "error": f"Unsupported BraTS vision test mode: {mode}"},
            ensure_ascii=False,
            indent=2,
        )
    ground_truth_mask = Path(mask_path) if mask_path else DEFAULT_MASK
    if mode == "ground_truth" and not ground_truth_mask.exists():
        return json.dumps(
            {"status": "error", "error": f"Mask not found: {ground_truth_mask}"},
            ensure_ascii=False,
            indent=2,
        )

    case_name = selected_case_id or _case_name_from_image(image)
    mode_suffix = "_medsam2" if mode == "medsam2" else ""
    overlay_path = output / f"{case_name}{mode_suffix}_overlay.png"
    result_path = (
        Path(result_json_path)
        if result_json_path
        else output / f"{case_name}{mode_suffix}_vision_result.json"
    )
    segmentation_prompt = dict(prompt or {})
    if prompt_from_reference_mask:
        if not reference_mask_path:
            return json.dumps(
                {
                    "status": "error",
                    "error": "--prompt-from-reference-mask requires a reference mask.",
                },
                ensure_ascii=False,
                indent=2,
            )
        segmentation_prompt.update(generate_brats_prompt_from_reference_mask(reference_mask_path))

    disease_knowledge = _load_brats_disease_knowledge(disease_name)
    if mode == "ground_truth":
        result = VisionAgent().analyze_brats_nifti_ground_truth(
            image_path=str(image),
            mask_path=str(ground_truth_mask),
            overlay_path=str(overlay_path),
            disease_knowledge=disease_knowledge,
        )
        payload_mode = "brats_nifti_ground_truth"
    else:
        model_mask_path = Path(mask_path) if mask_path else output / f"{case_name}_medsam2_mask.nii.gz"
        segmentation_tool = SegmentationTool(
            mask_reader=NiftiMaskReaderTool(),
            overlay_generator=NiftiOverlayGenerationTool(),
            model_backend=MedSAM2SegmentationTool(runner=MedSAM2CommandRunner.from_env()),
        )
        result = VisionAgent(segmentation_tool=segmentation_tool).analyze_brats_with_segmentation_model(
            image_path=str(image),
            prompt=segmentation_prompt,
            mask_path=str(model_mask_path),
            overlay_path=str(overlay_path),
            disease_knowledge=disease_knowledge,
        )
        payload_mode = "brats_medsam2_model"
    payload: dict[str, Any] = {
        "status": "ok",
        "case_id": selected_case_id or case_name,
        "mode": payload_mode,
        "result_json_path": str(result_path),
        "result": result,
    }
    if mode == "medsam2":
        payload["segmentation_prompt"] = segmentation_prompt
    if reference_mask_path:
        payload["evaluation"] = BratsEvaluationTool().evaluate(
            prediction_mask_path=result["image_outputs"]["mask_path"],
            reference_mask_path=reference_mask_path,
        )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.dumps(payload, ensure_ascii=False, indent=2)


def run_brats_vision_manifest(
    manifest_path: Path | str = DEFAULT_MANIFEST,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    mode: str = "ground_truth",
    prompt: dict[str, Any] | None = None,
    summary_path: Path | str | None = None,
    prompt_from_reference_mask: bool = False,
) -> str:
    manifest = Path(manifest_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest_payload = _load_manifest(manifest)
    cases = manifest_payload.get("cases", [])
    summary_file = Path(summary_path) if summary_path else output / "summary.json"
    markdown_summary_file = summary_file.with_suffix(".md")

    case_summaries: list[dict[str, Any]] = []
    ok_count = 0
    for case in cases:
        case_id = case["case_id"]
        try:
            result_payload = json.loads(
                run_brats_vision_test_line(
                    output_dir=output,
                    mode=mode,
                    prompt=prompt,
                    manifest_path=manifest,
                    case_id=case_id,
                    prompt_from_reference_mask=prompt_from_reference_mask,
                )
            )
        except Exception as exc:
            result_payload = {
                "status": "error",
                "case_id": case_id,
                "mode": mode,
                "error": f"{type(exc).__name__}: {exc}",
            }
        if result_payload.get("status") == "ok":
            ok_count += 1
        case_summaries.append(
            {
                "case_id": case_id,
                "status": result_payload.get("status"),
                "mode": result_payload.get("mode"),
                "result_json_path": result_payload.get("result_json_path"),
                "overlay_path": result_payload.get("result", {})
                .get("image_outputs", {})
                .get("overlay_path"),
                "evaluation": result_payload.get("evaluation"),
                "error": result_payload.get("error"),
            }
        )

    payload = {
        "status": "ok" if ok_count == len(cases) else "partial_error",
        "manifest_path": str(manifest),
        "summary_path": str(summary_file),
        "summary_markdown_path": str(markdown_summary_file),
        "case_count": len(cases),
        "ok_count": ok_count,
        "failed_case_ids": [
            case["case_id"] for case in case_summaries if case.get("status") != "ok"
        ],
        "aggregate": _aggregate_case_metrics(case_summaries),
        "cases": case_summaries,
    }
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_summary_file.write_text(_render_manifest_markdown_summary(payload), encoding="utf-8")
    return json.dumps(payload, ensure_ascii=False, indent=2)


def validate_brats_manifest(manifest_path: Path | str = DEFAULT_MANIFEST) -> str:
    manifest = Path(manifest_path)
    manifest_payload = _load_manifest(manifest)
    cases = manifest_payload.get("cases", [])
    case_results: list[dict[str, Any]] = []
    manifest_errors: list[str] = []
    if not cases:
        manifest_errors.append("No cases found in BraTS manifest")

    for index, case in enumerate(cases):
        case_id = case.get("case_id") or f"case_{index}"
        errors: list[str] = []
        resolved_paths: dict[str, str | None] = {}

        if not case.get("case_id"):
            errors.append("case_id is required")
        for key in ("image_path", "mask_path", "reference_mask_path"):
            value = case.get(key)
            if not value:
                errors.append(f"{key} is required")
                resolved_paths[key] = None
                continue
            resolved = _resolve_manifest_path(value, manifest.parent)
            resolved_paths[key] = str(resolved)
            if not resolved.exists():
                errors.append(f"{key} not found: {resolved}")

        case_results.append(
            {
                "case_id": case_id,
                "status": "invalid" if errors else "ok",
                "errors": errors,
                "resolved_paths": resolved_paths,
            }
        )

    valid_count = sum(1 for case in case_results if case["status"] == "ok")
    payload = {
        "status": "ok" if valid_count == len(cases) and not manifest_errors else "invalid",
        "manifest_path": str(manifest),
        "case_count": len(cases),
        "valid_count": valid_count,
        "errors": manifest_errors,
        "invalid_case_ids": [
            case["case_id"] for case in case_results if case["status"] != "ok"
        ],
        "cases": case_results,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def check_brats_medsam2_readiness(manifest_path: Path | str = DEFAULT_MANIFEST) -> str:
    manifest_validation = json.loads(validate_brats_manifest(manifest_path))
    medsam2_configuration = inspect_medsam2_configuration()
    errors: list[str] = []

    if manifest_validation.get("status") != "ok":
        errors.append("BraTS manifest is invalid.")
    if not medsam2_configuration.get("command_template_present"):
        errors.append("MEDSAM2_COMMAND_TEMPLATE is required.")
    missing_placeholders = medsam2_configuration.get("missing_command_template_placeholders") or []
    if missing_placeholders:
        errors.append(
            "MEDSAM2_COMMAND_TEMPLATE missing required placeholders: "
            + ", ".join(missing_placeholders)
        )
    if medsam2_configuration.get("repo_path_present") and not medsam2_configuration.get("repo_path_exists"):
        errors.append(f"MEDSAM2_REPO_PATH not found: {medsam2_configuration.get('repo_path')}")
    if medsam2_configuration.get("timeout_error"):
        errors.append(str(medsam2_configuration["timeout_error"]))

    payload = {
        "status": "ok" if not errors else "not_ready",
        "manifest_path": str(Path(manifest_path)),
        "manifest_validation": manifest_validation,
        "medsam2_configuration": medsam2_configuration,
        "errors": errors,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def generate_brats_prompts_from_manifest(
    manifest_path: Path | str = DEFAULT_MANIFEST,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    summary_path: Path | str | None = None,
) -> str:
    manifest = Path(manifest_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest_payload = _load_manifest(manifest)
    cases = manifest_payload.get("cases", [])
    summary_file = Path(summary_path) if summary_path else output / "prompts_summary.json"
    markdown_summary_file = summary_file.with_suffix(".md")

    case_summaries: list[dict[str, Any]] = []
    ok_count = 0
    for raw_case in cases:
        case_id = raw_case.get("case_id", "unknown_case")
        try:
            case = _load_manifest_case(manifest, case_id)
            reference_mask_path = case.get("reference_mask_path") or case.get("mask_path")
            if not reference_mask_path:
                raise ValueError(f"reference_mask_path is required for case: {case_id}")
            prompt = generate_brats_prompt_from_reference_mask(reference_mask_path)
            prompt_path = output / f"{case_id}_prompt.json"
            prompt_overlay_path = output / f"{case_id}_prompt_overlay.png"
            prompt_path.write_text(json.dumps(prompt, ensure_ascii=False, indent=2), encoding="utf-8")
            _write_prompt_overlay(case["image_path"], prompt, prompt_overlay_path)
            ok_count += 1
            case_summaries.append(
                {
                    "case_id": case_id,
                    "status": "ok",
                    "prompt_json_path": str(prompt_path),
                    "prompt_overlay_path": str(prompt_overlay_path),
                    "prompt": prompt,
                    "error": None,
                }
            )
        except Exception as exc:
            case_summaries.append(
                {
                    "case_id": case_id,
                    "status": "error",
                    "prompt_json_path": None,
                    "prompt_overlay_path": None,
                    "prompt": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    payload = {
        "status": "ok" if ok_count == len(cases) and cases else "partial_error",
        "manifest_path": str(manifest),
        "summary_path": str(summary_file),
        "summary_markdown_path": str(markdown_summary_file),
        "case_count": len(cases),
        "ok_count": ok_count,
        "failed_case_ids": [
            case["case_id"] for case in case_summaries if case.get("status") != "ok"
        ],
        "cases": case_summaries,
    }
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_summary_file.write_text(_render_prompt_markdown_summary(payload), encoding="utf-8")
    return json.dumps(payload, ensure_ascii=False, indent=2)


def generate_brats_prompt_from_reference_mask(reference_mask_path: Path | str) -> dict[str, Any]:
    mask_volume = NibabelLoader().load(reference_mask_path).get_fdata()
    nonzero = mask_volume > 0
    if not bool(nonzero.any()):
        raise ValueError(f"Reference mask has no tumor labels: {reference_mask_path}")

    coords = nonzero.nonzero()
    x_min, x_max = int(coords[0].min()), int(coords[0].max())
    y_min, y_max = int(coords[1].min()), int(coords[1].max())
    z_min, z_max = int(coords[2].min()), int(coords[2].max())
    slice_index = _largest_nonzero_slice(mask_volume)
    slice_mask = mask_volume[:, :, slice_index] > 0
    slice_coords = slice_mask.nonzero()
    slice_x_min, slice_x_max = int(slice_coords[0].min()), int(slice_coords[0].max())
    slice_y_min, slice_y_max = int(slice_coords[1].min()), int(slice_coords[1].max())
    labels = sorted({int(value) for value in mask_volume[nonzero].ravel().tolist()})

    return {
        "source": "reference_mask_bbox",
        "reference_mask_path": str(reference_mask_path),
        "label_ids": labels,
        "slice_index": slice_index,
        "boxes": [[slice_x_min, slice_y_min, slice_x_max + 1, slice_y_max + 1]],
        "box_3d": [x_min, y_min, z_min, x_max + 1, y_max + 1, z_max + 1],
    }


def _largest_nonzero_slice(mask_volume: Any) -> int:
    best_index = 0
    best_count = -1
    for z in range(mask_volume.shape[2]):
        count = int((mask_volume[:, :, z] > 0).sum())
        if count > best_count:
            best_index = z
            best_count = count
    return best_index


def _write_prompt_overlay(image_path: Path | str, prompt: dict[str, Any], output_path: Path | str) -> Path:
    volume = NibabelLoader().load(image_path).get_fdata()
    slice_index = int(prompt["slice_index"])
    if len(volume.shape) == 4:
        slice_data = volume[:, :, slice_index, 0]
    else:
        slice_data = volume[:, :, slice_index]
    image = _grayscale_rgba(slice_data.tolist())
    draw = ImageDraw.Draw(image)
    for box in prompt.get("boxes", []):
        x_min, y_min, x_max, y_max = [int(value) for value in box]
        draw.rectangle((x_min, y_min, x_max, y_max), outline=(255, 0, 0, 255), width=3)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


def _grayscale_rgba(image_slice: list[list[float]]) -> Image.Image:
    flat = [value for row in image_slice for value in row]
    low = min(flat)
    high = max(flat)
    scale = 255.0 / (high - low) if high > low else 1.0
    height = len(image_slice)
    width = len(image_slice[0]) if height else 0
    image = Image.new("L", (width, height), 0)
    pixels = image.load()
    for y, row in enumerate(image_slice):
        for x, value in enumerate(row):
            pixels[x, y] = int(max(0, min(255, (value - low) * scale)))
    return image.convert("RGBA")


def _case_name_from_image(image_path: Path) -> str:
    name = image_path.name
    for suffix in (".nii.gz", ".nii", ".png", ".jpg", ".jpeg"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return image_path.stem


def _load_brats_disease_knowledge(disease_name: str) -> dict[str, Any]:
    if disease_name != "成人弥漫性胶质瘤":
        return {"disease_name": disease_name}
    try:
        return KnowledgeBuilderTool().load_guideline_knowledge("diffuse_glioma_brats")
    except FileNotFoundError:
        return {"disease_name": disease_name}


def _load_manifest_case(manifest_path: Path | str, case_id: str | None) -> dict[str, Any]:
    manifest = Path(manifest_path)
    payload = _load_manifest(manifest)
    cases = payload.get("cases", [])
    if not cases:
        raise ValueError(f"No cases found in BraTS manifest: {manifest}")
    if case_id is None:
        case = cases[0]
    else:
        matches = [candidate for candidate in cases if candidate.get("case_id") == case_id]
        if not matches:
            raise ValueError(f"Case not found in BraTS manifest: {case_id}")
        case = matches[0]
    resolved = dict(case)
    for key in ("image_path", "mask_path", "reference_mask_path"):
        if key in resolved and resolved[key]:
            resolved[key] = str(_resolve_manifest_path(resolved[key], manifest.parent))
    return resolved


def _load_manifest(manifest_path: Path | str) -> dict[str, Any]:
    return json.loads(Path(manifest_path).read_text(encoding="utf-8"))


def _aggregate_case_metrics(case_summaries: list[dict[str, Any]]) -> dict[str, float | None]:
    dice_keys = ("whole_tumor_dice", "tumor_core_dice", "enhancing_tumor_dice")
    aggregate: dict[str, float | None] = {}
    for dice_key in dice_keys:
        values = [
            case["evaluation"][dice_key]
            for case in case_summaries
            if case.get("evaluation") and dice_key in case["evaluation"]
        ]
        metric_name = f"mean_{dice_key}"
        aggregate[metric_name] = sum(values) / len(values) if values else None
    return aggregate


def _render_manifest_markdown_summary(summary: dict[str, Any]) -> str:
    aggregate = summary.get("aggregate", {})
    lines = [
        "# BraTS Vision Test Line Summary",
        "",
        f"- status: {summary.get('status')}",
        f"- manifest: {summary.get('manifest_path')}",
        f"- cases: {summary.get('ok_count')}/{summary.get('case_count')} ok",
        f"- failed_case_ids: {', '.join(summary.get('failed_case_ids') or []) or 'none'}",
        "",
        "## Aggregate",
        "",
    ]
    for key in ("mean_whole_tumor_dice", "mean_tumor_core_dice", "mean_enhancing_tumor_dice"):
        lines.append(f"- {key}: {aggregate.get(key)}")
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| case_id | status | mode | whole_tumor_dice | tumor_core_dice | enhancing_tumor_dice | overlay | result | error |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for case in summary.get("cases", []):
        evaluation = case.get("evaluation") or {}
        lines.append(
            "| {case_id} | {status} | {mode} | {whole} | {core} | {enhancing} | {overlay} | {result} | {error} |".format(
                case_id=case.get("case_id"),
                status=case.get("status"),
                mode=case.get("mode"),
                whole=evaluation.get("whole_tumor_dice"),
                core=evaluation.get("tumor_core_dice"),
                enhancing=evaluation.get("enhancing_tumor_dice"),
                overlay=case.get("overlay_path"),
                result=case.get("result_json_path"),
                error=case.get("error") or "",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_prompt_markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# BraTS MedSAM2 Prompt Summary",
        "",
        f"- status: {summary.get('status')}",
        f"- manifest: {summary.get('manifest_path')}",
        f"- cases: {summary.get('ok_count')}/{summary.get('case_count')} ok",
        f"- failed_case_ids: {', '.join(summary.get('failed_case_ids') or []) or 'none'}",
        "",
        "| case_id | status | slice_index | boxes | box_3d | prompt | overlay | error |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in summary.get("cases", []):
        prompt = case.get("prompt") or {}
        lines.append(
            "| {case_id} | {status} | {slice_index} | {boxes} | {box_3d} | {prompt_path} | {overlay_path} | {error} |".format(
                case_id=case.get("case_id"),
                status=case.get("status"),
                slice_index=prompt.get("slice_index"),
                boxes=prompt.get("boxes"),
                box_3d=prompt.get("box_3d"),
                prompt_path=case.get("prompt_json_path"),
                overlay_path=case.get("prompt_overlay_path"),
                error=case.get("error") or "",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _resolve_manifest_path(path_value: str, manifest_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute() or path.exists():
        return path
    return manifest_dir / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BraTS/glioma Vision Agent test line.")
    parser.add_argument(
        "--mode",
        choices=["ground_truth", "medsam2"],
        default="ground_truth",
        help="Segmentation mode for the test line.",
    )
    parser.add_argument("--manifest", help="Optional BraTS manifest JSON path.")
    parser.add_argument("--case-id", help="Case id to select from --manifest. Defaults to the first case.")
    parser.add_argument(
        "--all-cases",
        action="store_true",
        help="Run all cases from --manifest and write a summary JSON.",
    )
    parser.add_argument(
        "--validate-manifest",
        action="store_true",
        help="Validate manifest case ids and image/mask/reference paths without running VisionAgent.",
    )
    parser.add_argument(
        "--check-medsam2",
        action="store_true",
        help="Check BraTS manifest and MedSAM2 runner readiness without running inference.",
    )
    parser.add_argument(
        "--generate-prompts",
        action="store_true",
        help="Generate MedSAM2 bbox prompt JSON files from manifest reference masks without running inference.",
    )
    parser.add_argument("--summary-json", help="Optional explicit summary JSON path for --all-cases.")
    parser.add_argument("--image", default=str(DEFAULT_IMAGE), help="Input BraTS MRI NIfTI path.")
    parser.add_argument(
        "--mask",
        help=(
            "Ground-truth segmentation path in ground_truth mode, or expected "
            "model mask output path in medsam2 mode."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for overlay and JSON result. Defaults to output/fake.",
    )
    parser.add_argument("--result-json", help="Optional explicit JSON result path.")
    parser.add_argument("--disease-name", default="成人弥漫性胶质瘤")
    parser.add_argument("--prompt-json", default="{}", help="Prompt JSON for MedSAM2 mode.")
    parser.add_argument(
        "--reference-mask",
        help="Optional BraTS ground-truth mask used to evaluate model output Dice scores.",
    )
    parser.add_argument(
        "--prompt-from-reference-mask",
        action="store_true",
        help="Build a MedSAM2 test prompt from the reference mask bounding box.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.validate_manifest:
        output = validate_brats_manifest(args.manifest or DEFAULT_MANIFEST)
        print(output)
        payload = json.loads(output)
        if payload.get("status") != "ok":
            sys.exit(1)
        return
    if args.check_medsam2:
        output = check_brats_medsam2_readiness(args.manifest or DEFAULT_MANIFEST)
        print(output)
        payload = json.loads(output)
        if payload.get("status") != "ok":
            sys.exit(1)
        return
    if args.generate_prompts:
        output = generate_brats_prompts_from_manifest(
            manifest_path=args.manifest or DEFAULT_MANIFEST,
            output_dir=args.output_dir,
            summary_path=args.summary_json,
        )
        print(output)
        payload = json.loads(output)
        if payload.get("status") != "ok":
            sys.exit(1)
        return

    try:
        prompt = json.loads(args.prompt_json)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "error": f"Invalid --prompt-json: {exc}"}, ensure_ascii=False, indent=2))
        sys.exit(1)

    if args.all_cases:
        output = run_brats_vision_manifest(
            manifest_path=args.manifest or DEFAULT_MANIFEST,
            output_dir=args.output_dir,
            mode=args.mode,
            prompt=prompt,
            summary_path=args.summary_json,
            prompt_from_reference_mask=args.prompt_from_reference_mask,
        )
    else:
        output = run_brats_vision_test_line(
            image_path=args.image,
            mask_path=args.mask,
            output_dir=args.output_dir,
            result_json_path=args.result_json,
            disease_name=args.disease_name,
            mode=args.mode,
            prompt=prompt,
            reference_mask_path=args.reference_mask,
            manifest_path=args.manifest,
            case_id=args.case_id,
            prompt_from_reference_mask=args.prompt_from_reference_mask,
        )
    print(output)
    payload = json.loads(output)
    if payload.get("status") != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
