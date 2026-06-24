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


class FakeInsufficientEvidenceDoctor(FakeGaoDoctor):
    def handle_message(self, *args, **kwargs):
        super().handle_message(*args, **kwargs)
        return {
            "case_id": kwargs.get("case_id") or "case_new",
            "intent": "diagnosis",
            "reply_to_patient": "primary evidence insufficient",
            "report": {
                "target_disease_assessment": {
                    "target_disease": kwargs.get("disease_key"),
                    "evidence_status": "insufficient",
                },
                "integrated_reasoning_summary": {
                    "evidence_status": "insufficient",
                    "conclusion": "目前证据不足，不能确认股骨头坏死。",
                },
            },
        }


class FakeVerboseInsufficientEvidenceDoctor(FakeGaoDoctor):
    def handle_message(self, *args, **kwargs):
        super().handle_message(*args, **kwargs)
        return {
            "case_id": kwargs.get("case_id") or "case_new",
            "intent": "diagnosis",
            "reply_to_patient": (
                "您好，我是高医生。我已经为您详细阅读了这份结构化医学辅助分析报告。"
                "首先需要特别向您说明：本报告属于辅助分析提示，并非最终的临床医学诊断。"
            ),
            "report": {
                "target_disease_assessment": {
                    "target_disease": kwargs.get("disease_key"),
                    "evidence_status": "insufficient",
                },
                "integrated_reasoning_summary": {
                    "evidence_status": "insufficient",
                    "conclusion": "目前证据不足，不能确认股骨头坏死。",
                },
            },
        }


class FakeStrongFhnEvidenceDoctor(FakeGaoDoctor):
    def handle_message(self, *args, **kwargs):
        super().handle_message(*args, **kwargs)
        return {
            "case_id": kwargs.get("case_id") or "case_new",
            "intent": "diagnosis",
            "reply_to_patient": "primary evidence partially supported",
            "visual_evidence_bundle": {
                "present_findings": ["sclerotic_band", "cystic_change"],
                "structured_visual_facts": [
                    {
                        "finding_id": "finding_sclerosis",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "summary_text": "右侧股骨头上外侧硬化带",
                    },
                    {
                        "finding_id": "finding_cystic",
                        "target": "cystic_change",
                        "display_name": "囊性变",
                        "summary_text": "右侧股骨头内可疑囊性变",
                    },
                ],
            },
            "report": {
                "target_disease_assessment": {
                    "target_disease": kwargs.get("disease_key"),
                    "evidence_status": "insufficient",
                },
                "integrated_reasoning_summary": {
                    "target_disease": kwargs.get("disease_key"),
                    "evidence_status": "insufficient",
                    "can_confirm_target_disease": False,
                    "conclusion": "目前证据不足，不能确认股骨头坏死。",
                },
                "imaging_evidence_summary": {
                    "supported_targets": ["sclerotic_band", "cystic_change"],
                },
            },
        }


class FakeSecondaryVisualEvidenceRunner:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        *,
        image_path,
        patient_message,
        patient_info,
        disease_key,
        disease_knowledge,
        vision_mode,
    ):
        self.calls.append(
            {
                "image_path": image_path,
                "patient_message": patient_message,
                "patient_info": patient_info,
                "disease_key": disease_key,
                "disease_knowledge": disease_knowledge,
                "vision_mode": vision_mode,
            }
        )
        if disease_key == "osteoarthritis_or_degenerative_hip_disease":
            return {
                "status": "ok",
                "visual_evidence_bundle": {
                    "schema_version": "secondary_visual_evidence_bundle.v1",
                    "disease_target": disease_key,
                    "present_findings": ["joint_space_narrowing", "osteophyte"],
                    "findings": [
                        {
                            "target": "joint_space_narrowing",
                            "display_name": "关节间隙变窄",
                            "description": "按备用退变 knowledge 复查发现关节间隙变窄候选征象",
                        },
                        {
                            "target": "osteophyte",
                            "display_name": "骨赘",
                            "description": "按备用退变 knowledge 复查发现骨赘候选征象",
                        },
                    ],
                    "numeric_evidence": {"finding_count": 2},
                },
                "image_outputs": {
                    "overlay_path": "output/fake/secondary_oa_overlay.png",
                    "mask_path": "not_generated",
                },
            }
        return {
            "status": "ok",
            "visual_evidence_bundle": {
                "schema_version": "secondary_visual_evidence_bundle.v1",
                "disease_target": disease_key,
                "present_findings": [],
                "findings": [],
            },
            "image_outputs": {"overlay_path": "not_generated", "mask_path": "not_generated"},
        }


class FakeMultiSecondaryVisualEvidenceRunner:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        *,
        image_path,
        patient_message,
        patient_info,
        disease_key,
        disease_knowledge,
        vision_mode,
    ):
        self.calls.append(
            {
                "image_path": image_path,
                "patient_message": patient_message,
                "patient_info": patient_info,
                "disease_key": disease_key,
                "disease_knowledge": disease_knowledge,
                "vision_mode": vision_mode,
            }
        )
        findings_by_key = {
            "osteoarthritis_or_degenerative_hip_disease": [
                ("joint_space_narrowing", "关节间隙变窄"),
                ("osteophyte", "骨赘"),
                ("subchondral_sclerosis", "软骨下硬化"),
            ],
            "post_traumatic_change": [
                ("old_fracture_deformity", "陈旧骨折畸形"),
            ],
            "developmental_dysplasia_related_degeneration": [],
        }
        findings = [
            {
                "target": target,
                "display_name": display_name,
                "description": f"按 {disease_key} 备用 knowledge 复查发现 {display_name}",
            }
            for target, display_name in findings_by_key.get(disease_key, [])
        ]
        return {
            "status": "ok",
            "visual_evidence_bundle": {
                "schema_version": "secondary_visual_evidence_bundle.v1",
                "disease_target": disease_key,
                "present_findings": [finding["target"] for finding in findings],
                "findings": findings,
                "numeric_evidence": {"finding_count": len(findings)},
            },
            "image_outputs": {
                "overlay_path": f"output/fake/secondary_{disease_key}_overlay.png",
                "mask_path": "not_generated",
            },
        }


class FakeSecondaryVlmPromptRunner:
    def __init__(self):
        self.calls = []

    def run(self, task, system_prompt, user_payload):
        self.calls.append(
            {
                "task": task,
                "system_prompt": system_prompt,
                "user_payload": user_payload,
            }
        )
        return json.dumps(
            {
                "findings": [
                    {
                        "target": "joint_space_narrowing",
                        "side": "right",
                        "bbox": [34, 42, 96, 108],
                        "rationale": "joint-space narrowing candidate",
                        "confidence": 0.72,
                    },
                    {
                        "target": "osteophyte",
                        "side": "right",
                        "bbox": [98, 44, 132, 86],
                        "rationale": "marginal osteophyte candidate",
                        "confidence": 0.68,
                    },
                ]
            },
            ensure_ascii=False,
        )


class FakeInsufficientEvidenceDoctorWithVlm(FakeInsufficientEvidenceDoctor):
    def __init__(self, prompt_runner):
        super().__init__()
        self.prompt_runner = prompt_runner


class FakeAlignmentPlanner:
    def __init__(self):
        self.calls = []

    def build_plan(self, payload, routing_decision, disease_knowledge):
        self.calls.append(
            {
                "payload": payload,
                "routing_decision": routing_decision,
                "disease_knowledge": disease_knowledge,
            }
        )
        return {
            "selected_knowledge": routing_decision.get("selected_knowledge"),
            "analysis_status": "partial_evidence",
            "clinical_focus": "planner injected",
            "image_context": {"modality": "xray", "body_part": "hip"},
            "visual_tasks": [],
            "diagnosis_scope": {"allowed": [], "blocked": []},
            "suspected_conditions": [],
            "required_next_images": [],
            "insufficiency_reasons": [],
        }


class MissingKnowledgeTool:
    def load_guideline_knowledge(self, disease_key):
        raise FileNotFoundError(disease_key)

    def prepare_knowledge(self, **kwargs):
        return {
            "knowledge_id": f"{kwargs['disease_key']}_proposal_v0.1",
            "disease_name": kwargs["disease_name"],
            "knowledge_type": "data_mined_hypothesis",
            "source_type": "internal_dataset_summary",
            "evidence_level": "low",
        }


class ProposalKnowledgeTool(MissingKnowledgeTool):
    def __init__(self):
        self.prepare_calls = []

    def prepare_knowledge(self, **kwargs):
        self.prepare_calls.append(kwargs)
        return {
            "knowledge_id": f"{kwargs['disease_key']}_proposal_v0.1",
            "disease_name": kwargs["disease_name"],
            "knowledge_type": "data_mined_hypothesis",
            "source_type": "internal_dataset_summary",
            "evidence_level": "low",
            "quality_control": {
                "formal_knowledge_status": "proposal_only",
                "can_enter_formal_guideline_knowledge": False,
            },
            "safety_gate": {
                "mode_required": "hypothesis_validation",
            },
        }


class IncompleteLocalKnowledgeTool(ProposalKnowledgeTool):
    def load_guideline_knowledge(self, disease_key):
        return {
            "knowledge_id": f"{disease_key}_guideline_v0.1",
            "disease_name": "不完整本地 knowledge",
            "knowledge_type": "guideline_based",
            "source_type": "guideline",
            "evidence_level": "medium",
        }


class FhnOnlyKnowledgeTool(ProposalKnowledgeTool):
    def load_guideline_knowledge(self, disease_key):
        if disease_key != "femoral_head_necrosis":
            raise FileNotFoundError(disease_key)
        return json.loads(Path("knowledge/femoral_head_necrosis.yaml").read_text(encoding="utf-8"))


class InvalidVisualProtocolKnowledgeTool(ProposalKnowledgeTool):
    def load_guideline_knowledge(self, disease_key):
        return {
            "knowledge_id": f"{disease_key}_guideline_v0.1",
            "disease_name": "无效 visual protocol knowledge",
            "knowledge_type": "guideline_based",
            "source_type": "guideline",
            "evidence_level": "medium",
            "visual_protocol": {
                "disease_target": disease_key,
                "alignment_tasks": [],
            },
        }


class InvalidEvidenceProtocolKnowledgeTool(ProposalKnowledgeTool):
    def load_guideline_knowledge(self, disease_key):
        return {
            "knowledge_id": f"{disease_key}_guideline_v0.1",
            "disease_name": "无效多维 evidence protocol knowledge",
            "knowledge_type": "guideline_based",
            "source_type": "guideline",
            "evidence_level": "medium",
            "imaging_evidence_protocol": {
                "disease_target": disease_key,
                "finding_targets": [],
            },
            "quantitative_evidence_protocol": {
                "image_feature_quantification": [],
            },
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
    def test_service_defaults_to_finding_list_baseline_evidence_mode(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor, knowledge_tool=FhnOnlyKnowledgeTool())

        result = service.handle_request(
            {
                "patient_message": "右髋疼痛，上传 X 光，请先看股骨头坏死方向。",
                "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "disease_key": "femoral_head_necrosis",
                "vision_mode": "no_mask_knowledge",
            }
        )

        routing = result["routing_decision"]
        self.assertEqual(routing["evidence_protocol_mode"], "finding_list_baseline")
        self.assertFalse(routing["quantitative_protocol_requested"])
        self.assertEqual(
            routing["quantitative_protocol_status"],
            "not_requested_default_finding_list_only",
        )
        self.assertEqual(
            fake_doctor.calls[0]["routing_decision"]["evidence_protocol_mode"],
            "finding_list_baseline",
        )
        summary = result["evidence_protocol_mode_summary"]
        self.assertEqual(summary["mode"], "finding_list_baseline")
        self.assertFalse(summary["quantitative_protocol_requested"])
        self.assertIn("病灶征象", summary["doctor_facing_summary"])

    def test_service_quantitative_protocol_is_opt_in_and_reports_current_limit(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor, knowledge_tool=FhnOnlyKnowledgeTool())

        result = service.handle_request(
            {
                "patient_message": "右髋疼痛，上传 X 光，请尝试加入量化指标协议。",
                "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "disease_key": "femoral_head_necrosis",
                "vision_mode": "no_mask_knowledge",
                "evidence_protocol_mode": "quantitative_optional",
            }
        )

        routing = result["routing_decision"]
        self.assertEqual(routing["evidence_protocol_mode"], "quantitative_optional")
        self.assertTrue(routing["quantitative_protocol_requested"])
        self.assertEqual(
            routing["quantitative_protocol_status"],
            "requested_requires_validated_measurement_backend",
        )
        summary = result["evidence_protocol_mode_summary"]
        self.assertTrue(summary["quantitative_protocol_requested"])
        self.assertFalse(summary["quantitative_protocol_default_enabled"])
        self.assertIn("可选量化", summary["doctor_facing_summary"])
        self.assertIn("暂不默认启用", summary["safety_boundary"])
        self.assertIn("证据提取范围", result["report"])

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
        self.assertEqual(call["vision_mode"], "no_mask_knowledge")
        self.assertEqual(
            [item["image_path"] for item in call["patient_info"]["image_series"]],
            [
                "output/fake/uploads/patient_ap_pelvis.png",
                "output/fake/uploads/patient_frog_lateral.png",
            ],
        )
        self.assertEqual(call["patient_info"]["image_series"][1]["view_hint"], "frog_lateral")

    def test_service_infers_generic_lateral_view_for_multi_image_case_group(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        service.handle_request(
            {
                "patient_message": "左髋疼痛，上传正位和侧位 X 光",
                "image_paths": [
                    "output/real/onfh_pair/ap_detail_idiopathic_onfh.jpg",
                    "output/real/onfh_pair/lateral_idiopathic_onfh.jpg",
                ],
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        call = fake_doctor.calls[0]
        self.assertEqual(
            [item["view_hint"] for item in call["patient_info"]["image_series"]],
            ["ap_pelvis", "lateral"],
        )

    def test_service_accepts_real_vlm_validation_mode_for_fhn_multiview(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "左髋疼痛，上传正位和侧位 X 光，请检查候选征象",
                "image_paths": [
                    "output/real/onfh_pair/ap_detail_idiopathic_onfh.jpg",
                    "output/real/onfh_pair/lateral_idiopathic_onfh.jpg",
                ],
                "patient_info": {"symptoms": ["左髋疼痛"]},
                "vision_mode": "real_vlm_validation",
            }
        )

        call = fake_doctor.calls[0]
        self.assertEqual(call["image_path"], "output/real/onfh_pair/ap_detail_idiopathic_onfh.jpg")
        self.assertEqual(call["disease_key"], "femoral_head_necrosis")
        self.assertEqual(call["vision_mode"], "real_vlm_validation")
        self.assertEqual(
            [item["view_hint"] for item in call["patient_info"]["image_series"]],
            ["ap_pelvis", "lateral"],
        )
        self.assertEqual(result["routing_decision"]["selected_vision_mode"], "real_vlm_validation")
        self.assertEqual(result["routing_decision"]["source"], "explicit")

    def test_service_rejects_unknown_explicit_vision_mode(self):
        service = MedScopeService(gaodoctor_agent=FakeGaoDoctor())

        with self.assertRaisesRegex(ValueError, "unsupported vision_mode"):
            service.handle_request(
                {
                    "patient_message": "左髋疼痛，上传 X 光",
                    "image_path": "output/fake/uploads/patient_ap_pelvis.png",
                    "vision_mode": "typo_vlm_mode",
                }
            )

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
                knowledge_memory={
                    "knowledge_id": "femoral_head_necrosis_v0.1",
                    "selected_knowledge": "femoral_head_necrosis",
                    "knowledge_type": "guideline_based",
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

    def test_service_auto_selects_glioma_knowledge_from_message_and_image(self):
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
        self.assertEqual(result["routing_decision"]["selected_knowledge"], "diffuse_glioma_brats")
        self.assertEqual(result["routing_decision"]["selected_vision_mode"], "medsam2")
        self.assertEqual(result["routing_decision"]["source"], "auto")
        self.assertEqual(result["routing_decision"]["agent_scope"], "orchestrator_api")
        self.assertEqual(
            result["routing_decision"]["knowledge_builder_action"],
            "load_existing_knowledge",
        )
        self.assertGreaterEqual(result["routing_decision"]["confidence"], 0.6)
        self.assertIn("胶质瘤", result["routing_decision"]["matched_clues"])
        self.assertIn("flair", result["routing_decision"]["matched_clues"])

    def test_service_persists_orchestrator_routing_scope_to_knowledge_memory(self):
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
                    "patient_message": "左髋疼痛三个月，走路加重，帮我看看这张 X 光有没有问题",
                    "image_path": "data/images/demo_xray.png",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                }
            )

            saved_case = memory.get_case_by_id(result["case_id"])
            routing = saved_case["knowledge_memory"]["routing_decision"]
            self.assertEqual(result["routing_decision"]["agent_scope"], "orchestrator_api")
            self.assertEqual(routing["agent_scope"], "orchestrator_api")
            self.assertEqual(routing["selected_knowledge"], "femoral_head_necrosis")
            self.assertEqual(routing["selected_vision_mode"], "no_mask_knowledge")
            self.assertEqual(routing["source"], "auto")
            self.assertEqual(routing["primary_hypothesis"], "femoral_head_necrosis")
            self.assertEqual(routing["initial_evidence_status"], "requires_evidence_acquisition")
            self.assertEqual(routing["routing_evidence_status"], "requires_evidence_acquisition")
            self.assertIn(
                "osteoarthritis_or_degenerative_hip_disease",
                routing["differential_knowledge_candidates"],
            )
            self.assertIn("left hip pain", routing["knowledge_search_reason"])
            self.assertEqual(len(no_mask_runner.calls), 1)

    def test_service_auto_selects_ipf_knowledge_from_hrct_chest_clues(self):
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
            result["routing_decision"]["selected_knowledge"],
            "idiopathic_pulmonary_fibrosis_hrct",
        )
        self.assertEqual(result["routing_decision"]["source"], "auto")
        self.assertIn("hrct", result["routing_decision"]["matched_clues"])
        self.assertIn("特发性肺纤维化", result["routing_decision"]["matched_clues"])
        self.assertEqual(result["alignment_plan"]["image_context"]["modality"], "CT")
        self.assertIn("HRCT", result["alignment_plan"]["image_context"]["available_sequences"])
        self.assertEqual(result["alignment_plan"]["image_context"]["body_part"], "chest")
        self.assertEqual(result["alignment_plan"]["analysis_status"], "evidence_sufficient")

    def test_service_keeps_default_knowledge_for_non_glioma_image(self):
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
        self.assertIsNone(result["routing_decision"]["selected_knowledge"])
        self.assertIsNone(result["routing_decision"]["selected_vision_mode"])
        self.assertEqual(result["routing_decision"]["source"], "default")
        self.assertEqual(result["routing_decision"]["agent_scope"], "orchestrator_api")
        self.assertEqual(result["routing_decision"]["knowledge_builder_action"], "none")
        self.assertEqual(result["routing_decision"]["matched_clues"], [])

    def test_service_does_not_mark_missing_local_knowledge_as_loaded(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(
            gaodoctor_agent=fake_doctor,
            knowledge_tool=MissingKnowledgeTool(),
        )

        result = service.handle_request(
            {
                "patient_message": "左髋疼痛，考虑罕见髋部疾病，请根据指南评估",
                "image_path": "output/fake/uploads/rare_hip_xray.png",
                "disease_key": "rare_hip_disorder",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        routing = result["routing_decision"]
        self.assertEqual(routing["selected_knowledge"], "rare_hip_disorder")
        self.assertEqual(routing["primary_hypothesis"], "rare_hip_disorder")
        self.assertEqual(routing["knowledge_builder_action"], "search_or_generate_knowledge")
        self.assertIn("local knowledge", routing["knowledge_search_reason"])

    def test_service_returns_proposal_only_knowledge_when_local_knowledge_is_missing(self):
        fake_doctor = FakeGaoDoctor()
        proposal_tool = ProposalKnowledgeTool()
        service = MedScopeService(
            gaodoctor_agent=fake_doctor,
            knowledge_tool=proposal_tool,
        )

        result = service.handle_request(
            {
                "patient_message": "左髋疼痛，考虑罕见髋部疾病，请根据指南评估",
                "image_path": "output/fake/uploads/rare_hip_xray.png",
                "disease_key": "rare_hip_disorder",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        self.assertEqual(result["intent"], "knowledge_proposal")
        self.assertEqual(result["analysis_status"], "knowledge_proposal_required")
        self.assertEqual(result["routing_decision"]["knowledge_builder_action"], "search_or_generate_knowledge")
        self.assertEqual(result["knowledge_builder_proposal"]["knowledge_id"], "rare_hip_disorder_proposal_v0.1")
        self.assertFalse(result["knowledge_builder_proposal"]["formal_update_allowed"])
        self.assertFalse(result["knowledge_builder_proposal"]["diagnosis_allowed"])
        self.assertEqual(proposal_tool.prepare_calls[0]["disease_key"], "rare_hip_disorder")
        self.assertFalse(proposal_tool.prepare_calls[0]["persist"])
        self.assertEqual(fake_doctor.calls, [])

    def test_service_returns_proposal_only_when_local_knowledge_lacks_protocol(self):
        fake_doctor = FakeGaoDoctor()
        knowledge_tool = IncompleteLocalKnowledgeTool()
        service = MedScopeService(
            gaodoctor_agent=fake_doctor,
            knowledge_tool=knowledge_tool,
        )

        result = service.handle_request(
            {
                "patient_message": "左髋疼痛，上传 X 光，请评估这个不完整 knowledge",
                "image_path": "output/fake/uploads/left_hip_xray.png",
                "disease_key": "incomplete_local_knowledge",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        self.assertEqual(result["intent"], "knowledge_proposal")
        self.assertEqual(result["analysis_status"], "knowledge_proposal_required")
        self.assertEqual(result["routing_decision"]["selected_knowledge"], "incomplete_local_knowledge")
        self.assertEqual(result["routing_decision"]["knowledge_builder_action"], "search_or_generate_knowledge")
        self.assertIn("required protocol", result["routing_decision"]["knowledge_search_reason"])
        self.assertEqual(knowledge_tool.prepare_calls[0]["disease_key"], "incomplete_local_knowledge")
        self.assertFalse(knowledge_tool.prepare_calls[0]["persist"])
        self.assertEqual(fake_doctor.calls, [])

    def test_service_returns_proposal_only_when_local_visual_protocol_is_invalid(self):
        fake_doctor = FakeGaoDoctor()
        knowledge_tool = InvalidVisualProtocolKnowledgeTool()
        service = MedScopeService(
            gaodoctor_agent=fake_doctor,
            knowledge_tool=knowledge_tool,
        )

        result = service.handle_request(
            {
                "patient_message": "左髋疼痛，上传 X 光，请评估这个 protocol 无效的 knowledge",
                "image_path": "output/fake/uploads/left_hip_xray.png",
                "disease_key": "invalid_visual_protocol_knowledge",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        self.assertEqual(result["intent"], "knowledge_proposal")
        self.assertEqual(result["analysis_status"], "knowledge_proposal_required")
        self.assertEqual(
            result["routing_decision"]["knowledge_builder_action"],
            "search_or_generate_knowledge",
        )
        self.assertIn("invalid visual_protocol", result["routing_decision"]["knowledge_search_reason"])
        self.assertEqual(knowledge_tool.prepare_calls[0]["disease_key"], "invalid_visual_protocol_knowledge")
        self.assertEqual(fake_doctor.calls, [])

    def test_service_returns_proposal_only_when_local_evidence_protocol_is_invalid(self):
        fake_doctor = FakeGaoDoctor()
        knowledge_tool = InvalidEvidenceProtocolKnowledgeTool()
        service = MedScopeService(
            gaodoctor_agent=fake_doctor,
            knowledge_tool=knowledge_tool,
        )

        result = service.handle_request(
            {
                "patient_message": "左髋疼痛，上传 X 光，请评估这个 evidence protocol 无效的 knowledge",
                "image_path": "output/fake/uploads/left_hip_xray.png",
                "disease_key": "invalid_evidence_protocol_knowledge",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        self.assertEqual(result["intent"], "knowledge_proposal")
        self.assertEqual(result["analysis_status"], "knowledge_proposal_required")
        self.assertEqual(
            result["routing_decision"]["knowledge_builder_action"],
            "search_or_generate_knowledge",
        )
        self.assertIn(
            "invalid evidence_protocol",
            result["routing_decision"]["knowledge_search_reason"],
        )
        self.assertEqual(
            knowledge_tool.prepare_calls[0]["disease_key"],
            "invalid_evidence_protocol_knowledge",
        )
        self.assertEqual(fake_doctor.calls, [])

    def test_service_auto_selects_femoral_head_knowledge_from_hip_xray_clues(self):
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
        self.assertEqual(fake_doctor.calls[0]["vision_mode"], "no_mask_knowledge")
        self.assertEqual(result["routing_decision"]["selected_knowledge"], "femoral_head_necrosis")
        self.assertEqual(result["routing_decision"]["selected_vision_mode"], "no_mask_knowledge")
        self.assertEqual(result["routing_decision"]["source"], "auto")
        self.assertEqual(result["routing_decision"]["knowledge_builder_action"], "load_existing_knowledge")
        self.assertIn("髋", result["routing_decision"]["matched_clues"])
        self.assertEqual(result["routing_decision"]["primary_hypothesis"], "femoral_head_necrosis")
        self.assertEqual(
            result["routing_decision"]["initial_evidence_status"],
            "requires_evidence_acquisition",
        )
        self.assertEqual(
            result["routing_decision"]["routing_evidence_status"],
            "requires_evidence_acquisition",
        )
        self.assertIn(
            "osteoarthritis_or_degenerative_hip_disease",
            result["routing_decision"]["differential_knowledge_candidates"],
        )
        hypotheses = result["routing_decision"]["clinical_hypotheses"]
        self.assertEqual(hypotheses[0]["role"], "primary")
        self.assertEqual(hypotheses[0]["disease_key"], "femoral_head_necrosis")
        self.assertEqual(hypotheses[0]["status"], "requires_evidence_acquisition")
        self.assertIn("symptom", hypotheses[0]["reason"])
        self.assertIn(
            "osteoarthritis_or_degenerative_hip_disease",
            [item["disease_key"] for item in hypotheses if item["role"] == "differential"],
        )

    def test_service_routes_fhn_as_hypothesis_not_default_positive_disease(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "右髋疼痛，怀疑股骨头坏死，上传 X 光片",
                "image_path": "output/fake/uploads/right_hip_ap_xray.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        routing = result["routing_decision"]
        self.assertEqual(routing["primary_hypothesis"], "femoral_head_necrosis")
        self.assertEqual(routing["selected_knowledge"], "femoral_head_necrosis")
        self.assertEqual(routing["initial_evidence_status"], "requires_evidence_acquisition")
        self.assertNotEqual(routing["initial_evidence_status"], "supported")
        self.assertIn("clinical hypothesis", routing["knowledge_search_reason"])
        self.assertEqual(routing["differential_knowledge_candidates"], [])
        self.assertEqual(routing["display_differential_knowledge_candidates"], [])
        self.assertEqual(len(routing["clinical_hypotheses"]), 1)

    def test_service_keeps_explicit_fhn_disease_key_focused_without_differentials(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "请用股骨头坏死 knowledge 分析这张 X 光片",
                "image_path": "output/fake/uploads/right_hip_ap_xray.png",
                "disease_key": "femoral_head_necrosis",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "vision_mode": "real_vlm_validation",
            }
        )

        routing = result["routing_decision"]
        self.assertEqual(routing["source"], "explicit")
        self.assertEqual(routing["selected_knowledge"], "femoral_head_necrosis")
        self.assertEqual(routing["differential_knowledge_candidates"], [])
        self.assertEqual(routing["display_differential_knowledge_candidates"], [])
        self.assertEqual(len(routing["clinical_hypotheses"]), 1)

    def test_service_preserves_prompt_clinical_context_for_fhn_diagnosis(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        service.handle_request(
            {
                "patient_message": "右髋疼痛三个月，走路后加重，长期激素治疗，偶尔饮酒，无明显外伤史，上传 X 光片",
                "image_path": "output/fake/uploads/right_hip_ap_xray.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        forwarded_info = fake_doctor.calls[0]["patient_info"]
        self.assertIn("clinical_context", forwarded_info)
        self.assertIn("长期激素治疗", forwarded_info["clinical_context"])
        self.assertIn("偶尔饮酒", forwarded_info["clinical_context"])
        self.assertEqual(
            forwarded_info["clinical_context_source"],
            "patient_message",
        )
        structured = forwarded_info["structured_clinical_context"]
        self.assertEqual(structured["schema_version"], "clinical_context_extraction.v1")
        self.assertEqual(structured["source"], "patient_message")
        self.assertIn("走路后加重", structured["source_text"])
        fields = structured["fields"]
        self.assertEqual(fields["symptoms"]["values"], ["hip_pain"])
        self.assertEqual(fields["duration"]["value"], "三个月")
        self.assertEqual(fields["laterality"]["value"], "right")
        self.assertEqual(fields["pain_location"]["value"], "hip")
        self.assertEqual(fields["aggravating_factors"]["values"], ["walking_or_activity"])
        self.assertEqual(fields["steroid_use"]["status"], "present")
        self.assertEqual(fields["alcohol_use"]["status"], "present")
        self.assertEqual(fields["trauma_history"]["status"], "absent")
        self.assertEqual(
            structured["provided_risk_factors"],
            ["corticosteroid_use", "alcohol_use"],
        )
        self.assertNotIn("trauma_history", structured["provided_risk_factors"])
        self.assertEqual(structured["risk_factor_role"], "suspicion_modifier_only")

    def test_service_marks_unprovided_clinical_prompt_fields_as_missing(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        service.handle_request(
            {
                "patient_message": "左髋疼痛，上传 X 光片",
                "image_path": "output/fake/uploads/left_hip_ap_xray.png",
                "patient_info": {},
            }
        )

        structured = fake_doctor.calls[0]["patient_info"]["structured_clinical_context"]
        fields = structured["fields"]
        self.assertEqual(fields["laterality"]["value"], "left")
        self.assertEqual(fields["pain_location"]["value"], "hip")
        self.assertEqual(fields["duration"]["status"], "missing")
        self.assertEqual(fields["aggravating_factors"]["status"], "missing")
        self.assertEqual(fields["steroid_use"]["status"], "missing")
        self.assertEqual(fields["alcohol_use"]["status"], "missing")
        self.assertEqual(fields["trauma_history"]["status"], "missing")
        self.assertIn("duration", structured["missing_fields"])
        self.assertIn("steroid_use", structured["missing_fields"])

    def test_service_marks_fhn_with_degenerative_clues_for_bounded_differential_review(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "左髋疼痛，X 光有关节间隙变窄和退变，也担心股骨头坏死",
                "image_path": "output/fake/uploads/left_hip_ap_xray.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            }
        )

        routing = result["routing_decision"]
        self.assertEqual(routing["primary_hypothesis"], "femoral_head_necrosis")
        self.assertIn(
            "osteoarthritis_or_degenerative_hip_disease",
            routing["differential_knowledge_candidates"],
        )
        self.assertEqual(routing["initial_evidence_status"], "requires_differential_review")
        self.assertEqual(routing["routing_evidence_status"], "requires_differential_review")
        self.assertEqual(result["alignment_plan"]["analysis_status"], "partial_evidence")

    def test_service_ranks_fhn_differential_candidates_and_deprioritizes_denied_trauma(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)

        result = service.handle_request(
            {
                "patient_message": "右髋疼痛三个月，走路后加重，长期激素治疗，偶尔饮酒，无明显外伤史。请结合这张髋关节 X 光片分析可能方向。",
                "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "vision_mode": "real_vlm_validation",
            }
        )

        ranking = result["routing_decision"]["differential_candidate_ranking"]
        by_key = {item["disease_key"]: item for item in ranking}
        self.assertEqual(
            by_key["osteoarthritis_or_degenerative_hip_disease"]["display_group"],
            "strong_differential",
        )
        self.assertEqual(
            by_key["post_traumatic_change"]["display_group"],
            "low_priority",
        )
        self.assertEqual(
            by_key["post_traumatic_change"]["deprioritized_by"],
            "denied_trauma_history",
        )
        self.assertEqual(
            result["routing_decision"]["display_differential_knowledge_candidates"],
            ["osteoarthritis_or_degenerative_hip_disease"],
        )
        hypotheses = result["routing_decision"]["clinical_hypotheses"]
        post_traumatic = next(
            item for item in hypotheses if item["disease_key"] == "post_traumatic_change"
        )
        self.assertEqual(post_traumatic["display_group"], "low_priority")
        self.assertEqual(post_traumatic["priority"], 4)

    def test_service_primary_only_mode_keeps_secondary_candidates_display_only_by_default(self):
        fake_doctor = FakeInsufficientEvidenceDoctor()
        knowledge_tool = FhnOnlyKnowledgeTool()
        service = MedScopeService(
            gaodoctor_agent=fake_doctor,
            knowledge_tool=knowledge_tool,
        )

        result = service.handle_request(
            {
                "patient_message": "右髋疼痛三个月，走路后加重，长期激素治疗，偶尔饮酒，无明显外伤史。请结合这张髋关节 X 光片分析可能方向。",
                "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "vision_mode": "real_vlm_validation",
            }
        )

        routing = result["routing_decision"]
        self.assertEqual(routing["knowledge_selection_mode"], "primary_only")
        self.assertIn(
            "osteoarthritis_or_degenerative_hip_disease",
            routing["display_differential_knowledge_candidates"],
        )
        plan = routing["secondary_knowledge_run_plan"]
        self.assertEqual(plan["status"], "not_triggered")
        self.assertFalse(plan["triggered"])
        self.assertEqual(plan["candidates"], [])
        self.assertIn("primary-only", plan["reason"])
        self.assertEqual(knowledge_tool.prepare_calls, [])

    def test_service_agent_auto_mode_builds_secondary_knowledge_run_plan_after_insufficient_primary_evidence(self):
        fake_doctor = FakeInsufficientEvidenceDoctor()
        knowledge_tool = FhnOnlyKnowledgeTool()
        service = MedScopeService(
            gaodoctor_agent=fake_doctor,
            knowledge_tool=knowledge_tool,
        )

        result = service.handle_request(
            {
                "patient_message": "右髋疼痛三个月，走路后加重，长期激素治疗，偶尔饮酒，无明显外伤史。请结合这张髋关节 X 光片分析可能方向。",
                "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "vision_mode": "real_vlm_validation",
                "knowledge_selection_mode": "agent_auto_secondary",
            }
        )

        self.assertEqual(
            result["routing_decision"]["knowledge_selection_mode"],
            "agent_auto_secondary",
        )
        plan = result["routing_decision"]["secondary_knowledge_run_plan"]
        self.assertEqual(plan["status"], "secondary_hypothesis_validation_ready")
        self.assertTrue(plan["triggered"])
        self.assertEqual(plan["primary_knowledge"], "femoral_head_necrosis")
        self.assertEqual(plan["trigger_reason"], "primary_evidence_insufficient")
        self.assertEqual(
            [item["disease_key"] for item in plan["candidates"]],
            ["osteoarthritis_or_degenerative_hip_disease"],
        )
        candidate = plan["candidates"][0]
        self.assertEqual(
            candidate["action"],
            "run_unreviewed_knowledge_hypothesis_validation",
        )
        self.assertEqual(candidate["knowledge_builder_action"], "search_or_generate_knowledge")
        self.assertEqual(candidate["review_status"], "unreviewed")
        self.assertEqual(candidate["use_scope"], "hypothesis_validation_only")
        self.assertTrue(candidate["analysis_allowed"])
        self.assertFalse(candidate["diagnosis_allowed"])
        self.assertEqual(len(fake_doctor.calls), 1)
        self.assertEqual(
            knowledge_tool.prepare_calls[0]["disease_key"],
            "osteoarthritis_or_degenerative_hip_disease",
        )
        secondary_analysis = result["secondary_knowledge_analysis"]
        self.assertEqual(
            [item["disease_key"] for item in secondary_analysis],
            ["osteoarthritis_or_degenerative_hip_disease"],
        )
        self.assertEqual(
            secondary_analysis[0]["analysis_mode"],
            "hypothesis_validation_only",
        )
        self.assertEqual(secondary_analysis[0]["knowledge_builder_status"], "proposal_prepared")
        self.assertFalse(secondary_analysis[0]["diagnosis_allowed"])
        self.assertFalse(secondary_analysis[0]["formal_knowledge_updated"])
        self.assertIn("备用 Knowledge 复查结果", result["report"])
        self.assertEqual(
            result["report"]["备用 Knowledge 复查结果"][0]["disease_key"],
            "osteoarthritis_or_degenerative_hip_disease",
        )
        self.assertFalse(knowledge_tool.prepare_calls[0]["persist"])

    def test_service_manual_secondary_mode_uses_user_selected_backup_knowledge(self):
        with TemporaryDirectory() as tmpdir:
            fake_doctor = FakeInsufficientEvidenceDoctor()
            knowledge_tool = FhnOnlyKnowledgeTool()
            service = MedScopeService(
                gaodoctor_agent=fake_doctor,
                knowledge_tool=knowledge_tool,
                secondary_knowledge_proposal_dir=Path(tmpdir) / "secondary_knowledge_proposals",
            )

            result = service.handle_request(
                {
                    "patient_message": "右髋疼痛三个月，走路后加重。请先看主方向，同时备用检查退行性髋关节病变。",
                    "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "vision_mode": "real_vlm_validation",
                    "knowledge_selection_mode": "manual_secondary",
                    "manual_secondary_knowledge_candidates": [
                        "osteoarthritis_or_degenerative_hip_disease",
                    ],
                }
            )

            routing = result["routing_decision"]
            self.assertEqual(routing["knowledge_selection_mode"], "manual_secondary")
            self.assertEqual(
                routing["manual_secondary_knowledge_candidates"],
                ["osteoarthritis_or_degenerative_hip_disease"],
            )
            plan = routing["secondary_knowledge_run_plan"]
            self.assertEqual(plan["status"], "manual_secondary_hypothesis_validation_ready")
            self.assertTrue(plan["triggered"])
            self.assertEqual(plan["trigger_reason"], "manual_secondary_knowledge_selected")
            self.assertEqual(
                [item["disease_key"] for item in plan["candidates"]],
                ["osteoarthritis_or_degenerative_hip_disease"],
            )
            self.assertEqual(
                plan["candidates"][0]["action"],
                "run_unreviewed_knowledge_hypothesis_validation",
            )
            self.assertEqual(plan["candidates"][0]["candidate_status"], "selected_for_knowledgebuilder")
            self.assertEqual(plan["candidates"][0]["knowledge_builder_status"], "proposal_prepared")
            self.assertTrue(plan["candidates"][0]["selected_by_user"])
            self.assertEqual(
                [step["status"] for step in plan["candidates"][0]["knowledge_builder_progress"]],
                ["done", "done", "done"],
            )
            self.assertFalse(plan["candidates"][0]["diagnosis_allowed"])
            self.assertEqual(
                knowledge_tool.prepare_calls[0]["disease_key"],
                "osteoarthritis_or_degenerative_hip_disease",
            )
            secondary_analysis = result["secondary_knowledge_analysis"]
            self.assertEqual(
                [item["disease_key"] for item in secondary_analysis],
                ["osteoarthritis_or_degenerative_hip_disease"],
            )
            self.assertEqual(secondary_analysis[0]["analysis_mode"], "hypothesis_validation_only")
            self.assertEqual(secondary_analysis[0]["knowledge_builder_status"], "proposal_prepared")
            self.assertEqual(
                secondary_analysis[0]["workflow_stage"],
                "unreviewed_knowledge_hypothesis_validation_completed",
            )
            self.assertEqual(secondary_analysis[0]["candidate_status"], "selected_for_knowledgebuilder")
            self.assertTrue(secondary_analysis[0]["selected_by_user"])
            self.assertIn("KnowledgeBuilder", secondary_analysis[0]["finding"])
            self.assertIn("knowledge_builder_proposal_detail", secondary_analysis[0])
            self.assertIn("guideline_evidence_summary", secondary_analysis[0])
            self.assertIn(
                "ACR Appropriateness Criteria Chronic Hip Pain",
                secondary_analysis[0]["guideline_evidence_summary"]["source_titles"],
            )
            self.assertIn("differential_review", secondary_analysis[0])
            self.assertIn("expected_evidence_to_check", secondary_analysis[0]["differential_review"])
            self.assertIn("current_observation_summary", secondary_analysis[0]["differential_review"])
            self.assertIn("report_sentence", secondary_analysis[0]["differential_review"])
            self.assertIn(
                "骨关节炎或退行性髋关节病变",
                secondary_analysis[0]["differential_review"]["report_sentence"],
            )
            self.assertIn("证据支持度", secondary_analysis[0]["differential_review"]["report_sentence"])
            self.assertIn("不能替代医生诊断", secondary_analysis[0]["differential_review"]["report_sentence"])
            self.assertFalse(secondary_analysis[0]["diagnosis_allowed"])
            self.assertFalse(secondary_analysis[0]["formal_knowledge_updated"])

    def test_service_manual_secondary_runs_candidate_visual_protocol_for_own_evidence_bundle(self):
        with TemporaryDirectory() as tmpdir:
            fake_doctor = FakeInsufficientEvidenceDoctor()
            visual_runner = FakeSecondaryVisualEvidenceRunner()
            service = MedScopeService(
                gaodoctor_agent=fake_doctor,
                knowledge_tool=FhnOnlyKnowledgeTool(),
                secondary_knowledge_proposal_dir=Path(tmpdir) / "secondary_knowledge_proposals",
                secondary_visual_evidence_runner=visual_runner,
            )

            result = service.handle_request(
                {
                    "patient_message": "右髋疼痛三个月，备用检查退行性髋关节病变。",
                    "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "vision_mode": "real_vlm_validation",
                    "knowledge_selection_mode": "manual_secondary",
                    "manual_secondary_knowledge_candidates": [
                        "osteoarthritis_or_degenerative_hip_disease",
                    ],
                }
            )

            self.assertEqual(len(visual_runner.calls), 1)
            call = visual_runner.calls[0]
            self.assertEqual(call["disease_key"], "osteoarthritis_or_degenerative_hip_disease")
            self.assertEqual(call["vision_mode"], "real_vlm_validation")
            self.assertEqual(
                call["disease_knowledge"]["visual_protocol"]["disease_target"],
                "osteoarthritis_or_degenerative_hip_disease",
            )
            secondary = result["secondary_knowledge_analysis"][0]
            self.assertEqual(secondary["secondary_visual_status"], "ok")
            self.assertEqual(
                secondary["secondary_visual_protocol_status"],
                "executed_with_candidate_knowledge",
            )
            self.assertEqual(
                secondary["secondary_visual_evidence_bundle"]["disease_target"],
                "osteoarthritis_or_degenerative_hip_disease",
            )
            review = secondary["differential_review"]
            self.assertEqual(review["diagnostic_confidence"]["confidence_level"], "moderate")
            self.assertIn("关节间隙变窄", review["diagnostic_confidence"]["basis"])
            self.assertIn("骨赘", review["diagnostic_confidence"]["basis"])
            self.assertIn("按备用 Knowledge 自己的视觉协议", review["report_sentence"])
            self.assertEqual(
                result["report"]["备用 Knowledge 复查结果"][0]["secondary_visual_status"],
                "ok",
            )

    def test_service_default_secondary_runner_calls_vlm_with_candidate_visual_protocol(self):
        with TemporaryDirectory() as tmpdir:
            prompt_runner = FakeSecondaryVlmPromptRunner()
            fake_doctor = FakeInsufficientEvidenceDoctorWithVlm(prompt_runner)
            service = MedScopeService(
                gaodoctor_agent=fake_doctor,
                knowledge_tool=FhnOnlyKnowledgeTool(),
                secondary_knowledge_proposal_dir=Path(tmpdir) / "secondary_knowledge_proposals",
            )

            result = service.handle_request(
                {
                    "patient_message": "右髋疼痛三个月，备用检查退行性髋关节病变。",
                    "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "vision_mode": "real_vlm_validation",
                    "knowledge_selection_mode": "manual_secondary",
                    "manual_secondary_knowledge_candidates": [
                        "osteoarthritis_or_degenerative_hip_disease",
                    ],
                }
            )

            self.assertEqual(len(prompt_runner.calls), 1)
            call = prompt_runner.calls[0]
            self.assertEqual(call["task"], "secondary_visual_evidence_extraction")
            self.assertEqual(
                call["user_payload"]["disease_key"],
                "osteoarthritis_or_degenerative_hip_disease",
            )
            self.assertEqual(
                call["user_payload"]["visual_protocol"]["disease_target"],
                "osteoarthritis_or_degenerative_hip_disease",
            )
            secondary = result["secondary_knowledge_analysis"][0]
            self.assertEqual(secondary["secondary_visual_status"], "ok")
            self.assertEqual(
                secondary["secondary_visual_protocol_status"],
                "executed_with_candidate_knowledge",
            )
            bundle = secondary["secondary_visual_evidence_bundle"]
            self.assertEqual(bundle["disease_target"], "osteoarthritis_or_degenerative_hip_disease")
            self.assertEqual(bundle["present_findings"], ["joint_space_narrowing", "osteophyte"])
            self.assertEqual(
                [finding["display_name"] for finding in bundle["findings"]],
                ["关节间隙变窄", "骨赘"],
            )
            confidence = secondary["differential_review"]["diagnostic_confidence"]
            self.assertEqual(confidence["confidence_level"], "moderate")
            self.assertIn("关节间隙变窄", confidence["basis"])
            self.assertIn("骨赘", confidence["basis"])

    def test_service_manual_secondary_mode_keeps_three_user_selected_backup_knowledges(self):
        service = MedScopeService(
            gaodoctor_agent=FakeInsufficientEvidenceDoctor(),
            knowledge_tool=FhnOnlyKnowledgeTool(),
        )

        result = service.handle_request(
            {
                "patient_message": "右髋疼痛三个月，请备用复查退变、外伤后改变和发育不良相关退变。",
                "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "vision_mode": "real_vlm_validation",
                "knowledge_selection_mode": "manual_secondary",
                "manual_secondary_knowledge_candidates": [
                    "osteoarthritis_or_degenerative_hip_disease",
                    "post_traumatic_change",
                    "developmental_dysplasia_related_degeneration",
                ],
            }
        )

        expected = [
            "osteoarthritis_or_degenerative_hip_disease",
            "post_traumatic_change",
            "developmental_dysplasia_related_degeneration",
        ]
        routing = result["routing_decision"]
        self.assertEqual(routing["manual_secondary_knowledge_candidates"], expected)
        self.assertEqual(routing["secondary_knowledge_run_plan"]["max_secondary_runs"], 3)
        self.assertEqual(
            [item["disease_key"] for item in routing["secondary_knowledge_run_plan"]["candidates"]],
            expected,
        )
        self.assertEqual(
            [item["disease_key"] for item in result["secondary_knowledge_analysis"]],
            expected,
        )
        self.assertIn("备用 Knowledge 复查结果", result["report"])
        self.assertEqual(
            [item["disease_key"] for item in result["report"]["备用 Knowledge 复查结果"]],
            expected,
        )

    def test_service_manual_secondary_runs_each_candidate_visual_protocol_and_scores_independently(self):
        visual_runner = FakeMultiSecondaryVisualEvidenceRunner()
        service = MedScopeService(
            gaodoctor_agent=FakeInsufficientEvidenceDoctor(),
            knowledge_tool=FhnOnlyKnowledgeTool(),
            secondary_visual_evidence_runner=visual_runner,
        )

        result = service.handle_request(
            {
                "patient_message": "右髋疼痛三个月，请备用复查退变、外伤后改变和发育不良相关退变。",
                "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "vision_mode": "real_vlm_validation",
                "knowledge_selection_mode": "manual_secondary",
                "manual_secondary_knowledge_candidates": [
                    "osteoarthritis_or_degenerative_hip_disease",
                    "post_traumatic_change",
                    "developmental_dysplasia_related_degeneration",
                ],
            }
        )

        expected = [
            "osteoarthritis_or_degenerative_hip_disease",
            "post_traumatic_change",
            "developmental_dysplasia_related_degeneration",
        ]
        self.assertEqual([call["disease_key"] for call in visual_runner.calls], expected)
        self.assertEqual(
            [
                call["disease_knowledge"]["visual_protocol"]["disease_target"]
                for call in visual_runner.calls
            ],
            expected,
        )

        analysis_by_key = {
            item["disease_key"]: item for item in result["secondary_knowledge_analysis"]
        }
        self.assertEqual(
            analysis_by_key["osteoarthritis_or_degenerative_hip_disease"][
                "secondary_visual_evidence_bundle"
            ]["present_findings"],
            ["joint_space_narrowing", "osteophyte", "subchondral_sclerosis"],
        )
        oa_confidence = analysis_by_key["osteoarthritis_or_degenerative_hip_disease"][
            "differential_review"
        ]["diagnostic_confidence"]
        self.assertEqual(oa_confidence["confidence_level"], "high")
        self.assertGreaterEqual(oa_confidence["confidence_score"], 0.75)
        self.assertIn("关节间隙变窄", oa_confidence["basis"])
        self.assertIn("骨赘", oa_confidence["basis"])

        trauma_confidence = analysis_by_key["post_traumatic_change"][
            "differential_review"
        ]["diagnostic_confidence"]
        self.assertEqual(trauma_confidence["confidence_level"], "low")
        self.assertIn("骨折或外伤相关线索", trauma_confidence["basis"])

        dysplasia_confidence = analysis_by_key["developmental_dysplasia_related_degeneration"][
            "differential_review"
        ]["diagnostic_confidence"]
        self.assertEqual(dysplasia_confidence["confidence_level"], "insufficient")
        self.assertEqual(
            analysis_by_key["developmental_dysplasia_related_degeneration"][
                "secondary_visual_evidence_bundle"
            ]["present_findings"],
            [],
        )

    def test_service_adds_high_support_confidence_for_fhn_xray_cystic_and_sclerosis(self):
        service = MedScopeService(
            gaodoctor_agent=FakeStrongFhnEvidenceDoctor(),
            knowledge_tool=FhnOnlyKnowledgeTool(),
        )

        result = service.handle_request(
            {
                "patient_message": "右髋疼痛三个月，X 光有硬化带和囊性变，判断股骨头坏死。",
                "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "disease_key": "femoral_head_necrosis",
                "vision_mode": "real_vlm_validation",
            }
        )

        confidence = result["diagnostic_confidence"][0]
        self.assertEqual(confidence["disease_key"], "femoral_head_necrosis")
        self.assertEqual(confidence["confidence_level"], "high")
        self.assertGreaterEqual(confidence["confidence_score"], 0.8)
        self.assertIn("影像证据高度支持", confidence["label"])
        self.assertIn("MRI", confidence["caveat"])
        self.assertIn("硬化带", confidence["basis"])
        self.assertIn("囊性变", confidence["basis"])
        self.assertIn("诊断置信度", result["report"])
        self.assertNotIn("不能确认", result["report"]["诊断置信度"][0]["display_sentence"])

    def test_service_confidence_reads_visual_bundle_findings_used_by_patient_ui(self):
        class FindingsOnlyDoctor(FakeGaoDoctor):
            def handle_message(self, *args, **kwargs):
                super().handle_message(*args, **kwargs)
                return {
                    "case_id": "case_new",
                    "intent": "diagnosis",
                    "reply_to_patient": "ok",
                    "visual_evidence_bundle": {
                        "findings": [
                            {
                                "target": "sclerotic_band",
                                "display_name": "硬化带",
                                "evidence_text": "右侧股骨头软骨下硬化带",
                            },
                            {
                                "target": "cystic_change",
                                "display_name": "囊性变",
                                "evidence_text": "右侧股骨头内囊性变",
                            },
                        ],
                    },
                    "report": {
                        "target_disease_assessment": {
                            "target_disease": kwargs.get("disease_key"),
                            "evidence_status": "insufficient",
                        },
                        "integrated_reasoning_summary": {
                            "target_disease": kwargs.get("disease_key"),
                            "evidence_status": "insufficient",
                            "can_confirm_target_disease": False,
                        },
                    },
                }

        result = MedScopeService(
            gaodoctor_agent=FindingsOnlyDoctor(),
            knowledge_tool=FhnOnlyKnowledgeTool(),
        ).handle_request(
            {
                "patient_message": "右髋疼痛，X 光有硬化带和囊性变，判断股骨头坏死。",
                "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "disease_key": "femoral_head_necrosis",
                "vision_mode": "real_vlm_validation",
            }
        )

        confidence = result["diagnostic_confidence"][0]
        self.assertEqual(confidence["confidence_level"], "high")
        self.assertIn("硬化带", confidence["basis"])
        self.assertIn("囊性变", confidence["basis"])

    def test_service_secondary_review_does_not_use_patient_reply_as_image_observation(self):
        with TemporaryDirectory() as tmpdir:
            fake_doctor = FakeVerboseInsufficientEvidenceDoctor()
            service = MedScopeService(
                gaodoctor_agent=fake_doctor,
                knowledge_tool=FhnOnlyKnowledgeTool(),
                secondary_knowledge_proposal_dir=Path(tmpdir) / "secondary_knowledge_proposals",
            )

            result = service.handle_request(
                {
                    "patient_message": "右髋疼痛三个月，走路后加重。备用检查退行性髋关节病变。",
                    "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "vision_mode": "real_vlm_validation",
                    "knowledge_selection_mode": "manual_secondary",
                    "manual_secondary_knowledge_candidates": [
                        "osteoarthritis_or_degenerative_hip_disease",
                    ],
                }
            )

            review = result["secondary_knowledge_analysis"][0]["differential_review"]
            self.assertNotIn("您好，我是高医生", review["current_observation_summary"])
            self.assertNotIn("您好，我是高医生", review["report_sentence"])
            self.assertIn(
                "当前没有形成足够稳定的备用疾病专属影像证据",
                review["current_observation_summary"],
            )

    def test_service_manual_secondary_writes_reviewable_unreviewed_knowledge_artifact(self):
        with TemporaryDirectory() as tmpdir:
            fake_doctor = FakeInsufficientEvidenceDoctor()
            knowledge_tool = FhnOnlyKnowledgeTool()
            proposal_dir = Path(tmpdir) / "output" / "fake" / "secondary_knowledge_proposals"
            service = MedScopeService(
                gaodoctor_agent=fake_doctor,
                knowledge_tool=knowledge_tool,
                secondary_knowledge_proposal_dir=proposal_dir,
            )

            result = service.handle_request(
                {
                    "patient_message": "右髋疼痛三个月，走路后加重。备用检查退行性髋关节病变。",
                    "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "vision_mode": "real_vlm_validation",
                    "knowledge_selection_mode": "manual_secondary",
                    "manual_secondary_knowledge_candidates": [
                        "osteoarthritis_or_degenerative_hip_disease",
                    ],
                }
            )

            secondary = result["secondary_knowledge_analysis"][0]
            detail = secondary["knowledge_builder_proposal_detail"]
            artifact_path = Path(detail["proposal_artifact_path"])
            self.assertTrue(artifact_path.exists())
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["schema_version"], "secondary_knowledge_proposal.v1")
            self.assertEqual(
                artifact["candidate_key"],
                "osteoarthritis_or_degenerative_hip_disease",
            )
            self.assertEqual(artifact["knowledge_builder_status"], "proposal_prepared")
            self.assertEqual(artifact["review_queue_status"], "entered_knowledge_review_queue")
            self.assertFalse(artifact["diagnosis_allowed"])
            self.assertFalse(artifact["formal_knowledge_updated"])
            self.assertIn("proposal_knowledge", artifact)
            self.assertEqual(artifact["proposal_knowledge"]["knowledge_type"], "guideline_based")
            self.assertEqual(artifact["proposal_knowledge"]["evidence_level"], "high")
            self.assertTrue(artifact["proposal_knowledge"]["source_documents"])
            self.assertIn("ACR Appropriateness Criteria", artifact["proposal_knowledge"]["source"])
            self.assertEqual(artifact["proposal_knowledge"]["path_type"], "guideline_aware_evidence_pipeline")
            self.assertIn("clinical_features", artifact["proposal_knowledge"])
            self.assertIn("髋关节疼痛", artifact["proposal_knowledge"]["clinical_features"]["common_symptoms"])
            self.assertIn("required_image_views", artifact["proposal_knowledge"])
            self.assertIn("骨盆/髋关节 X 光正位", artifact["proposal_knowledge"]["required_image_views"])
            self.assertIn("visual_targets", artifact["proposal_knowledge"])
            self.assertIn("髋关节间隙", artifact["proposal_knowledge"]["visual_targets"]["anatomy"])
            self.assertNotIn("candidate_observation_rules", artifact["proposal_knowledge"])
            self.assertTrue(artifact["proposal_knowledge"]["source_priority"])
            self.assertTrue(artifact["proposal_knowledge"]["guideline_extraction"]["citations"])
            self.assertTrue(artifact["proposal_knowledge"]["guideline_documents"])
            visual_protocol = artifact["proposal_knowledge"]["visual_protocol"]
            self.assertEqual(
                visual_protocol["disease_target"],
                "osteoarthritis_or_degenerative_hip_disease",
            )
            self.assertTrue(visual_protocol["finding_targets"])
            self.assertIn("diagnosis_scope", visual_protocol)
            self.assertIn("insufficiency_rules", visual_protocol)
            self.assertIn(
                "required_image_views",
                [
                    section["heading"]
                    for document in artifact["proposal_knowledge"]["guideline_documents"]
                    for section in document["sections"]
                ],
            )
            self.assertEqual(
                artifact["proposal_knowledge"]["quality_control"]["citation_status"],
                "verified",
            )
            self.assertIn(
                "ACR Appropriateness Criteria Chronic Hip Pain",
                artifact["knowledge_builder_proposal_detail"]["source_titles"],
            )
            self.assertIn(
                "required_image_views",
                artifact["knowledge_builder_proposal_detail"]["guideline_sections"],
            )
            self.assertEqual(
                artifact["proposal_knowledge"]["quality_control"]["formal_knowledge_status"],
                "needs_review",
            )
            self.assertEqual(
                secondary["workflow_stage"],
                "unreviewed_knowledge_hypothesis_validation_completed",
            )
            self.assertIn("可追溯指南/规则来源", secondary["finding"])
            self.assertIn("proposal_artifact_path", detail)

    def test_service_does_not_build_secondary_plan_when_user_explicitly_focuses_fhn_knowledge(self):
        fake_doctor = FakeInsufficientEvidenceDoctor()
        service = MedScopeService(
            gaodoctor_agent=fake_doctor,
            knowledge_tool=FhnOnlyKnowledgeTool(),
        )

        result = service.handle_request(
            {
                "patient_message": "请用股骨头坏死 knowledge 分析这张 X 光片",
                "image_path": "output/fake/uploads/right_hip_ap_xray.png",
                "disease_key": "femoral_head_necrosis",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "vision_mode": "real_vlm_validation",
            }
        )

        plan = result["routing_decision"]["secondary_knowledge_run_plan"]
        self.assertEqual(plan["status"], "not_applicable")
        self.assertFalse(plan["triggered"])
        self.assertEqual(plan["candidates"], [])
        self.assertIn("explicit", plan["reason"])

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
        self.assertEqual(fake_doctor.calls[0]["vision_mode"], "no_mask_knowledge")
        self.assertEqual(result["routing_decision"]["selected_knowledge"], "femoral_head_necrosis")
        self.assertEqual(result["routing_decision"]["selected_vision_mode"], "no_mask_knowledge")
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
            fake_planner.calls[0]["routing_decision"]["selected_knowledge"],
            "femoral_head_necrosis",
        )
        self.assertEqual(
            fake_planner.calls[0]["disease_knowledge"]["knowledge_id"],
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
        self.assertEqual(plan["selected_knowledge"], "femoral_head_necrosis")
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

        self.assertEqual(result["routing_decision"]["selected_knowledge"], "diffuse_glioma_brats")
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
                knowledge_memory={
                    "knowledge_id": "diffuse_glioma_brats_v0.1",
                    "selected_knowledge": "diffuse_glioma_brats",
                    "knowledge_type": "guideline_based",
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
            self.assertEqual(result["runtime_manifest"]["selected_knowledge"], "diffuse_glioma_brats")
            self.assertIn("memory_v1", result["runtime_manifest"]["contracts_checked"])
            self.assertEqual(result["stop_hook_gate"]["schema_version"], "stop_hook_gate.v1")
            self.assertEqual(result["stop_hook_gate"]["case_id"], "case_001")
            self.assertTrue(result["stop_hook_gate"]["runtime_safety"]["read_only"])
            self.assertFalse(result["stop_hook_gate"]["runtime_safety"]["formal_knowledge_updated"])
            self.assertEqual(
                result["self_evolving_queue"]["schema_version"],
                "self_evolving_queue.v1",
            )
            self.assertEqual(result["self_evolving_queue"]["case_id"], "case_001")
            self.assertEqual(result["self_evolving_queue"]["status"], "candidate_only")
            self.assertTrue(result["self_evolving_queue"]["runtime_safety"]["queue_written"])
            self.assertFalse(
                result["self_evolving_queue"]["runtime_safety"]["formal_knowledge_updated"]
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
