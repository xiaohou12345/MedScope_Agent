import json
import shutil
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.brats_medsam2_auto_eval import run_brats_medsam2_auto_eval
from scripts.brats_vlm_prompt_demo import main, run_brats_vlm_prompt_demo


REAL_SAMPLE_DIR = Path("data/external/brats2021_00030")
REAL_IMAGE = REAL_SAMPLE_DIR / "BraTS2021_00030_flair.nii.gz"
REAL_MASK = REAL_SAMPLE_DIR / "BraTS2021_00030_seg.nii.gz"
REAL_MANIFEST = Path("data/external/brats_manifest.json")


class RecordingVisionClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = []

    def chat_with_image(self, *, image_path, system_prompt, user_payload, task):
        self.calls.append(
            {
                "image_path": image_path,
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "task": task,
            }
        )
        return self.content


class CopyReferenceMaskRunner:
    def __init__(self, reference_mask_path: Path) -> None:
        self.reference_mask_path = reference_mask_path

    def predict_mask(self, image_path, output_mask_path, prompt):
        shutil.copyfile(self.reference_mask_path, output_mask_path)
        return output_mask_path


class FailingVisionClient:
    def chat_with_image(self, *, image_path, system_prompt, user_payload, task):
        raise OSError("temporary vision route failure")


@unittest.skipUnless(
    REAL_IMAGE.exists() and REAL_MASK.exists() and REAL_MANIFEST.exists(),
    "real BraTS2021 sample files are not downloaded",
)
class BratsVlmPromptDemoTest(unittest.TestCase):
    def test_vlm_prompt_exports_slice_png_and_writes_non_reference_medsam2_prompt(self):
        with TemporaryDirectory() as tmpdir:
            client = RecordingVisionClient(
                json.dumps(
                    {
                        "modality": "mri",
                        "body_part": "brain",
                        "suspected_regions": [
                            {
                                "target": "whole_tumor",
                                "bbox": [60, 133, 124, 193],
                                "confidence": 0.81,
                                "rationale": "FLAIR hyperintense mass-like region.",
                            }
                        ],
                        "limitations": ["single 2D slice only"],
                    }
                )
            )

            payload = run_brats_vlm_prompt_demo(
                image_path=REAL_IMAGE,
                output_dir=Path(tmpdir),
                slice_index=100,
                client=client,
            )

            slice_png = Path(payload["slice_png_path"])
            medsam2_prompt_path = Path(payload["medsam2_prompt_path"])
            medsam2_prompt = json.loads(medsam2_prompt_path.read_text(encoding="utf-8"))

            self.assertEqual(payload["status"], "ok")
            self.assertTrue(slice_png.exists())
            self.assertTrue(medsam2_prompt_path.exists())
            self.assertGreater(slice_png.stat().st_size, 1000)
            self.assertEqual(medsam2_prompt["source"], "vision_model_bbox")
            self.assertEqual(medsam2_prompt["slice_index"], 100)
            self.assertEqual(medsam2_prompt["boxes"], [[60, 133, 124, 193]])
            self.assertNotIn("reference_mask_path", medsam2_prompt)
            self.assertEqual(client.calls[0]["task"], "vision_prompt_generation")

    def test_generated_vlm_prompt_can_enter_auto_eval_gate(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            client = RecordingVisionClient(
                json.dumps(
                    {
                        "modality": "mri",
                        "body_part": "brain",
                        "suspected_regions": [
                            {
                                "target": "whole_tumor",
                                "bbox": [60, 133, 124, 193],
                                "confidence": 0.81,
                            }
                        ],
                    }
                )
            )

            prompt_payload = run_brats_vlm_prompt_demo(
                image_path=REAL_IMAGE,
                output_dir=root / "prompt",
                slice_index=100,
                client=client,
            )
            eval_payload = run_brats_medsam2_auto_eval(
                manifest_path=REAL_MANIFEST,
                case_id="brats2021_00030",
                prompt_path=prompt_payload["medsam2_prompt_path"],
                output_dir=root / "eval",
                medsam2_runner=CopyReferenceMaskRunner(REAL_MASK),
            )

        self.assertEqual(eval_payload["status"], "ok")
        self.assertEqual(eval_payload["prompt_source"], "vision_model_bbox")
        self.assertEqual(eval_payload["data_boundary"]["reference_mask_role"], "evaluation_only")

    def test_cli_reports_vlm_not_ready_without_api_key(self):
        with (
            TemporaryDirectory() as tmpdir,
            patch.dict("os.environ", {}, clear=True),
            patch("scripts.brats_vlm_prompt_demo._load_dotenv_local", lambda: None),
        ):
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--slice-index",
                        "100",
                        "--output-dir",
                        str(Path(tmpdir) / "prompt"),
                    ]
                )

            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "vlm_not_ready")
        self.assertFalse(payload["real_call_attempted"])
        self.assertIn("DMX_API_KEY", payload["errors"][0])

    def test_vlm_route_failure_returns_structured_not_ready_payload(self):
        with TemporaryDirectory() as tmpdir:
            payload = run_brats_vlm_prompt_demo(
                image_path=REAL_IMAGE,
                output_dir=Path(tmpdir),
                slice_index=100,
                client=FailingVisionClient(),
            )

        self.assertEqual(payload["status"], "vlm_not_ready")
        self.assertFalse(payload["real_call_attempted"])
        self.assertIn("temporary vision route failure", payload["errors"][0])


if __name__ == "__main__":
    unittest.main()
