const state = {
  caseId: "",
  lastPayload: {},
  sampleMaskPath: "data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz",
  useSampleMask: false,
  sampleDiseaseKey: "",
  sampleVisionMode: "",
  demoCaseSlug: "",
  sampleKnowledgeSelectionMode: "",
  sampleManualSecondaryKnowledges: [],
  realDemoMode: false,
  publicSafeDemoMode: false,
  casePending: false,
  qaPending: false,
  qaAbortController: null,
  qaPendingItem: null,
  qaPendingQuestion: "",
  caseProgressTimer: null,
  caseProgressStartedAt: 0,
  caseProgressLabel: "",
  selectedKnowledgeKey: "",
  selectedKnowledgeDetail: {},
  sampleEvidenceProtocolMode: "finding_list_baseline",
  uploadedImagePaths: [],
  uploadedImageNames: [],
  activeWorkspaceView: "clinical",
  selectedArchitectureModule: "clinical_orchestrator",
  selectedOptimizationDirection: "guideline_knowledge_structure",
};

const elements = {
  statusText: document.getElementById("statusText"),
  healthButton: document.getElementById("healthButton"),
  clinicalDemoTab: document.getElementById("clinicalDemoTab"),
  architectureRoadmapTab: document.getElementById("architectureRoadmapTab"),
  clinicalDemoView: document.getElementById("clinicalDemoView"),
  architectureRoadmapPanel: document.getElementById("architectureRoadmapPanel"),
  architectureDiagramView: document.getElementById("architectureDiagramView"),
  architectureModuleList: document.getElementById("architectureModuleList"),
  architectureDetailView: document.getElementById("architectureDetailView"),
  optimizationDirectionList: document.getElementById("optimizationDirectionList"),
  optimizationDirectionDetail: document.getElementById("optimizationDirectionDetail"),
  roadmapTodoView: document.getElementById("roadmapTodoView"),
  sampleGliomaButton: document.getElementById("sampleGliomaButton"),
  publicSafeDemoButton: document.getElementById("publicSafeDemoButton"),
  realVlmMedSAM2Button: document.getElementById("realVlmMedSAM2Button"),
  evidenceGatewaySnapshotButton: document.getElementById("evidenceGatewaySnapshotButton"),
  xrayInsufficientButton: document.getElementById("xrayInsufficientButton"),
  fhnNoMaskButton: document.getElementById("fhnNoMaskButton"),
  autoRoutingRiskCompareButton: document.getElementById("autoRoutingRiskCompareButton"),
  caseForm: document.getElementById("caseForm"),
  qaForm: document.getElementById("qaForm"),
  submitButton: document.getElementById("submitButton"),
  resetButton: document.getElementById("resetButton"),
  dropZone: document.getElementById("dropZone"),
  fileInput: document.getElementById("fileInput"),
  uploadStatus: document.getElementById("uploadStatus"),
  patientMessage: document.getElementById("patientMessage"),
  imageModality: document.getElementById("imageModality"),
  imagePath: document.getElementById("imagePath"),
  symptoms: document.getElementById("symptoms"),
  knowledgeSelectionMode: document.getElementById("knowledgeSelectionMode"),
  evidenceProtocolMode: document.getElementById("evidenceProtocolMode"),
  manualSecondaryKnowledges: document.getElementById("manualSecondaryKnowledges"),
  qaInput: document.getElementById("qaInput"),
  qaSubmitButton: document.getElementById("qaSubmitButton"),
  reportView: document.getElementById("reportView"),
  visualMeta: document.getElementById("visualMeta"),
  lesionFigure: document.getElementById("lesionFigure"),
  caseIdBadge: document.getElementById("caseIdBadge"),
  intentBadge: document.getElementById("intentBadge"),
  alignmentView: document.getElementById("alignmentView"),
  evidenceView: document.getElementById("evidenceView"),
  auditView: document.getElementById("auditView"),
  qaLog: document.getElementById("qaLog"),
  refreshKnowledgesButton: document.getElementById("refreshKnowledgesButton"),
  saveKnowledgeDraftButton: document.getElementById("saveKnowledgeDraftButton"),
  promoteKnowledgeButton: document.getElementById("promoteKnowledgeButton"),
  knowledgeListView: document.getElementById("knowledgeListView"),
  knowledgeDetailView: document.getElementById("knowledgeDetailView"),
  knowledgeReviewStatus: document.getElementById("knowledgeReviewStatus"),
  knowledgeProtocolComparisonView: document.getElementById("knowledgeProtocolComparisonView"),
  researchEvidenceReviewView: document.getElementById("researchEvidenceReviewView"),
};

const knowledgeComparisonFallbackLabels = {
  finding_list_baseline: "版本 1：历史 finding-list baseline",
  evidence_protocol_v1: "版本 2：Evidence protocol + quantitative protocol",
};

const architectureRoadmapData = {
  statusLabels: {
    done: "done",
    in_progress: "in_progress",
    parked: "parked",
    frozen: "frozen",
    deferred: "deferred",
  },
  modules: [
    {
      key: "clinical_orchestrator",
      title: "Clinical Orchestrator",
      short: "高医生入口：识别 ONFH 筛查场景、选择 Knowledge、协调流程。",
      positioning: "高医生入口：把髋部症状和髋关节影像转成 ONFH 证据分析任务，决定是否进入股骨头坏死主线或鉴别复查。",
      inputs: ["患者描述", "髋关节影像类型", "部位和症状", "ONFH 风险因素"],
      outputs: ["ONFH 主要怀疑方向（primary hypothesis）", "选中的 Knowledge（selected_knowledge）", "鉴别复查候选（differential candidates）", "选择理由（routing reason）"],
      boundaries: ["不做全病种自动诊断", "不直接诊断", "不把 Knowledge 选择当成确诊结论"],
      status: "in_progress",
      todo: ["补充“髋部 + 图像类型 + 症状 + 风险因素”的 ONFH 路由表", "统一 Knowledge 选择结果格式"],
    },
    {
      key: "vision_evidence_agent",
      title: "Vision Evidence Agent",
      short: "从图片里提取证据，不负责下诊断。",
      positioning: "从髋关节影像里提取 ONFH 证据：按 Knowledge 要求找硬化带、囊性变、塌陷/新月征等可疑区域，生成候选分割，并输出可读的结构化数值。",
      inputs: ["髋关节原始图像（raw image）", "ONFH Knowledge 或鉴别 Knowledge", "看什么的清单（visual checklist）"],
      outputs: ["视觉证据（visual evidence）", "候选病灶图 / mask", "面积、比例、位置等数值（measurement）", "证据质量和缺失项"],
      boundaries: ["不直接输出诊断", "不把不稳定的候选框当成确定病灶"],
      status: "in_progress",
      todo: ["继续优化 ONFH X 光征象候选定位", "补 mask 质量检查", "真实量化先等 VisionAgent 稳定"],
    },
    {
      key: "diagnosis_reasoning_agent",
      title: "Diagnosis Reasoning Agent",
      short: "判断还能不能下结论，只能使用证据包。",
      positioning: "判断 ONFH 筛查和分期辅助能说到哪一步：只根据 evidence_bundle 和指南规则生成有边界的报告。",
      inputs: ["患者信息（patient info）", "选中的 Knowledge", "证据包（evidence_bundle）", "指南规则（guideline rules）"],
      outputs: ["是否支持 ONFH", "可能分期边界", "缺少什么", "哪些表现不特异", "下一步建议"],
      boundaries: ["不直接看原图", "不重新选择 Knowledge", "不补全证据包里没有的内容"],
      status: "in_progress",
      todo: ["用人工标注生成的 evidence_bundle 验证推理", "继续收紧缺失证据表达"],
    },
    {
      key: "knowledge_builder_guideline_agent",
      title: "Knowledge Builder / Guideline Agent",
      short: "缺少 Knowledge 时，找指南并生成候选 Knowledge。",
      positioning: "主线优先维护 ONFH Knowledge；缺少鉴别复查或扩展资料时，检索权威指南，把指南整理成候选 Knowledge 和视觉检查清单。",
      inputs: ["ONFH 或鉴别疾病名", "图像类型", "指南来源"],
      outputs: ["候选 Knowledge", "视觉检查清单", "待审核草稿（proposal）"],
      boundaries: ["不自动覆盖正式 Knowledge", "候选草稿必须人工审核"],
      status: "in_progress",
      todo: ["保持只生成草稿", "完善指南来源追溯", "继续强化 Evidence Gateway 安全边界"],
    },
    {
      key: "memory_audit_layer",
      title: "Memory & Audit Layer",
      short: "底层记录层：病例、图像、Knowledge、推理和证据包。",
      positioning: "底层基础设施，不是 Agent；负责记录全链路，方便回放、审计和追问。",
      inputs: ["患者记忆（patient memory）", "图像记忆（image memory）", "Knowledge 记忆", "推理记忆", "证据包存档"],
      outputs: ["审计记录", "病例回放", "追问依据"],
      boundaries: ["不参与诊断推理", "不改变 evidence_bundle 的证据边界"],
      status: "in_progress",
      todo: ["增强前端 audit 可读性", "把四类 memory 的来源和时间线展示得更清楚"],
    },
    {
      key: "evidence_bundle",
      title: "evidence_bundle",
      short: "把视觉结果打包成证据包（evidence_bundle）。",
      positioning: "核心对象：把视觉证据、患者信息、缺失证据和来源记录打包，交给诊断 Agent。",
      inputs: ["患者上下文", "视觉证据", "测量数值", "质量判断", "缺失证据", "来源记录"],
      outputs: ["可用于诊断的证据", "缺失证据矩阵", "可审计来源"],
      boundaries: ["不包含未经观察支持的诊断结论", "不把论文证据当成指南证据"],
      status: "in_progress",
      todo: ["完善人工标注证据包", "补患者上下文来源追溯"],
    },
  ],
  optimizationDirections: [
    {
      key: "guideline_knowledge_structure",
      title: "ONFH Guideline Knowledge 结构扩展",
      progress: 84,
      status: "in_progress",
      summary: "ONFH 指南 Knowledge 升级：把“要看什么、怎么量化、缺什么证据”写清楚。",
      completed: [
        "影像证据清单（Imaging evidence）：告诉视觉 Agent 要找哪些征象",
        "可量化指标（Measurement）：面积、比例、位置等能转成数值的内容",
        "鉴别诊断（Differential diagnosis）：哪些相似疾病需要排除",
        "患者背景（Clinical context）：激素、饮酒、外伤等只能作为风险线索",
        "综合判断规则（Reasoning rules）：明确哪些证据足够，哪些证据不足",
      ],
      todo: [
        "统一 Knowledge 格式和校验器",
        "沉淀 ONFH 专病 Knowledge 模板",
        "未来接入 Annotation-derived Evidence Bundle v1",
      ],
      limits: [
        "真实 ROI、轮廓、关键点质量检查还不稳定",
        "真实可靠测量引擎还未完成",
      ],
      recovery: "等 VisionAgent 稳定后恢复 Real X-ray Case Comparison。",
      safety: "Knowledge 只定义证据需求，不替代真实测量模型。",
    },
    {
      key: "clinical_context",
      title: "患者临床信息结合",
      progress: 76,
      status: "in_progress",
      summary: "把症状和风险因素放进证据包，但只改变怀疑程度。",
      completed: [
        "患者描述和风险因素进入临床背景（clinical context）",
        "激素、饮酒、外伤史只能提高或降低怀疑程度",
        "不能替代影像证据确诊",
      ],
      todo: [
        "结构化抽取疼痛部位、左右侧、持续时间、活动后加重",
        "抽取激素使用、饮酒史、外伤史",
        "missing context 标记 unknown",
        "report / memory / QA 中显示来源和限制",
      ],
      limits: ["不做完整问诊系统", "不做复杂风险评分模型"],
      recovery: "当病例展示需要更强临床上下文时推进 v2。",
      safety: "临床风险只改变怀疑程度（clinical risk changes suspicion level only），不能替代影像或指南证据。",
    },
    {
      key: "knowledge_routing",
      title: "ONFH 主线候选假设 / Knowledge Routing",
      progress: 84,
      status: "done",
      summary: "v1 完成：系统不做全病种诊断，只做 ONFH-first 路由；其他髋关节 Knowledge 作为假阳性抑制器和鉴别复查候选。",
      completed: [
        "用户没明确说股骨头坏死时，可根据髋痛 + X-ray 生成主要怀疑方向",
        "自动选择 FHN knowledge",
        "保留骨关节炎、外伤后改变、DDH 相关退变等备用可能性（differential candidates）",
        "备用髋关节 Knowledge 用于检查 ONFH 阳性征象是否存在更合理的替代解释，从而降低假阳性",
        "前端提示 routing 不是诊断结论",
      ],
      todo: [
        "统一路由输出格式",
        "补一个轻量的“部位 + 图像类型 + 症状”路由表",
        "未来可做 Differential Knowledge Run v1：输出 false_positive_risk 和 alternative_explanation_strength",
      ],
      limits: ["不做完整多疾病排序", "不做全病种自动诊断", "不自动运行所有 differential candidates"],
      recovery: "当主线 demo 稳定后，再扩展 differential knowledge run。",
      safety: "routing 是流程选择，不是最终诊断。",
    },
    {
      key: "research_evidence",
      title: "论文证据安全补充 Guideline Knowledge",
      progress: 88,
      status: "frozen",
      summary: "论文证据只能做补充建议，不能直接变成指南规则。",
      completed: [
        "论文证据生成器（Research Evidence Builder）",
        "论文证据草稿（Research Evidence Proposal）",
        "PubMed 摘要和元数据读取",
        "证据安全门（Evidence Gateway）",
        "来源质量、时效性、适用性和冲突检查",
        "人工审核清单",
        "前端 Research Evidence Review",
        "只生成草稿（proposal-only）",
        "不写入正式 Knowledge（formal_update=false）",
      ],
      todo: [
        "按需触发 Research Evidence Retrieval：只有 guideline knowledge 不足、出现 evidence gap、需要量化 protocol 或 differential clue 时才检索",
        "Research Evidence Ingestion production v2",
        "全文 PDF parser",
        "正式人工审批系统",
      ],
      limits: [
        "默认诊断流程不固定检索论文",
        "不做 production PubMed 检索质量评估",
        "不做 knowledge registry 写入",
        "不做真实 apply controlled extension",
      ],
      recovery: "等 Guideline Knowledge 主线和 annotation-derived evidence bundle 稳定后再恢复。",
      safety: "research evidence is not guideline evidence；按需检索只补 evidence gap；不进入 diagnosis rules；不自动修改正式 knowledge。",
    },
  ],
  todos: [
    {
      title: "Annotation-derived Evidence Bundle v1",
      priority: "高优先级",
      status: "in_progress",
      description: "使用已有 ONFH X-ray COCO / 人工标注生成结构化 evidence bundle，绕开 VisionAgent 自动分割不稳定问题，验证 DiagnosisAgent 在可靠 evidence 下的推理正确性。",
    },
    {
      title: "Clinical Context Evidence v2",
      priority: "中优先级",
      status: "deferred",
      description: "进一步结构化患者症状、不良习惯、风险因素和缺失信息。",
    },
    {
      title: "FHN X-ray Quantification / Measurement Protocol v2",
      priority: "中低优先级",
      status: "deferred",
      description: "等 ROI / contour / landmark / mask QC 更稳定后，再推进真实塌陷程度、坏死面积比例、骨小梁紊乱程度等量化执行。",
    },
    {
      title: "Real X-ray Case Comparison",
      priority: "暂存",
      status: "parked",
      description: "旧版“征象列表 Knowledge”和新版“证据包 Knowledge”的病例级对比暂存，原因是 VisionAgent 真实定位、分割、量化还不稳定。",
    },
    {
      title: "Research Evidence Ingestion production v2",
      priority: "冻结",
      status: "frozen",
      description: "论文证据 v1 已收敛，production PubMed/PDF/approval workflow 暂缓；后续改成 evidence gap 触发的按需检索，而不是每次诊断固定检索。",
    },
  ],
};

function setWorkspaceView(viewName) {
  const isArchitecture = viewName === "architecture";
  state.activeWorkspaceView = isArchitecture ? "architecture" : "clinical";
  elements.clinicalDemoView.hidden = isArchitecture;
  elements.architectureRoadmapPanel.hidden = !isArchitecture;
  elements.clinicalDemoView.classList.toggle("active", !isArchitecture);
  elements.architectureRoadmapPanel.classList.toggle("active", isArchitecture);
  elements.clinicalDemoTab.classList.toggle("active", !isArchitecture);
  elements.architectureRoadmapTab.classList.toggle("active", isArchitecture);
  elements.clinicalDemoTab.setAttribute("aria-selected", String(!isArchitecture));
  elements.architectureRoadmapTab.setAttribute("aria-selected", String(isArchitecture));
  if (isArchitecture) {
    renderArchitectureRoadmap();
    if (window.location.hash !== "#architecture-roadmap") {
      window.history.replaceState(null, "", "#architecture-roadmap");
    }
    return;
  }
  if (window.location.hash === "#architecture-roadmap") {
    window.history.replaceState(null, "", window.location.pathname);
  }
}

function renderArchitectureRoadmap() {
  renderArchitectureDiagram();
  renderArchitectureModules();
  renderOptimizationDirections();
  renderRoadmapTodos();
}

function renderArchitectureDiagram() {
  elements.architectureDiagramView.innerHTML = `
    <div class="architecture-flow-diagram pipeline-poster" role="img" aria-label="MedScope guideline-aware evidence pipeline poster">
      <section class="poster-card poster-input poster-flow-node-compact">
        <strong>模拟输入</strong>
        <span>患者上传 X 光 + 主诉</span>
      </section>

      <div class="poster-main-flow">
        <button type="button" data-architecture-module="clinical_orchestrator" data-scroll-target="architectureDetailView" class="poster-card poster-flow-node-compact">
          <span class="poster-step">1</span>
          <strong>Clinical Orchestrator</strong>
          <em>分诊 / 选 Knowledge</em>
        </button>
        <span class="poster-flow-arrow-inline" aria-hidden="true">→</span>
        <button type="button" data-architecture-module="vision_evidence_agent" data-scroll-target="architectureDetailView" class="poster-card poster-flow-node-compact">
          <span class="poster-step">2</span>
          <strong>Vision Evidence Agent</strong>
          <em>从图像提证据</em>
        </button>
        <span class="poster-flow-arrow-inline" aria-hidden="true">→</span>
        <button type="button" data-architecture-module="evidence_bundle" data-scroll-target="architectureDetailView" class="poster-card poster-flow-node-compact poster-bundle-compact">
          <span class="poster-step">核心</span>
          <strong>evidence_bundle</strong>
          <em>证据包</em>
        </button>
        <span class="poster-flow-arrow-inline" aria-hidden="true">→</span>
        <button type="button" data-architecture-module="diagnosis_reasoning_agent" data-scroll-target="architectureDetailView" class="poster-card poster-flow-node-compact poster-diagnosis-compact">
          <span class="poster-step">3</span>
          <strong>Diagnosis Reasoning Agent</strong>
          <em>判断能不能下结论</em>
        </button>
      </div>

      <div class="poster-support-flow">
        <button type="button" data-architecture-module="knowledge_builder_guideline_agent" data-scroll-target="architectureDetailView" class="poster-card poster-flow-node-compact poster-knowledge-compact">
          <span class="poster-step">4</span>
          <strong>Knowledge Builder / Guideline Agent</strong>
          <em>缺 Knowledge 时找指南</em>
        </button>
        <span class="poster-flow-arrow-inline poster-flow-arrow-return" aria-hidden="true">↗</span>
        <button type="button" data-architecture-module="memory_audit_layer" data-scroll-target="architectureDetailView" class="poster-card poster-flow-node-compact poster-memory-compact">
          <span class="poster-step">5</span>
          <strong>Memory & Audit Layer</strong>
          <em>记录 / 回放 / 审计</em>
        </button>
      </div>

      <section class="poster-optimization-inline" aria-label="Optimization Directions">
        <strong>优化方向</strong>
        ${renderPosterOptimizationButtons()}
      </section>
    </div>
  `;
}

function renderPosterOptimizationButtons() {
  return architectureRoadmapData.optimizationDirections.map((direction) => `
    <button
      type="button"
      class="poster-optimization-button poster-flow-node-compact"
      data-optimization-direction="${escapeHtml(direction.key)}"
      data-scroll-target="optimizationDirectionDetail"
    >
      <span>${escapeHtml(String(direction.progress))}%</span>
      <strong>${escapeHtml(direction.title)}</strong>
    </button>
  `).join("");
}

function renderArchitectureModules() {
  elements.architectureModuleList.innerHTML = architectureRoadmapData.modules.map((module) => `
    <button
      type="button"
      class="architecture-module-card ${module.key === state.selectedArchitectureModule ? "selected" : ""}"
      data-architecture-module="${escapeHtml(module.key)}"
      data-scroll-target="architectureDetailView"
    >
      <strong>${escapeHtml(module.title)}</strong>
      <span>${escapeHtml(module.short)}</span>
      ${renderStatusBadge(module.status)}
    </button>
  `).join("");
  selectArchitectureModule(state.selectedArchitectureModule, {skipListRender: true});
}

function selectArchitectureModule(moduleKey, options = {}) {
  const module = architectureRoadmapData.modules.find((item) => item.key === moduleKey)
    || architectureRoadmapData.modules[0];
  state.selectedArchitectureModule = module.key;
  if (!options.skipListRender) {
    Array.from(document.querySelectorAll("[data-architecture-module]")).forEach((node) => {
      node.classList.toggle("selected", node.dataset.architectureModule === module.key);
    });
  }
  elements.architectureDetailView.innerHTML = `
    <article class="architecture-detail-card">
      <div class="architecture-detail-heading">
        <h3>${escapeHtml(module.title)}</h3>
        ${renderStatusBadge(module.status)}
      </div>
      <p>${escapeHtml(module.positioning)}</p>
      ${renderRoadmapSection("输入", module.inputs)}
      ${renderRoadmapSection("输出", module.outputs)}
      ${renderRoadmapSection("不做什么 / 安全边界", module.boundaries)}
      ${renderRoadmapSection("TODO / 后续优化", module.todo)}
    </article>
  `;
  if (options.scroll) {
    scrollArchitectureTarget("architectureDetailView");
  }
}

function renderOptimizationDirections() {
  elements.optimizationDirectionList.innerHTML = architectureRoadmapData.optimizationDirections.map((direction) => `
    <button
      type="button"
      class="optimization-card ${direction.key === state.selectedOptimizationDirection ? "selected" : ""}"
      data-optimization-direction="${escapeHtml(direction.key)}"
      data-scroll-target="optimizationDirectionDetail"
    >
      <span>${renderStatusBadge(direction.status)}</span>
      <strong>${escapeHtml(direction.title)}</strong>
      <em>${escapeHtml(direction.summary)}</em>
      ${renderProgress(direction.progress)}
    </button>
  `).join("");
  selectOptimizationDirection(state.selectedOptimizationDirection, {skipListRender: true});
}

function selectOptimizationDirection(directionKey, options = {}) {
  const direction = architectureRoadmapData.optimizationDirections.find((item) => item.key === directionKey)
    || architectureRoadmapData.optimizationDirections[0];
  state.selectedOptimizationDirection = direction.key;
  if (!options.skipListRender) {
    Array.from(document.querySelectorAll("[data-optimization-direction]")).forEach((node) => {
      node.classList.toggle("selected", node.dataset.optimizationDirection === direction.key);
    });
  }
  elements.optimizationDirectionDetail.innerHTML = `
    <article class="optimization-detail-card">
      <div class="architecture-detail-heading">
        <h3>${escapeHtml(direction.title)}</h3>
        ${renderStatusBadge(direction.status)}
      </div>
      <p>${escapeHtml(direction.summary)}</p>
      ${renderProgress(direction.progress)}
      ${renderRoadmapSection("已完成内容", direction.completed)}
      ${renderRoadmapSection("TODO", direction.todo)}
      ${renderRoadmapSection("暂存 / 冻结内容", direction.limits)}
      <section class="roadmap-note"><strong>后续恢复条件</strong><p>${escapeHtml(direction.recovery)}</p></section>
      <section class="roadmap-note"><strong>安全边界</strong><p>${escapeHtml(direction.safety)}</p></section>
    </article>
  `;
  if (options.scroll) {
    scrollArchitectureTarget("optimizationDirectionDetail");
  }
}

function scrollArchitectureTarget(targetId) {
  const target = document.getElementById(targetId);
  if (!target) {
    return;
  }
  target.scrollIntoView({behavior: "smooth", block: "start"});
}

function renderRoadmapTodos() {
  elements.roadmapTodoView.innerHTML = architectureRoadmapData.todos.map((todo) => `
    <article class="roadmap-todo-card">
      <div>
        <span class="roadmap-priority">${escapeHtml(todo.priority)}</span>
        ${renderStatusBadge(todo.status)}
      </div>
      <strong>${escapeHtml(todo.title)}</strong>
      <p>${escapeHtml(todo.description)}</p>
    </article>
  `).join("");
}

function renderRoadmapSection(title, items) {
  const normalized = Array.isArray(items) ? items : [];
  return `
    <section class="roadmap-section">
      <strong>${escapeHtml(title)}</strong>
      <ul>
        ${normalized.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </section>
  `;
}

function renderStatusBadge(status) {
  const label = architectureRoadmapData.statusLabels[status] || status || "unknown";
  return `<span class="status-pill status-${escapeHtml(status)}">${escapeHtml(label)}</span>`;
}

function renderProgress(progress) {
  const value = Math.max(0, Math.min(100, Number(progress) || 0));
  return `
    <div class="roadmap-progress" aria-label="progress ${value}%">
      <span style="width: ${value}%"></span>
      <b>${value}%</b>
    </div>
  `;
}

function setStatus(text, kind = "") {
  elements.statusText.textContent = text;
  elements.statusText.className = kind ? `status-${kind}` : "";
}

function clearCaseProgressTimer() {
  if (state.caseProgressTimer) {
    clearInterval(state.caseProgressTimer);
    state.caseProgressTimer = null;
  }
  state.caseProgressStartedAt = 0;
  state.caseProgressLabel = "";
}

function caseProgressStage(elapsedSeconds, stages) {
  const stageList = stages && stages.length ? stages : [
    {after: 0, text: "正在选择 knowledge 和检查影像输入"},
    {after: 8, text: "正在调用视觉模型定位候选征象"},
    {after: 25, text: "正在生成或校验分割候选区域"},
    {after: 45, text: "正在整合 evidence bundle 和诊断报告"},
  ];
  return stageList.reduce((current, stage) => (
    elapsedSeconds >= stage.after ? stage.text : current
  ), stageList[0].text);
}

function caseProgressStagesForPayload(payload) {
  const selectedSecondaryKnowledges = Array.isArray(payload?.manual_secondary_knowledge_candidates)
    ? payload.manual_secondary_knowledge_candidates
    : [];
  if (payload?.knowledge_selection_mode === "manual_secondary" && selectedSecondaryKnowledges.length) {
    return [
      {after: 0, text: "正在选择主 Knowledge 并检查影像输入"},
      {after: 6, text: "正在调用 KnowledgeBuilder 建立备用 Knowledge 草案"},
      {after: 16, text: "正在加载或生成备用 Knowledge evidence protocol"},
      {after: 28, text: "正在进行备用 Knowledge hypothesis validation"},
      {after: 45, text: "正在整合主分析、备用复查和诊断报告"},
    ];
  }
  return [
    {after: 0, text: "正在选择 knowledge 和检查影像输入"},
    {after: 8, text: "正在调用 VLM/API 定位候选影像征象"},
    {after: 25, text: "正在运行或跳过分割候选区域"},
    {after: 45, text: "正在生成 evidence bundle 和诊断报告"},
  ];
}

function startCaseProgress(label, stages) {
  clearCaseProgressTimer();
  state.caseProgressStartedAt = Date.now();
  state.caseProgressLabel = label || "病例分析中";
  const update = () => {
    const elapsed = Math.max(1, Math.floor((Date.now() - state.caseProgressStartedAt) / 1000));
    const stage = caseProgressStage(elapsed, stages);
    setStatus(`${state.caseProgressLabel}... ${elapsed}s · ${stage}`);
    if (elements.visualMeta.innerHTML.includes("Thinking...")) {
      elements.visualMeta.innerHTML = `
        <p>Thinking... ${escapeHtml(stage)}</p>
        <p class="muted">已等待 ${elapsed}s。实时上传会调用 VLM/API；预生成样例会更快。</p>
      `;
    }
    if (elements.reportView.innerHTML.includes("Thinking...")) {
      elements.reportView.innerHTML = `
        <p>Thinking... 等待诊断报告</p>
        <p class="muted">已等待 ${elapsed}s，完成视觉证据后会自动生成报告。</p>
      `;
    }
  };
  update();
  state.caseProgressTimer = setInterval(update, 1000);
}

function splitList(value) {
  return value
    .split(/[，,;；\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildCasePayload() {
  const imagePaths = state.uploadedImagePaths.length
    ? state.uploadedImagePaths
    : splitList(elements.imagePath.value);
  const caseNarrative = elements.patientMessage.value.trim();
  const payload = {
    patient_message: caseNarrative,
    image_path: imagePaths[0] || elements.imagePath.value.trim() || null,
    patient_info: {
      symptoms: splitList(caseNarrative),
      clinical_notes: caseNarrative,
      image_modality: elements.imageModality.value || "xray",
    },
  };
  if (imagePaths.length > 1) {
    payload.image_paths = imagePaths;
    payload.patient_info.image_series = imagePaths.map((path, index) => ({
      image_id: `image_${String(index + 1).padStart(3, "0")}`,
      image_path: path,
      view_hint: inferViewHint(path, state.uploadedImageNames[index] || ""),
    }));
  }
  if (state.useSampleMask) {
    payload.mask_path = state.sampleMaskPath;
  }
  payload.disease_key = state.sampleDiseaseKey || "femoral_head_necrosis";
  const knowledgeSelectionMode = elements.knowledgeSelectionMode.value || "primary_only";
  payload.knowledge_selection_mode = knowledgeSelectionMode;
  payload.evidence_protocol_mode = elements.evidenceProtocolMode.value || "finding_list_baseline";
  if (knowledgeSelectionMode !== "manual_secondary") {
    clearManualSecondaryKnowledges();
  }
  const manualSecondaryKnowledges = splitList(elements.manualSecondaryKnowledges.value);
  if (knowledgeSelectionMode === "manual_secondary" && manualSecondaryKnowledges.length) {
    payload.manual_secondary_knowledge_candidates = manualSecondaryKnowledges;
  }
  const selectedVisionMode = manualSecondaryVisionMode(knowledgeSelectionMode);
  if (selectedVisionMode) {
    payload.vision_mode = selectedVisionMode;
  }
  return payload;
}

function manualSecondaryVisionMode(knowledgeSelectionMode) {
  if (knowledgeSelectionMode !== "manual_secondary") {
    return state.sampleVisionMode;
  }
  return state.sampleVisionMode;
}

function inferViewHint(path, filename) {
  const text = `${path} ${filename}`.toLowerCase();
  if (text.includes("frog") || text.includes("lauenstein") || text.includes("蛙")) {
    return "frog_lateral";
  }
  if (text.includes("lateral") || text.includes("侧位")) {
    return "lateral";
  }
  if (text.includes("ap") || text.includes("pelvis") || text.includes("正位") || text.includes("卧")) {
    return "ap_pelvis";
  }
  return "unknown";
}

function buildQaPayload() {
  return {
    case_id: state.caseId,
    patient_message: elements.qaInput.value.trim(),
  };
}

async function postMedScope(payload) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000);
  try {
    const response = await fetch("/v1/medscope", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const body = await parseJsonResponse(response);
    if (!response.ok) {
      throw buildApiError(body, response.status);
    }
    return body;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("实时分析超过 180 秒未返回。建议先用预生成样例演示，或检查 VLM/分割模型后端。");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function postMedScopeQa(payload, signal) {
  const response = await fetch("/v1/medscope", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
    signal,
  });
  const body = await parseJsonResponse(response);
  if (!response.ok) {
    throw buildApiError(body, response.status);
  }
  return body;
}

async function parseJsonResponse(response) {
  const text = await response.text();
  if (!text.trim()) {
    throw new Error(`服务响应为空：HTTP ${response.status}。可能是后端进程重启、连接中断或实时模型调用异常。`);
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`服务返回了非 JSON 响应：HTTP ${response.status}。请检查服务器日志。`);
  }
}

async function fetchKnowledgeList() {
  const response = await fetch("/v1/knowledge");
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  return body;
}

async function fetchKnowledgeDetail(knowledgeKey) {
  const response = await fetch(`/v1/knowledge/${encodeURIComponent(knowledgeKey)}`);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  return body;
}

async function fetchKnowledgeProtocolComparison() {
  const response = await fetch("/v1/knowledge/femoral_head_necrosis/comparison");
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  return body;
}

async function fetchResearchEvidenceReview() {
  const response = await fetch("/v1/research-evidence-review");
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  return body;
}

async function saveKnowledgeReviewDraft() {
  if (!state.selectedKnowledgeKey) {
    setStatus("请先选择一个 Knowledge", "warn");
    return;
  }
  const payload = buildKnowledgeDraftPayload();
  const response = await fetch(`/v1/knowledge/${encodeURIComponent(state.selectedKnowledgeKey)}/review-draft`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  elements.knowledgeReviewStatus.textContent = `草稿已保存：${body.draft_path}`;
  setStatus("Knowledge 审核：保存草稿完成", "ok");
  await loadKnowledgeDetail(state.selectedKnowledgeKey);
}

async function promoteKnowledgeToFormalLibrary() {
  if (!state.selectedKnowledgeKey) {
    setStatus("请先选择一个候选 Knowledge", "warn");
    return;
  }
  if (!state.selectedKnowledgeKey.startsWith("proposal:")) {
    setStatus("当前已经是正式 Knowledge，不需要重复保存", "warn");
    return;
  }
  const response = await fetch(`/v1/knowledge/${encodeURIComponent(state.selectedKnowledgeKey)}/promote`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      reviewer_name: "doctor_reviewer",
      review_note: document.getElementById("knowledgeReviewNotes")?.value.trim() || "",
    }),
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  elements.knowledgeReviewStatus.textContent = `已保存为正式 Knowledge：${body.knowledge_path}；状态 ${body.review_status}`;
  setStatus("Knowledge 已进入正式库，可后续复用", "ok");
  await loadKnowledgeList();
  await loadKnowledgeDetail(body.knowledge_key);
}

async function fetchMemoryReplay(caseId) {
  const response = await fetch(`/v1/memory/cases/${encodeURIComponent(caseId)}/replay`);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  return body;
}

async function fetchStandardDemoCase(caseSlug) {
  const response = await fetch(`/v1/demo/standard/cases/${encodeURIComponent(caseSlug)}/response`);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  return body;
}

async function fetchDemoJson(path) {
  const response = await fetch(path);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  return body;
}

async function fetchEvidenceGatewaySnapshot() {
  return fetchDemoJson("/v1/demo/evidence-gateway-snapshot");
}

async function fetchPublicSafeDemo() {
  const payload = await fetchDemoJson("/v1/demo/public-safe");
  payload.demo_source = payload.demo_source || "public_safe_demo_suite";
  return payload;
}

async function fetchRealVlmMedSAM2Demo() {
  try {
    return await fetchRealVlmMedSAM2Response();
  } catch (error) {
    setStatus("完整真实样例 response 不可用，改为读取分项 artifact...", "warn");
  }
  const [summary, report, evidenceBundle, segmentation, vlmPrompt] = await Promise.all([
    fetchDemoJson("/v1/demo/real-vlm-medsam2"),
    fetchDemoJson("/v1/demo/real-vlm-medsam2/report"),
    fetchDemoJson("/v1/demo/real-vlm-medsam2/evidence-bundle"),
    fetchDemoJson("/v1/demo/real-vlm-medsam2/segmentation"),
    fetchDemoJson("/v1/demo/real-vlm-medsam2/vlm-prompt"),
  ]);
  return buildRealVlmMedSAM2Payload({
    summary,
    report,
    evidenceBundle,
    segmentation,
    vlmPrompt,
  });
}

async function fetchRealVlmMedSAM2Response() {
  const payload = await fetchDemoJson("/v1/demo/real-vlm-medsam2/response");
  payload.demo_source = payload.demo_source || "real_vlm_medsam2_artifact";
  return payload;
}

function buildRealVlmMedSAM2Payload(parts) {
  const summary = parts.summary || {};
  const report = parts.report || {};
  const evidenceBundle = parts.evidenceBundle || {};
  const segmentation = parts.segmentation || {};
  const vlmPrompt = parts.vlmPrompt || {};
  const visualResult = evidenceBundle.visual_result || segmentation.result || {};
  const visualEvidence = visualResult.visual_evidence || {};
  const measurements = visualEvidence.measurements || {};
  const completeness = visualEvidence.completeness || {};
  const segmentationResults = Array.isArray(visualEvidence.segmentation_results)
    ? visualEvidence.segmentation_results
    : [];
  const visualToolPlan = Array.isArray(visualEvidence.visual_tool_plan)
    ? visualEvidence.visual_tool_plan
    : [];
  const rawImageOutputs = evidenceBundle.image_outputs || segmentation.image_outputs || visualResult.image_outputs || {};
  const imageOutputs = {
    ...rawImageOutputs,
    original_preview_path: rawImageOutputs.original_preview_path || vlmPrompt.slice_png_path,
    localization_overlay_path: rawImageOutputs.localization_overlay_path || vlmPrompt.bbox_overlay_path,
  };
  const evaluation = evidenceBundle.evaluation || segmentation.evaluation || {};
  const usedKnowledge = report.used_knowledge || {};
  const caseId = summary.case_id || evidenceBundle.case_id || segmentation.case_id || "brats2021_00030";
  const diseaseKey = evidenceBundle.disease_key || summary.disease_key || "diffuse_glioma_brats";
  const promptBoxes = Array.isArray(vlmPrompt.boxes)
    ? vlmPrompt.boxes.map((box) => Array.isArray(box) ? box.join(",") : String(box)).join(" | ")
    : "";
  const imageEvidence = {
    image_path: imageOutputs.original_image_path || visualResult.image_path || vlmPrompt.image_path,
    modality: visualResult.modality || "MRI",
    body_part: visualResult.body_part || "brain",
    image_outputs: imageOutputs,
    segmentation_quality: visualEvidence.segmentation_quality || "medsam2",
    measurements: {
      ...measurements,
      whole_tumor_dice: evaluation.whole_tumor_dice,
      tumor_core_dice: evaluation.tumor_core_dice,
      enhancing_tumor_dice: evaluation.enhancing_tumor_dice,
      prompt_source: summary.prompt_source || segmentation.prompt_source || vlmPrompt.prompt_source,
      vlm_bbox: promptBoxes,
    },
    completeness,
    segmentation_results: segmentationResults,
    visual_tool_plan: visualToolPlan,
  };
  return {
    case_id: caseId,
    intent: "diagnosis",
    demo_source: "real_vlm_medsam2_artifact",
    reply_to_patient: summary.diagnostic_tendency || report.diagnostic_tendency || "",
    report,
    image_outputs: imageOutputs,
    visual_input_contract: {
      image_path: imageEvidence.image_path,
      modality: imageEvidence.modality,
      body_part: imageEvidence.body_part,
      segmentation_quality: imageEvidence.segmentation_quality,
      image_outputs: imageOutputs,
      measurements,
      completeness,
      segmentation_results: segmentationResults,
      visual_tool_plan: visualToolPlan,
    },
    alignment_plan: {
      analysis_status: "partial_evidence",
      clinical_focus: "adult diffuse glioma imaging evidence",
      selected_knowledge: evidenceBundle.disease_key || summary.disease_key || "diffuse_glioma_brats",
      image_context: {
        modality: imageEvidence.modality,
        body_part: imageEvidence.body_part,
        available_sequences: ["FLAIR"],
      },
      suspected_conditions: [
        {
          disease: "adult diffuse glioma",
          reason: "VLM generated candidate bbox and MedSAM2 produced a brain tumor mask; diagnosis still requires complete MRI and pathology.",
        },
      ],
      visual_tasks: [
        {
          task: "vlm_candidate_localization",
          status: vlmPrompt.status === "ok" ? "runnable" : "unassessed",
          required_input: "FLAIR slice PNG",
          reason: `prompt_source=${vlmPrompt.prompt_source || summary.prompt_source || "-"}`,
        },
        {
          task: "medsam2_candidate_segmentation",
          status: segmentation.status === "ok" ? "runnable" : "unassessed",
          required_input: "VLM bbox prompt",
          reason: `whole_tumor_dice=${formatValue(evaluation.whole_tumor_dice)}`,
        },
      ],
      required_next_images: [
        {region: "brain", modality: "T1", reason: "Required for tumor core assessment."},
        {region: "brain", modality: "T1ce", reason: "Required for enhancing tumor assessment."},
        {region: "brain", modality: "T2", reason: "Required for broader edema/core assessment."},
      ],
      insufficiency_reasons: [
        "This is an auditable demo artifact, not a live clinical-grade segmentation run.",
        "Missing T1/T1ce/T2 fields must not be interpreted as negative or zero.",
      ],
    },
    evidence_bundle: {
      patient_context: {
        case_id: caseId,
        disease_key: evidenceBundle.disease_key || summary.disease_key,
        prompt_source: summary.prompt_source || segmentation.prompt_source || vlmPrompt.prompt_source,
      },
      image_evidence: imageEvidence,
      knowledge_evidence: {
        selected_knowledge: evidenceBundle.disease_key || summary.disease_key || "diffuse_glioma_brats",
        selected_vision_mode: "medsam2",
        knowledge_type: usedKnowledge.knowledge_type || "guideline_based",
        guideline_evidence: {
          citations: usedKnowledge.source_documents || usedKnowledge.guideline_extraction?.citations || [],
        },
        quality_control: {
          formal_knowledge_status: usedKnowledge.knowledge_type ? "loaded" : "not_reported",
          visual_protocol_status: "used_by_demo",
        },
      },
      missing_or_unassessed: {
        image_memory: completeness,
      },
      quality_warnings: [
        "reference_mask was used only for post-hoc Dice/QC, not for prompt generation.",
        "enhancing_tumor Dice is 0.0 in this demo and should not be treated as a reliable absence claim.",
      ],
    },
    memory_audit: {
      memory_completeness: {
        patient_memory: {status: "demo_artifact", reason: "pre-generated demo sample"},
        image_memory: {status: "supported", reason: "real VLM prompt and MedSAM2 artifact available"},
        knowledge_memory: {status: "supported", reason: evidenceBundle.disease_key || summary.disease_key || "diffuse_glioma_brats"},
        reasoning_memory: {status: "supported", reason: "diagnosis report artifact available"},
      },
      memory_type_details: {
        patient_memory: {
          patient_id: caseId,
          intent: "diagnosis",
          symptom_count: Array.isArray(summary.symptoms) ? summary.symptoms.length : 0,
          qa_history_count: 0,
        },
        image_memory: {
          original_preview_path: imageOutputs.original_preview_path,
          localization_overlay_path: imageOutputs.localization_overlay_path,
          overlay_path: imageOutputs.overlay_path,
          mask_path: imageOutputs.mask_path,
          mask_preview_path: imageOutputs.mask_preview_path,
          segmentation_quality: imageEvidence.segmentation_quality,
        },
        knowledge_memory: {
          selected_knowledge: diseaseKey,
          used_knowledge: diseaseKey,
          knowledge_type: usedKnowledge.knowledge_type || "guideline_based",
          analysis_status: "partial_evidence",
          required_next_images: [
            {region: "brain", modality: "T1/T1ce/T2", reason: "Complete MRI sequences are required."},
          ],
          visual_protocol_status: "used_by_demo",
        },
        reasoning_memory: {
          llm_attempted: summary.llm_attempted,
          llm_fallback_reason: summary.llm_fallback_reason,
          model: summary.model,
        },
      },
      alignment_summary: {
        analysis_status: "partial_evidence",
        clinical_focus: "adult diffuse glioma imaging evidence",
        visual_task_status_counts: {runnable: 2},
        required_next_images: [
          {region: "brain", modality: "T1/T1ce/T2", reason: "Complete MRI sequences are required."},
        ],
      },
      knowledge_quality: {
        formal_knowledge_status: usedKnowledge.knowledge_type ? "loaded" : "not_reported",
        visual_protocol_status: "used_by_demo",
        citation_status: usedKnowledge.source_documents?.length ? "present" : "not_reported",
      },
      qa_safety: {
        evidence_bundle_required: true,
        evidence_bundle_used: false,
        evidence_bundle_used_count: 0,
        qa_history_count: 0,
        llm_used_count: summary.llm_attempted ? 1 : 0,
        fallback_count: summary.llm_fallback_reason ? 1 : 0,
        missing_or_unassessed_count: Object.keys(completeness).filter((key) => completeness[key]?.status !== "supported").length,
      },
      agents_traced: [
        "GaoDoctorAgent",
        "KnowledgeBuilderAgent",
        "VisionAgent",
        "DiagnosisDoctorAgent",
        "MemoryManager",
      ],
      trace_consistency: {
        agent_io_matches_trace: true,
        required_agents_present: true,
        missing_required_agents: [],
        qa_extension_present: false,
        agent_count: 5,
        agent_io_count: 5,
      },
      agent_io_summary: {
        GaoDoctorAgent: {
          input: Array.isArray(summary.symptoms) ? summary.symptoms : [],
          output: "diagnosis",
          routing_decision: {
            selected_knowledge: diseaseKey,
            selected_vision_mode: "medsam2",
            source: "auto",
            agent_scope: "orchestrator_api",
            knowledge_builder_action: "load_existing_knowledge",
          },
        },
        KnowledgeBuilderAgent: {
          input: {selected_knowledge: diseaseKey},
          output: diseaseKey,
        },
        VisionAgent: {
          input: imageEvidence.image_path,
          output: imageOutputs,
          selected_vision_mode: "medsam2",
          tool: "MedSAM2",
          prompt_tool: "VLM Prompt",
        },
        DiagnosisDoctorAgent: {
          input: {measurements, completeness},
          output: report.diagnostic_tendency || report["诊断倾向"],
        },
        MemoryManager: {
          input: {
            case_id: caseId,
            memory_types: ["patient_memory", "image_memory", "knowledge_memory", "reasoning_memory"],
          },
          output: {
            audit_status: "available",
            evidence_bundle_status: "available",
          },
        },
      },
      missing_or_unassessed: {image_memory: completeness},
    },
    memory_replay: {
      case_id: caseId,
      replay_consistency: {
        required_events_present: true,
        missing_required_events: [],
        memory_scope_complete: true,
        steps_missing_memory_scope: [],
        qa_extension_present: false,
        step_count: 7,
      },
      steps: [
        {
          agent: "GaoDoctorAgent",
          event: "patient_intake",
          memory_scope: "patient_memory",
          intent: "diagnosis",
          patient_id: caseId,
          symptoms: Array.isArray(summary.symptoms) ? summary.symptoms : [],
        },
        {
          agent: "GaoDoctorAgent",
          event: "knowledge_routing",
          memory_scope: "knowledge_memory",
          decision_owner: "orchestrator_api",
          routing_decision: {
            selected_knowledge: diseaseKey,
            selected_vision_mode: "medsam2",
            source: "auto",
            agent_scope: "orchestrator_api",
            knowledge_builder_action: "load_existing_knowledge",
          },
          selected_knowledge: diseaseKey,
          selected_vision_mode: "medsam2",
          knowledge_type: usedKnowledge.knowledge_type,
          knowledge_builder_action: "load_existing_knowledge",
        },
        {
          agent: "KnowledgeBuilderAgent",
          event: "knowledge_loading",
          memory_scope: "knowledge_memory",
          action: "load_existing_knowledge",
          selected_knowledge: diseaseKey,
          used_knowledge: diseaseKey,
          knowledge_type: usedKnowledge.knowledge_type,
          evidence_level: usedKnowledge.evidence_level,
          formal_knowledge_status: usedKnowledge.knowledge_type ? "loaded" : "not_reported",
          visual_protocol_status: "used_by_demo",
        },
        {agent: "VisionAgent", event: "vlm_prompt_generation", memory_scope: "image_memory", tool: "VLM Prompt", segmentation_quality: "vision_model_bbox", measurements: {bbox: promptBoxes}},
        {
          agent: "VisionAgent",
          event: "visual_evidence",
          memory_scope: "image_memory",
          tool: "MedSAM2",
          selected_vision_mode: "medsam2",
          segmentation_quality: imageEvidence.segmentation_quality,
          measurements: imageEvidence.measurements,
        },
        {agent: "DiagnosisDoctorAgent", event: "diagnosis_report", memory_scope: "reasoning_memory", diagnostic_tendency: report.diagnostic_tendency || report["诊断倾向"]},
        {
          agent: "MemoryManager",
          event: "memory_audit",
          memory_scope: "patient_memory,image_memory,knowledge_memory,reasoning_memory",
          evidence_bundle_status: "available",
          audit_status: "available",
          quality_warnings: [
            "reference_mask was used only for post-hoc Dice/QC, not for prompt generation.",
            "missing MRI sequences must not be interpreted as negative findings.",
          ],
        },
      ],
    },
  };
}

async function postDemoQa(caseSlug, payload) {
  const response = await fetch(`/v1/demo/standard/cases/${encodeURIComponent(caseSlug)}/qa`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
    signal: state.qaAbortController?.signal,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  return body;
}

async function postRealVlmMedSAM2Qa(payload) {
  const response = await fetch("/v1/demo/real-vlm-medsam2/qa", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
    signal: state.qaAbortController?.signal,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  body.demo_source = "real_vlm_medsam2_artifact";
  return body;
}

async function postPublicSafeDemoQa(payload) {
  const response = await fetch("/v1/demo/public-safe/qa", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
    signal: state.qaAbortController?.signal,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  body.demo_source = "public_safe_demo_suite";
  return body;
}

async function fetchStandardDemoCaseOrRun(caseSlug, livePayload) {
  try {
    const payload = await fetchStandardDemoCase(caseSlug);
    payload.demo_case_slug = caseSlug;
    return payload;
  } catch (error) {
    setStatus("预生成样例不可用，改为实时分析...", "warn");
    state.demoCaseSlug = "";
    state.publicSafeDemoMode = false;
    return postMedScope(livePayload);
  }
}

function formatApiError(body, status) {
  const parts = [];
  if (body.error_type) {
    parts.push(body.error_type);
  }
  parts.push(body.error || `HTTP ${status}`);
  if (Array.isArray(body.action_items) && body.action_items.length) {
    parts.push(body.action_items.join(" "));
  }
  return parts.join("：");
}

function buildApiError(body, status) {
  const error = new Error(formatApiError(body, status));
  error.apiPayload = body || {};
  error.apiStatus = status;
  return error;
}

function shortApiErrorMessage(error, fallbackMessage = "病例分析失败") {
  const body = error?.apiPayload || {};
  if (body.error_type === "medsam2_not_ready") {
    return "分割后端未配置，详情见报告区";
  }
  if (body.error_type === "vlm_api_unavailable") {
    return "视觉模型调用中断，详情见报告区";
  }
  if (isOnfhVisualCandidateFailure(error)) {
    return "当前图片不适用 ONFH 专病筛查，详情见报告区";
  }
  if (body.error_type) {
    return `${fallbackMessage}：${body.error_type}`;
  }
  return error?.message || fallbackMessage;
}

async function uploadFile(file) {
  if (!file) {
    return null;
  }
  elements.uploadStatus.textContent = `上传中：${file.name}`;
  const response = await fetch(`/v1/upload?filename=${encodeURIComponent(file.name)}`, {
    method: "POST",
    headers: {"Content-Type": "application/octet-stream"},
    body: file,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.error || `HTTP ${response.status}`);
  }
  return body;
}

async function uploadFiles(fileList) {
  const files = Array.from(fileList || []).filter(Boolean);
  if (!files.length) {
    return;
  }
  elements.uploadStatus.textContent = `上传中：${files.length} 个文件`;
  const uploaded = [];
  for (const file of files) {
    elements.uploadStatus.textContent = `上传中：${file.name}`;
    const body = await uploadFile(file);
    if (body) {
      uploaded.push(body);
    }
  }
  state.uploadedImagePaths = uploaded.map((item) => item.image_path);
  state.uploadedImageNames = uploaded.map((item) => item.filename);
  elements.imagePath.value = state.uploadedImagePaths.join("\n");
  state.useSampleMask = false;
  state.sampleDiseaseKey = "";
  state.sampleVisionMode = "";
  setKnowledgeSelectionMode("primary_only");
  setEvidenceProtocolMode("finding_list_baseline");
  setEvidenceProtocolMode("finding_list_baseline");
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  state.publicSafeDemoMode = false;
  resetViews();
  elements.uploadStatus.textContent = formatUploadedImageSeriesStatus(uploaded);
}

function formatUploadedImageSeriesStatus(uploaded) {
  const items = Array.isArray(uploaded) ? uploaded : [];
  if (!items.length) {
    return "未上传影像";
  }
  const rows = items.map((item, index) => {
    const imageId = index === 0 ? "image_001" : `image_${String(index + 1).padStart(3, "0")}`;
    const filename = item.filename || item.image_path || `影像 ${index + 1}`;
    const viewHint = inferViewHint(item.image_path || "", filename);
    return `${imageId} · ${imageViewLabel(viewHint)} · ${filename}`;
  });
  if (rows.length === 1) {
    return `已上传：${rows[0]}`;
  }
  return `已上传 ${rows.length} 张同一病例影像：${rows.join("；")}`;
}

async function checkHealth() {
  setStatus("检查中...");
  try {
    const response = await fetch("/v1/readiness");
    const body = await response.json();
    const apiReady = body.api_route?.real_call_ready === true;
    const medsamReady = body.medsam2?.real_call_ready === true;
    const route = body.api_route?.active_route || "-";
    const textModel = body.api_route?.model || "-";
    const visionModel = body.api_route?.vision_model || "-";
    const message = body.status === "ok"
      ? `API 已连接 · route=${route} · text=${textModel} · vision=${visionModel} · 模型${apiReady ? "已配置" : "未配置"} · MedSAM2${medsamReady ? "已配置" : "未配置"}`
      : "API 状态异常";
    setStatus(message, body.status === "ok" ? (apiReady ? "ok" : "warn") : "warn");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function renderList(items) {
  if (!Array.isArray(items)) {
    return `<p>${escapeHtml(String(items || "-"))}</p>`;
  }
  if (!items.length) {
    return "<p>-</p>";
  }
  return `<ul>${items.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>`;
}

function renderMetricGrid(items) {
  const rows = Object.entries(items || {});
  if (!rows.length) {
    return '<div class="trace-empty">-</div>';
  }
  return `
    <dl class="metric-grid">
      ${rows.map(([key, value]) => `
        <div>
          <dt>${escapeHtml(String(key))}</dt>
          <dd>${escapeHtml(formatValue(value))}</dd>
        </div>
      `).join("")}
    </dl>
  `;
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function renderStatusPills(statusMap) {
  const entries = Object.entries(statusMap || {});
  if (!entries.length) {
    return '<div class="trace-empty">-</div>';
  }
  return `
    <div class="pill-list">
      ${entries.map(([key, value]) => {
        const status = typeof value === "object" && value ? value.status || value.reason || value : value;
        return `<span class="status-pill">${escapeHtml(String(key))}: ${escapeHtml(formatValue(status))}</span>`;
      }).join("")}
    </div>
  `;
}

function getVisualEvidenceBundle(payload) {
  return payload.visual_evidence_bundle
    || payload.evidence_bundle?.image_evidence?.visual_evidence_bundle
    || {};
}

function getSegmentationResults(payload) {
  const fromContract = payload.visual_input_contract?.segmentation_results;
  const fromBundle = payload.evidence_bundle?.image_evidence?.segmentation_results;
  const fromReport = payload.report?.visual_input_contract?.segmentation_results;
  if (Array.isArray(fromContract)) {
    return fromContract;
  }
  if (Array.isArray(fromBundle)) {
    return fromBundle;
  }
  if (Array.isArray(fromReport)) {
    return fromReport;
  }
  return [];
}

function getVisualToolPlan(payload) {
  const fromContract = payload.visual_input_contract?.visual_tool_plan;
  const fromBundle = payload.evidence_bundle?.image_evidence?.visual_tool_plan;
  const fromReport = payload.report?.visual_input_contract?.visual_tool_plan;
  if (Array.isArray(fromContract)) {
    return fromContract;
  }
  if (Array.isArray(fromBundle)) {
    return fromBundle;
  }
  if (Array.isArray(fromReport)) {
    return fromReport;
  }
  return [];
}

function renderKnowledgeList(payload) {
  const knowledge = Array.isArray(payload.knowledge) ? payload.knowledge : [];
  const proposals = differentialKnowledgeCandidateProposals(knowledge);
  const reviewItems = [...knowledge, ...proposals];
  if (!reviewItems.length) {
    elements.knowledgeListView.innerHTML = '<div class="trace-empty">暂无可审核 Knowledge</div>';
    return;
  }
  elements.knowledgeListView.innerHTML = `
    <div class="doctor-knowledge-list">
      ${reviewItems.map((knowledge) => {
        const summary = knowledge.doctor_summary || {};
        const selectedClass = knowledge.knowledge_key === state.selectedKnowledgeKey ? " selected" : "";
        const isProposal = knowledge.proposal_status === "proposal_only";
        const proposalLabel = knowledge.candidate_status === "selected_for_knowledgebuilder"
          ? "未审核"
          : isProposal ? "本次病例候选" : "";
        return `
          <button class="doctor-knowledge-item${selectedClass}" type="button" data-knowledge-key="${escapeHtml(knowledge.knowledge_key)}" ${isProposal ? `data-proposal-candidate-key="${escapeHtml(knowledge.candidate_key)}"` : ""}>
            <strong>${escapeHtml(knowledge.disease_name || knowledge.knowledge_key)}</strong>
            <span>${escapeHtml(knowledgeEvidenceLevelLabel(knowledge.evidence_level))} · ${escapeHtml(knowledge.knowledge_type || "knowledge")}</span>
            <small>症状 ${formatValue(summary.symptom_count)} / 影像 ${formatValue(summary.image_requirement_count)} / 征象 ${formatValue(summary.visual_finding_count)}</small>
            <em>${proposalLabel || (knowledge.review_status === "draft_saved" ? "已有医生草稿" : "未审核")}</em>
          </button>
        `;
      }).join("")}
    </div>
  `;
  elements.knowledgeListView.querySelectorAll("[data-knowledge-key]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.dataset.proposalCandidateKey) {
        const persistedProposal = payload.knowledge.some((knowledge) => knowledge.knowledge_key === button.dataset.knowledgeKey);
        if (persistedProposal) {
          await loadKnowledgeDetail(button.dataset.knowledgeKey);
          return;
        }
        renderKnowledgeProposalCandidateDetail(button.dataset.proposalCandidateKey, payload);
        return;
      }
      await loadKnowledgeDetail(button.dataset.knowledgeKey);
    });
  });
}

function knowledgeEvidenceLevelLabel(evidenceLevel) {
  const labels = {
    unreviewed: "未审核",
    pending_medical_source_review: "医疗来源待补充",
  };
  return labels[evidenceLevel] || evidenceLevel || "未标注";
}

function differentialKnowledgeCandidateProposals(formalKnowledges = []) {
  const routing = state.lastPayload.routing_decision
    || state.lastPayload.evidence_bundle?.knowledge_evidence?.routing_decision
    || {};
  const formalKeys = new Set(
    formalKnowledges.flatMap((knowledge) => [knowledge.knowledge_key, knowledge.candidate_key]).filter(Boolean)
  );
  const selected = routing.selected_knowledge || routing.primary_hypothesis;
  const planCandidateItems = Array.isArray(routing.secondary_knowledge_run_plan?.candidates)
    ? routing.secondary_knowledge_run_plan.candidates
    : [];
  const analysisItems = Array.isArray(state.lastPayload.secondary_knowledge_analysis)
    ? state.lastPayload.secondary_knowledge_analysis
    : [];
  const candidateMetadata = new Map();
  [...planCandidateItems, ...analysisItems].forEach((item) => {
    if (item?.disease_key) {
      candidateMetadata.set(item.disease_key, item);
    }
  });
  const planCandidates = planCandidateItems.map((item) => item.disease_key);
  const analysisCandidates = analysisItems
    ? analysisItems.map((item) => item.disease_key)
    : [];
  const candidates = uniqueStrings([
    ...(Array.isArray(routing.differential_knowledge_candidates)
      ? routing.differential_knowledge_candidates
      : []),
    ...(Array.isArray(routing.manual_secondary_knowledge_candidates)
      ? routing.manual_secondary_knowledge_candidates
      : []),
    ...planCandidates,
    ...analysisCandidates,
  ]);
  return candidates
    .filter((candidate) => candidate && candidate !== selected && !formalKeys.has(candidate))
    .map((candidate) => ({
      knowledge_key: `proposal:${candidate}`,
      candidate_key: candidate,
      disease_name: humanDiseaseName(candidate),
      evidence_level: "proposal_only",
      knowledge_type: "differential_candidate",
      review_status: "proposal_only",
      proposal_status: "proposal_only",
      candidate_status: candidateMetadata.get(candidate)?.candidate_status || "case_candidate",
      selected_by_user: Boolean(candidateMetadata.get(candidate)?.selected_by_user),
      knowledge_builder_status: candidateMetadata.get(candidate)?.knowledge_builder_status || "",
      knowledge_builder_progress: candidateMetadata.get(candidate)?.knowledge_builder_progress || [],
      knowledge_builder_proposal_detail: candidateMetadata.get(candidate)?.knowledge_builder_proposal_detail || {},
      differential_review: candidateMetadata.get(candidate)?.differential_review || {},
      doctor_summary: {
        symptom_count: "待指南抽取",
        image_requirement_count: "待指南抽取",
        visual_finding_count: "待指南抽取",
      },
    }));
}

async function loadKnowledgeProtocolComparison() {
  if (!elements.knowledgeProtocolComparisonView) {
    return;
  }
  elements.knowledgeProtocolComparisonView.innerHTML = '<div class="trace-empty">Knowledge 版本对比加载中...</div>';
  try {
    const payload = await fetchKnowledgeProtocolComparison();
    renderKnowledgeProtocolComparison(payload);
  } catch (error) {
    elements.knowledgeProtocolComparisonView.innerHTML = `<div class="trace-empty">${escapeHtml(error.message)}</div>`;
  }
}

async function loadResearchEvidenceReview() {
  if (!elements.researchEvidenceReviewView) {
    return;
  }
  elements.researchEvidenceReviewView.innerHTML = '<div class="trace-empty">Research Evidence Review 加载中...</div>';
  try {
    const payload = await fetchResearchEvidenceReview();
    renderResearchEvidenceReview(payload);
  } catch (error) {
    elements.researchEvidenceReviewView.innerHTML = `<div class="trace-empty">${escapeHtml(error.message)}</div>`;
  }
}

function renderResearchEvidenceReview(payload) {
  const retrieval = payload.research_evidence_retrieval || {};
  const request = retrieval.request || {};
  const papers = Array.isArray(retrieval.normalized_research_evidence)
    ? retrieval.normalized_research_evidence
    : Array.isArray(payload.normalized_research_evidence) ? payload.normalized_research_evidence : [];
  const claims = payload.claim_builder?.candidate_claims || [];
  const reviewItems = payload.gateway_review_artifact?.review_items || [];
  const safety = payload.runtime_safety || {};
  const paths = payload.output_paths || {};
  elements.researchEvidenceReviewView.innerHTML = `
    <div class="research-review-workspace">
      <section class="research-review-summary">
        <h3>${escapeHtml(request.research_question || "Research Evidence Review")}</h3>
        <p>research evidence is not guideline evidence；当前证据只进入 proposal-only / dry-run，不直接作为诊断规则或正式 knowledge 更新。</p>
        <div class="research-safety-badges">
          ${[
            "proposal_only=true",
            "formal_knowledge_updated=false",
            "diagnosis_rules_modified=false",
            "registry_updated=false",
            "promotion_requires_human_approval=true",
          ].map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
        </div>
        ${renderMetricGrid({
          "Disease": payload.disease_key,
          "Target knowledge": payload.target_knowledge_id,
          "Papers": papers.length,
          "Claims": claims.length,
          "Gateway": payload.gateway_review_artifact?.review_status || "-",
          "Patch preview": payload.formal_knowledge_extension_patch_preview?.patch_status || "-",
        })}
      </section>
      <section class="research-review-grid">
        ${renderResearchPaperList(papers)}
        ${renderResearchClaimList(claims)}
        ${renderResearchGateList(reviewItems)}
        ${renderResearchDryRunSummary(payload)}
      </section>
      <section class="research-review-paths">
        <strong>Proposal artifact</strong>
        <span>${escapeHtml(paths.proposal_json_path || "生成后写入 output/fake/research_evidence_review")}</span>
      </section>
      <details class="research-debug-details">
        <summary>开发调试数据</summary>
        <pre>${escapeHtml(JSON.stringify({
          schema_version: payload.schema_version,
          runtime_safety: safety,
          output_paths: paths,
        }, null, 2))}</pre>
      </details>
    </div>
  `;
}

function renderResearchPaperList(papers) {
  return `
    <article class="research-review-card">
      <h3>retrieved papers / supplied metadata</h3>
      ${papers.length ? papers.map((paper) => `
        <div class="research-paper-item">
          <strong>${escapeHtml(paper.title || "unknown")}</strong>
          <span>${escapeHtml([paper.journal, paper.year || paper.publication_year, paper.pmid || paper.PMID].filter(Boolean).join(" · ") || "metadata")}</span>
          <p>${escapeHtml((paper.abstract || paper.source_trace?.abstract || "abstract unknown").slice(0, 220))}</p>
        </div>
      `).join("") : '<p>暂无论文 metadata。</p>'}
    </article>
  `;
}

function renderResearchClaimList(claims) {
  return `
    <article class="research-review-card">
      <h3>candidate claims</h3>
      ${claims.length ? claims.map((claim) => `
        <div class="research-claim-item">
          <strong>${escapeHtml(claim.claim_type || claim.legacy_candidate_type || "candidate")}</strong>
          <span>${escapeHtml(claim.proposed_knowledge_section || claim.target_protocol_section || "-")}</span>
          <p>${escapeHtml(claim.summary || "")}</p>
          <em>promotion_allowed=false · requires_human_review=true · ${escapeHtml(claim.diagnosis_usable_level || "not_diagnosis_usable")}</em>
        </div>
      `).join("") : '<p>暂无 candidate claim。</p>'}
    </article>
  `;
}

function renderResearchGateList(reviewItems) {
  return `
    <article class="research-review-card">
      <h3>Evidence Gateway gate status</h3>
      ${reviewItems.length ? reviewItems.map((item) => `
        <div class="research-gate-item">
          <strong>${escapeHtml(item.item_id || "review item")}</strong>
          <span>${escapeHtml(item.guideline_conflict_status || "-")}</span>
          ${renderResearchGateBadges(item.gate_status || {})}
        </div>
      `).join("") : '<p>暂无 gate status。</p>'}
    </article>
  `;
}

function renderResearchGateBadges(gates) {
  return `
    <div class="research-gate-badges">
      ${Object.entries(gates).map(([key, value]) => `
        <span>${escapeHtml(key)}: ${escapeHtml(value?.status || "unknown")}</span>
      `).join("")}
    </div>
  `;
}

function renderResearchDryRunSummary(payload) {
  const checklist = payload.human_review_checklist || {};
  const patch = payload.formal_knowledge_extension_patch_preview || {};
  return `
    <article class="research-review-card">
      <h3>dry-run / patch-preview summary</h3>
      ${renderMetricGrid({
        "Dry run": payload.promotion_dry_run?.promotion_status || "-",
        "Controlled draft": payload.controlled_knowledge_extension_draft?.draft_status || "-",
        "Patch preview": patch.patch_status || "-",
        "Human review": checklist.review_status || "-",
        "Pre-apply audit": patch.pre_apply_audit?.audit_status || "-",
      })}
      <p>Patch preview 只允许 research-mode / supplemental section；正式 knowledge、diagnosis rules 和 registry 都不会在这里被修改。</p>
    </article>
  `;
}

function renderKnowledgeProtocolComparison(payload) {
  const versions = Array.isArray(payload.versions) ? payload.versions : [];
  const evaluation = payload.evaluation_summary || {};
  const takeaway = payload.comparison_takeaway || {};
  elements.knowledgeProtocolComparisonView.innerHTML = `
    <div class="knowledge-comparison-workspace">
      <section class="knowledge-comparison-summary">
        <h3>${escapeHtml(payload.title || "Knowledge 版本对比")}</h3>
        <p>${escapeHtml(payload.safety_note || "该对比只用于 protocol coverage 审阅。")}</p>
        ${renderKnowledgeComparisonTakeaway(takeaway)}
        ${renderKnowledgeComparisonCoverage(evaluation)}
      </section>
      <div class="knowledge-version-grid">
        ${versions.map(renderKnowledgeVersionCard).join("") || '<div class="trace-empty">暂无版本信息</div>'}
      </div>
    </div>
  `;
}

function renderKnowledgeComparisonTakeaway(takeaway) {
  const advantages = Array.isArray(takeaway.advantages) ? takeaway.advantages : [];
  return `
    <article class="knowledge-takeaway-card">
      <strong>${escapeHtml(takeaway.title || "新版强在哪")}</strong>
      <p>${escapeHtml(takeaway.summary || "新版把 finding-list baseline 升级为 Evidence protocol：不仅列出征象，还说明如何获取证据、哪些需要量化、哪些不能直接诊断。")}</p>
      <ul>
        ${(advantages.length ? advantages : [
          "将软骨下骨骨折作为独立证据项，而不是混在塌陷里。",
          "明确哪些征象需要候选分割，哪些只能作为 VLM 观察。",
          "把纹理紊乱、塌陷程度、坏死面积比例等量化入口折叠管理。",
        ]).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </article>
  `;
}

function renderKnowledgeComparisonCoverage(evaluation) {
  if (!evaluation || evaluation.status === "missing") {
    return `
      <article class="knowledge-coverage-card">
        <strong>真实 X-ray protocol coverage</strong>
        <p>${escapeHtml(evaluation?.interpretation || "暂无真实 X-ray protocol coverage 结果。")}</p>
      </article>
    `;
  }
  const missingLabels = Array.isArray(evaluation.baseline_missing_labels)
    ? evaluation.baseline_missing_labels
    : [];
  return `
    <article class="knowledge-coverage-card">
      <div>
        <strong>真实 X-ray protocol coverage</strong>
        <span>${escapeHtml(evaluation.primary_modality || "Xray")}</span>
      </div>
      ${renderMetricGrid({
        "新版覆盖": `${evaluation.current_coverage || "-"} (${formatValue(evaluation.current_coverage_percent)}%)`,
        "旧版覆盖": `${evaluation.baseline_coverage || "-"} (${formatValue(evaluation.baseline_coverage_percent)}%)`,
        "旧版缺口": missingLabels.length ? missingLabels.join("、") : "无",
      })}
      <p>${escapeHtml(evaluation.interpretation || "")}</p>
    </article>
  `;
}

function renderKnowledgeVersionCard(version) {
  const names = Array.isArray(version.finding_names) ? version.finding_names : [];
  const targets = Array.isArray(version.evidence_targets) ? version.evidence_targets : [];
  const quantitative = Array.isArray(version.quantitative_items) ? version.quantitative_items : [];
  const quantificationGroups = Array.isArray(version.quantification_groups) ? version.quantification_groups : [];
  const limits = Array.isArray(version.human_readable_limits) ? version.human_readable_limits : [];
  const versionLabel = version.label || knowledgeComparisonFallbackLabels[version.version_key] || "Knowledge 版本";
  return `
    <article class="knowledge-version-card">
      <div class="knowledge-version-heading">
        <strong>${escapeHtml(versionLabel)}</strong>
        <span>${escapeHtml(version.version_key || "")}</span>
      </div>
      <p>${escapeHtml(version.summary || "")}</p>
      ${renderMetricGrid({
        "影像证据项": version.finding_count,
        "Evidence protocol": version.has_evidence_protocol ? "有" : "无",
        "Quantitative protocol": version.has_quantitative_protocol ? "有" : "无",
      })}
      <div class="knowledge-pill-list">
        ${names.map((name) => `<span>${escapeHtml(name)}</span>`).join("")}
      </div>
      ${targets.length ? `
        <div class="knowledge-target-table">
          ${targets.map((target) => `
            <div>
              <strong>${escapeHtml(target.name || target.target || "")}</strong>
              <span>${escapeHtml(target.evidence_mode || "")}${target.needs_quantification ? " · 需要量化" : ""}</span>
              <em>${escapeHtml(target.diagnosis_role || "")}</em>
            </div>
          `).join("")}
        </div>
      ` : ""}
      ${quantitative.length ? `
        ${renderQuantificationNeedDetails(quantificationGroups, quantitative)}
      ` : ""}
      ${limits.length ? `
        <div class="knowledge-readable-block">
          <strong>边界</strong>
          <ul>${limits.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
        </div>
      ` : ""}
    </article>
  `;
}

function renderQuantificationNeedDetails(groups, quantitativeItems) {
  const hasGroups = Array.isArray(groups) && groups.some((group) => Array.isArray(group.items) && group.items.length);
  return `
    <details class="knowledge-quantification-details">
      <summary>哪些指标需要量化</summary>
      ${hasGroups ? groups.map(renderQuantificationGroup).join("") : `
        <div class="knowledge-readable-block">
          <strong>量化入口</strong>
          <p>${escapeHtml((quantitativeItems || []).join("、"))}</p>
        </div>
      `}
    </details>
  `;
}

function renderQuantificationGroup(group) {
  const items = Array.isArray(group.items) ? group.items : [];
  if (!items.length) {
    return "";
  }
  return `
    <section class="knowledge-quantification-group">
      <strong>${escapeHtml(group.label || "量化指标")}</strong>
      <p>${escapeHtml(group.summary || "")}</p>
      <div>
        ${items.map((item) => `
          <article>
            <span>${escapeHtml(item.name || "")}</span>
            <b>${escapeHtml(item.human_target || item.target || "")}</b>
            <em>${escapeHtml(item.reason || "")}</em>
            ${renderQuantificationItemMeta(item)}
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function renderQuantificationItemMeta(item) {
  const meta = [];
  if (item.unit) {
    meta.push(`单位：${item.unit}`);
  }
  if (item.measurement_method) {
    meta.push(`方法：${item.measurement_method}`);
  }
  if (item.staging_rule_summary) {
    meta.push(`分期规则：${item.staging_rule_summary}`);
  }
  if (item.safety_summary) {
    meta.push(`安全规则：${item.safety_summary}`);
  }
  if (!meta.length) {
    return "";
  }
  return `
    <small>${meta.map(escapeHtml).join(" · ")}</small>
  `;
}

async function loadKnowledgeList() {
  elements.knowledgeListView.innerHTML = '<div class="trace-empty">Knowledge 加载中...</div>';
  try {
    const payload = await fetchKnowledgeList();
    renderKnowledgeList(payload);
    if (!state.selectedKnowledgeKey && payload.knowledge && payload.knowledge.length) {
      await loadKnowledgeDetail(payload.knowledge[0].knowledge_key);
    }
  } catch (error) {
    elements.knowledgeListView.innerHTML = `<div class="trace-empty">${escapeHtml(error.message)}</div>`;
  }
}

async function loadKnowledgeDetail(knowledgeKey) {
  state.selectedKnowledgeKey = knowledgeKey;
  elements.knowledgeDetailView.innerHTML = '<div class="trace-empty">Knowledge 详情加载中...</div>';
  try {
    const detail = await fetchKnowledgeDetail(knowledgeKey);
    state.selectedKnowledgeDetail = detail;
    renderKnowledgeReviewWorkspace(detail);
    const listPayload = await fetchKnowledgeList();
    renderKnowledgeList(listPayload);
  } catch (error) {
    elements.knowledgeDetailView.innerHTML = `<div class="trace-empty">${escapeHtml(error.message)}</div>`;
  }
}

function renderKnowledgeProposalCandidateDetail(candidateKey, listPayload = {knowledge: []}) {
  state.selectedKnowledgeKey = `proposal:${candidateKey}`;
  const routing = state.lastPayload.routing_decision
    || state.lastPayload.evidence_bundle?.knowledge_evidence?.routing_decision
    || {};
  const planCandidates = Array.isArray(routing.secondary_knowledge_run_plan?.candidates)
    ? routing.secondary_knowledge_run_plan.candidates
    : [];
  const analysisItems = Array.isArray(state.lastPayload.secondary_knowledge_analysis)
    ? state.lastPayload.secondary_knowledge_analysis
    : [];
  const secondaryMetaFromPayload = [...planCandidates, ...analysisItems]
    .find((item) => item?.disease_key === candidateKey) || {};
  const proposalFromListPayload = Array.isArray(listPayload.knowledge)
    ? listPayload.knowledge.find((item) => item?.candidate_key === candidateKey) || {}
    : {};
  const secondaryMeta = Object.keys(secondaryMetaFromPayload).length
    ? secondaryMetaFromPayload
    : proposalFromListPayload;
  const hypotheses = Array.isArray(routing.clinical_hypotheses)
    ? routing.clinical_hypotheses
    : [];
  const hypothesis = hypotheses.find((item) => item.disease_key === candidateKey) || {};
  const diseaseName = humanDiseaseName(candidateKey);
  const selectedForKnowledgeBuilder = secondaryMeta.candidate_status === "selected_for_knowledgebuilder";
  const proposalReady = secondaryMeta.knowledge_builder_status === "proposal_prepared"
    || selectedForKnowledgeBuilder;
  elements.knowledgeReviewStatus.textContent = selectedForKnowledgeBuilder
    ? "未审核；当前仍是候选草案，医生确认后可保存为正式 Knowledge 复用。"
    : "Differential candidate 已进入 proposal-only Knowledge 审核队列；医生确认后可保存为正式 Knowledge。";
  elements.knowledgeDetailView.innerHTML = `
    <div class="doctor-knowledge-workspace">
      <section class="doctor-knowledge-section">
        <h3>${escapeHtml(diseaseName || candidateKey)} ${proposalReady ? "未审核备用 Knowledge" : "待建 Knowledge"}</h3>
        ${renderMetricGrid({
          candidate_key: candidateKey,
          proposal_status: selectedForKnowledgeBuilder ? "selected_for_knowledgebuilder" : "proposal_only",
          candidate_type: "differential_candidate",
          source: "current_case_routing",
          knowledge_builder_status: secondaryMeta.knowledge_builder_status || "pending",
          review_queue_status: secondaryMeta.review_queue_status || secondaryMeta.knowledge_builder_proposal_detail?.review_queue_status || "pending",
          formal_knowledge_updated: "false",
          diagnosis_allowed: "false",
        })}
        <p class="warning-text">${selectedForKnowledgeBuilder
          ? "这是医生在本次病例中选中的备用疾病；KnowledgeBuilder proposal 已生成并进入审核库。点击“保存为正式 Knowledge”后会写入 knowledge/，但仍标记为 needs_review，不会自动作为确诊规则运行。"
          : "这是本次病例 routing 生成的鉴别候选，用于提醒医生审核是否需要补建 guideline knowledge。医生确认后可保存进正式 Knowledge 库。"
        }</p>
        ${renderKnowledgeBuilderProposalDetail(secondaryMeta.knowledge_builder_proposal_detail)}
        ${renderSecondaryKnowledgeBuilderProgress(secondaryMeta)}
      </section>
      <section class="doctor-knowledge-section">
        <h3>候选来源</h3>
        ${renderList([
          `主分析 Knowledge：${humanDiseaseName(routing.selected_knowledge || routing.primary_hypothesis || "")}`,
          `候选角色：${hypothesisRoleLabel(hypothesis.role || "differential")}`,
          `当前状态：${routingEvidenceStatusLabel(hypothesis.status || "differential_candidate")}`,
          hypothesis.reason || "Alternative explanation retained by routing.",
        ])}
      </section>
      <section class="doctor-knowledge-section">
        <h3>进入正式 Knowledge 前需要</h3>
        ${renderList([
          "由 KnowledgeBuilder 检索指南或共识来源。",
          "抽取 clinical / imaging / quantitative / differential protocol。",
          "通过 validator 和人工审核。",
          "保存为正式 Knowledge 后进入 knowledge/ 复用，但状态仍为 needs_review。",
          "审核通过前 diagnosis_allowed=false，不作为正式确诊规则。",
        ])}
      </section>
    </div>
  `;
  renderKnowledgeList(listPayload);
}

function renderKnowledgeBuilderProposalDetail(detail = {}) {
  if (!detail || !Object.keys(detail).length) {
    return "";
  }
  const expected = Array.isArray(detail.expected_evidence_to_check)
    ? detail.expected_evidence_to_check
    : [];
  return `
    <div class="doctor-knowledge-subsection">
      <h4>KnowledgeBuilder 草案说明</h4>
      <p>${escapeHtml(detail.doctor_facing_summary || "当前候选已进入 KnowledgeBuilder proposal-only 草案。")}</p>
      ${renderMetricGrid({
        knowledge_id: detail.knowledge_id || "-",
        knowledge_type: detail.knowledge_type || "-",
        evidence_level: detail.evidence_level || "-",
        source_type: detail.source_type || "-",
        formal_knowledge_updated: detail.formal_knowledge_updated === true ? "是" : "否",
      })}
      ${renderGuidelineEvidenceSummary(detail)}
      ${expected.length ? `
        <div class="trace-subblock">
          <strong>需要复查的证据</strong>
          ${renderList(expected)}
        </div>
      ` : ""}
    </div>
  `;
}

function renderKnowledgeReviewWorkspace(detail) {
  const view = detail.doctor_view || {};
  const identity = view.identity || {};
  const clinical = view.clinical_profile || {};
  const imaging = Array.isArray(view.imaging_requirements) ? view.imaging_requirements : [];
  const findings = Array.isArray(view.visual_findings) ? view.visual_findings : [];
  const stages = Array.isArray(view.staging_rules) ? view.staging_rules : [];
  const safety = Array.isArray(view.safety_notes) ? view.safety_notes : [];
  const sources = Array.isArray(view.source_documents) ? view.source_documents : [];
  const draft = detail.draft || {};
  elements.knowledgeReviewStatus.textContent = draft.exists
    ? `已有医生草稿：${draft.draft_path}`
    : "医生审核模式：正式 Knowledge 可保存审核草稿；候选 Knowledge 可另存到正式库复用。";
  elements.knowledgeDetailView.innerHTML = `
    <div class="doctor-knowledge-workspace">
      <section class="doctor-knowledge-section">
        <h3>${escapeHtml(identity.disease_name || detail.knowledge_key || "未命名 Knowledge")}</h3>
        ${renderMetricGrid({
          knowledge_id: identity.knowledge_id,
          knowledge_type: identity.knowledge_type,
          evidence_level: identity.evidence_level,
          source: identity.source,
        })}
      </section>
      <section class="doctor-knowledge-section doctor-edit-grid">
        <label>常见症状
          <textarea id="knowledgeCommonSymptoms" rows="4">${escapeHtml((clinical.common_symptoms || []).join("\n"))}</textarea>
        </label>
        <label>危险因素
          <textarea id="knowledgeRiskFactors" rows="4">${escapeHtml((clinical.risk_factors || []).join("\n"))}</textarea>
        </label>
        <label>需要的影像检查
          <textarea id="knowledgeImageRequirements" rows="4">${escapeHtml(imaging.map((item) => item.label).join("\n"))}</textarea>
        </label>
        <label>医生审核备注
          <textarea id="knowledgeReviewNotes" rows="4" placeholder="写下需要修改、删除或补充的医学意见"></textarea>
        </label>
      </section>
      <section class="doctor-knowledge-section">
        <h3>影像征象</h3>
        <div class="doctor-finding-list">
          ${findings.map((finding, index) => renderDoctorFindingEditor(finding, index)).join("") || '<div class="trace-empty">暂无影像征象</div>'}
        </div>
      </section>
      <section class="doctor-knowledge-section">
        <h3>分期 / 判断规则</h3>
        ${renderDoctorStageCards(stages)}
      </section>
      <section class="doctor-knowledge-section">
        <h3>证据不足和下一步检查</h3>
        ${renderDoctorSafetyNotes(safety)}
      </section>
      <section class="doctor-knowledge-section">
        <h3>指南来源</h3>
        ${sources.length ? `<div class="citation-list">${sources.map(renderCitation).join("")}</div>` : '<div class="trace-empty">暂无来源</div>'}
      </section>
    </div>
  `;
}

function renderDoctorFindingEditor(finding, index) {
  return `
    <article class="doctor-finding-card" data-finding-index="${index}">
      <div>
        <strong>${escapeHtml(finding.display_name || finding.target || "影像征象")}</strong>
        <span>${escapeHtml(finding.doctor_execution_label || "按当前工具计划处理")}</span>
      </div>
      <p>${escapeHtml(finding.description || "暂无描述")}</p>
      ${renderMetricGrid({
        target: finding.target,
        required_modalities: Array.isArray(finding.required_modalities) ? finding.required_modalities.join(", ") : finding.required_modalities,
        measurements: Array.isArray(finding.measurements) ? finding.measurements.join(", ") : finding.measurements,
        diagnostic_role: finding.diagnostic_role,
      })}
      <label>医生对该征象的修改意见
        <textarea class="knowledgeFindingComment" rows="2" data-target="${escapeHtml(finding.target || "")}" data-display-name="${escapeHtml(finding.display_name || finding.target || "")}" placeholder="例如：描述不准确 / 需要补充典型表现 / 不建议分割"></textarea>
      </label>
    </article>
  `;
}

function renderDoctorStageCards(stages) {
  if (!stages.length) {
    return '<div class="trace-empty">暂无分期规则</div>';
  }
  return `
    <div class="doctor-stage-list">
      ${stages.map((stage) => `
        <article class="doctor-stage-card">
          <strong>${escapeHtml(stage.stage || "分期")}</strong>
          <p>${escapeHtml(stage.description || "-")}</p>
          ${renderList(stage.features || [])}
        </article>
      `).join("")}
    </div>
  `;
}

function renderDoctorSafetyNotes(notes) {
  if (!notes.length) {
    return '<div class="trace-empty">暂无证据不足规则</div>';
  }
  return `
    <div class="doctor-safety-list">
      ${notes.map((note) => `
        <article class="doctor-safety-card">
          <strong>${escapeHtml(note.status || "提示")}</strong>
          <p>${escapeHtml(note.reason || "-")}</p>
          ${renderMetricGrid({condition: note.condition, modality: note.modality, region: note.region})}
        </article>
      `).join("")}
    </div>
  `;
}

function buildKnowledgeDraftPayload() {
  const comments = Array.from(elements.knowledgeDetailView.querySelectorAll(".knowledgeFindingComment"))
    .map((input) => ({
      target: input.dataset.target,
      display_name: input.dataset.displayName,
      doctor_comment: input.value.trim(),
    }))
    .filter((item) => item.doctor_comment);
  return {
    reviewer_name: "doctor_reviewer",
    sections: {
      clinical_profile: {
        common_symptoms: splitListByLine(document.getElementById("knowledgeCommonSymptoms")?.value || ""),
        risk_factors: splitListByLine(document.getElementById("knowledgeRiskFactors")?.value || ""),
      },
      imaging_requirements: splitListByLine(document.getElementById("knowledgeImageRequirements")?.value || ""),
      visual_findings_review: comments,
      review_notes: document.getElementById("knowledgeReviewNotes")?.value.trim() || "",
    },
  };
}

function splitListByLine(value) {
  return value
    .split(/[\n，,;；]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function renderGuidelineEvidence(payload) {
  const bundle = payload.evidence_bundle || {};
  const report = payload.report || {};
  const evidence = bundle.knowledge_evidence?.guideline_evidence || payload.guideline_evidence || report.guideline_evidence || {};
  const citations = Array.isArray(evidence.citations) ? evidence.citations : [];
  const sourceDocuments = Array.isArray(evidence.source_documents) ? evidence.source_documents : [];
  const references = citations.length ? citations : sourceDocuments;
  const conflictsHtml = renderGuidelineConflicts(evidence);
  const sourcePriorityHtml = renderSourcePriority(evidence);
  if (!references.length && !conflictsHtml && !sourcePriorityHtml) {
    return "";
  }
  return `
    <div class="report-section guideline-evidence">
      <h3>指南依据</h3>
      ${sourcePriorityHtml}
      ${conflictsHtml}
      ${references.length ? `<div class="citation-list">${references.map(renderCitation).join("")}</div>` : ""}
    </div>
  `;
}

function getAlignmentPlan(payload) {
  return payload.alignment_plan
    || payload.evidence_bundle?.knowledge_evidence?.alignment_plan
    || payload.report?.alignment_plan
    || {};
}

function renderAlignmentPlan(payload) {
  const plan = getAlignmentPlan(payload);
  if (!Object.keys(plan).length) {
    elements.alignmentView.innerHTML = '<div class="trace-empty">本次响应未返回 alignment plan</div>';
    return;
  }
  const imageContext = plan.image_context || {};
  const tasks = Array.isArray(plan.visual_tasks) ? plan.visual_tasks : [];
  const suspected = Array.isArray(plan.suspected_conditions) ? plan.suspected_conditions : [];
  const nextImages = Array.isArray(plan.required_next_images) ? plan.required_next_images : [];
  const insufficiencyReasons = Array.isArray(plan.insufficiency_reasons) ? plan.insufficiency_reasons : [];
  elements.alignmentView.innerHTML = `
    <div class="alignment-summary">
      <span class="alignment-status alignment-status-${escapeClassName(plan.analysis_status)}">
        ${escapeHtml(statusLabel(plan.analysis_status))}
      </span>
      <span>${escapeHtml(plan.clinical_focus || "-")}</span>
    </div>
    <div class="trace-block">
      <h3>图像与 Knowledge</h3>
      ${renderMetricGrid({
        selected_knowledge: plan.selected_knowledge,
        modality: imageContext.modality,
        body_part: imageContext.body_part,
        available_sequences: Array.isArray(imageContext.available_sequences)
          ? imageContext.available_sequences.join(", ")
          : imageContext.available_sequences,
      })}
    </div>
    <div class="trace-block">
      <h3>视觉任务</h3>
      ${renderAlignmentTasks(tasks)}
    </div>
    <div class="trace-block">
      <h3>疑似方向</h3>
      ${renderConditionList(suspected)}
    </div>
    <div class="trace-block">
      <h3>建议补充影像</h3>
      ${renderNextImageList(nextImages)}
    </div>
    <div class="trace-block">
      <h3>证据限制</h3>
      ${renderList(insufficiencyReasons)}
    </div>
  `;
}

function statusLabel(status) {
  const labels = {
    evidence_sufficient: "证据充分",
    partial_evidence: "部分证据",
    insufficient_evidence: "证据不足",
    contraindicated_or_wrong_modality: "图像不匹配",
  };
  return labels[status] || status || "-";
}

function renderAlignmentTasks(tasks) {
  if (!tasks.length) {
    return '<div class="trace-empty">-</div>';
  }
  return `
    <div class="alignment-task-list">
      ${tasks.map((task) => `
        <div class="alignment-task">
          <strong>${escapeHtml(task.task || "-")}</strong>
          <span>${escapeHtml(taskStatusLabel(task.status))}</span>
          <p>${escapeHtml(task.required_input || "-")}</p>
          <p>${escapeHtml(task.reason || "-")}</p>
        </div>
      `).join("")}
    </div>
  `;
}

function taskStatusLabel(status) {
  const labels = {
    runnable: "可执行",
    missing_input: "缺少输入",
    unassessed: "未评估",
    candidate_passed_qc: "候选分割通过质量检查",
    failed_qc: "质量检查未通过",
    not_run: "未运行",
    not_ready: "未就绪",
  };
  return labels[status] || status || "-";
}

function renderConditionList(items) {
  if (!items.length) {
    return '<div class="trace-empty">-</div>';
  }
  return `
    <div class="detail-list">
      ${items.map((item) => `
        <div>
          <strong>${escapeHtml(item.disease || "-")}</strong>
          <p>${escapeHtml(item.reason || "-")}</p>
        </div>
      `).join("")}
    </div>
  `;
}

function renderNextImageList(items) {
  if (!items.length) {
    return '<div class="trace-empty">-</div>';
  }
  return `
    <div class="detail-list">
      ${items.map((item) => `
        <div>
          <strong>${escapeHtml([item.region, item.modality].filter(Boolean).join(" ") || "-")}</strong>
          <p>${escapeHtml(item.reason || "-")}</p>
        </div>
      `).join("")}
    </div>
  `;
}

function escapeClassName(value) {
  return String(value || "unknown").replace(/[^a-zA-Z0-9_-]/g, "-");
}

function renderSourcePriority(evidence) {
  const sources = Array.isArray(evidence.source_priority) ? evidence.source_priority : [];
  if (!sources.length) {
    return "";
  }
  return `
    <div class="source-priority">
      <strong>来源优先级</strong>
      ${sources.map((source) => {
        const title = source.title || source.source_id || "未命名来源";
        const meta = [source.publication_year, source.region, source.source_priority ? `priority ${source.source_priority}` : ""]
          .filter(Boolean)
          .join(" · ");
        return `<span>${escapeHtml(String(title))}${meta ? ` (${escapeHtml(meta)})` : ""}</span>`;
      }).join("")}
    </div>
  `;
}

function renderGuidelineConflicts(evidence) {
  const conflicts = Array.isArray(evidence.conflicts) ? evidence.conflicts : [];
  if (!conflicts.length) {
    return "";
  }
  return `
    <div class="guideline-conflicts">
      <strong>指南冲突需复核</strong>
      ${conflicts.map((conflict) => {
        const field = conflict.field || "unknown_field";
        const resolution = conflict.resolution || "review_required";
        const severity = conflict.severity ? `[${conflict.severity}] ` : "";
        return `<span>${escapeHtml(severity + String(field))}: ${escapeHtml(String(resolution))}</span>`;
      }).join("")}
    </div>
  `;
}

function renderCitation(citation) {
  const title = citation.title || citation.source_id || "未命名来源";
  const publisher = citation.publisher || citation.source_kind || "";
  const evidenceNote = citation.evidence_note || "";
  const sectionId = citation.section_id ? `#${citation.section_id}` : "";
  const url = citation.url || "";
  const urlHtml = url
    ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">打开来源</a>`
    : "";
  const meta = [publisher, sectionId].filter(Boolean).join(" · ");
  return `
    <div class="citation-item">
      <strong>${escapeHtml(String(title))}</strong>
      ${meta ? `<span class="citation-meta">${escapeHtml(meta)}</span>` : ""}
      ${evidenceNote ? `<p>${escapeHtml(String(evidenceNote))}</p>` : ""}
      ${urlHtml}
    </div>
  `;
}

function renderReport(payload) {
  const report = payload.report || {};
  const knowledgeProposalHtml = renderKnowledgeProposalReport(payload);
  if (knowledgeProposalHtml) {
    setReportHtml(`${renderRoutingClinicalSummary(payload)}${knowledgeProposalHtml}`);
    return;
  }
  if (!Object.keys(report).length && payload.reply_to_patient) {
    setReportHtml(`<div class="report-section"><p>${escapeHtml(payload.reply_to_patient)}</p></div>`);
    return;
  }
  const routingSummaryHtml = renderRoutingClinicalSummary(payload);
  const evidenceProtocolModeHtml = renderEvidenceProtocolModeSummary(payload);
  const patientSummaryHtml = renderPatientDiagnosisSummary(payload);
  const hasStructuredReport = Boolean(patientSummaryHtml);
  if (patientSummaryHtml) {
    elements.reportView.innerHTML = `${routingSummaryHtml}${evidenceProtocolModeHtml}${patientSummaryHtml}`;
    return;
  }
  const reportHtml = renderLegacyReportSections(report, hasStructuredReport);
  const differentialHtml = renderDifferentialConsiderations(payload);
  const guidelineEvidenceHtml = renderGuidelineEvidence(payload);
  setReportHtml(
    routingSummaryHtml || reportHtml || differentialHtml || guidelineEvidenceHtml
      ? `${routingSummaryHtml}${evidenceProtocolModeHtml}${reportHtml}${differentialHtml}${guidelineEvidenceHtml}`
      : '<div class="report-empty">无报告字段</div>'
  );
}

function setReportHtml(html) {
  elements.reportView.innerHTML = html;
  bindManualSecondaryActionButtons();
}

function bindManualSecondaryActionButtons() {
  elements.reportView.querySelectorAll("[data-secondary-knowledge-key]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      selectManualSecondaryKnowledge(button.dataset.secondaryKnowledgeKey);
    });
  });
  elements.reportView.querySelectorAll("[data-secondary-knowledge-remove-key]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      removeManualSecondaryKnowledge(button.dataset.secondaryKnowledgeRemoveKey);
    });
  });
}

function renderEvidenceProtocolModeSummary(payload) {
  const report = payload.report || {};
  const summary = payload.evidence_protocol_mode_summary || report["证据提取范围"] || {};
  if (!Object.keys(summary).length) {
    return "";
  }
  return `
    <div class="report-section evidence-protocol-mode-summary">
      <h3>证据提取范围</h3>
      <p>${escapeHtml(summary.doctor_facing_summary || summary.mode_label || "")}</p>
      ${summary.safety_boundary ? `<p class="muted">${escapeHtml(summary.safety_boundary)}</p>` : ""}
    </div>
  `;
}

function renderPatientDiagnosisSummary(payload) {
  const report = payload.report || {};
  const integrated = report.integrated_reasoning_summary || {};
  const hasStructuredReport = Boolean(
    Object.keys(integrated).length
    || Object.keys(report.target_disease_assessment || {}).length
    || Object.keys(report.imaging_evidence_summary || {}).length
    || Array.isArray(report.recommendation)
    || Array.isArray(report.missing_evidence)
  );
  if (!hasStructuredReport) {
    return "";
  }
  const evidenceItems = patientDiagnosisEvidenceItems(payload).slice(0, 5);
  const lesionHighlights = patientDiagnosisLesionHighlights(payload).slice(0, 4);
  const nextSteps = patientDiagnosisNextSteps(payload).slice(0, 3);
  const stagingHtml = renderOnfhStagingAssessment(payload);
  return `
    <div class="report-section patient-diagnosis-summary" aria-label="患者诊断摘要">
      <h3>重点结论</h3>
      <div class="patient-priority-grid">
        <article class="patient-priority-card patient-priority-disease">
          <h4>疾病判断</h4>
          ${renderPatientPrimaryDiagnosis(payload)}
          ${renderPatientSecondaryReviewSummary(payload)}
        </article>
        <article class="patient-priority-card patient-priority-lesions">
          <h4>发现的病灶/征象</h4>
          ${lesionHighlights.length ? renderList(lesionHighlights) : "<p>当前报告没有返回明确可用的病灶或影像征象。</p>"}
        </article>
        <article class="patient-priority-card patient-priority-boundary">
          <h4>疑似/确诊边界</h4>
          <p>${escapeHtml(patientDiagnosisBoundary(payload))}</p>
        </article>
      </div>
      <div class="patient-summary-block">
        <h4>主要依据</h4>
        ${evidenceItems.length ? renderList(evidenceItems) : "<p>当前没有足够稳定的可诊断依据。</p>"}
      </div>
      ${stagingHtml}
      <div class="patient-summary-block">
        <h4>下一步</h4>
        ${nextSteps.length ? renderList(nextSteps) : "<p>建议结合线下医生评估后决定补充检查。</p>"}
      </div>
    </div>
  `;
}

function renderOnfhStagingAssessment(payload) {
  const staging = onfhStagingSummary(payload);
  if (!staging || !Object.keys(staging).length) {
    return "";
  }
  const supporting = Array.isArray(staging.supporting_findings || staging.supporting)
    ? (staging.supporting_findings || staging.supporting).filter(Boolean)
    : [];
  return `
    <div class="patient-summary-block onfh-staging-summary">
      <h4>分期辅助</h4>
      <p><strong>${escapeHtml(staging.stage || "不能分期")}</strong></p>
      ${supporting.length ? `<p>分期依据：${escapeHtml(supporting.join("、"))}</p>` : ""}
      ${staging.rationale ? `<p>${escapeHtml(staging.rationale)}</p>` : ""}
      ${staging.limitations ? `<p class="muted">${escapeHtml(staging.limitations)}</p>` : ""}
    </div>
  `;
}

function patientDiagnosisHeadline(payload) {
  const report = payload.report || {};
  const onfh = payload.onfh_assessment || report.onfh_assessment || {};
  if (onfh.flow_type === "negative" && onfh.conclusion) {
    return String(onfh.conclusion);
  }
  const integrated = report.integrated_reasoning_summary || {};
  const assessment = report.target_disease_assessment || {};
  const targetDisease = integrated.target_disease || assessment.target_disease || payload.routing_decision?.primary_hypothesis;
  const diseaseName = humanDiseaseName(targetDisease || "");
  const canConfirm = integrated.can_confirm_target_disease === true || assessment.can_confirm_target_disease === true;
  const confidence = primaryDiagnosticConfidence(payload);
  if (confidence) {
    return diagnosticConfidenceSentence(confidence);
  }
  if (canConfirm) {
    return diseaseName ? `支持/倾向：${diseaseName}` : "支持/倾向：目标疾病";
  }
  const status = integrated.evidence_status || assessment.evidence_status || payload.routing_decision?.routing_evidence_status;
  if (status === "insufficient" || status === "requires_evidence_acquisition") {
    return diseaseName ? `不能确认：${diseaseName}` : "不能确认目标疾病";
  }
  const tendency = report.diagnostic_tendency || report["诊断倾向"];
  if (tendency) {
    return String(tendency);
  }
  return diseaseName ? `疑似方向：${diseaseName}` : "当前未形成明确疾病判断";
}

function renderPatientPrimaryDiagnosis(payload) {
  const confidence = primaryDiagnosticConfidence(payload);
  const staging = onfhPriorityStagingSummary(payload);
  if (!confidence) {
    return `
      <p class="diagnosis-main-text">${escapeHtml(patientDiagnosisHeadline(payload))}</p>
      ${renderDiagnosisStageSnippet(staging)}
    `;
  }
  const diseaseName = confidence.disease_name || humanDiseaseName(confidence.disease_key || "") || "目标疾病";
  const level = confidence.confidence_label || confidence.confidence_level || "未分级";
  const scoreText = `规则支持等级：${diagnosticSupportTierLabel(confidence)}`;
  const basis = Array.isArray(confidence.basis) ? confidence.basis.filter(Boolean).slice(0, 3) : [];
  return `
    <div class="diagnosis-main-line">
      <strong>${escapeHtml(diseaseName)}</strong>
      <span class="diagnosis-confidence-pill">${escapeHtml(level)}</span>
    </div>
    <p class="diagnosis-score-line">${escapeHtml(scoreText)}</p>
    ${renderDiagnosisStageSnippet(staging)}
    ${basis.length ? `
      <p class="diagnosis-confidence-note">依据：${escapeHtml(basis.join("、"))}</p>
    ` : ""}
    <p class="diagnosis-confidence-note">该支持度由当前 evidence bundle 的规则估计得到，不是校准后的真实患病概率。</p>
  `;
}

function renderDiagnosisStageSnippet(staging) {
  if (!staging) {
    return "";
  }
  return `
    <div class="diagnosis-stage-line">
      <span>分期辅助</span>
      <strong>${escapeHtml(staging.stage)}</strong>
    </div>
    ${staging.supporting.length ? `
      <p class="diagnosis-confidence-note">分期依据：${escapeHtml(staging.supporting.join("、"))}</p>
    ` : ""}
  `;
}

function onfhPriorityStagingSummary(payload) {
  const staging = onfhStagingSummary(payload);
  const stage = staging?.stage || "";
  if (!stage || stage === "不能分期") {
    return null;
  }
  return {
    stage,
    supporting: Array.isArray(staging.supporting_findings || staging.supporting)
      ? (staging.supporting_findings || staging.supporting).filter(Boolean).slice(0, 4)
      : [],
  };
}

function onfhStagingSummary(payload) {
  const assessment = payload.onfh_assessment || payload.report?.onfh_assessment || {};
  const staging = assessment.staging_assessment || payload.report?.["分期辅助"] || {};
  if (staging && Object.keys(staging).length) {
    return staging;
  }
  return deriveOnfhStagingFromVisibleFindings(payload);
}

function deriveOnfhStagingFromVisibleFindings(payload) {
  const lesionText = patientDiagnosisLesionHighlights(payload).join(" ");
  const supporting = [];
  if (/塌陷|collapse/i.test(lesionText)) {
    supporting.push("股骨头塌陷");
  }
  if (/新月|软骨下骨折|subchondral[_\s-]*fracture|crescent/i.test(lesionText)) {
    supporting.push("新月征/软骨下骨折");
  }
  if (supporting.length) {
    return {
      stage: "疑似 ARCO III 或以上",
      confidence: "stage_suspected_from_visible_findings",
      supporting_findings: uniqueStrings(supporting),
      rationale: "塌陷、新月征或软骨下骨折提示进入塌陷相关阶段。",
      limitations: "仍需标准体位 X 光或 MRI 明确塌陷范围和坏死面积。",
    };
  }
  if (/硬化|sclerotic/i.test(lesionText)) {
    supporting.push("硬化带");
  }
  if (/囊性|囊变|cystic/i.test(lesionText)) {
    supporting.push("囊性变");
  }
  if (/骨小梁|trabecular|纹理/i.test(lesionText)) {
    supporting.push("骨小梁模糊");
  }
  if (supporting.length) {
    return {
      stage: "疑似 ARCO II",
      confidence: "stage_suspected_from_visible_findings",
      supporting_findings: uniqueStrings(supporting),
      rationale: "X 光可见硬化、囊性变或骨小梁异常，且当前未显示明确塌陷相关征象。",
      limitations: "MRI 可进一步确认坏死范围，并排除早期或隐匿性改变。",
    };
  }
  return {};
}

function renderPatientSecondaryReviewSummary(payload) {
  const items = patientSecondaryReviewItems(payload);
  if (!items.length) {
    return "";
  }
  const title = patientSecondaryReviewTitle(payload);
  return `
    <div class="patient-secondary-review-summary">
      <div class="secondary-review-heading">
        <strong>${escapeHtml(title)}</strong>
        <small>按备用 Knowledge 专属视觉协议复查</small>
      </div>
      <ul>
        ${items.map((item) => `
          <li class="secondary-review-${escapeHtml(item.confidenceLevel)}">
            <div>
              <span>${escapeHtml(item.diseaseName)}</span>
              <em class="secondary-review-pill">${escapeHtml(item.confidenceText)}</em>
            </div>
            <small class="secondary-review-evidence">${escapeHtml(item.evidenceText)}</small>
          </li>
        `).join("")}
      </ul>
    </div>
  `;
}

function patientSecondaryReviewTitle(payload) {
  const mode = payload.routing_decision?.knowledge_selection_mode || payload.knowledge_selection_mode || "";
  if (mode === "agent_auto_secondary") {
    return "Agent 自动备用复查";
  }
  if (mode === "manual_secondary") {
    return "人工备用复查";
  }
  return "备用复查";
}

function patientSecondaryReviewItems(payload) {
  const report = payload.report || {};
  const items = Array.isArray(payload.secondary_knowledge_analysis)
    ? payload.secondary_knowledge_analysis
    : Array.isArray(report["备用 Knowledge 复查结果"])
      ? report["备用 Knowledge 复查结果"]
      : [];
  return items
    .filter((item) => item && Object.keys(item).length)
    .slice(0, 3)
    .map((item) => {
      const review = item.differential_review || {};
      const confidence = review.diagnostic_confidence || {};
      const confidenceLevel = confidence.confidence_level || "insufficient";
      return {
        diseaseName: item.disease_name || humanDiseaseName(item.disease_key || "") || "备用疾病",
        confidenceText: secondaryConfidenceText(confidence),
        confidenceLevel,
        evidenceText: secondaryReviewEvidenceLine(item),
      };
    });
}

function secondaryReviewEvidenceLine(item = {}) {
  const bundle = item.secondary_visual_evidence_bundle || {};
  const findings = Array.isArray(bundle.findings) ? bundle.findings : [];
  const present = Array.isArray(bundle.present_findings) ? bundle.present_findings : [];
  const labels = uniqueStrings([
    ...findings.map((finding) => visualFindingDisplayName(finding)),
    ...present.map(humanFindingName),
  ]).filter(Boolean).slice(0, 3);
  if (labels.length) {
    return `按备用 Knowledge 专属视觉协议复查：${labels.join("、")}`;
  }
  if (item.secondary_visual_status === "ok") {
    return "按备用 Knowledge 专属视觉协议复查：未提取到该备用病种的专属支持征象";
  }
  const review = item.differential_review || {};
  const current = review.current_observation_summary || "";
  if (current) {
    return current;
  }
  return "未提取到该备用病种的专属支持征象";
}

function primaryDiagnosticConfidence(payload) {
  const items = Array.isArray(payload.diagnostic_confidence)
    ? payload.diagnostic_confidence
    : Array.isArray(payload.report?.["诊断置信度"])
      ? payload.report["诊断置信度"]
      : [];
  return items.find((item) => item?.role === "primary")
    || items[0]
    || derivedPrimaryDiagnosticConfidence(payload);
}

function derivedPrimaryDiagnosticConfidence(payload) {
  const report = payload.report || {};
  const integrated = report.integrated_reasoning_summary || {};
  const assessment = report.target_disease_assessment || {};
  const targetDisease = integrated.target_disease || assessment.target_disease || payload.routing_decision?.primary_hypothesis;
  if (targetDisease !== "femoral_head_necrosis") {
    return null;
  }
  const lesionText = patientDiagnosisLesionHighlights(payload).join(" ");
  const hasSclerotic = /硬化|sclerotic/i.test(lesionText);
  const hasCystic = /囊性|囊变|cystic/i.test(lesionText);
  const hasCollapse = /塌陷|新月|软骨下骨折|collapse|crescent|subchondral[_\s-]*fracture/i.test(lesionText);
  if (!hasSclerotic && !hasCystic && !hasCollapse) {
    return null;
  }
  const confidenceLevel = hasCollapse || (hasSclerotic && hasCystic) ? "high" : "moderate";
  const confidenceLabel = confidenceLevel === "high" ? "高度支持" : "中等支持";
  const confidenceScore = confidenceLevel === "high" ? 0.82 : 0.62;
  const basis = [];
  if (hasSclerotic) basis.push("硬化带");
  if (hasCystic) basis.push("囊性变");
  if (hasCollapse) basis.push("股骨头塌陷/新月征");
  return {
    disease_key: "femoral_head_necrosis",
    disease_name: "股骨头坏死",
    role: "primary",
    confidence_level: confidenceLevel,
    confidence_label: confidenceLabel,
    confidence_score: confidenceScore,
    basis,
    caveat: confidenceLevel === "high"
      ? "当前 X 光征象已经高度支持股骨头坏死方向；建议 MRI 明确坏死范围、分期和是否存在早期塌陷，最终仍需影像科/骨科医生结合病史确认。"
      : "当前 X 光征象中等支持股骨头坏死方向；如症状持续或风险因素明确，建议 MRI 进一步评估。",
  };
}

function diagnosticConfidenceSentence(confidence = {}) {
  const diseaseName = confidence.disease_name || humanDiseaseName(confidence.disease_key || "") || "目标疾病";
  const level = confidence.confidence_label || confidence.confidence_level || "未分级";
  if (confidence.confidence_level === "insufficient") {
    return `证据不足：${diseaseName}`;
  }
  return `影像证据${level}：${diseaseName}，规则支持等级：${diagnosticSupportTierLabel(confidence)}`;
}

function diagnosticSupportTierLabel(confidence = {}) {
  const label = confidence.confidence_label || confidence.confidence_level || "";
  const level = String(confidence.confidence_level || "").toLowerCase();
  if (label.includes("高度") || level === "high") {
    return "高度";
  }
  if (label.includes("中等") || level === "moderate" || level === "medium") {
    return "中度";
  }
  if (label.includes("不足") || level === "insufficient" || level === "low") {
    return "证据不足";
  }
  return label || "证据不足";
}

function patientDiagnosisLesionHighlights(payload) {
  const report = payload.report || {};
  const integrated = report.integrated_reasoning_summary || {};
  const imaging = integrated.imaging_support || report.imaging_evidence_summary || {};
  const visualBundle = getVisualEvidenceBundle(payload);
  const visibleFindings = patientVisibleFindings(visualBundle)
    .map((finding) => finding.text
      ? `${finding.title}：${finding.text}`
      : finding.title
    );
  const supportedTargets = Array.isArray(imaging.supported_targets)
    ? uniquePatientFindingNames(imaging.supported_targets).map((name) => `可参考发现：${name}`)
    : [];
  const presentFindings = Array.isArray(visualBundle.present_findings)
    ? uniquePatientFindingNames(visualBundle.present_findings).map((name) => `视觉候选：${name}`)
    : [];
  return uniqueStrings([
    ...visibleFindings,
    ...supportedTargets,
    ...presentFindings,
  ]).filter(Boolean);
}

function patientDiagnosisBoundary(payload) {
  const primaryConclusion = patientDiagnosisConclusion(payload);
  return primaryConclusion;
}

function patientDiagnosisConclusion(payload) {
  const report = payload.report || {};
  const onfh = payload.onfh_assessment || report.onfh_assessment || {};
  if (onfh.conclusion) {
    return String(onfh.conclusion);
  }
  const integrated = report.integrated_reasoning_summary || {};
  const assessment = report.target_disease_assessment || {};
  const targetDisease = integrated.target_disease || assessment.target_disease || payload.routing_decision?.primary_hypothesis;
  const diseaseName = humanDiseaseName(targetDisease || "");
  const confidence = primaryDiagnosticConfidence(payload);
  if (confidence && confidence.confidence_level !== "insufficient") {
    return confidence.caveat || (
      diseaseName
        ? `当前证据支持${diseaseName}方向，但仍需医生结合完整检查确认。`
        : "当前证据支持目标疾病方向，但仍需医生结合完整检查确认。"
    );
  }
  if (integrated.can_confirm_target_disease === true || assessment.can_confirm_target_disease === true) {
    return diseaseName
      ? `当前证据支持${diseaseName}方向，但仍需医生结合完整检查确认。`
      : "当前证据支持目标疾病方向，但仍需医生结合完整检查确认。";
  }
  const status = integrated.evidence_status || assessment.evidence_status || payload.routing_decision?.routing_evidence_status;
  if (status === "insufficient" || status === "requires_evidence_acquisition") {
    return diseaseName
      ? `目前证据不足，不能仅凭当前资料确认${diseaseName}。`
      : "目前证据不足，不能仅凭当前资料确认目标疾病。";
  }
  return report.diagnostic_tendency || report["诊断倾向"] || payload.reply_to_patient || "当前报告未给出明确结论。";
}

function patientSecondaryKnowledgeConclusion(payload, options = {}) {
  const report = payload.report || {};
  const items = Array.isArray(payload.secondary_knowledge_analysis)
    ? payload.secondary_knowledge_analysis
    : Array.isArray(report["备用 Knowledge 复查结果"])
      ? report["备用 Knowledge 复查结果"]
      : [];
  const visibleItems = items.filter((item) => item && Object.keys(item).length).slice(0, 3);
  if (!visibleItems.length) {
    return "";
  }
  return visibleItems
    .map((item) => secondaryKnowledgeConclusionText(item, options))
    .filter(Boolean)
    .join(options.compact ? "；" : " ");
}

function secondaryConfidenceText(confidence = {}) {
  return `规则支持等级：${diagnosticSupportTierLabel(confidence)}`;
}

function secondaryKnowledgeConclusionText(item, options = {}) {
  const diseaseName = item.disease_name || humanDiseaseName(item.disease_key || "") || "备用疾病";
  const diagnosisAllowed = item.diagnosis_allowed === true;
  const review = item.differential_review || {};
  const confidence = review.diagnostic_confidence || {};
  const confidenceText = secondaryConfidenceText(confidence);
  if (diagnosisAllowed) {
    return options.compact
      ? `备用复查支持：${diseaseName}${confidenceText ? `（${confidenceText}）` : ""}`
      : `备用疾病复查：当前证据支持${diseaseName}方向${confidenceText ? `，支持度为${confidenceText}` : ""}，但仍需医生结合完整检查确认。`;
  }
  if (options.compact) {
    return `备用复查：${diseaseName}${confidenceText ? `（${confidenceText}）` : "证据不足"}`;
  }
  const weakSupport = Array.isArray(review.weak_supporting_evidence)
    ? review.weak_supporting_evidence.slice(0, 2)
    : [];
  const missing = Array.isArray(review.missing_required_evidence)
    ? review.missing_required_evidence.slice(0, 2)
    : [];
  const supportText = weakSupport.length
    ? `当前有 ${weakSupport.join("、")} 等弱提示，`
    : "";
  const missingText = missing.length
    ? `仍需复查 ${missing.join("、")}。`
    : "仍需补充针对性证据。";
  return `备用疾病复查：${diseaseName}当前证据支持度为${confidenceText || "证据不足"}，${supportText}${missingText}`;
}

function patientDiagnosisEvidenceItems(payload) {
  const report = payload.report || {};
  const onfh = payload.onfh_assessment || report.onfh_assessment || {};
  const integrated = report.integrated_reasoning_summary || {};
  const imaging = integrated.imaging_support || report.imaging_evidence_summary || {};
  const quantitative = integrated.quantitative_support || report.quantitative_evidence_summary || {};
  const missing = integrated.missing_evidence || {};
  const items = [];
  const supportedTargets = Array.isArray(imaging.supported_targets)
    ? imaging.supported_targets
    : [];
  if (supportedTargets.length) {
    items.push(`可参考发现：${uniquePatientFindingNames(supportedTargets).join("、")}`);
  }
  if (Array.isArray(onfh.detected_findings) && onfh.detected_findings.length) {
    items.push(`ONFH 征象：${onfh.detected_findings.map((item) => item.display_name || humanFindingName(item.target)).filter(Boolean).slice(0, 4).join("、")}`);
  }
  if (onfh.flow_type === "negative" && onfh.negative_category) {
    items.push(`阴性流程：${onfhNegativeCategoryLabel(onfh.negative_category)}`);
  }
  const nonspecificTargets = Array.isArray(imaging.nonspecific_or_unusable_targets)
    ? imaging.nonspecific_or_unusable_targets
    : [];
  if (nonspecificTargets.length) {
    items.push(`仅作提示：${uniquePatientFindingNames(nonspecificTargets).join("、")} 不能单独作为确诊依据。`);
  }
  const strongCount = Number(quantitative.strong_quantitative_support_count || 0);
  if (strongCount > 0) {
    items.push(`稳定量化支持：${strongCount} 项。`);
  } else {
    items.push("当前没有稳定的量化证据可以直接支持确诊。");
  }
  items.push(...secondaryReviewEvidenceItems(payload));
  const missingTargets = Array.isArray(missing.missing_required_targets)
    ? missing.missing_required_targets
    : [];
  if (missingTargets.length) {
    items.push(`仍缺少：${missingTargets.slice(0, 3).map(patientMissingEvidenceName).join("、")}。`);
  }
  return items;
}

function onfhNegativeCategoryLabel(category) {
  const labels = {
    image_quality_or_view_insufficient: "图像质量或体位不足，当前无法可靠判断",
    xray_negative_but_clinical_risk_high: "X 光未见明确征象，但症状/风险因素强，建议 MRI",
    evidence_not_supportive: "当前证据不支持 ONFH，但建议随访观察",
  };
  return labels[category] || category || "阴性证据待复核";
}

function secondaryReviewEvidenceItems(payload) {
  const items = Array.isArray(payload.secondary_knowledge_analysis)
    ? payload.secondary_knowledge_analysis
    : [];
  return items
    .map((item) => item.differential_review?.report_sentence)
    .filter(Boolean)
    .slice(0, 2)
    .map((sentence) => `备用复查：${sentence}`);
}

function patientDiagnosisNextSteps(payload) {
  const report = payload.report || {};
  const integrated = report.integrated_reasoning_summary || {};
  const integratedSteps = Array.isArray(integrated.recommended_next_step)
    ? integrated.recommended_next_step
    : [];
  if (integratedSteps.length) {
    return integratedSteps;
  }
  if (Array.isArray(report.recommendation) && report.recommendation.length) {
    return report.recommendation;
  }
  if (Array.isArray(report["建议下一步"]) && report["建议下一步"].length) {
    return report["建议下一步"];
  }
  const legacyNext = report["建议进一步检查"];
  if (Array.isArray(legacyNext)) {
    return legacyNext;
  }
  if (legacyNext) {
    return [legacyNext];
  }
  return [];
}

function renderKnowledgeProposalReport(payload) {
  const proposal = payload.knowledge_builder_proposal || {};
  if (!Object.keys(proposal).length) {
    return "";
  }
  const missingEvidence = Array.isArray(payload.missing_evidence) ? payload.missing_evidence : [];
  const limitations = Array.isArray(payload.modality_limitations) ? payload.modality_limitations : [];
  const recommendations = Array.isArray(payload.recommendation) ? payload.recommendation : [];
  return `
    <div class="report-section report-knowledge-proposal">
      <h3>Knowledge Builder 候选草案</h3>
      <p>${escapeHtml(payload.reply_to_patient || "当前缺少本地正式 knowledge，已进入候选草案流程。")}</p>
      ${renderMetricGrid({
        selected_knowledge: proposal.selected_knowledge,
        disease_name: proposal.disease_name,
        knowledge_type: proposal.knowledge_type,
        evidence_level: proposal.evidence_level,
        formal_update_allowed: proposal.formal_update_allowed === true ? "是" : "否",
        diagnosis_allowed: proposal.diagnosis_allowed === true ? "是" : "否",
      })}
      <p class="warning-text">不能直接诊断；候选 knowledge 需要指南来源与人工审核后才能进入正式诊断流程。</p>
      ${missingEvidence.length ? `<h4>缺失依据</h4>${renderList(missingEvidence.map((item) => `${item.field || "evidence"}：${item.reason || item.status || "-"}`))}` : ""}
      ${limitations.length ? `<h4>当前限制</h4>${renderList(limitations)}` : ""}
      ${recommendations.length ? `<h4>建议下一步</h4>${renderList(recommendations)}` : ""}
    </div>
  `;
}

function renderLegacyReportSections(report, hasStructuredReport) {
  const sections = hasStructuredReport
    ? [
        ["诊断倾向", report["诊断倾向"] || report.diagnostic_tendency],
        ["治疗建议", report["治疗建议"]],
      ]
    : [
        ["诊断倾向", report["诊断倾向"] || report.diagnostic_tendency],
        ["影像依据", report["影像依据"]],
        ["不确定性说明", report["不确定性说明"]],
        ["建议进一步检查", report["建议进一步检查"]],
        ["治疗建议", report["治疗建议"]],
      ];
  return sections
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([title, value]) => {
      const body = Array.isArray(value) ? renderList(value) : `<p>${escapeHtml(String(value))}</p>`;
      return `<div class="report-section"><h3>${escapeHtml(title)}</h3>${body}</div>`;
    })
    .join("");
}

function renderRoutingClinicalSummary(payload) {
  const routing = payload.routing_decision
    || payload.evidence_bundle?.knowledge_evidence?.routing_decision
    || {};
  const report = payload.report || {};
  const assessment = report.target_disease_assessment || {};
  const hypothesis = routing.primary_hypothesis || assessment.target_disease || routing.selected_knowledge;
  const status = routing.routing_evidence_status
    || routing.initial_evidence_status
    || assessment.evidence_status;
  if (!hypothesis && !status) {
    return "";
  }
  const parts = [];
  const selectedKnowledge = routing.selected_knowledge || hypothesis;
  if (routing.knowledge_selection_mode) {
    parts.push(`Knowledge 模式：${knowledgeSelectionModeLabel(routing.knowledge_selection_mode)}`);
  }
  if (selectedKnowledge) {
    parts.push(`主分析 Knowledge：${humanDiseaseName(selectedKnowledge)}`);
  }
  if (hypothesis) {
    parts.push(`Primary hypothesis：${humanDiseaseName(hypothesis)}`);
  }
  if (status) {
    parts.push(`证据状态：${routingEvidenceStatusLabel(status)}`);
  }
  const candidates = Array.isArray(routing.differential_knowledge_candidates)
    ? routing.differential_knowledge_candidates
    : [];
  const displayCandidates = Array.isArray(routing.display_differential_knowledge_candidates)
    ? routing.display_differential_knowledge_candidates
    : candidates.slice(0, 3);
  if (displayCandidates.length) {
    parts.push(`重点鉴别复核：${displayCandidates.map(humanDiseaseName).join("、")}`);
  }
  const hypotheses = Array.isArray(routing.clinical_hypotheses)
    ? routing.clinical_hypotheses
    : [];
  const secondaryAnalysisItems = Array.isArray(payload.secondary_knowledge_analysis)
    ? payload.secondary_knowledge_analysis
    : Array.isArray(report["备用 Knowledge 复查结果"])
      ? report["备用 Knowledge 复查结果"]
      : [];
  const hasSecondaryAnalysis = secondaryAnalysisItems.length > 0;
  const selectedSecondaryKnowledges = selectedManualSecondaryKnowledges();
  const visibleRoutingHypotheses = hypotheses.filter((item) => (
    item.role === "primary"
    || item.display_group === "strong_differential"
    || Number(item.priority) <= 1
  ));
  const collapsedRoutingHypotheses = hypotheses.filter((item) => (
    !visibleRoutingHypotheses.includes(item)
  ));
  const manualSecondaryCandidateKeys = uniqueStrings([
    ...displayCandidates,
    ...candidates,
    ...hypotheses
      .filter((item) => item.role === "differential")
      .map((item) => item.disease_key || item.target || ""),
  ]).filter((candidate) => candidate && candidate !== selectedKnowledge);
  const manualSecondaryCandidateHtml = renderManualSecondaryCandidateList(
    manualSecondaryCandidateKeys,
    selectedSecondaryKnowledges,
  );
  const secondaryKnowledgeNameItems = uniqueStrings(
    secondaryAnalysisItems
      .map((item) => item.disease_key || item.knowledge_id || item.target || "")
      .filter(Boolean),
  );
  const secondaryKnowledgeNamesHtml = secondaryKnowledgeNameItems.length
    ? `
      <div class="doctor-routing-knowledge-list" aria-label="已运行的备用 Knowledge">
        ${secondaryKnowledgeNameItems.map((knowledgeKey) => `
          <span>${escapeHtml(humanDiseaseName(knowledgeKey))}</span>
        `).join("")}
      </div>
    `
    : "";
  const doctorRoutingSummaryHtml = hasSecondaryAnalysis ? `
    <div class="doctor-routing-summary">
      <article class="doctor-routing-card">
        <strong>主分析 Knowledge</strong>
        <span>${escapeHtml(humanDiseaseName(selectedKnowledge || hypothesis || ""))}</span>
        <small>${escapeHtml(routingEvidenceStatusLabel(status || ""))}</small>
      </article>
      <article class="doctor-routing-card">
        <strong>备用复查状态</strong>
        <span>已按备用 Knowledge 运行复查</span>
        ${secondaryKnowledgeNamesHtml}
        <small>复查结果仍受 evidence bundle 和审核状态约束。</small>
      </article>
      ${secondaryAnalysisItems.slice(0, 3).map((item) => {
        const review = item.differential_review || {};
        const confidence = review.diagnostic_confidence || {};
        return `
          <article class="doctor-routing-card doctor-routing-secondary">
            <strong>${escapeHtml(humanDiseaseName(item.disease_key || ""))}</strong>
            <span>${escapeHtml(secondaryConfidenceText(confidence))}</span>
            <small>${escapeHtml(secondaryReviewEvidenceLine(item))}</small>
          </article>
        `;
      }).join("")}
    </div>
  ` : "";
  const hypothesisQueueHtml = hypotheses.length
    ? `
      <div class="hypothesis-queue">
        <strong>候选假设队列</strong>
        <ul>
          ${visibleRoutingHypotheses.map((item) => `
            <li>
              <span>${escapeHtml(hypothesisRoleLabel(item.role))}</span>
              <b>${escapeHtml(humanDiseaseName(item.disease_key || item.target || ""))}</b>
              <em>${escapeHtml(routingEvidenceStatusLabel(item.status || ""))}</em>
              ${item.reason ? `<small>${escapeHtml(item.reason)}</small>` : ""}
              ${renderManualSecondaryAction(item, selectedSecondaryKnowledges)}
            </li>
          `).join("")}
        </ul>
        ${collapsedRoutingHypotheses.length ? `
          <details class="routing-collapsed-hypotheses">
            <summary>更多鉴别候选（${collapsedRoutingHypotheses.length}）</summary>
            <ul>
              ${collapsedRoutingHypotheses.map((item) => `
                <li>
                  <span>${escapeHtml(item.display_group === "low_priority" ? "低优先级" : "条件性鉴别")}</span>
                  <b>${escapeHtml(humanDiseaseName(item.disease_key || item.target || ""))}</b>
                  <em>${escapeHtml(routingEvidenceStatusLabel(item.status || ""))}</em>
                  ${item.reason ? `<small>${escapeHtml(item.reason)}</small>` : ""}
                  ${renderManualSecondaryAction(item, selectedSecondaryKnowledges)}
                </li>
              `).join("")}
            </ul>
          </details>
        ` : ""}
        <p class="muted">${hasSecondaryAnalysis
          ? "这不是诊断结论；只是根据症状、部位和影像类型决定先检查哪些 evidence。下方已按备用 Knowledge 运行复查，复查结果仍受 evidence bundle 和审核状态约束。"
          : "这不是诊断结论；只是根据症状、部位和影像类型决定先检查哪些 evidence。当前只加载主分析 Knowledge；鉴别候选会进入 proposal-only Knowledge 审核队列，但不会被当作正式或已运行的诊断 Knowledge。"
        }</p>
      </div>
    `
    : "";
  const secondaryKnowledgeRunPlan = routing.secondary_knowledge_run_plan || {};
  const secondaryCandidates = Array.isArray(secondaryKnowledgeRunPlan.candidates)
    ? secondaryKnowledgeRunPlan.candidates
    : [];
  const secondaryKnowledgeRunHtml = secondaryKnowledgeRunPlan.status ? `
    <div class="hypothesis-queue secondary-knowledge-run-plan">
      <strong>${hasSecondaryAnalysis ? "已运行备用 Knowledge 复查" : "Secondary knowledge run"}</strong>
      <p>${escapeHtml(secondaryKnowledgeRunPlan.reason || routingEvidenceStatusLabel(secondaryKnowledgeRunPlan.status))}</p>
      ${secondaryCandidates.length ? `
        <ul>
          ${secondaryCandidates.map((item) => `
            <li>
              <span>${escapeHtml(hasSecondaryAnalysis ? "已按备用 Knowledge 运行复查" : item.review_status === "unreviewed" ? "未审核 Knowledge 可用于假设验证" : "正式 Knowledge")}</span>
              <b>${escapeHtml(humanDiseaseName(item.disease_key || ""))}</b>
              <em>${escapeHtml(item.use_scope || item.action || "")}</em>
              <small>${escapeHtml(item.diagnosis_allowed === false ? "不能作为正式确诊依据" : "可进入受证据约束的二级诊断")}</small>
              ${renderSecondaryKnowledgeBuilderProgress(item)}
            </li>
          `).join("")}
        </ul>
      ` : ""}
    </div>
  ` : "";
  const secondaryKnowledgeAnalysisHtml = renderSecondaryKnowledgeAnalysis(payload);
  const technicalRoutingDetailsHtml = hasSecondaryAnalysis ? `
    <details class="routing-technical-details">
      <summary>查看技术细节</summary>
      ${hypothesisQueueHtml}
      ${manualSecondaryCandidateHtml}
      ${secondaryKnowledgeRunHtml}
      ${secondaryKnowledgeAnalysisHtml}
    </details>
  ` : "";
  return `
    <div class="report-section report-path-summary">
      <h3>分析路径</h3>
      <p>${escapeHtml(parts.join("；"))}</p>
      ${hasSecondaryAnalysis ? doctorRoutingSummaryHtml : hypothesisQueueHtml}
      ${hasSecondaryAnalysis ? technicalRoutingDetailsHtml : manualSecondaryCandidateHtml}
      ${hasSecondaryAnalysis ? "" : secondaryKnowledgeRunHtml}
      ${hasSecondaryAnalysis ? "" : secondaryKnowledgeAnalysisHtml}
    </div>
  `;
}

function uniqueStrings(values) {
  const seen = new Set();
  return values.filter((value) => {
    const normalized = String(value || "").trim();
    if (!normalized || seen.has(normalized)) {
      return false;
    }
    seen.add(normalized);
    return true;
  });
}

function renderManualSecondaryCandidateList(candidateKeys, selectedSecondaryKnowledges = []) {
  const keys = Array.isArray(candidateKeys) ? candidateKeys : [];
  if (!keys.length) {
    return "";
  }
  return `
    <div class="hypothesis-queue manual-secondary-candidates">
      <strong>可追加备用复查</strong>
      <ul>
        ${keys.map((candidateKey) => `
          <li>
            <b>${escapeHtml(humanDiseaseName(candidateKey))}</b>
            ${renderManualSecondaryAction(
              {disease_key: candidateKey, role: "differential"},
              selectedSecondaryKnowledges,
            )}
          </li>
        `).join("")}
      </ul>
      <p class="muted">点击候选后会切换到人工备用 Knowledge 模式；如果本地没有正式 Knowledge，会先走 KnowledgeBuilder proposal，并仅用于 hypothesis validation。</p>
    </div>
  `;
}

function renderManualSecondaryAction(item, selectedSecondaryKnowledges = []) {
  const diseaseKey = item.disease_key || item.target || "";
  if (!diseaseKey || item.role !== "differential") {
    return "";
  }
  const selected = selectedSecondaryKnowledges.includes(diseaseKey);
  return `
    <button
      type="button"
      class="secondary-knowledge-action${selected ? " selected" : ""}"
      ${selected
        ? `data-secondary-knowledge-remove-key="${escapeHtml(diseaseKey)}"`
        : `data-secondary-knowledge-key="${escapeHtml(diseaseKey)}"`}
    >${selected ? "取消备用复查" : "加入备用复查"}</button>
  `;
}

function renderSecondaryKnowledgeAnalysis(payload) {
  const report = payload.report || {};
  const items = Array.isArray(payload.secondary_knowledge_analysis)
    ? payload.secondary_knowledge_analysis
    : Array.isArray(report["备用 Knowledge 复查结果"])
      ? report["备用 Knowledge 复查结果"]
      : [];
  if (!items.length) {
    return "";
  }
  return `
    <div class="hypothesis-queue secondary-knowledge-analysis">
      <strong>备用 Knowledge 复查结果</strong>
      <ul>
        ${items.map((item) => `
          <li>
            <b>${escapeHtml(humanDiseaseName(item.disease_key || ""))}</b>
            <em>${escapeHtml(item.analysis_mode || "")}</em>
            <small>${escapeHtml(item.evidence_boundary || "")}</small>
            ${item.finding ? `<small>${escapeHtml(item.finding)}</small>` : ""}
            ${renderGuidelineEvidenceSummary(item.guideline_evidence_summary || item.knowledge_builder_proposal_detail || {})}
            ${renderSecondaryVisualEvidenceSummary(item)}
            ${renderSecondaryDifferentialReview(item.differential_review)}
            ${renderSecondaryKnowledgeBuilderProgress(item)}
          </li>
        `).join("")}
      </ul>
    </div>
  `;
}

function renderSecondaryVisualEvidenceSummary(item = {}) {
  const bundle = item.secondary_visual_evidence_bundle || {};
  const findings = Array.isArray(bundle.findings) ? bundle.findings : [];
  const present = Array.isArray(bundle.present_findings) ? bundle.present_findings : [];
  const labels = uniqueStrings([
    ...findings.map((finding) => visualFindingDisplayName(finding)),
    ...present.map(humanFindingName),
  ]).filter(Boolean).slice(0, 5);
  const status = item.secondary_visual_protocol_status || item.secondary_visual_status || "";
  if (!labels.length && !status) {
    return "";
  }
  return `
    <div class="trace-subblock secondary-visual-evidence-summary">
      <strong>备用视觉证据包</strong>
      ${status ? `<small>视觉协议状态：${escapeHtml(status)}</small>` : ""}
      ${labels.length ? `<small>备用 Knowledge 观察到：${escapeHtml(labels.join("、"))}</small>` : ""}
    </div>
  `;
}

function renderGuidelineEvidenceSummary(summary = {}) {
  const sourceTitles = Array.isArray(summary.source_titles) ? summary.source_titles : [];
  const guidelineSections = Array.isArray(summary.guideline_sections) ? summary.guideline_sections : [];
  if (!sourceTitles.length && !guidelineSections.length && !summary.citation_status) {
    return "";
  }
  return `
    <div class="trace-subblock guideline-evidence-summary">
      <strong>指南/规则来源</strong>
      ${sourceTitles.length ? `
        <small>来源：${escapeHtml(sourceTitles.slice(0, 3).join("；"))}</small>
      ` : ""}
      ${guidelineSections.length ? `
        <small>已抽取结构：${escapeHtml(guidelineSections.slice(0, 5).join("、"))}</small>
      ` : ""}
      ${summary.citation_status ? `
        <small>引用状态：${escapeHtml(summary.citation_status)}</small>
      ` : ""}
    </div>
  `;
}

function renderSecondaryDifferentialReview(review = {}) {
  if (!review || !Object.keys(review).length) {
    return "";
  }
  const expected = Array.isArray(review.expected_evidence_to_check)
    ? review.expected_evidence_to_check
    : [];
  const weakSupport = Array.isArray(review.weak_supporting_evidence)
    ? review.weak_supporting_evidence
    : [];
  return `
    <div class="secondary-differential-review">
      <strong>备用复查判断</strong>
      <p>${escapeHtml(review.report_sentence || review.review_title || "")}</p>
      ${review.current_observation_summary ? `
        <small>当前图像观察：${escapeHtml(review.current_observation_summary)}</small>
      ` : ""}
      ${expected.length ? `
        <small>需要复查的证据：${escapeHtml(expected.join("、"))}</small>
      ` : ""}
      ${weakSupport.length ? `
        <small>弱提示：${escapeHtml(weakSupport.join("、"))}</small>
      ` : ""}
    </div>
  `;
}

function renderSecondaryKnowledgeBuilderProgress(item = {}) {
  const progress = Array.isArray(item.knowledge_builder_progress) ? item.knowledge_builder_progress : [];
  const selectedForKnowledgeBuilder = item.candidate_status === "selected_for_knowledgebuilder"
    || item.knowledge_builder_status === "proposal_prepared";
  if (!progress.length && !selectedForKnowledgeBuilder) {
    return "";
  }
  const steps = progress.length ? progress : [
    {
      step: "prepare_knowledge_proposal",
      label: "KnowledgeBuilder proposal 已生成并进入审核库",
      status: "done",
    },
  ];
  return `
    <div class="knowledgebuilder-progress">
      <strong>KnowledgeBuilder 备用 Knowledge 进度</strong>
      ${selectedForKnowledgeBuilder ? `<span>未审核</span>` : ""}
      <ol>
        ${steps.map((step) => `
          <li>
            <b>${escapeHtml(step.label || step.step || "KnowledgeBuilder step")}</b>
            <em>${escapeHtml(step.status || "")}</em>
          </li>
        `).join("")}
      </ol>
    </div>
  `;
}

function renderEvidenceProtocolReport(payload) {
  const report = payload.report || {};
  const integrated = report.integrated_reasoning_summary || {};
  const hypotheses = report.clinical_hypotheses_assessment || {};
  const imaging = report.imaging_evidence_summary || {};
  const quantitative = report.quantitative_evidence_summary || {};
  const clinical = report.clinical_context_assessment || {};
  const missingEvidence = Array.isArray(report.missing_evidence) ? report.missing_evidence : [];
  const modalityLimitations = Array.isArray(report.modality_limitations)
    ? report.modality_limitations
    : [];
  const recommendations = Array.isArray(report.recommendation) ? report.recommendation : [];

  const hasStructuredEvidence = Boolean(
    Object.keys(integrated).length
    || Object.keys(hypotheses).length
    || Object.keys(imaging).length
    || Object.keys(quantitative).length
    || Object.keys(clinical).length
    || missingEvidence.length
    || modalityLimitations.length
    || recommendations.length
  );
  if (!hasStructuredEvidence) {
    return "";
  }

  const usableItems = Array.isArray(imaging.usable_items) ? imaging.usable_items : [];
  const nonspecificItems = Array.isArray(imaging.nonspecific_items)
    ? imaging.nonspecific_items
    : [];
  const missingItems = Array.isArray(imaging.missing_items) ? imaging.missing_items : [];
  const measurementItems = Array.isArray(quantitative.measurement_items)
    ? quantitative.measurement_items
    : [];
  const exploratoryFeatures = Array.isArray(quantitative.exploratory_features)
    ? quantitative.exploratory_features
    : [];

  return `
    ${renderIntegratedReasoningSummary(integrated)}
    ${renderClinicalHypothesesAssessment(hypotheses)}
    <div class="report-section evidence-protocol-report">
      <h3>影像证据</h3>
      ${usableItems.length ? `<h4>可参考发现</h4>${renderEvidenceProtocolItemList(usableItems, "usable")}` : ""}
      ${nonspecificItems.length ? `<h4>仅作提示</h4>${renderEvidenceProtocolItemList(nonspecificItems, "limited")}` : ""}
      ${!usableItems.length && !nonspecificItems.length ? "<p>当前没有可直接采用的影像证据。</p>" : ""}
    </div>
    <div class="report-section evidence-protocol-report">
      <h3>量化证据</h3>
      <p>${escapeHtml(quantitativeEvidencePatientSummary(quantitative))}</p>
      ${measurementItems.length ? `<h4>可查看测量</h4>${renderEvidenceProtocolItemList(measurementItems, "measurement")}` : ""}
      ${exploratoryFeatures.length ? `<h4>仅作提示</h4>${renderEvidenceProtocolItemList(exploratoryFeatures, "limited")}` : ""}
      ${!measurementItems.length && !exploratoryFeatures.length ? "<p>当前没有稳定的量化证据。</p>" : ""}
    </div>
    <div class="report-section evidence-protocol-report">
      <h3>临床风险因素</h3>
      ${renderClinicalContextAssessment(clinical)}
    </div>
    <div class="report-section evidence-protocol-report">
      <h3>缺失证据</h3>
      ${missingItems.length ? renderEvidenceProtocolItemList(missingItems, "missing") : ""}
      ${missingEvidence.length ? renderList(missingEvidence) : ""}
      ${modalityLimitations.length ? `<h4>影像局限</h4>${renderList(modalityLimitations)}` : ""}
      ${!missingItems.length && !missingEvidence.length && !modalityLimitations.length ? "<p>当前未报告额外缺失证据。</p>" : ""}
    </div>
    <div class="report-section evidence-protocol-report">
      <h3>建议下一步</h3>
      ${recommendations.length ? renderList(recommendations) : "<p>暂无下一步建议。</p>"}
    </div>
  `;
}

function renderIntegratedReasoningSummary(summary) {
  if (!summary || !Object.keys(summary).length) {
    return "";
  }
  const imaging = summary.imaging_support || {};
  const quantitative = summary.quantitative_support || {};
  const missing = summary.missing_evidence || {};
  const clinical = summary.clinical_risk_support || {};
  const recommendations = Array.isArray(summary.recommended_next_step)
    ? summary.recommended_next_step
    : [];
  const supportedTargets = Array.isArray(imaging.supported_targets)
    ? imaging.supported_targets
    : [];
  const missingTargets = Array.isArray(missing.missing_required_targets)
    ? missing.missing_required_targets
    : [];
  const exploratoryTargets = Array.isArray(quantitative.exploratory_targets)
    ? quantitative.exploratory_targets
    : [];
  const riskFactors = Array.isArray(clinical.provided_risk_factors)
    ? clinical.provided_risk_factors
    : [];
  const conclusion = summary.can_confirm_target_disease === true
    ? "当前证据支持目标疾病，但仍需医生结合完整检查确认。"
    : "当前证据不能确认目标疾病。";
  return `
    <div class="report-section evidence-protocol-report">
      <h3>综合推理</h3>
      <p><strong>${escapeHtml(conclusion)}</strong></p>
      <ul>
        <li>证据状态：${escapeHtml(routingEvidenceStatusLabel(summary.evidence_status || ""))}</li>
        <li>影像支持：${supportedTargets.length ? escapeHtml(supportedTargets.map(humanFindingName).join("、")) : "暂无可直接采用的支持证据"}</li>
        <li>量化支持：${escapeHtml(quantitativeEvidencePatientSummary({
          strong_quantitative_support_count: quantitative.strong_quantitative_support_count,
        }))}</li>
        <li>探索性提示：${exploratoryTargets.length ? escapeHtml(exploratoryTargets.map(humanFindingName).join("、")) : "无稳定可用的探索性量化提示"}</li>
        <li>临床风险：${riskFactors.length ? escapeHtml(riskFactors.join("、")) : "未提供可确认风险因素"}</li>
        <li>缺失证据：${missingTargets.length ? escapeHtml(missingTargets.map(humanFindingName).join("、")) : "未报告关键缺失证据"}</li>
      </ul>
      ${recommendations.length ? `<h4>下一步</h4>${renderList(recommendations.slice(0, 3))}` : ""}
    </div>
  `;
}

function renderClinicalHypothesesAssessment(assessment) {
  if (!assessment || !Object.keys(assessment).length) {
    return "";
  }
  const primary = assessment.primary_hypothesis || {};
  const retained = Array.isArray(assessment.differential_retained)
    ? assessment.differential_retained
    : [];
  return `
    <div class="report-section evidence-protocol-report">
      <h3>主假设评估</h3>
      ${primary.disease_key ? `
        <p>
          当前优先检查：<strong>${escapeHtml(humanDiseaseName(primary.disease_key))}</strong>
          ${primary.status ? `（${escapeHtml(routingEvidenceStatusLabel(primary.status))}）` : ""}
        </p>
      ` : "<p>当前没有明确主假设。</p>"}
      ${retained.length ? `
        <h4>鉴别保留</h4>
        <ul>
          ${retained.map((item) => `
            <li>
              <strong>${escapeHtml(humanDiseaseName(item.disease_key || item.condition || ""))}</strong>
              ${item.reason ? `<span>${escapeHtml(item.reason)}</span>` : ""}
            </li>
          `).join("")}
        </ul>
      ` : ""}
      <p class="muted">${assessment.hypotheses_are_diagnosis === false
        ? "这些候选假设不是诊断证据；最终判断必须来自 evidence bundle 和指南约束。"
        : "候选假设只用于解释分析路径，不能替代诊断证据。"
      }</p>
    </div>
  `;
}

function uniquePatientFindingNames(targets) {
  return Array.from(new Set(
    targets.map(humanFindingName).filter(Boolean)
  )).slice(0, 3);
}

function patientMissingEvidenceName(target) {
  const labels = {
    measurement_grade_mask: "可用于测量分级的病灶分割结果",
    segmentation_display: "可展示的分割对照图",
    roi_contour: "可靠的解剖轮廓",
    landmark_quality: "可靠的关键点定位",
    mri_required: "MRI 等进一步影像检查",
    clinical_context: "关键病史信息",
  };
  return labels[target] || humanFindingName(target) || "必要证据";
}

function humanFindingName(target) {
  const labels = {
    sclerotic_band: "硬化带",
    cystic_change: "囊性变",
    trabecular_blurring: "骨小梁模糊",
    collapse: "股骨头塌陷",
    crescent_sign: "新月征/软骨下骨折",
    subchondral_fracture: "新月征/软骨下骨折",
    early_osteonecrosis: "早期股骨头坏死",
    insufficient_visual_input: "影像输入不足",
    image_review_limitation: "影像查看受限",
    real_vlm_validation: "VLM 候选验证未返回可用结果",
  };
  return labels[target] || target || "";
}

const VISUAL_SYSTEM_FINDING_LABELS = {
  insufficient_visual_input: {
    label: "影像输入不足",
    description: "当前没有可直接读取的 X 光图像像素内容，系统不能可靠提取股骨头坏死相关视觉征象。请确认已上传可读图像，或等待 VLM/API 返回候选标注。",
  },
  image_review_limitation: {
    label: "影像查看受限",
    description: "当前影像只能作为候选观察提示，不能单独作为诊断依据。",
  },
  real_vlm_validation: {
    label: "VLM 候选验证未返回可用结果",
    description: "VLM 没有返回可用于复核的候选征象，需要重新上传可读影像或由医生人工复核。",
  },
};

function normalizedVisualFindingKey(finding = {}) {
  return String(
    finding.target
    || finding.finding_id
    || finding.code
    || finding.name
    || finding.display_name
    || ""
  );
}

function visualFindingDisplayName(finding = {}) {
  const key = normalizedVisualFindingKey(finding);
  const configured = VISUAL_SYSTEM_FINDING_LABELS[key];
  if (configured?.label) {
    return configured.label;
  }
  const displayName = finding.display_name || humanFindingName(key);
  return displayName || "候选影像发现";
}

function visualFindingRawTextIsChinese(text) {
  return /[\u3400-\u9fff]/.test(String(text || ""));
}

function visualFindingReadableText(finding = {}) {
  const key = normalizedVisualFindingKey(finding);
  const configured = VISUAL_SYSTEM_FINDING_LABELS[key];
  const rawText = finding.evidence_text
    || finding.evidence_basis
    || finding.description
    || finding.reason
    || "";
  if (configured?.description && !visualFindingRawTextIsChinese(rawText)) {
    return configured.description;
  }
  return rawText || configured?.description || "";
}

function quantitativeEvidencePatientSummary(quantitative) {
  const supportCount = Number(quantitative.strong_quantitative_support_count || 0);
  if (supportCount > 0) {
    return `有 ${supportCount} 项测量可作为诊断参考。`;
  }
  return "当前量化结果不能确认疾病，只能辅助理解影像表现。";
}

function renderEvidenceProtocolItemList(items, role = "neutral") {
  const visible = Array.isArray(items) ? items.filter(Boolean).slice(0, 8) : [];
  if (!visible.length) {
    return '<div class="trace-empty">无</div>';
  }
  return `
    <ul>
      ${visible.map((item) => `
        <li>
          <strong>${escapeHtml(evidenceProtocolItemTitle(item))}</strong>
          <span>${escapeHtml(evidenceProtocolItemSummary(item, role))}</span>
        </li>
      `).join("")}
    </ul>
  `;
}

function evidenceProtocolItemTitle(item) {
  const title = item.display_name
    || item.target
    || item.evidence_type
    || item.finding_id
    || "证据项";
  const view = evidenceViewHintLabel(item.view_hint);
  if (!view || String(title).startsWith(`${view}：`)) {
    return title;
  }
  return `${view}：${title}`;
}

function evidenceViewHintLabel(viewHint) {
  if (!viewHint || viewHint === "unknown") {
    return "";
  }
  return imageViewLabel(viewHint);
}

function evidenceProtocolItemSummary(item, role = "neutral") {
  const observation = item.visual_observation || {};
  const limitations = Array.isArray(item.limitations) ? item.limitations : [];
  const statusText = evidenceProtocolRoleLabel(item, role);
  const parts = [
    observation.description || observation.reason || item.evidence_text || item.description,
    statusText,
    limitations.length ? limitations[0] : "",
  ].filter(Boolean);
  return parts.join("；") || "-";
}

function evidenceProtocolRoleLabel(item, role) {
  if (role === "usable") {
    return "可作为诊断参考，但仍需医生结合完整检查判断";
  }
  if (role === "measurement") {
    return item.diagnosis_usable === true
      ? "测量可参考"
      : "测量质量不足，不能确认";
  }
  if (role === "missing") {
    return "缺少这部分证据，不能确认或排除";
  }
  if (role === "limited" || item.diagnosis_usable === false) {
    return "仅作提示，不能确认";
  }
  return "";
}

function renderClinicalContextAssessment(clinical) {
  if (!clinical || !Object.keys(clinical).length) {
    return "<p>用户未提供明确临床风险因素；不能编造病史。</p>";
  }
  const riskFactors = Array.isArray(clinical.provided_risk_factors)
    ? clinical.provided_risk_factors
    : [];
  const missingContext = Array.isArray(clinical.missing_clinical_context)
    ? clinical.missing_clinical_context
    : [];
  return `
    ${riskFactors.length ? `<h4>已提供</h4>${renderList(riskFactors)}` : "<p>未提供可确认的风险因素。</p>"}
    ${missingContext.length ? `<h4>未提供</h4>${renderList(missingContext)}` : ""}
    ${clinical.role ? `<p>${escapeHtml(clinical.role)}</p>` : ""}
  `;
}

function renderDifferentialConsiderations(payload) {
  const report = payload.report || {};
  const considerations = Array.isArray(report.differential_considerations)
    ? report.differential_considerations
    : [];
  const visible = considerations
    .filter((item) => item && (item.display_name || item.condition || item.reason))
    .slice(0, 4);
  if (!visible.length) {
    return "";
  }
  return `
    <div class="report-section differential-considerations">
      <h3>鉴别考虑</h3>
      <ul>
        ${visible.map((item) => `
          <li>
            <strong>${escapeHtml(item.display_name || humanDiseaseName(item.condition) || "替代解释")}</strong>
            ${item.reason ? `<span>${escapeHtml(item.reason)}</span>` : ""}
          </li>
        `).join("")}
      </ul>
    </div>
  `;
}

function routingEvidenceStatusLabel(status) {
  const labels = {
    supported: "有支持证据",
    not_supported: "暂未支持",
    insufficient: "证据不足",
    nonspecific: "非特异发现",
    requires_evidence_acquisition: "需要先采集证据",
    requires_differential_review: "需要鉴别复核",
    legacy_observation: "旧版观察证据",
  };
  return labels[status] || status;
}

function hypothesisRoleLabel(role) {
  const labels = {
    primary: "优先检查",
    differential: "鉴别保留",
  };
  return labels[role] || role || "候选";
}

function knowledgeSelectionModeLabel(mode) {
  const labels = {
    primary_only: "主 Knowledge 单路",
    manual_secondary: "主 Knowledge + 人工备用 Knowledge",
    agent_auto_secondary: "ONFH + 鉴别复查",
  };
  return labels[mode] || mode || "";
}

function humanDiseaseName(value) {
  const labels = {
    femoral_head_necrosis: "股骨头坏死",
    diffuse_glioma_brats: "成人弥漫性胶质瘤",
    idiopathic_pulmonary_fibrosis_hrct: "特发性肺纤维化",
    osteoarthritis_or_degenerative_hip_disease: "骨关节炎或退行性髋关节病变",
    developmental_dysplasia_related_degeneration: "发育性髋臼发育不良相关退变",
    post_traumatic_change: "外伤后改变",
    infection_or_inflammatory_arthritis: "感染或炎症性关节炎",
    tumor_like_lesion: "肿瘤样骨病变",
  };
  return labels[value] || value || "";
}

function renderVisualOutput(payload) {
  const bundleImage = payload.evidence_bundle?.image_evidence || {};
  const visualBundle = getVisualEvidenceBundle(payload);
  const numeric = visualBundle.numeric_evidence || {};
  const outputs = {
    ...(visualBundle.image_outputs || {}),
    ...(bundleImage.image_outputs || {}),
    ...(payload.image_outputs || {}),
  };
  const overlayPath = outputs.overlay_path;
  const originalPath = outputs.original_image_path || bundleImage.image_path || payload.visual_input_contract?.image_path || "-";
  const modality = bundleImage.modality || payload.visual_input_contract?.modality || "-";
  const bodyPart = bundleImage.body_part || payload.visual_input_contract?.body_part || "-";
  const displayState = buildVisualDisplayState(payload, visualBundle);
  const demoSourceSummary = renderDemoSourceSummary({
    demo_source: payload.demo_source,
    qa_source: payload.qa_source,
    case_id: payload.case_id,
  });
  elements.visualMeta.innerHTML = `
    ${demoSourceSummary}
    ${renderPatientVisualSummary({
      visualBundle,
      displayState,
      modality,
      bodyPart,
      findingCount: numeric.finding_count,
    })}
  `;
  const comparisonHtml = renderLesionComparison({
    original_path: originalPath,
    original_preview_path: outputs.original_preview_path,
    mask_path: outputs.mask_path,
    mask_preview_path: outputs.mask_preview_path,
    overlay_path: overlayPath,
    comparison_path: outputs.comparison_path,
  });
  const vlmAnnotationHtml = renderVlmAnnotationPanel({
    annotation_path: outputs.vlm_annotation_path || outputs.localization_overlay_path || outputs.bbox_overlay_path,
    target_overlay_paths: outputs.target_overlay_paths,
    original_path: originalPath,
    visualBundle,
    displayState,
  });
  const segmentationHtml = renderSegmentationPanel({
    comparisonHtml,
    candidateGalleryHtml: displayState.segmentationDisplayAllowed ? renderCandidateLesionGallery(payload) : "",
    displayState,
  });
  const multiViewHtml = renderMultiViewOutputGallery(visualBundle);
  const inputImageHtml = (!multiViewHtml && !vlmAnnotationHtml && !segmentationHtml)
    ? renderInputImageFallbackGallery(payload, visualBundle, originalPath)
    : "";
  if (!multiViewHtml && !vlmAnnotationHtml && !segmentationHtml && !inputImageHtml) {
    elements.lesionFigure.hidden = true;
    elements.lesionFigure.innerHTML = "";
    return;
  }
  elements.lesionFigure.innerHTML = `
    <div class="visual-output-tabs" aria-label="视觉输出模式">
      ${multiViewHtml}
      ${vlmAnnotationHtml}
      ${segmentationHtml}
      ${inputImageHtml}
    </div>
  `;
  elements.lesionFigure.hidden = false;
}

function renderInputImageFallbackGallery(payload, visualBundle = {}, originalPath = "-") {
  const items = buildInputImageFallbackItems(payload, visualBundle, originalPath);
  if (!items.length) {
    return "";
  }
  return `
    <section class="visual-mode-panel visual-mode-input" aria-label="输入图像">
      <div class="visual-mode-head">
        <strong>输入图像</strong>
        <span>等待视觉输出</span>
      </div>
      <div class="target-overlay-grid">
        ${items.map((item) => `
          <button
            class="target-overlay-card"
            type="button"
            data-lightbox-src="${escapeHtml(item.url)}"
            data-lightbox-title="${escapeHtml(item.title)}"
            data-lightbox-caption="${escapeHtml(item.caption)}"
            aria-label="放大查看 ${escapeHtml(item.title)}"
          >
            <img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.title)}" />
            <div>
              <strong>${escapeHtml(item.title)}</strong>
              <span>${escapeHtml(item.imageId)}</span>
            </div>
            <p>${escapeHtml(item.caption)}</p>
          </button>
        `).join("")}
      </div>
    </section>
  `;
}

function buildInputImageFallbackItems(payload, visualBundle = {}, originalPath = "-") {
  const context = visualBundle.image_context || payload.evidence_bundle?.image_evidence?.image_context || {};
  const series = Array.isArray(context.image_series) ? context.image_series : [];
  const payloadSeries = Array.isArray(payload.patient_info?.image_series) ? payload.patient_info.image_series : [];
  const payloadImagePaths = Array.isArray(payload.image_paths)
    ? payload.image_paths
    : (payload.image_path ? [payload.image_path] : []);
  const rawItems = series.length
    ? series
    : payloadSeries.length
      ? payloadSeries
      : payloadImagePaths.length
        ? payloadImagePaths.map((path, index) => ({
          image_id: `image_${String(index + 1).padStart(3, "0")}`,
          image_path: path,
          view_hint: inferViewHint(path, state.uploadedImageNames[index] || ""),
        }))
        : (originalPath && originalPath !== "-" ? [{
          image_id: "image_001",
          image_path: originalPath,
          view_hint: inferViewHint(originalPath, ""),
        }] : []);
  const seen = new Set();
  return rawItems
    .map((item, index) => {
      const imagePath = typeof item === "string" ? item : item.image_path;
      const url = outputImageUrl(imagePath);
      const imageId = typeof item === "string"
        ? `image_${String(index + 1).padStart(3, "0")}`
        : item.image_id || `image_${String(index + 1).padStart(3, "0")}`;
      const viewHint = typeof item === "string"
        ? inferViewHint(item, state.uploadedImageNames[index] || "")
        : item.view_hint || inferViewHint(imagePath, state.uploadedImageNames[index] || "");
      return {
        url,
        imageId,
        title: imageViewLabel(viewHint),
        caption: "输入图像已上传；等待视觉 Agent 返回候选标注或分割结果。",
      };
    })
    .filter((item) => {
      if (!item.url || seen.has(item.url)) {
        return false;
      }
      seen.add(item.url);
      return true;
    });
}

function renderPatientVisualSummary({visualBundle, displayState, modality, bodyPart, findingCount}) {
  const findings = patientVisibleFindings(visualBundle);
  const requiredNextImages = Array.isArray(visualBundle.required_next_images)
    ? visualBundle.required_next_images
    : [];
  const statusText = displayState.segmentationDisplayAllowed
    ? "已生成可用于展示的分割结果"
    : "当前仅展示 VLM 标注，不把 mask 当作诊断依据";
  return `
    <div class="patient-visual-summary" aria-label="患者可见影像摘要">
      <div class="patient-visual-head">
        <strong>患者可见影像摘要</strong>
        <span>${escapeHtml([modality, bodyPart].filter((item) => item && item !== "-").join(" · ") || "影像")}</span>
      </div>
      <div class="patient-visual-status">${escapeHtml(statusText)}</div>
      ${findings.length ? `
        <div class="patient-visual-section">
          <h3>主要影像发现</h3>
          <ul>
            ${findings.map((finding) => `
              <li>
                <strong>${escapeHtml(finding.title)}</strong>
                ${finding.text ? `<span>${escapeHtml(finding.text)}</span>` : ""}
              </li>
            `).join("")}
          </ul>
        </div>
      ` : `
        <div class="patient-visual-section">
          <h3>主要影像发现</h3>
          <p>${Number(findingCount || 0) > 0 ? "候选影像发现未进入诊断采用列表。" : "暂未返回明确的候选影像发现。"}</p>
        </div>
      `}
      ${requiredNextImages.length ? `
        <div class="patient-visual-section">
          <h3>建议补充检查</h3>
          <ul>
            ${requiredNextImages.map((item) => `
              <li>
                <strong>${escapeHtml([item.region, item.modality].filter(Boolean).join(" ") || "补充影像")}</strong>
                ${item.reason ? `<span>${escapeHtml(item.reason)}</span>` : ""}
              </li>
            `).join("")}
          </ul>
        </div>
      ` : ""}
    </div>
  `;
}

function renderDemoSourceSummary(source) {
  const visible = Object.fromEntries(
    Object.entries(source || {}).filter(([, value]) => value !== null && value !== undefined && value !== "")
  );
  if (!Object.keys(visible).length) {
    return "";
  }
  return `
    <div class="trace-subblock">
      <strong>Demo / Artifact Source</strong>
      ${renderMetricGrid(visible)}
    </div>
  `;
}

function patientVisibleFindings(visualBundle) {
  const findings = Array.isArray(visualBundle.findings) ? visualBundle.findings : [];
  return findings
    .map((finding) => ({
      title: visualFindingDisplayName(finding),
      text: visualFindingReadableText(finding),
      diagnosisUsable: finding.diagnosis_usable === true,
    }))
    .filter((finding) => finding.text || finding.title)
    .sort((a, b) => Number(b.diagnosisUsable) - Number(a.diagnosisUsable))
    .slice(0, 5);
}

function buildVisualDisplayState(payload, visualBundle) {
  const evidence = payload.visual_input_contract?.visual_evidence
    || visualBundle.diagnosis_payload?.visual_evidence
    || {};
  const segmentationResults = Array.isArray(visualBundle.segmentation_results)
    ? visualBundle.segmentation_results
    : Array.isArray(evidence.segmentation_results) ? evidence.segmentation_results : [];
  const warningList = [
    ...(Array.isArray(visualBundle.quality_warnings) ? visualBundle.quality_warnings : []),
    ...(Array.isArray(evidence.quality_warnings) ? evidence.quality_warnings : []),
  ];
  const hasFakeSegmentation = segmentationResults.some((result) => {
    const source = result.selected_tool?.segmentation_source || result.segmentation_source || "";
    return String(source).startsWith("fake_");
  });
  const blockingWarning = warningList.find((warning) => {
    const code = warning.code || "";
    return warning.severity === "error"
      || warning.severity === "critical"
      || code === "box_mask_misalignment"
      || code === "overlapping_candidate_masks";
  });
  let segmentationStatus = visualBundle.segmentation_status
    || evidence.segmentation_status
    || "";
  let fallbackMode = visualBundle.fallback_mode || evidence.fallback_mode || "";
  let reason = visualBundle.segmentation_status_reason
    || evidence.segmentation_status_reason
    || "";
  if (hasFakeSegmentation) {
    segmentationStatus = "failed_qc";
    fallbackMode = "vlm_only";
    reason = reason || "当前分割来自 fake/demo backend，不能作为病灶 mask 展示。";
  } else if (blockingWarning) {
    segmentationStatus = "failed_qc";
    fallbackMode = "vlm_only";
    reason = reason || blockingWarning.message || blockingWarning.reason || blockingWarning.code;
  } else if (!segmentationStatus) {
    segmentationStatus = segmentationResults.some((result) => result.diagnosis_usable)
      ? "candidate_passed_qc"
      : segmentationResults.length ? "failed_qc" : "not_run";
    fallbackMode = segmentationStatus === "candidate_passed_qc" ? "" : "vlm_only";
  }
  const segmentationDisplayAllowed = (
    visualBundle.segmentation_display_allowed === true
    || segmentationStatus === "candidate_passed_qc"
  ) && segmentationStatus !== "failed_qc" && !fallbackMode;
  return {
    visualOutputMode: visualBundle.visual_output_mode
      || evidence.visual_output_mode
      || (segmentationResults.length ? "vlm_plus_segmenter" : "vlm_only"),
    segmentationStatus,
    fallbackMode,
    reason: reason || (segmentationDisplayAllowed
      ? "候选分割通过当前质量门控。"
      : "分割未通过质量检查，已降级为 VLM 标注。"),
    segmentationDisplayAllowed,
  };
}

function renderVlmAnnotationPanel({annotation_path, target_overlay_paths, original_path, visualBundle, displayState}) {
  const annotationUrl = outputImageUrl(annotation_path);
  const originalUrl = outputImageUrl(original_path);
  const previewUrl = annotationUrl || originalUrl;
  const targetGalleryHtml = renderTargetOverlayGallery(target_overlay_paths, visualBundle);
  if (!previewUrl && !targetGalleryHtml) {
    return "";
  }
  return `
    <section class="visual-mode-panel visual-mode-vlm">
      <div class="visual-mode-head">
        <strong>VLM 标注</strong>
        <span>${escapeHtml(displayState.visualOutputMode || "vlm_only")}</span>
      </div>
      ${previewUrl ? `
        <div class="visual-mode-image">
          <img src="${escapeHtml(previewUrl)}" alt="VLM 标注的候选病灶位置总览" />
        </div>
      ` : ""}
      ${targetGalleryHtml}
      <p>显示 VLM/Codex 根据 knowledge 给出的候选位置、框选区域和文字证据；这不是像素级医学分割。</p>
    </section>
  `;
}

const VISUAL_FINDING_LABELS = {
  sclerotic_band: {
    label: "硬化带",
    description: "股骨头内带状或横颈线样密度增高候选区域。",
    color: "#f97316",
    guidance: "看股骨头负重区下方是否有带状、横线样密度增高。",
  },
  cystic_change: {
    label: "囊性变",
    description: "股骨头内局灶透亮、小圆形或不规则囊样候选区域。",
    color: "#2563eb",
    guidance: "看股骨头内是否有小圆形或不规则透亮低密度区。",
  },
  trabecular_blurring: {
    label: "骨小梁模糊",
    description: "股骨头内骨小梁纹理不清或局部骨密度减低候选区域。",
    color: "#7c3aed",
    guidance: "看候选区域内骨小梁纹理是否变淡、变乱或边界不清。",
  },
  collapse: {
    label: "股骨头塌陷",
    description: "股骨头轮廓变扁、塌陷或新月征候选征象。",
    color: "#16a34a",
    guidance: "看股骨头外形边缘是否变扁、不连续或出现塌陷轮廓。",
  },
};

function renderTargetOverlayGallery(targetOverlayPaths, visualBundle = {}) {
  const findingsByTarget = findingMetadataByTarget(visualBundle);
  const items = Array.isArray(targetOverlayPaths)
    ? targetOverlayPaths
      .map((item) => ({
        target: item.target || "candidate_region",
        displayName: targetDisplayName(item, findingsByTarget),
        description: targetDescription(item, findingsByTarget),
        regionCount: item.region_count,
        regions: findingsByTarget[String(item.target || "")]?.regions || [],
        url: outputImageUrl(item.overlay_path),
      }))
      .filter((item) => item.url)
    : [];
  if (!items.length) {
    return "";
  }
  return `
    <div class="target-overlay-gallery" aria-label="按征象单独查看">
      <div class="target-overlay-gallery-head">
        <strong>按征象单独查看</strong>
        <span>${items.length} 类候选征象</span>
      </div>
      <div class="target-overlay-grid">
        ${items.map((item) => `
          <button
            class="target-overlay-card"
            type="button"
            data-lightbox-src="${escapeHtml(item.url)}"
            data-lightbox-title="${escapeHtml(item.displayName)}"
            data-lightbox-caption="${escapeHtml(item.description)}"
            data-lightbox-regions="${escapeHtml(JSON.stringify(item.regions))}"
            aria-label="放大查看 ${escapeHtml(item.displayName)}"
          >
            <img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.displayName)} 单独标注图" />
            <div>
              <strong>${escapeHtml(item.displayName)}</strong>
              <span>${escapeHtml(String(item.regionCount || 1))} 处</span>
            </div>
            <p>${escapeHtml(item.description)}</p>
          </button>
        `).join("")}
      </div>
    </div>
  `;
}

function findingMetadataByTarget(visualBundle = {}) {
  const findings = Array.isArray(visualBundle.findings) ? visualBundle.findings : [];
  return findings.reduce((mapping, finding) => {
    const target = String(finding.target || "");
    if (!target) {
      return mapping;
    }
    const current = mapping[target] || {
      displayName: finding.display_name || finding.target,
      description: "",
      regions: [],
    };
    const description = finding.evidence_text || finding.description || finding.evidence_basis || "";
    mapping[target] = {
      displayName: current.displayName || finding.display_name || finding.target,
      description: current.description || description,
      regions: [
        ...current.regions,
        ...normalizeFindingRegions(finding, current.regions.length),
      ],
    };
    return mapping;
  }, {});
}

function normalizeFindingRegions(finding, offset = 0) {
  const regionSources = Array.isArray(finding.regions) && finding.regions.length
    ? finding.regions
    : [finding.measurements || finding];
  return regionSources
    .map((region, index) => ({
      regionId: region.region_id || finding.region_id || String(offset + index + 1),
      target: finding.target || region.target || "",
      laterality: region.laterality || finding.laterality || "",
      bbox: normalizeBbox(region.bbox || region.measurements?.bbox || finding.bbox || finding.measurements?.bbox),
      areaPx: region.area_px || region.measurements?.area_px || finding.measurements?.area_px,
    }))
    .filter((region) => region.bbox);
}

function normalizeBbox(bbox) {
  if (!Array.isArray(bbox) || bbox.length !== 4) {
    return null;
  }
  const values = bbox.map((value) => Number(value));
  if (values.some((value) => !Number.isFinite(value))) {
    return null;
  }
  const [x1, y1, x2, y2] = values;
  if (x2 <= x1 || y2 <= y1) {
    return null;
  }
  return values;
}

function targetDisplayName(item, findingsByTarget) {
  const target = String(item.target || "");
  const configured = VISUAL_FINDING_LABELS[target];
  const rawName = item.display_name || findingsByTarget[target]?.displayName || target || "候选征象";
  const label = configured?.label || rawName;
  return target && label !== target ? `${label} (${target})` : label;
}

function targetDescription(item, findingsByTarget) {
  const target = String(item.target || "");
  return findingsByTarget[target]?.description
    || VISUAL_FINDING_LABELS[target]?.description
    || item.description
    || "根据当前 knowledge 定位出的候选影像征象，点击可放大查看。";
}

function visualFindingStyle(target) {
  return VISUAL_FINDING_LABELS[String(target || "")] || {
    label: "候选征象",
    color: "#ef4444",
    guidance: "看彩色高亮框内的局部灰度、纹理或轮廓异常。",
  };
}

function renderSegmentationPanel({comparisonHtml, candidateGalleryHtml, displayState}) {
  if (!displayState.segmentationDisplayAllowed) {
    return `
      <section class="visual-mode-panel visual-mode-segmentation visual-mode-disabled">
        <div class="visual-mode-head">
          <strong>分割结果</strong>
          <span>${escapeHtml(taskStatusLabel(displayState.segmentationStatus))}</span>
        </div>
        <div class="segmentation-fallback-box">
          <strong>分割未通过质量检查，已降级为 VLM 标注</strong>
          <p>${escapeHtml(displayState.reason)}</p>
        </div>
      </section>
    `;
  }
  if (!comparisonHtml && !candidateGalleryHtml) {
    return "";
  }
  return `
    <section class="visual-mode-panel visual-mode-segmentation">
      <div class="visual-mode-head">
        <strong>分割结果</strong>
        <span>${escapeHtml(taskStatusLabel(displayState.segmentationStatus))}</span>
      </div>
      ${comparisonHtml}
      ${candidateGalleryHtml}
    </section>
  `;
}

function renderLesionComparison(paths) {
  const items = buildVisualComparisonItems(paths);
  if (!items.some((item) => item.url)) {
    return "";
  }
  return `
    <div class="lesion-comparison" aria-label="视觉 Agent 病灶图对比">
      ${items.map((item) => `
        <div class="lesion-comparison-item">
          <strong>${escapeHtml(item.label)}</strong>
          ${item.url
            ? `<img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.alt)}" />`
            : '<div class="lesion-comparison-empty">未生成可预览图</div>'}
        </div>
      `).join("")}
    </div>
    <figcaption>仅在分割通过质量检查时展示 mask、overlay 与数值结果</figcaption>
  `;
}

function buildVisualComparisonItems(paths) {
  return [
    {
      label: "原图+分割对照",
      alt: "原图与视觉 Agent 分割结果的并排对照图",
      url: outputImageUrl(paths.comparison_path),
    },
    {
      label: "原图",
      alt: "原始医疗图像",
      url: outputImageUrl(paths.original_preview_path || paths.original_path),
    },
    {
      label: "分割候选 mask",
      alt: "视觉 Agent 生成并通过质量检查的候选 mask",
      url: outputImageUrl(paths.mask_preview_path || paths.mask_path),
    },
    {
      label: "对比叠加",
      alt: "原图叠加病灶轮廓的对比结果",
      url: outputImageUrl(paths.overlay_path),
    },
  ];
}

function renderMultiViewOutputGallery(visualBundle = {}) {
  const items = buildMultiViewOutputItems(visualBundle);
  if (!items.length) {
    return "";
  }
  return `
    <section class="visual-mode-panel visual-mode-multiview" aria-label="多体位视觉结果">
      <div class="visual-mode-head">
        <strong>多体位视觉结果</strong>
        <span>按体位查看</span>
      </div>
      <div class="target-overlay-grid">
        ${items.map((item) => `
          <button
            class="target-overlay-card"
            type="button"
            data-lightbox-src="${escapeHtml(item.url)}"
            data-lightbox-title="${escapeHtml(item.title)}"
            data-lightbox-caption="${escapeHtml(item.caption)}"
            data-lightbox-regions="${escapeHtml(JSON.stringify(item.regions))}"
            data-view-hint="${escapeHtml(item.viewHint)}"
            aria-label="放大查看 ${escapeHtml(item.title)}"
          >
            <img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.title)}" />
            <div>
              <strong>${escapeHtml(item.title)}</strong>
              <span>${escapeHtml(item.imageId)}</span>
            </div>
            <p>${escapeHtml(item.caption)}</p>
          </button>
        `).join("")}
      </div>
    </section>
  `;
}

function buildMultiViewOutputItems(visualBundle = {}) {
  const results = Array.isArray(visualBundle.per_image_results)
    ? visualBundle.per_image_results
    : Array.isArray(visualBundle.image_outputs?.per_image_outputs)
      ? visualBundle.image_outputs.per_image_outputs
      : [];
  const findings = Array.isArray(visualBundle.findings) ? visualBundle.findings : [];
  return results
    .map((result, index) => {
      const imageOutputs = result.image_outputs || result;
      const url = outputImageUrl(imageOutputs.comparison_path)
        || outputImageUrl(imageOutputs.vlm_annotation_path)
        || outputImageUrl(imageOutputs.localization_overlay_path)
        || outputImageUrl(imageOutputs.bbox_overlay_path)
        || outputImageUrl(imageOutputs.overlay_path)
        || outputImageUrl(imageOutputs.original_preview_path)
        || outputImageUrl(imageOutputs.original_image_path || result.image_path);
      const imageId = result.image_id || `image_${index + 1}`;
      const viewHint = result.view_hint || "unknown";
      const viewFindings = findings.filter((finding) => finding.image_id === imageId);
      const findingNames = viewFindings
        .map((finding) => finding.display_name || finding.target)
        .filter(Boolean);
      return {
        url,
        imageId,
        viewHint,
        title: imageViewLabel(viewHint),
        caption: findingNames.length
          ? `候选征象：${findingNames.join("、")}`
          : "该体位的视觉候选结果。",
        regions: viewFindings.flatMap((finding, regionOffset) => normalizeFindingRegions(finding, regionOffset)),
      };
    })
    .filter((item) => item.url);
}

function renderCandidateLesionGallery(payload) {
  const candidates = buildCandidateLesionItems(payload);
  if (!candidates.length) {
    return "";
  }
  return `
    <div class="candidate-lesion-gallery" aria-label="候选病灶证据图库">
      <div class="candidate-lesion-gallery-head">
        <strong>候选病灶证据</strong>
        <span>按诊断采用状态区分</span>
      </div>
      <div class="candidate-lesion-grid">
        ${candidates.map((candidate) => `
          <article class="candidate-lesion-card candidate-lesion-${escapeClassName(candidate.usageKind)}">
            <div class="candidate-lesion-image">
              ${candidate.previewUrl
                ? `<img src="${escapeHtml(candidate.previewUrl)}" alt="${escapeHtml(candidate.alt)}" />`
                : '<div class="lesion-comparison-empty">未生成可预览图</div>'}
            </div>
            <div class="candidate-lesion-body">
              <div class="candidate-lesion-title">
                <strong>${escapeHtml(candidate.title)}</strong>
                <span>${escapeHtml(candidate.usageLabel)}</span>
              </div>
              <p>${escapeHtml(candidate.reason)}</p>
              ${renderMetricGrid({
                finding_id: candidate.findingId,
                laterality: candidate.laterality,
                status: candidate.status,
                area_px: candidate.areaPx,
                area_ratio_in_image: candidate.areaRatioInImage,
                area_ratio_in_anatomy: candidate.areaRatioInAnatomy,
                alignment_status: candidate.alignmentStatus,
              })}
            </div>
          </article>
        `).join("")}
      </div>
    </div>
  `;
}

function buildCandidateLesionItems(payload) {
  const galleryItems = getLesionGalleryItems(payload);
  if (galleryItems.length) {
    return galleryItems.map((item, index) => {
      const usage = item.usage || {};
      const imagePaths = item.image_paths || {};
      const measurements = item.measurements || {};
      const quality = item.quality || {};
      const previewUrl = outputImageUrl(imagePaths.comparison_path)
        || outputImageUrl(imagePaths.overlay_path)
        || outputImageUrl(imagePaths.mask_path);
      const usageKind = usage.status || "candidate";
      const baseTitle = item.display_name || item.target || "候选病灶";
      return {
        findingId: item.finding_id || `finding_${index + 1}`,
        title: candidateTitleWithView(baseTitle, item.view_label, item.view_hint),
        alt: `${baseTitle}分割对照图`,
        previewUrl,
        usageKind,
        usageLabel: visualFactUsageLabel(usageKind),
        reason: usage.reason || "候选视觉证据，需结合 evidence bundle 和诊断审计解释。",
        laterality: item.laterality || measurements.laterality,
        status: item.status,
        areaPx: measurements.area_px,
        areaRatioInImage: measurements.area_ratio_in_image,
        areaRatioInAnatomy: measurements.area_ratio_in_anatomy,
        alignmentStatus: quality.alignment_status,
      };
    }).filter((candidate) => candidate.previewUrl || candidate.findingId);
  }
  const visualBundle = getVisualEvidenceBundle(payload);
  const findings = Array.isArray(visualBundle.findings) ? visualBundle.findings : [];
  const usageMap = buildVisualFactUsageMap(payload);
  return findings.flatMap((finding, findingIndex) => {
    const regions = Array.isArray(finding.regions) && finding.regions.length
      ? finding.regions
      : [finding.measurements || {}];
    return regions.map((region, regionIndex) => {
      const usage = usageMap.get(finding.finding_id) || {};
      const measurements = region.measurements || finding.measurements || {};
      const comparisonPath = region.comparison_path || finding.comparison_path || measurements.comparison_path;
      const overlayPath = region.overlay_path || finding.overlay_path || measurements.overlay_path;
      const maskPath = region.mask_path || finding.mask_path || measurements.mask_path;
      const previewUrl = outputImageUrl(comparisonPath) || outputImageUrl(overlayPath) || outputImageUrl(maskPath);
      const usageKind = usage.kind || "candidate";
      const baseTitle = `${finding.display_name || finding.target || "候选病灶"}${regions.length > 1 ? ` #${regionIndex + 1}` : ""}`;
      return {
        findingId: finding.finding_id || `finding_${findingIndex + 1}`,
        title: candidateTitleWithView(
          baseTitle,
          region.view_label || finding.view_label || usage.view_label,
          region.view_hint || finding.view_hint || usage.view_hint,
        ),
        alt: `${finding.display_name || finding.target || "候选病灶"}分割对照图`,
        previewUrl,
        usageKind,
        usageLabel: visualFactUsageLabel(usageKind),
        reason: usage.reason || finding.evidence_text || finding.description || "候选视觉证据，需结合 evidence bundle 和诊断审计解释。",
        laterality: region.laterality || measurements.laterality || usage.laterality,
        status: finding.status || usage.status,
        areaPx: region.area_px ?? measurements.area_px ?? usage.area_px,
        areaRatioInImage: region.area_ratio_in_image ?? measurements.area_ratio_in_image ?? usage.area_ratio_in_image,
        areaRatioInAnatomy: region.area_ratio_in_anatomy ?? measurements.area_ratio_in_anatomy ?? usage.area_ratio_in_anatomy,
        alignmentStatus: measurements.box_mask_alignment?.status || usage.alignment_status,
      };
    });
  }).filter((candidate) => candidate.previewUrl || candidate.findingId);
}

function candidateTitleWithView(title, viewLabel, viewHint) {
  const view = viewLabel || evidenceViewHintLabel(viewHint);
  if (!view || String(title).startsWith(`${view}：`)) {
    return title;
  }
  return `${view}：${title}`;
}

function getLesionGalleryItems(payload) {
  const topLevelItems = payload.lesion_gallery?.items;
  if (Array.isArray(topLevelItems)) {
    return topLevelItems;
  }
  const bundleItems = payload.evidence_bundle?.lesion_gallery?.items;
  if (Array.isArray(bundleItems)) {
    return bundleItems;
  }
  return [];
}

function buildVisualFactUsageMap(payload) {
  const usage = getVisualFactUsage(payload);
  const map = new Map();
  const used = Array.isArray(usage.used) ? usage.used : [];
  const excluded = Array.isArray(usage.excluded) ? usage.excluded : [];
  used.forEach((fact) => {
    if (fact.finding_id) {
      map.set(fact.finding_id, {
        ...fact,
        kind: "used",
        reason: fact.summary_text || "诊断 Agent 已采用该视觉证据。",
      });
    }
  });
  excluded.forEach((fact) => {
    if (fact.finding_id) {
      map.set(fact.finding_id, {
        ...fact,
        kind: "excluded",
        reason: fact.exclusion_reason || fact.summary_text || "诊断 Agent 未采用该视觉证据。",
      });
    }
  });
  return map;
}

function visualFactUsageLabel(kind) {
  if (kind === "used") {
    return "诊断采用";
  }
  if (kind === "excluded") {
    return "排除";
  }
  return "候选";
}

function outputImageUrl(path) {
  if (typeof path !== "string" || !path.startsWith("output/")) {
    return "";
  }
  if (!/\.(png|jpg|jpeg|webp|gif)$/i.test(path)) {
    return "";
  }
  return `/${path}`;
}

function imageViewLabel(viewHint) {
  const labels = {
    ap_pelvis: "骨盆正位/AP",
    frog_lateral: "蛙式侧位",
    lateral: "髋关节侧位/Lateral",
    unknown: "未知体位",
  };
  return labels[viewHint] || viewHint || "未知体位";
}

function renderImageSeriesContext(bundle) {
  const context = bundle.image_context || {};
  const series = Array.isArray(context.image_series) ? context.image_series : [];
  const coverage = context.view_coverage || {};
  const providedViews = Array.isArray(coverage.provided_views) ? coverage.provided_views : [];
  const missingViews = Array.isArray(coverage.missing_views) ? coverage.missing_views : [];
  const expectedViews = Array.isArray(coverage.expected_views) ? coverage.expected_views : [];
  if (!series.length && !providedViews.length && !expectedViews.length) {
    return "";
  }
  const scopeLabel = coverage.analysis_scope === "multi_view_execution"
    ? "多体位分析"
    : coverage.analysis_scope === "primary_image_only"
      ? "当前仅分析主图"
      : coverage.analysis_scope === "single_image"
        ? "单图分析"
        : coverage.analysis_scope || "影像输入";
  const scopeDescription = coverage.analysis_scope === "multi_view_execution"
    ? "多张同一患者影像已分别进入视觉执行，并在 evidence bundle 中合并为同一次病例证据。"
    : coverage.analysis_scope === "primary_image_only"
      ? "多张同一患者影像会先进入病例上下文，当前视觉执行结果仍以主图为准。"
      : "当前病例按单张影像执行视觉分析。";
  const primaryImage = series.find((item) => item.image_id === context.primary_image_id) || series[0] || {};
  const seriesRows = series.map((item, index) => (
    `${item.image_id || `image_${index + 1}`}: ${imageViewLabel(item.view_hint)}`
  ));
  return `
    <div class="trace-subblock">
      <strong>多体位输入</strong>
      <p class="muted">${escapeHtml(scopeLabel)}；${escapeHtml(scopeDescription)}</p>
      ${renderMetricGrid({
        image_count: series.length || undefined,
        primary_image: primaryImage.image_id || context.primary_image_id,
        primary_view: imageViewLabel(primaryImage.view_hint),
        provided_views: providedViews.map(imageViewLabel).join(", "),
        analyzed_views: (Array.isArray(coverage.analyzed_views) ? coverage.analyzed_views : []).map(imageViewLabel).join(", "),
        expected_views: expectedViews.map(imageViewLabel).join(", "),
        missing_views: missingViews.map(imageViewLabel).join(", ") || "无",
      })}
      ${seriesRows.length ? renderList(seriesRows) : ""}
    </div>
  `;
}

function renderVisualEvidenceBundle(bundle, options = {}) {
  if (!bundle || !Object.keys(bundle).length) {
    return options.compact ? "" : '<div class="trace-empty">暂无多征象视觉证据</div>';
  }
  const findings = Array.isArray(bundle.findings) ? bundle.findings : [];
  const numeric = bundle.numeric_evidence || {};
  const present = Array.isArray(bundle.present_findings) ? bundle.present_findings : [];
  const requiredNextImages = Array.isArray(bundle.required_next_images)
    ? bundle.required_next_images
    : [];
  return `
    <div class="${options.compact ? "visual-finding-summary" : "trace-subblock"}">
      ${options.compact ? "" : "<strong>多征象视觉证据</strong>"}
      ${renderMetricGrid({
        present_findings: present.join(", "),
        needs_next_imaging: bundle.needs_next_imaging,
        required_next_images: requiredNextImages
          .map((item) => `${item.modality || "-"} ${item.region || ""}`.trim())
          .join("; "),
        finding_count: numeric.finding_count,
        region_count: numeric.region_count,
        total_area_px: numeric.total_area_px,
        sum_area_ratio_in_image: numeric.sum_area_ratio_in_image,
        max_area_ratio_in_anatomy: numeric.max_area_ratio_in_anatomy,
      })}
      ${options.compact ? "" : renderImageSeriesContext(bundle)}
      ${renderFindingList(findings)}
    </div>
  `;
}

function renderFindingList(findings) {
  if (!Array.isArray(findings) || !findings.length) {
    return '<div class="trace-empty">暂无 finding</div>';
  }
  return `
    <div class="finding-list">
      ${findings.map((finding) => {
        const measurements = finding.measurements || {};
        const anatomyMatch = measurements.anatomy_match || {};
        const regions = Array.isArray(finding.regions) ? finding.regions : [];
        return `
          <div class="finding-item">
            <strong>${escapeHtml(visualFindingDisplayName(finding))}</strong>
            <span>${escapeHtml(finding.status || "-")}</span>
            ${renderMetricGrid({
              target: finding.target,
              confidence: finding.confidence,
              polygon_points: Array.isArray(finding.polygon) ? finding.polygon.length : undefined,
              evidence_text: finding.evidence_text,
              area_px: measurements.area_px,
              area_ratio_in_image: measurements.area_ratio_in_image,
              area_ratio_in_anatomy: measurements.area_ratio_in_anatomy,
              matched_anatomy: anatomyMatch.anatomy_name || measurements.anatomy_name,
              overlap_anatomy_px: anatomyMatch.overlap_anatomy_px || measurements.overlap_anatomy_px,
              anatomy_selection_rule: anatomyMatch.selection_rule,
              region_count: regions.length,
            })}
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderSegmentationResults(results) {
  if (!Array.isArray(results) || !results.length) {
    return '<div class="trace-empty">暂无分割任务结果</div>';
  }
  return `
    <div class="segmentation-result-list">
      ${results.map((result) => {
        const quality = result.quality || {};
        const selectedTool = result.selected_tool || {};
        const warnings = Array.isArray(quality.warnings) ? quality.warnings.join("; ") : quality.warnings;
        return `
          <article class="segmentation-result-item segmentation-status-${escapeClassName(result.status)}">
            <div class="segmentation-result-head">
              <strong>${escapeHtml(result.task_name || result.target || "-")}</strong>
              <span>${escapeHtml(taskStatusLabel(result.status))}</span>
            </div>
            ${renderMetricGrid({
              target: result.target,
              diagnosis_usable: result.diagnosis_usable ? "诊断可用" : "不用于诊断",
              selected_tool: selectedTool.tool_name,
              quality_level: quality.level,
              quality_score: quality.score,
              mask_path: result.mask_path,
              overlay_path: result.overlay_path,
              warnings,
            })}
            ${renderMetricGrid(result.measurements || {})}
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function renderVisualToolPlan(plan) {
  if (!Array.isArray(plan) || !plan.length) {
    return '<div class="trace-empty">暂无视觉工具计划</div>';
  }
  return `
    <div class="visual-tool-plan-list">
      ${plan.map((item) => {
        const task = item.task || {};
        const selectedTool = item.selected_tool || {};
        const required = Array.isArray(task.required_modalities)
          ? task.required_modalities.join(", ")
          : task.required_modalities;
        return `
          <article class="visual-tool-plan-item">
            <strong>${escapeHtml(task.task_name || item.task_name || task.target || "-")}</strong>
            <span>${escapeHtml(taskStatusLabel(item.status))}</span>
            ${renderMetricGrid({
              target: task.target,
              selected_tool: selectedTool.tool_name,
              tool_role: selectedTool.role,
              required_modalities: required,
              diagnosis_usable_without_qc: item.diagnosis_usable_without_qc,
            })}
            <p>${escapeHtml(item.reason || task.reason || "-")}</p>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function getVisualFactUsage(payload) {
  return payload.report?.visual_fact_usage
    || payload.memory_audit?.visual_fact_usage
    || payload.evidence_bundle?.reasoning_evidence?.visual_fact_usage
    || {};
}

function renderVisualFactUsage(payload) {
  const usage = getVisualFactUsage(payload);
  const used = Array.isArray(usage.used) ? usage.used : [];
  const excluded = Array.isArray(usage.excluded) ? usage.excluded : [];
  if (!used.length && !excluded.length) {
    return '<div class="trace-empty">暂无视觉证据使用审计</div>';
  }
  return `
    ${renderMetricGrid({
      used_count: usage.used_count ?? used.length,
      excluded_count: usage.excluded_count ?? excluded.length,
    })}
    <div class="visual-fact-usage">
      <section>
        <h4>诊断采用证据</h4>
        ${renderVisualFactList(used, "used")}
      </section>
      <section>
        <h4>排除证据</h4>
        ${renderVisualFactList(excluded, "excluded")}
      </section>
    </div>
  `;
}

function renderVisualFactList(facts, kind) {
  if (!Array.isArray(facts) || !facts.length) {
    return '<div class="trace-empty">无</div>';
  }
  return `
    <div class="visual-fact-list">
      ${facts.map((fact) => `
        <article class="visual-fact-item visual-fact-${escapeClassName(kind)}">
          <strong>${escapeHtml(fact.display_name || fact.target || fact.finding_id || "-")}</strong>
          <span>${escapeHtml(fact.laterality || "-")}</span>
          <p>${escapeHtml(fact.summary_text || fact.exclusion_reason || "-")}</p>
          ${renderMetricGrid({
            finding_id: fact.finding_id,
            target: fact.target,
            status: fact.status,
            exclusion_reason: fact.exclusion_reason,
            area_px: fact.area_px,
            area_ratio_in_anatomy: fact.area_ratio_in_anatomy,
            alignment_status: fact.alignment_status,
            independent_evidence: fact.independent_evidence,
          })}
        </article>
      `).join("")}
    </div>
  `;
}

function renderEvidenceBundle(payload) {
  const bundle = payload.evidence_bundle || {};
  if (!Object.keys(bundle).length) {
    elements.evidenceView.innerHTML = '<div class="trace-empty">本次响应未返回 evidence bundle</div>';
    return;
  }
  const image = bundle.image_evidence || {};
  const knowledge = bundle.knowledge_evidence || {};
  const clinicalContext = bundle.clinical_context_evidence || {};
  const differentialReasoning = bundle.differential_reasoning_evidence || {};
  const quantitativeEvidence = bundle.quantitative_evidence || {};
  const integratedReasoning = bundle.integrated_reasoning_evidence || {};
  const visualBundle = getVisualEvidenceBundle(payload);
  const segmentationResults = getSegmentationResults(payload);
  const visualToolPlan = getVisualToolPlan(payload);
  const missing = bundle.missing_or_unassessed?.image_memory || {};
  const warnings = Array.isArray(bundle.quality_warnings) ? bundle.quality_warnings : [];
  elements.evidenceView.innerHTML = `
    <div class="trace-block">
      <h3>多征象视觉证据</h3>
      ${renderVisualEvidenceBundle(visualBundle)}
    </div>
    <div class="trace-block">
      <h3>视觉证据使用审计</h3>
      ${renderVisualFactUsage(payload)}
    </div>
    <div class="trace-block">
      <h3>患者上下文</h3>
      ${renderMetricGrid(bundle.patient_context || {})}
    </div>
    <div class="trace-block">
      <h3>临床上下文证据</h3>
      ${renderClinicalContextEvidence(clinicalContext)}
    </div>
    <div class="trace-block">
      <h3>鉴别推理证据</h3>
      ${renderDifferentialReasoningEvidence(differentialReasoning)}
    </div>
    <div class="trace-block">
      <h3>量化证据审计</h3>
      ${renderQuantitativeEvidence(quantitativeEvidence)}
    </div>
    <div class="trace-block">
      <h3>综合推理审计</h3>
      ${renderIntegratedReasoningEvidence(integratedReasoning)}
    </div>
    <div class="trace-block">
      <h3>视觉测量</h3>
      ${renderMetricGrid(image.measurements || {})}
    </div>
    <div class="trace-block">
      <h3>分割任务结果</h3>
      ${renderSegmentationResults(segmentationResults)}
    </div>
    <div class="trace-block">
      <h3>视觉工具计划</h3>
      ${renderVisualToolPlan(visualToolPlan)}
    </div>
    <div class="trace-block">
      <h3>证据充分性</h3>
      ${renderStatusPills(image.completeness || {})}
    </div>
    <div class="trace-block">
      <h3>缺失/未评估</h3>
      ${renderStatusPills(missing)}
    </div>
    <div class="trace-block">
      <h3>Quality Warnings</h3>
      ${renderList(warnings)}
    </div>
    <div class="trace-block">
      <h3>Knowledge</h3>
      ${renderMetricGrid({
        selected_knowledge: knowledge.selected_knowledge,
        selected_vision_mode: knowledge.selected_vision_mode,
        knowledge_type: knowledge.knowledge_type,
        formal_knowledge_status: knowledge.quality_control?.formal_knowledge_status,
        visual_protocol_status: knowledge.quality_control?.visual_protocol_status,
      })}
    </div>
  `;
}

function renderQuantitativeEvidence(quantitativeEvidence) {
  if (!quantitativeEvidence || !Object.keys(quantitativeEvidence).length) {
    return '<div class="trace-empty">未提取量化证据</div>';
  }
  const measurements = Array.isArray(quantitativeEvidence.measurement_items)
    ? quantitativeEvidence.measurement_items
    : [];
  const exploratory = Array.isArray(quantitativeEvidence.exploratory_features)
    ? quantitativeEvidence.exploratory_features
    : [];
  return renderMetricGrid({
    strong_quantitative_support_count: quantitativeEvidence.strong_quantitative_support_count || 0,
    diagnosis_usable_level: quantitativeEvidence.diagnosis_usable_level || "not_usable_or_exploratory",
    can_confirm_diagnosis: quantitativeEvidence.can_confirm_diagnosis === true,
    measurement_items: measurements.length,
    exploratory_features: exploratory.length,
  });
}

function renderIntegratedReasoningEvidence(integratedReasoning) {
  if (!integratedReasoning || !Object.keys(integratedReasoning).length) {
    return '<div class="trace-empty">未提取综合推理证据</div>';
  }
  return renderMetricGrid({
    target_disease: integratedReasoning.target_disease,
    evidence_status: integratedReasoning.evidence_status,
    diagnosis_usable_level: integratedReasoning.diagnosis_usable_level || "bounded_summary_only",
    can_confirm_target_disease: integratedReasoning.can_confirm_target_disease === true,
    can_create_new_evidence: integratedReasoning.can_create_new_evidence === true,
    supported_targets: Array.isArray(integratedReasoning.supported_targets)
      ? integratedReasoning.supported_targets.join("；")
      : integratedReasoning.supported_targets,
    missing_required_targets: Array.isArray(integratedReasoning.missing_required_targets)
      ? integratedReasoning.missing_required_targets.join("；")
      : integratedReasoning.missing_required_targets,
    measurement_targets_not_usable: Array.isArray(integratedReasoning.measurement_targets_not_usable)
      ? integratedReasoning.measurement_targets_not_usable.join("；")
      : integratedReasoning.measurement_targets_not_usable,
    exploratory_targets: Array.isArray(integratedReasoning.exploratory_targets)
      ? integratedReasoning.exploratory_targets.join("；")
      : integratedReasoning.exploratory_targets,
    recommended_next_step: Array.isArray(integratedReasoning.recommended_next_step)
      ? integratedReasoning.recommended_next_step.slice(0, 2).join("；")
      : integratedReasoning.recommended_next_step,
  });
}

function renderClinicalContextEvidence(clinicalContext) {
  if (!clinicalContext || !Object.keys(clinicalContext).length) {
    return '<div class="trace-empty">未提取临床上下文证据</div>';
  }
  return renderMetricGrid({
    source: clinicalContext.source,
    provided_risk_factors: Array.isArray(clinicalContext.provided_risk_factors)
      ? clinicalContext.provided_risk_factors.join("；")
      : clinicalContext.provided_risk_factors,
    missing_clinical_context: Array.isArray(clinicalContext.missing_clinical_context)
      ? clinicalContext.missing_clinical_context.join("；")
      : clinicalContext.missing_clinical_context,
    diagnosis_usable_level: clinicalContext.diagnosis_usable_level || "risk_modifier_only",
    can_confirm_without_imaging: clinicalContext.can_confirm_without_imaging === true,
  });
}

function renderDifferentialReasoningEvidence(differentialReasoning) {
  if (!differentialReasoning || !Object.keys(differentialReasoning).length) {
    return '<div class="trace-empty">未提取鉴别推理证据</div>';
  }
  const considerations = Array.isArray(differentialReasoning.considerations)
    ? differentialReasoning.considerations
    : [];
  const summary = renderMetricGrid({
    primary_hypothesis: differentialReasoning.primary_hypothesis,
    routing_evidence_status: differentialReasoning.routing_evidence_status,
    diagnosis_usable_level: differentialReasoning.diagnosis_usable_level || "bounded_differential_only",
    can_replace_primary_diagnosis: differentialReasoning.can_replace_primary_diagnosis === true,
  });
  if (!considerations.length) {
    return summary;
  }
  return `
    ${summary}
    <ul>
      ${considerations.slice(0, 5).map((item) => `
        <li>
          <strong>${escapeHtml(item.display_name || humanDiseaseName(item.condition || ""))}</strong>
          <span>${escapeHtml([item.status, item.reason].filter(Boolean).join("；"))}</span>
        </li>
      `).join("")}
    </ul>
  `;
}

function renderMemoryAudit(payload) {
  const audit = payload.memory_audit || {};
  if (!Object.keys(audit).length) {
    elements.auditView.innerHTML = '<div class="trace-empty">本次响应未返回 memory audit</div>';
    return;
  }
  elements.auditView.innerHTML = `
    <div class="trace-block">
      <h3>四类 Memory</h3>
      ${renderMemoryRoleSummary()}
      ${renderStatusPills(audit.memory_completeness || {})}
    </div>
    <div class="trace-block">
      <h3>Memory Details</h3>
      ${renderMemoryTypeDetails(audit.memory_type_details || {})}
    </div>
    <div class="trace-block">
      <h3>Alignment Summary</h3>
      ${renderAlignmentAuditSummary(audit.alignment_summary || {})}
    </div>
    <div class="trace-block">
      <h3>Knowledge Quality</h3>
      ${renderKnowledgeQuality(audit.knowledge_quality || {})}
    </div>
    <div class="trace-block">
      <h3>QA Safety</h3>
      ${renderQaSafety(audit.qa_safety || {})}
    </div>
    <div class="trace-block">
      <h3>Trace Consistency</h3>
      ${renderTraceConsistency(audit.trace_consistency || {})}
    </div>
    <div class="trace-block">
      <h3>Runtime Gateway Trace</h3>
      ${renderRuntimeGatewayTrace(payload.runtime_gateway_trace || {}, payload.runtime_gateway_trace_path)}
    </div>
    <div class="trace-block">
      <h3>Runtime Manifest</h3>
      ${renderRuntimeManifest(payload.runtime_manifest || {}, payload.runtime_manifest_path)}
    </div>
    <div class="trace-block">
      <h3>Stop Hook Gate</h3>
      ${renderStopHookGate(payload.stop_hook_gate || {}, payload.stop_hook_gate_path)}
    </div>
    <div class="trace-block">
      <h3>Self-evolving Queue</h3>
      ${renderSelfEvolvingQueue(payload.self_evolving_queue || {}, payload.self_evolving_queue_path)}
    </div>
    <div class="trace-block">
      <h3>Candidate Validation Gate</h3>
      ${renderCandidateValidationGate(payload.candidate_validation_gate || {}, payload.candidate_validation_gate_path)}
    </div>
    <div class="trace-block">
      <h3>视觉证据使用审计</h3>
      ${renderVisualFactUsage(payload)}
    </div>
    <div class="trace-block">
      <h3>临床证据流水线</h3>
      ${renderAgentFlowSummary(audit)}
    </div>
    <div class="trace-block">
      <h3>Memory Replay</h3>
      ${renderMemoryReplay(payload.memory_replay || {})}
    </div>
    <div class="trace-block">
      <h3>实现节点 Trace</h3>
      ${renderList(audit.agents_traced || [])}
    </div>
    <div class="trace-block">
      <h3>Agent / Layer I/O</h3>
      ${renderMemoryTypeDetails(audit.agent_io_summary || {})}
    </div>
    <div class="trace-block">
      <h3>Missing / Unassessed</h3>
      ${renderStatusPills(audit.missing_or_unassessed?.image_memory || {})}
    </div>
    <div class="trace-block">
      <h3>Guideline Conflicts</h3>
      ${renderGuidelineConflicts({conflicts: audit.guideline_conflicts || []}) || '<div class="trace-empty">无冲突</div>'}
    </div>
    <div class="trace-block">
      <h3>Audit Path</h3>
      <p>${escapeHtml(payload.memory_audit_path || "-")}</p>
    </div>
  `;
}

function renderRuntimeGatewayTrace(trace, runtimeGatewayTracePath) {
  if (!Object.keys(trace).length) {
    return '<div class="trace-empty">暂无 runtime gateway trace</div>';
  }
  const stages = Array.isArray(trace.stages) ? trace.stages : [];
  const safety = trace.safety_invariants || {};
  const consistency = trace.trace_consistency || {};
  return `
    <p class="pipeline-note">Runtime Gateway Trace 汇总底层 gateway 的四段执行轨迹：knowledge 分发、stop hook、自我候选沉淀和正式升级验证门。</p>
    ${renderMetricGrid({
      schema_version: trace.schema_version,
      trace_path: runtimeGatewayTracePath || trace.trace_path,
      promotion_status: trace.promotion_status,
      formal_update_allowed: trace.formal_update_allowed,
      stage_count: stages.length,
    })}
    <div class="trace-subblock">
      <strong>Gateway Stages</strong>
      ${renderList(stages.map((stage) => {
        const name = stage.stage || "-";
        const status = stage.status || "-";
        const path = stage.artifact_path || "-";
        return `${name}: ${status} · ${path}`;
      }))}
    </div>
    <div class="trace-subblock">
      <strong>Trace Consistency</strong>
      ${renderMetricGrid({
        all_stage_artifacts_available: consistency.all_stage_artifacts_available,
        all_stage_schemas_present: consistency.all_stage_schemas_present,
        stage_count: consistency.stage_count,
        missing_artifact_paths: Array.isArray(consistency.missing_artifact_paths) ? consistency.missing_artifact_paths.join(", ") : consistency.missing_artifact_paths,
        missing_schema_stages: Array.isArray(consistency.missing_schema_stages) ? consistency.missing_schema_stages.join(", ") : consistency.missing_schema_stages,
      })}
    </div>
    <div class="trace-subblock">
      <strong>Safety Invariants</strong>
      ${renderMetricGrid({
        formal_knowledge_updated: safety.formal_knowledge_updated,
        formal_guideline_updated: safety.formal_guideline_updated,
        diagnosis_report_updated: safety.diagnosis_report_updated,
        candidate_artifacts_only: safety.candidate_artifacts_only,
      })}
    </div>
  `;
}

function renderCandidateValidationGate(gate, candidateValidationGatePath) {
  if (!Object.keys(gate).length) {
    return '<div class="trace-empty">暂无 candidate validation gate</div>';
  }
  const decision = gate.promotion_decision || {};
  const safety = gate.runtime_safety || {};
  const validations = Array.isArray(gate.item_validations) ? gate.item_validations : [];
  return `
    <p class="pipeline-note">Candidate Validation Gate 是正式升级前的验证门：未通过人工、指南来源或数据集验证时，候选项只能停留在 output/fake。</p>
    ${renderMetricGrid({
      schema_version: gate.schema_version,
      gate_path: candidateValidationGatePath || gate.gate_path,
      source_queue_path: gate.source_queue_path,
      promotion_status: decision.status,
      formal_update_allowed: decision.formal_update_allowed,
      reason: decision.reason,
    })}
    <div class="trace-subblock">
      <strong>Item Validations</strong>
      ${renderList(validations.map((item) => {
        const id = item.item_id || "-";
        const status = item.validation_status || "-";
        const decisionText = item.decision || "-";
        const failed = Array.isArray(item.failed_checks) ? item.failed_checks.join(", ") : "";
        return `${id}: ${status} · ${decisionText}${failed ? ` · failed: ${failed}` : ""}`;
      }))}
    </div>
    <div class="trace-subblock">
      <strong>Review Requirements</strong>
      ${renderList(gate.review_requirements || [])}
    </div>
    <div class="trace-subblock">
      <strong>Runtime Safety</strong>
      ${renderMetricGrid({
        validation_gate_executed: safety.validation_gate_executed,
        read_only: safety.read_only,
        formal_knowledge_updated: safety.formal_knowledge_updated,
        formal_guideline_updated: safety.formal_guideline_updated,
        diagnosis_report_updated: safety.diagnosis_report_updated,
      })}
    </div>
  `;
}

function renderSelfEvolvingQueue(queue, selfEvolvingQueuePath) {
  if (!Object.keys(queue).length) {
    return '<div class="trace-empty">暂无 self-evolving queue</div>';
  }
  const safety = queue.runtime_safety || {};
  const items = Array.isArray(queue.queue_items) ? queue.queue_items : [];
  const policy = queue.review_policy || {};
  return `
    <p class="pipeline-note">Self-evolving Queue 只沉淀候选记忆、候选规则或 candidate knowledge patch；验证前不更新正式医疗 knowledge。</p>
    ${renderMetricGrid({
      schema_version: queue.schema_version,
      status: queue.status,
      queue_path: selfEvolvingQueuePath || queue.queue_path,
      item_count: items.length,
      required_review: policy.required_review,
    })}
    <div class="trace-subblock">
      <strong>Queue Items</strong>
      ${renderList(items.map((item) => {
        const type = item.candidate_type || "-";
        const code = item.source_warning_code || "-";
        const status = item.validation_status || "-";
        const proposal = item.proposal || "";
        return `${type}: ${code} · ${status}${proposal ? ` · ${proposal}` : ""}`;
      }))}
    </div>
    <div class="trace-subblock">
      <strong>Review Policy</strong>
      ${renderMetricGrid({
        promotion_rule: policy.promotion_rule,
        allowed_outputs: Array.isArray(policy.allowed_outputs) ? policy.allowed_outputs.join(", ") : policy.allowed_outputs,
      })}
    </div>
    <div class="trace-subblock">
      <strong>Runtime Safety</strong>
      ${renderMetricGrid({
        queue_written: safety.queue_written,
        candidate_only: safety.candidate_only,
        formal_knowledge_updated: safety.formal_knowledge_updated,
        formal_guideline_updated: safety.formal_guideline_updated,
        diagnosis_report_updated: safety.diagnosis_report_updated,
      })}
    </div>
  `;
}

function renderStopHookGate(gate, stopHookGatePath) {
  if (!Object.keys(gate).length) {
    return '<div class="trace-empty">暂无 stop hook gate</div>';
  }
  const safety = gate.runtime_safety || {};
  const warnings = Array.isArray(gate.runtime_warnings) ? gate.runtime_warnings : [];
  return `
    <p class="pipeline-note">Stop Hook Gate 是只读自检：发现风险并给出 next actions，不自动修改报告或正式 knowledge。</p>
    ${renderMetricGrid({
      schema_version: gate.schema_version,
      gate_path: stopHookGatePath || gate.gate_path,
      source_runtime_manifest_path: gate.source_runtime_manifest_path,
      warning_count: warnings.length,
    })}
    <div class="trace-subblock">
      <strong>Runtime Warnings</strong>
      ${renderList(warnings.map((warning) => {
        const severity = warning.severity || "-";
        const code = warning.code || "-";
        const message = warning.message || "";
        return `${severity}: ${code}${message ? ` · ${message}` : ""}`;
      }))}
    </div>
    <div class="trace-subblock">
      <strong>Next Actions</strong>
      ${renderList(gate.next_actions || [])}
    </div>
    <div class="trace-subblock">
      <strong>Candidate Knowledge Patch</strong>
      ${renderMetricGrid(gate.candidate_knowledge_patch || {})}
    </div>
    <div class="trace-subblock">
      <strong>Runtime Safety</strong>
      ${renderMetricGrid({
        stop_hook_executed: safety.stop_hook_executed,
        read_only: safety.read_only,
        formal_knowledge_updated: safety.formal_knowledge_updated,
        diagnosis_report_updated: safety.diagnosis_report_updated,
        self_evolving_queue_updated: safety.self_evolving_queue_updated,
      })}
    </div>
  `;
}

function renderRuntimeManifest(manifest, runtimeManifestPath) {
  if (!Object.keys(manifest).length) {
    return '<div class="trace-empty">暂无 Evidence Gateway runtime manifest</div>';
  }
  const safety = manifest.runtime_safety || {};
  const blocked = manifest.blocked_or_missing_evidence || {};
  const generated = manifest.generated_artifacts || {};
  return `
    <p class="pipeline-note">Evidence Gateway 记录本轮 knowledge 分发、文件 artifact、工具调用、contract guards 和只读 safety 状态。</p>
    ${renderMetricGrid({
      schema_version: manifest.schema_version,
      selected_knowledge: manifest.selected_knowledge,
      knowledge_version: manifest.knowledge_version,
      knowledge_type: manifest.knowledge_type,
      analysis_status: blocked.analysis_status,
      manifest_path: runtimeManifestPath || manifest.manifest_path,
    })}
    <div class="trace-subblock">
      <strong>Input Artifacts</strong>
      ${renderMetricGrid(manifest.input_artifacts || {})}
    </div>
    <div class="trace-subblock">
      <strong>Generated Artifacts</strong>
      ${renderMetricGrid({
        evidence_bundle_status: generated.evidence_bundle_status,
        memory_audit_path: generated.memory_audit_path,
        case_memory_path: generated.case_memory_path,
        lesion_gallery_summary: generated.lesion_gallery_summary,
      })}
    </div>
    <div class="trace-subblock">
      <strong>Tool Calls</strong>
      ${renderList((manifest.tool_calls || []).map((call) => {
        const stage = call.stage || "-";
        const tool = call.tool || "-";
        const action = call.action ? ` · ${call.action}` : "";
        return `${stage}: ${tool}${action}`;
      }))}
    </div>
    <div class="trace-subblock">
      <strong>Contract Guards</strong>
      ${renderStatusPills(manifest.contracts_checked || {})}
    </div>
    <div class="trace-subblock">
      <strong>Memory Written</strong>
      ${renderStatusPills(manifest.memory_written || {})}
    </div>
    <div class="trace-subblock">
      <strong>Runtime Safety</strong>
      ${renderMetricGrid({
        manifest_only: safety.manifest_only,
        stop_hook_executed: safety.stop_hook_executed,
        formal_knowledge_updated: safety.formal_knowledge_updated,
        self_evolving_action: safety.self_evolving_action,
      })}
    </div>
  `;
}

function renderMemoryRoleSummary() {
  const roles = [
    {
      name: "patient_memory",
      title: "患者输入",
      description: "记录患者主诉、症状、病例入口和追问历史。",
    },
    {
      name: "image_memory",
      title: "图像与视觉证据",
      description: "记录图像模态、病灶图、结构化视觉证据、测量值和证据充分性。",
    },
    {
      name: "knowledge_memory",
      title: "Knowledge / 指南 / 路由",
      description: "记录选择了哪个 knowledge、路由依据、指南来源、质量控制和 alignment plan。",
    },
    {
      name: "reasoning_memory",
      title: "诊断推理与报告",
      description: "记录诊断 Agent 使用/排除的证据、诊断倾向、不确定性和后续建议。",
    },
  ];
  return `
    <div class="memory-role-list">
      ${roles.map((role) => `
        <div class="memory-role-item">
          <strong>${escapeHtml(role.title)}</strong>
          <span>${escapeHtml(role.name)}</span>
          <p>${escapeHtml(role.description)}</p>
        </div>
      `).join("")}
    </div>
  `;
}

function renderAgentFlowSummary(audit) {
  const summary = audit.agent_io_summary || {};
  const stages = [
    {
      agent: "GaoDoctorAgent",
      title: "临床编排 / 入口分诊",
      memory: "patient_memory / knowledge_memory",
      description: "核心 Agent。读取患者描述和图像上下文，决定 intent、目标 knowledge、视觉模式和下游调用顺序。",
      metrics: {
        selected_knowledge: summary.GaoDoctorAgent?.routing_decision?.selected_knowledge,
        selected_vision_mode: summary.GaoDoctorAgent?.routing_decision?.selected_vision_mode,
        knowledge_builder_action: summary.GaoDoctorAgent?.routing_decision?.knowledge_builder_action,
      },
    },
    {
      agent: "KnowledgeBuilderAgent",
      title: "条件 Knowledge 构建 / 加载",
      memory: "knowledge_memory",
      description: "条件组件。有现成 knowledge 时只加载/校验；缺失时才进入指南检索、knowledge 生成和 visual protocol 构建。",
      metrics: {
        input: summary.KnowledgeBuilderAgent?.input,
        output: summary.KnowledgeBuilderAgent?.output,
      },
    },
    {
      agent: "VisionAgent",
      title: "视觉证据提取",
      memory: "image_memory",
      description: "核心 Agent。按 knowledge 视觉协议调用 VLM prompt、MedSAM2 和测量工具，返回病灶图与结构化数值。",
      metrics: {
        tool: summary.VisionAgent?.tool,
        prompt_tool: summary.VisionAgent?.prompt_tool,
        selected_vision_mode: summary.VisionAgent?.selected_vision_mode,
        lesion_gallery_items: summary.VisionAgent?.lesion_gallery_summary?.item_count,
        lesion_gallery_used: summary.VisionAgent?.lesion_gallery_summary?.used_count,
        lesion_gallery_excluded: summary.VisionAgent?.lesion_gallery_summary?.excluded_count,
      },
    },
    {
      agent: "DiagnosisDoctorAgent",
      title: "证据约束诊断推理",
      memory: "reasoning_memory",
      description: "核心 Agent。不看原图，只消费 evidence bundle，区分可用证据、排除证据和缺失证据。",
      metrics: {
        output: summary.DiagnosisDoctorAgent?.output,
        used_count: summary.DiagnosisDoctorAgent?.visual_fact_usage?.used_count,
        excluded_count: summary.DiagnosisDoctorAgent?.visual_fact_usage?.excluded_count,
      },
    },
    {
      agent: "MemoryManager",
      title: "Memory / Audit Layer",
      memory: "patient/image/knowledge/reasoning",
      description: "基础设施层，不作为诊断 Agent。保存四类 memory、agent I/O、evidence bundle 与可回放审计链。",
      metrics: {
        audit_status: summary.MemoryManager?.output?.audit_status,
        evidence_bundle_status: summary.MemoryManager?.output?.evidence_bundle_status,
        lesion_gallery_status: summary.MemoryManager?.output?.lesion_gallery_status,
        lesion_gallery_items: summary.MemoryManager?.output?.lesion_gallery_summary?.item_count,
      },
    },
  ];
  if (summary["GaoDoctorAgent QA"]) {
    stages.push({
      agent: "GaoDoctorAgent QA",
      title: "追问回答",
      memory: "patient_memory.qa_history",
      description: "基于已有 evidence bundle 回答追问，不重新解释缺失证据，也不脱离病例记忆。",
      metrics: {
        question: summary["GaoDoctorAgent QA"]?.input,
        evidence_bundle_used: summary["GaoDoctorAgent QA"]?.output?.evidence_bundle_used,
        llm_used: summary["GaoDoctorAgent QA"]?.output?.llm_used,
        llm_fallback_reason: summary["GaoDoctorAgent QA"]?.output?.llm_fallback_reason,
        qa_source: summary["GaoDoctorAgent QA"]?.output?.qa_source,
      },
    });
  }
  return `
    <p class="pipeline-note">架构按医疗安全边界拆分为 3 个核心 Agent、1 个条件 Knowledge 组件和 1 个 Memory/Audit 基础设施层；下方实现节点 trace 保留内部类名用于审计。</p>
    <div class="agent-flow-list">
      ${stages.map((stage, index) => `
        <article class="agent-flow-item">
          <span>${index + 1}</span>
          <div>
            <strong>${escapeHtml(stage.title)}</strong>
            <em>${escapeHtml(stage.agent)} · ${escapeHtml(stage.memory)}</em>
            <p>${escapeHtml(stage.description)}</p>
            ${renderMetricGrid(stage.metrics)}
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function renderMemoryReplay(replay) {
  const steps = Array.isArray(replay.steps) ? replay.steps : [];
  if (!steps.length) {
    return '<div class="trace-empty">暂无回放步骤</div>';
  }
  const consistency = replay.replay_consistency || {};
  return `
    <div class="trace-subsection">
      <h3>Replay Consistency</h3>
      ${renderMetricGrid({
        required_events_present: consistency.required_events_present,
        memory_scope_complete: consistency.memory_scope_complete,
        qa_extension_present: consistency.qa_extension_present,
        step_count: consistency.step_count,
        missing_required_events: Array.isArray(consistency.missing_required_events)
          ? consistency.missing_required_events.join(", ")
          : consistency.missing_required_events,
        steps_missing_memory_scope: Array.isArray(consistency.steps_missing_memory_scope)
          ? consistency.steps_missing_memory_scope.join(", ")
          : consistency.steps_missing_memory_scope,
      })}
    </div>
    <div class="memory-replay-list">
      ${steps.map((step, index) => `
        <div class="memory-replay-step">
          <span>${index + 1}</span>
          <div>
            <strong>${escapeHtml(step.agent || "-")}</strong>
            <p>${escapeHtml(replayStepLabel(step.event))}</p>
            ${renderMetricGrid(replayStepSummary(step))}
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function replayStepLabel(eventName) {
  const labels = {
    patient_intake: "患者入口",
    knowledge_routing: "Knowledge 路由",
    knowledge_loading: "Knowledge 加载",
    vlm_prompt_generation: "视觉提示生成",
    visual_evidence: "视觉证据",
    diagnosis_report: "诊断推理",
    memory_audit: "记忆审计",
    follow_up_qa: "追问回答",
  };
  return labels[eventName] || eventName || "-";
}

function replayStepSummary(step) {
  if (step.event === "patient_intake") {
    return {
      memory_scope: step.memory_scope,
      intent: step.intent,
      patient_id: step.patient_id,
      symptoms: Array.isArray(step.symptoms) ? step.symptoms.join(", ") : step.symptoms,
    };
  }
  if (step.event === "knowledge_routing") {
    const routingDecision = step.routing_decision || {};
    return {
      memory_scope: step.memory_scope,
      decision_owner: step.decision_owner || routingDecision.agent_scope,
      selected_knowledge: step.selected_knowledge,
      knowledge_type: step.knowledge_type,
      routing_source: routingDecision.source,
      knowledge_builder_action: step.knowledge_builder_action || routingDecision.knowledge_builder_action,
      analysis_status: step.analysis_status,
    };
  }
  if (step.event === "knowledge_loading") {
    return {
      memory_scope: step.memory_scope,
      action: step.action,
      selected_knowledge: step.selected_knowledge,
      knowledge_type: step.knowledge_type,
      evidence_level: step.evidence_level,
      formal_knowledge_status: step.formal_knowledge_status,
      visual_protocol_status: step.visual_protocol_status,
    };
  }
  if (step.event === "vlm_prompt_generation") {
    return {
      memory_scope: step.memory_scope,
      tool: step.tool,
      segmentation_quality: step.segmentation_quality,
      measurements: step.measurements,
    };
  }
  if (step.event === "visual_evidence") {
    return {
      memory_scope: step.memory_scope,
      tool: step.tool,
      selected_vision_mode: step.selected_vision_mode,
      modality: step.modality,
      body_part: step.body_part,
      segmentation_quality: step.segmentation_quality,
      lesion_gallery_summary: step.lesion_gallery_summary,
      measurements: step.measurements,
    };
  }
  if (step.event === "diagnosis_report") {
    return {
      memory_scope: step.memory_scope,
      diagnostic_tendency: step.diagnostic_tendency,
      uncertainty: step.uncertainty,
      visual_fact_usage_summary: step.visual_fact_usage_summary,
      used_visual_targets: Array.isArray(step.used_visual_targets)
        ? step.used_visual_targets.join(", ")
        : step.used_visual_targets,
      excluded_visual_targets: Array.isArray(step.excluded_visual_targets)
        ? step.excluded_visual_targets.join(", ")
        : step.excluded_visual_targets,
    };
  }
  if (step.event === "memory_audit") {
    return {
      memory_scope: step.memory_scope,
      evidence_bundle_status: step.evidence_bundle_status,
      audit_status: step.audit_status,
      lesion_gallery_summary: step.lesion_gallery_summary,
      quality_warnings: step.quality_warnings,
    };
  }
  if (step.event === "follow_up_qa") {
    return {
      memory_scope: step.memory_scope,
      question: step.question,
      evidence_bundle_used: step.evidence_bundle_used,
      qa_evidence_scope: step.qa_evidence_scope,
      visual_fact_usage_summary: step.visual_fact_usage_summary,
      used_visual_targets: Array.isArray(step.used_visual_targets)
        ? step.used_visual_targets.join(", ")
        : step.used_visual_targets,
      excluded_visual_targets: Array.isArray(step.excluded_visual_targets)
        ? step.excluded_visual_targets.join(", ")
        : step.excluded_visual_targets,
      llm_used: step.llm_used,
      llm_fallback_reason: step.llm_fallback_reason,
    };
  }
  return step;
}

function renderMemoryTypeDetails(details) {
  if (!Object.keys(details).length) {
    return '<div class="trace-empty">-</div>';
  }
  return `
    <div class="memory-detail-list">
      ${Object.entries(details).map(([memoryType, summary]) => `
        <div class="memory-detail-item">
          <strong>${escapeHtml(memoryType)}</strong>
          ${renderMetricGrid(summary || {})}
        </div>
      `).join("")}
    </div>
  `;
}

function renderAlignmentAuditSummary(summary) {
  if (!Object.keys(summary).length) {
    return '<div class="trace-empty">-</div>';
  }
  return `
    ${renderMetricGrid({
      analysis_status: summary.analysis_status,
      clinical_focus: summary.clinical_focus,
      visual_task_status_counts: summary.visual_task_status_counts,
    })}
    <div class="trace-subblock">
      <strong>Blocked Scopes</strong>
      ${renderList(summary.blocked_scopes || [])}
    </div>
    <div class="trace-subblock">
      <strong>Required Next Images</strong>
      ${renderNextImageList(summary.required_next_images || [])}
    </div>
  `;
}

function renderKnowledgeQuality(quality) {
  if (!Object.keys(quality).length) {
    return '<div class="trace-empty">-</div>';
  }
  return `
    ${renderMetricGrid({
      formal_knowledge_status: quality.formal_knowledge_status,
      visual_protocol_status: quality.visual_protocol_status,
      citation_status: quality.citation_status,
      conflict_status: quality.conflict_status,
    })}
    <div class="trace-subblock">
      <strong>Visual Protocol Errors</strong>
      ${renderList(quality.visual_protocol_errors || [])}
    </div>
    <div class="trace-subblock">
      <strong>Visual Protocol Warnings</strong>
      ${renderList(quality.visual_protocol_warnings || [])}
    </div>
  `;
}

function renderQaSafety(safety) {
  if (!Object.keys(safety).length) {
    return '<div class="trace-empty">-</div>';
  }
  return `
    ${renderMetricGrid({
      evidence_bundle_required: safety.evidence_bundle_required,
      evidence_bundle_used: safety.evidence_bundle_used,
      evidence_bundle_used_count: safety.evidence_bundle_used_count,
      qa_history_count: safety.qa_history_count,
      llm_used_count: safety.llm_used_count,
      fallback_count: safety.fallback_count,
      missing_or_unassessed_count: safety.missing_or_unassessed_count,
    })}
    <div class="trace-subblock">
      <strong>Blocked Scopes</strong>
      ${renderList(safety.blocked_scopes || [])}
    </div>
  `;
}

function renderTraceConsistency(consistency) {
  if (!Object.keys(consistency).length) {
    return '<div class="trace-empty">-</div>';
  }
  return renderMetricGrid({
    agent_io_matches_trace: consistency.agent_io_matches_trace,
    required_agents_present: consistency.required_agents_present,
    qa_extension_present: consistency.qa_extension_present,
    agent_count: consistency.agent_count,
    agent_io_count: consistency.agent_io_count,
    missing_required_agents: Array.isArray(consistency.missing_required_agents)
      ? consistency.missing_required_agents.join(", ")
      : consistency.missing_required_agents,
  });
}

function renderEvidenceGatewaySnapshot(snapshot) {
  const architecture = snapshot.architecture_model || {};
  const visual = snapshot.phase_b_visual_evidence || {};
  const metrics = visual.key_metrics || {};
  const gate = snapshot.candidate_gate || {};
  const claims = snapshot.claims || {};
  state.lastPayload = {demo_source: "evidence_gateway_snapshot", snapshot};
  state.caseId = visual.case_id || "";
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  state.publicSafeDemoMode = false;
  elements.caseIdBadge.textContent = state.caseId || "Gateway Snapshot";
  elements.intentBadge.textContent = "gateway_snapshot";
  elements.lesionFigure.hidden = true;
  elements.lesionFigure.innerHTML = "";
  elements.visualMeta.innerHTML = `
    <p class="pipeline-note">真实 VLM + MedSAM2 视觉链路已跑通，但当前结果只进入 Evidence Gateway 的 candidate-only review。</p>
    ${renderMetricGrid({
      prompt_source: visual.prompt_source,
      auto_eval_status: visual.auto_eval_status,
      medsam2_ready: visual.medsam2_ready,
      reference_mask_used: visual.reference_mask_used,
      reference_mask_role: visual.reference_mask_role,
      failure_types: visual.failure_types,
      mask_path: visual.artifacts?.mask_path,
      overlay_path: visual.artifacts?.overlay_path,
    })}
  `;
  elements.reportView.innerHTML = `
    <div class="report-section">
      <h3>当前验证结论</h3>
      ${renderMetricGrid({
        overall_status: snapshot.overall_status,
        recommended_narrative: architecture.recommended_narrative,
        not_five_parallel_agents: architecture.not_five_parallel_agents,
      })}
    </div>
    <div class="report-section">
      <h3>可以宣称</h3>
      ${renderList(claims.can_claim || [])}
    </div>
    <div class="report-section">
      <h3>不能宣称</h3>
      ${renderList(claims.cannot_claim || [])}
    </div>
  `;
  elements.alignmentView.innerHTML = `
    <p class="pipeline-note">上层是临床证据流水线，下层是 Agentic Runtime / Evidence Gateway；这不是五个并列 Agent 的堆叠。</p>
    <div class="trace-subblock">
      <strong>Top Layer</strong>
      ${renderList(architecture.top_layer || [])}
    </div>
    <div class="trace-subblock">
      <strong>Runtime Gateway</strong>
      ${renderList(architecture.runtime_gateway || [])}
    </div>
  `;
  elements.evidenceView.innerHTML = `
    <div class="trace-subblock">
      <strong>Key Metrics</strong>
      ${renderMetricGrid(metrics)}
    </div>
    <div class="trace-subblock">
      <strong>Artifacts</strong>
      ${renderMetricGrid(visual.artifacts || {})}
    </div>
  `;
  elements.auditView.innerHTML = `
    <p class="pipeline-note">Candidate gate 默认阻断未验证视觉失败项，不允许自动修改正式 guideline knowledge 或诊断报告。</p>
    ${renderMetricGrid({
      candidate_count: gate.candidate_count,
      non_reference_metric_review_count: gate.non_reference_metric_review_count,
      pending_review_count: gate.pending_review_count,
      promotion_status: gate.promotion_status,
      formal_update_allowed: gate.formal_update_allowed,
      candidate_only: gate.candidate_only,
      formal_knowledge_updated: gate.formal_knowledge_updated,
      formal_guideline_updated: gate.formal_guideline_updated,
      diagnosis_report_updated: gate.diagnosis_report_updated,
    })}
    <div class="trace-subblock">
      <strong>Candidate Type Counts</strong>
      ${renderMetricGrid(gate.candidate_type_counts || {})}
    </div>
  `;
}

function renderPayload(payload) {
  state.lastPayload = payload;
  state.caseId = payload.case_id || state.caseId || "";
  state.demoCaseSlug = payload.demo_case_slug || state.demoCaseSlug || "";
  state.realDemoMode = payload.demo_source === "real_vlm_medsam2_artifact" || state.realDemoMode;
  state.publicSafeDemoMode = payload.demo_source === "public_safe_demo_suite" || state.publicSafeDemoMode;
  elements.caseIdBadge.textContent = state.caseId || "无病例";
  elements.intentBadge.textContent = payload.intent || "-";
  renderVisualOutput(payload);
  renderReport(payload);
  renderAlignmentPlan(payload);
  renderEvidenceBundle(payload);
  renderMemoryAudit(payload);
  if (state.caseId && !payload.memory_replay) {
    refreshMemoryReplay(state.caseId);
  }
  loadKnowledgeList();
  updateQaControls();
}

function renderQaPayload(payload) {
  state.caseId = payload.case_id || state.caseId || "";
  state.lastPayload = {
    ...state.lastPayload,
    case_id: state.caseId,
    intent: payload.intent || "qa",
    demo_source: payload.demo_source || state.lastPayload.demo_source,
    qa_source: payload.qa_source || state.lastPayload.qa_source,
    memory_audit: payload.memory_audit || state.lastPayload.memory_audit,
    memory_replay: payload.memory_replay || state.lastPayload.memory_replay,
    runtime_gateway_trace: payload.runtime_gateway_trace || state.lastPayload.runtime_gateway_trace,
  };
  if (payload.demo_source || payload.qa_source) {
    renderVisualOutput(state.lastPayload);
  }
  if (payload.memory_audit || payload.memory_replay || payload.runtime_gateway_trace) {
    renderMemoryAudit(state.lastPayload);
  }
  updateQaControls();
}

async function refreshMemoryReplay(caseId) {
  try {
    const replay = await fetchMemoryReplay(caseId);
    if (state.caseId !== caseId) {
      return;
    }
    state.lastPayload.memory_replay = replay;
    renderMemoryAudit(state.lastPayload);
  } catch (error) {
    return;
  }
}

function setQaPending(isPending) {
  state.qaPending = isPending;
  if (!isPending) {
    state.qaAbortController = null;
    state.qaPendingItem = null;
    state.qaPendingQuestion = "";
  }
  updateQaControls();
}

function updateQaControls() {
  const analysisReady = Boolean(state.caseId);
  elements.qaInput.disabled = !analysisReady || state.casePending || state.qaPending;
  elements.qaSubmitButton.disabled = !analysisReady || state.casePending;
  elements.qaSubmitButton.textContent = state.qaPending ? "撤回" : "发送";
  elements.qaInput.placeholder = analysisReady
    ? "例如：为什么增强肿瘤没有结果？"
    : "分析完成后可以追问";
}

function setCasePending(isPending, label = "运行分析") {
  state.casePending = isPending;
  elements.submitButton.disabled = isPending;
  [
    elements.sampleGliomaButton,
    elements.publicSafeDemoButton,
    elements.realVlmMedSAM2Button,
    elements.evidenceGatewaySnapshotButton,
    elements.xrayInsufficientButton,
    elements.fhnNoMaskButton,
    elements.autoRoutingRiskCompareButton,
  ].forEach((button) => {
    if (button) {
      button.disabled = isPending;
    }
  });
  elements.submitButton.textContent = isPending ? "Thinking..." : label;
  updateQaControls();
  if (!isPending) {
    clearCaseProgressTimer();
  }
}

function bindOptionalClick(element, handler) {
  if (element) {
    element.addEventListener("click", handler);
  }
}

function showCaseThinking(label) {
  elements.visualMeta.innerHTML = `
    <div class="trace-empty" aria-busy="true">
      Thinking... ${escapeHtml(label || "视觉 Agent 正在分析")}
    </div>
  `;
  elements.reportView.innerHTML = `
    <div class="report-empty" aria-busy="true">
      Thinking... 等待诊断报告
    </div>
  `;
  elements.evidenceView.innerHTML = `
    <div class="trace-empty" aria-busy="true">
      Thinking... 等待 evidence bundle
    </div>
  `;
  elements.alignmentView.innerHTML = `
    <div class="trace-empty" aria-busy="true">
      Thinking... 等待 alignment plan
    </div>
  `;
  elements.auditView.innerHTML = `
    <div class="trace-empty" aria-busy="true">
      Thinking... 等待 memory audit
    </div>
  `;
  elements.lesionFigure.hidden = true;
  elements.lesionFigure.innerHTML = "";
}

function renderCaseError(error, fallbackMessage = "病例分析失败") {
  const message = error?.message || fallbackMessage;
  const structuredHtml = renderStructuredErrorPanel(error, fallbackMessage);
  if (structuredHtml) {
    elements.visualMeta.innerHTML = structuredHtml;
    elements.reportView.innerHTML = structuredHtml;
    elements.evidenceView.innerHTML = structuredHtml;
    elements.auditView.innerHTML = structuredHtml;
    elements.lesionFigure.hidden = true;
    elements.lesionFigure.innerHTML = "";
    return;
  }
  const detailHtml = `
    <div class="trace-empty error-state" role="alert">
      <strong>${escapeHtml(fallbackMessage)}</strong>
      <p>${escapeHtml(message)}</p>
      <p class="muted">如果是实时上传病例，请检查是否已经上传影像、VLM/API 是否可用，以及分割后端是否配置完成。</p>
    </div>
  `;
  elements.visualMeta.innerHTML = detailHtml;
  elements.reportView.innerHTML = `
    <div class="report-empty error-state" role="alert">
      <strong>${escapeHtml(fallbackMessage)}</strong>
      <p>${escapeHtml(message)}</p>
    </div>
  `;
  elements.evidenceView.innerHTML = detailHtml;
  elements.auditView.innerHTML = detailHtml;
  elements.lesionFigure.hidden = true;
  elements.lesionFigure.innerHTML = "";
}

function renderStructuredErrorPanel(error, fallbackMessage = "病例分析失败") {
  const body = error?.apiPayload || {};
  if (isOnfhVisualCandidateFailure(error)) {
    return `
      <div class="report-section readiness-error-panel error-state" role="alert">
        <h3>不适用当前 ONFH 专病系统</h3>
        <p>视觉链路未能在当前图片中确认可用于股骨头坏死筛查的髋关节候选区域。</p>
        <h4>需要处理</h4>
        ${renderList([
          "请上传骨盆正位、蛙式位或清晰髋关节 MRI。",
          "如果当前图片是胸部、脑部或其他部位影像，应切换到对应专病系统。",
        ])}
        <p class="muted">该提示来自 ONFH 适用性检查；不会把底层视觉管线错误当作诊断结果。</p>
      </div>
    `;
  }
  if (!body.error_type && !body.medsam2_configuration && !body.routing_decision) {
    return "";
  }
  let title = fallbackMessage;
  if (body.error_type === "medsam2_not_ready") {
    title = "部署检查未通过";
  } else if (body.error_type === "vlm_api_unavailable") {
    title = "VLM/API 临时不可用";
  }
  const actionItems = Array.isArray(body.action_items) ? body.action_items : [];
  const medsam2 = body.medsam2_configuration || {};
  const routing = body.routing_decision || {};
  const detail = body.error || error?.message || fallbackMessage;
  return `
    <div class="report-section readiness-error-panel error-state" role="alert">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(detail)}</p>
      ${actionItems.length ? `
        <h4>需要处理</h4>
        ${renderList(actionItems)}
      ` : ""}
      ${Object.keys(routing).length ? `
        <h4>本次分析路径</h4>
        ${renderMetricGrid({
          selected_knowledge: routing.selected_knowledge,
          primary_hypothesis: routing.primary_hypothesis,
          routing_evidence_status: routing.routing_evidence_status || routing.initial_evidence_status,
        })}
      ` : ""}
      ${Object.keys(medsam2).length ? `
        <h4>MedSAM2 配置</h4>
        ${renderMetricGrid({
          real_call_ready: medsam2.real_call_ready,
          command_template_present: medsam2.command_template_present,
          repo_path_exists: medsam2.repo_path_exists,
          checkpoint_path_exists: medsam2.checkpoint_path_exists,
          config_path_exists: medsam2.config_path_exists,
        })}
      ` : ""}
      <p class="muted">这个提示已放在报告区；顶部状态栏只保留短提示，避免错误细节挤占界面。</p>
    </div>
  `;
}

function isOnfhVisualCandidateFailure(error) {
  const body = error?.apiPayload || {};
  const text = [
    body.error,
    body.technical_detail,
    error?.message,
  ].filter(Boolean).join(" ");
  return text.includes("FHN no-mask visual pipeline did not complete")
    && text.includes("finding_segmentation_not_ready");
}

function showQaThinking(question) {
  const item = document.createElement("div");
  item.className = "qa-item qa-pending";
  item.setAttribute("aria-busy", "true");
  item.innerHTML = `<strong>${escapeHtml(question)}</strong><p>Thinking...</p>`;
  elements.qaLog.prepend(item);
  return item;
}

function updateQaItem(item, question, answer, kind = "") {
  if (kind === "withdrawn") {
    item.remove();
    return;
  }
  item.className = kind ? `qa-item qa-${kind}` : "qa-item";
  item.removeAttribute("aria-busy");
  item.innerHTML = `<strong>${escapeHtml(question)}</strong>${renderPatientQaAnswer(answer)}`;
}

function renderPatientQaAnswer(answer) {
  const paragraphs = patientQaAnswerParagraphs(answer);
  if (!paragraphs.length) {
    return '<div class="qa-answer"><p>-</p></div>';
  }
  return `
    <div class="qa-answer">
      ${paragraphs.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("")}
    </div>
  `;
}

function patientQaAnswerParagraphs(answer) {
  const cleaned = String(answer || "")
    .replace(/\*\*/g, "")
    .replace(/__/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (!cleaned) {
    return [];
  }
  const parts = cleaned
    .split(/(?<=[。！？!?])\s+/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (parts.length <= 1 && cleaned.length > 150) {
    return cleaned
      .split(/(?<=；|;)\s*/)
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, 3);
  }
  return parts.slice(0, 3);
}

function ensureImageLightbox() {
  let lightbox = document.getElementById("imageLightbox");
  if (lightbox) {
    return lightbox;
  }
  lightbox = document.createElement("div");
  lightbox.id = "imageLightbox";
  lightbox.className = "image-lightbox";
  lightbox.hidden = true;
  lightbox.innerHTML = `
    <div class="image-lightbox-backdrop" data-lightbox-close="true"></div>
    <section class="image-lightbox-panel" role="dialog" aria-modal="true" aria-labelledby="imageLightboxTitle">
      <div class="image-lightbox-head">
        <strong id="imageLightboxTitle"></strong>
        <button type="button" data-lightbox-close="true" aria-label="关闭放大图">×</button>
      </div>
      <div class="image-lightbox-body">
        <img alt="" />
      </div>
      <div class="image-lightbox-crops" aria-label="局部放大候选区域"></div>
      <p class="image-lightbox-caption"></p>
    </section>
  `;
  document.body.appendChild(lightbox);
  return lightbox;
}

function openImageLightbox({src, title, caption, regions}) {
  if (!src) {
    return;
  }
  const lightbox = ensureImageLightbox();
  const image = lightbox.querySelector("img");
  const crops = lightbox.querySelector(".image-lightbox-crops");
  const parsedRegions = parseLightboxRegions(regions);
  crops.innerHTML = "";
  image.onload = () => renderLightboxCrops(image, parsedRegions, crops);
  image.alt = title || "放大查看影像标注";
  image.src = src;
  lightbox.querySelector("#imageLightboxTitle").textContent = title || "影像标注";
  lightbox.querySelector(".image-lightbox-caption").textContent = caption || "";
  lightbox.hidden = false;
  document.body.classList.add("lightbox-open");
  lightbox.querySelector("[data-lightbox-close='true']").focus();
  if (image.complete && image.naturalWidth) {
    renderLightboxCrops(image, parsedRegions, crops);
  }
}

function closeImageLightbox() {
  const lightbox = document.getElementById("imageLightbox");
  if (!lightbox) {
    return;
  }
  lightbox.hidden = true;
  lightbox.querySelector("img").removeAttribute("src");
  lightbox.querySelector(".image-lightbox-crops").innerHTML = "";
  document.body.classList.remove("lightbox-open");
}

function parseLightboxRegions(rawRegions) {
  if (Array.isArray(rawRegions)) {
    return rawRegions;
  }
  if (!rawRegions) {
    return [];
  }
  try {
    const parsed = JSON.parse(rawRegions);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function renderLightboxCrops(image, regions, container) {
  container.innerHTML = "";
  const normalizedRegions = regions
    .map((region) => ({
      ...region,
      bbox: normalizeBbox(region.bbox),
    }))
    .filter((region) => region.bbox)
    .slice(0, 6);
  if (!normalizedRegions.length || !image.naturalWidth || !image.naturalHeight) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  const heading = document.createElement("strong");
  heading.textContent = "局部放大";
  container.appendChild(heading);
  const grid = document.createElement("div");
  grid.className = "image-lightbox-crop-grid";
  normalizedRegions.forEach((region, index) => {
    grid.appendChild(buildLightboxCropItem({
      image,
      region,
      index,
    }));
  });
  container.appendChild(grid);
}

function buildLightboxCropItem({image, region, index}) {
  const item = document.createElement("article");
  item.className = "image-lightbox-crop-item";
  const canvas = document.createElement("canvas");
  const crop = paddedCrop(region.bbox, image.naturalWidth, image.naturalHeight);
  const targetWidth = 360;
  const targetHeight = Math.max(180, Math.round((crop.height / crop.width) * targetWidth));
  canvas.width = targetWidth;
  canvas.height = targetHeight;
  const context = canvas.getContext("2d");
  const style = visualFindingStyle(region.target);
  context.drawImage(
    image,
    crop.x,
    crop.y,
    crop.width,
    crop.height,
    0,
    0,
    targetWidth,
    targetHeight,
  );
  enhanceCanvasContrast(context, targetWidth, targetHeight);
  const scaleX = targetWidth / crop.width;
  const scaleY = targetHeight / crop.height;
  const [x1, y1, x2, y2] = region.bbox;
  drawCandidateHighlight({
    context,
    label: style.label || "候选区域",
    color: style.color || "#ef4444",
    rect: {
      x: (x1 - crop.x) * scaleX,
      y: (y1 - crop.y) * scaleY,
      width: (x2 - x1) * scaleX,
      height: (y2 - y1) * scaleY,
    },
  });
  const label = document.createElement("div");
  label.innerHTML = `
    <strong>候选区域 ${escapeHtml(region.regionId || String(index + 1))}</strong>
    <span>${escapeHtml([region.laterality, region.areaPx ? `${region.areaPx} px` : ""].filter(Boolean).join(" · ") || "bbox 局部放大")}</span>
  `;
  const hint = document.createElement("p");
  hint.textContent = style.guidance || "看彩色高亮框内的局部灰度、纹理或轮廓异常。";
  item.appendChild(canvas);
  item.appendChild(label);
  item.appendChild(hint);
  return item;
}

function enhanceCanvasContrast(context, width, height) {
  let imageData;
  try {
    imageData = context.getImageData(0, 0, width, height);
  } catch (error) {
    return;
  }
  const data = imageData.data;
  const contrast = 1.32;
  const brightness = 5;
  for (let index = 0; index < data.length; index += 4) {
    const gray = data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114;
    const enhanced = Math.max(0, Math.min(255, (gray - 128) * contrast + 128 + brightness));
    data[index] = enhanced;
    data[index + 1] = enhanced;
    data[index + 2] = enhanced;
  }
  context.putImageData(imageData, 0, 0);
}

function drawCandidateHighlight({context, label, color, rect}) {
  const x = Math.max(0, rect.x);
  const y = Math.max(0, rect.y);
  const width = Math.max(8, rect.width);
  const height = Math.max(8, rect.height);
  context.save();
  context.fillStyle = hexToRgba(color, 0.22);
  context.strokeStyle = color;
  context.lineWidth = 4;
  context.fillRect(x, y, width, height);
  context.strokeRect(x, y, width, height);
  context.setLineDash([8, 5]);
  context.lineWidth = 2;
  context.strokeStyle = "#ffffff";
  context.strokeRect(x + 4, y + 4, Math.max(1, width - 8), Math.max(1, height - 8));
  context.setLineDash([]);
  const labelText = `看这里：${label}`;
  context.font = "bold 18px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
  const metrics = context.measureText(labelText);
  const labelWidth = Math.min(context.canvas.width - 16, metrics.width + 18);
  const labelHeight = 30;
  const labelX = Math.max(8, Math.min(context.canvas.width - labelWidth - 8, x));
  const labelY = y > 42 ? y - 38 : Math.min(context.canvas.height - labelHeight - 8, y + height + 8);
  context.fillStyle = hexToRgba(color, 0.92);
  context.fillRect(labelX, labelY, labelWidth, labelHeight);
  context.fillStyle = "#ffffff";
  context.fillText(labelText, labelX + 9, labelY + 21);
  context.restore();
}

function hexToRgba(hex, alpha) {
  const normalized = String(hex || "#ef4444").replace("#", "");
  const value = normalized.length === 3
    ? normalized.split("").map((char) => char + char).join("")
    : normalized.padEnd(6, "0").slice(0, 6);
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function paddedCrop(bbox, imageWidth, imageHeight) {
  const [x1, y1, x2, y2] = bbox;
  const width = x2 - x1;
  const height = y2 - y1;
  const padding = Math.max(width, height, 36) * 1.15;
  const centerX = (x1 + x2) / 2;
  const centerY = (y1 + y2) / 2;
  const cropWidth = Math.min(imageWidth, Math.max(width + padding * 2, 96));
  const cropHeight = Math.min(imageHeight, Math.max(height + padding * 2, 96));
  const cropX = Math.max(0, Math.min(imageWidth - cropWidth, centerX - cropWidth / 2));
  const cropY = Math.max(0, Math.min(imageHeight - cropHeight, centerY - cropHeight / 2));
  return {
    x: cropX,
    y: cropY,
    width: cropWidth,
    height: cropHeight,
  };
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setKnowledgeSelectionMode(mode = "primary_only", manualSecondaryKnowledges = []) {
  state.sampleKnowledgeSelectionMode = mode;
  state.sampleManualSecondaryKnowledges = Array.isArray(manualSecondaryKnowledges)
    ? manualSecondaryKnowledges
    : [];
  elements.knowledgeSelectionMode.value = mode;
  elements.manualSecondaryKnowledges.value = state.sampleManualSecondaryKnowledges.join(", ");
  renderManualSecondaryKnowledgeSelection();
}

function setEvidenceProtocolMode(mode = "finding_list_baseline") {
  const normalized = mode === "quantitative_optional"
    ? "quantitative_optional"
    : "finding_list_baseline";
  state.sampleEvidenceProtocolMode = normalized;
  elements.evidenceProtocolMode.value = normalized;
}

function selectedManualSecondaryKnowledges() {
  return splitList(elements.manualSecondaryKnowledges.value);
}

function clearManualSecondaryKnowledges() {
  state.sampleManualSecondaryKnowledges = [];
  elements.manualSecondaryKnowledges.value = "";
  syncManualSecondarySelectionToPayload([]);
  renderManualSecondaryKnowledgeSelection();
}

function syncManualSecondarySelectionToPayload(selected) {
  const normalized = Array.isArray(selected) ? selected : [];
  state.sampleManualSecondaryKnowledges = normalized;
  if (!state.lastPayload || !Object.keys(state.lastPayload).length) {
    return;
  }
  state.lastPayload.manual_secondary_knowledge_candidates = normalized;
  state.lastPayload.knowledge_selection_mode = normalized.length ? "manual_secondary" : "primary_only";
  const routing = state.lastPayload.routing_decision || {};
  routing.manual_secondary_knowledge_candidates = normalized;
  routing.knowledge_selection_mode = state.lastPayload.knowledge_selection_mode;
  state.lastPayload.routing_decision = routing;
}

function selectManualSecondaryKnowledge(knowledgeKey) {
  const normalized = String(knowledgeKey || "").trim();
  if (!normalized) {
    return;
  }
  const selected = selectedManualSecondaryKnowledges();
  if (!selected.includes(normalized)) {
    selected.push(normalized);
  }
  elements.manualSecondaryKnowledges.value = selected.slice(0, 3).join(", ");
  elements.knowledgeSelectionMode.value = "manual_secondary";
  syncManualSecondarySelectionToPayload(selectedManualSecondaryKnowledges());
  renderManualSecondaryKnowledgeSelection();
  renderReport(state.lastPayload);
  setStatus("已加入备用复查，点击“运行分析”会按人工备用 Knowledge 模式重新分析", "ok");
}

function removeManualSecondaryKnowledge(knowledgeKey) {
  const normalized = String(knowledgeKey || "").trim();
  if (!normalized) {
    return;
  }
  const selected = selectedManualSecondaryKnowledges().filter((item) => item !== normalized);
  elements.manualSecondaryKnowledges.value = selected.join(", ");
  if (!selected.length && elements.knowledgeSelectionMode.value === "manual_secondary") {
    elements.knowledgeSelectionMode.value = "primary_only";
  }
  syncManualSecondarySelectionToPayload(selected);
  renderManualSecondaryKnowledgeSelection();
  renderReport(state.lastPayload);
  setStatus("已取消备用复查", "ok");
}

function renderManualSecondaryKnowledgeSelection() {
  const selected = selectedManualSecondaryKnowledges();
  const target = document.getElementById("manualSecondaryKnowledgeSelection");
  if (!target) {
    return;
  }
  target.innerHTML = `
    <strong>当前备用复查 Knowledge</strong>
    ${selected.length ? `
      <div class="manual-secondary-selection-list">
        ${selected.map((knowledgeKey) => `
          <span class="manual-secondary-selection-item">
            <b>${escapeHtml(humanDiseaseName(knowledgeKey))}</b>
            <button
              type="button"
              aria-label="取消 ${escapeHtml(humanDiseaseName(knowledgeKey))} 备用复查"
              data-secondary-knowledge-remove-key="${escapeHtml(knowledgeKey)}"
            >取消</button>
          </span>
        `).join("")}
      </div>
    ` : `
      <span>先运行主 Knowledge 分析；系统给出候选假设后，可在报告中点击“加入备用复查”。</span>
    `}
  `;
}

function loadStandardSample() {
  elements.patientMessage.value = "请基于这次 FLAIR MRI 做胶质瘤辅助分析";
  elements.imageModality.value = "mri";
  elements.imagePath.value = "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz";
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  state.useSampleMask = true;
  state.sampleDiseaseKey = "";
  state.sampleVisionMode = "";
  setKnowledgeSelectionMode("primary_only");
  setEvidenceProtocolMode("finding_list_baseline");
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  state.publicSafeDemoMode = false;
  elements.symptoms.value = "头痛";
  elements.uploadStatus.textContent = "已载入内置 BraTS FLAIR 样例；将自动使用参考 mask 稳定生成病灶图。";
}

function loadRealVlmMedSAM2Sample() {
  elements.patientMessage.value = "请展示真实 VLM bbox + MedSAM2 分割 + 诊断 Agent 的 BraTS 胶质瘤样例";
  elements.imageModality.value = "mri";
  elements.imagePath.value = "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz";
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  state.useSampleMask = false;
  state.sampleDiseaseKey = "diffuse_glioma_brats";
  state.sampleVisionMode = "medsam2";
  setKnowledgeSelectionMode("primary_only");
  setEvidenceProtocolMode("finding_list_baseline");
  state.demoCaseSlug = "";
  state.realDemoMode = true;
  state.publicSafeDemoMode = false;
  elements.symptoms.value = "头痛";
  elements.uploadStatus.textContent = "已载入真实 VLM+MedSAM2 样例 artifact；将展示候选框、分割图、Dice/QC 和诊断报告。";
}

function loadXrayInsufficientSample() {
  elements.patientMessage.value = "左髋疼痛，X光能不能判断有没有早期股骨头坏死？";
  elements.imageModality.value = "xray";
  elements.imagePath.value = "output/fake/uploads/hip_xray.png";
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  state.useSampleMask = false;
  state.sampleDiseaseKey = "";
  state.sampleVisionMode = "";
  setKnowledgeSelectionMode("primary_only");
  setEvidenceProtocolMode("finding_list_baseline");
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  state.publicSafeDemoMode = false;
  elements.symptoms.value = "髋关节疼痛";
  elements.uploadStatus.textContent = "已载入髋部 X 光证据不足样例；该样例会触发指南影像不足门控，不生成 mask。";
}

function loadFhnNoMaskSample() {
  elements.patientMessage.value = "右髋疼痛，上传 X 光，请根据股骨头坏死 knowledge 自动圈出候选征象";
  elements.imageModality.value = "xray";
  elements.imagePath.value = "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png";
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  state.useSampleMask = false;
  state.sampleDiseaseKey = "femoral_head_necrosis";
  state.sampleVisionMode = "no_mask_knowledge";
  setKnowledgeSelectionMode("primary_only");
  setEvidenceProtocolMode("finding_list_baseline");
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  state.publicSafeDemoMode = false;
  elements.symptoms.value = [
    "症状：右髋疼痛三个月，走路后加重。",
    "检查背景：已上传髋关节 X 光片。",
    "风险因素：长期激素治疗，偶尔饮酒。",
    "外伤史：无明显外伤史。",
  ].join("\n");
  elements.uploadStatus.textContent = "已载入 FHN no-mask 多征象样例；将调用 VLM 生成 box prompt，再由 MedSAM2 分割候选病灶。";
}

function loadAutoRoutingRiskCompareSample() {
  elements.patientMessage.value = [
    "症状：右髋疼痛三个月，走路后加重。",
    "检查背景：已上传髋关节 X 光片。",
    "风险因素：长期激素治疗，偶尔饮酒。",
    "外伤史：无明显外伤史。",
  ].join("\n");
  elements.imageModality.value = "xray";
  elements.imagePath.value = "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png";
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  state.useSampleMask = false;
  state.sampleDiseaseKey = "femoral_head_necrosis";
  state.sampleVisionMode = "real_vlm_validation";
  clearManualSecondaryKnowledges();
  setKnowledgeSelectionMode("primary_only", []);
  setEvidenceProtocolMode("finding_list_baseline");
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  state.publicSafeDemoMode = false;
  elements.symptoms.value = "";
  elements.uploadStatus.textContent = "已载入 ONFH 专病样例；系统将直接使用股骨头坏死 Knowledge 分析髋关节 X 光证据。";
}

function loadPublicSafeDemoInputs() {
  elements.patientMessage.value = "public-safe MVP 演示：髋部疼痛，展示自动 knowledge 路由、视觉候选证据、诊断报告、evidence bundle 和 memory audit";
  elements.imageModality.value = "xray";
  elements.imagePath.value = "";
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  state.useSampleMask = false;
  state.sampleDiseaseKey = "";
  state.sampleVisionMode = "";
  setKnowledgeSelectionMode("primary_only");
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  state.publicSafeDemoMode = false;
  elements.symptoms.value = "髋关节疼痛";
  elements.uploadStatus.textContent = "正在运行 public-safe MVP 样例；使用合成非患者影像，不需要真实 FHN 数据或真实 mask。";
}

function setSampleButtonsDisabled(isDisabled) {
  setCasePending(isDisabled);
}

async function runStandardSample() {
  if (state.casePending) {
    setStatus("上一个病例仍在分析中", "warn");
    return;
  }
  loadStandardSample();
  resetViews();
  setStatus("已载入扩展示例，点击“运行分析”开始", "ok");
}

async function runPublicSafeDemo() {
  if (state.casePending) {
    setStatus("上一个病例仍在分析中", "warn");
    return;
  }
  loadPublicSafeDemoInputs();
  resetViews();
  setCasePending(true);
  showCaseThinking("Public-safe MVP 样例运行中");
  startCaseProgress("运行 Public-safe MVP 样例", [
    {after: 0, text: "正在生成合成非患者影像和病例输入"},
    {after: 2, text: "正在执行自动 knowledge 路由和视觉候选证据链"},
    {after: 4, text: "正在写出 response、evidence bundle、memory audit 和 QA artifact"},
  ]);
  setStatus("Public-safe MVP 样例运行中...");
  try {
    const payload = await fetchPublicSafeDemo();
    renderPayload(payload);
    setStatus("Public-safe MVP 样例完成", "ok");
  } catch (error) {
    renderCaseError(error, "Public-safe MVP 样例运行失败");
    setStatus(error.message, "error");
  } finally {
    setCasePending(false);
  }
}

async function runRealVlmMedSAM2Sample() {
  if (state.casePending) {
    setStatus("上一个病例仍在分析中", "warn");
    return;
  }
  loadRealVlmMedSAM2Sample();
  resetViews();
  setStatus("已载入真实 VLM+MedSAM2 样例，点击“运行分析”开始", "ok");
}

async function runEvidenceGatewaySnapshot() {
  if (state.casePending) {
    setStatus("上一个病例仍在分析中", "warn");
    return;
  }
  setCasePending(true);
  showCaseThinking("Evidence Gateway 快照读取中");
  startCaseProgress("读取 Evidence Gateway 快照", [
    {after: 0, text: "正在读取预生成 artifact"},
    {after: 3, text: "正在整合 gateway 视图"},
  ]);
  setStatus("Evidence Gateway 快照读取中...");
  try {
    const snapshot = await fetchEvidenceGatewaySnapshot();
    renderEvidenceGatewaySnapshot(snapshot);
    setStatus("Evidence Gateway 快照完成", "ok");
  } catch (error) {
    renderCaseError(error, "Evidence Gateway 快照读取失败");
    setStatus(error.message, "error");
  } finally {
    setCasePending(false);
  }
}

async function runXrayInsufficientSample() {
  if (state.casePending) {
    setStatus("上一个病例仍在分析中", "warn");
    return;
  }
  loadXrayInsufficientSample();
  resetViews();
  setStatus("已载入 X 光证据不足样例，点击“运行分析”开始", "ok");
}

async function runFhnNoMaskSample() {
  if (state.casePending) {
    setStatus("上一个病例仍在分析中", "warn");
    return;
  }
  loadFhnNoMaskSample();
  resetViews();
  setStatus("已载入 FHN no-mask 多征象样例，点击“运行分析”开始", "ok");
}

async function runAutoRoutingRiskCompareSample() {
  if (state.casePending) {
    setStatus("上一个病例仍在分析中", "warn");
    return;
  }
  loadAutoRoutingRiskCompareSample();
  resetViews();
  setStatus("已载入 ONFH 专病样例，点击“运行分析”开始", "ok");
}

function resetViews() {
  state.caseId = "";
  state.lastPayload = {};
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  state.publicSafeDemoMode = false;
  state.qaPending = false;
  setCasePending(false);
  updateQaControls();
  elements.qaLog.innerHTML = "";
  elements.reportView.innerHTML = '<div class="report-empty">等待分析结果</div>';
  elements.visualMeta.textContent = "等待视觉 Agent 输出";
  elements.alignmentView.innerHTML = '<div class="trace-empty">等待 alignment plan</div>';
  elements.evidenceView.innerHTML = '<div class="trace-empty">等待 evidence bundle</div>';
  elements.auditView.innerHTML = '<div class="trace-empty">等待 memory audit</div>';
  elements.lesionFigure.hidden = true;
  elements.lesionFigure.innerHTML = "";
  elements.caseIdBadge.textContent = "无病例";
  elements.intentBadge.textContent = "-";
}

elements.clinicalDemoTab.addEventListener("click", () => setWorkspaceView("clinical"));
elements.architectureRoadmapTab.addEventListener("click", () => setWorkspaceView("architecture"));
window.addEventListener("hashchange", () => {
  setWorkspaceView(window.location.hash === "#architecture-roadmap" ? "architecture" : "clinical");
});
elements.healthButton.addEventListener("click", checkHealth);
bindOptionalClick(elements.sampleGliomaButton, runStandardSample);
bindOptionalClick(elements.publicSafeDemoButton, runPublicSafeDemo);
bindOptionalClick(elements.realVlmMedSAM2Button, runRealVlmMedSAM2Sample);
bindOptionalClick(elements.evidenceGatewaySnapshotButton, runEvidenceGatewaySnapshot);
bindOptionalClick(elements.xrayInsufficientButton, runXrayInsufficientSample);
bindOptionalClick(elements.fhnNoMaskButton, runFhnNoMaskSample);
bindOptionalClick(elements.autoRoutingRiskCompareButton, runAutoRoutingRiskCompareSample);
elements.refreshKnowledgesButton.addEventListener("click", loadKnowledgeList);
elements.saveKnowledgeDraftButton.addEventListener("click", async () => {
  try {
    await saveKnowledgeReviewDraft();
  } catch (error) {
    setStatus(error.message, "error");
  }
});
elements.promoteKnowledgeButton.addEventListener("click", async () => {
  try {
    await promoteKnowledgeToFormalLibrary();
  } catch (error) {
    setStatus(error.message, "error");
  }
});
elements.fileInput.addEventListener("change", async () => {
  try {
    await uploadFiles(elements.fileInput.files);
    setStatus("上传完成", "ok");
  } catch (error) {
    setStatus(error.message, "error");
  }
});
["dragenter", "dragover"].forEach((name) => {
  elements.dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    elements.dropZone.classList.add("dragging");
  });
});

["dragleave", "drop"].forEach((name) => {
  elements.dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    elements.dropZone.classList.remove("dragging");
  });
});

elements.dropZone.addEventListener("drop", async (event) => {
  try {
    await uploadFiles(event.dataTransfer.files);
    setStatus("上传完成", "ok");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

document.addEventListener("click", (event) => {
  const architectureModuleButton = event.target.closest("[data-architecture-module]");
  if (architectureModuleButton) {
    selectArchitectureModule(architectureModuleButton.dataset.architectureModule, {scroll: true});
    return;
  }
  const optimizationDirectionButton = event.target.closest("[data-optimization-direction]");
  if (optimizationDirectionButton) {
    selectOptimizationDirection(optimizationDirectionButton.dataset.optimizationDirection, {scroll: true});
    return;
  }
  const secondaryKnowledgeRemoveButton = event.target.closest("[data-secondary-knowledge-remove-key]");
  if (secondaryKnowledgeRemoveButton) {
    removeManualSecondaryKnowledge(secondaryKnowledgeRemoveButton.dataset.secondaryKnowledgeRemoveKey);
    return;
  }
  const secondaryKnowledgeButton = event.target.closest("[data-secondary-knowledge-key]");
  if (secondaryKnowledgeButton) {
    selectManualSecondaryKnowledge(secondaryKnowledgeButton.dataset.secondaryKnowledgeKey);
    return;
  }
  const card = event.target.closest("[data-lightbox-src]");
  if (card) {
    openImageLightbox({
      src: card.dataset.lightboxSrc,
      title: card.dataset.lightboxTitle,
      caption: card.dataset.lightboxCaption,
      regions: card.dataset.lightboxRegions,
    });
    return;
  }
  if (event.target.closest("[data-lightbox-close]")) {
    closeImageLightbox();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeImageLightbox();
  }
});

elements.caseForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.casePending) {
    setStatus("上一个病例仍在分析中", "warn");
    return;
  }
  state.caseId = "";
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  state.publicSafeDemoMode = false;
  state.qaPending = false;
  elements.qaLog.innerHTML = "";
  setCasePending(true);
  showCaseThinking("病例分析中");
  const requestPayload = buildCasePayload();
  startCaseProgress("实时病例分析", caseProgressStagesForPayload(requestPayload));
  setStatus("分析中...");
  try {
    const payload = await postMedScope(requestPayload);
    renderPayload(payload);
    setStatus("分析完成", "ok");
  } catch (error) {
    renderCaseError(error, "病例分析失败");
    setStatus(shortApiErrorMessage(error, "病例分析失败"), "error");
  } finally {
    setCasePending(false);
  }
});

elements.qaForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.qaPending) {
    if (state.qaAbortController) {
      state.qaAbortController.abort();
    }
    if (state.qaPendingItem) {
      updateQaItem(state.qaPendingItem, state.qaPendingQuestion, "", "withdrawn");
    }
    elements.qaInput.value = state.qaPendingQuestion;
    setQaPending(false);
    setStatus("已撤回追问，可修改后重新发送", "ok");
    return;
  }
  const question = elements.qaInput.value.trim();
  if (!question || !state.caseId) {
    setStatus(state.caseId ? "请输入追问" : "需要先完成一个病例", "warn");
    return;
  }
  const thinkingItem = showQaThinking(question);
  state.qaAbortController = new AbortController();
  state.qaPendingItem = thinkingItem;
  state.qaPendingQuestion = question;
  setQaPending(true);
  setStatus("发送中...");
  try {
    const payload = state.realDemoMode
      ? await postRealVlmMedSAM2Qa(buildQaPayload())
      : state.publicSafeDemoMode
        ? await postPublicSafeDemoQa(buildQaPayload())
      : state.demoCaseSlug
        ? await postDemoQa(state.demoCaseSlug, buildQaPayload())
        : await postMedScopeQa(buildQaPayload(), state.qaAbortController.signal);
    renderQaPayload(payload);
    updateQaItem(thinkingItem, question, payload.reply_to_patient);
    elements.qaInput.value = "";
    setStatus("已回答", "ok");
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    updateQaItem(thinkingItem, question, error.message, "error");
    setStatus(error.message, "error");
  } finally {
    setQaPending(false);
  }
});

elements.resetButton.addEventListener("click", () => {
  state.caseId = "";
  state.lastPayload = {};
  state.useSampleMask = false;
  state.sampleDiseaseKey = "";
  state.sampleVisionMode = "";
  setKnowledgeSelectionMode("primary_only");
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  state.publicSafeDemoMode = false;
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  elements.caseForm.reset();
  resetViews();
  setStatus("已清空");
});

updateQaControls();
renderArchitectureRoadmap();
setWorkspaceView(window.location.hash === "#architecture-roadmap" ? "architecture" : "clinical");
checkHealth();
loadResearchEvidenceReview();
loadKnowledgeProtocolComparison();
loadKnowledgeList();
