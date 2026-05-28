import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from llm.model_client import ChatResponse, RecordingModelClient
from scripts.brats_real_vlm_medsam2_diagnosis_demo import (
    run_brats_real_vlm_medsam2_diagnosis_demo,
)


def _auto_eval_payload(status: str = "ok") -> dict:
    return {
        "status": status,
        "case_id": "brats2021_00030",
        "disease_key": "diffuse_glioma_brats",
        "prompt_source": "vision_model_bbox",
        "image_outputs": {
            "original_image_path": "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz",
            "mask_path": "output/fake/case_mask.nii.gz",
            "overlay_path": "output/fake/case_overlay.png",
        },
        "evaluation": {
            "whole_tumor_dice": 0.88,
            "tumor_core_dice": 0.44,
            "enhancing_tumor_dice": 0.0,
        },
        "result": {
            "image_path": "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz",
            "modality": "MRI",
            "body_part": "brain",
            "image_outputs": {
                "original_image_path": "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz",
                "mask_path": "output/fake/case_mask.nii.gz",
                "overlay_path": "output/fake/case_overlay.png",
            },
            "visual_evidence": {
                "collapse": False,
                "joint_space_narrowing": False,
                "segmentation_quality": "medsam2",
                "suspected_visual_findings": [
                    "medsam2 模型已生成肿瘤分割 mask",
                    "whole tumor 体积估计为 137.914 ml",
                ],
                "measurements": {
                    "whole_tumor_volume_ml": 137.914,
                    "tumor_core_volume_ml": None,
                    "enhancing_tumor_volume_ml": None,
                    "edema_present": False,
                    "mass_effect": None,
                },
                "completeness": {
                    "whole_tumor": {
                        "status": "supported",
                        "reason": "FLAIR modality available",
                    },
                    "tumor_core": {
                        "status": "missing",
                        "reason": "Requires T1, T1ce, T2 modalities",
                    },
                    "enhancing_tumor": {
                        "status": "missing",
                        "reason": "Requires T1ce modality",
                    },
                    "mass_effect": {
                        "status": "missing",
                        "reason": "Requires T1, T2 modalities",
                    },
                },
                "segmentation_results": [
                    {
                        "task_name": "segment_whole_tumor",
                        "target": "whole_tumor",
                        "status": "completed",
                        "mask_path": "output/fake/case_mask.nii.gz",
                        "overlay_path": "output/fake/case_overlay.png",
                        "measurements": {"whole_tumor_volume_ml": 137.914},
                        "quality": {"score": 0.7, "level": "medium", "warnings": []},
                        "completeness": {
                            "status": "supported",
                            "reason": "Segmentation passed QC",
                        },
                        "diagnosis_usable": True,
                    }
                ],
            },
        },
        "data_boundary": {
            "prompt_role": "non_reference_candidate_localization_required",
            "reference_mask_role": "evaluation_only",
            "model_mask_role": "automatic_candidate_segmentation",
        },
    }


class BratsRealVlmMedSAM2DiagnosisDemoTest(unittest.TestCase):
    def test_demo_generates_diagnosis_from_auto_eval_visual_result(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            auto_eval_path = root / "auto_eval.json"
            auto_eval_path.write_text(json.dumps(_auto_eval_payload()), encoding="utf-8")
            model_client = RecordingModelClient(
                ChatResponse(
                    content=json.dumps(
                        {
                            "诊断倾向": "影像提示胶质瘤相关异常，需结合完整 MRI 和病理分子结果",
                            "影像依据": ["FLAIR 上 whole tumor 分割体积约 137.914 ml"],
                            "分期判断": "当前仅可做影像证据描述，不能完成整合分型",
                            "不确定性说明": ["缺少 T1ce，不能判断强化肿瘤"],
                            "建议进一步检查": ["补充 T1/T1ce/T2 MRI 序列"],
                            "治疗建议": ["神经肿瘤专科复核"],
                            "used_visual_fields": ["whole_tumor"],
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

            payload = run_brats_real_vlm_medsam2_diagnosis_demo(
                auto_eval_result_path=auto_eval_path,
                output_dir=root / "diagnosis",
                model_client=model_client,
            )

            summary = json.loads((root / "diagnosis" / "summary.json").read_text())
            report = json.loads((root / "diagnosis" / "diagnosis_report.json").read_text())
            evidence_bundle = json.loads(
                (root / "diagnosis" / "evidence_bundle.json").read_text()
            )
            raw_content = json.loads((root / "diagnosis" / "llm_raw_content.json").read_text())

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["llm_attempted"])
        self.assertEqual(model_client.calls[0]["task"], "diagnosis_report_generation")
        self.assertEqual(summary["prompt_source"], "vision_model_bbox")
        self.assertEqual(report["diagnostic_tendency"], "影像提示胶质瘤相关异常，需结合完整 MRI 和病理分子结果")
        self.assertEqual(evidence_bundle["visual_result"]["visual_evidence"]["measurements"]["whole_tumor_volume_ml"], 137.914)
        self.assertIn("FLAIR 上 whole tumor", raw_content["content"])

    def test_demo_falls_back_to_rule_based_report_when_llm_route_fails(self):
        class FailingModelClient:
            def chat(self, messages, task):
                raise OSError("temporary diagnosis route failure")

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            auto_eval_path = root / "auto_eval.json"
            auto_eval_path.write_text(json.dumps(_auto_eval_payload()), encoding="utf-8")

            payload = run_brats_real_vlm_medsam2_diagnosis_demo(
                auto_eval_result_path=auto_eval_path,
                output_dir=root / "diagnosis",
                model_client=FailingModelClient(),
            )

            report = json.loads((root / "diagnosis" / "diagnosis_report.json").read_text())

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["llm_attempted"])
        self.assertIn("temporary diagnosis route failure", payload["llm_fallback_reason"])
        self.assertIn("成人弥漫性胶质瘤", report["diagnostic_tendency"])

    def test_demo_rejects_non_ok_auto_eval_result_before_diagnosis(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            auto_eval_path = root / "auto_eval.json"
            auto_eval_path.write_text(
                json.dumps(_auto_eval_payload(status="not_ready")),
                encoding="utf-8",
            )

            payload = run_brats_real_vlm_medsam2_diagnosis_demo(
                auto_eval_result_path=auto_eval_path,
                output_dir=root / "diagnosis",
            )

            summary = json.loads((root / "diagnosis" / "summary.json").read_text())

        self.assertEqual(payload["status"], "not_ready")
        self.assertFalse(payload["llm_attempted"])
        self.assertIn("auto_eval status is not ok", payload["error"])
        self.assertEqual(summary["status"], "not_ready")


if __name__ == "__main__":
    unittest.main()
