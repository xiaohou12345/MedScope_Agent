from __future__ import annotations

import argparse
import mimetypes
import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from api.service import MedScopeReadinessError, MedScopeService
from memory.memory_manager import MemoryManager
from scripts.image_prompt_skill_baseline import run_image_prompt_skill_baseline
from tools.skill_builder_tool import SkillBuilderTool


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
REPLAY_MEMORY_SCOPE_BY_EVENT = {
    "patient_intake": "patient_memory",
    "skill_routing": "skill_memory",
    "skill_loading": "skill_memory",
    "vlm_prompt_generation": "image_memory",
    "visual_evidence": "image_memory",
    "diagnosis_report": "reasoning_memory",
    "memory_audit": "patient_memory,image_memory,skill_memory,reasoning_memory",
    "follow_up_qa": "patient_memory.qa_history",
}
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


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
    relative = route_path.removeprefix("/output/")
    if not relative or ".." in Path(relative).parts:
        raise ValueError("invalid output path")
    resolved = (root / relative).resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("output path escaped root")
    return resolved


def _safe_upload_filename(filename: str) -> str:
    name = Path(filename or "upload.bin").name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "upload.bin"


def dispatch_skill_request(
    method: str,
    path: str,
    body: bytes = b"",
    skills_dir: Path | str = PROJECT_ROOT / "skills",
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
) -> tuple[int | None, dict]:
    route_path = urlparse(path).path
    if route_path != "/v1/skills" and not route_path.startswith("/v1/skills/"):
        return None, {}
    skills_root = Path(skills_dir)
    output = Path(output_root)
    if method == "GET" and route_path == "/v1/skills":
        skills = [
            _doctor_skill_summary(skill_key=skill_path.stem, skill=skill, output_root=output)
            for skill_path, skill in _iter_skill_files(skills_root)
        ]
        skills.sort(key=lambda item: item["disease_name"])
        return 200, {"skills": skills, "count": len(skills)}

    prefix = "/v1/skills/"
    remainder = route_path.removeprefix(prefix).strip("/")
    parts = remainder.split("/") if remainder else []
    if not parts or not _is_safe_skill_key(parts[0]):
        return 404, {"error": "not found"}
    skill_key = parts[0]
    try:
        skill_path, skill = _load_skill_file(skill_key=skill_key, skills_dir=skills_root)
    except FileNotFoundError:
        return 404, {"error": f"skill not found: {skill_key}"}

    if method == "GET" and len(parts) == 1:
        return 200, {
            "skill_key": skill_key,
            "skill_path": str(skill_path),
            "doctor_view": _doctor_skill_view(skill),
            "draft": _latest_skill_review_draft(skill_key=skill_key, output_root=output),
            "raw_skill_available": True,
        }
    if method == "POST" and len(parts) == 2 and parts[1] == "review-draft":
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError as exc:
            return 400, {"error": f"invalid json: {exc}"}
        return 200, _save_skill_review_draft(
            skill_key=skill_key,
            skill=skill,
            payload=payload,
            output_root=output,
        )
    return 404, {"error": "not found"}


def _iter_skill_files(skills_dir: Path) -> list[tuple[Path, dict]]:
    if not skills_dir.exists():
        return []
    loaded: list[tuple[Path, dict]] = []
    for skill_path in sorted(skills_dir.glob("*.yaml")):
        try:
            loaded.append((skill_path, json.loads(skill_path.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            continue
    return loaded


def _load_skill_file(*, skill_key: str, skills_dir: Path) -> tuple[Path, dict]:
    skill_path = skills_dir / f"{skill_key}.yaml"
    if not skill_path.exists():
        raise FileNotFoundError(skill_path)
    return skill_path, json.loads(skill_path.read_text(encoding="utf-8"))


def _is_safe_skill_key(skill_key: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", skill_key or ""))


def _doctor_skill_summary(*, skill_key: str, skill: dict, output_root: Path) -> dict:
    clinical = skill.get("clinical_features") or {}
    protocol = skill.get("visual_protocol") or {}
    return {
        "skill_key": skill_key,
        "disease_name": skill.get("disease_name") or skill_key,
        "skill_id": skill.get("skill_id"),
        "skill_type": skill.get("skill_type"),
        "evidence_level": skill.get("evidence_level"),
        "source": skill.get("source"),
        "doctor_summary": {
            "symptom_count": len(clinical.get("common_symptoms") or []),
            "risk_factor_count": len(clinical.get("risk_factors") or []),
            "image_requirement_count": len(skill.get("required_image_views") or []),
            "visual_finding_count": len(protocol.get("finding_targets") or []),
            "source_count": len(skill.get("source_documents") or []),
        },
        "review_status": "draft_saved"
        if _latest_skill_review_draft(skill_key=skill_key, output_root=output_root)["exists"]
        else "no_draft",
    }


def _doctor_skill_view(skill: dict) -> dict:
    clinical = skill.get("clinical_features") or {}
    protocol = skill.get("visual_protocol") or {}
    return {
        "identity": {
            "disease_name": skill.get("disease_name"),
            "skill_id": skill.get("skill_id"),
            "skill_type": _skill_type_label(skill.get("skill_type")),
            "evidence_level": _evidence_level_label(skill.get("evidence_level")),
            "source": skill.get("source"),
        },
        "clinical_profile": {
            "common_symptoms": list(clinical.get("common_symptoms") or []),
            "risk_factors": list(clinical.get("risk_factors") or []),
        },
        "imaging_requirements": [
            {"label": str(item), "review_prompt": "这个检查是否是诊断该病必须或推荐的影像？"}
            for item in skill.get("required_image_views") or []
        ],
        "visual_findings": _doctor_visual_findings(protocol),
        "staging_rules": _doctor_staging_rules(skill.get("staging_rules") or {}),
        "safety_notes": _doctor_safety_notes(protocol),
        "report_requirements": list((skill.get("report_requirements") or {}).get("include") or []),
        "source_documents": [
            {
                "title": document.get("title") or document.get("source_id") or "未命名来源",
                "publisher": document.get("publisher") or document.get("source_kind"),
                "url": document.get("url"),
                "evidence_note": document.get("evidence_note"),
            }
            for document in skill.get("source_documents") or []
            if isinstance(document, dict)
        ],
    }


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


def _skill_type_label(value: object) -> str:
    labels = {
        "guideline_based": "正式指南 Skill",
        "data_mined_hypothesis": "数据挖掘假设 Skill",
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


def _latest_skill_review_draft(*, skill_key: str, output_root: Path) -> dict:
    draft_dir = output_root / "fake" / "skill_review_drafts"
    drafts = sorted(draft_dir.glob(f"{skill_key}_*.json")) if draft_dir.exists() else []
    if not drafts:
        return {"exists": False}
    latest = drafts[-1]
    return {"exists": True, "draft_path": str(latest), "updated_at": latest.stem.removeprefix(f"{skill_key}_")}


def _save_skill_review_draft(
    *,
    skill_key: str,
    skill: dict,
    payload: dict,
    output_root: Path,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("review draft payload must be an object")
    draft_dir = output_root / "fake" / "skill_review_drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    draft_path = draft_dir / f"{skill_key}_{timestamp}.json"
    draft = {
        "schema_version": "skill_review_draft.v1",
        "status": "draft_saved",
        "skill_key": skill_key,
        "skill_id": skill.get("skill_id"),
        "disease_name": skill.get("disease_name"),
        "reviewer_name": str(payload.get("reviewer_name") or ""),
        "sections": dict(payload.get("sections") or {}),
        "created_at": timestamp,
        "formal_skill_updated": False,
        "safety_note": "Draft only. Formal skills/*.yaml files are not modified by this route.",
    }
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "draft_saved",
        "skill_key": skill_key,
        "draft_path": str(draft_path),
        "formal_skill_updated": False,
        "next_step": "Human review gate must approve before updating formal skill files.",
    }


def dispatch_http_request(
    method: str,
    path: str,
    body: bytes = b"",
    service_factory: Callable[[], MedScopeService] | None = None,
    memory_factory: Callable[[], MemoryManager] | None = None,
) -> tuple[int, dict]:
    factory = service_factory or MedScopeService
    demo_status, demo_payload = dispatch_demo_request(method=method, path=path, body=body)
    if demo_status is not None:
        return demo_status, demo_payload
    skill_status, skill_payload = dispatch_skill_request(method=method, path=path, body=body)
    if skill_status is not None:
        return skill_status, skill_payload
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
    if method == "POST" and route_path == "/v1/medscope":
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
            return 200, factory().handle_request(payload)
        except MedScopeReadinessError as exc:
            return 503, exc.to_response()
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except json.JSONDecodeError as exc:
            return 400, {"error": f"invalid json: {exc}"}
    if method == "POST" and route_path == "/v1/upload":
        parsed = urlparse(path)
        filename = "upload.bin"
        if parsed.query.startswith("filename="):
            filename = parsed.query.removeprefix("filename=")
        return handle_file_upload(filename=filename, body=body)
    if method == "POST" and route_path == "/v1/baseline/image-prompt-skill":
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
                    "如果只想离线测试，请运行 scripts.image_prompt_skill_baseline 的单元测试或注入 fake client。",
                ],
            }
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except json.JSONDecodeError as exc:
            return 400, {"error": f"invalid json: {exc}"}
    return 404, {"error": "not found"}


def _run_image_baseline_from_payload(payload: dict) -> dict:
    image_path = payload.get("image_path")
    patient_prompt = payload.get("patient_prompt") or payload.get("patient_message")
    if not image_path:
        raise ValueError("image_path is required")
    if not patient_prompt:
        raise ValueError("patient_prompt is required")
    disease_skill = payload.get("skill")
    disease_key = payload.get("disease_key")
    if disease_skill is None and disease_key:
        disease_skill = SkillBuilderTool().load_guideline_skill(str(disease_key))
    return run_image_prompt_skill_baseline(
        image_path=Path(str(image_path)),
        patient_prompt=str(patient_prompt),
        disease_skill=disease_skill,
        disease_key=str(disease_key) if disease_key else None,
        output_dir=Path(DEFAULT_OUTPUT_ROOT) / "fake" / "image_prompt_skill_baseline",
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
    remainder = route_path.removeprefix(prefix).strip("/")
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
    remainder = route_path.removeprefix(prefix).strip("/")
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
    return _read_demo_json(artifact_path, output_root=Path(output_root))


def _dispatch_real_vlm_medsam2_demo_request(
    method: str,
    route_path: str,
    body: bytes,
    output_root: Path,
) -> tuple[int, dict]:
    prefix = "/v1/demo/real-vlm-medsam2"
    artifact_name = route_path.removeprefix(prefix).strip("/")
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
        name = name.removesuffix(".nii.gz")
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
        "SkillBuilderAgent",
        "VisionAgent",
        "DiagnosisDoctorAgent",
        "MemoryManager",
    ] + (["GaoDoctorAgent QA"] if qa_mode else [])
    agent_io_summary = {
        "GaoDoctorAgent": {
            "input": summary.get("symptoms") or [],
            "output": "diagnosis",
            "routing_decision": {
                "selected_skill": disease_key,
                "selected_vision_mode": "medsam2",
                "source": "auto",
                "agent_scope": "orchestrator_api",
                "skill_builder_action": "load_existing_skill",
            },
        },
        "SkillBuilderAgent": {
            "input": {"selected_skill": disease_key},
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
                "memory_types": ["patient_memory", "image_memory", "skill_memory", "reasoning_memory"],
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
            "skill_memory": {"status": "supported"},
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
            "skill_memory": {
                "selected_skill": disease_key,
                "used_skill": disease_key,
                "skill_type": report.get("used_skill", {}).get("skill_type") or "guideline_based",
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
        "selected_skill": disease_key,
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
            "event": "skill_routing",
            "memory_scope": "skill_memory",
            "decision_owner": "orchestrator_api",
            "routing_decision": {
                "selected_skill": disease_key,
                "selected_vision_mode": "medsam2",
                "source": "auto",
                "agent_scope": "orchestrator_api",
                "skill_builder_action": "load_existing_skill",
            },
            "selected_skill": disease_key,
            "selected_vision_mode": "medsam2",
            "skill_type": report.get("used_skill", {}).get("skill_type"),
            "skill_builder_action": "load_existing_skill",
        },
        {
            "agent": "SkillBuilderAgent",
            "event": "skill_loading",
            "memory_scope": "skill_memory",
            "action": "load_existing_skill",
            "selected_skill": disease_key,
            "used_skill": disease_key,
            "skill_type": report.get("used_skill", {}).get("skill_type"),
            "evidence_level": report.get("used_skill", {}).get("evidence_level"),
            "formal_skill_status": "loaded",
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
            "memory_scope": "patient_memory,image_memory,skill_memory,reasoning_memory",
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
        "skill_evidence": {
            "selected_skill": bundle.get("disease_key") or summary.get("disease_key"),
            "selected_vision_mode": "medsam2",
            "skill_type": report.get("used_skill", {}).get("skill_type"),
            "guideline_evidence": {
                "citations": report.get("used_skill", {}).get("source_documents", []),
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
            "因此这个样例能证明主线可运行，但不能证明通用临床级分割已经完成。"
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
