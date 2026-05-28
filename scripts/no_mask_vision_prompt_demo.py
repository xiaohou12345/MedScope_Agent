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
    prompt_result_path.write_text(
        json.dumps(prompt_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_bbox_overlay(
        image_path=image,
        boxes=prompt_result.get("segmentation_prompt", {}).get("boxes") or [],
        output_path=bbox_overlay_path,
    )
    summary = {
        "status": prompt_result["status"],
        "image_path": str(image),
        "output_dir": str(output),
        "prompt_result_path": str(prompt_result_path),
        "bbox_overlay_path": str(bbox_overlay_path),
        "summary_path": str(summary_path),
        "segmentation_prompt": prompt_result.get("segmentation_prompt", {}),
        "diagnosis_usable": prompt_result.get("diagnosis_usable", False),
        "next_step": "Pass segmentation_prompt.boxes to MedSAM2 or another segmentation runner.",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


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
        draw.rectangle((x1, y1, x2, y2), outline=(255, 0, 0), width=4)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


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
