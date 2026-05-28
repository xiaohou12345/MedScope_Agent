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
