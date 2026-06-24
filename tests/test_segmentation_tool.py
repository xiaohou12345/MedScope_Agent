import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from agents.vision_agent import VisionAgent
from tools.feature_extraction_tool import FeatureExtractionTool
from tools.segmentation_tool import SegmentationTool


class FakeSegmentationTool:
    def __init__(self):
        self.calls = []

    def segment_from_mask(self, image_path, mask_path, overlay_path):
        self.calls.append((image_path, mask_path, overlay_path))
        Path(overlay_path).write_text("fake overlay", encoding="utf-8")
        return {
            "image_outputs": {
                "original_image_path": image_path,
                "mask_path": mask_path,
                "overlay_path": overlay_path,
            },
            "features": {
                "whole_tumor_volume_ml": 123.0,
                "tumor_core_volume_ml": 45.0,
                "enhancing_tumor_volume_ml": 6.0,
                "edema_present": True,
                "mass_effect": "not_assessed_in_phase_a",
                "segmentation_quality": "fake_tool_boundary",
                "label_counts": {1: 39, 2: 78, 4: 6},
            },
            "mask_shape": {
                "width": 10,
                "height": 10,
                "depth": 1,
            },
            "segmentation_source": "ground_truth_mask",
        }


class SegmentationToolTest(unittest.TestCase):
    def _write_demo_image_and_mask(self, base_dir: Path) -> tuple[Path, Path]:
        image_path = base_dir / "case_flair.png"
        mask_path = base_dir / "case_mask.png"
        image = Image.new("L", (8, 8), 80)
        mask = Image.new("L", (8, 8), 0)
        pixels = mask.load()
        for x in range(1, 5):
            for y in range(1, 5):
                pixels[x, y] = 2
        for x in range(2, 4):
            for y in range(2, 4):
                pixels[x, y] = 1
        pixels[3, 3] = 4
        image.save(image_path)
        mask.save(mask_path)
        return image_path, mask_path

    def test_segmentation_tool_wraps_ground_truth_mask_reader_overlay_and_features(self):
        with TemporaryDirectory() as tmpdir:
            image_path, mask_path = self._write_demo_image_and_mask(Path(tmpdir))
            overlay_path = Path(tmpdir) / "overlay.png"

            result = SegmentationTool(
                feature_extractor=FeatureExtractionTool(voxel_volume_ml=0.5),
            ).segment_from_mask(
                image_path=image_path,
                mask_path=mask_path,
                overlay_path=overlay_path,
            )

            self.assertEqual(result["image_outputs"]["mask_path"], str(mask_path))
            self.assertTrue(overlay_path.exists())
            self.assertEqual(result["features"]["whole_tumor_volume_ml"], 8.0)
            self.assertEqual(result["features"]["tumor_core_volume_ml"], 2.0)
            self.assertEqual(result["mask_shape"]["width"], 8)
            self.assertEqual(result["segmentation_source"], "ground_truth_mask")

    def test_vision_agent_uses_segmentation_tool_boundary_for_brats_ground_truth(self):
        with TemporaryDirectory() as tmpdir:
            image_path = str(Path(tmpdir) / "image.png")
            mask_path = str(Path(tmpdir) / "mask.png")
            overlay_path = str(Path(tmpdir) / "overlay.png")
            fake_segmentation_tool = FakeSegmentationTool()

            result = VisionAgent(segmentation_tool=fake_segmentation_tool).analyze_brats_ground_truth(
                image_path=image_path,
                mask_path=mask_path,
                overlay_path=overlay_path,
                disease_knowledge={"disease_name": "成人弥漫性胶质瘤"},
            )

            self.assertEqual(fake_segmentation_tool.calls, [(image_path, mask_path, overlay_path)])
            self.assertEqual(result["visual_evidence"]["whole_tumor_volume_ml"], 123.0)
            self.assertEqual(result["visual_evidence"]["segmentation_quality"], "fake_tool_boundary")
            self.assertEqual(result["image_outputs"]["overlay_path"], overlay_path)


if __name__ == "__main__":
    unittest.main()
