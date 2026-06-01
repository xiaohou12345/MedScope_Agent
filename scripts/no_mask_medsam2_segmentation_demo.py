from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from contracts.medical_contracts import SegmentationResult
from tools.generic_mask_measurement_tool import GenericMaskMeasurementTool
from tools.medsam2_segmentation_tool import (
    MedSAM2CommandRunner,
    MedSAM2SegmentationTool,
    MissingMedSAM2BackendError,
)
from tools.segmentation_tool import SegmentationTool


DEFAULT_PROMPT_RESULT = Path("output/fake/no_mask_vision_prompt_demo/vision_prompt_result.json")
DEFAULT_OUTPUT_DIR = Path("output/fake/no_mask_medsam2_segmentation_demo")


def run_no_mask_medsam2_segmentation_demo(
    *,
    prompt_result_path: Path | str = DEFAULT_PROMPT_RESULT,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    segmentation_tool: Any | None = None,
    anatomy_mask_path: Path | str | None = None,
    anatomy_name: str = "anatomy",
    anatomy_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prompt_file = Path(prompt_result_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    prompt_result = json.loads(prompt_file.read_text(encoding="utf-8"))
    image_path = Path(prompt_result["image_path"])
    segmentation_prompt = prompt_result.get("segmentation_prompt") or {}
    boxes = segmentation_prompt.get("boxes") or []
    target_regions = _target_regions_from_prompt_result(
        prompt_result=prompt_result,
        segmentation_prompt=segmentation_prompt,
    )
    summary_path = output / "summary.json"
    if not target_regions:
        return _write_summary(
            summary_path,
            {
                "status": "no_prompt_box",
                "prompt_result_path": str(prompt_file),
                "errors": ["segmentation_prompt.boxes is empty"],
            },
        )

    try:
        tool = segmentation_tool or _default_medsam2_segmentation_tool()
    except MissingMedSAM2BackendError as exc:
        return _write_summary(
            summary_path,
            {
                "status": "medsam2_not_ready",
                "prompt_result_path": str(prompt_file),
                "image_path": str(image_path),
                "errors": [str(exc)],
                "next_step": "Configure MEDSAM2_COMMAND_TEMPLATE and rerun this script.",
            },
        )

    try:
        finding_results = [
            _segment_target_region(
                tool=tool,
                image_path=image_path,
                output_dir=output,
                target_region=target_region,
                use_legacy_paths=len(target_regions) == 1,
                anatomy_mask_path=anatomy_mask_path,
                anatomy_name=anatomy_name,
                anatomy_candidates=anatomy_candidates,
            )
            for target_region in target_regions
        ]
    except Exception as exc:
        return _write_summary(
            summary_path,
            {
                "status": "segmentation_error",
                "prompt_result_path": str(prompt_file),
                "image_path": str(image_path),
                "segmentation_prompt": segmentation_prompt,
                "target_regions": target_regions,
                "errors": [str(exc)],
                "next_step": "Fallback to VLM-only visual annotation or configure a working segmentation backend.",
            },
        )
    quality_warnings = _attach_box_mask_alignment_quality_control(finding_results)
    quality_warnings.extend(_attach_overlap_quality_control(finding_results))
    first_result = finding_results[0]
    payload = {
        "status": "ok",
        "prompt_result_path": str(prompt_file),
        "image_path": str(image_path),
        "mask_path": first_result["mask_path"],
        "overlay_path": first_result["overlay_path"],
        "comparison_path": first_result["comparison_path"],
        "summary_path": str(summary_path),
        "segmentation_prompt": segmentation_prompt,
        "measurements": first_result["measurements"],
        "segmentation_result": first_result["segmentation_result"],
        "segmentation_results": [
            dict(item["segmentation_result"]) for item in finding_results
        ],
        "findings": [
            dict(item["finding"]) for item in finding_results
        ],
        "quality_warnings": quality_warnings,
        "diagnosis_usable": any(
            bool(item["segmentation_result"]["diagnosis_usable"])
            for item in finding_results
        ),
    }
    return _write_summary(summary_path, payload)


def _default_medsam2_segmentation_tool() -> SegmentationTool:
    return SegmentationTool(
        model_backend=MedSAM2SegmentationTool(runner=MedSAM2CommandRunner.from_env()),
        segmentation_source="medsam2",
    )


def _target_regions_from_prompt_result(
    *,
    prompt_result: dict[str, Any],
    segmentation_prompt: dict[str, Any],
) -> list[dict[str, Any]]:
    suspected_regions = prompt_result.get("suspected_regions") or []
    if suspected_regions:
        return [
            {
                "region_id": str(index),
                "target": str(region.get("target") or f"candidate_region_{index}"),
                "display_name": _display_name_for_target(
                    str(region.get("display_name") or region.get("target") or "候选区域")
                ),
                "bbox": list(region["bbox"]),
                "confidence": float(region.get("confidence") or 0.0),
                "rationale": str(region.get("rationale") or ""),
                "execution_mode": str(region.get("execution_mode") or "vlm_plus_segmenter"),
                "localization_mode": str(region.get("localization_mode") or "bbox"),
                "segmentation_mode": str(region.get("segmentation_mode") or "candidate_mask"),
                "diagnosis_usable_level": str(
                    region.get("diagnosis_usable_level") or "candidate_support"
                ),
                "prompt": {
                    "source": segmentation_prompt.get("source", "vision_model_bbox"),
                    "boxes": [list(region["bbox"])],
                    "points": [],
                    "image_size": dict(segmentation_prompt.get("image_size") or {}),
                },
            }
            for index, region in enumerate(suspected_regions, start=1)
            if isinstance(region, dict) and region.get("bbox")
        ]
    return [
        {
            "region_id": str(index),
            "target": "candidate_lesion",
            "display_name": "候选病灶区域",
            "bbox": list(box),
            "confidence": 0.0,
            "rationale": "",
            "execution_mode": "vlm_plus_segmenter",
            "localization_mode": "bbox",
            "segmentation_mode": "candidate_mask",
            "diagnosis_usable_level": "candidate_support",
            "prompt": {
                "source": segmentation_prompt.get("source", "vision_model_bbox"),
                "boxes": [list(box)],
                "points": [],
                "image_size": dict(segmentation_prompt.get("image_size") or {}),
            },
        }
        for index, box in enumerate(segmentation_prompt.get("boxes") or [], start=1)
    ]


def _segment_target_region(
    *,
    tool: Any,
    image_path: Path,
    output_dir: Path,
    target_region: dict[str, Any],
    use_legacy_paths: bool,
    anatomy_mask_path: Path | str | None,
    anatomy_name: str,
    anatomy_candidates: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    target = _safe_filename(str(target_region["target"]))
    if use_legacy_paths:
        mask_path = output_dir / "medsam2_mask.png"
        overlay_path = output_dir / "medsam2_overlay.png"
        comparison_path = output_dir / "medsam2_comparison.png"
    else:
        region_index = str(target_region.get("region_id") or len(list(output_dir.glob("medsam2_*_mask.png"))) + 1)
        mask_path = output_dir / f"medsam2_{region_index}_{target}_mask.png"
        overlay_path = output_dir / f"medsam2_{region_index}_{target}_overlay.png"
        comparison_path = output_dir / f"medsam2_{region_index}_{target}_comparison.png"
    segmentation = tool.segment_with_model(
        image_path=str(image_path),
        prompt=target_region["prompt"],
        mask_path=str(mask_path),
        overlay_path=str(overlay_path),
    )
    _write_original_overlay_comparison(
        image_path=image_path,
        overlay_path=overlay_path,
        comparison_path=comparison_path,
    )
    measurements = _measure_with_best_anatomy_candidate(
        image_path=image_path,
        mask_path=mask_path,
        anatomy_mask_path=anatomy_mask_path,
        anatomy_name=anatomy_name,
        anatomy_candidates=anatomy_candidates,
    )
    measurements["box_mask_alignment"] = _box_mask_alignment(
        mask_path=mask_path,
        prompt_bbox=target_region.get("bbox"),
        measurements=measurements,
    )
    segmentation_result = _segmentation_result(
        image_outputs=segmentation["image_outputs"],
        measurements=measurements,
        segmentation_source=segmentation.get("segmentation_source", "medsam2"),
        task_name=f"segment_{target_region['target']}",
        target=str(target_region["target"]),
    )
    segmentation_result["comparison_path"] = str(comparison_path)
    finding = _finding_from_segmentation(
        target_region=target_region,
        mask_path=str(mask_path),
        overlay_path=str(overlay_path),
        comparison_path=str(comparison_path),
        measurements=measurements,
        segmentation_result=segmentation_result,
    )
    return {
        "mask_path": str(mask_path),
        "overlay_path": str(overlay_path),
        "comparison_path": str(comparison_path),
        "measurements": measurements,
        "segmentation_result": segmentation_result,
        "finding": finding,
    }


def _write_original_overlay_comparison(
    *,
    image_path: Path,
    overlay_path: Path,
    comparison_path: Path,
) -> None:
    original = Image.open(image_path).convert("RGB")
    overlay = Image.open(overlay_path).convert("RGB")
    if overlay.size != original.size:
        overlay = overlay.resize(original.size)
    comparison = Image.new("RGB", (original.width + overlay.width, original.height), "white")
    comparison.paste(original, (0, 0))
    comparison.paste(overlay, (original.width, 0))
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    comparison.save(comparison_path)


def _measure_with_best_anatomy_candidate(
    *,
    image_path: Path,
    mask_path: Path,
    anatomy_mask_path: Path | str | None,
    anatomy_name: str,
    anatomy_candidates: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    measurement_tool = GenericMaskMeasurementTool()
    candidates = [
        dict(candidate)
        for candidate in anatomy_candidates or []
        if isinstance(candidate, dict) and candidate.get("mask_path")
    ]
    if not candidates:
        return measurement_tool.measure(
            image_path=image_path,
            mask_path=mask_path,
            anatomy_mask_path=anatomy_mask_path,
            anatomy_name=anatomy_name,
        )

    measured_candidates = []
    for index, candidate in enumerate(candidates):
        measured = measurement_tool.measure(
            image_path=image_path,
            mask_path=mask_path,
            anatomy_mask_path=candidate["mask_path"],
            anatomy_name=str(candidate.get("anatomy_name") or anatomy_name),
        )
        measured["anatomy_match"] = {
            "candidate_index": index,
            "anatomy_name": measured.get("anatomy_name"),
            "mask_path": str(candidate["mask_path"]),
            "overlap_anatomy_px": measured.get("lesion_overlap_anatomy_px"),
            "selection_rule": "max_lesion_overlap_anatomy_px",
        }
        measured_candidates.append(measured)

    measured_candidates.sort(
        key=lambda item: (
            -int(item.get("lesion_overlap_anatomy_px") or 0),
            str(item.get("anatomy_name") or ""),
        )
    )
    best = measured_candidates[0]
    best["anatomy_candidates_evaluated"] = [
        {
            "anatomy_name": item.get("anatomy_name"),
            "mask_path": item.get("anatomy_match", {}).get("mask_path"),
            "overlap_anatomy_px": item.get("lesion_overlap_anatomy_px"),
            "area_ratio_in_anatomy": item.get("lesion_area_ratio_in_anatomy"),
        }
        for item in measured_candidates
    ]
    return best


def _segmentation_result(
    *,
    image_outputs: dict[str, Any],
    measurements: dict[str, Any],
    segmentation_source: str,
    task_name: str = "segment_candidate_lesion",
    target: str = "candidate_lesion",
) -> dict[str, Any]:
    area = float(measurements.get("lesion_area_px") or 0)
    if area <= 0:
        status = "low_quality"
        quality = {
            "score": 0.2,
            "level": "low",
            "warnings": ["lesion mask is empty"],
        }
        completeness = {
            "status": "unassessed",
            "reason": "MedSAM2 candidate mask did not pass QC",
        }
        diagnosis_usable = False
    else:
        status = "completed"
        quality = {
            "score": 0.6,
            "level": "medium",
            "warnings": ["candidate segmentation requires clinical/model QC"],
        }
        completeness = {
            "status": "supported",
            "reason": "Candidate mask generated from vision-model box prompt",
        }
        diagnosis_usable = True
    return SegmentationResult(
        task_name=task_name,
        target=target,
        status=status,
        mask_path=str(image_outputs.get("mask_path") or "not_generated"),
        overlay_path=str(image_outputs.get("overlay_path") or "not_generated"),
        measurements=measurements,
        quality=quality,
        completeness=completeness,
        diagnosis_usable=diagnosis_usable,
        selected_tool={
            "tool_name": "medsam2",
            "role": "candidate_segmenter",
            "segmentation_source": segmentation_source,
        },
    ).to_dict()


def _finding_from_segmentation(
    *,
    target_region: dict[str, Any],
    mask_path: str,
    overlay_path: str,
    comparison_path: str,
    measurements: dict[str, Any],
    segmentation_result: dict[str, Any],
) -> dict[str, Any]:
    finding_id = _finding_id_from_target_region(target_region)
    laterality = _infer_laterality(
        target_region=target_region,
        measurements=measurements,
    )
    regions = [
        {
            "region_id": str(region.get("region_id") or f"r{index}"),
            "mask_path": mask_path,
            "overlay_path": overlay_path,
            "comparison_path": comparison_path,
            "bbox": region.get("bbox"),
            "centroid": region.get("centroid"),
            "area_px": int(region.get("area_px") or 0),
            "area_ratio_in_image": float(region.get("area_ratio_in_image") or 0.0),
            "area_ratio_in_anatomy": region.get("area_ratio_in_anatomy"),
            "laterality": _infer_laterality(
                target_region=target_region,
                measurements=measurements,
                region=region,
            ),
            "anatomical_zone": measurements.get("anatomy_name") or "unknown",
            "measurements": dict(region),
        }
        for index, region in enumerate(measurements.get("regions") or [], start=1)
        if int(region.get("area_px") or 0) > 0
    ]
    return {
        "finding_id": finding_id,
        "target": str(target_region["target"]),
        "display_name": str(target_region.get("display_name") or target_region["target"]),
        "status": "candidate_present" if regions else "candidate_absent",
        "regions": regions,
        "independent_evidence": True,
        "overlap_qc": {"status": "independent_candidate"},
        "confidence": float(target_region.get("confidence") or 0.0),
        "evidence_basis": str(target_region.get("rationale") or ""),
        "execution_mode": str(target_region.get("execution_mode") or "vlm_plus_segmenter"),
        "localization_mode": str(target_region.get("localization_mode") or "bbox"),
        "segmentation_mode": str(target_region.get("segmentation_mode") or "candidate_mask"),
        "diagnosis_usable_level": str(
            target_region.get("diagnosis_usable_level") or "candidate_support"
        ),
        "measurements": {
            "area_px": int(measurements.get("lesion_area_px") or 0),
            "area_ratio_in_image": float(measurements.get("lesion_area_ratio") or 0.0),
            "area_ratio_in_anatomy": measurements.get("lesion_area_ratio_in_anatomy"),
            "anatomy_area_px": measurements.get("anatomy_area_px"),
            "overlap_anatomy_px": measurements.get("lesion_overlap_anatomy_px"),
            "anatomy_name": measurements.get("anatomy_name"),
            "bbox": measurements.get("lesion_bbox"),
            "centroid": measurements.get("lesion_centroid"),
            "laterality": laterality,
            "bbox_size": measurements.get("lesion_bbox_size"),
            "fill_ratio": measurements.get("lesion_fill_ratio"),
            "elongation": measurements.get("lesion_elongation"),
            "mean_intensity": measurements.get("lesion_mean_intensity"),
            "box_mask_alignment": dict(measurements.get("box_mask_alignment") or {}),
            "anatomy_match": dict(measurements.get("anatomy_match") or {}),
            "anatomy_candidates_evaluated": [
                dict(candidate)
                for candidate in measurements.get("anatomy_candidates_evaluated") or []
                if isinstance(candidate, dict)
            ],
        },
        "diagnosis_usable": bool(segmentation_result.get("diagnosis_usable")),
        "segmentation_ref": {
            "task_name": segmentation_result.get("task_name"),
            "selected_tool": dict(segmentation_result.get("selected_tool") or {}),
            "quality": dict(segmentation_result.get("quality") or {}),
            "comparison_path": comparison_path,
        },
    }


def _infer_laterality(
    *,
    target_region: dict[str, Any],
    measurements: dict[str, Any],
    region: dict[str, Any] | None = None,
) -> str:
    anatomy_name = str(measurements.get("anatomy_name") or "").lower()
    if anatomy_name.startswith("left_") or "左" in anatomy_name:
        return "left"
    if anatomy_name.startswith("right_") or "右" in anatomy_name:
        return "right"

    prompt = target_region.get("prompt") or {}
    image_size = prompt.get("image_size") or {}
    width = image_size.get("width")
    try:
        image_width = float(width)
    except (TypeError, ValueError):
        image_width = 0.0
    if image_width <= 0:
        return "unknown"

    centroid = (region or {}).get("centroid") or measurements.get("lesion_centroid")
    if isinstance(centroid, (list, tuple)) and centroid:
        try:
            x_coord = float(centroid[0])
        except (TypeError, ValueError):
            x_coord = -1.0
        if x_coord >= 0:
            return "image_left" if x_coord < image_width / 2 else "image_right"

    bbox = (region or {}).get("bbox") or measurements.get("lesion_bbox") or target_region.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            center_x = (float(bbox[0]) + float(bbox[2])) / 2
        except (TypeError, ValueError):
            return "unknown"
        return "image_left" if center_x < image_width / 2 else "image_right"
    return "unknown"


def _finding_id_from_target_region(target_region: dict[str, Any]) -> str:
    target = _safe_filename(str(target_region["target"]))
    region_id = _safe_filename(str(target_region.get("region_id") or ""))
    if region_id:
        return f"finding_{region_id}_{target}"
    return f"finding_{target}"


def _attach_overlap_quality_control(
    finding_results: list[dict[str, Any]],
    *,
    iou_threshold: float = 0.85,
) -> list[dict[str, Any]]:
    quality_warnings: list[dict[str, Any]] = []
    for current_index, current in enumerate(finding_results):
        current_finding = current["finding"]
        current_finding.setdefault("independent_evidence", True)
        current_finding.setdefault("overlap_qc", {"status": "independent_candidate"})
        if not current_finding.get("diagnosis_usable", True):
            continue
        for previous in finding_results[:current_index]:
            previous_finding = previous["finding"]
            if not previous_finding.get("diagnosis_usable", True):
                continue
            mask_iou = _mask_iou(
                _finding_mask_path(previous_finding),
                _finding_mask_path(current_finding),
            )
            if mask_iou is None or mask_iou < iou_threshold:
                continue
            current_finding["independent_evidence"] = False
            current_finding["overlap_qc"] = {
                "status": "overlaps_existing_finding",
                "overlap_with_finding_id": previous_finding.get("finding_id"),
                "overlap_with_target": previous_finding.get("target"),
                "mask_iou": round(mask_iou, 6),
                "iou_threshold": iou_threshold,
                "interpretation": (
                    "This finding shares nearly the same mask as another finding; "
                    "do not count it as independent diagnostic evidence."
                ),
            }
            warning_text = "overlaps with another finding mask"
            _append_quality_warning(current_finding, warning_text)
            _append_quality_warning(current["segmentation_result"], warning_text)
            quality_warnings.append(
                {
                    "code": "overlapping_candidate_findings",
                    "severity": "warning",
                    "finding_id": current_finding.get("finding_id"),
                    "target": current_finding.get("target"),
                    "overlap_with_finding_id": previous_finding.get("finding_id"),
                    "overlap_with_target": previous_finding.get("target"),
                    "mask_iou": round(mask_iou, 6),
                    "message": (
                        "Two skill findings were segmented to highly overlapping masks; "
                        "the later finding is marked as non-independent evidence."
                    ),
                }
            )
            break
    return quality_warnings


def _attach_box_mask_alignment_quality_control(
    finding_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    quality_warnings: list[dict[str, Any]] = []
    for item in finding_results:
        finding = item["finding"]
        segmentation_result = item["segmentation_result"]
        alignment = (
            finding.get("measurements", {}).get("box_mask_alignment")
            or item.get("measurements", {}).get("box_mask_alignment")
            or {}
        )
        status = alignment.get("status")
        if status == "aligned" or status == "not_assessed":
            continue

        warning_text = "mask alignment with vision-model box prompt requires review"
        if status == "low_alignment":
            warning_text = "mask is poorly aligned with the vision-model box prompt"
            finding["diagnosis_usable"] = False
            segmentation_result["diagnosis_usable"] = False
            segmentation_result["status"] = "low_quality"
            segmentation_result["completeness"] = {
                "status": "unassessed",
                "reason": "MedSAM2 mask is poorly aligned with the vision-model box prompt",
            }
            _set_quality_level(segmentation_result, score=0.25, level="low")
            _set_quality_level(finding, score=0.25, level="low")

        _append_quality_warning(finding, warning_text)
        _append_quality_warning(segmentation_result, warning_text)
        quality_warnings.append(
            {
                "code": (
                    "box_mask_misalignment"
                    if status == "low_alignment"
                    else "box_mask_partial_alignment"
                ),
                "severity": "warning" if status == "partial_alignment" else "error",
                "finding_id": finding.get("finding_id"),
                "target": finding.get("target"),
                "prompt_bbox": alignment.get("prompt_bbox"),
                "mask_bbox": alignment.get("mask_bbox"),
                "mask_area_inside_prompt_ratio": alignment.get(
                    "mask_area_inside_prompt_ratio"
                ),
                "mask_bbox_iou": alignment.get("mask_bbox_iou"),
                "message": (
                    "MedSAM2 mask does not sufficiently align with the VLM prompt box; "
                    "do not use this finding as diagnostic evidence."
                    if status == "low_alignment"
                    else "MedSAM2 mask only partially aligns with the VLM prompt box; "
                    "review this visual evidence before relying on it."
                ),
            }
        )
    return quality_warnings


def _finding_mask_path(finding: dict[str, Any]) -> str | None:
    for region in finding.get("regions") or []:
        if isinstance(region, dict) and region.get("mask_path"):
            return str(region["mask_path"])
    return None


def _mask_iou(mask_path_a: str | None, mask_path_b: str | None) -> float | None:
    if not mask_path_a or not mask_path_b:
        return None
    path_a = Path(mask_path_a)
    path_b = Path(mask_path_b)
    if not path_a.exists() or not path_b.exists():
        return None
    mask_a = _binary_mask_image(path_a)
    mask_b = _binary_mask_image(path_b)
    if mask_a.size != mask_b.size:
        return None
    intersection = ImageChops.multiply(mask_a, mask_b)
    union = ImageChops.lighter(mask_a, mask_b)
    union_count = _nonzero_pixel_count(union)
    if union_count <= 0:
        return None
    return _nonzero_pixel_count(intersection) / union_count


def _box_mask_alignment(
    *,
    mask_path: Path,
    prompt_bbox: Any,
    measurements: dict[str, Any],
) -> dict[str, Any]:
    prompt = _normalize_bbox(prompt_bbox)
    mask_bbox = _normalize_bbox(measurements.get("lesion_bbox"))
    lesion_area = int(measurements.get("lesion_area_px") or 0)
    if prompt is None:
        return {
            "status": "not_assessed",
            "reason": "No valid VLM prompt bbox is available",
            "prompt_bbox": None,
            "mask_bbox": mask_bbox,
        }
    if lesion_area <= 0 or mask_bbox is None:
        return {
            "status": "empty_mask",
            "reason": "MedSAM2 mask is empty",
            "prompt_bbox": prompt,
            "mask_bbox": mask_bbox,
            "mask_area_inside_prompt_ratio": 0.0,
            "mask_bbox_iou": 0.0,
        }

    inside_count = _mask_area_inside_bbox(mask_path=mask_path, bbox=prompt)
    inside_ratio = round(inside_count / max(lesion_area, 1), 6)
    bbox_iou = round(_bbox_iou(prompt, mask_bbox), 6)
    if inside_ratio < 0.5:
        status = "low_alignment"
        reason = "Less than half of mask pixels fall inside the VLM prompt bbox"
    elif inside_ratio < 0.8:
        status = "partial_alignment"
        reason = "Mask partially overlaps the VLM prompt bbox"
    else:
        status = "aligned"
        reason = "Most mask pixels fall inside the VLM prompt bbox"
    return {
        "status": status,
        "reason": reason,
        "prompt_bbox": prompt,
        "mask_bbox": mask_bbox,
        "mask_area_inside_prompt_px": inside_count,
        "mask_area_px": lesion_area,
        "mask_area_inside_prompt_ratio": inside_ratio,
        "mask_bbox_iou": bbox_iou,
    }


def _normalize_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        x1, y1, x2, y2 = [int(round(float(item))) for item in value[:4]]
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _mask_area_inside_bbox(*, mask_path: Path, bbox: list[int]) -> int:
    path = Path(mask_path)
    if not path.exists():
        return 0
    mask = _binary_mask_image(path)
    width, height = mask.size
    x1 = max(min(int(bbox[0]), width), 0)
    y1 = max(min(int(bbox[1]), height), 0)
    x2 = max(min(int(bbox[2]), width), 0)
    y2 = max(min(int(bbox[3]), height), 0)
    if x2 <= x1 or y2 <= y1:
        return 0
    return _nonzero_pixel_count(mask.crop((x1, y1, x2, y2)))


def _bbox_iou(bbox_a: list[int], bbox_b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = bbox_a
    bx1, by1, bx2, by2 = bbox_b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    intersection = max(ix2 - ix1, 0) * max(iy2 - iy1, 0)
    area_a = max(ax2 - ax1, 0) * max(ay2 - ay1, 0)
    area_b = max(bx2 - bx1, 0) * max(by2 - by1, 0)
    union = area_a + area_b - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _binary_mask_image(path: Path) -> Image.Image:
    return Image.open(path).convert("L").point(lambda value: 255 if value > 0 else 0)


def _nonzero_pixel_count(image: Image.Image) -> int:
    histogram = image.histogram()
    return sum(histogram[1:])


def _append_quality_warning(payload: dict[str, Any], warning: str) -> None:
    if "segmentation_ref" in payload:
        segmentation_ref = dict(payload.get("segmentation_ref") or {})
        quality = dict(segmentation_ref.get("quality") or {})
    else:
        segmentation_ref = {}
        quality = dict(payload.get("quality") or {})
    warnings = list(quality.get("warnings") or [])
    if warning not in warnings:
        warnings.append(warning)
    quality["warnings"] = warnings
    if "segmentation_ref" in payload:
        segmentation_ref["quality"] = quality
        payload["segmentation_ref"] = segmentation_ref
    else:
        payload["quality"] = quality


def _set_quality_level(payload: dict[str, Any], *, score: float, level: str) -> None:
    if "segmentation_ref" in payload:
        segmentation_ref = dict(payload.get("segmentation_ref") or {})
        quality = dict(segmentation_ref.get("quality") or {})
    else:
        segmentation_ref = {}
        quality = dict(payload.get("quality") or {})
    quality["score"] = score
    quality["level"] = level
    if "segmentation_ref" in payload:
        segmentation_ref["quality"] = quality
        payload["segmentation_ref"] = segmentation_ref
    else:
        payload["quality"] = quality


def _safe_filename(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned.strip("_") or "candidate"


def _display_name_for_target(value: str) -> str:
    display_names = {
        "sclerotic_band": "硬化带",
        "cystic_change": "囊性变",
        "trabecular_blurring": "骨小梁模糊或局灶性骨质疏松",
        "collapse": "股骨头塌陷",
        "lung_opacity": "肺部浸润影/实变影候选区域",
    }
    return display_names.get(value, value)


def _write_summary(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _load_dotenv_local(path: Path = Path(".env.local")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run MedSAM2 from a no-mask vision-model bbox prompt."
    )
    parser.add_argument("--prompt-result", default=str(DEFAULT_PROMPT_RESULT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--anatomy-mask", default="")
    parser.add_argument("--anatomy-name", default="anatomy")
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_dotenv_local()
    args = build_parser().parse_args(argv)
    result = run_no_mask_medsam2_segmentation_demo(
        prompt_result_path=Path(args.prompt_result),
        output_dir=Path(args.output_dir),
        anatomy_mask_path=Path(args.anatomy_mask) if args.anatomy_mask else None,
        anatomy_name=args.anatomy_name,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
