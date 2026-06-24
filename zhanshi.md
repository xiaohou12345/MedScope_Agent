Goal：MedScope Interactive Architecture & Optimization Roadmap Frontend v1

目标：

先不要改后端，优先审计现有前端结构，复用现有组件和路由。先给实现计划，确认后再改代码。

基于当前 Guideline-aware Evidence Pipeline 系统流程图，开发一个用于项目展示的前端页面。该页面用于向老师 / 组会 / 项目评审展示 MedScope 的整体架构、各模块职责、当前四个优化方向、TODO 状态和后续计划。

本轮目标不是修改诊断逻辑，不是改 VisionAgent，不是新增 Research Evidence 能力，而是做一个交互式前端展示层，让项目主线和优化方向更清晰可讲、可点、可展开。

背景：

当前系统流程图展示了 MedScope 的主架构：

- Clinical Orchestrator
- Vision Evidence Agent
- Diagnosis Reasoning Agent
- Knowledge Builder / Guideline Agent
- Memory & Audit Layer
- evidence_bundle 作为核心证据对象

目前我们希望先基于这张图做一个前端展示页面。后续我可能会重新生成更精细的系统图，再发给你基于新图继续拓展。因此本轮实现需要保持结构清晰、组件化、便于替换图片和扩展模块详情。

一、页面总体目标

实现一个 MedScope 架构展示页面，核心功能包括：

1. 展示系统主流程图；
2. 支持点击图中模块或旁边模块卡片查看详细说明；
3. 支持展示四个优化方向；
4. 每个优化方向可以展开查看：
   - 当前进度；
   - 已完成内容；
   - TODO；
   - 暂存 / 冻结内容；
   - 后续恢复条件；
   - 安全边界；
5. 支持 TODO 提示和状态标签；
6. 支持后续替换系统流程图图片；
7. 不影响现有诊断 / demo / backend 逻辑。

二、页面结构

建议新增一个前端页面，例如：

- `/architecture`
- `/project-roadmap`
- 或在现有 demo 页面中新增一个 tab：`Architecture / Roadmap`

页面分为几个区域：

1. 顶部项目标题区

展示：

- 项目名：MedScope
- 副标题：Guideline-aware Evidence Pipeline
- 简短说明：
  “核心不是堆叠多个 Agent，而是围绕 evidence_bundle 建立受医疗安全边界约束的临床证据流水线。”

1. 系统流程图展示区

展示当前上传的系统流程图图片。

要求：

- 图片宽度自适应；
- 支持缩放或点击查看大图；
- 后续方便替换图片；
- 图片下方显示一句说明：
  “该图展示 MedScope 当前主线：Clinical Orchestrator → Vision Evidence Agent → evidence_bundle → Diagnosis Reasoning Agent，并由 Memory & Audit Layer 记录全链路。”

1. 模块交互区

在流程图旁边或下方增加模块卡片。模块包括：

- Clinical Orchestrator
- Vision Evidence Agent
- Diagnosis Reasoning Agent
- Knowledge Builder / Guideline Agent
- Memory & Audit Layer
- evidence_bundle

点击每个模块时，右侧或弹窗展示详情。

每个模块详情至少包含：

- 模块定位；
- 输入；
- 输出；
- 不做什么；
- 当前完成状态；
- TODO / 后续优化。

示例内容：

Clinical Orchestrator：

- 定位：入口分诊、clinical hypothesis 生成、knowledge routing、流程协调。
- 输入：患者主诉、图像模态、部位、疾病线索。
- 输出：primary_hypothesis、selected_knowledge、differential_candidates、routing_reason。
- 不做：不直接诊断。
- TODO：后续可扩展 body-part + modality + symptom routing registry。

Vision Evidence Agent：

- 定位：把医学图像转成结构化视觉证据。
- 输入：raw_image、selected_knowledge、visual_protocol。
- 输出：visual_evidence、candidate mask、measurement、quality、completeness。
- 不做：不直接输出诊断。
- 当前限制：真实 X-ray 病灶定位、分割、量化仍不稳定。
- TODO：继续优化病灶候选定位、mask QC、ROI / contour / landmark、真实量化执行。

Diagnosis Reasoning Agent：

- 定位：只基于 evidence_bundle 和 guideline knowledge 生成 bounded diagnosis report。
- 输入：patient_info、selected_knowledge、evidence_bundle、guideline_rules。
- 输出：支持证据、缺失证据、非特异征象、诊断边界、建议。
- 不做：不直接看原图，不重新选 knowledge。
- TODO：继续验证在 annotation-derived evidence bundle 下的推理正确性。

Knowledge Builder / Guideline Agent：

- 定位：条件触发，缺少 knowledge 时检索指南并生成 candidate knowledge。
- 输入：disease / modality / guideline source。
- 输出：candidate knowledge、visual protocol、proposal artifact。
- 不做：不自动修改正式 guideline knowledge。
- TODO：保持 proposal-only 和 Evidence Gateway 安全边界。

Memory & Audit Layer：

- 定位：横向基础设施层，不是 Agent。
- 记录：patient memory、image memory、knowledge memory、reasoning memory、evidence bundle store。
- 作用：支持 replay、audit、QA 追溯。
- TODO：继续增强前端 audit 展示可读性。

evidence_bundle：

- 定位：核心证据对象。
- 内容：patient_context、visual_evidence、measurements、quality、missing_evidence、limitations、source trace。
- 作用：DiagnosisAgent 的唯一证据输入。
- TODO：继续完善 annotation-derived evidence bundle 和 clinical context 追溯。

三、四个优化方向展示区

增加一个 “Optimization Directions / 四个优化方向” 区域。

四个方向分别是：

1. Guideline Knowledge 结构扩展
2. 患者临床信息结合
3. 系统生成候选假设 / Knowledge Routing
4. 论文证据安全补充 Guideline Knowledge

每个方向做成可点击卡片或折叠面板。

每张卡片显示：

- 当前进度百分比；
- 状态标签；
- 简短说明；
- TODO 数量；
- 是否冻结 / 暂存 / 继续推进。

建议状态：

1. Guideline Knowledge 结构扩展
   - 进度：80-85%
   - 状态：v1 基本完成，v2 可继续
   - 已完成：
     - finding list → evidence protocol；
     - imaging evidence protocol；
     - quantitative evidence protocol；
     - differential protocol；
     - clinical context protocol；
     - integrated reasoning protocol；
     - 量化拆分为 image-feature quantification 和 geometric / morphologic measurement。
   - 当前限制：
     - 真实 ROI / contour / landmark / view quality gate 还主要是协议层；
     - 真实临床可靠测量引擎还未完成。
   - TODO：
     - 统一 schema / validator；
     - 继续沉淀通用 knowledge protocol 模板；
     - 未来接入 annotation-derived evidence bundle；
     - 等 VisionAgent 稳定后恢复 real X-ray case comparison。
2. 患者临床信息结合
   - 进度：70-80%
   - 状态：v1 已收敛，可做 v2
   - 已完成：
     - patient prompt / risk factors 进入 clinical context bundle；
     - risk factor 只能作为 suspicion modifier；
     - 不能替代影像证据确诊。
   - TODO：
     - 更结构化抽取疼痛部位、左右侧、持续时间、活动后加重；
     - 抽取激素使用、饮酒史、外伤史；
     - missing context 标记 unknown；
     - report / memory / QA 中显示来源和限制。
   - 注意：
     - 不做完整问诊系统；
     - 不做复杂风险评分模型。
3. 系统生成候选假设 / Knowledge Routing
   - 进度：80-85%
   - 状态：v1 完成，暂时不需要重做
   - 已完成：
     - 用户不明确说 FHN 时，可根据髋痛 + X-ray 生成 primary hypothesis；
     - 自动选择 FHN knowledge；
     - 保留 differential candidates；
     - 前端提示 routing 不是诊断结论。
   - TODO：
     - 统一 routing output 格式；
     - 轻量补 body-part + modality + symptom routing registry；
     - 未来可做 Differential Knowledge Run v1。
   - 当前不做：
     - 不做完整多疾病排序；
     - 不做多 knowledge 自动诊断；
     - 不自动运行所有 differential candidates。
4. 论文证据安全补充 Guideline Knowledge
   - 进度：85-90%
   - 状态：v1 收敛，暂时冻结
   - 已完成：
     - Research Evidence Builder；
     - Research Evidence Proposal；
     - PubMed metadata / abstract retrieval；
     - supplied metadata fallback；
     - Evidence Gateway；
     - source quality / freshness / applicability / conflict gate；
     - human review checklist；
     - controlled knowledge extension draft；
     - formal patch preview；
     - 前端 Research Evidence Review；
     - proposal-only；
     - formal_update=false。
   - 当前冻结：
     - 不做 production PubMed 检索质量评估；
     - 不做全文 PDF parser；
     - 不做正式人工审批系统；
     - 不做 knowledge registry 写入；
     - 不做真实 apply controlled extension。
   - 安全边界：
     - research evidence is not guideline evidence；
     - 不进入 diagnosis rules；
     - 不自动修改正式 knowledge。

四、TODO 面板

增加一个全局 TODO / Next Steps 面板，按优先级展示：

高优先级：

- Annotation-derived Evidence Bundle v1：
  使用已有 ONFH X-ray COCO / 人工标注生成结构化 evidence bundle，绕开 VisionAgent 自动分割不稳定问题，验证 DiagnosisAgent 在可靠 evidence 下的推理正确性。

中优先级：

- Clinical Context Evidence v2：
  进一步结构化患者症状、不良习惯、风险因素和缺失信息。

中低优先级：

- FHN X-ray Quantification / Measurement Protocol v2：
  等 ROI / contour / landmark / mask QC 更稳定后，再推进真实塌陷程度、坏死面积比例、骨小梁紊乱程度等量化执行。

暂存：

- Real X-ray Case Comparison：
  旧 finding-list knowledge vs 新 evidence-protocol knowledge 的病例级对比暂存，原因是 VisionAgent 真实定位、分割、量化还不稳定。

冻结：

- Research Evidence Ingestion production v2：
  论文证据 v1 已收敛，production PubMed/PDF/approval workflow 暂缓。

五、前端交互要求

1. 点击模块卡片，显示模块详情。
2. 点击四个优化方向卡片，显示该方向详细进度和 TODO。
3. TODO 支持状态标签：
   - done
   - in_progress
   - parked
   - frozen
   - deferred
4. 页面需要有较好的展示效果，适合组会讲解。
5. 默认不要堆 raw JSON。
6. 如有 debug 信息，放到折叠区。
7. 支持移动端基本可读。
8. 不影响现有 demo 页面。
9. 组件尽量复用现有前端风格。
10. 后续更换流程图图片时，不需要重写页面逻辑。

六、数据来源

本轮可以先使用前端静态数据或本地配置文件，不强制接后端。

建议新增一个配置文件，例如：

- frontend data file
- architectureRoadmap.ts
- architectureRoadmap.json

里面维护：

- modules
- optimizationDirections
- todos
- status labels
- progress values
- descriptions

后续如果需要，可以再改成从后端读取。

七、本轮不做

本轮不做：

1. 不改诊断逻辑；
2. 不改 VisionAgent；
3. 不训练模型；
4. 不新增真实 PubMed / PDF 功能；
5. 不修改 knowledge registry；
6. 不做 annotation-derived evidence bundle 的后端实现；
7. 不做 real X-ray old-vs-new comparison；
8. 不做新的多 knowledge differential diagnosis；
9. 不引入新的大后端模块；
10. 不改变现有测试通过状态。

八、测试要求

根据项目现有前端测试框架，尽量添加或更新测试：

1. Architecture / Roadmap 页面能渲染；
2. 系统流程图能显示；
3. 模块卡片能展开详情；
4. 四个优化方向能显示进度和状态；
5. TODO 面板能显示 done / parked / frozen / deferred 状态；
6. Research Evidence 方向显示 v1 收敛和冻结边界；
7. Real X-ray Case Comparison 显示 parked；
8. 页面不影响现有 demo 流程。

如果项目没有成熟前端测试，则至少保证构建通过、lint 通过、现有测试通过。

九、完成标准

本轮完成后需要满足：

1. 有一个可访问的 Architecture / Roadmap 前端页面或 tab；
2. 页面展示当前系统流程图；
3. 页面展示 6 个核心模块详情；
4. 页面展示四个优化方向的进度、状态、TODO 和限制；
5. 页面展示后续优先级和暂存 / 冻结项；
6. 用户可以点击模块或方向查看详情；
7. 页面适合组会展示；
8. 不影响现有诊断 demo；
9. 构建和测试通过；
10. 提交本轮改动。

本轮目标是先做项目展示前端，让系统架构、模块职责、四个优化方向、TODO 和后续路线更清晰可见。后续我可能会提供新的架构图图片，再基于该页面继续拓展。