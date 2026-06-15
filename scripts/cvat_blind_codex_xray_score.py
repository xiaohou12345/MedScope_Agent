from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_EXPERIMENT_DIR = Path("output/fake/codex_blind_xray_direct_stage_20260613/roi_crop")
LABELS = ["normal", "II", "III", "uncertain"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score blind Codex Xray staging outputs.")
    parser.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    private_rows = _read_csv(args.experiment_dir / "private" / "private_index.csv")
    output_dir = args.experiment_dir / "codex_outputs"
    scored_rows: list[dict[str, Any]] = []
    for row in private_rows:
        case_id = row["case_id"]
        output_json = output_dir / f"{case_id}.json"
        pred = "missing"
        confidence = ""
        reason = ""
        status = "missing"
        if output_json.exists():
            data = json.loads(output_json.read_text(encoding="utf-8"))
            status = str(data.get("status") or "")
            prediction = data.get("prediction") or {}
            pred = _normalize(prediction.get("prediction"))
            confidence = prediction.get("confidence", "")
            reason = prediction.get("reason", "")
        gt = _normalize(row["gt_xray_stage"])
        abstain_as_normal = "normal" if pred in {"uncertain", "missing"} else pred
        scored_rows.append(
            {
                "case_id": case_id,
                "gt_xray_stage": gt,
                "prediction": pred,
                "prediction_abstain_as_normal": abstain_as_normal,
                "correct": pred == gt,
                "correct_abstain_as_normal": abstain_as_normal == gt,
                "abstained": pred in {"uncertain", "missing"},
                "confidence": confidence,
                "status": status,
                "reason": reason,
            }
        )
    summary = _summary(scored_rows)
    _write_csv(output_dir / "scored_cases.csv", scored_rows)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "confusion_matrix.csv").write_text(
        _matrix_csv(summary["confusion_matrix"]),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    correct = sum(bool(row["correct"]) for row in rows)
    correct_abstain_as_normal = sum(bool(row["correct_abstain_as_normal"]) for row in rows)
    abstained = sum(bool(row["abstained"]) for row in rows)
    non_abstain_rows = [row for row in rows if not row["abstained"]]
    non_abstain_correct = sum(bool(row["correct"]) for row in non_abstain_rows)
    matrix: dict[str, dict[str, int]] = {
        gt: {pred: 0 for pred in LABELS + ["missing"]} for gt in LABELS[:3]
    }
    for row in rows:
        gt = _normalize(row["gt_xray_stage"])
        pred = _normalize(row["prediction"])
        if pred not in LABELS:
            pred = "missing"
        matrix.setdefault(gt, {label: 0 for label in LABELS + ["missing"]})
        matrix[gt][pred] = matrix[gt].get(pred, 0) + 1
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else None,
        "abstained": abstained,
        "coverage": (total - abstained) / total if total else None,
        "non_abstain_accuracy": non_abstain_correct / len(non_abstain_rows)
        if non_abstain_rows
        else None,
        "correct_abstain_as_normal": correct_abstain_as_normal,
        "accuracy_abstain_as_normal": correct_abstain_as_normal / total if total else None,
        "gt_counts": dict(Counter(row["gt_xray_stage"] for row in rows)),
        "prediction_counts": dict(Counter(row["prediction"] for row in rows)),
        "confusion_matrix": matrix,
    }


def _matrix_csv(matrix: dict[str, dict[str, int]]) -> str:
    cols = LABELS + ["missing"]
    lines = [",".join(["gt"] + cols)]
    for gt in ["normal", "II", "III"]:
        row = matrix.get(gt, {})
        lines.append(",".join([gt] + [str(row.get(col, 0)) for col in cols]))
    return "\n".join(lines) + "\n"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _normalize(value: Any) -> str:
    text = str(value or "").strip()
    low = text.lower()
    if low in {"normal", "正常", "未发现异常", "无明显异常", "无异常"}:
        return "normal"
    if low in {"ii", "ii期", "2", "2期", "二期", "arco ii", "arco ii期"}:
        return "II"
    if low in {"iii", "iii期", "3", "3期", "三期", "arco iii", "arco iii期"}:
        return "III"
    if low in {"uncertain", "abstain", "无法判断", "不确定"}:
        return "uncertain"
    if low == "missing":
        return "missing"
    return text or "missing"


if __name__ == "__main__":
    main()
