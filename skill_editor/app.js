const API = "/skill-editor/api";

const els = {
  statusText: document.querySelector("#statusText"),
  refreshButton: document.querySelector("#refreshButton"),
  saveButton: document.querySelector("#saveButton"),
  newSkillButton: document.querySelector("#newSkillButton"),
  newPromptButton: document.querySelector("#newPromptButton"),
  deleteButton: document.querySelector("#deleteButton"),
  skillList: document.querySelector("#skillList"),
  promptList: document.querySelector("#promptList"),
  skillEditor: document.querySelector("#skillEditor"),
  promptEditor: document.querySelector("#promptEditor"),
  promptMarkdown: document.querySelector("#promptMarkdown"),
  authorInput: document.querySelector("#authorInput"),
  noteInput: document.querySelector("#noteInput"),
  stagingPreview: document.querySelector("#stagingPreview"),
  sourcePreview: document.querySelector("#sourcePreview"),
  previewView: document.querySelector("#previewView"),
  rawView: document.querySelector("#rawView"),
  historyView: document.querySelector("#historyView"),
  toast: document.querySelector("#toast"),
};

let state = {
  kind: "skill",
  key: "",
  skills: [],
  prompts: [],
  detail: null,
  tab: "preview",
};

bindEvents();
boot();

function bindEvents() {
  els.refreshButton.addEventListener("click", refreshAll);
  els.saveButton.addEventListener("click", saveCurrent);
  els.newSkillButton.addEventListener("click", createSkill);
  els.newPromptButton.addEventListener("click", createPrompt);
  els.deleteButton.addEventListener("click", deleteCurrent);
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      state.tab = button.dataset.tab;
      renderTabs();
    });
  });
  document.querySelectorAll("[data-skill-field]").forEach((input) => {
    input.addEventListener("input", () => {
      if (state.kind !== "skill" || !state.detail) return;
      state.detail.editor[input.dataset.skillField] = input.value;
      renderPreview();
    });
  });
  els.promptMarkdown.addEventListener("input", () => {
    if (state.kind !== "prompt" || !state.detail) return;
    state.detail.markdown = els.promptMarkdown.value;
    renderPreview();
  });
}

async function boot() {
  try {
    await api("/health");
    setStatus("已连接 MedScope skill_editor，保存会写入当前仓库的 skills/ 和 prompts/");
    await refreshAll();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function refreshAll() {
  const [skillData, promptData] = await Promise.all([
    api("/skills"),
    api("/prompts"),
  ]);
  state.skills = skillData.skills || [];
  state.prompts = promptData.prompts || [];
  renderLists();
  if (state.key) {
    await loadDocument(state.kind, state.key);
  } else if (state.skills.length) {
    await loadDocument("skill", state.skills[0].skill_key);
  } else if (state.prompts.length) {
    await loadDocument("prompt", state.prompts[0].prompt_key);
  }
}

async function loadDocument(kind, key) {
  const detail = await api(`/${kind === "skill" ? "skills" : "prompts"}/${encodeURIComponent(key)}`);
  state.kind = kind;
  state.key = key;
  state.detail = detail;
  state.tab = "preview";
  renderLists();
  renderEditor();
  renderTabs();
}

async function saveCurrent() {
  if (!state.key || !state.detail) return;
  const author = els.authorInput.value.trim() || "未填写";
  const note = els.noteInput.value.trim() || "医生修改";
  if (state.kind === "skill") {
    state.detail = await api(`/skills/${encodeURIComponent(state.key)}`, {
      method: "PUT",
      body: {
        author,
        note,
        editor: collectSkillEditor(),
      },
    });
  } else {
    state.detail = await api(`/prompts/${encodeURIComponent(state.key)}`, {
      method: "PUT",
      body: {
        author,
        note,
        markdown: els.promptMarkdown.value,
      },
    });
  }
  els.noteInput.value = "";
  await refreshAll();
  showToast("已保存，并写入版本记录");
}

async function createSkill() {
  const skillKey = window.prompt("请输入 skill 文件名，例如 femoral_head_necrosis");
  if (!skillKey) return;
  const diseaseName = window.prompt("请输入疾病名称，例如 股骨头坏死") || "新疾病 Skill";
  const created = await api("/skills", {
    method: "POST",
    body: {
      skill_key: skillKey,
      disease_name: diseaseName,
      author: els.authorInput.value.trim() || "系统",
    },
  });
  await refreshAll();
  await loadDocument("skill", created.skill_key);
  showToast("已新增 skill 文件");
}

async function createPrompt() {
  const promptKey = window.prompt("请输入 prompt 文件名，例如 diagnosis_agent_prompt");
  if (!promptKey) return;
  const created = await api("/prompts", {
    method: "POST",
    body: {
      prompt_key: promptKey,
      author: els.authorInput.value.trim() || "系统",
    },
  });
  await refreshAll();
  await loadDocument("prompt", created.prompt_key);
  showToast("已新增 prompt 文件");
}

async function deleteCurrent() {
  if (!state.key) return;
  const label = state.kind === "skill" ? "Skill" : "Prompt";
  const confirmed = window.confirm(`确认删除当前 ${label} 文件？删除前会保存一份版本快照。`);
  if (!confirmed) return;
  await api(`/${state.kind === "skill" ? "skills" : "prompts"}/${encodeURIComponent(state.key)}`, {
    method: "DELETE",
    body: {
      author: els.authorInput.value.trim() || "未填写",
      note: "医生删除文件",
    },
  });
  state.key = "";
  state.detail = null;
  await refreshAll();
  showToast(`已删除 ${label}`);
}

function renderLists() {
  els.skillList.innerHTML = state.skills.map((skill) => `
    <button class="doc-button ${state.kind === "skill" && state.key === skill.skill_key ? "active" : ""}" data-kind="skill" data-key="${escapeHtml(skill.skill_key)}" type="button">
      <strong>${escapeHtml(skill.title || skill.skill_key)}</strong>
      <span>${escapeHtml(skill.skill_key)} · ${escapeHtml(skill.version_count)} 版</span>
    </button>
  `).join("") || '<p class="empty">暂无 skill</p>';
  els.promptList.innerHTML = state.prompts.map((prompt) => `
    <button class="doc-button ${state.kind === "prompt" && state.key === prompt.prompt_key ? "active" : ""}" data-kind="prompt" data-key="${escapeHtml(prompt.prompt_key)}" type="button">
      <strong>${escapeHtml(prompt.title || prompt.prompt_key)}</strong>
      <span>${escapeHtml(prompt.prompt_key)} · ${escapeHtml(prompt.version_count)} 版</span>
    </button>
  `).join("") || '<p class="empty">暂无 prompt</p>';
  document.querySelectorAll(".doc-button").forEach((button) => {
    button.addEventListener("click", () => loadDocument(button.dataset.kind, button.dataset.key));
  });
}

function renderEditor() {
  els.skillEditor.classList.toggle("hidden", state.kind !== "skill");
  els.promptEditor.classList.toggle("hidden", state.kind !== "prompt");
  if (!state.detail) return;
  if (state.kind === "skill") {
    const editor = state.detail.editor || {};
    document.querySelectorAll("[data-skill-field]").forEach((input) => {
      input.value = editor[input.dataset.skillField] || "";
    });
    els.stagingPreview.textContent = editor.staging_rules_preview || "{}";
    els.sourcePreview.textContent = editor.source_documents_preview || "[]";
  } else {
    els.promptMarkdown.value = state.detail.markdown || "";
  }
  renderPreview();
  renderRaw();
  renderHistory();
}

function renderTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.tab);
  });
  els.previewView.classList.toggle("hidden", state.tab !== "preview");
  els.rawView.classList.toggle("hidden", state.tab !== "raw");
  els.historyView.classList.toggle("hidden", state.tab !== "history");
  renderPreview();
  renderRaw();
  renderHistory();
}

function renderPreview() {
  if (!state.detail) {
    els.previewView.innerHTML = "<p>请选择一个文件。</p>";
    return;
  }
  if (state.kind === "prompt") {
    els.previewView.innerHTML = markdownToHtml(state.detail.markdown || "");
    return;
  }
  const editor = collectSkillEditor();
  els.previewView.innerHTML = `
    <h2>${escapeHtml(editor.disease_name || state.key)}</h2>
    ${renderField("Skill ID", editor.skill_id)}
    ${renderField("证据等级", editor.evidence_level)}
    ${renderField("来源", editor.source)}
    ${renderList("常见症状", editor.common_symptoms)}
    ${renderList("风险因素", editor.risk_factors)}
    ${renderList("需要的影像检查", editor.required_image_views)}
    ${renderList("解剖关注区域", editor.anatomy)}
    ${renderList("影像征象", editor.lesion_features)}
    ${renderList("视觉 Agent 目标", editor.segmentation_targets)}
    ${renderList("报告需要包含", editor.report_requirements)}
  `;
}

function renderRaw() {
  if (!state.detail) {
    els.rawView.textContent = "";
    return;
  }
  els.rawView.textContent = state.kind === "skill"
    ? JSON.stringify(state.detail.raw || {}, null, 2)
    : state.detail.markdown || "";
}

function renderHistory() {
  const versions = state.detail?.versions || [];
  if (!versions.length) {
    els.historyView.innerHTML = "<p>暂无版本记录。</p>";
    return;
  }
  els.historyView.innerHTML = versions.map((version) => `
    <article class="history-item">
      <strong>${escapeHtml(version.note || version.action || "修改")}</strong>
      <span>修改人：${escapeHtml(version.author || "未填写")} · ${escapeHtml(version.created_at || "")}</span>
      <div class="history-actions">
        <button type="button" data-version-view="${escapeHtml(version.id)}">对比当前</button>
        <button type="button" data-version-restore="${escapeHtml(version.id)}">恢复此版</button>
      </div>
    </article>
  `).join("") + '<div id="diffBox" class="diff-box"></div>';
  els.historyView.querySelectorAll("[data-version-view]").forEach((button) => {
    button.addEventListener("click", () => compareVersion(button.dataset.versionView));
  });
  els.historyView.querySelectorAll("[data-version-restore]").forEach((button) => {
    button.addEventListener("click", () => restoreVersion(button.dataset.versionRestore));
  });
}

async function compareVersion(versionId) {
  const version = await fetchVersion(versionId);
  const currentText = state.kind === "skill"
    ? JSON.stringify(collectSkillEditor(), null, 2)
    : els.promptMarkdown.value;
  const oldContent = version.content || {};
  const oldText = state.kind === "skill"
    ? JSON.stringify(oldContent, null, 2)
    : oldContent.markdown || "";
  document.querySelector("#diffBox").innerHTML = `
    <h3>版本对比</h3>
    <div class="readonly-grid">
      <label>当前内容<pre>${escapeHtml(currentText)}</pre></label>
      <label>历史版本<pre>${escapeHtml(oldText)}</pre></label>
    </div>
  `;
}

async function restoreVersion(versionId) {
  const confirmed = window.confirm("确认恢复这个历史版本？当前文件会被覆盖，并生成一条恢复记录。");
  if (!confirmed) return;
  const path = `/${state.kind === "skill" ? "skills" : "prompts"}/${encodeURIComponent(state.key)}/versions/${encodeURIComponent(versionId)}/restore`;
  state.detail = await api(path, {
    method: "POST",
    body: {
      author: els.authorInput.value.trim() || "未填写",
    },
  });
  renderEditor();
  showToast("已恢复历史版本");
}

async function fetchVersion(versionId) {
  const path = `/${state.kind === "skill" ? "skills" : "prompts"}/${encodeURIComponent(state.key)}/versions/${encodeURIComponent(versionId)}`;
  const payload = await api(path);
  return payload.version;
}

function collectSkillEditor() {
  if (state.kind !== "skill") return {};
  const editor = {...(state.detail?.editor || {})};
  document.querySelectorAll("[data-skill-field]").forEach((input) => {
    editor[input.dataset.skillField] = input.value;
  });
  return editor;
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    method: options.method || "GET",
    headers: {"Content-Type": "application/json"},
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `请求失败：${response.status}`);
  }
  return payload;
}

function renderField(label, value) {
  return value ? `<p><strong>${escapeHtml(label)}：</strong>${escapeHtml(value)}</p>` : "";
}

function renderList(label, text) {
  const items = splitLines(text);
  if (!items.length) return "";
  return `<h3>${escapeHtml(label)}</h3><ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function splitLines(value) {
  return String(value || "")
    .split(/[\n，,;；]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").split("\n");
  const html = [];
  let inList = false;
  for (const line of lines) {
    const text = line.trim();
    if (!text) {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      continue;
    }
    if (text.startsWith("- ") || text.startsWith("* ")) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${escapeHtml(text.slice(2))}</li>`);
      continue;
    }
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
    if (text.startsWith("### ")) html.push(`<h3>${escapeHtml(text.slice(4))}</h3>`);
    else if (text.startsWith("## ")) html.push(`<h2>${escapeHtml(text.slice(3))}</h2>`);
    else if (text.endsWith("：") || text.endsWith(":")) html.push(`<h3>${escapeHtml(text)}</h3>`);
    else html.push(`<p>${escapeHtml(text)}</p>`);
  }
  if (inList) html.push("</ul>");
  return html.join("");
}

function setStatus(text, kind = "") {
  els.statusText.textContent = text;
  els.statusText.className = kind ? `status-${kind}` : "";
}

function showToast(text) {
  els.toast.textContent = text;
  els.toast.classList.add("show");
  window.setTimeout(() => els.toast.classList.remove("show"), 1800);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
