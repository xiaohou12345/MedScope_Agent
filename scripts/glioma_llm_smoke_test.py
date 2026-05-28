from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from agents.diagnosis_agent import DiagnosisDoctorAgent
from agents.gaodoctor_agent import GaoDoctorAgent
from llm.model_client import ApiRouteLog, ModelClient, OpenAICompatibleModelClient
from memory.memory_manager import MemoryManager


DEFAULT_IMAGE = Path("data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz")
DEFAULT_MASK = Path("data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz")
DEFAULT_OUTPUT_DIR = Path("output/fake/glioma_llm_smoke")


class CapturingPromptRunner:
    def __init__(self, model_client: ModelClient) -> None:
        self.model_client = model_client
        self.last_content: str | None = None

    def run(self, task: str, system_prompt: str, user_payload: dict[str, Any]) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
            },
        ]
        self.last_content = self.model_client.chat(messages=messages, task=task).content
        return self.last_content


def run_glioma_llm_smoke(
    image_path: Path | str = DEFAULT_IMAGE,
    mask_path: Path | str = DEFAULT_MASK,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    route_log_path: Path | str = "docs/API_ROUTE_LOG.md",
    real: bool = False,
    model_client: ModelClient | None = None,
) -> str:
    route_log = ApiRouteLog.from_file(route_log_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    image = Path(image_path)
    mask = Path(mask_path)
    api_key_env = route_log.api_key_env_for_active_route()
    payload: dict[str, Any] = {
        "status": "dry_run",
        "active_route": route_log.active_route,
        "model": route_log.model_for_active_route(),
        "api_key_env": api_key_env,
        "api_key_present": bool(os.environ.get(api_key_env)),
        "image_path": str(image),
        "image_exists": image.exists(),
        "mask_path": str(mask),
        "mask_exists": mask.exists(),
        "output_dir": str(output),
        "real_call_attempted": False,
    }
    if not real:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if model_client is None and not payload["api_key_present"]:
        payload["status"] = "not_ready"
        payload["error"] = f"Missing {api_key_env}"
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if not image.exists():
        payload["status"] = "not_ready"
        payload["error"] = f"Image not found: {image}"
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if not mask.exists():
        payload["status"] = "not_ready"
        payload["error"] = f"Mask not found: {mask}"
        return json.dumps(payload, ensure_ascii=False, indent=2)

    client = model_client or OpenAICompatibleModelClient(route_log=route_log)
    prompt_runner = CapturingPromptRunner(model_client=client)
    memory = MemoryManager(base_dir=output / "memory")
    doctor = GaoDoctorAgent(
        diagnosis_agent=DiagnosisDoctorAgent(
            prompt_runner=prompt_runner,
        ),
        memory_manager=memory,
    )
    result = doctor.handle_message(
        patient_message="请基于这次 FLAIR MRI 做胶质瘤辅助分析",
        image_path=str(image),
        patient_info={"symptoms": ["头痛"]},
        disease_key="diffuse_glioma_brats",
        vision_mode="ground_truth",
        mask_path=str(mask),
    )
    case_memory = memory.get_case_by_id(result["case_id"])
    result_path = output / "glioma_llm_smoke_result.json"
    payload.update(
        {
            "status": "ok",
            "real_call_attempted": True,
            "case_id": result["case_id"],
            "result_json_path": str(result_path),
            "reply_to_patient": result["reply_to_patient"],
            "report": result["report"],
            "case_memory": case_memory,
        }
    )
    if prompt_runner.last_content is not None:
        payload["llm_raw_content"] = prompt_runner.last_content
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.dumps(payload, ensure_ascii=False, indent=2)


def run_glioma_llm_manifest(
    manifest_path: Path | str = "data/external/brats_manifest.json",
    output_dir: Path | str = DEFAULT_OUTPUT_DIR / "batch",
    route_log_path: Path | str = "docs/API_ROUTE_LOG.md",
    real: bool = False,
    model_client: ModelClient | None = None,
    min_cases: int = 1,
) -> str:
    manifest = Path(manifest_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    cases = manifest_payload.get("cases", [])
    summary_path = output / "summary.json"
    markdown_summary_path = output / "summary.md"

    case_summaries: list[dict[str, Any]] = []
    ok_count = 0
    fallback_count = 0
    quality_gate = {
        "min_cases": min_cases,
        "actual_cases": len(cases),
        "passed": len(cases) >= min_cases,
        "reason": None
        if len(cases) >= min_cases
        else f"Manifest has {len(cases)} cases, fewer than required min_cases={min_cases}",
    }
    if not quality_gate["passed"]:
        summary = {
            "status": "insufficient_cases",
            "manifest_path": str(manifest),
            "summary_path": str(summary_path),
            "summary_markdown_path": str(markdown_summary_path),
            "case_count": len(cases),
            "ok_count": ok_count,
            "fallback_count": fallback_count,
            "failed_case_ids": [],
            "fallback_case_ids": [],
            "quality_gate": quality_gate,
            "cases": case_summaries,
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_summary_path.write_text(_render_manifest_summary_markdown(summary), encoding="utf-8")
        return json.dumps(summary, ensure_ascii=False, indent=2)

    for case in cases:
        case_id = case.get("case_id", "unknown_case")
        case_output_dir = output / case_id
        try:
            result_payload = json.loads(
                run_glioma_llm_smoke(
                    image_path=_resolve_manifest_path(case["image_path"], manifest.parent),
                    mask_path=_resolve_manifest_path(case["mask_path"], manifest.parent),
                    output_dir=case_output_dir,
                    route_log_path=route_log_path,
                    real=real,
                    model_client=model_client,
                )
            )
            status = result_payload.get("status")
            report = result_payload.get("report") or {}
            llm_fallback = "llm_fallback_reason" in report
            if status == "ok":
                ok_count += 1
            if llm_fallback:
                fallback_count += 1
            case_summaries.append(
                {
                    "case_id": case_id,
                    "status": status,
                    "result_json_path": result_payload.get("result_json_path"),
                    "llm_fallback": llm_fallback,
                    "llm_fallback_reason": report.get("llm_fallback_reason"),
                    "used_visual_fields": report.get("used_visual_fields", []),
                    "missing_visual_fields_acknowledged": report.get(
                        "missing_visual_fields_acknowledged", []
                    ),
                    "error": result_payload.get("error"),
                }
            )
        except Exception as exc:
            case_summaries.append(
                {
                    "case_id": case_id,
                    "status": "error",
                    "result_json_path": None,
                    "llm_fallback": None,
                    "llm_fallback_reason": None,
                    "used_visual_fields": [],
                    "missing_visual_fields_acknowledged": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    summary = {
        "status": _manifest_summary_status(
            real=real,
            case_count=len(cases),
            ok_count=ok_count,
            case_summaries=case_summaries,
        ),
        "manifest_path": str(manifest),
        "summary_path": str(summary_path),
        "summary_markdown_path": str(markdown_summary_path),
        "case_count": len(cases),
        "ok_count": ok_count,
        "fallback_count": fallback_count,
        "failed_case_ids": [
            case["case_id"]
            for case in case_summaries
            if case.get("status") not in {"ok", "dry_run"}
        ],
        "fallback_case_ids": [
            case["case_id"] for case in case_summaries if case.get("llm_fallback")
        ],
        "quality_gate": quality_gate,
        "cases": case_summaries,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_summary_path.write_text(_render_manifest_summary_markdown(summary), encoding="utf-8")
    return json.dumps(summary, ensure_ascii=False, indent=2)


def _manifest_summary_status(
    real: bool,
    case_count: int,
    ok_count: int,
    case_summaries: list[dict[str, Any]],
) -> str:
    if not real:
        return "dry_run"
    if ok_count == case_count and case_count:
        return "ok"
    if any(case.get("status") == "ok" for case in case_summaries):
        return "partial_error"
    return "error"


def _render_manifest_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Glioma LLM Smoke Summary",
        "",
        f"- status: {summary.get('status')}",
        f"- manifest: {summary.get('manifest_path')}",
        f"- cases: {summary.get('ok_count')}/{summary.get('case_count')} ok",
        f"- fallback_count: {summary.get('fallback_count')}",
        f"- min_cases: {summary.get('quality_gate', {}).get('min_cases')}",
        f"- quality_gate: {summary.get('quality_gate', {}).get('passed')}",
        "",
        "| case_id | status | fallback | used_visual_fields | missing_visual_fields_acknowledged | result | error |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in summary.get("cases", []):
        lines.append(
            "| {case_id} | {status} | {fallback} | {used} | {missing} | {result} | {error} |".format(
                case_id=case.get("case_id"),
                status=case.get("status"),
                fallback=case.get("llm_fallback"),
                used=", ".join(case.get("used_visual_fields") or []),
                missing=", ".join(case.get("missing_visual_fields_acknowledged") or []),
                result=case.get("result_json_path") or "",
                error=case.get("error") or case.get("llm_fallback_reason") or "",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _resolve_manifest_path(path_value: str, manifest_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute() or path.exists():
        return path
    return manifest_dir / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a glioma LLM smoke test through GaoDoctor.")
    parser.add_argument("--image", default=str(DEFAULT_IMAGE))
    parser.add_argument("--mask", default=str(DEFAULT_MASK))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--route-log", default="docs/API_ROUTE_LOG.md")
    parser.add_argument("--real", action="store_true", help="Actually call the active model route.")
    parser.add_argument("--manifest", help="Optional BraTS manifest JSON path for batch mode.")
    parser.add_argument("--all-cases", action="store_true", help="Run all cases from --manifest.")
    parser.add_argument(
        "--min-cases",
        type=int,
        default=1,
        help="Minimum manifest case count required before batch mode runs cases.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.all_cases:
        print(
            run_glioma_llm_manifest(
                manifest_path=args.manifest or "data/external/brats_manifest.json",
                output_dir=args.output_dir,
                route_log_path=args.route_log,
                real=args.real,
                min_cases=args.min_cases,
            )
        )
        return
    print(
        run_glioma_llm_smoke(
            image_path=args.image,
            mask_path=args.mask,
            output_dir=args.output_dir,
            route_log_path=args.route_log,
            real=args.real,
        )
    )


if __name__ == "__main__":
    main()
