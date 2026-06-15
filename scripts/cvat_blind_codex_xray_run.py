from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


DEFAULT_EXPERIMENT_DIR = Path("output/fake/codex_blind_xray_direct_stage_20260613/roi_crop")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex direct blind Xray staging on anonymous cases.")
    parser.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--skip-case-id", action="append", default=[])
    parser.add_argument("--model", default="", help="Optional codex --model value.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--jobs", type=int, default=1, help="Number of concurrent codex exec calls.")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--record-codex-events",
        action="store_true",
        help="Pass codex exec --json and save stdout/stderr event logs per case.",
    )
    parser.add_argument(
        "--isolated-public-copy",
        action="store_true",
        help="Run each case from a temporary directory containing only public files for that case.",
    )
    parser.add_argument(
        "--isolation-root",
        type=Path,
        default=Path("/tmp/cvat_blind_codex_xray_isolated"),
        help="Root for --isolated-public-copy temporary case directories.",
    )
    parser.add_argument(
        "--keep-isolated-workdir",
        action="store_true",
        help="Keep per-case isolated public directories for audit instead of deleting them.",
    )
    parser.add_argument(
        "--codex-sandbox",
        choices=["read-only", "workspace-write", "danger-full-access"],
        default="",
        help="Optional codex exec --sandbox value. Prefer read-only for blind evals.",
    )
    parser.add_argument(
        "--dangerous",
        action="store_true",
        help="Pass --dangerously-bypass-approvals-and-sandbox to codex exec.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    public_dir = args.experiment_dir / "public"
    output_dir = args.experiment_dir / "codex_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_csv(public_dir / "cases.csv")
    if args.case_id:
        keep = set(args.case_id)
        rows = [row for row in rows if row["case_id"] in keep]
    if args.skip_case_id:
        skip = set(args.skip_case_id)
        rows = [row for row in rows if row["case_id"] not in skip]
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise RuntimeError("No cases selected")

    prompt_template = _prompt_template(args.experiment_dir.name)
    indexed_rows = list(enumerate(rows, start=1))
    run_rows: list[dict[str, Any]] = []
    if args.jobs <= 1:
        for index, row in indexed_rows:
            result = _run_one(index, len(rows), row, args, public_dir, output_dir, prompt_template)
            run_rows.append(result)
    else:
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = [
                executor.submit(
                    _run_one,
                    index,
                    len(rows),
                    row,
                    args,
                    public_dir,
                    output_dir,
                    prompt_template,
                )
                for index, row in indexed_rows
            ]
            for future in as_completed(futures):
                run_rows.append(future.result())
    _write_csv(output_dir / "run_index.csv", run_rows)
    print(f"Wrote outputs to {output_dir}", flush=True)


def _run_one(
    index: int,
    total: int,
    row: dict[str, str],
    args: argparse.Namespace,
    public_dir: Path,
    output_dir: Path,
    prompt_template: str,
) -> dict[str, Any]:
    case_id = row["case_id"]
    run_public_dir = public_dir.resolve()
    cleanup_dir: Path | None = None
    if args.isolated_public_copy:
        run_public_dir = _prepare_isolated_public_dir(args, public_dir, row)
        cleanup_dir = None if args.keep_isolated_workdir else run_public_dir
    image_path = (run_public_dir / row["image_file"]).resolve()
    out_json = (output_dir / f"{case_id}.json").resolve()
    out_txt = (output_dir / f"{case_id}.txt").resolve()
    event_dir = (output_dir / "codex_event_logs").resolve()
    stdout_log = event_dir / (
        f"{case_id}.stdout.jsonl" if args.record_codex_events else f"{case_id}.stdout.log"
    )
    stderr_log = event_dir / f"{case_id}.stderr.log"
    if out_txt.exists() and not args.force:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        skipped_row = {
            "case_id": case_id,
            "image_file": row["image_file"],
            "status": "skipped_existing",
            "output_text": str(out_txt),
            "output_json": str(out_json),
        }
        print(f"[{index}/{total}] {case_id}: skipped_existing", flush=True)
        return skipped_row

    prompt = prompt_template.replace("__CASE_ID__", case_id)
    cmd = ["codex", "exec", "--skip-git-repo-check"]
    if args.record_codex_events:
        cmd.append("--json")
    if args.dangerous:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    if args.codex_sandbox:
        cmd.extend(["--sandbox", args.codex_sandbox])
    if args.model:
        cmd.extend(["--model", args.model])
    cmd.extend(["--image", str(image_path), "--output-last-message", str(out_txt), prompt])
    started = time.time()
    status = "ok"
    returncode = 0
    stdout = ""
    stderr = ""
    try:
        result = subprocess.run(
            cmd,
            cwd=run_public_dir,
            text=True,
            capture_output=True,
            timeout=args.timeout,
            env=os.environ.copy(),
        )
        returncode = result.returncode
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        if result.returncode != 0:
            status = "failed"
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        returncode = -1
        stdout = _timeout_stream_to_text(exc.stdout)
        stderr = _timeout_stream_to_text(exc.stderr) or str(exc)
    finally:
        event_dir.mkdir(parents=True, exist_ok=True)
        stdout_log.write_text(stdout, encoding="utf-8", errors="replace")
        stderr_log.write_text(stderr, encoding="utf-8", errors="replace")
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
    raw_text = out_txt.read_text(encoding="utf-8", errors="replace") if out_txt.exists() else ""
    parsed = _parse_prediction(raw_text)
    out_json.write_text(
        json.dumps(
            {
                "case_id": case_id,
                "image_file": row["image_file"],
                "status": status,
                "returncode": returncode,
                "duration_sec": round(time.time() - started, 3),
                "prediction": parsed,
                "raw_text": raw_text,
                "stdout_log": str(stdout_log),
                "stderr_log": str(stderr_log),
                "isolated_public_dir": str(run_public_dir) if args.isolated_public_copy else "",
                "isolated_public_dir_kept": bool(args.isolated_public_copy and args.keep_isolated_workdir),
                "stderr_tail": stderr[-4000:],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    result_row = {
        "case_id": case_id,
        "image_file": row["image_file"],
        "status": status,
        "returncode": returncode,
        "duration_sec": round(time.time() - started, 3),
        "prediction": parsed.get("prediction", ""),
        "confidence": parsed.get("confidence", ""),
        "output_text": str(out_txt),
        "output_json": str(out_json),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
        "isolated_public_dir": str(run_public_dir) if args.isolated_public_copy else "",
    }
    print(f"[{index}/{total}] {case_id}: {status} {parsed.get('prediction', '')}", flush=True)
    return result_row


def _prepare_isolated_public_dir(
    args: argparse.Namespace,
    public_dir: Path,
    row: dict[str, str],
) -> Path:
    case_id = row["case_id"]
    case_dir = (args.isolation_root / args.experiment_dir.name / case_id).resolve()
    shutil.rmtree(case_dir, ignore_errors=True)
    (case_dir / "images").mkdir(parents=True, exist_ok=True)
    shutil.copy2(public_dir / row["image_file"], case_dir / row["image_file"])
    task_md = public_dir / "TASK.md"
    if task_md.exists():
        shutil.copy2(task_md, case_dir / "TASK.md")
    _write_csv(case_dir / "cases.csv", [row])
    return case_dir


def _timeout_stream_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _prompt_template(experiment_name: str) -> str:
    if experiment_name == "gt_mask":
        input_description = (
            "附带图片是匿名医生病灶 mask 的单侧 ROI 裁剪图：白色区域表示医生标出的 Xray "
            "坏死相关征象区域，黑色表示未标注区域。"
        )
    elif experiment_name == "roi_plus_gt_mask":
        input_description = (
            "附带图片是匿名髋关节 Xray 单侧 ROI 裁剪图，红色半透明区域表示医生标出的 Xray "
            "坏死相关征象区域。"
        )
    else:
        input_description = "附带图片是匿名髋关节 Xray 单侧 ROI 裁剪图。"
    return f"""你是一名医学影像判读助手。请只根据{input_description}判断股骨头坏死 Xray 三分类分期。

分类只能是：
- normal：Xray 未见明确股骨头坏死相关异常。
- II：可见硬化、囊变、混杂密度等坏死相关 Xray 征象，但没有明确塌陷/新月征/软骨下骨折。
- III：可见软骨下骨折、新月征、股骨头轮廓塌陷或变扁等结构性改变。
- uncertain：图像质量或可见范围不足，无法判断。

请输出严格 JSON，不要输出 Markdown，不要添加额外文字：
{{"case_id":"__CASE_ID__","prediction":"normal|II|III|uncertain","confidence":0.0,"reason":"一句话说明依据"}}"""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _parse_prediction(text: str) -> dict[str, Any]:
    stripped = text.strip()
    candidates = [stripped]
    if "```" in stripped:
        for part in stripped.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{") and part.endswith("}"):
                candidates.append(part)
    first = stripped.find("{")
    last = stripped.rfind("}")
    if 0 <= first < last:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                data["prediction"] = _normalize_prediction(data.get("prediction"))
                return data
        except json.JSONDecodeError:
            pass
    return {"prediction": _normalize_prediction(stripped), "confidence": None, "reason": stripped[:500]}


def _normalize_prediction(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"normal", "正常", "未发现异常", "无明显异常", "无异常"}:
        return "normal"
    if text in {"ii", "ii期", "2", "2期", "二期", "arco ii", "arco ii期"}:
        return "II"
    if text in {"iii", "iii期", "3", "3期", "三期", "arco iii", "arco iii期"}:
        return "III"
    if "iii" in text or "3期" in text or "三期" in text:
        return "III"
    if "ii" in text or "2期" in text or "二期" in text:
        return "II"
    if "正常" in text or "未见" in text or "无明显" in text:
        return "normal"
    return "uncertain"


if __name__ == "__main__":
    main()
