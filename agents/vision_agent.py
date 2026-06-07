from __future__ import annotations

from typing import Any

from contracts.medical_contracts import ImageOutputs, VisualAnalysisResult, VisualEvidence
from tools.feature_extraction_tool import FeatureExtractionTool
from tools.mask_reader_tool import MaskReaderTool
from tools.nifti_mask_reader_tool import NiftiMaskReaderTool
from tools.nifti_overlay_generation_tool import NiftiOverlayGenerationTool
from tools.overlay_generation_tool import OverlayGenerationTool
from tools.segmentation_tool import SegmentationTool
from tools.visual_quality_gate import VisualQualityGate
from tools.visual_tool_router import VisualToolRouter


class VisionAgent:
    """Extracts structured image evidence without making final diagnoses."""

    def __init__(
        self,
        mask_reader: MaskReaderTool | None = None,
        overlay_generator: OverlayGenerationTool | None = None,
        nifti_mask_reader: NiftiMaskReaderTool | None = None,
        nifti_overlay_generator: NiftiOverlayGenerationTool | None = None,
        segmentation_tool: SegmentationTool | None = None,
        feature_extractor: FeatureExtractionTool | None = None,
        visual_tool_router: VisualToolRouter | None = None,
        quality_gate: VisualQualityGate | None = None,
    ) -> None:
        self.mask_reader = mask_reader or MaskReaderTool()
        self.overlay_generator = overlay_generator or OverlayGenerationTool()
        self.nifti_mask_reader = nifti_mask_reader
        self.nifti_overlay_generator = nifti_overlay_generator
        self.feature_extractor = feature_extractor or FeatureExtractionTool()
        self.segmentation_tool = segmentation_tool or SegmentationTool(
            mask_reader=self.mask_reader,
            overlay_generator=self.overlay_generator,
            feature_extractor=self.feature_extractor,
        )
        self.visual_tool_router = visual_tool_router or VisualToolRouter()
        self.quality_gate = quality_gate or VisualQualityGate()

    def analyze_image(
        self,
        image_path: str,
        disease_skill: dict[str, Any],
    ) -> dict[str, Any]:
        if disease_skill.get("imaging_evidence_protocol"):
            return self.analyze_with_visual_protocol(
                image_path=image_path,
                disease_skill=disease_skill,
            )
        tasks = disease_skill.get("vision_agent_tasks", {})
        evidence = VisualEvidence(
            femoral_head_shape="基本完整",
            collapse=False,
            sclerosis="疑似轻度",
            cystic_change="未明确",
            joint_space_narrowing=False,
            joint_space="未明显狭窄",
            lesion_mask="not_generated_in_mvp",
            confidence=0.78,
            texture_abnormality_score=0.74,
            lesion_area_ratio=0.13,
            collapse_ratio=0.0,
            joint_space_width="preserved",
            lesion_detected=True,
            lesion_location="left femoral head",
            segmentation_quality="simulated",
            suspected_visual_findings=[
                "股骨头负重区纹理异常",
                "未见明显塌陷",
                "关节间隙尚可",
            ],
        )
        return VisualAnalysisResult(
            image_path=image_path,
            modality="xray",
            body_part="hip",
            requested_targets=tasks.get("segmentation_targets", []),
            requested_features=tasks.get("quantitative_features", []),
            image_outputs=ImageOutputs(
                original_image_path=image_path,
                mask_path="data/masks/demo_xray_mask.png",
                overlay_path="data/overlays/demo_xray_overlay.png",
            ),
            visual_evidence=evidence,
        ).to_dict()

    def analyze_with_visual_protocol(
        self,
        image_path: str,
        disease_skill: dict[str, Any],
        mask_path: str | None = None,
        overlay_path: str | None = None,
        segmentation_prompt: dict[str, Any] | None = None,
        output_mask_path: str | None = None,
    ) -> dict[str, Any]:
        protocol = self._visual_protocol_from_skill(disease_skill)
        visual_tool_plan = self.visual_tool_router.plan_from_protocol(protocol)
        if mask_path:
            resolved_overlay_path = overlay_path or self._default_overlay_path(image_path)
            segmentation_tool = self._segmentation_tool_for_mask_path(mask_path)
            segmentation = segmentation_tool.segment_from_mask(
                image_path=image_path,
                mask_path=mask_path,
                overlay_path=resolved_overlay_path,
            )
            return self._visual_result_from_segmentation(
                image_path=image_path,
                disease_skill=disease_skill,
                segmentation=segmentation,
                segmentation_source=segmentation["segmentation_source"],
            )
        if segmentation_prompt and output_mask_path:
            resolved_overlay_path = overlay_path or self._default_overlay_path(image_path)
            segmentation_tool = self._segmentation_tool_for_mask_path(output_mask_path)
            segmentation = segmentation_tool.segment_with_model(
                image_path=image_path,
                prompt=segmentation_prompt,
                mask_path=output_mask_path,
                overlay_path=resolved_overlay_path,
            )
            return self._visual_result_from_segmentation(
                image_path=image_path,
                disease_skill=disease_skill,
                segmentation=segmentation,
                segmentation_source=segmentation["segmentation_source"],
            )
        visual_tool_plan = self._mark_runnable_tasks_without_runtime(visual_tool_plan)
        segmentation_results = self._build_segmentation_results(
            visual_tool_plan=visual_tool_plan,
            features={},
            image_outputs={},
            segmentation_source="not_run_no_runtime_executor",
        )
        evidence_items = self._evidence_items_from_visual_plan(
            visual_tool_plan=visual_tool_plan,
            segmentation_results=segmentation_results,
        )
        evidence = VisualEvidence(
            femoral_head_shape="not_applicable",
            collapse=False,
            sclerosis="not_applicable",
            cystic_change="not_applicable",
            joint_space_narrowing=False,
            joint_space="not_applicable",
            lesion_mask="not_generated",
            confidence=0.0,
            texture_abnormality_score=0.0,
            lesion_area_ratio=0.0,
            collapse_ratio=0.0,
            joint_space_width="not_applicable",
            lesion_detected=False,
            lesion_location="not_assessed",
            segmentation_quality="not_run_no_runtime_executor",
            disease_target=protocol.get("disease_target"),
            measurements=self._empty_measurements_from_protocol(protocol),
            completeness=self._completeness_from_segmentation_results(segmentation_results),
            visual_tool_plan=visual_tool_plan,
            segmentation_results=segmentation_results,
            evidence_items=evidence_items,
            suspected_visual_findings=[
                "视觉工具已完成路由，但当前没有可执行的分割运行时输入。"
            ],
        )
        return VisualAnalysisResult(
            image_path=image_path,
            modality=self._modality_from_protocol_or_path(protocol, image_path),
            body_part=self._body_part_from_protocol(protocol),
            requested_targets=list(protocol.get("segmentation_targets") or []),
            requested_features=list(protocol.get("measurements") or []),
            image_outputs=ImageOutputs(
                original_image_path=image_path,
                mask_path="not_generated",
                overlay_path="not_generated",
            ),
            visual_evidence=evidence,
        ).to_dict()

    def analyze_brats_nifti_ground_truth(
        self,
        image_path: str,
        mask_path: str,
        overlay_path: str,
        disease_skill: dict[str, Any],
    ) -> dict[str, Any]:
        segmentation_tool = SegmentationTool(
            mask_reader=self.nifti_mask_reader or NiftiMaskReaderTool(),
            overlay_generator=self.nifti_overlay_generator or NiftiOverlayGenerationTool(),
            feature_extractor=self.feature_extractor,
            segmentation_source="ground_truth_nifti",
        )
        segmentation = segmentation_tool.segment_from_mask(
            image_path=image_path,
            mask_path=mask_path,
            overlay_path=overlay_path,
        )
        features = segmentation["features"]
        mask_shape = segmentation["mask_shape"]
        image_outputs = segmentation["image_outputs"]
        protocol_payload = self._build_visual_protocol_payload(
            features=features,
            disease_skill=disease_skill,
            image_path=image_path,
            image_outputs=image_outputs,
            segmentation_source=segmentation["segmentation_source"],
        )
        evidence = VisualEvidence(
            femoral_head_shape="not_applicable",
            collapse=False,
            sclerosis="not_applicable",
            cystic_change="not_applicable",
            joint_space_narrowing=False,
            joint_space="not_applicable",
            lesion_mask=mask_path,
            confidence=1.0,
            texture_abnormality_score=0.0,
            lesion_area_ratio=features["whole_tumor_volume_ml"] / max(
                mask_shape["width"] * mask_shape["height"] * mask_shape["depth"], 1
            ),
            collapse_ratio=0.0,
            joint_space_width="not_applicable",
            lesion_detected=features["whole_tumor_volume_ml"] > 0,
            lesion_location="brain tumor mask region",
            segmentation_quality="ground_truth_nifti",
            whole_tumor_volume_ml=features["whole_tumor_volume_ml"],
            tumor_core_volume_ml=self._protocol_consistent_measurement(
                protocol_payload, "tumor_core", features["tumor_core_volume_ml"]
            ),
            enhancing_tumor_volume_ml=self._protocol_consistent_measurement(
                protocol_payload, "enhancing_tumor", features["enhancing_tumor_volume_ml"]
            ),
            edema_present=features["edema_present"],
            mass_effect=features["mass_effect"],
            suspected_visual_findings=[
                "真实 BraTS NIfTI mask 已读取",
                "已生成真实 MRI 切片 overlay 图",
                f"whole tumor 体积估计为 {features['whole_tumor_volume_ml']:.3f} ml",
            ],
            **protocol_payload,
        )
        return VisualAnalysisResult(
            image_path=image_path,
            modality="MRI",
            body_part="brain",
            requested_targets=disease_skill.get("vision_agent_tasks", {}).get(
                "segmentation_targets", []
            ),
            requested_features=disease_skill.get("vision_agent_tasks", {}).get(
                "quantitative_features", []
            ),
            image_outputs=ImageOutputs(
                original_image_path=image_outputs["original_image_path"],
                mask_path=image_outputs["mask_path"],
                overlay_path=image_outputs["overlay_path"],
            ),
            visual_evidence=evidence,
        ).to_dict()

    def analyze_brats_ground_truth(
        self,
        image_path: str,
        mask_path: str,
        overlay_path: str,
        disease_skill: dict[str, Any],
    ) -> dict[str, Any]:
        segmentation = self.segmentation_tool.segment_from_mask(
            image_path=image_path,
            mask_path=mask_path,
            overlay_path=overlay_path,
        )
        features = segmentation["features"]
        mask_shape = segmentation["mask_shape"]
        image_outputs = segmentation["image_outputs"]
        protocol_payload = self._build_visual_protocol_payload(
            features=features,
            disease_skill=disease_skill,
            image_path=image_path,
            image_outputs=image_outputs,
            segmentation_source=segmentation["segmentation_source"],
        )
        evidence = VisualEvidence(
            femoral_head_shape="not_applicable",
            collapse=False,
            sclerosis="not_applicable",
            cystic_change="not_applicable",
            joint_space_narrowing=False,
            joint_space="not_applicable",
            lesion_mask=mask_path,
            confidence=1.0,
            texture_abnormality_score=0.0,
            lesion_area_ratio=features["whole_tumor_volume_ml"] / max(
                mask_shape["width"] * mask_shape["height"] * mask_shape["depth"], 1
            ),
            collapse_ratio=0.0,
            joint_space_width="not_applicable",
            lesion_detected=features["whole_tumor_volume_ml"] > 0,
            lesion_location="brain tumor mask region",
            segmentation_quality=features["segmentation_quality"],
            whole_tumor_volume_ml=features["whole_tumor_volume_ml"],
            tumor_core_volume_ml=self._protocol_consistent_measurement(
                protocol_payload, "tumor_core", features["tumor_core_volume_ml"]
            ),
            enhancing_tumor_volume_ml=self._protocol_consistent_measurement(
                protocol_payload, "enhancing_tumor", features["enhancing_tumor_volume_ml"]
            ),
            edema_present=features["edema_present"],
            mass_effect=features["mass_effect"],
            suspected_visual_findings=[
                "肿瘤区域分割 mask 已生成",
                "已生成原图与 mask 的 overlay 图",
                f"whole tumor 体积估计为 {features['whole_tumor_volume_ml']} ml",
            ],
            **protocol_payload,
        )
        return VisualAnalysisResult(
            image_path=image_path,
            modality="MRI",
            body_part="brain",
            requested_targets=disease_skill.get("vision_agent_tasks", {}).get(
                "segmentation_targets", []
            ),
            requested_features=disease_skill.get("vision_agent_tasks", {}).get(
                "quantitative_features", []
            ),
            image_outputs=ImageOutputs(
                original_image_path=image_outputs["original_image_path"],
                mask_path=image_outputs["mask_path"],
                overlay_path=image_outputs["overlay_path"],
            ),
            visual_evidence=evidence,
        ).to_dict()

    def analyze_brats_with_segmentation_model(
        self,
        image_path: str,
        prompt: dict[str, Any],
        mask_path: str,
        overlay_path: str,
        disease_skill: dict[str, Any],
    ) -> dict[str, Any]:
        segmentation = self.segmentation_tool.segment_with_model(
            image_path=image_path,
            prompt=prompt,
            mask_path=mask_path,
            overlay_path=overlay_path,
        )
        features = segmentation["features"]
        mask_shape = segmentation["mask_shape"]
        image_outputs = segmentation["image_outputs"]
        source = segmentation["segmentation_source"]
        protocol_payload = self._build_visual_protocol_payload(
            features=features,
            disease_skill=disease_skill,
            image_path=image_path,
            image_outputs=image_outputs,
            segmentation_source=segmentation["segmentation_source"],
        )
        evidence = VisualEvidence(
            femoral_head_shape="not_applicable",
            collapse=False,
            sclerosis="not_applicable",
            cystic_change="not_applicable",
            joint_space_narrowing=False,
            joint_space="not_applicable",
            lesion_mask=mask_path,
            confidence=0.0,
            texture_abnormality_score=0.0,
            lesion_area_ratio=features["whole_tumor_volume_ml"] / max(
                mask_shape["width"] * mask_shape["height"] * mask_shape["depth"], 1
            ),
            collapse_ratio=0.0,
            joint_space_width="not_applicable",
            lesion_detected=features["whole_tumor_volume_ml"] > 0,
            lesion_location="brain tumor mask region",
            segmentation_quality=features["segmentation_quality"],
            whole_tumor_volume_ml=features["whole_tumor_volume_ml"],
            tumor_core_volume_ml=self._protocol_consistent_measurement(
                protocol_payload, "tumor_core", features["tumor_core_volume_ml"]
            ),
            enhancing_tumor_volume_ml=self._protocol_consistent_measurement(
                protocol_payload, "enhancing_tumor", features["enhancing_tumor_volume_ml"]
            ),
            edema_present=features["edema_present"],
            mass_effect=features["mass_effect"],
            suspected_visual_findings=[
                f"{source} 模型已生成肿瘤分割 mask",
                "已生成原图与模型 mask 的 overlay 图",
                f"whole tumor 体积估计为 {features['whole_tumor_volume_ml']} ml",
            ],
            **protocol_payload,
        )
        return VisualAnalysisResult(
            image_path=image_path,
            modality="MRI",
            body_part="brain",
            requested_targets=disease_skill.get("vision_agent_tasks", {}).get(
                "segmentation_targets", []
            ),
            requested_features=disease_skill.get("vision_agent_tasks", {}).get(
                "quantitative_features", []
            ),
            image_outputs=ImageOutputs(
                original_image_path=image_outputs["original_image_path"],
                mask_path=image_outputs["mask_path"],
                overlay_path=image_outputs["overlay_path"],
            ),
            visual_evidence=evidence,
        ).to_dict()

    def _visual_result_from_segmentation(
        self,
        image_path: str,
        disease_skill: dict[str, Any],
        segmentation: dict[str, Any],
        segmentation_source: str,
    ) -> dict[str, Any]:
        features = segmentation["features"]
        mask_shape = segmentation["mask_shape"]
        image_outputs = segmentation["image_outputs"]
        protocol = self._visual_protocol_from_skill(disease_skill)
        protocol_payload = self._build_visual_protocol_payload(
            features=features,
            disease_skill=disease_skill,
            image_path=image_path,
            image_outputs=image_outputs,
            segmentation_source=segmentation_source,
        )
        evidence = VisualEvidence(
            femoral_head_shape="not_applicable",
            collapse=False,
            sclerosis="not_applicable",
            cystic_change="not_applicable",
            joint_space_narrowing=False,
            joint_space="not_applicable",
            lesion_mask=image_outputs["mask_path"],
            confidence=1.0 if "ground_truth" in segmentation_source else 0.7,
            texture_abnormality_score=0.0,
            lesion_area_ratio=features.get("whole_tumor_volume_ml", 0.0) / max(
                mask_shape["width"] * mask_shape["height"] * mask_shape["depth"], 1
            ),
            collapse_ratio=0.0,
            joint_space_width="not_applicable",
            lesion_detected=features.get("whole_tumor_volume_ml", 0.0) > 0,
            lesion_location="visual protocol target region",
            segmentation_quality=features.get("segmentation_quality", segmentation_source),
            whole_tumor_volume_ml=features.get("whole_tumor_volume_ml"),
            tumor_core_volume_ml=self._protocol_consistent_measurement(
                protocol_payload, "tumor_core", features.get("tumor_core_volume_ml")
            ),
            enhancing_tumor_volume_ml=self._protocol_consistent_measurement(
                protocol_payload, "enhancing_tumor", features.get("enhancing_tumor_volume_ml")
            ),
            edema_present=features.get("edema_present"),
            mass_effect=features.get("mass_effect"),
            suspected_visual_findings=[
                f"{segmentation_source} 已按 visual_protocol 生成视觉证据",
                "已生成 mask/overlay 并完成任务级 QC",
            ],
            **protocol_payload,
        )
        return VisualAnalysisResult(
            image_path=image_path,
            modality=self._modality_from_protocol_or_path(protocol, image_path),
            body_part=self._body_part_from_protocol(protocol),
            requested_targets=list(protocol.get("segmentation_targets") or []),
            requested_features=list(protocol.get("measurements") or []),
            image_outputs=ImageOutputs(
                original_image_path=image_outputs["original_image_path"],
                mask_path=image_outputs["mask_path"],
                overlay_path=image_outputs["overlay_path"],
            ),
            visual_evidence=evidence,
        ).to_dict()

    def _build_visual_protocol_payload(
        self,
        features: dict[str, Any],
        disease_skill: dict[str, Any],
        image_path: str,
        image_outputs: dict[str, Any] | None = None,
        segmentation_source: str = "unknown",
    ) -> dict[str, Any]:
        protocol = self._visual_protocol_from_skill(disease_skill)
        if not protocol:
            return {}
        available_modalities = [
            str(modality).upper()
            for modality in protocol.get("available_modalities", [])
        ] or self._infer_available_modalities(image_path)
        required_modalities = protocol.get("required_modalities", {})
        measurements: dict[str, Any] = {}
        completeness: dict[str, Any] = {}
        for measurement_name in protocol.get("measurements", []):
            target = self._target_for_measurement(measurement_name)
            required_raw = [str(modality) for modality in required_modalities.get(target, [])]
            required = [modality.upper() for modality in required_raw]
            missing = [
                modality
                for modality in required_raw
                if modality.upper() not in available_modalities
            ]
            feature_value = features.get(measurement_name)
            if missing:
                measurements[measurement_name] = None
                completeness[target] = {
                    "status": "missing",
                    "reason": self._requires_modality_reason(missing),
                }
            elif feature_value is None or feature_value == "not_assessed_in_phase_a":
                measurements[measurement_name] = None
                completeness[target] = {
                    "status": "unassessed",
                    "reason": "Not configured in current prompt",
                }
            else:
                measurements[measurement_name] = self._normalize_measurement_value(feature_value)
                completeness[target] = {
                    "status": "supported",
                    "reason": self._supported_modality_reason(required or available_modalities),
                }
        visual_tool_plan = self.visual_tool_router.plan_from_protocol(protocol)
        segmentation_results = self._build_segmentation_results(
            visual_tool_plan=visual_tool_plan,
            features=features,
            image_outputs=image_outputs or {},
            segmentation_source=segmentation_source,
        )
        evidence_items = self._evidence_items_from_visual_plan(
            visual_tool_plan=visual_tool_plan,
            segmentation_results=segmentation_results,
        )
        return {
            "disease_target": protocol.get("disease_target"),
            "measurements": measurements,
            "completeness": completeness,
            "visual_tool_plan": visual_tool_plan,
            "segmentation_results": segmentation_results,
            "evidence_items": evidence_items,
        }

    def _build_segmentation_results(
        self,
        visual_tool_plan: list[dict[str, Any]],
        features: dict[str, Any],
        image_outputs: dict[str, Any],
        segmentation_source: str,
    ) -> list[dict[str, Any]]:
        results = []
        for planned in visual_tool_plan:
            task = planned["task"]
            if planned["status"] != "runnable":
                results.append(
                    self.quality_gate.skipped_result(
                        task_name=task["task_name"],
                        target=task["target"],
                        status=planned["status"],
                        reason=planned["reason"],
                        selected_tool=planned.get("selected_tool"),
                    ).to_dict()
                )
                continue
            results.append(
                self.quality_gate.evaluate(
                    task_name=task["task_name"],
                    target=task["target"],
                    image_outputs=image_outputs,
                    measurements=self._task_measurements(task, features),
                    segmentation_source=segmentation_source,
                    selected_tool=planned.get("selected_tool"),
                ).to_dict()
            )
        return results

    def _evidence_items_from_visual_plan(
        self,
        visual_tool_plan: list[dict[str, Any]],
        segmentation_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results_by_target = {
            str(result.get("target")): dict(result)
            for result in segmentation_results
            if isinstance(result, dict)
        }
        items: list[dict[str, Any]] = []
        for planned in visual_tool_plan:
            if not isinstance(planned, dict):
                continue
            task = dict(planned.get("task") or {})
            target = str(task.get("target") or "")
            if not target:
                continue
            result = results_by_target.get(target, {})
            diagnosis_level = str(
                planned.get("diagnosis_usable_level")
                or task.get("diagnosis_usable_level")
                or "not_usable"
            )
            execution_mode = str(planned.get("execution_mode") or task.get("execution_mode") or "")
            diagnosis_usable = (
                bool(result.get("diagnosis_usable"))
                if result
                else diagnosis_level not in {"exploratory_only", "not_usable"}
                and planned.get("status") == "runnable"
                and bool(planned.get("diagnosis_usable_without_qc"))
            )
            measurement_usable = bool(task.get("measurement_usable", False)) and diagnosis_usable
            items.append(
                {
                    "target": target,
                    "display_name": task.get("display_name") or target,
                    "evidence_type": planned.get("evidence_type") or task.get("evidence_type") or "visual_observation",
                    "execution_mode": execution_mode,
                    "visual_observation": {
                        "status": planned.get("status"),
                        "reason": planned.get("reason"),
                    },
                    "segmentation": {
                        "status": result.get("status", "not_run"),
                        "mask_path": result.get("mask_path", "not_generated"),
                        "overlay_path": result.get("overlay_path", "not_generated"),
                    },
                    "measurements": {
                        **dict(result.get("measurements") or {}),
                        "measurement_dependencies": list(task.get("measurement_dependencies") or []),
                        "measurement_usable": measurement_usable,
                    },
                    "quality": dict(result.get("quality") or {}),
                    "diagnosis_usable": diagnosis_usable,
                    "diagnosis_usable_level": diagnosis_level,
                    "limitations": list(task.get("limitations") or []),
                }
            )
        return items

    def _task_measurements(
        self,
        task: dict[str, Any],
        features: dict[str, Any],
    ) -> dict[str, Any]:
        measurements = {}
        for measurement_name in task.get("measurements") or []:
            if measurement_name in features:
                measurements[measurement_name] = self._normalize_measurement_value(
                    features[measurement_name]
                )
        if measurements:
            return measurements
        fallback = {
            "whole_tumor": "whole_tumor_volume_ml",
            "tumor_core": "tumor_core_volume_ml",
            "enhancing_tumor": "enhancing_tumor_volume_ml",
        }.get(task.get("target"))
        if fallback and fallback in features:
            measurements[fallback] = self._normalize_measurement_value(features[fallback])
        return measurements

    def _mark_runnable_tasks_without_runtime(
        self,
        visual_tool_plan: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        updated = []
        for item in visual_tool_plan:
            if item.get("status") != "runnable":
                updated.append(item)
                continue
            copied = {
                **item,
                "status": "no_capable_tool",
                "reason": "No runtime executor input was provided for the selected visual tool.",
                "diagnosis_usable_without_qc": False,
            }
            updated.append(copied)
        return updated

    def _empty_measurements_from_protocol(self, protocol: dict[str, Any]) -> dict[str, Any]:
        return {str(measurement): None for measurement in protocol.get("measurements") or []}

    def _visual_protocol_from_skill(self, disease_skill: dict[str, Any]) -> dict[str, Any]:
        return dict(
            disease_skill.get("imaging_evidence_protocol")
            or disease_skill.get("visual_protocol")
            or {}
        )

    def _completeness_from_segmentation_results(
        self,
        segmentation_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        completeness = {}
        for result in segmentation_results:
            target = result.get("target")
            if target:
                completeness[str(target)] = dict(result.get("completeness") or {})
        return completeness

    def _default_overlay_path(self, image_path: str) -> str:
        return str(image_path) + "_overlay.png"

    def _segmentation_tool_for_mask_path(self, mask_path: str) -> SegmentationTool:
        if not self._is_nifti_path(mask_path):
            return self.segmentation_tool
        return SegmentationTool(
            mask_reader=self.nifti_mask_reader or NiftiMaskReaderTool(),
            overlay_generator=self.nifti_overlay_generator or NiftiOverlayGenerationTool(),
            feature_extractor=self.feature_extractor,
            model_backend=self.segmentation_tool.model_backend,
            segmentation_source="ground_truth_nifti",
        )

    def _is_nifti_path(self, path: str) -> bool:
        lowered = str(path).lower()
        return lowered.endswith(".nii") or lowered.endswith(".nii.gz")

    def _modality_from_protocol_or_path(self, protocol: dict[str, Any], image_path: str) -> str:
        modalities = protocol.get("imaging_modalities") or protocol.get("available_modalities") or []
        if modalities:
            return str(modalities[0])
        inferred = self._infer_available_modalities(image_path)
        return "MRI" if inferred else "unknown"

    def _body_part_from_protocol(self, protocol: dict[str, Any]) -> str:
        disease_target = str(protocol.get("disease_target") or "").lower()
        if "glioma" in disease_target or "brain" in disease_target:
            return "brain"
        if "femoral" in disease_target or "hip" in disease_target:
            return "hip"
        return "unknown"

    def _infer_available_modalities(self, image_path: str) -> list[str]:
        path = image_path.lower()
        modalities = []
        for label in ("flair", "t1ce", "t1", "t2"):
            if label in path:
                modalities.append(label.upper())
        return modalities

    def _target_for_measurement(self, measurement_name: str) -> str:
        mapping = {
            "whole_tumor_volume_ml": "whole_tumor",
            "tumor_core_volume_ml": "tumor_core",
            "enhancing_tumor_volume_ml": "enhancing_tumor",
            "edema_present": "edema",
            "mass_effect": "mass_effect",
            "lesion_location": "lesion_location",
        }
        return mapping.get(measurement_name, measurement_name)

    def _normalize_measurement_value(self, value: Any) -> Any:
        if isinstance(value, float):
            return round(value, 3)
        return value

    def _protocol_consistent_measurement(
        self,
        protocol_payload: dict[str, Any],
        target: str,
        value: Any,
    ) -> Any:
        completeness = protocol_payload.get("completeness") or {}
        target_status = completeness.get(target) or {}
        if target_status.get("status") in {"missing", "unassessed"}:
            return None
        return value

    def _requires_modality_reason(self, modalities: list[str]) -> str:
        if len(modalities) == 1:
            return f"Requires {modalities[0]} modality"
        return f"Requires {', '.join(modalities)} modalities"

    def _supported_modality_reason(self, modalities: list[str]) -> str:
        if len(modalities) == 1:
            return f"{modalities[0]} modality available"
        if modalities:
            return f"{', '.join(modalities)} modalities available"
        return "Computed from segmentation output"
