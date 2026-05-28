import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from scripts.no_mask_vision_prompt_demo import (
    default_pneumonia_opacity_skill,
    run_no_mask_vision_prompt_demo,
)


class DemoVisionClient:
    def chat_with_image(self, *, image_path, system_prompt, user_payload, task):
        return json.dumps(
            {
                "modality": "xray",
                "body_part": "chest",
                "suspected_regions": [
                    {
                        "target": "right_lower_lung_opacity",
                        "bbox": [20, 60, 120, 180],
                        "confidence": 0.72,
                        "rationale": "Focal opacity candidate.",
                    }
                ],
                "limitations": ["candidate localization only"],
            }
        )


class NoMaskVisionPromptDemoTest(unittest.TestCase):
    def test_default_pneumonia_skill_is_loaded_from_formal_skill_file(self):
        skill = default_pneumonia_opacity_skill()

        self.assertEqual(skill["skill_id"], "pneumonia_chest_xray_v0.1")
        self.assertEqual(skill["skill_type"], "guideline_based")
        self.assertEqual(skill["visual_protocol"]["disease_target"], "community_acquired_pneumonia")
        self.assertIn("lung_opacity", skill["visual_protocol"]["segmentation_targets"])

    def test_demo_writes_prompt_json_and_bbox_overlay(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "cxr.jpg"
            output_dir = workdir / "out"
            Image.new("RGB", (160, 220), "black").save(image_path)

            result = run_no_mask_vision_prompt_demo(
                image_path=image_path,
                output_dir=output_dir,
                patient_message="咳嗽发热，胸片疑似肺炎",
                client=DemoVisionClient(),
            )

            self.assertEqual(result["status"], "ok")
            self.assertTrue(Path(result["prompt_result_path"]).exists())
            self.assertTrue(Path(result["bbox_overlay_path"]).exists())
            prompt_result = json.loads(Path(result["prompt_result_path"]).read_text(encoding="utf-8"))
            self.assertEqual(prompt_result["segmentation_prompt"]["boxes"], [[20, 60, 120, 180]])
            self.assertFalse(prompt_result["diagnosis_usable"])


if __name__ == "__main__":
    unittest.main()
