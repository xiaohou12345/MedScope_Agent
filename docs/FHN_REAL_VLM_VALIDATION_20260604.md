# FHN Real VLM Multi-View Validation

Date: 2026-06-04

This phase adds a narrow validation path for femoral head necrosis (FHN) multi-view X-ray inputs. The goal is to let real VLM-localized candidate observations enter the existing FHN evidence protocol without upgrading those observations into clinical-grade diagnosis, segmentation, or measurement support.

## What The Mode Does

`real_vlm_validation` is an explicit vision mode accepted by the service, CLI demo, and frontend. It:

- preserves multi-view image inputs as an image series with view hints such as `ap_pelvis`, `lateral`, or `frog_lateral`;
- calls the configured OpenAI-compatible VLM route through the existing prompt runner when a real run is requested;
- asks the model for localized candidate findings, not for a diagnosis;
- parses VLM boxes or polygons through `tools/vlm_candidate_parser.py`;
- writes structured evidence items into the evidence bundle;
- keeps DiagnosisAgent bounded by the evidence bundle and the FHN skill protocol.

## What It Does Not Prove

This mode does not prove that the system can diagnose FHN from X-ray. It also does not prove that VLM localization is clinically reliable.

The current contract explicitly avoids these unsafe upgrades:

- a VLM bbox or polygon is not a medical mask;
- candidate localization is not measurement-grade segmentation;
- missing MRI, missing lateral views, or failed parsing is not negative evidence;
- exploratory image features are not strong diagnostic evidence;
- DiagnosisAgent still cannot inspect raw pixels.

## Evidence Bundle Mapping

VLM findings are converted into evidence items with explicit quality and usability fields.

Localized candidates are represented as:

```json
{
  "evidence_type": "visual_observation",
  "execution_mode": "vlm_only",
  "diagnosis_usable_level": "candidate_support",
  "measurements": {
    "measurement_usable": false
  }
}
```

Unlocalized or invalid findings are downgraded to `observation_only` and include limitations such as `no_valid_location` or `invalid_bbox`.

No VLM candidate produced by this phase is allowed to become `measurement_support`.

## Missing And Low-Quality Outputs

Failures are represented as evidence state, not as disease absence.

- If the API key or route is not configured, readiness reports `not_ready` without calling the network.
- If VLM output cannot be parsed, the evidence bundle records a non-usable evidence item and a quality warning.
- If a candidate lacks usable coordinates, it remains an observation-only item.
- If segmentation is not requested or does not run, segmentation is marked as not generated and measurements remain unusable.

## Dry-Run Demo

Use dry-run mode to validate inputs and write readiness artifacts without an API call:

```bash
python -m scripts.fhn_real_vlm_multiview_demo \
  --ap-image /path/to/ap_pelvis.png \
  --lateral-image /path/to/lateral.png \
  --output-dir output/real/fhn_real_vlm_validation_demo \
  --dry-run
```

Expected artifacts:

- `readiness.json`
- `input_manifest.json`
- `summary.json`

## Real Demo

Configure the model route first:

```bash
export DMX_API_KEY="..."
```

Then run:

```bash
python -m scripts.fhn_real_vlm_multiview_demo \
  --ap-image /path/to/ap_pelvis.png \
  --lateral-image /path/to/lateral.png \
  --frog-lateral-image /path/to/frog_lateral.png \
  --message "left hip pain, please review these hip X-rays" \
  --output-dir output/real/fhn_real_vlm_validation_demo
```

Expected artifacts:

- `summary.json`
- `response.json`
- `evidence_bundle.json`
- `visual_evidence_bundle.json`
- `diagnosis_report.json`
- `audit.json`
- `input_manifest.json`
- `readiness.json`

## Frontend Use

The web UI exposes this as `真实 VLM 候选验证` under the evidence acquisition mode selector. The default remains the existing safe automatic mode. Selecting real VLM validation only changes the current case payload by sending:

```json
{
  "vision_mode": "real_vlm_validation"
}
```

The UI labels this path as candidate visual evidence so users do not confuse it with measurement-grade segmentation.

## Verification

This phase is covered by:

- `tests.test_service_entrypoint`
- `tests.test_vlm_candidate_parser`
- `tests.test_fhn_real_vlm_validation`
- `tests.test_api_connectivity`
- `tests.test_http_entrypoint`
- `tests.test_fhn_real_vlm_multiview_demo`

The final gate for this phase is:

```bash
node --check web/app.js
python -m unittest discover -v
git diff --check
```
