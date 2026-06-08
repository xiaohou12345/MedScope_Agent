from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


def _copy_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in value}


@dataclass(frozen=True)
class ImageOutputs:
    """Visual artifacts produced or referenced by the vision agent."""

    original_image_path: str
    mask_path: str
    overlay_path: str
    comparison_path: str | None = None
    vlm_annotation_path: str | None = None
    localization_overlay_path: str | None = None

    def __post_init__(self) -> None:
        missing = [
            name
            for name, value in {
                "original_image_path": self.original_image_path,
                "mask_path": self.mask_path,
                "overlay_path": self.overlay_path,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"image output paths cannot be empty: {', '.join(missing)}")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "original_image_path": self.original_image_path,
            "mask_path": self.mask_path,
            "overlay_path": self.overlay_path,
        }
        if self.comparison_path:
            payload["comparison_path"] = self.comparison_path
        if self.vlm_annotation_path:
            payload["vlm_annotation_path"] = self.vlm_annotation_path
        if self.localization_overlay_path:
            payload["localization_overlay_path"] = self.localization_overlay_path
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ImageOutputs":
        return cls(
            original_image_path=payload["original_image_path"],
            mask_path=payload["mask_path"],
            overlay_path=payload["overlay_path"],
            comparison_path=payload.get("comparison_path"),
            vlm_annotation_path=payload.get("vlm_annotation_path"),
            localization_overlay_path=payload.get("localization_overlay_path"),
        )


@dataclass(frozen=True)
class LesionGallery:
    """Display-ready lesion artifacts aligned with visual fact usage."""

    items: list[dict[str, Any]]

    SCHEMA_VERSION: ClassVar[str] = "lesion_gallery.v1"
    ALLOWED_USAGE_STATUSES: ClassVar[set[str]] = {"used", "excluded", "candidate"}

    def __post_init__(self) -> None:
        for item in self.items:
            if not isinstance(item, dict):
                raise ValueError("lesion gallery items must be objects")
            if not str(item.get("finding_id") or "").strip():
                raise ValueError("lesion gallery item requires finding_id")
            usage = item.get("usage") or {}
            if not isinstance(usage, dict):
                raise ValueError("lesion gallery item usage must be an object")
            usage_status = usage.get("status", "candidate")
            if usage_status not in self.ALLOWED_USAGE_STATUSES:
                raise ValueError(f"unsupported lesion gallery usage status: {usage_status}")

    def to_dict(self) -> dict[str, Any]:
        used_count = self._count_usage("used")
        excluded_count = self._count_usage("excluded")
        candidate_count = self._count_usage("candidate")
        return {
            "schema_version": self.SCHEMA_VERSION,
            "items": [dict(item) for item in self.items],
            "used_count": used_count,
            "excluded_count": excluded_count,
            "candidate_count": candidate_count,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LesionGallery":
        schema_version = payload.get("schema_version", cls.SCHEMA_VERSION)
        if schema_version != cls.SCHEMA_VERSION:
            raise ValueError(f"unsupported lesion gallery schema: {schema_version}")
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise ValueError("lesion gallery items must be a list")
        return cls(items=[dict(item) for item in items])

    def _count_usage(self, usage_status: str) -> int:
        return sum(
            1
            for item in self.items
            if (item.get("usage") or {}).get("status", "candidate") == usage_status
        )


@dataclass(frozen=True)
class PatientCaseInput:
    """Single front-door payload accepted by the patient-facing agent."""

    patient_message: str
    image_path: str
    patient_info: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "patient_message": self.patient_message,
            "image_path": self.image_path,
            "patient_info": _copy_dict(self.patient_info),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PatientCaseInput":
        return cls(
            patient_message=payload["patient_message"],
            image_path=payload["image_path"],
            patient_info=_copy_dict(payload["patient_info"]),
        )


@dataclass(frozen=True)
class PatientIntent:
    """Routing decision for the patient-facing agent."""

    intent_type: str
    patient_message: str
    image_path: str | None = None
    case_id: str | None = None

    ALLOWED_TYPES: ClassVar[set[str]] = {"diagnosis", "qa", "review", "report_explanation"}

    def __post_init__(self) -> None:
        if self.intent_type not in self.ALLOWED_TYPES:
            raise ValueError(f"unsupported patient intent: {self.intent_type}")
        if self.intent_type == "diagnosis" and not self.image_path:
            raise ValueError("diagnosis intent requires image_path")
        if self.intent_type in {"qa", "report_explanation"} and not self.case_id:
            raise ValueError(f"{self.intent_type} intent requires case_id")
        if self.intent_type == "review" and (not self.case_id or not self.image_path):
            raise ValueError("review intent requires case_id and image_path")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "intent_type": self.intent_type,
            "patient_message": self.patient_message,
        }
        if self.image_path:
            payload["image_path"] = self.image_path
        if self.case_id:
            payload["case_id"] = self.case_id
        return payload


@dataclass(frozen=True)
class SkillRoutingDecision:
    """Orchestrator/API decision about which existing skill and vision mode to use."""

    selected_skill: str | None
    selected_vision_mode: str | None
    source: str
    reason: str
    confidence: float
    matched_clues: list[str] = field(default_factory=list)
    agent_scope: str = "orchestrator_api"
    skill_selection_mode: str = "primary_only"
    manual_secondary_skill_candidates: list[str] = field(default_factory=list)
    primary_hypothesis: str | None = None
    differential_skill_candidates: list[str] = field(default_factory=list)
    differential_candidate_ranking: list[dict[str, Any]] = field(default_factory=list)
    display_differential_skill_candidates: list[str] = field(default_factory=list)
    secondary_skill_run_plan: dict[str, Any] = field(default_factory=dict)
    clinical_hypotheses: list[dict[str, Any]] = field(default_factory=list)
    skill_search_reason: str | None = None
    initial_evidence_status: str = "insufficient"
    routing_evidence_status: str | None = None
    skill_builder_action: str | None = None

    ALLOWED_SOURCES: ClassVar[set[str]] = {"auto", "explicit", "default"}
    ALLOWED_EVIDENCE_STATUSES: ClassVar[set[str]] = {
        "insufficient",
        "nonspecific",
        "requires_evidence_acquisition",
        "requires_differential_review",
    }
    ALLOWED_SKILL_BUILDER_ACTIONS: ClassVar[set[str]] = {
        "none",
        "load_existing_skill",
        "search_or_generate_skill",
    }
    ALLOWED_SKILL_SELECTION_MODES: ClassVar[set[str]] = {
        "primary_only",
        "manual_secondary",
        "agent_auto_secondary",
    }

    def __post_init__(self) -> None:
        if self.source not in self.ALLOWED_SOURCES:
            raise ValueError(f"unsupported routing source: {self.source}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("routing confidence must be between 0 and 1")
        if self.agent_scope != "orchestrator_api":
            raise ValueError("skill routing decisions must stay in orchestrator_api scope")
        if self.skill_selection_mode not in self.ALLOWED_SKILL_SELECTION_MODES:
            raise ValueError(f"unsupported skill selection mode: {self.skill_selection_mode}")
        if self.initial_evidence_status not in self.ALLOWED_EVIDENCE_STATUSES:
            raise ValueError(
                f"unsupported initial evidence status: {self.initial_evidence_status}"
            )
        effective_status = self.routing_evidence_status or self.initial_evidence_status
        if effective_status not in self.ALLOWED_EVIDENCE_STATUSES:
            raise ValueError(f"unsupported routing evidence status: {effective_status}")
        effective_action = self.skill_builder_action or self._skill_builder_action()
        if effective_action not in self.ALLOWED_SKILL_BUILDER_ACTIONS:
            raise ValueError(f"unsupported skill builder action: {effective_action}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_skill": self.selected_skill,
            "selected_vision_mode": self.selected_vision_mode,
            "source": self.source,
            "reason": self.reason,
            "confidence": self.confidence,
            "matched_clues": list(self.matched_clues),
            "agent_scope": self.agent_scope,
            "skill_builder_action": self.skill_builder_action or self._skill_builder_action(),
            "skill_selection_mode": self.skill_selection_mode,
            "manual_secondary_skill_candidates": list(self.manual_secondary_skill_candidates),
            "primary_hypothesis": self.primary_hypothesis,
            "differential_skill_candidates": list(self.differential_skill_candidates),
            "differential_candidate_ranking": [
                dict(item) for item in self.differential_candidate_ranking
            ],
            "display_differential_skill_candidates": list(
                self.display_differential_skill_candidates
            ),
            "secondary_skill_run_plan": dict(self.secondary_skill_run_plan),
            "clinical_hypotheses": [dict(item) for item in self.clinical_hypotheses],
            "skill_search_reason": self.skill_search_reason,
            "initial_evidence_status": self.initial_evidence_status,
            "routing_evidence_status": self.routing_evidence_status or self.initial_evidence_status,
        }

    def _skill_builder_action(self) -> str:
        if self.selected_skill:
            return "load_existing_skill"
        return "none"


@dataclass(frozen=True)
class AlignmentPlan:
    """Coordinates patient intent, uploaded image context, and skill visual requirements."""

    selected_skill: str | None
    analysis_status: str
    clinical_focus: str
    image_context: dict[str, Any]
    visual_tasks: list[dict[str, Any]]
    diagnosis_scope: dict[str, Any]
    suspected_conditions: list[dict[str, Any]] = field(default_factory=list)
    required_next_images: list[dict[str, Any]] = field(default_factory=list)
    insufficiency_reasons: list[str] = field(default_factory=list)

    ALLOWED_STATUSES: ClassVar[set[str]] = {
        "evidence_sufficient",
        "partial_evidence",
        "insufficient_evidence",
        "contraindicated_or_wrong_modality",
    }

    def __post_init__(self) -> None:
        if self.analysis_status not in self.ALLOWED_STATUSES:
            raise ValueError(f"unsupported alignment status: {self.analysis_status}")
        if not isinstance(self.image_context, dict):
            raise ValueError("alignment image_context must be a dict")
        if not isinstance(self.diagnosis_scope, dict):
            raise ValueError("alignment diagnosis_scope must be a dict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_skill": self.selected_skill,
            "analysis_status": self.analysis_status,
            "clinical_focus": self.clinical_focus,
            "image_context": dict(self.image_context),
            "visual_tasks": [dict(task) for task in self.visual_tasks],
            "diagnosis_scope": {
                key: list(value) if isinstance(value, list) else value
                for key, value in self.diagnosis_scope.items()
            },
            "suspected_conditions": [
                dict(condition) for condition in self.suspected_conditions
            ],
            "required_next_images": [
                dict(image) for image in self.required_next_images
            ],
            "insufficiency_reasons": list(self.insufficiency_reasons),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AlignmentPlan":
        return cls(
            selected_skill=payload.get("selected_skill"),
            analysis_status=payload["analysis_status"],
            clinical_focus=payload.get("clinical_focus", ""),
            image_context=dict(payload.get("image_context") or {}),
            visual_tasks=[dict(task) for task in payload.get("visual_tasks") or []],
            diagnosis_scope=dict(payload.get("diagnosis_scope") or {}),
            suspected_conditions=[
                dict(condition)
                for condition in payload.get("suspected_conditions") or []
            ],
            required_next_images=[
                dict(image) for image in payload.get("required_next_images") or []
            ],
            insufficiency_reasons=list(payload.get("insufficiency_reasons") or []),
        )


@dataclass(frozen=True)
class VisualTask:
    """One skill-derived visual task that can be routed to a visual tool."""

    task_name: str
    target: str
    required_modalities: list[str]
    output: str = "mask"
    measurements: list[str] = field(default_factory=list)
    reason: str = ""
    execution_mode: str = "vlm_plus_segmenter"
    localization_mode: str = "bbox"
    segmentation_mode: str = "candidate_mask"
    diagnosis_usable_level: str = "candidate_support"
    evidence_type: str = "candidate_mask"
    measurement_dependencies: list[str] = field(default_factory=list)
    measurement_usable: bool = False

    ALLOWED_EXECUTION_MODES: ClassVar[set[str]] = {
        "vlm_only",
        "vlm_plus_segmenter",
        "specialist_segmenter",
        "measurement_only",
        "insufficient_input",
    }
    ALLOWED_LOCALIZATION_MODES: ClassVar[set[str]] = {
        "bbox",
        "region",
        "score",
        "measurement",
    }
    ALLOWED_SEGMENTATION_MODES: ClassVar[set[str]] = {
        "none",
        "candidate_mask",
        "anatomical_mask",
        "specialist_mask",
    }
    ALLOWED_DIAGNOSIS_USABLE_LEVELS: ClassVar[set[str]] = {
        "observation_only",
        "candidate_support",
        "measurement_support",
        "exploratory_only",
        "not_usable",
    }
    ALLOWED_EVIDENCE_TYPES: ClassVar[set[str]] = {
        "visual_observation",
        "candidate_mask",
        "anatomical_measurement",
        "image_feature_quantification",
        "clinical_context",
        "differential_reasoning",
    }

    def __post_init__(self) -> None:
        if not self.task_name:
            raise ValueError("visual task_name is required")
        if not self.target:
            raise ValueError("visual task target is required")
        if not self.required_modalities:
            raise ValueError("visual task required_modalities is required")
        if self.execution_mode not in self.ALLOWED_EXECUTION_MODES:
            raise ValueError(f"unsupported visual execution_mode: {self.execution_mode}")
        if self.localization_mode not in self.ALLOWED_LOCALIZATION_MODES:
            raise ValueError(f"unsupported visual localization_mode: {self.localization_mode}")
        if self.segmentation_mode not in self.ALLOWED_SEGMENTATION_MODES:
            raise ValueError(f"unsupported visual segmentation_mode: {self.segmentation_mode}")
        if self.diagnosis_usable_level not in self.ALLOWED_DIAGNOSIS_USABLE_LEVELS:
            raise ValueError(
                f"unsupported visual diagnosis_usable_level: {self.diagnosis_usable_level}"
            )
        if self.evidence_type not in self.ALLOWED_EVIDENCE_TYPES:
            raise ValueError(f"unsupported visual evidence_type: {self.evidence_type}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_name": self.task_name,
            "target": self.target,
            "required_modalities": list(self.required_modalities),
            "output": self.output,
            "measurements": list(self.measurements),
            "reason": self.reason,
            "execution_mode": self.execution_mode,
            "localization_mode": self.localization_mode,
            "segmentation_mode": self.segmentation_mode,
            "diagnosis_usable_level": self.diagnosis_usable_level,
            "evidence_type": self.evidence_type,
            "measurement_dependencies": list(self.measurement_dependencies),
            "measurement_usable": bool(self.measurement_usable),
        }

    @classmethod
    def from_protocol_task(
        cls,
        payload: dict[str, Any],
        measurements: list[str] | None = None,
    ) -> "VisualTask":
        target = str(payload.get("target") or "")
        execution_mode = str(payload.get("execution_mode") or "vlm_plus_segmenter")
        task_name = str(
            payload.get("task")
            or payload.get("task_name")
            or cls._task_name_from_target(target, execution_mode)
        )
        return cls(
            task_name=task_name,
            target=target or cls._target_from_task_name(task_name),
            required_modalities=[
                str(modality) for modality in payload.get("required_modalities") or []
            ],
            output=str(payload.get("output") or "mask"),
            measurements=list(measurements or payload.get("measurements") or []),
            reason=str(payload.get("reason") or ""),
            execution_mode=execution_mode,
            localization_mode=str(payload.get("localization_mode") or "bbox"),
            segmentation_mode=str(payload.get("segmentation_mode") or "candidate_mask"),
            diagnosis_usable_level=str(
                payload.get("diagnosis_usable_level") or "candidate_support"
            ),
            evidence_type=str(payload.get("evidence_type") or cls._evidence_type_for_execution_mode(execution_mode)),
            measurement_dependencies=[
                str(item) for item in payload.get("measurement_dependencies") or []
            ],
            measurement_usable=bool(payload.get("measurement_usable", False)),
        )

    @staticmethod
    def _task_name_from_target(target: str, execution_mode: str) -> str:
        if not target:
            return ""
        if execution_mode in {"vlm_plus_segmenter", "specialist_segmenter"}:
            return f"segment_{target}"
        if execution_mode == "measurement_only":
            return f"measure_{target}"
        return f"assess_{target}"

    @staticmethod
    def _target_from_task_name(task_name: str) -> str:
        normalized = task_name
        for prefix in ("segment_", "measure_", "assess_"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
        return normalized or task_name

    @staticmethod
    def _evidence_type_for_execution_mode(execution_mode: str) -> str:
        return {
            "vlm_only": "visual_observation",
            "vlm_plus_segmenter": "candidate_mask",
            "specialist_segmenter": "candidate_mask",
            "measurement_only": "anatomical_measurement",
            "insufficient_input": "visual_observation",
        }.get(execution_mode, "visual_observation")


@dataclass(frozen=True)
class VisualToolCapability:
    """Static declaration of what a visual tool can do."""

    tool_name: str
    supported_modalities: list[str]
    supported_tasks: list[str]
    output: str
    priority: int = 0
    role: str = "specialist_segmenter"
    supported_execution_modes: list[str] = field(default_factory=list)
    backend_type: str = ""
    interface_contract: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tool_name:
            raise ValueError("visual tool_name is required")
        if not self.supported_modalities:
            raise ValueError("visual tool supported_modalities is required")
        if not self.supported_tasks:
            raise ValueError("visual tool supported_tasks is required")

    def supports(
        self,
        modality: str,
        task_name: str,
        target: str | None = None,
        execution_mode: str | None = None,
    ) -> bool:
        modality_ok = self._supports_modality(modality)
        task_ok = (
            task_name in self.supported_tasks
            or (target is not None and target in self.supported_tasks)
            or "generic_lesion_candidate" in self.supported_tasks
        )
        mode_ok = self._supports_execution_mode(execution_mode)
        return modality_ok and task_ok and mode_ok

    def _supports_execution_mode(self, execution_mode: str | None) -> bool:
        if not execution_mode or not self.supported_execution_modes:
            return True
        return execution_mode in self.supported_execution_modes

    def _supports_modality(self, modality: str) -> bool:
        normalized = self._normalize_modality(modality)
        supported = {self._normalize_modality(item) for item in self.supported_modalities}
        if normalized in supported:
            return True
        modality_family = {
            "FLAIR": "MRI",
            "T1": "MRI",
            "T1CE": "MRI",
            "T2": "MRI",
            "MRI FLAIR": "MRI",
            "MRI T1": "MRI",
            "MRI T1CE": "MRI",
            "MRI T2": "MRI",
        }.get(normalized)
        return bool(modality_family and modality_family in supported)

    @staticmethod
    def _normalize_modality(modality: str) -> str:
        normalized = str(modality).strip().upper().replace("_", " ").replace("-", "")
        aliases = {
            "XRAY": "XRAY",
            "X RAY": "XRAY",
            "X光": "XRAY",
            "X 光": "XRAY",
            "T1CE": "T1CE",
            "T1 CE": "T1CE",
        }
        return aliases.get(normalized, normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "supported_modalities": list(self.supported_modalities),
            "supported_tasks": list(self.supported_tasks),
            "output": self.output,
            "priority": self.priority,
            "role": self.role,
            "supported_execution_modes": list(self.supported_execution_modes),
            "backend_type": self.backend_type,
            "interface_contract": dict(self.interface_contract),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VisualToolCapability":
        return cls(
            tool_name=payload["tool_name"],
            supported_modalities=list(payload.get("supported_modalities") or []),
            supported_tasks=list(payload.get("supported_tasks") or []),
            output=payload.get("output", "mask"),
            priority=int(payload.get("priority", 0)),
            role=payload.get("role", "specialist_segmenter"),
            supported_execution_modes=list(payload.get("supported_execution_modes") or []),
            backend_type=str(payload.get("backend_type") or ""),
            interface_contract=dict(payload.get("interface_contract") or {}),
        )


@dataclass(frozen=True)
class SegmentationResult:
    """Task-level segmentation outcome after routing and QC."""

    task_name: str
    target: str
    status: str
    mask_path: str
    overlay_path: str
    measurements: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    completeness: dict[str, Any] = field(default_factory=dict)
    diagnosis_usable: bool | None = None
    selected_tool: dict[str, Any] | None = None

    ALLOWED_STATUSES: ClassVar[set[str]] = {
        "completed",
        "missing_input",
        "no_capable_tool",
        "low_quality",
    }

    def __post_init__(self) -> None:
        if self.status not in self.ALLOWED_STATUSES:
            raise ValueError(f"unsupported segmentation status: {self.status}")
        if self.diagnosis_usable is None:
            object.__setattr__(self, "diagnosis_usable", self.status == "completed")
        if self.status != "completed" and self.diagnosis_usable:
            raise ValueError("only completed segmentation can be diagnosis_usable")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "task_name": self.task_name,
            "target": self.target,
            "status": self.status,
            "mask_path": self.mask_path,
            "overlay_path": self.overlay_path,
            "measurements": dict(self.measurements),
            "quality": dict(self.quality),
            "completeness": dict(self.completeness),
            "diagnosis_usable": bool(self.diagnosis_usable),
        }
        if self.selected_tool is not None:
            payload["selected_tool"] = dict(self.selected_tool)
        return payload


@dataclass(frozen=True)
class VisualEvidence:
    """Image-only observations. Final diagnosis is intentionally excluded."""

    femoral_head_shape: str
    collapse: bool
    sclerosis: str
    cystic_change: str
    joint_space_narrowing: bool
    joint_space: str
    lesion_mask: str
    confidence: float
    texture_abnormality_score: float
    lesion_area_ratio: float
    collapse_ratio: float
    joint_space_width: str
    lesion_detected: bool = False
    lesion_location: str = "未定位"
    segmentation_quality: str = "not_available"
    visual_output_mode: str = "vlm_plus_segmenter"
    segmentation_status: str = "unknown"
    fallback_mode: str | None = None
    segmentation_status_reason: str | None = None
    whole_tumor_volume_ml: float | None = None
    tumor_core_volume_ml: float | None = None
    enhancing_tumor_volume_ml: float | None = None
    edema_present: bool | None = None
    mass_effect: str | None = None
    suspected_visual_findings: list[str] = field(default_factory=list)
    disease_target: str | None = None
    measurements: dict[str, Any] = field(default_factory=dict)
    completeness: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    structured_visual_facts: list[dict[str, Any]] = field(default_factory=list)
    segmentation_results: list[dict[str, Any]] = field(default_factory=list)
    visual_tool_plan: list[dict[str, Any]] = field(default_factory=list)
    evidence_items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "femoral_head_shape": self.femoral_head_shape,
            "collapse": self.collapse,
            "sclerosis": self.sclerosis,
            "cystic_change": self.cystic_change,
            "joint_space_narrowing": self.joint_space_narrowing,
            "joint_space": self.joint_space,
            "lesion_mask": self.lesion_mask,
            "confidence": self.confidence,
            "texture_abnormality_score": self.texture_abnormality_score,
            "lesion_area_ratio": self.lesion_area_ratio,
            "collapse_ratio": self.collapse_ratio,
            "joint_space_width": self.joint_space_width,
            "lesion_detected": self.lesion_detected,
            "lesion_location": self.lesion_location,
            "segmentation_quality": self.segmentation_quality,
            "visual_output_mode": self.visual_output_mode,
            "segmentation_status": self.segmentation_status,
            "suspected_visual_findings": list(self.suspected_visual_findings),
        }
        optional_fields = {
            "whole_tumor_volume_ml": self.whole_tumor_volume_ml,
            "tumor_core_volume_ml": self.tumor_core_volume_ml,
            "enhancing_tumor_volume_ml": self.enhancing_tumor_volume_ml,
            "edema_present": self.edema_present,
            "mass_effect": self.mass_effect,
            "disease_target": self.disease_target,
            "fallback_mode": self.fallback_mode,
            "segmentation_status_reason": self.segmentation_status_reason,
        }
        payload.update({key: value for key, value in optional_fields.items() if value is not None})
        if self.measurements:
            payload["measurements"] = dict(self.measurements)
        if self.completeness:
            payload["completeness"] = dict(self.completeness)
        if self.findings:
            payload["findings"] = [dict(item) for item in self.findings]
        if self.structured_visual_facts:
            payload["structured_visual_facts"] = [
                dict(item) for item in self.structured_visual_facts
            ]
        if self.segmentation_results:
            payload["segmentation_results"] = [dict(item) for item in self.segmentation_results]
        if self.visual_tool_plan:
            payload["visual_tool_plan"] = [dict(item) for item in self.visual_tool_plan]
        if self.evidence_items:
            payload["evidence_items"] = [dict(item) for item in self.evidence_items]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VisualEvidence":
        if "diagnosis" in payload or "diagnostic_tendency" in payload:
            raise ValueError("VisualEvidence cannot contain final diagnosis fields")
        return cls(
            femoral_head_shape=payload.get("femoral_head_shape", "未评估"),
            collapse=payload["collapse"],
            sclerosis=payload.get("sclerosis", "未评估"),
            cystic_change=payload.get("cystic_change", "未评估"),
            joint_space_narrowing=payload["joint_space_narrowing"],
            joint_space=payload.get("joint_space", "未评估"),
            lesion_mask=payload.get("lesion_mask", "not_generated"),
            confidence=payload.get("confidence", 0.0),
            texture_abnormality_score=payload.get("texture_abnormality_score", 0.0),
            lesion_area_ratio=payload.get("lesion_area_ratio", 0.0),
            collapse_ratio=payload.get("collapse_ratio", 0.0),
            joint_space_width=payload.get("joint_space_width", "unknown"),
            lesion_detected=payload.get("lesion_detected", False),
            lesion_location=payload.get("lesion_location", "未定位"),
            segmentation_quality=payload.get("segmentation_quality", "not_available"),
            visual_output_mode=payload.get("visual_output_mode", "vlm_plus_segmenter"),
            segmentation_status=payload.get("segmentation_status", "unknown"),
            fallback_mode=payload.get("fallback_mode"),
            segmentation_status_reason=payload.get("segmentation_status_reason"),
            whole_tumor_volume_ml=payload.get("whole_tumor_volume_ml"),
            tumor_core_volume_ml=payload.get("tumor_core_volume_ml"),
            enhancing_tumor_volume_ml=payload.get("enhancing_tumor_volume_ml"),
            edema_present=payload.get("edema_present"),
            mass_effect=payload.get("mass_effect"),
            suspected_visual_findings=list(payload.get("suspected_visual_findings", [])),
            disease_target=payload.get("disease_target"),
            measurements=dict(payload.get("measurements", {})),
            completeness=dict(payload.get("completeness", {})),
            findings=[
                dict(item) for item in payload.get("findings", [])
            ],
            structured_visual_facts=[
                dict(item) for item in payload.get("structured_visual_facts", [])
            ],
            segmentation_results=[
                dict(item) for item in payload.get("segmentation_results", [])
            ],
            visual_tool_plan=[
                dict(item) for item in payload.get("visual_tool_plan", [])
            ],
            evidence_items=[
                dict(item) for item in payload.get("evidence_items", [])
            ],
        )


@dataclass(frozen=True)
class VisualAnalysisResult:
    """Structured output from the vision agent to the diagnosis agent."""

    image_path: str
    modality: str
    body_part: str
    visual_evidence: VisualEvidence
    image_outputs: ImageOutputs
    requested_targets: list[str] = field(default_factory=list)
    requested_features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_path": self.image_path,
            "modality": self.modality,
            "body_part": self.body_part,
            "image_outputs": self.image_outputs.to_dict(),
            "requested_targets": list(self.requested_targets),
            "requested_features": list(self.requested_features),
            "visual_evidence": self.visual_evidence.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VisualAnalysisResult":
        if "diagnosis" in payload or "diagnostic_tendency" in payload:
            raise ValueError("VisualAnalysisResult cannot contain final diagnosis fields")
        image_outputs_payload = payload.get(
            "image_outputs",
            {
                "original_image_path": payload["image_path"],
                "mask_path": "not_generated",
                "overlay_path": "not_generated",
            },
        )
        return cls(
            image_path=payload["image_path"],
            modality=payload["modality"],
            body_part=payload["body_part"],
            requested_targets=list(payload.get("requested_targets", [])),
            requested_features=list(payload.get("requested_features", [])),
            image_outputs=ImageOutputs.from_dict(image_outputs_payload),
            visual_evidence=VisualEvidence.from_dict(payload["visual_evidence"]),
        )


@dataclass(frozen=True)
class DiagnosisVisualInput:
    """Normalized visual payload consumed by the diagnosis agent."""

    visual_result: VisualAnalysisResult

    def to_dict(self) -> dict[str, Any]:
        payload = self.visual_result.to_dict()
        evidence = payload["visual_evidence"]
        return {
            "image_path": payload["image_path"],
            "modality": payload["modality"],
            "body_part": payload["body_part"],
            "image_outputs": payload["image_outputs"],
            "requested_targets": payload["requested_targets"],
            "requested_features": payload["requested_features"],
            "visual_evidence": evidence,
            "measurements": dict(evidence.get("measurements", {})),
            "completeness": dict(evidence.get("completeness", {})),
            "findings": [
                dict(item) for item in evidence.get("findings", [])
            ],
            "structured_visual_facts": [
                dict(item) for item in evidence.get("structured_visual_facts", [])
            ],
            "segmentation_results": [
                dict(item) for item in evidence.get("segmentation_results", [])
            ],
            "visual_tool_plan": [
                dict(item) for item in evidence.get("visual_tool_plan", [])
            ],
            "evidence_items": [
                dict(item) for item in evidence.get("evidence_items", [])
            ],
            "segmentation_quality": evidence.get("segmentation_quality", "not_available"),
        }

    @classmethod
    def from_visual_result(cls, payload: dict[str, Any]) -> "DiagnosisVisualInput":
        return cls(visual_result=VisualAnalysisResult.from_dict(payload))


@dataclass(frozen=True)
class SkillDescriptor:
    """Small skill identity saved in memory and attached to reports."""

    disease: str
    skill_id: str
    skill_type: str
    evidence_level: str
    source: str
    warning: str | None = None
    path_type: str | None = None
    safety_gate: dict[str, Any] = field(default_factory=dict)
    discovery_metadata: dict[str, Any] = field(default_factory=dict)
    source_documents: list[dict[str, Any]] = field(default_factory=list)
    source_priority: list[dict[str, Any]] = field(default_factory=list)
    guideline_source: dict[str, Any] = field(default_factory=dict)
    guideline_extraction: dict[str, Any] = field(default_factory=dict)
    guideline_conflicts: list[dict[str, Any]] = field(default_factory=list)
    quality_control: dict[str, Any] = field(default_factory=dict)
    imaging_evidence_protocol: dict[str, Any] = field(default_factory=dict)
    quantitative_evidence_protocol: dict[str, Any] = field(default_factory=dict)
    differential_diagnosis_protocol: dict[str, Any] = field(default_factory=dict)
    clinical_context_protocol: dict[str, Any] = field(default_factory=dict)
    integrated_reasoning_protocol: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.skill_type == "data_mined_hypothesis":
            if self.evidence_level != "low":
                raise ValueError("Hypothesis skills must use low evidence_level")
            if not self.warning:
                raise ValueError("Hypothesis skills must carry a warning")
        if self.skill_type == "guideline_based" and self.evidence_level == "low":
            raise ValueError("Guideline skills cannot be labeled low evidence")
        if self.skill_type == "guideline_based" and self.guideline_extraction:
            citations = self.guideline_extraction.get("citations") or []
            if not citations:
                raise ValueError(
                    "Guideline skills with guideline_extraction must carry citations"
                )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "disease": self.disease,
            "skill_id": self.skill_id,
            "skill_type": self.skill_type,
            "evidence_level": self.evidence_level,
            "source": self.source,
            "path_type": self.path_type or self._default_path_type(),
        }
        if self.warning:
            payload["warning"] = self.warning
        if self.safety_gate:
            payload["safety_gate"] = dict(self.safety_gate)
        if self.discovery_metadata:
            payload["discovery_metadata"] = dict(self.discovery_metadata)
        if self.source_documents:
            payload["source_documents"] = [dict(document) for document in self.source_documents]
        if self.source_priority:
            payload["source_priority"] = [dict(source) for source in self.source_priority]
        if self.guideline_source:
            payload["guideline_source"] = dict(self.guideline_source)
        if self.guideline_extraction:
            payload["guideline_extraction"] = dict(self.guideline_extraction)
        if self.guideline_conflicts:
            payload["guideline_conflicts"] = [
                dict(conflict) for conflict in self.guideline_conflicts
            ]
        if self.quality_control:
            payload["quality_control"] = dict(self.quality_control)
        for key in (
            "imaging_evidence_protocol",
            "quantitative_evidence_protocol",
            "differential_diagnosis_protocol",
            "clinical_context_protocol",
            "integrated_reasoning_protocol",
        ):
            value = getattr(self, key)
            if value:
                payload[key] = dict(value)
        return payload

    def _default_path_type(self) -> str:
        if self.skill_type == "data_mined_hypothesis":
            return "privileged_knowledge_discovery"
        return "guideline_aware"

    @classmethod
    def from_skill(cls, skill: dict[str, Any]) -> "SkillDescriptor":
        return cls(
            disease=skill["disease_name"],
            skill_id=skill["skill_id"],
            skill_type=skill["skill_type"],
            evidence_level=skill["evidence_level"],
            source=skill["source"],
            warning=skill.get("warning"),
            path_type=skill.get("path_type"),
            safety_gate=dict(skill.get("safety_gate", {})),
            discovery_metadata=dict(skill.get("discovery_metadata", {})),
            source_documents=[dict(document) for document in skill.get("source_documents", [])],
            source_priority=[dict(source) for source in skill.get("source_priority", [])],
            guideline_source=dict(skill.get("guideline_source", {})),
            guideline_extraction=dict(skill.get("guideline_extraction", {})),
            guideline_conflicts=[dict(conflict) for conflict in skill.get("guideline_conflicts", [])],
            quality_control=dict(skill.get("quality_control", {})),
            imaging_evidence_protocol=dict(skill.get("imaging_evidence_protocol", {})),
            quantitative_evidence_protocol=dict(skill.get("quantitative_evidence_protocol", {})),
            differential_diagnosis_protocol=dict(skill.get("differential_diagnosis_protocol", {})),
            clinical_context_protocol=dict(skill.get("clinical_context_protocol", {})),
            integrated_reasoning_protocol=dict(skill.get("integrated_reasoning_protocol", {})),
        )
