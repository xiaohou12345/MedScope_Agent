from __future__ import annotations

import re
from typing import Any


class GuidelineExtractionTool:
    """Extracts structured skill fields from guideline document sections."""

    def extract(
        self,
        disease_key: str,
        disease_name: str,
        documents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "clinical_features": {
                "common_symptoms": [],
                "risk_factors": [],
            },
            "required_image_views": [],
            "visual_targets": {
                "anatomy": [],
                "lesion_features": [],
            },
            "vision_agent_tasks": {
                "segmentation_targets": [],
                "quantitative_features": [],
            },
            "report_requirements": {
                "include": [],
            },
        }
        extracted_fields: set[str] = set()
        citations: list[dict[str, Any]] = []

        for document in documents:
            for section in document.get("sections", []):
                heading = self._normalize_heading(str(section.get("heading", "")))
                text = str(section.get("text", ""))
                self._collect_citations(citations, section.get("citations", []))
                if heading == "clinical_features":
                    self._merge_mapping_lists(payload["clinical_features"], self._parse_keyed_lists(text))
                    extracted_fields.add("clinical_features")
                elif heading == "required_image_views":
                    payload["required_image_views"] = self._merge_list(
                        payload["required_image_views"],
                        self._split_values(text),
                    )
                    extracted_fields.add("required_image_views")
                elif heading == "visual_targets":
                    self._merge_mapping_lists(payload["visual_targets"], self._parse_keyed_lists(text))
                    extracted_fields.add("visual_targets")
                elif heading == "staging_rules":
                    payload["staging_rules"] = self._merge_dict(
                        payload.get("staging_rules", {}),
                        self._parse_rule_block(text),
                    )
                    extracted_fields.add("staging_rules")
                elif heading == "vision_agent_tasks":
                    self._merge_mapping_lists(payload["vision_agent_tasks"], self._parse_keyed_lists(text))
                    extracted_fields.add("vision_agent_tasks")
                elif heading == "visual_protocol":
                    payload["visual_protocol"] = self._merge_dict(
                        payload.get("visual_protocol", {}),
                        self._parse_visual_protocol(text),
                    )
                    extracted_fields.add("visual_protocol")
                elif heading == "report_requirements":
                    parsed_requirements = self._parse_report_requirements(text)
                    payload["report_requirements"] = self._merge_dict(
                        payload.get("report_requirements", {}),
                        parsed_requirements,
                    )
                    extracted_fields.add("report_requirements")

        payload["guideline_extraction"] = {
            "tool": self.__class__.__name__,
            "disease_key": disease_key,
            "disease_name": disease_name,
            "source_document_count": len(documents),
            "extracted_fields": sorted(extracted_fields),
            "citations": citations,
        }
        return payload

    def _normalize_heading(self, heading: str) -> str:
        return heading.strip().lower().replace(" ", "_").replace("-", "_")

    def _parse_keyed_lists(self, text: str) -> dict[str, list[str]]:
        values: dict[str, list[str]] = {}
        for line in self._lines(text):
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            normalized_key = key.strip()
            values[normalized_key] = self._merge_list(
                values.get(normalized_key, []),
                self._split_values(raw_value),
            )
        return values

    def _parse_rule_block(self, text: str) -> dict[str, dict[str, Any]]:
        rules: dict[str, dict[str, Any]] = {}
        for line in self._lines(text):
            if ":" not in line:
                continue
            name, raw_value = line.split(":", 1)
            rule: dict[str, Any] = {}
            parts = [part.strip() for part in raw_value.split("|") if part.strip()]
            if parts:
                rule["description"] = parts[0]
            for part in parts[1:]:
                if "=" not in part:
                    continue
                key, value = part.split("=", 1)
                rule[key.strip()] = self._split_values(value)
            rules[name.strip()] = rule
        return rules

    def _parse_visual_protocol(self, text: str) -> dict[str, Any]:
        protocol: dict[str, Any] = {}
        required_modalities: dict[str, list[str]] = {}
        for line in self._lines(text):
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            key = key.strip()
            if key.startswith("required_modalities."):
                target = key.split(".", 1)[1]
                required_modalities[target] = self._split_values(raw_value)
            elif key == "disease_target":
                values = self._split_values(raw_value)
                protocol[key] = values[0] if values else ""
            else:
                protocol[key] = self._split_values(raw_value)
        if required_modalities:
            protocol["required_modalities"] = required_modalities
        return protocol

    def _parse_report_requirements(self, text: str) -> dict[str, Any]:
        parsed = self._parse_keyed_lists(text)
        if parsed:
            return parsed
        return {"include": self._split_values(text)}

    def _lines(self, text: str) -> list[str]:
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _split_values(self, text: str) -> list[str]:
        normalized = re.sub(r"[；;]", "\n", text)
        values = [value.strip() for value in normalized.splitlines()]
        return [value for value in values if value]

    def _merge_mapping_lists(self, target: dict[str, list[str]], updates: dict[str, list[str]]) -> None:
        for key, values in updates.items():
            target[key] = self._merge_list(target.get(key, []), values)

    def _merge_list(self, current: list[str], values: list[str]) -> list[str]:
        merged = list(current)
        for value in values:
            if value not in merged:
                merged.append(value)
        return merged

    def _merge_dict(self, current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        merged = dict(current)
        for key, value in updates.items():
            if (
                key in merged
                and isinstance(merged[key], dict)
                and isinstance(value, dict)
            ):
                merged[key] = self._merge_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _collect_citations(
        self,
        target: list[dict[str, Any]],
        citations: Any,
    ) -> None:
        if not isinstance(citations, list):
            return
        seen = {
            (
                citation.get("source_id"),
                citation.get("url"),
                citation.get("evidence_note"),
            )
            for citation in target
        }
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            key = (
                citation.get("source_id"),
                citation.get("url"),
                citation.get("evidence_note"),
            )
            if key in seen:
                continue
            target.append(dict(citation))
            seen.add(key)
