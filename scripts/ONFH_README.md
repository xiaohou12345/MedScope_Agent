# ONFH Script Entry Points

This directory contains general MedScope demos plus ONFH-specific experiment
scripts. The ONFH scripts are research/evaluation utilities, not default service
entrypoints. Keep reusable runtime behavior in `agents/`, `llm/`, `tools/`, and
`api/`; keep dataset-specific evaluation glue here.

## Canonical Entry Point

Use `scripts/eval_pipeline.py` as the normal entry point. It intentionally
exposes only the three agent routes. The lower-level `xray_*.py` and
`eval_*.py` files remain available for debugging and cached-result
reproduction, but they should be treated as implementation steps.

List the available steps:

```bash
python scripts/eval_pipeline.py list
```

Run one step:

```bash
python scripts/eval_pipeline.py run real-vlm-agent
python scripts/eval_pipeline.py run mock-agent
python scripts/eval_pipeline.py run real-vlm-mock-agent
```

Run the standard ordered pipeline:

```bash
python scripts/eval_pipeline.py all
```

Pass-through arguments after the subcommand are forwarded to the underlying
script. For example:

```bash
python scripts/eval_pipeline.py run real-vlm-agent -- --limit 3
```

## Current Stable ONFH Path

Use this path when reproducing the 2026-06-08 Xray ROI/VLM/agent comparison.

The stable path is now exposed as three `scripts/eval_pipeline.py` steps:

1. `real-vlm-agent`: uses the repository's agent route with finding list from real VLM ROI observations.
2. `mock-agent`: uses the same candidate diagnosis layer with finding list from doctor-reviewed mock mask evidence.
3. `real-vlm-mock-agent`: uses the agent route with a combined finding list from real VLM observations and mock mask evidence.

These routes differ from the repository's main agent path mainly in how the
finding list is obtained, plus the branch-local diagnosis/fallback fixes.

Direct script commands are still supported, but new documentation should point
to `scripts/eval_pipeline.py` first.

The detailed code map and default output paths are documented in
`docs/ONFH_EXPERIMENTS.md`.

## Diagnostic Or Historical ONFH Scripts

These files are useful for debugging or reproducing earlier variants, but they
are not the recommended clean pipeline:

- `debug_vision_model_route.py`
- `export_mock_agent_trace_log.py`
- `test_dmx_route.py`

The old PPT builders, whole-image experiments, and intermediate candidate-stage
rerun scripts were removed from this repository because they are not part of the
current ROI-only evaluation logic.

## Runtime Boundaries

- `agents/candidate_diagnosis_agent.py` is an ONFH-only experimental wrapper. It does
  not replace `agents/diagnosis_agent.py`.
- `llm/model_client.py`, `llm/response_stream.py`, and
  `llm/model_call_logger.py` are reusable route/logging plumbing.
- `tools/vision_prompt_generator.py` is reusable VLM plumbing. Dataset-specific
  ROI crop construction should stay in ONFH scripts, not in this tool.
- `scripts/xray_mask_mock_eval.py`, `scripts/xray_roi_mock_eval.py`,
  `scripts/xray_roi_vlm_eval.py`, and `scripts/eval_summary.py` are lower-level
  preparation or reporting utilities, not public experiment routes.
- Local outputs should stay under `output/fake/` or external output folders and
  should not be committed.

## Before Changing Shared Code

Run the focused tests that cover the current ONFH-related shared changes:

```bash
/home/guanyandong/miniconda3/bin/python -m unittest \
  tests.test_diagnosis_llm_workflow \
  tests.test_candidate_diagnosis_agent
```
