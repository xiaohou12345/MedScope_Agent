from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
from typing import Any


DEFAULT_EXPERIMENT_ROOT = Path("output/fake/onfh_xray_six_experiments_20260611")
DEFAULT_OUTPUT = DEFAULT_EXPERIMENT_ROOT / "trace_viewer.html"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a dependency-free HTML viewer for MedScope experiment traces."
    )
    parser.add_argument("--experiment-root", type=Path, default=DEFAULT_EXPERIMENT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--max-json-chars",
        type=int,
        default=180_000,
        help="Maximum characters embedded for one JSON pane before truncation.",
    )
    args = parser.parse_args()
    build_viewer(
        experiment_root=args.experiment_root,
        output=args.output,
        max_json_chars=args.max_json_chars,
    )


def build_viewer(*, experiment_root: Path, output: Path, max_json_chars: int) -> dict[str, Any]:
    experiment_root = experiment_root.resolve()
    output = output.resolve()
    payload = {
        "experiment_root": str(experiment_root),
        "index": _read_csv(experiment_root / "index.csv"),
        "experiments": [],
    }
    for exp_dir in sorted(p for p in experiment_root.iterdir() if p.is_dir()):
        if not exp_dir.name[:2].isdigit():
            continue
        payload["experiments"].append(
            _load_experiment(exp_dir=exp_dir, max_json_chars=max_json_chars)
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_html(payload), encoding="utf-8")
    return {"output": str(output), "experiment_count": len(payload["experiments"])}


def _load_experiment(*, exp_dir: Path, max_json_chars: int) -> dict[str, Any]:
    cases_dir = exp_dir / "cases"
    cases = []
    if cases_dir.exists():
        for case_dir in sorted(p for p in cases_dir.iterdir() if p.is_dir()):
            cases.append(_load_case(case_dir=case_dir, max_json_chars=max_json_chars))
    return {
        "folder": exp_dir.name,
        "readme": _read_text(exp_dir / "README.md", limit=20_000),
        "metrics": _read_json(exp_dir / "metrics.json", max_json_chars=max_json_chars),
        "summary": _read_json(exp_dir / "summary.json", max_json_chars=max_json_chars),
        "config": _experiment_config(exp_dir),
        "rows_csv": str((exp_dir / "rows.csv").resolve()) if (exp_dir / "rows.csv").exists() else "",
        "case_count": len(cases),
        "cases": cases,
    }


def _load_case(*, case_dir: Path, max_json_chars: int) -> dict[str, Any]:
    summary = _read_json(case_dir / "summary.json", max_json_chars=max_json_chars)
    row = _read_json(case_dir / "row.json", max_json_chars=max_json_chars)
    events = []
    events_dir = case_dir / "events"
    if events_dir.exists():
        for event_file in sorted(events_dir.glob("*.json")):
            event = _read_json(event_file, max_json_chars=max_json_chars)
            events.append(
                {
                    "file": event_file.name,
                    "agent": event.get("agent"),
                    "event": event.get("event"),
                    "order": event.get("order"),
                    "json": event,
                }
            )
    else:
        events_json = _read_json(case_dir / "events.json", max_json_chars=max_json_chars)
        if isinstance(events_json, list):
            for event in events_json:
                if isinstance(event, dict):
                    events.append(
                        {
                            "file": "events.json",
                            "agent": event.get("agent"),
                            "event": event.get("event"),
                            "order": event.get("order"),
                            "json": event,
                        }
                    )

    llm_calls = []
    llm_dir = case_dir / "llm_calls"
    if llm_dir.exists():
        for call_file in sorted(llm_dir.glob("*.json")):
            call = _read_json(call_file, max_json_chars=max_json_chars)
            llm_calls.append(
                {
                    "file": call_file.name,
                    "task": call.get("task"),
                    "model": call.get("model"),
                    "status": call.get("status"),
                    "json": call,
                }
            )
    return {
        "folder": case_dir.name,
        "path": str(case_dir.resolve()),
        "readme": _read_text(case_dir / "README.md", limit=20_000),
        "summary": summary,
        "row": row,
        "config": _case_config(summary, events, llm_calls),
        "events": events,
        "llm_calls": llm_calls,
    }


def _experiment_config(exp_dir: Path) -> dict[str, Any]:
    metrics = _read_json(exp_dir / "metrics.json", max_json_chars=80_000)
    if not isinstance(metrics, dict):
        metrics = {}
    has_cases = (exp_dir / "cases").exists()
    has_traces = (exp_dir / "agent_traces").exists()
    readme = _read_text(exp_dir / "README.md", limit=20_000)
    return {
        "experiment": metrics.get("experiment") or exp_dir.name,
        "visual_evidence_source": metrics.get("visual_evidence_source"),
        "diagnosis_llm": metrics.get("diagnosis_llm"),
        "primary_metric": metrics.get("primary_metric") or "agent_final_stage vs Xray GT",
        "rows_csv": str((exp_dir / "rows.csv").resolve()) if (exp_dir / "rows.csv").exists() else "",
        "has_case_folders": has_cases,
        "has_raw_agent_traces": has_traces,
        "trace_note": _trace_note(readme, has_traces),
    }


def _trace_note(readme: str, has_traces: bool) -> str:
    if "Trace Limitation" in readme:
        return (
            "This experiment has reconstructed lightweight case folders only; "
            "full per-agent trace and prompt/response records were not saved in the source run."
        )
    if has_traces:
        return "Full case traces are available when the case has events and LLM call files."
    return "No raw trace directory was found for this experiment entry."


def _case_config(
    summary: Any,
    events: list[dict[str, Any]],
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    summary_dict = summary if isinstance(summary, dict) else {}
    return {
        "experiment_name": summary_dict.get("experiment_name"),
        "source": summary_dict.get("source"),
        "case_id": summary_dict.get("case_id"),
        "trace_id": summary_dict.get("trace_id"),
        "image_path": summary_dict.get("image_path"),
        "gt_xray_stage": summary_dict.get("gt_xray_stage"),
        "agent_final_stage": summary_dict.get("agent_final_stage"),
        "correct": summary_dict.get("correct"),
        "event_count": len(events),
        "llm_call_count": len(llm_calls),
        "agent_flow": [
            {
                "order": event.get("order"),
                "agent": event.get("agent"),
                "event": event.get("event"),
            }
            for event in events
        ],
        "llm_flow": [
            {
                "order": index,
                "task": call.get("task"),
                "model": call.get("model"),
                "status": call.get("status"),
                "route": (call.get("json") or {}).get("route") if isinstance(call.get("json"), dict) else None,
                "duration_ms": (call.get("json") or {}).get("duration_ms")
                if isinstance(call.get("json"), dict)
                else None,
            }
            for index, call in enumerate(llm_calls, start=1)
        ],
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path, *, max_json_chars: int) -> Any:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"_parse_error": "invalid json", "_path": str(path), "_text": text[:max_json_chars]}
    rendered = json.dumps(value, ensure_ascii=False, indent=2)
    if len(rendered) <= max_json_chars:
        return value
    return {
        "_truncated": True,
        "_path": str(path),
        "_chars": len(rendered),
        "_preview": rendered[:max_json_chars],
    }


def _read_text(path: Path, *, limit: int) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[truncated]"


def _render_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MedScope Trace Viewer</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #667085;
      --border: #d9dee7;
      --accent: #176b87;
      --accent-2: #7a4b00;
      --bad: #b42318;
      --good: #027a48;
      --code: #111827;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
    }}
    header {{
      height: 56px;
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 0 18px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 2;
    }}
    header h1 {{
      font-size: 17px;
      margin: 0;
      white-space: nowrap;
    }}
    input, select, button {{
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text);
      border-radius: 6px;
      height: 34px;
      padding: 0 10px;
      font: inherit;
    }}
    button {{
      cursor: pointer;
      background: #f9fafb;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 320px minmax(420px, 1fr) 48%;
      min-height: calc(100vh - 56px);
    }}
    aside, main, section {{
      min-width: 0;
      border-right: 1px solid var(--border);
    }}
    aside {{
      background: var(--panel);
      padding: 12px;
      overflow: auto;
      max-height: calc(100vh - 56px);
      position: sticky;
      top: 56px;
    }}
    main, section {{
      padding: 14px;
      overflow: auto;
      max-height: calc(100vh - 56px);
    }}
    .toolbar {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      margin-bottom: 10px;
    }}
    .case {{
      cursor: pointer;
    }}
    .case.active, .event.active, .llm-call.active {{
      border-color: var(--accent);
      box-shadow: inset 3px 0 0 var(--accent);
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 6px;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 2px 7px;
      border: 1px solid var(--border);
      border-radius: 999px;
      color: var(--muted);
      background: #fbfcfe;
      font-size: 12px;
    }}
    .pill.good {{ color: var(--good); border-color: #a6d8bf; }}
    .pill.bad {{ color: var(--bad); border-color: #f5b5ad; }}
    .pill.warn {{ color: var(--accent-2); border-color: #e7c47c; }}
    .event {{
      cursor: pointer;
    }}
    .flow-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 8px;
    }}
    .kv {{
      display: grid;
      grid-template-columns: 150px minmax(0, 1fr);
      gap: 6px 10px;
      align-items: start;
    }}
    .kv div:nth-child(odd) {{
      color: var(--muted);
      font-size: 12px;
    }}
    .llm-call {{
      cursor: pointer;
    }}
    .event-title {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-weight: 600;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: var(--code);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      line-height: 1.45;
    }}
    .tabs {{
      display: flex;
      gap: 6px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }}
    .tabs button.active {{
      border-color: var(--accent);
      color: var(--accent);
      background: #eef8fb;
    }}
    .muted {{ color: var(--muted); }}
    .small {{ font-size: 12px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 7px 8px;
      text-align: left;
      vertical-align: top;
      font-size: 12px;
    }}
    th {{ background: #f3f5f8; }}
    mark {{ background: #ffe58f; padding: 0 2px; }}
  </style>
</head>
<body>
  <header>
    <h1>MedScope Trace Viewer</h1>
    <select id="experimentSelect"></select>
    <input id="searchInput" placeholder="搜索 case / agent / prompt / 字段" style="min-width: 300px; flex: 1;" />
    <button id="clearSearch">清空</button>
  </header>
  <div class="layout">
    <aside>
      <div id="experimentSummary"></div>
      <div id="caseList"></div>
    </aside>
    <main>
      <div id="caseHeader"></div>
      <div id="eventList"></div>
    </main>
    <section>
      <div class="tabs">
        <button data-tab="config" class="active">Config</button>
        <button data-tab="input">Event Input</button>
        <button data-tab="output">Event Output</button>
        <button data-tab="llm_input">LLM Input</button>
        <button data-tab="llm_output">LLM Output</button>
        <button data-tab="json">Raw JSON</button>
      </div>
      <div id="detailPane"></div>
    </section>
  </div>
  <script id="trace-data" type="application/json">{html.escape(data)}</script>
  <script>
    const DATA = JSON.parse(document.getElementById('trace-data').textContent);
    const state = {{ expIndex: 0, caseIndex: 0, eventIndex: 0, llmIndex: 0, tab: 'config', query: '' }};

    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    const jsonText = (v) => JSON.stringify(v ?? null, null, 2);
    const contains = (obj, q) => !q || JSON.stringify(obj ?? '', null, 0).toLowerCase().includes(q.toLowerCase());

    function selectedExperiment() {{ return DATA.experiments[state.expIndex] || DATA.experiments[0]; }}
    function filteredCases() {{
      const exp = selectedExperiment();
      const q = state.query.trim();
      return (exp.cases || []).map((c, i) => [c, i]).filter(([c]) => contains(c, q));
    }}
    function selectedCase() {{
      const cases = filteredCases();
      return cases[state.caseIndex]?.[0] || cases[0]?.[0] || null;
    }}
    function selectedEvent() {{
      const c = selectedCase();
      return c?.events?.[state.eventIndex] || c?.events?.[0] || null;
    }}
    function selectedLlmCall() {{
      const c = selectedCase();
      return c?.llm_calls?.[state.llmIndex] || c?.llm_calls?.[0] || null;
    }}
    function metricFor(folder) {{
      return (DATA.index || []).find(row => row.folder === folder) || {{}};
    }}
    function render() {{
      renderExperimentSelect();
      renderCaseList();
      renderEventList();
      renderDetail();
    }}
    function renderExperimentSelect() {{
      const sel = $('experimentSelect');
      if (!sel.dataset.ready) {{
        DATA.experiments.forEach((exp, i) => {{
          const opt = document.createElement('option');
          opt.value = i;
          opt.textContent = `${{exp.folder}} (${{exp.case_count}} cases)`;
          sel.appendChild(opt);
        }});
        sel.addEventListener('change', () => {{
          state.expIndex = Number(sel.value);
          state.caseIndex = 0; state.eventIndex = 0;
          render();
        }});
        sel.dataset.ready = '1';
      }}
      sel.value = state.expIndex;
    }}
    function renderCaseList() {{
      const exp = selectedExperiment();
      const metric = metricFor(exp.folder);
      $('experimentSummary').innerHTML = `
        <div class="card">
          <strong>${{esc(exp.folder)}}</strong>
          <div class="meta">
            <span class="pill">acc ${{esc(metric.accuracy || '')}}</span>
            <span class="pill">correct ${{esc(metric.correct || '')}}/${{esc(metric.total || '')}}</span>
            <span class="pill">abstain ${{esc(metric.abstain || '')}}</span>
            <span class="pill">LLM ${{esc(exp.config?.diagnosis_llm)}}</span>
          </div>
          <div class="small muted" style="margin-top:8px;">${{esc(metric.experiment || '')}}</div>
          <div class="small muted" style="margin-top:6px;">${{esc(exp.config?.trace_note || '')}}</div>
        </div>`;
      const cases = filteredCases();
      if (state.caseIndex >= cases.length) state.caseIndex = 0;
      $('caseList').innerHTML = cases.map(([c, originalIndex], i) => {{
        const s = c.summary || {{}};
        const ok = String(s.correct ?? s.evaluation?.correct ?? '').toLowerCase() === 'true';
        const gt = s.gt_xray_stage ?? s.evaluation?.gt_xray_stage ?? '';
        const pred = s.agent_final_stage ?? s.evaluation?.agent_final_stage ?? '';
        return `<div class="card case ${{i === state.caseIndex ? 'active' : ''}}" data-case="${{i}}">
          <strong>${{esc(c.folder)}}</strong>
          <div class="meta">
            <span class="pill ${{ok ? 'good' : 'bad'}}">${{ok ? 'correct' : 'not correct'}}</span>
            <span class="pill">GT ${{esc(gt)}}</span>
            <span class="pill">Pred ${{esc(pred)}}</span>
            <span class="pill">events ${{c.events?.length || 0}}</span>
            <span class="pill">LLM ${{c.llm_calls?.length || 0}}</span>
          </div>
        </div>`;
      }}).join('') || '<div class="muted">No cases matched.</div>';
      document.querySelectorAll('.case').forEach(el => el.addEventListener('click', () => {{
        state.caseIndex = Number(el.dataset.case);
        state.eventIndex = 0; state.llmIndex = 0;
        render();
      }}));
    }}
    function renderEventList() {{
      const c = selectedCase();
      if (!c) {{
        $('caseHeader').innerHTML = '';
        $('eventList').innerHTML = '';
        return;
      }}
      const s = c.summary || {{}};
      $('caseHeader').innerHTML = `<div class="card">
        <strong>${{esc(c.folder)}}</strong>
        <div class="small muted">${{esc(c.path)}}</div>
        <div class="meta">
          <span class="pill">GT ${{esc(s.gt_xray_stage ?? s.evaluation?.gt_xray_stage ?? '')}}</span>
          <span class="pill">Pred ${{esc(s.agent_final_stage ?? s.evaluation?.agent_final_stage ?? '')}}</span>
          <span class="pill">Source ${{esc(s.source || '')}}</span>
          <span class="pill">LLM ${{c.llm_calls?.length || 0}}</span>
        </div>
      </div>`;
      const events = c.events || [];
      if (state.eventIndex >= events.length) state.eventIndex = 0;
      const eventHtml = events.map((e, i) => `
        <div class="card event ${{i === state.eventIndex ? 'active' : ''}}" data-event="${{i}}">
          <div class="event-title"><span>${{esc(e.order)}}. ${{esc(e.agent)}}</span><span class="muted">${{esc(e.event)}}</span></div>
          <div class="small muted">${{esc(e.file)}}</div>
        </div>`).join('');
      const llmCalls = c.llm_calls || [];
      if (state.llmIndex >= llmCalls.length) state.llmIndex = 0;
      const llmHtml = `
        <div class="card">
          <strong>LLM Calls</strong>
          <div class="small muted">选择后在右侧查看本次模型调用的输入和输出。</div>
        </div>
        ${{llmCalls.map((call, i) => `
          <div class="card llm-call ${{i === state.llmIndex ? 'active' : ''}}" data-llm="${{i}}">
            <div class="event-title"><span>${{i + 1}}. ${{esc(call.task)}}</span><span class="muted">${{esc(call.status)}}</span></div>
            <div class="small muted">${{esc(call.model)}} · ${{esc(call.file)}}</div>
          </div>`).join('') || '<div class="card muted">No LLM calls recorded for this case.</div>'}}
      `;
      $('eventList').innerHTML = `<div class="card"><strong>Agent Flow</strong><div class="small muted">按实际记录顺序展示 agent 输入输出事件。</div></div>${{eventHtml}}${{llmHtml}}`;
      document.querySelectorAll('.event').forEach(el => el.addEventListener('click', () => {{
        state.eventIndex = Number(el.dataset.event);
        if (!['config', 'llm_input', 'llm_output'].includes(state.tab)) state.tab = state.tab;
        render();
      }}));
      document.querySelectorAll('.llm-call').forEach(el => el.addEventListener('click', () => {{
        state.llmIndex = Number(el.dataset.llm);
        if (!['llm_input', 'llm_output'].includes(state.tab)) state.tab = 'llm_input';
        render();
      }}));
    }}
    function renderDetail() {{
      document.querySelectorAll('.tabs button').forEach(btn => {{
        btn.classList.toggle('active', btn.dataset.tab === state.tab);
      }});
      const c = selectedCase();
      const e = selectedEvent();
      const call = selectedLlmCall();
      if (!c) {{
        $('detailPane').innerHTML = '<div class="muted">No case selected.</div>';
        return;
      }}
      if (state.tab === 'config') {{
        $('detailPane').innerHTML = renderConfig(selectedExperiment(), c);
      }} else if (state.tab === 'llm_input') {{
        if (!call) $('detailPane').innerHTML = '<div class="muted">No LLM call selected.</div>';
        else $('detailPane').innerHTML = renderLlmInput(call);
      }} else if (state.tab === 'llm_output') {{
        if (!call) $('detailPane').innerHTML = '<div class="muted">No LLM call selected.</div>';
        else $('detailPane').innerHTML = renderLlmOutput(call);
      }} else if (!e) {{
        $('detailPane').innerHTML = '<div class="muted">No event selected.</div>';
      }} else if (state.tab === 'input') {{
        $('detailPane').innerHTML = `<pre>${{esc(jsonText(e.json?.input))}}</pre>`;
      }} else if (state.tab === 'output') {{
        $('detailPane').innerHTML = `<pre>${{esc(jsonText(e.json?.output))}}</pre>`;
      }} else {{
        $('detailPane').innerHTML = `<pre>${{esc(jsonText({{case: c, selected_event: e, selected_llm_call: call}}))}}</pre>`;
      }}
    }}

    function renderConfig(exp, c) {{
      const cfg = exp.config || {{}};
      const ccfg = c.config || {{}};
      const metric = metricFor(exp.folder);
      const flow = (ccfg.agent_flow || []).map(item => `
        <div class="card">
          <strong>${{esc(item.order)}}. ${{esc(item.agent)}}</strong>
          <div class="small muted">${{esc(item.event)}}</div>
        </div>`).join('');
      const llmFlow = (ccfg.llm_flow || []).map(item => `
        <div class="card">
          <strong>${{esc(item.order)}}. ${{esc(item.task)}}</strong>
          <div class="meta">
            <span class="pill">${{esc(item.model)}}</span>
            <span class="pill">${{esc(item.status)}}</span>
            <span class="pill">${{esc(item.route || '')}}</span>
            <span class="pill">${{esc(item.duration_ms || '')}} ms</span>
          </div>
        </div>`).join('') || '<div class="card muted">No LLM calls recorded.</div>';
      return `
        <div class="card">
          <strong>Experiment Config</strong>
          <div class="kv" style="margin-top:10px;">
            <div>experiment</div><div>${{esc(cfg.experiment || metric.experiment || exp.folder)}}</div>
            <div>visual evidence</div><div>${{esc(cfg.visual_evidence_source || '')}}</div>
            <div>diagnosis LLM</div><div>${{esc(cfg.diagnosis_llm)}}</div>
            <div>primary metric</div><div>${{esc(cfg.primary_metric || '')}}</div>
            <div>rows csv</div><div>${{esc(cfg.rows_csv || '')}}</div>
            <div>trace status</div><div>${{esc(cfg.trace_note || '')}}</div>
          </div>
        </div>
        <div class="card">
          <strong>Case Result</strong>
          <div class="kv" style="margin-top:10px;">
            <div>case id</div><div>${{esc(ccfg.case_id || '')}}</div>
            <div>trace id</div><div>${{esc(ccfg.trace_id || '')}}</div>
            <div>source</div><div>${{esc(ccfg.source || '')}}</div>
            <div>image path</div><div>${{esc(ccfg.image_path || '')}}</div>
            <div>GT Xray stage</div><div>${{esc(ccfg.gt_xray_stage || '')}}</div>
            <div>agent final stage</div><div>${{esc(ccfg.agent_final_stage || '')}}</div>
            <div>correct</div><div>${{esc(ccfg.correct)}}</div>
          </div>
        </div>
        <div class="card"><strong>Agent Flow</strong></div>
        <div class="flow-grid">${{flow || '<div class="muted">No agent events recorded.</div>'}}</div>
        <div class="card"><strong>LLM Flow</strong><div class="small muted">这里列出每次模型调用；具体 prompt/response 用 LLM Input / LLM Output tab 查看。</div></div>
        <div class="flow-grid">${{llmFlow}}</div>
      `;
    }}

    function renderLlmInput(call) {{
      const obj = call.json || {{}};
      const input = {{
        task: call.task,
        model: call.model,
        status: call.status,
        route: obj.route,
        endpoint: obj.endpoint,
        image: obj.image,
        messages: obj.messages,
        request_payload: obj.request_payload,
      }};
      return `<div class="card"><strong>${{esc(call.task)}} · Input</strong><div class="small muted">${{esc(call.file)}}</div></div><pre>${{esc(jsonText(input))}}</pre>`;
    }}

    function renderLlmOutput(call) {{
      const obj = call.json || {{}};
      const output = {{
        task: call.task,
        model: call.model,
        status: call.status,
        duration_ms: obj.duration_ms,
        retry_count: obj.retry_count,
        errors: obj.errors,
        response_content: obj.response_content,
        response_raw_summary: obj.response_raw_summary,
      }};
      return `<div class="card"><strong>${{esc(call.task)}} · Output</strong><div class="small muted">${{esc(call.file)}}</div></div><pre>${{esc(jsonText(output))}}</pre>`;
    }}

    $('searchInput').addEventListener('input', (event) => {{
      state.query = event.target.value;
      state.caseIndex = 0; state.eventIndex = 0;
      render();
    }});
    $('clearSearch').addEventListener('click', () => {{
      $('searchInput').value = '';
      state.query = '';
      state.caseIndex = 0; state.eventIndex = 0;
      render();
    }});
    document.querySelectorAll('.tabs button').forEach(btn => btn.addEventListener('click', () => {{
      state.tab = btn.dataset.tab;
      renderDetail();
    }}));
    render();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
