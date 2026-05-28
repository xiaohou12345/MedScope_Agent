from __future__ import annotations

from typing import Any

from tools.mask_reader_tool import MaskData


class FeatureExtractionTool:
    """Extracts BraTS-style region features from label counts."""

    def __init__(self, voxel_volume_ml: float = 1.0) -> None:
        self.voxel_volume_ml = voxel_volume_ml

    def extract_brats_features(self, mask_data: MaskData) -> dict[str, Any]:
        voxel_volume_ml = mask_data.voxel_volume_ml or self.voxel_volume_ml
        necrotic_core = mask_data.label_counts.get(1, 0)
        edema = mask_data.label_counts.get(2, 0)
        enhancing = mask_data.label_counts.get(4, 0)
        tumor_core = necrotic_core + enhancing
        whole_tumor = necrotic_core + edema + enhancing
        return {
            "whole_tumor_volume_ml": whole_tumor * voxel_volume_ml,
            "tumor_core_volume_ml": tumor_core * voxel_volume_ml,
            "enhancing_tumor_volume_ml": enhancing * voxel_volume_ml,
            "edema_present": edema > 0,
            "mass_effect": "not_assessed_in_phase_a",
            "segmentation_quality": "demo_ground_truth",
            "label_counts": dict(mask_data.label_counts),
        }
