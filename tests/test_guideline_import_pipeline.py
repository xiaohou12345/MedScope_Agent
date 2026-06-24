import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.diagnosis_agent import DiagnosisDoctorAgent
from agents.vision_agent import VisionAgent
from scripts.guideline_import_to_knowledge_demo import run_guideline_import_to_knowledge


class GuidelineImportPipelineTest(unittest.TestCase):
    def test_raw_guideline_text_imports_to_catalog_and_builds_guideline_knowledge(self):
        raw_text = """disease_key: imported_glioma
disease_name: 导入胶质瘤
source_type: medical_guideline
evidence_level: high
title: Imported glioma guideline
publisher: Imported Society
source_id: imported_glioma_guideline

## clinical_features
common_symptoms: 头痛; 癫痫发作
risk_factors: 既往颅脑放疗史

## required_image_views
MRI T1; MRI T1ce; MRI FLAIR

## vision_agent_tasks
segmentation_targets: whole tumor; enhancing tumor
quantitative_features: whole_tumor_volume_ml; enhancing_tumor_volume_ml

## visual_protocol
disease_target: imported_glioma
segmentation_targets: whole_tumor; enhancing_tumor
required_modalities.whole_tumor: FLAIR
required_modalities.enhancing_tumor: T1ce
measurements: whole_tumor_volume_ml; enhancing_tumor_volume_ml
"""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            raw_path = output_dir / "raw_guideline.txt"
            catalog_path = output_dir / "guideline_sources.json"
            knowledge_path = output_dir / "imported_glioma_guideline_knowledge.json"
            raw_path.write_text(raw_text, encoding="utf-8")

            result = run_guideline_import_to_knowledge(
                raw_path=raw_path,
                catalog_path=catalog_path,
                knowledge_output_path=knowledge_path,
                disease_key="imported_glioma",
                disease_name="导入胶质瘤",
            )

            knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))

        self.assertEqual(result["knowledge_output_path"], str(knowledge_path))
        self.assertEqual(knowledge["knowledge_type"], "guideline_based")
        self.assertEqual(knowledge["path_type"], "guideline_aware")
        self.assertEqual(knowledge["guideline_source"]["source_catalog_path"], str(catalog_path))
        self.assertIn("头痛", knowledge["clinical_features"]["common_symptoms"])
        self.assertIn("MRI FLAIR", knowledge["required_image_views"])
        self.assertIn("whole tumor", knowledge["vision_agent_tasks"]["segmentation_targets"])
        self.assertEqual(knowledge["visual_protocol"]["disease_target"], "imported_glioma")
        self.assertEqual(
            knowledge["visual_protocol"]["required_modalities"]["enhancing_tumor"],
            ["T1ce"],
        )

    def test_imported_guideline_knowledge_can_be_consumed_by_vision_and_diagnosis_agents(self):
        raw_text = """disease_key: imported_agent_disease
disease_name: 导入 Agent 疾病
source_type: medical_guideline
evidence_level: high
title: Imported agent guideline
publisher: Imported Society
source_id: imported_agent_guideline

## clinical_features
common_symptoms: 髋关节疼痛

## vision_agent_tasks
segmentation_targets: target_region
quantitative_features: texture_abnormality_score
"""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            raw_path = output_dir / "raw_guideline.txt"
            catalog_path = output_dir / "guideline_sources.json"
            knowledge_path = output_dir / "imported_agent_guideline_knowledge.json"
            raw_path.write_text(raw_text, encoding="utf-8")

            run_guideline_import_to_knowledge(
                raw_path=raw_path,
                catalog_path=catalog_path,
                knowledge_output_path=knowledge_path,
                disease_key="imported_agent_disease",
                disease_name="导入 Agent 疾病",
            )
            knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
            visual_result = VisionAgent().analyze_image(
                image_path="data/images/demo_xray.png",
                disease_knowledge=knowledge,
            )
            report = DiagnosisDoctorAgent().generate_report(
                case_id="case_imported_guideline",
                patient_info={"symptoms": ["髋关节疼痛"]},
                visual_result=visual_result,
                disease_knowledge=knowledge,
            )

        self.assertEqual(visual_result["requested_targets"], ["target_region"])
        self.assertEqual(visual_result["requested_features"], ["texture_abnormality_score"])
        self.assertEqual(report["used_knowledge"]["knowledge_type"], "guideline_based")
        self.assertEqual(report["used_knowledge"]["knowledge_id"], "imported_agent_disease_guideline_v0.1")

    def test_imported_guideline_report_exposes_guideline_evidence(self):
        raw_text = """disease_key: cited_agent_disease
disease_name: 引用 Agent 疾病
source_type: medical_guideline
evidence_level: high
title: Cited guideline
publisher: Citation Society
source_id: cited_guideline
url: https://example.org/cited-guideline
source_kind: official_guideline
evidence_note: Citation should reach diagnosis report

## clinical_features
common_symptoms: 髋关节疼痛

## vision_agent_tasks
segmentation_targets: target_region
quantitative_features: texture_abnormality_score
"""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            raw_path = output_dir / "raw_guideline.txt"
            catalog_path = output_dir / "guideline_sources.json"
            knowledge_path = output_dir / "cited_agent_guideline_knowledge.json"
            raw_path.write_text(raw_text, encoding="utf-8")

            run_guideline_import_to_knowledge(
                raw_path=raw_path,
                catalog_path=catalog_path,
                knowledge_output_path=knowledge_path,
                disease_key="cited_agent_disease",
                disease_name="引用 Agent 疾病",
            )
            knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
            visual_result = VisionAgent().analyze_image(
                image_path="data/images/demo_xray.png",
                disease_knowledge=knowledge,
            )
            report = DiagnosisDoctorAgent().generate_report(
                case_id="case_cited_guideline",
                patient_info={"symptoms": ["髋关节疼痛"]},
                visual_result=visual_result,
                disease_knowledge=knowledge,
            )

        self.assertIn("guideline_evidence", report)
        self.assertEqual(report["指南依据"][0]["url"], "https://example.org/cited-guideline")
        self.assertEqual(
            report["guideline_evidence"]["citations"][0]["evidence_note"],
            "Citation should reach diagnosis report",
        )
        self.assertEqual(
            report["used_knowledge"]["guideline_extraction"]["citations"][0]["source_kind"],
            "official_guideline",
        )

    def test_diagnosis_report_exposes_guideline_conflicts_and_source_priority(self):
        knowledge = {
            "disease_name": "冲突指南疾病",
            "knowledge_id": "conflict_guideline_v0.1",
            "knowledge_type": "guideline_based",
            "evidence_level": "high",
            "source": "Newer guideline; Older guideline",
            "source_documents": [
                {"source_id": "newer_guideline", "title": "Newer guideline"},
                {"source_id": "older_guideline", "title": "Older guideline"},
            ],
            "source_priority": [
                {"source_id": "newer_guideline", "publication_year": "2024"},
                {"source_id": "older_guideline", "publication_year": "2018"},
            ],
            "guideline_extraction": {
                "tool": "GuidelineExtractionTool",
                "citations": [
                    {
                        "source_id": "newer_guideline",
                        "title": "Newer guideline",
                        "url": "https://example.org/newer",
                    }
                ],
            },
            "guideline_conflicts": [
                {
                    "field": "required_image_views",
                    "status": "conflict",
                    "resolution": "merged_union_review_required",
                }
            ],
        }
        visual_result = VisionAgent().analyze_image(
            image_path="data/images/demo_xray.png",
            disease_knowledge=knowledge,
        )
        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_conflict_guideline",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
            disease_knowledge=knowledge,
        )

        self.assertEqual(
            report["guideline_evidence"]["source_priority"][0]["source_id"],
            "newer_guideline",
        )
        self.assertEqual(
            report["guideline_evidence"]["conflicts"][0]["field"],
            "required_image_views",
        )


if __name__ == "__main__":
    unittest.main()
