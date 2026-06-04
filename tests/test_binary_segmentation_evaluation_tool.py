import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from tools.binary_segmentation_evaluation_tool import BinarySegmentationEvaluationTool


class BinarySegmentationEvaluationToolTest(unittest.TestCase):
    def test_evaluate_reports_binary_lesion_dice_iou_and_pixel_counts(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            prediction_path = tmp / "prediction.png"
            reference_path = tmp / "reference.png"
            prediction = Image.new("L", (4, 4), 0)
            reference = Image.new("L", (4, 4), 0)
            for point in [(0, 0), (1, 0), (1, 1), (3, 3)]:
                prediction.putpixel(point, 255)
            for point in [(0, 0), (1, 0), (2, 2)]:
                reference.putpixel(point, 255)
            prediction.save(prediction_path)
            reference.save(reference_path)

            metrics = BinarySegmentationEvaluationTool().evaluate(
                prediction_mask_path=prediction_path,
                reference_mask_path=reference_path,
            )

            self.assertAlmostEqual(metrics["lesion_dice"], 4 / 7)
            self.assertAlmostEqual(metrics["lesion_iou"], 0.4)
            self.assertEqual(metrics["lesion_prediction_pixels"], 4)
            self.assertEqual(metrics["lesion_reference_pixels"], 3)
            self.assertEqual(metrics["lesion_intersection_pixels"], 2)
            self.assertEqual(metrics["lesion_union_pixels"], 5)
            self.assertEqual(metrics["lesion_false_positive_pixels"], 2)
            self.assertEqual(metrics["lesion_false_negative_pixels"], 1)

    def test_evaluate_rejects_shape_mismatch_without_resizing_masks(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            prediction_path = tmp / "prediction.png"
            reference_path = tmp / "reference.png"
            Image.new("L", (4, 4), 255).save(prediction_path)
            Image.new("L", (5, 4), 255).save(reference_path)

            with self.assertRaisesRegex(ValueError, "shapes do not match"):
                BinarySegmentationEvaluationTool().evaluate(
                    prediction_mask_path=prediction_path,
                    reference_mask_path=reference_path,
                )


if __name__ == "__main__":
    unittest.main()
