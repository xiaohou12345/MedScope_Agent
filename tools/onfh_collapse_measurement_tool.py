from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, hypot, pi, sin, sqrt
from pathlib import Path
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class ImageRulerCalibration:
    """Pixel-to-mm calibration from an image ruler or future DICOM spacing."""

    pixel_length: float
    real_length_mm: float
    source: str = "manual_image_ruler"

    @classmethod
    def from_points(
        cls,
        *,
        point_a: tuple[float, float],
        point_b: tuple[float, float],
        real_length_mm: float,
        source: str = "manual_image_ruler",
    ) -> "ImageRulerCalibration":
        pixel_length = hypot(point_b[0] - point_a[0], point_b[1] - point_a[1])
        return cls(
            pixel_length=pixel_length,
            real_length_mm=real_length_mm,
            source=source,
        )

    @property
    def mm_per_pixel(self) -> float:
        if self.pixel_length <= 0 or self.real_length_mm <= 0:
            raise ValueError("pixel_length and real_length_mm must be positive")
        return self.real_length_mm / self.pixel_length

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "ruler_pixel_length": round(float(self.pixel_length), 6),
            "real_length_mm": round(float(self.real_length_mm), 6),
            "mm_per_pixel": round(self.mm_per_pixel, 8),
        }


class ONFHCollapseMeasurementTool:
    """Measures femoral-head superior depression from a binary femoral-head mask.

    The tool intentionally separates geometry from calibration. It can use a
    rough image ruler today, then switch to DICOM PixelSpacing later without
    changing the contour measurement contract.
    """

    def measure(
        self,
        *,
        image_path: Path | str,
        femoral_head_mask_path: Path | str,
        calibration: ImageRulerCalibration | None = None,
        image_side: str | None = None,
    ) -> dict[str, Any]:
        width, height = self._image_size(image_path)
        mask_points = self._mask_points(femoral_head_mask_path, size=(width, height))
        if len(mask_points) < 50:
            return self._not_usable_payload(
                reason="femoral_head_roi_missing_or_too_small",
                calibration=calibration,
                mask_area_px=len(mask_points),
            )

        boundary = self._boundary_points(mask_points)
        if len(boundary) < 20:
            return self._not_usable_payload(
                reason="contour_too_sparse",
                calibration=calibration,
                mask_area_px=len(mask_points),
                boundary_point_count=len(boundary),
            )

        closed_contour = self._reconstruct_closed_complete_contour(
            mask_points=mask_points,
            boundary=boundary,
            image_width=width,
            image_side=image_side,
        )
        if closed_contour is None:
            return self._not_usable_payload(
                reason="complete_contour_reconstruction_failed",
                calibration=calibration,
                mask_area_px=len(mask_points),
                boundary_point_count=len(boundary),
            )

        depression = self._maximum_radial_depression_from_closed_contour(
            contour_model=closed_contour,
        )
        if depression is None:
            return self._not_usable_payload(
                reason="closed_contour_not_measurable",
                calibration=calibration,
                mask_area_px=len(mask_points),
                boundary_point_count=len(boundary),
            )

        maximum_depression_px = depression["maximum_depression_px"]
        maximum_depression_mm = None
        if calibration is not None:
            maximum_depression_mm = maximum_depression_px * calibration.mm_per_pixel
        reference_diameter_px = closed_contour["reference_diameter_px"]
        pW_percent = maximum_depression_px / max(reference_diameter_px, 1.0) * 100.0

        return {
            "target": "femoral_head_collapse",
            "evidence_type": "anatomical_measurement",
            "collapse_status": "measured",
            "measurement_method": "reference_contour_deviation",
            "measurement_usable": True,
            "maximum_depression_px": round(maximum_depression_px, 3),
            "reference_diameter_px": round(reference_diameter_px, 3),
            "femoral_head_deficiency_pW_percent": round(pW_percent, 6),
            "maximum_depression_mm": (
                round(maximum_depression_mm, 3)
                if maximum_depression_mm is not None
                else None
            ),
            "normalized_depression": round(
                maximum_depression_px / max(closed_contour["normalization_width_px"], 1.0),
                6,
            ),
            "depression_point": depression["depression_point"],
            "reference_point": depression["reference_point"],
            "reference_fit": {
                "type": "complete_contour_model",
                "fit_strategy": "closed_radial_contour_reconstruction",
                "model": closed_contour["reference_model"],
                "center": [
                    round(closed_contour["center"][0], 3),
                    round(closed_contour["center"][1], 3),
                ],
                "concentric_circle": (
                    {
                        "center": [
                            round(closed_contour["concentric_circle"]["cx"], 3),
                            round(closed_contour["concentric_circle"]["cy"], 3),
                        ],
                        "radius_px": round(closed_contour["concentric_circle"]["radius"], 3),
                        "diameter_px": round(reference_diameter_px, 3),
                    }
                    if closed_contour.get("concentric_circle")
                    else None
                ),
                "angle_bin_count": len(closed_contour["profile"]),
                "normalization_width_px": round(closed_contour["normalization_width_px"], 3),
                "preserved_contour_point_count": closed_contour["preserved_point_count"],
                "excluded_suspected_defect_angle_count": len(closed_contour["excluded_bins"]),
                "excluded_suspected_defect_column_count": len(closed_contour["excluded_bins"]),
                "measurement_sector": "acetabular_covered_superolateral_weight_bearing",
                "image_side": closed_contour["image_side"],
                "allowed_angle_degrees": closed_contour["allowed_angle_degrees"],
            },
            "actual_mask_contour": self._actual_closed_contour_payload(closed_contour),
            "observed_contour": self._measurement_sector_contour_payload(closed_contour),
            "reconstructed_complete_contour": self._fitted_closed_contour_payload(closed_contour),
            "calibration_source": calibration.source if calibration else "none",
            "calibration": calibration.to_dict() if calibration else None,
            "quality": {
                "roi_qc": "pass",
                "contour_qc": "pass",
                "reference_contour_qc": "pass",
                "calibration_qc": "pass" if calibration else "missing_scale",
                "mask_area_px": len(mask_points),
                "boundary_point_count": len(boundary),
                "preserved_contour_point_count": closed_contour["preserved_point_count"],
                "excluded_suspected_defect_angle_count": len(closed_contour["excluded_bins"]),
                "excluded_suspected_defect_column_count": len(closed_contour["excluded_bins"]),
                "reference_model": closed_contour["reference_model"],
                "measurement_sector": "acetabular_covered_superolateral_weight_bearing",
                "image_side": closed_contour["image_side"],
                "allowed_angle_degrees": closed_contour["allowed_angle_degrees"],
                "measurement_confidence": 0.75 if calibration else 0.6,
            },
            "stage_implication": self._stage_implication(maximum_depression_mm),
            "diagnosis_usable_level": (
                "measurement_support"
                if maximum_depression_mm is not None
                else "exploratory_support_without_mm_scale"
            ),
            "limitations": self._limitations(calibration),
        }

    def _image_size(self, image_path: Path | str) -> tuple[int, int]:
        with Image.open(image_path) as image:
            return image.size

    def _mask_points(
        self,
        mask_path: Path | str,
        *,
        size: tuple[int, int],
    ) -> set[tuple[int, int]]:
        width, height = size
        with Image.open(mask_path) as raw_mask:
            mask = raw_mask.convert("L")
            if mask.size != size:
                mask = mask.resize(size)
            pixels = mask.load()
            return {
                (x, y)
                for y in range(height)
                for x in range(width)
                if pixels[x, y] != 0
            }

    def _boundary_points(
        self,
        mask_points: set[tuple[int, int]],
    ) -> list[tuple[float, float]]:
        boundary: list[tuple[float, float]] = []
        for x, y in mask_points:
            if (
                (x - 1, y) not in mask_points
                or (x + 1, y) not in mask_points
                or (x, y - 1) not in mask_points
                or (x, y + 1) not in mask_points
            ):
                boundary.append((float(x), float(y)))
        return boundary

    def _fit_circle(
        self,
        points: list[tuple[float, float]],
    ) -> dict[str, float] | None:
        # Fit x^2 + y^2 + a*x + b*y + c = 0 by least squares.
        n = float(len(points))
        sx = sy = sxx = syy = sxy = 0.0
        bx = by = bc = 0.0
        for x, y in points:
            z = x * x + y * y
            sx += x
            sy += y
            sxx += x * x
            syy += y * y
            sxy += x * y
            bx -= x * z
            by -= y * z
            bc -= z
        solution = self._solve_3x3(
            [
                [sxx, sxy, sx],
                [sxy, syy, sy],
                [sx, sy, n],
            ],
            [bx, by, bc],
        )
        if solution is None:
            return None
        a, b, c = solution
        cx = -a / 2.0
        cy = -b / 2.0
        radius_sq = cx * cx + cy * cy - c
        if radius_sq <= 0:
            return None
        return {"cx": cx, "cy": cy, "radius": sqrt(radius_sq)}

    def _reconstruct_closed_complete_contour(
        self,
        *,
        mask_points: set[tuple[int, int]],
        boundary: list[tuple[float, float]],
        image_width: int,
        image_side: str | None,
    ) -> dict[str, Any] | None:
        center = self._mask_centroid(mask_points)
        bbox = self._mask_bbox(mask_points)
        resolved_image_side = self._resolve_image_side(
            image_side=image_side,
            center_x=center[0],
            image_width=image_width,
        )
        profile = self._closed_radial_profile(boundary=boundary, center=center)
        if len(profile) < 90:
            return None
        x0, y0, x1, y1 = bbox

        initial_reference = self._smooth_upper_radial_reference(
            profile=profile,
            excluded_bins=set(),
        )
        initial_profile = self._profile_with_radial_reference(
            profile=profile,
            reference_radii=initial_reference,
            center=center,
            bbox=bbox,
            image_side=resolved_image_side,
        )
        excluded_bins = self._suspected_defect_angle_bins(initial_profile)
        if len(excluded_bins) > len(profile) * 0.35:
            excluded_bins = set()

        circle = self._concentric_circle_fit_from_profile(
            profile=initial_profile,
            excluded_bins=excluded_bins,
        )
        if circle is not None:
            final_reference = self._circle_reference_radii(
                profile=profile,
                center=center,
                circle=circle,
            )
            reference_model = "concentric_circle_with_angular_envelope_qc"
            reference_diameter_px = 2.0 * circle["radius"]
        else:
            final_reference = self._smooth_upper_radial_reference(
                profile=profile,
                excluded_bins=excluded_bins,
            )
            reference_model = "angular_upper_envelope"
            reference_diameter_px = max(float(x1 - x0 + 1), float(y1 - y0 + 1), 1.0)
        final_profile = self._profile_with_radial_reference(
            profile=profile,
            reference_radii=final_reference,
            center=center,
            bbox=bbox,
            image_side=resolved_image_side,
        )
        return {
            "center": center,
            "bbox": bbox,
            "profile": final_profile,
            "excluded_bins": excluded_bins,
            "preserved_point_count": len(profile) - len(excluded_bins),
            "normalization_width_px": max(float(x1 - x0 + 1), float(y1 - y0 + 1), 1.0),
            "reference_diameter_px": reference_diameter_px,
            "reference_model": reference_model,
            "concentric_circle": circle,
            "image_side": resolved_image_side,
            "allowed_angle_degrees": self._weight_bearing_angle_range(resolved_image_side),
        }

    def _concentric_circle_fit_from_profile(
        self,
        *,
        profile: list[dict[str, float]],
        excluded_bins: set[int],
    ) -> dict[str, float] | None:
        support_points: list[tuple[float, float]] = []
        for entry in profile:
            bin_index = int(entry["bin_index"])
            if bin_index in excluded_bins:
                continue
            angle = entry.get("angle_degrees", (entry["theta"] * 180.0 / pi) % 360.0)
            is_superior_articular_arc = 180.0 <= angle <= 360.0
            is_defect_sector = entry.get("measurement_allowed", False)
            if is_superior_articular_arc and not is_defect_sector:
                support_points.append((entry["actual_x"], entry["actual_y"]))
        if len(support_points) < 30:
            support_points = [
                (entry["actual_x"], entry["actual_y"])
                for entry in profile
                if int(entry["bin_index"]) not in excluded_bins
                and 180.0 <= ((entry["theta"] * 180.0 / pi) % 360.0) <= 360.0
            ]
        if len(support_points) < 30:
            return None
        return self._fit_circle(support_points)

    def _circle_reference_radii(
        self,
        *,
        profile: list[dict[str, float]],
        center: tuple[float, float],
        circle: dict[str, float],
    ) -> list[float]:
        cx, cy = center
        ccx = circle["cx"]
        ccy = circle["cy"]
        radius = circle["radius"]
        reference: list[float] = []
        for entry in profile:
            theta = entry["theta"]
            ux = cos(theta)
            uy = sin(theta)
            ox = cx - ccx
            oy = cy - ccy
            b = 2.0 * (ox * ux + oy * uy)
            c = ox * ox + oy * oy - radius * radius
            discriminant = b * b - 4.0 * c
            if discriminant < 0:
                reference.append(entry["actual_radius"])
                continue
            root = sqrt(discriminant)
            t1 = (-b + root) / 2.0
            t2 = (-b - root) / 2.0
            candidates = [t for t in (t1, t2) if t > 0]
            reference_radius = max(candidates) if candidates else entry["actual_radius"]
            reference.append(max(reference_radius, entry["actual_radius"]))
        return reference

    def _resolve_image_side(
        self,
        *,
        image_side: str | None,
        center_x: float,
        image_width: int,
    ) -> str:
        if image_side in {"image_left_femoral_head", "image_right_femoral_head"}:
            return image_side
        if image_side == "single_femoral_head":
            return (
                "image_left_femoral_head"
                if center_x < image_width / 2.0
                else "image_right_femoral_head"
            )
        return (
            "image_left_femoral_head"
            if center_x < image_width / 2.0
            else "image_right_femoral_head"
        )

    def _mask_centroid(self, mask_points: set[tuple[int, int]]) -> tuple[float, float]:
        count = max(len(mask_points), 1)
        return (
            sum(x for x, _ in mask_points) / count,
            sum(y for _, y in mask_points) / count,
        )

    def _mask_bbox(self, mask_points: set[tuple[int, int]]) -> tuple[int, int, int, int]:
        xs = [x for x, _ in mask_points]
        ys = [y for _, y in mask_points]
        return min(xs), min(ys), max(xs), max(ys)

    def _closed_radial_profile(
        self,
        *,
        boundary: list[tuple[float, float]],
        center: tuple[float, float],
        bin_count: int = 360,
    ) -> list[dict[str, float]]:
        cx, cy = center
        by_bin: dict[int, dict[str, float]] = {}
        for x, y in boundary:
            dx = x - cx
            dy = y - cy
            radius = hypot(dx, dy)
            if radius <= 0:
                continue
            theta = atan2(dy, dx)
            if theta < 0:
                theta += 2.0 * pi
            bin_index = int(round(theta / (2.0 * pi) * bin_count)) % bin_count
            current = by_bin.get(bin_index)
            if current is None or radius > current["actual_radius"]:
                by_bin[bin_index] = {
                    "bin_index": float(bin_index),
                    "theta": (2.0 * pi * bin_index) / bin_count,
                    "actual_radius": radius,
                    "actual_x": x,
                    "actual_y": y,
                }

        if len(by_bin) < max(45, bin_count // 8):
            return []

        profile: list[dict[str, float]] = []
        known_bins = sorted(by_bin)
        for bin_index in range(bin_count):
            item = by_bin.get(bin_index)
            if item is None:
                item = self._interpolated_radial_bin(
                    bin_index=bin_index,
                    by_bin=by_bin,
                    known_bins=known_bins,
                    center=center,
                    bin_count=bin_count,
                )
            profile.append(item)
        return profile

    def _interpolated_radial_bin(
        self,
        *,
        bin_index: int,
        by_bin: dict[int, dict[str, float]],
        known_bins: list[int],
        center: tuple[float, float],
        bin_count: int,
    ) -> dict[str, float]:
        previous_candidates = [value for value in known_bins if value < bin_index]
        next_candidates = [value for value in known_bins if value > bin_index]
        previous_bin = previous_candidates[-1] if previous_candidates else known_bins[-1] - bin_count
        next_bin = next_candidates[0] if next_candidates else known_bins[0] + bin_count
        previous_item = by_bin[previous_bin % bin_count]
        next_item = by_bin[next_bin % bin_count]
        span = max(float(next_bin - previous_bin), 1.0)
        ratio = (bin_index - previous_bin) / span
        radius = previous_item["actual_radius"] * (1.0 - ratio) + next_item["actual_radius"] * ratio
        theta = (2.0 * pi * bin_index) / bin_count
        cx, cy = center
        return {
            "bin_index": float(bin_index),
            "theta": theta,
            "actual_radius": radius,
            "actual_x": cx + radius * cos(theta),
            "actual_y": cy + radius * sin(theta),
        }

    def _smooth_upper_radial_reference(
        self,
        *,
        profile: list[dict[str, float]],
        excluded_bins: set[int],
    ) -> list[float]:
        radii = [entry["actual_radius"] for entry in profile]
        count = len(profile)
        window = max(8, count // 36)
        reference: list[float] = []
        for index, actual_radius in enumerate(radii):
            values: list[float] = []
            for offset in range(-window, window + 1):
                neighbor = (index + offset) % count
                if neighbor in excluded_bins:
                    continue
                values.append(radii[neighbor])
            if not values:
                values = [actual_radius]
            values.sort()
            quantile_index = min(len(values) - 1, int(round((len(values) - 1) * 0.72)))
            reference.append(max(values[quantile_index], actual_radius))

        for _ in range(2):
            smoothed: list[float] = []
            for index, value in enumerate(reference):
                values = [reference[(index + offset) % count] for offset in range(-2, 3)]
                smooth_value = sum(values) / len(values)
                actual_radius = radii[index]
                if index not in excluded_bins:
                    smooth_value = max(smooth_value, actual_radius)
                smoothed.append(smooth_value)
            reference = smoothed
        return reference

    def _profile_with_radial_reference(
        self,
        *,
        profile: list[dict[str, float]],
        reference_radii: list[float],
        center: tuple[float, float],
        bbox: tuple[int, int, int, int],
        image_side: str,
    ) -> list[dict[str, float]]:
        cx, cy = center
        x0, y0, x1, y1 = bbox
        bbox_height = max(float(y1 - y0 + 1), 1.0)
        bbox_width = max(float(x1 - x0 + 1), 1.0)
        measurement_y_limit = cy + bbox_height * 0.08
        lateral_sign = -1.0 if image_side == "image_left_femoral_head" else 1.0
        entries: list[dict[str, float]] = []
        for entry, reference_radius in zip(profile, reference_radii):
            theta = entry["theta"]
            reference_x = cx + reference_radius * cos(theta)
            reference_y = cy + reference_radius * sin(theta)
            actual_radius = entry["actual_radius"]
            actual_y = entry["actual_y"]
            actual_x = entry["actual_x"]
            depression = max(reference_radius - actual_radius, 0.0)
            superior_score = (cy - min(actual_y, reference_y)) / bbox_height
            lateral_score = lateral_sign * (actual_x - cx) / bbox_width
            in_weight_bearing_angle = self._is_in_weight_bearing_angle(
                theta=theta,
                image_side=image_side,
            )
            entries.append(
                {
                    **entry,
                    "reference_radius": reference_radius,
                    "reference_x": reference_x,
                    "reference_y": reference_y,
                    "depression_px": depression,
                    "measurement_allowed": bool(
                        (actual_y <= measurement_y_limit or reference_y <= measurement_y_limit)
                        and superior_score >= 0.10
                        and lateral_score >= -0.08
                        and in_weight_bearing_angle
                    ),
                    "measurement_region": "acetabular_covered_superolateral_weight_bearing",
                    "superior_score": superior_score,
                    "lateral_score": lateral_score,
                    "angle_degrees": (theta * 180.0 / pi) % 360.0,
                }
            )
        return entries

    def _weight_bearing_angle_range(self, image_side: str) -> list[float]:
        return [245.0, 295.0]

    def _is_in_weight_bearing_angle(self, *, theta: float, image_side: str) -> bool:
        angle = (theta * 180.0 / pi) % 360.0
        lower, upper = self._weight_bearing_angle_range(image_side)
        return lower <= angle <= upper

    def _suspected_defect_angle_bins(self, profile: list[dict[str, float]]) -> set[int]:
        depressions = [
            entry["depression_px"]
            for entry in profile
            if entry["depression_px"] > 0 and entry.get("measurement_allowed")
        ]
        if not depressions:
            return set()
        median = self._median(depressions)
        deviations = [abs(value - median) for value in depressions]
        mad = self._median(deviations)
        threshold = max(3.0, median + max(1.5 * mad, 1.5))
        max_depression = max(depressions)
        threshold = min(threshold, max_depression * 0.65) if max_depression > 0 else threshold
        suspected = {
            int(entry["bin_index"])
            for entry in profile
            if entry["depression_px"] >= threshold
            and entry["depression_px"] > 0
            and entry.get("measurement_allowed")
        }
        expanded: set[int] = set()
        count = len(profile)
        for bin_index in suspected:
            for offset in range(-2, 3):
                expanded.add((bin_index + offset) % count)
        return expanded

    def _solve_3x3(
        self,
        matrix: list[list[float]],
        vector: list[float],
    ) -> list[float] | None:
        a = [row[:] + [value] for row, value in zip(matrix, vector)]
        for col in range(3):
            pivot = max(range(col, 3), key=lambda row: abs(a[row][col]))
            if abs(a[pivot][col]) < 1e-9:
                return None
            if pivot != col:
                a[col], a[pivot] = a[pivot], a[col]
            pivot_value = a[col][col]
            for j in range(col, 4):
                a[col][j] /= pivot_value
            for row in range(3):
                if row == col:
                    continue
                factor = a[row][col]
                for j in range(col, 4):
                    a[row][j] -= factor * a[col][j]
        return [a[row][3] for row in range(3)]

    def _observed_superior_profile(
        self,
        mask_points: set[tuple[int, int]],
    ) -> list[dict[str, float]]:
        upper_by_x: dict[int, int] = {}
        lower_by_x: dict[int, int] = {}
        for x, y in mask_points:
            if x not in upper_by_x or y < upper_by_x[x]:
                upper_by_x[x] = y
            if x not in lower_by_x or y > lower_by_x[x]:
                lower_by_x[x] = y

        entries: list[dict[str, float]] = []
        if not upper_by_x:
            return entries

        heights = [lower_by_x[x] - upper_by_x[x] + 1 for x in upper_by_x]
        max_height = max(heights)
        min_column_height = max(2, int(max_height * 0.08))
        for x in sorted(upper_by_x):
            column_height = lower_by_x[x] - upper_by_x[x] + 1
            if column_height < min_column_height:
                continue
            entries.append(
                {
                    "x": float(x),
                    "actual_y": float(upper_by_x[x]),
                    "column_height": float(column_height),
                }
            )
        return entries

    def _reconstruct_local_complete_contour(
        self,
        observed_profile: list[dict[str, float]],
    ) -> dict[str, Any] | None:
        initial_model = self._fit_local_quadratic(observed_profile)
        if initial_model is None:
            return None

        initial_profile = self._profile_with_reference(
            observed_profile=observed_profile,
            reference_model=initial_model,
        )
        excluded_columns = self._suspected_defect_columns(initial_profile)
        preserved_profile = [
            entry for entry in observed_profile if int(round(entry["x"])) not in excluded_columns
        ]
        minimum_preserved_count = max(20, int(len(observed_profile) * 0.45))
        if len(preserved_profile) < minimum_preserved_count:
            preserved_profile = observed_profile
            excluded_columns = set()

        final_model = self._fit_local_quadratic(preserved_profile)
        if final_model is None:
            final_model = initial_model

        x_values = [entry["x"] for entry in observed_profile]
        normalization_width_px = max(x_values) - min(x_values) + 1.0
        return {
            "model": final_model,
            "initial_model": initial_model,
            "excluded_columns": excluded_columns,
            "preserved_point_count": len(preserved_profile),
            "normalization_width_px": normalization_width_px,
        }

    def _fit_local_quadratic(
        self,
        profile: list[dict[str, float]],
    ) -> dict[str, Any] | None:
        if len(profile) < 3:
            return None
        x_center = sum(entry["x"] for entry in profile) / len(profile)
        s0 = float(len(profile))
        s1 = s2 = s3 = s4 = 0.0
        t0 = t1 = t2 = 0.0
        for entry in profile:
            dx = entry["x"] - x_center
            y = entry["actual_y"]
            dx2 = dx * dx
            s1 += dx
            s2 += dx2
            s3 += dx2 * dx
            s4 += dx2 * dx2
            t0 += y
            t1 += dx * y
            t2 += dx2 * y
        solution = self._solve_3x3(
            [
                [s4, s3, s2],
                [s3, s2, s1],
                [s2, s1, s0],
            ],
            [t2, t1, t0],
        )
        if solution is None:
            return None
        a, b, c = solution
        return {
            "kind": "quadratic",
            "x_center": x_center,
            "coefficients": [a, b, c],
        }

    def _evaluate_local_quadratic(
        self,
        *,
        x: float,
        model: dict[str, Any],
    ) -> float:
        a, b, c = model["coefficients"]
        dx = x - model["x_center"]
        return a * dx * dx + b * dx + c

    def _profile_with_reference(
        self,
        *,
        observed_profile: list[dict[str, float]],
        reference_model: dict[str, Any],
    ) -> list[dict[str, float]]:
        entries: list[dict[str, float]] = []
        for entry in observed_profile:
            reference_y = self._evaluate_local_quadratic(
                x=entry["x"],
                model=reference_model,
            )
            actual_y = entry["actual_y"]
            entries.append(
                {
                    "x": entry["x"],
                    "actual_y": actual_y,
                    "reference_y": reference_y,
                    "depression_px": actual_y - reference_y,
                }
            )
        return entries

    def _suspected_defect_columns(self, profile: list[dict[str, float]]) -> set[int]:
        depressions = [entry["depression_px"] for entry in profile if entry["depression_px"] > 0]
        if not depressions:
            return set()
        median = self._median(depressions)
        deviations = [abs(value - median) for value in depressions]
        mad = self._median(deviations)
        threshold = max(3.0, median + max(1.5 * mad, 1.5))
        max_depression = max(depressions)
        threshold = min(threshold, max_depression * 0.65) if max_depression > 0 else threshold
        suspected = {
            int(round(entry["x"]))
            for entry in profile
            if entry["depression_px"] >= threshold and entry["depression_px"] > 0
        }
        expanded: set[int] = set()
        for x in suspected:
            expanded.update(range(x - 2, x + 3))
        return expanded

    def _median(self, values: list[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    def _maximum_superior_depression_from_profile(
        self,
        *,
        observed_profile: list[dict[str, float]],
        reference_model: dict[str, Any],
    ) -> dict[str, Any] | None:
        profile = self._profile_with_reference(
            observed_profile=observed_profile,
            reference_model=reference_model,
        )
        max_depression = -1.0
        max_item: dict[str, float] | None = None
        for item in profile:
            depression = item["depression_px"]
            if depression > max_depression:
                max_depression = depression
                max_item = item
        if max_item is None:
            return None
        return {
            "maximum_depression_px": max(max_depression, 0.0),
            "depression_point": [
                round(max_item["x"], 3),
                round(max_item["actual_y"], 3),
            ],
            "reference_point": [
                round(max_item["x"], 3),
                round(max_item["reference_y"], 3),
            ],
            "profile": profile,
        }

    def _maximum_radial_depression_from_closed_contour(
        self,
        *,
        contour_model: dict[str, Any],
    ) -> dict[str, Any] | None:
        profile = contour_model["profile"]
        candidates = [entry for entry in profile if entry.get("measurement_allowed")]
        if not candidates:
            candidates = profile
        max_item = max(candidates, key=lambda entry: entry["depression_px"], default=None)
        if max_item is None:
            return None
        return {
            "maximum_depression_px": max(max_item["depression_px"], 0.0),
            "depression_point": [
                round(max_item["actual_x"], 3),
                round(max_item["actual_y"], 3),
            ],
            "reference_point": [
                round(max_item["reference_x"], 3),
                round(max_item["reference_y"], 3),
            ],
            "profile": profile,
        }

    def _actual_closed_contour_payload(self, contour_model: dict[str, Any]) -> dict[str, Any]:
        profile = contour_model["profile"]
        return {
            "type": "actual_closed_mask_contour",
            "point_count": len(profile),
            "sampled_points": self._sample_points(
                [[entry["actual_x"], entry["actual_y"]] for entry in profile]
            ),
        }

    def _measurement_sector_contour_payload(self, contour_model: dict[str, Any]) -> dict[str, Any]:
        profile = [
            entry for entry in contour_model["profile"] if entry.get("measurement_allowed")
        ]
        return {
            "type": "actual_measurement_sector_contour",
            "point_count": len(profile),
            "sampled_points": self._sample_points(
                [[entry["actual_x"], entry["actual_y"]] for entry in profile]
            ),
        }

    def _fitted_closed_contour_payload(self, contour_model: dict[str, Any]) -> dict[str, Any]:
        profile = contour_model["profile"]
        return {
            "type": "fitted_complete_closed_contour",
            "fit_model": "angular_upper_envelope",
            "point_count": len(profile),
            "sampled_points": self._sample_points(
                [[entry["reference_x"], entry["reference_y"]] for entry in profile]
            ),
        }

    def _observed_contour_payload(self, profile: list[dict[str, float]]) -> dict[str, Any]:
        return {
            "type": "mask_superior_observed_contour",
            "point_count": len(profile),
            "sampled_points": self._sample_points(
                [[entry["x"], entry["actual_y"]] for entry in profile]
            ),
        }

    def _reconstructed_contour_payload(self, profile: list[dict[str, float]]) -> dict[str, Any]:
        return {
            "type": "local_reconstructed_complete_superior_contour",
            "fit_model": "quadratic_upper_contour",
            "point_count": len(profile),
            "sampled_points": self._sample_points(
                [[entry["x"], entry["reference_y"]] for entry in profile]
            ),
        }

    def _sample_points(self, points: list[list[float]]) -> list[list[float]]:
        if not points:
            return []
        step = max(1, len(points) // 120)
        sampled = points[::step]
        if sampled[-1] != points[-1]:
            sampled.append(points[-1])
        return [[round(x, 3), round(y, 3)] for x, y in sampled]

    def _stage_implication(self, maximum_depression_mm: float | None) -> str:
        if maximum_depression_mm is None:
            return "cannot_split_ARCO_IIIA_IIIB_without_scale"
        if maximum_depression_mm <= 2.0:
            return "compatible_with_ARCO_IIIA"
        return "compatible_with_ARCO_IIIB"

    def _limitations(self, calibration: ImageRulerCalibration | None) -> list[str]:
        limitations = [
            "Requires a reliable femoral-head ROI mask and superior contour.",
            "Local superior-contour reconstruction is a geometric approximation and must be reviewed.",
        ]
        if calibration is None:
            limitations.append(
                "No image ruler or DICOM pixel spacing was provided; millimeter value and ARCO IIIA/IIIB split are unavailable."
            )
        else:
            limitations.append(
                "Image-ruler calibration is approximate; DICOM PixelSpacing should replace it when available."
            )
        return limitations

    def _not_usable_payload(
        self,
        *,
        reason: str,
        calibration: ImageRulerCalibration | None,
        mask_area_px: int = 0,
        boundary_point_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "target": "femoral_head_collapse",
            "evidence_type": "anatomical_measurement",
            "collapse_status": "unassessed",
            "measurement_method": "reference_contour_deviation",
            "measurement_usable": False,
            "maximum_depression_px": None,
            "maximum_depression_mm": None,
            "normalized_depression": None,
            "depression_point": None,
            "reference_point": None,
            "reference_fit": None,
            "calibration_source": calibration.source if calibration else "none",
            "calibration": calibration.to_dict() if calibration else None,
            "quality": {
                "roi_qc": "fail",
                "contour_qc": "fail",
                "reference_contour_qc": "fail",
                "calibration_qc": "pass" if calibration else "missing_scale",
                "mask_area_px": mask_area_px,
                "boundary_point_count": boundary_point_count,
                "failure_reason": reason,
                "measurement_confidence": 0.0,
            },
            "stage_implication": "measurement_unavailable",
            "diagnosis_usable_level": "not_usable",
            "limitations": self._limitations(calibration),
        }
