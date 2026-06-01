import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.image_prompt_skill_baseline import (
    IMAGE_BASELINE_LEVELS,
    run_image_prompt_skill_baseline,
)


class RecordingImageBaselineClient:
    def __init__(self):
        self.calls = []

    def chat_with_image(self, *, image_path, system_prompt, user_payload, task):
        self.calls.append(
            {
                "image_path": str(image_path),
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "task": task,
            }
        )
        level = user_payload["baseline_level"]
        return json.dumps(
            {
                "诊断倾向": f"{level} 输出",
                "影像依据": [f"{level} image observation"],
                "分期判断": "不能仅凭当前图像完成最终诊断",
                "不确定性说明": ["baseline output for comparison only"],
                "建议进一步检查": ["按 skill 要求补充检查"],
                "治疗建议": ["临床复核"],
            },
            ensure_ascii=False,
        )


class ImagePromptSkillBaselineTest(unittest.TestCase):
    def test_image_prompt_skill_baseline_runs_three_levels_with_same_image_and_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_path = root / "hip.png"
            Image.new("RGB", (24, 18), "black").save(image_path)
            client = RecordingImageBaselineClient()
            skill = {
                "disease_name": "股骨头坏死",
                "skill_id": "femoral_head_necrosis_test",
                "visual_protocol": {
                    "disease_target": "femoral_head_necrosis",
                    "finding_targets": [
                        {
                            "target": "sclerotic_band",
                            "display_name": "硬化带",
                            "execution_mode": "vlm_plus_segmenter",
                        }
                    ],
                    "required_next_images": [
                        {
                            "modality": "MRI",
                            "region": "双髋关节",
                            "reason": "X 光不足以排除早期病变。",
                        }
                    ],
                },
            }

            result = run_image_prompt_skill_baseline(
                image_path=image_path,
                patient_prompt="右髋疼痛三个月，请判断是否股骨头坏死",
                disease_skill=skill,
                output_dir=root / "out",
                client=client,
            )

            self.assertEqual(result["schema_version"], "image_prompt_skill_baseline.v1")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                [item["level"] for item in result["baseline_results"]],
                ["simple_prompt", "workflow_prompt", "fewshot_prompt"],
            )
            self.assertEqual(len(client.calls), 3)
            self.assertTrue(all(call["image_path"] == str(image_path) for call in client.calls))
            self.assertTrue(all(call["task"] == "image_prompt_skill_baseline" for call in client.calls))
            self.assertTrue(
                all(
                    call["user_payload"]["patient_prompt"] == "右髋疼痛三个月，请判断是否股骨头坏死"
                    for call in client.calls
                )
            )
            self.assertTrue(
                all(call["user_payload"]["skill"]["skill_id"] == "femoral_head_necrosis_test" for call in client.calls)
            )
            self.assertEqual(result["metrics_by_level"]["simple_prompt"]["json_valid_count"], 1)
            self.assertTrue(Path(result["output_paths"]["json_path"]).exists())
            self.assertTrue(Path(result["output_paths"]["markdown_path"]).exists())

    def test_baseline_level_order_is_simple_workflow_fewshot(self):
        self.assertEqual(
            [level["level"] for level in IMAGE_BASELINE_LEVELS],
            ["simple_prompt", "workflow_prompt", "fewshot_prompt"],
        )


if __name__ == "__main__":
    unittest.main()
