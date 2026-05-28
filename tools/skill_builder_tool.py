from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.evidence_summary_tool import EvidenceSummaryTool
from tools.guideline_extraction_tool import GuidelineExtractionTool
from tools.guideline_search_tool import GuidelineSearchTool
from tools.visual_protocol_builder import VisualProtocolBuilder
from tools.visual_protocol_validator import VisualProtocolValidator


class SkillBuilderTool:
    """Loads guideline skills and creates clearly labeled hypothesis skills."""

    def __init__(
        self,
        skills_dir: Path | str = "skills",
        guideline_search_tool: GuidelineSearchTool | None = None,
        guideline_extraction_tool: GuidelineExtractionTool | None = None,
        evidence_summary_tool: EvidenceSummaryTool | None = None,
        visual_protocol_builder: VisualProtocolBuilder | None = None,
        visual_protocol_validator: VisualProtocolValidator | None = None,
    ) -> None:
        self.skills_dir = Path(skills_dir)
        self.guideline_search_tool = guideline_search_tool or GuidelineSearchTool()
        self.guideline_extraction_tool = guideline_extraction_tool or GuidelineExtractionTool()
        self.evidence_summary_tool = evidence_summary_tool or EvidenceSummaryTool()
        self.visual_protocol_builder = visual_protocol_builder or VisualProtocolBuilder()
        self.visual_protocol_validator = visual_protocol_validator or VisualProtocolValidator()

    def load_guideline_skill(self, disease_key: str) -> dict[str, Any]:
        skill_path = self.skills_dir / f"{disease_key}.yaml"
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill file not found: {skill_path}")
        return json.loads(skill_path.read_text(encoding="utf-8"))

    def prepare_skill(
        self,
        disease_key: str,
        disease_name: str,
        observations: list[str],
        persist: bool = False,
    ) -> dict[str, Any]:
        try:
            return self.load_guideline_skill(disease_key)
        except FileNotFoundError:
            guideline_result = self.guideline_search_tool.search(
                disease_key=disease_key,
                disease_name=disease_name,
            )
            if guideline_result["has_guideline"]:
                skill = self.build_guideline_skill_from_search(guideline_result)
                if persist:
                    self.save_skill(disease_key, skill)
                return skill
            summary = self.evidence_summary_tool.summarize_observations(
                disease_name=disease_name,
                observations=observations,
            )
            summary["disease_key"] = disease_key
            skill = self.build_hypothesis_skill_from_summary(summary)
            if persist:
                self.save_skill(disease_key, skill)
            return skill

    def save_skill(self, disease_key: str, skill: dict[str, Any]) -> Path:
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        skill_path = self.skills_dir / f"{disease_key}.yaml"
        skill_path.write_text(
            json.dumps(skill, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return skill_path

    def build_guideline_skill_from_search(self, guideline_result: dict[str, Any]) -> dict[str, Any]:
        source_documents = list(guideline_result["sources"])
        source = "; ".join(document["title"] for document in source_documents)
        if guideline_result.get("guideline_documents"):
            guideline_payload = self.guideline_extraction_tool.extract(
                disease_key=guideline_result["disease_key"],
                disease_name=guideline_result["disease_name"],
                documents=list(guideline_result["guideline_documents"]),
            )
        else:
            guideline_payload = dict(guideline_result.get("guideline_payload") or {})
        skill = {
            "disease_name": guideline_result["disease_name"],
            "skill_id": f"{guideline_result['disease_key']}_guideline_v0.1",
            "version": "0.1",
            "path_type": "guideline_aware",
            "source_type": guideline_result["source_type"],
            "skill_type": "guideline_based",
            "evidence_level": guideline_result["evidence_level"],
            "source": source,
            "source_documents": source_documents,
            "source_priority": self._build_source_priority(source_documents),
            "guideline_source": {
                "source_catalog_path": guideline_result.get("source_catalog_path"),
            },
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
                "include": ["诊断倾向", "影像依据", "不确定性说明", "建议进一步检查", "治疗建议"],
            },
        }
        for field in (
            "clinical_features",
            "required_image_views",
            "visual_targets",
            "staging_rules",
            "vision_agent_tasks",
            "visual_protocol",
            "evidence_completeness_matrix",
            "report_requirements",
            "guideline_extraction",
        ):
            if field in guideline_payload:
                skill[field] = guideline_payload[field]
        skill["visual_protocol"] = self.visual_protocol_builder.build(skill)
        conflicts = self._detect_guideline_conflicts(
            documents=list(guideline_result.get("guideline_documents") or []),
            sources=source_documents,
        )
        if conflicts:
            skill["guideline_conflicts"] = conflicts
        self._attach_guideline_quality_control(skill)
        return skill

    def _build_source_priority(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        indexed_sources = list(enumerate(sources))

        def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
            index, source = item
            priority = self._coerce_int(source.get("source_priority"), default=0)
            year = self._coerce_int(source.get("publication_year"), default=0)
            return (-priority, -year, index)

        priority_summary: list[dict[str, Any]] = []
        for _, source in sorted(indexed_sources, key=sort_key):
            priority_summary.append(
                {
                    key: source[key]
                    for key in (
                        "source_id",
                        "title",
                        "publisher",
                        "url",
                        "source_kind",
                        "publication_year",
                        "region",
                        "source_priority",
                    )
                    if source.get(key)
                }
            )
        return priority_summary

    def _detect_guideline_conflicts(
        self,
        documents: list[dict[str, Any]],
        sources: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        field_values: dict[str, list[dict[str, Any]]] = {}
        source_by_id = {
            source.get("source_id"): source
            for source in sources
            if source.get("source_id")
        }
        for document in documents:
            source_id = document.get("source_id")
            for section in document.get("sections", []):
                source = source_by_id.get(source_id, {})
                for candidate in self._conflict_candidates_for_section(
                    heading=str(section.get("heading", "")),
                    text=str(section.get("text", "")),
                ):
                    field_values.setdefault(candidate["field"], []).append(
                        {
                            "source_id": source_id,
                            "title": source.get("title") or document.get("title"),
                            "publication_year": source.get("publication_year"),
                            "region": source.get("region"),
                            "source_priority": source.get("source_priority"),
                            "severity": candidate["severity"],
                            "values": candidate["values"],
                        }
                    )

        conflicts: list[dict[str, Any]] = []
        for field, entries in field_values.items():
            by_source = self._merge_conflict_entries_by_source(entries)
            distinct_value_sets = {self._normalized_value_key(entry["values"]) for entry in by_source}
            if len(by_source) < 2 or len(distinct_value_sets) < 2:
                continue
            severity = str(by_source[0].get("severity") or self._severity_for_conflict_field(field))
            conflicts.append(
                {
                    "field": field,
                    "status": "conflict",
                    "severity": severity,
                    "resolution": "merged_union_review_required",
                    "sources": self._sort_conflict_sources(by_source),
                }
            )
        return conflicts

    def _conflict_candidates_for_section(
        self,
        heading: str,
        text: str,
    ) -> list[dict[str, Any]]:
        normalized = heading.strip().lower().replace(" ", "_").replace("-", "_")
        if normalized == "clinical_features":
            parsed = self.guideline_extraction_tool._parse_keyed_lists(text)
            return [
                {
                    "field": f"clinical_features.{key}",
                    "severity": "low",
                    "values": values,
                }
                for key, values in parsed.items()
                if key in {"common_symptoms", "risk_factors"} and values
            ]
        if normalized == "required_image_views":
            values = self.guideline_extraction_tool._split_values(text)
            return [
                {
                    "field": "required_image_views",
                    "severity": "medium",
                    "values": values,
                }
            ] if values else []
        if normalized == "visual_protocol":
            protocol = self.guideline_extraction_tool._parse_visual_protocol(text)
            required_modalities = protocol.get("required_modalities") or {}
            return [
                {
                    "field": f"visual_protocol.required_modalities.{target}",
                    "severity": "medium",
                    "values": values,
                }
                for target, values in required_modalities.items()
                if values
            ]
        if normalized == "staging_rules":
            rules = self.guideline_extraction_tool._parse_rule_block(text)
            return [
                {
                    "field": f"staging_rules.{rule_name}",
                    "severity": "high",
                    "values": self._staging_rule_values(rule),
                }
                for rule_name, rule in rules.items()
                if rule
            ]
        return []

    def _staging_rule_values(self, rule: dict[str, Any]) -> list[str]:
        values: list[str] = []
        if rule.get("description"):
            values.append(str(rule["description"]))
        for key, value in sorted(rule.items()):
            if key == "description":
                continue
            if isinstance(value, list):
                values.extend(str(item) for item in value)
            else:
                values.append(str(value))
        return values

    def _severity_for_conflict_field(self, field: str) -> str:
        if field.startswith("staging_rules."):
            return "high"
        if field.startswith("visual_protocol.") or field == "required_image_views":
            return "medium"
        return "low"

    def _normalized_value_key(self, values: list[str]) -> tuple[str, ...]:
        return tuple(sorted(str(value).strip().lower() for value in values if str(value).strip()))

    def _merge_conflict_entries_by_source(
        self,
        entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for entry in entries:
            source_id = str(entry.get("source_id") or entry.get("title") or "unknown")
            target = merged.setdefault(source_id, {**entry, "values": []})
            target["values"] = self._merge_list(target["values"], entry.get("values", []))
            target["severity"] = entry.get("severity") or target.get("severity")
        return list(merged.values())

    def _sort_conflict_sources(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            sources,
            key=lambda source: (
                -self._coerce_int(source.get("source_priority"), default=0),
                -self._coerce_int(source.get("publication_year"), default=0),
                str(source.get("source_id") or ""),
            ),
        )

    def _merge_list(self, current: list[str], values: list[str]) -> list[str]:
        merged = list(current)
        for value in values:
            if value not in merged:
                merged.append(value)
        return merged

    def _coerce_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _attach_guideline_quality_control(self, skill: dict[str, Any]) -> None:
        if skill.get("skill_type") != "guideline_based":
            return
        extraction = skill.get("guideline_extraction") or {}
        citations = extraction.get("citations") or []
        if not citations:
            raise ValueError("guideline_based skills require guideline_extraction.citations")
        citation_urls = [citation.get("url") for citation in citations if isinstance(citation, dict)]
        missing_url_count = len(citations) - len([url for url in citation_urls if url])
        conflicts = list(skill.get("guideline_conflicts") or [])
        conflict_count = len(conflicts)
        severity_counts = self._conflict_severity_counts(conflicts)
        highest_conflict_severity = self._highest_conflict_severity(conflicts)
        missing_core_sections = self._missing_core_sections(skill)
        visual_protocol_validation = self.visual_protocol_validator.validate_skill(skill)
        visual_protocol_ready = bool(visual_protocol_validation["valid"])
        formal_ready = (
            missing_url_count == 0
            and conflict_count == 0
            and not missing_core_sections
            and visual_protocol_ready
        )
        skill["quality_control"] = {
            "citation_status": "verified" if missing_url_count == 0 else "needs_review",
            "citation_count": len(citations),
            "missing_url_count": missing_url_count,
            "source_priority_status": self._source_priority_status(skill),
            "conflict_status": "needs_review" if conflict_count else "none",
            "conflict_count": conflict_count,
            "conflict_severity_counts": severity_counts,
            "highest_conflict_severity": highest_conflict_severity,
            "missing_core_sections": missing_core_sections,
            "core_section_status": "incomplete" if missing_core_sections else "complete",
            "visual_protocol_status": visual_protocol_validation["status"],
            "visual_protocol_errors": list(visual_protocol_validation["errors"]),
            "visual_protocol_warnings": list(visual_protocol_validation["warnings"]),
            "formal_skill_status": "formal_ready" if formal_ready else "needs_review",
            "can_enter_formal_guideline_skill": formal_ready,
        }

    def _conflict_severity_counts(self, conflicts: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"low": 0, "medium": 0, "high": 0}
        for conflict in conflicts:
            severity = conflict.get("severity")
            if severity in counts:
                counts[severity] += 1
        return counts

    def _highest_conflict_severity(self, conflicts: list[dict[str, Any]]) -> str:
        severity_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        highest = "none"
        for conflict in conflicts:
            severity = str(conflict.get("severity") or "none")
            if severity_rank.get(severity, 0) > severity_rank[highest]:
                highest = severity
        return highest

    def _source_priority_status(self, skill: dict[str, Any]) -> str:
        source_priority = skill.get("source_priority") or []
        if not source_priority:
            return "missing"
        for source in source_priority:
            if not isinstance(source, dict):
                continue
            if source.get("source_priority") or source.get("publication_year") or source.get("region"):
                return "ranked"
        return "implicit_order"

    def _missing_core_sections(self, skill: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        clinical_features = skill.get("clinical_features") or {}
        if not any(clinical_features.get(key) for key in ("common_symptoms", "risk_factors")):
            missing.append("clinical_features")
        if not skill.get("required_image_views"):
            missing.append("required_image_views")
        vision_agent_tasks = skill.get("vision_agent_tasks") or {}
        if not any(
            vision_agent_tasks.get(key)
            for key in ("segmentation_targets", "quantitative_features")
        ):
            missing.append("vision_agent_tasks")
        extraction = skill.get("guideline_extraction") or {}
        if not extraction.get("citations"):
            missing.append("guideline_extraction.citations")
        return missing

    def build_hypothesis_skill_from_summary(self, summary: dict[str, Any]) -> dict[str, Any]:
        skill = self.build_hypothesis_skill(
            disease_key=str(summary.get("disease_key") or "data_mined_hypothesis"),
            disease_name=summary["disease_name"],
            observations=list(summary["observations"]),
            source=summary["source"],
        )
        skill["source_type"] = summary["source_type"]
        skill["evidence_summary_mode"] = summary["mode"]
        return skill

    def build_hypothesis_skill(
        self,
        disease_key: str,
        disease_name: str,
        observations: list[str],
        source: str = "internal dataset statistical summary",
    ) -> dict[str, Any]:
        return {
            "disease_name": disease_name,
            "skill_id": f"{disease_key}_hypothesis_v0.1",
            "version": "0.1",
            "path_type": "privileged_knowledge_discovery",
            "skill_type": "data_mined_hypothesis",
            "evidence_level": "low",
            "source_type": "internal_dataset_summary",
            "source": source,
            "warning": "该规则来自数据总结，不等同于正式医学指南，只能作为辅助提示",
            "candidate_observation_rules": observations,
            "required_modalities": {
                "training_teacher": ["gold_standard_or_high_cost_modality"],
                "deployment": ["low_cost_or_routine_image"],
            },
            "visual_protocol": {
                "observation_rules": observations,
                "output_fields": [
                    "candidate_risk_signal",
                    "confidence",
                    "evidence_limitations",
                ],
            },
            "evidence_completeness_matrix": {
                "gold_standard_confirmation": {
                    "status": "missing_at_deployment",
                    "reason": "Hypothesis skill must be confirmed by gold-standard modality.",
                }
            },
            "safety_gate": {
                "mode_required": "hypothesis_validation",
                "allowed_outputs": [
                    "early_risk_alert",
                    "research_warning",
                    "recommend_gold_standard_confirmation",
                ],
                "forbidden_claims": ["确诊", "正式指南", "指南推荐", "阴性排除"],
            },
            "discovery_metadata": {
                "method": "evidence_summary_placeholder",
                "teacher_signal": "not_configured_yet",
                "sample_size": None,
                "validation_status": "unvalidated_hypothesis",
            },
        }
