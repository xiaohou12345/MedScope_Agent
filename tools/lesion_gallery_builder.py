from __future__ import annotations

from typing import Any

from contracts.medical_contracts import LesionGallery


def build_lesion_gallery(
    visual_evidence_bundle: dict[str, Any] | None,
    visual_fact_usage: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a display-ready lesion gallery from visual evidence and usage audit."""

    bundle = visual_evidence_bundle or {}
    findings = [
        dict(finding)
        for finding in bundle.get("findings") or []
        if isinstance(finding, dict)
    ]
    usage_by_id = _usage_by_finding_id(visual_fact_usage or {})
    items: list[dict[str, Any]] = []
    for finding_index, finding in enumerate(findings, start=1):
        regions = finding.get("regions")
        if not isinstance(regions, list) or not regions:
            regions = [finding.get("measurements") or {}]
        for region_index, region_payload in enumerate(regions, start=1):
            region = dict(region_payload) if isinstance(region_payload, dict) else {}
            finding_id = str(finding.get("finding_id") or f"finding_{finding_index}")
            usage = usage_by_id.get(finding_id, _candidate_usage(finding))
            measurements = _region_measurements(region=region, finding=finding, usage=usage)
            image_paths = _image_paths(region=region, finding=finding, measurements=measurements)
            items.append(
                {
                    "finding_id": finding_id,
                    "region_id": region.get("region_id") or f"r{region_index}",
                    "target": finding.get("target"),
                    "display_name": finding.get("display_name") or finding.get("target"),
                    "status": finding.get("status") or usage.get("status"),
                    "usage": {
                        "status": usage.get("usage_status", "candidate"),
                        "reason": usage.get("usage_reason")
                        or "候选视觉证据，需结合 evidence bundle 和诊断审计解释。",
                    },
                    "laterality": region.get("laterality")
                    or measurements.get("laterality")
                    or usage.get("laterality"),
                    "anatomical_zone": region.get("anatomical_zone")
                    or measurements.get("anatomical_zone")
                    or usage.get("anatomical_zone"),
                    "image_paths": image_paths,
                    "measurements": measurements,
                    "quality": {
                        "alignment_status": measurements.get("box_mask_alignment", {}).get("status")
                        if isinstance(measurements.get("box_mask_alignment"), dict)
                        else usage.get("alignment_status"),
                        "quality_level": usage.get("quality_level"),
                    },
                }
            )
    return LesionGallery(items=items).to_dict()


def _usage_by_finding_id(visual_fact_usage: dict[str, Any]) -> dict[str, dict[str, Any]]:
    usage_by_id: dict[str, dict[str, Any]] = {}
    for usage_status, key in (("used", "used"), ("excluded", "excluded")):
        facts = visual_fact_usage.get(key)
        if not isinstance(facts, list):
            continue
        for fact in facts:
            if not isinstance(fact, dict) or not fact.get("finding_id"):
                continue
            usage_by_id[str(fact["finding_id"])] = {
                **fact,
                "usage_status": usage_status,
                "usage_reason": (
                    fact.get("exclusion_reason")
                    if usage_status == "excluded"
                    else fact.get("summary_text")
                )
                or fact.get("summary_text"),
            }
    return usage_by_id


def _candidate_usage(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "usage_status": "candidate",
        "status": finding.get("status"),
        "usage_reason": finding.get("evidence_text") or finding.get("description"),
    }


def _region_measurements(
    region: dict[str, Any],
    finding: dict[str, Any],
    usage: dict[str, Any],
) -> dict[str, Any]:
    measurements = {}
    if isinstance(finding.get("measurements"), dict):
        measurements.update(finding["measurements"])
    if isinstance(region.get("measurements"), dict):
        measurements.update(region["measurements"])
    for key in (
        "area_px",
        "area_ratio_in_image",
        "area_ratio_in_anatomy",
        "bbox",
        "centroid",
        "laterality",
        "anatomical_zone",
    ):
        if key in region:
            measurements[key] = region[key]
        elif key in usage and key not in measurements:
            measurements[key] = usage[key]
    return measurements


def _image_paths(
    region: dict[str, Any],
    finding: dict[str, Any],
    measurements: dict[str, Any],
) -> dict[str, Any]:
    return {
        "comparison_path": region.get("comparison_path")
        or finding.get("comparison_path")
        or measurements.get("comparison_path"),
        "overlay_path": region.get("overlay_path")
        or finding.get("overlay_path")
        or measurements.get("overlay_path"),
        "mask_path": region.get("mask_path")
        or finding.get("mask_path")
        or measurements.get("mask_path"),
    }
