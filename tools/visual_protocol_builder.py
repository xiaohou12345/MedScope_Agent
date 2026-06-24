from __future__ import annotations

import re
from typing import Any


class VisualProtocolBuilder:
    """Builds missing visual_protocol fields from extracted guideline knowledge fields."""

    def build(self, knowledge: dict[str, Any]) -> dict[str, Any]:
        protocol = dict(knowledge.get("visual_protocol") or {})
        required_image_views = self._as_list(knowledge.get("required_image_views"))
        vision_agent_tasks = knowledge.get("vision_agent_tasks") or {}
        measurements = self._as_list(
            protocol.get("measurements")
            or vision_agent_tasks.get("quantitative_features")
        )

        protocol.setdefault("disease_target", self._disease_target(knowledge))
        protocol.setdefault("clinical_focus", f"{knowledge.get('disease_name', '目标疾病')}影像评估")

        imaging_modalities = self._imaging_modalities(
            required_image_views=required_image_views,
            protocol=protocol,
        )
        if imaging_modalities:
            protocol.setdefault("imaging_modalities", imaging_modalities)
            protocol.setdefault("available_modalities", imaging_modalities)

        if measurements:
            protocol.setdefault("measurements", measurements)

        required_modalities = self._required_modalities(
            protocol=protocol,
            required_image_views=required_image_views,
            vision_agent_tasks=vision_agent_tasks,
            measurements=measurements,
        )
        if required_modalities:
            protocol["required_modalities"] = required_modalities

        if not protocol.get("alignment_tasks"):
            protocol["alignment_tasks"] = self._alignment_tasks(required_modalities)

        if not protocol.get("suspected_conditions"):
            disease_name = str(knowledge.get("disease_name") or protocol["disease_target"])
            protocol["suspected_conditions"] = [
                {
                    "disease": disease_name,
                    "reason": "患者描述或图像线索匹配当前 guideline knowledge。",
                }
            ]

        if not protocol.get("required_next_images"):
            protocol["required_next_images"] = [
                {
                    "modality": self._next_image_modality(required_image_views, required_modalities),
                    "region": self._region(knowledge),
                    "reason": "补充满足当前 visual_protocol 的关键影像后，才能完成缺失视觉证据评估。",
                }
            ]

        diagnosis_scope = dict(protocol.get("diagnosis_scope") or {})
        diagnosis_scope.setdefault(
            "allowed",
            [
                "只分析当前图像和 knowledge 支持的视觉证据",
                "说明缺失影像导致的不确定性",
                "给出下一步所需影像检查",
            ],
        )
        diagnosis_scope.setdefault(
            "blocked",
            self._blocked_scope(knowledge, required_image_views),
        )
        protocol["diagnosis_scope"] = diagnosis_scope

        if not protocol.get("insufficiency_rules"):
            rules = self._insufficiency_rules(knowledge, required_image_views)
            if rules:
                protocol["insufficiency_rules"] = rules

        return protocol

    def _disease_target(self, knowledge: dict[str, Any]) -> str:
        extraction = knowledge.get("guideline_extraction") or {}
        if extraction.get("disease_key"):
            return str(extraction["disease_key"])
        knowledge_id = str(knowledge.get("knowledge_id") or "guideline_knowledge")
        return re.sub(r"_guideline_v[\d.]+$", "", knowledge_id)

    def _imaging_modalities(
        self,
        *,
        required_image_views: list[str],
        protocol: dict[str, Any],
    ) -> list[str]:
        values = list(required_image_views)
        for item in self._as_list(protocol.get("imaging_modalities")):
            values.append(item)
        for item in self._as_list(protocol.get("available_modalities")):
            values.append(item)
        required_modalities = protocol.get("required_modalities") or {}
        if isinstance(required_modalities, dict):
            for modalities in required_modalities.values():
                values.extend(self._as_list(modalities))

        modalities: list[str] = []
        for value in values:
            broad = self._broad_modality(value)
            if broad and broad not in modalities:
                modalities.append(broad)
        return modalities

    def _required_modalities(
        self,
        *,
        protocol: dict[str, Any],
        required_image_views: list[str],
        vision_agent_tasks: dict[str, Any],
        measurements: list[str],
    ) -> dict[str, list[str]]:
        current = protocol.get("required_modalities")
        if isinstance(current, dict) and current:
            return {
                str(target): self._as_list(modalities)
                for target, modalities in current.items()
                if str(target).strip() and self._as_list(modalities)
            }

        default_requirements = required_image_views or self._as_list(protocol.get("imaging_modalities"))
        if not default_requirements:
            default_requirements = ["medical image"]

        required_modalities: dict[str, list[str]] = {}
        for target in self._as_list(vision_agent_tasks.get("segmentation_targets")):
            required_modalities[self._field_key(target)] = list(default_requirements)
        for feature in measurements:
            required_modalities[self._field_key(feature)] = list(default_requirements)
        return required_modalities

    def _alignment_tasks(self, required_modalities: dict[str, list[str]]) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for target, modalities in required_modalities.items():
            task_name = f"assess_{self._field_key(target)}"
            tasks.append(
                {
                    "task": task_name,
                    "required_modalities": list(modalities),
                    "reason": f"{target} 需要 {'、'.join(modalities)} 支撑。",
                }
            )
        return tasks

    def _next_image_modality(
        self,
        required_image_views: list[str],
        required_modalities: dict[str, list[str]],
    ) -> str:
        candidates = list(required_image_views)
        for modalities in required_modalities.values():
            candidates.extend(modalities)
        for candidate in candidates:
            if self._broad_modality(candidate) == "MRI":
                return "MRI"
        for candidate in candidates:
            broad = self._broad_modality(candidate)
            if broad:
                return broad
        return "medical image"

    def _region(self, knowledge: dict[str, Any]) -> str:
        text = " ".join(
            [
                str(knowledge.get("disease_name") or ""),
                " ".join(self._as_list((knowledge.get("visual_targets") or {}).get("anatomy"))),
                " ".join(self._as_list(knowledge.get("required_image_views"))),
            ]
        ).lower()
        if any(marker in text for marker in ["股骨头", "髋", "hip", "femoral"]):
            return "双髋关节"
        if any(marker in text for marker in ["脑", "brain", "glioma", "胶质瘤"]):
            return "brain"
        return "target region"

    def _blocked_scope(self, knowledge: dict[str, Any], required_image_views: list[str]) -> list[str]:
        blocked = [
            "不得把缺失影像证据解释为阴性",
            "不得从 missing_input 推断正常",
        ]
        text = self._knowledge_text(knowledge)
        if "x 光可无明显异常" in text or ("x" in text.lower() and "mri" in text.lower()):
            blocked.append("不能将 X 光未见异常解释为无病")
        if "分子" in text or "组织" in text or "histomolecular" in text.lower():
            blocked.append("不能仅凭影像完成最终整合诊断")
        if any(self._broad_modality(view) == "MRI" for view in required_image_views):
            blocked.append("不能在缺少关键 MRI 序列时排除需要 MRI 支撑的病变")
        return blocked

    def _insufficiency_rules(
        self,
        knowledge: dict[str, Any],
        required_image_views: list[str],
    ) -> list[dict[str, str]]:
        text = self._knowledge_text(knowledge)
        has_xray = any(self._broad_modality(view) == "X-ray" for view in required_image_views)
        has_mri = any(self._broad_modality(view) == "MRI" for view in required_image_views)
        if has_xray and has_mri and ("早期" in text or "x 光可无明显异常" in text):
            return [
                {
                    "condition": "suspected early disease with X-ray only",
                    "status": "insufficient_evidence",
                    "reason": "当前 X 光不足以排除需要 MRI 支撑的早期或隐匿病变。",
                }
            ]
        return [
            {
                "condition": "missing required modality",
                "status": "partial_evidence",
                "reason": "当前影像只支持部分 visual_protocol 任务，缺失任务不能解释为阴性。",
            }
        ]

    def _broad_modality(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if any(marker in text for marker in ["x-ray", "xray", "x 光", "x光", "radiograph"]):
            return "X-ray"
        if "mri" in text or text in {"t1", "t1ce", "t2", "flair", "stir"}:
            return "MRI"
        if "ct" in text:
            return "CT"
        if "ultrasound" in text or "超声" in text:
            return "Ultrasound"
        if "fundus" in text or "眼底" in text:
            return "Fundus"
        if "pathology" in text or "病理" in text:
            return "Pathology"
        return ""

    def _field_key(self, value: Any) -> str:
        text = str(value or "").strip()
        normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", text).strip("_")
        return normalized.lower() or "target"

    def _knowledge_text(self, knowledge: dict[str, Any]) -> str:
        return str(knowledge)

    def _as_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if str(value).strip() else []
