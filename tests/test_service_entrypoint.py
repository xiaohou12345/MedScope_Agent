import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.gaodoctor_agent import GaoDoctorAgent
from api.service import MedScopeService
from llm.prompt_runner import PromptRunner
from memory.memory_manager import MemoryManager


class FakeGaoDoctor:
    def __init__(self):
        self.calls = []

    def handle_message(
        self,
        patient_message,
        image_path=None,
        patient_info=None,
        case_id=None,
        disease_key=None,
        vision_mode=None,
        mask_path=None,
        segmentation_prompt=None,
        hypothesis_validation_mode=False,
        alignment_plan=None,
        routing_decision=None,
    ):
        self.calls.append(
            {
                "patient_message": patient_message,
                "image_path": image_path,
                "patient_info": patient_info,
                "case_id": case_id,
                "disease_key": disease_key,
                "vision_mode": vision_mode,
                "mask_path": mask_path,
                "segmentation_prompt": segmentation_prompt,
                "hypothesis_validation_mode": hypothesis_validation_mode,
                "alignment_plan": alignment_plan,
                "routing_decision": routing_decision,
            }
        )
        return {
            "case_id": case_id or "case_new",
            "intent": "qa" if case_id else "diagnosis",
            "reply_to_patient": "ok",
        }


class FakeAlignmentPlanner:
    def __init__(self):
        self.calls = []

    def build_plan(self, payload, routing_decision, disease_skill):
        self.calls.append(
            {
                "payload": payload,
                "routing_decision": routing_decision,
                "disease_skill": disease_skill,
            }
        )
        return {
            "selected_skill": routing_decision.get("selected_skill"),
            "analysis_status": "partial_evidence",
            "clinical_focus": "planner injected",
            "image_context": {"modality": "xray", "body_part": "hip"},
            "visual_tasks": [],
            "diagnosis_scope": {"allowed": [], "blocked": []},
            "suspected_conditions": [],
            "required_next_images": [],
            "insufficiency_reasons": [],
        }


class FakeNoMaskVisualRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        image_path = str(kwargs["image_path"])
        visual_result = {
            "image_path": image_path,
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": image_path,
                "mask_path": "output/fake/fhn_no_mask/finding_mask.png",
                "overlay_path": "output/fake/fhn_no_mask/finding_overlay.png",
                "comparison_path": "output/fake/fhn_no_mask/finding_comparison.png",
            },
            "visual_evidence": {
                "collapse": False,
                "sclerosis": "候选阳性",
                "cystic_change": "unknown",
                "joint_space_narrowing": False,
                "lesion_mask": "output/fake/fhn_no_mask/finding_mask.png",
                "confidence": 0.7,
                "texture_abnormality_score": 0.75,
                "lesion_area_ratio": 0.03,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "lesion_detected": True,
                "lesion_location": "femoral head",
                "disease_target": "femoral_head_necrosis",
                "segmentation_quality": "medium_candidate",
                "suspected_visual_findings": ["硬化带：candidate_present"],
                "measurements": {"lesion_area_ratio": 0.03},
                "completeness": {},
                "findings": [
                    {
                        "finding_id": "finding_sclerotic_band",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                        "measurements": {"area_px": 120},
                    }
                ],
            },
        }
        return {
            "status": "ok",
            "visual_analysis_result": visual_result,
        }


class MedScopeServiceEntrypointTest(unittest.TestCase):
    def test_service_default_gaodoctor_has_prompt_runner_for_follow_up_qa(self):
        service = MedScopeService()

        self.assertIsInstance(service.gaodoctor_agent.prompt_runner, PromptRunner)

    def test_service_routes_diagnosis_payload_through_gaodoctor_only(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "左髋疼痛三个月",
                "image_path": "data/images/demo_xray.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        self.assertEqual(result["intent"], "diagnosis")
        self.assertEqual(fake_doctor.calls[0]["image_path"], "data/images/demo_xray.png")
        self.assertFalse(hasattr(service, "diagnosis_agent"))
        self.assertFalse(hasattr(service, "vision_agent"))

    def test_service_accepts_multi_image_case_group_and_uses_first_image_as_primary(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        service.handle_request(
            {
                "patient_message": "右髋疼痛，判断是否股骨头坏死",
                "image_paths": [
                    "output/fake/uploads/patient_ap_pelvis.png",
                    "output/fake/uploads/patient_frog_lateral.png",
                ],
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        call = fake_doctor.calls[0]
        self.assertEqual(call["image_path"], "output/fake/uploads/patient_ap_pelvis.png")
        self.assertEqual(call["disease_key"], "femoral_head_necrosis")
        self.assertEqual(call["vision_mode"], "no_mask_skill")
        self.assertEqual(
            [item["image_path"] for item in call["patient_info"]["image_series"]],
            [
                "output/fake/uploads/patient_ap_pelvis.png",
                "output/fake/uploads/patient_frog_lateral.png",
            ],
        )
        self.assertEqual(call["patient_info"]["image_series"][1]["view_hint"], "frog_lateral")

    def test_service_routes_qa_payload_through_same_front_door(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "你刚才说哪里异常？",
                "case_id": "case_001",
            }
        )

        self.assertEqual(result["intent"], "qa")
        self.assertEqual(result["case_id"], "case_001")
        self.assertEqual(fake_doctor.calls[0]["case_id"], "case_001")
        self.assertIsNone(fake_doctor.calls[0]["image_path"])

    def test_service_qa_response_attaches_follow_up_agent_memory_trace(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa"
            memory.save_case_memory(
                case_id=case_id,
                patient_memory={
                    "case_id": case_id,
                    "patient_message": "左髋疼痛三个月",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "symptoms": ["髋关节疼痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "case_id": case_id,
                    "image_path": "data/images/demo_xray.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "visual_features": {},
                },
                skill_memory={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "selected_skill": "femoral_head_necrosis",
                    "skill_type": "guideline_based",
                },
                reasoning_memory={
                    "case_id": case_id,
                    "diagnostic_tendency": "疑似早期股骨头坏死",
                    "key_evidence": ["股骨头负重区纹理异常"],
                },
            )

            class QaMemoryBackedDoctor(FakeGaoDoctor):
                def handle_message(self, **kwargs):
                    memory.append_qa_memory(
                        case_id=case_id,
                        question=kwargs["patient_message"],
                        answer="基于 evidence bundle 回答。",
                        llm_used=True,
                    )
                    return {
                        "case_id": case_id,
                        "intent": "qa",
                        "reply_to_patient": "基于 evidence bundle 回答。",
                        "case_memory_path": str(Path(tmpdir) / "cases" / f"{case_id}.json"),
                    }

            result = MedScopeService(gaodoctor_agent=QaMemoryBackedDoctor()).handle_request(
                {
                    "patient_message": "增强缺失是不是阴性？",
                    "case_id": case_id,
                }
            )

            self.assertEqual(result["intent"], "qa")
            self.assertEqual(result["memory_audit"]["agents_traced"][-1], "GaoDoctorAgent QA")
            self.assertEqual(
                result["memory_audit"]["agent_io_summary"]["GaoDoctorAgent QA"]["input"],
                "增强缺失是不是阴性？",
            )
            self.assertEqual(result["memory_replay"]["steps"][-1]["agent"], "GaoDoctorAgent QA")
            self.assertEqual(result["memory_replay"]["steps"][-1]["event"], "follow_up_qa")
            self.assertEqual(result["memory_replay"]["case_summary"]["qa_history_count"], 1)

    def test_service_routes_glioma_visual_payload_through_gaodoctor_only(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "请基于这次 FLAIR MRI 做胶质瘤辅助分析",
                "image_path": "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz",
                "mask_path": "data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz",
                "disease_key": "diffuse_glioma_brats",
                "vision_mode": "ground_truth",
            }
        )

        self.assertEqual(result["intent"], "diagnosis")
        self.assertEqual(fake_doctor.calls[0]["disease_key"], "diffuse_glioma_brats")
        self.assertEqual(fake_doctor.calls[0]["vision_mode"], "ground_truth")
        self.assertEqual(
            fake_doctor.calls[0]["mask_path"],
            "data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz",
        )

    def test_service_auto_selects_glioma_skill_from_message_and_image(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "请看一下这个脑部胶质瘤影像",
                "image_path": "output/fake/uploads/patient_flair.nii.gz",
                "patient_info": {"symptoms": ["头痛"]},
            }
        )

        self.assertEqual(fake_doctor.calls[0]["disease_key"], "diffuse_glioma_brats")
        self.assertEqual(fake_doctor.calls[0]["vision_mode"], "medsam2")
        self.assertEqual(fake_doctor.calls[0]["routing_decision"]["agent_scope"], "orchestrator_api")
        self.assertEqual(result["routing_decision"]["selected_skill"], "diffuse_glioma_brats")
        self.assertEqual(result["routing_decision"]["selected_vision_mode"], "medsam2")
        self.assertEqual(result["routing_decision"]["source"], "auto")
        self.assertEqual(result["routing_decision"]["agent_scope"], "orchestrator_api")
        self.assertEqual(
            result["routing_decision"]["skill_builder_action"],
            "load_existing_skill",
        )
        self.assertGreaterEqual(result["routing_decision"]["confidence"], 0.6)
        self.assertIn("胶质瘤", result["routing_decision"]["matched_clues"])
        self.assertIn("flair", result["routing_decision"]["matched_clues"])

    def test_service_persists_orchestrator_routing_scope_to_skill_memory(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            no_mask_runner = FakeNoMaskVisualRunner()
            service = MedScopeService(
                gaodoctor_agent=GaoDoctorAgent(
                    memory_manager=memory,
                    no_mask_visual_pipeline_runner=no_mask_runner,
                )
            )

            result = service.handle_request(
                {
                    "patient_message": "左髋疼痛三个月，想根据这张 X 光判断股骨头坏死风险",
                    "image_path": "data/images/demo_xray.png",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                }
            )

            saved_case = memory.get_case_by_id(result["case_id"])
            routing = saved_case["skill_memory"]["routing_decision"]
            self.assertEqual(result["routing_decision"]["agent_scope"], "orchestrator_api")
            self.assertEqual(routing["agent_scope"], "orchestrator_api")
            self.assertEqual(routing["selected_skill"], "femoral_head_necrosis")
            self.assertEqual(routing["selected_vision_mode"], "no_mask_skill")
            self.assertEqual(routing["source"], "auto")
            self.assertEqual(len(no_mask_runner.calls), 1)

    def test_service_auto_selects_ipf_skill_from_hrct_chest_clues(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "长期干咳气短，想根据这次 HRCT 判断是否有特发性肺纤维化或 UIP 表现",
                "image_path": "output/fake/uploads/chest_hrct_slice.png",
                "patient_info": {"symptoms": ["干咳", "气短"]},
            }
        )

        self.assertEqual(
            fake_doctor.calls[0]["disease_key"],
            "idiopathic_pulmonary_fibrosis_hrct",
        )
        self.assertIsNone(fake_doctor.calls[0]["vision_mode"])
        self.assertEqual(
            result["routing_decision"]["selected_skill"],
            "idiopathic_pulmonary_fibrosis_hrct",
        )
        self.assertEqual(result["routing_decision"]["source"], "auto")
        self.assertIn("hrct", result["routing_decision"]["matched_clues"])
        self.assertIn("特发性肺纤维化", result["routing_decision"]["matched_clues"])
        self.assertEqual(result["alignment_plan"]["image_context"]["modality"], "CT")
        self.assertIn("HRCT", result["alignment_plan"]["image_context"]["available_sequences"])
        self.assertEqual(result["alignment_plan"]["image_context"]["body_part"], "chest")
        self.assertEqual(result["alignment_plan"]["analysis_status"], "evidence_sufficient")

    def test_service_keeps_default_skill_for_non_glioma_image(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "请看一下这张普通医学图像",
                "image_path": "output/fake/uploads/scan.png",
                "patient_info": {"symptoms": ["不适"]},
            }
        )

        self.assertIsNone(fake_doctor.calls[0]["disease_key"])
        self.assertIsNone(fake_doctor.calls[0]["vision_mode"])
        self.assertIsNone(result["routing_decision"]["selected_skill"])
        self.assertIsNone(result["routing_decision"]["selected_vision_mode"])
        self.assertEqual(result["routing_decision"]["source"], "default")
        self.assertEqual(result["routing_decision"]["agent_scope"], "orchestrator_api")
        self.assertEqual(result["routing_decision"]["skill_builder_action"], "none")
        self.assertEqual(result["routing_decision"]["matched_clues"], [])

    def test_service_auto_selects_femoral_head_skill_from_hip_xray_clues(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "左髋疼痛三个月，帮我看看片子",
                "image_path": "output/fake/uploads/hip_xray.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        self.assertEqual(fake_doctor.calls[0]["disease_key"], "femoral_head_necrosis")
        self.assertEqual(fake_doctor.calls[0]["vision_mode"], "no_mask_skill")
        self.assertEqual(result["routing_decision"]["selected_skill"], "femoral_head_necrosis")
        self.assertEqual(result["routing_decision"]["selected_vision_mode"], "no_mask_skill")
        self.assertEqual(result["routing_decision"]["source"], "auto")
        self.assertEqual(result["routing_decision"]["skill_builder_action"], "load_existing_skill")
        self.assertIn("髋", result["routing_decision"]["matched_clues"])
        self.assertEqual(result["alignment_plan"]["analysis_status"], "partial_evidence")

    def test_service_auto_selects_fhn_no_mask_mode_for_uploaded_hip_image_without_prompt_keywords(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "右髋疼痛，帮我看看",
                "image_path": "output/fake/uploads/uploaded_patient_image.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        self.assertEqual(fake_doctor.calls[0]["disease_key"], "femoral_head_necrosis")
        self.assertEqual(fake_doctor.calls[0]["vision_mode"], "no_mask_skill")
        self.assertEqual(result["routing_decision"]["selected_skill"], "femoral_head_necrosis")
        self.assertEqual(result["routing_decision"]["selected_vision_mode"], "no_mask_skill")
        self.assertEqual(result["routing_decision"]["source"], "auto")
        self.assertIn("髋", result["routing_decision"]["matched_clues"])

    def test_service_delegates_alignment_plan_to_planner(self):
        fake_doctor = FakeGaoDoctor()
        fake_planner = FakeAlignmentPlanner()
        service = MedScopeService(
            gaodoctor_agent=fake_doctor,
            alignment_planner=fake_planner,
        )

        result = service.handle_request(
            {
                "patient_message": "左髋疼痛三个月，帮我看看片子",
                "image_path": "output/fake/uploads/hip_xray.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        self.assertEqual(len(fake_planner.calls), 1)
        self.assertEqual(
            fake_planner.calls[0]["routing_decision"]["selected_skill"],
            "femoral_head_necrosis",
        )
        self.assertEqual(
            fake_planner.calls[0]["disease_skill"]["skill_id"],
            "femoral_head_necrosis_v0.1",
        )
        self.assertEqual(result["alignment_plan"]["clinical_focus"], "planner injected")
        self.assertEqual(fake_doctor.calls[0]["alignment_plan"], result["alignment_plan"])

    def test_service_builds_insufficient_alignment_for_early_fhn_xray_question(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "左髋疼痛，X光能不能判断有没有早期股骨头坏死？",
                "image_path": "output/fake/uploads/hip_xray.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        plan = result["alignment_plan"]
        self.assertEqual(plan["selected_skill"], "femoral_head_necrosis")
        self.assertEqual(plan["analysis_status"], "insufficient_evidence")
        self.assertEqual(fake_doctor.calls[0]["alignment_plan"], plan)
        self.assertEqual(plan["suspected_conditions"][0]["disease"], "股骨头坏死")
        self.assertEqual(plan["required_next_images"][0]["modality"], "MRI")
        self.assertIn("不能将 X 光未见异常解释为无病", "；".join(plan["diagnosis_scope"]["blocked"]))

    def test_service_routing_decision_marks_explicit_payload(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "请基于这次 FLAIR MRI 做胶质瘤辅助分析",
                "image_path": "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz",
                "mask_path": "data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz",
                "disease_key": "diffuse_glioma_brats",
                "vision_mode": "ground_truth",
            }
        )

        self.assertEqual(result["routing_decision"]["selected_skill"], "diffuse_glioma_brats")
        self.assertEqual(result["routing_decision"]["selected_vision_mode"], "ground_truth")
        self.assertEqual(result["routing_decision"]["source"], "explicit")
        self.assertEqual(result["routing_decision"]["confidence"], 1.0)

    def test_service_can_pass_hypothesis_validation_mode_switch(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        service.handle_request(
            {
                "patient_message": "请用假设验证模式分析候选特征",
                "image_path": "data/images/demo_xray.png",
                "hypothesis_validation_mode": True,
            }
        )

        self.assertTrue(fake_doctor.calls[0]["hypothesis_validation_mode"])

    def test_service_rejects_missing_patient_message(self):
        service = MedScopeService(gaodoctor_agent=FakeGaoDoctor())

        with self.assertRaises(ValueError):
            service.handle_request({"image_path": "data/images/demo_xray.png"})

    def test_service_adds_image_outputs_from_case_memory(self):
        with TemporaryDirectory() as tmpdir:
            case_path = Path(tmpdir) / "case_001.json"
            case_path.write_text(
                json.dumps(
                    {
                        "image_memory": {
                            "image_outputs": {
                                "overlay_path": "output/fake/overlay.png",
                                "mask_path": "output/fake/mask.nii.gz",
                            },
                            "visual_features": {
                                "measurements": {"whole_tumor_volume_ml": 12.3},
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            class MemoryBackedDoctor(FakeGaoDoctor):
                def handle_message(self, **kwargs):
                    return {
                        "case_id": "case_001",
                        "intent": "diagnosis",
                        "reply_to_patient": "ok",
                        "case_memory_path": str(case_path),
                    }

            service = MedScopeService(gaodoctor_agent=MemoryBackedDoctor())

            result = service.handle_request({"patient_message": "请分析"})

            self.assertEqual(result["image_outputs"]["overlay_path"], "output/fake/overlay.png")
            self.assertEqual(
                result["visual_features"]["measurements"]["whole_tumor_volume_ml"],
                12.3,
            )

    def test_service_adds_evidence_bundle_and_memory_audit_from_case_memory(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            visual_evidence_bundle = {
                "schema_version": "visual_evidence_bundle.v1",
                "present_findings": ["sclerotic_band", "cystic_change"],
                "structured_visual_facts": [
                    {
                        "finding_id": "finding_sclerosis",
                        "target": "sclerotic_band",
                        "summary_text": "硬化带作为可用视觉证据",
                    },
                    {
                        "finding_id": "finding_cyst",
                        "target": "cystic_change",
                        "summary_text": "囊性变作为非独立候选证据",
                    },
                ],
                "numeric_evidence": {
                    "finding_count": 2,
                    "total_area_px": 200,
                },
                "findings": [
                    {
                        "finding_id": "finding_sclerosis",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "regions": [
                            {
                                "region_id": "r1",
                                "comparison_path": "output/fake/sclerosis_comparison.png",
                                "area_px": 120,
                            }
                        ],
                    },
                    {
                        "finding_id": "finding_cyst",
                        "target": "cystic_change",
                        "display_name": "囊性变",
                        "regions": [
                            {
                                "region_id": "r1",
                                "comparison_path": "output/fake/cyst_comparison.png",
                                "area_px": 80,
                            }
                        ],
                    },
                ],
            }
            memory.save_case_memory(
                case_id="case_001",
                patient_memory={
                    "patient_id": "patient_001",
                    "patient_message": "请分析",
                    "patient_info": {"symptoms": ["头痛"]},
                    "symptoms": ["头痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "image_path": "output/fake/uploads/flair.nii.gz",
                    "modality": "MRI",
                    "body_part": "brain",
                    "image_outputs": {
                        "overlay_path": "output/fake/overlay.png",
                        "mask_path": "output/fake/mask.nii.gz",
                    },
                    "visual_evidence": {
                        "segmentation_quality": "ground_truth_nifti",
                        "measurements": {"whole_tumor_volume_ml": 12.3},
                        "completeness": {
                            "enhancing_tumor": {
                                "status": "missing",
                                "reason": "Requires T1ce modality",
                            }
                        },
                    },
                    "visual_evidence_bundle": visual_evidence_bundle,
                },
                skill_memory={
                    "skill_id": "diffuse_glioma_brats_v0.1",
                    "selected_skill": "diffuse_glioma_brats",
                    "skill_type": "guideline_based",
                    "guideline_evidence": {
                        "citations": [{"title": "Official guideline"}],
                    },
                    "quality_control": {"citation_status": "verified"},
                },
                reasoning_memory={
                    "diagnostic_tendency": "成人弥漫性胶质瘤影像疑似",
                    "key_evidence": ["whole tumor 体积估计"],
                    "uncertainty": ["缺少 T1ce"],
                    "follow_up": ["补全增强序列"],
                    "treatment_advice": ["线下复核"],
                    "visual_fact_usage": {
                        "used": [
                            {
                                "finding_id": "finding_sclerosis",
                                "target": "sclerotic_band",
                                "summary_text": "硬化带作为可用视觉证据",
                            }
                        ],
                        "excluded": [
                            {
                                "finding_id": "finding_cyst",
                                "target": "cystic_change",
                                "exclusion_reason": "non_independent_evidence",
                            }
                        ],
                        "used_count": 1,
                        "excluded_count": 1,
                    },
                },
            )

            class MemoryBackedDoctor(FakeGaoDoctor):
                def handle_message(self, **kwargs):
                    return {
                        "case_id": "case_001",
                        "intent": "diagnosis",
                        "reply_to_patient": "ok",
                        "case_memory_path": str(Path(tmpdir) / "cases" / "case_001.json"),
                    }

            result = MedScopeService(gaodoctor_agent=MemoryBackedDoctor()).handle_request(
                {"patient_message": "请分析"}
            )

            self.assertEqual(result["evidence_bundle"]["case_id"], "case_001")
            self.assertEqual(
                result["visual_evidence_bundle"]["present_findings"],
                ["sclerotic_band", "cystic_change"],
            )
            self.assertEqual(
                result["structured_visual_facts"],
                visual_evidence_bundle["structured_visual_facts"],
            )
            self.assertEqual(result["visual_fact_usage"]["used_count"], 1)
            self.assertEqual(result["visual_fact_usage"]["excluded_count"], 1)
            self.assertEqual(
                result["used_visual_facts"][0]["finding_id"],
                "finding_sclerosis",
            )
            self.assertEqual(
                result["excluded_visual_facts"][0]["finding_id"],
                "finding_cyst",
            )
            self.assertEqual(
                result["evidence_bundle"]["image_evidence"]["visual_evidence_bundle"][
                    "numeric_evidence"
                ]["finding_count"],
                2,
            )
            self.assertEqual(
                result["evidence_bundle"]["missing_or_unassessed"]["image_memory"][
                    "enhancing_tumor"
                ]["status"],
                "missing",
            )
            self.assertEqual(result["memory_audit"]["case_id"], "case_001")
            self.assertTrue(result["memory_audit"]["memory_completeness"]["patient_memory"])
            self.assertTrue(Path(result["memory_audit_path"]).exists())
            self.assertEqual(result["runtime_manifest"]["schema_version"], "runtime_manifest.v1")
            self.assertEqual(result["runtime_manifest"]["case_id"], "case_001")
            self.assertEqual(result["runtime_manifest"]["selected_skill"], "diffuse_glioma_brats")
            self.assertIn("memory_v1", result["runtime_manifest"]["contracts_checked"])
            self.assertEqual(result["stop_hook_gate"]["schema_version"], "stop_hook_gate.v1")
            self.assertEqual(result["stop_hook_gate"]["case_id"], "case_001")
            self.assertTrue(result["stop_hook_gate"]["runtime_safety"]["read_only"])
            self.assertFalse(result["stop_hook_gate"]["runtime_safety"]["formal_skill_updated"])
            self.assertEqual(
                result["self_evolving_queue"]["schema_version"],
                "self_evolving_queue.v1",
            )
            self.assertEqual(result["self_evolving_queue"]["case_id"], "case_001")
            self.assertEqual(result["self_evolving_queue"]["status"], "candidate_only")
            self.assertTrue(result["self_evolving_queue"]["runtime_safety"]["queue_written"])
            self.assertFalse(
                result["self_evolving_queue"]["runtime_safety"]["formal_skill_updated"]
            )
            self.assertEqual(
                result["candidate_validation_gate"]["schema_version"],
                "candidate_validation_gate.v1",
            )
            self.assertEqual(result["candidate_validation_gate"]["case_id"], "case_001")
            self.assertEqual(
                result["candidate_validation_gate"]["promotion_decision"]["status"],
                "blocked",
            )
            self.assertFalse(
                result["candidate_validation_gate"]["promotion_decision"][
                    "formal_update_allowed"
                ]
            )
            self.assertEqual(
                result["runtime_gateway_trace"]["schema_version"],
                "runtime_gateway_trace.v1",
            )
            self.assertEqual(result["runtime_gateway_trace"]["case_id"], "case_001")
            self.assertEqual(result["runtime_gateway_trace"]["promotion_status"], "blocked")
            self.assertFalse(result["runtime_gateway_trace"]["formal_update_allowed"])
            self.assertEqual(result["memory_replay"]["case_id"], "case_001")
            self.assertEqual(result["memory_replay"]["steps"][0]["agent"], "GaoDoctorAgent")
            self.assertEqual(result["lesion_gallery"]["schema_version"], "lesion_gallery.v1")
            self.assertEqual(result["lesion_gallery"]["used_count"], 1)
            self.assertEqual(result["lesion_gallery"]["excluded_count"], 1)
            self.assertEqual(
                result["lesion_gallery"]["items"][0]["image_paths"]["comparison_path"],
                "output/fake/sclerosis_comparison.png",
            )
            self.assertEqual(
                result["evidence_bundle"]["lesion_gallery"]["items"][1]["usage"]["status"],
                "excluded",
            )

    def test_service_exposes_guideline_evidence_from_report(self):
        class CitationDoctor(FakeGaoDoctor):
            def handle_message(self, **kwargs):
                return {
                    "case_id": "case_cited",
                    "intent": "diagnosis",
                    "reply_to_patient": "ok",
                    "report": {
                        "guideline_evidence": {
                            "citations": [
                                {
                                    "title": "Official guideline",
                                    "url": "https://example.org/guideline",
                                    "source_kind": "official_guideline",
                                    "evidence_note": "Used for report",
                                }
                            ]
                        }
                    },
                }

        result = MedScopeService(gaodoctor_agent=CitationDoctor()).handle_request(
            {"patient_message": "请分析", "image_path": "data/images/demo_xray.png"}
        )

        self.assertEqual(
            result["guideline_evidence"]["citations"][0]["url"],
            "https://example.org/guideline",
        )


if __name__ == "__main__":
    unittest.main()
