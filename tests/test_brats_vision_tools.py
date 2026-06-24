import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from agents.vision_agent import VisionAgent
from tools.feature_extraction_tool import FeatureExtractionTool
from tools.mask_reader_tool import MaskReaderTool
from tools.overlay_generation_tool import OverlayGenerationTool


class BratsVisionToolsTest(unittest.TestCase):
    def _write_demo_image_and_mask(self, base_dir: Path) -> tuple[Path, Path]:
        image_path = base_dir / "case_flair.png"
        mask_path = base_dir / "case_mask.png"
        image = Image.new("L", (8, 8), 80)
        mask = Image.new("L", (8, 8), 0)
        pixels = mask.load()
        for x in range(1, 5):
            for y in range(1, 5):
                pixels[x, y] = 2
        for x in range(2, 4):
            for y in range(2, 4):
                pixels[x, y] = 1
        pixels[3, 3] = 4
        image.save(image_path)
        mask.save(mask_path)
        return image_path, mask_path

    def test_mask_reader_loads_label_counts(self):
        with TemporaryDirectory() as tmpdir:
            image_path, mask_path = self._write_demo_image_and_mask(Path(tmpdir))
            mask_data = MaskReaderTool().read(mask_path)

            self.assertEqual(mask_data.width, 8)
            self.assertEqual(mask_data.height, 8)
            self.assertEqual(mask_data.label_counts[4], 1)
            self.assertEqual(mask_data.label_counts[1], 3)
            self.assertEqual(mask_data.label_counts[2], 12)

    def test_feature_extraction_computes_brats_regions(self):
        with TemporaryDirectory() as tmpdir:
            _, mask_path = self._write_demo_image_and_mask(Path(tmpdir))
            mask_data = MaskReaderTool().read(mask_path)

            features = FeatureExtractionTool(voxel_volume_ml=0.5).extract_brats_features(mask_data)

            self.assertEqual(features["enhancing_tumor_volume_ml"], 0.5)
            self.assertEqual(features["tumor_core_volume_ml"], 2.0)
            self.assertEqual(features["whole_tumor_volume_ml"], 8.0)
            self.assertTrue(features["edema_present"])
            self.assertEqual(features["segmentation_quality"], "demo_ground_truth")

    def test_overlay_generation_writes_png(self):
        with TemporaryDirectory() as tmpdir:
            image_path, mask_path = self._write_demo_image_and_mask(Path(tmpdir))
            overlay_path = Path(tmpdir) / "overlay.png"

            output = OverlayGenerationTool().generate_overlay(
                image_path=image_path,
                mask_path=mask_path,
                overlay_path=overlay_path,
            )

            self.assertEqual(output, overlay_path)
            self.assertTrue(overlay_path.exists())
            with Image.open(overlay_path) as overlay:
                self.assertEqual(overlay.mode, "RGBA")

    def test_vision_agent_can_run_brats_ground_truth_demo(self):
        with TemporaryDirectory() as tmpdir:
            image_path, mask_path = self._write_demo_image_and_mask(Path(tmpdir))
            overlay_path = Path(tmpdir) / "overlay.png"

            result = VisionAgent().analyze_brats_ground_truth(
                image_path=str(image_path),
                mask_path=str(mask_path),
                overlay_path=str(overlay_path),
                disease_knowledge={"disease_name": "成人弥漫性胶质瘤"},
            )

            self.assertEqual(result["modality"], "MRI")
            self.assertEqual(result["body_part"], "brain")
            self.assertEqual(result["image_outputs"]["mask_path"], str(mask_path))
            self.assertTrue(Path(result["image_outputs"]["overlay_path"]).exists())
            self.assertEqual(result["visual_evidence"]["whole_tumor_volume_ml"], 16.0)
            self.assertIn("肿瘤区域分割 mask 已生成", result["visual_evidence"]["suspected_visual_findings"])

    def test_vision_agent_uses_knowledge_visual_protocol_for_measurement_completeness(self):
        with TemporaryDirectory() as tmpdir:
            image_path, mask_path = self._write_demo_image_and_mask(Path(tmpdir))
            flair_path = Path(tmpdir) / "case_flair.nii.gz"
            image_path.rename(flair_path)
            overlay_path = Path(tmpdir) / "overlay.png"
            knowledge = {
                "disease_name": "成人弥漫性胶质瘤",
                "visual_protocol": {
                    "disease_target": "diffuse_glioma_adult",
                    "available_modalities": ["FLAIR"],
                    "required_modalities": {
                        "whole_tumor": ["FLAIR"],
                        "tumor_core": ["T1", "T1ce", "T2"],
                        "enhancing_tumor": ["T1ce"],
                    },
                    "measurements": [
                        "whole_tumor_volume_ml",
                        "tumor_core_volume_ml",
                        "enhancing_tumor_volume_ml",
                    ],
                },
            }

            result = VisionAgent().analyze_brats_ground_truth(
                image_path=str(flair_path),
                mask_path=str(mask_path),
                overlay_path=str(overlay_path),
                disease_knowledge=knowledge,
            )

            evidence = result["visual_evidence"]
            self.assertEqual(evidence["disease_target"], "diffuse_glioma_adult")
            self.assertEqual(evidence["measurements"]["whole_tumor_volume_ml"], 16.0)
            self.assertIsNone(evidence["measurements"]["tumor_core_volume_ml"])
            self.assertIsNone(evidence["measurements"]["enhancing_tumor_volume_ml"])
            self.assertIsNone(evidence.get("tumor_core_volume_ml"))
            self.assertIsNone(evidence.get("enhancing_tumor_volume_ml"))
            self.assertEqual(evidence["completeness"]["whole_tumor"]["status"], "supported")
            self.assertEqual(evidence["completeness"]["tumor_core"]["status"], "missing")
            self.assertIn("Requires T1", evidence["completeness"]["tumor_core"]["reason"])
            self.assertEqual(evidence["completeness"]["enhancing_tumor"]["reason"], "Requires T1ce modality")

    def test_vision_agent_attaches_tool_routing_and_qc_task_results(self):
        with TemporaryDirectory() as tmpdir:
            image_path, mask_path = self._write_demo_image_and_mask(Path(tmpdir))
            flair_path = Path(tmpdir) / "case_flair.nii.gz"
            image_path.rename(flair_path)
            overlay_path = Path(tmpdir) / "overlay.png"
            knowledge = {
                "disease_name": "成人弥漫性胶质瘤",
                "visual_protocol": {
                    "disease_target": "diffuse_glioma_adult",
                    "available_modalities": ["FLAIR"],
                    "alignment_tasks": [
                        {
                            "task": "segment_whole_tumor",
                            "required_modalities": ["FLAIR"],
                            "reason": "whole tumor 主要依赖 FLAIR 可见范围。",
                        },
                        {
                            "task": "measure_enhancing_tumor",
                            "required_modalities": ["T1ce"],
                            "reason": "enhancing tumor 需要增强 T1ce。",
                        },
                    ],
                    "required_modalities": {
                        "whole_tumor": ["FLAIR"],
                        "enhancing_tumor": ["T1ce"],
                    },
                    "measurements": [
                        "whole_tumor_volume_ml",
                        "enhancing_tumor_volume_ml",
                    ],
                },
            }

            result = VisionAgent().analyze_brats_ground_truth(
                image_path=str(flair_path),
                mask_path=str(mask_path),
                overlay_path=str(overlay_path),
                disease_knowledge=knowledge,
            )

            task_results = result["visual_evidence"]["segmentation_results"]
            by_target = {item["target"]: item for item in task_results}
            self.assertEqual(by_target["whole_tumor"]["status"], "completed")
            self.assertTrue(by_target["whole_tumor"]["diagnosis_usable"])
            self.assertEqual(by_target["enhancing_tumor"]["status"], "missing_input")
            self.assertFalse(by_target["enhancing_tumor"]["diagnosis_usable"])
            self.assertIn("visual_tool_plan", result["visual_evidence"])

    def test_generic_visual_protocol_executor_runs_mask_backed_routed_task(self):
        with TemporaryDirectory() as tmpdir:
            image_path, mask_path = self._write_demo_image_and_mask(Path(tmpdir))
            flair_path = Path(tmpdir) / "case_flair.nii.gz"
            image_path.rename(flair_path)
            knowledge = {
                "disease_name": "通用胶质瘤视觉协议",
                "visual_protocol": {
                    "disease_target": "generic_glioma_protocol",
                    "imaging_modalities": ["MRI"],
                    "available_modalities": ["FLAIR"],
                    "alignment_tasks": [
                        {
                            "task": "segment_whole_tumor",
                            "required_modalities": ["FLAIR"],
                            "reason": "FLAIR supports whole tumor segmentation.",
                        },
                        {
                            "task": "measure_enhancing_tumor",
                            "required_modalities": ["T1ce"],
                            "reason": "Enhancement requires T1ce.",
                        },
                    ],
                    "required_modalities": {
                        "whole_tumor": ["FLAIR"],
                        "enhancing_tumor": ["T1ce"],
                    },
                    "measurements": [
                        "whole_tumor_volume_ml",
                        "enhancing_tumor_volume_ml",
                    ],
                },
            }

            result = VisionAgent().analyze_with_visual_protocol(
                image_path=str(flair_path),
                disease_knowledge=knowledge,
                mask_path=str(mask_path),
                overlay_path=str(Path(tmpdir) / "generic_overlay.png"),
            )

            evidence = result["visual_evidence"]
            by_target = {item["target"]: item for item in evidence["segmentation_results"]}
            self.assertEqual(result["modality"], "MRI")
            self.assertEqual(evidence["disease_target"], "generic_glioma_protocol")
            self.assertEqual(by_target["whole_tumor"]["status"], "completed")
            self.assertTrue(by_target["whole_tumor"]["diagnosis_usable"])
            self.assertEqual(by_target["whole_tumor"]["measurements"]["whole_tumor_volume_ml"], 16.0)
            self.assertEqual(by_target["enhancing_tumor"]["status"], "missing_input")
            self.assertIsNone(evidence["measurements"]["enhancing_tumor_volume_ml"])

    def test_generic_visual_protocol_executor_does_not_fake_mask_without_runtime(self):
        with TemporaryDirectory() as tmpdir:
            image_path, _ = self._write_demo_image_and_mask(Path(tmpdir))
            flair_path = Path(tmpdir) / "case_flair.nii.gz"
            image_path.rename(flair_path)
            knowledge = {
                "disease_name": "通用胶质瘤视觉协议",
                "visual_protocol": {
                    "disease_target": "generic_glioma_protocol",
                    "imaging_modalities": ["MRI"],
                    "available_modalities": ["FLAIR"],
                    "alignment_tasks": [
                        {
                            "task": "segment_whole_tumor",
                            "required_modalities": ["FLAIR"],
                            "reason": "FLAIR supports whole tumor segmentation.",
                        }
                    ],
                    "required_modalities": {"whole_tumor": ["FLAIR"]},
                    "measurements": ["whole_tumor_volume_ml"],
                },
            }

            result = VisionAgent().analyze_with_visual_protocol(
                image_path=str(flair_path),
                disease_knowledge=knowledge,
            )

            evidence = result["visual_evidence"]
            self.assertEqual(result["image_outputs"]["mask_path"], "not_generated")
            self.assertEqual(evidence["segmentation_results"][0]["status"], "no_capable_tool")
            self.assertFalse(evidence["segmentation_results"][0]["diagnosis_usable"])
            self.assertEqual(evidence["completeness"]["whole_tumor"]["status"], "unassessed")


if __name__ == "__main__":
    unittest.main()
