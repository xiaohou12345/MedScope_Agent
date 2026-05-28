import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.osic_ipf_dataset import (
    DEFAULT_OSIC_MANIFEST,
    check_osic_download_readiness,
    validate_osic_manifest,
)


class OSICIPFDatasetTest(unittest.TestCase):
    def test_default_manifest_documents_sources_and_pending_download(self):
        payload = json.loads(validate_osic_manifest(DEFAULT_OSIC_MANIFEST))

        self.assertEqual(payload["dataset"], "OSIC Pulmonary Fibrosis Progression")
        self.assertEqual(payload["disease_key"], "idiopathic_pulmonary_fibrosis_hrct")
        self.assertEqual(payload["status"], "pending_download")
        self.assertEqual(payload["case_count"], 0)
        self.assertTrue(payload["access"]["requires_kaggle_login"])
        self.assertIn("osic-pulmonary-fibrosis-progression", payload["access"]["competition_url"])
        self.assertEqual(
            payload["data_boundary"]["lung_mask_role"],
            "anatomy_mask_not_fibrosis_ground_truth",
        )

    def test_manifest_validation_accepts_existing_ct_case_and_lung_mask(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_dir = root / "patient001"
            case_dir.mkdir()
            (case_dir / "slice001.dcm").write_bytes(b"fake dicom bytes")
            lung_mask_path = root / "patient001_lung_mask.nrrd"
            lung_mask_path.write_text("fake mask", encoding="utf-8")
            metadata_path = root / "train.csv"
            metadata_path.write_text("Patient,Weeks,FVC\npatient001,0,2500\n", encoding="utf-8")
            manifest_path = root / "osic_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "dataset": "OSIC Pulmonary Fibrosis Progression",
                        "disease_key": "idiopathic_pulmonary_fibrosis_hrct",
                        "access": {"requires_kaggle_login": True},
                        "cases": [
                            {
                                "case_id": "patient001",
                                "ct_path": "patient001",
                                "lung_mask_path": "patient001_lung_mask.nrrd",
                                "metadata_path": "train.csv",
                                "disease_name": "特发性肺纤维化 HRCT 评估",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = json.loads(validate_osic_manifest(manifest_path))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["valid_count"], 1)
        case = payload["cases"][0]
        self.assertEqual(case["status"], "ok")
        self.assertEqual(case["resolved_paths"]["ct_path"], str(case_dir))
        self.assertEqual(case["resolved_paths"]["lung_mask_path"], str(lung_mask_path))
        self.assertEqual(case["resolved_paths"]["metadata_path"], str(metadata_path))
        self.assertIsNone(case["resolved_paths"]["fibrosis_mask_path"])
        self.assertEqual(case["label_boundary"]["fibrosis_mask_status"], "not_available")

    def test_manifest_validation_reports_missing_ct_before_visual_demo(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest_path = root / "osic_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "dataset": "OSIC Pulmonary Fibrosis Progression",
                        "disease_key": "idiopathic_pulmonary_fibrosis_hrct",
                        "cases": [
                            {
                                "case_id": "missing_case",
                                "ct_path": "missing_ct_dir",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = json.loads(validate_osic_manifest(manifest_path))

        self.assertEqual(payload["status"], "invalid")
        self.assertEqual(payload["invalid_case_ids"], ["missing_case"])
        self.assertIn("ct_path not found", payload["cases"][0]["errors"][0])

    def test_download_readiness_reports_kaggle_auth_requirement_without_downloading(self):
        with TemporaryDirectory() as tmpdir:
            missing_config = Path(tmpdir) / "missing_kaggle.json"

            payload = json.loads(
                check_osic_download_readiness(
                    manifest_path=DEFAULT_OSIC_MANIFEST,
                    kaggle_config_path=missing_config,
                )
            )

        self.assertEqual(payload["status"], "needs_auth")
        self.assertFalse(payload["kaggle_config_present"])
        self.assertIn("kaggle.json", payload["action_items"][0])


if __name__ == "__main__":
    unittest.main()
