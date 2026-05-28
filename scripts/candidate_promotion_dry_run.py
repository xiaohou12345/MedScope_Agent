"""Build a candidate promotion dry-run artifact.

The dry run turns reviewed candidate items into proposal-only records. It must not
update formal skills, guideline sources, or diagnosis reports.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("output/fake/candidate_promotion_dry_run")
DEFAULT_QUEUE_PATH = Path("output/fake/vision_evidence_candidate_queue.json")
DEFAULT_VALIDATION_GATE_PATH = Path("output/fake/vision_evidence_candidate_validation_gate.json")


def build_candidate_promotion_dry_run(
    *,
    candidate_queue: dict[str, Any] | None = None,
    candidate_queue_path: Path | str | None = None,
    validation_gate: dict[str, Any] | None = None,
    validation_gate_path: Path | str | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    queue_path = Path(candidate_queue_path) if candidate_queue_path else DEFAULT_QUEUE_PATH
    gate_path = (
        Path(validation_gate_path) if validation_gate_path else DEFAULT_VALIDATION_GATE_PATH
    )
    queue = candidate_queue if candidate_queue is not None else _read_json(queue_path)
    gate = validation_gate if validation_gate is not None else _read_json(gate_path)
    item_by_id = {
        str(item.get("item_id") or ""): item
        for item in queue.get("queue_items") or []
        if isinstance(item, dict) and item.get("item_id")
    }
    validations = [
        item
        for item in gate.get("item_validations") or []
        if isinstance(item, dict)
    ]
    proposals = [
        _build_promotion_proposal(validation, item_by_id[str(validation.get("item_id"))])
        for validation in validations
        if _is_accepted(validation) and str(validation.get("item_id")) in item_by_id
    ]
    non_promoted_items = [
        _build_non_promoted_item(validation)
        for validation in validations
        if not _is_accepted(validation)
    ]
    payload = {
        "schema_version": "candidate_promotion_dry_run.v1",
        "source_queue_schema_version": queue.get("schema_version"),
        "source_queue_path": None if candidate_queue is not None else str(queue_path),
        "source_validation_gate_schema_version": gate.get("schema_version"),
        "source_validation_gate_path": None if validation_gate is not None else str(gate_path),
        "proposal_count": len(proposals),
        "promotion_proposals": proposals,
        "non_promoted_items": non_promoted_items,
        "promotion_decision": {
            "status": "proposal_only" if proposals else "no_approved_candidates",
            "reason": (
                "approved_candidates_require_explicit_human_promotion_approval"
                if proposals
                else "no_reviewer_accepted_candidate_items"
            ),
            "formal_update_allowed": False,
            "required_approval": "explicit_human_promotion_approval",
        },
        "runtime_safety": {
            "dry_run_only": True,
            "candidate_artifacts_only": True,
            "formal_skill_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "formal_update_allowed": False,
        },
    }
    json_path = output / "candidate_promotion_dry_run.json"
    markdown_path = output / "candidate_promotion_dry_run.md"
    payload["output_paths"] = {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_accepted(validation: dict[str, Any]) -> bool:
    return validation.get("review_status") == "accepted"


def _build_promotion_proposal(
    validation: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    return {
        "item_id": item.get("item_id"),
        "source_case_id": item.get("source_case_id"),
        "candidate_type": item.get("candidate_type"),
        "source_warning_code": item.get("source_warning_code"),
        "proposed_artifact": _proposed_artifact_for_type(str(item.get("candidate_type") or "")),
        "proposal": item.get("proposal"),
        "evidence": item.get("evidence") or {},
        "review_decision": validation.get("review_status"),
        "reviewer_note": validation.get("reviewer_note") or {},
        "required_approval": "explicit_human_promotion_approval",
        "allowed_action": "proposal_only_no_formal_update",
        "formal_update_allowed": False,
    }


def _build_non_promoted_item(validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": validation.get("item_id"),
        "source_case_id": validation.get("source_case_id"),
        "candidate_type": validation.get("candidate_type"),
        "review_status": validation.get("review_status"),
        "decision": "kept_as_candidate",
        "formal_update_allowed": False,
    }


def _proposed_artifact_for_type(candidate_type: str) -> str:
    if candidate_type == "manual_review_label":
        return "candidate_review_label"
    if candidate_type == "quality_gate_rule":
        return "candidate_quality_gate_rule"
    return "candidate_skill_patch"


def _render_markdown(payload: dict[str, Any]) -> str:
    decision = payload.get("promotion_decision") or {}
    safety = payload.get("runtime_safety") or {}
    lines = [
        "# MedScope Candidate Promotion Dry Run",
        "",
        "This artifact converts reviewed candidates into proposal-only records. It does not update formal medical rules.",
        "",
        f"- `status`: `{decision.get('status')}`",
        f"- `reason`: `{decision.get('reason')}`",
        "- `formal_update_allowed=false`",
        f"- `proposal_count`: `{payload.get('proposal_count')}`",
        f"- `formal_skill_updated={str(safety.get('formal_skill_updated')).lower()}`",
        f"- `formal_guideline_updated={str(safety.get('formal_guideline_updated')).lower()}`",
        f"- `diagnosis_report_updated={str(safety.get('diagnosis_report_updated')).lower()}`",
        "",
        "## Promotion Proposals",
        "",
        "| item_id | case_id | type | proposed_artifact | required_approval |",
        "| --- | --- | --- | --- | --- |",
    ]
    for proposal in payload.get("promotion_proposals") or []:
        lines.append(
            "| {item_id} | {source_case_id} | {candidate_type} | {proposed_artifact} | {required_approval} |".format(
                item_id=proposal.get("item_id"),
                source_case_id=proposal.get("source_case_id"),
                candidate_type=proposal.get("candidate_type"),
                proposed_artifact=proposal.get("proposed_artifact"),
                required_approval=proposal.get("required_approval"),
            )
        )
    lines.extend(
        [
            "",
            "## Non-promoted Items",
            "",
            "| item_id | case_id | type | review_status | decision |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in payload.get("non_promoted_items") or []:
        lines.append(
            "| {item_id} | {source_case_id} | {candidate_type} | {review_status} | {decision} |".format(
                item_id=item.get("item_id"),
                source_case_id=item.get("source_case_id"),
                candidate_type=item.get("candidate_type"),
                review_status=item.get("review_status"),
                decision=item.get("decision"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-queue", default=str(DEFAULT_QUEUE_PATH))
    parser.add_argument("--validation-gate", default=str(DEFAULT_VALIDATION_GATE_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    payload = build_candidate_promotion_dry_run(
        candidate_queue_path=args.candidate_queue,
        validation_gate_path=args.validation_gate,
        output_dir=args.output_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
