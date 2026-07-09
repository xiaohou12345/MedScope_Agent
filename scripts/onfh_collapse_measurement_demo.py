from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.onfh_collapse_measurement_tool import (
    ImageRulerCalibration,
    ONFHCollapseMeasurementTool,
)
from tools.xray_ruler_calibration_tool import XRayRulerCalibrationTool

from PIL import Image, ImageDraw


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure ONFH femoral-head collapse from a femoral-head mask and optional image ruler calibration.",
    )
    parser.add_argument("--image", required=True, help="Full X-ray image path.")
    parser.add_argument(
        "--femoral-head-mask",
        required=True,
        help="Binary femoral-head ROI mask aligned with the image.",
    )
    parser.add_argument(
        "--ruler-pixel-length",
        type=float,
        default=None,
        help="Pixel length corresponding to the real ruler length, e.g. pixels for 10 cm.",
    )
    parser.add_argument(
        "--ruler-points",
        default=None,
        help="Two ruler endpoints as x1,y1,x2,y2. Overrides --ruler-pixel-length.",
    )
    parser.add_argument(
        "--ruler-real-length-mm",
        type=float,
        default=100.0,
        help="Real ruler length in mm. Default is 100 mm for 10 cm.",
    )
    parser.add_argument(
        "--auto-right-ruler",
        action="store_true",
        help="Detect an approximate blue ruler in the right side of exported X-ray image.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to write measurement JSON.",
    )
    parser.add_argument(
        "--overlay-output",
        default=None,
        help="Optional path to write a measurement overlay image.",
    )
    args = parser.parse_args()

    image_path = Path(args.image)
    mask_path = Path(args.femoral_head_mask)
    calibration, calibration_report = build_calibration(
        image_path=image_path,
        ruler_pixel_length=args.ruler_pixel_length,
        ruler_points=args.ruler_points,
        ruler_real_length_mm=args.ruler_real_length_mm,
        auto_right_ruler=args.auto_right_ruler,
    )
    result = ONFHCollapseMeasurementTool().measure(
        image_path=image_path,
        femoral_head_mask_path=mask_path,
        calibration=calibration,
    )
    if calibration_report is not None:
        result["calibration_report"] = serializable_calibration_report(calibration_report)
    if args.overlay_output:
        write_measurement_overlay(
            image_path=image_path,
            femoral_head_mask_path=mask_path,
            result=result,
            calibration_report=calibration_report,
            output_path=Path(args.overlay_output),
        )
        result["overlay_path"] = args.overlay_output
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output_json:
        Path(args.output_json).write_text(payload + "\n", encoding="utf-8")


def build_calibration(
    *,
    image_path: Path | None = None,
    ruler_pixel_length: float | None,
    ruler_points: str | None,
    ruler_real_length_mm: float,
    auto_right_ruler: bool = False,
) -> tuple[ImageRulerCalibration | None, dict | None]:
    if ruler_points:
        values = [float(item.strip()) for item in ruler_points.split(",")]
        if len(values) != 4:
            raise ValueError("--ruler-points must be x1,y1,x2,y2")
        calibration = ImageRulerCalibration.from_points(
            point_a=(values[0], values[1]),
            point_b=(values[2], values[3]),
            real_length_mm=ruler_real_length_mm,
            source="manual_image_ruler",
        )
        return calibration, {"ruler_detected": True, "mode": "manual_points"}
    if ruler_pixel_length is not None:
        calibration = ImageRulerCalibration(
            pixel_length=ruler_pixel_length,
            real_length_mm=ruler_real_length_mm,
            source="manual_image_ruler",
        )
        return calibration, {"ruler_detected": True, "mode": "manual_pixel_length"}
    if auto_right_ruler:
        if image_path is None:
            raise ValueError("image_path is required when auto_right_ruler=True")
        report = XRayRulerCalibrationTool().detect_right_ruler(
            image_path=image_path,
            real_length_mm=ruler_real_length_mm,
        )
        return report["calibration"], report
    return None, None


def serializable_calibration_report(report: dict) -> dict:
    return {key: value for key, value in report.items() if key != "calibration"}


def write_measurement_overlay(
    *,
    image_path: Path,
    femoral_head_mask_path: Path,
    result: dict,
    calibration_report: dict | None,
    output_path: Path,
) -> None:
    image = Image.open(image_path).convert("RGB")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    mask = Image.open(femoral_head_mask_path).convert("L")
    if mask.size != image.size:
        mask = mask.resize(image.size)
    mask_pixels = mask.load()
    width, height = image.size
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            if mask_pixels[x, y] != 0:
                draw.point((x, y), fill=(0, 160, 255, 70))

    reference_fit = result.get("reference_fit") or {}
    if reference_fit.get("type") == "circle":
        cx, cy = reference_fit["center"]
        radius = reference_fit["radius_px"]
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            outline=(255, 190, 0, 230),
            width=3,
        )

    depression_point = result.get("depression_point")
    reference_point = result.get("reference_point")
    if depression_point and reference_point:
        draw.line(
            (reference_point[0], reference_point[1], depression_point[0], depression_point[1]),
            fill=(255, 60, 60, 255),
            width=4,
        )
        for point, color in [
            (reference_point, (255, 190, 0, 255)),
            (depression_point, (255, 60, 60, 255)),
        ]:
            x, y = point
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=color)

    if calibration_report and calibration_report.get("ruler_bbox"):
        x1, y1, x2, y2 = calibration_report["ruler_bbox"]
        draw.rectangle((x1, y1, x2, y2), outline=(0, 255, 255, 230), width=3)

    output = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.save(output_path)


if __name__ == "__main__":
    main()
