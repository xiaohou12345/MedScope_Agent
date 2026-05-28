import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from contracts.medical_contracts import SegmentationResult
from tools.visual_quality_gate import VisualQualityGate
from tools.visual_tool_router import VisualToolRegistry, VisualToolRouter


class VisualToolRouterTest(unittest.TestCase):
    def _glioma_protocol(self):
        return {
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
            "measurements": [
                "whole_tumor_volume_ml",
                "enhancing_tumor_volume_ml",
            ],
        }

    def test_default_registry_contains_medsam2_as_generic_candidate_segmenter(self):
        registry = VisualToolRegistry.from_file(Path("tools/visual_tool_registry.yaml"))

        medsam2 = registry.get("medsam2")

        self.assertEqual(medsam2.role, "candidate_segmenter")
        self.assertIn("generic_lesion_candidate", medsam2.supported_tasks)
        self.assertTrue(medsam2.supports(modality="MRI", task_name="segment_whole_tumor"))

    def test_router_prefers_specific_tool_then_marks_missing_input(self):
        registry = VisualToolRegistry.from_dict(
            {
                "tools": [
                    {
                        "tool_name": "medsam2",
                        "supported_modalities": ["MRI", "CT", "Xray", "PNG"],
                        "supported_tasks": ["generic_lesion_candidate"],
                        "output": "binary_mask",
                        "priority": 50,
                        "role": "candidate_segmenter",
                    },
                    {
                        "tool_name": "brats_model",
                        "supported_modalities": ["MRI FLAIR", "FLAIR", "MRI T1ce"],
                        "supported_tasks": ["segment_whole_tumor", "enhancing_tumor"],
                        "output": "multi_label_mask",
                        "priority": 100,
                        "role": "specialist_segmenter",
                    },
                ]
            }
        )

        plan = VisualToolRouter(registry=registry).plan_from_protocol(self._glioma_protocol())
        by_target = {item["task"]["target"]: item for item in plan}

        self.assertEqual(by_target["whole_tumor"]["status"], "runnable")
        self.assertEqual(by_target["whole_tumor"]["selected_tool"]["tool_name"], "brats_model")
        self.assertEqual(by_target["whole_tumor"]["selected_tool"]["role"], "specialist_segmenter")
        self.assertEqual(by_target["enhancing_tumor"]["status"], "missing_input")
        self.assertIsNone(by_target["enhancing_tumor"]["selected_tool"])
        self.assertIn("Requires T1ce", by_target["enhancing_tumor"]["reason"])

    def test_router_falls_back_to_medsam2_candidate_when_no_specialist_exists(self):
        registry = VisualToolRegistry.from_dict(
            {
                "tools": [
                    {
                        "tool_name": "medsam2",
                        "supported_modalities": ["MRI", "CT", "Xray", "PNG"],
                        "supported_tasks": ["generic_lesion_candidate"],
                        "output": "binary_mask",
                        "priority": 50,
                        "role": "candidate_segmenter",
                    }
                ]
            }
        )

        plan = VisualToolRouter(registry=registry).plan_from_protocol(self._glioma_protocol())

        self.assertEqual(plan[0]["status"], "runnable")
        self.assertEqual(plan[0]["selected_tool"]["tool_name"], "medsam2")
        self.assertEqual(plan[0]["selected_tool"]["role"], "candidate_segmenter")
        self.assertFalse(plan[0]["diagnosis_usable_without_qc"])

    def test_router_returns_no_capable_tool_when_registry_cannot_cover_task(self):
        registry = VisualToolRegistry.from_dict({"tools": []})

        plan = VisualToolRouter(registry=registry).plan_from_protocol(self._glioma_protocol())

        self.assertEqual(plan[0]["status"], "no_capable_tool")
        self.assertIsNone(plan[0]["selected_tool"])
        self.assertFalse(plan[0]["diagnosis_usable_without_qc"])

    def test_router_derives_execution_modes_from_skill_finding_targets(self):
        registry = VisualToolRegistry.from_dict(
            {
                "tools": [
                    {
                        "tool_name": "medsam2",
                        "supported_modalities": ["MRI", "CT", "X-ray", "PNG"],
                        "supported_tasks": ["generic_lesion_candidate"],
                        "supported_execution_modes": ["vlm_plus_segmenter"],
                        "output": "binary_mask",
                        "priority": 50,
                        "role": "candidate_segmenter",
                    },
                    {
                        "tool_name": "xray_fhn_detector",
                        "supported_modalities": ["X-ray"],
                        "supported_tasks": ["trabecular_blurring", "collapse"],
                        "supported_execution_modes": ["vlm_only", "measurement_only"],
                        "output": "boxes_or_findings",
                        "priority": 80,
                        "role": "rule_detector",
                    },
                ]
            }
        )
        protocol = {
            "disease_target": "femoral_head_necrosis",
            "available_modalities": ["X-ray"],
            "finding_targets": [
                {
                    "target": "sclerotic_band",
                    "required_modalities": ["X-ray"],
                    "execution_mode": "vlm_plus_segmenter",
                    "localization_mode": "bbox",
                    "segmentation_mode": "candidate_mask",
                    "diagnosis_usable_level": "candidate_support",
                },
                {
                    "target": "trabecular_blurring",
                    "required_modalities": ["X-ray"],
                    "execution_mode": "vlm_only",
                    "localization_mode": "score",
                    "segmentation_mode": "none",
                    "diagnosis_usable_level": "observation_only",
                },
                {
                    "target": "collapse",
                    "required_modalities": ["X-ray"],
                    "execution_mode": "measurement_only",
                    "localization_mode": "measurement",
                    "segmentation_mode": "none",
                    "diagnosis_usable_level": "measurement_support",
                },
            ],
            "alignment_tasks": [
                {
                    "task": "assess_early_osteonecrosis",
                    "target": "early_osteonecrosis",
                    "required_modalities": ["MRI T1", "MRI T2", "MRI STIR"],
                    "execution_mode": "insufficient_input",
                }
            ],
        }

        plan = VisualToolRouter(registry=registry).plan_from_protocol(protocol)
        by_target = {item["task"]["target"]: item for item in plan}

        self.assertEqual(by_target["sclerotic_band"]["execution_mode"], "vlm_plus_segmenter")
        self.assertEqual(by_target["sclerotic_band"]["selected_tool"]["tool_name"], "medsam2")
        self.assertFalse(by_target["sclerotic_band"]["diagnosis_usable_without_qc"])
        self.assertEqual(by_target["trabecular_blurring"]["execution_mode"], "vlm_only")
        self.assertEqual(by_target["trabecular_blurring"]["selected_tool"]["tool_name"], "xray_fhn_detector")
        self.assertTrue(by_target["trabecular_blurring"]["diagnosis_usable_without_qc"])
        self.assertEqual(by_target["collapse"]["execution_mode"], "measurement_only")
        self.assertEqual(by_target["collapse"]["selected_tool"]["tool_name"], "xray_fhn_detector")
        self.assertEqual(by_target["early_osteonecrosis"]["execution_mode"], "insufficient_input")
        self.assertEqual(by_target["early_osteonecrosis"]["status"], "missing_input")
        self.assertIn("Requires MRI T1", by_target["early_osteonecrosis"]["reason"])

    def test_quality_gate_marks_empty_or_unstable_mask_as_not_diagnosis_usable(self):
        result = VisualQualityGate().evaluate(
            task_name="segment_whole_tumor",
            target="whole_tumor",
            image_outputs={
                "mask_path": "output/fake/empty_mask.nii.gz",
                "overlay_path": "output/fake/empty_overlay.png",
            },
            measurements={"whole_tumor_volume_ml": 0.0},
            segmentation_source="medsam2",
        )

        self.assertIsInstance(result, SegmentationResult)
        self.assertEqual(result.status, "low_quality")
        self.assertFalse(result.diagnosis_usable)
        self.assertEqual(result.completeness["status"], "unassessed")

    def test_registry_can_load_json_yaml_file(self):
        with TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "visual_tool_registry.yaml"
            registry_path.write_text(
                """
{
  "tools": [
    {
      "tool_name": "xray_fhn_detector",
      "supported_modalities": ["Xray"],
      "supported_tasks": ["assess_late_xray_findings"],
      "output": "boxes_or_findings",
      "priority": 80,
      "role": "rule_detector"
    }
  ]
}
""",
                encoding="utf-8",
            )

            registry = VisualToolRegistry.from_file(registry_path)

            self.assertEqual(registry.get("xray_fhn_detector").output, "boxes_or_findings")


if __name__ == "__main__":
    unittest.main()
