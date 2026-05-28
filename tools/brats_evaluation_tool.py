from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.nifti_mask_reader_tool import NibabelLoader


class BratsEvaluationTool:
    """Evaluates BraTS-style segmentation masks against a reference mask."""

    REGIONS = {
        "whole_tumor": {1, 2, 4},
        "tumor_core": {1, 4},
        "enhancing_tumor": {4},
    }

    def __init__(self, nifti_loader: Any | None = None) -> None:
        self.nifti_loader = nifti_loader or NibabelLoader()

    def evaluate(self, prediction_mask_path: Path | str, reference_mask_path: Path | str) -> dict[str, float]:
        prediction_image = self.nifti_loader.load(prediction_mask_path)
        reference_image = self.nifti_loader.load(reference_mask_path)
        prediction = prediction_image.get_fdata()
        reference = reference_image.get_fdata()
        if tuple(prediction.shape) != tuple(reference.shape):
            raise ValueError(
                "Prediction and reference mask shapes do not match: "
                f"{prediction.shape} != {reference.shape}"
            )

        voxel_volume_ml = self._voxel_volume_ml(reference_image)
        metrics: dict[str, float] = {}
        for region_name, labels in self.REGIONS.items():
            prediction_region = self._region_mask(prediction, labels)
            reference_region = self._region_mask(reference, labels)
            metrics.update(
                self._region_metrics(
                    region_name=region_name,
                    prediction_region=prediction_region,
                    reference_region=reference_region,
                    voxel_volume_ml=voxel_volume_ml,
                )
            )
        return metrics

    def _region_metrics(
        self,
        *,
        region_name: str,
        prediction_region: Any,
        reference_region: Any,
        voxel_volume_ml: float,
    ) -> dict[str, float]:
        prediction_count = int(prediction_region.sum())
        reference_count = int(reference_region.sum())
        intersection = int((prediction_region & reference_region).sum())
        union = prediction_count + reference_count - intersection
        prediction_volume = round(prediction_count * voxel_volume_ml, 6)
        reference_volume = round(reference_count * voxel_volume_ml, 6)
        absolute_volume_error = round(abs(prediction_volume - reference_volume), 6)
        return {
            f"{region_name}_dice": (
                1.0
                if prediction_count == 0 and reference_count == 0
                else (2.0 * intersection) / (prediction_count + reference_count)
            ),
            f"{region_name}_iou": 1.0 if union == 0 else intersection / union,
            f"{region_name}_prediction_voxels": prediction_count,
            f"{region_name}_reference_voxels": reference_count,
            f"{region_name}_prediction_volume_ml": prediction_volume,
            f"{region_name}_reference_volume_ml": reference_volume,
            f"{region_name}_absolute_volume_error_ml": absolute_volume_error,
            f"{region_name}_relative_volume_error": (
                None if reference_volume == 0 else absolute_volume_error / reference_volume
            ),
            f"{region_name}_prediction_component_count": self._component_count(prediction_region),
            f"{region_name}_reference_component_count": self._component_count(reference_region),
            f"{region_name}_false_positive_component_count": self._component_count_without_overlap(
                component_mask=prediction_region,
                overlap_mask=reference_region,
            ),
            f"{region_name}_false_negative_component_count": self._component_count_without_overlap(
                component_mask=reference_region,
                overlap_mask=prediction_region,
            ),
        }

    def _region_mask(self, data: Any, labels: set[int]) -> Any:
        mask = data == next(iter(labels))
        for label in labels:
            mask = mask | (data == label)
        return mask

    def _voxel_volume_ml(self, image: Any) -> float:
        header = getattr(image, "header", None)
        if header is None or not hasattr(header, "get_zooms"):
            return 0.001
        zooms = tuple(float(value) for value in header.get_zooms()[:3])
        if len(zooms) < 3:
            return 0.001
        return (zooms[0] * zooms[1] * zooms[2]) / 1000.0

    def _component_count(self, mask: Any) -> int:
        return len(self._components(mask))

    def _component_count_without_overlap(self, *, component_mask: Any, overlap_mask: Any) -> int:
        count = 0
        for component in self._components(component_mask):
            if not any(bool(overlap_mask[index]) for index in component):
                count += 1
        return count

    def _components(self, mask: Any) -> list[set[tuple[int, ...]]]:
        visited: set[tuple[int, ...]] = set()
        active = {tuple(index) for index in zip(*mask.nonzero())}
        components: list[set[tuple[int, ...]]] = []
        for start in list(active):
            if start in visited:
                continue
            component: set[tuple[int, ...]] = set()
            stack = [start]
            visited.add(start)
            while stack:
                index = stack.pop()
                component.add(index)
                for neighbor in self._neighbors(index, mask.shape):
                    if neighbor not in active or neighbor in visited:
                        continue
                    visited.add(neighbor)
                    stack.append(neighbor)
            components.append(component)
        return components

    def _neighbors(self, index: tuple[int, ...], shape: tuple[int, ...]) -> list[tuple[int, ...]]:
        neighbors: list[tuple[int, ...]] = []
        for axis in range(len(shape)):
            for delta in (-1, 1):
                candidate = list(index)
                candidate[axis] += delta
                if 0 <= candidate[axis] < shape[axis]:
                    neighbors.append(tuple(candidate))
        return neighbors
