"""Run image + patient prompt + skill baselines at three prompt strengths."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from tools.skill_builder_tool import SkillBuilderTool
from tools.vision_prompt_generator import OpenAICompatibleVisionClient, VisionClient


DEFAULT_OUTPUT_DIR = Path("output/fake/image_prompt_skill_baseline")

IMAGE_BASELINE_LEVELS: list[dict[str, Any]] = [
    {
        "level": "simple_prompt",
        "display_name": "Simple image prompt",
        "constraint_level": 1,
        "prompt_path": "prompts/baselines/simple_prompt.md",
    },
    {
        "level": "workflow_prompt",
        "display_name": "Workflow image prompt",
        "constraint_level": 2,
        "prompt_path": "prompts/baselines/workflow_prompt.md",
    },
    {
        "level": "fewshot_prompt",
        "display_name": "Few-shot image prompt",
        "constraint_level": 3,
        "prompt_path": "prompts/baselines/fewshot_prompt.md",
    },
]


def run_image_prompt_skill_baseline(
    *,
    image_path: Path | str,
    patient_prompt: str,
    disease_skill: dict[str, Any] | None = None,
    disease_key: str | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    client: VisionClient | None = None,
) -> dict[str, Any]:
    image = Path(image_path)
    if not image.exists():
        raise FileNotFoundError(f"image_path not found: {image}")
    if not patient_prompt.strip():
        raise ValueError("patient_prompt is required")
    skill = disease_skill or SkillBuilderTool().load_guideline_skill(
        disease_key or "femoral_head_necrosis"
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    baseline_client = client or OpenAICompatibleVisionClient()
    results = [
        _run_level(
            image_path=image,
            patient_prompt=patient_prompt,
            disease_skill=skill,
            baseline_level=level,
            client=baseline_client,
        )
        for level in IMAGE_BASELINE_LEVELS
    ]
    payload = {
        "schema_version": "image_prompt_skill_baseline.v1",
        "status": "completed",
        "created_at": timestamp,
        "image_path": str(image),
        "patient_prompt": patient_prompt,
        "skill_summary": _skill_summary(skill),
        "baseline_count": len(results),
        "baseline_levels": [dict(level) for level in IMAGE_BASELINE_LEVELS],
        "baseline_results": results,
        "metrics_by_level": {
            result["level"]: dict(result["metrics"])
            for result in results
        },
        "comparison_boundary": {
            "baseline_uses_raw_image": True,
            "baseline_uses_medscope_vision_agent": False,
            "baseline_uses_medsam2": False,
            "baseline_updates_memory": False,
            "purpose": "Compare prompt-only VLM behavior against MedScope evidence-bound pipeline.",
        },
    }
    json_path = output / "image_prompt_skill_baseline.json"
    markdown_path = output / "image_prompt_skill_baseline.md"
    payload["output_paths"] = {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _run_level(
    *,
    image_path: Path,
    patient_prompt: str,
    disease_skill: dict[str, Any],
    baseline_level: dict[str, Any],
    client: VisionClient,
) -> dict[str, Any]:
    level = str(baseline_level["level"])
    system_prompt = _read_prompt(Path(str(baseline_level["prompt_path"])))
    user_payload = {
        "baseline_level": level,
        "patient_prompt": patient_prompt,
        "skill": _baseline_skill_payload(disease_skill),
        "required_output_schema": {
            "诊断倾向": "string",
            "影像依据": ["string"],
            "分期判断": "string",
            "不确定性说明": ["string"],
            "建议进一步检查": ["string"],
            "治疗建议": ["string"],
        },
        "comparison_rules": [
            "This is a prompt-only baseline.",
            "Do not call segmentation tools.",
            "Do not claim this output is the MedScope agent result.",
        ],
    }
    raw_content = client.chat_with_image(
        image_path=image_path,
        system_prompt=system_prompt,
        user_payload=user_payload,
        task="image_prompt_skill_baseline",
    )
    parsed_report, parse_error = _parse_json(raw_content)
    metrics = _baseline_metrics(parsed_report=parsed_report, parse_error=parse_error)
    return {
        "level": level,
        "display_name": baseline_level["display_name"],
        "constraint_level": baseline_level["constraint_level"],
        "prompt_path": baseline_level["prompt_path"],
        "raw_content": raw_content,
        "parsed_report": parsed_report,
        "parse_error": parse_error,
        "metrics": metrics,
    }


def _baseline_skill_payload(skill: dict[str, Any]) -> dict[str, Any]:
    protocol = skill.get("visual_protocol") or {}
    return {
        "disease_name": skill.get("disease_name"),
        "skill_id": skill.get("skill_id"),
        "skill_type": skill.get("skill_type"),
        "evidence_level": skill.get("evidence_level"),
        "source": skill.get("source"),
        "clinical_features": dict(skill.get("clinical_features") or {}),
        "required_image_views": list(skill.get("required_image_views") or []),
        "visual_protocol": {
            "disease_target": protocol.get("disease_target"),
            "clinical_focus": protocol.get("clinical_focus"),
            "finding_targets": [
                dict(target)
                for target in protocol.get("finding_targets") or []
                if isinstance(target, dict)
            ],
            "insufficiency_rules": [
                dict(rule)
                for rule in protocol.get("insufficiency_rules") or []
                if isinstance(rule, dict)
            ],
            "required_next_images": [
                dict(item)
                for item in protocol.get("required_next_images") or []
                if isinstance(item, dict)
            ],
            "diagnosis_scope": dict(protocol.get("diagnosis_scope") or {}),
        },
    }


def _skill_summary(skill: dict[str, Any]) -> dict[str, Any]:
    protocol = skill.get("visual_protocol") or {}
    return {
        "disease_name": skill.get("disease_name"),
        "skill_id": skill.get("skill_id"),
        "disease_target": protocol.get("disease_target"),
        "finding_target_count": len(protocol.get("finding_targets") or []),
        "required_next_image_count": len(protocol.get("required_next_images") or []),
    }


def _parse_json(raw_content: str) -> tuple[dict[str, Any] | None, str | None]:
    text = raw_content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        payload = json.loads(text)
    except JSONDecodeError as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "baseline response JSON must be an object"
    return payload, None


def _baseline_metrics(
    *,
    parsed_report: dict[str, Any] | None,
    parse_error: str | None,
) -> dict[str, Any]:
    text = json.dumps(parsed_report or {}, ensure_ascii=False)
    mentioned_next_image = any(keyword in text for keyword in ["MRI", "CT", "增强", "T1", "T2", "STIR"])
    uncertainty_count = len(parsed_report.get("不确定性说明") or []) if parsed_report else 0
    return {
        "json_valid_count": 1 if parsed_report is not None and parse_error is None else 0,
        "mentions_lesion_or_finding_count": 1
        if any(keyword in text for keyword in ["病灶", "征象", "硬化", "囊性", "肿瘤", "阴影", "异常"])
        else 0,
        "required_next_image_mentioned_count": 1 if mentioned_next_image else 0,
        "uncertainty_statement_count": uncertainty_count,
        "direct_final_diagnosis_claim_count": 1
        if any(keyword in text for keyword in ["明确诊断", "可以确诊", "最终诊断"])
        else 0,
    }


def _read_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# MedScope Image + Prompt + Skill Baseline",
        "",
        "This artifact compares three prompt-only VLM baselines on the same uploaded image, patient prompt, and skill.",
        "",
        f"- `status`: `{payload.get('status')}`",
        f"- `image_path`: `{payload.get('image_path')}`",
        f"- `baseline_count`: `{payload.get('baseline_count')}`",
        "",
        "| level | json valid | finding mentioned | next image mentioned | final diagnosis claim |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for result in payload.get("baseline_results") or []:
        metrics = result.get("metrics") or {}
        lines.append(
            "| {level} | {json_valid} | {finding} | {next_image} | {final_claim} |".format(
                level=result.get("level"),
                json_valid=metrics.get("json_valid_count"),
                finding=metrics.get("mentions_lesion_or_finding_count"),
                next_image=metrics.get("required_next_image_mentioned_count"),
                final_claim=metrics.get("direct_final_diagnosis_claim_count"),
            )
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Baselines see the raw image through the VLM client.",
            "- Baselines do not call VisionAgent, MedSAM2, evidence bundle construction, DiagnosisAgent, or MemoryManager.",
            "- Use this artifact to compare prompt-only behavior against the controlled MedScope pipeline.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--disease-key", default="femoral_head_necrosis")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    payload = run_image_prompt_skill_baseline(
        image_path=Path(args.image),
        patient_prompt=args.message,
        disease_key=args.disease_key,
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
