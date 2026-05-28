import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.vision_agent import VisionAgent
from tools.nifti_overlay_generation_tool import NiftiOverlayGenerationTool


REAL_SAMPLE_DIR = Path("data/external/brats2021_00030")
REAL_IMAGE = REAL_SAMPLE_DIR / "BraTS2021_00030_flair.nii.gz"
REAL_MASK = REAL_SAMPLE_DIR / "BraTS2021_00030_seg.nii.gz"


@unittest.skipUnless(
    REAL_IMAGE.exists() and REAL_MASK.exists(),
    "real BraTS2021 sample files are not downloaded",
)
class RealBratsSampleTest(unittest.TestCase):
    def test_nifti_overlay_generation_writes_real_png(self):
        with TemporaryDirectory() as tmpdir:
            overlay_path = Path(tmpdir) / "real_overlay.png"

            result = NiftiOverlayGenerationTool().generate_overlay(
                image_path=REAL_IMAGE,
                mask_path=REAL_MASK,
                overlay_path=overlay_path,
            )

            self.assertEqual(result, overlay_path)
            self.assertTrue(overlay_path.exists())
            self.assertGreater(overlay_path.stat().st_size, 1000)

    def test_vision_agent_runs_real_brats_nifti_sample(self):
        with TemporaryDirectory() as tmpdir:
            overlay_path = Path(tmpdir) / "real_overlay.png"

            result = VisionAgent().analyze_brats_nifti_ground_truth(
                image_path=str(REAL_IMAGE),
                mask_path=str(REAL_MASK),
                overlay_path=str(overlay_path),
                disease_skill={"disease_name": "成人弥漫性胶质瘤"},
            )

            evidence = result["visual_evidence"]
            self.assertEqual(result["modality"], "MRI")
            self.assertEqual(result["image_outputs"]["mask_path"], str(REAL_MASK))
            self.assertTrue(Path(result["image_outputs"]["overlay_path"]).exists())
            self.assertGreater(evidence["whole_tumor_volume_ml"], 100)
            self.assertGreater(evidence["enhancing_tumor_volume_ml"], 20)
            self.assertTrue(evidence["edema_present"])


if __name__ == "__main__":
    unittest.main()
