import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.brats_vision_test_line import (
    check_brats_medsam2_readiness,
    generate_brats_prompt_from_reference_mask,
    generate_brats_prompts_from_manifest,
    run_brats_vision_manifest,
    run_brats_vision_test_line,
    validate_brats_manifest,
)


REAL_SAMPLE_DIR = Path("data/external/brats2021_00030")
REAL_IMAGE = REAL_SAMPLE_DIR / "BraTS2021_00030_flair.nii.gz"
REAL_MASK = REAL_SAMPLE_DIR / "BraTS2021_00030_seg.nii.gz"


@unittest.skipUnless(
    REAL_IMAGE.exists() and REAL_MASK.exists(),
    "real BraTS2021 sample files are not downloaded",
)
class BratsVisionTestLineTest(unittest.TestCase):
    def test_real_brats_sample_writes_overlay_and_json_result(self):
        with TemporaryDirectory() as tmpdir:
            output = run_brats_vision_test_line(
                image_path=REAL_IMAGE,
                mask_path=REAL_MASK,
                output_dir=Path(tmpdir),
            )

            payload = json.loads(output)
            result = payload["result"]
            evidence = result["visual_evidence"]
            result_path = Path(payload["result_json_path"])
            overlay_path = Path(result["image_outputs"]["overlay_path"])

            self.assertEqual(payload["status"], "ok")
            self.assertTrue(result_path.exists())
            self.assertTrue(overlay_path.exists())
            self.assertGreater(overlay_path.stat().st_size, 1000)
            self.assertEqual(result["modality"], "MRI")
            self.assertEqual(result["body_part"], "brain")
            self.assertNotIn("diagnostic_tendency", result)
            self.assertGreater(evidence["whole_tumor_volume_ml"], 100)
            self.assertTrue(evidence["edema_present"])

    def test_manifest_case_can_drive_ground_truth_test_line(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "brats2021_00030",
                                "image_path": str(REAL_IMAGE),
                                "mask_path": str(REAL_MASK),
                                "disease_name": "成人弥漫性胶质瘤",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = run_brats_vision_test_line(
                manifest_path=manifest_path,
                case_id="brats2021_00030",
                output_dir=workdir / "output",
            )

            payload = json.loads(output)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["case_id"], "brats2021_00030")
            self.assertEqual(payload["mode"], "brats_nifti_ground_truth")
            self.assertTrue(Path(payload["result"]["image_outputs"]["overlay_path"]).exists())

    def test_brats_test_line_loads_glioma_knowledge_visual_protocol(self):
        with TemporaryDirectory() as tmpdir:
            output = run_brats_vision_test_line(
                image_path=REAL_IMAGE,
                mask_path=REAL_MASK,
                output_dir=Path(tmpdir),
            )

            payload = json.loads(output)
            evidence = payload["result"]["visual_evidence"]

            self.assertEqual(evidence["disease_target"], "diffuse_glioma_adult")
            self.assertEqual(evidence["measurements"]["whole_tumor_volume_ml"], 117.996)
            self.assertIsNone(evidence["measurements"]["enhancing_tumor_volume_ml"])
            self.assertEqual(evidence["completeness"]["whole_tumor"]["status"], "supported")
            self.assertEqual(evidence["completeness"]["enhancing_tumor"]["status"], "missing")

    def test_manifest_batch_writes_summary_for_all_cases(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "brats2021_00030",
                                "image_path": str(REAL_IMAGE),
                                "mask_path": str(REAL_MASK),
                                "reference_mask_path": str(REAL_MASK),
                                "disease_name": "成人弥漫性胶质瘤",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = run_brats_vision_manifest(
                manifest_path=manifest_path,
                output_dir=workdir / "output",
                mode="ground_truth",
            )

            payload = json.loads(output)
            summary_path = Path(payload["summary_path"])
            markdown_summary_path = Path(payload["summary_markdown_path"])
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["case_count"], 1)
            self.assertEqual(payload["ok_count"], 1)
            self.assertTrue(summary_path.exists())
            self.assertTrue(markdown_summary_path.exists())
            self.assertEqual(payload["cases"][0]["case_id"], "brats2021_00030")
            self.assertTrue(Path(payload["cases"][0]["result_json_path"]).exists())
            self.assertEqual(payload["aggregate"]["mean_whole_tumor_dice"], 1.0)
            self.assertEqual(payload["aggregate"]["mean_tumor_core_dice"], 1.0)
            self.assertEqual(payload["aggregate"]["mean_enhancing_tumor_dice"], 1.0)
            self.assertEqual(payload["failed_case_ids"], [])
            markdown = markdown_summary_path.read_text(encoding="utf-8")
            self.assertIn("brats2021_00030", markdown)
            self.assertIn("mean_whole_tumor_dice", markdown)
            self.assertIn("brats2021_00030_overlay.png", markdown)

    def test_manifest_batch_records_case_error_when_medsam2_is_not_configured(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "brats2021_00030",
                                "image_path": str(REAL_IMAGE),
                                "mask_path": str(REAL_MASK),
                                "reference_mask_path": str(REAL_MASK),
                                "disease_name": "成人弥漫性胶质瘤",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {}, clear=True):
                output = run_brats_vision_manifest(
                    manifest_path=manifest_path,
                    output_dir=workdir / "output",
                    mode="medsam2",
                )

            payload = json.loads(output)
            self.assertEqual(payload["status"], "partial_error")
            self.assertEqual(payload["ok_count"], 0)
            self.assertEqual(payload["failed_case_ids"], ["brats2021_00030"])
            self.assertIn("MEDSAM2_COMMAND_TEMPLATE", payload["cases"][0]["error"])
            self.assertTrue(Path(payload["summary_path"]).exists())

    def test_manifest_medsam2_mode_does_not_use_ground_truth_mask_as_model_output(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_mask = workdir / "ground_truth_seg.nii.gz"
            shutil.copyfile(REAL_MASK, manifest_mask)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "brats2021_00030",
                                "image_path": str(REAL_IMAGE),
                                "mask_path": str(manifest_mask),
                                "reference_mask_path": str(manifest_mask),
                                "disease_name": "成人弥漫性胶质瘤",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            fake_infer = workdir / "fake_medsam2_infer.py"
            fake_infer.write_text(
                "\n".join(
                    [
                        "import argparse",
                        "import shutil",
                        "parser = argparse.ArgumentParser()",
                        "parser.add_argument('--image')",
                        "parser.add_argument('--output')",
                        "parser.add_argument('--prompt-json')",
                        "parser.add_argument('--source-mask')",
                        "args = parser.parse_args()",
                        "shutil.copyfile(args.source_mask, args.output)",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(
                "os.environ",
                {
                    "MEDSAM2_COMMAND_TEMPLATE": (
                        f"python {fake_infer} "
                        "--image {image_path} "
                        "--output {output_mask_path} "
                        "--prompt-json {prompt_json} "
                        f"--source-mask {REAL_MASK.resolve()}"
                    ),
                    "MEDSAM2_REPO_PATH": str(workdir),
                },
                clear=False,
            ):
                output = run_brats_vision_test_line(
                    manifest_path=manifest_path,
                    case_id="brats2021_00030",
                    output_dir=workdir / "output",
                    mode="medsam2",
                    prompt={"boxes": [[1, 1, 5, 5]]},
                )

            payload = json.loads(output)
            model_mask = Path(payload["result"]["image_outputs"]["mask_path"])
            self.assertEqual(payload["status"], "ok")
            self.assertNotEqual(model_mask, manifest_mask)
            self.assertEqual(model_mask.name, "brats2021_00030_medsam2_mask.nii.gz")

    def test_manifest_validation_accepts_existing_paths(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "brats2021_00030",
                                "image_path": str(REAL_IMAGE),
                                "mask_path": str(REAL_MASK),
                                "reference_mask_path": str(REAL_MASK),
                                "disease_name": "成人弥漫性胶质瘤",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = json.loads(validate_brats_manifest(manifest_path))

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["case_count"], 1)
            self.assertEqual(payload["valid_count"], 1)
            self.assertEqual(payload["invalid_case_ids"], [])
            self.assertEqual(payload["cases"][0]["status"], "ok")
            self.assertEqual(payload["cases"][0]["errors"], [])

    def test_manifest_validation_reports_missing_paths_before_running_cases(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "missing_case",
                                "image_path": "missing_flair.nii.gz",
                                "mask_path": "missing_seg.nii.gz",
                                "reference_mask_path": "missing_reference.nii.gz",
                                "disease_name": "成人弥漫性胶质瘤",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = json.loads(validate_brats_manifest(manifest_path))
            case = payload["cases"][0]

            self.assertEqual(payload["status"], "invalid")
            self.assertEqual(payload["case_count"], 1)
            self.assertEqual(payload["valid_count"], 0)
            self.assertEqual(payload["invalid_case_ids"], ["missing_case"])
            self.assertEqual(case["status"], "invalid")
            self.assertTrue(any("image_path" in error for error in case["errors"]))
            self.assertTrue(any("mask_path" in error for error in case["errors"]))
            self.assertTrue(any("reference_mask_path" in error for error in case["errors"]))

    def test_manifest_validation_rejects_empty_case_list(self):
        with TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps({"cases": []}, ensure_ascii=False),
                encoding="utf-8",
            )

            payload = json.loads(validate_brats_manifest(manifest_path))

            self.assertEqual(payload["status"], "invalid")
            self.assertEqual(payload["case_count"], 0)
            self.assertEqual(payload["valid_count"], 0)
            self.assertEqual(payload["invalid_case_ids"], [])
            self.assertEqual(payload["errors"], ["No cases found in BraTS manifest"])

    def test_medsam2_readiness_reports_missing_runner_without_running_cases(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "brats2021_00030",
                                "image_path": str(REAL_IMAGE),
                                "mask_path": str(REAL_MASK),
                                "reference_mask_path": str(REAL_MASK),
                                "disease_name": "成人弥漫性胶质瘤",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {}, clear=True):
                payload = json.loads(check_brats_medsam2_readiness(manifest_path))

            self.assertEqual(payload["status"], "not_ready")
            self.assertEqual(payload["manifest_validation"]["status"], "ok")
            self.assertFalse(payload["medsam2_configuration"]["real_call_ready"])
            self.assertTrue(
                any("MEDSAM2_COMMAND_TEMPLATE" in error for error in payload["errors"])
            )

    def test_medsam2_readiness_accepts_valid_manifest_and_runner_configuration(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            fake_infer = workdir / "fake_medsam2_infer.py"
            fake_infer.write_text("print('dry-run only')\n", encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "brats2021_00030",
                                "image_path": str(REAL_IMAGE),
                                "mask_path": str(REAL_MASK),
                                "reference_mask_path": str(REAL_MASK),
                                "disease_name": "成人弥漫性胶质瘤",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(
                "os.environ",
                {
                    "MEDSAM2_COMMAND_TEMPLATE": (
                        f"python {fake_infer} "
                        "--image {image_path} "
                        "--output {output_mask_path} "
                        "--prompt-json {prompt_json}"
                    ),
                    "MEDSAM2_REPO_PATH": str(workdir),
                    "MEDSAM2_TIMEOUT_SECONDS": "30",
                },
                clear=True,
            ):
                payload = json.loads(check_brats_medsam2_readiness(manifest_path))

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["errors"], [])
            self.assertEqual(payload["manifest_validation"]["status"], "ok")
            self.assertTrue(payload["medsam2_configuration"]["real_call_ready"])
            self.assertFalse(payload["medsam2_configuration"]["real_call_attempted"])

    def test_medsam2_readiness_reports_invalid_command_template_placeholders(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "brats2021_00030",
                                "image_path": str(REAL_IMAGE),
                                "mask_path": str(REAL_MASK),
                                "reference_mask_path": str(REAL_MASK),
                                "disease_name": "成人弥漫性胶质瘤",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(
                "os.environ",
                {
                    "MEDSAM2_COMMAND_TEMPLATE": "python infer.py --image {image_path}",
                    "MEDSAM2_REPO_PATH": str(workdir),
                },
                clear=True,
            ):
                payload = json.loads(check_brats_medsam2_readiness(manifest_path))

            self.assertEqual(payload["status"], "not_ready")
            self.assertEqual(
                payload["medsam2_configuration"]["missing_command_template_placeholders"],
                ["output_mask_path", "prompt_json"],
            )
            self.assertTrue(any("output_mask_path" in error for error in payload["errors"]))

    def test_reference_mask_prompt_contains_2d_and_3d_boxes(self):
        prompt = generate_brats_prompt_from_reference_mask(REAL_MASK)

        self.assertEqual(prompt["source"], "reference_mask_bbox")
        self.assertEqual(prompt["label_ids"], [1, 2, 4])
        self.assertIn("slice_index", prompt)
        self.assertEqual(len(prompt["box_3d"]), 6)
        self.assertEqual(len(prompt["boxes"]), 1)
        x_min, y_min, x_max, y_max = prompt["boxes"][0]
        x0, y0, z0, x1, y1, z1 = prompt["box_3d"]
        self.assertLess(x_min, x_max)
        self.assertLess(y_min, y_max)
        self.assertLess(x0, x1)
        self.assertLess(y0, y1)
        self.assertLess(z0, z1)

    def test_medsam2_mode_can_build_prompt_from_reference_mask(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            captured_prompt = workdir / "captured_prompt.json"
            fake_infer = workdir / "fake_medsam2_infer.py"
            fake_infer.write_text(
                "\n".join(
                    [
                        "import argparse",
                        "import shutil",
                        "from pathlib import Path",
                        "parser = argparse.ArgumentParser()",
                        "parser.add_argument('--image')",
                        "parser.add_argument('--output')",
                        "parser.add_argument('--prompt-json')",
                        "parser.add_argument('--source-mask')",
                        "parser.add_argument('--capture-prompt')",
                        "args = parser.parse_args()",
                        "Path(args.capture_prompt).write_text(args.prompt_json, encoding='utf-8')",
                        "shutil.copyfile(args.source_mask, args.output)",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "MEDSAM2_COMMAND_TEMPLATE": (
                        f"python {fake_infer} "
                        "--image {image_path} "
                        "--output {output_mask_path} "
                        "--prompt-json {prompt_json} "
                        f"--source-mask {REAL_MASK.resolve()} "
                        f"--capture-prompt {captured_prompt}"
                    ),
                    "MEDSAM2_REPO_PATH": str(workdir),
                },
                clear=False,
            ):
                output = run_brats_vision_test_line(
                    image_path=REAL_IMAGE,
                    output_dir=workdir / "output",
                    mode="medsam2",
                    reference_mask_path=REAL_MASK,
                    prompt_from_reference_mask=True,
                )

            payload = json.loads(output)
            prompt = json.loads(captured_prompt.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["segmentation_prompt"]["source"], "reference_mask_bbox")
            self.assertEqual(prompt["source"], "reference_mask_bbox")
            self.assertIn("box_3d", prompt)
            self.assertIn("boxes", prompt)

    def test_generate_prompts_from_manifest_writes_case_prompt_and_summary(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            output_dir = workdir / "output"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "brats2021_00030",
                                "image_path": str(REAL_IMAGE),
                                "mask_path": str(REAL_MASK),
                                "reference_mask_path": str(REAL_MASK),
                                "disease_name": "成人弥漫性胶质瘤",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = generate_brats_prompts_from_manifest(
                manifest_path=manifest_path,
                output_dir=output_dir,
            )

            payload = json.loads(output)
            case = payload["cases"][0]
            prompt_path = Path(case["prompt_json_path"])
            prompt_overlay_path = Path(case["prompt_overlay_path"])
            summary_path = Path(payload["summary_path"])
            summary_markdown_path = Path(payload["summary_markdown_path"])
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["case_count"], 1)
            self.assertEqual(payload["ok_count"], 1)
            self.assertEqual(payload["failed_case_ids"], [])
            self.assertTrue(prompt_path.exists())
            self.assertTrue(prompt_overlay_path.exists())
            self.assertGreater(prompt_overlay_path.stat().st_size, 1000)
            self.assertTrue(summary_path.exists())
            self.assertTrue(summary_markdown_path.exists())
            prompt = json.loads(prompt_path.read_text(encoding="utf-8"))
            self.assertEqual(prompt["source"], "reference_mask_bbox")
            self.assertEqual(prompt["label_ids"], [1, 2, 4])
            self.assertEqual(case["prompt"]["source"], "reference_mask_bbox")
            markdown = summary_markdown_path.read_text(encoding="utf-8")
            self.assertIn("brats2021_00030", markdown)
            self.assertIn("slice_index", markdown)
            self.assertIn("box_3d", markdown)
            self.assertIn("brats2021_00030_prompt.json", markdown)
            self.assertIn("brats2021_00030_prompt_overlay.png", markdown)

    def test_generate_prompts_from_manifest_records_case_error_without_stopping(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "missing_reference",
                                "image_path": str(REAL_IMAGE),
                                "mask_path": str(REAL_MASK),
                                "reference_mask_path": "missing_reference.nii.gz",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = generate_brats_prompts_from_manifest(
                manifest_path=manifest_path,
                output_dir=workdir / "output",
            )

            payload = json.loads(output)
            self.assertEqual(payload["status"], "partial_error")
            self.assertEqual(payload["ok_count"], 0)
            self.assertEqual(payload["failed_case_ids"], ["missing_reference"])
            self.assertIn("missing_reference.nii.gz", payload["cases"][0]["error"])
            self.assertIsNone(payload["cases"][0]["prompt_overlay_path"])

    def test_medsam2_mode_writes_model_mask_overlay_and_json_result(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            fake_infer = workdir / "fake_medsam2_infer.py"
            fake_infer.write_text(
                "\n".join(
                    [
                        "import argparse",
                        "import shutil",
                        "parser = argparse.ArgumentParser()",
                        "parser.add_argument('--image')",
                        "parser.add_argument('--output')",
                        "parser.add_argument('--prompt-json')",
                        "parser.add_argument('--source-mask')",
                        "args = parser.parse_args()",
                        "shutil.copyfile(args.source_mask, args.output)",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "MEDSAM2_COMMAND_TEMPLATE": (
                        f"python {fake_infer} "
                        "--image {image_path} "
                        "--output {output_mask_path} "
                        "--prompt-json {prompt_json} "
                        f"--source-mask {REAL_MASK.resolve()}"
                    ),
                    "MEDSAM2_REPO_PATH": str(workdir),
                },
                clear=False,
            ):
                output = run_brats_vision_test_line(
                    image_path=REAL_IMAGE,
                    output_dir=workdir / "output",
                    mode="medsam2",
                    prompt={"boxes": [[1, 1, 5, 5]]},
                    reference_mask_path=REAL_MASK,
                )

            payload = json.loads(output)
            result = payload["result"]
            evidence = result["visual_evidence"]
            mask_path = Path(result["image_outputs"]["mask_path"])
            overlay_path = Path(result["image_outputs"]["overlay_path"])
            result_path = Path(payload["result_json_path"])

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["mode"], "brats_medsam2_model")
            self.assertIn("_medsam2_", result_path.name)
            self.assertIn("_medsam2_", overlay_path.name)
            self.assertTrue(mask_path.exists())
            self.assertTrue(overlay_path.exists())
            self.assertEqual(evidence["segmentation_quality"], "medsam2")
            self.assertGreater(evidence["whole_tumor_volume_ml"], 100)
            self.assertIn("medsam2 模型已生成肿瘤分割 mask", evidence["suspected_visual_findings"])
            self.assertEqual(payload["evaluation"]["whole_tumor_dice"], 1.0)
            self.assertEqual(payload["evaluation"]["tumor_core_dice"], 1.0)
            self.assertEqual(payload["evaluation"]["enhancing_tumor_dice"], 1.0)


if __name__ == "__main__":
    unittest.main()
