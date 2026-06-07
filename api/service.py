from __future__ import annotations

import json
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
        if patient_info.get("clinical_context") or patient_info.get("history") or patient_info.get("risk_factors"):
            return
        message = str(payload.get("patient_message") or "").strip()
        if not message:
            return
        markers = [
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
        ]
        lowered = message.lower()
        if not any(marker in lowered for marker in markers):
            return
        patient_info["clinical_context"] = message
        patient_info["clinical_context_source"] = "patient_message"

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
        matched_clues = self._match_supported_clues(payload)
        disease_key = explicit_disease_key or self._infer_disease_key(payload)
        vision_mode = explicit_vision_mode or self._infer_vision_mode(
            disease_key=disease_key,
            payload=payload,
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
        )
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
            initial_evidence_status=initial_evidence_status,
        )
        return SkillRoutingDecision(
            selected_skill=disease_key,
            selected_vision_mode=vision_mode,
            source=source,
            reason=reason,
            confidence=confidence,
            matched_clues=matched_clues,
            primary_hypothesis=disease_key,
            differential_skill_candidates=differential_candidates,
            clinical_hypotheses=clinical_hypotheses,
            skill_search_reason=skill_search_reason,
            initial_evidence_status=initial_evidence_status,
            routing_evidence_status=initial_evidence_status,
            skill_builder_action=skill_builder_action,
        ).to_dict()

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
        if skill.get("visual_protocol"):
            validation = VisualProtocolValidator().validate_skill(skill)
            if not validation.get("valid"):
                errors = "; ".join(str(error) for error in validation.get("errors", []))
                return False, f"local skill has invalid visual_protocol: {errors}"
            return True, "local skill has valid visual_protocol"
        if skill.get("imaging_evidence_protocol"):
            validation = self._validate_imaging_evidence_protocol(
                skill.get("imaging_evidence_protocol")
            )
            if not validation["valid"]:
                return False, f"local skill has invalid imaging_evidence_protocol: {'; '.join(validation['errors'])}"
            return True, "local skill has valid imaging_evidence_protocol"
        supporting_protocol_fields = [
            "quantitative_evidence_protocol",
            "differential_diagnosis_protocol",
            "clinical_context_protocol",
            "integrated_reasoning_protocol",
        ]
        if any(bool(skill.get(field)) for field in supporting_protocol_fields):
            return False, "local skill is missing imaging_evidence_protocol for visual evidence acquisition"
        return False, "local skill is missing required protocol"

    def _validate_imaging_evidence_protocol(self, protocol: Any) -> dict[str, Any]:
        errors: list[str] = []
        if not isinstance(protocol, dict) or not protocol:
            return {
                "valid": False,
                "errors": ["imaging_evidence_protocol is required"],
            }
        if not str(protocol.get("disease_target") or "").strip():
            errors.append("imaging_evidence_protocol.disease_target is required")
        finding_targets = protocol.get("finding_targets")
        if not isinstance(finding_targets, list) or not finding_targets:
            errors.append("imaging_evidence_protocol.finding_targets is required")
        else:
            for index, finding in enumerate(finding_targets):
                field = f"imaging_evidence_protocol.finding_targets[{index}]"
                if not isinstance(finding, dict):
                    errors.append(f"{field} must be an object")
                    continue
                if not str(finding.get("target") or "").strip():
                    errors.append(f"{field}.target is required")
                if not str(finding.get("execution_mode") or "").strip():
                    errors.append(f"{field}.execution_mode is required")
        return {"valid": not errors, "errors": errors}

    def _disease_name_for(self, disease_key: str) -> str:
        names = {
            "femoral_head_necrosis": "股骨头坏死",
            "diffuse_glioma_brats": "成人弥漫性胶质瘤",
            "idiopathic_pulmonary_fibrosis_hrct": "特发性肺纤维化",
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
    ) -> list[str]:
        if disease_key != "femoral_head_necrosis":
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

    def _clinical_hypotheses(
        self,
        *,
        disease_key: str | None,
        payload: dict[str, Any],
        differential_candidates: list[str],
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
            }
        ]
        for candidate in differential_candidates:
            hypotheses.append(
                {
                    "disease_key": candidate,
                    "role": "differential",
                    "status": "differential_candidate",
                    "reason": (
                        "Alternative explanation retained by the orchestrator; requires bounded "
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
