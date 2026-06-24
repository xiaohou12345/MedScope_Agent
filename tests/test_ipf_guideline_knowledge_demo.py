import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.ipf_guideline_knowledge_demo import run_ipf_guideline_knowledge_demo
from tools.guideline_search_tool import GuidelineSearchTool
from tools.visual_protocol_validator import VisualProtocolValidator


class IPFGuidelineKnowledgeDemoTest(unittest.TestCase):
    def test_ipf_guideline_demo_generates_guideline_knowledge_with_hrct_visual_protocol(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            result = run_ipf_guideline_knowledge_demo(
                output_dir=output_dir,
                collect_sources=False,
            )

            knowledge = json.loads(Path(result["knowledge_output_path"]).read_text(encoding="utf-8"))
            search_result = GuidelineSearchTool(
                source_catalog_path=result["catalog_path"]
            ).search(
                disease_key="idiopathic_pulmonary_fibrosis_hrct",
                disease_name="特发性肺纤维化 HRCT 评估",
            )

        self.assertEqual(result["disease_key"], "idiopathic_pulmonary_fibrosis_hrct")
        self.assertEqual(knowledge["knowledge_type"], "guideline_based")
        self.assertEqual(knowledge["path_type"], "guideline_aware")
        self.assertIn("HRCT chest", knowledge["required_image_views"])
        self.assertIn("UIP_pattern", knowledge["staging_rules"])
        self.assertIn(
            "honeycombing_candidate",
            knowledge["vision_agent_tasks"]["segmentation_targets"],
        )
        self.assertEqual(
            knowledge["visual_protocol"]["disease_target"],
            "idiopathic_pulmonary_fibrosis_hrct",
        )
        self.assertIn(
            "HRCT chest",
            knowledge["visual_protocol"]["required_modalities"]["honeycombing_candidate"],
        )
        self.assertEqual(
            VisualProtocolValidator().validate_knowledge(knowledge)["status"],
            "valid",
        )
        self.assertTrue(search_result["has_guideline"])
        self.assertGreaterEqual(len(search_result["sources"]), 2)
        self.assertEqual(search_result["sources"][0]["source_id"], "ats_ers_jrs_alat_ipf_2022")


if __name__ == "__main__":
    unittest.main()
