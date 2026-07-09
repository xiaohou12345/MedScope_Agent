from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.onfh_xray_approx_collapse_tool import (  # noqa: E402
    ApproxFemoralHeadSeed,
    ONFHApproxXRayCollapseTool,
)
from tools.xray_ruler_calibration_tool import XRayRulerCalibrationTool  # noqa: E402


DEFAULT_INPUT_DIR = Path(
    "/Users/houshaohua/Desktop/code/aidoctor/data/中日友好医院/"
    "xray_ruler_candidates_30/right_ruler_selected"
)


ROUGH_SEEDS: dict[str, list[ApproxFemoralHeadSeed]] = {
    "01_orig03_髋3.jpg": [
        ApproxFemoralHeadSeed("image_left", 252, 500, 105),
        ApproxFemoralHeadSeed("image_right", 786, 500, 105),
    ],
    "02_orig04_髋4.jpg": [
        ApproxFemoralHeadSeed("image_left", 260, 520, 110),
        ApproxFemoralHeadSeed("image_right", 775, 505, 105),
    ],
    "03_orig07_髋1.jpg": [
        ApproxFemoralHeadSeed("image_left", 245, 470, 90),
        ApproxFemoralHeadSeed("image_right", 775, 455, 90),
    ],
    "04_orig08_髋2.jpg": [
        ApproxFemoralHeadSeed("image_left", 242, 460, 90),
        ApproxFemoralHeadSeed("image_right", 780, 455, 90),
    ],
    "05_orig09_髋3.jpg": [
        ApproxFemoralHeadSeed("image_left", 255, 485, 92),
        ApproxFemoralHeadSeed("image_right", 780, 480, 92),
    ],
    "06_orig10_髋1.jpg": [
        ApproxFemoralHeadSeed("image_left", 255, 505, 95),
        ApproxFemoralHeadSeed("image_right", 775, 500, 95),
    ],
    "07_orig11_髋2.jpg": [
        ApproxFemoralHeadSeed("single_visible_head", 510, 580, 105),
    ],
    "08_orig23_髋1.jpg": [
        ApproxFemoralHeadSeed("image_left", 290, 565, 95),
        ApproxFemoralHeadSeed("image_right", 735, 555, 95),
    ],
    "09_orig24_髋2.jpg": [
        ApproxFemoralHeadSeed("image_left", 260, 560, 95),
        ApproxFemoralHeadSeed("image_right", 765, 555, 95),
    ],
    "10_orig25_髋1.jpg": [
        ApproxFemoralHeadSeed("image_left", 300, 660, 100),
        ApproxFemoralHeadSeed("image_right", 730, 660, 100),
    ],
    "11_orig29_髋1.jpg": [
        ApproxFemoralHeadSeed("image_left", 290, 595, 105),
        ApproxFemoralHeadSeed("image_right", 735, 595, 105),
    ],
    "12_orig30_髋2.jpg": [
        ApproxFemoralHeadSeed("image_left", 270, 625, 105),
        ApproxFemoralHeadSeed("image_right", 760, 625, 105),
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run approximate ONFH collapse-depth demo on real exported X-ray samples with right rulers.",
    )
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir) if args.output_dir else input_dir / "approx_collapse_demo"
    output_dir.mkdir(parents=True, exist_ok=True)

    ruler_tool = XRayRulerCalibrationTool()
    measure_tool = ONFHApproxXRayCollapseTool()
    all_records: list[dict] = []

    for image_path in sorted(input_dir.glob("*.jpg")):
        if image_path.name == "selected_contact_sheet.jpg":
            continue
        seeds = ROUGH_SEEDS.get(image_path.name)
        if not seeds:
            continue
        calibration_report = ruler_tool.detect_right_ruler(
            image_path=image_path,
            real_length_mm=100.0,
        )
        calibration = calibration_report["calibration"]
        measurements = [
            measure_tool.measure(
                image_path=image_path,
                seed=seed,
                calibration=calibration,
            )
            for seed in seeds
        ]
        overlay_path = output_dir / f"{image_path.stem}_approx_overlay.jpg"
        measure_tool.draw_overlay(
            image_path=image_path,
            measurements=measurements,
            output_path=overlay_path,
        )
        for measurement in measurements:
            record = dict(measurement)
            record["filename"] = image_path.name
            record["overlay_path"] = str(overlay_path)
            record["ruler_detected"] = calibration_report["ruler_detected"]
            record["ruler_pixel_length"] = calibration_report["ruler_pixel_length"]
            record["mm_per_pixel"] = calibration_report["mm_per_pixel"]
            all_records.append(record)

    write_json(output_dir / "approx_collapse_measurements.json", all_records)
    write_csv(output_dir / "approx_collapse_measurements.csv", all_records)
    write_contact_sheet(output_dir=output_dir)
    print(output_dir)
    print(f"measurements={len(all_records)}")


def write_json(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, records: list[dict]) -> None:
    fields = [
        "filename",
        "image_side",
        "maximum_depression_px",
        "maximum_depression_mm",
        "normalized_depression",
        "stage_implication",
        "measurement_usable",
        "surface_point_count",
        "ruler_pixel_length",
        "mm_per_pixel",
        "overlay_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in fields})


def write_contact_sheet(*, output_dir: Path) -> None:
    from PIL import Image, ImageDraw

    overlays = sorted(output_dir.glob("*_approx_overlay.jpg"))
    thumbs = []
    for overlay in overlays:
        image = Image.open(overlay).convert("RGB")
        image.thumbnail((420, 420))
        canvas = Image.new("RGB", (450, 465), "white")
        canvas.paste(image, ((450 - image.width) // 2, 5))
        ImageDraw.Draw(canvas).text((10, 435), overlay.name, fill="black")
        thumbs.append(canvas)
    if not thumbs:
        return
    cols = 3
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 450, rows * 465), (238, 242, 246))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % cols) * 450, (index // cols) * 465))
    sheet.save(output_dir / "approx_collapse_overlay_contact_sheet.jpg", quality=92)


if __name__ == "__main__":
    main()
