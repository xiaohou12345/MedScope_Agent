import json
import unittest
from pathlib import Path


class KnowledgeBaselineTest(unittest.TestCase):
    def test_fhn_finding_list_baseline_is_preserved_for_protocol_comparison(self):
        baseline_path = Path(
            "knowledge/baselines/femoral_head_necrosis_finding_list_baseline_20260604.yaml"
        )
        current_path = Path("knowledge/femoral_head_necrosis.yaml")

        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        current = json.loads(current_path.read_text(encoding="utf-8"))

        self.assertEqual(baseline["knowledge_id"], "femoral_head_necrosis_v0.1")
        self.assertIn("finding_targets", baseline["visual_protocol"])
        self.assertNotIn("imaging_evidence_protocol", baseline)
        self.assertNotIn("quantitative_evidence_protocol", baseline)
        self.assertIn("imaging_evidence_protocol", current)
        self.assertIn("quantitative_evidence_protocol", current)


if __name__ == "__main__":
    unittest.main()
