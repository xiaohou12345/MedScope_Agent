# ONFH Script Entry Points

This directory contains general MedScope demos plus ONFH-specific experiment
scripts. The ONFH scripts are research/evaluation utilities, not default service
entrypoints. Keep reusable runtime behavior in `agents/`, `llm/`, `tools/`, and
`api/`; keep dataset-specific evaluation glue here.

## Canonical Entry Point

Use `scripts/eval_pipeline.py` as the normal entry point. It intentionally
exposes only the three current original-flow agent routes.

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

1. `real-vlm-agent`: uses the original service diagnosis chain with finding list from real VLM ROI observations.
2. `mock-agent`: uses the original service diagnosis chain with finding list from doctor-reviewed mock mask evidence.
3. `real-vlm-mock-agent`: uses the original service diagnosis chain with a combined finding list from real VLM observations and mock mask evidence.

These routes differ from the repository's main agent path mainly in how the
finding list is obtained, plus the ONFH Xray evidence-mapping adaptation.

Direct script commands are still supported, but new documentation should point
to `scripts/eval_pipeline.py` first.

The detailed code map and default output paths are documented in
`docs/ONFH_EXPERIMENTS.md`.

## Runtime Boundaries

- `llm/model_client.py`, `llm/response_stream.py`, and
  `llm/model_call_logger.py` are reusable route/logging plumbing.
- `tools/vision_prompt_generator.py` is reusable VLM plumbing. Dataset-specific
  ROI crop construction should stay in ONFH scripts, not in this tool.
- `scripts/xray_mask_mock_eval.py` and `scripts/xray_cached_mixed_original_flow_eval.py`
  are the current original-flow evaluation implementations behind the public routes.
- Local outputs should stay under `output/fake/` or external output folders and
  should not be committed.

## Before Changing Shared Code

Run the focused tests that cover the current ONFH-related shared changes:

```bash
/home/guanyandong/miniconda3/bin/python -m unittest \
  tests.test_diagnosis_llm_workflow \
  tests.test_eval_pipeline_entrypoint
```
