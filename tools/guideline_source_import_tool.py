from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class GuidelineSourceImportTool:
    """Converts raw guideline text files into guideline source catalog entries."""

    REQUIRED_METADATA = {
        "disease_key",
        "disease_name",
        "source_type",
        "evidence_level",
        "title",
        "publisher",
        "source_id",
    }

    def import_file(self, raw_path: Path | str, catalog_path: Path | str) -> dict[str, Any]:
        raw_file = Path(raw_path)
        entry = self.import_text(raw_file.read_text(encoding="utf-8"))
        catalog_file = Path(catalog_path)
        catalog = self._load_catalog(catalog_file)
        disease_key = entry["disease_key"]
        catalog[disease_key] = self._merge_catalog_entry(
            catalog.get(disease_key),
            entry["catalog_entry"],
        )
        catalog_file.parent.mkdir(parents=True, exist_ok=True)
        catalog_file.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return entry

    def import_text(self, raw_text: str) -> dict[str, Any]:
        metadata_lines, section_blocks = self._split_metadata_and_sections(raw_text)
        metadata = self._parse_metadata(metadata_lines)
        missing = sorted(self.REQUIRED_METADATA - set(metadata))
        if missing:
            raise ValueError(f"Missing guideline metadata: {', '.join(missing)}")
        sections = self._parse_sections(section_blocks)
        if not sections:
            raise ValueError("Guideline raw text must contain at least one '## section' block")

        source = {
            "title": metadata["title"],
            "publisher": metadata["publisher"],
            "source_id": metadata["source_id"],
        }
        for field in (
            "url",
            "source_kind",
            "evidence_note",
            "publication_year",
            "region",
            "source_priority",
        ):
            if metadata.get(field):
                source[field] = metadata[field]
        document = {
            "title": metadata["title"],
            "source_id": metadata["source_id"],
            "sections": self._attach_citations(
                sections=sections,
                source=source,
            ),
        }
        return {
            "disease_key": metadata["disease_key"],
            "catalog_entry": {
                "disease_name": metadata["disease_name"],
                "source_type": metadata["source_type"],
                "evidence_level": metadata["evidence_level"],
                "sources": [source],
                "guideline_documents": [document],
            },
        }

    def _split_metadata_and_sections(self, raw_text: str) -> tuple[list[str], str]:
        metadata_lines: list[str] = []
        section_lines: list[str] = []
        in_sections = False
        for line in raw_text.splitlines():
            if line.strip().startswith("## "):
                in_sections = True
            if in_sections:
                section_lines.append(line)
            else:
                metadata_lines.append(line)
        return metadata_lines, "\n".join(section_lines)

    def _parse_metadata(self, lines: list[str]) -> dict[str, str]:
        metadata: dict[str, str] = {}
        for line in lines:
            stripped = line.strip()
            if not stripped or ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            metadata[key.strip()] = value.strip()
        return metadata

    def _parse_sections(self, raw_sections: str) -> list[dict[str, str]]:
        sections: list[dict[str, str]] = []
        current_heading: str | None = None
        current_lines: list[str] = []
        for line in raw_sections.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                self._append_section(sections, current_heading, current_lines)
                current_heading = stripped[3:].strip()
                current_lines = []
            else:
                current_lines.append(line)
        self._append_section(sections, current_heading, current_lines)
        return sections

    def _append_section(
        self,
        sections: list[dict[str, str]],
        heading: str | None,
        lines: list[str],
    ) -> None:
        if not heading:
            return
        text = "\n".join(line.strip() for line in lines).strip()
        if text:
            sections.append({"heading": heading, "text": text})

    def _attach_citations(
        self,
        sections: list[dict[str, str]],
        source: dict[str, str],
    ) -> list[dict[str, Any]]:
        citation = {
            key: source[key]
            for key in (
                "title",
                "publisher",
                "source_id",
                "url",
                "source_kind",
                "evidence_note",
                "publication_year",
                "region",
                "source_priority",
            )
            if source.get(key)
        }
        return [
            {
                **section,
                "citations": [citation],
            }
            for section in sections
        ]

    def _load_catalog(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _merge_catalog_entry(
        self,
        existing: dict[str, Any] | None,
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        if not existing:
            return incoming
        merged = dict(existing)
        merged["disease_name"] = incoming["disease_name"]
        merged["source_type"] = incoming["source_type"]
        merged["evidence_level"] = incoming["evidence_level"]
        merged["sources"] = self._merge_by_source_id(
            list(existing.get("sources", [])),
            list(incoming.get("sources", [])),
        )
        merged["guideline_documents"] = self._merge_by_source_id(
            list(existing.get("guideline_documents", [])),
            list(incoming.get("guideline_documents", [])),
        )
        return merged

    def _merge_by_source_id(
        self,
        existing_items: list[dict[str, Any]],
        incoming_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged = list(existing_items)
        positions = {
            item.get("source_id"): index
            for index, item in enumerate(merged)
            if item.get("source_id")
        }
        for item in incoming_items:
            source_id = item.get("source_id")
            if source_id in positions:
                merged[positions[source_id]] = item
            else:
                positions[source_id] = len(merged)
                merged.append(item)
        return merged
