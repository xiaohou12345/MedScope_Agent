import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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

    def test_api_route_log_keeps_vision_model_separate_from_chat_model(self):
        with TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "API_ROUTE_LOG.md"
            log_path.write_text(
                "\n".join(
                    [
                        "# API Route Log",
                        "",
                        "active_route: dmx",
                        "dmx_model: deepseek-v4-pro",
                        "dmx_vision_model: gpt-5.5",
                        "ky_model: ky-self-hosted-medical",
                        "ky_vision_model: ky-self-hosted-vision",
                    ]
                ),
                encoding="utf-8",
            )

            route_log = ApiRouteLog.from_file(log_path)

            self.assertEqual(route_log.model_for_active_route(), "deepseek-v4-pro")
            self.assertEqual(route_log.vision_model_for_active_route(), "gpt-5.5")

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

    def test_openai_client_normalizes_responses_base_url(self):
        route_log = ApiRouteLog(
            active_route="dmx",
            dmx_base_url="https://anyaigc.com/v1",
            dmx_model="gpt-5.5-share2",
            dmx_api_endpoint="responses",
        )
        client = OpenAICompatibleModelClient(route_log=route_log)

        self.assertEqual(
            client.responses_url(),
            "https://anyaigc.com/v1/responses",
        )

    def test_openai_client_can_call_responses_api_without_network(self):
        class FakeHttpResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "output": [
                            {
                                "content": [
                                    {"type": "output_text", "text": "pong"},
                                ],
                            },
                        ],
                    }
                ).encode("utf-8")

        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeHttpResponse()

        route_log = ApiRouteLog(
            active_route="dmx",
            dmx_base_url="https://anyaigc.com/v1",
            dmx_model="gpt-5.5-share2",
            dmx_api_endpoint="responses",
            dmx_user_agent="curl/8.5.0",
        )
        client = OpenAICompatibleModelClient(route_log=route_log, timeout_seconds=7)

        with patch.dict("os.environ", {"DMX_API_KEY": "test-key"}), patch(
            "llm.model_client.request.urlopen",
            fake_urlopen,
        ):
            response = client.chat(
                messages=[
                    {"role": "system", "content": "只回复 pong。"},
                    {"role": "user", "content": "ping"},
                ],
                task="api_smoke_test",
            )

        self.assertEqual(response.content, "pong")
        self.assertEqual(response.model, "gpt-5.5-share2")
        self.assertEqual(captured["url"], "https://anyaigc.com/v1/responses")
        self.assertEqual(captured["headers"]["User-agent"], "curl/8.5.0")
        self.assertEqual(captured["payload"]["model"], "gpt-5.5-share2")
        self.assertIn("system: 只回复 pong。", captured["payload"]["input"])
        self.assertIn("user: ping", captured["payload"]["input"])
        self.assertNotIn("metadata", captured["payload"])
        self.assertFalse(captured["payload"]["store"])
        self.assertFalse(captured["payload"]["stream"])
        self.assertEqual(captured["timeout"], 7)

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

            self.assertIn("影像证据不足", result["reply_to_patient"])
            self.assertIn("MRI", result["reply_to_patient"])
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
            system_prompt = model_client.calls[0]["messages"][0]["content"]
            user_payload = model_client.calls[0]["messages"][1]["content"]

            self.assertEqual(answer, "LLM 基于证据回答：缺少 T1ce 时不能判断强化肿瘤为阴性。")
            self.assertEqual(model_client.calls[0]["task"], "follow_up_qa")
            self.assertIn("integrated_reasoning_evidence", system_prompt)
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

    def test_gaodoctor_allows_follow_up_llm_answer_that_says_evidence_not_available(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content="目前未见可用于判断强化肿瘤的 T1ce 证据，因此不能说无强化或阴性。",
                model="fake-model",
                route="test",
            )
        )
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_missing_evidence_safe_language"
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

            self.assertEqual(
                answer,
                "目前未见可用于判断强化肿瘤的 T1ce 证据，因此不能说无强化或阴性。",
            )
            self.assertTrue(qa_entry["llm_used"])
            self.assertIsNone(qa_entry["llm_fallback_reason"])

    def test_gaodoctor_follow_up_llm_answer_strips_markdown_bold_markers(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content="**无法确定**。当前证据不足，不能只凭这张 X 光确诊。",
                model="fake-model",
                route="test",
            )
        )
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_markdown_bold"
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
                    "visual_evidence": {"segmentation_quality": "candidate"},
                },
                skill_memory={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "selected_skill": "femoral_head_necrosis",
                },
                reasoning_memory={
                    "diagnostic_tendency": "疑似股骨头坏死候选影像表现",
                    "key_evidence": ["股骨头上缘轮廓轻度不规则候选区"],
                    "uncertainty": ["单纯 X 光证据不足，建议补充 MRI/CT"],
                },
            )
            doctor = GaoDoctorAgent(
                memory_manager=memory,
                prompt_runner=PromptRunner(model_client=model_client),
            )

            answer = doctor.answer_follow_up(case_id=case_id, question="这张图片能确定吗？")

            self.assertEqual(answer, "无法确定。当前证据不足，不能只凭这张 X 光确诊。")
            self.assertNotIn("**", answer)

    def test_gaodoctor_follow_up_llm_answer_rewrites_patient_unfriendly_visual_terms(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=(
                    "目前无法确诊。测量级定位遮罩目前未评估，"
                    "分割图像显示缺失，这不能解释为阴性。"
                ),
                model="fake-model",
                route="test",
            )
        )
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_patient_terms"
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
                    "visual_evidence": {"segmentation_quality": "candidate"},
                },
                skill_memory={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "selected_skill": "femoral_head_necrosis",
                },
                reasoning_memory={
                    "diagnostic_tendency": "疑似股骨头坏死候选影像表现",
                    "key_evidence": ["股骨头上缘轮廓轻度不规则候选区"],
                    "uncertainty": ["单纯 X 光证据不足，建议补充 MRI/CT"],
                },
            )
            doctor = GaoDoctorAgent(
                memory_manager=memory,
                prompt_runner=PromptRunner(model_client=model_client),
            )

            answer = doctor.answer_follow_up(case_id=case_id, question="这张图片能确定吗？")

            self.assertIn("可用于测量的分割结果", answer)
            self.assertIn("分割对照图", answer)
            self.assertNotIn("遮罩", answer)
            self.assertNotIn("分割图像显示缺失", answer)

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

    def test_gaodoctor_follow_up_template_answers_prognosis_concisely(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_prognosis"
            memory.save_case_memory(
                case_id=case_id,
                patient_memory={
                    "patient_message": "右髋疼痛，上传 X 光",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "symptoms": ["髋关节疼痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "image_path": "hip.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "visual_evidence": {
                        "segmentation_quality": "candidate",
                        "completeness": {
                            "measurement_grade_mask": {
                                "status": "unassessed",
                                "reason": "Current execution mode did not request segmentation.",
                            },
                            "segmentation_display": {
                                "status": "missing",
                                "reason": "Segmentation did not complete: segmentation_error.",
                            },
                        },
                    },
                },
                skill_memory={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "selected_skill": "femoral_head_necrosis",
                },
                reasoning_memory={
                    "diagnostic_tendency": "疑似股骨头坏死候选影像表现",
                    "key_evidence": [
                        "股骨头塌陷：右侧股骨头上缘轮廓轻度不规则候选；未生成测量级 mask。",
                        "硬化带：右侧股骨头上外侧见带状密度增高候选影；未生成测量级 mask。",
                        "囊性变：右侧股骨头内可疑小片透亮区；未生成测量级 mask。",
                    ],
                    "uncertainty": [
                        "当前输出使用候选视觉证据，不能替代真实医学诊断",
                        "视觉证据字段 measurement_grade_mask 当前为 unassessed",
                        "视觉证据字段 segmentation_display 当前为 missing",
                        "不能在缺少 MRI 时排除早期股骨头坏死",
                    ],
                },
            )
            doctor = GaoDoctorAgent(memory_manager=memory)

            answer = doctor.answer_follow_up(case_id=case_id, question="这个病能活多久")

            self.assertIn("不能仅凭这张 X 光判断寿命", answer)
            self.assertIn("股骨头坏死通常不是直接决定生存期的疾病", answer)
            self.assertLess(len(answer), 180)
            self.assertNotIn("measurement_grade_mask", answer)
            self.assertNotIn("segmentation_display", answer)
            self.assertNotIn("未作为独立依据的视觉事实", answer)

    def test_gaodoctor_follow_up_template_answers_diagnosis_question_with_conclusion_first(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_diagnosis_question"
            memory.save_case_memory(
                case_id=case_id,
                patient_memory={
                    "patient_message": "右髋疼痛，上传 X 光",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "symptoms": ["髋关节疼痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "image_path": "hip.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "visual_evidence": {
                        "segmentation_quality": "candidate",
                        "completeness": {
                            "segmentation_display": {
                                "status": "missing",
                                "reason": "Segmentation did not complete: segmentation_error.",
                            },
                        },
                    },
                },
                skill_memory={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "selected_skill": "femoral_head_necrosis",
                },
                reasoning_memory={
                    "diagnostic_tendency": "疑似股骨头坏死候选影像表现",
                    "key_evidence": [
                        "股骨头塌陷：右侧股骨头上缘轮廓轻度不规则候选区；未生成测量级 mask。",
                        "硬化带：右侧股骨头上外侧见带状密度增高候选影；未生成测量级 mask。",
                    ],
                    "uncertainty": [
                        "单纯 X 光对早期股骨头坏死敏感性有限",
                        "当前输出使用候选视觉证据，不能替代真实医学诊断",
                    ],
                },
            )
            doctor = GaoDoctorAgent(memory_manager=memory)

            answer = doctor.answer_follow_up(case_id=case_id, question="这张图片是股骨头坏死吗")

            self.assertTrue(answer.startswith("目前不能仅凭这张 X 光确诊"))
            self.assertIn("存在股骨头坏死相关候选征象", answer)
            self.assertIn("建议带片给骨科医生复核", answer)
            self.assertLess(len(answer), 240)
            self.assertNotIn("未作为独立依据的视觉事实", answer)
            self.assertNotIn("not_diagnosis_usable", answer)

    def test_gaodoctor_follow_up_template_uses_integrated_reasoning_for_diagnosis_question(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_integrated_reasoning"
            memory.save_case_memory(
                case_id=case_id,
                patient_memory={
                    "patient_message": "右髋疼痛，上传 X 光",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "symptoms": ["髋关节疼痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "image_path": "hip.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "visual_evidence": {},
                },
                skill_memory={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "selected_skill": "femoral_head_necrosis",
                },
                reasoning_memory={
                    "diagnostic_tendency": "影像证据不足，需进一步评估",
                    "key_evidence": [
                        "股骨头塌陷：右侧股骨头上缘轮廓轻度不规则候选区；未生成测量级 mask。",
                        "硬化带：右侧股骨头上外侧见带状密度增高候选影；未生成测量级 mask。",
                    ],
                    "uncertainty": [
                        "视觉证据字段 segmentation_display 当前为 missing：Segmentation did not complete.",
                    ],
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
                                "provided_risk_factors": [],
                                "missing_clinical_context": [],
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
                },
            )
            doctor = GaoDoctorAgent(memory_manager=memory)

            answer = doctor.answer_follow_up(case_id=case_id, question="这张图片是股骨头坏死吗")

            self.assertTrue(answer.startswith("目前不能仅凭这张 X 光确诊股骨头坏死"))
            self.assertIn("早期股骨头坏死证据不足", answer)
            self.assertIn("MRI", answer)
            self.assertLess(len(answer), 220)
            self.assertNotIn("未生成测量级 mask", answer)
            self.assertNotIn("segmentation_display", answer)
            self.assertNotIn("missing", answer)

    def test_gaodoctor_follow_up_template_uses_integrated_reasoning_for_next_step_question(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_integrated_next_step"
            memory.save_case_memory(
                case_id=case_id,
                patient_memory={
                    "patient_message": "右髋疼痛，上传 X 光",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                    "symptoms": ["髋关节疼痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "image_path": "hip.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "visual_evidence": {},
                },
                skill_memory={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "selected_skill": "femoral_head_necrosis",
                },
                reasoning_memory={
                    "diagnostic_tendency": "影像证据不足，需进一步评估",
                    "key_evidence": [
                        "硬化带：右侧股骨头上外侧见带状密度增高候选影；未生成测量级 mask。",
                    ],
                    "uncertainty": [
                        "视觉证据字段 segmentation_display 当前为 missing：Segmentation did not complete.",
                    ],
                    "report": {
                        "integrated_reasoning_summary": {
                            "target_disease": "femoral_head_necrosis",
                            "evidence_status": "insufficient",
                            "can_confirm_target_disease": False,
                            "imaging_support": {
                                "supported_targets": [],
                                "nonspecific_or_unusable_targets": ["sclerotic_band"],
                                "missing_targets": ["early_osteonecrosis"],
                            },
                            "quantitative_support": {
                                "strong_quantitative_support_count": 0,
                                "measurement_targets_not_usable": ["collapse"],
                                "exploratory_targets": ["trabecular_blurring"],
                            },
                            "missing_evidence": {
                                "missing_required_targets": ["early_osteonecrosis"],
                            },
                            "recommended_next_step": [
                                "建议完善双髋 MRI T1/T2/STIR 检查。",
                                "建议由骨科或影像科医生结合临床体征复核。",
                            ],
                        }
                    },
                },
            )
            doctor = GaoDoctorAgent(memory_manager=memory)

            answer = doctor.answer_follow_up(case_id=case_id, question="下一步应该做什么？")

            self.assertTrue(answer.startswith("下一步建议"))
            self.assertIn("MRI", answer)
            self.assertIn("骨科或影像科医生", answer)
            self.assertIn("不能仅凭当前 X 光确认", answer)
            self.assertLess(len(answer), 220)
            self.assertNotIn("未生成测量级 mask", answer)
            self.assertNotIn("segmentation_display", answer)
            self.assertNotIn("missing", answer)

    def test_gaodoctor_follow_up_identity_question_does_not_dump_case_evidence(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_qa_identity"
            memory.save_case_memory(
                case_id=case_id,
                patient_memory={
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
                        "measurements": {"whole_tumor_volume_ml": 117.996},
                        "completeness": {
                            "tumor_core": {"status": "missing", "reason": "Requires T1, T1ce, T2"}
                        },
                    },
                },
                skill_memory={"skill_id": "diffuse_glioma_brats_v0.1"},
                reasoning_memory={
                    "diagnostic_tendency": "成人弥漫性胶质瘤影像疑似",
                    "key_evidence": ["whole tumor 体积估计为 117.996 ml"],
                    "uncertainty": ["tumor_core 缺少 T1/T1ce/T2，不能解释为阴性或 0"],
                },
            )
            doctor = GaoDoctorAgent(memory_manager=memory)

            answer = doctor.answer_follow_up(case_id=case_id, question="你是谁")

            self.assertIn("我是 MedScope 的高医生 Agent", answer)
            self.assertLess(len(answer), 120)
            self.assertNotIn("117.996", answer)
            self.assertNotIn("tumor_core", answer)
            self.assertNotIn("missing", answer)
            self.assertNotIn("FLAIR", answer)

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
