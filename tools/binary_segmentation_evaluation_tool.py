from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image


class BinarySegmentationEvaluationTool:
    """Evaluates 2D binary lesion masks without disease-specific label semantics."""

    def evaluate(
        self,
        prediction_mask_path: Path | str,
        reference_mask_path: Path | str,
    ) -> dict[str, Any]:
        prediction = self._load_binary_points(prediction_mask_path)
        reference = self._load_binary_points(reference_mask_path)
        if prediction["size"] != reference["size"]:
            raise ValueError(
                "Prediction and reference mask shapes do not match: "
                f"{prediction['size']} != {reference['size']}"
            )

        prediction_points = prediction["points"]
        reference_points = reference["points"]
        intersection = prediction_points & reference_points
        union = prediction_points | reference_points
        prediction_count = len(prediction_points)
        reference_count = len(reference_points)
        intersection_count = len(intersection)
        union_count = len(union)
        return {
            "lesion_dice": (
                1.0
                if prediction_count == 0 and reference_count == 0
                else (2.0 * intersection_count) / (prediction_count + reference_count)
            ),
            "lesion_iou": 1.0 if union_count == 0 else intersection_count / union_count,
            "lesion_prediction_pixels": prediction_count,
            "lesion_reference_pixels": reference_count,
            "lesion_intersection_pixels": intersection_count,
            "lesion_union_pixels": union_count,
            "lesion_false_positive_pixels": len(prediction_points - reference_points),
            "lesion_false_negative_pixels": len(reference_points - prediction_points),
        }

    def _load_binary_points(self, path: Path | str) -> dict[str, Any]:
        with Image.open(path) as raw:
            image = raw.convert("L")
            width, height = image.size
            pixels = image.load()
            points = {
                (x, y)
                for y in range(height)
                for x in range(width)
                if pixels[x, y] != 0
            }
        return {"size": (width, height), "points": points}
