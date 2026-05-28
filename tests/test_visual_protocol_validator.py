import json
import unittest
from copy import deepcopy
from pathlib import Path

from tools.skill_builder_tool import SkillBuilderTool
from tools.visual_protocol_validator import VisualProtocolValidator


class VisualProtocolValidatorTest(unittest.TestCase):
    def test_static_guideline_skills_have_valid_visual_protocol(self):
        validator = VisualProtocolValidator()

        for skill_path in (
            Path("skills/femoral_head_necrosis.yaml"),
            Path("skills/diffuse_glioma_brats.yaml"),
            Path("skills/pneumonia_chest_xray.yaml"),
            Path("skills/idiopathic_pulmonary_fibrosis_hrct.yaml"),
        ):
            with self.subTest(skill_path=str(skill_path)):
                skill = json.loads(skill_path.read_text(encoding="utf-8"))
                result = validator.validate_skill(skill)

                self.assertTrue(result["valid"], result)
                self.assertEqual(result["errors"], [])

    def test_femoral_head_skill_declares_stage_ii_xray_findings(self):
        skill = json.loads(Path("skills/femoral_head_necrosis.yaml").read_text(encoding="utf-8"))
        finding_targets = {
            finding["target"]: finding
            for finding in skill["visual_protocol"].get("finding_targets", [])
        }

        self.assertIn("sclerotic_band", finding_targets)
        self.assertIn("cystic_change", finding_targets)
        self.assertIn("trabecular_blurring", finding_targets)
        self.assertIn("collapse", finding_targets)
        self.assertEqual(
            finding_targets["sclerotic_band"]["measurements"],
            ["area_ratio_in_femoral_head", "relative_density_score", "elongation"],
        )
        self.assertEqual(
            finding_targets["cystic_change"]["measurements"],
            ["area_ratio_in_femoral_head", "relative_lucency_score", "roundness"],
        )

    def test_femoral_head_skill_declares_anatomy_reference_for_normalized_measurements(self):
        skill = json.loads(Path("skills/femoral_head_necrosis.yaml").read_text(encoding="utf-8"))

        anatomy_reference = skill["visual_protocol"].get("anatomy_reference")

        self.assertEqual(anatomy_reference["target"], "femoral_head")
        self.assertEqual(anatomy_reference["display_name"], "股骨头解剖区域")
        self.assertEqual(anatomy_reference["required_modalities"], ["X-ray"])
        self.assertIn("area_ratio_in_femoral_head", anatomy_reference["normalizes"])

    def test_missing_visual_protocol_is_invalid_for_guideline_skill(self):
        result = VisualProtocolValidator().validate_skill(
            {
                "skill_type": "guideline_based",
                "skill_id": "missing_protocol_v0.1",
            }
        )

        self.assertFalse(result["valid"])
        self.assertIn("visual_protocol is required for guideline_based skill", result["errors"])

    def test_alignment_tasks_must_name_task_and_required_modalities(self):
        skill = self._minimal_valid_skill()
        skill["visual_protocol"]["alignment_tasks"] = [
            {"task": "segment_target"},
            {"required_modalities": ["MRI"]},
        ]

        result = VisualProtocolValidator().validate_skill(skill)

        self.assertFalse(result["valid"])
        self.assertIn("visual_protocol.alignment_tasks[0].required_modalities is required", result["errors"])
        self.assertIn("visual_protocol.alignment_tasks[1].task is required", result["errors"])

    def test_required_next_images_and_blocked_scope_are_quality_gates(self):
        skill = self._minimal_valid_skill()
        skill["visual_protocol"].pop("required_next_images")
        skill["visual_protocol"]["diagnosis_scope"] = {"allowed": ["limited report"]}

        result = VisualProtocolValidator().validate_skill(skill)

        self.assertFalse(result["valid"])
        self.assertIn("visual_protocol.required_next_images is required", result["errors"])
        self.assertIn(
            "visual_protocol.diagnosis_scope.blocked should list forbidden conclusions",
            result["warnings"],
        )

    def test_skill_builder_records_visual_protocol_status_in_quality_control(self):
        skill = SkillBuilderTool().build_guideline_skill_from_search(
            {
                "disease_key": "incomplete_visual_protocol",
                "disease_name": "视觉协议不完整疾病",
                "has_guideline": True,
                "source_type": "medical_guideline",
                "evidence_level": "high",
                "source_catalog_path": "output/fake/incomplete_visual_protocol.json",
                "sources": [
                    {
                        "source_id": "test_guideline",
                        "title": "Test guideline",
                        "publisher": "Test publisher",
                        "url": "https://example.org/test-guideline",
                    }
                ],
                "guideline_documents": [
                    {
                        "source_id": "test_guideline",
                        "title": "Test guideline",
                        "sections": [
                            {
                                "heading": "clinical_features",
                                "text": "common_symptoms: pain",
                                "citations": [
                                    {
                                        "source_id": "test_guideline",
                                        "title": "Test guideline",
                                        "url": "https://example.org/test-guideline",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )

        self.assertEqual(skill["quality_control"]["visual_protocol_status"], "invalid")
        self.assertIn(
            "visual_protocol.alignment_tasks is required",
            skill["quality_control"]["visual_protocol_errors"],
        )
        self.assertIn(
            "visual_protocol.required_modalities is required",
            skill["quality_control"]["visual_protocol_errors"],
        )
        self.assertEqual(skill["quality_control"]["formal_skill_status"], "needs_review")
        self.assertFalse(skill["quality_control"]["can_enter_formal_guideline_skill"])

    def test_skill_builder_marks_valid_visual_protocol_as_valid(self):
        guideline_result = {
            "disease_key": "valid_visual_protocol",
            "disease_name": "视觉协议完整疾病",
            "has_guideline": True,
            "source_type": "medical_guideline",
            "evidence_level": "high",
            "source_catalog_path": "output/fake/valid_visual_protocol.json",
            "sources": [
                {
                    "source_id": "valid_guideline",
                    "title": "Valid guideline",
                    "publisher": "Valid publisher",
                    "url": "https://example.org/valid-guideline",
                }
            ],
            "guideline_payload": {
                "clinical_features": {"common_symptoms": ["pain"], "risk_factors": []},
                "required_image_views": ["MRI"],
                "vision_agent_tasks": {
                    "segmentation_targets": ["target_region"],
                    "quantitative_features": ["target_volume_ml"],
                },
                "guideline_extraction": {
                    "citations": [
                        {
                            "source_id": "valid_guideline",
                            "title": "Valid guideline",
                            "url": "https://example.org/valid-guideline",
                        }
                    ],
                },
                "visual_protocol": self._minimal_valid_skill()["visual_protocol"],
            },
        }

        skill = SkillBuilderTool().build_guideline_skill_from_search(guideline_result)

        self.assertEqual(skill["quality_control"]["visual_protocol_status"], "valid")
        self.assertEqual(skill["quality_control"]["visual_protocol_errors"], [])
        self.assertEqual(skill["quality_control"]["formal_skill_status"], "formal_ready")
        self.assertTrue(skill["quality_control"]["can_enter_formal_guideline_skill"])

    def _minimal_valid_skill(self):
        return deepcopy(
            {
                "skill_type": "guideline_based",
                "skill_id": "minimal_valid_v0.1",
                "visual_protocol": {
                    "disease_target": "minimal_disease",
                    "clinical_focus": "minimal disease imaging assessment",
                    "imaging_modalities": ["MRI"],
                    "alignment_tasks": [
                        {
                            "task": "segment_target_region",
                            "required_modalities": ["MRI"],
                            "reason": "MRI supports this target.",
                        }
                    ],
                    "required_modalities": {
                        "target_region": ["MRI"],
                    },
                    "required_next_images": [
                        {
                            "modality": "MRI",
                            "region": "target region",
                            "reason": "MRI is needed for the visual protocol.",
                        }
                    ],
                    "diagnosis_scope": {
                        "allowed": ["limited image-supported assessment"],
                        "blocked": ["do not infer missing evidence as negative"],
                    },
                },
            }
        )


if __name__ == "__main__":
    unittest.main()
