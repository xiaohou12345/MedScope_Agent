from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.mask_reader_tool import MaskData


class MissingNiftiDependencyError(RuntimeError):
    """Raised when nibabel is required but not installed."""


class NibabelLoader:
    def __init__(self) -> None:
        try:
            import nibabel as nib
        except ImportError as exc:
            raise MissingNiftiDependencyError(
                "nibabel is required to read BraTS .nii/.nii.gz masks. "
                "Install it before using real NIfTI data."
            ) from exc
        self._nib = nib

    def load(self, path: Path | str) -> Any:
        return self._nib.load(str(path))


class NiftiMaskReaderTool:
    """Reads BraTS-style 3D NIfTI segmentation masks when nibabel is available."""

    def __init__(self, nifti_loader: Any | None = None) -> None:
        self.nifti_loader = nifti_loader

    def read(self, mask_path: Path | str) -> MaskData:
        loader = self.nifti_loader or NibabelLoader()
        image = loader.load(mask_path)
        data = image.get_fdata()
        shape = self._shape_of(data)
        label_counts: dict[int, int] = {}
        for value in self._iter_values(data):
            label = int(value)
            if label == 0:
                continue
            label_counts[label] = label_counts.get(label, 0) + 1
        zooms = image.header.get_zooms()
        voxel_volume_ml = self._voxel_volume_ml(zooms)
        return MaskData(
            path=Path(mask_path),
            width=shape[0],
            height=shape[1],
            depth=shape[2],
            label_counts=label_counts,
            voxel_volume_ml=voxel_volume_ml,
        )

    def _shape_of(self, data: Any) -> tuple[int, int, int]:
        if hasattr(data, "shape"):
            shape = tuple(data.shape)
        else:
            shape = (
                len(data),
                len(data[0]) if data else 0,
                len(data[0][0]) if data and data[0] else 0,
            )
        if len(shape) < 3:
            return (shape[0], shape[1], 1)
        return (shape[0], shape[1], shape[2])

    def _iter_values(self, data: Any):
        if hasattr(data, "ravel"):
            yield from data.ravel()
            return
        for plane in data:
            for row in plane:
                for value in row:
                    yield value

    def _voxel_volume_ml(self, zooms: tuple[float, ...]) -> float:
        if len(zooms) < 3:
            return 0.001
        voxel_volume_mm3 = float(zooms[0]) * float(zooms[1]) * float(zooms[2])
        return voxel_volume_mm3 / 1000.0
