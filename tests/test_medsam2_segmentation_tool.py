import json
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from agents.vision_agent import VisionAgent
from tools.feature_extraction_tool import FeatureExtractionTool
from tools.medsam2_segmentation_tool import (
    MedSAM2CommandRunner,
    MedSAM2SegmentationTool,
    MissingMedSAM2BackendError,
)
from tools.segmentation_tool import SegmentationTool


class FakeMedSAM2Runner:
    def __init__(self):
        self.calls = []

    def predict_mask(self, image_path, output_mask_path, prompt):
        self.calls.append(
            {
                "image_path": image_path,
                "output_mask_path": output_mask_path,
                "prompt": prompt,
            }
        )
        mask = Image.new("L", (8, 8), 0)
        pixels = mask.load()
        for x in range(1, 5):
            for y in range(1, 5):
                pixels[x, y] = 2
        pixels[2, 2] = 1
        pixels[3, 3] = 4
        mask.save(output_mask_path)
        return output_mask_path


class FakeMedSAM2SegmentationTool:
    def __init__(self):
        self.calls = []

    def segment_with_model(self, image_path, prompt, mask_path, overlay_path):
        self.calls.append(
            {
                "image_path": image_path,
                "prompt": prompt,
                "mask_path": mask_path,
                "overlay_path": overlay_path,
            }
        )
        Path(mask_path).write_text("fake mask", encoding="utf-8")
        Path(overlay_path).write_text("fake overlay", encoding="utf-8")
        return {
            "image_outputs": {
                "original_image_path": image_path,
                "mask_path": mask_path,
                "overlay_path": overlay_path,
            },
            "features": {
                "whole_tumor_volume_ml": 42.0,
                "tumor_core_volume_ml": 12.0,
                "enhancing_tumor_volume_ml": 5.0,
                "edema_present": True,
                "mass_effect": "not_assessed_in_phase_a",
                "segmentation_quality": "medsam2",
                "label_counts": {1: 7, 2: 30, 4: 5},
            },
            "mask_shape": {
                "width": 8,
                "height": 8,
                "depth": 1,
            },
            "segmentation_source": "medsam2",
        }


class MedSAM2SegmentationToolTest(unittest.TestCase):
    def _write_demo_image(self, base_dir: Path) -> Path:
        image_path = base_dir / "case_flair.png"
        Image.new("L", (8, 8), 80).save(image_path)
        return image_path

    def test_medsam2_tool_calls_runner_and_writes_mask(self):
        with TemporaryDirectory() as tmpdir:
            image_path = self._write_demo_image(Path(tmpdir))
            mask_path = Path(tmpdir) / "medsam2_mask.png"
            runner = FakeMedSAM2Runner()

            output = MedSAM2SegmentationTool(runner=runner).predict_mask(
                image_path=image_path,
                output_mask_path=mask_path,
                prompt={"boxes": [[1, 1, 5, 5]]},
            )

            self.assertEqual(output, mask_path)
            self.assertTrue(mask_path.exists())
            self.assertEqual(runner.calls[0]["prompt"], {"boxes": [[1, 1, 5, 5]]})

    def test_medsam2_tool_has_clear_error_without_backend(self):
        with self.assertRaises(MissingMedSAM2BackendError):
            MedSAM2SegmentationTool().predict_mask(
                image_path="case_flair.png",
                output_mask_path="medsam2_mask.png",
                prompt={"boxes": [[1, 1, 5, 5]]},
            )

    def test_command_runner_loads_configuration_from_environment(self):
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
                clear=False,
            ):
                runner = MedSAM2CommandRunner.from_env()

        self.assertEqual(runner.repo_path, repo_path)
        self.assertEqual(runner.timeout_seconds, 120)
        self.assertIn("{image_path}", runner.command_template)

    def test_command_runner_strips_wrapping_quotes_from_environment_template(self):
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "MedSAM2"
            repo_path.mkdir()
            with patch.dict(
                "os.environ",
                {
                    "MEDSAM2_COMMAND_TEMPLATE": "'python infer.py --image {image_path} --output {output_mask_path} --prompt {prompt_json}'",
                    "MEDSAM2_REPO_PATH": str(repo_path),
                },
                clear=True,
            ):
                runner = MedSAM2CommandRunner.from_env()

        self.assertEqual(
            runner.command_template,
            "python infer.py --image {image_path} --output {output_mask_path} --prompt {prompt_json}",
        )

    def test_command_runner_has_clear_error_when_template_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(MissingMedSAM2BackendError):
                MedSAM2CommandRunner.from_env()

    def test_command_runner_rejects_template_missing_required_placeholders(self):
        with patch.dict(
            "os.environ",
            {
                "MEDSAM2_COMMAND_TEMPLATE": "python infer.py --image {image_path}",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(
                MissingMedSAM2BackendError,
                "output_mask_path, prompt_json",
            ):
                MedSAM2CommandRunner.from_env()

    def test_command_runner_rejects_invalid_timeout_from_environment(self):
        with patch.dict(
            "os.environ",
            {
                "MEDSAM2_COMMAND_TEMPLATE": "python infer.py --image {image_path} --output {output_mask_path} --prompt {prompt_json}",
                "MEDSAM2_TIMEOUT_SECONDS": "slow",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(MissingMedSAM2BackendError, "MEDSAM2_TIMEOUT_SECONDS"):
                MedSAM2CommandRunner.from_env()

    def test_command_runner_rejects_missing_repo_path_from_environment(self):
        missing_repo = "/tmp/medsam2_missing_for_test"
        with patch.dict(
            "os.environ",
            {
                "MEDSAM2_COMMAND_TEMPLATE": "python infer.py --image {image_path} --output {output_mask_path} --prompt {prompt_json}",
                "MEDSAM2_REPO_PATH": missing_repo,
            },
            clear=True,
        ):
            with self.assertRaisesRegex(MissingMedSAM2BackendError, "MEDSAM2_REPO_PATH"):
                MedSAM2CommandRunner.from_env()

    def test_command_runner_executes_configured_command(self):
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
                        "parser.add_argument('--prompt')",
                        "args = parser.parse_args()",
                        "Image.new('L', (8, 8), 2).save(args.output)",
                    ]
                ),
                encoding="utf-8",
            )
            image_path = self._write_demo_image(workdir)
            mask_path = workdir / "mask.png"
            runner = MedSAM2CommandRunner(
                command_template=f"python {script_path} --image {{image_path}} --output {{output_mask_path}} --prompt {{prompt_json}}",
                repo_path=workdir,
                timeout_seconds=30,
            )

            output = runner.predict_mask(
                image_path=str(image_path),
                output_mask_path=str(mask_path),
                prompt={"boxes": [[1, 1, 5, 5]]},
            )

            self.assertEqual(output, str(mask_path.resolve()))
            self.assertTrue(mask_path.exists())

    def test_command_runner_passes_absolute_paths_when_repo_cwd_is_set(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            project_dir = workdir / "project"
            repo_path = workdir / "MedSAM2"
            project_dir.mkdir()
            repo_path.mkdir()
            image_path = project_dir / "case_flair.png"
            mask_path = project_dir / "outputs" / "medsam2_mask.png"
            capture_path = workdir / "captured_paths.json"
            Image.new("L", (8, 8), 80).save(image_path)
            script_path = workdir / "capture_paths.py"
            script_path.write_text(
                "\n".join(
                    [
                        "import argparse",
                        "import json",
                        "from pathlib import Path",
                        "from PIL import Image",
                        "parser = argparse.ArgumentParser()",
                        "parser.add_argument('--image')",
                        "parser.add_argument('--output')",
                        "parser.add_argument('--capture')",
                        "parser.add_argument('--prompt')",
                        "args = parser.parse_args()",
                        "Path(args.capture).write_text(json.dumps({'image': args.image, 'output': args.output}), encoding='utf-8')",
                        "Path(args.output).parent.mkdir(parents=True, exist_ok=True)",
                        "Image.new('L', (8, 8), 1).save(args.output)",
                    ]
                ),
                encoding="utf-8",
            )

            runner = MedSAM2CommandRunner(
                command_template=(
                    f"python {script_path} "
                    "--image {image_path} "
                    "--output {output_mask_path} "
                    f"--capture {capture_path} "
                    "--prompt {prompt_json}"
                ),
                repo_path=repo_path,
            )
            runner.predict_mask(
                image_path=image_path.relative_to(project_dir),
                output_mask_path=mask_path.relative_to(project_dir),
                prompt={"boxes": [[1, 1, 5, 5]]},
            )

            captured = json.loads(capture_path.read_text(encoding="utf-8"))
            self.assertTrue(Path(captured["image"]).is_absolute())
            self.assertTrue(Path(captured["output"]).is_absolute())

    def test_segmentation_tool_can_use_medsam2_backend(self):
        with TemporaryDirectory() as tmpdir:
            image_path = self._write_demo_image(Path(tmpdir))
            mask_path = Path(tmpdir) / "medsam2_mask.png"
            overlay_path = Path(tmpdir) / "medsam2_overlay.png"
            medsam2_tool = MedSAM2SegmentationTool(runner=FakeMedSAM2Runner())

            result = SegmentationTool(
                model_backend=medsam2_tool,
                feature_extractor=FeatureExtractionTool(voxel_volume_ml=0.5),
            ).segment_with_model(
                image_path=image_path,
                prompt={"boxes": [[1, 1, 5, 5]]},
                mask_path=mask_path,
                overlay_path=overlay_path,
            )

            self.assertEqual(result["segmentation_source"], "medsam2")
            self.assertTrue(mask_path.exists())
            self.assertTrue(overlay_path.exists())
            self.assertEqual(result["features"]["whole_tumor_volume_ml"], 8.0)
            self.assertEqual(result["features"]["segmentation_quality"], "medsam2")

    def test_vision_agent_can_analyze_brats_with_medsam2_segmentation_model(self):
        with TemporaryDirectory() as tmpdir:
            segmentation_tool = FakeMedSAM2SegmentationTool()
            image_path = str(Path(tmpdir) / "case_flair.png")
            mask_path = str(Path(tmpdir) / "medsam2_mask.png")
            overlay_path = str(Path(tmpdir) / "medsam2_overlay.png")

            result = VisionAgent(segmentation_tool=segmentation_tool).analyze_brats_with_segmentation_model(
                image_path=image_path,
                prompt={"boxes": [[1, 1, 5, 5]]},
                mask_path=mask_path,
                overlay_path=overlay_path,
                disease_skill={"disease_name": "成人弥漫性胶质瘤"},
            )

            self.assertEqual(segmentation_tool.calls[0]["prompt"], {"boxes": [[1, 1, 5, 5]]})
            self.assertEqual(result["image_outputs"]["mask_path"], mask_path)
            self.assertEqual(result["visual_evidence"]["segmentation_quality"], "medsam2")
            self.assertEqual(result["visual_evidence"]["whole_tumor_volume_ml"], 42.0)


if __name__ == "__main__":
    unittest.main()
