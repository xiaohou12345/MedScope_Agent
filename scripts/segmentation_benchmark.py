from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.prepare_public_demo_fixture import prepare_public_demo_fixture
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

    cases = [
        _evaluate_case(
            raw_case=dict(raw_case),
            prepare_fixtures=prepare_fixtures,
            evaluator=evaluator or BratsEvaluationTool(),
        )
        for raw_case in manifest.get("cases") or []
        if isinstance(raw_case, dict)
    ]
    payload = {
        "schema_version": "segmentation_benchmark_result.v1",
        "source_manifest_path": str(manifest_path),
        "source_manifest_schema_version": manifest.get("schema_version"),
        "benchmark_id": manifest.get("benchmark_id"),
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


def _evaluate_case(
    *,
    raw_case: dict[str, Any],
    prepare_fixtures: bool,
    evaluator: Any,
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
    else:
        metric_status = "metric_ready"
        metrics = evaluator.evaluate(
            prediction_mask_path=prediction,
            reference_mask_path=reference,
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
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Segmentation Benchmark Result",
        "",
        f"- `benchmark_id`: `{payload.get('benchmark_id')}`",
        f"- `benchmark_scope`: `{payload.get('benchmark_scope')}`",
        f"- `case_count`: `{payload.get('aggregate', {}).get('case_count')}`",
        f"- `metric_ready_case_count`: `{payload.get('aggregate', {}).get('metric_ready_case_count')}`",
        f"- `missing_reference_mask_count`: `{payload.get('aggregate', {}).get('missing_reference_mask_count')}`",
        "",
        "| case_id | disease | modality | backend | metric_status | diagnosis_allowed |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in payload.get("cases") or []:
        lines.append(
            "| {case_id} | {disease} | {modality} | {backend} | {status} | {diagnosis} |".format(
                case_id=case.get("case_id"),
                disease=case.get("disease_key"),
                modality=case.get("modality"),
                backend=case.get("backend_type"),
                status=case.get("metric_status"),
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
