from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PIPELINE_STEPS = {
    "real-vlm-agent": {
        "script": "scripts/xray_roi_agent_eval.py",
        "description": "Agent route whose finding list comes from real VLM ROI observations.",
    },
    "mock-agent": {
        "script": "scripts/xray_mask_agent_eval.py",
        "description": "Agent route whose finding list comes from doctor-reviewed mock mask evidence.",
    },
    "real-vlm-mock-agent": {
        "script": "scripts/xray_roi_mask_agent_eval.py",
        "description": "Agent route whose finding list combines real VLM observations and mock mask evidence.",
    },
}

DEFAULT_ALL_STEPS = [
    "real-vlm-agent",
    "mock-agent",
    "real-vlm-mock-agent",
]


def main() -> None:
    args, passthrough = parse_args()
    if args.command == "list":
        print_steps()
        return
    if args.command == "run":
        run_steps([args.step], passthrough, dry_run=args.dry_run)
        return
    if args.command == "all":
        run_steps(args.steps or DEFAULT_ALL_STEPS, passthrough, dry_run=args.dry_run)
        return
    raise SystemExit(f"Unknown command: {args.command}")


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description=(
            "Canonical ONFH experiment entrypoint. Legacy scripts remain available "
            "for direct debugging, but normal reproduction should start here."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List ONFH pipeline steps.")

    run_parser = subparsers.add_parser("run", help="Run one ONFH pipeline step.")
    run_parser.add_argument("step", choices=sorted(PIPELINE_STEPS))
    run_parser.add_argument("--dry-run", action="store_true")

    all_parser = subparsers.add_parser("all", help="Run the standard ONFH pipeline.")
    all_parser.add_argument(
        "--steps",
        nargs="+",
        choices=sorted(PIPELINE_STEPS),
        help="Override the default step order.",
    )
    all_parser.add_argument("--dry-run", action="store_true")

    return parser.parse_known_args()


def print_steps() -> None:
    for name, config in PIPELINE_STEPS.items():
        print(f"{name:16s} {config['script']}")
        print(f"{'':16s} {config['description']}")


def run_steps(step_names: list[str], passthrough: list[str], *, dry_run: bool) -> None:
    for step_name in step_names:
        config = PIPELINE_STEPS[step_name]
        command = [
            sys.executable,
            str(PROJECT_ROOT / config["script"]),
            *config.get("default_args", []),
            *passthrough,
        ]
        print(f"[eval_pipeline] {step_name}: {' '.join(command)}")
        if dry_run:
            continue
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)


if __name__ == "__main__":
    main()
