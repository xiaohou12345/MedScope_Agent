from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.guideline_search_tool import GuidelineSearchTool
from tools.guideline_source_import_tool import GuidelineSourceImportTool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import raw guideline text into a source catalog.")
    parser.add_argument("--raw-path", required=True, help="Path to a raw guideline text file.")
    parser.add_argument(
        "--catalog-path",
        default=str(GuidelineSearchTool.DEFAULT_SOURCE_CATALOG_PATH),
        help="Path to guideline source catalog JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    entry = GuidelineSourceImportTool().import_file(
        raw_path=Path(args.raw_path),
        catalog_path=Path(args.catalog_path),
    )
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
