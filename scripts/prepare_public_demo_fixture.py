from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


DEFAULT_OUTPUT_DIR = Path("output/fake/public_demo_fixture")


def prepare_public_demo_fixture(output_dir: Path | str = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    """Create a deterministic, public-safe demo fixture for fresh clones.

    The generated image is synthetic and intentionally not a medical record. It is
    only meant to exercise upload, routing, skill selection, and bounded evidence
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
        "vision_mode": "no_mask_skill",
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
    args = parser.parse_args(argv)
    result = prepare_public_demo_fixture(output_dir=args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
