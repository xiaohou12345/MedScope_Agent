import unittest

from scripts.eval_pipeline import PIPELINE_STEPS


class OnfhEvalEntrypointTest(unittest.TestCase):
    def test_pipeline_exposes_only_the_three_agent_routes(self):
        self.assertEqual(
            set(PIPELINE_STEPS),
            {"real-vlm-agent", "mock-agent", "real-vlm-mock-agent"},
        )

    def test_real_vlm_agent_route_uses_roi_agent_script(self):
        self.assertEqual(
            PIPELINE_STEPS["real-vlm-agent"]["script"],
            "scripts/xray_roi_agent_eval.py",
        )


if __name__ == "__main__":
    unittest.main()
