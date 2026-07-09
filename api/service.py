from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agents.gaodoctor_agent import GaoDoctorAgent
from agents.vision_agent import VisionAgent
from contracts.medical_contracts import KnowledgeRoutingDecision
from llm.model_client import OpenAICompatibleModelClient
from llm.prompt_runner import PromptRunner
from memory.memory_manager import MemoryManager
from tools.alignment_planner import AlignmentPlanner
from tools.guideline_knowledge_templates import apply_guideline_knowledge_template
from tools.knowledge_builder_tool import KnowledgeBuilderTool
from tools.visual_protocol_validator import VisualProtocolValidator
from tools.vlm_candidate_parser import parse_vlm_candidates
from tools.medsam2_segmentation_tool import (
    MissingMedSAM2BackendError,
    inspect_medsam2_configuration,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def normalize_guideline_knowledge_draft(
    *,
    knowledge: dict[str, Any],
    disease_key: str,
    source_documents: list[dict[str, Any]] | None = None,
    source_catalog_path: str = "data/guidelines/guideline_sources.json",
    promoted_from: str | None = None,
    promoted_by: str = "",
    promoted_at: str = "",
) -> dict[str, Any]:
    normalized = json.loads(json.dumps(knowledge, ensure_ascii=False))
    normalized["knowledge_type"] = "guideline_based"
    if normalized.get("evidence_level") in (None, "", "low", "none", "proposal_only", "unreviewed"):
        normalized["evidence_level"] = "high"
    normalized["source_type"] = (
        normalized.get("source_type")
        if normalized.get("source_type") not in (None, "", "internal_dataset_summary", "none")
        else "medical_guideline"
    )
    sources = list(source_documents or normalized.get("source_documents") or [])
    if not sources:
        raise ValueError("guideline knowledge draft requires source_documents")
    normalized["source_documents"] = sources
    normalized["source_priority"] = _guideline_source_priority(sources)
    normalized["guideline_source"] = {
        "source_catalog_path": source_catalog_path,
    }
    if _is_dataset_placeholder_source(normalized.get("source")):
        normalized["source"] = _guideline_source_summary(sources)
    if _is_dataset_placeholder_warning(normalized.get("warning")):
        normalized["warning"] = (
            "该 Knowledge 由 KnowledgeBuilder 基于可追溯医疗指南/规则来源生成，"
            "仍需医生审核后才能作为正式诊断规则使用。"
        )
    if normalized.get("path_type") in (None, "", "privileged_knowledge_discovery"):
        normalized["path_type"] = "guideline_aware_evidence_pipeline"
    normalized = apply_guideline_knowledge_template(normalized, disease_key=disease_key)
    extraction = dict(normalized.get("guideline_extraction") or {})
    extraction.setdefault("tool", "knowledgebuilder_guideline_source_sync")
    extraction["citations"] = list(extraction.get("citations") or sources)
    normalized["guideline_extraction"] = extraction
    if not normalized.get("guideline_documents"):
        normalized["guideline_documents"] = _guideline_documents_from_sources(
            disease_key=disease_key,
            knowledge=normalized,
            sources=sources,
        )

    citations = [citation for citation in extraction["citations"] if isinstance(citation, dict)]
    missing_url_count = len(citations) - len([citation for citation in citations if citation.get("url")])
    validation = VisualProtocolValidator().validate_knowledge(normalized)
    quality = dict(normalized.get("quality_control") or {})
    quality.update(
        {
            "citation_status": "verified" if missing_url_count == 0 else "needs_review",
            "citation_count": len(citations),
            "missing_url_count": missing_url_count,
            "source_priority_status": "available" if normalized["source_priority"] else "missing",
            "visual_protocol_status": validation["status"],
            "visual_protocol_errors": list(validation["errors"]),
            "visual_protocol_warnings": list(validation["warnings"]),
            "guideline_document_status": (
                "available" if normalized.get("guideline_documents") else "missing"
            ),
            "formal_knowledge_status": "needs_review",
            "review_status": "human_review_required",
            "medical_source_status": "present_unreviewed",
            "can_enter_formal_guideline_knowledge": False,
        }
    )
    if promoted_from:
        quality["promoted_from"] = promoted_from
    if promoted_at:
        quality["promoted_at"] = promoted_at
    if promoted_by:
        quality["promoted_by"] = promoted_by
    normalized["quality_control"] = quality
    return normalized


def _is_dataset_placeholder_source(source: Any) -> bool:
    text = str(source or "").strip().lower()
    if not text:
        return True
    return text in {
        "internal dataset statistical summary",
        "internal_dataset_summary",
        "current_case_knowledgebuilder_proposal",
        "none",
    }


def _is_dataset_placeholder_warning(warning: Any) -> bool:
    text = str(warning or "").strip().lower()
    if not text:
        return False
    return "数据总结" in text or "dataset" in text


def _guideline_source_summary(sources: list[dict[str, Any]]) -> str:
    return "; ".join(
        str(document.get("title") or document.get("source_id") or "guideline source")
        for document in sources
        if isinstance(document, dict)
    )


def _guideline_documents_from_sources(
    *,
    disease_key: str,
    knowledge: dict[str, Any],
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    disease_name = str(knowledge.get("disease_name") or disease_key)
    citations = [
        {
            key: source[key]
            for key in (
                "source_id",
                "title",
                "publisher",
                "url",
                "source_kind",
                "publication_year",
                "region",
                "evidence_note",
            )
            if source.get(key)
        }
        for source in sources
        if isinstance(source, dict)
    ]
    return [
        {
            "title": f"{disease_name} guideline synthesis",
            "source_id": f"{disease_key}_guideline_synthesis",
            "sections": [
                {
                    "heading": "source_documents",
                    "text": "; ".join(
                        str(source.get("title") or source.get("source_id") or "guideline source")
                        for source in sources
                    ),
                    "citations": citations,
                },
                {
                    "heading": "required_image_views",
                    "text": _default_guideline_section_text(
                        disease_key=disease_key,
                        heading="required_image_views",
                    ),
                    "citations": citations,
                },
                {
                    "heading": "visual_targets",
                    "text": _default_guideline_section_text(
                        disease_key=disease_key,
                        heading="visual_targets",
                    ),
                    "citations": citations,
                },
                {
                    "heading": "diagnostic_boundary",
                    "text": (
                        "This proposal can define evidence to review, but diagnosis_allowed=false "
                        "until doctor review validates the knowledge and evidence protocol."
                    ),
                    "citations": citations,
                },
            ],
        }
    ]


def _default_guideline_section_text(*, disease_key: str, heading: str) -> str:
    sections = {
        "osteoarthritis_or_degenerative_hip_disease": {
            "required_image_views": (
                "骨盆/髋关节 X 光正位；必要时侧位或蛙式位；当 X 光不能解释症状或需要评估软组织/骨髓改变时补充 MRI。"
            ),
            "visual_targets": (
                "anatomy: 髋关节间隙; 股骨头; 髋臼边缘; 软骨下骨\n"
                "lesion_features: 关节间隙狭窄; 骨赘; 软骨下硬化; 退变性股骨头形态不规则"
            ),
        },
        "post_traumatic_change": {
            "required_image_views": (
                "髋关节 X 光正位；外伤或疼痛持续时根据指南补充侧位、CT 或 MRI。"
            ),
            "visual_targets": (
                "anatomy: 股骨头; 股骨颈; 髋臼; 近端股骨\n"
                "lesion_features: 骨折线; 陈旧骨折畸形; 外伤后轮廓异常; 内固定或术后改变"
            ),
        },
        "developmental_dysplasia_related_degeneration": {
            "required_image_views": (
                "骨盆/髋关节 X 光正位；必要时侧位或其他体位评估髋臼覆盖和继发退变。"
            ),
            "visual_targets": (
                "anatomy: 髋臼覆盖; 股骨头位置; 关节间隙; 髋臼外上缘\n"
                "lesion_features: 髋臼发育浅; 股骨头外移; 半脱位; 继发退变"
            ),
        },
    }
    return sections.get(disease_key, {}).get(
        heading,
        "Use guideline sources to define disease-specific image views and visual targets before diagnosis.",
    )


def _guideline_source_priority(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def coerce_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    indexed_sources = list(enumerate(sources))
    priority_summary: list[dict[str, Any]] = []
    for _, source in sorted(
        indexed_sources,
        key=lambda item: (
            -coerce_int(item[1].get("source_priority")),
            -coerce_int(item[1].get("publication_year")),
            item[0],
        ),
    ):
        priority_summary.append(
            {
                key: source[key]
                for key in (
                    "source_id",
                    "title",
                    "publisher",
                    "url",
                    "source_kind",
                    "publication_year",
                    "region",
                    "source_priority",
                )
                if source.get(key)
            }
        )
    return priority_summary


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
        "no_mask_knowledge",
        "real_vlm_validation",
    }
    SUPPORTED_KNOWLEDGE_SELECTION_MODES = {
        "primary_only",
        "manual_secondary",
        "agent_auto_secondary",
    }
    SUPPORTED_EVIDENCE_PROTOCOL_MODES = {
        "finding_list_baseline",
        "quantitative_optional",
    }

    def __init__(
        self,
        gaodoctor_agent: Any | None = None,
        knowledge_tool: KnowledgeBuilderTool | None = None,
        alignment_planner: AlignmentPlanner | None = None,
        secondary_knowledge_proposal_dir: Path | str | None = None,
        secondary_visual_evidence_runner: Any | None = None,
    ) -> None:
        self.gaodoctor_agent = gaodoctor_agent or GaoDoctorAgent(
            prompt_runner=PromptRunner(model_client=OpenAICompatibleModelClient())
        )
        self.knowledge_tool = knowledge_tool or KnowledgeBuilderTool()
        self.alignment_planner = alignment_planner or AlignmentPlanner()
        self.secondary_knowledge_proposal_dir = Path(
            secondary_knowledge_proposal_dir
            or PROJECT_ROOT / "output" / "fake" / "secondary_knowledge_proposals"
        )
        self.secondary_visual_evidence_runner = (
            secondary_visual_evidence_runner or self._run_secondary_visual_evidence
        )

    def handle_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_image_payload(payload)
        patient_message = payload.get("patient_message")
        if not patient_message:
            raise ValueError("patient_message is required")
        routing_decision = self._build_routing_decision(payload)
        applicability = self._onfh_applicability_check(payload, routing_decision)
        if applicability:
            routing_decision["onfh_applicability"] = applicability
            if applicability.get("status") != "applicable":
                return self._build_onfh_not_applicable_response(
                    payload=payload,
                    routing_decision=routing_decision,
                    applicability=applicability,
                )
        if routing_decision.get("knowledge_builder_action") == "search_or_generate_knowledge":
            return self._build_knowledge_proposal_response(
                payload=payload,
                routing_decision=routing_decision,
            )
        alignment_plan = self._build_alignment_plan(payload, routing_decision)
        disease_key = routing_decision["selected_knowledge"]
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
        except RuntimeError as exc:
            if self._is_onfh_visual_candidate_failure(exc, routing_decision):
                applicability = self._build_onfh_visual_candidate_failure_applicability()
                routing_decision["onfh_applicability"] = applicability
                return self._build_onfh_not_applicable_response(
                    payload=payload,
                    routing_decision=routing_decision,
                    applicability=applicability,
                )
            raise
        result.setdefault("image_path", payload.get("image_path") or "")
        result.setdefault("patient_message", patient_message)
        result.setdefault("patient_info", payload.get("patient_info") or {})
        routing_decision = self._attach_secondary_knowledge_run_plan(
            payload=payload,
            routing_decision=routing_decision,
            primary_result=result,
        )
        result["routing_decision"] = routing_decision
        self._attach_secondary_knowledge_analysis(result, routing_decision)
        self._attach_evidence_protocol_mode_summary(result, routing_decision)
        result["alignment_plan"] = alignment_plan
        result.setdefault("analysis_status", alignment_plan["analysis_status"])
        if alignment_plan.get("suspected_conditions"):
            result.setdefault("suspected_conditions", alignment_plan["suspected_conditions"])
        if alignment_plan.get("required_next_images"):
            result.setdefault("required_next_images", alignment_plan["required_next_images"])
        result = self._attach_case_outputs(result)
        self._attach_diagnostic_confidence(result)
        self._attach_onfh_diagnostic_flow(result)
        return result

    def _onfh_applicability_check(
        self,
        payload: dict[str, Any],
        routing_decision: dict[str, Any],
    ) -> dict[str, Any] | None:
        if routing_decision.get("selected_knowledge") != "femoral_head_necrosis":
            return None
        text = self._routing_text(payload)
        image_text = " ".join(
            str(value)
            for value in [
                payload.get("image_path", ""),
                " ".join(str(path) for path in self._coerce_image_paths(payload.get("image_paths"))),
            ]
        ).lower()
        has_image = bool(payload.get("image_path") or self._coerce_image_paths(payload.get("image_paths")))
        hip_image_markers = [
            "hip",
            "pelvis",
            "femoral",
            "fhn",
            "onfh",
            "avn",
            "髋",
            "骨盆",
            "股骨头",
        ]
        non_hip_image_markers = [
            "brain",
            "brats",
            "flair",
            "glioma",
            "chest",
            "lung",
            "hrct",
            "ipf",
            "脑",
            "胶质瘤",
            "胸",
            "肺",
        ]
        hip_context_markers = [
            "髋",
            "股骨头",
            "骨盆",
            "hip",
            "femoral",
            "pelvis",
            "onfh",
            "fhn",
            "avn",
        ]
        hip_image_context_markers = [
            "髋关节",
            "髋部",
            "骨盆",
            "pelvis",
            "hip",
            "femoral head x",
            "股骨头 x",
            "股骨头x",
            "股骨头影像",
            "股骨头片",
        ]
        clinical_markers = [
            "疼",
            "痛",
            "活动",
            "走路",
            "负重",
            "跛行",
            "受限",
            "激素",
            "饮酒",
            "酗酒",
            "外伤",
            "创伤",
            "steroid",
            "corticosteroid",
            "alcohol",
            "trauma",
            "pain",
            "limp",
        ]
        supported_modality_markers = ["xray", "x-ray", "x 光", "x光", "radiograph", "mri", "磁共振"]
        unsupported_modality_markers = ["ct", "hrct", "超声", "ultrasound"]
        modality = self._onfh_requested_modality(payload, text)
        image_has_hip_marker = any(marker in image_text for marker in hip_image_markers)
        image_has_non_hip_marker = any(marker in image_text for marker in non_hip_image_markers)
        text_has_non_hip_context = any(marker in text for marker in non_hip_image_markers)
        text_has_hip_context = any(marker in text for marker in hip_context_markers)
        text_has_hip_image_context = any(marker in text for marker in hip_image_context_markers)
        text_has_clinical_context = any(marker in text for marker in clinical_markers)
        has_supported_modality = modality in {"xray", "mri"} or any(
            marker in text for marker in supported_modality_markers
        )
        has_unsupported_modality = modality == "unsupported" or any(
            marker in text for marker in unsupported_modality_markers
        )

        missing: list[str] = []
        if not has_image:
            missing.append("需要上传骨盆/髋关节 X 光或 MRI。")
        if (image_has_non_hip_marker or text_has_non_hip_context) and not (
            image_has_hip_marker or text_has_hip_image_context
        ):
            return {
                "status": "not_applicable",
                "reason": "uploaded_image_is_not_hip_related",
                "checks": {
                    "hip_related_image": False,
                    "supported_modality": has_supported_modality,
                    "clinical_context": text_has_clinical_context or text_has_hip_context,
                    "has_image": has_image,
                },
                "missing": ["当前上传影像不像骨盆/髋关节影像。"],
                "recommendation": [
                    "请上传骨盆正位、蛙式位或髋关节 MRI。",
                    "如果需要分析脑部、胸部或其他部位，应切换到对应专病系统。",
                ],
            }
        if has_unsupported_modality and not has_supported_modality:
            return {
                "status": "not_applicable",
                "reason": "unsupported_image_modality_for_onfh",
                "checks": {
                    "hip_related_image": image_has_hip_marker or text_has_hip_context,
                    "supported_modality": False,
                    "clinical_context": text_has_clinical_context or text_has_hip_context,
                    "has_image": has_image,
                },
                "missing": ["当前 ONFH MVP 主要支持 X 光和 MRI。"],
                "recommendation": [
                    "请上传髋关节 X 光或 MRI。",
                    "CT/超声等模态暂不作为当前演示主流程输入。",
                ],
            }
        if not (image_has_hip_marker or text_has_hip_context):
            missing.append("需要明确这是骨盆/髋关节相关影像或描述。")
        if not (text_has_clinical_context or text_has_hip_context):
            missing.append("请补充髋痛、活动受限、激素使用、饮酒或外伤等 ONFH 相关背景。")
        if not has_supported_modality:
            missing.append("请说明影像类型是 X 光还是 MRI。")
        if missing:
            return {
                "status": "insufficient_input",
                "reason": "missing_onfh_applicability_inputs",
                "checks": {
                    "hip_related_image": image_has_hip_marker or text_has_hip_context,
                    "supported_modality": has_supported_modality,
                    "clinical_context": text_has_clinical_context or text_has_hip_context,
                    "has_image": has_image,
                },
                "missing": missing,
                "recommendation": [
                    "请上传骨盆/髋关节 X 光或 MRI。",
                    "请补充髋部症状、活动受限和激素/饮酒/外伤等风险因素。",
                ],
            }
        return {
            "status": "applicable",
            "reason": "hip_related_input_matches_onfh_scope",
            "checks": {
                "hip_related_image": image_has_hip_marker or text_has_hip_context,
                "supported_modality": has_supported_modality,
                "clinical_context": text_has_clinical_context or text_has_hip_context,
                "has_image": has_image,
            },
            "modality": modality,
            "missing": [],
            "recommendation": [],
        }

    def _onfh_requested_modality(self, payload: dict[str, Any], text: str) -> str:
        patient_info = payload.get("patient_info") if isinstance(payload.get("patient_info"), dict) else {}
        raw = str(
            payload.get("image_modality")
            or patient_info.get("image_modality")
            or patient_info.get("modality")
            or ""
        ).strip().lower()
        if raw in {"xray", "x-ray", "x 光", "x光", "radiograph"}:
            return "xray"
        if raw in {"mri", "mr", "磁共振"}:
            return "mri"
        if raw in {"ct", "hrct", "ultrasound", "超声"}:
            return "unsupported"
        if any(marker in text for marker in ["xray", "x-ray", "x 光", "x光", "radiograph"]):
            return "xray"
        if any(marker in text for marker in ["ap_pelvis", "frog_lateral", "frog", "正位", "侧位", "蛙式"]):
            return "xray"
        if any(marker in text for marker in ["mri", "磁共振"]):
            return "mri"
        if any(marker in text for marker in ["ct", "hrct", "ultrasound", "超声"]):
            return "unsupported"
        return "unknown"

    def _build_onfh_not_applicable_response(
        self,
        *,
        payload: dict[str, Any],
        routing_decision: dict[str, Any],
        applicability: dict[str, Any],
    ) -> dict[str, Any]:
        status = str(applicability.get("status") or "not_applicable")
        not_applicable = status == "not_applicable"
        title = "不适用当前 ONFH 专病系统" if not_applicable else "当前输入不足以进行 ONFH 筛查"
        reply = (
            f"{title}。"
            + " ".join(str(item) for item in applicability.get("missing", []) if item)
        ).strip()
        recommendations = list(applicability.get("recommendation") or [])
        return {
            "intent": "diagnosis",
            "analysis_status": (
                "not_applicable_to_onfh_system" if not_applicable else "insufficient_onfh_input"
            ),
            "reply_to_patient": reply,
            "patient_message": payload.get("patient_message") or "",
            "image_path": payload.get("image_path") or "",
            "patient_info": payload.get("patient_info") or {},
            "routing_decision": routing_decision,
            "onfh_applicability": applicability,
            "report": {
                "重点结论": {
                    "疾病判断": title,
                    "发现的病灶/征象": [],
                    "疑似/确诊边界": reply,
                },
                "target_disease_assessment": {
                    "target_disease": "femoral_head_necrosis",
                    "evidence_status": status,
                    "conclusion": title,
                },
                "integrated_reasoning_summary": {
                    "evidence_status": status,
                    "conclusion": reply,
                },
                "适用性检查": applicability,
                "建议下一步": recommendations,
            },
            "missing_evidence": [
                {
                    "field": "onfh_applicability",
                    "status": status,
                    "reason": item,
                }
                for item in applicability.get("missing", [])
            ],
            "recommendation": recommendations,
        }

    def _is_onfh_visual_candidate_failure(
        self,
        exc: RuntimeError,
        routing_decision: dict[str, Any],
    ) -> bool:
        if routing_decision.get("selected_knowledge") != "femoral_head_necrosis":
            return False
        message = str(exc)
        return (
            "FHN no-mask visual pipeline did not complete" in message
            and "finding_segmentation_not_ready" in message
        )

    def _build_onfh_visual_candidate_failure_applicability(self) -> dict[str, Any]:
        return {
            "status": "not_applicable",
            "reason": "visual_pipeline_could_not_confirm_hip_onfh_candidate",
            "checks": {
                "hip_related_image": "unverified_by_visual_pipeline",
                "supported_modality": True,
                "clinical_context": True,
                "has_image": True,
            },
            "missing": [
                "视觉链路未能在当前图片中确认可用于股骨头坏死筛查的髋关节候选区域。",
            ],
            "recommendation": [
                "请上传骨盆正位、蛙式位或清晰髋关节 MRI。",
                "如果当前图片是胸部、脑部或其他部位影像，则不适用当前 ONFH 专病系统。",
            ],
        }

    def _build_knowledge_proposal_response(
        self,
        *,
        payload: dict[str, Any],
        routing_decision: dict[str, Any],
    ) -> dict[str, Any]:
        disease_key = str(routing_decision.get("selected_knowledge") or "")
        proposal_knowledge = self.knowledge_tool.prepare_knowledge(
            disease_key=disease_key,
            disease_name=self._disease_name_for(disease_key),
            observations=self._proposal_observations(payload),
            persist=False,
        )
        proposal_knowledge = self._ensure_guideline_proposal_knowledge(
            disease_key=disease_key,
            proposal_knowledge=proposal_knowledge,
        )
        return {
            "intent": "knowledge_proposal",
            "analysis_status": "knowledge_proposal_required",
            "reply_to_patient": (
                "当前本地没有可直接用于诊断的正式 knowledge。系统已生成候选 knowledge 草案，"
                "需要经过指南来源和人工审核后，才能进入受约束诊断流程。"
            ),
            "routing_decision": routing_decision,
            "knowledge_builder_proposal": {
                "knowledge_id": proposal_knowledge.get("knowledge_id"),
                "selected_knowledge": disease_key,
                "disease_name": proposal_knowledge.get("disease_name") or self._disease_name_for(disease_key),
                "knowledge_type": proposal_knowledge.get("knowledge_type"),
                "source_type": proposal_knowledge.get("source_type"),
                "evidence_level": proposal_knowledge.get("evidence_level"),
                "formal_update_allowed": False,
                "diagnosis_allowed": False,
                "review_required": True,
                "proposal_knowledge": proposal_knowledge,
            },
            "missing_evidence": [
                {
                    "field": "formal_guideline_knowledge",
                    "status": "missing",
                    "reason": "No local reviewed knowledge was available for the selected clinical hypothesis.",
                }
            ],
            "modality_limitations": [
                "未加载正式 guideline knowledge 前，不运行视觉取证和诊断推理。",
            ],
            "recommendation": [
                "先由 Knowledge Builder/Guideline Agent 搜索权威指南来源。",
                "将候选 knowledge 作为 proposal-only artifact 审核，不直接写入正式 knowledge 库。",
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
        knowledge_selection_mode = self._knowledge_selection_mode(payload)
        evidence_protocol_mode = self._evidence_protocol_mode(payload)
        matched_clues = self._match_supported_clues(payload)
        disease_key = explicit_disease_key or self._infer_disease_key(payload)
        vision_mode = explicit_vision_mode or self._infer_vision_mode(
            disease_key=disease_key,
            payload=payload,
        )
        focused_primary_only = self._focused_primary_knowledge_only(
            payload=payload,
            explicit_disease_key=bool(explicit_disease_key),
        )
        manual_secondary_candidates = self._manual_secondary_knowledge_candidates(
            payload=payload,
            primary_knowledge=disease_key,
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
        differential_candidates = self._differential_knowledge_candidates(
            disease_key=disease_key,
            payload=payload,
            focused_primary_only=focused_primary_only,
        )
        differential_ranking = self._rank_differential_knowledge_candidates(
            disease_key=disease_key,
            payload=payload,
            differential_candidates=differential_candidates,
        )
        display_differential_candidates = [
            item["disease_key"]
            for item in differential_ranking
            if item.get("display_group") == "strong_differential"
        ][:3]
        knowledge_builder_action, knowledge_builder_action_reason = self._knowledge_builder_action_for(
            disease_key
        )
        knowledge_search_reason = self._knowledge_search_reason(
            disease_key=disease_key,
            payload=payload,
            knowledge_builder_action=knowledge_builder_action,
            knowledge_builder_action_reason=knowledge_builder_action_reason,
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
        return KnowledgeRoutingDecision(
            selected_knowledge=disease_key,
            selected_vision_mode=vision_mode,
            source=source,
            reason=reason,
            confidence=confidence,
            matched_clues=matched_clues,
            knowledge_selection_mode=knowledge_selection_mode,
            evidence_protocol_mode=evidence_protocol_mode,
            manual_secondary_knowledge_candidates=manual_secondary_candidates,
            primary_hypothesis=disease_key,
            differential_knowledge_candidates=differential_candidates,
            differential_candidate_ranking=differential_ranking,
            display_differential_knowledge_candidates=display_differential_candidates,
            secondary_knowledge_run_plan=self._initial_secondary_knowledge_run_plan(
                knowledge_selection_mode=knowledge_selection_mode,
                focused_primary_only=focused_primary_only,
                manual_secondary_candidates=manual_secondary_candidates,
                has_differential_candidates=bool(differential_candidates),
            ),
            clinical_hypotheses=clinical_hypotheses,
            knowledge_search_reason=knowledge_search_reason,
            initial_evidence_status=initial_evidence_status,
            routing_evidence_status=initial_evidence_status,
            knowledge_builder_action=knowledge_builder_action,
        ).to_dict()

    def _knowledge_selection_mode(self, payload: dict[str, Any]) -> str:
        mode = str(payload.get("knowledge_selection_mode") or "primary_only").strip()
        if mode not in self.SUPPORTED_KNOWLEDGE_SELECTION_MODES:
            supported = ", ".join(sorted(self.SUPPORTED_KNOWLEDGE_SELECTION_MODES))
            raise ValueError(
                f"unsupported knowledge_selection_mode: {mode}. Supported modes: {supported}"
            )
        return mode

    def _evidence_protocol_mode(self, payload: dict[str, Any]) -> str:
        mode = str(payload.get("evidence_protocol_mode") or "finding_list_baseline").strip()
        if mode not in self.SUPPORTED_EVIDENCE_PROTOCOL_MODES:
            supported = ", ".join(sorted(self.SUPPORTED_EVIDENCE_PROTOCOL_MODES))
            raise ValueError(
                f"unsupported evidence_protocol_mode: {mode}. Supported modes: {supported}"
            )
        return mode

    def _manual_secondary_knowledge_candidates(
        self,
        *,
        payload: dict[str, Any],
        primary_knowledge: str | None,
    ) -> list[str]:
        raw = payload.get("manual_secondary_knowledge_candidates")
        if raw is None:
            raw = payload.get("secondary_knowledge_candidates")
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
            if not value or value == primary_knowledge or value in candidates:
                continue
            candidates.append(value)
        return candidates[:3]

    def _initial_secondary_knowledge_run_plan(
        self,
        *,
        knowledge_selection_mode: str,
        focused_primary_only: bool,
        manual_secondary_candidates: list[str],
        has_differential_candidates: bool,
    ) -> dict[str, Any]:
        if knowledge_selection_mode == "primary_only":
            return {
                "status": "not_applicable" if focused_primary_only else "not_triggered",
                "triggered": False,
                "reason": (
                    "explicit primary knowledge focus; secondary differential run was not requested"
                    if focused_primary_only
                    else "primary-only mode keeps secondary candidates display-only"
                ),
                "knowledge_selection_mode": knowledge_selection_mode,
                "candidates": [],
            }
        if knowledge_selection_mode == "manual_secondary":
            return {
                "status": "awaiting_manual_secondary_evidence"
                if manual_secondary_candidates
                else "not_triggered",
                "triggered": False,
                "reason": (
                    "manual secondary mode selected; waiting for primary result before preparing selected backup knowledge"
                    if manual_secondary_candidates
                    else "manual secondary mode selected but no backup knowledge was provided"
                ),
                "knowledge_selection_mode": knowledge_selection_mode,
                "candidates": [],
            }
        if focused_primary_only:
            return {
                "status": "not_applicable",
                "triggered": False,
                "reason": "explicit primary knowledge focus; agent-auto secondary run was not requested",
                "knowledge_selection_mode": knowledge_selection_mode,
                "candidates": [],
            }
        if not has_differential_candidates:
            return {
                "status": "not_applicable",
                "triggered": False,
                "reason": "no differential candidates were generated by routing",
                "knowledge_selection_mode": knowledge_selection_mode,
                "candidates": [],
            }
        return {
            "status": "awaiting_primary_evidence",
            "triggered": False,
            "reason": "secondary run is evaluated after the primary knowledge evidence bundle is available",
            "knowledge_selection_mode": knowledge_selection_mode,
            "candidates": [],
        }

    def _attach_secondary_knowledge_run_plan(
        self,
        *,
        payload: dict[str, Any],
        routing_decision: dict[str, Any],
        primary_result: dict[str, Any],
    ) -> dict[str, Any]:
        updated = dict(routing_decision)
        knowledge_selection_mode = str(updated.get("knowledge_selection_mode") or "primary_only")
        initial_plan = dict(updated.get("secondary_knowledge_run_plan") or {})
        if initial_plan.get("status") == "not_applicable":
            updated["secondary_knowledge_run_plan"] = initial_plan
            return updated
        if knowledge_selection_mode == "primary_only":
            updated["secondary_knowledge_run_plan"] = {
                "status": initial_plan.get("status") or "not_triggered",
                "triggered": False,
                "reason": initial_plan.get("reason") or "primary-only mode keeps secondary candidates display-only",
                "knowledge_selection_mode": knowledge_selection_mode,
                "candidates": [],
            }
            return updated
        if knowledge_selection_mode == "manual_secondary":
            candidates = list(updated.get("manual_secondary_knowledge_candidates") or [])
        else:
            candidates = list(updated.get("display_differential_knowledge_candidates") or [])
        if not candidates and knowledge_selection_mode != "manual_secondary":
            candidates = [
                item.get("disease_key")
                for item in updated.get("differential_candidate_ranking", [])
                if item.get("display_group") == "strong_differential"
            ]
        candidates = [str(candidate) for candidate in candidates if candidate][:3]
        if not candidates:
            updated["secondary_knowledge_run_plan"] = {
                "status": "not_applicable",
                "triggered": False,
                "reason": "no high-priority differential candidate is eligible for secondary run",
                "knowledge_selection_mode": knowledge_selection_mode,
                "candidates": [],
            }
            return updated
        if (
            knowledge_selection_mode == "agent_auto_secondary"
            and not self._primary_result_has_insufficient_evidence(primary_result)
        ):
            updated["secondary_knowledge_run_plan"] = {
                "status": "not_triggered",
                "triggered": False,
                "reason": "primary knowledge did not report insufficient evidence",
                "knowledge_selection_mode": knowledge_selection_mode,
                "candidates": [],
            }
            return updated

        candidate_plans = [
            self._secondary_knowledge_candidate_plan(
                candidate_key=candidate,
                primary_knowledge=str(updated.get("selected_knowledge") or ""),
                payload=payload,
                knowledge_selection_mode=knowledge_selection_mode,
            )
            for candidate in candidates
        ]
        updated["secondary_knowledge_run_plan"] = {
            "status": "manual_secondary_hypothesis_validation_ready"
            if knowledge_selection_mode == "manual_secondary"
            else "secondary_hypothesis_validation_ready",
            "triggered": True,
            "primary_knowledge": updated.get("selected_knowledge"),
            "trigger_reason": "manual_secondary_knowledge_selected"
            if knowledge_selection_mode == "manual_secondary"
            else "primary_evidence_insufficient",
            "knowledge_selection_mode": knowledge_selection_mode,
            "reason": (
                "Manual secondary knowledge was selected; backup knowledge can be used as bounded hypothesis validation."
                if knowledge_selection_mode == "manual_secondary"
                else "Primary knowledge evidence is insufficient; high-priority differential candidates "
                "can be used as bounded secondary hypothesis validation."
            ),
            "max_secondary_runs": 3,
            "candidates": candidate_plans,
        }
        return updated

    def _attach_secondary_knowledge_analysis(
        self,
        result: dict[str, Any],
        routing_decision: dict[str, Any],
    ) -> None:
        plan = routing_decision.get("secondary_knowledge_run_plan") or {}
        candidates = plan.get("candidates") if isinstance(plan, dict) else []
        if not isinstance(candidates, list) or not candidates:
            return
        analysis_items = [
            self._secondary_knowledge_analysis_item(candidate, primary_result=result)
            for candidate in candidates
            if isinstance(candidate, dict)
        ]
        if not analysis_items:
            return
        result["secondary_knowledge_analysis"] = analysis_items
        report = result.setdefault("report", {})
        if isinstance(report, dict):
            report["备用 Knowledge 复查结果"] = analysis_items

    def _attach_evidence_protocol_mode_summary(
        self,
        result: dict[str, Any],
        routing_decision: dict[str, Any],
    ) -> None:
        mode = str(routing_decision.get("evidence_protocol_mode") or "finding_list_baseline")
        quantitative_requested = mode == "quantitative_optional"
        summary = {
            "mode": mode,
            "mode_label": (
                "可选量化指标协议"
                if quantitative_requested
                else "默认病灶征象 finding-list baseline"
            ),
            "quantitative_protocol_requested": quantitative_requested,
            "quantitative_protocol_default_enabled": False,
            "doctor_facing_summary": (
                "本次已主动加入可选量化指标协议；系统会把塌陷程度、坏死面积比例、"
                "骨小梁紊乱等作为待测量证据需求，但只有在 ROI/轮廓/测量质量门可靠时才可使用。"
                if quantitative_requested
                else "本次默认只使用病灶征象 finding-list baseline：优先检查硬化带、囊性变、"
                "软骨下骨折/新月征等可由现有 mask 标注支持的病灶征象。"
            ),
            "safety_boundary": (
                "可选量化暂不默认启用；当前没有经过质量门验证的量化输出时，不能把量化协议当作诊断证据。"
                if quantitative_requested
                else "当前不请求量化指标；不会因为新版 knowledge 存在量化协议就默认要求视觉系统输出塌陷角度、"
                "骨小梁紊乱程度或坏死面积比例。"
            ),
        }
        result["evidence_protocol_mode_summary"] = summary
        report = result.setdefault("report", {})
        if isinstance(report, dict):
            report["证据提取范围"] = summary

    def _secondary_knowledge_analysis_item(
        self,
        candidate: dict[str, Any],
        *,
        primary_result: dict[str, Any],
    ) -> dict[str, Any]:
        diagnosis_allowed = bool(candidate.get("diagnosis_allowed"))
        unreviewed = candidate.get("review_status") == "unreviewed"
        analysis_mode = (
            "hypothesis_validation_only"
            if unreviewed or not diagnosis_allowed
            else "evidence_bounded_secondary_diagnosis"
        )
        knowledge_builder_status = (
            "formal_knowledge_loaded"
            if candidate.get("knowledge_builder_action") == "load_existing_knowledge"
            else "proposal_prepared"
        )
        workflow_stage = (
            "formal_secondary_knowledge_ready"
            if knowledge_builder_status == "formal_knowledge_loaded"
            else "unreviewed_knowledge_hypothesis_validation_completed"
        )
        secondary_visual = self._run_secondary_candidate_visual_pass(
            candidate=candidate,
            primary_result=primary_result,
        )
        differential_review = self._secondary_differential_review(
            candidate=candidate,
            primary_result=primary_result,
            secondary_visual=secondary_visual,
        )
        return {
            "disease_key": candidate.get("disease_key"),
            "disease_name": candidate.get("disease_name"),
            "analysis_mode": analysis_mode,
            "workflow_stage": workflow_stage,
            "candidate_status": candidate.get("candidate_status"),
            "knowledge_builder_status": knowledge_builder_status,
            "knowledge_builder_progress": candidate.get("knowledge_builder_progress") or [],
            "selected_by_user": bool(candidate.get("selected_by_user")),
            "review_status": candidate.get("review_status"),
            "proposal_knowledge_id": candidate.get("proposal_knowledge_id"),
            "knowledge_builder_proposal_detail": candidate.get("knowledge_builder_proposal_detail")
            or {},
            "guideline_evidence_summary": candidate.get("guideline_evidence_summary") or {},
            "secondary_visual_status": secondary_visual.get("status"),
            "secondary_visual_protocol_status": secondary_visual.get("visual_protocol_status"),
            "secondary_visual_evidence_bundle": secondary_visual.get("visual_evidence_bundle") or {},
            "secondary_visual_outputs": secondary_visual.get("image_outputs") or {},
            "differential_review": differential_review,
            "evidence_boundary": (
                "未审核 Knowledge 仅用于 hypothesis validation，不能作为正式确诊依据。"
                if analysis_mode == "hypothesis_validation_only"
                else "正式 Knowledge 可进入受证据约束的二级诊断复核。"
            ),
            "finding": (
                "KnowledgeBuilder 已基于可追溯指南/规则来源生成未审核备用 Knowledge，并对当前病例证据完成 "
                "hypothesis validation 级复查；当前结果用于提示需要补充哪些证据，不能覆盖主分析结论。"
            ),
            "diagnosis_allowed": diagnosis_allowed,
            "formal_knowledge_updated": bool(candidate.get("formal_knowledge_updated")),
        }

    def _run_secondary_candidate_visual_pass(
        self,
        *,
        candidate: dict[str, Any],
        primary_result: dict[str, Any],
    ) -> dict[str, Any]:
        disease_key = str(candidate.get("disease_key") or "")
        try:
            disease_knowledge = self._secondary_runtime_knowledge(candidate)
            payload = self._secondary_visual_payload(primary_result)
            visual_result = self.secondary_visual_evidence_runner(
                image_path=payload["image_path"],
                patient_message=payload["patient_message"],
                patient_info=payload["patient_info"],
                disease_key=disease_key,
                disease_knowledge=disease_knowledge,
                vision_mode=(primary_result.get("routing_decision") or {}).get("selected_vision_mode"),
            )
            return self._normalize_secondary_visual_result(
                disease_key=disease_key,
                visual_result=visual_result,
            )
        except Exception as exc:
            return {
                "status": "failed",
                "visual_protocol_status": "secondary_visual_failed",
                "error": str(exc),
                "visual_evidence_bundle": {},
                "image_outputs": {},
            }

    def _secondary_runtime_knowledge(self, candidate: dict[str, Any]) -> dict[str, Any]:
        if isinstance(candidate.get("proposal_knowledge"), dict):
            return candidate["proposal_knowledge"]
        disease_key = str(candidate.get("disease_key") or "")
        if candidate.get("knowledge_builder_status") == "formal_knowledge_loaded":
            return self.knowledge_tool.load_guideline_knowledge(disease_key)
        detail = candidate.get("knowledge_builder_proposal_detail") or {}
        artifact_path = detail.get("proposal_artifact_path")
        if artifact_path and Path(str(artifact_path)).exists():
            artifact = json.loads(Path(str(artifact_path)).read_text(encoding="utf-8"))
            proposal_knowledge = artifact.get("proposal_knowledge")
            if isinstance(proposal_knowledge, dict):
                return proposal_knowledge
        raise FileNotFoundError(f"secondary runtime knowledge unavailable: {disease_key}")

    def _run_secondary_visual_evidence(
        self,
        *,
        image_path: str,
        patient_message: str,
        patient_info: dict[str, Any],
        disease_key: str,
        disease_knowledge: dict[str, Any],
        vision_mode: str | None,
    ) -> dict[str, Any]:
        if not image_path:
            raise ValueError("secondary visual evidence requires image_path")
        if vision_mode == "real_vlm_validation" and getattr(self.gaodoctor_agent, "prompt_runner", None):
            return self._run_secondary_vlm_visual_evidence(
                image_path=image_path,
                patient_message=patient_message,
                patient_info=patient_info,
                disease_key=disease_key,
                disease_knowledge=disease_knowledge,
            )
        visual_agent = VisionAgent()
        if disease_knowledge.get("visual_protocol") or disease_knowledge.get("imaging_evidence_protocol"):
            visual_result = visual_agent.analyze_with_visual_protocol(
                image_path=image_path,
                disease_knowledge=disease_knowledge,
            )
        else:
            visual_result = visual_agent.analyze_image(
                image_path=image_path,
                disease_knowledge=disease_knowledge,
            )
        return {
            "status": "ok",
            **visual_result,
        }

    def _run_secondary_vlm_visual_evidence(
        self,
        *,
        image_path: str,
        patient_message: str,
        patient_info: dict[str, Any],
        disease_key: str,
        disease_knowledge: dict[str, Any],
    ) -> dict[str, Any]:
        prompt_runner = getattr(self.gaodoctor_agent, "prompt_runner", None)
        if prompt_runner is None:
            raise RuntimeError("secondary VLM visual evidence requires prompt_runner")
        image_series = self._secondary_image_series(
            image_path=image_path,
            patient_info=patient_info,
        )
        user_payload = {
            "patient_message": patient_message,
            "disease_key": disease_key,
            "disease_name": disease_knowledge.get("disease_name") or self._disease_name_for(disease_key),
            "image_paths": [item["image_path"] for item in image_series],
            "image_series": image_series,
            "visual_protocol": disease_knowledge.get("visual_protocol") or {},
            "imaging_evidence_protocol": disease_knowledge.get("imaging_evidence_protocol") or {},
            "instruction": (
                "Use only this candidate knowledge's visual protocol. Return JSON with a findings list. "
                "Do not diagnose. Do not invent findings not visible in the image."
            ),
        }
        response = prompt_runner.run(
            task="secondary_visual_evidence_extraction",
            system_prompt=(
                "You are a visual evidence extractor for a secondary differential knowledge. "
                "Look for the requested protocol findings only. Return compact JSON."
            ),
            user_payload=user_payload,
        )
        raw_payload = self._parse_secondary_vlm_response(response)
        primary = image_series[0]
        evidence_items = parse_vlm_candidates(
            raw_payload,
            image_id=str(primary["image_id"]),
            view_hint=str(primary.get("view_hint") or "unknown"),
            source_image_path=str(primary.get("image_path") or image_path),
            imaging_evidence_protocol=disease_knowledge.get("imaging_evidence_protocol"),
        )
        bundle = self._secondary_bundle_from_vlm_items(
            disease_key=disease_key,
            evidence_items=evidence_items,
        )
        return {
            "status": "ok",
            "visual_evidence_bundle": bundle,
            "image_outputs": {
                "original_image_path": image_path,
                "mask_path": "not_generated",
                "overlay_path": "not_generated",
            },
        }

    def _secondary_image_series(
        self,
        *,
        image_path: str,
        patient_info: dict[str, Any],
    ) -> list[dict[str, str]]:
        series = patient_info.get("image_series") if isinstance(patient_info, dict) else None
        normalized = [
            {
                "image_id": str(item.get("image_id") or f"image_{index + 1:03d}"),
                "image_path": str(item.get("image_path") or ""),
                "view_hint": str(item.get("view_hint") or "unknown"),
            }
            for index, item in enumerate(series or [])
            if isinstance(item, dict) and item.get("image_path")
        ]
        if normalized:
            return normalized
        return [{"image_id": "image_001", "image_path": image_path, "view_hint": "unknown"}]

    def _parse_secondary_vlm_response(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        text = str(response).strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        for block in text.split("```"):
            block = block.strip()
            if block.lower().startswith("json"):
                block = block[4:].strip()
            if not block:
                continue
            try:
                parsed = json.loads(block)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        raise ValueError("secondary VLM response was not a JSON object")

    def _secondary_bundle_from_vlm_items(
        self,
        *,
        disease_key: str,
        evidence_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        findings = []
        present = []
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            target = str(item.get("target") or "")
            if not target:
                continue
            if item.get("diagnosis_usable"):
                present.append(target)
            observation = item.get("visual_observation") or {}
            findings.append(
                {
                    "finding_id": item.get("finding_id") or target,
                    "target": target,
                    "display_name": self._finding_name_for(target),
                    "image_id": item.get("image_id"),
                    "view_hint": item.get("view_hint"),
                    "source_image_path": item.get("source_image_path"),
                    "status": observation.get("status", "candidate_present"),
                    "description": observation.get("rationale") or observation.get("reason"),
                    "measurements": item.get("measurements") or {},
                    "quality": item.get("quality") or {},
                    "diagnosis_usable": bool(item.get("diagnosis_usable")),
                    "diagnosis_usable_level": item.get("diagnosis_usable_level"),
                    "limitations": list(item.get("limitations") or []),
                }
            )
        return {
            "schema_version": "secondary_visual_evidence_bundle.v1",
            "disease_target": disease_key,
            "present_findings": list(dict.fromkeys(present)),
            "findings": findings,
            "evidence_items": evidence_items,
            "numeric_evidence": {
                "finding_count": len(findings),
                "candidate_support_count": len(set(present)),
            },
        }

    def _secondary_visual_payload(self, primary_result: dict[str, Any]) -> dict[str, Any]:
        routing = primary_result.get("routing_decision") or {}
        patient_info = dict(primary_result.get("patient_info") or {})
        image_path = (
            primary_result.get("image_path")
            or (primary_result.get("image_outputs") or {}).get("original_image_path")
            or routing.get("image_path")
            or ""
        )
        if not image_path:
            visual_bundle = primary_result.get("visual_evidence_bundle") or {}
            for item in visual_bundle.get("findings") or []:
                if isinstance(item, dict) and item.get("source_image_path"):
                    image_path = str(item["source_image_path"])
                    break
        return {
            "image_path": image_path,
            "patient_message": str(primary_result.get("patient_message") or ""),
            "patient_info": patient_info,
        }

    def _normalize_secondary_visual_result(
        self,
        *,
        disease_key: str,
        visual_result: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(visual_result, dict):
            raise ValueError("secondary visual runner did not return a dict")
        bundle = visual_result.get("visual_evidence_bundle")
        if not isinstance(bundle, dict):
            bundle = self._visual_result_to_secondary_bundle(
                disease_key=disease_key,
                visual_result=visual_result,
            )
        if "disease_target" not in bundle:
            bundle = {**bundle, "disease_target": disease_key}
        return {
            "status": str(visual_result.get("status") or "ok"),
            "visual_protocol_status": "executed_with_candidate_knowledge",
            "visual_evidence_bundle": bundle,
            "image_outputs": visual_result.get("image_outputs") or {},
        }

    def _visual_result_to_secondary_bundle(
        self,
        *,
        disease_key: str,
        visual_result: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = visual_result.get("visual_evidence") or {}
        findings = evidence.get("findings") if isinstance(evidence, dict) else []
        evidence_items = evidence.get("evidence_items") if isinstance(evidence, dict) else []
        present = []
        for item in findings or []:
            if isinstance(item, dict) and item.get("target"):
                present.append(str(item["target"]))
        return {
            "schema_version": "secondary_visual_evidence_bundle.v1",
            "disease_target": disease_key,
            "present_findings": list(dict.fromkeys(present)),
            "findings": findings if isinstance(findings, list) else [],
            "evidence_items": evidence_items if isinstance(evidence_items, list) else [],
            "numeric_evidence": {
                "finding_count": len(findings) if isinstance(findings, list) else 0,
            },
        }

    def _secondary_differential_review(
        self,
        *,
        candidate: dict[str, Any],
        primary_result: dict[str, Any],
        secondary_visual: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        disease_key = str(candidate.get("disease_key") or "")
        disease_name = str(candidate.get("disease_name") or self._disease_name_for(disease_key))
        expected = self._secondary_expected_evidence(disease_key)
        secondary_observations = self._secondary_visual_observation_summary(
            secondary_visual or {}
        )
        observations = secondary_observations or self._primary_observation_summary(primary_result)
        observation_source_text = (
            "按备用 Knowledge 自己的视觉协议复查"
            if secondary_observations
            else "沿用主分析 evidence bundle 复查"
        )
        observation_text = "；".join(observations) if observations else "当前没有形成足够稳定的备用疾病专属影像证据。"
        weak_support = self._secondary_weak_supporting_evidence(
            disease_key=disease_key,
            observations=observations,
        )
        missing = expected[:3]
        confidence = self._secondary_confidence(
            disease_key=disease_key,
            disease_name=disease_name,
            weak_support=weak_support,
            missing=missing,
        )
        report_sentence = (
            f"针对{disease_name}：{observation_source_text}，当前可见/已抽取信息为 {observation_text}。"
            f"{'其中 ' + '、'.join(weak_support) + ' 可作为弱提示；' if weak_support else ''}"
            f"当前证据支持度为{confidence['confidence_label']}；"
            f"仍缺少 { '、'.join(missing) } 等针对性证据，因此只能作为备用复查方向，不能替代医生诊断。"
        )
        return {
            "review_title": f"{disease_name} 备用复查判断",
            "current_observation_summary": observation_text,
            "expected_evidence_to_check": expected,
            "weak_supporting_evidence": weak_support,
            "missing_required_evidence": missing,
            "report_sentence": report_sentence,
            "diagnosis_allowed": bool(candidate.get("diagnosis_allowed")),
            "diagnostic_confidence": confidence,
        }

    def _secondary_visual_observation_summary(self, secondary_visual: dict[str, Any]) -> list[str]:
        if secondary_visual.get("status") != "ok":
            return []
        bundle = secondary_visual.get("visual_evidence_bundle") or {}
        observations: list[str] = []
        for item in bundle.get("findings") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("display_name") or self._finding_name_for(str(item.get("target") or ""))
            status = item.get("status") or item.get("description") or item.get("evidence_text")
            if name:
                observations.append(f"{name}{f'：{status}' if status else ''}")
        for item in bundle.get("structured_visual_facts") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("display_name") or self._finding_name_for(str(item.get("target") or ""))
            status = item.get("status") or item.get("summary_text")
            if name:
                observations.append(f"{name}{f'：{status}' if status else ''}")
        for target in bundle.get("present_findings") or []:
            observations.append(self._finding_name_for(str(target)))
        return list(dict.fromkeys(item for item in observations if item))[:6]

    def _secondary_confidence(
        self,
        *,
        disease_key: str,
        disease_name: str,
        weak_support: list[str],
        missing: list[str],
    ) -> dict[str, Any]:
        if len(weak_support) >= 3:
            level = "high"
            score = 0.78
            label = "高度支持"
        elif len(weak_support) >= 2:
            level = "moderate"
            score = 0.58
            label = "中等支持"
        elif weak_support:
            level = "low"
            score = 0.38
            label = "低度支持"
        else:
            level = "insufficient"
            score = 0.18
            label = "证据不足"
        basis = weak_support or ["当前证据包未提取到该备用疾病的特异性征象"]
        caveat = (
            f"{disease_name} 需要复查 "
            f"{'、'.join(missing[:2]) if missing else '针对性影像和临床证据'}；"
            "当前结论只用于备用复查排序。"
        )
        return {
            "disease_key": disease_key,
            "disease_name": disease_name,
            "confidence_level": level,
            "confidence_score": score,
            "confidence_label": label,
            "basis": basis,
            "caveat": caveat,
        }

    def _secondary_expected_evidence(self, disease_key: str) -> list[str]:
        profiles = {
            "osteoarthritis_or_degenerative_hip_disease": [
                "关节间隙是否变窄",
                "髋臼或股骨头边缘是否有骨赘",
                "软骨下硬化是否以关节退变模式分布",
                "股骨头形态是否出现退变性不规则",
            ],
            "post_traumatic_change": [
                "是否存在明确骨折线或陈旧骨折畸形",
                "股骨头/股骨颈轮廓是否与外伤后改变一致",
                "是否有外伤史或术后/固定相关改变",
            ],
            "developmental_dysplasia_related_degeneration": [
                "髋臼覆盖是否不足",
                "髋臼是否浅或外上缘发育不良",
                "股骨头外移或半脱位征象",
                "继发性关节退变表现",
            ],
        }
        return profiles.get(
            disease_key,
            [
                "该候选疾病的特异性影像征象",
                "与主分析疾病不同的鉴别证据",
                "是否需要补充体位或临床病史",
            ],
        )

    def _primary_observation_summary(self, result: dict[str, Any]) -> list[str]:
        observations: list[str] = []
        for item in result.get("structured_visual_facts") or []:
            if isinstance(item, dict):
                name = item.get("display_name") or item.get("target") or item.get("finding_id")
                status = item.get("status")
                if name:
                    observations.append(f"{name}{f'：{status}' if status else ''}")
        visual_bundle = result.get("visual_evidence_bundle") or {}
        for item in visual_bundle.get("structured_visual_facts") or []:
            if isinstance(item, dict):
                name = item.get("display_name") or item.get("target") or item.get("finding_id")
                status = item.get("status")
                if name:
                    observations.append(f"{name}{f'：{status}' if status else ''}")
        report = result.get("report") or {}
        imaging = report.get("imaging_evidence_summary") or {}
        for target in imaging.get("supported_targets") or []:
            observations.append(str(target))
        for target in imaging.get("nonspecific_or_unusable_targets") or []:
            observations.append(f"{target}：非特异或不可单独诊断")
        return list(dict.fromkeys(item for item in observations if item))[:5]

    def _secondary_weak_supporting_evidence(
        self,
        *,
        disease_key: str,
        observations: list[str],
    ) -> list[str]:
        text = " ".join(observations)
        weak: list[str] = []
        if disease_key == "osteoarthritis_or_degenerative_hip_disease":
            if any(marker in text for marker in ["硬化", "density", "密度"]):
                weak.append("硬化/密度改变")
            if any(marker in text for marker in ["关节间隙", "joint_space"]):
                weak.append("关节间隙变窄")
            if any(marker in text for marker in ["骨赘", "osteophyte"]):
                weak.append("骨赘")
        if disease_key == "post_traumatic_change":
            if any(marker in text for marker in ["骨折", "fracture", "外伤"]):
                weak.append("骨折或外伤相关线索")
        if disease_key == "developmental_dysplasia_related_degeneration":
            if any(marker in text for marker in ["髋臼", "覆盖", "发育不良", "半脱位"]):
                weak.append("髋臼覆盖/发育异常线索")
        return weak[:3]

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

    def _secondary_knowledge_candidate_plan(
        self,
        *,
        candidate_key: str,
        primary_knowledge: str,
        payload: dict[str, Any],
        knowledge_selection_mode: str,
    ) -> dict[str, Any]:
        knowledge_builder_action, knowledge_builder_reason = self._knowledge_builder_action_for(candidate_key)
        selected_by_user = knowledge_selection_mode == "manual_secondary"
        base = {
            "disease_key": candidate_key,
            "disease_name": self._disease_name_for(candidate_key),
            "primary_knowledge": primary_knowledge,
            "knowledge_builder_action": knowledge_builder_action,
            "knowledge_builder_reason": knowledge_builder_reason,
            "analysis_allowed": True,
            "selected_by_user": selected_by_user,
            "candidate_status": (
                "selected_for_secondary_review"
                if knowledge_builder_action == "load_existing_knowledge"
                else "selected_for_knowledgebuilder"
            ),
        }
        if knowledge_builder_action == "load_existing_knowledge":
            proposal_detail = self._formal_secondary_knowledge_detail(candidate_key)
            return {
                **base,
                "action": "run_formal_secondary_knowledge",
                "knowledge_builder_status": "formal_knowledge_loaded",
                "knowledge_builder_proposal_detail": proposal_detail,
                "knowledge_builder_progress": [
                    {
                        "step": "select_candidate",
                        "label": "已选择备用疾病",
                        "status": "done",
                    },
                    {
                        "step": "load_existing_knowledge",
                        "label": "已加载正式 Knowledge",
                        "status": "done",
                    },
                    {
                        "step": "hypothesis_validation",
                        "label": "进入备用复查",
                        "status": "ready",
                    },
                ],
                "review_status": "formal_guideline_knowledge",
                "use_scope": "evidence_bounded_secondary_diagnosis",
                "diagnosis_allowed": True,
            }
        proposal_knowledge = self.knowledge_tool.prepare_knowledge(
            disease_key=candidate_key,
            disease_name=self._disease_name_for(candidate_key),
            observations=self._proposal_observations(payload),
            persist=False,
        )
        proposal_knowledge = self._ensure_guideline_proposal_knowledge(
            disease_key=candidate_key,
            proposal_knowledge=proposal_knowledge,
        )
        progress = [
            {
                "step": "select_candidate",
                "label": "已选择备用疾病",
                "status": "done",
            },
            {
                "step": "prepare_knowledge_proposal",
                "label": "KnowledgeBuilder proposal 已生成并进入审核库",
                "status": "done",
            },
            {
                "step": "hypothesis_validation",
                "label": "已完成备用 Knowledge 假设复查",
                "status": "done",
            },
        ]
        proposal_detail = self._proposal_secondary_knowledge_detail(
            disease_key=candidate_key,
            proposal_knowledge=proposal_knowledge,
        )
        guideline_evidence_summary = self._proposal_guideline_evidence_summary(proposal_knowledge)
        proposal_artifact_path = self._write_secondary_knowledge_proposal_artifact(
            candidate_key=candidate_key,
            primary_knowledge=primary_knowledge,
            proposal_knowledge=proposal_knowledge,
            proposal_detail=proposal_detail,
            progress=progress,
        )
        proposal_detail["proposal_artifact_path"] = str(proposal_artifact_path)
        proposal_detail["review_queue_status"] = "entered_knowledge_review_queue"
        return {
            **base,
            "action": "run_unreviewed_knowledge_hypothesis_validation",
            "knowledge_builder_status": "proposal_prepared",
            "knowledge_builder_proposal_detail": proposal_detail,
            "knowledge_builder_progress": progress,
            "review_queue_status": "entered_knowledge_review_queue",
            "review_status": "unreviewed",
            "use_scope": "hypothesis_validation_only",
            "diagnosis_allowed": False,
            "proposal_knowledge_id": proposal_knowledge.get("knowledge_id"),
            "proposal_knowledge_type": proposal_knowledge.get("knowledge_type"),
            "proposal_knowledge": proposal_knowledge,
            "guideline_evidence_summary": guideline_evidence_summary,
            "formal_knowledge_updated": False,
        }

    def _write_secondary_knowledge_proposal_artifact(
        self,
        *,
        candidate_key: str,
        primary_knowledge: str,
        proposal_knowledge: dict[str, Any],
        proposal_detail: dict[str, Any],
        progress: list[dict[str, Any]],
    ) -> Path:
        safe_key = re.sub(r"[^A-Za-z0-9_-]+", "_", candidate_key).strip("_")
        if not safe_key:
            safe_key = "secondary_candidate"
        self.secondary_knowledge_proposal_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = self.secondary_knowledge_proposal_dir / f"{safe_key}.json"
        artifact = {
            "schema_version": "secondary_knowledge_proposal.v1",
            "candidate_key": candidate_key,
            "disease_name": self._disease_name_for(candidate_key),
            "primary_knowledge": primary_knowledge,
            "proposal_status": "proposal_only",
            "candidate_status": "selected_for_knowledgebuilder",
            "knowledge_builder_status": "proposal_prepared",
            "review_queue_status": "entered_knowledge_review_queue",
            "diagnosis_allowed": False,
            "formal_knowledge_updated": False,
            "knowledge_builder_progress": progress,
            "knowledge_builder_proposal_detail": {
                **proposal_detail,
                "proposal_artifact_path": str(artifact_path),
                "review_queue_status": "entered_knowledge_review_queue",
            },
            "proposal_knowledge": proposal_knowledge,
            "safety_boundary": (
                "Proposal-only secondary knowledge. It may be used for bounded hypothesis validation "
                "but cannot modify formal guideline knowledge or make a positive diagnosis."
            ),
        }
        artifact_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return artifact_path

    def _proposal_secondary_knowledge_detail(
        self,
        *,
        disease_key: str,
        proposal_knowledge: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "knowledge_id": proposal_knowledge.get("knowledge_id"),
            "knowledge_type": proposal_knowledge.get("knowledge_type"),
            "evidence_level": proposal_knowledge.get("evidence_level"),
            "source_type": proposal_knowledge.get("source_type"),
            "formal_knowledge_updated": False,
            "expected_evidence_to_check": self._secondary_expected_evidence(disease_key),
            **self._proposal_guideline_evidence_summary(proposal_knowledge),
            "doctor_facing_summary": (
                "KnowledgeBuilder 已生成 proposal-only 备用 Knowledge 草案；该草案只用于本次病例假设复查，"
                "不会写入正式 knowledge 库，也不会作为确诊规则。"
            ),
        }

    def _proposal_guideline_evidence_summary(self, proposal_knowledge: dict[str, Any]) -> dict[str, Any]:
        source_documents = [
            document for document in proposal_knowledge.get("source_documents") or []
            if isinstance(document, dict)
        ]
        guideline_documents = [
            document for document in proposal_knowledge.get("guideline_documents") or []
            if isinstance(document, dict)
        ]
        guideline_sections = []
        for document in guideline_documents:
            for section in document.get("sections") or []:
                if isinstance(section, dict) and section.get("heading"):
                    guideline_sections.append(str(section["heading"]))
        quality = proposal_knowledge.get("quality_control") or {}
        return {
            "source_count": len(source_documents),
            "source_titles": [
                str(document.get("title") or document.get("source_id") or "未命名来源")
                for document in source_documents
            ],
            "guideline_document_count": len(guideline_documents),
            "guideline_sections": list(dict.fromkeys(guideline_sections)),
            "citation_status": quality.get("citation_status"),
            "medical_source_status": quality.get("medical_source_status"),
        }

    def _ensure_guideline_proposal_knowledge(
        self,
        *,
        disease_key: str,
        proposal_knowledge: dict[str, Any],
    ) -> dict[str, Any]:
        knowledge = json.loads(json.dumps(proposal_knowledge, ensure_ascii=False))
        source_documents = list(knowledge.get("source_documents") or self._default_guideline_sources_for(disease_key))
        if not source_documents:
            quality = dict(knowledge.get("quality_control") or {})
            quality.update(
                {
                    "formal_knowledge_status": "proposal_only",
                    "medical_source_status": "missing",
                    "citation_status": "missing",
                    "citation_count": 0,
                    "missing_url_count": 0,
                    "can_enter_formal_guideline_knowledge": False,
                }
            )
            knowledge["quality_control"] = quality
            return knowledge
        return normalize_guideline_knowledge_draft(
            knowledge=knowledge,
            disease_key=disease_key,
            source_documents=source_documents,
        )

    def _default_guideline_sources_for(self, disease_key: str) -> list[dict[str, Any]]:
        sources_by_key: dict[str, list[dict[str, Any]]] = {
            "osteoarthritis_or_degenerative_hip_disease": [
                {
                    "title": "ACR Appropriateness Criteria Chronic Hip Pain",
                    "publisher": "American College of Radiology",
                    "source_id": "acr_chronic_hip_pain",
                    "url": "https://acsearch.acr.org/docs/69425/Narrative/",
                    "source_kind": "imaging_appropriateness_guideline",
                    "publication_year": 2022,
                    "region": "US",
                    "source_priority": 10,
                    "evidence_note": "Hip radiography and imaging workup for chronic hip pain including degenerative disease considerations.",
                },
                {
                    "title": "NICE Osteoarthritis in over 16s: diagnosis and management",
                    "publisher": "NICE",
                    "source_id": "nice_osteoarthritis_ng226",
                    "url": "https://www.nice.org.uk/guidance/ng226",
                    "source_kind": "clinical_guideline",
                    "publication_year": 2022,
                    "region": "UK",
                    "source_priority": 9,
                    "evidence_note": "Clinical osteoarthritis diagnosis and management guideline used as a review source.",
                },
            ],
            "post_traumatic_change": [
                {
                    "title": "ACR Appropriateness Criteria Acute Hip Pain",
                    "publisher": "American College of Radiology",
                    "source_id": "acr_acute_hip_pain",
                    "url": "https://acsearch.acr.org/docs/3082587/Narrative/",
                    "source_kind": "imaging_appropriateness_guideline",
                    "publication_year": 2024,
                    "region": "US",
                    "source_priority": 10,
                    "evidence_note": "Imaging pathway for traumatic or acute hip pain.",
                }
            ],
            "developmental_dysplasia_related_degeneration": [
                {
                    "title": "ACR Appropriateness Criteria Chronic Hip Pain",
                    "publisher": "American College of Radiology",
                    "source_id": "acr_chronic_hip_pain",
                    "url": "https://acsearch.acr.org/docs/69425/Narrative/",
                    "source_kind": "imaging_appropriateness_guideline",
                    "publication_year": 2022,
                    "region": "US",
                    "source_priority": 10,
                    "evidence_note": "Chronic hip pain imaging source used for dysplasia-related degenerative review.",
                }
            ],
        }
        return list(sources_by_key.get(disease_key, []))

    def _formal_secondary_knowledge_detail(self, disease_key: str) -> dict[str, Any]:
        return {
            "knowledge_id": disease_key,
            "knowledge_type": "formal_guideline_knowledge",
            "evidence_level": "guideline",
            "source_type": "local_knowledge_library",
            "formal_knowledge_updated": False,
            "expected_evidence_to_check": self._secondary_expected_evidence(disease_key),
            "doctor_facing_summary": "已加载本地正式 Knowledge，可进入受证据边界约束的备用复查。",
        }

    def _validate_vision_mode(self, vision_mode: str) -> None:
        if vision_mode not in self.SUPPORTED_VISION_MODES:
            supported = ", ".join(sorted(self.SUPPORTED_VISION_MODES))
            raise ValueError(
                f"unsupported vision_mode: {vision_mode}. Supported modes: {supported}"
            )

    def _knowledge_builder_action_for(self, disease_key: str | None) -> tuple[str, str]:
        if not disease_key:
            return "none", "No primary hypothesis selected."
        try:
            knowledge = self.knowledge_tool.load_guideline_knowledge(str(disease_key))
        except FileNotFoundError:
            return "search_or_generate_knowledge", "local knowledge was not found"
        protocol_ready, protocol_reason = self._knowledge_protocol_readiness(knowledge)
        if not protocol_ready:
            return "search_or_generate_knowledge", protocol_reason
        return "load_existing_knowledge", "local knowledge has required protocol"

    def _knowledge_protocol_readiness(self, knowledge: dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(knowledge, dict):
            return False, "local knowledge is not a valid object"
        validator = VisualProtocolValidator()
        has_full_evidence_protocol = bool(knowledge.get("imaging_evidence_protocol")) or any(
            bool(knowledge.get(field))
            for field in (
                "differential_diagnosis_protocol",
                "clinical_context_protocol",
                "integrated_reasoning_protocol",
            )
        )
        if has_full_evidence_protocol:
            evidence_validation = validator.validate_evidence_protocol(knowledge)
            if not evidence_validation.get("valid"):
                errors = "; ".join(str(error) for error in evidence_validation.get("errors", []))
                return False, f"local knowledge has invalid evidence_protocol: {errors}"
            return True, "local knowledge has valid evidence_protocol"
        if knowledge.get("quantitative_evidence_protocol"):
            quantitative_validation = validator.validate_quantitative_evidence_protocol(
                knowledge.get("quantitative_evidence_protocol")
            )
            if not quantitative_validation.get("valid"):
                errors = "; ".join(str(error) for error in quantitative_validation.get("errors", []))
                return False, f"local knowledge has invalid quantitative_evidence_protocol: {errors}"
        if knowledge.get("visual_protocol"):
            validation = validator.validate_knowledge(knowledge)
            if not validation.get("valid"):
                errors = "; ".join(str(error) for error in validation.get("errors", []))
                return False, f"local knowledge has invalid visual_protocol: {errors}"
            return True, "local knowledge has valid visual_protocol"
        return False, "local knowledge is missing required protocol"

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

    def _differential_knowledge_candidates(
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

    def _focused_primary_knowledge_only(
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
            for marker in ["怀疑", "是不是", "是否", "用", "根据", "knowledge", "诊断", "分析"]
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

    def _rank_differential_knowledge_candidates(
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
                        "evidence review and does not replace the primary knowledge."
                    ),
                }
            )
        return hypotheses

    def _knowledge_search_reason(
        self,
        *,
        disease_key: str | None,
        payload: dict[str, Any],
        knowledge_builder_action: str | None = None,
        knowledge_builder_action_reason: str | None = None,
    ) -> str:
        if not disease_key:
            return (
                "No ONFH primary knowledge matched from the current hip/ONFH screening scope; "
                "non-ONFH inputs require explicit review before any extension knowledge is generated."
            )
        if knowledge_builder_action == "search_or_generate_knowledge":
            return (
                f"Selected {disease_key} as a primary clinical hypothesis, but {knowledge_builder_action_reason or 'the local knowledge is not ready'}; "
                "Knowledge Builder should search guideline sources and create a proposal knowledge before evidence-bounded diagnosis."
            )
        if disease_key == "femoral_head_necrosis":
            text = self._routing_text(payload)
            side = "left hip pain" if any(marker in text for marker in ["左髋", "left hip"]) else "hip pain"
            if any(marker in text for marker in ["怀疑", "股骨头坏死", "fhn", "onfh", "avn"]):
                return (
                    "User raised femoral head necrosis as a concern; selected the existing FHN knowledge as a primary clinical hypothesis, "
                    "while keeping bounded differential candidates for evidence acquisition."
                )
            return (
                f"{side} with hip X-ray; user did not provide a confirmed diagnosis; "
                "FHN and degenerative, traumatic, and dysplasia-related causes should be considered before evidence-bounded diagnosis."
            )
        return (
            "Selected an extension knowledge as a bounded technical example or differential review; "
            "the current product scope remains ONFH screening and evidence analysis."
        )

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
        specific_markers = [
            "股骨头",
            "髋",
            "hip",
            "pelvis",
            "femoral",
            "fhn",
            "onfh",
            "avn",
        ]
        if not any(marker in text for marker in specific_markers):
            return []
        femoral_markers = specific_markers + [
            "xray",
            "x-ray",
            "x 光",
            "x光",
            "坏死",
        ]
        return [marker for marker in femoral_markers if marker in text]

    def _routing_text(self, payload: dict[str, Any]) -> str:
        patient_info = payload.get("patient_info", {}) if isinstance(payload.get("patient_info"), dict) else {}
        symptoms = patient_info.get("symptoms", [])
        if isinstance(symptoms, str):
            symptoms_text = symptoms
        else:
            symptoms_text = " ".join(str(symptom) for symptom in symptoms)
        return " ".join(
            str(value)
            for value in [
                payload.get("patient_message", ""),
                payload.get("image_path", ""),
                payload.get("image_modality", ""),
                patient_info.get("image_modality", ""),
                patient_info.get("clinical_notes", ""),
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
            return "no_mask_knowledge"
        return None

    def _build_alignment_plan(
        self,
        payload: dict[str, Any],
        routing_decision: dict[str, Any],
    ) -> dict[str, Any]:
        disease_key = routing_decision.get("selected_knowledge")
        disease_knowledge: dict[str, Any] = {}
        try:
            if disease_key:
                disease_knowledge = self.knowledge_tool.load_guideline_knowledge(str(disease_key))
        except FileNotFoundError:
            disease_knowledge = {}
        return self.alignment_planner.build_plan(
            payload=payload,
            routing_decision=routing_decision,
            disease_knowledge=disease_knowledge,
        )

    def _attach_diagnostic_confidence(self, result: dict[str, Any]) -> None:
        primary = self._primary_diagnostic_confidence(result)
        secondary = self._secondary_diagnostic_confidence_items(result)
        items = [item for item in [primary, *secondary] if item]
        if not items:
            return
        result["diagnostic_confidence"] = items
        report = result.setdefault("report", {})
        if isinstance(report, dict):
            report["诊断置信度"] = [
                {
                    **item,
                    "display_sentence": self._diagnostic_confidence_sentence(item),
                }
                for item in items
            ]

    def _primary_diagnostic_confidence(self, result: dict[str, Any]) -> dict[str, Any] | None:
        report = result.get("report") or {}
        integrated = report.get("integrated_reasoning_summary") or {}
        assessment = report.get("target_disease_assessment") or {}
        routing = result.get("routing_decision") or {}
        disease_key = str(
            integrated.get("target_disease")
            or assessment.get("target_disease")
            or routing.get("primary_hypothesis")
            or routing.get("selected_knowledge")
            or ""
        )
        if not disease_key:
            return None
        disease_name = self._disease_name_for(disease_key)
        basis = self._primary_confidence_basis(result)
        level, score, label = self._primary_confidence_level(
            disease_key=disease_key,
            basis=basis,
            result=result,
        )
        if level == "insufficient" and not basis:
            basis = ["当前证据包没有提取到可支持该疾病的稳定影像征象"]
        return {
            "disease_key": disease_key,
            "disease_name": disease_name,
            "role": "primary",
            "confidence_level": level,
            "confidence_score": score,
            "confidence_label": label,
            "label": f"影像证据{label}：{disease_name}",
            "basis": basis[:5],
            "caveat": self._primary_confidence_caveat(disease_key=disease_key, level=level),
        }

    def _primary_confidence_basis(self, result: dict[str, Any]) -> list[str]:
        report = result.get("report") or {}
        imaging = report.get("imaging_evidence_summary") or {}
        basis: list[str] = []
        for target in imaging.get("supported_targets") or []:
            basis.append(self._finding_name_for(str(target)))
        visual_bundle = result.get("visual_evidence_bundle") or {}
        for target in visual_bundle.get("present_findings") or []:
            basis.append(self._finding_name_for(str(target)))
        for item in result.get("structured_visual_facts") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("display_name") or self._finding_name_for(str(item.get("target") or ""))
            if name:
                basis.append(str(name))
        for item in visual_bundle.get("structured_visual_facts") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("display_name") or self._finding_name_for(str(item.get("target") or ""))
            if name:
                basis.append(str(name))
        for item in visual_bundle.get("findings") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("display_name") or self._finding_name_for(str(item.get("target") or ""))
            if name:
                basis.append(str(name))
        return list(dict.fromkeys(item for item in basis if item))

    def _primary_confidence_level(
        self,
        *,
        disease_key: str,
        basis: list[str],
        result: dict[str, Any],
    ) -> tuple[str, float, str]:
        report = result.get("report") or {}
        integrated = report.get("integrated_reasoning_summary") or {}
        assessment = report.get("target_disease_assessment") or {}
        if integrated.get("can_confirm_target_disease") is True or assessment.get("can_confirm_target_disease") is True:
            return "high", 0.86, "高度支持"
        basis_text = " ".join(basis)
        if disease_key == "femoral_head_necrosis":
            has_sclerotic = any(marker in basis_text for marker in ["硬化", "sclerotic"])
            has_cystic = any(marker in basis_text for marker in ["囊性", "囊变", "cystic"])
            has_collapse = any(marker in basis_text for marker in ["塌陷", "collapse", "新月"])
            if has_collapse or (has_sclerotic and has_cystic):
                return "high", 0.82, "高度支持"
            if has_sclerotic or has_cystic:
                return "moderate", 0.62, "中等支持"
        status = str(
            integrated.get("evidence_status")
            or assessment.get("evidence_status")
            or result.get("analysis_status")
            or ""
        )
        if basis:
            return "low", 0.42, "低度支持"
        if status in {"insufficient", "requires_evidence_acquisition", "partial_evidence"}:
            return "insufficient", 0.18, "证据不足"
        return "low", 0.35, "低度支持"

    def _primary_confidence_caveat(self, *, disease_key: str, level: str) -> str:
        if disease_key == "femoral_head_necrosis":
            if level == "high":
                return "建议 MRI 明确坏死范围、分期和是否存在早期塌陷；最终诊断仍需影像科/骨科医生结合病史确认。"
            return "X 光对早期股骨头坏死敏感性有限；如症状持续或风险因素明确，建议 MRI 进一步评估。"
        return "该置信度是 evidence bundle 内部支持度，不是校准后的流行病学概率；最终诊断需医生确认。"

    def _secondary_diagnostic_confidence_items(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for analysis in result.get("secondary_knowledge_analysis") or []:
            if not isinstance(analysis, dict):
                continue
            confidence = (analysis.get("differential_review") or {}).get("diagnostic_confidence")
            if isinstance(confidence, dict):
                items.append({**confidence, "role": "secondary"})
        return items

    def _diagnostic_confidence_sentence(self, item: dict[str, Any]) -> str:
        name = item.get("disease_name") or self._disease_name_for(str(item.get("disease_key") or ""))
        level = item.get("confidence_label") or item.get("confidence_level") or "未分级"
        basis = item.get("basis") if isinstance(item.get("basis"), list) else []
        basis_text = f"；依据：{'、'.join(str(value) for value in basis[:3])}" if basis else ""
        caveat = f"；{item.get('caveat')}" if item.get("caveat") else ""
        return f"{name}：当前证据支持度为{level}{basis_text}{caveat}"

    def _attach_onfh_diagnostic_flow(self, result: dict[str, Any]) -> None:
        routing = result.get("routing_decision") or {}
        report = result.setdefault("report", {})
        disease_key = str(
            routing.get("selected_knowledge")
            or routing.get("primary_hypothesis")
            or (report.get("target_disease_assessment") or {}).get("target_disease")
            or ""
        )
        if disease_key != "femoral_head_necrosis":
            return
        confidence = self._primary_diagnostic_confidence(result)
        findings = self._onfh_detected_findings(result)
        has_supporting_findings = bool(findings)
        support_level = (confidence or {}).get("confidence_level") or "insufficient"
        support_label = (confidence or {}).get("confidence_label") or "证据不足"
        if has_supporting_findings:
            flow_type = "positive"
            negative_category = None
            conclusion = (
                f"当前影像发现 {', '.join(item['display_name'] for item in findings[:4])}，"
                f"对股骨头坏死方向为{support_label}。"
            )
        else:
            flow_type = "negative"
            negative_category = self._onfh_negative_category(result)
            conclusion = self._onfh_negative_conclusion(negative_category)
        staging = self._onfh_staging_assessment(findings=findings, result=result)
        next_steps = self._onfh_next_steps(
            flow_type=flow_type,
            negative_category=negative_category,
            findings=findings,
            result=result,
        )
        assessment = {
            "disease_key": "femoral_head_necrosis",
            "flow_type": flow_type,
            "support_level": support_level,
            "support_label": support_label,
            "confidence_score": (confidence or {}).get("confidence_score"),
            "detected_findings": findings,
            "staging_assessment": staging,
            "negative_category": negative_category,
            "conclusion": conclusion,
            "next_steps": next_steps,
            "safety_note": (
                "该结果是基于当前 evidence bundle 的 ONFH 专病辅助判断，"
                "不能替代影像科/骨科医生的正式诊断。"
            ),
        }
        result["onfh_assessment"] = assessment
        report["onfh_assessment"] = assessment
        if staging:
            report["分期辅助"] = staging
            if flow_type == "positive" and staging.get("stage") and staging.get("stage") != "不能分期":
                supporting = [
                    str(item)
                    for item in staging.get("supporting_findings", [])
                    if item
                ]
                stage_summary = str(staging["stage"])
                if supporting:
                    stage_summary = f"{stage_summary}；依据：{'、'.join(supporting)}"
                report.setdefault("重点结论", {})["分期辅助"] = stage_summary
        if next_steps:
            report["建议下一步"] = next_steps

    def _onfh_detected_findings(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        targets: list[dict[str, Any]] = []

        def add(target: str, *, text: str = "", source: str = "") -> None:
            normalized = self._normalize_onfh_finding_target(target or text)
            if not normalized:
                return
            display_name = self._finding_name_for(normalized)
            if any(item["target"] == normalized for item in targets):
                return
            targets.append(
                {
                    "target": normalized,
                    "display_name": display_name,
                    "evidence_text": text or display_name,
                    "diagnostic_role": self._onfh_finding_diagnostic_role(normalized),
                    "source": source,
                }
            )

        visual_bundle = result.get("visual_evidence_bundle") or {}
        for target in visual_bundle.get("present_findings") or []:
            add(str(target), source="visual_evidence_bundle.present_findings")
        for container in [
            result.get("structured_visual_facts") or [],
            visual_bundle.get("structured_visual_facts") or [],
            visual_bundle.get("findings") or [],
            result.get("used_visual_facts") or [],
        ]:
            for item in container:
                if not isinstance(item, dict):
                    continue
                text = str(
                    item.get("summary_text")
                    or item.get("evidence_text")
                    or item.get("description")
                    or item.get("display_name")
                    or ""
                )
                add(str(item.get("target") or item.get("display_name") or text), text=text, source="visual_fact")
        report = result.get("report") or {}
        imaging = report.get("imaging_evidence_summary") or {}
        for target in imaging.get("supported_targets") or []:
            add(str(target), source="report.imaging_evidence_summary")
        for basis in self._primary_confidence_basis(result):
            add(str(basis), source="diagnostic_confidence_basis")
        return targets

    def _normalize_onfh_finding_target(self, value: str) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        if any(marker in text for marker in ["sclerotic", "硬化"]):
            return "sclerotic_band"
        if any(marker in text for marker in ["cystic", "囊性", "囊变"]):
            return "cystic_change"
        if any(marker in text for marker in ["crescent", "新月", "软骨下骨折", "subchondral_fracture", "subchondral fracture"]):
            return "crescent_sign"
        if any(marker in text for marker in ["collapse", "塌陷"]):
            return "collapse"
        if any(marker in text for marker in ["trabecular", "骨小梁", "纹理"]):
            return "trabecular_blurring"
        return ""

    def _onfh_finding_diagnostic_role(self, target: str) -> str:
        if target in {"collapse", "crescent_sign"}:
            return "supports_collapse_stage"
        if target in {"sclerotic_band", "cystic_change", "trabecular_blurring"}:
            return "supports_radiographic_onfh"
        return "supporting_visual_clue"

    def _onfh_staging_assessment(
        self,
        *,
        findings: list[dict[str, Any]],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        targets = {item["target"] for item in findings}
        modality = self._onfh_result_modality(result)
        if "collapse" in targets or "crescent_sign" in targets:
            supporting = [
                item["display_name"]
                for item in findings
                if item["target"] in {"collapse", "crescent_sign"}
            ]
            return {
                "stage": "疑似 ARCO III 或以上",
                "confidence": "stage_suspected",
                "supporting_findings": supporting,
                "rationale": "新月征/软骨下骨折或股骨头塌陷提示已进入塌陷相关阶段。",
                "limitations": "仍需标准体位 X 光或 MRI 明确塌陷范围和坏死面积。",
            }
        if targets.intersection({"sclerotic_band", "cystic_change", "trabecular_blurring"}):
            supporting = [
                item["display_name"]
                for item in findings
                if item["target"] in {"sclerotic_band", "cystic_change", "trabecular_blurring"}
            ]
            return {
                "stage": "疑似 ARCO II",
                "confidence": "stage_suspected",
                "supporting_findings": supporting,
                "rationale": "X 光可见硬化带、囊性变或骨小梁异常，且未返回明确塌陷/新月征。",
                "limitations": "MRI 可进一步确认坏死范围，并排除早期或隐匿性改变。",
            }
        if modality == "xray":
            return {
                "stage": "不能分期",
                "confidence": "not_stageable",
                "supporting_findings": [],
                "rationale": "当前 X 光未返回可用于 ONFH 分期的明确征象。",
                "limitations": "X 光阴性不能排除 ARCO I；如症状和风险因素强，建议 MRI。",
            }
        return {
            "stage": "不能分期",
            "confidence": "not_stageable",
            "supporting_findings": [],
            "rationale": "当前 evidence bundle 未提供可用于分期的 ONFH 影像征象。",
            "limitations": "需要标准化 X 光/MRI 和可靠视觉证据后再分期。",
        }

    def _onfh_negative_category(self, result: dict[str, Any]) -> str:
        quality_text = json.dumps(
            {
                "visual_evidence_bundle": result.get("visual_evidence_bundle") or {},
                "visual_input_contract": result.get("visual_input_contract") or {},
                "image_outputs": result.get("image_outputs") or {},
            },
            ensure_ascii=False,
        ).lower()
        if any(
            marker in quality_text
            for marker in [
                "low_quality",
                "quality_low",
                "poor_quality",
                "view_insufficient",
                "not_standard_view",
                "invalid_view",
                "图像质量",
                "体位不足",
            ]
        ):
            return "image_quality_or_view_insufficient"
        modality = self._onfh_result_modality(result)
        if modality == "xray" and self._onfh_has_strong_clinical_risk(result):
            return "xray_negative_but_clinical_risk_high"
        return "evidence_not_supportive"

    def _onfh_negative_conclusion(self, category: str) -> str:
        if category == "image_quality_or_view_insufficient":
            return "当前图像质量或体位不足，不能可靠判断股骨头坏死。"
        if category == "xray_negative_but_clinical_risk_high":
            return "当前 X 光未发现明确 ONFH 征象，但症状或风险因素较强，不能排除早期股骨头坏死。"
        return "当前 evidence bundle 未发现支持股骨头坏死的明确影像征象。"

    def _onfh_next_steps(
        self,
        *,
        flow_type: str,
        negative_category: str | None,
        findings: list[dict[str, Any]],
        result: dict[str, Any],
    ) -> list[str]:
        if flow_type == "positive":
            targets = {item["target"] for item in findings}
            steps = ["建议结合影像科/骨科医生复核原片和病史。"]
            if targets.intersection({"sclerotic_band", "cystic_change", "trabecular_blurring"}):
                steps.append("建议 MRI 明确坏死范围、骨髓水肿和是否存在早期塌陷。")
            if targets.intersection({"collapse", "crescent_sign"}):
                steps.append("建议进一步评估塌陷范围、负重区受累程度和治疗方案。")
            return steps
        if negative_category == "image_quality_or_view_insufficient":
            return ["建议补充标准骨盆正位、蛙式位 X 光或髋关节 MRI 后再评估。"]
        if negative_category == "xray_negative_but_clinical_risk_high":
            return ["建议补充髋关节 MRI；X 光阴性不能排除 ARCO I 或早期坏死。"]
        return ["若症状持续、加重或存在明确风险因素，建议随访复查或补充 MRI。"]

    def _onfh_result_modality(self, result: dict[str, Any]) -> str:
        patient_info = result.get("patient_info") if isinstance(result.get("patient_info"), dict) else {}
        routing_text = self._routing_text(
            {
                "patient_message": result.get("patient_message") or "",
                "image_path": result.get("image_path") or "",
                "patient_info": patient_info,
            }
        )
        return self._onfh_requested_modality(
            {
                "image_path": result.get("image_path") or "",
                "patient_info": patient_info,
            },
            routing_text,
        )

    def _onfh_has_strong_clinical_risk(self, result: dict[str, Any]) -> bool:
        patient_info = result.get("patient_info") if isinstance(result.get("patient_info"), dict) else {}
        text = self._routing_text(
            {
                "patient_message": result.get("patient_message") or "",
                "image_path": result.get("image_path") or "",
                "patient_info": patient_info,
            }
        )
        has_symptoms = any(marker in text for marker in ["髋", "hip", "疼", "痛", "走路", "活动", "负重"])
        has_risk = any(
            marker in text
            for marker in [
                "激素",
                "饮酒",
                "酗酒",
                "外伤",
                "创伤",
                "steroid",
                "corticosteroid",
                "alcohol",
                "trauma",
            ]
        )
        return has_symptoms and has_risk

    def _finding_name_for(self, target: str) -> str:
        labels = {
            "sclerotic_band": "硬化带",
            "cystic_change": "囊性变",
            "trabecular_blurring": "骨小梁模糊",
            "collapse": "股骨头塌陷",
            "crescent_sign": "新月征/软骨下骨折",
            "joint_space_narrowing": "关节间隙变窄",
            "osteophyte": "骨赘",
        }
        return labels.get(target, target)

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
