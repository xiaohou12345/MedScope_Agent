当前推荐把系统讲成“临床证据流水线”，不要再把所有实现节点都包装成并列 Agent。

这不是大重构，而是把已有模块按医疗安全边界重新命名和解释：

```
患者 / 前端
   ↓
Clinical Orchestrator：统一入口、意图识别、skill 路由、患者解释、追问 QA
   ↓
Skill Builder / Guideline Component：条件触发；有 skill 就加载，没有合适 skill 才检索指南并生成 guideline skill
   ↓
Vision Evidence Agent：按 skill 的 visual_protocol 提取影像证据、分割病灶、输出 mask/overlay/数值
   ↓
Diagnosis Reasoning Agent：只消费结构化 evidence bundle，不直接看原图，生成受指南约束的报告
   ↓
Memory / Audit Layer：保存 patient/image/skill/reasoning 四类 memory，生成 replay 和 audit
```

所以对外汇报时建议说：

```
MedScope 是一个 guideline-aware clinical evidence pipeline。
核心是 3 个 Agent：
1. Clinical Orchestrator
2. Vision Evidence Agent
3. Diagnosis Reasoning Agent

另外有 1 个条件触发的 Skill Builder / Guideline Component，
以及 1 个 Memory / Audit 基础设施层。
```

这样能避免“为了分 Agent 而分 Agent”的质疑。拆分依据不是数量，而是：

```
谁负责入口和任务编排？
谁负责从图像中提取可审计证据？
谁负责基于指南和证据做推理？
谁只在没有合适 skill 时构建指南 skill？
谁负责保存证据链和回放审计？
```

还可以进一步把底层讲成一套 `Agentic Runtime / Evidence Gateway`，类似 Claude Code / Codex 这类新式 agent 系统：

```
主 Agent 不直接包办所有事情，
而是通过 gateway 分发 skill、文件、工具和约束。
每次调用结束后再通过 stop hooks / reflection hooks 做自检、写 memory、生成候选改进。
```

这层底座负责：

```
1. Skill Gateway：装载 guideline skill、hypothesis skill 和 visual_protocol。
2. Shared File Workspace：共享上传图像、mask、overlay、comparison、evidence bundle 和 audit artifact。
3. Contract Guards：约束每个 Agent 能读什么、能写什么、不能越权输出什么。
4. Tool Router：按 skill 和图像模态选择 VLM、MedSAM2、测量工具或指南采集工具。
5. Stop Hooks：每次调用后检查证据缺口、质量门控、memory 写入和下一步建议。
6. Self-evolving Queue：沉淀候选诊疗规则或 skill patch，但不能直接覆盖正式指南。
```

这样对外可以讲成两层：

```
上层：临床证据流水线，解决医疗职责边界。
底层：Agentic Runtime / Evidence Gateway，解决 skill 分发、文件共享、hooks、自检和长期记忆。
```

特别要注意：self-evolving 不是让系统自动篡改医疗指南，而是让系统把运行后的反思沉淀为候选规则，进入验证队列。只有通过真实数据、指南来源或人工审核后，才能从 `candidate_skill_patch` 升级为正式 skill。

旧版可以理解成这套实现结构：

```
患者 / 前端
   ↓
Clinical Orchestrator / 高医生实现节点：对话入口、任务分发、结果解释、QA
   ↓
Skill Builder / Guideline Component：条件加载或生成疾病 Skill
   ↓
Vision Evidence Agent / 视觉实现节点：图像预处理、分割、病灶定位、影像特征提取
   ↓
Diagnosis Reasoning Agent / 诊断实现节点：指南约束推理、报告生成
   ↓
Memory / Audit Layer：患者信息、影像结果、指南 Skill、诊断过程、历史问答
```

## 1. 先明确职责边界，而不是追求 Agent 数量

### Clinical Orchestrator：临床编排入口

它不负责真正的图像分析，也不直接下诊断。它主要做这几件事：

```
1. 和患者对话
2. 收集患者基本信息
3. 接收医疗图片
4. 判断用户意图：诊断 / 问答 / 复查 / 解释报告
5. 自动选择已有 skill，或在缺少 skill 时触发 Skill Builder / Guideline Component
6. 调用视觉证据提取和诊断推理
7. 把最终报告用患者能听懂的话输出
8. 后续继续做 QA
```

它更像“门诊医生 + 临床工作流编排器”，不是诊断黑盒。

它的输入：

```
{
  "patient_message": "医生帮我看看这个片子",
  "image_path": "xxx.png",
  "patient_info": {
    "age": 45,
    "sex": "male",
    "symptoms": ["髋关节疼痛"]
  }
}
```

它的输出：

```
{
  "reply_to_patient": "根据影像分析结果，存在股骨头坏死早期可能，建议进一步结合 MRI 检查确认……"
}
```

------

### Skill Builder / Guideline Component：条件触发的指南 skill 构建器

这个组件不必被讲成一个永远参与诊断的并列 Agent。它的触发条件很明确：

它负责：

```
1. 当前仓库已有合适 skill：直接加载，不重新生成。
2. 当前仓库没有合适 skill：检索真实指南来源。
3. 找到正式指南：生成 guideline_based disease_skill。
4. 没有正式指南：只能生成 data_mined_hypothesis，并显式标低证据等级。
5. 生成的 skill 必须包含 visual_protocol，告诉视觉证据提取环节要观察什么。
```

这个组件的价值是把“医学指南”变成机器可执行的 skill，而不是直接诊断。

------

### Vision Evidence Agent：影像证据提取器

视觉证据提取的定位一定要克制。

它不应该输出：

```
{
  "diagnosis": "股骨头坏死一期"
}
```

它应该输出：

```
{
  "visual_evidence": {
    "femoral_head_shape": "基本完整",
    "collapse": false,
    "sclerosis": "疑似轻度",
    "cystic_change": "未明确",
    "joint_space": "未明显狭窄",
    "lesion_mask": "mask_001.png",
    "confidence": 0.78
  }
}
```

也就是说，Vision Evidence Agent 只负责回答：

```
图上看到了什么？
病灶在哪里？
分割结果如何？
有哪些可量化特征？
模型置信度是多少？
这些证据是否达到诊断可用标准？
```

不要让它负责最终医学结论。

------

### Diagnosis Reasoning Agent：证据约束推理器

这个 Agent 是医学推理环节，但不是像素理解环节。

它负责：

```
1. 读取已选 disease_skill。
2. 读取患者症状和风险因素。
3. 读取 Vision Evidence Agent 返回的结构化 evidence bundle。
4. 检查 evidence completeness：哪些证据支持，哪些缺失，哪些不适用。
5. 根据指南 + 图像证据 + 患者症状生成报告。
6. 给出不确定性、补充检查建议和禁止过度判断的说明。
```

注意：**Diagnosis Reasoning Agent 不直接处理像素图片**，它只处理结构化证据。

它收到 Vision Evidence Agent 的结果应该是这种：

```
{
  "image_type": "xray",
  "lesion_detected": true,
  "lesion_location": "left femoral head",
  "segmentation_quality": "good",
  "collapse_detected": false,
  "joint_space_narrowing": false,
  "texture_abnormality_score": 0.72,
  "suspected_findings": [
    "股骨头局部骨小梁纹理异常",
    "未见明显塌陷",
    "关节间隙基本正常"
  ]
}
```

然后 Diagnosis Reasoning Agent 再根据 disease skill 判断：

```
如果未见塌陷 + X 光纹理异常 + 症状符合 + MRI 金标准提示早期改变，
则考虑早期股骨头坏死可能，但 X 光单独诊断可靠性有限。
```

------

## 2. 你的整体流程可以这样设计

我建议你先按这个流程写：

```
Step 1：患者上传图片，向高医生提问
Step 2：Clinical Orchestrator 记录患者信息，创建 case_id
Step 3：Clinical Orchestrator 根据患者描述和图像元信息自动选择 skill
Step 4：如果仓库已有合适 skill，直接加载
Step 5：如果没有合适 skill，触发 Skill Builder / Guideline Component 检索真实指南并生成 skill
Step 6：如果 skill 判断当前图像模态不足，直接输出“证据不足 + 建议补充影像”
Step 7：如果图像模态可分析，把 skill.visual_protocol 交给 Vision Evidence Agent
Step 8：Vision Evidence Agent 根据 skill 要求定位、分割和量化病灶
Step 9：Vision Evidence Agent 返回结构化影像证据、mask、overlay、quality gate
Step 10：Diagnosis Reasoning Agent 结合指南、影像证据和症状生成报告
Step 11：报告返回 Clinical Orchestrator
Step 12：Clinical Orchestrator 用患者能理解的话输出，并支持后续 QA
Step 13：Memory / Audit Layer 保存四类 memory、evidence bundle、replay 和 audit
```

可以画成：

```
患者
 ↓
Clinical Orchestrator
 ↓
Skill Builder / Guideline Component
 ├── 指南检索工具
 ├── disease_skill 生成器
 └── data_mined_hypothesis 生成器
 ↓
Vision Evidence Agent
 ├── 图像预处理
 ├── 分割模型
 ├── 病灶定位
 └── 特征提取
 ↓
Diagnosis Reasoning Agent
 ├── evidence bundle
 ├── evidence completeness
 ├── visual fact usage
 └── 受指南约束报告
 ↓
Clinical Orchestrator
 ↓
Memory / Audit Layer
 ↓
患者
```

------

## 3. disease_skill 文件应该怎么设计？

你说的“指南 Skill 文件”是非常关键的。

它不应该是一大段自然语言，而应该是**结构化的诊断规则文件**。比如股骨头坏死可以这样设计：

```
disease_name: "股骨头坏死"
version: "0.1"
source_type: "medical_guideline"

clinical_features:
  common_symptoms:
    - "髋关节疼痛"
    - "腹股沟区疼痛"
    - "活动受限"
  risk_factors:
    - "长期饮酒"
    - "激素使用史"
    - "外伤史"

required_image_views:
  - "双髋正位 X 光"
  - "蛙式位 X 光"
  - "MRI T1"
  - "MRI T2"

visual_targets:
  anatomy:
    - "股骨头"
    - "髋臼"
    - "关节间隙"
  lesion_features:
    - "股骨头塌陷"
    - "硬化带"
    - "囊性变"
    - "新月征"
    - "骨小梁纹理异常"

staging_rules:
  ARCO_I:
    description: "X 光可无明显异常，MRI 可见异常信号"
    xray_features:
      - "无明显塌陷"
      - "无明显关节间隙狭窄"
    mri_features:
      - "T1 低信号"
      - "T2 异常信号"
  ARCO_II:
    description: "X 光可见硬化或囊性变，但无股骨头塌陷"
    xray_features:
      - "硬化影"
      - "囊性改变"
      - "无明显塌陷"
  ARCO_III:
    description: "出现股骨头塌陷或新月征"
    xray_features:
      - "新月征"
      - "股骨头塌陷"
  ARCO_IV:
    description: "继发骨关节炎改变"
    xray_features:
      - "关节间隙狭窄"
      - "髋臼改变"
      - "明显骨关节炎"

vision_agent_tasks:
  segmentation_targets:
    - "股骨头区域"
    - "疑似坏死区域"
    - "关节间隙"
  quantitative_features:
    - "lesion_area_ratio"
    - "collapse_ratio"
    - "joint_space_width"
    - "texture_abnormality_score"

report_requirements:
  include:
    - "诊断倾向"
    - "影像依据"
    - "分期判断"
    - "不确定性说明"
    - "建议进一步检查"
    - "治疗建议"
```

这个文件的作用是告诉视觉 Agent：

```
你要看哪里？
你要分割哪里？
你要提取哪些指标？
哪些影像特征对诊断有意义？
```

同时也告诉诊断医生 Agent：

```
拿到这些影像特征以后，怎么根据指南推理？
```

------

## 4. “没有指南，根据数据总结指南”这个模式怎么做？

这个模式风险很高，不能叫“总结指南”。因为如果没有医学指南，你不能让大模型自己发明医学指南。

建议你把它改名为：

```
evidence_summary_mode
证据总结模式
```

也就是说，它不是生成“指南”，而是生成：

```
基于已有病例数据的候选观察规则
```

比如：

```
在 100 个已确诊病例中，早期股骨头坏死患者的 X 光常出现：
1. 股骨头外形未塌陷
2. 局部骨小梁纹理紊乱
3. 灰度方差高于正常组
4. 病灶区域集中于负重区
```

这个只能叫：

```
hypothesis_skill
候选假设 Skill
```

不能叫：

```
guideline_skill
医学指南 Skill
```

你可以这样区分：

```
skill_type: "guideline_based"
evidence_level: "high"
source: "official guideline"
```

和：

```
skill_type: "data_mined_hypothesis"
evidence_level: "low"
source: "internal dataset statistical summary"
warning: "该规则来自数据总结，不等同于正式医学指南，只能作为辅助提示"
```

这个设计非常重要。否则老师一问你：

> 你这个指南从哪里来的？有医学依据吗？

你就会很被动。

所以正确设计是：

```
有指南 → guideline_skill
无指南 → hypothesis_skill
```

这两个必须分开。

------

## 5. Memory 怎么设计？

Memory 不要一上来做得太玄乎。你可以先分成 4 类。

### 第一类：Patient Memory，患者记忆

保存患者基本信息：

```
{
  "case_id": "case_20240517_001",
  "patient_profile": {
    "age": 45,
    "sex": "male",
    "chief_complaint": "左髋疼痛 3 个月",
    "symptoms": ["髋关节疼痛", "活动受限"],
    "risk_factors": ["饮酒史"],
    "medical_history": []
  }
}
```

作用是：后续 QA 时，系统知道这个患者之前说过什么。

------

### 第二类：Image Memory，影像记忆

保存每一次影像分析结果：

```
{
  "case_id": "case_20240517_001",
  "image_memory": [
    {
      "image_id": "xray_001",
      "modality": "xray",
      "body_part": "hip",
      "analysis_time": "2026-05-23",
      "segmentation_result": {
        "mask_path": "mask_xray_001.png",
        "quality": "good"
      },
      "visual_features": {
        "collapse_detected": false,
        "joint_space_narrowing": false,
        "texture_abnormality_score": 0.72,
        "lesion_area_ratio": 0.14
      }
    }
  ]
}
```

作用是：后面患者问“你刚才说哪里异常？”系统能回答。

------

### 第三类：Skill Memory，疾病 Skill 记忆

保存已经生成过的疾病 skill：

```
{
  "disease": "股骨头坏死",
  "skill_id": "femoral_head_necrosis_v0.1",
  "skill_type": "guideline_based",
  "source": "ARCO 分期相关指南",
  "version": "0.1",
  "created_at": "2026-05-23"
}
```

作用是：下次再遇到同类疾病，不用重新提炼指南，可以直接复用。

------

### 第四类：Reasoning Memory，推理记忆

保存诊断过程，而不是只保存结论。

```
{
  "case_id": "case_20240517_001",
  "reasoning_memory": {
    "used_skill": "femoral_head_necrosis_v0.1",
    "key_evidence": [
      "X 光未见明显塌陷",
      "股骨头区域纹理异常评分较高",
      "患者存在髋关节疼痛症状"
    ],
    "diagnostic_result": "疑似早期股骨头坏死",
    "uncertainty": [
      "单纯 X 光对早期股骨头坏死敏感性有限",
      "建议结合 MRI 进一步确认"
    ]
  }
}
```

作用是防止主 Agent 幻觉。因为它每次回答都可以回看之前的证据，而不是重新编。

------

## 6. 你的 Memory 可以这样落地

第一版不要上复杂向量数据库。你可以先这样：

```
短期 Memory：存在当前会话 state 里
长期 Memory：存在 JSON / SQLite / PostgreSQL
指南 Skill：存在本地 yaml / markdown 文件
病例影像结果：存在 case_id 对应的 JSON 文件
```

项目结构可以这样写：

```
medical_agent_system/
├── app.py
├── agents/
│   ├── gaodoctor_agent.py
│   ├── diagnosis_agent.py
│   ├── vision_agent.py
│   └── report_agent.py
├── tools/
│   ├── guideline_search_tool.py
│   ├── skill_builder_tool.py
│   ├── segmentation_tool.py
│   ├── feature_extraction_tool.py
│   └── report_template_tool.py
├── memory/
│   ├── patient_memory.py
│   ├── image_memory.py
│   ├── skill_memory.py
│   └── reasoning_memory.py
├── skills/
│   ├── femoral_head_necrosis.yaml
│   └── rare_disease_x.yaml
├── data/
│   ├── images/
│   ├── masks/
│   └── cases/
└── prompts/
    ├── gaodoctor_prompt.md
    ├── diagnosis_agent_prompt.md
    ├── vision_agent_prompt.md
    └── report_prompt.md
```

------

## 7. 你这个系统最小可运行版本应该怎么做？

不要一开始就做完整医疗系统。你第一版只做这个：

```
输入：一张 X 光图片 + 患者一句描述
输出：一份结构化医疗报告
```

第一版流程：

```
1. 高医生接收图片和症状
2. 诊断医生读取股骨头坏死 skill 文件
3. 视觉 Agent 先不接真实模型，返回模拟 JSON
4. 诊断医生根据模拟 JSON 生成报告
5. 高医生把报告解释给患者
6. Memory 保存本次 case
```

第一版甚至可以先不用真实分割模型，用假数据跑通流程：

```
{
  "modality": "xray",
  "body_part": "hip",
  "collapse_detected": false,
  "joint_space_narrowing": false,
  "texture_abnormality_score": 0.74,
  "lesion_area_ratio": 0.13,
  "suspected_visual_findings": [
    "股骨头负重区纹理异常",
    "未见明显塌陷",
    "关节间隙尚可"
  ]
}
```

等这个流程跑通后，再把视觉 Agent 换成真实模型。

------

## 8. 当前建议的最终架构表达

早期可以把系统粗略理解成高医生、诊断医生、视觉 Agent 三部分，但当前组会和论文汇报不建议继续按“几个 Agent”来讲。

更稳妥的版本是：

```
1. Clinical Orchestrator
2. Vision Evidence Agent
3. Diagnosis Reasoning Agent
4. Skill Builder / Guideline Component
5. Memory / Audit Layer
```

其中只有前三个是核心 Agent；Skill Builder 是条件触发的指南 skill 构建组件，Memory / Audit 是基础设施层。

更清晰的职责表述是：

```
Clinical Orchestrator
负责：对话、收集信息、自动选择 skill、分发任务、展示报告、回答患者问题

Vision Evidence Agent
负责：分割、定位、特征提取、输出影像证据 JSON

Diagnosis Reasoning Agent
负责：医学推理、读取 guideline skill、消费结构化视觉证据、生成受约束报告

Skill Builder / Guideline Component
负责：在缺少合适 skill 时，把真实指南转成结构化 disease_skill

Memory / Audit Layer
负责：保存患者信息、影像结果、skill、推理记录、evidence bundle 和 replay
```

我更推荐这个版本，因为它不强调 Agent 数量，而强调医疗安全边界。**能作为条件组件或基础设施层解释的，就不要硬讲成并列业务 Agent。**

------

## 9. 你可以这样向老师描述你的架构

你可以这样说：

> 我计划设计一个面向罕见病影像辅助诊断的 guideline-aware clinical evidence pipeline。系统不是按 Agent 数量堆叠，而是按医疗安全边界拆成三个核心 Agent、一个条件 Skill Builder / Guideline Component 和一个 Memory / Audit 基础设施层。Clinical Orchestrator 负责患者入口、意图识别、自动 skill 路由和追问解释；Vision Evidence Agent 根据 disease skill 中的 visual protocol 对上传医学图像进行病灶定位、分割、特征提取和质量门控，并返回结构化影像证据；Diagnosis Reasoning Agent 不直接看原图，只消费 guideline skill、患者上下文和 evidence bundle，生成受证据充分性约束的诊断报告。
>
> 对于有正式指南的疾病，Skill Builder / Guideline Component 将真实指南转化为 guideline-based skill；对于缺乏指南的罕见病，系统不会直接生成“医学指南”，而是进入 evidence summary / data-mined hypothesis mode，从已有病例数据中总结候选影像规律，形成 hypothesis skill，并明确标注其证据等级较低，仅作为辅助分析依据。Memory / Audit Layer 用于保存 patient_memory、image_memory、skill_memory、reasoning_memory、evidence bundle 和 replay，从而保证多轮问答中的连续性、可解释性和可审计性。

------
