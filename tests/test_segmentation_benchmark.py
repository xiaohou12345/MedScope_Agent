import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

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
            self.assertEqual(result["evaluator_type"], "binary_mask")
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
            tmp = Path(tmpdir)
            prediction_path = tmp / "prediction.png"
            reference_path = tmp / "reference.png"
            prediction_path.write_text("fake prediction", encoding="utf-8")
            reference_path.write_text("fake reference", encoding="utf-8")
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
                                "prediction_mask_path": str(prediction_path),
                                "reference_mask_path": str(reference_path),
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

    def test_manifest_reports_missing_mask_files_before_calling_evaluator(self):
        class RaisingEvaluator:
            def evaluate(self, prediction_mask_path, reference_mask_path):
                raise AssertionError("evaluator should not run for missing mask files")

        with TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "missing_file_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "segmentation_benchmark_manifest.v1",
                        "benchmark_id": "fhn_missing_files_fixture",
                        "evaluator_type": "binary_mask",
                        "cases": [
                            {
                                "case_id": "missing_reference_file_case",
                                "disease_key": "femoral_head_necrosis",
                                "modality": "X-ray",
                                "prediction_mask_path": str(Path(tmpdir) / "prediction.png"),
                                "reference_mask_path": str(Path(tmpdir) / "reference.png"),
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
                evaluator=RaisingEvaluator(),
            )

            case = result["cases"][0]
            self.assertEqual(case["metric_status"], "missing_reference_file")
            self.assertIsNone(case["metrics"])
            self.assertEqual(result["aggregate"]["missing_reference_file_count"], 1)
            self.assertEqual(result["aggregate"]["metric_ready_case_count"], 0)
            self.assertIn("reference_mask_path does not exist", case["limitations"])
            markdown = Path(result["output_paths"]["markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("missing_reference_file_count", markdown)
            self.assertIn("missing_reference_file", markdown)

    def test_manifest_can_select_binary_mask_evaluator_for_fhn_png_masks(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            prediction_path = tmp / "prediction.png"
            reference_path = tmp / "reference.png"
            prediction = Image.new("L", (4, 4), 0)
            reference = Image.new("L", (4, 4), 0)
            for point in [(0, 0), (1, 0), (1, 1), (3, 3)]:
                prediction.putpixel(point, 255)
            for point in [(0, 0), (1, 0), (2, 2)]:
                reference.putpixel(point, 255)
            prediction.save(prediction_path)
            reference.save(reference_path)

            manifest_path = tmp / "binary_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "segmentation_benchmark_manifest.v1",
                        "benchmark_id": "fhn_binary_mask_fixture",
                        "evaluator_type": "binary_mask",
                        "metric_gates": {
                            "required_metrics": ["lesion_dice", "lesion_iou"],
                            "minimums": {"lesion_dice": 0.5, "lesion_iou": 0.4},
                        },
                        "cases": [
                            {
                                "case_id": "binary_metric_case",
                                "disease_key": "femoral_head_necrosis",
                                "modality": "X-ray",
                                "body_part": "hip",
                                "backend_type": "vlm_plus_segmenter",
                                "benchmark_role": "metric_ready_fixture",
                                "image_path": str(tmp / "image.png"),
                                "prediction_mask_path": str(prediction_path),
                                "reference_mask_path": str(reference_path),
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
                output_dir=tmp / "benchmark",
            )

            case = result["cases"][0]
            self.assertEqual(case["metric_status"], "metric_ready")
            self.assertAlmostEqual(case["metrics"]["lesion_dice"], 4 / 7)
            self.assertAlmostEqual(case["metrics"]["lesion_iou"], 0.4)
            self.assertEqual(case["quality_gate"]["status"], "pass")
            self.assertEqual(result["aggregate"]["metric_pass_case_count"], 1)
            self.assertEqual(result["aggregate"]["metric_fail_case_count"], 0)

    def test_relative_case_paths_are_resolved_from_manifest_directory(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "dataset"
            prediction_dir = root / "prediction"
            reference_dir = root / "reference"
            images_dir = root / "images"
            prediction_dir.mkdir(parents=True)
            reference_dir.mkdir(parents=True)
            images_dir.mkdir(parents=True)
            prediction_path = prediction_dir / "case_mask.png"
            reference_path = reference_dir / "case_mask.png"
            image_path = images_dir / "case.png"
            Image.new("L", (4, 4), 0).save(image_path)
            prediction = Image.new("L", (4, 4), 0)
            reference = Image.new("L", (4, 4), 0)
            for point in [(0, 0), (1, 0)]:
                prediction.putpixel(point, 255)
                reference.putpixel(point, 255)
            prediction.save(prediction_path)
            reference.save(reference_path)

            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "segmentation_benchmark_manifest.v1",
                        "benchmark_id": "relative_path_fixture",
                        "evaluator_type": "binary_mask",
                        "metric_gates": {
                            "required_metrics": ["lesion_dice"],
                            "minimums": {"lesion_dice": 1.0},
                        },
                        "cases": [
                            {
                                "case_id": "relative_case",
                                "disease_key": "femoral_head_necrosis",
                                "modality": "X-ray",
                                "image_path": "images/case.png",
                                "prediction_mask_path": "prediction/case_mask.png",
                                "reference_mask_path": "reference/case_mask.png",
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
            )

            case = result["cases"][0]
            self.assertEqual(case["metric_status"], "metric_ready")
            self.assertEqual(case["quality_gate"]["status"], "pass")
            self.assertEqual(case["metrics"]["lesion_dice"], 1.0)
            self.assertEqual(Path(case["prediction_mask_path"]), prediction_path)
            self.assertEqual(Path(case["reference_mask_path"]), reference_path)
            self.assertEqual(Path(case["image_path"]), image_path)

    def test_manifest_rejects_unknown_evaluator_type_without_silent_fallback(self):
        with TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "bad_evaluator_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "segmentation_benchmark_manifest.v1",
                        "benchmark_id": "bad_evaluator",
                        "evaluator_type": "unknown_model_specific_metric",
                        "cases": [
                            {
                                "case_id": "bad_case",
                                "disease_key": "femoral_head_necrosis",
                                "modality": "X-ray",
                                "reference_mask_path": None,
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unsupported segmentation benchmark evaluator_type"):
                run_segmentation_benchmark(
                    manifest_path=manifest_path,
                    output_dir=Path(tmpdir) / "benchmark",
                )


if __name__ == "__main__":
    unittest.main()
