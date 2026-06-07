from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from agents.report_agent import ReportAgent
from contracts.medical_contracts import AlignmentPlan, DiagnosisVisualInput, SkillDescriptor, VisualAnalysisResult
from llm.prompt_runner import PromptRunner
from tools.skill_builder_tool import SkillBuilderTool


REQUIRED_REPORT_FIELDS = [
    "诊断倾向",
    "影像依据",
    "分期判断",
    "不确定性说明",
    "建议进一步检查",
    "治疗建议",
]


class DiagnosisDoctorAgent:
    """Combines disease skills, visual evidence, and symptoms into reports."""

    def __init__(
        self,
        skill_tool: SkillBuilderTool | None = None,
        report_agent: ReportAgent | None = None,
        prompt_runner: PromptRunner | None = None,
        hypothesis_validation_mode: bool = False,
    ) -> None:
        self.skill_tool = skill_tool or SkillBuilderTool()
        self.report_agent = report_agent or ReportAgent()
        self.prompt_runner = prompt_runner
        self.hypothesis_validation_mode = hypothesis_validation_mode

    def load_disease_skill(self, disease_key: str = "femoral_head_necrosis") -> dict[str, Any]:
        return self.skill_tool.load_guideline_skill(disease_key)

    def prepare_skill(
        self,
        disease_key: str,
        disease_name: str,
        observations: list[str],
    ) -> dict[str, Any]:
        return self.skill_tool.prepare_skill(
            disease_key=disease_key,
            disease_name=disease_name,
            observations=observations,
        )

    def generate_report(
        self,
        case_id: str,
        patient_info: dict[str, Any],
        visual_result: dict[str, Any],
        disease_skill: dict[str, Any] | None = None,
        hypothesis_validation_mode: bool | None = None,
        alignment_plan: dict[str, Any] | None = None,
        routing_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        skill = disease_skill or self.load_disease_skill()
        checked_visual_result = VisualAnalysisResult.from_dict(visual_result).to_dict()
        self._apply_segmentation_usability_gate(checked_visual_result)
        visual_input_contract = DiagnosisVisualInput.from_visual_result(
            checked_visual_result
        ).to_dict()
        evidence = checked_visual_result["visual_evidence"]
        skill_descriptor = SkillDescriptor.from_skill(skill).to_dict()
        checked_alignment_plan = self._checked_alignment_plan(alignment_plan)

        effective_hypothesis_mode = (
            self.hypothesis_validation_mode
            if hypothesis_validation_mode is None
            else hypothesis_validation_mode
        )
        if self._alignment_blocks_diagnosis(checked_alignment_plan):
            report = self._generate_alignment_constrained_report(
                case_id=case_id,
                visual_result=checked_visual_result,
                skill_descriptor=skill_descriptor,
                alignment_plan=checked_alignment_plan,
            )
            self._attach_visual_fact_usage(report, evidence)
            self._attach_guideline_evidence(report, skill_descriptor)
            self._attach_clinical_context_bundle(report, patient_info, skill_descriptor)
            self._attach_clinical_hypotheses_assessment(report, routing_decision)
            report["visual_input_contract"] = visual_input_contract
            return report

        if skill_descriptor.get("skill_type") == "data_mined_hypothesis":
            if not effective_hypothesis_mode:
                raise ValueError(
                    "hypothesis_validation_mode is disabled; "
                    "data_mined_hypothesis skills cannot run in clinical diagnosis mode"
                )
            report = self._generate_hypothesis_validation_report(
                case_id=case_id,
                evidence=evidence,
                skill=skill,
                skill_descriptor=skill_descriptor,
            )
            self._attach_visual_fact_usage(report, evidence)
            self._attach_clinical_context_bundle(report, patient_info, skill_descriptor)
            self._attach_clinical_hypotheses_assessment(report, routing_decision)
            report["visual_input_contract"] = visual_input_contract
            return report

        if self.prompt_runner:
            llm_report, fallback_reason = self._try_generate_llm_report(
                case_id=case_id,
                patient_info=patient_info,
                visual_result=checked_visual_result,
                disease_skill=skill,
                skill_descriptor=skill_descriptor,
                alignment_plan=checked_alignment_plan,
            )
            if llm_report:
                self._apply_alignment_constraints(llm_report, checked_alignment_plan)
                self._attach_visual_fact_usage(llm_report, evidence)
                self._attach_guideline_evidence(llm_report, skill_descriptor)
                self._attach_clinical_context_bundle(llm_report, patient_info, skill_descriptor)
                self._attach_clinical_hypotheses_assessment(llm_report, routing_decision)
                llm_report["visual_input_contract"] = visual_input_contract
                return llm_report
        else:
            fallback_reason = None

        report = self._generate_rule_based_report(
            case_id=case_id,
            patient_info=patient_info,
            evidence=evidence,
            skill_descriptor=skill_descriptor,
        )
        if fallback_reason:
            report["llm_fallback_reason"] = fallback_reason
        self._apply_alignment_constraints(report, checked_alignment_plan)
        self._attach_visual_fact_usage(report, evidence)
        self._attach_guideline_evidence(report, skill_descriptor)
        self._attach_clinical_context_bundle(report, patient_info, skill_descriptor)
        self._attach_clinical_hypotheses_assessment(report, routing_decision)
        report["visual_input_contract"] = visual_input_contract
        return report

    def _attach_clinical_context_bundle(
        self,
        report: dict[str, Any],
        patient_info: dict[str, Any],
        skill_descriptor: dict[str, Any],
    ) -> None:
        bundle = self._build_clinical_context_bundle(patient_info, skill_descriptor)
        report["clinical_context_bundle"] = bundle
        assessment = report.get("clinical_context_assessment")
        if isinstance(assessment, dict):
            assessment["clinical_context_bundle"] = bundle

    def _attach_guideline_evidence(
        self,
        report: dict[str, Any],
        skill_descriptor: dict[str, Any],
    ) -> None:
        if skill_descriptor.get("skill_type") != "guideline_based":
            return
        evidence = self._build_guideline_evidence(skill_descriptor)
        if not evidence["citations"] and not evidence["source_documents"]:
            return
        report["guideline_evidence"] = evidence
        report["指南依据"] = evidence["citations"] or evidence["source_documents"]

    def _build_guideline_evidence(self, skill_descriptor: dict[str, Any]) -> dict[str, Any]:
        extraction = skill_descriptor.get("guideline_extraction") or {}
        source = skill_descriptor.get("guideline_source") or {}
        citations = self._dedupe_citations(list(extraction.get("citations") or []))
        source_documents = [
            dict(document)
            for document in skill_descriptor.get("source_documents") or []
            if isinstance(document, dict)
        ]
        source_priority = [
            dict(source_entry)
            for source_entry in skill_descriptor.get("source_priority") or []
            if isinstance(source_entry, dict)
        ]
        conflicts = [
            dict(conflict)
            for conflict in skill_descriptor.get("guideline_conflicts") or []
            if isinstance(conflict, dict)
        ]
        return {
            "citations": citations,
            "source_documents": source_documents,
            "source_priority": source_priority,
            "conflicts": conflicts,
            "source_catalog_path": source.get("source_catalog_path"),
            "quality_control": dict(skill_descriptor.get("quality_control") or {}),
        }

    def _attach_visual_fact_usage(
        self,
        report: dict[str, Any],
        evidence: dict[str, Any],
    ) -> None:
        usage = self._visual_fact_usage(evidence)
        report["visual_fact_usage"] = usage
        report["used_visual_facts"] = usage["used"]
        report["excluded_visual_facts"] = usage["excluded"]

    def _attach_clinical_hypotheses_assessment(
        self,
        report: dict[str, Any],
        routing_decision: dict[str, Any] | None,
    ) -> None:
        if not isinstance(routing_decision, dict):
            return
        hypotheses = [
            dict(item)
            for item in routing_decision.get("clinical_hypotheses") or []
            if isinstance(item, dict)
        ]
        if not hypotheses and routing_decision.get("primary_hypothesis"):
            hypotheses = [
                {
                    "disease_key": routing_decision.get("primary_hypothesis"),
                    "role": "primary",
                    "status": routing_decision.get("routing_evidence_status")
                    or routing_decision.get("initial_evidence_status")
                    or "requires_evidence_acquisition",
                    "reason": routing_decision.get("skill_search_reason")
                    or routing_decision.get("reason")
                    or "Primary hypothesis selected by orchestrator.",
                }
            ]
        if not hypotheses:
            return
        primary = next(
            (item for item in hypotheses if item.get("role") == "primary"),
            hypotheses[0],
        )
        differentials = [
            item for item in hypotheses if item.get("role") == "differential"
        ]
        report["clinical_hypotheses_assessment"] = {
            "primary_hypothesis": primary,
            "differential_retained": differentials,
            "hypotheses_are_diagnosis": False,
            "role": (
                "Clinical hypotheses guide skill routing and evidence acquisition; "
                "they are not diagnostic evidence by themselves."
            ),
        }
        target_assessment = report.get("target_disease_assessment")
        if isinstance(target_assessment, dict):
            target_assessment.setdefault("routing_role", "primary_hypothesis")
            target_assessment.setdefault(
                "routing_boundary",
                "Primary hypothesis must be supported by evidence_bundle before diagnosis.",
            )

    def _visual_fact_usage(self, evidence: dict[str, Any]) -> dict[str, Any]:
        facts = [
            dict(fact)
            for fact in evidence.get("structured_visual_facts") or []
            if isinstance(fact, dict)
        ]
        if not facts and evidence.get("findings"):
            from tools.structured_visual_fact_builder import build_structured_visual_facts

            facts = build_structured_visual_facts(
                [
                    dict(finding)
                    for finding in evidence.get("findings") or []
                    if isinstance(finding, dict)
                ]
            )
        used: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        for fact in facts:
            reason = self._visual_fact_exclusion_reason(fact)
            if reason:
                excluded_fact = dict(fact)
                excluded_fact["exclusion_reason"] = reason
                excluded.append(excluded_fact)
            else:
                used.append(dict(fact))
        return {
            "used": used,
            "excluded": excluded,
            "used_count": len(used),
            "excluded_count": len(excluded),
        }

    def _visual_fact_exclusion_reason(self, fact: dict[str, Any]) -> str | None:
        if not str(fact.get("target") or "").strip():
            return "missing_target"
        if fact.get("diagnosis_usable", True) is not True:
            return "not_diagnosis_usable"
        if fact.get("independent_evidence", True) is not True:
            return "non_independent_evidence"
        if fact.get("status") not in {"candidate_present", "supported", "detected"}:
            return "not_candidate_present"
        return None

    def _dedupe_citations(self, citations: list[Any]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            normalized = dict(citation)
            key = (
                str(normalized.get("source_id") or ""),
                str(normalized.get("title") or ""),
                str(normalized.get("url") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped

    def _generate_hypothesis_validation_report(
        self,
        case_id: str,
        evidence: dict[str, Any],
        skill: dict[str, Any],
        skill_descriptor: dict[str, Any],
    ) -> dict[str, Any]:
        rules = list(skill.get("candidate_observation_rules", []))
        visual_findings = list(evidence.get("suspected_visual_findings", []))
        if rules:
            visual_findings.extend(f"候选假设特征：{rule}" for rule in rules)
        warning = skill.get(
            "warning",
            "该规则来自数据总结，不等同于正式医学指南，只能作为辅助提示",
        )
        visual_payload = dict(evidence)
        visual_payload["suspected_visual_findings"] = visual_findings
        report = self.report_agent.build_report(
            case_id=case_id,
            diagnostic_tendency=f"科研假设风险提示：{skill['disease_name']} 需要进一步验证",
            staging="该输出不是临床分期；仅用于 hypothesis validation 模式下的科研预警。",
            visual_evidence=visual_payload,
            uncertainty=[
                warning,
                "该 data-mined hypothesis 尚未形成正式临床指南，不能作为确定诊断依据。",
                "当前输出只表示低证据风险信号，需要金标准检查确认。",
            ],
            follow_up=[
                "建议进一步金标准检查，例如 MRI/增强序列或专科医生复核。",
                "建议在独立验证集上复核该候选影像特征的稳定性。",
            ],
            treatment_advice=[
                "不得基于该假设结果直接制定治疗方案。",
                "如症状持续或进展，应按常规临床路径线下就医。",
            ],
        )
        report["used_skill"] = skill_descriptor
        report["hypothesis_validation_mode"] = "enabled"
        report["safety_gate"] = dict(skill.get("safety_gate", {}))
        return report

    def _generate_rule_based_report(
        self,
        case_id: str,
        patient_info: dict[str, Any],
        evidence: dict[str, Any],
        skill_descriptor: dict[str, Any],
    ) -> dict[str, Any]:
        if skill_descriptor.get("skill_id") == "diffuse_glioma_brats_v0.1":
            return self._generate_glioma_rule_based_report(
                case_id=case_id,
                evidence=evidence,
                skill_descriptor=skill_descriptor,
            )

        symptoms = patient_info.get("symptoms", [])
        visual_findings = list(evidence.get("suspected_visual_findings", []))
        usable_findings = self._usable_visual_findings(evidence)
        non_independent_notes = self._non_independent_finding_notes(evidence)
        bounded_assessment = self._build_bounded_fhn_assessment(
            patient_info=patient_info,
            evidence=evidence,
            skill_descriptor=skill_descriptor,
        )
        fhn_xray_support = [
            finding
            for finding in usable_findings
            if finding["target"] in {"sclerotic_band", "cystic_change", "trabecular_blurring"}
        ]
        collapse_candidates = [
            finding for finding in usable_findings if finding["target"] == "collapse"
        ]
        fhn_support_names = list(
            dict.fromkeys(finding["display_name"] for finding in fhn_xray_support)
        )
        fhn_support_text = "、".join(fhn_support_names)
        if fhn_support_names:
            visual_findings.append(
                "X 光候选征象：" + fhn_support_text
            )
        if collapse_candidates:
            visual_findings.append(
                "塌陷候选征象：" + "、".join(
                    finding["display_name"] for finding in collapse_candidates
                ) + "，需要影像科或 MRI 复核，不能解释为阴性。"
            )
        visual_findings.extend(non_independent_notes)

        early_pattern = (
            not evidence.get("collapse", True)
            and not evidence.get("joint_space_narrowing", True)
            and evidence.get("texture_abnormality_score", 0) >= 0.7
            and "髋关节疼痛" in symptoms
            and bounded_assessment["target_disease_assessment"]["evidence_status"] != "insufficient"
        )
        if fhn_xray_support and collapse_candidates:
            tendency = "疑似股骨头坏死影像表现，需 MRI 和影像科复核"
            staging = (
                f"X 光存在{fhn_support_text}等独立候选征象，同时存在塌陷候选征象；"
                "不能按塌陷阴性处理，需复核 ARCO II 与 ARCO III 边界。"
            )
        elif fhn_xray_support and not evidence.get("collapse", False):
            tendency = "疑似股骨头坏死影像表现，需 MRI 和影像科复核"
            staging = (
                f"X 光存在{fhn_support_text}等独立候选征象且未见塌陷，"
                "倾向 ARCO II 可能；不能排除更早期或更复杂病变。"
            )
        elif early_pattern:
            tendency = "疑似早期股骨头坏死"
            staging = "倾向 ARCO I-II：X 光未见塌陷，存在纹理异常；需 MRI 确认"
        else:
            tendency = "影像证据不足，需进一步评估"
            staging = "暂无法可靠分期"
        if bounded_assessment["target_disease_assessment"]["evidence_status"] == "insufficient":
            tendency = "影像证据不足，需进一步评估"
            staging = "现有证据不能可靠判断早期股骨头坏死；X 光路径需 MRI 补充。"

        report_evidence = dict(evidence)
        report_evidence["suspected_visual_findings"] = visual_findings
        report = self.report_agent.build_report(
            case_id=case_id,
            diagnostic_tendency=tendency,
            staging=staging,
            visual_evidence=report_evidence,
            uncertainty=[
                "单纯 X 光对早期股骨头坏死敏感性有限",
                "当前输出使用候选视觉证据，不能替代真实医学诊断",
            ]
            + self._visual_protocol_uncertainty(evidence)
            + non_independent_notes,
            follow_up=[
                "建议完善双髋 MRI T1/T2 检查",
                "建议由骨科或影像科医生结合临床体征复核",
            ],
            treatment_advice=[
                "避免负重和剧烈活动，等待进一步检查结论",
                "如疼痛明显或活动受限加重，应尽快线下就医",
            ],
        )
        report["used_skill"] = skill_descriptor
        report.update(bounded_assessment)
        return report

    def _build_bounded_fhn_assessment(
        self,
        *,
        patient_info: dict[str, Any],
        evidence: dict[str, Any],
        skill_descriptor: dict[str, Any],
    ) -> dict[str, Any]:
        evidence_items = [
            dict(item)
            for item in evidence.get("evidence_items") or []
            if isinstance(item, dict)
        ]
        if not evidence_items:
            evidence_items = self._evidence_items_from_legacy_evidence(evidence)
        missing = self._missing_evidence_items(evidence)
        usable_support = [
            item for item in evidence_items
            if self._is_fhn_diagnosis_support_item(item)
        ]
        nonspecific = [
            item for item in evidence_items
            if not self._is_fhn_diagnosis_support_item(item)
        ]
        evidence_status = (
            "supported"
            if usable_support
            else "insufficient"
            if missing or nonspecific
            else "legacy_observation"
        )
        risk_factors = self._clinical_risk_factors(patient_info, skill_descriptor)
        differential = self._bounded_differential_considerations(
            skill_descriptor=skill_descriptor,
            nonspecific=nonspecific,
            missing=missing,
        )
        modality_limitations = self._fhn_modality_limitations(evidence, missing)
        recommendations = self._fhn_bounded_recommendations(missing, modality_limitations)
        target_assessment = {
            "target_disease": "femoral_head_necrosis",
            "evidence_status": evidence_status,
            "supports_target_disease": [
                item.get("target") for item in usable_support if item.get("target")
            ],
            "nonspecific_or_unusable_findings": [
                item.get("target") for item in nonspecific if item.get("target")
            ],
            "missing_required_evidence": [
                item.get("target") for item in missing if item.get("target")
            ],
        }
        imaging_summary = {
            "usable_items": usable_support,
            "nonspecific_items": nonspecific,
            "missing_items": missing,
        }
        quantitative_summary = self._quantitative_evidence_summary(evidence_items)
        clinical_context = {
            "provided_risk_factors": risk_factors,
            "missing_clinical_context": self._missing_clinical_context(patient_info, skill_descriptor),
            "can_confirm_without_imaging": False,
            "role": "clinical risk changes suspicion level only; it cannot confirm ONFH without imaging evidence.",
            "structured_context": self._structured_clinical_context(patient_info),
            "suspicion_effect": self._clinical_suspicion_effect(risk_factors),
        }
        clinical_context_bundle = self._build_clinical_context_bundle(
            patient_info,
            skill_descriptor,
        )
        missing_evidence = [
            item.get("visual_observation", {}).get("reason") or item.get("target")
            for item in missing
        ]
        return {
            "target_disease_assessment": target_assessment,
            "imaging_evidence_summary": imaging_summary,
            "quantitative_evidence_summary": quantitative_summary,
            "differential_considerations": differential,
            "clinical_context_assessment": clinical_context,
            "clinical_context_bundle": clinical_context_bundle,
            "missing_evidence": missing_evidence,
            "modality_limitations": modality_limitations,
            "recommendation": recommendations,
            "integrated_reasoning_summary": self._integrated_fhn_reasoning_summary(
                target_assessment=target_assessment,
                imaging_summary=imaging_summary,
                quantitative_summary=quantitative_summary,
                differential_considerations=differential,
                clinical_context=clinical_context,
                clinical_context_bundle=clinical_context_bundle,
                modality_limitations=modality_limitations,
                recommendations=recommendations,
            ),
        }

    def _is_fhn_diagnosis_support_item(self, item: dict[str, Any]) -> bool:
        if item.get("diagnosis_usable") is not True:
            return False
        level = str(item.get("diagnosis_usable_level") or "")
        if level == "measurement_support":
            measurements = item.get("measurements") or {}
            return measurements.get("measurement_usable") is True
        if level != "candidate_support":
            return False

        evidence_type = str(item.get("evidence_type") or "")
        execution_mode = str(item.get("execution_mode") or "")
        if evidence_type != "candidate_mask" and execution_mode != "vlm_plus_segmenter":
            return True
        return self._candidate_mask_qc_passed(item)

    def _candidate_mask_qc_passed(self, item: dict[str, Any]) -> bool:
        quality = item.get("quality") or {}
        segmentation = item.get("segmentation") or {}
        accepted_statuses = {"passed", "accepted", "usable", "diagnosis_usable", "high"}
        rejected_statuses = {
            "candidate_only",
            "failed",
            "low_quality",
            "missing",
            "not_run",
            "requires_validation",
            "unassessed",
        }
        observed_statuses = [
            str(quality.get("qc_status") or ""),
            str(quality.get("status") or ""),
            str(quality.get("validation_status") or ""),
            str(segmentation.get("qc_status") or ""),
            str(segmentation.get("status") or ""),
            str(segmentation.get("quality") or ""),
        ]
        if any(status in rejected_statuses for status in observed_statuses):
            return False
        if segmentation.get("diagnosis_usable") is True:
            return True
        return any(status in accepted_statuses for status in observed_statuses)

    def _evidence_items_from_legacy_evidence(self, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for finding in evidence.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            level = str(finding.get("diagnosis_usable_level") or "")
            if not level:
                level = "candidate_support" if finding.get("diagnosis_usable", True) else "not_usable"
            items.append(
                {
                    "target": finding.get("target"),
                    "evidence_type": finding.get("evidence_type", "visual_observation"),
                    "execution_mode": finding.get("execution_mode", "vlm_only"),
                    "quality": dict(finding.get("quality") or {}),
                    "diagnosis_usable": bool(finding.get("diagnosis_usable", False)),
                    "diagnosis_usable_level": level,
                    "measurements": dict(finding.get("measurements") or {}),
                    "limitations": list(finding.get("limitations") or []),
                }
            )
        return items

    def _missing_evidence_items(self, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        missing: list[dict[str, Any]] = []
        for target, status in (evidence.get("completeness") or {}).items():
            if not isinstance(status, dict):
                continue
            if status.get("status") not in {"missing", "unassessed"}:
                continue
            missing.append(
                {
                    "target": str(target),
                    "evidence_type": "visual_observation",
                    "execution_mode": "insufficient_input",
                    "visual_observation": {
                        "status": status.get("status"),
                        "reason": status.get("reason", "not assessed"),
                    },
                    "quality": {"status": status.get("status")},
                    "diagnosis_usable": False,
                    "diagnosis_usable_level": "not_usable",
                    "limitations": [status.get("reason", "not assessed")],
                }
            )
        return missing

    def _quantitative_evidence_summary(self, evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
        exploratory = []
        measurements = []
        for item in evidence_items:
            if item.get("evidence_type") == "image_feature_quantification" or item.get("diagnosis_usable_level") == "exploratory_only":
                exploratory.append(item)
            if item.get("evidence_type") == "anatomical_measurement":
                measurements.append(item)
        return {
            "exploratory_features": exploratory,
            "measurement_items": measurements,
            "strong_quantitative_support_count": sum(
                1
                for item in measurements
                if item.get("diagnosis_usable") is True
                and (item.get("measurements") or {}).get("measurement_usable") is True
            ),
        }

    def _integrated_fhn_reasoning_summary(
        self,
        *,
        target_assessment: dict[str, Any],
        imaging_summary: dict[str, Any],
        quantitative_summary: dict[str, Any],
        differential_considerations: list[dict[str, Any]],
        clinical_context: dict[str, Any],
        clinical_context_bundle: dict[str, Any],
        modality_limitations: list[str],
        recommendations: list[str],
    ) -> dict[str, Any]:
        measurement_items = [
            item
            for item in quantitative_summary.get("measurement_items") or []
            if isinstance(item, dict)
        ]
        exploratory_features = [
            item
            for item in quantitative_summary.get("exploratory_features") or []
            if isinstance(item, dict)
        ]
        measurement_not_usable = [
            str(item.get("target"))
            for item in measurement_items
            if item.get("target")
            and (
                item.get("diagnosis_usable") is not True
                or (item.get("measurements") or {}).get("measurement_usable") is not True
            )
        ]
        return {
            "target_disease": target_assessment.get("target_disease"),
            "evidence_status": target_assessment.get("evidence_status"),
            "can_confirm_target_disease": (
                target_assessment.get("evidence_status") == "supported"
                and bool(target_assessment.get("supports_target_disease"))
            ),
            "imaging_support": {
                "supported_targets": list(target_assessment.get("supports_target_disease") or []),
                "nonspecific_or_unusable_targets": list(
                    target_assessment.get("nonspecific_or_unusable_findings") or []
                ),
                "missing_targets": list(
                    target_assessment.get("missing_required_evidence") or []
                ),
                "usable_item_count": len(imaging_summary.get("usable_items") or []),
            },
            "quantitative_support": {
                "strong_quantitative_support_count": quantitative_summary.get(
                    "strong_quantitative_support_count",
                    0,
                ),
                "measurement_targets_not_usable": measurement_not_usable,
                "exploratory_targets": [
                    str(item.get("target"))
                    for item in exploratory_features
                    if item.get("target")
                ],
                "role": (
                    "Measurement evidence requires usable ROI/contour/landmark quality; "
                    "exploratory image features require validation and cannot confirm ONFH."
                ),
            },
            "differential_considerations": {
                "retained": list(differential_considerations),
                "role": "Bounded differential considerations only; DiagnosisAgent does not select a new disease here.",
            },
            "clinical_risk_support": {
                "provided_risk_factors": list(clinical_context.get("provided_risk_factors") or []),
                "missing_clinical_context": list(
                    clinical_context.get("missing_clinical_context") or []
                ),
                "can_confirm_without_imaging": False,
                "clinical_context_source": clinical_context_bundle.get("source"),
                "clinical_context_bundle": clinical_context_bundle,
            },
            "missing_evidence": {
                "missing_required_targets": list(
                    target_assessment.get("missing_required_evidence") or []
                ),
            },
            "modality_limitation": list(modality_limitations),
            "recommended_next_step": list(recommendations),
        }

    def _build_clinical_context_bundle(
        self,
        patient_info: dict[str, Any],
        skill_descriptor: dict[str, Any],
    ) -> dict[str, Any]:
        raw_values: list[str] = []
        source_fields: list[str] = []
        for key in ("clinical_context", "history", "risk_factors", "symptoms"):
            value = patient_info.get(key)
            if value is None or value == "":
                continue
            source_fields.append(key)
            if isinstance(value, list):
                raw_values.extend(str(item) for item in value if str(item).strip())
            else:
                raw_values.append(str(value))
        structured = self._structured_clinical_context(patient_info)
        if structured:
            source_fields.append("structured_clinical_context")
            source_text = str(structured.get("source_text") or "").strip()
            if source_text and source_text not in raw_values:
                raw_values.append(source_text)
        raw_context = "；".join(raw_values)
        if patient_info.get("clinical_context_source"):
            source = patient_info["clinical_context_source"]
        elif structured:
            source = structured.get("source")
        elif raw_context:
            source = "structured_patient_info"
        else:
            source = "missing"
        provided = self._clinical_risk_factors(patient_info, skill_descriptor)
        missing = self._missing_clinical_context(patient_info, skill_descriptor)
        source_trace = {
            "source_fields": source_fields,
            "structured_context_source": structured.get("source") if structured else "missing",
        }
        if structured.get("source_text"):
            source_trace["source_text"] = structured.get("source_text")
        return {
            "schema_version": "clinical_context_bundle.v1",
            "source": source,
            "source_fields": source_fields,
            "raw_context": raw_context,
            "structured_context": structured,
            "source_trace": source_trace,
            "risk_modifiers": {
                "provided_risk_factors": provided,
                "missing_clinical_context": missing,
                "suspicion_modifier_only": True,
            },
            "suspicion_effect": self._clinical_suspicion_effect(provided),
            "diagnostic_limits": {
                "can_confirm_without_imaging": False,
                "diagnosis_usable": False,
                "diagnosis_usable_level": "risk_modifier_only",
                "role": (
                    "clinical context changes suspicion level only; it cannot "
                    "replace imaging evidence or confirm diagnosis."
                ),
            },
        }

    def _clinical_risk_factors(
        self,
        patient_info: dict[str, Any],
        skill_descriptor: dict[str, Any],
    ) -> list[str]:
        provided = []
        structured = self._structured_clinical_context(patient_info)
        structured_provided = [
            str(item)
            for item in structured.get("provided_risk_factors") or []
            if str(item).strip()
        ]
        structured_absent = set(self._absent_structured_risk_factors(patient_info))
        raw_values = []
        for key in ("risk_factors", "history", "clinical_context"):
            value = patient_info.get(key)
            if isinstance(value, list):
                raw_values.extend(str(item) for item in value)
            elif value:
                raw_values.append(str(value))
        text = " ".join(raw_values).lower()
        aliases = {
            "corticosteroid_use": ["激素", "corticosteroid", "steroid"],
            "alcohol_use": ["饮酒", "alcohol"],
            "trauma_history": ["外伤", "trauma"],
            "hematologic_disease": ["血液", "sickle", "镰状"],
            "autoimmune_disease": ["自身免疫", "autoimmune"],
        }
        protocol = skill_descriptor.get("clinical_context_protocol") or {}
        for factor in protocol.get("risk_factors") or []:
            factor = str(factor)
            if factor in structured_absent:
                continue
            if factor in structured_provided:
                provided.append(factor)
                continue
            if any(alias in text for alias in aliases.get(factor, [factor])):
                provided.append(str(factor))
        return provided

    def _missing_clinical_context(
        self,
        patient_info: dict[str, Any],
        skill_descriptor: dict[str, Any],
    ) -> list[str]:
        protocol = skill_descriptor.get("clinical_context_protocol") or {}
        provided = set(self._clinical_risk_factors(patient_info, skill_descriptor))
        known_absent = set(self._absent_structured_risk_factors(patient_info))
        return [
            str(factor)
            for factor in protocol.get("risk_factors") or []
            if str(factor) not in provided and str(factor) not in known_absent
        ]

    def _structured_clinical_context(self, patient_info: dict[str, Any]) -> dict[str, Any]:
        structured = patient_info.get("structured_clinical_context")
        return dict(structured) if isinstance(structured, dict) else {}

    def _absent_structured_risk_factors(self, patient_info: dict[str, Any]) -> list[str]:
        structured = self._structured_clinical_context(patient_info)
        fields = structured.get("fields") or {}
        absent: list[str] = []
        for field in fields.values():
            if not isinstance(field, dict):
                continue
            if field.get("status") == "absent" and field.get("risk_factor"):
                absent.append(str(field["risk_factor"]))
        return absent

    def _clinical_suspicion_effect(self, provided_risk_factors: list[str]) -> dict[str, Any]:
        return {
            "direction": "increases_suspicion" if provided_risk_factors else "neutral_or_unknown",
            "basis": list(provided_risk_factors),
            "role": "suspicion_modifier_only",
            "can_confirm_diagnosis": False,
        }

    def _bounded_differential_considerations(
        self,
        *,
        skill_descriptor: dict[str, Any],
        nonspecific: list[dict[str, Any]],
        missing: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        protocol = skill_descriptor.get("differential_diagnosis_protocol") or {}
        considerations = []
        for candidate in protocol.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            considerations.append(
                {
                    "condition": candidate.get("condition"),
                    "display_name": candidate.get("display_name"),
                    "status": "cannot_exclude" if missing else "nonspecific_finding",
                    "reason": (
                        "当前存在缺失证据或非特异观察，不能开放式改诊断；仅提示需结合指南和临床复核。"
                        if nonspecific or missing
                        else "当前 evidence_bundle 未提供支持该替代解释的独立证据。"
                    ),
                }
            )
        return considerations

    def _fhn_modality_limitations(
        self,
        evidence: dict[str, Any],
        missing: list[dict[str, Any]],
    ) -> list[str]:
        limitations = [
            "单纯 X 光对早期股骨头坏死敏感性有限。",
            "X-ray only 不能可靠判断或排除 early osteonecrosis。",
        ]
        for item in missing:
            reason = item.get("visual_observation", {}).get("reason")
            if reason and reason not in limitations:
                limitations.append(str(reason))
        return limitations

    def _fhn_bounded_recommendations(
        self,
        missing: list[dict[str, Any]],
        modality_limitations: list[str],
    ) -> list[str]:
        recommendations = [
            "建议完善双髋 MRI T1/T2/STIR 检查。",
            "建议由骨科或影像科医生结合临床体征复核。",
        ]
        if not missing and not modality_limitations:
            recommendations.append("如影像证据仍不一致，建议补充标准体位片或专科复核。")
        return recommendations

    def _usable_visual_findings(self, evidence: dict[str, Any]) -> list[dict[str, str]]:
        structured_facts = [
            fact
            for fact in evidence.get("structured_visual_facts") or []
            if isinstance(fact, dict)
        ]
        if structured_facts:
            return self._usable_visual_findings_from_facts(structured_facts)

        findings: list[dict[str, str]] = []
        for finding in evidence.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            if not finding.get("diagnosis_usable", True):
                continue
            if finding.get("independent_evidence", True) is False:
                continue
            if finding.get("status") not in {"candidate_present", "supported", "detected"}:
                continue
            target = str(finding.get("target") or "").strip()
            if not target:
                continue
            findings.append(
                {
                    "target": target,
                    "display_name": self._localized_finding_display_name(finding),
                    "measurements": dict(finding.get("measurements") or {}),
                }
            )
        return findings

    def _usable_visual_findings_from_facts(
        self,
        facts: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        findings: list[dict[str, str]] = []
        for fact in facts:
            if not fact.get("diagnosis_usable", True):
                continue
            if fact.get("independent_evidence", True) is False:
                continue
            if fact.get("status") not in {"candidate_present", "supported", "detected"}:
                continue
            target = str(fact.get("target") or "").strip()
            if not target:
                continue
            findings.append(
                {
                    "target": target,
                    "display_name": self._localized_fact_display_name(fact),
                    "measurements": dict(fact),
                }
            )
        return findings

    def _localized_fact_display_name(self, fact: dict[str, Any]) -> str:
        target = str(fact.get("target") or "")
        base_name = self._finding_display_name(str(fact.get("display_name") or target))
        laterality = str(fact.get("laterality") or "").strip()
        prefix = self._laterality_display_name(laterality)
        if prefix and not base_name.startswith(prefix):
            base_name = f"{prefix}{base_name}"
        return self._with_view_prefix(base_name, str(fact.get("view_hint") or ""))

    def _non_independent_finding_notes(self, evidence: dict[str, Any]) -> list[str]:
        notes: list[str] = []
        seen: set[tuple[str, str, str]] = set()
        for finding in evidence.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            if finding.get("independent_evidence", True) is not False:
                continue
            if not finding.get("diagnosis_usable", True):
                continue
            if finding.get("status") not in {"candidate_present", "supported", "detected"}:
                continue
            target = str(finding.get("target") or "").strip()
            if not target:
                continue
            overlap_qc = dict(finding.get("overlap_qc") or {})
            overlap_target = str(overlap_qc.get("overlap_with_target") or "").strip()
            if not overlap_target:
                overlap_target = self._overlap_warning_target_for(
                    evidence=evidence,
                    target=target,
                )
            mask_iou = overlap_qc.get("mask_iou")
            display_name = self._localized_finding_display_name(finding)
            overlap_finding = self._finding_by_id(
                evidence=evidence,
                finding_id=str(overlap_qc.get("overlap_with_finding_id") or ""),
            )
            overlap_display = (
                self._localized_finding_display_name(overlap_finding)
                if overlap_finding
                else self._finding_display_name(overlap_target)
                if overlap_target
                else "另一候选征象"
            )
            iou_text = f"（mask IoU {mask_iou}）" if mask_iou is not None else ""
            key = (display_name, overlap_display, str(mask_iou))
            if key in seen:
                continue
            seen.add(key)
            notes.append(
                f"同区域候选征象：{display_name} 与 {overlap_display} 的分割 mask 高度重叠{iou_text}，"
                "不作为独立诊断依据，需影像科或更合适的专病模型复核。"
            )
        return notes

    def _finding_by_id(
        self,
        *,
        evidence: dict[str, Any],
        finding_id: str,
    ) -> dict[str, Any] | None:
        if not finding_id:
            return None
        for finding in evidence.get("findings") or []:
            if isinstance(finding, dict) and str(finding.get("finding_id") or "") == finding_id:
                return finding
        return None

    def _localized_finding_display_name(self, finding: dict[str, Any]) -> str:
        target = str(finding.get("target") or "")
        base_name = self._finding_display_name(str(finding.get("display_name") or target))
        laterality = self._finding_laterality(finding)
        prefix = self._laterality_display_name(laterality)
        if prefix and not base_name.startswith(prefix):
            base_name = f"{prefix}{base_name}"
        return self._with_view_prefix(base_name, str(finding.get("view_hint") or ""))

    def _finding_laterality(self, finding: dict[str, Any]) -> str:
        measurements = finding.get("measurements") or {}
        laterality = str(measurements.get("laterality") or "").strip()
        if laterality and laterality != "unknown":
            return laterality
        for region in finding.get("regions") or []:
            if isinstance(region, dict):
                region_laterality = str(region.get("laterality") or "").strip()
                if region_laterality and region_laterality != "unknown":
                    return region_laterality
        return ""

    def _laterality_display_name(self, laterality: str) -> str:
        return {
            "left": "左侧",
            "right": "右侧",
            "image_left": "图像左侧",
            "image_right": "图像右侧",
        }.get(laterality, "")

    def _with_view_prefix(self, name: str, view_hint: str) -> str:
        view = self._view_hint_display_name(view_hint)
        if not view or name.startswith(f"{view}："):
            return name
        return f"{view}：{name}"

    def _view_hint_display_name(self, view_hint: str) -> str:
        return {
            "ap_pelvis": "骨盆正位/AP",
            "frog_lateral": "蛙式侧位",
            "lateral": "侧位",
        }.get(view_hint, "")

    def _overlap_warning_target_for(
        self,
        *,
        evidence: dict[str, Any],
        target: str,
    ) -> str:
        for warning in evidence.get("quality_warnings") or []:
            if not isinstance(warning, dict):
                continue
            if warning.get("code") != "overlapping_candidate_findings":
                continue
            if str(warning.get("target") or "") == target:
                return str(warning.get("overlap_with_target") or "")
        return ""

    def _finding_display_name(self, value: str) -> str:
        display_names = {
            "sclerotic_band": "硬化带",
            "cystic_change": "囊性变",
            "trabecular_blurring": "骨小梁模糊或局灶性骨质疏松",
            "collapse": "股骨头塌陷",
            "lung_opacity": "肺部浸润影/实变影候选区域",
        }
        return display_names.get(value, value)

    def _checked_alignment_plan(self, alignment_plan: dict[str, Any] | None) -> dict[str, Any]:
        if not alignment_plan:
            return {}
        return AlignmentPlan.from_dict(alignment_plan).to_dict()

    def _alignment_blocks_diagnosis(self, alignment_plan: dict[str, Any]) -> bool:
        return alignment_plan.get("analysis_status") in {
            "insufficient_evidence",
            "contraindicated_or_wrong_modality",
        }

    def _generate_alignment_constrained_report(
        self,
        case_id: str,
        visual_result: dict[str, Any],
        skill_descriptor: dict[str, Any],
        alignment_plan: dict[str, Any],
    ) -> dict[str, Any]:
        image_context = alignment_plan.get("image_context") or {}
        suspected = alignment_plan.get("suspected_conditions") or []
        suspected_text = "；".join(
            f"{item.get('disease', '疑似疾病')}：{item.get('reason', '')}"
            for item in suspected
            if isinstance(item, dict)
        )
        next_steps = self._alignment_next_steps(alignment_plan)
        uncertainty = self._alignment_uncertainty(alignment_plan)
        report = self.report_agent.build_report(
            case_id=case_id,
            diagnostic_tendency="现有影像证据不足，需补充检查后判断",
            staging="暂无法依据当前影像按指南完成可靠分期或排除诊断。",
            visual_evidence=visual_result["visual_evidence"],
            uncertainty=uncertainty,
            follow_up=next_steps,
            treatment_advice=[
                "该结果不是最终诊断，需线下专科医生结合完整影像和必要检查复核。",
                "如症状持续、加重或出现功能受限，应及时线下就医。",
            ],
        )
        report["影像依据"] = [
            f"当前上传图像识别为 {image_context.get('modality', visual_result.get('modality', 'unknown'))} / {image_context.get('body_part', visual_result.get('body_part', 'unknown'))}",
            suspected_text or "症状和图像线索提示存在疑似疾病方向，但证据不足。",
        ]
        report["used_skill"] = skill_descriptor
        report["alignment_plan"] = alignment_plan
        return report

    def _apply_alignment_constraints(
        self,
        report: dict[str, Any],
        alignment_plan: dict[str, Any],
    ) -> None:
        if not alignment_plan:
            return
        report["alignment_plan"] = alignment_plan
        uncertainty = report.setdefault("不确定性说明", [])
        if isinstance(uncertainty, str):
            uncertainty = [uncertainty]
            report["不确定性说明"] = uncertainty
        for item in self._alignment_uncertainty(alignment_plan):
            if item not in uncertainty:
                uncertainty.append(item)
        follow_up = report.setdefault("建议进一步检查", [])
        if isinstance(follow_up, str):
            follow_up = [follow_up]
            report["建议进一步检查"] = follow_up
        for item in self._alignment_next_steps(alignment_plan):
            if item not in follow_up:
                follow_up.append(item)

    def _alignment_uncertainty(self, alignment_plan: dict[str, Any]) -> list[str]:
        values = list(alignment_plan.get("insufficiency_reasons") or [])
        values.extend(alignment_plan.get("diagnosis_scope", {}).get("blocked", []) or [])
        if alignment_plan.get("analysis_status") != "evidence_sufficient":
            values.append("当前结论必须受 alignment_plan 约束，不能越过已标记的证据不足字段。")
        return [str(value) for value in values if str(value).strip()]

    def _alignment_next_steps(self, alignment_plan: dict[str, Any]) -> list[str]:
        next_images = alignment_plan.get("required_next_images") or []
        steps = [
            f"建议上传或完善{item.get('region', '')} {item.get('modality', '')}：{item.get('reason', '')}".strip()
            for item in next_images
            if isinstance(item, dict)
        ]
        return steps or ["建议补充指南要求的关键影像后再进行判断"]

    def _generate_glioma_rule_based_report(
        self,
        case_id: str,
        evidence: dict[str, Any],
        skill_descriptor: dict[str, Any],
    ) -> dict[str, Any]:
        measurements = evidence.get("measurements") or {}
        whole_tumor_volume = measurements.get("whole_tumor_volume_ml")
        tendency = "成人弥漫性胶质瘤影像疑似，需病理和分子诊断确认"
        staging = (
            "当前仅基于结构化 MRI 视觉证据评估肿瘤负荷；"
            "WHO/EANO 整合诊断仍需组织病理和分子标志物。"
        )
        visual_findings = list(evidence.get("suspected_visual_findings", []))
        if whole_tumor_volume is not None:
            visual_findings.append(f"whole tumor 结构化体积约 {whole_tumor_volume} ml")

        glioma_evidence = dict(evidence)
        glioma_evidence["suspected_visual_findings"] = visual_findings
        report = self.report_agent.build_report(
            case_id=case_id,
            diagnostic_tendency=tendency,
            staging=staging,
            visual_evidence=glioma_evidence,
            uncertainty=[
                "MRI 影像只能支持肿瘤范围和形态学辅助判断，不能替代病理诊断",
                "缺少 IDH、1p/19q、MGMT、TERT/EGFR/+7-10 等分子证据",
            ]
            + self._visual_protocol_uncertainty(evidence),
            follow_up=[
                "建议补全 T1、T1ce、T2、FLAIR MRI 序列以评估肿瘤核心和强化成分",
                "建议神经肿瘤 MDT 结合病理和分子检测形成整合诊断",
            ],
            treatment_advice=[
                "治疗方案需等待病理分级、分子分型和可切除性评估后决定",
                "如出现进行性头痛、癫痫或神经功能缺损，应尽快线下就医",
            ],
        )
        report["used_skill"] = skill_descriptor
        return report

    def _visual_protocol_uncertainty(self, evidence: dict[str, Any]) -> list[str]:
        completeness = evidence.get("completeness") or {}
        uncertainty: list[str] = []
        for target, status in completeness.items():
            if not isinstance(status, dict):
                continue
            if status.get("status") in {"missing", "unassessed"}:
                reason = status.get("reason", "not assessed")
                uncertainty.append(
                    f"视觉证据字段 {target} 当前为 {status['status']}：{reason}，不能将其解释为阴性或数值为 0。"
                )
            if status.get("status") == "low_quality":
                reason = status.get("reason", "segmentation did not pass QC")
                uncertainty.append(
                    f"视觉证据字段 {target} 当前为 low_quality：{reason}，不能作为诊断可用证据。"
                )
        return uncertainty

    def _apply_segmentation_usability_gate(self, visual_result: dict[str, Any]) -> None:
        evidence = visual_result.get("visual_evidence") or {}
        segmentation_results = evidence.get("segmentation_results") or []
        if not segmentation_results:
            return
        measurements = dict(evidence.get("measurements") or {})
        completeness = dict(evidence.get("completeness") or {})
        for result in segmentation_results:
            if not isinstance(result, dict):
                continue
            if result.get("diagnosis_usable", True):
                continue
            target = str(result.get("target") or result.get("task_name") or "visual_task")
            for measurement_name in self._measurements_for_segmentation_result(result):
                measurements[measurement_name] = None
            reason = (
                (result.get("completeness") or {}).get("reason")
                or "; ".join((result.get("quality") or {}).get("warnings") or [])
                or "Segmentation did not pass QC"
            )
            completeness[target] = {
                "status": "low_quality"
                if result.get("status") == "low_quality"
                else "missing"
                if result.get("status") == "missing_input"
                else "unassessed",
                "reason": reason,
                "diagnosis_usable": False,
            }
        evidence["measurements"] = measurements
        evidence["completeness"] = completeness

    def _measurements_for_segmentation_result(self, result: dict[str, Any]) -> list[str]:
        measurements = result.get("measurements") or {}
        if measurements:
            return [str(key) for key in measurements]
        target = result.get("target")
        mapping = {
            "whole_tumor": "whole_tumor_volume_ml",
            "tumor_core": "tumor_core_volume_ml",
            "enhancing_tumor": "enhancing_tumor_volume_ml",
        }
        return [mapping[target]] if target in mapping else []

    def _try_generate_llm_report(
        self,
        case_id: str,
        patient_info: dict[str, Any],
        visual_result: dict[str, Any],
        disease_skill: dict[str, Any],
        skill_descriptor: dict[str, Any],
        alignment_plan: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        try:
            content = self.prompt_runner.run(
                task="diagnosis_report_generation",
                system_prompt=self._load_diagnosis_prompt(),
                user_payload={
                    "case_id": case_id,
                    "patient_info": patient_info,
                    "disease_skill": disease_skill,
                    "visual_result": visual_result,
                    "alignment_plan": alignment_plan,
                    "required_report_fields": REQUIRED_REPORT_FIELDS,
                },
            )
            report = json.loads(content)
            self._normalize_llm_report_list_fields(report)
            self._validate_llm_report(report)
            self._validate_llm_visual_field_contract(report, visual_result)
            self._validate_llm_against_visual_completeness(report, visual_result)
            self._validate_llm_against_visual_quality(report, visual_result)
            self._validate_llm_against_alignment_plan(report, alignment_plan)
            report["case_id"] = case_id
            report["diagnostic_tendency"] = report["诊断倾向"]
            report["used_skill"] = skill_descriptor
            return report, None
        except (JSONDecodeError, TypeError) as exc:
            return None, f"invalid llm json: {exc}"
        except ValueError as exc:
            return None, str(exc)

    def _validate_llm_report(self, report: dict[str, Any]) -> None:
        missing = [field for field in REQUIRED_REPORT_FIELDS if field not in report]
        if missing:
            raise ValueError(f"missing required report fields: {', '.join(missing)}")
        list_fields = ["影像依据", "不确定性说明", "建议进一步检查", "治疗建议"]
        bad_fields = [field for field in list_fields if not isinstance(report[field], list)]
        if bad_fields:
            raise ValueError(f"report fields must be lists: {', '.join(bad_fields)}")

    def _normalize_llm_report_list_fields(self, report: dict[str, Any]) -> None:
        for field in ["影像依据", "不确定性说明", "建议进一步检查", "治疗建议"]:
            if isinstance(report.get(field), str):
                report[field] = [report[field]]
        self._validate_llm_report(report)

    def _validate_llm_visual_field_contract(
        self,
        report: dict[str, Any],
        visual_result: dict[str, Any],
    ) -> None:
        evidence = visual_result.get("visual_evidence") or {}
        completeness = evidence.get("completeness") or {}
        if not completeness:
            return

        for field in ("used_visual_fields", "missing_visual_fields_acknowledged"):
            if field not in report:
                raise ValueError(
                    "used_visual_fields and missing_visual_fields_acknowledged are required "
                    "when visual completeness is present"
                )
            if not isinstance(report[field], list):
                raise ValueError(f"{field} must be a list")

        missing_targets = [
            str(target)
            for target, status in completeness.items()
            if isinstance(status, dict) and status.get("status") in {"missing", "unassessed"}
        ]
        acknowledged = {str(target) for target in report["missing_visual_fields_acknowledged"]}
        unacknowledged = [target for target in missing_targets if target not in acknowledged]
        if unacknowledged:
            raise ValueError(
                "missing_visual_fields_acknowledged must include: "
                + ", ".join(unacknowledged)
            )

    def _validate_llm_against_visual_completeness(
        self,
        report: dict[str, Any],
        visual_result: dict[str, Any],
    ) -> None:
        evidence = visual_result.get("visual_evidence") or {}
        completeness = evidence.get("completeness") or {}
        if not completeness:
            return

        forbidden_claim_markers = [
            "为 0",
            "为0",
            "0 ml",
            "0ml",
            "阴性",
            "未见",
            "无强化",
            "没有强化",
            "未发现",
        ]
        for target, status in completeness.items():
            if not isinstance(status, dict):
                continue
            if status.get("status") not in {"missing", "unassessed"}:
                continue
            target_context = self._report_target_context(report, str(target))
            if not target_context:
                continue
            if self._has_unqualified_negative_or_zero_claim(
                report_text=target_context,
                markers=forbidden_claim_markers,
            ):
                reason = status.get("reason", "not assessed")
                raise ValueError(
                    f"missing visual evidence {target} was interpreted as negative/zero: {reason}"
                )

    def _validate_llm_against_visual_quality(
        self,
        report: dict[str, Any],
        visual_result: dict[str, Any],
    ) -> None:
        evidence = visual_result.get("visual_evidence") or {}
        non_independent_notes = self._non_independent_finding_notes(evidence)
        if not non_independent_notes:
            return
        report_text = json.dumps(report, ensure_ascii=False)
        required_quality_markers = ["同区域", "重叠", "不作为独立", "非独立"]
        if not any(marker in report_text for marker in required_quality_markers):
            raise ValueError("llm report ignores overlapping candidate visual evidence")
        if "独立征象" in report_text and not any(
            marker in report_text for marker in ["不作为独立", "非独立"]
        ):
            raise ValueError("llm report counts overlapping candidate visual evidence as independent")

    def _validate_llm_against_alignment_plan(
        self,
        report: dict[str, Any],
        alignment_plan: dict[str, Any],
    ) -> None:
        if not alignment_plan:
            return
        report_text = json.dumps(report, ensure_ascii=False)
        if self._alignment_blocks_diagnosis(alignment_plan):
            required_limit_markers = ["证据不足", "无法", "不能", "需补充", "不满足"]
            if not any(marker in report_text for marker in required_limit_markers):
                raise ValueError("llm report ignores blocking alignment_plan status")

        blocked_items = alignment_plan.get("diagnosis_scope", {}).get("blocked", []) or []
        for blocked in blocked_items:
            markers = self._forbidden_markers_for_blocked_scope(str(blocked))
            if markers and self._has_unqualified_negative_or_zero_claim(report_text, markers):
                raise ValueError(f"llm report violates alignment_plan blocked scope: {blocked}")

    def _forbidden_markers_for_blocked_scope(self, blocked_scope: str) -> list[str]:
        markers: list[str] = []
        if any(term in blocked_scope for term in ["无病", "排除", "正常", "阴性"]):
            markers.extend(["无病", "排除", "正常", "阴性"])
        if any(term in blocked_scope for term in ["未见异常", "X 光", "X光"]):
            markers.extend(["未见异常", "未见明显异常", "无需补充检查"])
        if any(term in blocked_scope for term in ["强化", "T1ce", "增强"]):
            markers.extend(["无强化", "未见强化", "没有强化", "强化阴性", "增强肿瘤为 0", "0 ml"])
        if any(term in blocked_scope for term in ["缺失", "missing_input", "missing", "缺少"]):
            markers.extend(["为 0", "为0", "0 ml", "阴性", "未见", "未发现", "正常"])
        return list(dict.fromkeys(markers))

    def _has_unqualified_negative_or_zero_claim(
        self,
        report_text: str,
        markers: list[str],
    ) -> bool:
        negation_markers = ["不能", "不可", "不得", "不应", "无法", "不宜"]
        for marker in markers:
            search_from = 0
            while True:
                index = report_text.find(marker, search_from)
                if index == -1:
                    break
                prefix = report_text[max(0, index - 32) : index]
                if not any(negation in prefix for negation in negation_markers):
                    return True
                search_from = index + len(marker)
        return False

    def _report_mentions_visual_target(self, report_text: str, target: str) -> bool:
        return any(alias in report_text for alias in self._visual_target_aliases(target))

    def _report_target_context(self, report: Any, target: str) -> str:
        aliases = self._visual_target_aliases(target)
        snippets = [
            text
            for text in self._iter_report_strings(report)
            if any(alias in text for alias in aliases)
        ]
        return "\n".join(snippets)

    def _iter_report_strings(self, value: Any):
        if isinstance(value, str):
            yield value
            return
        if isinstance(value, dict):
            for item in value.values():
                yield from self._iter_report_strings(item)
            return
        if isinstance(value, list):
            for item in value:
                yield from self._iter_report_strings(item)

    def _visual_target_aliases(self, target: str) -> list[str]:
        aliases = {
            "whole_tumor": ["whole_tumor", "whole tumor", "全肿瘤", "肿瘤整体"],
            "tumor_core": ["tumor_core", "tumor core", "肿瘤核心", "核心肿瘤"],
            "enhancing_tumor": [
                "enhancing_tumor",
                "enhancing tumor",
                "强化肿瘤",
                "强化成分",
                "增强肿瘤",
            ],
            "mass_effect": ["mass_effect", "mass effect", "占位效应", "中线移位"],
            "edema": ["edema", "水肿"],
        }
        return aliases.get(target, [target])

    def _load_diagnosis_prompt(self) -> str:
        prompt_path = Path("prompts/diagnosis_agent_prompt.md")
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return "你是诊断医生 Agent，只能根据结构化证据生成 JSON 报告。"
