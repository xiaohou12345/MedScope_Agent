from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


class GuidelineSearchTool:
    """Offline guideline source catalog used before wiring a real search provider."""

    DEFAULT_SOURCE_CATALOG_PATH = Path("data/guidelines/guideline_sources.json")

    def __init__(
        self,
        offline_index: dict[str, dict[str, Any]] | None = None,
        source_catalog_path: Path | str | None = None,
    ) -> None:
        self.source_catalog_path = Path(source_catalog_path or self.DEFAULT_SOURCE_CATALOG_PATH)
        self.offline_index = deepcopy(offline_index) if offline_index is not None else self._load_source_catalog()

    def search(self, disease_key: str, disease_name: str) -> dict[str, Any]:
        record = self.offline_index.get(disease_key)
        if not record:
            return {
                "disease_key": disease_key,
                "disease_name": disease_name,
                "has_guideline": False,
                "source_type": "none",
                "evidence_level": "none",
                "sources": [],
                "source_catalog_path": str(self.source_catalog_path),
            }
        return {
            "disease_key": disease_key,
            "disease_name": record.get("disease_name", disease_name),
            "has_guideline": True,
            "source_type": record["source_type"],
            "evidence_level": record["evidence_level"],
            "sources": deepcopy(record.get("sources", [])),
            "guideline_documents": deepcopy(record.get("guideline_documents", [])),
            "source_catalog_path": str(self.source_catalog_path),
        }

    def _load_source_catalog(self) -> dict[str, dict[str, Any]]:
        if not self.source_catalog_path.exists():
            return {}
        return json.loads(self.source_catalog_path.read_text(encoding="utf-8"))
