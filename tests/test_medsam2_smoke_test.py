import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from scripts.medsam2_smoke_test import run_medsam2_smoke_check


class MedSAM2SmokeTest(unittest.TestCase):
    def test_dry_run_reports_missing_command_template(self):
        with patch.dict("os.environ", {}, clear=True):
            output = run_medsam2_smoke_check(real=False)

        payload = json.loads(output)
        self.assertFalse(payload["command_template_present"])
        self.assertFalse(payload["real_call_ready"])
        self.assertFalse(payload["real_call_attempted"])

    def test_dry_run_reports_ready_when_command_and_repo_exist(self):
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "MedSAM2"
            repo_path.mkdir()
            with patch.dict(
                "os.environ",
                {
                    "MEDSAM2_COMMAND_TEMPLATE": "python infer.py --image {image_path} --output {output_mask_path} --prompt {prompt_json}",
                    "MEDSAM2_REPO_PATH": str(repo_path),
                    "MEDSAM2_TIMEOUT_SECONDS": "120",
                },
                clear=True,
            ):
                output = run_medsam2_smoke_check(real=False)

        payload = json.loads(output)
        self.assertTrue(payload["command_template_present"])
        self.assertTrue(payload["repo_path_exists"])
        self.assertEqual(payload["timeout_seconds"], 120)
        self.assertTrue(payload["real_call_ready"])

    def test_dry_run_reports_missing_required_template_placeholders(self):
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "MedSAM2"
            repo_path.mkdir()
            with patch.dict(
                "os.environ",
                {
                    "MEDSAM2_COMMAND_TEMPLATE": "python infer.py --image {image_path}",
                    "MEDSAM2_REPO_PATH": str(repo_path),
                },
                clear=True,
            ):
                output = run_medsam2_smoke_check(real=False)

        payload = json.loads(output)
        self.assertTrue(payload["command_template_present"])
        self.assertFalse(payload["real_call_ready"])
        self.assertEqual(
            payload["missing_command_template_placeholders"],
            ["output_mask_path", "prompt_json"],
        )

    def test_real_smoke_runs_configured_command_and_writes_mask(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            script_path = workdir / "fake_medsam2_infer.py"
            script_path.write_text(
                "\n".join(
                    [
                        "import argparse",
                        "from PIL import Image",
                        "parser = argparse.ArgumentParser()",
                        "parser.add_argument('--image')",
                        "parser.add_argument('--output')",
                        "parser.add_argument('--prompt-json')",
                        "args = parser.parse_args()",
                        "Image.new('L', (8, 8), 2).save(args.output)",
                    ]
                ),
                encoding="utf-8",
            )
            image_path = workdir / "case_flair.png"
            Image.new("L", (8, 8), 80).save(image_path)
            mask_path = workdir / "medsam2_mask.png"
            with patch.dict(
                "os.environ",
                {
                    "MEDSAM2_COMMAND_TEMPLATE": f"python {script_path} --image {{image_path}} --output {{output_mask_path}} --prompt-json {{prompt_json}}",
                    "MEDSAM2_REPO_PATH": str(workdir),
                },
                clear=False,
            ):
                output = run_medsam2_smoke_check(
                    image_path=image_path,
                    mask_path=mask_path,
                    real=True,
                )

        payload = json.loads(output)
        self.assertTrue(payload["real_call_attempted"])
        self.assertEqual(payload["mask_path"], str(mask_path.resolve()))
        self.assertTrue(payload["mask_created"])


if __name__ == "__main__":
    unittest.main()
