# ONFH Experiment Code Map

This branch contains two different kinds of changes:

1. Core MedScope plumbing that should remain reusable across diseases.
2. ONFH-specific experiment scripts used for the 2026-06-08 Xray ROI/VLM evaluation.

Keep those two layers conceptually separate. Most files under `scripts/xray_*.py` and `scripts/eval_*.py`
are cached-evaluation utilities, not default production entrypoints.

## Core Changes

These files affect reusable runtime behavior:

- `llm/model_client.py`
  - Adds OpenAI-compatible Responses API support.
  - Adds optional streaming for Responses via `MEDSCOPE_RESPONSES_STREAM`.
  - Writes model-call audit logs through `llm/model_call_logger.py`.

- `tools/vision_prompt_generator.py`
  - Adds Responses API support for vision calls.
  - Adds optional streaming via `MEDSCOPE_VISION_RESPONSES_STREAM`.
  - Logs image metadata and model-call payloads without storing base64 image data.

- `llm/model_call_logger.py`
  - Central model-call audit logger.
  - Redacts secrets and summarizes base64 image data URLs.
  - Default log directory: `output/fake/model_call_logs`.
  - Override with `MEDSCOPE_MODEL_CALL_LOG_DIR`.
  - Disable with `MEDSCOPE_DISABLE_MODEL_CALL_LOG=1`.

- `llm/response_stream.py`
  - Parses OpenAI-compatible SSE responses.
  - Used by both text and vision clients when the active route needs `stream=true`.

- `agents/diagnosis_agent.py`
  - Narrows blocked negative-language handling so limited Xray observations such as
    "X 光未见明显异常，但仍需 MRI" do not trigger fallback.
  - Keeps hard negative claims such as "无病", "排除", and "无需补充检查" blocked.

- `prompts/diagnosis_agent_prompt.md`
  - Clarifies missing/unassessed evidence language.
  - Allows limited Xray observation only when paired with modality limitation and MRI follow-up.

## Tests To Keep Green

Run these after changing the ONFH or LLM plumbing:

```bash
/home/guanyandong/miniconda3/bin/python -m unittest \
  tests.test_diagnosis_llm_workflow \
  tests.test_eval_pipeline_entrypoint
```

The broader existing test suite is larger and may include environment-dependent
tests. For this branch, the two tests above cover the changed diagnosis
fallback behavior and the ONFH evaluation entrypoint.

## ONFH Evaluation Pipeline

Use the unified entrypoint for normal reproduction:

```bash
python scripts/eval_pipeline.py list
python scripts/eval_pipeline.py run real-vlm-agent
python scripts/eval_pipeline.py run mock-agent
python scripts/eval_pipeline.py run real-vlm-mock-agent
```

The unified entrypoint intentionally exposes only the three current original-flow
agent routes.

The current ONFH evaluation uses cached CSV/JSON outputs under `output/fake`.
PPT/report generation is intentionally kept outside this repository.

Main original-flow routes:

1. Real VLM agent route
   - `scripts/xray_cached_mixed_original_flow_eval.py --mode real-vlm`
   - Finding list source:
     real VLM observations from blinded femoral-head ROI crops.
   - Main cached output:
     `output/fake/xray_34tag_side_mixed_original_flow_20260609/eval_rows.csv`

2. Mock agent route
   - `scripts/xray_mask_mock_eval.py`
   - Finding list source:
     doctor-reviewed Xray mask evidence converted into structured findings.
   - Main cached output:
     `output/fake/original_flow_full_mock_xray_gt_agent_final_20260609_xray3class/side_level_eval.csv`

3. Real VLM + mock agent route
   - `scripts/xray_cached_mixed_original_flow_eval.py --mode mixed`
   - Finding list source:
     real VLM ROI observations plus doctor-reviewed mock mask evidence.
   - Main cached output:
     `output/fake/xray_34tag_side_mixed_original_flow_20260609/eval_rows.csv`

Implementation utilities:

- `scripts/xray_mask_mock_eval.py`
  - Builds mock visual evidence from doctor-reviewed Xray masks.
- `scripts/xray_cached_mixed_original_flow_eval.py`
  - Runs the original service diagnosis chain with real VLM findings, or real VLM plus mock findings.

## Report Interpretation Rules

- `real ROI agent`
  - Input: anonymized ROI crop image.
  - Visual evidence: VLM candidate findings.
  - These findings are **not** doctor GT masks.

- `mock mask agent`
  - Input: doctor-reviewed Xray GT mask converted to structured visual evidence.
  - This estimates a mask-evidence upper bound and should not be described as real VLM performance.

- `real ROI + mask evidence agent`
  - Input: real ROI VLM findings plus doctor-reviewed Xray mask evidence.
  - This is a combination of two evidence sources.

The old PPT builders, whole-image experiments, and candidate-stage rerun scripts
were removed from this repository because they are not part of the ROI-only
evaluation path.
