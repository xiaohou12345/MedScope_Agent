import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.collect_guideline_source import main as collect_guideline_source_main
from tools.guideline_section_mapper_tool import GuidelineSectionMapperTool
from tools.guideline_source_collector_tool import GuidelineSourceCollectorTool
from tools.guideline_search_tool import GuidelineSearchTool
from tools.skill_builder_tool import SkillBuilderTool


class GuidelineSourceCollectorTest(unittest.TestCase):
    def test_section_mapper_converts_real_world_headings_to_canonical_sections(self):
        mapped_text = GuidelineSectionMapperTool().map_text(
            """
            ## Clinical manifestations
            Patients may present with hip pain, groin pain, restricted range of motion.

            ## Imaging and diagnosis
            Plain radiography, CT, MRI, SPECT, and PET may be used.

            ## ARCO staging
            Stage I has abnormal MRI and normal radiographs. Stage III includes collapse.

            ## Treatment recommendations
            Core decompression may be considered before collapse. Total hip arthroplasty
            is used for advanced collapse.
            """
        )

        self.assertIn("## clinical_features", mapped_text)
        self.assertIn("common_symptoms: hip pain; groin pain; restricted range of motion", mapped_text)
        self.assertIn("## required_image_views", mapped_text)
        self.assertIn("Plain radiography; CT; MRI; SPECT; PET", mapped_text)
        self.assertIn("## staging_rules", mapped_text)
        self.assertIn("ARCO_staging:", mapped_text)
        self.assertIn("## report_requirements", mapped_text)
        self.assertIn("treatment_context:", mapped_text)

    def test_section_mapper_skips_author_and_reference_noise(self):
        mapped_text = GuidelineSectionMapperTool().map_text(
            """
            ## Guidelines for clinical diagnosis and treatment of osteonecrosis
            Dewei Zhao

            ## Author information
            Department of Orthopaedics, University Hospital.

            ## References
            1. Example citation.

            ## Clinical diagnosis
            Pain is primarily localized in the hip, buttock, or groin area.
            MRI, CT, and X-ray imaging may be used for diagnosis.
            """
        )

        self.assertNotIn("Dewei Zhao", mapped_text)
        self.assertNotIn("Author information", mapped_text)
        self.assertNotIn("Example citation", mapped_text)
        self.assertIn("## clinical_features", mapped_text)
        self.assertIn("hip pain", mapped_text)
        self.assertIn("## required_image_views", mapped_text)
        self.assertIn("MRI; CT; X-ray", mapped_text)

    def test_collect_html_guideline_source_writes_raw_file_with_citation_metadata(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_path = tmp / "guideline.html"
            raw_path = tmp / "raw_guideline.txt"
            html_path.write_text(
                """
                <html>
                  <head><title>Ignored</title><script>remove_me()</script></head>
                  <body>
                    <h1>Clinical Guideline</h1>
                    <h2>clinical_features</h2>
                    <p>common_symptoms: 头痛; 癫痫发作</p>
                    <h2>required_image_views</h2>
                    <p>MRI T1; MRI FLAIR</p>
                  </body>
                </html>
                """,
                encoding="utf-8",
            )

            result = GuidelineSourceCollectorTool().collect_to_raw_file(
                source=str(html_path),
                raw_output_path=raw_path,
                metadata={
                    "disease_key": "html_guideline",
                    "disease_name": "HTML 指南病种",
                    "source_type": "medical_guideline",
                    "evidence_level": "high",
                    "title": "HTML guideline",
                    "publisher": "HTML Society",
                    "source_id": "html_guideline_source",
                    "source_kind": "official_guideline",
                    "evidence_note": "Collected from HTML",
                },
            )

            raw_text = raw_path.read_text(encoding="utf-8")

        self.assertEqual(result["raw_output_path"], str(raw_path))
        self.assertIn("url: " + str(html_path), raw_text)
        self.assertIn("source_kind: official_guideline", raw_text)
        self.assertIn("## clinical_features", raw_text)
        self.assertIn("common_symptoms: 头痛; 癫痫发作", raw_text)
        self.assertNotIn("remove_me", raw_text)

    def test_collect_html_guideline_source_preserves_priority_metadata(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_path = tmp / "priority_guideline.html"
            raw_path = tmp / "priority_raw.txt"
            catalog_path = tmp / "priority_catalog.json"
            html_path.write_text(
                """
                <h1>Priority Guideline</h1>
                <h2>required_image_views</h2>
                <p>HRCT chest</p>
                """,
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                collect_guideline_source_main(
                    [
                        "--source",
                        str(html_path),
                        "--raw-output-path",
                        str(raw_path),
                        "--catalog-path",
                        str(catalog_path),
                        "--import-to-catalog",
                        "--disease-key",
                        "priority_guideline",
                        "--disease-name",
                        "优先级指南病种",
                        "--title",
                        "Priority guideline",
                        "--publisher",
                        "Priority Society",
                        "--source-id",
                        "priority_guideline_source",
                        "--publication-year",
                        "2022",
                        "--region",
                        "international",
                        "--source-priority",
                        "10",
                    ]
                )
            search_result = GuidelineSearchTool(source_catalog_path=catalog_path).search(
                disease_key="priority_guideline",
                disease_name="优先级指南病种",
            )

        source = search_result["sources"][0]
        self.assertEqual(source["publication_year"], "2022")
        self.assertEqual(source["region"], "international")
        self.assertEqual(source["source_priority"], "10")

    def test_collector_can_semantic_map_html_before_import(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_path = tmp / "semantic_guideline.html"
            raw_path = tmp / "semantic_raw.txt"
            catalog_path = tmp / "semantic_catalog.json"
            html_path.write_text(
                """
                <h1>Semantic Guideline</h1>
                <h2>Clinical manifestations</h2>
                <p>Patients may present with headache, seizures, focal neurologic deficits.</p>
                <h2>Imaging diagnosis</h2>
                <p>MRI T1, MRI T1ce, MRI T2 and MRI FLAIR are used.</p>
                """,
                encoding="utf-8",
            )

            GuidelineSourceCollectorTool().collect_to_raw_file(
                source=str(html_path),
                raw_output_path=raw_path,
                metadata={
                    "disease_key": "semantic_guideline",
                    "disease_name": "语义映射指南病种",
                    "source_type": "medical_guideline",
                    "evidence_level": "high",
                    "title": "Semantic guideline",
                    "publisher": "Semantic Society",
                    "source_id": "semantic_guideline_source",
                },
                semantic_map=True,
            )
            with redirect_stdout(io.StringIO()):
                collect_guideline_source_main(
                    [
                        "--source",
                        str(html_path),
                        "--raw-output-path",
                        str(raw_path),
                        "--catalog-path",
                        str(catalog_path),
                        "--import-to-catalog",
                        "--semantic-map",
                        "--disease-key",
                        "semantic_guideline",
                        "--disease-name",
                        "语义映射指南病种",
                        "--title",
                        "Semantic guideline",
                        "--publisher",
                        "Semantic Society",
                        "--source-id",
                        "semantic_guideline_source",
                    ]
                )
            search_result = GuidelineSearchTool(source_catalog_path=catalog_path).search(
                disease_key="semantic_guideline",
                disease_name="语义映射指南病种",
            )
            skill = SkillBuilderTool(
                guideline_search_tool=GuidelineSearchTool(source_catalog_path=catalog_path)
            ).build_guideline_skill_from_search(search_result)

        self.assertIn("headache", skill["clinical_features"]["common_symptoms"])
        self.assertIn("MRI FLAIR", skill["required_image_views"])

    def test_collected_html_guideline_can_enter_skill_builder_pipeline(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_path = tmp / "pipeline_guideline.html"
            raw_path = tmp / "pipeline_raw.txt"
            catalog_path = tmp / "guideline_sources.json"
            html_path.write_text(
                """
                <h1>Pipeline Guideline</h1>
                <h2>clinical_features</h2>
                <p>common_symptoms: 髋关节疼痛</p>
                <h2>vision_agent_tasks</h2>
                <p>segmentation_targets: lesion_region</p>
                <p>quantitative_features: lesion_area_ratio</p>
                """,
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                collect_guideline_source_main(
                    [
                        "--source",
                        str(html_path),
                        "--raw-output-path",
                        str(raw_path),
                        "--catalog-path",
                        str(catalog_path),
                        "--import-to-catalog",
                        "--disease-key",
                        "pipeline_guideline",
                        "--disease-name",
                        "Pipeline 指南病种",
                        "--source-type",
                        "medical_guideline",
                        "--evidence-level",
                        "high",
                        "--title",
                        "Pipeline guideline",
                        "--publisher",
                        "Pipeline Society",
                        "--source-id",
                        "pipeline_guideline_source",
                        "--source-kind",
                        "clinical_guideline",
                        "--evidence-note",
                        "Collected through CLI",
                    ]
                )
            search_result = GuidelineSearchTool(source_catalog_path=catalog_path).search(
                disease_key="pipeline_guideline",
                disease_name="Pipeline 指南病种",
            )
            skill = SkillBuilderTool(
                guideline_search_tool=GuidelineSearchTool(source_catalog_path=catalog_path)
            ).build_guideline_skill_from_search(search_result)

        self.assertEqual(skill["clinical_features"]["common_symptoms"], ["髋关节疼痛"])
        self.assertEqual(skill["vision_agent_tasks"]["segmentation_targets"], ["lesion_region"])
        self.assertEqual(skill["quality_control"]["citation_status"], "verified")
        self.assertEqual(
            skill["guideline_extraction"]["citations"][0]["source_kind"],
            "clinical_guideline",
        )

    def test_collect_pdf_guideline_uses_injected_text_extractor(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pdf_path = tmp / "guideline.pdf"
            raw_path = tmp / "pdf_raw.txt"
            pdf_path.write_bytes(b"%PDF-1.4 fake test bytes")

            result = GuidelineSourceCollectorTool(
                pdf_text_extractor=lambda path: "## clinical_features\ncommon_symptoms: 头痛"
            ).collect_to_raw_file(
                source=str(pdf_path),
                raw_output_path=raw_path,
                metadata={
                    "disease_key": "pdf_guideline",
                    "disease_name": "PDF 指南病种",
                    "source_type": "medical_guideline",
                    "evidence_level": "high",
                    "title": "PDF guideline",
                    "publisher": "PDF Society",
                    "source_id": "pdf_guideline_source",
                },
            )

            raw_text = raw_path.read_text(encoding="utf-8")

        self.assertEqual(result["content_type"], "application/pdf")
        self.assertIn("## clinical_features", raw_text)
        self.assertIn("common_symptoms: 头痛", raw_text)


if __name__ == "__main__":
    unittest.main()
