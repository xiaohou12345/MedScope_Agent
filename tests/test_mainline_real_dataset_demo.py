import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.mainline_real_dataset_demo import main, run_mainline_real_dataset_demo


REAL_SAMPLE_DIR = Path("data/external/brats2021_00030")
REAL_IMAGE = REAL_SAMPLE_DIR / "BraTS2021_00030_flair.nii.gz"
REAL_MASK = REAL_SAMPLE_DIR / "BraTS2021_00030_seg.nii.gz"
REAL_MANIFEST = Path("data/external/brats_manifest.json")


@unittest.skipUnless(
    REAL_IMAGE.exists() and REAL_MASK.exists() and REAL_MANIFEST.exists(),
    "real BraTS2021 sample files are not downloaded",
)
class MainlineRealDatasetDemoTest(unittest.TestCase):
    def test_demo_runs_real_dataset_prompt_vision_e2e_and_audit(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "mainline_real_dataset"

            result = run_mainline_real_dataset_demo(output_dir=output_dir)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["dataset"], "BraTS2021")
            self.assertEqual(result["disease_key"], "diffuse_glioma_brats")
            self.assertEqual(result["manifest_validation"]["status"], "ok")
            self.assertEqual(result["prompt_generation"]["status"], "ok")
            self.assertEqual(result["vision_ground_truth"]["status"], "ok")
            self.assertEqual(result["end_to_end"]["routing_decision"]["selected_skill"], "diffuse_glioma_brats")
            self.assertEqual(result["end_to_end"]["routing_decision"]["selected_vision_mode"], "ground_truth")
            self.assertTrue(Path(result["summary_path"]).exists())
            self.assertTrue(Path(result["run_markdown_path"]).exists())
            self.assertTrue(Path(result["end_to_end"]["evidence_bundle_path"]).exists())
            self.assertTrue(Path(result["end_to_end"]["audit_path"]).exists())

            summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
            run_markdown = Path(result["run_markdown_path"]).read_text(encoding="utf-8")

            self.assertEqual(summary["status"], "ok")
            self.assertIn("真实数据闭环", run_markdown)
            self.assertIn("ground-truth mask", run_markdown)
            self.assertIn("不是 MedSAM2 真实自动分割结果", run_markdown)

    def test_cli_writes_summary(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "mainline_real_dataset_cli"
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["--output-dir", str(output_dir)])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(Path(payload["summary_path"]).exists())


if __name__ == "__main__":
    unittest.main()
