import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.research_evidence_builder import (
    ResearchEvidenceRetriever,
    build_research_evidence_proposal,
    build_research_evidence_proposal_from_request,
)


class ResearchEvidenceGatewayTest(unittest.TestCase):
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
