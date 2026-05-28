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


def build_medscope_medsam2_command_template(
    wrapper_path: Path | str = "scripts/medsam2_brats_wrapper.py",
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


def validate_medscope_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    if "slice_index" not in prompt:
        raise ValueError("MedSAM2 BraTS prompt requires slice_index.")
    boxes = prompt.get("boxes")
    if not boxes:
        raise ValueError("MedSAM2 BraTS prompt requires boxes.")
    first_box = boxes[0]
    if len(first_box) != 4:
        raise ValueError("MedSAM2 BraTS prompt box must have four values.")
    box = [int(value) for value in first_box]
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("MedSAM2 BraTS prompt box must satisfy x_max>x_min and y_max>y_min.")
    return {
        "slice_index": int(prompt["slice_index"]),
        "box": box,
        "label_ids": [int(value) for value in prompt.get("label_ids", [1])],
    }


def normalize_medsam2_cfg_name(cfg_path: Path | str, medsam2_repo_path: Path | str) -> str:
    cfg = Path(cfg_path)
    repo = Path(medsam2_repo_path)
    sam2_root = repo / "sam2"
    try:
        return cfg.relative_to(sam2_root).as_posix()
    except ValueError:
        return cfg.as_posix()


def run_medsam2_brats_wrapper(
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
    normalized_prompt = validate_medscope_prompt(prompt)

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
            "slice_index": normalized_prompt["slice_index"],
            "box_for_medscope": normalized_prompt["box"],
            "label_ids": normalized_prompt["label_ids"],
        },
        "errors": errors,
    }
    if errors or dry_run:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    try:
        _run_real_medsam2_inference(
            image_path=image,
            output_mask_path=output_mask,
            prompt=normalized_prompt,
            medsam2_repo_path=repo,
            checkpoint_path=Path(payload["checkpoint_path"]),
            cfg_path=Path(payload["cfg_path"]),
            device=device,
        )
    except Exception as exc:  # pragma: no cover - depends on external MedSAM2 runtime
        payload["status"] = "error"
        payload["errors"] = [f"{type(exc).__name__}: {exc}"]
        payload["mask_created"] = output_mask.exists()
        return json.dumps(payload, ensure_ascii=False, indent=2)

    payload["mask_created"] = output_mask.exists()
    if not output_mask.exists():
        payload["status"] = "error"
        payload["errors"] = [f"MedSAM2 wrapper finished but mask was not created: {output_mask}"]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _run_real_medsam2_inference(
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

    try:
        import nibabel as nib
    except ImportError as exc:
        raise RuntimeError("nibabel is required for BraTS NIfTI MedSAM2 inference.") from exc

    sys.path.insert(0, str(medsam2_repo_path))
    try:
        from sam2.build_sam import build_sam2_video_predictor_npz
    except ImportError as exc:
        raise RuntimeError(
            "Could not import MedSAM2 sam2 package. Check --medsam2-repo and install MedSAM2."
        ) from exc

    nifti_image = nib.load(str(image_path))
    volume = nifti_image.get_fdata()
    if volume.ndim == 4:
        volume = volume[:, :, :, 0]
    if volume.ndim != 3:
        raise ValueError(f"Expected 3D or 4D BraTS NIfTI image, got shape {volume.shape}.")

    frames = np.moveaxis(volume, 2, 0)
    frames_uint8 = _normalize_volume_to_uint8(frames)
    video_height, video_width = frames_uint8.shape[1], frames_uint8.shape[2]
    img_resized = _resize_grayscale_to_rgb_and_resize(frames_uint8, 512)
    img_resized = torch.from_numpy(img_resized / 255.0).to(device)
    mean = torch.tensor((0.485, 0.456, 0.406), dtype=torch.float32, device=device)[:, None, None]
    std = torch.tensor((0.229, 0.224, 0.225), dtype=torch.float32, device=device)[:, None, None]
    img_resized = (img_resized - mean) / std

    cfg_name = normalize_medsam2_cfg_name(cfg_path, medsam2_repo_path)
    predictor = build_sam2_video_predictor_npz(cfg_name, str(checkpoint_path), device=device)
    segs_by_slice = np.zeros(frames_uint8.shape, dtype=np.uint8)
    z_mid = prompt["slice_index"]
    if z_mid < 0 or z_mid >= frames_uint8.shape[0]:
        raise ValueError(f"slice_index out of range: {z_mid}; depth={frames_uint8.shape[0]}")

    medsam_box = _medscope_box_to_medsam2_box(prompt["box"])
    autocast = (
        torch.autocast(device_type="cuda", dtype=torch.bfloat16)
        if device.startswith("cuda")
        else contextlib.nullcontext()
    )
    with torch.inference_mode(), autocast:
        inference_state = predictor.init_state(img_resized, video_height, video_width)
        _, _, out_mask_logits = predictor.add_new_points_or_box(
            inference_state=inference_state,
            frame_idx=z_mid,
            obj_id=1,
            box=np.array(medsam_box),
        )
        mask_prompt = (out_mask_logits[0] > 0.0).squeeze(0).cpu().numpy().astype(np.uint8)
        _, _, masks = predictor.add_new_mask(
            inference_state,
            frame_idx=z_mid,
            obj_id=1,
            mask=mask_prompt,
        )
        segs_by_slice[z_mid, ((masks[0] > 0.0).cpu().numpy())[0]] = 1
        for out_frame_idx, _, out_mask_logits in predictor.propagate_in_video(
            inference_state,
            start_frame_idx=z_mid,
            reverse=False,
        ):
            segs_by_slice[out_frame_idx, (out_mask_logits[0] > 0.0).cpu().numpy()[0]] = 1
        predictor.reset_state(inference_state)

        inference_state = predictor.init_state(img_resized, video_height, video_width)
        predictor.add_new_mask(inference_state, frame_idx=z_mid, obj_id=1, mask=mask_prompt)
        for out_frame_idx, _, out_mask_logits in predictor.propagate_in_video(
            inference_state,
            start_frame_idx=z_mid,
            reverse=True,
        ):
            segs_by_slice[out_frame_idx, (out_mask_logits[0] > 0.0).cpu().numpy()[0]] = 1
        predictor.reset_state(inference_state)

    segs_volume = np.moveaxis(segs_by_slice, 0, 2).astype(np.uint8)
    output_mask_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(segs_volume, nifti_image.affine, nifti_image.header), str(output_mask_path))


def _normalize_volume_to_uint8(volume: Any) -> Any:
    import numpy as np

    finite = volume[np.isfinite(volume)]
    if finite.size == 0:
        return np.zeros(volume.shape, dtype=np.uint8)
    nonzero = finite[finite != 0]
    reference = nonzero if nonzero.size else finite
    low, high = np.percentile(reference, [0.5, 99.5])
    if high <= low:
        low, high = float(reference.min()), float(reference.max())
    if high <= low:
        return np.zeros(volume.shape, dtype=np.uint8)
    clipped = np.clip(volume, low, high)
    scaled = (clipped - low) / (high - low) * 255.0
    scaled[volume == 0] = 0
    return scaled.astype(np.uint8)


def _resize_grayscale_to_rgb_and_resize(volume: Any, image_size: int) -> Any:
    import numpy as np
    from PIL import Image

    depth = volume.shape[0]
    resized = np.zeros((depth, 3, image_size, image_size), dtype=np.float32)
    for index in range(depth):
        image = Image.fromarray(volume[index].astype(np.uint8)).convert("RGB")
        image = image.resize((image_size, image_size))
        resized[index] = np.asarray(image).transpose(2, 0, 1)
    return resized


def _medscope_box_to_medsam2_box(box: list[int]) -> list[int]:
    x_min, y_min, x_max, y_max = box
    return [y_min, x_min, y_max, x_max]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MedScope wrapper for MedSAM2 BraTS NIfTI inference.")
    parser.add_argument("--image", help="Input BraTS image .nii/.nii.gz path.")
    parser.add_argument("--output", help="Output binary mask .nii/.nii.gz path.")
    parser.add_argument("--prompt-json", help="MedScope prompt JSON with slice_index and boxes.")
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
            build_medscope_medsam2_command_template(
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
    output = run_medsam2_brats_wrapper(
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
