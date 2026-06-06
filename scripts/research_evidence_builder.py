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
        "sample_size": sample_size,
        "population": population,
        "modality": modality,
        "study_design": study_design,
        "evidence_level": evidence_level,
        "disease_key": disease_key,
        "research_question": research_question,
        "source_origin": source_origin,
    }
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
    if (
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
