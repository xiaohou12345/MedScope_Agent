from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from tools.brats_evaluation_tool import BratsEvaluationTool


DEFAULT_BRATS_SUMMARY = Path("output/fake/brats_vision_medsam2_two_cases/summary.json")
DEFAULT_FHN_RESPONSE = Path(
    "output/fake/standard_demo_with_fhn_no_mask_qc/cases/"
    "fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_response.json"
)
DEFAULT_FHN_PIPELINE_SUMMARY = Path(
    "output/fake/gaodoctor_fhn_no_mask/case_20260526_180715_929568/summary.json"
)
DEFAULT_NON_REFERENCE_PROMPT_SUMMARY = Path("output/fake/brats_phase_b_vlm_prompt/summary.json")
DEFAULT_NON_REFERENCE_AUTO_EVAL_SUMMARY = Path(
    "output/fake/brats_phase_b_non_reference_auto_eval/summary.json"
)
DEFAULT_OUTPUT_DIR = Path("output/fake")


def build_vision_evidence_eval_summary(
    *,
    brats_summary_path: Path | str = DEFAULT_BRATS_SUMMARY,
    fhn_response_path: Path | str = DEFAULT_FHN_RESPONSE,
    fhn_pipeline_summary_path: Path | str | None = DEFAULT_FHN_PIPELINE_SUMMARY,
    non_reference_prompt_summary_path: Path | str | None = DEFAULT_NON_REFERENCE_PROMPT_SUMMARY,
    non_reference_auto_eval_summary_path: Path | str | None = DEFAULT_NON_REFERENCE_AUTO_EVAL_SUMMARY,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    brats_evaluator: Any | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    brats_summary = _read_json(Path(brats_summary_path))
    cases.extend(_build_brats_cases(brats_summary, brats_evaluator=brats_evaluator))

    fhn_response = _read_json(Path(fhn_response_path))
    fhn_pipeline = (
        _read_json(Path(fhn_pipeline_summary_path))
        if fhn_pipeline_summary_path and Path(fhn_pipeline_summary_path).exists()
        else {}
    )
    cases.append(_build_fhn_case(fhn_response, fhn_pipeline))
    non_reference_attempts = _build_non_reference_attempts(
        prompt_summary_path=non_reference_prompt_summary_path,
        auto_eval_summary_path=non_reference_auto_eval_summary_path,
    )

    payload = {
        "schema_version": "vision_evidence_eval_summary.v1",
        "source_paths": {
            "brats_summary_path": str(brats_summary_path),
            "fhn_response_path": str(fhn_response_path),
            "fhn_pipeline_summary_path": (
                str(fhn_pipeline_summary_path) if fhn_pipeline_summary_path else None
            ),
            "non_reference_prompt_summary_path": (
                str(non_reference_prompt_summary_path)
                if non_reference_prompt_summary_path
                else None
            ),
            "non_reference_auto_eval_summary_path": (
                str(non_reference_auto_eval_summary_path)
                if non_reference_auto_eval_summary_path
                else None
            ),
        },
        "aggregate": _build_aggregate(cases, non_reference_attempts),
        "cases": cases,
        "non_reference_attempts": non_reference_attempts,
        "next_actions": _build_next_actions(cases, non_reference_attempts),
    }

    json_path = output / "vision_evidence_eval_summary.json"
    markdown_path = output / "vision_evidence_eval_summary.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    payload["output_paths"] = {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def build_vision_evidence_candidate_queue(
    *,
    eval_summary: dict[str, Any] | None = None,
    eval_summary_path: Path | str | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source_path = Path(eval_summary_path) if eval_summary_path else output / "vision_evidence_eval_summary.json"
    summary = eval_summary if eval_summary is not None else _read_json(source_path)
    queue_items = _build_vision_evidence_candidate_items(summary)
    payload = {
        "schema_version": "vision_evidence_candidate_queue.v1",
        "source_summary_schema_version": summary.get("schema_version"),
        "source_summary_path": None if eval_summary is not None else str(source_path),
        "status": "candidate_only",
        "candidate_count": len(queue_items),
        "queue_items": queue_items,
        "review_policy": {
            "required_review": "human_or_validated_dataset",
            "promotion_rule": (
                "Vision evidence failures can only become formal knowledge changes after "
                "manual review or dataset validation."
            ),
            "allowed_outputs": [
                "candidate_visual_protocol_review",
                "candidate_manual_review_label",
                "candidate_quality_gate_rule",
            ],
        },
        "runtime_gateway_mapping": {
            "layer": "Agentic Runtime / Evidence Gateway",
            "stages": [
                "stop_hooks_reflection",
                "self_evolving_queue",
                "candidate_validation_gate",
            ],
            "presentation_note": (
                "The gateway distributes knowledge and shared artifacts, applies policy "
                "guards, records hook outputs, and keeps self-evolving items as "
                "review-only candidates."
            ),
        },
        "runtime_safety": {
            "queue_written": True,
            "candidate_only": True,
            "candidate_artifacts_only": True,
            "formal_knowledge_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "formal_update_allowed": False,
        },
    }
    json_path = output / "vision_evidence_candidate_queue.json"
    markdown_path = output / "vision_evidence_candidate_queue.md"
    payload["output_paths"] = {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_candidate_queue_markdown(payload), encoding="utf-8")
    return payload


def build_vision_evidence_candidate_validation_gate(
    *,
    candidate_queue: dict[str, Any] | None = None,
    candidate_queue_path: Path | str | None = None,
    reviewer_notes: dict[str, Any] | None = None,
    reviewer_notes_path: Path | str | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    queue_path = (
        Path(candidate_queue_path)
        if candidate_queue_path
        else output / "vision_evidence_candidate_queue.json"
    )
    notes_path = Path(reviewer_notes_path) if reviewer_notes_path else None
    queue = candidate_queue if candidate_queue is not None else _read_json(queue_path)
    notes = (
        reviewer_notes
        if reviewer_notes is not None
        else (_read_json(notes_path) if notes_path and notes_path.exists() else {})
    )
    note_by_item_id = _reviewer_notes_by_item_id(notes)
    item_validations = [
        _validate_vision_candidate_item(item, note_by_item_id.get(str(item.get("item_id") or "")))
        for item in queue.get("queue_items") or []
        if isinstance(item, dict)
    ]
    unmatched_note_ids = sorted(
        item_id
        for item_id in note_by_item_id
        if item_id not in {str(item.get("item_id") or "") for item in queue.get("queue_items") or []}
    )
    review_summary = _candidate_review_summary(item_validations)
    payload = {
        "schema_version": "vision_evidence_candidate_validation_gate.v1",
        "source_queue_schema_version": queue.get("schema_version"),
        "source_queue_path": None if candidate_queue is not None else str(queue_path),
        "source_reviewer_notes_schema_version": notes.get("schema_version"),
        "source_reviewer_notes_path": str(notes_path) if notes_path else None,
        "review_summary": review_summary,
        "item_validations": item_validations,
        "unmatched_reviewer_note_item_ids": unmatched_note_ids,
        "promotion_decision": {
            "status": "blocked",
            "reason": (
                "candidate_items_reviewed_but_formal_promotion_requires_separate_approval"
                if review_summary["reviewed_count"]
                else "candidate_items_require_human_or_dataset_review"
            ),
            "formal_update_allowed": False,
            "promotable_item_ids": [],
        },
        "review_requirements": [
            "Reviewer notes can update candidate validation state only.",
            "Formal knowledge or guideline promotion requires a separate explicit approval step.",
            "No diagnosis report may be rewritten from candidate queue review alone.",
        ],
        "runtime_safety": {
            "validation_gate_executed": True,
            "read_only": True,
            "candidate_artifacts_only": True,
            "formal_knowledge_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "formal_update_allowed": False,
        },
    }
    json_path = output / "vision_evidence_candidate_validation_gate.json"
    markdown_path = output / "vision_evidence_candidate_validation_gate.md"
    payload["output_paths"] = {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(
        _render_candidate_validation_gate_markdown(payload),
        encoding="utf-8",
    )
    return payload


def build_vision_evidence_reviewer_notes_template(
    *,
    candidate_queue: dict[str, Any] | None = None,
    candidate_queue_path: Path | str | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    queue_path = (
        Path(candidate_queue_path)
        if candidate_queue_path
        else output / "vision_evidence_candidate_queue.json"
    )
    queue = candidate_queue if candidate_queue is not None else _read_json(queue_path)
    notes = [
        {
            "item_id": item.get("item_id"),
            "source_case_id": item.get("source_case_id"),
            "candidate_type": item.get("candidate_type"),
            "source_warning_code": item.get("source_warning_code"),
            "review_status": "pending_review",
            "reviewer_note": "",
        }
        for item in queue.get("queue_items") or []
        if isinstance(item, dict)
    ]
    payload = {
        "schema_version": "vision_evidence_reviewer_notes.v1",
        "source_queue_schema_version": queue.get("schema_version"),
        "source_queue_path": None if candidate_queue is not None else str(queue_path),
        "review_status": "pending_human_review",
        "allowed_review_statuses": [
            "accepted",
            "rejected",
            "needs_revision",
            "pending_review",
        ],
        "reviewer": "",
        "notes": notes,
        "safety_note": (
            "Reviewer notes update candidate validation state only; they do not "
            "modify formal knowledge, guidelines, or diagnosis reports."
        ),
    }
    json_path = output / "vision_evidence_reviewer_notes_template.json"
    payload["output_paths"] = {"json_path": str(json_path)}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _build_brats_cases(
    summary: dict[str, Any],
    *,
    brats_evaluator: Any | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    evaluator = brats_evaluator or BratsEvaluationTool()
    for case in summary.get("cases") or []:
        if not isinstance(case, dict):
            continue
        result_payload = _read_optional_json(case.get("result_json_path"))
        result = dict(result_payload.get("result") or {})
        visual_evidence = dict(result.get("visual_evidence") or {})
        image_outputs = dict(result.get("image_outputs") or {})
        suspected_findings = [
            finding
            for finding in visual_evidence.get("suspected_visual_findings") or []
            if str(finding).strip()
        ]
        evaluation = _reference_evaluation_for_case(
            case=case,
            result_payload=result_payload,
            evaluator=evaluator,
        )
        dice_values = [
            float(value)
            for key, value in evaluation.items()
            if key.endswith("_dice") and isinstance(value, (int, float))
        ]
        iou_values = [
            float(value)
            for key, value in evaluation.items()
            if key.endswith("_iou") and isinstance(value, (int, float))
        ]
        absolute_volume_errors = [
            float(value)
            for key, value in evaluation.items()
            if key.endswith("_absolute_volume_error_ml") and isinstance(value, (int, float))
        ]
        failure_types = _failure_types_from_reference_case(case, evaluation)
        rows.append(
            {
                "case_id": str(case.get("case_id") or "unknown_brats_case"),
                "disease_knowledge": "diffuse_glioma_brats",
                "modality": str(result.get("modality") or "mri"),
                "reference_available": True,
                "visual_fact_count": len(suspected_findings),
                "adopted_fact_count": 0,
                "excluded_fact_count": 0,
                "mask_artifact_count": _count_paths(image_outputs, ["mask_path"]),
                "overlay_artifact_count": _count_paths(
                    image_outputs,
                    ["overlay_path", "comparison_path", "bbox_overlay_path"],
                ),
                "mean_dice": round(sum(dice_values) / len(dice_values), 6)
                if dice_values
                else None,
                "mean_iou": round(sum(iou_values) / len(iou_values), 6)
                if iou_values
                else None,
                "mean_absolute_volume_error_ml": round(
                    sum(absolute_volume_errors) / len(absolute_volume_errors),
                    6,
                )
                if absolute_volume_errors
                else None,
                "false_positive_component_count": _sum_metric_suffix(
                    evaluation,
                    "_false_positive_component_count",
                ),
                "false_negative_component_count": _sum_metric_suffix(
                    evaluation,
                    "_false_negative_component_count",
                ),
                "metrics": evaluation,
                "quality_warning_count": 0,
                "failure_types": failure_types,
                "diagnosis_allowed": False,
                "candidate_queue_action": "add_visual_protocol_review"
                if failure_types
                else "no_action",
                "review_status": "pending_review",
                "source_result_path": case.get("result_json_path"),
                "blocked_reason": (
                    "reference-mask metric review only; not a diagnosis workflow"
                ),
            }
        )
    return rows


def _build_vision_evidence_candidate_items(summary: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for case in summary.get("cases") or []:
        if not isinstance(case, dict):
            continue
        for failure_type in case.get("failure_types") or []:
            items.append(_failure_candidate_item(case, str(failure_type)))
        for manual_item in case.get("manual_review_items") or []:
            if isinstance(manual_item, dict):
                items.append(_manual_review_candidate_item(case, manual_item))
    for attempt in summary.get("non_reference_attempts") or []:
        if not isinstance(attempt, dict):
            continue
        if attempt.get("auto_eval_status") != "ok":
            items.append(_non_reference_attempt_candidate_item(attempt))
            continue
        for failure_type in attempt.get("failure_types") or []:
            items.append(_non_reference_metric_candidate_item(attempt, str(failure_type)))
    return items


def _reviewer_notes_by_item_id(reviewer_notes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    notes = reviewer_notes.get("notes") or []
    if not isinstance(notes, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for note in notes:
        if not isinstance(note, dict):
            continue
        item_id = str(note.get("item_id") or "")
        if item_id:
            result[item_id] = note
    return result


def _validate_vision_candidate_item(
    item: dict[str, Any],
    reviewer_note: dict[str, Any] | None,
) -> dict[str, Any]:
    status = str((reviewer_note or {}).get("review_status") or "pending_review")
    allowed_statuses = {"accepted", "rejected", "needs_revision", "pending_review"}
    if status not in allowed_statuses:
        status = "needs_revision"
    failed_checks: list[str] = []
    passed_checks: list[str] = []
    if item.get("item_id"):
        passed_checks.append("item_id_present")
    else:
        failed_checks.append("item_id_missing")
    if reviewer_note:
        passed_checks.append("reviewer_note_present")
    else:
        failed_checks.append("reviewer_note_missing")
    if status in {"accepted", "rejected", "needs_revision"}:
        passed_checks.append("human_review_recorded")
    else:
        failed_checks.append("human_review_pending")
    if item.get("formal_update_allowed") is False:
        passed_checks.append("formal_update_blocked")
    else:
        failed_checks.append("formal_update_not_blocked")
    return {
        "item_id": item.get("item_id"),
        "source_case_id": item.get("source_case_id"),
        "candidate_type": item.get("candidate_type"),
        "source_warning_code": item.get("source_warning_code"),
        "reviewer_note": reviewer_note or {},
        "review_status": status,
        "validation_status": "reviewed" if status != "pending_review" else "pending_review",
        "formal_update_allowed": False,
        "allowed_action": "candidate_review_only",
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "decision": (
            "kept_as_candidate_after_review"
            if status != "pending_review"
            else "blocked_pending_review"
        ),
    }


def _candidate_review_summary(item_validations: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "item_count": len(item_validations),
        "reviewed_count": sum(
            1 for item in item_validations if item.get("validation_status") == "reviewed"
        ),
        "pending_count": sum(
            1 for item in item_validations if item.get("validation_status") == "pending_review"
        ),
        "accepted_count": sum(
            1 for item in item_validations if item.get("review_status") == "accepted"
        ),
        "rejected_count": sum(
            1 for item in item_validations if item.get("review_status") == "rejected"
        ),
        "needs_revision_count": sum(
            1 for item in item_validations if item.get("review_status") == "needs_revision"
        ),
    }


def _failure_candidate_item(case: dict[str, Any], failure_type: str) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "unknown_case")
    return {
        "item_id": f"{_slug(case_id)}_{_slug(failure_type)}_visual_protocol_review",
        "source_case_id": case_id,
        "source_stage": "vision_evidence_eval",
        "source_warning_code": failure_type,
        "candidate_type": "visual_protocol_review",
        "disease_knowledge": case.get("disease_knowledge"),
        "modality": case.get("modality"),
        "proposal": _proposal_for_vision_failure(failure_type),
        "evidence": {
            "reference_available": case.get("reference_available"),
            "diagnosis_allowed": case.get("diagnosis_allowed"),
            "metrics": case.get("metrics") or {},
            "quality_warning_count": case.get("quality_warning_count"),
            "failure_type": failure_type,
        },
        "validation_status": "pending_review",
        "allowed_action": "candidate_review_only",
        "formal_update_allowed": False,
    }


def _manual_review_candidate_item(
    case: dict[str, Any],
    manual_item: dict[str, Any],
) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "unknown_case")
    finding_id = str(manual_item.get("finding_id") or "unknown_finding")
    return {
        "item_id": f"{_slug(case_id)}_{_slug(finding_id)}_manual_review_label",
        "source_case_id": case_id,
        "source_stage": "vision_evidence_eval",
        "source_warning_code": "manual_review_required",
        "candidate_type": "manual_review_label",
        "disease_knowledge": case.get("disease_knowledge"),
        "modality": case.get("modality"),
        "proposal": (
            "Review the suggested no-mask finding label before reusing it as "
            "training data or a formal visual protocol rule."
        ),
        "evidence": {
            "manual_review_item": manual_item,
            "diagnosis_allowed": case.get("diagnosis_allowed"),
            "reference_available": case.get("reference_available"),
        },
        "validation_status": "pending_review",
        "allowed_action": "candidate_review_only",
        "formal_update_allowed": False,
    }


def _non_reference_attempt_candidate_item(attempt: dict[str, Any]) -> dict[str, Any]:
    case_id = str(attempt.get("case_id") or "unknown_case")
    warning_code = "medsam2_not_ready"
    return {
        "item_id": f"{_slug(case_id)}_{warning_code}_runtime_configuration_review",
        "source_case_id": case_id,
        "source_stage": "non_reference_auto_eval",
        "source_warning_code": warning_code,
        "candidate_type": "runtime_configuration_review",
        "disease_knowledge": attempt.get("disease_knowledge"),
        "modality": attempt.get("modality"),
        "proposal": (
            "Configure and validate MedSAM2 runner before claiming non-reference "
            "automatic segmentation results."
        ),
        "evidence": {
            "prompt_status": attempt.get("prompt_status"),
            "auto_eval_status": attempt.get("auto_eval_status"),
            "prompt_source": attempt.get("prompt_source"),
            "medsam2_ready": attempt.get("medsam2_ready"),
            "missing_medsam2_configuration": list(
                attempt.get("missing_medsam2_configuration") or []
            ),
        },
        "validation_status": "pending_review",
        "allowed_action": "candidate_review_only",
        "formal_update_allowed": False,
    }


def _non_reference_metric_candidate_item(
    attempt: dict[str, Any],
    failure_type: str,
) -> dict[str, Any]:
    case_id = str(attempt.get("case_id") or "unknown_case")
    return {
        "item_id": f"{_slug(case_id)}_{_slug(failure_type)}_non_reference_metric_review",
        "source_case_id": case_id,
        "source_stage": "non_reference_auto_eval",
        "source_warning_code": failure_type,
        "candidate_type": "non_reference_metric_review",
        "disease_knowledge": attempt.get("disease_knowledge"),
        "modality": attempt.get("modality"),
        "proposal": (
            "Review the successful non-reference VLM+MedSAM2 run before using its "
            "metric pattern to revise visual protocol, prompt constraints, or quality gates."
        ),
        "evidence": {
            "prompt_status": attempt.get("prompt_status"),
            "auto_eval_status": attempt.get("auto_eval_status"),
            "prompt_source": attempt.get("prompt_source"),
            "medsam2_ready": attempt.get("medsam2_ready"),
            "reference_mask_used": attempt.get("reference_mask_used"),
            "reference_mask_role": attempt.get("reference_mask_role"),
            "failure_type": failure_type,
            "metrics": attempt.get("metrics") or {},
        },
        "validation_status": "pending_review",
        "allowed_action": "candidate_review_only",
        "formal_update_allowed": False,
    }


def _proposal_for_vision_failure(failure_type: str) -> str:
    proposals = {
        "under_segmentation": (
            "Review prompt boxes, mask post-processing, and region definitions for "
            "under-segmented visual evidence."
        ),
        "over_segmentation": (
            "Review prompt constraints and quality gates for over-segmented visual evidence."
        ),
        "merged_independent_findings": (
            "Review independence rules so overlapping findings are not counted as "
            "separate diagnostic evidence without validation."
        ),
        "low_quality_mask": (
            "Review mask quality thresholds and require human or dataset validation "
            "before promotion."
        ),
        "tool_not_ready": "Keep this tool failure as a candidate runtime issue for review.",
    }
    return proposals.get(
        failure_type,
        "Review this visual evidence failure before changing a formal knowledge.",
    )


def _slug(value: str) -> str:
    cleaned = []
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
        else:
            cleaned.append("_")
    return "_".join(part for part in "".join(cleaned).split("_") if part)


def _build_fhn_case(response: dict[str, Any], pipeline_summary: dict[str, Any]) -> dict[str, Any]:
    bundle = dict(pipeline_summary.get("visual_evidence_bundle") or {})
    image_context = dict(bundle.get("image_context") or {})
    image_outputs = dict(bundle.get("image_outputs") or {})
    quality_warnings = [
        warning for warning in bundle.get("quality_warnings") or [] if isinstance(warning, dict)
    ]
    structured_visual_facts = [
        fact for fact in response.get("structured_visual_facts") or [] if isinstance(fact, dict)
    ]
    used_visual_facts = [
        fact for fact in response.get("used_visual_facts") or [] if isinstance(fact, dict)
    ]
    excluded_visual_facts = [
        fact for fact in response.get("excluded_visual_facts") or [] if isinstance(fact, dict)
    ]
    failure_types = _failure_types_from_no_mask_case(
        structured_visual_facts=structured_visual_facts,
        excluded_visual_facts=excluded_visual_facts,
        quality_warning_count=len(quality_warnings),
    )
    diagnosis_allowed = bool(used_visual_facts)
    manual_review_items = _manual_review_items_for_no_mask_case(
        structured_visual_facts=structured_visual_facts,
        used_visual_facts=used_visual_facts,
        excluded_visual_facts=excluded_visual_facts,
    )
    return {
        "case_id": str(response.get("case_id") or "fhn_no_mask_multifinding"),
        "disease_knowledge": str(pipeline_summary.get("disease_key") or "femoral_head_necrosis"),
        "modality": str(image_context.get("modality") or "xray"),
        "reference_available": False,
        "visual_fact_count": len(structured_visual_facts),
        "adopted_fact_count": len(used_visual_facts),
        "excluded_fact_count": len(excluded_visual_facts),
        "mask_artifact_count": _count_paths(image_outputs, ["mask_path"]),
        "overlay_artifact_count": _count_paths(
            image_outputs,
            ["overlay_path", "comparison_path", "bbox_overlay_path"],
        ),
        "mean_dice": None,
        "mean_iou": None,
        "mean_absolute_volume_error_ml": None,
        "false_positive_component_count": None,
        "false_negative_component_count": None,
        "metrics": dict(bundle.get("numeric_evidence") or {}),
        "quality_warning_count": len(quality_warnings),
        "failure_types": failure_types,
        "diagnosis_allowed": diagnosis_allowed,
        "manual_review_items": manual_review_items,
        "manual_review_counts": _manual_review_counts(manual_review_items),
        "candidate_queue_action": "add_visual_protocol_review"
        if failure_types
        else "no_action",
        "review_status": "pending_review",
        "source_result_path": None,
        "blocked_reason": None
        if diagnosis_allowed
        else "no adopted visual facts available for diagnosis reasoning",
    }


def _build_non_reference_attempts(
    *,
    prompt_summary_path: Path | str | None,
    auto_eval_summary_path: Path | str | None,
) -> list[dict[str, Any]]:
    prompt_summary = (
        _read_json(Path(prompt_summary_path))
        if prompt_summary_path and Path(prompt_summary_path).exists()
        else {}
    )
    auto_eval_summary = (
        _read_json(Path(auto_eval_summary_path))
        if auto_eval_summary_path and Path(auto_eval_summary_path).exists()
        else {}
    )
    if not prompt_summary and not auto_eval_summary:
        return []
    image_path = str(prompt_summary.get("image_path") or "")
    case_id = str(auto_eval_summary.get("case_id") or _case_id_from_image_path(image_path))
    medsam2_configuration = dict(auto_eval_summary.get("medsam2_configuration") or {})
    evaluation = dict(auto_eval_summary.get("evaluation") or {})
    auto_eval_status = auto_eval_summary.get("status")
    real_medsam2_call_attempted = bool(auto_eval_summary.get("real_call_attempted"))
    medsam2_ready = bool(medsam2_configuration.get("real_call_ready")) or (
        auto_eval_status == "ok" and real_medsam2_call_attempted
    )
    prompt_boundary = dict(prompt_summary.get("data_boundary") or {})
    auto_eval_boundary = dict(auto_eval_summary.get("data_boundary") or {})
    prompt_source = str(
        auto_eval_summary.get("prompt_source")
        or prompt_summary.get("prompt_source")
        or "unknown"
    )
    return [
        {
            "case_id": case_id or "unknown_non_reference_case",
            "disease_knowledge": str(auto_eval_summary.get("disease_key") or "diffuse_glioma_brats"),
            "modality": "mri",
            "prompt_status": prompt_summary.get("status"),
            "auto_eval_status": auto_eval_status,
            "prompt_source": prompt_source,
            "slice_index": prompt_summary.get("slice_index"),
            "box_count": len(prompt_summary.get("boxes") or []),
            "real_vlm_call_attempted": bool(prompt_summary.get("real_call_attempted")),
            "real_medsam2_call_attempted": real_medsam2_call_attempted,
            "reference_mask_used": bool(prompt_boundary.get("reference_mask_used")),
            "reference_mask_role": auto_eval_boundary.get("reference_mask_role"),
            "medsam2_ready": medsam2_ready,
            "missing_medsam2_configuration": list(
                medsam2_configuration.get("missing_command_template_placeholders") or []
            ),
            "metrics": evaluation,
            "failure_types": _failure_types_from_non_reference_attempt(
                status=auto_eval_status,
                evaluation=evaluation,
            ),
            "artifacts": {
                "slice_png_path": prompt_summary.get("slice_png_path"),
                "medsam2_prompt_path": prompt_summary.get("medsam2_prompt_path"),
                "bbox_overlay_path": prompt_summary.get("bbox_overlay_path"),
                "mask_path": (auto_eval_summary.get("image_outputs") or {}).get("mask_path"),
                "overlay_path": (auto_eval_summary.get("image_outputs") or {}).get("overlay_path"),
                "auto_eval_summary_path": str(auto_eval_summary_path)
                if auto_eval_summary_path
                else None,
            },
            "diagnosis_allowed": False,
            "blocked_reason": (
                None
                if auto_eval_summary.get("status") == "ok"
                else "non-reference automatic segmentation is not ready"
            ),
        }
    ]


def _failure_types_from_non_reference_attempt(
    *,
    status: Any,
    evaluation: dict[str, Any],
) -> list[str]:
    if status != "ok":
        return []
    failures: list[str] = []
    dice_values = [
        float(value)
        for key, value in evaluation.items()
        if key.endswith("_dice") and isinstance(value, (int, float))
    ]
    if any(value <= 0.0 for value in dice_values):
        failures.append("under_segmentation")
    if any(0.0 < value < 0.5 for value in dice_values):
        failures.append("low_quality_mask")
    false_positive_counts = [
        int(value)
        for key, value in evaluation.items()
        if key.endswith("_false_positive_component_count") and isinstance(value, int)
    ]
    if any(value > 0 for value in false_positive_counts):
        failures.append("over_segmentation")
    return sorted(set(failures))


def _build_aggregate(
    cases: list[dict[str, Any]],
    non_reference_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    failure_counter: Counter[str] = Counter()
    for case in cases:
        failure_counter.update(case.get("failure_types") or [])
    non_reference_attempts = non_reference_attempts or []
    return {
        "case_count": len(cases),
        "reference_case_count": sum(1 for case in cases if case.get("reference_available")),
        "no_mask_case_count": sum(1 for case in cases if not case.get("reference_available")),
        "diagnosis_allowed_count": sum(1 for case in cases if case.get("diagnosis_allowed")),
        "non_reference_attempt_count": len(non_reference_attempts),
        "non_reference_prompt_ok_count": sum(
            1 for attempt in non_reference_attempts if attempt.get("prompt_status") == "ok"
        ),
        "non_reference_auto_eval_ready_count": sum(
            1 for attempt in non_reference_attempts if attempt.get("auto_eval_status") == "ok"
        ),
        "total_visual_fact_count": sum(int(case.get("visual_fact_count") or 0) for case in cases),
        "total_adopted_fact_count": sum(int(case.get("adopted_fact_count") or 0) for case in cases),
        "total_excluded_fact_count": sum(int(case.get("excluded_fact_count") or 0) for case in cases),
        "reference_mean_dice": _mean_case_metric(cases, "mean_dice"),
        "reference_mean_iou": _mean_case_metric(cases, "mean_iou"),
        "reference_mean_absolute_volume_error_ml": _mean_case_metric(
            cases,
            "mean_absolute_volume_error_ml",
        ),
        "reference_false_positive_component_count": sum(
            int(case.get("false_positive_component_count") or 0)
            for case in cases
            if case.get("reference_available")
        ),
        "reference_false_negative_component_count": sum(
            int(case.get("false_negative_component_count") or 0)
            for case in cases
            if case.get("reference_available")
        ),
        "manual_review_counts": _aggregate_manual_review_counts(cases),
        "failure_type_counts": dict(sorted(failure_counter.items())),
    }


def _build_next_actions(
    cases: list[dict[str, Any]],
    non_reference_attempts: list[dict[str, Any]] | None = None,
) -> list[str]:
    actions: list[str] = []
    reference_cases = [case for case in cases if case.get("reference_available")]
    reference_metrics_complete = bool(reference_cases) and all(
        case.get("mean_iou") is not None
        and case.get("mean_absolute_volume_error_ml") is not None
        and case.get("false_positive_component_count") is not None
        and case.get("false_negative_component_count") is not None
        for case in reference_cases
    )
    if reference_cases and not reference_metrics_complete:
        actions.append("Add IoU, volume error, and component-count metrics for reference-mask cases.")
    elif reference_cases:
        actions.append("Review low-performing reference subregions and record failure categories.")
    no_mask_cases = [case for case in cases if not case.get("reference_available")]
    no_mask_review_labels_ready = bool(no_mask_cases) and all(
        case.get("manual_review_counts") is not None for case in no_mask_cases
    )
    if no_mask_cases and not no_mask_review_labels_ready:
        actions.append("Add manual review labels for no-mask findings: accepted, rejected, or uncertain.")
    elif no_mask_cases:
        actions.append("Run human review for no-mask suggested labels and persist reviewer notes.")
    if any(case.get("failure_types") for case in cases):
        actions.append("Route failure records to self_evolving_queue as candidate-only visual protocol reviews.")
    non_reference_attempts = non_reference_attempts or []
    if any(
        attempt.get("prompt_status") == "ok" and attempt.get("auto_eval_status") != "ok"
        for attempt in non_reference_attempts
    ):
        actions.append("Configure MedSAM2 runner to complete non-reference VLM prompt auto-evaluation.")
    if any(attempt.get("failure_types") for attempt in non_reference_attempts):
        actions.append("Review non-reference VLM+MedSAM2 metric failures before any knowledge update.")
    return actions


def _failure_types_from_reference_case(
    case: dict[str, Any],
    evaluation: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    if case.get("status") != "ok":
        failures.append("tool_not_ready")
    dice_values = [
        float(value)
        for key, value in evaluation.items()
        if key.endswith("_dice") and isinstance(value, (int, float))
    ]
    if any(value <= 0.0 for value in dice_values):
        failures.append("under_segmentation")
    return sorted(set(failures))


def _reference_evaluation_for_case(
    *,
    case: dict[str, Any],
    result_payload: dict[str, Any],
    evaluator: Any,
) -> dict[str, Any]:
    evaluation = dict(case.get("evaluation") or result_payload.get("evaluation") or {})
    if any(key.endswith("_iou") for key in evaluation):
        return evaluation
    result = dict(result_payload.get("result") or {})
    image_outputs = dict(result.get("image_outputs") or {})
    prompt = dict(result_payload.get("segmentation_prompt") or {})
    prediction_mask = image_outputs.get("mask_path")
    reference_mask = prompt.get("reference_mask_path")
    if not prediction_mask or not reference_mask:
        return evaluation
    try:
        extended = evaluator.evaluate(
            prediction_mask_path=prediction_mask,
            reference_mask_path=reference_mask,
        )
    except Exception:
        return evaluation
    merged = dict(evaluation)
    merged.update(extended)
    return merged


def _failure_types_from_no_mask_case(
    *,
    structured_visual_facts: list[dict[str, Any]],
    excluded_visual_facts: list[dict[str, Any]],
    quality_warning_count: int,
) -> list[str]:
    failures: list[str] = []
    if quality_warning_count:
        failures.append("low_quality_mask")
    if excluded_visual_facts:
        failures.append("merged_independent_findings")
    if any(str(fact.get("quality_level") or "").lower() == "low" for fact in structured_visual_facts):
        failures.append("low_quality_mask")
    return sorted(set(failures))


def _manual_review_items_for_no_mask_case(
    *,
    structured_visual_facts: list[dict[str, Any]],
    used_visual_facts: list[dict[str, Any]],
    excluded_visual_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    used_ids = {str(fact.get("finding_id")) for fact in used_visual_facts}
    excluded_by_id = {
        str(fact.get("finding_id")): fact
        for fact in excluded_visual_facts
        if fact.get("finding_id")
    }
    items: list[dict[str, Any]] = []
    for fact in structured_visual_facts:
        finding_id = str(fact.get("finding_id") or "")
        if finding_id in used_ids:
            label = "accepted"
            reason = "adopted_visual_fact"
        elif finding_id in excluded_by_id:
            label = "rejected"
            excluded_fact = excluded_by_id[finding_id]
            reason = str(
                excluded_fact.get("exclusion_reason")
                or excluded_fact.get("non_independent_reason")
                or "excluded_visual_fact"
            )
        else:
            label = "uncertain"
            reason = "not_adopted_or_excluded"
        items.append(
            {
                "finding_id": finding_id or None,
                "target": fact.get("target"),
                "suggested_label": label,
                "review_status": "pending_human_review",
                "reason": reason,
            }
        )
    return items


def _manual_review_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "accepted": sum(1 for item in items if item.get("suggested_label") == "accepted"),
        "rejected": sum(1 for item in items if item.get("suggested_label") == "rejected"),
        "uncertain": sum(1 for item in items if item.get("suggested_label") == "uncertain"),
    }


def _aggregate_manual_review_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"accepted": 0, "rejected": 0, "uncertain": 0}
    for case in cases:
        counts = case.get("manual_review_counts") or {}
        for key in totals:
            totals[key] += int(counts.get(key) or 0)
    return totals


def _count_paths(payload: dict[str, Any], keys: list[str]) -> int:
    return sum(1 for key in keys if str(payload.get(key) or "").strip())


def _sum_metric_suffix(payload: dict[str, Any], suffix: str) -> int:
    return sum(
        int(value)
        for key, value in payload.items()
        if key.endswith(suffix) and isinstance(value, (int, float))
    )


def _mean_case_metric(cases: list[dict[str, Any]], key: str) -> float | None:
    values = [
        float(case[key])
        for case in cases
        if case.get("reference_available") and isinstance(case.get(key), (int, float))
    ]
    return round(sum(values) / len(values), 6) if values else None


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_json(path_value: Any) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(str(path_value))
    if not path.exists():
        return {}
    return _read_json(path)


def _case_id_from_image_path(image_path: str) -> str:
    name = Path(image_path).name if image_path else ""
    if name.endswith("_flair.nii.gz"):
        return name[: -len("_flair.nii.gz")].lower()
    if name.endswith(".nii.gz"):
        return name[: -len(".nii.gz")].lower()
    return Path(name).stem.lower() if name else ""


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# MedScope Vision Evidence Evaluation Summary",
        "",
        "This file summarizes Phase B visual evidence evaluation artifacts.",
        "",
        "## Aggregate",
        "",
    ]
    aggregate = payload.get("aggregate") or {}
    for key in [
        "case_count",
        "reference_case_count",
        "no_mask_case_count",
        "diagnosis_allowed_count",
        "total_visual_fact_count",
        "total_adopted_fact_count",
        "total_excluded_fact_count",
        "reference_mean_dice",
        "reference_mean_iou",
        "reference_mean_absolute_volume_error_ml",
        "reference_false_positive_component_count",
        "reference_false_negative_component_count",
    ]:
        lines.append(f"- `{key}`: `{aggregate.get(key)}`")
    lines.append(f"- `manual_review_counts`: `{aggregate.get('manual_review_counts')}`")
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| case_id | disease_knowledge | modality | reference | visual facts | adopted | excluded | mean dice | mean IoU | volume error ml | FP comp | FN comp | failures | diagnosis allowed |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for case in payload.get("cases") or []:
        failures = ", ".join(case.get("failure_types") or []) or "none"
        mean_dice = case.get("mean_dice")
        mean_iou = case.get("mean_iou")
        mean_volume_error = case.get("mean_absolute_volume_error_ml")
        lines.append(
            "| {case_id} | {disease_knowledge} | {modality} | {reference} | {visual} | "
            "{adopted} | {excluded} | {mean_dice} | {mean_iou} | {volume_error} | "
            "{fp_components} | {fn_components} | {failures} | {diagnosis_allowed} |".format(
                case_id=case.get("case_id"),
                disease_knowledge=case.get("disease_knowledge"),
                modality=case.get("modality"),
                reference=case.get("reference_available"),
                visual=case.get("visual_fact_count"),
                adopted=case.get("adopted_fact_count"),
                excluded=case.get("excluded_fact_count"),
                mean_dice="" if mean_dice is None else mean_dice,
                mean_iou="" if mean_iou is None else mean_iou,
                volume_error="" if mean_volume_error is None else mean_volume_error,
                fp_components=(
                    ""
                    if case.get("false_positive_component_count") is None
                    else case.get("false_positive_component_count")
                ),
                fn_components=(
                    ""
                    if case.get("false_negative_component_count") is None
                    else case.get("false_negative_component_count")
                ),
                failures=failures,
                diagnosis_allowed=case.get("diagnosis_allowed"),
            )
        )
    manual_items = [
        (case.get("case_id"), item)
        for case in payload.get("cases") or []
        for item in case.get("manual_review_items") or []
        if isinstance(item, dict)
    ]
    if manual_items:
        lines.extend(
            [
                "",
                "## Manual Review Items",
                "",
                "| case_id | finding_id | target | suggested_label | review_status | reason |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for case_id, item in manual_items:
            lines.append(
                "| {case_id} | {finding_id} | {target} | {label} | {status} | {reason} |".format(
                    case_id=case_id,
                    finding_id=item.get("finding_id"),
                    target=item.get("target"),
                    label=item.get("suggested_label"),
                    status=item.get("review_status"),
                    reason=item.get("reason"),
                )
            )
    non_reference_attempts = [
        attempt
        for attempt in payload.get("non_reference_attempts") or []
        if isinstance(attempt, dict)
    ]
    if non_reference_attempts:
        lines.extend(
            [
                "",
                "## Non-reference Attempts",
                "",
                "| case_id | prompt_status | auto_eval_status | prompt_source | boxes | reference_mask_used | medsam2_ready |",
                "| --- | --- | --- | --- | ---: | --- | --- |",
            ]
        )
        for attempt in non_reference_attempts:
            lines.append(
                "| {case_id} | {prompt_status} | {auto_eval_status} | {prompt_source} | "
                "{box_count} | {reference_mask_used} | {medsam2_ready} |".format(
                    case_id=attempt.get("case_id"),
                    prompt_status=attempt.get("prompt_status"),
                    auto_eval_status=attempt.get("auto_eval_status"),
                    prompt_source=attempt.get("prompt_source"),
                    box_count=attempt.get("box_count"),
                    reference_mask_used=attempt.get("reference_mask_used"),
                    medsam2_ready=attempt.get("medsam2_ready"),
                )
            )
    lines.extend(["", "## Next Actions", ""])
    for action in payload.get("next_actions") or []:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def _render_candidate_queue_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# MedScope Vision Evidence Candidate Queue",
        "",
        "This artifact is candidate-only. It records visual evaluation failures and manual review labels for the Agentic Runtime / Evidence Gateway.",
        "",
        "- `status`: `{}`".format(payload.get("status")),
        "- `candidate_count`: `{}`".format(payload.get("candidate_count")),
        "- `formal_update_allowed=false`",
        "- `formal_knowledge_updated=false`",
        "- `formal_guideline_updated=false`",
        "- `diagnosis_report_updated=false`",
        "",
        "## Runtime Gateway Mapping",
        "",
    ]
    mapping = payload.get("runtime_gateway_mapping") or {}
    lines.append(f"- `layer`: `{mapping.get('layer')}`")
    lines.append(f"- `stages`: `{mapping.get('stages')}`")
    lines.append(f"- `note`: {mapping.get('presentation_note')}")
    lines.extend(
        [
            "",
            "## Queue Items",
            "",
            "| item_id | case_id | type | warning | knowledge | modality | validation | allowed_action |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in payload.get("queue_items") or []:
        lines.append(
            "| {item_id} | {case_id} | {candidate_type} | {warning} | {knowledge} | "
            "{modality} | {validation} | {allowed_action} |".format(
                item_id=item.get("item_id"),
                case_id=item.get("source_case_id"),
                candidate_type=item.get("candidate_type"),
                warning=item.get("source_warning_code"),
                knowledge=item.get("disease_knowledge"),
                modality=item.get("modality"),
                validation=item.get("validation_status"),
                allowed_action=item.get("allowed_action"),
            )
        )
    lines.extend(
        [
            "",
            "## Review Policy",
            "",
            "- `required_review`: `{}`".format(
                (payload.get("review_policy") or {}).get("required_review")
            ),
            "- `promotion_rule`: {}".format(
                (payload.get("review_policy") or {}).get("promotion_rule")
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _render_candidate_validation_gate_markdown(payload: dict[str, Any]) -> str:
    review_summary = payload.get("review_summary") or {}
    lines = [
        "# MedScope Vision Evidence Candidate Validation Gate",
        "",
        "This artifact records reviewer notes against visual evidence candidate items. It is still candidate-only.",
        "",
        "- `status`: `{}`".format((payload.get("promotion_decision") or {}).get("status")),
        "- `reason`: `{}`".format((payload.get("promotion_decision") or {}).get("reason")),
        "- `formal_update_allowed=false`",
        "- `formal_knowledge_updated=false`",
        "- `formal_guideline_updated=false`",
        "- `diagnosis_report_updated=false`",
        "",
        "## Review Summary",
        "",
    ]
    for key in [
        "item_count",
        "reviewed_count",
        "pending_count",
        "accepted_count",
        "rejected_count",
        "needs_revision_count",
    ]:
        lines.append(f"- `{key}`: `{review_summary.get(key)}`")
    lines.extend(
        [
            "",
            "## Item Validations",
            "",
            "| item_id | case_id | type | warning | review_status | validation_status | allowed_action |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in payload.get("item_validations") or []:
        lines.append(
            "| {item_id} | {case_id} | {candidate_type} | {warning} | {review_status} | "
            "{validation_status} | {allowed_action} |".format(
                item_id=item.get("item_id"),
                case_id=item.get("source_case_id"),
                candidate_type=item.get("candidate_type"),
                warning=item.get("source_warning_code"),
                review_status=item.get("review_status"),
                validation_status=item.get("validation_status"),
                allowed_action=item.get("allowed_action"),
            )
        )
    lines.extend(["", "## Review Requirements", ""])
    for requirement in payload.get("review_requirements") or []:
        lines.append(f"- {requirement}")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a unified Phase B visual evidence evaluation summary."
    )
    parser.add_argument("--brats-summary", default=str(DEFAULT_BRATS_SUMMARY))
    parser.add_argument("--fhn-response", default=str(DEFAULT_FHN_RESPONSE))
    parser.add_argument("--fhn-pipeline-summary", default=str(DEFAULT_FHN_PIPELINE_SUMMARY))
    parser.add_argument(
        "--non-reference-prompt-summary",
        default=str(DEFAULT_NON_REFERENCE_PROMPT_SUMMARY),
    )
    parser.add_argument(
        "--non-reference-auto-eval-summary",
        default=str(DEFAULT_NON_REFERENCE_AUTO_EVAL_SUMMARY),
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--write-candidate-queue",
        action="store_true",
        help="Also write candidate-only self-evolving queue artifacts for visual evaluation.",
    )
    parser.add_argument(
        "--reviewer-notes",
        default=None,
        help="Optional reviewer notes JSON to validate visual evidence candidate queue items.",
    )
    parser.add_argument(
        "--write-validation-gate",
        action="store_true",
        help="Also write candidate validation gate artifacts for the visual candidate queue.",
    )
    parser.add_argument(
        "--write-reviewer-notes-template",
        action="store_true",
        help="Write a pending human-review notes template for visual candidate queue items.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_vision_evidence_eval_summary(
        brats_summary_path=args.brats_summary,
        fhn_response_path=args.fhn_response,
        fhn_pipeline_summary_path=args.fhn_pipeline_summary,
        non_reference_prompt_summary_path=args.non_reference_prompt_summary,
        non_reference_auto_eval_summary_path=args.non_reference_auto_eval_summary,
        output_dir=args.output_dir,
    )
    if args.write_candidate_queue:
        candidate_queue = build_vision_evidence_candidate_queue(
            eval_summary=payload,
            output_dir=args.output_dir,
        )
        payload["candidate_queue_output_paths"] = candidate_queue.get("output_paths")
        if args.write_reviewer_notes_template:
            reviewer_template = build_vision_evidence_reviewer_notes_template(
                candidate_queue=candidate_queue,
                output_dir=args.output_dir,
            )
            payload["reviewer_notes_template_output_paths"] = reviewer_template.get(
                "output_paths"
            )
        if args.write_validation_gate:
            validation_gate = build_vision_evidence_candidate_validation_gate(
                candidate_queue=candidate_queue,
                reviewer_notes_path=args.reviewer_notes,
                output_dir=args.output_dir,
            )
            payload["candidate_validation_gate_output_paths"] = validation_gate.get(
                "output_paths"
            )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
