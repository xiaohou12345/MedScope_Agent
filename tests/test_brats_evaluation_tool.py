from __future__ import annotations

import unittest

import numpy as np

from tools.brats_evaluation_tool import BratsEvaluationTool


class FakeNiftiImage:
    def __init__(self, data, zooms=(1.0, 1.0, 2.0)) -> None:
        self._data = data
        self.header = self
        self._zooms = zooms

    def get_fdata(self):
        return self._data

    def get_zooms(self):
        return self._zooms


class PathNiftiLoader:
    def __init__(self, images) -> None:
        self.images = images

    def load(self, path):
        return self.images[str(path)]


class BratsEvaluationToolTest(unittest.TestCase):
    def test_evaluate_reports_iou_volume_error_and_component_counts(self) -> None:
        prediction = np.zeros((1, 4, 4), dtype=int)
        reference = np.zeros((1, 4, 4), dtype=int)
        prediction[0, 0, 0] = 1
        prediction[0, 0, 1] = 1
        prediction[0, 1, 1] = 1
        prediction[0, 3, 3] = 1
        reference[0, 0, 0] = 1
        reference[0, 0, 1] = 1
        reference[0, 2, 2] = 1
        loader = PathNiftiLoader(
            {
                "prediction.nii.gz": FakeNiftiImage(prediction),
                "reference.nii.gz": FakeNiftiImage(reference),
            }
        )

        metrics = BratsEvaluationTool(nifti_loader=loader).evaluate(
            "prediction.nii.gz",
            "reference.nii.gz",
        )

        self.assertAlmostEqual(metrics["whole_tumor_dice"], 4 / 7)
        self.assertAlmostEqual(metrics["whole_tumor_iou"], 0.4)
        self.assertEqual(metrics["whole_tumor_prediction_voxels"], 4)
        self.assertEqual(metrics["whole_tumor_reference_voxels"], 3)
        self.assertEqual(metrics["whole_tumor_prediction_volume_ml"], 0.008)
        self.assertEqual(metrics["whole_tumor_reference_volume_ml"], 0.006)
        self.assertEqual(metrics["whole_tumor_absolute_volume_error_ml"], 0.002)
        self.assertAlmostEqual(metrics["whole_tumor_relative_volume_error"], 1 / 3)
        self.assertEqual(metrics["whole_tumor_prediction_component_count"], 2)
        self.assertEqual(metrics["whole_tumor_reference_component_count"], 2)
        self.assertEqual(metrics["whole_tumor_false_positive_component_count"], 1)
        self.assertEqual(metrics["whole_tumor_false_negative_component_count"], 1)


if __name__ == "__main__":
    unittest.main()
