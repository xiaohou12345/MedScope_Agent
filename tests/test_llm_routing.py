import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.gaodoctor_agent import GaoDoctorAgent
from llm.model_client import (
    ApiRouteLog,
    ChatResponse,
    OpenAICompatibleModelClient,
    RecordingModelClient,
)
from llm.prompt_runner import PromptRunner
from memory.memory_manager import MemoryManager


class LlmRoutingTest(unittest.TestCase):
    def _save_fact_usage_case(self, memory: MemoryManager, case_id: str) -> None:
        visual_fact_usage = {
            "used": [
                {
                    "finding_id": "finding_1_sclerotic_band",
                    "target": "sclerotic_band",
                    "display_name": "硬化带",
                    "status": "candidate_present",
                    "laterality": "image_left",
                    "diagnosis_usable": True,
                    "independent_evidence": True,
                    "alignment_status": "aligned",
                    "summary_text": "image_left; 硬化带; candidate_present; independent_evidence",
                }
            ],
            "excluded": [
                {
                    "finding_id": "finding_2_cystic_change",
                    "target": "cystic_change",
                    "display_name": "囊性变",
                    "status": "candidate_present",
                    "laterality": "image_left",
                    "diagnosis_usable": True,
                    "independent_evidence": False,
                    "non_independent_reason": "overlaps_existing_finding",
                    "overlap_with_finding_id": "finding_1_sclerotic_band",
                    "alignment_status": "aligned",
                    "summary_text": "image_left; 囊性变; candidate_present; non_independent_evidence",
                    "exclusion_reason": "non_independent_evidence",
                }
            ],
            "used_count": 1,
            "excluded_count": 1,
        }
        memory.save_case_memory(
            case_id=case_id,
            patient_memory={
                "patient_id": "patient_001",
                "patient_message": "右髋疼痛，上传 X 光",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
                "symptoms": ["髋关节疼痛"],
                "intent": "diagnosis",
            },
            image_memory={
                "image_path": "hip.png",
                "modality": "xray",
                "body_part": "hip",
                "visual_evidence": {"segmentation_quality": "medium_candidate"},
                "visual_evidence_bundle": {
                    "schema_version": "visual_evidence_bundle.v1",
                    "structured_visual_facts": visual_fact_usage["used"]
                    + visual_fact_usage["excluded"],
                },
            },
            skill_memory={
                "skill_id": "femoral_head_necrosis_v0.1",
                "selected_skill": "femoral_head_necrosis",
                "skill_type": "guideline_based",
            },
            reasoning_memory={
                "diagnostic_tendency": "疑似股骨头坏死影像表现",
                "key_evidence": ["X 光候选征象：图像左侧硬化带"],
                "uncertainty": ["图像左侧囊性变与硬化带重叠，不作为独立诊断依据"],
                "follow_up": ["建议完善双髋 MRI"],
                "treatment_advice": ["线下复核"],
                "visual_fact_usage": visual_fact_usage,
            },
        )

    def test_api_route_log_selects_active_route_without_network(self):
        with TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "API_ROUTE_LOG.md"
            log_path.write_text(
                "\n".join(
                    [
                        "# API Route Log",
                        "",
                        "active_route: dmx",
                        "dmx_model: dmx-medical-chat",
                        "ky_model: ky-self-hosted-medical",
                    ]
                ),
                encoding="utf-8",
            )

            route_log = ApiRouteLog.from_file(log_path)

            self.assertEqual(route_log.active_route, "dmx")
            self.assertEqual(route_log.model_for_active_route(), "dmx-medical-chat")

    def test_openai_client_normalizes_provider_base_url(self):
        route_log = ApiRouteLog(
            active_route="dmx",
            dmx_base_url="https://anyaigc.com",
            dmx_model="deepseek-v4-pro",
        )
        client = OpenAICompatibleModelClient(route_log=route_log)

        self.assertEqual(
            client.chat_completions_url(),
            "https://anyaigc.com/v1/chat/completions",
        )

    def test_api_route_log_can_select_self_hosted_ky(self):
        with TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "API_ROUTE_LOG.md"
            log_path.write_text(
                "\n".join(
                    [
                        "# API Route Log",
                        "",
                        "active_route: ky",
                        "dmx_model: dmx-medical-chat",
                        "ky_model: ky-self-hosted-medical",
                    ]
                ),
                encoding="utf-8",
            )

            route_log = ApiRouteLog.from_file(log_path)

            self.assertEqual(route_log.active_route, "ky")
            self.assertEqual(route_log.model_for_active_route(), "ky-self-hosted-medical")

    def test_prompt_runner_uses_model_client_contract(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content="患者解释文本",
                model="fake-model",
                route="test",
            )
        )
        runner = PromptRunner(model_client=model_client)

        output = runner.run(
            task="patient_explanation",
            system_prompt="你是高医生",
            user_payload={"诊断倾向": "疑似早期股骨头坏死"},
        )

        self.assertEqual(output, "患者解释文本")
        self.assertEqual(model_client.calls[0]["task"], "patient_explanation")
        self.assertEqual(model_client.calls[0]["messages"][0]["role"], "system")

    def test_gaodoctor_can_use_llm_for_patient_explanation_but_keeps_fallback(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content="LLM 生成的患者解释",
                model="fake-model",
                route="test",
            )
        )
        with TemporaryDirectory() as tmpdir:
            doctor = GaoDoctorAgent(
                memory_manager=MemoryManager(base_dir=Path(tmpdir)),
                prompt_runner=PromptRunner(model_client=model_client),
            )

            result = doctor.handle_patient_case(
                patient_message="左髋疼痛三个月",
                image_path="data/images/demo_xray.png",
                patient_info={
                    "age": 45,
                    "sex": "male",
                    "symptoms": ["髋关节疼痛"],
                },
            )

            self.assertEqual(result["reply_to_patient"], "LLM 生成的患者解释")
            self.assertEqual(model_client.calls[0]["task"], "patient_report_explanation")

    def test_gaodoctor_patient_explanation_falls_back_when_llm_fails(self):
        class FailingModelClient:
            def chat(self, messages, task):
                raise RuntimeError("missing api key")

        with TemporaryDirectory() as tmpdir:
            doctor = GaoDoctorAgent(
                memory_manager=MemoryManager(base_dir=Path(tmpdir)),
                prompt_runner=PromptRunner(model_client=FailingModelClient()),
            )

            result = doctor.handle_patient_case(
                patient_message="左髋疼痛三个月",
                image_path="data/images/demo_xray.png",
                patient_info={
                    "age": 45,
                    "sex": "male",
                    "symptoms": ["髋关节疼痛"],
                },
            )

            self.assertIn("疑似早期股骨头坏死", result["reply_to_patient"])
            self.assertIn("影像上看到", result["reply_to_patient"])

    def test_gaodoctor_uses_llm_for_follow_up_qa_with_evidence_bundle(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content="LLM 基于证据回答：缺少 T1ce 时不能判断强化肿瘤为阴性。",
                model="fake-model",
                route="test",
            )
        )
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_llm"
            memory.save_case_memory(
                case_id=case_id,
                patient_memory={
                    "patient_id": "patient_001",
                    "patient_message": "请看一下 FLAIR MRI",
                    "patient_info": {"symptoms": ["头痛"]},
                    "symptoms": ["头痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "image_path": "flair.nii.gz",
                    "modality": "MRI",
                    "body_part": "brain",
                    "visual_evidence": {
                        "measurements": {
                            "whole_tumor_volume_ml": 117.996,
                            "enhancing_tumor_volume_ml": None,
                        },
                        "completeness": {
                            "whole_tumor": {"status": "supported", "reason": "FLAIR modality available"},
                            "enhancing_tumor": {"status": "missing", "reason": "Requires T1ce modality"},
                        },
                        "segmentation_quality": "ground_truth_nifti",
                    },
                },
                skill_memory={
                    "skill_id": "diffuse_glioma_brats_v0.1",
                    "selected_skill": "diffuse_glioma_brats",
                    "skill_type": "guideline_based",
                    "guideline_evidence": {
                        "citations": [{"title": "EANO guideline"}],
                    },
                },
                reasoning_memory={
                    "diagnostic_tendency": "成人弥漫性胶质瘤影像疑似",
                    "key_evidence": ["whole tumor 体积估计为 117.996 ml"],
                    "uncertainty": ["enhancing_tumor 缺少 T1ce，不能解释为阴性或 0"],
                    "follow_up": ["补全 T1ce"],
                    "treatment_advice": ["线下复核"],
                },
            )
            doctor = GaoDoctorAgent(
                memory_manager=memory,
                prompt_runner=PromptRunner(model_client=model_client),
            )

            answer = doctor.answer_follow_up(
                case_id=case_id,
                question="为什么增强肿瘤没有结果？",
            )
            saved_case = memory.get_case_by_id(case_id)
            qa_entry = saved_case["patient_memory"]["qa_history"][0]
            user_payload = model_client.calls[0]["messages"][1]["content"]

            self.assertEqual(answer, "LLM 基于证据回答：缺少 T1ce 时不能判断强化肿瘤为阴性。")
            self.assertEqual(model_client.calls[0]["task"], "follow_up_qa")
            self.assertIn("evidence_bundle", user_payload)
            self.assertIn("为什么增强肿瘤没有结果？", user_payload)
            self.assertIn("Requires T1ce modality", user_payload)
            self.assertTrue(qa_entry["evidence_bundle_used"])
            self.assertTrue(qa_entry["llm_used"])
            self.assertIsNone(qa_entry["llm_fallback_reason"])

    def test_gaodoctor_rejects_follow_up_llm_answer_that_violates_alignment_plan(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content="可以认为未见强化肿瘤，增强肿瘤为 0 ml。",
                model="fake-model",
                route="test",
            )
        )
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_alignment_blocked"
            memory.save_case_memory(
                case_id=case_id,
                patient_memory={
                    "patient_id": "patient_001",
                    "patient_message": "请看一下 FLAIR MRI",
                    "patient_info": {"symptoms": ["头痛"]},
                    "symptoms": ["头痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "image_path": "flair.nii.gz",
                    "modality": "MRI",
                    "body_part": "brain",
                    "visual_evidence": {
                        "measurements": {
                            "whole_tumor_volume_ml": 117.996,
                            "enhancing_tumor_volume_ml": None,
                        },
                        "completeness": {
                            "whole_tumor": {"status": "supported", "reason": "FLAIR modality available"},
                            "enhancing_tumor": {"status": "missing", "reason": "Requires T1ce modality"},
                        },
                        "segmentation_quality": "ground_truth_nifti",
                    },
                },
                skill_memory={
                    "skill_id": "diffuse_glioma_brats_v0.1",
                    "selected_skill": "diffuse_glioma_brats",
                    "skill_type": "guideline_based",
                    "alignment_plan": {
                        "analysis_status": "partial_evidence",
                        "diagnosis_scope": {
                            "blocked": ["不能从缺失 T1ce 推断无强化"],
                        },
                    },
                },
                reasoning_memory={
                    "diagnostic_tendency": "成人弥漫性胶质瘤影像疑似",
                    "key_evidence": ["whole tumor 体积估计为 117.996 ml"],
                    "uncertainty": ["enhancing_tumor 缺少 T1ce，不能解释为阴性或 0"],
                    "follow_up": ["补全 T1ce"],
                    "treatment_advice": ["线下复核"],
                },
            )
            doctor = GaoDoctorAgent(
                memory_manager=memory,
                prompt_runner=PromptRunner(model_client=model_client),
            )

            answer = doctor.answer_follow_up(
                case_id=case_id,
                question="增强肿瘤是不是没有？",
            )
            saved_case = memory.get_case_by_id(case_id)
            qa_entry = saved_case["patient_memory"]["qa_history"][0]

            self.assertIn("enhancing_tumor 缺少 T1ce", answer)
            self.assertFalse(qa_entry["llm_used"])
            self.assertIn("violates evidence constraints", qa_entry["llm_fallback_reason"])

    def test_gaodoctor_rejects_follow_up_llm_answer_that_uses_excluded_visual_fact(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content="囊性变也是独立诊断依据，可以和硬化带一起支持判断。",
                model="fake-model",
                route="test",
            )
        )
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_excluded_fact"
            self._save_fact_usage_case(memory, case_id)
            doctor = GaoDoctorAgent(
                memory_manager=memory,
                prompt_runner=PromptRunner(model_client=model_client),
            )

            answer = doctor.answer_follow_up(case_id=case_id, question="囊性变能说明什么？")
            saved_case = memory.get_case_by_id(case_id)
            qa_entry = saved_case["patient_memory"]["qa_history"][0]

            self.assertIn("囊性变", answer)
            self.assertIn("不作为独立诊断依据", answer)
            self.assertFalse(qa_entry["llm_used"])
            self.assertIn("excluded visual fact", qa_entry["llm_fallback_reason"])

    def test_gaodoctor_follow_up_template_explains_excluded_visual_fact_reason(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_excluded_fact_template"
            self._save_fact_usage_case(memory, case_id)
            doctor = GaoDoctorAgent(memory_manager=memory)

            answer = doctor.answer_follow_up(case_id=case_id, question="为什么囊性变没有算？")

            self.assertIn("囊性变", answer)
            self.assertIn("non_independent_evidence", answer)
            self.assertIn("不作为独立诊断依据", answer)

    def test_gaodoctor_follow_up_qa_falls_back_when_llm_fails(self):
        class FailingModelClient:
            def __init__(self):
                self.calls = []

            def chat(self, messages, task):
                self.calls.append({"messages": messages, "task": task})
                raise RuntimeError("model unavailable")

        model_client = FailingModelClient()
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_fallback"
            memory.save_case_memory(
                case_id=case_id,
                patient_memory={
                    "patient_message": "左髋疼痛三个月",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "symptoms": ["髋关节疼痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "image_path": "hip.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "visual_evidence": {"segmentation_quality": "simulated"},
                },
                skill_memory={"skill_id": "femoral_head_necrosis_v0.1"},
                reasoning_memory={
                    "diagnostic_tendency": "疑似早期股骨头坏死",
                    "key_evidence": ["股骨头负重区纹理异常"],
                    "uncertainty": ["单纯 X 光对早期病变敏感性有限"],
                },
            )
            doctor = GaoDoctorAgent(
                memory_manager=memory,
                prompt_runner=PromptRunner(model_client=model_client),
            )

            answer = doctor.answer_follow_up(case_id=case_id, question="你刚才说哪里异常？")
            saved_case = memory.get_case_by_id(case_id)
            qa_entry = saved_case["patient_memory"]["qa_history"][0]

            self.assertIn("股骨头负重区纹理异常", answer)
            self.assertEqual(model_client.calls[0]["task"], "follow_up_qa")
            self.assertTrue(qa_entry["evidence_bundle_used"])
            self.assertFalse(qa_entry["llm_used"])
            self.assertIn("model unavailable", qa_entry["llm_fallback_reason"])

    def test_route_log_does_not_require_api_key_for_dry_run_tests(self):
        with TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "API_ROUTE_LOG.md"
            log_path.write_text("active_route: dmx\n", encoding="utf-8")
            previous = os.environ.pop("DMX_API_KEY", None)
            try:
                route_log = ApiRouteLog.from_file(log_path)
                self.assertEqual(route_log.active_route, "dmx")
            finally:
                if previous is not None:
                    os.environ["DMX_API_KEY"] = previous


if __name__ == "__main__":
    unittest.main()
