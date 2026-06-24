import tempfile
import unittest
from pathlib import Path

from scripts.candidate_promotion_dry_run import build_candidate_promotion_dry_run


class CandidatePromotionDryRunTest(unittest.TestCase):
    def test_approved_candidate_generates_proposal_without_formal_update(self) -> None:
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
                        "proposal": "Revise enhancing tumor visual protocol.",
                        "evidence": {"whole_tumor_dice": 0.83, "enhancing_tumor_dice": 0.0},
                        "validation_status": "pending_review",
                        "allowed_action": "candidate_review_only",
                        "formal_update_allowed": False,
                    },
                    {
                        "item_id": "case_2_false_positive_review",
                        "source_case_id": "case_2",
                        "candidate_type": "quality_gate_rule",
                        "source_warning_code": "false_positive_components",
                        "proposal": "Add component-count QC threshold.",
                        "evidence": {"false_positive_component_count": 19},
                        "validation_status": "pending_review",
                        "allowed_action": "candidate_review_only",
                        "formal_update_allowed": False,
                    },
                ],
            }
            validation_gate = {
                "schema_version": "vision_evidence_candidate_validation_gate.v1",
                "source_queue_schema_version": "vision_evidence_candidate_queue.v1",
                "review_summary": {
                    "item_count": 2,
                    "reviewed_count": 2,
                    "accepted_count": 1,
                    "needs_revision_count": 1,
                    "pending_count": 0,
                },
                "item_validations": [
                    {
                        "item_id": "case_1_under_segmentation_visual_protocol_review",
                        "source_case_id": "case_1",
                        "candidate_type": "visual_protocol_review",
                        "source_warning_code": "under_segmentation",
                        "review_status": "accepted",
                        "validation_status": "reviewed",
                        "reviewer_note": {
                            "review_status": "accepted",
                            "reviewer_note": "Failure is reproducible in this case.",
                        },
                        "formal_update_allowed": False,
                    },
                    {
                        "item_id": "case_2_false_positive_review",
                        "source_case_id": "case_2",
                        "candidate_type": "quality_gate_rule",
                        "source_warning_code": "false_positive_components",
                        "review_status": "needs_revision",
                        "validation_status": "reviewed",
                        "reviewer_note": {
                            "review_status": "needs_revision",
                            "reviewer_note": "Needs one more dataset before proposal.",
                        },
                        "formal_update_allowed": False,
                    },
                ],
                "promotion_decision": {
                    "status": "blocked",
                    "reason": "candidate_items_reviewed_but_formal_promotion_requires_separate_approval",
                    "formal_update_allowed": False,
                },
            }

            dry_run = build_candidate_promotion_dry_run(
                candidate_queue=queue,
                validation_gate=validation_gate,
                output_dir=root / "out",
            )

            self.assertEqual(dry_run["schema_version"], "candidate_promotion_dry_run.v1")
            self.assertEqual(dry_run["source_queue_schema_version"], "vision_evidence_candidate_queue.v1")
            self.assertEqual(
                dry_run["source_validation_gate_schema_version"],
                "vision_evidence_candidate_validation_gate.v1",
            )
            self.assertEqual(dry_run["promotion_decision"]["status"], "proposal_only")
            self.assertFalse(dry_run["promotion_decision"]["formal_update_allowed"])
            self.assertEqual(dry_run["proposal_count"], 1)
            self.assertEqual(
                dry_run["promotion_proposals"][0]["item_id"],
                "case_1_under_segmentation_visual_protocol_review",
            )
            self.assertEqual(
                dry_run["promotion_proposals"][0]["required_approval"],
                "explicit_human_promotion_approval",
            )
            self.assertEqual(
                dry_run["promotion_proposals"][0]["proposed_artifact"],
                "candidate_knowledge_patch",
            )
            self.assertFalse(dry_run["runtime_safety"]["formal_knowledge_updated"])
            self.assertFalse(dry_run["runtime_safety"]["formal_guideline_updated"])
            self.assertFalse(dry_run["runtime_safety"]["diagnosis_report_updated"])
            self.assertTrue((root / "out" / "candidate_promotion_dry_run.json").exists())
            markdown = (root / "out" / "candidate_promotion_dry_run.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("proposal_only", markdown)
            self.assertIn("formal_knowledge_updated=false", markdown)


if __name__ == "__main__":
    unittest.main()
