# MedScope 双路径医疗 Agent 框架

## 目标定位

MedScope 当前目标已收敛为面向股骨头坏死（ONFH）的专病筛查、证据分析和分期辅助系统。系统不再对外表述为“从所有疾病中自动判断患者患了什么病”的通用诊断系统；它首先围绕 ONFH 的指南 Knowledge、髋关节影像证据、风险因素、鉴别复查和分期边界建立一条可审计的临床证据流水线。

底层 Knowledge / Evidence Gateway 仍保留可扩展设计，但这属于后续研究扩展能力，不是当前产品主张。胶质瘤、肺炎、IPF 等 Knowledge 仅作为架构验证或技术样例，不作为全病种临床诊断能力声明。

髋关节相关的非 ONFH Knowledge 应被定义为 `differential review knowledge` 或 `false-positive suppressor knowledge`：它们的任务不是和 ONFH 主线并列做多病种自动诊断，而是在 ONFH 支持度较高、证据不足或征象不特异时，检查骨关节炎、外伤后改变、DDH 相关退变等替代解释是否更合理。最终报告应同时输出 ONFH 支持度、替代解释强度、假阳性风险和建议补充检查。

本文档区分三类状态：

- 已实现：当前代码和测试已经验证的能力。
- 正在实现：已有部分契约或雏形，但还未形成完整闭环的能力。
- 规划中：论文或项目愿景中的研究方向，不能在汇报中表述为已完成。

## 对外汇报口径：双层架构

当前不建议把 MedScope 讲成“五个并列 Agent”。更准确、也更容易回应质疑的说法是：

```text
上层：Clinical Evidence Pipeline
  Clinical Orchestrator
    -> Vision Evidence Agent
    -> Diagnosis Reasoning Agent
  条件触发：Knowledge Builder / Guideline Component
  基础设施：Memory / Audit Layer

下层：Agentic Runtime / Evidence Gateway
  Knowledge Gateway
  Shared Artifact Workspace
  Contract / Policy Guards
  Tool Router
  Stop Hooks / Reflection Hooks
  Self-evolving Queue
  Candidate Validation Gate
```

一句话版本：

> MedScope 不是为了分 Agent 而分 Agent，而是把 ONFH 专病筛查、影像证据分析和分期辅助拆成一条受指南约束的证据流水线，并在底层引入类似 Claude Code / Codex 的 agentic runtime，通过 knowledge 分发、文件 artifact 共享、工具约束、stop hooks、memory audit 和候选规则验证门，让每次推理都可追踪、可复核、可回滚。

如果老师质疑“五个 Agent 像是为了分而分”，建议直接把重点从 Agent 数量转到 runtime 机制：

> 五个实现类不是论文贡献点，它们只是当前 MVP 的 worker 拆分。真正的结构贡献是 Evidence Gateway：主 Agent 不直接持有所有医学能力，而是通过 gateway 装载 medical knowledge、分发共享文件、限制工具权限、检查 evidence contract，并在每次调用后通过 stop hooks 生成可复核的候选改进。这样系统可以换病种、换视觉模型、换指南来源，而不用重写临床主链路。

这套口径解决两个问题：

- 医疗安全边界：ONFH 图像观察、指南加载、诊断推理和审计记忆不能混在一个黑盒里，否则错误难以定位。
- 工程可扩展性：新的 ONFH 鉴别知识、新视觉模型、新指南来源和新验证规则应接入 knowledge/tool/runtime 层，而不是重构临床主链路。

因此，`Knowledge Builder` 和 `MemoryManager` 不应被讲成始终并列的业务诊断 Agent。它们分别属于条件触发的 guideline/knowledge 组件和底层 audit/runtime 基础设施。

## Agentic Runtime / Evidence Gateway

在“临床证据流水线”之下，还可以抽象出一层类似 Claude Code / Codex 的 agentic runtime。它不是新的医疗诊断 Agent，而是让主 Agent 能精细化管理 knowledge、文件、上下文、工具和执行后自检的底层 gateway。

这一层可以这样解释：

```text
Clinical Orchestrator
  -> Evidence Gateway / Agentic Runtime
       -> Knowledge Registry / Knowledge Builder
       -> Shared File Workspace
       -> Contract & Policy Guards
       -> Tool Router
       -> Stop Hooks / Reflection Hooks
       -> Memory & Audit Store
  -> Vision Evidence Agent
  -> Diagnosis Reasoning Agent
```

核心机制：

- `Knowledge Registry / Knowledge Gateway`：统一管理 guideline knowledge、hypothesis knowledge、visual_protocol 和版本信息。主 Agent 不直接把自然语言塞给下游，而是分发经过约束的 knowledge。
- `Shared File Workspace`：统一保存上传图片、mask、overlay、comparison、evidence bundle、memory replay 和审计文件。Agent 之间共享文件路径和结构化 artifact，而不是互相传大段不可审计上下文。
- `Contract & Policy Guards`：通过 `contracts/`、alignment plan、completeness、safety gate 限制每个 Agent 能读什么、能输出什么、不能越权生成什么。
- `Tool Router`：根据 knowledge 的 visual protocol 和输入图像模态选择 VLM prompt、MedSAM2、测量工具或指南采集工具。
- `Stop Hooks / Reflection Hooks`：每次调用后做自检，例如检查证据是否缺失、mask 是否可用、诊断是否引用了 excluded fact、是否需要补充影像、是否需要更新 memory。
- `Memory & Audit Store`：把 patient/image/knowledge/reasoning 四类 memory 和 QA 历史写回，形成下一轮调用可复用的上下文。

更具体地说，底层 gateway 把一次病例调用拆成五类可控资源，而不是让多个 Agent 自由聊天：

| Gateway 资源 | 管理对象 | 约束方式 | 当前系统中的证据 |
| --- | --- | --- | --- |
| Knowledge 系统 | guideline knowledge、hypothesis knowledge、visual protocol、版本与来源 | `knowledge_type`、`path_type`、quality gate、validation gate | `knowledge/`、`KnowledgeBuilderTool`、visual protocol validator |
| 文件共享 | 上传图像、mask、overlay、comparison、evidence bundle、audit、replay | 只传路径和结构化 artifact，不把大段上下文口头转述 | `output/fake/`、case memory、frontend artifact route |
| 工具分发 | VLM prompt、MedSAM2、测量工具、指南采集工具 | 按 knowledge 和模态路由，输出必须回到契约字段 | `VisualToolRouter`、segmentation/measurement tools |
| 契约守卫 | completeness、alignment plan、excluded fact、safety gate | 缺失证据不能写成阴性，候选证据不能直接进入正式诊断 | `contracts/`、diagnosis validation、QA guard |
| Hooks 与演化 | runtime warnings、candidate memory、candidate rule、candidate knowledge patch | stop hook 只读，self-evolving 只进候选队列，formal update 默认阻断 | `runtime_manifest`、`stop_hook_gate`、`self_evolving_queue`、`candidate_validation_gate` |

这层 runtime 的价值是把“多 Agent 协作”从简单串联变成可约束、可复用、可审计的工作台：主 Agent 负责分发任务和文件，底层 gateway 负责限制权限、装载 knowledge、路由工具、记录结果，并在调用结束后触发自检。

和 Claude Code / Codex 的类比只用于解释工程机制，不表示系统依赖某个具体产品：

- Claude Code / Codex 通过工作目录、工具权限、技能文件和 hooks 管理编码任务。
- MedScope 通过 case workspace、medical knowledge、视觉工具、evidence contract 和 stop hooks 管理诊疗证据任务。
- 两者相同点是“主 Agent 不直接持有所有能力，而是通过 gateway 装载 knowledge、分发文件、约束工具和记录执行轨迹”。
- MedScope 的额外要求是医疗安全：runtime 不能自动把候选经验升级为正式诊疗规则。

需要注意安全边界：所谓 self-evolving 不能直接自动改写正式医疗指南。更稳妥的做法是：

- 每次运行后通过 hooks 生成 `candidate_memory`、`candidate_rule` 或 `candidate_knowledge_patch`。
- 候选内容先进入 `output/fake/` 或低证据 memory，不进入正式 `knowledge/`。
- 只有经过验证、人工确认或数据集评测后，才能提升为 `guideline_based` knowledge 或写入 `output/real/`。
- 对临床规则的“自我演化”必须保留来源、版本、证据等级、验证记录和回滚路径。

### Runtime 落地路线

为了避免把 gateway 讲成空概念，后续可以按四个阶段落地：

当前已补充一个汇总入口：`MemoryManager.build_runtime_gateway_trace(case_id)` 会把 `runtime_manifest`、`stop_hook_gate`、`self_evolving_queue` 和 `candidate_validation_gate` 串成 `runtime_gateway_trace.v1`，写入 `output/fake/runtime_gateway_trace/`，并由 service response 暴露为 `runtime_gateway_trace` / `runtime_gateway_trace_path`。前端 Evidence Pipeline Trace 已能展示 Runtime Gateway Trace 摘要。这个总览用于汇报“底层 gateway 如何管理 knowledge、文件、hooks、候选学习和验证门”，不是新的诊断 Agent。当前 trace 已包含 `trace_consistency`，用于检查四段 artifact 是否存在、schema 是否齐全、stage 顺序是否完整。

#### Phase 1：Runtime Manifest

目标：每次病例运行后生成一份机器可读的 runtime manifest，说明本轮调用使用了哪些 knowledge、文件 artifact、工具、契约和 memory。

当前状态：已实现最小闭环。`MemoryManager.build_runtime_manifest(case_id)` 会从 case memory 生成 `runtime_manifest.v1`，写入 `output/fake/runtime_manifest/`，并由 service response 暴露为 `runtime_manifest` / `runtime_manifest_path`。前端 Evidence Pipeline Trace 已能展示 Runtime Manifest 摘要。

最小字段：

- `case_id`
- `selected_knowledge`
- `knowledge_version`
- `input_artifacts`
- `generated_artifacts`
- `tool_calls`
- `contracts_checked`
- `memory_written`
- `blocked_or_missing_evidence`

验收口径：

- manifest 只写入 `output/fake/` 或 case memory。
- manifest 能解释“为什么选这个 knowledge、为什么调用这些工具、哪些证据缺失”。
- manifest 不生成医学结论，只记录执行事实。

#### Phase 2：Stop Hook Gate

目标：每次主链路结束后运行 stop hook，自检 evidence bundle 和诊断报告是否越界。

当前状态：已实现最小只读 gate。`MemoryManager.build_stop_hook_gate(case_id)` 会读取 runtime manifest、evidence bundle 和 case memory，输出 `stop_hook_gate.v1`，写入 `output/fake/stop_hook_gate/`，并由 service response 暴露为 `stop_hook_gate` / `stop_hook_gate_path`。前端 Evidence Pipeline Trace 已能展示 Stop Hook Gate 摘要。

最小检查：

- Diagnosis 是否引用了 `excluded` visual fact。
- 是否把 missing / unassessed 证据写成阴性。
- 是否缺少 `patient_memory / image_memory / knowledge_memory / reasoning_memory`。
- 是否需要建议补充影像或人工复核。
- 是否生成候选规则或候选 knowledge patch。

验收口径：

- hook 只能输出 `runtime_warnings`、`next_actions`、`candidate_memory`、`candidate_knowledge_patch`。
- hook 不能自动修改正式 `knowledge/`。
- hook 不能覆盖诊断报告，只能标记风险和建议。
- 当前实现遵守只读边界：`read_only=true`、`formal_knowledge_updated=false`、`diagnosis_report_updated=false`。后续候选队列由独立的 `self_evolving_queue` 步骤写入，不由 stop hook 直接修改正式资源。

#### Phase 3：Self-evolving Queue

目标：把多次病例中重复出现的经验沉淀为候选规则队列，而不是直接写入正式指南。

当前状态：已实现最小候选队列。`MemoryManager.build_self_evolving_queue(case_id)` 会读取 Stop Hook Gate，把 warning / next action 转成 `candidate_memory`、`candidate_rule` 或 `candidate_knowledge_patch`，写入 `output/fake/self_evolving_queue/`，并由 service response 暴露为 `self_evolving_queue` / `self_evolving_queue_path`。前端 Evidence Pipeline Trace 已能展示 Self-evolving Queue 摘要。

最小字段：

- `item_id`
- `source_warning_code`
- `candidate_type`
- `proposal`
- `evidence`
- `validation_status`
- `allowed_action`
- `formal_update_allowed`

验收口径：

- 默认 `validation_status=pending_review`。
- 默认 `allowed_action=candidate_review_only`。
- 默认 `formal_update_allowed=false`。
- 只有通过真实数据评测、指南来源确认或人工审核后，才能升级正式 knowledge。
- 所有升级必须有版本号、来源和回滚路径。

#### Phase 4：Candidate Validation Gate

目标：在 candidate queue 和正式 knowledge 之间增加验证门，避免候选规则被误当成已验证医学知识。

当前状态：已实现最小只读验证门。`MemoryManager.build_candidate_validation_gate(case_id)` 会读取 `self_evolving_queue.v1`，检查每个候选项是否具备 warning 来源、proposal、evidence、验证状态和正式升级许可，写入 `output/fake/candidate_validation_gate/`，并由 service response 暴露为 `candidate_validation_gate` / `candidate_validation_gate_path`。前端 Evidence Pipeline Trace 已能展示 Candidate Validation Gate 摘要。

最小字段：

- `source_queue_path`
- `item_validations`
- `promotion_decision`
- `review_requirements`
- `runtime_safety`

验收口径：

- 未经人工、指南来源或数据集验证的候选项默认 `promotion_decision.status=blocked`。
- 默认 `formal_update_allowed=false`。
- validation gate 不修改正式 `knowledge/`、guideline source 或诊断报告。
- 只有 item 具备 validated/approved 状态和明确 formal update 许可时，才允许进入后续人工 promotion 流程。

## 双路径机制

### Guideline-Aware Path

适用场景：已有成熟临床指南、诊疗边界较清晰的疾病或任务。

当前已实现能力：

- `guideline_based` Knowledge。
- 自动 Knowledge 路由契约 `routing_decision`。
- Vision Agent 输出 `VisualAnalysisResult`，不做最终诊断。
- Diagnosis Agent 只消费结构化视觉证据和 Knowledge。
- `visual_input_contract` 记录诊断 Agent 实际收到的视觉输入。
- `completeness` 字段用于阻止缺失证据被解释为 0 或阴性。
- BraTS 胶质瘤 HTTP 端到端样例验证。

### Privileged Knowledge Discovery Path

适用场景：临床上存在早期预警或发现需求，但尚无成熟影像学指南的病变。

当前已实现能力：

- `data_mined_hypothesis` Knowledge 类型。
- `path_type=privileged_knowledge_discovery`。
- `safety_gate`，限制 hypothesis knowledge 的输出范围。
- `hypothesis_validation_mode` 显式开关，默认关闭。
- 默认关闭时，Diagnosis Agent 会拒绝使用 hypothesis knowledge 生成诊断报告。
- 显式开启时，只能输出科研假设风险提示、金标准检查建议和不确定性说明。

正在实现能力：

- 用 mock/evidence summary 生成 `fhn_stage1_hypothesis` 类候选 Knowledge。
- 将 discovery knowledge 作为科研预警链路而非临床诊断链路。

规划中能力：

- LUPI 特权信息学习。
- 多模态知识蒸馏。
- MRI/CT 金标准标签到 X 光低成本影像的特征对齐。
- 由真实多模态数据生成经过验证的 `fhn_stage1_hypothesis.yaml`。

## 临床证据流水线职责边界

当前对外表述不再强调“五个并列 Agent”。更准确的结构是：

- 三个核心 Agent：Clinical Orchestrator、Vision Evidence Agent、Diagnosis Reasoning Agent。
- 一个条件触发组件：Knowledge Builder / Guideline Agent。
- 一个基础设施层：Memory & Audit Layer。

这种拆分依据是医疗安全边界，而不是为了增加 Agent 数量：谁负责入口与路由，谁负责看图取证，谁负责指南和 knowledge，谁负责诊断推理，谁负责审计追溯。

### GaoDoctor / Orchestrator Agent

核心 Agent。负责患者入口、意图分类、自动 Knowledge 路由、下游协调和多轮 QA。

已实现：

- 自动选择已有 Knowledge。
- 返回 `routing_decision`。
- 把 `hypothesis_validation_mode` 从 API 传递到 Diagnosis Agent。

### Knowledge Builder Agent

条件触发组件。负责加载、生成和持久化 Knowledge。有现成 knowledge 时主要是加载和校验；缺少 knowledge 时才进入指南检索、指南抽取和 knowledge 生成。

已实现：

- 有指南时生成或加载 `guideline_based` Knowledge。
- 无指南时生成 `data_mined_hypothesis` Knowledge。
- hypothesis Knowledge 强制携带 warning、low evidence、discovery metadata 和 safety gate。

未实现：

- 从真实 LUPI/蒸馏结果自动生成可验证的新 Knowledge。

### Vision Agent

核心 Agent。负责按 Knowledge 中的视觉协议提取结构化证据。

已实现：

- 输出 `image_outputs`、`visual_evidence`、`measurements`、`completeness`。
- 对胶质瘤样例支持 ground-truth mask 路径和 MedSAM2 路径。

### Diagnosis Agent

核心 Agent。负责严密契约推理，不触碰原始像素。

已实现：

- 强制解析 `VisualAnalysisResult`。
- 附带 `visual_input_contract`。
- 对 guideline Knowledge 输出诊断报告。
- 对 hypothesis Knowledge 默认阻断。
- 仅在 `hypothesis_validation_mode=True` 时输出科研预警。

### Memory & Audit Layer

基础设施层，不作为诊断 Agent。负责 patient/image/knowledge/reasoning/QA 记忆、evidence bundle、audit 和 replay。

已实现：

- 保存病例、视觉证据、Knowledge 摘要、推理结果和 QA 记录。

## Knowledge Schema 边界

### Guideline Knowledge

关键字段：

- `knowledge_type=guideline_based`
- `path_type=guideline_aware`
- `evidence_level=high`
- `source_type=medical_guideline`
- `vision_agent_tasks`
- `report_requirements`

允许输出：

- 结构化诊断倾向。
- 指南约束下的不确定性说明。
- 进一步检查和治疗建议。

### Hypothesis Knowledge

关键字段：

- `knowledge_type=data_mined_hypothesis`
- `path_type=privileged_knowledge_discovery`
- `evidence_level=low`
- `source_type=internal_dataset_summary`
- `warning`
- `candidate_observation_rules`
- `visual_protocol`
- `evidence_completeness_matrix`
- `safety_gate`
- `discovery_metadata`

默认行为：

- 不允许进入临床诊断报告生成。

开启条件：

- 必须显式传入 `hypothesis_validation_mode=True`。

允许输出：

- early_risk_alert
- research_warning
- recommend_gold_standard_confirmation

禁止输出：

- 确诊。
- 正式指南结论。
- 指南推荐。
- 阴性排除。

## 当前验证状态

当前测试覆盖了：

- guideline/hypothesis Knowledge 边界。
- hypothesis Knowledge 默认阻断。
- hypothesis validation mode 开启后的科研预警输出。
- Vision -> Diagnosis 输入契约。
- HTTP 端到端 BraTS 样例。
- MedSAM2 readiness 错误提示。

尚未验证：

- 真实 LUPI 训练。
- 真实多模态蒸馏。
- 真实 `fhn_stage1_hypothesis.yaml` 由数据自动生成。
