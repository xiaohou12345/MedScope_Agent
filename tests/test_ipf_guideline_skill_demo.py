import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.ipf_guideline_skill_demo import run_ipf_guideline_skill_demo
from tools.guideline_search_tool import GuidelineSearchTool
from tools.visual_protocol_validator import VisualProtocolValidator


class IPFGuidelineSkillDemoTest(unittest.TestCase):
    def test_ipf_guideline_demo_generates_guideline_skill_with_hrct_visual_protocol(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            result = run_ipf_guideline_skill_demo(
                output_dir=output_dir,
                collect_sources=False,
            )

            skill = json.loads(Path(result["skill_output_path"]).read_text(encoding="utf-8"))
            search_result = GuidelineSearchTool(
                source_catalog_path=result["catalog_path"]
            ).search(
                disease_key="idiopathic_pulmonary_fibrosis_hrct",
                disease_name="特发性肺纤维化 HRCT 评估",
            )

        self.assertEqual(result["disease_key"], "idiopathic_pulmonary_fibrosis_hrct")
        self.assertEqual(skill["skill_type"], "guideline_based")
        self.assertEqual(skill["path_type"], "guideline_aware")
        self.assertIn("HRCT chest", skill["required_image_views"])
        self.assertIn("UIP_pattern", skill["staging_rules"])
        self.assertIn(
            "honeycombing_candidate",
            skill["vision_agent_tasks"]["segmentation_targets"],
        )
        self.assertEqual(
            skill["visual_protocol"]["disease_target"],
            "idiopathic_pulmonary_fibrosis_hrct",
        )
        self.assertIn(
            "HRCT chest",
            skill["visual_protocol"]["required_modalities"]["honeycombing_candidate"],
        )
        self.assertEqual(
            VisualProtocolValidator().validate_skill(skill)["status"],
            "valid",
        )
        self.assertTrue(search_result["has_guideline"])
        self.assertGreaterEqual(len(search_result["sources"]), 2)
        self.assertEqual(search_result["sources"][0]["source_id"], "ats_ers_jrs_alat_ipf_2022")


if __name__ == "__main__":
    unittest.main()
