from __future__ import annotations

import argparse
import mimetypes
import json
import os
import re
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

from api.service import MedScopeReadinessError, MedScopeService, normalize_guideline_knowledge_draft
from llm.connectivity import ApiConnectivityChecker
from memory.memory_manager import MemoryManager
from scripts.image_prompt_knowledge_baseline import run_image_prompt_knowledge_baseline
from scripts.prepare_public_demo_fixture import run_public_safe_demo_suite
from scripts.research_evidence_builder import build_research_evidence_review_package
from knowledge_editor.backend import (
    dispatch_knowledge_editor_api_request,
    dispatch_knowledge_editor_static_request,
)
from tools.knowledge_builder_tool import KnowledgeBuilderTool
from tools.medsam2_segmentation_tool import inspect_medsam2_configuration


STATIC_ROOT = Path(__file__).resolve().parent.parent / "web"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UPLOAD_ROOT = PROJECT_ROOT / "output" / "fake" / "uploads"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output"
STANDARD_DEMO_DIR_NAME = "standard_demo_with_fhn_no_mask_qc"
REAL_VLM_MEDSAM2_DIAGNOSIS_DIR_NAME = "brats_real_vlm_medsam2_diagnosis_demo_real_llm"
REAL_VLM_MEDSAM2_SEGMENTATION_DIR_NAME = "brats_medsam2_auto_eval_real_vlm_prompt_real_medsam2"
REAL_VLM_MEDSAM2_PROMPT_DIR_NAME = "brats_vlm_prompt_demo_real_api"
DEMO_ARTIFACT_FILENAMES = {
    "response": "{case_slug}_response.json",
    "evidence-bundle": "{case_slug}_evidence_bundle.json",
    "audit": "{case_slug}_audit.json",
}
REAL_VLM_MEDSAM2_ARTIFACTS = {
    "": (REAL_VLM_MEDSAM2_DIAGNOSIS_DIR_NAME, "summary.json"),
    "report": (REAL_VLM_MEDSAM2_DIAGNOSIS_DIR_NAME, "diagnosis_report.json"),
    "evidence-bundle": (REAL_VLM_MEDSAM2_DIAGNOSIS_DIR_NAME, "evidence_bundle.json"),
    "raw-llm": (REAL_VLM_MEDSAM2_DIAGNOSIS_DIR_NAME, "llm_raw_content.json"),
    "segmentation": (REAL_VLM_MEDSAM2_SEGMENTATION_DIR_NAME, "summary.json"),
    "vlm-prompt": (REAL_VLM_MEDSAM2_PROMPT_DIR_NAME, "summary.json"),
}
REQUIRED_TRACE_AGENTS = [
    "GaoDoctorAgent",
    "KnowledgeBuilderAgent",
    "VisionAgent",
    "DiagnosisDoctorAgent",
    "MemoryManager",
]
REQUIRED_REPLAY_EVENTS = [
    "patient_intake",
    "knowledge_routing",
    "knowledge_loading",
    "visual_evidence",
    "diagnosis_report",
    "memory_audit",
]
REPLAY_MEMORY_SCOPE_BY_EVENT = {
    "patient_intake": "patient_memory",
    "knowledge_routing": "knowledge_memory",
    "knowledge_loading": "knowledge_memory",
    "vlm_prompt_generation": "image_memory",
    "visual_evidence": "image_memory",
    "diagnosis_report": "reasoning_memory",
    "memory_audit": "patient_memory,image_memory,knowledge_memory,reasoning_memory",
    "follow_up_qa": "patient_memory.qa_history",
}
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


def _remove_prefix(value: str, prefix: str) -> str:
    return value[len(prefix) :] if value.startswith(prefix) else value


def _remove_suffix(value: str, suffix: str) -> str:
    return value[: -len(suffix)] if suffix and value.endswith(suffix) else value


def load_dotenv_local(path: Path | str = Path(".env.local")) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    loaded: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if not key or key in os.environ:
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded


def _build_trace_consistency(agents_traced: list[str], agent_io_summary: dict) -> dict:
    agent_io_keys = list(agent_io_summary.keys())
    missing_required_agents = [
        agent for agent in REQUIRED_TRACE_AGENTS if agent not in agents_traced
    ]
    return {
        "agent_io_matches_trace": agent_io_keys == agents_traced,
        "required_agents_present": not missing_required_agents,
        "missing_required_agents": missing_required_agents,
        "qa_extension_present": "GaoDoctorAgent QA" in agents_traced,
        "agent_count": len(agents_traced),
        "agent_io_count": len(agent_io_keys),
    }


def _build_replay_consistency(steps: list[dict]) -> dict:
    events = [step.get("event") for step in steps]
    missing_required_events = [
        event for event in REQUIRED_REPLAY_EVENTS if event not in events
    ]
    steps_missing_memory_scope = [
        index for index, step in enumerate(steps) if not step.get("memory_scope")
    ]
    return {
        "required_events_present": not missing_required_events,
        "missing_required_events": missing_required_events,
        "memory_scope_complete": not steps_missing_memory_scope,
        "steps_missing_memory_scope": steps_missing_memory_scope,
        "qa_extension_present": "follow_up_qa" in events,
        "step_count": len(steps),
    }


def _with_default_replay_memory_scope(step: dict) -> dict:
    normalized_step = dict(step)
    if normalized_step.get("memory_scope"):
        return normalized_step
    memory_scope = REPLAY_MEMORY_SCOPE_BY_EVENT.get(normalized_step.get("event"))
    if memory_scope:
        normalized_step["memory_scope"] = memory_scope
    return normalized_step


def _normalize_replay_steps_memory_scope(steps: list[dict]) -> list[dict]:
    return [
        _with_default_replay_memory_scope(step)
        for step in steps
        if isinstance(step, dict)
    ]


def dispatch_static_request(path: str) -> tuple[int, bytes, str]:
    route_path = urlparse(path).path
    if route_path not in STATIC_ROUTES:
        return 404, b"", "text/plain; charset=utf-8"
    filename, content_type = STATIC_ROUTES[route_path]
    file_path = STATIC_ROOT / filename
    if not file_path.exists():
        return 404, b"", "text/plain; charset=utf-8"
    return 200, file_path.read_bytes(), content_type


def handle_file_upload(
    filename: str,
    body: bytes,
    upload_root: Path | str = DEFAULT_UPLOAD_ROOT,
) -> tuple[int, dict]:
    if not body:
        return 400, {"error": "empty upload body"}
    safe_name = _safe_upload_filename(filename)
    root = Path(upload_root)
    if root.name != "uploads":
        root = root / "output" / "fake" / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    file_path = root / safe_name
    file_path.write_bytes(body)
    return 200, {"image_path": str(file_path), "filename": safe_name, "size_bytes": len(body)}


def build_readiness_payload(
    upload_root: Path | str = DEFAULT_UPLOAD_ROOT,
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
) -> dict:
    upload_path = Path(upload_root)
    output_path = Path(output_root)
    upload_path.mkdir(parents=True, exist_ok=True)
    output_path.mkdir(parents=True, exist_ok=True)
    api_checker = ApiConnectivityChecker()
    api_route = api_checker.inspect()
    real_vlm_validation = api_checker.inspect_real_vlm_validation()
    medsam2 = inspect_medsam2_configuration()
    return {
        "status": "ok",
        "api_route": api_route,
        "real_vlm_validation": real_vlm_validation,
        "medsam2": medsam2,
        "storage": {
            "upload_root": str(upload_path),
            "upload_root_exists": upload_path.exists(),
            "upload_root_writable": os.access(upload_path, os.W_OK),
            "output_root": str(output_path),
            "output_root_exists": output_path.exists(),
            "output_root_writable": os.access(output_path, os.W_OK),
        },
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
        },
    }


def dispatch_binary_request(
    method: str,
    path: str,
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
) -> tuple[int, bytes, str]:
    if method != "GET":
        return 404, b"", "text/plain; charset=utf-8"
    try:
        file_path = resolve_public_output_path(path, output_root=output_root)
    except ValueError:
        return 404, b"", "text/plain; charset=utf-8"
    if not file_path.exists() or not file_path.is_file():
        return 404, b"", "text/plain; charset=utf-8"
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return 200, file_path.read_bytes(), content_type


def resolve_public_output_path(path: str, output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path:
    route_path = urlparse(path).path
    if not route_path.startswith("/output/"):
        raise ValueError("only output files can be served")
    root = Path(output_root).resolve()
    relative = _remove_prefix(route_path, "/output/")
    if not relative or ".." in Path(relative).parts:
        raise ValueError("invalid output path")
    resolved = (root / relative).resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("output path escaped root")
    return resolved


def _safe_upload_filename(filename: str) -> str:
    name = Path(filename or "upload.bin").name
    name = re.sub(r"[^\w.-]+", "_", name, flags=re.UNICODE).strip("._")
    return name or "upload.bin"


def dispatch_knowledge_request(
    method: str,
    path: str,
    body: bytes = b"",
    knowledges_dir: Path | str = PROJECT_ROOT / "knowledge",
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
) -> tuple[int | None, dict]:
    route_path = unquote(urlparse(path).path)
    if route_path != "/v1/knowledge" and not route_path.startswith("/v1/knowledge/"):
        return None, {}
    knowledges_root = Path(knowledges_dir)
    output = Path(output_root)
    if method == "GET" and route_path == "/v1/knowledge":
        formal_knowledge_keys = {
            knowledge_path.stem
            for knowledge_path, _knowledge in _iter_knowledge_files(knowledges_root)
        }
        knowledge = [
            _doctor_knowledge_summary(knowledge_key=knowledge_path.stem, knowledge=knowledge, output_root=output)
            for knowledge_path, knowledge in _iter_knowledge_files(knowledges_root)
        ]
        knowledge.extend(
            _doctor_secondary_knowledge_proposal_summary(
                artifact_path=artifact_path,
                artifact=artifact,
            )
            for artifact_path, artifact in _iter_secondary_knowledge_proposal_files(output)
            if str(artifact.get("candidate_key") or artifact_path.stem) not in formal_knowledge_keys
        )
        knowledge.sort(key=lambda item: item["disease_name"])
        return 200, {"knowledge": knowledge, "count": len(knowledge)}

    prefix = "/v1/knowledge/"
    remainder = _remove_prefix(route_path, prefix).strip("/")
    parts = remainder.split("/") if remainder else []
    if not parts:
        return 404, {"error": "not found"}
    knowledge_key = parts[0]
    if knowledge_key.startswith("proposal:"):
        candidate_key = _remove_prefix(knowledge_key, "proposal:")
        if not _is_safe_knowledge_key(candidate_key):
            return 404, {"error": "not found"}
        if method == "GET" and len(parts) == 1:
            try:
                artifact_path, artifact = _load_secondary_knowledge_proposal(
                    candidate_key=candidate_key,
                    output_root=output,
                )
            except FileNotFoundError as exc:
                return 404, {"error": str(exc)}
            proposal_knowledge = artifact.get("proposal_knowledge") or {}
            if not isinstance(proposal_knowledge, dict) or not proposal_knowledge:
                return 404, {"error": f"proposal knowledge not found: {candidate_key}"}
            proposal_knowledge = json.loads(json.dumps(proposal_knowledge, ensure_ascii=False))
            proposal_knowledge.setdefault("disease_name", artifact.get("disease_name") or candidate_key)
            return 200, {
                "knowledge_key": f"proposal:{candidate_key}",
                "candidate_key": candidate_key,
                "proposal_artifact_path": str(artifact_path),
                "doctor_view": _doctor_knowledge_view(proposal_knowledge),
                "draft": _latest_knowledge_review_draft(
                    knowledge_key=f"proposal_{candidate_key}",
                    output_root=output,
                ),
                "raw_knowledge_available": True,
                "proposal_status": artifact.get("proposal_status") or "proposal_only",
                "review_queue_status": artifact.get("review_queue_status"),
                "formal_knowledge_updated": artifact.get("formal_knowledge_updated") is True,
            }
        if method == "POST" and len(parts) == 2 and parts[1] == "review-draft":
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except json.JSONDecodeError as exc:
                return 400, {"error": f"invalid json: {exc}"}
            try:
                _artifact_path, artifact = _load_secondary_knowledge_proposal(
                    candidate_key=candidate_key,
                    output_root=output,
                )
            except FileNotFoundError as exc:
                return 404, {"error": str(exc)}
            proposal_knowledge = artifact.get("proposal_knowledge") or {}
            if not isinstance(proposal_knowledge, dict) or not proposal_knowledge:
                return 404, {"error": f"proposal knowledge not found: {candidate_key}"}
            proposal_knowledge = json.loads(json.dumps(proposal_knowledge, ensure_ascii=False))
            proposal_knowledge.setdefault("disease_name", artifact.get("disease_name") or candidate_key)
            draft = _save_knowledge_review_draft(
                knowledge_key=f"proposal_{candidate_key}",
                knowledge=proposal_knowledge,
                payload=payload,
                output_root=output,
            )
            draft["knowledge_key"] = f"proposal:{candidate_key}"
            return 200, draft
        if method == "POST" and len(parts) == 2 and parts[1] == "promote":
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except json.JSONDecodeError as exc:
                return 400, {"error": f"invalid json: {exc}"}
            try:
                return 200, _promote_secondary_knowledge_proposal(
                    candidate_key=candidate_key,
                    payload=payload,
                    knowledges_dir=knowledges_root,
                    output_root=output,
                )
            except FileNotFoundError as exc:
                return 404, {"error": str(exc)}
            except FileExistsError as exc:
                return 409, {"error": str(exc)}
            except ValueError as exc:
                return 400, {"error": str(exc)}
        return 404, {"error": "not found"}
    if not _is_safe_knowledge_key(knowledge_key):
        return 404, {"error": "not found"}
    try:
        knowledge_path, knowledge = _load_knowledge_file(knowledge_key=knowledge_key, knowledges_dir=knowledges_root)
    except FileNotFoundError:
        return 404, {"error": f"knowledge not found: {knowledge_key}"}

    if method == "GET" and len(parts) == 1:
        return 200, {
            "knowledge_key": knowledge_key,
            "knowledge_path": str(knowledge_path),
            "doctor_view": _doctor_knowledge_view(knowledge),
            "draft": _latest_knowledge_review_draft(knowledge_key=knowledge_key, output_root=output),
            "raw_knowledge_available": True,
        }
    if method == "GET" and len(parts) == 2 and parts[1] == "comparison":
        return 200, _knowledge_protocol_comparison(
            knowledge_key=knowledge_key,
            current_knowledge=knowledge,
            knowledges_dir=knowledges_root,
            output_root=output,
        )
    if method == "POST" and len(parts) == 2 and parts[1] == "review-draft":
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError as exc:
            return 400, {"error": f"invalid json: {exc}"}
        return 200, _save_knowledge_review_draft(
            knowledge_key=knowledge_key,
            knowledge=knowledge,
            payload=payload,
            output_root=output,
        )
    return 404, {"error": "not found"}


def _iter_knowledge_files(knowledges_dir: Path) -> list[tuple[Path, dict]]:
    if not knowledges_dir.exists():
        return []
    loaded: list[tuple[Path, dict]] = []
    for knowledge_path in sorted(knowledges_dir.glob("*.yaml")):
        try:
            loaded.append((knowledge_path, json.loads(knowledge_path.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            continue
    return loaded


def _iter_secondary_knowledge_proposal_files(output_root: Path) -> list[tuple[Path, dict]]:
    proposal_dir = output_root / "fake" / "secondary_knowledge_proposals"
    if not proposal_dir.exists():
        return []
    loaded: list[tuple[Path, dict]] = []
    for proposal_path in sorted(proposal_dir.glob("*.json")):
        try:
            artifact = json.loads(proposal_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if artifact.get("schema_version") != "secondary_knowledge_proposal.v1":
            continue
        loaded.append((proposal_path, artifact))
    return loaded


def _load_secondary_knowledge_proposal(*, candidate_key: str, output_root: Path) -> tuple[Path, dict]:
    proposal_path = output_root / "fake" / "secondary_knowledge_proposals" / f"{candidate_key}.json"
    if not proposal_path.exists():
        raise FileNotFoundError(f"proposal not found: {candidate_key}")
    artifact = json.loads(proposal_path.read_text(encoding="utf-8"))
    if artifact.get("schema_version") != "secondary_knowledge_proposal.v1":
        raise FileNotFoundError(f"proposal not found: {candidate_key}")
    return proposal_path, artifact


def _load_knowledge_file(*, knowledge_key: str, knowledges_dir: Path) -> tuple[Path, dict]:
    knowledge_path = knowledges_dir / f"{knowledge_key}.yaml"
    if not knowledge_path.exists():
        raise FileNotFoundError(knowledge_path)
    return knowledge_path, json.loads(knowledge_path.read_text(encoding="utf-8"))


def _is_safe_knowledge_key(knowledge_key: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", knowledge_key or ""))


def _doctor_knowledge_summary(*, knowledge_key: str, knowledge: dict, output_root: Path) -> dict:
    clinical = knowledge.get("clinical_features") or {}
    protocol = knowledge.get("visual_protocol") or {}
    return {
        "knowledge_key": knowledge_key,
        "disease_name": knowledge.get("disease_name") or knowledge_key,
        "knowledge_id": knowledge.get("knowledge_id"),
        "knowledge_type": knowledge.get("knowledge_type"),
        "evidence_level": knowledge.get("evidence_level"),
        "source": knowledge.get("source"),
        "doctor_summary": {
            "symptom_count": len(clinical.get("common_symptoms") or []),
            "risk_factor_count": len(clinical.get("risk_factors") or []),
            "image_requirement_count": len(knowledge.get("required_image_views") or []),
            "visual_finding_count": len(protocol.get("finding_targets") or []),
            "source_count": len(knowledge.get("source_documents") or []),
        },
        "review_status": "draft_saved"
        if _latest_knowledge_review_draft(knowledge_key=knowledge_key, output_root=output_root)["exists"]
        else "no_draft",
    }


def _doctor_secondary_knowledge_proposal_summary(
    *,
    artifact_path: Path,
    artifact: dict,
) -> dict:
    candidate_key = str(artifact.get("candidate_key") or artifact_path.stem)
    proposal_knowledge = artifact.get("proposal_knowledge") or {}
    clinical = proposal_knowledge.get("clinical_features") or {}
    protocol = proposal_knowledge.get("visual_protocol") or {}
    observation_rules = protocol.get("observation_rules") or []
    finding_targets = protocol.get("finding_targets") or []
    image_requirements = proposal_knowledge.get("required_image_views") or []
    detail = dict(artifact.get("knowledge_builder_proposal_detail") or {})
    detail.setdefault("proposal_artifact_path", str(artifact_path))
    detail.setdefault("review_queue_status", artifact.get("review_queue_status"))
    return {
        "knowledge_key": f"proposal:{candidate_key}",
        "candidate_key": candidate_key,
        "disease_name": artifact.get("disease_name") or candidate_key,
        "knowledge_id": proposal_knowledge.get("knowledge_id") or detail.get("knowledge_id"),
        "knowledge_type": proposal_knowledge.get("knowledge_type") or artifact.get("knowledge_type") or "guideline_based",
        "evidence_level": proposal_knowledge.get("evidence_level") or artifact.get("evidence_level") or "high",
        "source": proposal_knowledge.get("source") or "current_case_knowledgebuilder_proposal",
        "doctor_summary": {
            "symptom_count": len(clinical.get("common_symptoms") or []),
            "risk_factor_count": len(clinical.get("risk_factors") or []),
            "image_requirement_count": len(image_requirements),
            "visual_finding_count": len(finding_targets) or len(observation_rules),
            "source_count": len(proposal_knowledge.get("source_documents") or []),
        },
        "review_status": "proposal_only",
        "proposal_status": artifact.get("proposal_status") or "proposal_only",
        "candidate_status": artifact.get("candidate_status") or "selected_for_knowledgebuilder",
        "knowledge_builder_status": artifact.get("knowledge_builder_status") or "proposal_prepared",
        "review_queue_status": artifact.get("review_queue_status") or "entered_knowledge_review_queue",
        "selected_by_user": True,
        "diagnosis_allowed": artifact.get("diagnosis_allowed") is True,
        "formal_knowledge_updated": artifact.get("formal_knowledge_updated") is True,
        "knowledge_builder_progress": list(artifact.get("knowledge_builder_progress") or []),
        "knowledge_builder_proposal_detail": detail,
    }


def _doctor_knowledge_view(knowledge: dict) -> dict:
    clinical = knowledge.get("clinical_features") or {}
    protocol = knowledge.get("visual_protocol") or {}
    return {
        "identity": {
            "disease_name": knowledge.get("disease_name"),
            "knowledge_id": knowledge.get("knowledge_id"),
            "knowledge_type": _knowledge_type_label(knowledge.get("knowledge_type")),
            "evidence_level": _evidence_level_label(knowledge.get("evidence_level")),
            "source": knowledge.get("source"),
        },
        "clinical_profile": {
            "common_symptoms": list(clinical.get("common_symptoms") or []),
            "risk_factors": list(clinical.get("risk_factors") or []),
        },
        "imaging_requirements": [
            {"label": str(item), "review_prompt": "这个检查是否是诊断该病必须或推荐的影像？"}
            for item in knowledge.get("required_image_views") or []
        ],
        "visual_findings": _doctor_visual_findings(protocol),
        "staging_rules": _doctor_staging_rules(knowledge.get("staging_rules") or {}),
        "safety_notes": _doctor_safety_notes(protocol),
        "report_requirements": list((knowledge.get("report_requirements") or {}).get("include") or []),
        "source_documents": [
            {
                "title": document.get("title") or document.get("source_id") or "未命名来源",
                "publisher": document.get("publisher") or document.get("source_kind"),
                "url": document.get("url"),
                "evidence_note": document.get("evidence_note"),
            }
            for document in knowledge.get("source_documents") or []
            if isinstance(document, dict)
        ],
    }


def _knowledge_protocol_comparison(
    *,
    knowledge_key: str,
    current_knowledge: dict,
    knowledges_dir: Path,
    output_root: Path,
) -> dict:
    baseline_knowledge = _load_finding_list_baseline(knowledge_key=knowledge_key, knowledges_dir=knowledges_dir)
    disease_name = current_knowledge.get("disease_name") or baseline_knowledge.get("disease_name") or knowledge_key
    current_summary = _evidence_protocol_version_summary(current_knowledge)
    evaluation_summary = _knowledge_comparison_evaluation_summary(output_root)
    return {
        "schema_version": "knowledge_protocol_comparison.v1",
        "knowledge_key": knowledge_key,
        "title": f"{disease_name} Knowledge 版本对比",
        "display_policy": {
            "collapsed_by_default": True,
            "audience": "doctor_or_research_review",
            "raw_yaml_hidden": True,
            "diagnosis_accuracy_claim_allowed": False,
        },
        "versions": [
            _finding_list_version_summary(baseline_knowledge),
            current_summary,
        ],
        "comparison_takeaway": _knowledge_comparison_takeaway(current_summary, evaluation_summary),
        "evaluation_summary": evaluation_summary,
        "safety_note": "该对比只说明 protocol coverage，不等同于诊断准确率；正式诊断仍需完整 evidence bundle 和医生审核。",
    }


def _load_finding_list_baseline(*, knowledge_key: str, knowledges_dir: Path) -> dict:
    baseline_dir = knowledges_dir / "baselines"
    candidates = [
        baseline_dir / f"{knowledge_key}_finding_list_baseline_20260604.yaml",
        baseline_dir / "femoral_head_necrosis_finding_list_baseline_20260604.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    if baseline_dir.exists():
        for candidate in sorted(baseline_dir.glob("*finding_list_baseline*.yaml")):
            return json.loads(candidate.read_text(encoding="utf-8"))
    return {}


def _finding_list_version_summary(knowledge: dict) -> dict:
    visual_targets = knowledge.get("visual_targets") or {}
    finding_names = [
        str(item)
        for item in visual_targets.get("lesion_features") or []
        if item
    ]
    if not finding_names:
        finding_names = [
            str(target.get("display_name") or target.get("target"))
            for target in (knowledge.get("visual_protocol") or {}).get("finding_targets") or []
            if isinstance(target, dict)
        ]
    return {
        "version_key": "finding_list_baseline",
        "label": "版本 1：历史 finding-list baseline",
        "summary": "以影像表现清单为主，适合保留历史判断口径；但没有完整区分候选观察、候选分割、量化测量和证据不足边界。",
        "knowledge_id": knowledge.get("knowledge_id") or "finding_list_baseline",
        "finding_names": finding_names,
        "finding_count": len(finding_names),
        "has_evidence_protocol": False,
        "has_quantitative_protocol": False,
        "human_readable_limits": [
            "只能说明列出了哪些典型表现。",
            "不能清楚表达哪些证据可分割、哪些只能观察、哪些需要质量门。",
        ],
    }


def _evidence_protocol_version_summary(knowledge: dict) -> dict:
    protocol = knowledge.get("visual_protocol") or {}
    quantitative = knowledge.get("quantitative_evidence_protocol") or {}
    target_name_by_key = {
        str(target.get("target")): str(target.get("display_name") or target.get("target"))
        for target in protocol.get("finding_targets") or []
        if isinstance(target, dict) and target.get("target")
    }
    quantitative_groups = _quantification_groups(quantitative, target_name_by_key)
    quantified_targets = {
        item["target"]
        for group in quantitative_groups
        for item in group["items"]
        if item.get("target")
    }
    findings = [
        {
            "name": str(target.get("display_name") or target.get("target") or ""),
            "target": target.get("target"),
            "evidence_mode": _execution_mode_label(target.get("execution_mode")),
            "diagnosis_role": _diagnosis_usable_label(target.get("diagnosis_usable_level")),
            "needs_quantification": (
                target.get("target") in quantified_targets
                or target.get("execution_mode") == "measurement_only"
            ),
            "quantification_reason": _quantification_reason(target, target.get("target") in quantified_targets),
        }
        for target in protocol.get("finding_targets") or []
        if isinstance(target, dict)
    ]
    finding_names = [item["name"] for item in findings if item["name"]]
    measurement_names = [
        str(item.get("measurement_name") or item.get("feature_name"))
        for section_name in ("image_feature_quantification", "measurement_evidence")
        for item in quantitative.get(section_name) or []
        if isinstance(item, dict) and (item.get("measurement_name") or item.get("feature_name"))
    ]
    return {
        "version_key": "evidence_protocol_v1",
        "label": "版本 2：Evidence protocol + quantitative protocol",
        "summary": "在 finding list 基础上补充证据获取协议：哪些征象可作为候选分割、哪些仅能 VLM 观察、哪些需要几何或形态测量，以及证据不足时不能下诊断结论。",
        "knowledge_id": knowledge.get("knowledge_id") or "evidence_protocol_v1",
        "finding_names": finding_names,
        "finding_count": len(finding_names),
        "evidence_targets": findings,
        "has_evidence_protocol": bool(findings),
        "has_quantitative_protocol": bool(quantitative),
        "quantitative_items": measurement_names,
        "quantitative_item_count": len(measurement_names),
        "quantification_groups": quantitative_groups,
        "why_better_than_baseline": [
            "把影像表现拆成可执行证据：VLM 观察、候选分割、几何/形态测量和证据不足边界。",
            "把软骨下骨骨折单独建模为 X-ray 候选证据，不再混在股骨头塌陷里。",
            "把纹理/骨小梁紊乱与塌陷深度、坏死面积比例等量化入口分开管理。",
            "明确候选 mask 和探索性量化不能单独确诊，需要质量门和医生审核。",
        ],
        "human_readable_limits": [
            "候选 mask 不能自动升级为确诊证据。",
            "量化测量需要 ROI、轮廓、landmark 或质量门通过后才可用于支持判断。",
        ],
    }


def _quantification_groups(quantitative: dict, target_name_by_key: dict[str, str]) -> list[dict]:
    image_features = [
        _quantification_item(
            item=item,
            name_key="feature_name",
            target_name_by_key=target_name_by_key,
            reason="用于发现纹理紊乱、骨小梁结构紊乱等肉眼不稳定征象；当前属于探索性，不直接确诊。",
        )
        for item in quantitative.get("image_feature_quantification") or []
        if isinstance(item, dict)
    ]
    measurements = [
        _quantification_item(
            item=item,
            name_key="measurement_name",
            target_name_by_key=target_name_by_key,
            reason="用于测量塌陷深度、坏死面积比例、软骨下骨折范围或左右不对称；需要 ROI/轮廓/质量门通过后才可作为支持证据。",
        )
        for item in quantitative.get("measurement_evidence") or []
        if isinstance(item, dict)
    ]
    return [
        {
            "group_key": "image_feature_quantification",
            "label": "影像特征量化",
            "summary": "用于发现纹理紊乱、骨小梁结构紊乱、局部密度模式等不适合直接画成稳定 mask 的特征。",
            "items": image_features,
        },
        {
            "group_key": "geometric_or_morphologic_measurement",
            "label": "几何 / 形态测量",
            "summary": "用于判断塌陷程度、坏死面积比例、软骨下骨折范围、股骨头形态和左右对称性等需要量化支持的证据。",
            "items": measurements,
        },
    ]


def _quantification_item(
    *,
    item: dict,
    name_key: str,
    target_name_by_key: dict[str, str],
    reason: str,
) -> dict:
    name = str(item.get(name_key) or "")
    target = str(item.get("target") or _infer_target_from_quantification_name(name))
    staging_rule = item.get("staging_rule") if isinstance(item.get("staging_rule"), dict) else {}
    unit = str(item.get("unit") or "")
    measurement_method = str(item.get("measurement_method") or "")
    primary_metric = str(item.get("primary_metric") or "")
    calibration_required = bool(item.get("calibration_required"))
    is_primary_collapse_metric = (
        name == "maximum_femoral_head_depression_mm"
        or primary_metric == "maximum_depression_depth"
    )
    item_reason = (
        "用于 ARCO IIIA/IIIB 分层的核心指标；必须通过像素间距/标尺和 ROI/轮廓/landmark QC 后才可输出 mm。"
        if is_primary_collapse_metric
        else reason
    )
    return {
        "name": name,
        "target": target,
        "human_target": target_name_by_key.get(target, _humanize_target(target)),
        "reason": item_reason,
        "unit": unit,
        "primary_metric": primary_metric,
        "measurement_method": measurement_method,
        "calibration_required": calibration_required,
        "diagnosis_usable_level": str(item.get("diagnosis_usable_level") or ""),
        "staging_rule_summary": _staging_rule_summary(staging_rule),
        "safety_summary": _quantification_safety_summary(item),
        "is_primary_collapse_metric": is_primary_collapse_metric,
        "quality_gate": "、".join(str(value) for value in item.get("quality_requirements") or []),
        "diagnosis_boundary": "量化结果只能作为 evidence bundle 的支持项，不能替代影像证据和医生审核。",
    }


def _infer_target_from_quantification_name(name: str) -> str:
    if "subchondral_fracture" in name:
        return "subchondral_fracture"
    if "collapse" in name or "depression" in name:
        return "collapse"
    if "trabecular" in name or "texture" in name:
        return "trabecular_blurring"
    if "sclerotic" in name or "sclerosis" in name:
        return "sclerotic_band"
    if "cystic" in name:
        return "cystic_change"
    if "asymmetry" in name:
        return "bilateral_femoral_heads"
    return ""


def _staging_rule_summary(staging_rule: dict) -> str:
    if not staging_rule:
        return ""
    labels = {
        "ARCO_IIIA": "ARCO IIIA",
        "ARCO_IIIB": "ARCO IIIB",
    }
    parts = []
    for key, value in staging_rule.items():
        if value is None:
            continue
        parts.append(f"{labels.get(str(key), str(key))} {value}")
    return "；".join(parts)


def _quantification_safety_summary(item: dict) -> str:
    parts: list[str] = []
    no_calibration_policy = str(item.get("no_calibration_policy") or "")
    if no_calibration_policy:
        if "do_not_output_mm" in no_calibration_policy:
            parts.append("无 DICOM pixel spacing 或可靠标尺时不能输出 mm，只输出归一化轮廓偏差。")
        else:
            parts.append(no_calibration_policy)
    failure_policy = item.get("failure_policy")
    if isinstance(failure_policy, dict):
        if "measurement_usable=false" in str(failure_policy.get("roi_or_landmark_unreliable") or ""):
            parts.append("ROI、参考轮廓或 landmark 不可靠时 measurement_usable=false。")
        suspected = str(failure_policy.get("suspected_collapse_unmeasurable") or "")
        if suspected:
            parts.append("疑似塌陷但无法可靠测量时不能强行细分 ARCO IIIA/IIIB。")
    return " ".join(parts)


def _humanize_target(target: str) -> str:
    labels = {
        "collapse": "股骨头塌陷",
        "subchondral_fracture": "软骨下骨骨折",
        "trabecular_blurring": "骨小梁模糊或纹理紊乱",
        "sclerotic_band": "硬化带",
        "cystic_change": "囊性变",
        "sclerotic_band_or_cystic_change": "硬化带或囊性变",
        "bilateral_femoral_heads": "双侧股骨头",
    }
    return labels.get(target, target or "未标注 target")


def _quantification_reason(target: dict, has_quantitative_target: bool) -> str:
    if target.get("execution_mode") == "measurement_only":
        return "该征象主要依赖轮廓、ROI 或 landmark 测量，不能只靠候选框判断。"
    if has_quantitative_target:
        return "该征象有对应量化入口，用于评估范围、比例或纹理强度。"
    return "当前主要作为候选观察或候选分割证据。"


def _knowledge_comparison_takeaway(current_summary: dict, evaluation_summary: dict) -> dict:
    missing = evaluation_summary.get("baseline_missing_labels") or []
    coverage_text = ""
    if evaluation_summary.get("status") == "available":
        coverage_text = (
            f"真实 X-ray 标注中，新版覆盖 {evaluation_summary.get('current_coverage')}，"
            f"旧版覆盖 {evaluation_summary.get('baseline_coverage')}。"
        )
    advantages = list(current_summary.get("why_better_than_baseline") or [])
    if missing:
        advantages.insert(0, f"真实 X-ray 对比中，旧版漏掉 {'、'.join(missing)}；新版把它作为独立 evidence target。")
    return {
        "title": "新版强在哪",
        "summary": coverage_text or "新版强在把 finding list 升级为可执行 evidence protocol。",
        "advantages": advantages,
    }


def _diagnosis_usable_label(value: str | None) -> str:
    labels = {
        "candidate_support": "候选支持，不能单独确诊",
        "measurement_support": "测量支持，需质量门通过",
        "observation_only": "观察提示",
        "not_usable": "证据不足",
        "exploratory_only": "探索性，不用于诊断",
    }
    return labels.get(value or "", value or "未标注")


def _knowledge_comparison_evaluation_summary(output_root: Path) -> dict:
    evaluation_path = (
        output_root
        / "real"
        / "onfh_coco_protocol_evaluation"
        / "onfh_coco_protocol_evaluation.json"
    )
    if not evaluation_path.exists():
        return {
            "status": "missing",
            "title": "真实 X-ray protocol coverage",
            "interpretation": "尚未发现真实 X-ray protocol evaluation artifact；可先运行 ONFH COCO protocol evaluation。",
        }
    payload = json.loads(evaluation_path.read_text(encoding="utf-8"))
    total = int((payload.get("dataset") or {}).get("evaluated_annotation_count") or 0)
    aggregate = payload.get("aggregate") or {}
    current = int(aggregate.get("current_protocol_covered_annotation_count") or 0)
    baseline = int(aggregate.get("baseline_covered_annotation_count") or 0)
    missing = list((payload.get("coverage_gaps") or {}).get("baseline_missing_labels") or [])
    primary_modality = (payload.get("evaluation_scope") or {}).get("primary_modality") or "Xray"
    return {
        "status": "available",
        "title": "真实 X-ray protocol coverage",
        "primary_modality": primary_modality,
        "evaluated_annotation_count": total,
        "current_coverage": f"{current}/{total}" if total else "0/0",
        "baseline_coverage": f"{baseline}/{total}" if total else "0/0",
        "current_coverage_percent": _percent(current, total),
        "baseline_coverage_percent": _percent(baseline, total),
        "baseline_missing_labels": missing,
        "interpretation": (
            f"新版 evidence protocol 覆盖更完整：当前版本覆盖 {current}/{total} 个 X-ray 标注，"
            f"历史 finding-list baseline 覆盖 {baseline}/{total} 个；主要缺口为"
            f"{'、'.join(missing) if missing else '无明确缺口'}。"
        ),
    }


def _percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator * 100 / denominator, 1)


def _doctor_visual_findings(protocol: dict) -> list[dict]:
    findings = []
    for target in protocol.get("finding_targets") or []:
        if not isinstance(target, dict):
            continue
        findings.append(
            {
                "target": target.get("target"),
                "display_name": target.get("display_name") or target.get("target"),
                "description": target.get("description"),
                "required_modalities": list(target.get("required_modalities") or []),
                "measurements": list(target.get("measurements") or []),
                "diagnostic_role": target.get("diagnostic_role"),
                "execution_mode": target.get("execution_mode"),
                "doctor_execution_label": _execution_mode_label(target.get("execution_mode")),
            }
        )
    return findings


def _doctor_staging_rules(staging_rules: dict) -> list[dict]:
    stages = []
    for stage, rule in staging_rules.items():
        if isinstance(rule, dict):
            features = []
            for key, value in rule.items():
                if key == "description":
                    continue
                if isinstance(value, list):
                    features.extend(str(item) for item in value)
                else:
                    features.append(str(value))
            stages.append(
                {
                    "stage": str(stage),
                    "description": str(rule.get("description") or ""),
                    "features": features,
                }
            )
        else:
            stages.append({"stage": str(stage), "description": str(rule), "features": []})
    return stages


def _doctor_safety_notes(protocol: dict) -> list[dict]:
    notes = []
    for rule in protocol.get("insufficiency_rules") or []:
        if isinstance(rule, dict):
            notes.append(
                {
                    "condition": rule.get("condition"),
                    "status": rule.get("status") or "insufficient_evidence",
                    "reason": rule.get("reason"),
                }
            )
    for item in protocol.get("required_next_images") or []:
        if isinstance(item, dict):
            notes.append(
                {
                    "condition": "需要补充影像",
                    "status": "required_next_image",
                    "reason": item.get("reason"),
                    "modality": item.get("modality"),
                    "region": item.get("region"),
                }
            )
    return notes


def _knowledge_type_label(value: object) -> str:
    labels = {
        "guideline_based": "正式指南 Knowledge",
        "data_mined_hypothesis": "数据挖掘假设 Knowledge",
    }
    return labels.get(str(value), str(value or "未标注"))


def _evidence_level_label(value: object) -> str:
    labels = {"high": "高", "medium": "中", "low": "低"}
    return labels.get(str(value), str(value or "未标注"))


def _execution_mode_label(value: object) -> str:
    labels = {
        "vlm_only": "只做视觉观察，不生成分割 mask",
        "vlm_plus_segmenter": "先定位候选区域，再生成候选分割",
        "specialist_segmenter": "使用专病分割模型",
        "measurement_only": "只做形态或数值测量",
        "insufficient_input": "当前影像不足，不能执行",
    }
    return labels.get(str(value), "按当前工具计划处理")


def _latest_knowledge_review_draft(*, knowledge_key: str, output_root: Path) -> dict:
    draft_dir = output_root / "fake" / "knowledge_review_drafts"
    drafts = sorted(draft_dir.glob(f"{knowledge_key}_*.json")) if draft_dir.exists() else []
    if not drafts:
        return {"exists": False}
    latest = drafts[-1]
    return {"exists": True, "draft_path": str(latest), "updated_at": _remove_prefix(latest.stem, f"{knowledge_key}_")}


def _save_knowledge_review_draft(
    *,
    knowledge_key: str,
    knowledge: dict,
    payload: dict,
    output_root: Path,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("review draft payload must be an object")
    draft_dir = output_root / "fake" / "knowledge_review_drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    draft_path = draft_dir / f"{knowledge_key}_{timestamp}.json"
    draft = {
        "schema_version": "knowledge_review_draft.v1",
        "status": "draft_saved",
        "knowledge_key": knowledge_key,
        "knowledge_id": knowledge.get("knowledge_id"),
        "disease_name": knowledge.get("disease_name"),
        "reviewer_name": str(payload.get("reviewer_name") or ""),
        "sections": dict(payload.get("sections") or {}),
        "created_at": timestamp,
        "formal_knowledge_updated": False,
        "safety_note": "Draft only. Formal knowledge/*.yaml files are not modified by this route.",
    }
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "draft_saved",
        "knowledge_key": knowledge_key,
        "draft_path": str(draft_path),
        "formal_knowledge_updated": False,
        "next_step": "Human review gate must approve before updating formal knowledge files.",
    }


def _promote_secondary_knowledge_proposal(
    *,
    candidate_key: str,
    payload: dict,
    knowledges_dir: Path,
    output_root: Path,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("promotion payload must be an object")
    proposal_path = output_root / "fake" / "secondary_knowledge_proposals" / f"{candidate_key}.json"
    if not proposal_path.exists():
        raise FileNotFoundError(f"proposal not found: {candidate_key}")
    artifact = json.loads(proposal_path.read_text(encoding="utf-8"))
    if artifact.get("schema_version") != "secondary_knowledge_proposal.v1":
        raise ValueError("proposal artifact schema is not secondary_knowledge_proposal.v1")
    proposal_knowledge = artifact.get("proposal_knowledge")
    if not isinstance(proposal_knowledge, dict) or not proposal_knowledge:
        raise ValueError("proposal artifact has no proposal_knowledge")
    knowledge_path = knowledges_dir / f"{candidate_key}.yaml"
    if knowledge_path.exists() and payload.get("overwrite") is not True:
        raise FileExistsError(f"formal knowledge already exists: {candidate_key}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    reviewer_name = str(payload.get("reviewer_name") or "")
    draft_knowledge = json.loads(json.dumps(proposal_knowledge, ensure_ascii=False))
    draft_knowledge.setdefault("disease_name", artifact.get("disease_name") or candidate_key)
    draft_knowledge.setdefault(
        "knowledge_id",
        artifact.get("knowledge_builder_proposal_detail", {}).get("knowledge_id")
        or f"{candidate_key}_v0.1",
    )
    formal_knowledge = normalize_guideline_knowledge_draft(
        knowledge=draft_knowledge,
        disease_key=candidate_key,
        promoted_from=str(proposal_path),
        promoted_by=reviewer_name,
        promoted_at=timestamp,
    )
    diagnosis_rules = dict(formal_knowledge.get("diagnosis_rules") or {})
    diagnosis_rules.setdefault("diagnosis_allowed_without_review", False)
    formal_knowledge["diagnosis_rules"] = diagnosis_rules
    formal_knowledge["promotion_record"] = {
        "schema_version": "knowledge_promotion_record.v1",
        "source_artifact": str(proposal_path),
        "reviewer_name": reviewer_name,
        "created_at": timestamp,
        "note": str(payload.get("review_note") or "Promoted from KnowledgeBuilder proposal for reusable formal knowledge review."),
    }

    knowledges_dir.mkdir(parents=True, exist_ok=True)
    knowledge_path.write_text(json.dumps(formal_knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "formal_knowledge_saved",
        "knowledge_key": candidate_key,
        "knowledge_path": str(knowledge_path),
        "formal_knowledge_updated": True,
        "review_status": "needs_review",
        "next_step": "Formal knowledge file is reusable but remains needs_review until doctor validation.",
    }


def dispatch_http_request(
    method: str,
    path: str,
    body: bytes = b"",
    service_factory: Callable[[], MedScopeService] | None = None,
    memory_factory: Callable[[], MemoryManager] | None = None,
) -> tuple[int, dict]:
    factory = service_factory or MedScopeService
    editor_status, editor_payload = dispatch_knowledge_editor_api_request(
        method=method,
        path=path,
        body=body,
    )
    if editor_status is not None:
        return editor_status, editor_payload
    demo_status, demo_payload = dispatch_demo_request(method=method, path=path, body=body)
    if demo_status is not None:
        return demo_status, demo_payload
    knowledge_status, knowledge_payload = dispatch_knowledge_request(method=method, path=path, body=body)
    if knowledge_status is not None:
        return knowledge_status, knowledge_payload
    memory_status, memory_payload = dispatch_memory_request(
        method=method,
        path=path,
        memory_factory=memory_factory,
    )
    if memory_status is not None:
        return memory_status, memory_payload
    route_path = urlparse(path).path
    if method == "GET" and route_path == "/health":
        return 200, {"status": "ok"}
    if method == "GET" and route_path == "/v1/readiness":
        return 200, build_readiness_payload()
    if route_path == "/v1/research-evidence-review":
        return dispatch_research_evidence_review_request(method=method, body=body)
    if method == "POST" and route_path == "/v1/medscope":
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
            return 200, factory().handle_request(payload)
        except json.JSONDecodeError as exc:
            return 400, {"error": f"invalid json: {exc}"}
        except MedScopeReadinessError as exc:
            return 503, exc.to_response()
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except Exception as exc:
            if _is_transient_vlm_api_error(exc):
                return 503, {
                    "error": (
                        "VLM/API 临时不可用：实时视觉证据获取时 HTTPS 连接被远端中断。"
                        "请稍后重试，或先使用预生成/安全样例继续演示。"
                    ),
                    "error_type": "vlm_api_unavailable",
                    "technical_detail": str(exc),
                    "action_items": [
                        "稍后重试实时分析，SSL EOF 通常是上游 API 或网络连接短暂中断。",
                        "检查当前 VLM/API route、API key、代理和网络是否可用。",
                        "演示时可先切换到预生成样例或安全候选验证模式，避免实时 VLM 调用中断流程。",
                    ],
                }
            return 500, {
                "error": str(exc),
                "error_type": "analysis_runtime_error",
                "action_items": [
                    "实时分析链路异常中断，请查看服务器日志或重试。",
                    "如果刚上传图片，请确认图片路径存在且 VLM/API 可用。",
                ],
            }
    if method == "POST" and route_path == "/v1/upload":
        parsed = urlparse(path)
        filename = "upload.bin"
        if parsed.query.startswith("filename="):
            filename = unquote(_remove_prefix(parsed.query, "filename="))
        return handle_file_upload(filename=filename, body=body)
    if method == "POST" and route_path == "/v1/baseline/image-prompt-knowledge":
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
            return 200, _run_image_baseline_from_payload(payload)
        except FileNotFoundError as exc:
            return 400, {"error": str(exc), "error_type": "missing_input"}
        except RuntimeError as exc:
            return 503, {
                "error": str(exc),
                "error_type": "baseline_model_not_ready",
                "action_items": [
                    "确认 docs/API_ROUTE_LOG.md 中 active_route 指向可用模型路由。",
                    "配置对应 API key 环境变量，例如 DMX_API_KEY 或 KY_API_KEY。",
                    "如果只想离线测试，请运行 scripts.image_prompt_knowledge_baseline 的单元测试或注入 fake client。",
                ],
            }
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except json.JSONDecodeError as exc:
            return 400, {"error": f"invalid json: {exc}"}
    return 404, {"error": "not found"}


def _is_transient_vlm_api_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = [
        "urlopen error",
        "unexpected_eof_while_reading",
        "eof occurred in violation of protocol",
        "ssl:",
        "connection reset",
        "connection aborted",
        "remote end closed connection",
        "temporarily unavailable",
        "timed out",
    ]
    return any(marker in text for marker in markers)


def dispatch_research_evidence_review_request(
    *,
    method: str,
    body: bytes = b"",
) -> tuple[int, dict]:
    if method not in {"GET", "POST"}:
        return 404, {"error": "not found"}
    if method == "GET":
        request = _default_research_evidence_review_request()
    else:
        try:
            request = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError as exc:
            return 400, {"error": f"invalid json: {exc}"}
    package = build_research_evidence_review_package(
        disease_key=request.get("disease_key") or "femoral_head_necrosis",
        target_knowledge_id=request.get("target_knowledge_id") or "femoral_head_necrosis_v0.1",
        modality=request.get("modality") or "MRI",
        research_question=request.get("research_question")
        or "MRI quantitative feature proposal for femoral head osteonecrosis",
        supplied_metadata=list(request.get("supplied_metadata") or []),
        supplied_texts=list(request.get("supplied_texts") or []),
        guideline_knowledge=dict(request.get("guideline_knowledge") or {}),
        pubmed_enabled=bool(request.get("pubmed_enabled", False)),
        pubmed_limit=int(request.get("pubmed_limit") or 10),
        human_review_decisions=list(request.get("human_review_decisions") or []),
        output_dir=DEFAULT_OUTPUT_ROOT / "fake" / "research_evidence_review",
    )
    package["display_policy"] = {
        "collapsed_by_default": True,
        "audience": "doctor_or_researcher_review",
        "raw_json_hidden_by_default": True,
        "research_evidence_label": "research evidence is not guideline evidence",
        "proposal_only_before_approval": True,
    }
    package["runtime_safety"].update(
        {
            "proposal_only": True,
            "formal_knowledge_updated": False,
            "diagnosis_rules_modified": False,
            "registry_updated": False,
            "promotion_requires_human_approval": True,
        }
    )
    return 200, package


def _default_research_evidence_review_request() -> dict:
    return {
        "disease_key": "femoral_head_necrosis",
        "target_knowledge_id": "femoral_head_necrosis_v0.1",
        "modality": "MRI",
        "research_question": "MRI texture disorder and necrotic area ratio as proposal-only supplemental evidence",
        "supplied_metadata": [
            {
                "source_id": "demo_onfh_texture_2025",
                "title": "MRI texture disorder score for early osteonecrosis",
                "journal": "Demo Research Review",
                "publication_year": 2025,
                "source_type": "journal article",
                "study_design": "multi center retrospective",
                "sample_size": 420,
                "population": "adult hip pain cohort",
                "modality": "MRI",
                "evidence_level": "moderate",
                "candidate_claim_type": "candidate_measurement_protocol",
                "target_protocol_section": "quantitative_evidence_protocol.image_feature_quantification",
                "abstract": "Demo metadata for review UI; not a guideline recommendation.",
            }
        ],
        "guideline_knowledge": {
            "knowledge_id": "femoral_head_necrosis_v0.1",
            "supported_modalities": ["X-ray"],
            "evidence_protocol_sections": [
                "quantitative_evidence_protocol.image_feature_quantification"
            ],
        },
    }


def _run_image_baseline_from_payload(payload: dict) -> dict:
    image_path = payload.get("image_path")
    patient_prompt = payload.get("patient_prompt") or payload.get("patient_message")
    if not image_path:
        raise ValueError("image_path is required")
    if not patient_prompt:
        raise ValueError("patient_prompt is required")
    disease_knowledge = payload.get("knowledge")
    disease_key = payload.get("disease_key")
    if disease_knowledge is None and disease_key:
        disease_knowledge = KnowledgeBuilderTool().load_guideline_knowledge(str(disease_key))
    return run_image_prompt_knowledge_baseline(
        image_path=Path(str(image_path)),
        patient_prompt=str(patient_prompt),
        disease_knowledge=disease_knowledge,
        disease_key=str(disease_key) if disease_key else None,
        output_dir=Path(DEFAULT_OUTPUT_ROOT) / "fake" / "image_prompt_knowledge_baseline",
    )


def dispatch_memory_request(
    method: str,
    path: str,
    memory_factory: Callable[[], MemoryManager] | None = None,
) -> tuple[int | None, dict]:
    if method != "GET":
        return None, {}
    parsed = urlparse(path)
    route_path = parsed.path
    if not route_path.startswith("/v1/memory/"):
        return None, {}
    memory = memory_factory() if memory_factory else MemoryManager()
    query = parse_qs(parsed.query)
    if route_path == "/v1/memory/cases":
        limit = _parse_positive_int(query.get("limit", ["20"])[0], default=20)
        return 200, {"cases": memory.list_case_summaries(limit=limit)}
    prefix = "/v1/memory/cases/"
    if not route_path.startswith(prefix):
        return 404, {"error": "not found"}
    remainder = _remove_prefix(route_path, prefix).strip("/")
    parts = remainder.split("/") if remainder else []
    if not parts or not parts[0]:
        return 404, {"error": "not found"}
    case_id = parts[0]
    action = parts[1] if len(parts) > 1 else "case"
    try:
        if action == "case":
            return 200, memory.get_case_by_id(case_id)
        if action == "replay":
            return 200, memory.build_case_replay(case_id)
        if action == "evidence-bundle":
            return 200, memory.get_evidence_bundle(case_id)
        if action == "audit":
            return 200, memory.build_audit_summary(case_id)
    except FileNotFoundError:
        return 404, {"error": f"case not found: {case_id}"}
    return 404, {"error": "not found"}


def dispatch_demo_request(
    method: str,
    path: str,
    body: bytes = b"",
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
) -> tuple[int | None, dict]:
    if method not in {"GET", "POST"}:
        return None, {}
    route_path = urlparse(path).path
    if method == "GET" and route_path == "/v1/demo/standard":
        return _read_demo_json(
            Path(output_root)
            / "fake"
            / STANDARD_DEMO_DIR_NAME
            / "standard_demo_summary.json",
            output_root=Path(output_root),
        )
    if method == "GET" and route_path == "/v1/demo/evidence-gateway-snapshot":
        return _read_demo_json(
            Path(output_root) / "fake" / "evidence_gateway_snapshot.json",
            output_root=Path(output_root),
        )
    if method == "GET" and route_path == "/v1/demo/public-safe":
        summary = run_public_safe_demo_suite(
            output_dir=Path(output_root) / "fake" / "public_safe_demo_suite",
        )
        return _build_public_safe_demo_payload(summary, output_root=Path(output_root))
    if method == "POST" and route_path == "/v1/demo/public-safe/qa":
        return _answer_public_safe_demo_qa(body=body, output_root=Path(output_root))
    real_demo_prefix = "/v1/demo/real-vlm-medsam2"
    if route_path == real_demo_prefix or route_path.startswith(f"{real_demo_prefix}/"):
        return _dispatch_real_vlm_medsam2_demo_request(
            method=method,
            route_path=route_path,
            body=body,
            output_root=Path(output_root),
        )
    prefix = "/v1/demo/standard/cases/"
    if not route_path.startswith(prefix):
        return None, {}
    remainder = _remove_prefix(route_path, prefix).strip("/")
    parts = remainder.split("/") if remainder else []
    if len(parts) != 2:
        return 404, {"error": "not found"}
    case_slug, artifact_type = parts
    if not re.fullmatch(r"[A-Za-z0-9_-]+", case_slug):
        return 404, {"error": "not found"}
    if method == "POST" and artifact_type == "qa":
        return _answer_demo_case_qa(case_slug=case_slug, body=body, output_root=Path(output_root))
    if method != "GET":
        return 404, {"error": "not found"}
    filename_template = DEMO_ARTIFACT_FILENAMES.get(artifact_type)
    if not filename_template:
        return 404, {"error": "not found"}
    artifact_path = (
        Path(output_root)
        / "fake"
        / STANDARD_DEMO_DIR_NAME
        / "cases"
        / case_slug
        / "artifacts"
        / filename_template.format(case_slug=case_slug)
    )
    status, payload = _read_demo_json(artifact_path, output_root=Path(output_root))
    if status == 200 and artifact_type == "response":
        payload = _backfill_standard_demo_response(case_slug=case_slug, payload=payload)
    return status, payload


def _dispatch_real_vlm_medsam2_demo_request(
    method: str,
    route_path: str,
    body: bytes,
    output_root: Path,
) -> tuple[int, dict]:
    prefix = "/v1/demo/real-vlm-medsam2"
    artifact_name = _remove_prefix(route_path, prefix).strip("/")
    if method == "POST" and artifact_name == "qa":
        return _answer_real_vlm_medsam2_demo_qa(body=body, output_root=output_root)
    if method == "GET" and artifact_name == "response":
        return _build_real_vlm_medsam2_demo_response(output_root=output_root)
    if method != "GET":
        return 404, {"error": "not found"}
    artifact = REAL_VLM_MEDSAM2_ARTIFACTS.get(artifact_name)
    if not artifact:
        return 404, {"error": "not found"}
    directory_name, filename = artifact
    return _read_demo_json(
        output_root / "fake" / directory_name / filename,
        output_root=output_root,
    )


def _read_real_vlm_medsam2_demo_core_artifacts(output_root: Path) -> tuple[int, dict, dict, dict]:
    summary_status, summary = _read_demo_json(
        output_root / "fake" / REAL_VLM_MEDSAM2_DIAGNOSIS_DIR_NAME / "summary.json",
        output_root=output_root,
    )
    if summary_status != 200:
        return summary_status, summary, {}, {}
    report_status, report = _read_demo_json(
        output_root / "fake" / REAL_VLM_MEDSAM2_DIAGNOSIS_DIR_NAME / "diagnosis_report.json",
        output_root=output_root,
    )
    if report_status != 200:
        return report_status, report, {}, {}
    bundle_status, bundle = _read_demo_json(
        output_root / "fake" / REAL_VLM_MEDSAM2_DIAGNOSIS_DIR_NAME / "evidence_bundle.json",
        output_root=output_root,
    )
    if bundle_status != 200:
        return bundle_status, bundle, {}, {}
    return 200, summary, report, bundle


def _build_real_vlm_medsam2_demo_response(output_root: Path) -> tuple[int, dict]:
    status, summary, report, bundle = _read_real_vlm_medsam2_demo_core_artifacts(output_root)
    if status != 200:
        return status, summary
    image_outputs = _build_real_vlm_medsam2_preview_image_outputs(
        image_outputs=bundle.get("image_outputs", {}),
        output_root=output_root,
    )
    normalized_bundle = _normalize_real_vlm_medsam2_evidence_bundle(
        summary,
        report,
        bundle,
        image_outputs_override=image_outputs,
    )
    normalized_report = _normalize_real_vlm_medsam2_demo_report(report, bundle)
    alignment_plan = _build_real_vlm_medsam2_demo_alignment_plan(summary, bundle)
    memory_replay = _build_real_vlm_medsam2_demo_memory_replay(
        question=None,
        summary=summary,
        report=normalized_report,
        bundle=bundle,
        answer=None,
    )
    visual_input_contract = _build_real_vlm_medsam2_visual_input_contract(
        normalized_bundle=normalized_bundle,
        image_outputs=image_outputs,
    )
    return 200, {
        "case_id": summary.get("case_id") or bundle.get("case_id"),
        "intent": "diagnosis",
        "demo_source": "real_vlm_medsam2_artifact",
        "reply_to_patient": summary.get("diagnostic_tendency") or normalized_report.get("diagnostic_tendency") or normalized_report.get("诊断倾向"),
        "report": normalized_report,
        "image_outputs": image_outputs,
        "visual_input_contract": visual_input_contract,
        "alignment_plan": alignment_plan,
        "evidence_bundle": normalized_bundle,
        "memory_audit": _build_real_vlm_medsam2_demo_memory_audit(
            summary=summary,
            report=normalized_report,
            bundle=bundle,
            alignment_plan=alignment_plan,
            image_outputs_override=image_outputs,
            qa_mode=False,
        ),
        "memory_replay": memory_replay,
    }


def _answer_real_vlm_medsam2_demo_qa(body: bytes | None, output_root: Path) -> tuple[int, dict]:
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError as exc:
        return 400, {"error": f"invalid json: {exc}"}
    question = str(payload.get("patient_message") or "").strip()
    if not question:
        return 400, {"error": "patient_message is required"}
    status, summary, report, bundle = _read_real_vlm_medsam2_demo_core_artifacts(output_root)
    if status != 200:
        return status, summary
    answer = _format_real_vlm_medsam2_demo_qa_answer(question, summary, report, bundle)
    image_outputs = _build_real_vlm_medsam2_preview_image_outputs(
        image_outputs=bundle.get("image_outputs", {}),
        output_root=output_root,
    )
    normalized_bundle = _normalize_real_vlm_medsam2_evidence_bundle(
        summary,
        report,
        bundle,
        image_outputs_override=image_outputs,
    )
    normalized_report = _normalize_real_vlm_medsam2_demo_report(report, bundle)
    alignment_plan = _build_real_vlm_medsam2_demo_alignment_plan(summary, bundle)
    memory_replay = _build_real_vlm_medsam2_demo_memory_replay(
        question=question,
        summary=summary,
        report=normalized_report,
        bundle=bundle,
        answer=answer,
    )
    visual_input_contract = _build_real_vlm_medsam2_visual_input_contract(
        normalized_bundle=normalized_bundle,
        image_outputs=image_outputs,
    )
    return 200, {
        "case_id": summary.get("case_id") or bundle.get("case_id"),
        "intent": "qa",
        "demo_source": "real_vlm_medsam2_artifact",
        "qa_source": "real_vlm_medsam2_demo_artifact",
        "reply_to_patient": answer,
        "report": normalized_report,
        "image_outputs": image_outputs,
        "visual_input_contract": visual_input_contract,
        "alignment_plan": alignment_plan,
        "evidence_bundle": normalized_bundle,
        "memory_audit": _build_real_vlm_medsam2_demo_memory_audit(
            summary=summary,
            report=normalized_report,
            bundle=bundle,
            alignment_plan=alignment_plan,
            image_outputs_override=image_outputs,
            qa_mode=True,
        ),
        "memory_replay": memory_replay,
    }


def _build_real_vlm_medsam2_preview_image_outputs(image_outputs: dict, output_root: Path) -> dict:
    outputs = dict(image_outputs or {})
    vlm_status, vlm_summary = _read_demo_json(
        output_root / "fake" / REAL_VLM_MEDSAM2_PROMPT_DIR_NAME / "summary.json",
        output_root=output_root,
    )
    if vlm_status == 200:
        outputs.setdefault("original_preview_path", vlm_summary.get("slice_png_path"))
        outputs.setdefault("localization_overlay_path", vlm_summary.get("bbox_overlay_path"))
    mask_path = outputs.get("mask_path")
    if not outputs.get("mask_preview_path") and _is_previewable_image_path(mask_path):
        outputs["mask_preview_path"] = mask_path
    if not outputs.get("mask_preview_path") and mask_path:
        preview_path = _generate_nifti_mask_preview_path(mask_path=mask_path, output_root=output_root)
        if preview_path:
            outputs["mask_preview_path"] = preview_path
    return {key: value for key, value in outputs.items() if value is not None}


def _is_previewable_image_path(path: object) -> bool:
    return isinstance(path, str) and path.startswith("output/") and bool(
        re.search(r"\.(png|jpe?g|webp|gif)$", path, flags=re.IGNORECASE)
    )


def _generate_nifti_mask_preview_path(mask_path: object, output_root: Path) -> str:
    if not isinstance(mask_path, str) or not mask_path.lower().endswith((".nii", ".nii.gz")):
        return ""
    resolved_mask = _resolve_artifact_input_path(mask_path, output_root=output_root)
    if not resolved_mask.exists():
        return ""
    output_dir = output_root / "fake" / REAL_VLM_MEDSAM2_SEGMENTATION_DIR_NAME
    preview_name = f"{_preview_stem(mask_path)}_mask_preview.png"
    preview_path = output_dir / preview_name
    if not preview_path.exists():
        try:
            _write_nifti_mask_preview(mask_path=resolved_mask, output_path=preview_path)
        except Exception:
            return ""
    return _public_output_path(preview_path, output_root=output_root)


def _write_nifti_mask_preview(mask_path: Path, output_path: Path) -> None:
    from PIL import Image
    from tools.nifti_mask_reader_tool import NibabelLoader

    mask_volume = NibabelLoader().load(mask_path).get_fdata()
    slice_index = _largest_nonzero_slice(mask_volume)
    mask_slice = mask_volume[:, :, slice_index]
    width = int(mask_slice.shape[0])
    height = int(mask_slice.shape[1])
    preview = Image.new("RGBA", (width, height), (15, 23, 32, 255))
    pixels = preview.load()
    for x in range(width):
        for y in range(height):
            if mask_slice[x, y] > 0:
                pixels[x, y] = (255, 77, 77, 255)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output_path)


def _largest_nonzero_slice(mask_volume: object) -> int:
    best_index = 0
    best_count = -1
    for index in range(mask_volume.shape[2]):
        count = int((mask_volume[:, :, index] > 0).sum())
        if count > best_count:
            best_index = index
            best_count = count
    return best_index


def _preview_stem(path: str) -> str:
    name = Path(path).name
    if name.endswith(".nii.gz"):
        name = _remove_suffix(name, ".nii.gz")
    else:
        name = Path(name).stem
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "mask"


def _resolve_artifact_input_path(path: str, output_root: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if path.startswith("output/"):
        return output_root.parent / path
    return PROJECT_ROOT / path


def _public_output_path(path: Path, output_root: Path) -> str:
    return f"output/{path.resolve().relative_to(output_root.resolve()).as_posix()}"


def _build_real_vlm_medsam2_visual_input_contract(
    normalized_bundle: dict,
    image_outputs: dict,
) -> dict:
    image_evidence = normalized_bundle.get("image_evidence", {})
    return {
        "image_path": image_evidence.get("image_path"),
        "modality": image_evidence.get("modality"),
        "body_part": image_evidence.get("body_part"),
        "segmentation_quality": image_evidence.get("segmentation_quality"),
        "image_outputs": image_outputs,
        "measurements": image_evidence.get("measurements", {}),
        "completeness": image_evidence.get("completeness", {}),
        "segmentation_results": image_evidence.get("segmentation_results", []),
        "visual_tool_plan": image_evidence.get("visual_tool_plan", []),
    }


def _build_real_vlm_medsam2_demo_memory_audit(
    summary: dict,
    report: dict,
    bundle: dict,
    alignment_plan: dict,
    image_outputs_override: dict | None,
    qa_mode: bool,
) -> dict:
    visual_result = bundle.get("visual_result", {})
    visual_evidence = visual_result.get("visual_evidence", {})
    image_outputs = image_outputs_override or bundle.get("image_outputs", visual_result.get("image_outputs", {}))
    visual_task_status_counts = _count_visual_task_statuses(visual_evidence.get("segmentation_results", []))
    visual_fact_usage = _build_real_vlm_medsam2_visual_fact_usage(bundle)
    case_id = summary.get("case_id") or bundle.get("case_id")
    disease_key = bundle.get("disease_key") or summary.get("disease_key") or "diffuse_glioma_brats"
    intent = "qa" if qa_mode else "diagnosis"
    qa_safety = {
        "evidence_bundle_required": True,
        "evidence_bundle_used": True,
        "evidence_bundle_used_count": 1 if qa_mode else 0,
        "qa_source": "real_vlm_medsam2_demo_artifact" if qa_mode else None,
        "llm_used_count": 0 if qa_mode else (1 if summary.get("llm_attempted") else 0),
        "fallback_count": 0,
    }
    agents_traced = [
        "GaoDoctorAgent",
        "KnowledgeBuilderAgent",
        "VisionAgent",
        "DiagnosisDoctorAgent",
        "MemoryManager",
    ] + (["GaoDoctorAgent QA"] if qa_mode else [])
    agent_io_summary = {
        "GaoDoctorAgent": {
            "input": summary.get("symptoms") or [],
            "output": "diagnosis",
            "routing_decision": {
                "selected_knowledge": disease_key,
                "selected_vision_mode": "medsam2",
                "source": "auto",
                "agent_scope": "orchestrator_api",
                "knowledge_builder_action": "load_existing_knowledge",
            },
        },
        "KnowledgeBuilderAgent": {
            "input": {"selected_knowledge": disease_key},
            "output": disease_key,
        },
        "VisionAgent": {
            "input": image_outputs.get("original_image_path") or visual_result.get("image_path"),
            "output": image_outputs,
            "selected_vision_mode": "medsam2",
            "tool": "MedSAM2",
            "prompt_tool": "VLM Prompt",
        },
        "DiagnosisDoctorAgent": {
            "input": {
                "measurements": visual_evidence.get("measurements", {}),
                "completeness": visual_evidence.get("completeness", {}),
            },
            "output": report.get("diagnostic_tendency") or report.get("诊断倾向"),
            "visual_fact_usage": visual_fact_usage,
        },
        "MemoryManager": {
            "input": {
                "case_id": case_id,
                "memory_types": ["patient_memory", "image_memory", "knowledge_memory", "reasoning_memory"],
            },
            "output": {
                "audit_status": "available",
                "evidence_bundle_status": "available",
            },
        },
    }
    if qa_mode:
        agent_io_summary["GaoDoctorAgent QA"] = {
            "input": "evidence_bundle_visual_fact_usage",
            "output": {
                "qa_source": "real_vlm_medsam2_demo_artifact",
                "evidence_bundle_used": True,
            },
        }
    ordered_agent_io_summary = {
        agent: agent_io_summary[agent]
        for agent in agents_traced
        if agent in agent_io_summary
    }
    return {
        "qa_safety": qa_safety,
        "memory_completeness": {
            "patient_memory": {"status": "demo_artifact"},
            "image_memory": {"status": "supported"},
            "knowledge_memory": {"status": "supported"},
            "reasoning_memory": {"status": "supported"},
        },
        "memory_type_details": {
            "patient_memory": {
                "patient_id": case_id,
                "intent": intent,
                "symptom_count": len(summary.get("symptoms") or []),
                "qa_history_count": 1 if qa_mode else 0,
            },
            "image_memory": {
                "original_preview_path": image_outputs.get("original_preview_path"),
                "localization_overlay_path": image_outputs.get("localization_overlay_path"),
                "overlay_path": image_outputs.get("overlay_path"),
                "mask_path": image_outputs.get("mask_path"),
                "mask_preview_path": image_outputs.get("mask_preview_path"),
                "segmentation_quality": visual_evidence.get("segmentation_quality") or "medsam2",
            },
            "knowledge_memory": {
                "selected_knowledge": disease_key,
                "used_knowledge": disease_key,
                "knowledge_type": report.get("used_knowledge", {}).get("knowledge_type") or "guideline_based",
                "analysis_status": alignment_plan.get("analysis_status"),
                "required_next_images": alignment_plan.get("required_next_images", []),
                "visual_protocol_status": "used_by_demo",
            },
            "reasoning_memory": {
                "llm_attempted": summary.get("llm_attempted"),
                "llm_fallback_reason": summary.get("llm_fallback_reason"),
                "model": summary.get("model"),
                "diagnostic_tendency": report.get("diagnostic_tendency") or report.get("诊断倾向"),
            },
        },
        "alignment_summary": {
            "analysis_status": alignment_plan.get("analysis_status"),
            "clinical_focus": alignment_plan.get("clinical_focus"),
            "required_next_images": alignment_plan.get("required_next_images", []),
            "visual_task_status_counts": visual_task_status_counts,
        },
        "visual_fact_usage": visual_fact_usage,
        "agents_traced": agents_traced,
        "trace_consistency": _build_trace_consistency(
            agents_traced=agents_traced,
            agent_io_summary=ordered_agent_io_summary,
        ),
        "agent_io_summary": ordered_agent_io_summary,
    }


def _normalize_real_vlm_medsam2_demo_report(report: dict, bundle: dict) -> dict:
    normalized = dict(report)
    visual_fact_usage = _build_real_vlm_medsam2_visual_fact_usage(bundle)
    normalized["visual_fact_usage"] = visual_fact_usage
    normalized["used_visual_facts"] = visual_fact_usage["used"]
    normalized["excluded_visual_facts"] = visual_fact_usage["excluded"]
    return normalized


def _backfill_standard_demo_response(case_slug: str, payload: dict) -> dict:
    if case_slug != "fhn_no_mask_multifinding":
        return payload
    routing = payload.get("routing_decision")
    if not isinstance(routing, dict) or routing.get("selected_knowledge") != "femoral_head_necrosis":
        return payload
    report = payload.get("report")
    if not isinstance(report, dict):
        return payload
    if report.get("target_disease_assessment") and report.get("imaging_evidence_summary"):
        return payload

    normalized = dict(payload)
    normalized_report = dict(report)
    normalized_routing = dict(routing)
    normalized_routing.setdefault("primary_hypothesis", "femoral_head_necrosis")
    normalized_routing.setdefault("initial_evidence_status", "nonspecific")
    normalized_routing.setdefault("routing_evidence_status", "nonspecific")
    normalized_routing.setdefault(
        "knowledge_search_reason",
        "Loaded legacy FHN no-mask demo as a bounded clinical hypothesis artifact.",
    )
    normalized.setdefault("routing_decision", normalized_routing)

    alignment_plan = normalized.get("alignment_plan")
    if not isinstance(alignment_plan, dict):
        alignment_plan = report.get("alignment_plan") if isinstance(report.get("alignment_plan"), dict) else {}
    visual_fact_usage = _standard_demo_visual_fact_usage(normalized, normalized_report)
    used_items = [
        _standard_demo_visual_fact_to_protocol_item(fact, diagnosis_usable=True)
        for fact in visual_fact_usage.get("used", [])
        if isinstance(fact, dict)
    ]
    nonspecific_items = [
        _standard_demo_visual_fact_to_protocol_item(fact, diagnosis_usable=False)
        for fact in visual_fact_usage.get("excluded", [])
        if isinstance(fact, dict)
    ]
    missing_items = _standard_demo_missing_items(alignment_plan)
    recommendations = _standard_demo_recommendations(normalized_report, alignment_plan)
    modality_limitations = _standard_demo_modality_limitations(normalized_report, alignment_plan)

    normalized_report.setdefault(
        "target_disease_assessment",
        {
            "target_disease": "femoral_head_necrosis",
            "evidence_status": "nonspecific" if not used_items else "supported",
            "supports_target_disease": [
                item.get("target") for item in used_items if item.get("target")
            ],
            "nonspecific_or_unusable_findings": [
                item.get("target") for item in nonspecific_items if item.get("target")
            ],
            "missing_required_evidence": [
                item.get("target") for item in missing_items if item.get("target")
            ],
        },
    )
    normalized_report.setdefault(
        "imaging_evidence_summary",
        {
            "usable_items": used_items,
            "nonspecific_items": nonspecific_items,
            "missing_items": missing_items,
        },
    )
    normalized_report.setdefault(
        "quantitative_evidence_summary",
        {
            "exploratory_features": [],
            "measurement_items": [
                item for item in used_items + nonspecific_items
                if item.get("measurements")
            ],
            "strong_quantitative_support_count": 0,
        },
    )
    normalized_report.setdefault(
        "differential_considerations",
        [
            {
                "condition": "osteoarthritis_or_degenerative_hip_disease",
                "display_name": "骨关节炎或退行性髋关节病变",
                "status": "cannot_exclude",
                "reason": "旧 demo artifact 只提供候选影像征象，不能开放式改诊断；需结合临床和影像科复核。",
            },
            {
                "condition": "post_traumatic_change",
                "display_name": "外伤后改变",
                "status": "cannot_exclude",
                "reason": "如果存在外伤史，部分非特异影像改变需要纳入鉴别。",
            },
        ],
    )
    normalized_report.setdefault(
        "clinical_context_assessment",
        {
            "provided_risk_factors": [],
            "missing_clinical_context": [
                "corticosteroid_use",
                "alcohol_use",
                "trauma_history",
            ],
            "can_confirm_without_imaging": False,
            "role": "临床风险因素只能改变怀疑程度，不能替代影像证据确诊。",
        },
    )
    normalized_report.setdefault(
        "missing_evidence",
        [
            item.get("visual_observation", {}).get("reason") or item.get("target")
            for item in missing_items
        ],
    )
    normalized_report.setdefault("modality_limitations", modality_limitations)
    normalized_report.setdefault("recommendation", recommendations)
    normalized["report"] = normalized_report
    return normalized


def _standard_demo_visual_fact_usage(payload: dict, report: dict) -> dict:
    usage = report.get("visual_fact_usage") or payload.get("visual_fact_usage")
    if isinstance(usage, dict):
        return {
            "used": list(usage.get("used") or []),
            "excluded": list(usage.get("excluded") or []),
        }
    return {
        "used": list(payload.get("used_visual_facts") or report.get("used_visual_facts") or []),
        "excluded": list(
            payload.get("excluded_visual_facts") or report.get("excluded_visual_facts") or []
        ),
    }


def _standard_demo_visual_fact_to_protocol_item(
    fact: dict,
    *,
    diagnosis_usable: bool,
) -> dict:
    target = fact.get("target") or fact.get("finding_id") or "legacy_visual_fact"
    measurements = {
        key: fact.get(key)
        for key in (
            "area_px",
            "area_ratio_in_image",
            "area_ratio_in_anatomy",
            "bbox",
            "centroid",
        )
        if fact.get(key) is not None
    }
    if measurements:
        measurements["measurement_usable"] = False
    return {
        "target": target,
        "display_name": fact.get("display_name") or target,
        "evidence_type": "visual_observation",
        "execution_mode": "vlm_plus_segmenter",
        "visual_observation": {
            "status": fact.get("status") or "candidate_present",
            "description": fact.get("summary_text") or fact.get("exclusion_reason") or "",
        },
        "segmentation": {
            "status": "legacy_demo_candidate",
            "reason": "Backfilled from pre-generated no-mask demo artifact.",
        },
        "measurements": measurements,
        "quality": {
            "status": fact.get("quality_level") or "legacy_demo",
            "qc_status": "legacy_demo_backfill",
        },
        "diagnosis_usable": diagnosis_usable,
        "diagnosis_usable_level": "candidate_support" if diagnosis_usable else "observation_only",
        "limitations": [
            "Legacy no-mask demo artifact; use for demonstration, not as independent clinical diagnosis.",
        ],
    }


def _standard_demo_missing_items(alignment_plan: dict) -> list[dict]:
    reasons = list(alignment_plan.get("insufficiency_reasons") or [])
    if not reasons:
        reasons = ["X 光不能可靠排除早期股骨头坏死；缺少 MRI 证据。"]
    return [
        {
            "target": "early_osteonecrosis_mri_evidence",
            "evidence_type": "visual_observation",
            "execution_mode": "insufficient_input",
            "visual_observation": {
                "status": "missing",
                "reason": str(reason),
            },
            "quality": {"status": "missing_input"},
            "diagnosis_usable": False,
            "diagnosis_usable_level": "not_usable",
            "limitations": ["Missing MRI evidence must not be treated as negative."],
        }
        for reason in reasons
    ]


def _standard_demo_recommendations(report: dict, alignment_plan: dict) -> list[str]:
    recommendations = [
        str(item)
        for item in report.get("建议进一步检查") or []
        if str(item).strip()
    ]
    for image in alignment_plan.get("required_next_images") or []:
        if not isinstance(image, dict):
            continue
        modality = image.get("modality") or "补充影像"
        region = image.get("region") or ""
        reason = image.get("reason") or ""
        text = f"建议完善{region} {modality} 检查".strip()
        if reason:
            text = f"{text}：{reason}"
        if text not in recommendations:
            recommendations.append(text)
    if not recommendations:
        recommendations = [
            "建议完善双髋 MRI T1/T2/STIR 检查。",
            "建议由骨科或影像科医生结合临床体征复核。",
        ]
    return recommendations


def _standard_demo_modality_limitations(report: dict, alignment_plan: dict) -> list[str]:
    limitations = [
        "单纯 X 光对早期股骨头坏死敏感性有限。",
        "X-ray only 不能可靠判断或排除 early osteonecrosis。",
    ]
    for item in report.get("不确定性说明") or []:
        text = str(item).strip()
        if text and text not in limitations:
            limitations.append(text)
    for reason in alignment_plan.get("insufficiency_reasons") or []:
        text = str(reason).strip()
        if text and text not in limitations:
            limitations.append(text)
    return limitations


def _build_real_vlm_medsam2_visual_fact_usage(bundle: dict) -> dict:
    visual_result = bundle.get("visual_result", {})
    visual_evidence = visual_result.get("visual_evidence", {})
    segmentation_results = visual_evidence.get("segmentation_results", [])
    completeness = visual_evidence.get("completeness", {})
    if not isinstance(segmentation_results, list):
        segmentation_results = []
    used = []
    excluded = []
    for result in segmentation_results:
        if not isinstance(result, dict):
            continue
        target = result.get("target") or result.get("task_name")
        measurements = result.get("measurements", {})
        if not isinstance(measurements, dict):
            measurements = {}
        fact = {
            "finding_id": target,
            "display_name": target,
            "target": target,
            "source_task": result.get("task_name"),
            "status": result.get("status"),
            "diagnosis_usable": bool(result.get("diagnosis_usable")),
            "mask_path": result.get("mask_path"),
            "overlay_path": result.get("overlay_path"),
            **measurements,
        }
        if result.get("diagnosis_usable") is True:
            fact["summary_text"] = _summarize_real_vlm_medsam2_used_visual_fact(target, measurements)
            used.append(fact)
            continue
        completeness_reason = _status_reason(completeness.get(str(target)))
        fact["exclusion_reason"] = result.get("status") or completeness_reason or "not_diagnosis_usable"
        fact["summary_text"] = completeness_reason or "This visual task was not usable for diagnosis."
        excluded.append(fact)
    return {
        "used": used,
        "excluded": excluded,
        "used_count": len(used),
        "excluded_count": len(excluded),
    }


def _summarize_real_vlm_medsam2_used_visual_fact(target: object, measurements: dict) -> str:
    if target == "whole_tumor" and measurements.get("whole_tumor_volume_ml") is not None:
        return f"whole_tumor segmentation supports volume={measurements.get('whole_tumor_volume_ml')} ml."
    return "This segmentation task produced diagnosis-usable visual evidence."


def _count_visual_task_statuses(segmentation_results: object) -> dict:
    if not isinstance(segmentation_results, list):
        return {}
    counts: dict[str, int] = {}
    for result in segmentation_results:
        if not isinstance(result, dict):
            continue
        status = str(result.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        if result.get("diagnosis_usable") is True:
            counts["runnable"] = counts.get("runnable", 0) + 1
    return counts


def _build_real_vlm_medsam2_demo_alignment_plan(summary: dict, bundle: dict) -> dict:
    visual_result = bundle.get("visual_result", {})
    visual_evidence = visual_result.get("visual_evidence", {})
    completeness = visual_evidence.get("completeness", {})
    evaluation = bundle.get("evaluation", {})
    disease_key = bundle.get("disease_key") or summary.get("disease_key") or "diffuse_glioma_brats"
    return {
        "analysis_status": "partial_evidence",
        "clinical_focus": "adult diffuse glioma imaging evidence",
        "selected_knowledge": disease_key,
        "image_context": {
            "modality": visual_result.get("modality") or "MRI",
            "body_part": visual_result.get("body_part") or "brain",
            "available_sequences": ["FLAIR"],
        },
        "suspected_conditions": [
            {
                "disease": "adult diffuse glioma",
                "reason": "VLM bbox and MedSAM2 mask support a candidate whole tumor region; complete MRI and pathology are still required.",
            }
        ],
        "visual_tasks": [
            {
                "task": "vlm_candidate_localization",
                "status": "runnable",
                "required_input": "FLAIR slice PNG",
                "reason": f"prompt_source={summary.get('prompt_source') or bundle.get('prompt_source') or '-'}",
            },
            {
                "task": "medsam2_candidate_segmentation",
                "status": "runnable",
                "required_input": "VLM bbox prompt",
                "reason": f"whole_tumor_dice={evaluation.get('whole_tumor_dice')}",
            },
        ],
        "required_next_images": [
            {"region": "brain", "modality": "T1", "reason": "Required for tumor core assessment."},
            {"region": "brain", "modality": "T1ce", "reason": "Required for enhancing tumor assessment."},
            {"region": "brain", "modality": "T2", "reason": "Required for broader edema/core assessment."},
        ],
        "insufficiency_reasons": [
            _status_reason(completeness.get("tumor_core")) or "tumor_core requires additional MRI modalities.",
            _status_reason(completeness.get("enhancing_tumor")) or "enhancing_tumor requires T1ce modality.",
            "This QA answer is constrained to the pre-generated real VLM+MedSAM2 evidence bundle.",
        ],
    }


def _build_real_vlm_medsam2_demo_memory_replay(
    question: str | None,
    summary: dict,
    report: dict,
    bundle: dict,
    answer: str | None,
) -> dict:
    visual_result = bundle.get("visual_result", {})
    visual_evidence = visual_result.get("visual_evidence", {})
    evaluation = bundle.get("evaluation", {})
    disease_key = bundle.get("disease_key") or summary.get("disease_key") or "diffuse_glioma_brats"
    visual_fact_usage = _build_real_vlm_medsam2_visual_fact_usage(bundle)
    steps = [
        {
            "agent": "GaoDoctorAgent",
            "event": "patient_intake",
            "memory_scope": "patient_memory",
            "intent": "diagnosis",
            "patient_id": summary.get("case_id") or bundle.get("case_id"),
            "symptoms": list(summary.get("symptoms") or []),
        },
        {
            "agent": "GaoDoctorAgent",
            "event": "knowledge_routing",
            "memory_scope": "knowledge_memory",
            "decision_owner": "orchestrator_api",
            "routing_decision": {
                "selected_knowledge": disease_key,
                "selected_vision_mode": "medsam2",
                "source": "auto",
                "agent_scope": "orchestrator_api",
                "knowledge_builder_action": "load_existing_knowledge",
            },
            "selected_knowledge": disease_key,
            "selected_vision_mode": "medsam2",
            "knowledge_type": report.get("used_knowledge", {}).get("knowledge_type"),
            "knowledge_builder_action": "load_existing_knowledge",
        },
        {
            "agent": "KnowledgeBuilderAgent",
            "event": "knowledge_loading",
            "memory_scope": "knowledge_memory",
            "action": "load_existing_knowledge",
            "selected_knowledge": disease_key,
            "used_knowledge": disease_key,
            "knowledge_type": report.get("used_knowledge", {}).get("knowledge_type"),
            "evidence_level": report.get("used_knowledge", {}).get("evidence_level"),
            "formal_knowledge_status": "loaded",
            "visual_protocol_status": "used_by_demo",
        },
        {
            "agent": "VisionAgent",
            "event": "vlm_prompt_generation",
            "memory_scope": "image_memory",
            "tool": "VLM Prompt",
            "segmentation_quality": "vision_model_bbox",
            "measurements": {"prompt_source": summary.get("prompt_source") or bundle.get("prompt_source")},
        },
        {
            "agent": "VisionAgent",
            "event": "visual_evidence",
            "memory_scope": "image_memory",
            "tool": "MedSAM2",
            "selected_vision_mode": "medsam2",
            "modality": visual_result.get("modality") or "MRI",
            "body_part": visual_result.get("body_part") or "brain",
            "segmentation_quality": visual_evidence.get("segmentation_quality") or "medsam2",
            "measurements": {
                **visual_evidence.get("measurements", {}),
                "whole_tumor_dice": evaluation.get("whole_tumor_dice"),
                "enhancing_tumor_dice": evaluation.get("enhancing_tumor_dice"),
            },
        },
        {
            "agent": "DiagnosisDoctorAgent",
            "event": "diagnosis_report",
            "memory_scope": "reasoning_memory",
            "diagnostic_tendency": report.get("diagnostic_tendency") or report.get("诊断倾向"),
            "uncertainty": report.get("不确定性说明"),
            "visual_fact_usage_summary": {
                "used_count": visual_fact_usage.get("used_count", 0),
                "excluded_count": visual_fact_usage.get("excluded_count", 0),
            },
            "used_visual_targets": [
                item.get("target")
                for item in visual_fact_usage.get("used", [])
                if isinstance(item, dict) and item.get("target")
            ],
            "excluded_visual_targets": [
                item.get("target")
                for item in visual_fact_usage.get("excluded", [])
                if isinstance(item, dict) and item.get("target")
            ],
        },
        {
            "agent": "MemoryManager",
            "event": "memory_audit",
            "memory_scope": "patient_memory,image_memory,knowledge_memory,reasoning_memory",
            "evidence_bundle_status": "available",
            "audit_status": "available",
            "quality_warnings": list(bundle.get("quality_warnings") or []),
        },
    ]
    if question:
        steps.append(
            {
                "agent": "GaoDoctorAgent QA",
                "event": "follow_up_qa",
                "memory_scope": "patient_memory.qa_history",
                "question": question,
                "answer": answer,
                "evidence_bundle_used": True,
                "qa_source": "real_vlm_medsam2_demo_artifact",
                "qa_evidence_scope": "evidence_bundle_visual_fact_usage",
                "visual_fact_usage_summary": {
                    "used_count": visual_fact_usage.get("used_count", 0),
                    "excluded_count": visual_fact_usage.get("excluded_count", 0),
                },
                "used_visual_targets": [
                    item.get("target")
                    for item in visual_fact_usage.get("used", [])
                    if isinstance(item, dict) and item.get("target")
                ],
                "excluded_visual_targets": [
                    item.get("target")
                    for item in visual_fact_usage.get("excluded", [])
                    if isinstance(item, dict) and item.get("target")
                ],
            }
        )
    return {
        "case_id": summary.get("case_id") or bundle.get("case_id"),
        "replay_consistency": _build_replay_consistency(steps),
        "steps": steps,
    }


def _status_reason(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("reason") or "")
    return ""


def _normalize_real_vlm_medsam2_evidence_bundle(
    summary: dict,
    report: dict,
    bundle: dict,
    image_outputs_override: dict | None = None,
) -> dict:
    visual_result = bundle.get("visual_result", {})
    visual_evidence = visual_result.get("visual_evidence", {})
    measurements = visual_evidence.get("measurements", {})
    completeness = visual_evidence.get("completeness", {})
    evaluation = bundle.get("evaluation", {})
    image_outputs = image_outputs_override or bundle.get("image_outputs", visual_result.get("image_outputs", {}))
    segmentation_results = visual_evidence.get("segmentation_results", [])
    visual_tool_plan = visual_evidence.get("visual_tool_plan", [])
    return {
        "patient_context": {
            "case_id": summary.get("case_id") or bundle.get("case_id"),
            "disease_key": bundle.get("disease_key") or summary.get("disease_key"),
            "prompt_source": bundle.get("prompt_source") or summary.get("prompt_source"),
        },
        "image_evidence": {
            "image_path": image_outputs.get("original_image_path") or visual_result.get("image_path"),
            "modality": visual_result.get("modality") or "MRI",
            "body_part": visual_result.get("body_part") or "brain",
            "image_outputs": image_outputs,
            "segmentation_quality": visual_evidence.get("segmentation_quality") or "medsam2",
            "measurements": {
                **measurements,
                "whole_tumor_dice": evaluation.get("whole_tumor_dice"),
                "tumor_core_dice": evaluation.get("tumor_core_dice"),
                "enhancing_tumor_dice": evaluation.get("enhancing_tumor_dice"),
            },
            "completeness": completeness,
            "segmentation_results": segmentation_results,
            "visual_tool_plan": visual_tool_plan,
        },
        "knowledge_evidence": {
            "selected_knowledge": bundle.get("disease_key") or summary.get("disease_key"),
            "selected_vision_mode": "medsam2",
            "knowledge_type": report.get("used_knowledge", {}).get("knowledge_type"),
            "guideline_evidence": {
                "citations": report.get("used_knowledge", {}).get("source_documents", []),
            },
        },
        "reasoning_evidence": {
            "visual_fact_usage": _build_real_vlm_medsam2_visual_fact_usage(bundle),
        },
        "quality_warnings": [
            "This QA answer is constrained to the pre-generated real VLM+MedSAM2 evidence bundle.",
            "Missing visual fields must not be interpreted as negative or zero.",
        ],
    }


def _format_real_vlm_medsam2_demo_qa_answer(
    question: str,
    summary: dict,
    report: dict,
    bundle: dict,
) -> str:
    visual_result = bundle.get("visual_result", {})
    visual_evidence = visual_result.get("visual_evidence", {})
    measurements = visual_evidence.get("measurements", {})
    completeness = visual_evidence.get("completeness", {})
    evaluation = bundle.get("evaluation", {})
    question_lower = question.lower()
    enhancing_status = completeness.get("enhancing_tumor", {})
    tumor_core_status = completeness.get("tumor_core", {})
    whole_volume = measurements.get("whole_tumor_volume_ml")
    whole_dice = evaluation.get("whole_tumor_dice")
    enhancing_dice = evaluation.get("enhancing_tumor_dice")
    if any(keyword in question_lower for keyword in ["enhancing", "t1ce", "强化", "增强", "0"]):
        reason = enhancing_status.get("reason") or "Requires T1ce modality"
        return (
            "根据当前 real VLM+MedSAM2 demo 的 evidence bundle，enhancing tumor 字段是缺失证据，"
            f"原因是：{reason}。因此不能把它解释为阴性、无强化或体积为 0。"
            f"后验 QC 中 enhancing tumor Dice={enhancing_dice} 只说明本次候选分割没有可靠覆盖增强肿瘤标签，"
            "不构成临床上的“没有增强肿瘤”结论。"
        )
    if any(keyword in question_lower for keyword in ["tumor core", "核心", "core"]):
        reason = tumor_core_status.get("reason") or "Requires additional MRI modalities"
        return (
            "根据当前 evidence bundle，tumor core 也是缺失/不充分证据，"
            f"原因是：{reason}。诊断 Agent 只能使用已支持的 whole tumor 和已明确的缺失字段，"
            "不能补写核心肿瘤体积或把缺失当作阴性。"
        )
    if any(keyword in question_lower for keyword in ["dice", "qc", "质量", "准不准", "准确"]):
        return (
            "当前样例的后验 QC 只用于演示评估："
            f"whole tumor Dice={whole_dice}，enhancing tumor Dice={enhancing_dice}。"
            "reference mask 只用于评估，不参与 VLM bbox prompt 或 MedSAM2 分割输入。"
            "因此这个样例只能证明扩展示例主线可运行，不能证明系统具备全病种临床级分割能力。"
        )
    if any(keyword in question_lower for keyword in ["体积", "volume", "whole"]):
        return (
            "当前 evidence bundle 中可用的主要量化字段是 whole tumor volume，"
            f"约为 {whole_volume} ml。tumor core 和 enhancing tumor 因模态不足被标记为 missing，"
            "不能作为数值 0 传给诊断推理。"
        )
    tendency = report.get("diagnostic_tendency") or report.get("诊断倾向") or summary.get("diagnostic_tendency")
    return (
        f"根据当前 real VLM+MedSAM2 demo evidence bundle，本例诊断倾向为：{tendency}。"
        "回答只使用已生成的 VLM bbox、MedSAM2 mask/overlay、量化测量、证据充分性和诊断报告 artifact；"
        "缺失字段不会被解释为阴性或 0。"
    )


def _answer_demo_case_qa(case_slug: str, body: bytes, output_root: Path) -> tuple[int, dict]:
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError as exc:
        return 400, {"error": f"invalid json: {exc}"}
    question = str(payload.get("patient_message") or "").strip()
    if not question:
        return 400, {"error": "patient_message is required"}
    response_status, response_payload = _read_demo_json(
        output_root
        / "fake"
        / STANDARD_DEMO_DIR_NAME
        / "cases"
        / case_slug
        / "artifacts"
        / f"{case_slug}_response.json",
        output_root=output_root,
    )
    if response_status != 200:
        return response_status, response_payload
    visual_fact_usage = _demo_visual_fact_usage(response_payload)
    answer = _format_demo_qa_answer(question, visual_fact_usage)
    memory_replay = _append_demo_qa_replay_step(
        response_payload=response_payload,
        question=question,
        answer=answer,
        visual_fact_usage=visual_fact_usage,
    )
    memory_audit = _append_demo_qa_audit_node(
        response_payload=response_payload,
        visual_fact_usage=visual_fact_usage,
    )
    return 200, {
        "case_id": response_payload.get("case_id"),
        "intent": "qa",
        "qa_source": "demo_artifact",
        "reply_to_patient": answer,
        "visual_fact_usage": visual_fact_usage,
        "evidence_bundle": response_payload.get("evidence_bundle", {}),
        "memory_audit": memory_audit,
        "memory_replay": memory_replay,
    }


def _answer_public_safe_demo_qa(body: bytes, output_root: Path) -> tuple[int, dict]:
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError as exc:
        return 400, {"error": f"invalid json: {exc}"}
    question = str(payload.get("patient_message") or "").strip()
    if not question:
        return 400, {"error": "patient_message is required"}
    summary_status, summary = _load_or_run_public_safe_demo_summary(output_root)
    if summary_status != 200:
        return summary_status, summary
    response_status, response_payload = _build_public_safe_demo_payload(
        summary,
        output_root=output_root,
    )
    if response_status != 200:
        return response_status, response_payload
    visual_fact_usage = _demo_visual_fact_usage(response_payload)
    answer = _format_public_safe_demo_qa_answer(question, visual_fact_usage)
    memory_replay = _append_demo_qa_replay_step(
        response_payload=response_payload,
        question=question,
        answer=answer,
        visual_fact_usage=visual_fact_usage,
    )
    memory_audit = _append_demo_qa_audit_node(
        response_payload=response_payload,
        visual_fact_usage=visual_fact_usage,
    )
    memory_replay["steps"][-1]["qa_source"] = "public_safe_demo_artifact"
    memory_audit["qa_safety"]["qa_source"] = "public_safe_demo_artifact"
    return 200, {
        "case_id": response_payload.get("case_id"),
        "intent": "qa",
        "demo_source": "public_safe_demo_suite",
        "qa_source": "public_safe_demo_artifact",
        "reply_to_patient": answer,
        "visual_fact_usage": visual_fact_usage,
        "evidence_bundle": response_payload.get("evidence_bundle", {}),
        "memory_audit": memory_audit,
        "memory_replay": memory_replay,
        "public_safe_demo_summary": summary,
    }


def _format_public_safe_demo_qa_answer(question: str, visual_fact_usage: dict) -> str:
    base_answer = _format_demo_qa_answer(question, visual_fact_usage)
    if "下一步" in question or "建议" in question:
        return (
            "这是 public-safe demo artifact 的追问回答，只用于演示主线。"
            "下一步演示上可以检查 evidence bundle、memory audit 和候选视觉证据是否完整；"
            "临床上不能用这张合成图做诊断或 benchmark。真实病例需要真实影像、医生审核和后续 MRI/专科评估。"
        )
    return (
        "这是 public-safe demo artifact 的追问回答，不读取实时病例 memory，"
        f"只基于本次 public-safe evidence bundle。{base_answer}"
    )


def _load_or_run_public_safe_demo_summary(output_root: Path) -> tuple[int, dict]:
    summary_path = output_root / "fake" / "public_safe_demo_suite" / "public_safe_demo_summary.json"
    status, payload = _read_demo_json(summary_path, output_root=output_root)
    if status == 200:
        return status, payload
    if status != 404:
        return status, payload
    summary = run_public_safe_demo_suite(
        output_dir=output_root / "fake" / "public_safe_demo_suite",
    )
    return 200, summary


def _append_demo_qa_replay_step(
    response_payload: dict,
    question: str,
    answer: str,
    visual_fact_usage: dict,
) -> dict:
    replay = dict(response_payload.get("memory_replay") or {})
    steps = _normalize_replay_steps_memory_scope(list(replay.get("steps") or []))
    used_targets = [
        item.get("target")
        for item in visual_fact_usage.get("used", [])
        if isinstance(item, dict) and item.get("target")
    ]
    excluded_targets = [
        item.get("target")
        for item in visual_fact_usage.get("excluded", [])
        if isinstance(item, dict) and item.get("target")
    ]
    steps.append(
        {
            "agent": "GaoDoctorAgent QA",
            "event": "follow_up_qa",
            "memory_scope": "patient_memory.qa_history",
            "question": question,
            "answer": answer,
            "evidence_bundle_used": True,
            "qa_source": "demo_artifact",
            "qa_evidence_scope": "evidence_bundle_visual_fact_usage",
            "visual_fact_usage_summary": {
                "used_count": visual_fact_usage.get("used_count", 0),
                "excluded_count": visual_fact_usage.get("excluded_count", 0),
            },
            "used_visual_targets": used_targets,
            "excluded_visual_targets": excluded_targets,
        }
    )
    replay["case_id"] = replay.get("case_id") or response_payload.get("case_id")
    replay["steps"] = steps
    replay["replay_consistency"] = _build_replay_consistency(steps)
    return replay


def _append_demo_qa_audit_node(response_payload: dict, visual_fact_usage: dict) -> dict:
    audit = dict(response_payload.get("memory_audit") or {})
    agents_traced = list(audit.get("agents_traced") or [])
    if "GaoDoctorAgent QA" not in agents_traced:
        agents_traced.append("GaoDoctorAgent QA")
    visual_fact_usage_summary = {
        "used_count": visual_fact_usage.get("used_count", 0),
        "excluded_count": visual_fact_usage.get("excluded_count", 0),
    }
    agent_io_summary = dict(audit.get("agent_io_summary") or {})
    agent_io_summary["GaoDoctorAgent QA"] = {
        "input": "evidence_bundle_visual_fact_usage",
        "output": {
            "qa_source": "demo_artifact",
            "evidence_bundle_used": True,
            "visual_fact_usage_summary": visual_fact_usage_summary,
        },
    }
    qa_safety = dict(audit.get("qa_safety") or {})
    qa_safety.update(
        {
            "evidence_bundle_required": True,
            "evidence_bundle_used": True,
            "evidence_bundle_used_count": 1,
            "qa_source": "demo_artifact",
            "visual_fact_usage_summary": visual_fact_usage_summary,
        }
    )
    audit["agents_traced"] = agents_traced
    ordered_agent_io_summary = {
        agent: agent_io_summary[agent]
        for agent in agents_traced
        if agent in agent_io_summary
    }
    audit["agent_io_summary"] = ordered_agent_io_summary
    audit["trace_consistency"] = _build_trace_consistency(
        agents_traced=agents_traced,
        agent_io_summary=ordered_agent_io_summary,
    )
    audit["qa_safety"] = qa_safety
    return audit


def _demo_visual_fact_usage(response_payload: dict) -> dict:
    return (
        response_payload.get("report", {}).get("visual_fact_usage")
        or response_payload.get("memory_audit", {}).get("visual_fact_usage")
        or response_payload.get("evidence_bundle", {})
        .get("reasoning_evidence", {})
        .get("visual_fact_usage")
        or {"used": [], "excluded": [], "used_count": 0, "excluded_count": 0}
    )


def _format_demo_qa_answer(question: str, visual_fact_usage: dict) -> str:
    used = visual_fact_usage.get("used") if isinstance(visual_fact_usage.get("used"), list) else []
    excluded = (
        visual_fact_usage.get("excluded")
        if isinstance(visual_fact_usage.get("excluded"), list)
        else []
    )
    used_labels = _format_demo_fact_labels(used)
    excluded_lines = []
    for fact in excluded:
        label = fact.get("display_name") or fact.get("target") or fact.get("finding_id") or "未命名证据"
        reason = fact.get("exclusion_reason") or fact.get("non_independent_reason") or "not_used"
        overlap = fact.get("overlap_with_finding_id")
        detail = f"{label}: {reason}"
        if overlap:
            detail += f"，与 {overlap} 重叠"
        excluded_lines.append(detail)
    if "囊性变" in question or "排除" in question or "独立" in question:
        excluded_text = "；".join(excluded_lines) or "本例没有被排除的视觉证据。"
        return (
            f"根据当前 demo evidence bundle，囊性变属于候选视觉发现，但在 visual_fact_usage 中被标记为 excluded。"
            f"排除原因：{excluded_text}。因此它不作为独立诊断依据；本次诊断主要采用的视觉证据是：{used_labels}。"
        )
    return (
        f"根据当前 demo evidence bundle，本次诊断采用证据：{used_labels}。"
        f"排除证据：{'；'.join(excluded_lines) if excluded_lines else '无'}。"
        "该回答来自预生成 demo artifact，受 visual_fact_usage 约束。"
    )


def _format_demo_fact_labels(facts: list[dict]) -> str:
    labels = []
    for fact in facts:
        name = fact.get("display_name") or fact.get("target") or fact.get("finding_id") or "未命名证据"
        side = fact.get("laterality")
        labels.append(f"{side} {name}" if side else str(name))
    return "、".join(labels) if labels else "无"


def _read_demo_json(path: Path, output_root: Path = DEFAULT_OUTPUT_ROOT) -> tuple[int, dict]:
    try:
        resolved = path.resolve()
        root = output_root.resolve()
        if root != resolved and root not in resolved.parents:
            return 404, {"error": "not found"}
        if not resolved.exists() or not resolved.is_file():
            return 404, {"error": "not found"}
        return 200, json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return 500, {"error": f"invalid demo json: {exc}"}


def _build_public_safe_demo_payload(summary: dict, output_root: Path) -> tuple[int, dict]:
    response_status, response = _read_demo_json(Path(summary["response_path"]), output_root=output_root)
    if response_status != 200:
        return response_status, response
    bundle_status, evidence_bundle = _read_demo_json(
        Path(summary["evidence_bundle_path"]),
        output_root=output_root,
    )
    if bundle_status != 200:
        return bundle_status, evidence_bundle
    audit_status, memory_audit = _read_demo_json(Path(summary["memory_audit_path"]), output_root=output_root)
    if audit_status != 200:
        return audit_status, memory_audit
    qa_status, qa_response = _read_demo_json(Path(summary["qa_response_path"]), output_root=output_root)
    if qa_status != 200:
        return qa_status, qa_response
    payload = {
        **response,
        "demo_name": summary.get("demo_name"),
        "status": summary.get("status"),
        "demo_source": "public_safe_demo_suite",
        "public_safe_demo_summary": summary,
        "safety": summary.get("safety", {}),
        "suite_output_dir": summary.get("suite_output_dir"),
        "fixture_manifest_path": summary.get("fixture_manifest_path"),
        "response_path": summary.get("response_path"),
        "evidence_bundle_path": summary.get("evidence_bundle_path"),
        "memory_audit_path": summary.get("memory_audit_path"),
        "qa_response_path": summary.get("qa_response_path"),
        "summary_path": summary.get("summary_path"),
        "summary_markdown_path": summary.get("summary_markdown_path"),
        "evidence_bundle": evidence_bundle,
        "memory_audit": memory_audit,
        "demo_qa_response": qa_response,
        "steps": summary.get("steps", {}),
    }
    return 200, payload


def _parse_positive_int(value: str, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def create_handler(service_factory: Callable[[], MedScopeService] | None = None):
    factory = service_factory or MedScopeService

    class MedScopeHttpHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            editor_status, editor_body, editor_content_type = dispatch_knowledge_editor_static_request(self.path)
            if editor_status is not None:
                self._write_bytes(editor_status, editor_body, editor_content_type)
                return
            static_status, body, content_type = dispatch_static_request(self.path)
            if static_status == 200:
                self._write_bytes(static_status, body, content_type)
                return
            binary_status, binary_body, binary_content_type = dispatch_binary_request(
                method="GET",
                path=self.path,
            )
            if binary_status == 200:
                self._write_bytes(binary_status, binary_body, binary_content_type)
                return
            status_code, payload = dispatch_http_request(
                method="GET",
                path=self.path,
                service_factory=factory,
            )
            self._write_json(status_code, payload)

        def do_POST(self) -> None:
            status_code, payload = dispatch_http_request(
                method="POST",
                path=self.path,
                body=self._read_body(),
                service_factory=factory,
            )
            self._write_json(status_code, payload)

        def do_PUT(self) -> None:
            status_code, payload = dispatch_http_request(
                method="PUT",
                path=self.path,
                body=self._read_body(),
                service_factory=factory,
            )
            self._write_json(status_code, payload)

        def do_DELETE(self) -> None:
            status_code, payload = dispatch_http_request(
                method="DELETE",
                path=self.path,
                body=self._read_body(),
                service_factory=factory,
            )
            self._write_json(status_code, payload)

        def log_message(self, format: str, *args) -> None:
            return

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0"))
            return self.rfile.read(length)

        def _write_json(self, status_code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._write_bytes(status_code, body, "application/json; charset=utf-8")

        def _write_bytes(self, status_code: int, body: bytes, content_type: str) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return MedScopeHttpHandler


def run_http_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), create_handler())
    print(f"MedScope HTTP API listening on http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MedScope HTTP API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    load_dotenv_local()
    run_http_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
