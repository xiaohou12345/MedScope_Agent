import json
import unittest
from contextlib import redirect_stdout
from io import StringIO

from scripts.check_runtime_environment import inspect_runtime_environment, main


class RuntimeEnvironmentTest(unittest.TestCase):
    def test_inspection_accepts_python_310_or_newer(self):
        report = inspect_runtime_environment(python_version=(3, 10, 0))

        self.assertEqual(report["python"]["status"], "ready")
        self.assertTrue(report["ready"])
        self.assertEqual(report["python"]["required"], ">=3.10")

    def test_inspection_rejects_python_38_with_actionable_message(self):
        report = inspect_runtime_environment(python_version=(3, 8, 18))

        self.assertEqual(report["python"]["status"], "not_ready")
        self.assertFalse(report["ready"])
        self.assertIn("Python 3.10+", report["action_items"][0])
        self.assertIn("3.8.18", report["python"]["current"])

    def test_cli_prints_json_readiness_report(self):
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = main([])

        payload = json.loads(stdout.getvalue())
        self.assertIn(exit_code, {0, 1})
        self.assertIn("ready", payload)
        self.assertIn("python", payload)
        self.assertEqual(payload["schema_version"], "runtime_environment_readiness.v1")


if __name__ == "__main__":
    unittest.main()
