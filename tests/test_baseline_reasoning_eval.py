import json
import tempfile
import unittest
from pathlib import Path

from llm.model_client import ChatResponse, RecordingModelClient
from scripts.baseline_reasoning_eval import (
    BASELINE_LEVELS,
    build_baseline_reasoning_eval,
)


class BaselineReasoningEvalTest(unittest.TestCase):
    def test_eval_defines_three_baseline_levels(self) -> None:
        self.assertEqual(
            [level["level"] for level in BASELINE_LEVELS],
            ["simple_prompt", "workflow_prompt", "fewshot_prompt"],
        )
        self.assertLess(
            BASELINE_LEVELS[0]["constraint_level"],
            BASELINE_LEVELS[1]["constraint_level"],
        )
        self.assertLess(
            BASELINE_LEVELS[1]["constraint_level"],
            BASELINE_LEVELS[2]["constraint_level"],
        )

    def test_eval_runs_three_prompt_baselines_and_writes_reports(self) -> None:
        responses = [
            {
                "诊断倾向": "可以排除早期股骨头坏死",
                "影像依据": ["X 光未见明显异常"],
                "分期判断": "无病",
                "不确定性说明": [],
                "建议进一步检查": [],
                "治疗建议": ["观察"],
            },
            {
                "诊断倾向": "现有 X 光证据不足",
                "影像依据": ["当前可见候选硬化带，但早期病变需要 MRI"],
                "分期判断": "不能仅凭 X 光排除早期病变",
                "不确定性说明": ["缺少 MRI T1/T2/STIR"],
                "建议进一步检查": ["双髋 MRI T1/T2/STIR"],
                "治疗建议": ["骨科复核"],
            },
            {
                "诊断倾向": "现有证据提示候选异常但不足以确诊",
                "影像依据": ["使用了诊断可用的候选硬化带证据"],
                "分期判断": "不能把缺失 MRI 证据解释为阴性",
                "不确定性说明": ["VLM-only 或 excluded finding 不能作为独立依据"],
                "建议进一步检查": ["双髋 MRI T1/T2/STIR"],
                "治疗建议": ["结合临床复核"],
            },
        ]
        client = SequencedModelClient(
            [
                ChatResponse(
                    content=json.dumps(response, ensure_ascii=False),
                    model="fake",
                    route="test",
                )
                for response in responses
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = build_baseline_reasoning_eval(
                output_dir=root / "out",
                model_client=client,
            )

            self.assertEqual(result["schema_version"], "baseline_reasoning_eval.v1")
            self.assertEqual(result["baseline_count"], 3)
            self.assertEqual(
                [item["level"] for item in result["baseline_results"]],
                ["simple_prompt", "workflow_prompt", "fewshot_prompt"],
            )
            self.assertEqual(result["metrics_by_level"]["simple_prompt"]["json_valid_count"], 1)
            self.assertGreater(
                result["metrics_by_level"]["simple_prompt"]["missing_as_negative_violation_count"],
                0,
            )
            self.assertEqual(
                result["metrics_by_level"]["fewshot_prompt"]["missing_as_negative_violation_count"],
                0,
            )
            self.assertEqual(
                result["metrics_by_level"]["fewshot_prompt"]["required_next_image_mentioned_count"],
                1,
            )
            self.assertLess(
                result["metrics_by_level"]["simple_prompt"]["safety_pass_rate"],
                result["metrics_by_level"]["fewshot_prompt"]["safety_pass_rate"],
            )
            self.assertTrue(Path(result["output_paths"]["json_path"]).exists())
            markdown = Path(result["output_paths"]["markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("simple_prompt", markdown)
            self.assertIn("fewshot_prompt", markdown)
            self.assertEqual(len(client.calls), 3)
            self.assertTrue(all(call["task"] == "baseline_reasoning_eval" for call in client.calls))

    def test_eval_can_run_without_network_using_deterministic_stub(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = build_baseline_reasoning_eval(output_dir=Path(tmpdir) / "out")

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["baseline_count"], 3)
            self.assertEqual(result["runtime_safety"]["diagnosis_report_updated"], False)


class SequencedModelClient:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, messages, task):
        self.calls.append({"messages": messages, "task": task})
        if not self.responses:
            raise AssertionError("No response left")
        return self.responses.pop(0)


if __name__ == "__main__":
    unittest.main()
