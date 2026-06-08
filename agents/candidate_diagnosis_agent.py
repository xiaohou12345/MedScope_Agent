from __future__ import annotations

from typing import Any

from agents.diagnosis_agent import DiagnosisDoctorAgent


class CandidateDiagnosisAgent(DiagnosisDoctorAgent):
    """Experimental ONFH diagnosis layer with explicit uncertainty output.

    This class leaves the shared DiagnosisDoctorAgent unchanged. It adds a
    structured ONFH candidate-staging decision after the base report is built,
    so visual-model results and agent-level diagnosis can be scored separately.
    """

    III_TARGETS = {"collapse", "subchondral_fracture", "crescent_sign"}
    III_TEXT_MARKERS = ("塌陷", "软骨下", "骨折", "新月")
    I_II_TARGETS = {
        "sclerotic_band",
        "cystic_change",
        "mixed_density_region",
        "trabecular_blurring",
    }
    I_II_TEXT_MARKERS = ("硬化", "囊", "密度不均", "骨小梁")

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
        report = super().generate_report(
            case_id=case_id,
            patient_info=patient_info,
            visual_result=visual_result,
            disease_skill=disease_skill,
            hypothesis_validation_mode=hypothesis_validation_mode,
            alignment_plan=alignment_plan,
            routing_decision=routing_decision,
        )
        if not self._is_onfh_case(report=report, visual_result=visual_result, disease_skill=disease_skill):
            return report

        evidence = dict(
            (report.get("visual_input_contract") or {}).get("visual_evidence")
            or visual_result.get("visual_evidence")
            or {}
        )
        visual_model_result = self._build_visual_model_result(evidence)
        agent_diagnosis = self._build_agent_diagnosis(
            visual_model_result=visual_model_result,
            modality=str(visual_result.get("modality") or "").lower(),
            base_report=report,
        )
        report["onfh_visual_model_result"] = visual_model_result
        report["onfh_agent_diagnosis"] = agent_diagnosis
        report["agent_stage"] = agent_diagnosis["stage"]
        report["agent_stage_confidence"] = agent_diagnosis["confidence"]
        report["agent_abstained"] = agent_diagnosis["abstained"]
        report["agent_uncertainty_status"] = agent_diagnosis["uncertainty_status"]
        report["不确定性说明"] = list(
            dict.fromkeys(
                list(report.get("不确定性说明") or [])
                + list(agent_diagnosis["uncertainty_reasons"])
            )
        )
        return report

    def _is_onfh_case(
        self,
        *,
        report: dict[str, Any],
        visual_result: dict[str, Any],
        disease_skill: dict[str, Any] | None,
    ) -> bool:
        skill = disease_skill or report.get("used_skill") or {}
        skill_text = " ".join(
            str(value)
            for value in [
                skill.get("skill_id"),
                skill.get("disease_key"),
                skill.get("disease_name"),
                visual_result.get("visual_evidence", {}).get("disease_target"),
            ]
            if value
        )
        return any(
            marker in skill_text
            for marker in ["femoral_head_necrosis", "股骨头坏死", "ONFH"]
        )

    def _build_visual_model_result(self, evidence: dict[str, Any]) -> dict[str, Any]:
        findings = self._candidate_findings(evidence)
        targets = [finding["target"] for finding in findings if finding.get("target")]
        basis_texts = [finding["text"] for finding in findings if finding.get("text")]
        stage = self._stage_from_targets_and_text(targets=targets, texts=basis_texts)
        return {
            "stage": stage,
            "stage_source": "visual_evidence_candidate_mapping",
            "basis_targets": sorted(set(targets)),
            "basis_text": basis_texts,
            "finding_count": len(findings),
            "has_stage_relevant_evidence": stage in {"normal", "I/II", "III+"},
            "diagnosis_usable_finding_count": sum(
                1 for finding in findings if finding.get("diagnosis_usable") is True
            ),
        }

    def _candidate_findings(self, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for finding in evidence.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            if finding.get("independent_evidence", True) is False:
                continue
            status = str(finding.get("status") or "").strip()
            if status and status not in {"candidate_present", "supported", "detected"}:
                continue
            rows.append(
                {
                    "target": str(finding.get("target") or "").strip(),
                    "text": self._finding_text(finding),
                    "diagnosis_usable": finding.get("diagnosis_usable", True) is True,
                }
            )
        if rows:
            return rows

        for fact in evidence.get("structured_visual_facts") or []:
            if not isinstance(fact, dict):
                continue
            if fact.get("independent_evidence", True) is False:
                continue
            status = str(fact.get("status") or "").strip()
            if status and status not in {"candidate_present", "supported", "detected"}:
                continue
            rows.append(
                {
                    "target": str(fact.get("target") or "").strip(),
                    "text": self._finding_text(fact),
                    "diagnosis_usable": fact.get("diagnosis_usable", True) is True,
                }
            )
        if rows:
            return rows

        for text in evidence.get("suspected_visual_findings") or []:
            text_value = str(text).strip()
            if text_value:
                rows.append({"target": "", "text": text_value, "diagnosis_usable": True})
        return rows

    def _finding_text(self, finding: dict[str, Any]) -> str:
        fields = [
            finding.get("display_name"),
            finding.get("target"),
            finding.get("summary_text"),
            finding.get("evidence_text"),
            finding.get("rationale"),
        ]
        return "；".join(str(value) for value in fields if value)

    def _stage_from_targets_and_text(self, *, targets: list[str], texts: list[str]) -> str:
        target_set = set(targets)
        joined_text = " ".join(texts)
        if target_set & self.III_TARGETS or any(marker in joined_text for marker in self.III_TEXT_MARKERS):
            return "III+"
        if target_set & self.I_II_TARGETS or any(marker in joined_text for marker in self.I_II_TEXT_MARKERS):
            return "I/II"
        if targets or texts:
            return "normal"
        return "evidence_insufficient"

    def _build_agent_diagnosis(
        self,
        *,
        visual_model_result: dict[str, Any],
        modality: str,
        base_report: dict[str, Any],
    ) -> dict[str, Any]:
        base_stage = self._parse_base_report_stage(base_report)
        visual_stage = str(visual_model_result.get("stage") or "evidence_insufficient")
        base_stage_text = str(base_report.get("分期判断") or "")
        base_tendency = str(base_report.get("diagnostic_tendency") or "")
        uncertainty_reasons = [
            "当前输出保留原版 DiagnosisAgent 的诊断边界。",
            "视觉候选分期只作为不确定诊断参考，不自动覆盖原版最终分期。",
        ]
        if modality and modality not in {"xray", "x-ray", "radiograph"}:
            uncertainty_reasons.append(f"当前输入模态为 {modality}，本实验规则主要按 Xray 候选征象设计。")
        if base_stage == "evidence_insufficient":
            if visual_stage in {"normal", "I/II", "III+"}:
                uncertainty_reasons.append(
                    f"原版报告未可靠分期；视觉层给出 {visual_stage} 候选分期，仅作待复核线索。"
                )
                confidence = {"normal": 0.25, "I/II": 0.35, "III+": 0.4}.get(visual_stage, 0.0)
            else:
                uncertainty_reasons.append("原版报告和视觉层均未提供可分期证据。")
                confidence = 0.0
            return {
                "stage": "evidence_insufficient",
                "candidate_stage": visual_stage,
                "confidence": confidence,
                "abstained": True,
                "uncertainty_status": "base_report_abstain",
                "diagnostic_tendency": base_tendency or "影像证据不足，需进一步评估",
                "report_stage_text": base_stage_text or "暂无法可靠分期",
                "uncertainty_reasons": uncertainty_reasons,
                "basis_targets": list(visual_model_result.get("basis_targets") or []),
                "decision_scope": "experimental_onfh_uncertain_diagnosis_close_to_base",
            }

        confidence = {"normal": 0.55, "I/II": 0.62, "III+": 0.68}.get(base_stage, 0.0)
        if visual_stage in {"normal", "I/II", "III+"} and visual_stage != base_stage:
            uncertainty_reasons.append(
                f"原版最终分期为 {base_stage}，视觉候选分期为 {visual_stage}，存在分期不一致。"
            )
            confidence = min(confidence, 0.45)
        return {
            "stage": base_stage,
            "candidate_stage": visual_stage,
            "confidence": confidence,
            "abstained": False,
            "uncertainty_status": "base_report_classified",
            "diagnostic_tendency": base_tendency,
            "report_stage_text": base_stage_text,
            "uncertainty_reasons": uncertainty_reasons,
            "basis_targets": list(visual_model_result.get("basis_targets") or []),
            "decision_scope": "experimental_onfh_uncertain_diagnosis_close_to_base",
        }

    def _parse_base_report_stage(self, base_report: dict[str, Any]) -> str:
        text = " ".join(
            str(base_report.get(field) or "")
            for field in ["分期判断", "diagnostic_tendency", "诊断倾向"]
        )
        if any(marker in text for marker in ["证据不足", "暂无法", "不能可靠", "需 MRI", "需MRI"]):
            return "evidence_insufficient"
        if any(marker in text for marker in ["III", "III+", "塌陷", "软骨下骨折", "新月"]):
            return "III+"
        if any(marker in text for marker in ["I/II", "ARCO II", "早期", "硬化", "囊性"]):
            return "I/II"
        if any(marker in text for marker in ["未见明确", "normal", "阴性"]):
            return "normal"
        return "evidence_insufficient"
