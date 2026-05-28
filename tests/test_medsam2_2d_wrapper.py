import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from scripts.medsam2_2d_wrapper import (
    build_medscope_medsam2_2d_command_template,
    run_medsam2_2d_wrapper,
    validate_2d_prompt,
)


class MedSAM22DWrapperTest(unittest.TestCase):
    def test_validate_2d_prompt_accepts_box_prompt(self):
        prompt = validate_2d_prompt({"boxes": [[1, 2, 7, 9]]})

        self.assertEqual(prompt["box"], [1, 2, 7, 9])

    def test_validate_2d_prompt_rejects_missing_box(self):
        with self.assertRaisesRegex(ValueError, "requires boxes"):
            validate_2d_prompt({"points": []})

    def test_dry_run_reports_missing_runtime_inputs(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "cxr.png"
            Image.new("RGB", (10, 10), "black").save(image_path)

            payload = json.loads(
                run_medsam2_2d_wrapper(
                    image_path=image_path,
                    output_mask_path=Path(tmpdir) / "mask.png",
                    prompt={"boxes": [[1, 2, 7, 9]]},
                    medsam2_repo_path=Path(tmpdir) / "missing_repo",
                    checkpoint_path=Path(tmpdir) / "missing.pt",
                    cfg_path=Path(tmpdir) / "missing.yaml",
                    dry_run=True,
                )
            )

            self.assertEqual(payload["status"], "error")
            self.assertIn("medsam2 repo not found", "\n".join(payload["errors"]))

    def test_command_template_contains_runner_placeholders(self):
        template = build_medscope_medsam2_2d_command_template(
            wrapper_path="/repo/scripts/medsam2_2d_wrapper.py",
            medsam2_repo_path="/tmp/MedSAM2",
            checkpoint_path="/tmp/MedSAM2/checkpoints/MedSAM2_latest.pt",
            cfg_path="/tmp/MedSAM2/sam2/configs/sam2.1_hiera_t512.yaml",
            device="cpu",
        )

        self.assertIn("{image_path}", template)
        self.assertIn("{output_mask_path}", template)
        self.assertIn("{prompt_json}", template)
        self.assertIn("--device cpu", template)


if __name__ == "__main__":
    unittest.main()
