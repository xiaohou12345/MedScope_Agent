import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.onfh_coco_protocol_eval import run_onfh_coco_protocol_evaluation


class OnfhCocoProtocolEvaluationTest(unittest.TestCase):
    def test_coco_labels_are_mapped_to_protocol_and_baseline_without_leaking_paths(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "onfh_package"
            annotations = root / "annotations"
            images = root / "images"
            annotations.mkdir(parents=True)
            images.mkdir()
            coco = {
                "images": [
                    {
                        "id": 1,
                        "file_name": "2021年/1 36床张三 女19岁/术前/MRI001.jpg",
                        "width": 100,
                        "height": 80,
                    },
                    {
                        "id": 2,
                        "file_name": "2021年/2 42床李四 男44岁/术前/髋1.jpg",
                        "width": 120,
                        "height": 90,
                    },
                ],
                "categories": [
                    {"id": 1, "name": "MRI-T2双线征"},
                    {"id": 2, "name": "硬化带"},
                    {"id": 3, "name": "未映射标签"},
                ],
                "annotations": [
                    {
                        "id": 10,
                        "image_id": 1,
                        "category_id": 1,
                        "area": 25,
                        "bbox": [1, 2, 5, 5],
                    },
                    {
                        "id": 11,
                        "image_id": 2,
                        "category_id": 2,
                        "area": 40,
                        "bbox": [10, 20, 8, 5],
                    },
                    {
                        "id": 12,
                        "image_id": 2,
                        "category_id": 3,
                        "area": 5,
                        "bbox": [0, 0, 1, 5],
                    },
                ],
            }
            (annotations / "instances_coco.json").write_text(
                json.dumps(coco, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            payload = run_onfh_coco_protocol_evaluation(
                package_dir=root,
                output_dir=Path(tmpdir) / "out",
                baseline_skill_path=Path(
                    "skills/baselines/femoral_head_necrosis_finding_list_baseline_20260604.yaml"
                ),
                current_skill_path=Path("skills/femoral_head_necrosis.yaml"),
            )
            output_paths = payload["output_paths"]
            self.assertTrue(Path(output_paths["json_path"]).exists())
            self.assertTrue(Path(output_paths["markdown_path"]).exists())

        self.assertEqual(payload["schema_version"], "onfh_coco_protocol_evaluation.v1")
        self.assertEqual(payload["dataset"]["image_count"], 2)
        self.assertEqual(payload["dataset"]["annotation_count"], 3)
        self.assertTrue(payload["safety"]["real_data_evaluation_only"])
        self.assertTrue(payload["safety"]["patient_paths_redacted"])
        self.assertFalse(payload["safety"]["formal_skill_update_allowed"])
        self.assertFalse(payload["safety"]["diagnosis_allowed"])

        labels = payload["label_mapping"]
        self.assertEqual(labels["硬化带"]["target"], "sclerotic_band")
        self.assertEqual(labels["硬化带"]["current_protocol_status"], "covered")
        self.assertEqual(labels["硬化带"]["baseline_status"], "covered")
        self.assertEqual(labels["MRI-T2双线征"]["target"], "early_osteonecrosis")
        self.assertEqual(
            labels["MRI-T2双线征"]["current_protocol_status"],
            "covered_but_insufficient_input_rule",
        )
        self.assertEqual(labels["MRI-T2双线征"]["baseline_status"], "gap")
        self.assertEqual(labels["未映射标签"]["current_protocol_status"], "unmapped_label")

        aggregate = payload["aggregate"]
        self.assertEqual(aggregate["mapped_annotation_count"], 2)
        self.assertEqual(aggregate["unmapped_annotation_count"], 1)
        self.assertEqual(aggregate["current_protocol_covered_annotation_count"], 2)
        self.assertEqual(aggregate["baseline_covered_annotation_count"], 1)
        self.assertEqual(aggregate["total_mask_area_px"], 70)

        self.assertIn("MRI-T2双线征", payload["coverage_gaps"]["baseline_missing_labels"])
        self.assertIn("未映射标签", payload["coverage_gaps"]["unmapped_labels"])
        self.assertIn(
            "MRI-T2双线征",
            payload["coverage_gaps"]["current_protocol_mri_specific_detail_needed"],
        )

        sample = payload["sample_evidence_items"][0]
        self.assertNotIn("张三", json.dumps(sample, ensure_ascii=False))
        self.assertNotIn("李四", json.dumps(sample, ensure_ascii=False))
        self.assertRegex(sample["redacted_image_ref"], r"image_\d+")


if __name__ == "__main__":
    unittest.main()
