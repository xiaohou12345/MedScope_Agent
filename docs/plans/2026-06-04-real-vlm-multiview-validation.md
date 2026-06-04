# Real VLM Multi-View Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Validate that real VLM outputs from multi-view hip X-ray inputs can enter the existing FHN evidence protocol safely, without upgrading candidate observations into clinical-grade diagnosis or segmentation.

**Architecture:** Keep the current FHN Evidence Protocol MVP intact. Add a narrow validation path that calls the configured VLM route, converts model-localized visual candidates into structured evidence items, records quality and limitations, then compares the result against the deterministic no-mask pipeline. Diagnosis remains bounded by `evidence_bundle + skill protocol`; the VLM never becomes a free diagnostic authority.

**Tech Stack:** Python unittest, existing `llm/` OpenAI-compatible client, `api/service.py`, `agents/gaodoctor_agent.py`, `agents/vision_agent.py`, `tools/visual_tool_router.py`, `tools/structured_visual_fact_builder.py`, static frontend under `web/`, JSON artifacts under ignored `output/`.

---

## Non-Goals

- Do not claim validated clinical diagnosis.
- Do not require MedSAM2 to succeed.
- Do not treat VLM boxes or polygons as clinical masks.
- Do not use missing MRI or missing frog-lateral view as negative evidence.
- Do not implement APTR / FPTR measurements in this phase.
- Do not expand beyond `femoral_head_necrosis` in this phase.

## Task 1: Add Real VLM Validation Mode Contract

**Files:**

- Modify: `contracts/medical_contracts.py`
- Modify: `api/service.py`
- Test: `tests/test_service_entrypoint.py`

**Step 1: Write the failing test**

Add a service test:

```python
def test_service_accepts_real_vlm_validation_mode_for_fhn_multiview(self):
    service = MedScopeService()
    payload = {
        "patient_message": "left hip pain, please review these hip X-rays",
        "image_paths": ["/tmp/ap_pelvis.png", "/tmp/lateral.png"],
        "patient_info": {"symptoms": ["left hip pain"]},
        "vision_mode": "real_vlm_validation",
    }
    normalized = service._normalize_case_payload(payload)
    self.assertEqual(normalized["vision_mode"], "real_vlm_validation")
    self.assertEqual(normalized["image_series"][0]["view_hint"], "ap_pelvis")
    self.assertEqual(normalized["image_series"][1]["view_hint"], "lateral")
```

**Step 2: Run test to verify it fails**

Run:

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_accepts_real_vlm_validation_mode_for_fhn_multiview -v
```

Expected: fail because `real_vlm_validation` is not yet accepted or normalized.

**Step 3: Implement minimal contract support**

- Allow `vision_mode == "real_vlm_validation"` in service normalization.
- Preserve `image_series`, `view_hint`, `image_path`, and patient prompt.
- Do not automatically call VLM in this task.

**Step 4: Run test to verify it passes**

Run:

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_accepts_real_vlm_validation_mode_for_fhn_multiview -v
```

Expected: pass.

**Step 5: Commit**

```bash
git add api/service.py contracts/medical_contracts.py tests/test_service_entrypoint.py
git commit -m "feat: add real VLM validation mode contract"
```

## Task 2: Add VLM Candidate Evidence Parser

**Files:**

- Create: `tools/vlm_candidate_parser.py`
- Test: `tests/test_vlm_candidate_parser.py`

**Step 1: Write the failing tests**

Add tests for model output parsing:

```python
def test_parser_converts_vlm_boxes_to_candidate_evidence_items():
    raw = {
        "findings": [
            {
                "target": "sclerotic_band",
                "side": "left",
                "bbox": [100, 120, 180, 190],
                "rationale": "arc-like increased density",
                "confidence": 0.63,
            }
        ]
    }
    items = parse_vlm_candidates(raw, image_id="image_001", view_hint="ap_pelvis")
    self.assertEqual(items[0]["target"], "sclerotic_band")
    self.assertEqual(items[0]["evidence_type"], "visual_observation")
    self.assertEqual(items[0]["execution_mode"], "vlm_only")
    self.assertEqual(items[0]["diagnosis_usable_level"], "candidate_support")
    self.assertFalse(items[0]["measurements"].get("measurement_usable", True))
```

```python
def test_parser_marks_invalid_or_missing_locations_as_observation_only():
    raw = {"findings": [{"target": "trabecular_blurring", "rationale": "texture unclear"}]}
    items = parse_vlm_candidates(raw, image_id="image_001", view_hint="ap_pelvis")
    self.assertEqual(items[0]["diagnosis_usable_level"], "observation_only")
    self.assertIn("no_valid_location", items[0]["limitations"])
```

**Step 2: Run tests to verify they fail**

Run:

```bash
python -m unittest tests.test_vlm_candidate_parser -v
```

Expected: fail because parser does not exist.

**Step 3: Implement parser**

Implement `parse_vlm_candidates(raw, image_id, view_hint)`:

- Accept dict output from VLM.
- Normalize target, side, bbox, polygon, rationale, confidence.
- Return evidence items compatible with current evidence bundle.
- Default to `diagnosis_usable=false` unless location and target pass quality checks.
- Use `candidate_support` only for localized candidate findings.
- Use `observation_only` for unlocalized VLM findings.
- Never create measurement support.

**Step 4: Run parser tests**

Run:

```bash
python -m unittest tests.test_vlm_candidate_parser -v
```

Expected: pass.

**Step 5: Commit**

```bash
git add tools/vlm_candidate_parser.py tests/test_vlm_candidate_parser.py
git commit -m "feat: parse VLM candidates into bounded evidence items"
```

## Task 3: Wire Real VLM Validation Into Vision Agent

**Files:**

- Modify: `agents/vision_agent.py`
- Modify: `agents/gaodoctor_agent.py`
- Test: `tests/test_fhn_real_vlm_validation.py`

**Step 1: Write the failing test**

Add a fake prompt runner / VLM client test:

```python
def test_gaodoctor_real_vlm_validation_persists_candidate_evidence_without_diagnosis_upgrade(self):
    runner = FakeVlmRunner({
        "findings": [
            {
                "target": "sclerotic_band",
                "side": "left",
                "bbox": [100, 120, 180, 190],
                "rationale": "arc-like increased density",
                "confidence": 0.63,
            }
        ]
    })
    agent = GaoDoctorAgent(prompt_runner=runner)
    result = agent.run_case({
        "patient_message": "left hip pain",
        "image_paths": ["/tmp/ap_pelvis.png", "/tmp/lateral.png"],
        "vision_mode": "real_vlm_validation",
    })
    bundle = result["evidence_bundle"]
    item = bundle["evidence_items"][0]
    self.assertEqual(item["execution_mode"], "vlm_only")
    self.assertEqual(item["diagnosis_usable_level"], "candidate_support")
    self.assertNotEqual(result["diagnosis_report"]["target_disease_assessment"]["certainty"], "confirmed")
```

**Step 2: Run test to verify it fails**

Run:

```bash
python -m unittest tests.test_fhn_real_vlm_validation -v
```

Expected: fail because real VLM validation mode is not wired.

**Step 3: Implement wiring**

- In `GaoDoctorAgent`, route `vision_mode == "real_vlm_validation"` to a narrow real-VLM validation path.
- Reuse existing skill routing for `femoral_head_necrosis`.
- Ask VLM for evidence candidates, not diagnosis.
- Parse model output through `tools/vlm_candidate_parser.py`.
- Store parsed items in `evidence_bundle`.
- Continue using DiagnosisAgent bounded reasoning.

**Step 4: Run targeted tests**

Run:

```bash
python -m unittest tests.test_fhn_real_vlm_validation -v
python -m unittest tests.test_fhn_evidence_protocol -v
python -m unittest tests.test_service_entrypoint -v
```

Expected: pass.

**Step 5: Commit**

```bash
git add agents/gaodoctor_agent.py agents/vision_agent.py tests/test_fhn_real_vlm_validation.py
git commit -m "feat: wire real VLM validation into FHN evidence flow"
```

## Task 4: Add Offline Real-VLM Readiness And Failure Artifacts

**Files:**

- Modify: `api/service.py`
- Modify: `docs/API_ROUTE_LOG.md`
- Test: `tests/test_api_connectivity.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_readiness_reports_real_vlm_validation_requires_api_key_without_calling_network(self):
    report = inspect_real_vlm_validation_readiness(env={})
    self.assertEqual(report["status"], "not_ready")
    self.assertIn("api_key_missing", report["reasons"])
```

```python
def test_readiness_never_returns_secret_values(self):
    report = inspect_real_vlm_validation_readiness(env={"DMX_API_KEY": "sk-secret"})
    self.assertNotIn("sk-secret", json.dumps(report))
```

**Step 2: Run tests to verify fail**

Run:

```bash
python -m unittest tests.test_api_connectivity -v
```

Expected: fail until readiness helper exists.

**Step 3: Implement readiness helper**

- Check configured model route.
- Check expected API key presence.
- Check image input exists when running a real case.
- Never call network.
- Never expose key values.

**Step 4: Run tests**

Run:

```bash
python -m unittest tests.test_api_connectivity -v
```

Expected: pass.

**Step 5: Commit**

```bash
git add api/service.py docs/API_ROUTE_LOG.md tests/test_api_connectivity.py
git commit -m "feat: add real VLM validation readiness checks"
```

## Task 5: Add CLI Demo For Real VLM Multi-View Validation

**Files:**

- Create: `scripts/fhn_real_vlm_multiview_demo.py`
- Test: `tests/test_fhn_real_vlm_multiview_demo.py`

**Step 1: Write failing dry-run test**

```python
def test_demo_dry_run_writes_readiness_report_without_api_call(self):
    output_dir = self.tmp_path / "demo"
    result = run_demo(
        ap_image="/tmp/ap.png",
        lateral_image="/tmp/lateral.png",
        output_dir=str(output_dir),
        dry_run=True,
    )
    self.assertEqual(result["status"], "dry_run")
    self.assertTrue((output_dir / "readiness.json").exists())
```

**Step 2: Run test to verify fail**

Run:

```bash
python -m unittest tests.test_fhn_real_vlm_multiview_demo -v
```

Expected: fail because script does not exist.

**Step 3: Implement CLI**

CLI behavior:

- Accept `--ap-image`, `--lateral-image`, optional `--frog-lateral-image`.
- Accept `--message`, `--output-dir`, `--dry-run`.
- Dry run writes readiness report only.
- Real run calls service with `vision_mode=real_vlm_validation`.
- Write:
  - `summary.json`
  - `evidence_bundle.json`
  - `diagnosis_report.json`
  - `audit.json`
  - copied input image manifest

**Step 4: Run tests**

Run:

```bash
python -m unittest tests.test_fhn_real_vlm_multiview_demo -v
```

Expected: pass.

**Step 5: Commit**

```bash
git add scripts/fhn_real_vlm_multiview_demo.py tests/test_fhn_real_vlm_multiview_demo.py
git commit -m "feat: add FHN real VLM multi-view validation demo"
```

## Task 6: Add Frontend Toggle For Validation Mode

**Files:**

- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/app.css`
- Test: `tests/test_http_entrypoint.py`

**Step 1: Write failing frontend static test**

Add assertions:

```python
def test_static_app_js_exposes_real_vlm_validation_mode_without_defaulting_to_it(self):
    app_js = self._read_static("app.js")
    self.assertIn("real_vlm_validation", app_js)
    self.assertIn("candidate visual evidence", app_js)
    self.assertIn("no_mask_skill", app_js)
```

**Step 2: Run failing test**

Run:

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_exposes_real_vlm_validation_mode_without_defaulting_to_it -v
```

Expected: fail until UI toggle exists.

**Step 3: Implement UI toggle**

- Add a small validation-mode selector in the diagnostic controls.
- Default remains current safe mode.
- Label real VLM mode as validation / candidate evidence.
- Disable or warn if readiness is not ready.

**Step 4: Run frontend tests**

Run:

```bash
node --check web/app.js
python -m unittest tests.test_http_entrypoint -v
```

Expected: pass.

**Step 5: Commit**

```bash
git add web/index.html web/app.js web/app.css tests/test_http_entrypoint.py
git commit -m "feat: expose real VLM validation mode in frontend"
```

## Task 7: Final Verification And Phase Report

**Files:**

- Create: `docs/FHN_REAL_VLM_VALIDATION_20260604.md`
- Modify: `README.md`
- Optional local ignored artifacts: `output/real/MedScope项目关键成果整理/08_主线真实数据验证/`

**Step 1: Run full verification**

Run:

```bash
node --check web/app.js
python -m unittest discover -v
git diff --check
```

Expected: all pass.

**Step 2: Write phase report**

Create:

```text
docs/FHN_REAL_VLM_VALIDATION_20260604.md
```

Include:

- What real VLM validation mode does.
- What it does not prove.
- How candidate VLM observations map into evidence bundle.
- How missing inputs and low-quality outputs are represented.
- How to run dry-run demo.
- How to run real demo when API key is configured.

**Step 3: Link from README**

Add a link under the Architecture / project phase docs list.

**Step 4: Commit**

```bash
git add docs/FHN_REAL_VLM_VALIDATION_20260604.md README.md
git commit -m "docs: document FHN real VLM validation workflow"
```

## Final Verification Gate

Before pushing:

```bash
git status --short
node --check web/app.js
python -m unittest discover -v
git diff --check
git log --oneline -5
```

Expected:

- Worktree clean after commits.
- JS syntax passes.
- Full unittest passes.
- No diff whitespace errors.
- Recent commits correspond to this plan.

## Execution Notes

- Use one commit per task.
- Do not push until all tasks pass.
- Do not use `git add .`.
- Do not add `output/`, `.env*`, DICOM/NIfTI, or model weights.
- If real VLM API is unavailable, the phase can still complete dry-run readiness and mocked parser validation, but the real-run artifact must be marked `not_ready`, not faked.
