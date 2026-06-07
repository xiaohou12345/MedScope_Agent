from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.lesion_gallery_builder import build_lesion_gallery


class MemoryManager:
    """Persists case-level patient, image, skill, and reasoning memory as JSON."""

    SCHEMA_VERSION = "memory_v1"
    MEMORY_TYPES = ["patient_memory", "image_memory", "skill_memory", "reasoning_memory"]
    REQUIRED_TRACE_AGENTS = [
        "GaoDoctorAgent",
        "SkillBuilderAgent",
        "VisionAgent",
        "DiagnosisDoctorAgent",
        "MemoryManager",
    ]
    REQUIRED_REPLAY_EVENTS = [
        "patient_intake",
        "skill_routing",
        "skill_loading",
        "visual_evidence",
        "diagnosis_report",
        "memory_audit",
    ]

    def __init__(self, base_dir: Path | str = "data") -> None:
        self.base_dir = Path(base_dir)
        self.cases_dir = self.base_dir / "cases"
        self.cases_dir.mkdir(parents=True, exist_ok=True)

    def create_case_id(self) -> str:
        return "case_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    def save_case_memory(
        self,
        case_id: str,
        patient_memory: dict[str, Any],
        image_memory: dict[str, Any],
        skill_memory: dict[str, Any],
        reasoning_memory: dict[str, Any],
    ) -> Path:
        now = datetime.now().isoformat(timespec="seconds")
        normalized_patient_memory = self._normalize_patient_memory(
            case_id=case_id,
            patient_memory=patient_memory,
            qa_history=patient_memory.get("qa_history", []),
        )
        record = {
            "schema_version": self.SCHEMA_VERSION,
            "memory_types": list(self.MEMORY_TYPES),
            "case_id": case_id,
            "created_at": patient_memory.get("created_at") or now,
            "updated_at": now,
            "patient_memory": normalized_patient_memory,
            "image_memory": self._normalize_image_memory(case_id, image_memory),
            "skill_memory": self._normalize_skill_memory(skill_memory),
            "reasoning_memory": self._normalize_reasoning_memory(case_id, reasoning_memory),
            "qa_memory": normalized_patient_memory["qa_history"],
        }
        case_path = self.cases_dir / f"{case_id}.json"
        case_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return case_path

    def load_case_memory(self, case_id: str) -> dict[str, Any]:
        case_path = self.cases_dir / f"{case_id}.json"
        return self._normalize_record(json.loads(case_path.read_text(encoding="utf-8")))

    def get_case_by_id(self, case_id: str) -> dict[str, Any]:
        return self.load_case_memory(case_id)

    def find_cases_by_disease(self, disease: str) -> list[dict[str, Any]]:
        records = []
        for case_path in sorted(self.cases_dir.glob("*.json")):
            record = self._normalize_record(json.loads(case_path.read_text(encoding="utf-8")))
            skill_memory = record.get("skill_memory", {})
            disease_candidates = {
                str(skill_memory.get("disease") or ""),
                str(skill_memory.get("disease_name") or ""),
                str(skill_memory.get("skill_id") or ""),
                str(skill_memory.get("selected_skill") or ""),
                str(skill_memory.get("used_skill") or ""),
            }
            if disease in disease_candidates:
                records.append(record)
        return records

    def find_cases_by_patient(self, patient_id: str) -> list[dict[str, Any]]:
        records = []
        for case_path in sorted(self.cases_dir.glob("*.json")):
            record = self._normalize_record(json.loads(case_path.read_text(encoding="utf-8")))
            if str(record.get("patient_memory", {}).get("patient_id") or "") == patient_id:
                records.append(record)
        return records

    def get_latest_case_for_patient(self, patient_id: str) -> dict[str, Any] | None:
        records = self.find_cases_by_patient(patient_id)
        if not records:
            return None
        return max(records, key=self._record_sort_key)

    def list_recent_cases(self, limit: int = 20) -> list[dict[str, Any]]:
        records = [
            self._normalize_record(json.loads(case_path.read_text(encoding="utf-8")))
            for case_path in self.cases_dir.glob("*.json")
        ]
        return sorted(records, key=self._record_sort_key, reverse=True)[:limit]

    def list_case_summaries(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            self._case_summary(record)
            for record in self.list_recent_cases(limit=limit)
        ]

    def get_evidence_bundle(self, case_id: str) -> dict[str, Any]:
        record = self.load_case_memory(case_id)
        image_memory = record["image_memory"]
        skill_memory = record["skill_memory"]
        reasoning_memory = record["reasoning_memory"]
        missing_or_unassessed = self._collect_missing_or_unassessed(record)
        quality_warnings = self._collect_quality_warnings(record, missing_or_unassessed)
        visual_evidence_bundle = image_memory.get("visual_evidence_bundle", {})
        visual_fact_usage = reasoning_memory.get("visual_fact_usage", {})
        lesion_gallery = build_lesion_gallery(
            visual_evidence_bundle=visual_evidence_bundle,
            visual_fact_usage=visual_fact_usage,
        )
        clinical_context_evidence = self._clinical_context_evidence(record)
        differential_reasoning_evidence = self._differential_reasoning_evidence(record)
        quantitative_evidence = self._quantitative_evidence(record)
        integrated_reasoning_evidence = self._integrated_reasoning_evidence(record)
        return {
            "case_id": record["case_id"],
            "patient_context": {
                "patient_id": record["patient_memory"].get("patient_id"),
                "patient_message": record["patient_memory"].get("patient_message"),
                "patient_info": record["patient_memory"].get("patient_info", {}),
                "symptoms": record["patient_memory"].get("symptoms", []),
                "intent": record["patient_memory"].get("intent"),
            },
            "clinical_context_evidence": clinical_context_evidence,
            "differential_reasoning_evidence": differential_reasoning_evidence,
            "quantitative_evidence": quantitative_evidence,
            "integrated_reasoning_evidence": integrated_reasoning_evidence,
            "image_evidence": {
                "image_path": image_memory.get("image_path"),
                "modality": image_memory.get("modality"),
                "body_part": image_memory.get("body_part"),
                "image_outputs": image_memory.get("image_outputs", {}),
                "visual_features": image_memory.get("visual_features", {}),
                "visual_evidence": image_memory.get("visual_evidence", {}),
                "visual_evidence_bundle": visual_evidence_bundle,
                "measurements": image_memory.get("measurements", {}),
                "completeness": image_memory.get("completeness", {}),
                "segmentation_quality": image_memory.get("segmentation_quality"),
            },
            "skill_evidence": {
                "selected_skill": skill_memory.get("selected_skill"),
                "selected_vision_mode": skill_memory.get("selected_vision_mode"),
                "routing_decision": skill_memory.get("routing_decision", {}),
                "alignment_plan": skill_memory.get("alignment_plan", {}),
                "used_skill": skill_memory.get("used_skill"),
                "skill_type": skill_memory.get("skill_type"),
                "guideline_evidence": skill_memory.get("guideline_evidence", {}),
                "source_priority": skill_memory.get("source_priority", []),
                "guideline_conflicts": skill_memory.get("guideline_conflicts", []),
                "quality_control": skill_memory.get("quality_control", {}),
            },
            "reasoning_evidence": {
                "diagnostic_tendency": reasoning_memory.get("diagnostic_tendency"),
                "visual_input_contract": reasoning_memory.get("visual_input_contract", {}),
                "visual_fact_usage": reasoning_memory.get("visual_fact_usage", {}),
                "used_visual_facts": reasoning_memory.get("used_visual_facts", []),
                "excluded_visual_facts": reasoning_memory.get("excluded_visual_facts", []),
                "used_visual_fields": reasoning_memory.get("used_visual_fields", []),
                "missing_visual_fields_acknowledged": reasoning_memory.get(
                    "missing_visual_fields_acknowledged",
                    [],
                ),
                "uncertainty": reasoning_memory.get("uncertainty", []),
                "follow_up": reasoning_memory.get("follow_up", []),
                "treatment_advice": reasoning_memory.get("treatment_advice", []),
                "key_evidence": reasoning_memory.get("key_evidence", []),
            },
            "lesion_gallery": lesion_gallery,
            "missing_or_unassessed": missing_or_unassessed,
            "quality_warnings": quality_warnings,
        }

    def _clinical_context_evidence(self, record: dict[str, Any]) -> dict[str, Any]:
        patient_memory = record.get("patient_memory") or {}
        patient_info = patient_memory.get("patient_info") or {}
        reasoning_report = (record.get("reasoning_memory") or {}).get("report") or {}
        assessment = reasoning_report.get("clinical_context_assessment") or {}
        raw_context = (
            patient_info.get("clinical_context")
            or patient_info.get("history")
            or patient_info.get("risk_factors")
            or ""
        )
        if isinstance(raw_context, list):
            raw_context = "；".join(str(item) for item in raw_context)
        return {
            "evidence_type": "clinical_context",
            "source": patient_info.get("clinical_context_source") or (
                "structured_patient_info" if raw_context else "missing"
            ),
            "raw_context": str(raw_context),
            "provided_risk_factors": list(assessment.get("provided_risk_factors") or []),
            "missing_clinical_context": list(assessment.get("missing_clinical_context") or []),
            "can_confirm_without_imaging": bool(assessment.get("can_confirm_without_imaging", False)),
            "diagnosis_usable": False,
            "diagnosis_usable_level": "risk_modifier_only",
            "role": assessment.get(
                "role",
                "clinical context can modify suspicion only; it cannot replace imaging evidence.",
            ),
        }

    def _differential_reasoning_evidence(self, record: dict[str, Any]) -> dict[str, Any]:
        skill_memory = record.get("skill_memory") or {}
        routing_decision = skill_memory.get("routing_decision") or {}
        reasoning_report = (record.get("reasoning_memory") or {}).get("report") or {}
        considerations = reasoning_report.get("differential_considerations") or []
        if not isinstance(considerations, list):
            considerations = []
        candidates = routing_decision.get("differential_skill_candidates") or []
        if not isinstance(candidates, list):
            candidates = []
        return {
            "evidence_type": "differential_reasoning",
            "source": "diagnosis_report_and_routing_decision",
            "primary_hypothesis": routing_decision.get("primary_hypothesis"),
            "routing_evidence_status": routing_decision.get("routing_evidence_status")
            or routing_decision.get("initial_evidence_status"),
            "differential_skill_candidates": list(candidates),
            "considerations": [dict(item) for item in considerations if isinstance(item, dict)],
            "diagnosis_usable": False,
            "diagnosis_usable_level": "bounded_differential_only",
            "can_replace_primary_diagnosis": False,
            "role": (
                "Differential considerations explain alternative possibilities and nonspecific findings; "
                "they cannot replace evidence-bounded diagnosis without supporting evidence."
            ),
        }

    def _quantitative_evidence(self, record: dict[str, Any]) -> dict[str, Any]:
        reasoning_report = (record.get("reasoning_memory") or {}).get("report") or {}
        summary = reasoning_report.get("quantitative_evidence_summary") or {}
        measurement_items = list(summary.get("measurement_items") or [])
        exploratory_features = list(summary.get("exploratory_features") or [])
        if not measurement_items and not exploratory_features:
            visual_bundle = (
                (record.get("image_memory") or {})
                .get("visual_evidence_bundle")
                or {}
            )
            evidence_items = visual_bundle.get("evidence_items") or visual_bundle.get("findings") or []
            for item in evidence_items:
                if not isinstance(item, dict):
                    continue
                if item.get("evidence_type") == "anatomical_measurement":
                    measurement_items.append(dict(item))
                if (
                    item.get("evidence_type") == "image_feature_quantification"
                    or item.get("diagnosis_usable_level") == "exploratory_only"
                ):
                    exploratory_features.append(dict(item))
        strong_count = int(summary.get("strong_quantitative_support_count") or 0)
        if strong_count == 0:
            strong_count = sum(
                1
                for item in measurement_items
                if item.get("diagnosis_usable") is True
                and (item.get("measurements") or {}).get("measurement_usable") is True
            )
        return {
            "evidence_type": "quantitative_evidence",
            "source": "diagnosis_report_and_visual_evidence_bundle",
            "measurement_items": [
                dict(item) for item in measurement_items if isinstance(item, dict)
            ],
            "exploratory_features": [
                dict(item) for item in exploratory_features if isinstance(item, dict)
            ],
            "strong_quantitative_support_count": strong_count,
            "can_confirm_diagnosis": strong_count > 0,
            "diagnosis_usable_level": (
                "measurement_support" if strong_count > 0 else "not_usable_or_exploratory"
            ),
            "role": (
                "Quantitative evidence is only diagnosis-supporting when measurements are usable and quality-gated; "
                "exploratory image features require validation."
            ),
        }

    def _integrated_reasoning_evidence(self, record: dict[str, Any]) -> dict[str, Any]:
        reasoning_report = (record.get("reasoning_memory") or {}).get("report") or {}
        summary = reasoning_report.get("integrated_reasoning_summary") or {}
        if not isinstance(summary, dict):
            summary = {}
        imaging = summary.get("imaging_support") or {}
        quantitative = summary.get("quantitative_support") or {}
        missing = summary.get("missing_evidence") or {}
        clinical = summary.get("clinical_risk_support") or {}
        return {
            "evidence_type": "integrated_reasoning",
            "source": "diagnosis_report.integrated_reasoning_summary",
            "target_disease": summary.get("target_disease"),
            "evidence_status": summary.get("evidence_status"),
            "can_confirm_target_disease": bool(summary.get("can_confirm_target_disease", False)),
            "supported_targets": list(imaging.get("supported_targets") or []),
            "nonspecific_or_unusable_targets": list(
                imaging.get("nonspecific_or_unusable_targets") or []
            ),
            "missing_required_targets": list(missing.get("missing_required_targets") or []),
            "strong_quantitative_support_count": int(
                quantitative.get("strong_quantitative_support_count") or 0
            ),
            "measurement_targets_not_usable": list(
                quantitative.get("measurement_targets_not_usable") or []
            ),
            "exploratory_targets": list(quantitative.get("exploratory_targets") or []),
            "provided_risk_factors": list(clinical.get("provided_risk_factors") or []),
            "recommended_next_step": list(summary.get("recommended_next_step") or []),
            "diagnosis_usable": False,
            "diagnosis_usable_level": "bounded_summary_only",
            "can_create_new_evidence": False,
            "role": (
                "Integrated reasoning summarizes already bounded evidence; it cannot create new findings "
                "or override missing, low-quality, or exploratory evidence."
            ),
        }

    def append_qa_memory(
        self,
        case_id: str,
        question: str,
        answer: str,
        llm_used: bool = False,
        llm_fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        case_path = self.cases_dir / f"{case_id}.json"
        record = self._normalize_record(json.loads(case_path.read_text(encoding="utf-8")))
        qa_entry = {
            "question": question,
            "answer": answer,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "referenced_case_id": case_id,
            "evidence_bundle_used": True,
            "llm_used": llm_used,
            "llm_fallback_reason": llm_fallback_reason,
        }
        record["patient_memory"].setdefault("qa_history", []).append(qa_entry)
        record["qa_memory"] = record["patient_memory"]["qa_history"]
        record["updated_at"] = qa_entry["created_at"]
        case_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return record

    def build_audit_summary(self, case_id: str) -> dict[str, Any]:
        record = self.load_case_memory(case_id)
        evidence_bundle = self.get_evidence_bundle(case_id)
        alignment_plan = (
            record["skill_memory"].get("alignment_plan")
            or record["reasoning_memory"].get("alignment_plan")
            or {}
        )
        routing_decision = record["skill_memory"].get("routing_decision", {})
        quality_control = record["skill_memory"].get("quality_control") or {}
        qa_history = record["patient_memory"].get("qa_history", [])
        blocked_scopes = list((alignment_plan.get("diagnosis_scope") or {}).get("blocked") or [])
        missing_count = len(evidence_bundle["missing_or_unassessed"].get("image_memory", {}))
        lesion_gallery_summary = self._lesion_gallery_summary(
            evidence_bundle.get("lesion_gallery", {})
        )
        selected_vision_mode = (
            record["skill_memory"].get("selected_vision_mode")
            or routing_decision.get("selected_vision_mode")
        )
        visual_tool_name = self._infer_visual_tool_name(
            image_memory=record["image_memory"],
            selected_vision_mode=selected_vision_mode,
        )
        agents_traced = [
            "GaoDoctorAgent",
            "SkillBuilderAgent",
            "VisionAgent",
            "DiagnosisDoctorAgent",
            "MemoryManager",
        ]
        if qa_history:
            agents_traced.append("GaoDoctorAgent QA")
        agent_io_summary = {
            "GaoDoctorAgent": {
                "input": record["patient_memory"].get("patient_message"),
                "output": record["patient_memory"].get("intent"),
                "routing_decision": routing_decision,
            },
            "SkillBuilderAgent": {
                "input": record["skill_memory"].get("routing_decision", {}),
                "output": record["skill_memory"].get("selected_skill")
                or record["skill_memory"].get("skill_id"),
            },
            "VisionAgent": {
                "input": record["image_memory"].get("image_path"),
                "output": record["image_memory"].get("image_outputs", {}),
                "selected_vision_mode": selected_vision_mode,
                "tool": visual_tool_name,
                "lesion_gallery_summary": lesion_gallery_summary,
            },
            "DiagnosisDoctorAgent": {
                "input": record["reasoning_memory"].get("visual_input_contract", {}),
                "output": record["reasoning_memory"].get("diagnostic_tendency"),
                "visual_fact_usage": record["reasoning_memory"].get(
                    "visual_fact_usage",
                    {},
                ),
            },
            "MemoryManager": {
                "input": {
                    "case_id": case_id,
                    "memory_types": list(record.get("memory_types") or self.MEMORY_TYPES),
                },
                "output": {
                    "audit_status": "available",
                    "evidence_bundle_status": "available",
                    "lesion_gallery_status": (
                        "available" if lesion_gallery_summary["item_count"] else "empty"
                    ),
                    "lesion_gallery_summary": lesion_gallery_summary,
                },
            },
        }
        if qa_history:
            latest_qa = qa_history[-1]
            agent_io_summary["GaoDoctorAgent QA"] = {
                "input": latest_qa.get("question"),
                "output": {
                    "answer": latest_qa.get("answer"),
                    "evidence_bundle_used": latest_qa.get("evidence_bundle_used"),
                    "llm_used": latest_qa.get("llm_used"),
                    "llm_fallback_reason": latest_qa.get("llm_fallback_reason"),
                },
            }
        ordered_agent_io_summary = {
            agent: agent_io_summary[agent]
            for agent in agents_traced
            if agent in agent_io_summary
        }
        clinical_hypotheses = [
            dict(item)
            for item in routing_decision.get("clinical_hypotheses") or []
            if isinstance(item, dict)
        ]
        audit = {
            "case_id": case_id,
            "schema_version": record["schema_version"],
            "agents_traced": agents_traced,
            "trace_consistency": self._build_trace_consistency(
                agents_traced=agents_traced,
                agent_io_summary=ordered_agent_io_summary,
            ),
            "memory_completeness": {
                memory_type: bool(record.get(memory_type))
                for memory_type in self.MEMORY_TYPES
            },
            "memory_type_details": {
                "patient_memory": {
                    "patient_id": record["patient_memory"].get("patient_id"),
                    "intent": record["patient_memory"].get("intent"),
                    "symptom_count": len(record["patient_memory"].get("symptoms") or []),
                    "qa_history_count": len(qa_history),
                },
                "image_memory": {
                    "modality": record["image_memory"].get("modality"),
                    "body_part": record["image_memory"].get("body_part"),
                    "segmentation_quality": record["image_memory"].get("segmentation_quality"),
                    "measurement_count": len(record["image_memory"].get("measurements") or {}),
                    "finding_count": (
                        record["image_memory"]
                        .get("visual_evidence_bundle", {})
                        .get("numeric_evidence", {})
                        .get("finding_count", 0)
                    ),
                    "lesion_gallery_item_count": lesion_gallery_summary["item_count"],
                    "lesion_gallery_used_count": lesion_gallery_summary["used_count"],
                    "lesion_gallery_excluded_count": lesion_gallery_summary["excluded_count"],
                    "missing_or_unassessed_count": missing_count,
                    "has_overlay": bool(
                        (record["image_memory"].get("image_outputs") or {}).get("overlay_path")
                    ),
                },
                "skill_memory": {
                    "selected_skill": record["skill_memory"].get("selected_skill"),
                    "used_skill": record["skill_memory"].get("used_skill"),
                    "skill_type": record["skill_memory"].get("skill_type"),
                    "routing_agent_scope": routing_decision.get("agent_scope"),
                    "routing_source": routing_decision.get("source"),
                    "skill_builder_action": routing_decision.get("skill_builder_action"),
                    "primary_hypothesis": routing_decision.get("primary_hypothesis"),
                    "initial_evidence_status": routing_decision.get("initial_evidence_status"),
                    "routing_evidence_status": routing_decision.get("routing_evidence_status"),
                    "differential_skill_candidates": list(
                        routing_decision.get("differential_skill_candidates") or []
                    ),
                    "clinical_hypotheses": clinical_hypotheses,
                    "clinical_hypotheses_count": len(clinical_hypotheses),
                    "formal_skill_status": quality_control.get("formal_skill_status"),
                    "visual_protocol_status": quality_control.get("visual_protocol_status"),
                },
                "reasoning_memory": {
                    "diagnostic_tendency": record["reasoning_memory"].get("diagnostic_tendency"),
                    "used_visual_field_count": len(record["reasoning_memory"].get("used_visual_fields") or []),
                    "missing_visual_fields_acknowledged": record["reasoning_memory"].get(
                        "missing_visual_fields_acknowledged",
                        [],
                    ),
                    "uncertainty_count": len(record["reasoning_memory"].get("uncertainty") or []),
                    "follow_up_count": len(record["reasoning_memory"].get("follow_up") or []),
                },
            },
            "alignment_summary": {
                "analysis_status": alignment_plan.get("analysis_status"),
                "clinical_focus": alignment_plan.get("clinical_focus"),
                "blocked_scopes": blocked_scopes,
                "required_next_images": list(alignment_plan.get("required_next_images") or []),
                "visual_task_status_counts": self._visual_task_status_counts(
                    alignment_plan.get("visual_tasks") or []
                ),
            },
            "skill_quality": {
                "formal_skill_status": quality_control.get("formal_skill_status"),
                "visual_protocol_status": quality_control.get("visual_protocol_status"),
                "visual_protocol_errors": list(quality_control.get("visual_protocol_errors") or []),
                "visual_protocol_warnings": list(quality_control.get("visual_protocol_warnings") or []),
                "conflict_status": quality_control.get("conflict_status"),
                "citation_status": quality_control.get("citation_status"),
            },
            "qa_safety": {
                "evidence_bundle_required": True,
                "qa_history_count": len(qa_history),
                "evidence_bundle_used_count": len(
                    [entry for entry in qa_history if entry.get("evidence_bundle_used")]
                ),
                "llm_used_count": len([entry for entry in qa_history if entry.get("llm_used")]),
                "fallback_count": len([entry for entry in qa_history if entry.get("llm_fallback_reason")]),
                "blocked_scopes": blocked_scopes,
                "missing_or_unassessed_count": missing_count,
            },
            "agent_io_summary": ordered_agent_io_summary,
            "visual_fact_usage": record["reasoning_memory"].get("visual_fact_usage", {}),
            "lesion_gallery_summary": lesion_gallery_summary,
            "visual_evidence_used": evidence_bundle["image_evidence"],
            "guideline_evidence_used": evidence_bundle["skill_evidence"].get(
                "guideline_evidence",
                {},
            ),
            "missing_or_unassessed": evidence_bundle["missing_or_unassessed"],
            "quality_warnings": evidence_bundle["quality_warnings"],
            "guideline_conflicts": record["skill_memory"].get("guideline_conflicts", []),
            "qa_history_count": len(record["patient_memory"].get("qa_history", [])),
        }
        audit_dir = Path("output/fake/memory_audit")
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / f"{case_id}_audit.json"
        audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return audit

    def _build_trace_consistency(
        self,
        agents_traced: list[str],
        agent_io_summary: dict[str, Any],
    ) -> dict[str, Any]:
        agent_io_keys = list(agent_io_summary.keys())
        missing_required_agents = [
            agent for agent in self.REQUIRED_TRACE_AGENTS if agent not in agents_traced
        ]
        return {
            "agent_io_matches_trace": agent_io_keys == agents_traced,
            "required_agents_present": not missing_required_agents,
            "missing_required_agents": missing_required_agents,
            "qa_extension_present": "GaoDoctorAgent QA" in agents_traced,
            "agent_count": len(agents_traced),
            "agent_io_count": len(agent_io_keys),
        }

    def build_case_replay(self, case_id: str) -> dict[str, Any]:
        record = self.load_case_memory(case_id)
        evidence_bundle = self.get_evidence_bundle(case_id)
        audit = self.build_audit_summary(case_id)
        lesion_gallery_summary = self._lesion_gallery_summary(
            evidence_bundle.get("lesion_gallery", {})
        )
        patient_memory = record["patient_memory"]
        image_memory = record["image_memory"]
        skill_memory = record["skill_memory"]
        reasoning_memory = record["reasoning_memory"]
        routing_decision = skill_memory.get("routing_decision", {})
        alignment_plan = (
            skill_memory.get("alignment_plan")
            or reasoning_memory.get("alignment_plan")
            or {}
        )
        selected_vision_mode = (
            skill_memory.get("selected_vision_mode")
            or routing_decision.get("selected_vision_mode")
        )
        visual_tool_name = self._infer_visual_tool_name(
            image_memory=image_memory,
            selected_vision_mode=selected_vision_mode,
        )
        steps = [
            {
                "agent": "GaoDoctorAgent",
                "event": "patient_intake",
                "memory_scope": "patient_memory",
                "intent": patient_memory.get("intent"),
                "patient_id": patient_memory.get("patient_id"),
                "symptoms": patient_memory.get("symptoms", []),
            },
            {
                "agent": "GaoDoctorAgent",
                "event": "skill_routing",
                "memory_scope": "skill_memory",
                "decision_owner": routing_decision.get("agent_scope") or "gaodoctor_agent",
                "routing_decision": routing_decision,
                "selected_skill": skill_memory.get("selected_skill"),
                "used_skill": skill_memory.get("used_skill"),
                "skill_type": skill_memory.get("skill_type"),
                "skill_builder_action": routing_decision.get("skill_builder_action"),
                "analysis_status": alignment_plan.get("analysis_status"),
                "required_next_images": list(alignment_plan.get("required_next_images") or []),
            },
            {
                "agent": "SkillBuilderAgent",
                "event": "skill_loading",
                "memory_scope": "skill_memory",
                "action": routing_decision.get("skill_builder_action"),
                "selected_skill": skill_memory.get("selected_skill"),
                "used_skill": skill_memory.get("used_skill"),
                "skill_type": skill_memory.get("skill_type"),
                "evidence_level": skill_memory.get("evidence_level"),
                "formal_skill_status": (
                    skill_memory.get("quality_control", {}) or {}
                ).get("formal_skill_status"),
                "visual_protocol_status": (
                    skill_memory.get("quality_control", {}) or {}
                ).get("visual_protocol_status"),
            },
            {
                "agent": "VisionAgent",
                "event": "visual_evidence",
                "memory_scope": "image_memory",
                "tool": visual_tool_name,
                "selected_vision_mode": selected_vision_mode,
                "image_path": image_memory.get("image_path"),
                "modality": image_memory.get("modality"),
                "body_part": image_memory.get("body_part"),
                "image_outputs": image_memory.get("image_outputs", {}),
                "measurements": image_memory.get("measurements", {}),
                "visual_evidence_bundle": image_memory.get("visual_evidence_bundle", {}),
                "lesion_gallery_summary": lesion_gallery_summary,
                "completeness": image_memory.get("completeness", {}),
                "segmentation_quality": image_memory.get("segmentation_quality"),
            },
            {
                "agent": "DiagnosisDoctorAgent",
                "event": "diagnosis_report",
                "memory_scope": "reasoning_memory",
                "diagnostic_tendency": reasoning_memory.get("diagnostic_tendency"),
                "key_evidence": reasoning_memory.get("key_evidence", []),
                "uncertainty": reasoning_memory.get("uncertainty", []),
                "follow_up": reasoning_memory.get("follow_up", []),
            },
            {
                "agent": "MemoryManager",
                "event": "memory_audit",
                "memory_scope": "patient_memory,image_memory,skill_memory,reasoning_memory",
                "evidence_bundle_status": "available",
                "audit_status": "available",
                "memory_completeness": audit.get("memory_completeness", {}),
                "lesion_gallery_summary": lesion_gallery_summary,
                "quality_warnings": audit.get("quality_warnings", []),
            },
        ]
        for entry in patient_memory.get("qa_history", []):
            steps.append(
                {
                    "agent": "GaoDoctorAgent QA",
                    "event": "follow_up_qa",
                    "memory_scope": "patient_memory.qa_history",
                    "question": entry.get("question"),
                    "answer": entry.get("answer"),
                    "evidence_bundle_used": entry.get("evidence_bundle_used"),
                    "llm_used": entry.get("llm_used"),
                    "llm_fallback_reason": entry.get("llm_fallback_reason"),
                }
            )
        return {
            "case_id": case_id,
            "status": "ready",
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "case_summary": self._case_summary(record),
            "replay_consistency": self._build_replay_consistency(steps),
            "steps": steps,
            "memory_outputs": {
                "case_memory_path": str(self.cases_dir / f"{case_id}.json"),
                "audit_path": str(Path("output/fake/memory_audit") / f"{case_id}_audit.json"),
                "evidence_bundle": evidence_bundle,
            },
        }

    def build_runtime_manifest(self, case_id: str) -> dict[str, Any]:
        record = self.load_case_memory(case_id)
        evidence_bundle = self.get_evidence_bundle(case_id)
        patient_memory = record["patient_memory"]
        image_memory = record["image_memory"]
        skill_memory = record["skill_memory"]
        reasoning_memory = record["reasoning_memory"]
        routing_decision = skill_memory.get("routing_decision", {})
        alignment_plan = (
            skill_memory.get("alignment_plan")
            or reasoning_memory.get("alignment_plan")
            or {}
        )
        selected_vision_mode = (
            skill_memory.get("selected_vision_mode")
            or routing_decision.get("selected_vision_mode")
        )
        visual_tool_name = self._infer_visual_tool_name(
            image_memory=image_memory,
            selected_vision_mode=selected_vision_mode,
        )
        lesion_gallery = evidence_bundle.get("lesion_gallery", {})
        manifest = {
            "schema_version": "runtime_manifest.v1",
            "case_id": case_id,
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "selected_skill": (
                skill_memory.get("selected_skill")
                or skill_memory.get("used_skill")
                or skill_memory.get("skill_id")
            ),
            "skill_version": (
                skill_memory.get("used_skill")
                or skill_memory.get("skill_id")
                or skill_memory.get("selected_skill")
            ),
            "skill_type": skill_memory.get("skill_type"),
            "input_artifacts": {
                "patient_message_present": bool(patient_memory.get("patient_message")),
                "image_path": image_memory.get("image_path"),
                "modality": image_memory.get("modality"),
                "body_part": image_memory.get("body_part"),
            },
            "generated_artifacts": {
                "image_outputs": image_memory.get("image_outputs", {}),
                "lesion_gallery_summary": self._lesion_gallery_summary(lesion_gallery),
                "evidence_bundle_status": "available",
                "memory_audit_path": str(
                    Path("output/fake/memory_audit") / f"{case_id}_audit.json"
                ),
                "case_memory_path": str(self.cases_dir / f"{case_id}.json"),
            },
            "tool_calls": [
                {
                    "stage": "skill_gateway",
                    "tool": "SkillBuilderTool",
                    "action": routing_decision.get("skill_builder_action"),
                    "selected_skill": routing_decision.get("selected_skill"),
                },
                {
                    "stage": "visual_evidence",
                    "tool": visual_tool_name,
                    "selected_vision_mode": selected_vision_mode,
                    "diagnosis_usable": self._visual_evidence_has_diagnosis_usable_fact(
                        image_memory
                    ),
                },
                {
                    "stage": "memory_audit",
                    "tool": "MemoryManager",
                    "action": "build_evidence_bundle_and_replay",
                },
            ],
            "contracts_checked": {
                "memory_v1": record.get("schema_version") == self.SCHEMA_VERSION,
                "patient_case_input": bool(patient_memory),
                "skill_routing_decision": bool(routing_decision),
                "alignment_plan": bool(alignment_plan),
                "visual_analysis_result": bool(
                    image_memory.get("visual_evidence")
                    or image_memory.get("visual_evidence_bundle")
                    or image_memory.get("visual_features")
                ),
                "evidence_bundle": bool(evidence_bundle),
                "safety_gate": bool(
                    skill_memory.get("safety_gate")
                    or skill_memory.get("quality_control")
                    or alignment_plan.get("diagnosis_scope")
                ),
            },
            "memory_written": {
                memory_type: bool(record.get(memory_type))
                for memory_type in self.MEMORY_TYPES
            },
            "blocked_or_missing_evidence": {
                "analysis_status": alignment_plan.get("analysis_status"),
                "missing_or_unassessed": evidence_bundle.get("missing_or_unassessed", {}),
                "quality_warnings": evidence_bundle.get("quality_warnings", []),
                "required_next_images": list(alignment_plan.get("required_next_images") or []),
                "blocked_scopes": list(
                    (alignment_plan.get("diagnosis_scope") or {}).get("blocked") or []
                ),
            },
            "runtime_safety": {
                "manifest_only": True,
                "stop_hook_executed": False,
                "formal_skill_updated": False,
                "self_evolving_action": "candidate_only_no_formal_skill_update",
            },
        }
        manifest_dir = Path("output/fake/runtime_manifest")
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f"{case_id}_runtime_manifest.json"
        manifest["manifest_path"] = str(manifest_path)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest

    def build_stop_hook_gate(self, case_id: str) -> dict[str, Any]:
        manifest = self.build_runtime_manifest(case_id)
        evidence_bundle = self.get_evidence_bundle(case_id)
        record = self.load_case_memory(case_id)
        missing_or_unassessed = evidence_bundle.get("missing_or_unassessed", {})
        quality_warnings = evidence_bundle.get("quality_warnings", [])
        blocked_or_missing = manifest.get("blocked_or_missing_evidence", {})
        blocked_scopes = list(blocked_or_missing.get("blocked_scopes") or [])
        required_next_images = list(blocked_or_missing.get("required_next_images") or [])
        memory_written = manifest.get("memory_written", {})
        warnings: list[dict[str, Any]] = []
        if self._has_missing_or_unassessed(missing_or_unassessed):
            warnings.append(
                {
                    "code": "missing_or_unassessed_evidence",
                    "severity": "medium",
                    "message": "Some evidence fields are missing or unassessed and must not be treated as negative.",
                    "details": missing_or_unassessed,
                }
            )
        if blocked_scopes:
            warnings.append(
                {
                    "code": "blocked_diagnosis_scope",
                    "severity": "high",
                    "message": "Alignment plan blocks at least one diagnosis scope.",
                    "details": blocked_scopes,
                }
            )
        if quality_warnings:
            warnings.append(
                {
                    "code": "quality_warnings_present",
                    "severity": "medium",
                    "message": "Evidence bundle contains quality warnings.",
                    "details": quality_warnings,
                }
            )
        missing_memory_types = [
            memory_type for memory_type, present in memory_written.items() if not present
        ]
        if missing_memory_types:
            warnings.append(
                {
                    "code": "memory_incomplete",
                    "severity": "high",
                    "message": "One or more required memory scopes are missing.",
                    "details": missing_memory_types,
                }
            )
        visual_fact_usage = record["reasoning_memory"].get("visual_fact_usage", {})
        if int(visual_fact_usage.get("excluded_count") or 0) > 0:
            warnings.append(
                {
                    "code": "excluded_visual_facts_present",
                    "severity": "low",
                    "message": "Excluded visual facts exist and must not be reused as independent evidence.",
                    "details": {
                        "excluded_count": visual_fact_usage.get("excluded_count"),
                        "excluded": visual_fact_usage.get("excluded", []),
                    },
                }
            )
        next_actions = self._build_stop_hook_next_actions(
            required_next_images=required_next_images,
            warnings=warnings,
        )
        gate = {
            "schema_version": "stop_hook_gate.v1",
            "case_id": case_id,
            "source_runtime_manifest_path": manifest.get("manifest_path"),
            "runtime_warnings": warnings,
            "next_actions": next_actions,
            "candidate_memory": {
                "status": "not_generated",
                "reason": "read_only_gate",
            },
            "candidate_skill_patch": {
                "status": "not_generated",
                "reason": "read_only_gate",
                "validation_status": "not_started",
            },
            "runtime_safety": {
                "stop_hook_executed": True,
                "read_only": True,
                "formal_skill_updated": False,
                "diagnosis_report_updated": False,
                "self_evolving_queue_updated": False,
            },
        }
        gate_dir = Path("output/fake/stop_hook_gate")
        gate_dir.mkdir(parents=True, exist_ok=True)
        gate_path = gate_dir / f"{case_id}_stop_hook_gate.json"
        gate["gate_path"] = str(gate_path)
        gate_path.write_text(
            json.dumps(gate, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return gate

    def build_self_evolving_queue(self, case_id: str) -> dict[str, Any]:
        gate = self.build_stop_hook_gate(case_id)
        queue_items = self._build_self_evolving_queue_items(gate)
        queue = {
            "schema_version": "self_evolving_queue.v1",
            "case_id": case_id,
            "status": "candidate_only",
            "source_stop_hook_gate": gate,
            "queue_items": queue_items,
            "review_policy": {
                "required_review": "human_or_validated_dataset",
                "promotion_rule": (
                    "Candidate memory or skill patches must be validated before formal skill update."
                ),
                "allowed_outputs": [
                    "candidate_memory",
                    "candidate_rule",
                    "candidate_skill_patch",
                ],
            },
            "runtime_safety": {
                "queue_written": True,
                "candidate_only": True,
                "formal_skill_updated": False,
                "formal_guideline_updated": False,
                "diagnosis_report_updated": False,
            },
        }
        queue_dir = Path("output/fake/self_evolving_queue")
        queue_dir.mkdir(parents=True, exist_ok=True)
        queue_path = queue_dir / f"{case_id}_self_evolving_queue.json"
        queue["queue_path"] = str(queue_path)
        queue_path.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return queue

    def build_candidate_validation_gate(self, case_id: str) -> dict[str, Any]:
        queue = self.build_self_evolving_queue(case_id)
        item_validations = [
            self._validate_candidate_queue_item(item)
            for item in queue.get("queue_items", [])
            if isinstance(item, dict)
        ]
        promotable_items = [
            item for item in item_validations if item.get("promotion_eligible") is True
        ]
        gate = {
            "schema_version": "candidate_validation_gate.v1",
            "case_id": case_id,
            "source_queue_path": queue.get("queue_path"),
            "source_queue_schema_version": queue.get("schema_version"),
            "item_validations": item_validations,
            "promotion_decision": {
                "status": "ready" if promotable_items else "blocked",
                "reason": (
                    "candidate_items_passed_validation"
                    if promotable_items
                    else "candidate_items_require_review_or_validation"
                ),
                "formal_update_allowed": bool(promotable_items),
                "promotable_item_ids": [
                    str(item.get("item_id")) for item in promotable_items
                ],
            },
            "review_requirements": [
                "人工或经过验证的数据集审核候选项。",
                "保留 source warning、case id、evidence 和版本回滚路径。",
                "升级正式 skill 前必须确认不覆盖正式指南原文。",
            ],
            "runtime_safety": {
                "validation_gate_executed": True,
                "read_only": True,
                "formal_skill_updated": False,
                "formal_guideline_updated": False,
                "diagnosis_report_updated": False,
            },
        }
        gate_dir = Path("output/fake/candidate_validation_gate")
        gate_dir.mkdir(parents=True, exist_ok=True)
        gate_path = gate_dir / f"{case_id}_candidate_validation_gate.json"
        gate["gate_path"] = str(gate_path)
        gate_path.write_text(
            json.dumps(gate, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return gate

    def build_runtime_gateway_trace(self, case_id: str) -> dict[str, Any]:
        manifest = self.build_runtime_manifest(case_id)
        stop_hook_gate = self.build_stop_hook_gate(case_id)
        queue = self.build_self_evolving_queue(case_id)
        validation_gate = self.build_candidate_validation_gate(case_id)
        promotion_decision = validation_gate.get("promotion_decision", {})
        trace = {
            "schema_version": "runtime_gateway_trace.v1",
            "case_id": case_id,
            "stages": [
                {
                    "stage": "runtime_manifest",
                    "schema_version": manifest.get("schema_version"),
                    "status": "available",
                    "artifact_path": manifest.get("manifest_path"),
                    "summary": {
                        "selected_skill": manifest.get("selected_skill"),
                        "skill_type": manifest.get("skill_type"),
                    },
                },
                {
                    "stage": "stop_hook_gate",
                    "schema_version": stop_hook_gate.get("schema_version"),
                    "status": "available",
                    "artifact_path": stop_hook_gate.get("gate_path"),
                    "summary": {
                        "warning_count": len(stop_hook_gate.get("runtime_warnings") or []),
                        "read_only": stop_hook_gate.get("runtime_safety", {}).get("read_only"),
                    },
                },
                {
                    "stage": "self_evolving_queue",
                    "schema_version": queue.get("schema_version"),
                    "status": queue.get("status"),
                    "artifact_path": queue.get("queue_path"),
                    "summary": {
                        "item_count": len(queue.get("queue_items") or []),
                        "candidate_only": queue.get("runtime_safety", {}).get("candidate_only"),
                    },
                },
                {
                    "stage": "candidate_validation_gate",
                    "schema_version": validation_gate.get("schema_version"),
                    "status": promotion_decision.get("status"),
                    "artifact_path": validation_gate.get("gate_path"),
                    "summary": {
                        "formal_update_allowed": promotion_decision.get(
                            "formal_update_allowed"
                        ),
                        "reason": promotion_decision.get("reason"),
                    },
                },
            ],
            "promotion_status": promotion_decision.get("status"),
            "formal_update_allowed": bool(
                promotion_decision.get("formal_update_allowed")
            ),
            "safety_invariants": {
                "formal_skill_updated": False,
                "formal_guideline_updated": False,
                "diagnosis_report_updated": False,
                "candidate_artifacts_only": True,
            },
            "presentation_summary": (
                "Runtime Gateway coordinates skill dispatch, artifacts, hooks, "
                "candidate learning, and validation without directly changing formal medical skills."
            ),
        }
        trace["trace_consistency"] = self._build_runtime_gateway_trace_consistency(
            trace["stages"]
        )
        trace_dir = Path("output/fake/runtime_gateway_trace")
        trace_dir.mkdir(parents=True, exist_ok=True)
        trace_path = trace_dir / f"{case_id}_runtime_gateway_trace.json"
        trace["trace_path"] = str(trace_path)
        trace_path.write_text(
            json.dumps(trace, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return trace

    def _build_runtime_gateway_trace_consistency(
        self,
        stages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        missing_artifact_paths = [
            str(stage.get("stage") or "unknown")
            for stage in stages
            if not stage.get("artifact_path") or not Path(str(stage.get("artifact_path"))).exists()
        ]
        missing_schema_stages = [
            str(stage.get("stage") or "unknown")
            for stage in stages
            if not stage.get("schema_version")
        ]
        return {
            "stage_count": len(stages),
            "all_stage_artifacts_available": not missing_artifact_paths,
            "all_stage_schemas_present": not missing_schema_stages,
            "missing_artifact_paths": missing_artifact_paths,
            "missing_schema_stages": missing_schema_stages,
            "stage_order": [str(stage.get("stage") or "") for stage in stages],
        }

    def _validate_candidate_queue_item(self, item: dict[str, Any]) -> dict[str, Any]:
        passed_checks: list[str] = []
        failed_checks: list[str] = []

        if item.get("item_id"):
            passed_checks.append("item_id_present")
        else:
            failed_checks.append("item_id_missing")

        if item.get("source_warning_code"):
            passed_checks.append("source_warning_present")
        else:
            failed_checks.append("source_warning_missing")

        if item.get("proposal"):
            passed_checks.append("proposal_present")
        else:
            failed_checks.append("proposal_missing")

        if item.get("evidence") not in (None, {}, []):
            passed_checks.append("evidence_present")
        else:
            failed_checks.append("evidence_missing")

        validation_status = item.get("validation_status")
        if validation_status in {"validated", "approved"}:
            passed_checks.append("review_or_validation_present")
        elif validation_status == "not_required" and item.get("allowed_action") == "archive_only":
            passed_checks.append("archive_only_no_promotion")
        else:
            failed_checks.append("review_or_validation_missing")

        if item.get("formal_update_allowed") is True:
            passed_checks.append("candidate_allows_formal_update")
        else:
            failed_checks.append("formal_update_not_allowed")

        promotion_eligible = (
            "review_or_validation_present" in passed_checks
            and "candidate_allows_formal_update" in passed_checks
            and not failed_checks
        )
        return {
            "item_id": item.get("item_id"),
            "candidate_type": item.get("candidate_type"),
            "source_warning_code": item.get("source_warning_code"),
            "validation_status": validation_status,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "promotion_eligible": promotion_eligible,
            "decision": "ready_for_manual_promotion" if promotion_eligible else "blocked",
        }

    def _build_self_evolving_queue_items(self, gate: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        warnings = gate.get("runtime_warnings") or []
        for index, warning in enumerate(warnings, start=1):
            if not isinstance(warning, dict):
                continue
            code = str(warning.get("code") or "runtime_warning")
            items.append(
                {
                    "item_id": f"{gate.get('case_id')}_{index:02d}_{code}",
                    "source_warning_code": code,
                    "severity": warning.get("severity"),
                    "candidate_type": self._candidate_type_for_warning(code),
                    "proposal": self._proposal_for_warning(warning),
                    "evidence": warning.get("details"),
                    "next_actions": list(gate.get("next_actions") or []),
                    "validation_status": "pending_review",
                    "allowed_action": "candidate_review_only",
                    "formal_update_allowed": False,
                }
            )
        if not items:
            items.append(
                {
                    "item_id": f"{gate.get('case_id')}_00_no_action",
                    "source_warning_code": "no_runtime_warning",
                    "severity": "info",
                    "candidate_type": "candidate_memory",
                    "proposal": "保留本轮运行记录；暂不提出 skill 或规则变更。",
                    "evidence": {},
                    "next_actions": list(gate.get("next_actions") or []),
                    "validation_status": "not_required",
                    "allowed_action": "archive_only",
                    "formal_update_allowed": False,
                }
            )
        return items

    def _candidate_type_for_warning(self, warning_code: str) -> str:
        if warning_code in {"blocked_diagnosis_scope", "missing_or_unassessed_evidence"}:
            return "candidate_skill_patch"
        if warning_code in {"memory_incomplete", "excluded_visual_facts_present"}:
            return "candidate_memory"
        return "candidate_rule"

    def _proposal_for_warning(self, warning: dict[str, Any]) -> str:
        code = str(warning.get("code") or "")
        if code == "missing_or_unassessed_evidence":
            return "为当前 skill 补充 evidence completeness 规则，明确 missing/unassessed 不可解释为阴性。"
        if code == "blocked_diagnosis_scope":
            return "保留诊断范围阻断规则，并要求补充指定影像后再解除阻断。"
        if code == "quality_warnings_present":
            return "沉淀视觉质量警告为候选规则，后续用验证集确认是否需要升级为正式 quality gate。"
        if code == "memory_incomplete":
            return "补充 memory 写入完整性检查，避免四类 memory 缺失。"
        if code == "excluded_visual_facts_present":
            return "追问 QA 应继续排除 non-independent 或 not-usable 视觉事实。"
        return str(warning.get("message") or "保留为候选运行经验。")

    def _has_missing_or_unassessed(self, missing_or_unassessed: dict[str, Any]) -> bool:
        for scope_value in missing_or_unassessed.values():
            if isinstance(scope_value, dict) and scope_value:
                return True
            if isinstance(scope_value, list) and scope_value:
                return True
        return False

    def _build_stop_hook_next_actions(
        self,
        required_next_images: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> list[str]:
        actions: list[str] = []
        for image in required_next_images:
            if not isinstance(image, dict):
                continue
            modality = image.get("modality") or "补充影像"
            region = image.get("region") or image.get("body_part") or "目标区域"
            reason = image.get("reason") or "补充关键影像"
            actions.append(f"补充关键影像：{region} {modality}；{reason}")
        if any(warning.get("code") == "missing_or_unassessed_evidence" for warning in warnings):
            actions.append("不要将 missing / unassessed 证据解释为阴性。")
        if any(warning.get("code") == "excluded_visual_facts_present" for warning in warnings):
            actions.append("追问 QA 不得把 excluded visual facts 重新作为独立诊断证据。")
        if not actions:
            actions.append("无需自动修改报告或 skill；保留只读审计记录。")
        return actions

    def _visual_evidence_has_diagnosis_usable_fact(self, image_memory: dict[str, Any]) -> bool:
        visual_evidence_bundle = image_memory.get("visual_evidence_bundle", {})
        findings = visual_evidence_bundle.get("findings")
        if not isinstance(findings, list):
            return bool(image_memory.get("image_outputs") or image_memory.get("visual_features"))
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            if finding.get("diagnosis_usable") is True:
                return True
            for region in finding.get("regions") or []:
                if isinstance(region, dict) and region.get("diagnosis_usable") is True:
                    return True
        return False

    def _build_replay_consistency(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        events = [step.get("event") for step in steps]
        missing_required_events = [
            event for event in self.REQUIRED_REPLAY_EVENTS if event not in events
        ]
        steps_missing_memory_scope = [
            index
            for index, step in enumerate(steps)
            if not step.get("memory_scope")
        ]
        return {
            "required_events_present": not missing_required_events,
            "missing_required_events": missing_required_events,
            "memory_scope_complete": not steps_missing_memory_scope,
            "steps_missing_memory_scope": steps_missing_memory_scope,
            "qa_extension_present": "follow_up_qa" in events,
            "step_count": len(steps),
        }

    def _lesion_gallery_summary(self, lesion_gallery: dict[str, Any]) -> dict[str, Any]:
        items = lesion_gallery.get("items")
        if not isinstance(items, list):
            items = []
        comparison_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            image_paths = item.get("image_paths") or {}
            if isinstance(image_paths, dict) and image_paths.get("comparison_path"):
                comparison_count += 1
        return {
            "schema_version": lesion_gallery.get("schema_version", "lesion_gallery.v1"),
            "item_count": len(items),
            "used_count": int(lesion_gallery.get("used_count") or 0),
            "excluded_count": int(lesion_gallery.get("excluded_count") or 0),
            "candidate_count": int(lesion_gallery.get("candidate_count") or 0),
            "comparison_artifact_count": comparison_count,
        }

    def _infer_visual_tool_name(
        self,
        image_memory: dict[str, Any],
        selected_vision_mode: str | None,
    ) -> str | None:
        visual_plan = (
            image_memory.get("visual_evidence", {}).get("visual_tool_plan")
            or image_memory.get("visual_evidence_bundle", {}).get("visual_tool_plan")
            or []
        )
        for planned in reversed(visual_plan):
            selected_tool = planned.get("selected_tool") or {}
            tool_name = selected_tool.get("tool_name") or planned.get("tool_name")
            if tool_name:
                return str(tool_name)
        if selected_vision_mode == "medsam2":
            return "MedSAM2"
        if selected_vision_mode == "ground_truth":
            return "ground_truth_mask"
        return selected_vision_mode

    def _case_summary(self, record: dict[str, Any]) -> dict[str, Any]:
        patient_memory = record.get("patient_memory", {})
        image_memory = record.get("image_memory", {})
        skill_memory = record.get("skill_memory", {})
        reasoning_memory = record.get("reasoning_memory", {})
        alignment_plan = (
            skill_memory.get("alignment_plan")
            or reasoning_memory.get("alignment_plan")
            or {}
        )
        qa_history = patient_memory.get("qa_history") or []
        return {
            "case_id": record.get("case_id"),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "patient_id": patient_memory.get("patient_id"),
            "intent": patient_memory.get("intent"),
            "selected_skill": skill_memory.get("selected_skill") or skill_memory.get("skill_id"),
            "used_skill": skill_memory.get("used_skill"),
            "skill_type": skill_memory.get("skill_type"),
            "analysis_status": alignment_plan.get("analysis_status"),
            "modality": image_memory.get("modality"),
            "body_part": image_memory.get("body_part"),
            "segmentation_quality": image_memory.get("segmentation_quality"),
            "diagnostic_tendency": reasoning_memory.get("diagnostic_tendency"),
            "qa_history_count": len(qa_history),
        }

    def _visual_task_status_counts(self, visual_tasks: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in visual_tasks:
            status = str(task.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _normalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        case_id = str(record.get("case_id") or "")
        created_at = record.get("created_at") or record.get("saved_at") or self._now()
        qa_history = self._normalize_qa_history(
            case_id=case_id,
            qa_history=record.get("patient_memory", {}).get("qa_history", []),
            qa_memory=record.get("qa_memory", []),
        )
        patient_memory = self._normalize_patient_memory(
            case_id=case_id,
            patient_memory=dict(record.get("patient_memory") or {}),
            qa_history=qa_history,
        )
        normalized = {
            "schema_version": self.SCHEMA_VERSION,
            "memory_types": list(self.MEMORY_TYPES),
            "case_id": case_id,
            "created_at": created_at,
            "updated_at": record.get("updated_at") or record.get("saved_at") or created_at,
            "patient_memory": patient_memory,
            "image_memory": self._normalize_image_memory(
                case_id,
                dict(record.get("image_memory") or {}),
            ),
            "skill_memory": self._normalize_skill_memory(dict(record.get("skill_memory") or {})),
            "reasoning_memory": self._normalize_reasoning_memory(
                case_id,
                dict(record.get("reasoning_memory") or {}),
            ),
            "qa_memory": patient_memory["qa_history"],
        }
        return normalized

    def _normalize_patient_memory(
        self,
        case_id: str,
        patient_memory: dict[str, Any],
        qa_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        patient_info = (
            patient_memory.get("patient_info")
            or patient_memory.get("patient_profile")
            or {}
        )
        symptoms = patient_memory.get("symptoms")
        if symptoms is None:
            symptoms = patient_info.get("symptoms", []) if isinstance(patient_info, dict) else []
        normalized = dict(patient_memory)
        normalized["case_id"] = patient_memory.get("case_id") or case_id
        normalized["patient_id"] = patient_memory.get("patient_id")
        normalized["patient_message"] = patient_memory.get("patient_message", "")
        normalized["patient_info"] = patient_info
        normalized["symptoms"] = symptoms
        normalized["intent"] = patient_memory.get("intent", "diagnosis")
        normalized["qa_history"] = list(qa_history)
        return normalized

    def _normalize_image_memory(self, case_id: str, image_memory: dict[str, Any]) -> dict[str, Any]:
        visual_evidence = (
            image_memory.get("visual_evidence")
            or image_memory.get("visual_features")
            or {}
        )
        measurements = image_memory.get("measurements") or visual_evidence.get("measurements") or {}
        completeness = image_memory.get("completeness") or visual_evidence.get("completeness") or {}
        segmentation_quality = (
            image_memory.get("segmentation_quality")
            or visual_evidence.get("segmentation_quality")
            or "not_available"
        )
        normalized = dict(image_memory)
        normalized["case_id"] = image_memory.get("case_id") or case_id
        normalized.setdefault("image_path", "")
        normalized.setdefault("modality", "unknown")
        normalized.setdefault("body_part", "unknown")
        normalized.setdefault("image_outputs", {})
        normalized["visual_features"] = image_memory.get("visual_features") or visual_evidence
        normalized["visual_evidence"] = visual_evidence
        normalized["visual_evidence_bundle"] = image_memory.get("visual_evidence_bundle") or {}
        normalized["measurements"] = measurements
        normalized["completeness"] = completeness
        normalized["segmentation_quality"] = segmentation_quality
        return normalized

    def _normalize_skill_memory(self, skill_memory: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(skill_memory)
        skill_id = skill_memory.get("skill_id") or skill_memory.get("selected_skill")
        normalized["selected_skill"] = skill_memory.get("selected_skill") or skill_id
        normalized.setdefault("selected_vision_mode", None)
        normalized.setdefault("routing_decision", {})
        normalized.setdefault("alignment_plan", {})
        normalized["used_skill"] = skill_memory.get("used_skill") or skill_id
        normalized.setdefault("skill_type", skill_memory.get("type"))
        normalized.setdefault("guideline_evidence", {})
        normalized.setdefault("source_priority", [])
        normalized.setdefault("guideline_conflicts", skill_memory.get("conflicts", []))
        normalized.setdefault("quality_control", {})
        return normalized

    def _normalize_reasoning_memory(
        self,
        case_id: str,
        reasoning_memory: dict[str, Any],
    ) -> dict[str, Any]:
        report = reasoning_memory.get("report") or {}
        diagnostic_tendency = (
            reasoning_memory.get("diagnostic_tendency")
            or reasoning_memory.get("diagnostic_result")
            or report.get("diagnostic_tendency")
            or report.get("诊断倾向")
        )
        uncertainty = reasoning_memory.get("uncertainty") or report.get("不确定性说明") or []
        follow_up = reasoning_memory.get("follow_up") or report.get("建议进一步检查") or []
        treatment_advice = (
            reasoning_memory.get("treatment_advice")
            or report.get("治疗建议")
            or []
        )
        normalized = dict(reasoning_memory)
        normalized["case_id"] = reasoning_memory.get("case_id") or case_id
        normalized["report"] = report
        normalized["diagnostic_tendency"] = diagnostic_tendency
        normalized["diagnostic_result"] = reasoning_memory.get("diagnostic_result") or diagnostic_tendency
        normalized["visual_input_contract"] = (
            reasoning_memory.get("visual_input_contract")
            or report.get("visual_input_contract")
            or {}
        )
        visual_fact_usage = (
            reasoning_memory.get("visual_fact_usage")
            or report.get("visual_fact_usage")
            or {}
        )
        normalized["visual_fact_usage"] = visual_fact_usage
        normalized["used_visual_facts"] = (
            reasoning_memory.get("used_visual_facts")
            or report.get("used_visual_facts")
            or visual_fact_usage.get("used")
            or []
        )
        normalized["excluded_visual_facts"] = (
            reasoning_memory.get("excluded_visual_facts")
            or report.get("excluded_visual_facts")
            or visual_fact_usage.get("excluded")
            or []
        )
        normalized["used_visual_fields"] = (
            reasoning_memory.get("used_visual_fields")
            or report.get("used_visual_fields")
            or []
        )
        normalized["missing_visual_fields_acknowledged"] = (
            reasoning_memory.get("missing_visual_fields_acknowledged")
            or report.get("missing_visual_fields_acknowledged")
            or []
        )
        normalized["uncertainty"] = uncertainty
        normalized["follow_up"] = follow_up
        normalized["treatment_advice"] = treatment_advice
        normalized.setdefault("key_evidence", reasoning_memory.get("key_evidence") or report.get("影像依据") or [])
        return normalized

    def _normalize_qa_history(
        self,
        case_id: str,
        qa_history: list[dict[str, Any]],
        qa_memory: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        entries = qa_history or qa_memory or []
        normalized_entries = []
        for entry in entries:
            created_at = entry.get("created_at") or entry.get("answered_at") or self._now()
            normalized_entries.append(
                {
                    "question": entry.get("question", ""),
                    "answer": entry.get("answer", ""),
                    "created_at": created_at,
                    "referenced_case_id": entry.get("referenced_case_id") or case_id,
                    "evidence_bundle_used": bool(entry.get("evidence_bundle_used", True)),
                    "llm_used": bool(entry.get("llm_used", False)),
                    "llm_fallback_reason": entry.get("llm_fallback_reason"),
                }
            )
        return normalized_entries

    def _collect_missing_or_unassessed(self, record: dict[str, Any]) -> dict[str, Any]:
        completeness = record["image_memory"].get("completeness") or {}
        missing_image = {
            target: status
            for target, status in completeness.items()
            if isinstance(status, dict) and status.get("status") in {"missing", "unassessed"}
        }
        return {
            "image_memory": missing_image,
            "reasoning_memory": {
                "missing_visual_fields_acknowledged": record["reasoning_memory"].get(
                    "missing_visual_fields_acknowledged",
                    [],
                )
            },
        }

    def _collect_quality_warnings(
        self,
        record: dict[str, Any],
        missing_or_unassessed: dict[str, Any],
    ) -> list[str]:
        warnings = []
        for target, status in missing_or_unassessed.get("image_memory", {}).items():
            warnings.append(
                f"image_memory.{target} is {status.get('status')}: {status.get('reason')}"
            )
        quality_control = record["skill_memory"].get("quality_control") or {}
        if quality_control.get("formal_skill_status") == "needs_review":
            warnings.append("skill_memory quality_control requires review")
        conflicts = record["skill_memory"].get("guideline_conflicts") or []
        if conflicts:
            warnings.append("guideline conflicts require manual review")
        return warnings

    def _record_sort_key(self, record: dict[str, Any]) -> tuple[str, str]:
        return (str(record.get("updated_at") or record.get("created_at") or ""), record["case_id"])

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")
