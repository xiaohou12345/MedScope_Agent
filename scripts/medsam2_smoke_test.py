from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.medsam2_segmentation_tool import (
    MedSAM2CommandRunner,
    inspect_medsam2_configuration,
)


def run_medsam2_smoke_check(
    image_path: Path | str | None = None,
    mask_path: Path | str | None = None,
    prompt: dict[str, Any] | None = None,
    real: bool = False,
) -> str:
    inspection = inspect_medsam2_configuration()
    if not real:
        return json.dumps(inspection, ensure_ascii=False, indent=2)

    inspection["real_call_attempted"] = True
    if not inspection["real_call_ready"]:
        inspection["error"] = "MedSAM2 command runner is not ready."
        return json.dumps(inspection, ensure_ascii=False, indent=2)
    if image_path is None:
        inspection["error"] = "--image is required for real MedSAM2 smoke test."
        return json.dumps(inspection, ensure_ascii=False, indent=2)

    output_mask_path = Path(mask_path) if mask_path else Path("output/fake/medsam2_smoke_mask.png")
    runner = MedSAM2CommandRunner.from_env()
    try:
        result_path = runner.predict_mask(
            image_path=image_path,
            output_mask_path=output_mask_path,
            prompt=prompt or {},
        )
    except Exception as exc:  # pragma: no cover - real external runner failure path
        inspection["error"] = f"{type(exc).__name__}: {exc}"
        inspection["mask_path"] = str(output_mask_path)
        inspection["mask_created"] = output_mask_path.exists()
        return json.dumps(inspection, ensure_ascii=False, indent=2)

    mask_created = Path(result_path).exists()
    inspection["mask_path"] = str(result_path)
    inspection["mask_created"] = mask_created
    if not mask_created:
        inspection["error"] = f"MedSAM2 command finished but mask was not created: {result_path}"
    return json.dumps(inspection, ensure_ascii=False, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect or smoke-test MedSAM2 runner configuration.")
    parser.add_argument("--image", help="Input image path for --real smoke test.")
    parser.add_argument(
        "--mask",
        default="output/fake/medsam2_smoke_mask.png",
        help="Expected output mask path for --real smoke test.",
    )
    parser.add_argument(
        "--prompt-json",
        default="{}",
        help="Prompt JSON passed to MedSAM2 wrapper, for example '{\"boxes\": [[1, 1, 5, 5]]}'.",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Actually call the configured MedSAM2 command runner.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        prompt = json.loads(args.prompt_json)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"Invalid --prompt-json: {exc}"}, ensure_ascii=False, indent=2))
        sys.exit(1)

    output = run_medsam2_smoke_check(
        image_path=args.image,
        mask_path=args.mask,
        prompt=prompt,
        real=args.real,
    )
    print(output)
    payload = json.loads(output)
    if args.real and ("error" in payload or not payload.get("mask_created", False)):
        sys.exit(1)


if __name__ == "__main__":
    main()
