from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from llm.connectivity import DEFAULT_EXTERNAL_SCRIPT, ApiConnectivityChecker
from llm.model_client import ApiRouteLog, OpenAICompatibleModelClient


def run_smoke_check(
    route_log_path: Path | str = "docs/API_ROUTE_LOG.md",
    external_script_path: Path | str = DEFAULT_EXTERNAL_SCRIPT,
    real: bool = False,
) -> str:
    route_log = ApiRouteLog.from_file(route_log_path)
    checker = ApiConnectivityChecker(
        route_log=route_log,
        external_script_path=external_script_path,
    )
    inspection = checker.inspect()
    if not real:
        return json.dumps(inspection, ensure_ascii=False, indent=2)

    if not inspection["api_key_present"]:
        inspection["error"] = f"Missing {inspection['api_key_env']}"
        inspection["real_call_attempted"] = False
        return json.dumps(inspection, ensure_ascii=False, indent=2)

    smoke_result = checker.run_model_smoke(
        OpenAICompatibleModelClient(route_log=route_log)
    )
    inspection.update(smoke_result)
    return json.dumps(inspection, ensure_ascii=False, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect or smoke-test MedScope API routing.")
    parser.add_argument("--route-log", default="docs/API_ROUTE_LOG.md")
    parser.add_argument("--external-script", default=str(DEFAULT_EXTERNAL_SCRIPT))
    parser.add_argument(
        "--real",
        action="store_true",
        help="Actually call the active model route. Requires the route API key env var.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = run_smoke_check(
        route_log_path=args.route_log,
        external_script_path=args.external_script,
        real=args.real,
    )
    print(output)
    payload = json.loads(output)
    if args.real and "error" in payload:
        sys.exit(1)


if __name__ == "__main__":
    main()
