import tempfile
import unittest
from pathlib import Path

from scripts.evidence_bounded_reasoning_eval import build_evidence_bounded_reasoning_eval


class EvidenceBoundedReasoningEvalTest(unittest.TestCase):
    def test_eval_summarizes_five_reasoning_boundaries_without_violations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            eval_result = build_evidence_bounded_reasoning_eval(output_dir=root / "out")

            self.assertEqual(
                eval_result["schema_version"],
                "evidence_bounded_reasoning_eval.v1",
            )
            self.assertEqual(eval_result["status"], "passed")
            self.assertEqual(eval_result["case_count"], 5)
            self.assertEqual(
                set(eval_result["category_summary"]),
                {"adopted", "missing", "excluded", "overlap", "qa"},
            )
            self.assertEqual(eval_result["metrics"]["unsupported_claim_count"], 0)
            self.assertEqual(eval_result["metrics"]["missing_as_negative_violation_count"], 0)
            self.assertEqual(eval_result["metrics"]["excluded_fact_reuse_violation_count"], 0)
            self.assertEqual(eval_result["metrics"]["overlap_double_count_violation_count"], 0)
            self.assertEqual(eval_result["metrics"]["qa_grounding_violation_count"], 0)
            self.assertTrue(eval_result["runtime_safety"]["evidence_bundle_required"])
            self.assertTrue(eval_result["runtime_safety"]["diagnosis_uses_adopted_evidence_only"])
            self.assertFalse(eval_result["runtime_safety"]["diagnosis_report_updated"])
            self.assertTrue(
                all(case["passed"] is True for case in eval_result["eval_cases"])
            )
            markdown = (root / "out" / "evidence_bounded_reasoning_eval.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Evidence-bounded Reasoning Eval", markdown)
            self.assertIn("missing_as_negative_violation_count", markdown)
            self.assertIn("QA", markdown)


if __name__ == "__main__":
    unittest.main()
