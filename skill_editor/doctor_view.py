from __future__ import annotations

from typing import Any


def build_doctor_skill_summary(*, skill_key: str, skill: dict[str, Any], draft_exists: bool = False) -> dict[str, Any]:
    clinical = skill.get("clinical_features") or {}
    protocol = skill.get("visual_protocol") or {}
    return {
        "skill_key": skill_key,
        "disease_name": skill.get("disease_name") or skill_key,
        "skill_id": skill.get("skill_id"),
        "skill_type": skill.get("skill_type"),
        "evidence_level": skill.get("evidence_level"),
        "source": skill.get("source"),
        "doctor_summary": {
            "symptom_count": len(clinical.get("common_symptoms") or []),
            "risk_factor_count": len(clinical.get("risk_factors") or []),
            "image_requirement_count": len(skill.get("required_image_views") or []),
            "visual_finding_count": len(protocol.get("finding_targets") or []),
            "source_count": len(skill.get("source_documents") or []),
        },
        "review_status": "draft_saved" if draft_exists else "no_draft",
    }


def build_doctor_skill_view(skill: dict[str, Any]) -> dict[str, Any]:
    clinical = skill.get("clinical_features") or {}
    protocol = skill.get("visual_protocol") or {}
    return {
        "identity": {
            "disease_name": skill.get("disease_name"),
            "skill_id": skill.get("skill_id"),
            "skill_type": skill_type_label(skill.get("skill_type")),
            "evidence_level": evidence_level_label(skill.get("evidence_level")),
            "source": skill.get("source"),
        },
        "clinical_profile": {
            "common_symptoms": list(clinical.get("common_symptoms") or []),
            "risk_factors": list(clinical.get("risk_factors") or []),
        },
        "imaging_requirements": [
            {"label": str(item), "review_prompt": "这个检查是否是诊断该病必须或推荐的影像？"}
            for item in skill.get("required_image_views") or []
        ],
        "visual_findings": doctor_visual_findings(protocol),
        "alignment_tasks": doctor_alignment_tasks(protocol),
        "required_modalities": doctor_required_modalities(protocol),
        "measurements": doctor_measurements(protocol),
        "suspected_conditions": doctor_suspected_conditions(protocol),
        "staging_rules": doctor_staging_rules(skill.get("staging_rules") or {}),
        "safety_notes": doctor_safety_notes(protocol),
        "report_requirements": list((skill.get("report_requirements") or {}).get("include") or []),
        "source_documents": doctor_source_documents(skill.get("source_documents") or []),
        "quality_control": doctor_quality_control(skill.get("quality_control") or {}),
    }


def doctor_visual_findings(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for target in protocol.get("finding_targets") or []:
        if not isinstance(target, dict):
            continue
        findings.append(
            {
                "target": target.get("target"),
                "display_name": target.get("display_name") or target.get("target"),
                "description": target.get("description"),
                "required_modalities": list(target.get("required_modalities") or []),
                "measurements": list(target.get("measurements") or []),
                "diagnostic_role": target.get("diagnostic_role"),
                "execution_mode": target.get("execution_mode"),
                "doctor_execution_label": execution_mode_label(target.get("execution_mode")),
            }
        )
    return findings


def doctor_alignment_tasks(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = []
    for task in protocol.get("alignment_tasks") or []:
        if isinstance(task, dict):
            tasks.append(
                {
                    "task": task.get("task"),
                    "label": _humanize_key(task.get("task")),
                    "required_modalities": list(task.get("required_modalities") or []),
                    "reason": task.get("reason"),
                }
            )
    return tasks


def doctor_required_modalities(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    modalities = protocol.get("required_modalities") or {}
    if not isinstance(modalities, dict):
        return []
    return [
        {"target": str(target), "label": _humanize_key(target), "modalities": list(values or [])}
        for target, values in modalities.items()
    ]


def doctor_measurements(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    measurements = protocol.get("measurements") or {}
    if not isinstance(measurements, dict):
        return []
    rows = []
    for name, value in measurements.items():
        if isinstance(value, dict):
            rows.append(
                {
                    "name": str(name),
                    "label": _humanize_key(name),
                    "description": value.get("description") or value.get("reason") or "",
                    "unit": value.get("unit") or "",
                    "required_modalities": list(value.get("required_modalities") or []),
                }
            )
        else:
            rows.append({"name": str(name), "label": _humanize_key(name), "description": str(value), "unit": "", "required_modalities": []})
    return rows


def doctor_suspected_conditions(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    conditions = []
    for item in protocol.get("suspected_conditions") or []:
        if isinstance(item, dict):
            conditions.append(
                {
                    "condition": item.get("condition") or item.get("disease") or "疑似方向",
                    "reason": item.get("reason"),
                }
            )
    return conditions


def doctor_staging_rules(staging_rules: dict[str, Any]) -> list[dict[str, Any]]:
    stages = []
    for stage, rule in staging_rules.items():
        if isinstance(rule, dict):
            features = []
            for key, value in rule.items():
                if key == "description":
                    continue
                if isinstance(value, list):
                    features.extend(str(item) for item in value)
                else:
                    features.append(str(value))
            stages.append(
                {
                    "stage": str(stage),
                    "label": _humanize_key(stage),
                    "raw_stage": str(stage),
                    "description": str(rule.get("description") or ""),
                    "features": features,
                }
            )
        else:
            stages.append({"stage": str(stage), "label": _humanize_key(stage), "raw_stage": str(stage), "description": str(rule), "features": []})
    return stages


def doctor_safety_notes(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    notes = []
    for rule in protocol.get("insufficiency_rules") or []:
        if isinstance(rule, dict):
            notes.append(
                {
                    "condition": rule.get("condition"),
                    "status": status_label(rule.get("status") or "insufficient_evidence"),
                    "reason": rule.get("reason"),
                }
            )
    for item in protocol.get("required_next_images") or []:
        if isinstance(item, dict):
            notes.append(
                {
                    "condition": "需要补充影像",
                    "status": "建议补充检查",
                    "reason": item.get("reason"),
                    "modality": item.get("modality"),
                    "region": item.get("region"),
                }
            )
    return notes


def doctor_source_documents(documents: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "title": document.get("title") or document.get("source_id") or "未命名来源",
            "publisher": document.get("publisher") or document.get("source_kind"),
            "url": document.get("url"),
            "evidence_note": document.get("evidence_note"),
        }
        for document in documents
        if isinstance(document, dict)
    ]


def doctor_quality_control(quality: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(quality, dict):
        return {"items": [], "doctor_review_notes": []}
    items = [
        {"label": quality_label(key), "value": _stringify_value(value)}
        for key, value in quality.items()
        if key != "doctor_review_notes"
    ]
    notes = []
    for note in quality.get("doctor_review_notes") or []:
        if isinstance(note, dict):
            notes.append({"author": note.get("author"), "note": note.get("note"), "created_at": note.get("created_at")})
        else:
            notes.append({"author": "", "note": str(note), "created_at": ""})
    return {"items": items, "doctor_review_notes": notes}


def skill_type_label(value: object) -> str:
    labels = {
        "guideline_based": "正式指南 Skill",
        "data_mined_hypothesis": "数据挖掘假设 Skill",
    }
    return labels.get(str(value), str(value or "未标注"))


def evidence_level_label(value: object) -> str:
    labels = {"high": "高", "medium": "中", "low": "低", "review_required": "待审核"}
    return labels.get(str(value), str(value or "未标注"))


def execution_mode_label(value: object) -> str:
    labels = {
        "vlm_only": "只做视觉观察，不生成分割 mask",
        "vlm_plus_segmenter": "先定位候选区域，再生成候选分割",
        "specialist_segmenter": "使用专病分割模型",
        "measurement_only": "只做形态或数值测量",
        "insufficient_input": "当前影像不足，不能执行",
    }
    return labels.get(str(value), "按当前工具计划处理")


def status_label(value: object) -> str:
    labels = {
        "insufficient_evidence": "证据不足",
        "required_next_image": "需要补充影像",
        "missing": "缺失",
        "unassessed": "未评估",
        "supported": "已有证据支持",
    }
    return labels.get(str(value), str(value or "未标注"))


def quality_label(key: object) -> str:
    labels = {
        "citation_status": "引用状态",
        "citation_count": "引用数量",
        "missing_url_count": "缺少链接数量",
    }
    return labels.get(str(key), _humanize_key(key))


def _humanize_key(value: object) -> str:
    text = str(value or "").strip()
    labels = {
        "whole_tumor": "全肿瘤范围",
        "tumor_core": "肿瘤核心",
        "enhancing_tumor": "强化肿瘤",
        "edema": "水肿",
        "mass_effect": "占位效应",
        "necrosis": "坏死",
        "collapse": "塌陷",
        "sclerotic_band": "硬化带",
        "cystic_change": "囊性变",
        "joint_space_narrowing": "关节间隙狭窄",
        "imaging_suspicion": "影像疑似方向",
        "integrated_diagnosis_required": "需要整合诊断",
    }
    return labels.get(text, text.replace("_", " "))


def _stringify_value(value: object) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    if isinstance(value, dict):
        return "；".join(f"{_humanize_key(key)}：{_stringify_value(item)}" for key, item in value.items())
    return str(value)
