import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from api.service import MedScopeService
from tests.test_service_entrypoint import FakeGaoDoctor

from scripts.prepare_public_demo_fixture import (
    main as public_demo_fixture_main,
    prepare_public_demo_fixture,
    run_public_safe_demo_suite,
)


class PublicDemoFixtureTest(unittest.TestCase):
    def test_fixture_generates_public_safe_image_and_service_payload(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "fixture"

            result = prepare_public_demo_fixture(output_dir=output_dir)

            manifest_path = Path(result["manifest_path"])
            image_path = Path(result["image_path"])
            self.assertTrue(manifest_path.exists())
            self.assertTrue(image_path.exists())
            self.assertEqual(image_path.suffix, ".png")
            self.assertIn("public_safe", result["safety"])
            self.assertNotIn("data/external", str(image_path))
            self.assertNotIn("output/real", str(image_path))

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload = manifest["service_payload"]
            self.assertEqual(payload["image_path"], str(image_path))
            self.assertEqual(payload["disease_key"], "femoral_head_necrosis")
            self.assertEqual(payload["vision_mode"], "no_mask_skill")

            fake_doctor = FakeGaoDoctor()
            service = MedScopeService(gaodoctor_agent=fake_doctor)
            service_result = service.handle_request(payload)

            self.assertEqual(service_result["routing_decision"]["selected_skill"], "femoral_head_necrosis")
            self.assertEqual(service_result["routing_decision"]["selected_vision_mode"], "no_mask_skill")
            self.assertEqual(fake_doctor.calls[0]["image_path"], str(image_path))

    def test_public_safe_demo_suite_runs_service_memory_audit_and_qa_without_real_data(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "public_suite"

            result = run_public_safe_demo_suite(output_dir=output_dir)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["safety"]["real_fhn_data_required"], False)
            self.assertEqual(result["safety"]["not_clinical_diagnosis"], True)
            self.assertTrue(Path(result["fixture_manifest_path"]).exists())
            self.assertTrue(Path(result["response_path"]).exists())
            self.assertTrue(Path(result["evidence_bundle_path"]).exists())
            self.assertTrue(Path(result["memory_audit_path"]).exists())
            self.assertTrue(Path(result["qa_response_path"]).exists())
            self.assertTrue(Path(result["summary_markdown_path"]).exists())

            response = json.loads(Path(result["response_path"]).read_text(encoding="utf-8"))
            qa_response = json.loads(Path(result["qa_response_path"]).read_text(encoding="utf-8"))
            audit = json.loads(Path(result["memory_audit_path"]).read_text(encoding="utf-8"))

            self.assertEqual(response["routing_decision"]["selected_skill"], "femoral_head_necrosis")
            self.assertEqual(response["routing_decision"]["selected_vision_mode"], "no_mask_skill")
            self.assertEqual(qa_response["intent"], "qa")
            self.assertEqual(qa_response["case_id"], response["case_id"])
            self.assertIn("reply_to_patient", qa_response)
            self.assertGreaterEqual(audit["qa_safety"]["qa_history_count"], 1)
            self.assertIn("GaoDoctorAgent QA", audit["agents_traced"])

            markdown = Path(result["summary_markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("public_safe", markdown)
            self.assertIn("follow-up QA", markdown)
            self.assertIn("not clinical diagnosis", markdown)

    def test_public_safe_demo_suite_cli_writes_summary(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "public_suite_cli"
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = public_demo_fixture_main(["--suite", "--output-dir", str(output_dir)])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue((output_dir / "public_safe_demo_summary.json").exists())
            self.assertTrue((output_dir / "public_safe_demo_summary.md").exists())
            self.assertTrue(Path(payload["qa_response_path"]).exists())


if __name__ == "__main__":
    unittest.main()
