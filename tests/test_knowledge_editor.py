import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from knowledge_editor.backend import (
    dispatch_knowledge_editor_api_request,
    dispatch_knowledge_editor_static_request,
)


class KnowledgeEditorTest(unittest.TestCase):
    def test_static_editor_page_is_served_from_own_route(self):
        status, body, content_type = dispatch_knowledge_editor_static_request("/knowledge-editor/")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn("Knowledge / Prompt 可视化编辑器".encode("utf-8"), body)
        self.assertIn(b"/knowledge-editor/app.js", body)

    def test_knowledge_editor_updates_existing_medscope_yaml_without_losing_unknown_fields(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            knowledges_dir = root / "knowledge"
            versions = root / "versions"
            knowledges_dir.mkdir()
            knowledge_path = knowledges_dir / "fhn.yaml"
            knowledge_path.write_text(
                json.dumps(
                    {
                        "disease_name": "股骨头坏死",
                        "knowledge_id": "fhn_v0.1",
                        "version": "0.1",
                        "unknown_runtime_field": {"keep": True},
                        "clinical_features": {
                            "common_symptoms": ["髋痛"],
                            "risk_factors": [],
                        },
                        "required_image_views": ["X 光"],
                        "visual_targets": {"anatomy": ["股骨头"], "lesion_features": []},
                        "vision_agent_tasks": {"segmentation_targets": [], "quantitative_features": []},
                        "report_requirements": {"include": ["诊断倾向"]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status, payload = dispatch_knowledge_editor_api_request(
                method="PUT",
                path="/knowledge-editor/api/knowledge/fhn",
                body=json.dumps(
                    {
                        "author": "张医生",
                        "note": "补充症状",
                        "editor": {
                            "disease_name": "股骨头坏死",
                            "knowledge_id": "fhn_v0.1",
                            "version": "0.1",
                            "evidence_level": "high",
                            "source": "医生审核",
                            "common_symptoms": "髋痛\n跛行",
                            "risk_factors": "激素使用史",
                            "required_image_views": "X 光\nMRI",
                            "anatomy": "股骨头\n髋臼",
                            "lesion_features": "硬化带",
                            "segmentation_targets": "股骨头区域",
                            "quantitative_features": "collapse_ratio",
                            "report_requirements": "诊断倾向\n不确定性说明",
                            "doctor_notes": "早期 X 光阴性不能排除。",
                        },
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                knowledges_dir=knowledges_dir,
                version_root=versions,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["knowledge_key"], "fhn")
            updated = json.loads(knowledge_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["unknown_runtime_field"], {"keep": True})
            self.assertEqual(updated["clinical_features"]["common_symptoms"], ["髋痛", "跛行"])
            self.assertEqual(updated["required_image_views"], ["X 光", "MRI"])
            self.assertEqual(updated["visual_targets"]["anatomy"], ["股骨头", "髋臼"])
            self.assertEqual(updated["report_requirements"]["include"], ["诊断倾向", "不确定性说明"])
            self.assertEqual(updated["quality_control"]["doctor_review_notes"][0]["author"], "张医生")
            self.assertEqual(len(payload["versions"]), 1)

    def test_prompt_editor_creates_updates_and_restores_prompt_md(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompts_dir = root / "prompts"
            versions = root / "versions"
            prompts_dir.mkdir()

            status, created = dispatch_knowledge_editor_api_request(
                method="POST",
                path="/knowledge-editor/api/prompts",
                body=json.dumps(
                    {
                        "prompt_key": "diagnosis_agent_prompt",
                        "markdown": "你是诊断医生 Agent。",
                        "author": "系统",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                prompts_dir=prompts_dir,
                version_root=versions,
            )
            self.assertEqual(status, 200)
            self.assertEqual(created["prompt_key"], "diagnosis_agent_prompt")

            status, updated = dispatch_knowledge_editor_api_request(
                method="PUT",
                path="/knowledge-editor/api/prompts/diagnosis_agent_prompt",
                body=json.dumps(
                    {
                        "markdown": "你是诊断医生 Agent，负责生成辅助诊断报告。",
                        "author": "张医生",
                        "note": "补充职责",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                prompts_dir=prompts_dir,
                version_root=versions,
            )

            self.assertEqual(status, 200)
            prompt_path = prompts_dir / "diagnosis_agent_prompt.md"
            self.assertEqual(prompt_path.read_text(encoding="utf-8"), "你是诊断医生 Agent，负责生成辅助诊断报告。")
            self.assertEqual(len(updated["versions"]), 2)
            first_version_id = updated["versions"][-1]["id"]

            status, restored = dispatch_knowledge_editor_api_request(
                method="POST",
                path=f"/knowledge-editor/api/prompts/diagnosis_agent_prompt/versions/{first_version_id}/restore",
                body=json.dumps({"author": "张医生"}, ensure_ascii=False).encode("utf-8"),
                prompts_dir=prompts_dir,
                version_root=versions,
            )

            self.assertEqual(status, 200)
            self.assertEqual(restored["markdown"], "你是诊断医生 Agent。")
            self.assertEqual(prompt_path.read_text(encoding="utf-8"), "你是诊断医生 Agent。")


if __name__ == "__main__":
    unittest.main()
