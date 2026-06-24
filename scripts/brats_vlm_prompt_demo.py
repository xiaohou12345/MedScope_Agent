from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from tools.nifti_mask_reader_tool import NibabelLoader
from tools.knowledge_builder_tool import KnowledgeBuilderTool
from tools.vision_prompt_generator import OpenAICompatibleVisionClient, VisionPromptGenerator


DEFAULT_IMAGE = Path("data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz")
DEFAULT_OUTPUT_DIR = Path("output/fake/brats_vlm_prompt_demo")
DEFAULT_MESSAGE = "请在这张 FLAIR MRI 切片中定位疑似胶质瘤 whole tumor 候选区域，只返回候选框。"


def run_brats_vlm_prompt_demo(
    *,
    image_path: Path | str = DEFAULT_IMAGE,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    slice_index: int | None = None,
    patient_message: str = DEFAULT_MESSAGE,
    client: Any | None = None,
) -> dict[str, Any]:
    image = Path(image_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    selected_slice, depth = _resolve_slice_index(image, slice_index)
    slice_png_path = output / f"{_case_name(image)}_slice_{selected_slice:03d}.png"
    prompt_result_path = output / f"{_case_name(image)}_vlm_prompt_result.json"
    medsam2_prompt_path = output / f"{_case_name(image)}_vision_model_prompt.json"
    bbox_overlay_path = output / f"{_case_name(image)}_vision_model_prompt_overlay.png"

    _write_nifti_slice_png(
        image_path=image,
        slice_index=selected_slice,
        output_path=slice_png_path,
    )
    knowledge = KnowledgeBuilderTool().load_guideline_knowledge("diffuse_glioma_brats")
    using_default_client = client is None
    try:
        prompt_result = VisionPromptGenerator(
            client=client or OpenAICompatibleVisionClient()
        ).generate(
            image_path=slice_png_path,
            disease_knowledge=_prompt_knowledge(knowledge),
            patient_message=patient_message,
        )
        real_call_attempted = using_default_client
    except (RuntimeError, OSError) as exc:
        prompt_result = {
            "status": "vlm_not_ready",
            "image_path": str(slice_png_path),
            "segmentation_prompt": {
                "source": "vision_model_bbox",
                "boxes": [],
                "points": [],
            },
            "suspected_regions": [],
            "limitations": [],
            "diagnosis_usable": False,
            "errors": [str(exc)],
        }
        real_call_attempted = using_default_client and not str(exc).startswith("Missing ")
    medsam2_prompt = _build_medsam2_prompt(
        prompt_result=prompt_result,
        slice_index=selected_slice,
    )
    _write_json(prompt_result_path, prompt_result)
    _write_json(medsam2_prompt_path, medsam2_prompt)
    _write_bbox_overlay(
        image_path=slice_png_path,
        boxes=medsam2_prompt.get("boxes") or [],
        output_path=bbox_overlay_path,
    )
    payload = {
        "status": prompt_result.get("status"),
        "image_path": str(image),
        "slice_index": selected_slice,
        "volume_depth": depth,
        "slice_png_path": str(slice_png_path),
        "prompt_result_path": str(prompt_result_path),
        "medsam2_prompt_path": str(medsam2_prompt_path),
        "bbox_overlay_path": str(bbox_overlay_path),
        "prompt_source": medsam2_prompt["source"],
        "boxes": medsam2_prompt["boxes"],
        "real_call_attempted": real_call_attempted,
        "errors": list(prompt_result.get("errors") or []),
        "data_boundary": {
            "slice_selection": "explicit" if slice_index is not None else "middle_slice",
            "reference_mask_used": False,
            "prompt_role": "vision_model_candidate_localization",
            "diagnosis_usable": False,
        },
    }
    _write_json(output / "summary.json", payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a non-reference BraTS MedSAM2 prompt from a VLM over one NIfTI slice."
    )
    parser.add_argument("--image", default=str(DEFAULT_IMAGE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--slice-index", type=int)
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_dotenv_local()
    args = build_parser().parse_args(argv)
    payload = run_brats_vlm_prompt_demo(
        image_path=args.image,
        output_dir=args.output_dir,
        slice_index=args.slice_index,
        patient_message=args.message,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") in {"ok", "no_suspected_region"} else 1


def _resolve_slice_index(image_path: Path, slice_index: int | None) -> tuple[int, int]:
    volume = NibabelLoader().load(image_path).get_fdata()
    if volume.ndim == 4:
        volume = volume[:, :, :, 0]
    if volume.ndim != 3:
        raise ValueError(f"Expected 3D or 4D BraTS NIfTI image, got shape {volume.shape}.")
    depth = int(volume.shape[2])
    selected = depth // 2 if slice_index is None else int(slice_index)
    if selected < 0 or selected >= depth:
        raise ValueError(f"slice_index out of range: {selected}; depth={depth}")
    return selected, depth


def _write_nifti_slice_png(
    *,
    image_path: Path,
    slice_index: int,
    output_path: Path,
) -> Path:
    import numpy as np

    volume = NibabelLoader().load(image_path).get_fdata()
    if volume.ndim == 4:
        volume = volume[:, :, :, 0]
    slice_data = volume[:, :, slice_index]
    finite = slice_data[np.isfinite(slice_data)]
    if finite.size == 0:
        normalized = np.zeros(slice_data.shape, dtype=np.uint8)
    else:
        nonzero = finite[finite != 0]
        reference = nonzero if nonzero.size else finite
        low, high = np.percentile(reference, [0.5, 99.5])
        if high <= low:
            low, high = float(reference.min()), float(reference.max())
        if high <= low:
            normalized = np.zeros(slice_data.shape, dtype=np.uint8)
        else:
            clipped = np.clip(slice_data, low, high)
            normalized = ((clipped - low) / (high - low) * 255.0).astype(np.uint8)
            normalized[slice_data == 0] = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(normalized).convert("RGB").save(output_path)
    return output_path


def _prompt_knowledge(knowledge: dict[str, Any]) -> dict[str, Any]:
    prompt_knowledge = dict(knowledge)
    visual_protocol = dict(knowledge.get("visual_protocol") or {})
    visual_protocol["finding_targets"] = [
        {
            "target": "whole_tumor",
            "display_name": "FLAIR visible whole tumor candidate",
            "measurements": ["whole_tumor_volume_ml"],
        }
    ]
    prompt_knowledge["visual_protocol"] = visual_protocol
    return prompt_knowledge


def _build_medsam2_prompt(
    *,
    prompt_result: dict[str, Any],
    slice_index: int,
) -> dict[str, Any]:
    segmentation_prompt = prompt_result.get("segmentation_prompt") or {}
    return {
        "source": "vision_model_bbox",
        "slice_index": int(slice_index),
        "boxes": list(segmentation_prompt.get("boxes") or []),
        "points": list(segmentation_prompt.get("points") or []),
        "label_ids": [1],
        "image_size": segmentation_prompt.get("image_size"),
        "suspected_regions": list(prompt_result.get("suspected_regions") or []),
        "limitations": list(prompt_result.get("limitations") or []),
    }


def _write_bbox_overlay(
    *,
    image_path: Path,
    boxes: list[list[int]],
    output_path: Path,
) -> Path:
    with Image.open(image_path) as raw:
        image = raw.convert("RGB")
    draw = ImageDraw.Draw(image)
    for box in boxes:
        x1, y1, x2, y2 = [int(value) for value in box]
        draw.rectangle((x1, y1, x2, y2), outline=(255, 0, 0), width=3)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_dotenv_local(path: Path = Path(".env.local")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _case_name(image_path: Path) -> str:
    name = image_path.name
    for suffix in (".nii.gz", ".nii", ".gz"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return image_path.stem


if __name__ == "__main__":
    raise SystemExit(main())
