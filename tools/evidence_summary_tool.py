from __future__ import annotations


class EvidenceSummaryTool:
    """Creates low-evidence summaries when no formal guideline is available."""

    DEFAULT_WARNING = "该规则来自数据总结，不等同于正式医学指南，只能作为辅助提示"

    def summarize_observations(
        self,
        disease_name: str,
        observations: list[str],
        source: str = "internal dataset statistical summary",
    ) -> dict[str, object]:
        return {
            "mode": "evidence_summary_mode",
            "disease_key": disease_name.lower().replace(" ", "_"),
            "disease_name": disease_name,
            "source": source,
            "source_type": "internal_dataset_summary",
            "evidence_level": "low",
            "warning": self.DEFAULT_WARNING,
            "observations": list(observations),
        }
