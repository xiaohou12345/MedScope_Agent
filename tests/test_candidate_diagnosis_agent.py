import unittest

from agents.candidate_diagnosis_agent import CandidateDiagnosisAgent


def _visual_result(findings):
    return {
        "image_path": "hip_xray.png",
        "modality": "xray",
        "body_part": "hip",
        "image_outputs": {
            "original_image_path": "hip_xray.png",
            "mask_path": "mask.png",
            "overlay_path": "overlay.png",
        },
        "visual_evidence": {
            "disease_target": "femoral_head_necrosis",
            "collapse": False,
            "joint_space_narrowing": False,
            "texture_abnormality_score": 0.0,
            "measurements": {},
            "completeness": {},
            "segmentation_quality": "candidate",
            "suspected_visual_findings": [],
            "findings": findings,
        },
    }


class CandidateDiagnosisAgentTest(unittest.TestCase):
    def test_agent_separates_visual_candidate_stage_from_agent_diagnosis(self):
        report = CandidateDiagnosisAgent().generate_report(
            case_id="case_onfh_candidate",
            patient_info={},
            visual_result=_visual_result(
                [
                    {
                        "target": "subchondral_fracture",
                        "display_name": "软骨下骨折",
                        "status": "candidate_present",
                        "diagnosis_usable": True,
                    }
                ]
            ),
        )

        self.assertEqual(report["onfh_visual_model_result"]["stage"], "III+")
        self.assertEqual(report["onfh_agent_diagnosis"]["candidate_stage"], "III+")
        self.assertEqual(report["onfh_agent_diagnosis"]["stage"], "evidence_insufficient")
        self.assertTrue(report["onfh_agent_diagnosis"]["abstained"])
        self.assertEqual(
            report["onfh_agent_diagnosis"]["uncertainty_status"],
            "base_report_abstain",
        )
        self.assertIn("无法可靠分期", report["分期判断"])

    def test_agent_abstains_when_stage_relevant_visual_evidence_is_missing(self):
        report = CandidateDiagnosisAgent().generate_report(
            case_id="case_onfh_abstain",
            patient_info={},
            visual_result=_visual_result([]),
        )

        self.assertEqual(report["onfh_visual_model_result"]["stage"], "evidence_insufficient")
        self.assertEqual(report["onfh_agent_diagnosis"]["stage"], "evidence_insufficient")
        self.assertTrue(report["onfh_agent_diagnosis"]["abstained"])
        self.assertEqual(report["agent_stage_confidence"], 0.0)
        self.assertEqual(report["分期判断"], "暂无法可靠分期")


if __name__ == "__main__":
    unittest.main()
