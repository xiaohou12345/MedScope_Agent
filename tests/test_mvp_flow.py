import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agents.diagnosis_agent import DiagnosisDoctorAgent
from agents.gaodoctor_agent import GaoDoctorAgent
from agents.vision_agent import VisionAgent
from memory.memory_manager import MemoryManager

REAL_SAMPLE_DIR = Path("data/external/brats2021_00030")
REAL_IMAGE = REAL_SAMPLE_DIR / "BraTS2021_00030_flair.nii.gz"
REAL_MASK = REAL_SAMPLE_DIR / "BraTS2021_00030_seg.nii.gz"


class RecordingVisionAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def analyze_with_visual_protocol(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "image_path": kwargs["image_path"],
            "modality": "MRI",
            "body_part": "brain",
            "image_outputs": {
                "original_image_path": kwargs["image_path"],
                "mask_path": kwargs.get("mask_path") or kwargs.get("output_mask_path"),
                "overlay_path": kwargs.get("overlay_path"),
            },
            "visual_evidence": {
                "disease_target": "diffuse_glioma_adult",
                "measurements": {},
                "completeness": {},
                "segmentation_quality": "recorded",
            },
        }

    def analyze_brats_nifti_ground_truth(self, **kwargs):
        raise AssertionError("GaoDoctorAgent should use analyze_with_visual_protocol")

    def analyze_brats_with_segmentation_model(self, **kwargs):
        raise AssertionError("GaoDoctorAgent should use analyze_with_visual_protocol")

    def analyze_image(self, **kwargs):
        raise AssertionError("not expected in glioma visual-protocol test")


class MultiFindingVisionAgent:
    def analyze_image(self, **kwargs):
        image_path = kwargs["image_path"]
        return {
            "image_path": image_path,
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": image_path,
                "mask_path": "output/fake/multifinding/mask.png",
                "overlay_path": "output/fake/multifinding/overlay.png",
            },
            "requested_targets": ["sclerotic_band", "cystic_change"],
            "requested_features": ["area_ratio_in_anatomy"],
            "visual_evidence": {
                "femoral_head_shape": "未评估",
                "collapse": False,
                "sclerosis": "候选阳性",
                "cystic_change": "候选阳性",
                "joint_space_narrowing": False,
                "joint_space": "未评估",
                "lesion_mask": "output/fake/multifinding/mask.png",
                "confidence": 0.7,
                "texture_abnormality_score": 0.75,
                "lesion_area_ratio": 0.08,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "lesion_detected": True,
                "lesion_location": "right femoral head",
                "segmentation_quality": "medium_candidate",
                "disease_target": "femoral_head_necrosis",
                "suspected_visual_findings": [
                    "硬化带：candidate_present；候选硬化带",
                    "囊性变：candidate_present；候选囊性变",
                ],
                "measurements": {"lesion_area_ratio": 0.08},
                "completeness": {
                    "candidate_lesion_mask": {
                        "status": "supported",
                        "reason": "candidate mask generated",
                    }
                },
                "findings": [
                    {
                        "finding_id": "finding_sclerotic_band",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "regions": [
                            {
                                "region_id": "r1",
                                "mask_path": "output/fake/multifinding/sclerotic_band_mask.png",
                                "overlay_path": "output/fake/multifinding/sclerotic_band_overlay.png",
                                "bbox": [10, 20, 30, 40],
                                "centroid": [20, 30],
                                "area_px": 120,
                                "area_ratio_in_image": 0.02,
                                "area_ratio_in_anatomy": 0.12,
                            }
                        ],
                        "confidence": 0.82,
                        "evidence_basis": "候选硬化带",
                        "measurements": {
                            "area_px": 120,
                            "area_ratio_in_image": 0.02,
                            "area_ratio_in_anatomy": 0.12,
                        },
                        "diagnosis_usable": True,
                    },
                    {
                        "finding_id": "finding_cystic_change",
                        "target": "cystic_change",
                        "display_name": "囊性变",
                        "status": "candidate_present",
                        "regions": [
                            {
                                "region_id": "r1",
                                "mask_path": "output/fake/multifinding/cystic_change_mask.png",
                                "overlay_path": "output/fake/multifinding/cystic_change_overlay.png",
                                "bbox": [12, 22, 24, 36],
                                "centroid": [18, 29],
                                "area_px": 80,
                                "area_ratio_in_image": 0.01,
                                "area_ratio_in_anatomy": 0.08,
                            }
                        ],
                        "confidence": 0.76,
                        "evidence_basis": "候选囊性变",
                        "measurements": {
                            "area_px": 80,
                            "area_ratio_in_image": 0.01,
                            "area_ratio_in_anatomy": 0.08,
                        },
                        "diagnosis_usable": True,
                    },
                ],
                "segmentation_results": [],
                "visual_tool_plan": [
                    {"step": "vision_model_localization", "tool_name": "gemini-3.5-flash"},
                    {"step": "segmentation", "tool_name": "medsam2"},
                ],
            },
        }


class FactUsageVisionAgent:
    def analyze_image(self, **kwargs):
        image_path = kwargs["image_path"]
        return {
            "image_path": image_path,
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": image_path,
                "mask_path": "output/fake/fact_usage/mask.png",
                "overlay_path": "output/fake/fact_usage/overlay.png",
            },
            "requested_targets": ["sclerotic_band", "cystic_change", "collapse"],
            "requested_features": ["structured_visual_facts"],
            "visual_evidence": {
                "femoral_head_shape": "未评估",
                "collapse": False,
                "sclerosis": "候选阳性",
                "cystic_change": "候选阳性",
                "joint_space_narrowing": False,
                "joint_space": "未评估",
                "lesion_mask": "output/fake/fact_usage/mask.png",
                "confidence": 0.7,
                "texture_abnormality_score": 0.75,
                "lesion_area_ratio": 0.08,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "lesion_detected": True,
                "lesion_location": "right femoral head",
                "segmentation_quality": "medium_candidate",
                "disease_target": "femoral_head_necrosis",
                "suspected_visual_findings": [],
                "measurements": {},
                "completeness": {},
                "findings": [],
                "structured_visual_facts": [
                    {
                        "finding_id": "fact_used_sclerosis",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "laterality": "image_left",
                        "diagnosis_usable": True,
                        "independent_evidence": True,
                        "alignment_status": "aligned",
                    },
                    {
                        "finding_id": "fact_excluded_cyst",
                        "target": "cystic_change",
                        "display_name": "囊性变",
                        "status": "candidate_present",
                        "laterality": "image_left",
                        "diagnosis_usable": True,
                        "independent_evidence": False,
                        "non_independent_reason": "overlaps_existing_finding",
                        "overlap_with_finding_id": "fact_used_sclerosis",
                        "alignment_status": "aligned",
                    },
                    {
                        "finding_id": "fact_excluded_collapse",
                        "target": "collapse",
                        "display_name": "股骨头塌陷",
                        "status": "candidate_present",
                        "laterality": "image_right",
                        "diagnosis_usable": False,
                        "independent_evidence": True,
                        "alignment_status": "low_alignment",
                    },
                ],
            },
        }


class FakeNoMaskSkillPipeline:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        image_path = str(kwargs["image_path"])
        view_token = "frog_lateral" if "frog" in image_path else "ap_pelvis" if "ap" in image_path else "single"
        path_prefix = f"{view_token}_" if view_token != "single" else ""
        visual_result = {
            "image_path": image_path,
            "modality": "xray",
            "body_part": "hip",
            "image_outputs": {
                "original_image_path": image_path,
                "mask_path": f"output/fake/fhn_no_mask/{path_prefix}finding_mask.png",
                "overlay_path": f"output/fake/fhn_no_mask/{path_prefix}finding_overlay.png",
                "comparison_path": f"output/fake/fhn_no_mask/{path_prefix}finding_comparison.png",
            },
            "requested_targets": ["sclerotic_band", "cystic_change"],
            "requested_features": ["area_ratio_in_anatomy", "anatomy_match"],
            "visual_evidence": {
                "collapse": False,
                "sclerosis": "候选阳性",
                "cystic_change": "候选阳性",
                "joint_space_narrowing": False,
                "lesion_mask": "output/fake/fhn_no_mask/finding_mask.png",
                "confidence": 0.7,
                "texture_abnormality_score": 0.75,
                "lesion_area_ratio": 0.03,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "lesion_detected": True,
                "lesion_location": "femoral head",
                "disease_target": "femoral_head_necrosis",
                "segmentation_quality": "medium_candidate",
                "suspected_visual_findings": [
                    "硬化带：candidate_present；候选硬化带",
                    "囊性变：candidate_present；候选囊性变",
                ],
                "measurements": {"lesion_area_ratio": 0.03},
                "completeness": {
                    "candidate_lesion_mask": {
                        "status": "supported",
                        "reason": "VLM box prompt plus MedSAM2 candidate segmentation.",
                    }
                },
                "findings": [
                    {
                        "finding_id": f"{view_token}_finding_sclerotic_band",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "status": "candidate_present",
                        "regions": [],
                        "confidence": 0.82,
                        "evidence_basis": "候选硬化带",
                        "measurements": {
                            "area_px": 120,
                            "area_ratio_in_image": 0.02,
                            "area_ratio_in_anatomy": 0.12,
                            "anatomy_match": {
                                "anatomy_name": "femoral_head",
                                "candidate_index": 0,
                                "overlap_anatomy_px": 90,
                            },
                        },
                        "diagnosis_usable": True,
                    },
                    {
                        "finding_id": f"{view_token}_finding_cystic_change",
                        "target": "cystic_change",
                        "display_name": "囊性变",
                        "status": "candidate_present",
                        "regions": [],
                        "confidence": 0.76,
                        "evidence_basis": "候选囊性变",
                        "measurements": {
                            "area_px": 80,
                            "area_ratio_in_image": 0.01,
                            "area_ratio_in_anatomy": 0.08,
                            "anatomy_match": {
                                "anatomy_name": "femoral_head",
                                "candidate_index": 1,
                                "overlap_anatomy_px": 70,
                            },
                        },
                        "diagnosis_usable": True,
                    },
                ],
                "segmentation_results": [],
                "visual_tool_plan": [
                    {"step": "vision_model_localization", "tool_name": "gemini-3.5-flash"},
                    {"step": "segmentation", "tool_name": "medsam2"},
                ],
            },
        }
        return {
            "status": "ok",
            "summary_path": "output/fake/fhn_no_mask/summary.json",
            "visual_analysis_result": visual_result,
            "visual_evidence_bundle": {
                "schema_version": "visual_evidence_bundle.v1",
                "present_findings": ["sclerotic_band", "cystic_change"],
                "numeric_evidence": {"finding_count": 2, "total_area_px": 200},
                "findings": visual_result["visual_evidence"]["findings"],
            },
        }


class MedScopeMvpFlowTest(unittest.TestCase):
    def test_gaodoctor_runs_case_and_persists_traceable_memory(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            doctor = GaoDoctorAgent(memory_manager=memory)

            result = doctor.handle_patient_case(
                patient_message="左髋疼痛三个月，帮我看看片子",
                image_path="data/images/demo_xray.png",
                patient_info={
                    "age": 45,
                    "sex": "male",
                    "symptoms": ["髋关节疼痛", "活动受限"],
                    "risk_factors": ["饮酒史"],
                },
            )

            self.assertIn("reply_to_patient", result)
            self.assertIn("case_id", result)
            self.assertIn("影像证据不足", result["reply_to_patient"])
            self.assertIn("MRI", result["reply_to_patient"])

            case_file = Path(tmpdir) / "cases" / f"{result['case_id']}.json"
            self.assertTrue(case_file.exists())
            saved_case = json.loads(case_file.read_text(encoding="utf-8"))
            self.assertEqual(saved_case["schema_version"], "memory_v1")
            self.assertEqual(
                saved_case["memory_types"],
                ["patient_memory", "image_memory", "skill_memory", "reasoning_memory"],
            )
            self.assertIn("patient_memory", saved_case)
            self.assertIn("image_memory", saved_case)
            self.assertIn("skill_memory", saved_case)
            self.assertIn("reasoning_memory", saved_case)
            self.assertIn("qa_memory", saved_case)
            self.assertEqual(saved_case["patient_memory"]["patient_info"]["age"], 45)
            self.assertEqual(saved_case["patient_memory"]["symptoms"], ["髋关节疼痛", "活动受限"])
            self.assertEqual(saved_case["patient_memory"]["intent"], "diagnosis")
            self.assertEqual(saved_case["image_memory"]["modality"], "X-ray")
            self.assertIn("image_outputs", saved_case["image_memory"])
            self.assertIn("visual_evidence", saved_case["image_memory"])
            self.assertIn("measurements", saved_case["image_memory"])
            self.assertIn("completeness", saved_case["image_memory"])
            self.assertIn("segmentation_quality", saved_case["image_memory"])
            self.assertEqual(
                saved_case["skill_memory"]["selected_skill"],
                "femoral_head_necrosis_v0.1",
            )
            self.assertIn("routing_decision", saved_case["skill_memory"])
            self.assertIn("guideline_evidence", saved_case["skill_memory"])
            self.assertEqual(
                saved_case["skill_memory"]["skill_type"],
                "guideline_based",
            )
            self.assertIn("report", saved_case["reasoning_memory"])
            self.assertEqual(
                saved_case["reasoning_memory"]["diagnostic_tendency"],
                "影像证据不足，需进一步评估",
            )
            self.assertIn("visual_input_contract", saved_case["reasoning_memory"])
            self.assertIn("uncertainty", saved_case["reasoning_memory"])
            image_bundle = saved_case["image_memory"]["visual_evidence_bundle"]
            self.assertEqual(image_bundle["schema_version"], "visual_evidence_bundle.v2")
            self.assertTrue(image_bundle["evidence_items"])
            bundle = memory.get_evidence_bundle(result["case_id"])
            self.assertEqual(bundle["patient_context"]["patient_message"], "左髋疼痛三个月，帮我看看片子")
            self.assertEqual(bundle["reasoning_evidence"]["diagnostic_tendency"], "影像证据不足，需进一步评估")

    def test_gaodoctor_persists_multifinding_visual_evidence_bundle_to_memory(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            doctor = GaoDoctorAgent(
                memory_manager=memory,
                vision_agent=MultiFindingVisionAgent(),
            )

            result = doctor.handle_patient_case(
                patient_message="右髋疼痛，上传 X 光，请根据股骨头坏死 skill 分析",
                image_path="output/fake/uploads/fhn_xray.png",
                patient_info={"symptoms": ["髋关节疼痛"]},
                disease_key="femoral_head_necrosis",
            )

            saved_case = json.loads(Path(result["case_memory_path"]).read_text(encoding="utf-8"))
            image_bundle = saved_case["image_memory"]["visual_evidence_bundle"]
            self.assertEqual(image_bundle["schema_version"], "visual_evidence_bundle.v1")
            self.assertEqual(image_bundle["present_findings"], ["sclerotic_band", "cystic_change"])
            self.assertEqual(image_bundle["numeric_evidence"]["finding_count"], 2)
            self.assertEqual(image_bundle["numeric_evidence"]["total_area_px"], 200)
            self.assertEqual(len(image_bundle["structured_visual_facts"]), 2)
            self.assertEqual(
                image_bundle["structured_visual_facts"][0]["target"],
                "sclerotic_band",
            )
            self.assertTrue(
                image_bundle["structured_visual_facts"][0]["diagnosis_usable"]
            )
            self.assertEqual(
                image_bundle["structured_visual_facts"][0]["area_px"],
                120,
            )
            self.assertEqual(
                image_bundle["diagnosis_payload"]["visual_evidence"]["findings"][1]["target"],
                "cystic_change",
            )

            evidence_bundle = memory.get_evidence_bundle(result["case_id"])
            self.assertEqual(
                evidence_bundle["image_evidence"]["visual_evidence_bundle"]["present_findings"],
                ["sclerotic_band", "cystic_change"],
            )
            self.assertIn(
                "X 光候选征象：硬化带、囊性变",
                "；".join(evidence_bundle["reasoning_evidence"]["key_evidence"]),
            )

    def test_gaodoctor_persists_visual_fact_usage_to_reasoning_memory_and_audit(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            doctor = GaoDoctorAgent(
                memory_manager=memory,
                vision_agent=FactUsageVisionAgent(),
            )

            result = doctor.handle_patient_case(
                patient_message="右髋疼痛，上传 X 光，请根据股骨头坏死 skill 分析",
                image_path="output/fake/uploads/fhn_xray.png",
                patient_info={"symptoms": ["髋关节疼痛"]},
                disease_key="femoral_head_necrosis",
            )

            saved_case = json.loads(Path(result["case_memory_path"]).read_text(encoding="utf-8"))
            usage = saved_case["reasoning_memory"]["visual_fact_usage"]
            self.assertEqual(
                [fact["finding_id"] for fact in usage["used"]],
                ["fact_used_sclerosis"],
            )
            self.assertEqual(
                [fact["finding_id"] for fact in usage["excluded"]],
                ["fact_excluded_cyst", "fact_excluded_collapse"],
            )
            self.assertEqual(
                usage["excluded"][0]["exclusion_reason"],
                "non_independent_evidence",
            )
            self.assertEqual(
                usage["excluded"][1]["exclusion_reason"],
                "not_diagnosis_usable",
            )

            audit = memory.build_audit_summary(result["case_id"])
            self.assertEqual(audit["visual_fact_usage"]["used_count"], 1)
            self.assertEqual(audit["visual_fact_usage"]["excluded_count"], 2)
            self.assertEqual(
                audit["agent_io_summary"]["DiagnosisDoctorAgent"]["visual_fact_usage"][
                    "used_count"
                ],
                1,
            )

    def test_gaodoctor_runs_fhn_no_mask_skill_pipeline_when_requested(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            no_mask_runner = FakeNoMaskSkillPipeline()
            doctor = GaoDoctorAgent(
                memory_manager=memory,
                no_mask_visual_pipeline_runner=no_mask_runner,
            )

            result = doctor.handle_patient_case(
                patient_message="右髋疼痛，上传 X 光，请根据股骨头坏死 skill 自动圈出候选征象",
                image_path="output/fake/uploads/fhn_xray.png",
                patient_info={"symptoms": ["髋关节疼痛"]},
                disease_key="femoral_head_necrosis",
                vision_mode="no_mask_skill",
            )

            self.assertEqual(len(no_mask_runner.calls), 1)
            self.assertEqual(no_mask_runner.calls[0]["image_path"], "output/fake/uploads/fhn_xray.png")
            self.assertEqual(no_mask_runner.calls[0]["disease_key"], "femoral_head_necrosis")
            self.assertEqual(no_mask_runner.calls[0]["patient_message"], "右髋疼痛，上传 X 光，请根据股骨头坏死 skill 自动圈出候选征象")

            saved_case = json.loads(Path(result["case_memory_path"]).read_text(encoding="utf-8"))
            image_bundle = saved_case["image_memory"]["visual_evidence_bundle"]
            self.assertEqual(image_bundle["present_findings"], ["sclerotic_band", "cystic_change"])
            self.assertEqual(image_bundle["numeric_evidence"]["total_area_px"], 200)
            self.assertEqual(
                image_bundle["findings"][0]["measurements"]["anatomy_match"]["anatomy_name"],
                "femoral_head",
            )
            self.assertEqual(
                saved_case["image_memory"]["image_outputs"]["comparison_path"],
                "output/fake/fhn_no_mask/finding_comparison.png",
            )
            self.assertEqual(
                image_bundle["image_outputs"]["comparison_path"],
                "output/fake/fhn_no_mask/finding_comparison.png",
            )
            self.assertEqual(
                saved_case["skill_memory"]["selected_vision_mode"],
                "no_mask_skill",
            )

    def test_gaodoctor_runs_multi_view_fhn_no_mask_pipeline_and_merges_evidence(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            no_mask_runner = FakeNoMaskSkillPipeline()
            doctor = GaoDoctorAgent(
                memory_manager=memory,
                no_mask_visual_pipeline_runner=no_mask_runner,
            )

            result = doctor.handle_patient_case(
                patient_message="右髋疼痛，上传正位和蛙式位 X 光，请判断是否股骨头坏死",
                image_path="output/fake/uploads/patient_ap_pelvis.png",
                patient_info={
                    "symptoms": ["髋关节疼痛"],
                    "image_series": [
                        {
                            "image_id": "image_001",
                            "image_path": "output/fake/uploads/patient_ap_pelvis.png",
                            "view_hint": "ap_pelvis",
                        },
                        {
                            "image_id": "image_002",
                            "image_path": "output/fake/uploads/patient_frog_lateral.png",
                            "view_hint": "frog_lateral",
                        },
                    ],
                },
                disease_key="femoral_head_necrosis",
                vision_mode="no_mask_skill",
            )

            saved_case = json.loads(Path(result["case_memory_path"]).read_text(encoding="utf-8"))
            image_bundle = saved_case["image_memory"]["visual_evidence_bundle"]
            image_context = image_bundle["image_context"]

        self.assertEqual(
            [call["image_path"] for call in no_mask_runner.calls],
            [
                "output/fake/uploads/patient_ap_pelvis.png",
                "output/fake/uploads/patient_frog_lateral.png",
            ],
        )
        self.assertEqual(
            [item["view_hint"] for item in image_context["image_series"]],
            ["ap_pelvis", "frog_lateral"],
        )
        self.assertEqual(image_context["primary_image_id"], "image_001")
        self.assertEqual(image_context["view_coverage"]["provided_views"], ["ap_pelvis", "frog_lateral"])
        self.assertEqual(image_context["view_coverage"]["analysis_scope"], "multi_view_execution")
        self.assertEqual(
            image_context["view_coverage"]["analyzed_views"],
            ["ap_pelvis", "frog_lateral"],
        )
        self.assertEqual(len(image_bundle["per_image_results"]), 2)
        self.assertEqual(len(image_bundle["findings"]), 4)
        self.assertEqual(image_bundle["numeric_evidence"]["finding_count"], 4)
        self.assertEqual(image_bundle["numeric_evidence"]["total_area_px"], 400)
        self.assertEqual(
            {(finding["image_id"], finding["view_hint"]) for finding in image_bundle["findings"]},
            {("image_001", "ap_pelvis"), ("image_002", "frog_lateral")},
        )
        self.assertEqual(
            {
                result["image_id"]: result["image_outputs"]["comparison_path"]
                for result in image_bundle["per_image_results"]
            },
            {
                "image_001": "output/fake/fhn_no_mask/ap_pelvis_finding_comparison.png",
                "image_002": "output/fake/fhn_no_mask/frog_lateral_finding_comparison.png",
            },
        )

    def test_gaodoctor_persists_insufficient_image_skill_alignment_without_vision_run(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            doctor = GaoDoctorAgent(memory_manager=memory)
            alignment_plan = {
                "selected_skill": "femoral_head_necrosis",
                "analysis_status": "insufficient_evidence",
                "clinical_focus": "股骨头坏死早期评估",
                "image_context": {
                    "modality": "xray",
                    "body_part": "hip",
                    "available_sequences": [],
                },
                "visual_tasks": [
                    {
                        "task": "assess_late_xray_findings",
                        "required_input": "X-ray",
                        "status": "runnable",
                    },
                    {
                        "task": "assess_early_osteonecrosis",
                        "required_input": "MRI T1/T2",
                        "status": "missing_input",
                        "reason": "Early osteonecrosis can be radiograph-negative.",
                    },
                ],
                "diagnosis_scope": {
                    "allowed": ["提示当前 X 光不足以排除早期病变"],
                    "blocked": ["不能将 X 光未见异常解释为无病"],
                },
                "suspected_conditions": [
                    {
                        "disease": "股骨头坏死",
                        "reason": "髋痛症状与疑似疾病方向匹配，但 X 光不足以排除早期病变。",
                    }
                ],
                "required_next_images": [
                    {
                        "modality": "MRI",
                        "region": "双髋关节",
                        "reason": "早期股骨头坏死需要 MRI T1/T2 或 STIR 评估。",
                    }
                ],
                "insufficiency_reasons": ["X 光不足以排除早期股骨头坏死"],
            }

            result = doctor.handle_message(
                patient_message="左髋疼痛，X光能不能判断有没有早期股骨头坏死？",
                image_path="output/fake/uploads/hip_xray.png",
                patient_info={"symptoms": ["髋关节疼痛"]},
                disease_key="femoral_head_necrosis",
                alignment_plan=alignment_plan,
            )

            self.assertEqual(result["analysis_status"], "insufficient_evidence")
            self.assertIn("无法进行可靠判断", result["reply_to_patient"])
            self.assertEqual(result["required_next_images"][0]["modality"], "MRI")

            saved_case = json.loads(Path(result["case_memory_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved_case["image_memory"]["segmentation_quality"], "not_run_insufficient_evidence")
            self.assertEqual(
                saved_case["image_memory"]["completeness"]["assess_early_osteonecrosis"]["status"],
                "missing",
            )
            self.assertEqual(
                saved_case["skill_memory"]["alignment_plan"]["analysis_status"],
                "insufficient_evidence",
            )
            self.assertEqual(
                saved_case["reasoning_memory"]["diagnostic_tendency"],
                "现有影像证据不足，需补充检查后判断",
            )

    def test_gaodoctor_glioma_modes_use_generic_visual_protocol_executor(self):
        skill = DiagnosisDoctorAgent().load_disease_skill("diffuse_glioma_brats")
        recording_vision = RecordingVisionAgent()
        doctor = GaoDoctorAgent(vision_agent=recording_vision)

        ground_truth_result = doctor._run_visual_analysis(
            case_id="case_gt",
            image_path="case_flair.nii.gz",
            patient_message="请基于这次 FLAIR MRI 做胶质瘤辅助分析",
            disease_key="diffuse_glioma_brats",
            disease_skill=skill,
            vision_mode="ground_truth",
            mask_path="case_seg.nii.gz",
            segmentation_prompt=None,
        )

        self.assertEqual(ground_truth_result["visual_evidence"]["segmentation_quality"], "recorded")
        self.assertEqual(len(recording_vision.calls), 1)
        self.assertEqual(recording_vision.calls[0]["mask_path"], "case_seg.nii.gz")
        self.assertEqual(recording_vision.calls[0]["disease_skill"], skill)

        created_agents = []

        class RecordingMedSAM2VisionAgent(RecordingVisionAgent):
            def __init__(self, **kwargs):
                super().__init__()
                self.init_kwargs = kwargs
                created_agents.append(self)

        with patch("agents.gaodoctor_agent.MedSAM2CommandRunner.from_env", return_value=object()):
            with patch("agents.gaodoctor_agent.VisionAgent", RecordingMedSAM2VisionAgent):
                doctor._run_visual_analysis(
                    case_id="case_medsam2",
                    image_path="case_flair.nii.gz",
                    patient_message="请基于这次 FLAIR MRI 做胶质瘤辅助分析",
                    disease_key="diffuse_glioma_brats",
                    disease_skill=skill,
                    vision_mode="medsam2",
                    mask_path=None,
                    segmentation_prompt={"boxes": [[1, 1, 5, 5]]},
                )

        self.assertEqual(len(created_agents), 1)
        medsam2_call = created_agents[0].calls[0]
        self.assertEqual(medsam2_call["segmentation_prompt"], {"boxes": [[1, 1, 5, 5]]})
        self.assertTrue(str(medsam2_call["output_mask_path"]).endswith("_medsam2_mask.nii.gz"))
        self.assertEqual(medsam2_call["disease_skill"], skill)

    @unittest.skipUnless(
        REAL_IMAGE.exists() and REAL_MASK.exists(),
        "real BraTS2021 sample files are not downloaded",
    )
    def test_gaodoctor_runs_glioma_brats_case_and_persists_visual_protocol_memory(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            doctor = GaoDoctorAgent(memory_manager=memory)

            result = doctor.handle_message(
                patient_message="请基于这次 FLAIR MRI 做胶质瘤辅助分析",
                image_path=str(REAL_IMAGE),
                patient_info={"symptoms": ["头痛"], "age": 58},
                disease_key="diffuse_glioma_brats",
                vision_mode="ground_truth",
                mask_path=str(REAL_MASK),
            )

            report = result["report"]
            self.assertEqual(result["intent"], "diagnosis")
            self.assertEqual(report["used_skill"]["skill_id"], "diffuse_glioma_brats_v0.1")
            self.assertIn("胶质瘤", report["diagnostic_tendency"])
            self.assertIn("enhancing_tumor", "；".join(report["不确定性说明"]))
            self.assertNotIn("增强肿瘤体积为 0", "；".join(report["不确定性说明"]))

            saved_case = json.loads(Path(result["case_memory_path"]).read_text(encoding="utf-8"))
            image_memory = saved_case["image_memory"]
            self.assertEqual(image_memory["modality"], "MRI")
            self.assertEqual(image_memory["body_part"], "brain")
            self.assertIn("image_outputs", image_memory)
            self.assertTrue(Path(image_memory["image_outputs"]["overlay_path"]).exists())
            self.assertEqual(
                image_memory["visual_features"]["disease_target"],
                "diffuse_glioma_adult",
            )
            self.assertEqual(
                image_memory["visual_features"]["completeness"]["enhancing_tumor"]["status"],
                "missing",
            )

    def test_gaodoctor_routes_follow_up_qa_to_existing_memory(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            case_id = "case_existing"
            memory.save_case_memory(
                case_id=case_id,
                patient_memory={
                    "case_id": case_id,
                    "patient_message": "左髋疼痛三个月",
                    "patient_profile": {},
                },
                image_memory={
                    "case_id": case_id,
                    "image_id": "image_001",
                    "image_path": "data/images/demo_xray.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "visual_features": {},
                },
                skill_memory={
                    "disease": "股骨头坏死",
                    "skill_id": "femoral_head_necrosis_v0.1",
                    "skill_type": "guideline_based",
                    "evidence_level": "high",
                    "source": "ARCO 分期相关公开医学知识整理",
                },
                reasoning_memory={
                    "case_id": case_id,
                    "used_skill": "femoral_head_necrosis_v0.1",
                    "key_evidence": ["股骨头负重区纹理异常", "未见明显塌陷"],
                    "diagnostic_result": "疑似早期股骨头坏死",
                    "uncertainty": ["单纯 X 光对早期病变敏感性有限"],
                },
            )
            doctor = GaoDoctorAgent(memory_manager=memory)

            result = doctor.handle_message(
                patient_message="你刚才说哪里异常？",
                case_id=case_id,
            )

            self.assertEqual(result["intent"], "qa")
            self.assertEqual(result["case_id"], case_id)
            self.assertIn("股骨头负重区纹理异常", result["reply_to_patient"])
            self.assertIn("未见明显塌陷", result["reply_to_patient"])
            self.assertIn("xray", result["reply_to_patient"])
            self.assertIn("hip", result["reply_to_patient"])
            self.assertNotIn("MRI 显示", result["reply_to_patient"])
            self.assertEqual(len(list((Path(tmpdir) / "cases").glob("*.json"))), 1)
            saved_case = memory.get_case_by_id(case_id)
            self.assertEqual(len(saved_case["qa_memory"]), 1)
            self.assertEqual(saved_case["qa_memory"][0]["question"], "你刚才说哪里异常？")
            self.assertEqual(saved_case["qa_memory"], saved_case["patient_memory"]["qa_history"])
            self.assertEqual(
                saved_case["patient_memory"]["qa_history"][0]["referenced_case_id"],
                case_id,
            )
            self.assertTrue(saved_case["patient_memory"]["qa_history"][0]["evidence_bundle_used"])

    def test_vision_agent_returns_evidence_without_final_diagnosis(self):
        evidence = VisionAgent().analyze_image(
            image_path="data/images/demo_xray.png",
            disease_skill={
                "disease_name": "股骨头坏死",
                "vision_agent_tasks": {
                    "segmentation_targets": ["股骨头区域", "疑似坏死区域"],
                    "quantitative_features": ["texture_abnormality_score"],
                },
            },
        )

        self.assertIn("visual_evidence", evidence)
        self.assertIn("image_outputs", evidence)
        self.assertNotIn("diagnosis", evidence)
        self.assertFalse(evidence["visual_evidence"]["collapse"])
        self.assertIn("mask_path", evidence["image_outputs"])

    def test_diagnosis_agent_combines_skill_visual_evidence_and_symptoms(self):
        visual_result = VisionAgent().analyze_image(
            image_path="data/images/demo_xray.png",
            disease_skill={
                "disease_name": "股骨头坏死",
                "vision_agent_tasks": {
                    "segmentation_targets": ["股骨头区域"],
                    "quantitative_features": ["texture_abnormality_score"],
                },
            },
        )
        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_test",
            patient_info={
                "symptoms": ["髋关节疼痛"],
                "risk_factors": ["饮酒史"],
            },
            visual_result=visual_result,
        )

        self.assertEqual(report["diagnostic_tendency"], "疑似早期股骨头坏死")
        self.assertEqual(report["诊断倾向"], "疑似早期股骨头坏死")
        self.assertIn("影像依据", report)
        self.assertIn("不确定性说明", report)
        self.assertIn("建议进一步检查", report)
        self.assertEqual(
            report["visual_input_contract"]["image_outputs"]["overlay_path"],
            visual_result["image_outputs"]["overlay_path"],
        )
        self.assertEqual(
            report["visual_input_contract"]["visual_evidence"]["segmentation_quality"],
            visual_result["visual_evidence"]["segmentation_quality"],
        )

    def test_missing_guideline_creates_low_evidence_hypothesis_skill(self):
        skill = DiagnosisDoctorAgent().prepare_skill(
            disease_key="rare_disease_without_guideline",
            disease_name="罕见病示例",
            observations=["已确诊病例中常见局部纹理异常"],
        )

        self.assertEqual(skill["skill_type"], "data_mined_hypothesis")
        self.assertEqual(skill["evidence_level"], "low")
        self.assertIn("不等同于正式医学指南", skill["warning"])

    def test_hypothesis_skill_is_blocked_unless_validation_mode_is_enabled(self):
        visual_result = VisionAgent().analyze_image(
            image_path="data/images/demo_xray.png",
            disease_skill={
                "disease_name": "股骨头坏死 1 期假设",
                "vision_agent_tasks": {
                    "segmentation_targets": ["股骨头区域"],
                    "quantitative_features": ["texture_abnormality_score"],
                },
            },
        )
        hypothesis_skill = DiagnosisDoctorAgent().prepare_skill(
            disease_key="fhn_stage1_without_guideline",
            disease_name="股骨头坏死 1 期假设",
            observations=["X 光股骨头负重区出现亚像素级纹理不均"],
        )

        with self.assertRaisesRegex(ValueError, "hypothesis_validation_mode"):
            DiagnosisDoctorAgent().generate_report(
                case_id="case_hypothesis_blocked",
                patient_info={"symptoms": ["髋关节疼痛"]},
                visual_result=visual_result,
                disease_skill=hypothesis_skill,
            )

    def test_hypothesis_validation_mode_generates_research_warning_not_diagnosis(self):
        visual_result = VisionAgent().analyze_image(
            image_path="data/images/demo_xray.png",
            disease_skill={
                "disease_name": "股骨头坏死 1 期假设",
                "vision_agent_tasks": {
                    "segmentation_targets": ["股骨头区域"],
                    "quantitative_features": ["texture_abnormality_score"],
                },
            },
        )
        hypothesis_skill = DiagnosisDoctorAgent().prepare_skill(
            disease_key="fhn_stage1_without_guideline",
            disease_name="股骨头坏死 1 期假设",
            observations=["X 光股骨头负重区出现亚像素级纹理不均"],
        )

        report = DiagnosisDoctorAgent().generate_report(
            case_id="case_hypothesis_enabled",
            patient_info={"symptoms": ["髋关节疼痛"]},
            visual_result=visual_result,
            disease_skill=hypothesis_skill,
            hypothesis_validation_mode=True,
        )

        self.assertEqual(report["hypothesis_validation_mode"], "enabled")
        self.assertEqual(report["used_skill"]["skill_type"], "data_mined_hypothesis")
        self.assertIn("科研假设风险提示", report["diagnostic_tendency"])
        self.assertIn("建议进一步金标准检查", "；".join(report["建议进一步检查"]))
        patient_facing_text = json.dumps(
            {
                "诊断倾向": report["诊断倾向"],
                "影像依据": report["影像依据"],
                "分期判断": report["分期判断"],
                "不确定性说明": report["不确定性说明"],
                "建议进一步检查": report["建议进一步检查"],
                "治疗建议": report["治疗建议"],
            },
            ensure_ascii=False,
        )
        self.assertNotIn("确诊", patient_facing_text)
        self.assertNotIn("正式指南", report["diagnostic_tendency"])


if __name__ == "__main__":
    unittest.main()
