from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from tools.skill_builder_tool import SkillBuilderTool
from tools.vision_prompt_generator import OpenAICompatibleVisionClient, VisionPromptGenerator


DEFAULT_OUTPUT_DIR = Path("output/fake/no_mask_vision_prompt_demo")


def default_pneumonia_opacity_skill() -> dict[str, Any]:
    return SkillBuilderTool().load_guideline_skill("pneumonia_chest_xray")


def run_no_mask_vision_prompt_demo(
    *,
    image_path: Path | str,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    patient_message: str = "咳嗽发热，胸片疑似肺炎，请定位可疑肺部浸润影区域",
    disease_skill: dict[str, Any] | None = None,
    client: Any | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    image = Path(image_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    generator = VisionPromptGenerator(client=client or OpenAICompatibleVisionClient())
    prompt_result = generator.generate(
        image_path=image,
        disease_skill=disease_skill or default_pneumonia_opacity_skill(),
        patient_message=patient_message,
    )
    prompt_result["source_metadata"] = source_metadata or {}

    prompt_result_path = output / "vision_prompt_result.json"
    bbox_overlay_path = output / "vision_prompt_bbox_overlay.png"
    summary_path = output / "summary.json"
    target_overlay_paths = _write_target_bbox_overlays(
        image_path=image,
        regions=prompt_result.get("suspected_regions") or [],
        output_dir=output / "target_overlays",
    )
    prompt_result_path.write_text(
        json.dumps(prompt_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_bbox_overlay(
        image_path=image,
        regions=prompt_result.get("suspected_regions") or [],
        output_path=bbox_overlay_path,
    )
    summary = {
        "status": prompt_result["status"],
        "image_path": str(image),
        "output_dir": str(output),
        "prompt_result_path": str(prompt_result_path),
        "bbox_overlay_path": str(bbox_overlay_path),
        "target_overlay_paths": target_overlay_paths,
        "summary_path": str(summary_path),
        "segmentation_prompt": prompt_result.get("segmentation_prompt", {}),
        "diagnosis_usable": prompt_result.get("diagnosis_usable", False),
        "next_step": "Pass segmentation_prompt.boxes to MedSAM2 or another segmentation runner.",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _write_target_bbox_overlays(
    *,
    image_path: Path,
    regions: list[dict[str, Any]],
    output_dir: Path,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    display_names: dict[str, str] = {}
    for region in regions:
        if not isinstance(region, dict):
            continue
        target = str(region.get("target") or "candidate_region")
        grouped.setdefault(target, []).append(region)
        display_names.setdefault(target, str(region.get("display_name") or target))
    overlays = []
    for index, (target, target_regions) in enumerate(grouped.items(), start=1):
        overlay_path = output_dir / f"{index:02d}_{_safe_filename(target)}_overlay.png"
        _write_bbox_overlay(
            image_path=image_path,
            regions=target_regions,
            output_path=overlay_path,
        )
        overlays.append(
            {
                "target": target,
                "display_name": display_names.get(target, target),
                "overlay_path": str(overlay_path),
                "region_count": len(target_regions),
            }
        )
    return overlays


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    cleaned = cleaned.strip("_")
    return cleaned or "candidate_region"


def _write_bbox_overlay(
    *,
    image_path: Path,
    regions: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    with Image.open(image_path) as raw:
        image = raw.convert("RGB")
    draw = ImageDraw.Draw(image)
    label_slots: list[tuple[int, int, int, int]] = []
    for index, region in enumerate(regions, start=1):
        box = region.get("bbox") or []
        if len(box) != 4:
            continue
        x1, y1, x2, y2 = [int(value) for value in box]
        polygon = region.get("polygon") or []
        draw.rectangle((x1, y1, x2, y2), outline=(0, 210, 255), width=2)
        if polygon:
            points = [(int(point[0]), int(point[1])) for point in polygon if len(point) == 2]
            if len(points) >= 3:
                draw.line(points + [points[0]], fill=(255, 215, 0), width=2)
        label_box = _label_box_outside_region(
            index=index,
            bbox=(x1, y1, x2, y2),
            image_size=image.size,
            used_boxes=label_slots,
        )
        label_slots.append(label_box)
        _draw_external_label(
            draw=draw,
            label=str(index),
            label_box=label_box,
            anchor=(x1, y1),
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def _label_box_outside_region(
    *,
    index: int,
    bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
    used_boxes: list[tuple[int, int, int, int]],
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    width, height = image_size
    label_size = 18
    gap = 7
    candidates = [
        (x1 - label_size - gap, y1 - label_size - gap),
        (x2 + gap, y1 - label_size - gap),
        (x1 - label_size - gap, y2 + gap),
        (x2 + gap, y2 + gap),
        (x1, y1 - label_size - gap),
        (x2 - label_size, y1 - label_size - gap),
    ]
    for candidate_x, candidate_y in candidates:
        label_box = _clamped_label_box(candidate_x, candidate_y, label_size, width, height)
        if not _boxes_overlap(label_box, bbox) and not any(
            _boxes_overlap(label_box, used_box) for used_box in used_boxes
        ):
            return label_box
    fallback_y = max(0, min(height - label_size, gap + (index - 1) * (label_size + gap)))
    return _clamped_label_box(gap, fallback_y, label_size, width, height)


def _clamped_label_box(
    x: int,
    y: int,
    label_size: int,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    left = max(0, min(width - label_size, int(x)))
    top = max(0, min(height - label_size, int(y)))
    return (left, top, left + label_size, top + label_size)


def _boxes_overlap(
    box_a: tuple[int, int, int, int],
    box_b: tuple[int, int, int, int],
) -> bool:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    return max(ax1, bx1) < min(ax2, bx2) and max(ay1, by1) < min(ay2, by2)


def _draw_external_label(
    *,
    draw: ImageDraw.ImageDraw,
    label: str,
    label_box: tuple[int, int, int, int],
    anchor: tuple[int, int],
) -> None:
    left, top, right, bottom = label_box
    center = ((left + right) // 2, (top + bottom) // 2)
    draw.line((center[0], center[1], anchor[0], anchor[1]), fill=(255, 80, 80), width=1)
    draw.ellipse(label_box, fill=(255, 80, 80), outline=(255, 255, 255), width=1)
    text_x = left + 6 if len(label) == 1 else left + 3
    draw.text((text_x, top + 2), label, fill=(255, 255, 255))


def _load_dotenv_local(path: Path = Path(".env.local")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate candidate segmentation bbox prompts from an unmasked medical image."
    )
    parser.add_argument("--image", required=True, help="Input medical image path.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--message",
        default="咳嗽发热，胸片疑似肺炎，请定位可疑肺部浸润影区域",
    )
    parser.add_argument("--source-url", default="")
    parser.add_argument("--source-license", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_dotenv_local()
    args = build_parser().parse_args(argv)
    result = run_no_mask_vision_prompt_demo(
        image_path=Path(args.image),
        output_dir=Path(args.output_dir),
        patient_message=args.message,
        source_metadata={
            "source_url": args.source_url,
            "source_license": args.source_license,
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
