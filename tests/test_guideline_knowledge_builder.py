import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.evidence_summary_tool import EvidenceSummaryTool
from tools.guideline_extraction_tool import GuidelineExtractionTool
from tools.guideline_source_import_tool import GuidelineSourceImportTool
from tools.guideline_search_tool import GuidelineSearchTool
from tools.knowledge_builder_tool import KnowledgeBuilderTool
from tools.visual_protocol_validator import VisualProtocolValidator


class GuidelineKnowledgeBuilderTest(unittest.TestCase):
    def test_guideline_search_finds_official_source_without_network(self):
        result = GuidelineSearchTool().search(
            disease_key="femoral_head_necrosis",
            disease_name="股骨头坏死",
        )

        self.assertTrue(result["has_guideline"])
        self.assertEqual(result["source_type"], "medical_guideline")
        self.assertEqual(result["evidence_level"], "high")
        self.assertGreaterEqual(len(result["sources"]), 1)
        self.assertIn("guideline_documents", result)
        self.assertNotIn("guideline_payload", result)

    def test_guideline_search_loads_default_source_catalog_from_file(self):
        result = GuidelineSearchTool().search(
            disease_key="diffuse_glioma_brats",
            disease_name="成人弥漫性胶质瘤",
        )

        self.assertEqual(result["source_catalog_path"], "data/guidelines/guideline_sources.json")
        self.assertGreaterEqual(len(result["guideline_documents"]), 2)
        self.assertEqual(
            result["guideline_documents"][0]["source_id"],
            "eano_adult_diffuse_glioma_guideline",
        )

    def test_guideline_search_finds_pneumonia_chest_xray_source(self):
        result = GuidelineSearchTool().search(
            disease_key="pneumonia_chest_xray",
            disease_name="成人社区获得性肺炎胸片评估",
        )

        self.assertTrue(result["has_guideline"])
        self.assertEqual(result["source_type"], "medical_guideline")
        self.assertEqual(result["evidence_level"], "high")
        self.assertGreaterEqual(len(result["guideline_documents"]), 2)
        self.assertEqual(
            result["guideline_documents"][0]["source_id"],
            "ats_idsa_cap_adults_2019",
        )

    def test_guideline_search_finds_ipf_hrct_source(self):
        result = GuidelineSearchTool().search(
            disease_key="idiopathic_pulmonary_fibrosis_hrct",
            disease_name="特发性肺纤维化 HRCT 评估",
        )

        self.assertTrue(result["has_guideline"])
        self.assertEqual(result["source_type"], "medical_guideline")
        self.assertEqual(result["evidence_level"], "high")
        self.assertGreaterEqual(len(result["guideline_documents"]), 2)
        self.assertEqual(
            result["sources"][0]["source_id"],
            "ats_ers_jrs_alat_ipf_2022",
        )
        knowledge = KnowledgeBuilderTool().build_guideline_knowledge_from_search(result)
        self.assertIn("HRCT chest", knowledge["required_image_views"])
        self.assertIn("UIP_pattern", knowledge["staging_rules"])
        self.assertEqual(
            knowledge["visual_protocol"]["disease_target"],
            "idiopathic_pulmonary_fibrosis_hrct",
        )

    def test_guideline_search_can_load_custom_source_catalog_file(self):
        with TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "custom_guideline_sources.json"
            source_path.write_text(
                json.dumps(
                    {
                        "custom_disease": {
                            "disease_name": "自定义疾病",
                            "source_type": "medical_guideline",
                            "evidence_level": "medium",
                            "sources": [
                                {
                                    "title": "Custom guideline",
                                    "publisher": "Test publisher",
                                    "source_id": "custom_guideline",
                                }
                            ],
                            "guideline_documents": [
                                {
                                    "title": "Custom guideline",
                                    "source_id": "custom_guideline",
                                    "sections": [
                                        {
                                            "heading": "required_image_views",
                                            "text": "CT; MRI",
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = GuidelineSearchTool(source_catalog_path=source_path).search(
                disease_key="custom_disease",
                disease_name="自定义疾病",
            )

        self.assertTrue(result["has_guideline"])
        self.assertEqual(result["source_catalog_path"], str(source_path))
        self.assertEqual(result["guideline_documents"][0]["sections"][0]["text"], "CT; MRI")

    def test_guideline_source_import_converts_raw_guideline_text_to_catalog_entry(self):
        raw_text = """disease_key: test_glioma
disease_name: 测试胶质瘤
source_type: medical_guideline
evidence_level: high
title: Test glioma guideline
publisher: Test Society
source_id: test_glioma_guideline
url: https://example.org/test-glioma-guideline
source_kind: peer_reviewed_guideline
evidence_note: Test guideline section citation
publication_year: 2025
region: global
source_priority: 9

## clinical_features
common_symptoms: 头痛; 癫痫发作
risk_factors: 既往颅脑放疗史

## required_image_views
MRI T1; MRI T1ce; MRI FLAIR

## visual_protocol
disease_target: test_glioma
segmentation_targets: whole_tumor; enhancing_tumor
required_modalities.enhancing_tumor: T1ce
"""
        entry = GuidelineSourceImportTool().import_text(raw_text)

        self.assertEqual(entry["disease_key"], "test_glioma")
        self.assertEqual(entry["catalog_entry"]["disease_name"], "测试胶质瘤")
        self.assertEqual(entry["catalog_entry"]["sources"][0]["source_id"], "test_glioma_guideline")
        document = entry["catalog_entry"]["guideline_documents"][0]
        self.assertEqual(document["title"], "Test glioma guideline")
        self.assertEqual(document["sections"][0]["heading"], "clinical_features")
        self.assertIn("头痛", document["sections"][0]["text"])
        self.assertEqual(
            document["sections"][0]["citations"][0]["url"],
            "https://example.org/test-glioma-guideline",
        )
        self.assertEqual(
            document["sections"][0]["citations"][0]["source_kind"],
            "peer_reviewed_guideline",
        )
        self.assertEqual(entry["catalog_entry"]["sources"][0]["publication_year"], "2025")
        self.assertEqual(entry["catalog_entry"]["sources"][0]["region"], "global")
        self.assertEqual(entry["catalog_entry"]["sources"][0]["source_priority"], "9")

    def test_guideline_source_import_appends_raw_text_to_catalog_file(self):
        raw_text = """disease_key: imported_disease
disease_name: 导入疾病
source_type: medical_guideline
evidence_level: medium
title: Imported guideline
publisher: Imported Society
source_id: imported_guideline

## required_image_views
CT; MRI
"""
        with TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "imported_guideline.txt"
            catalog_path = Path(tmpdir) / "guideline_sources.json"
            raw_path.write_text(raw_text, encoding="utf-8")

            GuidelineSourceImportTool().import_file(
                raw_path=raw_path,
                catalog_path=catalog_path,
            )
            result = GuidelineSearchTool(source_catalog_path=catalog_path).search(
                disease_key="imported_disease",
                disease_name="导入疾病",
            )

        self.assertTrue(result["has_guideline"])
        self.assertEqual(result["source_catalog_path"], str(catalog_path))
        self.assertEqual(result["guideline_documents"][0]["sections"][0]["text"], "CT; MRI")

    def test_guideline_source_import_merges_multiple_documents_for_same_disease(self):
        first_text = """disease_key: merged_disease
disease_name: 合并疾病
source_type: medical_guideline
evidence_level: high
title: First guideline
publisher: First Society
source_id: first_guideline

## clinical_features
common_symptoms: 头痛
"""
        second_text = """disease_key: merged_disease
disease_name: 合并疾病
source_type: medical_guideline
evidence_level: high
title: Second guideline
publisher: Second Society
source_id: second_guideline

## visual_protocol
disease_target: merged_disease
"""
        with TemporaryDirectory() as tmpdir:
            catalog_path = Path(tmpdir) / "guideline_sources.json"
            first_path = Path(tmpdir) / "first.txt"
            second_path = Path(tmpdir) / "second.txt"
            first_path.write_text(first_text, encoding="utf-8")
            second_path.write_text(second_text, encoding="utf-8")

            tool = GuidelineSourceImportTool()
            tool.import_file(raw_path=first_path, catalog_path=catalog_path)
            tool.import_file(raw_path=second_path, catalog_path=catalog_path)

            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

        entry = catalog["merged_disease"]
        self.assertEqual(
            [source["source_id"] for source in entry["sources"]],
            ["first_guideline", "second_guideline"],
        )
        self.assertEqual(
            [document["source_id"] for document in entry["guideline_documents"]],
            ["first_guideline", "second_guideline"],
        )

    def test_guideline_extraction_parses_documents_into_knowledge_payload(self):
        documents = [
            {
                "title": "EANO adult diffuse glioma guideline",
                "sections": [
                    {
                        "heading": "clinical_features",
                        "text": "common_symptoms: 头痛; 癫痫发作\nrisk_factors: 既往颅脑放疗史",
                        "citations": [
                            {
                                "title": "EANO adult diffuse glioma guideline",
                                "url": "https://example.org/eano",
                                "source_kind": "official_guideline",
                                "evidence_note": "Clinical features section",
                            }
                        ],
                    },
                    {
                        "heading": "required_image_views",
                        "text": "MRI T1; MRI T1ce; MRI T2; MRI FLAIR",
                    },
                    {
                        "heading": "visual_targets",
                        "text": (
                            "anatomy: 大脑半球; 脑室\n"
                            "lesion_features: whole tumor; tumor core; enhancing tumor"
                        ),
                    },
                    {
                        "heading": "staging_rules",
                        "text": (
                            "integrated_diagnosis_required: "
                            "EANO/WHO 体系强调组织学和分子诊断整合 | "
                            "required_non_imaging_evidence=IDH 状态; 1p/19q 共缺失"
                        ),
                    },
                    {
                        "heading": "vision_agent_tasks",
                        "text": (
                            "segmentation_targets: whole tumor; tumor core; enhancing tumor\n"
                            "quantitative_features: whole_tumor_volume_ml; tumor_core_volume_ml"
                        ),
                    },
                    {
                        "heading": "visual_protocol",
                        "text": (
                            "disease_target: diffuse_glioma_adult\n"
                            "segmentation_targets: whole_tumor; tumor_core; enhancing_tumor\n"
                            "required_modalities.enhancing_tumor: T1ce"
                        ),
                    },
                ],
            }
        ]

        payload = GuidelineExtractionTool().extract(
            disease_key="diffuse_glioma_brats",
            disease_name="成人弥漫性胶质瘤",
            documents=documents,
        )

        self.assertIn("头痛", payload["clinical_features"]["common_symptoms"])
        self.assertIn("MRI FLAIR", payload["required_image_views"])
        self.assertIn("whole tumor", payload["visual_targets"]["lesion_features"])
        self.assertIn("integrated_diagnosis_required", payload["staging_rules"])
        self.assertIn("whole tumor", payload["vision_agent_tasks"]["segmentation_targets"])
        self.assertEqual(payload["visual_protocol"]["disease_target"], "diffuse_glioma_adult")
        self.assertEqual(
            payload["visual_protocol"]["required_modalities"]["enhancing_tumor"],
            ["T1ce"],
        )
        self.assertEqual(
            payload["guideline_extraction"]["citations"][0]["url"],
            "https://example.org/eano",
        )

    def test_guideline_extraction_merges_repeated_keyed_list_lines(self):
        payload = GuidelineExtractionTool().extract(
            disease_key="repeated_keys",
            disease_name="重复字段疾病",
            documents=[
                {
                    "title": "Repeated key guideline",
                    "sections": [
                        {
                            "heading": "clinical_features",
                            "text": (
                                "common_symptoms: hip pain; groin pain\n"
                                "common_symptoms: knee pain; limited hip internal rotation"
                            ),
                        }
                    ],
                }
            ],
        )

        self.assertEqual(
            payload["clinical_features"]["common_symptoms"],
            ["hip pain", "groin pain", "knee pain", "limited hip internal rotation"],
        )

    def test_evidence_summary_never_labels_dataset_summary_as_guideline(self):
        summary = EvidenceSummaryTool().summarize_observations(
            disease_name="罕见病示例",
            observations=["已确诊病例中常见局部纹理异常"],
        )

        self.assertEqual(summary["mode"], "evidence_summary_mode")
        self.assertEqual(summary["source_type"], "internal_dataset_summary")
        self.assertEqual(summary["evidence_level"], "low")
        self.assertIn("不等同于正式医学指南", summary["warning"])

    def test_knowledge_builder_uses_guideline_search_for_guideline_based_knowledge(self):
        with TemporaryDirectory() as tmpdir:
            knowledge = KnowledgeBuilderTool(knowledges_dir=Path(tmpdir)).prepare_knowledge(
                disease_key="femoral_head_necrosis",
                disease_name="股骨头坏死",
                observations=["髋关节疼痛"],
            )

        self.assertEqual(knowledge["knowledge_type"], "guideline_based")
        self.assertEqual(knowledge["evidence_level"], "high")
        self.assertEqual(knowledge["source_type"], "medical_guideline")
        self.assertIn("source_documents", knowledge)
        self.assertTrue(VisualProtocolValidator().validate_knowledge(knowledge)["valid"])
        self.assertEqual(knowledge["quality_control"]["visual_protocol_status"], "valid")
        self.assertTrue(knowledge["quality_control"]["can_enter_formal_guideline_knowledge"])
        self.assertIn("alignment_tasks", knowledge["visual_protocol"])
        self.assertEqual(knowledge["visual_protocol"]["required_next_images"][0]["modality"], "MRI")
        self.assertIn("blocked", knowledge["visual_protocol"]["diagnosis_scope"])

    def test_knowledge_builder_uses_formal_guideline_template_for_secondary_hip_knowledge(self):
        with TemporaryDirectory() as tmpdir:
            knowledge = KnowledgeBuilderTool(knowledges_dir=Path(tmpdir)).prepare_knowledge(
                disease_key="osteoarthritis_or_degenerative_hip_disease",
                disease_name="骨关节炎或退行性髋关节病变",
                observations=["髋关节疼痛"],
            )

        self.assertEqual(knowledge["knowledge_type"], "guideline_based")
        self.assertEqual(knowledge["source_type"], "medical_guideline")
        self.assertEqual(knowledge["evidence_level"], "high")
        self.assertIn("ACR Appropriateness Criteria", knowledge["source"])
        self.assertIn("NICE Osteoarthritis", knowledge["source"])
        self.assertNotIn("candidate_observation_rules", knowledge)
        self.assertEqual(knowledge["path_type"], "guideline_aware")
        self.assertIn("髋关节疼痛", knowledge["clinical_features"]["common_symptoms"])
        self.assertIn("骨盆/髋关节 X 光正位", knowledge["required_image_views"])
        self.assertIn("髋关节间隙", knowledge["visual_targets"]["anatomy"])
        self.assertEqual(
            knowledge["visual_protocol"]["disease_target"],
            "osteoarthritis_or_degenerative_hip_disease",
        )
        self.assertTrue(knowledge["visual_protocol"]["finding_targets"])
        self.assertTrue(knowledge["visual_protocol"]["insufficiency_rules"])
        self.assertTrue(knowledge["source_documents"][0]["url"])
        self.assertTrue(VisualProtocolValidator().validate_knowledge(knowledge)["valid"])

    def test_guideline_search_result_builds_actionable_guideline_knowledge(self):
        with TemporaryDirectory() as tmpdir:
            knowledge = KnowledgeBuilderTool(knowledges_dir=Path(tmpdir)).prepare_knowledge(
                disease_key="diffuse_glioma_brats",
                disease_name="成人弥漫性胶质瘤",
                observations=["MRI FLAIR 见异常高信号"],
            )

        self.assertEqual(knowledge["knowledge_type"], "guideline_based")
        self.assertEqual(knowledge["path_type"], "guideline_aware")
        self.assertEqual(
            knowledge["guideline_source"]["source_catalog_path"],
            "data/guidelines/guideline_sources.json",
        )
        self.assertIn("guideline_extraction", knowledge)
        self.assertEqual(knowledge["guideline_extraction"]["tool"], "GuidelineExtractionTool")
        self.assertIn("citations", knowledge["guideline_extraction"])
        self.assertTrue(knowledge["guideline_extraction"]["citations"])
        self.assertIn("头痛", knowledge["clinical_features"]["common_symptoms"])
        self.assertIn("MRI FLAIR", knowledge["required_image_views"])
        self.assertIn("integrated_diagnosis_required", knowledge["staging_rules"])
        self.assertIn("whole tumor", knowledge["vision_agent_tasks"]["segmentation_targets"])
        self.assertEqual(knowledge["visual_protocol"]["disease_target"], "diffuse_glioma_adult")
        self.assertEqual(
            knowledge["visual_protocol"]["required_modalities"]["enhancing_tumor"],
            ["T1ce"],
        )
        self.assertEqual(knowledge["quality_control"]["visual_protocol_status"], "valid")
        self.assertEqual(knowledge["quality_control"]["visual_protocol_errors"], [])
        self.assertTrue(knowledge["visual_protocol"]["alignment_tasks"])
        self.assertTrue(knowledge["visual_protocol"]["required_next_images"])
        self.assertTrue(knowledge["visual_protocol"]["diagnosis_scope"]["blocked"])

    def test_knowledge_builder_marks_multi_source_conflicts_and_source_priority(self):
        guideline_result = {
            "disease_key": "conflict_disease",
            "disease_name": "冲突指南疾病",
            "has_guideline": True,
            "source_type": "medical_guideline",
            "evidence_level": "high",
            "source_catalog_path": "output/fake/conflict_catalog.json",
            "sources": [
                {
                    "source_id": "newer_guideline",
                    "title": "Newer guideline",
                    "publisher": "New Society",
                    "url": "https://example.org/newer",
                    "publication_year": "2024",
                    "region": "global",
                    "source_priority": "10",
                },
                {
                    "source_id": "older_guideline",
                    "title": "Older guideline",
                    "publisher": "Old Society",
                    "url": "https://example.org/older",
                    "publication_year": "2018",
                    "region": "regional",
                    "source_priority": "5",
                },
            ],
            "guideline_documents": [
                {
                    "source_id": "newer_guideline",
                    "title": "Newer guideline",
                    "sections": [
                        {
                            "heading": "required_image_views",
                            "text": "MRI; CT",
                            "citations": [
                                {
                                    "source_id": "newer_guideline",
                                    "title": "Newer guideline",
                                    "url": "https://example.org/newer",
                                }
                            ],
                        }
                    ],
                },
                {
                    "source_id": "older_guideline",
                    "title": "Older guideline",
                    "sections": [
                        {
                            "heading": "required_image_views",
                            "text": "X-ray; MRI",
                            "citations": [
                                {
                                    "source_id": "older_guideline",
                                    "title": "Older guideline",
                                    "url": "https://example.org/older",
                                }
                            ],
                        }
                    ],
                },
            ],
        }

        knowledge = KnowledgeBuilderTool().build_guideline_knowledge_from_search(guideline_result)

        self.assertEqual(knowledge["source_priority"][0]["source_id"], "newer_guideline")
        self.assertEqual(knowledge["source_priority"][0]["publication_year"], "2024")
        self.assertEqual(knowledge["source_priority"][0]["region"], "global")
        self.assertEqual(knowledge["guideline_conflicts"][0]["field"], "required_image_views")
        self.assertEqual(knowledge["guideline_conflicts"][0]["resolution"], "merged_union_review_required")
        self.assertEqual(
            [source["source_id"] for source in knowledge["guideline_conflicts"][0]["sources"]],
            ["newer_guideline", "older_guideline"],
        )
        self.assertEqual(knowledge["quality_control"]["conflict_status"], "needs_review")
        self.assertEqual(knowledge["quality_control"]["conflict_count"], 1)

    def test_knowledge_builder_grades_conflicts_across_core_guideline_fields(self):
        guideline_result = {
            "disease_key": "graded_conflict_disease",
            "disease_name": "分级冲突疾病",
            "has_guideline": True,
            "source_type": "medical_guideline",
            "evidence_level": "high",
            "source_catalog_path": "output/fake/graded_conflict_catalog.json",
            "sources": [
                {
                    "source_id": "global_2024",
                    "title": "Global 2024 guideline",
                    "publisher": "Global Society",
                    "url": "https://example.org/global-2024",
                    "publication_year": "2024",
                    "region": "global",
                    "source_priority": "10",
                },
                {
                    "source_id": "regional_2018",
                    "title": "Regional 2018 guideline",
                    "publisher": "Regional Society",
                    "url": "https://example.org/regional-2018",
                    "publication_year": "2018",
                    "region": "regional",
                    "source_priority": "5",
                },
            ],
            "guideline_documents": [
                {
                    "source_id": "global_2024",
                    "title": "Global 2024 guideline",
                    "sections": [
                        {
                            "heading": "clinical_features",
                            "text": (
                                "common_symptoms: hip pain; groin pain\n"
                                "risk_factors: corticosteroid use"
                            ),
                            "citations": [
                                {
                                    "source_id": "global_2024",
                                    "title": "Global 2024 guideline",
                                    "url": "https://example.org/global-2024",
                                }
                            ],
                        },
                        {"heading": "required_image_views", "text": "MRI; X-ray"},
                        {
                            "heading": "visual_protocol",
                            "text": (
                                "disease_target: onfh\n"
                                "required_modalities.lesion_extent: MRI"
                            ),
                        },
                        {
                            "heading": "staging_rules",
                            "text": "ARCO_I: MRI abnormal and radiograph normal",
                        },
                        {
                            "heading": "vision_agent_tasks",
                            "text": "segmentation_targets: femoral_head\nquantitative_features: lesion_area_ratio",
                        },
                    ],
                },
                {
                    "source_id": "regional_2018",
                    "title": "Regional 2018 guideline",
                    "sections": [
                        {
                            "heading": "clinical_features",
                            "text": (
                                "common_symptoms: hip pain; knee pain\n"
                                "risk_factors: alcohol use"
                            ),
                            "citations": [
                                {
                                    "source_id": "regional_2018",
                                    "title": "Regional 2018 guideline",
                                    "url": "https://example.org/regional-2018",
                                }
                            ],
                        },
                        {"heading": "required_image_views", "text": "MRI; X-ray"},
                        {
                            "heading": "visual_protocol",
                            "text": (
                                "disease_target: onfh\n"
                                "required_modalities.lesion_extent: MRI; CT"
                            ),
                        },
                        {
                            "heading": "staging_rules",
                            "text": "ARCO_I: bone scan or MRI abnormal before radiograph changes",
                        },
                        {
                            "heading": "vision_agent_tasks",
                            "text": "segmentation_targets: femoral_head\nquantitative_features: lesion_area_ratio",
                        },
                    ],
                },
            ],
        }

        knowledge = KnowledgeBuilderTool().build_guideline_knowledge_from_search(guideline_result)
        conflicts_by_field = {
            conflict["field"]: conflict
            for conflict in knowledge["guideline_conflicts"]
        }

        self.assertEqual(
            conflicts_by_field["clinical_features.common_symptoms"]["severity"],
            "low",
        )
        self.assertEqual(
            conflicts_by_field["clinical_features.risk_factors"]["severity"],
            "low",
        )
        self.assertEqual(
            conflicts_by_field["visual_protocol.required_modalities.lesion_extent"]["severity"],
            "medium",
        )
        self.assertEqual(conflicts_by_field["staging_rules.ARCO_I"]["severity"], "high")
        self.assertEqual(knowledge["quality_control"]["highest_conflict_severity"], "high")
        self.assertEqual(knowledge["quality_control"]["conflict_severity_counts"]["low"], 2)
        self.assertEqual(knowledge["quality_control"]["conflict_severity_counts"]["medium"], 1)
        self.assertEqual(knowledge["quality_control"]["conflict_severity_counts"]["high"], 1)
        self.assertEqual(knowledge["quality_control"]["missing_core_sections"], [])
        self.assertEqual(knowledge["quality_control"]["core_section_status"], "complete")
        self.assertEqual(knowledge["quality_control"]["formal_knowledge_status"], "needs_review")
        self.assertFalse(knowledge["quality_control"]["can_enter_formal_guideline_knowledge"])

    def test_knowledge_builder_quality_gate_marks_missing_core_sections(self):
        guideline_result = {
            "disease_key": "incomplete_guideline",
            "disease_name": "不完整指南疾病",
            "has_guideline": True,
            "source_type": "medical_guideline",
            "evidence_level": "high",
            "source_catalog_path": "output/fake/incomplete_catalog.json",
            "sources": [
                {
                    "source_id": "incomplete_source",
                    "title": "Incomplete guideline",
                    "publisher": "Incomplete Society",
                    "url": "https://example.org/incomplete",
                }
            ],
            "guideline_documents": [
                {
                    "source_id": "incomplete_source",
                    "title": "Incomplete guideline",
                    "sections": [
                        {
                            "heading": "clinical_features",
                            "text": "common_symptoms: hip pain",
                            "citations": [
                                {
                                    "source_id": "incomplete_source",
                                    "title": "Incomplete guideline",
                                    "url": "https://example.org/incomplete",
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        knowledge = KnowledgeBuilderTool().build_guideline_knowledge_from_search(guideline_result)

        self.assertIn("required_image_views", knowledge["quality_control"]["missing_core_sections"])
        self.assertIn("vision_agent_tasks", knowledge["quality_control"]["missing_core_sections"])
        self.assertEqual(knowledge["quality_control"]["core_section_status"], "incomplete")
        self.assertEqual(knowledge["quality_control"]["source_priority_status"], "implicit_order")
        self.assertEqual(knowledge["quality_control"]["formal_knowledge_status"], "needs_review")
        self.assertFalse(knowledge["quality_control"]["can_enter_formal_guideline_knowledge"])

    def test_knowledge_builder_uses_evidence_summary_for_missing_guideline(self):
        with TemporaryDirectory() as tmpdir:
            knowledge = KnowledgeBuilderTool(knowledges_dir=Path(tmpdir)).prepare_knowledge(
                disease_key="rare_disease_without_guideline",
                disease_name="罕见病示例",
                observations=["已确诊病例中常见局部纹理异常"],
            )

        self.assertEqual(knowledge["knowledge_type"], "data_mined_hypothesis")
        self.assertEqual(knowledge["evidence_level"], "low")
        self.assertEqual(knowledge["source_type"], "internal_dataset_summary")
        self.assertEqual(knowledge["evidence_summary_mode"], "evidence_summary_mode")
        self.assertIn("不等同于正式医学指南", knowledge["warning"])
        self.assertEqual(knowledge["path_type"], "privileged_knowledge_discovery")
        self.assertEqual(knowledge["safety_gate"]["mode_required"], "hypothesis_validation")
        self.assertIn("确诊", knowledge["safety_gate"]["forbidden_claims"])
        self.assertEqual(
            knowledge["safety_gate"]["allowed_outputs"],
            ["early_risk_alert", "research_warning", "recommend_gold_standard_confirmation"],
        )
        self.assertEqual(knowledge["discovery_metadata"]["teacher_signal"], "not_configured_yet")
        self.assertEqual(knowledge["required_modalities"]["deployment"], ["low_cost_or_routine_image"])

    def test_knowledge_builder_can_persist_generated_knowledge_when_explicitly_requested(self):
        with TemporaryDirectory() as tmpdir:
            knowledges_dir = Path(tmpdir)
            knowledge = KnowledgeBuilderTool(knowledges_dir=knowledges_dir).prepare_knowledge(
                disease_key="rare_disease_without_guideline",
                disease_name="罕见病示例",
                observations=["已确诊病例中常见局部纹理异常"],
                persist=True,
            )

            saved_path = knowledges_dir / "rare_disease_without_guideline.yaml"
            self.assertTrue(saved_path.exists())
            self.assertIn(knowledge["knowledge_type"], saved_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
