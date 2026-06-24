from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.evidence_gateway_snapshot import build_evidence_gateway_snapshot


class EvidenceGatewaySnapshotTest(unittest.TestCase):
    def test_snapshot_summarizes_real_visual_run_and_candidate_only_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary_path = root / "vision_summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "schema_version": "vision_evidence_eval_summary.v1",
                        "aggregate": {
                            "non_reference_auto_eval_ready_count": 1,
                        },
                        "non_reference_attempts": [
                            {
                                "case_id": "brats2021_00030",
                                "prompt_status": "ok",
                                "auto_eval_status": "ok",
                                "prompt_source": "vision_model_bbox",
                                "real_vlm_call_attempted": True,
                                "real_medsam2_call_attempted": True,
                                "reference_mask_used": False,
                                "reference_mask_role": "evaluation_only",
                                "medsam2_ready": True,
                                "metrics": {
                                    "whole_tumor_dice": 0.83253389,
                                    "tumor_core_dice": 0.39318669,
                                    "enhancing_tumor_dice": 0.0,
                                    "whole_tumor_false_positive_component_count": 19,
                                },
                                "failure_types": [
                                    "low_quality_mask",
                                    "over_segmentation",
                                    "under_segmentation",
                                ],
                                "artifacts": {
                                    "mask_path": "mask.nii.gz",
                                    "overlay_path": "overlay.png",
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            queue_path = root / "candidate_queue.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "schema_version": "vision_evidence_candidate_queue.v1",
                        "candidate_count": 11,
                        "queue_items": [
                            {"candidate_type": "manual_review_label"},
                            {"candidate_type": "non_reference_metric_review"},
                            {"candidate_type": "non_reference_metric_review"},
                            {"candidate_type": "non_reference_metric_review"},
                        ],
                        "runtime_safety": {
                            "candidate_only": True,
                            "formal_knowledge_updated": False,
                            "formal_guideline_updated": False,
                            "diagnosis_report_updated": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            gate_path = root / "validation_gate.json"
            gate_path.write_text(
                json.dumps(
                    {
                        "schema_version": "vision_evidence_candidate_validation_gate.v1",
                        "review_summary": {
                            "item_count": 11,
                            "pending_count": 11,
                        },
                        "promotion_decision": {
                            "status": "blocked",
                            "formal_update_allowed": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            snapshot = build_evidence_gateway_snapshot(
                vision_summary_path=summary_path,
                candidate_queue_path=queue_path,
                validation_gate_path=gate_path,
                output_dir=root / "out",
            )

            self.assertEqual(snapshot["schema_version"], "evidence_gateway_snapshot.v1")
            self.assertEqual(
                snapshot["architecture_model"]["recommended_narrative"],
                "Clinical Evidence Pipeline + Agentic Runtime / Evidence Gateway",
            )
            self.assertTrue(snapshot["architecture_model"]["not_five_parallel_agents"])
            self.assertEqual(snapshot["overall_status"], "demonstrable_but_not_clinical_grade")
            self.assertEqual(snapshot["phase_b_visual_evidence"]["auto_eval_status"], "ok")
            self.assertTrue(snapshot["phase_b_visual_evidence"]["medsam2_ready"])
            self.assertEqual(
                snapshot["phase_b_visual_evidence"]["key_metrics"]["whole_tumor_dice"],
                0.832534,
            )
            self.assertEqual(snapshot["candidate_gate"]["candidate_count"], 11)
            self.assertEqual(snapshot["candidate_gate"]["non_reference_metric_review_count"], 3)
            self.assertEqual(snapshot["candidate_gate"]["promotion_status"], "blocked")
            self.assertFalse(snapshot["candidate_gate"]["formal_update_allowed"])
            self.assertIn(
                "真实 VLM + MedSAM2 视觉链路已经可演示",
                snapshot["claims"]["can_claim"],
            )
            self.assertIn(
                "不能宣称通用医学图像分割已经达到临床级",
                snapshot["claims"]["cannot_claim"],
            )

            markdown = (root / "out" / "evidence_gateway_snapshot.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("不是五个并列 Agent", markdown)
            self.assertIn("whole_tumor_dice", markdown)
            self.assertTrue((root / "out" / "evidence_gateway_snapshot.json").exists())


if __name__ == "__main__":
    unittest.main()
