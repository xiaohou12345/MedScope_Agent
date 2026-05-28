import json
import unittest
from pathlib import Path

from tools.alignment_planner import AlignmentPlanner


class AlignmentPlannerTest(unittest.TestCase):
    def test_planner_uses_femoral_head_visual_protocol_for_xray_insufficiency(self):
        skill = json.loads(Path("skills/femoral_head_necrosis.yaml").read_text(encoding="utf-8"))

        plan = AlignmentPlanner().build_plan(
            payload={
                "patient_message": "左髋疼痛，X光能不能判断有没有早期股骨头坏死？",
                "image_path": "output/fake/uploads/hip_xray.png",
                "patient_info": {"symptoms": ["髋关节疼痛"]},
            },
            routing_decision={"selected_skill": "femoral_head_necrosis"},
            disease_skill=skill,
        )

        self.assertEqual(plan["analysis_status"], "insufficient_evidence")
        self.assertEqual(plan["selected_skill"], "femoral_head_necrosis")
        self.assertEqual(plan["image_context"]["modality"], "xray")
        self.assertEqual(plan["suspected_conditions"][0]["disease"], "股骨头坏死")
        self.assertEqual(plan["required_next_images"][0]["modality"], "MRI")
        tasks = {task["task"]: task for task in plan["visual_tasks"]}
        self.assertEqual(tasks["assess_late_xray_findings"]["status"], "runnable")
        self.assertEqual(tasks["assess_early_osteonecrosis"]["status"], "missing_input")
        self.assertIn("X 光不足以排除早期股骨头坏死", plan["insufficiency_reasons"][0])

    def test_planner_uses_glioma_visual_protocol_for_partial_flair_mri(self):
        skill = json.loads(Path("skills/diffuse_glioma_brats.yaml").read_text(encoding="utf-8"))

        plan = AlignmentPlanner().build_plan(
            payload={
                "patient_message": "请基于这次 FLAIR MRI 做胶质瘤辅助分析",
                "image_path": "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz",
                "patient_info": {"symptoms": ["头痛"]},
            },
            routing_decision={"selected_skill": "diffuse_glioma_brats"},
            disease_skill=skill,
        )

        self.assertEqual(plan["analysis_status"], "partial_evidence")
        tasks = {task["task"]: task for task in plan["visual_tasks"]}
        self.assertEqual(tasks["segment_whole_tumor"]["status"], "runnable")
        self.assertEqual(tasks["measure_enhancing_tumor"]["status"], "missing_input")
        self.assertEqual(tasks["measure_enhancing_tumor"]["required_input"], "T1ce")
        self.assertEqual(plan["required_next_images"][0]["modality"], "MRI")

    def test_planner_handles_unmatched_skill_without_disease_specific_code(self):
        plan = AlignmentPlanner().build_plan(
            payload={
                "patient_message": "请看一下这张普通医学图像",
                "image_path": "output/fake/uploads/scan.png",
                "patient_info": {"symptoms": ["不适"]},
            },
            routing_decision={"selected_skill": None},
            disease_skill={},
        )

        self.assertEqual(plan["analysis_status"], "partial_evidence")
        self.assertIsNone(plan["selected_skill"])
        self.assertEqual(plan["visual_tasks"], [])


if __name__ == "__main__":
    unittest.main()
