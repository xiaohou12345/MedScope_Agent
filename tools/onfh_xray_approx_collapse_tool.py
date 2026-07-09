from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from tools.onfh_collapse_measurement_tool import ImageRulerCalibration


@dataclass(frozen=True)
class ApproxFemoralHeadSeed:
    image_side: str
    cx: float
    cy: float
    radius_px: float


class ONFHApproxXRayCollapseTool:
    """Approximate femoral-head depression from exported X-ray plus rough seed.

    This tool is for v0 data probing only. It estimates the superior articular
    surface from intensity inside a rough femoral-head circle and measures its
    vertical deviation from the reference circle. Clinical-grade measurement
    should use a reviewed ROI contour and DICOM PixelSpacing.
    """

    def measure(
        self,
        *,
        image_path: Path | str,
        seed: ApproxFemoralHeadSeed,
        calibration: ImageRulerCalibration | None,
    ) -> dict[str, Any]:
        with Image.open(image_path) as raw_image:
            gray = np.asarray(raw_image.convert("L"), dtype=np.float32)
        height, width = gray.shape
        roi_values = self._circle_values(gray, seed)
        if roi_values.size < 500:
            return self._not_usable(seed=seed, reason="seed_circle_outside_image")

        threshold = float(max(np.percentile(roi_values, 67), 85.0))
        surface_points = self._superior_surface_points(gray, seed, threshold=threshold)
        if len(surface_points) < 8:
            return self._not_usable(seed=seed, reason="surface_not_detected")

        max_item = max(surface_points, key=lambda item: item["depression_px"])
        max_px = max(0.0, float(max_item["depression_px"]))
        max_mm = max_px * calibration.mm_per_pixel if calibration else None

        return {
            "target": "femoral_head_collapse",
            "evidence_type": "approximate_exported_xray_measurement",
            "collapse_status": "approximately_measured",
            "measurement_method": "rough_seed_circle_surface_deviation",
            "measurement_usable": True,
            "image_side": seed.image_side,
            "maximum_depression_px": round(max_px, 3),
            "maximum_depression_mm": round(max_mm, 3) if max_mm is not None else None,
            "normalized_depression": round(max_px / max(seed.radius_px * 2.0, 1.0), 6),
            "depression_point": [round(max_item["x"], 3), round(max_item["actual_y"], 3)],
            "reference_point": [round(max_item["x"], 3), round(max_item["reference_y"], 3)],
            "reference_fit": {
                "type": "rough_seed_circle",
                "center": [round(seed.cx, 3), round(seed.cy, 3)],
                "radius_px": round(seed.radius_px, 3),
            },
            "surface_point_count": len(surface_points),
            "calibration_source": calibration.source if calibration else "none",
            "calibration": calibration.to_dict() if calibration else None,
            "stage_implication": self._stage_implication(max_mm),
            "diagnosis_usable_level": "prototype_only",
            "quality": {
                "roi_qc": "approximate_seed",
                "surface_detection_qc": "rough_intensity_based",
                "calibration_qc": "approximate_pass" if calibration else "missing_scale",
                "threshold": round(threshold, 3),
                "measurement_confidence": 0.35 if calibration else 0.25,
            },
            "limitations": [
                "This is a rough exported-image test based on approximate seed circles, not a reviewed segmentation.",
                "Use reviewed femoral-head contour and DICOM PixelSpacing before clinical ARCO IIIA/IIIB use.",
            ],
        }

    def draw_overlay(
        self,
        *,
        image_path: Path | str,
        measurements: list[dict[str, Any]],
        output_path: Path | str,
    ) -> None:
        image = Image.open(image_path).convert("RGB")
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        colors = {
            "image_left": (255, 190, 0, 235),
            "image_right": (0, 210, 255, 235),
            "single_visible_head": (255, 190, 0, 235),
        }
        for item in measurements:
            fit = item.get("reference_fit") or {}
            if not fit:
                continue
            cx, cy = fit["center"]
            radius = fit["radius_px"]
            color = colors.get(item.get("image_side"), (255, 190, 0, 235))
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                outline=color,
                width=4,
            )
            depression_point = item.get("depression_point")
            reference_point = item.get("reference_point")
            if depression_point and reference_point:
                draw.line(
                    (
                        reference_point[0],
                        reference_point[1],
                        depression_point[0],
                        depression_point[1],
                    ),
                    fill=(255, 60, 60, 255),
                    width=5,
                )
                for point in (reference_point, depression_point):
                    x, y = point
                    draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=(255, 60, 60, 255))
            label = self._label_text(item)
            draw.text((cx - radius, cy + radius + 8), label, fill=color)

        output = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_path)

    def _circle_values(self, gray: np.ndarray, seed: ApproxFemoralHeadSeed) -> np.ndarray:
        height, width = gray.shape
        x_min = max(0, int(seed.cx - seed.radius_px))
        x_max = min(width - 1, int(seed.cx + seed.radius_px))
        y_min = max(0, int(seed.cy - seed.radius_px))
        y_max = min(height - 1, int(seed.cy + seed.radius_px))
        values: list[float] = []
        for y in range(y_min, y_max + 1):
            for x in range(x_min, x_max + 1):
                if (x - seed.cx) ** 2 + (y - seed.cy) ** 2 <= seed.radius_px**2:
                    values.append(float(gray[y, x]))
        return np.asarray(values, dtype=np.float32)

    def _superior_surface_points(
        self,
        gray: np.ndarray,
        seed: ApproxFemoralHeadSeed,
        *,
        threshold: float,
    ) -> list[dict[str, float]]:
        height, width = gray.shape
        points: list[dict[str, float]] = []
        x_min = max(0, int(round(seed.cx - seed.radius_px * 0.58)))
        x_max = min(width - 1, int(round(seed.cx + seed.radius_px * 0.58)))
        for x in range(x_min, x_max + 1):
            dx = x - seed.cx
            root = seed.radius_px**2 - dx**2
            if root <= 0:
                continue
            reference_y = seed.cy - sqrt(root)
            y0 = max(0, int(round(reference_y - seed.radius_px * 0.08)))
            # v0 safety bound: only search close to the superior articular
            # surface. Searching deeper can incorrectly lock onto femoral neck,
            # acetabular overlap, or dense trabecular structures.
            y1 = min(height - 1, int(round(reference_y + seed.radius_px * 0.32)))
            if y1 <= y0:
                continue
            column = gray[y0 : y1 + 1, x]
            hits = np.where(column >= threshold)[0]
            if hits.size == 0:
                continue
            actual_y = float(y0 + int(hits[0]))
            depression_px = actual_y - reference_y
            if depression_px < -seed.radius_px * 0.08:
                continue
            points.append(
                {
                    "x": float(x),
                    "actual_y": actual_y,
                    "reference_y": float(reference_y),
                    "depression_px": float(depression_px),
                }
            )
        return points

    def _stage_implication(self, maximum_depression_mm: float | None) -> str:
        if maximum_depression_mm is None:
            return "cannot_split_ARCO_IIIA_IIIB_without_scale"
        if maximum_depression_mm <= 2.0:
            return "roughly_compatible_with_ARCO_IIIA"
        return "roughly_compatible_with_ARCO_IIIB"

    def _not_usable(self, *, seed: ApproxFemoralHeadSeed, reason: str) -> dict[str, Any]:
        return {
            "target": "femoral_head_collapse",
            "evidence_type": "approximate_exported_xray_measurement",
            "collapse_status": "unassessed",
            "measurement_method": "rough_seed_circle_surface_deviation",
            "measurement_usable": False,
            "image_side": seed.image_side,
            "maximum_depression_px": None,
            "maximum_depression_mm": None,
            "normalized_depression": None,
            "depression_point": None,
            "reference_point": None,
            "reference_fit": {
                "type": "rough_seed_circle",
                "center": [round(seed.cx, 3), round(seed.cy, 3)],
                "radius_px": round(seed.radius_px, 3),
            },
            "diagnosis_usable_level": "not_usable",
            "quality": {"failure_reason": reason, "measurement_confidence": 0.0},
            "limitations": ["Approximate exported-image measurement failed."],
        }

    def _label_text(self, item: dict[str, Any]) -> str:
        side = item.get("image_side", "head")
        px = item.get("maximum_depression_px")
        mm = item.get("maximum_depression_mm")
        if px is None:
            return f"{side}: not usable"
        if mm is None:
            return f"{side}: {px}px"
        return f"{side}: {mm}mm"
