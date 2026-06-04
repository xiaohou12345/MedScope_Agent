import json
import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.fhn_real_vlm_multiview_demo import main, run_demo


class FakeService:
    def __init__(self):
        self.payloads = []

    def handle_request(self, payload):
        self.payloads.append(payload)
        return {
            "case_id": "case_real_vlm_demo",
            "reply_to_patient": "候选视觉证据已生成。",
            "routing_decision": {
                "selected_skill": "femoral_head_necrosis",
                "selected_vision_mode": "real_vlm_validation",
            },
            "visual_evidence_bundle": {
                "schema_version": "visual_evidence_bundle.v2",
                "evidence_items": [
                    {
                        "target": "sclerotic_band",
                        "execution_mode": "vlm_only",
                        "diagnosis_usable_level": "candidate_support",
                        "diagnosis_usable": True,
                    },
                    {
                        "target": "cystic_change",
                        "execution_mode": "vlm_only",
                        "diagnosis_usable_level": "candidate_support",
                        "diagnosis_usable": True,
                    },
                    {
                        "target": "collapse",
                        "execution_mode": "measurement_only",
                        "diagnosis_usable_level": "not_usable",
                        "diagnosis_usable": False,
                    },
                ],
            },
            "evidence_bundle": {
                "case_id": "case_real_vlm_demo",
                "image_evidence": {
                    "visual_evidence_bundle": {
                        "evidence_items": [
                            {
                                "target": "sclerotic_band",
                                "execution_mode": "vlm_only",
                            }
                        ]
                    }
                },
            },
            "memory_audit": {"case_id": "case_real_vlm_demo", "agents_traced": ["GaoDoctorAgent"]},
            "report": {
                "diagnostic_tendency": "候选证据，需复核",
                "visual_fact_usage": {"used_count": 2, "excluded_count": 1},
            },
        }


class FhnRealVlmMultiViewDemoTest(unittest.TestCase):
    def test_demo_dry_run_writes_readiness_report_without_api_call(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "demo"
            result = run_demo(
                ap_image="/tmp/ap.png",
                lateral_image="/tmp/lateral.png",
                output_dir=output_dir,
                dry_run=True,
            )

            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["vision_mode"], "real_vlm_validation")
            self.assertTrue((output_dir / "readiness.json").exists())
            readiness = json.loads((output_dir / "readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(readiness["workflow"], "fhn_real_vlm_validation")
            self.assertFalse(readiness["network_call_attempted"])

    def test_demo_dry_run_loads_dotenv_local_without_leaking_secret(self):
        old_cwd = Path.cwd()
        with TemporaryDirectory() as tmpdir, patch.dict("os.environ", {}, clear=True):
            tmp_path = Path(tmpdir)
            (tmp_path / ".env.local").write_text("DMX_API_KEY=sk-test-secret\n", encoding="utf-8")
            output_dir = tmp_path / "demo"
            os.chdir(tmp_path)
            try:
                result = run_demo(
                    ap_image="/tmp/ap.png",
                    lateral_image="/tmp/lateral.png",
                    output_dir=output_dir,
                    dry_run=True,
                )
            finally:
                os.chdir(old_cwd)

            self.assertTrue(result["readiness"]["api_key_present"])
            self.assertEqual(result["readiness"]["status"], "ready")
            self.assertNotIn("sk-test-secret", json.dumps(result, ensure_ascii=False))

    def test_demo_real_run_writes_summary_evidence_report_and_audit(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "demo"
            service = FakeService()

            result = run_demo(
                ap_image="/tmp/ap.png",
                lateral_image="/tmp/lateral.png",
                output_dir=output_dir,
                message="左髋疼痛，上传正位和侧位 X 光",
                dry_run=False,
                service_factory=lambda: service,
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(service.payloads[0]["vision_mode"], "real_vlm_validation")
            self.assertEqual(service.payloads[0]["image_paths"], ["/tmp/ap.png", "/tmp/lateral.png"])
            self.assertTrue((output_dir / "summary.json").exists())
            self.assertTrue((output_dir / "evidence_bundle.json").exists())
            self.assertTrue((output_dir / "diagnosis_report.json").exists())
            self.assertTrue((output_dir / "audit.json").exists())
            self.assertTrue((output_dir / "input_manifest.json").exists())
            self.assertTrue((output_dir / "summary.md").exists())

            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["case_id"], "case_real_vlm_demo")
            self.assertEqual(summary["selected_vision_mode"], "real_vlm_validation")
            self.assertEqual(summary["evidence_item_count"], 3)
            self.assertEqual(summary["evidence_item_status_counts"]["candidate_support"], 2)
            self.assertEqual(summary["evidence_item_status_counts"]["not_usable"], 1)
            self.assertEqual(summary["execution_mode_counts"]["measurement_only"], 1)
            self.assertEqual(summary["diagnosis_usable_counts"]["usable"], 2)
            self.assertEqual(summary["diagnosis_usable_counts"]["not_usable"], 1)
            self.assertEqual(summary["visual_fact_usage_counts"], {"used_count": 2, "excluded_count": 1})
            self.assertEqual(summary["summary_markdown_path"], str(output_dir / "summary.md"))
            markdown = (output_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("# FHN Real VLM Multi-View Validation", markdown)
            self.assertIn("candidate_support: 2", markdown)
            self.assertIn("measurement_only: 1", markdown)
            self.assertIn("used_count: 2", markdown)
            self.assertIn("excluded_count: 1", markdown)
            self.assertIn("not clinical diagnosis", markdown)

    def test_cli_dry_run_prints_json_summary(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "demo"
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--ap-image",
                        "/tmp/ap.png",
                        "--lateral-image",
                        "/tmp/lateral.png",
                        "--output-dir",
                        str(output_dir),
                        "--dry-run",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "dry_run")
            self.assertTrue((output_dir / "readiness.json").exists())


if __name__ == "__main__":
    unittest.main()
