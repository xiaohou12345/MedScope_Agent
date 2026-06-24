import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.parse import quote
from unittest.mock import patch

from agents.gaodoctor_agent import GaoDoctorAgent
from api.service import MedScopeService
from api.http_server import (
    dispatch_binary_request,
    dispatch_demo_request,
    dispatch_http_request,
    dispatch_knowledge_request,
    dispatch_static_request,
    handle_file_upload,
    load_dotenv_local,
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


class SslEofService:
    def handle_request(self, payload):
        raise URLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1032)")


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
    def test_load_dotenv_local_loads_missing_keys_without_overriding_environment(self):
        with TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ",
            {"DMX_API_KEY": "already-set"},
            clear=True,
        ):
            env_path = Path(tmpdir) / ".env.local"
            env_path.write_text(
                "\n".join(
                    [
                        "DMX_API_KEY=file-key",
                        "KY_API_KEY=ky-file-key",
                        "IGNORED_LINE",
                    ]
                ),
                encoding="utf-8",
            )

            loaded = load_dotenv_local(env_path)

            self.assertEqual(loaded, {"KY_API_KEY": "ky-file-key"})
            import os

            self.assertEqual(os.environ["DMX_API_KEY"], "already-set")
            self.assertEqual(os.environ["KY_API_KEY"], "ky-file-key")

    def test_health_endpoint_returns_ok(self):
        status, payload = dispatch_http_request(
            method="GET",
            path="/health",
            service_factory=FakeService,
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_readiness_endpoint_reports_offline_deployment_checks_without_secret_values(self):
        with patch.dict("os.environ", {"DMX_API_KEY": "secret-test-key"}, clear=False):
            status, payload = dispatch_http_request(
                method="GET",
                path="/v1/readiness",
                service_factory=FakeService,
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["api_route"]["active_route"], "dmx")
        self.assertTrue(payload["api_route"]["api_key_present"])
        self.assertEqual(payload["real_vlm_validation"]["workflow"], "fhn_real_vlm_validation")
        self.assertEqual(payload["real_vlm_validation"]["status"], "ready")
        self.assertTrue(payload["real_vlm_validation"]["api_key_present"])
        self.assertFalse(payload["real_vlm_validation"]["network_call_attempted"])
        self.assertNotIn("secret-test-key", json.dumps(payload, ensure_ascii=False))
        self.assertIn("real_call_ready", payload["api_route"])
        self.assertIn("real_call_ready", payload["medsam2"])
        self.assertTrue(payload["storage"]["upload_root_exists"])
        self.assertTrue(payload["storage"]["output_root_exists"])
        self.assertIn("version", payload["python"])

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
        self.assertIn("开发调试信息", text)
        self.assertIn("alignmentPanel", text)
        self.assertIn("运行审计", text)
        self.assertIn("alignmentView", text)
        self.assertIn("evidencePanel", text)
        self.assertIn("auditPanel", text)
        self.assertIn("qaSubmitButton", text)
        self.assertIn("载入标准样例", text)
        self.assertIn("运行 Public-safe MVP 样例", text)
        self.assertIn("载入 X 光证据不足样例", text)
        self.assertIn("载入 FHN no-mask 样例", text)
        self.assertIn("Evidence Gateway 快照", text)
        self.assertIn("载入 VLM+MedSAM2 样例", text)
        self.assertNotIn("调试 JSON", text)
        self.assertNotIn("图像路径", text)
        self.assertNotIn("Mask 路径", text)
        self.assertNotIn("视觉模式", text)
        self.assertNotIn("疾病 Knowledge", text)

    def test_root_frontend_assets_use_current_cache_buster(self):
        status, body, content_type = dispatch_static_request("/")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn('/static/app.css?v=knowledge-rename-v1-20260624', text)
        self.assertIn('/static/app.js?v=knowledge-rename-v1-20260624', text)
        self.assertNotIn("knowledge-review-20260528", text)
        css_status, _, css_type = dispatch_static_request("/static/app.css?v=knowledge-rename-v1-20260624")
        js_status, _, js_type = dispatch_static_request("/static/app.js?v=knowledge-rename-v1-20260624")
        self.assertEqual(css_status, 200)
        self.assertEqual(css_type, "text/css; charset=utf-8")
        self.assertEqual(js_status, 200)
        self.assertEqual(js_type, "application/javascript; charset=utf-8")

    def test_root_exposes_architecture_roadmap_workspace_without_backend_route(self):
        status, body, content_type = dispatch_static_request("/")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        html = body.decode("utf-8")
        self.assertIn("clinicalDemoTab", html)
        self.assertIn("architectureRoadmapTab", html)
        self.assertIn("clinicalDemoView", html)
        self.assertIn("architectureRoadmapPanel", html)
        self.assertIn("Architecture / Roadmap", html)
        self.assertIn("Guideline-aware Evidence Pipeline", html)
        self.assertIn("architectureDiagramView", html)
        self.assertIn("architectureModuleList", html)
        self.assertIn("architectureDetailView", html)
        self.assertIn("optimizationDirectionList", html)
        self.assertIn("optimizationDirectionDetail", html)
        self.assertIn("roadmapTodoView", html)
        self.assertIn("pipelinePosterStage", html)
        self.assertIn("architecture-quote-panel", html)

    def test_frontend_architecture_roadmap_static_data_covers_modules_directions_and_statuses(self):
        js_status, js_body, js_type = dispatch_static_request("/static/app.js")

        self.assertEqual(js_status, 200)
        self.assertEqual(js_type, "application/javascript; charset=utf-8")
        js = js_body.decode("utf-8")
        self.assertIn("architectureRoadmapData", js)
        self.assertIn("renderArchitectureRoadmap", js)
        self.assertIn("selectArchitectureModule", js)
        self.assertIn("selectOptimizationDirection", js)
        for module_name in [
            "Clinical Orchestrator",
            "Vision Evidence Agent",
            "Diagnosis Reasoning Agent",
            "Knowledge Builder / Guideline Agent",
            "Memory & Audit Layer",
            "evidence_bundle",
        ]:
            self.assertIn(module_name, js)
        for direction_name in [
            "Guideline Knowledge 结构扩展",
            "患者临床信息结合",
            "系统生成候选假设 / Knowledge Routing",
            "论文证据安全补充 Guideline Knowledge",
        ]:
            self.assertIn(direction_name, js)
        for status_name in ["done", "in_progress", "parked", "frozen", "deferred"]:
            self.assertIn(status_name, js)
        self.assertIn("Research Evidence Ingestion production v2", js)
        self.assertIn("Real X-ray Case Comparison", js)
        self.assertIn("Annotation-derived Evidence Bundle v1", js)
        self.assertIn("research evidence is not guideline evidence", js)
        self.assertIn("按需触发 Research Evidence Retrieval", js)
        self.assertIn("默认诊断流程不固定检索论文", js)
        self.assertIn("evidence gap 触发的按需检索", js)
        self.assertIn("clinical risk changes suspicion level only", js)

    def test_frontend_architecture_roadmap_uses_patient_friendly_bilingual_copy(self):
        js_status, js_body, js_type = dispatch_static_request("/static/app.js")

        self.assertEqual(js_status, 200)
        self.assertEqual(js_type, "application/javascript; charset=utf-8")
        js = js_body.decode("utf-8")
        roadmap_start = js.index("const architectureRoadmapData")
        roadmap_end = js.index("function setWorkspaceView")
        roadmap_js = js[roadmap_start:roadmap_end]
        self.assertIn("从图片里提取证据", roadmap_js)
        self.assertIn("把视觉结果打包成证据包（evidence_bundle）", roadmap_js)
        self.assertIn("判断还能不能下结论", roadmap_js)
        self.assertIn("指南 Knowledge 升级", roadmap_js)
        self.assertIn("影像证据清单（Imaging evidence）", roadmap_js)
        self.assertIn("可量化指标（Measurement）", roadmap_js)
        self.assertIn("鉴别诊断（Differential diagnosis）", roadmap_js)
        self.assertNotIn("finding list -> evidence protocol", roadmap_js)
        self.assertNotIn("imaging evidence protocol", roadmap_js)
        self.assertNotIn("quantitative evidence protocol", roadmap_js)
        self.assertNotIn("differential protocol", roadmap_js)
        self.assertNotIn("integrated reasoning protocol", roadmap_js)

    def test_frontend_architecture_poster_uses_single_column_stage_to_prevent_overlap(self):
        css_status, css_body, css_type = dispatch_static_request("/static/app.css")

        self.assertEqual(css_status, 200)
        self.assertEqual(css_type, "text/css; charset=utf-8")
        css = css_body.decode("utf-8")
        self.assertIn(".pipeline-poster-stage", css)
        poster_stage_start = css.index(".pipeline-poster-stage")
        poster_stage_end = css.index(".architecture-diagram-panel", poster_stage_start)
        poster_stage_css = css[poster_stage_start:poster_stage_end]
        self.assertIn("grid-template-columns: minmax(0, 1fr)", poster_stage_css)
        self.assertIn("overflow: hidden", poster_stage_css)
        self.assertIn(".architecture-flow-diagram", css)
        flow_start = css.index(".architecture-flow-diagram")
        flow_end = css.index(".pipeline-poster", flow_start)
        flow_css = css[flow_start:flow_end]
        self.assertIn("overflow-x: auto", flow_css)

    def test_frontend_architecture_poster_links_flow_nodes_and_optimization_directions_to_details(self):
        js_status, js_body, js_type = dispatch_static_request("/static/app.js")
        css_status, css_body, css_type = dispatch_static_request("/static/app.css")

        self.assertEqual(js_status, 200)
        self.assertEqual(js_type, "application/javascript; charset=utf-8")
        self.assertEqual(css_status, 200)
        self.assertEqual(css_type, "text/css; charset=utf-8")
        js = js_body.decode("utf-8")
        css = css_body.decode("utf-8")
        self.assertIn("poster-main-flow", js)
        self.assertIn("poster-flow-arrow-inline", js)
        self.assertIn("poster-flow-node-compact", js)
        self.assertIn('data-scroll-target="architectureDetailView"', js)
        self.assertIn('data-scroll-target="optimizationDirectionDetail"', js)
        self.assertIn("poster-optimization-inline", js)
        self.assertIn("Guideline Knowledge 结构扩展", js)
        self.assertIn("患者临床信息结合", js)
        self.assertIn("系统生成候选假设 / Knowledge Routing", js)
        self.assertIn("论文证据安全补充 Guideline Knowledge", js)
        self.assertIn("scrollArchitectureTarget", js)
        self.assertIn("scrollIntoView", js)
        self.assertIn(".poster-main-flow", css)
        self.assertIn(".poster-flow-arrow-inline", css)
        self.assertIn(".poster-flow-node-compact", css)
        self.assertIn(".poster-optimization-inline", css)
        self.assertNotIn("position: absolute;\n  z-index: 0;", css)

    def test_frontend_uses_agent_safe_vision_routing_without_manual_mode_picker(self):
        status, body, content_type = dispatch_static_request("/")
        js_status, js_body, js_type = dispatch_static_request("/static/app.js?v=frontend-demo-20260603")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertEqual(js_status, 200)
        self.assertEqual(js_type, "application/javascript; charset=utf-8")
        html = body.decode("utf-8")
        js = js_body.decode("utf-8")
        self.assertNotIn("visionModeSelect", html)
        self.assertNotIn("真实 VLM 候选验证", html)
        self.assertNotIn("FHN no-mask 候选证据", html)
        self.assertNotIn("MedSAM2 分割模式", html)
        self.assertIn("Agent 会按 Knowledge evidence protocol 自动选择安全视觉链路", html)
        self.assertNotIn("visionModeSelect", js)
        self.assertNotIn('option value="" selected', html)
        self.assertNotIn("state.sampleVisionMode || elements.visionModeSelect.value", js)
        self.assertIn('state.sampleVisionMode = "no_mask_knowledge"', js)
        self.assertIn("候选视觉证据", js)

    def test_frontend_exposes_knowledge_selection_modes_without_vision_mode_picker(self):
        status, body, content_type = dispatch_static_request("/")
        js_status, js_body, js_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertEqual(js_status, 200)
        self.assertEqual(js_type, "application/javascript; charset=utf-8")
        html = body.decode("utf-8")
        js = js_body.decode("utf-8")
        self.assertIn("knowledgeSelectionMode", html)
        self.assertIn("evidenceProtocolMode", html)
        self.assertIn("finding_list_baseline", html)
        self.assertIn("quantitative_optional", html)
        self.assertIn("默认：只看病灶征象", html)
        self.assertIn("可选：加入量化指标协议", html)
        self.assertIn("primary_only", html)
        self.assertIn("manual_secondary", html)
        self.assertIn("agent_auto_secondary", html)
        self.assertIn("manualSecondaryKnowledges", html)
        self.assertIn("manualSecondaryKnowledgeSelection", html)
        self.assertIn("主 Knowledge 单路", html)
        self.assertIn("人工备用 Knowledge", html)
        self.assertIn("Agent 自动多 Knowledge", html)
        self.assertIn('type="hidden" id="manualSecondaryKnowledges"', html)
        self.assertNotIn("例如 osteoarthritis_or_degenerative_hip_disease", html)
        self.assertIn("payload.knowledge_selection_mode", js)
        self.assertIn("payload.evidence_protocol_mode", js)
        self.assertIn("elements.evidenceProtocolMode.value", js)
        self.assertIn("setEvidenceProtocolMode", js)
        self.assertIn("clearManualSecondaryKnowledges", js)
        self.assertIn('knowledgeSelectionMode !== "manual_secondary"', js)
        self.assertIn("manual_secondary_knowledge_candidates", js)
        self.assertIn("splitList(elements.manualSecondaryKnowledges.value)", js)
        self.assertIn("manualSecondaryVisionMode", js)
        self.assertIn('manualSecondaryVisionMode(knowledgeSelectionMode)', js)
        manual_vision_slice = js[
            js.index("function manualSecondaryVisionMode"):
            js.index("function inferViewHint")
        ]
        self.assertNotIn('return "no_mask_knowledge"', manual_vision_slice)
        self.assertIn("selectManualSecondaryKnowledge", js)
        self.assertIn("removeManualSecondaryKnowledge", js)
        self.assertIn("bindManualSecondaryActionButtons", js)
        self.assertIn("setReportHtml", js)
        self.assertIn("event.stopPropagation()", js)
        self.assertIn("state.lastPayload.manual_secondary_knowledge_candidates", js)
        self.assertIn("selected.slice(0, 3)", js)
        self.assertNotIn("selected.slice(0, 2).join", js)
        self.assertIn("data-secondary-knowledge-key", js)
        self.assertIn("data-secondary-knowledge-remove-key", js)
        self.assertIn("加入备用复查", js)
        self.assertIn("当前备用复查 Knowledge", js)
        self.assertIn("取消备用复查", js)
        self.assertIn("manual-secondary-selection-list", js)
        self.assertNotIn('${selected ? "disabled" : ""}', js)
        self.assertIn("caseProgressStagesForPayload", js)
        self.assertIn("正在调用 KnowledgeBuilder 建立备用 Knowledge 草案", js)
        self.assertIn("const requestPayload = buildCasePayload()", js)
        self.assertIn("postMedScope(requestPayload)", js)
        self.assertNotIn("visionModeSelect", html)

    def test_frontend_exposes_auto_routing_clinical_risk_comparison_sample(self):
        status, body, content_type = dispatch_static_request("/")
        js_status, js_body, js_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertEqual(js_status, 200)
        self.assertEqual(js_type, "application/javascript; charset=utf-8")
        html = body.decode("utf-8")
        js = js_body.decode("utf-8")
        self.assertIn("载入自动路由+不良习惯对比样例", html)
        self.assertIn("autoRoutingRiskCompareButton", html)
        self.assertIn("loadAutoRoutingRiskCompareSample", js)
        sample_start = js.index("function loadAutoRoutingRiskCompareSample")
        sample_end = js.index("function loadPublicSafeDemoInputs")
        sample_slice = js[sample_start:sample_end]
        self.assertIn("右髋疼痛三个月", sample_slice)
        self.assertIn("长期激素治疗", sample_slice)
        self.assertIn("偶尔饮酒", sample_slice)
        self.assertIn("无明显外伤史", sample_slice)
        self.assertIn('state.sampleDiseaseKey = ""', sample_slice)
        self.assertIn('state.sampleVisionMode = "real_vlm_validation"', sample_slice)
        self.assertIn('setKnowledgeSelectionMode("agent_auto_secondary", [])', sample_slice)
        self.assertIn("clearManualSecondaryKnowledges()", sample_slice)
        self.assertNotIn('state.sampleVisionMode = "no_mask_knowledge"', sample_slice)
        self.assertNotIn("股骨头坏死", sample_slice)

    def test_frontend_exposes_collapsible_fhn_knowledge_protocol_comparison(self):
        status, body, content_type = dispatch_static_request("/")
        js_status, js_body, js_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertEqual(js_status, 200)
        self.assertEqual(js_type, "application/javascript; charset=utf-8")
        html = body.decode("utf-8")
        js = js_body.decode("utf-8")
        self.assertIn("Knowledge 版本对比", html)
        self.assertIn("knowledgeProtocolComparisonView", html)
        clinical_section = html[
            html.index('id="clinicalDemoView"'):
            html.index('id="architectureRoadmapPanel"')
        ]
        architecture_section = html[html.index('id="architectureRoadmapPanel"'):]
        self.assertNotIn("knowledge-comparison-details", clinical_section)
        self.assertIn("knowledge-comparison-details", architecture_section)
        self.assertIn("/v1/knowledge/femoral_head_necrosis/comparison", js)
        self.assertIn("renderKnowledgeProtocolComparison", js)
        self.assertIn("finding-list baseline", js)
        self.assertIn("Evidence protocol", js)
        self.assertIn("真实 X-ray protocol coverage", js)
        self.assertIn("新版强在哪", js)
        self.assertIn("哪些指标需要量化", js)
        self.assertIn("renderQuantificationNeedDetails", js)
        self.assertIn("knowledge-quantification-details", js)
        comparison_section = html[
            html.index("knowledge-comparison-details"):
            html.index("research-evidence-review-details")
        ]
        self.assertNotIn("raw YAML", comparison_section)
        self.assertNotIn("annotation_id", js)

    def test_frontend_exposes_collapsible_research_evidence_review_panel_without_raw_json_by_default(self):
        status, body, content_type = dispatch_static_request("/")
        js_status, js_body, js_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertEqual(js_status, 200)
        self.assertEqual(js_type, "application/javascript; charset=utf-8")
        html = body.decode("utf-8")
        js = js_body.decode("utf-8")
        self.assertIn("Research Evidence Review", html)
        self.assertIn("researchEvidenceReviewView", html)
        clinical_section = html[
            html.index('id="clinicalDemoView"'):
            html.index('id="architectureRoadmapPanel"')
        ]
        architecture_section = html[html.index('id="architectureRoadmapPanel"'):]
        self.assertNotIn("research-evidence-review-details", clinical_section)
        self.assertIn("research-evidence-review-details", architecture_section)
        self.assertIn("research evidence is not guideline evidence", html)
        self.assertIn("proposal-only", html)
        self.assertIn("/v1/research-evidence-review", js)
        self.assertIn("renderResearchEvidenceReview", js)
        self.assertIn("proposal_only=true", js)
        self.assertIn("formal_knowledge_updated=false", js)
        self.assertIn("promotion_requires_human_approval=true", js)
        review_section = html[
            html.index("research-evidence-review-details"):
            html.index("roadmap-todo-panel")
        ]
        self.assertNotIn("raw JSON", review_section)
        self.assertNotIn("调试 JSON", review_section)

    def test_research_evidence_review_endpoint_returns_proposal_only_review_package(self):
        status, payload = dispatch_http_request(
            method="GET",
            path="/v1/research-evidence-review",
            service_factory=FakeService,
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["schema_version"], "research_evidence_review_package.v1")
        self.assertEqual(payload["proposal_status"], "proposal_only")
        self.assertFalse(payload["runtime_safety"]["formal_knowledge_updated"])
        self.assertFalse(payload["runtime_safety"]["diagnosis_rules_modified"])
        self.assertFalse(payload["runtime_safety"]["registry_updated"])
        self.assertTrue(payload["runtime_safety"]["promotion_requires_human_approval"])
        self.assertEqual(
            payload["display_policy"]["research_evidence_label"],
            "research evidence is not guideline evidence",
        )
        self.assertIn("gateway_review_artifact", payload)
        self.assertIn("formal_knowledge_extension_patch_preview", payload)

    def test_root_keeps_evidence_gateway_snapshot_inside_debug_section(self):
        status, body, content_type = dispatch_static_request("/")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        text = body.decode("utf-8")
        input_panel = text[
            text.index('<form id="caseForm"'):
            text.index('<section id="visualPanel"')
        ]
        debug_section = text[
            text.index('<details class="debug-details">'):
            text.index('<section class="panel qa-panel">')
        ]
        self.assertNotIn("evidenceGatewaySnapshotButton", input_panel)
        self.assertIn("evidenceGatewaySnapshotButton", debug_section)
        self.assertIn("Evidence Gateway 快照", debug_section)

    def test_static_app_js_renders_patient_friendly_routing_and_differential_sections(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("renderRoutingClinicalSummary", text)
        self.assertIn("renderEvidenceProtocolReport", text)
        self.assertIn("renderEvidenceProtocolModeSummary", text)
        self.assertIn("renderLegacyReportSections", text)
        self.assertIn("renderDifferentialConsiderations", text)
        self.assertIn("renderClinicalHypothesesAssessment", text)
        self.assertIn("分析路径", text)
        self.assertIn("主假设评估", text)
        self.assertIn("影像证据", text)
        self.assertIn("量化证据", text)
        self.assertIn("证据提取范围", text)
        self.assertIn("鉴别考虑", text)
        self.assertIn("clinical_hypotheses_assessment", text)
        self.assertIn("候选假设队列", text)
        self.assertIn("clinical_hypotheses", text)
        self.assertIn("缺失证据", text)
        self.assertIn("建议下一步", text)
        self.assertIn("routing_evidence_status", text)
        self.assertIn("imaging_evidence_summary", text)
        self.assertIn("quantitative_evidence_summary", text)
        self.assertIn("integrated_reasoning_summary", text)
        self.assertIn("clinical_context_evidence", text)
        self.assertIn("临床上下文证据", text)
        self.assertIn("risk_modifier_only", text)
        self.assertIn("differential_reasoning_evidence", text)
        self.assertIn("鉴别推理证据", text)
        self.assertIn("bounded_differential_only", text)
        self.assertIn("quantitative_evidence", text)
        self.assertIn("量化证据审计", text)
        self.assertIn("not_usable_or_exploratory", text)
        self.assertIn("integrated_reasoning_evidence", text)
        self.assertIn("综合推理审计", text)
        self.assertIn("bounded_summary_only", text)
        self.assertIn("differential_considerations", text)
        self.assertIn("missing_evidence", text)
        self.assertIn("recommendation", text)
        patient_report_slice = text[
            text.index("function renderEvidenceProtocolReport"):
            text.index("function renderDifferentialConsiderations")
        ]
        self.assertIn("renderClinicalHypothesesAssessment", patient_report_slice)
        self.assertIn("主假设评估", patient_report_slice)
        self.assertIn("综合推理", patient_report_slice)
        self.assertIn("不是诊断证据", patient_report_slice)
        self.assertIn("可参考发现", patient_report_slice)
        self.assertIn("仅作提示", patient_report_slice)
        self.assertIn("不能确认", patient_report_slice)
        self.assertNotIn("执行方式：", patient_report_slice)
        self.assertNotIn("诊断级别：", patient_report_slice)
        self.assertNotIn("强量化支持", patient_report_slice)
        self.assertNotIn("measurement_usable", patient_report_slice)
        render_report_slice = text[
            text.index("function renderReport"):
            text.index("function renderRoutingClinicalSummary")
        ]
        self.assertIn("const routingSummaryHtml = renderRoutingClinicalSummary(payload)", render_report_slice)
        self.assertIn("renderPatientDiagnosisSummary(payload)", render_report_slice)
        self.assertIn("hasStructuredReport", render_report_slice)
        self.assertIn("renderLegacyReportSections(report, hasStructuredReport)", render_report_slice)
        self.assertIn(
            "${routingSummaryHtml}${evidenceProtocolModeHtml}${patientSummaryHtml}",
            render_report_slice,
        )
        self.assertNotIn("renderEvidenceProtocolReport(payload)", render_report_slice)
        render_payload_slice = text[
            text.index("function renderPayload"):
            text.index("function renderQaPayload")
        ]
        self.assertIn("loadKnowledgeList()", render_payload_slice)
        routing_slice = text[
            text.index("function renderRoutingClinicalSummary"):
            text.index("function renderEvidenceProtocolReport")
        ]
        self.assertIn("clinical_hypotheses", routing_slice)
        self.assertIn("doctor-routing-summary", routing_slice)
        self.assertIn("doctor-routing-card", routing_slice)
        self.assertIn("doctor-routing-knowledge-list", routing_slice)
        self.assertIn("已运行的备用 Knowledge", routing_slice)
        self.assertIn("备用复查状态", routing_slice)
        self.assertIn("查看技术细节", routing_slice)
        self.assertIn("主分析 Knowledge", routing_slice)
        self.assertIn("Primary hypothesis", routing_slice)
        self.assertIn("候选假设队列", routing_slice)
        self.assertIn("这不是诊断结论", routing_slice)
        self.assertIn("当前只加载主分析 Knowledge", routing_slice)
        self.assertIn("进入 proposal-only Knowledge 审核队列", routing_slice)
        self.assertIn("visibleRoutingHypotheses", routing_slice)
        self.assertIn("collapsedRoutingHypotheses", routing_slice)
        self.assertIn("更多鉴别候选", routing_slice)
        self.assertIn("低优先级", routing_slice)
        self.assertIn("display_differential_knowledge_candidates", routing_slice)
        self.assertIn("重点鉴别复核", routing_slice)
        self.assertIn("secondary_knowledge_run_plan", routing_slice)
        self.assertIn("Secondary knowledge run", routing_slice)
        self.assertIn("已运行备用 Knowledge 复查", routing_slice)
        self.assertIn("下方已按备用 Knowledge 运行复查", routing_slice)
        self.assertIn("已按备用 Knowledge 运行复查", routing_slice)
        self.assertIn("未审核 Knowledge 可用于假设验证", routing_slice)
        self.assertIn("不能作为正式确诊依据", routing_slice)
        self.assertIn("renderManualSecondaryCandidateList", routing_slice)
        self.assertIn("可追加备用复查", routing_slice)
        self.assertIn("manualSecondaryCandidateKeys", routing_slice)
        self.assertIn("renderSecondaryKnowledgeAnalysis", routing_slice)
        self.assertIn("renderSecondaryKnowledgeBuilderProgress", routing_slice)
        self.assertIn("secondaryReviewEvidenceItems", text)
        self.assertIn("备用复查：", text)
        self.assertIn("secondary_knowledge_analysis", routing_slice)
        self.assertIn("knowledge_builder_progress", routing_slice)
        self.assertIn("KnowledgeBuilder 备用 Knowledge 进度", routing_slice)
        self.assertIn("KnowledgeBuilder 备用 Knowledge 进度", routing_slice)
        self.assertIn("备用复查判断", routing_slice)
        self.assertIn("需要复查的证据", routing_slice)
        self.assertIn("当前图像观察", routing_slice)
        self.assertIn("report_sentence", routing_slice)
        self.assertIn("备用 Knowledge 复查结果", routing_slice)
        legacy_slice = text[
            text.index("function renderLegacyReportSections"):
            text.index("function renderRoutingClinicalSummary")
        ]
        self.assertIn("hasStructuredReport", legacy_slice)
        self.assertIn('"诊断倾向"', legacy_slice)
        self.assertIn('"治疗建议"', legacy_slice)
        self.assertIn('"影像依据"', legacy_slice)
        self.assertIn('"不确定性说明"', legacy_slice)
        self.assertIn('"建议进一步检查"', legacy_slice)

    def test_static_app_js_adds_differential_candidates_to_knowledge_review_queue(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("differentialKnowledgeCandidateProposals", text)
        self.assertIn("renderKnowledgeProposalCandidateDetail", text)
        self.assertIn("proposal_only", text)
        self.assertIn("differential_candidate", text)
        self.assertIn("待建 Knowledge", text)
        self.assertIn("本次病例候选", text)
        self.assertIn("未审核", text)
        self.assertIn("KnowledgeBuilder proposal 已生成并进入审核库", text)
        self.assertIn("KnowledgeBuilder 草案说明", text)
        self.assertIn("review_queue_status", text)
        self.assertIn("需要复查的证据", text)
        self.assertIn("指南/规则来源", text)
        self.assertIn("renderGuidelineEvidenceSummary", text)
        self.assertIn("source_titles", text)
        self.assertIn("guideline_sections", text)
        self.assertIn("knowledge_builder_proposal_detail", text)
        self.assertIn("differential_review", text)
        self.assertIn("proposalFromListPayload", text)
        self.assertIn("secondaryMetaFromPayload", text)
        self.assertIn("formalKnowledges.flatMap", text)
        self.assertIn("knowledge.candidate_key", text)
        self.assertIn("保存为正式 Knowledge", text)
        self.assertIn("needs_review", text)
        self.assertIn("不作为正式确诊规则", text)
        self.assertIn("function knowledgeEvidenceLevelLabel", text)
        self.assertIn("未审核", text)
        self.assertIn("医疗来源待补充", text)
        self.assertIn("knowledgeEvidenceLevelLabel(knowledge.evidence_level)", text)

    def test_static_app_js_renders_patient_diagnosis_report_as_three_block_summary(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("function renderPatientDiagnosisSummary", text)
        self.assertIn("function patientDiagnosisConclusion", text)
        self.assertIn("function patientDiagnosisEvidenceItems", text)
        self.assertIn("function patientDiagnosisNextSteps", text)
        summary_slice = text[
            text.index("function renderPatientDiagnosisSummary"):
            text.index("function patientDiagnosisConclusion")
        ]
        self.assertIn("患者诊断摘要", summary_slice)
        self.assertIn("重点结论", summary_slice)
        self.assertIn("疾病判断", summary_slice)
        self.assertIn("发现的病灶/征象", summary_slice)
        self.assertIn("疑似/确诊边界", summary_slice)
        self.assertIn("主要依据", summary_slice)
        self.assertIn("下一步", summary_slice)
        self.assertIn("renderPatientPrimaryDiagnosis(payload)", summary_slice)
        self.assertIn("renderPatientSecondaryReviewSummary(payload)", summary_slice)
        self.assertIn("patientDiagnosisLesionHighlights(payload)", summary_slice)
        self.assertIn("patientDiagnosisBoundary(payload)", summary_slice)
        self.assertIn("slice(0, 3)", summary_slice)
        self.assertNotIn("量化证据", summary_slice)
        self.assertNotIn("临床风险因素", summary_slice)
        self.assertNotIn("缺失证据</h3>", summary_slice)
        self.assertIn("function patientDiagnosisLesionHighlights", text)
        self.assertIn("patientVisibleFindings(visualBundle)", text)
        self.assertIn("function patientDiagnosisBoundary", text)

    def test_static_app_js_surfaces_secondary_knowledge_conclusion_in_patient_summary(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("function patientSecondaryKnowledgeConclusion", text)
        self.assertIn("function renderPatientSecondaryReviewSummary", text)
        self.assertIn("function patientSecondaryReviewTitle", text)
        self.assertIn("function secondaryReviewEvidenceLine", text)
        self.assertIn("function patientSecondaryReviewItems", text)
        self.assertIn("function renderSecondaryVisualEvidenceSummary", text)
        self.assertIn("secondary_visual_evidence_bundle", text)
        self.assertIn("备用视觉证据包", text)
        self.assertIn("Agent 自动备用复查", text)
        self.assertIn("按备用 Knowledge 专属视觉协议复查", text)
        self.assertIn("未提取到该备用病种的专属支持征象", text)
        headline_slice = text[
            text.index("function patientDiagnosisHeadline"):
            text.index("function patientDiagnosisLesionHighlights")
        ]
        boundary_slice = text[
            text.index("function patientDiagnosisBoundary"):
            text.index("function patientDiagnosisConclusion")
        ]
        self.assertNotIn("patientSecondaryKnowledgeConclusion(payload", headline_slice)
        self.assertNotIn("patientSecondaryKnowledgeConclusion(payload)", boundary_slice)
        self.assertIn("patient-secondary-review-summary", text)
        helper_slice = text[
            text.index("function patientSecondaryKnowledgeConclusion"):
            text.index("function patientDiagnosisEvidenceItems")
        ]
        self.assertIn("备用疾病复查", helper_slice)
        self.assertIn("备用复查", helper_slice)
        self.assertIn("证据不足", helper_slice)
        self.assertIn("证据支持度", helper_slice)

    def test_static_app_js_uses_confidence_and_all_secondary_knowledges_in_patient_summary(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("function primaryDiagnosticConfidence", text)
        self.assertIn("function diagnosticConfidenceSentence", text)
        self.assertIn("diagnostic_confidence", text)
        self.assertIn("function renderPatientPrimaryDiagnosis", text)
        headline_slice = text[
            text.index("function patientDiagnosisHeadline"):
            text.index("function patientDiagnosisLesionHighlights")
        ]
        self.assertIn("primaryDiagnosticConfidence(payload)", headline_slice)
        self.assertIn("diagnosticConfidenceSentence(confidence)", headline_slice)
        primary_slice = text[
            text.index("function renderPatientPrimaryDiagnosis"):
            text.index("function primaryDiagnosticConfidence")
        ]
        self.assertIn("规则支持度", primary_slice)
        self.assertIn("不是校准后的真实患病概率", primary_slice)
        helper_slice = text[
            text.index("function patientSecondaryKnowledgeConclusion"):
            text.index("function patientDiagnosisEvidenceItems")
        ]
        self.assertIn("function secondaryConfidenceText", helper_slice)
        self.assertIn("规则支持度", helper_slice)
        self.assertIn("const visibleItems = items.filter", helper_slice)
        self.assertIn(".map((item) => secondaryKnowledgeConclusionText", helper_slice)
        self.assertIn("function secondaryKnowledgeConclusionText", helper_slice)
        self.assertNotIn("const first = items.find", helper_slice)
        self.assertIn("function derivedPrimaryDiagnosticConfidence", text)
        self.assertIn("patientDiagnosisLesionHighlights(payload)", text)
        self.assertIn("硬化带", text)
        self.assertIn("囊性变", text)

    def test_static_app_js_loads_persisted_proposal_detail_into_review_workspace(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        click_slice = text[
            text.index('querySelectorAll("[data-knowledge-key]")'):
            text.index("function knowledgeEvidenceLevelLabel")
        ]
        self.assertIn("payload.knowledge.some", click_slice)
        self.assertIn("await loadKnowledgeDetail(button.dataset.knowledgeKey)", click_slice)
        self.assertIn("renderKnowledgeProposalCandidateDetail", click_slice)

    def test_static_app_css_wraps_patient_priority_cards_without_overflow(self):
        status, body, content_type = dispatch_static_request("/static/app.css")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/css; charset=utf-8")
        css = body.decode("utf-8")
        grid_slice = css[
            css.index(".patient-priority-grid"):
            css.index(".patient-priority-card", css.index(".patient-priority-grid"))
        ]
        card_slice = css[
            css.index(".patient-priority-card"):
            css.index(".patient-priority-disease")
        ]
        self.assertIn("repeat(auto-fit", grid_slice)
        self.assertIn("minmax(220px, 1fr)", grid_slice)
        self.assertIn("overflow-wrap: anywhere", card_slice)
        self.assertIn("word-break: break-word", card_slice)
        self.assertIn(".diagnosis-main-line", css)
        self.assertIn(".diagnosis-confidence-pill", css)
        self.assertIn(".patient-secondary-review-summary", css)
        self.assertIn(".secondary-review-heading", css)
        self.assertIn(".secondary-review-evidence", css)
        self.assertIn(".secondary-review-pill", css)
        self.assertIn(".doctor-routing-summary", css)
        self.assertIn(".doctor-routing-card", css)
        self.assertIn(".doctor-routing-knowledge-list", css)
        self.assertIn(".routing-technical-details", css)

    def test_static_app_js_hides_internal_missing_evidence_keys_from_patient_summary(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("function patientMissingEvidenceName", text)
        evidence_slice = text[
            text.index("function patientDiagnosisEvidenceItems"):
            text.index("function patientDiagnosisNextSteps")
        ]
        self.assertIn("patientMissingEvidenceName", evidence_slice)
        self.assertNotIn("missingTargets.slice(0, 3).map(humanFindingName)", evidence_slice)
        missing_label_slice = text[
            text.index("function patientMissingEvidenceName"):
            text.index("function humanFindingName")
        ]
        self.assertIn("可用于测量分级的病灶分割结果", missing_label_slice)
        self.assertIn("可展示的分割对照图", missing_label_slice)
        self.assertNotIn("缺少可用于测量分级的病灶分割结果", missing_label_slice)
        self.assertNotIn("缺少可展示的分割对照图", missing_label_slice)
        self.assertNotIn("仍缺少：缺少", missing_label_slice)
        self.assertNotIn("measurement_grade_mask", evidence_slice)
        self.assertNotIn("segmentation_display", evidence_slice)

    def test_static_app_js_deduplicates_patient_summary_finding_names(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("function uniquePatientFindingNames", text)
        evidence_slice = text[
            text.index("function patientDiagnosisEvidenceItems"):
            text.index("function patientDiagnosisNextSteps")
        ]
        self.assertIn("uniquePatientFindingNames(supportedTargets)", evidence_slice)
        self.assertIn("uniquePatientFindingNames(nonspecificTargets)", evidence_slice)
        self.assertNotIn("supportedTargets.map(humanFindingName)", evidence_slice)
        self.assertNotIn("nonspecificTargets.slice(0, 3).map(humanFindingName)", evidence_slice)
        helper_slice = text[
            text.index("function uniquePatientFindingNames"):
            text.index("function patientMissingEvidenceName")
        ]
        self.assertIn("new Set", helper_slice)
        self.assertIn("filter(Boolean)", helper_slice)
        self.assertIn("slice(0, 3)", helper_slice)

    def test_static_app_js_renders_knowledge_proposal_report_before_plain_reply(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("function renderKnowledgeProposalReport", text)
        self.assertIn("Knowledge Builder 候选草案", text)
        self.assertIn("不能直接诊断", text)
        self.assertIn("formal_update_allowed", text)
        render_report_slice = text[
            text.index("function renderReport"):
            text.index("function renderLegacyReportSections")
        ]
        self.assertIn("renderKnowledgeProposalReport(payload)", render_report_slice)
        self.assertLess(
            render_report_slice.index("renderKnowledgeProposalReport(payload)"),
            render_report_slice.index("payload.reply_to_patient"),
        )

    def test_static_app_js_renders_protocol_evidence_item_view_source(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        title_slice = text[
            text.index("function evidenceProtocolItemTitle"):
            text.index("function evidenceProtocolItemSummary")
        ]
        self.assertIn("evidenceViewHintLabel", title_slice)
        self.assertIn("view_hint", title_slice)
        self.assertIn("骨盆正位/AP", text)
        self.assertIn("蛙式侧位", text)

    def test_static_app_js_renders_lesion_gallery_view_source(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        gallery_slice = text[
            text.index("function buildCandidateLesionItems"):
            text.index("function getLesionGalleryItems")
        ]
        self.assertIn("candidateTitleWithView", gallery_slice)
        self.assertIn("view_label", gallery_slice)
        self.assertIn("view_hint", gallery_slice)

    def test_static_app_js_health_button_uses_readiness_endpoint(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        health_slice = text[
            text.index("async function checkHealth"):
            text.index("function renderList")
        ]
        self.assertIn("/v1/readiness", health_slice)
        self.assertIn("real_call_ready", health_slice)
        self.assertIn("vision_model", health_slice)
        self.assertIn("text=", health_slice)
        self.assertIn("vision=", health_slice)
        self.assertIn("MedSAM2", health_slice)
        self.assertNotIn('fetch("/health")', health_slice)

    def test_static_app_js_upload_status_summarizes_multiview_inputs(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("function formatUploadedImageSeriesStatus", text)
        upload_slice = text[
            text.index("async function uploadFiles"):
            text.index("async function checkHealth")
        ]
        self.assertIn("formatUploadedImageSeriesStatus(uploaded)", upload_slice)
        formatter_slice = text[
            text.index("function formatUploadedImageSeriesStatus"):
            text.index("async function checkHealth")
        ]
        self.assertIn("inferViewHint", formatter_slice)
        infer_slice = text[
            text.index("function inferViewHint"):
            text.index("function buildQaPayload")
        ]
        self.assertIn('text.includes("lateral")', infer_slice)
        self.assertIn('text.includes("侧位")', infer_slice)
        label_slice = text[
            text.index("function imageViewLabel"):
            text.index("function renderImageSeriesContext")
        ]
        self.assertIn('lateral: "髋关节侧位/Lateral"', label_slice)
        self.assertIn("imageViewLabel", formatter_slice)
        self.assertIn("image_001", formatter_slice)
        self.assertIn("骨盆正位/AP", text)
        self.assertIn("蛙式侧位", text)

    def test_static_app_js_clears_stale_outputs_and_gates_qa_during_new_analysis(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        upload_slice = text[
            text.index("async function uploadFiles"):
            text.index("function formatUploadedImageSeriesStatus")
        ]
        self.assertIn("resetViews()", upload_slice)
        self.assertIn("state.useSampleMask = false", upload_slice)
        thinking_slice = text[
            text.index("function showCaseThinking"):
            text.index("function renderCaseError")
        ]
        self.assertIn("elements.alignmentView.innerHTML", thinking_slice)
        self.assertIn("elements.lesionFigure.hidden = true", thinking_slice)
        qa_slice = text[
            text.index("function updateQaControls"):
            text.index("function setCasePending")
        ]
        self.assertIn("state.qaPending", qa_slice)
        self.assertIn("elements.qaInput.disabled = !analysisReady || state.casePending || state.qaPending", qa_slice)
        self.assertIn("elements.qaSubmitButton.disabled = !analysisReady || state.casePending", qa_slice)

    def test_static_app_js_renders_qa_answer_with_patient_safe_clean_paragraphs(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("function renderPatientQaAnswer", text)
        self.assertIn("function patientQaAnswerParagraphs", text)
        qa_slice = text[
            text.index("function updateQaItem"):
            text.index("function ensureImageLightbox")
        ]
        self.assertIn("renderPatientQaAnswer(answer)", qa_slice)
        self.assertNotIn("<p>${escapeHtml(answer || \"-\")}</p>", qa_slice)
        renderer_slice = text[
            text.index("function renderPatientQaAnswer"):
            text.index("function patientQaAnswerParagraphs")
        ]
        self.assertIn("qa-answer", renderer_slice)
        self.assertIn("paragraphs.map", renderer_slice)
        paragraph_slice = text[
            text.index("function patientQaAnswerParagraphs"):
            text.index("function ensureImageLightbox")
        ]
        self.assertIn('replace(/\\*\\*/g, "")', paragraph_slice)
        self.assertIn('replace(/__/g, "")', paragraph_slice)
        self.assertIn("slice(0, 3)", paragraph_slice)

    def test_static_app_js_falls_back_to_uploaded_input_image_when_no_visual_output_exists(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("function renderInputImageFallbackGallery", text)
        self.assertIn("function buildInputImageFallbackItems", text)
        visual_slice = text[
            text.index("function renderVisualOutput"):
            text.index("function renderPatientVisualSummary")
        ]
        self.assertIn("renderInputImageFallbackGallery", visual_slice)
        fallback_slice = text[
            text.index("function buildInputImageFallbackItems"):
            text.index("function renderPatientVisualSummary")
        ]
        self.assertIn("visualBundle.image_context", fallback_slice)
        self.assertIn("payload.image_paths", fallback_slice)
        self.assertIn("payload.image_path", fallback_slice)
        self.assertIn("输入图像", text)

    def test_static_app_js_translates_system_visual_findings_for_patient_display(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("function visualFindingDisplayName", text)
        self.assertIn("function visualFindingRawTextIsChinese", text)
        self.assertIn("insufficient_visual_input", text)
        self.assertIn("影像输入不足", text)
        self.assertIn("VLM 候选验证未返回可用结果", text)
        patient_slice = text[
            text.index("function patientVisibleFindings"):
            text.index("function buildVisualDisplayState")
        ]
        self.assertIn("visualFindingDisplayName(finding)", patient_slice)
        self.assertIn("visualFindingReadableText(finding)", patient_slice)
        debug_slice = text[
            text.index("function renderFindingList"):
            text.index("function renderSegmentationResults")
        ]
        self.assertIn("visualFindingDisplayName(finding)", debug_slice)

    def test_static_app_js_renders_readiness_errors_as_structured_panels(self):
        status, body, content_type = dispatch_static_request("/static/app.js")

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/javascript; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("function buildApiError", text)
        self.assertIn("error.apiPayload", text)
        self.assertIn("function renderStructuredErrorPanel", text)
        self.assertIn("部署检查未通过", text)
        self.assertIn("VLM/API 临时不可用", text)
        self.assertIn("视觉模型调用中断，详情见报告区", text)
        self.assertIn("vlm_api_unavailable", text)
        self.assertIn("需要处理", text)
        self.assertIn("medsam2_configuration", text)
        self.assertIn("routing_decision", text)
        error_slice = text[
            text.index("function renderCaseError"):
            text.index("function showQaThinking")
        ]
        self.assertIn("renderStructuredErrorPanel", error_slice)
        self.assertIn("报告区", error_slice)
        status_slice = text[
            text.index('elements.caseForm.addEventListener("submit"'):
            text.index('elements.qaForm.addEventListener("submit"')
        ]
        self.assertIn("shortApiErrorMessage(error", status_slice)
        self.assertNotIn("setStatus(error.message", status_slice)

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
        self.assertIn(b"renderImageSeriesContext", body)
        self.assertIn(b"view_coverage", body)
        self.assertIn(b"image_series", body)
        self.assertIn("多体位输入".encode("utf-8"), body)
        self.assertIn("当前仅分析主图".encode("utf-8"), body)
        self.assertIn("多体位分析".encode("utf-8"), body)
        self.assertIn(b"multi_view_execution", body)
        self.assertIn(b"renderSegmentationResults", body)
        self.assertIn(b"renderVisualToolPlan", body)
        self.assertIn("分割任务结果".encode("utf-8"), body)
        self.assertIn("视觉工具计划".encode("utf-8"), body)
        self.assertIn("诊断可用".encode("utf-8"), body)
        self.assertIn(b"renderVisualFactUsage", body)
        self.assertIn(b"renderLesionComparison", body)
        self.assertIn(b"renderPatientVisualSummary", body)
        self.assertIn(b"renderTargetOverlayGallery", body)
        self.assertIn(b"openImageLightbox", body)
        self.assertIn(b"data-lightbox-src", body)
        self.assertIn(b"data-lightbox-regions", body)
        self.assertIn(b"renderLightboxCrops", body)
        self.assertIn(b"enhanceCanvasContrast", body)
        self.assertIn(b"drawCandidateHighlight", body)
        self.assertIn("看这里".encode("utf-8"), body)
        self.assertIn("局部灰度".encode("utf-8"), body)
        self.assertIn("局部放大".encode("utf-8"), body)
        self.assertIn("硬化带".encode("utf-8"), body)
        self.assertIn("患者可见影像摘要".encode("utf-8"), body)
        self.assertIn("按征象单独查看".encode("utf-8"), body)
        self.assertIn(b"buildVisualComparisonItems", body)
        self.assertIn(b"original_preview_path", body)
        self.assertIn(b"slice_png_path", body)
        self.assertIn(b"bbox_overlay_path", body)
        self.assertIn(b"mask_preview_path", body)
        self.assertIn("原图".encode("utf-8"), body)
        self.assertIn("VLM 标注".encode("utf-8"), body)
        self.assertIn("分割结果".encode("utf-8"), body)
        self.assertIn("分割候选 mask".encode("utf-8"), body)
        self.assertIn("对比叠加".encode("utf-8"), body)
        self.assertIn(b"renderMultiViewOutputGallery", body)
        self.assertIn(b"per_image_results", body)
        self.assertIn("多体位视觉结果".encode("utf-8"), body)
        self.assertIn("按体位查看".encode("utf-8"), body)
        self.assertIn(b"data-view-hint", body)
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
        self.assertIn("条件 Knowledge 构建 / 加载".encode("utf-8"), body)
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
        self.assertIn("Knowledge / 指南 / 路由".encode("utf-8"), body)
        self.assertIn("诊断推理与报告".encode("utf-8"), body)
        self.assertIn(b"renderKnowledgeQuality", body)
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
        self.assertIn(b'event: "knowledge_loading"', body)
        self.assertIn(b'event: "vlm_prompt_generation"', body)
        self.assertIn(b'tool: "VLM Prompt"', body)
        self.assertIn(b'tool: "MedSAM2"', body)
        self.assertIn(b'agent: "MemoryManager"', body)
        self.assertIn(b'event: "memory_audit"', body)
        self.assertIn(b"agent_io_summary", body)
        self.assertIn(b"evidence_bundle_status", body)
        self.assertIn(b"decision_owner", body)
        self.assertIn(b"knowledge_builder_action", body)
        self.assertIn(b"routing_source", body)
        self.assertIn(b'decision_owner: "orchestrator_api"', body)
        self.assertNotIn(b'agent: "Knowledge Builder", event: "knowledge_routing"', body)
        self.assertNotIn(b"Knowledge/VLM prompt", body)
        self.assertIn(b"/v1/memory/cases/", body)
        self.assertIn(b"visual_protocol_status", body)
        self.assertIn(b"qa_safety", body)
        self.assertIn(b"memory_type_details", body)
        self.assertIn(b"runStandardSample", body)
        self.assertIn(b"runPublicSafeDemo", body)
        self.assertIn(b"runRealVlmMedSAM2Sample", body)
        self.assertIn(b"runXrayInsufficientSample", body)
        self.assertIn(b"runFhnNoMaskSample", body)
        self.assertIn(b"runEvidenceGatewaySnapshot", body)
        self.assertIn(b"fetchPublicSafeDemo", body)
        self.assertIn(b"publicSafeDemoButton", body)
        self.assertIn(b"postPublicSafeDemoQa", body)
        self.assertIn(b"publicSafeDemoMode", body)
        self.assertIn(b"/v1/demo/public-safe/qa", body)
        self.assertIn(b"public_safe_demo_suite", body)
        self.assertIn(b"renderDemoSourceSummary", body)
        self.assertIn(b"demo_source: payload.demo_source", body)
        self.assertIn(b"qa_source: payload.qa_source || state.lastPayload.qa_source", body)
        self.assertIn(b"renderVisualOutput(state.lastPayload)", body)
        self.assertIn(b"fetchEvidenceGatewaySnapshot", body)
        self.assertIn(b"renderEvidenceGatewaySnapshot", body)
        self.assertIn("Evidence Gateway 快照".encode("utf-8"), body)
        self.assertIn(b"/v1/demo/evidence-gateway-snapshot", body)
        self.assertIn(b"/v1/demo/public-safe", body)
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
        self.assertIn(b"no_mask_knowledge", body)
        self.assertIn(b"femoral_head_necrosis", body)
        self.assertIn(b"alignment_plan", body)
        self.assertIn(b"insufficient_evidence", body)
        self.assertIn(b"qaPending", body)
        self.assertIn(b"casePending", body)
        self.assertIn(b"setQaPending", body)
        self.assertIn(b"setCasePending", body)
        self.assertIn(b"showQaThinking", body)
        self.assertIn(b"showCaseThinking", body)
        self.assertIn(b"renderCaseError", body)
        self.assertIn(b"Thinking", body)
        self.assertIn("如果是实时上传病例".encode("utf-8"), body)
        self.assertIn(b"fetchKnowledgeList", body)
        self.assertIn(b"renderKnowledgeReviewWorkspace", body)
        self.assertIn(b"saveKnowledgeReviewDraft", body)
        self.assertIn("Knowledge 审核".encode("utf-8"), body)
        self.assertIn("医生审核".encode("utf-8"), body)
        self.assertIn("保存草稿".encode("utf-8"), body)
        self.assertIn("保存为正式 Knowledge".encode("utf-8"), body)
        self.assertIn(b"promoteKnowledgeToFormalLibrary", body)
        self.assertIn(b"/promote", body)
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

    def test_upload_route_decodes_frontend_encoded_filename(self):
        encoded_filename = quote("髋关节 正位.png")

        status, payload = dispatch_http_request(
            method="POST",
            path=f"/v1/upload?filename={encoded_filename}",
            body=b"fake-png",
            service_factory=FakeService,
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["filename"], "髋关节_正位.png")
        self.assertNotIn("%", payload["filename"])

    def test_upload_rejects_empty_file(self):
        status, payload = handle_file_upload(filename="scan.nii.gz", body=b"")

        self.assertEqual(status, 400)
        self.assertIn("empty", payload["error"])

    def test_knowledge_list_returns_doctor_friendly_summaries(self):
        with TemporaryDirectory() as tmpdir:
            knowledges_dir = Path(tmpdir) / "knowledge"
            knowledges_dir.mkdir()
            (knowledges_dir / "fhn.yaml").write_text(
                json.dumps(
                    {
                        "disease_name": "股骨头坏死",
                        "knowledge_id": "fhn_v0.1",
                        "knowledge_type": "guideline_based",
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

            status, payload = dispatch_knowledge_request(
                method="GET",
                path="/v1/knowledge",
                knowledges_dir=knowledges_dir,
                output_root=Path(tmpdir) / "output",
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["count"], 1)
            summary = payload["knowledge"][0]
            self.assertEqual(summary["knowledge_key"], "fhn")
            self.assertEqual(summary["disease_name"], "股骨头坏死")
            self.assertEqual(summary["doctor_summary"]["symptom_count"], 1)
            self.assertEqual(summary["doctor_summary"]["image_requirement_count"], 2)
            self.assertEqual(summary["doctor_summary"]["visual_finding_count"], 2)
            self.assertEqual(summary["review_status"], "no_draft")

    def test_knowledge_list_includes_secondary_knowledge_proposal_artifacts(self):
        with TemporaryDirectory() as tmpdir:
            knowledges_dir = Path(tmpdir) / "knowledge"
            output_root = Path(tmpdir) / "output"
            proposal_dir = output_root / "fake" / "secondary_knowledge_proposals"
            knowledges_dir.mkdir()
            proposal_dir.mkdir(parents=True)
            (knowledges_dir / "fhn.yaml").write_text(
                json.dumps(
                    {
                        "disease_name": "股骨头坏死",
                        "knowledge_id": "fhn_v0.1",
                        "knowledge_type": "guideline_based",
                        "evidence_level": "high",
                        "clinical_features": {"common_symptoms": ["髋痛"]},
                        "visual_protocol": {"finding_targets": []},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (proposal_dir / "osteoarthritis_or_degenerative_hip_disease.json").write_text(
                json.dumps(
                    {
                        "schema_version": "secondary_knowledge_proposal.v1",
                        "candidate_key": "osteoarthritis_or_degenerative_hip_disease",
                        "disease_name": "骨关节炎或退行性髋关节病变",
                        "proposal_status": "proposal_only",
                        "candidate_status": "selected_for_knowledgebuilder",
                        "knowledge_builder_status": "proposal_prepared",
                        "review_queue_status": "entered_knowledge_review_queue",
                        "diagnosis_allowed": False,
                        "formal_knowledge_updated": False,
                        "knowledge_builder_progress": [
                            {"step": "prepare_knowledge_proposal", "label": "KnowledgeBuilder proposal 已生成并进入审核库", "status": "done"}
                        ],
                        "knowledge_builder_proposal_detail": {
                            "knowledge_id": "osteoarthritis_or_degenerative_hip_disease_guideline_v0.1",
                            "knowledge_type": "guideline_based",
                            "evidence_level": "high",
                            "source_type": "medical_guideline",
                            "expected_evidence_to_check": ["关节间隙是否变窄"],
                            "proposal_artifact_path": str(proposal_dir / "osteoarthritis_or_degenerative_hip_disease.json"),
                        },
                        "proposal_knowledge": {
                            "knowledge_id": "osteoarthritis_or_degenerative_hip_disease_guideline_v0.1",
                            "knowledge_type": "guideline_based",
                            "evidence_level": "high",
                            "source": "ACR Appropriateness Criteria Chronic Hip Pain",
                            "source_documents": [
                                {
                                    "title": "ACR Appropriateness Criteria Chronic Hip Pain",
                                    "url": "https://acsearch.acr.org/docs/69425/Narrative/",
                                    "source_kind": "imaging_appropriateness_guideline",
                                }
                            ],
                            "clinical_features": {"common_symptoms": ["髋痛"]},
                            "required_image_views": ["髋关节 X 光"],
                            "visual_protocol": {"observation_rules": ["关节间隙是否变窄"]},
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status, payload = dispatch_knowledge_request(
                method="GET",
                path="/v1/knowledge",
                knowledges_dir=knowledges_dir,
                output_root=output_root,
            )

            self.assertEqual(status, 200)
            proposal = next(
                item for item in payload["knowledge"]
                if item["knowledge_key"] == "proposal:osteoarthritis_or_degenerative_hip_disease"
            )
            self.assertEqual(proposal["proposal_status"], "proposal_only")
            self.assertEqual(proposal["knowledge_builder_status"], "proposal_prepared")
            self.assertEqual(proposal["review_queue_status"], "entered_knowledge_review_queue")
            self.assertEqual(proposal["doctor_summary"]["symptom_count"], 1)
            self.assertEqual(proposal["doctor_summary"]["image_requirement_count"], 1)
            self.assertEqual(proposal["doctor_summary"]["visual_finding_count"], 1)
            self.assertEqual(proposal["doctor_summary"]["source_count"], 1)
            self.assertEqual(proposal["knowledge_type"], "guideline_based")
            self.assertEqual(proposal["evidence_level"], "high")
            self.assertIn("ACR Appropriateness Criteria", proposal["source"])
            self.assertFalse(proposal["diagnosis_allowed"])
            self.assertFalse(proposal["formal_knowledge_updated"])

            detail_status, detail_payload = dispatch_knowledge_request(
                method="GET",
                path="/v1/knowledge/proposal:osteoarthritis_or_degenerative_hip_disease",
                knowledges_dir=knowledges_dir,
                output_root=output_root,
            )
            self.assertEqual(detail_status, 200)
            self.assertEqual(
                detail_payload["knowledge_key"],
                "proposal:osteoarthritis_or_degenerative_hip_disease",
            )
            self.assertEqual(
                detail_payload["doctor_view"]["identity"]["disease_name"],
                "骨关节炎或退行性髋关节病变",
            )
            self.assertEqual(
                detail_payload["doctor_view"]["clinical_profile"]["common_symptoms"],
                ["髋痛"],
            )
            self.assertEqual(
                detail_payload["doctor_view"]["imaging_requirements"][0]["label"],
                "髋关节 X 光",
            )
            self.assertEqual(
                detail_payload["doctor_view"]["source_documents"][0]["title"],
                "ACR Appropriateness Criteria Chronic Hip Pain",
            )
            self.assertFalse(detail_payload["draft"]["exists"])

    def test_knowledge_detail_translates_knowledge_to_doctor_review_sections(self):
        with TemporaryDirectory() as tmpdir:
            knowledges_dir = Path(tmpdir) / "knowledge"
            knowledges_dir.mkdir()
            (knowledges_dir / "fhn.yaml").write_text(
                json.dumps(
                    {
                        "disease_name": "股骨头坏死",
                        "knowledge_id": "fhn_v0.1",
                        "knowledge_type": "guideline_based",
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

            status, payload = dispatch_knowledge_request(
                method="GET",
                path="/v1/knowledge/fhn",
                knowledges_dir=knowledges_dir,
                output_root=Path(tmpdir) / "output",
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["knowledge_key"], "fhn")
            self.assertEqual(payload["doctor_view"]["identity"]["disease_name"], "股骨头坏死")
            self.assertEqual(payload["doctor_view"]["clinical_profile"]["common_symptoms"], ["髋痛", "活动受限"])
            self.assertEqual(payload["doctor_view"]["imaging_requirements"][0]["label"], "双髋正位 X 光")
            self.assertEqual(payload["doctor_view"]["visual_findings"][0]["display_name"], "硬化带")
            self.assertEqual(payload["doctor_view"]["visual_findings"][0]["doctor_execution_label"], "先定位候选区域，再生成候选分割")
            self.assertEqual(payload["doctor_view"]["staging_rules"][0]["stage"], "ARCO_II")
            self.assertEqual(payload["doctor_view"]["safety_notes"][0]["reason"], "X 光不能排除早期病变")
            self.assertEqual(payload["doctor_view"]["source_documents"][0]["title"], "ONFH guideline")
            self.assertFalse(payload["draft"]["exists"])

    def test_fhn_knowledge_comparison_returns_readable_version_and_xray_coverage_summary(self):
        with TemporaryDirectory() as tmpdir:
            knowledges_dir = Path(tmpdir) / "knowledge"
            baseline_dir = knowledges_dir / "baselines"
            output_root = Path(tmpdir) / "output"
            eval_dir = output_root / "real" / "onfh_coco_protocol_evaluation"
            baseline_dir.mkdir(parents=True)
            eval_dir.mkdir(parents=True)
            (knowledges_dir / "fhn.yaml").write_text(
                json.dumps(
                    {
                        "disease_name": "股骨头坏死",
                        "knowledge_id": "fhn_protocol_v1",
                        "visual_protocol": {
                            "finding_targets": [
                                {
                                    "target": "sclerotic_band",
                                    "display_name": "硬化带",
                                    "execution_mode": "vlm_plus_segmenter",
                                    "diagnosis_usable_level": "candidate_support",
                                },
                                {
                                    "target": "subchondral_fracture",
                                    "display_name": "软骨下骨骨折",
                                    "execution_mode": "vlm_plus_segmenter",
                                    "diagnosis_usable_level": "candidate_support",
                                },
                            ]
                        },
                        "quantitative_evidence_protocol": {
                            "image_feature_quantification": [{"feature_name": "texture_disorder_score"}],
                            "measurement_evidence": [{"measurement_name": "subchondral_fracture_extent"}],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (baseline_dir / "fhn_finding_list_baseline_20260604.yaml").write_text(
                json.dumps(
                    {
                        "disease_name": "股骨头坏死",
                        "knowledge_id": "fhn_finding_list_baseline",
                        "visual_targets": {
                            "lesion_features": ["硬化带", "囊性变", "股骨头塌陷"],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (eval_dir / "onfh_coco_protocol_evaluation.json").write_text(
                json.dumps(
                    {
                        "evaluation_scope": {"primary_modality": "Xray"},
                        "dataset": {"evaluated_annotation_count": 86},
                        "aggregate": {
                            "current_protocol_covered_annotation_count": 86,
                            "baseline_covered_annotation_count": 70,
                        },
                        "coverage_gaps": {"baseline_missing_labels": ["软骨下骨骨折"]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status, payload = dispatch_knowledge_request(
                method="GET",
                path="/v1/knowledge/fhn/comparison",
                knowledges_dir=knowledges_dir,
                output_root=output_root,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["knowledge_key"], "fhn")
            self.assertEqual(payload["title"], "股骨头坏死 Knowledge 版本对比")
            self.assertEqual(payload["versions"][0]["label"], "版本 1：历史 finding-list baseline")
            self.assertFalse(payload["versions"][0]["has_quantitative_protocol"])
            self.assertEqual(payload["versions"][1]["label"], "版本 2：Evidence protocol + quantitative protocol")
            self.assertTrue(payload["versions"][1]["has_quantitative_protocol"])
            self.assertIn("软骨下骨骨折", payload["versions"][1]["finding_names"])
            self.assertIn("新版强在哪", payload["comparison_takeaway"]["title"])
            self.assertIn("软骨下骨骨折", " ".join(payload["comparison_takeaway"]["advantages"]))
            quantification = payload["versions"][1]["quantification_groups"]
            self.assertEqual(quantification[0]["label"], "影像特征量化")
            self.assertEqual(quantification[1]["label"], "几何 / 形态测量")
            self.assertEqual(quantification[1]["items"][0]["name"], "subchondral_fracture_extent")
            self.assertIn("软骨下骨骨折", quantification[1]["items"][0]["human_target"])
            self.assertEqual(payload["evaluation_summary"]["primary_modality"], "Xray")
            self.assertEqual(payload["evaluation_summary"]["current_coverage"], "86/86")
            self.assertEqual(payload["evaluation_summary"]["baseline_coverage"], "70/86")
            self.assertEqual(payload["evaluation_summary"]["baseline_missing_labels"], ["软骨下骨骨折"])
            self.assertIn("覆盖更完整", payload["evaluation_summary"]["interpretation"])
            self.assertNotIn("knowledge_path", payload)
            self.assertNotIn("annotation_id", json.dumps(payload, ensure_ascii=False))

    def test_knowledge_review_draft_is_saved_under_output_fake_without_overwriting_formal_knowledge(self):
        with TemporaryDirectory() as tmpdir:
            knowledges_dir = Path(tmpdir) / "knowledge"
            output_root = Path(tmpdir) / "output"
            knowledges_dir.mkdir()
            knowledge_path = knowledges_dir / "fhn.yaml"
            formal_knowledge = {
                "disease_name": "股骨头坏死",
                "knowledge_id": "fhn_v0.1",
                "knowledge_type": "guideline_based",
                "evidence_level": "high",
                "source": "临床指南",
                "clinical_features": {"common_symptoms": ["髋痛"]},
                "visual_protocol": {"finding_targets": []},
            }
            knowledge_path.write_text(json.dumps(formal_knowledge, ensure_ascii=False), encoding="utf-8")

            status, payload = dispatch_knowledge_request(
                method="POST",
                path="/v1/knowledge/fhn/review-draft",
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
                knowledges_dir=knowledges_dir,
                output_root=output_root,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "draft_saved")
            self.assertEqual(payload["formal_knowledge_updated"], False)
            draft_path = Path(payload["draft_path"])
            self.assertIn("output/fake/knowledge_review_drafts", payload["draft_path"])
            self.assertTrue(draft_path.exists())
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual(draft["reviewer_name"], "张医生")
            self.assertEqual(draft["sections"]["clinical_profile"]["common_symptoms"], ["髋痛", "跛行"])
            self.assertEqual(json.loads(knowledge_path.read_text(encoding="utf-8")), formal_knowledge)

    def test_secondary_knowledge_proposal_can_be_promoted_to_formal_knowledge_library(self):
        with TemporaryDirectory() as tmpdir:
            knowledges_dir = Path(tmpdir) / "knowledge"
            output_root = Path(tmpdir) / "output"
            proposal_dir = output_root / "fake" / "secondary_knowledge_proposals"
            knowledges_dir.mkdir()
            proposal_dir.mkdir(parents=True)
            proposal_path = proposal_dir / "osteoarthritis_or_degenerative_hip_disease.json"
            proposal_knowledge = {
                "disease_name": "骨关节炎或退行性髋关节病变",
                "knowledge_id": "osteoarthritis_or_degenerative_hip_disease_guideline_v0.1",
                "knowledge_type": "guideline_based",
                "evidence_level": "high",
                "source": "internal dataset statistical summary",
                "warning": "该规则来自数据总结，不等同于正式医学指南，只能作为辅助提示",
                "source_documents": [
                    {
                        "title": "ACR Appropriateness Criteria Chronic Hip Pain",
                        "url": "https://acsearch.acr.org/docs/69425/Narrative/",
                        "source_kind": "imaging_appropriateness_guideline",
                    },
                    {
                        "title": "NICE Osteoarthritis in over 16s: diagnosis and management",
                        "url": "https://www.nice.org.uk/guidance/ng226",
                        "source_kind": "clinical_guideline",
                    },
                ],
                "clinical_features": {"common_symptoms": ["髋痛"], "risk_factors": ["年龄增长"]},
                "required_image_views": ["髋关节 X 光"],
                "visual_protocol": {
                    "observation_rules": ["关节间隙是否变窄", "髋臼或股骨头边缘是否有骨赘"],
                    "finding_targets": [
                        {"target": "joint_space_narrowing", "display_name": "关节间隙变窄"}
                    ],
                },
            }
            proposal_path.write_text(
                json.dumps(
                    {
                        "schema_version": "secondary_knowledge_proposal.v1",
                        "candidate_key": "osteoarthritis_or_degenerative_hip_disease",
                        "disease_name": "骨关节炎或退行性髋关节病变",
                        "proposal_status": "proposal_only",
                        "candidate_status": "selected_for_knowledgebuilder",
                        "knowledge_builder_status": "proposal_prepared",
                        "review_queue_status": "entered_knowledge_review_queue",
                        "diagnosis_allowed": False,
                        "formal_knowledge_updated": False,
                        "proposal_knowledge": proposal_knowledge,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status, payload = dispatch_knowledge_request(
                method="POST",
                path="/v1/knowledge/proposal:osteoarthritis_or_degenerative_hip_disease/promote",
                body=json.dumps({"reviewer_name": "张医生"}, ensure_ascii=False).encode("utf-8"),
                knowledges_dir=knowledges_dir,
                output_root=output_root,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "formal_knowledge_saved")
            self.assertTrue(payload["formal_knowledge_updated"])
            formal_path = knowledges_dir / "osteoarthritis_or_degenerative_hip_disease.yaml"
            self.assertEqual(Path(payload["knowledge_path"]), formal_path)
            self.assertTrue(formal_path.exists())
            saved = json.loads(formal_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["disease_name"], "骨关节炎或退行性髋关节病变")
            self.assertEqual(saved["knowledge_type"], "guideline_based")
            self.assertEqual(saved["evidence_level"], "high")
            self.assertIn("ACR Appropriateness Criteria", saved["source"])
            self.assertNotIn("internal dataset", saved["source"])
            self.assertNotIn("数据总结", saved.get("warning", ""))
            self.assertEqual(len(saved["source_documents"]), 2)
            self.assertEqual(saved["source_priority"][0]["title"], "ACR Appropriateness Criteria Chronic Hip Pain")
            self.assertEqual(saved["guideline_source"]["source_catalog_path"], "data/guidelines/guideline_sources.json")
            self.assertEqual(len(saved["guideline_extraction"]["citations"]), 2)
            self.assertEqual(saved["quality_control"]["formal_knowledge_status"], "needs_review")
            self.assertEqual(saved["quality_control"]["citation_status"], "verified")
            self.assertEqual(saved["quality_control"]["citation_count"], 2)
            self.assertEqual(saved["quality_control"]["missing_url_count"], 0)
            self.assertIn("visual_protocol_status", saved["quality_control"])
            self.assertEqual(saved["quality_control"]["promoted_from"], str(proposal_path))
            self.assertEqual(saved["quality_control"]["medical_source_status"], "present_unreviewed")
            self.assertFalse(saved["diagnosis_rules"]["diagnosis_allowed_without_review"])
            self.assertFalse(json.loads(proposal_path.read_text(encoding="utf-8"))["formal_knowledge_updated"])

            list_status, list_payload = dispatch_knowledge_request(
                method="GET",
                path="/v1/knowledge",
                knowledges_dir=knowledges_dir,
                output_root=output_root,
            )
            self.assertEqual(list_status, 200)
            formal = next(
                item for item in list_payload["knowledge"]
                if item["knowledge_key"] == "osteoarthritis_or_degenerative_hip_disease"
            )
            self.assertEqual(formal["review_status"], "no_draft")
            self.assertEqual(formal["knowledge_type"], "guideline_based")
            self.assertEqual(formal["evidence_level"], "high")
            self.assertIn("ACR Appropriateness Criteria", formal["source"])

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
                knowledge_memory={"selected_knowledge": "diffuse_glioma_brats"},
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
                knowledge_memory={"selected_knowledge": "diffuse_glioma_brats"},
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

    def test_public_safe_demo_endpoint_generates_suite_without_real_data(self):
        with TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"

            status, payload = dispatch_demo_request(
                method="GET",
                path="/v1/demo/public-safe",
                output_root=output_root,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["demo_name"], "public_safe_medscope_mvp_demo")
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["safety"]["real_fhn_data_required"], False)
            self.assertEqual(payload["safety"]["not_clinical_diagnosis"], True)
            self.assertEqual(payload["demo_source"], "public_safe_demo_suite")
            self.assertIn("reply_to_patient", payload)
            self.assertIn("report", payload)
            self.assertIn("image_outputs", payload)
            self.assertIn("memory_audit", payload)
            self.assertIn("public_safe_demo_summary", payload)
            self.assertEqual(
                payload["routing_decision"]["selected_knowledge"],
                "femoral_head_necrosis",
            )
            self.assertTrue(Path(payload["response_path"]).exists())
            self.assertTrue(Path(payload["evidence_bundle_path"]).exists())
            self.assertTrue(Path(payload["memory_audit_path"]).exists())
            self.assertTrue(Path(payload["qa_response_path"]).exists())
            self.assertIn(
                str(output_root / "fake" / "public_safe_demo_suite"),
                payload["suite_output_dir"],
            )

    def test_public_safe_demo_qa_answers_from_demo_artifact_not_live_memory(self):
        with TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            setup_status, setup_payload = dispatch_demo_request(
                method="GET",
                path="/v1/demo/public-safe",
                output_root=output_root,
            )

            status, payload = dispatch_demo_request(
                method="POST",
                path="/v1/demo/public-safe/qa",
                body=json.dumps(
                    {"patient_message": "下一步应该做什么？"},
                    ensure_ascii=False,
                ).encode("utf-8"),
                output_root=output_root,
            )

            self.assertEqual(setup_status, 200)
            self.assertEqual(status, 200)
            self.assertEqual(payload["case_id"], setup_payload["case_id"])
            self.assertEqual(payload["intent"], "qa")
            self.assertEqual(payload["demo_source"], "public_safe_demo_suite")
            self.assertEqual(payload["qa_source"], "public_safe_demo_artifact")
            self.assertIn("public-safe", payload["reply_to_patient"])
            self.assertIn("evidence_bundle", payload)
            self.assertIn("memory_audit", payload)
            self.assertIn("memory_replay", payload)
            self.assertEqual(
                payload["memory_replay"]["steps"][-1]["agent"],
                "GaoDoctorAgent QA",
            )
            self.assertTrue(payload["memory_audit"]["trace_consistency"]["qa_extension_present"])

    def test_fhn_no_mask_demo_response_backfills_structured_protocol_report(self):
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
            (artifacts_dir / "fhn_no_mask_multifinding_response.json").write_text(
                json.dumps(
                    {
                        "case_id": "case_demo",
                        "routing_decision": {
                            "selected_knowledge": "femoral_head_necrosis",
                            "selected_vision_mode": "no_mask_knowledge",
                        },
                        "alignment_plan": {
                            "required_next_images": [
                                {
                                    "modality": "MRI",
                                    "region": "双髋关节",
                                    "reason": "早期股骨头坏死需要 MRI 评估。",
                                }
                            ],
                            "insufficiency_reasons": ["X 光不能排除早期股骨头坏死。"],
                        },
                        "report": {
                            "case_id": "case_demo",
                            "诊断倾向": "疑似股骨头坏死影像表现，需 MRI 和影像科复核",
                            "visual_fact_usage": {
                                "used": [
                                    {
                                        "target": "sclerotic_band",
                                        "display_name": "硬化带",
                                        "summary_text": "右侧股骨头上外侧带状密度增高候选区",
                                        "diagnosis_usable": True,
                                        "quality_level": "medium",
                                    }
                                ],
                                "excluded": [
                                    {
                                        "target": "cystic_change",
                                        "display_name": "囊性变",
                                        "exclusion_reason": "non_independent_evidence",
                                        "diagnosis_usable": False,
                                    }
                                ],
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status, response = dispatch_demo_request(
                method="GET",
                path="/v1/demo/standard/cases/fhn_no_mask_multifinding/response",
                output_root=output_root,
            )

        self.assertEqual(status, 200)
        report = response["report"]
        self.assertIn("target_disease_assessment", report)
        self.assertIn("imaging_evidence_summary", report)
        self.assertIn("quantitative_evidence_summary", report)
        self.assertIn("clinical_context_assessment", report)
        self.assertIn("missing_evidence", report)
        self.assertIn("modality_limitations", report)
        self.assertIn("recommendation", report)
        self.assertEqual(
            report["target_disease_assessment"]["target_disease"],
            "femoral_head_necrosis",
        )
        self.assertEqual(len(report["imaging_evidence_summary"]["usable_items"]), 1)
        self.assertEqual(len(report["imaging_evidence_summary"]["nonspecific_items"]), 1)
        self.assertTrue(any("MRI" in item for item in report["recommendation"]))

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
                json.dumps({"route": "dmx", "model": "gpt-5.5"}),
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
            self.assertEqual(raw["model"], "gpt-5.5")
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
                    "knowledge_memory",
                    "reasoning_memory",
                ],
            )
            self.assertEqual(response["memory_audit"]["memory_type_details"]["patient_memory"]["intent"], "diagnosis")
            self.assertEqual(
                response["memory_audit"]["memory_type_details"]["knowledge_memory"]["selected_knowledge"],
                "diffuse_glioma_brats",
            )
            self.assertEqual(
                response["memory_audit"]["agents_traced"],
                [
                    "GaoDoctorAgent",
                    "KnowledgeBuilderAgent",
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
            self.assertEqual(response["memory_replay"]["steps"][1]["event"], "knowledge_routing")
            self.assertEqual(response["memory_replay"]["steps"][1]["memory_scope"], "knowledge_memory")
            self.assertEqual(response["memory_replay"]["steps"][1]["decision_owner"], "orchestrator_api")
            self.assertEqual(
                response["memory_replay"]["steps"][1]["knowledge_builder_action"],
                "load_existing_knowledge",
            )
            self.assertEqual(response["memory_replay"]["steps"][2]["agent"], "KnowledgeBuilderAgent")
            self.assertEqual(response["memory_replay"]["steps"][2]["event"], "knowledge_loading")
            self.assertEqual(response["memory_replay"]["steps"][2]["memory_scope"], "knowledge_memory")
            self.assertEqual(response["memory_replay"]["steps"][2]["action"], "load_existing_knowledge")
            self.assertEqual(response["memory_replay"]["steps"][2]["selected_knowledge"], "diffuse_glioma_brats")
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
            self.assertEqual(response["memory_replay"]["steps"][-1]["memory_scope"], "patient_memory,image_memory,knowledge_memory,reasoning_memory")
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
                        "model": "gpt-5.5",
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
                json.dumps({"route": "dmx", "model": "gpt-5.5"}),
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
                    "KnowledgeBuilderAgent",
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
                payload["alignment_plan"]["selected_knowledge"],
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
            self.assertEqual(payload["memory_replay"]["steps"][1]["event"], "knowledge_routing")
            self.assertEqual(payload["memory_replay"]["steps"][1]["memory_scope"], "knowledge_memory")
            self.assertEqual(payload["memory_replay"]["steps"][1]["decision_owner"], "orchestrator_api")
            self.assertEqual(
                payload["memory_replay"]["steps"][1]["knowledge_builder_action"],
                "load_existing_knowledge",
            )
            self.assertEqual(payload["memory_replay"]["steps"][2]["agent"], "KnowledgeBuilderAgent")
            self.assertEqual(payload["memory_replay"]["steps"][2]["event"], "knowledge_loading")
            self.assertEqual(payload["memory_replay"]["steps"][2]["memory_scope"], "knowledge_memory")
            self.assertEqual(payload["memory_replay"]["steps"][2]["action"], "load_existing_knowledge")
            self.assertEqual(payload["memory_replay"]["steps"][2]["selected_knowledge"], "diffuse_glioma_brats")
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
                        "KnowledgeBuilderAgent",
                        "VisionAgent",
                        "DiagnosisDoctorAgent",
                        "MemoryManager",
                    ],
                    "agent_io_summary": {
                        "GaoDoctorAgent": {"input": "demo"},
                        "KnowledgeBuilderAgent": {"output": "femoral_head_necrosis"},
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

    def test_post_medscope_returns_orchestrator_knowledge_routing_decision(self):
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
        self.assertEqual(payload["routing_decision"]["selected_knowledge"], "diffuse_glioma_brats")
        self.assertEqual(payload["routing_decision"]["agent_scope"], "orchestrator_api")
        self.assertEqual(
            payload["routing_decision"]["knowledge_builder_action"],
            "load_existing_knowledge",
        )

    def test_post_medscope_returns_knowledge_proposal_when_selected_knowledge_is_missing(self):
        class MissingProposalKnowledgeTool:
            def load_guideline_knowledge(self, disease_key):
                raise FileNotFoundError(disease_key)

            def prepare_knowledge(self, **kwargs):
                return {
                    "knowledge_id": f"{kwargs['disease_key']}_proposal_v0.1",
                    "disease_name": kwargs["disease_name"],
                    "knowledge_type": "data_mined_hypothesis",
                    "source_type": "internal_dataset_summary",
                    "evidence_level": "low",
                }

        fake_doctor = FakeGaoDoctor()
        service = MedScopeService(
            gaodoctor_agent=fake_doctor,
            knowledge_tool=MissingProposalKnowledgeTool(),
        )
        status, payload = dispatch_http_request(
            method="POST",
            path="/v1/medscope",
            body=json.dumps(
                {
                    "patient_message": "左髋疼痛，考虑罕见髋部疾病，请根据指南评估",
                    "image_path": "output/fake/uploads/rare_hip_xray.png",
                    "disease_key": "rare_hip_disorder",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            service_factory=lambda: service,
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["intent"], "knowledge_proposal")
        self.assertEqual(payload["analysis_status"], "knowledge_proposal_required")
        self.assertEqual(
            payload["routing_decision"]["knowledge_builder_action"],
            "search_or_generate_knowledge",
        )
        self.assertFalse(payload["knowledge_builder_proposal"]["diagnosis_allowed"])
        self.assertFalse(payload["knowledge_builder_proposal"]["formal_update_allowed"])
        self.assertEqual(fake_doctor.calls, [])

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
                payload["routing_decision"]["selected_knowledge"],
                "diffuse_glioma_brats",
            )
            self.assertEqual(
                payload["routing_decision"]["selected_vision_mode"],
                "ground_truth",
            )
            self.assertEqual(payload["routing_decision"]["agent_scope"], "orchestrator_api")
            self.assertEqual(
                payload["routing_decision"]["knowledge_builder_action"],
                "load_existing_knowledge",
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
        self.assertEqual(payload["routing_decision"]["selected_knowledge"], "diffuse_glioma_brats")
        self.assertEqual(payload["routing_decision"]["selected_vision_mode"], "medsam2")
        self.assertFalse(payload["medsam2_configuration"]["command_template_present"])
        self.assertFalse(payload["medsam2_configuration"]["real_call_ready"])
        self.assertIn("MEDSAM2_COMMAND_TEMPLATE", " ".join(payload["action_items"]))

    def test_post_medscope_returns_503_for_transient_vlm_ssl_disconnect_without_raw_report_error(self):
        status, payload = dispatch_http_request(
            method="POST",
            path="/v1/medscope",
            body=json.dumps(
                {
                    "patient_message": "右髋疼痛三个月，请做人工备用 Knowledge 复查。",
                    "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
                    "patient_info": {"symptoms": ["髋关节疼痛"]},
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            service_factory=SslEofService,
        )

        self.assertEqual(status, 503)
        self.assertEqual(payload["error_type"], "vlm_api_unavailable")
        self.assertIn("VLM/API 临时不可用", payload["error"])
        self.assertIn("稍后重试", " ".join(payload["action_items"]))
        self.assertIn("UNEXPECTED_EOF_WHILE_READING", payload["technical_detail"])
        self.assertNotIn("<urlopen error", payload["error"])

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
