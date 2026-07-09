import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from tools.onfh_collapse_measurement_tool import (
    ImageRulerCalibration,
    ONFHCollapseMeasurementTool,
)
from scripts.onfh_collapse_measurement_demo import build_calibration


def write_circle_mask_with_superior_notch(
    path: Path,
    *,
    size: tuple[int, int] = (140, 140),
    center: tuple[int, int] = (70, 72),
    radius: int = 42,
    notch_depth_px: int = 8,
) -> None:
    image = Image.new("L", size, 0)
    pixels = image.load()
    cx, cy = center
    for y in range(size[1]):
        for x in range(size[0]):
            dx = x - cx
            dy = y - cy
            if dx * dx + dy * dy > radius * radius:
                continue
            top_y = cy - math.sqrt(max(radius * radius - dx * dx, 0))
            if abs(dx) <= 10 and y < top_y + notch_depth_px:
                continue
            pixels[x, y] = 255
    image.save(path)


def write_circle_mask_with_asymmetric_superior_notches(
    path: Path,
    *,
    size: tuple[int, int] = (160, 160),
    center: tuple[int, int] = (80, 82),
    radius: int = 46,
) -> None:
    image = Image.new("L", size, 0)
    pixels = image.load()
    cx, cy = center
    for y in range(size[1]):
        for x in range(size[0]):
            dx = x - cx
            dy = y - cy
            if dx * dx + dy * dy > radius * radius:
                continue
            top_y = cy - math.sqrt(max(radius * radius - dx * dx, 0))
            is_far_lateral_left_edge_notch = -44 <= dx <= -35 and y < top_y + 20
            is_lateral_left_notch = -25 <= dx <= -10 and y < top_y + 7
            is_medial_right_notch = 10 <= dx <= 25 and y < top_y + 18
            if is_far_lateral_left_edge_notch or is_lateral_left_notch or is_medial_right_notch:
                continue
            pixels[x, y] = 255
    image.save(path)


class ONFHCollapseMeasurementToolTest(unittest.TestCase):
    def test_measures_normalized_depression_without_mm_when_no_calibration(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "xray.png"
            mask_path = Path(tmpdir) / "femoral_head_mask.png"
            Image.new("L", (140, 140), 80).save(image_path)
            write_circle_mask_with_superior_notch(mask_path, notch_depth_px=8)

            result = ONFHCollapseMeasurementTool().measure(
                image_path=image_path,
                femoral_head_mask_path=mask_path,
            )

            self.assertEqual(result["target"], "femoral_head_collapse")
            self.assertEqual(result["measurement_method"], "reference_contour_deviation")
            self.assertTrue(result["measurement_usable"])
            self.assertGreater(result["maximum_depression_px"], 5.0)
            self.assertIsNone(result["maximum_depression_mm"])
            self.assertGreater(result["normalized_depression"], 0.05)
            self.assertEqual(result["reference_fit"]["type"], "complete_contour_model")
            self.assertEqual(result["reference_fit"]["fit_strategy"], "closed_radial_contour_reconstruction")
            self.assertIn("femoral_head_deficiency_pW_percent", result)
            self.assertIn("reference_diameter_px", result)
            self.assertAlmostEqual(
                result["femoral_head_deficiency_pW_percent"],
                result["maximum_depression_px"] / result["reference_diameter_px"] * 100.0,
                places=3,
            )
            self.assertIn("concentric_circle", result["reference_fit"]["model"])
            self.assertIn("observed_contour", result)
            self.assertIn("reconstructed_complete_contour", result)
            self.assertIn("actual_mask_contour", result)
            self.assertEqual(
                result["actual_mask_contour"]["type"],
                "actual_closed_mask_contour",
            )
            self.assertEqual(
                result["reconstructed_complete_contour"]["type"],
                "fitted_complete_closed_contour",
            )
            self.assertGreater(result["observed_contour"]["point_count"], 0)
            self.assertGreater(result["actual_mask_contour"]["point_count"], 100)
            self.assertGreater(result["reconstructed_complete_contour"]["point_count"], 100)
            reconstructed_y_values = [
                point[1]
                for point in result["reconstructed_complete_contour"]["sampled_points"]
            ]
            self.assertGreater(max(reconstructed_y_values), 95.0)
            self.assertGreater(
                result["quality"]["excluded_suspected_defect_column_count"],
                0,
            )
            self.assertEqual(result["calibration_source"], "none")
            self.assertEqual(
                result["stage_implication"],
                "cannot_split_ARCO_IIIA_IIIB_without_scale",
            )

    def test_limits_collapse_measurement_to_acetabular_superolateral_weight_bearing_region(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "xray.png"
            mask_path = Path(tmpdir) / "femoral_head_mask.png"
            Image.new("L", (160, 160), 80).save(image_path)
            write_circle_mask_with_asymmetric_superior_notches(mask_path)

            result = ONFHCollapseMeasurementTool().measure(
                image_path=image_path,
                femoral_head_mask_path=mask_path,
                image_side="image_left_femoral_head",
            )

            self.assertTrue(result["measurement_usable"])
            self.assertEqual(
                result["reference_fit"]["measurement_sector"],
                "acetabular_covered_superolateral_weight_bearing",
            )
            self.assertIn("concentric_circle", result["reference_fit"]["model"])
            self.assertEqual(result["reference_fit"]["allowed_angle_degrees"], [245.0, 295.0])
            self.assertLess(result["depression_point"][0], result["reference_fit"]["center"][0])
            self.assertGreater(result["depression_point"][0], result["reference_fit"]["center"][0] - 35.0)
            self.assertLess(result["maximum_depression_px"], 14.0)

    def test_uses_manual_ruler_calibration_to_report_mm_and_arco_iiib(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "xray.png"
            mask_path = Path(tmpdir) / "femoral_head_mask.png"
            Image.new("L", (140, 140), 80).save(image_path)
            write_circle_mask_with_superior_notch(mask_path, notch_depth_px=8)

            result = ONFHCollapseMeasurementTool().measure(
                image_path=image_path,
                femoral_head_mask_path=mask_path,
                calibration=ImageRulerCalibration(
                    pixel_length=40.0,
                    real_length_mm=100.0,
                    source="manual_image_ruler_10cm",
                ),
            )

            self.assertAlmostEqual(result["calibration"]["mm_per_pixel"], 2.5)
            self.assertGreater(result["maximum_depression_mm"], 2.0)
            self.assertEqual(result["stage_implication"], "compatible_with_ARCO_IIIB")

    def test_uses_ruler_points_for_calibration_and_can_report_arco_iiia(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "xray.png"
            mask_path = Path(tmpdir) / "femoral_head_mask.png"
            Image.new("L", (140, 140), 80).save(image_path)
            write_circle_mask_with_superior_notch(mask_path, notch_depth_px=8)

            result = ONFHCollapseMeasurementTool().measure(
                image_path=image_path,
                femoral_head_mask_path=mask_path,
                calibration=ImageRulerCalibration.from_points(
                    point_a=(10, 10),
                    point_b=(10, 1010),
                    real_length_mm=100.0,
                    source="manual_image_ruler_10cm",
                ),
            )

            self.assertAlmostEqual(result["calibration"]["ruler_pixel_length"], 1000.0)
            self.assertLessEqual(result["maximum_depression_mm"], 2.0)
            self.assertEqual(result["stage_implication"], "compatible_with_ARCO_IIIA")

    def test_rejects_empty_or_tiny_masks_as_not_usable(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "xray.png"
            mask_path = Path(tmpdir) / "mask.png"
            Image.new("L", (20, 20), 80).save(image_path)
            Image.new("L", (20, 20), 0).save(mask_path)

            result = ONFHCollapseMeasurementTool().measure(
                image_path=image_path,
                femoral_head_mask_path=mask_path,
            )

            self.assertFalse(result["measurement_usable"])
            self.assertEqual(result["quality"]["roi_qc"], "fail")
            self.assertIsNone(result["maximum_depression_px"])

    def test_demo_builds_auto_right_ruler_calibration(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "xray_with_ruler.png"
            image = Image.new("RGB", (220, 180), (35, 35, 35))
            pixels = image.load()
            for y in range(40, 141):
                pixels[205, y] = (80, 210, 255)
            image.save(image_path)

            calibration, report = build_calibration(
                image_path=image_path,
                ruler_pixel_length=None,
                ruler_points=None,
                ruler_real_length_mm=100.0,
                auto_right_ruler=True,
            )

            self.assertIsNotNone(calibration)
            self.assertTrue(report["ruler_detected"])
            self.assertEqual(calibration.source, "image_right_ruler_approx")


if __name__ == "__main__":
    unittest.main()
