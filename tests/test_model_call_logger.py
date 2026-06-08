import json
import tempfile
import unittest
from pathlib import Path

from llm.model_call_logger import log_model_call, sanitize_for_model_log


class ModelCallLoggerTest(unittest.TestCase):
    def test_sanitizes_secrets_and_data_urls(self):
        sanitized = sanitize_for_model_log(
            {
                "api_key": "secret",
                "Authorization": "Bearer secret",
                "image_url": "data:image/png;base64,aGVsbG8=",
            }
        )

        self.assertEqual(sanitized["api_key"], "***REDACTED***")
        self.assertEqual(sanitized["Authorization"], "***REDACTED***")
        self.assertEqual(sanitized["image_url"]["type"], "data_url_omitted")
        self.assertEqual(sanitized["image_url"]["byte_length"], 5)

    def test_writes_jsonl_and_task_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            record = log_model_call(
                {
                    "call_id": "call 1",
                    "task": "vision/test",
                    "request": {"api_key": "secret"},
                    "response": {"content": "ok"},
                },
                log_dir=output_dir,
            )

            jsonl_path = output_dir / "model_calls.jsonl"
            self.assertTrue(jsonl_path.exists())
            rows = [
                json.loads(line)
                for line in jsonl_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["request"]["api_key"], "***REDACTED***")
            self.assertEqual(rows[0]["schema_version"], "model_call_log.v1")
            self.assertTrue((output_dir / "vision_test_call_1.json").exists())
            self.assertEqual(record["request"]["api_key"], "***REDACTED***")


if __name__ == "__main__":
    unittest.main()
