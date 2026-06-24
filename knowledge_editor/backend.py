from __future__ import annotations

import json
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


EDITOR_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = EDITOR_ROOT.parent
KNOWLEDGES_DIR = PROJECT_ROOT / "knowledge"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
VERSION_ROOT = PROJECT_ROOT / "output" / "knowledge_editor_versions"

STATIC_FILES = {
    "/knowledge-editor": "index.html",
    "/knowledge-editor/": "index.html",
    "/knowledge-editor/app.js": "app.js",
    "/knowledge-editor/styles.css": "styles.css",
}


def _remove_prefix(value: str, prefix: str) -> str:
    return value[len(prefix) :] if value.startswith(prefix) else value


def _remove_suffix(value: str, suffix: str) -> str:
    return value[: -len(suffix)] if suffix and value.endswith(suffix) else value


def dispatch_knowledge_editor_static_request(path: str) -> tuple[int | None, bytes, str]:
    route_path = urlparse(path).path
    filename = STATIC_FILES.get(route_path)
    if not filename:
        return None, b"", ""
    file_path = EDITOR_ROOT / filename
    if not file_path.exists():
        return 404, b"not found", "text/plain; charset=utf-8"
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    if file_path.suffix == ".html":
        content_type = "text/html; charset=utf-8"
    elif file_path.suffix == ".css":
        content_type = "text/css; charset=utf-8"
    elif file_path.suffix == ".js":
        content_type = "application/javascript; charset=utf-8"
    return 200, file_path.read_bytes(), content_type


def dispatch_knowledge_editor_api_request(
    method: str,
    path: str,
    body: bytes = b"",
    *,
    knowledges_dir: Path | str = KNOWLEDGES_DIR,
    prompts_dir: Path | str = PROMPTS_DIR,
    version_root: Path | str = VERSION_ROOT,
) -> tuple[int | None, dict]:
    route_path = urlparse(path).path
    if route_path == "/knowledge-editor/api/health":
        return 200, {"status": "ok"}
    try:
        if route_path == "/knowledge-editor/api/knowledge" or route_path.startswith("/knowledge-editor/api/knowledge/"):
            return _dispatch_knowledge_api(
                method=method,
                route_path=route_path,
                body=body,
                knowledges_dir=Path(knowledges_dir),
                version_root=Path(version_root),
            )
        if route_path == "/knowledge-editor/api/prompts" or route_path.startswith("/knowledge-editor/api/prompts/"):
            return _dispatch_prompt_api(
                method=method,
                route_path=route_path,
                body=body,
                prompts_dir=Path(prompts_dir),
                version_root=Path(version_root),
            )
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return None, {}


def _dispatch_knowledge_api(
    *,
    method: str,
    route_path: str,
    body: bytes,
    knowledges_dir: Path,
    version_root: Path,
) -> tuple[int, dict]:
    if method == "GET" and route_path == "/knowledge-editor/api/knowledge":
        knowledge = [
            _knowledge_summary(knowledge_key=path.stem, knowledge=_read_knowledge(path), version_root=version_root)
            for path in sorted(knowledges_dir.glob("*.yaml"))
            if _can_read_json(path)
        ] if knowledges_dir.exists() else []
        knowledge.sort(key=lambda item: item["title"])
        return 200, {"knowledge": knowledge}

    if method == "POST" and route_path == "/knowledge-editor/api/knowledge":
        payload = _json_body(body)
        knowledge_key = _safe_key(payload.get("knowledge_key") or payload.get("name") or "new_knowledge")
        knowledges_dir.mkdir(parents=True, exist_ok=True)
        knowledge_path = knowledges_dir / f"{knowledge_key}.yaml"
        if knowledge_path.exists():
            return 409, {"error": f"knowledge already exists: {knowledge_key}"}
        knowledge = _new_knowledge(knowledge_key=knowledge_key, payload=payload)
        knowledge_path.write_text(_json_text(knowledge), encoding="utf-8")
        _save_version(
            kind="knowledge",
            document_key=knowledge_key,
            content=knowledge,
            author=str(payload.get("author") or "系统"),
            note=str(payload.get("note") or "创建 knowledge"),
            action="create",
            version_root=version_root,
        )
        return 200, _knowledge_detail(knowledge_key=knowledge_key, knowledge_path=knowledge_path, version_root=version_root)

    knowledge_key, suffix = _split_document_route(route_path, "/knowledge-editor/api/knowledge/")
    if not knowledge_key:
        return 404, {"error": "not found"}
    knowledge_path = knowledges_dir / f"{knowledge_key}.yaml"
    if not knowledge_path.exists():
        return 404, {"error": f"knowledge not found: {knowledge_key}"}

    if method == "GET" and not suffix:
        return 200, _knowledge_detail(knowledge_key=knowledge_key, knowledge_path=knowledge_path, version_root=version_root)
    if method == "GET" and suffix == "versions":
        return 200, {"versions": _list_versions(kind="knowledge", document_key=knowledge_key, version_root=version_root)}
    if method == "GET" and suffix.startswith("versions/"):
        version_id = _remove_prefix(suffix, "versions/")
        return _version_response(kind="knowledge", document_key=knowledge_key, version_id=version_id, version_root=version_root)
    if method == "POST" and suffix.startswith("versions/") and suffix.endswith("/restore"):
        version_id = _remove_suffix(_remove_prefix(suffix, "versions/"), "/restore").strip("/")
        status, payload = _version_response(
            kind="knowledge",
            document_key=knowledge_key,
            version_id=version_id,
            version_root=version_root,
        )
        if status != 200:
            return status, payload
        knowledge = payload["version"]["content"]
        knowledge_path.write_text(_json_text(knowledge), encoding="utf-8")
        request = _json_body(body) if body else {}
        _save_version(
            kind="knowledge",
            document_key=knowledge_key,
            content=knowledge,
            author=str(request.get("author") or "系统"),
            note=f"恢复版本 {version_id}",
            action="restore",
            version_root=version_root,
        )
        return 200, _knowledge_detail(knowledge_key=knowledge_key, knowledge_path=knowledge_path, version_root=version_root)
    if method == "PUT" and not suffix:
        payload = _json_body(body)
        current = _read_knowledge(knowledge_path)
        updated = _apply_knowledge_editor_payload(current, payload)
        knowledge_path.write_text(_json_text(updated), encoding="utf-8")
        _save_version(
            kind="knowledge",
            document_key=knowledge_key,
            content=updated,
            author=str(payload.get("author") or "未填写"),
            note=str(payload.get("note") or "医生修改 knowledge"),
            action="update",
            version_root=version_root,
        )
        return 200, _knowledge_detail(knowledge_key=knowledge_key, knowledge_path=knowledge_path, version_root=version_root)
    if method == "DELETE" and not suffix:
        payload = _json_body(body) if body else {}
        current = _read_knowledge(knowledge_path)
        _save_version(
            kind="knowledge",
            document_key=knowledge_key,
            content=current,
            author=str(payload.get("author") or "未填写"),
            note=str(payload.get("note") or "删除前快照"),
            action="delete",
            version_root=version_root,
        )
        knowledge_path.unlink()
        return 200, {"status": "deleted", "knowledge_key": knowledge_key}
    return 404, {"error": "not found"}


def _dispatch_prompt_api(
    *,
    method: str,
    route_path: str,
    body: bytes,
    prompts_dir: Path,
    version_root: Path,
) -> tuple[int, dict]:
    if method == "GET" and route_path == "/knowledge-editor/api/prompts":
        prompts = [
            _prompt_summary(prompt_path=path, version_root=version_root)
            for path in sorted(prompts_dir.glob("*.md"))
        ] if prompts_dir.exists() else []
        return 200, {"prompts": prompts}

    if method == "POST" and route_path == "/knowledge-editor/api/prompts":
        payload = _json_body(body)
        prompt_key = _safe_key(payload.get("prompt_key") or payload.get("name") or "new_prompt")
        prompts_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = prompts_dir / f"{prompt_key}.md"
        if prompt_path.exists():
            return 409, {"error": f"prompt already exists: {prompt_key}"}
        markdown = str(payload.get("markdown") or "你是某个 Agent，负责...\n\n要求：\n- \n")
        prompt_path.write_text(markdown, encoding="utf-8")
        _save_version(
            kind="prompts",
            document_key=prompt_key,
            content={"markdown": markdown},
            author=str(payload.get("author") or "系统"),
            note=str(payload.get("note") or "创建 prompt"),
            action="create",
            version_root=version_root,
        )
        return 200, _prompt_detail(prompt_key=prompt_key, prompt_path=prompt_path, version_root=version_root)

    prompt_key, suffix = _split_document_route(route_path, "/knowledge-editor/api/prompts/")
    if not prompt_key:
        return 404, {"error": "not found"}
    prompt_path = prompts_dir / f"{prompt_key}.md"
    if not prompt_path.exists():
        return 404, {"error": f"prompt not found: {prompt_key}"}

    if method == "GET" and not suffix:
        return 200, _prompt_detail(prompt_key=prompt_key, prompt_path=prompt_path, version_root=version_root)
    if method == "GET" and suffix == "versions":
        return 200, {"versions": _list_versions(kind="prompts", document_key=prompt_key, version_root=version_root)}
    if method == "GET" and suffix.startswith("versions/"):
        version_id = _remove_prefix(suffix, "versions/")
        return _version_response(kind="prompts", document_key=prompt_key, version_id=version_id, version_root=version_root)
    if method == "POST" and suffix.startswith("versions/") and suffix.endswith("/restore"):
        version_id = _remove_suffix(_remove_prefix(suffix, "versions/"), "/restore").strip("/")
        status, payload = _version_response(
            kind="prompts",
            document_key=prompt_key,
            version_id=version_id,
            version_root=version_root,
        )
        if status != 200:
            return status, payload
        markdown = str(payload["version"]["content"].get("markdown") or "")
        prompt_path.write_text(markdown, encoding="utf-8")
        request = _json_body(body) if body else {}
        _save_version(
            kind="prompts",
            document_key=prompt_key,
            content={"markdown": markdown},
            author=str(request.get("author") or "系统"),
            note=f"恢复版本 {version_id}",
            action="restore",
            version_root=version_root,
        )
        return 200, _prompt_detail(prompt_key=prompt_key, prompt_path=prompt_path, version_root=version_root)
    if method == "PUT" and not suffix:
        payload = _json_body(body)
        markdown = str(payload.get("markdown") or "")
        prompt_path.write_text(markdown, encoding="utf-8")
        _save_version(
            kind="prompts",
            document_key=prompt_key,
            content={"markdown": markdown},
            author=str(payload.get("author") or "未填写"),
            note=str(payload.get("note") or "医生修改 prompt"),
            action="update",
            version_root=version_root,
        )
        return 200, _prompt_detail(prompt_key=prompt_key, prompt_path=prompt_path, version_root=version_root)
    if method == "DELETE" and not suffix:
        payload = _json_body(body) if body else {}
        markdown = prompt_path.read_text(encoding="utf-8")
        _save_version(
            kind="prompts",
            document_key=prompt_key,
            content={"markdown": markdown},
            author=str(payload.get("author") or "未填写"),
            note=str(payload.get("note") or "删除前快照"),
            action="delete",
            version_root=version_root,
        )
        prompt_path.unlink()
        return 200, {"status": "deleted", "prompt_key": prompt_key}
    return 404, {"error": "not found"}


def _knowledge_summary(*, knowledge_key: str, knowledge: dict, version_root: Path) -> dict:
    clinical = knowledge.get("clinical_features") or {}
    return {
        "knowledge_key": knowledge_key,
        "title": knowledge.get("disease_name") or knowledge_key,
        "knowledge_id": knowledge.get("knowledge_id") or "",
        "evidence_level": knowledge.get("evidence_level") or "",
        "symptom_count": len(clinical.get("common_symptoms") or []),
        "image_requirement_count": len(knowledge.get("required_image_views") or []),
        "version_count": len(_list_versions(kind="knowledge", document_key=knowledge_key, version_root=version_root)),
    }


def _knowledge_detail(*, knowledge_key: str, knowledge_path: Path, version_root: Path) -> dict:
    knowledge = _read_knowledge(knowledge_path)
    return {
        "knowledge_key": knowledge_key,
        "path": str(knowledge_path),
        "editor": _knowledge_to_editor(knowledge),
        "raw": knowledge,
        "versions": _list_versions(kind="knowledge", document_key=knowledge_key, version_root=version_root),
    }


def _knowledge_to_editor(knowledge: dict) -> dict:
    clinical = knowledge.get("clinical_features") or {}
    targets = knowledge.get("visual_targets") or {}
    tasks = knowledge.get("vision_agent_tasks") or {}
    report = knowledge.get("report_requirements") or {}
    return {
        "disease_name": knowledge.get("disease_name") or "",
        "knowledge_id": knowledge.get("knowledge_id") or "",
        "version": knowledge.get("version") or "",
        "source": knowledge.get("source") or "",
        "evidence_level": knowledge.get("evidence_level") or "",
        "common_symptoms": _join_list(clinical.get("common_symptoms")),
        "risk_factors": _join_list(clinical.get("risk_factors")),
        "required_image_views": _join_list(knowledge.get("required_image_views")),
        "anatomy": _join_list(targets.get("anatomy")),
        "lesion_features": _join_list(targets.get("lesion_features")),
        "segmentation_targets": _join_list(tasks.get("segmentation_targets")),
        "quantitative_features": _join_list(tasks.get("quantitative_features")),
        "report_requirements": _join_list(report.get("include")),
        "doctor_notes": _join_doctor_notes(knowledge),
        "staging_rules_preview": _json_text(knowledge.get("staging_rules") or {}),
        "source_documents_preview": _json_text(knowledge.get("source_documents") or []),
    }


def _apply_knowledge_editor_payload(knowledge: dict, payload: dict) -> dict:
    updated = json.loads(json.dumps(knowledge, ensure_ascii=False))
    editor = payload.get("editor") or {}
    if not isinstance(editor, dict):
        raise ValueError("editor must be an object")

    for field in ("disease_name", "knowledge_id", "version", "source", "evidence_level"):
        if field in editor:
            updated[field] = str(editor.get(field) or "").strip()

    clinical = dict(updated.get("clinical_features") or {})
    if "common_symptoms" in editor:
        clinical["common_symptoms"] = _split_lines(editor.get("common_symptoms"))
    if "risk_factors" in editor:
        clinical["risk_factors"] = _split_lines(editor.get("risk_factors"))
    updated["clinical_features"] = clinical

    if "required_image_views" in editor:
        updated["required_image_views"] = _split_lines(editor.get("required_image_views"))

    targets = dict(updated.get("visual_targets") or {})
    if "anatomy" in editor:
        targets["anatomy"] = _split_lines(editor.get("anatomy"))
    if "lesion_features" in editor:
        targets["lesion_features"] = _split_lines(editor.get("lesion_features"))
    updated["visual_targets"] = targets

    tasks = dict(updated.get("vision_agent_tasks") or {})
    if "segmentation_targets" in editor:
        tasks["segmentation_targets"] = _split_lines(editor.get("segmentation_targets"))
    if "quantitative_features" in editor:
        tasks["quantitative_features"] = _split_lines(editor.get("quantitative_features"))
    updated["vision_agent_tasks"] = tasks

    if "report_requirements" in editor:
        report = dict(updated.get("report_requirements") or {})
        report["include"] = _split_lines(editor.get("report_requirements"))
        updated["report_requirements"] = report

    doctor_note = str(editor.get("doctor_notes") or "").strip()
    if doctor_note:
        quality = dict(updated.get("quality_control") or {})
        notes = list(quality.get("doctor_review_notes") or [])
        notes.append(
            {
                "author": str(payload.get("author") or "未填写"),
                "note": doctor_note,
                "created_at": _timestamp(),
            }
        )
        quality["doctor_review_notes"] = notes
        updated["quality_control"] = quality
    return updated


def _new_knowledge(*, knowledge_key: str, payload: dict) -> dict:
    disease_name = str(payload.get("disease_name") or payload.get("title") or "新疾病 Knowledge").strip()
    return {
        "disease_name": disease_name,
        "knowledge_id": f"{knowledge_key}_v0.1",
        "version": "0.1",
        "source_type": "doctor_edited",
        "knowledge_type": "guideline_based",
        "evidence_level": "review_required",
        "source": "医生可视化编辑器创建，需补充来源",
        "source_documents": [],
        "quality_control": {
            "citation_status": "review_required",
            "doctor_review_notes": [],
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
            "include": ["诊断倾向", "影像依据", "不确定性说明", "建议进一步检查"],
        },
    }


def _prompt_summary(*, prompt_path: Path, version_root: Path) -> dict:
    markdown = prompt_path.read_text(encoding="utf-8")
    title = next((line.strip("# ").strip() for line in markdown.splitlines() if line.strip()), prompt_path.stem)
    return {
        "prompt_key": prompt_path.stem,
        "title": title,
        "version_count": len(_list_versions(kind="prompts", document_key=prompt_path.stem, version_root=version_root)),
    }


def _prompt_detail(*, prompt_key: str, prompt_path: Path, version_root: Path) -> dict:
    return {
        "prompt_key": prompt_key,
        "path": str(prompt_path),
        "markdown": prompt_path.read_text(encoding="utf-8"),
        "versions": _list_versions(kind="prompts", document_key=prompt_key, version_root=version_root),
    }


def _save_version(
    *,
    kind: str,
    document_key: str,
    content: dict,
    author: str,
    note: str,
    action: str,
    version_root: Path,
) -> Path:
    version_dir = version_root / kind / document_key
    version_dir.mkdir(parents=True, exist_ok=True)
    version_id = _timestamp()
    version_path = version_dir / f"{version_id}.json"
    payload = {
        "id": version_id,
        "kind": kind,
        "document_key": document_key,
        "action": action,
        "author": author or "未填写",
        "note": note or action,
        "created_at": version_id,
        "content": content,
    }
    version_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return version_path


def _list_versions(*, kind: str, document_key: str, version_root: Path) -> list[dict]:
    version_dir = version_root / kind / document_key
    if not version_dir.exists():
        return []
    versions = []
    for path in sorted(version_dir.glob("*.json"), reverse=True):
        try:
            version = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        versions.append(
            {
                "id": version.get("id") or path.stem,
                "action": version.get("action") or "",
                "author": version.get("author") or "未填写",
                "note": version.get("note") or "",
                "created_at": version.get("created_at") or path.stem,
            }
        )
    return versions


def _version_response(*, kind: str, document_key: str, version_id: str, version_root: Path) -> tuple[int, dict]:
    if not _is_safe_key(version_id):
        return 404, {"error": "not found"}
    version_path = version_root / kind / document_key / f"{version_id}.json"
    if not version_path.exists():
        return 404, {"error": f"version not found: {version_id}"}
    return 200, {"version": json.loads(version_path.read_text(encoding="utf-8"))}


def _read_knowledge(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _can_read_json(path: Path) -> bool:
    try:
        _read_knowledge(path)
        return True
    except json.JSONDecodeError:
        return False


def _json_body(body: bytes) -> dict:
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid json: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    return payload


def _split_document_route(route_path: str, prefix: str) -> tuple[str, str]:
    remainder = _remove_prefix(route_path, prefix).strip("/")
    if not remainder:
        return "", ""
    parts = remainder.split("/", 1)
    key = parts[0]
    if not _is_safe_key(key):
        return "", ""
    return key, parts[1] if len(parts) > 1 else ""


def _safe_key(value: object) -> str:
    key = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_")
    if not key:
        raise ValueError("document key is required")
    return key


def _is_safe_key(value: object) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", str(value or "")))


def _split_lines(value: object) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[\n，,;；]+", str(value or ""))
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _join_list(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return "\n".join(str(item) for item in value)


def _join_doctor_notes(knowledge: dict) -> str:
    notes = (knowledge.get("quality_control") or {}).get("doctor_review_notes") or []
    if not isinstance(notes, list):
        return ""
    return "\n".join(str(item.get("note") or item) for item in notes if item)


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
