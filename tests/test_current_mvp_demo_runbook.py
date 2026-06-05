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
            "python -m scripts.prepare_public_demo_fixture --suite",
            "python -m scripts.end_to_end_demo --suite",
            "python -m scripts.prepare_public_demo_fixture",
            "python -m scripts.check_runtime_environment",
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

    def test_readmes_document_public_safe_qa_route_as_current_api(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        api_routes = readme.split("Other useful routes:", 1)[1].split("## Useful Demos", 1)[0]
        self.assertIn("POST /v1/demo/public-safe/qa", api_routes)
        self.assertNotIn("Expand public-safe fixtures", readme)

        zh_readme = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        zh_api_routes = zh_readme.split("常用接口：", 1)[1].split("## 常用 Demo", 1)[0]
        self.assertIn("POST /v1/demo/public-safe/qa", zh_api_routes)
        self.assertNotIn("把公开安全 fixture 扩展成", zh_readme)

    def test_runbook_recommends_frontend_public_safe_button_for_smoke_demo(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        demonstration_order = text.split("Recommended demonstration order:", 1)[1].split(
            "## What To Say In A Meeting",
            1,
        )[0]
        self.assertIn("运行 Public-safe MVP 样例", demonstration_order)
        self.assertIn("POST /v1/demo/public-safe/qa", demonstration_order)
        self.assertIn("artifact-bound", demonstration_order)
        self.assertNotIn("Load or upload a public-safe image.", demonstration_order)


if __name__ == "__main__":
    unittest.main()
