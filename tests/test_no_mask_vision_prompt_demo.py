import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from scripts.no_mask_vision_prompt_demo import (
    default_pneumonia_opacity_skill,
    run_no_mask_vision_prompt_demo,
    _write_bbox_overlay,
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


class MultiFindingVisionClient:
    def chat_with_image(self, *, image_path, system_prompt, user_payload, task):
        return json.dumps(
            {
                "modality": "xray",
                "body_part": "hip",
                "suspected_regions": [
                    {
                        "target": "sclerotic_band",
                        "bbox": [20, 40, 80, 90],
                        "polygon": [[28, 50], [68, 50], [72, 78], [32, 82]],
                        "confidence": 0.72,
                        "rationale": "Band-like sclerosis candidate.",
                    },
                    {
                        "target": "cystic_change",
                        "bbox": [92, 42, 142, 94],
                        "polygon": [[104, 56], [130, 56], [134, 82], [106, 84]],
                        "confidence": 0.64,
                        "rationale": "Lucent cystic candidate.",
                    },
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

    def test_demo_writes_per_target_overlay_paths(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.jpg"
            output_dir = workdir / "out"
            Image.new("RGB", (180, 140), "black").save(image_path)

            result = run_no_mask_vision_prompt_demo(
                image_path=image_path,
                output_dir=output_dir,
                patient_message="髋痛，上传骨盆正位 X 光",
                client=MultiFindingVisionClient(),
            )

            target_overlays = result["target_overlay_paths"]
            self.assertEqual(
                [item["target"] for item in target_overlays],
                ["sclerotic_band", "cystic_change"],
            )
            for item in target_overlays:
                self.assertEqual(item["region_count"], 1)
                self.assertTrue(Path(item["overlay_path"]).exists())
            summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["target_overlay_paths"], target_overlays)

    def test_bbox_overlay_keeps_candidate_region_visible(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.jpg"
            output_path = workdir / "overlay.png"
            Image.new("RGB", (180, 140), (80, 80, 80)).save(image_path)

            _write_bbox_overlay(
                image_path=image_path,
                output_path=output_path,
                regions=[
                    {
                        "bbox": [40, 50, 92, 104],
                        "polygon": [[52, 62], [76, 62], [84, 86], [58, 94]],
                    },
                    {
                        "bbox": [62, 58, 116, 112],
                        "polygon": [[74, 70], [98, 70], [106, 94], [80, 102]],
                    },
                ],
            )

            overlay = Image.open(output_path).convert("RGB")
            red_pixels_inside_first_box = 0
            total_inside_first_box = 0
            for x in range(40, 92):
                for y in range(50, 104):
                    red, green, blue = overlay.getpixel((x, y))
                    if red > 220 and green < 60 and blue < 60:
                        red_pixels_inside_first_box += 1
                    total_inside_first_box += 1

            self.assertLess(red_pixels_inside_first_box / total_inside_first_box, 0.08)


if __name__ == "__main__":
    unittest.main()
