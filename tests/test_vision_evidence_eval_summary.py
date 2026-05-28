from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.vision_evidence_eval_summary import (
    build_vision_evidence_candidate_queue,
    build_vision_evidence_candidate_validation_gate,
    build_vision_evidence_reviewer_notes_template,
    build_vision_evidence_eval_summary,
)


class FakeBratsEvaluator:
    def evaluate(self, prediction_mask_path, reference_mask_path):
        return {
            "whole_tumor_dice": 0.8,
            "whole_tumor_iou": 0.67,
            "whole_tumor_absolute_volume_error_ml": 1.5,
            "whole_tumor_false_positive_component_count": 2,
            "whole_tumor_false_negative_component_count": 1,
        }


class VisionEvidenceEvalSummaryTest(unittest.TestCase):
    def test_summary_merges_reference_metrics_and_no_mask_visual_fact_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brats_result = root / "brats_case_result.json"
            brats_result.write_text(
                json.dumps(
                    {
                        "result": {
                            "modality": "mri",
                            "image_outputs": {
                                "mask_path": str(root / "brats_mask.nii.gz"),
                                "overlay_path": str(root / "brats_overlay.png"),
                            },
                            "visual_evidence": {
                                "suspected_visual_findings": [
                                    "whole tumor candidate mask generated"
                                ],
                                "completeness": {
                                    "whole_tumor": {"status": "supported"},
                                    "enhancing_tumor": {"status": "missing"},
                                },
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            brats_summary = root / "brats_summary.json"
            brats_summary.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "case_count": 1,
                        "ok_count": 1,
                        "failed_case_ids": [],
                        "cases": [
                            {
                                "case_id": "brats_case_1",
                                "status": "ok",
                                "mode": "brats_medsam2_model",
                                "result_json_path": str(brats_result),
                                "overlay_path": str(root / "brats_overlay.png"),
                                "evaluation": {
                                    "whole_tumor_dice": 0.91,
                                    "tumor_core_dice": 0.42,
                                    "enhancing_tumor_dice": 0.0,
                                    "whole_tumor_iou": 0.83,
                                    "tumor_core_iou": 0.3,
                                    "enhancing_tumor_iou": 0.0,
                                    "whole_tumor_absolute_volume_error_ml": 1.2,
                                    "tumor_core_absolute_volume_error_ml": 2.3,
                                    "enhancing_tumor_absolute_volume_error_ml": 0.4,
                                    "whole_tumor_false_positive_component_count": 1,
                                    "tumor_core_false_positive_component_count": 2,
                                    "enhancing_tumor_false_positive_component_count": 0,
                                    "whole_tumor_false_negative_component_count": 0,
                                    "tumor_core_false_negative_component_count": 1,
                                    "enhancing_tumor_false_negative_component_count": 3,
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            fhn_response = root / "fhn_response.json"
            fhn_response.write_text(
                json.dumps(
                    {
                        "case_id": "case_fhn",
                        "structured_visual_facts": [
                            {"finding_id": "finding_1", "quality_level": "medium"},
                            {"finding_id": "finding_2", "quality_level": "low"},
                        ],
                        "used_visual_facts": [{"finding_id": "finding_1"}],
                        "excluded_visual_facts": [
                            {
                                "finding_id": "finding_2",
                                "exclusion_reason": "non_independent_evidence",
                            }
                        ],
                        "runtime_gateway_trace": {
                            "trace_consistency": {
                                "all_stage_artifacts_available": True,
                                "all_stage_schemas_present": True,
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            fhn_pipeline = root / "fhn_pipeline_summary.json"
            fhn_pipeline.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "disease_key": "femoral_head_necrosis",
                        "visual_evidence_bundle": {
                            "image_context": {"modality": "xray"},
                            "image_outputs": {
                                "mask_path": str(root / "fhn_mask.png"),
                                "overlay_path": str(root / "fhn_overlay.png"),
                                "comparison_path": str(root / "fhn_comparison.png"),
                            },
                            "quality_warnings": [{"code": "overlap"}],
                            "numeric_evidence": {
                                "diagnosis_usable_finding_count": 1,
                                "diagnosis_unusable_finding_count": 1,
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = build_vision_evidence_eval_summary(
                brats_summary_path=brats_summary,
                fhn_response_path=fhn_response,
                fhn_pipeline_summary_path=fhn_pipeline,
                output_dir=root / "out",
            )

            self.assertEqual(payload["schema_version"], "vision_evidence_eval_summary.v1")
            self.assertEqual(payload["aggregate"]["case_count"], 2)
            self.assertEqual(payload["aggregate"]["reference_case_count"], 1)
            self.assertEqual(payload["aggregate"]["no_mask_case_count"], 1)
            self.assertEqual(payload["aggregate"]["diagnosis_allowed_count"], 1)

            by_case = {case["case_id"]: case for case in payload["cases"]}
            self.assertEqual(by_case["brats_case_1"]["reference_available"], True)
            self.assertEqual(by_case["brats_case_1"]["mean_dice"], 0.443333)
            self.assertEqual(by_case["brats_case_1"]["mean_iou"], 0.376667)
            self.assertEqual(by_case["brats_case_1"]["mean_absolute_volume_error_ml"], 1.3)
            self.assertEqual(by_case["brats_case_1"]["false_positive_component_count"], 3)
            self.assertEqual(by_case["brats_case_1"]["false_negative_component_count"], 4)
            self.assertIn("under_segmentation", by_case["brats_case_1"]["failure_types"])
            self.assertFalse(
                any("Add IoU" in action for action in payload["next_actions"])
            )
            self.assertTrue(
                any("Review low-performing" in action for action in payload["next_actions"])
            )
            self.assertFalse(
                any("Add manual review labels" in action for action in payload["next_actions"])
            )
            self.assertTrue(
                any("Run human review" in action for action in payload["next_actions"])
            )
            self.assertEqual(by_case["case_fhn"]["visual_fact_count"], 2)
            self.assertEqual(by_case["case_fhn"]["adopted_fact_count"], 1)
            self.assertEqual(by_case["case_fhn"]["excluded_fact_count"], 1)
            self.assertEqual(by_case["case_fhn"]["quality_warning_count"], 1)
            self.assertEqual(by_case["case_fhn"]["diagnosis_allowed"], True)
            self.assertEqual(
                by_case["case_fhn"]["manual_review_counts"],
                {"accepted": 1, "rejected": 1, "uncertain": 0},
            )
            self.assertEqual(
                by_case["case_fhn"]["manual_review_items"],
                [
                    {
                        "finding_id": "finding_1",
                        "target": None,
                        "suggested_label": "accepted",
                        "review_status": "pending_human_review",
                        "reason": "adopted_visual_fact",
                    },
                    {
                        "finding_id": "finding_2",
                        "target": None,
                        "suggested_label": "rejected",
                        "review_status": "pending_human_review",
                        "reason": "non_independent_evidence",
                    },
                ],
            )
            self.assertEqual(payload["aggregate"]["manual_review_counts"]["accepted"], 1)
            self.assertEqual(payload["aggregate"]["manual_review_counts"]["rejected"], 1)

            self.assertTrue((root / "out" / "vision_evidence_eval_summary.json").exists())
            markdown = (root / "out" / "vision_evidence_eval_summary.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("brats_case_1", markdown)
            self.assertIn("case_fhn", markdown)
            self.assertIn("Manual Review Items", markdown)
            self.assertIn("finding_1", markdown)
            self.assertIn("accepted", markdown)
            self.assertIn("pending_human_review", markdown)

    def test_summary_backfills_extended_reference_metrics_from_result_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brats_result = root / "brats_case_result.json"
            brats_result.write_text(
                json.dumps(
                    {
                        "result": {
                            "modality": "mri",
                            "image_outputs": {
                                "mask_path": "prediction.nii.gz",
                                "overlay_path": "overlay.png",
                            },
                            "visual_evidence": {},
                        },
                        "segmentation_prompt": {
                            "reference_mask_path": "reference.nii.gz",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            brats_summary = root / "brats_summary.json"
            brats_summary.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "brats_case_1",
                                "status": "ok",
                                "result_json_path": str(brats_result),
                                "evaluation": {"whole_tumor_dice": 0.1},
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            fhn_response = root / "fhn_response.json"
            fhn_response.write_text(
                json.dumps({"case_id": "case_fhn"}, ensure_ascii=False),
                encoding="utf-8",
            )

            payload = build_vision_evidence_eval_summary(
                brats_summary_path=brats_summary,
                fhn_response_path=fhn_response,
                fhn_pipeline_summary_path=None,
                output_dir=root / "out",
                brats_evaluator=FakeBratsEvaluator(),
            )

            brats_case = payload["cases"][0]
            self.assertEqual(brats_case["mean_dice"], 0.8)
            self.assertEqual(brats_case["mean_iou"], 0.67)
            self.assertEqual(brats_case["mean_absolute_volume_error_ml"], 1.5)
            self.assertEqual(brats_case["false_positive_component_count"], 2)
            self.assertEqual(brats_case["false_negative_component_count"], 1)

    def test_summary_includes_non_reference_vlm_prompt_and_medsam2_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brats_summary = root / "brats_summary.json"
            brats_summary.write_text(
                json.dumps({"cases": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            fhn_response = root / "fhn_response.json"
            fhn_response.write_text(
                json.dumps({"case_id": "case_fhn"}, ensure_ascii=False),
                encoding="utf-8",
            )
            prompt_summary = root / "prompt_summary.json"
            prompt_summary.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "image_path": "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz",
                        "slice_index": 100,
                        "prompt_source": "vision_model_bbox",
                        "boxes": [[50, 130, 130, 195]],
                        "real_call_attempted": True,
                        "data_boundary": {
                            "reference_mask_used": False,
                            "prompt_role": "vision_model_candidate_localization",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            auto_eval_summary = root / "auto_eval_summary.json"
            auto_eval_summary.write_text(
                json.dumps(
                    {
                        "status": "not_ready",
                        "case_id": "brats2021_00030",
                        "prompt_source": "vision_model_bbox",
                        "real_call_attempted": False,
                        "medsam2_configuration": {
                            "real_call_ready": False,
                            "missing_command_template_placeholders": [
                                "image_path",
                                "output_mask_path",
                                "prompt_json",
                            ],
                        },
                        "data_boundary": {
                            "reference_mask_role": "evaluation_only",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = build_vision_evidence_eval_summary(
                brats_summary_path=brats_summary,
                fhn_response_path=fhn_response,
                fhn_pipeline_summary_path=None,
                non_reference_prompt_summary_path=prompt_summary,
                non_reference_auto_eval_summary_path=auto_eval_summary,
                output_dir=root / "out",
            )

            self.assertEqual(payload["aggregate"]["non_reference_attempt_count"], 1)
            self.assertEqual(payload["aggregate"]["non_reference_prompt_ok_count"], 1)
            self.assertEqual(payload["aggregate"]["non_reference_auto_eval_ready_count"], 0)
            attempt = payload["non_reference_attempts"][0]
            self.assertEqual(attempt["case_id"], "brats2021_00030")
            self.assertEqual(attempt["prompt_status"], "ok")
            self.assertEqual(attempt["auto_eval_status"], "not_ready")
            self.assertEqual(attempt["prompt_source"], "vision_model_bbox")
            self.assertFalse(attempt["reference_mask_used"])
            self.assertFalse(attempt["medsam2_ready"])
            self.assertEqual(attempt["box_count"], 1)
            self.assertTrue(
                any("Configure MedSAM2" in action for action in payload["next_actions"])
            )
            markdown = (root / "out" / "vision_evidence_eval_summary.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Non-reference Attempts", markdown)
            self.assertIn("brats2021_00030", markdown)
            self.assertIn("not_ready", markdown)

    def test_summary_marks_successful_non_reference_medsam2_run_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brats_summary = root / "brats_summary.json"
            brats_summary.write_text(
                json.dumps({"cases": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            fhn_response = root / "fhn_response.json"
            fhn_response.write_text(
                json.dumps({"case_id": "case_fhn"}, ensure_ascii=False),
                encoding="utf-8",
            )
            prompt_summary = root / "prompt_summary.json"
            prompt_summary.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "image_path": "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz",
                        "slice_index": 100,
                        "prompt_source": "vision_model_bbox",
                        "boxes": [[50, 130, 130, 195]],
                        "real_call_attempted": True,
                        "data_boundary": {"reference_mask_used": False},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            auto_eval_summary = root / "auto_eval_summary.json"
            auto_eval_summary.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "case_id": "brats2021_00030",
                        "prompt_source": "vision_model_bbox",
                        "real_call_attempted": True,
                        "evaluation": {
                            "whole_tumor_dice": 0.83,
                            "whole_tumor_false_positive_component_count": 19,
                            "enhancing_tumor_dice": 0.0,
                        },
                        "data_boundary": {"reference_mask_role": "evaluation_only"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = build_vision_evidence_eval_summary(
                brats_summary_path=brats_summary,
                fhn_response_path=fhn_response,
                fhn_pipeline_summary_path=None,
                non_reference_prompt_summary_path=prompt_summary,
                non_reference_auto_eval_summary_path=auto_eval_summary,
                output_dir=root / "out",
            )

            self.assertEqual(payload["aggregate"]["non_reference_auto_eval_ready_count"], 1)
            attempt = payload["non_reference_attempts"][0]
            self.assertTrue(attempt["medsam2_ready"])
            self.assertEqual(attempt["metrics"]["whole_tumor_dice"], 0.83)
            self.assertIn("under_segmentation", attempt["failure_types"])
            self.assertIn("over_segmentation", attempt["failure_types"])
            self.assertTrue(
                any("Review non-reference" in action for action in payload["next_actions"])
            )

    def test_candidate_queue_routes_failures_and_manual_review_as_candidate_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary = {
                "schema_version": "vision_evidence_eval_summary.v1",
                "aggregate": {"case_count": 2},
                "cases": [
                    {
                        "case_id": "brats_case_1",
                        "disease_skill": "diffuse_glioma_brats",
                        "modality": "mri",
                        "reference_available": True,
                        "failure_types": ["under_segmentation"],
                        "metrics": {
                            "whole_tumor_dice": 0.1,
                            "whole_tumor_iou": 0.05,
                            "whole_tumor_false_negative_component_count": 3,
                        },
                        "diagnosis_allowed": False,
                    },
                    {
                        "case_id": "case_fhn",
                        "disease_skill": "femoral_head_necrosis",
                        "modality": "xray",
                        "reference_available": False,
                        "failure_types": ["low_quality_mask"],
                        "quality_warning_count": 1,
                        "manual_review_items": [
                            {
                                "finding_id": "finding_1",
                                "target": "sclerotic_band",
                                "suggested_label": "accepted",
                                "review_status": "pending_human_review",
                                "reason": "adopted_visual_fact",
                            }
                        ],
                        "diagnosis_allowed": True,
                    },
                ],
                "non_reference_attempts": [
                    {
                        "case_id": "brats_case_1",
                        "disease_skill": "diffuse_glioma_brats",
                        "prompt_status": "ok",
                        "auto_eval_status": "not_ready",
                        "prompt_source": "vision_model_bbox",
                        "medsam2_ready": False,
                        "missing_medsam2_configuration": ["image_path"],
                    }
                ],
                "next_actions": [
                    "Route failure records to self_evolving_queue as candidate-only visual protocol reviews."
                ],
            }

            queue = build_vision_evidence_candidate_queue(
                eval_summary=summary,
                output_dir=root / "out",
            )

            self.assertEqual(queue["schema_version"], "vision_evidence_candidate_queue.v1")
            self.assertEqual(queue["status"], "candidate_only")
            self.assertEqual(queue["source_summary_schema_version"], "vision_evidence_eval_summary.v1")
            self.assertEqual(queue["candidate_count"], 4)
            self.assertEqual(
                queue["runtime_gateway_mapping"]["stages"],
                [
                    "stop_hooks_reflection",
                    "self_evolving_queue",
                    "candidate_validation_gate",
                ],
            )
            self.assertTrue(queue["runtime_safety"]["candidate_artifacts_only"])
            self.assertFalse(queue["runtime_safety"]["formal_skill_updated"])
            self.assertFalse(queue["runtime_safety"]["formal_guideline_updated"])
            self.assertFalse(queue["runtime_safety"]["diagnosis_report_updated"])
            self.assertTrue(
                all(
                    item["validation_status"] == "pending_review"
                    and item["allowed_action"] == "candidate_review_only"
                    and item["formal_update_allowed"] is False
                    for item in queue["queue_items"]
                )
            )
            self.assertIn(
                "visual_protocol_review",
                {item["candidate_type"] for item in queue["queue_items"]},
            )
            self.assertIn(
                "manual_review_label",
                {item["candidate_type"] for item in queue["queue_items"]},
            )
            self.assertIn(
                "runtime_configuration_review",
                {item["candidate_type"] for item in queue["queue_items"]},
            )
            self.assertTrue((root / "out" / "vision_evidence_candidate_queue.json").exists())
            markdown = (root / "out" / "vision_evidence_candidate_queue.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("candidate-only", markdown)
            self.assertIn("formal_update_allowed=false", markdown)

    def test_candidate_queue_routes_successful_non_reference_metric_failures_as_candidate_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary = {
                "schema_version": "vision_evidence_eval_summary.v1",
                "aggregate": {"case_count": 0},
                "cases": [],
                "non_reference_attempts": [
                    {
                        "case_id": "brats2021_00030",
                        "disease_skill": "diffuse_glioma_brats",
                        "modality": "mri",
                        "prompt_status": "ok",
                        "auto_eval_status": "ok",
                        "prompt_source": "vision_model_bbox",
                        "medsam2_ready": True,
                        "failure_types": ["under_segmentation", "over_segmentation"],
                        "metrics": {
                            "whole_tumor_dice": 0.83,
                            "enhancing_tumor_dice": 0.0,
                            "whole_tumor_false_positive_component_count": 19,
                        },
                    }
                ],
            }

            queue = build_vision_evidence_candidate_queue(
                eval_summary=summary,
                output_dir=root / "out",
            )

            self.assertEqual(queue["candidate_count"], 2)
            self.assertEqual(
                {item["candidate_type"] for item in queue["queue_items"]},
                {"non_reference_metric_review"},
            )
            self.assertTrue(
                all(
                    item["allowed_action"] == "candidate_review_only"
                    and item["formal_update_allowed"] is False
                    for item in queue["queue_items"]
                )
            )

    def test_candidate_validation_gate_records_reviewer_notes_without_formal_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            queue = {
                "schema_version": "vision_evidence_candidate_queue.v1",
                "status": "candidate_only",
                "queue_items": [
                    {
                        "item_id": "case_1_under_segmentation_visual_protocol_review",
                        "source_case_id": "case_1",
                        "candidate_type": "visual_protocol_review",
                        "source_warning_code": "under_segmentation",
                        "validation_status": "pending_review",
                        "allowed_action": "candidate_review_only",
                        "formal_update_allowed": False,
                    },
                    {
                        "item_id": "case_2_finding_1_manual_review_label",
                        "source_case_id": "case_2",
                        "candidate_type": "manual_review_label",
                        "source_warning_code": "manual_review_required",
                        "validation_status": "pending_review",
                        "allowed_action": "candidate_review_only",
                        "formal_update_allowed": False,
                    },
                ],
            }
            reviewer_notes = {
                "schema_version": "vision_evidence_reviewer_notes.v1",
                "reviewer": "reviewer_a",
                "notes": [
                    {
                        "item_id": "case_1_under_segmentation_visual_protocol_review",
                        "review_status": "needs_revision",
                        "reviewer_note": "Enhancing tumor is missed; revise visual protocol.",
                    },
                    {
                        "item_id": "case_2_finding_1_manual_review_label",
                        "review_status": "accepted",
                        "reviewer_note": "Candidate label matches the displayed region.",
                    },
                ],
            }

            gate = build_vision_evidence_candidate_validation_gate(
                candidate_queue=queue,
                reviewer_notes=reviewer_notes,
                output_dir=root / "out",
            )

            self.assertEqual(
                gate["schema_version"],
                "vision_evidence_candidate_validation_gate.v1",
            )
            self.assertEqual(gate["source_queue_schema_version"], "vision_evidence_candidate_queue.v1")
            self.assertEqual(gate["review_summary"]["reviewed_count"], 2)
            self.assertEqual(gate["review_summary"]["accepted_count"], 1)
            self.assertEqual(gate["review_summary"]["needs_revision_count"], 1)
            self.assertEqual(gate["review_summary"]["pending_count"], 0)
            self.assertEqual(gate["promotion_decision"]["status"], "blocked")
            self.assertEqual(
                gate["promotion_decision"]["reason"],
                "candidate_items_reviewed_but_formal_promotion_requires_separate_approval",
            )
            self.assertFalse(gate["promotion_decision"]["formal_update_allowed"])
            self.assertFalse(gate["runtime_safety"]["formal_skill_updated"])
            self.assertFalse(gate["runtime_safety"]["formal_guideline_updated"])
            self.assertFalse(gate["runtime_safety"]["diagnosis_report_updated"])
            self.assertTrue(
                all(
                    validation["formal_update_allowed"] is False
                    for validation in gate["item_validations"]
                )
            )
            self.assertEqual(
                gate["item_validations"][0]["reviewer_note"]["review_status"],
                "needs_revision",
            )
            self.assertTrue(
                (root / "out" / "vision_evidence_candidate_validation_gate.json").exists()
            )
            markdown = (
                root / "out" / "vision_evidence_candidate_validation_gate.md"
            ).read_text(encoding="utf-8")
            self.assertIn("formal_update_allowed=false", markdown)
            self.assertIn("needs_revision", markdown)

    def test_reviewer_notes_template_preserves_pending_human_review_without_fake_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            queue = {
                "schema_version": "vision_evidence_candidate_queue.v1",
                "queue_items": [
                    {
                        "item_id": "case_1_under_segmentation_visual_protocol_review",
                        "source_case_id": "case_1",
                        "candidate_type": "visual_protocol_review",
                        "source_warning_code": "under_segmentation",
                    }
                ],
            }

            template = build_vision_evidence_reviewer_notes_template(
                candidate_queue=queue,
                output_dir=root / "out",
            )

            self.assertEqual(template["schema_version"], "vision_evidence_reviewer_notes.v1")
            self.assertEqual(template["review_status"], "pending_human_review")
            self.assertEqual(template["notes"][0]["review_status"], "pending_review")
            self.assertEqual(template["notes"][0]["reviewer_note"], "")
            self.assertEqual(template["notes"][0]["item_id"], "case_1_under_segmentation_visual_protocol_review")
            self.assertTrue(
                (root / "out" / "vision_evidence_reviewer_notes_template.json").exists()
            )


if __name__ == "__main__":
    unittest.main()
