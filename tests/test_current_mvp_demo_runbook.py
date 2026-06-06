import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = REPO_ROOT / "docs" / "CURRENT_MVP_DEMO_RUNBOOK_20260605.md"
PROGRESS_SYNC = REPO_ROOT / "docs" / "PROJECT_PROGRESS_SYNC_20260607.zh-CN.md"


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

    def test_project_progress_sync_is_the_current_docs_entrypoint(self):
        self.assertTrue(PROGRESS_SYNC.exists())
        text = PROGRESS_SYNC.read_text(encoding="utf-8")
        self.assertIn("MedScope Agent 项目进度同步", text)
        self.assertIn("推荐下一轮 Goal 顺序", text)
        self.assertIn("已合并 / 删除的冗余文档", text)
        self.assertIn("不要重做 Research Evidence Ingestion v1", text)

        target = "docs/PROJECT_PROGRESS_SYNC_20260607.zh-CN.md"
        for readme_name in ["README.md", "README.zh-CN.md"]:
            with self.subTest(readme_name=readme_name):
                readme = (REPO_ROOT / readme_name).read_text(encoding="utf-8")
                self.assertIn(target, readme)

    def test_readmes_document_lists_are_bilingually_aligned_for_current_closure(self):
        required_targets = [
            "docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md",
            "docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md",
            "docs/CURRENT_GOAL_COMPLETION_AUDIT_20260605.md",
            "docs/CURRENT_MVP_DEMO_RUNBOOK_20260605.md",
        ]

        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        see_list = readme.split("See:", 1)[1].split("## Repository Layout", 1)[0]
        zh_readme = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        zh_see_list = zh_readme.split("详细说明：", 1)[1].split("## 目录结构", 1)[0]

        for target in required_targets:
            with self.subTest(target=target, readme="README.md"):
                self.assertIn(target, see_list)
            with self.subTest(target=target, readme="README.zh-CN.md"):
                self.assertIn(target, zh_see_list)

    def test_readmes_document_public_safe_qa_route_as_current_api(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        api_routes = readme.split("Other useful routes:", 1)[1].split("## Useful Demos", 1)[0]
        self.assertIn("GET /v1/readiness", api_routes)
        self.assertIn("POST /v1/demo/public-safe/qa", api_routes)
        self.assertNotIn("Expand public-safe fixtures", readme)
        public_safe_section = readme.split("Public-safe MVP suite for fresh clones:", 1)[1].split(
            "No-mask visual pipeline:",
            1,
        )[0]
        self.assertIn("does not prove lesion detection quality", public_safe_section)

        zh_readme = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        zh_api_routes = zh_readme.split("常用接口：", 1)[1].split("## 常用 Demo", 1)[0]
        self.assertIn("GET /v1/readiness", zh_api_routes)
        self.assertIn("POST /v1/demo/public-safe/qa", zh_api_routes)
        self.assertNotIn("把公开安全 fixture 扩展成", zh_readme)
        zh_public_safe_section = zh_readme.split("fresh clone 可用的公开安全 MVP suite：", 1)[1].split(
            "无 mask 视觉流水线：",
            1,
        )[0]
        self.assertIn("不证明病灶检测质量", zh_public_safe_section)

    def test_readmes_document_benchmark_results_do_not_update_diagnosis_or_skills(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        current_review = readme.split("## Current Review", 1)[1].split("## Safety and Privacy", 1)[0]
        self.assertIn(
            "Benchmark results do not update clinical diagnosis or formal skills",
            current_review,
        )

        zh_readme = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        zh_current_review = zh_readme.split("## 项目 Review", 1)[1].split("## 医疗安全和隐私", 1)[0]
        self.assertIn(
            "benchmark 结果不会更新临床诊断或正式 skill",
            zh_current_review,
        )

    def test_readmes_use_current_closure_as_handoff_baseline(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        next_steps = readme.split("Recommended next engineering steps:", 1)[1].split(
            "## Safety and Privacy",
            1,
        )[0]
        self.assertIn("Use the current goal closure scope and completion audit", next_steps)
        self.assertIn("handoff baseline", next_steps)
        self.assertNotIn("Close the current MVP goal", next_steps)

        zh_readme = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        zh_next_steps = zh_readme.split("建议下一步：", 1)[1].split("## 医疗安全和隐私", 1)[0]
        self.assertIn("把 current goal closure scope 和 completion audit", zh_next_steps)
        self.assertIn("交接基线", zh_next_steps)
        self.assertNotIn("先把当前 MVP goal 收敛", zh_next_steps)

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
