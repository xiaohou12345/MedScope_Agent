import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from api.service import MedScopeService
from tests.test_service_entrypoint import FakeGaoDoctor

from scripts.prepare_public_demo_fixture import prepare_public_demo_fixture


class PublicDemoFixtureTest(unittest.TestCase):
    def test_fixture_generates_public_safe_image_and_service_payload(self):
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "fixture"

            result = prepare_public_demo_fixture(output_dir=output_dir)

            manifest_path = Path(result["manifest_path"])
            image_path = Path(result["image_path"])
            self.assertTrue(manifest_path.exists())
            self.assertTrue(image_path.exists())
            self.assertEqual(image_path.suffix, ".png")
            self.assertIn("public_safe", result["safety"])
            self.assertNotIn("data/external", str(image_path))
            self.assertNotIn("output/real", str(image_path))

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload = manifest["service_payload"]
            self.assertEqual(payload["image_path"], str(image_path))
            self.assertEqual(payload["disease_key"], "femoral_head_necrosis")
            self.assertEqual(payload["vision_mode"], "no_mask_skill")

            fake_doctor = FakeGaoDoctor()
            service = MedScopeService(gaodoctor_agent=fake_doctor)
            service_result = service.handle_request(payload)

            self.assertEqual(service_result["routing_decision"]["selected_skill"], "femoral_head_necrosis")
            self.assertEqual(service_result["routing_decision"]["selected_vision_mode"], "no_mask_skill")
            self.assertEqual(fake_doctor.calls[0]["image_path"], str(image_path))


if __name__ == "__main__":
    unittest.main()
