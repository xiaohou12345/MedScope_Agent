import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

from tools.xray_ruler_calibration_tool import XRayRulerCalibrationTool


class XRayRulerCalibrationToolTest(unittest.TestCase):
    def test_detects_right_side_blue_10cm_ruler(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "xray_with_ruler.png"
            image = Image.new("RGB", (220, 180), (35, 35, 35))
            draw = ImageDraw.Draw(image)
            draw.line((205, 40, 205, 140), fill=(80, 210, 255), width=2)
            for y in range(40, 141, 10):
                draw.line((198, y, 212, y), fill=(80, 210, 255), width=2)
            image.save(image_path)

            result = XRayRulerCalibrationTool().detect_right_ruler(
                image_path=image_path,
                real_length_mm=100.0,
            )

            self.assertTrue(result["ruler_detected"])
            self.assertEqual(result["calibration_source"], "image_right_ruler_approx")
            self.assertGreater(result["ruler_pixel_length"], 95)
            self.assertLess(result["ruler_pixel_length"], 105)
            self.assertAlmostEqual(result["calibration"].mm_per_pixel, 1.0, delta=0.06)

    def test_returns_not_detected_when_no_right_ruler_is_visible(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "xray_without_ruler.png"
            Image.new("RGB", (220, 180), (35, 35, 35)).save(image_path)

            result = XRayRulerCalibrationTool().detect_right_ruler(
                image_path=image_path,
                real_length_mm=100.0,
            )

            self.assertFalse(result["ruler_detected"])
            self.assertIsNone(result["calibration"])
            self.assertEqual(result["failure_reason"], "right_ruler_not_detected")


if __name__ == "__main__":
    unittest.main()
