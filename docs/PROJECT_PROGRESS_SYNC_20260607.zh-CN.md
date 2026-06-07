# MedScope Agent 项目进度同步 - 2026-06-07

这个文档是当前项目状态的统一入口，用来代替聊天记录里的零散记忆。后续选下一轮 goal 时，优先看这里。

## 当前基线

- 最近实现基线：`900930c feat: structure clinical context evidence`
- 最近文档同步提交：`a43e771 docs: consolidate project progress docs`
- 当前工作区注意：根目录 `goal.md` 仍有本地未提交修改，本文件不修改它。
- 产品安全定位：当前是 evidence-bounded clinical agent MVP，不是临床验证过的自动诊断产品。

## 总览

| 方向 | 当前状态 | 怎么理解 |
| --- | --- | --- |
| 1. Guideline Skill 结构扩展 | v1 基本完成 | FHN skill 已经从 finding list 升级为 evidence acquisition protocol，包含影像、量化、鉴别、临床上下文和综合推理协议。 |
| 2. 患者临床信息结合 | v1 完成并收敛 | 患者 prompt 已结构化为 clinical evidence bundle，report / memory / QA 可追溯展示，并被限制为 suspicion modifier，不能替代影像证据。 |
| 3. 候选假设生成与 Skill Routing | v1 完成 | 用户不显式指定疾病时，髋痛 + X-ray 可以自动生成 FHN primary hypothesis 和 differential candidates；候选假设不是诊断结论。 |
| 4. 论文证据安全补充 Guideline Skill | v1 完成并收敛 | 论文证据可以进入 proposal-only、gateway、human review checklist、dry-run、patch preview 和前端 Review 面板，但不会直接改正式 skill。 |

## 暂存目标

### Real X-ray Case Comparison：finding-list baseline vs evidence-protocol skill

状态：暂存，等待 VisionAgent 能力提升后恢复。

暂停原因：

- 当前 VisionAgent 对真实 X-ray 病灶的定位、分割和量化能力还不稳定。
- 目前无法可靠依靠病灶提示词生成可用 mask。
- 现在强行做旧 finding-list skill vs 新 evidence-protocol skill 的真实病例对比，会被视觉能力瓶颈干扰，无法公平体现 evidence protocol 本身的价值。

本阶段先不做：

- 真实病例旧 skill vs 新 skill 对比。
- 真实病灶自动分割效果对比。
- 真实量化指标对比。
- 基于 VisionAgent 输出证明新版 protocol 更优。

恢复条件：

- 病灶候选定位更稳定。
- mask / ROI / contour 有基本 QC。
- measurement prototype 能在真实样例上稳定输出。
- evidence bundle 能区分 candidate evidence 和 measurement evidence。
- 前端能展示视觉结果和质量限制。

当前替代方向：

- 利用已有人工标注生成 annotation-derived evidence bundle。
- 验证 DiagnosisAgent 在给定结构化 evidence 时的推理正确性。
- 完善 clinical context / audit / QA 的证据边界。
- 保持 VisionAgent 作为独立优化线继续提升。

## 1. Guideline Skill 结构扩展

### 已完成

- `skills/femoral_head_necrosis.yaml` 已包含：
  - `imaging_evidence_protocol`
  - `quantitative_evidence_protocol`
  - `differential_diagnosis_protocol`
  - `clinical_context_protocol`
  - `integrated_reasoning_protocol`
- FHN X-ray 证据目标已经分层：
  - candidate mask：`sclerotic_band`、`cystic_change`、`subchondral_fracture`
  - VLM/观察级：`trabecular_blurring`
  - 测量导向：`collapse`
  - X-ray 证据不足规则：`early_osteonecrosis`
- 量化 protocol 已拆成两类：
  - 影像特征量化：texture/trabecular/sclerosis pattern 等探索性 score
  - 几何或形态测量：collapse depth、suspected area ratio、subchondral fracture extent、左右不对称
- `VisualProtocolValidator` 已检查量化协议、临床上下文边界和 integrated reasoning 必需字段。
- Vision / Diagnosis 流程已经消费 protocol evidence，不再把所有 finding 自动当成诊断事实。
- 保留历史 finding-list baseline，并在前端 Skill 对比面板中展示。
- 真实 ONFH COCO protocol evaluation 默认只评估 X-ray，MRI 只作为辅助特征发现材料。

### 证据位置

- Skill：`skills/femoral_head_necrosis.yaml`
- Validator：`tools/visual_protocol_validator.py`
- Runtime：`agents/vision_agent.py`、`agents/gaodoctor_agent.py`、`agents/diagnosis_agent.py`
- 真实数据 protocol eval：`scripts/onfh_coco_protocol_eval.py`
- 前端对比：`/v1/skills/femoral_head_necrosis/comparison`、`web/app.js`
- 测试：
  - `tests/test_fhn_evidence_protocol.py`
  - `tests/test_visual_protocol_validator.py`
  - `tests/test_onfh_coco_protocol_eval.py`
  - `tests/test_skill_baselines.py`
  - `tests/test_http_entrypoint.py`

### 未完成 / v2

- 量化测量还不是临床可靠测量引擎；ROI、contour、landmark、view quality gate 还主要是协议和质量边界。
- texture / trabecular 这类影像特征量化仍是 exploratory，不是已验证 predictor。
- rich evidence protocol 目前最强的是 FHN 和少数样例 skill，不是所有疾病都覆盖。
- MRI 标注目前只作为发现新病灶特征的辅助材料，不作为当前 runtime 主目标。

### 下一步建议

如果做这部分，建议 goal 是：

```text
FHN X-ray Evidence Protocol v2：让量化/测量协议更可执行、更易审核。
范围：只做 X-ray；强化 collapse、subchondral fracture、area ratio 的前置条件、输出字段、质量门和前端折叠展示。
边界：不声明临床测量准确率。
```

## 2. 患者临床信息结合

### 已完成

- `api/service.py` 会把 patient prompt 中的临床上下文补进 `patient_info`。
- `api/service.py` 会从 patient prompt 结构化抽取：
  - symptoms
  - duration
  - laterality
  - pain location
  - aggravating factors
  - steroid use
  - alcohol use
  - trauma history
- 未提供字段会标记为 `missing` / `unknown`，明确否定的风险因素会标记为 `absent`，不会编造。
- `DiagnosisAgent` 会生成 `clinical_context_bundle`。
- 已支持从 skill protocol 中抽取/匹配风险因素：
  - 激素使用
  - 饮酒
  - 外伤史
  - 血液疾病
  - 自身免疫疾病
- 临床信息边界明确：
  - 只能提高/降低怀疑程度
  - 不能确诊
  - 不能替代影像证据
- Memory/evidence bundle 会暴露 `clinical_context_evidence`。
- `clinical_context_evidence` 会保留 `structured_context`、`source_trace` 和 `suspicion_effect`。
- QA 能引用 clinical context，但会明确说明不能越权诊断。
- tests 已保护“没有影像支持时，不能仅凭临床风险因素确诊”。

### 证据位置

- Prompt preservation：`api/service.py`
- Clinical context bundle：`agents/diagnosis_agent.py`
- Skill protocol：`skills/femoral_head_necrosis.yaml`
- Memory：`memory/memory_manager.py`
- Frontend：`web/app.js`
- 测试：
  - `tests/test_service_entrypoint.py`
  - `tests/test_fhn_evidence_protocol.py`
  - `tests/test_memory_manager.py`
  - `tests/test_mvp_flow.py`
  - `tests/test_http_entrypoint.py`

### 未完成 / v2

- 还没有抽取更细的临床强度字段：
  - 外伤发生时间
  - 激素剂量/持续时间
  - 饮酒强度
- 前端还没有专门的临床风险因素审核表单。
- 缺失临床信息还没有形成自动追问 flow。
- 风险因素还没有在多候选疾病之间做权重排序。

### 下一步建议

```text
Clinical Context Evidence v2：把结构化 clinical evidence bundle 产品化。
范围：补充剂量/强度/时间字段、missing-context questions、前端审核表单和多候选疾病权重。
边界：临床风险因素仍然只能作为 suspicion modifier，不能确诊。
```

## 3. 候选假设生成与 Skill Routing

### 已完成

- 用户不提供 `disease_key` 时，service 可以自动推断 primary disease skill。
- 对“髋痛 + 髋关节/X-ray clues”，primary hypothesis 会变成 `femoral_head_necrosis`。
- 已保留 differential candidates：
  - `osteoarthritis_or_degenerative_hip_disease`
  - `post_traumatic_change`
  - `developmental_dysplasia_related_degeneration`
  - 有感染、炎症、肿瘤提示时追加相应候选
- Routing 输出包括：
  - `primary_hypothesis`
  - `differential_skill_candidates`
  - `clinical_hypotheses`
  - `initial_evidence_status`
  - `routing_evidence_status`
- Diagnosis report 会附加 `clinical_hypotheses_assessment`，并明确：
  - `hypotheses_are_diagnosis=false`
- 前端已经显示“候选假设队列”，并提示“这不是诊断结论”。

### 证据位置

- Routing：`api/service.py`
- Diagnosis boundary：`agents/diagnosis_agent.py`
- Frontend：`web/app.js`
- Memory/audit：`memory/memory_manager.py`
- 测试：
  - `tests/test_service_entrypoint.py`
  - `tests/test_contracts.py`
  - `tests/test_fhn_evidence_protocol.py`
  - `tests/test_memory_manager.py`
  - `tests/test_http_entrypoint.py`

### 未完成 / v2

- 还不是通用多疾病排序系统。
- 没有 candidate hypothesis score model。
- 没有完整 body-part / modality / disease ontology routing registry。
- 当前 FHN 路径下的 differential candidates 主要是规则驱动。

### 下一步建议

这部分不要再作为 v1 重做。如果以后要做：

```text
Hypothesis Routing v2：基于部位、模态、症状和临床上下文做多 skill 排序。
范围：输出 ranked primary/differential skill candidates。
边界：候选假设仍然只是 routing/evidence-acquisition plan，不是诊断。
```

## 4. 论文证据安全补充 Guideline Skill

### 已完成

- `ResearchEvidenceRetriever` 支持 PubMed metadata/abstract retrieval 和 supplied metadata fallback。
- PubMed 不可用时不会阻断 supplied metadata normalization。
- PubMed XML parser 会保留 title、journal、year、PMID、DOI、abstract。
- `ResearchEvidenceExtractor` 能把 metadata / abstract / supplied text 转成 normalized research evidence。
- 不确定字段写 `unknown`，不猜测 sample size、modality 等字段。
- normalized evidence 保留 `source_trace` 和 `source_metadata`。
- `ResearchClaimBuilder` 输出 canonical candidate claim types：
  - `imaging_feature`
  - `quantitative_feature`
  - `geometric_or_morphologic_measurement`
  - `clinical_risk_association`
  - `differential_diagnosis_clue`
- legacy candidate type 单独保留，兼容旧 artifact。
- Evidence Gateway 输出命名 gate status：
  - source quality
  - freshness
  - applicability
  - modality match
  - population match
  - sample size
  - guideline conflict
  - reproducibility / external validation
  - human review required
- Review package 包含：
  - research evidence proposal
  - quality gate report
  - human review checklist
  - promotion dry-run
  - controlled skill extension draft
  - formal skill extension patch preview
- 前端有默认折叠的 Research Evidence Review 面板。
- 安全边界明确：
  - proposal-only
  - 不更新正式 skill
  - 不更新 diagnosis rules
  - 不更新 registry
  - promotion 需要人工审核

### 证据位置

- Builder：`scripts/research_evidence_builder.py`
- API：`/v1/research-evidence-review`，`api/http_server.py`
- Frontend：`web/index.html`、`web/app.js`、`web/app.css`
- 测试：
  - `tests/test_research_evidence_gateway.py`
  - `tests/test_http_entrypoint.py`

### 未完成 / v2

- 没有 production 级真实 PubMed 检索质量评估流程。
- 没有全文 PDF parser。
- 没有 production approval identity / permission / signature 系统。
- 没有真正点击后应用 controlled extension 的 UI。
- 不自动更新正式 skill，这是刻意安全边界，不是 bug。

### 下一步建议

这部分 v1 已经收敛，除非明确启动 production ingestion，否则暂缓：

```text
Research Ingestion v2：真实 PubMed review + production human approval。
范围：真实 query 质量、reviewer workflow、签名、审计。
边界：仍然不自动更新正式 skill。
```

## 支撑模块状态

### 前端

已完成：

- 主病例输入、影像发现、诊断报告、追问。
- Skill 版本对比。
- Research Evidence Review。
- 候选假设队列。
- Clinical/evidence/debug section。
- Agent 自动安全选择视觉链路，不再让用户手动选复杂模式。

未完成：

- protocol/debug 信息仍然偏密，需要继续做医生友好的折叠和摘要。
- 临床上下文、量化证据、controlled extension 审核可以继续做更清晰的 review UI。

### Memory / Audit

已完成：

- case memory、replay、evidence bundle、clinical context evidence、routing memory、runtime/audit、QA evidence-bound answer。

未完成：

- production human approval 的签名审计链还没有做。

### 真实数据 / ONFH COCO Evaluation

已完成：

- `scripts/onfh_coco_protocol_eval.py` 支持真实 ONFH package。
- 默认只评估 X-ray。
- 可以对比历史 finding-list baseline 和当前 evidence-protocol skill。
- 前端 Skill 对比会总结 coverage 和量化需求。

未完成：

- 不声明临床准确率。
- 没有 validated real segmentation / measurement benchmark。
- MRI 只是辅助发现新特征，不是当前 runtime 目标。

## 推荐下一轮 Goal 顺序

1. **Clinical Context Evidence v2**  
   最适合先做。它能让患者 prompt 中的病史和风险因素更自然地进入 evidence bundle。

2. **FHN X-ray Quantification / Measurement Protocol v2**  
   如果目标是让新版 evidence protocol 相比旧 finding-list 更明显、更可读，就做这个。

3. **Protocol Evidence 前端审核体验**  
   如果目标是演示和人工 review 更清楚，就先优化前端折叠、摘要和证据分组。

4. **Hypothesis Routing v2**  
   当前 v1 已经够 FHN workflow 使用，后面扩多疾病时再做。

5. **Research Ingestion v2**  
   除非明确要做 production paper ingestion 和 approval，否则先暂缓。

## 不建议重复打开的事项

- 不要重做 Research Evidence Ingestion v1。
- 不要重做 Clinical Hypothesis Routing v1。
- 不要把 PubMed / paper evidence 当成 guideline evidence。
- 如果产品方向是 X-ray，不要把 MRI 当成 runtime 测试主目标。
- 不要用 protocol coverage 或 demo artifact 声称临床验证。

## 已合并 / 删除的冗余文档

这些文档的有效信息已经合并到本文档和现有 current closure 文档中，后续不再单独维护：

- `docs/PROJECT_PROGRESS_SYNC_20260607.md`
- `docs/PRE_COMMIT_AUDIT_20260604.md`
- `docs/FHN_REAL_VLM_VALIDATION_20260604.md`
- `docs/plans/2026-06-04-real-vlm-multiview-validation.md`
- `docs/plans/2026-06-06-controlled-skill-extension-draft-v1.md`
- `docs/plans/2026-06-06-formal-skill-extension-patch-preview-v1.md`
- `docs/plans/2026-06-06-human-review-controlled-promotion-v1.md`

## 保留文档说明

这些文档仍然有独立价值或被测试/代码引用，不删除：

- `docs/API_ROUTE_LOG.md`：模型路由配置，代码和测试依赖。
- `docs/architecture/boundaries.md`：架构边界。
- `docs/AGENT_FLOW.zh-CN.md`：中文 Agent/流水线解释。
- `docs/DUAL_PATH_AGENT_FRAMEWORK.md`：双路径框架说明。
- `docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md`：FHN evidence protocol 历史阶段入口，被测试守护。
- `docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md`：当前 closure 边界，被测试守护。
- `docs/CURRENT_GOAL_COMPLETION_AUDIT_20260605.md`：closure audit，被测试守护。
- `docs/CURRENT_MVP_DEMO_RUNBOOK_20260605.md`：当前 demo runbook，被测试守护。
- `docs/datasets/brats_glioma_plan.md`：BraTS 数据计划。
- `docs/datasets/medsam2_runner_config.md`：MedSAM2 runner 配置。
- `docs/goal.md`：历史目标/方案说明，暂不删除。

## 验证基线

最近 Research Evidence Review ingestion 后完整验证：

```bash
python -m unittest
```

```text
Ran 483 tests in 63.926s
OK
```

格式检查：

```bash
git diff --check
```

```text
OK
```
