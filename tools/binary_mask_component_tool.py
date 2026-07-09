from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class BinaryMaskComponent:
    component_id: str
    points: frozenset[tuple[int, int]]
    area_px: int
    bbox: list[int]
    centroid: list[float]


class BinaryMaskComponentTool:
    """Splits a binary mask into connected components.

    The ONFH mask pipeline uses this to separate left/right femoral heads or
    extra predicted instances before geometric measurement.
    """

    def components(
        self,
        *,
        mask_path: Path | str,
        min_area_px: int = 1,
    ) -> list[BinaryMaskComponent]:
        with Image.open(mask_path) as raw_mask:
            mask = raw_mask.convert("L")
            width, height = mask.size
            pixels = mask.load()
            foreground = {
                (x, y)
                for y in range(height)
                for x in range(width)
                if pixels[x, y] != 0
            }

        remaining = set(foreground)
        components: list[BinaryMaskComponent] = []
        while remaining:
            seed = remaining.pop()
            queue: deque[tuple[int, int]] = deque([seed])
            points = [seed]
            while queue:
                x, y = queue.popleft()
                for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if neighbor not in remaining:
                        continue
                    remaining.remove(neighbor)
                    queue.append(neighbor)
                    points.append(neighbor)
            if len(points) < min_area_px:
                continue
            components.append(self._component(points))

        components.sort(key=lambda item: (-item.area_px, item.bbox))
        return [
            BinaryMaskComponent(
                component_id=f"component_{index}",
                points=component.points,
                area_px=component.area_px,
                bbox=component.bbox,
                centroid=component.centroid,
            )
            for index, component in enumerate(components, start=1)
        ]

    def write_component_mask(
        self,
        *,
        component: BinaryMaskComponent,
        size: tuple[int, int],
        output_path: Path | str,
    ) -> None:
        output = Image.new("L", size, 0)
        pixels = output.load()
        for x, y in component.points:
            pixels[x, y] = 255
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_path)

    def _component(self, points: list[tuple[int, int]]) -> BinaryMaskComponent:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        area = len(points)
        return BinaryMaskComponent(
            component_id="component_pending",
            points=frozenset(points),
            area_px=area,
            bbox=[min(xs), min(ys), max(xs) + 1, max(ys) + 1],
            centroid=[round(sum(xs) / area, 3), round(sum(ys) / area, 3)],
        )
