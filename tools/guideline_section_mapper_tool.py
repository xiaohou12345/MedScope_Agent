from __future__ import annotations

import re
from typing import Any


class GuidelineSectionMapperTool:
    """Maps real-world guideline headings into canonical raw guideline sections."""

    MAX_STRUCTURED_NOTE_CHARS = 1200

    IMAGING_TERMS = [
        "plain radiography",
        "x-ray",
        "xray",
        "ct",
        "mri t1ce",
        "mri t1",
        "mri t2",
        "mri flair",
        "mri",
        "spect",
        "pet",
        "ultrasound",
    ]

    SYMPTOM_TERMS = [
        "hip pain",
        "buttock pain",
        "groin pain",
        "knee pain",
        "limited hip internal rotation",
        "restricted range of motion",
        "headache",
        "seizures",
        "seizure",
        "focal neurologic deficits",
        "neurologic deficits",
        "cognitive change",
    ]

    def map_text(self, sectioned_text: str) -> str:
        sections = self._parse_sections(sectioned_text)
        canonical: dict[str, list[str]] = {}
        for section in sections:
            heading = section["heading"]
            text = section["text"]
            if self._is_noise_section(heading, text):
                continue
            for canonical_heading in self._canonical_headings(heading, text):
                formatted = self._format_section(canonical_heading, heading, text)
                if not formatted:
                    continue
                canonical.setdefault(canonical_heading, []).append(formatted)
        if not canonical:
            return sectioned_text.strip()
        return "\n\n".join(
            f"## {heading}\n" + "\n".join(values).strip()
            for heading, values in canonical.items()
        )

    def _parse_sections(self, text: str) -> list[dict[str, str]]:
        sections: list[dict[str, str]] = []
        current_heading: str | None = None
        current_lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                self._append_section(sections, current_heading, current_lines)
                current_heading = stripped.removeprefix("## ").strip()
                current_lines = []
            else:
                current_lines.append(stripped)
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
        text = "\n".join(line for line in lines if line).strip()
        if text:
            sections.append({"heading": heading, "text": text})

    def _canonical_headings(self, heading: str, text: str) -> list[str]:
        normalized = self._normalize(heading)
        combined = self._normalize(f"{heading} {text}")
        if normalized in {
            "clinical_features",
            "required_image_views",
            "visual_targets",
            "staging_rules",
            "vision_agent_tasks",
            "visual_protocol",
            "report_requirements",
        }:
            return [normalized]
        headings: list[str] = []
        if self._extract_symptoms(text):
            headings.append("clinical_features")
        if self._extract_image_views(text) and any(
            term in combined for term in ["imaging", "radiolog", "diagnos", "examination", "mri", "ct", "x-ray"]
        ):
            headings.append("required_image_views")
        if any(term in normalized for term in ["stage", "staging", "classification", "arco", "who"]):
            headings.append("staging_rules")
        if any(term in normalized for term in ["treatment", "management", "recommendation", "follow up", "prevention"]):
            headings.append("report_requirements")
        return headings

    def _format_section(self, canonical_heading: str, original_heading: str, text: str) -> str:
        if canonical_heading == "clinical_features":
            symptoms = self._extract_symptoms(text)
            if symptoms:
                return f"common_symptoms: {'; '.join(symptoms)}"
            if ":" in text:
                return text
            return ""
        if canonical_heading == "required_image_views":
            image_views = self._extract_image_views(text)
            if image_views:
                return "; ".join(image_views)
            return text
        if canonical_heading == "staging_rules":
            rule_key = self._normalize_rule_key(original_heading)
            return f"{rule_key}: {self._truncate(self._compact(text))}"
        if canonical_heading == "report_requirements":
            return f"treatment_context: {self._truncate(self._compact(text))}"
        return text

    def _is_noise_section(self, heading: str, text: str) -> bool:
        normalized_heading = self._normalize(heading)
        if any(
            marker in normalized_heading
            for marker in [
                "author",
                "references",
                "resources",
                "actions",
                "abstract",
                "general introduction",
                "translational potential",
                "cite",
                "permalink",
                "copyright",
                "article notes",
                "affiliation",
                "figure",
            ]
        ):
            return True
        compact_text = self._compact(text)
        if len(compact_text) < 24 and not self._extract_symptoms(text) and not self._extract_image_views(text):
            return True
        return False

    def _extract_symptoms(self, text: str) -> list[str]:
        lower = self._normalize(text)
        symptoms: list[str] = []
        for term in self.SYMPTOM_TERMS:
            if term in lower and term not in symptoms:
                symptoms.append(term)
        if "pain" in lower and "hip" in lower and "hip pain" not in symptoms:
            symptoms.append("hip pain")
        if "pain" in lower and "buttock" in lower and "buttock pain" not in symptoms:
            symptoms.append("buttock pain")
        if "pain" in lower and "groin" in lower and "groin pain" not in symptoms:
            symptoms.append("groin pain")
        return symptoms

    def _extract_image_views(self, text: str) -> list[str]:
        lower = self._normalize(text)
        matched: list[tuple[int, str]] = []
        for term in self.IMAGING_TERMS:
            index = lower.find(term)
            if index == -1:
                continue
            label = self._image_label(term)
            matched.append((index, label))
        views: list[str] = []
        for _, label in sorted(matched, key=lambda item: item[0]):
            if label not in views:
                views.append(label)
        return views

    def _image_label(self, term: str) -> str:
        labels = {
            "ct": "CT",
            "mri": "MRI",
            "mri t1": "MRI T1",
            "mri t1ce": "MRI T1ce",
            "mri t2": "MRI T2",
            "mri flair": "MRI FLAIR",
            "pet": "PET",
            "spect": "SPECT",
            "x-ray": "X-ray",
            "xray": "X-ray",
        }
        return labels.get(term, term.capitalize())

    def _preserve_keyed_or_note(self, fallback_key: str, text: str) -> str:
        if ":" in text:
            return text
        return f"{fallback_key}: {self._compact(text)}"

    def _normalize_rule_key(self, heading: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", heading).strip("_")
        return normalized or "staging_rule"

    def _normalize(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def _compact(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _truncate(self, text: str) -> str:
        if len(text) <= self.MAX_STRUCTURED_NOTE_CHARS:
            return text
        return text[: self.MAX_STRUCTURED_NOTE_CHARS].rstrip() + "..."
