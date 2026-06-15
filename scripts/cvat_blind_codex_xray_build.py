from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image, ImageOps
from scipy import ndimage


DEFAULT_SIDE_EVAL = Path(
    "output/fake/original_flow_mock_roi_side_prompt_runner_34_completed_20260611/"
    "side_level_eval.csv"
)
DEFAULT_ROI_INDEX = Path(
    "/data/gongwenxin/workspace/onfh/outputs/"
    "onfh_xray_6jobs_femoral_roi_consensus_20260604/roi_index.csv"
)
DEFAULT_OUTPUT = Path("output/fake/codex_blind_xray_direct_stage_20260613")

IMAGE_LEFT_FOR_PATIENT_SIDE = {
    "右": "left",
    "左": "right",
}


@dataclass(frozen=True)
class Component:
    label: int
    area: int
    x1: int
    y1: int
    x2: int
    y2: int
    cx: float
    cy: float

    @property
    def image_side(self) -> str:
        return "left" if self.cx < 0 else "right"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build leakage-controlled blind Xray ROI inputs for direct Codex staging."
    )
    parser.add_argument("--side-eval", type=Path, default=DEFAULT_SIDE_EVAL)
    parser.add_argument("--roi-index", type=Path, default=DEFAULT_ROI_INDEX)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--experiment",
        choices=["roi_crop", "gt_mask", "roi_plus_gt_mask"],
        default="roi_crop",
        help="Blind input variant to materialize.",
    )
    parser.add_argument("--padding-ratio", type=float, default=0.35)
    parser.add_argument("--min-padding", type=int, default=80)
    parser.add_argument("--limit", type=int, default=0, help="Optional first-N subset for smoke build.")
    parser.add_argument("--force", action="store_true", help="Replace the experiment directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    exp_dir = args.output_dir / args.experiment
    public_dir = exp_dir / "public"
    private_dir = exp_dir / "private"
    image_dir = public_dir / "images"
    if exp_dir.exists() and args.force:
        shutil.rmtree(exp_dir)
    image_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)

    rows = _load_rows(args.side_eval, args.roi_index)
    if args.limit:
        rows = rows[: args.limit]

    public_rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for idx, row in enumerate(rows, start=1):
        case_id = f"case_{idx:04d}"
        image = Image.open(row["roi_source_image_path"]).convert("RGB")
        roi_mask = np.array(Image.open(row["roi_mask_path"]).convert("L")) > 0
        lesion_mask = _read_optional_mask(row.get("doctor_mask_path"))

        components = _components(roi_mask, min_area=500)
        selected, selection_warning = _select_component(
            components=components,
            patient_side=str(row["patient_side"]),
            image_width=image.width,
        )
        if selection_warning:
            warnings.append({"case_id": case_id, **selection_warning})

        crop_box = _padded_box(
            selected.x1,
            selected.y1,
            selected.x2,
            selected.y2,
            image.width,
            image.height,
            padding_ratio=args.padding_ratio,
            min_padding=args.min_padding,
        )
        out_path = image_dir / f"{case_id}.png"
        if args.experiment == "roi_crop":
            output_image = image.crop(crop_box)
        elif args.experiment == "gt_mask":
            output_image = _mask_only_image(lesion_mask, image.size, crop_box)
        else:
            output_image = _roi_with_mask_overlay(image, lesion_mask, crop_box)
        output_image.save(out_path)

        public_rows.append(
            {
                "case_id": case_id,
                "image_file": f"images/{case_id}.png",
            }
        )
        private_rows.append(
            {
                "case_id": case_id,
                "experiment": args.experiment,
                "gt_xray_stage": _normalize_stage(row["gt_xray_stage"]),
                "patient_key": row["patient_key"],
                "patient_side": row["patient_side"],
                "image_id": row["image_id"],
                "source_image_path": row["image_path"],
                "roi_source_image_path": row["roi_source_image_path"],
                "roi_mask_path": row["roi_mask_path"],
                "doctor_mask_path": row.get("doctor_mask_path") or "",
                "doctor_overlay_path": row.get("doctor_overlay_path") or "",
                "selected_component_count": len(components),
                "selected_component_area": selected.area,
                "selected_component_image_side": _image_half(selected.cx, image.width),
                "target_image_side": IMAGE_LEFT_FOR_PATIENT_SIDE.get(str(row["patient_side"]), ""),
                "crop_x1": crop_box[0],
                "crop_y1": crop_box[1],
                "crop_x2": crop_box[2],
                "crop_y2": crop_box[3],
                "blind_image_path": str(out_path),
            }
        )

    _write_csv(public_dir / "cases.csv", public_rows)
    _write_csv(private_dir / "private_index.csv", private_rows)
    (private_dir / "private_index.json").write_text(
        json.dumps(private_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (private_dir / "selection_warnings.json").write_text(
        json.dumps(warnings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_task_readme(public_dir / "TASK.md", args.experiment, len(public_rows))
    _write_root_readme(exp_dir / "README.md", args.experiment, len(public_rows), warnings)
    print(f"Built {len(public_rows)} blind cases under {exp_dir}")
    print(f"Public input: {public_dir}")
    print(f"Private index: {private_dir / 'private_index.csv'}")
    if warnings:
        print(f"Selection warnings: {len(warnings)}; see {private_dir / 'selection_warnings.json'}")


def _load_rows(side_eval_path: Path, roi_index_path: Path) -> list[dict[str, Any]]:
    side = pd.read_csv(side_eval_path)
    roi = pd.read_csv(roi_index_path).rename(
        columns={
            "mask_path": "roi_mask_path",
            "image_copy_path": "roi_source_image_path",
        }
    )
    merged = side.merge(
        roi[["source_path", "roi_mask_path", "roi_source_image_path"]],
        left_on="image_path",
        right_on="source_path",
        how="left",
    )
    missing = merged[merged["roi_mask_path"].isna()]
    if len(missing):
        raise RuntimeError(f"{len(missing)} side rows have no matched ROI mask")
    merged = merged.sort_values(["image_id", "patient_side"]).reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for row in merged.to_dict(orient="records"):
        rows.append(
            {
                "image_id": int(row["image_id"]),
                "image_path": str(row["image_path"]),
                "patient_key": str(row["patient_key"]),
                "patient_side": str(row["patient_side"]),
                "gt_xray_stage": str(row["gt_xray_stage"]),
                "roi_mask_path": str(row["roi_mask_path"]),
                "roi_source_image_path": str(row["roi_source_image_path"]),
                "doctor_mask_path": str(row.get("mask_path") or ""),
                "doctor_overlay_path": str(row.get("overlay_path") or ""),
            }
        )
    return rows


def _components(mask: np.ndarray, min_area: int) -> list[Component]:
    labels, count = ndimage.label(mask)
    components: list[Component] = []
    for label in range(1, count + 1):
        ys, xs = np.where(labels == label)
        area = int(xs.size)
        if area < min_area:
            continue
        components.append(
            Component(
                label=label,
                area=area,
                x1=int(xs.min()),
                y1=int(ys.min()),
                x2=int(xs.max()) + 1,
                y2=int(ys.max()) + 1,
                cx=float((xs.min() + xs.max()) / 2),
                cy=float((ys.min() + ys.max()) / 2),
            )
        )
    components.sort(key=lambda item: item.area, reverse=True)
    if not components:
        ys, xs = np.where(mask)
        if xs.size == 0:
            raise RuntimeError("ROI mask has no foreground")
        components.append(
            Component(
                label=1,
                area=int(xs.size),
                x1=int(xs.min()),
                y1=int(ys.min()),
                x2=int(xs.max()) + 1,
                y2=int(ys.max()) + 1,
                cx=float((xs.min() + xs.max()) / 2),
                cy=float((ys.min() + ys.max()) / 2),
            )
        )
    return components


def _select_component(
    *,
    components: list[Component],
    patient_side: str,
    image_width: int,
) -> tuple[Component, dict[str, Any] | None]:
    target = IMAGE_LEFT_FOR_PATIENT_SIDE.get(patient_side)
    if not target:
        return components[0], {"reason": "unknown_patient_side", "patient_side": patient_side}
    if len(components) == 1:
        selected = components[0]
        actual = _image_half(selected.cx, image_width)
        warning = None
        if actual != target:
            warning = {
                "reason": "single_component_not_on_expected_half",
                "patient_side": patient_side,
                "target_image_side": target,
                "selected_image_side": actual,
            }
        return selected, warning
    candidates = [item for item in components if _image_half(item.cx, image_width) == target]
    if candidates:
        return max(candidates, key=lambda item: item.area), None
    selected = min(
        components,
        key=lambda item: abs(item.cx - (image_width * (0.25 if target == "left" else 0.75))),
    )
    return selected, {
        "reason": "no_component_on_expected_half",
        "patient_side": patient_side,
        "target_image_side": target,
        "selected_image_side": _image_half(selected.cx, image_width),
    }


def _image_half(cx: float, width: int) -> str:
    return "left" if cx < width / 2 else "right"


def _padded_box(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    width: int,
    height: int,
    *,
    padding_ratio: float,
    min_padding: int,
) -> tuple[int, int, int, int]:
    box_w = x2 - x1
    box_h = y2 - y1
    pad = max(min_padding, int(math.ceil(max(box_w, box_h) * padding_ratio)))
    return (
        max(0, x1 - pad),
        max(0, y1 - pad),
        min(width, x2 + pad),
        min(height, y2 + pad),
    )


def _read_optional_mask(path_value: Any) -> np.ndarray | None:
    path = Path(str(path_value or ""))
    if not path.exists():
        return None
    return np.array(Image.open(path).convert("L")) > 0


def _mask_only_image(
    lesion_mask: np.ndarray | None,
    image_size: tuple[int, int],
    crop_box: tuple[int, int, int, int],
) -> Image.Image:
    width, height = image_size
    mask = np.zeros((height, width), dtype=np.uint8)
    if lesion_mask is not None:
        mask[: lesion_mask.shape[0], : lesion_mask.shape[1]] = (lesion_mask > 0).astype(np.uint8) * 255
    return Image.fromarray(mask, mode="L").crop(crop_box).convert("RGB")


def _roi_with_mask_overlay(
    image: Image.Image,
    lesion_mask: np.ndarray | None,
    crop_box: tuple[int, int, int, int],
) -> Image.Image:
    crop = image.crop(crop_box).convert("RGBA")
    if lesion_mask is None:
        return crop.convert("RGB")
    x1, y1, x2, y2 = crop_box
    local_mask = lesion_mask[y1:y2, x1:x2]
    overlay = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    red = np.zeros((crop.size[1], crop.size[0], 4), dtype=np.uint8)
    red[:, :, 0] = 255
    red[:, :, 3] = (local_mask > 0).astype(np.uint8) * 120
    overlay = Image.fromarray(red, mode="RGBA")
    return Image.alpha_composite(crop, overlay).convert("RGB")


def _normalize_stage(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"未发现异常", "normal", "正常"}:
        return "normal"
    if text in {"2期", "II", "II期", "2"}:
        return "II"
    if text in {"3期", "III", "III期", "3"}:
        return "III"
    return text


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_task_readme(path: Path, experiment: str, count: int) -> None:
    path.write_text(
        f"""# Blind Xray Staging Task

You will receive {count} anonymized hip Xray ROI images.

For each image, classify the visible femoral-head region into exactly one of:

- normal: no obvious Xray finding of femoral head necrosis
- II: Xray findings compatible with ARCO II, without collapse
- III: Xray findings compatible with ARCO III, such as subchondral fracture/crescent sign/collapse
- uncertain: image quality or visible evidence is insufficient

Return one JSON object per case with:

```json
{{"case_id": "case_0001", "prediction": "normal|II|III|uncertain", "confidence": 0.0, "reason": "..."}}
```

Do not use file names or external metadata for diagnosis. The images are intentionally anonymized.

Experiment: {experiment}
""",
        encoding="utf-8",
    )


def _write_root_readme(
    path: Path,
    experiment: str,
    count: int,
    warnings: list[dict[str, Any]],
) -> None:
    path.write_text(
        f"""# Codex Blind Direct Xray Staging

Experiment: `{experiment}`

Cases: {count}

Directory layout:

- `public/`: safe to expose to Codex. Contains only anonymous images and task text.
- `private/`: not exposed to Codex during prediction. Contains GT labels, original paths, and crop metadata for scoring.

Blindness guard:

- public image names are `case_XXXX.png`
- public CSV contains only case ids and relative image file names
- GT labels, patient names, sides, original paths, and task/job identifiers are private

ROI side rule in private metadata:

- patient right maps to image left
- patient left maps to image right
- if only one femoral-head component exists, the only component is used

Selection warnings: {len(warnings)}
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
