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

    def _normalize_image_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        image_paths = self._coerce_image_paths(normalized.get("image_paths"))
        if image_paths and not normalized.get("image_path"):
            normalized["image_path"] = image_paths[0]
        if image_paths:
            normalized["image_paths"] = image_paths
            patient_info = dict(normalized.get("patient_info") or {})
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
        return SkillRoutingDecision(
            selected_skill=disease_key,
            selected_vision_mode=vision_mode,
            source=source,
            reason=reason,
            confidence=confidence,
            matched_clues=matched_clues,
        ).to_dict()

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
