import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory.memory_manager import MemoryManager


class MemoryManagerQueryTest(unittest.TestCase):
    def _save_case(
        self,
        memory: MemoryManager,
        case_id: str,
        disease: str,
        patient_id: str = "patient_001",
    ) -> None:
        memory.save_case_memory(
            case_id=case_id,
            patient_memory={
                "case_id": case_id,
                "patient_message": "患者描述",
                "patient_id": patient_id,
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "symptoms": ["髋关节疼痛"],
                "intent": "diagnosis",
            },
            image_memory={
                "case_id": case_id,
                "image_id": "image_001",
                "image_path": "data/images/demo_xray.png",
                "modality": "xray",
                "body_part": "hip",
                "image_outputs": {
                    "original_image_path": "data/images/demo_xray.png",
                    "mask_path": "data/masks/demo_xray_mask.png",
                    "overlay_path": "data/overlays/demo_xray_overlay.png",
                },
                "visual_features": {
                    "lesion_detected": True,
                    "segmentation_quality": "simulated",
                    "measurements": {"lesion_area_ratio": 0.13},
                    "completeness": {
                        "whole_lesion": {"status": "supported", "reason": "xray available"},
                        "enhancement": {"status": "missing", "reason": "Requires contrast modality"},
                    },
                },
            },
            knowledge_memory={
                "disease": disease,
                "knowledge_id": f"{disease}_knowledge_v0.1",
                "selected_knowledge": f"{disease}_knowledge_v0.1",
                "knowledge_type": "guideline_based",
                "evidence_level": "high",
                "source": "test source",
                "routing_decision": {
                    "selected_knowledge": f"{disease}_knowledge_v0.1",
                    "selected_vision_mode": "ground_truth",
                    "source": "auto",
                    "agent_scope": "orchestrator_api",
                    "knowledge_builder_action": "load_existing_knowledge",
                    "primary_hypothesis": "femoral_head_necrosis",
                    "differential_knowledge_candidates": [
                        "osteoarthritis_or_degenerative_hip_disease",
                    ],
                    "clinical_hypotheses": [
                        {
                            "disease_key": "femoral_head_necrosis",
                            "role": "primary",
                            "status": "requires_differential_review",
                            "reason": "Matched hip pain symptom and hip/X-ray clues.",
                        },
                        {
                            "disease_key": "osteoarthritis_or_degenerative_hip_disease",
                            "role": "differential",
                            "status": "differential_candidate",
                            "reason": "Alternative explanation retained by orchestrator.",
                        },
                    ],
                    "initial_evidence_status": "requires_differential_review",
                    "routing_evidence_status": "requires_differential_review",
                },
                "guideline_evidence": {"citations": [{"title": "test guideline"}]},
                "quality_control": {
                    "formal_knowledge_status": "formal_ready",
                    "visual_protocol_status": "valid",
                    "visual_protocol_errors": [],
                    "visual_protocol_warnings": [],
                },
                "alignment_plan": {
                    "analysis_status": "partial_evidence",
                    "diagnosis_scope": {
                        "blocked": ["不能把缺失增强证据解释为阴性"],
                    },
                    "required_next_images": [
                        {
                            "modality": "MRI",
                            "region": "target region",
                            "reason": "补充关键影像",
                        }
                    ],
                },
            },
            reasoning_memory={
                "case_id": case_id,
                "used_knowledge": f"{disease}_knowledge_v0.1",
                "report": {"case_id": case_id, "诊断倾向": "测试诊断"},
                "key_evidence": ["证据 A"],
                "diagnostic_result": "测试诊断",
                "diagnostic_tendency": "测试诊断",
                "uncertainty": ["不确定性 A"],
                "follow_up": ["复查建议 A"],
                "treatment_advice": ["治疗建议 A"],
                "alignment_plan": {
                    "analysis_status": "partial_evidence",
                    "diagnosis_scope": {
                        "blocked": ["不能把缺失增强证据解释为阴性"],
                    },
                    "required_next_images": [
                        {
                            "modality": "MRI",
                            "region": "target region",
                            "reason": "补充关键影像",
                        }
                    ],
                },
            },
        )

    def test_save_case_memory_writes_memory_v1_schema(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")

            record = memory.get_case_by_id("case_001")

            self.assertEqual(record["schema_version"], "memory_v1")
            self.assertEqual(
                record["memory_types"],
                ["patient_memory", "image_memory", "knowledge_memory", "reasoning_memory"],
            )
            self.assertIn("created_at", record)
            self.assertIn("updated_at", record)
            self.assertEqual(record["patient_memory"]["patient_id"], "patient_001")
            self.assertEqual(record["patient_memory"]["symptoms"], ["髋关节疼痛"])
            self.assertEqual(record["patient_memory"]["qa_history"], [])
            self.assertEqual(record["image_memory"]["measurements"], {"lesion_area_ratio": 0.13})
            self.assertEqual(
                record["image_memory"]["completeness"]["enhancement"]["status"],
                "missing",
            )
            self.assertEqual(record["image_memory"]["segmentation_quality"], "simulated")

    def test_get_case_by_id_returns_case_memory(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")

            record = memory.get_case_by_id("case_001")

            self.assertEqual(record["case_id"], "case_001")
            self.assertEqual(record["knowledge_memory"]["disease"], "股骨头坏死")

    def test_load_case_memory_normalizes_legacy_case_without_rewriting_it(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            legacy_path = Path(tmpdir) / "cases" / "case_legacy.json"
            legacy_record = {
                "case_id": "case_legacy",
                "patient_memory": {
                    "case_id": "case_legacy",
                    "patient_message": "旧病例描述",
                    "patient_profile": {"symptoms": ["头痛"]},
                },
                "image_memory": {
                    "case_id": "case_legacy",
                    "image_path": "legacy.png",
                    "modality": "MRI",
                    "body_part": "brain",
                    "visual_features": {
                        "measurements": {"whole_tumor_volume_ml": 12.5},
                        "completeness": {
                            "tumor_core": {"status": "missing", "reason": "Requires T1"}
                        },
                        "segmentation_quality": "legacy_quality",
                    },
                },
                "knowledge_memory": {"disease": "成人弥漫性胶质瘤", "knowledge_id": "diffuse_glioma_brats_v0.1"},
                "reasoning_memory": {
                    "key_evidence": ["旧证据"],
                    "diagnostic_result": "旧诊断",
                    "uncertainty": ["旧不确定性"],
                },
                "qa_memory": [
                    {
                        "question": "旧问题",
                        "answer": "旧回答",
                        "answered_at": "2026-05-23T10:00:00",
                    }
                ],
                "saved_at": "2026-05-23T10:00:00",
            }
            legacy_path.write_text(json.dumps(legacy_record, ensure_ascii=False), encoding="utf-8")

            record = memory.get_case_by_id("case_legacy")
            persisted = json.loads(legacy_path.read_text(encoding="utf-8"))

            self.assertEqual(record["schema_version"], "memory_v1")
            self.assertEqual(record["created_at"], "2026-05-23T10:00:00")
            self.assertEqual(record["patient_memory"]["patient_info"], {"symptoms": ["头痛"]})
            self.assertEqual(record["patient_memory"]["qa_history"][0]["question"], "旧问题")
            self.assertEqual(record["image_memory"]["measurements"], {"whole_tumor_volume_ml": 12.5})
            self.assertEqual(record["image_memory"]["segmentation_quality"], "legacy_quality")
            self.assertNotIn("schema_version", persisted)

    def test_find_cases_by_disease_returns_matching_knowledge_memories(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")
            self._save_case(memory, "case_002", "成人弥漫性胶质瘤")
            self._save_case(memory, "case_003", "股骨头坏死")

            records = memory.find_cases_by_disease("股骨头坏死")

            self.assertEqual([record["case_id"] for record in records], ["case_001", "case_003"])
            self.assertTrue(all(record["knowledge_memory"]["disease"] == "股骨头坏死" for record in records))

    def test_find_cases_by_patient_and_latest_case_use_updated_at_order(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死", patient_id="patient_a")
            self._save_case(memory, "case_002", "成人弥漫性胶质瘤", patient_id="patient_b")
            self._save_case(memory, "case_003", "股骨头坏死", patient_id="patient_a")

            cases = memory.find_cases_by_patient("patient_a")
            latest = memory.get_latest_case_for_patient("patient_a")
            recent = memory.list_recent_cases(limit=2)

            self.assertEqual([record["case_id"] for record in cases], ["case_001", "case_003"])
            self.assertEqual(latest["case_id"], "case_003")
            self.assertEqual([record["case_id"] for record in recent], ["case_003", "case_002"])

    def test_get_evidence_bundle_returns_common_trace_payload(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")

            bundle = memory.get_evidence_bundle("case_001")

            self.assertEqual(bundle["case_id"], "case_001")
            self.assertEqual(bundle["patient_context"]["patient_id"], "patient_001")
            self.assertEqual(bundle["image_evidence"]["modality"], "xray")
            self.assertEqual(
                bundle["image_evidence"]["completeness"]["enhancement"]["status"],
                "missing",
            )
            self.assertEqual(bundle["knowledge_evidence"]["knowledge_type"], "guideline_based")
            self.assertEqual(bundle["reasoning_evidence"]["diagnostic_tendency"], "测试诊断")
            self.assertEqual(
                bundle["missing_or_unassessed"]["image_memory"]["enhancement"]["status"],
                "missing",
            )
            self.assertTrue(bundle["quality_warnings"])

    def test_get_evidence_bundle_exposes_clinical_context_evidence(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            memory.save_case_memory(
                case_id="case_clinical_context",
                patient_memory={
                    "case_id": "case_clinical_context",
                    "patient_message": "右髋疼痛，长期激素治疗，偶尔饮酒",
                    "patient_id": "patient_001",
                    "patient_info": {
                        "symptoms": ["髋关节疼痛"],
                        "clinical_context": "右髋疼痛，长期激素治疗，偶尔饮酒",
                        "clinical_context_source": "patient_message",
                        "structured_clinical_context": {
                            "schema_version": "clinical_context_extraction.v1",
                            "source": "patient_message",
                            "source_text": "右髋疼痛三个月，走路后加重，长期激素治疗，偶尔饮酒",
                            "fields": {
                                "symptoms": {"status": "present", "values": ["hip_pain"]},
                                "duration": {"status": "present", "value": "三个月"},
                                "laterality": {"status": "present", "value": "right"},
                                "pain_location": {"status": "present", "value": "hip"},
                                "aggravating_factors": {
                                    "status": "present",
                                    "values": ["walking_or_activity"],
                                },
                                "steroid_use": {"status": "present", "value": True},
                                "alcohol_use": {"status": "present", "value": True},
                                "trauma_history": {"status": "missing", "value": "unknown"},
                            },
                            "provided_risk_factors": [
                                "corticosteroid_use",
                                "alcohol_use",
                            ],
                            "missing_fields": ["trauma_history"],
                            "risk_factor_role": "suspicion_modifier_only",
                        },
                    },
                    "symptoms": ["髋关节疼痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "case_id": "case_clinical_context",
                    "image_path": "data/images/fhn_xray.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "image_outputs": {},
                    "visual_features": {},
                },
                knowledge_memory={
                    "selected_knowledge": "femoral_head_necrosis",
                    "selected_vision_mode": "no_mask_knowledge",
                    "knowledge_type": "guideline_based",
                    "routing_decision": {},
                    "alignment_plan": {},
                },
                reasoning_memory={
                    "case_id": "case_clinical_context",
                    "diagnostic_tendency": "疑似股骨头坏死，但证据不足",
                    "report": {
                        "clinical_context_assessment": {
                            "provided_risk_factors": [
                                "corticosteroid_use",
                                "alcohol_use",
                            ],
                            "missing_clinical_context": [
                                "trauma_history",
                            ],
                            "can_confirm_without_imaging": False,
                            "role": "clinical risk changes suspicion level only; it cannot confirm ONFH without imaging evidence.",
                            "suspicion_effect": {
                                "direction": "increases_suspicion",
                                "basis": [
                                    "corticosteroid_use",
                                    "alcohol_use",
                                ],
                                "role": "suspicion_modifier_only",
                            },
                        }
                    },
                    "key_evidence": [],
                    "uncertainty": [],
                    "follow_up": [],
                    "treatment_advice": [],
                },
            )

            bundle = memory.get_evidence_bundle("case_clinical_context")

            clinical = bundle["clinical_context_evidence"]
            self.assertEqual(
                clinical["source"],
                "patient_message",
            )
            self.assertEqual(clinical["schema_version"], "clinical_context_bundle.v1")
            self.assertIn("长期激素治疗", clinical["raw_context"])
            self.assertIn("clinical_context", clinical["source_fields"])
            self.assertEqual(
                clinical["provided_risk_factors"],
                ["corticosteroid_use", "alcohol_use"],
            )
            self.assertEqual(
                clinical["risk_modifiers"]["provided_risk_factors"],
                ["corticosteroid_use", "alcohol_use"],
            )
            self.assertEqual(
                clinical["missing_clinical_context"],
                ["trauma_history"],
            )
            self.assertFalse(clinical["can_confirm_without_imaging"])
            self.assertEqual(
                clinical["diagnosis_usable_level"],
                "risk_modifier_only",
            )
            self.assertEqual(
                clinical["diagnostic_limits"]["diagnosis_usable_level"],
                "risk_modifier_only",
            )
            self.assertEqual(
                clinical["structured_context"]["fields"]["laterality"]["value"],
                "right",
            )
            self.assertEqual(
                clinical["structured_context"]["fields"]["aggravating_factors"]["values"],
                ["walking_or_activity"],
            )
            self.assertEqual(
                clinical["source_trace"]["structured_context_source"],
                "patient_message",
            )
            self.assertIn(
                "source_text",
                clinical["source_trace"],
            )
            self.assertEqual(
                clinical["suspicion_effect"]["role"],
                "suspicion_modifier_only",
            )

    def test_get_evidence_bundle_exposes_differential_reasoning_evidence(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            memory.save_case_memory(
                case_id="case_differential_context",
                patient_memory={
                    "case_id": "case_differential_context",
                    "patient_message": "左髋疼痛，X 光有关节间隙变窄和退变",
                    "patient_id": "patient_001",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "symptoms": ["髋关节疼痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "case_id": "case_differential_context",
                    "image_path": "data/images/fhn_xray.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "image_outputs": {},
                    "visual_features": {},
                    "completeness": {
                        "early_osteonecrosis": {
                            "status": "missing",
                            "reason": "X-ray only; requires MRI",
                        }
                    },
                },
                knowledge_memory={
                    "selected_knowledge": "femoral_head_necrosis",
                    "selected_vision_mode": "no_mask_knowledge",
                    "knowledge_type": "guideline_based",
                    "routing_decision": {
                        "primary_hypothesis": "femoral_head_necrosis",
                        "differential_knowledge_candidates": [
                            "osteoarthritis_or_degenerative_hip_disease",
                        ],
                        "routing_evidence_status": "requires_differential_review",
                    },
                    "alignment_plan": {},
                },
                reasoning_memory={
                    "case_id": "case_differential_context",
                    "diagnostic_tendency": "疑似股骨头坏死，但需鉴别退变性髋关节病变",
                    "report": {
                        "differential_considerations": [
                            {
                                "condition": "osteoarthritis_or_degenerative_hip_disease",
                                "display_name": "退变性髋关节病变",
                                "status": "cannot_exclude",
                                "reason": "当前存在非特异观察和缺失证据，需保留鉴别。",
                            }
                        ]
                    },
                    "key_evidence": [],
                    "uncertainty": [],
                    "follow_up": [],
                    "treatment_advice": [],
                },
            )

            bundle = memory.get_evidence_bundle("case_differential_context")

            differential = bundle["differential_reasoning_evidence"]
            self.assertEqual(
                differential["evidence_type"],
                "differential_reasoning",
            )
            self.assertEqual(
                differential["primary_hypothesis"],
                "femoral_head_necrosis",
            )
            self.assertEqual(
                differential["routing_evidence_status"],
                "requires_differential_review",
            )
            self.assertEqual(
                differential["diagnosis_usable_level"],
                "bounded_differential_only",
            )
            self.assertFalse(differential["can_replace_primary_diagnosis"])
            self.assertEqual(
                differential["considerations"][0]["condition"],
                "osteoarthritis_or_degenerative_hip_disease",
            )

    def test_get_evidence_bundle_exposes_quantitative_evidence(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            measurement_item = {
                "target": "collapse",
                "evidence_type": "anatomical_measurement",
                "execution_mode": "measurement_only",
                "measurements": {
                    "collapse_depth_mm": None,
                    "measurement_usable": False,
                    "reason": "ROI/contour quality insufficient",
                },
                "quality": {"status": "low_quality"},
                "diagnosis_usable": False,
                "diagnosis_usable_level": "not_usable",
            }
            exploratory_item = {
                "target": "trabecular_irregularity_score",
                "evidence_type": "image_feature_quantification",
                "execution_mode": "vlm_only",
                "measurements": {
                    "score": None,
                    "measurement_usable": False,
                },
                "quality": {"status": "requires_validation"},
                "diagnosis_usable": False,
                "diagnosis_usable_level": "exploratory_only",
            }
            memory.save_case_memory(
                case_id="case_quantitative_context",
                patient_memory={
                    "case_id": "case_quantitative_context",
                    "patient_message": "右髋疼痛，上传 X 光",
                    "patient_id": "patient_001",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "symptoms": ["髋关节疼痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "case_id": "case_quantitative_context",
                    "image_path": "data/images/fhn_xray.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "image_outputs": {},
                    "visual_features": {},
                    "visual_evidence_bundle": {
                        "schema_version": "visual_evidence_bundle.v2",
                        "evidence_items": [measurement_item, exploratory_item],
                    },
                },
                knowledge_memory={
                    "selected_knowledge": "femoral_head_necrosis",
                    "selected_vision_mode": "no_mask_knowledge",
                    "knowledge_type": "guideline_based",
                    "routing_decision": {},
                    "alignment_plan": {},
                },
                reasoning_memory={
                    "case_id": "case_quantitative_context",
                    "diagnostic_tendency": "疑似股骨头坏死，但量化证据不足",
                    "report": {
                        "quantitative_evidence_summary": {
                            "measurement_items": [measurement_item],
                            "exploratory_features": [exploratory_item],
                            "strong_quantitative_support_count": 0,
                        }
                    },
                    "key_evidence": [],
                    "uncertainty": [],
                    "follow_up": [],
                    "treatment_advice": [],
                },
            )

            bundle = memory.get_evidence_bundle("case_quantitative_context")

            quantitative = bundle["quantitative_evidence"]
            self.assertEqual(
                quantitative["evidence_type"],
                "quantitative_evidence",
            )
            self.assertEqual(quantitative["strong_quantitative_support_count"], 0)
            self.assertEqual(len(quantitative["measurement_items"]), 1)
            self.assertEqual(len(quantitative["exploratory_features"]), 1)
            self.assertFalse(quantitative["can_confirm_diagnosis"])
            self.assertEqual(
                quantitative["measurement_items"][0]["measurements"]["measurement_usable"],
                False,
            )
            self.assertEqual(
                quantitative["exploratory_features"][0]["diagnosis_usable_level"],
                "exploratory_only",
            )

    def test_get_evidence_bundle_exposes_integrated_reasoning_evidence(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            memory.save_case_memory(
                case_id="case_integrated_reasoning",
                patient_memory={
                    "case_id": "case_integrated_reasoning",
                    "patient_message": "右髋疼痛，上传 X 光",
                    "patient_id": "patient_001",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "symptoms": ["髋关节疼痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "case_id": "case_integrated_reasoning",
                    "image_path": "data/images/fhn_xray.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "image_outputs": {},
                    "visual_features": {},
                },
                knowledge_memory={
                    "selected_knowledge": "femoral_head_necrosis",
                    "selected_vision_mode": "no_mask_knowledge",
                    "knowledge_type": "guideline_based",
                    "routing_decision": {},
                    "alignment_plan": {},
                },
                reasoning_memory={
                    "case_id": "case_integrated_reasoning",
                    "diagnostic_tendency": "影像证据不足，需进一步评估",
                    "report": {
                        "integrated_reasoning_summary": {
                            "target_disease": "femoral_head_necrosis",
                            "evidence_status": "insufficient",
                            "can_confirm_target_disease": False,
                            "imaging_support": {
                                "supported_targets": [],
                                "nonspecific_or_unusable_targets": ["collapse"],
                                "missing_targets": ["early_osteonecrosis"],
                                "usable_item_count": 0,
                            },
                            "quantitative_support": {
                                "strong_quantitative_support_count": 0,
                                "measurement_targets_not_usable": ["collapse"],
                                "exploratory_targets": ["trabecular_blurring"],
                            },
                            "clinical_risk_support": {
                                "provided_risk_factors": ["corticosteroid_use"],
                                "missing_clinical_context": ["trauma_history"],
                                "can_confirm_without_imaging": False,
                            },
                            "missing_evidence": {
                                "missing_required_targets": ["early_osteonecrosis"],
                            },
                            "recommended_next_step": [
                                "建议完善双髋 MRI T1/T2/STIR 检查。",
                            ],
                        }
                    },
                    "key_evidence": [],
                    "uncertainty": [],
                    "follow_up": [],
                    "treatment_advice": [],
                },
            )

            bundle = memory.get_evidence_bundle("case_integrated_reasoning")

            integrated = bundle["integrated_reasoning_evidence"]
            self.assertEqual(integrated["evidence_type"], "integrated_reasoning")
            self.assertEqual(integrated["target_disease"], "femoral_head_necrosis")
            self.assertEqual(integrated["evidence_status"], "insufficient")
            self.assertFalse(integrated["can_confirm_target_disease"])
            self.assertEqual(
                integrated["diagnosis_usable_level"],
                "bounded_summary_only",
            )
            self.assertFalse(integrated["can_create_new_evidence"])
            self.assertIn(
                "early_osteonecrosis",
                integrated["missing_required_targets"],
            )
            self.assertIn(
                "collapse",
                integrated["measurement_targets_not_usable"],
            )
            self.assertIn(
                "trabecular_blurring",
                integrated["exploratory_targets"],
            )
            self.assertTrue(any("MRI" in item for item in integrated["recommended_next_step"]))

    def test_get_evidence_bundle_builds_lesion_gallery_from_visual_usage(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            memory.save_case_memory(
                case_id="case_001",
                patient_memory={
                    "patient_message": "请分析",
                    "patient_info": {},
                    "symptoms": [],
                    "intent": "diagnosis",
                },
                image_memory={
                    "image_path": "output/fake/uploads/fhn.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "image_outputs": {},
                    "visual_evidence_bundle": {
                        "schema_version": "visual_evidence_bundle.v1",
                        "findings": [
                            {
                                "finding_id": "finding_used",
                                "target": "sclerotic_band",
                                "display_name": "硬化带",
                                "status": "candidate_present",
                                "regions": [
                                    {
                                        "region_id": "r1",
                                        "comparison_path": "output/fake/used_comparison.png",
                                        "overlay_path": "output/fake/used_overlay.png",
                                        "mask_path": "output/fake/used_mask.png",
                                        "area_px": 120,
                                        "area_ratio_in_image": 0.12,
                                        "laterality": "image_left",
                                    }
                                ],
                            },
                            {
                                "finding_id": "finding_excluded",
                                "target": "cystic_change",
                                "display_name": "囊性变",
                                "status": "candidate_present",
                                "regions": [
                                    {
                                        "region_id": "r1",
                                        "comparison_path": "output/fake/excluded_comparison.png",
                                        "area_px": 80,
                                        "laterality": "image_left",
                                    }
                                ],
                            },
                        ],
                    },
                },
                knowledge_memory={
                    "selected_knowledge": "femoral_head_necrosis",
                    "knowledge_type": "guideline_based",
                },
                reasoning_memory={
                    "diagnostic_tendency": "疑似",
                    "key_evidence": [],
                    "uncertainty": [],
                    "follow_up": [],
                    "treatment_advice": [],
                    "visual_fact_usage": {
                        "used": [
                            {
                                "finding_id": "finding_used",
                                "target": "sclerotic_band",
                                "summary_text": "image_left; 硬化带; candidate_present",
                            }
                        ],
                        "excluded": [
                            {
                                "finding_id": "finding_excluded",
                                "target": "cystic_change",
                                "exclusion_reason": "non_independent_evidence",
                            }
                        ],
                        "used_count": 1,
                        "excluded_count": 1,
                    },
                },
            )

            gallery = memory.get_evidence_bundle("case_001")["lesion_gallery"]

            self.assertEqual(gallery["schema_version"], "lesion_gallery.v1")
            self.assertEqual(gallery["used_count"], 1)
            self.assertEqual(gallery["excluded_count"], 1)
            self.assertEqual(gallery["items"][0]["usage"]["status"], "used")
            self.assertEqual(gallery["items"][0]["image_paths"]["comparison_path"], "output/fake/used_comparison.png")
            self.assertEqual(gallery["items"][1]["usage"]["status"], "excluded")
            self.assertEqual(gallery["items"][1]["usage"]["reason"], "non_independent_evidence")
            audit = memory.build_audit_summary("case_001")
            self.assertEqual(audit["lesion_gallery_summary"]["item_count"], 2)
            self.assertEqual(audit["lesion_gallery_summary"]["used_count"], 1)
            self.assertEqual(audit["lesion_gallery_summary"]["excluded_count"], 1)
            self.assertEqual(audit["lesion_gallery_summary"]["comparison_artifact_count"], 2)
            self.assertEqual(
                audit["agent_io_summary"]["VisionAgent"]["lesion_gallery_summary"][
                    "item_count"
                ],
                2,
            )
            self.assertEqual(
                audit["agent_io_summary"]["MemoryManager"]["output"]["lesion_gallery_status"],
                "available",
            )
            self.assertEqual(
                audit["memory_type_details"]["image_memory"]["lesion_gallery_item_count"],
                2,
            )
            replay = memory.build_case_replay("case_001")
            visual_step = next(
                step for step in replay["steps"] if step["event"] == "visual_evidence"
            )
            audit_step = next(
                step for step in replay["steps"] if step["event"] == "memory_audit"
            )
            self.assertEqual(visual_step["lesion_gallery_summary"]["item_count"], 2)
            self.assertEqual(audit_step["lesion_gallery_summary"]["used_count"], 1)

    def test_lesion_gallery_preserves_multiview_source_context(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            memory.save_case_memory(
                case_id="case_multiview_gallery",
                patient_memory={
                    "patient_message": "请分析双体位髋关节 X 光",
                    "patient_info": {},
                    "symptoms": ["髋关节疼痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "image_path": "output/fake/uploads/fhn_ap.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "image_outputs": {},
                    "visual_evidence_bundle": {
                        "schema_version": "visual_evidence_bundle.v2",
                        "findings": [
                            {
                                "finding_id": "image_001_sclerotic_band",
                                "image_id": "image_001",
                                "view_hint": "ap_pelvis",
                                "target": "sclerotic_band",
                                "display_name": "硬化带",
                                "status": "candidate_present",
                                "regions": [
                                    {
                                        "region_id": "r1",
                                        "comparison_path": "output/fake/ap_comparison.png",
                                    }
                                ],
                            },
                            {
                                "finding_id": "image_002_cystic_change",
                                "image_id": "image_002",
                                "view_hint": "frog_lateral",
                                "target": "cystic_change",
                                "display_name": "囊性变",
                                "status": "candidate_present",
                                "regions": [
                                    {
                                        "region_id": "r1",
                                        "comparison_path": "output/fake/frog_comparison.png",
                                    }
                                ],
                            },
                        ],
                    },
                },
                knowledge_memory={
                    "selected_knowledge": "femoral_head_necrosis",
                    "knowledge_type": "guideline_based",
                },
                reasoning_memory={
                    "diagnostic_tendency": "疑似",
                    "key_evidence": [],
                    "uncertainty": [],
                    "follow_up": [],
                    "treatment_advice": [],
                    "visual_fact_usage": {
                        "used": [
                            {
                                "finding_id": "image_001_sclerotic_band",
                                "image_id": "image_001",
                                "view_hint": "ap_pelvis",
                                "target": "sclerotic_band",
                                "summary_text": "骨盆正位/AP：硬化带",
                            },
                            {
                                "finding_id": "image_002_cystic_change",
                                "image_id": "image_002",
                                "view_hint": "frog_lateral",
                                "target": "cystic_change",
                                "summary_text": "蛙式侧位：囊性变",
                            },
                        ],
                        "excluded": [],
                        "used_count": 2,
                        "excluded_count": 0,
                    },
                },
            )

            gallery = memory.get_evidence_bundle("case_multiview_gallery")["lesion_gallery"]

            self.assertEqual(
                [(item.get("image_id"), item.get("view_hint")) for item in gallery["items"]],
                [("image_001", "ap_pelvis"), ("image_002", "frog_lateral")],
            )
            self.assertEqual(
                [item.get("view_label") for item in gallery["items"]],
                ["骨盆正位/AP", "蛙式侧位"],
            )

    def test_append_qa_memory_persists_follow_up_history(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")

            memory.append_qa_memory(
                case_id="case_001",
                question="你刚才说哪里异常？",
                answer="主要依据 xray hip 影像记录：证据 A。",
            )

            record = memory.get_case_by_id("case_001")
            self.assertEqual(len(record["patient_memory"]["qa_history"]), 1)
            self.assertEqual(record["patient_memory"]["qa_history"][0]["question"], "你刚才说哪里异常？")
            self.assertIn("xray hip", record["patient_memory"]["qa_history"][0]["answer"])
            self.assertEqual(
                record["patient_memory"]["qa_history"][0]["referenced_case_id"],
                "case_001",
            )
            self.assertTrue(record["patient_memory"]["qa_history"][0]["evidence_bundle_used"])
            self.assertEqual(record["qa_memory"], record["patient_memory"]["qa_history"])

    def test_build_audit_summary_includes_follow_up_qa_agent_after_qa(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")
            memory.append_qa_memory(
                case_id="case_001",
                question="增强缺失是不是阴性？",
                answer="不是。增强证据缺失只能说明需要补充检查，不能当作阴性。",
                llm_used=True,
            )

            audit = memory.build_audit_summary("case_001")

            self.assertEqual(audit["agents_traced"][-1], "GaoDoctorAgent QA")
            self.assertEqual(
                list(audit["agent_io_summary"].keys()),
                audit["agents_traced"],
            )
            self.assertEqual(
                audit["agent_io_summary"]["GaoDoctorAgent QA"]["input"],
                "增强缺失是不是阴性？",
            )
            self.assertTrue(
                audit["agent_io_summary"]["GaoDoctorAgent QA"]["output"]["evidence_bundle_used"]
            )
            self.assertEqual(audit["qa_safety"]["qa_history_count"], 1)
            self.assertEqual(audit["qa_safety"]["llm_used_count"], 1)
            self.assertEqual(audit["qa_safety"]["evidence_bundle_used_count"], 1)
            self.assertEqual(
                audit["memory_type_details"]["patient_memory"]["qa_history_count"],
                1,
            )

    def test_build_audit_summary_writes_fake_output_report(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")

            audit = memory.build_audit_summary("case_001")

            audit_path = Path("output/fake/memory_audit/case_001_audit.json")
            self.assertTrue(audit_path.exists())
            self.assertEqual(audit["case_id"], "case_001")
            self.assertEqual(audit["schema_version"], "memory_v1")
            self.assertEqual(
                audit["agents_traced"],
                [
                    "GaoDoctorAgent",
                    "KnowledgeBuilderAgent",
                    "VisionAgent",
                    "DiagnosisDoctorAgent",
                    "MemoryManager",
                ],
            )
            self.assertTrue(audit["memory_completeness"]["patient_memory"])
            self.assertTrue(audit["memory_completeness"]["image_memory"])
            self.assertTrue(audit["memory_completeness"]["knowledge_memory"])
            self.assertTrue(audit["memory_completeness"]["reasoning_memory"])
            self.assertIn("enhancement", audit["missing_or_unassessed"]["image_memory"])
            self.assertEqual(audit["memory_type_details"]["knowledge_memory"]["selected_knowledge"], "股骨头坏死_knowledge_v0.1")
            self.assertEqual(
                audit["memory_type_details"]["knowledge_memory"]["routing_agent_scope"],
                "orchestrator_api",
            )
            self.assertEqual(
                audit["memory_type_details"]["knowledge_memory"]["primary_hypothesis"],
                "femoral_head_necrosis",
            )
            self.assertEqual(
                audit["memory_type_details"]["knowledge_memory"]["routing_evidence_status"],
                "requires_differential_review",
            )
            self.assertEqual(
                audit["memory_type_details"]["knowledge_memory"]["differential_knowledge_candidates"],
                ["osteoarthritis_or_degenerative_hip_disease"],
            )
            self.assertEqual(
                audit["memory_type_details"]["knowledge_memory"]["clinical_hypotheses_count"],
                2,
            )
            self.assertEqual(
                audit["memory_type_details"]["knowledge_memory"]["clinical_hypotheses"][0]["role"],
                "primary",
            )
            self.assertEqual(
                audit["memory_type_details"]["knowledge_memory"]["clinical_hypotheses"][1]["role"],
                "differential",
            )
            self.assertEqual(
                audit["agent_io_summary"]["GaoDoctorAgent"]["routing_decision"]["agent_scope"],
                "orchestrator_api",
            )
            self.assertEqual(
                list(audit["agent_io_summary"].keys()),
                audit["agents_traced"],
            )
            self.assertTrue(audit["trace_consistency"]["agent_io_matches_trace"])
            self.assertTrue(audit["trace_consistency"]["required_agents_present"])
            self.assertFalse(audit["trace_consistency"]["qa_extension_present"])
            self.assertEqual(audit["trace_consistency"]["agent_count"], 5)
            self.assertEqual(audit["agent_io_summary"]["VisionAgent"]["selected_vision_mode"], "ground_truth")
            self.assertEqual(audit["agent_io_summary"]["VisionAgent"]["tool"], "ground_truth_mask")
            self.assertEqual(
                audit["agent_io_summary"]["MemoryManager"]["output"]["audit_status"],
                "available",
            )
            self.assertEqual(
                audit["agent_io_summary"]["MemoryManager"]["output"]["evidence_bundle_status"],
                "available",
            )
            self.assertEqual(audit["alignment_summary"]["analysis_status"], "partial_evidence")
            self.assertEqual(audit["knowledge_quality"]["visual_protocol_status"], "valid")
            self.assertEqual(audit["qa_safety"]["qa_history_count"], 0)
            self.assertIn("不能把缺失增强证据解释为阴性", audit["qa_safety"]["blocked_scopes"])

    def test_build_runtime_manifest_records_gateway_execution_facts(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")

            manifest = memory.build_runtime_manifest("case_001")

            self.assertEqual(manifest["schema_version"], "runtime_manifest.v1")
            self.assertEqual(manifest["case_id"], "case_001")
            self.assertEqual(manifest["selected_knowledge"], "股骨头坏死_knowledge_v0.1")
            self.assertEqual(manifest["knowledge_version"], "股骨头坏死_knowledge_v0.1")
            self.assertEqual(
                manifest["input_artifacts"]["image_path"],
                "data/images/demo_xray.png",
            )
            self.assertEqual(
                manifest["generated_artifacts"]["image_outputs"]["overlay_path"],
                "data/overlays/demo_xray_overlay.png",
            )
            self.assertEqual(manifest["tool_calls"][1]["tool"], "ground_truth_mask")
            self.assertTrue(manifest["contracts_checked"]["memory_v1"])
            self.assertTrue(manifest["contracts_checked"]["evidence_bundle"])
            self.assertTrue(manifest["memory_written"]["patient_memory"])
            self.assertTrue(manifest["memory_written"]["image_memory"])
            self.assertIn(
                "enhancement",
                manifest["blocked_or_missing_evidence"]["missing_or_unassessed"][
                    "image_memory"
                ],
            )
            self.assertEqual(
                manifest["runtime_safety"]["self_evolving_action"],
                "candidate_only_no_formal_knowledge_update",
            )
            self.assertTrue(
                Path("output/fake/runtime_manifest/case_001_runtime_manifest.json").exists()
            )

    def test_build_stop_hook_gate_reports_read_only_runtime_warnings(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")

            gate = memory.build_stop_hook_gate("case_001")

            self.assertEqual(gate["schema_version"], "stop_hook_gate.v1")
            self.assertEqual(gate["case_id"], "case_001")
            self.assertTrue(gate["runtime_safety"]["stop_hook_executed"])
            self.assertTrue(gate["runtime_safety"]["read_only"])
            self.assertFalse(gate["runtime_safety"]["formal_knowledge_updated"])
            self.assertFalse(gate["runtime_safety"]["diagnosis_report_updated"])
            warning_codes = [warning["code"] for warning in gate["runtime_warnings"]]
            self.assertIn("missing_or_unassessed_evidence", warning_codes)
            self.assertIn("blocked_diagnosis_scope", warning_codes)
            self.assertIn("补充关键影像", " ".join(gate["next_actions"]))
            self.assertEqual(gate["candidate_knowledge_patch"]["status"], "not_generated")
            self.assertEqual(gate["candidate_knowledge_patch"]["reason"], "read_only_gate")
            self.assertTrue(
                Path("output/fake/stop_hook_gate/case_001_stop_hook_gate.json").exists()
            )

    def test_build_self_evolving_queue_records_candidate_only_items(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")

            queue = memory.build_self_evolving_queue("case_001")

            self.assertEqual(queue["schema_version"], "self_evolving_queue.v1")
            self.assertEqual(queue["case_id"], "case_001")
            self.assertEqual(queue["status"], "candidate_only")
            self.assertEqual(queue["source_stop_hook_gate"]["schema_version"], "stop_hook_gate.v1")
            self.assertTrue(queue["queue_items"])
            self.assertIn(
                "missing_or_unassessed_evidence",
                [item["source_warning_code"] for item in queue["queue_items"]],
            )
            self.assertEqual(queue["queue_items"][0]["validation_status"], "pending_review")
            self.assertEqual(queue["queue_items"][0]["allowed_action"], "candidate_review_only")
            self.assertTrue(queue["runtime_safety"]["queue_written"])
            self.assertFalse(queue["runtime_safety"]["formal_knowledge_updated"])
            self.assertFalse(queue["runtime_safety"]["formal_guideline_updated"])
            self.assertTrue(
                Path("output/fake/self_evolving_queue/case_001_self_evolving_queue.json").exists()
            )

    def test_build_candidate_validation_gate_blocks_unreviewed_queue_items(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")

            gate = memory.build_candidate_validation_gate("case_001")

            self.assertEqual(gate["schema_version"], "candidate_validation_gate.v1")
            self.assertEqual(gate["case_id"], "case_001")
            self.assertEqual(gate["promotion_decision"]["status"], "blocked")
            self.assertEqual(
                gate["promotion_decision"]["reason"],
                "candidate_items_require_review_or_validation",
            )
            self.assertFalse(gate["promotion_decision"]["formal_update_allowed"])
            self.assertTrue(gate["item_validations"])
            self.assertIn(
                "review_or_validation_missing",
                gate["item_validations"][0]["failed_checks"],
            )
            self.assertFalse(gate["runtime_safety"]["formal_knowledge_updated"])
            self.assertFalse(gate["runtime_safety"]["formal_guideline_updated"])
            self.assertTrue(gate["runtime_safety"]["validation_gate_executed"])
            self.assertTrue(
                Path(
                    "output/fake/candidate_validation_gate/"
                    "case_001_candidate_validation_gate.json"
                ).exists()
            )

    def test_build_runtime_gateway_trace_summarizes_all_runtime_stages(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")

            trace = memory.build_runtime_gateway_trace("case_001")

            self.assertEqual(trace["schema_version"], "runtime_gateway_trace.v1")
            self.assertEqual(trace["case_id"], "case_001")
            self.assertEqual(
                [stage["stage"] for stage in trace["stages"]],
                [
                    "runtime_manifest",
                    "stop_hook_gate",
                    "self_evolving_queue",
                    "candidate_validation_gate",
                ],
            )
            self.assertEqual(trace["promotion_status"], "blocked")
            self.assertFalse(trace["formal_update_allowed"])
            self.assertTrue(trace["trace_consistency"]["all_stage_artifacts_available"])
            self.assertTrue(trace["trace_consistency"]["all_stage_schemas_present"])
            self.assertEqual(trace["trace_consistency"]["stage_count"], 4)
            self.assertEqual(trace["trace_consistency"]["missing_artifact_paths"], [])
            self.assertTrue(trace["safety_invariants"]["formal_knowledge_updated"] is False)
            self.assertTrue(trace["safety_invariants"]["diagnosis_report_updated"] is False)
            self.assertTrue(
                Path("output/fake/runtime_gateway_trace/case_001_runtime_gateway_trace.json").exists()
            )

    def test_list_case_summaries_returns_demo_safe_metadata(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死", patient_id="patient_a")
            self._save_case(memory, "case_002", "成人弥漫性胶质瘤", patient_id="patient_b")

            summaries = memory.list_case_summaries(limit=1)

            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0]["case_id"], "case_002")
            self.assertEqual(summaries[0]["patient_id"], "patient_b")
            self.assertEqual(summaries[0]["selected_knowledge"], "成人弥漫性胶质瘤_knowledge_v0.1")
            self.assertEqual(summaries[0]["analysis_status"], "partial_evidence")
            self.assertEqual(summaries[0]["modality"], "xray")
            self.assertEqual(summaries[0]["qa_history_count"], 0)
            self.assertNotIn("patient_message", summaries[0])

    def test_build_case_replay_returns_agent_step_timeline(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            self._save_case(memory, "case_001", "股骨头坏死")
            memory.append_qa_memory(
                case_id="case_001",
                question="为什么还需要 MRI？",
                answer="因为增强证据缺失。",
                llm_used=True,
            )

            replay = memory.build_case_replay("case_001")

            self.assertEqual(replay["case_id"], "case_001")
            self.assertEqual(replay["status"], "ready")
            self.assertTrue(replay["replay_consistency"]["required_events_present"])
            self.assertTrue(replay["replay_consistency"]["memory_scope_complete"])
            self.assertTrue(replay["replay_consistency"]["qa_extension_present"])
            self.assertEqual(replay["replay_consistency"]["step_count"], 7)
            self.assertEqual(replay["replay_consistency"]["missing_required_events"], [])
            self.assertEqual(replay["replay_consistency"]["steps_missing_memory_scope"], [])
            self.assertEqual(
                [step["agent"] for step in replay["steps"]],
                [
                    "GaoDoctorAgent",
                    "GaoDoctorAgent",
                    "KnowledgeBuilderAgent",
                    "VisionAgent",
                    "DiagnosisDoctorAgent",
                    "MemoryManager",
                    "GaoDoctorAgent QA",
                ],
            )
            self.assertEqual(replay["steps"][0]["event"], "patient_intake")
            self.assertEqual(replay["steps"][0]["memory_scope"], "patient_memory")
            self.assertEqual(replay["steps"][1]["selected_knowledge"], "股骨头坏死_knowledge_v0.1")
            self.assertEqual(replay["steps"][1]["event"], "knowledge_routing")
            self.assertEqual(replay["steps"][1]["memory_scope"], "knowledge_memory")
            self.assertEqual(replay["steps"][1]["decision_owner"], "orchestrator_api")
            self.assertEqual(replay["steps"][1]["routing_decision"]["agent_scope"], "orchestrator_api")
            self.assertEqual(replay["steps"][1]["knowledge_builder_action"], "load_existing_knowledge")
            self.assertEqual(replay["steps"][2]["event"], "knowledge_loading")
            self.assertEqual(replay["steps"][2]["memory_scope"], "knowledge_memory")
            self.assertEqual(replay["steps"][2]["action"], "load_existing_knowledge")
            self.assertEqual(replay["steps"][2]["selected_knowledge"], "股骨头坏死_knowledge_v0.1")
            self.assertEqual(replay["steps"][3]["memory_scope"], "image_memory")
            self.assertEqual(replay["steps"][3]["selected_vision_mode"], "ground_truth")
            self.assertEqual(replay["steps"][3]["tool"], "ground_truth_mask")
            self.assertEqual(replay["steps"][3]["segmentation_quality"], "simulated")
            self.assertEqual(replay["steps"][4]["memory_scope"], "reasoning_memory")
            self.assertEqual(replay["steps"][4]["diagnostic_tendency"], "测试诊断")
            self.assertEqual(replay["steps"][5]["memory_scope"], "patient_memory,image_memory,knowledge_memory,reasoning_memory")
            self.assertEqual(replay["steps"][5]["evidence_bundle_status"], "available")
            self.assertEqual(replay["steps"][6]["event"], "follow_up_qa")
            self.assertEqual(replay["steps"][6]["agent"], "GaoDoctorAgent QA")
            self.assertEqual(replay["steps"][6]["memory_scope"], "patient_memory.qa_history")
            self.assertTrue(replay["memory_outputs"]["audit_path"].endswith("case_001_audit.json"))
            self.assertEqual(replay["memory_outputs"]["evidence_bundle"]["case_id"], "case_001")


if __name__ == "__main__":
    unittest.main()
