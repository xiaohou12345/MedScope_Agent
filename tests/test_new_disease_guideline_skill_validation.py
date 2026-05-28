from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.new_disease_guideline_skill_validation import (
    run_new_disease_guideline_skill_validation,
)


class NewDiseaseGuidelineSkillValidationTest(unittest.TestCase):
    def test_ipf_guideline_skill_visual_evidence_bundle_and_safety_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "validation"

            payload = run_new_disease_guideline_skill_validation(output_dir=output_dir)

            summary = json.loads(Path(payload["summary_json_path"]).read_text(encoding="utf-8"))
            markdown = Path(payload["summary_markdown_path"]).read_text(encoding="utf-8")

        self.assertEqual(summary["schema_version"], "new_disease_guideline_skill_validation.v1")
        self.assertEqual(summary["disease_key"], "idiopathic_pulmonary_fibrosis_hrct")
        self.assertEqual(summary["status"], "ok")
        self.assertTrue(summary["guideline_skill"]["generated"])
        self.assertEqual(summary["guideline_skill"]["skill_type"], "guideline_based")
        self.assertGreaterEqual(summary["guideline_skill"]["source_count"], 2)
        self.assertEqual(summary["guideline_skill"]["visual_protocol_status"], "valid")
        self.assertIn("HRCT chest", summary["guideline_skill"]["required_image_views"])
        self.assertEqual(summary["visual_evidence"]["status"], "ok")
        self.assertEqual(summary["visual_evidence"]["evidence_bundle_schema"], "ipf_visual_evidence_bundle.v1")
        self.assertEqual(summary["visual_evidence"]["anatomy_mask_role"], "anatomy_mask_not_fibrosis_ground_truth")
        self.assertEqual(summary["visual_evidence"]["present_finding_count"], 0)
        self.assertGreaterEqual(summary["visual_evidence"]["unassessed_target_count"], 4)
        self.assertFalse(summary["safety_boundary"]["diagnosis_allowed"])
        self.assertFalse(summary["safety_boundary"]["formal_skill_updated"])
        self.assertFalse(summary["safety_boundary"]["diagnosis_report_updated"])
        self.assertIn(
            "visual_protocol_can_build_evidence_bundle",
            summary["claims"]["can_claim"],
        )
        self.assertIn(
            "cannot_diagnose_ipf_from_dry_run_bundle",
            summary["claims"]["cannot_claim"],
        )
        self.assertIn("新病种 guideline skill 端到端验证", markdown)
        self.assertIn("idiopathic_pulmonary_fibrosis_hrct", markdown)
        self.assertIn("diagnosis_allowed=false", markdown)


if __name__ == "__main__":
    unittest.main()
