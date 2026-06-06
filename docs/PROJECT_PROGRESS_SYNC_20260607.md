# MedScope Agent Project Progress Sync - 2026-06-07

This document is the current progress map for the project. It is meant to
replace chat-history memory when deciding the next goal.

## Current Baseline

- Latest implementation commit reviewed: `97d1a34 feat: add research evidence review ingestion`.
- Current working tree note: `goal.md` has local unstaged changes that are not
  part of this progress document.
- Current safe product posture: evidence-bounded clinical agent MVP, not a
  clinically validated automatic diagnosis product.

## Executive Summary

| Area | Current status | Practical interpretation |
| --- | --- | --- |
| 1. Guideline Skill structure expansion | v1 mostly complete | FHN skill is no longer just a finding list. It has imaging, quantitative, differential, clinical context, and integrated reasoning protocols. Remaining work is mostly broader disease coverage and stronger real measurement execution. |
| 2. Clinical information integration | v1 complete, v2 useful | Patient prompt/history/risk factors are preserved in a structured clinical context bundle and bounded as suspicion modifiers only. Remaining work is richer extraction and front-end review ergonomics. |
| 3. Clinical hypothesis generation and skill routing | v1 complete | User does not need to explicitly name FHN for hip-pain X-ray routing. The system generates primary/differential hypotheses and labels them as routing hypotheses, not diagnosis evidence. Remaining work is general multi-disease ranking. |
| 4. Research evidence safely supplementing guideline skill | v1 complete and converged | Research evidence can enter proposal-only artifacts, gateway review, controlled draft, patch preview, and front-end review. It still does not update formal skills, registry, or diagnosis rules. Remaining work is production ingestion v2. |

## 1. Guideline Skill Structure Expansion

### Completed

- `skills/femoral_head_necrosis.yaml` now contains:
  - `imaging_evidence_protocol`
  - `quantitative_evidence_protocol`
  - `differential_diagnosis_protocol`
  - `clinical_context_protocol`
  - `integrated_reasoning_protocol`
- FHN X-ray finding targets are split by evidence type and execution mode:
  - candidate mask: `sclerotic_band`, `cystic_change`, `subchondral_fracture`
  - VLM/observation only: `trabecular_blurring`
  - measurement oriented: `collapse`
  - insufficient X-ray input rule: `early_osteonecrosis`
- Quantitative protocol is separated into:
  - image-feature quantification, such as texture/trabecular disorder scores
  - geometric or morphologic measurement, such as collapse depth, suspected area ratio, subchondral fracture extent, and asymmetry
- `VisualProtocolValidator` enforces item-level quantitative contracts and clinical context boundaries.
- Vision and diagnosis paths consume protocol evidence instead of treating every finding as a direct diagnostic fact.
- A historical finding-list baseline is preserved under `skills/baselines/` and surfaced through the front-end comparison panel.
- Real ONFH COCO protocol evaluation has been scoped to X-ray by default, with MRI treated as auxiliary material rather than the main runtime target.

### Evidence

- Skill: `skills/femoral_head_necrosis.yaml`
- Validator: `tools/visual_protocol_validator.py`
- Runtime usage: `agents/vision_agent.py`, `agents/gaodoctor_agent.py`, `agents/diagnosis_agent.py`
- Real-data protocol evaluation: `scripts/onfh_coco_protocol_eval.py`
- Front-end comparison: `/v1/skills/femoral_head_necrosis/comparison`, `web/app.js`
- Tests:
  - `tests/test_fhn_evidence_protocol.py`
  - `tests/test_visual_protocol_validator.py`
  - `tests/test_onfh_coco_protocol_eval.py`
  - `tests/test_skill_baselines.py`
  - `tests/test_http_entrypoint.py`

### Not Completed / v2

- Measurement execution is not yet clinically robust. ROI, contour, landmark,
  and view-quality gates exist conceptually but are not a validated measurement
  engine.
- Quantitative features are still mostly exploratory or protocol-level
  definitions, not validated numerical predictors.
- Current rich protocol coverage is strongest for FHN and selected sample
  skills, not all diseases.
- MRI labels in the ONFH package are useful as auxiliary discovery signals but
  are not the runtime target for the current product direction.

### Suggested Next Work

The next useful goal in this area would be:

```text
FHN X-ray Evidence Protocol v2: make measurement/quantification review more executable and readable.
Scope: keep X-ray only; improve collapse/subchondral fracture/area-ratio measurement preconditions, output fields, quality gates, and front-end folded review.
Do not claim clinical measurement accuracy.
```

## 2. Clinical Information Integration

### Completed

- Patient prompt clinical context is forwarded into `patient_info` when not
  already structured.
- Diagnosis attaches a structured `clinical_context_bundle`.
- Clinical risk factors are extracted against the skill protocol, including:
  - corticosteroid use
  - alcohol use
  - trauma history
  - hematologic disease
  - autoimmune disease
- Clinical context is explicitly bounded:
  - it can modify suspicion level
  - it cannot confirm diagnosis
  - it cannot replace imaging evidence
- Memory/evidence bundle exposes clinical context evidence.
- Front-end renders clinical context evidence in the structured report/debug
  view without treating it as diagnosis evidence.

### Evidence

- Prompt preservation: `api/service.py`
- Clinical context bundle: `agents/diagnosis_agent.py`
- Skill protocol: `skills/femoral_head_necrosis.yaml`
- Memory exposure: `memory/memory_manager.py`
- Front-end rendering: `web/app.js`
- Tests:
  - `tests/test_service_entrypoint.py`
  - `tests/test_fhn_evidence_protocol.py`
  - `tests/test_memory_manager.py`
  - `tests/test_mvp_flow.py`
  - `tests/test_http_entrypoint.py`

### Not Completed / v2

- Clinical information extraction is still lightweight. It does not yet produce
  a rich normalized timeline such as pain duration, activity-related worsening,
  exact laterality, trauma date, steroid dose/duration, or alcohol exposure
  intensity.
- There is no dedicated front-end form for structured clinical risk review.
- Missing clinical context does not yet trigger a guided question flow.
- Risk factors are not yet scored or ranked across multiple differential
  hypotheses.

### Suggested Next Work

```text
Clinical Context Evidence v2: normalize patient prompt into a structured clinical evidence bundle.
Scope: extract laterality, pain duration, pain location, activity worsening, steroid use, alcohol use, trauma history, and missing-context questions.
Boundary: risk factors remain suspicion modifiers only and cannot confirm diagnosis.
```

## 3. Clinical Hypothesis Generation and Skill Routing

### Completed

- The service can infer a primary disease skill without explicit user
  `disease_key`.
- For hip pain + hip/X-ray clues, the primary hypothesis becomes
  `femoral_head_necrosis`.
- Differential candidates are retained, including:
  - `osteoarthritis_or_degenerative_hip_disease`
  - `post_traumatic_change`
  - `developmental_dysplasia_related_degeneration`
  - infection/inflammatory or tumor-like candidates when prompt clues appear
- Routing output includes:
  - `primary_hypothesis`
  - `differential_skill_candidates`
  - `clinical_hypotheses`
  - `initial_evidence_status`
  - `routing_evidence_status`
- Diagnosis report attaches `clinical_hypotheses_assessment` and explicitly
  sets `hypotheses_are_diagnosis=false`.
- Front-end shows the candidate hypothesis queue and states that it is not a
  diagnostic conclusion.

### Evidence

- Routing: `api/service.py`
- Diagnosis boundary: `agents/diagnosis_agent.py`
- Front-end rendering: `web/app.js`
- Memory/audit: `memory/memory_manager.py`
- Tests:
  - `tests/test_service_entrypoint.py`
  - `tests/test_contracts.py`
  - `tests/test_fhn_evidence_protocol.py`
  - `tests/test_memory_manager.py`
  - `tests/test_http_entrypoint.py`

### Not Completed / v2

- General multi-disease ranking is still limited.
- There is no score model for competing hypotheses.
- There is no broad disease ontology or body-part/modality routing registry.
- Differential skill candidates are mostly rule-based for the current FHN path.

### Suggested Next Work

Do not redo this as a v1 goal. If needed later:

```text
Hypothesis Routing v2: add general multi-skill ranking across body part, modality, symptoms, and clinical context.
Scope: route to ranked primary/differential skill candidates across more diseases.
Boundary: hypotheses remain routing/evidence-acquisition plans, not diagnosis.
```

## 4. Research Evidence Safely Supplementing Guideline Skill

### Completed

- `ResearchEvidenceRetriever` supports PubMed metadata/abstract retrieval and
  supplied metadata fallback.
- PubMed unavailable cases do not block supplied metadata normalization.
- PubMed XML metadata parser preserves title, journal, year, PMID, DOI, and
  abstract.
- `ResearchEvidenceExtractor` converts metadata/abstract/supplied text into
  normalized research evidence and uses `unknown` rather than guessing missing
  fields.
- Normalized evidence preserves source trace and source metadata.
- `ResearchClaimBuilder` emits canonical candidate claim types:
  - `imaging_feature`
  - `quantitative_feature`
  - `geometric_or_morphologic_measurement`
  - `clinical_risk_association`
  - `differential_diagnosis_clue`
- Legacy candidate types are preserved separately for compatibility.
- Evidence Gateway outputs named gate statuses:
  - source quality
  - freshness
  - applicability
  - modality match
  - population match
  - sample size
  - guideline conflict
  - reproducibility/external validation
  - human review required
- Review package includes:
  - research evidence proposal
  - quality gate report
  - human review checklist
  - promotion dry-run
  - controlled skill extension draft
  - formal skill extension patch preview
- Front-end has a folded Research Evidence Review panel.
- Safety boundary is explicit:
  - proposal-only
  - no formal skill update
  - no diagnosis rules update
  - no registry update
  - promotion requires human approval

### Evidence

- Builder: `scripts/research_evidence_builder.py`
- API: `/v1/research-evidence-review`, `api/http_server.py`
- Front-end: `web/index.html`, `web/app.js`, `web/app.css`
- Tests:
  - `tests/test_research_evidence_gateway.py`
  - `tests/test_http_entrypoint.py`

### Not Completed / v2

- No production live-PubMed quality evaluation workflow.
- No full-text PDF parser.
- No production approval identity/permission/signature system.
- No UI that actually applies an approved controlled extension.
- No automatic formal skill update, by design.

### Suggested Next Work

This area is converged for v1. Defer unless explicitly starting:

```text
Research Ingestion v2: live PubMed review + production human approval.
Scope: real query quality, reviewer workflow, signatures, audit.
Boundary: still no automatic formal skill update.
```

## Supporting Project Areas

### Front-End

Completed:

- Main case input and visual/report panels.
- Skill version comparison panel.
- Research Evidence Review panel.
- Candidate hypothesis queue.
- Clinical/evidence/debug sections.
- Safer agent-routed vision flow without manual mode picker.

Remaining:

- Better clinician-facing organization for dense protocol/debug information.
- More polished review screens for clinical context, quantification, and
  controlled skill extension.

### Memory / Audit

Completed:

- Case memory, replay, evidence bundle, clinical context evidence, routing
  memory, runtime/audit details, QA evidence-bound answers.

Remaining:

- More production-like audit trail for human approval and signed promotion.

### Real Data / ONFH COCO Evaluation

Completed:

- Real ONFH package path is supported by `scripts/onfh_coco_protocol_eval.py`.
- Evaluation is scoped to X-ray by default.
- Baseline finding-list skill and current evidence-protocol skill can be
  compared.
- Front-end comparison summarizes coverage and quantitative needs.

Remaining:

- No claim of clinical accuracy.
- No validated real segmentation/measurement benchmark yet.
- MRI remains auxiliary for feature discovery, not runtime target.

## Recommended Next Goal Order

1. **Clinical Context Evidence v2**  
   Best if the priority is using patient prompt information more naturally.
   It is smaller and directly improves diagnostic reasoning readability.

2. **FHN X-ray Quantification / Measurement Protocol v2**  
   Best if the priority is making the new evidence protocol visibly stronger
   than the old finding-list skill.

3. **Front-End Review Ergonomics for Protocol Evidence**  
   Best if the priority is making the existing work easier for a doctor or
   researcher to inspect.

4. **Hypothesis Routing v2**  
   Useful later, but current v1 is already good enough for the FHN workflow.

5. **Research Ingestion v2**  
   Defer unless the explicit goal is production paper ingestion and approval.

## Current "Do Not Reopen Unless Needed" List

- Do not redo Research Evidence Ingestion v1.
- Do not redo Clinical Hypothesis Routing v1.
- Do not treat PubMed/paper evidence as guideline evidence.
- Do not use MRI as the runtime test target if the product direction is X-ray.
- Do not claim clinical validation from protocol coverage or demo artifacts.

## Verification Snapshot

Latest full verification recorded after Research Evidence Review ingestion:

```bash
python -m unittest
```

```text
Ran 483 tests in 63.926s
OK
```

Formatting check:

```bash
git diff --check
```

```text
OK
```
