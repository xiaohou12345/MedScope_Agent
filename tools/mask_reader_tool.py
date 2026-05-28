from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class MaskData:
    path: Path
    width: int
    height: int
    label_counts: dict[int, int]
    depth: int = 1
    voxel_volume_ml: float | None = None


class MaskReaderTool:
    """Reads simple 2D label masks for the BraTS Phase A flow."""

    def read(self, mask_path: Path | str) -> MaskData:
        path = Path(mask_path)
        with Image.open(path) as raw_image:
            image = raw_image.convert("L")
            label_counts: dict[int, int] = {}
            pixel_values = (
                image.get_flattened_data()
                if hasattr(image, "get_flattened_data")
                else image.getdata()
            )
            for value in list(pixel_values):
                if value == 0:
                    continue
                label_counts[value] = label_counts.get(value, 0) + 1
            return MaskData(
                path=path,
                width=image.width,
                height=image.height,
                label_counts=label_counts,
            )
