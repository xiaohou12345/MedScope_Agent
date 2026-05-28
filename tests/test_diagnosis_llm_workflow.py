import json
import unittest

from agents.diagnosis_agent import DiagnosisDoctorAgent
from agents.vision_agent import VisionAgent
from llm.model_client import ChatResponse, RecordingModelClient
from llm.prompt_runner import PromptRunner


class DiagnosisLlmWorkflowTest(unittest.TestCase):
    def _visual_result(self):
        return VisionAgent().analyze_image(
            image_path="data/images/demo_xray.png",
            disease_skill={
                "disease_name": "股骨头坏死",
                "vision_agent_tasks": {
                    "segmentation_targets": ["股骨头区域"],
                    "quantitative_features": ["texture_abnormality_score"],
                },
            },
        )

    def _alignment_plan(self, analysis_status="partial_evidence", blocked=None):
        return {
            "selected_skill": "femoral_head_necrosis",
            "analysis_status": analysis_status,
            "clinical_focus": "指南约束影像评估",
            "image_context": {
                "modality": "xray",
                "body_part": "hip",
                "available_sequences": [],
                "image_path": "data/images/demo_xray.png",
            },
            "visual_tasks": [
                {
                    "task": "assess_early_osteonecrosis",
                    "required_input": "MRI T1/T2",
                    "status": "missing_input",
                    "reason": "需要 MRI 支撑。",
                }
            ],
            "diagnosis_scope": {
                "allowed": ["说明当前证据限制"],
                "blocked": blocked or ["不得把缺失影像证据解释为阴性"],
            },
            "suspected_conditions": [
                {
                    "disease": "股骨头坏死",
                    "reason": "症状和当前 skill 匹配，但影像证据不足。",
                }
            ],
            "required_next_images": [
                {
                    "modality": "MRI T1ce",
                    "region": "target region",
                    "reason": "补充关键序列以完成视觉协议。",
                }
            ],
            "insufficiency_reasons": ["当前影像不足以完成指南要求的视觉证据。"],
        }

    def test_diagnosis_agent_can_generate_report_from_llm_json(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 疑似早期股骨头坏死",
                        "影像依据": ["股骨头负重区纹理异常", "未见明显塌陷"],
                        "分期判断": "倾向 ARCO I-II，建议 MRI 确认",
                        "不确定性说明": ["X 光早期敏感性有限"],
                        "建议进一步检查": ["双髋 MRI T1/T2"],
                        "治疗建议": ["减少负重", "骨科门诊复核"],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_llm",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=self._visual_result(),
        )

        self.assertEqual(report["诊断倾向"], "LLM 疑似早期股骨头坏死")
        self.assertEqual(report["diagnostic_tendency"], "LLM 疑似早期股骨头坏死")
        self.assertEqual(model_client.calls[0]["task"], "diagnosis_report_generation")
        self.assertIn("used_skill", report)

    def test_diagnosis_agent_excludes_not_usable_segmentation_measurements(self):
        agent = DiagnosisDoctorAgent()
        visual_result = {
            "image_path": "output/fake/case_flair.nii.gz",
            "modality": "MRI",
            "body_part": "brain",
            "image_outputs": {
                "original_image_path": "output/fake/case_flair.nii.gz",
                "mask_path": "output/fake/case_mask.nii.gz",
                "overlay_path": "output/fake/case_overlay.png",
            },
            "visual_evidence": {
                "collapse": False,
                "joint_space_narrowing": False,
                "segmentation_quality": "medsam2",
                "suspected_visual_findings": ["MedSAM2 candidate mask failed QC"],
                "measurements": {"whole_tumor_volume_ml": 42.0},
                "completeness": {
                    "whole_tumor": {
                        "status": "supported",
                        "reason": "before QC",
                    }
                },
                "segmentation_results": [
                    {
                        "task_name": "segment_whole_tumor",
                        "target": "whole_tumor",
                        "status": "low_quality",
                        "mask_path": "output/fake/case_mask.nii.gz",
                        "overlay_path": "output/fake/case_overlay.png",
                        "measurements": {"whole_tumor_volume_ml": 42.0},
                        "quality": {
                            "score": 0.2,
                            "level": "low",
                            "warnings": ["whole_tumor_volume_ml is empty or unstable"],
                        },
                        "completeness": {
                            "status": "unassessed",
                            "reason": "Segmentation did not pass QC",
                        },
                        "diagnosis_usable": False,
                    }
                ],
            },
        }

        report = agent.generate_report(
            case_id="case_low_quality",
            patient_info={"symptoms": ["头痛"]},
            visual_result=visual_result,
            disease_skill=agent.load_disease_skill("diffuse_glioma_brats"),
        )

        self.assertIsNone(
            report["visual_input_contract"]["measurements"]["whole_tumor_volume_ml"]
        )
        self.assertEqual(
            report["visual_input_contract"]["completeness"]["whole_tumor"]["status"],
            "low_quality",
        )
        report_text = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("42.0 ml", report_text)
        self.assertIn("不能作为诊断可用证据", report_text)

    def test_diagnosis_agent_passes_and_applies_partial_alignment_plan_to_llm_report(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 有限影像辅助分析",
                        "影像依据": ["当前 FLAIR 可见异常信号"],
                        "分期判断": "当前证据不足以完成整合诊断",
                        "不确定性说明": ["缺少增强序列"],
                        "建议进一步检查": ["补全 MRI 序列"],
                        "治疗建议": ["线下专科复核"],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        alignment_plan = self._alignment_plan(
            analysis_status="partial_evidence",
            blocked=["不能从缺失 T1ce 推断无强化"],
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_partial_alignment",
            patient_info={"symptoms": ["头痛"]},
            visual_result=self._visual_result(),
            alignment_plan=alignment_plan,
        )
        user_payload = model_client.calls[0]["messages"][1]["content"]

        self.assertIn("alignment_plan", user_payload)
        self.assertEqual(report["alignment_plan"]["analysis_status"], "partial_evidence")
        self.assertIn("不能从缺失 T1ce 推断无强化", report["不确定性说明"])
        self.assertTrue(any("T1ce" in item for item in report["建议进一步检查"]))

    def test_diagnosis_agent_blocks_llm_when_alignment_plan_is_insufficient(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 可以排除早期股骨头坏死",
                        "影像依据": ["X 光未见异常"],
                        "分期判断": "无病",
                        "不确定性说明": ["无明显不确定性"],
                        "建议进一步检查": ["无需补充检查"],
                        "治疗建议": ["观察"],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        alignment_plan = self._alignment_plan(
            analysis_status="insufficient_evidence",
            blocked=["不能将 X 光未见异常解释为无病"],
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_insufficient_alignment",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=self._visual_result(),
            alignment_plan=alignment_plan,
        )

        self.assertEqual(model_client.calls, [])
        self.assertEqual(report["诊断倾向"], "现有影像证据不足，需补充检查后判断")
        self.assertIn("不能将 X 光未见异常解释为无病", report["不确定性说明"])
        self.assertEqual(report["alignment_plan"]["analysis_status"], "insufficient_evidence")

    def test_diagnosis_agent_normalizes_single_string_report_list_fields_from_llm(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 疑似早期股骨头坏死",
                        "影像依据": "股骨头负重区纹理异常",
                        "分期判断": "倾向 ARCO I-II，建议 MRI 确认",
                        "不确定性说明": "X 光早期敏感性有限",
                        "建议进一步检查": "双髋 MRI T1/T2",
                        "治疗建议": "减少负重",
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_llm_string_lists",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=self._visual_result(),
        )

        self.assertEqual(report["诊断倾向"], "LLM 疑似早期股骨头坏死")
        self.assertEqual(report["影像依据"], ["股骨头负重区纹理异常"])
        self.assertEqual(report["治疗建议"], ["减少负重"])
        self.assertNotIn("llm_fallback_reason", report)

    def test_diagnosis_prompt_includes_visual_completeness_safety_rules(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 疑似早期股骨头坏死",
                        "影像依据": ["股骨头负重区纹理异常"],
                        "分期判断": "倾向 ARCO I-II",
                        "不确定性说明": ["X 光早期敏感性有限"],
                        "建议进一步检查": ["双髋 MRI T1/T2"],
                        "治疗建议": ["减少负重"],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        agent.generate_report(
            case_id="case_prompt_rules",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=self._visual_result(),
        )

        system_prompt = model_client.calls[0]["messages"][0]["content"]
        self.assertIn("completeness", system_prompt)
        self.assertIn("missing", system_prompt)
        self.assertIn("null", system_prompt)
        self.assertIn("不能解释为 0", system_prompt)
        self.assertIn("T1ce", system_prompt)

    def test_diagnosis_agent_falls_back_when_llm_returns_invalid_json(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content="这不是 JSON",
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_bad_llm",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=self._visual_result(),
        )

        self.assertEqual(report["诊断倾向"], "疑似早期股骨头坏死")
        self.assertIn("llm_fallback_reason", report)

    def test_diagnosis_agent_falls_back_when_llm_report_missing_required_fields(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps({"诊断倾向": "缺字段报告"}, ensure_ascii=False),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_missing_fields",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=self._visual_result(),
        )

        self.assertEqual(report["诊断倾向"], "疑似早期股骨头坏死")
        self.assertIn("missing required report fields", report["llm_fallback_reason"])

    def test_diagnosis_agent_uses_skill_findings_for_femoral_head_necrosis_xray(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"].update(
            {
                "collapse": False,
                "joint_space_narrowing": False,
                "texture_abnormality_score": 0.0,
                "findings": [
                    {
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                    },
                    {
                        "target": "cystic_change",
                        "display_name": "囊性变",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                    },
                ],
            }
        )

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fhn_findings",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
        )

        self.assertIn("股骨头坏死", report["诊断倾向"])
        self.assertIn("ARCO II", report["分期判断"])
        self.assertIn("硬化带", " ".join(report["影像依据"]))
        self.assertIn("囊性变", " ".join(report["影像依据"]))

    def test_diagnosis_agent_marks_overlapping_skill_findings_as_non_independent(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"].update(
            {
                "collapse": False,
                "joint_space_narrowing": False,
                "texture_abnormality_score": 0.0,
                "suspected_visual_findings": [],
                "quality_warnings": [
                    {
                        "code": "overlapping_candidate_findings",
                        "target": "cystic_change",
                        "overlap_with_target": "sclerotic_band",
                        "mask_iou": 1.0,
                    }
                ],
                "findings": [
                    {
                        "finding_id": "finding_1_sclerotic_band",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                        "independent_evidence": True,
                    },
                    {
                        "finding_id": "finding_2_cystic_change",
                        "target": "cystic_change",
                        "display_name": "囊性变",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                        "independent_evidence": False,
                        "overlap_qc": {
                            "status": "overlaps_existing_finding",
                            "overlap_with_target": "sclerotic_band",
                            "mask_iou": 1.0,
                        },
                    },
                ],
            }
        )

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fhn_overlapping_findings",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
        )

        evidence_text = " ".join(report["影像依据"])
        uncertainty_text = " ".join(report["不确定性说明"])
        self.assertIn("X 光候选征象：硬化带", evidence_text)
        self.assertNotIn("X 光候选征象：硬化带、囊性变", evidence_text)
        self.assertIn("同区域候选征象", evidence_text)
        self.assertIn("囊性变", evidence_text)
        self.assertIn("硬化带", evidence_text)
        self.assertIn("不作为独立诊断依据", evidence_text)
        self.assertIn("同区域候选征象", uncertainty_text)
        self.assertNotIn("囊性变/骨小梁", report["分期判断"])

    def test_diagnosis_agent_preserves_image_side_for_repeated_independent_findings(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"].update(
            {
                "collapse": False,
                "joint_space_narrowing": False,
                "texture_abnormality_score": 0.0,
                "findings": [
                    {
                        "finding_id": "finding_1_sclerotic_band",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                        "independent_evidence": True,
                        "measurements": {"laterality": "image_left"},
                    },
                    {
                        "finding_id": "finding_2_sclerotic_band",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                        "independent_evidence": True,
                        "measurements": {"laterality": "image_right"},
                    },
                ],
            }
        )

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fhn_bilateral_findings",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
        )

        evidence_text = " ".join(report["影像依据"])
        self.assertIn("X 光候选征象：图像左侧硬化带、图像右侧硬化带", evidence_text)
        self.assertIn("图像左侧硬化带、图像右侧硬化带等独立候选征象", report["分期判断"])

    def test_diagnosis_agent_can_use_structured_visual_facts_without_raw_findings(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"].update(
            {
                "collapse": False,
                "joint_space_narrowing": False,
                "texture_abnormality_score": 0.0,
                "findings": [],
                "structured_visual_facts": [
                    {
                        "finding_id": "fact_1",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "laterality": "image_left",
                        "diagnosis_usable": True,
                        "independent_evidence": True,
                        "area_px": 120,
                        "alignment_status": "aligned",
                    }
                ],
            }
        )

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_structured_visual_facts",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
        )

        evidence_text = " ".join(report["影像依据"])
        self.assertIn("X 光候选征象：图像左侧硬化带", evidence_text)
        self.assertIn("图像左侧硬化带等独立候选征象", report["分期判断"])

    def test_diagnosis_agent_records_used_and_excluded_structured_visual_facts(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"].update(
            {
                "collapse": False,
                "joint_space_narrowing": False,
                "texture_abnormality_score": 0.0,
                "findings": [],
                "structured_visual_facts": [
                    {
                        "finding_id": "fact_used_sclerosis",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "laterality": "image_left",
                        "diagnosis_usable": True,
                        "independent_evidence": True,
                        "alignment_status": "aligned",
                    },
                    {
                        "finding_id": "fact_non_independent_cyst",
                        "target": "cystic_change",
                        "display_name": "囊性变",
                        "status": "candidate_present",
                        "laterality": "image_left",
                        "diagnosis_usable": True,
                        "independent_evidence": False,
                        "non_independent_reason": "overlaps_existing_finding",
                        "overlap_with_finding_id": "fact_used_sclerosis",
                        "alignment_status": "aligned",
                    },
                    {
                        "finding_id": "fact_misaligned_collapse",
                        "target": "collapse",
                        "display_name": "股骨头塌陷",
                        "status": "candidate_present",
                        "laterality": "image_right",
                        "diagnosis_usable": False,
                        "independent_evidence": True,
                        "alignment_status": "low_alignment",
                    },
                ],
            }
        )

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fact_usage",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
        )

        usage = report["visual_fact_usage"]
        self.assertEqual(
            [fact["finding_id"] for fact in usage["used"]],
            ["fact_used_sclerosis"],
        )
        self.assertEqual(
            [fact["finding_id"] for fact in usage["excluded"]],
            ["fact_non_independent_cyst", "fact_misaligned_collapse"],
        )
        self.assertEqual(
            usage["excluded"][0]["exclusion_reason"],
            "non_independent_evidence",
        )
        self.assertEqual(
            usage["excluded"][1]["exclusion_reason"],
            "not_diagnosis_usable",
        )

    def test_diagnosis_agent_rejects_llm_report_that_counts_overlapping_findings_as_independent(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"].update(
            {
                "collapse": False,
                "joint_space_narrowing": False,
                "texture_abnormality_score": 0.0,
                "quality_warnings": [
                    {
                        "code": "overlapping_candidate_findings",
                        "target": "cystic_change",
                        "overlap_with_target": "sclerotic_band",
                        "mask_iou": 1.0,
                    }
                ],
                "findings": [
                    {
                        "finding_id": "finding_1_sclerotic_band",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                        "independent_evidence": True,
                    },
                    {
                        "finding_id": "finding_2_cystic_change",
                        "target": "cystic_change",
                        "display_name": "囊性变",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                        "independent_evidence": False,
                        "overlap_qc": {
                            "status": "overlaps_existing_finding",
                            "overlap_with_target": "sclerotic_band",
                            "mask_iou": 1.0,
                        },
                    },
                ],
            }
        )
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 疑似股骨头坏死",
                        "影像依据": ["X 光候选征象：硬化带、囊性变"],
                        "分期判断": "两个独立征象支持 ARCO II",
                        "不确定性说明": ["X 光早期敏感性有限"],
                        "建议进一步检查": ["双髋 MRI T1/T2"],
                        "治疗建议": ["减少负重"],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_fhn_overlapping_findings_llm",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
        )

        report_text = json.dumps(report, ensure_ascii=False)
        self.assertIn("llm_fallback_reason", report)
        self.assertIn("overlapping candidate visual evidence", report["llm_fallback_reason"])
        self.assertIn("同区域候选征象", report_text)
        self.assertIn("不作为独立诊断依据", report_text)
        self.assertNotIn("两个独立征象支持", report_text)

    def test_diagnosis_agent_does_not_turn_collapse_candidate_into_negative_claim(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"].update(
            {
                "collapse": False,
                "joint_space_narrowing": False,
                "texture_abnormality_score": 0.0,
                "findings": [
                    {
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                    },
                    {
                        "target": "collapse",
                        "display_name": "股骨头塌陷",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                        "measurements": {"area_ratio_in_anatomy": 0.000739},
                    },
                ],
            }
        )

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_fhn_collapse_candidate",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
        )

        staging = report["分期判断"]
        self.assertIn("塌陷候选", staging)
        self.assertNotIn("未见塌陷", staging)
        self.assertIn("股骨头塌陷", " ".join(report["影像依据"]))

    def test_diagnosis_agent_reports_missing_visual_protocol_evidence_without_zero_claim(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"]["suspected_visual_findings"] = ["whole tumor 体积已评估"]
        visual_result["visual_evidence"]["measurements"] = {
            "whole_tumor_volume_ml": 35.7,
            "enhancing_tumor_volume_ml": None,
        }
        visual_result["visual_evidence"]["completeness"] = {
            "whole_tumor": {
                "status": "supported",
                "reason": "FLAIR modality available",
            },
            "enhancing_tumor": {
                "status": "missing",
                "reason": "Requires T1ce modality",
            },
        }

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_glioma",
            patient_info={"symptoms": ["头痛"]},
            visual_result=visual_result,
            disease_skill={
                "disease_name": "成人弥漫性胶质瘤",
                "skill_id": "diffuse_glioma_brats_v0.1",
                "skill_type": "guideline_based",
                "evidence_level": "high",
                "source": "EANO adult diffuse glioma guideline",
            },
        )

        uncertainty_text = " ".join(report["不确定性说明"])
        self.assertIn("enhancing_tumor", uncertainty_text)
        self.assertIn("Requires T1ce modality", uncertainty_text)
        self.assertNotIn("增强肿瘤体积为 0", uncertainty_text)

    def test_diagnosis_agent_rejects_llm_report_that_turns_missing_visual_evidence_into_zero(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"]["suspected_visual_findings"] = ["whole tumor 体积已评估"]
        visual_result["visual_evidence"]["measurements"] = {
            "whole_tumor_volume_ml": 35.7,
            "enhancing_tumor_volume_ml": None,
        }
        visual_result["visual_evidence"]["completeness"] = {
            "whole_tumor": {
                "status": "supported",
                "reason": "FLAIR modality available",
            },
            "enhancing_tumor": {
                "status": "missing",
                "reason": "Requires T1ce modality",
            },
        }
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 胶质瘤辅助分析",
                        "影像依据": ["增强肿瘤体积为 0 ml", "未见强化肿瘤"],
                        "分期判断": "仅凭 FLAIR 判断强化成分阴性",
                        "不确定性说明": ["暂无明显不确定性"],
                        "建议进一步检查": ["随访"],
                        "治疗建议": ["观察"],
                        "used_visual_fields": ["whole_tumor"],
                        "missing_visual_fields_acknowledged": ["enhancing_tumor"],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_bad_glioma_llm",
            patient_info={"symptoms": ["头痛"]},
            visual_result=visual_result,
            disease_skill={
                "disease_name": "成人弥漫性胶质瘤",
                "skill_id": "diffuse_glioma_brats_v0.1",
                "skill_type": "guideline_based",
                "evidence_level": "high",
                "source": "EANO adult diffuse glioma guideline",
            },
        )

        self.assertEqual(
            report["diagnostic_tendency"],
            "成人弥漫性胶质瘤影像疑似，需病理和分子诊断确认",
        )
        self.assertIn("llm_fallback_reason", report)
        self.assertIn("missing visual evidence", report["llm_fallback_reason"])
        report_text = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("增强肿瘤体积为 0", report_text)
        self.assertIn("Requires T1ce modality", report_text)

    def test_diagnosis_agent_requires_structured_visual_field_acknowledgement_when_completeness_exists(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"]["suspected_visual_findings"] = ["whole tumor 体积已评估"]
        visual_result["visual_evidence"]["measurements"] = {
            "whole_tumor_volume_ml": 35.7,
            "enhancing_tumor_volume_ml": None,
        }
        visual_result["visual_evidence"]["completeness"] = {
            "whole_tumor": {
                "status": "supported",
                "reason": "FLAIR modality available",
            },
            "enhancing_tumor": {
                "status": "missing",
                "reason": "Requires T1ce modality",
            },
        }
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 胶质瘤辅助分析",
                        "影像依据": ["whole tumor 体积已评估"],
                        "分期判断": "影像不能替代病理和分子诊断",
                        "不确定性说明": ["缺少 T1ce，enhancing_tumor 不能评估"],
                        "建议进一步检查": ["补充 T1ce"],
                        "治疗建议": ["神经肿瘤 MDT 评估"],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_missing_visual_contract",
            patient_info={"symptoms": ["头痛"]},
            visual_result=visual_result,
            disease_skill={
                "disease_name": "成人弥漫性胶质瘤",
                "skill_id": "diffuse_glioma_brats_v0.1",
                "skill_type": "guideline_based",
                "evidence_level": "high",
                "source": "EANO adult diffuse glioma guideline",
            },
        )

        self.assertEqual(
            report["diagnostic_tendency"],
            "成人弥漫性胶质瘤影像疑似，需病理和分子诊断确认",
        )
        self.assertIn("llm_fallback_reason", report)
        self.assertIn("missing_visual_fields_acknowledged", report["llm_fallback_reason"])

    def test_diagnosis_agent_accepts_structured_visual_field_acknowledgement_from_llm(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"]["suspected_visual_findings"] = ["whole tumor 体积已评估"]
        visual_result["visual_evidence"]["measurements"] = {
            "whole_tumor_volume_ml": 35.7,
            "enhancing_tumor_volume_ml": None,
        }
        visual_result["visual_evidence"]["completeness"] = {
            "whole_tumor": {
                "status": "supported",
                "reason": "FLAIR modality available",
            },
            "enhancing_tumor": {
                "status": "missing",
                "reason": "Requires T1ce modality",
            },
        }
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 胶质瘤辅助分析",
                        "影像依据": ["whole tumor 体积已评估"],
                        "分期判断": "影像不能替代病理和分子诊断",
                        "不确定性说明": ["缺少 T1ce，enhancing_tumor 不能评估"],
                        "建议进一步检查": ["补充 T1ce"],
                        "治疗建议": ["神经肿瘤 MDT 评估"],
                        "used_visual_fields": ["whole_tumor"],
                        "missing_visual_fields_acknowledged": ["enhancing_tumor"],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_good_visual_contract",
            patient_info={"symptoms": ["头痛"]},
            visual_result=visual_result,
            disease_skill={
                "disease_name": "成人弥漫性胶质瘤",
                "skill_id": "diffuse_glioma_brats_v0.1",
                "skill_type": "guideline_based",
                "evidence_level": "high",
                "source": "EANO adult diffuse glioma guideline",
            },
        )

        self.assertEqual(report["diagnostic_tendency"], "LLM 胶质瘤辅助分析")
        self.assertEqual(report["used_visual_fields"], ["whole_tumor"])
        self.assertEqual(report["missing_visual_fields_acknowledged"], ["enhancing_tumor"])
        self.assertEqual(
            report["visual_input_contract"]["completeness"]["enhancing_tumor"]["status"],
            "missing",
        )
        self.assertIsNone(
            report["visual_input_contract"]["measurements"]["enhancing_tumor_volume_ml"]
        )
        self.assertNotIn("llm_fallback_reason", report)

    def test_diagnosis_agent_accepts_llm_report_that_says_missing_field_cannot_be_treated_as_zero(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"]["suspected_visual_findings"] = ["whole tumor 体积已评估"]
        visual_result["visual_evidence"]["measurements"] = {
            "whole_tumor_volume_ml": 35.7,
            "tumor_core_volume_ml": None,
        }
        visual_result["visual_evidence"]["completeness"] = {
            "whole_tumor": {
                "status": "supported",
                "reason": "FLAIR modality available",
            },
            "tumor_core": {
                "status": "missing",
                "reason": "Requires T1, T1ce, T2 modalities",
            },
        }
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 胶质瘤辅助分析",
                        "影像依据": ["whole tumor 体积已评估"],
                        "分期判断": "影像不能替代病理和分子诊断",
                        "不确定性说明": [
                            "tumor_core_volume_ml 为 null，代表缺乏对应模态数据，不能视为 0 或阴性。"
                        ],
                        "建议进一步检查": ["补充 T1/T1ce/T2"],
                        "治疗建议": ["神经肿瘤 MDT 评估"],
                        "used_visual_fields": ["whole_tumor"],
                        "missing_visual_fields_acknowledged": ["tumor_core"],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_negated_zero_claim",
            patient_info={"symptoms": ["头痛"]},
            visual_result=visual_result,
            disease_skill={
                "disease_name": "成人弥漫性胶质瘤",
                "skill_id": "diffuse_glioma_brats_v0.1",
                "skill_type": "guideline_based",
                "evidence_level": "high",
                "source": "EANO adult diffuse glioma guideline",
            },
        )

        self.assertEqual(report["diagnostic_tendency"], "LLM 胶质瘤辅助分析")
        self.assertNotIn("llm_fallback_reason", report)

    def test_diagnosis_agent_accepts_llm_report_that_says_missing_field_cannot_be_assumed_negative(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"]["suspected_visual_findings"] = ["whole tumor 体积已评估"]
        visual_result["visual_evidence"]["measurements"] = {
            "whole_tumor_volume_ml": 35.7,
            "tumor_core_volume_ml": None,
        }
        visual_result["visual_evidence"]["completeness"] = {
            "whole_tumor": {
                "status": "supported",
                "reason": "FLAIR modality available",
            },
            "tumor_core": {
                "status": "missing",
                "reason": "Requires T1, T1ce, T2 modalities",
            },
        }
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 胶质瘤辅助分析",
                        "影像依据": ["whole tumor 体积已评估"],
                        "分期判断": "影像不能替代病理和分子诊断",
                        "不确定性说明": [
                            "肿瘤核心体积在视觉证据中标记为缺失，不能报告具体数值或假定为阴性。"
                        ],
                        "建议进一步检查": ["补充 T1/T1ce/T2"],
                        "治疗建议": ["神经肿瘤 MDT 评估"],
                        "used_visual_fields": ["whole_tumor"],
                        "missing_visual_fields_acknowledged": ["tumor_core"],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_negated_negative_claim",
            patient_info={"symptoms": ["头痛"]},
            visual_result=visual_result,
            disease_skill={
                "disease_name": "成人弥漫性胶质瘤",
                "skill_id": "diffuse_glioma_brats_v0.1",
                "skill_type": "guideline_based",
                "evidence_level": "high",
                "source": "EANO adult diffuse glioma guideline",
            },
        )

        self.assertEqual(report["diagnostic_tendency"], "LLM 胶质瘤辅助分析")
        self.assertNotIn("llm_fallback_reason", report)

    def test_diagnosis_agent_does_not_apply_supported_field_negative_words_to_missing_targets(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"]["measurements"] = {
            "whole_tumor_volume_ml": 35.7,
            "tumor_core_volume_ml": None,
            "enhancing_tumor_volume_ml": None,
            "edema_present": False,
        }
        visual_result["visual_evidence"]["completeness"] = {
            "whole_tumor": {"status": "supported", "reason": "FLAIR modality available"},
            "edema": {"status": "supported", "reason": "FLAIR modality available"},
            "tumor_core": {
                "status": "missing",
                "reason": "Requires T1, T1ce, T2 modalities",
            },
            "enhancing_tumor": {
                "status": "missing",
                "reason": "Requires T1ce modality",
            },
        }
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 胶质瘤辅助分析",
                        "影像依据": [
                            "whole tumor 体积已评估",
                            "edema_present 为阴性/未见明显异常",
                            "tumor_core 当前缺失，无法评估，不能判定为无核心或体积为0。",
                            "enhancing_tumor 当前缺失，不能判定为无强化或强化体积为0。",
                        ],
                        "分期判断": "影像不能替代病理和分子诊断",
                        "不确定性说明": ["缺少 T1/T1ce/T2，核心和强化成分不能作为阴性处理。"],
                        "建议进一步检查": ["补充 T1/T1ce/T2"],
                        "治疗建议": ["神经肿瘤 MDT 评估"],
                        "used_visual_fields": ["whole_tumor", "edema"],
                        "missing_visual_fields_acknowledged": [
                            "tumor_core",
                            "enhancing_tumor",
                        ],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(prompt_runner=PromptRunner(model_client=model_client))

        report = agent.generate_report(
            case_id="case_supported_edema_negative_missing_core_safe",
            patient_info={"symptoms": ["头痛"]},
            visual_result=visual_result,
            disease_skill={
                "disease_name": "成人弥漫性胶质瘤",
                "skill_id": "diffuse_glioma_brats_v0.1",
                "skill_type": "guideline_based",
                "evidence_level": "high",
                "source": "EANO adult diffuse glioma guideline",
            },
        )

        self.assertEqual(report["diagnostic_tendency"], "LLM 胶质瘤辅助分析")
        self.assertNotIn("llm_fallback_reason", report)

    def test_diagnosis_agent_accepts_differential_statement_about_non_enhancing_glioma(self):
        visual_result = self._visual_result()
        visual_result["visual_evidence"]["suspected_visual_findings"] = ["whole tumor 体积已评估"]
        visual_result["visual_evidence"]["measurements"] = {
            "whole_tumor_volume_ml": 117.9,
            "tumor_core_volume_ml": None,
            "enhancing_tumor_volume_ml": None,
        }
        visual_result["visual_evidence"]["completeness"] = {
            "whole_tumor": {
                "status": "supported",
                "reason": "FLAIR modality available",
            },
            "tumor_core": {
                "status": "missing",
                "reason": "Requires T1, T1ce, T2 modalities",
            },
            "enhancing_tumor": {
                "status": "missing",
                "reason": "Requires T1ce modality",
            },
        }
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 胶质瘤辅助分析",
                        "影像依据": ["whole tumor 体积已评估"],
                        "分期判断": "影像不能替代病理和分子诊断",
                        "不确定性说明": [
                            "缺少 T1ce 序列，无法判断是否存在强化肿瘤成分，不能排除高级别胶质瘤或低级别无强化胶质瘤",
                            "缺少 T1 和 T2 序列，肿瘤核心体积 (tumor_core) 无法评估",
                        ],
                        "建议进一步检查": ["补充 T1/T1ce/T2"],
                        "治疗建议": ["神经肿瘤 MDT 评估"],
                        "used_visual_fields": ["whole_tumor"],
                        "missing_visual_fields_acknowledged": [
                            "tumor_core",
                            "enhancing_tumor",
                        ],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        agent = DiagnosisDoctorAgent(
            prompt_runner=PromptRunner(model_client=model_client)
        )

        report = agent.generate_report(
            case_id="case_differential_non_enhancing_glioma",
            patient_info={"symptoms": ["头痛"]},
            visual_result=visual_result,
            disease_skill={
                "disease_name": "成人弥漫性胶质瘤",
                "skill_id": "diffuse_glioma_brats_v0.1",
                "skill_type": "guideline_based",
                "evidence_level": "high",
                "source": "EANO adult diffuse glioma guideline",
            },
        )

        self.assertEqual(report["diagnostic_tendency"], "LLM 胶质瘤辅助分析")
        self.assertNotIn("llm_fallback_reason", report)


if __name__ == "__main__":
    unittest.main()
