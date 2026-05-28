import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agents.gaodoctor_agent import GaoDoctorAgent
from api.service import MedScopeService
from api.http_server import (
    dispatch_binary_request,
    dispatch_demo_request,
    dispatch_http_request,
    dispatch_skill_request,
    dispatch_static_request,
    handle_file_upload,
    resolve_public_output_path,
)
from memory.memory_manager import MemoryManager


REAL_SAMPLE_DIR = Path("data/external/brats2021_00030")
REAL_IMAGE = REAL_SAMPLE_DIR / "BraTS2021_00030_flair.nii.gz"
REAL_MASK = REAL_SAMPLE_DIR / "BraTS2021_00030_seg.nii.gz"


class FakeService:
    def __init__(self):
        self.payloads = []

    def handle_request(self, payload):
        self.payloads.append(payload)
        if not payload.get("patient_message"):
            raise ValueError("patient_message is required")
        return {
            "case_id": payload.get("case_id") or "case_http",
            "intent": "qa" if payload.get("case_id") else "diagnosis",
            "reply_to_patient": "ok",
        }


class FakeGaoDoctor:
    def __init__(self):
        self.calls = []

    def handle_message(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "case_id": kwargs.get("case_id") or "case_http",
            "intent": "diagnosis",
            "reply_to_patient": "ok",
        }


class HttpEntrypointTest(unittest.TestCase):
    def test_health_endpoint_returns_ok(self):
        status, payload = dispatch_http_request(
            method="GET",
            path="/health",
            service_factory=FakeService,
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_root_serves_interactive_frontend(self):
        status, body, content_type = dispatch_static_request("/")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("MedScope Agent", text)
        self.assertIn("/static/app.js", text)
        self.assertIn("dropZone", text)
        self.assertIn("医疗影像", text)
        self.assertIn("visualPanel", text)
        self.assertIn("alignmentPanel", text)
        self.assertIn("Evidence Pipeline Trace", text)
        self.assertIn("alignmentView", text)
        self.assertIn("evidencePanel", text)
        self.assertIn("auditPanel", text)
        self.assertIn("qaSubmitButton", text)
        self.assertIn("一键标准样例", text)
        self.assertIn("X 光证据不足样例", text)
        self.assertIn("FHN no-mask 多征象样例", text)
        self.assertIn("Evidence Gateway 快照", text)
        self.assertIn("真实 VLM+MedSAM2 样例", text)
        self.assertNotIn("调试 JSON", text)
        self.assertNotIn("图像路径", text)
        self.assertNotIn("Mask 路径", text)
        self.assertNotIn("视觉模式", text)
        self.assertNotIn("疾病 Skill", text)

    def test_static_frontend_assets_are_served_from_allowlist(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        self.assertIn(b"/v1/medscope", body)
        self.assertIn(b"action_items", body)
        self.assertIn(b"error_type", body)
        self.assertIn(b"guideline_evidence", body)
        self.assertIn(b"renderGuidelineEvidence", body)
        self.assertIn(b"renderGuidelineConflicts", body)
        self.assertIn(b"renderSourcePriority", body)
        self.assertIn(b"renderEvidenceBundle", body)
        self.assertIn(b"renderVisualEvidenceBundle", body)
        self.assertIn(b"renderSegmentationResults", body)
        self.assertIn(b"renderVisualToolPlan", body)
        self.assertIn("分割任务结果".encode("utf-8"), body)
        self.assertIn("视觉工具计划".encode("utf-8"), body)
        self.assertIn("诊断可用".encode("utf-8"), body)
        self.assertIn(b"renderVisualFactUsage", body)
        self.assertIn(b"renderLesionComparison", body)
        self.assertIn(b"buildVisualComparisonItems", body)
        self.assertIn(b"original_preview_path", body)
        self.assertIn(b"slice_png_path", body)
        self.assertIn(b"bbox_overlay_path", body)
        self.assertIn(b"mask_preview_path", body)
        self.assertIn("原图".encode("utf-8"), body)
        self.assertIn("分割病灶".encode("utf-8"), body)
        self.assertIn("对比叠加".encode("utf-8"), body)
        self.assertIn("诊断采用证据".encode("utf-8"), body)
        self.assertIn("排除证据".encode("utf-8"), body)
        self.assertIn(b"visual_fact_usage", body)
        self.assertIn(b"excluded_count", body)
        self.assertIn(b"renderFindingList", body)
        self.assertIn(b"present_findings", body)
        self.assertIn(b"numeric_evidence", body)
        self.assertIn(b"anatomy_match", body)
        self.assertIn(b"overlap_anatomy_px", body)
        self.assertIn(b"renderMemoryAudit", body)
        self.assertIn(b"renderMemoryRoleSummary", body)
        self.assertIn(b"renderMemoryTypeDetails", body)
        self.assertIn(b"renderTraceConsistency", body)
        self.assertIn("Trace Consistency".encode("utf-8"), body)
        self.assertIn(b"renderMemoryReplay", body)
        self.assertIn(b"renderRuntimeManifest", body)
        self.assertIn("Runtime Manifest".encode("utf-8"), body)
        self.assertIn("Evidence Gateway".encode("utf-8"), body)
        self.assertIn(b"runtime_manifest", body)
        self.assertIn(b"runtime_manifest_path", body)
        self.assertIn(b"renderStopHookGate", body)
        self.assertIn("Stop Hook Gate".encode("utf-8"), body)
        self.assertIn(b"stop_hook_gate", body)
        self.assertIn(b"stop_hook_gate_path", body)
        self.assertIn(b"renderSelfEvolvingQueue", body)
        self.assertIn("Self-evolving Queue".encode("utf-8"), body)
        self.assertIn(b"self_evolving_queue", body)
        self.assertIn(b"self_evolving_queue_path", body)
        self.assertIn(b"renderCandidateValidationGate", body)
        self.assertIn("Candidate Validation Gate".encode("utf-8"), body)
        self.assertIn(b"candidate_validation_gate", body)
        self.assertIn(b"candidate_validation_gate_path", body)
        self.assertIn(b"renderRuntimeGatewayTrace", body)
        self.assertIn("Runtime Gateway Trace".encode("utf-8"), body)
        self.assertIn(b"runtime_gateway_trace", body)
        self.assertIn(b"runtime_gateway_trace_path", body)
        self.assertIn(b"all_stage_artifacts_available", body)
        self.assertIn(b"all_stage_schemas_present", body)
        self.assertIn(b"renderAgentFlowSummary", body)
        self.assertIn("临床证据流水线".encode("utf-8"), body)
        self.assertIn("3 个核心 Agent".encode("utf-8"), body)
        self.assertIn("Memory/Audit 基础设施层".encode("utf-8"), body)
        self.assertIn("临床编排 / 入口分诊".encode("utf-8"), body)
        self.assertIn("条件 Skill 构建 / 加载".encode("utf-8"), body)
        self.assertIn("视觉证据提取".encode("utf-8"), body)
        self.assertIn("证据约束诊断推理".encode("utf-8"), body)
        self.assertIn("Memory / Audit Layer".encode("utf-8"), body)
        self.assertIn("实现节点 Trace".encode("utf-8"), body)
        self.assertIn("Agent / Layer I/O".encode("utf-8"), body)
        self.assertIn(b"GaoDoctorAgent QA", body)
        self.assertIn("追问回答".encode("utf-8"), body)
        self.assertIn("基于已有 evidence bundle 回答追问".encode("utf-8"), body)
        self.assertIn("患者输入".encode("utf-8"), body)
        self.assertIn("图像与视觉证据".encode("utf-8"), body)
        self.assertIn("Skill / 指南 / 路由".encode("utf-8"), body)
        self.assertIn("诊断推理与报告".encode("utf-8"), body)
        self.assertIn(b"renderSkillQuality", body)
        self.assertIn(b"renderQaSafety", body)
        self.assertIn(b"evidence_bundle_used_count", body)
        self.assertIn(b"evidence_bundle_used_count: 0", body)
        self.assertIn(b"renderAlignmentPlan", body)
        self.assertIn(b"memory_replay", body)
        self.assertIn(b"replay_consistency", body)
        self.assertIn(b"memory_scope_complete", body)
        self.assertIn(b"comparison_path", body)
        self.assertIn(b"renderCandidateLesionGallery", body)
        self.assertIn(b"getLesionGalleryItems", body)
        self.assertIn(b"lesion_gallery", body)
        self.assertIn(b"lesion_gallery_summary", body)
        self.assertIn(b"lesion_gallery_status", body)
        self.assertIn("候选病灶证据".encode("utf-8"), body)
        self.assertIn("诊断采用".encode("utf-8"), body)
        self.assertIn("排除".encode("utf-8"), body)
        self.assertIn(b"memory_scope", body)
        self.assertIn(b"patient_memory.qa_history", body)
        self.assertIn(b'event: "patient_intake"', body)
        self.assertIn(b"used_visual_targets", body)
        self.assertIn(b"excluded_visual_targets", body)
        self.assertIn(b"visual_fact_usage_summary", body)
        self.assertIn(b"qa_evidence_scope", body)
        self.assertIn(b'event: "skill_loading"', body)
        self.assertIn(b'event: "vlm_prompt_generation"', body)
        self.assertIn(b'tool: "VLM Prompt"', body)
        self.assertIn(b'tool: "MedSAM2"', body)
        self.assertIn(b'agent: "MemoryManager"', body)
        self.assertIn(b'event: "memory_audit"', body)
        self.assertIn(b"agent_io_summary", body)
        self.assertIn(b"evidence_bundle_status", body)
        self.assertIn(b"decision_owner", body)
        self.assertIn(b"skill_builder_action", body)
        self.assertIn(b"routing_source", body)
        self.assertIn(b'decision_owner: "orchestrator_api"', body)
        self.assertNotIn(b'agent: "Skill Builder", event: "skill_routing"', body)
        self.assertNotIn(b"Skill/VLM prompt", body)
        self.assertIn(b"/v1/memory/cases/", body)
        self.assertIn(b"visual_protocol_status", body)
        self.assertIn(b"qa_safety", body)
        self.assertIn(b"memory_type_details", body)
        self.assertIn(b"runStandardSample", body)
        self.assertIn(b"runRealVlmMedSAM2Sample", body)
        self.assertIn(b"runXrayInsufficientSample", body)
        self.assertIn(b"runFhnNoMaskSample", body)
        self.assertIn(b"runEvidenceGatewaySnapshot", body)
        self.assertIn(b"fetchEvidenceGatewaySnapshot", body)
        self.assertIn(b"renderEvidenceGatewaySnapshot", body)
        self.assertIn("Evidence Gateway 快照".encode("utf-8"), body)
        self.assertIn(b"/v1/demo/evidence-gateway-snapshot", body)
        self.assertIn(b"/v1/demo/standard", body)
        self.assertIn(b"/v1/demo/real-vlm-medsam2", body)
        self.assertIn(b"/v1/demo/real-vlm-medsam2/response", body)
        self.assertIn(b"/v1/demo/real-vlm-medsam2/qa", body)
        self.assertIn(b"fetchRealVlmMedSAM2Demo", body)
        self.assertIn(b"fetchRealVlmMedSAM2Response", body)
        self.assertIn(b"buildRealVlmMedSAM2Payload", body)
        self.assertIn(b"postRealVlmMedSAM2Qa", body)
        self.assertIn(b"fetchStandardDemoCase", body)
        self.assertIn(b"postDemoQa", body)
        self.assertIn(b"/v1/demo/standard/cases/", body)
        self.assertIn(b"/qa", body)
        self.assertIn(b"demoCaseSlug", body)
        self.assertIn(b"no_mask_skill", body)
        self.assertIn(b"femoral_head_necrosis", body)
        self.assertIn(b"alignment_plan", body)
        self.assertIn(b"insufficient_evidence", body)
        self.assertIn(b"qaPending", body)
        self.assertIn(b"casePending", body)
        self.assertIn(b"setQaPending", body)
        self.assertIn(b"setCasePending", body)
        self.assertIn(b"showQaThinking", body)
        self.assertIn(b"showCaseThinking", body)
        self.assertIn(b"Thinking", body)
        self.assertIn(b"fetchSkillList", body)
        self.assertIn(b"renderSkillReviewWorkspace", body)
        self.assertIn(b"saveSkillReviewDraft", body)
        self.assertIn("Skill 审核".encode("utf-8"), body)
        self.assertIn("医生审核".encode("utf-8"), body)
        self.assertIn("保存草稿".encode("utf-8"), body)
        self.assertNotIn(b"rawJson", body)

    def test_static_frontend_rejects_unknown_asset(self):
        status, payload = dispatch_http_request(
            method="GET",
            path="/static/unknown.js",
            service_factory=FakeService,
        )

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "not found")

    def test_upload_writes_file_to_output_fake_uploads(self):
        with TemporaryDirectory() as tmpdir:
            status, payload = handle_file_upload(
                filename="scan.nii.gz",
                body=b"fake-nifti",
                upload_root=Path(tmpdir),
            )

            self.assertEqual(status, 200)
            uploaded_path = Path(payload["image_path"])
            self.assertEqual(uploaded_path.name, "scan.nii.gz")
            self.assertIn("output/fake/uploads", payload["image_path"])
            self.assertEqual(uploaded_path.read_bytes(), b"fake-nifti")

    def test_upload_rejects_empty_file(self):
        status, payload = handle_file_upload(filename="scan.nii.gz", body=b"")

        self.assertEqual(status, 400)
        self.assertIn("empty", payload["error"])

    def test_skill_list_returns_doctor_friendly_summaries(self):
        with TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir) / "skills"
            skills_dir.mkdir()
            (skills_dir / "fhn.yaml").write_text(
                json.dumps(
                    {
                        "disease_name": "股骨头坏死",
                        "skill_id": "fhn_v0.1",
                        "skill_type": "guideline_based",
                        "evidence_level": "high",
                        "source": "临床指南",
                        "clinical_features": {"common_symptoms": ["髋痛"]},
                        "required_image_views": ["双髋 X 光", "MRI"],
                        "visual_protocol": {
                            "finding_targets": [
                                {"target": "sclerotic_band", "display_name": "硬化带"},
                                {"target": "collapse", "display_name": "股骨头塌陷"},
                            ]
                        },
                        "source_documents": [{"title": "ONFH guideline", "url": "https://example.test"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status, payload = dispatch_skill_request(
                method="GET",
                path="/v1/skills",
                skills_dir=skills_dir,
                output_root=Path(tmpdir) / "output",
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["count"], 1)
            summary = payload["skills"][0]
            self.assertEqual(summary["skill_key"], "fhn")
            self.assertEqual(summary["disease_name"], "股骨头坏死")
            self.assertEqual(summary["doctor_summary"]["symptom_count"], 1)
            self.assertEqual(summary["doctor_summary"]["image_requirement_count"], 2)
            self.assertEqual(summary["doctor_summary"]["visual_finding_count"], 2)
            self.assertEqual(summary["review_status"], "no_draft")

    def test_skill_detail_translates_skill_to_doctor_review_sections(self):
        with TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir) / "skills"
            skills_dir.mkdir()
            (skills_dir / "fhn.yaml").write_text(
                json.dumps(
                    {
                        "disease_name": "股骨头坏死",
                        "skill_id": "fhn_v0.1",
                        "skill_type": "guideline_based",
                        "evidence_level": "high",
                        "source": "临床指南",
                        "clinical_features": {
                            "common_symptoms": ["髋痛", "活动受限"],
                            "risk_factors": ["激素使用史"],
                        },
                        "required_image_views": ["双髋正位 X 光", "MRI T1/T2/STIR"],
                        "staging_rules": {
                            "ARCO_II": {
                                "description": "X 光硬化或囊变，无塌陷",
                                "xray_features": ["硬化影", "囊性改变"],
                            }
                        },
                        "visual_protocol": {
                            "finding_targets": [
                                {
                                    "target": "sclerotic_band",
                                    "display_name": "硬化带",
                                    "description": "股骨头内带状密度增高",
                                    "execution_mode": "vlm_plus_segmenter",
                                    "required_modalities": ["X-ray"],
                                }
                            ],
                            "insufficiency_rules": [
                                {"reason": "X 光不能排除早期病变"}
                            ],
                            "required_next_images": [
                                {"modality": "MRI", "region": "双髋", "reason": "评估早期坏死"}
                            ],
                        },
                        "source_documents": [{"title": "ONFH guideline", "url": "https://example.test"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status, payload = dispatch_skill_request(
                method="GET",
                path="/v1/skills/fhn",
                skills_dir=skills_dir,
                output_root=Path(tmpdir) / "output",
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["skill_key"], "fhn")
            self.assertEqual(payload["doctor_view"]["identity"]["disease_name"], "股骨头坏死")
            self.assertEqual(payload["doctor_view"]["clinical_profile"]["common_symptoms"], ["髋痛", "活动受限"])
            self.assertEqual(payload["doctor_view"]["imaging_requirements"][0]["label"], "双髋正位 X 光")
            self.assertEqual(payload["doctor_view"]["visual_findings"][0]["display_name"], "硬化带")
            self.assertEqual(payload["doctor_view"]["visual_findings"][0]["doctor_execution_label"], "先定位候选区域，再生成候选分割")
            self.assertEqual(payload["doctor_view"]["staging_rules"][0]["stage"], "ARCO_II")
            self.assertEqual(payload["doctor_view"]["safety_notes"][0]["reason"], "X 光不能排除早期病变")
            self.assertEqual(payload["doctor_view"]["source_documents"][0]["title"], "ONFH guideline")
            self.assertFalse(payload["draft"]["exists"])

    def test_skill_review_draft_is_saved_under_output_fake_without_overwriting_formal_skill(self):
        with TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir) / "skills"
            output_root = Path(tmpdir) / "output"
            skills_dir.mkdir()
            skill_path = skills_dir / "fhn.yaml"
            formal_skill = {
                "disease_name": "股骨头坏死",
                "skill_id": "fhn_v0.1",
                "skill_type": "guideline_based",
                "evidence_level": "high",
                "source": "临床指南",
                "clinical_features": {"common_symptoms": ["髋痛"]},
                "visual_protocol": {"finding_targets": []},
            }
            skill_path.write_text(json.dumps(formal_skill, ensure_ascii=False), encoding="utf-8")

            status, payload = dispatch_skill_request(
                method="POST",
                path="/v1/skills/fhn/review-draft",
                body=json.dumps(
                    {
                        "reviewer_name": "张医生",
                        "sections": {
                            "clinical_profile": {
                                "common_symptoms": ["髋痛", "跛行"]
                            },
                            "review_notes": "建议补充 MRI 阴性不能排除早期病变的说明",
                        },
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                skills_dir=skills_dir,
                output_root=output_root,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "draft_saved")
            self.assertEqual(payload["formal_skill_updated"], False)
            draft_path = Path(payload["draft_path"])
            self.assertIn("output/fake/skill_review_drafts", payload["draft_path"])
            self.assertTrue(draft_path.exists())
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual(draft["reviewer_name"], "张医生")
            self.assertEqual(draft["sections"]["clinical_profile"]["common_symptoms"], ["髋痛", "跛行"])
            self.assertEqual(json.loads(skill_path.read_text(encoding="utf-8")), formal_skill)

    def test_public_output_route_serves_only_output_files(self):
        with TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            image_path = output_root / "fake" / "overlay.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"png-bytes")

            resolved = resolve_public_output_path(
                "/output/fake/overlay.png",
                output_root=output_root,
            )

            self.assertEqual(resolved.resolve(), image_path.resolve())

    def test_public_output_route_rejects_path_escape(self):
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                resolve_public_output_path(
                    "/output/../data/cases/private.json",
                    output_root=Path(tmpdir) / "output",
                )

    def test_binary_dispatch_serves_output_file(self):
        with TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            file_path = output_root / "fake" / "overlay.png"
            file_path.parent.mkdir(parents=True)
            file_path.write_bytes(b"png-bytes")

            status, body, content_type = dispatch_binary_request(
                "GET",
                "/output/fake/overlay.png",
                output_root=output_root,
            )

            self.assertEqual(status, 200)
            self.assertEqual(body, b"png-bytes")
            self.assertEqual(content_type, "image/png")

    def test_get_memory_cases_returns_recent_case_summaries(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            memory.save_case_memory(
                case_id="case_http_memory",
                patient_memory={
                    "patient_id": "patient_http",
                    "patient_message": "请分析",
                    "patient_info": {"symptoms": ["头痛"]},
                    "symptoms": ["头痛"],
                    "intent": "diagnosis",
                },
                image_memory={"image_path": "scan.nii.gz", "modality": "MRI", "body_part": "brain"},
                skill_memory={"selected_skill": "diffuse_glioma_brats"},
                reasoning_memory={"diagnostic_tendency": "测试诊断"},
            )

            status, payload = dispatch_http_request(
                method="GET",
                path="/v1/memory/cases?limit=5",
                memory_factory=lambda: memory,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["cases"][0]["case_id"], "case_http_memory")
            self.assertEqual(payload["cases"][0]["patient_id"], "patient_http")
            self.assertNotIn("patient_message", payload["cases"][0])

    def test_get_memory_case_replay_bundle_and_audit(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            memory.save_case_memory(
                case_id="case_http_memory",
                patient_memory={
                    "patient_id": "patient_http",
                    "patient_message": "请分析",
                    "patient_info": {"symptoms": ["头痛"]},
                    "symptoms": ["头痛"],
                    "intent": "diagnosis",
                },
                image_memory={
                    "image_path": "scan.nii.gz",
                    "modality": "MRI",
                    "body_part": "brain",
                    "visual_evidence": {
                        "segmentation_quality": "ground_truth_nifti",
                        "measurements": {"whole_tumor_volume_ml": 12.3},
                    },
                },
                skill_memory={"selected_skill": "diffuse_glioma_brats"},
                reasoning_memory={"diagnostic_tendency": "测试诊断"},
            )

            replay_status, replay = dispatch_http_request(
                method="GET",
                path="/v1/memory/cases/case_http_memory/replay",
                memory_factory=lambda: memory,
            )
            bundle_status, bundle = dispatch_http_request(
                method="GET",
                path="/v1/memory/cases/case_http_memory/evidence-bundle",
                memory_factory=lambda: memory,
            )
            audit_status, audit = dispatch_http_request(
                method="GET",
                path="/v1/memory/cases/case_http_memory/audit",
                memory_factory=lambda: memory,
            )

            self.assertEqual(replay_status, 200)
            self.assertEqual(replay["case_id"], "case_http_memory")
            self.assertEqual(replay["steps"][0]["agent"], "GaoDoctorAgent")
            self.assertEqual(bundle_status, 200)
            self.assertEqual(bundle["case_id"], "case_http_memory")
            self.assertEqual(audit_status, 200)
            self.assertEqual(audit["case_id"], "case_http_memory")

    def test_demo_summary_and_case_artifacts_are_served_from_output_fake(self):
        with TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            demo_dir = output_root / "fake" / "standard_demo_with_fhn_no_mask_qc"
            artifacts_dir = demo_dir / "cases" / "fhn_no_mask_multifinding" / "artifacts"
            artifacts_dir.mkdir(parents=True)
            (demo_dir / "standard_demo_summary.json").write_text(
                json.dumps(
                    {
                        "demo_name": "medscope_standard_demo_suite",
                        "cases": [{"case_name": "fhn_no_mask_multifinding"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "fhn_no_mask_multifinding_response.json").write_text(
                json.dumps({"case_id": "case_demo", "image_outputs": {"overlay_path": "x.png"}}),
                encoding="utf-8",
            )
            (artifacts_dir / "fhn_no_mask_multifinding_evidence_bundle.json").write_text(
                json.dumps({"case_id": "case_demo", "reasoning_evidence": {}}),
                encoding="utf-8",
            )
            (artifacts_dir / "fhn_no_mask_multifinding_audit.json").write_text(
                json.dumps({"case_id": "case_demo", "memory_completeness": {}}),
                encoding="utf-8",
            )

            summary_status, summary = dispatch_demo_request(
                method="GET",
                path="/v1/demo/standard",
                output_root=output_root,
            )
            response_status, response = dispatch_demo_request(
                method="GET",
                path="/v1/demo/standard/cases/fhn_no_mask_multifinding/response",
                output_root=output_root,
            )
            bundle_status, bundle = dispatch_demo_request(
                method="GET",
                path="/v1/demo/standard/cases/fhn_no_mask_multifinding/evidence-bundle",
                output_root=output_root,
            )
            audit_status, audit = dispatch_demo_request(
                method="GET",
                path="/v1/demo/standard/cases/fhn_no_mask_multifinding/audit",
                output_root=output_root,
            )

            self.assertEqual(summary_status, 200)
            self.assertEqual(summary["demo_name"], "medscope_standard_demo_suite")
            self.assertEqual(response_status, 200)
            self.assertEqual(response["case_id"], "case_demo")
            self.assertIn("image_outputs", response)
            self.assertEqual(bundle_status, 200)
            self.assertEqual(bundle["case_id"], "case_demo")
            self.assertIn("reasoning_evidence", bundle)
            self.assertEqual(audit_status, 200)
            self.assertEqual(audit["case_id"], "case_demo")
            self.assertIn("memory_completeness", audit)

    def test_evidence_gateway_snapshot_demo_is_served_from_output_fake(self):
        with TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            snapshot_path = output_root / "fake" / "evidence_gateway_snapshot.json"
            snapshot_path.parent.mkdir(parents=True)
            snapshot_path.write_text(
                json.dumps(
                    {
                        "schema_version": "evidence_gateway_snapshot.v1",
                        "overall_status": "demonstrable_but_not_clinical_grade",
                        "architecture_model": {
                            "not_five_parallel_agents": True,
                        },
                        "phase_b_visual_evidence": {
                            "auto_eval_status": "ok",
                            "medsam2_ready": True,
                        },
                        "candidate_gate": {
                            "candidate_count": 11,
                            "promotion_status": "blocked",
                            "formal_update_allowed": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status, payload = dispatch_demo_request(
                method="GET",
                path="/v1/demo/evidence-gateway-snapshot",
                output_root=output_root,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["schema_version"], "evidence_gateway_snapshot.v1")
            self.assertEqual(payload["overall_status"], "demonstrable_but_not_clinical_grade")
            self.assertTrue(payload["phase_b_visual_evidence"]["medsam2_ready"])
            self.assertEqual(payload["candidate_gate"]["candidate_count"], 11)
            self.assertFalse(payload["candidate_gate"]["formal_update_allowed"])

    def test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake(self):
        with TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            diagnosis_dir = output_root / "fake" / "brats_real_vlm_medsam2_diagnosis_demo_real_llm"
            segmentation_dir = output_root / "fake" / "brats_medsam2_auto_eval_real_vlm_prompt_real_medsam2"
            vlm_dir = output_root / "fake" / "brats_vlm_prompt_demo_real_api"
            diagnosis_dir.mkdir(parents=True)
            segmentation_dir.mkdir(parents=True)
            vlm_dir.mkdir(parents=True)
            (diagnosis_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "demo_name": "brats_real_vlm_medsam2_diagnosis_demo",
                        "llm_attempted": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diagnosis_dir / "diagnosis_report.json").write_text(
                json.dumps(
                    {
                        "diagnostic_tendency": "成人弥漫性胶质瘤可能",
                        "visual_fact_usage": {"used": [], "excluded": [], "used_count": 0, "excluded_count": 0},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diagnosis_dir / "evidence_bundle.json").write_text(
                json.dumps(
                    {
                        "case_id": "brats2021_00030",
                        "image_outputs": {
                            "original_image_path": str(REAL_IMAGE),
                            "mask_path": str(REAL_MASK),
                            "overlay_path": "output/fake/overlay.png",
                        },
                        "visual_evidence": {
                            "measurements": {"whole_tumor_volume_ml": 137.914}
                        },
                        "visual_result": {
                            "visual_evidence": {
                                "measurements": {"whole_tumor_volume_ml": 137.914},
                                "segmentation_results": [
                                    {
                                        "task_name": "segment_whole_tumor",
                                        "target": "whole_tumor",
                                        "status": "completed",
                                        "diagnosis_usable": True,
                                        "measurements": {"whole_tumor_volume_ml": 137.914},
                                    },
                                    {
                                        "task_name": "measure_tumor_core",
                                        "target": "tumor_core",
                                        "status": "missing_input",
                                        "diagnosis_usable": False,
                                        "measurements": {},
                                    },
                                    {
                                        "task_name": "measure_enhancing_tumor",
                                        "target": "enhancing_tumor",
                                        "status": "missing_input",
                                        "diagnosis_usable": False,
                                        "measurements": {},
                                    },
                                ],
                                "visual_tool_plan": [
                                    {
                                        "task": {"task_name": "segment_whole_tumor"},
                                        "status": "runnable",
                                        "selected_tool": {"tool_name": "brats_model"},
                                    }
                                ],
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diagnosis_dir / "llm_raw_content.json").write_text(
                json.dumps({"route": "dmx", "model": "gemini-3.5-flash"}),
                encoding="utf-8",
            )
            (segmentation_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "prompt_source": "vision_model_bbox",
                        "aggregate": {"mean_whole_tumor_dice": 0.8868},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (vlm_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "prompt_source": "vision_model_bbox",
                        "bbox_prompt": [[58, 130, 125, 195]],
                        "slice_png_path": "output/fake/brats_vlm_prompt_demo_real_api/brats_slice.png",
                        "bbox_overlay_path": "output/fake/brats_vlm_prompt_demo_real_api/brats_bbox_overlay.png",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            summary_status, summary = dispatch_demo_request(
                method="GET",
                path="/v1/demo/real-vlm-medsam2",
                output_root=output_root,
            )
            report_status, report = dispatch_demo_request(
                method="GET",
                path="/v1/demo/real-vlm-medsam2/report",
                output_root=output_root,
            )
            bundle_status, bundle = dispatch_demo_request(
                method="GET",
                path="/v1/demo/real-vlm-medsam2/evidence-bundle",
                output_root=output_root,
            )
            raw_status, raw = dispatch_demo_request(
                method="GET",
                path="/v1/demo/real-vlm-medsam2/raw-llm",
                output_root=output_root,
            )
            segmentation_status, segmentation = dispatch_demo_request(
                method="GET",
                path="/v1/demo/real-vlm-medsam2/segmentation",
                output_root=output_root,
            )
            vlm_status, vlm = dispatch_demo_request(
                method="GET",
                path="/v1/demo/real-vlm-medsam2/vlm-prompt",
                output_root=output_root,
            )
            response_status, response = dispatch_demo_request(
                method="GET",
                path="/v1/demo/real-vlm-medsam2/response",
                output_root=output_root,
            )

            self.assertEqual(summary_status, 200)
            self.assertEqual(summary["status"], "ok")
            self.assertTrue(summary["llm_attempted"])
            self.assertEqual(report_status, 200)
            self.assertIn("胶质瘤", report["diagnostic_tendency"])
            self.assertEqual(bundle_status, 200)
            self.assertEqual(bundle["visual_evidence"]["measurements"]["whole_tumor_volume_ml"], 137.914)
            self.assertEqual(raw_status, 200)
            self.assertEqual(raw["model"], "gemini-3.5-flash")
            self.assertEqual(segmentation_status, 200)
            self.assertEqual(segmentation["prompt_source"], "vision_model_bbox")
            self.assertEqual(vlm_status, 200)
            self.assertEqual(vlm["bbox_prompt"], [[58, 130, 125, 195]])
            self.assertEqual(response_status, 200)
            self.assertEqual(response["demo_source"], "real_vlm_medsam2_artifact")
            self.assertEqual(response["intent"], "diagnosis")
            self.assertIn("report", response)
            self.assertIn("image_outputs", response)
            self.assertIn("original_preview_path", response["image_outputs"])
            self.assertIn("localization_overlay_path", response["image_outputs"])
            self.assertIn("mask_preview_path", response["image_outputs"])
            self.assertEqual(
                response["image_outputs"]["original_preview_path"],
                "output/fake/brats_vlm_prompt_demo_real_api/brats_slice.png",
            )
            self.assertEqual(
                response["image_outputs"]["localization_overlay_path"],
                "output/fake/brats_vlm_prompt_demo_real_api/brats_bbox_overlay.png",
            )
            self.assertTrue(response["image_outputs"]["mask_preview_path"].endswith("_mask_preview.png"))
            self.assertTrue((output_root.parent / response["image_outputs"]["mask_preview_path"]).exists())
            self.assertEqual(
                response["visual_input_contract"]["image_outputs"]["mask_preview_path"],
                response["image_outputs"]["mask_preview_path"],
            )
            self.assertEqual(
                response["evidence_bundle"]["image_evidence"]["image_outputs"]["original_preview_path"],
                response["image_outputs"]["original_preview_path"],
            )
            self.assertEqual(
                response["memory_audit"]["memory_type_details"]["image_memory"]["original_preview_path"],
                response["image_outputs"]["original_preview_path"],
            )
            self.assertEqual(
                response["memory_audit"]["memory_type_details"]["image_memory"]["mask_preview_path"],
                response["image_outputs"]["mask_preview_path"],
            )
            self.assertEqual(
                response["memory_audit"]["agent_io_summary"]["VisionAgent"]["output"]["mask_preview_path"],
                response["image_outputs"]["mask_preview_path"],
            )
            self.assertEqual(response["alignment_plan"]["analysis_status"], "partial_evidence")
            self.assertIn("evidence_bundle", response)
            self.assertEqual(
                response["visual_input_contract"]["segmentation_results"][0]["task_name"],
                "segment_whole_tumor",
            )
            self.assertTrue(response["visual_input_contract"]["segmentation_results"][0]["diagnosis_usable"])
            self.assertEqual(
                response["visual_input_contract"]["visual_tool_plan"][0]["selected_tool"]["tool_name"],
                "brats_model",
            )
            self.assertEqual(
                response["evidence_bundle"]["image_evidence"]["segmentation_results"][1]["status"],
                "missing_input",
            )
            self.assertIn("memory_audit", response)
            self.assertEqual(
                list(response["memory_audit"]["memory_type_details"].keys()),
                [
                    "patient_memory",
                    "image_memory",
                    "skill_memory",
                    "reasoning_memory",
                ],
            )
            self.assertEqual(response["memory_audit"]["memory_type_details"]["patient_memory"]["intent"], "diagnosis")
            self.assertEqual(
                response["memory_audit"]["memory_type_details"]["skill_memory"]["selected_skill"],
                "diffuse_glioma_brats",
            )
            self.assertEqual(
                response["memory_audit"]["agents_traced"],
                [
                    "GaoDoctorAgent",
                    "SkillBuilderAgent",
                    "VisionAgent",
                    "DiagnosisDoctorAgent",
                    "MemoryManager",
                ],
            )
            self.assertEqual(
                list(response["memory_audit"]["agent_io_summary"].keys()),
                response["memory_audit"]["agents_traced"],
            )
            self.assertTrue(response["memory_audit"]["trace_consistency"]["agent_io_matches_trace"])
            self.assertTrue(response["memory_audit"]["trace_consistency"]["required_agents_present"])
            self.assertFalse(response["memory_audit"]["trace_consistency"]["qa_extension_present"])
            self.assertEqual(response["memory_audit"]["trace_consistency"]["agent_count"], 5)
            self.assertEqual(
                response["memory_audit"]["agent_io_summary"]["VisionAgent"]["tool"],
                "MedSAM2",
            )
            self.assertEqual(
                response["memory_audit"]["agent_io_summary"]["VisionAgent"]["selected_vision_mode"],
                "medsam2",
            )
            self.assertEqual(
                response["memory_audit"]["agent_io_summary"]["MemoryManager"]["output"]["evidence_bundle_status"],
                "available",
            )
            self.assertEqual(response["memory_replay"]["steps"][0]["agent"], "GaoDoctorAgent")
            self.assertEqual(response["memory_replay"]["steps"][0]["event"], "patient_intake")
            self.assertEqual(response["memory_replay"]["steps"][0]["memory_scope"], "patient_memory")
            self.assertEqual(response["memory_replay"]["steps"][1]["agent"], "GaoDoctorAgent")
            self.assertEqual(response["memory_replay"]["steps"][1]["event"], "skill_routing")
            self.assertEqual(response["memory_replay"]["steps"][1]["memory_scope"], "skill_memory")
            self.assertEqual(response["memory_replay"]["steps"][1]["decision_owner"], "orchestrator_api")
            self.assertEqual(
                response["memory_replay"]["steps"][1]["skill_builder_action"],
                "load_existing_skill",
            )
            self.assertEqual(response["memory_replay"]["steps"][2]["agent"], "SkillBuilderAgent")
            self.assertEqual(response["memory_replay"]["steps"][2]["event"], "skill_loading")
            self.assertEqual(response["memory_replay"]["steps"][2]["memory_scope"], "skill_memory")
            self.assertEqual(response["memory_replay"]["steps"][2]["action"], "load_existing_skill")
            self.assertEqual(response["memory_replay"]["steps"][2]["selected_skill"], "diffuse_glioma_brats")
            self.assertEqual(response["memory_replay"]["steps"][3]["agent"], "VisionAgent")
            self.assertEqual(response["memory_replay"]["steps"][3]["event"], "vlm_prompt_generation")
            self.assertEqual(response["memory_replay"]["steps"][3]["memory_scope"], "image_memory")
            self.assertEqual(response["memory_replay"]["steps"][3]["tool"], "VLM Prompt")
            self.assertEqual(response["memory_replay"]["steps"][4]["agent"], "VisionAgent")
            self.assertEqual(response["memory_replay"]["steps"][4]["event"], "visual_evidence")
            self.assertEqual(response["memory_replay"]["steps"][4]["memory_scope"], "image_memory")
            self.assertEqual(response["memory_replay"]["steps"][4]["tool"], "MedSAM2")
            self.assertEqual(response["memory_replay"]["steps"][4]["selected_vision_mode"], "medsam2")
            self.assertTrue(response["memory_replay"]["replay_consistency"]["required_events_present"])
            self.assertTrue(response["memory_replay"]["replay_consistency"]["memory_scope_complete"])
            self.assertFalse(response["memory_replay"]["replay_consistency"]["qa_extension_present"])
            self.assertEqual(response["memory_audit"]["alignment_summary"]["visual_task_status_counts"]["runnable"], 1)
            self.assertEqual(response["memory_audit"]["alignment_summary"]["visual_task_status_counts"]["missing_input"], 2)
            usage = response["report"]["visual_fact_usage"]
            self.assertEqual(usage["used_count"], 1)
            self.assertEqual(usage["excluded_count"], 2)
            self.assertEqual(usage["used"][0]["target"], "whole_tumor")
            self.assertEqual(usage["used"][0]["source_task"], "segment_whole_tumor")
            self.assertEqual(usage["used"][0]["whole_tumor_volume_ml"], 137.914)
            self.assertEqual(usage["excluded"][0]["target"], "tumor_core")
            self.assertEqual(usage["excluded"][0]["exclusion_reason"], "missing_input")
            self.assertEqual(response["evidence_bundle"]["reasoning_evidence"]["visual_fact_usage"]["used_count"], 1)
            self.assertEqual(response["memory_audit"]["visual_fact_usage"]["excluded_count"], 2)
            self.assertEqual(response["memory_replay"]["steps"][-1]["event"], "memory_audit")
            self.assertEqual(response["memory_replay"]["steps"][-1]["agent"], "MemoryManager")
            self.assertEqual(response["memory_replay"]["steps"][-1]["memory_scope"], "patient_memory,image_memory,skill_memory,reasoning_memory")
            self.assertEqual(response["memory_replay"]["steps"][-1]["evidence_bundle_status"], "available")
            replay_diagnosis = response["memory_replay"]["steps"][-2]
            self.assertEqual(replay_diagnosis["event"], "diagnosis_report")
            self.assertEqual(replay_diagnosis["memory_scope"], "reasoning_memory")
            self.assertEqual(replay_diagnosis["visual_fact_usage_summary"]["used_count"], 1)
            self.assertEqual(replay_diagnosis["visual_fact_usage_summary"]["excluded_count"], 2)
            self.assertEqual(replay_diagnosis["used_visual_targets"], ["whole_tumor"])
            self.assertEqual(replay_diagnosis["excluded_visual_targets"], ["tumor_core", "enhancing_tumor"])

    def test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle(self):
        with TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            diagnosis_dir = output_root / "fake" / "brats_real_vlm_medsam2_diagnosis_demo_real_llm"
            segmentation_dir = output_root / "fake" / "brats_medsam2_auto_eval_real_vlm_prompt_real_medsam2"
            vlm_dir = output_root / "fake" / "brats_vlm_prompt_demo_real_api"
            diagnosis_dir.mkdir(parents=True)
            segmentation_dir.mkdir(parents=True)
            vlm_dir.mkdir(parents=True)
            (diagnosis_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "case_id": "brats2021_00030",
                        "prompt_source": "vision_model_bbox",
                        "model": "gemini-3.5-flash",
                        "llm_attempted": True,
                        "diagnostic_tendency": "成人弥漫性胶质瘤可能",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diagnosis_dir / "diagnosis_report.json").write_text(
                json.dumps(
                    {
                        "case_id": "brats2021_00030",
                        "diagnostic_tendency": "成人弥漫性胶质瘤可能",
                        "missing_visual_fields_acknowledged": ["enhancing_tumor"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diagnosis_dir / "evidence_bundle.json").write_text(
                json.dumps(
                    {
                        "case_id": "brats2021_00030",
                        "image_outputs": {"overlay_path": "output/fake/overlay.png"},
                        "evaluation": {
                            "whole_tumor_dice": 0.8868,
                            "enhancing_tumor_dice": 0.0,
                        },
                        "visual_result": {
                            "visual_evidence": {
                                "measurements": {
                                    "whole_tumor_volume_ml": 137.914,
                                    "enhancing_tumor_volume_ml": None,
                                },
                                "completeness": {
                                    "whole_tumor": {"status": "supported", "reason": "FLAIR available"},
                                    "enhancing_tumor": {"status": "missing", "reason": "Requires T1ce modality"},
                                },
                                "segmentation_results": [
                                    {
                                        "task_name": "segment_whole_tumor",
                                        "target": "whole_tumor",
                                        "status": "completed",
                                        "diagnosis_usable": True,
                                        "measurements": {"whole_tumor_volume_ml": 137.914},
                                    },
                                    {
                                        "task_name": "measure_enhancing_tumor",
                                        "target": "enhancing_tumor",
                                        "status": "missing_input",
                                        "diagnosis_usable": False,
                                        "measurements": {},
                                    },
                                ],
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diagnosis_dir / "llm_raw_content.json").write_text(
                json.dumps({"route": "dmx", "model": "gemini-3.5-flash"}),
                encoding="utf-8",
            )
            (segmentation_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "prompt_source": "vision_model_bbox",
                        "evaluation": {"whole_tumor_dice": 0.8868},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (vlm_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "prompt_source": "vision_model_bbox",
                        "boxes": [[58, 130, 125, 195]],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status, payload = dispatch_demo_request(
                method="POST",
                path="/v1/demo/real-vlm-medsam2/qa",
                body=json.dumps(
                    {"patient_message": "为什么 enhancing tumor 是 0？"},
                    ensure_ascii=False,
                ).encode("utf-8"),
                output_root=output_root,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["case_id"], "brats2021_00030")
            self.assertEqual(payload["intent"], "qa")
            self.assertEqual(payload["demo_source"], "real_vlm_medsam2_artifact")
            self.assertEqual(payload["qa_source"], "real_vlm_medsam2_demo_artifact")
            self.assertIn("T1ce", payload["reply_to_patient"])
            self.assertIn("不能", payload["reply_to_patient"])
            self.assertIn("阴性", payload["reply_to_patient"])
            self.assertEqual(
                payload["visual_input_contract"]["segmentation_results"][0]["target"],
                "whole_tumor",
            )
            self.assertEqual(
                payload["visual_input_contract"]["segmentation_results"][1]["target"],
                "enhancing_tumor",
            )
            self.assertTrue(payload["visual_input_contract"]["segmentation_results"][0]["diagnosis_usable"])
            self.assertIn("evidence_bundle", payload)
            self.assertEqual(
                payload["evidence_bundle"]["image_evidence"]["measurements"]["whole_tumor_volume_ml"],
                137.914,
            )
            self.assertEqual(
                payload["evidence_bundle"]["image_evidence"]["completeness"]["enhancing_tumor"]["status"],
                "missing",
            )
            self.assertEqual(payload["report"]["visual_fact_usage"]["used_count"], 1)
            self.assertEqual(payload["report"]["visual_fact_usage"]["excluded_count"], 1)
            self.assertEqual(payload["evidence_bundle"]["reasoning_evidence"]["visual_fact_usage"]["used"][0]["target"], "whole_tumor")
            self.assertEqual(payload["memory_audit"]["visual_fact_usage"]["excluded"][0]["target"], "enhancing_tumor")
            self.assertEqual(
                payload["memory_audit"]["agents_traced"][:5],
                [
                    "GaoDoctorAgent",
                    "SkillBuilderAgent",
                    "VisionAgent",
                    "DiagnosisDoctorAgent",
                    "MemoryManager",
                ],
            )
            self.assertEqual(
                list(payload["memory_audit"]["agent_io_summary"].keys()),
                payload["memory_audit"]["agents_traced"],
            )
            self.assertTrue(payload["memory_audit"]["trace_consistency"]["agent_io_matches_trace"])
            self.assertTrue(payload["memory_audit"]["trace_consistency"]["required_agents_present"])
            self.assertTrue(payload["memory_audit"]["trace_consistency"]["qa_extension_present"])
            self.assertEqual(payload["memory_audit"]["trace_consistency"]["agent_count"], 6)
            self.assertEqual(
                payload["memory_audit"]["agent_io_summary"]["VisionAgent"]["tool"],
                "MedSAM2",
            )
            self.assertEqual(
                payload["memory_audit"]["agent_io_summary"]["GaoDoctorAgent QA"]["output"]["qa_source"],
                "real_vlm_medsam2_demo_artifact",
            )
            self.assertEqual(payload["memory_audit"]["qa_safety"]["evidence_bundle_used_count"], 1)
            self.assertEqual(payload["alignment_plan"]["analysis_status"], "partial_evidence")
            self.assertEqual(
                payload["alignment_plan"]["selected_skill"],
                "diffuse_glioma_brats",
            )
            self.assertEqual(
                payload["memory_replay"]["steps"][-1]["event"],
                "follow_up_qa",
            )
            self.assertEqual(payload["memory_replay"]["steps"][-2]["event"], "memory_audit")
            self.assertEqual(payload["memory_replay"]["steps"][-2]["agent"], "MemoryManager")
            self.assertEqual(payload["memory_replay"]["steps"][-2]["evidence_bundle_status"], "available")
            self.assertEqual(payload["memory_replay"]["steps"][0]["agent"], "GaoDoctorAgent")
            self.assertEqual(payload["memory_replay"]["steps"][0]["event"], "patient_intake")
            self.assertEqual(payload["memory_replay"]["steps"][0]["memory_scope"], "patient_memory")
            self.assertEqual(payload["memory_replay"]["steps"][1]["agent"], "GaoDoctorAgent")
            self.assertEqual(payload["memory_replay"]["steps"][1]["event"], "skill_routing")
            self.assertEqual(payload["memory_replay"]["steps"][1]["memory_scope"], "skill_memory")
            self.assertEqual(payload["memory_replay"]["steps"][1]["decision_owner"], "orchestrator_api")
            self.assertEqual(
                payload["memory_replay"]["steps"][1]["skill_builder_action"],
                "load_existing_skill",
            )
            self.assertEqual(payload["memory_replay"]["steps"][2]["agent"], "SkillBuilderAgent")
            self.assertEqual(payload["memory_replay"]["steps"][2]["event"], "skill_loading")
            self.assertEqual(payload["memory_replay"]["steps"][2]["memory_scope"], "skill_memory")
            self.assertEqual(payload["memory_replay"]["steps"][2]["action"], "load_existing_skill")
            self.assertEqual(payload["memory_replay"]["steps"][2]["selected_skill"], "diffuse_glioma_brats")
            self.assertEqual(payload["memory_replay"]["steps"][3]["agent"], "VisionAgent")
            self.assertEqual(payload["memory_replay"]["steps"][3]["event"], "vlm_prompt_generation")
            self.assertEqual(payload["memory_replay"]["steps"][3]["memory_scope"], "image_memory")
            self.assertEqual(payload["memory_replay"]["steps"][3]["tool"], "VLM Prompt")
            self.assertEqual(payload["memory_replay"]["steps"][4]["agent"], "VisionAgent")
            self.assertEqual(payload["memory_replay"]["steps"][4]["event"], "visual_evidence")
            self.assertEqual(payload["memory_replay"]["steps"][4]["memory_scope"], "image_memory")
            self.assertEqual(payload["memory_replay"]["steps"][4]["tool"], "MedSAM2")
            self.assertEqual(payload["memory_replay"]["steps"][4]["selected_vision_mode"], "medsam2")
            qa_step = payload["memory_replay"]["steps"][-1]
            self.assertEqual(qa_step["agent"], "GaoDoctorAgent QA")
            self.assertEqual(qa_step["memory_scope"], "patient_memory.qa_history")
            self.assertTrue(payload["memory_replay"]["replay_consistency"]["required_events_present"])
            self.assertTrue(payload["memory_replay"]["replay_consistency"]["memory_scope_complete"])
            self.assertTrue(payload["memory_replay"]["replay_consistency"]["qa_extension_present"])
            self.assertTrue(qa_step["evidence_bundle_used"])
            self.assertIn("enhancing tumor", qa_step["question"])
            self.assertEqual(qa_step["visual_fact_usage_summary"]["used_count"], 1)
            self.assertEqual(qa_step["visual_fact_usage_summary"]["excluded_count"], 1)
            self.assertEqual(qa_step["used_visual_targets"], ["whole_tumor"])
            self.assertEqual(qa_step["excluded_visual_targets"], ["enhancing_tumor"])
            self.assertEqual(qa_step["qa_evidence_scope"], "evidence_bundle_visual_fact_usage")

    def test_real_vlm_medsam2_demo_rejects_unknown_artifact(self):
        with TemporaryDirectory() as tmpdir:
            status, payload = dispatch_demo_request(
                method="GET",
                path="/v1/demo/real-vlm-medsam2/unknown",
                output_root=Path(tmpdir) / "output",
            )

            self.assertEqual(status, 404)
            self.assertEqual(payload["error"], "not found")

    def test_demo_case_qa_answers_from_artifact_visual_fact_usage(self):
        with TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            artifacts_dir = (
                output_root
                / "fake"
                / "standard_demo_with_fhn_no_mask_qc"
                / "cases"
                / "fhn_no_mask_multifinding"
                / "artifacts"
            )
            artifacts_dir.mkdir(parents=True)
            response_payload = {
                "case_id": "case_demo",
                "report": {
                    "visual_fact_usage": {
                        "used": [
                            {
                                "finding_id": "finding_1_sclerotic_band",
                                "display_name": "硬化带",
                                "target": "sclerotic_band",
                                "laterality": "image_left",
                                "summary_text": "image_left; 硬化带; independent_evidence",
                            }
                        ],
                        "excluded": [
                            {
                                "finding_id": "finding_3_cystic_change",
                                "display_name": "囊性变",
                                "target": "cystic_change",
                                "laterality": "image_left",
                                "exclusion_reason": "non_independent_evidence",
                                "overlap_with_finding_id": "finding_1_sclerotic_band",
                            }
                        ],
                        "used_count": 1,
                        "excluded_count": 1,
                    }
                },
                "evidence_bundle": {"reasoning_evidence": {}},
                "memory_audit": {
                    "visual_fact_usage": {},
                    "agents_traced": [
                        "GaoDoctorAgent",
                        "SkillBuilderAgent",
                        "VisionAgent",
                        "DiagnosisDoctorAgent",
                        "MemoryManager",
                    ],
                    "agent_io_summary": {
                        "GaoDoctorAgent": {"input": "demo"},
                        "SkillBuilderAgent": {"output": "femoral_head_necrosis"},
                        "VisionAgent": {"tool": "MedSAM2"},
                        "DiagnosisDoctorAgent": {"visual_fact_usage": {}},
                        "MemoryManager": {
                            "output": {
                                "audit_status": "available",
                                "evidence_bundle_status": "available",
                            }
                        },
                    },
                    "qa_safety": {"evidence_bundle_required": True},
                },
                "memory_replay": {
                    "case_id": "case_demo",
                    "steps": [
                        {"agent": "GaoDoctorAgent", "event": "patient_intake"},
                        {"agent": "MemoryManager", "event": "memory_audit"},
                    ],
                },
            }
            (artifacts_dir / "fhn_no_mask_multifinding_response.json").write_text(
                json.dumps(response_payload, ensure_ascii=False),
                encoding="utf-8",
            )

            status, payload = dispatch_demo_request(
                method="POST",
                path="/v1/demo/standard/cases/fhn_no_mask_multifinding/qa",
                body=json.dumps(
                    {"patient_message": "为什么囊性变没有算作独立依据？"},
                    ensure_ascii=False,
                ).encode("utf-8"),
                output_root=output_root,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["case_id"], "case_demo")
            self.assertEqual(payload["intent"], "qa")
            self.assertEqual(payload["qa_source"], "demo_artifact")
            self.assertIn("囊性变", payload["reply_to_patient"])
            self.assertIn("non_independent_evidence", payload["reply_to_patient"])
            self.assertIn("不作为独立诊断依据", payload["reply_to_patient"])
            self.assertEqual(payload["visual_fact_usage"]["used_count"], 1)
            self.assertEqual(payload["visual_fact_usage"]["excluded_count"], 1)
            self.assertEqual(payload["memory_replay"]["steps"][-1]["agent"], "GaoDoctorAgent QA")
            self.assertEqual(payload["memory_replay"]["steps"][-1]["event"], "follow_up_qa")
            self.assertEqual(payload["memory_replay"]["steps"][-1]["memory_scope"], "patient_memory.qa_history")
            self.assertTrue(payload["memory_replay"]["replay_consistency"]["memory_scope_complete"])
            self.assertTrue(payload["memory_replay"]["replay_consistency"]["qa_extension_present"])
            self.assertTrue(payload["memory_replay"]["steps"][-1]["evidence_bundle_used"])
            self.assertEqual(
                payload["memory_replay"]["steps"][-1]["qa_evidence_scope"],
                "evidence_bundle_visual_fact_usage",
            )
            self.assertEqual(
                payload["memory_replay"]["steps"][-1]["visual_fact_usage_summary"],
                {"used_count": 1, "excluded_count": 1},
            )
            self.assertEqual(payload["memory_audit"]["agents_traced"][-1], "GaoDoctorAgent QA")
            self.assertEqual(
                list(payload["memory_audit"]["agent_io_summary"].keys()),
                payload["memory_audit"]["agents_traced"],
            )
            self.assertTrue(payload["memory_audit"]["trace_consistency"]["agent_io_matches_trace"])
            self.assertTrue(payload["memory_audit"]["trace_consistency"]["required_agents_present"])
            self.assertTrue(payload["memory_audit"]["trace_consistency"]["qa_extension_present"])
            self.assertEqual(
                payload["memory_audit"]["agent_io_summary"]["GaoDoctorAgent QA"]["output"]["qa_source"],
                "demo_artifact",
            )
            self.assertTrue(payload["memory_audit"]["qa_safety"]["evidence_bundle_used"])
            self.assertEqual(payload["memory_audit"]["qa_safety"]["evidence_bundle_used_count"], 1)
            self.assertEqual(payload["memory_audit"]["qa_safety"]["qa_source"], "demo_artifact")
            self.assertEqual(
                payload["memory_audit"]["qa_safety"]["visual_fact_usage_summary"],
                {"used_count": 1, "excluded_count": 1},
            )

    def test_demo_artifact_route_rejects_unknown_or_unsafe_case_slug(self):
        with TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            status, payload = dispatch_demo_request(
                method="GET",
                path="/v1/demo/standard/cases/../private/response",
                output_root=output_root,
            )

            self.assertEqual(status, 404)
            self.assertEqual(payload["error"], "not found")

    def test_post_medscope_routes_json_to_service(self):
        service = FakeService()
        status, payload = dispatch_http_request(
            method="POST",
            path="/v1/medscope",
            body=json.dumps(
                {
                    "patient_message": "左髋疼痛三个月",
                    "image_path": "data/images/demo_xray.png",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            service_factory=lambda: service,
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["intent"], "diagnosis")
        self.assertEqual(service.payloads[0]["image_path"], "data/images/demo_xray.png")

    def test_post_medscope_returns_orchestrator_skill_routing_decision(self):
        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(gaodoctor_agent=fake_doctor)
        status, payload = dispatch_http_request(
            method="POST",
            path="/v1/medscope",
            body=json.dumps(
                {
                    "patient_message": "请看一下这个脑部胶质瘤影像",
                    "image_path": "output/fake/uploads/patient_flair.nii.gz",
                    "patient_info": {"symptoms": ["头痛"]},
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            service_factory=lambda: service,
        )

        self.assertEqual(status, 200)
        self.assertEqual(fake_doctor.calls[0]["disease_key"], "diffuse_glioma_brats")
        self.assertEqual(payload["routing_decision"]["selected_skill"], "diffuse_glioma_brats")
        self.assertEqual(payload["routing_decision"]["agent_scope"], "orchestrator_api")
        self.assertEqual(
            payload["routing_decision"]["skill_builder_action"],
            "load_existing_skill",
        )

    @unittest.skipUnless(
        REAL_IMAGE.exists() and REAL_MASK.exists(),
        "real BraTS2021 sample files are not downloaded",
    )
    def test_post_medscope_runs_auto_routed_brats_end_to_end_sample(self):
        with TemporaryDirectory() as tmpdir:
            memory = MemoryManager(base_dir=Path(tmpdir))
            service = MedScopeService(
                gaodoctor_agent=GaoDoctorAgent(memory_manager=memory)
            )
            status, payload = dispatch_http_request(
                method="POST",
                path="/v1/medscope",
                body=json.dumps(
                    {
                        "patient_message": "请基于这次 FLAIR MRI 做胶质瘤辅助分析",
                        "image_path": str(REAL_IMAGE),
                        "mask_path": str(REAL_MASK),
                        "patient_info": {"symptoms": ["头痛"], "age": 58},
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                service_factory=lambda: service,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["routing_decision"]["source"], "auto")
            self.assertEqual(
                payload["routing_decision"]["selected_skill"],
                "diffuse_glioma_brats",
            )
            self.assertEqual(
                payload["routing_decision"]["selected_vision_mode"],
                "ground_truth",
            )
            self.assertEqual(payload["routing_decision"]["agent_scope"], "orchestrator_api")
            self.assertEqual(
                payload["routing_decision"]["skill_builder_action"],
                "load_existing_skill",
            )

            overlay_path = payload["image_outputs"]["overlay_path"]
            self.assertTrue(Path(overlay_path).exists())
            self.assertEqual(
                payload["report"]["visual_input_contract"]["image_outputs"]["overlay_path"],
                overlay_path,
            )
            self.assertEqual(
                payload["visual_input_contract"]["image_outputs"]["overlay_path"],
                overlay_path,
            )
            self.assertIsNone(
                payload["visual_input_contract"]["measurements"]["enhancing_tumor_volume_ml"]
            )
            self.assertEqual(
                payload["visual_input_contract"]["completeness"]["enhancing_tumor"]["status"],
                "missing",
            )
            report_text = json.dumps(payload["report"], ensure_ascii=False)
            self.assertNotIn("增强肿瘤体积为 0", report_text)

            route_path = "/" + overlay_path
            image_status, body, content_type = dispatch_binary_request("GET", route_path)
            self.assertEqual(image_status, 200)
            self.assertGreater(len(body), 0)
            self.assertEqual(content_type, "image/png")

    def test_post_medscope_returns_503_when_auto_medsam2_is_not_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            status, payload = dispatch_http_request(
                method="POST",
                path="/v1/medscope",
                body=json.dumps(
                    {
                        "patient_message": "请看一下这个脑部胶质瘤影像",
                        "image_path": "output/fake/uploads/patient_flair.nii.gz",
                        "patient_info": {"symptoms": ["头痛"]},
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )

        self.assertEqual(status, 503)
        self.assertEqual(payload["error_type"], "medsam2_not_ready")
        self.assertIn("MEDSAM2_COMMAND_TEMPLATE", payload["error"])
        self.assertEqual(payload["routing_decision"]["selected_skill"], "diffuse_glioma_brats")
        self.assertEqual(payload["routing_decision"]["selected_vision_mode"], "medsam2")
        self.assertFalse(payload["medsam2_configuration"]["command_template_present"])
        self.assertFalse(payload["medsam2_configuration"]["real_call_ready"])
        self.assertIn("MEDSAM2_COMMAND_TEMPLATE", " ".join(payload["action_items"]))

    def test_post_medscope_returns_400_for_invalid_payload(self):
        status, payload = dispatch_http_request(
            method="POST",
            path="/v1/medscope",
            body=json.dumps({"image_path": "data/images/demo_xray.png"}).encode("utf-8"),
            service_factory=FakeService,
        )

        self.assertEqual(status, 400)
        self.assertIn("patient_message is required", payload["error"])

    def test_unknown_route_returns_404(self):
        status, payload = dispatch_http_request(
            method="GET",
            path="/unknown",
            service_factory=FakeService,
        )

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "not found")


if __name__ == "__main__":
    unittest.main()
