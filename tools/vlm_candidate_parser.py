from __future__ import annotations

from typing import Any


def parse_vlm_candidates(
    raw: dict[str, Any],
    *,
    image_id: str,
    view_hint: str,
    source_image_path: str | None = None,
) -> list[dict[str, Any]]:
    """Convert VLM-localized findings into bounded evidence items.

    The parser intentionally does not produce measurement support. A VLM region
    is treated as candidate visual evidence until later QC or specialist tools
    validate it.
    """

    if not isinstance(raw, dict):
        return []
    findings = raw.get("findings")
    if not isinstance(findings, list):
        return []

    evidence_items: list[dict[str, Any]] = []
    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            continue
        target = str(finding.get("target") or "").strip()
        if not target:
            continue

        bbox, bbox_limitation = _normalize_bbox(finding.get("bbox"))
        polygon = _normalize_polygon(finding.get("polygon"))
        has_location = bool(bbox or polygon)
        limitations = ["vlm_candidate_not_measurement"]
        if bbox_limitation:
            limitations.append(bbox_limitation)
        if not has_location:
            limitations.append("no_valid_location")

        diagnosis_level = "candidate_support" if has_location else "observation_only"
        evidence_items.append(
            {
                "target": target,
                "display_name": str(finding.get("display_name") or target),
                "image_id": image_id,
                "view_hint": view_hint,
                "source_image_path": source_image_path,
                "evidence_type": "visual_observation",
                "execution_mode": "vlm_only",
                "visual_observation": {
                    "status": "candidate_present" if has_location else "observed_unlocalized",
                    "rationale": str(finding.get("rationale") or finding.get("description") or ""),
                    "laterality": _normalize_side(finding.get("side") or finding.get("laterality")),
                },
                "segmentation": {
                    "status": "not_requested",
                    "quality": "not_available",
                },
                "measurements": _measurements_payload(bbox=bbox, polygon=polygon),
                "quality": {
                    "source": "vlm",
                    "confidence": _normalize_confidence(finding.get("confidence")),
                    "localization_status": "localized_candidate"
                    if has_location
                    else "unlocalized_observation",
                },
                "diagnosis_usable": has_location,
                "diagnosis_usable_level": diagnosis_level,
                "limitations": limitations,
                "finding_id": str(finding.get("finding_id") or f"{image_id}_{index:03d}_{target}"),
            }
        )
    return evidence_items


def _normalize_bbox(value: Any) -> tuple[list[int] | None, str | None]:
    if not isinstance(value, list) or len(value) != 4:
        return None, None
    try:
        bbox = [int(round(float(item))) for item in value]
    except (TypeError, ValueError):
        return None, "invalid_bbox"
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        return None, "invalid_bbox"
    if min(bbox) < 0:
        return None, "invalid_bbox"
    return bbox, None


def _normalize_polygon(value: Any) -> list[list[int]] | None:
    if not isinstance(value, list) or len(value) < 3:
        return None
    points: list[list[int]] = []
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            return None
        try:
            x = int(round(float(point[0])))
            y = int(round(float(point[1])))
        except (TypeError, ValueError):
            return None
        if x < 0 or y < 0:
            return None
        points.append([x, y])
    return points


def _measurements_payload(
    *,
    bbox: list[int] | None,
    polygon: list[list[int]] | None,
) -> dict[str, Any]:
    measurements: dict[str, Any] = {"measurement_usable": False}
    if bbox:
        measurements["bbox"] = bbox
    if polygon:
        measurements["polygon"] = polygon
    return measurements


def _normalize_confidence(value: Any) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0.0:
        return 0.0
    if confidence > 1.0:
        return 1.0
    return round(confidence, 4)


def _normalize_side(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"left", "l", "左", "左侧"}:
        return "left"
    if text in {"right", "r", "右", "右侧"}:
        return "right"
    if text in {"bilateral", "both", "双侧"}:
        return "bilateral"
    return None
