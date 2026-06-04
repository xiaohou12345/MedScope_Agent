import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.segmentation_benchmark import (
    DEFAULT_FHN_PUBLIC_FIXTURE_MANIFEST,
    run_segmentation_benchmark,
)


class SegmentationBenchmarkTest(unittest.TestCase):
    def test_default_fhn_manifest_runs_as_web_demo_independent_readiness_gate(self):
        self.assertTrue(DEFAULT_FHN_PUBLIC_FIXTURE_MANIFEST.exists())

        with TemporaryDirectory() as tmpdir:
            result = run_segmentation_benchmark(
                manifest_path=DEFAULT_FHN_PUBLIC_FIXTURE_MANIFEST,
                output_dir=Path(tmpdir) / "benchmark",
                prepare_fixtures=True,
            )

            self.assertEqual(result["schema_version"], "segmentation_benchmark_result.v1")
            self.assertEqual(result["benchmark_scope"], "disease_specific_segmentation_validation")
            self.assertTrue(result["safety"]["web_demo_independent"])
            self.assertTrue(result["safety"]["not_clinical_diagnosis"])
            self.assertFalse(result["safety"]["formal_skill_update_allowed"])
            self.assertEqual(result["aggregate"]["case_count"], 1)
            self.assertEqual(result["aggregate"]["metric_ready_case_count"], 0)
            self.assertEqual(result["aggregate"]["missing_reference_mask_count"], 1)

            case = result["cases"][0]
            self.assertEqual(case["disease_key"], "femoral_head_necrosis")
            self.assertEqual(case["metric_status"], "missing_reference_mask")
            self.assertIsNone(case["metrics"])
            self.assertIn("segmentation metrics require reference_mask_path", case["limitations"])
            self.assertNotIn("web", str(case["image_path"]).lower())
            self.assertNotIn("output/real", str(case["image_path"]))

            summary_path = Path(result["output_paths"]["json_path"])
            markdown_path = Path(result["output_paths"]["markdown_path"])
            self.assertTrue(summary_path.exists())
            self.assertTrue(markdown_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertEqual(summary["aggregate"]["metric_ready_case_count"], 0)
            self.assertIn("missing_reference_mask", markdown)

    def test_manifest_rejects_cases_that_mix_benchmark_with_web_demo_artifacts(self):
        with TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "bad_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "segmentation_benchmark_manifest.v1",
                        "benchmark_id": "bad_web_demo_manifest",
                        "cases": [
                            {
                                "case_id": "bad_case",
                                "disease_key": "femoral_head_necrosis",
                                "modality": "X-ray",
                                "image_path": "web/static/demo.png",
                                "reference_mask_path": None,
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "web demo artifact"):
                run_segmentation_benchmark(
                    manifest_path=manifest_path,
                    output_dir=Path(tmpdir) / "benchmark",
                )


if __name__ == "__main__":
    unittest.main()
