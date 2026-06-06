import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.diagnosis_agent import DiagnosisDoctorAgent
from agents.gaodoctor_agent import GaoDoctorAgent
from agents.vision_agent import VisionAgent
from contracts.medical_contracts import SkillDescriptor
from memory.memory_manager import MemoryManager
from tools.skill_builder_tool import SkillBuilderTool
from tools.visual_tool_router import VisualToolRouter


class ProtocolTraceVisionAgent:
    def analyze_image(self, **kwargs):
        return self.analyze_with_visual_protocol(**kwargs)

    def analyze_with_visual_protocol(self, **kwargs):
        return {
            "image_path": kwargs["image_path"],
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": kwargs["image_path"],
                "mask_path": "not_generated",
                "overlay_path": "not_generated",
            },
            "requested_targets": ["sclerotic_band", "collapse", "early_osteonecrosis"],
            "requested_features": [],
            "visual_evidence": {
                "collapse": False,
                "joint_space_narrowing": False,
                "sclerosis": "candidate",
                "cystic_change": "unknown",
                "femoral_head_shape": "unknown",
                "joint_space": "unknown",
                "lesion_mask": "not_generated",
                "confidence": 0.35,
                "texture_abnormality_score": 0.0,
                "lesion_area_ratio": 0.0,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "disease_target": "femoral_head_necrosis",
                "findings": [
                    {
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                        "diagnosis_usable_level": "candidate_support",
                        "measurements": {"area_px": 120},
                        "quality": {"qc_status": "candidate_only"},
                    },
                    {
                        "target": "collapse",
                        "display_name": "股骨头塌陷",
                        "status": "unassessed",
                        "diagnosis_usable": False,
                        "diagnosis_usable_level": "not_usable",
                        "measurements": {"measurement_usable": False},
                        "quality": {"roi_quality": "missing_contour"},
                    },
                ],
                "completeness": {
                    "early_osteonecrosis": {
                        "status": "missing",
                        "reason": "X-ray only; requires MRI T1/T2/STIR",
                    }
                },
                "segmentation_quality": "not_run_candidate_only",
            },
        }


class FemoralHeadEvidenceProtocolTest(unittest.TestCase):
    def setUp(self):
        self.skill = SkillBuilderTool().load_guideline_skill("femoral_head_necrosis")

    def test_fhn_skill_exposes_multidimensional_evidence_protocol(self):
        for key in [
            "imaging_evidence_protocol",
            "quantitative_evidence_protocol",
            "differential_diagnosis_protocol",
            "clinical_context_protocol",
            "integrated_reasoning_protocol",
        ]:
            self.assertIn(key, self.skill)

        imaging_protocol = self.skill["imaging_evidence_protocol"]
        targets = {item["target"]: item for item in imaging_protocol["finding_targets"]}
        self.assertEqual(targets["sclerotic_band"]["execution_mode"], "vlm_plus_segmenter")
        self.assertEqual(targets["cystic_change"]["diagnosis_usable_level"], "candidate_support")
        self.assertEqual(targets["trabecular_blurring"]["segmentation_mode"], "none")
        self.assertEqual(targets["subchondral_fracture"]["execution_mode"], "vlm_plus_segmenter")
        self.assertEqual(targets["subchondral_fracture"]["diagnosis_usable_level"], "candidate_support")
        self.assertEqual(targets["collapse"]["execution_mode"], "measurement_only")
        self.assertEqual(targets["early_osteonecrosis"]["execution_mode"], "insufficient_input")

        quantitative = self.skill["quantitative_evidence_protocol"]
        exploratory = {
            item["feature_name"]: item
            for item in quantitative["image_feature_quantification"]
        }
        self.assertEqual(exploratory["trabecular_irregularity_score"]["validation_status"], "requires_validation")
        self.assertFalse(exploratory["trabecular_irregularity_score"]["diagnosis_usable"])

    def test_skill_descriptor_preserves_fhn_protocols_for_memory_and_diagnosis(self):
        descriptor = SkillDescriptor.from_skill(self.skill).to_dict()

        for key in [
            "imaging_evidence_protocol",
            "quantitative_evidence_protocol",
            "differential_diagnosis_protocol",
            "clinical_context_protocol",
            "integrated_reasoning_protocol",
        ]:
            self.assertIn(key, descriptor)

        self.assertEqual(
            descriptor["imaging_evidence_protocol"]["disease_target"],
            "femoral_head_necrosis",
        )
        self.assertTrue(descriptor["differential_diagnosis_protocol"]["candidates"])
        self.assertIn(
            "recommended_next_step",
            descriptor["integrated_reasoning_protocol"]["required_sections"],
        )

    def test_visual_router_builds_safe_fhn_execution_strategy(self):
        plan = VisualToolRouter().plan_from_skill(self.skill)
        by_target = {item["task"]["target"]: item for item in plan}

        self.assertEqual(by_target["sclerotic_band"]["execution_mode"], "vlm_plus_segmenter")
        self.assertEqual(by_target["sclerotic_band"]["evidence_type"], "candidate_mask")
        self.assertEqual(by_target["sclerotic_band"]["diagnosis_usable_level"], "candidate_support")
        self.assertFalse(by_target["sclerotic_band"]["diagnosis_usable_without_qc"])

        self.assertEqual(by_target["trabecular_blurring"]["execution_mode"], "vlm_only")
        self.assertEqual(by_target["trabecular_blurring"]["evidence_type"], "visual_observation")
        self.assertEqual(by_target["trabecular_blurring"]["diagnosis_usable_level"], "observation_only")

        self.assertEqual(by_target["collapse"]["execution_mode"], "measurement_only")
        self.assertEqual(by_target["collapse"]["evidence_type"], "anatomical_measurement")
        self.assertEqual(by_target["collapse"]["measurement_usable"], False)
        self.assertIn("contour", by_target["collapse"]["measurement_dependencies"])

        self.assertEqual(by_target["subchondral_fracture"]["execution_mode"], "vlm_plus_segmenter")
        self.assertEqual(by_target["subchondral_fracture"]["evidence_type"], "candidate_mask")
        self.assertFalse(by_target["subchondral_fracture"]["diagnosis_usable_without_qc"])

        self.assertEqual(by_target["early_osteonecrosis"]["execution_mode"], "insufficient_input")
        self.assertEqual(by_target["early_osteonecrosis"]["status"], "missing_input")
        self.assertEqual(by_target["early_osteonecrosis"]["diagnosis_usable_level"], "not_usable")

    def test_vision_agent_uses_imaging_evidence_protocol_for_fhn_runtime_plan(self):
        result = VisionAgent().analyze_with_visual_protocol(
            image_path="output/real/fhn/fhn_pelvis_xray_panel_b.png",
            disease_skill=self.skill,
        )
        evidence = result["visual_evidence"]
        by_target = {item["target"]: item for item in evidence["evidence_items"]}

        self.assertIn("sclerotic_band", by_target)
        self.assertIn("collapse", by_target)
        self.assertIn("early_osteonecrosis", by_target)
        self.assertEqual(by_target["sclerotic_band"]["evidence_type"], "candidate_mask")
        self.assertEqual(by_target["collapse"]["execution_mode"], "measurement_only")
        self.assertEqual(
            by_target["collapse"]["measurements"]["measurement_dependencies"],
            ["femoral_head_roi", "contour", "articular_surface_contour", "landmark_quality"],
        )
        self.assertFalse(by_target["collapse"]["measurements"]["measurement_usable"])
        self.assertEqual(by_target["early_osteonecrosis"]["execution_mode"], "insufficient_input")
        self.assertEqual(by_target["early_osteonecrosis"]["diagnosis_usable_level"], "not_usable")

    def test_vision_agent_default_image_entry_uses_fhn_protocol_not_simulated_evidence(self):
        result = VisionAgent().analyze_image(
            image_path="output/real/fhn/fhn_pelvis_xray_panel_b.png",
            disease_skill=self.skill,
        )
        evidence = result["visual_evidence"]
        by_target = {item["target"]: item for item in evidence["evidence_items"]}

        self.assertEqual(evidence["segmentation_quality"], "not_run_no_runtime_executor")
        self.assertEqual(result["modality"], "X-ray")
        self.assertIn("collapse", by_target)
        self.assertEqual(by_target["collapse"]["execution_mode"], "measurement_only")
        self.assertFalse(by_target["collapse"]["measurements"]["measurement_usable"])
        self.assertEqual(by_target["early_osteonecrosis"]["execution_mode"], "insufficient_input")

    def test_evidence_bundle_items_keep_quality_and_diagnosis_levels(self):
        bundle = GaoDoctorAgent()._build_visual_evidence_bundle(
            {
                "image_path": "output/fake/uploads/fhn_ap.png",
                "modality": "xray",
                "body_part": "hip",
                "image_outputs": {"original_image_path": "fhn_ap.png"},
                "visual_evidence": {
                    "disease_target": "femoral_head_necrosis",
                    "findings": [
                        {
                            "target": "sclerotic_band",
                            "display_name": "硬化带",
                            "status": "candidate_present",
                            "diagnosis_usable": True,
                            "diagnosis_usable_level": "candidate_support",
                            "measurements": {"area_px": 120},
                            "quality": {"qc_status": "candidate_only"},
                        },
                        {
                            "target": "trabecular_blurring",
                            "display_name": "骨小梁模糊",
                            "status": "candidate_present",
                            "diagnosis_usable": False,
                            "diagnosis_usable_level": "exploratory_only",
                            "measurements": {"trabecular_irregularity_score": 0.8},
                            "quality": {"validation_status": "requires_validation"},
                        },
                        {
                            "target": "collapse",
                            "display_name": "股骨头塌陷",
                            "status": "unassessed",
                            "diagnosis_usable": False,
                            "diagnosis_usable_level": "not_usable",
                            "measurements": {"measurement_usable": False},
                            "quality": {"roi_quality": "missing_contour"},
                        },
                    ],
                    "completeness": {
                        "early_osteonecrosis": {
                            "status": "missing",
                            "reason": "Requires MRI T1/T2/STIR",
                        }
                    },
                },
            },
            self.skill,
        )

        self.assertEqual(bundle["schema_version"], "visual_evidence_bundle.v2")
        self.assertEqual(len(bundle["evidence_items"]), 4)
        for item in bundle["evidence_items"]:
            self.assertIn("quality", item)
            self.assertIn("diagnosis_usable", item)
            self.assertIn("diagnosis_usable_level", item)

        by_target = {item["target"]: item for item in bundle["evidence_items"]}
        self.assertEqual(by_target["sclerotic_band"]["evidence_type"], "candidate_mask")
        self.assertEqual(by_target["trabecular_blurring"]["diagnosis_usable_level"], "exploratory_only")
        self.assertFalse(by_target["collapse"]["measurements"]["measurement_usable"])
        self.assertEqual(by_target["early_osteonecrosis"]["execution_mode"], "insufficient_input")

    def test_evidence_bundle_applies_quantitative_protocol_to_generic_findings(self):
        bundle = GaoDoctorAgent()._build_visual_evidence_bundle(
            {
                "image_path": "output/fake/uploads/fhn_ap.png",
                "modality": "xray",
                "body_part": "hip",
                "image_outputs": {"original_image_path": "fhn_ap.png"},
                "visual_evidence": {
                    "disease_target": "femoral_head_necrosis",
                    "findings": [
                        {
                            "target": "trabecular_blurring",
                            "display_name": "骨小梁模糊",
                            "status": "candidate_present",
                            "measurements": {"trabecular_irregularity_score": 0.8},
                        },
                        {
                            "target": "collapse",
                            "display_name": "股骨头塌陷",
                            "status": "candidate_present",
                            "measurements": {"collapse_depth_mm": 1.6},
                        },
                    ],
                },
            },
            self.skill,
        )

        by_target = {item["target"]: item for item in bundle["evidence_items"]}
        trabecular = by_target["trabecular_blurring"]
        collapse = by_target["collapse"]

        self.assertEqual(trabecular["evidence_type"], "image_feature_quantification")
        self.assertEqual(trabecular["diagnosis_usable_level"], "exploratory_only")
        self.assertFalse(trabecular["diagnosis_usable"])
        self.assertEqual(
            trabecular["quantitative_protocol"]["feature_names"],
            ["texture_disorder_score", "trabecular_irregularity_score"],
        )
        self.assertEqual(
            trabecular["quality"]["validation_status"],
            "requires_validation",
        )

        self.assertEqual(collapse["evidence_type"], "anatomical_measurement")
        self.assertEqual(collapse["diagnosis_usable_level"], "measurement_support")
        self.assertFalse(collapse["measurements"]["measurement_usable"])
        self.assertIn("femoral_head_roi", collapse["measurements"]["measurement_dependencies"])
        self.assertEqual(
            collapse["quantitative_protocol"]["measurement_names"],
            ["femoral_head_collapse_depth"],
        )

    def test_gaodoctor_persists_fhn_protocol_evidence_items_to_memory(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            doctor = GaoDoctorAgent(
                memory_manager=memory,
                vision_agent=ProtocolTraceVisionAgent(),
            )

            result = doctor.handle_patient_case(
                patient_message="右髋疼痛，上传 X 光，请根据股骨头坏死 skill 分析",
                image_path="output/real/fhn/fhn_pelvis_xray_panel_b.png",
                patient_info={"symptoms": ["髋关节疼痛"]},
                disease_key="femoral_head_necrosis",
            )

            saved_case = json.loads(Path(result["case_memory_path"]).read_text(encoding="utf-8"))
            image_bundle = saved_case["image_memory"]["visual_evidence_bundle"]
            self.assertEqual(image_bundle["schema_version"], "visual_evidence_bundle.v2")
            self.assertEqual(image_bundle["evidence_protocol_version"], "visual_evidence_bundle.v2")
            self.assertIn("evidence_items", image_bundle)
            by_target = {item["target"]: item for item in image_bundle["evidence_items"]}
            self.assertEqual(by_target["sclerotic_band"]["evidence_type"], "candidate_mask")
            self.assertEqual(by_target["sclerotic_band"]["diagnosis_usable_level"], "candidate_support")
            self.assertEqual(by_target["collapse"]["execution_mode"], "measurement_only")
            self.assertFalse(by_target["collapse"]["measurements"]["measurement_usable"])
            self.assertEqual(by_target["early_osteonecrosis"]["execution_mode"], "insufficient_input")

            evidence_bundle = memory.get_evidence_bundle(result["case_id"])
            traced_items = evidence_bundle["image_evidence"]["visual_evidence_bundle"]["evidence_items"]
            self.assertEqual(len(traced_items), len(image_bundle["evidence_items"]))
            self.assertEqual(
                evidence_bundle["skill_evidence"]["used_skill"],
                "femoral_head_necrosis_v0.1",
            )

    def test_diagnosis_report_is_bounded_by_missing_and_differential_evidence(self):
        visual_result = {
            "image_path": "output/fake/uploads/fhn_ap.png",
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": "output/fake/uploads/fhn_ap.png",
                "mask_path": "not_generated",
                "overlay_path": "not_generated",
            },
            "requested_targets": [],
            "requested_features": [],
            "visual_evidence": {
                "collapse": False,
                "joint_space_narrowing": False,
                "sclerosis": "候选",
                "cystic_change": "unknown",
                "femoral_head_shape": "unknown",
                "joint_space": "unknown",
                "lesion_mask": "not_generated",
                "confidence": 0.3,
                "texture_abnormality_score": 0.8,
                "lesion_area_ratio": 0.0,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "disease_target": "femoral_head_necrosis",
                "findings": [
                    {
                        "target": "trabecular_blurring",
                        "display_name": "骨小梁模糊",
                        "status": "candidate_present",
                        "diagnosis_usable": False,
                        "diagnosis_usable_level": "exploratory_only",
                        "quality": {"validation_status": "requires_validation"},
                    }
                ],
                "completeness": {
                    "early_osteonecrosis": {
                        "status": "missing",
                        "reason": "X-ray only; requires MRI",
                    }
                },
            },
        }
        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fhn_protocol",
            patient_info={
                "symptoms": ["髋关节疼痛"],
                "risk_factors": ["激素使用史"],
            },
            visual_result=visual_result,
            disease_skill=self.skill,
        )

        for key in [
            "target_disease_assessment",
            "imaging_evidence_summary",
            "quantitative_evidence_summary",
            "differential_considerations",
            "clinical_context_assessment",
            "missing_evidence",
            "modality_limitations",
            "recommendation",
        ]:
            self.assertIn(key, report)
        self.assertEqual(report["target_disease_assessment"]["evidence_status"], "insufficient")
        self.assertFalse(report["clinical_context_assessment"]["can_confirm_without_imaging"])
        self.assertTrue(report["differential_considerations"])
        self.assertTrue(any("MRI" in item for item in report["recommendation"]))
        self.assertNotIn("排除", report["诊断倾向"])

    def test_diagnosis_report_adds_integrated_reasoning_summary_from_multidimensional_evidence(self):
        visual_result = {
            "image_path": "output/fake/uploads/fhn_ap.png",
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": "output/fake/uploads/fhn_ap.png",
                "mask_path": "not_generated",
                "overlay_path": "not_generated",
            },
            "requested_targets": [],
            "requested_features": [],
            "visual_evidence": {
                "collapse": False,
                "joint_space_narrowing": False,
                "sclerosis": "候选",
                "cystic_change": "unknown",
                "femoral_head_shape": "unknown",
                "joint_space": "unknown",
                "lesion_mask": "not_generated",
                "confidence": 0.3,
                "texture_abnormality_score": 0.8,
                "lesion_area_ratio": 0.0,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "disease_target": "femoral_head_necrosis",
                "evidence_items": [
                    {
                        "target": "collapse",
                        "evidence_type": "anatomical_measurement",
                        "execution_mode": "measurement_only",
                        "measurements": {
                            "collapse_depth_mm": None,
                            "measurement_usable": False,
                        },
                        "quality": {"roi_quality": "missing_contour"},
                        "diagnosis_usable": True,
                        "diagnosis_usable_level": "measurement_support",
                        "limitations": ["ROI/contour quality insufficient"],
                    },
                    {
                        "target": "trabecular_blurring",
                        "evidence_type": "image_feature_quantification",
                        "execution_mode": "vlm_only",
                        "measurements": {"trabecular_irregularity_score": 0.82},
                        "quality": {"validation_status": "requires_validation"},
                        "diagnosis_usable": False,
                        "diagnosis_usable_level": "exploratory_only",
                        "limitations": ["Exploratory feature; requires validation"],
                    },
                ],
                "completeness": {
                    "early_osteonecrosis": {
                        "status": "missing",
                        "reason": "X-ray only; requires MRI",
                    }
                },
            },
        }

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fhn_integrated_reasoning",
            patient_info={
                "symptoms": ["髋关节疼痛"],
                "clinical_context": "右髋疼痛，长期激素治疗，偶尔饮酒",
            },
            visual_result=visual_result,
            disease_skill=self.skill,
        )

        summary = report["integrated_reasoning_summary"]
        self.assertEqual(summary["target_disease"], "femoral_head_necrosis")
        self.assertEqual(summary["evidence_status"], "insufficient")
        self.assertFalse(summary["can_confirm_target_disease"])
        self.assertEqual(summary["imaging_support"]["supported_targets"], [])
        self.assertIn("collapse", summary["quantitative_support"]["measurement_targets_not_usable"])
        self.assertIn("trabecular_blurring", summary["quantitative_support"]["exploratory_targets"])
        self.assertIn("corticosteroid_use", summary["clinical_risk_support"]["provided_risk_factors"])
        self.assertIn("early_osteonecrosis", summary["missing_evidence"]["missing_required_targets"])
        self.assertTrue(summary["differential_considerations"]["retained"])
        self.assertTrue(any("MRI" in item for item in summary["recommended_next_step"]))

    def test_diagnosis_report_exposes_structured_clinical_context_bundle(self):
        visual_result = {
            "image_path": "output/fake/uploads/fhn_ap.png",
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": "output/fake/uploads/fhn_ap.png",
                "mask_path": "not_generated",
                "overlay_path": "not_generated",
            },
            "requested_targets": [],
            "requested_features": [],
            "visual_evidence": {
                "disease_target": "femoral_head_necrosis",
                "collapse": False,
                "joint_space_narrowing": False,
                "sclerosis": "unknown",
                "cystic_change": "unknown",
                "femoral_head_shape": "unknown",
                "joint_space": "unknown",
                "lesion_mask": "not_generated",
                "confidence": 0.0,
                "texture_abnormality_score": 0.0,
                "lesion_area_ratio": 0.0,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "evidence_items": [],
                "completeness": {
                    "early_osteonecrosis": {
                        "status": "missing",
                        "reason": "X-ray only; requires MRI",
                    }
                },
            },
        }

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fhn_clinical_bundle",
            patient_info={
                "symptoms": ["右髋疼痛"],
                "clinical_context": "右髋疼痛三个月，长期激素治疗，偶尔饮酒",
                "clinical_context_source": "patient_message",
            },
            visual_result=visual_result,
            disease_skill=self.skill,
        )

        bundle = report["clinical_context_bundle"]
        self.assertEqual(bundle["schema_version"], "clinical_context_bundle.v1")
        self.assertEqual(bundle["source"], "patient_message")
        self.assertIn("clinical_context", bundle["source_fields"])
        self.assertIn("右髋疼痛三个月", bundle["raw_context"])
        self.assertEqual(
            bundle["risk_modifiers"]["provided_risk_factors"],
            ["corticosteroid_use", "alcohol_use"],
        )
        self.assertEqual(bundle["diagnostic_limits"]["diagnosis_usable_level"], "risk_modifier_only")
        self.assertFalse(bundle["diagnostic_limits"]["can_confirm_without_imaging"])
        self.assertIn(
            "clinical_context_bundle",
            report["integrated_reasoning_summary"]["clinical_risk_support"],
        )

    def test_diagnosis_report_preserves_routing_hypotheses_without_treating_them_as_evidence(self):
        visual_result = {
            "image_path": "output/fake/uploads/fhn_ap.png",
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": "output/fake/uploads/fhn_ap.png",
                "mask_path": "not_generated",
                "overlay_path": "not_generated",
            },
            "requested_targets": [],
            "requested_features": [],
            "visual_evidence": {
                "disease_target": "femoral_head_necrosis",
                "collapse": False,
                "joint_space_narrowing": False,
                "sclerosis": "unknown",
                "cystic_change": "unknown",
                "femoral_head_shape": "unknown",
                "joint_space": "unknown",
                "lesion_mask": "not_generated",
                "confidence": 0.0,
                "texture_abnormality_score": 0.0,
                "lesion_area_ratio": 0.0,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "evidence_items": [],
                "completeness": {
                    "early_osteonecrosis": {
                        "status": "missing",
                        "reason": "X-ray only; requires MRI",
                    }
                },
            },
        }
        routing_decision = {
            "primary_hypothesis": "femoral_head_necrosis",
            "clinical_hypotheses": [
                {
                    "disease_key": "femoral_head_necrosis",
                    "role": "primary",
                    "status": "requires_evidence_acquisition",
                    "reason": "Matched hip pain symptom and hip/X-ray clues.",
                },
                {
                    "disease_key": "osteoarthritis_or_degenerative_hip_disease",
                    "role": "differential",
                    "status": "differential_candidate",
                    "reason": "Alternative explanation retained by orchestrator.",
                },
            ],
        }

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fhn_routing_hypotheses",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
            disease_skill=self.skill,
            routing_decision=routing_decision,
        )

        hypothesis_assessment = report["clinical_hypotheses_assessment"]
        self.assertEqual(
            hypothesis_assessment["primary_hypothesis"]["disease_key"],
            "femoral_head_necrosis",
        )
        self.assertEqual(
            hypothesis_assessment["differential_retained"][0]["disease_key"],
            "osteoarthritis_or_degenerative_hip_disease",
        )
        self.assertFalse(hypothesis_assessment["hypotheses_are_diagnosis"])
        self.assertEqual(
            report["target_disease_assessment"]["routing_role"],
            "primary_hypothesis",
        )
        self.assertEqual(
            report["target_disease_assessment"]["evidence_status"],
            "insufficient",
        )

    def test_low_quality_measurement_and_exploratory_quantification_do_not_become_strong_support(self):
        visual_result = {
            "image_path": "output/fake/uploads/fhn_ap.png",
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": "output/fake/uploads/fhn_ap.png",
                "mask_path": "not_generated",
                "overlay_path": "not_generated",
            },
            "requested_targets": [],
            "requested_features": [],
            "visual_evidence": {
                "collapse": False,
                "joint_space_narrowing": False,
                "sclerosis": "候选",
                "cystic_change": "unknown",
                "femoral_head_shape": "unknown",
                "joint_space": "unknown",
                "lesion_mask": "not_generated",
                "confidence": 0.3,
                "texture_abnormality_score": 0.8,
                "lesion_area_ratio": 0.0,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "disease_target": "femoral_head_necrosis",
                "evidence_items": [
                    {
                        "target": "collapse",
                        "evidence_type": "anatomical_measurement",
                        "execution_mode": "measurement_only",
                        "measurements": {
                            "collapse_depth": None,
                            "measurement_usable": False,
                        },
                        "quality": {"roi_quality": "missing_contour"},
                        "diagnosis_usable": False,
                        "diagnosis_usable_level": "not_usable",
                        "limitations": ["ROI/contour quality insufficient"],
                    },
                    {
                        "target": "trabecular_blurring",
                        "evidence_type": "image_feature_quantification",
                        "execution_mode": "vlm_only",
                        "measurements": {"trabecular_irregularity_score": 0.82},
                        "quality": {"validation_status": "requires_validation"},
                        "diagnosis_usable": False,
                        "diagnosis_usable_level": "exploratory_only",
                        "limitations": ["Exploratory feature; requires validation"],
                    },
                ],
                "completeness": {},
            },
        }

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fhn_safety",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
            disease_skill=self.skill,
        )

        quantitative = report["quantitative_evidence_summary"]
        self.assertEqual(quantitative["strong_quantitative_support_count"], 0)
        self.assertEqual(
            report["target_disease_assessment"]["evidence_status"],
            "insufficient",
        )
        self.assertIn("collapse", report["target_disease_assessment"]["nonspecific_or_unusable_findings"])
        self.assertIn("trabecular_blurring", report["target_disease_assessment"]["nonspecific_or_unusable_findings"])

    def test_candidate_mask_without_qc_does_not_become_target_disease_support(self):
        visual_result = {
            "image_path": "output/fake/uploads/fhn_ap.png",
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": "output/fake/uploads/fhn_ap.png",
                "mask_path": "not_generated",
                "overlay_path": "not_generated",
            },
            "requested_targets": [],
            "requested_features": [],
            "visual_evidence": {
                "collapse": False,
                "joint_space_narrowing": False,
                "sclerosis": "候选",
                "cystic_change": "unknown",
                "femoral_head_shape": "unknown",
                "joint_space": "unknown",
                "lesion_mask": "not_generated",
                "confidence": 0.3,
                "texture_abnormality_score": 0.0,
                "lesion_area_ratio": 0.0,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "disease_target": "femoral_head_necrosis",
                "evidence_items": [
                    {
                        "target": "sclerotic_band",
                        "evidence_type": "candidate_mask",
                        "execution_mode": "vlm_plus_segmenter",
                        "visual_observation": {"status": "candidate_present"},
                        "segmentation": {"status": "candidate_only"},
                        "measurements": {"area_px": 120},
                        "quality": {"qc_status": "candidate_only"},
                        "diagnosis_usable": True,
                        "diagnosis_usable_level": "candidate_support",
                        "limitations": ["Candidate mask requires QC before diagnosis use"],
                    }
                ],
                "completeness": {},
            },
        }

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fhn_candidate_qc",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
            disease_skill=self.skill,
        )

        assessment = report["target_disease_assessment"]
        self.assertEqual(assessment["evidence_status"], "insufficient")
        self.assertNotIn("sclerotic_band", assessment["supports_target_disease"])
        self.assertIn("sclerotic_band", assessment["nonspecific_or_unusable_findings"])

    def test_measurement_support_requires_measurement_usable_true(self):
        visual_result = {
            "image_path": "output/fake/uploads/fhn_ap.png",
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": "output/fake/uploads/fhn_ap.png",
                "mask_path": "not_generated",
                "overlay_path": "not_generated",
            },
            "requested_targets": [],
            "requested_features": [],
            "visual_evidence": {
                "collapse": False,
                "joint_space_narrowing": False,
                "sclerosis": "unknown",
                "cystic_change": "unknown",
                "femoral_head_shape": "unknown",
                "joint_space": "unknown",
                "lesion_mask": "not_generated",
                "confidence": 0.3,
                "texture_abnormality_score": 0.0,
                "lesion_area_ratio": 0.0,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "disease_target": "femoral_head_necrosis",
                "evidence_items": [
                    {
                        "target": "collapse",
                        "evidence_type": "anatomical_measurement",
                        "execution_mode": "measurement_only",
                        "visual_observation": {"status": "unassessed"},
                        "measurements": {
                            "collapse_depth_mm": None,
                            "measurement_usable": False,
                        },
                        "quality": {"roi_quality": "missing_contour"},
                        "diagnosis_usable": True,
                        "diagnosis_usable_level": "measurement_support",
                        "limitations": ["ROI/contour quality insufficient"],
                    }
                ],
                "completeness": {},
            },
        }

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fhn_measurement_gate",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
            disease_skill=self.skill,
        )

        assessment = report["target_disease_assessment"]
        self.assertEqual(assessment["evidence_status"], "insufficient")
        self.assertNotIn("collapse", assessment["supports_target_disease"])
        self.assertIn("collapse", assessment["nonspecific_or_unusable_findings"])


if __name__ == "__main__":
    unittest.main()
