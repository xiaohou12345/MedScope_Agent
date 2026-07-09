from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.binary_mask_component_tool import BinaryMaskComponent, BinaryMaskComponentTool  # noqa: E402
from tools.onfh_collapse_measurement_tool import ONFHCollapseMeasurementTool  # noqa: E402


DEFAULT_DATASET_DIR = Path(
    "/Users/houshaohua/Desktop/code/aidoctor/20260708_new_sam3_valid_viz_gtfix"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare GT and predicted femoral-head masks for ONFH collapse-depth measurement.",
    )
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--min-area-px", type=int, default=2500)
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir)
    output_dir = Path(args.output_dir) if args.output_dir else dataset_dir / "collapse_roi_compare"
    output_dir.mkdir(parents=True, exist_ok=True)
    component_dir = output_dir / "component_masks"
    overlay_dir = output_dir / "overlays"
    component_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)

    image_paths = sorted((dataset_dir / "original_images").glob("*"))
    image_paths = [path for path in image_paths if path.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    all_measurements: list[dict[str, Any]] = []
    all_comparisons: list[dict[str, Any]] = []

    for image_path in image_paths:
        gt_mask_path = dataset_dir / "gt_masks" / f"{image_path.stem}__gt_mask.png"
        pred_mask_path = dataset_dir / "pred_masks" / f"{image_path.stem}__pred_mask.png"
        if not gt_mask_path.exists() or not pred_mask_path.exists():
            continue

        with Image.open(image_path) as raw_image:
            image_size = raw_image.size

        gt_items = measure_mask_components(
            image_path=image_path,
            mask_path=gt_mask_path,
            mask_type="gt",
            image_size=image_size,
            output_dir=component_dir,
            min_area_px=args.min_area_px,
        )
        pred_items = measure_mask_components(
            image_path=image_path,
            mask_path=pred_mask_path,
            mask_type="pred",
            image_size=image_size,
            output_dir=component_dir,
            min_area_px=args.min_area_px,
        )
        overlay_path = overlay_dir / f"{image_path.stem}_gt_pred_collapse_compare.jpg"
        draw_compare_overlay(
            image_path=image_path,
            gt_items=gt_items,
            pred_items=pred_items,
            output_path=overlay_path,
        )
        for item in gt_items + pred_items:
            item["compare_overlay_path"] = str(overlay_path)
        all_measurements.extend(gt_items + pred_items)
        all_comparisons.extend(compare_gt_pred(gt_items=gt_items, pred_items=pred_items))

    write_csv(output_dir / "collapse_roi_measurements.csv", all_measurements)
    write_csv(output_dir / "collapse_roi_gt_pred_comparison.csv", all_comparisons)
    write_json(output_dir / "collapse_roi_measurements.json", all_measurements)
    write_json(output_dir / "collapse_roi_gt_pred_comparison.json", all_comparisons)
    write_summary(output_dir / "summary.json", all_measurements, all_comparisons)
    write_contact_sheet(overlay_dir=overlay_dir, output_path=output_dir / "collapse_roi_compare_contact_sheet.jpg")
    print(output_dir)
    print(f"measurements={len(all_measurements)} comparisons={len(all_comparisons)}")


def measure_mask_components(
    *,
    image_path: Path,
    mask_path: Path,
    mask_type: str,
    image_size: tuple[int, int],
    output_dir: Path,
    min_area_px: int,
) -> list[dict[str, Any]]:
    components = BinaryMaskComponentTool().components(
        mask_path=mask_path,
        min_area_px=min_area_px,
    )
    side_labels = side_labels_for_components(components, image_size=image_size)
    items: list[dict[str, Any]] = []
    for component in components:
        image_side = side_labels.get(component.component_id, component.component_id)
        component_mask_path = output_dir / mask_type / f"{image_path.stem}_{component.component_id}.png"
        BinaryMaskComponentTool().write_component_mask(
            component=component,
            size=image_size,
            output_path=component_mask_path,
        )
        measurement = ONFHCollapseMeasurementTool().measure(
            image_path=image_path,
            femoral_head_mask_path=component_mask_path,
            calibration=None,
            image_side=image_side,
        )
        item = {
            "image": image_path.name,
            "image_stem": image_path.stem,
            "mask_type": mask_type,
            "component_id": component.component_id,
            "image_side": image_side,
            "component_mask_path": str(component_mask_path),
            "component_area_px": component.area_px,
            "component_bbox": component.bbox,
            "component_centroid": component.centroid,
            "measurement_usable": measurement.get("measurement_usable"),
            "maximum_depression_px": measurement.get("maximum_depression_px"),
            "maximum_depression_mm": measurement.get("maximum_depression_mm"),
            "reference_diameter_px": measurement.get("reference_diameter_px"),
            "femoral_head_deficiency_pW_percent": measurement.get("femoral_head_deficiency_pW_percent"),
            "normalized_depression": measurement.get("normalized_depression"),
            "depression_point": measurement.get("depression_point"),
            "reference_point": measurement.get("reference_point"),
            "reference_fit": measurement.get("reference_fit"),
            "actual_mask_contour": measurement.get("actual_mask_contour"),
            "observed_contour": measurement.get("observed_contour"),
            "reconstructed_complete_contour": measurement.get("reconstructed_complete_contour"),
            "stage_implication": measurement.get("stage_implication"),
            "diagnosis_usable_level": measurement.get("diagnosis_usable_level"),
            "quality": measurement.get("quality"),
        }
        items.append(item)
    return items


def side_labels_for_components(
    components: list[BinaryMaskComponent],
    *,
    image_size: tuple[int, int],
) -> dict[str, str]:
    if len(components) == 1:
        return {components[0].component_id: "single_femoral_head"}
    ordered = sorted(components, key=lambda component: component.centroid[0])
    labels: dict[str, str] = {}
    width = image_size[0]
    for index, component in enumerate(ordered):
        if index == 0:
            label = "image_left_femoral_head"
        elif index == len(ordered) - 1:
            label = "image_right_femoral_head"
        elif component.centroid[0] < width / 2:
            label = f"extra_left_component_{index + 1}"
        else:
            label = f"extra_right_component_{index + 1}"
        labels[component.component_id] = label
    return labels


def compare_gt_pred(
    *,
    gt_items: list[dict[str, Any]],
    pred_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    remaining_pred = pred_items[:]
    rows: list[dict[str, Any]] = []
    for gt in gt_items:
        if not remaining_pred:
            rows.append(comparison_row(gt, None))
            continue
        pred = min(
            remaining_pred,
            key=lambda item: centroid_distance(gt["component_centroid"], item["component_centroid"]),
        )
        remaining_pred.remove(pred)
        rows.append(comparison_row(gt, pred))
    for pred in remaining_pred:
        rows.append(comparison_row(None, pred))
    return rows


def comparison_row(gt: dict[str, Any] | None, pred: dict[str, Any] | None) -> dict[str, Any]:
    image = gt["image"] if gt else pred["image"]
    gt_px = value_or_none(gt, "maximum_depression_px")
    pred_px = value_or_none(pred, "maximum_depression_px")
    gt_pw = value_or_none(gt, "femoral_head_deficiency_pW_percent")
    pred_pw = value_or_none(pred, "femoral_head_deficiency_pW_percent")
    gt_norm = value_or_none(gt, "normalized_depression")
    pred_norm = value_or_none(pred, "normalized_depression")
    iou = component_iou(gt, pred) if gt and pred else None
    return {
        "image": image,
        "gt_component_id": gt.get("component_id") if gt else None,
        "pred_component_id": pred.get("component_id") if pred else None,
        "gt_image_side": gt.get("image_side") if gt else None,
        "pred_image_side": pred.get("image_side") if pred else None,
        "gt_area_px": gt.get("component_area_px") if gt else None,
        "pred_area_px": pred.get("component_area_px") if pred else None,
        "component_iou": round(iou, 6) if iou is not None else None,
        "centroid_distance_px": (
            round(centroid_distance(gt["component_centroid"], pred["component_centroid"]), 3)
            if gt and pred
            else None
        ),
        "gt_maximum_depression_px": gt_px,
        "pred_maximum_depression_px": pred_px,
        "abs_depression_error_px": round(abs(pred_px - gt_px), 3) if gt_px is not None and pred_px is not None else None,
        "gt_reference_diameter_px": value_or_none(gt, "reference_diameter_px"),
        "pred_reference_diameter_px": value_or_none(pred, "reference_diameter_px"),
        "gt_femoral_head_deficiency_pW_percent": gt_pw,
        "pred_femoral_head_deficiency_pW_percent": pred_pw,
        "abs_pW_error_percent": round(abs(pred_pw - gt_pw), 6) if gt_pw is not None and pred_pw is not None else None,
        "gt_normalized_depression": gt_norm,
        "pred_normalized_depression": pred_norm,
        "abs_normalized_error": round(abs(pred_norm - gt_norm), 6) if gt_norm is not None and pred_norm is not None else None,
        "gt_stage_implication": gt.get("stage_implication") if gt else None,
        "pred_stage_implication": pred.get("stage_implication") if pred else None,
        "compare_overlay_path": (gt or pred).get("compare_overlay_path"),
    }


def value_or_none(item: dict[str, Any] | None, key: str) -> float | None:
    if not item:
        return None
    value = item.get(key)
    return float(value) if value is not None else None


def component_iou(gt: dict[str, Any], pred: dict[str, Any]) -> float:
    gt_mask = Image.open(gt["component_mask_path"]).convert("L")
    pred_mask = Image.open(pred["component_mask_path"]).convert("L")
    gt_data = gt_mask.getdata()
    pred_data = pred_mask.getdata()
    intersection = 0
    union = 0
    for gt_value, pred_value in zip(gt_data, pred_data):
        gt_fg = gt_value != 0
        pred_fg = pred_value != 0
        if gt_fg and pred_fg:
            intersection += 1
        if gt_fg or pred_fg:
            union += 1
    return intersection / max(union, 1)


def centroid_distance(a: list[float], b: list[float]) -> float:
    return ((float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2) ** 0.5


def draw_compare_overlay(
    *,
    image_path: Path,
    gt_items: list[dict[str, Any]],
    pred_items: list[dict[str, Any]],
    output_path: Path,
) -> None:
    image = Image.open(image_path).convert("RGB")
    gt_panel = draw_panel(image=image, items=gt_items, title="GT mask -> closed fitted complete contour")
    pred_panel = draw_panel(image=image, items=pred_items, title="Pred mask -> closed fitted complete contour")
    width = gt_panel.width + pred_panel.width
    height = max(gt_panel.height, pred_panel.height)
    canvas = Image.new("RGB", (width, height), "white")
    canvas.paste(gt_panel, (0, 0))
    canvas.paste(pred_panel, (gt_panel.width, 0))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=92)


def draw_panel(*, image: Image.Image, items: list[dict[str, Any]], title: str) -> Image.Image:
    max_width = 820
    scale = min(max_width / image.width, 1.0)
    panel = image.resize((int(image.width * scale), int(image.height * scale)))
    overlay = Image.new("RGBA", panel.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    colors = [(255, 190, 0, 230), (0, 210, 255, 230), (255, 70, 180, 230), (80, 255, 120, 230)]
    for index, item in enumerate(items):
        color = colors[index % len(colors)]
        mask = Image.open(item["component_mask_path"]).convert("L")
        if scale != 1.0:
            mask = mask.resize(panel.size)
        draw_mask_points(draw=draw, mask=mask, color=(color[0], color[1], color[2], 55))
        draw_measurement(draw=draw, item=item, color=color, scale=scale)
    output = Image.alpha_composite(panel.convert("RGBA"), overlay).convert("RGB")
    title_bar = Image.new("RGB", (output.width, output.height + 64), "white")
    title_bar.paste(output, (0, 64))
    title_draw = ImageDraw.Draw(title_bar)
    title_draw.text((16, 14), title, fill=(20, 30, 40))
    return title_bar


def draw_mask_points(*, draw: ImageDraw.ImageDraw, mask: Image.Image, color: tuple[int, int, int, int]) -> None:
    pixels = mask.load()
    width, height = mask.size
    step = max(1, int(max(width, height) / 600))
    for y in range(0, height, step):
        for x in range(0, width, step):
            if pixels[x, y] != 0:
                draw.point((x, y), fill=color)


def draw_measurement(
    *,
    draw: ImageDraw.ImageDraw,
    item: dict[str, Any],
    color: tuple[int, int, int, int],
    scale: float,
) -> None:
    draw_sampled_polyline(
        draw=draw,
        points=(item.get("actual_mask_contour") or {}).get("sampled_points") or [],
        scale=scale,
        fill=(40, 255, 80, 245),
        width=max(2, int(3 * scale)),
    )
    draw_sampled_polyline(
        draw=draw,
        points=(item.get("reconstructed_complete_contour") or {}).get("sampled_points") or [],
        scale=scale,
        fill=(255, 255, 255, 245),
        width=max(2, int(4 * scale)),
    )
    depression_point = item.get("depression_point")
    reference_point = item.get("reference_point")
    if depression_point and reference_point:
        line = tuple(value * scale for value in (reference_point[0], reference_point[1], depression_point[0], depression_point[1]))
        draw.line(line, fill=(255, 40, 40, 255), width=max(2, int(5 * scale)))
        for point in (reference_point, depression_point):
            x = point[0] * scale
            y = point[1] * scale
            r = max(3, int(7 * scale))
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 40, 40, 255))
    bbox = item.get("component_bbox") or [10, 10, 10, 10]
    label = f"{item.get('image_side')} | {item.get('maximum_depression_px')} px | norm {item.get('normalized_depression')}"
    draw.text((bbox[0] * scale, max(0, bbox[1] * scale - 18)), label, fill=color)


def draw_sampled_polyline(
    *,
    draw: ImageDraw.ImageDraw,
    points: list[list[float]],
    scale: float,
    fill: tuple[int, int, int, int],
    width: int,
) -> None:
    if len(points) < 2:
        return
    scaled = [(point[0] * scale, point[1] * scale) for point in points]
    draw.line(scaled, fill=fill, width=width)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: simplify_value(row.get(key)) for key in fields})


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_summary(path: Path, measurements: list[dict[str, Any]], comparisons: list[dict[str, Any]]) -> None:
    paired = [row for row in comparisons if row.get("abs_depression_error_px") is not None]
    paired_pw = [row for row in comparisons if row.get("abs_pW_error_percent") is not None]
    summary = {
        "image_count": len({row["image"] for row in measurements}),
        "measurement_count": len(measurements),
        "comparison_count": len(comparisons),
        "paired_comparison_count": len(paired),
        "mean_abs_depression_error_px": round(mean([row["abs_depression_error_px"] for row in paired]), 3) if paired else None,
        "mean_abs_normalized_error": round(mean([row["abs_normalized_error"] for row in paired]), 6) if paired else None,
        "mean_abs_pW_error_percent": round(mean([row["abs_pW_error_percent"] for row in paired_pw]), 6) if paired_pw else None,
        "mean_component_iou": round(mean([row["component_iou"] for row in paired if row.get("component_iou") is not None]), 6) if paired else None,
        "note": "Distances are pixel/normalized values only. No DICOM PixelSpacing was available in this validation package.",
    }
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_contact_sheet(*, overlay_dir: Path, output_path: Path) -> None:
    overlays = sorted(overlay_dir.glob("*_gt_pred_collapse_compare.jpg"))
    if not overlays:
        return
    thumbs: list[Image.Image] = []
    for path in overlays:
        image = Image.open(path).convert("RGB")
        image.thumbnail((720, 420))
        canvas = Image.new("RGB", (760, 470), "white")
        canvas.paste(image, ((760 - image.width) // 2, 8))
        ImageDraw.Draw(canvas).text((12, 440), path.name, fill="black")
        thumbs.append(canvas)
    cols = 2
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 760, rows * 470), (238, 242, 246))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % cols) * 760, (index // cols) * 470))
    sheet.save(output_path, quality=92)


def simplify_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


if __name__ == "__main__":
    main()
