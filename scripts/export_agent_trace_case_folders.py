from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


DEFAULT_INPUTS = [
    Path("output/fake/original_flow_full_mock_xray_gt_agent_final_20260610_trace_v2/agent_traces"),
    Path("output/fake/original_flow_mock_roi_side_prompt_runner_34_completed_20260611/agent_traces"),
    Path("output/fake/xray_34tag_side_mixed_original_flow_prompt_runner_34_completed_20260611/agent_traces"),
]
DEFAULT_OUTPUT_DIR = Path("output/fake/agent_trace_case_folders_20260611")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export MedScope agent traces into one folder per case."
    )
    parser.add_argument(
        "--input-trace-dir",
        type=Path,
        action="append",
        default=None,
        help="Directory containing case_trace_index.csv and cases/*.json. Can be repeated.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    input_dirs = args.input_trace_dir or DEFAULT_INPUTS
    export_case_folders(input_dirs=input_dirs, output_dir=args.output_dir)


def export_case_folders(*, input_dirs: list[Path], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    summary = {
        "schema_version": "medscope_agent_case_folder_export.v1",
        "output_dir": str(output_dir),
        "inputs": [str(path) for path in input_dirs],
        "experiments": {},
    }
    for input_dir in input_dirs:
        experiment_rows = _export_one_trace_dir(input_dir=input_dir, output_dir=output_dir)
        all_rows.extend(experiment_rows)
        if experiment_rows:
            experiment = str(experiment_rows[0].get("experiment_name") or input_dir.name)
            summary["experiments"][experiment] = {
                "case_count": len(experiment_rows),
                "index_csv": str(output_dir / _safe_filename(experiment) / "index.csv"),
                "index_json": str(output_dir / _safe_filename(experiment) / "index.json"),
            }

    combined_csv = output_dir / "index.csv"
    combined_json = output_dir / "index.json"
    _write_csv(combined_csv, all_rows)
    combined_json.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["case_count"] = len(all_rows)
    summary["index_csv"] = str(combined_csv)
    summary["index_json"] = str(combined_json)
    (output_dir / "README.md").write_text(_render_export_readme(summary), encoding="utf-8")
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _export_one_trace_dir(*, input_dir: Path, output_dir: Path) -> list[dict[str, Any]]:
    index_path = input_dir / "case_trace_index.csv"
    if not index_path.exists():
        raise FileNotFoundError(f"missing trace index: {index_path}")
    source_rows = list(csv.DictReader(index_path.open(encoding="utf-8")))
    exported_rows: list[dict[str, Any]] = []
    for order, source_row in enumerate(source_rows, start=1):
        trace_path = Path(str(source_row.get("case_trace_path") or ""))
        if not trace_path.is_absolute():
            trace_path = Path.cwd() / trace_path
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        experiment = _experiment_name_for_trace(trace, source_row, input_dir)
        experiment_dir = output_dir / _safe_filename(experiment)
        case_name = _case_folder_name(order=order, trace=trace, row=source_row)
        case_dir = experiment_dir / "cases" / case_name
        _write_case_folder(case_dir=case_dir, trace=trace, source_row=source_row)
        exported = {
            "order": order,
            "experiment_name": experiment,
            "trace_id": trace.get("trace_id"),
            "case_id": trace.get("case_id"),
            "patient_key": trace.get("patient_key"),
            "source": trace.get("source"),
            "image_path": trace.get("image_path"),
            "gt_xray_stage": source_row.get("gt_xray_stage"),
            "agent_final_stage": source_row.get("agent_final_stage"),
            "agent_loose_stage": source_row.get("agent_loose_stage"),
            "agent_xray_3class_stage": source_row.get("agent_xray_3class_stage"),
            "correct": source_row.get("correct"),
            "loose_correct": source_row.get("loose_correct"),
            "xray_3class_correct": source_row.get("xray_3class_correct"),
            "model_call_count": source_row.get("model_call_count"),
            "case_folder": str(case_dir),
            "case_readme": str(case_dir / "README.md"),
            "trace_json": str(case_dir / "trace.json"),
            "source_trace_json": str(trace_path),
        }
        exported_rows.append(exported)

    rows_by_experiment: dict[str, list[dict[str, Any]]] = {}
    for row in exported_rows:
        rows_by_experiment.setdefault(str(row.get("experiment_name") or input_dir.name), []).append(row)
    for experiment, experiment_rows in rows_by_experiment.items():
        experiment_dir = output_dir / _safe_filename(experiment)
        experiment_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(experiment_dir / "index.csv", experiment_rows)
        (experiment_dir / "index.json").write_text(
            json.dumps(experiment_rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (experiment_dir / "README.md").write_text(
            _render_experiment_readme(experiment, experiment_rows),
            encoding="utf-8",
        )
    return exported_rows


def _experiment_name_for_trace(
    trace: dict[str, Any],
    source_row: dict[str, Any],
    input_dir: Path,
) -> str:
    experiment = str(trace.get("experiment_name") or source_row.get("experiment_name") or input_dir.name)
    if experiment != "xray_cached_original_flow_both":
        return experiment
    source = str(trace.get("source") or source_row.get("source") or "")
    if source == "real_vlm_roi_findings":
        return "xray_cached_original_flow_real-vlm"
    if source == "mixed_real_vlm_plus_mock_findings":
        return "xray_cached_original_flow_mixed"
    return experiment


def _write_case_folder(*, case_dir: Path, trace: dict[str, Any], source_row: dict[str, Any]) -> None:
    events_dir = case_dir / "events"
    llm_dir = case_dir / "llm_calls"
    events_dir.mkdir(parents=True, exist_ok=True)
    llm_dir.mkdir(parents=True, exist_ok=True)

    (case_dir / "trace.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = _case_summary(trace, source_row)
    (case_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    event_rows = []
    model_call_rows = []
    for event in trace.get("events") or []:
        order = int(event.get("order") or len(event_rows) + 1)
        agent = str(event.get("agent") or "unknown")
        event_name = str(event.get("event") or "event")
        event_file = events_dir / f"{order:02d}_{_safe_filename(agent)}_{_safe_filename(event_name)}.json"
        event_file.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
        event_rows.append(
            {
                "order": order,
                "agent": agent,
                "event": event_name,
                "event_file": str(event_file),
            }
        )
        if agent == "ModelCallLogger":
            calls = ((event.get("output") or {}).get("model_calls") or [])
            for call_index, call in enumerate(calls, start=1):
                call_file, md_file = _write_model_call(llm_dir, call_index, call)
                model_call_rows.append(
                    {
                        "order": call_index,
                        "task": call.get("task"),
                        "call_id": call.get("call_id"),
                        "logged_at": call.get("logged_at"),
                        "model": call.get("model"),
                        "image_path": (call.get("image") or {}).get("image_path")
                        if isinstance(call.get("image"), dict)
                        else None,
                        "prompt_response_json": str(call_file),
                        "prompt_response_md": str(md_file),
                        "source_json_path": call.get("source_json_path"),
                    }
                )
    _write_csv(case_dir / "events_index.csv", event_rows)
    _write_csv(case_dir / "llm_calls_index.csv", model_call_rows)
    (case_dir / "README.md").write_text(
        _render_case_readme(summary, event_rows, model_call_rows),
        encoding="utf-8",
    )


def _write_model_call(llm_dir: Path, index: int, call: dict[str, Any]) -> tuple[Path, Path]:
    task = _safe_filename(str(call.get("task") or "model_call"))
    call_id = _safe_filename(str(call.get("call_id") or index))
    json_path = llm_dir / f"{index:02d}_{task}_{call_id}.json"
    md_path = llm_dir / f"{index:02d}_{task}_{call_id}.md"
    json_path.write_text(json.dumps(call, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_model_call_md(call), encoding="utf-8")
    return json_path, md_path


def _case_summary(trace: dict[str, Any], source_row: dict[str, Any]) -> dict[str, Any]:
    evaluation = {}
    for event in trace.get("events") or []:
        if event.get("agent") == "EvaluationRunner":
            output = event.get("output")
            if isinstance(output, dict):
                evaluation = output
                break
    return {
        "trace_id": trace.get("trace_id"),
        "case_id": trace.get("case_id"),
        "experiment_name": trace.get("experiment_name"),
        "patient_key": trace.get("patient_key"),
        "source": trace.get("source"),
        "image_path": trace.get("image_path"),
        "gt_xray_stage": source_row.get("gt_xray_stage") or evaluation.get("gt_xray_stage"),
        "agent_final_stage": source_row.get("agent_final_stage") or evaluation.get("agent_final_stage"),
        "agent_loose_stage": source_row.get("agent_loose_stage") or evaluation.get("agent_loose_stage"),
        "agent_xray_3class_stage": (
            source_row.get("agent_xray_3class_stage")
            or evaluation.get("agent_xray_3class_stage")
        ),
        "correct": source_row.get("correct") or evaluation.get("correct"),
        "loose_correct": source_row.get("loose_correct") or evaluation.get("loose_correct"),
        "xray_3class_correct": (
            source_row.get("xray_3class_correct")
            or evaluation.get("xray_3class_correct")
        ),
        "model_call_count": source_row.get("model_call_count"),
        "event_count": len(trace.get("events") or []),
        "evaluation": evaluation,
    }


def _case_folder_name(*, order: int, trace: dict[str, Any], row: dict[str, Any]) -> str:
    parts = [
        f"{order:03d}",
        str(trace.get("source") or row.get("source") or "case"),
        str(trace.get("patient_key") or row.get("patient_key") or ""),
        str(trace.get("trace_id") or row.get("trace_id") or ""),
    ]
    return _safe_filename("__".join(part for part in parts if part))[:180]


def _render_export_readme(summary: dict[str, Any]) -> str:
    lines = [
        "# MedScope Agent Trace Case Folders",
        "",
        f"- Total cases: {summary.get('case_count')}",
        f"- Combined index CSV: `{summary.get('index_csv')}`",
        f"- Combined index JSON: `{summary.get('index_json')}`",
        "",
        "## Experiments",
        "",
    ]
    for name, payload in (summary.get("experiments") or {}).items():
        lines.append(f"- `{name}`: {payload.get('case_count')} cases, index `{payload.get('index_csv')}`")
    lines.extend(
        [
            "",
            "## Per-Case Layout",
            "",
            "- `README.md`: human-readable overview",
            "- `summary.json`: compact metadata and final scoring",
            "- `trace.json`: full case trace",
            "- `events/`: one JSON file per agent event in execution order",
            "- `llm_calls/`: one JSON and one Markdown file per matched model call",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_experiment_readme(experiment: str, rows: list[dict[str, Any]]) -> str:
    by_source: dict[str, int] = {}
    for row in rows:
        source = str(row.get("source") or "unknown")
        by_source[source] = by_source.get(source, 0) + 1
    lines = [
        f"# {experiment}",
        "",
        f"- Cases: {len(rows)}",
        "- Index: `index.csv` / `index.json`",
        "",
        "## Source Counts",
        "",
    ]
    for source, count in sorted(by_source.items()):
        lines.append(f"- `{source}`: {count}")
    return "\n".join(lines) + "\n"


def _render_case_readme(
    summary: dict[str, Any],
    event_rows: list[dict[str, Any]],
    model_call_rows: list[dict[str, Any]],
) -> str:
    lines = [
        f"# {summary.get('trace_id')}",
        "",
        f"- Experiment: `{summary.get('experiment_name')}`",
        f"- Source: `{summary.get('source')}`",
        f"- Patient: `{summary.get('patient_key')}`",
        f"- Image: `{summary.get('image_path')}`",
        f"- GT Xray stage: `{summary.get('gt_xray_stage')}`",
        f"- Agent final stage: `{summary.get('agent_final_stage')}`",
        f"- Correct: `{summary.get('correct')}`",
        f"- Model calls: `{summary.get('model_call_count')}`",
        "",
        "## Agent Events",
        "",
    ]
    for row in event_rows:
        lines.append(f"{row['order']}. `{row['agent']}` / `{row['event']}` -> `{row['event_file']}`")
    lines.extend(["", "## LLM Calls", ""])
    if not model_call_rows:
        lines.append("No matched model calls for this case.")
    else:
        for row in model_call_rows:
            lines.append(
                f"{row['order']}. `{row.get('task')}` `{row.get('call_id')}` "
                f"-> `{row.get('prompt_response_md')}`"
            )
    return "\n".join(lines) + "\n"


def _render_model_call_md(call: dict[str, Any]) -> str:
    payload = call.get("request_payload")
    response = call.get("response_content")
    lines = [
        f"# {call.get('task')} / {call.get('call_id')}",
        "",
        f"- Logged at: `{call.get('logged_at')}`",
        f"- Model: `{call.get('model')}`",
        f"- Source JSON: `{call.get('source_json_path')}`",
        "",
        "## Request Payload",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Response Content",
        "",
        "```text",
        "" if response is None else str(response),
        "```",
        "",
    ]
    return "\n".join(lines)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)
    return cleaned.strip("._") or "unknown"


if __name__ == "__main__":
    main()
