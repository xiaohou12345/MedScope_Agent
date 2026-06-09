from __future__ import annotations

from typing import Any

from agents.diagnosis_agent import DiagnosisDoctorAgent


STAGE_SCHEMA_REGISTRY: dict[str, dict[str, Any]] = {
    "mri_arco_3class": {
        "name": "mri_arco_3class",
        "labels": ["normal", "I/II", "III+"],
        "canonical_map": {
            "normal": "normal",
            "I/II": "I/II",
            "II": "I/II",
            "III+": "III+",
            "III": "III+",
            "evidence_insufficient": "evidence_insufficient",
        },
        "confidence": {"normal": 0.45, "I/II": 0.6, "III+": 0.65},
        "tendency": {
            "normal": "finding list 未见明确 ONFH 候选征象",
            "I/II": "finding list 支持早期 ONFH 候选征象，倾向 ARCO I/II 可能",
            "III+": "finding list 出现塌陷/软骨下骨折/新月征相关候选征象，倾向 ARCO III 及以上可能",
        },
        "decision_scope": "experimental_onfh_lite_findings_only",
    },
    "xray_arco_3class": {
        "name": "xray_arco_3class",
        "labels": ["normal", "II", "III"],
        "canonical_map": {
            "normal": "normal",
            "I/II": "II",
            "II": "II",
            "III+": "III",
            "III": "III",
            "evidence_insufficient": "evidence_insufficient",
        },
        "confidence": {"normal": 0.45, "II": 0.6, "III": 0.65},
        "tendency": {
            "normal": "finding list 未见明确 Xray ONFH 候选征象",
            "II": "finding list 支持 Xray ARCO II 候选征象，未见明确塌陷/软骨下骨折",
            "III": "finding list 出现塌陷/软骨下骨折/新月征相关候选征象，倾向 Xray ARCO III",
        },
        "decision_scope": "experimental_onfh_xray_arco_3class_findings_only",
    },
}


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

    def generate_lite_report(
        self,
        *,
        case_id: str,
        patient_info: dict[str, Any],
        findings: list[dict[str, Any]],
        modality: str = "xray",
        disease_target: str = "femoral_head_necrosis",
        stage_schema: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a compact ONFH candidate report from findings only.

        This path is intended for controlled experiments where the finding list
        has already been produced, for example from reviewed mock masks. It does
        not call the base DiagnosisDoctorAgent and intentionally avoids sending
        the full skill, visual contract, image outputs, or audit bundle.
        """
        evidence = {
            "disease_target": disease_target,
            "findings": findings,
        }
        schema = self._resolve_stage_schema(stage_schema)
        visual_model_result = self._build_visual_model_result(evidence, stage_schema=schema)
        agent_diagnosis = self._build_lite_agent_diagnosis(
            visual_model_result=visual_model_result,
            modality=modality,
            stage_schema=schema,
        )
        report = {
            "case_id": case_id,
            "patient_info": {
                "patient_id": patient_info.get("patient_id"),
                "patient_side": patient_info.get("patient_side"),
            },
            "诊断倾向": agent_diagnosis["diagnostic_tendency"],
            "diagnostic_tendency": agent_diagnosis["diagnostic_tendency"],
            "影像依据": list(visual_model_result.get("basis_text") or []),
            "分期判断": agent_diagnosis["report_stage_text"],
            "不确定性说明": agent_diagnosis["uncertainty_reasons"],
            "建议进一步检查": ["结合 MRI、临床资料和线下医生复核确认分期。"],
            "治疗建议": ["本输出仅用于研究评估，不作为治疗建议。"],
            "onfh_visual_model_result": visual_model_result,
            "onfh_agent_diagnosis": agent_diagnosis,
            "agent_stage": agent_diagnosis["stage"],
            "agent_stage_confidence": agent_diagnosis["confidence"],
            "agent_abstained": agent_diagnosis["abstained"],
            "agent_uncertainty_status": agent_diagnosis["uncertainty_status"],
            "lite_mode": True,
            "lite_input_contract": {
                "modality": modality,
                "disease_target": disease_target,
                "finding_count": len(findings),
                "fields_used": ["findings.target", "findings.display_name", "findings.summary_text"],
                "stage_schema": schema.get("name"),
                "allowed_stages": list(schema.get("labels") or []),
                "excluded_from_prompt": [
                    "used_skill",
                    "visual_input_contract",
                    "image_outputs",
                    "visual_fact_usage",
                    "excluded_visual_facts",
                    "guideline_evidence",
                ],
            },
        }
        return report

    def generate_report(
        self,
        case_id: str,
        patient_info: dict[str, Any],
        visual_result: dict[str, Any],
        disease_skill: dict[str, Any] | None = None,
        hypothesis_validation_mode: bool | None = None,
        alignment_plan: dict[str, Any] | None = None,
        routing_decision: dict[str, Any] | None = None,
        stage_schema: str | dict[str, Any] | None = None,
        final_stage_mode: str = "conservative",
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
        schema = self._resolve_stage_schema(stage_schema)
        visual_model_result = self._build_visual_model_result(evidence, stage_schema=schema)
        agent_diagnosis = self._build_agent_diagnosis(
            visual_model_result=visual_model_result,
            modality=str(visual_result.get("modality") or "").lower(),
            base_report=report,
            stage_schema=schema,
            final_stage_mode=final_stage_mode,
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

    def _build_visual_model_result(
        self,
        evidence: dict[str, Any],
        *,
        stage_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        schema = self._resolve_stage_schema(stage_schema)
        findings = self._candidate_findings(evidence)
        positive_findings = [
            finding for finding in findings if str(finding.get("status") or "") != "negative"
        ]
        targets = [finding["target"] for finding in positive_findings if finding.get("target")]
        positive_basis_texts = [
            finding["text"] for finding in positive_findings if finding.get("text")
        ]
        basis_texts = [finding["text"] for finding in findings if finding.get("text")]
        raw_stage = self._stage_from_targets_and_text(targets=targets, texts=positive_basis_texts)
        if raw_stage == "evidence_insufficient" and findings and not positive_findings:
            raw_stage = "normal"
        stage = self._canonical_stage(raw_stage, schema)
        return {
            "stage": stage,
            "raw_stage": raw_stage,
            "stage_source": "visual_evidence_candidate_mapping",
            "stage_schema": schema.get("name"),
            "allowed_stages": list(schema.get("labels") or []),
            "basis_targets": sorted(set(targets)),
            "basis_text": basis_texts,
            "finding_count": len(findings),
            "has_stage_relevant_evidence": stage in set(schema.get("labels") or []),
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
            if status and status not in {"candidate_present", "supported", "detected", "negative"}:
                continue
            rows.append(
                {
                    "target": str(finding.get("target") or "").strip(),
                    "text": self._finding_text(finding),
                    "status": status,
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
            if status and status not in {"candidate_present", "supported", "detected", "negative"}:
                continue
            rows.append(
                {
                    "target": str(fact.get("target") or "").strip(),
                    "text": self._finding_text(fact),
                    "status": status,
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
        stage_schema: dict[str, Any] | None = None,
        final_stage_mode: str = "conservative",
    ) -> dict[str, Any]:
        schema = self._resolve_stage_schema(stage_schema)
        allowed_stages = set(schema.get("labels") or [])
        allow_provisional_final = final_stage_mode == "llm_final"
        base_stage = self._parse_base_report_stage(
            base_report,
            allow_provisional=allow_provisional_final,
        )
        base_stage = self._canonical_stage(base_stage, schema)
        visual_stage = self._canonical_stage(
            visual_model_result.get("stage") or "evidence_insufficient",
            schema,
        )
        base_stage_text = str(base_report.get("分期判断") or "")
        base_tendency = str(base_report.get("diagnostic_tendency") or "")
        uncertainty_reasons = [
            "当前输出保留原版 DiagnosisAgent 的诊断边界。",
            "视觉候选分期只作为不确定诊断参考，不自动覆盖原版最终分期。",
            f"当前候选分期使用 {schema.get('name')} 标签空间。",
        ]
        if modality and modality not in {"xray", "x-ray", "radiograph"}:
            uncertainty_reasons.append(f"当前输入模态为 {modality}，本实验规则主要按 Xray 候选征象设计。")
        if allow_provisional_final and base_stage in allowed_stages:
            confidence = (schema.get("confidence") or {}).get(base_stage, 0.0)
            if visual_stage in allowed_stages and visual_stage != base_stage:
                uncertainty_reasons.append(
                    f"full 诊断报告解析分期为 {base_stage}，视觉候选分期为 {visual_stage}，存在分期不一致。"
                )
                confidence = min(confidence, 0.45)
            uncertainty_reasons.append(
                "llm_final 实验模式启用：允许原版 full 诊断报告中的倾向性分期作为可评分 final stage。"
            )
            return {
                "stage": base_stage,
                "candidate_stage": visual_stage,
                "provisional_stage": base_stage,
                "provisional_confidence": confidence,
                "can_assign_final_stage": True,
                "stage_output_mode": "llm_final_from_full_report",
                "confidence": confidence,
                "abstained": False,
                "uncertainty_status": "llm_final_stage_from_full_report",
                "diagnostic_tendency": base_tendency,
                "report_stage_text": base_stage_text,
                "uncertainty_reasons": uncertainty_reasons,
                "basis_targets": list(visual_model_result.get("basis_targets") or []),
                "decision_scope": "experimental_onfh_llm_final_stage_from_full_report",
                "stage_schema": schema.get("name"),
                "allowed_stages": list(schema.get("labels") or []),
            }
        if base_stage == "evidence_insufficient":
            if visual_stage in allowed_stages:
                uncertainty_reasons.append(
                    f"原版报告未可靠分期；视觉层给出 {visual_stage} 候选分期，仅作待复核线索。"
                )
                confidence = self._full_candidate_confidence(visual_stage, schema)
            else:
                uncertainty_reasons.append("原版报告和视觉层均未提供可分期证据。")
                confidence = 0.0
            return {
                "stage": "evidence_insufficient",
                "candidate_stage": visual_stage,
                "provisional_stage": visual_stage,
                "provisional_confidence": confidence,
                "can_assign_final_stage": False,
                "stage_output_mode": "abstain_with_candidate",
                "confidence": confidence,
                "abstained": True,
                "uncertainty_status": "base_report_abstain",
                "diagnostic_tendency": base_tendency or "影像证据不足，需进一步评估",
                "report_stage_text": base_stage_text or "暂无法可靠分期",
                "uncertainty_reasons": uncertainty_reasons,
                "basis_targets": list(visual_model_result.get("basis_targets") or []),
                "decision_scope": "experimental_onfh_uncertain_diagnosis_close_to_base",
                "stage_schema": schema.get("name"),
                "allowed_stages": list(schema.get("labels") or []),
            }

        confidence = (schema.get("confidence") or {}).get(base_stage, 0.0)
        if visual_stage in allowed_stages and visual_stage != base_stage:
            uncertainty_reasons.append(
                f"原版最终分期为 {base_stage}，视觉候选分期为 {visual_stage}，存在分期不一致。"
            )
            confidence = min(confidence, 0.45)
        return {
            "stage": base_stage,
            "candidate_stage": visual_stage,
            "provisional_stage": visual_stage,
            "provisional_confidence": confidence,
            "can_assign_final_stage": True,
            "stage_output_mode": "final_with_candidate",
            "confidence": confidence,
            "abstained": False,
            "uncertainty_status": "base_report_classified",
            "diagnostic_tendency": base_tendency,
            "report_stage_text": base_stage_text,
            "uncertainty_reasons": uncertainty_reasons,
            "basis_targets": list(visual_model_result.get("basis_targets") or []),
            "decision_scope": "experimental_onfh_uncertain_diagnosis_close_to_base",
            "stage_schema": schema.get("name"),
            "allowed_stages": list(schema.get("labels") or []),
        }

    def _full_candidate_confidence(self, stage: str, stage_schema: dict[str, Any]) -> float:
        if stage == "evidence_insufficient":
            return 0.0
        if stage == "normal":
            return 0.25
        if stage in {"I/II", "II"}:
            return 0.35
        if stage in {"III+", "III"}:
            return 0.4
        return float((stage_schema.get("confidence") or {}).get(stage, 0.0))

    def _build_lite_agent_diagnosis(
        self,
        *,
        visual_model_result: dict[str, Any],
        modality: str,
        stage_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        schema = self._resolve_stage_schema(stage_schema)
        allowed_stages = set(schema.get("labels") or [])
        visual_stage = self._canonical_stage(
            visual_model_result.get("stage") or "evidence_insufficient",
            schema,
        )
        uncertainty_reasons = [
            "lite 模式仅使用 finding list，不使用完整 skill、视觉 contract 或审计字段。",
            f"该输出使用 {schema.get('name')} 标签空间，用于研究评估，不等同跨模态确诊分期。",
        ]
        if modality and modality not in {"xray", "x-ray", "radiograph"}:
            uncertainty_reasons.append(f"当前输入模态为 {modality}，lite 规则主要按 Xray 候选征象设计。")
        if visual_stage == "evidence_insufficient":
            return {
                "stage": "evidence_insufficient",
                "candidate_stage": "evidence_insufficient",
                "confidence": 0.0,
                "abstained": True,
                "uncertainty_status": "lite_no_stage_relevant_findings",
                "diagnostic_tendency": "finding list 未提供可分期征象，暂无法可靠分期",
                "report_stage_text": "暂无法可靠分期",
                "uncertainty_reasons": uncertainty_reasons,
                "basis_targets": list(visual_model_result.get("basis_targets") or []),
                "decision_scope": schema.get("decision_scope", "experimental_onfh_lite_findings_only"),
                "stage_schema": schema.get("name"),
                "allowed_stages": list(schema.get("labels") or []),
            }
        confidence = (schema.get("confidence") or {}).get(visual_stage, 0.0)
        tendency = (schema.get("tendency") or {}).get(visual_stage, "finding list 证据不足")
        return {
            "stage": visual_stage,
            "candidate_stage": visual_stage,
            "confidence": confidence,
            "abstained": False,
            "uncertainty_status": (
                "lite_candidate_stage_from_findings"
                if visual_stage in allowed_stages
                else "lite_stage_outside_schema"
            ),
            "diagnostic_tendency": tendency,
            "report_stage_text": tendency,
            "uncertainty_reasons": uncertainty_reasons,
            "basis_targets": list(visual_model_result.get("basis_targets") or []),
            "decision_scope": schema.get("decision_scope", "experimental_onfh_lite_findings_only"),
            "stage_schema": schema.get("name"),
            "allowed_stages": list(schema.get("labels") or []),
        }

    def _resolve_stage_schema(self, stage_schema: str | dict[str, Any] | None) -> dict[str, Any]:
        if stage_schema is None:
            return dict(STAGE_SCHEMA_REGISTRY["mri_arco_3class"])
        if isinstance(stage_schema, str):
            if stage_schema not in STAGE_SCHEMA_REGISTRY:
                raise ValueError(f"unknown ONFH stage_schema: {stage_schema}")
            return dict(STAGE_SCHEMA_REGISTRY[stage_schema])
        schema = dict(stage_schema)
        if not schema.get("labels"):
            raise ValueError("stage_schema must define labels")
        schema.setdefault("name", "custom")
        schema.setdefault("canonical_map", {})
        schema.setdefault("confidence", {})
        schema.setdefault("tendency", {})
        return schema

    def _canonical_stage(self, stage: Any, stage_schema: dict[str, Any]) -> str:
        text = str(stage or "").strip()
        if not text:
            return "evidence_insufficient"
        canonical_map = stage_schema.get("canonical_map") or {}
        if text in canonical_map:
            return str(canonical_map[text])
        if text in set(stage_schema.get("labels") or []):
            return text
        if text == "evidence_insufficient":
            return text
        if "III" in text or "塌陷" in text or "新月" in text or "软骨下" in text:
            return str(canonical_map.get("III+", canonical_map.get("III", "III+")))
        if "I/II" in text or "I /II" in text or "II" in text or "硬化" in text or "囊" in text:
            return str(canonical_map.get("I/II", canonical_map.get("II", "I/II")))
        if "normal" in text or "无明显异常" in text or "未见" in text or "阴性" in text:
            return str(canonical_map.get("normal", "normal"))
        return "evidence_insufficient"

    def _parse_base_report_stage(
        self,
        base_report: dict[str, Any],
        *,
        allow_provisional: bool = False,
    ) -> str:
        text = " ".join(
            str(base_report.get(field) or "")
            for field in ["分期判断", "diagnostic_tendency", "诊断倾向"]
        )
        if allow_provisional:
            if any(marker in text for marker in ["证据不足", "暂无法", "不能可靠", "不能完成", "不能判定", "等待MRI", "等待 MRI"]):
                return "evidence_insufficient"
            if self._has_positive_stage_context(
                text,
                stage_markers=["III", "III+", "ARCO 3", "ARCO III", "塌陷", "软骨下骨折", "新月"],
            ):
                return "III+"
            if self._has_positive_stage_context(
                text,
                stage_markers=["I/II", "ARCO II", "II 期", "II期", "二期", "硬化", "囊性"],
            ):
                return "I/II"
            if any(marker in text for marker in ["未见明确", "未见明显", "normal", "阴性", "无明确 ONFH"]):
                return "normal"
        if any(marker in text for marker in ["证据不足", "暂无法", "不能可靠", "需 MRI", "需MRI"]):
            return "evidence_insufficient"
        if any(marker in text for marker in ["III", "III+", "塌陷", "软骨下骨折", "新月"]):
            return "III+"
        if any(marker in text for marker in ["I/II", "ARCO II", "早期", "硬化", "囊性"]):
            return "I/II"
        if any(marker in text for marker in ["未见明确", "normal", "阴性"]):
            return "normal"
        return "evidence_insufficient"

    def _has_positive_stage_context(self, text: str, *, stage_markers: list[str]) -> bool:
        positive_cues = ["倾向", "支持", "符合", "考虑", "提示", "可见", "存在", "主要来自"]
        negative_cues = ["未提供", "未见", "无明确", "不能", "不足以", "缺少", "等待"]
        for marker in stage_markers:
            start = 0
            while True:
                index = text.find(marker, start)
                if index < 0:
                    break
                window = text[max(0, index - 24) : index + len(marker) + 24]
                if any(cue in window for cue in positive_cues) and not any(
                    cue in window for cue in negative_cues
                ):
                    return True
                start = index + len(marker)
        return False
