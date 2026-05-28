from __future__ import annotations

from pathlib import Path

from PIL import Image


class OverlayGenerationTool:
    """Generates a simple colored PNG overlay from a grayscale image and label mask."""

    COLORS = {
        1: (255, 0, 0, 120),
        2: (0, 255, 0, 100),
        4: (0, 0, 255, 140),
    }

    def generate_overlay(
        self,
        image_path: Path | str,
        mask_path: Path | str,
        overlay_path: Path | str,
    ) -> Path:
        image = Image.open(image_path).convert("RGBA")
        mask = Image.open(mask_path).convert("L")
        if image.size != mask.size:
            raise ValueError("image and mask must have the same size")

        color_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        color_pixels = color_layer.load()
        mask_pixels = mask.load()
        for y in range(mask.height):
            for x in range(mask.width):
                label = mask_pixels[x, y]
                if label in self.COLORS:
                    color_pixels[x, y] = self.COLORS[label]

        overlay = Image.alpha_composite(image, color_layer)
        output_path = Path(overlay_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        overlay.save(output_path)
        return output_path
