from __future__ import annotations

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
        )
        report = self.diagnosis_agent.generate_report(
            case_id=case_id,
            patient_info=case_input.patient_info,
            visual_result=visual_result,
            disease_skill=disease_skill,
            hypothesis_validation_mode=hypothesis_validation_mode,
            alignment_plan=alignment_plan,
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
        visual_evidence_bundle = self._build_visual_evidence_bundle(visual_result)
        image_memory = {
            "case_id": case_id,
            "image_id": "image_001",
            "image_path": case_input.image_path,
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
    ) -> dict[str, Any]:
        if disease_key == "femoral_head_necrosis" and vision_mode == "no_mask_skill":
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

    def _run_no_mask_skill_visual_pipeline(
        self,
        *,
        case_id: str,
        image_path: str,
        patient_message: str,
        disease_key: str,
        disease_skill: dict[str, Any],
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

    def _build_visual_evidence_bundle(self, visual_result: dict[str, Any]) -> dict[str, Any]:
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
        return {
            "schema_version": "visual_evidence_bundle.v1",
            "disease_target": evidence.get("disease_target"),
            "image_context": {
                "image_path": visual_result.get("image_path"),
                "modality": visual_result.get("modality"),
                "body_part": visual_result.get("body_part"),
            },
            "image_outputs": dict(visual_result.get("image_outputs") or {}),
            "present_findings": present_findings,
            "findings": findings,
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
                "如果 reasoning_evidence.visual_fact_usage 或 visual_fact_usage 中有 excluded facts，"
                "不得把 excluded fact 说成独立诊断依据；必须说明其 exclusion_reason。"
                "如果 evidence_bundle 中字段为 missing 或 unassessed，必须明确说明证据缺失，"
                "不得把缺失解释为阴性、正常、没有发现或数值为 0。"
                "回答应面向患者，语言简洁，并保留必要的不确定性和线下就医提示。"
            ),
            user_payload={
                "question": question,
                "evidence_bundle": evidence_bundle,
                "required_safety_rules": [
                    "Only answer from evidence_bundle.",
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
        return answer

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
                if not any(negation in prefix for negation in negation_markers):
                    return True
                search_from = index + len(marker)
        return False

    def _answer_follow_up_with_template(
        self,
        question: str,
        evidence_bundle: dict[str, Any],
    ) -> str:
        reasoning_evidence = evidence_bundle["reasoning_evidence"]
        image_memory = evidence_bundle["image_evidence"]
        evidence = "；".join(reasoning_evidence["key_evidence"])
        uncertainty = "；".join(reasoning_evidence["uncertainty"])
        fact_usage_text = self._format_visual_fact_usage_for_follow_up(evidence_bundle)
        image_context = f"{image_memory['modality']} {image_memory['body_part']}"
        return (
            f"关于“{question}”，我刚才主要依据的是 {image_context} 影像记录：{evidence}。"
            f"{fact_usage_text}"
            f"需要注意：{uncertainty}。"
        )

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
        return f"{laterality}{name}" if laterality and not name.startswith(laterality) else name

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
