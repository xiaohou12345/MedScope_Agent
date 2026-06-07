from __future__ import annotations

from typing import Any


def build_structured_visual_facts(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        measurements = dict(finding.get("measurements") or {})
        alignment = dict(measurements.get("box_mask_alignment") or {})
        overlap_qc = dict(finding.get("overlap_qc") or {})
        fact = {
            "finding_id": finding.get("finding_id"),
            "image_id": finding.get("image_id"),
            "view_hint": finding.get("view_hint"),
            "source_image_path": finding.get("source_image_path"),
            "target": finding.get("target"),
            "display_name": finding.get("display_name") or finding.get("target"),
            "status": finding.get("status"),
            "laterality": measurements.get("laterality"),
            "anatomical_zone": measurements.get("anatomy_name"),
            "diagnosis_usable": bool(finding.get("diagnosis_usable", True)),
            "independent_evidence": bool(finding.get("independent_evidence", True)),
            "non_independent_reason": overlap_qc.get("status")
            if not finding.get("independent_evidence", True)
            else None,
            "overlap_with_finding_id": overlap_qc.get("overlap_with_finding_id"),
            "area_px": int(measurements.get("area_px") or 0),
            "area_ratio_in_image": measurements.get("area_ratio_in_image"),
            "area_ratio_in_anatomy": measurements.get("area_ratio_in_anatomy"),
            "bbox": measurements.get("bbox"),
            "centroid": measurements.get("centroid"),
            "alignment_status": alignment.get("status") or "not_assessed",
            "mask_area_inside_prompt_ratio": alignment.get(
                "mask_area_inside_prompt_ratio"
            ),
            "mask_bbox_iou": alignment.get("mask_bbox_iou"),
            "quality_level": (
                dict(
                    dict(finding.get("segmentation_ref") or {}).get("quality") or {}
                ).get("level")
            ),
        }
        fact["summary_text"] = _structured_visual_fact_summary(fact)
        facts.append(fact)
    return facts


def _structured_visual_fact_summary(fact: dict[str, Any]) -> str:
    parts = []
    view = _view_hint_display_name(str(fact.get("view_hint") or ""))
    laterality = fact.get("laterality")
    display_name = str(fact.get("display_name") or fact.get("target") or "finding")
    if laterality:
        display_name = f"{laterality}{display_name}"
    if view:
        display_name = f"{view}：{display_name}"
    parts.append(display_name)
    parts.append(str(fact.get("status") or "unknown_status"))
    if not fact.get("diagnosis_usable", True):
        parts.append("not_diagnosis_usable")
    elif not fact.get("independent_evidence", True):
        parts.append("non_independent_evidence")
    else:
        parts.append("independent_evidence")
    if fact.get("alignment_status"):
        parts.append(f"alignment={fact['alignment_status']}")
    if fact.get("area_ratio_in_anatomy") is not None:
        parts.append(f"area_ratio_in_anatomy={fact['area_ratio_in_anatomy']}")
    elif fact.get("area_ratio_in_image") is not None:
        parts.append(f"area_ratio_in_image={fact['area_ratio_in_image']}")
    return "; ".join(parts)


def _view_hint_display_name(view_hint: str) -> str:
    return {
        "ap_pelvis": "骨盆正位/AP",
        "frog_lateral": "蛙式侧位",
        "lateral": "侧位",
    }.get(view_hint, "")
