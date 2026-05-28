from __future__ import annotations

from typing import Any

from contracts.medical_contracts import SegmentationResult


class VisualQualityGate:
    """Converts raw segmentation output into diagnosis-gated task evidence."""

    def evaluate(
        self,
        *,
        task_name: str,
        target: str,
        image_outputs: dict[str, Any],
        measurements: dict[str, Any],
        segmentation_source: str,
        selected_tool: dict[str, Any] | None = None,
    ) -> SegmentationResult:
        warnings = self._quality_warnings(measurements)
        if warnings:
            status = "low_quality"
            quality = {"score": 0.2, "level": "low", "warnings": warnings}
            completeness = {
                "status": "unassessed",
                "reason": "Segmentation did not pass QC",
            }
            diagnosis_usable = False
        else:
            status = "completed"
            quality = {
                "score": 1.0 if "ground_truth" in segmentation_source else 0.7,
                "level": "high" if "ground_truth" in segmentation_source else "medium",
                "warnings": [],
            }
            completeness = {
                "status": "supported",
                "reason": "Segmentation passed QC",
            }
            diagnosis_usable = True
        return SegmentationResult(
            task_name=task_name,
            target=target,
            status=status,
            mask_path=str(image_outputs.get("mask_path") or "not_generated"),
            overlay_path=str(image_outputs.get("overlay_path") or "not_generated"),
            measurements=dict(measurements),
            quality=quality,
            completeness=completeness,
            diagnosis_usable=diagnosis_usable,
            selected_tool=selected_tool,
        )

    def skipped_result(
        self,
        *,
        task_name: str,
        target: str,
        status: str,
        reason: str,
        selected_tool: dict[str, Any] | None = None,
    ) -> SegmentationResult:
        completeness_status = "missing" if status == "missing_input" else "unassessed"
        return SegmentationResult(
            task_name=task_name,
            target=target,
            status=status,
            mask_path="not_generated",
            overlay_path="not_generated",
            quality={"score": 0.0, "level": "none", "warnings": [reason]},
            completeness={"status": completeness_status, "reason": reason},
            diagnosis_usable=False,
            selected_tool=selected_tool,
        )

    def _quality_warnings(self, measurements: dict[str, Any]) -> list[str]:
        warnings = []
        volume_items = {
            key: value
            for key, value in measurements.items()
            if key.endswith("_volume_ml")
        }
        for key, value in volume_items.items():
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                warnings.append(f"{key} is not numeric")
                continue
            if numeric <= 0:
                warnings.append(f"{key} is empty or zero")
        return warnings
