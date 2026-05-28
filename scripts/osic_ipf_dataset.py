from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_OSIC_MANIFEST = Path("data/external/osic_ipf_manifest.json")
EXPECTED_DATASET = "OSIC Pulmonary Fibrosis Progression"
EXPECTED_DISEASE_KEY = "idiopathic_pulmonary_fibrosis_hrct"


def validate_osic_manifest(manifest_path: Path | str = DEFAULT_OSIC_MANIFEST) -> str:
    manifest = Path(manifest_path)
    payload = _load_manifest(manifest)
    cases = payload.get("cases") or []
    access = _normalized_access(payload)
    data_boundary = _normalized_data_boundary(payload)
    manifest_errors: list[str] = []

    if payload.get("dataset") != EXPECTED_DATASET:
        manifest_errors.append(f"dataset must be {EXPECTED_DATASET}")
    if payload.get("disease_key") != EXPECTED_DISEASE_KEY:
        manifest_errors.append(f"disease_key must be {EXPECTED_DISEASE_KEY}")

    case_results = [
        _validate_case(case=case, index=index, manifest_dir=manifest.parent)
        for index, case in enumerate(cases)
    ]
    valid_count = sum(1 for case in case_results if case["status"] == "ok")
    if manifest_errors:
        status = "invalid"
    elif not cases:
        status = "pending_download"
    elif valid_count == len(cases):
        status = "ok"
    else:
        status = "invalid"

    result = {
        "status": status,
        "manifest_path": str(manifest),
        "dataset": payload.get("dataset"),
        "disease_key": payload.get("disease_key"),
        "disease_name": payload.get("disease_name"),
        "access": access,
        "data_boundary": data_boundary,
        "case_count": len(cases),
        "valid_count": valid_count,
        "errors": manifest_errors,
        "invalid_case_ids": [
            case["case_id"] for case in case_results if case["status"] != "ok"
        ],
        "cases": case_results,
    }
    if status == "pending_download":
        result["action_items"] = [
            "Download OSIC CT data from Kaggle after accepting the competition terms.",
            "Add local CT case paths to data/external/osic_ipf_manifest.json.",
            "Optionally add lung_mask_path for anatomy normalization; do not treat lung masks as fibrosis labels.",
        ]
    return json.dumps(result, ensure_ascii=False, indent=2)


def check_osic_download_readiness(
    manifest_path: Path | str = DEFAULT_OSIC_MANIFEST,
    kaggle_config_path: Path | str | None = None,
) -> str:
    manifest_validation = json.loads(validate_osic_manifest(manifest_path))
    config_path = Path(kaggle_config_path) if kaggle_config_path else Path.home() / ".kaggle" / "kaggle.json"
    config_present = config_path.exists()
    requires_auth = bool(manifest_validation.get("access", {}).get("requires_kaggle_login"))
    if requires_auth and not config_present:
        status = "needs_auth"
    elif manifest_validation.get("status") == "ok":
        status = "ready"
    else:
        status = "pending_download"

    action_items: list[str] = []
    if requires_auth and not config_present:
        action_items.append("Create Kaggle API credentials at ~/.kaggle/kaggle.json or pass an explicit kaggle_config_path.")
    if manifest_validation.get("status") == "pending_download":
        action_items.extend(manifest_validation.get("action_items", []))
    if manifest_validation.get("status") == "invalid":
        action_items.append("Fix invalid OSIC manifest case paths before running IPF visual demo.")

    result = {
        "status": status,
        "manifest_path": str(Path(manifest_path)),
        "kaggle_config_path": str(config_path),
        "kaggle_config_present": config_present,
        "manifest_validation": manifest_validation,
        "action_items": action_items,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate OSIC/IPF CT dataset manifest and download readiness."
    )
    parser.add_argument("--manifest", default=str(DEFAULT_OSIC_MANIFEST))
    parser.add_argument("--validate-manifest", action="store_true")
    parser.add_argument("--check-download-readiness", action="store_true")
    parser.add_argument("--kaggle-config-path", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check_download_readiness:
        output = check_osic_download_readiness(
            manifest_path=args.manifest,
            kaggle_config_path=args.kaggle_config_path,
        )
    else:
        output = validate_osic_manifest(args.manifest)
    print(output)
    return 0


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalized_access(payload: dict[str, Any]) -> dict[str, Any]:
    access = dict(payload.get("access") or {})
    access.setdefault("requires_kaggle_login", True)
    access.setdefault(
        "competition_url",
        "https://www.kaggle.com/c/osic-pulmonary-fibrosis-progression",
    )
    return access


def _normalized_data_boundary(payload: dict[str, Any]) -> dict[str, Any]:
    boundary = dict(payload.get("data_boundary") or {})
    boundary.setdefault("ct_role", "raw_medical_image_input")
    boundary.setdefault("lung_mask_role", "anatomy_mask_not_fibrosis_ground_truth")
    boundary.setdefault("fibrosis_mask_role", "not_available_by_default")
    return boundary


def _validate_case(case: dict[str, Any], index: int, manifest_dir: Path) -> dict[str, Any]:
    case_id = str(case.get("case_id") or f"case_{index}")
    errors: list[str] = []
    resolved_paths: dict[str, str | None] = {}

    if not case.get("case_id"):
        errors.append("case_id is required")
    for key, required in (
        ("ct_path", True),
        ("lung_mask_path", False),
        ("metadata_path", False),
        ("fibrosis_mask_path", False),
    ):
        value = case.get(key)
        if not value:
            if required:
                errors.append(f"{key} is required")
            resolved_paths[key] = None
            continue
        resolved = _resolve_manifest_path(str(value), manifest_dir)
        resolved_paths[key] = str(resolved)
        if not resolved.exists():
            errors.append(f"{key} not found: {resolved}")

    label_boundary = {
        "lung_mask_status": "available_anatomy_only" if resolved_paths.get("lung_mask_path") else "not_available",
        "fibrosis_mask_status": "available" if resolved_paths.get("fibrosis_mask_path") else "not_available",
        "warning": "Lung masks can normalize anatomy and distribution only; they are not fibrosis lesion labels.",
    }
    return {
        "case_id": case_id,
        "status": "invalid" if errors else "ok",
        "errors": errors,
        "resolved_paths": resolved_paths,
        "label_boundary": label_boundary,
    }


def _resolve_manifest_path(path_value: str, manifest_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return manifest_dir / path


if __name__ == "__main__":
    raise SystemExit(main())
