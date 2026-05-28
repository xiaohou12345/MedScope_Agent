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
        report["visual_input_contract"] = visual_input_contract
        return report

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
        return report

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
        if not prefix or base_name.startswith(prefix):
            return base_name
        return f"{prefix}{base_name}"

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
        if not prefix or base_name.startswith(prefix):
            return base_name
        return f"{prefix}{base_name}"

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
