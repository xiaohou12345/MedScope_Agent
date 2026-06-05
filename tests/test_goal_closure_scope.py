import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCOPE_DOC = REPO_ROOT / "docs" / "CURRENT_GOAL_CLOSURE_SCOPE_20260605.md"
COMPLETION_AUDIT_DOC = REPO_ROOT / "docs" / "CURRENT_GOAL_COMPLETION_AUDIT_20260605.md"
FHN_MVP_DOC = REPO_ROOT / "docs" / "FHN_EVIDENCE_PROTOCOL_MVP_20260604.md"


class GoalClosureScopeTest(unittest.TestCase):
    def test_current_goal_scope_defers_real_fhn_data_without_claiming_real_benchmark(self):
        self.assertTrue(SCOPE_DOC.exists())

        text = SCOPE_DOC.read_text(encoding="utf-8")
        self.assertIn("Current Goal Closure Scope", text)
        self.assertIn("real FHN data and masks are deferred", text)
        self.assertIn("not required for this goal", text)
        self.assertIn("421 tests", text)
        self.assertIn("437 tests", text)
        self.assertIn("76.867s", text)
        self.assertIn("OK", text)
        self.assertIn("public-safe fixture quality boundary guard", text)
        self.assertIn("benchmark result isolation guard", text)
        self.assertIn("completion audit guard", text)
        self.assertNotIn("real FHN benchmark completed", text)
        self.assertNotIn("metric-ready real benchmark completed", text)

    def test_project_readmes_link_current_goal_scope(self):
        target = "docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md"
        for readme_name in ["README.md", "README.zh-CN.md"]:
            with self.subTest(readme_name=readme_name):
                readme = (REPO_ROOT / readme_name).read_text(encoding="utf-8")
                self.assertIn(target, readme)

    def test_current_goal_completion_audit_maps_scope_to_evidence(self):
        self.assertTrue(COMPLETION_AUDIT_DOC.exists())

        text = COMPLETION_AUDIT_DOC.read_text(encoding="utf-8")
        required_phrases = [
            "Current Goal Completion Audit",
            "Evidence Status",
            "five-agent clinical evidence pipeline",
            "FHN evidence-protocol sample path",
            "segmentation benchmark infrastructure",
            "benchmark results blocked",
            "README and Chinese README aligned",
            "Deferred Evidence",
            "real FHN data and masks are deferred",
            "python -m unittest discover -v",
            "437 tests",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        self.assertNotIn("real FHN benchmark completed", text)
        self.assertNotIn("metric-ready real benchmark completed", text)

    def test_project_readmes_link_current_goal_completion_audit(self):
        target = "docs/CURRENT_GOAL_COMPLETION_AUDIT_20260605.md"
        for readme_name in ["README.md", "README.zh-CN.md"]:
            with self.subTest(readme_name=readme_name):
                readme = (REPO_ROOT / readme_name).read_text(encoding="utf-8")
                self.assertIn(target, readme)

    def test_fhn_mvp_doc_marks_421_tests_as_historical_snapshot(self):
        self.assertTrue(FHN_MVP_DOC.exists())

        text = FHN_MVP_DOC.read_text(encoding="utf-8")
        self.assertIn("Historical Verification Snapshot", text)
        self.assertIn("421 tests passed", text)
        self.assertIn("CURRENT_GOAL_CLOSURE_SCOPE_20260605.md", text)
        self.assertIn("CURRENT_GOAL_COMPLETION_AUDIT_20260605.md", text)


if __name__ == "__main__":
    unittest.main()
