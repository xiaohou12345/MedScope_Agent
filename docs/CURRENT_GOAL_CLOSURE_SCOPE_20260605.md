# Current Goal Closure Scope - 2026-06-05

This document fixes the closure boundary for the current MedScope Agent goal.
The requirement-to-evidence audit is tracked in
[CURRENT_GOAL_COMPLETION_AUDIT_20260605.md](CURRENT_GOAL_COMPLETION_AUDIT_20260605.md).

## Included In This Goal

- Keep the five-agent clinical evidence pipeline understandable and demonstrable.
- Keep the FHN evidence-protocol sample path working from skill schema to visual execution strategy, structured evidence bundle, bounded diagnosis report, QA, and memory audit.
- Keep segmentation benchmark infrastructure available as a public-safe, manifest-driven readiness and metric-gate framework.
- Keep benchmark results blocked from clinical diagnosis, formal skill promotion, or self-evolving guideline updates.
- Keep README and Chinese README aligned with the current MVP status and limitations.

## Deferred From This Goal

The real FHN data and masks are deferred and are not required for this goal.

This means the current goal does not require:

- Real labeled FHN AP/frog-lateral datasets.
- Real reference masks or landmark annotations.
- A metric-ready real benchmark manifest.
- Claims that MedSAM2, VLM localization, or any specialist model has reached clinically reliable FHN lesion segmentation.

When the user obtains the data later, the next phase can add those cases under
`benchmarks/segmentation/` with `evaluator_type: binary_mask`,
`reference_mask_path`, `prediction_mask_path`, and `metric_gates`.

## Current Verification Baseline

The latest completed full regression before this scope lock was:

```text
421 tests passed
```

After adding the scope, runbook, public-safe suite, runtime-environment guards,
artifact-bound public-safe demo QA route, README API/next-step guard, runbook
frontend smoke-demo order guard, bilingual readiness route guard, and frontend
demo/QA-source visibility guard, public-safe fixture quality boundary guard,
benchmark result isolation guard, and completion audit guard, the current full
regression is:

```text
Ran 440 tests in 73.130s
OK
```

The scope document adds a small documentation guard so future edits do not
accidentally turn deferred real-data validation into a current-goal requirement.

## Reporting Boundary

Safe to say:

- The MedScope Agent MVP has a working evidence-bounded architecture.
- The FHN skill path has a structured evidence protocol and visual execution strategy.
- The benchmark framework can evaluate real binary lesion masks when they are added.
- The current public fixture is only a smoke/readiness artifact.

Not safe to say:

- Real FHN benchmark completed.
- Metric-ready real benchmark completed.
- FHN X-ray lesion segmentation quality is clinically validated.
- Missing mask, missing MRI, or missing clinical context means a negative finding.
