import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from scripts.no_mask_medsam2_segmentation_demo import run_no_mask_medsam2_segmentation_demo


class FakeSegmentationTool:
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
        image = Image.open(image_path)
        mask = Image.new("L", image.size, 0)
        pixels = mask.load()
        for x in range(2, 6):
            for y in range(3, 8):
                pixels[x, y] = 255
        mask.save(mask_path)
        image.convert("RGB").save(overlay_path)
        return {
            "image_outputs": {
                "original_image_path": str(image_path),
                "mask_path": str(mask_path),
                "overlay_path": str(overlay_path),
            },
            "features": {"segmentation_quality": "fake_medsam2"},
            "mask_shape": {"width": image.size[0], "height": image.size[1], "depth": 1},
            "segmentation_source": "medsam2",
        }


class PromptBoxSegmentationTool:
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
        image = Image.open(image_path)
        mask = Image.new("L", image.size, 0)
        pixels = mask.load()
        x1, y1, x2, y2 = [int(value) for value in prompt["boxes"][0]]
        for x in range(max(x1, 0), min(x2, image.size[0])):
            for y in range(max(y1, 0), min(y2, image.size[1])):
                pixels[x, y] = 255
        mask.save(mask_path)
        image.convert("RGB").save(overlay_path)
        return {
            "image_outputs": {
                "original_image_path": str(image_path),
                "mask_path": str(mask_path),
                "overlay_path": str(overlay_path),
            },
            "features": {"segmentation_quality": "fake_medsam2"},
            "mask_shape": {"width": image.size[0], "height": image.size[1], "depth": 1},
            "segmentation_source": "medsam2",
        }


class OutsidePromptSegmentationTool:
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
        image = Image.open(image_path)
        mask = Image.new("L", image.size, 0)
        pixels = mask.load()
        for x in range(12, 18):
            for y in range(1, 5):
                pixels[x, y] = 255
        mask.save(mask_path)
        image.convert("RGB").save(overlay_path)
        return {
            "image_outputs": {
                "original_image_path": str(image_path),
                "mask_path": str(mask_path),
                "overlay_path": str(overlay_path),
            },
            "features": {"segmentation_quality": "fake_medsam2"},
            "mask_shape": {"width": image.size[0], "height": image.size[1], "depth": 1},
            "segmentation_source": "medsam2",
        }


class NoMaskMedSAM2SegmentationDemoTest(unittest.TestCase):
    def _write_prompt_result(self, base_dir: Path) -> tuple[Path, Path]:
        image_path = base_dir / "cxr.png"
        prompt_path = base_dir / "vision_prompt_result.json"
        Image.new("RGB", (10, 10), "black").save(image_path)
        prompt_path.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "image_path": str(image_path),
                    "segmentation_prompt": {
                        "source": "vision_model_bbox",
                        "boxes": [[1, 2, 7, 9]],
                        "points": [],
                        "image_size": {"width": 10, "height": 10},
                    },
                    "diagnosis_usable": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return image_path, prompt_path

    def test_demo_runs_segmentation_tool_and_writes_measurements(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            _, prompt_path = self._write_prompt_result(workdir)
            fake_tool = FakeSegmentationTool()

            result = run_no_mask_medsam2_segmentation_demo(
                prompt_result_path=prompt_path,
                output_dir=workdir / "out",
                segmentation_tool=fake_tool,
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(fake_tool.calls[0]["prompt"]["boxes"], [[1, 2, 7, 9]])
            self.assertTrue(Path(result["mask_path"]).exists())
            self.assertTrue(Path(result["overlay_path"]).exists())
            self.assertTrue(Path(result["comparison_path"]).exists())
            self.assertEqual(
                result["segmentation_result"]["comparison_path"],
                result["comparison_path"],
            )
            self.assertEqual(
                result["findings"][0]["regions"][0]["comparison_path"],
                result["comparison_path"],
            )
            with Image.open(result["comparison_path"]) as comparison:
                self.assertEqual(comparison.size, (20, 10))
            self.assertEqual(result["measurements"]["lesion_area_px"], 20)
            self.assertEqual(result["measurements"]["lesion_area_ratio"], 0.2)
            self.assertEqual(result["segmentation_result"]["status"], "completed")

    def test_demo_marks_mask_outside_prompt_box_as_not_diagnosis_usable(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.png"
            prompt_path = workdir / "vision_prompt_result.json"
            Image.new("RGB", (20, 10), "black").save(image_path)
            prompt_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "image_path": str(image_path),
                        "segmentation_prompt": {
                            "source": "vision_model_bbox",
                            "boxes": [[1, 1, 5, 5]],
                            "points": [],
                            "image_size": {"width": 20, "height": 10},
                        },
                        "suspected_regions": [
                            {
                                "target": "sclerotic_band",
                                "bbox": [1, 1, 5, 5],
                                "confidence": 0.82,
                                "rationale": "candidate sclerosis",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_no_mask_medsam2_segmentation_demo(
                prompt_result_path=prompt_path,
                output_dir=workdir / "out",
                segmentation_tool=OutsidePromptSegmentationTool(),
            )

            finding = result["findings"][0]
            alignment = finding["measurements"]["box_mask_alignment"]
            self.assertEqual(result["status"], "ok")
            self.assertFalse(result["diagnosis_usable"])
            self.assertFalse(result["segmentation_results"][0]["diagnosis_usable"])
            self.assertFalse(finding["diagnosis_usable"])
            self.assertEqual(alignment["status"], "low_alignment")
            self.assertEqual(alignment["prompt_bbox"], [1, 1, 5, 5])
            self.assertEqual(alignment["mask_bbox"], [12, 1, 18, 5])
            self.assertEqual(alignment["mask_area_inside_prompt_ratio"], 0.0)
            self.assertEqual(alignment["mask_bbox_iou"], 0.0)
            self.assertEqual(
                result["quality_warnings"][0]["code"],
                "box_mask_misalignment",
            )

    def test_demo_adds_anatomy_normalized_measurements_when_anatomy_mask_is_given(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            _, prompt_path = self._write_prompt_result(workdir)
            anatomy_mask_path = workdir / "femoral_head_mask.png"
            anatomy = Image.new("L", (10, 10), 0)
            pixels = anatomy.load()
            for x in range(0, 8):
                for y in range(0, 8):
                    pixels[x, y] = 255
            anatomy.save(anatomy_mask_path)
            fake_tool = FakeSegmentationTool()

            result = run_no_mask_medsam2_segmentation_demo(
                prompt_result_path=prompt_path,
                output_dir=workdir / "out",
                segmentation_tool=fake_tool,
                anatomy_mask_path=anatomy_mask_path,
                anatomy_name="femoral_head",
            )

            self.assertEqual(result["measurements"]["anatomy_name"], "femoral_head")
            self.assertEqual(result["measurements"]["anatomy_area_px"], 64)
            self.assertEqual(result["measurements"]["lesion_overlap_anatomy_px"], 20)
            self.assertEqual(result["measurements"]["lesion_area_ratio_in_anatomy"], 0.3125)
            self.assertEqual(
                result["findings"][0]["measurements"]["area_ratio_in_anatomy"],
                0.3125,
            )
            self.assertEqual(
                result["findings"][0]["regions"][0]["area_ratio_in_anatomy"],
                0.3125,
            )

    def test_demo_matches_each_finding_to_best_overlapping_anatomy_candidate(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.png"
            prompt_path = workdir / "vision_prompt_result.json"
            Image.new("RGB", (20, 10), "black").save(image_path)
            prompt_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "image_path": str(image_path),
                        "segmentation_prompt": {
                            "source": "vision_model_bbox",
                            "boxes": [[12, 2, 18, 8]],
                            "points": [],
                            "image_size": {"width": 20, "height": 10},
                        },
                        "suspected_regions": [
                            {
                                "target": "sclerotic_band",
                                "bbox": [12, 2, 18, 8],
                                "confidence": 0.82,
                                "rationale": "right-side candidate",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            left_anatomy_path = workdir / "left_femoral_head.png"
            right_anatomy_path = workdir / "right_femoral_head.png"
            left = Image.new("L", (20, 10), 0)
            right = Image.new("L", (20, 10), 0)
            left_pixels = left.load()
            right_pixels = right.load()
            for x in range(0, 8):
                for y in range(0, 10):
                    left_pixels[x, y] = 255
            for x in range(10, 20):
                for y in range(0, 10):
                    right_pixels[x, y] = 255
            left.save(left_anatomy_path)
            right.save(right_anatomy_path)

            result = run_no_mask_medsam2_segmentation_demo(
                prompt_result_path=prompt_path,
                output_dir=workdir / "out",
                segmentation_tool=PromptBoxSegmentationTool(),
                anatomy_candidates=[
                    {
                        "anatomy_name": "left_femoral_head",
                        "mask_path": str(left_anatomy_path),
                    },
                    {
                        "anatomy_name": "right_femoral_head",
                        "mask_path": str(right_anatomy_path),
                    },
                ],
            )

            self.assertEqual(result["status"], "ok")
            finding = result["findings"][0]
            self.assertEqual(finding["measurements"]["anatomy_name"], "right_femoral_head")
            self.assertEqual(finding["measurements"]["overlap_anatomy_px"], 36)
            self.assertEqual(finding["measurements"]["area_ratio_in_anatomy"], 0.36)
            self.assertEqual(
                finding["measurements"]["anatomy_match"]["anatomy_name"],
                "right_femoral_head",
            )
            self.assertEqual(
                finding["measurements"]["anatomy_match"]["overlap_anatomy_px"],
                36,
            )
            self.assertEqual(
                finding["measurements"]["anatomy_candidates_evaluated"][0]["anatomy_name"],
                "right_femoral_head",
            )

    def test_demo_marks_overlapping_candidate_masks_as_non_independent_evidence(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.png"
            prompt_path = workdir / "vision_prompt_result.json"
            Image.new("RGB", (12, 12), "black").save(image_path)
            prompt_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "image_path": str(image_path),
                        "segmentation_prompt": {
                            "source": "vision_model_bbox",
                            "boxes": [[1, 1, 7, 7], [2, 2, 8, 8]],
                            "points": [],
                            "image_size": {"width": 12, "height": 12},
                        },
                        "suspected_regions": [
                            {
                                "target": "sclerotic_band",
                                "bbox": [1, 1, 7, 7],
                                "confidence": 0.82,
                                "rationale": "linear dense band",
                            },
                            {
                                "target": "collapse",
                                "bbox": [2, 2, 8, 8],
                                "confidence": 0.74,
                                "rationale": "flattened contour",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_no_mask_medsam2_segmentation_demo(
                prompt_result_path=prompt_path,
                output_dir=workdir / "out",
                segmentation_tool=FakeSegmentationTool(),
            )

            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["quality_warnings"])
            self.assertEqual(
                result["quality_warnings"][0]["code"],
                "overlapping_candidate_findings",
            )
            first, second = result["findings"]
            self.assertTrue(first["independent_evidence"])
            self.assertFalse(second["independent_evidence"])
            self.assertEqual(
                second["overlap_qc"]["overlap_with_finding_id"],
                first["finding_id"],
            )
            self.assertGreaterEqual(second["overlap_qc"]["mask_iou"], 0.9)
            self.assertIn(
                "overlaps with another finding mask",
                second["segmentation_ref"]["quality"]["warnings"],
            )

    def test_demo_segments_each_suspected_region_into_structured_findings(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path, prompt_path = self._write_prompt_result(workdir)
            prompt_payload = json.loads(prompt_path.read_text(encoding="utf-8"))
            prompt_payload["suspected_regions"] = [
                {
                    "target": "sclerotic_band",
                    "bbox": [1, 2, 7, 9],
                    "confidence": 0.73,
                    "rationale": "band-like increased density",
                },
                {
                    "target": "cystic_change",
                    "bbox": [2, 3, 8, 9],
                    "confidence": 0.64,
                    "rationale": "small lucent candidate",
                },
            ]
            prompt_path.write_text(json.dumps(prompt_payload, ensure_ascii=False), encoding="utf-8")
            fake_tool = FakeSegmentationTool()

            result = run_no_mask_medsam2_segmentation_demo(
                prompt_result_path=prompt_path,
                output_dir=workdir / "out",
                segmentation_tool=fake_tool,
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(fake_tool.calls), 2)
            self.assertEqual(fake_tool.calls[0]["prompt"]["boxes"], [[1, 2, 7, 9]])
            self.assertEqual(fake_tool.calls[1]["prompt"]["boxes"], [[2, 3, 8, 9]])
            self.assertEqual([finding["target"] for finding in result["findings"]], ["sclerotic_band", "cystic_change"])
            self.assertEqual(
                len({finding["finding_id"] for finding in result["findings"]}),
                2,
            )
            self.assertEqual([finding["display_name"] for finding in result["findings"]], ["硬化带", "囊性变"])
            self.assertEqual(result["findings"][0]["regions"][0]["area_px"], 20)
            self.assertTrue(Path(result["findings"][0]["regions"][0]["mask_path"]).exists())
            self.assertEqual(result["findings"][1]["confidence"], 0.64)

    def test_demo_gives_unique_finding_ids_when_same_target_has_multiple_regions(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path, prompt_path = self._write_prompt_result(workdir)
            prompt_payload = json.loads(prompt_path.read_text(encoding="utf-8"))
            prompt_payload["suspected_regions"] = [
                {
                    "target": "sclerotic_band",
                    "bbox": [1, 2, 7, 9],
                    "confidence": 0.73,
                    "rationale": "right-side band-like increased density",
                },
                {
                    "target": "sclerotic_band",
                    "bbox": [10, 2, 16, 9],
                    "confidence": 0.68,
                    "rationale": "left-side band-like increased density",
                },
            ]
            prompt_path.write_text(json.dumps(prompt_payload, ensure_ascii=False), encoding="utf-8")

            result = run_no_mask_medsam2_segmentation_demo(
                prompt_result_path=prompt_path,
                output_dir=workdir / "out",
                segmentation_tool=FakeSegmentationTool(),
            )

            finding_ids = [finding["finding_id"] for finding in result["findings"]]
            self.assertEqual(len(finding_ids), 2)
            self.assertEqual(len(set(finding_ids)), 2)

    def test_demo_infers_image_side_for_multiple_candidates_from_centroid(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            image_path = workdir / "hip.png"
            prompt_path = workdir / "vision_prompt_result.json"
            Image.new("RGB", (20, 10), "black").save(image_path)
            prompt_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "image_path": str(image_path),
                        "segmentation_prompt": {
                            "source": "vision_model_bbox",
                            "boxes": [[1, 2, 7, 8], [12, 2, 18, 8]],
                            "points": [],
                            "image_size": {"width": 20, "height": 10},
                        },
                        "suspected_regions": [
                            {
                                "target": "sclerotic_band",
                                "bbox": [1, 2, 7, 8],
                                "confidence": 0.73,
                                "rationale": "image-left band-like density",
                            },
                            {
                                "target": "sclerotic_band",
                                "bbox": [12, 2, 18, 8],
                                "confidence": 0.68,
                                "rationale": "image-right band-like density",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_no_mask_medsam2_segmentation_demo(
                prompt_result_path=prompt_path,
                output_dir=workdir / "out",
                segmentation_tool=PromptBoxSegmentationTool(),
            )

            self.assertEqual(
                [finding["measurements"]["laterality"] for finding in result["findings"]],
                ["image_left", "image_right"],
            )
            self.assertEqual(
                [finding["regions"][0]["laterality"] for finding in result["findings"]],
                ["image_left", "image_right"],
            )

    def test_demo_reports_not_ready_without_medsam2_runner(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            _, prompt_path = self._write_prompt_result(workdir)

            result = run_no_mask_medsam2_segmentation_demo(
                prompt_result_path=prompt_path,
                output_dir=workdir / "out",
                segmentation_tool=None,
            )

            self.assertEqual(result["status"], "medsam2_not_ready")
            self.assertIn("MEDSAM2_COMMAND_TEMPLATE", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
