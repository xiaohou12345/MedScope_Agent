from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.guideline_search_tool import GuidelineSearchTool
from tools.guideline_source_collector_tool import GuidelineSourceCollectorTool
from tools.guideline_source_import_tool import GuidelineSourceImportTool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect a guideline web/PDF source into raw text and optionally import it."
    )
    parser.add_argument("--source", required=True, help="HTTP(S), file URL, or local source path.")
    parser.add_argument(
        "--raw-output-path",
        default=None,
        help="Output raw guideline text path. Defaults to output/fake/guideline_collector/<source_id>_raw_guideline.txt.",
    )
    parser.add_argument(
        "--catalog-path",
        default=str(GuidelineSearchTool.DEFAULT_SOURCE_CATALOG_PATH),
        help="Guideline source catalog JSON path.",
    )
    parser.add_argument(
        "--import-to-catalog",
        action="store_true",
        help="Import the collected raw guideline text into the catalog.",
    )
    parser.add_argument(
        "--semantic-map",
        action="store_true",
        help="Map real-world headings to canonical raw guideline sections before import.",
    )
    parser.add_argument("--disease-key", required=True)
    parser.add_argument("--disease-name", required=True)
    parser.add_argument("--source-type", default="medical_guideline")
    parser.add_argument("--evidence-level", default="high")
    parser.add_argument("--title", required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-kind", default=None)
    parser.add_argument("--evidence-note", default=None)
    parser.add_argument("--publication-year", default=None)
    parser.add_argument("--region", default=None)
    parser.add_argument("--source-priority", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw_output_path = Path(args.raw_output_path) if args.raw_output_path else _default_raw_path(args.source_id)
    metadata = {
        "disease_key": args.disease_key,
        "disease_name": args.disease_name,
        "source_type": args.source_type,
        "evidence_level": args.evidence_level,
        "title": args.title,
        "publisher": args.publisher,
        "source_id": args.source_id,
    }
    if args.source_kind:
        metadata["source_kind"] = args.source_kind
    if args.evidence_note:
        metadata["evidence_note"] = args.evidence_note
    if args.publication_year:
        metadata["publication_year"] = args.publication_year
    if args.region:
        metadata["region"] = args.region
    if args.source_priority:
        metadata["source_priority"] = args.source_priority

    result = GuidelineSourceCollectorTool(
        timeout_seconds=args.timeout_seconds,
    ).collect_to_raw_file(
        source=args.source,
        raw_output_path=raw_output_path,
        metadata=metadata,
        semantic_map=args.semantic_map,
    )
    if args.import_to_catalog:
        import_result = GuidelineSourceImportTool().import_file(
            raw_path=raw_output_path,
            catalog_path=Path(args.catalog_path),
        )
        catalog_entry = import_result["catalog_entry"]
        result["import_result"] = {
            "disease_key": import_result["disease_key"],
            "source_count": len(catalog_entry.get("sources", [])),
            "document_count": len(catalog_entry.get("guideline_documents", [])),
            "section_count": sum(
                len(document.get("sections", []))
                for document in catalog_entry.get("guideline_documents", [])
            ),
        }
        result["catalog_path"] = args.catalog_path
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _default_raw_path(source_id: str) -> Path:
    safe_source_id = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in source_id
    )
    return Path("output/fake/guideline_collector") / f"{safe_source_id}_raw_guideline.txt"


if __name__ == "__main__":
    raise SystemExit(main())
