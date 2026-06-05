from __future__ import annotations

from typing import Any


class VisualProtocolValidator:
    """Validates the visual protocol contract used by image-skill alignment."""

    def validate_skill(self, skill: dict[str, Any]) -> dict[str, Any]:
        if skill.get("skill_type") != "guideline_based":
            return {
                "valid": True,
                "status": "not_required",
                "errors": [],
                "warnings": [],
            }
        return self.validate(skill.get("visual_protocol"))

    def validate_evidence_protocol(self, skill: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []

        if skill.get("skill_type") != "guideline_based":
            return {
                "valid": True,
                "status": "not_required",
                "errors": [],
                "warnings": [],
            }

        imaging = skill.get("imaging_evidence_protocol")
        quantitative = skill.get("quantitative_evidence_protocol")
        clinical = skill.get("clinical_context_protocol")
        integrated = skill.get("integrated_reasoning_protocol")

        self._validate_imaging_evidence_protocol(imaging, errors, warnings)
        self._validate_quantitative_evidence_protocol(quantitative, errors)
        self._validate_clinical_context_protocol(clinical, errors)
        self._validate_integrated_reasoning_protocol(integrated, errors)

        return {
            "valid": not errors,
            "status": "valid" if not errors else "invalid",
            "errors": errors,
            "warnings": warnings,
        }

    def validate(self, visual_protocol: Any) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []

        if not isinstance(visual_protocol, dict) or not visual_protocol:
            return {
                "valid": False,
                "status": "invalid",
                "errors": ["visual_protocol is required for guideline_based skill"],
                "warnings": [],
            }

        self._require_text(
            visual_protocol,
            key="disease_target",
            field="visual_protocol.disease_target",
            errors=errors,
        )
        self._validate_alignment_tasks(visual_protocol.get("alignment_tasks"), errors)
        self._validate_required_modalities(visual_protocol.get("required_modalities"), errors)
        self._validate_required_next_images(visual_protocol.get("required_next_images"), errors)
        self._validate_diagnosis_scope(visual_protocol.get("diagnosis_scope"), errors, warnings)
        self._validate_optional_insufficiency_rules(
            visual_protocol.get("insufficiency_rules"),
            warnings,
        )

        return {
            "valid": not errors,
            "status": "valid" if not errors else "invalid",
            "errors": errors,
            "warnings": warnings,
        }

    def _validate_alignment_tasks(self, value: Any, errors: list[str]) -> None:
        if not isinstance(value, list) or not value:
            errors.append("visual_protocol.alignment_tasks is required")
            return
        for index, task in enumerate(value):
            field = f"visual_protocol.alignment_tasks[{index}]"
            if not isinstance(task, dict):
                errors.append(f"{field} must be an object")
                continue
            self._require_text(task, key="task", field=f"{field}.task", errors=errors)
            required_modalities = task.get("required_modalities")
            if not self._non_empty_list(required_modalities):
                errors.append(f"{field}.required_modalities is required")

    def _validate_required_modalities(self, value: Any, errors: list[str]) -> None:
        if not isinstance(value, dict) or not value:
            errors.append("visual_protocol.required_modalities is required")
            return
        for target, modalities in value.items():
            if not str(target).strip():
                errors.append("visual_protocol.required_modalities contains an empty target")
            if not self._non_empty_list(modalities):
                errors.append(f"visual_protocol.required_modalities.{target} is required")

    def _validate_required_next_images(self, value: Any, errors: list[str]) -> None:
        if not isinstance(value, list) or not value:
            errors.append("visual_protocol.required_next_images is required")
            return
        for index, image in enumerate(value):
            field = f"visual_protocol.required_next_images[{index}]"
            if not isinstance(image, dict):
                errors.append(f"{field} must be an object")
                continue
            for key in ("modality", "region", "reason"):
                self._require_text(image, key=key, field=f"{field}.{key}", errors=errors)

    def _validate_diagnosis_scope(
        self,
        value: Any,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        if not isinstance(value, dict):
            errors.append("visual_protocol.diagnosis_scope is required")
            return
        if not self._non_empty_list(value.get("allowed")):
            warnings.append("visual_protocol.diagnosis_scope.allowed should list supported conclusions")
        if not self._non_empty_list(value.get("blocked")):
            warnings.append("visual_protocol.diagnosis_scope.blocked should list forbidden conclusions")

    def _validate_optional_insufficiency_rules(self, value: Any, warnings: list[str]) -> None:
        if value is None:
            warnings.append("visual_protocol.insufficiency_rules is recommended")
            return
        if not isinstance(value, list):
            warnings.append("visual_protocol.insufficiency_rules should be a list")
            return
        for index, rule in enumerate(value):
            if not isinstance(rule, dict):
                warnings.append(f"visual_protocol.insufficiency_rules[{index}] should be an object")
                continue
            if not str(rule.get("condition") or "").strip():
                warnings.append(f"visual_protocol.insufficiency_rules[{index}].condition is recommended")
            if not str(rule.get("reason") or "").strip():
                warnings.append(f"visual_protocol.insufficiency_rules[{index}].reason is recommended")

    def _validate_imaging_evidence_protocol(
        self,
        value: Any,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        if not isinstance(value, dict) or not value:
            errors.append("imaging_evidence_protocol is required")
            return
        self._require_text(
            value,
            key="disease_target",
            field="imaging_evidence_protocol.disease_target",
            errors=errors,
        )
        finding_targets = value.get("finding_targets")
        if not isinstance(finding_targets, list) or not finding_targets:
            errors.append("imaging_evidence_protocol.finding_targets is required")
            return
        for index, finding in enumerate(finding_targets):
            field = f"imaging_evidence_protocol.finding_targets[{index}]"
            if not isinstance(finding, dict):
                errors.append(f"{field} must be an object")
                continue
            for key in ("target", "execution_mode", "evidence_type", "diagnosis_usable_level"):
                self._require_text(finding, key=key, field=f"{field}.{key}", errors=errors)
            execution_mode = str(finding.get("execution_mode") or "")
            if execution_mode in {"vlm_plus_segmenter", "measurement_only"}:
                if not str(finding.get("segmentation_mode") or "").strip():
                    errors.append(f"{field}.segmentation_mode is required")
                if not isinstance(finding.get("measurement_dependencies"), list):
                    errors.append(f"{field}.measurement_dependencies must be a list")
            if execution_mode == "vlm_only" and finding.get("segmentation_mode") not in {None, "none"}:
                warnings.append(f"{field}.segmentation_mode should be none for vlm_only")

    def _validate_quantitative_evidence_protocol(self, value: Any, errors: list[str]) -> None:
        if not isinstance(value, dict) or not value:
            errors.append("quantitative_evidence_protocol is required")
            return
        for key in ("image_feature_quantification", "measurement_evidence"):
            if not isinstance(value.get(key), list):
                errors.append(f"quantitative_evidence_protocol.{key} must be a list")

    def _validate_clinical_context_protocol(self, value: Any, errors: list[str]) -> None:
        if not isinstance(value, dict) or not value:
            errors.append("clinical_context_protocol is required")
            return
        if not isinstance(value.get("risk_factors", []), list):
            errors.append("clinical_context_protocol.risk_factors must be a list")
        reasoning_rule = str(value.get("reasoning_rule") or "").lower()
        if not self._states_clinical_context_cannot_confirm(reasoning_rule):
            errors.append(
                "clinical_context_protocol.reasoning_rule must state clinical context cannot confirm diagnosis"
            )

    def _validate_integrated_reasoning_protocol(self, value: Any, errors: list[str]) -> None:
        if not isinstance(value, dict) or not value:
            errors.append("integrated_reasoning_protocol is required")
            return
        required_sections = value.get("required_sections")
        if not isinstance(required_sections, list) or not required_sections:
            errors.append("integrated_reasoning_protocol.required_sections is required")
            return
        if "clinical_context_source" not in required_sections:
            errors.append(
                "integrated_reasoning_protocol.required_sections must include clinical_context_source"
            )
        if not isinstance(value.get("safety_rules", []), list):
            errors.append("integrated_reasoning_protocol.safety_rules must be a list")

    def _states_clinical_context_cannot_confirm(self, value: str) -> bool:
        return (
            ("clinical" in value and "cannot confirm" in value)
            or ("临床" in value and "不能" in value and "确诊" in value)
            or ("clinical risk factor cannot replace imaging confirmation" in value)
        )

    def _require_text(
        self,
        payload: dict[str, Any],
        *,
        key: str,
        field: str,
        errors: list[str],
    ) -> None:
        if not str(payload.get(key) or "").strip():
            errors.append(f"{field} is required")

    def _non_empty_list(self, value: Any) -> bool:
        return isinstance(value, list) and any(str(item).strip() for item in value)
