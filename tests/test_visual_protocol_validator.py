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

    def test_static_guideline_skills_have_valid_evidence_protocol(self):
        validator = VisualProtocolValidator()

        for skill_path in (
            Path("skills/femoral_head_necrosis.yaml"),
            Path("skills/pneumonia_chest_xray.yaml"),
        ):
            with self.subTest(skill_path=str(skill_path)):
                skill = json.loads(skill_path.read_text(encoding="utf-8"))
                result = validator.validate_evidence_protocol(skill)

                self.assertTrue(result["valid"], result)
                self.assertEqual(result["errors"], [])

    def test_non_fhn_skill_declares_evidence_acquisition_protocol(self):
        skill = json.loads(Path("skills/pneumonia_chest_xray.yaml").read_text(encoding="utf-8"))

        imaging = skill["imaging_evidence_protocol"]
        targets = {item["target"]: item for item in imaging["finding_targets"]}
        quantitative = skill["quantitative_evidence_protocol"]
        clinical = skill["clinical_context_protocol"]
        integrated = skill["integrated_reasoning_protocol"]

        self.assertEqual(imaging["disease_target"], "community_acquired_pneumonia")
        self.assertEqual(targets["lung_opacity"]["execution_mode"], "vlm_plus_segmenter")
        self.assertEqual(targets["fever_or_cough"]["execution_mode"], "clinical_context_only")
        self.assertEqual(
            targets["fever_or_cough"]["diagnosis_usable_level"],
            "risk_modifier_only",
        )
        self.assertTrue(quantitative["image_feature_quantification"])
        self.assertTrue(quantitative["measurement_evidence"])
        self.assertIn("fever", clinical["symptom_fields"])
        self.assertIn(
            "clinical context cannot confirm pneumonia without imaging and clinical assessment",
            clinical["reasoning_rule"],
        )
        self.assertIn("clinical_context_source", integrated["required_sections"])

    def test_static_skills_declare_versioned_quantitative_contract(self):
        validator = VisualProtocolValidator()

        for skill_path in (
            Path("skills/femoral_head_necrosis.yaml"),
            Path("skills/diffuse_glioma_brats.yaml"),
            Path("skills/pneumonia_chest_xray.yaml"),
            Path("skills/idiopathic_pulmonary_fibrosis_hrct.yaml"),
        ):
            with self.subTest(skill_path=str(skill_path)):
                skill = json.loads(skill_path.read_text(encoding="utf-8"))
                quantitative = skill["quantitative_evidence_protocol"]

                self.assertEqual(
                    quantitative["schema_version"],
                    "quantitative_evidence_protocol.v1",
                )
                self.assertIn("image_feature_quantification", quantitative["protocol_sections"])
                self.assertIn("measurement_evidence", quantitative["protocol_sections"])
                self.assertIn("diagnosis_boundary", quantitative)
                self.assertIn("quality_gate_defaults", quantitative)
                result = validator.validate_quantitative_evidence_protocol(quantitative)
                self.assertTrue(result["valid"], result)

    def test_quantitative_protocol_requires_item_level_contract(self):
        skill = self._minimal_valid_skill()
        skill["imaging_evidence_protocol"] = {
            "disease_target": "minimal_disease",
            "finding_targets": [
                {
                    "target": "target_region",
                    "execution_mode": "measurement_only",
                    "evidence_type": "anatomical_measurement",
                    "diagnosis_usable_level": "measurement_support",
                    "segmentation_mode": "none",
                    "measurement_dependencies": ["roi"],
                }
            ],
        }
        skill["quantitative_evidence_protocol"] = {
            "schema_version": "quantitative_evidence_protocol.v1",
            "protocol_sections": ["image_feature_quantification", "measurement_evidence"],
            "diagnosis_boundary": "Exploratory features cannot confirm diagnosis.",
            "quality_gate_defaults": {"measurement_usable_default": False},
            "image_feature_quantification": [
                {
                    "feature_name": "texture_score",
                    "target": "target_region",
                    "diagnosis_usable": True,
                    "diagnosis_usable_level": "candidate_support",
                }
            ],
            "measurement_evidence": [
                {
                    "measurement_name": "collapse_depth",
                    "target": "target_region",
                    "measurement_usable_default": True,
                }
            ],
        }
        skill["clinical_context_protocol"] = {
            "risk_factors": ["risk_demo"],
            "reasoning_rule": "clinical context cannot confirm diagnosis",
        }
        skill["integrated_reasoning_protocol"] = {
            "required_sections": ["imaging_support", "clinical_context_source"],
            "safety_rules": [],
        }

        result = VisualProtocolValidator().validate_evidence_protocol(skill)

        self.assertFalse(result["valid"])
        self.assertIn(
            "quantitative_evidence_protocol.image_feature_quantification[0].validation_status is required",
            result["errors"],
        )
        self.assertIn(
            "quantitative_evidence_protocol.image_feature_quantification[0] must remain exploratory_only unless validated",
            result["errors"],
        )
        self.assertIn(
            "quantitative_evidence_protocol.measurement_evidence[0].requires must be a non-empty list",
            result["errors"],
        )
        self.assertIn(
            "quantitative_evidence_protocol.measurement_evidence[0] cannot default to measurement usable without quality requirements",
            result["errors"],
        )

    def test_evidence_protocol_requires_clinical_context_limits(self):
        skill = self._minimal_valid_skill()
        skill["imaging_evidence_protocol"] = {
            "disease_target": "minimal_disease",
            "finding_targets": [
                {
                    "target": "target_region",
                    "execution_mode": "vlm_only",
                    "evidence_type": "visual_observation",
                    "diagnosis_usable_level": "observation_only",
                }
            ],
        }
        skill["quantitative_evidence_protocol"] = {
            "image_feature_quantification": [],
            "measurement_evidence": [],
        }
        skill["clinical_context_protocol"] = {
            "risk_factors": ["risk_demo"],
        }
        skill["integrated_reasoning_protocol"] = {
            "required_sections": ["imaging_support", "clinical_risk_support"],
            "safety_rules": [],
        }

        result = VisualProtocolValidator().validate_evidence_protocol(skill)

        self.assertFalse(result["valid"])
        self.assertIn(
            "clinical_context_protocol.reasoning_rule must state clinical context cannot confirm diagnosis",
            result["errors"],
        )
        self.assertIn(
            "integrated_reasoning_protocol.required_sections must include clinical_context_source",
            result["errors"],
        )

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
