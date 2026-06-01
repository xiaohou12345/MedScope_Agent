import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from llm.connectivity import ApiConnectivityChecker
from llm.model_client import ApiRouteLog, ChatResponse, RecordingModelClient
from scripts.api_smoke_test import run_smoke_check


class ApiConnectivityTest(unittest.TestCase):
    def test_inspection_reports_missing_default_external_script(self):
        checker = ApiConnectivityChecker(
            route_log=ApiRouteLog(active_route="dmx"),
            external_script_path=Path("/tmp/medscope_missing_cloudgpt_client_example.py"),
        )

        result = checker.inspect()

        self.assertEqual(result["active_route"], "dmx")
        self.assertEqual(result["vision_model"], "dmx-medical-chat")
        self.assertEqual(result["api_key_env"], "DMX_API_KEY")
        self.assertFalse(result["external_script_found"])
        self.assertFalse(result["real_call_ready"])

    def test_real_call_ready_depends_on_api_key_not_external_script(self):
        old_key = os.environ.get("DMX_API_KEY")
        os.environ["DMX_API_KEY"] = "test-key"
        try:
            checker = ApiConnectivityChecker(
                route_log=ApiRouteLog(active_route="dmx"),
                external_script_path=Path("/tmp/medscope_missing_cloudgpt_client_example.py"),
            )

            result = checker.inspect()
        finally:
            if old_key is None:
                os.environ.pop("DMX_API_KEY", None)
            else:
                os.environ["DMX_API_KEY"] = old_key

        self.assertFalse(result["external_script_found"])
        self.assertTrue(result["real_call_ready"])

    def test_inspection_reports_ready_when_script_and_env_exist(self):
        with TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "cloudgpt_client_example.py"
            script_path.write_text("print('ok')\n", encoding="utf-8")
            old_key = os.environ.get("DMX_API_KEY")
            os.environ["DMX_API_KEY"] = "test-key"
            try:
                checker = ApiConnectivityChecker(
                    route_log=ApiRouteLog(active_route="dmx"),
                    external_script_path=script_path,
                )

                result = checker.inspect()
            finally:
                if old_key is None:
                    os.environ.pop("DMX_API_KEY", None)
                else:
                    os.environ["DMX_API_KEY"] = old_key

            self.assertTrue(result["api_key_present"])
            self.assertTrue(result["external_script_found"])
            self.assertTrue(result["real_call_ready"])

    def test_model_smoke_uses_model_client_without_network_in_unit_tests(self):
        checker = ApiConnectivityChecker(route_log=ApiRouteLog(active_route="ky"))
        client = RecordingModelClient(
            response=ChatResponse(content="pong", model="fake", route="test")
        )

        result = checker.run_model_smoke(client)

        self.assertEqual(result["content"], "pong")
        self.assertEqual(client.calls[0]["task"], "api_smoke_test")

    def test_smoke_script_dry_run_outputs_json_report(self):
        with TemporaryDirectory() as tmpdir:
            route_log_path = Path(tmpdir) / "API_ROUTE_LOG.md"
            route_log_path.write_text(
                "active_route: ky\nky_model: ky-self-hosted-medical\n",
                encoding="utf-8",
            )

            output = run_smoke_check(
                route_log_path=route_log_path,
                external_script_path=Path("/tmp/missing.py"),
                real=False,
            )

            payload = json.loads(output)
            self.assertEqual(payload["active_route"], "ky")
            self.assertEqual(payload["vision_model"], "ky-self-hosted-medical")
            self.assertFalse(payload["real_call_attempted"])
            self.assertFalse(payload["external_script_found"])

    def test_smoke_script_reports_separate_vision_model(self):
        with TemporaryDirectory() as tmpdir:
            route_log_path = Path(tmpdir) / "API_ROUTE_LOG.md"
            route_log_path.write_text(
                "\n".join(
                    [
                        "active_route: dmx",
                        "dmx_model: deepseek-v4-pro",
                        "dmx_vision_model: gpt-5.5",
                    ]
                ),
                encoding="utf-8",
            )

            output = run_smoke_check(
                route_log_path=route_log_path,
                external_script_path=Path("/tmp/missing.py"),
                real=False,
            )

            payload = json.loads(output)
            self.assertEqual(payload["model"], "deepseek-v4-pro")
            self.assertEqual(payload["vision_model"], "gpt-5.5")


if __name__ == "__main__":
    unittest.main()
