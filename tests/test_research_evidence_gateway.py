import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.research_evidence_builder import (
    ResearchClaimBuilder,
    ResearchEvidenceExtractor,
    ResearchEvidenceRetriever,
    build_research_evidence_proposal,
    build_research_evidence_proposal_from_request,
    build_research_evidence_review_package,
    parse_pubmed_xml_metadata,
)


class ResearchEvidenceGatewayTest(unittest.TestCase):
    def test_retriever_falls_back_to_supplied_metadata_when_pubmed_is_unavailable_and_keeps_source_trace(self) -> None:
        def failing_pubmed_client(query: str, limit: int) -> list[dict]:
            raise RuntimeError("network unavailable")

        result = ResearchEvidenceRetriever(pubmed_client=failing_pubmed_client).retrieve(
            disease_key="femoral_head_necrosis",
            modality="MRI",
            research_question="MRI radiomics measurement protocol",
            supplied_metadata=[
                {
                    "title": "MRI radiomics for osteonecrosis",
                    "journal": "Skeletal Radiology",
                    "year": 2025,
                    "PMID": "45678901",
                    "DOI": "10.1000/onfh-radiomics",
                    "abstract": "A retrospective MRI radiomics study without reported sample size.",
                    "source_type": "journal article",
                }
            ],
            pubmed_enabled=True,
            pubmed_limit=3,
        )

        self.assertEqual(result["retrieval"]["status"], "pubmed_unavailable_supplied_metadata_fallback")
        self.assertTrue(result["retrieval"]["pubmed_retrieval_attempted"])
        self.assertEqual(result["retrieval"]["pubmed_result_count"], 0)
        self.assertIn("network unavailable", result["retrieval"]["pubmed_error"])
        evidence = result["normalized_research_evidence"][0]
        self.assertEqual(evidence["sample_size"], "unknown")
        self.assertEqual(evidence["source_trace"]["title"], "MRI radiomics for osteonecrosis")
        self.assertEqual(evidence["source_trace"]["journal"], "Skeletal Radiology")
        self.assertEqual(evidence["source_trace"]["PMID"], "45678901")
        self.assertEqual(evidence["source_trace"]["DOI"], "10.1000/onfh-radiomics")
        self.assertIn("retrospective MRI radiomics", evidence["source_trace"]["abstract"])
        self.assertEqual(evidence["source_trace"]["query"], result["retrieval"]["pubmed_query"])
        self.assertEqual(evidence["source_trace"]["source_type"], "peer_reviewed_journal")
        self.assertIn("retrieved_at", evidence["source_trace"])
        self.assertEqual(evidence["target_disease"], "femoral_head_necrosis")
        self.assertEqual(evidence["limitations"], ["unknown"])

    def test_extractor_marks_unknown_fields_without_fabricating_sample_size_or_modality(self) -> None:
        extraction = ResearchEvidenceExtractor().extract(
            disease_key="femoral_head_necrosis",
            modality="unknown",
            research_question="new imaging features",
            supplied_texts=[
                {
                    "source_id": "abstract_unknowns",
                    "title": "Exploratory osteonecrosis imaging findings",
                    "source_type": "journal article",
                    "text_kind": "abstract",
                    "text": "This abstract describes exploratory imaging findings but does not report modality or cohort size.",
                }
            ],
        )

        evidence = extraction["extracted_research_evidence"][0]
        self.assertEqual(evidence["sample_size"], "unknown")
        self.assertEqual(evidence["modality"], "unknown")
        self.assertEqual(evidence["source_trace"]["abstract"], "This abstract describes exploratory imaging findings but does not report modality or cohort size.")
        self.assertEqual(evidence["source_metadata"]["title"], "Exploratory osteonecrosis imaging findings")
        self.assertEqual(evidence["target_disease"], "femoral_head_necrosis")
        self.assertEqual(evidence["proposed_imaging_finding"], "unknown")
        self.assertEqual(evidence["proposed_measurement_or_ai_feature"], "unknown")

    def test_claim_builder_emits_canonical_candidate_claim_contract(self) -> None:
        claims = ResearchClaimBuilder().build_claims(
            disease_key="femoral_head_necrosis",
            normalized_research_evidence=[
                {
                    "source_id": "study_texture",
                    "source_ids": ["study_texture"],
                    "title": "MRI texture disorder score for ONFH",
                    "source_type": "peer_reviewed_journal",
                    "sample_size": 420,
                    "population": "adult hip pain cohort",
                    "modality": "MRI",
                    "evidence_level": "moderate",
                    "candidate_claim_type": "candidate_measurement_protocol",
                    "target_protocol_section": "quantitative_evidence_protocol.image_feature_quantification",
                    "limitations": ["retrospective study"],
                }
            ],
        )

        claim = claims[0]
        self.assertEqual(claim["claim_type"], "quantitative_feature")
        self.assertEqual(claim["legacy_candidate_type"], "candidate_measurement_protocol")
        self.assertEqual(claim["source_ids"], ["study_texture"])
        self.assertEqual(
            claim["proposed_skill_section"],
            "quantitative_evidence_protocol.image_feature_quantification",
        )
        self.assertEqual(claim["target_disease"], "femoral_head_necrosis")
        self.assertEqual(claim["guideline_conflict_status"], "not_evaluated")
        self.assertFalse(claim["promotion_allowed"])
        self.assertEqual(claim["diagnosis_usable_level"], "not_diagnosis_usable")
        self.assertTrue(claim["requires_human_review"])
        self.assertTrue(claim["exploratory_only"])

    def test_gateway_outputs_named_goal_gate_statuses_and_formal_update_false(self) -> None:
        package = build_research_evidence_review_package(
            disease_key="femoral_head_necrosis",
            target_skill_id="femoral_head_necrosis_v0.1",
            modality="MRI",
            research_question="MRI necrotic area ratio as supplemental measurement",
            supplied_metadata=[
                {
                    "source_id": "study_necrotic_ratio",
                    "title": "MRI necrotic area ratio for ONFH staging",
                    "source_type": "journal article",
                    "publication_year": 2025,
                    "study_design": "multi center retrospective",
                    "sample_size": 420,
                    "modality": "MRI",
                    "population": "adult hip pain cohort",
                    "evidence_level": "moderate",
                    "candidate_claim_type": "candidate_measurement_protocol",
                    "target_protocol_section": (
                        "quantitative_evidence_protocol.measurement_evidence"
                    ),
                }
            ],
            guideline_skill={
                "skill_id": "femoral_head_necrosis_v0.1",
                "supported_modalities": ["X-ray"],
                "evidence_protocol_sections": [
                    "quantitative_evidence_protocol.measurement_evidence"
                ],
            },
        )

        gate_status = package["gateway_review_artifact"]["review_items"][0]["gate_status"]
        self.assertEqual(
            set(gate_status),
            {
                "source_quality",
                "freshness",
                "applicability",
                "modality_match",
                "population_match",
                "sample_size",
                "guideline_conflict",
                "reproducibility_or_external_validation",
                "human_review_required",
            },
        )
        self.assertEqual(gate_status["modality_match"]["status"], "blocked")
        self.assertEqual(gate_status["guideline_conflict"]["status"], "requires_review")
        self.assertFalse(package["gateway_review_artifact"]["runtime_safety"]["formal_update"])
        self.assertFalse(package["proposal"]["quality_gate"]["runtime_safety"]["formal_update"])

    def test_extractor_builds_structured_evidence_from_abstract_text(self) -> None:
        extraction = ResearchEvidenceExtractor().extract(
            disease_key="femoral_head_necrosis",
            modality="MRI",
            research_question="MRI texture measurement protocol",
            supplied_texts=[
                {
                    "source_id": "abstract_texture_2025",
                    "title": "MRI texture features for early osteonecrosis",
                    "source_type": "journal article",
                    "year": 2025,
                    "doi": "10.1000/texture",
                    "text_kind": "abstract",
                    "text": (
                        "Multi-center retrospective study of 420 adult hip pain patients. "
                        "MRI texture disorder score and necrotic area ratio were evaluated "
                        "for early femoral head osteonecrosis. External validation is required. "
                        "Limitations include retrospective design and no guideline recommendation."
                    ),
                }
            ],
        )

        self.assertEqual(extraction["schema_version"], "research_evidence_extraction.v1")
        self.assertFalse(extraction["runtime_safety"]["formal_skill_updated"])
        self.assertFalse(extraction["runtime_safety"]["diagnosis_report_updated"])
        evidence = extraction["extracted_research_evidence"][0]
        self.assertEqual(evidence["source_id"], "abstract_texture_2025")
        self.assertEqual(evidence["title"], "MRI texture features for early osteonecrosis")
        self.assertEqual(evidence["publication_year"], 2025)
        self.assertEqual(evidence["source_type"], "peer_reviewed_journal")
        self.assertEqual(evidence["DOI"], "10.1000/texture")
        self.assertEqual(evidence["sample_size"], 420)
        self.assertEqual(evidence["population"], "adult hip pain patients")
        self.assertEqual(evidence["modality"], "MRI")
        self.assertEqual(evidence["study_design"], "multi_center_retrospective")
        self.assertEqual(evidence["evidence_level"], "moderate")
        self.assertEqual(evidence["candidate_claim_type"], "candidate_measurement_protocol")
        self.assertEqual(
            evidence["target_protocol_section"],
            "quantitative_evidence_protocol.measurement_evidence",
        )
        self.assertIn("texture disorder score", evidence["proposed_features"])
        self.assertIn("necrotic area ratio", evidence["proposed_features"])
        self.assertIn("retrospective design", evidence["limitations"])
        self.assertTrue(evidence["requires_external_validation"])
        self.assertFalse(evidence["formal_update_allowed"])
        self.assertFalse(evidence["diagnosis_allowed"])

    def test_extractor_handles_pdf_text_and_differential_clue_without_pdf_parsing(self) -> None:
        extraction = ResearchEvidenceExtractor().extract(
            disease_key="femoral_head_necrosis",
            modality="MRI",
            research_question="differential diagnosis clues",
            supplied_texts=[
                {
                    "source_id": "pdf_text_differential",
                    "title": "Differential MRI signs for hip pain",
                    "source_type": "journal article",
                    "publication_year": 2024,
                    "text_kind": "pdf_text",
                    "text": (
                        "Prospective validation study, n=160 adult hip pain cohort. "
                        "MRI findings may distinguish osteonecrosis from degenerative hip disease. "
                        "This differential diagnosis clue needs external validation."
                    ),
                }
            ],
        )

        evidence = extraction["extracted_research_evidence"][0]
        self.assertEqual(evidence["source_origin"], "supplied_pdf_text")
        self.assertEqual(evidence["study_design"], "prospective_validation")
        self.assertEqual(evidence["sample_size"], 160)
        self.assertEqual(evidence["candidate_claim_type"], "differential_diagnosis_clue")
        self.assertEqual(evidence["target_protocol_section"], "differential_diagnosis_protocol")
        self.assertIn("differential diagnosis clue", evidence["extraction_notes"])
        self.assertTrue(evidence["requires_external_validation"])

    def test_review_package_uses_extracted_text_when_metadata_is_not_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = build_research_evidence_review_package(
                disease_key="femoral_head_necrosis",
                target_skill_id="femoral_head_necrosis_v0.1",
                modality="MRI",
                research_question="MRI texture protocol",
                supplied_texts=[
                    {
                        "source_id": "text_texture",
                        "title": "MRI texture feature protocol for ONFH",
                        "source_type": "journal article",
                        "publication_year": 2025,
                        "text_kind": "abstract",
                        "text": (
                            "Multi-center retrospective study of 420 adult hip pain patients. "
                            "MRI texture disorder score was evaluated as a measurement protocol. "
                            "External validation is required."
                        ),
                    }
                ],
                guideline_skill={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "supported_modalities": ["X-ray"],
                    "evidence_protocol_sections": ["imaging_evidence_protocol"],
                },
                output_dir=root / "review",
            )

            self.assertEqual(
                package["research_evidence_extraction"]["schema_version"],
                "research_evidence_extraction.v1",
            )
            self.assertEqual(len(package["research_evidence_retrieval"]["normalized_research_evidence"]), 1)
            candidate = package["proposal"]["candidate_extensions"][0]
            self.assertEqual(candidate["candidate_type"], "candidate_measurement_protocol")
            self.assertEqual(candidate["source_id"], "text_texture")
            self.assertEqual(package["gateway_review_artifact"]["review_items"][0]["guideline_conflict_status"], "human_review_required")
            self.assertFalse(package["runtime_safety"]["formal_skill_updated"])
            self.assertFalse(package["runtime_safety"]["diagnosis_report_updated"])
            self.assertTrue((root / "review" / "research_evidence_extraction.json").exists())
            self.assertTrue((root / "review" / "research_evidence_review_package.json").exists())

    def test_cli_builds_review_package_from_supplied_texts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            request_path = root / "request.json"
            output_dir = root / "review"
            request_path.write_text(
                json.dumps(
                    {
                        "disease_key": "femoral_head_necrosis",
                        "target_skill_id": "femoral_head_necrosis_v0.1",
                        "modality": "MRI",
                        "research_question": "MRI texture protocol",
                        "build_review_package": True,
                        "guideline_skill": {
                            "skill_id": "femoral_head_necrosis_v0.1",
                            "supported_modalities": ["MRI"],
                            "evidence_protocol_sections": [
                                "quantitative_evidence_protocol.measurement_evidence"
                            ],
                        },
                        "supplied_texts": [
                            {
                                "source_id": "cli_text_texture",
                                "title": "MRI texture feature protocol for ONFH",
                                "source_type": "journal article",
                                "publication_year": 2025,
                                "text_kind": "abstract",
                                "text": (
                                    "Multi-center retrospective study of 420 adult hip pain patients. "
                                    "MRI texture disorder score was evaluated as a measurement protocol. "
                                    "External validation is required."
                                ),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.research_evidence_builder",
                    "--input-json",
                    str(request_path),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=Path.cwd(),
                check=True,
                text=True,
                capture_output=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema_version"], "research_evidence_review_package.v1")
            self.assertEqual(payload["research_evidence_extraction"]["source_text_count"], 1)
            self.assertEqual(payload["proposal"]["candidate_extensions"][0]["source_id"], "cli_text_texture")
            self.assertFalse(payload["runtime_safety"]["formal_skill_updated"])
            self.assertFalse(payload["runtime_safety"]["diagnosis_report_updated"])
            self.assertTrue((output_dir / "research_evidence_extraction.json").exists())

    def test_claim_builder_generates_supported_candidate_claim_types_from_normalized_evidence(self) -> None:
        normalized_evidence = [
            {
                "source_id": "study_texture",
                "title": "MRI texture feature protocol for ONFH",
                "year": 2025,
                "publication_year": 2025,
                "source_type": "peer_reviewed_journal",
                "sample_size": 420,
                "population": "adult hip pain cohort",
                "modality": "MRI",
                "study_design": "multi_center_retrospective",
                "evidence_level": "moderate",
                "research_question": "texture measurement protocol",
                "candidate_claim_type": "candidate_measurement_protocol",
                "target_protocol_section": "quantitative_evidence_protocol.image_feature_quantification",
                "limitations": ["retrospective study"],
                "requires_external_validation": True,
            },
            {
                "source_id": "study_differential",
                "title": "MRI signs distinguishing ONFH from degenerative hip disease",
                "year": 2024,
                "publication_year": 2024,
                "source_type": "peer_reviewed_journal",
                "sample_size": 160,
                "population": "adult hip pain cohort",
                "modality": "MRI",
                "study_design": "prospective_validation",
                "evidence_level": "moderate",
                "research_question": "differential diagnosis clue",
                "candidate_claim_type": "differential_diagnosis_clue",
            },
            {
                "source_id": "study_steroid_risk",
                "title": "Steroid exposure risk context for osteonecrosis",
                "year": 2023,
                "publication_year": 2023,
                "source_type": "peer_reviewed_journal",
                "sample_size": 520,
                "population": "adult hip pain cohort",
                "modality": "clinical_context",
                "study_design": "multi_center_retrospective",
                "evidence_level": "moderate",
                "candidate_claim_type": "clinical_risk_context_clue",
            },
            {
                "source_id": "study_gate",
                "title": "Minimum external validation rule for radiomics features",
                "year": 2025,
                "publication_year": 2025,
                "source_type": "consensus_statement",
                "sample_size": 0,
                "population": "adult hip pain cohort",
                "modality": "MRI",
                "study_design": "consensus",
                "evidence_level": "consensus",
                "candidate_claim_type": "candidate_quality_gate_rule",
            },
            {
                "source_id": "study_extension",
                "title": "MRI marrow edema as candidate skill extension",
                "year": 2024,
                "publication_year": 2024,
                "source_type": "peer_reviewed_journal",
                "sample_size": 240,
                "population": "adult hip pain cohort",
                "modality": "MRI",
                "study_design": "multi_center_retrospective",
                "evidence_level": "moderate",
                "candidate_claim_type": "candidate_skill_extension",
            },
        ]

        claims = ResearchClaimBuilder().build_claims(
            disease_key="femoral_head_necrosis",
            normalized_research_evidence=normalized_evidence,
        )

        self.assertEqual(
            [claim["claim_type"] for claim in claims],
            [
                "quantitative_feature",
                "differential_diagnosis_clue",
                "clinical_risk_association",
                "imaging_feature",
                "imaging_feature",
            ],
        )
        self.assertEqual(
            [claim["legacy_candidate_type"] for claim in claims],
            [
                "candidate_measurement_protocol",
                "differential_diagnosis_clue",
                "clinical_risk_context_clue",
                "candidate_quality_gate_rule",
                "candidate_skill_extension",
            ],
        )
        for claim in claims:
            self.assertIn("claim_id", claim)
            self.assertIn("summary", claim)
            self.assertIn("source_id", claim)
            self.assertIn("target_protocol_section", claim)
            self.assertIn("modality", claim)
            self.assertIn("applicability", claim)
            self.assertIn("population", claim["applicability"])
            self.assertIn("limitations", claim)
            self.assertIn("evidence_level", claim)
            self.assertTrue(claim["requires_external_validation"])
            self.assertFalse(claim["formal_update_allowed"])
            self.assertFalse(claim["diagnosis_allowed"])

    def test_review_package_marks_guideline_conflict_and_generates_review_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = build_research_evidence_review_package(
                disease_key="femoral_head_necrosis",
                target_skill_id="femoral_head_necrosis_v0.1",
                modality="MRI",
                research_question="MRI texture protocol conflicts with current X-ray skill scope",
                supplied_metadata=[
                    {
                        "source_id": "study_conflict_texture",
                        "title": "MRI texture feature protocol for ONFH",
                        "source_type": "journal article",
                        "publication_year": 2025,
                        "study_design": "multi center retrospective",
                        "sample_size": 420,
                        "modality": "MRI",
                        "population": "adult hip pain cohort",
                        "evidence_level": "moderate",
                        "candidate_claim_type": "candidate_measurement_protocol",
                        "target_protocol_section": "quantitative_evidence_protocol.image_feature_quantification",
                    }
                ],
                guideline_skill={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "supported_modalities": ["X-ray"],
                    "evidence_protocol_sections": ["imaging_evidence_protocol"],
                },
                output_dir=root / "review",
            )

            self.assertEqual(package["schema_version"], "research_evidence_review_package.v1")
            self.assertEqual(package["proposal"]["schema_version"], "research_evidence_proposal.v1")
            self.assertEqual(package["claim_builder"]["schema_version"], "research_claim_builder.v1")
            review = package["gateway_review_artifact"]
            self.assertEqual(review["schema_version"], "research_gateway_review_artifact.v1")
            self.assertEqual(review["review_items"][0]["guideline_conflict_status"], "human_review_required")
            self.assertTrue(review["review_items"][0]["exploratory_only"])
            self.assertTrue(review["review_items"][0]["research_mode_only"])
            self.assertTrue(review["review_items"][0]["diagnosis_report_forbidden"])
            self.assertIn("modality_not_in_guideline_skill", review["review_items"][0]["conflict_reasons"])
            self.assertFalse(review["runtime_safety"]["formal_skill_updated"])
            self.assertFalse(review["runtime_safety"]["diagnosis_report_updated"])

            checklist = package["human_review_checklist"]
            self.assertEqual(checklist["schema_version"], "research_human_review_checklist.v1")
            self.assertEqual(checklist["review_status"], "pending_human_review")
            self.assertIn("guideline_conflict_review", checklist["required_review_steps"])
            self.assertFalse(checklist["formal_update_allowed"])
            self.assertFalse(checklist["diagnosis_allowed"])

            dry_run = package["promotion_dry_run"]
            self.assertEqual(dry_run["schema_version"], "research_promotion_dry_run.v1")
            self.assertEqual(dry_run["promotion_status"], "proposal_only_pending_human_approval")
            self.assertEqual(
                dry_run["suggested_section_updates"][0]["target_protocol_section"],
                "quantitative_evidence_protocol.image_feature_quantification",
            )
            self.assertFalse(dry_run["formal_skill_updated"])
            self.assertFalse(dry_run["diagnosis_report_updated"])
            self.assertTrue((root / "review" / "human_review_checklist.json").exists())
            self.assertTrue((root / "review" / "human_review_checklist.md").exists())
            self.assertTrue((root / "review" / "research_promotion_dry_run.json").exists())
            self.assertTrue((root / "review" / "research_gateway_review_artifact.json").exists())

    def test_review_package_generates_controlled_skill_extension_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = build_research_evidence_review_package(
                disease_key="femoral_head_necrosis",
                target_skill_id="femoral_head_necrosis_v0.1",
                modality="MRI",
                research_question="MRI necrotic area ratio as supplemental measurement",
                supplied_metadata=[
                    {
                        "source_id": "study_necrotic_ratio",
                        "title": "MRI necrotic area ratio for ONFH staging",
                        "source_type": "journal article",
                        "publication_year": 2025,
                        "study_design": "multi center retrospective",
                        "sample_size": 420,
                        "modality": "MRI",
                        "population": "adult hip pain cohort",
                        "evidence_level": "moderate",
                        "candidate_claim_type": "candidate_measurement_protocol",
                        "target_protocol_section": (
                            "quantitative_evidence_protocol.measurement_evidence"
                        ),
                    }
                ],
                guideline_skill={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "supported_modalities": ["MRI"],
                    "evidence_protocol_sections": [
                        "quantitative_evidence_protocol.measurement_evidence"
                    ],
                },
                output_dir=root / "review",
            )

            draft = package["controlled_skill_extension_draft"]
            self.assertEqual(draft["schema_version"], "controlled_skill_extension_draft.v1")
            self.assertEqual(draft["draft_status"], "pending_human_review")
            self.assertEqual(
                draft["source_proposal_schema_version"],
                package["proposal"]["schema_version"],
            )
            self.assertEqual(draft["target_skill_id"], "femoral_head_necrosis_v0.1")
            self.assertTrue(draft["human_review_required"])
            self.assertFalse(draft["runtime_safety"]["formal_skill_updated"])
            self.assertFalse(draft["runtime_safety"]["formal_guideline_updated"])
            self.assertFalse(draft["runtime_safety"]["diagnosis_report_updated"])
            self.assertFalse(draft["runtime_safety"]["formal_update_allowed"])
            self.assertFalse(draft["runtime_safety"]["diagnosis_allowed"])

            update = draft["proposed_section_updates"][0]
            self.assertEqual(update["source_id"], "study_necrotic_ratio")
            self.assertEqual(update["candidate_type"], "candidate_measurement_protocol")
            self.assertEqual(
                update["target_protocol_section"],
                "quantitative_evidence_protocol.measurement_evidence",
            )
            self.assertEqual(update["evidence_level"], "moderate")
            self.assertEqual(update["evidence_use_label"], "supplemental")
            self.assertEqual(update["guideline_conflict_status"], "no_direct_conflict_detected")
            self.assertEqual(update["conflict_reasons"], [])
            self.assertEqual(
                update["suggested_section_action"],
                "add_research_mode_supplemental_measurement",
            )
            self.assertTrue(update["human_review_required"])
            self.assertTrue(update["research_mode_only"])
            self.assertFalse(update["formal_update_allowed"])
            self.assertFalse(update["diagnosis_allowed"])
            self.assertIn("proposed_section_updates", draft["promotion_dry_run_diff"])
            self.assertTrue(
                (root / "review" / "controlled_skill_extension_draft.json").exists()
            )
            self.assertTrue(
                (root / "review" / "controlled_skill_extension_draft.md").exists()
            )

    def test_human_review_approval_builds_controlled_promotion_package_without_applying_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = build_research_evidence_review_package(
                disease_key="femoral_head_necrosis",
                target_skill_id="femoral_head_necrosis_v0.1",
                modality="MRI",
                research_question="MRI necrotic area ratio as supplemental measurement",
                supplied_metadata=[
                    {
                        "source_id": "study_necrotic_ratio",
                        "title": "MRI necrotic area ratio for ONFH staging",
                        "source_type": "journal article",
                        "publication_year": 2025,
                        "study_design": "multi center retrospective",
                        "sample_size": 420,
                        "modality": "MRI",
                        "population": "adult hip pain cohort",
                        "evidence_level": "moderate",
                        "candidate_claim_type": "candidate_measurement_protocol",
                        "target_protocol_section": (
                            "quantitative_evidence_protocol.measurement_evidence"
                        ),
                    }
                ],
                guideline_skill={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "supported_modalities": ["MRI"],
                    "evidence_protocol_sections": [
                        "quantitative_evidence_protocol.measurement_evidence"
                    ],
                },
                human_review_decisions=[
                    {
                        "item_id": "femoral_head_necrosis_study_necrotic_ratio_claim_001",
                        "decision": "approved",
                        "reviewer_id": "reviewer_rad_001",
                        "reviewed_at": "2026-06-06T12:00:00Z",
                        "notes": "Use only as research-mode supplemental measurement.",
                    }
                ],
                output_dir=root / "review",
            )

            decision = package["human_review_decision"]
            self.assertEqual(decision["schema_version"], "research_human_review_decision.v1")
            self.assertEqual(decision["decision_status"], "approved")
            decision_item = decision["items"][0]
            self.assertEqual(decision_item["review_decision"], "approved")
            self.assertEqual(decision_item["reviewer_id"], "reviewer_rad_001")
            self.assertFalse(decision_item["formal_update_allowed"])
            self.assertFalse(decision_item["diagnosis_allowed"])

            promotion = package["controlled_promotion_package"]
            self.assertEqual(promotion["schema_version"], "controlled_promotion_package.v1")
            self.assertEqual(
                promotion["package_status"],
                "ready_for_controlled_promotion_review",
            )
            self.assertFalse(promotion["runtime_safety"]["formal_skill_updated"])
            self.assertFalse(promotion["runtime_safety"]["formal_guideline_updated"])
            self.assertFalse(promotion["runtime_safety"]["diagnosis_report_updated"])
            self.assertFalse(promotion["runtime_safety"]["formal_update_allowed"])
            self.assertFalse(promotion["runtime_safety"]["diagnosis_allowed"])

            approved = promotion["approved_updates"][0]
            self.assertEqual(approved["source_id"], "study_necrotic_ratio")
            self.assertEqual(
                approved["target_protocol_section"],
                "quantitative_evidence_protocol.measurement_evidence",
            )
            self.assertEqual(approved["evidence_use_label"], "supplemental")
            self.assertEqual(approved["review_decision"], "approved")
            self.assertFalse(approved["formal_patch_applied"])
            self.assertFalse(approved["diagnosis_flow_changed"])

            patch_preview = promotion["formal_skill_patch_preview"]
            self.assertEqual(patch_preview["patch_status"], "preview_only_not_applied")
            self.assertFalse(patch_preview["formal_skill_file_changed"])
            self.assertIn(
                "quantitative_evidence_protocol.measurement_evidence",
                patch_preview["preview_sections"][0]["target_protocol_section"],
            )
            self.assertIn("rollback_notes", promotion)
            self.assertIn("audit_log", promotion)
            self.assertTrue(promotion["audit_log"][0]["event"].startswith("human_review"))
            self.assertTrue(
                (root / "review" / "research_human_review_decision.json").exists()
            )
            self.assertTrue(
                (root / "review" / "controlled_promotion_package.json").exists()
            )
            self.assertTrue(
                (root / "review" / "controlled_promotion_package.md").exists()
            )

    def test_formal_skill_extension_patch_preview_is_generated_for_approved_supplemental_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = build_research_evidence_review_package(
                disease_key="femoral_head_necrosis",
                target_skill_id="femoral_head_necrosis_v0.1",
                modality="MRI",
                research_question="MRI necrotic area ratio as supplemental measurement",
                supplied_metadata=[
                    {
                        "source_id": "study_necrotic_ratio",
                        "title": "MRI necrotic area ratio for ONFH staging",
                        "source_type": "journal article",
                        "publication_year": 2025,
                        "study_design": "multi center retrospective",
                        "sample_size": 420,
                        "modality": "MRI",
                        "population": "adult hip pain cohort",
                        "evidence_level": "moderate",
                        "candidate_claim_type": "candidate_measurement_protocol",
                        "target_protocol_section": (
                            "quantitative_evidence_protocol.measurement_evidence"
                        ),
                    }
                ],
                guideline_skill={
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "supported_modalities": ["MRI"],
                    "evidence_protocol_sections": [
                        "quantitative_evidence_protocol.measurement_evidence"
                    ],
                },
                human_review_decisions=[
                    {
                        "item_id": "femoral_head_necrosis_study_necrotic_ratio_claim_001",
                        "decision": "approved",
                        "reviewer_id": "reviewer_rad_001",
                        "reviewed_at": "2026-06-06T12:00:00Z",
                    }
                ],
                output_dir=root / "review",
            )

            patch = package["formal_skill_extension_patch_preview"]
            self.assertEqual(
                patch["schema_version"],
                "formal_skill_extension_patch_preview.v1",
            )
            self.assertEqual(patch["patch_status"], "ready_for_human_apply_review")
            self.assertEqual(patch["target_skill_id"], "femoral_head_necrosis_v0.1")
            self.assertIn("femoral_head_necrosis_v0.1", patch["target_skill_file_preview"])
            self.assertEqual(
                patch["target_sections"][0]["safe_extension_section"],
                (
                    "research_evidence_supplements."
                    "quantitative_evidence_protocol.measurement_evidence"
                ),
            )
            self.assertEqual(
                patch["target_sections"][0]["original_target_protocol_section"],
                "quantitative_evidence_protocol.measurement_evidence",
            )
            self.assertIn(
                "+ research_evidence_supplements.",
                patch["diff_preview"]["unified_diff"],
            )
            self.assertFalse(patch["diff_preview"]["patch_applied"])
            self.assertIn("reviewer_sign_off", patch["sign_off_checklist"]["required_items"])
            self.assertIn("diagnosis_boundary_sign_off", patch["sign_off_checklist"]["required_items"])
            self.assertEqual(patch["rollback_plan"]["rollback_status"], "preview_only")
            self.assertEqual(patch["pre_apply_audit"]["audit_status"], "passed")
            self.assertTrue(patch["pre_apply_audit"]["allowed_research_mode_sections_only"])
            self.assertFalse(patch["pre_apply_audit"]["guideline_core_modified"])
            self.assertFalse(patch["pre_apply_audit"]["diagnosis_rules_modified"])
            self.assertFalse(patch["pre_apply_audit"]["skill_registry_modified"])
            self.assertFalse(patch["runtime_safety"]["formal_skill_updated"])
            self.assertFalse(patch["runtime_safety"]["formal_guideline_updated"])
            self.assertFalse(patch["runtime_safety"]["diagnosis_report_updated"])
            self.assertFalse(patch["runtime_safety"]["skill_registry_updated"])
            self.assertFalse(patch["runtime_safety"]["patch_applied"])
            self.assertTrue(
                (root / "review" / "formal_skill_extension_patch_preview.json").exists()
            )
            self.assertTrue(
                (root / "review" / "formal_skill_extension_patch_preview.md").exists()
            )

    def test_formal_skill_extension_patch_preview_blocks_diagnosis_or_core_sections(self) -> None:
        package = build_research_evidence_review_package(
            disease_key="femoral_head_necrosis",
            target_skill_id="femoral_head_necrosis_v0.1",
            modality="MRI",
            research_question="unsafe diagnosis rule change should be blocked",
            supplied_metadata=[
                {
                    "source_id": "unsafe_diagnosis_rule",
                    "title": "Unsafe diagnosis rule candidate",
                    "source_type": "journal article",
                    "publication_year": 2025,
                    "study_design": "multi center retrospective",
                    "sample_size": 420,
                    "modality": "MRI",
                    "population": "adult hip pain cohort",
                    "evidence_level": "moderate",
                    "candidate_claim_type": "candidate_skill_extension",
                    "target_protocol_section": "diagnosis_rules.confirmatory_criteria",
                }
            ],
            guideline_skill={
                "skill_id": "femoral_head_necrosis_v0.1",
                "supported_modalities": ["MRI"],
                "evidence_protocol_sections": [
                    "diagnosis_rules.confirmatory_criteria"
                ],
            },
            human_review_decisions=[
                {
                    "item_id": "femoral_head_necrosis_unsafe_diagnosis_rule_claim_001",
                    "decision": "approved",
                    "reviewer_id": "reviewer_rad_001",
                }
            ],
        )

        patch = package["formal_skill_extension_patch_preview"]
        self.assertEqual(patch["patch_status"], "blocked_by_pre_apply_audit")
        self.assertEqual(patch["pre_apply_audit"]["audit_status"], "blocked")
        self.assertIn(
            "forbidden_target_section",
            patch["pre_apply_audit"]["violations"],
        )
        self.assertFalse(patch["pre_apply_audit"]["allowed_research_mode_sections_only"])
        self.assertFalse(patch["pre_apply_audit"]["guideline_core_modified"])
        self.assertFalse(patch["pre_apply_audit"]["skill_registry_modified"])
        self.assertTrue(patch["pre_apply_audit"]["diagnosis_rules_modified"])
        self.assertEqual(patch["diff_preview"]["unified_diff"], "")
        self.assertFalse(patch["diff_preview"]["patch_applied"])
        self.assertFalse(patch["runtime_safety"]["formal_skill_updated"])
        self.assertFalse(patch["runtime_safety"]["diagnosis_report_updated"])
        self.assertFalse(patch["runtime_safety"]["skill_registry_updated"])
        self.assertFalse(patch["runtime_safety"]["patch_applied"])

    def test_review_package_blocks_weak_claim_and_keeps_promotion_dry_run_read_only(self) -> None:
        package = build_research_evidence_review_package(
            disease_key="community_acquired_pneumonia",
            target_skill_id="pneumonia_chest_xray_v0.1",
            modality="Chest X-ray",
            research_question="AI opacity score for pneumonia",
            supplied_metadata=[
                {
                    "source_id": "weak_preprint",
                    "title": "Small preprint model for opacity detection",
                    "source_type": "preprint",
                    "year": 2017,
                    "study_design": "single center retrospective",
                    "sample_size": 18,
                    "modality": "Chest CT",
                    "population": "pediatric ICU cohort",
                    "evidence_level": "low",
                    "candidate_claim_type": "candidate_skill_extension",
                }
            ],
            guideline_skill={
                "skill_id": "pneumonia_chest_xray_v0.1",
                "supported_modalities": ["Chest X-ray"],
                "evidence_protocol_sections": ["integrated_reasoning_protocol"],
            },
        )

        validation = package["proposal"]["quality_gate"]["claim_validations"][0]
        self.assertEqual(validation["decision"], "blocked")
        self.assertEqual(package["promotion_dry_run"]["promotion_status"], "blocked_by_quality_gate")
        self.assertFalse(package["promotion_dry_run"]["formal_update_allowed"])
        self.assertFalse(package["promotion_dry_run"]["diagnosis_allowed"])
        self.assertTrue(package["gateway_review_artifact"]["review_items"][0]["diagnosis_report_forbidden"])

    def test_controlled_skill_extension_draft_blocks_conflicted_or_weak_items(self) -> None:
        package = build_research_evidence_review_package(
            disease_key="community_acquired_pneumonia",
            target_skill_id="pneumonia_chest_xray_v0.1",
            modality="Chest X-ray",
            research_question="AI opacity score for pneumonia",
            supplied_metadata=[
                {
                    "source_id": "weak_preprint",
                    "title": "Small preprint model for opacity detection",
                    "source_type": "preprint",
                    "year": 2017,
                    "study_design": "single center retrospective",
                    "sample_size": 18,
                    "modality": "Chest CT",
                    "population": "pediatric ICU cohort",
                    "evidence_level": "low",
                    "candidate_claim_type": "candidate_skill_extension",
                }
            ],
            guideline_skill={
                "skill_id": "pneumonia_chest_xray_v0.1",
                "supported_modalities": ["Chest X-ray"],
                "evidence_protocol_sections": ["integrated_reasoning_protocol"],
            },
        )

        draft = package["controlled_skill_extension_draft"]
        self.assertEqual(draft["schema_version"], "controlled_skill_extension_draft.v1")
        self.assertEqual(draft["draft_status"], "blocked_by_gateway")
        self.assertEqual(draft["guideline_conflict_summary"]["blocked_count"], 1)
        self.assertFalse(draft["runtime_safety"]["formal_update_allowed"])
        self.assertFalse(draft["runtime_safety"]["diagnosis_allowed"])

        update = draft["proposed_section_updates"][0]
        self.assertEqual(update["source_id"], "weak_preprint")
        self.assertEqual(update["evidence_use_label"], "research_only")
        self.assertEqual(update["suggested_section_action"], "do_not_promote_blocked_item")
        self.assertEqual(update["guideline_conflict_status"], "human_review_required")
        self.assertIn("modality_not_in_guideline_skill", update["conflict_reasons"])
        self.assertTrue(update["research_mode_only"])
        self.assertTrue(update["exploratory_only"])
        self.assertFalse(update["promotion_allowed_after_review"])
        self.assertFalse(update["formal_update_allowed"])
        self.assertFalse(update["diagnosis_allowed"])

    def test_rejected_or_needs_revision_items_do_not_enter_promotion_package(self) -> None:
        package = build_research_evidence_review_package(
            disease_key="femoral_head_necrosis",
            target_skill_id="femoral_head_necrosis_v0.1",
            modality="MRI",
            research_question="MRI research-only additions needing review",
            supplied_metadata=[
                {
                    "source_id": "study_measurement",
                    "title": "MRI necrotic area ratio for ONFH staging",
                    "source_type": "journal article",
                    "publication_year": 2025,
                    "study_design": "multi center retrospective",
                    "sample_size": 420,
                    "modality": "MRI",
                    "population": "adult hip pain cohort",
                    "evidence_level": "moderate",
                    "candidate_claim_type": "candidate_measurement_protocol",
                    "target_protocol_section": (
                        "quantitative_evidence_protocol.measurement_evidence"
                    ),
                },
                {
                    "source_id": "study_differential",
                    "title": "MRI differential clue for hip pain",
                    "source_type": "journal article",
                    "publication_year": 2024,
                    "study_design": "prospective validation",
                    "sample_size": 160,
                    "modality": "MRI",
                    "population": "adult hip pain cohort",
                    "evidence_level": "moderate",
                    "candidate_claim_type": "differential_diagnosis_clue",
                    "target_protocol_section": "differential_diagnosis_protocol",
                },
            ],
            guideline_skill={
                "skill_id": "femoral_head_necrosis_v0.1",
                "supported_modalities": ["MRI"],
                "evidence_protocol_sections": [
                    "quantitative_evidence_protocol.measurement_evidence",
                    "differential_diagnosis_protocol",
                ],
            },
            human_review_decisions=[
                {
                    "item_id": "femoral_head_necrosis_study_measurement_claim_001",
                    "decision": "rejected",
                    "reviewer_id": "reviewer_rad_001",
                    "notes": "Measurement is not reproducible enough.",
                },
                {
                    "item_id": "femoral_head_necrosis_study_differential_claim_002",
                    "decision": "needs_revision",
                    "reviewer_id": "reviewer_rad_001",
                    "notes": "Needs clearer guideline conflict statement.",
                },
            ],
        )

        decision = package["human_review_decision"]
        self.assertEqual(decision["decision_status"], "not_approved")
        self.assertEqual(
            [item["review_decision"] for item in decision["items"]],
            ["rejected", "needs_revision"],
        )

        promotion = package["controlled_promotion_package"]
        self.assertEqual(promotion["package_status"], "not_ready_for_promotion")
        self.assertEqual(promotion["approved_updates"], [])
        self.assertEqual(len(promotion["rejected_or_revision_items"]), 2)
        self.assertEqual(
            promotion["formal_skill_patch_preview"]["patch_status"],
            "no_approved_updates",
        )
        self.assertEqual(promotion["formal_skill_patch_preview"]["preview_sections"], [])
        self.assertFalse(promotion["formal_skill_patch_preview"]["formal_skill_file_changed"])
        self.assertTrue(
            any(
                event["event"] == "human_review_item_not_approved"
                for event in promotion["audit_log"]
            )
        )
        self.assertFalse(promotion["runtime_safety"]["formal_update_allowed"])
        self.assertFalse(promotion["runtime_safety"]["diagnosis_allowed"])

    def test_cli_builds_full_review_package_from_request_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            request_path = root / "request.json"
            output_dir = root / "review"
            request_path.write_text(
                json.dumps(
                    {
                        "disease_key": "femoral_head_necrosis",
                        "target_skill_id": "femoral_head_necrosis_v0.1",
                        "modality": "MRI",
                        "research_question": "MRI texture protocol",
                        "build_review_package": True,
                        "guideline_skill": {
                            "skill_id": "femoral_head_necrosis_v0.1",
                            "supported_modalities": ["MRI"],
                            "evidence_protocol_sections": [
                                "quantitative_evidence_protocol.measurement_evidence"
                            ],
                        },
                        "supplied_metadata": [
                            {
                                "source_id": "study_cli_texture",
                                "title": "MRI texture feature protocol for ONFH",
                                "source_type": "journal article",
                                "publication_year": 2025,
                                "study_design": "multi center retrospective",
                                "sample_size": 420,
                                "modality": "MRI",
                                "population": "adult hip pain cohort",
                                "evidence_level": "moderate",
                                "candidate_claim_type": "candidate_measurement_protocol",
                            }
                        ],
                        "human_review_decisions": [
                            {
                                "item_id": "femoral_head_necrosis_study_cli_texture_claim_001",
                                "decision": "approved",
                                "reviewer_id": "reviewer_cli",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.research_evidence_builder",
                    "--input-json",
                    str(request_path),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=Path.cwd(),
                check=True,
                text=True,
                capture_output=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema_version"], "research_evidence_review_package.v1")
            self.assertEqual(payload["proposal"]["proposal_status"], "proposal_only")
            self.assertFalse(payload["runtime_safety"]["formal_skill_updated"])
            self.assertFalse(payload["runtime_safety"]["diagnosis_report_updated"])
            self.assertTrue((output_dir / "research_evidence_proposal.json").exists())
            self.assertTrue((output_dir / "research_gateway_review_artifact.json").exists())
            self.assertTrue((output_dir / "human_review_checklist.json").exists())
            self.assertTrue((output_dir / "human_review_checklist.md").exists())
            self.assertTrue((output_dir / "research_promotion_dry_run.json").exists())
            self.assertEqual(
                payload["human_review_decision"]["decision_status"],
                "approved",
            )
            self.assertEqual(
                payload["controlled_promotion_package"]["package_status"],
                "ready_for_controlled_promotion_review",
            )
            self.assertTrue((output_dir / "research_human_review_decision.json").exists())
            self.assertTrue((output_dir / "controlled_promotion_package.json").exists())
            self.assertTrue((output_dir / "controlled_promotion_package.md").exists())
            self.assertEqual(
                payload["formal_skill_extension_patch_preview"]["patch_status"],
                "ready_for_human_apply_review",
            )
            self.assertTrue(
                (output_dir / "formal_skill_extension_patch_preview.json").exists()
            )
            self.assertTrue(
                (output_dir / "formal_skill_extension_patch_preview.md").exists()
            )

    def test_retriever_normalizes_supplied_metadata_without_pubmed_retrieval(self) -> None:
        class FailingPubMedClient:
            called = False

            def __call__(self, query: str, limit: int) -> list[dict]:
                self.called = True
                raise AssertionError("PubMed client should not be called when retrieval is disabled")

        pubmed_client = FailingPubMedClient()
        result = ResearchEvidenceRetriever(pubmed_client=pubmed_client).retrieve(
            disease_key="femoral_head_necrosis",
            modality="MRI",
            research_question="MRI texture features for early osteonecrosis",
            supplied_metadata=[
                {
                    "title": "MRI texture features for early osteonecrosis",
                    "year": "2025",
                    "source_type": "journal article",
                    "DOI": "10.1000/onfh-texture",
                    "sample_size": "n=420",
                    "population": "Adult hip pain cohort",
                    "modality": "mri",
                    "study_design": "multi-center retrospective cohort",
                    "evidence_level": "moderate",
                }
            ],
            pubmed_enabled=False,
        )

        self.assertEqual(result["schema_version"], "research_evidence_retrieval.v1")
        self.assertEqual(result["request"]["disease_key"], "femoral_head_necrosis")
        self.assertFalse(result["retrieval"]["pubmed_enabled"])
        self.assertFalse(result["retrieval"]["pubmed_retrieval_attempted"])
        self.assertFalse(result["runtime_safety"]["paper_search_performed"])
        self.assertFalse(pubmed_client.called)
        evidence = result["normalized_research_evidence"][0]
        self.assertEqual(evidence["title"], "MRI texture features for early osteonecrosis")
        self.assertEqual(evidence["year"], 2025)
        self.assertEqual(evidence["publication_year"], 2025)
        self.assertEqual(evidence["source_type"], "peer_reviewed_journal")
        self.assertEqual(evidence["doi"], "10.1000/onfh-texture")
        self.assertEqual(evidence["DOI"], "10.1000/onfh-texture")
        self.assertEqual(evidence["sample_size"], 420)
        self.assertEqual(evidence["population"], "adult hip pain cohort")
        self.assertEqual(evidence["modality"], "MRI")
        self.assertEqual(evidence["study_design"], "multi_center_retrospective")
        self.assertEqual(evidence["evidence_level"], "moderate")

    def test_retriever_can_use_injected_pubmed_metadata_client_when_enabled(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_pubmed_client(query: str, limit: int) -> list[dict]:
            calls.append((query, limit))
            return [
                {
                    "pmid": "12345678",
                    "article_title": "PubMed abstract for MRI osteonecrosis measurement",
                    "pub_date": "2024 Jun",
                    "doi": "10.1000/pubmed-onfh",
                    "sample_size": 180,
                    "population": "adult hip pain cohort",
                    "modality": "MRI",
                    "study_design": "prospective validation study",
                    "publication_types": ["Journal Article"],
                }
            ]

        result = ResearchEvidenceRetriever(pubmed_client=fake_pubmed_client).retrieve(
            disease_key="femoral_head_necrosis",
            modality="MRI",
            research_question="necrotic area ratio validation",
            pubmed_enabled=True,
            pubmed_limit=5,
        )

        self.assertEqual(len(calls), 1)
        self.assertIn("femoral_head_necrosis", calls[0][0])
        self.assertIn("necrotic area ratio validation", calls[0][0])
        self.assertEqual(calls[0][1], 5)
        self.assertTrue(result["retrieval"]["pubmed_enabled"])
        self.assertTrue(result["retrieval"]["pubmed_retrieval_attempted"])
        self.assertTrue(result["runtime_safety"]["paper_search_performed"])
        evidence = result["normalized_research_evidence"][0]
        self.assertEqual(evidence["source_id"], "pubmed_12345678")
        self.assertEqual(evidence["title"], "PubMed abstract for MRI osteonecrosis measurement")
        self.assertEqual(evidence["year"], 2024)
        self.assertEqual(evidence["source_type"], "peer_reviewed_journal")
        self.assertEqual(evidence["doi"], "10.1000/pubmed-onfh")
        self.assertEqual(evidence["DOI"], "10.1000/pubmed-onfh")
        self.assertEqual(evidence["evidence_level"], "moderate")

    def test_pubmed_xml_parser_preserves_title_journal_doi_and_abstract(self) -> None:
        records = parse_pubmed_xml_metadata(
            """
            <PubmedArticleSet>
              <PubmedArticle>
                <MedlineCitation>
                  <PMID>12345678</PMID>
                  <Article>
                    <Journal>
                      <Title>Skeletal Radiology</Title>
                      <JournalIssue>
                        <PubDate><Year>2025</Year></PubDate>
                      </JournalIssue>
                    </Journal>
                    <ArticleTitle>MRI measurement for osteonecrosis</ArticleTitle>
                    <Abstract>
                      <AbstractText>Necrotic area ratio was evaluated in MRI.</AbstractText>
                      <AbstractText Label="LIMITATIONS">External validation is required.</AbstractText>
                    </Abstract>
                    <PublicationTypeList>
                      <PublicationType>Journal Article</PublicationType>
                    </PublicationTypeList>
                  </Article>
                  <ArticleIdList>
                    <ArticleId IdType="doi">10.1000/pubmed-xml</ArticleId>
                  </ArticleIdList>
                </MedlineCitation>
              </PubmedArticle>
            </PubmedArticleSet>
            """
        )

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["pmid"], "12345678")
        self.assertEqual(record["article_title"], "MRI measurement for osteonecrosis")
        self.assertEqual(record["journal"], "Skeletal Radiology")
        self.assertEqual(record["pub_date"], "2025")
        self.assertEqual(record["doi"], "10.1000/pubmed-xml")
        self.assertIn("Necrotic area ratio", record["abstract"])
        self.assertIn("External validation", record["abstract"])

    def test_request_builder_connects_normalized_metadata_to_gateway_proposal_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload = build_research_evidence_proposal_from_request(
                disease_key="femoral_head_necrosis",
                target_skill_id="femoral_head_necrosis_v0.1",
                modality="MRI",
                research_question="MRI necrotic area ratio as a candidate measurement",
                supplied_metadata=[
                    {
                        "title": "Area ratio measurement for ONFH MRI",
                        "source_type": "journal",
                        "publication_year": 2024,
                        "study_design": "multi center retrospective",
                        "sample_size": 180,
                        "modality": "MRI",
                        "population": "adult hip pain cohort",
                        "evidence_level": "moderate",
                    }
                ],
                extracted_claims=[
                    {
                        "claim_id": "necrotic_area_ratio_mri",
                        "claim_type": "candidate_measurement_protocol",
                        "summary": "MRI necrotic area ratio may be useful as a candidate measurement.",
                        "target_protocol_section": "quantitative_evidence_protocol.measurement_evidence",
                        "modality": "MRI",
                        "applicability": {
                            "population": "adult hip pain cohort",
                            "requires_external_validation": True,
                        },
                    }
                ],
                output_dir=root / "gateway",
            )

            self.assertEqual(payload["schema_version"], "research_evidence_proposal.v1")
            self.assertEqual(
                payload["research_evidence_retrieval"]["schema_version"],
                "research_evidence_retrieval.v1",
            )
            self.assertEqual(len(payload["normalized_research_evidence"]), 1)
            self.assertEqual(payload["sources"][0]["year"], 2024)
            self.assertEqual(payload["sources"][0]["publication_year"], 2024)
            self.assertEqual(payload["candidate_extensions"][0]["source_id"], payload["sources"][0]["source_id"])
            self.assertEqual(payload["proposal_status"], "proposal_only")
            self.assertEqual(payload["quality_gate"]["promotion_decision"]["status"], "candidate_review_only")
            self.assertFalse(payload["runtime_safety"]["formal_skill_updated"])
            self.assertFalse(payload["runtime_safety"]["diagnosis_report_updated"])
            self.assertFalse(payload["runtime_safety"]["formal_update_allowed"])
            self.assertFalse(payload["runtime_safety"]["diagnosis_allowed"])
            self.assertTrue((root / "gateway" / "research_evidence_proposal.json").exists())

    def test_request_builder_blocks_weak_normalized_source_through_gateway(self) -> None:
        payload = build_research_evidence_proposal_from_request(
            disease_key="community_acquired_pneumonia",
            target_skill_id="pneumonia_chest_xray_v0.1",
            modality="Chest X-ray",
            research_question="AI opacity score for pneumonia",
            supplied_metadata=[
                {
                    "title": "Small preprint model for opacity detection",
                    "source_type": "preprint",
                    "year": 2017,
                    "study_design": "single center retrospective",
                    "sample_size": 18,
                    "modality": "Chest CT",
                    "population": "pediatric ICU cohort",
                    "evidence_level": "low",
                }
            ],
            extracted_claims=[
                {
                    "claim_id": "ct_opacity_ai_score",
                    "claim_type": "candidate_skill_extension",
                    "summary": "AI score should diagnose adult chest X-ray pneumonia.",
                    "target_protocol_section": "integrated_reasoning_protocol",
                    "modality": "Chest X-ray",
                    "applicability": {
                        "population": "adult outpatient chest X-ray",
                        "requires_external_validation": True,
                    },
                }
            ],
        )

        validation = payload["quality_gate"]["claim_validations"][0]
        self.assertEqual(validation["decision"], "blocked")
        self.assertIn("source_type_not_peer_reviewed_or_guideline", validation["failed_checks"])
        self.assertIn("sample_size_below_minimum", validation["failed_checks"])
        self.assertIn("stale_or_missing_publication_year", validation["failed_checks"])
        self.assertIn("modality_mismatch", validation["failed_checks"])
        self.assertFalse(payload["quality_gate"]["promotion_decision"]["formal_update_allowed"])
        self.assertFalse(payload["quality_gate"]["promotion_decision"]["diagnosis_allowed"])

    def test_builds_proposal_only_candidate_extension_from_supplied_study(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload = build_research_evidence_proposal(
                disease_key="femoral_head_necrosis",
                target_skill_id="femoral_head_necrosis_v0.1",
                sources=[
                    {
                        "source_id": "study_2025_mri_texture",
                        "title": "MRI texture features for early osteonecrosis",
                        "source_type": "peer_reviewed_journal",
                        "publication_year": 2025,
                        "study_design": "multi_center_retrospective",
                        "sample_size": 420,
                        "modality": "MRI",
                        "population": "adult hip pain cohort",
                        "evidence_level": "moderate",
                        "url": "https://example.org/study",
                    }
                ],
                extracted_claims=[
                    {
                        "claim_id": "texture_disorder_score",
                        "claim_type": "candidate_measurement_protocol",
                        "summary": "Texture disorder score may improve early ONFH suspicion on MRI.",
                        "target_protocol_section": "quantitative_evidence_protocol.image_feature_quantification",
                        "modality": "MRI",
                        "applicability": {
                            "population": "adult hip pain cohort",
                            "requires_external_validation": True,
                        },
                        "limitations": ["retrospective study", "not a guideline recommendation"],
                    }
                ],
                output_dir=root / "out",
            )

            self.assertEqual(payload["schema_version"], "research_evidence_proposal.v1")
            self.assertEqual(payload["disease_key"], "femoral_head_necrosis")
            self.assertEqual(payload["target_skill_id"], "femoral_head_necrosis_v0.1")
            self.assertEqual(payload["proposal_status"], "proposal_only")
            self.assertEqual(payload["candidate_extensions"][0]["candidate_type"], "candidate_measurement_protocol")
            self.assertEqual(
                payload["candidate_extensions"][0]["allowed_action"],
                "proposal_only_no_formal_update",
            )
            self.assertFalse(payload["candidate_extensions"][0]["formal_update_allowed"])
            self.assertFalse(payload["candidate_extensions"][0]["diagnosis_allowed"])
            self.assertFalse(payload["runtime_safety"]["formal_skill_updated"])
            self.assertFalse(payload["runtime_safety"]["formal_guideline_updated"])
            self.assertFalse(payload["runtime_safety"]["diagnosis_report_updated"])
            self.assertFalse(payload["quality_gate"]["promotion_decision"]["formal_update_allowed"])
            self.assertEqual(
                payload["quality_gate"]["promotion_decision"]["status"],
                "candidate_review_only",
            )
            self.assertIn("human_review_required", payload["quality_gate"]["required_reviews"])
            self.assertTrue((root / "out" / "research_evidence_proposal.json").exists())
            self.assertTrue((root / "out" / "research_evidence_quality_gate.json").exists())
            markdown = (root / "out" / "research_evidence_proposal.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("proposal_only", markdown)
            self.assertIn("formal_update_allowed=false", markdown)

    def test_quality_gate_blocks_weak_or_inapplicable_research_evidence(self) -> None:
        payload = build_research_evidence_proposal(
            disease_key="community_acquired_pneumonia",
            target_skill_id="pneumonia_chest_xray_v0.1",
            sources=[
                {
                    "source_id": "preprint_small_single_center",
                    "title": "Small preprint model for opacity detection",
                    "source_type": "preprint",
                    "publication_year": 2017,
                    "study_design": "single_center_retrospective",
                    "sample_size": 18,
                    "modality": "Chest CT",
                    "population": "pediatric ICU cohort",
                    "evidence_level": "low",
                }
            ],
            extracted_claims=[
                {
                    "claim_id": "ct_opacity_ai_score",
                    "claim_type": "candidate_skill_extension",
                    "summary": "AI score should diagnose adult chest X-ray pneumonia.",
                    "target_protocol_section": "integrated_reasoning_protocol",
                    "modality": "Chest X-ray",
                    "applicability": {
                        "population": "adult outpatient chest X-ray",
                        "requires_external_validation": True,
                    },
                    "limitations": [],
                }
            ],
        )

        validation = payload["quality_gate"]["claim_validations"][0]
        self.assertEqual(validation["decision"], "blocked")
        self.assertIn("source_type_not_peer_reviewed_or_guideline", validation["failed_checks"])
        self.assertIn("sample_size_below_minimum", validation["failed_checks"])
        self.assertIn("stale_or_missing_publication_year", validation["failed_checks"])
        self.assertIn("modality_mismatch", validation["failed_checks"])
        self.assertIn("population_mismatch", validation["failed_checks"])
        self.assertFalse(validation["diagnosis_allowed"])
        self.assertFalse(validation["formal_update_allowed"])
        self.assertEqual(payload["quality_gate"]["promotion_decision"]["status"], "blocked")

    def test_rejects_candidate_that_tries_to_bypass_proposal_only_boundary(self) -> None:
        with self.assertRaises(ValueError):
            build_research_evidence_proposal(
                disease_key="femoral_head_necrosis",
                target_skill_id="femoral_head_necrosis_v0.1",
                sources=[
                    {
                        "source_id": "study",
                        "title": "Study",
                        "source_type": "peer_reviewed_journal",
                        "publication_year": 2025,
                        "study_design": "multi_center_retrospective",
                        "sample_size": 200,
                        "modality": "MRI",
                        "population": "adult hip pain cohort",
                        "evidence_level": "moderate",
                    }
                ],
                extracted_claims=[
                    {
                        "claim_id": "unsafe_claim",
                        "claim_type": "candidate_skill_extension",
                        "summary": "Directly update the formal skill.",
                        "target_protocol_section": "imaging_evidence_protocol",
                        "modality": "MRI",
                        "formal_update_allowed": True,
                    }
                ],
            )

    def test_cli_builds_research_gateway_artifacts_without_paper_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            request_path = root / "request.json"
            output_dir = root / "gateway"
            request_path.write_text(
                json.dumps(
                    {
                        "disease_key": "femoral_head_necrosis",
                        "target_skill_id": "femoral_head_necrosis_v0.1",
                        "sources": [
                            {
                                "source_id": "study_2024_area_ratio",
                                "title": "Area ratio measurement for ONFH MRI",
                                "source_type": "peer_reviewed_journal",
                                "publication_year": 2024,
                                "study_design": "multi_center_retrospective",
                                "sample_size": 180,
                                "modality": "MRI",
                                "population": "adult hip pain cohort",
                                "evidence_level": "moderate",
                            }
                        ],
                        "extracted_claims": [
                            {
                                "claim_id": "necrotic_area_ratio_mri",
                                "claim_type": "candidate_measurement_protocol",
                                "summary": "MRI necrotic area ratio may be useful as a candidate measurement.",
                                "target_protocol_section": "quantitative_evidence_protocol.measurement_evidence",
                                "modality": "MRI",
                                "applicability": {
                                    "population": "adult hip pain cohort",
                                    "requires_external_validation": True,
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.research_evidence_builder",
                    "--input-json",
                    str(request_path),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=Path.cwd(),
                check=True,
                text=True,
                capture_output=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema_version"], "research_evidence_proposal.v1")
            self.assertFalse(payload["runtime_safety"]["paper_search_performed"])
            self.assertFalse(payload["runtime_safety"]["formal_skill_updated"])
            self.assertTrue((output_dir / "research_evidence_proposal.json").exists())
            self.assertTrue((output_dir / "research_evidence_quality_gate.json").exists())


if __name__ == "__main__":
    unittest.main()
