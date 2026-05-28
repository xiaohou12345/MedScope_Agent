import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.no_mask_candidate_diagnosis_demo import (
    build_candidate_visual_analysis_result,
    run_no_mask_candidate_diagnosis_demo,
)


class NoMaskCandidateDiagnosisDemoTest(unittest.TestCase):
    def test_demo_builds_hypothesis_report_from_medsam2_summary(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            segmentation_summary = workdir / "segmentation_summary.json"
            segmentation_summary.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "image_path": "output/fake/no_mask_vision_source_pneumonia_xray.jpg",
                        "mask_path": "output/fake/no_mask_medsam2_segmentation_demo/medsam2_mask.png",
                        "overlay_path": "output/fake/no_mask_medsam2_segmentation_demo/medsam2_overlay.png",
                        "measurements": {
                            "lesion_area_px": 9278,
                            "image_area_px": 214800,
                            "lesion_area_ratio": 0.043194,
                            "lesion_bbox": [10, 470, 156, 595],
                            "lesion_centroid": [79.17, 519.799],
                        },
                        "segmentation_result": {
                            "task_name": "segment_candidate_lesion",
                            "target": "candidate_lesion",
                            "status": "completed",
                            "mask_path": "output/fake/no_mask_medsam2_segmentation_demo/medsam2_mask.png",
                            "overlay_path": "output/fake/no_mask_medsam2_segmentation_demo/medsam2_overlay.png",
                            "measurements": {
                                "lesion_area_px": 9278,
                                "lesion_area_ratio": 0.043194,
                            },
                            "quality": {
                                "score": 0.6,
                                "level": "medium",
                                "warnings": [
                                    "candidate segmentation requires clinical/model QC"
                                ],
                            },
                            "completeness": {
                                "status": "supported",
                                "reason": "Candidate mask generated from vision-model box prompt",
                            },
                            "diagnosis_usable": True,
                            "selected_tool": {
                                "tool_name": "medsam2",
                                "role": "candidate_segmenter",
                                "segmentation_source": "medsam2",
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_no_mask_candidate_diagnosis_demo(
                segmentation_summary_path=segmentation_summary,
                output_dir=workdir / "out",
            )

            self.assertEqual(result["status"], "ok")
            report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
            self.assertTrue(report["诊断倾向"].startswith("科研假设风险提示"))
            self.assertEqual(
                report["used_skill"]["skill_type"],
                "data_mined_hypothesis",
            )
            self.assertEqual(report["hypothesis_validation_mode"], "enabled")
            visual_contract = report["visual_input_contract"]
            self.assertEqual(visual_contract["modality"], "xray")
            self.assertEqual(
                visual_contract["measurements"]["lesion_area_ratio"],
                0.043194,
            )
            self.assertEqual(
                visual_contract["segmentation_results"][0]["selected_tool"]["tool_name"],
                "medsam2",
            )
            self.assertEqual(visual_contract["findings"][0]["target"], "lung_opacity")
            self.assertEqual(
                visual_contract["findings"][0]["regions"][0]["area_px"],
                9278,
            )
            self.assertEqual(
                visual_contract["findings"][0]["regions"][0]["area_ratio_in_image"],
                0.043194,
            )
            self.assertTrue(visual_contract["findings"][0]["diagnosis_usable"])
            self.assertIn(
                "不能作为确定诊断依据",
                " ".join(report["不确定性说明"]),
            )

    def test_visual_result_maps_multiple_mask_regions_into_one_finding(self):
        visual_result = build_candidate_visual_analysis_result(
            {
                "status": "ok",
                "image_path": "cxr.png",
                "mask_path": "mask.png",
                "overlay_path": "overlay.png",
                "comparison_path": "comparison.png",
                "measurements": {
                    "lesion_area_px": 15,
                    "image_area_px": 120,
                    "lesion_area_ratio": 0.125,
                    "lesion_bbox": [1, 1, 11, 9],
                    "lesion_centroid": [6.2, 4.9],
                    "region_count": 2,
                    "regions": [
                        {
                            "region_id": "r1",
                            "area_px": 9,
                            "area_ratio_in_image": 0.075,
                            "bbox": [8, 6, 11, 9],
                            "centroid": [9.0, 7.0],
                        },
                        {
                            "region_id": "r2",
                            "area_px": 6,
                            "area_ratio_in_image": 0.05,
                            "bbox": [1, 1, 4, 3],
                            "centroid": [2.0, 1.5],
                        },
                    ],
                },
                "segmentation_result": {
                    "task_name": "segment_candidate_lesion",
                    "diagnosis_usable": True,
                    "selected_tool": {"tool_name": "medsam2"},
                    "quality": {"score": 0.6},
                },
            }
        )

        finding = visual_result["visual_evidence"]["findings"][0]
        self.assertEqual(
            visual_result["image_outputs"]["comparison_path"],
            "comparison.png",
        )
        self.assertEqual(finding["target"], "lung_opacity")
        self.assertEqual(len(finding["regions"]), 2)
        self.assertEqual(finding["regions"][0]["region_id"], "r1")
        self.assertEqual(finding["regions"][0]["area_px"], 9)
        self.assertEqual(finding["regions"][1]["bbox"], [1, 1, 4, 3])

    def test_visual_result_reuses_findings_from_segmentation_summary(self):
        visual_result = build_candidate_visual_analysis_result(
            {
                "status": "ok",
                "image_path": "hip.png",
                "mask_path": "mask.png",
                "overlay_path": "overlay.png",
                "measurements": {
                    "lesion_area_px": 20,
                    "image_area_px": 100,
                    "lesion_area_ratio": 0.2,
                },
                "findings": [
                    {
                        "finding_id": "finding_sclerotic_band",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "regions": [{"region_id": "r1", "area_px": 20}],
                        "diagnosis_usable": True,
                    }
                ],
                "segmentation_result": {
                    "task_name": "segment_sclerotic_band",
                    "diagnosis_usable": True,
                    "selected_tool": {"tool_name": "medsam2"},
                    "quality": {"score": 0.6},
                },
            }
        )

        self.assertEqual(
            visual_result["visual_evidence"]["findings"][0]["target"],
            "sclerotic_band",
        )
        self.assertEqual(
            visual_result["requested_targets"],
            ["sclerotic_band"],
        )
        facts = visual_result["visual_evidence"]["structured_visual_facts"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["target"], "sclerotic_band")
        self.assertTrue(facts[0]["diagnosis_usable"])

    def test_demo_builds_guideline_report_for_femoral_head_findings(self):
        with TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            segmentation_summary = workdir / "segmentation_summary.json"
            segmentation_summary.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "image_path": "output/fake/fhn_xray.png",
                        "mask_path": "output/fake/fhn_mask.png",
                        "overlay_path": "output/fake/fhn_overlay.png",
                        "measurements": {
                            "lesion_area_px": 1371,
                            "image_area_px": 75200,
                            "lesion_area_ratio": 0.018231,
                            "lesion_bbox": [65, 72, 111, 120],
                            "lesion_centroid": [89.143, 95.499],
                        },
                        "findings": [
                            {
                                "finding_id": "finding_sclerotic_band",
                                "target": "sclerotic_band",
                                "display_name": "硬化带",
                                "status": "candidate_present",
                                "regions": [{"region_id": "r1", "area_px": 1371}],
                                "diagnosis_usable": True,
                            },
                            {
                                "finding_id": "finding_cystic_change",
                                "target": "cystic_change",
                                "display_name": "囊性变",
                                "status": "candidate_present",
                                "regions": [{"region_id": "r1", "area_px": 1371}],
                                "diagnosis_usable": True,
                            },
                        ],
                        "segmentation_result": {
                            "task_name": "segment_sclerotic_band",
                            "target": "sclerotic_band",
                            "diagnosis_usable": True,
                            "selected_tool": {"tool_name": "medsam2"},
                            "quality": {"score": 0.6},
                        },
                        "segmentation_results": [
                            {
                                "task_name": "segment_sclerotic_band",
                                "target": "sclerotic_band",
                                "diagnosis_usable": True,
                                "selected_tool": {"tool_name": "medsam2"},
                                "quality": {"score": 0.6},
                            },
                            {
                                "task_name": "segment_cystic_change",
                                "target": "cystic_change",
                                "diagnosis_usable": True,
                                "selected_tool": {"tool_name": "medsam2"},
                                "quality": {"score": 0.6},
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_no_mask_candidate_diagnosis_demo(
                segmentation_summary_path=segmentation_summary,
                output_dir=workdir / "out",
                disease_key="femoral_head_necrosis",
                case_id="case_fhn_no_mask",
                patient_message="髋关节疼痛，上传髋关节 X 光。",
                symptoms=["髋关节疼痛"],
                modality="xray",
                body_part="hip",
                hypothesis_validation_mode=False,
            )

            self.assertEqual(result["status"], "ok")
            report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["used_skill"]["skill_type"], "guideline_based")
            self.assertIn("股骨头坏死", report["诊断倾向"])
            self.assertEqual(report["visual_input_contract"]["body_part"], "hip")
            self.assertEqual(
                [finding["target"] for finding in report["visual_input_contract"]["findings"]],
                ["sclerotic_band", "cystic_change"],
            )


if __name__ == "__main__":
    unittest.main()
