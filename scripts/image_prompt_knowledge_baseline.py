"""Run image + patient prompt + knowledge baselines at three prompt strengths."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from tools.knowledge_builder_tool import KnowledgeBuilderTool
from tools.vision_prompt_generator import OpenAICompatibleVisionClient, VisionClient


DEFAULT_OUTPUT_DIR = Path("output/fake/image_prompt_knowledge_baseline")

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


def run_image_prompt_knowledge_baseline(
    *,
    image_path: Path | str,
    patient_prompt: str,
    disease_knowledge: dict[str, Any] | None = None,
    disease_key: str | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    client: VisionClient | None = None,
) -> dict[str, Any]:
    image = Path(image_path)
    if not image.exists():
        raise FileNotFoundError(f"image_path not found: {image}")
    if not patient_prompt.strip():
        raise ValueError("patient_prompt is required")
    knowledge = disease_knowledge or KnowledgeBuilderTool().load_guideline_knowledge(
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
            disease_knowledge=knowledge,
            baseline_level=level,
            client=baseline_client,
        )
        for level in IMAGE_BASELINE_LEVELS
    ]
    payload = {
        "schema_version": "image_prompt_knowledge_baseline.v1",
        "status": "completed",
        "created_at": timestamp,
        "image_path": str(image),
        "patient_prompt": patient_prompt,
        "knowledge_summary": _knowledge_summary(knowledge),
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
    json_path = output / "image_prompt_knowledge_baseline.json"
    markdown_path = output / "image_prompt_knowledge_baseline.md"
    chinese_conclusion_path = output / "中文结论.md"
    payload["output_paths"] = {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "chinese_conclusion_path": str(chinese_conclusion_path),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    chinese_conclusion_path.write_text(_render_chinese_conclusion(payload), encoding="utf-8")
    return payload


def _run_level(
    *,
    image_path: Path,
    patient_prompt: str,
    disease_knowledge: dict[str, Any],
    baseline_level: dict[str, Any],
    client: VisionClient,
) -> dict[str, Any]:
    level = str(baseline_level["level"])
    system_prompt = _read_prompt(Path(str(baseline_level["prompt_path"])))
    user_payload = {
        "baseline_level": level,
        "patient_prompt": patient_prompt,
        "knowledge": _baseline_knowledge_payload(disease_knowledge),
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
        task="image_prompt_knowledge_baseline",
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


def _baseline_knowledge_payload(knowledge: dict[str, Any]) -> dict[str, Any]:
    protocol = knowledge.get("visual_protocol") or {}
    return {
        "disease_name": knowledge.get("disease_name"),
        "knowledge_id": knowledge.get("knowledge_id"),
        "knowledge_type": knowledge.get("knowledge_type"),
        "evidence_level": knowledge.get("evidence_level"),
        "source": knowledge.get("source"),
        "clinical_features": dict(knowledge.get("clinical_features") or {}),
        "required_image_views": list(knowledge.get("required_image_views") or []),
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


def _knowledge_summary(knowledge: dict[str, Any]) -> dict[str, Any]:
    protocol = knowledge.get("visual_protocol") or {}
    return {
        "disease_name": knowledge.get("disease_name"),
        "knowledge_id": knowledge.get("knowledge_id"),
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
        "# MedScope Image + Prompt + Knowledge Baseline",
        "",
        "This artifact compares three prompt-only VLM baselines on the same uploaded image, patient prompt, and knowledge.",
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


def _render_chinese_conclusion(payload: dict[str, Any]) -> str:
    results = {
        str(result.get("level")): result
        for result in payload.get("baseline_results") or []
        if isinstance(result, dict)
    }
    simple = _parsed_report(results.get("simple_prompt"))
    workflow = _parsed_report(results.get("workflow_prompt"))
    fewshot = _parsed_report(results.get("fewshot_prompt"))
    knowledge = payload.get("knowledge_summary") or {}
    disease_name = str(knowledge.get("disease_name") or "目标疾病")
    image_path = str(payload.get("image_path") or "")
    patient_prompt = str(payload.get("patient_prompt") or "")
    lines = [
        f"# {disease_name}三层 Codex/VLM 分析中文结论",
        "",
        "## 工作流输入",
        "",
        f"- 图像：`{image_path}`",
        f"- 患者描述：{patient_prompt}",
        f"- 使用 knowledge：`{knowledge.get('knowledge_id') or 'unknown'}`",
        "",
        "## 总体结论",
        "",
        _overall_conclusion([simple, workflow, fewshot], disease_name=disease_name),
        "",
        "## 三层分析差别",
        "",
        "| 层级 | 主要结论 | 证据边界 |",
        "| --- | --- | --- |",
        "| simple_prompt | {simple_conclusion} | {simple_boundary} |".format(
            simple_conclusion=_report_field(simple, "诊断倾向"),
            simple_boundary=_first_item(simple, "不确定性说明"),
        ),
        "| workflow_prompt | {workflow_conclusion} | {workflow_boundary} |".format(
            workflow_conclusion=_report_field(workflow, "诊断倾向"),
            workflow_boundary=_first_item(workflow, "不确定性说明"),
        ),
        "| fewshot_prompt | {fewshot_conclusion} | {fewshot_boundary} |".format(
            fewshot_conclusion=_report_field(fewshot, "诊断倾向"),
            fewshot_boundary=_first_item(fewshot, "不确定性说明"),
        ),
        "",
        "## 三个层次具体说明",
        "",
        "### Level 1: simple_prompt",
        "",
        "simple_prompt 是最弱约束版本。它直接把原始医疗图像、患者描述和 disease knowledge 给 VLM，主要依靠模型自身视觉理解和医学常识回答。",
        "",
        "本层适合作为最低基线：可以观察普通 VLM 是否能发现大方向异常，但证据边界通常不够稳定，容易把候选征象说得偏确定。",
        "",
        "### Level 2: workflow_prompt",
        "",
        "workflow_prompt 在 simple_prompt 基础上增加流程约束，要求模型按影像依据、分期边界、不确定性和下一步检查组织回答。",
        "",
        "本层通常比 simple_prompt 更重视证据边界，但本质仍是模型直接看图生成文本，没有真实 mask、数值化病灶特征或采用/排除证据审计。",
        "",
        "### Level 3: fewshot_prompt",
        "",
        "fewshot_prompt 是三层里约束最强的 prompt-only baseline。它通过示例提醒模型：不能把缺失证据当作阴性，不能把候选征象直接当作最终诊断。",
        "",
        "本层通常最接近 evidence-bounded reasoning 的语言风格，但仍然不是正式 MedScope Agent 输出。",
        "",
        "## 和 MedScope Agent 主流程的区别",
        "",
        "三层 Codex/VLM baseline 的流程是：",
        "",
        "```text",
        "图片 + 患者描述 + knowledge -> VLM 直接生成诊断文本",
        "```",
        "",
        "MedScope Agent 主流程是：",
        "",
        "```text",
        "图片 + 患者描述",
        "-> 高医生 Agent 自动选择 knowledge",
        "-> VisionAgent 根据 knowledge 生成候选视觉证据",
        "-> MedSAM2 或 VLM-only 模式生成病灶候选图",
        "-> evidence bundle 记录可用证据、缺失证据、排除证据",
        "-> DiagnosisAgent 只消费结构化证据生成诊断报告",
        "-> MemoryManager 保存 patient/image/knowledge/reasoning memory",
        "-> QA 只能基于已保存 evidence bundle 回答",
        "```",
        "",
        "核心区别是：baseline 是“模型直接看图并说结论”；MedScope 是“模型和工具协同产生证据，再由诊断 Agent 受约束推理”。",
        "",
        "## 一句话总结",
        "",
        _one_sentence_summary([simple, workflow, fewshot], disease_name=disease_name),
        "",
    ]
    return "\n".join(lines)


def _parsed_report(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    parsed = result.get("parsed_report")
    return parsed if isinstance(parsed, dict) else {}


def _report_field(report: dict[str, Any], key: str) -> str:
    value = report.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list) and value:
        return "；".join(str(item).strip() for item in value[:2] if str(item).strip())
    return "未生成有效内容"


def _first_item(report: dict[str, Any], key: str) -> str:
    value = report.get(key)
    if isinstance(value, list):
        for item in value:
            text = str(item).strip()
            if text:
                return text
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "未明确说明"


def _overall_conclusion(reports: list[dict[str, Any]], *, disease_name: str) -> str:
    conclusions = " ".join(_report_field(report, "诊断倾向") for report in reports if report)
    if not conclusions:
        return (
            f"三层 baseline 未生成稳定诊断文本，需要查看 JSON 原始结果。"
            f"这不代表没有{disease_name}，只代表 baseline 输出不可用。"
        )
    if any(term in conclusions for term in ["可疑", "可能", "倾向", "怀疑", "候选"]):
        return (
            f"三层 Codex/VLM baseline 均提示存在{disease_name}相关可疑影像表现。"
            "这些输出可作为 prompt-only 对照组，但不能替代正式 Agent 主流程。"
        )
    return (
        f"三层 Codex/VLM baseline 已完成对{disease_name}的 prompt-only 分析。"
        "具体结论需要结合下方每层输出和证据边界查看。"
    )


def _one_sentence_summary(reports: list[dict[str, Any]], *, disease_name: str) -> str:
    next_checks = " ".join(
        _report_field(report, "建议进一步检查")
        for report in reports
        if report
    )
    if "MRI" in next_checks:
        return (
            f"当前 prompt-only baseline 可提示{disease_name}相关可能性，"
            "但仍应通过正式 MedScope Agent 主流程和必要的 MRI/专科复核完成证据约束判断。"
        )
    return (
        f"当前 prompt-only baseline 只能作为{disease_name}的对照分析，"
        "正式结论仍应以后续 Agent evidence bundle 和诊断报告为准。"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--disease-key", default="femoral_head_necrosis")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    payload = run_image_prompt_knowledge_baseline(
        image_path=Path(args.image),
        patient_prompt=args.message,
        disease_key=args.disease_key,
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
