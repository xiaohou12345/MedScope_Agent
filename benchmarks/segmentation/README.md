# Segmentation Benchmarks

This folder is for disease-specific segmentation validation, separate from the
web demo and frontend screenshots.

Current scope:

- Manifest-driven benchmark readiness checks.
- Explicit separation between public-safe generated fixtures and real labeled
  benchmark data.
- No clinical diagnosis claims.
- No formal skill updates from benchmark results.

The initial FHN manifest is a public-safe smoke fixture. It verifies that the
benchmark runner, case schema, and safety gates work, but it does not contain a
reference mask and therefore does not produce Dice/IoU metrics.

Run:

```bash
python -m scripts.segmentation_benchmark \
  --manifest benchmarks/segmentation/femoral_head_necrosis/public_fixture_manifest.json \
  --output-dir output/fake/segmentation_benchmark/fhn_public_fixture \
  --prepare-fixtures
```
