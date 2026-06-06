"""Build proposal-only research evidence artifacts.

The builder accepts already supplied research/source metadata. It does not
search papers, update formal skills, or modify diagnosis outputs.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


DEFAULT_OUTPUT_DIR = Path("output/fake/research_evidence_gateway")
ALLOWED_CANDIDATE_TYPES = {
    "research_evidence_proposal",
    "candidate_skill_extension",
    "candidate_measurement_protocol",
    "candidate_quality_gate_rule",
    "differential_diagnosis_clue",
    "clinical_risk_context_clue",
}
TRUSTED_SOURCE_TYPES = {
    "peer_reviewed_journal",
    "medical_guideline",
    "consensus_statement",
    "regulatory_document",
}
MIN_SAMPLE_SIZE = 50
FRESH_PUBLICATION_YEAR = 2020
PubMedMetadataClient = Callable[[str, int], list[dict[str, Any]]]


class ResearchEvidenceRetriever:
    def __init__(self, pubmed_client: PubMedMetadataClient | None = None) -> None:
        self.pubmed_client = pubmed_client or _default_pubmed_metadata_client

    def retrieve(
        self,
        *,
        disease_key: str,
        modality: str,
        research_question: str,
        supplied_metadata: list[dict[str, Any]] | None = None,
        pubmed_enabled: bool = False,
        pubmed_limit: int = 10,
    ) -> dict[str, Any]:
        normalized_evidence: list[dict[str, Any]] = []
        for index, metadata in enumerate(supplied_metadata or [], start=1):
            normalized_evidence.append(
                normalize_research_metadata(
                    metadata,
                    disease_key=disease_key,
                    requested_modality=modality,
                    research_question=research_question,
                    source_origin="supplied_metadata",
                    index=index,
                )
            )

        pubmed_records: list[dict[str, Any]] = []
        query = _build_pubmed_query(disease_key, modality, research_question)
        if pubmed_enabled:
            pubmed_records = self.pubmed_client(query, pubmed_limit)
            offset = len(normalized_evidence)
            for index, metadata in enumerate(pubmed_records, start=offset + 1):
                normalized_evidence.append(
                    normalize_research_metadata(
                        metadata,
                        disease_key=disease_key,
                        requested_modality=modality,
                        research_question=research_question,
                        source_origin="pubmed",
                        index=index,
                    )
                )

        return {
            "schema_version": "research_evidence_retrieval.v1",
            "request": {
                "disease_key": disease_key,
                "modality": _normalize_modality(modality),
                "research_question": research_question,
            },
            "retrieval": {
                "supplied_metadata_count": len(supplied_metadata or []),
                "pubmed_enabled": pubmed_enabled,
                "pubmed_retrieval_attempted": pubmed_enabled,
                "pubmed_result_count": len(pubmed_records),
                "pubmed_query": query if pubmed_enabled else None,
                "status": (
                    "supplied_and_pubmed_metadata_normalized"
                    if pubmed_enabled
                    else "supplied_metadata_normalized"
                ),
            },
            "normalized_research_evidence": normalized_evidence,
            "runtime_safety": {
                "paper_search_performed": pubmed_enabled,
                "formal_skill_updated": False,
                "formal_guideline_updated": False,
                "diagnosis_report_updated": False,
                "formal_update_allowed": False,
                "diagnosis_allowed": False,
            },
        }


class ResearchEvidenceExtractor:
    def extract(
        self,
        *,
        disease_key: str,
        modality: str,
        research_question: str,
        supplied_texts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        extracted: list[dict[str, Any]] = []
        for index, text_source in enumerate(supplied_texts, start=1):
            extracted.append(
                _extract_research_evidence_from_text(
                    disease_key=disease_key,
                    requested_modality=modality,
                    research_question=research_question,
                    text_source=text_source,
                    index=index,
                )
            )
        return {
            "schema_version": "research_evidence_extraction.v1",
            "source_text_count": len(supplied_texts),
            "extracted_research_evidence": extracted,
            "runtime_safety": {
                "input_mode": "supplied_text_only",
                "pdf_binary_parsed": False,
                "llm_extraction_used": False,
                "formal_skill_updated": False,
                "formal_guideline_updated": False,
                "diagnosis_report_updated": False,
                "formal_update_allowed": False,
                "diagnosis_allowed": False,
            },
        }


class ResearchClaimBuilder:
    def build_claims(
        self,
        *,
        disease_key: str,
        normalized_research_evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        for index, evidence in enumerate(normalized_research_evidence, start=1):
            claim_type = _normalize_claim_type(evidence.get("candidate_claim_type"))
            claim = {
                "claim_id": _build_claim_id(disease_key, evidence, index),
                "claim_type": claim_type,
                "summary": _build_claim_summary(evidence, claim_type),
                "source_id": evidence.get("source_id"),
                "target_protocol_section": _target_section_for_claim(evidence, claim_type),
                "modality": evidence.get("modality") or "unknown",
                "applicability": {
                    "population": evidence.get("population") or "unknown",
                    "requires_external_validation": True,
                },
                "limitations": _claim_limitations(evidence),
                "evidence_level": evidence.get("evidence_level") or "unknown",
                "requires_external_validation": bool(
                    evidence.get("requires_external_validation", True)
                ),
                "formal_update_allowed": False,
                "diagnosis_allowed": False,
            }
            claims.append(claim)
        return claims


def build_research_evidence_review_package(
    *,
    disease_key: str,
    target_skill_id: str,
    modality: str,
    research_question: str,
    supplied_metadata: list[dict[str, Any]] | None = None,
    supplied_texts: list[dict[str, Any]] | None = None,
    guideline_skill: dict[str, Any] | None = None,
    pubmed_enabled: bool = False,
    pubmed_limit: int = 10,
    pubmed_client: PubMedMetadataClient | None = None,
    human_review_decisions: list[dict[str, Any]] | None = None,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    extraction = ResearchEvidenceExtractor().extract(
        disease_key=disease_key,
        modality=modality,
        research_question=research_question,
        supplied_texts=list(supplied_texts or []),
    )
    merged_metadata = list(supplied_metadata or []) + list(
        extraction["extracted_research_evidence"]
    )
    retrieval = ResearchEvidenceRetriever(pubmed_client=pubmed_client).retrieve(
        disease_key=disease_key,
        modality=modality,
        research_question=research_question,
        supplied_metadata=merged_metadata,
        pubmed_enabled=pubmed_enabled,
        pubmed_limit=pubmed_limit,
    )
    claims = ResearchClaimBuilder().build_claims(
        disease_key=disease_key,
        normalized_research_evidence=list(retrieval["normalized_research_evidence"]),
    )
    proposal = build_research_evidence_proposal(
        disease_key=disease_key,
        target_skill_id=target_skill_id,
        sources=list(retrieval["normalized_research_evidence"]),
        extracted_claims=claims,
        output_dir=None,
    )
    proposal["research_evidence_retrieval"] = retrieval
    proposal["normalized_research_evidence"] = list(
        retrieval["normalized_research_evidence"]
    )
    proposal["claim_builder"] = _claim_builder_artifact(claims)
    proposal["runtime_safety"].update(
        {
            "input_mode": "research_evidence_review_package",
            "paper_search_performed": retrieval["runtime_safety"]["paper_search_performed"],
            "research_metadata_normalized": True,
            "candidate_claims_generated": True,
            "candidate_artifacts_only": True,
            "formal_skill_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "formal_update_allowed": False,
            "diagnosis_allowed": False,
        }
    )
    review_artifact = _build_gateway_review_artifact(
        proposal=proposal,
        guideline_skill=guideline_skill or {},
    )
    human_review_checklist = _build_human_review_checklist(review_artifact)
    promotion_dry_run = _build_research_promotion_dry_run(
        proposal=proposal,
        review_artifact=review_artifact,
    )
    controlled_skill_extension_draft = _build_controlled_skill_extension_draft(
        proposal=proposal,
        review_artifact=review_artifact,
        promotion_dry_run=promotion_dry_run,
    )
    human_review_decision = _build_human_review_decision(
        review_artifact=review_artifact,
        controlled_skill_extension_draft=controlled_skill_extension_draft,
        human_review_decisions=list(human_review_decisions or []),
    )
    controlled_promotion_package = _build_controlled_promotion_package(
        controlled_skill_extension_draft=controlled_skill_extension_draft,
        human_review_decision=human_review_decision,
    )
    package = {
        "schema_version": "research_evidence_review_package.v1",
        "disease_key": disease_key,
        "target_skill_id": target_skill_id,
        "proposal_status": "proposal_only",
        "research_evidence_extraction": extraction,
        "research_evidence_retrieval": retrieval,
        "claim_builder": _claim_builder_artifact(claims),
        "proposal": proposal,
        "gateway_review_artifact": review_artifact,
        "human_review_checklist": human_review_checklist,
        "promotion_dry_run": promotion_dry_run,
        "controlled_skill_extension_draft": controlled_skill_extension_draft,
        "human_review_decision": human_review_decision,
        "controlled_promotion_package": controlled_promotion_package,
        "runtime_safety": {
            "candidate_artifacts_only": True,
            "formal_skill_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "formal_update_allowed": False,
            "diagnosis_allowed": False,
        },
    }
    if output_dir is not None:
        _write_review_package_outputs(package, Path(output_dir))
    return package


def build_research_evidence_proposal_from_request(
    *,
    disease_key: str,
    target_skill_id: str,
    modality: str,
    research_question: str,
    extracted_claims: list[dict[str, Any]],
    supplied_metadata: list[dict[str, Any]] | None = None,
    pubmed_enabled: bool = False,
    pubmed_limit: int = 10,
    pubmed_client: PubMedMetadataClient | None = None,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    retrieval = ResearchEvidenceRetriever(pubmed_client=pubmed_client).retrieve(
        disease_key=disease_key,
        modality=modality,
        research_question=research_question,
        supplied_metadata=supplied_metadata,
        pubmed_enabled=pubmed_enabled,
        pubmed_limit=pubmed_limit,
    )
    payload = build_research_evidence_proposal(
        disease_key=disease_key,
        target_skill_id=target_skill_id,
        sources=list(retrieval["normalized_research_evidence"]),
        extracted_claims=extracted_claims,
        output_dir=None,
    )
    payload["research_evidence_retrieval"] = retrieval
    payload["normalized_research_evidence"] = list(retrieval["normalized_research_evidence"])
    payload["runtime_safety"].update(
        {
            "input_mode": "research_evidence_retrieval",
            "paper_search_performed": retrieval["runtime_safety"]["paper_search_performed"],
            "research_metadata_normalized": True,
            "candidate_artifacts_only": True,
            "formal_skill_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "formal_update_allowed": False,
            "diagnosis_allowed": False,
        }
    )
    if output_dir is not None:
        _write_outputs(payload, Path(output_dir))
    return payload


def normalize_research_metadata(
    metadata: dict[str, Any],
    *,
    disease_key: str,
    requested_modality: str,
    research_question: str,
    source_origin: str,
    index: int,
) -> dict[str, Any]:
    title = _first_present(metadata, "title", "article_title", "name") or "unknown"
    year = _coerce_year(
        _first_present(metadata, "year", "publication_year", "pub_date", "date")
    )
    source_type = _normalize_source_type(metadata, source_origin=source_origin)
    study_design = _normalize_study_design(
        _first_present(metadata, "study_design", "design", "publication_type", "publication_types")
        or title
    )
    evidence_level = _normalize_evidence_level(
        _first_present(metadata, "evidence_level", "level"),
        source_type=source_type,
        study_design=study_design,
    )
    sample_size = _coerce_sample_size(
        _first_present(metadata, "sample_size", "n", "participants", "cohort_size")
    )
    doi = _first_present(metadata, "doi", "DOI")
    pmid = _first_present(metadata, "pmid", "PMID", "uid")
    source_id = _normalize_source_id(
        metadata.get("source_id"),
        pmid=pmid,
        doi=doi,
        index=index,
        source_origin=source_origin,
    )
    population = str(_first_present(metadata, "population", "cohort") or "unknown").strip().lower()
    modality = _normalize_modality(_first_present(metadata, "modality", "imaging_modality") or requested_modality)
    normalized = {
        "source_id": source_id,
        "title": str(title).strip(),
        "year": year,
        "publication_year": year,
        "source_type": source_type,
        "doi": str(doi).strip() if doi else None,
        "DOI": str(doi).strip() if doi else None,
        "sample_size": sample_size,
        "population": population,
        "modality": modality,
        "study_design": study_design,
        "evidence_level": evidence_level,
        "disease_key": disease_key,
        "research_question": research_question,
        "source_origin": source_origin,
    }
    for optional_key in (
        "candidate_claim_type",
        "target_protocol_section",
        "requires_external_validation",
        "limitations",
    ):
        if optional_key in metadata:
            normalized[optional_key] = metadata[optional_key]
    if pmid:
        normalized["pmid"] = str(pmid).strip()
    if metadata.get("url"):
        normalized["url"] = metadata["url"]
    return normalized


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
        "evidence_level": claim.get("evidence_level"),
        "requires_external_validation": bool(
            claim.get("requires_external_validation", True)
        ),
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


def _coerce_year(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"(19|20)\d{2}", str(value))
    if not match:
        return None
    return int(match.group(0))


def _coerce_sample_size(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value).replace(",", ""))
    if not match:
        return 0
    return int(match.group(0))


def _first_present(metadata: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalize_source_id(
    source_id: Any,
    *,
    pmid: Any,
    doi: Any,
    index: int,
    source_origin: str,
) -> str:
    if source_id:
        return str(source_id).strip()
    if pmid:
        return f"pubmed_{str(pmid).strip()}"
    if doi:
        safe_doi = re.sub(r"[^a-zA-Z0-9]+", "_", str(doi).strip()).strip("_").lower()
        return f"doi_{safe_doi}"
    return f"{source_origin}_{index:03d}"


def _normalize_source_type(metadata: dict[str, Any], *, source_origin: str) -> str:
    raw = str(
        _first_present(metadata, "source_type", "publication_type", "publication_types")
        or ""
    ).lower()
    if "preprint" in raw:
        return "preprint"
    if "guideline" in raw:
        return "medical_guideline"
    if "consensus" in raw:
        return "consensus_statement"
    if "regulatory" in raw:
        return "regulatory_document"
    if source_origin == "pubmed" or "journal" in raw or "article" in raw:
        return "peer_reviewed_journal"
    return raw.replace(" ", "_") if raw else "unknown"


def _normalize_modality(value: Any) -> str:
    raw = str(value or "unknown").strip()
    lookup = {
        "mri": "MRI",
        "magnetic resonance imaging": "MRI",
        "ct": "CT",
        "chest ct": "Chest CT",
        "xray": "X-ray",
        "x-ray": "X-ray",
        "chest x-ray": "Chest X-ray",
        "chest xray": "Chest X-ray",
    }
    return lookup.get(raw.lower(), raw)


def _normalize_study_design(value: Any) -> str:
    if isinstance(value, list):
        raw = " ".join(str(item) for item in value)
    else:
        raw = str(value or "")
    text = raw.lower().replace("-", " ").replace("_", " ")
    if "meta" in text or "systematic review" in text:
        return "systematic_review_or_meta_analysis"
    if "multi" in text and "retrospective" in text:
        return "multi_center_retrospective"
    if "single" in text and "retrospective" in text:
        return "single_center_retrospective"
    if "prospective" in text:
        return "prospective_validation"
    if "random" in text:
        return "randomized_trial"
    if "case report" in text:
        return "case_report"
    if "retrospective" in text:
        return "retrospective"
    if "journal article" in text:
        return "journal_article"
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "unknown"


def _normalize_evidence_level(
    value: Any,
    *,
    source_type: str,
    study_design: str,
) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"low", "moderate", "high", "guideline", "consensus"}:
        return raw
    if source_type == "medical_guideline":
        return "guideline"
    if source_type == "consensus_statement":
        return "consensus"
    if source_type == "preprint" or study_design == "case_report":
        return "low"
    if study_design in {"systematic_review_or_meta_analysis", "randomized_trial"}:
        return "high"
    if study_design in {
        "multi_center_retrospective",
        "prospective_validation",
        "retrospective",
        "single_center_retrospective",
    }:
        return "moderate"
    return "unknown"


def _extract_research_evidence_from_text(
    *,
    disease_key: str,
    requested_modality: str,
    research_question: str,
    text_source: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    text = str(text_source.get("text") or "")
    base_metadata = dict(text_source)
    base_metadata.pop("text", None)
    base_metadata.setdefault("source_id", f"text_source_{index:03d}")
    base_metadata.setdefault("modality", _infer_modality_from_text(text, requested_modality))
    base_metadata.setdefault("study_design", _infer_study_design_from_text(text))
    base_metadata.setdefault("sample_size", _infer_sample_size_from_text(text))
    base_metadata.setdefault("population", _infer_population_from_text(text))
    base_metadata.setdefault(
        "candidate_claim_type",
        _infer_candidate_claim_type_from_text(text, research_question),
    )
    base_metadata.setdefault(
        "target_protocol_section",
        _target_section_for_claim({}, base_metadata["candidate_claim_type"]),
    )
    base_metadata.setdefault("limitations", _infer_limitations_from_text(text))
    base_metadata.setdefault(
        "requires_external_validation",
        _infer_requires_external_validation(text),
    )
    normalized = normalize_research_metadata(
        base_metadata,
        disease_key=disease_key,
        requested_modality=requested_modality,
        research_question=research_question,
        source_origin=_source_origin_for_text_kind(base_metadata.get("text_kind")),
        index=index,
    )
    normalized["proposed_features"] = _extract_proposed_features(text)
    normalized["extraction_notes"] = _extraction_notes_for_text(text, normalized)
    normalized["text_kind"] = str(text_source.get("text_kind") or "supplied_text")
    normalized["formal_update_allowed"] = False
    normalized["diagnosis_allowed"] = False
    return normalized


def _infer_modality_from_text(text: str, requested_modality: str) -> str:
    lower = text.lower()
    if "mri" in lower or "magnetic resonance" in lower:
        return "MRI"
    if "chest x-ray" in lower or "chest xray" in lower:
        return "Chest X-ray"
    if "x-ray" in lower or "xray" in lower:
        return "X-ray"
    if "ct" in lower:
        return "CT"
    return requested_modality


def _infer_study_design_from_text(text: str) -> str:
    lower = text.lower()
    if "meta-analysis" in lower or "systematic review" in lower:
        return "systematic_review_or_meta_analysis"
    if "multi-center" in lower or "multicenter" in lower or "multi center" in lower:
        if "retrospective" in lower:
            return "multi_center_retrospective"
    if "single-center" in lower or "single center" in lower:
        if "retrospective" in lower:
            return "single_center_retrospective"
    if "prospective" in lower:
        return "prospective_validation"
    if "retrospective" in lower:
        return "retrospective"
    if "randomized" in lower or "randomised" in lower:
        return "randomized_trial"
    return "unknown"


def _infer_sample_size_from_text(text: str) -> int:
    patterns = [
        r"\bn\s*=\s*(\d[\d,]*)",
        r"\bstudy of\s+(\d[\d,]*)\b",
        r"\b(\d[\d,]*)\s+(?:adult\s+)?(?:patients|participants|subjects|cases)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _coerce_sample_size(match.group(1))
    return 0


def _infer_population_from_text(text: str) -> str:
    lower = text.lower()
    patterns = [
        r"(\badult [a-z -]+ (?:patients|cohort))",
        r"(\bpediatric [a-z -]+ (?:patients|cohort))",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return match.group(1).strip()
    if "adult" in lower:
        return "adult cohort"
    if "pediatric" in lower or "paediatric" in lower:
        return "pediatric cohort"
    return "unknown"


def _infer_candidate_claim_type_from_text(text: str, research_question: str) -> str:
    lower = f"{text} {research_question}".lower()
    if "differential" in lower or "distinguish" in lower:
        return "differential_diagnosis_clue"
    if "risk" in lower or "steroid" in lower or "alcohol" in lower:
        return "clinical_risk_context_clue"
    if "quality gate" in lower or "minimum external validation" in lower:
        return "candidate_quality_gate_rule"
    if (
        "measurement" in lower
        or "score" in lower
        or "ratio" in lower
        or "texture" in lower
        or "radiomics" in lower
    ):
        return "candidate_measurement_protocol"
    return "candidate_skill_extension"


def _infer_limitations_from_text(text: str) -> list[str]:
    lower = text.lower()
    limitations: list[str] = []
    if "retrospective" in lower:
        limitations.append("retrospective design")
    if "single-center" in lower or "single center" in lower:
        limitations.append("single center study")
    if "no guideline" in lower or "not a guideline" in lower:
        limitations.append("not a guideline recommendation")
    return limitations


def _infer_requires_external_validation(text: str) -> bool:
    lower = text.lower()
    if "external validation is required" in lower:
        return True
    if "needs external validation" in lower:
        return True
    if "externally validated" in lower:
        return False
    return True


def _extract_proposed_features(text: str) -> list[str]:
    lower = text.lower()
    features: list[str] = []
    known_features = [
        "texture disorder score",
        "necrotic area ratio",
        "marrow edema",
        "radiomics feature",
        "collapse measurement",
    ]
    for feature in known_features:
        if feature in lower:
            features.append(feature)
    return features


def _extraction_notes_for_text(text: str, evidence: dict[str, Any]) -> list[str]:
    notes = [
        f"text_kind={evidence.get('text_kind', 'supplied_text')}",
        f"candidate_claim_type={evidence.get('candidate_claim_type')}",
    ]
    if evidence.get("candidate_claim_type") == "differential_diagnosis_clue":
        notes.append("differential diagnosis clue")
    if "abstract" in str(evidence.get("text_kind") or ""):
        notes.append("abstract text extraction")
    return notes


def _source_origin_for_text_kind(text_kind: Any) -> str:
    if str(text_kind or "").strip().lower() == "pdf_text":
        return "supplied_pdf_text"
    if str(text_kind or "").strip().lower() == "abstract":
        return "supplied_abstract_text"
    return "supplied_text"


def _normalize_claim_type(value: Any) -> str:
    raw = str(value or "").strip()
    if raw in ALLOWED_CANDIDATE_TYPES and raw != "research_evidence_proposal":
        return raw
    return "candidate_skill_extension"


def _build_claim_id(disease_key: str, evidence: dict[str, Any], index: int) -> str:
    source_id = str(evidence.get("source_id") or f"source_{index:03d}")
    safe_source = re.sub(r"[^a-zA-Z0-9]+", "_", source_id).strip("_").lower()
    return f"{disease_key}_{safe_source}_claim_{index:03d}"


def _build_claim_summary(evidence: dict[str, Any], claim_type: str) -> str:
    title = str(evidence.get("title") or "Untitled research evidence").strip()
    evidence_level = evidence.get("evidence_level") or "unknown"
    modality = evidence.get("modality") or "unknown modality"
    return (
        f"{title} is proposed as {claim_type} for {modality}; "
        f"evidence_level={evidence_level}. This is candidate-only research evidence."
    )


def _target_section_for_claim(evidence: dict[str, Any], claim_type: str) -> str:
    explicit = evidence.get("target_protocol_section")
    if explicit:
        return str(explicit)
    defaults = {
        "candidate_measurement_protocol": (
            "quantitative_evidence_protocol.measurement_evidence"
        ),
        "candidate_quality_gate_rule": "quality_gate_protocol.research_evidence_gate",
        "differential_diagnosis_clue": "differential_diagnosis_protocol",
        "clinical_risk_context_clue": "clinical_context_bundle.risk_factors",
        "candidate_skill_extension": "integrated_reasoning_protocol",
    }
    return defaults.get(claim_type, "integrated_reasoning_protocol")


def _claim_limitations(evidence: dict[str, Any]) -> list[str]:
    limitations = list(evidence.get("limitations") or [])
    if evidence.get("source_type") != "medical_guideline":
        limitations.append("not a formal guideline recommendation")
    if evidence.get("requires_external_validation", True):
        limitations.append("requires external validation before promotion")
    return _dedupe_strings(limitations)


def _claim_builder_artifact(claims: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "research_claim_builder.v1",
        "claim_count": len(claims),
        "supported_claim_types": [
            "candidate_skill_extension",
            "candidate_measurement_protocol",
            "candidate_quality_gate_rule",
            "differential_diagnosis_clue",
            "clinical_risk_context_clue",
        ],
        "candidate_claims": claims,
        "runtime_safety": {
            "proposal_only": True,
            "formal_update_allowed": False,
            "diagnosis_allowed": False,
        },
    }


def _build_gateway_review_artifact(
    *,
    proposal: dict[str, Any],
    guideline_skill: dict[str, Any],
) -> dict[str, Any]:
    review_items = [
        _build_review_item(candidate, guideline_skill)
        for candidate in proposal.get("candidate_extensions") or []
    ]
    return {
        "schema_version": "research_gateway_review_artifact.v1",
        "review_status": "pending_human_review",
        "review_items": review_items,
        "summary": {
            "claim_count": len(review_items),
            "guideline_conflict_count": sum(
                1
                for item in review_items
                if item["guideline_conflict_status"] == "human_review_required"
            ),
            "blocked_count": sum(
                1 for item in review_items if item["quality_gate_decision"] == "blocked"
            ),
        },
        "runtime_safety": {
            "research_mode_only": True,
            "proposal_only": True,
            "formal_skill_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "formal_update_allowed": False,
            "diagnosis_allowed": False,
        },
    }


def _build_review_item(
    candidate: dict[str, Any],
    guideline_skill: dict[str, Any],
) -> dict[str, Any]:
    conflict_reasons = _guideline_conflict_reasons(candidate, guideline_skill)
    quality_gate = candidate.get("quality_gate") or {}
    exploratory_only = bool(
        conflict_reasons
        or candidate.get("evidence_level") in {"low", "unknown"}
        or candidate.get("requires_external_validation", True)
        or quality_gate.get("decision") == "blocked"
    )
    return {
        "item_id": candidate.get("item_id"),
        "candidate_type": candidate.get("candidate_type"),
        "source_id": candidate.get("source_id"),
        "target_protocol_section": candidate.get("target_protocol_section"),
        "quality_gate_decision": quality_gate.get("decision"),
        "guideline_conflict_status": (
            "human_review_required" if conflict_reasons else "no_direct_conflict_detected"
        ),
        "conflict_reasons": conflict_reasons,
        "applicability_review_required": True,
        "exploratory_only": exploratory_only,
        "human_review_required": True,
        "research_mode_only": True,
        "diagnosis_report_forbidden": True,
        "formal_update_allowed": False,
        "diagnosis_allowed": False,
    }


def _guideline_conflict_reasons(
    candidate: dict[str, Any],
    guideline_skill: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    supported_modalities = guideline_skill.get("supported_modalities") or []
    if supported_modalities and not _casefold_contains(
        supported_modalities,
        candidate.get("modality"),
    ):
        reasons.append("modality_not_in_guideline_skill")
    sections = guideline_skill.get("evidence_protocol_sections") or []
    if sections and not _casefold_contains(
        sections,
        candidate.get("target_protocol_section"),
    ):
        reasons.append("target_protocol_section_not_in_guideline_skill")
    return reasons


def _casefold_contains(values: list[Any], needle: Any) -> bool:
    normalized_values = {str(value or "").strip().lower() for value in values}
    return str(needle or "").strip().lower() in normalized_values


def _build_human_review_checklist(
    review_artifact: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "research_human_review_checklist.v1",
        "review_status": "pending_human_review",
        "required_review_steps": [
            "source_quality_review",
            "guideline_conflict_review",
            "applicability_review",
            "external_validation_review",
            "diagnosis_boundary_review",
        ],
        "items": [
            {
                "item_id": item.get("item_id"),
                "candidate_type": item.get("candidate_type"),
                "quality_gate_decision": item.get("quality_gate_decision"),
                "guideline_conflict_status": item.get("guideline_conflict_status"),
                "review_status": "pending_human_review",
                "research_mode_only": True,
                "diagnosis_report_forbidden": True,
            }
            for item in review_artifact.get("review_items") or []
        ],
        "formal_update_allowed": False,
        "diagnosis_allowed": False,
    }


def _build_research_promotion_dry_run(
    *,
    proposal: dict[str, Any],
    review_artifact: dict[str, Any],
) -> dict[str, Any]:
    promotion_status = (
        "blocked_by_quality_gate"
        if proposal.get("quality_gate", {}).get("promotion_decision", {}).get("status")
        == "blocked"
        else "proposal_only_pending_human_approval"
    )
    return {
        "schema_version": "research_promotion_dry_run.v1",
        "promotion_status": promotion_status,
        "suggested_section_updates": [
            {
                "item_id": item.get("item_id"),
                "candidate_type": item.get("candidate_type"),
                "target_protocol_section": item.get("target_protocol_section"),
                "suggested_action_if_human_approved": (
                    "draft_limited_research_mode_skill_extension"
                ),
                "guideline_conflict_status": item.get("guideline_conflict_status"),
            }
            for item in review_artifact.get("review_items") or []
        ],
        "formal_skill_updated": False,
        "formal_guideline_updated": False,
        "diagnosis_report_updated": False,
        "formal_update_allowed": False,
        "diagnosis_allowed": False,
    }


def _build_controlled_skill_extension_draft(
    *,
    proposal: dict[str, Any],
    review_artifact: dict[str, Any],
    promotion_dry_run: dict[str, Any],
) -> dict[str, Any]:
    candidate_by_item_id = {
        str(candidate.get("item_id")): candidate
        for candidate in proposal.get("candidate_extensions") or []
    }
    proposed_updates = [
        _build_controlled_section_update(
            review_item=item,
            candidate=candidate_by_item_id.get(str(item.get("item_id")), {}),
        )
        for item in review_artifact.get("review_items") or []
    ]
    blocked_count = sum(
        1 for item in proposed_updates if item["quality_gate_decision"] == "blocked"
    )
    conflict_count = sum(
        1
        for item in proposed_updates
        if item["guideline_conflict_status"] == "human_review_required"
    )
    draft_status = "blocked_by_gateway" if blocked_count else "pending_human_review"
    return {
        "schema_version": "controlled_skill_extension_draft.v1",
        "draft_status": draft_status,
        "source_proposal_schema_version": proposal.get("schema_version"),
        "source_proposal_status": proposal.get("proposal_status"),
        "target_skill_id": proposal.get("target_skill_id"),
        "disease_key": proposal.get("disease_key"),
        "proposed_section_updates": proposed_updates,
        "guideline_conflict_summary": {
            "blocked_count": blocked_count,
            "guideline_conflict_count": conflict_count,
            "human_review_required_count": sum(
                1 for item in proposed_updates if item["human_review_required"]
            ),
        },
        "promotion_dry_run_diff": {
            "source_promotion_status": promotion_dry_run.get("promotion_status"),
            "proposed_section_updates": [
                {
                    "item_id": item.get("item_id"),
                    "target_protocol_section": item.get("target_protocol_section"),
                    "suggested_section_action": item.get("suggested_section_action"),
                    "evidence_use_label": item.get("evidence_use_label"),
                }
                for item in proposed_updates
            ],
            "formal_skill_file_changed": False,
            "diagnosis_flow_changed": False,
        },
        "human_review_required": True,
        "runtime_safety": {
            "controlled_draft_only": True,
            "research_mode_only": True,
            "formal_skill_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "formal_update_allowed": False,
            "diagnosis_allowed": False,
        },
    }


def _build_human_review_decision(
    *,
    review_artifact: dict[str, Any],
    controlled_skill_extension_draft: dict[str, Any],
    human_review_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    supplied_by_item_id = {
        str(item.get("item_id") or ""): item
        for item in human_review_decisions
        if item.get("item_id")
    }
    review_by_item_id = {
        str(item.get("item_id") or ""): item
        for item in review_artifact.get("review_items") or []
    }
    items = [
        _build_human_review_decision_item(
            update=update,
            review_item=review_by_item_id.get(str(update.get("item_id")), {}),
            supplied_decision=supplied_by_item_id.get(str(update.get("item_id")), {}),
        )
        for update in controlled_skill_extension_draft.get("proposed_section_updates") or []
    ]
    decisions = {item["review_decision"] for item in items}
    approved_count = sum(1 for item in items if item["review_decision"] == "approved")
    pending_count = sum(
        1 for item in items if item["review_decision"] == "pending_human_review"
    )
    if pending_count:
        decision_status = "pending_human_review"
    elif approved_count and decisions <= {"approved"}:
        decision_status = "approved"
    elif approved_count:
        decision_status = "partially_approved"
    else:
        decision_status = "not_approved"
    return {
        "schema_version": "research_human_review_decision.v1",
        "decision_status": decision_status,
        "source_draft_schema_version": controlled_skill_extension_draft.get(
            "schema_version"
        ),
        "target_skill_id": controlled_skill_extension_draft.get("target_skill_id"),
        "review_item_count": len(items),
        "items": items,
        "runtime_safety": {
            "human_decision_only": True,
            "formal_skill_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "formal_update_allowed": False,
            "diagnosis_allowed": False,
        },
    }


def _build_human_review_decision_item(
    *,
    update: dict[str, Any],
    review_item: dict[str, Any],
    supplied_decision: dict[str, Any],
) -> dict[str, Any]:
    review_decision = _normalize_human_review_decision(
        supplied_decision.get("decision")
        or supplied_decision.get("review_decision")
    )
    promotion_allowed = bool(update.get("promotion_allowed_after_review"))
    if review_decision == "approved" and not promotion_allowed:
        review_decision = "needs_revision"
    return {
        "item_id": update.get("item_id"),
        "candidate_type": update.get("candidate_type"),
        "source_id": update.get("source_id"),
        "target_protocol_section": update.get("target_protocol_section"),
        "quality_gate_decision": update.get("quality_gate_decision"),
        "guideline_conflict_status": update.get("guideline_conflict_status"),
        "conflict_reasons": list(update.get("conflict_reasons") or []),
        "evidence_level": update.get("evidence_level"),
        "evidence_use_label": update.get("evidence_use_label"),
        "review_decision": review_decision,
        "reviewer_id": supplied_decision.get("reviewer_id"),
        "reviewed_at": supplied_decision.get("reviewed_at"),
        "review_notes": supplied_decision.get("notes")
        or supplied_decision.get("review_notes"),
        "promotion_allowed_after_review": promotion_allowed,
        "diagnosis_report_forbidden": bool(
            review_item.get("diagnosis_report_forbidden", True)
        ),
        "formal_update_allowed": False,
        "diagnosis_allowed": False,
    }


def _normalize_human_review_decision(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"approved", "rejected", "needs_revision"}:
        return raw
    return "pending_human_review"


def _build_controlled_promotion_package(
    *,
    controlled_skill_extension_draft: dict[str, Any],
    human_review_decision: dict[str, Any],
) -> dict[str, Any]:
    update_by_item_id = {
        str(update.get("item_id") or ""): update
        for update in controlled_skill_extension_draft.get("proposed_section_updates")
        or []
    }
    approved_updates = []
    rejected_or_revision_items = []
    for decision_item in human_review_decision.get("items") or []:
        update = update_by_item_id.get(str(decision_item.get("item_id")), {})
        if (
            decision_item.get("review_decision") == "approved"
            and decision_item.get("promotion_allowed_after_review") is True
        ):
            approved_updates.append(
                _build_approved_controlled_update(
                    update=update,
                    decision_item=decision_item,
                )
            )
        elif decision_item.get("review_decision") != "pending_human_review":
            rejected_or_revision_items.append(
                _build_rejected_or_revision_item(decision_item)
            )
    patch_preview = _build_formal_skill_patch_preview(
        target_skill_id=controlled_skill_extension_draft.get("target_skill_id"),
        approved_updates=approved_updates,
    )
    return {
        "schema_version": "controlled_promotion_package.v1",
        "package_status": (
            "ready_for_controlled_promotion_review"
            if approved_updates
            else "not_ready_for_promotion"
        ),
        "source_draft_schema_version": controlled_skill_extension_draft.get(
            "schema_version"
        ),
        "source_review_decision_schema_version": human_review_decision.get(
            "schema_version"
        ),
        "target_skill_id": controlled_skill_extension_draft.get("target_skill_id"),
        "approved_updates": approved_updates,
        "rejected_or_revision_items": rejected_or_revision_items,
        "formal_skill_patch_preview": patch_preview,
        "rollback_notes": _build_controlled_promotion_rollback_notes(
            target_skill_id=controlled_skill_extension_draft.get("target_skill_id"),
            approved_updates=approved_updates,
        ),
        "audit_log": _build_controlled_promotion_audit_log(
            human_review_decision=human_review_decision,
            approved_updates=approved_updates,
            rejected_or_revision_items=rejected_or_revision_items,
        ),
        "runtime_safety": {
            "controlled_package_only": True,
            "formal_patch_preview_only": True,
            "formal_skill_updated": False,
            "formal_guideline_updated": False,
            "diagnosis_report_updated": False,
            "formal_update_allowed": False,
            "diagnosis_allowed": False,
        },
    }


def _build_approved_controlled_update(
    *,
    update: dict[str, Any],
    decision_item: dict[str, Any],
) -> dict[str, Any]:
    return {
        "item_id": update.get("item_id"),
        "candidate_type": update.get("candidate_type"),
        "source_id": update.get("source_id"),
        "target_protocol_section": update.get("target_protocol_section"),
        "suggested_section_action": update.get("suggested_section_action"),
        "evidence_level": update.get("evidence_level"),
        "evidence_use_label": update.get("evidence_use_label"),
        "review_decision": decision_item.get("review_decision"),
        "reviewer_id": decision_item.get("reviewer_id"),
        "review_notes": decision_item.get("review_notes"),
        "formal_patch_applied": False,
        "diagnosis_flow_changed": False,
        "formal_update_allowed": False,
        "diagnosis_allowed": False,
    }


def _build_rejected_or_revision_item(decision_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": decision_item.get("item_id"),
        "candidate_type": decision_item.get("candidate_type"),
        "source_id": decision_item.get("source_id"),
        "target_protocol_section": decision_item.get("target_protocol_section"),
        "review_decision": decision_item.get("review_decision"),
        "reviewer_id": decision_item.get("reviewer_id"),
        "review_notes": decision_item.get("review_notes"),
        "reason": "human_review_did_not_approve_promotion",
        "formal_update_allowed": False,
        "diagnosis_allowed": False,
    }


def _build_formal_skill_patch_preview(
    *,
    target_skill_id: Any,
    approved_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    if not approved_updates:
        return {
            "patch_status": "no_approved_updates",
            "target_skill_id": target_skill_id,
            "preview_sections": [],
            "patch_preview_text": "",
            "formal_skill_file_changed": False,
            "patch_applied": False,
        }
    preview_sections = [
        {
            "item_id": update.get("item_id"),
            "target_protocol_section": update.get("target_protocol_section"),
            "candidate_type": update.get("candidate_type"),
            "evidence_use_label": update.get("evidence_use_label"),
            "source_id": update.get("source_id"),
            "proposed_addition": (
                f"Add {update.get('evidence_use_label')} research-mode "
                f"{update.get('candidate_type')} from {update.get('source_id')} "
                f"to {update.get('target_protocol_section')}."
            ),
        }
        for update in approved_updates
    ]
    return {
        "patch_status": "preview_only_not_applied",
        "target_skill_id": target_skill_id,
        "preview_sections": preview_sections,
        "patch_preview_text": "\n".join(
            f"+ [{section['evidence_use_label']}] {section['proposed_addition']}"
            for section in preview_sections
        ),
        "formal_skill_file_changed": False,
        "patch_applied": False,
    }


def _build_controlled_promotion_rollback_notes(
    *,
    target_skill_id: Any,
    approved_updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not approved_updates:
        return [
            {
                "status": "no_approved_updates",
                "note": "No rollback action is needed because no formal patch is previewed.",
            }
        ]
    return [
        {
            "item_id": update.get("item_id"),
            "target_skill_id": target_skill_id,
            "rollback_action": "remove_previewed_research_mode_extension_if_promoted_later",
            "formal_patch_applied": False,
        }
        for update in approved_updates
    ]


def _build_controlled_promotion_audit_log(
    *,
    human_review_decision: dict[str, Any],
    approved_updates: list[dict[str, Any]],
    rejected_or_revision_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {
            "event": f"human_review_decision_{human_review_decision.get('decision_status')}",
            "schema_version": human_review_decision.get("schema_version"),
            "formal_skill_updated": False,
            "diagnosis_report_updated": False,
        }
    ]
    for update in approved_updates:
        events.append(
            {
                "event": "human_review_item_approved_for_controlled_package",
                "item_id": update.get("item_id"),
                "source_id": update.get("source_id"),
                "formal_patch_applied": False,
            }
        )
    for item in rejected_or_revision_items:
        events.append(
            {
                "event": "human_review_item_not_approved",
                "item_id": item.get("item_id"),
                "review_decision": item.get("review_decision"),
                "formal_patch_applied": False,
            }
        )
    return events


def _build_controlled_section_update(
    *,
    review_item: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    quality_gate_decision = str(review_item.get("quality_gate_decision") or "")
    conflict_status = str(review_item.get("guideline_conflict_status") or "")
    conflict_reasons = list(review_item.get("conflict_reasons") or [])
    evidence_level = str(candidate.get("evidence_level") or "unknown")
    evidence_use_label = _controlled_evidence_use_label(
        quality_gate_decision=quality_gate_decision,
        conflict_status=conflict_status,
        evidence_level=evidence_level,
    )
    promotion_allowed_after_review = (
        quality_gate_decision != "blocked"
        and conflict_status != "human_review_required"
    )
    return {
        "item_id": review_item.get("item_id"),
        "candidate_type": review_item.get("candidate_type"),
        "source_id": review_item.get("source_id"),
        "target_protocol_section": review_item.get("target_protocol_section"),
        "suggested_section_action": _controlled_suggested_section_action(
            candidate_type=str(review_item.get("candidate_type") or ""),
            evidence_use_label=evidence_use_label,
            promotion_allowed_after_review=promotion_allowed_after_review,
        ),
        "evidence_level": evidence_level,
        "evidence_use_label": evidence_use_label,
        "quality_gate_decision": quality_gate_decision,
        "guideline_conflict_status": conflict_status,
        "conflict_reasons": conflict_reasons,
        "human_review_required": True,
        "research_mode_only": True,
        "exploratory_only": bool(review_item.get("exploratory_only")),
        "promotion_allowed_after_review": promotion_allowed_after_review,
        "formal_update_allowed": False,
        "diagnosis_allowed": False,
    }


def _controlled_evidence_use_label(
    *,
    quality_gate_decision: str,
    conflict_status: str,
    evidence_level: str,
) -> str:
    if quality_gate_decision == "blocked":
        return "research_only"
    if conflict_status == "human_review_required":
        return "exploratory"
    if evidence_level in {"moderate", "high", "consensus"}:
        return "supplemental"
    return "exploratory"


def _controlled_suggested_section_action(
    *,
    candidate_type: str,
    evidence_use_label: str,
    promotion_allowed_after_review: bool,
) -> str:
    if not promotion_allowed_after_review:
        if evidence_use_label == "research_only":
            return "do_not_promote_blocked_item"
        return "keep_as_exploratory_research_extension"
    if candidate_type == "candidate_measurement_protocol":
        return "add_research_mode_supplemental_measurement"
    if candidate_type == "differential_diagnosis_clue":
        return "add_research_mode_differential_clue"
    if candidate_type == "clinical_risk_context_clue":
        return "add_research_mode_clinical_context_clue"
    if candidate_type == "candidate_quality_gate_rule":
        return "add_research_mode_quality_gate_note"
    return "add_research_mode_supplemental_skill_extension"


def _dedupe_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _build_pubmed_query(disease_key: str, modality: str, research_question: str) -> str:
    parts = [
        disease_key,
        disease_key.replace("_", " "),
        modality,
        research_question,
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


def _default_pubmed_metadata_client(query: str, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": str(limit),
        }
    )
    search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{params}"
    with urllib.request.urlopen(search_url, timeout=20) as response:
        search_payload = json.loads(response.read().decode("utf-8"))
    pmids = search_payload.get("esearchresult", {}).get("idlist", [])
    if not pmids:
        return []
    summary_params = urllib.parse.urlencode(
        {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "json",
        }
    )
    summary_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{summary_params}"
    with urllib.request.urlopen(summary_url, timeout=20) as response:
        summary_payload = json.loads(response.read().decode("utf-8"))
    result = summary_payload.get("result", {})
    records: list[dict[str, Any]] = []
    for pmid in pmids:
        item = result.get(str(pmid), {})
        article_ids = item.get("articleids") or []
        doi = None
        for article_id in article_ids:
            if article_id.get("idtype") == "doi":
                doi = article_id.get("value")
                break
        records.append(
            {
                "pmid": pmid,
                "article_title": item.get("title"),
                "pub_date": item.get("pubdate"),
                "source_type": "peer_reviewed_journal",
                "doi": doi,
                "publication_types": item.get("pubtype") or [],
            }
        )
    return records


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


def _write_review_package_outputs(package: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    proposal = package["proposal"]
    _write_outputs(proposal, output)
    review_path = output / "research_gateway_review_artifact.json"
    extraction_path = output / "research_evidence_extraction.json"
    checklist_path = output / "human_review_checklist.json"
    checklist_md_path = output / "human_review_checklist.md"
    dry_run_path = output / "research_promotion_dry_run.json"
    draft_path = output / "controlled_skill_extension_draft.json"
    draft_md_path = output / "controlled_skill_extension_draft.md"
    review_decision_path = output / "research_human_review_decision.json"
    promotion_package_path = output / "controlled_promotion_package.json"
    promotion_package_md_path = output / "controlled_promotion_package.md"
    package_path = output / "research_evidence_review_package.json"
    package["output_paths"] = {
        "review_package_json_path": str(package_path),
        "proposal_json_path": str(output / "research_evidence_proposal.json"),
        "quality_gate_json_path": str(output / "research_evidence_quality_gate.json"),
        "extraction_json_path": str(extraction_path),
        "gateway_review_json_path": str(review_path),
        "human_review_checklist_json_path": str(checklist_path),
        "human_review_checklist_md_path": str(checklist_md_path),
        "promotion_dry_run_json_path": str(dry_run_path),
        "controlled_skill_extension_draft_json_path": str(draft_path),
        "controlled_skill_extension_draft_md_path": str(draft_md_path),
        "human_review_decision_json_path": str(review_decision_path),
        "controlled_promotion_package_json_path": str(promotion_package_path),
        "controlled_promotion_package_md_path": str(promotion_package_md_path),
    }
    review_path.write_text(
        json.dumps(package["gateway_review_artifact"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    extraction_path.write_text(
        json.dumps(package["research_evidence_extraction"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    checklist_path.write_text(
        json.dumps(package["human_review_checklist"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    checklist_md_path.write_text(
        _render_human_review_checklist_markdown(package["human_review_checklist"]),
        encoding="utf-8",
    )
    dry_run_path.write_text(
        json.dumps(package["promotion_dry_run"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    draft_path.write_text(
        json.dumps(
            package["controlled_skill_extension_draft"],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    draft_md_path.write_text(
        _render_controlled_skill_extension_draft_markdown(
            package["controlled_skill_extension_draft"]
        ),
        encoding="utf-8",
    )
    review_decision_path.write_text(
        json.dumps(package["human_review_decision"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    promotion_package_path.write_text(
        json.dumps(
            package["controlled_promotion_package"],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    promotion_package_md_path.write_text(
        _render_controlled_promotion_package_markdown(
            package["controlled_promotion_package"]
        ),
        encoding="utf-8",
    )
    package_path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _render_human_review_checklist_markdown(checklist: dict[str, Any]) -> str:
    lines = [
        "# Research Evidence Human Review Checklist",
        "",
        f"- `review_status`: `{checklist.get('review_status')}`",
        "- `formal_update_allowed=false`",
        "- `diagnosis_allowed=false`",
        "",
        "## Required Review Steps",
        "",
    ]
    for step in checklist.get("required_review_steps") or []:
        lines.append(f"- [ ] `{step}`")
    lines.extend(
        [
            "",
            "## Candidate Items",
            "",
            "| item_id | type | quality_gate | guideline_conflict | review_status |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in checklist.get("items") or []:
        lines.append(
            "| {item_id} | {candidate_type} | {quality_gate_decision} | "
            "{guideline_conflict_status} | {review_status} |".format(**item)
        )
    lines.append("")
    return "\n".join(lines)


def _render_controlled_skill_extension_draft_markdown(draft: dict[str, Any]) -> str:
    safety = draft.get("runtime_safety") or {}
    lines = [
        "# Controlled Skill Extension Draft",
        "",
        "This is a proposal-only draft for human review.",
        "",
        f"- `draft_status`: `{draft.get('draft_status')}`",
        f"- `target_skill_id`: `{draft.get('target_skill_id')}`",
        "- `formal_update_allowed=false`",
        f"- `diagnosis_allowed={str(safety.get('diagnosis_allowed')).lower()}`",
        "- `formal_skill_updated=false`",
        "- `diagnosis_report_updated=false`",
        "",
        "## Proposed Section Updates",
        "",
        "| item_id | type | source | section | evidence | use | conflict | action |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in draft.get("proposed_section_updates") or []:
        lines.append(
            "| {item_id} | {candidate_type} | {source_id} | {target_protocol_section} | "
            "{evidence_level} | {evidence_use_label} | {guideline_conflict_status} | "
            "{suggested_section_action} |".format(**item)
        )
    lines.append("")
    return "\n".join(lines)


def _render_controlled_promotion_package_markdown(package: dict[str, Any]) -> str:
    safety = package.get("runtime_safety") or {}
    patch_preview = package.get("formal_skill_patch_preview") or {}
    lines = [
        "# Controlled Promotion Package",
        "",
        "This package is a human-reviewed preview. It does not modify formal skills.",
        "",
        f"- `package_status`: `{package.get('package_status')}`",
        f"- `target_skill_id`: `{package.get('target_skill_id')}`",
        f"- `patch_status`: `{patch_preview.get('patch_status')}`",
        "- `formal_update_allowed=false`",
        f"- `diagnosis_allowed={str(safety.get('diagnosis_allowed')).lower()}`",
        "- `formal_skill_updated=false`",
        "- `diagnosis_report_updated=false`",
        "",
        "## Approved Updates",
        "",
        "| item_id | type | source | section | evidence_use | patch_applied |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in package.get("approved_updates") or []:
        lines.append(
            "| {item_id} | {candidate_type} | {source_id} | "
            "{target_protocol_section} | {evidence_use_label} | "
            "{formal_patch_applied} |".format(**item)
        )
    lines.extend(
        [
            "",
            "## Rejected Or Revision Items",
            "",
            "| item_id | type | source | decision |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in package.get("rejected_or_revision_items") or []:
        lines.append(
            "| {item_id} | {candidate_type} | {source_id} | {review_decision} |".format(
                **item
            )
        )
    lines.append("")
    return "\n".join(lines)


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
    parser.add_argument("--enable-pubmed", action="store_true")
    parser.add_argument("--pubmed-limit", type=int, default=10)
    args = parser.parse_args()
    request = json.loads(args.input_json.read_text(encoding="utf-8"))
    if request.get("build_review_package"):
        payload = build_research_evidence_review_package(
            disease_key=request["disease_key"],
            target_skill_id=request["target_skill_id"],
            modality=request.get("modality") or _infer_request_modality(request),
            research_question=request.get("research_question") or "",
            supplied_metadata=list(
                request.get("supplied_metadata")
                or request.get("sources")
                or []
            ),
            supplied_texts=list(request.get("supplied_texts") or []),
            guideline_skill=dict(request.get("guideline_skill") or {}),
            pubmed_enabled=args.enable_pubmed,
            pubmed_limit=args.pubmed_limit,
            human_review_decisions=list(request.get("human_review_decisions") or []),
            output_dir=args.output_dir,
        )
    elif (
        request.get("modality")
        or request.get("research_question")
        or request.get("supplied_metadata")
        or args.enable_pubmed
    ):
        payload = build_research_evidence_proposal_from_request(
            disease_key=request["disease_key"],
            target_skill_id=request["target_skill_id"],
            modality=request.get("modality") or _infer_request_modality(request),
            research_question=request.get("research_question") or "",
            supplied_metadata=list(
                request.get("supplied_metadata")
                or request.get("sources")
                or []
            ),
            extracted_claims=list(request.get("extracted_claims") or []),
            pubmed_enabled=args.enable_pubmed,
            pubmed_limit=args.pubmed_limit,
            output_dir=args.output_dir,
        )
    else:
        payload = build_research_evidence_proposal(
            disease_key=request["disease_key"],
            target_skill_id=request["target_skill_id"],
            sources=list(request.get("sources") or []),
            extracted_claims=list(request.get("extracted_claims") or []),
            output_dir=args.output_dir,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _infer_request_modality(request: dict[str, Any]) -> str:
    for collection_key in ("extracted_claims", "supplied_metadata", "sources"):
        for item in request.get(collection_key) or []:
            if item.get("modality"):
                return str(item["modality"])
    return "unknown"


if __name__ == "__main__":
    main()
