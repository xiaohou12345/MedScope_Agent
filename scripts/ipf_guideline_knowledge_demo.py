from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.guideline_search_tool import GuidelineSearchTool
from tools.guideline_source_collector_tool import GuidelineSourceCollectorTool
from tools.guideline_source_import_tool import GuidelineSourceImportTool
from tools.knowledge_builder_tool import KnowledgeBuilderTool


DEFAULT_OUTPUT_DIR = Path("output/fake/ipf_guideline_knowledge_demo")
DISEASE_KEY = "idiopathic_pulmonary_fibrosis_hrct"
DISEASE_NAME = "特发性肺纤维化 HRCT 评估"


IPF_SOURCE_SPECS: list[dict[str, str]] = [
    {
        "source": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9851481/",
        "disease_key": DISEASE_KEY,
        "disease_name": DISEASE_NAME,
        "source_type": "medical_guideline",
        "evidence_level": "high",
        "title": "Idiopathic Pulmonary Fibrosis (an Update) and Progressive Pulmonary Fibrosis in Adults",
        "publisher": "ATS/ERS/JRS/ALAT",
        "source_id": "ats_ers_jrs_alat_ipf_2022",
        "source_kind": "official_guideline",
        "evidence_note": "2022 ATS/ERS/JRS/ALAT IPF update; probable UIP may support IPF diagnosis after multidisciplinary discussion in an appropriate clinical setting.",
        "publication_year": "2022",
        "region": "international",
        "source_priority": "10",
    },
    {
        "source": "https://pubmed.ncbi.nlm.nih.gov/30168753/",
        "disease_key": DISEASE_KEY,
        "disease_name": DISEASE_NAME,
        "source_type": "medical_guideline",
        "evidence_level": "high",
        "title": "Diagnosis of Idiopathic Pulmonary Fibrosis",
        "publisher": "ATS/ERS/JRS/ALAT",
        "source_id": "ats_ers_jrs_alat_ipf_diagnosis_2018",
        "source_kind": "official_guideline",
        "evidence_note": "2018 ATS/ERS/JRS/ALAT diagnostic guideline defining HRCT patterns: UIP, probable UIP, indeterminate, and alternative diagnosis.",
        "publication_year": "2018",
        "region": "international",
        "source_priority": "9",
    },
]


def canonical_ipf_raw_text(metadata: dict[str, str]) -> str:
    """Structured draft extracted from official IPF guideline concepts."""

    lines = [
        f"disease_key: {metadata['disease_key']}",
        f"disease_name: {metadata['disease_name']}",
        f"source_type: {metadata['source_type']}",
        f"evidence_level: {metadata['evidence_level']}",
        f"title: {metadata['title']}",
        f"publisher: {metadata['publisher']}",
        f"source_id: {metadata['source_id']}",
        f"url: {metadata['source']}",
        f"source_kind: {metadata['source_kind']}",
        f"evidence_note: {metadata['evidence_note']}",
        f"publication_year: {metadata['publication_year']}",
        f"region: {metadata['region']}",
        f"source_priority: {metadata['source_priority']}",
        "",
        "## clinical_features",
        "common_symptoms: progressive dyspnea; chronic dry cough; exertional breathlessness",
        "risk_factors: older age; smoking history; male sex; family history of pulmonary fibrosis",
        "",
        "## required_image_views",
        "HRCT chest; thin-section chest CT",
        "",
        "## visual_targets",
        "anatomy: bilateral lungs; subpleural lung zones; basal lung zones",
        "lesion_features: honeycombing; reticulation; traction bronchiectasis; ground-glass opacity; basal subpleural predominance",
        "",
        "## staging_rules",
        "UIP_pattern: HRCT pattern with subpleural and basal predominance plus honeycombing, with or without peripheral traction bronchiectasis | required_visual_evidence=honeycombing_candidate; basal_subpleural_distribution",
        "probable_UIP_pattern: HRCT pattern with subpleural and basal predominance plus reticular abnormality and traction bronchiectasis or bronchiolectasis, without honeycombing | required_visual_evidence=reticulation_candidate; traction_bronchiectasis_candidate; basal_subpleural_distribution",
        "indeterminate_for_UIP: fibrotic HRCT features that do not meet UIP or probable UIP pattern and do not suggest an alternative diagnosis | required_visual_evidence=fibrosis_candidate",
        "alternative_diagnosis_pattern: HRCT findings suggesting another interstitial lung disease pattern or non-IPF diagnosis | required_visual_evidence=alternative_pattern_candidate",
        "",
        "## vision_agent_tasks",
        "segmentation_targets: honeycombing_candidate; reticulation_candidate; traction_bronchiectasis_candidate; fibrosis_candidate",
        "quantitative_features: fibrosis_area_ratio; basal_subpleural_score; lower_lung_zone_ratio; honeycombing_area_ratio; reticulation_area_ratio",
        "",
        "## visual_protocol",
        "disease_target: idiopathic_pulmonary_fibrosis_hrct",
        "clinical_focus: HRCT pattern evidence for IPF/UIP assessment",
        "imaging_modalities: HRCT chest; thin-section chest CT",
        "segmentation_targets: honeycombing_candidate; reticulation_candidate; traction_bronchiectasis_candidate; fibrosis_candidate",
        "required_modalities.honeycombing_candidate: HRCT chest; thin-section chest CT",
        "required_modalities.reticulation_candidate: HRCT chest; thin-section chest CT",
        "required_modalities.traction_bronchiectasis_candidate: HRCT chest; thin-section chest CT",
        "required_modalities.fibrosis_candidate: HRCT chest; thin-section chest CT",
        "measurements: fibrosis_area_ratio; basal_subpleural_score; lower_lung_zone_ratio; honeycombing_area_ratio; reticulation_area_ratio",
        "",
        "## report_requirements",
        "include: HRCT pattern category; supporting visual evidence; missing clinical evidence; need for pulmonary function testing; need for ILD multidisciplinary discussion",
        "safety_constraints: do not diagnose IPF from image evidence alone; do not treat missing HRCT findings as negative; request HRCT if only chest X-ray is available",
        "",
    ]
    return "\n".join(lines)


def run_ipf_guideline_knowledge_demo(
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    collect_sources: bool = False,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    output = Path(output_dir)
    raw_dir = output / "raw"
    collected_dir = output / "collected_sources"
    catalog_path = output / "guideline_sources.json"
    knowledge_output_path = output / f"{DISEASE_KEY}.yaml"
    raw_dir.mkdir(parents=True, exist_ok=True)

    collection_results: list[dict[str, Any]] = []
    if collect_sources:
        collector = GuidelineSourceCollectorTool(timeout_seconds=timeout_seconds)
        collected_dir.mkdir(parents=True, exist_ok=True)
        for spec in IPF_SOURCE_SPECS:
            collection_results.append(
                collector.collect_to_raw_file(
                    source=spec["source"],
                    raw_output_path=collected_dir / f"{spec['source_id']}_collected_raw.txt",
                    metadata=spec,
                    semantic_map=False,
                )
            )

    importer = GuidelineSourceImportTool()
    raw_paths: list[str] = []
    for spec in IPF_SOURCE_SPECS:
        raw_path = raw_dir / f"{spec['source_id']}_structured_raw.txt"
        raw_path.write_text(canonical_ipf_raw_text(spec), encoding="utf-8")
        importer.import_file(raw_path=raw_path, catalog_path=catalog_path)
        raw_paths.append(str(raw_path))

    search_tool = GuidelineSearchTool(source_catalog_path=catalog_path)
    knowledge = KnowledgeBuilderTool(
        knowledges_dir=output / "_no_existing_knowledges",
        guideline_search_tool=search_tool,
    ).prepare_knowledge(
        disease_key=DISEASE_KEY,
        disease_name=DISEASE_NAME,
        observations=[],
    )
    knowledge_output_path.write_text(
        json.dumps(knowledge, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "disease_key": DISEASE_KEY,
        "disease_name": DISEASE_NAME,
        "raw_paths": raw_paths,
        "catalog_path": str(catalog_path),
        "knowledge_output_path": str(knowledge_output_path),
        "source_count": len(IPF_SOURCE_SPECS),
        "collected_source_count": len(collection_results),
        "collection_results": collection_results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an IPF HRCT guideline knowledge draft from official source definitions."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory under output/fake by default.",
    )
    parser.add_argument(
        "--collect-sources",
        action="store_true",
        help="Also fetch real web/PDF source pages into collected_sources before building the structured draft.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_ipf_guideline_knowledge_demo(
        output_dir=Path(args.output_dir),
        collect_sources=args.collect_sources,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
