import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from tools.vision_prompt_generator import VisionPromptGenerator


class RecordingVisionClient:
    def __init__(self, content: str):
        self.content = content
        self.calls = []

    def chat_with_image(self, *, image_path, system_prompt, user_payload, task):
        self.calls.append(
            {
                "image_path": image_path,
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "task": task,
            }
        )
        return self.content


class VisionPromptGeneratorTest(unittest.TestCase):
    def test_generator_converts_model_bbox_json_to_segmentation_prompt(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "cxr.jpg"
            Image.new("RGB", (358, 600), "black").save(image_path)
            client = RecordingVisionClient(
                json.dumps(
                    {
                        "modality": "xray",
                        "body_part": "chest",
                        "suspected_regions": [
                            {
                                "target": "right_lower_lung_opacity",
                                "bbox": [35, 315, 205, 555],
                                "confidence": 0.74,
                                "rationale": "Focal lower-zone opacity.",
                            }
                        ],
                        "limitations": ["single frontal projection only"],
                    }
                )
            )

            result = VisionPromptGenerator(client=client).generate(
                image_path=image_path,
                disease_skill={
                    "disease_name": "肺炎影像筛查",
                    "visual_protocol": {
                        "disease_target": "pneumonia_opacity",
                        "imaging_modalities": ["Xray"],
                        "segmentation_targets": ["lung_opacity"],
                    },
                },
                patient_message="发热咳嗽，帮我看看胸片有没有肺炎影像征象",
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["modality"], "xray")
            self.assertEqual(result["body_part"], "chest")
            self.assertEqual(result["segmentation_prompt"]["boxes"], [[35, 315, 205, 555]])
            self.assertEqual(result["segmentation_prompt"]["source"], "vision_model_bbox")
            self.assertEqual(result["suspected_regions"][0]["target"], "right_lower_lung_opacity")
            self.assertFalse(result["diagnosis_usable"])
            self.assertEqual(client.calls[0]["task"], "vision_prompt_generation")

    def test_generator_preserves_vlm_only_polygon_and_next_imaging_guidance(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "hip.jpg"
            Image.new("RGB", (320, 240), "black").save(image_path)
            client = RecordingVisionClient(
                json.dumps(
                    {
                        "modality": "xray",
                        "body_part": "hip",
                        "needs_next_imaging": True,
                        "required_next_images": [
                            {
                                "modality": "MRI",
                                "region": "双髋",
                                "reason": "X 光只能提供候选征象，早期坏死需要 MRI T1/T2/STIR 评估。",
                            }
                        ],
                        "suspected_regions": [
                            {
                                "target": "sclerotic_band",
                                "bbox": [64, 70, 128, 118],
                                "polygon": [[64, 78], [118, 70], [128, 98], [88, 118]],
                                "confidence": 0.76,
                                "rationale": "股骨头负重区可疑硬化带。",
                                "evidence_text": "左侧股骨头负重区可疑带状密度增高。",
                            }
                        ],
                    }
                )
            )

            result = VisionPromptGenerator(client=client).generate(
                image_path=image_path,
                disease_skill={
                    "disease_name": "股骨头坏死",
                    "visual_protocol": {
                        "disease_target": "femoral_head_necrosis",
                        "required_next_images": [
                            {
                                "modality": "MRI",
                                "region": "双髋",
                                "reason": "指南建议 MRI 评估早期坏死。",
                            }
                        ],
                        "finding_targets": [
                            {
                                "target": "sclerotic_band",
                                "execution_mode": "vlm_only",
                            }
                        ],
                    },
                },
                patient_message="髋痛，上传骨盆正位 X 光",
            )

            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["needs_next_imaging"])
            self.assertEqual(result["required_next_images"][0]["modality"], "MRI")
            self.assertEqual(
                result["suspected_regions"][0]["polygon"],
                [[64, 78], [118, 70], [128, 98], [88, 118]],
            )
            self.assertEqual(
                result["suspected_regions"][0]["evidence_text"],
                "左侧股骨头负重区可疑带状密度增高。",
            )
            schema = client.calls[0]["user_payload"]["required_output_schema"]
            self.assertIn("polygon", schema["suspected_regions"][0])
            self.assertIn("required_next_images", schema)

    def test_generator_passes_skill_finding_targets_to_vision_model(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "hip.jpg"
            Image.new("RGB", (300, 300), "black").save(image_path)
            client = RecordingVisionClient(
                json.dumps(
                    {
                        "modality": "xray",
                        "body_part": "hip",
                        "suspected_regions": [],
                    }
                )
            )

            VisionPromptGenerator(client=client).generate(
                image_path=image_path,
                disease_skill={
                    "disease_name": "股骨头坏死",
                    "visual_protocol": {
                        "disease_target": "femoral_head_necrosis",
                        "finding_targets": [
                            {
                                "target": "sclerotic_band",
                                "display_name": "硬化带",
                                "measurements": ["relative_density_score"],
                            },
                            {
                                "target": "cystic_change",
                                "display_name": "囊性变",
                                "measurements": ["relative_lucency_score"],
                            },
                        ],
                    },
                },
                patient_message="髋关节疼痛，上传 X 光",
            )

            payload = client.calls[0]["user_payload"]
            self.assertEqual(
                [item["target"] for item in payload["requested_finding_targets"]],
                ["sclerotic_band", "cystic_change"],
            )
            self.assertEqual(
                payload["required_output_schema"]["suspected_regions"][0]["target"],
                "one_of_requested_finding_targets",
            )

    def test_generator_rejects_invalid_bbox_without_silent_repair(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "cxr.jpg"
            Image.new("RGB", (358, 600), "black").save(image_path)
            client = RecordingVisionClient(
                json.dumps(
                    {
                        "suspected_regions": [
                            {
                                "target": "opacity",
                                "bbox": [200, 315, 35, 555],
                                "confidence": 0.74,
                            }
                        ]
                    }
                )
            )

            result = VisionPromptGenerator(client=client).generate(
                image_path=image_path,
                disease_skill={"disease_name": "肺炎影像筛查"},
                patient_message="咳嗽发热",
            )

            self.assertEqual(result["status"], "invalid_model_output")
            self.assertEqual(result["segmentation_prompt"]["boxes"], [])
            self.assertIn("Invalid bbox", result["errors"][0])

    def test_generator_keeps_valid_regions_when_one_model_bbox_is_invalid(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "hip.jpg"
            Image.new("RGB", (320, 235), "black").save(image_path)
            client = RecordingVisionClient(
                json.dumps(
                    {
                        "modality": "xray",
                        "body_part": "hip",
                        "suspected_regions": [
                            {
                                "target": "sclerotic_band",
                                "bbox": [65, 75, 110, 115],
                                "confidence": 0.85,
                                "rationale": "Visible band-like sclerosis.",
                            },
                            {
                                "target": "cystic_change",
                                "bbox": [65, 215, 110, 255],
                                "confidence": 0.8,
                                "rationale": "Out-of-bounds candidate.",
                            },
                        ],
                    }
                )
            )

            result = VisionPromptGenerator(client=client).generate(
                image_path=image_path,
                disease_skill={"disease_name": "股骨头坏死"},
                patient_message="髋关节疼痛",
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["segmentation_prompt"]["boxes"], [[65, 75, 110, 115]])
            self.assertEqual(result["suspected_regions"][0]["target"], "sclerotic_band")
            self.assertEqual(len(result["rejected_regions"]), 1)
            self.assertIn("Invalid bbox", result["rejected_regions"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
