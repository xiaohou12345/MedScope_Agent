from __future__ import annotations

import argparse
import json
import platform
import sys
from typing import Any


MIN_PYTHON = (3, 10)


def inspect_runtime_environment(python_version: tuple[int, ...] | None = None) -> dict[str, Any]:
    version = tuple(python_version or sys.version_info[:3])
    current = ".".join(str(part) for part in version[:3])
    python_ready = version >= MIN_PYTHON
    action_items = []
    if not python_ready:
        action_items.append(
            "Use Python 3.10+ before starting MedScope, for example: "
            "/usr/bin/python3.10 -m api.http_server --host 0.0.0.0 --port 8000"
        )
        action_items.append(
            "Python 3.7/3.8 may fail with misleading import or syntax errors before the API can start."
        )
    return {
        "schema_version": "runtime_environment_readiness.v1",
        "ready": python_ready,
        "python": {
            "required": ">=3.10",
            "current": current,
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "status": "ready" if python_ready else "not_ready",
        },
        "action_items": action_items,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check whether the local Python runtime can run MedScope Agent."
    )
    parser.parse_args(argv)
    report = inspect_runtime_environment()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
