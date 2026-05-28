import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.ipf_visual_demo import run_ipf_visual_demo


class IPFVisualDemoTest(unittest.TestCase):
    def test_demo_returns_pending_download_when_default_manifest_has_no_cases(self):
        with TemporaryDirectory() as tmpdir:
            payload = json.loads(run_ipf_visual_demo(output_dir=Path(tmpdir)))

        self.assertEqual(payload["status"], "pending_download")
        self.assertEqual(payload["disease_key"], "idiopathic_pulmonary_fibrosis_hrct")
        self.assertIn("Download OSIC CT data", payload["action_items"][0])
        self.assertIsNone(payload.get("evidence_bundle_path"))

    def test_demo_builds_evidence_bundle_skeleton_for_local_ct_case_without_fibrosis_mask(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_dir = root / "patient001"
            case_dir.mkdir()
            (case_dir / "slice001.dcm").write_bytes(b"fake dicom")
            lung_mask = root / "patient001_lung_mask.nrrd"
            lung_mask.write_text("fake lung mask", encoding="utf-8")
            manifest_path = root / "osic_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "dataset": "OSIC Pulmonary Fibrosis Progression",
                        "disease_key": "idiopathic_pulmonary_fibrosis_hrct",
                        "disease_name": "特发性肺纤维化 HRCT 评估",
                        "access": {"requires_kaggle_login": True},
                        "cases": [
                            {
                                "case_id": "patient001",
                                "ct_path": "patient001",
                                "lung_mask_path": "patient001_lung_mask.nrrd",
                                "disease_name": "特发性肺纤维化 HRCT 评估",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = json.loads(
                run_ipf_visual_demo(
                    manifest_path=manifest_path,
                    case_id="patient001",
                    output_dir=root / "output",
                )
            )
            bundle = json.loads(Path(payload["evidence_bundle_path"]).read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["case_id"], "patient001")
        self.assertEqual(payload["alignment_plan"]["analysis_status"], "evidence_sufficient")
        self.assertEqual(payload["alignment_plan"]["image_context"]["modality"], "CT")
        self.assertIn("HRCT", payload["alignment_plan"]["image_context"]["available_sequences"])
        self.assertEqual(bundle["schema_version"], "ipf_visual_evidence_bundle.v1")
        self.assertEqual(bundle["disease_target"], "idiopathic_pulmonary_fibrosis_hrct")
        self.assertEqual(bundle["present_findings"], [])
        self.assertEqual(bundle["anatomy_evidence"]["lung_mask_status"], "available_anatomy_only")
        self.assertEqual(bundle["data_boundary"]["lung_mask_role"], "anatomy_mask_not_fibrosis_ground_truth")
        self.assertEqual(bundle["completeness"]["fibrosis_candidate"]["status"], "unassessed")
        self.assertIn("not fibrosis lesion labels", bundle["quality_warnings"][0])

    def test_demo_rejects_invalid_manifest_before_visual_evidence(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest_path = root / "invalid_osic_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "dataset": "OSIC Pulmonary Fibrosis Progression",
                        "disease_key": "idiopathic_pulmonary_fibrosis_hrct",
                        "cases": [{"case_id": "missing", "ct_path": "missing_ct"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = json.loads(
                run_ipf_visual_demo(
                    manifest_path=manifest_path,
                    output_dir=root / "output",
                )
            )

        self.assertEqual(payload["status"], "invalid_manifest")
        self.assertEqual(payload["manifest_validation"]["invalid_case_ids"], ["missing"])
        self.assertIsNone(payload.get("evidence_bundle_path"))


if __name__ == "__main__":
    unittest.main()
