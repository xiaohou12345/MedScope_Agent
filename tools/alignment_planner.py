from __future__ import annotations

from typing import Any

from contracts.medical_contracts import AlignmentPlan


class AlignmentPlanner:
    """Builds image-symptom-skill alignment plans from skill visual_protocol."""

    def build_plan(
        self,
        payload: dict[str, Any],
        routing_decision: dict[str, Any],
        disease_skill: dict[str, Any],
    ) -> dict[str, Any]:
        selected_skill = routing_decision.get("selected_skill")
        image_context = self.infer_image_context(payload)
        if not selected_skill:
            return AlignmentPlan(
                selected_skill=None,
                analysis_status="partial_evidence",
                clinical_focus="general medical image triage",
                image_context=image_context,
                visual_tasks=[],
                diagnosis_scope={
                    "allowed": ["提示当前尚未匹配到疾病专用 skill"],
                    "blocked": ["不得输出疾病特异性诊断结论"],
                },
            ).to_dict()

        visual_protocol = disease_skill.get("visual_protocol") or {}
        if not visual_protocol:
            return AlignmentPlan(
                selected_skill=str(selected_skill),
                analysis_status="partial_evidence",
                clinical_focus=str(disease_skill.get("disease_name") or selected_skill),
                image_context=image_context,
                visual_tasks=[],
                diagnosis_scope={
                    "allowed": ["按已选 skill 的可用证据进行有限分析"],
                    "blocked": ["不得把缺失影像证据解释为阴性"],
                },
            ).to_dict()

        visual_tasks = self._build_visual_tasks(visual_protocol, image_context)
        analysis_status = self._determine_status(
            payload=payload,
            image_context=image_context,
            visual_tasks=visual_tasks,
            visual_protocol=visual_protocol,
        )
        required_next_images = self._required_next_images(
            visual_protocol=visual_protocol,
            analysis_status=analysis_status,
        )
        insufficiency_reasons = self._insufficiency_reasons(
            payload=payload,
            analysis_status=analysis_status,
            visual_tasks=visual_tasks,
            visual_protocol=visual_protocol,
        )
        return AlignmentPlan(
            selected_skill=str(selected_skill),
            analysis_status=analysis_status,
            clinical_focus=str(
                visual_protocol.get("clinical_focus")
                or f"{disease_skill.get('disease_name', selected_skill)}影像评估"
            ),
            image_context=image_context,
            visual_tasks=visual_tasks,
            diagnosis_scope=self._diagnosis_scope(visual_protocol),
            suspected_conditions=self._suspected_conditions(
                disease_skill=disease_skill,
                visual_protocol=visual_protocol,
            ),
            required_next_images=required_next_images,
            insufficiency_reasons=insufficiency_reasons,
        ).to_dict()

    def infer_image_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = self._routing_text(payload)
        sequences = []
        for marker, label in (
            ("thin-section", "thin-section CT"),
            ("thin section", "thin-section CT"),
            ("hrct", "HRCT"),
            ("t1ce", "T1ce"),
            ("t1gd", "T1ce"),
            ("flair", "FLAIR"),
            ("stir", "STIR"),
            ("dwi", "DWI"),
            ("t1", "T1"),
            ("t2", "T2"),
        ):
            if marker in text and label not in sequences:
                sequences.append(label)
        if any(marker in text for marker in ["xray", "x-ray", "x 光", "x光", "radiograph"]):
            modality = "xray"
        elif any(marker in text for marker in ["mri", ".nii", "flair", "t1", "t2", "stir"]):
            modality = "MRI"
        elif "ct" in text or "hrct" in text:
            modality = "CT"
        else:
            modality = "unknown"

        if any(marker in text for marker in ["髋", "股骨头", "hip", "femoral"]):
            body_part = "hip"
        elif any(marker in text for marker in ["脑", "brain", "glioma", "胶质瘤", "brats"]):
            body_part = "brain"
        elif any(
            marker in text
            for marker in ["胸", "肺", "chest", "lung", "pulmonary", "ipf", "uip", "hrct"]
        ):
            body_part = "chest"
        else:
            body_part = "unknown"
        return {
            "modality": modality,
            "body_part": body_part,
            "available_sequences": sequences,
            "image_path": payload.get("image_path"),
        }

    def _build_visual_tasks(
        self,
        visual_protocol: dict[str, Any],
        image_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        task_specs = visual_protocol.get("alignment_tasks")
        if not isinstance(task_specs, list):
            task_specs = [
                {
                    "task": task,
                    "required_modalities": modalities,
                    "reason": self._default_missing_reason(task, modalities),
                }
                for task, modalities in (visual_protocol.get("required_modalities") or {}).items()
            ]
        return [
            {
                "task": str(task.get("task") or task.get("name") or ""),
                "required_input": self._format_required_input(task.get("required_modalities")),
                "status": "runnable"
                if self._requirements_satisfied(task.get("required_modalities"), image_context)
                else "missing_input",
                "reason": str(task.get("reason") or self._default_missing_reason(
                    task.get("task") or task.get("name") or "",
                    task.get("required_modalities"),
                )),
            }
            for task in task_specs
            if task.get("task") or task.get("name")
        ]

    def _determine_status(
        self,
        payload: dict[str, Any],
        image_context: dict[str, Any],
        visual_tasks: list[dict[str, Any]],
        visual_protocol: dict[str, Any],
    ) -> str:
        current_modality = self._normalize_requirement(image_context.get("modality"))
        if not self._is_modality_allowed(visual_protocol, current_modality):
            return "contraindicated_or_wrong_modality"
        for rule in visual_protocol.get("insufficiency_rules") or []:
            if self._rule_matches(rule, payload, image_context):
                return str(rule.get("status") or "insufficient_evidence")
        if not visual_tasks:
            return "partial_evidence"
        if all(task["status"] == "runnable" for task in visual_tasks):
            return "evidence_sufficient"
        if any(task["status"] == "runnable" for task in visual_tasks):
            return "partial_evidence"
        return "insufficient_evidence"

    def _required_next_images(
        self,
        visual_protocol: dict[str, Any],
        analysis_status: str,
    ) -> list[dict[str, Any]]:
        if analysis_status == "evidence_sufficient":
            return []
        configured = visual_protocol.get("required_next_images")
        if isinstance(configured, list) and configured:
            return [dict(item) for item in configured if isinstance(item, dict)]
        return [
            {
                "modality": "MRI",
                "region": "target region",
                "reason": "建议补充满足当前 visual_protocol 的关键影像。",
            }
        ]

    def _insufficiency_reasons(
        self,
        payload: dict[str, Any],
        analysis_status: str,
        visual_tasks: list[dict[str, Any]],
        visual_protocol: dict[str, Any],
    ) -> list[str]:
        reasons = [
            str(rule.get("reason"))
            for rule in visual_protocol.get("insufficiency_rules") or []
            if self._rule_matches(rule, payload, {})
            and rule.get("reason")
        ]
        if reasons:
            return reasons
        if analysis_status == "evidence_sufficient":
            return []
        missing_reasons = [
            task["reason"]
            for task in visual_tasks
            if task["status"] == "missing_input" and task.get("reason")
        ]
        if missing_reasons:
            return missing_reasons
        return ["当前上传图像不满足该 skill 的关键影像证据要求。"]

    def _diagnosis_scope(self, visual_protocol: dict[str, Any]) -> dict[str, Any]:
        configured = visual_protocol.get("diagnosis_scope")
        if isinstance(configured, dict):
            return {
                "allowed": list(configured.get("allowed") or []),
                "blocked": list(configured.get("blocked") or []),
            }
        return {
            "allowed": ["只分析当前图像和 skill 支持的视觉证据"],
            "blocked": ["不得把缺失影像证据解释为阴性", "不得从 missing_input 推断正常"],
        }

    def _suspected_conditions(
        self,
        disease_skill: dict[str, Any],
        visual_protocol: dict[str, Any],
    ) -> list[dict[str, Any]]:
        configured = visual_protocol.get("suspected_conditions")
        if isinstance(configured, list) and configured:
            return [dict(item) for item in configured if isinstance(item, dict)]
        disease_name = disease_skill.get("disease_name")
        if not disease_name:
            return []
        return [
            {
                "disease": disease_name,
                "reason": "患者描述或图像线索匹配当前 disease skill。",
            }
        ]

    def _requirements_satisfied(
        self,
        requirements: Any,
        image_context: dict[str, Any],
    ) -> bool:
        if not requirements:
            return False
        if isinstance(requirements, str):
            requirements = [requirements]
        sequences = {
            self._normalize_requirement(sequence)
            for sequence in image_context.get("available_sequences") or []
        }
        modality = self._normalize_requirement(image_context.get("modality"))
        for requirement in requirements:
            normalized = self._normalize_requirement(requirement)
            if normalized == modality or normalized in sequences:
                return True
            if modality == "ct" and ("ct" in normalized or "hrct" in normalized):
                return True
            if normalized.startswith("mri") and modality == "mri":
                parts = normalized.split()
                if len(parts) == 1 or any(part in sequences for part in parts[1:]):
                    return True
        return False

    def _is_modality_allowed(
        self,
        visual_protocol: dict[str, Any],
        current_modality: str,
    ) -> bool:
        configured = {
            self._normalize_requirement(modality)
            for modality in visual_protocol.get("imaging_modalities")
            or visual_protocol.get("available_modalities", [])
        }
        broad_modalities = {"mri", "xray", "ct", "ultrasound", "pathology", "fundus"}
        allowed_modalities = configured & broad_modalities
        if not allowed_modalities:
            return True
        return current_modality in allowed_modalities

    def _rule_matches(
        self,
        rule: dict[str, Any],
        payload: dict[str, Any],
        image_context: dict[str, Any],
    ) -> bool:
        condition = str(rule.get("condition") or "").lower()
        text = self._routing_text(payload)
        modality = self._normalize_requirement(image_context.get("modality"))
        if "x-ray only" in condition or "xray only" in condition or "x 光" in condition:
            if modality and modality != "xray":
                return False
        if "early" in condition or "早期" in condition:
            return self._has_early_or_exclusion_intent(payload)
        keywords = rule.get("keywords") or []
        if keywords:
            return any(str(keyword).lower() in text for keyword in keywords)
        return False

    def _has_early_or_exclusion_intent(self, payload: dict[str, Any]) -> bool:
        text = self._routing_text(payload)
        markers = [
            "早期",
            "一期",
            "1期",
            "i期",
            "排除",
            "能不能判断",
            "刚开始",
            "阴性",
        ]
        return any(marker in text for marker in markers)

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
                symptoms_text,
            ]
        ).lower()

    def _normalize_requirement(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        aliases = {
            "x-ray": "xray",
            "x ray": "xray",
            "x 光": "xray",
            "x光": "xray",
            "radiograph": "xray",
        }
        return aliases.get(text, text)

    def _format_required_input(self, requirements: Any) -> str:
        if isinstance(requirements, list):
            return "/".join(str(item) for item in requirements)
        return str(requirements or "-")

    def _default_missing_reason(self, task: Any, requirements: Any) -> str:
        return f"{task} requires {self._format_required_input(requirements)}."
