from __future__ import annotations

from typing import Any


class ReportAgent:
    """Formats diagnosis output into a structured medical report."""

    def build_report(
        self,
        case_id: str,
        diagnostic_tendency: str,
        staging: str,
        visual_evidence: dict[str, Any],
        uncertainty: list[str],
        follow_up: list[str],
        treatment_advice: list[str],
    ) -> dict[str, Any]:
        return {
            "case_id": case_id,
            "诊断倾向": diagnostic_tendency,
            "diagnostic_tendency": diagnostic_tendency,
            "影像依据": visual_evidence.get("suspected_visual_findings", []),
            "分期判断": staging,
            "不确定性说明": uncertainty,
            "建议进一步检查": follow_up,
            "治疗建议": treatment_advice,
        }
