# MedScope Agent 功能边界与主线/支线流程

本文档用于把 MedScope 当前项目从“几个 Agent 的堆叠”整理成一条可讲清楚、可演示、可扩展的 ONFH 专病系统主线。

推荐对外表述：

> MedScope 不再定位为全病种自动诊断系统，而是面向股骨头坏死（ONFH）的专病筛查、证据分析和分期辅助系统。它把 ONFH 影像证据分析拆成一条受 guideline knowledge、visual evidence、evidence bundle 和 memory audit 约束的临床证据流水线。每个 Agent 只负责一个安全边界内的工作，底层 Evidence Gateway 负责 knowledge、文件、工具、契约、hooks 和 candidate queue 的统一管理。

其他髋关节 Knowledge 的定位是鉴别复查和假阳性控制：当 ONFH Knowledge 发现硬化带、囊性变、塌陷或新月征等支持证据时，系统可以调用骨关节炎、外伤后改变、DDH 相关退变等 Knowledge 检查这些阳性征象是否存在替代解释。这样做的目标不是扩大成全病种诊断，而是降低 ONFH 假阳性。

## 1. 总体结构

```text
患者 / 前端 / API
  -> Clinical Orchestrator
  -> Knowledge Gateway / Knowledge Builder
  -> Vision Evidence Agent
  -> Diagnosis Reasoning Agent
  -> Memory / Audit Layer
  -> Follow-up QA / Runtime Trace / Candidate Queue
```

从实现上看，项目里有多个类和工具；从系统设计上看，建议分成三层：

```text
第一层：用户入口层
  Web Frontend
  HTTP API
  CLI

第二层：临床证据流水线
  Clinical Orchestrator
  Knowledge Gateway / Knowledge Builder
  Vision Evidence Agent
  Diagnosis Reasoning Agent
  Memory / Audit Layer

第三层：Agentic Runtime / Evidence Gateway
  Knowledge Registry
  Shared Artifact Workspace
  Tool Router
  Contract Guards
  Stop Hooks
  Self-evolving Candidate Queue
  Candidate Validation Gate
```

这三层解决的问题不同：

- 用户入口层解决“怎么把图片、描述、追问传进系统”。
- 临床证据流水线解决“怎么把病例处理成可解释报告”。
- Evidence Gateway 解决“怎么让多 Agent 协作可控、可审计、可回滚、可扩展”。

## 2. 各 Agent / 组件功能说明

### 2.1 Clinical Orchestrator

对应代码：

- `agents/gaodoctor_agent.py`
- `api/service.py`

它是整个系统的唯一主入口。患者、前端、API、CLI 都不应该绕过它直接调用诊断 Agent 或视觉 Agent。

核心职责：

- 接收患者描述、图像路径、患者信息、case id。
- 判断用户意图：新诊断、复查、报告解释、follow-up QA。
- 根据描述、症状、图像路径和显式参数生成 `routing_decision`。
- 决定当前病例应该使用哪个 disease knowledge。
- 调用 alignment planner 判断“当前图像 + 当前 knowledge 是否匹配”。
- 调用 Vision Evidence Agent 生成视觉证据。
- 调用 Diagnosis Reasoning Agent 生成诊断报告。
- 调用 Memory / Audit Layer 保存四类 memory 和审计产物。
- 对患者输出简化后的解释。

它不应该做的事：

- 不直接读像素、圈病灶或生成 mask。
- 不直接替代诊断 Agent 下医学结论。
- 不直接写 provider-specific API 调用。
- 不直接把候选经验升级成正式医学 knowledge。

输入：

```json
{
  "patient_message": "请评估这张髋关节 X 光",
  "image_path": "...",
  "patient_info": {
    "age": 45,
    "sex": "male",
    "symptoms": ["髋关节疼痛"]
  },
  "case_id": null,
  "disease_key": null,
  "vision_mode": null
}
```

输出：

- `case_id`
- `routing_decision`
- `alignment_plan`
- `image_outputs`
- `visual_evidence_bundle`
- `report`
- `memory_audit`
- `runtime_gateway_trace`
- `reply_to_patient`

一句话：

> Clinical Orchestrator 是“总控医生”，负责问诊入口、路由、调度和患者解释，但不直接看图、不直接分割、不直接脑补诊断。

### 2.2 Knowledge Gateway / Knowledge Builder

对应代码：

- `tools/knowledge_builder_tool.py`
- `tools/guideline_search_tool.py`
- `tools/guideline_extraction_tool.py`
- `tools/guideline_source_collector_tool.py`
- `tools/guideline_source_import_tool.py`
- `knowledge/*.yaml`

它负责管理疾病知识，不负责最终诊断。

核心职责：

- 从 `knowledge/` 加载已有 disease knowledge。
- 检查 knowledge 是 `guideline_based` 还是 `data_mined_hypothesis`。
- 读取 knowledge 中的 `visual_protocol`，告诉视觉 Agent 需要观察什么。
- 读取 knowledge 中的 `staging_rules`、`required_image_views`、`source_documents`，告诉诊断 Agent 可用的指南依据。
- 在缺少 knowledge 时，通过指南来源采集和抽取工具生成新的 guideline knowledge。
- 当找不到正式指南时，只能生成 `data_mined_hypothesis`，不能伪装成医学指南。
- 保存医生 review draft，但不自动改正式 knowledge。

它不应该做的事：

- 不直接看原始医学图像。
- 不直接生成诊断报告。
- 不把数据挖掘结果伪装成正式指南。
- 不绕过 validation gate 自动修改正式 knowledge。

Knowledge 中最关键的字段：

```json
{
  "disease_name": "股骨头坏死",
  "knowledge_type": "guideline_based",
  "evidence_level": "high",
  "source_documents": [],
  "clinical_features": {},
  "required_image_views": [],
  "staging_rules": {},
  "visual_protocol": {
    "finding_targets": [],
    "required_next_images": [],
    "insufficiency_rules": []
  }
}
```

一句话：

> Knowledge Gateway 是“指南和技能管理层”，负责把疾病指南变成可执行的 visual protocol 和 reasoning constraints。

### 2.3 Vision Evidence Agent

对应代码：

- `agents/vision_agent.py`
- `tools/visual_tool_router.py`
- `tools/vision_prompt_generator.py`
- `tools/medsam2_segmentation_tool.py`
- `tools/generic_mask_measurement_tool.py`
- `tools/visual_quality_gate.py`
- `scripts/no_mask_knowledge_visual_pipeline_demo.py`
- `scripts/no_mask_vision_prompt_demo.py`
- `scripts/no_mask_medsam2_segmentation_demo.py`

它是“可编程影像证据提取器”，不是诊断医生。

核心职责：

- 读取 disease knowledge 的 `visual_protocol`。
- 判断当前图像模态是否满足该 knowledge 的要求。
- 对每个 finding target 决定执行模式：
  - `vlm_only`：只做视觉观察，不生成 mask。
  - `vlm_plus_segmenter`：VLM 先给候选位置，再用 MedSAM2 等模型分割。
  - `measurement_only`：只做形态或数值测量。
  - `specialist_segmenter`：后续可接专病分割模型。
  - `insufficient_input`：当前影像不足，不能执行。
- 输出原图、mask、overlay、按征象分开的局部图。
- 输出结构化 finding、region、bbox、area、ratio、confidence、quality warning。
- 标记哪些视觉证据可以用于诊断，哪些只能作为候选或需要人工复核。
- 对缺失模态明确写入 `completeness`，例如“需要 MRI T1ce，当前缺失”。

它不应该做的事：

- 不输出最终诊断。
- 不把 VLM 候选框当作确定病灶。
- 不把 MedSAM2 生成的 mask 自动当作高质量医学分割。
- 不把缺失模态解释成阴性。

Vision Agent 的标准输出：

```json
{
  "image_outputs": {
    "original_image_path": "...",
    "mask_path": "...",
    "overlay_path": "...",
    "target_overlay_paths": {
      "sclerotic_band": "..."
    }
  },
  "visual_evidence": {
    "disease_target": "femoral_head_necrosis",
    "findings": [],
    "structured_visual_facts": [],
    "measurements": {},
    "completeness": {},
    "segmentation_quality": "candidate",
    "quality_warnings": []
  }
}
```

一句话：

> Vision Evidence Agent 的任务不是“诊断有没有病”，而是根据 knowledge 把图像中可观察、可分割、可测量、可缺失的证据整理成结构化证据包。

### 2.4 Diagnosis Reasoning Agent

对应代码：

- `agents/diagnosis_agent.py`
- `prompts/diagnosis_agent_prompt.md`
- `tools/structured_visual_fact_builder.py`

它是“证据约束推理器”，不是视觉模型。

核心职责：

- 读取 disease knowledge。
- 读取 Vision Agent 输出的 `VisualAnalysisResult`。
- 生成 `visual_input_contract`，明确诊断 Agent 实际收到哪些视觉字段。
- 区分：
  - 已支持证据。
  - 缺失证据。
  - 未评估证据。
  - 被 quality gate 排除的证据。
  - 重叠、非独立、不可诊断使用的视觉 fact。
- 生成诊断报告：
  - 诊断倾向。
  - 影像依据。
  - 分期判断。
  - 不确定性说明。
  - 建议进一步检查。
  - 治疗建议。
- 如果启用 LLM，则用 prompt runner 生成报告；如果 LLM 输出不合格，则 fallback 到规则报告。
- 拒绝 LLM 把 missing/null 写成 0、阴性或“未见异常”。

它不应该做的事：

- 不读取原始图像。
- 不生成 mask。
- 不根据自己想象补全视觉证据。
- 不把候选 finding 当作已经验证的事实。
- 不在缺少必要影像时给出过度确定的诊断。

一句话：

> Diagnosis Reasoning Agent 只吃 evidence bundle，不看原图；它的价值是低幻觉、可追踪、可解释的指南约束推理。

### 2.5 Memory / Audit Layer

对应代码：

- `memory/memory_manager.py`
- `data/cases/`
- `output/fake/runtime_manifest/`
- `output/fake/stop_hook_gate/`
- `output/fake/self_evolving_queue/`
- `output/fake/candidate_validation_gate/`
- `output/fake/runtime_gateway_trace/`

它是系统的证据链和审计底座。

四类 memory：

#### patient_memory

保存患者入口信息：

- `case_id`
- `patient_id`
- `patient_message`
- `patient_info`
- `symptoms`
- `intent`
- `qa_history`

作用：

- 让系统知道这次病例来自谁、问了什么、症状是什么。
- 支持后续 follow-up QA。
- 支持复查和病例回放。

#### image_memory

保存影像证据：

- `image_path`
- `modality`
- `body_part`
- `image_outputs`
- `visual_evidence`
- `measurements`
- `completeness`
- `visual_evidence_bundle`

作用：

- 记录 Vision Agent 实际看到了什么、输出了什么。
- 保存 mask、overlay、局部图等 artifact 路径。
- 让诊断报告可以追溯到具体视觉证据。

#### knowledge_memory

保存本次病例使用的医学 knowledge：

- `selected_knowledge`
- `selected_vision_mode`
- `routing_decision`
- `alignment_plan`
- `knowledge_type`
- `guideline_evidence`
- `source_priority`
- `quality_control`

作用：

- 解释为什么选这个 knowledge。
- 记录该 knowledge 是正式指南还是数据假设。
- 保存指南来源、冲突、质量控制信息。

#### reasoning_memory

保存诊断推理结果：

- `report`
- `diagnostic_tendency`
- `key_evidence`
- `visual_input_contract`
- `visual_fact_usage`
- `used_visual_facts`
- `excluded_visual_facts`
- `missing_visual_fields_acknowledged`
- `uncertainty`
- `follow_up`

作用：

- 记录诊断 Agent 实际用了哪些证据。
- 记录哪些视觉证据被排除以及原因。
- 支持后续 QA 时只根据已保存证据回答。

Memory / Audit Layer 还会生成：

- `evidence_bundle`
- `memory_audit`
- `case_replay`
- `runtime_manifest`
- `stop_hook_gate`
- `self_evolving_queue`
- `candidate_validation_gate`
- `runtime_gateway_trace`

一句话：

> Memory 不是简单存报告，而是存“病例输入、图像证据、knowledge 依据、推理过程、证据使用情况和后续 QA”的完整证据链。

## 3. 一条主线：标准端到端诊断流程

下面是一条最标准的主线，用于演示“上传图片 + 自动选 knowledge + 分割/视觉证据 + 诊断报告 + evidence bundle + memory audit”。

### Step 0：用户输入

用户在前端或 API 提交：

```json
{
  "patient_message": "左髋疼痛三个月，请评估这张 X 光",
  "image_path": "output/fake/uploads/hip_xray.png",
  "patient_info": {
    "age": 45,
    "sex": "male",
    "symptoms": ["髋关节疼痛"],
    "risk_factors": ["饮酒史"]
  }
}
```

### Step 1：Clinical Orchestrator 接收请求

Orchestrator 创建或识别 case：

- 这是新诊断，不是 QA。
- 有图片。
- 有髋关节/股骨头/X 光线索。

输出初步 intent：

```json
{
  "intent": "diagnosis"
}
```

### Step 2：自动选择 knowledge

Orchestrator 根据文本和图像路径线索选择：

```json
{
  "selected_knowledge": "femoral_head_necrosis",
  "selected_vision_mode": null,
  "source": "auto",
  "confidence": 0.75,
  "matched_clues": ["髋", "x光", "股骨头"]
}
```

### Step 3：Knowledge Gateway 加载 knowledge

系统读取：

```text
knowledge/femoral_head_necrosis.yaml
```

得到：

- 疾病名称：股骨头坏死。
- knowledge 类型：`guideline_based`。
- 指南来源：ARCO / ONFH guideline 相关来源。
- X 光可观察征象：硬化带、囊性变、骨小梁模糊、塌陷、新月征。
- MRI 需求：早期病变 X 光不足，需要 MRI。
- visual protocol：每个征象需要什么模态、是否能分割、是否只观察。

### Step 4：Alignment Planner 判断图像和 knowledge 是否匹配

系统检查：

- 当前是 X 光。
- 股骨头坏死 knowledge 可以用 X 光评估中晚期征象。
- 但如果问题是“能不能排除早期股骨头坏死”，X 光不足。

可能输出：

```json
{
  "analysis_status": "partial",
  "supported_tasks": ["assess_late_xray_findings"],
  "blocked_tasks": ["assess_early_osteonecrosis"],
  "required_next_images": [
    {
      "modality": "MRI",
      "reason": "X 光不足以排除早期股骨头坏死，需要 MRI T1/T2/STIR。"
    }
  ]
}
```

### Step 5：Vision Tool Router 生成视觉工具计划

Vision Agent 读取 knowledge 的 finding targets：

- 硬化带：`vlm_plus_segmenter`
- 囊性变：`vlm_plus_segmenter`
- 骨小梁模糊：`vlm_only`
- 塌陷：`measurement_only`

生成计划：

```json
[
  {
    "target": "sclerotic_band",
    "execution_mode": "vlm_plus_segmenter",
    "selected_tool": "vlm_localization + medsam2"
  },
  {
    "target": "cystic_change",
    "execution_mode": "vlm_plus_segmenter",
    "selected_tool": "vlm_localization + medsam2"
  },
  {
    "target": "trabecular_blurring",
    "execution_mode": "vlm_only",
    "selected_tool": "vision_model_observation"
  },
  {
    "target": "collapse",
    "execution_mode": "measurement_only",
    "selected_tool": "measurement"
  }
]
```

### Step 6：Vision Evidence Agent 执行视觉证据提取

可能发生两种视觉工作：

#### 6.1 VLM-only

VLM 根据 knowledge 提示词在图像中寻找候选征象，输出：

- 哪些位置可疑。
- bbox / polygon。
- 候选解释。
- confidence。
- 是否建议进一步影像。

#### 6.2 VLM + MedSAM2

VLM 先给出 box prompt：

```json
{
  "target": "cystic_change",
  "bbox": [120, 240, 190, 310],
  "reason": "股骨头内局灶透亮区候选"
}
```

MedSAM2 根据 box prompt 生成候选 mask。

测量工具再输出：

- `area_px`
- `area_ratio_in_image`
- `area_ratio_in_anatomy`
- `bbox`
- `centroid`
- `overlap_quality`
- `diagnosis_usable`

### Step 7：Vision Agent 输出结构化视觉证据

输出不是一句“有病/没病”，而是：

```json
{
  "image_outputs": {
    "original_image_path": "...",
    "overlay_path": "...",
    "target_overlay_paths": {
      "sclerotic_band": "...",
      "cystic_change": "..."
    }
  },
  "visual_evidence": {
    "disease_target": "femoral_head_necrosis",
    "findings": [
      {
        "target": "cystic_change",
        "display_name": "囊性变",
        "status": "candidate_present",
        "regions": [
          {
            "bbox": [120, 240, 190, 310],
            "area_px": 2380,
            "area_ratio_in_anatomy": 0.08
          }
        ],
        "diagnosis_usable": true,
        "confidence": 0.76
      }
    ],
    "completeness": {
      "early_osteonecrosis": {
        "status": "missing",
        "reason": "Requires MRI T1/T2/STIR"
      }
    }
  }
}
```

### Step 8：Diagnosis Agent 读取 evidence bundle

Diagnosis Agent 不看原图，只读取：

- knowledge。
- visual evidence。
- completeness。
- structured visual facts。
- patient info。
- alignment plan。

它先建立 `visual_input_contract`：

```json
{
  "received_fields": ["findings", "measurements", "completeness"],
  "missing_fields": ["MRI early disease evidence"],
  "blocked_inferences": [
    "不能根据 X 光排除早期股骨头坏死",
    "不能把缺失 MRI 写成阴性"
  ]
}
```

### Step 9：Diagnosis Agent 生成报告

报告会分清楚：

- X 光支持哪些候选征象。
- 哪些证据不足。
- 当前能否分期。
- 需要补充什么检查。

示意：

```json
{
  "诊断倾向": "影像可见股骨头坏死相关候选征象，但需结合临床和进一步影像确认。",
  "影像依据": [
    "股骨头区域存在疑似囊性变候选区。",
    "存在疑似硬化带候选区。"
  ],
  "分期判断": "若 X 光征象可靠且无塌陷，偏向 ARCO II 候选；若存在塌陷则需考虑 ARCO III 或以上。",
  "不确定性说明": [
    "当前只有 X 光，不能排除早期股骨头坏死。",
    "VLM/MedSAM2 输出为候选视觉证据，需要人工或专病模型复核。"
  ],
  "建议进一步检查": [
    "建议补充双髋 MRI T1/T2/STIR。"
  ]
}
```

### Step 10：Memory Manager 写入四类 memory

系统保存：

- `patient_memory`
- `image_memory`
- `knowledge_memory`
- `reasoning_memory`

并生成：

- evidence bundle。
- memory audit。
- case replay。
- runtime trace。

### Step 11：前端展示

前端展示用户真正需要看的内容：

- 影像发现。
- 原图 + 候选病灶分开显示。
- 每种征象可点击放大。
- 诊断报告。
- 证据不足和下一步检查。
- evidence bundle / memory audit 可折叠查看。

### Step 12：用户追问

用户问：

```text
你刚才说哪里异常？
```

系统不会重新编造，而是：

- 找到 case_id。
- 读取 memory。
- 读取 evidence bundle。
- 只根据已保存的 used/excluded visual facts 回答。

## 4. N 条支线流程

主线之外，系统会根据输入和状态进入不同支线。

### 支线 A：已有 knowledge，直接进入主流程

触发条件：

- `disease_key` 明确传入。
- 或 Orchestrator 自动匹配到已有 knowledge。

流程：

```text
输入
  -> 自动/显式选择 knowledge
  -> load knowledge/{disease_key}.yaml
  -> 检查 visual_protocol
  -> Vision Agent
  -> Diagnosis Agent
  -> Memory / Audit
```

例子：

- 股骨头坏死 X 光。
- BraTS 胶质瘤 MRI。
- IPF HRCT。
- 肺炎胸片。

特点：

- 最稳定。
- 最适合作为当前 MVP 演示主线。

### 支线 B：没有合适 knowledge，调用 Knowledge Builder

触发条件：

- Orchestrator 没有匹配到已有 knowledge。
- 用户显式要求分析一个新病种。
- 当前 `knowledge/` 中没有对应 disease key。

流程：

```text
输入新病种
  -> Knowledge Gateway 检查本地 knowledge
  -> 未找到
  -> Guideline Search / Source Collector
  -> Guideline Extraction
  -> Visual Protocol Builder
  -> Quality Gate
  -> 生成 guideline_based knowledge 或 data_mined_hypothesis
```

分两种结果：

#### B1：找到正式指南

生成：

```json
{
  "knowledge_type": "guideline_based",
  "evidence_level": "high",
  "source_documents": []
}
```

然后进入主流程。

#### B2：找不到正式指南

只能生成：

```json
{
  "knowledge_type": "data_mined_hypothesis",
  "evidence_level": "low",
  "warning": "This is not a formal medical guideline."
}
```

此时不能用于常规临床诊断，只能进入 hypothesis validation mode。

### 支线 C：图像和 knowledge 不匹配，停止或部分分析

触发条件：

- 用户上传 X 光，但问题需要 MRI。
- 用户上传普通胸片，但 knowledge 需要 HRCT。
- 用户上传单序列 MRI，但胶质瘤 protocol 需要 T1/T1ce/T2/FLAIR。

流程：

```text
输入图像
  -> Knowledge 已选择
  -> Alignment Planner 检查模态
  -> 当前影像不足
  -> 生成 insufficient_evidence
  -> 只输出可支持部分和建议补充影像
```

例子：

```text
用户上传 X 光，问是否能排除早期股骨头坏死。
```

系统应该回答：

- 当前 X 光可以看中晚期征象。
- 不能可靠排除早期股骨头坏死。
- 需要 MRI T1/T2/STIR。

它不应该回答：

- “未见异常，所以没有股骨头坏死。”

### 支线 D：Vision Agent 只用 VLM，不调用分割模型

触发条件：

- knowledge 中某些征象不适合像素级分割。
- 当前没有可用 MedSAM2。
- 用户只需要候选视觉观察。
- `execution_mode = vlm_only`。

流程：

```text
Knowledge finding target
  -> VLM prompt
  -> bbox / polygon / textual observation
  -> structured_visual_facts
  -> diagnosis_usable 视 quality gate 决定
```

适合：

- 骨小梁模糊。
- 局灶密度改变。
- 模糊纹理异常。
- 一些只能视觉描述、难以稳定分割的征象。

限制：

- VLM-only 不能替代专病分割。
- 如果只是候选观察，应在报告中标记不确定性。

### 支线 E：VLM + MedSAM2 候选分割

触发条件：

- knowledge 的 target 可以先定位再分割。
- 当前有 VLM API。
- 当前有 MedSAM2 runner 或 fake runner。
- `execution_mode = vlm_plus_segmenter`。

流程：

```text
Knowledge target
  -> VLM 根据 knowledge 找候选 bbox
  -> bbox prompt 给 MedSAM2
  -> MedSAM2 生成 mask
  -> Measurement Tool 计算面积/比例/位置
  -> Quality Gate 判断是否可用于诊断
```

输出：

- 原图。
- 每个 target 的 overlay。
- 每个 target 的局部放大图。
- mask。
- bbox。
- area ratio。
- centroid。
- diagnosis_usable。

限制：

- 这是候选分割，不等于医学金标准。
- 如果 mask 和 prompt box 不匹配、过小、过大、重叠严重，应进入 excluded 或 manual review。

### 支线 F：专病分割模型

触发条件：

- 后续为某个疾病接入专门训练的分割模型。
- 例如股骨头坏死专病模型、肺纤维化 HRCT 模型、脑肿瘤 BraTS 模型。

流程：

```text
Knowledge target
  -> Visual Tool Router 选择 specialist_segmenter
  -> 专病模型输出 mask / heatmap / measurement
  -> Quality Gate
  -> Evidence Bundle
```

这是后续视觉 Agent 收敛的关键方向。

当前状态：

- 架构已预留。
- 通用 MedSAM2 路径已接入。
- 专病模型质量验证还需要单独 benchmark。

### 支线 G：诊断 Agent 使用 LLM，但受 evidence bundle 约束

触发条件：

- 配置了 `DMX_API_KEY` 或 `KY_API_KEY`。
- `PromptRunner` 可用。
- 诊断报告需要自然语言推理。

流程：

```text
Diagnosis Agent
  -> 构造 evidence-bounded prompt
  -> LLM 输出 JSON 报告
  -> schema check
  -> missing evidence safety check
  -> excluded fact reuse check
  -> 通过则采用
  -> 不通过则 fallback 规则报告
```

LLM 不能做的事：

- 不能引用 evidence bundle 中没有的视觉发现。
- 不能把缺失证据写成阴性。
- 不能把 excluded fact 当作依据。
- 不能直接看原图。

### 支线 H：Follow-up QA

触发条件：

- 用户带着 `case_id` 继续问问题。
- 例如“你刚才说哪里异常？”、“为什么需要 MRI？”、“这个结果严重吗？”

流程：

```text
用户追问
  -> Orchestrator 识别 qa intent
  -> Memory Manager 加载 case memory
  -> 生成 evidence bundle
  -> LLM 或 fallback 回答
  -> QA guard 检查不能越界
  -> append qa_history
```

特点：

- QA 不是重新诊断。
- QA 必须基于已有病例 evidence bundle。
- 回答后写入 `patient_memory.qa_history`。

### 支线 I：Stop Hook / Self-evolving Candidate Queue

触发条件：

- 每次病例主流程结束。
- 或视觉质量不足、证据缺失、诊断被降级、候选 finding 被排除。

流程：

```text
主流程结束
  -> runtime_manifest
  -> stop_hook_gate
  -> runtime_warnings
  -> self_evolving_queue
  -> candidate_validation_gate
```

它能做：

- 记录本次有哪些证据不足。
- 生成候选 memory。
- 生成候选 rule。
- 生成 candidate knowledge patch。

它不能做：

- 不能自动修改正式 `knowledge/*.yaml`。
- 不能覆盖诊断报告。
- 不能把候选经验当成指南。

一句话：

> Self-evolving 在 MedScope 中只能进入候选队列，不能直接升级为医学知识。

### 支线 J：Baseline 对比

触发条件：

- 需要做论文/组会对比。
- 需要证明 MedScope 比普通 LLM prompt 更安全。

流程：

```text
同一病例
  -> simple_prompt baseline
  -> workflow_prompt baseline
  -> fewshot_prompt baseline
  -> MedScope evidence-bounded pipeline
  -> 比较 missing-as-negative、unsupported claim、next image suggestion
```

相关文件：

- `prompts/baselines/simple_prompt.md`
- `prompts/baselines/workflow_prompt.md`
- `prompts/baselines/fewshot_prompt.md`
- `scripts/baseline_reasoning_eval.py`
- `scripts/image_prompt_knowledge_baseline.py`

价值：

- 说明普通 prompt 可能把缺失证据当阴性。
- 说明 workflow/fewshot 可以改善，但仍不如结构化 evidence bundle 稳定。
- 说明 MedScope 的核心优势不是“会说”，而是“证据边界可控”。

## 5. 项目如何被“一条主线 + 多条支线”串起来

可以这样画：

```text
主线：标准诊断链路

上传图片 + 患者描述
  -> Orchestrator 判断意图
  -> 自动选择或加载 Knowledge
  -> Alignment Planner 检查图像是否足够
  -> Vision Agent 根据 visual_protocol 提取证据
  -> Diagnosis Agent 基于 evidence bundle 生成报告
  -> Memory 写入四类 memory
  -> 前端展示报告、病灶图、证据包和审计
  -> Follow-up QA 基于 memory 回答

支线：
  A 已有 knowledge：直接主流程
  B 无 knowledge：Knowledge Builder 找指南/生成 knowledge
  C 图像不足：输出 insufficient evidence 和下一步影像
  D VLM-only：只做候选视觉观察
  E VLM+MedSAM2：候选定位 + 候选分割 + 数值测量
  F 专病分割模型：后续替换更强视觉后端
  G LLM 报告：受 evidence bundle 约束
  H Follow-up QA：受 memory/evidence bundle 约束
  I Stop Hook：生成候选改进但不自动升级
  J Baseline：与普通 LLM/Codex prompt 对比
```

## 6. 当前项目的核心卖点

### 6.1 不是黑盒端到端诊断

普通端到端视觉大模型可能直接输出：

```text
这张图像考虑股骨头坏死。
```

MedScope 输出的是：

```text
哪些 visual facts 被观察到；
哪些 mask/overlay 支持这些 facts；
哪些 evidence 被排除；
哪些模态缺失；
当前能做什么判断；
当前不能做什么判断；
下一步需要什么检查。
```

### 6.2 Knowledge 控制视觉任务

Vision Agent 不是随便看图，而是根据 knowledge 中的 `visual_protocol` 看：

- 该病需要看哪些征象。
- 每个征象需要什么图像模态。
- 哪些征象需要分割。
- 哪些征象只能观察。
- 哪些证据不足时必须提示补充检查。

### 6.3 诊断只消费结构化 evidence

Diagnosis Agent 不直接读原图，避免大模型直接凭图像自由发挥。它只消费：

- `visual_evidence`
- `measurements`
- `completeness`
- `structured_visual_facts`
- `guideline_evidence`
- `alignment_plan`

### 6.4 Memory 是证据链，不是聊天记录

Memory 保存：

- 患者问了什么。
- 图像输出了什么。
- 用了哪个 knowledge。
- 诊断用了哪些证据。
- 哪些证据被排除。
- QA 回答引用了什么。

这让系统可以被 replay、audit、debug 和扩展。

### 6.5 Candidate Queue 支持可控演化

系统可以记录“这次哪里失败了”“哪些规则可能需要改”，但不会自动改正式医学指南。

这保留了 self-evolving 的研究空间，同时避免医疗安全风险。

## 7. 当前最适合演示的主线

建议当前组会或 demo 使用：

```text
股骨头坏死 X 光 no-mask 多征象样例
```

原因：

- 用户上传单张医疗图像。
- Orchestrator 可以自动选 `femoral_head_necrosis` knowledge。
- Knowledge 中有清晰 visual protocol。
- Vision Agent 可以展示 VLM-only 和 VLM+MedSAM2 两种视觉路径。
- 前端可以展示每种征象单独图、局部放大、诊断报告。
- Diagnosis Agent 可以演示“X 光不足以排除早期病变，需要 MRI”。
- Memory audit 可以展示四类 memory。

推荐演示说法：

> 用户上传骨盆正位 X 光和主诉后，Clinical Orchestrator 自动选择股骨头坏死 knowledge。Knowledge Gateway 读取指南来源和 visual protocol，告诉 Vision Agent 要看硬化带、囊性变、骨小梁纹理和塌陷。Vision Agent 用 VLM 找候选区域，并在可分割征象上调用 MedSAM2 生成候选 mask 和面积比例。Diagnosis Agent 不看原图，只读取结构化 visual evidence 和 completeness，生成一个承认证据不足的诊断报告，并提示早期病变需要 MRI。最后 Memory Manager 保存 patient/image/knowledge/reasoning 四类 memory，前端展示 evidence bundle 和 audit trace。

## 8. 当前最需要继续完善的支线

优先级建议：

1. 视觉后端质量验证：建立疾病级 benchmark，区分 VLM-only、VLM+MedSAM2、专病模型。
2. 公开可复现实例：准备一组不会泄露隐私的小样例，保证新环境能跑通主线。
3. Knowledge Builder 真实指南采集闭环：继续完善网页/PDF 指南采集、抽取、质量门。
4. 依赖和部署：补 `requirements.txt` 或 `pyproject.toml`。
5. Candidate Queue 验证机制：把人工 review、数据集指标、指南来源确认接入 validation gate。
