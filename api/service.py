from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agents.gaodoctor_agent import GaoDoctorAgent
from contracts.medical_contracts import SkillRoutingDecision
from llm.model_client import OpenAICompatibleModelClient
from llm.prompt_runner import PromptRunner
from memory.memory_manager import MemoryManager
from tools.alignment_planner import AlignmentPlanner
from tools.skill_builder_tool import SkillBuilderTool
from tools.visual_protocol_validator import VisualProtocolValidator
from tools.medsam2_segmentation_tool import (
    MissingMedSAM2BackendError,
    inspect_medsam2_configuration,
)


class MedScopeReadinessError(RuntimeError):
    """Raised when a selected workflow cannot run because a backend is not ready."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        routing_decision: dict[str, Any],
        readiness: dict[str, Any],
        action_items: list[str],
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.routing_decision = routing_decision
        self.readiness = readiness
        self.action_items = action_items

    def to_response(self) -> dict[str, Any]:
        return {
            "error": str(self),
            "error_type": self.error_type,
            "routing_decision": self.routing_decision,
            "medsam2_configuration": self.readiness,
            "action_items": list(self.action_items),
        }


class MedScopeService:
    """Stable boundary for CLI, API, or frontend callers."""

    SUPPORTED_VISION_MODES = {
        "ground_truth",
        "medsam2",
        "no_mask_skill",
        "real_vlm_validation",
    }
    SUPPORTED_SKILL_SELECTION_MODES = {
        "primary_only",
        "manual_secondary",
        "agent_auto_secondary",
    }

    def __init__(
        self,
        gaodoctor_agent: Any | None = None,
        skill_tool: SkillBuilderTool | None = None,
        alignment_planner: AlignmentPlanner | None = None,
    ) -> None:
        self.gaodoctor_agent = gaodoctor_agent or GaoDoctorAgent(
            prompt_runner=PromptRunner(model_client=OpenAICompatibleModelClient())
        )
        self.skill_tool = skill_tool or SkillBuilderTool()
        self.alignment_planner = alignment_planner or AlignmentPlanner()

    def handle_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_image_payload(payload)
        patient_message = payload.get("patient_message")
        if not patient_message:
            raise ValueError("patient_message is required")
        routing_decision = self._build_routing_decision(payload)
        if routing_decision.get("skill_builder_action") == "search_or_generate_skill":
            return self._build_skill_proposal_response(
                payload=payload,
                routing_decision=routing_decision,
            )
        alignment_plan = self._build_alignment_plan(payload, routing_decision)
        disease_key = routing_decision["selected_skill"]
        vision_mode = routing_decision["selected_vision_mode"]
        try:
            result = self.gaodoctor_agent.handle_message(
                patient_message=patient_message,
                image_path=payload.get("image_path"),
                patient_info=payload.get("patient_info") or {},
                case_id=payload.get("case_id"),
                disease_key=disease_key,
                vision_mode=vision_mode,
                mask_path=payload.get("mask_path"),
                segmentation_prompt=payload.get("segmentation_prompt"),
                hypothesis_validation_mode=bool(payload.get("hypothesis_validation_mode")),
                alignment_plan=alignment_plan,
                routing_decision=routing_decision,
            )
        except MissingMedSAM2BackendError as exc:
            raise MedScopeReadinessError(
                str(exc),
                error_type="medsam2_not_ready",
                routing_decision=routing_decision,
                readiness=inspect_medsam2_configuration(),
                action_items=[
                    "配置 MEDSAM2_COMMAND_TEMPLATE，且包含 {image_path}、{output_mask_path}、{prompt_json} 占位符。",
                    "如使用本地 MedSAM2 仓库，配置 MEDSAM2_REPO_PATH 并确认路径存在。",
                    "配置完成后可先运行 MedSAM2 smoke/readiness 测试，再重新提交病例。",
                ],
            ) from exc
        routing_decision = self._attach_secondary_skill_run_plan(
            payload=payload,
            routing_decision=routing_decision,
            primary_result=result,
        )
        result["routing_decision"] = routing_decision
        result["alignment_plan"] = alignment_plan
        result.setdefault("analysis_status", alignment_plan["analysis_status"])
        if alignment_plan.get("suspected_conditions"):
            result.setdefault("suspected_conditions", alignment_plan["suspected_conditions"])
        if alignment_plan.get("required_next_images"):
            result.setdefault("required_next_images", alignment_plan["required_next_images"])
        return self._attach_case_outputs(result)

    def _build_skill_proposal_response(
        self,
        *,
        payload: dict[str, Any],
        routing_decision: dict[str, Any],
    ) -> dict[str, Any]:
        disease_key = str(routing_decision.get("selected_skill") or "")
        proposal_skill = self.skill_tool.prepare_skill(
            disease_key=disease_key,
            disease_name=self._disease_name_for(disease_key),
            observations=self._proposal_observations(payload),
            persist=False,
        )
        return {
            "intent": "skill_proposal",
            "analysis_status": "skill_proposal_required",
            "reply_to_patient": (
                "当前本地没有可直接用于诊断的正式 skill。系统已生成候选 skill 草案，"
                "需要经过指南来源和人工审核后，才能进入受约束诊断流程。"
            ),
            "routing_decision": routing_decision,
            "skill_builder_proposal": {
                "skill_id": proposal_skill.get("skill_id"),
                "selected_skill": disease_key,
                "disease_name": proposal_skill.get("disease_name") or self._disease_name_for(disease_key),
                "skill_type": proposal_skill.get("skill_type"),
                "source_type": proposal_skill.get("source_type"),
                "evidence_level": proposal_skill.get("evidence_level"),
                "formal_update_allowed": False,
                "diagnosis_allowed": False,
                "review_required": True,
                "proposal_skill": proposal_skill,
            },
            "missing_evidence": [
                {
                    "field": "formal_guideline_skill",
                    "status": "missing",
                    "reason": "No local reviewed skill was available for the selected clinical hypothesis.",
                }
            ],
            "modality_limitations": [
                "未加载正式 guideline skill 前，不运行视觉取证和诊断推理。",
            ],
            "recommendation": [
                "先由 Skill Builder/Guideline Agent 搜索权威指南来源。",
                "将候选 skill 作为 proposal-only artifact 审核，不直接写入正式 skill 库。",
                "审核通过后再运行 VisionAgent 和 DiagnosisAgent。",
            ],
        }

    def _normalize_image_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        patient_info = dict(normalized.get("patient_info") or {})
        self._attach_prompt_clinical_context(normalized, patient_info)
        if patient_info:
            normalized["patient_info"] = patient_info
        image_paths = self._coerce_image_paths(normalized.get("image_paths"))
        if image_paths and not normalized.get("image_path"):
            normalized["image_path"] = image_paths[0]
        if image_paths:
            normalized["image_paths"] = image_paths
            if not patient_info.get("image_series"):
                patient_info["image_series"] = [
                    {
                        "image_id": f"image_{index + 1:03d}",
                        "image_path": image_path,
                        "view_hint": self._infer_view_hint(image_path),
                    }
                    for index, image_path in enumerate(image_paths)
                ]
            normalized["patient_info"] = patient_info
        return normalized

    def _attach_prompt_clinical_context(
        self,
        payload: dict[str, Any],
        patient_info: dict[str, Any],
    ) -> None:
        message = str(payload.get("patient_message") or "").strip()
        if not message:
            return
        if not patient_info.get("structured_clinical_context"):
            patient_info["structured_clinical_context"] = (
                self._extract_structured_clinical_context(message)
            )
        if patient_info.get("clinical_context") or patient_info.get("history") or patient_info.get("risk_factors"):
            return
        if not self._has_prompt_clinical_clue(message):
            return
        patient_info["clinical_context"] = message
        patient_info["clinical_context_source"] = "patient_message"

    def _has_prompt_clinical_clue(self, message: str) -> bool:
        markers = [
            "痛",
            "疼",
            "髋",
            "左",
            "右",
            "双侧",
            "走路",
            "活动",
            "负重",
            "加重",
            "个月",
            "月",
            "年",
            "激素",
            "饮酒",
            "酗酒",
            "外伤",
            "创伤",
            "血液病",
            "镰状",
            "自身免疫",
            "corticosteroid",
            "steroid",
            "alcohol",
            "trauma",
            "sickle",
            "autoimmune",
            "pain",
            "hip",
            "left",
            "right",
        ]
        lowered = message.lower()
        return any(marker in lowered for marker in markers)

    def _extract_structured_clinical_context(self, message: str) -> dict[str, Any]:
        fields: dict[str, dict[str, Any]] = {
            "symptoms": self._extract_symptoms(message),
            "duration": self._extract_duration(message),
            "laterality": self._extract_laterality(message),
            "pain_location": self._extract_pain_location(message),
            "aggravating_factors": self._extract_aggravating_factors(message),
            "steroid_use": self._extract_binary_context(
                message,
                aliases=["激素", "steroid", "corticosteroid"],
                risk_factor="corticosteroid_use",
            ),
            "alcohol_use": self._extract_binary_context(
                message,
                aliases=["饮酒", "酗酒", "alcohol"],
                risk_factor="alcohol_use",
            ),
            "trauma_history": self._extract_binary_context(
                message,
                aliases=["外伤", "创伤", "trauma"],
                risk_factor="trauma_history",
            ),
        }
        provided_risk_factors = [
            field["risk_factor"]
            for field in (
                fields["steroid_use"],
                fields["alcohol_use"],
                fields["trauma_history"],
            )
            if field.get("status") == "present" and field.get("risk_factor")
        ]
        missing_fields = [
            name for name, field in fields.items() if field.get("status") == "missing"
        ]
        return {
            "schema_version": "clinical_context_extraction.v1",
            "source": "patient_message",
            "source_text": message,
            "fields": fields,
            "provided_risk_factors": provided_risk_factors,
            "missing_fields": missing_fields,
            "risk_factor_role": "suspicion_modifier_only",
        }

    def _extract_symptoms(self, message: str) -> dict[str, Any]:
        lowered = message.lower()
        values: list[str] = []
        if ("髋" in message or "hip" in lowered) and any(token in message for token in ["痛", "疼"]):
            values.append("hip_pain")
        elif any(token in message for token in ["痛", "疼"]) or "pain" in lowered:
            values.append("pain")
        return {
            "status": "present" if values else "missing",
            "values": values,
        }

    def _extract_duration(self, message: str) -> dict[str, Any]:
        match = re.search(
            r"([一二两三四五六七八九十\d]+(?:个)?(?:天|日|周|星期|月|个月|年))",
            message,
        )
        if not match:
            return {"status": "missing", "value": "unknown"}
        return {"status": "present", "value": match.group(1)}

    def _extract_laterality(self, message: str) -> dict[str, Any]:
        lowered = message.lower()
        if any(token in message for token in ["双侧", "双髋"]) or "bilateral" in lowered:
            return {"status": "present", "value": "bilateral"}
        if "右" in message or "right" in lowered:
            return {"status": "present", "value": "right"}
        if "左" in message or "left" in lowered:
            return {"status": "present", "value": "left"}
        return {"status": "missing", "value": "unknown"}

    def _extract_pain_location(self, message: str) -> dict[str, Any]:
        lowered = message.lower()
        if "髋" in message or "hip" in lowered:
            return {"status": "present", "value": "hip"}
        if "腹股沟" in message or "groin" in lowered:
            return {"status": "present", "value": "groin"}
        if "大腿" in message or "thigh" in lowered:
            return {"status": "present", "value": "thigh"}
        if "膝" in message or "knee" in lowered:
            return {"status": "present", "value": "knee"}
        return {"status": "missing", "value": "unknown"}

    def _extract_aggravating_factors(self, message: str) -> dict[str, Any]:
        lowered = message.lower()
        values: list[str] = []
        if (
            any(token in message for token in ["走路", "行走", "活动", "负重"])
            or "walking" in lowered
            or "activity" in lowered
            or "weight-bearing" in lowered
        ) and ("加重" in message or "worse" in lowered or "aggravat" in lowered):
            values.append("walking_or_activity")
        return {
            "status": "present" if values else "missing",
            "values": values,
        }

    def _extract_binary_context(
        self,
        message: str,
        *,
        aliases: list[str],
        risk_factor: str,
    ) -> dict[str, Any]:
        lowered = message.lower()
        matched_alias = next(
            (alias for alias in aliases if alias.lower() in lowered),
            "",
        )
        if not matched_alias:
            return {"status": "missing", "value": "unknown", "risk_factor": risk_factor}
        if self._is_context_negated(message, matched_alias):
            return {"status": "absent", "value": False, "risk_factor": risk_factor}
        return {"status": "present", "value": True, "risk_factor": risk_factor}

    def _is_context_negated(self, message: str, alias: str) -> bool:
        escaped = re.escape(alias)
        negation_before = rf"(无|没有|否认|未|无明显|不).{{0,8}}{escaped}"
        negation_after = rf"{escaped}.{{0,6}}(阴性|否认)"
        return bool(re.search(negation_before, message, re.IGNORECASE)) or bool(
            re.search(negation_after, message, re.IGNORECASE)
        )

    def _coerce_image_paths(self, value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            candidates = [item.strip() for item in value.replace("\n", ",").split(",")]
        elif isinstance(value, list):
            candidates = [str(item).strip() for item in value]
        else:
            return []
        return [item for item in candidates if item]

    def _infer_view_hint(self, image_path: str) -> str:
        text = image_path.lower()
        if any(marker in text for marker in ["frog", "lauenstein", "蛙"]):
            return "frog_lateral"
        if any(marker in text for marker in ["lateral", "侧位"]):
            return "lateral"
        if any(marker in text for marker in ["ap", "pelvis", "正位", "卧"]):
            return "ap_pelvis"
        return "unknown"

    def _build_routing_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        explicit_disease_key = payload.get("disease_key")
        explicit_vision_mode = payload.get("vision_mode")
        if explicit_vision_mode:
            self._validate_vision_mode(str(explicit_vision_mode))
        skill_selection_mode = self._skill_selection_mode(payload)
        matched_clues = self._match_supported_clues(payload)
        disease_key = explicit_disease_key or self._infer_disease_key(payload)
        vision_mode = explicit_vision_mode or self._infer_vision_mode(
            disease_key=disease_key,
            payload=payload,
        )
        focused_primary_only = self._focused_primary_skill_only(
            payload=payload,
            explicit_disease_key=bool(explicit_disease_key),
        )
        manual_secondary_candidates = self._manual_secondary_skill_candidates(
            payload=payload,
            primary_skill=disease_key,
        )
        if explicit_disease_key or explicit_vision_mode:
            source = "explicit"
            confidence = 1.0
            reason = "Payload explicitly provided routing fields."
        elif disease_key:
            source = "auto"
            confidence = 0.75
            reason = "Matched supported disease or imaging clues in patient text, symptoms, or image path."
        else:
            source = "default"
            confidence = 0.2
            reason = "No supported disease-specific routing clues matched; using the default workflow."
        differential_candidates = self._differential_skill_candidates(
            disease_key=disease_key,
            payload=payload,
            focused_primary_only=focused_primary_only,
        )
        differential_ranking = self._rank_differential_skill_candidates(
            disease_key=disease_key,
            payload=payload,
            differential_candidates=differential_candidates,
        )
        display_differential_candidates = [
            item["disease_key"]
            for item in differential_ranking
            if item.get("display_group") == "strong_differential"
        ][:2]
        skill_builder_action, skill_builder_action_reason = self._skill_builder_action_for(
            disease_key
        )
        skill_search_reason = self._skill_search_reason(
            disease_key=disease_key,
            payload=payload,
            skill_builder_action=skill_builder_action,
            skill_builder_action_reason=skill_builder_action_reason,
        )
        initial_evidence_status = self._initial_evidence_status(
            disease_key=disease_key,
            payload=payload,
            differential_candidates=differential_candidates,
        )
        clinical_hypotheses = self._clinical_hypotheses(
            disease_key=disease_key,
            payload=payload,
            differential_candidates=differential_candidates,
            differential_ranking=differential_ranking,
            initial_evidence_status=initial_evidence_status,
        )
        return SkillRoutingDecision(
            selected_skill=disease_key,
            selected_vision_mode=vision_mode,
            source=source,
            reason=reason,
            confidence=confidence,
            matched_clues=matched_clues,
            skill_selection_mode=skill_selection_mode,
            manual_secondary_skill_candidates=manual_secondary_candidates,
            primary_hypothesis=disease_key,
            differential_skill_candidates=differential_candidates,
            differential_candidate_ranking=differential_ranking,
            display_differential_skill_candidates=display_differential_candidates,
            secondary_skill_run_plan=self._initial_secondary_skill_run_plan(
                skill_selection_mode=skill_selection_mode,
                focused_primary_only=focused_primary_only,
                manual_secondary_candidates=manual_secondary_candidates,
                has_differential_candidates=bool(differential_candidates),
            ),
            clinical_hypotheses=clinical_hypotheses,
            skill_search_reason=skill_search_reason,
            initial_evidence_status=initial_evidence_status,
            routing_evidence_status=initial_evidence_status,
            skill_builder_action=skill_builder_action,
        ).to_dict()

    def _skill_selection_mode(self, payload: dict[str, Any]) -> str:
        mode = str(payload.get("skill_selection_mode") or "primary_only").strip()
        if mode not in self.SUPPORTED_SKILL_SELECTION_MODES:
            supported = ", ".join(sorted(self.SUPPORTED_SKILL_SELECTION_MODES))
            raise ValueError(
                f"unsupported skill_selection_mode: {mode}. Supported modes: {supported}"
            )
        return mode

    def _manual_secondary_skill_candidates(
        self,
        *,
        payload: dict[str, Any],
        primary_skill: str | None,
    ) -> list[str]:
        raw = payload.get("manual_secondary_skill_candidates")
        if raw is None:
            raw = payload.get("secondary_skill_candidates")
        if not raw:
            return []
        if isinstance(raw, str):
            values = [item.strip() for item in re.split(r"[,，;；\n]", raw)]
        elif isinstance(raw, list):
            values = [str(item).strip() for item in raw]
        else:
            values = []
        candidates: list[str] = []
        for value in values:
            if not value or value == primary_skill or value in candidates:
                continue
            candidates.append(value)
        return candidates[:2]

    def _initial_secondary_skill_run_plan(
        self,
        *,
        skill_selection_mode: str,
        focused_primary_only: bool,
        manual_secondary_candidates: list[str],
        has_differential_candidates: bool,
    ) -> dict[str, Any]:
        if skill_selection_mode == "primary_only":
            return {
                "status": "not_applicable" if focused_primary_only else "not_triggered",
                "triggered": False,
                "reason": (
                    "explicit primary skill focus; secondary differential run was not requested"
                    if focused_primary_only
                    else "primary-only mode keeps secondary candidates display-only"
                ),
                "skill_selection_mode": skill_selection_mode,
                "candidates": [],
            }
        if skill_selection_mode == "manual_secondary":
            return {
                "status": "awaiting_manual_secondary_evidence"
                if manual_secondary_candidates
                else "not_triggered",
                "triggered": False,
                "reason": (
                    "manual secondary mode selected; waiting for primary result before preparing selected backup skills"
                    if manual_secondary_candidates
                    else "manual secondary mode selected but no backup skill was provided"
                ),
                "skill_selection_mode": skill_selection_mode,
                "candidates": [],
            }
        if focused_primary_only:
            return {
                "status": "not_applicable",
                "triggered": False,
                "reason": "explicit primary skill focus; agent-auto secondary run was not requested",
                "skill_selection_mode": skill_selection_mode,
                "candidates": [],
            }
        if not has_differential_candidates:
            return {
                "status": "not_applicable",
                "triggered": False,
                "reason": "no differential candidates were generated by routing",
                "skill_selection_mode": skill_selection_mode,
                "candidates": [],
            }
        return {
            "status": "awaiting_primary_evidence",
            "triggered": False,
            "reason": "secondary run is evaluated after the primary skill evidence bundle is available",
            "skill_selection_mode": skill_selection_mode,
            "candidates": [],
        }

    def _attach_secondary_skill_run_plan(
        self,
        *,
        payload: dict[str, Any],
        routing_decision: dict[str, Any],
        primary_result: dict[str, Any],
    ) -> dict[str, Any]:
        updated = dict(routing_decision)
        skill_selection_mode = str(updated.get("skill_selection_mode") or "primary_only")
        initial_plan = dict(updated.get("secondary_skill_run_plan") or {})
        if initial_plan.get("status") == "not_applicable":
            updated["secondary_skill_run_plan"] = initial_plan
            return updated
        if skill_selection_mode == "primary_only":
            updated["secondary_skill_run_plan"] = {
                "status": initial_plan.get("status") or "not_triggered",
                "triggered": False,
                "reason": initial_plan.get("reason") or "primary-only mode keeps secondary candidates display-only",
                "skill_selection_mode": skill_selection_mode,
                "candidates": [],
            }
            return updated
        if skill_selection_mode == "manual_secondary":
            candidates = list(updated.get("manual_secondary_skill_candidates") or [])
        else:
            candidates = list(updated.get("display_differential_skill_candidates") or [])
        if not candidates and skill_selection_mode != "manual_secondary":
            candidates = [
                item.get("disease_key")
                for item in updated.get("differential_candidate_ranking", [])
                if item.get("display_group") == "strong_differential"
            ]
        candidates = [str(candidate) for candidate in candidates if candidate][:2]
        if not candidates:
            updated["secondary_skill_run_plan"] = {
                "status": "not_applicable",
                "triggered": False,
                "reason": "no high-priority differential candidate is eligible for secondary run",
                "skill_selection_mode": skill_selection_mode,
                "candidates": [],
            }
            return updated
        if (
            skill_selection_mode == "agent_auto_secondary"
            and not self._primary_result_has_insufficient_evidence(primary_result)
        ):
            updated["secondary_skill_run_plan"] = {
                "status": "not_triggered",
                "triggered": False,
                "reason": "primary skill did not report insufficient evidence",
                "skill_selection_mode": skill_selection_mode,
                "candidates": [],
            }
            return updated

        candidate_plans = [
            self._secondary_skill_candidate_plan(
                candidate_key=candidate,
                primary_skill=str(updated.get("selected_skill") or ""),
                payload=payload,
            )
            for candidate in candidates
        ]
        updated["secondary_skill_run_plan"] = {
            "status": "manual_secondary_hypothesis_validation_ready"
            if skill_selection_mode == "manual_secondary"
            else "secondary_hypothesis_validation_ready",
            "triggered": True,
            "primary_skill": updated.get("selected_skill"),
            "trigger_reason": "manual_secondary_skill_selected"
            if skill_selection_mode == "manual_secondary"
            else "primary_evidence_insufficient",
            "skill_selection_mode": skill_selection_mode,
            "reason": (
                "Manual secondary skill was selected; backup skills can be used as bounded hypothesis validation."
                if skill_selection_mode == "manual_secondary"
                else "Primary skill evidence is insufficient; high-priority differential candidates "
                "can be used as bounded secondary hypothesis validation."
            ),
            "max_secondary_runs": 2,
            "candidates": candidate_plans,
        }
        return updated

    def _primary_result_has_insufficient_evidence(self, result: dict[str, Any]) -> bool:
        report = result.get("report") or {}
        status_values = [
            result.get("analysis_status"),
            (report.get("target_disease_assessment") or {}).get("evidence_status"),
            (report.get("integrated_reasoning_summary") or {}).get("evidence_status"),
        ]
        insufficient_statuses = {
            "insufficient",
            "insufficient_evidence",
            "requires_differential_review",
            "partial_evidence",
        }
        if any(str(status or "").lower() in insufficient_statuses for status in status_values):
            return True
        report_text = json.dumps(report, ensure_ascii=False)
        return any(marker in report_text for marker in ["证据不足", "不能确认", "不能仅凭"])

    def _secondary_skill_candidate_plan(
        self,
        *,
        candidate_key: str,
        primary_skill: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        skill_builder_action, skill_builder_reason = self._skill_builder_action_for(candidate_key)
        base = {
            "disease_key": candidate_key,
            "disease_name": self._disease_name_for(candidate_key),
            "primary_skill": primary_skill,
            "skill_builder_action": skill_builder_action,
            "skill_builder_reason": skill_builder_reason,
            "analysis_allowed": True,
        }
        if skill_builder_action == "load_existing_skill":
            return {
                **base,
                "action": "run_formal_secondary_skill",
                "review_status": "formal_guideline_skill",
                "use_scope": "evidence_bounded_secondary_diagnosis",
                "diagnosis_allowed": True,
            }
        proposal_skill = self.skill_tool.prepare_skill(
            disease_key=candidate_key,
            disease_name=self._disease_name_for(candidate_key),
            observations=self._proposal_observations(payload),
            persist=False,
        )
        return {
            **base,
            "action": "run_unreviewed_skill_hypothesis_validation",
            "review_status": "unreviewed",
            "use_scope": "hypothesis_validation_only",
            "diagnosis_allowed": False,
            "proposal_skill_id": proposal_skill.get("skill_id"),
            "proposal_skill_type": proposal_skill.get("skill_type"),
            "formal_skill_updated": False,
        }

    def _validate_vision_mode(self, vision_mode: str) -> None:
        if vision_mode not in self.SUPPORTED_VISION_MODES:
            supported = ", ".join(sorted(self.SUPPORTED_VISION_MODES))
            raise ValueError(
                f"unsupported vision_mode: {vision_mode}. Supported modes: {supported}"
            )

    def _skill_builder_action_for(self, disease_key: str | None) -> tuple[str, str]:
        if not disease_key:
            return "none", "No primary hypothesis selected."
        try:
            skill = self.skill_tool.load_guideline_skill(str(disease_key))
        except FileNotFoundError:
            return "search_or_generate_skill", "local skill was not found"
        protocol_ready, protocol_reason = self._skill_protocol_readiness(skill)
        if not protocol_ready:
            return "search_or_generate_skill", protocol_reason
        return "load_existing_skill", "local skill has required protocol"

    def _skill_protocol_readiness(self, skill: dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(skill, dict):
            return False, "local skill is not a valid object"
        validator = VisualProtocolValidator()
        has_full_evidence_protocol = bool(skill.get("imaging_evidence_protocol")) or any(
            bool(skill.get(field))
            for field in (
                "differential_diagnosis_protocol",
                "clinical_context_protocol",
                "integrated_reasoning_protocol",
            )
        )
        if has_full_evidence_protocol:
            evidence_validation = validator.validate_evidence_protocol(skill)
            if not evidence_validation.get("valid"):
                errors = "; ".join(str(error) for error in evidence_validation.get("errors", []))
                return False, f"local skill has invalid evidence_protocol: {errors}"
            return True, "local skill has valid evidence_protocol"
        if skill.get("quantitative_evidence_protocol"):
            quantitative_validation = validator.validate_quantitative_evidence_protocol(
                skill.get("quantitative_evidence_protocol")
            )
            if not quantitative_validation.get("valid"):
                errors = "; ".join(str(error) for error in quantitative_validation.get("errors", []))
                return False, f"local skill has invalid quantitative_evidence_protocol: {errors}"
        if skill.get("visual_protocol"):
            validation = validator.validate_skill(skill)
            if not validation.get("valid"):
                errors = "; ".join(str(error) for error in validation.get("errors", []))
                return False, f"local skill has invalid visual_protocol: {errors}"
            return True, "local skill has valid visual_protocol"
        return False, "local skill is missing required protocol"

    def _disease_name_for(self, disease_key: str) -> str:
        names = {
            "femoral_head_necrosis": "股骨头坏死",
            "diffuse_glioma_brats": "成人弥漫性胶质瘤",
            "idiopathic_pulmonary_fibrosis_hrct": "特发性肺纤维化",
            "osteoarthritis_or_degenerative_hip_disease": "骨关节炎或退行性髋关节病变",
            "developmental_dysplasia_related_degeneration": "发育性髋臼发育不良相关退变",
            "post_traumatic_change": "外伤后改变",
            "infection_or_inflammatory_arthritis": "感染或炎症性关节炎",
            "tumor_like_lesion": "肿瘤样骨病变",
        }
        return names.get(disease_key, disease_key.replace("_", " "))

    def _proposal_observations(self, payload: dict[str, Any]) -> list[str]:
        observations: list[str] = []
        message = str(payload.get("patient_message") or "").strip()
        if message:
            observations.append(message)
        symptoms = (payload.get("patient_info") or {}).get("symptoms", [])
        if isinstance(symptoms, str):
            if symptoms.strip():
                observations.append(symptoms.strip())
        else:
            observations.extend(str(symptom).strip() for symptom in symptoms if str(symptom).strip())
        image_path = payload.get("image_path")
        if image_path:
            observations.append(f"uploaded_image: {image_path}")
        return observations

    def _differential_skill_candidates(
        self,
        *,
        disease_key: str | None,
        payload: dict[str, Any],
        focused_primary_only: bool = False,
    ) -> list[str]:
        if disease_key != "femoral_head_necrosis":
            return []
        if focused_primary_only:
            return []
        text = self._routing_text(payload)
        candidates = [
            "osteoarthritis_or_degenerative_hip_disease",
            "post_traumatic_change",
            "developmental_dysplasia_related_degeneration",
        ]
        if any(marker in text for marker in ["感染", "炎症", "发热", "infection", "inflammatory"]):
            candidates.append("infection_or_inflammatory_arthritis")
        if any(marker in text for marker in ["肿瘤", "骨破坏", "tumor", "aggressive"]):
            candidates.append("tumor_like_lesion")
        return candidates

    def _focused_primary_skill_only(
        self,
        *,
        payload: dict[str, Any],
        explicit_disease_key: bool,
    ) -> bool:
        patient_info = payload.get("patient_info") or {}
        symptoms = patient_info.get("symptoms", [])
        symptoms_text = (
            symptoms
            if isinstance(symptoms, str)
            else " ".join(str(item) for item in symptoms)
        )
        text = " ".join(
            str(value)
            for value in [payload.get("patient_message", ""), symptoms_text]
        ).lower()
        if self._explicitly_requests_differential_review(text):
            return False
        if explicit_disease_key:
            return True
        has_fhn_focus = any(
            marker in text
            for marker in ["股骨头坏死", "fhn", "onfh", "avn"]
        )
        has_focus_language = any(
            marker in text
            for marker in ["怀疑", "是不是", "是否", "用", "根据", "skill", "诊断", "分析"]
        )
        return has_fhn_focus and has_focus_language

    def _explicitly_requests_differential_review(self, text: str) -> bool:
        return any(
            marker in text
            for marker in [
                "鉴别",
                "其他可能",
                "还有什么",
                "排除其他",
                "differential",
                "other causes",
            ]
        )

    def _rank_differential_skill_candidates(
        self,
        *,
        disease_key: str | None,
        payload: dict[str, Any],
        differential_candidates: list[str],
    ) -> list[dict[str, Any]]:
        if disease_key != "femoral_head_necrosis":
            return []
        text = self._routing_text(payload)
        structured = (payload.get("patient_info") or {}).get("structured_clinical_context") or {}
        fields = structured.get("fields") if isinstance(structured, dict) else {}
        trauma_status = (
            fields.get("trauma_history", {}).get("status")
            if isinstance(fields, dict)
            else None
        )
        denied_trauma = trauma_status == "absent" or self._is_context_negated(text, "外伤")
        has_trauma_clue = not denied_trauma and any(
            marker in text for marker in ["外伤", "创伤", "trauma", "骨折"]
        )
        has_degenerative_clue = any(
            marker in text for marker in ["关节间隙", "退变", "骨关节炎", "osteoarthritis"]
        )
        has_dysplasia_clue = any(
            marker in text for marker in ["发育不良", "髋臼", "dysplasia", "ddh"]
        )
        ranked = []
        for candidate in differential_candidates:
            if candidate == "osteoarthritis_or_degenerative_hip_disease":
                ranked.append(
                    {
                        "disease_key": candidate,
                        "priority": 1,
                        "display_group": "strong_differential",
                        "rank_reason": (
                            "Hip pain and X-ray are a common context for degenerative hip disease review."
                            if not has_degenerative_clue
                            else "Degenerative clues such as joint-space narrowing or degeneration were mentioned."
                        ),
                    }
                )
                continue
            if candidate == "post_traumatic_change":
                if denied_trauma:
                    ranked.append(
                        {
                            "disease_key": candidate,
                            "priority": 4,
                            "display_group": "low_priority",
                            "deprioritized_by": "denied_trauma_history",
                            "rank_reason": (
                                "Patient denied obvious trauma history; keep only as low-priority audit candidate."
                            ),
                        }
                    )
                elif has_trauma_clue:
                    ranked.append(
                        {
                            "disease_key": candidate,
                            "priority": 2,
                            "display_group": "strong_differential",
                            "rank_reason": "Trauma/fracture clues were mentioned.",
                        }
                    )
                else:
                    ranked.append(
                        {
                            "disease_key": candidate,
                            "priority": 3,
                            "display_group": "more_differential",
                            "rank_reason": "No explicit trauma clue; retained as conditional differential.",
                        }
                    )
                continue
            if candidate == "developmental_dysplasia_related_degeneration":
                ranked.append(
                    {
                        "disease_key": candidate,
                        "priority": 2 if has_dysplasia_clue else 3,
                        "display_group": "strong_differential"
                        if has_dysplasia_clue
                        else "more_differential",
                        "rank_reason": (
                            "Dysplasia/acetabular clues were mentioned."
                            if has_dysplasia_clue
                            else "Requires dysplasia or acetabular abnormality clues; retained as conditional differential."
                        ),
                    }
                )
                continue
            ranked.append(
                {
                    "disease_key": candidate,
                    "priority": 2,
                    "display_group": "strong_differential",
                    "rank_reason": "Specific symptom or imaging clue was mentioned.",
                }
            )
        return sorted(ranked, key=lambda item: (int(item.get("priority", 9)), item["disease_key"]))

    def _clinical_hypotheses(
        self,
        *,
        disease_key: str | None,
        payload: dict[str, Any],
        differential_candidates: list[str],
        differential_ranking: list[dict[str, Any]] | None = None,
        initial_evidence_status: str,
    ) -> list[dict[str, Any]]:
        if not disease_key:
            return []
        reason = "Matched symptom, image modality, body-part, or disease clues for evidence acquisition."
        if disease_key == "femoral_head_necrosis":
            reason = (
                "Matched hip pain symptom and hip/X-ray clues; this is a primary clinical hypothesis "
                "for evidence acquisition, not a diagnosis."
            )
        hypotheses = [
            {
                "disease_key": disease_key,
                "role": "primary",
                "status": initial_evidence_status,
                "reason": reason,
                "priority": 0,
                "display_group": "primary",
            }
        ]
        ranking_by_key = {
            item.get("disease_key"): item
            for item in differential_ranking or []
            if item.get("disease_key")
        }
        for candidate in differential_candidates:
            rank = ranking_by_key.get(candidate, {})
            hypotheses.append(
                {
                    "disease_key": candidate,
                    "role": "differential",
                    "status": "differential_candidate",
                    "priority": int(rank.get("priority", 3)),
                    "display_group": rank.get("display_group", "more_differential"),
                    "deprioritized_by": rank.get("deprioritized_by"),
                    "reason": (
                        rank.get("rank_reason")
                        or "Alternative explanation retained by the orchestrator; requires bounded "
                        "evidence review and does not replace the primary skill."
                    ),
                }
            )
        return hypotheses

    def _skill_search_reason(
        self,
        *,
        disease_key: str | None,
        payload: dict[str, Any],
        skill_builder_action: str | None = None,
        skill_builder_action_reason: str | None = None,
    ) -> str:
        if not disease_key:
            return "No primary disease skill matched; Skill Builder may search guideline sources if requested."
        if skill_builder_action == "search_or_generate_skill":
            return (
                f"Selected {disease_key} as a primary clinical hypothesis, but {skill_builder_action_reason or 'the local skill is not ready'}; "
                "Skill Builder should search guideline sources and create a proposal skill before evidence-bounded diagnosis."
            )
        if disease_key == "femoral_head_necrosis":
            text = self._routing_text(payload)
            side = "left hip pain" if any(marker in text for marker in ["左髋", "left hip"]) else "hip pain"
            if any(marker in text for marker in ["怀疑", "股骨头坏死", "fhn", "onfh", "avn"]):
                return (
                    "User raised femoral head necrosis as a concern; selected the existing FHN skill as a primary clinical hypothesis, "
                    "while keeping bounded differential candidates for evidence acquisition."
                )
            return (
                f"{side} with hip X-ray; user did not provide a confirmed diagnosis; "
                "FHN and degenerative, traumatic, and dysplasia-related causes should be considered before evidence-bounded diagnosis."
            )
        return "Selected primary disease skill as a clinical hypothesis; existing skill is loaded before any Skill Builder proposal."

    def _initial_evidence_status(
        self,
        *,
        disease_key: str | None,
        payload: dict[str, Any],
        differential_candidates: list[str] | None = None,
    ) -> str:
        if not disease_key:
            return "insufficient"
        if not payload.get("image_path") and not payload.get("image_paths"):
            return "insufficient"
        if self._requires_differential_review(disease_key=disease_key, payload=payload):
            return "requires_differential_review"
        return "requires_evidence_acquisition"

    def _requires_differential_review(self, *, disease_key: str | None, payload: dict[str, Any]) -> bool:
        if disease_key != "femoral_head_necrosis":
            return False
        text = self._routing_text(payload)
        return any(
            marker in text
            for marker in [
                "关节间隙",
                "退变",
                "骨关节炎",
                "osteoarthritis",
                "外伤",
                "trauma",
                "骨折",
                "感染",
                "炎症",
                "发热",
                "肿瘤",
                "骨破坏",
            ]
        )

    def _infer_disease_key(self, payload: dict[str, Any]) -> str | None:
        if self._match_glioma_clues(payload):
            return "diffuse_glioma_brats"
        if self._match_ipf_clues(payload):
            return "idiopathic_pulmonary_fibrosis_hrct"
        if self._match_femoral_head_clues(payload):
            return "femoral_head_necrosis"
        return None

    def _match_supported_clues(self, payload: dict[str, Any]) -> list[str]:
        return (
            self._match_glioma_clues(payload)
            or self._match_ipf_clues(payload)
            or self._match_femoral_head_clues(payload)
        )

    def _match_glioma_clues(self, payload: dict[str, Any]) -> list[str]:
        text = self._routing_text(payload)
        glioma_markers = [
            "胶质瘤",
            "脑肿瘤",
            "脑部",
            "brain",
            "glioma",
            "brats",
            "flair",
            ".nii",
        ]
        return [marker for marker in glioma_markers if marker in text]

    def _match_ipf_clues(self, payload: dict[str, Any]) -> list[str]:
        text = self._routing_text(payload)
        ipf_markers = [
            "特发性肺纤维化",
            "肺纤维化",
            "间质性肺病",
            "间质性肺疾病",
            "uip",
            "ipf",
            "hrct",
            "thin-section",
            "thin section",
            "chest ct",
            "胸部ct",
            "胸部 ct",
            "干咳",
            "气短",
        ]
        return [marker for marker in ipf_markers if marker in text]

    def _match_femoral_head_clues(self, payload: dict[str, Any]) -> list[str]:
        text = self._routing_text(payload)
        femoral_markers = [
            "股骨头",
            "髋",
            "hip",
            "xray",
            "x-ray",
            "x 光",
            "x光",
            "坏死",
            "fhn",
            "onfh",
            "avn",
        ]
        return [marker for marker in femoral_markers if marker in text]

    def _routing_text(self, payload: dict[str, Any]) -> str:
        symptoms = payload.get("patient_info", {}).get("symptoms", [])
        if isinstance(symptoms, str):
            symptoms_text = symptoms
        else:
            symptoms_text = " ".join(str(symptom) for symptom in symptoms)
        return " ".join(
            str(value)
            for value in [
                payload.get("patient_message", ""),
                payload.get("image_path", ""),
                " ".join(str(path) for path in self._coerce_image_paths(payload.get("image_paths"))),
                symptoms_text,
            ]
        ).lower()

    def _infer_vision_mode(self, disease_key: str | None, payload: dict[str, Any]) -> str | None:
        if disease_key == "diffuse_glioma_brats":
            if payload.get("mask_path"):
                return "ground_truth"
            return "medsam2"
        if disease_key == "femoral_head_necrosis" and payload.get("image_path"):
            return "no_mask_skill"
        return None

    def _build_alignment_plan(
        self,
        payload: dict[str, Any],
        routing_decision: dict[str, Any],
    ) -> dict[str, Any]:
        disease_key = routing_decision.get("selected_skill")
        disease_skill: dict[str, Any] = {}
        try:
            if disease_key:
                disease_skill = self.skill_tool.load_guideline_skill(str(disease_key))
        except FileNotFoundError:
            disease_skill = {}
        return self.alignment_planner.build_plan(
            payload=payload,
            routing_decision=routing_decision,
            disease_skill=disease_skill,
        )

    def _attach_case_outputs(self, result: dict[str, Any]) -> dict[str, Any]:
        report = result.get("report") or {}
        if "visual_input_contract" in report:
            result["visual_input_contract"] = report["visual_input_contract"]
        if "guideline_evidence" in report:
            result["guideline_evidence"] = report["guideline_evidence"]

        case_memory_path = result.get("case_memory_path")
        if not case_memory_path:
            return result
        path = Path(case_memory_path)
        if not path.exists():
            return result
        case_memory = json.loads(path.read_text(encoding="utf-8"))
        image_memory = case_memory.get("image_memory") or {}
        if "image_outputs" in image_memory:
            result["image_outputs"] = image_memory["image_outputs"]
        if "visual_features" in image_memory:
            result["visual_features"] = image_memory["visual_features"]
        if "visual_evidence_bundle" in image_memory:
            result["visual_evidence_bundle"] = image_memory["visual_evidence_bundle"]
        self._attach_memory_trace(result, path)
        result.setdefault(
            "visual_evidence_bundle",
            result.get("evidence_bundle", {})
            .get("image_evidence", {})
            .get("visual_evidence_bundle", {}),
        )
        self._attach_top_level_visual_facts(result)
        if result.get("evidence_bundle", {}).get("lesion_gallery"):
            result["lesion_gallery"] = result["evidence_bundle"]["lesion_gallery"]
        return result

    def _attach_top_level_visual_facts(self, result: dict[str, Any]) -> None:
        visual_bundle = result.get("visual_evidence_bundle") or {}
        structured_facts = visual_bundle.get("structured_visual_facts")
        if isinstance(structured_facts, list):
            result["structured_visual_facts"] = [dict(fact) for fact in structured_facts]

        usage = self._select_visual_fact_usage(result)
        if usage:
            result["visual_fact_usage"] = usage
            used = usage.get("used") if isinstance(usage.get("used"), list) else []
            excluded = (
                usage.get("excluded")
                if isinstance(usage.get("excluded"), list)
                else []
            )
            result["used_visual_facts"] = [dict(item) for item in used]
            result["excluded_visual_facts"] = [dict(item) for item in excluded]

    def _select_visual_fact_usage(self, result: dict[str, Any]) -> dict[str, Any]:
        candidates = [
            result.get("visual_fact_usage"),
            (result.get("report") or {}).get("visual_fact_usage"),
            (result.get("evidence_bundle") or {})
            .get("reasoning_evidence", {})
            .get("visual_fact_usage"),
            (result.get("memory_audit") or {}).get("visual_fact_usage"),
        ]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            used = candidate.get("used")
            excluded = candidate.get("excluded")
            if used or excluded or candidate.get("used_count") or candidate.get("excluded_count"):
                normalized = dict(candidate)
                normalized.setdefault("used", used if isinstance(used, list) else [])
                normalized.setdefault(
                    "excluded",
                    excluded if isinstance(excluded, list) else [],
                )
                normalized.setdefault("used_count", len(normalized["used"]))
                normalized.setdefault("excluded_count", len(normalized["excluded"]))
                return normalized
        return {}

    def _attach_memory_trace(self, result: dict[str, Any], case_memory_path: Path) -> None:
        if case_memory_path.parent.name != "cases":
            return
        case_id = result.get("case_id")
        if not case_id:
            return
        memory = MemoryManager(base_dir=case_memory_path.parent.parent)
        result["evidence_bundle"] = memory.get_evidence_bundle(case_id)
        result["memory_audit"] = memory.build_audit_summary(case_id)
        result["memory_replay"] = memory.build_case_replay(case_id)
        result["runtime_manifest"] = memory.build_runtime_manifest(case_id)
        result["runtime_manifest_path"] = result["runtime_manifest"].get("manifest_path")
        result["stop_hook_gate"] = memory.build_stop_hook_gate(case_id)
        result["stop_hook_gate_path"] = result["stop_hook_gate"].get("gate_path")
        result["self_evolving_queue"] = memory.build_self_evolving_queue(case_id)
        result["self_evolving_queue_path"] = result["self_evolving_queue"].get("queue_path")
        result["candidate_validation_gate"] = memory.build_candidate_validation_gate(case_id)
        result["candidate_validation_gate_path"] = result["candidate_validation_gate"].get(
            "gate_path"
        )
        result["runtime_gateway_trace"] = memory.build_runtime_gateway_trace(case_id)
        result["runtime_gateway_trace_path"] = result["runtime_gateway_trace"].get("trace_path")
        result["memory_audit_path"] = str(Path("output/fake/memory_audit") / f"{case_id}_audit.json")
