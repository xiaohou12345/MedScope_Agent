import unittest

from contracts.medical_contracts import (
    AlignmentPlan,
    DiagnosisVisualInput,
    ImageOutputs,
    LesionGallery,
    PatientCaseInput,
    PatientIntent,
    SegmentationResult,
    SkillDescriptor,
    SkillRoutingDecision,
    VisualTask,
    VisualToolCapability,
    VisualAnalysisResult,
    VisualEvidence,
)


class ContractBoundaryTest(unittest.TestCase):
    def test_alignment_plan_contract_marks_image_skill_insufficiency(self):
        plan = AlignmentPlan(
            selected_skill="femoral_head_necrosis",
            analysis_status="insufficient_evidence",
            clinical_focus="股骨头坏死早期评估",
            image_context={
                "modality": "xray",
                "body_part": "hip",
                "available_sequences": [],
            },
            visual_tasks=[
                {
                    "task": "assess_late_xray_findings",
                    "required_input": "X-ray",
                    "status": "runnable",
                },
                {
                    "task": "assess_early_osteonecrosis",
                    "required_input": "MRI T1/T2",
                    "status": "missing_input",
                    "reason": "Early disease can be radiograph-negative.",
                },
            ],
            diagnosis_scope={
                "allowed": ["state xray cannot exclude early disease"],
                "blocked": ["claim no osteonecrosis from xray alone"],
            },
            suspected_conditions=[
                {
                    "disease": "股骨头坏死",
                    "reason": "髋痛症状与上传髋部 X 光提示需按指南补充 MRI。",
                }
            ],
            required_next_images=[
                {
                    "modality": "MRI",
                    "region": "双髋关节",
                    "reason": "指南路径中早期股骨头坏死需要 MRI 评估。",
                }
            ],
            insufficiency_reasons=["X 光不足以排除早期股骨头坏死"],
        )

        payload = plan.to_dict()

        self.assertEqual(payload["analysis_status"], "insufficient_evidence")
        self.assertEqual(payload["visual_tasks"][1]["status"], "missing_input")
        self.assertEqual(payload["required_next_images"][0]["modality"], "MRI")

    def test_alignment_plan_rejects_unsupported_status(self):
        with self.assertRaisesRegex(ValueError, "unsupported alignment status"):
            AlignmentPlan(
                selected_skill="femoral_head_necrosis",
                analysis_status="unclear",
                clinical_focus="股骨头坏死",
                image_context={"modality": "xray"},
                visual_tasks=[],
                diagnosis_scope={},
            )

    def test_patient_case_input_has_single_front_door_payload(self):
        case_input = PatientCaseInput(
            patient_message="左髋疼痛三个月",
            image_path="data/images/demo_xray.png",
            patient_info={
                "age": 45,
                "sex": "male",
                "symptoms": ["髋关节疼痛"],
            },
        )

        payload = case_input.to_dict()

        self.assertEqual(payload["patient_message"], "左髋疼痛三个月")
        self.assertEqual(payload["image_path"], "data/images/demo_xray.png")
        self.assertEqual(payload["patient_info"]["symptoms"], ["髋关节疼痛"])

    def test_patient_intent_contract_supports_four_entry_routes(self):
        diagnosis = PatientIntent(
            intent_type="diagnosis",
            patient_message="左髋疼痛三个月，帮我看看片子",
            image_path="data/images/demo_xray.png",
        )
        qa = PatientIntent(
            intent_type="qa",
            patient_message="你刚才说哪里异常？",
            case_id="case_001",
        )
        review = PatientIntent(
            intent_type="review",
            patient_message="这是复查片，和上次比怎么样？",
            case_id="case_001",
            image_path="data/images/review_xray.png",
        )
        explanation = PatientIntent(
            intent_type="report_explanation",
            patient_message="解释一下刚才的报告",
            case_id="case_001",
        )

        self.assertEqual(diagnosis.to_dict()["intent_type"], "diagnosis")
        self.assertEqual(qa.to_dict()["intent_type"], "qa")
        self.assertEqual(review.to_dict()["intent_type"], "review")
        self.assertEqual(explanation.to_dict()["intent_type"], "report_explanation")
        with self.assertRaises(ValueError):
            PatientIntent(intent_type="qa", patient_message="你刚才说哪里异常？")
        with self.assertRaises(ValueError):
            PatientIntent(intent_type="diagnosis", patient_message="帮我看看片子")

    def test_skill_routing_decision_contract_marks_orchestrator_scope(self):
        decision = SkillRoutingDecision(
            selected_skill="diffuse_glioma_brats",
            selected_vision_mode="medsam2",
            source="auto",
            reason="matched brain imaging clues",
            confidence=0.75,
            matched_clues=["胶质瘤", "flair"],
        )

        payload = decision.to_dict()

        self.assertEqual(payload["agent_scope"], "orchestrator_api")
        self.assertEqual(payload["skill_builder_action"], "load_existing_skill")
        self.assertEqual(payload["selected_skill"], "diffuse_glioma_brats")
        self.assertEqual(payload["matched_clues"], ["胶质瘤", "flair"])
        self.assertNotIn("generated_skill", payload)

        with self.assertRaises(ValueError):
            SkillRoutingDecision(
                selected_skill=None,
                selected_vision_mode=None,
                source="skill_builder",
                reason="invalid owner",
                confidence=0.5,
                matched_clues=[],
            )

    def test_skill_routing_decision_contract_preserves_hypothesis_and_initial_evidence_status(self):
        decision = SkillRoutingDecision(
            selected_skill="femoral_head_necrosis",
            selected_vision_mode="no_mask_skill",
            source="auto",
            reason="matched hip xray clues",
            confidence=0.75,
            matched_clues=["髋", "xray"],
            primary_hypothesis="femoral_head_necrosis",
            differential_skill_candidates=["osteoarthritis_or_degenerative_hip_disease"],
            clinical_hypotheses=[
                {
                    "disease_key": "femoral_head_necrosis",
                    "role": "primary",
                    "status": "requires_evidence_acquisition",
                    "reason": "hip pain with xray",
                },
                {
                    "disease_key": "osteoarthritis_or_degenerative_hip_disease",
                    "role": "differential",
                    "status": "differential_candidate",
                    "reason": "hip pain can have degenerative alternatives",
                },
            ],
            skill_search_reason="Selected primary disease skill as a clinical hypothesis.",
            initial_evidence_status="requires_evidence_acquisition",
            routing_evidence_status="requires_evidence_acquisition",
        )

        payload = decision.to_dict()

        self.assertEqual(payload["primary_hypothesis"], "femoral_head_necrosis")
        self.assertEqual(
            payload["differential_skill_candidates"],
            ["osteoarthritis_or_degenerative_hip_disease"],
        )
        self.assertEqual(payload["clinical_hypotheses"][0]["role"], "primary")
        self.assertEqual(payload["clinical_hypotheses"][0]["disease_key"], "femoral_head_necrosis")
        self.assertEqual(payload["clinical_hypotheses"][1]["role"], "differential")
        self.assertEqual(payload["initial_evidence_status"], "requires_evidence_acquisition")
        self.assertEqual(payload["routing_evidence_status"], "requires_evidence_acquisition")

        with self.assertRaises(ValueError):
            SkillRoutingDecision(
                selected_skill="femoral_head_necrosis",
                selected_vision_mode="no_mask_skill",
                source="auto",
                reason="invalid evidence status",
                confidence=0.75,
                initial_evidence_status="confirmed_diagnosis",
            )

        for diagnostic_status in ("supported", "not_supported"):
            with self.subTest(diagnostic_status=diagnostic_status):
                with self.assertRaises(ValueError):
                    SkillRoutingDecision(
                        selected_skill="femoral_head_necrosis",
                        selected_vision_mode="no_mask_skill",
                        source="auto",
                        reason="routing must not encode diagnostic conclusions",
                        confidence=0.75,
                        initial_evidence_status=diagnostic_status,
                    )

    def test_visual_analysis_contract_rejects_final_diagnosis(self):
        with self.assertRaises(ValueError):
            VisualAnalysisResult.from_dict(
                {
                    "image_path": "demo.png",
                    "modality": "xray",
                    "body_part": "hip",
                    "visual_evidence": {
                        "collapse": False,
                        "diagnosis": "股骨头坏死一期",
                    },
                }
            )

    def test_visual_analysis_contract_includes_image_outputs_and_text_evidence(self):
        result = VisualAnalysisResult.from_dict(
            {
                "image_path": "data/images/brats_case_flair.nii.gz",
                "modality": "MRI",
                "body_part": "brain",
                "image_outputs": {
                    "original_image_path": "data/images/brats_case_flair.nii.gz",
                    "mask_path": "data/masks/brats_case_mask.nii.gz",
                    "overlay_path": "data/overlays/brats_case_overlay.png",
                    "comparison_path": "output/fake/brats_case_comparison.png",
                },
                "visual_evidence": {
                    "collapse": False,
                    "joint_space_narrowing": False,
                    "lesion_detected": True,
                    "lesion_location": "left temporal lobe",
                    "segmentation_quality": "good",
                    "whole_tumor_volume_ml": 35.7,
                    "tumor_core_volume_ml": 12.4,
                    "enhancing_tumor_volume_ml": 4.2,
                    "edema_present": True,
                    "mass_effect": "mild",
                    "suspected_visual_findings": ["左颞叶异常信号区"],
                },
            }
        )

        payload = result.to_dict()

        self.assertEqual(payload["image_outputs"]["mask_path"], "data/masks/brats_case_mask.nii.gz")
        self.assertEqual(
            payload["image_outputs"]["comparison_path"],
            "output/fake/brats_case_comparison.png",
        )
        self.assertEqual(payload["visual_evidence"]["lesion_location"], "left temporal lobe")
        self.assertTrue(payload["visual_evidence"]["edema_present"])

    def test_image_outputs_requires_mask_and_overlay_paths(self):
        with self.assertRaises(ValueError):
            ImageOutputs(
                original_image_path="data/images/case.nii.gz",
                mask_path="",
                overlay_path="data/overlays/case.png",
            )

    def test_lesion_gallery_contract_counts_usage_and_validates_schema(self):
        gallery = LesionGallery.from_dict(
            {
                "schema_version": "lesion_gallery.v1",
                "items": [
                    {
                        "finding_id": "finding_used",
                        "target": "sclerotic_band",
                        "display_name": "硬化带",
                        "usage": {
                            "status": "used",
                            "reason": "diagnosis fact",
                        },
                        "image_paths": {
                            "comparison_path": "output/fake/used_comparison.png",
                        },
                    },
                    {
                        "finding_id": "finding_excluded",
                        "target": "cystic_change",
                        "display_name": "囊性变",
                        "usage": {
                            "status": "excluded",
                            "reason": "non_independent_evidence",
                        },
                        "image_paths": {
                            "comparison_path": "output/fake/excluded_comparison.png",
                        },
                    },
                    {
                        "finding_id": "finding_candidate",
                        "target": "collapse",
                        "usage": {
                            "status": "candidate",
                            "reason": "not yet audited",
                        },
                        "image_paths": {},
                    },
                ],
            }
        )

        payload = gallery.to_dict()

        self.assertEqual(payload["schema_version"], "lesion_gallery.v1")
        self.assertEqual(payload["used_count"], 1)
        self.assertEqual(payload["excluded_count"], 1)
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(
            payload["items"][1]["image_paths"]["comparison_path"],
            "output/fake/excluded_comparison.png",
        )
        with self.assertRaisesRegex(ValueError, "unsupported lesion gallery usage status"):
            LesionGallery(
                items=[
                    {
                        "finding_id": "finding_bad",
                        "usage": {"status": "maybe"},
                    }
                ]
            )

    def test_visual_evidence_contract_keeps_quantitative_fields_separate(self):
        evidence = VisualEvidence(
            femoral_head_shape="基本完整",
            collapse=False,
            sclerosis="疑似轻度",
            cystic_change="未明确",
            joint_space_narrowing=False,
            joint_space="未明显狭窄",
            lesion_mask="not_generated_in_mvp",
            confidence=0.78,
            texture_abnormality_score=0.74,
            lesion_area_ratio=0.13,
            collapse_ratio=0.0,
            joint_space_width="preserved",
            suspected_visual_findings=["股骨头负重区纹理异常"],
        )

        payload = evidence.to_dict()

        self.assertNotIn("diagnosis", payload)
        self.assertEqual(payload["texture_abnormality_score"], 0.74)
        self.assertEqual(payload["suspected_visual_findings"], ["股骨头负重区纹理异常"])

    def test_visual_evidence_contract_supports_protocol_measurements_and_completeness(self):
        result = VisualAnalysisResult.from_dict(
            {
                "image_path": "data/images/brats_case_flair.nii.gz",
                "modality": "MRI",
                "body_part": "brain",
                "image_outputs": {
                    "original_image_path": "data/images/brats_case_flair.nii.gz",
                    "mask_path": "data/masks/brats_case_mask.nii.gz",
                    "overlay_path": "data/overlays/brats_case_overlay.png",
                },
                "visual_evidence": {
                    "collapse": False,
                    "joint_space_narrowing": False,
                    "disease_target": "diffuse_glioma_adult",
                    "measurements": {
                        "whole_tumor_volume_ml": 35.7,
                        "enhancing_tumor_volume_ml": None,
                    },
                    "completeness": {
                        "whole_tumor": {
                            "status": "supported",
                            "reason": "FLAIR modality available",
                        },
                        "enhancing_tumor": {
                            "status": "missing",
                            "reason": "Requires T1ce modality",
                        },
                    },
                },
            }
        )

        payload = result.to_dict()

        self.assertEqual(payload["visual_evidence"]["disease_target"], "diffuse_glioma_adult")
        self.assertIsNone(payload["visual_evidence"]["measurements"]["enhancing_tumor_volume_ml"])
        self.assertEqual(
            payload["visual_evidence"]["completeness"]["enhancing_tumor"]["status"],
            "missing",
        )

    def test_visual_evidence_contract_preserves_structured_findings(self):
        result = VisualAnalysisResult.from_dict(
            {
                "image_path": "data/images/hip_ap.png",
                "modality": "X-ray",
                "body_part": "hip",
                "image_outputs": {
                    "original_image_path": "data/images/hip_ap.png",
                    "mask_path": "output/fake/sclerotic_band_mask.png",
                    "overlay_path": "output/fake/sclerotic_band_overlay.png",
                },
                "visual_evidence": {
                    "collapse": False,
                    "joint_space_narrowing": False,
                    "disease_target": "femoral_head_necrosis",
                    "findings": [
                        {
                            "finding_id": "f1",
                            "target": "sclerotic_band",
                            "display_name": "硬化带",
                            "status": "candidate_present",
                            "regions": [
                                {
                                    "region_id": "r1",
                                    "mask_path": "output/fake/sclerotic_band_mask.png",
                                    "overlay_path": "output/fake/sclerotic_band_overlay.png",
                                    "bbox": [120, 240, 190, 310],
                                    "centroid": [155.2, 276.8],
                                    "area_px": 1380,
                                    "area_ratio_in_image": 0.006,
                                    "area_ratio_in_anatomy": 0.12,
                                    "laterality": "left",
                                    "anatomical_zone": "superolateral_femoral_head",
                                }
                            ],
                            "confidence": 0.74,
                            "measurements": {
                                "relative_density_score": 0.27,
                                "elongation": 3.8,
                            },
                            "diagnosis_usable": True,
                        }
                    ],
                    "structured_visual_facts": [
                        {
                            "finding_id": "f1",
                            "target": "sclerotic_band",
                            "display_name": "硬化带",
                            "status": "candidate_present",
                            "laterality": "left",
                            "diagnosis_usable": True,
                            "independent_evidence": True,
                            "area_px": 1380,
                            "alignment_status": "aligned",
                        }
                    ],
                },
            }
        )

        visual_input = DiagnosisVisualInput.from_visual_result(result.to_dict()).to_dict()

        finding = visual_input["findings"][0]
        self.assertEqual(finding["target"], "sclerotic_band")
        self.assertEqual(finding["regions"][0]["area_ratio_in_anatomy"], 0.12)
        self.assertEqual(
            visual_input["visual_evidence"]["findings"][0]["display_name"],
            "硬化带",
        )
        self.assertEqual(
            visual_input["structured_visual_facts"][0]["alignment_status"],
            "aligned",
        )

    def test_diagnosis_visual_input_contract_preserves_outputs_and_completeness(self):
        visual_input = DiagnosisVisualInput.from_visual_result(
            {
                "image_path": "data/images/brats_case_flair.nii.gz",
                "modality": "MRI",
                "body_part": "brain",
                "image_outputs": {
                    "original_image_path": "data/images/brats_case_flair.nii.gz",
                    "mask_path": "output/fake/case_mask.nii.gz",
                    "overlay_path": "output/fake/case_overlay.png",
                },
                "visual_evidence": {
                    "collapse": False,
                    "joint_space_narrowing": False,
                    "disease_target": "diffuse_glioma_adult",
                    "measurements": {
                        "whole_tumor_volume_ml": 117.9,
                        "enhancing_tumor_volume_ml": None,
                    },
                    "completeness": {
                        "whole_tumor": {
                            "status": "supported",
                            "reason": "FLAIR modality available",
                        },
                        "enhancing_tumor": {
                            "status": "missing",
                            "reason": "Requires T1ce modality",
                        },
                    },
                    "segmentation_quality": "medsam2",
                },
            }
        ).to_dict()

        self.assertEqual(
            visual_input["image_outputs"]["overlay_path"],
            "output/fake/case_overlay.png",
        )
        self.assertIsNone(visual_input["measurements"]["enhancing_tumor_volume_ml"])
        self.assertEqual(
            visual_input["completeness"]["enhancing_tumor"]["status"],
            "missing",
        )
        self.assertEqual(visual_input["segmentation_quality"], "medsam2")
        self.assertNotIn("diagnosis", visual_input)

    def test_visual_task_contract_is_derived_from_skill_protocol_task(self):
        task = VisualTask.from_protocol_task(
            {
                "task": "segment_whole_tumor",
                "required_modalities": ["FLAIR"],
                "reason": "whole tumor 主要依赖 FLAIR 可见范围。",
            },
            measurements=["whole_tumor_volume_ml", "max_diameter_mm"],
        )

        payload = task.to_dict()

        self.assertEqual(payload["task_name"], "segment_whole_tumor")
        self.assertEqual(payload["target"], "whole_tumor")
        self.assertEqual(payload["required_modalities"], ["FLAIR"])
        self.assertEqual(payload["output"], "mask")
        self.assertEqual(payload["measurements"], ["whole_tumor_volume_ml", "max_diameter_mm"])

    def test_visual_tool_capability_contract_declares_supported_tasks_and_modalities(self):
        capability = VisualToolCapability(
            tool_name="medsam2",
            supported_modalities=["MRI", "CT", "Xray", "PNG"],
            supported_tasks=["generic_lesion_candidate"],
            output="binary_mask",
            priority=50,
            role="candidate_segmenter",
        )

        payload = capability.to_dict()

        self.assertTrue(capability.supports(modality="MRI", task_name="segment_whole_tumor"))
        self.assertEqual(payload["role"], "candidate_segmenter")
        self.assertEqual(payload["supported_tasks"], ["generic_lesion_candidate"])

    def test_segmentation_result_contract_blocks_low_quality_from_diagnosis(self):
        result = SegmentationResult(
            task_name="segment_whole_tumor",
            target="whole_tumor",
            status="low_quality",
            mask_path="output/fake/case_mask.nii.gz",
            overlay_path="output/fake/case_overlay.png",
            measurements={"whole_tumor_volume_ml": 117.9},
            quality={
                "score": 0.21,
                "level": "low",
                "warnings": ["mask is unstable across prompts"],
            },
            completeness={
                "status": "unassessed",
                "reason": "Segmentation did not pass QC",
            },
        )

        payload = result.to_dict()

        self.assertFalse(payload["diagnosis_usable"])
        self.assertEqual(payload["status"], "low_quality")
        self.assertIn("mask is unstable", payload["quality"]["warnings"][0])

    def test_segmentation_result_rejects_unsupported_status(self):
        with self.assertRaisesRegex(ValueError, "unsupported segmentation status"):
            SegmentationResult(
                task_name="segment_whole_tumor",
                target="whole_tumor",
                status="almost_done",
                mask_path="not_generated",
                overlay_path="not_generated",
            )

    def test_skill_descriptor_enforces_guideline_vs_hypothesis_boundary(self):
        guideline = SkillDescriptor(
            disease="股骨头坏死",
            skill_id="femoral_head_necrosis_v0.1",
            skill_type="guideline_based",
            evidence_level="high",
            source="ARCO 分期相关公开医学知识整理",
            path_type="guideline_aware",
        )
        hypothesis = SkillDescriptor(
            disease="罕见病示例",
            skill_id="rare_disease_demo_hypothesis_v0.1",
            skill_type="data_mined_hypothesis",
            evidence_level="low",
            source="internal dataset statistical summary",
            warning="该规则来自数据总结，不等同于正式医学指南，只能作为辅助提示",
            path_type="privileged_knowledge_discovery",
            safety_gate={"mode_required": "hypothesis_validation"},
            discovery_metadata={"sample_size": 12},
        )

        self.assertEqual(guideline.to_dict()["evidence_level"], "high")
        self.assertIn("不等同于正式医学指南", hypothesis.to_dict()["warning"])
        self.assertEqual(hypothesis.to_dict()["path_type"], "privileged_knowledge_discovery")
        self.assertEqual(
            hypothesis.to_dict()["safety_gate"]["mode_required"],
            "hypothesis_validation",
        )
        self.assertEqual(hypothesis.to_dict()["discovery_metadata"]["sample_size"], 12)
        with self.assertRaises(ValueError):
            SkillDescriptor(
                disease="错误示例",
                skill_id="bad_v0.1",
                skill_type="data_mined_hypothesis",
                evidence_level="high",
                source="internal dataset statistical summary",
            )

    def test_skill_descriptor_preserves_guideline_citations(self):
        descriptor = SkillDescriptor.from_skill(
            {
                "disease_name": "成人弥漫性胶质瘤",
                "skill_id": "diffuse_glioma_guideline_v0.1",
                "skill_type": "guideline_based",
                "evidence_level": "high",
                "source": "EANO guideline",
                "path_type": "guideline_aware",
                "source_documents": [
                    {
                        "title": "EANO guideline",
                        "url": "https://example.org/eano",
                        "source_id": "eano_guideline",
                    }
                ],
                "guideline_source": {
                    "source_catalog_path": "data/guidelines/guideline_sources.json",
                },
                "guideline_extraction": {
                    "tool": "GuidelineExtractionTool",
                    "citations": [
                        {
                            "title": "EANO guideline",
                            "url": "https://example.org/eano",
                            "source_kind": "official_guideline",
                            "evidence_note": "MRI recommendation",
                        }
                    ],
                },
                "source_priority": [
                    {
                        "source_id": "eano_guideline",
                        "publication_year": "2021",
                        "region": "global",
                    }
                ],
                "guideline_conflicts": [
                    {
                        "field": "required_image_views",
                        "status": "conflict",
                        "resolution": "merged_union_review_required",
                    }
                ],
            }
        ).to_dict()

        self.assertEqual(
            descriptor["guideline_source"]["source_catalog_path"],
            "data/guidelines/guideline_sources.json",
        )
        self.assertEqual(descriptor["source_documents"][0]["source_id"], "eano_guideline")
        self.assertEqual(
            descriptor["guideline_extraction"]["citations"][0]["url"],
            "https://example.org/eano",
        )
        self.assertEqual(descriptor["source_priority"][0]["publication_year"], "2021")
        self.assertEqual(descriptor["guideline_conflicts"][0]["field"], "required_image_views")


if __name__ == "__main__":
    unittest.main()
