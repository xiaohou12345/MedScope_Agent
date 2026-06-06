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
                    {"id": 4, "name": "软骨下骨骨折"},
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
                    {
                        "id": 13,
                        "image_id": 2,
                        "category_id": 4,
                        "area": 20,
                        "bbox": [20, 30, 5, 4],
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
        self.assertEqual(payload["evaluation_scope"]["primary_modality"], "Xray")
        self.assertFalse(payload["evaluation_scope"]["include_auxiliary_modalities"])
        self.assertEqual(payload["dataset"]["source_image_count"], 2)
        self.assertEqual(payload["dataset"]["source_annotation_count"], 4)
        self.assertEqual(payload["dataset"]["evaluated_annotation_count"], 3)
        self.assertEqual(payload["dataset"]["auxiliary_excluded_annotation_count"], 1)
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
            "auxiliary_excluded",
        )
        self.assertEqual(labels["MRI-T2双线征"]["baseline_status"], "auxiliary_excluded")
        self.assertEqual(labels["未映射标签"]["current_protocol_status"], "unmapped_label")
        self.assertEqual(labels["软骨下骨骨折"]["target"], "subchondral_fracture")
        self.assertEqual(labels["软骨下骨骨折"]["current_protocol_status"], "covered")
        self.assertEqual(labels["软骨下骨骨折"]["baseline_status"], "gap")

        aggregate = payload["aggregate"]
        self.assertEqual(aggregate["mapped_annotation_count"], 2)
        self.assertEqual(aggregate["unmapped_annotation_count"], 1)
        self.assertEqual(aggregate["current_protocol_covered_annotation_count"], 2)
        self.assertEqual(aggregate["baseline_covered_annotation_count"], 1)
        self.assertEqual(aggregate["total_mask_area_px"], 65)

        self.assertIn("MRI-T2双线征", payload["auxiliary_modalities"]["excluded_labels"])
        self.assertIn("未映射标签", payload["coverage_gaps"]["unmapped_labels"])
        self.assertEqual(payload["coverage_gaps"]["baseline_missing_labels"], ["软骨下骨骨折"])

        sample = payload["sample_evidence_items"][0]
        self.assertNotIn("张三", json.dumps(sample, ensure_ascii=False))
        self.assertNotIn("李四", json.dumps(sample, ensure_ascii=False))
        self.assertRegex(sample["redacted_image_ref"], r"image_\d+")

    def test_auxiliary_modalities_can_be_included_explicitly_for_discovery_analysis(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "onfh_package"
            annotations = root / "annotations"
            annotations.mkdir(parents=True)
            coco = {
                "images": [{"id": 1, "file_name": "case/MRI001.jpg", "width": 100, "height": 80}],
                "categories": [{"id": 1, "name": "MRI-T2双线征"}],
                "annotations": [
                    {"id": 10, "image_id": 1, "category_id": 1, "area": 25, "bbox": [1, 2, 5, 5]}
                ],
            }
            (annotations / "instances_coco.json").write_text(
                json.dumps(coco, ensure_ascii=False),
                encoding="utf-8",
            )

            payload = run_onfh_coco_protocol_evaluation(
                package_dir=root,
                output_dir=Path(tmpdir) / "out",
                baseline_skill_path=Path(
                    "skills/baselines/femoral_head_necrosis_finding_list_baseline_20260604.yaml"
                ),
                current_skill_path=Path("skills/femoral_head_necrosis.yaml"),
                include_auxiliary_modalities=True,
            )

        self.assertTrue(payload["evaluation_scope"]["include_auxiliary_modalities"])
        self.assertEqual(payload["dataset"]["evaluated_annotation_count"], 1)
        self.assertEqual(payload["dataset"]["auxiliary_excluded_annotation_count"], 0)
        self.assertEqual(
            payload["label_mapping"]["MRI-T2双线征"]["current_protocol_status"],
            "covered_but_insufficient_input_rule",
        )


if __name__ == "__main__":
    unittest.main()
