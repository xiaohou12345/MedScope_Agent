# ONFH Xray Original-Flow Mock Evaluation, 2026-06-09

## Purpose

This note records the ONFH Xray experiment that keeps the MedScope service and diagnosis/report chain as close as possible to the repository's original pipeline, while replacing only the visual evidence source with reviewed CVAT/COCO Xray masks.

The main goal is to avoid mixing temporary side pipelines with formal agent outputs. In this experiment, the primary prediction is parsed from the final report produced by the service flow. Visual finding to stage mappings are retained only as audit/debug columns.

## Original Flow

The service path used in this experiment is:

```text
MedScopeService.handle_request()
  -> GaoDoctorAgent.handle_message()
      -> GaoDoctorAgent.handle_patient_case()
          -> visual analysis step
          -> DiagnosisDoctorAgent.generate_report()
              -> ReportAgent.build_report()
```

For ONFH no-mask Xray cases, `GaoDoctorAgent` supports an injectable visual runner through:

```python
GaoDoctorAgent(no_mask_visual_pipeline_runner=runner)
```

This injection point is part of the GaoDoctorAgent flow. It allows the visual evidence source to be replaced without replacing `DiagnosisDoctorAgent` or `ReportAgent`.

## Minimal Replacement

The only intended replacement is:

```text
visual analysis source
```

Specifically:

```text
Default no-mask visual pipeline
  -> OnfhCocoMockVisualRunner
```

The runner converts reviewed Xray COCO masks into the `visual_analysis_result` structure expected by `DiagnosisDoctorAgent`.

The following components are not replaced:

```text
MedScopeService
GaoDoctorAgent orchestration
DiagnosisDoctorAgent final report generation
ReportAgent report formatting
case memory save path
```

This means the experiment is not using `CandidateDiagnosisAgent`, visual-stage heuristic scoring, or any temporary diagnosis-side runner as the formal output.

## Data Source

Clean COCO export:

```text
/data/gongwenxin/datasets/onfh/cjfh/exports/onfh_mri_xray_coco_instances_clean_20260605
```

Relevant files:

```text
manifest.csv
instances.csv
image_tags.csv
instances_coco.json
```

Xray GT is read from:

```text
image_tags.csv where modality == "Xray"
```

The Xray side-level GT distribution is:

```text
3期       13
2期       11
未发现异常 10
total    34
```

The Xray task uses a three-class output space:

```text
未发现异常
2期
3期
```

Xray does not attempt to separate ARCO I from ARCO II in this evaluation. Historical labels such as `ARCO II`, `ARCO I /II`, `ARCO III`, and `无明显异常` are normalized into the three Xray classes above.

For this and future Xray evaluations, Xray GT is the default scoring target. MRI tags are not used for primary Xray scoring. They may be retained only as reference metadata or used in explicitly labeled cross-modality experiments.

## Leakage Control

MRI GT must not be fed into visual evidence for valid Xray experiments.

The current script default is:

```text
include_mri_gt_in_visual = false
```

MRI GT can only be included with an explicit debug flag:

```bash
--include-mri-gt-in-visual
```

That flag should be treated as a leakage/debug setting, not a valid evaluation setting.

## Normal Cases Without Masks

Some Xray GT `未发现异常` cases have no COCO mask. These must not be dropped from Xray GT evaluation.

In the current script, Xray images with GT tags but no mask still enter the original service flow. Their mock visual findings are empty, and the final report is scored normally against Xray GT.

This keeps the evaluation at the full Xray GT scope:

```text
19 Xray images
34 side-level GT cases
```

## Command

The current original-flow mock run was:

```bash
python scripts/xray_mask_mock_eval.py \
  --export-dir /data/gongwenxin/datasets/onfh/cjfh/exports/onfh_mri_xray_coco_instances_clean_20260605 \
  --output-dir output/fake/original_flow_full_mock_xray_gt_agent_final_20260610_collapse_aligned \
  --side-mapping ap_flip
```

Output files:

```text
output/fake/original_flow_full_mock_xray_gt_agent_final_20260610_collapse_aligned/summary.json
output/fake/original_flow_full_mock_xray_gt_agent_final_20260610_collapse_aligned/side_level_eval.csv
output/fake/original_flow_full_mock_xray_gt_agent_final_20260610_collapse_aligned/instance_level_visual_outputs.csv
```

## Primary Metric Definition

Primary prediction:

```text
agent_final_stage
agent_loose_stage
```

`agent_final_stage` is parsed from the final report. `agent_loose_stage` allows a looser parsing of the same final report text, extracting a provisional stage from the tendency text even if the report also contains conservative evidence-limit language. It does not call a separate diagnosis Agent.

Primary GT:

```text
gt_xray_stage
```

This is aggregated from Xray tags per image side by max severity:

```text
未发现异常 < 2期 < 3期
```

Main correctness column:

```text
correct = agent_final_stage == gt_xray_stage
loose_correct = agent_loose_stage == gt_xray_stage
```

## Result

Run output:

```text
runnable_xray_images: 19
evaluated_images: 19
evaluable_side_cases: 34
```

Final-report stage accuracy after ONFH Xray evidence-mapping adaptation:

```text
correct: 16 / 34
accuracy: 47.06%
abstained: 9 / 34
coverage: 73.53%
non_abstain_correct: 16 / 25
non_abstain_accuracy: 64.00%
```

By Xray GT stage (Loose Metrics):

```text
未发现异常: 0 / 10 = 0.00%
3期       : 12 / 13 = 92.31%
2期       : 4 / 11 = 36.36%
```

Confusion matrix (Loose Metrics):

```text
GT 未发现异常 -> abstain: 9, 2期: 1
GT 3期       -> abstain: 0, 3期: 12, 2期: 1
GT 2期       -> abstain: 0, 3期: 7, 2期: 4
```

## Interpretation

The initial experiments with the original service chain yielded 11.76% accuracy and 17.65% coverage because critical Xray mock targets such as `subchondral_fracture` were not being carried forward as diagnosis-usable structural evidence. After adapting this mapping, the service chain forwards these findings as "ARCO III" or "ARCO II" tendencies.

The 2026-06-10 rerun aligned structural collapse handling across all active Xray evaluation paths. The shared runner-side rule treats `collapse`, `subchondral_fracture`, and `crescent_sign` as structural collapse evidence and normalizes them to the `collapse` target expected by `DiagnosisDoctorAgent`, while preserving the original target in metadata for audit.

The `loose` parsing mechanism extracts these tendency texts from the same final report when the report includes conservative disclaimers. It yields 47% end-to-end accuracy and 73.5% coverage without replacing `DiagnosisDoctorAgent` or `ReportAgent`.

## Current Script Contract

`scripts/xray_mask_mock_eval.py` currently follows this contract:

```text
visual source: reviewed Xray COCO mask, converted to visual_analysis_result
main flow: MedScopeService -> GaoDoctorAgent -> DiagnosisDoctorAgent -> ReportAgent
main prediction: final report stage parsed via `agent_final_stage` and `agent_loose_stage`
main GT: Xray tag stage from image_tags.csv
MRI GT: reference only, not primary scoring
visual finding stage: audit only
```
