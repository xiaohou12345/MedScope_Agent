import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.brats_medsam2_auto_eval import run_brats_medsam2_auto_eval


REAL_SAMPLE_DIR = Path("data/external/brats2021_00030")
REAL_IMAGE = REAL_SAMPLE_DIR / "BraTS2021_00030_flair.nii.gz"
REAL_MASK = REAL_SAMPLE_DIR / "BraTS2021_00030_seg.nii.gz"
REAL_MANIFEST = Path("data/external/brats_manifest.json")


class CopyReferenceMaskRunner:
    def __init__(self, reference_mask_path: Path) -> None:
        self.reference_mask_path = reference_mask_path
        self.calls = []

    def predict_mask(self, image_path, output_mask_path, prompt):
        self.calls.append(
            {
                "image_path": image_path,
                "output_mask_path": output_mask_path,
                "prompt": prompt,
            }
        )
        shutil.copyfile(self.reference_mask_path, output_mask_path)
        return output_mask_path


@unittest.skipUnless(
    REAL_IMAGE.exists() and REAL_MASK.exists() and REAL_MANIFEST.exists(),
    "real BraTS2021 sample files are not downloaded",
)
class BratsMedSAM2AutoEvalTest(unittest.TestCase):
    def test_eval_requires_non_reference_prompt_before_running_model(self):
        with TemporaryDirectory() as tmpdir:
            payload = run_brats_medsam2_auto_eval(
                manifest_path=REAL_MANIFEST,
                case_id="brats2021_00030",
                prompt_path=None,
                output_dir=Path(tmpdir),
            )

        self.assertEqual(payload["status"], "needs_prompt")
        self.assertFalse(payload["real_call_attempted"])
        self.assertIn("vision_model_bbox", payload["action_items"][0])

    def test_eval_rejects_reference_mask_bbox_prompt_by_default(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "prompt.json"
            prompt_path.write_text(
                json.dumps(
                    {
                        "source": "reference_mask_bbox",
                        "slice_index": 100,
                        "boxes": [[60, 133, 124, 193]],
                    }
                ),
                encoding="utf-8",
            )

            payload = run_brats_medsam2_auto_eval(
                manifest_path=REAL_MANIFEST,
                case_id="brats2021_00030",
                prompt_path=prompt_path,
                output_dir=root / "output",
            )

        self.assertEqual(payload["status"], "rejected_reference_prompt")
        self.assertFalse(payload["real_call_attempted"])
        self.assertIn("not allowed", payload["reason"])

    def test_eval_not_ready_writes_summary_for_auditable_gate_result(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "vision_prompt.json"
            output_dir = root / "output"
            prompt_path.write_text(
                json.dumps(
                    {
                        "source": "vision_model_bbox",
                        "slice_index": 100,
                        "boxes": [[58, 130, 125, 195]],
                        "label_ids": [1],
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {}, clear=True):
                payload = run_brats_medsam2_auto_eval(
                    manifest_path=REAL_MANIFEST,
                    case_id="brats2021_00030",
                    prompt_path=prompt_path,
                    output_dir=output_dir,
                )

            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(summary["status"], "not_ready")
        self.assertEqual(summary["prompt_source"], "vision_model_bbox")
        self.assertFalse(summary["real_call_attempted"])

    def test_eval_runs_fake_medsam2_and_scores_against_reference_without_using_reference_as_prompt(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "vision_prompt.json"
            prompt_path.write_text(
                json.dumps(
                    {
                        "source": "vision_model_bbox",
                        "slice_index": 100,
                        "boxes": [[60, 133, 124, 193]],
                        "label_ids": [1],
                    }
                ),
                encoding="utf-8",
            )
            runner = CopyReferenceMaskRunner(REAL_MASK)

            payload = run_brats_medsam2_auto_eval(
                manifest_path=REAL_MANIFEST,
                case_id="brats2021_00030",
                prompt_path=prompt_path,
                output_dir=root / "output",
                medsam2_runner=runner,
            )

            result_path = Path(payload["result_json_path"])
            model_mask_path = Path(payload["image_outputs"]["mask_path"])

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["case_id"], "brats2021_00030")
            self.assertEqual(payload["prompt_source"], "vision_model_bbox")
            self.assertEqual(payload["data_boundary"]["reference_mask_role"], "evaluation_only")
            self.assertTrue(payload["real_call_attempted"])
            self.assertEqual(len(runner.calls), 1)
            self.assertTrue(result_path.exists())
            self.assertTrue(model_mask_path.exists())
            self.assertEqual(payload["evaluation"]["whole_tumor_dice"], 1.0)
            self.assertEqual(payload["result"]["visual_evidence"]["measurements"]["whole_tumor_volume_ml"], 117.996)


if __name__ == "__main__":
    unittest.main()
