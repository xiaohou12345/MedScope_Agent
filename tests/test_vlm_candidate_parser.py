import unittest

from tools.vlm_candidate_parser import parse_vlm_candidates


class VlmCandidateParserTest(unittest.TestCase):
    def test_parser_converts_vlm_boxes_to_candidate_evidence_items(self):
        raw = {
            "findings": [
                {
                    "target": "sclerotic_band",
                    "side": "left",
                    "bbox": [100, 120, 180, 190],
                    "rationale": "arc-like increased density",
                    "confidence": 0.63,
                }
            ]
        }

        items = parse_vlm_candidates(
            raw,
            image_id="image_001",
            view_hint="ap_pelvis",
            source_image_path="output/real/onfh_pair/ap.png",
        )

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["target"], "sclerotic_band")
        self.assertEqual(item["image_id"], "image_001")
        self.assertEqual(item["view_hint"], "ap_pelvis")
        self.assertEqual(item["source_image_path"], "output/real/onfh_pair/ap.png")
        self.assertEqual(item["evidence_type"], "visual_observation")
        self.assertEqual(item["execution_mode"], "vlm_only")
        self.assertEqual(item["diagnosis_usable_level"], "candidate_support")
        self.assertTrue(item["diagnosis_usable"])
        self.assertEqual(item["visual_observation"]["status"], "candidate_present")
        self.assertEqual(item["visual_observation"]["rationale"], "arc-like increased density")
        self.assertEqual(item["visual_observation"]["laterality"], "left")
        self.assertEqual(item["measurements"]["bbox"], [100, 120, 180, 190])
        self.assertFalse(item["measurements"]["measurement_usable"])
        self.assertEqual(item["quality"]["source"], "vlm")
        self.assertEqual(item["quality"]["confidence"], 0.63)
        self.assertEqual(item["quality"]["localization_status"], "localized_candidate")
        self.assertIn("vlm_candidate_not_measurement", item["limitations"])

    def test_parser_marks_invalid_or_missing_locations_as_observation_only(self):
        raw = {
            "findings": [
                {
                    "target": "trabecular_blurring",
                    "rationale": "texture unclear",
                    "confidence": 0.51,
                }
            ]
        }

        items = parse_vlm_candidates(raw, image_id="image_001", view_hint="ap_pelvis")

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["target"], "trabecular_blurring")
        self.assertEqual(item["diagnosis_usable_level"], "observation_only")
        self.assertFalse(item["diagnosis_usable"])
        self.assertEqual(item["quality"]["localization_status"], "unlocalized_observation")
        self.assertEqual(item["measurements"]["measurement_usable"], False)
        self.assertIn("no_valid_location", item["limitations"])

    def test_parser_rejects_malformed_bbox_without_silent_repair(self):
        raw = {
            "findings": [
                {
                    "target": "cystic_change",
                    "bbox": [180, 190, 100, 120],
                    "rationale": "lucent focus",
                }
            ]
        }

        items = parse_vlm_candidates(raw, image_id="image_001", view_hint="ap_pelvis")

        self.assertEqual(items[0]["diagnosis_usable_level"], "observation_only")
        self.assertNotIn("bbox", items[0]["measurements"])
        self.assertIn("invalid_bbox", items[0]["limitations"])

    def test_parser_ignores_items_without_target(self):
        raw = {
            "findings": [
                {"bbox": [1, 2, 3, 4], "rationale": "missing target"},
                "not a dict",
            ]
        }

        self.assertEqual(
            parse_vlm_candidates(raw, image_id="image_001", view_hint="ap_pelvis"),
            [],
        )


if __name__ == "__main__":
    unittest.main()
