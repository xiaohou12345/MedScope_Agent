# Current MVP Demo Runbook - 2026-06-05

This runbook explains how to demonstrate the current MedScope Agent MVP without
requiring real FHN labels, real masks, or a real metric-ready benchmark.

## Scope

Use this runbook to show the current evidence-bounded system flow:

```text
patient input + image upload
  -> automatic skill routing
  -> visual evidence
  -> diagnosis report
  -> evidence bundle
  -> memory audit
  -> follow-up QA
```

This is not a clinical diagnosis. It is a research demo for architecture,
contracts, evidence boundaries, and auditability.

The real FHN data and masks are deferred. They are not required for this demo
runbook and should be added later through the segmentation benchmark framework
when those data are available.

## Public-Safe Fixture

Run the public-safe MVP suite when you want one command that covers upload,
automatic skill routing, visual evidence, diagnosis report, evidence bundle,
memory audit, and follow-up QA:

```bash
python -m scripts.prepare_public_demo_fixture --suite \
  --output-dir output/fake/public_safe_demo_suite
```

This suite uses a deterministic local visual runner, so it does not require a
real VLM API, MedSAM2 backend, real FHN data, or real masks.

Generate a public-safe synthetic input that can be committed or regenerated
without private DICOM, NIfTI, patient data, or ignored `output/real` artifacts:

```bash
python -m scripts.prepare_public_demo_fixture \
  --output-dir output/fake/public_demo_fixture
```

Expected purpose:

- Produces a synthetic X-ray-like PNG.
- Writes a manifest with a `service_payload`.
- Exercises upload, FHN skill routing, and report/audit plumbing.
- Does not claim true pathology, true lesion localization, or benchmark quality.

## Standard End-To-End Demo

Run the standard demo suite:

```bash
python -m scripts.end_to_end_demo --suite
```

The suite is designed to show the current MVP path rather than model quality:

- `glioma_ground_truth`: demonstrates image upload, skill routing, visual
  evidence from a reference-mask development path, diagnosis report generation,
  evidence bundle persistence, and memory audit.
- `xray_insufficient_evidence`: demonstrates that hip X-ray input can route to
  FHN as a clinical hypothesis while still reporting insufficient evidence and
  recommending MRI when the current modality is not enough.

Useful generated artifacts:

- `standard_demo_summary.json`
- `demo_summary.md`
- per-case response JSON
- per-case evidence bundle JSON
- per-case memory audit JSON

## Optional FHN No-Mask Demo

If the local no-mask fixture exists, the standard suite can include the FHN
multi-finding case:

```bash
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask
```

This path is useful for showing how a selected FHN skill can drive VLM-only or
VLM-plus-segmenter candidate evidence. It is still candidate evidence, not a
validated segmentation result.

## Web Demo

Start the API and frontend:

```bash
python -m api.http_server --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Recommended demonstration order:

1. Load or upload a public-safe image.
2. Enter a symptom-oriented message, such as hip pain, without requiring the
   user to name a disease.
3. Run analysis and inspect automatic skill routing in the audit views.
4. Review the visual evidence panel.
5. Review the patient-facing diagnosis report.
6. Open the evidence bundle to inspect structured facts, missing evidence, and
   quality levels.
7. Open memory audit to show patient memory, image memory, skill memory, and
   reasoning memory.
8. Ask a follow-up QA question only after analysis is complete.

## What To Say In A Meeting

Safe statements:

- The MVP separates orchestration, vision evidence, guideline skill handling,
  diagnosis reasoning, and memory/audit.
- The diagnosis agent consumes structured evidence instead of raw pixels.
- Missing input is preserved as missing input, not converted into a negative
  finding.
- Current FHN X-ray outputs are candidate evidence unless validated by future
  data and quality gates.
- The benchmark framework is ready to accept real binary lesion masks later.

Statements to avoid:

- The system has clinically validated FHN X-ray segmentation.
- The FHN real benchmark is complete.
- The public fixture proves lesion detection quality.
- VLM or MedSAM2 candidates are diagnosis-grade without quality validation.

## Next Data Phase

When real FHN data and masks are available, add them under
`benchmarks/segmentation/` with:

- `evaluator_type: binary_mask`
- `reference_mask_path`
- `prediction_mask_path`
- `metric_gates`

That phase should be a separate goal from this current MVP demo closure.
