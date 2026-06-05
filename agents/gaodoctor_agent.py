from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agents.diagnosis_agent import DiagnosisDoctorAgent
from agents.vision_agent import VisionAgent
from contracts.medical_contracts import AlignmentPlan, PatientCaseInput, PatientIntent, SkillDescriptor
from llm.prompt_runner import PromptRunner
from memory.memory_manager import MemoryManager
from tools.medsam2_segmentation_tool import MedSAM2CommandRunner, MedSAM2SegmentationTool
from tools.nifti_mask_reader_tool import NiftiMaskReaderTool
from tools.nifti_overlay_generation_tool import NiftiOverlayGenerationTool
from tools.segmentation_tool import SegmentationTool
from tools.vlm_candidate_parser import parse_vlm_candidates


class GaoDoctorAgent:
    """Patient-facing coordinator for intake, delegation, and explanation."""

    def __init__(
        self,
        diagnosis_agent: DiagnosisDoctorAgent | None = None,
        vision_agent: VisionAgent | None = None,
        memory_manager: MemoryManager | None = None,
        prompt_runner: PromptRunner | None = None,
        no_mask_visual_pipeline_runner: Any | None = None,
    ) -> None:
        self.diagnosis_agent = diagnosis_agent or DiagnosisDoctorAgent()
        self.vision_agent = vision_agent or VisionAgent()
        self.memory_manager = memory_manager or MemoryManager()
        self.prompt_runner = prompt_runner
        self.no_mask_visual_pipeline_runner = no_mask_visual_pipeline_runner

    def handle_message(
        self,
        patient_message: str,
        image_path: str | None = None,
        patient_info: dict[str, Any] | None = None,
        case_id: str | None = None,
        disease_key: str | None = None,
        vision_mode: str | None = None,
        mask_path: str | None = None,
        segmentation_prompt: dict[str, Any] | None = None,
        hypothesis_validation_mode: bool = False,
        alignment_plan: dict[str, Any] | None = None,
        routing_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        intent = self.classify_intent(
            patient_message=patient_message,
            image_path=image_path,
            case_id=case_id,
        )
        if intent.intent_type == "diagnosis":
            return {
                **self.handle_patient_case(
                    patient_message=patient_message,
                    image_path=intent.image_path or "",
                    patient_info=patient_info or {},
                    disease_key=disease_key,
                    vision_mode=vision_mode,
                    mask_path=mask_path,
                    segmentation_prompt=segmentation_prompt,
                    hypothesis_validation_mode=hypothesis_validation_mode,
                    alignment_plan=alignment_plan,
                    routing_decision=routing_decision,
                    intent_type=intent.intent_type,
                ),
                "intent": intent.intent_type,
            }
        if intent.intent_type == "review":
            review_info = dict(patient_info or {})
            review_info["previous_case_id"] = intent.case_id
            return {
                **self.handle_patient_case(
                    patient_message=patient_message,
                    image_path=intent.image_path or "",
                    patient_info=review_info,
                    disease_key=disease_key,
                    vision_mode=vision_mode,
                    mask_path=mask_path,
                    segmentation_prompt=segmentation_prompt,
                    hypothesis_validation_mode=hypothesis_validation_mode,
                    alignment_plan=alignment_plan,
                    routing_decision=routing_decision,
                    intent_type=intent.intent_type,
                ),
                "intent": intent.intent_type,
                "previous_case_id": intent.case_id,
            }
        if intent.intent_type == "report_explanation":
            return {
                "case_id": intent.case_id,
                "intent": intent.intent_type,
                "reply_to_patient": self.explain_saved_report(intent.case_id or ""),
            }
        return {
            "case_id": intent.case_id,
            "intent": intent.intent_type,
            "reply_to_patient": self.answer_follow_up(
                case_id=intent.case_id or "",
                question=patient_message,
            ),
        }

    def classify_intent(
        self,
        patient_message: str,
        image_path: str | None = None,
        case_id: str | None = None,
    ) -> PatientIntent:
        message = patient_message.strip()
        if case_id and image_path and self._contains_any(message, ["复查", "对比", "上次", "再看"]):
            return PatientIntent(
                intent_type="review",
                patient_message=patient_message,
                image_path=image_path,
                case_id=case_id,
            )
        if case_id and self._contains_any(message, ["报告", "解释", "什么意思", "看不懂"]):
            return PatientIntent(
                intent_type="report_explanation",
                patient_message=patient_message,
                case_id=case_id,
            )
        if case_id:
            return PatientIntent(
                intent_type="qa",
                patient_message=patient_message,
                case_id=case_id,
            )
        return PatientIntent(
            intent_type="diagnosis",
            patient_message=patient_message,
            image_path=image_path,
        )

    def handle_patient_case(
        self,
        patient_message: str,
        image_path: str,
        patient_info: dict[str, Any],
        disease_key: str | None = None,
        vision_mode: str | None = None,
        mask_path: str | None = None,
        segmentation_prompt: dict[str, Any] | None = None,
        hypothesis_validation_mode: bool = False,
        alignment_plan: dict[str, Any] | None = None,
        routing_decision: dict[str, Any] | None = None,
        intent_type: str = "diagnosis",
    ) -> dict[str, Any]:
        case_input = PatientCaseInput(
            patient_message=patient_message,
            image_path=image_path,
            patient_info=patient_info,
        )
        case_id = self.memory_manager.create_case_id()
        selected_disease_key = disease_key or "femoral_head_necrosis"
        selected_vision_mode = vision_mode
        if routing_decision:
            routing_decision = dict(routing_decision)
        else:
            routing_decision = self._build_memory_routing_decision(
                selected_disease_key=selected_disease_key,
                selected_vision_mode=selected_vision_mode,
                disease_key=disease_key,
                vision_mode=vision_mode,
            )
        disease_skill = self.diagnosis_agent.load_disease_skill(selected_disease_key)
        if self._should_stop_for_alignment(alignment_plan):
            return self._handle_insufficient_alignment_case(
                case_id=case_id,
                case_input=case_input,
                disease_skill=disease_skill,
                selected_disease_key=selected_disease_key,
                selected_vision_mode=selected_vision_mode,
                routing_decision=routing_decision,
                alignment_plan=alignment_plan or {},
                intent_type=intent_type,
            )
        visual_result = self._run_visual_analysis(
            case_id=case_id,
            image_path=case_input.image_path,
            patient_message=case_input.patient_message,
            disease_key=selected_disease_key,
            disease_skill=disease_skill,
            vision_mode=vision_mode,
            mask_path=mask_path,
            segmentation_prompt=segmentation_prompt,
            image_series=case_input.patient_info.get("image_series", []),
        )
        report = self.diagnosis_agent.generate_report(
            case_id=case_id,
            patient_info=case_input.patient_info,
            visual_result=visual_result,
            disease_skill=disease_skill,
            hypothesis_validation_mode=hypothesis_validation_mode,
            alignment_plan=alignment_plan,
            routing_decision=routing_decision,
        )

        patient_memory = {
            "case_id": case_id,
            "patient_id": case_input.patient_info.get("patient_id"),
            "patient_message": case_input.patient_message,
            "patient_info": case_input.patient_info,
            "patient_profile": case_input.patient_info,
            "symptoms": case_input.patient_info.get("symptoms", []),
            "intent": intent_type,
            "qa_history": [],
        }
        visual_evidence = visual_result["visual_evidence"]
        visual_evidence_bundle = self._build_visual_evidence_bundle(
            visual_result,
            disease_skill,
            image_series=case_input.patient_info.get("image_series", []),
            primary_image_path=case_input.image_path,
        )
        image_memory = {
            "case_id": case_id,
            "image_id": "image_001",
            "image_path": case_input.image_path,
            "image_series": case_input.patient_info.get("image_series", []),
            "modality": visual_result["modality"],
            "body_part": visual_result["body_part"],
            "image_outputs": visual_result["image_outputs"],
            "visual_features": visual_evidence,
            "visual_evidence": visual_evidence,
            "measurements": visual_evidence.get("measurements", {}),
            "completeness": visual_evidence.get("completeness", {}),
            "segmentation_quality": visual_evidence.get("segmentation_quality", "not_available"),
            "visual_evidence_bundle": visual_evidence_bundle,
        }
        used_skill = report["used_skill"]
        guideline_evidence = report.get("guideline_evidence", {})
        skill_memory = {
            **used_skill,
            "selected_skill": used_skill.get("skill_id", selected_disease_key),
            "selected_vision_mode": selected_vision_mode,
            "routing_decision": routing_decision,
            "alignment_plan": alignment_plan or {},
            "used_skill": used_skill.get("skill_id", selected_disease_key),
            "skill_type": used_skill.get("skill_type"),
            "guideline_evidence": guideline_evidence,
            "source_priority": guideline_evidence.get("source_priority", used_skill.get("source_priority", [])),
            "guideline_conflicts": guideline_evidence.get(
                "conflicts",
                used_skill.get("guideline_conflicts", []),
            ),
            "quality_control": guideline_evidence.get(
                "quality_control",
                used_skill.get("quality_control", {}),
            ),
        }
        reasoning_memory = {
            "case_id": case_id,
            "report": report,
            "used_skill": used_skill["skill_id"],
            "key_evidence": report["影像依据"],
            "diagnostic_result": report["diagnostic_tendency"],
            "diagnostic_tendency": report["diagnostic_tendency"],
            "visual_input_contract": report.get("visual_input_contract", {}),
            "visual_fact_usage": report.get("visual_fact_usage", {}),
            "used_visual_facts": report.get("used_visual_facts", []),
            "excluded_visual_facts": report.get("excluded_visual_facts", []),
            "used_visual_fields": report.get("used_visual_fields", []),
            "missing_visual_fields_acknowledged": report.get(
                "missing_visual_fields_acknowledged",
                [],
            ),
            "uncertainty": report["不确定性说明"],
            "follow_up": report["建议进一步检查"],
            "treatment_advice": report["治疗建议"],
            "alignment_plan": alignment_plan or {},
        }
        case_path = self.memory_manager.save_case_memory(
            case_id=case_id,
            patient_memory=patient_memory,
            image_memory=image_memory,
            skill_memory=skill_memory,
            reasoning_memory=reasoning_memory,
        )

        return {
            "case_id": case_id,
            "reply_to_patient": self._explain_report(report),
            "report": report,
            "case_memory_path": str(case_path),
            "alignment_plan": alignment_plan or {},
            "analysis_status": (alignment_plan or {}).get("analysis_status", "evidence_sufficient"),
        }

    def _should_stop_for_alignment(self, alignment_plan: dict[str, Any] | None) -> bool:
        if not alignment_plan:
            return False
        return alignment_plan.get("analysis_status") in {
            "insufficient_evidence",
            "contraindicated_or_wrong_modality",
        }

    def _handle_insufficient_alignment_case(
        self,
        case_id: str,
        case_input: PatientCaseInput,
        disease_skill: dict[str, Any],
        selected_disease_key: str,
        selected_vision_mode: str | None,
        routing_decision: dict[str, Any],
        alignment_plan: dict[str, Any],
        intent_type: str,
    ) -> dict[str, Any]:
        checked_plan = AlignmentPlan.from_dict(alignment_plan).to_dict()
        used_skill = SkillDescriptor.from_skill(disease_skill).to_dict()
        completeness = self._alignment_completeness(checked_plan)
        image_context = checked_plan.get("image_context", {})
        visual_evidence = {
            "segmentation_quality": "not_run_insufficient_evidence",
            "measurements": {},
            "completeness": completeness,
            "suspected_visual_findings": [],
            "disease_target": checked_plan.get("selected_skill"),
        }
        image_outputs = {
            "original_image_path": case_input.image_path,
            "mask_path": "not_generated",
            "overlay_path": "not_generated",
        }
        report = self._build_alignment_insufficient_report(
            case_id=case_id,
            alignment_plan=checked_plan,
            visual_evidence=visual_evidence,
            image_outputs=image_outputs,
            used_skill=used_skill,
        )
        self.diagnosis_agent._attach_guideline_evidence(report, used_skill)

        patient_memory = {
            "case_id": case_id,
            "patient_id": case_input.patient_info.get("patient_id"),
            "patient_message": case_input.patient_message,
            "patient_info": case_input.patient_info,
            "patient_profile": case_input.patient_info,
            "symptoms": case_input.patient_info.get("symptoms", []),
            "intent": intent_type,
            "qa_history": [],
        }
        image_memory = {
            "case_id": case_id,
            "image_id": "image_001",
            "image_path": case_input.image_path,
            "modality": image_context.get("modality", "unknown"),
            "body_part": image_context.get("body_part", "unknown"),
            "image_outputs": image_outputs,
            "visual_features": visual_evidence,
            "visual_evidence": visual_evidence,
            "measurements": {},
            "completeness": completeness,
            "segmentation_quality": "not_run_insufficient_evidence",
            "alignment_plan": checked_plan,
        }
        guideline_evidence = report.get("guideline_evidence", {})
        skill_memory = {
            **used_skill,
            "selected_skill": used_skill.get("skill_id", selected_disease_key),
            "selected_vision_mode": selected_vision_mode,
            "routing_decision": routing_decision,
            "alignment_plan": checked_plan,
            "used_skill": used_skill.get("skill_id", selected_disease_key),
            "skill_type": used_skill.get("skill_type"),
            "guideline_evidence": guideline_evidence,
            "source_priority": guideline_evidence.get("source_priority", used_skill.get("source_priority", [])),
            "guideline_conflicts": guideline_evidence.get(
                "conflicts",
                used_skill.get("guideline_conflicts", []),
            ),
            "quality_control": guideline_evidence.get(
                "quality_control",
                used_skill.get("quality_control", {}),
            ),
        }
        reasoning_memory = {
            "case_id": case_id,
            "report": report,
            "used_skill": used_skill["skill_id"],
            "key_evidence": report["影像依据"],
            "diagnostic_result": report["diagnostic_tendency"],
            "diagnostic_tendency": report["diagnostic_tendency"],
            "visual_input_contract": report["visual_input_contract"],
            "used_visual_fields": [],
            "missing_visual_fields_acknowledged": list(completeness),
            "uncertainty": report["不确定性说明"],
            "follow_up": report["建议进一步检查"],
            "treatment_advice": report["治疗建议"],
            "alignment_plan": checked_plan,
        }
        case_path = self.memory_manager.save_case_memory(
            case_id=case_id,
            patient_memory=patient_memory,
            image_memory=image_memory,
            skill_memory=skill_memory,
            reasoning_memory=reasoning_memory,
        )
        return {
            "case_id": case_id,
            "reply_to_patient": self._explain_alignment_insufficiency(report, checked_plan),
            "report": report,
            "case_memory_path": str(case_path),
            "alignment_plan": checked_plan,
            "analysis_status": checked_plan["analysis_status"],
            "suspected_conditions": checked_plan.get("suspected_conditions", []),
            "required_next_images": checked_plan.get("required_next_images", []),
        }

    def _alignment_completeness(self, alignment_plan: dict[str, Any]) -> dict[str, Any]:
        completeness: dict[str, Any] = {}
        for task in alignment_plan.get("visual_tasks", []):
            task_name = task.get("task")
            if not task_name:
                continue
            task_status = task.get("status")
            if task_status == "missing_input":
                status = "missing"
            elif task_status == "runnable":
                status = "unassessed"
            else:
                status = "unassessed"
            completeness[str(task_name)] = {
                "status": status,
                "reason": task.get("reason", "Not assessed by alignment gate"),
            }
        return completeness

    def _build_alignment_insufficient_report(
        self,
        case_id: str,
        alignment_plan: dict[str, Any],
        visual_evidence: dict[str, Any],
        image_outputs: dict[str, Any],
        used_skill: dict[str, Any],
    ) -> dict[str, Any]:
        image_context = alignment_plan.get("image_context", {})
        suspected = alignment_plan.get("suspected_conditions") or []
        suspected_text = "；".join(
            f"{item.get('disease', '疑似疾病')}：{item.get('reason', '')}"
            for item in suspected
        )
        next_images = alignment_plan.get("required_next_images") or []
        next_steps = [
            f"建议上传或完善{item.get('region', '')} {item.get('modality', '')}：{item.get('reason', '')}".strip()
            for item in next_images
        ] or ["建议补充指南要求的关键影像后再进行判断"]
        reasons = alignment_plan.get("insufficiency_reasons") or [
            "当前上传图像不满足该 skill 的关键影像证据要求"
        ]
        report = {
            "case_id": case_id,
            "diagnostic_tendency": "现有影像证据不足，需补充检查后判断",
            "诊断倾向": "现有影像证据不足，需补充检查后判断",
            "影像依据": [
                f"当前上传图像识别为 {image_context.get('modality', 'unknown')} / {image_context.get('body_part', 'unknown')}",
                suspected_text or "症状和图像线索提示存在疑似疾病方向，但证据不足。",
            ],
            "分期判断": "暂无法依据当前影像按指南完成可靠分期或排除诊断。",
            "不确定性说明": reasons
            + list(alignment_plan.get("diagnosis_scope", {}).get("blocked", [])),
            "建议进一步检查": next_steps,
            "治疗建议": [
                "该结果不是最终诊断，需线下专科医生结合体征、完整影像和必要检查复核。",
                "如症状持续、加重或出现功能受限，应及时线下就医。",
            ],
            "used_skill": used_skill,
            "alignment_plan": alignment_plan,
            "visual_input_contract": {
                "image_path": image_context.get("image_path"),
                "modality": image_context.get("modality", "unknown"),
                "body_part": image_context.get("body_part", "unknown"),
                "image_outputs": image_outputs,
                "requested_targets": [],
                "requested_features": [],
                "visual_evidence": visual_evidence,
                "measurements": {},
                "completeness": visual_evidence.get("completeness", {}),
                "segmentation_quality": visual_evidence["segmentation_quality"],
            },
        }
        return report

    def _explain_alignment_insufficiency(
        self,
        report: dict[str, Any],
        alignment_plan: dict[str, Any],
    ) -> str:
        suspected = alignment_plan.get("suspected_conditions") or []
        suspected_text = "、".join(
            str(item.get("disease")) for item in suspected if item.get("disease")
        ) or "相关疾病"
        next_images = alignment_plan.get("required_next_images") or []
        next_text = "；".join(
            f"{item.get('region', '')} {item.get('modality', '')}".strip()
            for item in next_images
        ) or "指南要求的补充影像"
        uncertainty = "；".join(report["不确定性说明"])
        return (
            f"根据现有指南以及你上传的医疗图像，目前无法进行可靠判断。"
            f"结合症状和图像线索，仍需考虑{suspected_text}可能。"
            f"主要限制是：{uncertainty}。建议补充上传或完善 {next_text}。"
        )

    def _run_visual_analysis(
        self,
        case_id: str,
        image_path: str,
        patient_message: str,
        disease_key: str,
        disease_skill: dict[str, Any],
        vision_mode: str | None,
        mask_path: str | None,
        segmentation_prompt: dict[str, Any] | None,
        image_series: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if disease_key == "femoral_head_necrosis" and vision_mode == "real_vlm_validation":
            return self._run_real_vlm_validation_visual_pipeline(
                case_id=case_id,
                image_path=image_path,
                patient_message=patient_message,
                disease_key=disease_key,
                disease_skill=disease_skill,
                image_series=image_series or [],
            )
        if disease_key == "femoral_head_necrosis" and vision_mode == "no_mask_skill":
            normalized_series = self._normalize_input_image_series(
                image_series=image_series or [],
                primary_image_path=image_path,
            )
            if len(normalized_series) > 1:
                return self._run_multi_view_no_mask_skill_visual_pipeline(
                    case_id=case_id,
                    image_series=normalized_series,
                    patient_message=patient_message,
                    disease_key=disease_key,
                    disease_skill=disease_skill,
                )
            return self._run_no_mask_skill_visual_pipeline(
                case_id=case_id,
                image_path=image_path,
                patient_message=patient_message,
                disease_key=disease_key,
                disease_skill=disease_skill,
            )
        if disease_key != "diffuse_glioma_brats":
            return self.vision_agent.analyze_image(
                image_path=image_path,
                disease_skill=disease_skill,
            )

        mode = vision_mode or "ground_truth"
        output_dir = Path("output/fake/gaodoctor_brats")
        output_dir.mkdir(parents=True, exist_ok=True)
        if mode == "ground_truth":
            if not mask_path:
                raise ValueError("mask_path is required for diffuse_glioma_brats ground_truth mode")
            return self.vision_agent.analyze_with_visual_protocol(
                image_path=image_path,
                mask_path=mask_path,
                overlay_path=str(output_dir / f"{case_id}_overlay.png"),
                disease_skill=disease_skill,
            )
        if mode == "medsam2":
            model_mask_path = mask_path or str(output_dir / f"{case_id}_medsam2_mask.nii.gz")
            overlay_path = output_dir / f"{case_id}_medsam2_overlay.png"
            segmentation_tool = SegmentationTool(
                mask_reader=NiftiMaskReaderTool(),
                overlay_generator=NiftiOverlayGenerationTool(),
                feature_extractor=getattr(self.vision_agent, "feature_extractor", None),
                model_backend=MedSAM2SegmentationTool(runner=MedSAM2CommandRunner.from_env()),
            )
            return VisionAgent(
                segmentation_tool=segmentation_tool,
                visual_tool_router=getattr(self.vision_agent, "visual_tool_router", None),
                quality_gate=getattr(self.vision_agent, "quality_gate", None),
                feature_extractor=getattr(self.vision_agent, "feature_extractor", None),
            ).analyze_with_visual_protocol(
                image_path=image_path,
                segmentation_prompt=segmentation_prompt or {},
                output_mask_path=str(model_mask_path),
                overlay_path=str(overlay_path),
                disease_skill=disease_skill,
            )
        raise ValueError(f"unsupported vision_mode for diffuse_glioma_brats: {mode}")

    def _run_real_vlm_validation_visual_pipeline(
        self,
        *,
        case_id: str,
        image_path: str,
        patient_message: str,
        disease_key: str,
        disease_skill: dict[str, Any],
        image_series: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized_series = self._normalize_input_image_series(
            image_series=image_series,
            primary_image_path=image_path,
        )
        image_paths = [item["image_path"] for item in normalized_series]
        raw_payload, warning = self._call_real_vlm_validation_runner(
            patient_message=patient_message,
            disease_key=disease_key,
            disease_skill=disease_skill,
            image_series=normalized_series,
        )
        primary = normalized_series[0] if normalized_series else {
            "image_id": "image_001",
            "image_path": image_path,
            "view_hint": "unknown",
        }
        evidence_items = (
            parse_vlm_candidates(
                raw_payload,
                image_id=str(primary["image_id"]),
                view_hint=str(primary.get("view_hint") or "unknown"),
                source_image_path=str(primary.get("image_path") or image_path),
                imaging_evidence_protocol=disease_skill.get("imaging_evidence_protocol"),
            )
            if isinstance(raw_payload, dict)
            else []
        )
        quality_warnings = []
        if warning:
            quality_warnings.append({"warning": warning, "source": "real_vlm_validation"})
        if not evidence_items:
            evidence_items = [
                {
                    "target": "real_vlm_validation",
                    "image_id": str(primary["image_id"]),
                    "view_hint": str(primary.get("view_hint") or "unknown"),
                    "source_image_path": str(primary.get("image_path") or image_path),
                    "evidence_type": "visual_observation",
                    "execution_mode": "vlm_only",
                    "visual_observation": {
                        "status": "unassessed",
                        "reason": warning or "VLM did not return usable candidate findings.",
                    },
                    "segmentation": {"status": "not_requested"},
                    "measurements": {"measurement_usable": False},
                    "quality": {"status": "not_usable", "source": "vlm"},
                    "diagnosis_usable": False,
                    "diagnosis_usable_level": "not_usable",
                    "limitations": [warning or "no_vlm_candidate_findings"],
                }
            ]
        findings = [
            self._finding_from_vlm_evidence_item(item)
            for item in evidence_items
            if isinstance(item, dict)
        ]
        return {
            "image_path": image_path,
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": image_path,
                "mask_path": "not_generated",
                "overlay_path": "not_generated",
                "per_image_outputs": [
                    {
                        "image_id": item["image_id"],
                        "view_hint": item.get("view_hint", "unknown"),
                        "image_path": item["image_path"],
                        "image_outputs": {
                            "original_image_path": item["image_path"],
                            "mask_path": "not_generated",
                            "overlay_path": "not_generated",
                        },
                    }
                    for item in normalized_series
                ],
            },
            "multi_view_results": [
                {
                    "image_id": item["image_id"],
                    "view_hint": item.get("view_hint", "unknown"),
                    "image_path": item["image_path"],
                }
                for item in normalized_series
            ],
            "visual_evidence": {
                "collapse": False,
                "sclerosis": "candidate" if evidence_items else "unassessed",
                "cystic_change": "unknown",
                "joint_space_narrowing": False,
                "joint_space": "unknown",
                "femoral_head_shape": "unknown",
                "lesion_mask": "not_generated",
                "confidence": self._max_vlm_confidence(evidence_items),
                "texture_abnormality_score": 0.0,
                "lesion_area_ratio": 0.0,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "lesion_detected": any(
                    item.get("diagnosis_usable_level") == "candidate_support"
                    for item in evidence_items
                ),
                "lesion_location": "candidate_vlm_region"
                if any(item.get("diagnosis_usable_level") == "candidate_support" for item in evidence_items)
                else "未定位",
                "disease_target": disease_key,
                "findings": findings,
                "evidence_items": evidence_items,
                "suspected_visual_findings": [
                    str((item.get("visual_observation") or {}).get("rationale") or item.get("target"))
                    for item in evidence_items
                    if item.get("diagnosis_usable_level") == "candidate_support"
                ],
                "measurements": {
                    "analyzed_image_count": len(image_paths),
                    "measurement_usable": False,
                },
                "completeness": {},
                "quality_warnings": quality_warnings,
                "segmentation_quality": "not_run_real_vlm_validation",
            },
        }

    def _max_vlm_confidence(self, evidence_items: list[dict[str, Any]]) -> float:
        confidences = [
            float((item.get("quality") or {}).get("confidence"))
            for item in evidence_items
            if (item.get("quality") or {}).get("confidence") is not None
        ]
        return max(confidences) if confidences else 0.0

    def _call_real_vlm_validation_runner(
        self,
        *,
        patient_message: str,
        disease_key: str,
        disease_skill: dict[str, Any],
        image_series: list[dict[str, str]],
    ) -> tuple[dict[str, Any] | None, str | None]:
        if self.prompt_runner is None:
            return None, "real_vlm_validation_not_configured"
        user_payload = {
            "patient_message": patient_message,
            "disease_key": disease_key,
            "image_paths": [item["image_path"] for item in image_series],
            "image_series": image_series,
            "imaging_evidence_protocol": disease_skill.get("imaging_evidence_protocol", {}),
            "instruction": (
                "Return candidate visual findings only as JSON. Do not diagnose. "
                "Do not claim segmentation or measurements."
            ),
        }
        try:
            response = self.prompt_runner.run(
                task="fhn_real_vlm_validation",
                system_prompt=(
                    "You are a visual evidence extractor. Return JSON with a findings list. "
                    "Each finding may include target, side, bbox, polygon, rationale, and confidence. "
                    "Do not provide a final diagnosis."
                ),
                user_payload=user_payload,
            )
            parsed = self._parse_real_vlm_validation_response(response)
        except Exception as exc:
            return None, f"real_vlm_validation_parse_error: {exc}"
        if not isinstance(parsed, dict):
            return None, "real_vlm_validation_parse_error: response was not a JSON object"
        return parsed, None

    def _parse_real_vlm_validation_response(self, response: Any) -> Any:
        if isinstance(response, dict):
            return response
        text = str(response).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        for block in self._extract_markdown_code_blocks(text):
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue
        json_object = self._extract_first_json_object(text)
        if json_object:
            return json.loads(json_object)
        return json.loads(text)

    def _extract_markdown_code_blocks(self, text: str) -> list[str]:
        blocks: list[str] = []
        parts = text.split("```")
        for index in range(1, len(parts), 2):
            block = parts[index].strip()
            if block.lower().startswith("json"):
                block = block[4:].strip()
            if block:
                blocks.append(block)
        return blocks

    def _extract_first_json_object(self, text: str) -> str | None:
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return None

    def _finding_from_vlm_evidence_item(self, item: dict[str, Any]) -> dict[str, Any]:
        observation = dict(item.get("visual_observation") or {})
        measurements = dict(item.get("measurements") or {})
        if observation.get("laterality") and "laterality" not in measurements:
            measurements["laterality"] = observation.get("laterality")
        return {
            "finding_id": item.get("finding_id"),
            "target": item.get("target"),
            "display_name": item.get("display_name") or item.get("target"),
            "image_id": item.get("image_id"),
            "view_hint": item.get("view_hint"),
            "source_image_path": item.get("source_image_path"),
            "status": observation.get("status", "unassessed"),
            "description": observation.get("rationale") or observation.get("reason"),
            "evidence_type": item.get("evidence_type"),
            "execution_mode": item.get("execution_mode"),
            "measurements": measurements,
            "quality": dict(item.get("quality") or {}),
            "diagnosis_usable": bool(item.get("diagnosis_usable", False)),
            "diagnosis_usable_level": item.get("diagnosis_usable_level", "not_usable"),
            "limitations": list(item.get("limitations") or []),
        }

    def _run_no_mask_skill_visual_pipeline(
        self,
        *,
        case_id: str,
        image_path: str,
        patient_message: str,
        disease_key: str,
        disease_skill: dict[str, Any],
        image_id: str | None = None,
    ) -> dict[str, Any]:
        runner = self.no_mask_visual_pipeline_runner
        if runner is None:
            from scripts.no_mask_skill_visual_pipeline_demo import (
                run_no_mask_skill_visual_pipeline_demo,
            )
            from scripts.no_mask_vision_prompt_demo import _load_dotenv_local

            _load_dotenv_local()
            runner = run_no_mask_skill_visual_pipeline_demo
        output_dir = Path("output/fake/gaodoctor_fhn_no_mask") / case_id
        if image_id:
            output_dir = output_dir / image_id
        summary = runner(
            image_path=image_path,
            output_dir=output_dir,
            disease_skill=disease_skill,
            disease_key=disease_key,
            patient_message=patient_message or "请根据股骨头坏死 skill 自动定位候选影像征象。",
        )
        if summary.get("status") != "ok":
            raise RuntimeError(
                f"FHN no-mask visual pipeline did not complete: {summary.get('status')}"
            )
        visual_result = summary.get("visual_analysis_result")
        if not isinstance(visual_result, dict):
            raise RuntimeError("FHN no-mask visual pipeline did not return visual_analysis_result")
        return visual_result

    def _run_multi_view_no_mask_skill_visual_pipeline(
        self,
        *,
        case_id: str,
        image_series: list[dict[str, Any]],
        patient_message: str,
        disease_key: str,
        disease_skill: dict[str, Any],
    ) -> dict[str, Any]:
        per_image_results = []
        for item in image_series:
            visual_result = self._run_no_mask_skill_visual_pipeline(
                case_id=case_id,
                image_path=str(item["image_path"]),
                patient_message=patient_message,
                disease_key=disease_key,
                disease_skill=disease_skill,
                image_id=str(item["image_id"]),
            )
            per_image_results.append(
                self._annotate_visual_result_image_context(
                    visual_result=visual_result,
                    image_id=str(item["image_id"]),
                    view_hint=str(item.get("view_hint") or "unknown"),
                )
            )
        return self._merge_multi_view_visual_results(per_image_results)

    def _normalize_input_image_series(
        self,
        *,
        image_series: list[dict[str, Any]],
        primary_image_path: str,
    ) -> list[dict[str, str]]:
        normalized = [
            {
                "image_id": str(item.get("image_id") or f"image_{index + 1:03d}"),
                "image_path": str(item.get("image_path") or ""),
                "view_hint": str(item.get("view_hint") or "unknown"),
            }
            for index, item in enumerate(image_series)
            if isinstance(item, dict) and item.get("image_path")
        ]
        if not normalized and primary_image_path:
            normalized = [
                {
                    "image_id": "image_001",
                    "image_path": primary_image_path,
                    "view_hint": "unknown",
                }
            ]
        return normalized

    def _annotate_visual_result_image_context(
        self,
        *,
        visual_result: dict[str, Any],
        image_id: str,
        view_hint: str,
    ) -> dict[str, Any]:
        annotated = dict(visual_result)
        annotated["image_id"] = image_id
        annotated["view_hint"] = view_hint
        evidence = dict(annotated.get("visual_evidence") or {})
        findings = []
        for finding in evidence.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            annotated_finding = dict(finding)
            annotated_finding["image_id"] = image_id
            annotated_finding["view_hint"] = view_hint
            annotated_finding["source_image_path"] = annotated.get("image_path")
            finding_id = str(annotated_finding.get("finding_id") or annotated_finding.get("target") or "finding")
            if not finding_id.startswith(f"{image_id}_"):
                annotated_finding["finding_id"] = f"{image_id}_{finding_id}"
            findings.append(annotated_finding)
        evidence["findings"] = findings
        evidence["segmentation_results"] = [
            {**result, "image_id": image_id, "view_hint": view_hint}
            for result in evidence.get("segmentation_results") or []
            if isinstance(result, dict)
        ]
        evidence["visual_tool_plan"] = [
            {**step, "image_id": image_id, "view_hint": view_hint}
            for step in evidence.get("visual_tool_plan") or []
            if isinstance(step, dict)
        ]
        annotated["visual_evidence"] = evidence
        return annotated

    def _merge_multi_view_visual_results(
        self,
        per_image_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not per_image_results:
            raise RuntimeError("multi-view visual pipeline did not return any image result")
        primary = dict(per_image_results[0])
        merged_evidence = dict(primary.get("visual_evidence") or {})
        merged_findings = []
        suspected_visual_findings = []
        segmentation_results = []
        visual_tool_plan = []
        per_image_outputs = []
        for result in per_image_results:
            evidence = result.get("visual_evidence") or {}
            image_id = result.get("image_id")
            view_hint = result.get("view_hint")
            merged_findings.extend(
                dict(finding)
                for finding in evidence.get("findings") or []
                if isinstance(finding, dict)
            )
            suspected_visual_findings.extend(
                f"{image_id}/{view_hint}: {item}"
                for item in evidence.get("suspected_visual_findings") or []
            )
            segmentation_results.extend(
                dict(item)
                for item in evidence.get("segmentation_results") or []
                if isinstance(item, dict)
            )
            visual_tool_plan.extend(
                dict(item)
                for item in evidence.get("visual_tool_plan") or []
                if isinstance(item, dict)
            )
            per_image_outputs.append(
                {
                    "image_id": image_id,
                    "view_hint": view_hint,
                    "image_path": result.get("image_path"),
                    "image_outputs": dict(result.get("image_outputs") or {}),
                }
            )
        merged_evidence["findings"] = merged_findings
        merged_evidence["suspected_visual_findings"] = suspected_visual_findings
        merged_evidence["segmentation_results"] = segmentation_results
        merged_evidence["visual_tool_plan"] = visual_tool_plan
        merged_evidence["segmentation_quality"] = "multi_view_candidate"
        measurements = dict(merged_evidence.get("measurements") or {})
        measurements["analyzed_image_count"] = len(per_image_results)
        merged_evidence["measurements"] = measurements
        image_outputs = dict(primary.get("image_outputs") or {})
        image_outputs["per_image_outputs"] = per_image_outputs
        primary["image_outputs"] = image_outputs
        primary["visual_evidence"] = merged_evidence
        primary["multi_view_results"] = per_image_outputs
        return primary

    def _build_visual_evidence_bundle(
        self,
        visual_result: dict[str, Any],
        disease_skill: dict[str, Any] | None = None,
        image_series: list[dict[str, Any]] | None = None,
        primary_image_path: str | None = None,
    ) -> dict[str, Any]:
        evidence = dict(visual_result.get("visual_evidence") or {})
        findings = [
            dict(finding)
            for finding in evidence.get("findings") or []
            if isinstance(finding, dict)
        ]
        present_findings = [
            str(finding.get("target"))
            for finding in findings
            if finding.get("status") in {"candidate_present", "supported", "detected"}
            and finding.get("diagnosis_usable", True)
            and str(finding.get("target") or "").strip()
        ]
        quality_warnings = [
            dict(warning)
            for warning in evidence.get("quality_warnings") or []
            if isinstance(warning, dict)
        ]
        evidence_items = self._build_evidence_items(
            evidence=evidence,
            visual_result=visual_result,
            disease_skill=disease_skill or {},
        )
        has_missing_protocol_completeness = any(
            isinstance(status, dict) and status.get("status") in {"missing", "unassessed", "low_quality"}
            for status in (evidence.get("completeness") or {}).values()
        )
        bundle_schema_version = (
            "visual_evidence_bundle.v2"
            if evidence.get("evidence_items") or has_missing_protocol_completeness
            else "visual_evidence_bundle.v1"
        )
        image_context = {
            "image_path": visual_result.get("image_path"),
            "modality": visual_result.get("modality"),
            "body_part": visual_result.get("body_part"),
        }
        image_context.update(
            self._build_image_series_context(
                image_series=image_series or [],
                primary_image_path=primary_image_path or str(visual_result.get("image_path") or ""),
                modality=str(visual_result.get("modality") or ""),
                body_part=str(visual_result.get("body_part") or ""),
                analyzed_image_paths=[
                    str(item.get("image_path"))
                    for item in visual_result.get("multi_view_results") or []
                    if isinstance(item, dict) and item.get("image_path")
                ],
            )
        )
        return {
            "schema_version": bundle_schema_version,
            "evidence_protocol_version": "visual_evidence_bundle.v2",
            "disease_target": evidence.get("disease_target"),
            "image_context": image_context,
            "image_outputs": dict(visual_result.get("image_outputs") or {}),
            "per_image_results": [
                dict(item)
                for item in visual_result.get("multi_view_results") or []
                if isinstance(item, dict)
            ],
            "present_findings": present_findings,
            "findings": findings,
            "evidence_items": evidence_items,
            "numeric_evidence": self._summarize_visual_numeric_evidence(findings),
            "structured_visual_facts": self._build_structured_visual_facts(findings),
            "text_evidence": list(evidence.get("suspected_visual_findings") or []),
            "quality_warnings": quality_warnings,
            "completeness": dict(evidence.get("completeness") or {}),
            "segmentation_results": [
                dict(result)
                for result in evidence.get("segmentation_results") or []
                if isinstance(result, dict)
            ],
            "visual_tool_plan": [
                dict(step)
                for step in evidence.get("visual_tool_plan") or []
                if isinstance(step, dict)
            ],
            "diagnosis_payload": visual_result,
            "aggregation_note": (
                "total_area_px is the sum of per-finding candidate masks and can double-count "
                "overlapping findings; Diagnosis Agent should reason per finding."
            ),
        }

    def _build_image_series_context(
        self,
        *,
        image_series: list[dict[str, Any]],
        primary_image_path: str,
        modality: str,
        body_part: str,
        analyzed_image_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_series = [
            {
                "image_id": str(item.get("image_id") or f"image_{index + 1:03d}"),
                "image_path": str(item.get("image_path") or ""),
                "view_hint": str(item.get("view_hint") or "unknown"),
            }
            for index, item in enumerate(image_series)
            if isinstance(item, dict) and item.get("image_path")
        ]
        if not normalized_series and primary_image_path:
            normalized_series = [
                {
                    "image_id": "image_001",
                    "image_path": primary_image_path,
                    "view_hint": "unknown",
                }
            ]
        primary_image_id = self._primary_image_id(
            image_series=normalized_series,
            primary_image_path=primary_image_path,
        )
        provided_views = []
        for item in normalized_series:
            view = item.get("view_hint") or "unknown"
            if view not in provided_views:
                provided_views.append(view)
        expected_views = (
            ["ap_pelvis", "frog_lateral"]
            if modality.lower() == "xray" and body_part.lower() == "hip"
            else []
        )
        analyzed_paths = set(analyzed_image_paths or [])
        analyzed_views = []
        for item in normalized_series:
            if item.get("image_path") not in analyzed_paths:
                continue
            view = item.get("view_hint") or "unknown"
            if view not in analyzed_views:
                analyzed_views.append(view)
        analysis_scope = "single_image"
        if len(normalized_series) > 1:
            analysis_scope = (
                "multi_view_execution"
                if len(analyzed_paths) > 1
                else "primary_image_only"
            )
        return {
            "image_series": normalized_series,
            "primary_image_id": primary_image_id,
            "view_coverage": {
                "provided_views": provided_views,
                "analyzed_views": analyzed_views,
                "expected_views": expected_views,
                "missing_views": [
                    view for view in expected_views if view not in provided_views
                ],
                "analysis_scope": analysis_scope,
            },
        }

    def _primary_image_id(
        self,
        *,
        image_series: list[dict[str, Any]],
        primary_image_path: str,
    ) -> str:
        for item in image_series:
            if item.get("image_path") == primary_image_path:
                return str(item.get("image_id") or "image_001")
        return str(image_series[0].get("image_id") or "image_001") if image_series else "image_001"

    def _build_evidence_items(
        self,
        *,
        evidence: dict[str, Any],
        visual_result: dict[str, Any],
        disease_skill: dict[str, Any],
    ) -> list[dict[str, Any]]:
        explicit_items = [
            dict(item)
            for item in evidence.get("evidence_items") or []
            if isinstance(item, dict)
        ]
        if explicit_items:
            return [self._normalize_evidence_item(item) for item in explicit_items]

        protocol_by_target = self._evidence_protocol_by_target(disease_skill)
        items = [
            self._evidence_item_from_finding(
                finding,
                protocol_by_target.get(str(finding.get("target") or "")),
            )
            for finding in evidence.get("findings") or []
            if isinstance(finding, dict)
        ]
        completeness = evidence.get("completeness") or {}
        for target, status in completeness.items():
            if not isinstance(status, dict) or status.get("status") not in {"missing", "unassessed"}:
                continue
            if any(item.get("target") == target for item in items):
                continue
            items.append(
                {
                    "target": str(target),
                    "evidence_type": "visual_observation",
                    "execution_mode": "insufficient_input"
                    if status.get("status") == "missing"
                    else "vlm_only",
                    "visual_observation": {
                        "status": status.get("status"),
                        "reason": status.get("reason", "not assessed"),
                    },
                    "segmentation": {},
                    "measurements": {},
                    "quality": {"status": status.get("status")},
                    "diagnosis_usable": False,
                    "diagnosis_usable_level": "not_usable",
                    "limitations": [status.get("reason", "not assessed")],
                }
            )
        return [self._normalize_evidence_item(item) for item in items]

    def _evidence_protocol_by_target(self, disease_skill: dict[str, Any]) -> dict[str, dict[str, Any]]:
        imaging_protocol = disease_skill.get("imaging_evidence_protocol") or {}
        targets = imaging_protocol.get("finding_targets") or []
        return {
            str(item.get("target")): dict(item)
            for item in targets
            if isinstance(item, dict) and item.get("target")
        }

    def _evidence_item_from_finding(
        self,
        finding: dict[str, Any],
        protocol_item: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        protocol_item = protocol_item or {}
        diagnosis_level = str(
            finding.get("diagnosis_usable_level")
            or protocol_item.get("diagnosis_usable_level")
            or ""
        )
        if not diagnosis_level:
            diagnosis_level = (
                "candidate_support"
                if finding.get("diagnosis_usable", True)
                else "not_usable"
            )
        evidence_type = str(finding.get("evidence_type") or protocol_item.get("evidence_type") or "")
        if not evidence_type:
            evidence_type = (
                "anatomical_measurement"
                if diagnosis_level == "measurement_support"
                else "image_feature_quantification"
                if diagnosis_level == "exploratory_only"
                else "candidate_mask"
            )
        measurements = dict(finding.get("measurements") or {})
        if protocol_item.get("measurement_dependencies"):
            measurements.setdefault(
                "measurement_dependencies",
                list(protocol_item.get("measurement_dependencies") or []),
            )
        if "measurement_usable" not in measurements:
            measurements["measurement_usable"] = bool(
                finding.get(
                    "measurement_usable",
                    protocol_item.get("measurement_usable", False),
                )
            )
        return {
            "target": str(finding.get("target") or ""),
            "image_id": finding.get("image_id"),
            "view_hint": finding.get("view_hint"),
            "display_name": finding.get("display_name") or finding.get("target"),
            "evidence_type": evidence_type,
            "execution_mode": finding.get("execution_mode") or protocol_item.get("execution_mode") or (
                "measurement_only" if evidence_type == "anatomical_measurement" else "vlm_plus_segmenter"
            ),
            "visual_observation": {
                "status": finding.get("status"),
                "description": finding.get("description"),
            },
            "segmentation": dict(finding.get("segmentation") or {}),
            "measurements": measurements,
            "quality": dict(finding.get("quality") or {}),
            "diagnosis_usable": bool(finding.get("diagnosis_usable", False)),
            "diagnosis_usable_level": diagnosis_level,
            "limitations": list(finding.get("limitations") or []),
        }

    def _normalize_evidence_item(self, item: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(item)
        normalized.setdefault("visual_observation", {})
        normalized.setdefault("segmentation", {})
        normalized.setdefault("measurements", {})
        normalized.setdefault("quality", {})
        normalized.setdefault("diagnosis_usable", False)
        normalized.setdefault("diagnosis_usable_level", "not_usable")
        normalized.setdefault("limitations", [])
        return normalized

    def _build_structured_visual_facts(
        self,
        findings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        from tools.structured_visual_fact_builder import build_structured_visual_facts

        return build_structured_visual_facts(findings)

    def _summarize_visual_numeric_evidence(
        self,
        findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total_area_px = 0
        total_diagnosis_usable_area_px = 0
        total_region_count = 0
        independent_finding_count = 0
        non_independent_finding_count = 0
        diagnosis_usable_finding_count = 0
        diagnosis_unusable_finding_count = 0
        area_ratios_in_image: list[float] = []
        area_ratios_in_anatomy: list[float] = []
        for finding in findings:
            diagnosis_usable = bool(finding.get("diagnosis_usable", True))
            if diagnosis_usable:
                diagnosis_usable_finding_count += 1
            else:
                diagnosis_unusable_finding_count += 1

            if diagnosis_usable and finding.get("independent_evidence", True):
                independent_finding_count += 1
            elif diagnosis_usable:
                non_independent_finding_count += 1
            measurements = finding.get("measurements") or {}
            area_px = int(measurements.get("area_px") or 0)
            total_area_px += area_px
            if diagnosis_usable:
                total_diagnosis_usable_area_px += area_px
            ratio_in_image = measurements.get("area_ratio_in_image")
            if ratio_in_image is not None:
                area_ratios_in_image.append(float(ratio_in_image))
            ratio_in_anatomy = measurements.get("area_ratio_in_anatomy")
            if ratio_in_anatomy is not None:
                area_ratios_in_anatomy.append(float(ratio_in_anatomy))
            total_region_count += len(finding.get("regions") or [])
        return {
            "finding_count": len(findings),
            "independent_finding_count": independent_finding_count,
            "non_independent_finding_count": non_independent_finding_count,
            "diagnosis_usable_finding_count": diagnosis_usable_finding_count,
            "diagnosis_unusable_finding_count": diagnosis_unusable_finding_count,
            "region_count": total_region_count,
            "total_area_px": total_area_px,
            "total_diagnosis_usable_area_px": total_diagnosis_usable_area_px,
            "sum_area_ratio_in_image": round(sum(area_ratios_in_image), 6),
            "max_area_ratio_in_anatomy": (
                round(max(area_ratios_in_anatomy), 6) if area_ratios_in_anatomy else None
            ),
        }

    def answer_follow_up(self, case_id: str, question: str) -> str:
        evidence_bundle = self.memory_manager.get_evidence_bundle(case_id)
        llm_used = False
        llm_fallback_reason = None
        if self._is_identity_question(question):
            answer = self._answer_identity_follow_up()
            self.memory_manager.append_qa_memory(
                case_id=case_id,
                question=question,
                answer=answer,
                llm_used=False,
                llm_fallback_reason="identity_question_template",
            )
            return answer
        if self.prompt_runner:
            try:
                answer = self._answer_follow_up_with_llm(
                    question=question,
                    evidence_bundle=evidence_bundle,
                )
                llm_used = True
            except Exception as exc:
                llm_fallback_reason = str(exc)
                answer = self._answer_follow_up_with_template(
                    question=question,
                    evidence_bundle=evidence_bundle,
                )
        else:
            answer = self._answer_follow_up_with_template(
                question=question,
                evidence_bundle=evidence_bundle,
            )
            llm_fallback_reason = "prompt_runner_not_configured"
        self.memory_manager.append_qa_memory(
            case_id=case_id,
            question=question,
            answer=answer,
            llm_used=llm_used,
            llm_fallback_reason=llm_fallback_reason,
        )
        return answer

    def _answer_follow_up_with_llm(
        self,
        question: str,
        evidence_bundle: dict[str, Any],
    ) -> str:
        answer = self.prompt_runner.run(
            task="follow_up_qa",
            system_prompt=(
                "你是高医生 Agent，负责回答患者对已保存病例的追问。"
                "你只能使用 user_payload.evidence_bundle 中已有的证据回答。"
                "不得新增影像发现、诊断结论、指南依据或治疗建议。"
                "如果 evidence_bundle 中存在 integrated_reasoning_evidence，"
                "必须优先用它判断能否确认疾病、证据是否不足、下一步建议是什么；"
                "底层视觉、量化和鉴别字段只能作为解释依据。"
                "如果 reasoning_evidence.visual_fact_usage 或 visual_fact_usage 中有 excluded facts，"
                "不得把 excluded fact 说成独立诊断依据；必须说明其 exclusion_reason。"
                "如果 evidence_bundle 中字段为 missing 或 unassessed，必须明确说明证据缺失，"
                "不得把缺失解释为阴性、正常、没有发现或数值为 0。"
                "回答必须面向患者，先直接回答问题，再用最多 1-2 句解释。"
                "不要输出 Case ID、字段名、JSON key、英文技术标签、完整报告、项目符号列表或 evidence_bundle 原文。"
                "底层字段只能作为内部依据，不能原样展示给患者。"
            ),
            user_payload={
                "question": question,
                "evidence_bundle": evidence_bundle,
                "required_safety_rules": [
                    "Only answer from evidence_bundle.",
                    "Prefer integrated_reasoning_evidence for conclusion boundaries when present.",
                    "Do not invent visual findings.",
                    "Use visual_fact_usage.used as usable evidence.",
                    "Do not count visual_fact_usage.excluded as independent evidence.",
                    "Do not interpret missing/unassessed fields as negative or zero.",
                    "Explain uncertainty when evidence is incomplete.",
                ],
            },
        ).strip()
        if not answer:
            raise ValueError("empty llm follow-up answer")
        self._validate_follow_up_answer_against_evidence_bundle(answer, evidence_bundle)
        answer = self._sanitize_patient_follow_up_answer(answer)
        return answer

    def _sanitize_patient_follow_up_answer(self, answer: str) -> str:
        lines = [
            line.strip(" -*\t")
            for line in answer.splitlines()
            if line.strip()
        ]
        compact = " ".join(lines)
        compact = re.sub(r"\*\*(.*?)\*\*", r"\1", compact)
        compact = re.sub(r"__(.*?)__", r"\1", compact)
        compact = compact.replace("**", "").replace("__", "")
        patient_term_replacements = {
            "测量级定位遮罩": "可用于测量的分割结果",
            "测量级 mask": "可用于测量的分割结果",
            "测量级mask": "可用于测量的分割结果",
            "定位遮罩": "分割结果",
            "遮罩": "分割结果",
            "分割图像显示缺失": "分割对照图缺失",
        }
        for technical_term, patient_term in patient_term_replacements.items():
            compact = compact.replace(technical_term, patient_term)
        if len(compact) <= 360:
            return compact
        return compact[:357].rstrip() + "..."

    def _validate_follow_up_answer_against_evidence_bundle(
        self,
        answer: str,
        evidence_bundle: dict[str, Any],
    ) -> None:
        blocked_items = (
            evidence_bundle.get("skill_evidence", {})
            .get("alignment_plan", {})
            .get("diagnosis_scope", {})
            .get("blocked", [])
            or []
        )
        missing_items = evidence_bundle.get("missing_or_unassessed", {}).get("image_memory", {})
        markers = self._forbidden_answer_markers(blocked_items)
        if missing_items:
            markers.extend(["为 0", "为0", "0 ml", "阴性", "未见", "未发现", "无强化", "没有强化"])
        if markers and self._has_unqualified_answer_claim(answer, markers):
            raise ValueError("follow-up llm answer violates evidence constraints")
        self._validate_follow_up_answer_against_visual_fact_usage(answer, evidence_bundle)

    def _validate_follow_up_answer_against_visual_fact_usage(
        self,
        answer: str,
        evidence_bundle: dict[str, Any],
    ) -> None:
        usage = self._visual_fact_usage_from_evidence_bundle(evidence_bundle)
        excluded = usage.get("excluded") or []
        if not excluded:
            return
        independent_markers = [
            "独立诊断依据",
            "独立证据",
            "可以和",
            "一起支持",
            "支持判断",
            "说明患有",
            "证明",
        ]
        for fact in excluded:
            if not isinstance(fact, dict):
                continue
            labels = [
                str(fact.get("display_name") or ""),
                str(fact.get("target") or ""),
                str(fact.get("finding_id") or ""),
            ]
            labels = [label for label in labels if label]
            if not labels or not any(label in answer for label in labels):
                continue
            if self._has_unqualified_answer_claim(answer, independent_markers):
                raise ValueError("follow-up llm answer uses excluded visual fact")

    def _forbidden_answer_markers(self, blocked_items: list[Any]) -> list[str]:
        markers: list[str] = []
        for item in blocked_items:
            text = str(item)
            if any(term in text for term in ["无病", "排除", "正常", "阴性"]):
                markers.extend(["无病", "排除", "正常", "阴性"])
            if any(term in text for term in ["强化", "T1ce", "增强"]):
                markers.extend(["无强化", "未见强化", "没有强化", "强化阴性", "增强肿瘤为 0", "0 ml"])
            if any(term in text for term in ["缺失", "缺少", "missing_input", "missing"]):
                markers.extend(["为 0", "为0", "0 ml", "阴性", "未见", "未发现", "正常"])
        return list(dict.fromkeys(markers))

    def _has_unqualified_answer_claim(self, answer: str, markers: list[str]) -> bool:
        negation_markers = ["不能", "不可", "不得", "不应", "无法", "不能判断", "不能解释"]
        for marker in markers:
            search_from = 0
            while True:
                index = answer.find(marker, search_from)
                if index == -1:
                    break
                prefix = answer[max(0, index - 32) : index]
                suffix = answer[index + len(marker) : index + len(marker) + 40]
                if self._is_qualified_missing_evidence_phrase(marker, suffix):
                    search_from = index + len(marker)
                    continue
                if not any(negation in prefix for negation in negation_markers):
                    return True
                search_from = index + len(marker)
        return False

    def _is_qualified_missing_evidence_phrase(self, marker: str, suffix: str) -> bool:
        if marker not in {"未见", "未发现"}:
            return False
        evidence_terms = ["证据", "依据", "信息", "数据"]
        qualifier_terms = ["可用于", "足够", "充分", "能够", "能用来", "支持", "判断"]
        return any(term in suffix for term in evidence_terms) and any(
            term in suffix for term in qualifier_terms
        )

    def _answer_follow_up_with_template(
        self,
        question: str,
        evidence_bundle: dict[str, Any],
    ) -> str:
        if self._is_identity_question(question):
            return self._answer_identity_follow_up()
        if self._is_prognosis_question(question):
            return self._answer_prognosis_follow_up_with_template(evidence_bundle)
        if self._is_clinical_context_question(question):
            return self._answer_clinical_context_follow_up_with_template(evidence_bundle)
        if self._is_diagnosis_confirmation_question(question):
            return self._answer_diagnosis_confirmation_with_template(evidence_bundle)
        integrated = evidence_bundle.get("integrated_reasoning_evidence") or {}
        if self._has_integrated_reasoning_content(integrated):
            integrated_answer = self._answer_general_follow_up_from_integrated_reasoning(
                evidence_bundle=evidence_bundle,
                integrated=integrated,
            )
            if integrated_answer:
                return integrated_answer
        reasoning_evidence = evidence_bundle["reasoning_evidence"]
        image_memory = evidence_bundle["image_evidence"]
        evidence_items = self._first_nonempty_items(reasoning_evidence["key_evidence"], limit=2)
        uncertainty_items = self._first_nonempty_items(reasoning_evidence["uncertainty"], limit=2)
        evidence = "；".join(evidence_items) or "目前没有可直接复述的关键影像依据"
        uncertainty = "；".join(uncertainty_items) or "仍需线下医生结合完整资料复核"
        fact_usage_text = self._format_visual_fact_usage_for_follow_up(evidence_bundle)
        image_context = f"{image_memory['modality']} {image_memory['body_part']}"
        return (
            f"关于“{question}”，这次 {image_context} 影像的关键依据是：{evidence}。"
            f"{fact_usage_text}"
            f"需要注意：{uncertainty}。"
        )

    def _answer_general_follow_up_from_integrated_reasoning(
        self,
        *,
        evidence_bundle: dict[str, Any],
        integrated: dict[str, Any],
    ) -> str:
        image = evidence_bundle.get("image_evidence", {})
        modality = str(image.get("modality") or "当前影像").upper()
        image_label = "X 光" if modality in {"XRAY", "X-RAY", "X光"} else str(image.get("modality") or "当前影像")
        next_steps = [
            str(item).strip().rstrip("。")
            for item in integrated.get("recommended_next_step") or []
            if str(item).strip()
        ]
        if next_steps:
            next_step_text = "；".join(next_steps[:2]) + "。"
        else:
            next_step_text = "建议带片给专科医生复核。"
        evidence_status = str(integrated.get("evidence_status") or "")
        missing_text = ""
        missing_targets = [
            str(target)
            for target in integrated.get("missing_required_targets") or []
            if target
        ]
        if "early_osteonecrosis" in missing_targets:
            missing_text = f"目前不能仅凭当前 {image_label}确认早期股骨头坏死。"
        elif evidence_status in {"insufficient", "requires_evidence_acquisition"}:
            missing_text = "目前证据仍不足，不能把缺失证据当成阴性。"
        if missing_text:
            return f"下一步建议：{next_step_text}{missing_text}"
        return f"下一步建议：{next_step_text}"

    def _is_identity_question(self, question: str) -> bool:
        normalized = question.strip().lower()
        return normalized in {"你是谁", "你是誰", "who are you", "你是什么", "你是什么agent"}

    def _answer_identity_follow_up(self) -> str:
        return (
            "我是 MedScope 的高医生 Agent，负责解释当前病例报告和回答追问。"
            "我只能根据已保存的影像证据和报告回答，不能替代线下医生诊断。"
        )

    def _is_prognosis_question(self, question: str) -> bool:
        return any(marker in question for marker in ["活多久", "能活", "寿命", "生存期"])

    def _is_clinical_context_question(self, question: str) -> bool:
        clinical_markers = [
            "病史",
            "风险",
            "危险因素",
            "激素",
            "饮酒",
            "酗酒",
            "外伤",
            "history",
            "risk factor",
            "steroid",
            "alcohol",
            "trauma",
        ]
        diagnosis_markers = ["确诊", "诊断", "说明", "支持", "能不能", "能否", "吗"]
        lowered = question.lower()
        return any(marker in lowered for marker in clinical_markers) and any(
            marker in lowered for marker in diagnosis_markers
        )

    def _answer_clinical_context_follow_up_with_template(
        self,
        evidence_bundle: dict[str, Any],
    ) -> str:
        clinical = evidence_bundle.get("clinical_context_evidence") or {}
        risk_modifiers = clinical.get("risk_modifiers") or {}
        limits = clinical.get("diagnostic_limits") or {}
        source = clinical.get("source") or "missing"
        factors = [
            str(item)
            for item in risk_modifiers.get("provided_risk_factors")
            or clinical.get("provided_risk_factors")
            or []
            if str(item).strip()
        ]
        factor_text = "、".join(factors) if factors else "当前没有结构化到明确风险因素"
        raw_context = str(clinical.get("raw_context") or "").strip()
        raw_text = f"原始上下文是：{raw_context}。" if raw_context else ""
        limit_role = str(
            limits.get("role")
            or clinical.get("role")
            or "clinical context can modify suspicion only; it cannot replace imaging evidence."
        )
        return (
            f"这部分临床上下文来源是 {source}。"
            f"已识别的 risk modifier 包括：{factor_text}。"
            f"{raw_text}"
            f"限制是：{limit_role} "
            "也就是说，它只能提高或降低怀疑程度，不能单独确诊。"
        )

    def _is_diagnosis_confirmation_question(self, question: str) -> bool:
        return any(marker in question for marker in ["是", "是不是", "有没有", "有吗", "吗"]) and any(
            disease in question for disease in ["股骨头坏死", "胶质瘤", "肺炎", "肺纤维化", "这个病"]
        )

    def _answer_diagnosis_confirmation_with_template(
        self,
        evidence_bundle: dict[str, Any],
    ) -> str:
        integrated = evidence_bundle.get("integrated_reasoning_evidence") or {}
        if self._has_integrated_reasoning_content(integrated):
            integrated_answer = self._answer_diagnosis_confirmation_from_integrated_reasoning(
                evidence_bundle=evidence_bundle,
                integrated=integrated,
            )
            if integrated_answer:
                return integrated_answer
        reasoning = evidence_bundle.get("reasoning_evidence", {})
        image = evidence_bundle.get("image_evidence", {})
        skill = evidence_bundle.get("skill_evidence", {})
        disease = self._display_disease_name(skill)
        key_evidence = self._first_nonempty_items(reasoning.get("key_evidence", []), limit=1)
        uncertainty = self._first_nonempty_items(reasoning.get("uncertainty", []), limit=1)
        modality = str(image.get("modality") or "当前影像").upper()
        image_label = "X 光" if modality in {"XRAY", "X-RAY", "X光"} else str(image.get("modality") or "当前影像")
        evidence_text = key_evidence[0] if key_evidence else "当前记录只有候选影像证据"
        uncertainty_text = uncertainty[0] if uncertainty else "仍需线下医生结合完整检查复核"
        return (
            f"目前不能仅凭这张 {image_label}确诊{disease}，但存在{disease}相关候选征象。"
            f"主要依据是：{evidence_text}。"
            f"需要注意：{uncertainty_text}。"
            "建议带片给骨科医生复核，并根据需要补充 MRI/CT。"
        )

    def _has_integrated_reasoning_content(self, integrated: dict[str, Any]) -> bool:
        if not isinstance(integrated, dict):
            return False
        scalar_keys = ["target_disease", "evidence_status"]
        if any(str(integrated.get(key) or "").strip() for key in scalar_keys):
            return True
        list_keys = [
            "supported_targets",
            "nonspecific_or_unusable_targets",
            "missing_required_targets",
            "measurement_targets_not_usable",
            "exploratory_targets",
            "recommended_next_step",
        ]
        return any(integrated.get(key) for key in list_keys)

    def _answer_diagnosis_confirmation_from_integrated_reasoning(
        self,
        *,
        evidence_bundle: dict[str, Any],
        integrated: dict[str, Any],
    ) -> str:
        image = evidence_bundle.get("image_evidence", {})
        skill = evidence_bundle.get("skill_evidence", {})
        disease = self._display_disease_name(skill)
        modality = str(image.get("modality") or "当前影像").upper()
        image_label = "X 光" if modality in {"XRAY", "X-RAY", "X光"} else str(image.get("modality") or "当前影像")
        can_confirm = integrated.get("can_confirm_target_disease") is True
        if can_confirm:
            conclusion = f"当前证据支持{disease}，但仍需要线下医生结合完整检查确认。"
        else:
            conclusion = f"目前不能仅凭这张 {image_label}确诊{disease}。"
        missing_targets = [
            str(target)
            for target in integrated.get("missing_required_targets") or []
            if target
        ]
        missing_text = self._diagnosis_missing_targets_patient_text(missing_targets)
        support_targets = [
            str(target)
            for target in integrated.get("supported_targets") or []
            if target
        ]
        if support_targets:
            evidence_text = "可参考的支持证据包括：" + "、".join(
                self._finding_patient_name(target) for target in support_targets
            ) + "。"
        else:
            evidence_text = missing_text or "当前没有足够的可诊断影像证据。"
        next_steps = [
            str(item).strip()
            for item in integrated.get("recommended_next_step") or []
            if str(item).strip()
        ]
        next_step = next_steps[0] if next_steps else "建议带片给骨科或影像科医生复核。"
        return f"{conclusion}{evidence_text}{next_step}"

    def _diagnosis_missing_targets_patient_text(self, missing_targets: list[str]) -> str:
        if "early_osteonecrosis" in missing_targets:
            return "早期股骨头坏死证据不足，需要 MRI 才能更可靠评估。"
        if missing_targets:
            return "仍缺少关键影像证据，不能把缺失当作阴性。"
        return ""

    def _finding_patient_name(self, target: str) -> str:
        return {
            "sclerotic_band": "硬化带",
            "cystic_change": "囊性变",
            "trabecular_blurring": "骨小梁模糊",
            "collapse": "股骨头塌陷",
            "early_osteonecrosis": "早期股骨头坏死",
        }.get(target, target)

    def _display_disease_name(self, skill: dict[str, Any]) -> str:
        value = str(skill.get("selected_skill") or skill.get("used_skill") or "")
        mapping = {
            "femoral_head_necrosis": "股骨头坏死",
            "diffuse_glioma_brats": "胶质瘤",
            "idiopathic_pulmonary_fibrosis_hrct": "肺纤维化",
            "pneumonia_chest_xray": "肺炎",
        }
        return mapping.get(value, "该疾病")

    def _answer_prognosis_follow_up_with_template(
        self,
        evidence_bundle: dict[str, Any],
    ) -> str:
        skill = evidence_bundle.get("skill_evidence", {})
        disease = str(skill.get("selected_skill") or skill.get("used_skill") or "")
        if "femoral_head_necrosis" in disease or "股骨头" in disease:
            return (
                "不能仅凭这张 X 光判断寿命。股骨头坏死通常不是直接决定生存期的疾病，"
                "主要影响疼痛、行走和髋关节功能；具体预后取决于分期、病因和治疗方案，"
                "需要骨科医生结合 MRI/CT 和体格检查评估。"
            )
        return (
            "不能仅凭当前影像证据判断能活多久。生存期或长期预后需要结合明确诊断、"
            "分期、病理/实验室结果、全身状况和治疗反应，由线下专科医生综合评估。"
        )

    def _first_nonempty_items(self, items: list[Any], limit: int) -> list[str]:
        result = []
        for item in items or []:
            text = str(item).strip()
            if text:
                result.append(text)
            if len(result) >= limit:
                break
        return result

    def _visual_fact_usage_from_evidence_bundle(
        self,
        evidence_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        reasoning_usage = (
            evidence_bundle.get("reasoning_evidence", {}).get("visual_fact_usage") or {}
        )
        if reasoning_usage:
            return reasoning_usage
        return evidence_bundle.get("visual_fact_usage", {}) or {}

    def _format_visual_fact_usage_for_follow_up(
        self,
        evidence_bundle: dict[str, Any],
    ) -> str:
        usage = self._visual_fact_usage_from_evidence_bundle(evidence_bundle)
        used = [
            fact for fact in usage.get("used") or [] if isinstance(fact, dict)
        ]
        excluded = [
            fact for fact in usage.get("excluded") or [] if isinstance(fact, dict)
        ]
        parts = []
        if used:
            parts.append(
                "已用于结论的视觉事实："
                + "、".join(self._visual_fact_label(fact) for fact in used)
                + "。"
            )
        if excluded:
            excluded_text = []
            for fact in excluded:
                label = self._visual_fact_label(fact)
                reason = str(fact.get("exclusion_reason") or "excluded").strip()
                excluded_text.append(f"{label}（{reason}，不作为独立诊断依据）")
            parts.append("未作为独立依据的视觉事实：" + "、".join(excluded_text) + "。")
        return "".join(parts)

    def _visual_fact_label(self, fact: dict[str, Any]) -> str:
        laterality = {
            "left": "左侧",
            "right": "右侧",
            "image_left": "图像左侧",
            "image_right": "图像右侧",
        }.get(str(fact.get("laterality") or ""), "")
        name = str(fact.get("display_name") or fact.get("target") or "视觉事实")
        if laterality and not name.startswith(laterality):
            name = f"{laterality}{name}"
        view = self._view_hint_display_name(str(fact.get("view_hint") or ""))
        return f"{view}：{name}" if view and not name.startswith(f"{view}：") else name

    def _view_hint_display_name(self, view_hint: str) -> str:
        return {
            "ap_pelvis": "骨盆正位/AP",
            "frog_lateral": "蛙式侧位",
            "lateral": "侧位",
        }.get(view_hint, "")

    def explain_saved_report(self, case_id: str) -> str:
        case_memory = self.memory_manager.load_case_memory(case_id)
        reasoning = case_memory["reasoning_memory"]
        evidence = "；".join(reasoning["key_evidence"])
        uncertainty = "；".join(reasoning["uncertainty"])
        return (
            f"刚才的辅助分析倾向是：{reasoning['diagnostic_result']}。"
            f"主要依据：{evidence}。不确定性：{uncertainty}。"
        )

    def _contains_any(self, message: str, keywords: list[str]) -> bool:
        return any(keyword in message for keyword in keywords)

    def _build_memory_routing_decision(
        self,
        selected_disease_key: str,
        selected_vision_mode: str | None,
        disease_key: str | None,
        vision_mode: str | None,
    ) -> dict[str, Any]:
        if disease_key or vision_mode:
            source = "explicit"
            reason = "Caller provided disease_key or vision_mode."
            confidence = 1.0
        else:
            source = "default"
            reason = "No disease-specific routing field was provided; using default skill."
            confidence = 0.2
        return {
            "selected_skill": selected_disease_key,
            "selected_vision_mode": selected_vision_mode,
            "source": source,
            "reason": reason,
            "confidence": confidence,
            "agent_scope": "gaodoctor_agent",
        }

    def _explain_report(self, report: dict[str, Any]) -> str:
        if self.prompt_runner:
            try:
                return self.prompt_runner.run(
                    task="patient_report_explanation",
                    system_prompt=(
                        "你是高医生 Agent，负责把结构化医学辅助分析报告解释给患者。"
                        "必须说明这不是最终诊断，不新增报告中没有的影像发现。"
                    ),
                    user_payload=report,
                )
            except Exception:
                pass
        evidence = "；".join(report["影像依据"])
        next_steps = "；".join(report["建议进一步检查"])
        return (
            f"{report['diagnostic_tendency']}。影像上看到：{evidence}。"
            f"{report['分期判断']}。下一步：{next_steps}。"
        )
