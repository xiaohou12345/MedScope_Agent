from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.guideline_search_tool import GuidelineSearchTool
from tools.guideline_source_import_tool import GuidelineSourceImportTool
from tools.knowledge_builder_tool import KnowledgeBuilderTool


DEFAULT_OUTPUT_DIR = Path("output/fake/guideline_import_demo")


def default_raw_guideline_text() -> str:
    return """disease_key: demo_glioma_guideline
disease_name: 演示胶质瘤指南
source_type: medical_guideline
evidence_level: high
title: Demo glioma guideline text
publisher: Demo Society
source_id: demo_glioma_guideline_text
url: https://www.nature.com/articles/s41571-020-00447-z
source_kind: official_guideline
evidence_note: Demo citation modeled after EANO adult diffuse glioma guideline

## clinical_features
common_symptoms: 头痛; 癫痫发作
risk_factors: 既往颅脑放疗史

## required_image_views
MRI T1; MRI T1ce; MRI T2; MRI FLAIR

## vision_agent_tasks
segmentation_targets: whole tumor; tumor core; enhancing tumor
quantitative_features: whole_tumor_volume_ml; tumor_core_volume_ml; enhancing_tumor_volume_ml

## visual_protocol
disease_target: demo_glioma_guideline
segmentation_targets: whole_tumor; tumor_core; enhancing_tumor
required_modalities.whole_tumor: FLAIR
required_modalities.tumor_core: T1; T1ce; T2
required_modalities.enhancing_tumor: T1ce
measurements: whole_tumor_volume_ml; tumor_core_volume_ml; enhancing_tumor_volume_ml
"""


def ensure_default_raw_guideline(raw_path: Path, overwrite: bool = False) -> Path:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not raw_path.exists():
        raw_path.write_text(default_raw_guideline_text(), encoding="utf-8")
    return raw_path


def run_guideline_import_to_knowledge(
    raw_path: Path | str,
    catalog_path: Path | str,
    knowledge_output_path: Path | str,
    disease_key: str,
    disease_name: str,
) -> dict[str, Any]:
    raw_file = Path(raw_path)
    catalog_file = Path(catalog_path)
    knowledge_file = Path(knowledge_output_path)

    import_result = GuidelineSourceImportTool().import_file(
        raw_path=raw_file,
        catalog_path=catalog_file,
    )
    search_tool = GuidelineSearchTool(source_catalog_path=catalog_file)
    knowledge = KnowledgeBuilderTool(
        knowledges_dir=knowledge_file.parent / "_no_existing_knowledges",
        guideline_search_tool=search_tool,
    ).prepare_knowledge(
        disease_key=disease_key,
        disease_name=disease_name,
        observations=[],
    )
    knowledge_file.parent.mkdir(parents=True, exist_ok=True)
    knowledge_file.write_text(
        json.dumps(knowledge, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "raw_path": str(raw_file),
        "catalog_path": str(catalog_file),
        "knowledge_output_path": str(knowledge_file),
        "disease_key": disease_key,
        "knowledge_type": knowledge["knowledge_type"],
        "knowledge_id": knowledge["knowledge_id"],
        "imported_source_id": import_result["catalog_entry"]["sources"][0]["source_id"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run raw guideline text -> source catalog -> guideline knowledge demo."
    )
    parser.add_argument(
        "--raw-path",
        default=str(DEFAULT_OUTPUT_DIR / "raw_guideline.txt"),
        help="Raw guideline text path. If missing, a demo raw guideline is created.",
    )
    parser.add_argument(
        "--catalog-path",
        default=str(DEFAULT_OUTPUT_DIR / "guideline_sources.json"),
        help="Output source catalog JSON path.",
    )
    parser.add_argument(
        "--knowledge-output-path",
        default=str(DEFAULT_OUTPUT_DIR / "demo_glioma_guideline_knowledge.json"),
        help="Output generated guideline knowledge JSON path.",
    )
    parser.add_argument("--disease-key", default="demo_glioma_guideline")
    parser.add_argument("--disease-name", default="演示胶质瘤指南")
    parser.add_argument(
        "--overwrite-raw",
        action="store_true",
        help="Overwrite the demo raw guideline text before importing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw_path = ensure_default_raw_guideline(
        Path(args.raw_path),
        overwrite=args.overwrite_raw,
    )
    result = run_guideline_import_to_knowledge(
        raw_path=raw_path,
        catalog_path=Path(args.catalog_path),
        knowledge_output_path=Path(args.knowledge_output_path),
        disease_key=args.disease_key,
        disease_name=args.disease_name,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
