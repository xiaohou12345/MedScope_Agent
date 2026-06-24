from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_VISION_SUMMARY = Path("output/fake/vision_evidence_eval_summary.json")
DEFAULT_CANDIDATE_QUEUE = Path("output/fake/vision_evidence_candidate_queue.json")
DEFAULT_VALIDATION_GATE = Path("output/fake/vision_evidence_candidate_validation_gate.json")
DEFAULT_OUTPUT_DIR = Path("output/fake")


def build_evidence_gateway_snapshot(
    *,
    vision_summary_path: Path | str = DEFAULT_VISION_SUMMARY,
    candidate_queue_path: Path | str = DEFAULT_CANDIDATE_QUEUE,
    validation_gate_path: Path | str = DEFAULT_VALIDATION_GATE,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    vision_summary = _read_json(Path(vision_summary_path))
    candidate_queue = _read_json(Path(candidate_queue_path))
    validation_gate = _read_json(Path(validation_gate_path))
    latest_attempt = _latest_non_reference_attempt(vision_summary)
    candidate_gate = _candidate_gate_summary(candidate_queue, validation_gate)
    visual_summary = _phase_b_visual_summary(latest_attempt)
    payload = {
        "schema_version": "evidence_gateway_snapshot.v1",
        "source_paths": {
            "vision_summary_path": str(vision_summary_path),
            "candidate_queue_path": str(candidate_queue_path),
            "validation_gate_path": str(validation_gate_path),
        },
        "architecture_model": {
            "recommended_narrative": (
                "Clinical Evidence Pipeline + Agentic Runtime / Evidence Gateway"
            ),
            "not_five_parallel_agents": True,
            "top_layer": [
                "Clinical Orchestrator",
                "Vision Evidence Component",
                "Diagnosis Reasoning Component",
                "Conditional Guideline Knowledge Component",
                "Memory / Audit Layer",
            ],
            "runtime_gateway": [
                "Knowledge Gateway",
                "Shared File Workspace",
                "Tool Router",
                "Contract Guards",
                "Stop Hooks / Reflection Hooks",
                "Self-evolving Candidate Queue",
                "Candidate Validation Gate",
            ],
        },
        "phase_b_visual_evidence": visual_summary,
        "candidate_gate": candidate_gate,
        "claims": _claims(visual_summary, candidate_gate),
        "overall_status": _overall_status(visual_summary, candidate_gate),
    }
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "evidence_gateway_snapshot.json"
    markdown_path = output / "evidence_gateway_snapshot.md"
    payload["output_paths"] = {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_non_reference_attempt(vision_summary: dict[str, Any]) -> dict[str, Any]:
    attempts = [
        attempt
        for attempt in vision_summary.get("non_reference_attempts") or []
        if isinstance(attempt, dict)
    ]
    return attempts[-1] if attempts else {}


def _phase_b_visual_summary(attempt: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(attempt.get("metrics") or {})
    artifacts = dict(attempt.get("artifacts") or {})
    return {
        "case_id": attempt.get("case_id"),
        "prompt_status": attempt.get("prompt_status"),
        "auto_eval_status": attempt.get("auto_eval_status"),
        "prompt_source": attempt.get("prompt_source"),
        "real_vlm_call_attempted": bool(attempt.get("real_vlm_call_attempted")),
        "real_medsam2_call_attempted": bool(attempt.get("real_medsam2_call_attempted")),
        "medsam2_ready": bool(attempt.get("medsam2_ready")),
        "reference_mask_used": bool(attempt.get("reference_mask_used")),
        "reference_mask_role": attempt.get("reference_mask_role"),
        "failure_types": list(attempt.get("failure_types") or []),
        "key_metrics": {
            key: _round_metric(metrics.get(key))
            for key in [
                "whole_tumor_dice",
                "tumor_core_dice",
                "enhancing_tumor_dice",
                "whole_tumor_false_positive_component_count",
            ]
            if key in metrics
        },
        "artifacts": {
            "mask_path": artifacts.get("mask_path"),
            "overlay_path": artifacts.get("overlay_path"),
            "auto_eval_summary_path": artifacts.get("auto_eval_summary_path"),
        },
    }


def _candidate_gate_summary(
    candidate_queue: dict[str, Any],
    validation_gate: dict[str, Any],
) -> dict[str, Any]:
    item_types = Counter(
        str(item.get("candidate_type") or "unknown")
        for item in candidate_queue.get("queue_items") or []
        if isinstance(item, dict)
    )
    promotion_decision = dict(validation_gate.get("promotion_decision") or {})
    review_summary = dict(validation_gate.get("review_summary") or {})
    runtime_safety = dict(candidate_queue.get("runtime_safety") or {})
    return {
        "candidate_count": int(candidate_queue.get("candidate_count") or 0),
        "candidate_type_counts": dict(sorted(item_types.items())),
        "non_reference_metric_review_count": item_types.get(
            "non_reference_metric_review", 0
        ),
        "pending_review_count": int(review_summary.get("pending_count") or 0),
        "promotion_status": promotion_decision.get("status"),
        "formal_update_allowed": bool(promotion_decision.get("formal_update_allowed")),
        "candidate_only": bool(runtime_safety.get("candidate_only")),
        "formal_knowledge_updated": bool(runtime_safety.get("formal_knowledge_updated")),
        "formal_guideline_updated": bool(runtime_safety.get("formal_guideline_updated")),
        "diagnosis_report_updated": bool(runtime_safety.get("diagnosis_report_updated")),
    }


def _claims(
    visual_summary: dict[str, Any],
    candidate_gate: dict[str, Any],
) -> dict[str, list[str]]:
    can_claim: list[str] = []
    if (
        visual_summary.get("auto_eval_status") == "ok"
        and visual_summary.get("medsam2_ready")
    ):
        can_claim.append("真实 VLM + MedSAM2 视觉链路已经可演示")
    if candidate_gate.get("promotion_status") == "blocked":
        can_claim.append("Evidence Gateway 能把未验证视觉问题阻断在 candidate-only 阶段")
    if candidate_gate.get("candidate_count"):
        can_claim.append("失败模式和人工复核项已被结构化记录到 candidate queue")
    cannot_claim = [
        "不能宣称通用医学图像分割已经达到临床级",
        "不能宣称 self-evolving 会自动修改正式 guideline knowledge",
        "不能把 non-reference candidate metric review 当作正式诊断依据",
    ]
    return {"can_claim": can_claim, "cannot_claim": cannot_claim}


def _overall_status(
    visual_summary: dict[str, Any],
    candidate_gate: dict[str, Any],
) -> str:
    if (
        visual_summary.get("auto_eval_status") == "ok"
        and visual_summary.get("medsam2_ready")
        and candidate_gate.get("promotion_status") == "blocked"
        and candidate_gate.get("formal_update_allowed") is False
    ):
        return "demonstrable_but_not_clinical_grade"
    if visual_summary.get("auto_eval_status") == "ok":
        return "visual_chain_runnable_gate_incomplete"
    return "incomplete"


def _round_metric(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    return value


def _render_markdown(payload: dict[str, Any]) -> str:
    visual = payload.get("phase_b_visual_evidence") or {}
    gate = payload.get("candidate_gate") or {}
    metrics = visual.get("key_metrics") or {}
    claims = payload.get("claims") or {}
    lines = [
        "# Evidence Gateway Snapshot",
        "",
        "用途：用一页说明当前系统不是五个并列 Agent，而是临床证据流水线 + Agentic Runtime / Evidence Gateway。",
        "",
        f"- `overall_status`: `{payload.get('overall_status')}`",
        "- 架构口径：不是五个并列 Agent；上层解释医疗证据职责，下层解释 knowledge、文件、工具、hooks 和候选验证。",
        "",
        "## Phase B Visual Evidence",
        "",
        f"- `case_id`: `{visual.get('case_id')}`",
        f"- `prompt_source`: `{visual.get('prompt_source')}`",
        f"- `auto_eval_status`: `{visual.get('auto_eval_status')}`",
        f"- `medsam2_ready`: `{visual.get('medsam2_ready')}`",
        f"- `reference_mask_used`: `{visual.get('reference_mask_used')}`",
        f"- `reference_mask_role`: `{visual.get('reference_mask_role')}`",
        f"- `failure_types`: `{visual.get('failure_types')}`",
        "",
        "### Key Metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Candidate Gate",
            "",
            f"- `candidate_count`: `{gate.get('candidate_count')}`",
            f"- `non_reference_metric_review_count`: `{gate.get('non_reference_metric_review_count')}`",
            f"- `pending_review_count`: `{gate.get('pending_review_count')}`",
            f"- `promotion_status`: `{gate.get('promotion_status')}`",
            f"- `formal_update_allowed`: `{gate.get('formal_update_allowed')}`",
            "",
            "## Can Claim",
            "",
        ]
    )
    for claim in claims.get("can_claim") or []:
        lines.append(f"- {claim}")
    lines.extend(["", "## Cannot Claim", ""])
    for claim in claims.get("cannot_claim") or []:
        lines.append(f"- {claim}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vision-summary", type=Path, default=DEFAULT_VISION_SUMMARY)
    parser.add_argument("--candidate-queue", type=Path, default=DEFAULT_CANDIDATE_QUEUE)
    parser.add_argument("--validation-gate", type=Path, default=DEFAULT_VALIDATION_GATE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    payload = build_evidence_gateway_snapshot(
        vision_summary_path=args.vision_summary,
        candidate_queue_path=args.candidate_queue,
        validation_gate_path=args.validation_gate,
        output_dir=args.output_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
