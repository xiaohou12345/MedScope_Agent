from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from tools.onfh_collapse_measurement_tool import ImageRulerCalibration


class XRayRulerCalibrationTool:
    """Approximate pixel-to-mm calibration from a visible right-side X-ray ruler.

    This is intentionally a v0 calibration provider for exported JPG/PNG images.
    It should be replaced by DICOM PixelSpacing when DICOM files are available.
    """

    def detect_right_ruler(
        self,
        *,
        image_path: Path | str,
        real_length_mm: float = 100.0,
        right_crop_fraction: float = 0.18,
    ) -> dict[str, Any]:
        with Image.open(image_path) as raw_image:
            image = raw_image.convert("RGB")
            width, height = image.size
            x_start = max(0, int(width * (1.0 - right_crop_fraction)))
            candidate_points = self._blue_ruler_points(image, x_start=x_start)

        if len(candidate_points) < 12:
            return self._not_detected_payload(
                failure_reason="right_ruler_not_detected",
                candidate_pixel_count=len(candidate_points),
            )

        ys = [point[1] for point in candidate_points]
        xs = [point[0] for point in candidate_points]
        y_min = min(ys)
        y_max = max(ys)
        pixel_length = float(y_max - y_min)
        if pixel_length <= 0:
            return self._not_detected_payload(
                failure_reason="right_ruler_zero_length",
                candidate_pixel_count=len(candidate_points),
            )

        calibration = ImageRulerCalibration(
            pixel_length=pixel_length,
            real_length_mm=real_length_mm,
            source="image_right_ruler_approx",
        )
        return {
            "ruler_detected": True,
            "calibration_source": calibration.source,
            "ruler_pixel_length": round(pixel_length, 3),
            "real_length_mm": round(real_length_mm, 3),
            "mm_per_pixel": round(calibration.mm_per_pixel, 8),
            "ruler_bbox": [min(xs), y_min, max(xs), y_max],
            "candidate_pixel_count": len(candidate_points),
            "calibration": calibration,
            "quality": {
                "calibration_qc": "approximate_pass",
                "source": "exported_image_right_ruler",
                "limitation": "Exported image ruler is approximate; DICOM PixelSpacing is preferred for clinical-grade millimeter measurement.",
            },
        }

    def _blue_ruler_points(
        self,
        image: Image.Image,
        *,
        x_start: int,
    ) -> list[tuple[int, int]]:
        pixels = image.load()
        width, height = image.size
        points: list[tuple[int, int]] = []
        for y in range(height):
            for x in range(x_start, width):
                red, green, blue = pixels[x, y]
                if blue >= 120 and green >= 80 and blue > red * 1.25:
                    points.append((x, y))
        return points

    def _not_detected_payload(
        self,
        *,
        failure_reason: str,
        candidate_pixel_count: int,
    ) -> dict[str, Any]:
        return {
            "ruler_detected": False,
            "calibration_source": "none",
            "ruler_pixel_length": None,
            "real_length_mm": None,
            "mm_per_pixel": None,
            "ruler_bbox": None,
            "candidate_pixel_count": candidate_pixel_count,
            "calibration": None,
            "failure_reason": failure_reason,
            "quality": {
                "calibration_qc": "missing_scale",
                "source": "none",
            },
        }
