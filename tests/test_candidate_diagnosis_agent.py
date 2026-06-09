import unittest

from agents.candidate_diagnosis_agent import CandidateDiagnosisAgent
from agents.diagnosis_agent import DiagnosisDoctorAgent


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

    def test_lite_report_uses_findings_only_and_classifies_candidate_stage(self):
        report = CandidateDiagnosisAgent().generate_lite_report(
            case_id="case_lite",
            patient_info={"patient_id": "p1", "patient_side": "左"},
            findings=[
                {
                    "target": "sclerotic_band",
                    "display_name": "硬化带",
                    "status": "detected",
                    "summary_text": "左侧硬化带 from reviewed mock GT mask",
                }
            ],
        )

        self.assertTrue(report["lite_mode"])
        self.assertEqual(report["onfh_visual_model_result"]["stage"], "I/II")
        self.assertEqual(report["onfh_agent_diagnosis"]["stage"], "I/II")
        self.assertFalse(report["onfh_agent_diagnosis"]["abstained"])
        self.assertNotIn("visual_input_contract", report)
        self.assertNotIn("used_skill", report)

    def test_lite_report_can_use_xray_three_class_stage_schema(self):
        report = CandidateDiagnosisAgent().generate_lite_report(
            case_id="case_xray_schema",
            patient_info={"patient_id": "p1", "patient_side": "左"},
            findings=[
                {
                    "target": "sclerotic_band",
                    "display_name": "硬化带",
                    "status": "detected",
                    "summary_text": "左侧硬化带 from reviewed mock GT mask",
                }
            ],
            stage_schema="xray_arco_3class",
        )

        self.assertEqual(report["onfh_visual_model_result"]["raw_stage"], "I/II")
        self.assertEqual(report["onfh_visual_model_result"]["stage"], "II")
        self.assertEqual(report["onfh_agent_diagnosis"]["stage"], "II")
        self.assertEqual(report["onfh_agent_diagnosis"]["allowed_stages"], ["normal", "II", "III"])

        report = CandidateDiagnosisAgent().generate_lite_report(
            case_id="case_xray_schema_iii",
            patient_info={"patient_id": "p1", "patient_side": "左"},
            findings=[
                {
                    "target": "subchondral_fracture",
                    "display_name": "软骨下骨折",
                    "status": "detected",
                }
            ],
            stage_schema="xray_arco_3class",
        )

        self.assertEqual(report["onfh_visual_model_result"]["raw_stage"], "III+")
        self.assertEqual(report["onfh_visual_model_result"]["stage"], "III")
        self.assertEqual(report["onfh_agent_diagnosis"]["stage"], "III")

    def test_llm_final_mode_scores_provisional_stage_from_full_report(self):
        agent = CandidateDiagnosisAgent()
        dx = agent._build_agent_diagnosis(
            visual_model_result={
                "stage": "II",
                "basis_targets": ["sclerotic_band"],
            },
            modality="xray",
            base_report={
                "诊断倾向": "辅助分析倾向股骨头坏死",
                "分期判断": "基于当前 X 光硬化带候选征象，辅助分期倾向 ARCO II 期可能；仍需 MRI 确认。",
            },
            stage_schema=agent._resolve_stage_schema("xray_arco_3class"),
            final_stage_mode="llm_final",
        )

        self.assertEqual(dx["stage"], "II")
        self.assertFalse(dx["abstained"])
        self.assertEqual(dx["stage_output_mode"], "llm_final_from_full_report")

    def test_llm_final_mode_does_not_score_negated_stage_mentions(self):
        agent = CandidateDiagnosisAgent()
        dx = agent._build_agent_diagnosis(
            visual_model_result={
                "stage": "normal",
                "basis_targets": [],
            },
            modality="xray",
            base_report={
                "诊断倾向": "当前辅助影像证据不足",
                "分期判断": "ARCO分期当前不能可靠判定。X光未提供支持ARCO III及以上所需的塌陷或新月征证据。",
            },
            stage_schema=agent._resolve_stage_schema("xray_arco_3class"),
            final_stage_mode="llm_final",
        )

        self.assertEqual(dx["stage"], "evidence_insufficient")
        self.assertTrue(dx["abstained"])

    def test_llm_report_json_parser_strips_zero_width_prefix(self):
        report = DiagnosisDoctorAgent()._parse_llm_report_json(
            '\u200b{"诊断倾向":"x","影像依据":[],"分期判断":"y",'
            '"不确定性说明":[],"建议进一步检查":[],"治疗建议":[]}'
        )

        self.assertEqual(report["分期判断"], "y")


if __name__ == "__main__":
    unittest.main()
