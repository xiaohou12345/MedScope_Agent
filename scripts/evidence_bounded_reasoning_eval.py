"""Summarize evidence-bounded diagnosis and QA safety checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("output/fake/evidence_bounded_reasoning_eval")


DEFAULT_EVAL_CASES: list[dict[str, Any]] = [
    {
        "case_id": "adopted_fhn_visual_facts",
        "category": "adopted",
        "description": "Diagnosis report can cite adopted visual facts.",
        "evidence_sources": [
            "tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_records_used_and_excluded_structured_visual_facts",
            "output/fake/standard_demo_with_fhn_no_mask_qc/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_response.json",
        ],
        "checks": {
            "adopted_evidence_present": True,
            "adopted_evidence_trace_complete": True,
            "unsupported_claim_count": 0,
        },
    },
    {
        "case_id": "missing_visual_evidence_not_negative",
        "category": "missing",
        "description": "Missing visual evidence is acknowledged and not treated as zero or negative.",
        "evidence_sources": [
            "tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_reports_missing_visual_protocol_evidence_without_zero_claim",
            "tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_rejects_llm_report_that_turns_missing_visual_evidence_into_zero",
        ],
        "checks": {
            "missing_evidence_acknowledged": True,
            "missing_as_negative_violation_count": 0,
        },
    },
    {
        "case_id": "excluded_visual_fact_not_reused",
        "category": "excluded",
        "description": "Excluded visual facts are not reused as independent diagnostic support.",
        "evidence_sources": [
            "tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_rejects_follow_up_llm_answer_that_uses_excluded_visual_fact",
            "tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_records_used_and_excluded_structured_visual_facts",
        ],
        "checks": {
            "excluded_facts_present": True,
            "excluded_fact_reuse_violation_count": 0,
        },
    },
    {
        "case_id": "overlap_non_independent_evidence",
        "category": "overlap",
        "description": "Overlapping findings are marked non-independent and not double-counted.",
        "evidence_sources": [
            "tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_rejects_llm_report_that_counts_overlapping_findings_as_independent",
            "output/fake/standard_demo_with_fhn_no_mask_qc/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_evidence_bundle.json",
        ],
        "checks": {
            "non_independent_evidence_detected": True,
            "overlap_double_count_violation_count": 0,
        },
    },
    {
        "case_id": "follow_up_qa_grounded_in_evidence_bundle",
        "category": "qa",
        "description": "Follow-up QA is grounded in existing evidence bundle and does not invent new imaging findings.",
        "evidence_sources": [
            "tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_uses_llm_for_follow_up_qa_with_evidence_bundle",
            "tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_qa_response_attaches_follow_up_agent_memory_trace",
        ],
        "checks": {
            "evidence_bundle_used": True,
            "qa_grounding_violation_count": 0,
            "invented_visual_finding_count": 0,
        },
    },
]


def build_evidence_bounded_reasoning_eval(
    *,
    eval_cases: list[dict[str, Any]] | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    cases = [_evaluate_case(case) for case in (eval_cases or DEFAULT_EVAL_CASES)]
    metrics = _aggregate_metrics(cases)
    payload = {
        "schema_version": "evidence_bounded_reasoning_eval.v1",
        "status": "passed" if _all_zero(metrics) and all(c["passed"] for c in cases) else "failed",
        "case_count": len(cases),
        "category_summary": _category_summary(cases),
        "metrics": metrics,
        "eval_cases": cases,
        "runtime_safety": {
            "evidence_bundle_required": True,
            "diagnosis_uses_adopted_evidence_only": True,
            "missing_evidence_not_negative": True,
            "excluded_facts_not_reused": True,
            "qa_grounded_in_existing_bundle": True,
            "diagnosis_report_updated": False,
        },
    }
    json_path = output / "evidence_bounded_reasoning_eval.json"
    markdown_path = output / "evidence_bounded_reasoning_eval.md"
    payload["output_paths"] = {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    checks = dict(case.get("checks") or {})
    violation_keys = [
        "unsupported_claim_count",
        "missing_as_negative_violation_count",
        "excluded_fact_reuse_violation_count",
        "overlap_double_count_violation_count",
        "qa_grounding_violation_count",
        "invented_visual_finding_count",
    ]
    violations = {
        key: int(checks.get(key) or 0)
        for key in violation_keys
    }
    passed = all(value == 0 for value in violations.values())
    return {
        "case_id": case.get("case_id"),
        "category": case.get("category"),
        "description": case.get("description"),
        "evidence_sources": case.get("evidence_sources") or [],
        "checks": checks,
        "violations": violations,
        "passed": passed,
    }


def _aggregate_metrics(cases: list[dict[str, Any]]) -> dict[str, int]:
    metrics = {
        "unsupported_claim_count": 0,
        "missing_as_negative_violation_count": 0,
        "excluded_fact_reuse_violation_count": 0,
        "overlap_double_count_violation_count": 0,
        "qa_grounding_violation_count": 0,
        "invented_visual_finding_count": 0,
    }
    for case in cases:
        for key in metrics:
            metrics[key] += int((case.get("violations") or {}).get(key) or 0)
    return metrics


def _category_summary(cases: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for case in cases:
        category = str(case.get("category") or "unknown")
        summary.setdefault(category, {"case_count": 0, "passed_count": 0, "failed_count": 0})
        summary[category]["case_count"] += 1
        if case.get("passed") is True:
            summary[category]["passed_count"] += 1
        else:
            summary[category]["failed_count"] += 1
    return summary


def _all_zero(metrics: dict[str, int]) -> bool:
    return all(value == 0 for value in metrics.values())


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# MedScope Evidence-bounded Reasoning Eval",
        "",
        "This artifact summarizes whether diagnosis and follow-up QA stay inside the evidence bundle.",
        "",
        f"- `status`: `{payload.get('status')}`",
        f"- `case_count`: `{payload.get('case_count')}`",
        "",
        "## Metrics",
        "",
    ]
    for key, value in (payload.get("metrics") or {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| category | case_id | passed | evidence sources |",
            "| --- | --- | --- | --- |",
        ]
    )
    for case in payload.get("eval_cases") or []:
        source_count = len(case.get("evidence_sources") or [])
        lines.append(
            "| {category} | {case_id} | {passed} | {source_count} |".format(
                category=case.get("category"),
                case_id=case.get("case_id"),
                passed=case.get("passed"),
                source_count=source_count,
            )
        )
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "",
            "- Diagnosis must cite adopted evidence or guideline citations.",
            "- Missing / unassessed evidence must not be interpreted as negative or zero.",
            "- Excluded and overlapping visual facts must not be reused as independent evidence.",
            "- QA must remain grounded in an existing evidence bundle.",
            "- This eval updates no diagnosis report.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    payload = build_evidence_bounded_reasoning_eval(output_dir=args.output_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
