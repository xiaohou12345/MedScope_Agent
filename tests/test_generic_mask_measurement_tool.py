import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from tools.generic_mask_measurement_tool import GenericMaskMeasurementTool


class GenericMaskMeasurementToolTest(unittest.TestCase):
    def test_measure_binary_mask_area_bbox_and_centroid(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "image.png"
            mask_path = Path(tmpdir) / "mask.png"
            Image.new("L", (10, 8), 20).save(image_path)
            mask = Image.new("L", (10, 8), 0)
            pixels = mask.load()
            for x in range(2, 5):
                for y in range(3, 7):
                    pixels[x, y] = 255
            mask.save(mask_path)

            measurements = GenericMaskMeasurementTool().measure(
                image_path=image_path,
                mask_path=mask_path,
            )

            self.assertEqual(measurements["lesion_area_px"], 12)
            self.assertEqual(measurements["image_area_px"], 80)
            self.assertEqual(measurements["lesion_bbox"], [2, 3, 5, 7])
            self.assertEqual(measurements["lesion_centroid"], [3.0, 4.5])
            self.assertEqual(measurements["lesion_area_ratio"], 0.15)
            self.assertEqual(measurements["lesion_bbox_size"], {"width": 3, "height": 4})
            self.assertEqual(measurements["lesion_fill_ratio"], 1.0)
            self.assertEqual(measurements["lesion_elongation"], 1.333)
            self.assertEqual(measurements["lesion_mean_intensity"], 20.0)

    def test_empty_mask_reports_zero_area_without_bbox(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "image.png"
            mask_path = Path(tmpdir) / "mask.png"
            Image.new("L", (10, 8), 20).save(image_path)
            Image.new("L", (10, 8), 0).save(mask_path)

            measurements = GenericMaskMeasurementTool().measure(
                image_path=image_path,
                mask_path=mask_path,
            )

            self.assertEqual(measurements["lesion_area_px"], 0)
            self.assertEqual(measurements["lesion_area_ratio"], 0.0)
            self.assertIsNone(measurements["lesion_bbox"])
            self.assertIsNone(measurements["lesion_centroid"])

    def test_measure_reports_multiple_connected_regions(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "image.png"
            mask_path = Path(tmpdir) / "mask.png"
            Image.new("L", (12, 10), 20).save(image_path)
            mask = Image.new("L", (12, 10), 0)
            pixels = mask.load()
            for x in range(1, 4):
                for y in range(1, 3):
                    pixels[x, y] = 255
            for x in range(8, 11):
                for y in range(6, 9):
                    pixels[x, y] = 255
            mask.save(mask_path)

            measurements = GenericMaskMeasurementTool().measure(
                image_path=image_path,
                mask_path=mask_path,
            )

            self.assertEqual(measurements["region_count"], 2)
            self.assertEqual(measurements["regions"][0]["area_px"], 9)
            self.assertEqual(measurements["regions"][0]["bbox"], [8, 6, 11, 9])
            self.assertEqual(measurements["regions"][1]["area_px"], 6)
            self.assertEqual(measurements["regions"][1]["bbox"], [1, 1, 4, 3])

    def test_measure_reports_lesion_ratio_inside_anatomy_mask(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "image.png"
            lesion_mask_path = Path(tmpdir) / "lesion_mask.png"
            anatomy_mask_path = Path(tmpdir) / "femoral_head_mask.png"
            Image.new("L", (10, 10), 20).save(image_path)

            anatomy = Image.new("L", (10, 10), 0)
            anatomy_pixels = anatomy.load()
            for x in range(2, 8):
                for y in range(2, 8):
                    anatomy_pixels[x, y] = 255
            anatomy.save(anatomy_mask_path)

            lesion = Image.new("L", (10, 10), 0)
            lesion_pixels = lesion.load()
            for x in range(4, 7):
                for y in range(4, 7):
                    lesion_pixels[x, y] = 255
            lesion.save(lesion_mask_path)

            measurements = GenericMaskMeasurementTool().measure(
                image_path=image_path,
                mask_path=lesion_mask_path,
                anatomy_mask_path=anatomy_mask_path,
                anatomy_name="femoral_head",
            )

            self.assertEqual(measurements["anatomy_name"], "femoral_head")
            self.assertEqual(measurements["anatomy_area_px"], 36)
            self.assertEqual(measurements["lesion_overlap_anatomy_px"], 9)
            self.assertEqual(measurements["lesion_area_ratio_in_anatomy"], 0.25)
            self.assertEqual(measurements["regions"][0]["area_ratio_in_anatomy"], 0.25)

    def test_measure_reports_partial_lesion_overlap_inside_anatomy_mask(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "image.png"
            lesion_mask_path = Path(tmpdir) / "lesion_mask.png"
            anatomy_mask_path = Path(tmpdir) / "femoral_head_mask.png"
            Image.new("L", (10, 10), 20).save(image_path)

            anatomy = Image.new("L", (10, 10), 0)
            anatomy_pixels = anatomy.load()
            for x in range(2, 6):
                for y in range(2, 6):
                    anatomy_pixels[x, y] = 255
            anatomy.save(anatomy_mask_path)

            lesion = Image.new("L", (10, 10), 0)
            lesion_pixels = lesion.load()
            for x in range(4, 8):
                for y in range(4, 8):
                    lesion_pixels[x, y] = 255
            lesion.save(lesion_mask_path)

            measurements = GenericMaskMeasurementTool().measure(
                image_path=image_path,
                mask_path=lesion_mask_path,
                anatomy_mask_path=anatomy_mask_path,
                anatomy_name="femoral_head",
            )

            self.assertEqual(measurements["lesion_area_px"], 16)
            self.assertEqual(measurements["anatomy_area_px"], 16)
            self.assertEqual(measurements["lesion_overlap_anatomy_px"], 4)
            self.assertEqual(measurements["lesion_area_ratio_in_anatomy"], 0.25)


if __name__ == "__main__":
    unittest.main()
