from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image


class GenericMaskMeasurementTool:
    """Extracts simple measurements from a 2D binary lesion mask."""

    def measure(
        self,
        image_path: Path | str,
        mask_path: Path | str,
        anatomy_mask_path: Path | str | None = None,
        anatomy_name: str = "anatomy",
    ) -> dict[str, Any]:
        with Image.open(image_path) as raw_image:
            width, height = raw_image.size
        with Image.open(mask_path) as raw_mask:
            mask = raw_mask.convert("L")
            if mask.size != (width, height):
                mask = mask.resize((width, height))
            nonzero: list[tuple[int, int]] = []
            pixels = mask.load()
            for y in range(height):
                for x in range(width):
                    if pixels[x, y] != 0:
                        nonzero.append((x, y))
        anatomy_points = self._mask_points(
            mask_path=anatomy_mask_path,
            size=(width, height),
        )
        with Image.open(image_path) as raw_image_for_intensity:
            intensity_image = raw_image_for_intensity.convert("L")
            intensity_pixels = intensity_image.load()
        image_area = width * height
        lesion_area = len(nonzero)
        anatomy_payload = self._anatomy_payload(
            lesion_points=nonzero,
            anatomy_points=anatomy_points,
            anatomy_name=anatomy_name,
        )
        if not nonzero:
            payload = {
                "lesion_area_px": 0,
                "image_area_px": image_area,
                "lesion_area_ratio": 0.0,
                "lesion_bbox": None,
                "lesion_centroid": None,
                "lesion_bbox_size": None,
                "lesion_fill_ratio": 0.0,
                "lesion_elongation": None,
                "lesion_mean_intensity": None,
                "region_count": 0,
                "regions": [],
            }
            payload.update(anatomy_payload)
            return payload
        xs = [point[0] for point in nonzero]
        ys = [point[1] for point in nonzero]
        bbox = [min(xs), min(ys), max(xs) + 1, max(ys) + 1]
        bbox_metrics = self._bbox_metrics(points=nonzero, bbox=bbox)
        regions = self._connected_regions(
            nonzero=nonzero,
            image_area=image_area,
            intensity_pixels=intensity_pixels,
            anatomy_points=anatomy_points,
        )
        payload = {
            "lesion_area_px": lesion_area,
            "image_area_px": image_area,
            "lesion_area_ratio": round(lesion_area / max(image_area, 1), 6),
            "lesion_bbox": bbox,
            "lesion_centroid": [
                round(sum(xs) / lesion_area, 3),
                round(sum(ys) / lesion_area, 3),
            ],
            "lesion_bbox_size": bbox_metrics["bbox_size"],
            "lesion_fill_ratio": bbox_metrics["fill_ratio"],
            "lesion_elongation": bbox_metrics["elongation"],
            "lesion_mean_intensity": self._mean_intensity(nonzero, intensity_pixels),
            "region_count": len(regions),
            "regions": regions,
        }
        payload.update(anatomy_payload)
        return payload

    def _connected_regions(
        self,
        *,
        nonzero: list[tuple[int, int]],
        image_area: int,
        intensity_pixels: Any,
        anatomy_points: set[tuple[int, int]] | None = None,
    ) -> list[dict[str, Any]]:
        remaining = set(nonzero)
        regions: list[dict[str, Any]] = []
        while remaining:
            seed = remaining.pop()
            stack = [seed]
            component = [seed]
            while stack:
                x, y = stack.pop()
                for neighbor in (
                    (x - 1, y),
                    (x + 1, y),
                    (x, y - 1),
                    (x, y + 1),
                ):
                    if neighbor not in remaining:
                        continue
                    remaining.remove(neighbor)
                    stack.append(neighbor)
                    component.append(neighbor)
            regions.append(
                self._region_payload(
                    component,
                    image_area=image_area,
                    intensity_pixels=intensity_pixels,
                    anatomy_points=anatomy_points,
                )
            )

        regions.sort(key=lambda item: (-int(item["area_px"]), item["bbox"]))
        for index, region in enumerate(regions, start=1):
            region["region_id"] = f"r{index}"
        return regions

    def _region_payload(
        self,
        component: list[tuple[int, int]],
        *,
        image_area: int,
        intensity_pixels: Any,
        anatomy_points: set[tuple[int, int]] | None = None,
    ) -> dict[str, Any]:
        xs = [point[0] for point in component]
        ys = [point[1] for point in component]
        area = len(component)
        bbox = [min(xs), min(ys), max(xs) + 1, max(ys) + 1]
        bbox_metrics = self._bbox_metrics(points=component, bbox=bbox)
        payload = {
            "area_px": area,
            "area_ratio_in_image": round(area / max(image_area, 1), 6),
            "bbox": bbox,
            "centroid": [
                round(sum(xs) / area, 3),
                round(sum(ys) / area, 3),
            ],
            "bbox_size": bbox_metrics["bbox_size"],
            "fill_ratio": bbox_metrics["fill_ratio"],
            "elongation": bbox_metrics["elongation"],
            "mean_intensity": self._mean_intensity(component, intensity_pixels),
        }
        if anatomy_points is not None:
            payload["overlap_anatomy_px"] = len(set(component) & anatomy_points)
            payload["area_ratio_in_anatomy"] = round(
                payload["overlap_anatomy_px"] / max(len(anatomy_points), 1),
                6,
            )
        return payload

    def _bbox_metrics(
        self,
        *,
        points: list[tuple[int, int]],
        bbox: list[int],
    ) -> dict[str, Any]:
        width = max(int(bbox[2]) - int(bbox[0]), 0)
        height = max(int(bbox[3]) - int(bbox[1]), 0)
        bbox_area = max(width * height, 1)
        short_axis = max(min(width, height), 1)
        long_axis = max(width, height)
        return {
            "bbox_size": {"width": width, "height": height},
            "fill_ratio": round(len(points) / bbox_area, 6),
            "elongation": round(long_axis / short_axis, 3),
        }

    def _mean_intensity(
        self,
        points: list[tuple[int, int]],
        intensity_pixels: Any,
    ) -> float | None:
        if not points:
            return None
        return round(sum(float(intensity_pixels[x, y]) for x, y in points) / len(points), 3)

    def _mask_points(
        self,
        *,
        mask_path: Path | str | None,
        size: tuple[int, int],
    ) -> set[tuple[int, int]] | None:
        if mask_path is None:
            return None
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

    def _anatomy_payload(
        self,
        *,
        lesion_points: list[tuple[int, int]],
        anatomy_points: set[tuple[int, int]] | None,
        anatomy_name: str,
    ) -> dict[str, Any]:
        if anatomy_points is None:
            return {}
        overlap = len(set(lesion_points) & anatomy_points)
        anatomy_area = len(anatomy_points)
        return {
            "anatomy_name": anatomy_name,
            "anatomy_area_px": anatomy_area,
            "lesion_overlap_anatomy_px": overlap,
            "lesion_area_ratio_in_anatomy": round(overlap / max(anatomy_area, 1), 6),
        }
