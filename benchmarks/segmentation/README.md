# Segmentation Benchmarks

This folder is for disease-specific segmentation validation, separate from the
web demo and frontend screenshots.

Current scope:

- Manifest-driven benchmark readiness checks.
- `binary_mask` evaluator for generic 2D lesion mask Dice/IoU.
- Manifest-level metric gates for metric-ready cases.
- Explicit separation between public-safe generated fixtures and real labeled
  benchmark data.
- No clinical diagnosis claims.
- No formal skill updates from benchmark results.

The initial FHN manifest is a public-safe smoke fixture. It verifies that the
benchmark runner, case schema, and safety gates work, but it does not contain a
reference mask and therefore does not produce Dice/IoU metrics.

When real labeled cases are added, define `metric_gates` in the manifest. The
runner will report metric pass/fail counts, but benchmark results still cannot
upgrade diagnosis output or update formal skills automatically.

For FHN X-ray cases, use `evaluator_type: binary_mask` unless a disease-specific
evaluator is added and validated separately. The legacy `brats_regions`
evaluator is only for BraTS-style multi-label tumor masks.

Metric-ready cases must point to existing `prediction_mask_path` and
`reference_mask_path` files. Missing files are reported as
`missing_prediction_file` or `missing_reference_file` before metric evaluation.
Relative `image_path`, `prediction_mask_path`, and `reference_mask_path` values
are resolved from the manifest file's directory, so benchmark folders can move
without depending on the current shell working directory.

Run:

```bash
python -m scripts.segmentation_benchmark \
  --manifest benchmarks/segmentation/femoral_head_necrosis/public_fixture_manifest.json \
  --output-dir output/fake/segmentation_benchmark/fhn_public_fixture \
  --prepare-fixtures
```
