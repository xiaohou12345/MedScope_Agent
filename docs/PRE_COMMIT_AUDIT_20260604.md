# Pre-Commit Audit: FHN Evidence Protocol MVP

Date: 2026-06-04

Current branch:

```text
features/hsh
```

## Purpose

This audit records what should be included in the next commit for the FHN Evidence Protocol MVP and what should remain local-only.

The main goal of the commit is:

> Add a femoral-head-necrosis-centered evidence protocol MVP that connects skill routing, visual execution strategy, structured evidence bundles, bounded diagnosis reasoning, multi-image input, memory audit, and frontend QA/report cleanup.

## Recommended Commit Title

```text
feat: add FHN evidence protocol MVP
```

## Files That Should Be Included

### Project Entry And Documentation

- `README.md`
- `docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md`
- `docs/PRE_COMMIT_AUDIT_20260604.md`
- `goalnew.md`

Reason:

- README points GitHub readers to the current FHN MVP phase.
- The FHN MVP document is the git-tracked version of the local `output/real` phase report.
- This audit records commit boundaries and prevents ignored local artifacts from being confused with commit contents.
- `goalnew.md` preserves the project decision log.

### Core Agent Code

- `agents/gaodoctor_agent.py`
- `agents/vision_agent.py`
- `agents/diagnosis_agent.py`

Reason:

- Clinical Orchestrator now handles hypothesis / skill routing and multi-image evidence flow.
- Vision Agent now uses visual execution strategy instead of treating every finding as a mask task.
- Diagnosis Agent consumes evidence bundle + skill protocol and handles missing evidence, nonspecific evidence, clinical context, and differential considerations.

### API And Service Boundary

- `api/service.py`
- `api/http_server.py`

Reason:

- Multi-image upload and view-hint normalization enter the stable service/API layer.
- Frontend and demos depend on these boundaries.

### Contracts And Memory

- `contracts/medical_contracts.py`
- `memory/memory_manager.py`

Reason:

- Evidence items carry execution mode, quality, diagnosis usability, and limitations.
- Memory audit preserves patient, image, skill, and reasoning memory for replay and QA.

### Skill And Visual Tools

- `skills/femoral_head_necrosis.yaml`
- `tools/visual_tool_router.py`
- `tools/structured_visual_fact_builder.py`
- `tools/lesion_gallery_builder.py`
- `tools/alignment_planner.py`

Reason:

- FHN skill is the sample multidimensional evidence protocol.
- Visual tools route findings into `vlm_only`, `vlm_plus_segmenter`, `measurement_only`, or `insufficient_input`.
- Gallery and structured fact builders preserve patient-facing visual evidence without upgrading weak masks into diagnostic proof.

### Frontend

- `web/index.html`
- `web/app.js`
- `web/app.css`

Reason:

- Supports multi-image upload.
- Sample loading no longer auto-runs analysis.
- Follow-up QA is enabled only after analysis.
- Patient-facing output hides low-level JSON/path/quality internals.

### Tests

- `tests/test_fhn_evidence_protocol.py`
- `tests/test_contracts.py`
- `tests/test_diagnosis_llm_workflow.py`
- `tests/test_http_entrypoint.py`
- `tests/test_llm_routing.py`
- `tests/test_memory_manager.py`
- `tests/test_mvp_flow.py`
- `tests/test_service_entrypoint.py`

Reason:

- These tests cover protocol schema, visual execution strategy, evidence bundle quality, missing evidence safety, multi-image service flow, memory audit, frontend behavior, and bounded diagnosis.

## Files That Should Not Be Added By Default

### Ignored Runtime Outputs

- `output/`
- `outputs/`

Reason:

- They are intentionally ignored by `.gitignore`.
- They contain local demos, generated images, runtime traces, and case outputs.
- Some files are useful for local presentation, but they should not be bulk committed.

Important local-only artifacts:

- `output/real/MedScope项目关键成果整理/06_架构汇报与阶段文档/当前阶段入口索引_20260604.md`
- `output/real/MedScope项目关键成果整理/06_架构汇报与阶段文档/阶段收敛报告_FHN多图EvidenceProtocol_MVP_20260604.md`
- `output/real/MedScope项目关键成果整理/06_架构汇报与阶段文档/交付清单与提交边界_20260604.md`
- `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/`

The git-tracked replacement entry point is:

- `docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md`

### Local Medical Data And Large Artifacts

Do not add:

- `data/external/`
- `data/cases/`
- `data/images/`
- `data/masks/`
- `data/overlays/`
- `*.dcm`
- `*.nii`
- `*.nii.gz`
- `*.pt`
- `*.pth`
- `*.ckpt`

Reason:

- These may contain large files, private local data, model weights, or generated outputs.

### Secrets And Server-Specific Files

Do not add:

- `.env`
- `.env.*`
- API keys
- SSH/server credentials
- local proxy/auth commands

Reason:

- Secrets must stay outside git.

## Verification Commands Before Commit

Run these before committing:

```bash
node --check web/app.js
python -m unittest discover -v
git diff --check
```

Optional targeted checks:

```bash
python -m unittest tests.test_fhn_evidence_protocol -v
python -m unittest tests.test_service_entrypoint -v
python -m unittest tests.test_http_entrypoint -v
```

## Current Known Verification Evidence

Fresh verification in the current worktree:

- `node --check web/app.js` exited with code 0.
- Latest follow-up verification after the real VLM validation path and dotenv isolation fix:
  `python -m unittest discover -v` ran `409` tests in `57.523s` and returned `OK`.
- `git diff --check` exited with code 0.

If additional code changes are made after this audit, rerun the full verification commands before committing.

## Suggested Staging Command

Review the file list manually first. If it still matches this audit, the intended staging set is:

```bash
git add README.md \
  docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md \
  docs/PRE_COMMIT_AUDIT_20260604.md \
  goalnew.md \
  agents/gaodoctor_agent.py \
  agents/vision_agent.py \
  agents/diagnosis_agent.py \
  api/service.py \
  api/http_server.py \
  contracts/medical_contracts.py \
  memory/memory_manager.py \
  skills/femoral_head_necrosis.yaml \
  tools/visual_tool_router.py \
  tools/structured_visual_fact_builder.py \
  tools/lesion_gallery_builder.py \
  tools/alignment_planner.py \
  web/index.html \
  web/app.js \
  web/app.css \
  tests/test_fhn_evidence_protocol.py \
  tests/test_contracts.py \
  tests/test_diagnosis_llm_workflow.py \
  tests/test_http_entrypoint.py \
  tests/test_llm_routing.py \
  tests/test_memory_manager.py \
  tests/test_mvp_flow.py \
  tests/test_service_entrypoint.py
```

Do not use `git add .` for this commit because ignored/generated medical artifacts and unrelated local files should remain out of scope.
