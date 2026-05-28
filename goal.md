你现在可以设计成这套结构：

```
患者 / 前端
   ↓
高医生 Agent：对话入口、任务分发、结果解释、QA
   ↓
诊断医生 Agent：指南检索、疾病 Skill 生成、诊断推理、报告生成
   ↓
视觉 Agent：图像预处理、分割、病灶定位、影像特征提取
   ↓
Memory：患者信息、影像结果、指南 Skill、诊断过程、历史问答
```

## 1. 先明确每个 Agent 的职责

### 高医生 Agent：前台医生

它不负责真正的图像分析，也不直接下诊断。它主要做这几件事：

```
1. 和患者对话
2. 收集患者基本信息
3. 接收医疗图片
4. 判断用户意图：诊断 / 问答 / 复查 / 解释报告
5. 调用诊断医生 Agent
6. 把最终报告用患者能听懂的话输出
7. 后续继续做 QA
```

高医生 Agent 更像“门诊医生 + 前端客服”。

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

### 诊断医生 Agent：核心大脑

这个 Agent 是整个系统最重要的部分。

它负责：

```
1. 判断可能是什么病
2. 检索医疗指南
3. 把指南整理成 disease_skill 文件
4. 调用视觉 Agent 做图像分析
5. 接收视觉 Agent 返回的结构化结果
6. 根据指南 + 图像证据 + 患者症状生成诊断报告
7. 给出治疗建议和不确定性说明
```

注意：**诊断医生 Agent 不直接处理像素图片**，它只处理结构化证据。

它收到视觉 Agent 的结果应该是这种：

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

然后诊断医生 Agent 再根据 disease skill 判断：

```
如果未见塌陷 + X 光纹理异常 + 症状符合 + MRI 金标准提示早期改变，
则考虑早期股骨头坏死可能，但 X 光单独诊断可靠性有限。
```

------

### 视觉 Agent：影像证据提取器

视觉 Agent 的定位一定要克制。

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

也就是说，视觉 Agent 只负责回答：

```
图上看到了什么？
病灶在哪里？
分割结果如何？
有哪些可量化特征？
模型置信度是多少？
```

不要让它负责最终医学结论。

------

## 2. 你的整体流程可以这样设计

我建议你先按这个流程写：

```
Step 1：患者上传图片，向高医生提问
Step 2：高医生记录患者信息，创建 case_id
Step 3：高医生把任务转交给诊断医生 Agent
Step 4：诊断医生 Agent 判断疑似疾病方向
Step 5：诊断医生 Agent 检索对应医疗指南
Step 6：如果找到指南，就生成 disease_skill
Step 7：如果没有指南，就进入“数据总结模式”
Step 8：诊断医生 Agent 把 disease_skill 发给视觉 Agent
Step 9：视觉 Agent 根据 skill 中的影像特征要求做分割和特征提取
Step 10：视觉 Agent 返回结构化影像证据
Step 11：诊断医生 Agent 结合指南、影像、症状生成报告
Step 12：报告返回高医生
Step 13：高医生用患者能理解的话输出，并支持后续 QA
```

可以画成：

```
患者
 ↓
高医生 Agent
 ↓
诊断医生 Agent
 ├── 指南检索工具
 ├── disease_skill 生成器
 ├── 数据总结模块
 └── 报告生成模块
 ↓
视觉 Agent
 ├── 图像预处理
 ├── 分割模型
 ├── 病灶定位
 └── 特征提取
 ↓
诊断医生 Agent
 ↓
高医生 Agent
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

## 8. 我建议你最终改成这 5 个 Agent / 模块

你原来是 3 个 Agent：高医生、诊断医生、视觉 Agent。

我建议改成：

```
1. 高医生 Agent
2. 诊断医生 Agent
3. 指南 Skill Builder
4. 视觉 Agent
5. 报告生成 Agent
```

其中 Skill Builder 可以不是独立 Agent，也可以只是诊断医生 Agent 的一个工具。

更清晰的版本是：

```
高医生 Agent
负责：对话、收集信息、展示报告、回答患者问题

诊断医生 Agent
负责：医学推理、调用指南、调用视觉结果、生成诊断判断

Skill Builder Tool
负责：把指南转成结构化 disease_skill

视觉 Agent
负责：分割、定位、特征提取、输出影像证据 JSON

Memory Manager
负责：保存患者信息、影像结果、skill、推理记录
```

我更推荐这个版本，因为不需要把所有东西都做成 Agent。**能用工具解决的，就不要硬做成 Agent。**

------

## 9. 你可以这样向老师描述你的架构

你可以这样说：

> 我计划设计一个面向罕见病影像辅助诊断的多 Agent 系统。系统由高医生 Agent、诊断医生 Agent、视觉 Agent 和 Memory Manager 组成。高医生 Agent 负责与患者对话和前端交互；诊断医生 Agent 负责医学指南检索、疾病 Skill 构建、诊断推理和报告生成；视觉 Agent 根据疾病 Skill 中定义的影像观察目标，对患者上传的医学图像进行分割、病灶定位和特征提取，并返回结构化影像证据；诊断医生 Agent 再结合患者症状、指南 Skill、影像证据和历史 Memory 生成诊断报告及初步治疗建议。
>
> 对于有正式指南的疾病，系统将指南转化为 guideline-based skill；对于缺乏指南的罕见病，系统不会直接生成“医学指南”，而是进入 evidence summary mode，从已有病例数据中总结候选影像规律，形成 hypothesis skill，并明确标注其证据等级较低，仅作为辅助分析依据。Memory 模块则用于保存患者信息、影像分析结果、疾病 Skill 和诊断推理过程，从而保证多轮问答中的连续性和可追溯性。

------

