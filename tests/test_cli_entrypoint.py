import unittest

from app import run_cli_request


class FakeService:
    def __init__(self):
        self.payloads = []

    def handle_request(self, payload):
        self.payloads.append(payload)
        return {
            "case_id": "case_cli",
            "reply_to_patient": "ok",
        }


class CliEntrypointTest(unittest.TestCase):
    def test_cli_request_uses_service_entrypoint(self):
        service = FakeService()

        result = run_cli_request(
            service=service,
            image_path="data/images/demo_xray.png",
            message="左髋疼痛三个月",
            age=45,
            sex="male",
            symptoms=["髋关节疼痛"],
            risk_factors=["饮酒史"],
        )

        self.assertEqual(result["case_id"], "case_cli")
        self.assertEqual(service.payloads[0]["patient_message"], "左髋疼痛三个月")
        self.assertEqual(service.payloads[0]["image_path"], "data/images/demo_xray.png")
        self.assertEqual(service.payloads[0]["patient_info"]["risk_factors"], ["饮酒史"])

    def test_cli_request_can_pass_glioma_visual_options_to_service(self):
        service = FakeService()

        run_cli_request(
            service=service,
            image_path="data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz",
            message="请基于这次 FLAIR MRI 做胶质瘤辅助分析",
            age=58,
            sex="female",
            symptoms=["头痛"],
            risk_factors=[],
            disease_key="diffuse_glioma_brats",
            vision_mode="ground_truth",
            mask_path="data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz",
        )

        payload = service.payloads[0]
        self.assertEqual(payload["disease_key"], "diffuse_glioma_brats")
        self.assertEqual(payload["vision_mode"], "ground_truth")
        self.assertEqual(
            payload["mask_path"],
            "data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz",
        )


if __name__ == "__main__":
    unittest.main()
