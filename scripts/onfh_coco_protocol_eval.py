from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_PACKAGE_DIR = Path("data/ONFH_MRI_Xray_COCO_clean_20260605_package")
DEFAULT_OUTPUT_DIR = Path("output/real/onfh_coco_protocol_evaluation")
DEFAULT_BASELINE_SKILL = Path(
    "skills/baselines/femoral_head_necrosis_finding_list_baseline_20260604.yaml"
)
DEFAULT_CURRENT_SKILL = Path("skills/femoral_head_necrosis.yaml")


ONFH_LABEL_TO_TARGET = {
    "MRI-T2双线征": {
        "target": "early_osteonecrosis",
        "evidence_family": "mri_specific_finding",
        "protocol_gap_note": "Current protocol treats early osteonecrosis as MRI-required input but does not yet split double-line sign into a dedicated MRI finding target.",
    },
    "MRI-T1低信号带": {
        "target": "early_osteonecrosis",
        "evidence_family": "mri_specific_finding",
        "protocol_gap_note": "Current protocol does not yet split T1 low-signal band into a dedicated MRI finding target.",
    },
    "MRI-T1坏死区": {
        "target": "early_osteonecrosis",
        "evidence_family": "mri_specific_finding",
        "protocol_gap_note": "Current protocol does not yet split MRI necrotic area into a dedicated MRI finding target or measurement protocol.",
    },
    "MRI-T2骨髓水肿": {
        "target": "early_osteonecrosis",
        "evidence_family": "mri_specific_finding",
        "protocol_gap_note": "Current protocol mentions MRI requirement but does not yet model bone marrow edema as its own target.",
    },
    "MRI-T2囊性变": {
        "target": "cystic_change",
        "evidence_family": "mri_specific_finding",
        "protocol_gap_note": "Cystic change is covered for X-ray candidate evidence; MRI-specific cystic-change handling is not yet explicit.",
    },
    "硬化带": {
        "target": "sclerotic_band",
        "evidence_family": "xray_finding",
        "protocol_gap_note": None,
    },
    "嚢性变": {
        "target": "cystic_change",
        "evidence_family": "xray_finding",
        "protocol_gap_note": None,
    },
    "囊性变": {
        "target": "cystic_change",
        "evidence_family": "xray_finding",
        "protocol_gap_note": None,
    },
    "软骨下骨骨折": {
        "target": "collapse",
        "evidence_family": "xray_or_mri_collapse_boundary",
        "protocol_gap_note": "Current protocol models collapse measurement but not subchondral fracture as a separate target.",
    },
    "混杂密度区": {
        "target": "trabecular_blurring",
        "evidence_family": "xray_observation",
        "protocol_gap_note": "Mapped as nonspecific texture/density disturbance; protocol should keep this lower confidence.",
    },
}


def run_onfh_coco_protocol_evaluation(
    *,
    package_dir: Path | str = DEFAULT_PACKAGE_DIR,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    baseline_skill_path: Path | str = DEFAULT_BASELINE_SKILL,
    current_skill_path: Path | str = DEFAULT_CURRENT_SKILL,
    primary_modality: str = "Xray",
    include_auxiliary_modalities: bool = False,
) -> dict[str, Any]:
    package = Path(package_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    coco_path = package / "annotations" / "instances_coco.json"
    coco = _read_json(coco_path)
    baseline_skill = _read_json(Path(baseline_skill_path))
    current_skill = _read_json(Path(current_skill_path))
    manifest_by_image_id = _read_manifest(package / "annotations" / "manifest.csv")

    images_by_id = {
        int(image["id"]): dict(image)
        for image in coco.get("images") or []
        if isinstance(image, dict) and image.get("id") is not None
    }
    categories_by_id = {
        int(category["id"]): str(category.get("name") or "")
        for category in coco.get("categories") or []
        if isinstance(category, dict) and category.get("id") is not None
    }
    baseline_targets = _baseline_targets(baseline_skill)
    current_targets = _current_protocol_targets(current_skill)
    current_quantitative_targets = _current_quantitative_targets(current_skill)

    label_stats: dict[str, dict[str, Any]] = {}
    sample_items: list[dict[str, Any]] = []
    mapped_annotation_count = 0
    unmapped_annotation_count = 0
    current_covered_count = 0
    baseline_covered_count = 0
    total_mask_area_px = 0.0
    evaluated_annotation_count = 0
    auxiliary_excluded_annotation_count = 0
    annotations_by_label: Counter[str] = Counter()
    images_by_label: dict[str, set[int]] = defaultdict(set)
    modalities_by_label: dict[str, Counter[str]] = defaultdict(Counter)
    auxiliary_excluded_by_label: Counter[str] = Counter()
    evaluated_image_ids: set[int] = set()

    for annotation in coco.get("annotations") or []:
        if not isinstance(annotation, dict):
            continue
        category = categories_by_id.get(int(annotation.get("category_id") or 0), "")
        image_id = int(annotation.get("image_id") or 0)
        image = images_by_id.get(image_id, {})
        manifest = manifest_by_image_id.get(image_id, {})
        modality = str(manifest.get("modality") or _infer_modality(category, image.get("file_name")))
        if not include_auxiliary_modalities and _normalize_modality(modality) != _normalize_modality(
            primary_modality
        ):
            auxiliary_excluded_annotation_count += 1
            auxiliary_excluded_by_label[category] += 1
            continue

        area = float(annotation.get("area") or 0)
        total_mask_area_px += area
        evaluated_annotation_count += 1
        evaluated_image_ids.add(image_id)
        annotations_by_label[category] += 1
        images_by_label[category].add(image_id)
        modalities_by_label[category][modality] += 1

        mapping = _label_mapping(
            label=category,
            baseline_targets=baseline_targets,
            current_targets=current_targets,
            current_quantitative_targets=current_quantitative_targets,
        )
        if mapping["target"]:
            mapped_annotation_count += 1
        else:
            unmapped_annotation_count += 1
        if mapping["current_protocol_status"] in {
            "covered",
            "covered_but_insufficient_input_rule",
            "covered_with_protocol_gap",
        }:
            current_covered_count += 1
        if mapping["baseline_status"] == "covered":
            baseline_covered_count += 1

        item = _sample_evidence_item(
            annotation=annotation,
            label=category,
            image=image,
            manifest=manifest,
            mapping=mapping,
        )
        if len(sample_items) < 20:
            sample_items.append(item)

    for label in sorted(categories_by_id.values()):
        mapping = _label_mapping(
            label=label,
            baseline_targets=baseline_targets,
            current_targets=current_targets,
            current_quantitative_targets=current_quantitative_targets,
        )
        if not include_auxiliary_modalities and auxiliary_excluded_by_label[label]:
            mapping = {
                **mapping,
                "current_protocol_status": "auxiliary_excluded",
                "baseline_status": "auxiliary_excluded",
                "quantitative_protocol_status": "auxiliary_excluded",
            }
        label_stats[label] = {
            **mapping,
            "annotation_count": annotations_by_label[label],
            "image_count": len(images_by_label[label]),
            "modalities": dict(sorted(modalities_by_label[label].items())),
            "auxiliary_excluded_annotation_count": auxiliary_excluded_by_label[label],
        }

    payload = {
        "schema_version": "onfh_coco_protocol_evaluation.v1",
        "evaluation_scope": {
            "primary_modality": primary_modality,
            "include_auxiliary_modalities": include_auxiliary_modalities,
            "auxiliary_modalities_role": (
                "excluded_from_primary_protocol_evaluation; retained only for future feature discovery"
                if not include_auxiliary_modalities
                else "included_for_auxiliary_discovery_analysis"
            ),
        },
        "dataset": {
            "package_dir": str(package),
            "coco_annotation_path": str(coco_path),
            "image_root": str(package / "images"),
            "source_image_count": len(coco.get("images") or []),
            "source_annotation_count": len(coco.get("annotations") or []),
            "evaluated_image_count": len(evaluated_image_ids),
            "evaluated_annotation_count": evaluated_annotation_count,
            "auxiliary_excluded_annotation_count": auxiliary_excluded_annotation_count,
            "category_count": len(coco.get("categories") or []),
        },
        "auxiliary_modalities": {
            "excluded_annotation_count": auxiliary_excluded_annotation_count,
            "excluded_labels": sorted(
                label for label, count in auxiliary_excluded_by_label.items() if count
            ),
            "excluded_label_counts": dict(sorted(auxiliary_excluded_by_label.items())),
        },
        "skill_comparison": {
            "baseline_skill_path": str(baseline_skill_path),
            "current_skill_path": str(current_skill_path),
            "baseline_finding_targets": sorted(baseline_targets),
            "current_imaging_targets": sorted(current_targets),
            "current_quantitative_targets": sorted(current_quantitative_targets),
        },
        "safety": {
            "real_data_evaluation_only": True,
            "patient_paths_redacted": True,
            "diagnosis_allowed": False,
            "formal_skill_update_allowed": False,
            "does_not_train_model": True,
            "does_not_update_formal_skill": True,
        },
        "aggregate": {
            "mapped_annotation_count": mapped_annotation_count,
            "unmapped_annotation_count": unmapped_annotation_count,
            "current_protocol_covered_annotation_count": current_covered_count,
            "baseline_covered_annotation_count": baseline_covered_count,
            "total_mask_area_px": int(total_mask_area_px)
            if total_mask_area_px.is_integer()
            else total_mask_area_px,
        },
        "label_mapping": label_stats,
        "coverage_gaps": _coverage_gaps(label_stats),
        "sample_evidence_items": sample_items,
    }
    json_path = output / "onfh_coco_protocol_evaluation.json"
    markdown_path = output / "onfh_coco_protocol_evaluation.md"
    payload["output_paths"] = {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    _write_json(json_path, payload)
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _label_mapping(
    *,
    label: str,
    baseline_targets: set[str],
    current_targets: set[str],
    current_quantitative_targets: set[str],
) -> dict[str, Any]:
    declared = ONFH_LABEL_TO_TARGET.get(label)
    if not declared:
        return {
            "target": None,
            "evidence_family": "unmapped",
            "current_protocol_status": "unmapped_label",
            "baseline_status": "unmapped_label",
            "quantitative_protocol_status": "unmapped_label",
            "protocol_gap_note": "No label-to-skill target mapping is defined.",
        }
    target = str(declared["target"])
    if target in current_targets:
        current_status = (
            "covered_but_insufficient_input_rule"
            if target == "early_osteonecrosis"
            else "covered"
        )
    else:
        current_status = "gap"
    if declared.get("protocol_gap_note") and current_status == "covered":
        current_status = "covered_with_protocol_gap"
    quantitative_status = "covered" if target in current_quantitative_targets else "gap"
    return {
        "target": target,
        "evidence_family": declared.get("evidence_family"),
        "current_protocol_status": current_status,
        "baseline_status": "covered" if target in baseline_targets else "gap",
        "quantitative_protocol_status": quantitative_status,
        "protocol_gap_note": declared.get("protocol_gap_note"),
    }


def _sample_evidence_item(
    *,
    annotation: dict[str, Any],
    label: str,
    image: dict[str, Any],
    manifest: dict[str, Any],
    mapping: dict[str, Any],
) -> dict[str, Any]:
    image_id = int(annotation.get("image_id") or 0)
    image_width = float(image.get("width") or 0)
    image_height = float(image.get("height") or 0)
    image_area = image_width * image_height
    annotation_area = float(annotation.get("area") or 0)
    return {
        "annotation_id": annotation.get("id"),
        "redacted_image_ref": f"image_{image_id}",
        "modality": manifest.get("modality") or _infer_modality(label, image.get("file_name")),
        "label": label,
        "target": mapping.get("target"),
        "bbox": list(annotation.get("bbox") or []),
        "mask_area_px": int(annotation_area) if annotation_area.is_integer() else annotation_area,
        "image_area_ratio": (
            round(annotation_area / image_area, 6) if image_area > 0 else None
        ),
        "current_protocol_status": mapping.get("current_protocol_status"),
        "baseline_status": mapping.get("baseline_status"),
        "diagnosis_allowed": False,
    }


def _baseline_targets(skill: dict[str, Any]) -> set[str]:
    visual_protocol = skill.get("visual_protocol") or {}
    return {
        str(item.get("target"))
        for item in visual_protocol.get("finding_targets") or []
        if isinstance(item, dict) and item.get("target")
    }


def _current_protocol_targets(skill: dict[str, Any]) -> set[str]:
    imaging = skill.get("imaging_evidence_protocol") or {}
    return {
        str(item.get("target"))
        for item in imaging.get("finding_targets") or []
        if isinstance(item, dict) and item.get("target")
    }


def _current_quantitative_targets(skill: dict[str, Any]) -> set[str]:
    quantitative = skill.get("quantitative_evidence_protocol") or {}
    targets = set()
    for item in quantitative.get("image_feature_quantification") or []:
        if isinstance(item, dict) and item.get("target"):
            targets.update(_expand_target(str(item.get("target"))))
    for item in quantitative.get("measurement_evidence") or []:
        if isinstance(item, dict) and item.get("target"):
            targets.update(_expand_target(str(item.get("target"))))
    return targets


def _expand_target(target: str) -> set[str]:
    targets = {target}
    if "_or_" in target:
        targets.update(part for part in target.split("_or_") if part)
    return targets


def _coverage_gaps(label_stats: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "unmapped_labels": sorted(
            label
            for label, stats in label_stats.items()
            if stats.get("current_protocol_status") == "unmapped_label"
        ),
        "baseline_missing_labels": sorted(
            label
            for label, stats in label_stats.items()
            if stats.get("baseline_status") == "gap" and stats.get("annotation_count", 0)
        ),
        "current_protocol_missing_labels": sorted(
            label
            for label, stats in label_stats.items()
            if stats.get("current_protocol_status") == "gap" and stats.get("annotation_count", 0)
        ),
        "current_protocol_mri_specific_detail_needed": sorted(
            label
            for label, stats in label_stats.items()
            if stats.get("evidence_family") == "mri_specific_finding"
            and stats.get("protocol_gap_note")
            and stats.get("annotation_count", 0)
        ),
        "quantitative_protocol_missing_targets": sorted(
            label
            for label, stats in label_stats.items()
            if stats.get("target") and stats.get("quantitative_protocol_status") == "gap"
            and stats.get("annotation_count", 0)
        ),
    }


def _read_manifest(path: Path) -> dict[int, dict[str, str]]:
    if not path.exists():
        return {}
    result: dict[int, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            image_id = row.get("image_id")
            if image_id is None:
                continue
            try:
                result[int(image_id)] = dict(row)
            except ValueError:
                continue
    return result


def _infer_modality(label: str, file_name: Any) -> str:
    text = f"{label} {file_name or ''}".lower()
    if "mri" in text:
        return "MRI"
    if "xray" in text or "x-ray" in text or "髋" in text:
        return "Xray"
    return "unknown"


def _normalize_modality(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"xray", "x-ray", "x ray", "xr"}:
        return "xray"
    if normalized == "mri":
        return "mri"
    return normalized


def _render_markdown(payload: dict[str, Any]) -> str:
    aggregate = payload.get("aggregate") or {}
    gaps = payload.get("coverage_gaps") or {}
    lines = [
        "# ONFH COCO Protocol Evaluation",
        "",
        f"- `schema_version`: `{payload.get('schema_version')}`",
        f"- `primary_modality`: `{payload.get('evaluation_scope', {}).get('primary_modality')}`",
        f"- `include_auxiliary_modalities`: `{payload.get('evaluation_scope', {}).get('include_auxiliary_modalities')}`",
        f"- `source_image_count`: `{payload.get('dataset', {}).get('source_image_count')}`",
        f"- `source_annotation_count`: `{payload.get('dataset', {}).get('source_annotation_count')}`",
        f"- `evaluated_annotation_count`: `{payload.get('dataset', {}).get('evaluated_annotation_count')}`",
        f"- `auxiliary_excluded_annotation_count`: `{payload.get('dataset', {}).get('auxiliary_excluded_annotation_count')}`",
        f"- `mapped_annotation_count`: `{aggregate.get('mapped_annotation_count')}`",
        f"- `unmapped_annotation_count`: `{aggregate.get('unmapped_annotation_count')}`",
        f"- `current_protocol_covered_annotation_count`: `{aggregate.get('current_protocol_covered_annotation_count')}`",
        f"- `baseline_covered_annotation_count`: `{aggregate.get('baseline_covered_annotation_count')}`",
        "",
        "## Coverage Gaps",
        "",
        f"- `unmapped_labels`: `{', '.join(gaps.get('unmapped_labels') or [])}`",
        f"- `baseline_missing_labels`: `{', '.join(gaps.get('baseline_missing_labels') or [])}`",
        f"- `current_protocol_mri_specific_detail_needed`: `{', '.join(gaps.get('current_protocol_mri_specific_detail_needed') or [])}`",
        "",
        "| label | target | annotations | current_protocol_status | baseline_status | quantitative_status |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for label, stats in sorted((payload.get("label_mapping") or {}).items()):
        lines.append(
            "| {label} | {target} | {count} | {current} | {baseline} | {quant} |".format(
                label=label,
                target=stats.get("target"),
                count=stats.get("annotation_count"),
                current=stats.get("current_protocol_status"),
                baseline=stats.get("baseline_status"),
                quant=stats.get("quantitative_protocol_status"),
            )
        )
    lines.extend(
        [
            "",
            "Safety boundary: this artifact evaluates protocol coverage on real annotation data.",
            "It does not train a model, update a formal skill, or authorize clinical diagnosis.",
        ]
    )
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate ONFH COCO labels against FHN skill protocols.")
    parser.add_argument("--package-dir", default=str(DEFAULT_PACKAGE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--baseline-skill", default=str(DEFAULT_BASELINE_SKILL))
    parser.add_argument("--current-skill", default=str(DEFAULT_CURRENT_SKILL))
    parser.add_argument("--primary-modality", default="Xray")
    parser.add_argument("--include-auxiliary-modalities", action="store_true")
    args = parser.parse_args(argv)
    payload = run_onfh_coco_protocol_evaluation(
        package_dir=Path(args.package_dir),
        output_dir=Path(args.output_dir),
        baseline_skill_path=Path(args.baseline_skill),
        current_skill_path=Path(args.current_skill),
        primary_modality=args.primary_modality,
        include_auxiliary_modalities=args.include_auxiliary_modalities,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
