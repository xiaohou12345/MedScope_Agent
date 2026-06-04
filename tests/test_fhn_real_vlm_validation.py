import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.gaodoctor_agent import GaoDoctorAgent
from api.service import MedScopeService
from memory.memory_manager import MemoryManager


class FakeVlmPromptRunner:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def run(self, task, system_prompt, user_payload):
        self.calls.append(
            {
                "task": task,
                "system_prompt": system_prompt,
                "user_payload": user_payload,
            }
        )
        return json.dumps(self.payload)


class FhnRealVlmValidationTest(unittest.TestCase):
    def test_service_real_vlm_validation_persists_candidate_evidence_without_segmentation_upgrade(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            runner = FakeVlmPromptRunner(
                {
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
            )
            service = MedScopeService(
                gaodoctor_agent=GaoDoctorAgent(
                    memory_manager=memory,
                    prompt_runner=runner,
                )
            )

            result = service.handle_request(
                {
                    "patient_message": "左髋疼痛，上传正位和侧位 X 光，请检查候选征象",
                    "image_paths": [
                        "output/real/onfh_pair/ap_detail_idiopathic_onfh.jpg",
                        "output/real/onfh_pair/lateral_idiopathic_onfh.jpg",
                    ],
                    "patient_info": {"symptoms": ["左髋疼痛"]},
                    "vision_mode": "real_vlm_validation",
                }
            )

            self.assertEqual(runner.calls[0]["task"], "fhn_real_vlm_validation")
            self.assertEqual(result["routing_decision"]["selected_vision_mode"], "real_vlm_validation")
            bundle = result["visual_evidence_bundle"]
            item = bundle["evidence_items"][0]
            self.assertEqual(item["target"], "sclerotic_band")
            self.assertEqual(item["execution_mode"], "vlm_only")
            self.assertEqual(item["evidence_type"], "visual_observation")
            self.assertEqual(item["diagnosis_usable_level"], "candidate_support")
            self.assertEqual(item["segmentation"]["status"], "not_requested")
            self.assertFalse(item["measurements"]["measurement_usable"])
            self.assertIn("vlm_candidate_not_measurement", item["limitations"])
            self.assertIn(
                "output/real/onfh_pair/ap_detail_idiopathic_onfh.jpg",
                runner.calls[0]["user_payload"]["image_paths"],
            )
            self.assertEqual(
                result["evidence_bundle"]["image_evidence"]["visual_evidence_bundle"]["image_context"]["view_coverage"]["provided_views"],
                ["ap_pelvis", "lateral"],
            )

    def test_service_real_vlm_validation_invalid_json_becomes_unassessed_visual_evidence(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            runner = FakeVlmPromptRunner("not-json")
            service = MedScopeService(
                gaodoctor_agent=GaoDoctorAgent(
                    memory_manager=memory,
                    prompt_runner=runner,
                )
            )

            result = service.handle_request(
                {
                    "patient_message": "左髋疼痛，上传 X 光",
                    "image_path": "output/real/onfh_pair/ap_detail_idiopathic_onfh.jpg",
                    "patient_info": {"symptoms": ["左髋疼痛"]},
                    "vision_mode": "real_vlm_validation",
                }
            )

            bundle = result["visual_evidence_bundle"]
            self.assertEqual(bundle["evidence_items"][0]["diagnosis_usable_level"], "not_usable")
            self.assertIn("real_vlm_validation_parse_error", bundle["quality_warnings"][0]["warning"])


if __name__ == "__main__":
    unittest.main()
