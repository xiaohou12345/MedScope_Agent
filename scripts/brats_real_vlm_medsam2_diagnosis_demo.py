from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from agents.diagnosis_agent import DiagnosisDoctorAgent
from llm.model_client import ApiRouteLog, ModelClient, OpenAICompatibleModelClient
from tools.knowledge_builder_tool import KnowledgeBuilderTool


DEFAULT_AUTO_EVAL_RESULT = Path(
    "output/fake/brats_medsam2_auto_eval_real_vlm_prompt_real_medsam2/"
    "brats2021_00030_medsam2_auto_eval_result.json"
)
DEFAULT_OUTPUT_DIR = Path("output/fake/brats_real_vlm_medsam2_diagnosis_demo")
DEFAULT_PATIENT_MESSAGE = "请基于这次 FLAIR MRI 和自动分割结果做胶质瘤辅助分析"


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


def run_brats_real_vlm_medsam2_diagnosis_demo(
    *,
    auto_eval_result_path: Path | str = DEFAULT_AUTO_EVAL_RESULT,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    patient_message: str = DEFAULT_PATIENT_MESSAGE,
    patient_info: dict[str, Any] | None = None,
    real: bool = False,
    model_client: ModelClient | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    auto_eval_path = Path(auto_eval_result_path)
    auto_eval = json.loads(auto_eval_path.read_text(encoding="utf-8"))
    route_log = ApiRouteLog.from_file()
    api_key_env = route_log.api_key_env_for_active_route()

    base_payload = {
        "auto_eval_result_path": str(auto_eval_path),
        "output_dir": str(output),
        "case_id": auto_eval.get("case_id"),
        "disease_key": auto_eval.get("disease_key"),
        "prompt_source": auto_eval.get("prompt_source"),
        "active_route": route_log.active_route,
        "model": route_log.model_for_active_route(),
        "api_key_env": api_key_env,
        "api_key_present": bool(os.environ.get(api_key_env)),
        "llm_attempted": False,
    }
    if auto_eval.get("status") != "ok":
        payload = {
            **base_payload,
            "status": "not_ready",
            "error": f"auto_eval status is not ok: {auto_eval.get('status')}",
        }
        _write_json(output / "summary.json", payload)
        return payload

    visual_result = dict(auto_eval["result"])
    knowledge = KnowledgeBuilderTool().load_guideline_knowledge(
        str(auto_eval.get("disease_key") or "diffuse_glioma_brats")
    )
    selected_model_client = model_client
    llm_attempted = model_client is not None
    if selected_model_client is None and real:
        _load_dotenv_local()
        if os.environ.get(api_key_env):
            selected_model_client = OpenAICompatibleModelClient(route_log=route_log)
            llm_attempted = True

    case_id = str(auto_eval.get("case_id") or "brats_real_vlm_medsam2_case")
    checked_patient_info = patient_info or {"symptoms": [], "patient_message": patient_message}
    llm_route_error = None
    prompt_runner = CapturingPromptRunner(selected_model_client) if selected_model_client else None
    try:
        agent = DiagnosisDoctorAgent(
            prompt_runner=prompt_runner
        )
        report = agent.generate_report(
            case_id=case_id,
            patient_info=checked_patient_info,
            visual_result=visual_result,
            disease_knowledge=knowledge,
        )
    except (RuntimeError, OSError) as exc:
        llm_route_error = f"{type(exc).__name__}: {exc}"
        agent = DiagnosisDoctorAgent()
        report = agent.generate_report(
            case_id=case_id,
            patient_info=checked_patient_info,
            visual_result=visual_result,
            disease_knowledge=knowledge,
        )
        report["llm_fallback_reason"] = llm_route_error
    evidence_bundle = {
        "case_id": auto_eval.get("case_id"),
        "disease_key": auto_eval.get("disease_key"),
        "prompt_source": auto_eval.get("prompt_source"),
        "image_outputs": auto_eval.get("image_outputs"),
        "evaluation": auto_eval.get("evaluation"),
        "data_boundary": auto_eval.get("data_boundary"),
        "visual_result": visual_result,
        "diagnosis_report": report,
    }
    report_path = output / "diagnosis_report.json"
    evidence_bundle_path = output / "evidence_bundle.json"
    raw_content_path = output / "llm_raw_content.json"
    _write_json(report_path, report)
    _write_json(evidence_bundle_path, evidence_bundle)
    if prompt_runner and prompt_runner.last_content is not None:
        _write_json(raw_content_path, {"content": prompt_runner.last_content})
    payload = {
        **base_payload,
        "status": "ok",
        "llm_attempted": llm_attempted,
        "real_call_requested": real,
        "report_path": str(report_path),
        "evidence_bundle_path": str(evidence_bundle_path),
        "llm_raw_content_path": str(raw_content_path)
        if prompt_runner and prompt_runner.last_content is not None
        else None,
        "diagnostic_tendency": report.get("diagnostic_tendency") or report.get("诊断倾向"),
        "used_visual_facts_count": (report.get("visual_fact_usage") or {}).get("used_count", 0),
        "excluded_visual_facts_count": (report.get("visual_fact_usage") or {}).get(
            "excluded_count", 0
        ),
        "llm_fallback_reason": llm_route_error or report.get("llm_fallback_reason"),
    }
    _write_json(output / "summary.json", payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a diagnosis report from real VLM bbox + MedSAM2 BraTS auto-eval output."
    )
    parser.add_argument("--auto-eval-result", default=str(DEFAULT_AUTO_EVAL_RESULT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--message", default=DEFAULT_PATIENT_MESSAGE)
    parser.add_argument("--real-llm", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_dotenv_local()
    payload = run_brats_real_vlm_medsam2_diagnosis_demo(
        auto_eval_result_path=args.auto_eval_result,
        output_dir=args.output_dir,
        patient_message=args.message,
        real=args.real_llm,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "ok" else 1


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_dotenv_local(path: Path = Path(".env.local")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


if __name__ == "__main__":
    raise SystemExit(main())
