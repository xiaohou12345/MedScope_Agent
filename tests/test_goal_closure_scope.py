import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCOPE_DOC = REPO_ROOT / "docs" / "CURRENT_GOAL_CLOSURE_SCOPE_20260605.md"


class GoalClosureScopeTest(unittest.TestCase):
    def test_current_goal_scope_defers_real_fhn_data_without_claiming_real_benchmark(self):
        self.assertTrue(SCOPE_DOC.exists())

        text = SCOPE_DOC.read_text(encoding="utf-8")
        self.assertIn("Current Goal Closure Scope", text)
        self.assertIn("real FHN data and masks are deferred", text)
        self.assertIn("not required for this goal", text)
        self.assertIn("421 tests", text)
        self.assertNotIn("real FHN benchmark completed", text)
        self.assertNotIn("metric-ready real benchmark completed", text)

    def test_project_readmes_link_current_goal_scope(self):
        target = "docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md"
        for readme_name in ["README.md", "README.zh-CN.md"]:
            with self.subTest(readme_name=readme_name):
                readme = (REPO_ROOT / readme_name).read_text(encoding="utf-8")
                self.assertIn(target, readme)


if __name__ == "__main__":
    unittest.main()
