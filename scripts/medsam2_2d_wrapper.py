from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any


DEFAULT_CFG = "sam2/configs/sam2.1_hiera_t512.yaml"
DEFAULT_CHECKPOINT = "checkpoints/MedSAM2_latest.pt"


def build_medscope_medsam2_2d_command_template(
    wrapper_path: Path | str = "scripts/medsam2_2d_wrapper.py",
    medsam2_repo_path: Path | str = "/path/to/MedSAM2",
    checkpoint_path: Path | str | None = None,
    cfg_path: Path | str | None = None,
    device: str = "cuda",
) -> str:
    parts = [
        "python",
        shlex.quote(str(wrapper_path)),
        "--image",
        "{image_path}",
        "--output",
        "{output_mask_path}",
        "--prompt-json",
        "{prompt_json}",
        "--medsam2-repo",
        shlex.quote(str(medsam2_repo_path)),
        "--device",
        shlex.quote(device),
    ]
    if checkpoint_path:
        parts.extend(["--checkpoint", shlex.quote(str(checkpoint_path))])
    if cfg_path:
        parts.extend(["--cfg", shlex.quote(str(cfg_path))])
    return " ".join(parts)


def validate_2d_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    boxes = prompt.get("boxes")
    if not boxes:
        raise ValueError("MedSAM2 2D prompt requires boxes.")
    first_box = boxes[0]
    if not isinstance(first_box, list) or len(first_box) != 4:
        raise ValueError("MedSAM2 2D prompt box must have four values.")
    box = [int(value) for value in first_box]
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("MedSAM2 2D prompt box must satisfy x_max>x_min and y_max>y_min.")
    return {"box": box}


def normalize_medsam2_cfg_name(cfg_path: Path | str, medsam2_repo_path: Path | str) -> str:
    cfg = Path(cfg_path)
    repo = Path(medsam2_repo_path)
    sam2_root = repo / "sam2"
    try:
        return cfg.relative_to(sam2_root).as_posix()
    except ValueError:
        return cfg.as_posix()


def run_medsam2_2d_wrapper(
    image_path: Path | str,
    output_mask_path: Path | str,
    prompt: dict[str, Any],
    medsam2_repo_path: Path | str | None = None,
    checkpoint_path: Path | str | None = None,
    cfg_path: Path | str | None = None,
    device: str = "cuda",
    dry_run: bool = False,
) -> str:
    image = Path(image_path)
    output_mask = Path(output_mask_path)
    repo_value = medsam2_repo_path or os.environ.get("MEDSAM2_REPO_PATH")
    repo = Path(repo_value) if repo_value else None
    normalized_prompt = validate_2d_prompt(prompt)
    resolved_checkpoint = Path(checkpoint_path or (repo / DEFAULT_CHECKPOINT if repo else DEFAULT_CHECKPOINT))
    resolved_cfg = Path(cfg_path or (repo / DEFAULT_CFG if repo else DEFAULT_CFG))

    errors: list[str] = []
    if not image.exists():
        errors.append(f"image not found: {image}")
    if repo is None:
        errors.append("--medsam2-repo or MEDSAM2_REPO_PATH is required.")
    elif not repo.exists():
        errors.append(f"medsam2 repo not found: {repo}")
    if not resolved_checkpoint.exists():
        errors.append(f"checkpoint not found: {resolved_checkpoint}")
    if not resolved_cfg.exists():
        errors.append(f"cfg not found: {resolved_cfg}")

    payload: dict[str, Any] = {
        "status": "ok" if not errors else "error",
        "real_call_attempted": not dry_run,
        "image_path": str(image),
        "output_mask_path": str(output_mask),
        "medsam2_repo_path": str(repo) if repo is not None else None,
        "checkpoint_path": str(resolved_checkpoint),
        "cfg_path": str(resolved_cfg),
        "device": device,
        "prompt": {
            "box": normalized_prompt["box"],
        },
        "errors": errors,
    }
    if errors or dry_run:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    try:
        _run_real_medsam2_2d_inference(
            image_path=image,
            output_mask_path=output_mask,
            prompt=normalized_prompt,
            medsam2_repo_path=repo,
            checkpoint_path=Path(payload["checkpoint_path"]),
            cfg_path=Path(payload["cfg_path"]),
            device=device,
        )
    except Exception as exc:  # pragma: no cover - external MedSAM2 runtime
        payload["status"] = "error"
        payload["errors"] = [f"{type(exc).__name__}: {exc}"]
        payload["mask_created"] = output_mask.exists()
        return json.dumps(payload, ensure_ascii=False, indent=2)

    payload["mask_created"] = output_mask.exists()
    if not output_mask.exists():
        payload["status"] = "error"
        payload["errors"] = [f"MedSAM2 wrapper finished but mask was not created: {output_mask}"]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _run_real_medsam2_2d_inference(
    *,
    image_path: Path,
    output_mask_path: Path,
    prompt: dict[str, Any],
    medsam2_repo_path: Path,
    checkpoint_path: Path,
    cfg_path: Path,
    device: str,
) -> None:
    import numpy as np
    import torch
    from PIL import Image

    sys.path.insert(0, str(medsam2_repo_path))
    try:
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor
    except ImportError as exc:
        raise RuntimeError(
            "Could not import MedSAM2 sam2 image predictor. Check --medsam2-repo and install MedSAM2."
        ) from exc

    image = Image.open(image_path).convert("RGB")
    cfg_name = normalize_medsam2_cfg_name(cfg_path, medsam2_repo_path)
    autocast = (
        torch.autocast(device_type="cuda", dtype=torch.bfloat16)
        if device.startswith("cuda")
        else contextlib.nullcontext()
    )
    with torch.inference_mode(), autocast:
        sam2_model = build_sam2(cfg_name, str(checkpoint_path), device=device)
        predictor = SAM2ImagePredictor(sam2_model)
        predictor.set_image(image)
        masks, scores, _ = predictor.predict(
            point_coords=None,
            point_labels=None,
            box=np.array(prompt["box"])[None, :],
            multimask_output=False,
        )
    mask = (masks[0] > 0).astype("uint8") * 255
    output_mask_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mask).save(output_mask_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MedScope wrapper for MedSAM2 2D image inference.")
    parser.add_argument("--image", help="Input PNG/JPG image path.")
    parser.add_argument("--output", help="Output binary mask PNG path.")
    parser.add_argument("--prompt-json", help="MedScope prompt JSON with boxes.")
    parser.add_argument("--medsam2-repo", default=os.environ.get("MEDSAM2_REPO_PATH"))
    parser.add_argument("--checkpoint")
    parser.add_argument("--cfg")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--print-command-template",
        action="store_true",
        help="Print a MEDSAM2_COMMAND_TEMPLATE using this wrapper and exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.print_command_template:
        print(
            build_medscope_medsam2_2d_command_template(
                wrapper_path=Path(__file__).resolve(),
                medsam2_repo_path=args.medsam2_repo or "/path/to/MedSAM2",
                checkpoint_path=args.checkpoint,
                cfg_path=args.cfg,
                device=args.device,
            )
        )
        return
    missing = [
        option
        for option, value in (
            ("--image", args.image),
            ("--output", args.output),
            ("--prompt-json", args.prompt_json),
        )
        if not value
    ]
    if missing:
        print(
            json.dumps(
                {"status": "error", "errors": [f"Missing required arguments: {', '.join(missing)}"]},
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)
    try:
        prompt = json.loads(args.prompt_json)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "errors": [f"Invalid --prompt-json: {exc}"]}, indent=2))
        sys.exit(1)
    output = run_medsam2_2d_wrapper(
        image_path=args.image,
        output_mask_path=args.output,
        prompt=prompt,
        medsam2_repo_path=args.medsam2_repo,
        checkpoint_path=args.checkpoint,
        cfg_path=args.cfg,
        device=args.device,
        dry_run=args.dry_run,
    )
    print(output)
    payload = json.loads(output)
    if payload.get("status") != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
