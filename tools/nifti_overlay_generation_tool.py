from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from tools.nifti_mask_reader_tool import NibabelLoader


class NiftiOverlayGenerationTool:
    """Creates a PNG overlay from a 3D/4D NIfTI image and a 3D NIfTI mask."""

    COLORS = {
        1: (255, 0, 0, 120),
        2: (0, 255, 0, 100),
        4: (0, 0, 255, 140),
    }

    def __init__(self, nifti_loader: Any | None = None) -> None:
        self.nifti_loader = nifti_loader or NibabelLoader()

    def generate_overlay(
        self,
        image_path: Path | str,
        mask_path: Path | str,
        overlay_path: Path | str,
    ) -> Path:
        image_volume = self.nifti_loader.load(image_path).get_fdata()
        mask_volume = self.nifti_loader.load(mask_path).get_fdata()
        slice_index = self._largest_mask_slice(mask_volume)
        image_slice = self._slice_2d(image_volume, slice_index)
        mask_slice = self._slice_2d(mask_volume, slice_index)

        base_image = self._grayscale_rgba(image_slice)
        color_layer = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
        color_pixels = color_layer.load()
        for y, row in enumerate(mask_slice):
            for x, raw_label in enumerate(row):
                label = int(raw_label)
                if label in self.COLORS:
                    color_pixels[x, y] = self.COLORS[label]

        overlay = Image.alpha_composite(base_image, color_layer)
        output_path = Path(overlay_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        overlay.save(output_path)
        return output_path

    def _largest_mask_slice(self, mask_volume: Any) -> int:
        shape = mask_volume.shape
        best_index = 0
        best_count = -1
        for z in range(shape[2]):
            mask_slice = mask_volume[:, :, z]
            count = int((mask_slice > 0).sum())
            if count > best_count:
                best_index = z
                best_count = count
        return best_index

    def _slice_2d(self, volume: Any, slice_index: int) -> list[list[float]]:
        if len(volume.shape) == 4:
            slice_data = volume[:, :, slice_index, 0]
        else:
            slice_data = volume[:, :, slice_index]
        return slice_data.tolist()

    def _grayscale_rgba(self, image_slice: list[list[float]]) -> Image.Image:
        flat = [value for row in image_slice for value in row]
        low = min(flat)
        high = max(flat)
        scale = 255.0 / (high - low) if high > low else 1.0
        height = len(image_slice)
        width = len(image_slice[0]) if height else 0
        image = Image.new("L", (width, height), 0)
        pixels = image.load()
        for y, row in enumerate(image_slice):
            for x, value in enumerate(row):
                pixels[x, y] = int(max(0, min(255, (value - low) * scale)))
        return image.convert("RGBA")
