from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.feature_extraction_tool import FeatureExtractionTool
from tools.mask_reader_tool import MaskReaderTool
from tools.overlay_generation_tool import OverlayGenerationTool


class SegmentationTool:
    """Boundary for segmentation workflows before replacing ground truth masks with models."""

    def __init__(
        self,
        mask_reader: Any | None = None,
        overlay_generator: Any | None = None,
        feature_extractor: FeatureExtractionTool | None = None,
        model_backend: Any | None = None,
        segmentation_source: str = "ground_truth_mask",
    ) -> None:
        self.mask_reader = mask_reader or MaskReaderTool()
        self.overlay_generator = overlay_generator or OverlayGenerationTool()
        self.feature_extractor = feature_extractor or FeatureExtractionTool()
        self.model_backend = model_backend
        self.segmentation_source = segmentation_source

    def segment_from_mask(
        self,
        image_path: Path | str,
        mask_path: Path | str,
        overlay_path: Path | str,
    ) -> dict[str, Any]:
        mask_data = self.mask_reader.read(mask_path)
        overlay_output = self.overlay_generator.generate_overlay(
            image_path=image_path,
            mask_path=mask_path,
            overlay_path=overlay_path,
        )
        features = self.feature_extractor.extract_brats_features(mask_data)
        return {
            "image_outputs": {
                "original_image_path": str(image_path),
                "mask_path": str(mask_path),
                "overlay_path": str(overlay_output),
            },
            "features": features,
            "mask_shape": {
                "width": mask_data.width,
                "height": mask_data.height,
                "depth": mask_data.depth,
            },
            "segmentation_source": self.segmentation_source,
        }

    def segment_with_model(
        self,
        image_path: Path | str,
        prompt: dict[str, Any],
        mask_path: Path | str,
        overlay_path: Path | str,
    ) -> dict[str, Any]:
        if self.model_backend is None:
            raise ValueError("model_backend is required for model segmentation")
        self.model_backend.predict_mask(
            image_path=image_path,
            output_mask_path=mask_path,
            prompt=prompt,
        )
        result = self.segment_from_mask(
            image_path=image_path,
            mask_path=mask_path,
            overlay_path=overlay_path,
        )
        source = getattr(self.model_backend, "segmentation_source", "model_generated_mask")
        result["segmentation_source"] = source
        result["features"]["segmentation_quality"] = source
        return result
