from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.prepare_public_demo_fixture import prepare_public_demo_fixture
from tools.binary_segmentation_evaluation_tool import BinarySegmentationEvaluationTool
from tools.brats_evaluation_tool import BratsEvaluationTool


DEFAULT_FHN_PUBLIC_FIXTURE_MANIFEST = Path(
    "benchmarks/segmentation/femoral_head_necrosis/public_fixture_manifest.json"
)
DEFAULT_OUTPUT_DIR = Path("output/fake/segmentation_benchmark")


def run_segmentation_benchmark(
    *,
    manifest_path: Path | str = DEFAULT_FHN_PUBLIC_FIXTURE_MANIFEST,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    prepare_fixtures: bool = False,
    evaluator: Any | None = None,
) -> dict[str, Any]:
    manifest = _read_json(Path(manifest_path))
    _validate_manifest(manifest)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    evaluator_type = str(manifest.get("evaluator_type") or "brats_regions")
    selected_evaluator = evaluator or _build_evaluator(evaluator_type)

    cases = [
        _evaluate_case(
            raw_case=dict(raw_case),
            prepare_fixtures=prepare_fixtures,
            evaluator=selected_evaluator,
            metric_gates=dict(manifest.get("metric_gates") or {}),
        )
        for raw_case in manifest.get("cases") or []
        if isinstance(raw_case, dict)
    ]
    payload = {
        "schema_version": "segmentation_benchmark_result.v1",
        "source_manifest_path": str(manifest_path),
        "source_manifest_schema_version": manifest.get("schema_version"),
        "benchmark_id": manifest.get("benchmark_id"),
        "evaluator_type": evaluator_type,
        "benchmark_scope": manifest.get(
            "benchmark_scope",
            "disease_specific_segmentation_validation",
        ),
        "safety": {
            "web_demo_independent": bool(
                (manifest.get("safety") or {}).get("web_demo_independent", True)
            ),
            "not_clinical_diagnosis": bool(
                (manifest.get("safety") or {}).get("not_clinical_diagnosis", True)
            ),
            "formal_skill_update_allowed": bool(
                (manifest.get("safety") or {}).get("formal_skill_update_allowed", False)
            ),
        },
        "aggregate": _aggregate(cases),
        "cases": cases,
    }
    json_path = output / "segmentation_benchmark_result.json"
    markdown_path = output / "segmentation_benchmark_result.md"
    payload["output_paths"] = {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    _write_json(json_path, payload)
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _build_evaluator(evaluator_type: str) -> Any:
    if evaluator_type == "binary_mask":
        return BinarySegmentationEvaluationTool()
    if evaluator_type == "brats_regions":
        return BratsEvaluationTool()
    raise ValueError(f"unsupported segmentation benchmark evaluator_type: {evaluator_type}")


def _evaluate_case(
    *,
    raw_case: dict[str, Any],
    prepare_fixtures: bool,
    evaluator: Any,
    metric_gates: dict[str, Any],
) -> dict[str, Any]:
    case = dict(raw_case)
    if prepare_fixtures and case.get("fixture_generator") == "scripts.prepare_public_demo_fixture":
        fixture = prepare_public_demo_fixture(
            output_dir=Path(str(case.get("fixture_output_dir") or "output/fake/public_demo_fixture"))
        )
        case["image_path"] = fixture["image_path"]
        case["fixture_manifest_path"] = fixture["manifest_path"]
    _validate_case_paths(case)

    prediction = case.get("prediction_mask_path")
    reference = case.get("reference_mask_path")
    limitations = list(case.get("limitations") or [])
    metrics = None
    if not reference:
        metric_status = "missing_reference_mask"
        limitations.append("segmentation metrics require reference_mask_path")
    elif not prediction:
        metric_status = "missing_prediction_mask"
        limitations.append("segmentation metrics require prediction_mask_path")
    elif not Path(str(reference)).exists():
        metric_status = "missing_reference_file"
        limitations.append("reference_mask_path does not exist")
    elif not Path(str(prediction)).exists():
        metric_status = "missing_prediction_file"
        limitations.append("prediction_mask_path does not exist")
    else:
        metric_status = "metric_ready"
        metrics = evaluator.evaluate(
            prediction_mask_path=prediction,
            reference_mask_path=reference,
        )
    quality_gate = _evaluate_metric_gate(
        metric_status=metric_status,
        metrics=metrics,
        metric_gates=metric_gates,
    )

    return {
        "case_id": case.get("case_id"),
        "disease_key": case.get("disease_key"),
        "modality": case.get("modality"),
        "body_part": case.get("body_part"),
        "backend_type": case.get("backend_type"),
        "benchmark_role": case.get("benchmark_role"),
        "image_path": case.get("image_path"),
        "prediction_mask_path": prediction,
        "reference_mask_path": reference,
        "metric_status": metric_status,
        "metrics": metrics,
        "quality_gate": quality_gate,
        "diagnosis_allowed": False,
        "formal_skill_update_allowed": False,
        "limitations": limitations,
    }


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != "segmentation_benchmark_manifest.v1":
        raise ValueError("unsupported segmentation benchmark manifest schema_version")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("segmentation benchmark manifest cases must be a non-empty list")
    if not (manifest.get("safety") or {}).get("web_demo_independent", True):
        raise ValueError("segmentation benchmark must be independent from web demo artifacts")


def _validate_case_paths(case: dict[str, Any]) -> None:
    for key in ("image_path", "prediction_mask_path", "reference_mask_path"):
        value = case.get(key)
        if value is None:
            continue
        normalized = str(value).replace("\\", "/").lower()
        if normalized.startswith("web/") or "/web/" in normalized:
            raise ValueError(f"{key} points to a web demo artifact: {value}")
        if "output/real" in normalized:
            raise ValueError(f"{key} points to ignored real output artifact: {value}")


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "case_count": len(cases),
        "metric_ready_case_count": sum(
            1 for case in cases if case.get("metric_status") == "metric_ready"
        ),
        "missing_reference_mask_count": sum(
            1 for case in cases if case.get("metric_status") == "missing_reference_mask"
        ),
        "missing_prediction_mask_count": sum(
            1 for case in cases if case.get("metric_status") == "missing_prediction_mask"
        ),
        "missing_reference_file_count": sum(
            1 for case in cases if case.get("metric_status") == "missing_reference_file"
        ),
        "missing_prediction_file_count": sum(
            1 for case in cases if case.get("metric_status") == "missing_prediction_file"
        ),
        "metric_pass_case_count": sum(
            1 for case in cases if (case.get("quality_gate") or {}).get("status") == "pass"
        ),
        "metric_fail_case_count": sum(
            1 for case in cases if (case.get("quality_gate") or {}).get("status") == "fail"
        ),
    }


def _evaluate_metric_gate(
    *,
    metric_status: str,
    metrics: dict[str, Any] | None,
    metric_gates: dict[str, Any],
) -> dict[str, Any]:
    if metric_status != "metric_ready":
        return {
            "status": "not_applicable",
            "reason": f"case metric_status is {metric_status}",
            "required_metrics": [],
            "minimums": {},
            "failed_metrics": [],
            "missing_metrics": [],
        }
    required_metrics = list(metric_gates.get("required_metrics") or [])
    minimums = dict(metric_gates.get("minimums") or {})
    if not required_metrics and not minimums:
        return {
            "status": "not_configured",
            "reason": "manifest does not define metric_gates",
            "required_metrics": [],
            "minimums": {},
            "failed_metrics": [],
            "missing_metrics": [],
        }

    metric_values = metrics or {}
    required = sorted(set(required_metrics) | set(minimums))
    missing = [name for name in required if name not in metric_values]
    failed = [
        name
        for name, minimum in minimums.items()
        if name in metric_values
        and metric_values[name] is not None
        and float(metric_values[name]) < float(minimum)
    ]
    status = "pass" if not missing and not failed else "fail"
    return {
        "status": status,
        "required_metrics": required,
        "minimums": minimums,
        "failed_metrics": failed,
        "missing_metrics": missing,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Segmentation Benchmark Result",
        "",
        f"- `benchmark_id`: `{payload.get('benchmark_id')}`",
        f"- `benchmark_scope`: `{payload.get('benchmark_scope')}`",
        f"- `case_count`: `{payload.get('aggregate', {}).get('case_count')}`",
        f"- `metric_ready_case_count`: `{payload.get('aggregate', {}).get('metric_ready_case_count')}`",
        f"- `metric_pass_case_count`: `{payload.get('aggregate', {}).get('metric_pass_case_count')}`",
        f"- `metric_fail_case_count`: `{payload.get('aggregate', {}).get('metric_fail_case_count')}`",
        f"- `missing_reference_mask_count`: `{payload.get('aggregate', {}).get('missing_reference_mask_count')}`",
        f"- `missing_reference_file_count`: `{payload.get('aggregate', {}).get('missing_reference_file_count')}`",
        f"- `missing_prediction_file_count`: `{payload.get('aggregate', {}).get('missing_prediction_file_count')}`",
        "",
        "| case_id | disease | modality | backend | metric_status | quality_gate | diagnosis_allowed |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in payload.get("cases") or []:
        lines.append(
            "| {case_id} | {disease} | {modality} | {backend} | {status} | {quality_gate} | {diagnosis} |".format(
                case_id=case.get("case_id"),
                disease=case.get("disease_key"),
                modality=case.get("modality"),
                backend=case.get("backend_type"),
                status=case.get("metric_status"),
                quality_gate=(case.get("quality_gate") or {}).get("status"),
                diagnosis=case.get("diagnosis_allowed"),
            )
        )
    lines.extend(
        [
            "",
            "Safety boundary: benchmark outputs are validation artifacts only. They do not update",
            "formal skills and cannot be used as clinical diagnosis reports.",
        ]
    )
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a manifest-driven segmentation benchmark.")
    parser.add_argument("--manifest", default=str(DEFAULT_FHN_PUBLIC_FIXTURE_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--prepare-fixtures", action="store_true")
    args = parser.parse_args(argv)
    result = run_segmentation_benchmark(
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        prepare_fixtures=args.prepare_fixtures,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
