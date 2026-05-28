from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from string import Formatter
from typing import Any


class MissingMedSAM2BackendError(RuntimeError):
    """Raised when MedSAM2 inference is requested without a configured backend."""


REQUIRED_COMMAND_TEMPLATE_PLACEHOLDERS = ("image_path", "output_mask_path", "prompt_json")


def inspect_medsam2_configuration() -> dict[str, Any]:
    command_template = _strip_wrapping_quotes(os.environ.get("MEDSAM2_COMMAND_TEMPLATE"))
    repo_path_value = os.environ.get("MEDSAM2_REPO_PATH")
    timeout_value = os.environ.get("MEDSAM2_TIMEOUT_SECONDS", "600")
    try:
        timeout_seconds: int | None = int(timeout_value)
        timeout_error = None
    except ValueError:
        timeout_seconds = None
        timeout_error = f"Invalid MEDSAM2_TIMEOUT_SECONDS: {timeout_value}"

    repo_path = Path(repo_path_value) if repo_path_value else None
    repo_path_exists = repo_path.exists() if repo_path else False
    repo_ready = repo_path is None or repo_path_exists
    missing_placeholders = _missing_command_template_placeholders(command_template)
    real_call_ready = (
        bool(command_template)
        and not missing_placeholders
        and repo_ready
        and timeout_seconds is not None
    )

    return {
        "command_template_present": bool(command_template),
        "command_template": command_template,
        "required_command_template_placeholders": list(REQUIRED_COMMAND_TEMPLATE_PLACEHOLDERS),
        "missing_command_template_placeholders": missing_placeholders,
        "repo_path": str(repo_path) if repo_path else None,
        "repo_path_present": repo_path is not None,
        "repo_path_exists": repo_path_exists,
        "timeout_seconds": timeout_seconds,
        "timeout_error": timeout_error,
        "real_call_ready": real_call_ready,
        "real_call_attempted": False,
    }


def _missing_command_template_placeholders(command_template: str | None) -> list[str]:
    if not command_template:
        return list(REQUIRED_COMMAND_TEMPLATE_PLACEHOLDERS)
    present = {
        field_name
        for _, field_name, _, _ in Formatter().parse(command_template)
        if field_name
    }
    return [
        placeholder
        for placeholder in REQUIRED_COMMAND_TEMPLATE_PLACEHOLDERS
        if placeholder not in present
    ]


def _strip_wrapping_quotes(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
        return normalized[1:-1]
    return normalized


class MedSAM2CommandRunner:
    """Runs an external MedSAM2 command configured by environment or constructor."""

    def __init__(
        self,
        command_template: str,
        repo_path: Path | str | None = None,
        timeout_seconds: int = 600,
    ) -> None:
        self.command_template = command_template
        self.repo_path = Path(repo_path) if repo_path else None
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> "MedSAM2CommandRunner":
        inspection = inspect_medsam2_configuration()
        command_template = inspection["command_template"]
        if not inspection["command_template_present"]:
            raise MissingMedSAM2BackendError(
                "MEDSAM2_COMMAND_TEMPLATE is required to configure MedSAM2 command runner."
            )
        missing_placeholders = inspection["missing_command_template_placeholders"]
        if missing_placeholders:
            raise MissingMedSAM2BackendError(
                "MEDSAM2_COMMAND_TEMPLATE missing required placeholders: "
                + ", ".join(missing_placeholders)
            )
        if inspection["timeout_error"]:
            raise MissingMedSAM2BackendError(inspection["timeout_error"])
        if inspection["repo_path_present"] and not inspection["repo_path_exists"]:
            raise MissingMedSAM2BackendError(
                f"MEDSAM2_REPO_PATH not found: {inspection['repo_path']}"
            )
        return cls(
            command_template=command_template,
            repo_path=inspection["repo_path"],
            timeout_seconds=inspection["timeout_seconds"],
        )

    def predict_mask(
        self,
        image_path: Path | str,
        output_mask_path: Path | str,
        prompt: dict[str, Any],
    ) -> str:
        resolved_image_path = Path(image_path).resolve()
        resolved_output_mask_path = Path(output_mask_path).resolve()
        command = self.command_template.format(
            image_path=shlex.quote(str(resolved_image_path)),
            output_mask_path=shlex.quote(str(resolved_output_mask_path)),
            prompt_json=shlex.quote(json.dumps(prompt, ensure_ascii=False)),
        )
        subprocess.run(
            shlex.split(command),
            cwd=str(self.repo_path) if self.repo_path else None,
            check=True,
            timeout=self.timeout_seconds,
        )
        return str(resolved_output_mask_path)


class MedSAM2SegmentationTool:
    """Adapter for a MedSAM2 inference backend.

    This class deliberately accepts an injected runner so the core agent code does
    not depend on a specific MedSAM2 checkout, weight path, or GPU runtime.
    """

    segmentation_source = "medsam2"

    def __init__(self, runner: Any | None = None) -> None:
        self.runner = runner

    def predict_mask(
        self,
        image_path: Path | str,
        output_mask_path: Path | str,
        prompt: dict[str, Any],
    ) -> Path:
        if self.runner is None:
            raise MissingMedSAM2BackendError(
                "MedSAM2 backend is not configured. Provide a runner that implements "
                "predict_mask(image_path, output_mask_path, prompt)."
            )
        output_path = Path(output_mask_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = self.runner.predict_mask(
            image_path=str(image_path),
            output_mask_path=str(output_path),
            prompt=prompt,
        )
        mask_path = Path(result) if result else output_path
        if not mask_path.exists():
            raise FileNotFoundError(f"MedSAM2 runner did not create mask: {mask_path}")
        return mask_path
