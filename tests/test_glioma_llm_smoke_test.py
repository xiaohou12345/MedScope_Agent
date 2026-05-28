import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from llm.model_client import ChatResponse, RecordingModelClient
from scripts.glioma_llm_smoke_test import run_glioma_llm_manifest, run_glioma_llm_smoke


REAL_SAMPLE_DIR = Path("data/external/brats2021_00030")
REAL_IMAGE = REAL_SAMPLE_DIR / "BraTS2021_00030_flair.nii.gz"
REAL_MASK = REAL_SAMPLE_DIR / "BraTS2021_00030_seg.nii.gz"


class GliomaLlmSmokeTest(unittest.TestCase):
    def test_dry_run_reports_route_and_does_not_call_real_model(self):
        with TemporaryDirectory() as tmpdir:
            output = run_glioma_llm_smoke(
                image_path=Path(tmpdir) / "case_flair.nii.gz",
                mask_path=Path(tmpdir) / "case_seg.nii.gz",
                output_dir=Path(tmpdir) / "output",
                real=False,
            )

            payload = json.loads(output)
            self.assertEqual(payload["status"], "dry_run")
            self.assertFalse(payload["real_call_attempted"])
            self.assertEqual(payload["active_route"], "dmx")
            self.assertEqual(payload["api_key_env"], "DMX_API_KEY")

    def test_real_run_reports_missing_api_key_without_calling_network(self):
        with TemporaryDirectory() as tmpdir, patch.dict("os.environ", {}, clear=True):
            output = run_glioma_llm_smoke(
                image_path=Path(tmpdir) / "case_flair.nii.gz",
                mask_path=Path(tmpdir) / "case_seg.nii.gz",
                output_dir=Path(tmpdir) / "output",
                real=True,
            )

            payload = json.loads(output)
            self.assertEqual(payload["status"], "not_ready")
            self.assertFalse(payload["real_call_attempted"])
            self.assertEqual(payload["error"], "Missing DMX_API_KEY")

    def test_manifest_dry_run_summary_does_not_count_cases_as_failed(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "case_dry",
                                "image_path": "missing_flair.nii.gz",
                                "mask_path": "missing_seg.nii.gz",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = run_glioma_llm_manifest(
                manifest_path=manifest_path,
                output_dir=workdir / "batch",
                real=False,
            )

            payload = json.loads(output)
            self.assertEqual(payload["status"], "dry_run")
            self.assertEqual(payload["ok_count"], 0)
            self.assertEqual(payload["failed_case_ids"], [])
            self.assertEqual(payload["cases"][0]["status"], "dry_run")

    def test_manifest_min_cases_gate_stops_before_model_call(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "不应调用",
                        "影像依据": [],
                        "分期判断": "不应调用",
                        "不确定性说明": [],
                        "建议进一步检查": [],
                        "治疗建议": [],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "case_only",
                                "image_path": "missing_flair.nii.gz",
                                "mask_path": "missing_seg.nii.gz",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = run_glioma_llm_manifest(
                manifest_path=manifest_path,
                output_dir=workdir / "batch",
                real=True,
                model_client=model_client,
                min_cases=2,
            )

            payload = json.loads(output)
            self.assertEqual(payload["status"], "insufficient_cases")
            self.assertEqual(payload["case_count"], 1)
            self.assertEqual(payload["ok_count"], 0)
            self.assertEqual(payload["fallback_count"], 0)
            self.assertEqual(payload["cases"], [])
            self.assertEqual(payload["failed_case_ids"], [])
            self.assertEqual(payload["quality_gate"]["min_cases"], 2)
            self.assertFalse(payload["quality_gate"]["passed"])
            self.assertEqual(model_client.calls, [])

    @unittest.skipUnless(
        REAL_IMAGE.exists() and REAL_MASK.exists(),
        "real BraTS2021 sample files are not downloaded",
    )
    def test_fake_model_run_writes_glioma_llm_report_without_losing_completeness(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 成人弥漫性胶质瘤影像疑似",
                        "影像依据": ["whole tumor 体积已评估"],
                        "分期判断": "影像不能替代病理和分子诊断",
                        "不确定性说明": ["缺少 T1ce，enhancing_tumor 不能评估"],
                        "建议进一步检查": ["补充 T1ce"],
                        "治疗建议": ["神经肿瘤 MDT 评估"],
                        "used_visual_fields": ["whole_tumor", "edema"],
                        "missing_visual_fields_acknowledged": [
                            "tumor_core",
                            "enhancing_tumor",
                            "mass_effect",
                        ],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        with TemporaryDirectory() as tmpdir:
            output = run_glioma_llm_smoke(
                image_path=REAL_IMAGE,
                mask_path=REAL_MASK,
                output_dir=Path(tmpdir) / "output",
                real=True,
                model_client=model_client,
            )

            payload = json.loads(output)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(payload["real_call_attempted"])
            self.assertTrue(Path(payload["result_json_path"]).exists())
            self.assertIn("llm_raw_content", payload)
            self.assertIn("used_visual_fields", payload["llm_raw_content"])
            self.assertEqual(payload["report"]["diagnostic_tendency"], "LLM 成人弥漫性胶质瘤影像疑似")
            self.assertEqual(
                payload["case_memory"]["image_memory"]["visual_features"]["completeness"][
                    "enhancing_tumor"
                ]["status"],
                "missing",
            )
            self.assertEqual(model_client.calls[0]["task"], "diagnosis_report_generation")

    @unittest.skipUnless(
        REAL_IMAGE.exists() and REAL_MASK.exists(),
        "real BraTS2021 sample files are not downloaded",
    )
    def test_manifest_batch_writes_summary_for_glioma_llm_smoke(self):
        model_client = RecordingModelClient(
            response=ChatResponse(
                content=json.dumps(
                    {
                        "诊断倾向": "LLM 成人弥漫性胶质瘤影像疑似",
                        "影像依据": ["whole tumor 体积已评估"],
                        "分期判断": "影像不能替代病理和分子诊断",
                        "不确定性说明": ["缺少 T1ce，enhancing_tumor 不能评估"],
                        "建议进一步检查": ["补充 T1ce"],
                        "治疗建议": ["神经肿瘤 MDT 评估"],
                        "used_visual_fields": ["whole_tumor", "edema"],
                        "missing_visual_fields_acknowledged": [
                            "tumor_core",
                            "enhancing_tumor",
                            "mass_effect",
                        ],
                    },
                    ensure_ascii=False,
                ),
                model="fake",
                route="test",
            )
        )
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            manifest_path = workdir / "brats_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "brats2021_00030",
                                "image_path": str(REAL_IMAGE),
                                "mask_path": str(REAL_MASK),
                                "disease_name": "成人弥漫性胶质瘤",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = run_glioma_llm_manifest(
                manifest_path=manifest_path,
                output_dir=workdir / "batch",
                real=True,
                model_client=model_client,
            )

            payload = json.loads(output)
            summary_path = Path(payload["summary_path"])
            markdown_summary_path = Path(payload["summary_markdown_path"])
            case = payload["cases"][0]
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["case_count"], 1)
            self.assertEqual(payload["ok_count"], 1)
            self.assertEqual(payload["fallback_count"], 0)
            self.assertTrue(summary_path.exists())
            self.assertTrue(markdown_summary_path.exists())
            self.assertEqual(case["case_id"], "brats2021_00030")
            self.assertFalse(case["llm_fallback"])
            self.assertEqual(case["used_visual_fields"], ["whole_tumor", "edema"])
            self.assertEqual(
                case["missing_visual_fields_acknowledged"],
                ["tumor_core", "enhancing_tumor", "mass_effect"],
            )
            markdown = markdown_summary_path.read_text(encoding="utf-8")
            self.assertIn("brats2021_00030", markdown)
            self.assertIn("fallback", markdown)


if __name__ == "__main__":
    unittest.main()
