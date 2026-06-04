import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = REPO_ROOT / "docs" / "CURRENT_MVP_DEMO_RUNBOOK_20260605.md"


class CurrentMvpDemoRunbookTest(unittest.TestCase):
    def test_runbook_documents_public_safe_current_mvp_flow(self):
        self.assertTrue(RUNBOOK.exists())

        text = RUNBOOK.read_text(encoding="utf-8")
        required_phrases = [
            "Current MVP Demo Runbook",
            "python -m scripts.end_to_end_demo --suite",
            "python -m scripts.prepare_public_demo_fixture",
            "upload",
            "automatic skill routing",
            "visual evidence",
            "diagnosis report",
            "evidence bundle",
            "memory audit",
            "follow-up QA",
            "real FHN data and masks are deferred",
            "not a clinical diagnosis",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_readmes_link_current_mvp_demo_runbook(self):
        target = "docs/CURRENT_MVP_DEMO_RUNBOOK_20260605.md"
        for readme_name in ["README.md", "README.zh-CN.md"]:
            with self.subTest(readme_name=readme_name):
                readme = (REPO_ROOT / readme_name).read_text(encoding="utf-8")
                self.assertIn(target, readme)


if __name__ == "__main__":
    unittest.main()
