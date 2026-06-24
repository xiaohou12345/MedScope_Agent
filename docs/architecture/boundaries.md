# MedScope MVP 架构边界

本文档用于固定当前阶段的模块边界，避免后续接真实模型、真实指南检索、前端或数据库时发生大工程重构。

当前对外推荐表述为“临床证据流水线”，而不是“五个并列 Agent”。实现代码中仍保留 `GaoDoctorAgent`、`VisionAgent`、`DiagnosisDoctorAgent`、`MemoryManager` 等类名用于审计和工程追踪，但汇报时应按医疗安全边界解释为：

1. 三个核心 Agent
   - `Clinical Orchestrator`：对应 `GaoDoctorAgent` 的入口、路由、患者解释和 QA 职责。
   - `Vision Evidence Agent`：对应 `VisionAgent` 的病灶定位、分割、测量、质量门控和结构化视觉证据输出。
   - `Diagnosis Reasoning Agent`：对应 `DiagnosisDoctorAgent` 的 guideline knowledge + evidence bundle 约束推理。
2. 一个条件触发组件
   - `Knowledge Builder / Guideline Component`：只有在缺少合适 knowledge、需要加载/生成 guideline knowledge、或进入 hypothesis 模式时才深入参与。
3. 一个基础设施层
   - `Memory / Audit Layer`：对应 `MemoryManager` 的四类 memory、evidence bundle、replay、audit，不应被讲成一个和诊断推理并列的业务 Agent。

在这条临床证据流水线之下，还可以补充一层 `Agentic Runtime / Evidence Gateway`。这层更接近 Claude Code / Codex 的工作方式：主 Agent 不直接把所有任务混在一个黑盒里，而是通过 gateway 管理 knowledge、文件、工具、约束和调用后的 hooks。

这层不是新的诊断 Agent，职责是：

- `Knowledge Gateway`：统一装载和分发 `knowledge/` 中的 guideline knowledge、hypothesis knowledge 和 visual protocol。
- `Shared File Workspace`：统一管理上传图像、mask、overlay、comparison、evidence bundle、audit 和 replay artifact。
- `Contract Guards`：按 `contracts/`、alignment plan、completeness 和 safety gate 限制输入输出。
- `Tool Router`：根据 knowledge 和模态选择指南采集、VLM prompt、MedSAM2、测量或 QC 工具。
- `Stop Hooks / Reflection Hooks`：每次调用后自动检查证据缺口、越权诊断、excluded fact 使用、memory 写入和下一步建议。
- `Self-evolving Queue`：只能生成候选规则、候选 knowledge patch 或待验证 memory，不能直接改写正式医疗指南。

因此当前架构可以分成两层来讲：

1. 上层是临床证据流水线，解释医疗职责和安全边界。
2. 底层是 Agentic Runtime / Evidence Gateway，解释 knowledge 分发、文件共享、hooks、自检和渐进式演化。

这个双层结构用于替代“五个 Agent 平铺”的汇报方式：

- `Clinical Orchestrator`、`Vision Evidence Agent`、`Diagnosis Reasoning Agent` 是真正承担临床任务流的核心 Agent。
- `Knowledge Builder / Guideline Component` 是条件触发组件：已有 knowledge 时只加载和校验；缺少 knowledge 时才检索指南、抽取规则、生成 knowledge。
- `Memory / Audit Layer` 是基础设施：保存四类 memory、evidence bundle、runtime trace 和 replay，不参与医学判断。
- `Agentic Runtime / Evidence Gateway` 是底层工作台：负责把 knowledge、文件 artifact、工具权限和 stop hooks 组织起来，让主链路可审计、可回滚、可逐步演化。

汇报时可以直接说明：代码里保留 `GaoDoctorAgent`、`VisionAgent`、`DiagnosisDoctorAgent`、`MemoryManager` 等实现名，是为了工程追踪；对外架构图应展示职责层次，而不是把所有类都画成同级业务 Agent。

## 1. 稳定分层

当前系统分为五层：

1. `contracts/`
   - 定义 Agent、Tool、Memory 之间传递的数据契约。
   - 后续新增真实视觉模型、真实指南检索、Web API 时，优先复用这里的输入输出结构。

2. `agents/`
   - `gaodoctor_agent.py`：Clinical Orchestrator 的当前实现，唯一患者入口，负责接收患者消息、图片路径、患者信息，调度 knowledge、视觉证据和诊断推理流程，并输出患者可读解释。
   - `diagnosis_agent.py`：Diagnosis Reasoning Agent 的当前实现，只处理结构化证据和疾病 Knowledge，不直接处理像素图片。
   - `vision_agent.py`：Vision Evidence Agent 的当前实现，只输出影像证据，不输出最终诊断。
   - `report_agent.py`：报告格式化实现，不作为主架构中的独立诊断 Agent 来汇报。

3. `tools/`
   - 放可替换工具，例如 guideline knowledge 加载、hypothesis knowledge 构建、视觉工具路由、分割和测量。
   - 后续真实指南检索、数据库统计、LLM 总结逻辑应放在这里或由这里包装。

4. `memory/`
   - 只负责保存和读取 case memory。
   - 当前实现为 JSON 文件；后续可替换为 SQLite/PostgreSQL，但对 Agent 暴露的字段不应大改。

5. `knowledge/`
   - 保存疾病 Knowledge。
   - `guideline_based` 和 `data_mined_hypothesis` 必须分清楚。

## 2. 不允许混淆的职责

- Clinical Orchestrator 不做图像分析，不直接下复杂医学结论。
- Diagnosis Reasoning Agent 不读原始像素，不生成 mask。
- Vision Evidence Agent 不输出 `diagnosis` 或 `diagnostic_tendency`。
- Knowledge Builder / Guideline Component 不替代诊断推理；它只负责把指南或假设转成 knowledge。
- Memory / Audit Layer 不参与医学判断；它只保存、回放和审计证据链。
- Agentic Runtime / Evidence Gateway 不产生医学结论；它只负责权限、文件、knowledge、工具路由、hooks 和审计。
- 无指南时不得伪装成正式指南，只能生成 `data_mined_hypothesis`，且 `evidence_level` 必须为 `low`，并带 warning。
- Memory 保存推理过程和证据，不只保存最终结论。
- Stop hooks 或 reflection hooks 不能直接修改正式 `guideline_based` knowledge；只能生成候选更新，等待验证和确认。

## 3. 关键契约

核心契约在 `contracts/medical_contracts.py`：

- `PatientCaseInput`：患者入口请求。
- `VisualEvidence`：视觉证据，不允许包含最终诊断字段。
- `VisualAnalysisResult`：Vision Evidence Agent 到 Diagnosis Reasoning Agent 的完整结构化结果。
- `KnowledgeDescriptor`：写入 Memory 和 Report 的 Knowledge 摘要，强制区分 guideline/hypothesis。

后续新增模块时，应先判断它输入输出对应哪个契约；如果需要扩字段，优先向契约添加兼容字段，而不是在 Agent 内部随意新造 dict。

## 4. 后续替换点

### 接真实视觉模型

只替换 `VisionAgent.analyze_image()` 内部实现，输出仍保持 `VisualAnalysisResult.to_dict()`：

- 输入：`image_path` + `disease_knowledge`
- 输出：`visual_evidence`
- 禁止输出最终诊断

### 接真实指南检索

扩展 `KnowledgeBuilderTool`：

- 有正式指南：生成 `guideline_based` knowledge
- 没有正式指南：生成 `data_mined_hypothesis` knowledge
- 不改 `DiagnosisDoctorAgent.generate_report()` 的主流程

### 接数据库 Memory

替换 `MemoryManager` 的存储后端，但保持：

- `save_case_memory(...)`
- `load_case_memory(case_id)`
- `patient_memory`
- `image_memory`
- `knowledge_memory`
- `reasoning_memory`

### 接前端或 API

前端/API 层只调用 `GaoDoctorAgent.handle_patient_case()` 或封装同等 payload，不绕过 Clinical Orchestrator 直接调诊断或视觉实现节点。

### 接 Runtime Gateway / Stop Hooks

优先新增一个轻量 runtime manifest 和 stop hook gate，而不是重构现有 Agent：

- manifest 记录本轮 `case_id`、knowledge、artifact、tool call、contract check、memory 写入和证据缺口。当前已通过 `MemoryManager.build_runtime_manifest(case_id)` 实现最小版本，并暴露到 service response。
- stop hook 读取 response、evidence bundle、memory audit 和 replay，输出 warning、next action、candidate patch。当前已通过 `MemoryManager.build_stop_hook_gate(case_id)` 实现最小只读版本，并暴露到 service response。
- self-evolving queue 读取 stop hook gate，把 warning 转成候选记忆、候选规则或 candidate knowledge patch。当前已通过 `MemoryManager.build_self_evolving_queue(case_id)` 实现最小候选队列，并暴露到 service response。
- candidate validation gate 读取 self-evolving queue，检查候选项是否满足审核与验证要求。当前已通过 `MemoryManager.build_candidate_validation_gate(case_id)` 实现最小只读验证门，并暴露到 service response。
- runtime gateway trace 汇总以上四段 artifact，形成面向演示和审计的一条 gateway 执行轨迹。当前已通过 `MemoryManager.build_runtime_gateway_trace(case_id)` 实现最小总览，并暴露到 service response；trace 内含 `trace_consistency`，检查 artifact 路径、schema 和 stage 顺序。
- stop hook 的输出默认进入 `output/fake/` 或 case memory。
- stop hook 不允许直接修改 `knowledge/`、诊断报告或 guideline source。

第一版只做审计和建议，不做自动执行：

```text
case response
  -> runtime_gateway_trace(summary)
  -> runtime manifest
  -> stop hook check
  -> runtime_warnings / next_actions
  -> self_evolving_queue(candidate_memory / candidate_rule / candidate_knowledge_patch)
  -> candidate_validation_gate(blocked unless reviewed/validated)
  -> 等待验证或人工确认
```

后续如果要把候选项升级为正式 knowledge，必须通过验证门：

- 候选规则必须关联 source case。
- 候选规则必须保留 warning 来源和 evidence。
- 候选规则必须有 validation status，默认只能 `candidate_review_only`。
- validation gate 默认阻断未审核候选项。
- 升级正式 knowledge 前必须保留版本和回滚路径。

## 5. 当前验证命令

```bash
python -m unittest discover -v
python app.py --image data/images/demo_xray.png --message 左髋疼痛三个月 --risk-factor 饮酒史
```
