const state = {
  caseId: "",
  lastPayload: {},
  sampleMaskPath: "data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz",
  useSampleMask: false,
  sampleDiseaseKey: "",
  sampleVisionMode: "",
  demoCaseSlug: "",
  realDemoMode: false,
  casePending: false,
  qaPending: false,
  qaAbortController: null,
  qaPendingItem: null,
  qaPendingQuestion: "",
  caseProgressTimer: null,
  caseProgressStartedAt: 0,
  caseProgressLabel: "",
  selectedSkillKey: "",
  selectedSkillDetail: {},
  uploadedImagePaths: [],
  uploadedImageNames: [],
};

const elements = {
  statusText: document.getElementById("statusText"),
  healthButton: document.getElementById("healthButton"),
  sampleGliomaButton: document.getElementById("sampleGliomaButton"),
  realVlmMedSAM2Button: document.getElementById("realVlmMedSAM2Button"),
  evidenceGatewaySnapshotButton: document.getElementById("evidenceGatewaySnapshotButton"),
  xrayInsufficientButton: document.getElementById("xrayInsufficientButton"),
  fhnNoMaskButton: document.getElementById("fhnNoMaskButton"),
  caseForm: document.getElementById("caseForm"),
  qaForm: document.getElementById("qaForm"),
  submitButton: document.getElementById("submitButton"),
  resetButton: document.getElementById("resetButton"),
  dropZone: document.getElementById("dropZone"),
  fileInput: document.getElementById("fileInput"),
  uploadStatus: document.getElementById("uploadStatus"),
  patientMessage: document.getElementById("patientMessage"),
  visionModeSelect: document.getElementById("visionModeSelect"),
  imagePath: document.getElementById("imagePath"),
  symptoms: document.getElementById("symptoms"),
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
  refreshSkillsButton: document.getElementById("refreshSkillsButton"),
  saveSkillDraftButton: document.getElementById("saveSkillDraftButton"),
  skillListView: document.getElementById("skillListView"),
  skillDetailView: document.getElementById("skillDetailView"),
  skillReviewStatus: document.getElementById("skillReviewStatus"),
};

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
    {after: 0, text: "正在选择 skill 和检查影像输入"},
    {after: 8, text: "正在调用视觉模型定位候选征象"},
    {after: 25, text: "正在生成或校验分割候选区域"},
    {after: 45, text: "正在整合 evidence bundle 和诊断报告"},
  ];
  return stageList.reduce((current, stage) => (
    elapsedSeconds >= stage.after ? stage.text : current
  ), stageList[0].text);
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
  const payload = {
    patient_message: elements.patientMessage.value.trim(),
    image_path: imagePaths[0] || elements.imagePath.value.trim() || null,
    patient_info: {
      symptoms: splitList(elements.symptoms.value),
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
  if (state.sampleDiseaseKey) {
    payload.disease_key = state.sampleDiseaseKey;
  }
  const selectedVisionMode = state.sampleVisionMode || elements.visionModeSelect.value;
  if (selectedVisionMode) {
    payload.vision_mode = selectedVisionMode;
  }
  return payload;
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

async function fetchSkillList() {
  const response = await fetch("/v1/skills");
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  return body;
}

async function fetchSkillDetail(skillKey) {
  const response = await fetch(`/v1/skills/${encodeURIComponent(skillKey)}`);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  return body;
}

async function saveSkillReviewDraft() {
  if (!state.selectedSkillKey) {
    setStatus("请先选择一个 Skill", "warn");
    return;
  }
  const payload = buildSkillDraftPayload();
  const response = await fetch(`/v1/skills/${encodeURIComponent(state.selectedSkillKey)}/review-draft`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  elements.skillReviewStatus.textContent = `草稿已保存：${body.draft_path}`;
  setStatus("Skill 审核：保存草稿完成", "ok");
  await loadSkillDetail(state.selectedSkillKey);
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
  const usedSkill = report.used_skill || {};
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
      selected_skill: evidenceBundle.disease_key || summary.disease_key || "diffuse_glioma_brats",
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
      skill_evidence: {
        selected_skill: evidenceBundle.disease_key || summary.disease_key || "diffuse_glioma_brats",
        selected_vision_mode: "medsam2",
        skill_type: usedSkill.skill_type || "guideline_based",
        guideline_evidence: {
          citations: usedSkill.source_documents || usedSkill.guideline_extraction?.citations || [],
        },
        quality_control: {
          formal_skill_status: usedSkill.skill_type ? "loaded" : "not_reported",
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
        skill_memory: {status: "supported", reason: evidenceBundle.disease_key || summary.disease_key || "diffuse_glioma_brats"},
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
        skill_memory: {
          selected_skill: diseaseKey,
          used_skill: diseaseKey,
          skill_type: usedSkill.skill_type || "guideline_based",
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
      skill_quality: {
        formal_skill_status: usedSkill.skill_type ? "loaded" : "not_reported",
        visual_protocol_status: "used_by_demo",
        citation_status: usedSkill.source_documents?.length ? "present" : "not_reported",
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
        "SkillBuilderAgent",
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
            selected_skill: diseaseKey,
            selected_vision_mode: "medsam2",
            source: "auto",
            agent_scope: "orchestrator_api",
            skill_builder_action: "load_existing_skill",
          },
        },
        SkillBuilderAgent: {
          input: {selected_skill: diseaseKey},
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
            memory_types: ["patient_memory", "image_memory", "skill_memory", "reasoning_memory"],
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
          event: "skill_routing",
          memory_scope: "skill_memory",
          decision_owner: "orchestrator_api",
          routing_decision: {
            selected_skill: diseaseKey,
            selected_vision_mode: "medsam2",
            source: "auto",
            agent_scope: "orchestrator_api",
            skill_builder_action: "load_existing_skill",
          },
          selected_skill: diseaseKey,
          selected_vision_mode: "medsam2",
          skill_type: usedSkill.skill_type,
          skill_builder_action: "load_existing_skill",
        },
        {
          agent: "SkillBuilderAgent",
          event: "skill_loading",
          memory_scope: "skill_memory",
          action: "load_existing_skill",
          selected_skill: diseaseKey,
          used_skill: diseaseKey,
          skill_type: usedSkill.skill_type,
          evidence_level: usedSkill.evidence_level,
          formal_skill_status: usedSkill.skill_type ? "loaded" : "not_reported",
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
          memory_scope: "patient_memory,image_memory,skill_memory,reasoning_memory",
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

async function fetchStandardDemoCaseOrRun(caseSlug, livePayload) {
  try {
    const payload = await fetchStandardDemoCase(caseSlug);
    payload.demo_case_slug = caseSlug;
    return payload;
  } catch (error) {
    setStatus("预生成样例不可用，改为实时分析...", "warn");
    state.demoCaseSlug = "";
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
  elements.visionModeSelect.value = "";
  state.demoCaseSlug = "";
  state.realDemoMode = false;
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
    const model = body.api_route?.model || "-";
    const message = body.status === "ok"
      ? `API 已连接 · route=${route} · model=${model} · 模型${apiReady ? "已配置" : "未配置"} · MedSAM2${medsamReady ? "已配置" : "未配置"}`
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

function renderSkillList(payload) {
  const skills = Array.isArray(payload.skills) ? payload.skills : [];
  if (!skills.length) {
    elements.skillListView.innerHTML = '<div class="trace-empty">暂无可审核 Skill</div>';
    return;
  }
  elements.skillListView.innerHTML = `
    <div class="doctor-skill-list">
      ${skills.map((skill) => {
        const summary = skill.doctor_summary || {};
        const selectedClass = skill.skill_key === state.selectedSkillKey ? " selected" : "";
        return `
          <button class="doctor-skill-item${selectedClass}" type="button" data-skill-key="${escapeHtml(skill.skill_key)}">
            <strong>${escapeHtml(skill.disease_name || skill.skill_key)}</strong>
            <span>${escapeHtml(skill.evidence_level || "未标注")} · ${escapeHtml(skill.skill_type || "skill")}</span>
            <small>症状 ${formatValue(summary.symptom_count)} / 影像 ${formatValue(summary.image_requirement_count)} / 征象 ${formatValue(summary.visual_finding_count)}</small>
            <em>${skill.review_status === "draft_saved" ? "已有医生草稿" : "未审核"}</em>
          </button>
        `;
      }).join("")}
    </div>
  `;
  elements.skillListView.querySelectorAll("[data-skill-key]").forEach((button) => {
    button.addEventListener("click", () => loadSkillDetail(button.dataset.skillKey));
  });
}

async function loadSkillList() {
  elements.skillListView.innerHTML = '<div class="trace-empty">Skill 加载中...</div>';
  try {
    const payload = await fetchSkillList();
    renderSkillList(payload);
    if (!state.selectedSkillKey && payload.skills && payload.skills.length) {
      await loadSkillDetail(payload.skills[0].skill_key);
    }
  } catch (error) {
    elements.skillListView.innerHTML = `<div class="trace-empty">${escapeHtml(error.message)}</div>`;
  }
}

async function loadSkillDetail(skillKey) {
  state.selectedSkillKey = skillKey;
  elements.skillDetailView.innerHTML = '<div class="trace-empty">Skill 详情加载中...</div>';
  try {
    const detail = await fetchSkillDetail(skillKey);
    state.selectedSkillDetail = detail;
    renderSkillReviewWorkspace(detail);
    const listPayload = await fetchSkillList();
    renderSkillList(listPayload);
  } catch (error) {
    elements.skillDetailView.innerHTML = `<div class="trace-empty">${escapeHtml(error.message)}</div>`;
  }
}

function renderSkillReviewWorkspace(detail) {
  const view = detail.doctor_view || {};
  const identity = view.identity || {};
  const clinical = view.clinical_profile || {};
  const imaging = Array.isArray(view.imaging_requirements) ? view.imaging_requirements : [];
  const findings = Array.isArray(view.visual_findings) ? view.visual_findings : [];
  const stages = Array.isArray(view.staging_rules) ? view.staging_rules : [];
  const safety = Array.isArray(view.safety_notes) ? view.safety_notes : [];
  const sources = Array.isArray(view.source_documents) ? view.source_documents : [];
  const draft = detail.draft || {};
  elements.skillReviewStatus.textContent = draft.exists
    ? `已有医生草稿：${draft.draft_path}`
    : "医生审核模式：草稿只保存到 output/fake，不直接覆盖正式 skill。";
  elements.skillDetailView.innerHTML = `
    <div class="doctor-skill-workspace">
      <section class="doctor-skill-section">
        <h3>${escapeHtml(identity.disease_name || detail.skill_key || "未命名 Skill")}</h3>
        ${renderMetricGrid({
          skill_id: identity.skill_id,
          skill_type: identity.skill_type,
          evidence_level: identity.evidence_level,
          source: identity.source,
        })}
      </section>
      <section class="doctor-skill-section doctor-edit-grid">
        <label>常见症状
          <textarea id="skillCommonSymptoms" rows="4">${escapeHtml((clinical.common_symptoms || []).join("\n"))}</textarea>
        </label>
        <label>危险因素
          <textarea id="skillRiskFactors" rows="4">${escapeHtml((clinical.risk_factors || []).join("\n"))}</textarea>
        </label>
        <label>需要的影像检查
          <textarea id="skillImageRequirements" rows="4">${escapeHtml(imaging.map((item) => item.label).join("\n"))}</textarea>
        </label>
        <label>医生审核备注
          <textarea id="skillReviewNotes" rows="4" placeholder="写下需要修改、删除或补充的医学意见"></textarea>
        </label>
      </section>
      <section class="doctor-skill-section">
        <h3>影像征象</h3>
        <div class="doctor-finding-list">
          ${findings.map((finding, index) => renderDoctorFindingEditor(finding, index)).join("") || '<div class="trace-empty">暂无影像征象</div>'}
        </div>
      </section>
      <section class="doctor-skill-section">
        <h3>分期 / 判断规则</h3>
        ${renderDoctorStageCards(stages)}
      </section>
      <section class="doctor-skill-section">
        <h3>证据不足和下一步检查</h3>
        ${renderDoctorSafetyNotes(safety)}
      </section>
      <section class="doctor-skill-section">
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
        <textarea class="skillFindingComment" rows="2" data-target="${escapeHtml(finding.target || "")}" data-display-name="${escapeHtml(finding.display_name || finding.target || "")}" placeholder="例如：描述不准确 / 需要补充典型表现 / 不建议分割"></textarea>
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

function buildSkillDraftPayload() {
  const comments = Array.from(elements.skillDetailView.querySelectorAll(".skillFindingComment"))
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
        common_symptoms: splitListByLine(document.getElementById("skillCommonSymptoms")?.value || ""),
        risk_factors: splitListByLine(document.getElementById("skillRiskFactors")?.value || ""),
      },
      imaging_requirements: splitListByLine(document.getElementById("skillImageRequirements")?.value || ""),
      visual_findings_review: comments,
      review_notes: document.getElementById("skillReviewNotes")?.value.trim() || "",
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
  const evidence = bundle.skill_evidence?.guideline_evidence || payload.guideline_evidence || report.guideline_evidence || {};
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
    || payload.evidence_bundle?.skill_evidence?.alignment_plan
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
      <h3>图像与 Skill</h3>
      ${renderMetricGrid({
        selected_skill: plan.selected_skill,
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
  const skillProposalHtml = renderSkillProposalReport(payload);
  if (skillProposalHtml) {
    elements.reportView.innerHTML = `${renderRoutingClinicalSummary(payload)}${skillProposalHtml}`;
    return;
  }
  if (!Object.keys(report).length && payload.reply_to_patient) {
    elements.reportView.innerHTML = `<div class="report-section"><p>${escapeHtml(payload.reply_to_patient)}</p></div>`;
    return;
  }
  const patientSummaryHtml = renderPatientDiagnosisSummary(payload);
  const hasStructuredReport = Boolean(patientSummaryHtml);
  if (patientSummaryHtml) {
    elements.reportView.innerHTML = patientSummaryHtml;
    return;
  }
  const routingSummaryHtml = renderRoutingClinicalSummary(payload);
  const reportHtml = renderLegacyReportSections(report, hasStructuredReport);
  const differentialHtml = renderDifferentialConsiderations(payload);
  const guidelineEvidenceHtml = renderGuidelineEvidence(payload);
  elements.reportView.innerHTML =
    routingSummaryHtml || reportHtml || differentialHtml || guidelineEvidenceHtml
      ? `${routingSummaryHtml}${reportHtml}${differentialHtml}${guidelineEvidenceHtml}`
      : '<div class="report-empty">无报告字段</div>';
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
  const evidenceItems = patientDiagnosisEvidenceItems(payload).slice(0, 3);
  const nextSteps = patientDiagnosisNextSteps(payload).slice(0, 3);
  return `
    <div class="report-section patient-diagnosis-summary" aria-label="患者诊断摘要">
      <h3>患者诊断摘要</h3>
      <div class="patient-summary-block">
        <h4>结论</h4>
        <p>${escapeHtml(patientDiagnosisConclusion(payload))}</p>
      </div>
      <div class="patient-summary-block">
        <h4>主要依据</h4>
        ${evidenceItems.length ? renderList(evidenceItems) : "<p>当前没有足够稳定的可诊断依据。</p>"}
      </div>
      <div class="patient-summary-block">
        <h4>下一步</h4>
        ${nextSteps.length ? renderList(nextSteps) : "<p>建议结合线下医生评估后决定补充检查。</p>"}
      </div>
    </div>
  `;
}

function patientDiagnosisConclusion(payload) {
  const report = payload.report || {};
  const integrated = report.integrated_reasoning_summary || {};
  const assessment = report.target_disease_assessment || {};
  const targetDisease = integrated.target_disease || assessment.target_disease || payload.routing_decision?.primary_hypothesis;
  const diseaseName = humanDiseaseName(targetDisease || "");
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

function patientDiagnosisEvidenceItems(payload) {
  const report = payload.report || {};
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
  const missingTargets = Array.isArray(missing.missing_required_targets)
    ? missing.missing_required_targets
    : [];
  if (missingTargets.length) {
    items.push(`仍缺少：${missingTargets.slice(0, 3).map(patientMissingEvidenceName).join("、")}。`);
  }
  return items;
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
  const legacyNext = report["建议进一步检查"];
  if (Array.isArray(legacyNext)) {
    return legacyNext;
  }
  if (legacyNext) {
    return [legacyNext];
  }
  return [];
}

function renderSkillProposalReport(payload) {
  const proposal = payload.skill_builder_proposal || {};
  if (!Object.keys(proposal).length) {
    return "";
  }
  const missingEvidence = Array.isArray(payload.missing_evidence) ? payload.missing_evidence : [];
  const limitations = Array.isArray(payload.modality_limitations) ? payload.modality_limitations : [];
  const recommendations = Array.isArray(payload.recommendation) ? payload.recommendation : [];
  return `
    <div class="report-section report-skill-proposal">
      <h3>Skill Builder 候选草案</h3>
      <p>${escapeHtml(payload.reply_to_patient || "当前缺少本地正式 skill，已进入候选草案流程。")}</p>
      ${renderMetricGrid({
        selected_skill: proposal.selected_skill,
        disease_name: proposal.disease_name,
        skill_type: proposal.skill_type,
        evidence_level: proposal.evidence_level,
        formal_update_allowed: proposal.formal_update_allowed === true ? "是" : "否",
        diagnosis_allowed: proposal.diagnosis_allowed === true ? "是" : "否",
      })}
      <p class="warning-text">不能直接诊断；候选 skill 需要指南来源与人工审核后才能进入正式诊断流程。</p>
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
    || payload.evidence_bundle?.skill_evidence?.routing_decision
    || {};
  const report = payload.report || {};
  const assessment = report.target_disease_assessment || {};
  const hypothesis = routing.primary_hypothesis || assessment.target_disease || routing.selected_skill;
  const status = routing.routing_evidence_status
    || routing.initial_evidence_status
    || assessment.evidence_status;
  if (!hypothesis && !status) {
    return "";
  }
  const parts = [];
  if (hypothesis) {
    parts.push(`临床假设：${humanDiseaseName(hypothesis)}`);
  }
  if (status) {
    parts.push(`证据状态：${routingEvidenceStatusLabel(status)}`);
  }
  const candidates = Array.isArray(routing.differential_skill_candidates)
    ? routing.differential_skill_candidates
    : [];
  if (candidates.length) {
    parts.push(`需要鉴别复核：${candidates.map(humanDiseaseName).join("、")}`);
  }
  const hypotheses = Array.isArray(routing.clinical_hypotheses)
    ? routing.clinical_hypotheses
    : [];
  const hypothesisQueueHtml = hypotheses.length
    ? `
      <div class="hypothesis-queue">
        <strong>候选假设队列</strong>
        <ul>
          ${hypotheses.map((item) => `
            <li>
              <span>${escapeHtml(hypothesisRoleLabel(item.role))}</span>
              <b>${escapeHtml(humanDiseaseName(item.disease_key || item.target || ""))}</b>
              <em>${escapeHtml(routingEvidenceStatusLabel(item.status || ""))}</em>
              ${item.reason ? `<small>${escapeHtml(item.reason)}</small>` : ""}
            </li>
          `).join("")}
        </ul>
        <p class="muted">这不是诊断结论；只是根据症状、部位和影像类型决定先检查哪些 evidence。</p>
      </div>
    `
    : "";
  return `
    <div class="report-section report-path-summary">
      <h3>分析路径</h3>
      <p>${escapeHtml(parts.join("；"))}</p>
      ${hypothesisQueueHtml}
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
    early_osteonecrosis: "早期股骨头坏死",
  };
  return labels[target] || target || "";
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
  elements.visualMeta.innerHTML = renderPatientVisualSummary({
    visualBundle,
    displayState,
    modality,
    bodyPart,
    findingCount: numeric.finding_count,
  });
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

function patientVisibleFindings(visualBundle) {
  const findings = Array.isArray(visualBundle.findings) ? visualBundle.findings : [];
  return findings
    .map((finding) => ({
      title: finding.display_name || finding.target || "候选影像发现",
      text: finding.evidence_text || finding.evidence_basis || finding.description || "",
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
      <p>显示 VLM/Codex 根据 skill 给出的候选位置、框选区域和文字证据；这不是像素级医学分割。</p>
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
    || "根据当前 skill 定位出的候选影像征象，点击可放大查看。";
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
            <strong>${escapeHtml(finding.display_name || finding.target || "-")}</strong>
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
  const skill = bundle.skill_evidence || {};
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
      <h3>Skill</h3>
      ${renderMetricGrid({
        selected_skill: skill.selected_skill,
        selected_vision_mode: skill.selected_vision_mode,
        skill_type: skill.skill_type,
        formal_skill_status: skill.quality_control?.formal_skill_status,
        visual_protocol_status: skill.quality_control?.visual_protocol_status,
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
      <h3>Skill Quality</h3>
      ${renderSkillQuality(audit.skill_quality || {})}
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
    <p class="pipeline-note">Runtime Gateway Trace 汇总底层 gateway 的四段执行轨迹：skill 分发、stop hook、自我候选沉淀和正式升级验证门。</p>
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
        formal_skill_updated: safety.formal_skill_updated,
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
        formal_skill_updated: safety.formal_skill_updated,
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
    <p class="pipeline-note">Self-evolving Queue 只沉淀候选记忆、候选规则或 candidate skill patch；验证前不更新正式医疗 skill。</p>
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
        formal_skill_updated: safety.formal_skill_updated,
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
    <p class="pipeline-note">Stop Hook Gate 是只读自检：发现风险并给出 next actions，不自动修改报告或正式 skill。</p>
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
      <strong>Candidate Skill Patch</strong>
      ${renderMetricGrid(gate.candidate_skill_patch || {})}
    </div>
    <div class="trace-subblock">
      <strong>Runtime Safety</strong>
      ${renderMetricGrid({
        stop_hook_executed: safety.stop_hook_executed,
        read_only: safety.read_only,
        formal_skill_updated: safety.formal_skill_updated,
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
    <p class="pipeline-note">Evidence Gateway 记录本轮 skill 分发、文件 artifact、工具调用、contract guards 和只读 safety 状态。</p>
    ${renderMetricGrid({
      schema_version: manifest.schema_version,
      selected_skill: manifest.selected_skill,
      skill_version: manifest.skill_version,
      skill_type: manifest.skill_type,
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
        formal_skill_updated: safety.formal_skill_updated,
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
      name: "skill_memory",
      title: "Skill / 指南 / 路由",
      description: "记录选择了哪个 skill、路由依据、指南来源、质量控制和 alignment plan。",
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
      memory: "patient_memory / skill_memory",
      description: "核心 Agent。读取患者描述和图像上下文，决定 intent、目标 skill、视觉模式和下游调用顺序。",
      metrics: {
        selected_skill: summary.GaoDoctorAgent?.routing_decision?.selected_skill,
        selected_vision_mode: summary.GaoDoctorAgent?.routing_decision?.selected_vision_mode,
        skill_builder_action: summary.GaoDoctorAgent?.routing_decision?.skill_builder_action,
      },
    },
    {
      agent: "SkillBuilderAgent",
      title: "条件 Skill 构建 / 加载",
      memory: "skill_memory",
      description: "条件组件。有现成 skill 时只加载/校验；缺失时才进入指南检索、skill 生成和 visual protocol 构建。",
      metrics: {
        input: summary.SkillBuilderAgent?.input,
        output: summary.SkillBuilderAgent?.output,
      },
    },
    {
      agent: "VisionAgent",
      title: "视觉证据提取",
      memory: "image_memory",
      description: "核心 Agent。按 skill 视觉协议调用 VLM prompt、MedSAM2 和测量工具，返回病灶图与结构化数值。",
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
      memory: "patient/image/skill/reasoning",
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
    <p class="pipeline-note">架构按医疗安全边界拆分为 3 个核心 Agent、1 个条件 Skill 组件和 1 个 Memory/Audit 基础设施层；下方实现节点 trace 保留内部类名用于审计。</p>
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
    skill_routing: "Skill 路由",
    skill_loading: "Skill 加载",
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
  if (step.event === "skill_routing") {
    const routingDecision = step.routing_decision || {};
    return {
      memory_scope: step.memory_scope,
      decision_owner: step.decision_owner || routingDecision.agent_scope,
      selected_skill: step.selected_skill,
      skill_type: step.skill_type,
      routing_source: routingDecision.source,
      skill_builder_action: step.skill_builder_action || routingDecision.skill_builder_action,
      analysis_status: step.analysis_status,
    };
  }
  if (step.event === "skill_loading") {
    return {
      memory_scope: step.memory_scope,
      action: step.action,
      selected_skill: step.selected_skill,
      skill_type: step.skill_type,
      evidence_level: step.evidence_level,
      formal_skill_status: step.formal_skill_status,
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

function renderSkillQuality(quality) {
  if (!Object.keys(quality).length) {
    return '<div class="trace-empty">-</div>';
  }
  return `
    ${renderMetricGrid({
      formal_skill_status: quality.formal_skill_status,
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
    <p class="pipeline-note">Candidate gate 默认阻断未验证视觉失败项，不允许自动修改正式 guideline skill 或诊断报告。</p>
    ${renderMetricGrid({
      candidate_count: gate.candidate_count,
      non_reference_metric_review_count: gate.non_reference_metric_review_count,
      pending_review_count: gate.pending_review_count,
      promotion_status: gate.promotion_status,
      formal_update_allowed: gate.formal_update_allowed,
      candidate_only: gate.candidate_only,
      formal_skill_updated: gate.formal_skill_updated,
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
  updateQaControls();
}

function renderQaPayload(payload) {
  state.caseId = payload.case_id || state.caseId || "";
  state.lastPayload = {
    ...state.lastPayload,
    case_id: state.caseId,
    intent: payload.intent || "qa",
    memory_audit: payload.memory_audit || state.lastPayload.memory_audit,
    memory_replay: payload.memory_replay || state.lastPayload.memory_replay,
    runtime_gateway_trace: payload.runtime_gateway_trace || state.lastPayload.runtime_gateway_trace,
  };
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
  elements.sampleGliomaButton.disabled = isPending;
  elements.realVlmMedSAM2Button.disabled = isPending;
  elements.evidenceGatewaySnapshotButton.disabled = isPending;
  elements.xrayInsufficientButton.disabled = isPending;
  elements.fhnNoMaskButton.disabled = isPending;
  elements.submitButton.textContent = isPending ? "Thinking..." : label;
  updateQaControls();
  if (!isPending) {
    clearCaseProgressTimer();
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
  if (!body.error_type && !body.medsam2_configuration && !body.routing_decision) {
    return "";
  }
  const title = body.error_type === "medsam2_not_ready"
    ? "部署检查未通过"
    : fallbackMessage;
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
          selected_skill: routing.selected_skill,
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

function loadStandardSample() {
  elements.patientMessage.value = "请基于这次 FLAIR MRI 做胶质瘤辅助分析";
  elements.imagePath.value = "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz";
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  state.useSampleMask = true;
  state.sampleDiseaseKey = "";
  state.sampleVisionMode = "";
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  elements.symptoms.value = "头痛";
  elements.uploadStatus.textContent = "已载入内置 BraTS FLAIR 样例；将自动使用参考 mask 稳定生成病灶图。";
}

function loadRealVlmMedSAM2Sample() {
  elements.patientMessage.value = "请展示真实 VLM bbox + MedSAM2 分割 + 诊断 Agent 的 BraTS 胶质瘤样例";
  elements.imagePath.value = "data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz";
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  state.useSampleMask = false;
  state.sampleDiseaseKey = "diffuse_glioma_brats";
  state.sampleVisionMode = "medsam2";
  elements.visionModeSelect.value = "medsam2";
  state.demoCaseSlug = "";
  state.realDemoMode = true;
  elements.symptoms.value = "头痛";
  elements.uploadStatus.textContent = "已载入真实 VLM+MedSAM2 样例 artifact；将展示候选框、分割图、Dice/QC 和诊断报告。";
}

function loadXrayInsufficientSample() {
  elements.patientMessage.value = "左髋疼痛，X光能不能判断有没有早期股骨头坏死？";
  elements.imagePath.value = "output/fake/uploads/hip_xray.png";
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  state.useSampleMask = false;
  state.sampleDiseaseKey = "";
  state.sampleVisionMode = "";
  elements.visionModeSelect.value = "";
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  elements.symptoms.value = "髋关节疼痛";
  elements.uploadStatus.textContent = "已载入髋部 X 光证据不足样例；该样例会触发指南影像不足门控，不生成 mask。";
}

function loadFhnNoMaskSample() {
  elements.patientMessage.value = "右髋疼痛，上传 X 光，请根据股骨头坏死 skill 自动圈出候选征象";
  elements.imagePath.value = "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png";
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  state.useSampleMask = false;
  state.sampleDiseaseKey = "femoral_head_necrosis";
  state.sampleVisionMode = "no_mask_skill";
  elements.visionModeSelect.value = "no_mask_skill";
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  elements.symptoms.value = "髋关节疼痛";
  elements.uploadStatus.textContent = "已载入 FHN no-mask 多征象样例；将调用 VLM 生成 box prompt，再由 MedSAM2 分割候选病灶。";
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
  setStatus("已载入标准样例，点击“运行分析”开始", "ok");
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

function resetViews() {
  state.caseId = "";
  state.lastPayload = {};
  state.demoCaseSlug = "";
  state.realDemoMode = false;
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

elements.healthButton.addEventListener("click", checkHealth);
elements.sampleGliomaButton.addEventListener("click", runStandardSample);
elements.realVlmMedSAM2Button.addEventListener("click", runRealVlmMedSAM2Sample);
elements.evidenceGatewaySnapshotButton.addEventListener("click", runEvidenceGatewaySnapshot);
elements.xrayInsufficientButton.addEventListener("click", runXrayInsufficientSample);
elements.fhnNoMaskButton.addEventListener("click", runFhnNoMaskSample);
elements.refreshSkillsButton.addEventListener("click", loadSkillList);
elements.saveSkillDraftButton.addEventListener("click", async () => {
  try {
    await saveSkillReviewDraft();
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
elements.visionModeSelect.addEventListener("change", () => {
  state.sampleVisionMode = "";
  if (elements.visionModeSelect.value === "real_vlm_validation") {
    setStatus("已选择真实 VLM 候选验证；输出只作为候选视觉证据", "warn");
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
  state.qaPending = false;
  elements.qaLog.innerHTML = "";
  setCasePending(true);
  showCaseThinking("病例分析中");
  startCaseProgress("实时病例分析", [
    {after: 0, text: "正在选择 skill 和检查影像输入"},
    {after: 8, text: "正在调用 VLM/API 定位候选影像征象"},
    {after: 25, text: "正在运行或跳过分割候选区域"},
    {after: 45, text: "正在生成 evidence bundle 和诊断报告"},
  ]);
  setStatus("分析中...");
  try {
    const payload = await postMedScope(buildCasePayload());
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
  elements.visionModeSelect.value = "";
  state.demoCaseSlug = "";
  state.realDemoMode = false;
  state.uploadedImagePaths = [];
  state.uploadedImageNames = [];
  elements.caseForm.reset();
  resetViews();
  setStatus("已清空");
});

updateQaControls();
checkHealth();
loadSkillList();
