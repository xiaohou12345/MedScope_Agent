目标：Research Evidence Ingestion v1 —— 完成“论文证据安全补充 guideline knowledge”的可审阅闭环

当前背景：

我们已经完成了较多后端安全架构能力，包括：

- Research Evidence Builder
- Research Evidence Proposal
- Evidence Gateway
- source quality / freshness / applicability / conflict / human review gate
- proposal-only artifact
- controlled knowledge extension draft
- formal knowledge extension patch preview
- 不直接修改正式 guideline knowledge 的安全边界

但目前这条线还更像后端 artifact 流程，距离一个可审阅、可追踪、可前端展示的 research ingestion 产品闭环还差最后一层：

- 还没有真实 PubMed metadata retrieval v1；
- 还没有 supplied metadata fallback 的完整用户路径；
- 还没有把论文 evidence promotion 接到前端审核展示；
- 目前论文证据还没有形成医生/研究者可读的 Research Evidence Review 面板。

本轮目标：

将现有 Research Evidence Builder / Evidence Gateway / controlled knowledge extension draft / formal knowledge extension patch preview 升级为 Research Evidence Ingestion v1。

核心目标不是让论文直接修改正式 knowledge，而是让论文证据进入一个受控候选区，并经过 metadata retrieval、evidence extraction、candidate claim builder、Evidence Gateway、human review checklist 和 promotion dry-run preview，最终生成 proposal-only / patch-preview artifact，并能在前端被清晰审阅。

一、必须保持的安全边界

1. 论文证据不能直接修改正式 guideline knowledge。
2. 论文证据不能直接进入 DiagnosisAgent 的正式诊断规则。
3. 论文证据只能生成 proposal-only artifact。
4. 只有通过 Evidence Gateway 和 human review 后，才允许生成 controlled knowledge extension draft / formal knowledge extension patch preview。
5. 默认不自动 promotion，不自动覆盖正式 knowledge。
6. 不修改 knowledge registry。
7. 不修改 diagnosis rules。
8. 不覆盖 guideline 主体内容。
9. 前端必须明确显示：
   - research evidence is not guideline evidence
   - research evidence is proposal-only before approval
   - formal_knowledge_updated=false
   - promotion_requires_human_approval=true

二、支持 PubMed metadata retrieval v1

实现或补齐 ResearchEvidenceRetriever：

输入：

- disease
- modality
- research_question

要求：

1. 优先支持 PubMed metadata 检索。
2. 第一版只需要 metadata / abstract，不要求全文解析。
3. 如果网络不可用、PubMed 不可用、API 不可用，需要支持 supplied metadata fallback。
4. 检索结果必须保留 source trace，包括：
   - title
   - year
   - journal
   - PMID
   - DOI if available
   - abstract
   - query
   - retrieved_at
   - source_type
5. 不允许把论文直接写入正式 knowledge。
6. 不允许提交真实 API key。
7. 不允许提交大 PDF 或患者数据。

三、Research Evidence Extraction v1

从 PubMed metadata / abstract / supplied metadata 中抽取 normalized research evidence。

结构化字段至少包括：

- source_metadata
- study_design
- sample_size
- population
- modality
- target_disease
- proposed_imaging_finding
- proposed_measurement_or_ai_feature
- limitations
- evidence_level

要求：

1. 抽取结果必须保留 source trace。
2. 不确定字段必须标记为 unknown。
3. 不允许 LLM 编造不存在的信息。
4. 如果 abstract 中没有 sample size，就写 unknown，而不是猜测。
5. 如果 modality 不明确，就写 unknown 或 mixed，而不是强行映射。

四、Research Claim Builder v1

把 normalized research evidence 转换成 candidate claims，而不是正式 knowledge rules。

claim 类型至少包括：

- imaging_feature
- quantitative_feature
- geometric_or_morphologic_measurement
- clinical_risk_association
- differential_diagnosis_clue

每个 claim 必须包含：

- claim_id
- claim_type
- source_ids
- evidence_level
- proposed_knowledge_section
- target_disease
- modality
- guideline_conflict_status
- promotion_allowed=false by default
- diagnosis_usable_level
- limitations
- requires_human_review=true by default

要求：

1. claim 只能表示“候选补充证据”。
2. claim 不能直接成为 diagnosis rule。
3. claim 不能直接修改 guideline knowledge。
4. claim 默认 promotion_allowed=false。
5. 如果 claim 只能作为 exploratory evidence，需要明确标记 exploratory_only。

五、Evidence Gateway 接入与扩展

将 research evidence proposal / candidate claims 接入现有 Evidence Gateway。

Gateway 至少输出这些 gate status：

- source_quality
- freshness
- applicability
- modality_match
- population_match
- sample_size
- guideline_conflict
- reproducibility_or_external_validation
- human_review_required

要求：

1. 未通过 human review 前，所有 claim 都只能是 proposal-only。
2. 与 guideline 冲突的 claim 必须被标记为 conflict 或 requires_review，不能进入 controlled extension。
3. modality 不匹配的 claim 必须被降级或阻断。
4. low-quality source 不能生成可 promotion 的 extension。
5. Gateway 输出必须包含 gate report artifact。
6. formal_update 必须始终为 false。

六、Controlled Knowledge Extension / Patch Preview 接入

复用已有 controlled knowledge extension draft 和 formal_knowledge_extension_patch_preview 能力。

要求：

1. 只有 Gateway 允许并且 human review 条件满足时，才能生成 controlled knowledge extension draft。
2. 生成 patch preview 时必须明确：
   - target knowledge
   - target knowledge file preview
   - original target section
   - safe research supplement section
   - diff preview
   - sign-off checklist
   - rollback plan
   - pre-apply audit
3. patch preview 只能指向 research-mode / supplemental section。
4. 如果试图修改 diagnosis rules、guideline 主体或非 supplemental section，必须 blocked_by_pre_apply_audit。
5. 仍然不应用 patch。
6. 仍然不修改正式 knowledge。
7. 仍然不修改 registry。
8. 仍然不进入 diagnosis。

七、前端 Research Evidence Review 面板

在前端增加一个默认折叠的 Research Evidence Review 面板。

展示内容：

1. research question
2. retrieved papers / supplied metadata
3. normalized research evidence summary
4. candidate claims
5. Evidence Gateway gate status
6. proposal-only artifact path
7. controlled knowledge extension dry-run summary
8. formal knowledge extension patch preview summary
9. human review checklist
10. safety boundary badges:
    - proposal_only=true
    - formal_knowledge_updated=false
    - diagnosis_rules_modified=false
    - registry_updated=false
    - promotion_requires_human_approval=true

前端展示要求：

1. 面向医生 / 研究者阅读，不要默认堆 raw JSON。
2. raw/debug JSON 只能放在折叠的开发调试区。
3. 必须明确区分 research evidence 和 guideline evidence。
4. 必须明确显示论文证据不能直接作为诊断规则。
5. 必须显示当前 evidence 是 proposal-only / dry-run，而不是 applied update。

八、测试要求

新增或修改测试覆盖：

1. PubMed metadata retrieval 或 supplied metadata fallback。
2. 网络不可用时 fallback path 可用。
3. extraction unknown 字段不编造。
4. candidate claim 默认 promotion_allowed=false。
5. candidate claim 默认 requires_human_review=true。
6. Evidence Gateway 阻断未审核论文证据。
7. low-quality source 不能进入 controlled extension。
8. modality mismatch 会被 gate 降级或阻断。
9. guideline conflict 会被 gate 标记为 requires_review / conflict。
10. controlled knowledge extension dry-run 不修改正式 knowledge。
11. formal knowledge extension patch preview 不修改 diagnosis rules。
12. patch preview 只能写入 research-mode / supplemental section。
13. 前端 Research Evidence Review 面板展示 proposal-only 状态。
14. 前端不默认展示 raw JSON。
15. full unittest 通过。
16. git diff --check 通过。

九、本轮不做的事情

本轮不做：

1. 不做全文 PDF 解析。
2. 不训练模型。
3. 不修改正式 guideline knowledge。
4. 不修改 knowledge registry。
5. 不把 research evidence 接入正式 DiagnosisAgent 结论。
6. 不把论文证据当作 guideline evidence。
7. 不提交 API key。
8. 不提交大 PDF。
9. 不提交患者数据。
10. 不做 production 级 human approval / registry write。

十、完成标准

本轮完成后需要满足：

1. 能从 PubMed metadata 或 supplied metadata 生成 research_evidence_proposal。
2. 能从 metadata / abstract 中抽取 normalized research evidence。
3. 能生成 candidate claims。
4. Candidate claims 默认 promotion_allowed=false。
5. 能通过 Evidence Gateway 生成 proposal-only gate report。
6. 能生成 controlled knowledge extension dry-run。
7. 能生成 formal knowledge extension patch preview。
8. 前端能折叠展示 Research Evidence Review。
9. 前端明确显示 research evidence 不是 guideline evidence。
10. 正式 guideline knowledge 不被自动修改。
11. Diagnosis rules 不被修改。
12. Knowledge registry 不被修改。
13. 全量 unittest 通过。
14. 提交本轮改动。

本轮完成后，这条线可以视为 Research Evidence Ingestion v1 收敛：论文证据可以被检索、抽取、生成候选 claim、经过 Evidence Gateway 审核、生成 proposal-only / patch-preview artifact，并在前端可审阅展示；但仍然不会自动修改正式 guideline knowledge，也不会直接进入诊断规则。
