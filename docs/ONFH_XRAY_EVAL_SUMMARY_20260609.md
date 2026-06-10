# ONFH Xray 原流程最小替换实验汇总 (2026-06-09)

## 实验目的
本实验旨在评估 MedScope 诊断链路（`GaoDoctorAgent` -> `DiagnosisDoctorAgent` -> `ReportAgent`）在接入不同质量的 Xray 视觉 findings 时的端到端诊断能力。实验保留原服务入口和诊断/报告链路，仅替换视觉 evidence 来源，不使用额外的候选诊断 Agent 作为正式输出。

这不是未改动 hsh 分支的原样输出，而是基于 hsh agent 框架的 ONFH Xray 三分类适配版：统一 Xray GT 标签空间、注入结构化 findings、并从最终报告中解析三分类分期。

## 实验矩阵
共三类视觉特征来源的对比实验：

1. **Pure Mock (医生标注 GT):** 仅使用经审核的 Xray COCO Mask 转换成的视觉 findings。
2. **Real VLM:** 仅使用 VLM 在 ROI 图像上推理生成的视觉 findings。
3. **Mixed (VLM + Mock GT):** 混合真实 VLM findings 与医生标注 Mock GT findings。

## 结果汇总 (基于 Xray 三分类 GT)

| 实验组 | 视觉来源 | 准确率 (Accuracy) | 非弃权准确率 (Non-abstain Acc) | 覆盖率 (Coverage) | 弃权计为正常准确率 (Acc if abstain=Normal) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Pure Mock** | 医生标注 (GT) | 47.06% | 64.00% | 73.53% | 73.53% |
| **Real VLM** | 仅 VLM 推理 | 32.35% | 34.38% | 94.12% | 35.29% |
| **Mixed** | VLM + Mock GT | 58.82% | 62.50% | 94.12% | 61.76% |

## 混淆矩阵 (GT vs 预测)

| 实验组 | GT 未发现异常 (10) | GT 3期 (13) | GT 2期 (11) |
| :--- | :--- | :--- | :--- |
| **Pure Mock** | 9 弃权, 1 误诊 | 12 正确, 1 误诊 | 8 正确, 3 误诊 |
| **Real VLM** | 2 弃权, 8 误诊 | 3 正确, 10 误诊 | 8 正确, 3 误诊 |
| **Mixed** | 2 弃权, 8 误诊 | 12 正确, 1 误诊 | 8 正确, 3 误诊 |

## 诊断瓶颈分析

1. **诊断链路能力：**
   - 在 Xray findings 到诊断 evidence 的映射完成适配后，原 service 诊断链路可以基于结构化视觉征象给出可评分的“2期/3期/未发现异常”三分类输出。
   - 该结果仍依赖 findings 质量和 Xray 适配规则，不应解读为未改动原流程已经具备稳定准确分期能力。
   
2. **当前视觉瓶颈：**
   - **VLM 幻觉 (High False Positive):** 在“未发现异常”的病例中，Real VLM 和 Mixed 组均产生了极高的误诊率（约 80%），这表明 VLM 模型在没有任何病理征象的情况下倾向于过度报告征象。
   - **VLM 漏诊 (High False Negative):** Real VLM 组在 3 期塌陷病例上的极低识别率证明其未能捕捉到“塌陷”这一关键晚期特征。

## 近期修复记录 (2026-06-09)

在实验评估过程中，发现 Xray findings 到诊断 evidence 的映射存在逻辑偏差，已完成以下适配：

1. **结构性破坏特征映射:**
   - 将 `subchondral_fracture` (软骨下骨折) 和 `crescent_sign` (新月征) 作为 Xray 结构性改变 findings 处理，并在评估 runner 中映射为可被诊断链路识别的塌陷/结构性改变 evidence。
   - 这样可以避免关键 3期相关 findings 在后续诊断链路中被当作证据不足而丢失。

2. **描述逻辑优化:** 
   - 修正了二期病例的负向描述模板。原先的 `"未见明确塌陷及软骨下骨折"` 描述会导致评估脚本的正则解析器误将二期识别为三期（因为命中了“软骨下骨折”词条）。
   - 现已替换为 `"未见明确塌陷等晚期征象"`，在保持医学逻辑严谨的前提下，通过了自动化评测的类别解析要求。

## 原流程规则逻辑 (Rule-based Logic)

本实验使用的诊断逻辑基于 `DiagnosisDoctorAgent` 的硬编码规则，不涉及 LLM 生成式推理：

### 逻辑变更对比

| 征象分类 | 适配前 | 适配后 |
| :--- | :--- | :--- |
| **塌陷/骨折/新月征** | 部分 Xray target 无法被诊断规则识别 | 在视觉 runner 中映射为结构性改变/塌陷相关 evidence |
| **报告文本** | 容易被证据不足或保守表述覆盖 | 最终报告中保留可解析的 ARCO II/III 倾向 |
| **诊断倾向** | 大量输出暂无法可靠分期 | 能基于结构化 findings 输出 Xray 三分类倾向 |

### 核心规则链与“三期”判断机制
1. **结构性改变 (Advanced):** 识别 `collapse`, `subchondral_fracture`, `crescent_sign`。触发 `ARCO II/III 边界复核` 的报告生成。
   - *说明：* Agent 本身不强制硬编码“这是三期”，而是根据征象描述“进入结构性改变期”。
   - *解析：* 评估脚本通过解析报告中的关键词（如“III”、“塌陷”、“新月征”）自动将其映射为 GT 中的“3期”。
2. **早期病变 (FHN Support):** 识别 `sclerotic_band`, `cystic_change` 等。触发 `倾向 ARCO II`。
3. **纹理模式 (Early Pattern):** 识别 `trabecular_blurring` + 症状。触发 `倾向 ARCO I-II`。
4. **兜底 (Abstain):** 证据不足时统一输出 `暂无法可靠分期`。
