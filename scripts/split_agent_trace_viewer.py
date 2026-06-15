from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path("output/fake/onfh_xray_six_experiments_20260611")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split an embedded MedScope trace viewer into lazy-loaded case JSON files."
    )
    parser.add_argument("--html", type=Path, default=DEFAULT_ROOT / "trace_viewer.html")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--data-dir", default="trace_viewer_data")
    parser.add_argument("--viewer-filename", default="trace_viewer.html")
    args = parser.parse_args()

    source_html = args.html.resolve()
    root = args.root.resolve()
    payload = _extract_payload(source_html)
    result = write_lazy_viewer(
        payload=payload,
        root=root,
        data_dir_name=args.data_dir,
        viewer_filename=args.viewer_filename,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _extract_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r'<script id="trace-data" type="application/json">(.*?)</script>',
        text,
        re.S,
    )
    if not match:
        raise ValueError(f"trace-data script not found in {path}")
    payload = json.loads(html.unescape(match.group(1)))
    if not isinstance(payload, dict) or not isinstance(payload.get("experiments"), list):
        raise ValueError(f"unexpected trace payload structure in {path}")
    return payload


def write_lazy_viewer(
    *,
    payload: dict[str, Any],
    root: Path,
    data_dir_name: str,
    viewer_filename: str,
) -> dict[str, Any]:
    data_dir = root / data_dir_name
    cases_dir = data_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "experiment_root": payload.get("experiment_root"),
        "index": payload.get("index") or [],
        "experiments": [],
    }
    case_count = 0
    for exp_index, exp in enumerate(payload.get("experiments") or []):
        exp_folder = exp.get("folder") or f"experiment_{exp_index + 1:02d}"
        exp_manifest = {
            "folder": exp_folder,
            "readme": exp.get("readme") or "",
            "metrics": exp.get("metrics"),
            "summary": exp.get("summary"),
            "config": exp.get("config") or {},
            "rows_csv": exp.get("rows_csv") or "",
            "case_count": len(exp.get("cases") or []),
            "cases": [],
        }
        for case_index, case in enumerate(exp.get("cases") or []):
            case_file = f"{_safe_name(exp_folder)}__{case_index + 1:03d}.json"
            case_path = cases_dir / case_file
            case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            summary = case.get("summary") if isinstance(case, dict) else {}
            config = case.get("config") if isinstance(case, dict) else {}
            row = case.get("row") if isinstance(case, dict) else {}
            exp_manifest["cases"].append(
                {
                    "folder": case.get("folder") if isinstance(case, dict) else case_file,
                    "path": case.get("path") if isinstance(case, dict) else "",
                    "summary": _compact_dict(summary),
                    "config": _compact_dict(config),
                    "row": _compact_row(row),
                    "event_count": len(case.get("events") or []) if isinstance(case, dict) else 0,
                    "llm_call_count": len(case.get("llm_calls") or []) if isinstance(case, dict) else 0,
                    "data_url": f"{data_dir_name}/cases/{case_file}",
                }
            )
            case_count += 1
        manifest["experiments"].append(exp_manifest)

    (data_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    viewer = root / viewer_filename
    viewer.write_text(_render_lazy_html(data_dir_name=data_dir_name), encoding="utf-8")
    return {
        "viewer": str(viewer),
        "manifest": str(data_dir / "manifest.json"),
        "case_count": case_count,
        "experiment_count": len(manifest["experiments"]),
    }


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "case"


def _compact_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keep = [
        "experiment_name",
        "source",
        "case_id",
        "trace_id",
        "image_path",
        "gt_xray_stage",
        "agent_final_stage",
        "correct",
        "evaluation",
    ]
    return {key: value.get(key) for key in keep if key in value}


def _compact_row(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keep = [
        "case_id",
        "patient_id",
        "image_id",
        "side",
        "gt_xray_stage",
        "agent_final_stage",
        "correct",
        "visual_stage",
    ]
    return {key: value.get(key) for key in keep if key in value}


def _render_lazy_html(*, data_dir_name: str) -> str:
    manifest_url = f"{data_dir_name}/manifest.json"
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
    header h1 {{ font-size: 17px; margin: 0; white-space: nowrap; }}
    input, select, button {{
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text);
      border-radius: 6px;
      height: 34px;
      padding: 0 10px;
      font: inherit;
    }}
    button {{ cursor: pointer; background: #f9fafb; }}
    .layout {{
      display: grid;
      grid-template-columns: 320px minmax(420px, 1fr) 48%;
      min-height: calc(100vh - 56px);
    }}
    aside, main, section {{ min-width: 0; border-right: 1px solid var(--border); }}
    aside {{
      background: var(--panel);
      padding: 12px;
      overflow: auto;
      max-height: calc(100vh - 56px);
      position: sticky;
      top: 56px;
    }}
    main, section {{ padding: 14px; overflow: auto; max-height: calc(100vh - 56px); }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      margin-bottom: 10px;
    }}
    .case, .event, .llm-call {{ cursor: pointer; }}
    .case.active, .event.active, .llm-call.active {{
      border-color: var(--accent);
      box-shadow: inset 3px 0 0 var(--accent);
    }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
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
    .event-title {{ display: flex; justify-content: space-between; gap: 8px; font-weight: 600; }}
    .action-row {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }}
    .mini-btn {{
      height: 26px;
      padding: 0 8px;
      font-size: 12px;
      border-radius: 5px;
    }}
    .flow-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }}
    .section-title {{
      margin: 14px 0 10px;
      font-weight: 700;
    }}
    .kv {{ display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: 6px 10px; align-items: start; }}
    .kv div:nth-child(odd) {{ color: var(--muted); font-size: 12px; }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: var(--code);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      line-height: 1.45;
    }}
    .tabs {{ display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }}
    .tabs button.active {{ border-color: var(--accent); color: var(--accent); background: #eef8fb; }}
    .muted {{ color: var(--muted); }}
    .small {{ font-size: 12px; }}
  </style>
</head>
<body>
  <header>
    <h1>MedScope Trace Viewer</h1>
    <select id="experimentSelect"></select>
    <input id="searchInput" placeholder="搜索 case / patient / GT / Pred" style="min-width: 300px; flex: 1;" />
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
  <script>
    const MANIFEST_URL = {json.dumps(manifest_url)};
    const state = {{ data: null, expIndex: 0, caseIndex: 0, eventIndex: 0, llmIndex: 0, tab: 'config', query: '', caseCache: new Map(), currentCase: null }};
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    const jsonText = (v) => JSON.stringify(v ?? null, null, 2);
    const lowerJson = (obj) => JSON.stringify(obj ?? '', null, 0).toLowerCase();

    function selectedExperiment() {{ return state.data?.experiments?.[state.expIndex] || state.data?.experiments?.[0]; }}
    function metricFor(folder) {{ return (state.data?.index || []).find(row => row.folder === folder) || {{}}; }}
    function filteredCases() {{
      const exp = selectedExperiment();
      const q = state.query.trim().toLowerCase();
      return (exp?.cases || []).map((c, i) => [c, i]).filter(([c]) => !q || lowerJson(c).includes(q));
    }}
    function selectedCaseMeta() {{
      const cases = filteredCases();
      return cases[state.caseIndex]?.[0] || cases[0]?.[0] || null;
    }}
    async function loadSelectedCase() {{
      const meta = selectedCaseMeta();
      if (!meta) {{
        state.currentCase = null;
        return null;
      }}
      if (state.caseCache.has(meta.data_url)) {{
        state.currentCase = state.caseCache.get(meta.data_url);
        return state.currentCase;
      }}
      $('detailPane').innerHTML = '<div class="card muted">Loading case JSON...</div>';
      const response = await fetch(meta.data_url, {{ cache: 'no-store' }});
      if (!response.ok) throw new Error(`Failed to load ${{meta.data_url}}: ${{response.status}}`);
      const data = await response.json();
      state.caseCache.set(meta.data_url, data);
      state.currentCase = data;
      return data;
    }}
    function selectedEvent() {{
      const c = state.currentCase;
      return c?.events?.[state.eventIndex] || c?.events?.[0] || null;
    }}
    function selectedLlmCall() {{
      const c = state.currentCase;
      return c?.llm_calls?.[state.llmIndex] || c?.llm_calls?.[0] || null;
    }}
    async function render() {{
      if (!state.data) {{
        $('detailPane').innerHTML = '<div class="card muted">Loading manifest...</div>';
        const response = await fetch(MANIFEST_URL, {{ cache: 'no-store' }});
        state.data = await response.json();
      }}
      renderExperimentSelect();
      renderCaseList();
      try {{
        await loadSelectedCase();
      }} catch (error) {{
        $('caseHeader').innerHTML = '';
        $('eventList').innerHTML = '';
        $('detailPane').innerHTML = `<div class="card"><strong>Load error</strong><pre>${{esc(error.stack || error.message || error)}}</pre></div>`;
        return;
      }}
      renderEventList();
      renderDetail();
    }}
    function renderExperimentSelect() {{
      const sel = $('experimentSelect');
      if (!sel.dataset.ready) {{
        (state.data.experiments || []).forEach((exp, i) => {{
          const opt = document.createElement('option');
          opt.value = i;
          opt.textContent = `${{exp.folder}} (${{exp.case_count}} cases)`;
          sel.appendChild(opt);
        }});
        sel.addEventListener('change', () => {{
          state.expIndex = Number(sel.value);
          state.caseIndex = 0; state.eventIndex = 0; state.llmIndex = 0; state.currentCase = null;
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
          <div class="small muted" style="margin-top:6px;">Case detail is lazy-loaded on click.</div>
        </div>`;
      const cases = filteredCases();
      if (state.caseIndex >= cases.length) state.caseIndex = 0;
      $('caseList').innerHTML = cases.map(([c], i) => {{
        const s = c.summary || {{}};
        const ok = String(s.correct ?? s.evaluation?.correct ?? c.row?.correct ?? '').toLowerCase() === 'true';
        const gt = s.gt_xray_stage ?? s.evaluation?.gt_xray_stage ?? c.row?.gt_xray_stage ?? '';
        const pred = s.agent_final_stage ?? s.evaluation?.agent_final_stage ?? c.row?.agent_final_stage ?? '';
        return `<div class="card case ${{i === state.caseIndex ? 'active' : ''}}" data-case="${{i}}">
          <strong>${{esc(c.folder)}}</strong>
          <div class="meta">
            <span class="pill ${{ok ? 'good' : 'bad'}}">${{ok ? 'correct' : 'not correct'}}</span>
            <span class="pill">GT ${{esc(gt)}}</span>
            <span class="pill">Pred ${{esc(pred)}}</span>
            <span class="pill">events ${{c.event_count || 0}}</span>
            <span class="pill">LLM ${{c.llm_call_count || 0}}</span>
          </div>
        </div>`;
      }}).join('') || '<div class="muted">No cases matched.</div>';
      document.querySelectorAll('.case').forEach(el => el.addEventListener('click', () => {{
        state.caseIndex = Number(el.dataset.case);
        state.eventIndex = 0; state.llmIndex = 0; state.currentCase = null;
        render();
      }}));
    }}
    function renderEventList() {{
      const c = state.currentCase;
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
      const eventCard = (e, i) => `
        <div class="card event ${{i === state.eventIndex ? 'active' : ''}}" data-select-event="${{i}}" data-tab="output">
          <div class="event-title"><span>${{esc(e.order)}}. ${{esc(e.agent)}}</span><span class="muted">${{esc(eventRole(e))}} · ${{esc(e.event)}}</span></div>
          <div class="small muted">${{esc(e.file)}}</div>
          <div class="action-row">
            <button class="mini-btn" data-select-event="${{i}}" data-tab="output">查看 Output</button>
            <button class="mini-btn" data-select-event="${{i}}" data-tab="input">查看 Input</button>
          </div>
        </div>`;
      const agentHtml = events.map((e, i) => [e, i]).filter(([e]) => eventGroup(e) === 'agent').map(([e, i]) => eventCard(e, i)).join('');
      const evalHtml = events.map((e, i) => [e, i]).filter(([e]) => eventGroup(e) === 'evaluation').map(([e, i]) => eventCard(e, i)).join('');
      const auditHtml = events.map((e, i) => [e, i]).filter(([e]) => eventGroup(e) === 'audit').map(([e, i]) => eventCard(e, i)).join('');
      const llmCalls = c.llm_calls || [];
      if (state.llmIndex >= llmCalls.length) state.llmIndex = 0;
      const llmHtml = `<div class="card"><strong>LLM Calls</strong><div class="small muted">选择后在右侧查看模型输入和输出。</div></div>
        ${{llmCalls.map((call, i) => `
          <div class="card llm-call ${{i === state.llmIndex ? 'active' : ''}}" data-select-llm="${{i}}" data-tab="llm_input">
            <div class="event-title"><span>${{i + 1}}. ${{esc(call.task)}}</span><span class="muted">${{esc(call.status)}}</span></div>
            <div class="small muted">${{esc(call.model)}} · ${{esc(call.file)}}</div>
            <div class="action-row">
              <button class="mini-btn" data-select-llm="${{i}}" data-tab="llm_input">查看 Input</button>
              <button class="mini-btn" data-select-llm="${{i}}" data-tab="llm_output">查看 Output</button>
            </div>
          </div>`).join('') || '<div class="card muted">No LLM calls recorded for this case.</div>'}}`;
      $('eventList').innerHTML = `
        <div class="card"><strong>Agent Flow</strong><div class="small muted">正式诊断链路中的业务 agent。</div></div>
        ${{agentHtml || '<div class="card muted">No agent events recorded.</div>'}}
        <div class="section-title">Evaluation</div>
        ${{evalHtml || '<div class="card muted">No evaluation events recorded.</div>'}}
        <div class="section-title">Audit Logs</div>
        <div class="card small muted">ModelCallLogger 是 prompt/response 审计记录器，不参与诊断决策。</div>
        ${{auditHtml || '<div class="card muted">No audit events recorded.</div>'}}
        ${{llmHtml}}`;
    }}
    function renderDetail() {{
      document.querySelectorAll('.tabs button').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === state.tab));
      const c = state.currentCase;
      const e = selectedEvent();
      const call = selectedLlmCall();
      if (!c) {{
        $('detailPane').innerHTML = '<div class="muted">No case selected.</div>';
      }} else if (state.tab === 'config') {{
        $('detailPane').innerHTML = renderConfig(selectedExperiment(), c);
      }} else if (state.tab === 'llm_input') {{
        $('detailPane').innerHTML = call ? renderLlmInput(call) : '<div class="muted">No LLM call selected.</div>';
      }} else if (state.tab === 'llm_output') {{
        $('detailPane').innerHTML = call ? renderLlmOutput(call) : '<div class="muted">No LLM call selected.</div>';
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
    function eventGroup(e) {{
      const agent = String(e?.agent || '');
      if (agent === 'ModelCallLogger') return 'audit';
      if (agent === 'EvaluationRunner') return 'evaluation';
      return 'agent';
    }}
    function eventRole(e) {{
      const group = eventGroup(e);
      if (group === 'audit') return 'audit logger';
      if (group === 'evaluation') return 'evaluation';
      return 'agent';
    }}
    function renderConfig(exp, c) {{
      const cfg = exp.config || {{}};
      const ccfg = c.config || {{}};
      const metric = metricFor(exp.folder);
      const flowItems = ccfg.agent_flow || [];
      const flowCard = (item, idx) => `<div class="card event ${{idx === state.eventIndex ? 'active' : ''}}" data-select-event="${{idx}}" data-tab="output"><strong>${{esc(item.order)}}. ${{esc(item.agent)}}</strong><div class="small muted">${{esc(eventRole(item))}} · ${{esc(item.event)}}</div><div class="action-row"><button class="mini-btn" data-select-event="${{idx}}" data-tab="output">查看 Output</button><button class="mini-btn" data-select-event="${{idx}}" data-tab="input">查看 Input</button></div></div>`;
      const flow = flowItems.map((item, idx) => [item, idx]).filter(([item]) => eventGroup(item) === 'agent').map(([item, idx]) => flowCard(item, idx)).join('');
      const evaluationFlow = flowItems.map((item, idx) => [item, idx]).filter(([item]) => eventGroup(item) === 'evaluation').map(([item, idx]) => flowCard(item, idx)).join('');
      const auditFlow = flowItems.map((item, idx) => [item, idx]).filter(([item]) => eventGroup(item) === 'audit').map(([item, idx]) => flowCard(item, idx)).join('');
      const llmFlow = (ccfg.llm_flow || []).map((item, idx) => `<div class="card llm-call ${{idx === state.llmIndex ? 'active' : ''}}" data-select-llm="${{idx}}" data-tab="llm_input"><strong>${{esc(item.order)}}. ${{esc(item.task)}}</strong><div class="meta"><span class="pill">${{esc(item.model)}}</span><span class="pill">${{esc(item.status)}}</span><span class="pill">${{esc(item.route || '')}}</span><span class="pill">${{esc(item.duration_ms || '')}} ms</span></div><div class="action-row"><button class="mini-btn" data-select-llm="${{idx}}" data-tab="llm_input">查看 Input</button><button class="mini-btn" data-select-llm="${{idx}}" data-tab="llm_output">查看 Output</button></div></div>`).join('') || '<div class="card muted">No LLM calls recorded.</div>';
      return `<div class="card"><strong>Experiment Config</strong><div class="kv" style="margin-top:10px;">
        <div>experiment</div><div>${{esc(cfg.experiment || metric.experiment || exp.folder)}}</div>
        <div>visual evidence</div><div>${{esc(cfg.visual_evidence_source || '')}}</div>
        <div>diagnosis LLM</div><div>${{esc(cfg.diagnosis_llm)}}</div>
        <div>primary metric</div><div>${{esc(cfg.primary_metric || '')}}</div>
        <div>rows csv</div><div>${{esc(cfg.rows_csv || '')}}</div>
      </div></div>
      <div class="card"><strong>Case Result</strong><div class="kv" style="margin-top:10px;">
        <div>case id</div><div>${{esc(ccfg.case_id || '')}}</div>
        <div>trace id</div><div>${{esc(ccfg.trace_id || '')}}</div>
        <div>source</div><div>${{esc(ccfg.source || '')}}</div>
        <div>image path</div><div>${{esc(ccfg.image_path || '')}}</div>
        <div>GT Xray stage</div><div>${{esc(ccfg.gt_xray_stage || '')}}</div>
        <div>agent final stage</div><div>${{esc(ccfg.agent_final_stage || '')}}</div>
        <div>correct</div><div>${{esc(ccfg.correct)}}</div>
      </div></div>
      <div class="card"><strong>Agent Flow</strong><div class="small muted">正式诊断链路中的业务 agent。</div></div><div class="flow-grid">${{flow || '<div class="muted">No agent events recorded.</div>'}}</div>
      <div class="card"><strong>Evaluation</strong></div><div class="flow-grid">${{evaluationFlow || '<div class="muted">No evaluation events recorded.</div>'}}</div>
      <div class="card"><strong>Audit Logs</strong><div class="small muted">ModelCallLogger 是 prompt/response 审计记录器，不参与诊断决策。</div></div><div class="flow-grid">${{auditFlow || '<div class="muted">No audit events recorded.</div>'}}</div>
      <div class="card"><strong>LLM Flow</strong><div class="small muted">具体 prompt/response 用 LLM Input / LLM Output tab 查看。</div></div><div class="flow-grid">${{llmFlow}}</div>`;
    }}
    function renderLlmInput(call) {{
      const obj = call.json || {{}};
      const input = {{ task: call.task, model: call.model, status: call.status, route: obj.route, endpoint: obj.endpoint, image: obj.image, messages: obj.messages, request_payload: obj.request_payload }};
      return `<div class="card"><strong>${{esc(call.task)}} · Input</strong><div class="small muted">${{esc(call.file)}}</div></div><pre>${{esc(jsonText(input))}}</pre>`;
    }}
    function renderLlmOutput(call) {{
      const obj = call.json || {{}};
      const output = {{ task: call.task, model: call.model, status: call.status, duration_ms: obj.duration_ms, retry_count: obj.retry_count, errors: obj.errors, response_content: obj.response_content, response_raw_summary: obj.response_raw_summary }};
      return `<div class="card"><strong>${{esc(call.task)}} · Output</strong><div class="small muted">${{esc(call.file)}}</div></div><pre>${{esc(jsonText(output))}}</pre>`;
    }}
    $('searchInput').addEventListener('input', (event) => {{
      state.query = event.target.value;
      state.caseIndex = 0; state.eventIndex = 0; state.llmIndex = 0; state.currentCase = null;
      render();
    }});
    $('clearSearch').addEventListener('click', () => {{
      $('searchInput').value = '';
      state.query = '';
      state.caseIndex = 0; state.eventIndex = 0; state.llmIndex = 0; state.currentCase = null;
      render();
    }});
    document.querySelectorAll('.tabs button').forEach(btn => btn.addEventListener('click', () => {{
      state.tab = btn.dataset.tab;
      renderDetail();
    }}));
    document.addEventListener('click', (event) => {{
      const eventTarget = event.target.closest('[data-select-event]');
      if (eventTarget) {{
        state.eventIndex = Number(eventTarget.dataset.selectEvent);
        state.tab = eventTarget.dataset.tab || 'output';
        renderEventList();
        renderDetail();
        return;
      }}
      const llmTarget = event.target.closest('[data-select-llm]');
      if (llmTarget) {{
        state.llmIndex = Number(llmTarget.dataset.selectLlm);
        state.tab = llmTarget.dataset.tab || 'llm_input';
        renderEventList();
        renderDetail();
      }}
    }});
    render();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
