from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts.medical_contracts import VisualTask, VisualToolCapability


class VisualToolRegistry:
    """Loads and queries visual tool capabilities."""

    REQUIRED_BACKEND_CONTRACT_FIELDS = {
        "input_contract",
        "output_contract",
        "quality_gate",
        "diagnosis_boundary",
    }
    ALLOWED_BACKEND_TYPES = {
        "vlm_only",
        "vlm_plus_segmenter",
        "specialist_segmenter",
        "measurement_only",
    }

    def __init__(self, tools: list[VisualToolCapability] | None = None) -> None:
        self.tools = tools or []

    @classmethod
    def from_file(cls, path: Path | str) -> "VisualToolRegistry":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VisualToolRegistry":
        raw_tools = payload.get("tools") or []
        if isinstance(raw_tools, dict):
            raw_tools = [
                {"tool_name": tool_name, **tool_payload}
                for tool_name, tool_payload in raw_tools.items()
            ]
        return cls([VisualToolCapability.from_dict(tool) for tool in raw_tools])

    def get(self, tool_name: str) -> VisualToolCapability:
        for tool in self.tools:
            if tool.tool_name == tool_name:
                return tool
        raise KeyError(tool_name)

    def backend_contracts(self) -> dict[str, dict[str, Any]]:
        contracts: dict[str, dict[str, Any]] = {}
        for tool in sorted(self.tools, key=lambda item: item.priority, reverse=True):
            if not tool.backend_type:
                continue
            contracts.setdefault(
                tool.backend_type,
                {
                    "tool_name": tool.tool_name,
                    "role": tool.role,
                    "supported_modalities": list(tool.supported_modalities),
                    "supported_tasks": list(tool.supported_tasks),
                    "supported_execution_modes": list(tool.supported_execution_modes),
                    **dict(tool.interface_contract),
                },
            )
        return contracts

    def validate_backend_contracts(self) -> list[str]:
        errors: list[str] = []
        for tool in self.tools:
            backend_type = tool.backend_type
            if not backend_type and not tool.interface_contract:
                continue
            if backend_type not in self.ALLOWED_BACKEND_TYPES:
                errors.append(f"{tool.tool_name} unsupported backend_type: {backend_type}")
            if not tool.interface_contract:
                errors.append(f"{tool.tool_name} interface_contract is required")
                continue
            for field in sorted(self.REQUIRED_BACKEND_CONTRACT_FIELDS):
                if field not in tool.interface_contract:
                    errors.append(f"{tool.tool_name} interface_contract.{field} is required")
            input_contract = tool.interface_contract.get("input_contract")
            if isinstance(input_contract, dict) and not input_contract.get("required_fields"):
                errors.append(
                    f"{tool.tool_name} interface_contract.input_contract.required_fields is required"
                )
            output_contract = tool.interface_contract.get("output_contract")
            if isinstance(output_contract, dict) and not output_contract.get("artifact_types"):
                errors.append(
                    f"{tool.tool_name} interface_contract.output_contract.artifact_types is required"
                )
        return errors

    def find_best_tool(
        self,
        task: VisualTask,
        available_modalities: list[str],
    ) -> VisualToolCapability | None:
        candidates: list[VisualToolCapability] = []
        for tool in self.tools:
            if any(
                tool.supports(
                    modality=modality,
                    task_name=task.task_name,
                    target=task.target,
                    execution_mode=task.execution_mode,
                )
                for modality in available_modalities
            ):
                candidates.append(tool)
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda tool: (
                tool.role != "candidate_segmenter",
                tool.priority,
            ),
            reverse=True,
        )[0]


class VisualToolRouter:
    """Routes skill visual_protocol tasks to capable visual tools."""

    def __init__(self, registry: VisualToolRegistry | None = None) -> None:
        self.registry = registry or VisualToolRegistry.from_file(
            Path("tools/visual_tool_registry.yaml")
        )

    def plan_from_protocol(self, visual_protocol: dict[str, Any]) -> list[dict[str, Any]]:
        available_modalities = [
            str(modality) for modality in visual_protocol.get("available_modalities") or []
        ]
        measurements = list(visual_protocol.get("measurements") or [])
        plan = []
        for raw_task in self._protocol_tasks(visual_protocol):
            task = VisualTask.from_protocol_task(
                raw_task,
                measurements=self._measurements_for_task(
                    target=VisualTask.from_protocol_task(raw_task).target,
                    measurements=measurements,
                ),
            )
            missing = self._missing_modalities(task.required_modalities, available_modalities)
            if missing:
                plan.append(
                    self._with_safety_fields(
                        {
                            "task": task.to_dict(),
                            "status": "missing_input",
                            "execution_mode": "insufficient_input"
                            if task.execution_mode == "insufficient_input"
                            else task.execution_mode,
                            "selected_tool": None,
                            "reason": self._requires_modality_reason(missing),
                            "diagnosis_usable_without_qc": False,
                        },
                        task,
                    )
                )
                continue
            tool = self.registry.find_best_tool(task, available_modalities)
            if tool is None:
                plan.append(
                    self._with_safety_fields(
                        {
                            "task": task.to_dict(),
                            "status": "no_capable_tool",
                            "execution_mode": task.execution_mode,
                            "selected_tool": None,
                            "reason": "No registered visual tool can satisfy this task.",
                            "diagnosis_usable_without_qc": False,
                        },
                        task,
                    )
                )
                continue
            plan.append(
                self._with_safety_fields(
                    {
                        "task": task.to_dict(),
                        "status": "runnable",
                        "execution_mode": task.execution_mode,
                        "selected_tool": tool.to_dict(),
                        "reason": self._selected_tool_reason(task, tool),
                        "diagnosis_usable_without_qc": self._diagnosis_usable_without_qc(task, tool),
                    },
                    task,
                )
            )
        return plan

    def plan_from_skill(self, skill: dict[str, Any]) -> list[dict[str, Any]]:
        protocol = skill.get("imaging_evidence_protocol") or skill.get("visual_protocol") or {}
        return self.plan_from_protocol(dict(protocol))

    def _protocol_tasks(self, visual_protocol: dict[str, Any]) -> list[dict[str, Any]]:
        tasks = [
            dict(task)
            for task in visual_protocol.get("alignment_tasks") or []
            if isinstance(task, dict)
        ]
        tasks.extend(
            self._task_from_finding_target(target)
            for target in visual_protocol.get("finding_targets") or []
            if isinstance(target, dict)
        )
        return tasks

    def _task_from_finding_target(self, finding_target: dict[str, Any]) -> dict[str, Any]:
        execution_mode = str(finding_target.get("execution_mode") or "vlm_plus_segmenter")
        segmentation_mode = str(finding_target.get("segmentation_mode") or "")
        if not segmentation_mode:
            segmentation_mode = (
                "none"
                if execution_mode in {"vlm_only", "measurement_only", "insufficient_input"}
                else "candidate_mask"
            )
        localization_mode = str(finding_target.get("localization_mode") or "")
        if not localization_mode:
            localization_mode = "measurement" if execution_mode == "measurement_only" else "bbox"
        diagnosis_level = str(finding_target.get("diagnosis_usable_level") or "")
        if not diagnosis_level:
            diagnosis_level = (
                "not_usable"
                if execution_mode == "insufficient_input"
                else "observation_only"
                if execution_mode == "vlm_only"
                else "measurement_support"
                if execution_mode == "measurement_only"
                else "candidate_support"
            )
        evidence_type = str(finding_target.get("evidence_type") or "")
        if not evidence_type:
            evidence_type = (
                "visual_observation"
                if execution_mode in {"vlm_only", "insufficient_input"}
                else "anatomical_measurement"
                if execution_mode == "measurement_only"
                else "candidate_mask"
            )
        measurement_dependencies = [
            str(item) for item in finding_target.get("measurement_dependencies") or []
        ]
        measurement_usable = bool(finding_target.get("measurement_usable", False))
        return {
            **finding_target,
            "execution_mode": execution_mode,
            "segmentation_mode": segmentation_mode,
            "localization_mode": localization_mode,
            "diagnosis_usable_level": diagnosis_level,
            "evidence_type": evidence_type,
            "measurement_dependencies": measurement_dependencies,
            "measurement_usable": measurement_usable,
        }

    def _plan_safety_fields(self, task: VisualTask) -> dict[str, Any]:
        return {
            "evidence_type": task.evidence_type,
            "diagnosis_usable_level": task.diagnosis_usable_level,
            "measurement_dependencies": list(task.measurement_dependencies),
            "measurement_usable": bool(task.measurement_usable),
        }

    def _with_safety_fields(self, item: dict[str, Any], task: VisualTask) -> dict[str, Any]:
        return {**item, **self._plan_safety_fields(task)}

    def _diagnosis_usable_without_qc(self, task: VisualTask, tool: VisualToolCapability) -> bool:
        if task.diagnosis_usable_level in {"exploratory_only", "not_usable"}:
            return False
        if task.execution_mode in {"vlm_plus_segmenter", "measurement_only"}:
            return False
        return tool.role != "candidate_segmenter"

    def _missing_modalities(
        self,
        required_modalities: list[str],
        available_modalities: list[str],
    ) -> list[str]:
        available = {self._normalize_modality(modality) for modality in available_modalities}
        return [
            modality
            for modality in required_modalities
            if self._normalize_modality(modality) not in available
        ]

    def _measurements_for_task(self, target: str, measurements: list[str]) -> list[str]:
        if not measurements:
            return []
        return [
            measurement
            for measurement in measurements
            if self._target_for_measurement(measurement) == target
        ]

    def _target_for_measurement(self, measurement: str) -> str:
        mapping = {
            "whole_tumor_volume_ml": "whole_tumor",
            "tumor_core_volume_ml": "tumor_core",
            "enhancing_tumor_volume_ml": "enhancing_tumor",
            "edema_present": "edema",
            "mass_effect": "mass_effect",
        }
        return mapping.get(measurement, measurement)

    def _normalize_modality(self, modality: str) -> str:
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

    def _requires_modality_reason(self, modalities: list[str]) -> str:
        if len(modalities) == 1:
            return f"Requires {modalities[0]} modality"
        return f"Requires {', '.join(modalities)} modalities"

    def _selected_tool_reason(
        self,
        task: VisualTask,
        tool: VisualToolCapability,
    ) -> str:
        mode_reasons = {
            "vlm_only": (
                f"Selected {tool.tool_name} for VLM observation; no lesion mask will be treated "
                "as measurement-grade evidence."
            ),
            "vlm_plus_segmenter": (
                f"Selected {tool.tool_name}; VLM localizes a candidate box and segmentation "
                "requires QC before diagnosis use."
            ),
            "specialist_segmenter": (
                f"Selected {tool.tool_name} as a specialist segmenter for this modality/task."
            ),
            "measurement_only": (
                f"Selected {tool.tool_name} for measurement/score extraction without forcing "
                "a lesion mask."
            ),
            "insufficient_input": "Required input is missing; visual execution is blocked.",
        }
        return mode_reasons.get(
            task.execution_mode,
            f"Selected {tool.tool_name} for {task.task_name}.",
        )
