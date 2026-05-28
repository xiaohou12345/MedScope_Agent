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
    laterality = fact.get("laterality")
    if laterality:
        parts.append(str(laterality))
    parts.append(str(fact.get("display_name") or fact.get("target") or "finding"))
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
