import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from tools.binary_mask_component_tool import BinaryMaskComponentTool


class BinaryMaskComponentToolTest(unittest.TestCase):
    def test_splits_binary_mask_into_filtered_components(self):
        with TemporaryDirectory() as tmpdir:
            mask_path = Path(tmpdir) / "mask.png"
            mask = Image.new("L", (60, 40), 0)
            pixels = mask.load()
            for y in range(8, 18):
                for x in range(5, 15):
                    pixels[x, y] = 255
            for y in range(10, 25):
                for x in range(35, 50):
                    pixels[x, y] = 255
            pixels[30, 2] = 255
            mask.save(mask_path)

            components = BinaryMaskComponentTool().components(
                mask_path=mask_path,
                min_area_px=20,
            )

            self.assertEqual(len(components), 2)
            self.assertEqual(components[0].area_px, 225)
            self.assertEqual(components[0].bbox, [35, 10, 50, 25])
            self.assertEqual(components[1].area_px, 100)
            self.assertEqual(components[1].bbox, [5, 8, 15, 18])

    def test_writes_single_component_mask(self):
        with TemporaryDirectory() as tmpdir:
            mask_path = Path(tmpdir) / "mask.png"
            output_path = Path(tmpdir) / "component.png"
            mask = Image.new("L", (20, 20), 0)
            pixels = mask.load()
            for y in range(5, 9):
                for x in range(6, 11):
                    pixels[x, y] = 255
            mask.save(mask_path)

            component = BinaryMaskComponentTool().components(mask_path=mask_path)[0]
            BinaryMaskComponentTool().write_component_mask(
                component=component,
                size=(20, 20),
                output_path=output_path,
            )

            written = Image.open(output_path).convert("L")
            self.assertEqual(sum(1 for value in written.getdata() if value), 20)


if __name__ == "__main__":
    unittest.main()
