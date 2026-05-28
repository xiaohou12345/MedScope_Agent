import unittest
from unittest.mock import patch

from tools.feature_extraction_tool import FeatureExtractionTool
from tools.nifti_mask_reader_tool import (
    MissingNiftiDependencyError,
    NibabelLoader,
    NiftiMaskReaderTool,
)


class FakeNiftiImage:
    def __init__(self, data, zooms):
        self._data = data
        self.header = self
        self._zooms = zooms

    def get_fdata(self):
        return self._data

    def get_zooms(self):
        return self._zooms


class FakeNiftiLoader:
    def __init__(self, image):
        self.image = image
        self.loaded_paths = []

    def load(self, path):
        self.loaded_paths.append(path)
        return self.image


class NiftiMaskReaderTest(unittest.TestCase):
    def test_nifti_reader_counts_3d_labels_and_voxel_volume(self):
        volume = [
            [[0, 1], [2, 4]],
            [[2, 2], [0, 4]],
        ]
        loader = FakeNiftiLoader(FakeNiftiImage(volume, zooms=(2.0, 2.0, 5.0)))

        mask_data = NiftiMaskReaderTool(nifti_loader=loader).read("case_seg.nii.gz")

        self.assertEqual(mask_data.width, 2)
        self.assertEqual(mask_data.height, 2)
        self.assertEqual(mask_data.depth, 2)
        self.assertEqual(mask_data.label_counts[1], 1)
        self.assertEqual(mask_data.label_counts[2], 3)
        self.assertEqual(mask_data.label_counts[4], 2)
        self.assertEqual(mask_data.voxel_volume_ml, 0.02)
        self.assertEqual(loader.loaded_paths, ["case_seg.nii.gz"])

    def test_feature_extraction_uses_mask_voxel_volume_when_available(self):
        volume = [[[1, 2, 4]]]
        loader = FakeNiftiLoader(FakeNiftiImage(volume, zooms=(1.0, 1.0, 10.0)))
        mask_data = NiftiMaskReaderTool(nifti_loader=loader).read("case_seg.nii.gz")

        features = FeatureExtractionTool().extract_brats_features(mask_data)

        self.assertEqual(features["whole_tumor_volume_ml"], 0.03)
        self.assertEqual(features["tumor_core_volume_ml"], 0.02)
        self.assertEqual(features["enhancing_tumor_volume_ml"], 0.01)

    def test_nifti_reader_has_clear_error_when_nibabel_missing(self):
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "nibabel":
                raise ImportError("nibabel intentionally unavailable")
            return real_import(name, *args, **kwargs)

        with self.assertRaises(MissingNiftiDependencyError):
            with patch("builtins.__import__", side_effect=fake_import):
                NibabelLoader()


if __name__ == "__main__":
    unittest.main()
