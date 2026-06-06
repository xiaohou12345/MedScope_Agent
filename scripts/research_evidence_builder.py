"""Build proposal-only research evidence artifacts.

The builder accepts already supplied research/source metadata. It does not
search papers, update formal skills, or modify diagnosis outputs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("output/fake/research_evidence_gateway")
ALLOWED_CANDIDATE_TYPES = {
    "research_evidence_proposal",
    "candidate_skill_extension",
    "candidate_measurement_protocol",
    "candidate_quality_gate_rule",
}
TRUSTED_SOURCE_TYPES = {
    "peer_reviewed_journal",
    "medical_guideline",
    "consensus_statement",
    "regulatory_document",
}
MIN_SAMPLE_SIZE = 50
FRESH_PUBLICATION_YEAR = 2020


def build_research_evidence_proposal(
    *,
    disease_key: str,
    target_skill_id: str,
    sources: list[dict[str, Any]],
    extracted_claims: list[dict[str, Any]],
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    _validate_boundary_inputs(extracted_claims)
    normalized_sources = [_normalize_source(source) for source in sources]
    source_by_id = {
        str(source.get("source_id") or f"source_{index + 1}"): source
        for index, source in enumerate(normalized_sources)
    }
    candidate_extensions = [
        _build_candidate_extension(
            claim=claim,
            source=_source_for_claim(claim, source_by_id, normalized_sources),
            index=index,
        )
        for index, claim in enumerate(extracted_claims, start=1)
    ]
    quality_gate = _build_quality_gate(candidate_extensions)
    payload = {
        "schema_version": "research_evidence_proposal.v1",
        "disease_key": disease_key,
        "target_skill_id": target_skill_id,
        "proposal_status": "proposal_only",
        "sources": normalized_sources,
        "candidate_extensions": candidate_extensions,
        "quality_gate": quality_gate,
        "runtime_safety": {
            "input_mode": "supplied_sources_only",
            "paper_search_performed": False,
            "candidate_artifacts_only": True,
            "formal_skill_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "formal_update_allowed": False,
            "diagnosis_allowed": False,
        },
    }
    if output_dir is not None:
        _write_outputs(payload, Path(output_dir))
    return payload


def _validate_boundary_inputs(claims: list[dict[str, Any]]) -> None:
    for claim in claims:
        if claim.get("formal_update_allowed") is True:
            raise ValueError("research evidence claims cannot request formal_update_allowed")
        if claim.get("diagnosis_allowed") is True:
            raise ValueError("research evidence claims cannot request diagnosis_allowed")


def _normalize_source(source: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(source)
    normalized.setdefault("source_type", "unknown")
    normalized.setdefault("evidence_level", "unknown")
    normalized.setdefault("sample_size", 0)
    normalized.setdefault("publication_year", None)
    return normalized


def _source_for_claim(
    claim: dict[str, Any],
    source_by_id: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    source_id = str(claim.get("source_id") or "")
    if source_id and source_id in source_by_id:
        return source_by_id[source_id]
    if len(sources) == 1:
        return sources[0]
    return {}


def _build_candidate_extension(
    *,
    claim: dict[str, Any],
    source: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    candidate_type = str(claim.get("claim_type") or "research_evidence_proposal")
    if candidate_type not in ALLOWED_CANDIDATE_TYPES:
        candidate_type = "research_evidence_proposal"
    candidate = {
        "item_id": str(claim.get("claim_id") or f"research_claim_{index:03d}"),
        "candidate_type": candidate_type,
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "target_protocol_section": claim.get("target_protocol_section"),
        "summary": claim.get("summary"),
        "modality": claim.get("modality"),
        "applicability": dict(claim.get("applicability") or {}),
        "limitations": list(claim.get("limitations") or []),
        "allowed_action": "proposal_only_no_formal_update",
        "formal_update_allowed": False,
        "diagnosis_allowed": False,
        "required_approval": "evidence_gateway_and_human_review",
    }
    candidate["quality_gate"] = _validate_candidate(candidate, source)
    return candidate


def _build_quality_gate(candidate_extensions: list[dict[str, Any]]) -> dict[str, Any]:
    validations = [
        dict(candidate.get("quality_gate") or {})
        for candidate in candidate_extensions
    ]
    blocked = [item for item in validations if item.get("decision") == "blocked"]
    needs_review = [item for item in validations if item.get("decision") == "candidate_review_only"]
    status = "blocked" if blocked else "candidate_review_only"
    return {
        "schema_version": "research_evidence_quality_gate.v1",
        "claim_count": len(candidate_extensions),
        "blocked_count": len(blocked),
        "candidate_review_only_count": len(needs_review),
        "claim_validations": validations,
        "required_reviews": [
            "human_review_required",
            "guideline_conflict_review_required",
            "applicability_review_required",
            "external_validation_required",
        ],
        "promotion_decision": {
            "status": status,
            "reason": (
                "research_evidence_failed_quality_gate"
                if blocked
                else "research_evidence_requires_human_review_before_any_promotion"
            ),
            "formal_update_allowed": False,
            "diagnosis_allowed": False,
            "required_approval": "explicit_human_promotion_approval",
        },
        "runtime_safety": {
            "read_only": True,
            "proposal_only": True,
            "formal_skill_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
        },
    }


def _validate_candidate(candidate: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    passed_checks: list[str] = []
    failed_checks: list[str] = []

    source_type = str(source.get("source_type") or "")
    if source_type in TRUSTED_SOURCE_TYPES:
        passed_checks.append("trusted_source_type")
    else:
        failed_checks.append("source_type_not_peer_reviewed_or_guideline")

    publication_year = _coerce_int(source.get("publication_year"))
    if publication_year is not None and publication_year >= FRESH_PUBLICATION_YEAR:
        passed_checks.append("fresh_or_current_source")
    else:
        failed_checks.append("stale_or_missing_publication_year")

    sample_size = _coerce_int(source.get("sample_size")) or 0
    if sample_size >= MIN_SAMPLE_SIZE:
        passed_checks.append("sample_size_minimum_met")
    else:
        failed_checks.append("sample_size_below_minimum")

    evidence_level = str(source.get("evidence_level") or "").lower()
    if evidence_level in {"moderate", "high", "guideline", "consensus"}:
        passed_checks.append("evidence_level_acceptable_for_candidate_review")
    else:
        failed_checks.append("evidence_level_too_low")

    if _text_equal(source.get("modality"), candidate.get("modality")):
        passed_checks.append("modality_applicable")
    else:
        failed_checks.append("modality_mismatch")

    applicability = candidate.get("applicability") or {}
    if _population_matches(source.get("population"), applicability.get("population")):
        passed_checks.append("population_applicable")
    else:
        failed_checks.append("population_mismatch")

    if candidate.get("target_protocol_section"):
        passed_checks.append("target_protocol_section_present")
    else:
        failed_checks.append("target_protocol_section_missing")

    if candidate.get("summary"):
        passed_checks.append("claim_summary_present")
    else:
        failed_checks.append("claim_summary_missing")

    decision = "blocked" if failed_checks else "candidate_review_only"
    return {
        "item_id": candidate.get("item_id"),
        "candidate_type": candidate.get("candidate_type"),
        "source_id": candidate.get("source_id"),
        "decision": decision,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "formal_update_allowed": False,
        "diagnosis_allowed": False,
        "allowed_action": "proposal_only_no_formal_update",
    }


def _text_equal(left: Any, right: Any) -> bool:
    return str(left or "").strip().lower() == str(right or "").strip().lower()


def _population_matches(source_population: Any, claim_population: Any) -> bool:
    left = set(str(source_population or "").lower().replace(",", " ").split())
    right = set(str(claim_population or "").lower().replace(",", " ").split())
    if not left or not right:
        return False
    return bool(left.intersection(right))


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_outputs(payload: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    proposal_path = output / "research_evidence_proposal.json"
    gate_path = output / "research_evidence_quality_gate.json"
    markdown_path = output / "research_evidence_proposal.md"
    payload["output_paths"] = {
        "proposal_json_path": str(proposal_path),
        "quality_gate_json_path": str(gate_path),
        "markdown_path": str(markdown_path),
    }
    proposal_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    gate_path.write_text(
        json.dumps(payload["quality_gate"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")


def _render_markdown(payload: dict[str, Any]) -> str:
    gate = payload.get("quality_gate") or {}
    decision = gate.get("promotion_decision") or {}
    safety = payload.get("runtime_safety") or {}
    lines = [
        "# Research Evidence Proposal",
        "",
        "This artifact records supplied research evidence as candidate-only proposals.",
        "It does not search papers or update formal guideline skills.",
        "",
        f"- `disease_key`: `{payload.get('disease_key')}`",
        f"- `target_skill_id`: `{payload.get('target_skill_id')}`",
        f"- `proposal_status`: `{payload.get('proposal_status')}`",
        f"- `quality_gate_status`: `{decision.get('status')}`",
        "- `formal_update_allowed=false`",
        f"- `diagnosis_allowed={str(safety.get('diagnosis_allowed')).lower()}`",
        f"- `paper_search_performed={str(safety.get('paper_search_performed')).lower()}`",
        "",
        "## Candidate Extensions",
        "",
        "| item_id | type | source | decision | allowed_action |",
        "| --- | --- | --- | --- | --- |",
    ]
    for candidate in payload.get("candidate_extensions") or []:
        gate_result = candidate.get("quality_gate") or {}
        lines.append(
            "| {item_id} | {candidate_type} | {source_id} | {decision} | {allowed_action} |".format(
                item_id=candidate.get("item_id"),
                candidate_type=candidate.get("candidate_type"),
                source_id=candidate.get("source_id"),
                decision=gate_result.get("decision"),
                allowed_action=candidate.get("allowed_action"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    request = json.loads(args.input_json.read_text(encoding="utf-8"))
    payload = build_research_evidence_proposal(
        disease_key=request["disease_key"],
        target_skill_id=request["target_skill_id"],
        sources=list(request.get("sources") or []),
        extracted_claims=list(request.get("extracted_claims") or []),
        output_dir=args.output_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
