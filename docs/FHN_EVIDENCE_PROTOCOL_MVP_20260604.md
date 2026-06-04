# FHN Evidence Protocol MVP

Date: 2026-06-04

This document is the git-tracked entry point for the current femoral head necrosis (FHN) evidence protocol MVP. The richer local demo artifacts live under `output/real/`, which is intentionally ignored by git.

## Current Scope

The current MVP demonstrates a bounded medical-agent workflow for `femoral_head_necrosis`:

```text
patient symptoms + one or more hip X-ray images
  -> Clinical Orchestrator hypothesis / skill routing
  -> FHN guideline skill evidence protocol
  -> visual execution strategy
  -> structured evidence bundle
  -> bounded diagnosis report
  -> memory audit
```

This phase is not a clinically validated automatic diagnosis or segmentation system.

## What Changed

### Skill Protocol

`skills/femoral_head_necrosis.yaml` now acts as the sample disease skill for a multi-dimensional evidence protocol. It supports, while remaining backward-compatible with older visual finding lists:

- `imaging_evidence_protocol`
- `quantitative_evidence_protocol`
- `differential_diagnosis_protocol`
- `clinical_context_protocol`
- `integrated_reasoning_protocol`

The key design change is that a guideline finding is no longer automatically treated as a segmentation task.

### Visual Execution Strategy

The visual pipeline now routes each finding through an execution strategy before evidence is produced:

- `vlm_only`
- `vlm_plus_segmenter`
- `specialist_segmenter`
- `measurement_only`
- `insufficient_input`

Examples:

- `sclerotic_band` and `cystic_change` may become candidate visual regions, but require quality checks before being used diagnostically.
- `trabecular_blurring` is treated as observation / exploratory texture evidence rather than a stable mask target.
- `collapse` is treated as measurement-oriented evidence and depends on ROI, contour, or landmark quality.
- early osteonecrosis on X-ray only should be marked as insufficient input rather than ruled out.

### Evidence Bundle

Diagnosis reasoning now receives structured evidence items with:

- target
- evidence type
- execution mode
- visual observation
- segmentation summary
- measurements
- quality
- diagnosis usable flag
- diagnosis usable level
- limitations

This is the contract that prevents missing or low-quality evidence from being silently upgraded into diagnostic certainty.

### Diagnosis Reasoning

`DiagnosisAgent` remains evidence-bounded:

- It does not inspect raw images.
- It does not treat missing evidence as negative evidence.
- It does not treat nonspecific findings as confirmed disease evidence.
- It includes differential considerations from the skill protocol.
- It states modality limitations, especially that X-ray cannot reliably exclude early FHN.

### Multi-Image Input

The frontend and service entry point support multiple uploaded images for the same patient. The service records view hints such as:

- `ap_pelvis`
- `frog_lateral`
- `lateral`
- `unknown`

This allows a case to preserve AP/lateral evidence separately instead of flattening all images into one visual record.

## Local Demo Artifacts

These files are intentionally not git-tracked because `output/` is ignored:

- `output/real/MedScope项目关键成果整理/06_架构汇报与阶段文档/当前阶段入口索引_20260604.md`
- `output/real/MedScope项目关键成果整理/06_架构汇报与阶段文档/阶段收敛报告_FHN多图EvidenceProtocol_MVP_20260604.md`
- `output/real/MedScope项目关键成果整理/06_架构汇报与阶段文档/交付清单与提交边界_20260604.md`
- `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/`
- `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/多体位AP蛙式位数据源审计.md`

The AP + lateral CC0 pair is a real-image demonstration candidate, not a strict AP + frog-lateral benchmark.

## Verification Snapshot

Latest full verification recorded after the real VLM validation path and dotenv isolation fix:

```bash
python -m unittest discover -v
```

Result recorded in the local phase report:

```text
421 tests passed
```

For a fresh pre-commit check, run:

```bash
node --check web/app.js
python -m unittest discover -v
git diff --check
```

## Reporting Boundary

Accurate statement:

> The project now has an FHN-centered evidence protocol MVP that separates skill routing, visual evidence extraction, evidence quality, bounded diagnosis reasoning, and memory audit.

Do not claim:

- stable clinical diagnosis of FHN from X-ray
- validated lesion segmentation on hip X-ray
- AP + frog-lateral benchmark coverage
- VLM candidate regions as clinical-grade masks
- MRI-level early FHN exclusion from X-ray

## Recommended Next Goals

Keep these as separate goals rather than extending this phase:

1. Real VLM API validation on multi-view hip X-ray cases.
2. Strict AP + frog-lateral paired dataset or small manually curated set.
3. FHN anatomical ROI / landmark / contour quality gates.
4. APTR / FPTR / collapse depth / sphericity measurement protocol.
5. Skill Builder proposal-skill review flow through the Evidence Gateway.
