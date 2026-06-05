# MedScope Agent

MedScope Agent is an experimental medical AI agent framework for guideline-aware, multimodal clinical evidence workflows. It is built around one principle: image analysis, guideline skill loading, diagnostic reasoning, and audit memory should be separated by explicit contracts, so that the system can explain what evidence was used, what evidence was missing, and what must not be inferred.

This repository is a research prototype. It is not a medical device and must not be used for real clinical diagnosis or treatment decisions.

中文说明见 [README.zh-CN.md](README.zh-CN.md).

## What This Project Does

MedScope turns a patient message plus medical image input into a traceable evidence workflow:

```text
Patient / frontend
  -> Clinical Orchestrator
  -> Skill Gateway / Skill Builder
  -> Vision Evidence Agent
  -> Diagnosis Reasoning Agent
  -> Memory / Audit Layer
  -> Runtime Gateway Trace / Stop Hooks / Candidate Queue
```

The current MVP supports:

- Guideline-based disease skills in `skills/`.
- Automatic skill routing from patient text, symptoms, and image path clues.
- Visual evidence generation from either reference masks, VLM-localized regions, or MedSAM2-compatible segmentation runners.
- Evidence-bounded diagnosis reports that consume structured visual evidence instead of raw pixels.
- Four memory scopes: `patient_memory`, `image_memory`, `skill_memory`, and `reasoning_memory`.
- Follow-up QA constrained by the saved evidence bundle.
- A lightweight web UI with upload, thinking state, visual evidence, diagnosis report, evidence bundle, and memory/audit views.
- Baseline prompt workflows for comparing direct LLM/Codex-style reasoning against the evidence-bounded pipeline.

## Architecture

The project is best described as a two-layer architecture rather than a flat list of agents.

### Clinical Evidence Pipeline

- `Clinical Orchestrator`: implemented by `agents/gaodoctor_agent.py`. It is the single patient-facing entry point and coordinates routing, skill selection, visual evidence, diagnosis, and QA.
- `Vision Evidence Agent`: implemented by `agents/vision_agent.py` plus visual tools. It localizes, segments, measures, and returns structured visual evidence. It does not produce the final diagnosis.
- `Diagnosis Reasoning Agent`: implemented by `agents/diagnosis_agent.py`. It consumes guideline skills and evidence bundles, then generates a diagnosis report with safety checks.
- `Skill Builder / Guideline Component`: implemented mainly under `tools/skill_builder_tool.py` and guideline tools. It loads existing skills or builds candidate guideline/hypothesis skills.
- `Memory / Audit Layer`: implemented by `memory/memory_manager.py`. It persists evidence, reports, runtime traces, replay data, and QA history.

### Agentic Runtime / Evidence Gateway

The lower layer behaves like a controlled runtime for medical evidence tasks:

- `Skill Gateway`: distributes guideline skills, visual protocols, and skill metadata.
- `Shared Artifact Workspace`: stores uploaded images, masks, overlays, comparison images, evidence bundles, and audit files.
- `Contract Guards`: enforce schema and policy boundaries in `contracts/medical_contracts.py`.
- `Tool Router`: maps skill visual protocols to VLM localization, MedSAM2, mask readers, measurement tools, or guideline collectors.
- `Stop Hooks / Reflection Hooks`: produce read-only warnings, next actions, candidate memories, and candidate skill patches.
- `Candidate Validation Gate`: blocks unreviewed candidate rules from becoming formal medical skills.

See:

- [docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md](docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md)
- [docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md](docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md)
- [docs/CURRENT_MVP_DEMO_RUNBOOK_20260605.md](docs/CURRENT_MVP_DEMO_RUNBOOK_20260605.md)
- [docs/FHN_REAL_VLM_VALIDATION_20260604.md](docs/FHN_REAL_VLM_VALIDATION_20260604.md)
- [docs/architecture/boundaries.md](docs/architecture/boundaries.md)
- [docs/DUAL_PATH_AGENT_FRAMEWORK.md](docs/DUAL_PATH_AGENT_FRAMEWORK.md)
- [docs/AGENT_FLOW.zh-CN.md](docs/AGENT_FLOW.zh-CN.md)

## Repository Layout

```text
agents/       Clinical orchestrator, vision, diagnosis, and report components
api/          HTTP API and stable service boundary
contracts/    Typed contracts between agents, tools, memory, and reports
docs/         Architecture notes, API routing, dataset and MedSAM2 setup notes
llm/          OpenAI-compatible model client and prompt runner
memory/       JSON memory store, evidence bundles, audit and runtime traces
prompts/      Diagnosis, orchestrator, and baseline prompt templates
scripts/      Demos, evaluation scripts, dataset probes, MedSAM2 wrappers
skills/       Disease skills with guideline sources and visual protocols
tests/        Unit and integration tests
tools/        Guideline, visual, segmentation, measurement, and routing tools
web/          Static frontend
```

Generated outputs and local medical data are intentionally ignored by git:

- `output/`, `outputs/`
- `data/external/`, `data/cases/`, `data/images/`, `data/masks/`, `data/overlays/`
- DICOM/NIfTI files and model weights
- `.env*` local secret files

## Supported Skills

Current formal skill files:

- `skills/femoral_head_necrosis.yaml`
- `skills/diffuse_glioma_brats.yaml`
- `skills/idiopathic_pulmonary_fibrosis_hrct.yaml`
- `skills/pneumonia_chest_xray.yaml`

The `.yaml` extension is used for skill files, but the current files are JSON-compatible payloads loaded by the standard `json` module.

## Requirements

Recommended environment:

- Python 3.10+
- Core install: Pillow
- Optional vision workflows: NumPy and nibabel
- Optional real segmentation: PyTorch and an external MedSAM2 checkout

Install the project in editable mode for local development:

```bash
python -m pip install -e .
```

Install the optional vision dependencies for NIfTI/BraTS, image metrics, and demo scripts:

```bash
python -m pip install -e ".[vision]"
```

For the full local test/demo environment:

```bash
python -m pip install -e ".[dev]"
```

## Model and Runtime Configuration

Model routing is centralized in [docs/API_ROUTE_LOG.md](docs/API_ROUTE_LOG.md). Agent code should not directly know provider-specific API details.

Required environment variables for real model calls:

```bash
export DMX_API_KEY="..."
# or
export KY_API_KEY="..."
```

MedSAM2 is optional and configured through environment variables:

```bash
export MEDSAM2_REPO_PATH="/path/to/MedSAM2"
export MEDSAM2_COMMAND_TEMPLATE='python /path/to/runner.py --image {image_path} --output {output_mask_path} --prompt-json {prompt_json}'
export MEDSAM2_TIMEOUT_SECONDS=600
```

See [docs/datasets/medsam2_runner_config.md](docs/datasets/medsam2_runner_config.md).

## Run the Web App

Check the runtime first. MedScope requires Python 3.10+:

```bash
python -m scripts.check_runtime_environment
```

Start the local HTTP server:

```bash
python -m api.http_server --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Deployment readiness check:

```bash
curl http://127.0.0.1:8000/v1/readiness
```

This endpoint performs offline checks only. It reports the active model route,
whether the expected API key environment variable is present, MedSAM2 runner
configuration status, writable output/upload directories, and Python runtime
version. It does not call the model API and does not return secret values.

## CLI Usage

Run the stable service entry point:

```bash
python app.py \
  --image /path/to/image.png \
  --message "left hip pain for three months" \
  --symptom "hip pain" \
  --risk-factor "alcohol use"
```

For an explicit disease skill:

```bash
python app.py \
  --image /path/to/image.png \
  --message "evaluate femoral head necrosis on this AP pelvis X-ray" \
  --disease-key femoral_head_necrosis
```

## HTTP API

Primary diagnosis endpoint:

```bash
curl -X POST http://127.0.0.1:8000/v1/medscope \
  -H "Content-Type: application/json" \
  -d '{
    "patient_message": "Please evaluate this hip X-ray.",
    "image_path": "/path/to/image.png",
    "patient_info": {
      "age": 45,
      "sex": "male",
      "symptoms": ["hip pain"]
    }
  }'
```

Other useful routes:

- `GET /health`
- `GET /v1/readiness`
- `POST /v1/upload?filename=image.png`
- `GET /v1/skills`
- `GET /v1/skills/{skill_key}`
- `POST /v1/skills/{skill_key}/review-draft`
- `GET /v1/memory/cases`
- `GET /v1/memory/cases/{case_id}`
- `GET /v1/memory/cases/{case_id}/evidence-bundle`
- `GET /v1/memory/cases/{case_id}/audit`
- `GET /v1/demo/public-safe`
- `POST /v1/demo/public-safe/qa`
- `GET /v1/demo/standard`
- `POST /v1/baseline/image-prompt-skill`

## Useful Demos and Evaluations

Standard end-to-end demo:

```bash
python -m scripts.end_to_end_demo --suite
```

API readiness check:

```bash
python -m scripts.api_smoke_test
```

Evidence-bounded reasoning evaluation:

```bash
python -m scripts.evidence_bounded_reasoning_eval
```

Baseline prompt evaluation:

```bash
python -m scripts.baseline_reasoning_eval
```

Image + prompt + skill baseline:

```bash
python -m scripts.image_prompt_skill_baseline \
  --image /path/to/image.png \
  --message "evaluate this image" \
  --disease-key femoral_head_necrosis \
  --output-dir output/real/Codex工作流基线/my_case
```

This is the reusable three-level Codex/VLM workflow. It runs `simple_prompt`,
`workflow_prompt`, and `fewshot_prompt` on the same image, prompt, and disease
skill, then writes:

- `image_prompt_skill_baseline.json`: raw three-level outputs and metrics.
- `image_prompt_skill_baseline.md`: compact comparison table.
- `中文结论.md`: Chinese conclusion, level explanations, and boundary versus
  the MedScope Agent pipeline.

Public-safe MVP suite for fresh clones:

```bash
python -m scripts.prepare_public_demo_fixture --suite \
  --output-dir output/fake/public_safe_demo_suite
```

Generate only the public-safe synthetic fixture:

```bash
python -m scripts.prepare_public_demo_fixture \
  --output-dir output/fake/public_demo_fixture
```

The suite writes a synthetic, non-patient hip X-ray-like PNG and deterministic
service artifacts for response, evidence bundle, memory audit, and follow-up QA.
Use it to test upload, routing, and the FHN skill path without private
DICOM/NIfTI files. It is not a clinical image or a segmentation benchmark.
It does not prove lesion detection quality.
After starting the HTTP server, the same suite is available at
`GET /v1/demo/public-safe`. The interactive frontend also includes a
`运行 Public-safe MVP 样例` button that runs this endpoint and renders the
diagnosis report, visual evidence, evidence bundle, and memory audit directly.
Follow-up QA for this demo uses `POST /v1/demo/public-safe/qa`, so it stays
bounded to the generated demo artifact instead of live case memory.

No-mask visual pipeline:

```bash
python -m scripts.no_mask_skill_visual_pipeline_demo \
  --image /path/to/xray.png \
  --message "evaluate femoral head necrosis"
```

FHN real VLM multi-view validation dry run:

```bash
python -m scripts.fhn_real_vlm_multiview_demo \
  --ap-image /path/to/ap_pelvis.png \
  --lateral-image /path/to/lateral.png \
  --output-dir output/real/fhn_real_vlm_validation_demo \
  --dry-run
```

BraTS visual test line:

```bash
python -m scripts.brats_vision_test_line
```

## Testing

Run the full test suite:

```bash
python -m unittest discover -v
```

Latest verified local status:

```text
Ran 434 tests in 59.537s
OK
```

Frontend syntax check:

```bash
node --check web/app.js
```

## Current Review

Strengths:

- The core clinical boundary is clear: the diagnosis agent consumes structured evidence and does not inspect raw pixels.
- The skill contract explicitly separates `guideline_based` skills from `data_mined_hypothesis` skills.
- The memory layer is useful for replay, QA, audit, and evidence-bundle inspection.
- The visual pipeline already supports multiple modes: reference masks, VLM-only observations, VLM-plus-segmenter candidates, and MedSAM2-compatible runners.
- Visual backends declare interface contracts for VLM-only observation, VLM-plus-segmenter candidate masks, and specialist segmenters.
- `benchmarks/segmentation/` separates disease-specific segmentation validation from the web demo, supports generic binary lesion-mask Dice/IoU, and reports metric-gate pass/fail status for metric-ready cases.
- The test suite is broad for an MVP and covers contracts, routing, memory, visual protocols, HTTP endpoints, and safety guards.

Important limitations:

- Real segmentation quality is not solved by the framework itself. MedSAM2 and VLM localization are routed and audited, but disease-specific segmentation quality still needs model validation.
- Several demos depend on ignored local artifacts under `output/` or `data/external/`.
- Dependency groups are now declared in `pyproject.toml`; there is still no lockfile, so exact reproducibility across machines is not pinned.
- Skill review and candidate promotion are intentionally blocked from updating formal skills automatically.
- The project is a research prototype, not a clinically validated diagnostic system.
- Current goal closure explicitly defers real FHN data, real masks, and a metric-ready real benchmark until those data are available. See [docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md](docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md).

Recommended next engineering steps:

1. Close the current MVP goal around architecture clarity, patient-facing report/QA behavior, evidence bundle audit, and benchmark infrastructure.
2. Keep the public-safe HTTP/frontend demo as the smoke gate for future report, QA, and memory-audit UI changes.
3. After real FHN labeled data and masks are obtained, add benchmark cases to `benchmarks/segmentation/` with `evaluator_type: binary_mask` and manifest `metric_gates`.
4. Add a lockfile or pinned environment export if exact deployment reproducibility becomes necessary.
5. Keep specialist model integration behind the visual backend contract and quality gate.
6. Keep all clinical rule updates behind review and validation gates.

## Safety and Privacy

- Do not commit API keys, `.env.local`, raw DICOM files, NIfTI files, model weights, or patient case traces.
- Generated clinical outputs are audit artifacts, not medical advice.
- Missing evidence must be represented as missing or unassessed, never as negative.
- Candidate findings from VLM or segmentation models should be treated as candidate evidence until reviewed or validated.
