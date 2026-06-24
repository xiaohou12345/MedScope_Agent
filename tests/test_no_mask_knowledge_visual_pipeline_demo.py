import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from scripts.no_mask_knowledge_visual_pipeline_demo import run_no_mask_knowledge_visual_pipeline_demo


class SequencedVisionClient:
    def __init__(self):
        self.calls = []

    def chat_with_image(self, *, image_path, system_prompt, user_payload, task):
        self.calls.append(
            {
                "image_path": image_path,
                "user_payload": user_payload,
                "task": task,
            }
        )
        targets = [
            item["target"]
            for item in user_payload.get("requested_finding_targets") or []
        ]
        if targets == ["femoral_head"]:
            return json.dumps(
                {
                    "modality": "xray",
                    "body_part": "hip",
                    "suspected_regions": [
                        {
                            "target": "femoral_head",
                            "bbox": [1, 2, 8, 9],
                            "confidence": 0.91,
                            "rationale": "right femoral head reference",
                        }
                    ],
                }
            )
        return json.dumps(
            {
                "modality": "xray",
                "body_part": "hip",
                "suspected_regions": [
                    {
                        "target": "sclerotic_band",
                        "bbox": [1, 2, 8, 9],
                        "confidence": 0.81,
                        "rationale": "candidate sclerosis",
                    },
                    {
                        "target": "cystic_change",
                        "bbox": [2, 3, 7, 8],
                        "confidence": 0.72,
                        "rationale": "candidate cystic lucency",
                    }
                ],
            }
        )


class BilateralVisionClient:
    def __init__(self):
        self.calls = []

    def chat_with_image(self, *, image_path, system_prompt, user_payload, task):
        self.calls.append(
            {
                "image_path": image_path,
                "user_payload": user_payload,
                "task": task,
            }
        )
        targets = [
            item["target"]
            for item in user_payload.get("requested_finding_targets") or []
        ]
        if targets == ["femoral_head"]:
            return json.dumps(
                {
                    "modality": "xray",
                    "body_part": "hip",
                    "suspected_regions": [
                        {
                            "target": "left_femoral_head",
                            "display_name": "左侧股骨头",
                            "bbox": [0, 0, 8, 10],
                            "confidence": 0.91,
                            "rationale": "left reference",
                        },
                        {
                            "target": "right_femoral_head",
                            "display_name": "右侧股骨头",
                            "bbox": [10, 0, 20, 10],
                            "confidence": 0.91,
                            "rationale": "right reference",
                        },
                    ],
                }
            )
        return json.dumps(
            {
                "modality": "xray",
                "body_part": "hip",
                "suspected_regions": [
                    {
                        "target": "sclerotic_band",
                        "bbox": [12, 2, 18, 8],
                        "confidence": 0.81,
                        "rationale": "right-side sclerosis",
                    }
                ],
            }
        )


class SingleLeftFindingVisionClient:
    def __init__(self):
        self.calls = []

    def chat_with_image(self, *, image_path, system_prompt, user_payload, task):
        self.calls.append(
            {
                "image_path": image_path,
                "user_payload": user_payload,
                "task": task,
            }
        )
        return json.dumps(
            {
                "modality": "xray",
                "body_part": "hip",
                "needs_next_imaging": True,
                "required_next_images": [
                    {
                        "modality": "MRI",
                        "region": "双髋",
                        "reason": "X 光候选征象不能排除早期股骨头坏死。",
                    }
                ],
                "suspected_regions": [
                    {
                        "target": "sclerotic_band",
                        "bbox": [1, 2, 8, 9],
                        "polygon": [[1, 2], [8, 2], [8, 9], [1, 9]],
                        "confidence": 0.81,
                        "rationale": "image-left sclerosis candidate",
                        "evidence_text": "图像左侧股骨头可疑硬化带。",
                    }
                ],
            }
        )


class MixedExecutionModeVisionClient:
    def __init__(self):
        self.calls = []

    def chat_with_image(self, *, image_path, system_prompt, user_payload, task):
        self.calls.append(
            {
                "image_path": image_path,
                "user_payload": user_payload,
                "task": task,
            }
        )
        targets = [
            item["target"]
            for item in user_payload.get("requested_finding_targets") or []
        ]
        regions = []
        if "sclerotic_band" in targets:
            regions.append(
                {
                    "target": "sclerotic_band",
                    "bbox": [2, 2, 8, 8],
                    "confidence": 0.82,
                    "rationale": "band-like density increase candidate",
                }
            )
        if "trabecular_blurring" in targets:
            regions.append(
                {
                    "target": "trabecular_blurring",
                    "bbox": [10, 2, 18, 8],
                    "confidence": 0.67,
                    "rationale": "texture is visually blurred but not reliably maskable",
                }
            )
        return json.dumps(
            {
                "modality": "xray",
                "body_part": "hip",
                "suspected_regions": regions,
                "limitations": ["single frontal radiograph only"],
            }
        )


class FakeSegmentationTool:
    def __init__(self):
        self.calls = []

    def segment_with_model(self, image_path, prompt, mask_path, overlay_path):
        self.calls.append(
            {
                "image_path": image_path,
                "prompt": prompt,
                "mask_path": mask_path,
                "overlay_path": overlay_path,
            }
        )
        image = Image.open(image_path)
        mask = Image.new("L", image.size, 0)
        pixels = mask.load()
        for x in range(2, 6):
            for y in range(3, 8):
                pixels[x, y] = 255
        mask.save(mask_path)
        image.convert("RGB").save(overlay_path)
        return {
            "image_outputs": {
                "original_image_path": str(image_path),
                "mask_path": str(mask_path),
                "overlay_path": str(overlay_path),
            },
            "features": {"segmentation_quality": "fake_medsam2"},
            "mask_shape": {"width": image.size[0], "height": image.size[1], "depth": 1},
            "segmentation_source": "medsam2",
        }


class PromptBoxSegmentationTool:
    def __init__(self):
        self.calls = []

    def segment_with_model(self, image_path, prompt, mask_path, overlay_path):
        self.calls.append(
            {
                "image_path": image_path,
                "prompt": prompt,
                "mask_path": mask_path,
                "overlay_path": overlay_path,
            }
        )
        image = Image.open(image_path)
        mask = Image.new("L", image.size, 0)
        pixels = mask.load()
        x1, y1, x2, y2 = [int(value) for value in prompt["boxes"][0]]
        for x in range(max(x1, 0), min(x2, image.size[0])):
            for y in range(max(y1, 0), min(y2, image.size[1])):
                pixels[x, y] = 255
        mask.save(mask_path)
        image.convert("RGB").save(overlay_path)
        return {
            "image_outputs": {
                "original_image_path": str(image_path),
                "mask_path": str(mask_path),
                "overlay_path": str(overlay_path),
            },
            "features": {"segmentation_quality": "fake_medsam2"},
            "mask_shape": {"width": image.size[0], "height": image.size[1], "depth": 1},
            "segmentation_source": "medsam2",
        }


class OutsidePromptSegmentationTool:
    def __init__(self):
        self.calls = []

    def segment_with_model(self, image_path, prompt, mask_path, overlay_path):
        self.calls.append(
            {
                "image_path": image_path,
                "prompt": prompt,
                "mask_path": mask_path,
                "overlay_path": overlay_path,
            }
        )
        image = Image.open(image_path)
        mask = Image.new("L", image.size, 0)
        pixels = mask.load()
        for x in range(12, 18):
            for y in range(1, 5):
                pixels[x, y] = 255
        mask.save(mask_path)
        image.convert("RGB").save(overlay_path)
        return {
            "image_outputs": {
                "original_image_path": str(image_path),
                "mask_path": str(mask_path),
                "overlay_path": str(overlay_path),
            },
            "features": {"segmentation_quality": "fake_medsam2"},
            "mask_shape": {"width": image.size[0], "height": image.size[1], "depth": 1},
            "segmentation_source": "medsam2",
        }


class FailingSegmentationTool:
    def segment_with_model(self, image_path, prompt, mask_path, overlay_path):
        raise RuntimeError("segmentation backend missing checkpoint")


class NoMaskKnowledgeVisualPipelineDemoTest(unittest.TestCase):
    def test_pipeline_uses_knowledge_anatomy_reference_before_finding_segmentation(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.png"
            Image.new("RGB", (10, 10), "black").save(image_path)
            knowledge = {
                "disease_name": "股骨头坏死",
                "visual_protocol": {
                    "disease_target": "femoral_head_necrosis",
                    "anatomy_reference": {
                        "target": "femoral_head",
                        "display_name": "股骨头解剖区域",
                        "description": "right femoral head reference",
                        "required_modalities": ["X-ray"],
                        "normalizes": ["area_ratio_in_femoral_head"],
                    },
                    "finding_targets": [
                        {
                            "target": "sclerotic_band",
                            "display_name": "硬化带",
                            "required_modalities": ["X-ray"],
                            "measurements": ["area_ratio_in_femoral_head"],
                        },
                        {
                            "target": "cystic_change",
                            "display_name": "囊性变",
                            "required_modalities": ["X-ray"],
                            "measurements": ["area_ratio_in_femoral_head"],
                        }
                    ],
                },
            }
            client = SequencedVisionClient()
            segmentation_tool = FakeSegmentationTool()

            result = run_no_mask_knowledge_visual_pipeline_demo(
                image_path=image_path,
                output_dir=workdir / "out",
                disease_knowledge=knowledge,
                patient_message="髋关节疼痛，上传髋关节X光",
                client=client,
                segmentation_tool=segmentation_tool,
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(len(segmentation_tool.calls), 3)
            self.assertEqual(result["anatomy_reference"]["target"], "femoral_head")
            self.assertTrue(Path(result["anatomy_reference"]["mask_path"]).exists())
            finding_summary = json.loads(
                Path(result["finding_segmentation_summary_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(len(finding_summary["findings"]), 2)
            self.assertEqual(
                finding_summary["findings"][0]["measurements"]["area_ratio_in_anatomy"],
                1.0,
            )
            self.assertEqual(
                finding_summary["findings"][0]["regions"][0]["anatomical_zone"],
                "femoral_head",
            )
            bundle = result["visual_evidence_bundle"]
            self.assertEqual(bundle["disease_target"], "femoral_head_necrosis")
            self.assertEqual(bundle["image_context"]["modality"], "xray")
            self.assertEqual(bundle["image_context"]["body_part"], "hip")
            self.assertEqual(
                bundle["present_findings"],
                ["sclerotic_band", "cystic_change"],
            )
            self.assertEqual(len(bundle["findings"]), 2)
            self.assertEqual(
                bundle["findings"][0]["measurements"]["area_ratio_in_anatomy"],
                1.0,
            )
            self.assertGreater(bundle["numeric_evidence"]["total_area_px"], 0)
            self.assertEqual(bundle["numeric_evidence"]["finding_count"], 2)
            self.assertEqual(bundle["numeric_evidence"]["independent_finding_count"], 1)
            self.assertEqual(bundle["numeric_evidence"]["non_independent_finding_count"], 1)
            self.assertTrue(bundle["text_evidence"])
            self.assertEqual(
                bundle["diagnosis_payload"]["visual_evidence"]["findings"][1]["target"],
                "cystic_change",
            )
            facts = bundle["structured_visual_facts"]
            self.assertEqual(len(facts), 2)
            self.assertEqual(facts[0]["finding_id"], "finding_1_sclerotic_band")
            self.assertEqual(facts[0]["target"], "sclerotic_band")
            self.assertEqual(facts[0]["display_name"], "硬化带")
            self.assertTrue(facts[0]["diagnosis_usable"])
            self.assertTrue(facts[0]["independent_evidence"])
            self.assertEqual(facts[0]["alignment_status"], "aligned")
            self.assertEqual(facts[0]["area_px"], 20)
            self.assertEqual(facts[0]["area_ratio_in_anatomy"], 1.0)
            self.assertEqual(facts[1]["target"], "cystic_change")
            self.assertFalse(facts[1]["independent_evidence"])
            self.assertEqual(
                facts[1]["non_independent_reason"],
                "overlaps_existing_finding",
            )

    def test_pipeline_passes_multiple_anatomy_masks_for_same_side_matching(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.png"
            Image.new("RGB", (20, 10), "black").save(image_path)
            knowledge = {
                "disease_name": "股骨头坏死",
                "visual_protocol": {
                    "disease_target": "femoral_head_necrosis",
                    "anatomy_reference": {
                        "target": "femoral_head",
                        "display_name": "股骨头解剖区域",
                        "description": "bilateral femoral head reference",
                        "required_modalities": ["X-ray"],
                        "normalizes": ["area_ratio_in_femoral_head"],
                    },
                    "finding_targets": [
                        {
                            "target": "sclerotic_band",
                            "display_name": "硬化带",
                            "required_modalities": ["X-ray"],
                            "measurements": ["area_ratio_in_femoral_head"],
                        }
                    ],
                },
            }

            result = run_no_mask_knowledge_visual_pipeline_demo(
                image_path=image_path,
                output_dir=workdir / "out",
                disease_knowledge=knowledge,
                patient_message="右髋疼痛，上传髋关节X光",
                client=BilateralVisionClient(),
                segmentation_tool=PromptBoxSegmentationTool(),
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["anatomy_reference"]["candidates"]), 2)
            finding = result["visual_evidence_bundle"]["findings"][0]
            self.assertEqual(finding["measurements"]["anatomy_name"], "right_femoral_head")
            self.assertEqual(finding["measurements"]["overlap_anatomy_px"], 36)
            self.assertEqual(finding["measurements"]["area_ratio_in_anatomy"], 0.36)

    def test_pipeline_propagates_overlap_quality_warnings_to_evidence_bundle(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.png"
            Image.new("RGB", (20, 10), "black").save(image_path)
            knowledge = {
                "disease_name": "股骨头坏死",
                "visual_protocol": {
                    "disease_target": "femoral_head_necrosis",
                    "finding_targets": [
                        {
                            "target": "sclerotic_band",
                            "display_name": "硬化带",
                            "required_modalities": ["X-ray"],
                            "measurements": ["area_px"],
                        },
                        {
                            "target": "collapse",
                            "display_name": "股骨头塌陷",
                            "required_modalities": ["X-ray"],
                            "measurements": ["area_px"],
                        },
                    ],
                },
            }

            result = run_no_mask_knowledge_visual_pipeline_demo(
                image_path=image_path,
                output_dir=workdir / "out",
                disease_knowledge=knowledge,
                patient_message="右髋疼痛，上传髋关节X光",
                client=SequencedVisionClient(),
                segmentation_tool=FakeSegmentationTool(),
            )

            bundle = result["visual_evidence_bundle"]
            self.assertEqual(result["status"], "ok")
            self.assertTrue(bundle["quality_warnings"])
            self.assertEqual(
                bundle["quality_warnings"][0]["code"],
                "overlapping_candidate_findings",
            )
            self.assertEqual(bundle["numeric_evidence"]["finding_count"], 2)
            self.assertEqual(bundle["numeric_evidence"]["independent_finding_count"], 1)
            self.assertFalse(bundle["findings"][1]["independent_evidence"])

    def test_pipeline_excludes_misaligned_masks_from_present_findings(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.png"
            Image.new("RGB", (20, 10), "black").save(image_path)
            knowledge = {
                "disease_name": "股骨头坏死",
                "visual_protocol": {
                    "disease_target": "femoral_head_necrosis",
                    "finding_targets": [
                        {
                            "target": "sclerotic_band",
                            "display_name": "硬化带",
                            "required_modalities": ["X-ray"],
                            "measurements": ["area_px"],
                        }
                    ],
                },
            }

            result = run_no_mask_knowledge_visual_pipeline_demo(
                image_path=image_path,
                output_dir=workdir / "out",
                disease_knowledge=knowledge,
                patient_message="右髋疼痛，上传髋关节X光",
                client=SingleLeftFindingVisionClient(),
                segmentation_tool=OutsidePromptSegmentationTool(),
            )

            bundle = result["visual_evidence_bundle"]
            self.assertEqual(result["status"], "ok")
            self.assertEqual(bundle["present_findings"], [])
            self.assertEqual(bundle["visual_output_mode"], "vlm_plus_segmenter")
            self.assertEqual(bundle["segmentation_status"], "failed_qc")
            self.assertEqual(bundle["fallback_mode"], "vlm_only")
            self.assertFalse(bundle["segmentation_display_allowed"])
            self.assertEqual(
                bundle["quality_warnings"][0]["code"],
                "box_mask_misalignment",
            )
            self.assertFalse(bundle["findings"][0]["diagnosis_usable"])
            self.assertEqual(bundle["numeric_evidence"]["diagnosis_usable_finding_count"], 0)
            self.assertEqual(bundle["numeric_evidence"]["diagnosis_unusable_finding_count"], 1)
            self.assertEqual(bundle["numeric_evidence"]["independent_finding_count"], 0)

    def test_pipeline_falls_back_to_vlm_only_when_segmenter_errors(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.png"
            Image.new("RGB", (20, 10), "black").save(image_path)
            knowledge = {
                "disease_name": "股骨头坏死",
                "visual_protocol": {
                    "disease_target": "femoral_head_necrosis",
                    "finding_targets": [
                        {
                            "target": "sclerotic_band",
                            "display_name": "硬化带",
                            "required_modalities": ["X-ray"],
                            "execution_mode": "vlm_plus_segmenter",
                            "segmentation_mode": "candidate_mask",
                            "diagnosis_usable_level": "candidate_support",
                        }
                    ],
                },
            }

            result = run_no_mask_knowledge_visual_pipeline_demo(
                image_path=image_path,
                output_dir=workdir / "out",
                disease_knowledge=knowledge,
                patient_message="右髋疼痛，上传髋关节X光",
                client=SingleLeftFindingVisionClient(),
                segmentation_tool=FailingSegmentationTool(),
            )

            bundle = result["visual_evidence_bundle"]
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["finding_segmentation_status"], "segmentation_error")
            self.assertEqual(bundle["visual_output_mode"], "vlm_plus_segmenter")
            self.assertEqual(bundle["segmentation_status"], "not_ready")
            self.assertEqual(bundle["fallback_mode"], "vlm_only")
            self.assertFalse(bundle["segmentation_display_allowed"])
            self.assertEqual(bundle["present_findings"], [])
            self.assertEqual(bundle["findings"][0]["target"], "sclerotic_band")
            self.assertEqual(bundle["findings"][0]["polygon"], [[1, 2], [8, 2], [8, 9], [1, 9]])
            self.assertEqual(bundle["findings"][0]["evidence_text"], "图像左侧股骨头可疑硬化带。")
            self.assertTrue(bundle["needs_next_imaging"])
            self.assertEqual(bundle["required_next_images"][0]["modality"], "MRI")
            self.assertFalse(bundle["findings"][0]["diagnosis_usable"])

    def test_pipeline_keeps_vlm_only_findings_without_calling_segmentation(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.png"
            Image.new("RGB", (20, 10), "black").save(image_path)
            knowledge = {
                "disease_name": "股骨头坏死",
                "visual_protocol": {
                    "disease_target": "femoral_head_necrosis",
                    "finding_targets": [
                        {
                            "target": "sclerotic_band",
                            "display_name": "硬化带",
                            "required_modalities": ["X-ray"],
                            "execution_mode": "vlm_plus_segmenter",
                            "segmentation_mode": "candidate_mask",
                            "diagnosis_usable_level": "candidate_support",
                            "measurements": ["area_px"],
                        },
                        {
                            "target": "trabecular_blurring",
                            "display_name": "骨小梁模糊",
                            "required_modalities": ["X-ray"],
                            "execution_mode": "vlm_only",
                            "segmentation_mode": "none",
                            "diagnosis_usable_level": "observation_only",
                        },
                    ],
                },
            }
            client = MixedExecutionModeVisionClient()
            segmentation_tool = PromptBoxSegmentationTool()

            result = run_no_mask_knowledge_visual_pipeline_demo(
                image_path=image_path,
                output_dir=workdir / "out",
                disease_knowledge=knowledge,
                patient_message="右髋疼痛，上传髋关节X光",
                client=client,
                segmentation_tool=segmentation_tool,
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(len(segmentation_tool.calls), 1)
            self.assertEqual(
                segmentation_tool.calls[0]["prompt"]["boxes"],
                [[2, 2, 8, 8]],
            )
            bundle = result["visual_evidence_bundle"]
            self.assertEqual(bundle["visual_output_mode"], "vlm_plus_segmenter")
            self.assertEqual(bundle["segmentation_status"], "candidate_passed_qc")
            self.assertIsNone(bundle["fallback_mode"])
            self.assertTrue(bundle["segmentation_display_allowed"])
            self.assertIn("vlm_annotation_path", bundle["image_outputs"])
            target_overlays = bundle["image_outputs"]["target_overlay_paths"]
            self.assertEqual(
                [item["target"] for item in target_overlays],
                ["sclerotic_band", "trabecular_blurring"],
            )
            for item in target_overlays:
                self.assertTrue(Path(item["overlay_path"]).exists())
            by_target = {finding["target"]: finding for finding in bundle["findings"]}
            self.assertEqual(by_target["sclerotic_band"]["execution_mode"], "vlm_plus_segmenter")
            self.assertTrue(by_target["sclerotic_band"]["diagnosis_usable"])
            self.assertEqual(by_target["trabecular_blurring"]["execution_mode"], "vlm_only")
            self.assertEqual(by_target["trabecular_blurring"]["segmentation_ref"]["status"], "not_run")
            self.assertFalse(by_target["trabecular_blurring"]["diagnosis_usable"])
            self.assertEqual(
                by_target["trabecular_blurring"]["diagnosis_usable_level"],
                "observation_only",
            )
            self.assertEqual(bundle["present_findings"], ["sclerotic_band"])
            self.assertEqual(bundle["numeric_evidence"]["diagnosis_usable_finding_count"], 1)
            self.assertEqual(bundle["numeric_evidence"]["diagnosis_unusable_finding_count"], 1)


if __name__ == "__main__":
    unittest.main()
