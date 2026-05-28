import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.test_mvp_flow import FakeNoMaskSkillPipeline

from scripts.end_to_end_demo import main as end_to_end_demo_main
from scripts.end_to_end_demo import run_end_to_end_demo, run_standard_demo_suite


class EndToEndDemoTest(unittest.TestCase):
    def test_demo_runs_upload_route_diagnosis_memory_bundle_and_audit(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "demo"

            result = run_end_to_end_demo(
                output_dir=output_dir,
                image_path=Path("data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz"),
                mask_path=Path("data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz"),
                patient_message="请基于这次 FLAIR MRI 做胶质瘤辅助分析",
                patient_info={
                    "patient_id": "demo_patient_001",
                    "age": 58,
                    "sex": "male",
                    "symptoms": ["头痛"],
                },
            )

            summary_path = Path(result["summary_path"])
            evidence_bundle_path = Path(result["evidence_bundle_path"])
            audit_path = Path(result["audit_path"])
            uploaded_image_path = Path(result["uploaded_image_path"])

            self.assertTrue(summary_path.exists())
            self.assertTrue(evidence_bundle_path.exists())
            self.assertTrue(audit_path.exists())
            self.assertTrue(uploaded_image_path.exists())
            self.assertIn("output/fake", result["demo_output_dir"])
            self.assertIn("case_id", result)
            self.assertEqual(result["routing_decision"]["selected_skill"], "diffuse_glioma_brats")
            self.assertEqual(result["routing_decision"]["selected_vision_mode"], "ground_truth")
            self.assertIn("image_outputs", result)
            self.assertIn("overlay_path", result["image_outputs"])
            self.assertIn("report", result)
            self.assertIn("reply_to_patient", result)

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            bundle = json.loads(evidence_bundle_path.read_text(encoding="utf-8"))
            audit = json.loads(audit_path.read_text(encoding="utf-8"))

            self.assertEqual(summary["case_id"], result["case_id"])
            self.assertEqual(summary["steps"]["upload"]["status"], "completed")
            self.assertEqual(summary["steps"]["auto_skill_routing"]["selected_skill"], "diffuse_glioma_brats")
            self.assertEqual(summary["steps"]["visual_segmentation"]["status"], "completed")
            self.assertTrue(Path(summary["steps"]["visual_segmentation"]["image_outputs"]["overlay_path"]).exists())
            self.assertEqual(summary["steps"]["evidence_bundle"]["path"], str(evidence_bundle_path))
            self.assertEqual(summary["steps"]["memory_audit"]["path"], str(audit_path))
            self.assertEqual(bundle["case_id"], result["case_id"])
            self.assertEqual(bundle["patient_context"]["patient_id"], "demo_patient_001")
            self.assertEqual(audit["case_id"], result["case_id"])
            self.assertTrue(audit["memory_completeness"]["patient_memory"])

    def test_standard_demo_suite_runs_glioma_and_xray_insufficient_cases(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "standard_demo"

            result = run_standard_demo_suite(output_dir=output_dir)

            summary_path = Path(result["summary_path"])
            markdown_path = Path(result["summary_markdown_path"])
            cases = {case["case_key"]: case for case in result["cases"]}

            self.assertTrue(summary_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertIn("output/fake", result["demo_output_dir"])
            self.assertEqual(result["status"], "ok")
            self.assertEqual(set(cases), {"glioma_ground_truth", "xray_insufficient_evidence"})

            glioma = cases["glioma_ground_truth"]
            glioma_response = json.loads(Path(glioma["response_path"]).read_text(encoding="utf-8"))
            self.assertEqual(glioma["analysis_status"], "partial_evidence")
            self.assertEqual(glioma["routing_decision"]["selected_skill"], "diffuse_glioma_brats")
            self.assertEqual(glioma["steps"]["visual_segmentation"]["status"], "completed")
            self.assertTrue(Path(glioma["steps"]["visual_segmentation"]["image_outputs"]["overlay_path"]).exists())
            self.assertTrue(Path(glioma["evidence_bundle_path"]).exists())
            self.assertTrue(Path(glioma["audit_path"]).exists())
            self.assertIn("report", glioma_response)

            xray = cases["xray_insufficient_evidence"]
            xray_response = json.loads(Path(xray["response_path"]).read_text(encoding="utf-8"))
            self.assertEqual(xray["analysis_status"], "insufficient_evidence")
            self.assertEqual(xray["routing_decision"]["selected_skill"], "femoral_head_necrosis")
            self.assertEqual(xray["steps"]["visual_segmentation"]["status"], "skipped_insufficient_evidence")
            self.assertEqual(xray["image_outputs"]["mask_path"], "not_generated")
            self.assertEqual(xray["required_next_images"][0]["modality"], "MRI")
            self.assertTrue(Path(xray["evidence_bundle_path"]).exists())
            self.assertTrue(Path(xray["audit_path"]).exists())
            self.assertIn("现有影像证据不足", xray_response["report"]["诊断倾向"])

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertEqual(summary["case_count"], 2)
            self.assertIn("glioma_ground_truth", markdown)
            self.assertIn("xray_insufficient_evidence", markdown)

    def test_standard_demo_suite_can_include_fhn_no_mask_multifinding_case(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "standard_demo"
            no_mask_runner = FakeNoMaskSkillPipeline()

            result = run_standard_demo_suite(
                output_dir=output_dir,
                include_fhn_no_mask=True,
                no_mask_visual_pipeline_runner=no_mask_runner,
            )

            cases = {case["case_key"]: case for case in result["cases"]}
            self.assertIn("fhn_no_mask_multifinding", cases)
            fhn = cases["fhn_no_mask_multifinding"]
            response = json.loads(Path(fhn["response_path"]).read_text(encoding="utf-8"))

            self.assertEqual(len(no_mask_runner.calls), 1)
            self.assertTrue(str(no_mask_runner.calls[0]["image_path"]).endswith("fhn_pelvis_xray_panel_b.png"))
            self.assertEqual(fhn["routing_decision"]["selected_skill"], "femoral_head_necrosis")
            self.assertEqual(fhn["routing_decision"]["selected_vision_mode"], "no_mask_skill")
            self.assertEqual(fhn["steps"]["visual_segmentation"]["status"], "completed")
            self.assertEqual(
                response["visual_evidence_bundle"]["present_findings"],
                ["sclerotic_band", "cystic_change"],
            )
            self.assertEqual(
                response["visual_evidence_bundle"]["findings"][0]["measurements"][
                    "anatomy_match"
                ]["anatomy_name"],
                "femoral_head",
            )
            self.assertEqual(result["case_count"], 3)

    def test_standard_demo_cli_suite_writes_summary(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "cli_standard_demo"

            with redirect_stdout(StringIO()):
                exit_code = end_to_end_demo_main(["--suite", "--output-dir", str(output_dir)])

            demo_dir = Path("output/fake") / output_dir.name
            self.assertEqual(exit_code, 0)
            self.assertTrue((demo_dir / "standard_demo_summary.json").exists())
            self.assertTrue((demo_dir / "demo_summary.md").exists())

    def test_standard_demo_cli_suite_uses_standard_default_output_dir(self):
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = end_to_end_demo_main(["--suite"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["demo_output_dir"], "output/fake/standard_demo")


if __name__ == "__main__":
    unittest.main()
