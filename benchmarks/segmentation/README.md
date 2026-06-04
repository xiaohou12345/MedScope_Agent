# Segmentation Benchmarks

This folder is for disease-specific segmentation validation, separate from the
web demo and frontend screenshots.

Current scope:

- Manifest-driven benchmark readiness checks.
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

Run:

```bash
python -m scripts.segmentation_benchmark \
  --manifest benchmarks/segmentation/femoral_head_necrosis/public_fixture_manifest.json \
  --output-dir output/fake/segmentation_benchmark/fhn_public_fixture \
  --prepare-fixtures
```
