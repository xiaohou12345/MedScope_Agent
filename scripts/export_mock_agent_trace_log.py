from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memory.memory_manager import MemoryManager


DEFAULT_SUMMARY_PATH = Path("output/fake/onfh_coco_mock_api_eval/summary.json")


def export_agent_trace_log(summary_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    output = output_dir or summary_path.parent
    output.mkdir(parents=True, exist_ok=True)
    memory = MemoryManager()

    entries = []
    for case in summary.get("cases") or []:
        case_id = str(case["case_id"])
        record = memory.load_case_memory(case_id)
        audit = memory.build_audit_summary(case_id)
        replay = memory.build_case_replay(case_id)
        runtime_manifest = memory.build_runtime_manifest(case_id)
        mock_visual_summary = _load_mock_visual_summary(case)
        entry = _build_trace_entry(
            case=case,
            record=record,
            audit=audit,
            replay=replay,
            runtime_manifest=runtime_manifest,
            mock_visual_summary=mock_visual_summary,
        )
        entries.append(entry)

    jsonl_path = output / "agent_trace_log.jsonl"
    json_path = output / "agent_trace_log.json"
    md_path = output / "agent_trace_log.md"
    jsonl_path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n",
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(
            {
                "source_summary_path": str(summary_path),
                "case_count": len(entries),
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    md_path.write_text(_build_markdown(entries), encoding="utf-8")

    export_summary = {
        "status": "ok",
        "source_summary_path": str(summary_path),
        "case_count": len(entries),
        "agent_trace_log_jsonl": str(jsonl_path),
        "agent_trace_log_json": str(json_path),
        "agent_trace_log_md": str(md_path),
    }
    export_summary_path = output / "agent_trace_log_summary.json"
    export_summary["summary_path"] = str(export_summary_path)
    export_summary_path.write_text(
        json.dumps(export_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return export_summary


def _load_mock_visual_summary(case: dict[str, Any]) -> dict[str, Any]:
    mask_path = case.get("mask_path")
    if not mask_path:
        return {}
    path = Path(mask_path).parent / "mock_visual_summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_trace_entry(
    *,
    case: dict[str, Any],
    record: dict[str, Any],
    audit: dict[str, Any],
    replay: dict[str, Any],
    runtime_manifest: dict[str, Any],
    mock_visual_summary: dict[str, Any],
) -> dict[str, Any]:
    patient_memory = record.get("patient_memory") or {}
    image_memory = record.get("image_memory") or {}
    skill_memory = record.get("skill_memory") or {}
    reasoning_memory = record.get("reasoning_memory") or {}
    report = reasoning_memory.get("report") or {}
    visual_evidence = image_memory.get("visual_evidence") or {}
    visual_input_contract = reasoning_memory.get("visual_input_contract") or {}
    routing_decision = skill_memory.get("routing_decision") or {}
    alignment_plan = skill_memory.get("alignment_plan") or reasoning_memory.get("alignment_plan") or {}
    service_payload = {
        "patient_message": patient_memory.get("patient_message"),
        "image_path": image_memory.get("image_path"),
        "patient_info": patient_memory.get("patient_info") or {},
        "disease_key": routing_decision.get("selected_skill"),
        "vision_mode": skill_memory.get("selected_vision_mode"),
    }
    return {
        "case_id": record.get("case_id"),
        "patient_key": case.get("patient_key"),
        "image_id": case.get("image_id"),
        "image_path": case.get("image_path"),
        "side_mapping": "ap_flip: image_left -> patient_right, image_right -> patient_left",
        "service_input": service_payload,
        "agent_io": {
            "MedScopeService": {
                "input": service_payload,
                "output": {
                    "routing_decision": routing_decision,
                    "alignment_plan": alignment_plan,
                    "analysis_status": case.get("analysis_status"),
                },
            },
            "GaoDoctorAgent": {
                "input": {
                    "patient_message": patient_memory.get("patient_message"),
                    "image_path": image_memory.get("image_path"),
                    "patient_info": patient_memory.get("patient_info") or {},
                    "disease_key": routing_decision.get("selected_skill"),
                    "vision_mode": skill_memory.get("selected_vision_mode"),
                },
                "output": {
                    "intent": patient_memory.get("intent"),
                    "case_id": record.get("case_id"),
                    "visual_result_forwarded": bool(visual_evidence),
                    "report_forwarded": bool(report),
                },
            },
            "SkillBuilderAgent": {
                "input": routing_decision,
                "output": {
                    "selected_skill": skill_memory.get("selected_skill"),
                    "used_skill": skill_memory.get("used_skill"),
                    "skill_type": skill_memory.get("skill_type"),
                    "quality_control": skill_memory.get("quality_control") or {},
                },
            },
            "VisionAgentMock": {
                "input": {
                    "image_path": image_memory.get("image_path"),
                    "mock_source_export_dir": (visual_evidence.get("measurements") or {}).get(
                        "mock_source_export_dir"
                    ),
                    "xray_image_id": (visual_evidence.get("measurements") or {}).get("xray_image_id"),
                },
                "output": {
                    "image_outputs": image_memory.get("image_outputs") or {},
                    "measurements": visual_evidence.get("measurements") or {},
                    "findings": visual_evidence.get("findings") or [],
                    "structured_visual_facts": visual_evidence.get("structured_visual_facts") or [],
                    "segmentation_results": visual_evidence.get("segmentation_results") or [],
                    "mock_visual_summary": _compact_mock_visual_summary(mock_visual_summary),
                },
            },
            "DiagnosisDoctorAgent": {
                "input": visual_input_contract,
                "output": {
                    "diagnostic_tendency": reasoning_memory.get("diagnostic_tendency"),
                    "stage_text": report.get("分期判断"),
                    "key_evidence": reasoning_memory.get("key_evidence") or [],
                    "uncertainty": reasoning_memory.get("uncertainty") or [],
                    "visual_fact_usage": reasoning_memory.get("visual_fact_usage") or {},
                    "report": report,
                },
            },
            "MemoryManager": {
                "input": {
                    "case_id": record.get("case_id"),
                    "memory_types": record.get("memory_types") or [],
                },
                "output": {
                    "case_memory_path": case.get("case_memory_path"),
                    "audit_path": runtime_manifest.get("generated_artifacts", {}).get("memory_audit_path"),
                    "runtime_manifest_path": runtime_manifest.get("manifest_path"),
                    "memory_completeness": audit.get("memory_completeness") or {},
                },
            },
        },
        "replay": replay,
        "audit_summary": audit,
        "runtime_manifest": runtime_manifest,
    }


def _compact_mock_visual_summary(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}
    visual_result = summary.get("visual_analysis_result") or {}
    evidence = visual_result.get("visual_evidence") or {}
    return {
        "status": summary.get("status"),
        "image_id": summary.get("image_id"),
        "patient_key": summary.get("patient_key"),
        "finding_count": summary.get("finding_count"),
        "gt_mri_tags": summary.get("gt_mri_tags") or [],
        "gt_mri_stage_by_side": summary.get("gt_mri_stage_by_side") or {},
        "mask_path": summary.get("mask_path"),
        "overlay_path": summary.get("overlay_path"),
        "measurements": evidence.get("measurements") or {},
        "requested_targets": visual_result.get("requested_targets") or [],
    }


def _build_markdown(entries: list[dict[str, Any]]) -> str:
    lines = [
        "# ONFH Mock Agent Trace Log",
        "",
        f"Cases: {len(entries)}",
        "",
        "This log records the tested in-process chain: service input -> routing/alignment -> mock visual output -> diagnosis -> memory/audit.",
        "",
    ]
    for entry in entries:
        case_id = entry["case_id"]
        vision = entry["agent_io"]["VisionAgentMock"]["output"]
        diagnosis = entry["agent_io"]["DiagnosisDoctorAgent"]["output"]
        memory_output = entry["agent_io"]["MemoryManager"]["output"]
        measurements = vision.get("measurements") or {}
        findings = vision.get("findings") or []
        lines.extend(
            [
                f"## {case_id}",
                "",
                f"- Patient: `{entry.get('patient_key')}`",
                f"- Image ID: `{entry.get('image_id')}`",
                f"- Image: `{entry.get('image_path')}`",
                f"- Side mapping: `{entry.get('side_mapping')}`",
                f"- Case memory: `{memory_output.get('case_memory_path')}`",
                f"- Runtime manifest: `{memory_output.get('runtime_manifest_path')}`",
                f"- Mask: `{vision.get('image_outputs', {}).get('mask_path')}`",
                f"- Overlay: `{vision.get('image_outputs', {}).get('overlay_path')}`",
                f"- Total mask area px: `{measurements.get('lesion_area_px')}`",
                f"- Total mask area ratio: `{measurements.get('lesion_area_ratio')}`",
                f"- Finding count: `{len(findings)}`",
                f"- Diagnostic tendency: `{diagnosis.get('diagnostic_tendency')}`",
                f"- Stage text: `{diagnosis.get('stage_text')}`",
                "",
                "| label | side | area_px | area_ratio | bbox |",
                "| --- | --- | ---: | ---: | --- |",
            ]
        )
        for finding in findings:
            item = finding.get("measurements") or {}
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(finding.get("display_name")),
                        str(item.get("patient_side")),
                        str(item.get("area_px")),
                        str(item.get("area_ratio_in_image")),
                        str(item.get("bbox")),
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export full agent IO logs for ONFH mock COCO eval.")
    parser.add_argument("--summary-path", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = export_agent_trace_log(args.summary_path, output_dir=args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
