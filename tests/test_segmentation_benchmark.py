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

    def test_metric_ready_case_applies_manifest_quality_gate_without_diagnosis_upgrade(self):
        class FakeEvaluator:
            def evaluate(self, prediction_mask_path, reference_mask_path):
                self.paths = (prediction_mask_path, reference_mask_path)
                return {"lesion_dice": 0.72, "lesion_iou": 0.56}

        with TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "metric_ready_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "segmentation_benchmark_manifest.v1",
                        "benchmark_id": "fhn_metric_ready_fixture",
                        "safety": {
                            "web_demo_independent": True,
                            "not_clinical_diagnosis": True,
                            "formal_skill_update_allowed": False,
                        },
                        "metric_gates": {
                            "required_metrics": ["lesion_dice", "lesion_iou"],
                            "minimums": {"lesion_dice": 0.8, "lesion_iou": 0.5},
                        },
                        "cases": [
                            {
                                "case_id": "metric_ready_case",
                                "disease_key": "femoral_head_necrosis",
                                "modality": "X-ray",
                                "body_part": "hip",
                                "backend_type": "vlm_plus_segmenter",
                                "benchmark_role": "metric_ready_fixture",
                                "image_path": "benchmarks/segmentation/femoral_head_necrosis/images/case.png",
                                "prediction_mask_path": "benchmarks/segmentation/femoral_head_necrosis/prediction/case_mask.png",
                                "reference_mask_path": "benchmarks/segmentation/femoral_head_necrosis/reference/case_mask.png",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = run_segmentation_benchmark(
                manifest_path=manifest_path,
                output_dir=Path(tmpdir) / "benchmark",
                evaluator=FakeEvaluator(),
            )

            self.assertEqual(result["aggregate"]["metric_ready_case_count"], 1)
            self.assertEqual(result["aggregate"]["metric_pass_case_count"], 0)
            self.assertEqual(result["aggregate"]["metric_fail_case_count"], 1)
            case = result["cases"][0]
            self.assertEqual(case["metric_status"], "metric_ready")
            self.assertEqual(case["metrics"]["lesion_dice"], 0.72)
            self.assertEqual(case["quality_gate"]["status"], "fail")
            self.assertIn("lesion_dice", case["quality_gate"]["failed_metrics"])
            self.assertFalse(case["diagnosis_allowed"])
            self.assertFalse(case["formal_skill_update_allowed"])
            markdown = Path(result["output_paths"]["markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("metric_fail_case_count", markdown)
            self.assertIn("| metric_ready_case |", markdown)
            self.assertIn("| fail |", markdown)


if __name__ == "__main__":
    unittest.main()
