from __future__ import annotations

import json
from typing import Any


def apply_guideline_knowledge_template(knowledge: dict[str, Any], disease_key: str) -> dict[str, Any]:
    """Return a guideline knowledge shaped like formal knowledge/*.yaml entries."""
    normalized = json.loads(json.dumps(knowledge, ensure_ascii=False))
    template = guideline_knowledge_template(disease_key)
    if not template:
        return normalized

    for key, value in template.items():
        if key == "visual_protocol":
            normalized[key] = _merge_dicts(value, normalized.get(key) or {})
        elif key == "vision_agent_tasks":
            normalized[key] = _merge_dicts(value, normalized.get(key) or {})
        elif key == "clinical_features":
            normalized[key] = _merge_dicts(value, normalized.get(key) or {})
        elif key not in normalized or normalized.get(key) in (None, "", [], {}):
            normalized[key] = json.loads(json.dumps(value, ensure_ascii=False))

    if normalized.get("knowledge_type") == "guideline_based":
        for legacy_key in (
            "candidate_observation_rules",
            "discovery_metadata",
            "evidence_summary_mode",
        ):
            normalized.pop(legacy_key, None)
    return normalized


def guideline_knowledge_template(disease_key: str) -> dict[str, Any]:
    templates = {
        "osteoarthritis_or_degenerative_hip_disease": _osteoarthritis_template(),
        "post_traumatic_change": _post_traumatic_change_template(),
        "developmental_dysplasia_related_degeneration": _ddh_degeneration_template(),
    }
    return json.loads(json.dumps(templates.get(disease_key, {}), ensure_ascii=False))


def _merge_dicts(defaults: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(defaults, ensure_ascii=False))
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        elif value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _osteoarthritis_template() -> dict[str, Any]:
    return {
        "clinical_features": {
            "common_symptoms": ["髋关节疼痛", "活动后疼痛加重", "关节僵硬", "活动受限"],
            "risk_factors": ["年龄增长", "既往髋关节损伤", "肥胖或负重增加", "发育性髋关节异常"],
        },
        "required_image_views": ["骨盆/髋关节 X 光正位", "必要时侧位或蛙式位 X 光", "症状与 X 光不符时补充 MRI"],
        "visual_targets": {
            "anatomy": ["髋关节间隙", "股骨头", "髋臼边缘", "软骨下骨"],
            "lesion_features": ["关节间隙狭窄", "骨赘", "软骨下硬化", "退变性股骨头形态不规则"],
        },
        "vision_agent_tasks": {
            "segmentation_targets": ["髋关节间隙", "股骨头/髋臼边缘骨赘候选区", "软骨下硬化候选区"],
            "quantitative_features": ["joint_space_width", "osteophyte_candidate_area", "subchondral_sclerosis_area_ratio"],
        },
        "visual_protocol": {
            "disease_target": "osteoarthritis_or_degenerative_hip_disease",
            "clinical_focus": "骨关节炎或退行性髋关节病变影像评估",
            "imaging_modalities": ["X-ray", "MRI"],
            "available_modalities": ["X-ray", "MRI"],
            "alignment_tasks": [
                {
                    "task": "assess_degenerative_xray_findings",
                    "required_modalities": ["X-ray"],
                    "reason": "X 光可评估关节间隙狭窄、骨赘和软骨下硬化等退变征象。",
                },
                {
                    "task": "assess_soft_tissue_or_bone_marrow_gap",
                    "required_modalities": ["MRI"],
                    "reason": "当 X 光不能解释症状或需要评估软组织/骨髓改变时，需要 MRI。",
                },
            ],
            "required_modalities": {
                "joint_space_narrowing": ["X-ray"],
                "osteophyte": ["X-ray"],
                "subchondral_sclerosis": ["X-ray"],
                "soft_tissue_or_bone_marrow_change": ["MRI"],
            },
            "measurements": ["joint_space_width", "osteophyte_candidate_area", "subchondral_sclerosis_area_ratio"],
            "finding_targets": [
                {
                    "target": "joint_space_narrowing",
                    "display_name": "关节间隙狭窄",
                    "description": "髋关节负重区或局部关节间隙变窄候选征象。",
                    "required_modalities": ["X-ray"],
                    "output": "measurement_or_region",
                    "execution_mode": "measurement_only",
                    "localization_mode": "measurement",
                    "segmentation_mode": "none",
                    "diagnosis_usable_level": "candidate_support",
                    "measurements": ["joint_space_width"],
                    "diagnostic_role": "degenerative_change_supportive_feature",
                },
                {
                    "target": "osteophyte",
                    "display_name": "骨赘",
                    "description": "髋臼或股骨头边缘骨性增生候选区域。",
                    "required_modalities": ["X-ray"],
                    "output": "mask_or_region",
                    "execution_mode": "vlm_plus_segmenter",
                    "localization_mode": "bbox",
                    "segmentation_mode": "candidate_mask",
                    "diagnosis_usable_level": "candidate_support",
                    "measurements": ["osteophyte_candidate_area"],
                    "diagnostic_role": "degenerative_change_supportive_feature",
                },
                {
                    "target": "subchondral_sclerosis",
                    "display_name": "软骨下硬化",
                    "description": "关节退变模式分布的软骨下密度增高候选区域。",
                    "required_modalities": ["X-ray"],
                    "output": "mask_or_region",
                    "execution_mode": "vlm_plus_segmenter",
                    "localization_mode": "bbox",
                    "segmentation_mode": "candidate_mask",
                    "diagnosis_usable_level": "candidate_support",
                    "measurements": ["subchondral_sclerosis_area_ratio"],
                    "diagnostic_role": "degenerative_change_supportive_feature",
                },
            ],
            "insufficiency_rules": [
                {
                    "condition": "hip pain with nondiagnostic X-ray",
                    "status": "partial_evidence",
                    "reason": "X 光退变征象不足或与症状不一致时，需要补充 MRI 或临床复核。",
                }
            ],
            "required_next_images": [
                {
                    "modality": "MRI",
                    "region": "双髋关节",
                    "reason": "当 X 光不能解释症状或需要排除骨髓/软组织病变时补充。",
                }
            ],
            "diagnosis_scope": {
                "allowed": ["说明退变性 X 光征象", "区分支持证据、缺失证据和不确定性", "提示下一步影像检查"],
                "blocked": ["不能仅凭单一候选征象确诊", "不能把缺失征象解释为阴性", "不能替代医生影像诊断"],
            },
        },
    }


def _post_traumatic_change_template() -> dict[str, Any]:
    return {
        "clinical_features": {
            "common_symptoms": ["髋部疼痛", "负重痛", "活动受限"],
            "risk_factors": ["明确外伤史", "既往骨折", "术后或内固定史"],
        },
        "required_image_views": ["髋关节 X 光正位", "必要时侧位 X 光", "疑似隐匿骨折时补充 CT 或 MRI"],
        "visual_targets": {
            "anatomy": ["股骨头", "股骨颈", "髋臼", "近端股骨"],
            "lesion_features": ["骨折线", "陈旧骨折畸形", "外伤后轮廓异常", "术后或内固定改变"],
        },
        "vision_agent_tasks": {
            "segmentation_targets": ["骨折线候选区", "外伤后轮廓异常区"],
            "quantitative_features": ["fracture_line_candidate_length", "contour_irregularity_score"],
        },
        "visual_protocol": {
            "disease_target": "post_traumatic_change",
            "clinical_focus": "髋部外伤后改变影像评估",
            "imaging_modalities": ["X-ray", "CT", "MRI"],
            "available_modalities": ["X-ray", "CT", "MRI"],
            "alignment_tasks": [
                {
                    "task": "assess_traumatic_xray_findings",
                    "required_modalities": ["X-ray"],
                    "reason": "X 光用于评估骨折线、畸形、内固定或术后改变。",
                }
            ],
            "required_modalities": {
                "fracture_line": ["X-ray", "CT"],
                "post_traumatic_deformity": ["X-ray", "CT"],
                "occult_fracture": ["MRI", "CT"],
            },
            "finding_targets": [
                {
                    "target": "fracture_line",
                    "display_name": "骨折线",
                    "description": "股骨头、股骨颈或髋臼附近线样透亮或皮质中断候选征象。",
                    "required_modalities": ["X-ray", "CT"],
                    "output": "mask_or_region",
                    "execution_mode": "vlm_plus_segmenter",
                    "localization_mode": "bbox",
                    "segmentation_mode": "candidate_mask",
                    "diagnosis_usable_level": "candidate_support",
                    "measurements": ["fracture_line_candidate_length"],
                    "diagnostic_role": "traumatic_change_supportive_feature",
                },
                {
                    "target": "post_traumatic_deformity",
                    "display_name": "外伤后轮廓异常",
                    "description": "陈旧骨折、畸形愈合或术后相关轮廓异常候选征象。",
                    "required_modalities": ["X-ray", "CT"],
                    "output": "region_or_score",
                    "execution_mode": "vlm_only",
                    "localization_mode": "score",
                    "segmentation_mode": "none",
                    "diagnosis_usable_level": "observation_only",
                    "measurements": ["contour_irregularity_score"],
                    "diagnostic_role": "traumatic_change_context_feature",
                },
            ],
            "insufficiency_rules": [
                {
                    "condition": "persistent pain after trauma with nondiagnostic X-ray",
                    "status": "partial_evidence",
                    "reason": "X 光未见明确骨折时仍不能排除隐匿骨折或软组织损伤，需要 CT 或 MRI。",
                }
            ],
            "required_next_images": [
                {"modality": "CT 或 MRI", "region": "髋关节", "reason": "外伤后疼痛持续或 X 光不确定时补充。"}
            ],
            "diagnosis_scope": {
                "allowed": ["说明外伤相关候选征象", "提示是否需要 CT/MRI 复查", "区分急性和陈旧改变的不确定性"],
                "blocked": ["不能无外伤史时强行解释为外伤后改变", "不能把 X 光阴性解释为排除隐匿骨折"],
            },
        },
    }


def _ddh_degeneration_template() -> dict[str, Any]:
    return {
        "clinical_features": {
            "common_symptoms": ["髋关节疼痛", "跛行", "活动受限"],
            "risk_factors": ["发育性髋关节发育不良史", "髋臼覆盖不足", "女性或年轻成人髋痛"],
        },
        "required_image_views": ["骨盆/髋关节 X 光正位", "必要时侧位或特殊体位 X 光"],
        "visual_targets": {
            "anatomy": ["髋臼覆盖", "股骨头位置", "关节间隙", "髋臼外上缘"],
            "lesion_features": ["髋臼发育浅", "股骨头外移", "半脱位", "继发退变"],
        },
        "vision_agent_tasks": {
            "segmentation_targets": ["髋臼覆盖候选区", "股骨头位置关系"],
            "quantitative_features": ["acetabular_coverage_score", "lateralization_score"],
        },
        "visual_protocol": {
            "disease_target": "developmental_dysplasia_related_degeneration",
            "clinical_focus": "发育性髋关节异常相关退变影像评估",
            "imaging_modalities": ["X-ray"],
            "available_modalities": ["X-ray"],
            "alignment_tasks": [
                {
                    "task": "assess_acetabular_coverage_and_secondary_degeneration",
                    "required_modalities": ["X-ray"],
                    "reason": "X 光用于评估髋臼覆盖、股骨头外移和继发退变征象。",
                }
            ],
            "required_modalities": {
                "acetabular_coverage": ["X-ray"],
                "femoral_head_lateralization": ["X-ray"],
                "secondary_degeneration": ["X-ray"],
            },
            "finding_targets": [
                {
                    "target": "acetabular_undercoverage",
                    "display_name": "髋臼覆盖不足",
                    "description": "髋臼发育浅或股骨头覆盖不足候选征象。",
                    "required_modalities": ["X-ray"],
                    "output": "measurement_or_region",
                    "execution_mode": "measurement_only",
                    "localization_mode": "measurement",
                    "segmentation_mode": "none",
                    "diagnosis_usable_level": "candidate_support",
                    "measurements": ["acetabular_coverage_score"],
                    "diagnostic_role": "dysplasia_related_feature",
                }
            ],
            "insufficiency_rules": [
                {
                    "condition": "single view cannot assess coverage reliably",
                    "status": "partial_evidence",
                    "reason": "单一体位 X 光可能不足以稳定评估髋臼覆盖和继发退变。",
                }
            ],
            "required_next_images": [
                {"modality": "补充体位 X 光或 MRI", "region": "髋关节", "reason": "用于复核覆盖不足和继发软骨/骨髓改变。"}
            ],
            "diagnosis_scope": {
                "allowed": ["说明髋臼覆盖不足候选征象", "提示继发退变可能性", "说明影像体位限制"],
                "blocked": ["不能仅凭单一截图完成发育异常定量诊断", "不能忽略体位和测量误差"],
            },
        },
    }
