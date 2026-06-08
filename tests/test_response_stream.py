import io
import json
import unittest

from llm.response_stream import parse_openai_compatible_sse_response


class ResponseStreamTest(unittest.TestCase):
    def test_parses_responses_output_text_delta_events(self):
        payload = "\n".join(
            [
                "event: response.output_text.delta",
                f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': 'hello '})}",
                "",
                "event: response.output_text.delta",
                f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': 'world'})}",
                "",
                "data: [DONE]",
                "",
            ]
        ).encode("utf-8")

        content, raw = parse_openai_compatible_sse_response(io.BytesIO(payload))

        self.assertEqual(content, "hello world")
        self.assertTrue(raw["stream"])
        self.assertGreaterEqual(raw["event_count"], 3)

    def test_falls_back_to_final_response_output_text(self):
        payload = (
            "data: "
            + json.dumps(
                {
                    "type": "response.completed",
                    "response": {
                        "output": [
                            {
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "final text",
                                    }
                                ]
                            }
                        ]
                    },
                }
            )
            + "\n\n"
        ).encode("utf-8")

        content, raw = parse_openai_compatible_sse_response(io.BytesIO(payload))

        self.assertEqual(content, "final text")
        self.assertEqual(raw["event_count"], 1)


if __name__ == "__main__":
    unittest.main()
