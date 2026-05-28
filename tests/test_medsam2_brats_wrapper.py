import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.medsam2_brats_wrapper import (
    build_medscope_medsam2_command_template,
    normalize_medsam2_cfg_name,
    run_medsam2_brats_wrapper,
    validate_medscope_prompt,
)


class MedSAM2BratsWrapperTest(unittest.TestCase):
    def test_command_template_contains_required_runner_placeholders(self):
        template = build_medscope_medsam2_command_template(
            wrapper_path="/repo/scripts/medsam2_brats_wrapper.py",
            medsam2_repo_path="/opt/MedSAM2",
            checkpoint_path="/opt/MedSAM2/checkpoints/MedSAM2_latest.pt",
        )

        self.assertIn("{image_path}", template)
        self.assertIn("{output_mask_path}", template)
        self.assertIn("{prompt_json}", template)
        self.assertIn("--medsam2-repo /opt/MedSAM2", template)
        self.assertIn("--checkpoint /opt/MedSAM2/checkpoints/MedSAM2_latest.pt", template)

    def test_validate_prompt_normalizes_first_box_and_slice_index(self):
        prompt = {
            "slice_index": "100",
            "boxes": [["60", "133", "124", "193"]],
            "label_ids": [1, 2, 4],
        }

        normalized = validate_medscope_prompt(prompt)

        self.assertEqual(normalized["slice_index"], 100)
        self.assertEqual(normalized["box"], [60, 133, 124, 193])
        self.assertEqual(normalized["label_ids"], [1, 2, 4])

    def test_validate_prompt_rejects_missing_box_or_slice(self):
        with self.assertRaisesRegex(ValueError, "slice_index"):
            validate_medscope_prompt({"boxes": [[1, 2, 3, 4]]})
        with self.assertRaisesRegex(ValueError, "boxes"):
            validate_medscope_prompt({"slice_index": 5})

    def test_normalize_cfg_name_accepts_repo_absolute_path(self):
        cfg_name = normalize_medsam2_cfg_name(
            cfg_path="/tmp/MedSAM2/sam2/configs/sam2.1_hiera_t512.yaml",
            medsam2_repo_path="/tmp/MedSAM2",
        )

        self.assertEqual(cfg_name, "configs/sam2.1_hiera_t512.yaml")

    def test_dry_run_reports_wrapper_contract_without_running_model(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "case_flair.nii.gz"
            output_mask_path = workdir / "case_mask.nii.gz"
            medsam2_repo = workdir / "MedSAM2"
            checkpoint_path = workdir / "MedSAM2" / "checkpoints" / "MedSAM2_latest.pt"
            cfg_path = workdir / "MedSAM2" / "sam2" / "configs" / "sam2.1_hiera_t512.yaml"
            image_path.write_bytes(b"placeholder")
            checkpoint_path.parent.mkdir(parents=True)
            cfg_path.parent.mkdir(parents=True)
            checkpoint_path.write_bytes(b"checkpoint")
            cfg_path.write_text("model: placeholder\n", encoding="utf-8")

            output = run_medsam2_brats_wrapper(
                image_path=image_path,
                output_mask_path=output_mask_path,
                prompt={"slice_index": 7, "boxes": [[1, 2, 3, 4]]},
                medsam2_repo_path=medsam2_repo,
                checkpoint_path=checkpoint_path,
                cfg_path=cfg_path,
                dry_run=True,
            )

        payload = json.loads(output)
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["real_call_attempted"])
        self.assertEqual(payload["image_path"], str(image_path))
        self.assertEqual(payload["output_mask_path"], str(output_mask_path))
        self.assertEqual(payload["prompt"]["box_for_medscope"], [1, 2, 3, 4])

    def test_dry_run_reports_missing_checkpoint_and_cfg_before_real_call(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "case_flair.nii.gz"
            medsam2_repo = workdir / "MedSAM2"
            image_path.write_bytes(b"placeholder")
            medsam2_repo.mkdir()

            output = run_medsam2_brats_wrapper(
                image_path=image_path,
                output_mask_path=workdir / "case_mask.nii.gz",
                prompt={"slice_index": 7, "boxes": [[1, 2, 3, 4]]},
                medsam2_repo_path=medsam2_repo,
                dry_run=True,
            )

        payload = json.loads(output)
        self.assertEqual(payload["status"], "error")
        self.assertFalse(payload["real_call_attempted"])
        self.assertTrue(any("checkpoint not found" in error for error in payload["errors"]))
        self.assertTrue(any("cfg not found" in error for error in payload["errors"]))

    def test_dry_run_requires_explicit_medsam2_repo(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "case_flair.nii.gz"
            image_path.write_bytes(b"placeholder")

            output = run_medsam2_brats_wrapper(
                image_path=image_path,
                output_mask_path=workdir / "case_mask.nii.gz",
                prompt={"slice_index": 7, "boxes": [[1, 2, 3, 4]]},
                medsam2_repo_path=None,
                dry_run=True,
            )

        payload = json.loads(output)
        self.assertEqual(payload["status"], "error")
        self.assertTrue(any("MEDSAM2_REPO_PATH" in error for error in payload["errors"]))

    def test_cli_can_print_command_template_without_image_arguments(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.medsam2_brats_wrapper",
                "--print-command-template",
                "--medsam2-repo",
                "/opt/MedSAM2",
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("{image_path}", completed.stdout)
        self.assertIn("--medsam2-repo /opt/MedSAM2", completed.stdout)


if __name__ == "__main__":
    unittest.main()
