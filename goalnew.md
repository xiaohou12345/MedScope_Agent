# MedScope Agent 实时执行目标

本文档是 `goal.md` 的执行版，用来记录后续每一步要做什么、当前做到哪里、怎么验收。后续推进时优先更新本文件，不再把阶段性计划散落到其他文档。

## 0. 当前原则

- 不做一次性大重构，每轮只推进一个清晰模块。
- 先固定接口和边界，再替换真实实现。
- Agent 不直接写 provider-specific API 逻辑，统一走 `llm/`。
- 诊断医生 Agent 不直接处理像素图片。
- 视觉 Agent 不输出最终诊断，只输出影像证据。
- 无正式指南时只能生成 `data_mined_hypothesis`，不能伪装成医学指南。
- Memory 必须保存证据链，不只保存最终结论。
- 对外汇报不再讲“五个 Agent 平铺”，而是讲“上层临床证据流水线 + 底层 Agentic Runtime / Evidence Gateway”。
- 底层 gateway 负责 skill 分发、共享 artifact、工具权限、contract guards、stop hooks、self-evolving candidate queue 和 validation gate。
- self-evolving 只能进入候选队列，不能自动修改正式 guideline skill。

## 0.1 2026-05-26 架构表述更新

- 已把系统定位从“五个并列 Agent”调整为双层架构：上层 `Clinical Evidence Pipeline`，下层 `Agentic Runtime / Evidence Gateway`。
- 已补充 Claude Code / Codex 类比：主 Agent 通过 gateway 管理 skill、文件共享、工具约束和 hooks。
- 已进一步明确：五个实现类只是 MVP worker 拆分，不是论文/组会的核心贡献；核心贡献应表述为 Evidence Gateway 对 skill、文件、工具、契约、stop hooks 和候选演化的统一管理。
- 已把底层 gateway 拆成五类可控资源：Skill 系统、Shared Artifact Workspace、Tool Router、Contract Guards、Hooks/Self-evolving Queue，用于回应“为什么不是为了分 Agent 而分”的质疑。
- 已同步更新答辩 Q&A、架构图和组会状态矩阵：增加 Gateway 资源管理图、Claude Code/Codex 类比回答，以及“实现类是 worker、Evidence Gateway 是 runtime 核心”的组会口径。
- 已同步演示 runbook：前端入口改为按当前演示端口/实际启动输出为准，Gateway 章节从“下一步落地”改为“当前按 runtime trace / manifest / stop hook / queue / validation gate 展示”；旧 `mvp_status_by_agents.md` 已标记为历史追溯材料，不作为组会主叙事。
- 已同步论文方法草稿和验证路线图：方法贡献明确为 controlled medical evidence execution，不再把 agent 数量作为创新点；下一阶段验证重心调整为 reviewer notes、candidate promotion dry-run 和 evidence-bounded reasoning eval。
- 已实现 `candidate promotion dry-run` 最小闭环：`scripts/candidate_promotion_dry_run.py` 会把 reviewer accepted 的 candidate item 转成 proposal-only artifact，输出 `candidate_skill_patch` proposal，但 `formal_skill_updated=false`、`formal_guideline_updated=false`、`diagnosis_report_updated=false`。
- 已生成 dry-run 产物：`output/fake/candidate_promotion_dry_run/candidate_promotion_dry_run.json` 和 `output/fake/candidate_promotion_dry_run/candidate_promotion_dry_run.md`。
- 已实现 `evidence-bounded reasoning eval` 最小聚合评测：`scripts/evidence_bounded_reasoning_eval.py` 汇总 adopted、missing、excluded、overlap、QA 五类 case，输出 `output/fake/evidence_bounded_reasoning_eval/evidence_bounded_reasoning_eval.json` 和 `.md`。
- 当前 reasoning eval 结果：`status=passed`、`case_count=5`、`unsupported_claim_count=0`、`missing_as_negative_violation_count=0`、`excluded_fact_reuse_violation_count=0`、`overlap_double_count_violation_count=0`、`qa_grounding_violation_count=0`。
- 已生成本轮总收敛审计：`output/fake/medscope_mvp_convergence_audit.md`。该文件把架构叙事、视觉证据评测、Gateway 安全链路、promotion dry-run、reasoning eval、不能宣称内容和下一阶段真实验证扩展压成一页。
- 已明确医疗安全差异：MedScope 的 stop hooks 和 self-evolving 只产生候选记忆、候选规则或候选 skill patch，必须通过 validation gate 后才能考虑升级。
- 已修正 Phase A audit：FHN response 顶层现在可直接展示 4 个 structured visual facts、2 个 adopted facts 和 2 个 excluded facts。
- 已新增 `output/fake/vision_evidence_eval_plan.md`，明确 Phase B 视觉证据评测线、指标、命令、失败模板和收敛标准。
- 已新增 `scripts/vision_evidence_eval_summary.py`，并生成 `output/fake/vision_evidence_eval_summary.json` 和 `output/fake/vision_evidence_eval_summary.md`。
- 当前 Phase B 汇总包含 3 个 case：2 个 BraTS reference-mask case 和 1 个 FHN no-mask case。
- 已补充 BraTS 视觉评测指标：IoU、volume error、false positive / false negative component count，并支持从旧 result JSON 回填扩展指标。
- 当前 Phase B summary：`reference_mean_iou=0.489807`，`reference_mean_absolute_volume_error_ml=24.661`，`reference_false_negative_component_count=32`。
- 已补 no-mask suggested manual review labels：FHN 当前 `accepted=2`、`rejected=2`、`uncertain=0`，所有标签仍是 `pending_human_review`，不伪装成已人工确认。
- 下一步不应再重构 Agent 数量，优先把失败样例接入 candidate queue / memory audit。

## 1. 总体架构目标

```text
患者 / 前端
  -> Clinical Orchestrator
  -> Skill Gateway / Skill Builder（已有 skill 则加载，缺失 skill 才构建）
  -> Vision Evidence Agent（按 visual protocol 输出视觉证据）
  -> Diagnosis Reasoning Agent（只消费 evidence bundle）
  -> Memory / Audit Layer（写入四类 memory）
  -> Runtime Gateway Trace / Stop Hooks / Candidate Queue
  -> 前端输出解释和 QA
```

核心模块：

- Clinical Orchestrator：患者入口、任务路由、skill 选择、报告解释、后续 QA。
- Vision Evidence Agent：图像预处理、分割、病灶定位、特征提取，只返回结构化视觉证据。
- Diagnosis Reasoning Agent：医学推理，融合 skill、患者上下文和 evidence bundle，生成报告。
- Skill Gateway / Skill Builder：已有指南 skill 时加载和校验；缺失 skill 时才检索指南、抽取规则、生成候选或正式 skill。
- Memory / Audit Layer：保存 patient/image/skill/reasoning 四类记忆，支撑 evidence bundle、audit、replay 和 QA。
- Agentic Runtime / Evidence Gateway：管理 skill 分发、共享 artifact、工具权限、contract guards、stop hooks、candidate queue 和 validation gate。
- LLM/API 层：统一 DMX/KY/API 调用，Agent 不直接依赖具体 provider。

## 2. 当前完成状态

### 已完成

- [x] 建立最小可运行 MVP：输入图片路径和患者描述，输出结构化报告。
- [x] 实现高医生 Agent、诊断医生 Agent、视觉 Agent、报告 Agent。
- [x] 实现 Memory JSON 持久化。
- [x] 实现股骨头坏死 `guideline_based` skill。
- [x] 实现 `data_mined_hypothesis` 与 `guideline_based` 的边界检查。
- [x] 新增 `contracts/`，固定 Agent 间数据契约。
- [x] 新增 `docs/architecture/boundaries.md`，说明后续可替换点。
- [x] 新增 `llm/`，统一模型 API 抽象。
- [x] 新增 `docs/API_ROUTE_LOG.md`，默认按日志选择 DMX/KY。
- [x] 高医生 Agent 支持可选 LLM 解释；无 API 时保留离线 fallback。
- [x] 当前测试覆盖 124 项，`python -m unittest discover -v` 通过。
- [x] 新增仓库内 API smoke check：`python -m scripts.api_smoke_test`。
- [x] DMX 路由已更新为 `https://anyaigc.com` + `deepseek-v4-pro`。
- [x] 真实 API smoke 已成功返回 `pong`。
- [x] 诊断医生 Agent 支持可选 LLM Prompt 工作流，并具备 JSON 校验和规则 fallback。
- [x] 诊断医生 LLM 工作流已增加 visual completeness 安全校验：LLM 若把 missing/null 视觉证据写成 0、阴性或未见，会被拒绝并走规则 fallback。
- [x] 视觉 Agent 契约已扩展为同时输出 `image_outputs` 和 `visual_evidence`。
- [x] 视觉 Agent 契约已扩展 `visual_evidence.measurements` 与 `visual_evidence.completeness`，用于区分“已支持证据”和“缺模态/未评估证据”。
- [x] 新增 BraTS / 成人弥漫性胶质瘤测试线计划和 disease skill。
- [x] BraTS Phase A 已支持读取 2D mask、生成 overlay PNG、提取基础肿瘤区域特征。
- [x] NIfTI/BraTS volume reader 已通过真实 BraTS2021 `.nii.gz` 样本验证，支持 3D label 统计和体素体积计算。
- [x] 真实 BraTS2021 样本已下载到 `data/external/brats2021_00030/`，并生成确认 overlay：`output/real/brats2021_00030_flair_overlay.png`。
- [x] BraTS / 胶质瘤视觉 Agent 测试线已有可执行入口：`python -m scripts.brats_vision_test_line`，支持 ground-truth 与 MedSAM2 模式，默认输出到 `output/fake/brats_vision_test_line/`。
- [x] 已新增 MedSAM2 分割后端适配层，Vision Agent 可通过模型生成 mask 后继续输出 overlay 和结构化证据。
- [x] 胶质瘤/BraTS 主流程已接入高医生 Agent：CLI/API/service 可传 `disease_key=diffuse_glioma_brats`、`vision_mode`、`mask_path`，由高医生统一分发到视觉 Agent 和诊断 Agent。
- [x] 高医生主流程会把胶质瘤视觉输出的 `image_outputs`、`visual_evidence.measurements`、`visual_evidence.completeness` 写入 case memory。
- [x] 诊断医生规则 fallback 已支持胶质瘤报告文案，明确影像只支持辅助判断，最终整合诊断需要病理和分子证据。

### 当前仍是模拟/待替换

- [x] 视觉 Agent 已支持 BraTS ground truth mask reader demo，并已用真实 NIfTI 样本验证文本证据和 overlay 图像输出。
- [x] MedSAM2 已接入为可插拔 runner；真实推理仍需配置外部 MedSAM2 代码、权重和运行环境。
- [x] 指南检索已有离线/可控工具桩；真实网络搜索/数据库还未接入。
- [x] 诊断医生 Agent 已有 LLM prompt 工作流；默认 CLI 仍走规则 fallback，避免无 API 时不可用。
- [x] 高医生 QA 已能通过统一入口读取既有 case memory 回答追问；仍未做完整多轮对话管理。
- [x] API 连通性已通过仓库内 smoke test 跑通；密钥不落盘，只通过环境变量临时注入。

## 3. 下一步执行顺序

### Step 1：API 连通性与真实 ModelClient

目标：确认 DMX 或自部署 KY 哪条路能真实调用，并把真实调用控制在 `llm/` 内。

要做：

- [x] 读取 `docs/API_ROUTE_LOG.md`，确认 `active_route`。
- [x] 按项目记忆使用默认连通性脚本：

```bash
python /Users/4paradigm/Documents/project/cloudgpt_client_example.py
```

- [x] 根据脚本结果更新 `docs/API_ROUTE_LOG.md`。
- [x] 补仓库内 API smoke check，默认只做离线检查，不在单元测试中联网。
- [x] 保证 Agent 只依赖 `PromptRunner`，不直接读 API key。
- [x] 提供真实 API key、base_url、model 后，运行 `python -m scripts.api_smoke_test --real`。

验收：

```bash
python -m unittest discover -v
python -c "from llm.model_client import ApiRouteLog; r=ApiRouteLog.from_file('docs/API_ROUTE_LOG.md'); print(r.active_route, r.model_for_active_route())"
```

完成标准：

- [x] 能明确当前走 DMX 还是 KY。
- [x] 没有 provider-specific 代码进入 `agents/`。

### Step 2：补诊断医生 Agent 的 LLM Prompt 工作流

目标：诊断医生不再只靠硬编码规则，而是能把患者信息、skill、视觉证据组织成 LLM prompt，输出结构化报告。

要做：

- [x] 新增 `prompts/diagnosis_agent_prompt.md`。
- [x] 新增诊断报告 JSON 输出约束。
- [x] 诊断医生 Agent 增加可选 `PromptRunner`。
- [x] 无 API 或 LLM 输出不合格时，保留规则 fallback。
- [x] 测试 LLM 输出不能缺少：诊断倾向、影像依据、分期判断、不确定性说明、建议进一步检查、治疗建议。

验收：

```bash
python -m unittest discover -v
```

完成标准：

- [x] 诊断医生仍只吃结构化证据，不读原始图片。
- [x] LLM 只参与报告生成，不越权做视觉分析。

### Step 3：补高医生 Agent 意图识别和 QA

目标：高医生能区分初诊、报告解释、追问、复查，而不是所有输入都走同一条诊断流程。

要做：

- [x] 定义 intent contract。
- [x] 支持 `diagnosis`、`qa`、`review`、`report_explanation`。
- [x] QA 优先读取 `reasoning_memory` 和 `image_memory`。
- [x] 禁止 QA 编造 memory 中不存在的证据。

验收：

```bash
python -m unittest discover -v
```

完成标准：

- 患者问“你刚才说哪里异常？”时能基于 memory 回答。
- 患者问新诊断时才创建新 case。

### Step 4：补指南检索和 Skill Builder

目标：诊断医生能从疾病方向触发指南检索，生成或复用 disease skill。

要做：

- [x] 新增 `tools/guideline_search_tool.py`。
- [x] 新增 `tools/evidence_summary_tool.py`。
- [x] 有正式指南时生成 `guideline_based` skill。
- [x] 无正式指南时进入 `evidence_summary_mode`，生成 `data_mined_hypothesis`。
- [x] Skill 支持显式写入 `skills/`；进入 `skill_memory` 的流程已有报告链路覆盖。

验收：

```bash
python -m unittest discover -v
```

完成标准：

- 不把数据总结产物叫医学指南。
- skill 中必须有 `source`、`evidence_level`、`skill_type`。

### Step 5：补 BraTS / 胶质瘤视觉 Agent 测试线

目标：在不改诊断医生的情况下，把模拟视觉 JSON 替换为 BraTS 风格的图像产物 + 结构化视觉证据。第一阶段不训练模型，先读取 ground truth mask。

要做：

- [x] 扩展视觉输出契约：同时支持 `image_outputs` 和 `visual_evidence`。
- [x] 新增 `skills/diffuse_glioma_brats.yaml`。
- [x] 新增 `docs/datasets/brats_glioma_plan.md`。
- [x] 新增 `tools/mask_reader_tool.py`。
- [x] 新增 `tools/overlay_generation_tool.py`。
- [x] 新增 `tools/segmentation_tool.py`。
- [x] 新增 `tools/feature_extraction_tool.py`。
- [x] 视觉 Agent 内部调用工具，但输出仍是 `VisualAnalysisResult`。
- [x] 支持 original image、mask、overlay 三类图像产物。
- [x] 支持 whole tumor / tumor core / enhancing tumor 的量化特征。
- [x] 新增 NIfTI/BraTS volume reader 接口，当前通过 fake loader 测试 3D volume。
- [x] 安装 `nibabel` 并用真实 BraTS `.nii.gz` 样例验证。
- [x] 新增 `scripts/brats_vision_test_line.py`，可直接跑真实 BraTS2021 样本并产出 overlay + JSON 视觉证据。
- [x] `scripts/brats_vision_test_line.py` 支持 `--mode medsam2`，模型 mask 默认写到 `output/fake/`，不覆盖 ground-truth mask。
- [x] `scripts/brats_vision_test_line.py` 支持 `--reference-mask`，可输出 whole tumor / tumor core / enhancing tumor Dice。
- [x] 新增 `data/external/brats_manifest.json`，测试线支持 `--manifest` 和 `--case-id` 选择病例。
- [x] `scripts/brats_vision_test_line.py` 支持 `--validate-manifest`，可在运行 VisionAgent 前检查 `cases` 非空和病例路径完整性。
- [x] `scripts/brats_vision_test_line.py` 支持 `--check-medsam2`，可在真实推理前同时检查 BraTS manifest、MedSAM2 runner 配置和命令模板必要占位符。
- [x] `MedSAM2CommandRunner.from_env()` 会在创建真实 runner 前硬校验命令模板占位符、`MEDSAM2_TIMEOUT_SECONDS` 和 `MEDSAM2_REPO_PATH`，配置不合格时抛出 `MissingMedSAM2BackendError`。
- [x] `scripts/brats_vision_test_line.py` 支持 `--prompt-from-reference-mask`，可从 BraTS reference mask 生成 MedSAM2 测试 prompt，并写入 `segmentation_prompt`。
- [x] `scripts/brats_vision_test_line.py` 支持 `--generate-prompts`，可批量生成每例 `*_prompt.json`、`*_prompt_overlay.png`、`prompts_summary.json` 和 `prompts_summary.md`，不运行模型。
- [x] 新增 `scripts/medsam2_brats_wrapper.py`，把 BraTS NIfTI、`prompt_json` 和单个输出 mask 路径桥接到官方 MedSAM2 predictor 调用，并支持 `--dry-run` 与 `--print-command-template`。
- [x] 已用真实 `MedSAM2_latest.pt` 在 CPU 上跑通 BraTS2021 `BraTS2021_00030` 单例 MedSAM2 推理，产出模型 mask、overlay、结构化视觉证据和 Dice。
- [x] 修复 manifest + MedSAM2 模式避免覆盖 ground-truth mask：`mask_path` 只在 `ground_truth` 模式默认取 manifest 标注，`medsam2` 模式默认写 `*_medsam2_mask.nii.gz`。
- [x] `scripts/brats_vision_test_line.py` 支持 `--all-cases` 批量运行 manifest，并写入 `summary.json`。
- [x] `summary.json` 已包含 `aggregate.mean_*_dice` 和 `failed_case_ids`，支持批量结果快速审计。
- [x] 批量运行同时写入 `summary.md`，用表格展示每例状态、Dice 和产物路径。
- [x] 批量 manifest 模式会捕获单例异常并输出 `partial_error`，避免未配置 MedSAM2 时整批直接中断。
- [x] `skills/diffuse_glioma_brats.yaml` 已新增 `visual_protocol`，明确 adult diffuse glioma 的分割目标、测量字段和各目标所需 MRI 模态。
- [x] BraTS 视觉测试线已通过 `SkillBuilderTool.load_guideline_skill("diffuse_glioma_brats")` 加载 guideline skill，不再只传裸 `disease_name`。
- [x] Vision Agent 已根据 `visual_protocol` 生成 `disease_target`、`measurements`、`completeness`，例如仅 FLAIR 输入时 whole tumor 为 `supported`，tumor core / enhancing tumor 为 `missing`。
- [x] Diagnosis Agent 已读取视觉证据 completeness，并在报告不确定性中说明缺失字段不能被解释为阴性或数值 0。
- [x] 真实 BraTS ground-truth 脚本已验证输出同时包含分割图路径、结构化测量、证据充分性和 Dice 评估。

验收：

```bash
python -m scripts.brats_vision_test_line
python -m scripts.brats_vision_test_line --validate-manifest --manifest data/external/brats_manifest.json
python -m scripts.brats_vision_test_line --generate-prompts --manifest data/external/brats_manifest.json
python -m scripts.brats_vision_test_line --check-medsam2 --manifest data/external/brats_manifest.json
python -m unittest discover -v
python app.py --image data/images/demo_xray.png --message 左髋疼痛三个月 --risk-factor 饮酒史
```

完成标准：

- 诊断医生代码不需要因为真实视觉模型而大改。
- 视觉 Agent 仍不输出最终诊断。
- 视觉 Agent 同时输出分割图路径和文本/JSON 证据。

### Step 6：Memory 后端增强

目标：让 memory 支持查询、复用 skill、多轮 QA，但先不急着上复杂向量数据库。

要做：

- [x] 增加按 case_id 查询。
- [x] 增加按 disease 查询 skill memory。
- [x] 增加历史 QA memory。
- [x] 保留 JSON 后端，后续再考虑 SQLite/PostgreSQL。

验收：

```bash
python -m unittest discover -v
```

完成标准：

- Memory 能支撑“刚才哪里异常”“为什么建议 MRI”“之前用的哪个 skill”。

### Step 7：封装 API / 前端入口

目标：给前端或服务调用一个稳定入口，不让前端绕过高医生 Agent。

要做：

- [x] 选择 CLI / service layer 入口方式；暂不引入 FastAPI 依赖。
- [x] API/service 只调用 `GaoDoctorAgent.handle_message()`。
- [x] 输入输出沿用 contract。
- [x] 增加最小接口测试。

验收：

```bash
python -m unittest discover -v
```

完成标准：

- 前端/API 不直接调用诊断医生或视觉 Agent。

### Step 8：胶质瘤端到端病例流

目标：把已经跑通的 BraTS / Guideline-aware Visual Protocol 接入完整 5-Agent 主流程，而不是停留在单独测试线。

要做：

- [x] `MedScopeService.handle_request()` 支持透传 `disease_key`、`vision_mode`、`mask_path`、`segmentation_prompt`。
- [x] CLI 支持 `--disease-key`、`--vision-mode`、`--mask`，仍统一调用 service 入口。
- [x] `GaoDoctorAgent.handle_message()` 支持按 `disease_key` 分流；默认股骨头流程不变。
- [x] `disease_key=diffuse_glioma_brats` 时，高医生加载 `diffuse_glioma_brats` skill，并调用 BraTS ground-truth 或 MedSAM2 视觉路径。
- [x] case memory 的 `image_memory` 保存 `image_outputs`，同时保存结构化视觉证据和 completeness。
- [x] 诊断医生 Agent 对胶质瘤 skill 生成胶质瘤方向报告，且不把 missing 视觉字段解释为 0。

验收：

```bash
python app.py --image data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz --mask data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz --message 请基于这次FLAIR_MRI做胶质瘤辅助分析 --disease-key diffuse_glioma_brats --vision-mode ground_truth --symptom 头痛
python -m unittest discover -v
```

完成标准：

- 患者入口仍只调用高医生 Agent。
- 高医生不直接做视觉分析，只做分发和记忆保存。
- 诊断医生只读取结构化视觉证据，不读原始图片。
- 胶质瘤报告和 memory 能追溯缺 T1ce 导致 `enhancing_tumor` 为 missing。

## 4. 每轮更新格式

每完成一轮，需要更新这里：

```text
日期：
本轮目标：
修改文件：
验证命令：
验证结果：
下一步：
风险/待确认：
```

## 5. 实时进展日志

### 2026-05-23

本轮目标：建立 MVP、固定边界、补 API 抽象层。

修改文件：

- `app.py`
- `agents/`
- `contracts/`
- `llm/`
- `memory/`
- `tools/`
- `skills/femoral_head_necrosis.yaml`
- `prompts/gaodoctor_prompt.md`
- `prompts/diagnosis_agent_prompt.md`
- `docs/API_ROUTE_LOG.md`
- `docs/architecture/boundaries.md`
- `docs/datasets/brats_glioma_plan.md`
- `tests/`

验证命令：

```bash
python -m unittest discover -v
python app.py --image data/images/demo_xray.png --message 左髋疼痛三个月 --risk-factor 饮酒史
```

验证结果：

- 33 个单元测试通过。
- CLI 能生成报告并保存 case memory。
- `python -m scripts.api_smoke_test` 能输出路由检查 JSON。
- 使用临时环境变量运行 `python -m scripts.api_smoke_test --real`，真实 API 返回 `pong`。
- 诊断医生 LLM 工作流支持：合法 JSON 报告、非法 JSON fallback、缺字段 fallback。
- 视觉契约支持 `image_outputs.original_image_path`、`mask_path`、`overlay_path`。
- 新增 BraTS / 成人弥漫性胶质瘤 skill，作为下一条测试线。
- BraTS Phase A demo 可读取 2D mask、生成 overlay PNG、提取 whole tumor / tumor core / enhancing tumor 特征。
- NIfTI reader 可统计 3D label，并按 header zooms 计算体素体积。
- 真实 BraTS2021 样本 `BraTS2021_00030` 已下载到 `data/external/brats2021_00030/`。
- 真实样本输出体积：whole tumor `117.996 ml`，tumor core `39.404 ml`，enhancing tumor `27.185 ml`。
- 已生成真实 overlay PNG：`output/real/brats2021_00030_flair_overlay.png`。

下一步：

- 下一步建议进入 Step 4：补指南检索和 Skill Builder，先做离线/可控的 guideline search contract，不直接上复杂搜索系统。

风险/待确认：

- `/Users/4paradigm/Documents/project/cloudgpt_client_example.py` 当前不存在，执行报错 `No such file or directory`。
- `DMX_API_KEY` 不写入仓库；每次真实调用需要由环境变量注入。
- 真实 API 已可用；后续接真实 Agent prompt 时仍需要保留结构化输出校验和 fallback。

### 2026-05-23 Step 3 追加

本轮目标：补高医生 Agent 意图识别和 QA 最小闭环，不做大重构。

修改文件：

- `contracts/medical_contracts.py`
- `agents/gaodoctor_agent.py`
- `tests/test_contracts.py`
- `tests/test_mvp_flow.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests.test_contracts.ContractBoundaryTest.test_patient_intent_contract_supports_four_entry_routes -v
python -m unittest tests.test_mvp_flow.MedScopeMvpFlowTest.test_gaodoctor_routes_follow_up_qa_to_existing_memory -v
python -m unittest tests/test_contracts.py tests/test_mvp_flow.py -v
python -m unittest discover -v
```

验证结果：

- 新增 `PatientIntent` contract，限制 `diagnosis`、`qa`、`review`、`report_explanation` 四类入口。
- 新增 `GaoDoctorAgent.handle_message()`，保留原 `handle_patient_case()` 不变。
- 患者问“你刚才说哪里异常？”时，会基于既有 `reasoning_memory` 和 `image_memory` 回答，不新建 case。
- 测试覆盖 QA 不编造 `MRI 显示` 这类 memory 中不存在的证据。
- 当前 `python -m unittest discover -v`：35 个测试通过。

下一步：

- 进入 Step 5/Step 6 的后续小步：可以先补 `segmentation_tool.py` 抽象，或增强 Memory 的按 case/disease 查询。

风险/待确认：

- 当前 intent 识别是轻量规则，不是完整 NLU；后续可接 LLM，但必须保留 contract 校验和 fallback。
- `review` 目前复用诊断流程并记录 `previous_case_id`，还没有实现真正的跨 case 对比。

### 2026-05-23 Step 4 追加

本轮目标：补指南检索和 evidence summary 的最小可控工具链，固定 `guideline_based` 与 `data_mined_hypothesis` 的边界。

修改文件：

- `tools/guideline_search_tool.py`
- `tools/evidence_summary_tool.py`
- `tools/skill_builder_tool.py`
- `agents/diagnosis_agent.py`
- `tests/test_guideline_skill_builder.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_guideline_skill_builder.py -v
python -m unittest tests/test_mvp_flow.py tests/test_contracts.py -v
python -m unittest discover -v
```

验证结果：

- `GuidelineSearchTool` 提供离线指南索引，不联网，用于先固定工具输入输出。
- `EvidenceSummaryTool` 生成 `evidence_summary_mode`，强制 `source_type=internal_dataset_summary`、`evidence_level=low`、带 warning。
- `SkillBuilderTool.prepare_skill()` 现在流程为：已有 skill 文件优先；否则查离线指南；仍无指南才生成 hypothesis skill。
- 有指南候选时生成 `guideline_based/high/medical_guideline`。
- 无指南时生成 `data_mined_hypothesis/low/internal_dataset_summary`，不会伪装成医学指南。
- 生成 skill 支持 `persist=True` 时显式写入 `skills/`，默认不落盘，避免污染真实 skill 目录。
- 当前 `python -m unittest discover -v`：40 个测试通过。

下一步：

- 建议进入 Step 6：增强 Memory 的按 case/disease 查询，支撑多轮 QA 和 skill 复用。

风险/待确认：

- 当前 `GuidelineSearchTool` 是离线索引，不代表真实完整指南检索；接真实数据库/网络搜索前仍需要 source 审核、时间版本和引用记录。

### 2026-05-23 Step 5 追加

本轮目标：补 `segmentation_tool.py` 抽象，把当前 ground truth mask reader 和未来真实分割模型的替换点固定住。

修改文件：

- `tools/segmentation_tool.py`
- `agents/vision_agent.py`
- `tests/test_segmentation_tool.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_segmentation_tool.py tests/test_brats_vision_tools.py tests/test_real_brats_sample.py -v
python -m unittest discover -v
```

验证结果：

- 新增 `SegmentationTool.segment_from_mask()`，统一包装 mask reader、overlay generator、feature extractor。
- `VisionAgent.analyze_brats_ground_truth()` 已通过 `SegmentationTool` 边界获取 mask/overlay/features。
- `VisionAgent.analyze_brats_nifti_ground_truth()` 也通过 `SegmentationTool` 包装 NIfTI reader/overlay。
- 当前 ground truth mask 与未来真实模型的替换点集中到 `SegmentationTool`，不需要改诊断医生 Agent。
- 当前 `python -m unittest discover -v`：42 个测试通过。

下一步：

- 进入 Step 7：封装一个稳定 API/前端入口，确保外部只走高医生 Agent。

风险/待确认：

- `SegmentationTool` 当前只包装 ground truth mask，不运行真实模型；接 nnU-Net/MONAI/MedSAM 时应扩展工具内部，不改 Agent contract。

### 2026-05-23 Step 6 追加

本轮目标：增强 Memory 查询与 QA 历史，继续保留 JSON 后端。

修改文件：

- `memory/memory_manager.py`
- `agents/gaodoctor_agent.py`
- `tests/test_memory_manager.py`
- `tests/test_mvp_flow.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_memory_manager.py -v
python -m unittest tests.test_mvp_flow.MedScopeMvpFlowTest.test_gaodoctor_routes_follow_up_qa_to_existing_memory tests.test_mvp_flow.MedScopeMvpFlowTest.test_gaodoctor_runs_case_and_persists_traceable_memory -v
python -m unittest discover -v
python app.py --image data/images/demo_xray.png --message 左髋疼痛三个月 --risk-factor 饮酒史
```

验证结果：

- `MemoryManager.get_case_by_id()` 可按 case_id 读取完整 case memory。
- `MemoryManager.find_cases_by_disease()` 可按 `skill_memory.disease` 查询历史 case。
- `MemoryManager.append_qa_memory()` 可把追问与回答追加到同一个 case 的 `qa_memory`。
- 新保存的 case 默认包含 `qa_memory: []`；读取旧 case 时会自动补默认字段。
- `GaoDoctorAgent.answer_follow_up()` 现在回答后会保存 QA history。
- 当前 `python -m unittest discover -v`：45 个测试通过。

下一步：

- 进入 Step 7：选择一个最小 API 入口，优先只暴露高医生 Agent，避免前端绕过诊断链路。

风险/待确认：

- 当前仍是 JSON 文件扫描，适合 MVP；如果 case 数量上来，需要再换 SQLite/PostgreSQL 或索引。

### 2026-05-23 Step 7 追加

本轮目标：封装最小 API/前端 service 入口，外部只走高医生 Agent。

修改文件：

- `api/__init__.py`
- `api/service.py`
- `app.py`
- `tests/test_service_entrypoint.py`
- `tests/test_cli_entrypoint.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_service_entrypoint.py tests/test_cli_entrypoint.py -v
python -m unittest discover -v
python app.py --image data/images/demo_xray.png --message 左髋疼痛三个月 --risk-factor 饮酒史
```

验证结果：

- 新增 `MedScopeService.handle_request()`，作为 CLI/API/前端可复用入口。
- Service 只持有 `GaoDoctorAgent`，不直接持有或暴露诊断医生 Agent、视觉 Agent。
- 初诊 payload 和 QA payload 都通过 `GaoDoctorAgent.handle_message()` 进入系统。
- CLI 已改为复用 `MedScopeService`，不再直接构造高医生诊断流程。
- 当前 `python -m unittest discover -v`：49 个测试通过。

下一步：

- 后续如要上 FastAPI，只需要薄封装 `MedScopeService.handle_request()`，不需要改五个 Agent 主链路。

风险/待确认：

- 当前是 service layer，不是常驻 HTTP 服务；如果需要浏览器/前端调试，再加 FastAPI 或简单 Web UI。

### 2026-05-23 Step 7 HTTP 追加

本轮目标：在 service layer 外增加无额外依赖的 HTTP API 适配层。

修改文件：

- `api/http_server.py`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_http_entrypoint.py tests/test_service_entrypoint.py tests/test_cli_entrypoint.py -v
python -m unittest discover -v
```

验证结果：

- 新增 `GET /health`，返回 `{"status": "ok"}`。
- 新增 `POST /v1/medscope`，接收 JSON payload 并调用 `MedScopeService.handle_request()`。
- HTTP 层不直接调用诊断医生 Agent 或视觉 Agent。
- 单元测试使用纯函数 `dispatch_http_request()`，避免测试依赖本地端口权限。
- 当前 `python -m unittest discover -v`：53 个测试通过。

下一步：

- 如果要给前端联调，可以运行 `python -m api.http_server --host 127.0.0.1 --port 8000`。

风险/待确认：

- 当前 HTTP server 使用 Python 标准库，适合 MVP；生产或前端长期联调建议再薄封装 FastAPI。

### 2026-05-23 MedSAM2 追加

本轮目标：按用户要求把分割模型方向切到 MedSAM2，并保持现有 Agent 边界不大改。

修改文件：

- `tools/medsam2_segmentation_tool.py`
- `tools/segmentation_tool.py`
- `agents/vision_agent.py`
- `scripts/medsam2_smoke_test.py`
- `tests/test_medsam2_segmentation_tool.py`
- `tests/test_medsam2_smoke_test.py`
- `docs/datasets/medsam2_runner_config.md`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_medsam2_segmentation_tool.py -v
python -m unittest tests/test_medsam2_smoke_test.py -v
python -m unittest tests/test_segmentation_tool.py tests/test_brats_vision_tools.py tests/test_real_brats_sample.py -v
python -m unittest discover -v
```

验证结果：

- 新增 `MedSAM2SegmentationTool`，作为 MedSAM2 runner 的适配层。
- 新增 `MedSAM2CommandRunner`，通过环境变量配置外部 MedSAM2 推理命令，不把权重和第三方仓库耦合进 Agent 代码。
- 新增 `python -m scripts.medsam2_smoke_test`，默认 dry-run 检查 MedSAM2 runner 配置，`--real` 时才实际调用外部命令并把测试 mask 写到 `output/fake/`。
- 未配置 runner 时会抛出清晰的 `MissingMedSAM2BackendError`，不伪装成本地已可真实推理。
- `SegmentationTool.segment_with_model()` 已支持模型生成 mask，然后复用 overlay 和 feature extraction 流程。
- `VisionAgent.analyze_brats_with_segmentation_model()` 已支持模型分割路径，输出仍是 `VisualAnalysisResult`。
- 新增 `docs/datasets/medsam2_runner_config.md`，记录 `MEDSAM2_REPO_PATH`、`MEDSAM2_COMMAND_TEMPLATE`、`MEDSAM2_TIMEOUT_SECONDS` 的配置方式。
- 当前 `python -m unittest discover -v`：66 个测试通过。

下一步：

- 对接真实 MedSAM2 runner：需要在外部 MedSAM2 环境中准备代码、checkpoint/权重、设备和 wrapper 脚本，再填入 `MEDSAM2_COMMAND_TEMPLATE`。

风险/待确认：

- 当前完成的是 MedSAM2 接入边界和可测试适配层；真实推理还没有下载/加载 MedSAM2 权重。

### 2026-05-23 BraTS 视觉测试线入口追加

本轮目标：把 BraTS / 胶质瘤视觉 Agent 能力从单元测试提升为可直接执行的测试线入口，并补 MedSAM2 模式。

修改文件：

- `scripts/brats_vision_test_line.py`
- `tools/brats_evaluation_tool.py`
- `tests/test_brats_vision_test_line.py`
- `data/external/brats_manifest.json`
- `docs/datasets/brats_glioma_plan.md`
- `docs/datasets/medsam2_runner_config.md`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_brats_vision_test_line.py -v
python -m scripts.brats_vision_test_line
python -m scripts.brats_vision_test_line --manifest data/external/brats_manifest.json --all-cases
python -m unittest tests/test_real_brats_sample.py tests/test_brats_vision_test_line.py -v
python -m unittest discover -v
```

验证结果：

- 新增 `python -m scripts.brats_vision_test_line`，默认读取真实 BraTS2021 `BraTS2021_00030` 样本。
- 新增 `data/external/brats_manifest.json`，同一入口可通过 `--manifest` 和 `--case-id` 选择病例。
- 支持 `--validate-manifest`，新增病例前可先检查 `cases` 非空，以及 `case_id`、`image_path`、`mask_path`、`reference_mask_path` 是否完整且存在。
- 支持 `--check-medsam2`，真实推理前可同时检查 BraTS manifest、`MEDSAM2_COMMAND_TEMPLATE` 必要占位符、`MEDSAM2_REPO_PATH` 和 `MEDSAM2_TIMEOUT_SECONDS`，该命令不调用真实模型。
- 支持 `--prompt-from-reference-mask`，真实 MedSAM2 测试前可从 BraTS reference mask 生成 2D/3D bbox prompt；该模式仅用于测试/评估，不代表无标注自动分割。
- 支持 `--generate-prompts`，可只生成每例 prompt JSON、bbox overlay PNG、`prompts_summary.json` 和 `prompts_summary.md` 做人工审计，不调用 MedSAM2。
- 支持 `--all-cases` 批量运行 manifest，输出每例结果、`summary.json` 和 `summary.md`。
- `summary.json` 聚合输出平均 Dice 和失败病例列表，方便真实模型批量评估。
- `summary.md` 以人工可读表格列出每例状态、Dice、overlay 和 result 路径。
- 批量模式会捕获单例异常；未配置 MedSAM2 时会记录失败 case 和错误信息，summary 仍会落盘。
- 默认输出 overlay 和 JSON 视觉证据到 `output/fake/brats_vision_test_line/`，避免未确认运行结果进入 `output/real/`。
- 同一入口已支持 `--mode medsam2`，通过 MedSAM2 runner 生成模型 mask，再复用 NIfTI overlay 和特征提取流程。
- MedSAM2 模式默认输出 `*_medsam2_mask.nii.gz`，避免覆盖真实 BraTS ground-truth mask。
- MedSAM2 模式可传入 `--reference-mask`，输出 whole tumor、tumor core、enhancing tumor 的 Dice 指标。
- `MedSAM2CommandRunner.from_env()` 现在会复用 dry-run readiness 逻辑，真实 runner 创建前即拒绝缺少 `{image_path}`、`{output_mask_path}`、`{prompt_json}` 的命令模板、非法 timeout 或不存在的 repo 路径。
- 输出仍保持 `VisualAnalysisResult`，包含 `image_outputs` 和 `visual_evidence`，不包含最终诊断字段。
- 当前 `python -m unittest discover -v`：82 个测试通过。

下一步：

- 使用真实 MedSAM2 环境运行 `python -m scripts.brats_vision_test_line --mode medsam2 --reference-mask ...`，生成模型 mask、overlay、视觉证据和 Dice 对比。

风险/待确认：

- 当前 MedSAM2 模式已通过 fake runner 验证完整链路；真实推理需要外部环境配置完成后再跑。

### 2026-05-23 MedSAM2 BraTS Wrapper 追加

本轮目标：补官方 MedSAM2 与 MedScope BraTS 单例测试线之间的薄封装，减少后续真实推理接入时对 Agent 主链路的改动。

修改文件：

- `scripts/medsam2_brats_wrapper.py`
- `tests/test_medsam2_brats_wrapper.py`
- `docs/datasets/medsam2_runner_config.md`
- `docs/datasets/brats_glioma_plan.md`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_medsam2_brats_wrapper.py -v
python -m scripts.medsam2_brats_wrapper --print-command-template --medsam2-repo /private/tmp/medscope_medsam2_probe --checkpoint /private/tmp/medscope_medsam2_probe/checkpoints/MedSAM2_latest.pt --cfg /private/tmp/medscope_medsam2_probe/sam2/configs/sam2.1_hiera_t512.yaml
python -m scripts.medsam2_brats_wrapper --image data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz --output output/fake/brats_vision_test_line/brats2021_00030_medsam2_wrapper_dry_mask.nii.gz --prompt-json '{"slice_index": 100, "boxes": [[60, 133, 124, 193]], "label_ids": [1, 2, 4]}' --medsam2-repo /private/tmp/medscope_medsam2_probe --checkpoint /private/tmp/medscope_medsam2_probe/checkpoints/MedSAM2_latest.pt --cfg /private/tmp/medscope_medsam2_probe/sam2/configs/sam2.1_hiera_t512.yaml --dry-run
python -m unittest discover -v
```

验证结果：

- 已临时克隆官方 MedSAM2 到 `/private/tmp/medscope_medsam2_probe` 核对脚本接口；不放入项目目录。
- 官方标准 3D 脚本偏 CT_DeepLesion 批处理，RECIST 脚本偏 NPZ/RECIST 标记；MedScope 侧新增 wrapper 承接 BraTS NIfTI + bbox prompt JSON。
- `scripts/medsam2_brats_wrapper.py` 支持校验 `slice_index`、`boxes`、图像路径、repo、checkpoint、cfg。
- `--print-command-template` 可直接生成包含 `{image_path}`、`{output_mask_path}`、`{prompt_json}` 的 `MEDSAM2_COMMAND_TEMPLATE`。
- 已下载单个 `MedSAM2_latest.pt` 到 `/private/tmp/medscope_medsam2_probe/checkpoints/`，未运行官方 `download.sh` 全量下载。
- 已安装最小依赖 `hydra-core`、`iopath`、`torchvision`，当前 `torch` 为 `2.12.0`；本机无 CUDA/MPS，因此用 CPU 验证。
- 已修复 wrapper 的 Hydra config 路径转换：外部绝对 cfg 路径会转换为官方 builder 需要的 `configs/sam2.1_hiera_t512.yaml`。
- 已修复 `MedSAM2CommandRunner` 在设置 `MEDSAM2_REPO_PATH` 作为 cwd 后相对路径失效的问题：传给外部 runner 的 image/output 路径现在会先 resolve 为绝对路径。
- 已修复 manifest + MedSAM2 模式可能把 ground-truth `mask_path` 当模型输出路径的问题，避免覆盖真实标注。
- 真实 BraTS2021 `BraTS2021_00030` 已通过 MedSAM2 CPU 推理，输出：
  - `output/fake/brats_vision_test_line/brats2021_00030_medsam2_mask.nii.gz`
  - `output/fake/brats_vision_test_line/brats2021_00030_medsam2_overlay.png`
  - `output/fake/brats_vision_test_line/brats2021_00030_medsam2_vision_result.json`
- 当前 Dice：whole tumor `0.9394868934746236`，tumor core `0.4929657650363098`，enhancing tumor `0.0`。
- 当前 `python -m unittest discover -v`：92 个测试通过。

下一步：

- 下一步可人工检查真实 MedSAM2 overlay，确认后把可归档产物复制到 `output/real/`；或者继续扩展第二个 BraTS case 做批量稳定性验证。

风险/待确认：

- 当前真实推理是在 CPU 上完成，速度慢；后续 GPU 环境只需替换 `--device cuda` 和对应依赖。
- BraTS 是 MRI，官方公开示例主要偏 CT/RECIST；当前 whole tumor Dice 已可用，但 enhancing tumor Dice 为 `0.0`，需要人工 overlay 审计和更多病例验证。

### 2026-05-23 胶质瘤端到端主流程追加

本轮目标：把 Guideline-aware Visual Protocol 从 BraTS 测试线接入完整高医生入口，形成胶质瘤病例的最小端到端闭环。

修改文件：

- `app.py`
- `api/service.py`
- `agents/gaodoctor_agent.py`
- `agents/diagnosis_agent.py`
- `tests/test_cli_entrypoint.py`
- `tests/test_service_entrypoint.py`
- `tests/test_mvp_flow.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_cli_entrypoint.py tests/test_service_entrypoint.py tests/test_mvp_flow.py tests/test_diagnosis_llm_workflow.py -v
python app.py --image data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz --mask data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz --message 请基于这次FLAIR_MRI做胶质瘤辅助分析 --disease-key diffuse_glioma_brats --vision-mode ground_truth --symptom 头痛
python -m unittest discover -v
```

验证结果：

- `MedScopeService.handle_request()` 现在可透传 `disease_key`、`vision_mode`、`mask_path`、`segmentation_prompt`，但 service 仍只持有高医生 Agent。
- CLI 新增 `--disease-key`、`--vision-mode`、`--mask`，继续统一调用 service。
- `GaoDoctorAgent.handle_message()` 支持胶质瘤病例参数，默认股骨头坏死路径保持不变。
- 胶质瘤路径会加载 `diffuse_glioma_brats` skill，调用 Vision Agent 的 BraTS ground-truth 或 MedSAM2 分割路径。
- case memory 的 `image_memory` 现在保存 `image_outputs`，并保存完整 `visual_features`，包括 `measurements` 和 `completeness`。
- 诊断医生规则 fallback 对 `diffuse_glioma_brats_v0.1` 生成胶质瘤方向报告，说明病理和分子证据仍必需。
- 真实 CLI 跑通 BraTS2021 `BraTS2021_00030`，报告中明确 `enhancing_tumor` 因缺 T1ce 为 `missing`，不能解释为 0。

下一步：

- 补胶质瘤报告的 LLM prompt 专用约束，让 LLM 模式也稳定遵守 visual completeness，而不仅是规则 fallback 遵守。

风险/待确认：

- MedSAM2 主流程路径已接好，但真实 MedSAM2 模式仍依赖外部 `MEDSAM2_COMMAND_TEMPLATE`、repo 和权重配置。

### 2026-05-23 胶质瘤 LLM 视觉证据安全栅栏追加

本轮目标：让真实 API/LLM 模式也遵守 `visual_evidence.completeness`，避免把缺失影像证据解释成 0 或阴性。

修改文件：

- `agents/diagnosis_agent.py`
- `prompts/diagnosis_agent_prompt.md`
- `tests/test_diagnosis_llm_workflow.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_diagnosis_llm_workflow.py tests/test_mvp_flow.py tests/test_cli_entrypoint.py tests/test_service_entrypoint.py -v
python -m unittest discover -v
```

验证结果：

- `diagnosis_agent_prompt.md` 已明确要求 LLM 遵守 `completeness`：`missing` / `unassessed` 只能写缺失或不能评估，`null` 不能解释为 0。
- Prompt 已明确胶质瘤缺 T1ce 时不能判断 `enhancing_tumor` / 强化肿瘤 / 强化成分，不能写“增强肿瘤体积为 0”。
- `DiagnosisDoctorAgent` 已在 LLM JSON 字段校验后追加 visual completeness 校验。
- 如果 LLM 把 `missing` 或 `unassessed` 目标写成 0、阴性、未见、未发现等，会抛出校验错误并进入规则 fallback。
- 合法 LLM 报告仍可正常通过，不影响默认股骨头路径和胶质瘤规则 fallback。

下一步：

- 用真实 DMX API 跑一次胶质瘤 LLM 诊断 smoke，检查真实模型是否按 prompt 主动写出缺 T1ce 的不确定性。

风险/待确认：

- 当前安全栅栏是文本级防护，不替代医学事实校验；后续可把报告字段进一步结构化，减少纯文本规则匹配。

### 2026-05-23 胶质瘤真实 LLM Smoke 追加

本轮目标：用真实 DMX API 运行一次胶质瘤 LLM 诊断 smoke，并确认 visual completeness 安全栅栏在真实模型输出上有效。

修改文件：

- `scripts/glioma_llm_smoke_test.py`
- `tests/test_glioma_llm_smoke_test.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_glioma_llm_smoke_test.py -v
python -m scripts.glioma_llm_smoke_test
DMX_API_KEY=<临时环境变量> python -m scripts.glioma_llm_smoke_test --real
python -m unittest discover -v
```

验证结果：

- 新增 `python -m scripts.glioma_llm_smoke_test`，默认 dry-run，只检查 DMX/KY 路由、样本图像、mask 和输出目录，不联网。
- `--real` 模式会通过 `PromptRunner(OpenAICompatibleModelClient)` 调用真实模型，再走高医生主流程：Vision Agent -> Diagnosis Agent -> Memory。
- 单元测试覆盖 dry-run、缺少 API key 的 `not_ready`、以及 fake model real-path，不触发网络。
- 真实 DMX 调用已成功到达 `deepseek-v4-pro`，并写入 `output/fake/glioma_llm_smoke/glioma_llm_smoke_result.json`。
- 真实模型输出触发 safety gate：`llm_fallback_reason` 为 `missing visual evidence tumor_core was interpreted as negative/zero: Requires T1, T1ce, T2 modalities`。
- 系统已拒绝该 LLM 报告并 fallback 到规则胶质瘤报告；最终报告保留 `enhancing_tumor`、`tumor_core`、`mass_effect` 的 missing 不确定性，未把缺失证据写成 0。
- 当前 `python -m unittest discover -v`：104 个测试通过。

下一步：

- 进一步把 LLM 输出 contract 结构化：要求 LLM 回传 `used_visual_fields` / `missing_visual_fields_acknowledged`，减少纯文本 safety gate 的误判。

风险/待确认：

- 真实 LLM 已证明可能误解 missing 证据；当前 fallback 是安全的，但会降低 LLM 报告利用率，需要继续增强 prompt 和结构化输出约束。

### 2026-05-23 LLM 视觉字段结构化 Contract 追加

本轮目标：把胶质瘤 LLM 报告从纯文本 safety gate 进一步收紧为结构化视觉字段确认，降低误判和漏判。

修改文件：

- `agents/diagnosis_agent.py`
- `prompts/diagnosis_agent_prompt.md`
- `tests/test_diagnosis_llm_workflow.py`
- `tests/test_glioma_llm_smoke_test.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_diagnosis_llm_workflow.py tests/test_glioma_llm_smoke_test.py -v
python -m scripts.glioma_llm_smoke_test
python -m unittest discover -v
```

验证结果：

- 当 `visual_evidence.completeness` 存在时，LLM 报告现在必须返回 `used_visual_fields` 和 `missing_visual_fields_acknowledged` 两个 list。
- `missing_visual_fields_acknowledged` 必须覆盖所有 `missing` / `unassessed` 视觉字段；否则报告被拒绝并进入规则 fallback。
- 即使结构化字段齐全，如果正文仍把 missing 证据写成 0、阴性或未见，仍会被原 safety gate 拒绝。
- Prompt JSON schema 已声明这两个字段在存在 `completeness` 时必须返回。
- fake LLM smoke 已更新为合格结构化输出，确保正向路径仍可接受 LLM 报告。
- `python -m scripts.glioma_llm_smoke_test` dry-run 正常输出 DMX 路由和样本状态。
- 当前 `python -m unittest discover -v`：106 个测试通过。

下一步：

- 用真实 DMX 再跑一次结构化 contract 后的 LLM smoke，看模型是否能主动返回 `used_visual_fields` 和 `missing_visual_fields_acknowledged`；如果仍 fallback，再继续收紧 prompt 示例或拆成二阶段修正。

风险/待确认：

- 当前 contract 只在 `visual_evidence.completeness` 存在时强制启用，避免影响旧 X 光流程；后续如果所有视觉 Agent 都输出 completeness，可以把它升级为全局强制字段。

### 2026-05-23 真实 LLM 结构化 Contract 复测追加

本轮目标：重跑真实 DMX 胶质瘤 LLM smoke，确认结构化字段 contract 在真实模型上是否可通过，并修复 safety gate 对否定句的误判。

修改文件：

- `agents/diagnosis_agent.py`
- `scripts/glioma_llm_smoke_test.py`
- `tests/test_diagnosis_llm_workflow.py`
- `tests/test_glioma_llm_smoke_test.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_diagnosis_llm_workflow.py tests/test_glioma_llm_smoke_test.py -v
DMX_API_KEY=<临时环境变量> python -m scripts.glioma_llm_smoke_test --real
python -m unittest discover -v
```

验证结果：

- `scripts.glioma_llm_smoke_test` 现在会在 `output/fake/glioma_llm_smoke/glioma_llm_smoke_result.json` 中保存 `llm_raw_content`，仅用于 smoke 调试。
- `DiagnosisDoctorAgent` 现在会把 LLM 返回的单个字符串 list 字段归一化为单元素 list，例如 `"治疗建议": "..."` 会变成 `["..."]`。
- safety gate 已区分“声称 missing 字段为 0/阴性”和“不能视为 0/不能假定为阴性”，避免把正确的不确定性说明误判为违规。
- 真实 DMX 复测已通过：报告没有 `llm_fallback_reason`。
- 真实模型返回了 `used_visual_fields: ["whole_tumor", "edema"]`。
- 真实模型返回了 `missing_visual_fields_acknowledged: ["tumor_core", "enhancing_tumor", "mass_effect"]`。
- 真实报告写明缺少 T1/T1ce/T2 时无法评估肿瘤核心、增强肿瘤成分和占位效应，没有把 missing 字段解释为 0。
- 当前 `python -m unittest discover -v`：109 个测试通过。

下一步：

- 开始做多病例/批量胶质瘤 LLM smoke：把 manifest 中每个 case 的视觉结果、LLM 报告、fallback 状态、结构化字段覆盖情况汇总成 `summary.json` 和 `summary.md`。

风险/待确认：

- 目前真实 LLM smoke 只验证了单例 `BraTS2021_00030`；还不能代表多病例稳定性。

### 2026-05-23 胶质瘤批量 LLM Smoke 追加

本轮目标：把单例胶质瘤真实 LLM smoke 扩展为 manifest 批量入口，并输出可审计 summary。

修改文件：

- `scripts/glioma_llm_smoke_test.py`
- `agents/diagnosis_agent.py`
- `tests/test_glioma_llm_smoke_test.py`
- `tests/test_diagnosis_llm_workflow.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_glioma_llm_smoke_test.py tests/test_diagnosis_llm_workflow.py -v
DMX_API_KEY=<临时环境变量> python -m scripts.glioma_llm_smoke_test --all-cases --manifest data/external/brats_manifest.json --real
python -m unittest discover -v
```

验证结果：

- `scripts.glioma_llm_smoke_test` 新增 `--manifest` 和 `--all-cases`，可按 `data/external/brats_manifest.json` 批量运行胶质瘤 LLM smoke。
- 批量入口会为每例写入独立 `glioma_llm_smoke_result.json`，并汇总 `summary.json` 与 `summary.md`。
- summary 记录 `case_count`、`ok_count`、`fallback_count`、失败病例、fallback 病例、`used_visual_fields` 和 `missing_visual_fields_acknowledged`。
- dry-run 批量模式状态为 `dry_run`，不会把未联网检查计入失败病例。
- 真实 DMX 批量 smoke 当前 manifest 1 例：`case_count=1`、`ok_count=1`、`fallback_count=0`、`failed_case_ids=[]`。
- 真实批量结果已写入 `output/fake/glioma_llm_smoke/summary.json` 和 `output/fake/glioma_llm_smoke/summary.md`。
- 真实模型返回 `used_visual_fields: ["whole_tumor", "edema"]`。
- 真实模型返回 `missing_visual_fields_acknowledged: ["tumor_core", "enhancing_tumor", "mass_effect"]`。
- 本轮发现 safety gate 会把“不能排除低级别无强化胶质瘤”误判为缺失强化证据的阴性结论；已加回归测试并修正语境窗口，保留真正 “missing 证据为 0/阴性/未见” 的拦截。
- 当前 `python -m unittest discover -v`：112 个测试通过。

下一步：

- 扩展 `data/external/brats_manifest.json` 到更多 BraTS 病例，继续观察真实 LLM 的 fallback 率和字段确认稳定性。

风险/待确认：

- 当前批量真实验证仍只有 1 例；还不能说明多病例稳定性。
- `output/fake/glioma_llm_smoke/` 属于实验性输出，确认无误后再把可归档结果迁移到 `output/real/`。

### 2026-05-23 胶质瘤批量稳定性 Quality Gate 追加

本轮目标：避免把 1 例真实 smoke 误当成多病例稳定性验证，为后续扩展真实 BraTS 病例加上最小病例数门槛。

修改文件：

- `scripts/glioma_llm_smoke_test.py`
- `tests/test_glioma_llm_smoke_test.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_glioma_llm_smoke_test.py -v
python -m scripts.glioma_llm_smoke_test --all-cases --manifest data/external/brats_manifest.json --min-cases 2 --output-dir output/fake/glioma_llm_smoke_min_cases_gate
DMX_API_KEY=<临时环境变量> python -m scripts.glioma_llm_smoke_test --all-cases --manifest data/external/brats_manifest.json --real
python -m unittest discover -v
```

验证结果：

- 批量 smoke 新增 `--min-cases`，默认值为 `1`，不影响现有单例 smoke。
- 当 manifest 病例数少于 `--min-cases` 时，脚本写入 `status=insufficient_cases`，不运行病例，也不调用模型 API。
- 病例数门槛结果会写入 `quality_gate`：`min_cases`、`actual_cases`、`passed`、`reason`。
- 当前本地 `data/external/brats_manifest.json` 只有 1 例；执行 `--min-cases 2` 后输出 `output/fake/glioma_llm_smoke_min_cases_gate/summary.json` 和 `summary.md`，状态为 `insufficient_cases`。
- 重新执行默认真实 DMX 批量 smoke 后，主 summary 保持 `status=ok`、`case_count=1`、`ok_count=1`、`fallback_count=0`，且 `quality_gate.passed=true`。
- 当前 `python -m unittest discover -v`：113 个测试通过。

下一步：

- 获取第二个及以上真实 BraTS 病例，追加到 `data/external/brats_manifest.json`，然后用 `--min-cases 2` 跑真实批量 smoke。

风险/待确认：

- 本轮没有新增真实病例；只是防止稳定性验证被单例结果误导。

### 2026-05-23 第二例 BraTS 真实病例与两例 LLM 批量验证追加

本轮目标：补充第二个真实 BraTS 病例，并用 `--min-cases 2` 跑真实两例胶质瘤 LLM 批量 smoke。

修改文件：

- `data/external/brats_manifest.json`
- `docs/datasets/brats_glioma_plan.md`
- `goalnew.md`

新增数据：

- `data/external/brats2021_00392/BraTS2021_00392_flair.nii.gz`
- `data/external/brats2021_00392/BraTS2021_00392_seg.nii.gz`

验证命令：

```bash
python -m scripts.brats_vision_test_line --image data/external/brats2021_00392/BraTS2021_00392_flair.nii.gz --mask data/external/brats2021_00392/BraTS2021_00392_seg.nii.gz --output-dir output/fake/brats_vision_test_line/brats2021_00392_ground_truth
python -m scripts.brats_vision_test_line --validate-manifest --manifest data/external/brats_manifest.json
python -m scripts.glioma_llm_smoke_test --all-cases --manifest data/external/brats_manifest.json --min-cases 2 --output-dir output/fake/glioma_llm_smoke_min_cases_gate
python -m scripts.brats_vision_test_line --manifest data/external/brats_manifest.json --all-cases --output-dir output/fake/brats_vision_test_line
DMX_API_KEY=<临时环境变量> python -m scripts.glioma_llm_smoke_test --all-cases --manifest data/external/brats_manifest.json --min-cases 2 --real
python -m unittest discover -v
```

验证结果：

- 新增真实 BraTS2021 `BraTS2021_00392`，包含 FLAIR 和 segmentation mask。
- 单例视觉测试线已验证 `BraTS2021_00392` 可读、可生成 overlay 和结构化视觉证据。
- `BraTS2021_00392` ground-truth 特征：whole tumor `47.590 ml`，tumor core `38.665 ml`，enhancing tumor `31.896 ml`，`edema_present=true`。
- `data/external/brats_manifest.json` 当前 2 例全部有效：`case_count=2`、`valid_count=2`。
- 两例 BraTS 视觉批量 ground-truth 通过：`ok_count=2`，平均 Dice 均为 `1.0`。
- `--min-cases 2` dry-run quality gate 通过：`quality_gate.passed=true`。
- 真实 DMX 两例 LLM smoke 通过：`case_count=2`、`ok_count=2`、`fallback_count=0`、`failed_case_ids=[]`、`fallback_case_ids=[]`。
- 两例真实 LLM 均返回 `used_visual_fields: ["whole_tumor", "edema"]`。
- 两例真实 LLM 均返回 `missing_visual_fields_acknowledged: ["tumor_core", "enhancing_tumor", "mass_effect"]`。

下一步：

- 继续扩展到 3-5 个真实 BraTS 病例，观察真实 LLM fallback 率和字段确认稳定性；或者切到 MedSAM2 模式对两例做真实模型分割质量评估。

风险/待确认：

- 第二例来自公开 HuggingFace 镜像，后续正式实验仍应记录原始数据许可和来源版本。
- 当前 LLM smoke 仍用 ground-truth mask 路径；如果要评估真实视觉 Agent，需要切换到 `vision_mode=medsam2` 并配置外部 MedSAM2 runner。

### 2026-05-23 两例 MedSAM2 真实分割批量评估追加

本轮目标：在已有两例 BraTS manifest 上切到真实 MedSAM2 runner，评估模型 mask 与 ground-truth mask 的 Dice。

修改文件：

- `docs/datasets/medsam2_runner_config.md`
- `docs/datasets/brats_glioma_plan.md`
- `goalnew.md`

验证命令：

```bash
MEDSAM2_REPO_PATH=/private/tmp/medscope_medsam2_probe \
MEDSAM2_COMMAND_TEMPLATE='python /Users/houshaohua/Desktop/code/aidoctor/MedScope_Agent/scripts/medsam2_brats_wrapper.py --image {image_path} --output {output_mask_path} --prompt-json {prompt_json} --medsam2-repo /private/tmp/medscope_medsam2_probe --device cpu --checkpoint /private/tmp/medscope_medsam2_probe/checkpoints/MedSAM2_latest.pt --cfg /private/tmp/medscope_medsam2_probe/sam2/configs/sam2.1_hiera_t512.yaml' \
MEDSAM2_TIMEOUT_SECONDS=600 \
python -m scripts.brats_vision_test_line --check-medsam2 --manifest data/external/brats_manifest.json

MEDSAM2_REPO_PATH=/private/tmp/medscope_medsam2_probe \
MEDSAM2_COMMAND_TEMPLATE='python /Users/houshaohua/Desktop/code/aidoctor/MedScope_Agent/scripts/medsam2_brats_wrapper.py --image {image_path} --output {output_mask_path} --prompt-json {prompt_json} --medsam2-repo /private/tmp/medscope_medsam2_probe --device cpu --checkpoint /private/tmp/medscope_medsam2_probe/checkpoints/MedSAM2_latest.pt --cfg /private/tmp/medscope_medsam2_probe/sam2/configs/sam2.1_hiera_t512.yaml' \
MEDSAM2_TIMEOUT_SECONDS=600 \
python -m scripts.brats_vision_test_line --manifest data/external/brats_manifest.json --all-cases --mode medsam2 --prompt-from-reference-mask --output-dir output/fake/brats_vision_medsam2_two_cases

python -m unittest discover -v
```

验证结果：

- MedSAM2 readiness 通过：manifest 2 例有效，`MEDSAM2_COMMAND_TEMPLATE`、repo、checkpoint 和 cfg 均可用。
- 两例真实 MedSAM2 CPU 推理通过：`case_count=2`，`ok_count=2`，`failed_case_ids=[]`。
- 输出目录：`output/fake/brats_vision_medsam2_two_cases/`。
- 批量 summary：`output/fake/brats_vision_medsam2_two_cases/summary.json`。
- 平均 Dice：whole tumor `0.9429948832342406`，tumor core `0.699260558571914`，enhancing tumor `0.0`。
- `brats2021_00030` Dice：whole tumor `0.9394868934746236`，tumor core `0.4929657650363098`，enhancing tumor `0.0`。
- `brats2021_00392` Dice：whole tumor `0.9465028729938577`，tumor core `0.9055553521075183`，enhancing tumor `0.0`。
- 当前 macOS/CPU 环境仍会提示 SAM2 CUDA extension post-processing 跳过；该警告不阻止 mask 输出。

下一步：

- 人工查看两例 MedSAM2 overlay，重点确认 enhancing tumor Dice 为 `0.0` 是 prompt/模型限制还是 label 映射问题；之后再决定是否调整 prompt 生成策略或分 label 分割。

风险/待确认：

- 当前 MedSAM2 测试 prompt 来自 reference mask bbox，只用于评估 promptable segmentation 链路，不代表无标注自动分割。
- enhancing tumor 当前两例均为 `0.0`，不适合作为增强肿瘤自动分割结论，需要单独排查。

### 2026-05-23 互动前端 MVP 追加

本轮目标：先做一个无需 Node/npm 的可交互前端，直接调用现有 HTTP API，不绕过高医生 Agent。

修改文件：

- `api/http_server.py`
- `web/index.html`
- `web/app.css`
- `web/app.js`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests/test_http_entrypoint.py -v
python -m unittest discover -v
python -m api.http_server --host 127.0.0.1 --port 8000
```

验证结果：

- HTTP server 现在支持 `/` 返回互动前端页面。
- 静态资源通过白名单路径提供：`/static/app.css`、`/static/app.js`。
- 前端可填写患者描述、图像路径、mask 路径、疾病 skill、视觉模式和症状。
- 前端提交后调用 `/v1/medscope`，仍通过 `MedScopeService -> GaoDoctorAgent` 进入系统。
- 前端会展示结构化报告、case_id、intent、原始 JSON。
- 前端支持基于当前 case_id 发送 QA 追问。
- 当前 `python -m unittest discover -v`：116 个测试通过。

下一步：

- 给前端增加 overlay/产物预览路由，限制只能读取 `output/` 下结果文件，避免任意文件暴露。

风险/待确认：

- 当前前端输入的是本机路径，不是浏览器上传文件；这符合当前后端 contract，后续如要上传 NIfTI 需要另做受控文件落盘入口。

### 2026-05-24 前端上传与病灶图预览追加

本轮目标：把前端从开发参数表单改为更接近用户交互的上传界面，并展示 Vision Agent 输出的病灶图。

修改文件：

- `api/http_server.py`
- `api/service.py`
- `web/index.html`
- `web/app.css`
- `web/app.js`
- `tests/test_http_entrypoint.py`
- `tests/test_service_entrypoint.py`
- `goalnew.md`

验证命令：

```bash
node --check web/app.js
python -m unittest tests/test_service_entrypoint.py tests/test_http_entrypoint.py -v
python -m unittest discover -v
```

验证结果：

- 前端隐藏 `Mask 路径` 和 `视觉模式`，不再把视觉 Agent 内部工作暴露给普通用户。
- 前端新增拖拽/点击上传 MRI 文件，上传接口为 `POST /v1/upload?filename=...`。
- 上传文件只写入 `output/fake/uploads/`。
- 普通上传病例不在前端显式传 `vision_mode`，由服务端根据描述和图像信息自动判断；mask 由 Vision Agent/分割后端生成。
- 内置胶质瘤样例仍使用隐藏的 ground-truth mask，便于本地无 MedSAM2 环境时立即展示完整病灶图。
- HTTP server 新增受控产物预览：只允许读取 `/output/...` 路径，禁止路径逃逸。
- `MedScopeService` 会从 `case_memory_path` 读取 `image_outputs` 和 `visual_features`，随 API 响应返回给前端。
- 前端收到 `image_outputs.overlay_path` 后，会显示 Vision Agent 输出的病灶 overlay。
- 当前 `python -m unittest discover -v`：122 个测试通过。

下一步：

- 把“开发样例 ground-truth”和“真实上传 medsam2”在 UI 上做得更明确，避免用户误以为上传病例也自带标注。

风险/待确认：

- 当前浏览器上传的是本机文件并落入 `output/fake/uploads/`，仍属于实验性输入。
- 普通上传走 MedSAM2 时依赖外部 `MEDSAM2_COMMAND_TEMPLATE`；如果未配置会返回后端错误，需要后续在 UI 上做 readiness 提示。

### 2026-05-24 前端通用医疗影像与自动 Skill 选择追加

本轮目标：前端不再让患者选择 disease skill，而是由 Agent 根据描述和上传图像信息自动选择处理流程。

修改文件：

- `api/service.py`
- `web/index.html`
- `web/app.js`
- `tests/test_service_entrypoint.py`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

验证命令：

```bash
node --check web/app.js
python -m unittest tests/test_service_entrypoint.py tests/test_http_entrypoint.py -v
python -m unittest discover -v
```

验证结果：

- 前端上传文案从 MRI 改为通用“医疗影像”，支持 MRI / CT / X-ray / PNG / NIfTI 等输入。
- 前端移除 `疾病 Skill` 选择控件，患者不再需要理解或选择 skill。
- 前端移除患者可见的 `图像路径` 输入，主入口只保留患者描述、症状和拖拽上传。
- 前端普通上传不再主动指定 `vision_mode=medsam2`；除内置胶质瘤样例外，分割流程由服务端/Agent 自动推断。
- `MedScopeService` 在没有显式 `disease_key` 时会根据患者描述、图像路径和症状做保守自动选择。
- 若描述或文件路径包含 `胶质瘤`、`脑部`、`brain`、`glioma`、`brats`、`flair`、`.nii` 等线索，自动选择 `diffuse_glioma_brats`。
- 自动选择胶质瘤 skill 且没有 `mask_path` 时，默认走 `vision_mode=medsam2`，mask 仍由 Vision Agent/分割后端生成。
- 普通髋部/X-ray 场景仍保持默认流程，不强行选择胶质瘤 skill。
- 显式 API payload 仍可传 `disease_key` / `vision_mode`，用于开发和测试，不影响已有脚本。
- 当前 `python -m unittest discover -v`：124 个测试通过。

下一步：

- 给自动 skill 选择加一个可解释字段，例如 `routing_decision`，前端显示“Agent 选择了哪个流程、为什么选择”。

风险/待确认：

- 当前自动选择是保守规则，不是完整多模态分类器；后续可以接 LLM 或专门的 routing agent，但必须保留 fallback。

### 2026-05-24 API 路由决策可解释字段追加

本轮目标：让“Agent 根据描述和上传图像自动选择 skill / vision mode”从黑盒行为变成 API 可验证字段。

修改文件：

- `api/service.py`
- `tests/test_service_entrypoint.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_auto_selects_glioma_skill_from_message_and_image tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_keeps_default_skill_for_non_glioma_image tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_routing_decision_marks_explicit_payload -v
python -m unittest discover -v
```

验证结果：

- `MedScopeService` 现在会在响应中返回 `routing_decision`。
- `routing_decision` 包含 `selected_skill`、`selected_vision_mode`、`source`、`reason`、`confidence`、`matched_clues`。
- 自动胶质瘤路由会记录匹配线索，例如 `胶质瘤`、`flair`。
- 非胶质瘤/非已支持专病场景会返回 `source=default`，不强行选择专病 skill。
- 显式 API payload 传入 `disease_key` / `vision_mode` 时，会返回 `source=explicit`，用于开发和测试链路。
- 当前 `python -m unittest discover -v`：125 个测试通过。

下一步：

- 固定 Vision Agent -> Diagnosis Agent 的结构化输入契约，重点检查 `visual_evidence`、`completeness`、`image_outputs` 是否完整贯穿诊断报告。

### 2026-05-24 Vision -> Diagnosis 输入契约固定

本轮目标：让诊断 Agent 明确记录它消费到的视觉输入，避免病灶图、mask、`visual_evidence`、`completeness` 在诊断阶段丢失或被误解释。

修改文件：

- `contracts/medical_contracts.py`
- `agents/diagnosis_agent.py`
- `tests/test_contracts.py`
- `tests/test_mvp_flow.py`
- `tests/test_diagnosis_llm_workflow.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests.test_contracts.ContractBoundaryTest.test_diagnosis_visual_input_contract_preserves_outputs_and_completeness tests.test_mvp_flow.MedScopeMvpFlowTest.test_diagnosis_agent_combines_skill_visual_evidence_and_symptoms tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_accepts_structured_visual_field_acknowledgement_from_llm -v
python -m unittest discover -v
```

验证结果：

- 新增 `DiagnosisVisualInput` 契约，从 `VisualAnalysisResult` 规范化诊断 Agent 可消费的视觉输入。
- `DiagnosisVisualInput` 保留 `image_outputs`、`visual_evidence`、`measurements`、`completeness`、`segmentation_quality`。
- Diagnosis Agent 的规则报告和 LLM 报告都会附带 `visual_input_contract`。
- 缺失视觉字段仍通过 `completeness` 明确传递，诊断报告不能把 `null` 或 `missing` 当作 0 或阴性。
- 当前 `python -m unittest discover -v`：126 个测试通过。

下一步：

- 做一个端到端样例验证：前端/HTTP 输入 -> 自动路由 -> Vision Agent 病灶图 -> Diagnosis Agent 报告 -> API 响应完整回传。

### 2026-05-24 Skill 自动选择归属与契约固定

本轮目标：把“患者不选择 skill，由系统自动选择已有 disease skill”的部分固定成 Orchestrator/API 路由契约，并明确它不是 Skill Builder 动态生成 skill。

修改文件：

- `contracts/medical_contracts.py`
- `api/service.py`
- `tests/test_contracts.py`
- `tests/test_service_entrypoint.py`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests.test_contracts.ContractBoundaryTest.test_skill_routing_decision_contract_marks_orchestrator_scope tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_auto_selects_glioma_skill_from_message_and_image tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_keeps_default_skill_for_non_glioma_image tests.test_http_entrypoint.HttpEntrypointTest.test_post_medscope_returns_orchestrator_skill_routing_decision -v
python -m unittest discover -v
```

验证结果：

- 新增 `SkillRoutingDecision` 契约，作为自动 skill 选择的稳定返回结构。
- `routing_decision.agent_scope` 固定为 `orchestrator_api`，说明该决策属于 GaoDoctor/API 编排层。
- `routing_decision.skill_builder_action` 明确区分当前行为：
  - 选中已有专病 skill 时为 `load_existing_skill`。
  - 默认流程、不选专病 skill 时为 `none`。
- 当前没有让 Skill Builder Agent 根据病例动态生成新 skill；Skill Builder 仍只提供已有 skill 的加载/维护能力。
- HTTP `/v1/medscope` 响应会透出该路由契约；后续前端已改为直接展示路由、证据和审计摘要，不再依赖原始 JSON 面板。

下一步：

- 做端到端样例验证，把 `routing_decision`、`image_outputs`、`visual_input_contract` 三者同时从 API 响应中检查出来。

### 2026-05-24 HTTP 端到端样例验证

本轮目标：用真实 BraTS 样例从 HTTP 入口验证完整链路：自动路由 -> 已有 skill 加载 -> Vision Agent 病灶图 -> Diagnosis Agent `visual_input_contract` -> API 完整回传。

修改文件：

- `api/service.py`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_post_medscope_runs_auto_routed_brats_end_to_end_sample -v
python -m unittest tests/test_http_entrypoint.py -v
python -m unittest discover -v
```

验证结果：

- 新增 HTTP 端到端测试 `test_post_medscope_runs_auto_routed_brats_end_to_end_sample`。
- 测试从 `/v1/medscope` 入口提交真实 BraTS FLAIR 图像和系统隐藏 mask，不显式传 `disease_key` / `vision_mode`。
- `MedScopeService` 自动选择 `diffuse_glioma_brats`，并因存在系统 mask 选择 `ground_truth` 验证路径。
- API 响应包含 `routing_decision`，且 `source=auto`、`agent_scope=orchestrator_api`、`skill_builder_action=load_existing_skill`。
- API 顶层现在会回传 `visual_input_contract`，同时报告内也保留 `report.visual_input_contract`。
- API 响应包含 `image_outputs.overlay_path`，overlay 文件真实存在，且 `/output/...` 预览路由可返回 `image/png`。
- `visual_input_contract.completeness.enhancing_tumor.status=missing`，`enhancing_tumor_volume_ml=null`，报告未把缺失字段写成“增强肿瘤体积为 0”。
- 当前 `python -m unittest discover -v`：129 个测试通过。

下一步：

- 给真实上传走 MedSAM2 时增加 readiness 提示：如果 MedSAM2 环境未配置，API/前端应返回清楚的可操作错误，而不是让用户以为分析卡住。

### 2026-05-24 MedSAM2 Readiness 错误提示

本轮目标：真实上传自动走 MedSAM2 时，如果本机 MedSAM2 后端未配置，API 和前端要返回清楚、可操作的错误，而不是内部异常或“卡住”。

修改文件：

- `api/service.py`
- `api/http_server.py`
- `web/app.js`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_post_medscope_returns_503_when_auto_medsam2_is_not_configured -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests/test_http_entrypoint.py -v
python -m unittest discover -v
```

验证结果：

- 新增 `MedScopeReadinessError`，用于把后端 readiness 问题从普通内部异常中区分出来。
- 当自动路由选择 `diffuse_glioma_brats + medsam2`，但缺少 `MEDSAM2_COMMAND_TEMPLATE` 等配置时，HTTP 返回 `503`。
- readiness 响应包含：
  - `error_type=medsam2_not_ready`
  - `routing_decision`
  - `medsam2_configuration`
  - `action_items`
- 前端 `postMedScope` 会把 `error_type`、`error`、`action_items` 合并为可显示错误信息。
- 当前 `python -m unittest discover -v`：130 个测试通过。

下一步：

- 做真实上传场景的 UI 体验完善：把 readiness 错误从顶部状态短文本升级为报告区中的结构化提示，避免长错误挤在状态栏。

### 2026-05-24 双路径框架文档与 Hypothesis Safety Gate 开关

本轮目标：把 Guideline-Aware Path 与 Privileged Knowledge Discovery Path 写成正式架构边界，并把假设验证 skill 做成默认关闭、显式开启的安全模式。

修改文件：

- `docs/DUAL_PATH_AGENT_FRAMEWORK.md`
- `tools/evidence_summary_tool.py`
- `tools/skill_builder_tool.py`
- `contracts/medical_contracts.py`
- `agents/diagnosis_agent.py`
- `agents/gaodoctor_agent.py`
- `api/service.py`
- `tests/test_guideline_skill_builder.py`
- `tests/test_contracts.py`
- `tests/test_mvp_flow.py`
- `tests/test_service_entrypoint.py`
- `goalnew.md`

验证命令：

```bash
python -m unittest tests.test_guideline_skill_builder.GuidelineSkillBuilderTest.test_skill_builder_uses_evidence_summary_for_missing_guideline tests.test_contracts.ContractBoundaryTest.test_skill_descriptor_enforces_guideline_vs_hypothesis_boundary tests.test_mvp_flow.MedScopeMvpFlowTest.test_hypothesis_skill_is_blocked_unless_validation_mode_is_enabled tests.test_mvp_flow.MedScopeMvpFlowTest.test_hypothesis_validation_mode_generates_research_warning_not_diagnosis -v
python -m unittest tests/test_guideline_skill_builder.py tests/test_contracts.py tests/test_mvp_flow.py tests/test_service_entrypoint.py -v
python -m unittest discover -v
```

验证结果：

- 新增 `docs/DUAL_PATH_AGENT_FRAMEWORK.md`，明确区分已实现、正在实现和规划中能力，避免把 LUPI/多模态蒸馏表述为已完成。
- `data_mined_hypothesis` skill 现在包含：
  - `path_type=privileged_knowledge_discovery`
  - `required_modalities`
  - `visual_protocol`
  - `evidence_completeness_matrix`
  - `safety_gate`
  - `discovery_metadata`
- `safety_gate.mode_required=hypothesis_validation`，默认不允许 hypothesis skill 进入临床诊断报告。
- Diagnosis Agent 默认阻断 `data_mined_hypothesis`，错误提示要求开启 `hypothesis_validation_mode`。
- 显式开启 `hypothesis_validation_mode=True` 时，Diagnosis Agent 只输出“科研假设风险提示”、金标准检查建议和低证据不确定性说明。
- `hypothesis_validation_mode` 可在 `DiagnosisDoctorAgent(...)` 构造时开启，也可在 `generate_report(..., hypothesis_validation_mode=True)` 单次调用开启。
- `MedScopeService` 可透传 `hypothesis_validation_mode` 到 GaoDoctor/Diagnosis 链路，默认仍为关闭。
- 当前 `python -m unittest discover -v`：133 个测试通过。

下一步：

- 用 mock evidence summary 生成一个可持久化的 `fhn_stage1_hypothesis` 样例 skill，放在 `output/fake/` 验证，不直接加入正式 `skills/` 目录。

### 2026-05-24 Guideline Skill Builder 主线增强

本轮目标：先把正式指南 skill 生成主线补扎实，知识发现 / hypothesis skill 作为 guideline 完成后的扩展能力保留。

修改文件：

- `tools/guideline_search_tool.py`
- `tools/skill_builder_tool.py`
- `tests/test_guideline_skill_builder.py`
- `goalnew.md`

已完成：

- `GuidelineSearchTool` 的离线指南索引不再只返回来源列表，新增结构化 `guideline_payload`。
- `SkillBuilderTool.build_guideline_skill_from_search()` 会把指南摘要转换成可执行的 `guideline_aware` skill。
- 生成的 guideline skill 已包含：
  - `path_type=guideline_aware`
  - `clinical_features`
  - `required_image_views`
  - `visual_targets`
  - `staging_rules`
  - `vision_agent_tasks`
  - 可选 `visual_protocol`
- 成人弥漫性胶质瘤命中指南检索时，已能生成带 MRI 模态要求、分割目标和测量字段的 guideline skill。
- 股骨头坏死命中指南检索时，已能生成带 ARCO 分期规则和视觉任务的 guideline skill。

验证命令：

```bash
python -m unittest tests/test_guideline_skill_builder.py -v
python -m unittest discover -v
```

验证结果：

- 6 项测试通过。
- 当前 `python -m unittest discover -v`：134 个测试通过。

下一步：

- 继续把 guideline skill 生成能力接入更真实的指南来源解析，但仍保持“找不到正式指南才进入 hypothesis skill”的优先级边界。

### 2026-05-24 Guideline 文档解析链路

本轮目标：把 Skill Builder 主线从“离线索引直接提供结构化 `guideline_payload`”推进到“指南文档/章节 -> 解析工具 -> guideline skill”。

修改文件：

- `tools/guideline_extraction_tool.py`
- `tools/guideline_search_tool.py`
- `tools/skill_builder_tool.py`
- `tests/test_guideline_skill_builder.py`
- `goalnew.md`

已完成：

- 新增 `GuidelineExtractionTool`，负责从指南文档章节中抽取：
  - `clinical_features`
  - `required_image_views`
  - `visual_targets`
  - `staging_rules`
  - `vision_agent_tasks`
  - `visual_protocol`
- `GuidelineSearchTool` 当前返回 `guideline_documents`，不再在搜索结果中暴露预制 `guideline_payload`。
- `SkillBuilderTool.build_guideline_skill_from_search()` 现在优先调用 `GuidelineExtractionTool.extract(...)` 生成 guideline payload。
- 生成的 guideline skill 会记录 `guideline_extraction` 元数据，说明解析工具、疾病键、来源文档数和抽取字段。
- 保留旧 `guideline_payload` 兼容 fallback，但当前默认离线索引已切到文档/章节路径。

验证命令：

```bash
python -m unittest tests/test_guideline_skill_builder.py -v
python -m unittest discover -v
```

验证结果：

- 7 项 guideline skill builder 测试通过。
- 当前 `python -m unittest discover -v`：135 个测试通过。

下一步：

- 把 `guideline_documents` 的来源从内置离线索引进一步拆成可持久化的指南文本/条目文件，或接入真实指南检索下载后的文本解析入口。

### 2026-05-24 Guideline Source Catalog 文件化

本轮目标：把指南文档/章节从 Python 代码常量中移出，改为可维护的来源 catalog 文件，为后续接真实指南下载/解析产物做准备。

修改文件：

- `data/guidelines/guideline_sources.json`
- `tools/guideline_search_tool.py`
- `tools/skill_builder_tool.py`
- `tests/test_guideline_skill_builder.py`
- `goalnew.md`

已完成：

- 新增 `data/guidelines/guideline_sources.json`，保存股骨头坏死和成人弥漫性胶质瘤的指南来源、文档条目和章节文本。
- `GuidelineSearchTool` 默认读取 `data/guidelines/guideline_sources.json`，同时支持 `source_catalog_path=...` 指向自定义来源文件。
- `GuidelineSearchTool` 的搜索结果会返回 `source_catalog_path`，方便后续追溯指南来源。
- `SkillBuilderTool` 生成 guideline skill 时写入 `guideline_source.source_catalog_path`，让 skill 能追踪到来源 catalog。
- 保留 `offline_index` 注入能力，便于测试或后续外部检索结果直接注入。

验证命令：

```bash
python -m unittest tests/test_guideline_skill_builder.py -v
python -m unittest discover -v
```

验证结果：

- 9 项 guideline skill builder 测试通过。
- 当前 `python -m unittest discover -v`：137 个测试通过。

下一步：

- 增加“真实指南文本导入 catalog”的脚本或工具，把下载/整理后的指南文本转换成 `guideline_sources.json` 的文档章节格式。

### 2026-05-24 Raw Guideline Text 导入工具

本轮目标：让下载、OCR 或人工整理后的指南文本能进入统一 source catalog，而不是手工编辑 `guideline_sources.json`。

修改文件：

- `tools/guideline_source_import_tool.py`
- `scripts/import_guideline_source.py`
- `tests/test_guideline_skill_builder.py`
- `goalnew.md`

已完成：

- 新增 `GuidelineSourceImportTool`：
  - 支持 `import_text(raw_text)` 将 raw 指南文本转换成 catalog entry。
  - 支持 `import_file(raw_path, catalog_path)` 写入指定 catalog 文件。
  - raw 文本格式为顶部 metadata + `## section_name` 章节块。
  - 必填 metadata：`disease_key`、`disease_name`、`source_type`、`evidence_level`、`title`、`publisher`、`source_id`。
- 同一 `disease_key` 多次导入时会合并 `sources` 和 `guideline_documents`，不会覆盖已有文档；相同 `source_id` 会替换对应文档。
- 新增 CLI 入口 `scripts/import_guideline_source.py`，可用 `--raw-path` 和 `--catalog-path` 导入真实指南文本。
- 已测试导入后的 catalog 可被 `GuidelineSearchTool(source_catalog_path=...)` 读取，后续继续进入 extraction/skill builder 链路。

验证命令：

```bash
python -m unittest tests/test_guideline_skill_builder.py -v
python -m unittest discover -v
```

验证结果：

- 12 项 guideline skill builder 测试通过。
- 当前 `python -m unittest discover -v`：140 个测试通过。

下一步：

- 补一个端到端验证：raw guideline txt -> import script -> source catalog -> SkillBuilder -> guideline skill，并把样例输出放在 `output/fake/`。

### 2026-05-24 Raw-to-Skill 端到端样例

本轮目标：验证完整 guideline 主线样例：raw guideline txt -> source catalog -> GuidelineSearchTool -> GuidelineExtractionTool -> SkillBuilderTool -> guideline skill -> Vision/Diagnosis Agent 消费。

修改文件：

- `scripts/guideline_import_to_skill_demo.py`
- `tests/test_guideline_import_pipeline.py`
- `goalnew.md`

已完成：

- 新增 `scripts/guideline_import_to_skill_demo.py`：
  - 默认创建 `output/fake/guideline_import_demo/raw_guideline.txt`。
  - 导入生成 `output/fake/guideline_import_demo/guideline_sources.json`。
  - 通过 `SkillBuilderTool` 生成 `output/fake/guideline_import_demo/demo_glioma_guideline_skill.json`。
- 样例 skill 已包含：
  - `skill_type=guideline_based`
  - `path_type=guideline_aware`
  - `guideline_source.source_catalog_path`
  - `guideline_extraction`
  - `clinical_features`
  - `required_image_views`
  - `vision_agent_tasks`
  - `visual_protocol`
- 新增 `tests/test_guideline_import_pipeline.py`：
  - 验证 raw 文本可导入 catalog 并生成 guideline skill。
  - 验证导入生成的 skill 可被 `VisionAgent` 和 `DiagnosisDoctorAgent` 消费。

样例产物：

- `output/fake/guideline_import_demo/raw_guideline.txt`
- `output/fake/guideline_import_demo/guideline_sources.json`
- `output/fake/guideline_import_demo/demo_glioma_guideline_skill.json`

验证命令：

```bash
python -m scripts.guideline_import_to_skill_demo
python -m unittest tests/test_guideline_import_pipeline.py tests/test_guideline_skill_builder.py -v
python -m unittest discover -v
```

验证结果：

- demo 脚本已生成 `guideline_based` skill 样例。
- guideline import pipeline + skill builder 共 14 项测试通过。
- 当前 `python -m unittest discover -v`：142 个测试通过。

下一步：

- 如果继续增强“真实指南来源解析”，应接入真实网页/PDF/OCR 文本获取层；当前主线已经具备 raw 文本导入、结构化抽取、skill 生成和 Agent 消费闭环。

### 2026-05-24 Guideline Citation 追溯字段

本轮目标：回答“指南来源在哪里、有依据吗”的问题，把 section 级 citation 从 source catalog 传到最终 guideline skill。

修改文件：

- `data/guidelines/guideline_sources.json`
- `tools/guideline_source_import_tool.py`
- `tools/guideline_extraction_tool.py`
- `scripts/guideline_import_to_skill_demo.py`
- `tests/test_guideline_skill_builder.py`
- `goalnew.md`

已完成：

- `GuidelineSourceImportTool` 支持 raw metadata 中的可选字段：
  - `url`
  - `source_kind`
  - `evidence_note`
- raw 文本导入 catalog 时，每个 section 会自动携带 `citations`。
- `GuidelineExtractionTool` 会汇总 section citations 到 `guideline_extraction.citations`。
- `data/guidelines/guideline_sources.json` 已为默认股骨头坏死和成人弥漫性胶质瘤条目补充 URL、来源类型和 evidence note。
- `scripts/guideline_import_to_skill_demo.py` 的 demo raw 文本已带 citation metadata，并支持 `--overwrite-raw` 重新生成 demo raw 文件。
- `output/fake/guideline_import_demo/` 的 raw、catalog、skill 三层都已生成 citation 字段。

验证命令：

```bash
python -m scripts.guideline_import_to_skill_demo --overwrite-raw
python -m unittest tests/test_guideline_import_pipeline.py tests/test_guideline_skill_builder.py -v
python -m unittest discover -v
```

验证结果：

- `output/fake/guideline_import_demo/demo_glioma_guideline_skill.json` 已包含 `guideline_extraction.citations`。
- guideline import pipeline + skill builder 共 14 项测试通过。
- 当前 `python -m unittest discover -v`：142 个测试通过。

下一步：

- 可以继续把 citations 显示到诊断报告或前端证据面板；目前 skill 层已经具备来源追溯字段。

### 2026-05-24 Guideline Evidence 报告/API/前端闭环

本轮目标：把 guideline citation 从 skill 层继续透传到诊断报告、HTTP API 和互动前端，形成“指南来源可追溯”的端到端闭环。

修改文件：

- `contracts/medical_contracts.py`
- `tools/skill_builder_tool.py`
- `agents/diagnosis_agent.py`
- `api/service.py`
- `web/app.js`
- `web/app.css`
- `skills/diffuse_glioma_brats.yaml`
- `skills/femoral_head_necrosis.yaml`
- `tests/test_contracts.py`
- `tests/test_guideline_import_pipeline.py`
- `tests/test_service_entrypoint.py`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

已完成：

- `SkillDescriptor` 保留 `source_documents`、`guideline_source`、`guideline_extraction` 和 `quality_control`。
- `SkillBuilderTool` 对新构建的 `guideline_based` skill 增加 citation 质量控制；如果 `guideline_extraction` 没有 citations，会拒绝进入正式 guideline skill。
- `DiagnosisDoctorAgent` 在正式指南路径中输出：
  - `guideline_evidence`
  - 中文报告字段 `指南依据`
  - 去重后的 citations、source documents、catalog 路径和质量控制信息。
- `MedScopeService` 将报告里的 `guideline_evidence` 提升到 API 顶层，方便前端直接消费。
- 互动前端新增“指南依据”展示区，显示来源标题、发布方/来源类型、section、evidence note 和来源链接。
- 默认两个正式 skill 已同步来源字段：
  - 成人弥漫性胶质瘤：EANO / ESTRO-EANO 来源。
  - 股骨头坏死：ARCO review / ONFH guideline 来源。

验证命令：

```bash
python -m unittest tests.test_contracts.ContractBoundaryTest.test_skill_descriptor_preserves_guideline_citations tests.test_guideline_import_pipeline.GuidelineImportPipelineTest.test_imported_guideline_report_exposes_guideline_evidence tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_exposes_guideline_evidence_from_report tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
python -m unittest tests.test_guideline_import_pipeline tests.test_guideline_skill_builder tests.test_contracts tests.test_service_entrypoint tests.test_http_entrypoint -v
node --check web/app.js
python -m unittest discover -v
```

验证结果：

- citation 透传新增测试通过。
- guideline/report/API/frontend 相关 51 个测试通过。
- `node --check web/app.js` 通过。
- 当前 `python -m unittest discover -v`：145 个测试通过。

下一步：

- 这一部分已经闭环。后续可以继续做“真实网页/PDF 指南采集器”，但那属于 guideline skill builder 的外部来源获取扩展，不需要重构当前 Agent 主链路。

### 2026-05-24 真实网页/PDF 指南采集器

本轮目标：给 Skill Builder 增加外部来源获取层，可以从真实网页或 PDF 采集指南文本，生成现有 raw guideline 格式，并可选导入 source catalog。

修改文件：

- `tools/guideline_source_collector_tool.py`
- `scripts/collect_guideline_source.py`
- `tests/test_guideline_source_collector.py`
- `goalnew.md`

已完成：

- 新增 `GuidelineSourceCollectorTool`：
  - 支持 `http/https` URL、`file://` URL 和本地文件路径。
  - 支持 HTML/普通文本抽取。
  - HTML 中的 `h1-h6` 会转换为 raw guideline 的 `## section`。
  - 自动去除 `script/style/noscript`。
  - 支持 PDF 采集；默认尝试 `pypdf` 或 `PyPDF2`，缺依赖时给出明确错误，也支持注入 `pdf_text_extractor`。
- 新增 CLI：
  - `python -m scripts.collect_guideline_source`
  - 默认输出到 `output/fake/guideline_collector/<source_id>_raw_guideline.txt`。
  - 可用 `--import-to-catalog` 直接把采集结果导入 catalog。
  - CLI 只打印摘要，不打印整篇指南正文。
- 新增测试：
  - HTML 采集后生成带 citation metadata 的 raw guideline。
  - 采集后的 HTML raw guideline 可进入 `GuidelineSearchTool -> SkillBuilderTool` 链路。
  - PDF 采集可通过注入 extractor 完成测试。
- 真实网页 smoke test：
  - 来源：`https://pmc.ncbi.nlm.nih.gov/articles/PMC7152793/`
  - 输出：
    - `output/fake/guideline_collector/onfh_guideline_real_raw.txt`
    - `output/fake/guideline_collector/guideline_sources.json`
  - 采集结果：`content_type=text/html`，`char_count=83279`，`section_count=45`。

验证命令：

```bash
python -m unittest tests.test_guideline_source_collector tests.test_guideline_import_pipeline tests.test_guideline_skill_builder -v
python -m scripts.collect_guideline_source --source https://pmc.ncbi.nlm.nih.gov/articles/PMC7152793/ --raw-output-path output/fake/guideline_collector/onfh_guideline_real_raw.txt --catalog-path output/fake/guideline_collector/guideline_sources.json --import-to-catalog --disease-key onfh_real_source_demo --disease-name 股骨头坏死真实来源样例 --source-type medical_guideline --evidence-level high --title 'Guideline for Diagnostic and Treatment of Osteonecrosis of the Femoral Head' --publisher 'PMC open access guideline' --source-id onfh_pmc7152793 --source-kind clinical_guideline --evidence-note 'Real public web guideline collection smoke test'
python -m unittest discover -v
```

验证结果：

- guideline source collector/import/builder 相关 18 个测试通过。
- 真实网页采集 smoke test 通过，产物已放入 `output/fake/guideline_collector/`。
- 当前 `python -m unittest discover -v`：148 个测试通过。

下一步：

- 采集器已经能“拿到真实来源并入库”。下一层更有价值的是“真实网页正文清洗与 section 语义映射”：把真实网页里的 `Abstract / Diagnosis / Imaging / Treatment` 自动映射为 `clinical_features / required_image_views / visual_protocol / report_requirements`，这样才能从任意真实指南更稳定地产生可执行 skill。

### 2026-05-24 真实指南 Section 语义映射

本轮目标：让真实网页/PDF 采集后的原始章节能被转换为现有 Skill Builder 可消费的 canonical sections，避免网页作者、引用、资源栏等噪声污染正式 skill。

修改文件：

- `tools/guideline_section_mapper_tool.py`
- `tools/guideline_source_collector_tool.py`
- `tools/guideline_extraction_tool.py`
- `scripts/collect_guideline_source.py`
- `tests/test_guideline_source_collector.py`
- `tests/test_guideline_skill_builder.py`
- `goalnew.md`

已完成：

- 新增 `GuidelineSectionMapperTool`：
  - 将真实章节标题和正文映射为：
    - `clinical_features`
    - `required_image_views`
    - `staging_rules`
    - `report_requirements`
  - 跳过作者、引用、资源、动作栏、摘要、概述、图注等噪声章节。
  - 对长段落做截断，避免 raw/skill 被网页全文污染。
  - 根据正文出现顺序保留影像视图顺序。
- `GuidelineSourceCollectorTool.collect_to_raw_file(..., semantic_map=True)` 支持采集后立即语义映射。
- CLI 新增 `--semantic-map` 参数。
- `GuidelineExtractionTool` 增强：
  - 支持 `report_requirements` section。
  - 修复重复 keyed list 行覆盖问题；例如多个 `common_symptoms:` 会合并而不是覆盖。
- 新增/扩展测试：
  - 真实世界 heading 映射到 canonical sections。
  - 作者/引用噪声不进入 canonical skill 字段。
  - semantic mapped HTML 可进入 `GuidelineSearchTool -> SkillBuilderTool`。
  - repeated keyed list extraction 合并测试。
- 真实网页 semantic smoke test：
  - 来源：`https://pmc.ncbi.nlm.nih.gov/articles/PMC7152793/`
  - 输出：
    - `output/fake/guideline_collector/onfh_guideline_semantic_raw.txt`
    - `output/fake/guideline_collector/semantic_guideline_sources.json`
    - `output/fake/guideline_collector/onfh_semantic_skill.json`
  - 采集后 canonical section 数：4。
  - 生成 skill 已抽取：
    - `required_image_views`: CT, MRI, X-ray, Plain radiography, MRI T2, SPECT
    - `clinical_features.common_symptoms`: hip pain, knee pain, limited hip internal rotation, buttock pain, groin pain
    - `staging_rules`: Staging
    - `guideline_extraction.citations`: 1 条真实来源 citation

验证命令：

```bash
python -m unittest tests.test_guideline_source_collector tests.test_guideline_import_pipeline tests.test_guideline_skill_builder -v
python -m scripts.collect_guideline_source --source https://pmc.ncbi.nlm.nih.gov/articles/PMC7152793/ --raw-output-path output/fake/guideline_collector/onfh_guideline_semantic_raw.txt --catalog-path output/fake/guideline_collector/semantic_guideline_sources.json --import-to-catalog --semantic-map --disease-key onfh_semantic_source_demo --disease-name 股骨头坏死语义映射样例 --source-type medical_guideline --evidence-level high --title 'Guideline for Diagnostic and Treatment of Osteonecrosis of the Femoral Head' --publisher 'PMC open access guideline' --source-id onfh_pmc7152793_semantic --source-kind clinical_guideline --evidence-note 'Real public web guideline semantic mapping smoke test'
python -m scripts.guideline_import_to_skill_demo --raw-path output/fake/guideline_collector/onfh_guideline_semantic_raw.txt --catalog-path output/fake/guideline_collector/semantic_guideline_sources.json --skill-output-path output/fake/guideline_collector/onfh_semantic_skill.json --disease-key onfh_semantic_source_demo --disease-name 股骨头坏死语义映射样例
python -m unittest discover -v
```

验证结果：

- guideline collector/import/builder 相关 22 个测试通过。
- 真实网页 semantic smoke test 通过。
- 当前 `python -m unittest discover -v`：152 个测试通过。

下一步：

- 现在真实指南可以采集、清洗、映射、入库并生成 guideline skill。后续最值得做的是“多来源 guideline skill 合并与冲突标注”：同一疾病多篇指南进入 catalog 后，需要标记来源优先级、年份、适用地区，以及同一字段的冲突说明。

### 2026-05-24 多来源 Guideline 合并与冲突标注

本轮目标：同一疾病存在多篇指南时，Skill Builder 不再静默合并所有字段，而是保留来源优先级、年份、地区，并对字段冲突打标，交给诊断报告和前端提示人工复核。

修改文件：

- `tools/guideline_source_import_tool.py`
- `tools/skill_builder_tool.py`
- `contracts/medical_contracts.py`
- `agents/diagnosis_agent.py`
- `web/app.js`
- `web/app.css`
- `tests/test_guideline_skill_builder.py`
- `tests/test_guideline_import_pipeline.py`
- `tests/test_contracts.py`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

已完成：

- raw guideline metadata 新增可选来源治理字段：
  - `publication_year`
  - `region`
  - `source_priority`
- `GuidelineSourceImportTool` 会把这些字段写入：
  - `sources`
  - section-level `citations`
- `SkillBuilderTool` 新增：
  - `source_priority`：按 `source_priority`、`publication_year` 排序后的来源摘要。
  - `guideline_conflicts`：当前检测 `required_image_views` 多来源不一致。
  - `quality_control.conflict_status`
  - `quality_control.conflict_count`
- 冲突处理策略：
  - 仍保留合并后的 union 字段给 Agent 使用。
  - 同时标记 `resolution=merged_union_review_required`，明确需要人工复核。
  - 不让系统擅自裁决哪篇指南“正确”。
- `SkillDescriptor` 透传：
  - `source_priority`
  - `guideline_conflicts`
- `DiagnosisDoctorAgent` 的 `guideline_evidence` 新增：
  - `source_priority`
  - `conflicts`
- 前端“指南依据”面板新增：
  - 来源优先级展示。
  - 指南冲突需复核提示。

验证命令：

```bash
python -m unittest tests.test_guideline_skill_builder.GuidelineSkillBuilderTest.test_guideline_source_import_converts_raw_guideline_text_to_catalog_entry tests.test_guideline_skill_builder.GuidelineSkillBuilderTest.test_skill_builder_marks_multi_source_conflicts_and_source_priority tests.test_guideline_skill_builder.GuidelineSkillBuilderTest.test_guideline_search_result_builds_actionable_guideline_skill -v
python -m unittest tests.test_guideline_import_pipeline.GuidelineImportPipelineTest.test_diagnosis_report_exposes_guideline_conflicts_and_source_priority tests.test_contracts.ContractBoundaryTest.test_skill_descriptor_preserves_guideline_citations -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_guideline_skill_builder tests.test_guideline_import_pipeline tests.test_contracts tests.test_http_entrypoint tests.test_service_entrypoint -v
python -m unittest discover -v
```

验证结果：

- guideline/report/API/frontend 相关 54 个测试通过。
- `node --check web/app.js` 通过。
- 当前 `python -m unittest discover -v`：154 个测试通过。

下一步：

- 目前冲突检测先覆盖 `required_image_views`。下一步可以继续扩展冲突检测字段到 `clinical_features`、`visual_protocol.required_modalities`、`staging_rules`，并增加冲突严重度分级。

### 2026-05-24 Guideline Skill Builder 封板收尾

本轮目标：完成“真实指南 -> guideline skill”链路最后三个收尾：扩展冲突检测字段、增加冲突严重度分级、补完整 quality gate。

修改文件：

- `tools/skill_builder_tool.py`
- `web/app.js`
- `tests/test_guideline_skill_builder.py`
- `goalnew.md`

已完成：

- 冲突检测字段从 `required_image_views` 扩展到：
  - `clinical_features.common_symptoms`
  - `clinical_features.risk_factors`
  - `visual_protocol.required_modalities.<target>`
  - `staging_rules.<rule_name>`
- 冲突严重度分级：
  - `low`：临床症状/风险因素差异。
  - `medium`：影像检查或视觉协议 required modalities 差异，会影响证据充分性。
  - `high`：分期/规则差异，必须人工复核。
- `quality_control` 补全 quality gate：
  - `source_priority_status`
  - `conflict_severity_counts`
  - `highest_conflict_severity`
  - `missing_core_sections`
  - `core_section_status`
  - `formal_skill_status`
  - `can_enter_formal_guideline_skill`
- formal gate 规则：
  - citation URL 缺失 -> `needs_review`
  - 有冲突 -> `needs_review`
  - 缺少核心 section -> `needs_review`
  - 全部满足才是 `formal_ready`
- 前端冲突展示增加 severity，例如 `[high] staging_rules.ARCO_I`。

验证命令：

```bash
python -m unittest tests.test_guideline_skill_builder.GuidelineSkillBuilderTest.test_skill_builder_grades_conflicts_across_core_guideline_fields tests.test_guideline_skill_builder.GuidelineSkillBuilderTest.test_skill_builder_quality_gate_marks_missing_core_sections tests.test_guideline_skill_builder.GuidelineSkillBuilderTest.test_skill_builder_marks_multi_source_conflicts_and_source_priority -v
python -m unittest tests.test_guideline_skill_builder tests.test_guideline_import_pipeline tests.test_contracts tests.test_http_entrypoint tests.test_service_entrypoint -v
node --check web/app.js
python -m unittest discover -v
```

验证结果：

- guideline/report/API/frontend 相关 56 个测试通过。
- `node --check web/app.js` 通过。
- 当前 `python -m unittest discover -v`：156 个测试通过。

阶段结论：

- “真实 URL/PDF -> raw guideline -> semantic sections -> catalog -> guideline skill -> source priority -> conflict annotation -> quality gate -> report/frontend 可见”已经闭环。
- 这部分可以阶段性封板。后续除非要做 LLM 精抽或指南编辑器，否则不需要继续扩大这个模块。

### 2026-05-24 Memory Manager v1

本轮目标：把 memory 从“能存 JSON”升级成“四类可追溯病例记忆链”，不做数据库或大重构。

修改文件：

- `memory/memory_manager.py`
- `agents/gaodoctor_agent.py`
- `tests/test_memory_manager.py`
- `tests/test_mvp_flow.py`
- `goalnew.md`

已完成：

- 新保存的病例统一写入 `schema_version: memory_v1`。
- 新保存的病例统一包含：
  - `memory_types`
  - `created_at`
  - `updated_at`
  - `patient_memory`
  - `image_memory`
  - `skill_memory`
  - `reasoning_memory`
- 四类 memory 标准化：
  - `patient_memory`：患者消息、患者信息、症状、意图、`qa_history`。
  - `image_memory`：图像路径、模态、部位、输出图、视觉证据、测量值、证据充分性、分割质量。
  - `skill_memory`：选中的 skill、视觉模式、路由决策、指南证据、来源优先级、冲突、quality gate。
  - `reasoning_memory`：完整报告、诊断倾向、视觉输入契约、已用字段、已承认缺失字段、不确定性、随访和治疗建议。
- 旧 `data/cases/*.json` 风格的 case 读取时自动 normalize 为 v1 视图；单纯读取不会重写旧文件。
- 保留 `qa_memory` 作为兼容别名，但标准入口变为 `patient_memory.qa_history`。
- 新增 `get_evidence_bundle(case_id)`，供 QA、前端证据展示和论文 trace 使用。
- 新增最小检索能力：
  - `get_case_by_id(case_id)`
  - `find_cases_by_patient(patient_id)`
  - `find_cases_by_disease(disease_name_or_skill_id)`
  - `get_latest_case_for_patient(patient_id)`
  - `list_recent_cases(limit=20)`
- 新增 `build_audit_summary(case_id)`，输出到 `output/fake/memory_audit/<case_id>_audit.json`。
- GaoDoctor 写入链路已改为显式写四类 memory，不再只依赖 MemoryManager 兜底：
  - GaoDoctor 写 `patient_memory` 和 `skill_memory.routing_decision`。
  - Vision Agent 结果进入 `image_memory`。
  - Skill Builder / Diagnosis skill 证据进入 `skill_memory`。
  - Diagnosis Doctor 报告进入 `reasoning_memory`。
- Follow-up QA 已改为通过 `get_evidence_bundle()` 取证据，并追加标准化 `qa_history`。

验证命令：

```bash
python -m unittest tests.test_memory_manager -v
python -m unittest tests.test_memory_manager tests.test_mvp_flow -v
python -m unittest tests.test_service_entrypoint tests.test_http_entrypoint -v
python -m unittest tests.test_guideline_import_pipeline tests.test_guideline_skill_builder tests.test_contracts -v
```

当前验证结果：

- MemoryManager 单元测试 8 个通过。
- Memory + MVP flow 测试 16 个通过。
- Service/HTTP 测试 25 个通过。
- Guideline/Contract 测试 31 个通过。

封板标准对应状态：

- `case -> 四类 memory -> evidence bundle -> retrieval -> QA history -> audit summary` 已完成并有测试覆盖。

### 2026-05-24 标准端到端展示样例

本轮目标：做一条可演示的标准流程，把“上传图片 -> 自动选 skill -> 分割结果 -> 诊断报告 -> evidence bundle -> memory audit”串成一个稳定入口。

修改文件：

- `api/service.py`
- `scripts/end_to_end_demo.py`
- `tests/test_service_entrypoint.py`
- `tests/test_end_to_end_demo.py`
- `goalnew.md`

已完成：

- `MedScopeService` 自动路由增强：
  - 胶质瘤/脑部/FLAIR/NIfTI 线索 -> `diffuse_glioma_brats`。
  - 髋部/X-ray/股骨头/坏死线索 -> `femoral_head_necrosis`。
  - 无明确线索仍保持 default，不强行选病种。
- 新增标准 demo runner：
  - 命令：`python -m scripts.end_to_end_demo`
  - 默认输入：`data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz`
  - 默认内部参考 mask：`data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz`
  - 默认输出目录：`output/fake/end_to_end_demo`
- Demo runner 会生成：
  - 上传副本：`output/fake/end_to_end_demo/uploads/`
  - case memory：`output/fake/end_to_end_demo/memory/cases/`
  - evidence bundle：`output/fake/end_to_end_demo/artifacts/<case_id>_evidence_bundle.json`
  - local audit：`output/fake/end_to_end_demo/artifacts/<case_id>_audit.json`
  - MemoryManager audit：`output/fake/memory_audit/<case_id>_audit.json`
  - summary：`output/fake/end_to_end_demo/end_to_end_demo_summary.json`
  - lesion overlay：`output/fake/gaodoctor_brats/<case_id>_overlay.png`
- 已实际跑出一条演示病例：
  - `case_id`: `case_20260524_171512_942392`
  - 自动路由：`diffuse_glioma_brats`
  - 视觉模式：`ground_truth`
  - overlay：`output/fake/gaodoctor_brats/case_20260524_171512_942392_overlay.png`
  - summary：`output/fake/end_to_end_demo/end_to_end_demo_summary.json`

验证命令：

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_auto_selects_femoral_head_skill_from_hip_xray_clues tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_keeps_default_skill_for_non_glioma_image tests.test_end_to_end_demo -v
python -m scripts.end_to_end_demo
python -m unittest tests.test_end_to_end_demo tests.test_service_entrypoint tests.test_mvp_flow -v
```

当前验证结果：

- demo runner 契约测试通过。
- service 自动路由相关测试通过。
- end-to-end demo / service / MVP flow 共 20 个测试通过。

### 2026-05-24 演示级前端闭环

本轮目标：把后端端到端 demo 变成前端可视化，不再让用户主要阅读原始 JSON。

修改文件：

- `api/service.py`
- `web/index.html`
- `web/app.js`
- `web/app.css`
- `tests/test_service_entrypoint.py`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

已完成：

- `MedScopeService` 在已有 `case_memory_path` 的情况下，薄层附加：
  - `evidence_bundle`
  - `memory_audit`
  - `memory_audit_path`
- 前端布局改为演示级闭环：
  - 左侧：上传图片 / 患者描述 / 症状。
  - 中间：图像输出、原始图像路径、modality、body part、segmentation quality、overlay 病灶图。
  - 右侧：诊断报告、影像依据、不确定性、建议检查、治疗建议、指南依据。
  - 底部：Evidence Bundle 摘要和 Memory Trace / Audit 摘要。
- 删除原始 JSON 调试面板，避免右侧大 JSON 干扰演示。
- “胶质瘤样例”改为“一键标准样例”：
  - 自动填入 BraTS FLAIR 样例描述。
  - 自动使用内置 FLAIR NIfTI 路径。
  - 自动带上参考 mask，稳定跑 ground-truth segmentation demo。
  - 点击后直接运行完整流程。
- Evidence Bundle 前端展示：
  - 患者上下文。
  - 视觉测量。
  - completeness。
  - missing/unassessed 字段。
  - quality warnings。
  - skill 摘要。
- Memory Audit 前端展示：
  - 四类 memory 完整性。
  - Agent trace。
  - missing/unassessed。
  - guideline conflicts。
  - audit 输出路径。

实际服务验证：

- 本地前端服务启动在：`http://127.0.0.1:8010`
- `GET /health` 返回：`{"status": "ok"}`
- `GET /` 已返回包含：
  - `visualPanel`
  - `evidencePanel`
  - `auditPanel`
  - `一键标准样例`
- `POST /v1/medscope` 标准 BraTS payload 已返回：
  - `image_outputs`
  - `evidence_bundle`
  - `memory_audit`
  - `memory_audit_path`

验证命令：

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_adds_evidence_bundle_and_memory_audit_from_case_memory tests.test_http_entrypoint.HttpEntrypointTest.test_root_serves_interactive_frontend tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint tests.test_service_entrypoint tests.test_end_to_end_demo tests.test_mvp_flow -v
python -m scripts.end_to_end_demo
```

当前验证结果：

- service/frontend 靶向测试通过。
- `node --check web/app.js` 通过。
- HTTP/service/end-to-end/MVP flow 共 36 个测试通过。
- 标准 demo 脚本已重新生成病例：`case_20260524_184306_654717`。

### 2026-05-24 Follow-up QA 使用 LLM

本轮目标：让追问 QA 使用 LLM，但必须受 `evidence_bundle` 约束；无 LLM 或 LLM 失败时仍保留模板 fallback。

修改文件：

- `agents/gaodoctor_agent.py`
- `api/service.py`
- `memory/memory_manager.py`
- `tests/test_llm_routing.py`
- `tests/test_service_entrypoint.py`
- `goalnew.md`

已完成：

- `GaoDoctorAgent.answer_follow_up()` 改为：
  - 先读取 `MemoryManager.get_evidence_bundle(case_id)`。
  - 有 `prompt_runner` 时调用 LLM task：`follow_up_qa`。
  - LLM user payload 明确包含：
    - `question`
    - `evidence_bundle`
    - `required_safety_rules`
  - system prompt 明确约束：
    - 只能基于 `evidence_bundle` 回答。
    - 不得新增影像发现、诊断结论、指南依据或治疗建议。
    - missing/unassessed 不得解释为阴性、正常、没有发现或数值为 0。
    - 证据不完整时必须说明不确定性。
- LLM 失败或未配置时：
  - 自动回退到原来的 evidence-grounded 模板回答。
  - 不影响前端追问流程。
- `MemoryManager.append_qa_memory()` 新增 QA 记录字段：
  - `llm_used`
  - `llm_fallback_reason`
- `MedScopeService()` 默认装配：
  - `PromptRunner(OpenAICompatibleModelClient())`
  - 因此默认 HTTP/API 追问链路具备 LLM 调用能力。
  - 如果环境变量缺 API key，调用时会 fallback，不会打断病例流程。
- 诊断后的患者解释 `_explain_report()` 也增加 LLM 失败 fallback，避免默认装配 LLM 后因为缺 API key 影响诊断。

验证命令：

```bash
python -m unittest tests.test_llm_routing -v
python -m unittest tests.test_service_entrypoint tests.test_http_entrypoint tests.test_mvp_flow tests.test_memory_manager -v
python -m scripts.end_to_end_demo
```

当前验证结果：

- LLM routing / follow-up QA 测试 9 个通过。
- service/http/mvp/memory 相关 44 个测试通过。
- 标准 demo 脚本可继续运行，LLM 缺 key 时不会破坏诊断主流程。

### 2026-05-24 Image-Symptom-Skill Alignment Plan

本轮目标：协调“患者描述 + 上传医疗图像 + guideline skill”，并正式处理“当前图像不足以按指南判断，需要补充其他影像”的情况。

修改文件：

- `contracts/medical_contracts.py`
- `api/service.py`
- `agents/gaodoctor_agent.py`
- `memory/memory_manager.py`
- `skills/femoral_head_necrosis.yaml`
- `tests/test_contracts.py`
- `tests/test_service_entrypoint.py`
- `tests/test_mvp_flow.py`

已完成：

- 新增 `AlignmentPlan` 契约：
  - `evidence_sufficient`
  - `partial_evidence`
  - `insufficient_evidence`
  - `contraindicated_or_wrong_modality`
- `MedScopeService` 在 skill routing 后生成 `alignment_plan`：
  - 识别上传图像模态、部位、可用 MRI 序列。
  - 结合已选 disease skill 生成视觉任务清单。
  - 对股骨头坏死场景区分：
    - 普通髋部 X 光：`partial_evidence`
    - 询问早期/有没有/能否排除 + X 光：`insufficient_evidence`
    - MRI：`evidence_sufficient`
  - 对胶质瘤场景区分：
    - FLAIR MRI：`partial_evidence`
    - 非 MRI：`contraindicated_or_wrong_modality`
- `GaoDoctorAgent` 收到 `insufficient_evidence` 或 `contraindicated_or_wrong_modality` 时：
  - 不调用视觉模型。
  - 不生成 mask / overlay。
  - 保存一条正式病例 memory。
  - 报告中明确说明“现有影像证据不足，需补充检查后判断”。
  - 返回疑似疾病与建议补充影像。
- `MemoryManager` 的 evidence bundle 现在包含：
  - `skill_evidence.alignment_plan`
- `femoral_head_necrosis` skill 增加 `visual_protocol`：
  - X 光可评估晚期结构改变。
  - 早期坏死与骨髓水肿需要 MRI。
  - X 光不足以排除早期病变。

验证命令：

```bash
python -m unittest tests.test_contracts tests.test_service_entrypoint tests.test_mvp_flow -v
python -m json.tool skills/femoral_head_necrosis.yaml >/tmp/fhn_skill_check.json
python -m unittest discover -v
```

当前验证结果：

- alignment plan 靶向测试通过。
- service / MVP / contract 相关 36 个测试通过。
- `skills/femoral_head_necrosis.yaml` JSON 校验通过。
- 全量测试 172 个通过。
- 临时真实 service 调用验证：
  - `analysis_status = insufficient_evidence`
  - `required_next_images[0].modality = MRI`
  - `image_outputs.mask_path = not_generated`

### 2026-05-24 前端展示 Alignment Plan

本轮目标：把后端 `alignment_plan` 展示到交互前端，让“上传图像是否满足 skill 指南证据要求”可以直接演示。

修改文件：

- `web/index.html`
- `web/app.js`
- `web/app.css`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

已完成：

- 病例输入区新增：
  - `X 光证据不足样例`
- 前端新增 `证据协调` 面板：
  - 显示 `analysis_status`
  - 显示当前图像模态、部位、可用序列
  - 显示选中的 skill
  - 显示每个视觉任务是可执行还是缺少输入
  - 显示疑似疾病方向
  - 显示建议补充的影像
  - 显示证据限制
- `renderPayload()` 现在会同时渲染：
  - 图像输出
  - 诊断报告
  - alignment plan
  - evidence bundle
  - memory audit
- X 光证据不足样例会填入：
  - `左髋疼痛，X光能不能判断有没有早期股骨头坏死？`
  - `output/fake/uploads/hip_xray.png`
  - `髋关节疼痛`
- 该样例用于演示：
  - `insufficient_evidence`
  - 疑似股骨头坏死
  - X 光不足以排除早期病变
  - 建议补充双髋 MRI
  - 不生成 mask

验证命令：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_root_serves_interactive_frontend tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint -v
python -m unittest discover -v
```

当前验证结果：

- 前端静态入口靶向测试通过。
- `node --check web/app.js` 通过。
- HTTP 入口 15 个测试通过。
- 全量测试 172 个通过。

### 2026-05-24 AlignmentPlanner 通用化

本轮目标：把 `alignment_plan` 从 `api.service` 中的病种分支逻辑，升级为由 `skill.visual_protocol` 驱动的通用 planner，避免后续新增病种时反复改 service 主流程。

修改文件：

- `tools/alignment_planner.py`
- `api/service.py`
- `skills/femoral_head_necrosis.yaml`
- `skills/diffuse_glioma_brats.yaml`
- `tests/test_alignment_planner.py`
- `tests/test_service_entrypoint.py`
- `goalnew.md`

已完成：

- 新增 `AlignmentPlanner`：
  - 输入 `payload`
  - 输入 `routing_decision`
  - 输入 `disease_skill.visual_protocol`
  - 输出标准 `AlignmentPlan`
- `MedScopeService` 现在只做：
  - skill routing
  - load skill
  - 调用 `AlignmentPlanner.build_plan(...)`
  - 不再保留 `_build_femoral_head_alignment_plan` / `_build_glioma_alignment_plan` 这类 alignment 病种分支。
- `femoral_head_necrosis.visual_protocol` 增加：
  - `alignment_tasks`
  - `required_next_images`
  - `suspected_conditions`
  - `diagnosis_scope`
  - `insufficiency_rules`
- `diffuse_glioma_brats.visual_protocol` 增加：
  - `imaging_modalities`
  - `alignment_tasks`
  - `required_next_images`
  - `suspected_conditions`
  - `diagnosis_scope`
- 新增测试锁定：
  - planner 能基于股骨头坏死 skill 生成 X 光早期证据不足 plan。
  - planner 能基于胶质瘤 skill 生成 FLAIR MRI 部分证据 plan。
  - service 使用注入的 planner，而不是自己生成 alignment 分支。

验证命令：

```bash
python -m unittest tests.test_alignment_planner -v
python -m unittest tests.test_alignment_planner tests.test_service_entrypoint tests.test_http_entrypoint tests.test_mvp_flow -v
python -m json.tool skills/femoral_head_necrosis.yaml >/tmp/fhn_skill_check.json
python -m json.tool skills/diffuse_glioma_brats.yaml >/tmp/glioma_skill_check.json
python -m unittest discover -v
```

当前验证结果：

- planner 单元测试 3 个通过。
- 相关测试 42 个通过。
- 两个 skill 文件 JSON 校验通过。
- 全量测试 176 个通过。
- 临时真实 service 调用验证：
  - `analysis_status = insufficient_evidence`
  - 第一项视觉任务来自 skill：`assess_late_xray_findings`
  - `required_next_images[0].modality = MRI`
  - `image_outputs.mask_path = not_generated`

### 2026-05-24 Visual Protocol Schema Validator

本轮目标：先把 `visual_protocol` 做成可校验契约，避免 Skill Builder 生成“看起来像 guideline skill、但缺少图像-症状-skill 协调字段”的不完整正式 skill。

修改文件：

- `tools/visual_protocol_validator.py`
- `tools/skill_builder_tool.py`
- `tests/test_visual_protocol_validator.py`
- `goalnew.md`

已完成：

- 新增 `VisualProtocolValidator`，用于校验 guideline skill 的 `visual_protocol`。
- 当前强制检查：
  - `visual_protocol.disease_target`
  - `visual_protocol.alignment_tasks`
  - 每个 `alignment_tasks[].task`
  - 每个 `alignment_tasks[].required_modalities`
  - `visual_protocol.required_modalities`
  - `visual_protocol.required_next_images`
  - `visual_protocol.diagnosis_scope`
- 当前警告检查：
  - `diagnosis_scope.allowed`
  - `diagnosis_scope.blocked`
  - `insufficiency_rules`
- `SkillBuilderTool._attach_guideline_quality_control()` 已接入 validator。
- `quality_control` 新增：
  - `visual_protocol_status`
  - `visual_protocol_errors`
  - `visual_protocol_warnings`
- `formal_skill_status` 和 `can_enter_formal_guideline_skill` 现在受 `visual_protocol` 有效性约束：
  - 缺少 `required_next_images` 或 `alignment_tasks` 时不能进入 `formal_ready`。
  - 缺少 `diagnosis_scope.blocked` 会进入 warning，用于提醒不能明确阻断哪些错误结论。
- 两个静态 skill：
  - `skills/femoral_head_necrosis.yaml`
  - `skills/diffuse_glioma_brats.yaml`
  已通过 validator。

验证命令：

```bash
python -m unittest tests.test_visual_protocol_validator -v
python -m unittest tests.test_visual_protocol_validator tests.test_guideline_skill_builder tests.test_guideline_import_pipeline tests.test_alignment_planner tests.test_service_entrypoint -v
```

当前验证结果：

- `tests.test_visual_protocol_validator` 6 个测试通过。
- Skill Builder、指南导入、AlignmentPlanner、Service 相关 44 个测试通过。

下一步：

- 做 Skill Builder 自动生成 `visual_protocol`，让从指南文本/PDF 导入的 skill 不再只生成简化字段，而是尽量自动补齐 `alignment_tasks`、`required_next_images`、`diagnosis_scope` 和 `insufficiency_rules`。

### 2026-05-24 Skill Builder 自动生成 Visual Protocol

本轮目标：让 Skill Builder 不依赖人工手写完整 `visual_protocol`。当指南采集/导入只提取到 `required_image_views`、`vision_agent_tasks`、`visual_targets`、`staging_rules` 或半成品 `required_modalities` 时，自动补齐图像-症状-skill 协调所需字段。

修改文件：

- `tools/visual_protocol_builder.py`
- `tools/skill_builder_tool.py`
- `tests/test_guideline_skill_builder.py`
- `tests/test_visual_protocol_validator.py`
- `goalnew.md`

已完成：

- 新增 `VisualProtocolBuilder`。
- `SkillBuilderTool.build_guideline_skill_from_search()` 现在会在质量控制前调用 builder：
  - 没有 `visual_protocol` 时，从指南字段生成一个协议。
  - 已有半成品 `visual_protocol` 时，保留已有字段并补齐缺失字段。
- 自动生成/补齐字段包括：
  - `disease_target`
  - `clinical_focus`
  - `imaging_modalities`
  - `available_modalities`
  - `required_modalities`
  - `alignment_tasks`
  - `measurements`
  - `suspected_conditions`
  - `required_next_images`
  - `diagnosis_scope.allowed`
  - `diagnosis_scope.blocked`
  - `insufficiency_rules`
- 股骨头坏死离线指南目录本身没有 `visual_protocol` 段，现在 Skill Builder 可自动生成有效协议：
  - 自动推断 MRI 是下一步关键影像。
  - 自动生成 `blocked` 约束，避免把 X 光阴性误当作无病。
- 胶质瘤指南目录原先只有半成品 `required_modalities`，现在可自动补齐：
  - `alignment_tasks`
  - `required_next_images`
  - `diagnosis_scope`
  - `insufficiency_rules`
- `formal_skill_status` 现在能正确区分：
  - 可推导出完整视觉协议的 guideline skill：`formal_ready`
  - 只有症状、没有影像任务/模态依据的 guideline skill：`needs_review`

验证命令：

```bash
python -m unittest tests.test_guideline_skill_builder.GuidelineSkillBuilderTest.test_skill_builder_uses_guideline_search_for_guideline_based_skill tests.test_guideline_skill_builder.GuidelineSkillBuilderTest.test_guideline_search_result_builds_actionable_guideline_skill -v
python -m unittest tests.test_visual_protocol_validator tests.test_guideline_skill_builder tests.test_guideline_import_pipeline tests.test_alignment_planner tests.test_service_entrypoint tests.test_guideline_source_collector -v
```

当前验证结果：

- 自动生成 visual protocol 的两个靶向测试通过。
- Validator、Skill Builder、指南导入、AlignmentPlanner、Service、真实网页/PDF 指南采集器相关 50 个测试通过。

下一步：

- 做诊断 Agent 受 `alignment_plan` 强约束：如果 alignment 已判断证据不足或模态不匹配，诊断 Agent 和 follow-up QA 都不能输出越权结论，只能解释当前证据限制、疑似方向和下一步影像需求。

### 2026-05-24 Diagnosis Agent 受 Alignment Plan 强约束

本轮目标：让诊断医生 Agent 和 follow-up QA 都不能绕过 `alignment_plan`。如果图像-症状-skill 协调层已经标记证据不足、模态不匹配或存在 blocked 结论，报告和追问必须显式承认这些限制。

修改文件：

- `agents/diagnosis_agent.py`
- `agents/gaodoctor_agent.py`
- `tests/test_diagnosis_llm_workflow.py`
- `tests/test_llm_routing.py`
- `goalnew.md`

已完成：

- `DiagnosisDoctorAgent.generate_report()` 新增可选 `alignment_plan` 入参。
- GaoDoctor 正常诊断链路现在会把 service 生成的 `alignment_plan` 传给诊断医生 Agent。
- 诊断医生 LLM prompt 的 user payload 现在包含：
  - `visual_result`
  - `disease_skill`
  - `alignment_plan`
  - `required_report_fields`
- 如果 `alignment_plan.analysis_status` 是：
  - `insufficient_evidence`
  - `contraindicated_or_wrong_modality`
  诊断医生 Agent 会跳过 LLM，直接生成受限报告。
- 受限报告固定表达：
  - 现有影像证据不足
  - 暂无法可靠分期或排除诊断
  - 必须补充 `required_next_images`
  - 必须保留 `diagnosis_scope.blocked`
- 如果是 `partial_evidence`，诊断医生 Agent 会把以下内容合并进报告：
  - `insufficiency_reasons`
  - `diagnosis_scope.blocked`
  - `required_next_images`
  - 原始 `alignment_plan`
- LLM 报告新增 alignment 校验：
  - 阻断态不能输出确诊式或排除式结论。
  - 不能违反 `diagnosis_scope.blocked`，例如“缺少 T1ce”时不能说“未见强化/强化为 0”。
- follow-up QA 新增 evidence bundle 校验：
  - LLM 回答如果把 missing/unassessed 视觉证据解释成阴性、正常、未见或 0，会被拒绝。
  - 被拒绝后回退到 evidence bundle 模板回答，并记录 `llm_fallback_reason`。

验证命令：

```bash
python -m unittest tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_passes_and_applies_partial_alignment_plan_to_llm_report tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_blocks_llm_when_alignment_plan_is_insufficient tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_rejects_follow_up_llm_answer_that_violates_alignment_plan -v
python -m unittest tests.test_diagnosis_llm_workflow tests.test_llm_routing tests.test_mvp_flow tests.test_service_entrypoint tests.test_http_entrypoint -v
```

当前验证结果：

- alignment 强约束 3 个靶向测试通过。
- 诊断、LLM 路由、MVP、Service、HTTP 入口相关 63 个测试通过。

下一步：

- 做前端和 memory audit 增强：把 `visual_protocol` 质量状态、自动生成状态、alignment 约束、QA 安全回退和四类 memory 在演示页面与 audit 中更清楚地展示。

### 2026-05-24 前端与 Memory Audit 增强

本轮目标：让端到端演示不需要打开原始 JSON，也能看到四类 memory、skill 质量、alignment 约束、QA 安全回退和证据缺失状态。

修改文件：

- `memory/memory_manager.py`
- `web/app.js`
- `web/app.css`
- `tests/test_memory_manager.py`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

已完成：

- `MemoryManager.build_audit_summary()` 新增 `memory_type_details`：
  - `patient_memory`：patient、intent、symptom、QA 数量摘要。
  - `image_memory`：modality、body_part、segmentation_quality、measurement 数量、缺失证据数量、是否有 overlay。
  - `skill_memory`：selected_skill、used_skill、skill_type、formal_skill_status、visual_protocol_status。
  - `reasoning_memory`：diagnostic_tendency、used_visual_fields、missing_visual_fields_acknowledged、不确定性和 follow-up 数量。
- audit 新增 `alignment_summary`：
  - `analysis_status`
  - `clinical_focus`
  - `blocked_scopes`
  - `required_next_images`
  - `visual_task_status_counts`
- audit 新增 `skill_quality`：
  - `formal_skill_status`
  - `visual_protocol_status`
  - `visual_protocol_errors`
  - `visual_protocol_warnings`
  - `citation_status`
  - `conflict_status`
- audit 新增 `qa_safety`：
  - 是否要求 evidence bundle
  - QA 历史数量
  - LLM 使用次数
  - fallback 次数
  - blocked scopes
  - missing/unassessed 数量
- 前端 `Memory Trace` 面板新增渲染：
  - `Memory Details`
  - `Alignment Summary`
  - `Skill Quality`
  - `QA Safety`
- 前端 `证据充分性` 面板的 Skill 区域新增展示：
  - `formal_skill_status`
  - `visual_protocol_status`
- 追问 thinking / 防重复发送仍保留。

验证命令：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_audit_summary_writes_fake_output_report tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_memory_manager tests.test_http_entrypoint tests.test_service_entrypoint tests.test_mvp_flow -v
python -m unittest discover -v
```

当前验证结果：

- Memory audit 与前端静态资源靶向测试通过。
- `node --check web/app.js` 通过。
- Memory / HTTP / Service / MVP 相关 47 个测试通过。
- 全量测试 185 个通过。

当前四步目标状态：

- [x] visual_protocol schema validator
- [x] Skill Builder 自动生成 visual_protocol
- [x] 诊断 Agent 受 alignment_plan 强约束
- [x] 前端和 memory audit 增强

### 2026-05-24 标准端到端演示样例固化

本轮目标：把“上传图片 + 自动选 skill + 分割结果 + 诊断报告 + evidence bundle + memory audit”固化成一条可演示流程，并提供一键 demo 脚本和验收测试。

修改文件：

- `scripts/end_to_end_demo.py`
- `tests/test_end_to_end_demo.py`
- `goalnew.md`

已完成：

- 新增标准 demo suite 入口：

```bash
python -m scripts.end_to_end_demo --suite
```

- `--suite` 默认输出到 `output/fake/standard_demo/`，显式传 `--output-dir` 时仍尊重用户指定目录。
- demo suite 固化两条代表性病例：
  - `glioma_ground_truth`：上传 BraTS FLAIR MRI，自动选择 `diffuse_glioma_brats`，运行 ground-truth 分割链路，输出 mask/overlay、结构化视觉证据、诊断报告、evidence bundle 和 memory audit。
  - `xray_insufficient_evidence`：上传髋部 X 光占位图并描述早期股骨头坏死疑问，自动选择 `femoral_head_necrosis`，根据指南/visual protocol 判断现有图像证据不足，不生成 mask，明确提示需要双髋 MRI。
- 每个 demo case 都有独立目录：
  - `uploads/`
  - `memory/`
  - `artifacts/`
- 每个 demo case 都写出：
  - response JSON
  - evidence bundle JSON
  - memory audit JSON
- suite 顶层写出：
  - `output/fake/standard_demo/standard_demo_summary.json`
  - `output/fake/standard_demo/demo_summary.md`
- 新增验收测试覆盖：
  - 单例端到端 demo
  - 标准双病例 demo suite
  - CLI 指定输出目录
  - CLI `--suite` 默认输出目录

验收命令：

```bash
python -m unittest tests.test_end_to_end_demo -v
python -m scripts.end_to_end_demo --suite
python -m unittest tests.test_end_to_end_demo tests.test_service_entrypoint tests.test_mvp_flow tests.test_http_entrypoint -v
python -m unittest discover -v
```

当前验证结果：

- `tests.test_end_to_end_demo` 4 个测试通过。
- 标准 demo 命令成功写入 `output/fake/standard_demo/`。
- End-to-end / Service / MVP / HTTP 相关 43 个测试通过。
- 全量测试 188 个通过。

当前标准 demo 状态：

- [x] 上传图片
- [x] 自动选择 skill
- [x] 视觉分割或证据不足跳过分割
- [x] 输出分割图/overlay 或明确 `not_generated`
- [x] 输出诊断报告
- [x] 输出 evidence bundle
- [x] 输出 memory audit
- [x] 一键脚本可跑
- [x] 验收测试覆盖

### 2026-05-24 Memory Manager 演示闭环增强

本轮目标：让已生成的 case memory 不只作为内部文件存在，而是能被独立查询、审计和演示回放，支撑前端展示完整 Agent 证据链。

修改文件：

- `memory/memory_manager.py`
- `api/http_server.py`
- `api/service.py`
- `web/app.js`
- `web/app.css`
- `tests/test_memory_manager.py`
- `tests/test_http_entrypoint.py`
- `tests/test_service_entrypoint.py`
- `goalnew.md`

已完成：

- MemoryManager 新增 `list_case_summaries(limit)`：
  - 返回近期病例的安全摘要。
  - 包含 `case_id`、`patient_id`、`selected_skill`、`analysis_status`、影像模态、诊断倾向和 QA 数量。
  - 不暴露完整 `patient_message`。
- MemoryManager 新增 `build_case_replay(case_id)`：
  - 回放 `GaoDoctorAgent` 患者入口。
  - 回放 `SkillBuilderAgent` skill 路由和 alignment 状态。
  - 回放 `VisionAgent` 视觉证据、测量、completeness 和分割质量。
  - 回放 `DiagnosisDoctorAgent` 诊断倾向、关键证据和不确定性。
  - 回放 `MemoryManager` evidence bundle / audit 状态。
  - 如果有追问，追加 follow-up QA 回放步骤。
- HTTP API 新增 memory 查询入口：

```text
GET /v1/memory/cases?limit=20
GET /v1/memory/cases/{case_id}
GET /v1/memory/cases/{case_id}/replay
GET /v1/memory/cases/{case_id}/evidence-bundle
GET /v1/memory/cases/{case_id}/audit
```

- Service 正常诊断响应现在会附带：
  - `evidence_bundle`
  - `memory_audit`
  - `memory_replay`
  - `memory_audit_path`
- 前端 `Memory Trace` 面板新增 `Memory Replay` 区域：
  - 展示每一步 Agent 名称。
  - 展示患者入口、skill 路由、视觉证据、诊断推理、memory audit、follow-up QA。
  - 如果响应中没有 `memory_replay`，会通过 `/v1/memory/cases/{case_id}/replay` 拉取。
- 标准 demo 已重新运行，两个病例 response JSON 均包含 `memory_replay`。

验收命令：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_list_case_summaries_returns_demo_safe_metadata tests.test_memory_manager.MemoryManagerQueryTest.test_build_case_replay_returns_agent_step_timeline tests.test_http_entrypoint.HttpEntrypointTest.test_get_memory_cases_returns_recent_case_summaries tests.test_http_entrypoint.HttpEntrypointTest.test_get_memory_case_replay_bundle_and_audit tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_adds_evidence_bundle_and_memory_audit_from_case_memory -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_memory_manager tests.test_http_entrypoint tests.test_service_entrypoint tests.test_mvp_flow -v
python -m scripts.end_to_end_demo --suite
rg -n "memory_replay" output/fake/standard_demo/cases/*/artifacts/*_response.json
python -m unittest discover -v
```

当前验证结果：

- Memory replay / memory API / service trace 5 个靶向测试通过。
- 前端静态资源测试通过。
- `node --check web/app.js` 通过。
- Memory / HTTP / Service / MVP 相关 51 个测试通过。
- 标准 demo 成功写入 `output/fake/standard_demo/`，两个 response JSON 均包含 `memory_replay`。
- 全量测试 192 个通过。

当前 Memory Manager 状态：

- [x] 四类 memory 持久化
- [x] evidence bundle
- [x] memory audit
- [x] case summary 查询
- [x] case replay 回放
- [x] memory HTTP 查询 API
- [x] service 响应附带 memory replay
- [x] 前端 Memory Trace 展示 replay

### 2026-05-24 通用视觉工具路由与 QC 门控底座

本轮目标：把视觉 Agent 从“某个病种分割 demo”向“skill 驱动的通用视觉工具路由框架”推进。核心原则是：Skill 定义视觉任务和缺失约束，Vision Agent 根据任务选择工具、生成任务级结果，并用 QC 决定结果是否能进入诊断推理。

修改文件：

- `contracts/medical_contracts.py`
- `agents/vision_agent.py`
- `agents/diagnosis_agent.py`
- `tools/visual_tool_router.py`
- `tools/visual_quality_gate.py`
- `tools/visual_tool_registry.yaml`
- `tests/test_contracts.py`
- `tests/test_visual_tool_router.py`
- `tests/test_brats_vision_tools.py`
- `tests/test_diagnosis_llm_workflow.py`
- `goalnew.md`

已完成：

- 新增通用视觉契约：
  - `VisualTask`
  - `VisualToolCapability`
  - `SegmentationResult`
- `SegmentationResult` 固定任务级输出字段：
  - `task_name`
  - `target`
  - `status`
  - `mask_path`
  - `overlay_path`
  - `measurements`
  - `quality`
  - `completeness`
  - `diagnosis_usable`
- `SegmentationResult.status` 当前支持：
  - `completed`
  - `missing_input`
  - `no_capable_tool`
  - `low_quality`
- 新增 `tools/visual_tool_registry.yaml`：
  - `brats_model`：专病/多标签分割工具占位能力。
  - `medsam2`：注册为 `candidate_segmenter`，即通用候选病灶生成器，而不是最终真理。
  - `xray_fhn_detector`：X 光股骨头结构征象规则/检测工具占位能力。
- 新增 `VisualToolRegistry` 和 `VisualToolRouter`：
  - 从 skill 的 `visual_protocol.alignment_tasks` 生成 `VisualTask`。
  - 根据 available modalities 判断 `missing_input`。
  - 优先选择专病工具。
  - 没有专病工具时允许回退到 MedSAM2 candidate。
  - 没有任何能力覆盖时返回 `no_capable_tool`。
- 新增 `VisualQualityGate`：
  - 对任务级分割结果打 `quality.score`、`quality.level`、`quality.warnings`。
  - 空 mask / 零体积等情况标记为 `low_quality`。
  - `low_quality` 和跳过任务统一 `diagnosis_usable=false`。
- Vision Agent 现在会在 `visual_evidence` 中附带：
  - `visual_tool_plan`
  - `segmentation_results`
- Diagnosis Agent 增加视觉可用性门控：
  - 如果某个 `segmentation_result.diagnosis_usable=false`，对应测量字段会置为 `null`。
  - 对应 completeness 会改为 `low_quality`、`missing` 或 `unassessed`。
  - 报告不确定性会明确说明该字段不能作为诊断可用证据。
- 标准 demo 已重新运行，胶质瘤病例 response JSON 已包含：
  - `visual_tool_plan`
  - `segmentation_results`
  - `diagnosis_usable`
- 通用 `visual_protocol` 执行器已接入高医生胶质瘤入口：
  - `ground_truth` 模式通过 `VisionAgent.analyze_with_visual_protocol(...)` 执行。
  - `medsam2` 模式通过同一个通用入口执行模型分割。
  - NIfTI mask / overlay 会在通用入口内自动切换到 NIfTI reader 和 overlay generator。
  - 高医生不再直接绑定 `analyze_brats_nifti_ground_truth` 或 `analyze_brats_with_segmentation_model`。

验收命令：

```bash
python -m unittest tests.test_contracts.ContractBoundaryTest.test_visual_task_contract_is_derived_from_skill_protocol_task tests.test_contracts.ContractBoundaryTest.test_visual_tool_capability_contract_declares_supported_tasks_and_modalities tests.test_contracts.ContractBoundaryTest.test_segmentation_result_contract_blocks_low_quality_from_diagnosis tests.test_contracts.ContractBoundaryTest.test_segmentation_result_rejects_unsupported_status tests.test_visual_tool_router tests.test_brats_vision_tools.BratsVisionToolsTest.test_vision_agent_attaches_tool_routing_and_qc_task_results -v
python -m unittest tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_excludes_not_usable_segmentation_measurements -v
python -m unittest tests.test_contracts tests.test_visual_tool_router tests.test_brats_vision_tools tests.test_diagnosis_llm_workflow tests.test_medsam2_segmentation_tool tests.test_mvp_flow -v
python -m scripts.end_to_end_demo --suite
rg -n "visual_tool_plan|segmentation_results|diagnosis_usable" output/fake/standard_demo/cases/glioma_ground_truth/artifacts/glioma_ground_truth_response.json
python -m unittest discover -v
python -m unittest tests.test_brats_vision_tools tests.test_medsam2_segmentation_tool tests.test_mvp_flow tests.test_diagnosis_llm_workflow -v
```

当前验证结果：

- 通用视觉契约、Router、QC、VisionAgent task-level 输出 11 个靶向测试通过。
- 诊断 Agent 排除 `diagnosis_usable=false` 测量的靶向测试通过。
- Contracts / Router / Vision / Diagnosis / MedSAM2 / MVP 相关 64 个测试通过。
- 标准 demo 成功写入 `output/fake/standard_demo/`，胶质瘤 response JSON 包含 `visual_tool_plan`、`segmentation_results`、`diagnosis_usable`。
- 全量测试 207 个通过。
- 高医生通用视觉入口接入后的 Vision / MedSAM2 / MVP / Diagnosis 相关 44 个测试通过。

当前视觉 Agent 状态：

- [x] skill 定义视觉任务和缺失约束
- [x] VisualTask / SegmentationResult / VisualToolCapability 契约
- [x] visual tool registry
- [x] VisualToolRouter
- [x] MedSAM2 注册为 candidate segmenter
- [x] QualityGate
- [x] VisionAgent 输出 task-level segmentation results
- [x] DiagnosisAgent 不使用 `diagnosis_usable=false` 的测量
- [x] 高医生胶质瘤 `ground_truth` / `medsam2` 入口已切到通用 `visual_protocol` executor
- [ ] 专病模型真实 runner 仍需按工具注册表逐步接入
- [ ] 解剖区域合理性、多 prompt 稳定性、多模态一致性 QC 仍是下一阶段增强项

### 2026-05-25 Skill 驱动多征象视觉证据 Bundle

本轮目标：回应“同一张医疗图像可能存在多个病情/多个征象”的主线需求，把无 mask 输入链路从“生成一个分割 summary”推进为“生成可直接传给诊断 Agent 的多征象视觉证据包”。该证据包仍然只描述影像观测，不输出最终诊断。

修改文件：

- `scripts/no_mask_skill_visual_pipeline_demo.py`
- `tests/test_no_mask_skill_visual_pipeline_demo.py`
- `goalnew.md`

已完成：

- `scripts.no_mask_skill_visual_pipeline_demo` 在完成 anatomy reference + finding segmentation 后，会生成顶层 `visual_evidence_bundle`。
- `visual_evidence_bundle` 当前包含：
  - `schema_version`
  - `disease_target`
  - `image_context`
  - `image_outputs`
  - `present_findings`
  - `findings`
  - `numeric_evidence`
  - `text_evidence`
  - `completeness`
  - `segmentation_results`
  - `visual_tool_plan`
  - `diagnosis_payload`
- 支持一张图中多个 finding，例如 `sclerotic_band` 和 `cystic_change` 同时存在时，会保留各自的：
  - mask / overlay 路径
  - bbox / centroid
  - 面积
  - 图像面积占比
  - 解剖区域面积占比
  - VLM rationale
  - MedSAM2 质量与可诊断性标记
- 新增 `numeric_evidence` 汇总层，供前端和 memory audit 快速展示：
  - `finding_count`
  - `region_count`
  - `total_area_px`
  - `sum_area_ratio_in_image`
  - `max_area_ratio_in_anatomy`
- 明确 `total_area_px` 是各 finding 候选 mask 面积求和，可能因重叠而重复计数；诊断 Agent 应按 finding 逐项推理。
- `diagnosis_payload` 复用现有 `VisualAnalysisResult` 兼容结构，后续可以直接交给 Diagnosis Agent。

验收命令：

```bash
python -m unittest tests.test_no_mask_skill_visual_pipeline_demo -v
python -m unittest tests.test_no_mask_skill_visual_pipeline_demo tests.test_no_mask_medsam2_segmentation_demo tests.test_no_mask_candidate_diagnosis_demo tests.test_visual_protocol_validator tests.test_diagnosis_llm_workflow tests.test_contracts tests.test_visual_tool_router -v
```

当前验证结果：

- 单项多征象 pipeline 测试通过。
- 视觉 no-mask demo、候选诊断 demo、visual protocol validator、诊断 Agent、contracts、VisualToolRouter 相关 58 个测试通过。

当前视觉 Agent 状态追加：

- [x] 无 mask 医疗图像可以由 skill finding_targets 驱动生成多个候选征象。
- [x] 每个候选征象可以分别调用 MedSAM2 生成 mask / overlay。
- [x] 多个候选征象可汇总为 `visual_evidence_bundle`，包含文本证据、数值证据和诊断输入 payload。
- [x] `GaoDoctorAgent` 主流程会把 `visual_result` 汇总为 `image_memory.visual_evidence_bundle`。
- [x] `MemoryManager.get_evidence_bundle()` 会在 `image_evidence.visual_evidence_bundle` 中透传该结构，供 QA、memory audit 和前端读取。
- [x] API/service 响应已把 `visual_evidence_bundle` 提到顶层，前端无需深挖 memory JSON。
- [x] 前端图像输出和证据充分性面板已展示多征象列表、finding 数量和数值汇总。
- [x] no-mask pipeline 已支持多个 anatomy candidate，并按 lesion/anatomy overlap 为每个 finding 选择最佳解剖参照。

### 2026-05-25 多征象 Bundle 接入高医生主流程与 Memory

本轮目标：把上一阶段 demo script 里的 `visual_evidence_bundle` 接入五 Agent 主线，保证上传图像后的视觉证据不只停留在脚本产物，而是能进入 case memory 和 evidence bundle，供诊断、QA、审计和前端展示复用。

修改文件：

- `agents/gaodoctor_agent.py`
- `memory/memory_manager.py`
- `tests/test_mvp_flow.py`
- `goalnew.md`

已完成：

- `GaoDoctorAgent.handle_patient_case(...)` 在视觉 Agent 返回 `visual_result` 后，会生成 `visual_evidence_bundle` 并写入 `image_memory`。
- `visual_evidence_bundle` 保持与 no-mask demo 一致的核心字段：
  - `schema_version`
  - `disease_target`
  - `image_context`
  - `image_outputs`
  - `present_findings`
  - `findings`
  - `numeric_evidence`
  - `text_evidence`
  - `completeness`
  - `segmentation_results`
  - `visual_tool_plan`
  - `diagnosis_payload`
- `MemoryManager._normalize_image_memory(...)` 会保留该字段，旧病例没有该字段时默认 `{}`，避免破坏 legacy memory。
- `MemoryManager.get_evidence_bundle(...)` 会把该字段暴露到 `image_evidence.visual_evidence_bundle`。
- `build_audit_summary(...)` 的 image memory 细节新增 `finding_count`，便于审计看到当前病例是否有多征象结构化输出。
- 新增主流程测试：假的 VisionAgent 返回 `sclerotic_band` 和 `cystic_change` 两个 finding，验证：
  - case memory 保存 `visual_evidence_bundle`
  - `present_findings` 为两个征象
  - `numeric_evidence.total_area_px` 正确汇总
  - `diagnosis_payload` 保留第二个 finding
  - `MemoryManager.get_evidence_bundle()` 可读取该 bundle
  - Diagnosis Agent 的 key evidence 能使用多 finding 形成候选影像依据

验收命令：

```bash
python -m unittest tests.test_mvp_flow.MedScopeMvpFlowTest.test_gaodoctor_persists_multifinding_visual_evidence_bundle_to_memory -v
python -m unittest tests.test_mvp_flow tests.test_memory_manager tests.test_no_mask_skill_visual_pipeline_demo tests.test_no_mask_medsam2_segmentation_demo tests.test_no_mask_candidate_diagnosis_demo tests.test_diagnosis_llm_workflow tests.test_contracts tests.test_visual_tool_router -v
```

当前验证结果：

- 主流程多征象 bundle 单测通过。
- MVP flow、MemoryManager、no-mask pipeline、候选诊断、Diagnosis Agent、Contracts、VisualToolRouter 相关 71 个测试通过。

下一步：

- 把 `visual_evidence_bundle` 接到 API/service 响应和前端展示层，让用户在交互界面能看到“病灶图 + 多征象列表 + 数值证据 + evidence bundle 摘要”。

### 2026-05-25 多征象 Bundle 接入 API/service 与前端展示

本轮目标：把 `visual_evidence_bundle` 从主流程 memory 继续暴露到 API/service 响应和交互前端，避免前端只能看到报告或原始 memory JSON。

修改文件：

- `api/service.py`
- `web/app.js`
- `web/app.css`
- `tests/test_service_entrypoint.py`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

已完成：

- `MedScopeService._attach_case_outputs(...)` 会从 case memory / evidence bundle 中读取 `visual_evidence_bundle`，并放到响应顶层 `result["visual_evidence_bundle"]`。
- `web/app.js` 新增：
  - `getVisualEvidenceBundle(...)`
  - `renderVisualEvidenceBundle(...)`
  - `renderFindingList(...)`
- 图像输出面板现在会显示：
  - `finding_count`
  - `total_area_px`
  - `present_findings`
  - 每个 finding 的 target、status、confidence、area、图像占比、解剖占比和 region 数量。
- 证据充分性面板新增“多征象视觉证据”区块，展示同一份 bundle 的数值和 finding 列表。
- 前端仍不显示调试 JSON，不把 mask 路径作为患者输入暴露；mask/overlay 只作为视觉 Agent 输出展示。

验收命令：

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_adds_evidence_bundle_and_memory_audit_from_case_memory -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_service_entrypoint tests.test_http_entrypoint tests.test_mvp_flow tests.test_memory_manager tests.test_no_mask_skill_visual_pipeline_demo tests.test_no_mask_medsam2_segmentation_demo tests.test_no_mask_candidate_diagnosis_demo -v
```

当前验证结果：

- service 顶层 `visual_evidence_bundle` 透传测试通过。
- 前端静态资产测试确认包含多征象渲染函数和字段。
- `node --check web/app.js` 通过。
- service/http/mvp/memory/no-mask 相关 62 个测试通过。

下一步：

- 继续补左右侧和解剖参照匹配：当 VLM 同时返回双侧股骨头或多个解剖区域时，finding 应匹配最近/同侧 anatomy mask，避免面积归一化取错侧。

### 2026-05-25 多 Anatomy Candidate 的同侧/重叠匹配

本轮目标：解决多解剖参照场景下的归一化风险。典型问题是髋部 X 光同时出现左右股骨头，如果 finding 永远使用第一个 anatomy mask，`area_ratio_in_anatomy` 会归一化到错误侧，后续诊断 Agent 得到的数值证据就不可信。

修改文件：

- `scripts/no_mask_medsam2_segmentation_demo.py`
- `scripts/no_mask_skill_visual_pipeline_demo.py`
- `tests/test_no_mask_medsam2_segmentation_demo.py`
- `tests/test_no_mask_skill_visual_pipeline_demo.py`
- `goalnew.md`

已完成：

- `run_no_mask_medsam2_segmentation_demo(...)` 新增可选 `anatomy_candidates`。
- 每个 finding 分割完成后，会对所有 anatomy candidate 分别测量：
  - `lesion_overlap_anatomy_px`
  - `lesion_area_ratio_in_anatomy`
  - `anatomy_area_px`
- 系统按 `max_lesion_overlap_anatomy_px` 为该 finding 选择最佳 anatomy mask。
- 输出中保留：
  - `anatomy_match`
  - `anatomy_candidates_evaluated`
  - 选中的 `anatomy_name`
- `run_no_mask_skill_visual_pipeline_demo(...)` 会从 anatomy segmentation summary 的多个 anatomy findings 中提取 candidates，并传给 finding segmentation。
- 新增测试覆盖：
  - 单个 finding 位于右侧时，不使用第一个左侧 anatomy mask，而是选择右侧 overlap 最大的 anatomy mask。
  - skill pipeline 的 anatomy reference 阶段返回左右两个股骨头时，finding 阶段可正确匹配右侧股骨头。

验收命令：

```bash
python -m unittest tests.test_no_mask_medsam2_segmentation_demo.NoMaskMedSAM2SegmentationDemoTest.test_demo_matches_each_finding_to_best_overlapping_anatomy_candidate -v
python -m unittest tests.test_no_mask_skill_visual_pipeline_demo.NoMaskSkillVisualPipelineDemoTest.test_pipeline_passes_multiple_anatomy_masks_for_same_side_matching -v
python -m unittest tests.test_no_mask_medsam2_segmentation_demo tests.test_no_mask_skill_visual_pipeline_demo tests.test_no_mask_candidate_diagnosis_demo tests.test_mvp_flow tests.test_memory_manager tests.test_service_entrypoint tests.test_http_entrypoint -v
```

当前验证结果：

- anatomy overlap 匹配单测通过。
- skill pipeline 多 anatomy candidate 传递测试通过。
- no-mask、MVP、memory、service、HTTP/frontend 相关 64 个测试通过。

下一步：

- 把这套 anatomy matching 信息进一步展示到前端 finding 列表里，例如显示 `anatomy_match.anatomy_name` 和匹配 overlap，方便人工审查分割是否归一化到正确解剖区域。

### 2026-05-25 Anatomy Match 进入 Finding 输出与前端审查

本轮目标：上一阶段已经能为每个 finding 选择最佳 anatomy candidate，本轮把匹配依据暴露到结构化输出和前端，方便人工确认病灶是否归一化到正确解剖区域。

修改文件：

- `scripts/no_mask_medsam2_segmentation_demo.py`
- `web/app.js`
- `tests/test_no_mask_medsam2_segmentation_demo.py`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

已完成：

- finding 的 `measurements` 现在保留：
  - `anatomy_match`
  - `anatomy_candidates_evaluated`
- 前端 finding 列表现在展示：
  - `matched_anatomy`
  - `overlap_anatomy_px`
  - `anatomy_selection_rule`
- 静态前端测试确认 bundle 渲染代码包含 `anatomy_match` 和 `overlap_anatomy_px`。

验收命令：

```bash
python -m unittest tests.test_no_mask_medsam2_segmentation_demo.NoMaskMedSAM2SegmentationDemoTest.test_demo_matches_each_finding_to_best_overlapping_anatomy_candidate -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_no_mask_medsam2_segmentation_demo tests.test_no_mask_skill_visual_pipeline_demo tests.test_no_mask_candidate_diagnosis_demo tests.test_mvp_flow tests.test_memory_manager tests.test_service_entrypoint tests.test_http_entrypoint -v
```

当前验证结果：

- anatomy match 结构化输出测试通过。
- 前端静态资产测试通过。
- `node --check web/app.js` 通过。
- no-mask、MVP、memory、service、HTTP/frontend 相关 64 个测试通过。

下一步：

- 继续把真实 FHN no-mask 演示重新跑一遍，检查真实 Gemini + MedSAM2 输出里是否能看到 `matched_anatomy`，并确认前端能展示该字段。

### 2026-05-25 真实 FHN no-mask 多征象演示核验

本轮目标：用真实 Gemini + MedSAM2 的 FHN no-mask 演示产物，确认 skill 驱动的多征象定位、MedSAM2 分割、anatomy matching、数值证据和诊断输入契约能串起来。

修改文件：

- `output/fake/fhn_auto_skill_visual_pipeline_anatomy_match_demo/README.md`
- `goalnew.md`

已完成：

- 已核验真实演示输出目录：
  - `output/fake/fhn_auto_skill_visual_pipeline_anatomy_match_demo/summary.json`
  - `output/fake/fhn_auto_skill_visual_pipeline_anatomy_match_demo/finding_segmentation/summary.json`
  - `output/fake/fhn_auto_skill_visual_pipeline_anatomy_match_demo/diagnosis/candidate_diagnosis_report.json`
- `visual_evidence_bundle.present_findings` 包含 5 个候选征象：
  - `sclerotic_band`
  - `sclerotic_band`
  - `cystic_change`
  - `cystic_change`
  - `collapse`
- 数值汇总：
  - `finding_count=5`
  - `total_area_px=6726`
- anatomy matching 已进入每个 finding 的 `measurements.anatomy_match`：
  - `sclerotic_band` 面积 `2136`，匹配 `femoral_head#0`，overlap `1425`
  - `sclerotic_band` 面积 `1653`，匹配 `femoral_head#1`，overlap `1357`
  - `cystic_change` 面积 `601`，匹配 `femoral_head#0`，overlap `601`
  - `cystic_change` 面积 `1078`，匹配 `femoral_head#1`，overlap `991`
  - `collapse` 面积 `1258`，匹配 `femoral_head#1`，overlap `806`
- candidate diagnosis report 的 `visual_input_contract.visual_evidence.findings` 保留全部 5 个 finding。
- 当前候选诊断倾向：
  - `疑似股骨头坏死影像表现，需 MRI 和影像科复核`
- 当前分期表达：
  - `X 光存在硬化带/囊性变/骨小梁异常等候选征象，同时存在塌陷候选征象；不能按塌陷阴性处理，需复核 ARCO II 与 ARCO III 边界。`
- 已新增输出目录 README，说明输入、流水线、关键产物、finding 数值和诊断 handoff。

验证命令：

```bash
python -m json.tool output/fake/fhn_auto_skill_visual_pipeline_anatomy_match_demo/summary.json >/tmp/fhn_anatomy_match_summary_check.json
python -m json.tool output/fake/fhn_auto_skill_visual_pipeline_anatomy_match_demo/finding_segmentation/summary.json >/tmp/fhn_anatomy_match_finding_check.json
python -m json.tool output/fake/fhn_auto_skill_visual_pipeline_anatomy_match_demo/diagnosis/candidate_diagnosis_report.json >/tmp/fhn_anatomy_match_diagnosis_check.json
python -m unittest tests.test_no_mask_medsam2_segmentation_demo tests.test_no_mask_skill_visual_pipeline_demo tests.test_no_mask_candidate_diagnosis_demo tests.test_mvp_flow tests.test_memory_manager tests.test_service_entrypoint tests.test_http_entrypoint -v
node --check web/app.js
```

当前验证结果：

- 真实 FHN no-mask 演示已经产出多 anatomy candidate、多 finding、anatomy matching、视觉证据 bundle 和候选诊断报告。
- 诊断输入契约已经保留全部多征象 finding，可供 Diagnosis Agent 做 evidence-grounded 推理。
- 三个真实产物 JSON 校验通过：
  - `summary.json`
  - `finding_segmentation/summary.json`
  - `diagnosis/candidate_diagnosis_report.json`
- `node --check web/app.js` 通过。
- no-mask、MVP、memory、service、HTTP/frontend 相关 64 个测试通过。

下一步：

- 把这条真实 FHN no-mask pipeline 接入标准 demo/API 演示入口，形成“上传普通医疗图像 -> 自动选 FHN skill -> VLM 给 MedSAM2 box prompt -> 输出病灶 overlay + 多征象数值 bundle -> Diagnosis Agent 报告”的可复现实例。

### 2026-05-25 FHN no-mask 接入 GaoDoctor/API/标准 Demo

本轮目标：把真实 FHN no-mask pipeline 从独立脚本接入主流程，让 API/service 和标准 demo 可以显式运行“上传普通医疗图像 -> FHN skill -> VLM box prompt -> MedSAM2 分割 -> 多征象数值 bundle -> Diagnosis Agent 报告”。

修改文件：

- `agents/gaodoctor_agent.py`
- `scripts/end_to_end_demo.py`
- `tests/test_mvp_flow.py`
- `tests/test_end_to_end_demo.py`
- `goalnew.md`

已完成：

- `GaoDoctorAgent` 新增可注入的 `no_mask_visual_pipeline_runner`。
- 当 `disease_key=femoral_head_necrosis` 且 `vision_mode=no_mask_skill` 时，高医生会调用 no-mask skill visual pipeline，而不是旧的 `VisionAgent.analyze_image()` 简化路径。
- no-mask pipeline 返回的 `visual_analysis_result` 会继续走现有 Diagnosis Agent、MemoryManager、evidence bundle 和 API/service 附加逻辑。
- 标准 demo suite 新增可选参数：
  - `include_fhn_no_mask=True`
  - `no_mask_visual_pipeline_runner=...`
- CLI 新增：

```bash
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask
```

- FHN no-mask demo 默认使用已有真实样例图：
  - `output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png`
  - 若该文件不存在，才回退到占位 X 光图。
- 单元测试使用 fake runner，不触发真实 API，但验证：
  - GaoDoctor 调用了 no-mask runner。
  - runner 收到原始 `patient_message`、`image_path`、`disease_key` 和 disease skill。
  - case memory 保存 `selected_vision_mode=no_mask_skill`。
  - API/service response 透出 `visual_evidence_bundle`。
  - 标准 demo 第三个病例包含 anatomy match。

真实运行结果：

- 已按 `docs/API_ROUTE_LOG.md` 确认当前 active route 为 DMX，模型为 `gemini-3.5-flash`。
- 已运行真实标准 demo：

```bash
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask
```

- 真实输出：
  - `output/fake/standard_demo_with_fhn_no_mask/standard_demo_summary.json`
  - `output/fake/standard_demo_with_fhn_no_mask/demo_summary.md`
  - `output/fake/standard_demo_with_fhn_no_mask/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_response.json`
  - `output/fake/standard_demo_with_fhn_no_mask/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_evidence_bundle.json`
  - `output/fake/standard_demo_with_fhn_no_mask/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_audit.json`
- 真实 FHN no-mask case：
  - `case_id=case_20260525_014915_107451`
  - `selected_skill=femoral_head_necrosis`
  - `selected_vision_mode=no_mask_skill`
  - `present_findings=['sclerotic_band', 'cystic_change', 'sclerotic_band', 'collapse']`
  - `finding_count=4`
  - `total_area_px=5266`
  - overlay：`output/fake/gaodoctor_fhn_no_mask/case_20260525_014915_107451/finding_segmentation/medsam2_1_sclerotic_band_overlay.png`
- 真实 API/service response 顶层已包含：
  - `visual_evidence_bundle`
  - `image_outputs`
  - `evidence_bundle`
  - `memory_audit`
  - `memory_replay`

验证命令：

```bash
python -m unittest tests.test_mvp_flow.MedScopeMvpFlowTest.test_gaodoctor_runs_fhn_no_mask_skill_pipeline_when_requested tests.test_end_to_end_demo.EndToEndDemoTest.test_standard_demo_suite_can_include_fhn_no_mask_multifinding_case -v
python -m unittest tests.test_end_to_end_demo tests.test_mvp_flow tests.test_service_entrypoint tests.test_http_entrypoint tests.test_no_mask_skill_visual_pipeline_demo tests.test_no_mask_medsam2_segmentation_demo tests.test_no_mask_candidate_diagnosis_demo -v
python -m py_compile agents/gaodoctor_agent.py scripts/end_to_end_demo.py
python -m scripts.end_to_end_demo --suite
python -m json.tool output/fake/standard_demo_with_fhn_no_mask/standard_demo_summary.json >/tmp/standard_demo_with_fhn_summary_check.json
python -m json.tool output/fake/standard_demo_with_fhn_no_mask/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_response.json >/tmp/fhn_no_mask_response_check.json
python -m json.tool output/fake/standard_demo_with_fhn_no_mask/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_evidence_bundle.json >/tmp/fhn_no_mask_evidence_check.json
python -m unittest discover -v
```

当前验证结果：

- 新增两个 RED 测试先按预期失败，随后实现后通过。
- 受影响范围 60 个测试通过。
- 默认标准 demo suite 仍能生成 2 个病例并通过。
- 真实 `--include-fhn-no-mask` demo 已成功生成 3 个病例，其中第三个病例完整跑通 VLM + MedSAM2 no-mask 视觉链路。
- 三个真实 demo JSON 产物校验通过。
- 全量 `python -m unittest discover -v`：243 个测试通过。

下一步：

- 把前端“一键标准样例”增加一个“FHN no-mask 多征象样例”按钮，让浏览器界面也能直接触发 `vision_mode=no_mask_skill`，并展示多征象 bundle、overlay、memory audit。

### 2026-05-25 前端 FHN no-mask 多征象样例入口

本轮目标：把刚接入 API/service 的 FHN no-mask 主线暴露到浏览器交互界面，让前端可以一键触发 `vision_mode=no_mask_skill`，并复用已有多征象 bundle、overlay、evidence bundle 和 memory audit 展示。

修改文件：

- `web/index.html`
- `web/app.js`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

已完成：

- 病例输入区新增按钮：
  - `FHN no-mask 多征象样例`
- 前端 state 新增：
  - `sampleDiseaseKey`
  - `sampleVisionMode`
- `buildCasePayload()` 会在样例需要时显式传：
  - `disease_key=femoral_head_necrosis`
  - `vision_mode=no_mask_skill`
- 新增 `loadFhnNoMaskSample()`：
  - 填入患者描述：`右髋疼痛，上传 X 光，请根据股骨头坏死 skill 自动圈出候选征象`
  - 使用图像：`output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png`
  - 填入症状：`髋关节疼痛`
  - 关闭 sample mask
- 新增 `runFhnNoMaskSample()`：
  - 调用 `/v1/medscope`
  - 成功后走已有 `renderPayload(...)`
  - 因此自动展示图像输出、多征象视觉证据、诊断报告、alignment plan、evidence bundle、memory audit 和 memory replay。
- 上传普通文件、胶质瘤样例、X 光证据不足样例和 reset 都会清理 sample-specific disease/vision mode，避免污染下一次提交。

验证命令：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_root_serves_interactive_frontend tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint tests.test_service_entrypoint tests.test_end_to_end_demo tests.test_mvp_flow -v
python -m unittest discover -v
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ | rg 'FHN no-mask|fhnNoMaskButton'
curl -s http://127.0.0.1:8000/static/app.js | rg 'runFhnNoMaskSample|no_mask_skill|femoral_head_necrosis'
```

当前验证结果：

- 新增前端 RED 测试先按预期失败，随后实现后通过。
- 前端静态入口和 JS allowlist 测试通过。
- `node --check web/app.js` 通过。
- HTTP / Service / End-to-end Demo / MVP flow 相关 49 个测试通过。
- 全量 `python -m unittest discover -v`：243 个测试通过。
- 已重启本地 HTTP server：`http://127.0.0.1:8000`。
- `GET /health` 返回 `{"status": "ok"}`。
- 前端 HTML 已包含 `FHN no-mask 多征象样例` / `fhnNoMaskButton`。
- 前端 JS 已包含 `runFhnNoMaskSample`、`no_mask_skill`、`femoral_head_necrosis`。

下一步：

- 重启本地 HTTP server，并用浏览器或 HTTP 静态入口确认前端页面已经包含 `FHN no-mask 多征象样例` 按钮。之后可以进一步做“前端点击该按钮的真实端到端人工验收”。

### 2026-05-25 前端 FHN no-mask HTTP 真实 Smoke

本轮目标：用前端按钮会提交的同款 payload 直接请求 `/v1/medscope`，验证浏览器入口背后的真实 HTTP 链路能跑通 FHN no-mask 多征象流程。

产出文件：

- `output/fake/frontend_fhn_no_mask_http_smoke/response.json`

请求 payload：

```json
{
  "patient_message": "右髋疼痛，上传 X 光，请根据股骨头坏死 skill 自动圈出候选征象",
  "image_path": "output/fake/fhn_multifinding_source/fhn_pelvis_xray_panel_b.png",
  "disease_key": "femoral_head_necrosis",
  "vision_mode": "no_mask_skill",
  "patient_info": {
    "symptoms": ["髋关节疼痛"]
  }
}
```

真实运行结果：

- `case_id=case_20260525_015527_055252`
- `intent=diagnosis`
- `analysis_status=partial_evidence`
- `selected_skill=femoral_head_necrosis`
- `selected_vision_mode=no_mask_skill`
- `present_findings=['sclerotic_band', 'collapse', 'sclerotic_band', 'collapse']`
- `numeric_evidence.finding_count=4`
- `numeric_evidence.total_area_px=6530`
- `memory_audit` 已返回。
- `memory_replay.steps=5`
- overlay：
  - `output/fake/gaodoctor_fhn_no_mask/case_20260525_015527_055252/finding_segmentation/medsam2_1_sclerotic_band_overlay.png`
- mask：
  - `output/fake/gaodoctor_fhn_no_mask/case_20260525_015527_055252/finding_segmentation/medsam2_1_sclerotic_band_mask.png`
- case memory：
  - `data/cases/case_20260525_015527_055252.json`
- memory audit path：
  - `output/fake/memory_audit/case_20260525_015527_055252_audit.json`

finding 摘要：

- `sclerotic_band`：面积 `1948`，`area_ratio_in_anatomy=0.958983`，匹配 `femoral_head#0`，overlap `1169`
- `collapse`：面积 `1948`，`area_ratio_in_anatomy=0.958983`，匹配 `femoral_head#0`，overlap `1169`
- `sclerotic_band`：面积 `1317`，`area_ratio_in_anatomy=0.871622`，匹配 `femoral_head#1`，overlap `1161`
- `collapse`：面积 `1317`，`area_ratio_in_anatomy=0.871622`，匹配 `femoral_head#1`，overlap `1161`

验证命令：

```bash
python -m json.tool output/fake/frontend_fhn_no_mask_http_smoke/response.json >/tmp/frontend_fhn_no_mask_http_response_check.json
curl -s -D /tmp/fhn_overlay_headers.txt -o /tmp/fhn_overlay_probe.png http://127.0.0.1:8000/output/fake/gaodoctor_fhn_no_mask/case_20260525_015527_055252/finding_segmentation/medsam2_1_sclerotic_band_overlay.png
```

当前验证结果：

- response JSON 校验通过。
- response 顶层包含前端需要的 `visual_evidence_bundle`、`image_outputs`、`memory_audit`、`memory_replay`。
- overlay 和 mask 文件真实存在。
- `/output/...overlay.png` GET 返回 `200 OK`、`Content-Type: image/png`、`Content-Length: 47095`。
- 注：标准库 HTTP server 不支持 `HEAD`，`curl -I` 会返回 `501 Unsupported method ('HEAD')`；浏览器图片加载使用 GET，不受影响。

下一步：

- 进入前端交互细节优化：当 FHN no-mask 真实执行时间较长时，在病例分析按钮上增加 Thinking/运行中状态和防重复提交，和 QA 追问的防重复机制保持一致。

### 2026-05-25 病例分析 Thinking 与防重复提交

本轮目标：FHN no-mask 真实执行时间较长，前端病例分析期间必须显示运行中状态，并禁止重复点击主提交和三个样例按钮，避免重复触发 VLM/MedSAM2 请求。

修改文件：

- `web/app.js`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

已完成：

- 前端 state 新增 `casePending`。
- 新增 `setCasePending(...)`：
  - 禁用/恢复主提交按钮。
  - 禁用/恢复胶质瘤标准样例、X 光证据不足样例、FHN no-mask 样例按钮。
  - 运行时按钮显示 `Thinking...`。
- 新增 `showCaseThinking(...)`：
  - 图像输出区显示 `Thinking...`
  - 报告区显示 `Thinking...`
  - evidence bundle 区显示 `Thinking...`
  - memory audit 区显示 `Thinking...`
- 主病例提交、胶质瘤样例、X 光证据不足样例、FHN no-mask 样例都接入同一个 `casePending` gate。
- 如果已有病例请求还在运行，再次点击会提示：
  - `上一个病例仍在分析中`
- reset 会同时清理病例 pending 和 QA pending。

验证命令：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint tests.test_service_entrypoint tests.test_end_to_end_demo tests.test_mvp_flow -v
python -m unittest discover -v
```

当前验证结果：

- 新增前端 RED 测试先按预期失败，随后实现后通过。
- `node --check web/app.js` 通过。
- HTTP / Service / End-to-end Demo / MVP flow 相关 49 个测试通过。
- 全量 `python -m unittest discover -v`：243 个测试通过。

下一步：

- 重启本地 HTTP server，让前端 Thinking/防重复提交逻辑生效；然后做一次静态入口确认。

执行结果：

- 已重启本地 HTTP server：`http://127.0.0.1:8000`
- `GET /health` 返回 `{"status": "ok"}`。
- `/static/app.js` 已确认包含：
  - `casePending`
  - `setCasePending`
  - `showCaseThinking`
  - `上一个病例仍在分析中`

下一步：

- 前端这一轮可阶段性停住。下一步建议回到视觉 Agent 质量问题：对 FHN no-mask 输出增加 “VLM prompt 结果审计 / prompt box 与 MedSAM2 mask 对齐审计”，因为真实 smoke 中 `collapse` 和 `sclerotic_band` 有共享 mask 面积的现象，需要在诊断前标出可能的重复/重叠候选。

### 2026-05-25 视觉 Agent 多征象重叠质量控制

本轮目标：一张医疗图像中允许存在多个候选病灶/征象，但如果多个 skill finding 最终由 MedSAM2 分割成高度重叠或同一块 mask，不能把它们当作多个独立强证据传给诊断 Agent。

修改文件：

- `scripts/no_mask_medsam2_segmentation_demo.py`
- `scripts/no_mask_candidate_diagnosis_demo.py`
- `scripts/no_mask_skill_visual_pipeline_demo.py`
- `agents/gaodoctor_agent.py`
- `tests/test_no_mask_medsam2_segmentation_demo.py`
- `tests/test_no_mask_skill_visual_pipeline_demo.py`
- `goalnew.md`

已完成：

- 在 no-mask MedSAM2 分割汇总层新增 finding mask IoU 审计。
- 当后续 finding 与前序 finding 的 mask IoU >= 0.85：
  - 后续 finding 标记 `independent_evidence=false`。
  - 后续 finding 增加 `overlap_qc`，记录重叠对象、重叠 target、mask_iou、阈值和解释。
  - summary 顶层增加 `quality_warnings`，code 为 `overlapping_candidate_findings`。
  - 对应 finding 的 `segmentation_ref.quality.warnings` 增加 `overlaps with another finding mask`。
- 同一 target 出现多个候选区域时，`finding_id` 现在会带 region 序号，避免左右侧或多灶同名 finding 发生 ID 冲突。
- `build_candidate_visual_analysis_result(...)` 将 `quality_warnings` 透传到 `visual_evidence`。
- `visual_evidence_bundle` 顶层新增 `quality_warnings`。
- `numeric_evidence` 新增：
  - `finding_count`
  - `independent_finding_count`
  - `non_independent_finding_count`
  - 原有 `region_count`、`total_area_px`、面积比例字段继续保留。
- GaoDoctor API 返回的 bundle 同步包含上述质量字段。

当前意义：

- 视觉 Agent 可以对一张图输出多个 finding/多个 region。
- 每个 finding 仍保留文本依据、mask/overlay、bbox、centroid、面积、解剖归一化比例等结构化信息。
- 如果两个病情标签实际来自同一块分割区域，诊断 Agent 可以看到它们不是独立证据，后续不能把它们简单相加为更强诊断依据。

验证命令：

```bash
python -m unittest tests.test_no_mask_medsam2_segmentation_demo -v
python -m unittest tests.test_no_mask_skill_visual_pipeline_demo -v
python -m unittest tests.test_no_mask_candidate_diagnosis_demo -v
python -m unittest tests.test_mvp_flow tests.test_service_entrypoint -v
python -m unittest discover -v
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask_qc
```

当前验证结果：

- no-mask MedSAM2 分割质量控制测试通过。
- no-mask skill visual pipeline 质量 warning 透传测试通过。
- no-mask candidate diagnosis demo 回归通过。
- MVP flow 与 service entrypoint 回归通过。
- 全量 `python -m unittest discover -v`：246 个测试通过。
- 真实 FHN no-mask 标准 demo 已跑通，输出目录：
  - `output/fake/standard_demo_with_fhn_no_mask_qc/`
  - FHN evidence bundle：`output/fake/standard_demo_with_fhn_no_mask_qc/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_evidence_bundle.json`
- 真实 FHN evidence bundle 中：
  - `finding_count=4`
  - `independent_finding_count=2`
  - `non_independent_finding_count=2`
  - finding IDs 为 `finding_1_sclerotic_band`、`finding_2_sclerotic_band`、`finding_3_cystic_change`、`finding_4_cystic_change`
  - `quality_warnings` 标出 `cystic_change` 与 `sclerotic_band` 的 mask_iou=1.0，因此囊性变候选不应当按独立强证据重复计数。
- 已重启本地 HTTP server：`http://127.0.0.1:8000`
- `GET /health` 返回 `{"status": "ok"}`。

下一步：

- 下一阶段建议让诊断 Agent 显式消费 `independent_evidence=false` 与 `quality_warnings`：报告中应把重叠候选写成“同区域候选征象，需复核”，而不是把它们当作相互独立的多个诊断依据。

### 2026-05-25 诊断 Agent 消费非独立视觉证据

本轮目标：视觉 Agent 已能标记 `independent_evidence=false` 和 `quality_warnings`，诊断 Agent 必须真正消费这些字段，不能只在 evidence bundle 里展示。

修改文件：

- `agents/diagnosis_agent.py`
- `prompts/diagnosis_agent_prompt.md`
- `tests/test_diagnosis_llm_workflow.py`
- `goalnew.md`

已完成：

- 规则诊断路径中，`independent_evidence=false` 的 finding 不再进入独立 X 光候选征象列表。
- 诊断报告的 `影像依据` 会增加：
  - `同区域候选征象：囊性变 与 硬化带 的分割 mask 高度重叠（mask IoU 1.0），不作为独立诊断依据，需影像科或更合适的专病模型复核。`
- 诊断报告的 `不确定性说明` 同步增加同区域非独立证据说明。
- 分期文本改为使用实际独立候选征象列表，例如：
  - `X 光存在硬化带等独立候选征象且未见塌陷...`
  - 不再模板化写成 `硬化带/囊性变/骨小梁异常`。
- LLM 诊断路径新增质量验证：
  - 如果视觉证据存在重叠/非独立 finding，而 LLM 报告没有承认同区域重叠或非独立性，则拒绝该 LLM 报告并 fallback。
  - 如果 LLM 把重叠 finding 写成“独立征象”，会触发 fallback。
- `prompts/diagnosis_agent_prompt.md` 增加规则：
  - `independent_evidence=false` 或 `overlapping_candidate_findings` 只能写成同区域候选/非独立候选证据/需复核，不能重复计数为独立诊断依据。

验证命令：

```bash
python -m unittest tests.test_diagnosis_llm_workflow -v
python -m unittest tests.test_mvp_flow tests.test_service_entrypoint tests.test_end_to_end_demo -v
python -m unittest discover -v
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask_qc
```

当前验证结果：

- `tests.test_diagnosis_llm_workflow`：19 个测试通过。
- MVP / Service / End-to-end demo 相关 32 个测试通过。
- 全量 `python -m unittest discover -v`：248 个测试通过。
- 真实 FHN no-mask demo 已重新生成：
  - `output/fake/standard_demo_with_fhn_no_mask_qc/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_response.json`
- 真实输出关键字段：
  - `finding_count=4`
  - `independent_finding_count=2`
  - `non_independent_finding_count=2`
  - `quality_warnings` 中两个 `cystic_change` 均与对应 `sclerotic_band` 的 `mask_iou=1.0`
  - 报告 `影像依据` 包含 `X 光候选征象：硬化带`
  - 报告 `影像依据` 和 `不确定性说明` 均包含 `同区域候选征象...不作为独立诊断依据`
  - 报告 `分期判断` 为 `X 光存在硬化带等独立候选征象且未见塌陷...`

下一步：

- 继续完善视觉 Agent 的多病灶表达：把左右侧/解剖区域信息从 anatomy match 和 bbox 推断出来，避免报告只写两个同名“硬化带”，而是能表达为“左侧/右侧候选区域”。这属于视觉证据结构化表达优化，不需要大重构。

### 2026-05-25 多候选区域侧别表达

本轮目标：一张图内存在多个同名 finding 时，不能在诊断报告中压缩成一个同名征象；至少要保留图像左侧/右侧这类候选区域信息，避免“两个硬化带”在报告中变成一个“硬化带”。

修改文件：

- `scripts/no_mask_medsam2_segmentation_demo.py`
- `agents/diagnosis_agent.py`
- `tests/test_no_mask_medsam2_segmentation_demo.py`
- `tests/test_diagnosis_llm_workflow.py`
- `goalnew.md`

已完成：

- no-mask MedSAM2 finding 现在会从候选区域 centroid / bbox 与 `image_size.width` 推断图像侧别：
  - `image_left`
  - `image_right`
  - 若 anatomy name 明确包含 left/right/左/右，则优先用解剖侧别 `left` / `right`
- finding 顶层 measurements 增加 `laterality`。
- region 级别也写入 `laterality`。
- 诊断 Agent 展示 finding 时会把侧别前缀合入显示名：
  - `图像左侧硬化带`
  - `图像右侧硬化带`
  - `图像左侧囊性变`
  - `图像右侧囊性变`
- 重叠非独立证据说明现在也保留侧别：
  - `图像左侧囊性变 与 图像左侧硬化带...`
  - `图像右侧囊性变 与 图像右侧硬化带...`
- 分期判断现在使用保留侧别的独立候选征象：
  - `X 光存在图像左侧硬化带、图像右侧硬化带等独立候选征象且未见塌陷...`

验证命令：

```bash
python -m unittest tests.test_no_mask_medsam2_segmentation_demo tests.test_no_mask_skill_visual_pipeline_demo -v
python -m unittest tests.test_diagnosis_llm_workflow -v
python -m unittest tests.test_mvp_flow tests.test_service_entrypoint tests.test_end_to_end_demo -v
python -m unittest discover -v
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask_qc
```

当前验证结果：

- no-mask segmentation / no-mask skill pipeline：11 个测试通过。
- diagnosis LLM workflow：20 个测试通过。
- MVP / Service / End-to-end demo：32 个测试通过。
- 全量 `python -m unittest discover -v`：250 个测试通过。
- 真实 FHN no-mask demo 已重新生成：
  - `output/fake/standard_demo_with_fhn_no_mask_qc/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_response.json`
- 真实输出关键字段：
  - finding laterality：
    - `finding_1_sclerotic_band`: `image_left`
    - `finding_2_sclerotic_band`: `image_right`
    - `finding_3_cystic_change`: `image_left`
    - `finding_4_cystic_change`: `image_right`
  - 报告 `影像依据` 包含：
    - `X 光候选征象：图像左侧硬化带、图像右侧硬化带`
    - `同区域候选征象：图像左侧囊性变 与 图像左侧硬化带...不作为独立诊断依据`
    - `同区域候选征象：图像右侧囊性变 与 图像右侧硬化带...不作为独立诊断依据`
  - 报告 `分期判断` 为：
    - `X 光存在图像左侧硬化带、图像右侧硬化带等独立候选征象且未见塌陷，倾向 ARCO II 可能；不能排除更早期或更复杂病变。`

注意：

- 当前 `image_left/image_right` 是图像坐标侧别，不等同于患者解剖左/右；报告中故意写“图像左侧/图像右侧”，避免误导。后续如果要变成“患者左侧/右侧”，需要 DICOM orientation 或可靠的影像标记支持。

下一步：

- 继续完善视觉证据质量：给 VLM bbox 与 MedSAM2 mask 的一致性增加 `box_mask_alignment` 数值，例如 mask 是否大幅跑出 bbox、mask 面积是否异常小/大，进一步减少错误框导致的误判。

### 2026-05-25 VLM bbox 与 MedSAM2 mask 对齐质控

本轮目标：视觉 Agent 不能只返回 mask 面积，还要检查 Gemini/VLM 给出的候选 bbox 和 MedSAM2 输出 mask 是否对齐；如果 mask 明显跑出 bbox，该 finding 不能作为诊断 Agent 的可靠证据。

修改文件：

- `scripts/no_mask_medsam2_segmentation_demo.py`
- `scripts/no_mask_skill_visual_pipeline_demo.py`
- `agents/gaodoctor_agent.py`
- `tests/test_no_mask_medsam2_segmentation_demo.py`
- `tests/test_no_mask_skill_visual_pipeline_demo.py`
- `goalnew.md`

已完成：

- no-mask MedSAM2 分割结果新增 `box_mask_alignment`：
  - `prompt_bbox`
  - `mask_bbox`
  - `mask_area_inside_prompt_px`
  - `mask_area_px`
  - `mask_area_inside_prompt_ratio`
  - `mask_bbox_iou`
  - `status`: `aligned` / `partial_alignment` / `low_alignment` / `empty_mask` / `not_assessed`
- 当 `mask_area_inside_prompt_ratio < 0.5` 时，标记为 `low_alignment`。
- `low_alignment` finding 会被降级：
  - finding `diagnosis_usable=false`
  - segmentation result `diagnosis_usable=false`
  - segmentation result `status=low_quality`
  - `quality_warnings` 增加 `box_mask_misalignment`
- `partial_alignment` 保留为候选证据，但增加 `box_mask_partial_alignment` warning，提示需要复核。
- overlap QC 不再把不可用于诊断的 finding 计入独立/非独立重叠证据判断。
- evidence bundle 的 `numeric_evidence` 新增：
  - `diagnosis_usable_finding_count`
  - `diagnosis_unusable_finding_count`
  - `total_diagnosis_usable_area_px`
- `independent_finding_count` / `non_independent_finding_count` 现在只统计 `diagnosis_usable=true` 的 finding，避免错位 mask 被误计为独立视觉证据。

验证命令：

```bash
python -m unittest tests.test_no_mask_medsam2_segmentation_demo.NoMaskMedSAM2SegmentationDemoTest.test_demo_marks_mask_outside_prompt_box_as_not_diagnosis_usable -v
python -m unittest tests.test_no_mask_skill_visual_pipeline_demo.NoMaskSkillVisualPipelineDemoTest.test_pipeline_excludes_misaligned_masks_from_present_findings -v
python -m unittest tests.test_no_mask_medsam2_segmentation_demo tests.test_no_mask_skill_visual_pipeline_demo tests.test_diagnosis_llm_workflow -v
python -m unittest discover -v
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask_qc
```

当前验证结果：

- 单测红绿闭环已确认：
  - mask 完全跑出 VLM bbox 时，先因缺少 `box_mask_alignment` 失败。
  - 实现后该测试通过。
- no-mask segmentation / no-mask skill pipeline / diagnosis LLM workflow：33 个测试通过。
- 全量 `python -m unittest discover -v`：252 个测试通过。
- 标准端到端 demo 已重新生成：
  - `output/fake/standard_demo_with_fhn_no_mask_qc/standard_demo_summary.json`
  - `output/fake/standard_demo_with_fhn_no_mask_qc/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_response.json`
- 真实 FHN no-mask demo 输出检查：
  - `finding_count=4`
  - `alignment_statuses=["aligned", "aligned", "aligned", "aligned"]`
  - `mask_area_inside_prompt_ratio=[0.91116, 0.997222, 0.91116, 0.997222]`
  - `diagnosis_usable=[true, true, true, true]`
  - `numeric_evidence.diagnosis_usable_finding_count=4`
  - `numeric_evidence.diagnosis_unusable_finding_count=0`
  - `numeric_evidence.total_diagnosis_usable_area_px=4884`

下一步：

- 下一阶段建议做“视觉证据文本化增强”：把 `box_mask_alignment`、解剖归一化面积、侧别、重叠非独立证据统一整理成 diagnosis agent 更容易消费的 `structured_visual_facts`，减少诊断 Agent 从原始嵌套字段里拼解释的复杂度。

### 2026-05-25 视觉证据 structured_visual_facts 收敛项

本轮目标：把视觉 Agent 的复杂嵌套输出压平成诊断 Agent 可直接消费的结构化事实列表，作为视觉主线第一版收敛点。后续诊断 Agent 不必从 `findings -> regions -> measurements -> overlap_qc -> box_mask_alignment` 里自行拼接医学事实。

修改文件：

- `tools/structured_visual_fact_builder.py`
- `contracts/medical_contracts.py`
- `scripts/no_mask_candidate_diagnosis_demo.py`
- `scripts/no_mask_skill_visual_pipeline_demo.py`
- `agents/gaodoctor_agent.py`
- `agents/diagnosis_agent.py`
- `tests/test_contracts.py`
- `tests/test_no_mask_candidate_diagnosis_demo.py`
- `tests/test_no_mask_skill_visual_pipeline_demo.py`
- `tests/test_diagnosis_llm_workflow.py`
- `tests/test_mvp_flow.py`
- `goalnew.md`

已完成：

- 新增共享 builder：`tools/structured_visual_fact_builder.py`。
- no-mask visual pipeline 的 `visual_evidence_bundle` 顶层新增 `structured_visual_facts`。
- no-mask candidate visual result 的 `visual_evidence` 内新增 `structured_visual_facts`。
- 高医生 Agent 持久化到 memory/API 的 `visual_evidence_bundle` 也新增 `structured_visual_facts`。
- `VisualEvidence` / `DiagnosisVisualInput` 契约正式保留 `structured_visual_facts`，规范化时不再丢字段。
- 诊断 Agent 现在优先消费 `structured_visual_facts`，只有 facts 不存在时才回退到原始 `findings`。
- 每条 fact 压平以下信息：
  - `finding_id`
  - `target`
  - `display_name`
  - `status`
  - `laterality`
  - `anatomical_zone`
  - `diagnosis_usable`
  - `independent_evidence`
  - `non_independent_reason`
  - `overlap_with_finding_id`
  - `area_px`
  - `area_ratio_in_image`
  - `area_ratio_in_anatomy`
  - `bbox`
  - `centroid`
  - `alignment_status`
  - `mask_area_inside_prompt_ratio`
  - `mask_bbox_iou`
  - `quality_level`
  - `summary_text`

验证命令：

```bash
python -m unittest tests.test_no_mask_skill_visual_pipeline_demo.NoMaskSkillVisualPipelineDemoTest.test_pipeline_uses_skill_anatomy_reference_before_finding_segmentation -v
python -m unittest tests.test_mvp_flow.MedScopeMvpFlowTest.test_gaodoctor_persists_multifinding_visual_evidence_bundle_to_memory -v
python -m unittest tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_can_use_structured_visual_facts_without_raw_findings -v
python -m unittest tests.test_no_mask_candidate_diagnosis_demo.NoMaskCandidateDiagnosisDemoTest.test_visual_result_reuses_findings_from_segmentation_summary -v
python -m unittest tests.test_contracts tests.test_no_mask_candidate_diagnosis_demo tests.test_no_mask_skill_visual_pipeline_demo tests.test_diagnosis_llm_workflow tests.test_mvp_flow -v
python -m unittest discover -v
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask_qc
```

当前验证结果：

- 目标回归测试：59 个测试通过。
- 全量 `python -m unittest discover -v`：253 个测试通过。
- 标准端到端 demo 已重新生成：
  - `output/fake/standard_demo_with_fhn_no_mask_qc/standard_demo_summary.json`
  - `output/fake/standard_demo_with_fhn_no_mask_qc/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_response.json`
- 真实 FHN no-mask response 检查：
  - `structured_visual_facts` 数量：4
  - targets：`sclerotic_band`, `sclerotic_band`, `cystic_change`, `cystic_change`
  - laterality：`image_left`, `image_right`, `image_left`, `image_right`
  - diagnosis_usable：全部 `true`
  - independent_evidence：前两个硬化带为 `true`，两个囊性变为 `false`
  - alignment_status：全部 `aligned`

阶段收敛判断：

- 视觉 Agent 第一版主线到这里收敛：skill 约束定位、MedSAM2 分割、mask/overlay、面积与解剖归一化、侧别、多 finding、重叠非独立证据、box-mask 对齐质控、structured facts、memory/API 持久化均已打通。
- 后续暂不继续扩视觉 Agent 架构，不换模型、不做大重构；只保留 bug 修和必要的字段稳定化。

下一步：

- 转入诊断 Agent 消费优化：让诊断报告和 follow-up QA 优先引用 `structured_visual_facts`，并把“哪些事实被用于结论、哪些被排除”写入 reasoning memory audit。

### 2026-05-25 诊断 Agent visual_fact_usage 审计

本轮目标：诊断 Agent 不仅要消费 `structured_visual_facts`，还要把“哪些视觉事实进入诊断结论、哪些被排除、为什么排除”写进报告、reasoning memory 和 memory audit，形成可追溯闭环。

修改文件：

- `agents/diagnosis_agent.py`
- `agents/gaodoctor_agent.py`
- `memory/memory_manager.py`
- `tests/test_diagnosis_llm_workflow.py`
- `tests/test_mvp_flow.py`
- `goalnew.md`

已完成：

- 诊断报告新增：
  - `visual_fact_usage`
  - `used_visual_facts`
  - `excluded_visual_facts`
- `visual_fact_usage` 结构：
  - `used`
  - `excluded`
  - `used_count`
  - `excluded_count`
- exclusion reason 目前支持：
  - `not_diagnosis_usable`
  - `non_independent_evidence`
  - `not_candidate_present`
  - `missing_target`
- GaoDoctor 保存 reasoning memory 时写入：
  - `visual_fact_usage`
  - `used_visual_facts`
  - `excluded_visual_facts`
- MemoryManager 的 evidence bundle 和 audit summary 暴露同一份使用/排除审计。
- `agent_io_summary.DiagnosisDoctorAgent` 中也记录 `visual_fact_usage`，便于前端或审计页直接查看诊断 Agent 的输入使用情况。

验证命令：

```bash
python -m unittest tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_records_used_and_excluded_structured_visual_facts -v
python -m unittest tests.test_mvp_flow.MedScopeMvpFlowTest.test_gaodoctor_persists_visual_fact_usage_to_reasoning_memory_and_audit -v
python -m unittest tests.test_diagnosis_llm_workflow tests.test_mvp_flow tests.test_memory_manager tests.test_service_entrypoint -v
python -m unittest discover -v
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask_qc
```

当前验证结果：

- 目标回归：60 个测试通过。
- 全量 `python -m unittest discover -v`：255 个测试通过。
- 标准端到端 demo 已重新生成：
  - `output/fake/standard_demo_with_fhn_no_mask_qc/standard_demo_summary.json`
  - `output/fake/standard_demo_with_fhn_no_mask_qc/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_response.json`
  - `output/fake/standard_demo_with_fhn_no_mask_qc/cases/fhn_no_mask_multifinding/artifacts/fhn_no_mask_multifinding_audit.json`
- 真实 FHN no-mask response / audit 检查：
  - `report.visual_fact_usage.used_count=2`
  - `report.visual_fact_usage.excluded_count=2`
  - used facts：
    - `finding_1_sclerotic_band`
    - `finding_2_sclerotic_band`
  - excluded facts：
    - `finding_3_cystic_change`
    - `finding_4_cystic_change`
  - excluded reasons：
    - `non_independent_evidence`
    - `non_independent_evidence`
  - audit 中 `visual_fact_usage` 与 `agent_io_summary.DiagnosisDoctorAgent.visual_fact_usage` 均已记录同样信息。

下一步：

- follow-up QA 消费优化：追问回答时优先读取 `reasoning_evidence.visual_fact_usage`，回答“为什么用了某个征象/为什么排除了某个征象/哪些证据支撑结论”时必须受 used/excluded facts 约束。

### 2026-05-25 follow-up QA 受 visual_fact_usage 约束

本轮目标：让追问 QA 不只是读取最终报告文本，而是显式读取 `reasoning_evidence.visual_fact_usage` / `visual_fact_usage`，回答“为什么用了某个视觉证据、为什么排除了某个视觉证据”时必须遵守诊断 Agent 已审计过的 used/excluded facts。

修改文件：

- `agents/gaodoctor_agent.py`
- `tests/test_llm_routing.py`
- `goalnew.md`

已完成：

- 高医生 follow-up QA 的 LLM prompt 增加 `visual_fact_usage` 安全规则：
  - `used` 中的事实可以作为可用视觉证据解释。
  - `excluded` 中的事实不能重新当成独立诊断依据。
  - 如果患者问到被排除事实，必须说明 `exclusion_reason`。
- follow-up QA 的 LLM 输出校验新增视觉证据使用约束：
  - 如果回答把 excluded fact 表述为“独立诊断依据”“可以一起支持判断”等，会拒绝 LLM 输出并走受约束 fallback。
  - fallback 会解释该视觉事实为何被排除，例如 `non_independent_evidence`。
- 模板 QA 回答现在会列出：
  - 本次用于诊断的视觉事实。
  - 本次排除的视觉事实及排除原因。

验证命令：

```bash
python -m unittest tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_rejects_follow_up_llm_answer_that_uses_excluded_visual_fact tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_follow_up_template_explains_excluded_visual_fact_reason -v
python -m unittest tests.test_llm_routing tests.test_mvp_flow tests.test_memory_manager tests.test_service_entrypoint -v
python -m unittest discover -v
python -m api.http_server --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health
```

当前验证结果：

- 新增 QA 约束红绿闭环已确认：
  - 先观察到 LLM 把 excluded 囊性变重新说成独立诊断依据时测试失败。
  - 实现校验和 fallback 后目标测试通过。
- 相关回归：50 个测试通过。
- 全量 `python -m unittest discover -v`：257 个测试通过。
- HTTP API 已用最新代码重启，`/health` 返回 `{"status":"ok"}`。
- 通过 `/v1/medscope` 新建默认病例 `case_20260525_111737_326632`，并验证：
  - `/v1/memory/cases/{case_id}/evidence-bundle` 可返回 `patient_context`、`image_evidence`、`skill_evidence`、`reasoning_evidence`。
  - `/v1/memory/cases/{case_id}/audit` 可返回四类 memory completeness 和 `qa_safety`。

阶段收敛判断：

- 视觉 Agent 到诊断 Agent 再到 follow-up QA 的证据约束链条已闭环：
  - 视觉 Agent 输出 `structured_visual_facts`。
  - 诊断 Agent 生成 `visual_fact_usage`。
  - Memory audit 记录 used/excluded facts。
  - follow-up QA 受同一份 usage audit 约束。
- 这一部分按 MVP 标准可以收敛；后续不继续扩大视觉模型能力，只做演示稳定化、前端展示和必要 bug 修。

下一步：

- 标准端到端演示稳定化：确认 HTTP API 当前进程加载的是最新代码，必要时重启；再用现有 demo output 检查前端/API 需要的 `response`、`evidence_bundle`、`image_outputs`、`memory_audit` 字段是否齐全。

风险/待确认：

- 当前标准 demo 产物默认在 `output/fake/standard_demo_with_fhn_no_mask_qc/`，但 HTTP memory 接口默认读取 `MemoryManager(base_dir="data")` 下的 `data/cases/`。演示时需要明确两种路径：
  - 前端走 HTTP API 实时新建病例，则 case 可从 `/v1/memory/cases/{case_id}/...` 查询。
  - 前端展示离线标准 demo，则应读取 demo output 产物，不应拿 demo `case_id` 去默认 memory endpoint 查询。
- 是否把默认 case memory 从 `data/cases/` 迁移到 `output/fake/memory/cases/`，需要单独作为下一步小阶段处理，避免影响已有病例查询和测试。

### 2026-05-25 标准 demo HTTP 只读入口

本轮目标：解决“标准 demo 产物在 `output/fake/...`，但 HTTP memory endpoint 默认读 `data/cases/`”导致的演示路径不一致问题。当前不迁移默认 memory，也不重构目录，只给离线标准 demo 增加只读 HTTP 入口，让前端可以稳定展示已生成的 response / evidence bundle / audit。

修改文件：

- `api/http_server.py`
- `web/app.js`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

已完成：

- 新增只读 demo HTTP 路由：
  - `GET /v1/demo/standard`
  - `GET /v1/demo/standard/cases/{case_slug}/response`
  - `GET /v1/demo/standard/cases/{case_slug}/evidence-bundle`
  - `GET /v1/demo/standard/cases/{case_slug}/audit`
- demo route 只读取 `output/fake/standard_demo_with_fhn_no_mask_qc/` 下的固定 JSON artifact。
- case slug 只允许 `[A-Za-z0-9_-]+`，未知 artifact 和路径逃逸返回 404。
- 前端三个样例按钮现在优先读取预生成标准 demo response：
  - `glioma_ground_truth`
  - `xray_insufficient_evidence`
  - `fhn_no_mask_multifinding`
- 如果预生成 demo 不存在，前端会回退到实时 `/v1/medscope` 分析，保留原交互能力。

验证命令：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_demo_summary_and_case_artifacts_are_served_from_output_fake tests.test_http_entrypoint.HttpEntrypointTest.test_demo_artifact_route_rejects_unknown_or_unsafe_case_slug -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_http_entrypoint.HttpEntrypointTest.test_demo_summary_and_case_artifacts_are_served_from_output_fake tests.test_http_entrypoint.HttpEntrypointTest.test_demo_artifact_route_rejects_unknown_or_unsafe_case_slug -v
python -m unittest tests.test_http_entrypoint tests.test_end_to_end_demo tests.test_service_entrypoint -v
python -m unittest discover -v
python -m api.http_server --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/v1/demo/standard
curl -s http://127.0.0.1:8000/v1/demo/standard/cases/fhn_no_mask_multifinding/response
```

当前验证结果：

- 新增 demo route 红绿闭环已确认：
  - 先因缺少 `dispatch_demo_request` 失败。
  - 实现只读 demo route 后目标测试通过。
- HTTP / end-to-end demo / service 相关回归：39 个测试通过。
- 全量 `python -m unittest discover -v`：259 个测试通过。
- HTTP API 已用最新代码重启，`/health` 返回 `{"status":"ok"}`。
- `GET /v1/demo/standard` 返回：
  - `demo_name=medscope_standard_demo_suite`
  - `case_count=3`
  - `demo_output_dir=output/fake/standard_demo_with_fhn_no_mask_qc`
- `GET /v1/demo/standard/cases/fhn_no_mask_multifinding/response` 返回：
  - `has_image_outputs=true`
  - `structured_visual_fact_count=4`
  - `report.visual_fact_usage.used_count=2`
  - `report.visual_fact_usage.excluded_count=2`
  - `has_memory_audit=true`

阶段收敛判断：

- 标准端到端展示路径现在分成两条，边界清楚：
  - 实时病例：`/v1/medscope` -> `data/cases/` -> `/v1/memory/cases/{case_id}/...`
  - 离线演示：`/v1/demo/standard...` -> `output/fake/standard_demo_with_fhn_no_mask_qc/...`
- 这解决了“demo case_id 无法从默认 memory endpoint 查到”的演示歧义，不需要现在做目录迁移或大重构。

下一步：

- 建议进入前端展示小收敛：把 `visual_fact_usage.used/excluded` 单独渲染成“诊断采用证据 / 排除证据”面板，而不是只埋在 evidence/audit JSON 结构里，方便你现场解释为什么某个病灶被采用或被排除。

### 2026-05-25 前端 visual_fact_usage 展示收敛

本轮目标：把 `visual_fact_usage.used/excluded` 从 JSON 审计字段提升为前端可直接解释的面板，让演示时能清楚说明“哪些视觉事实被诊断 Agent 采用，哪些被排除，为什么排除”。

修改文件：

- `web/app.js`
- `web/app.css`
- `tests/test_http_entrypoint.py`
- `goalnew.md`

已完成：

- 新增前端渲染函数：
  - `getVisualFactUsage(payload)`
  - `renderVisualFactUsage(payload)`
  - `renderVisualFactList(facts, kind)`
- `visual_fact_usage` 的读取优先级：
  - `report.visual_fact_usage`
  - `memory_audit.visual_fact_usage`
  - `evidence_bundle.reasoning_evidence.visual_fact_usage`
- Evidence Bundle 面板新增“视觉证据使用审计”区块。
- Memory Audit 面板也新增同一份“视觉证据使用审计”区块。
- 前端明确展示：
  - `used_count`
  - `excluded_count`
  - “诊断采用证据”
  - “排除证据”
  - 每条 fact 的 `finding_id`、`target`、`status`、`exclusion_reason`、面积、对齐状态、是否独立证据等。
- 样式上用绿色左边框表示 adopted/used，用黄色左边框表示 excluded，移动端自动单列。

验证命令：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
python -m unittest tests.test_http_entrypoint tests.test_end_to_end_demo tests.test_service_entrypoint -v
python -m unittest discover -v
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/static/app.js | rg 'renderVisualFactUsage|诊断采用证据|排除证据|visual_fact_usage'
curl -s http://127.0.0.1:8000/v1/demo/standard/cases/fhn_no_mask_multifinding/response
```

当前验证结果：

- 前端静态测试红绿闭环已确认：
  - 先因缺少 `renderVisualFactUsage` 失败。
  - 实现后目标测试通过。
- HTTP / end-to-end demo / service 相关回归：39 个测试通过。
- 全量 `python -m unittest discover -v`：259 个测试通过。
- HTTP API 当前 `/health` 返回 `{"status":"ok"}`。
- 浏览器可获取的 `/static/app.js` 已包含：
  - `renderVisualFactUsage`
  - `诊断采用证据`
  - `排除证据`
  - `visual_fact_usage`
- FHN no-mask demo response 当前：
  - `used_count=2`
  - `excluded_count=2`
  - adopted labels：`硬化带`, `硬化带`
  - excluded labels：`囊性变`, `囊性变`

阶段收敛判断：

- 现在前端演示不需要打开 JSON，也能解释视觉证据审计：
  - 视觉 Agent 输出病灶图和 facts。
  - 诊断 Agent 标记 used/excluded。
  - QA 受同一份证据约束。
  - 前端显式展示 adopted/excluded facts。

下一步：

- 建议做“演示讲解态收敛”：生成一个简短的中文 demo script / walkthrough，按五个 Agent 顺序解释当前标准样例，包括上传图像、自动选 skill、病灶分割图、诊断采用证据、排除证据、memory audit 和追问 QA。

### 2026-05-25 标准 demo walkthrough

本轮目标：生成一份可直接用于现场讲解的中文 demo walkthrough，不继续改主链路代码。重点是把当前标准样例按五个 Agent 串起来，解释上传图片、自动选 skill、病灶图、采用/排除证据、memory audit 和追问 QA。

新增文件：

- `output/fake/standard_demo_walkthrough.md`

已完成：

- walkthrough 覆盖演示入口：
  - `http://127.0.0.1:8000`
  - `GET /v1/demo/standard`
  - `GET /v1/demo/standard/cases/fhn_no_mask_multifinding/response`
- walkthrough 按五个 Agent 组织：
  - 高医生 Agent：唯一前门、意图识别、分发和汇总。
  - Skill Builder Agent：加载 `femoral_head_necrosis_v0.1` guideline skill。
  - 视觉 Agent：VLM box prompt、MedSAM2 candidate mask、测量和 `structured_visual_facts`。
  - 诊断医生 Agent：只消费结构化证据，生成 used/excluded visual facts。
  - Memory Manager：保存 patient/image/skill/reasoning 四类 memory 和 audit。
- walkthrough 使用当前真实标准 demo 产物中的关键事实：
  - `case_id=case_20260525_111052_813246`
  - `structured_visual_facts` 数量：4
  - `used_count=2`
  - `excluded_count=2`
  - 采用证据：两条硬化带。
  - 排除证据：两条囊性变。
  - 排除原因：`non_independent_evidence`，与已采用硬化带 mask 高度重叠。
- walkthrough 给出推荐追问：
  - “为什么囊性变没有算作独立依据？”
  - “你刚才主要依据了哪些影像证据？”
  - “为什么还要 MRI？”
- walkthrough 明确当前 MVP 边界：不是临床级诊断系统，也不声称任意疾病/任意图像都能精确分割。

验证命令：

```bash
wc -l output/fake/standard_demo_walkthrough.md
rg 'GaoDoctorAgent|Skill Builder|Vision|Diagnosis|Memory|诊断采用证据|排除证据|finding_1_sclerotic_band|finding_3_cystic_change|non_independent_evidence|used_count|excluded_count' output/fake/standard_demo_walkthrough.md
sed -n '1,80p' output/fake/standard_demo_walkthrough.md
```

当前验证结果：

- `output/fake/standard_demo_walkthrough.md` 已生成，共 258 行。
- 文档中已包含五个 Agent、采用/排除证据、关键 finding id、`non_independent_evidence`、`used_count`、`excluded_count`。
- 文档开头已明确该 walkthrough 用于 MVP 演示，不作为医学结论或临床报告。

阶段收敛判断：

- 当前标准 demo 已具备三层材料：
  - 可运行前端：`http://127.0.0.1:8000`
  - 可读 demo artifacts：`/v1/demo/standard...`
  - 可讲解 walkthrough：`output/fake/standard_demo_walkthrough.md`

下一步：

- 建议做一次“现场演示 dry run”：按 walkthrough 真实点击前端或通过 HTTP 顺序拉取 demo response，确认页面上病灶图、采用证据、排除证据、诊断报告、memory audit 都能在同一轮演示中展示出来。

### 2026-05-25 标准 demo dry run 与 demo QA 修复

本轮目标：按 walkthrough 做一次真实 HTTP dry run，确认前端、预生成 demo、病灶图、evidence bundle、memory audit 和追问 QA 能在同一轮演示中顺畅展示。

修改文件：

- `api/http_server.py`
- `web/app.js`
- `tests/test_http_entrypoint.py`
- `output/fake/standard_demo_walkthrough.md`
- `output/fake/standard_demo_dry_run_report.md`
- `goalnew.md`

已完成：

- dry run 验证前端 HTML 包含：
  - `FHN no-mask 多征象样例`
  - `dropZone`
  - `evidencePanel`
  - `auditPanel`
  - `qaSubmitButton`
- dry run 验证前端 JS 包含：
  - `fetchStandardDemoCase`
  - `renderVisualFactUsage`
  - `诊断采用证据`
  - `排除证据`
  - `showQaThinking`
  - `setQaPending`
- dry run 验证 FHN no-mask demo response：
  - `case_id=case_20260525_111052_813246`
  - `analysis_status=partial_evidence`
  - `structured_visual_fact_count=4`
  - `used_count=2`
  - `excluded_count=2`
  - adopted labels：`硬化带`, `硬化带`
  - excluded labels：`囊性变`, `囊性变`
- dry run 验证病灶 overlay 图像可通过 HTTP 加载：
  - `200 image/png 47095`
- dry run 验证 memory audit：
  - `patient_memory=true`
  - `image_memory=true`
  - `skill_memory=true`
  - `reasoning_memory=true`
  - `visual_fact_usage.used_count=2`
  - `visual_fact_usage.excluded_count=2`

发现并修复的问题：

- 问题：前端加载离线 demo response 后，追问仍走实时 `/v1/medscope`，但 demo `case_id` 不在默认 `data/cases/`，导致 `FileNotFoundError` 和 HTTP 连接断开。
- 根因：离线 demo artifact 与实时 memory backend 是两条不同路径，追问路径没有区分。
- 修复：
  - 新增 `POST /v1/demo/standard/cases/{case_slug}/qa`。
  - 前端加载预生成 demo 后记录 `demoCaseSlug`。
  - demo 追问走 demo QA endpoint。
  - 实时病例追问仍走 `/v1/medscope`。
- demo QA 当前基于预生成 artifact 的 `visual_fact_usage` 生成稳定回答，不调用实时 memory。

验证命令：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_demo_case_qa_answers_from_artifact_visual_fact_usage -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_http_entrypoint.HttpEntrypointTest.test_demo_case_qa_answers_from_artifact_visual_fact_usage -v
python -m unittest tests.test_http_entrypoint tests.test_end_to_end_demo tests.test_service_entrypoint tests.test_llm_routing -v
python -m unittest discover -v
python -m api.http_server --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/static/app.js | rg 'postDemoQa|demoCaseSlug|/v1/demo/standard/cases/|/qa'
curl -s -X POST http://127.0.0.1:8000/v1/demo/standard/cases/fhn_no_mask_multifinding/qa -H 'Content-Type: application/json' -d '{"case_id":"case_20260525_111052_813246","patient_message":"为什么囊性变没有算作独立依据？"}'
```

当前验证结果：

- 新增 demo QA 红绿闭环已确认：
  - 先因 `dispatch_demo_request()` 不支持 `body` / POST QA 而失败。
  - 实现后目标测试通过。
- HTTP / end-to-end demo / service / LLM QA 相关回归：52 个测试通过。
- 全量 `python -m unittest discover -v`：260 个测试通过。
- HTTP API 已用最新代码重启，`/health` 返回 `{"status":"ok"}`。
- 真实 demo QA 返回：
  - `intent=qa`
  - `qa_source=demo_artifact`
  - `used_count=2`
  - `excluded_count=2`
  - 回答包含 `non_independent_evidence` 和“不作为独立诊断依据”。
- 服务日志未再出现 demo QA 的 `FileNotFoundError`。

新增输出：

- `output/fake/standard_demo_dry_run_report.md`

阶段收敛判断：

- 当前标准演示已完成 dry run，可以按 walkthrough 现场展示：
  - 一键加载 FHN no-mask 样例。
  - 展示病灶 overlay。
  - 展示采用/排除视觉证据。
  - 展示诊断报告和 MRI 建议。
  - 展示 memory audit。
  - 追问“为什么囊性变没有算作独立依据？”可稳定回答。

下一步：

- 建议进入“最终 MVP 状态盘点”：按五个 Agent 汇总当前完成度、仍是 MVP/模拟的边界、下一阶段真正要做的三件事，避免继续在已收敛的演示链路上追加小功能。

### 2026-05-25 五 Agent MVP 状态盘点

本轮目标：在标准演示 dry run 已通过后，做最终 MVP 状态盘点，明确哪些已经收敛、哪些只是 MVP/模拟边界、下一阶段真正应该做什么，避免继续在已收敛演示链路上追加小功能。

新增文件：

- `output/fake/mvp_status_by_agents.md`

已完成：

- 按五个 Agent 汇总当前状态：
  - 高医生 Agent：唯一前门、自动路由、QA 约束已闭环。
  - Skill Builder Agent：guideline skill MVP 已闭环，真实大规模指南发现仍属下一阶段。
  - 视觉 Agent：通用候选分割 MVP 已闭环，临床级分割精度未收敛。
  - 诊断医生 Agent：evidence-constrained diagnosis 与 visual_fact_usage 审计已闭环。
  - Memory Manager：patient/image/skill/reasoning 四类 memory 与 audit 已闭环。
- 报告引用当前已验证证据：
  - `/health` 返回 `{"status":"ok"}`
  - `GET /v1/demo/standard` 返回 3 个 `ok` case
  - FHN no-mask response：`structured_visual_fact_count=4`
  - `used_count=2`
  - `excluded_count=2`
  - overlay 图像 HTTP 返回 `200 image/png 47095`
  - memory audit 四类 memory 均为 true
  - demo QA 返回 `qa_source=demo_artifact`
  - 全量回归 260 个测试通过
- 报告明确两条路径：
  - 离线演示路径：`/v1/demo/standard...`
  - 实时病例路径：`/v1/medscope` + `/v1/memory/cases/{case_id}/...`
- 报告明确当前阶段不应继续扩展：
  - 换分割模型
  - 追求所有病种临床级分割
  - 大规模 memory 后端迁移
  - 全自动医学指南发现平台
  - 继续重构前端布局
- 报告给出下一阶段真正该做的三件事：
  1. 选择一个新病种跑完整 guideline skill 流。
  2. 建立视觉 Agent 评测线。
  3. 固化演示版与研究版边界。
- 报告建议将当前版本冻结为：
  - `MedScope Agent MVP v0.1 - guideline-aware visual evidence demo`

验证命令：

```bash
wc -l output/fake/mvp_status_by_agents.md
rg '高医生 Agent|Skill Builder Agent|视觉 Agent|诊断医生 Agent|Memory Manager|MVP v0.1|下一阶段真正该做的三件事|used_count=2|excluded_count=2|260 个测试' output/fake/mvp_status_by_agents.md
sed -n '1,120p' output/fake/mvp_status_by_agents.md
```

当前验证结果：

- `output/fake/mvp_status_by_agents.md` 已生成。
- 内容包含五个 Agent、MVP 边界、下一阶段三件事、版本冻结建议和已验证证据。

阶段收敛判断：

- 当前演示链路、讲解材料、dry run 报告和 MVP 状态盘点均已齐备。
- 建议当前阶段到此冻结，不再继续在 FHN no-mask 标准 demo 上扩功能。

下一步：

- 如果继续推进，建议开启新阶段：选一个新病种，用真实指南采集器生成 guideline skill，再跑一条新的端到端样例，而不是继续改当前标准 demo。

### 2026-05-25 下一阶段病种选择：IPF / 特发性肺纤维化

本轮目标：回答“这部分什么时候收敛”，并把下一阶段从“继续发散视觉 Agent 精度”收敛到一个新的真实指南 + 真实图像端到端样例。

新增文件：

- `output/fake/next_disease_ipf_plan.md`

阶段判断：

- FHN no-mask 标准 demo 已建议冻结为 `MedScope Agent MVP v0.1 - guideline-aware visual evidence demo`。
- 当前不再继续在 FHN demo 上追加小功能。
- 下一阶段建议选 IPF / 特发性肺纤维化，目标版本为：
  - `MedScope Agent MVP v0.2 - real guideline skill + CT visual evidence demo`

选择 IPF 的原因：

- 有 ATS / ERS / JRS / ALAT 官方指南来源。
- HRCT 是诊断路径里的关键影像输入，适合验证 skill 驱动视觉 Agent。
- 指南里有可结构化的 HRCT pattern：UIP、probable UIP、indeterminate for UIP、alternative diagnosis。
- 有公开 CT 数据候选：OSIC Pulmonary Fibrosis Progression 及相关肺分割 mask 数据集。
- 医疗安全边界清晰：视觉 Agent 只能输出结构化影像证据，不能单独给出最终 IPF 诊断。

下一阶段收敛标准：

- Skill Builder 能基于真实 IPF 指南生成 `idiopathic_pulmonary_fibrosis_hrct` guideline skill。
- 高医生 Agent 能根据主诉和胸部 CT / HRCT 自动选择该 skill。
- 视觉 Agent 能按 skill 输出纤维化候选区域、overlay、mask、分布和结构化数值证据。
- Diagnosis Agent 只消费 evidence bundle，并在证据不足时明确建议补充 HRCT、肺功能、病史和 ILD 多学科评估。
- Memory audit 能完整记录 patient_memory、image_memory、skill_memory、reasoning_memory。

下一步：

- 直接进入“真实网页 / PDF 指南采集器 -> IPF guideline skill 草案”。

### 2026-05-25 IPF 真实指南采集器与 guideline skill 草案

本轮目标：按照下一阶段收敛方向，先完成“真实网页 / PDF 指南采集器 -> IPF guideline skill 草案”的第一版，不进入视觉 Agent 大重构。

代码变更：

- 扩展 `scripts/collect_guideline_source.py`：
  - 新增 `--publication-year`
  - 新增 `--region`
  - 新增 `--source-priority`
- 扩展 `tools/guideline_source_collector_tool.py`：
  - 采集 raw guideline text 时保留 `publication_year`、`region`、`source_priority`。
  - 这些字段会继续进入 `GuidelineSourceImportTool` 的 source catalog。
- 新增 `scripts/ipf_guideline_skill_demo.py`：
  - 默认输出到 `output/fake/ipf_guideline_skill_demo/`。
  - disease_key 固定为 `idiopathic_pulmonary_fibrosis_hrct`。
  - 内置两个真实指南来源：
    - 2022 ATS / ERS / JRS / ALAT IPF update：PMC 页面。
    - 2018 ATS / ERS / JRS / ALAT IPF diagnosis guideline：PubMed 页面。
  - 支持 `--collect-sources` 真实抓取网页/PDF 来源。
  - 同时生成结构化 raw guideline 草案、source catalog 和 guideline skill 草案。
- 新增 `tests/test_ipf_guideline_skill_demo.py`。
- 扩展 `tests/test_guideline_source_collector.py`，覆盖 priority metadata 透传。

新增输出：

- `output/fake/ipf_guideline_skill_demo/raw/ats_ers_jrs_alat_ipf_2022_structured_raw.txt`
- `output/fake/ipf_guideline_skill_demo/raw/ats_ers_jrs_alat_ipf_diagnosis_2018_structured_raw.txt`
- `output/fake/ipf_guideline_skill_demo/collected_sources/ats_ers_jrs_alat_ipf_2022_collected_raw.txt`
- `output/fake/ipf_guideline_skill_demo/collected_sources/ats_ers_jrs_alat_ipf_diagnosis_2018_collected_raw.txt`
- `output/fake/ipf_guideline_skill_demo/guideline_sources.json`
- `output/fake/ipf_guideline_skill_demo/idiopathic_pulmonary_fibrosis_hrct.yaml`

真实采集结果：

```text
python -m scripts.ipf_guideline_skill_demo --collect-sources --timeout-seconds 10
```

- `source_count=2`
- `collected_source_count=2`
- 2022 PMC 页面采集成功：
  - `content_type=text/html`
  - `char_count=176180`
- 2018 PubMed 页面采集成功：
  - `content_type=text/html`
  - `char_count=3534`

生成的 IPF skill 草案包含：

- `skill_type=guideline_based`
- `path_type=guideline_aware`
- `required_image_views` 包含：
  - `HRCT chest`
  - `thin-section chest CT`
- `staging_rules` 包含：
  - `UIP_pattern`
  - `probable_UIP_pattern`
  - `indeterminate_for_UIP`
  - `alternative_diagnosis_pattern`
- `vision_agent_tasks.segmentation_targets` 包含：
  - `honeycombing_candidate`
  - `reticulation_candidate`
  - `traction_bronchiectasis_candidate`
  - `fibrosis_candidate`
- `visual_protocol.required_modalities` 明确这些视觉任务需要 HRCT / thin-section CT。
- `quality_control.formal_skill_status=formal_ready`

验证命令：

```bash
python -m unittest tests.test_guideline_source_collector.GuidelineSourceCollectorTest.test_collect_html_guideline_source_preserves_priority_metadata -v
python -m unittest tests.test_ipf_guideline_skill_demo -v
python -m scripts.ipf_guideline_skill_demo
python -m scripts.ipf_guideline_skill_demo --collect-sources --timeout-seconds 10
python -m unittest tests.test_guideline_source_collector tests.test_guideline_import_pipeline tests.test_guideline_skill_builder tests.test_ipf_guideline_skill_demo -v
python -m unittest discover -v
```

当前验证结果：

- 新增测试先按预期失败：
  - CLI 不认识 `--publication-year / --region / --source-priority`。
  - `scripts.ipf_guideline_skill_demo` 不存在。
- 实现后新增测试通过。
- 指南采集 / 导入 / Skill Builder 相关 29 个测试通过。
- 全量回归：262 个测试通过。

阶段判断：

- “真实网页/PDF 指南采集器”已经从通用工具走到 IPF 真实来源样例。
- 当前 IPF skill 仍是 `output/fake/` 下的草案，尚未确认进入正式 `skills/`。
- 下一步不应继续改采集器本身，应该进入：
  - OSIC CT 数据接入计划。
  - IPF visual_protocol 对 Vision Agent 的执行链路。
  - 让高医生 Agent 根据“咳嗽/气短 + 胸部 CT/HRCT”自动选择 `idiopathic_pulmonary_fibrosis_hrct`。

### 2026-05-25 IPF skill 正式接入与自动路由

本轮目标：把上一轮 `output/fake` 下的 IPF guideline skill 草案接入正式系统入口，让高医生 / API 编排层能自动选择该 skill。视觉 CT 数据和 OSIC 接入留到下一阶段，不在本轮混做。

代码与数据变更：

- 新增正式 skill：
  - `skills/idiopathic_pulmonary_fibrosis_hrct.yaml`
- 更新默认指南 source catalog：
  - `data/guidelines/guideline_sources.json`
  - 新增 `idiopathic_pulmonary_fibrosis_hrct`
  - 保留 2022 ATS / ERS / JRS / ALAT IPF update 与 2018 IPF diagnosis guideline 两个来源。
- 更新 `api/service.py`：
  - 新增 IPF 自动路由 clues。
  - 匹配 `特发性肺纤维化`、`肺纤维化`、`间质性肺病`、`UIP`、`IPF`、`HRCT`、`chest CT`、`干咳`、`气短` 等线索。
  - 自动选择 `idiopathic_pulmonary_fibrosis_hrct`。
  - 暂不设置专用 `vision_mode`，避免在未接 OSIC/CT 执行链路前强行触发 MedSAM2。
- 更新 `tools/alignment_planner.py`：
  - 支持从文本 / 路径识别 `HRCT` 和 `thin-section CT`。
  - 支持将 HRCT / chest CT 归一为 CT 模态。
  - 支持识别 chest / lung / pulmonary / IPF / UIP / 胸 / 肺为胸部影像上下文。
  - CT 模态可满足 `HRCT chest` / `thin-section chest CT` 视觉任务要求。
- 更新测试：
  - `tests/test_guideline_skill_builder.py`
  - `tests/test_visual_protocol_validator.py`
  - `tests/test_service_entrypoint.py`

新增验证覆盖：

- 默认 `GuidelineSearchTool()` 能找到 IPF 指南来源。
- `SkillBuilderTool` 能从默认 catalog 构建 IPF guideline skill。
- `skills/idiopathic_pulmonary_fibrosis_hrct.yaml` 通过 `VisualProtocolValidator`。
- `MedScopeService` 能根据“干咳、气短、HRCT、特发性肺纤维化、UIP”等线索自动选择 IPF skill。
- alignment plan 能识别：
  - `modality=CT`
  - `available_sequences` 包含 `HRCT`
  - `body_part=chest`
  - `analysis_status=evidence_sufficient`

验证命令：

```bash
python -m unittest tests.test_guideline_skill_builder.GuidelineSkillBuilderTest.test_guideline_search_finds_ipf_hrct_source -v
python -m unittest tests.test_visual_protocol_validator.VisualProtocolValidatorTest.test_static_guideline_skills_have_valid_visual_protocol -v
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_auto_selects_ipf_skill_from_hrct_chest_clues -v
python -m unittest tests.test_service_entrypoint tests.test_http_entrypoint tests.test_guideline_skill_builder tests.test_visual_protocol_validator tests.test_ipf_guideline_skill_demo -v
python -m unittest discover -v
```

当前验证结果：

- 新增测试先按预期失败：
  - default source catalog 找不到 IPF。
  - `skills/idiopathic_pulmonary_fibrosis_hrct.yaml` 不存在。
  - 服务入口不会自动选择 IPF。
- 实现后，三个新增定向测试通过。
- 相关模块回归：63 个测试通过。
- 全量回归：264 个测试通过。

阶段判断：

- IPF 已从“草案 skill”进入系统正式 skill 列表。
- 高医生入口 / API 编排层已经能自动选择 IPF skill。
- 这一小阶段已收敛。

下一步：

- 接入 OSIC CT 数据 manifest / 下载校验。
- 建立 IPF visual demo 脚本：读取 OSIC CT slice 或 volume，按 `idiopathic_pulmonary_fibrosis_hrct` 的 visual_protocol 生成视觉任务和证据 bundle。
- 在还没有像素级纤维化标签前，明确区分：
  - 肺野 mask / anatomy mask：可用于归一化面积和区域分布。
  - 纤维化候选 mask：只能作为模型候选输出，不能当成 ground truth。

### 2026-05-25 OSIC / IPF CT 数据 manifest 与下载校验

本轮目标：先接入 OSIC CT 数据的 manifest 和下载 readiness 检查，不伪造本地 CT 病例，也不把肺野 mask 当作纤维化病灶标签。

新增文件：

- `data/external/osic_ipf_manifest.json`
- `scripts/osic_ipf_dataset.py`
- `tests/test_osic_ipf_dataset.py`

manifest 内容：

- dataset：`OSIC Pulmonary Fibrosis Progression`
- disease_key：`idiopathic_pulmonary_fibrosis_hrct`
- modality：`HRCT chest / chest CT`
- 数据来源：
  - OSIC Pulmonary Fibrosis Progression Kaggle competition
  - OSIC pulmonary fibrosis lung mask dataset
  - CT lung / heart / trachea segmentation dataset
- 当前 `cases=[]`，状态应为 `pending_download`。
- 明确数据边界：
  - CT 是原始医疗图像输入。
  - lung mask 只能作为 anatomy mask / 肺野归一化，不是 fibrosis ground truth。
  - 默认没有像素级 fibrosis mask。
  - FVC / time metadata 只能支持进展上下文，不是病灶像素标注。

新增脚本能力：

```bash
python -m scripts.osic_ipf_dataset --validate-manifest
python -m scripts.osic_ipf_dataset --check-download-readiness
```

当前默认 manifest 验证结果：

- `status=pending_download`
- `case_count=0`
- `valid_count=0`
- 无 invalid case。
- action items 指向：
  - 先在 Kaggle 接受数据条款并下载 OSIC CT。
  - 再把本地 CT case path 写入 manifest。
  - 可选加入 lung_mask_path，但必须标明 anatomy only。

下载 readiness 行为：

- 检查 Kaggle API credentials。
- 当缺少 `kaggle.json` 时返回：
  - `status=needs_auth`
  - `kaggle_config_present=false`
  - action item 提示配置 Kaggle credential。
- 不会自动下载大数据。

测试覆盖：

- 默认 manifest 会返回 `pending_download`。
- 临时构造的本地 CT case + lung mask 能通过 manifest 校验。
- 缺失 CT path 会在运行 visual demo 前报 invalid。
- 下载 readiness 能在不下载数据的情况下提示 Kaggle auth 需求。

验证命令：

```bash
python -m unittest tests.test_osic_ipf_dataset -v
python -m scripts.osic_ipf_dataset --validate-manifest
python -m scripts.osic_ipf_dataset --check-download-readiness --kaggle-config-path /private/tmp/missing_kaggle_for_medscope.json
python -m unittest tests.test_osic_ipf_dataset tests.test_ipf_guideline_skill_demo tests.test_service_entrypoint tests.test_guideline_skill_builder tests.test_visual_protocol_validator -v
python -m unittest discover -v
```

当前验证结果：

- OSIC/IPF 数据集新增测试：4 个通过。
- 相关模块回归：47 个测试通过。
- 全量回归：268 个测试通过。

阶段判断：

- OSIC 数据入口已经接入，但真实 CT 尚未下载到本地。
- 当前仍不进入 `output/real/`，因为没有确认正确的真实 OSIC 本地病例。
- 这一小阶段已收敛。

下一步：

- 做 `ipf_visual_demo` 的 dry-run/manifest-aware 脚本：
  - 当 manifest 仍为 `pending_download` 时，清晰返回缺数据和下载要求。
  - 当 manifest 有本地 CT case 时，加载 `idiopathic_pulmonary_fibrosis_hrct` skill，生成 visual task plan 和 evidence bundle skeleton。
  - 在没有 fibrosis mask 时，只允许输出 anatomy/context 证据，不得伪造纤维化分割结果。

### 2026-05-25 IPF visual demo dry-run 与 Vision Agent v0.1 收敛

本轮目标：把 IPF 视觉链路先收敛为 manifest-aware dry-run，并同时冻结 Vision Agent v0.1 的 MVP 边界，避免把“通用 Agent 架构闭环”和“研究级分割模型能力”混在一起。

新增文件：

- `scripts/ipf_visual_demo.py`
- `tests/test_ipf_visual_demo.py`
- `output/fake/vision_agent_v0_1_freeze.md`

IPF visual demo 当前行为：

- 默认 `data/external/osic_ipf_manifest.json` 仍为 `cases=[]`，运行 `python -m scripts.ipf_visual_demo` 返回 `status=pending_download`。
- 没有本地 OSIC CT case 时，不生成 evidence bundle，不生成假 mask。
- 若 manifest 中存在本地 CT case，脚本会加载 `idiopathic_pulmonary_fibrosis_hrct` skill，生成 alignment plan 和 `ipf_visual_evidence_bundle.v1`。
- 若只有 lung mask，bundle 会明确标记 `lung_mask_status=available_anatomy_only`，且说明 lung mask 不是 fibrosis lesion label。
- honeycombing / reticulation / traction bronchiectasis / fibrosis candidate mask 等字段保持 `unassessed` 或 missing，不转写为阴性或 0。

Vision Agent v0.1 冻结边界：

- 收敛标准是 skill 约束的图像证据提取闭环，而不是所有疾病的临床级分割准确率。
- Visual Agent 输出两类结果：
  - 图像产物：`mask_path`、`overlay_path`、上传图路径。
  - 结构化证据：`structured_visual_facts`、`measurements`、`completeness`、`quality_warnings`、`visual_fact_usage`、`evidence_bundle`。
- Diagnosis Agent 不读原始图像，只消费 evidence bundle。
- 证据不足时必须拒绝判断或建议补充正确模态，例如 X 光无法可靠判断早期股骨头坏死时提示 MRI，IPF dry-run 缺 CT 时提示先下载/配置 CT case。

当前可演示样例：

- FHN no-mask 多征象样例：展示 VLM box prompt + MedSAM2 candidate mask + measurements + 质量门控 + 诊断证据采用/排除。
- BraTS / 胶质瘤样例：展示 reference mask / MedSAM2 后端、overlay、体积测量和 modality completeness。
- IPF / OSIC dry-run：展示真实指南 skill 和数据集入口，但在缺少本地 CT / fibrosis mask 时不伪造病灶分割。

验证命令：

```bash
python -m unittest tests.test_ipf_visual_demo -v
python -m scripts.ipf_visual_demo
python -m unittest tests.test_end_to_end_demo tests.test_no_mask_skill_visual_pipeline_demo tests.test_no_mask_medsam2_segmentation_demo tests.test_ipf_visual_demo -v
python -m unittest discover -v
```

当前验证结果：

- `tests.test_ipf_visual_demo`：3 个通过。
- `python -m scripts.ipf_visual_demo`：返回 `status=pending_download`，符合默认 manifest 状态。
- 全量回归：271 个测试通过。

阶段判断：

- Vision Agent 主线 v0.1 可以收敛。
- 后续不要在这一阶段继续追求所有病种的精准分割。
- 下一阶段应选择一个真实数据闭环，围绕一个疾病完成“真实图像 + guideline skill + VLM prompt + MedSAM2 mask + measurements + diagnosis + memory audit”。

### 2026-05-25 真实数据闭环主线脚本

本轮目标：把已有 `output/fake/mainline_real_dataset/` 旧产物升级成可重复执行的标准入口，而不是只保留一次性输出。当前仍使用 BraTS ground-truth mask 验证主线契约，不宣称 MedSAM2 已完成自动病灶分割。

新增文件：

- `scripts/mainline_real_dataset_demo.py`
- `tests/test_mainline_real_dataset_demo.py`

主线脚本能力：

```bash
python -m scripts.mainline_real_dataset_demo
```

该入口串起五步：

1. 校验 `data/external/brats_manifest.json`。
2. 从 BraTS reference mask 生成 prompt JSON 和 prompt overlay。
3. 批量运行 BraTS ground-truth 视觉链路，输出 overlay、结构化视觉证据和 Dice。
4. 运行标准端到端 demo：上传真实 FLAIR MRI、自动选择 `diffuse_glioma_brats`、调用 Vision Agent、生成诊断报告。
5. 汇总 evidence bundle、memory audit、summary 和 `MAINLINE_RUN.md`。

默认输出：

- `output/fake/mainline_real_dataset/summary.json`
- `output/fake/mainline_real_dataset/MAINLINE_RUN.md`
- `output/fake/mainline_real_dataset/prompts/prompts_summary.json`
- `output/fake/mainline_real_dataset/vision_ground_truth/summary.json`
- `output/fake/mainline_real_dataset/full_e2e/end_to_end_demo_summary.json`

当前默认运行结果：

- dataset：`BraTS2021`
- disease_key：`diffuse_glioma_brats`
- manifest：2/2 valid
- prompt generation：2/2 ok
- vision ground-truth batch：2/2 ok
- mean Dice：
  - whole tumor：1.0
  - tumor core：1.0
  - enhancing tumor：1.0
- end-to-end selected_skill：`diffuse_glioma_brats`
- end-to-end selected_vision_mode：`ground_truth`

重要边界：

- 当前真实数据闭环证明的是“真实数据集标注 -> skill-driven Vision Agent -> 结构化证据 -> Diagnosis Agent -> evidence bundle -> memory audit”。
- 它还不证明无 reference mask 的自动分割能力。
- 要宣称“自动圈出病灶”，下一阶段必须运行 MedSAM2 或专病分割后端，不使用 reference mask 作为输入，并对模型 mask 与 reference mask 做 Dice/QC 对比。

验证命令：

```bash
python -m unittest tests.test_mainline_real_dataset_demo -v
python -m scripts.mainline_real_dataset_demo
python -m unittest tests.test_mainline_real_dataset_demo tests.test_end_to_end_demo tests.test_brats_vision_test_line -v
python -m unittest discover -v
```

阶段判断：

- 真实数据闭环已经有可重复入口。
- 主线仍放在 `output/fake/`，因为 ground-truth mask 用于验证契约，不是已确认的自动分割结果。
- 下一步如果继续视觉能力，应进入“MedSAM2 无 reference mask 自动分割评估”，而不是再做新的静态 demo。

### 2026-05-25 MedSAM2 无 reference mask 自动分割评估门槛

本轮目标：把“自动圈病灶”从口头说法变成可执行评估门槛。当前不直接宣称 MedSAM2 已经完成自动分割，而是先固定：reference mask 不能作为 prompt 来源，只能作为模型输出后的 Dice/QC 评估依据。

新增文件：

- `scripts/brats_medsam2_auto_eval.py`
- `tests/test_brats_medsam2_auto_eval.py`

新增入口：

```bash
python -m scripts.brats_medsam2_auto_eval
python -m scripts.brats_medsam2_auto_eval --prompt <non_reference_prompt.json>
```

核心规则：

- 如果没有 prompt，返回 `status=needs_prompt`，不调用 MedSAM2。
- 如果 prompt 的 `source=reference_mask_bbox` 或 `ground_truth_mask_bbox`，默认返回 `status=rejected_reference_prompt`，不调用 MedSAM2。
- 只有 `source=vision_model_bbox` 这类非 reference prompt 才允许进入自动分割评估。
- reference mask 只允许用于后验 `evaluation`，不能参与 prompt 生成。
- 输出边界写入：
  - `prompt_role=non_reference_candidate_localization_required`
  - `reference_mask_role=evaluation_only`
  - `model_mask_role=automatic_candidate_segmentation`
  - `diagnostic_claim=not_clinical_grade_until_overlay_qc_and_metric_review`

测试覆盖：

- 缺少 prompt 时返回 `needs_prompt`，且 `real_call_attempted=false`。
- 使用 reference-mask 生成的 prompt 时返回 `rejected_reference_prompt`，且 `real_call_attempted=false`。
- 注入 fake MedSAM2 runner 时，能在不使用 reference prompt 的情况下生成 model mask，随后用 reference mask 计算 Dice，并输出 Vision Agent 的结构化测量。

当前默认命令结果：

```bash
python -m scripts.brats_medsam2_auto_eval
```

返回：

- `status=needs_prompt`
- `real_call_attempted=false`

使用当前旧 prompt：

```bash
python -m scripts.brats_medsam2_auto_eval --prompt output/fake/mainline_real_dataset/prompts/brats2021_00030_prompt.json
```

返回：

- `status=rejected_reference_prompt`
- 原因：该 prompt 来源是 `reference_mask_bbox`，不能作为自动分割能力评估输入。

验证命令：

```bash
python -m unittest tests.test_brats_medsam2_auto_eval -v
python -m unittest tests.test_brats_medsam2_auto_eval tests.test_mainline_real_dataset_demo tests.test_brats_vision_test_line -v
python -m unittest discover -v
```

阶段判断：

- MedSAM2 自动分割评估入口已建立，但当前真实环境还缺非 reference prompt。
- 下一步应接入 VLM/Gemini 生成 `source=vision_model_bbox` 的 BraTS 2D/3D prompt，或者人工提供一份非 reference prompt，再运行真实 MedSAM2 并看 Dice/QC。

### 2026-05-25 BraTS VLM 非 reference prompt 入口

本轮目标：补上 MedSAM2 自动分割评估之前的关键前置产物：从 BraTS FLAIR NIfTI 中导出单张 2D slice PNG，让 VLM/Gemini 根据图像本身生成 `source=vision_model_bbox` 的候选 box prompt。该 prompt 不允许来自 reference mask。

新增文件：

- `scripts/brats_vlm_prompt_demo.py`
- `tests/test_brats_vlm_prompt_demo.py`

新增入口：

```bash
python -m scripts.brats_vlm_prompt_demo --slice-index 100 --output-dir output/fake/brats_vlm_prompt_demo_cli_probe
```

输出内容：

- `*_slice_100.png`：从 BraTS NIfTI 导出的 VLM 输入切片。
- `*_vlm_prompt_result.json`：VLM 原始结构化输出校验结果。
- `*_vision_model_prompt.json`：MedSAM2 auto-eval 可消费的 prompt，固定 `source=vision_model_bbox`。
- `*_vision_model_prompt_overlay.png`：VLM 候选框叠加图。

边界规则：

- `reference_mask_used=false`。
- `prompt_role=vision_model_candidate_localization`。
- `diagnosis_usable=false`，因为 VLM box 只是候选定位，不是诊断证据。
- CLI 会读取 `.env.local` 中的 `DMX_API_KEY`，但 API key 不写入代码或日志。
- 缺少 `DMX_API_KEY` 或真实 VLM 路由网络失败时返回结构化 `status=vlm_not_ready`，不会生成假 box，也不会 traceback。

测试覆盖：

- fake VLM client 能生成 `source=vision_model_bbox` prompt。
- 输出 prompt 不包含 `reference_mask_path`。
- 生成的 VLM prompt 可以被 `scripts.brats_medsam2_auto_eval` 接受，并进入 fake MedSAM2 runner + Dice/QC 后验评估。
- 缺少 API key 时 CLI 返回结构化 `vlm_not_ready`，而不是 traceback。
- VLM 路由失败时返回结构化 `vlm_not_ready`，而不是 traceback。

当前 CLI 探针结果：

```bash
python -m scripts.brats_vlm_prompt_demo --slice-index 100 --output-dir output/fake/brats_vlm_prompt_demo_cli_probe
```

返回：

- `status=vlm_not_ready`
- `real_call_attempted=true`
- 原因：沙箱内 DNS/网络解析失败
- 仍已导出可供 VLM 使用的 slice PNG。

真实联网 API 探针：

```bash
python -m scripts.brats_vlm_prompt_demo --slice-index 100 --output-dir output/fake/brats_vlm_prompt_demo_real_api
```

返回：

- `status=ok`
- `prompt_source=vision_model_bbox`
- `boxes=[[58, 130, 125, 195]]`
- `real_call_attempted=true`
- `reference_mask_used=false`

该真实 VLM prompt 继续交给 MedSAM2 auto-eval gate：

```bash
python -m scripts.brats_medsam2_auto_eval --prompt output/fake/brats_vlm_prompt_demo_real_api/BraTS2021_00030_flair_vision_model_prompt.json --output-dir output/fake/brats_medsam2_auto_eval_real_vlm_prompt
```

返回：

- `status=not_ready`
- `prompt_source=vision_model_bbox`
- `real_call_attempted=false`
- 原因：当前环境未配置 `MEDSAM2_COMMAND_TEMPLATE`
- 已写入 `output/fake/brats_medsam2_auto_eval_real_vlm_prompt/summary.json`
- 结论：真实 VLM 生成的非 reference prompt 已通过 gate，下一阻塞点是连接真实 MedSAM2 命令。

验证命令：

```bash
python -m unittest tests.test_brats_vlm_prompt_demo -v
python -m unittest tests.test_brats_vlm_prompt_demo tests.test_brats_medsam2_auto_eval tests.test_vision_prompt_generator -v
python -m unittest discover -v
```

阶段判断：

- BraTS VLM prompt 生成链路已经接到 auto-eval 门槛。
- 真实 VLM API 已输出非 reference `vision_model_bbox`。
- 已用临时 BraTS MedSAM2 command template 跑通真实 CPU MedSAM2 分割、Dice/QC 和诊断 Agent LLM 报告。

### 2026-05-25 真实 VLM bbox -> MedSAM2 -> 诊断 Agent 收敛样例

本轮目标：把“真实 VLM 根据 skill 生成 bbox prompt”继续接到真实 MedSAM2 分割，再把 Vision Agent 输出的结构化 evidence bundle 传给诊断 Agent，形成一条可演示主线。

真实输入：

- 图像：`data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz`
- VLM prompt：`output/fake/brats_vlm_prompt_demo_real_api/BraTS2021_00030_flair_vision_model_prompt.json`
- prompt source：`vision_model_bbox`
- bbox：`[[58, 130, 125, 195]]`
- reference mask：只用于后验 Dice/QC，不参与 prompt 生成。

真实 MedSAM2 命令配置：

```bash
MEDSAM2_REPO_PATH=/private/tmp/medscope_medsam2_probe
MEDSAM2_TIMEOUT_SECONDS=900
MEDSAM2_COMMAND_TEMPLATE='python /Users/houshaohua/Desktop/code/aidoctor/MedScope_Agent/scripts/medsam2_brats_wrapper.py --image {image_path} --output {output_mask_path} --prompt-json {prompt_json} --medsam2-repo /private/tmp/medscope_medsam2_probe --device cpu --checkpoint /private/tmp/medscope_medsam2_probe/checkpoints/MedSAM2_latest.pt --cfg /private/tmp/medscope_medsam2_probe/sam2/configs/sam2.1_hiera_t512.yaml'
```

真实 MedSAM2 输出：

- 目录：`output/fake/brats_medsam2_auto_eval_real_vlm_prompt_real_medsam2/`
- mask：`brats2021_00030_medsam2_auto_mask.nii.gz`
- overlay：`brats2021_00030_medsam2_auto_overlay.png`
- result：`brats2021_00030_medsam2_auto_eval_result.json`
- whole tumor Dice：`0.8867961392677113`
- tumor core Dice：`0.44137650999898487`
- enhancing tumor Dice：`0.0`
- whole tumor volume：`137.914 ml`

证据一致性修复：

- Vision Agent 现在会根据 `visual_protocol.completeness` 清理 legacy 顶层视觉数值。
- 当 `tumor_core` / `enhancing_tumor` 因缺少 T1/T1ce/T2 标记为 `missing` 时：
  - `visual_evidence.measurements.tumor_core_volume_ml = null`
  - `visual_evidence.measurements.enhancing_tumor_volume_ml = null`
  - 顶层 `visual_evidence.tumor_core_volume_ml` / `enhancing_tumor_volume_ml` 不再残留旧数值。
- 这样避免 LLM 从旧字段误读“缺失 = 0/阴性”。

诊断 Agent 输出：

- 新入口：`scripts/brats_real_vlm_medsam2_diagnosis_demo.py`
- 输出目录：`output/fake/brats_real_vlm_medsam2_diagnosis_demo_real_llm/`
- report：`diagnosis_report.json`
- evidence bundle：`evidence_bundle.json`
- LLM raw：`llm_raw_content.json`
- summary：`summary.json`
- route：`dmx`
- model：`gemini-3.5-flash`
- `llm_attempted=true`
- `llm_fallback_reason=null`

诊断报告关键结论：

- 诊断倾向：颅内占位性病变，影像学表现提示成人弥漫性胶质瘤可能，需结合完整影像及病理/分子检测进一步明确。
- 使用视觉字段：`whole_tumor`、`edema`
- 明确承认缺失字段：`tumor_core`、`enhancing_tumor`、`mass_effect`
- 报告明确说明缺少 T1/T1ce/T2 时，不能把缺失字段解释为阴性、无强化或体积为 0。

诊断安全栅栏修复：

- 原先 LLM 报告中如果 supported 字段（例如 edema）出现“阴性/未见”，会被错误套用到 missing 字段（例如 tumor_core）。
- 已将 missing visual evidence 校验改为 target-local context：只扫描包含该 missing target 别名的句子/列表项。
- 保留原有硬约束：如果模型真的把 missing target 写成阴性、未见、0 ml，仍会触发 fallback。

验证命令：

```bash
python -m unittest tests.test_brats_real_vlm_medsam2_diagnosis_demo -v
python -m unittest tests.test_diagnosis_llm_workflow -v
python -m unittest tests.test_brats_vision_tools -v
```

阶段判断：

- 真实主线已跑通到：真实图像 -> skill/VLM bbox -> MedSAM2 mask/overlay/数值 -> Diagnosis Agent LLM 报告。
- 当前仍未把这条真实链路整合成前端一键按钮；前端目前还主要消费已有 API/demo artifacts。

### 2026-05-25 真实 VLM + MedSAM2 样例 HTTP demo API 收敛

本轮目标：不在前端请求中重新跑 VLM/MedSAM2，而是先把已经跑通的真实 artifact 暴露为只读 demo API，保证演示链路可复现、可审计、不会因模型运行时间阻塞前端。

新增 HTTP demo 路由：

- `GET /v1/demo/real-vlm-medsam2`
  - 读取：`output/fake/brats_real_vlm_medsam2_diagnosis_demo_real_llm/summary.json`
- `GET /v1/demo/real-vlm-medsam2/report`
  - 读取：`output/fake/brats_real_vlm_medsam2_diagnosis_demo_real_llm/diagnosis_report.json`
- `GET /v1/demo/real-vlm-medsam2/evidence-bundle`
  - 读取：`output/fake/brats_real_vlm_medsam2_diagnosis_demo_real_llm/evidence_bundle.json`
- `GET /v1/demo/real-vlm-medsam2/raw-llm`
  - 读取：`output/fake/brats_real_vlm_medsam2_diagnosis_demo_real_llm/llm_raw_content.json`
- `GET /v1/demo/real-vlm-medsam2/segmentation`
  - 读取：`output/fake/brats_medsam2_auto_eval_real_vlm_prompt_real_medsam2/summary.json`
- `GET /v1/demo/real-vlm-medsam2/vlm-prompt`
  - 读取：`output/fake/brats_vlm_prompt_demo_real_api/summary.json`

接口边界：

- HTTP route 只读取 `output/` 下已有结果，不触发真实 API、不触发 MedSAM2 长任务。
- 分割能力本身暂时收敛为“VLM bbox prompt + MedSAM2 分割 + Dice/QC + 结构化数值”的可复现样例。
- 当前样例可以证明主线，但不能证明通用医学分割已经解决；后续通用性需要用更多病种/模态数据集继续验证。

验证命令：

```bash
python -m unittest tests.test_http_entrypoint -v
python -m unittest tests.test_brats_real_vlm_medsam2_diagnosis_demo tests.test_diagnosis_llm_workflow tests.test_brats_vision_tools tests.test_brats_medsam2_auto_eval tests.test_http_entrypoint -v
```

验证结果：

- `tests.test_http_entrypoint`：22 项通过。
- 相关链路测试：60 项通过。
- 默认真实 artifact 读取检查：
  - `/v1/demo/real-vlm-medsam2` -> `200 ok`
  - `/v1/demo/real-vlm-medsam2/report` -> `200`
  - `/v1/demo/real-vlm-medsam2/evidence-bundle` -> `200`
  - `/v1/demo/real-vlm-medsam2/segmentation` -> `200 ok`
  - `/v1/demo/real-vlm-medsam2/vlm-prompt` -> `200 ok`

阶段判断：

- 视觉 Agent 这一段可以先阶段性收敛：输出包含病灶图、mask、overlay、数值 evidence bundle，并能传给诊断 Agent。
- 真正未收敛的是“任意医学图像/任意病种都能稳定自动圈准病灶”，这需要数据集、模型评估和可能的模型替换，不应该混在当前 MVP 主线继续无限扩展。

### 2026-05-25 前端接入真实 VLM + MedSAM2 演示样例

本轮目标：把上一阶段已经暴露的只读 HTTP demo API 接到互动前端，形成可点击的真实主线演示入口。

前端新增：

- 病例输入区域新增按钮：`真实 VLM+MedSAM2 样例`
- 点击后读取以下只读 API：
  - `/v1/demo/real-vlm-medsam2`
  - `/v1/demo/real-vlm-medsam2/report`
  - `/v1/demo/real-vlm-medsam2/evidence-bundle`
  - `/v1/demo/real-vlm-medsam2/segmentation`
  - `/v1/demo/real-vlm-medsam2/vlm-prompt`
- 前端将这些 artifact 归一化为现有 `renderPayload` 可消费的结构，继续复用：
  - 图像输出面板
  - 诊断报告面板
  - 证据协调面板
  - evidence bundle 面板
  - memory trace 面板

展示内容：

- VLM 生成的 bbox prompt source 与 bbox。
- MedSAM2 输出的 mask/overlay 路径，并在图像输出面板显示 overlay。
- whole tumor / tumor core / enhancing tumor Dice 作为 QC 指标。
- whole tumor volume、tumor_core/enhancing_tumor 缺失充分性、补充 T1/T1ce/T2 的限制说明。
- 诊断 Agent 生成的 LLM 报告和指南引用。

边界：

- 前端按钮只展示已生成的真实 artifact，不在浏览器请求时重新跑 VLM、MedSAM2 或 LLM。
- 该入口用于演示主线闭环，不等价于已经解决通用医学图像病灶分割。

验证命令：

```bash
python -m unittest tests.test_http_entrypoint -v
node --check web/app.js
```

验证结果：

- `tests.test_http_entrypoint`：22 项通过。
- `node --check web/app.js`：通过。

### 2026-05-25 真实 VLM + MedSAM2 前端追问闭环

本轮目标：修正真实 VLM+MedSAM2 前端样例展示后的追问路径。上一阶段按钮已经能展示 artifact，但追问仍会落回普通 `/v1/medscope`，这会脱离当前真实样例的 evidence bundle。

新增：

- HTTP route：`POST /v1/demo/real-vlm-medsam2/qa`
- 前端函数：`postRealVlmMedSAM2Qa`
- 前端状态：点击真实样例后进入 `realDemoMode`，追问优先走真实 artifact QA 路由。

QA 边界：

- 不重新调用 VLM、MedSAM2 或 LLM。
- 只读取以下真实 artifact：
  - `summary.json`
  - `diagnosis_report.json`
  - `evidence_bundle.json`
- 回答必须受 evidence bundle 约束。
- 对 `enhancing_tumor` / `T1ce` / `0` 相关追问，明确说明：
  - `enhancing_tumor` 是缺失证据。
  - 原因是需要 T1ce。
  - 不能解释为阴性、无强化或体积为 0。
  - `enhancing_tumor Dice=0.0` 只代表本次候选分割没有可靠覆盖增强肿瘤标签，不构成临床阴性结论。

验证命令：

```bash
python -m unittest tests.test_http_entrypoint -v
node --check web/app.js
curl -s -X POST http://127.0.0.1:8099/v1/demo/real-vlm-medsam2/qa \
  -H 'Content-Type: application/json' \
  -d '{"patient_message":"为什么 enhancing tumor 是 0？"}'
```

验证结果：

- `tests.test_http_entrypoint`：23 项通过。
- `node --check web/app.js`：通过。
- 运行态 route 返回 `qa_source=real_vlm_medsam2_demo_artifact`，回答包含 T1ce 缺失、不能解释为阴性/0 的说明。

#### 追问后 trace 保持完整

补充修复：真实 demo QA 返回后，前端会用 QA payload 重绘页面；如果 QA payload 不携带 `alignment_plan` 和 `memory_replay`，追问一次后“证据协调”和“Memory Replay”会从完整演示退化为缺失状态。

新增要求：

- `POST /v1/demo/real-vlm-medsam2/qa` 返回 `alignment_plan`。
- `alignment_plan.analysis_status=partial_evidence`。
- `alignment_plan.selected_skill=diffuse_glioma_brats`。
- `memory_replay.steps` 最后一项为 `follow_up_qa`。
- `follow_up_qa.evidence_bundle_used=true`。

验证：

```bash
python -m unittest tests.test_http_entrypoint -v
python - <<'PY'
import json
import urllib.request
payload = json.dumps({'patient_message':'为什么 enhancing tumor 是 0？'}, ensure_ascii=False).encode('utf-8')
req = urllib.request.Request(
    'http://127.0.0.1:8100/v1/demo/real-vlm-medsam2/qa',
    data=payload,
    headers={'Content-Type':'application/json'},
    method='POST',
)
with urllib.request.urlopen(req, timeout=5) as resp:
    body = json.loads(resp.read().decode('utf-8'))
print(resp.status)
print(body['qa_source'])
print(body['alignment_plan']['analysis_status'])
print(body['memory_replay']['steps'][-1]['event'])
print(body['memory_replay']['steps'][-1]['evidence_bundle_used'])
PY
```

验证结果：

- `tests.test_http_entrypoint`：23 项通过。
- 运行态返回：
  - `200`
  - `real_vlm_medsam2_demo_artifact`
  - `partial_evidence`
  - `follow_up_qa`
  - `True`

### 2026-05-25 真实 VLM + MedSAM2 完整 response endpoint

本轮目标：把真实 VLM+MedSAM2 前端样例从“浏览器并发读取 5 个 artifact 再拼 payload”收拢为一个标准化 response API，降低前端脆弱性，并让它更接近标准 demo 的 `/response` 形态。

新增：

- HTTP route：`GET /v1/demo/real-vlm-medsam2/response`
- 前端函数：`fetchRealVlmMedSAM2Response`
- `fetchRealVlmMedSAM2Demo()` 优先读取完整 response；如果旧服务没有该 endpoint，再回退到原来的 5 个 artifact 拼装。

`/response` 返回：

- `case_id`
- `intent=diagnosis`
- `demo_source=real_vlm_medsam2_artifact`
- `report`
- `image_outputs`
- `visual_input_contract`
- `alignment_plan`
- `evidence_bundle`
- `memory_audit`
- `memory_replay`

运行态验证：

```bash
python - <<'PY'
import json
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8101/v1/demo/real-vlm-medsam2/response', timeout=5) as resp:
    body = json.loads(resp.read().decode('utf-8'))
    status = resp.status
print(status)
print(body['demo_source'])
print(body['intent'])
print(body['alignment_plan']['analysis_status'])
print(body['evidence_bundle']['image_evidence']['segmentation_quality'])
print(body['memory_replay']['steps'][-1]['event'])
PY
```

验证结果：

- `200`
- `real_vlm_medsam2_artifact`
- `diagnosis`
- `partial_evidence`
- `medsam2`
- `diagnosis_report`

### 2026-05-25 真实 VLM + MedSAM2 视觉任务明细契约

本轮目标：把真实样例 response 从“只有总体视觉证据”继续收敛为“能审计视觉 Agent 按 skill 执行了哪些任务、哪些分割结果可用于诊断”的结构。

新增到 `GET /v1/demo/real-vlm-medsam2/response`：

- `visual_input_contract.segmentation_results`
- `visual_input_contract.visual_tool_plan`
- `evidence_bundle.image_evidence.segmentation_results`
- `evidence_bundle.image_evidence.visual_tool_plan`
- `memory_audit.alignment_summary.visual_task_status_counts`

当前语义：

- `segmentation_results` 是视觉 Agent 的逐任务结果，例如 `segment_whole_tumor` 已完成且 `diagnosis_usable=true`。
- `missing_input` 任务会保留在结果里，例如 `tumor_core` 和 `enhancing_tumor` 因缺少 T1/T1ce/T2 不进入诊断可用证据。
- `visual_tool_plan` 记录 skill 视觉协议如何路由到工具，例如 `brats_model` / MedSAM2 相关工具。
- `visual_task_status_counts` 不再硬编码，改为从实际分割任务明细统计。

### 2026-05-25 前端展示视觉任务明细

本轮目标：后端已经把视觉任务明细放入真实样例 response，前端也要直接展示这些信息，避免用户只能看 JSON 或无法判断分割结果是否进入诊断 Agent。

新增前端展示：

- `renderSegmentationResults`
- `renderVisualToolPlan`
- Evidence Bundle 面板新增“分割任务结果”
- Evidence Bundle 面板新增“视觉工具计划”

展示语义：

- 每个分割任务显示 `task_name`、`target`、`status`、`diagnosis_usable`、`selected_tool`、mask/overlay 路径和测量值。
- 每个视觉工具计划显示 skill 视觉任务、所需模态、路由到的工具、工具角色和 reason。
- `diagnosis_usable=true` 明确显示为“诊断可用”；缺输入或不可用的任务显示为“不用于诊断”。

### 2026-05-25 真实样例视觉证据采用/排除审计

本轮目标：真实 VLM+MedSAM2 response 不能只展示分割任务，还要明确告诉诊断 Agent 和前端：哪些视觉证据被采用，哪些因为缺输入或不可诊断被排除。

新增后端归一化：

- 从 `visual_result.visual_evidence.segmentation_results` 派生 `visual_fact_usage`
- 注入 `report.visual_fact_usage`
- 注入 `report.used_visual_facts`
- 注入 `report.excluded_visual_facts`
- 注入 `evidence_bundle.reasoning_evidence.visual_fact_usage`
- 注入 `memory_audit.visual_fact_usage`

当前语义：

- `diagnosis_usable=true` 的分割任务进入 `used`
- `diagnosis_usable=false` 或 `missing_input` 的任务进入 `excluded`
- `whole_tumor` 会携带 `whole_tumor_volume_ml` 等测量值进入诊断可用证据
- `tumor_core` / `enhancing_tumor` 等缺输入任务会作为排除证据保留，避免诊断 Agent 把缺失误认为阴性或 0

### 2026-05-25 Memory Replay 视觉证据使用摘要

本轮目标：真实样例的 `memory_replay` 不只回放“诊断 Agent 生成了报告”，还要能回放诊断 Agent 当时采用和排除了哪些视觉证据。

新增：

- `memory_replay.steps[].visual_fact_usage_summary`
- `memory_replay.steps[].used_visual_targets`
- `memory_replay.steps[].excluded_visual_targets`
- 前端 `Memory Replay` 对 `diagnosis_report` 步骤展示这些字段

当前语义：

- DiagnosisDoctorAgent replay 步骤会显示 `used_count` / `excluded_count`
- 同时显示采用目标，例如 `whole_tumor`
- 同时显示排除目标，例如 `tumor_core`、`enhancing_tumor`
- QA 场景仍保留最后一步 `follow_up_qa`，但前面的诊断回放也可追溯视觉证据使用情况

### 2026-05-25 Follow-up QA Replay 证据约束摘要

本轮目标：追问回答不能只留下自然语言文本，还要在 `follow_up_qa` replay 步骤里保留“本回答仍受哪些视觉证据约束”。

新增：

- `follow_up_qa.visual_fact_usage_summary`
- `follow_up_qa.used_visual_targets`
- `follow_up_qa.excluded_visual_targets`
- `follow_up_qa.qa_evidence_scope`
- 前端 `Memory Replay` 对 `follow_up_qa` 步骤展示这些字段

当前语义：

- QA 回答明确使用同一个 `evidence_bundle_visual_fact_usage`
- 追问时仍显示采用证据目标，例如 `whole_tumor`
- 追问时仍显示排除目标，例如 `enhancing_tumor`
- 防止 follow-up QA 在 UI 上看起来像脱离 evidence bundle 的自由回答

### 2026-05-25 QA Response 视觉契约同形化

本轮目标：真实样例的诊断 response 和 QA response 要保持同一套顶层视觉证据契约，避免追问后前端或下游只能从深层 `evidence_bundle` 里找视觉任务。

新增：

- `qa.demo_source=real_vlm_medsam2_artifact`
- `qa.visual_input_contract`
- `_build_real_vlm_medsam2_visual_input_contract`

当前语义：

- diagnosis response 和 QA response 共用同一个 visual input contract 构建 helper
- QA response 顶层保留 `segmentation_results`
- QA response 顶层保留 `visual_tool_plan`
- QA response 仍保留 `evidence_bundle`、`memory_audit`、`memory_replay` 的 evidence-bound 审计链

### TODO：病灶图对照展示

先不进入当前实现，后续前端优化时处理。

目标展示形态：

- 图像输出区展示“原图”和“病灶分割叠加/圈注图”的并排对照。
- 对浏览器可直接显示的 PNG/JPG 输入，左侧显示原图，右侧显示 overlay。
- 对 NIfTI / DICOM 等浏览器不可直接显示的原始影像，左侧优先显示导出的 slice preview，右侧显示 segmentation overlay。
- mask 路径仍属于视觉 Agent 内部工作产物，不作为患者端主要输入或主要展示。

### 2026-05-25 Skill Routing 职责边界收敛

本轮目标：明确“自动选择 skill”属于高医生/Orchestrator 的前置分诊决策，不属于 DiagnosisDoctorAgent 的诊断推理职责。

新增/调整：

- `MedScopeService` 将完整 `routing_decision` 传入 `GaoDoctorAgent`
- `GaoDoctorAgent` 在保存 `skill_memory.routing_decision` 时优先使用上游 routing decision
- 保留直接调用 `GaoDoctorAgent` 时的本地 fallback routing decision
- 新增测试确认 service handoff 和 memory 中的 routing scope 都是 `orchestrator_api`

当前语义：

- API 顶层 response 的 `routing_decision.agent_scope=orchestrator_api`
- memory audit 中 `skill_memory.routing_decision.agent_scope=orchestrator_api`
- DiagnosisDoctorAgent 不负责自动选择 skill，只消费已加载 skill、视觉证据和 evidence bundle
- GaoDoctorAgent 仍负责病例入口、视觉/诊断协同和患者解释，但不覆盖上游 skill routing 审计来源

### 2026-05-25 Memory Replay / Audit Skill Routing 归属收敛

本轮目标：前一轮已经把 `routing_decision` 保存成 Orchestrator 来源，本轮继续让 memory replay 和 audit 也明确表达这个职责边界，避免回放链路里误以为 SkillBuilderAgent 或 DiagnosisDoctorAgent 负责自动选 skill。

新增/调整：

- `memory_replay.steps[].event=skill_routing` 的 agent 从 `SkillBuilderAgent` 调整为 `GaoDoctorAgent`
- skill routing replay 步骤新增 `decision_owner`
- skill routing replay 步骤新增完整 `routing_decision`
- skill routing replay 步骤新增 `skill_builder_action`
- `memory_audit.memory_type_details.skill_memory` 新增 `routing_agent_scope`
- `memory_audit.memory_type_details.skill_memory` 新增 `routing_source`
- `memory_audit.memory_type_details.skill_memory` 新增 `skill_builder_action`
- `memory_audit.agent_io_summary.GaoDoctorAgent` 新增 `routing_decision`

当前语义：

- GaoDoctor/Orchestrator 负责根据患者描述、图像路径和症状自动选择 skill
- SkillBuilderAgent 的动作只作为 `skill_builder_action` 记录，例如 `load_existing_skill`
- DiagnosisDoctorAgent 不出现在 skill routing 步骤里
- replay 和 audit 都能证明同一件事：选 skill 是诊断前的分诊/协调动作，不是诊断推理动作

### 2026-05-25 前端 Memory Replay 展示 Skill Routing 归属

本轮目标：后端 replay/audit 已经有 skill routing 归属字段，前端 `Memory Replay` 也要能直接看见这些字段，避免只能从 JSON 或 memory 文件里判断。

新增展示字段：

- `decision_owner`
- `routing_source`
- `skill_builder_action`

当前语义：

- `decision_owner=orchestrator_api` 时，说明 skill 自动选择来自高医生/Orchestrator 分诊层
- `routing_source=auto|explicit|default` 显示本次是自动选择、显式指定还是默认流程
- `skill_builder_action=load_existing_skill|generate_guideline_skill|none` 显示 SkillBuilder 在该次路由中承担的是加载、生成还是未参与
- 前端仍不把 DiagnosisDoctorAgent 展示为 skill routing 的执行者

### 2026-05-25 真实 VLM+MedSAM2 Demo Replay 归属一致化

本轮目标：普通 MemoryManager replay 已经把 `skill_routing` 归属到 GaoDoctor/Orchestrator，但真实 VLM+MedSAM2 demo response 使用手写 replay 构造，仍显示为 `Skill Builder`。这会让演示路径和主线语义不一致。

新增/调整：

- `GET /v1/demo/real-vlm-medsam2/response` 的 `memory_replay.steps[0].agent=GaoDoctorAgent`
- `POST /v1/demo/real-vlm-medsam2/qa` 的 `memory_replay.steps[0].agent=GaoDoctorAgent`
- 真实 demo replay 第一步新增 `decision_owner=orchestrator_api`
- 真实 demo replay 第一步新增完整 `routing_decision`
- 真实 demo replay 第一步新增 `selected_vision_mode=medsam2`
- 真实 demo replay 第一步新增 `skill_builder_action=load_existing_skill`

当前语义：

- 真实 demo、标准 memory replay、前端展示三者都保持一致
- SkillBuilder 不再被展示为“自动选择 skill”的执行者
- SkillBuilder 在真实 demo 中只作为已存在 guideline skill 的加载动作记录

### 2026-05-25 前端真实样例 Fallback Replay 归属一致化

本轮目标：前端优先读取 `/v1/demo/real-vlm-medsam2/response`，但如果该完整 response 不可用，会 fallback 到分项 artifact 拼装 payload。这个 fallback 路径里仍手写 `agent: "Skill Builder"`，会在降级展示时重新引入职责归属不一致。

新增/调整：

- `buildRealVlmMedSAM2Payload` 的 fallback `memory_replay.steps[0].agent=GaoDoctorAgent`
- fallback replay 第一步新增 `decision_owner=orchestrator_api`
- fallback replay 第一步新增完整 `routing_decision`
- fallback replay 第一步新增 `selected_vision_mode=medsam2`
- fallback replay 第一步新增 `skill_builder_action=load_existing_skill`
- 静态前端测试禁止再出现 `agent: "Skill Builder", event: "skill_routing"`

当前语义：

- 正常完整 response 路径和 fallback artifact 拼装路径都保持同一职责边界
- 即使真实样例 response 不可用，前端降级展示也不会把 SkillBuilder 显示为自动选 skill 的执行者

### 2026-05-25 真实 Demo / Fallback Agent Trace 归属一致化

本轮目标：`memory_replay` 已经收敛到 GaoDoctor/Orchestrator 负责 skill routing，但真实 demo 的 `memory_audit.agents_traced` 和前端 fallback 里仍有旧标签，容易让展示层误读为 `Skill/VLM prompt` 是一个独立 Agent 或 SkillBuilder 在负责自动选 skill。

新增/调整：

- 当时阶段先把真实 VLM+MedSAM2 response 的 `memory_audit.agents_traced` 与 replay 归属拉齐，避免继续出现旧标签 `Skill/VLM prompt`
- 后续已进一步修正：`VLM Prompt` 不再作为独立 Agent 出现在 `agents_traced`，而是作为 `VisionAgent / vlm_prompt_generation` 的工具来源
- 真实 VLM+MedSAM2 QA response 复用同一条五 Agent trace，并在追问场景追加 `GaoDoctorAgent QA`
- 前端 fallback payload 的 `memory_audit.agents_traced` 同步跟随五 Agent trace
- 静态前端测试禁止继续出现旧标签 `Skill/VLM prompt`

当前语义：

- GaoDoctorAgent：入口协调、自动选 skill、追问 QA
- SkillBuilderAgent：加载或生成 guideline skill，不承担最终诊断
- VisionAgent：根据 skill finding targets 生成 VLM box prompt，调用 MedSAM2 等视觉工具，并输出病灶图和数值证据
- DiagnosisDoctorAgent：只消费 evidence bundle 和视觉证据，生成诊断报告
- MemoryManager：持久化四类 memory，并生成 evidence bundle、audit、replay

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle -v
python -m py_compile api/http_server.py tests/test_http_entrypoint.py
python -m unittest tests.test_http_entrypoint -v
python -m unittest discover -v
```

结果：`python -m unittest discover -v` 已通过 289 项。

### 2026-05-25 标准 Audit / 真实 Demo 补齐 MemoryManager Trace

本轮目标：上一轮已把真实 demo 和 fallback 的前五个职责节点统一，但标准 `MemoryManager.build_audit_summary()` 的 `agents_traced` 仍没有把 `MemoryManager` 自己列入 trace，且顺序仍是 `GaoDoctorAgent -> VisionAgent -> SkillBuilderAgent -> DiagnosisDoctorAgent`。这会削弱五 Agent 展示里 Memory Manager 的审计角色。

新增/调整：

- 标准 memory audit 的 `agents_traced` 调整为：`GaoDoctorAgent -> SkillBuilderAgent -> VisionAgent -> DiagnosisDoctorAgent -> MemoryManager`
- 真实 VLM+MedSAM2 demo response 的 `memory_audit.agents_traced` 在 Diagnosis 后追加 `MemoryManager`
- 真实 VLM+MedSAM2 QA response 的 `memory_audit.agents_traced` 保持基础 trace 后再追加 `GaoDoctorAgent QA`
- 前端真实样例 fallback payload 的 `memory_audit.agents_traced` 同步追加 `MemoryManager`

当前语义：

- GaoDoctorAgent：患者入口、自动路由、协调下游 Agent
- SkillBuilderAgent：加载/生成 skill 和 guideline evidence
- VisionAgent：调用视觉工具或 MedSAM2，输出病灶图和结构化数值证据
- DiagnosisDoctorAgent：基于 evidence bundle 做诊断推理
- MemoryManager：持久化四类 memory，并生成 evidence bundle、audit、replay

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_audit_summary_writes_fake_output_report tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle -v
python -m unittest tests.test_memory_manager tests.test_http_entrypoint -v
python -m py_compile memory/memory_manager.py api/http_server.py tests/test_memory_manager.py tests/test_http_entrypoint.py
```

结果：相关测试已通过 33 项。
补充：`python -m unittest discover -v` 已通过 289 项。

### 2026-05-25 真实 Demo Replay 补齐 Patient Intake

本轮目标：标准 `MemoryManager.build_case_replay()` 的第一步是 `patient_intake`，但真实 VLM+MedSAM2 demo 的手写 replay 直接从 `skill_routing` 开始。这样在前端演示时，真实 demo 看起来像是从中间步骤启动，和“高医生作为统一入口”的 5-Agent 语义不一致。

新增/调整：

- 真实 VLM+MedSAM2 demo response 的 `memory_replay.steps[0]` 新增 `GaoDoctorAgent / patient_intake`
- 真实 VLM+MedSAM2 QA response 复用同一条 replay 起点，再在最后追加 `follow_up_qa`
- 前端真实样例 fallback payload 同步新增 `patient_intake` 起点，避免完整 response 不可用时降级展示不一致
- HTTP 静态前端测试新增 `event: "patient_intake"` 约束

当前语义：

- 当时阶段的真实 demo replay 顺序为：`patient_intake -> skill_routing -> visual_evidence -> diagnosis_report`
- 后续已进一步修正为：`patient_intake -> skill_routing -> skill_loading -> vlm_prompt_generation -> visual_evidence -> diagnosis_report -> memory_audit`
- QA 场景在上述基础上追加 `GaoDoctorAgent / follow_up_qa`
- 自动选 skill 仍是第二步，属于高医生/Orchestrator 的分诊决策，不再作为真实 demo 的起始入口

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle -v
python -m unittest tests.test_http_entrypoint -v
python -m py_compile api/http_server.py tests/test_http_entrypoint.py
```

结果：HTTP 入口测试已通过 23 项。

### 2026-05-25 Replay 补齐 SkillBuilder Loading 步骤

本轮目标：`agents_traced` 已经包含 `SkillBuilderAgent`，但标准 replay 和真实 VLM+MedSAM2 demo replay 里只有 `GaoDoctorAgent / skill_routing`，没有单独展示 SkillBuilder 的“加载/生成 skill”职责。这样五 Agent 演示里 SkillBuilder 仍然缺一环。

新增/调整：

- 标准 `MemoryManager.build_case_replay()` 在 `skill_routing` 后新增 `SkillBuilderAgent / skill_loading`
- 真实 VLM+MedSAM2 demo response 在 `skill_routing` 后新增 `SkillBuilderAgent / skill_loading`
- 真实 VLM+MedSAM2 QA response 复用同一 replay 链路，最后再追加 `follow_up_qa`
- 前端真实样例 fallback payload 同步新增 `SkillBuilderAgent / skill_loading`
- 前端 `Memory Replay` 新增 `skill_loading` 标签和摘要字段：`action`、`selected_skill`、`skill_type`、`evidence_level`、`formal_skill_status`、`visual_protocol_status`

当前语义：

- `GaoDoctorAgent / skill_routing` 只负责选择哪个 skill、哪个 vision mode
- `SkillBuilderAgent / skill_loading` 负责加载或生成 skill，并展示 skill 质量状态
- 真实 demo 无 QA replay 顺序进一步收敛为：`patient_intake -> skill_routing -> skill_loading -> vlm_prompt_generation -> visual_evidence -> diagnosis_report -> memory_audit`

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_case_replay_returns_agent_step_timeline tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle -v
python -m unittest tests.test_memory_manager tests.test_http_entrypoint -v
python -m py_compile memory/memory_manager.py api/http_server.py tests/test_memory_manager.py tests/test_http_entrypoint.py
```

结果：MemoryManager + HTTP 入口相关测试已通过 33 项。
补充：`python -m unittest discover -v` 已通过 289 项。

### 2026-05-25 VLM Prompt 从 Agent Trace 降为 VisionAgent 工具步骤

本轮目标：`agents_traced` 用于展示五个正式 Agent，但真实 VLM+MedSAM2 demo 里仍把 `VLM Prompt` 放进 `agents_traced`，相当于出现第六个 Agent。按照当前架构，VLM prompt 生成应属于 VisionAgent 内部的工具/子步骤，不应该和 GaoDoctor、SkillBuilder、Vision、Diagnosis、Memory 并列。

新增/调整：

- 真实 VLM+MedSAM2 demo response 的 `memory_audit.agents_traced` 改为只包含五个正式 Agent：`GaoDoctorAgent -> SkillBuilderAgent -> VisionAgent -> DiagnosisDoctorAgent -> MemoryManager`
- 真实 VLM+MedSAM2 QA response 复用同一五 Agent trace，再追加 `GaoDoctorAgent QA`
- 前端真实样例 fallback payload 的 `agents_traced` 同步改为五 Agent
- `memory_replay` 中原 `VLM Prompt / visual_evidence` 步骤改为 `VisionAgent / vlm_prompt_generation`，并用 `tool=VLM Prompt` 标记具体工具来源
- 前端 `Memory Replay` 新增 `vlm_prompt_generation` 标签和摘要字段

当前语义：

- `agents_traced` 只回答“哪几个 Agent 参与了”
- `memory_replay.steps` 可以展示 Agent 内部工具步骤，例如 VisionAgent 的 VLM prompt generation
- 真实 demo 无 QA replay 顺序保持完整：`patient_intake -> skill_routing -> skill_loading -> vlm_prompt_generation -> visual_evidence -> diagnosis_report -> memory_audit`

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle -v
python -m unittest tests.test_http_entrypoint -v
python -m py_compile api/http_server.py tests/test_http_entrypoint.py
```

结果：HTTP 入口测试已通过 23 项。
补充：`python -m unittest discover -v` 已通过 289 项。

### 2026-05-25 真实 Demo Replay 补齐 Memory Audit 步骤

本轮目标：上一轮已经让真实 VLM+MedSAM2 demo 的 replay 从 `patient_intake` 开始，但 `agents_traced` 里已有 `MemoryManager`，`memory_replay.steps` 里仍没有 `MemoryManager / memory_audit` 步骤。标准 `MemoryManager.build_case_replay()` 会在诊断后展示 evidence bundle / audit 状态，真实 demo 也应保持一致。

新增/调整：

- 真实 VLM+MedSAM2 demo response 的 replay 在 `DiagnosisDoctorAgent / diagnosis_report` 后追加 `MemoryManager / memory_audit`
- 真实 VLM+MedSAM2 QA response 在 `MemoryManager / memory_audit` 后追加 `GaoDoctorAgent / follow_up_qa`
- 前端真实样例 fallback payload 同步追加 `MemoryManager / memory_audit`
- HTTP 静态前端测试新增 `agent: "MemoryManager"` 和 `event: "memory_audit"` 约束

当前语义：

- 当时阶段无 QA 的真实 demo replay 顺序为：`patient_intake -> skill_routing -> visual_evidence -> diagnosis_report -> memory_audit`
- 后续已进一步修正为：`patient_intake -> skill_routing -> skill_loading -> vlm_prompt_generation -> visual_evidence -> diagnosis_report -> memory_audit`
- QA 场景在上述基础上追加 `GaoDoctorAgent / follow_up_qa`
- `MemoryManager / memory_audit` 步骤显式展示 `evidence_bundle_status=available`、`audit_status=available` 和质量警告

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle -v
python -m unittest tests.test_http_entrypoint -v
python -m py_compile api/http_server.py tests/test_http_entrypoint.py
```

结果：HTTP 入口测试已通过 23 项。

### 2026-05-25 Goalnew 旧 Agent Trace 表述清理

本轮目标：上一轮代码已经把 `VLM Prompt` 从 `agents_traced` 中降级为 `VisionAgent / vlm_prompt_generation` 工具步骤，但 `goalnew.md` 旧阶段记录里仍有“`VLM Prompt` 作为五节点之一”或“`VLM Prompt -> VisionAgent`”的旧说法，容易误导后续讲解。

新增/调整：

- 旧的 Agent Trace 阶段记录改为“当时阶段性写法，后续已修正”
- 当前语义统一为五个正式 Agent：`GaoDoctorAgent -> SkillBuilderAgent -> VisionAgent -> DiagnosisDoctorAgent -> MemoryManager`
- 真实 demo replay 当前顺序统一写为：`patient_intake -> skill_routing -> skill_loading -> vlm_prompt_generation -> visual_evidence -> diagnosis_report -> memory_audit`
- 保留 `VLM Prompt` 作为 VisionAgent 工具来源，而不是独立 Agent

验证：

```bash
rg -n "VLM Prompt.*VisionAgent|VisionAgent/MedSAM2|五个职责节点：.*VLM Prompt|VLM Prompt：|VLM Prompt -> VisionAgent|skill_loading -> VLM Prompt|skill_routing -> VLM Prompt" goalnew.md
```

结果：只剩“后续已修正”和“工具来源”语义，没有残留把 `VLM Prompt` 当独立 Agent 的当前结论。

### 2026-05-25 待办：病灶图展示对比版

用户新需求：最终展示的病灶图不应只展示单张 overlay，而应优先展示“原图 + 分割结果 + 圈出病灶区域”的对比图，便于直观看到病灶位置与分割范围。

暂不展开实现，作为后续前端/视觉展示优化待办：

- [ ] 设计统一 image output contract：区分 `original_image_path`、`mask_path`、`overlay_path`、`comparison_path`
- [ ] VisionAgent 在生成分割结果后补充 comparison artifact
- [ ] 前端优先展示 comparison artifact，缺失时 fallback 到 overlay
- [ ] 多病灶场景需要能显示多个区域标签或编号

### 2026-05-25 VisionAgent MedSAM2 工具溯源补齐

本轮目标：上一轮已经把 `VLM Prompt` 从独立 Agent 降级为 `VisionAgent / vlm_prompt_generation` 工具步骤，但真实 demo replay 的 `VisionAgent / visual_evidence` 还没有明确标注实际分割工具。为了让展示链路完整表达“VLM 先给 bbox prompt，MedSAM2 再做分割”，需要给视觉证据步骤补齐工具溯源。

新增/调整：

- 真实 VLM+MedSAM2 demo response 的 `VisionAgent / visual_evidence` 步骤新增 `tool=MedSAM2`
- 同一步骤新增 `selected_vision_mode=medsam2`
- 真实 VLM+MedSAM2 QA response 复用同一 replay 结构
- 前端真实样例 fallback payload 同步新增上述字段
- 前端 `Memory Replay` 的 `visual_evidence` 摘要显示 `tool` 和 `selected_vision_mode`

当前语义：

- `VisionAgent / vlm_prompt_generation`：内部工具为 `VLM Prompt`，负责根据 skill 和图像生成候选框
- `VisionAgent / visual_evidence`：内部工具为 `MedSAM2`，负责根据候选框生成 mask/overlay 和数值证据
- 二者都属于 VisionAgent，不进入 `agents_traced` 的正式 Agent 列表

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle -v
python -m unittest tests.test_http_entrypoint -v
python -m py_compile api/http_server.py tests/test_http_entrypoint.py
```

结果：HTTP 入口测试已通过 23 项。

### 2026-05-25 标准 Memory Replay 补齐视觉工具溯源

本轮目标：真实 VLM+MedSAM2 demo replay 已经能展示 `VLM Prompt -> MedSAM2` 作为 VisionAgent 内部工具链，但标准 `MemoryManager.build_case_replay()` 的 `VisionAgent / visual_evidence` 步骤仍只有影像证据和分割质量，没有 `selected_vision_mode` 与工具来源。这样前端读取普通 case memory 时会比真实 demo 少一层关键审计信息。

新增/调整：

- 标准 `MemoryManager.build_case_replay()` 的 `VisionAgent / visual_evidence` 步骤新增 `selected_vision_mode`
- 同一步骤新增 `tool`
- `selected_vision_mode` 优先来自 `skill_memory.selected_vision_mode`，缺失时回退到 `skill_memory.routing_decision.selected_vision_mode`
- `tool` 优先从 `visual_evidence.visual_tool_plan` 或 `visual_evidence_bundle.visual_tool_plan` 中提取最后一个工具名
- 当缺少 visual tool plan 时，按 vision mode 回退：
  - `medsam2` -> `MedSAM2`
  - `ground_truth` -> `ground_truth_mask`

当前语义：

- 标准 replay 和真实 demo replay 都能明确回答：VisionAgent 这一步到底使用了哪种视觉模式/工具
- `ground_truth_mask` 仅表示演示或测试链路使用了参考 mask，不等同于自动分割能力
- `MedSAM2` 表示候选框/提示驱动的自动分割工具步骤

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_case_replay_returns_agent_step_timeline -v
python -m unittest tests.test_memory_manager tests.test_http_entrypoint -v
python -m py_compile memory/memory_manager.py tests/test_memory_manager.py api/http_server.py tests/test_http_entrypoint.py
python -m unittest discover -v
```

结果：MemoryManager + HTTP 入口相关测试已通过 33 项；全量单元测试已通过 289 项。

### 2026-05-25 Memory Audit Agent I/O 补齐五 Agent

本轮目标：`agents_traced` 已经统一为五个正式 Agent，但标准 `MemoryManager.build_audit_summary()` 的 `agent_io_summary` 仍只列出四个 Agent，缺少 `MemoryManager` 自己，且顺序为 `GaoDoctorAgent -> VisionAgent -> SkillBuilderAgent -> DiagnosisDoctorAgent`，与五 Agent trace 不一致。

新增/调整：

- `agent_io_summary` 顺序统一为：`GaoDoctorAgent -> SkillBuilderAgent -> VisionAgent -> DiagnosisDoctorAgent -> MemoryManager`
- `agent_io_summary` 的 key 列表现在必须与 `agents_traced` 一致
- `VisionAgent` I/O 摘要新增：
  - `selected_vision_mode`
  - `tool`
- `MemoryManager` I/O 摘要新增：
  - 输入：`case_id`、`memory_types`
  - 输出：`audit_status=available`、`evidence_bundle_status=available`

当前语义：

- `agents_traced` 说明正式参与的五个 Agent
- `agent_io_summary` 说明每个 Agent 在本病例中的最小输入/输出摘要
- `MemoryManager` 不再只是隐含产物，而是在 audit 中显式展示其审计和 evidence bundle 汇总职责

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_audit_summary_writes_fake_output_report -v
```

结果：目标 MemoryManager audit 测试已通过。

### 2026-05-25 真实 Demo Memory Audit 补齐 Agent I/O

本轮目标：标准 `MemoryManager.build_audit_summary()` 已经补齐五 Agent 的 `agent_io_summary`，但真实 VLM+MedSAM2 demo 的 `memory_audit` 仍只有 `agents_traced`，没有每个 Agent 的输入/输出摘要；前端 fallback artifact 也缺同样字段。

新增/调整：

- 真实 VLM+MedSAM2 demo response 的 `memory_audit.agent_io_summary` 补齐五 Agent：
  - `GaoDoctorAgent`
  - `SkillBuilderAgent`
  - `VisionAgent`
  - `DiagnosisDoctorAgent`
  - `MemoryManager`
- 真实 VLM+MedSAM2 QA response 在上述基础上追加 `GaoDoctorAgent QA`
- `VisionAgent` I/O 摘要新增 `selected_vision_mode=medsam2`、`tool=MedSAM2`、`prompt_tool=VLM Prompt`
- `MemoryManager` I/O 摘要新增 `audit_status=available` 与 `evidence_bundle_status=available`
- 前端真实样例 fallback payload 同步新增 `agent_io_summary`
- 前端 Memory Audit 新增 `Agent I/O` 展示区块

当前语义：

- `agents_traced` 展示参与者列表
- `agent_io_summary` 展示每个参与者的最小输入/输出摘要
- 真实 demo 与标准 case memory 的 audit 结构进一步对齐

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle -v
```

结果：目标 HTTP demo audit 测试已通过。

### 2026-05-25 标准 Demo QA 补齐 Memory Replay

本轮目标：真实 VLM+MedSAM2 QA response 已经会在 `memory_replay` 末尾追加 `GaoDoctorAgent / follow_up_qa`，但标准 demo artifact QA 只返回回答、evidence bundle 和 memory audit，不返回 replay。前端追问标准样例时会缺少可审计的追问步骤。

新增/调整：

- 标准 demo QA response 新增 `memory_replay`
- 当原始 artifact 已有 `memory_replay` 时，复用原 steps 并追加 `GaoDoctorAgent / follow_up_qa`
- 追加的 QA step 包含：
  - `question`
  - `answer`
  - `evidence_bundle_used=true`
  - `qa_source=demo_artifact`
  - `qa_evidence_scope=evidence_bundle_visual_fact_usage`
  - `visual_fact_usage_summary`
  - `used_visual_targets`
  - `excluded_visual_targets`

当前语义：

- 标准 demo QA 与真实 VLM+MedSAM2 QA 都能展示追问属于 `GaoDoctorAgent`，且回答受 evidence bundle / visual fact usage 约束
- 前端不需要再依赖 live memory refresh 才能展示 demo 追问 replay

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_demo_case_qa_answers_from_artifact_visual_fact_usage -v
```

结果：目标标准 demo QA replay 测试已通过。

### 2026-05-25 标准 Demo QA 补齐 Memory Audit QA 节点

本轮目标：标准 demo QA 已经会在 `memory_replay` 追加 `GaoDoctorAgent / follow_up_qa`，但 `memory_audit` 仍只保留原始 artifact，导致审计视图和回放视图对追问步骤不一致。

新增/调整：

- 标准 demo QA response 的 `memory_audit.agents_traced` 追加 `GaoDoctorAgent QA`
- 标准 demo QA response 的 `memory_audit.agent_io_summary` 追加 `GaoDoctorAgent QA` 输入/输出摘要
- `qa_safety` 显式记录：
  - `evidence_bundle_required=true`
  - `evidence_bundle_used=true`
  - `qa_source=demo_artifact`
  - `visual_fact_usage_summary`

当前语义：

- 标准 demo QA 与真实 VLM+MedSAM2 QA 的 audit/replay 结构进一步对齐
- 前端 Memory Audit 可以看到追问回答由 `GaoDoctorAgent QA` 基于 evidence bundle 约束产生

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_demo_case_qa_answers_from_artifact_visual_fact_usage -v
```

结果：目标标准 demo QA audit 测试已通过。

### 2026-05-25 待办：病灶图对比展示

需求记录：最终展示的病灶图不只显示单张 overlay，而应提供“原图 + 分割病灶 + 圈出/叠加结果”的对比视图，便于直观看到病灶区域。

暂不处理原因：当前优先收敛 QA、memory audit、memory replay 的可审计闭环；前端视觉展示优化放入后续小阶段。

### 2026-05-25 前端病灶图三联对比展示

本轮目标：前端 `图像输出` 面板原来只显示单张 overlay，不利于演示“原图、分割病灶、叠加对比”的视觉 Agent 结果。需要在不暴露 mask 输入、不改 Agent 主线的前提下，使用现有 `image_outputs` 做对比展示。

新增/调整：

- `renderVisualOutput()` 改为调用 `renderLesionComparison()`
- 新增 `buildVisualComparisonItems()`：
  - 原图
  - 分割病灶
  - 对比叠加
- 新增 `outputImageUrl()`，只允许浏览器可直接预览的 `output/*.png/jpg/jpeg/webp/gif` 图片进入展示
- 不再向患者界面展示 mask 路径文本；不可预览或未生成的项目只显示“未生成可预览图”
- CSS 新增 `.lesion-comparison` 三列布局，窄屏自动变为单列

当前语义：

- 视觉 Agent 的输出仍然是结构化数值 + 图像 artifact
- 前端只负责把已有 artifact 展示为对比视图
- mask 仍是视觉 Agent 内部输出，不作为患者输入项暴露

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_root_serves_interactive_frontend tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
```

结果：目标前端静态测试与 JS 语法检查已通过。

### 2026-05-25 真实 VLM+MedSAM2 补齐三联图 Preview Outputs

本轮目标：前端已经支持“原图 / 分割病灶 / 对比叠加”三联展示，但真实 BraTS VLM+MedSAM2 demo 的原图和 mask 是 NIfTI，浏览器不能直接预览，导致三联图只能稳定显示 overlay。需要在不改模型链路的前提下，为真实 demo response 补齐可预览图片路径。

新增/调整：

- 真实 VLM+MedSAM2 response 的 `image_outputs` 新增：
  - `original_preview_path`：来自 VLM prompt artifact 的 slice PNG
  - `localization_overlay_path`：来自 VLM prompt artifact 的 bbox overlay
  - `mask_preview_path`：从 NIfTI mask 生成的浏览器可预览 PNG
- `visual_input_contract.image_outputs` 与 `evidence_bundle.image_evidence.image_outputs` 同步使用 enriched `image_outputs`
- 前端三联图优先使用：
  - `original_preview_path || original_image_path`
  - `mask_preview_path || mask_path`
  - `overlay_path`

当前语义：

- NIfTI 原始文件仍保留在结构化证据中
- 前端展示使用 preview artifact，不再依赖浏览器直接读取 NIfTI
- 视觉 Agent 输出仍然保持“结构化数值 + mask/overlay/preview 图像 artifact”

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake -v
node --check web/app.js
```

结果：真实 VLM+MedSAM2 preview outputs 与前端 preview 字段消费测试已通过。

### 2026-05-25 待办：DataMind / Discovery Mode 边界完善

需求记录：

- 高医生没有找到合适 clinical guideline skill 时，应调用 SkillBuilder 尝试创建 skill
- 如果创建出的 guideline skill 仍然无法覆盖当前图像/症状/证据条件，系统必须输出“无法基于现有证据判断，需要补充检查”，不能乱诊断
- 第二种模式是 discovery mode：SkillBuilder 的 DataMind 负责提出 data-mined hypothesis，并设计/记录验证逻辑
- DataMind 输出不是正式医疗指南，不能伪装成 guideline-based skill，也不能直接进入正式临床诊断结论
- discovery mode 的输出应明确：
  - hypothesis 来源
  - teacher/gold-standard signal 是否存在
  - validation status
  - allowed outputs / forbidden clinical claims
  - 需要哪些金标准图像或独立数据验证

暂不处理原因：当前先收尾视觉展示和真实 demo 可演示链路；DataMind/discovery mode 作为后续独立小阶段处理，避免和当前前端/视觉展示收敛混在一起。

### 2026-05-25 前端 Memory Trace 补齐四类 Memory 职责说明

本轮目标：Memory Manager 已经按 `patient_memory`、`image_memory`、`skill_memory`、`reasoning_memory` 四类保存和审计，但前端 Memory Trace 只显示状态和 detail，演示时仍需要口头解释四类 memory 分别做什么。

新增/调整：

- `Memory Trace -> 四类 Memory` 区块新增职责说明：
  - `patient_memory`：患者输入
  - `image_memory`：图像与视觉证据
  - `skill_memory`：Skill / 指南 / 路由
  - `reasoning_memory`：诊断推理与报告
- 新增 `renderMemoryRoleSummary()`，只负责展示说明，不改 memory 数据结构
- 新增 `.memory-role-list` / `.memory-role-item` 样式，桌面双列、窄屏单列

当前语义：

- Memory Manager 的四类 memory 契约不变
- 前端把四类 memory 的职责直接展示出来，便于 demo 和解释系统审计链路

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
```

结果：前端静态资源测试与 JS 语法检查已通过。

### 2026-06-04 FHN Real VLM Validation 收尾与回归状态同步

本轮目标：在 FHN Evidence Protocol MVP 已经收敛的基础上，补齐 real VLM validation 后的最终回归状态，避免 `.env.local` 中的 MedSAM2 配置污染后续测试，并把 git-tracked 阶段文档的测试快照更新到最新结果。

新增/调整：

- `scripts/fhn_real_vlm_multiview_demo.py` 的 `.env.local` 加载范围限定为 `DMX_` / `KY_`。
- 新增测试确认 dry-run 不会把 `MEDSAM2_REPO_PATH`、`MEDSAM2_COMMAND_TEMPLATE` 写入当前进程环境。
- `docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md` 的验证快照从 `391 tests passed` 更新为 `409 tests passed`。
- `docs/PRE_COMMIT_AUDIT_20260604.md` 增加最新 follow-up verification 记录。

验证：

```bash
node --check web/app.js
git diff --check
python -m unittest discover -v
```

结果：JS 语法检查、diff whitespace 检查与全量 `409` 个 unittest 均通过。

当前边界：

- FHN evidence protocol / real VLM validation 主线已经形成可演示 MVP。
- real VLM 输出仍只能作为候选视觉证据，不能宣称 X 光自动确诊股骨头坏死。
- MedSAM2 / 专病分割质量仍是后续独立验证任务，不在本轮收敛中伪装完成。

### 2026-06-04 依赖入口与新环境安装说明补齐

本轮目标：README 的下一步明确要求补 `requirements.txt` 或 `pyproject.toml`，否则别人 clone 仓库后不知道如何安装 core / vision / dev 依赖。当前先补标准 `pyproject.toml`，不引入锁文件，也不把外部 MedSAM2/PyTorch 环境伪装成仓库内依赖。

新增/调整：

- 新增 `pyproject.toml`
  - `requires-python = ">=3.10"`
  - core dependency：`Pillow`
  - optional dependency groups：
    - `vision`：`numpy`、`nibabel`
    - `dev`：当前完整本地测试/demo 需要的 `numpy`、`nibabel`
    - `medsam2-wrapper`：仅包含 wrapper 侧需要的 `numpy`、`nibabel`
  - package discovery 覆盖 `agents`、`api`、`contracts`、`llm`、`memory`、`scripts`、`skill_editor`、`tools`
- 更新 `README.md` / `README.zh-CN.md`
  - 安装方式改为 `python -m pip install -e .`
  - 视觉流程改为 `python -m pip install -e ".[vision]"`
  - 完整本地测试/demo 改为 `python -m pip install -e ".[dev]"`
  - 测试快照同步为 `409 tests`
  - 下一步列表移除“补 pyproject”，改为公开安全样例、视觉后端接口、benchmark、锁文件等后续任务

验证：

```bash
python -c "import tomllib; data=tomllib.load(open('pyproject.toml','rb')); print(data['project']['name'], data['project']['requires-python'], sorted(data['project']['optional-dependencies']))"
rg -n 'There is currently no committed|还没有提交 `requirements|Ran 405 tests|补 `requirements|Add `requirements' README.md README.zh-CN.md
git diff --check
python -m pip install -e . --no-deps --dry-run
```

结果：

- `pyproject.toml` 可被标准库 `tomllib` 正常解析。
- README 中旧的“没有 requirements/pyproject”和 `405 tests` 文案已无残留。
- `git diff --check` 通过。
- `pip install -e . --no-deps --dry-run` 可生成 editable metadata，并显示 `Would install medscope-agent-0.1.0`。

### 2026-06-04 Public-safe demo fixture 补齐

本轮目标：README 的下一步要求准备一组可以公开提交或脚本生成的小型安全样例，让 fresh clone 不依赖私有 `data/external` 或 ignored `output/real` 也能跑通主线。当前先做脚本生成型 fixture，避免提交真实医疗图像。

新增/调整：

- 新增 `scripts/prepare_public_demo_fixture.py`
  - 生成 `output/fake/public_demo_fixture/synthetic_hip_xray_public_safe.png`
  - 生成 `public_demo_fixture_manifest.json`
  - manifest 内含可直接传给 `MedScopeService` 的 `service_payload`
  - 明确标记 `public_safe`、`synthetic_image`、`not_real_patient_data`、`not_clinical_ground_truth`
- 新增 `tests/test_public_demo_fixture.py`
  - 验证 fixture image / manifest 存在
  - 验证路径不依赖 `data/external` 或 `output/real`
  - 验证 manifest payload 能让 service 路由到 `femoral_head_necrosis` + `no_mask_skill`
- 更新 `README.md` / `README.zh-CN.md`
  - 增加 `python -m scripts.prepare_public_demo_fixture --output-dir output/fake/public_demo_fixture`
  - 明确该图是合成样例，不是临床图像或分割 benchmark

验证：

```bash
python -m unittest tests.test_public_demo_fixture -v
python -m scripts.prepare_public_demo_fixture --output-dir /tmp/medscope_public_fixture_check
python -m unittest tests.test_end_to_end_demo tests.test_service_entrypoint -v
git diff --check
```

结果：新增 fixture 测试通过；fixture CLI 可生成 manifest 和 PNG；end-to-end/service 相关 `37` 个测试通过；`git diff --check` 通过。

当前边界：

- 该 fixture 只验证 fresh-clone 上传、路由、skill selection 和 service payload。
- 不宣称真实病灶定位、分割质量或临床诊断能力。

### 2026-06-04 Visual Backend Contract 标准化

本轮目标：README 的下一步要求把视觉后端接口进一步标准化，区分 VLM-only、VLM+MedSAM2、专病分割模型。当前不替换模型、不改分割算法，只把 `VisualToolRegistry` 的后端 contract 显式化，并加入校验。

新增/调整：

- `VisualToolCapability` 新增：
  - `backend_type`
  - `interface_contract`
- `VisualToolRegistry` 新增：
  - `backend_contracts()`
  - `validate_backend_contracts()`
- `tools/visual_tool_registry.yaml` 为三类后端补 contract：
  - `brats_model`: `specialist_segmenter`
  - `medsam2`: `vlm_plus_segmenter`
  - `xray_fhn_detector`: `vlm_only`
- contract 明确：
  - `input_contract`
  - `output_contract`
  - `quality_gate`
  - `diagnosis_boundary`
- README / 中文 README 更新当前状态和下一步列表：视觉后端接口标准化已进入当前能力，后续重点转为 benchmark、fixture suite、部署锁文件和 quality gate。

TDD 验证：

```bash
python -m unittest tests.test_visual_tool_router.VisualToolRouterTest.test_default_registry_contains_medsam2_as_generic_candidate_segmenter tests.test_visual_tool_router.VisualToolRouterTest.test_default_registry_declares_visual_backend_interface_contracts tests.test_visual_tool_router.VisualToolRouterTest.test_registry_validator_reports_missing_backend_contract_fields -v
```

RED 结果：新增测试先因 `VisualToolCapability.backend_type`、`VisualToolRegistry.backend_contracts()`、`VisualToolRegistry.validate_backend_contracts()` 不存在而失败。

GREEN 验证：

```bash
python -m unittest tests.test_visual_tool_router -v
python -m unittest tests.test_visual_tool_router tests.test_contracts -v
python -m unittest discover -v
```

结果：VisualToolRouter 全部 `9` 个测试通过；VisualToolRouter + contracts 共 `29` 个测试通过；全量 `412` 个 unittest 通过。

当前边界：

- backend contract 只约束视觉后端输入、输出、质量门和诊断边界。
- 它不代表 MedSAM2 或 VLM 已经能稳定分割股骨头坏死病灶。
- 专病模型接入仍必须提供实际 runner、数据集 benchmark 和 quality gate 结果。

### 2026-06-04 Segmentation Benchmark 入口补齐

本轮目标：README 的下一步要求单独建立视觉分割 benchmark，不要只依赖前端效果图判断。当前先建立 manifest-driven benchmark 入口和 readiness gate，不伪造真实 Dice/IoU。

新增/调整：

- 新增 `benchmarks/segmentation/README.md`
  - 明确 benchmark 与 web demo 分离
  - 明确输出是验证 artifact，不是诊断报告
- 新增 `benchmarks/segmentation/femoral_head_necrosis/public_fixture_manifest.json`
  - 使用 public-safe synthetic fixture
  - `reference_mask_path = null`
  - `benchmark_role = smoke_fixture`
  - 明确不是 metric-ready 标注集
- 新增 `scripts/segmentation_benchmark.py`
  - 读取 manifest
  - 可选 `--prepare-fixtures` 调用 public fixture generator
  - 输出 `segmentation_benchmark_result.json` 和 `.md`
  - 无 reference mask 时输出 `metric_status = missing_reference_mask`
  - 禁止 benchmark case 混入 `web/` 或 `output/real` artifact
- 新增 `tests/test_segmentation_benchmark.py`
  - 验证默认 FHN manifest 可作为 web-demo-independent readiness gate
  - 验证缺 reference mask 时不会生成 metrics
  - 验证混入 web demo artifact 会被拒绝
- README / 中文 README 更新当前能力和下一步：下一步变为向 benchmark 加入真实标注 case。

TDD 验证：

```bash
python -m unittest tests.test_segmentation_benchmark -v
```

RED 结果：新增测试先因 `scripts.segmentation_benchmark` 不存在而失败。

GREEN / CLI 验证：

```bash
python -m unittest tests.test_segmentation_benchmark -v
python -m scripts.segmentation_benchmark --manifest benchmarks/segmentation/femoral_head_necrosis/public_fixture_manifest.json --output-dir /tmp/medscope_segmentation_benchmark_check --prepare-fixtures
```

结果：benchmark 测试 `2` 个通过；CLI 输出 `case_count=1`、`metric_ready_case_count=0`、`missing_reference_mask_count=1`。

全量回归：

```bash
python -m unittest discover -v
```

结果：`421` 个测试通过，耗时 `58.289s`。

当前边界：

- 当前 manifest 只是 smoke/readiness fixture，不是带标注的医学 benchmark。
- 不宣称任何病灶分割质量。
- 真实 Dice/IoU 需要后续加入 reference mask 和 prediction mask。

### 2026-06-04 Segmentation Benchmark Metric Gate 补齐

本轮目标：上一轮 benchmark 入口只能证明 readiness 和“没有 reference mask 时不伪造指标”。本轮补齐 metric-ready case 的质量门统计，让真实标注 case 接入时可以明确 pass/fail，但仍不能升级诊断或 formal skill。

新增/调整：

- `scripts/segmentation_benchmark.py`
  - 支持读取 manifest 级 `metric_gates`
  - metric-ready case 会输出 `quality_gate.status = pass | fail | not_configured`
  - aggregate 增加 `metric_pass_case_count` 和 `metric_fail_case_count`
  - markdown 报告展示 quality gate 状态
- `tests/test_segmentation_benchmark.py`
  - 增加 metric-ready fixture 测试
  - 验证低于阈值时进入 `metric_fail_case_count`
  - 验证即使有 metrics，也不会允许 `diagnosis_allowed` 或 `formal_skill_update_allowed`
- `benchmarks/segmentation/README.md` / README / 中文 README
  - 明确后续真实标注 case 应通过 manifest `metric_gates` 做质量门验证。

TDD 验证：

```bash
python -m unittest tests.test_segmentation_benchmark.SegmentationBenchmarkTest.test_metric_ready_case_applies_manifest_quality_gate_without_diagnosis_upgrade -v
```

RED 结果：测试先因 aggregate 缺少 `metric_pass_case_count` / `metric_fail_case_count` 失败。

GREEN 验证：

```bash
python -m unittest tests.test_segmentation_benchmark -v
```

结果：benchmark 测试 `3` 个通过。

全量回归：

```bash
python -m unittest discover -v
```

结果：`421` 个测试通过，耗时 `58.289s`。

### 2026-06-04 Segmentation Benchmark Binary Mask Evaluator 补齐

本轮目标：上一轮 benchmark 已有 readiness gate 和 metric gate，但 FHN X-ray benchmark 不能长期复用 BraTS 的 `whole_tumor_*` 多标签脑肿瘤指标。本轮补齐通用 2D binary lesion mask evaluator，让真实 FHN PNG mask case 后续能直接算 `lesion_dice` / `lesion_iou`。

新增/调整：

- 新增 `tools/binary_segmentation_evaluation_tool.py`
  - 读取 2D binary mask PNG
  - 计算 `lesion_dice`、`lesion_iou`
  - 计算 prediction/reference/intersection/union/FP/FN 像素数
  - mask 尺寸不一致时显式报错，不自动 resize
- `scripts/segmentation_benchmark.py`
  - 支持 manifest `evaluator_type`
  - `binary_mask` 走通用二值 mask evaluator
  - `brats_regions` 保留给 BraTS-style 多标签肿瘤 mask
  - 未知 evaluator type 显式报错，不静默 fallback
  - result payload 输出 `evaluator_type`
- `benchmarks/segmentation/femoral_head_necrosis/public_fixture_manifest.json`
  - 声明 `evaluator_type = binary_mask`
- 新增/扩展测试：
  - `tests/test_binary_segmentation_evaluation_tool.py`
  - `tests/test_segmentation_benchmark.py`

TDD 验证：

```bash
python -m unittest tests.test_binary_segmentation_evaluation_tool tests.test_segmentation_benchmark.SegmentationBenchmarkTest.test_manifest_can_select_binary_mask_evaluator_for_fhn_png_masks -v
```

RED 结果：测试先因 `tools.binary_segmentation_evaluation_tool` 不存在、且 manifest 声明 `binary_mask` 仍走 BraTS evaluator 而失败。

GREEN / CLI 验证：

```bash
python -m unittest tests.test_binary_segmentation_evaluation_tool tests.test_segmentation_benchmark -v
python -m scripts.segmentation_benchmark --manifest benchmarks/segmentation/femoral_head_necrosis/public_fixture_manifest.json --output-dir /tmp/medscope_binary_benchmark_check --prepare-fixtures
```

结果：局部 benchmark/evaluator 测试 `7` 个通过；CLI 输出 `evaluator_type=binary_mask`，默认 smoke fixture 仍保持 `missing_reference_mask`，不伪造 Dice/IoU。

全量回归：

```bash
python -m unittest discover -v
```

结果：`421` 个测试通过，耗时 `58.289s`。

### 2026-06-04 Segmentation Benchmark Mask Path Validation 补齐

本轮目标：真实标注 benchmark case 接入时，manifest 里如果写了 `prediction_mask_path` / `reference_mask_path`，但文件实际不存在，runner 不应该等到底层 evaluator 抛错，也不能把它当作 metric-ready。需要先在 benchmark 层给出可审计状态。

新增/调整：

- `scripts/segmentation_benchmark.py`
  - `reference_mask_path` 不存在时输出 `metric_status = missing_reference_file`
  - `prediction_mask_path` 不存在时输出 `metric_status = missing_prediction_file`
  - 缺文件时不调用 evaluator
  - aggregate 增加 `missing_reference_file_count` / `missing_prediction_file_count`
  - markdown 报告展示缺文件计数
- `tests/test_segmentation_benchmark.py`
  - 增加缺文件测试，验证 evaluator 不会被调用
  - 原 metric-ready fake evaluator 测试改为使用真实存在的临时 mask 路径
- `benchmarks/segmentation/README.md`
  - 明确 metric-ready case 的 mask 路径必须存在。

TDD 验证：

```bash
python -m unittest tests.test_segmentation_benchmark.SegmentationBenchmarkTest.test_manifest_reports_missing_mask_files_before_calling_evaluator -v
```

RED 结果：测试先因缺文件时仍调用 evaluator 而失败。

GREEN / CLI 验证：

```bash
python -m unittest tests.test_segmentation_benchmark -v
python -m scripts.segmentation_benchmark --manifest benchmarks/segmentation/femoral_head_necrosis/public_fixture_manifest.json --output-dir /tmp/medscope_path_validation_benchmark_check --prepare-fixtures
```

结果：benchmark 测试 `6` 个通过；默认 smoke fixture CLI 正常输出，并新增缺文件计数字段，当前均为 `0`。

全量回归：

```bash
python -m unittest discover -v
```

结果：`421` 个测试通过，耗时 `58.289s`。

### 2026-06-04 Segmentation Benchmark Manifest-relative Path 补齐

本轮目标：真实 benchmark manifest 通常会放在数据集目录中，里面的 `images/case.png`、`prediction/case_mask.png`、`reference/case_mask.png` 应该相对于 manifest 文件所在目录解析，而不是依赖运行脚本时的当前工作目录。

新增/调整：

- `scripts/segmentation_benchmark.py`
  - 读取 manifest 时记录 `manifest_dir`
  - case 中的相对 `image_path`、`prediction_mask_path`、`reference_mask_path` 会解析到 manifest 所在目录
  - public-safe fixture 自动生成的 image path 保持原来的输出路径，不被错误改写到 benchmark 目录下
- `tests/test_segmentation_benchmark.py`
  - 新增 manifest-relative path 测试
  - 在临时 dataset 目录中创建 `images/`、`prediction/`、`reference/`
  - manifest 只写相对路径，runner 仍应跑出 `metric_ready` 和 `quality_gate=pass`
- `benchmarks/segmentation/README.md`
  - 说明相对路径按 manifest 目录解析，便于真实 benchmark 目录迁移。

TDD 验证：

```bash
python -m unittest tests.test_segmentation_benchmark.SegmentationBenchmarkTest.test_relative_case_paths_are_resolved_from_manifest_directory -v
```

RED 结果：测试先因为相对 `reference/case_mask.png` 被按 cwd 解析而输出 `missing_reference_file`。

GREEN 验证：

```bash
python -m unittest tests.test_segmentation_benchmark -v
```

结果：benchmark 测试 `7` 个通过。

全量回归：

```bash
python -m unittest discover -v
```

结果：`421` 个测试通过，耗时 `58.289s`。

### 2026-06-04 FHN Evidence Protocol MVP 收敛交付入口补齐

本轮目标：上一轮已经把 FHN 多图 Evidence Protocol MVP 的阶段报告、交付清单和本地演示材料整理到 `output/real`，但 `output/` 被 `.gitignore` 忽略，直接同步 GitHub 时这些入口文档不会被提交。因此需要补一个可跟踪的阶段入口，保证项目首页能看见当前阶段成果。

新增/调整：

- 新增 `docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md`
  - 作为 Git 可跟踪的当前阶段入口
  - 说明 FHN 样板 evidence protocol MVP 的范围
  - 串联 skill protocol、visual execution strategy、evidence bundle、bounded diagnosis、multi-image input 和 memory audit
  - 明确 `output/real` 中的本地演示产物路径
  - 明确不能夸大的边界：不是临床诊断系统、不是稳定 X 光分割、不是严格 AP + frog-lateral benchmark
  - 给出下一轮建议 goal：真实 VLM、多体位数据、ROI/landmark 质量门控、APTR/FPTR 测量、Skill Builder proposal gate
- 更新 `README.md`
  - 在架构文档列表中加入 `docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md`
- 更新 `output/real/MedScope项目关键成果整理/README.md`
  - 增加当前阶段入口
  - 指向阶段收敛报告、交付清单、AP+lateral 样例和数据源审计
- 新增本地展示索引：
  - `output/real/MedScope项目关键成果整理/06_架构汇报与阶段文档/当前阶段入口索引_20260604.md`
  - 该文件用于本地汇报材料组织，不随 Git 默认提交

验证：

```bash
git check-ignore -v output/real/MedScope项目关键成果整理/06_架构汇报与阶段文档/当前阶段入口索引_20260604.md
git check-ignore -v docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md
rg -n "FHN_EVIDENCE_PROTOCOL_MVP_20260604|391 tests|Reporting Boundary|Recommended Next Goals" README.md docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md
git diff --check
```

结果：

- `output/real/...` 确认被 `.gitignore: output/` 忽略，适合作为本地展示材料。
- `docs/FHN_EVIDENCE_PROTOCOL_MVP_20260604.md` 未被忽略，后续 GitHub 同步可见。
- README 已链接到该阶段入口。
- `git diff --check` 通过。

当前收敛判断：

- 如果本轮目标是 FHN Evidence Protocol MVP 的演示和代码交付边界，已经可以收敛。
- 下一轮不建议继续塞到本 goal，建议单独开真实 VLM / 多体位数据 / 测量协议 goal。

### 2026-06-04 FHN Evidence Protocol MVP 提交前审计清单

本轮目标：在不直接提交、不同步服务器的前提下，明确当前 `features/hsh` 分支中哪些文件应该进入 FHN Evidence Protocol MVP 阶段提交，哪些本地演示产物不应该被默认提交。

新增：

- `docs/PRE_COMMIT_AUDIT_20260604.md`

该文档记录：

- 推荐提交标题：`feat: add FHN evidence protocol MVP`
- 应提交的文件分组：
  - README / docs / goalnew
  - 三个核心 Agent
  - API / service 边界
  - contracts / memory
  - FHN skill 与 visual tools
  - web 前端
  - 对应 unittest
- 不建议默认提交的文件：
  - `output/` 和 `outputs/`
  - 本地医学数据、DICOM/NIfTI、模型权重
  - `.env*`、API key、服务器认证信息
- 提交前验证命令：
  - `node --check web/app.js`
  - `python -m unittest discover -v`
  - `git diff --check`
- 建议的显式 `git add` 文件列表，避免使用 `git add .`

验证：

```bash
git check-ignore -v docs/PRE_COMMIT_AUDIT_20260604.md
rg -n "Recommended Commit Title|Files That Should Be Included|Files That Should Not Be Added|Verification Commands Before Commit|Suggested Staging Command" docs/PRE_COMMIT_AUDIT_20260604.md
git diff --check
```

结果：

- `docs/PRE_COMMIT_AUDIT_20260604.md` 未被忽略。
- 审计清单关键章节存在。
- `git diff --check` 通过。

### 2026-06-04 多图上传病例组验收

本轮目标：验证前端一次上传多张同一患者影像时，不再只按单张图处理，而是把多张图作为同一病例的一组影像证据传入后续 agent 主线。

验收结果：

- 使用两张本地股骨头坏死相关 X 光样例执行真实前端上传
- 前端上传状态显示：`已上传 2 张同一病例影像`
- `buildCasePayload()` 生成：
  - `image_paths`：包含两张上传后的影像路径
  - `patient_info.image_series`：包含 `image_001`、`image_002`
  - 每张影像带 `view_hint`
- 上传后报告区保持 `等待分析结果`，不会自动运行分析
- 分析前 QA 仍处于禁用状态

验收产物：

- `output/fake/frontend_runtime_checks/multi_upload_payload_check.png`
- `output/fake/frontend_runtime_checks/multi_upload_payload_check.json`

当前语义：

- 多图输入已经具备前端 payload 基础
- 后续可继续扩展为“正位/AP + 蛙式位/frog lateral”协同诊断
- 当前验收只确认输入链路，不把两张 AP 样例误解释为完整临床多体位诊断证据

### 2026-06-04 多图后端主线收敛审计

本轮目标：在前端多图 payload 验收之后，继续确认后端是否真正把多张影像作为同一病例证据组传入 agent 主线，而不是只在 UI 层支持多图。

审计结论：

- `MedScopeService._normalize_image_payload()` 会把 `image_paths` 规范化，并在缺少 `patient_info.image_series` 时自动补齐：
  - `image_001`
  - `image_002`
  - `view_hint`
- `GaoDoctorAgent._run_multi_view_no_mask_skill_visual_pipeline()` 会逐张调用 no-mask visual pipeline
- `GaoDoctorAgent._annotate_visual_result_image_context()` 会给每张图的 finding / segmentation result / visual tool plan 注入：
  - `image_id`
  - `view_hint`
  - `source_image_path`
- `GaoDoctorAgent._merge_multi_view_visual_results()` 会合并多张图的视觉证据，并记录：
  - `per_image_results`
  - `analyzed_image_count`
  - `multi_view_candidate`
- `DiagnosisAgent` 会在报告证据和 `visual_fact_usage` 中保留多视角来源，例如：
  - `骨盆正位/AP：硬化带`
  - `蛙式侧位：囊性变`
- `MemoryManager` 的 lesion gallery 会保留每个病灶图对应的 `image_id`、`view_hint` 和中文视角标签

验证：

```bash
python -m unittest tests.test_mvp_flow.MedScopeMvpFlowTest.test_gaodoctor_runs_multi_view_fhn_no_mask_pipeline_and_merges_evidence -v
python -m unittest tests.test_diagnosis_llm_workflow.DiagnosisLlmWorkflowTest.test_diagnosis_agent_preserves_multiview_source_in_report_and_fact_usage -v
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_lesion_gallery_preserves_multiview_source_context -v
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_accepts_multi_image_case_group_and_uses_first_image_as_primary tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_auto_selects_fhn_no_mask_mode_for_uploaded_hip_image_without_prompt_keywords -v
```

结果：以上多图后端主线测试均通过。

当前边界：

- 已支持“同一患者多张影像”作为一组证据传入 agent 主线
- 已支持 AP / frog lateral 级别的 view provenance 保留
- 当前仍不是精准 X 光自动诊断系统；视觉定位质量仍取决于 VLM / MedSAM2 / QC
- 下一阶段若继续做多体位协同，需要重点补真实 AP+蛙式位数据样例和跨视角一致性规则

### 2026-06-04 AP + 蛙式位真实样例数据源审计

本轮目标：在多图输入链路已经打通之后，查清当前是否已有可严谨用于展示的“同一患者 AP + 蛙式位”股骨头坏死 X 光配对样例，避免把单张 AP 图或论文面板图误包装成多体位临床数据。

新增 artifact：

- `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/多体位AP蛙式位数据源审计.md`

审计结论：

- 本地 `onfh_ap_xray_demo_set` 已有 Wikimedia Commons 来源的 AP pelvis / AP hip detail 图像。
- 本地 `fhn_multifinding_source` 有股骨头坏死相关 X 光论文图或 AP 图。
- 本轮进一步从 Wikimedia Commons 同病例页面补齐 AP detail + lateral 候选集：
  - `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/`
  - `manifest.json`
  - `ap_detail_idiopathic_onfh.jpg`
  - `lateral_idiopathic_onfh.jpg`
- 当前仍未发现明确标注为同一患者 `frog_lateral` / `lauenstein` / `蛙式位` 的原始 X 光配对文件。
- 公开论文可支持 AP + frog-leg lateral 的医学必要性，但不能直接等同于可复用原始影像数据集。

已记录的公开来源：

- Wikimedia Commons ONFH X-ray category：适合 AP 单图演示。
- `Osteonecrosis of the femoral head: diagnosis and classification systems`：支持 frog-leg lateral 对 crescent sign / subchondral fracture 的观察价值。
- `Combining frog-leg lateral view may serve as a more sensitive X-ray position in monitoring collapse in ONFH`：支持 AP + frog 共同监测 collapse。
- `The Preserved Thickness Ratio of the Femoral Head Contributes to the Collapse Predictor of Osteonecrosis`：支持 APTR / FPTR 这类多体位量化 protocol 的后续设计。

当前边界：

- 多图工程链路已经支持 AP + frog provenance。
- 真实演示数据已有一个 CC0 AP + lateral 同病例候选，但仍缺一个去标识化、同一患者、明确蛙式位的 AP + 蛙式位 X 光配对样例。
- 如果短期使用开放论文 figure panel，只能标记为 `paper_figure_demo`，不能标记为 dataset 或 benchmark。
- Service 与前端上传状态已补普通 `lateral` 侧位识别，避免 AP+lateral 候选集显示为 unknown。

验证：

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_infers_generic_lateral_view_for_multi_image_case_group -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_upload_status_summarizes_multiview_inputs -v
```

结果：Service lateral view inference 与前端 lateral view label 测试通过。

推荐下一步：

- 先用 `onfh_ap_lateral_cc0_pair` 跑一次“同病例 AP+lateral 多图输入”真实演示。
- 同时继续找或请求一组真实去标识化 AP + 蛙式位病例。
- 若暂时没有严格 AP+frog 数据，先在 skill 中补 APTR / FPTR measurement protocol 占位，标记 `requires_landmark_quality` 与 `not_usable_until_validated`。

### 2026-06-04 CC0 AP + lateral 多图 Agent 演示

本轮目标：用刚整理的 Wikimedia Commons CC0 同病例 AP + lateral 股骨头坏死 X 光候选集，跑一次可复现的多图 agent 主线演示，验证真实开放图片输入下的 Service -> GaoDoctorAgent -> evidence bundle -> DiagnosisAgent -> Memory audit 闭环。

输入数据：

- `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/ap_detail_idiopathic_onfh.jpg`
- `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/lateral_idiopathic_onfh.jpg`
- manifest：`output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/manifest.json`

演示输出：

- `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/agent_multiview_demo/README.md`
- `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/agent_multiview_demo/artifacts/summary.json`
- `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/agent_multiview_demo/artifacts/response.json`
- `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/agent_multiview_demo/artifacts/evidence_bundle.json`
- `output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/agent_multiview_demo/artifacts/audit.json`
- memory：`output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/agent_multiview_demo/memory/cases/case_20260604_153214_371735.json`

视觉候选图输出：

- `output/fake/gaodoctor_fhn_no_mask/case_20260604_153214_371735/image_001/ap_pelvis_overlay.png`
- `output/fake/gaodoctor_fhn_no_mask/case_20260604_153214_371735/image_001/ap_pelvis_1_sclerotic_band_comparison.png`
- `output/fake/gaodoctor_fhn_no_mask/case_20260604_153214_371735/image_001/ap_pelvis_2_cystic_change_comparison.png`
- `output/fake/gaodoctor_fhn_no_mask/case_20260604_153214_371735/image_002/lateral_overlay.png`
- `output/fake/gaodoctor_fhn_no_mask/case_20260604_153214_371735/image_002/lateral_1_sclerotic_band_comparison.png`
- `output/fake/gaodoctor_fhn_no_mask/case_20260604_153214_371735/image_002/lateral_2_collapse_comparison.png`

运行结果：

- `routing_decision.selected_skill = femoral_head_necrosis`
- `routing_decision.selected_vision_mode = no_mask_skill`
- `analysis_status = partial_evidence`
- `runner_call_count = 2`
- `per_image_result_count = 2`
- `provided_views = ["ap_pelvis", "lateral"]`
- `missing_views = ["frog_lateral"]`
- `finding_count = 4`
- 诊断倾向：`疑似股骨头坏死影像表现，需 MRI 和影像科复核`

边界说明：

- 输入图片是真实 CC0 开放 X 光图像。
- 本次 visual runner 是 deterministic candidate demo，不是真实 VLM，也不是临床验证分割。
- 该演示验证的是多图输入、视角 provenance、evidence bundle、诊断约束和 memory audit 主线。
- 由于 lateral 不是明确 frog-leg lateral，系统正确记录 `missing_views = ["frog_lateral"]`，没有把普通侧位冒充蛙式位。

验证：

```bash
python - <<'PY'
from pathlib import Path
import json
base = Path('output/real/MedScope项目关键成果整理/02_股骨头坏死数据与X光样例/onfh_ap_lateral_cc0_pair/agent_multiview_demo')
summary = json.loads((base / 'artifacts/summary.json').read_text(encoding='utf-8'))
bundle = json.loads((base / 'artifacts/evidence_bundle.json').read_text(encoding='utf-8'))
response = json.loads((base / 'artifacts/response.json').read_text(encoding='utf-8'))
assert summary['status'] == 'ok'
assert summary['runner_call_count'] == 2
assert summary['per_image_result_count'] == 2
assert summary['image_context']['view_coverage']['provided_views'] == ['ap_pelvis', 'lateral']
assert 'frog_lateral' in summary['image_context']['view_coverage']['missing_views']
assert bundle['image_evidence']['visual_evidence_bundle']['numeric_evidence']['finding_count'] == 4
assert response['routing_decision']['selected_skill'] == 'femoral_head_necrosis'
assert response['routing_decision']['selected_vision_mode'] == 'no_mask_skill'
PY
```

结果：演示 artifact 检查通过。

### 2026-06-04 前端患者报告收敛与 FHN no-mask 交互复验

本轮目标：真实点击 `FHN no-mask` 样例时，样例按钮只应载入病例输入，不应自动分析；点击 `运行分析` 后，右侧患者报告不应先展示 `分析路径 / 候选假设队列` 等底层 routing 信息，而应优先展示面向患者的结论、主要依据和下一步。

新增/调整：

- `runFhnNoMaskSample()` 保持只载入样例、清空旧结果、提示点击运行分析
- `renderReport()` 在存在结构化患者摘要时，只把 `patientSummaryHtml` 渲染到右侧报告
- routing / differential / evidence protocol 详情继续保留在 payload、debug 区、evidence bundle 和 memory audit 中，不作为患者主报告前缀
- 新增前端入口测试，防止患者报告重新混入 `${routingSummaryHtml}${patientSummaryHtml}`
- 重新用 Playwright 跑 FHN no-mask 真实交互，确认：
  - 点击样例后报告仍是 `等待分析结果`
  - 点击运行后状态为 `分析完成`
  - 报告以 `患者诊断摘要` 开头
  - 报告不包含 `分析路径`
  - QA 在分析完成后解锁
  - 影像发现仍可见

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_patient_friendly_routing_and_differential_sections -v
python -m unittest tests.test_http_entrypoint -v
```

运行态产物：

- `output/fake/frontend_runtime_checks/fhn_after_patient_report_fix.png`
- `output/fake/frontend_runtime_checks/fhn_patient_report_fix_check.json`

### 2026-06-04 患者摘要缺失证据字段中文化

本轮目标：上一轮 FHN no-mask 真实交互中，患者报告已经不再显示 routing 详情，但 `主要依据` 里仍可能出现 `measurement_grade_mask`、`segmentation_display` 这类内部 evidence 字段名，不适合暴露给普通用户。

新增/调整：

- 新增 `patientMissingEvidenceName()`，把内部缺失证据 key 映射成患者可读名词短语
- `patientDiagnosisEvidenceItems()` 的 `仍缺少` 列表改用患者缺失证据映射，而不是 `humanFindingName()`
- 避免出现 `仍缺少：缺少...` 的重复文案
- 保留底层字段在 evidence bundle / audit 中用于审计，不改变后端结构化证据

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_hides_internal_missing_evidence_keys_from_patient_summary -v
python -m unittest tests.test_http_entrypoint -v
```

运行态产物：

- `output/fake/frontend_runtime_checks/fhn_after_missing_key_wording_fix.png`
- `output/fake/frontend_runtime_checks/fhn_missing_key_wording_fix_check.json`

### 2026-06-04 患者摘要 Finding 去重

本轮目标：FHN no-mask 真实交互中，同一征象可能来自左右侧或多个候选区域，底层 evidence bundle 需要保留多区域事实，但患者报告的 `主要依据` 不应显示 `硬化带、硬化带` 这类重复文本，避免误解为多条独立强证据。

新增/调整：

- 新增 `uniquePatientFindingNames()`，先把 finding target 转为患者可读名称，再去重，最多展示 3 类
- `patientDiagnosisEvidenceItems()` 的 `可参考发现` 和 `仅作提示` 都改用患者展示去重结果
- 底层 evidence bundle、visual fact usage、memory audit 仍保留原始多区域/多侧别记录

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_deduplicates_patient_summary_finding_names -v
python -m unittest tests.test_http_entrypoint -v
```

运行态产物：

- `output/fake/frontend_runtime_checks/fhn_after_patient_finding_dedup.png`
- `output/fake/frontend_runtime_checks/fhn_patient_finding_dedup_check.json`

### 2026-06-04 追问 QA 患者术语清洗

本轮目标：分析完成后的追问回答已经受 evidence bundle 约束，但真实交互里 LLM 仍可能输出 `测量级定位遮罩`、`分割图像显示缺失` 等偏工程化术语。患者端回答应保持简洁、无 markdown、无内部 key、无工程术语。

新增/调整：

- `_sanitize_patient_follow_up_answer()` 增加患者术语替换：
  - `测量级定位遮罩` / `测量级 mask` -> `可用于测量的分割结果`
  - `定位遮罩` / `遮罩` -> `分割结果`
  - `分割图像显示缺失` -> `分割对照图缺失`
- 新增 LLM routing 单测，确认追问回答不会向患者暴露不友好的视觉技术术语
- 真实浏览器复验 FHN no-mask 后追问 `这张图片是股骨头坏死吗`：
  - 状态为 `已回答`
  - 无 markdown 加粗
  - 无 `measurement_grade_mask` / `segmentation_display` / `alignment_plan`
  - 无 `遮罩` 或 `分割图像显示缺失`
  - 回答保持结论优先、简洁

验证：

```bash
python -m unittest tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_follow_up_llm_answer_rewrites_patient_unfriendly_visual_terms -v
python -m unittest tests.test_llm_routing -v
```

运行态产物：

- `output/fake/frontend_runtime_checks/fhn_followup_qa_patient_terms_fix.png`
- `output/fake/frontend_runtime_checks/fhn_followup_qa_patient_terms_fix_check.json`

### 2026-06-03 前端演示状态稳定性收尾

本轮目标：收紧互动前端的病例切换和追问状态，避免用户上传新图或载入样例后仍看到上一例旧结果；实时分析未完成前不允许追问；如果视觉后端没有返回标注/分割图，影像区至少展示上传的原始输入图像。

新增/调整：

- `uploadFiles()` 上传新影像后调用 `resetViews()`，清空上一例报告、视觉输出、evidence bundle、memory audit 和 QA history。
- 上传新图时继续清除样例专用状态：
  - `useSampleMask`
  - `sampleDiseaseKey`
  - `sampleVisionMode`
  - `demoCaseSlug`
  - `realDemoMode`
- `showCaseThinking()` 现在会同步清空旧 lesion figure，并把 alignment panel 也切换为 thinking 状态。
- `updateQaControls()` 收紧 QA 控件：
  - 没有完成病例分析时不能追问。
  - 病例分析中不能追问。
  - QA thinking 中输入框锁定，发送按钮保留为“撤回”，避免重复发送。
- `renderVisualOutput()` 新增输入图像兜底展示：
  - 没有 multi-view / VLM annotation / segmentation 输出时，展示上传的 `output/...` 原图。
  - 支持 `visualBundle.image_context.image_series`、`payload.image_paths`、`payload.image_path`。
  - 多图上传时可按体位展示输入图像。

当前语义：

- 点击样例或上传新图只是准备输入，不再保留旧病例结果。
- 必须点击“运行分析”后才会生成新报告和 QA 可用状态。
- 如果视觉模型/分割模型没有产生可展示结果，用户也能在影像区域看到本次输入图像，不会误以为图片丢失。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_clears_stale_outputs_and_gates_qa_during_new_analysis tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_falls_back_to_uploaded_input_image_when_no_visual_output_exists -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_upload_status_summarizes_multiview_inputs tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_patient_friendly_routing_and_differential_sections -v
python -m unittest tests.test_http_entrypoint -v
```

结果：新增前端状态测试通过；JS 语法检查通过；相关静态前端测试通过；HTTP entrypoint `41` 个 unittest 通过。

### 2026-06-03 患者可见诊断报告压缩为三块式摘要

本轮目标：右侧诊断报告不再默认展示完整 protocol 细节，避免患者看到过多底层字段和多层 evidence 分类。患者可见报告应聚焦“结论、主要依据、下一步”，详细 evidence protocol 继续保留在 Evidence Bundle / Memory Audit 中用于审计。

新增/调整：

- `renderReport()` 在存在结构化报告时改为渲染：
  - `renderRoutingClinicalSummary(payload)`
  - `renderPatientDiagnosisSummary(payload)`
- 新增 `renderPatientDiagnosisSummary()`，固定输出三块：
  - `结论`
  - `主要依据`
  - `下一步`
- 新增辅助函数：
  - `patientDiagnosisConclusion(payload)`
  - `patientDiagnosisEvidenceItems(payload)`
  - `patientDiagnosisNextSteps(payload)`
- 三块式摘要最多展示 3 条主要依据和 3 条下一步建议。
- `renderEvidenceProtocolReport()` 保留，但不再作为右侧患者报告的默认入口。

当前语义：

- 患者看到的是短报告，不会被“影像证据 / 量化证据 / 临床风险因素 / 缺失证据”等多块细节淹没。
- 详细结构化证据仍可通过 Evidence Bundle、Memory Audit、Agent Trace 查看。
- 对 FHN X-ray 场景，报告会优先说明“证据不足，不能仅凭当前资料确认”，再列主要依据和建议 MRI / 专科复核等下一步。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_patient_friendly_routing_and_differential_sections tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_patient_diagnosis_report_as_three_block_summary -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint -v
```

结果：新增三块式患者报告测试通过；JS 语法检查通过；HTTP entrypoint `42` 个 unittest 通过。

### 2026-06-03 QA 患者回答前端兜底清洗与分段

本轮目标：后端 follow-up QA 已经会去掉 Markdown 粗体并限制长度，但前端仍直接把 answer 放进一个 `<p>`，对 demo artifact / 错误回答 / 非标准来源缺少兜底清洗。需要让追问区在患者可见层面也保持简洁、可读，不出现 `**无法确定**` 这类 Markdown 符号或长段挤在一起。

新增/调整：

- `updateQaItem()` 不再直接拼接 `<p>${answer}</p>`，改为调用 `renderPatientQaAnswer(answer)`。
- 新增 `renderPatientQaAnswer()`：
  - 使用 `.qa-answer` 容器展示追问回答。
  - 将回答拆成最多 3 段。
  - 空回答显示 `-`。
- 新增 `patientQaAnswerParagraphs()`：
  - 去除 `**` 和 `__`。
  - 压缩多余空白。
  - 优先按中文/英文句末标点切分。
  - 长句兜底按分号切分，最多展示 3 段。
- `web/app.css` 新增 `.qa-answer` 样式，让多段回答保持间距。

当前语义：

- 后端仍负责 evidence-bound QA 约束和主要安全校验。
- 前端只做患者可见格式兜底，不改变医学含义。
- QA thinking、撤回和 memory audit 更新逻辑保持不变。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_qa_answer_with_patient_safe_clean_paragraphs -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint -v
```

结果：新增 QA 前端清洗测试通过；JS 语法检查通过；HTTP entrypoint `43` 个 unittest 通过。

### 2026-06-03 前端静态资源 Cache Buster 更新

本轮目标：前端这几轮连续修改了患者报告、QA 展示、多图上传和旧结果清理，但 `web/index.html` 仍引用旧的 `app.js?v=skill-review-20260528`，浏览器或服务器部署后可能继续加载旧 JS，导致用户看到的仍是旧行为。

新增/调整：

- `web/index.html` 的 CSS 引用改为：
  - `/static/app.css?v=frontend-demo-20260603`
- `web/index.html` 的 JS 引用改为：
  - `/static/app.js?v=frontend-demo-20260603`
- 新增测试确认：
  - 根页面不再包含旧 `skill-review-20260528`
  - CSS / JS 都带当前 cache buster
  - `/static/app.css?v=frontend-demo-20260603` 可正常服务
  - `/static/app.js?v=frontend-demo-20260603` 可正常服务

当前语义：

- 本地和服务器刷新页面时更容易拿到最新前端代码。
- 不改变 API、诊断逻辑或 evidence bundle，只解决浏览器缓存导致的前端版本错位。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_root_frontend_assets_use_current_cache_buster tests.test_http_entrypoint.HttpEntrypointTest.test_root_serves_interactive_frontend -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint -v
```

结果：新增 cache buster 测试通过；JS 语法检查通过；HTTP entrypoint `44` 个 unittest 通过。

### 2026-06-03 Evidence Gateway 快照移入开发调试区

本轮目标：`Evidence Gateway 快照` 是审计/开发演示入口，不是患者病例输入样例。它之前和“载入标准样例 / VLM+MedSAM2 样例 / X 光证据不足样例 / FHN no-mask 样例”放在同一组按钮里，容易让主输入区显得混杂。

新增/调整：

- `web/index.html` 中移除病例输入区的 `Evidence Gateway 快照`按钮。
- 将同一个 `id=evidenceGatewaySnapshotButton` 的按钮移动到 `开发调试信息` details 内。
- 新增说明文字：`审计演示入口，不作为患者病例输入`。
- 保持按钮 id 不变，因此 `web/app.js` 的事件绑定和快照读取逻辑不变。
- `web/app.css` 新增 `.debug-actions`，用于调试区按钮行布局。

当前语义：

- 主输入区只保留患者/演示病例相关入口。
- Evidence Gateway 快照被明确归到开发审计入口。
- 运行时功能不变，只调整信息架构和演示边界。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_root_keeps_evidence_gateway_snapshot_inside_debug_section tests.test_http_entrypoint.HttpEntrypointTest.test_root_serves_interactive_frontend -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint -v
```

结果：新增 DOM 位置测试通过；JS 语法检查通过；HTTP entrypoint `45` 个 unittest 通过。

### 2026-06-03 前端演示收口全量回归

本轮目标：前端连续完成了多项演示层收口，包括旧结果清理、QA 锁定与撤回、输入图像兜底、三块式患者报告、QA 前端清洗、cache buster 更新，以及 Evidence Gateway 快照移入开发调试区。需要用全量测试确认这些演示层修改没有破坏后端主线、FHN evidence protocol、Service 前门、Memory/Audit 和视觉工具链。

验证：

```bash
node --check web/app.js
python -m unittest tests.test_http_entrypoint -v
python -m unittest discover -v
```

结果：前端 JS 语法检查通过；HTTP entrypoint `45` 个 unittest 通过；全量 `387` 个 unittest 通过。

### 2026-06-03 FHN Integrated Reasoning Summary

本轮目标：`DiagnosisAgent` 已经分别输出影像证据、量化证据、鉴别考虑、临床上下文、缺失证据和下一步建议，但缺少一个把这些多维 evidence 汇总成患者可读诊断边界的结构。为跑通 `skill schema -> visual execution strategy -> structured evidence_bundle -> bounded diagnosis report` 的最后一段，需要在 FHN 样板路径中增加受约束综合推理摘要。

新增/调整：

- `DiagnosisDoctorAgent._build_bounded_fhn_assessment()` 新增 `integrated_reasoning_summary`。
- 新增 `_integrated_fhn_reasoning_summary()`，汇总：
  - `imaging_support`
  - `quantitative_support`
  - `differential_considerations`
  - `clinical_risk_support`
  - `missing_evidence`
  - `modality_limitation`
  - `recommended_next_step`
- 综合摘要显式输出 `can_confirm_target_disease`，避免把探索性纹理特征、质量不足测量或临床风险因素误当作确诊依据。
- 前端 `renderEvidenceProtocolReport()` 新增“综合推理”区块，只展示患者可理解的结论边界、影像支持、量化支持、临床风险、缺失证据和下一步建议，不暴露底层执行字段。

当前语义：

- `integrated_reasoning_summary` 不重新诊断，只整合已经由 evidence bundle 和 skill protocol 约束过的字段。
- FHN X-ray 场景下，如果 `early_osteonecrosis` 缺 MRI 支持，综合摘要会保持“不能确认目标疾病”。
- `collapse` 等 measurement-only 证据必须有可用 ROI/contour/landmark 质量，质量不足时只进入不可用测量列表。
- `trabecular_blurring` 等探索性影像特征只能进入 exploratory targets，不能升级为强诊断证据。

验证：

```bash
python -m unittest tests.test_fhn_evidence_protocol.FemoralHeadEvidenceProtocolTest.test_diagnosis_report_adds_integrated_reasoning_summary_from_multidimensional_evidence -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_patient_friendly_routing_and_differential_sections -v
node --check web/app.js
python -m unittest tests.test_fhn_evidence_protocol tests.test_http_entrypoint tests.test_service_entrypoint -v
git diff --check
python -m unittest discover -v
```

结果：目标 DiagnosisAgent 测试通过；前端静态展示测试通过；JS 语法检查通过；FHN、HTTP、Service 相关 `80` 个 unittest 通过；diff 空白检查通过；全量 `378` 个 unittest 通过。

### 2026-06-03 Integrated Reasoning Evidence Bundle 审计

本轮目标：上一阶段 `DiagnosisAgent` 已经生成 `integrated_reasoning_summary`，前端报告也能展示“综合推理”。但 Evidence Bundle / Memory 审计层还不能单独追踪这个综合推理摘要，导致 QA、Memory Audit 和演示追溯时只能看到分散的影像、量化、鉴别、临床上下文字段。为完成 `bounded diagnosis report -> evidence bundle audit` 的闭环，需要把综合推理也显式进入 evidence bundle。

新增/调整：

- `MemoryManager.get_evidence_bundle()` 新增顶层 `integrated_reasoning_evidence`。
- 新增 `_integrated_reasoning_evidence()`，从 `reasoning_memory.report.integrated_reasoning_summary` 提取：
  - target disease
  - evidence status
  - supported / nonspecific / missing targets
  - strong quantitative support count
  - unusable measurement targets
  - exploratory targets
  - clinical risk factors
  - recommended next steps
- `integrated_reasoning_evidence` 明确标记：
  - `diagnosis_usable=false`
  - `diagnosis_usable_level=bounded_summary_only`
  - `can_create_new_evidence=false`
- 前端 Evidence Bundle 面板新增“综合推理审计”区块，展示综合推理边界状态，不把它混同为新的影像证据。

当前语义：

- 综合推理审计只说明 DiagnosisAgent 如何整合已有 evidence，不创建新 finding。
- 如果测量质量不足、MRI 缺失或探索性特征未验证，审计层会保留这些限制，不能升级为诊断支持。
- Memory / QA / 前端 trace 可以从同一个 evidence bundle 中追踪“报告结论是怎么被约束出来的”。

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_get_evidence_bundle_exposes_integrated_reasoning_evidence -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_patient_friendly_routing_and_differential_sections -v
node --check web/app.js
python -m unittest tests.test_memory_manager tests.test_http_entrypoint tests.test_service_entrypoint tests.test_fhn_evidence_protocol -v
git diff --check
python -m unittest discover -v
```

结果：目标 MemoryManager 测试通过；前端静态展示测试通过；JS 语法检查通过；Memory、HTTP、Service、FHN 相关 `102` 个 unittest 通过；diff 空白检查通过；全量 `379` 个 unittest 通过。

### 2026-06-03 Follow-up QA 使用 Integrated Reasoning Evidence

本轮目标：Evidence Bundle 已经有 `integrated_reasoning_evidence`，但 follow-up QA 的模板兜底仍主要读取 `reasoning_evidence.key_evidence` 和 `uncertainty`，容易把“未生成测量级 mask”“segmentation_display missing”等底层字段直接输出给患者。需要让追问回答优先使用综合推理审计给出结论边界，再用底层证据作为内部依据。

新增/调整：

- `GaoDoctorAgent._answer_diagnosis_confirmation_with_template()` 优先读取真实的 `integrated_reasoning_evidence`。
- 新增 `_has_integrated_reasoning_content()`，避免空壳 integrated evidence 误触发新模板，保持旧病例兼容。
- 新增 `_answer_diagnosis_confirmation_from_integrated_reasoning()`，用于回答“这张图是不是某病”类追问：
  - 先给出能否确诊的结论
  - 简明说明缺失证据或可参考支持证据
  - 给出下一步检查建议
  - 不输出底层 JSON key、mask 状态或 segmentation 技术字段
- LLM follow-up system prompt 增加规则：如果 evidence bundle 中存在 `integrated_reasoning_evidence`，必须优先用它判断结论边界；视觉、量化和鉴别字段只作为解释依据。

当前语义：

- QA 不重新诊断，也不看原图，只基于 evidence bundle。
- 对 FHN X-ray 问“是不是股骨头坏死”时，如果综合审计显示 early osteonecrosis 缺 MRI，回答会明确“不能仅凭 X 光确诊，需要 MRI 更可靠评估”。
- 对没有真实 integrated summary 的旧病例，仍走原来的兼容模板，不改变已有追问行为。

验证：

```bash
python -m unittest tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_follow_up_template_uses_integrated_reasoning_for_diagnosis_question -v
python -m unittest tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_uses_llm_for_follow_up_qa_with_evidence_bundle -v
python -m unittest tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_follow_up_template_answers_diagnosis_question_with_conclusion_first -v
python -m unittest tests.test_llm_routing tests.test_mvp_flow tests.test_service_entrypoint tests.test_memory_manager -v
git diff --check
python -m unittest discover -v
```

结果：目标 QA 模板测试通过；LLM follow-up 约束测试通过；旧诊断确认模板兼容测试通过；QA、MVP、Service、Memory 相关 `83` 个 unittest 通过；diff 空白检查通过；全量 `380` 个 unittest 通过。

### 2026-06-03 普通 Follow-up QA 也优先使用 Integrated Reasoning

本轮目标：上一阶段已让“这张图是不是某病”类诊断确认追问优先使用 `integrated_reasoning_evidence`，但普通追问如“下一步应该做什么”仍会落回 `key_evidence` / `uncertainty` 模板，可能重新暴露“未生成测量级 mask”“segmentation_display missing”等底层字段。需要让普通追问也优先使用综合推理审计。

新增/调整：

- `GaoDoctorAgent._answer_follow_up_with_template()` 在身份、预后、诊断确认之外，优先检查真实的 `integrated_reasoning_evidence`。
- 新增 `_answer_general_follow_up_from_integrated_reasoning()`，用于普通追问：
  - 优先输出 `recommended_next_step`
  - 结合 `missing_required_targets` 和 `evidence_status` 说明为什么证据不足
  - 不复述底层 mask / segmentation / JSON key
- 保持旧病例兼容：没有真实 integrated summary 时仍使用原始 key evidence 模板。

当前语义：

- “下一步应该做什么”会得到短回答：建议补充 MRI / 专科复核，并说明不能仅凭当前 X 光确认早期股骨头坏死。
- QA 仍不重新诊断、不看原图，只消费 evidence bundle。
- `excluded visual fact`、LLM fallback、旧病例诊断确认等路径保持原行为。

验证：

```bash
python -m unittest tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_follow_up_template_uses_integrated_reasoning_for_next_step_question -v
python -m unittest tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_follow_up_template_explains_excluded_visual_fact_reason tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_follow_up_qa_falls_back_when_llm_fails tests.test_llm_routing.LlmRoutingTest.test_gaodoctor_follow_up_template_answers_diagnosis_question_with_conclusion_first -v
git diff --check
python -m unittest tests.test_llm_routing tests.test_mvp_flow tests.test_service_entrypoint tests.test_memory_manager -v
python -m unittest discover -v
```

结果：目标普通 QA 模板测试通过；旧 QA 模板相关测试通过；diff 空白检查通过；QA、MVP、Service、Memory 相关 `84` 个 unittest 通过；全量 `381` 个 unittest 通过。

### 2026-06-03 Orchestrator 本地 Skill 边界收紧

本轮目标：修正 `selected_skill` 的语义边界。Orchestrator 生成 primary hypothesis / selected skill 只代表“应该优先检查这个方向”，不能自动等价于“本地正式 guideline skill 已存在并已加载”。

新增/调整：

- `SkillRoutingDecision` 支持由 Orchestrator 显式传入 `skill_builder_action`
- `skill_builder_action` 合法值保持受控：
  - `none`
  - `load_existing_skill`
  - `search_or_generate_skill`
- `MedScopeService` 在构建 routing decision 时先尝试加载本地 skill：
  - 本地 skill 存在：`load_existing_skill`
  - 本地 skill 缺失：`search_or_generate_skill`
  - 没有 primary hypothesis：`none`
- `skill_search_reason` 在本地 skill 缺失时明确说明：
  - 当前只是 primary clinical hypothesis
  - local skill 未找到
  - 应由 Skill Builder 搜索指南并生成 proposal skill 后再进入受约束诊断
- 新增测试覆盖：显式选择 `rare_hip_disorder` 但本地 skill 缺失时，不能标记为 `load_existing_skill`

当前语义：

- 用户不需要先指定疾病，Orchestrator 可以从症状、部位、模态生成 clinical hypotheses
- 选中 hypothesis 只是 skill routing / evidence acquisition 的入口，不是诊断结论
- 本地 skill 是否存在由 service 边界真实检查
- Skill Builder 路径和已有正式 skill 路径被明确区分

验证：

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_does_not_mark_missing_local_skill_as_loaded -v
python -m unittest tests.test_contracts tests.test_service_entrypoint -v
```

结果：新增边界测试、contracts 测试与 service 入口回归测试均已通过。

补充验证：

```bash
python -m unittest tests.test_contracts tests.test_service_entrypoint tests.test_alignment_planner tests.test_mvp_flow tests.test_http_entrypoint -v
python -m unittest discover -v
git diff --check
```

结果：相关 `97` 个 unittest、全量 `366` 个 unittest 与 diff 空白检查均已通过。

### 2026-06-03 缺失本地 Skill 的 Proposal-only 安全分支

本轮目标：上一阶段已经把 `selected_skill` 和 `load_existing_skill` 解耦，但如果本地正式 skill 缺失，Service 仍可能继续进入 GaoDoctor / Vision / Diagnosis 链路。该行为不安全，因为 hypothesis 不能替代已审核 guideline skill。

新增/调整：

- `MedScopeService.handle_request()` 在 routing 后新增早停分支：
  - `skill_builder_action == search_or_generate_skill` 时不再进入 alignment / VisionAgent / DiagnosisAgent
  - 改为调用 `SkillBuilderTool.prepare_skill(..., persist=False)`
  - 返回 `intent=skill_proposal`
  - 返回 `analysis_status=skill_proposal_required`
- proposal-only 响应明确包含：
  - `skill_builder_proposal`
  - `formal_update_allowed=false`
  - `diagnosis_allowed=false`
  - `review_required=true`
  - `missing_evidence: formal_guideline_skill`
  - 下一步建议：搜索指南、人工审核、审核后再运行视觉与诊断
- `prepare_skill(..., persist=False)` 复用现有 Skill Builder 能力：
  - 有指南来源时可生成 guideline candidate
  - 无指南来源时退回 data-mined hypothesis
  - 均不写入正式 `skills/*.yaml`
- HTTP `/v1/medscope` 现在会把该 proposal-only payload 原样返回给前端。
- 前端 `renderReport()` 新增 `renderSkillProposalReport()`：
  - 在普通 `reply_to_patient` 之前渲染 proposal 报告区
  - 显示“Skill Builder 候选草案”
  - 明确提示“不能直接诊断”
  - 显示 `formal_update_allowed` 和 `diagnosis_allowed`

当前语义：

- Orchestrator 可以生成 clinical hypothesis。
- 本地正式 skill 存在时，才进入标准 evidence acquisition 和 diagnosis。
- 本地正式 skill 缺失时，只能进入 proposal-only Skill Builder 路径。
- proposal skill 不能污染正式 skill 库，不能直接驱动诊断。

验证：

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_returns_proposal_only_skill_when_local_skill_is_missing -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_post_medscope_returns_skill_proposal_when_selected_skill_is_missing -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_skill_proposal_report_before_plain_reply -v
python -m unittest tests.test_service_entrypoint tests.test_http_entrypoint tests.test_contracts tests.test_mvp_flow tests.test_guideline_skill_builder -v
python -m unittest discover -v
node --check web/app.js
git diff --check
```

结果：目标 service / HTTP / frontend 测试通过，相关 `115` 个 unittest 通过，全量 `369` 个 unittest、JS 语法检查与 diff 空白检查均已通过。

### 2026-06-03 本地 Skill 缺必要 Protocol 的 Proposal-only 分支

本轮目标：上一阶段已处理“本地 skill 文件不存在”的情况，但还需要处理“本地 skill 文件存在、却缺少可执行/可推理 protocol”的情况。这样的 skill 不能因为文件存在就进入 VisionAgent / DiagnosisAgent。

新增/调整：

- `MedScopeService._skill_builder_action_for()` 现在不只检查文件是否存在，还检查本地 skill 是否具备必要 protocol。
- 向后兼容的有效 protocol 字段包括：
  - `visual_protocol`
  - `imaging_evidence_protocol`
  - `quantitative_evidence_protocol`
  - `differential_diagnosis_protocol`
  - `clinical_context_protocol`
  - `integrated_reasoning_protocol`
- 本地 skill 存在但这些 protocol 全部缺失时：
  - `skill_builder_action=search_or_generate_skill`
  - `skill_search_reason` 明确说明 `local skill is missing required protocol`
  - Service 进入 proposal-only 分支
  - 不调用 GaoDoctor / VisionAgent / DiagnosisAgent
- 本地正式 skill 已具备 `visual_protocol` 或多维 protocol 时，仍保持 `load_existing_skill`，不影响 FHN、glioma、IPF 等现有主线。

当前语义：

- “本地有文件”不再等于“可以诊断”。
- “本地有可执行/可推理 protocol 的正式 skill”才允许进入 evidence acquisition 和 diagnosis。
- 缺 protocol 的 skill 只能进入 Skill Builder proposal / review 路径，避免后续 agent 基于空壳 skill 误推理。

验证：

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_returns_proposal_only_when_local_skill_lacks_protocol -v
python -m unittest tests.test_service_entrypoint tests.test_http_entrypoint tests.test_contracts tests.test_mvp_flow tests.test_guideline_skill_builder tests.test_visual_protocol_validator -v
python -m unittest discover -v
node --check web/app.js
git diff --check
```

结果：目标测试通过，相关 `124` 个 unittest 通过，全量 `370` 个 unittest、JS 语法检查与 diff 空白检查均已通过。

### 2026-06-03 本地 Visual Protocol 有效性校验

本轮目标：上一阶段只检查本地 skill 是否具备 protocol 字段，但 `visual_protocol` 可能是空壳或结构无效。无效 protocol 不能驱动 VisionAgent / DiagnosisAgent。

新增/调整：

- `MedScopeService` 接入 `VisualProtocolValidator`。
- 对 `guideline_based` 且包含 `visual_protocol` 的本地 skill 做严格校验。
- 无效 `visual_protocol` 会进入 proposal-only 分支：
  - `skill_builder_action=search_or_generate_skill`
  - `skill_search_reason` 包含 `invalid visual_protocol`
  - 不调用 GaoDoctor / VisionAgent / DiagnosisAgent
- 有效 `visual_protocol` 的正式 skill 仍保持 `load_existing_skill`。
- 只包含多维 evidence protocol 的 skill 后续需要进一步校验；不能再只按“字段存在”视为可执行。

当前语义：

- “本地有 protocol 字段”不等于“可执行”。
- `visual_protocol` 必须通过 contract validator，才能进入标准证据采集和诊断链路。
- 无效 protocol 只允许进入 Skill Builder proposal / review，不允许形成诊断。

验证：

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_returns_proposal_only_when_local_visual_protocol_is_invalid -v
python -m unittest tests.test_service_entrypoint tests.test_http_entrypoint tests.test_mvp_flow tests.test_visual_protocol_validator tests.test_guideline_skill_builder -v
python -m unittest discover -v
node --check web/app.js
git diff --check
```

结果：目标测试通过，相关 `105` 个 unittest 通过，全量 `371` 个 unittest、JS 语法检查与 diff 空白检查均已通过。

### 2026-06-03 多维 Evidence Protocol Readiness 校验

本轮目标：上一阶段已经校验 `visual_protocol`，但多维 evidence protocol 也不能只看字段是否存在。尤其是 FHN 样板中，`quantitative_evidence_protocol`、`differential_diagnosis_protocol`、`clinical_context_protocol` 等字段只能作为诊断推理的补充约束，不能单独驱动 VisionAgent 做视觉证据采集。

新增/调整：

- `MedScopeService._skill_protocol_readiness()` 新增多维 protocol readiness 判定。
- 新增 `_validate_imaging_evidence_protocol()`：
  - `imaging_evidence_protocol` 必须是非空 dict
  - 必须声明 `disease_target`
  - 必须包含非空 `finding_targets`
  - 每个 finding target 必须声明 `target` 和 `execution_mode`
- 本地 skill 如果只有 supporting protocols：
  - `quantitative_evidence_protocol`
  - `differential_diagnosis_protocol`
  - `clinical_context_protocol`
  - `integrated_reasoning_protocol`
  则不能进入标准诊断链路，会进入 proposal-only 分支。
- 无效 `imaging_evidence_protocol` 会进入 proposal-only 分支：
  - `skill_builder_action=search_or_generate_skill`
  - `skill_search_reason` 包含 `invalid imaging_evidence_protocol`
  - 不调用 GaoDoctor / VisionAgent / DiagnosisAgent
- 有效 `visual_protocol` 或有效 `imaging_evidence_protocol` 才能让本地正式 skill 进入 evidence acquisition 和 diagnosis。

当前语义：

- “多维 protocol 字段存在”不等于“可诊断”。
- `imaging_evidence_protocol` 是视觉证据采集的最低可执行入口；supporting protocols 只能补充量化、鉴别、临床上下文和综合推理。
- FHN 当前仍以 `visual_protocol` + `imaging_evidence_protocol` 为主线，探索性量化和鉴别协议只作为受约束诊断报告的边界，不冒充稳定自动诊断能力。

验证：

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_returns_proposal_only_when_local_evidence_protocol_is_invalid -v
python -m unittest tests.test_service_entrypoint tests.test_http_entrypoint tests.test_fhn_evidence_protocol tests.test_visual_protocol_validator tests.test_mvp_flow -v
python -m unittest discover -v
node --check web/app.js
git diff --check
```

结果：目标测试通过，相关 `99` 个 unittest 通过，全量 `372` 个 unittest、JS 语法检查与 diff 空白检查均已通过。

### 2026-06-03 Clinical Hypotheses Routing 输出

本轮目标：用户不应该必须先说“我怀疑自己是股骨头坏死”，系统才能选择 FHN skill。Orchestrator 需要根据症状、部位和图像线索先生成候选 clinical hypotheses，再选择 primary skill 进入证据采集。

新增/调整：

- `SkillRoutingDecision` 新增 `clinical_hypotheses` 字段。
- `MedScopeService._build_routing_decision()` 现在会输出：
  - primary hypothesis
  - differential candidates
  - 每个 hypothesis 的 role / status / reason
- FHN 场景中：
  - `左髋疼痛 + X 光/hip image` 会生成 `femoral_head_necrosis` primary hypothesis
  - 同时保留 `osteoarthritis_or_degenerative_hip_disease`、`post_traumatic_change`、`developmental_dysplasia_related_degeneration` 等 differential candidates
  - reason 明确说明这是 symptom + image clues 触发的 evidence acquisition，不是诊断
- `clinical_hypotheses` 会随 routing decision 进入 Service / HTTP / Memory 主线，不改变 DiagnosisAgent 的边界。

当前语义：

- Orchestrator 负责 hypothesis generation / skill routing，不负责最终诊断。
- `selected_skill` 仍是本轮证据采集的 primary skill。
- `clinical_hypotheses` 是候选假设队列，用来解释为什么查这个 skill，以及为什么保留鉴别方向。
- DiagnosisAgent 仍然只基于 evidence_bundle + skill protocol 推理，不重新选 skill、不直接看原图。

验证：

```bash
python -m unittest tests.test_contracts.ContractBoundaryTest.test_skill_routing_decision_contract_preserves_hypothesis_and_initial_evidence_status tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_auto_selects_femoral_head_skill_from_hip_xray_clues -v
python -m unittest tests.test_contracts tests.test_service_entrypoint tests.test_http_entrypoint tests.test_memory_manager tests.test_mvp_flow -v
```

结果：目标测试通过，相关 `118` 个 unittest 通过。

### 2026-06-03 Clinical Hypotheses 前端与 Memory Audit 展示

本轮目标：上一阶段 `routing_decision` 已经输出 `clinical_hypotheses`，但前端和 memory audit 仍主要展示 `primary_hypothesis` / `differential_skill_candidates`，容易让用户误以为系统只是在选择一个疾病标签。本轮把候选假设队列显式接到展示层和审计层。

新增/调整：

- 前端 `renderRoutingClinicalSummary()` 新增“候选假设队列”展示。
- 每个 hypothesis 显示：
  - role：优先检查 / 鉴别保留
  - disease key 的中文病种名
  - status 的患者可读标签
  - reason
- 前端明确提示：这不是诊断结论，只是根据症状、部位和影像类型决定先检查哪些 evidence。
- `MemoryManager.build_audit_summary()` 的 `memory_type_details.skill_memory` 新增：
  - `clinical_hypotheses`
  - `clinical_hypotheses_count`
- Memory Audit 因此能追溯 Orchestrator 当时生成了哪些候选假设，以及哪些只是鉴别保留。

当前语义：

- 前端展示不改变诊断逻辑。
- Orchestrator 的候选假设队列只解释 skill routing 和 evidence acquisition。
- DiagnosisAgent 仍只使用 evidence_bundle + skill protocol 做受约束推理。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_patient_friendly_routing_and_differential_sections tests.test_memory_manager.MemoryManagerQueryTest.test_build_audit_summary_writes_fake_output_report -v
python -m unittest tests.test_http_entrypoint tests.test_memory_manager tests.test_service_entrypoint tests.test_mvp_flow -v
```

结果：目标测试通过，相关 `98` 个 unittest 通过。

### 2026-06-03 DiagnosisAgent 消费 Clinical Hypotheses 边界

本轮目标：`clinical_hypotheses` 已经进入 Orchestrator、前端和 Memory Audit，但 DiagnosisAgent 的结构化报告还没有显式说明这些 hypothesis 只是 routing/evidence acquisition 边界，不是诊断证据。本轮把该上下文接入报告。

新增/调整：

- `DiagnosisDoctorAgent.generate_report()` 新增可选 `routing_decision` 参数。
- GaoDoctor 主线调用 DiagnosisAgent 时传入 `routing_decision`。
- DiagnosisAgent 在报告中附加 `clinical_hypotheses_assessment`：
  - `primary_hypothesis`
  - `differential_retained`
  - `hypotheses_are_diagnosis=false`
  - role 说明：候选假设只指导 skill routing 和 evidence acquisition
- `target_disease_assessment` 新增轻量边界字段：
  - `routing_role=primary_hypothesis`
  - `routing_boundary=Primary hypothesis must be supported by evidence_bundle before diagnosis.`

当前语义：

- DiagnosisAgent 仍不重新选 skill，不直接看原图。
- clinical hypotheses 不会被计入 `supports_target_disease`。
- 主假设评估仍由 evidence_bundle 的可用证据、缺失证据和质量门控决定。
- 鉴别保留仍是 bounded differential considerations，不开放式改诊断。

验证：

```bash
python -m unittest tests.test_fhn_evidence_protocol.FemoralHeadEvidenceProtocolTest.test_diagnosis_report_preserves_routing_hypotheses_without_treating_them_as_evidence -v
python -m unittest tests.test_fhn_evidence_protocol tests.test_diagnosis_llm_workflow tests.test_mvp_flow tests.test_service_entrypoint -v
```

结果：目标测试通过，相关 `77` 个 unittest 通过。

### 2026-06-03 前端报告展示 Clinical Hypotheses Assessment

本轮目标：DiagnosisAgent 已经把 `clinical_hypotheses_assessment` 写入结构化报告，但前端报告区还需要把它解释成患者/演示者能理解的内容，而不是只在底层 JSON 或 Memory Audit 中出现。

新增/调整：

- `renderEvidenceProtocolReport()` 读取 `report.clinical_hypotheses_assessment`。
- 新增 `renderClinicalHypothesesAssessment()` 展示：
  - 主假设：当前优先检查的疾病方向。
  - 鉴别保留：Orchestrator 保留的 bounded differential candidates。
  - 明确边界：这些候选假设不是诊断证据，最终判断必须来自 evidence bundle 和指南约束。
- 该展示只解释分析路径，不改变 DiagnosisAgent 的推理结果，也不把 hypothesis 升级为 evidence。

当前语义：

- 用户不需要先指定“我怀疑股骨头坏死”，系统可以根据症状、部位和图像生成候选假设。
- 前端会同时展示“为什么优先查这个 skill”和“为什么还保留鉴别方向”。
- 主假设仍不是诊断结论；诊断结论必须受 evidence bundle、缺失证据、质量门控和模态限制约束。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_patient_friendly_routing_and_differential_sections -v
python -m unittest tests.test_http_entrypoint tests.test_fhn_evidence_protocol tests.test_mvp_flow -v
node --check web/app.js
git diff --check
python -m unittest discover -v
```

结果：前端静态展示目标测试通过；相关 `65` 个 unittest 通过；JS 语法检查通过；`git diff --check` 通过；全量 `373` 个 unittest 通过。

### 2026-06-03 Prompt Clinical Context 进入 FHN 证据链路

本轮目标：FHN skill 已经定义 `clinical_context_protocol`，DiagnosisAgent 也能按 `patient_info` 提取风险因素；但真实前端/HTTP 使用时，用户常把“长期激素、饮酒、外伤史”等病史直接写在患者描述里。如果 Service 不把这些自由文本线索保留到 `patient_info.clinical_context`，后续 DiagnosisAgent、MemoryManager 和 QA 的 evidence bundle 就无法稳定使用这部分临床上下文。

新增/调整：

- `MedScopeService._normalize_image_payload()` 在进入 GaoDoctor 前统一规范化 `patient_info`。
- 新增 `_attach_prompt_clinical_context()`：
  - 当用户描述中包含激素、饮酒、外伤、血液病、自身免疫等 FHN 风险线索时，将原始描述保存到 `patient_info.clinical_context`。
  - 标记 `clinical_context_source=patient_message`，便于 Memory / QA 审计来源。
  - 如果调用方已经显式提供 `risk_factors`、`history` 或 `clinical_context`，不覆盖已有结构化输入。
- 该步骤只保留临床上下文，不改变 Orchestrator 的诊断边界，也不把风险因素当作影像确诊证据。

当前语义：

- 用户 prompt 中的风险因素可以被 DiagnosisAgent 的 `clinical_context_protocol` 使用。
- 风险因素只能改变 suspicion / pre-test likelihood，不能替代影像证据确诊。
- MemoryManager 的 evidence bundle 会通过 `patient_context.patient_info` 继续保留这段上下文，供后续 QA 在 evidence-bound 范围内回答。

验证：

```bash
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_preserves_prompt_clinical_context_for_fhn_diagnosis -v
python -m unittest tests.test_service_entrypoint tests.test_fhn_evidence_protocol tests.test_memory_manager -v
node --check web/app.js
git diff --check
python -m unittest discover -v
```

结果：目标测试通过；Service、FHN protocol、Memory 相关 `58` 个 unittest 通过；JS 语法检查通过；`git diff --check` 通过；全量 `374` 个 unittest 通过。

### 2026-06-03 Clinical Context Evidence Bundle 显式化

本轮目标：上一阶段已经把用户 prompt 中的风险因素保留到 `patient_info.clinical_context`，但 evidence bundle 里仍主要通过 `patient_context.patient_info` 间接暴露。为了符合多维 evidence protocol，临床上下文需要作为独立证据区块被 Memory / QA / 前端审计直接读取。

新增/调整：

- `MemoryManager.get_evidence_bundle()` 新增顶层 `clinical_context_evidence`。
- 新增 `_clinical_context_evidence()` 汇总：
  - `evidence_type=clinical_context`
  - `source`
  - `raw_context`
  - `provided_risk_factors`
  - `missing_clinical_context`
  - `can_confirm_without_imaging`
  - `diagnosis_usable=false`
  - `diagnosis_usable_level=risk_modifier_only`
- 前端 Evidence Bundle 面板新增“临床上下文证据”区块，直接展示风险因素、缺失病史和“仅风险修饰”级别。

当前语义：

- clinical context 是 evidence bundle 的一类证据，但不是影像证据，也不是确诊证据。
- 风险因素可用于解释 suspicion level，不能绕过视觉 evidence、missing evidence 和 modality limitation。
- QA 后续读取 evidence bundle 时，可以直接看到临床上下文证据来源与边界，而不需要解析底层 `patient_info`。

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_get_evidence_bundle_exposes_clinical_context_evidence -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_patient_friendly_routing_and_differential_sections -v
python -m unittest tests.test_memory_manager tests.test_service_entrypoint tests.test_fhn_evidence_protocol -v
python -m unittest tests.test_memory_manager tests.test_service_entrypoint tests.test_fhn_evidence_protocol tests.test_http_entrypoint -v
node --check web/app.js
git diff --check
python -m unittest discover -v
```

结果：目标测试通过；Memory、Service、FHN protocol 相关 `59` 个 unittest 通过；加入 HTTP/前端后相关 `98` 个 unittest 通过；JS 语法检查通过；`git diff --check` 通过；全量 `375` 个 unittest 通过。

### 2026-06-03 Differential Reasoning Evidence Bundle 显式化

本轮目标：`differential_considerations` 已经由 DiagnosisAgent 生成，并在报告中展示；但它还没有作为 evidence bundle 的独立证据区块存在。这样 QA / Memory Audit / 前端 Evidence Bundle 只能从诊断报告间接读取鉴别逻辑，不符合多维 evidence protocol 中 `differential_reasoning` 应独立可审计的要求。

新增/调整：

- `MemoryManager.get_evidence_bundle()` 新增顶层 `differential_reasoning_evidence`。
- 新增 `_differential_reasoning_evidence()` 汇总：
  - `evidence_type=differential_reasoning`
  - `primary_hypothesis`
  - `routing_evidence_status`
  - `differential_skill_candidates`
  - `considerations`
  - `diagnosis_usable=false`
  - `diagnosis_usable_level=bounded_differential_only`
  - `can_replace_primary_diagnosis=false`
- 前端 Evidence Bundle 面板新增“鉴别推理证据”区块，展示主假设、routing evidence status、鉴别候选和不可替代主诊断的边界。

当前语义：

- 鉴别推理证据用于解释“为什么保留替代解释 / 非特异征象 / 证据不足”。
- 它不是开放式新诊断，也不能因为存在候选鉴别就替代 primary hypothesis。
- DiagnosisAgent 仍不看原图、不重新选 skill；该 evidence 只来自 routing decision 和受约束报告。

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_get_evidence_bundle_exposes_differential_reasoning_evidence -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_patient_friendly_routing_and_differential_sections -v
python -m unittest tests.test_memory_manager tests.test_service_entrypoint tests.test_fhn_evidence_protocol tests.test_http_entrypoint -v
node --check web/app.js
git diff --check
python -m unittest discover -v
```

结果：目标测试通过；Memory、Service、FHN、HTTP/前端相关 `99` 个 unittest 通过；JS 语法检查通过；`git diff --check` 通过；全量 `376` 个 unittest 通过。

### 2026-06-03 Quantitative Evidence Bundle 显式化

本轮目标：`quantitative_evidence_summary` 已经由 DiagnosisAgent 生成，但 evidence bundle 仍主要通过 `image_evidence.measurements` 和 report 间接暴露量化证据。为满足 `quantitative_evidence_protocol` 的安全链路，需要把 measurement evidence 与 exploratory image-feature quantification 明确拆出来，供 Memory / QA / 前端审计直接使用。

新增/调整：

- `MemoryManager.get_evidence_bundle()` 新增顶层 `quantitative_evidence`。
- 新增 `_quantitative_evidence()` 汇总：
  - `measurement_items`
  - `exploratory_features`
  - `strong_quantitative_support_count`
  - `can_confirm_diagnosis`
  - `diagnosis_usable_level`
- 汇总优先读取 report 的 `quantitative_evidence_summary`，缺失时从 `visual_evidence_bundle.evidence_items` / `findings` 回填。
- 前端 Evidence Bundle 面板新增“量化证据审计”区块，展示强量化支持计数、可诊断级别、measurement 数量和 exploratory feature 数量。

当前语义：

- `measurement_items` 只有在 `diagnosis_usable=true` 且 `measurement_usable=true` 时，才可能计入强量化支持。
- `exploratory_features` 只能作为探索性提示，不能直接升级为确诊证据。
- X-ray 场景下 ROI/contour/landmark 质量不足时，量化证据会保持 `not_usable_or_exploratory`。

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_get_evidence_bundle_exposes_quantitative_evidence -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_patient_friendly_routing_and_differential_sections -v
python -m unittest tests.test_memory_manager tests.test_service_entrypoint tests.test_fhn_evidence_protocol tests.test_http_entrypoint -v
node --check web/app.js
git diff --check
python -m unittest discover -v
```

结果：目标测试通过；Memory、Service、FHN、HTTP/前端相关 `100` 个 unittest 通过；前端 JS 语法检查通过；diff 空白检查通过；全量 `377` 个 unittest 通过。

### 2026-06-03 Readiness 错误报告区结构化展示

本轮目标：真实上传或实时分析触发 MedSAM2 / API readiness 错误时，前端不能只把长错误塞到顶部状态栏；需要在影像发现、诊断报告、Evidence Bundle、Memory Audit 区域显示可读的结构化提示，让用户知道是部署配置问题，不是病例分析卡住。

新增/调整：

- `postMedScope()` / `postMedScopeQa()` 在 HTTP 非 2xx 时不再只抛普通字符串错误，而是通过 `buildApiError()` 保留：
  - `error.apiPayload`
  - `error.apiStatus`
  - 原始 `error_type`
  - `action_items`
  - `routing_decision`
  - `medsam2_configuration`
- 新增 `renderStructuredErrorPanel()`：
  - `medsam2_not_ready` 显示为“部署检查未通过”
  - `action_items` 显示为“需要处理”
  - `routing_decision` 显示本次自动选择的 skill / hypothesis / evidence status
  - `medsam2_configuration` 显示关键配置是否存在
- `renderCaseError()` 优先渲染结构化错误卡片。
- 运行分析失败时，顶部状态栏只显示短提示，例如“分割后端未配置，详情见报告区”，避免长串底层配置文本挤占界面。

当前语义：

- 这不是新的诊断逻辑，只是把已有 readiness payload 做成患者/演示者可读的 UI。
- 后端仍然通过 `503 + error_type=medsam2_not_ready` 表达部署未就绪。
- 报告区会说明“这是部署检查未通过”，不会误导成医学诊断失败或病例阴性。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_renders_readiness_errors_as_structured_panels -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint -v
python -m unittest discover -v
```

结果：新增结构化错误展示测试通过，JS 语法检查通过，HTTP 入口 `36` 个测试通过，全量 `364` 个 unittest 通过。

### 2026-06-03 多体位上传状态摘要

本轮目标：前端已支持一次上传多张同一患者影像，但上传完成提示只列文件名，不直观展示系统推断出的体位。对于股骨头坏死演示中的“骨盆正位 + 蛙式侧位”组合，用户需要在运行分析前看到每张图将作为哪一个体位进入 evidence bundle。

新增/调整：

- 新增 `formatUploadedImageSeriesStatus(uploaded)`。
- 上传完成后，`uploadFiles()` 不再只显示文件名列表，而是显示：
  - `image_001`
  - 推断体位：`骨盆正位/AP`、`蛙式侧位`、`未知体位`
  - 上传后的文件名
- 体位推断复用现有 `inferViewHint()` 和 `imageViewLabel()`，与后续 `patient_info.image_series` / evidence bundle 展示保持一致。
- 单图上传也显示 `image_001 · 体位 · 文件名`，避免用户不知道当前图像被当作什么视角处理。

当前语义：

- 这只是输入区可解释性增强，不改变后端路由或视觉执行。
- 多图仍作为同一病例影像组输入；后端继续由 `image_series` 和 `view_hint` 组织多体位 evidence。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_app_js_upload_status_summarizes_multiview_inputs -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint -v
```

结果：新增多体位上传状态测试通过，JS 语法检查通过，HTTP 入口 `37` 个测试通过。

### 2026-06-03 Orchestrator Hypothesis Generation 语义修正

本轮目标：修正“患者必须先说怀疑某个病才会调用对应 skill”的误解。更合理的流程是：患者只描述症状和上传图像时，Clinical Orchestrator 先生成 clinical hypothesis / differential candidates，再查本地 skill 库，已有 skill 就直接加载，缺失时才进入 Skill Builder / Guideline proposal。

新增/调整：

- `SkillRoutingDecision` 新增 `requires_evidence_acquisition` 状态。
- 普通“左髋疼痛 + X 光”不再把路由状态写成 `insufficient`，而是：
  - `primary_hypothesis=femoral_head_necrosis`
  - `selected_skill=femoral_head_necrosis`
  - `routing_evidence_status=requires_evidence_acquisition`
  - `differential_skill_candidates` 包含退变、外伤后改变、发育性髋臼发育不良相关退变等受约束候选方向
- 只有出现退变、外伤、感染、肿瘤样骨破坏等明确替代解释线索时，路由状态才升级为 `requires_differential_review`。
- `skill_search_reason` 区分：
  - 用户明确怀疑 FHN：作为 primary clinical hypothesis 加载已有 skill
  - 用户未指定疾病：基于 hip pain + hip X-ray 生成候选假设并加载已有 skill
- AlignmentPlanner 收紧了“早期/排除意图”判断：
  - “X 光能不能判断早期股骨头坏死”仍触发证据不足安全门
  - “帮我看看 X 光有没有问题”不再因为泛化的“有没有”而阻断 VisionAgent 采集候选征象
- 前端 `routingEvidenceStatusLabel()` 增加“需要先采集证据”中文标签。

当前语义：

- Orchestrator 负责 hypothesis generation / skill routing，不直接诊断。
- Skill Builder 不是每次都调用；已有正式 skill 时优先加载。
- VisionAgent 不是自由诊断，而是在已有 skill 和 execution strategy 下采集结构化证据。
- DiagnosisAgent 仍只消费 evidence bundle + guideline skill 做受约束推理。

验证：

```bash
python -m unittest tests.test_contracts.ContractBoundaryTest.test_skill_routing_decision_contract_preserves_hypothesis_and_initial_evidence_status tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_persists_orchestrator_routing_scope_to_skill_memory tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_auto_selects_femoral_head_skill_from_hip_xray_clues tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_routes_fhn_as_hypothesis_not_default_positive_disease tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_marks_fhn_with_degenerative_clues_for_bounded_differential_review tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_builds_insufficient_alignment_for_early_fhn_xray_question -v
```

结果：目标 Orchestrator / Alignment 路由测试已通过。

### 2026-05-26 Phase B 真实 non-reference MedSAM2 评测收敛

本轮目标：把真实 VLM box prompt + MedSAM2 分割结果纳入 Phase B 统一视觉证据评测，同时保持 Evidence Gateway 的 candidate-only 安全边界。

新增/调整：

- `scripts/vision_evidence_eval_summary.py`
  - 修正真实 auto-eval 成功时 `medsam2_ready` 仍显示为 `false` 的汇总问题。
  - 当 `auto_eval_status=ok` 且 `real_medsam2_call_attempted=true` 时，统一视为 MedSAM2 runner 已可用。
  - 非 reference auto-eval 成功后保留 `metrics`、`failure_types`、`mask_path`、`overlay_path`。
  - 成功但指标不稳定的 non-reference 结果进入 `non_reference_metric_review` candidate item。
  - candidate-only 边界不变：`formal_skill_updated=false`、`formal_guideline_updated=false`、`diagnosis_report_updated=false`。
- `tests/test_vision_evidence_eval_summary.py`
  - 新增真实成功 auto-eval 的 ready 状态测试。
  - 新增 successful non-reference metric failures 进入 candidate-only queue 的测试。
- 重新生成：
  - `output/fake/vision_evidence_eval_summary.json`
  - `output/fake/vision_evidence_eval_summary.md`
  - `output/fake/vision_evidence_candidate_queue.json`
  - `output/fake/vision_evidence_candidate_queue.md`
  - `output/fake/vision_evidence_reviewer_notes_template.json`
  - `output/fake/vision_evidence_candidate_validation_gate.json`
  - `output/fake/vision_evidence_candidate_validation_gate.md`
- 更新：
  - `output/fake/vision_evidence_eval_plan.md`
  - `output/fake/dual_layer_architecture_validation_roadmap.md`

当前真实 non-reference 结果：

- `auto_eval_status=ok`
- `medsam2_ready=true`
- `prompt_source=vision_model_bbox`
- `reference_mask_used=false`
- `reference_mask_role=evaluation_only`
- `whole_tumor_dice=0.8325`
- `tumor_core_dice=0.3932`
- `enhancing_tumor_dice=0.0`
- `whole_tumor_false_positive_component_count=19`
- 输出 mask：`output/fake/brats_phase_b_non_reference_auto_eval/brats2021_00030_medsam2_auto_mask.nii.gz`
- 输出 overlay：`output/fake/brats_phase_b_non_reference_auto_eval/brats2021_00030_medsam2_auto_overlay.png`

当前解释：

- 这一步已经证明真实主线可跑通：`VLM 根据 skill 定位 box -> MedSAM2 分割 -> 输出 mask/overlay -> 计算数值指标 -> Evidence Gateway 写入 candidate review`。
- 这一步不能宣称临床级分割已解决；tumor core 波动、enhancing tumor 为 0 和 false positive component 多，说明视觉协议/模型仍需后续复核。
- `candidate_count=11`，新增的 3 项是 non-reference metric review：`low_quality_mask`、`over_segmentation`、`under_segmentation`。

验证：

```bash
python -m unittest tests.test_vision_evidence_eval_summary.VisionEvidenceEvalSummaryTest.test_summary_marks_successful_non_reference_medsam2_run_ready tests.test_vision_evidence_eval_summary.VisionEvidenceEvalSummaryTest.test_candidate_queue_routes_successful_non_reference_metric_failures_as_candidate_only -v
```

结果：新增 TDD 测试已通过。

### 2026-05-26 Evidence Gateway 当前验证快照

本轮目标：把“临床证据流水线 + Evidence Gateway”从叙事进一步变成可检查 artifact，方便组会直接回答当前系统已经验证到哪里、不能宣称什么。

新增/调整：

- 新增 `scripts/evidence_gateway_snapshot.py`
  - 读取 `output/fake/vision_evidence_eval_summary.json`
  - 读取 `output/fake/vision_evidence_candidate_queue.json`
  - 读取 `output/fake/vision_evidence_candidate_validation_gate.json`
  - 汇总成一页 Evidence Gateway snapshot。
- 新增 `tests/test_evidence_gateway_snapshot.py`
  - 覆盖真实视觉链路、candidate-only gate、可宣称/不可宣称边界。
- 生成：
  - `output/fake/evidence_gateway_snapshot.json`
  - `output/fake/evidence_gateway_snapshot.md`
- 更新：
  - `output/fake/medscope_demo_runbook.md`
  - `output/fake/standard_demo_walkthrough.md`

当前 snapshot 结论：

- 推荐口径：`Clinical Evidence Pipeline + Agentic Runtime / Evidence Gateway`
- 明确不是五个并列 Agent：`not_five_parallel_agents=true`
- 当前状态：`demonstrable_but_not_clinical_grade`
- 真实视觉链路：`prompt_source=vision_model_bbox`，`auto_eval_status=ok`，`medsam2_ready=true`
- 关键指标：`whole_tumor_dice=0.832534`，`tumor_core_dice=0.393187`，`enhancing_tumor_dice=0.0`
- Candidate gate：`candidate_count=11`，`non_reference_metric_review_count=3`，`promotion_status=blocked`，`formal_update_allowed=false`

可以宣称：

- 真实 VLM + MedSAM2 视觉链路已经可演示。
- Evidence Gateway 能把未验证视觉问题阻断在 candidate-only 阶段。
- 失败模式和人工复核项已被结构化记录到 candidate queue。

不能宣称：

- 通用医学图像分割已经达到临床级。
- self-evolving 会自动修改正式 guideline skill。
- non-reference candidate metric review 可以作为正式诊断依据。

验证：

```bash
python -m unittest tests.test_evidence_gateway_snapshot -v
```

结果：新增 snapshot 测试已通过。

### 2026-05-26 Evidence Gateway Snapshot 接入前端/API

本轮目标：上一轮已经生成 `evidence_gateway_snapshot` 文件，但组会演示还需要能从前端直接打开，避免现场手动找 JSON/Markdown。

新增/调整：

- `api/http_server.py`
  - 新增只读 demo 路由：`GET /v1/demo/evidence-gateway-snapshot`
  - 路由只读取 `output/fake/evidence_gateway_snapshot.json`
  - 不重新计算、不改正式 skill、不改诊断报告。
- `web/index.html`
  - 样例按钮区新增 `Evidence Gateway 快照`。
- `web/app.js`
  - 新增 `fetchEvidenceGatewaySnapshot()`
  - 新增 `renderEvidenceGatewaySnapshot(snapshot)`
  - 新增 `runEvidenceGatewaySnapshot()`
  - 快照页展示：
    - `overall_status=demonstrable_but_not_clinical_grade`
    - `not_five_parallel_agents=true`
    - 真实 VLM+MedSAM2 视觉链路状态
    - key metrics
    - candidate gate 和 candidate type counts
    - can claim / cannot claim
- `tests/test_http_entrypoint.py`
  - 新增 demo route 测试
  - 扩展前端静态测试，确认按钮、fetch、render 和 route 字符串存在。

当前前端演示语义：

- `真实 VLM+MedSAM2 样例`：展示病例级视觉证据、报告、evidence bundle 和 memory audit。
- `Evidence Gateway 快照`：展示系统级验证状态，说明真实视觉链路可演示，但 non-reference 结果仍被 candidate-only gate 阻断，不能作为正式诊断依据。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_evidence_gateway_snapshot_demo_is_served_from_output_fake tests.test_http_entrypoint.HttpEntrypointTest.test_root_serves_interactive_frontend tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint tests.test_evidence_gateway_snapshot -v
```

结果：新增路由测试、前端静态测试、JS 语法检查和相关回归测试已通过。

### 2026-05-26 新病种 guideline skill 端到端验证

本轮目标：状态矩阵建议下一步做“新病种 guideline skill 端到端验证”，用于证明 Skill Builder / Guideline Component 不绑定 FHN/BraTS。当前选择 IPF HRCT 作为新病种。

新增/调整：

- 新增 `scripts/new_disease_guideline_skill_validation.py`
  - 复用 `run_ipf_guideline_skill_demo()` 生成 `idiopathic_pulmonary_fibrosis_hrct` guideline skill。
  - 复用 `run_ipf_visual_demo()` 构造 HRCT manifest dry-run，并生成 IPF visual evidence bundle skeleton。
  - 生成统一 summary，明确 guideline skill、visual protocol、evidence bundle 和 safety boundary。
- 新增 `tests/test_new_disease_guideline_skill_validation.py`
  - 覆盖 guideline skill 生成、visual protocol valid、evidence bundle skeleton、diagnosis blocked。
- 生成：
  - `output/fake/new_disease_guideline_skill_validation/new_disease_guideline_skill_validation.json`
  - `output/fake/new_disease_guideline_skill_validation/new_disease_guideline_skill_validation.md`
- 更新：
  - `output/fake/dual_layer_architecture_validation_roadmap.md`
  - `output/fake/medscope_mvp_group_meeting_status.md`
  - `output/fake/dual_layer_architecture_brief.md`

当前 IPF 验证结果：

- `disease_key=idiopathic_pulmonary_fibrosis_hrct`
- `skill_type=guideline_based`
- `visual_protocol_status=valid`
- `required_image_views=["HRCT chest", "thin-section chest CT"]`
- `segmentation_targets=["honeycombing_candidate", "reticulation_candidate", "traction_bronchiectasis_candidate", "fibrosis_candidate"]`
- `evidence_bundle_schema=ipf_visual_evidence_bundle.v1`
- `anatomy_mask_role=anatomy_mask_not_fibrosis_ground_truth`
- `present_finding_count=0`
- `unassessed_target_count=4`
- `diagnosis_allowed=false`

可以宣称：

- 新病种 guideline skill 可以生成。
- visual protocol 可以通过 validator。
- visual protocol 可以驱动 evidence bundle skeleton。
- 缺失视觉证据会被显式标记为 unassessed。

不能宣称：

- 不能从当前 dry-run bundle 诊断 IPF。
- 不能把 lung mask 当作 fibrosis ground truth。
- 不能宣称所有指南都能无审核自动生成正式 skill。

验证：

```bash
python -m unittest tests.test_new_disease_guideline_skill_validation -v
```

结果：新增 IPF 新病种端到端验证测试已通过。

### 2026-05-26 Phase B 视觉评测失败项接入 Candidate-only Queue

本轮目标：上一阶段已经生成 `vision_evidence_eval_summary`，但视觉失败项和 no-mask 人工复核项还停留在 summary / next action 中。现在把它们接入底层 Agentic Runtime / Evidence Gateway 的 candidate-only 链路，用于说明 stop hooks / reflection hooks / self-evolving queue 是“候选制”，不会自动改正式医疗 skill。

新增/调整：

- `scripts/vision_evidence_eval_summary.py` 新增 `build_vision_evidence_candidate_queue(...)`
- CLI 新增 `--write-candidate-queue`
- 新增输出：
  - `output/fake/vision_evidence_candidate_queue.json`
  - `output/fake/vision_evidence_candidate_queue.md`
- queue 中写入 8 个 candidate item：
  - BraTS under-segmentation 视觉协议复核 2 项
  - FHN low-quality mask / merged independent findings 视觉协议复核 2 项
  - FHN no-mask manual review label 4 项
- 所有 item 都是：
  - `validation_status=pending_review`
  - `allowed_action=candidate_review_only`
  - `formal_update_allowed=false`
- runtime safety 明确：
  - `candidate_artifacts_only=true`
  - `formal_skill_updated=false`
  - `formal_guideline_updated=false`
  - `diagnosis_report_updated=false`

架构语义：

- 这一步不是新增医疗 Agent，而是补齐底层 gateway 能力。
- 底层 gateway 类似 Claude Code / Codex 的工作区机制：通过 skill 文件、共享 artifact、工具约束、stop/reflection hooks 和 candidate validation gate 管理主 Agent。
- self-evolving 只沉淀候选失败模式、候选视觉协议复核和候选人工标签；正式 guideline skill 仍必须经过人工或数据集验证后才能升级。

验证：

```bash
python -m unittest tests.test_vision_evidence_eval_summary.VisionEvidenceEvalSummaryTest.test_candidate_queue_routes_failures_and_manual_review_as_candidate_only -v
python -m unittest tests.test_vision_evidence_eval_summary -v
python -m scripts.vision_evidence_eval_summary --write-candidate-queue
```

结果：候选队列单测、视觉评测 summary 测试和真实 Phase B artifact 生成均已通过。下一步是补充 reviewer note 回写机制，让人工复核结果仍先进入 candidate validation gate，而不是直接写正式 skill。

### 2026-05-26 Phase B Reviewer Note 回写与 Validation Gate

本轮目标：上一阶段已把视觉评测失败项写入 candidate-only queue，但还缺少人工 reviewer note 回写入口和对应 validation gate。现在补齐“人工复核 -> validation gate -> 仍不写正式 skill”的闭环。

新增/调整：

- `scripts/vision_evidence_eval_summary.py` 新增：
  - `build_vision_evidence_reviewer_notes_template(...)`
  - `build_vision_evidence_candidate_validation_gate(...)`
- CLI 新增：
  - `--write-reviewer-notes-template`
  - `--write-validation-gate`
  - `--reviewer-notes <path>`
- 新增输出：
  - `output/fake/vision_evidence_reviewer_notes_template.json`
  - `output/fake/vision_evidence_candidate_validation_gate.json`
  - `output/fake/vision_evidence_candidate_validation_gate.md`
- reviewer notes template 当前包含 8 个 item，全部为 `pending_review`，不伪造人工结论。
- validation gate 当前结果：
  - `item_count=8`
  - `reviewed_count=0`
  - `pending_count=8`
  - `promotion_decision.status=blocked`
  - `promotion_decision.reason=candidate_items_require_human_or_dataset_review`
  - `formal_update_allowed=false`

安全边界：

- reviewer note 只允许更新 candidate validation state。
- 即使 reviewer note 填成 `accepted`、`rejected` 或 `needs_revision`，本阶段仍不直接写正式 skill。
- 正式 guideline skill promotion 需要单独显式审批，不由 Phase B validation gate 自动执行。
- 诊断报告不会因为 candidate review 被重写。

验证：

```bash
python -m unittest tests.test_vision_evidence_eval_summary.VisionEvidenceEvalSummaryTest.test_candidate_validation_gate_records_reviewer_notes_without_formal_update -v
python -m unittest tests.test_vision_evidence_eval_summary.VisionEvidenceEvalSummaryTest.test_reviewer_notes_template_preserves_pending_human_review_without_fake_labels -v
python -m scripts.vision_evidence_eval_summary --write-candidate-queue --write-reviewer-notes-template --write-validation-gate
```

结果：reviewer note 回写测试、模板测试和真实 Phase B validation artifact 生成均已通过。下一步可以做人工复核填写，或进入 Phase B 的非 reference VLM prompt + MedSAM2 真实视觉闭环复测。

### 2026-05-26 Phase B 非 Reference VLM Prompt 真实复测

本轮目标：把 Phase B 从 reference-mask 回归和 FHN no-mask 样例推进到“真实 VLM 根据 BraTS FLAIR 图像生成非 reference box prompt”，并让该 prompt 进入 MedSAM2 auto-eval gate。

执行结果：

- 先读取 `docs/API_ROUTE_LOG.md`，确认当前 active route 为 DMX，模型为 `gemini-3.5-flash`。
- 第一次在沙箱内运行真实 VLM prompt 因网络解析失败返回结构化 `vlm_not_ready`。
- 随后用已授权网络权限重新运行：
  - `python -m scripts.brats_vlm_prompt_demo --image data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz --slice-index 100 ...`
- 真实 VLM 输出成功：
  - `status=ok`
  - `prompt_source=vision_model_bbox`
  - `boxes=[[50, 130, 130, 195]]`
  - `reference_mask_used=false`
  - `real_call_attempted=true`
- 输出 artifacts：
  - `output/fake/brats_phase_b_vlm_prompt/summary.json`
  - `output/fake/brats_phase_b_vlm_prompt/BraTS2021_00030_flair_slice_100.png`
  - `output/fake/brats_phase_b_vlm_prompt/BraTS2021_00030_flair_vision_model_prompt.json`
  - `output/fake/brats_phase_b_vlm_prompt/BraTS2021_00030_flair_vision_model_prompt_overlay.png`

MedSAM2 gate：

- 使用真实 VLM prompt 运行：
  - `python -m scripts.brats_medsam2_auto_eval --manifest data/external/brats_manifest.json --case-id brats2021_00030 --prompt output/fake/brats_phase_b_vlm_prompt/BraTS2021_00030_flair_vision_model_prompt.json --output-dir output/fake/brats_phase_b_non_reference_auto_eval`
- 当前结果：
  - `status=not_ready`
  - `prompt_source=vision_model_bbox`
  - `real_call_attempted=false`
  - `reference_mask_role=evaluation_only`
  - 阻塞点：`MEDSAM2_COMMAND_TEMPLATE` / MedSAM2 runner 未配置
- 输出 artifact：
  - `output/fake/brats_phase_b_non_reference_auto_eval/summary.json`

代码和 summary 收敛：

- `scripts/vision_evidence_eval_summary.py` 支持读取：
  - `output/fake/brats_phase_b_vlm_prompt/summary.json`
  - `output/fake/brats_phase_b_non_reference_auto_eval/summary.json`
- `vision_evidence_eval_summary.json` 新增 `non_reference_attempts`：
  - `non_reference_attempt_count=1`
  - `non_reference_prompt_ok_count=1`
  - `non_reference_auto_eval_ready_count=0`
- `vision_evidence_candidate_queue.json` 新增 `runtime_configuration_review`：
  - `source_warning_code=medsam2_not_ready`
  - `candidate_count=9`
- `vision_evidence_candidate_validation_gate.json` 当前：
  - `item_count=9`
  - `pending_count=9`
  - `promotion_decision.status=blocked`

验证：

```bash
python -m unittest tests.test_vision_evidence_eval_summary.VisionEvidenceEvalSummaryTest.test_summary_includes_non_reference_vlm_prompt_and_medsam2_gate_status -v
python -m unittest tests.test_vision_evidence_eval_summary.VisionEvidenceEvalSummaryTest.test_candidate_queue_routes_failures_and_manual_review_as_candidate_only -v
python -m scripts.vision_evidence_eval_summary --write-candidate-queue --write-reviewer-notes-template --write-validation-gate
```

结果：真实 VLM non-reference prompt 已生成并进入 auto-eval gate；当前唯一阻塞点是配置真实 MedSAM2 runner，不是 prompt 或 evidence gateway 结构问题。

### 2026-05-26 双层架构汇报口径收敛

本轮目标：回应“五个 Agent 像是为了分 Agent 而分”的质疑，把对外表述从“五个并列 Agent”收敛为更合理的双层架构。

新增/调整：

- 核心架构表述改为：
  - 上层：`Clinical Evidence Pipeline`
    - `Clinical Orchestrator`
    - `Vision Evidence Agent`
    - `Diagnosis Reasoning Agent`
    - 条件触发的 `Skill Builder / Guideline Component`
    - 基础设施性质的 `Memory / Audit Layer`
  - 下层：`Agentic Runtime / Evidence Gateway`
    - `Skill Gateway`
    - `Shared Artifact Workspace`
    - `Contract / Policy Guards`
    - `Tool Router`
    - `Stop Hooks / Reflection Hooks`
    - `Self-evolving Queue`
    - `Candidate Validation Gate`
- 明确 `Skill Builder` 不是每轮并列参与的诊断 Agent，而是在缺少合适 skill 或需要加载/生成 guideline skill 时触发。
- 明确 `MemoryManager` 不是业务诊断 Agent，而是 memory/audit/runtime 基础设施。
- 加入 Claude Code / Codex 类比：底层 gateway 通过 skill、共享文件、工具权限和 hooks 管理复杂任务。
- 明确医疗安全边界：self-evolving 只能生成候选 memory、候选规则或 candidate skill patch；验证前不能自动改正式 `guideline_based` skill。

已更新文档：

- `docs/DUAL_PATH_AGENT_FRAMEWORK.md`
- `docs/architecture/boundaries.md`
- `output/fake/standard_demo_walkthrough.md`
- `output/fake/mvp_status_by_agents.md`
- `output/fake/five_agent_virtual_mainline_ppt/README.md`
- `output/fake/five_agent_virtual_mainline_ppt/medscope_five_agent_virtual_mainline_notes.md`

当前汇报一句话：

> MedScope 不是为了分 Agent 而分 Agent，而是把临床诊断拆成一条受指南约束的证据流水线，并在底层引入类似 Claude Code / Codex 的 agentic runtime，通过 skill 分发、文件 artifact 共享、工具约束、stop hooks、memory audit 和候选规则验证门，让每次推理都可追踪、可复核、可回滚。

### 2026-05-26 双层架构一页式汇报入口

本轮目标：上一轮已经把“双层架构”写入核心文档和 walkthrough，但现场汇报仍缺一个最先打开的总览入口。新增一页式说明，避免组会时在多个长文档之间跳转。

新增/调整：

- 新增 `output/fake/dual_layer_architecture_brief.md`
  - 一句话定位
  - 双层结构图
  - 为什么不是一个大 Agent
  - Claude Code / Codex 类比边界
  - 当前 runtime trace artifact 表
  - 原“五个 Agent”到新架构的映射
  - 现场答辩短句
  - 当前汇报顺序
- `output/fake/medscope_demo_runbook.md`
  - 文件开头加入该一页式说明入口。
- `output/fake/standard_demo_walkthrough.md`
  - 文件开头加入该一页式说明入口。

当前推荐打开顺序：

1. `output/fake/dual_layer_architecture_brief.md`
2. 前端标准 demo
3. Evidence Pipeline Trace
4. Memory Audit / Replay

### 2026-05-26 双层架构 Mermaid 图

本轮目标：一页式说明已经能回答“为什么不是为了分 Agent 而分”，但还缺可直接复制到组会 Markdown、论文草稿或 PPT 工具里的架构图。

新增/调整：

- 新增 `output/fake/dual_layer_architecture_diagrams.md`
  - 双层总架构图
  - 端到端证据流 sequence diagram
  - Runtime Gateway Trace 图
  - 旧五 Agent 到新双层架构映射图
- `output/fake/dual_layer_architecture_brief.md`
  - 增加配套 diagrams 文件入口。
  - 汇报顺序中加入“需要展示架构图时打开 diagrams 文件”。
- `output/fake/medscope_demo_runbook.md`
  - 文件开头加入 diagrams 文件入口。
- `output/fake/standard_demo_walkthrough.md`
  - 文件开头加入 diagrams 文件入口。

当前推荐打开顺序：

1. `output/fake/dual_layer_architecture_brief.md`
2. `output/fake/dual_layer_architecture_diagrams.md`
3. 前端标准 demo
4. Evidence Pipeline Trace
5. Memory Audit / Replay

### 2026-05-26 双层架构答辩 Q&A

本轮目标：brief 和 diagrams 已经能说明架构，但组会中老师更可能追问“是不是包装、多 Agent 有什么创新、怎么验证、self-evolving 是否危险”。新增一份集中答辩材料。

新增/调整：

- 新增 `output/fake/dual_layer_architecture_defense_qa.md`
  - 是否为了分 Agent 而分
  - 创新点在哪里
  - 和普通 RAG / 多 Agent 的区别
  - 为什么诊断 Agent 不直接看原图
  - Vision Agent 分割不准怎么办
  - Skill Builder 自动找指南是否可靠
  - self-evolving 是否会乱改指南
  - Memory Manager 是否多余
  - 当前 MVP 完成了什么、不能夸大什么
  - 下一步如何验证
  - 论文命名建议
- `output/fake/dual_layer_architecture_brief.md`
  - 增加 Q&A 文件入口。
- `output/fake/medscope_demo_runbook.md`
  - 文件开头加入 Q&A 文件入口。
- `output/fake/standard_demo_walkthrough.md`
  - 文件开头加入 Q&A 文件入口。

当前推荐打开顺序：

1. `output/fake/dual_layer_architecture_brief.md`
2. `output/fake/dual_layer_architecture_diagrams.md`
3. `output/fake/dual_layer_architecture_defense_qa.md`
4. 前端标准 demo
5. Evidence Pipeline Trace
6. Memory Audit / Replay

### 2026-05-26 双层架构论文方法章节草稿

本轮目标：当前已有 brief、diagrams 和 defense Q&A，但还缺一份可直接迁移到开题报告或论文方法章节的草稿。

新增/调整：

- 新增 `output/fake/dual_layer_architecture_paper_method_draft.md`
  - Suggested Title
  - Abstract Draft
  - Core Contributions
  - System Overview
  - Data Flow
  - Safety Design
  - Current MVP Scope
  - Evaluation Plan
  - Positioning Against Related Systems
  - Recommended Figure Captions
  - Recommended Wording Boundary
  - Short Method Summary
- `output/fake/dual_layer_architecture_brief.md`
  - 增加 method draft 文件入口。
- `output/fake/medscope_demo_runbook.md`
  - 文件开头加入 method draft 文件入口。
- `output/fake/standard_demo_walkthrough.md`
  - 文件开头加入 method draft 文件入口。

当前材料包打开顺序：

1. `output/fake/dual_layer_architecture_brief.md`
2. `output/fake/dual_layer_architecture_diagrams.md`
3. `output/fake/dual_layer_architecture_defense_qa.md`
4. `output/fake/dual_layer_architecture_paper_method_draft.md`
5. 前端标准 demo
6. Evidence Pipeline Trace
7. Memory Audit / Replay

### 2026-05-26 双层架构验证路线图

本轮目标：method draft 中已有 Evaluation Plan，但仍偏概括。新增一份更可执行的验证路线图，把系统从“会讲”推进到“能验证”。

新增/调整：

- 新增 `output/fake/dual_layer_architecture_validation_roadmap.md`
  - 验证总目标
  - 三条验证线总览
  - 视觉证据质量验证
  - 指南 skill 质量验证
  - Evidence-bounded reasoning 验证
  - Runtime Gateway 与 self-evolving 安全验证
  - Phase A-E 阶段化执行计划
  - 推荐汇报口径
  - 当前不能宣称 / 可以宣称的边界
- `output/fake/dual_layer_architecture_brief.md`
  - 增加 validation roadmap 入口。
- `output/fake/dual_layer_architecture_paper_method_draft.md`
  - 增加详细验证路线图引用。
- `output/fake/medscope_demo_runbook.md`
  - 文件开头加入 validation roadmap 入口。
- `output/fake/standard_demo_walkthrough.md`
  - 文件开头加入 validation roadmap 入口。

当前材料包打开顺序：

1. `output/fake/dual_layer_architecture_brief.md`
2. `output/fake/dual_layer_architecture_diagrams.md`
3. `output/fake/dual_layer_architecture_defense_qa.md`
4. `output/fake/dual_layer_architecture_paper_method_draft.md`
5. `output/fake/dual_layer_architecture_validation_roadmap.md`
6. 前端标准 demo
7. Evidence Pipeline Trace
8. Memory Audit / Replay

### 2026-05-26 Phase A Demo Audit

本轮目标：根据 validation roadmap 的 Phase A，先复核现有标准 demo 与视觉评测 artifact，生成一份客观审计报告，说明哪些可以支撑双层架构主张，哪些静态 artifact 仍需刷新。

新增/调整：

- 新增 `output/fake/validation_phase_a_demo_audit.md`
  - 复核 `standard_demo_with_fhn_no_mask_qc` 三个 case：
    - `glioma_ground_truth`
    - `xray_insufficient_evidence`
    - `fhn_no_mask_multifinding`
  - 复核 FHN audit：
    - finding_count `4`
    - lesion_gallery_used_count `2`
    - lesion_gallery_excluded_count `2`
    - has_overlay `true`
  - 复核 X-ray insufficient evidence：
    - `analysis_status=insufficient_evidence`
    - required next image 为 MRI 双髋关节
  - 复核 BraTS MedSAM2 两例 Dice：
    - mean whole tumor Dice `0.9429948832342406`
    - mean tumor core Dice `0.699260558571914`
    - mean enhancing tumor Dice `0.0`
  - 复核较新 runtime trace artifact：
    - `all_stage_artifacts_available=true`
    - `all_stage_schemas_present=true`
    - `stage_count=4`
    - `promotion_status=blocked`
  - 明确当前缺口：
    - API 当前使用的 `standard_demo_with_fhn_no_mask_qc` 静态 response 尚未同步最新 `runtime_gateway_trace`
    - FHN response 顶层 `structured_visual_facts` 仍未完整展开，相关信息主要在 audit / lesion gallery 中
- `output/fake/dual_layer_architecture_validation_roadmap.md`
  - Phase A 章节增加该 audit 报告入口。
- `output/fake/dual_layer_architecture_brief.md`
  - 增加 Phase A demo audit 入口。

当前下一步建议：

1. 刷新或重生成 `standard_demo_with_fhn_no_mask_qc`，让 HTTP 标准 demo 直接带最新 runtime trace。
2. 对齐 FHN response 顶层字段和 audit 字段。
3. 进入 Phase B：生成 `vision_evidence_eval_plan.md`。

### 2026-05-26 标准 demo runtime trace 刷新

本轮目标：根据 Phase A audit 的第一项工程缺口，刷新当前 HTTP 标准 demo 指向的 `output/fake/standard_demo_with_fhn_no_mask_qc/`，让 FHN no-mask response 同步最新 Runtime Gateway Trace。

执行：

```bash
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask_qc
```

第一次在沙箱内运行时，FHN no-mask 真实 VLM 请求因网络解析失败中断；随后按 `docs/API_ROUTE_LOG.md` 确认当前 active route 为 DMX，并用已批准网络权限重新运行。第二次运行完成，真实 VLM + MedSAM2 生成了 FHN no-mask artifacts。

刷新后关键结果：

- `case_id=case_20260526_180322_029001`
- `runtime_gateway_trace_path=output/fake/runtime_gateway_trace/case_20260526_180322_029001_runtime_gateway_trace.json`
- `trace_consistency.stage_count=4`
- `trace_consistency.all_stage_artifacts_available=true`
- `trace_consistency.all_stage_schemas_present=true`
- `stage_order=[runtime_manifest, stop_hook_gate, self_evolving_queue, candidate_validation_gate]`
- `safety_invariants.formal_skill_updated=false`
- `safety_invariants.formal_guideline_updated=false`
- `safety_invariants.diagnosis_report_updated=false`
- `safety_invariants.candidate_artifacts_only=true`

仍存在的缺口：

- FHN response 顶层 `structured_visual_facts` 仍为 `0`。
- FHN response 顶层 `visual_fact_usage.used/excluded` 仍未展开。
- FHN audit 中已有 adopted/excluded visual facts：
  - `image_memory.finding_count=4`
  - `lesion_gallery_used_count=2`
  - `lesion_gallery_excluded_count=2`

同步更新：

- `output/fake/validation_phase_a_demo_audit.md`
  - 已从“runtime trace 缺失”更新为“runtime trace 已同步”。
  - 下一步工程项改为 response 顶层字段与 audit 字段对齐。

### 2026-05-26 Self-evolving Queue Phase 3 最小候选队列实现

本轮目标：承接 `Runtime Manifest -> Stop Hook Gate`，把 stop hook 的只读反思结果沉淀为可审计的候选队列，但仍然禁止自动修改正式医疗 guideline skill、诊断报告或指南来源。

新增/调整：

- `MemoryManager.build_self_evolving_queue(case_id)`
  - 读取 `stop_hook_gate.v1`。
  - 输出 `self_evolving_queue.v1`。
  - 把 runtime warning 转成候选项：
    - `candidate_memory`
    - `candidate_rule`
    - `candidate_skill_patch`
  - 每个候选项保留：
    - `source_warning_code`
    - `candidate_type`
    - `proposal`
    - `evidence`
    - `next_actions`
    - `validation_status=pending_review`
    - `allowed_action=candidate_review_only`
    - `formal_update_allowed=false`
  - 写入 `output/fake/self_evolving_queue/<case_id>_self_evolving_queue.json`。
- `api/service.py`
  - response 增加 `self_evolving_queue` 和 `self_evolving_queue_path`。
- `web/app.js`
  - Memory Audit 增加 `Self-evolving Queue` 区块。
  - 展示候选项、review policy 和 runtime safety。
- 文档同步：
  - `docs/DUAL_PATH_AGENT_FRAMEWORK.md`
  - `docs/architecture/boundaries.md`
  - `output/fake/medscope_demo_runbook.md`
  - `output/fake/standard_demo_walkthrough.md`

当前边界：

- 这是候选队列，不是正式规则升级系统。
- 不自动改 `skills/`。
- 不自动改 guideline source。
- 不自动改诊断报告。
- 候选项后续必须经过人工、指南来源或数据集验证后，才允许升级为正式 skill patch。

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_self_evolving_queue_records_candidate_only_items -v
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_adds_evidence_bundle_and_memory_audit_from_case_memory -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
python -m unittest tests.test_memory_manager tests.test_service_entrypoint tests.test_http_entrypoint -v
node --check web/app.js
python -m unittest discover -v
```

结果：新增红测已按 TDD 转绿；MemoryManager、Service、HTTP 入口目标测试共 `56` 个通过；JS 语法检查通过；全量 `296` 个 unittest 通过。

### 2026-05-26 Candidate Validation Gate Phase 4 最小只读验证门

本轮目标：在 `Self-evolving Queue` 和正式医疗 skill 之间加一道验证门，防止候选规则或 candidate skill patch 被误当成已经验证的临床知识。

新增/调整：

- `MemoryManager.build_candidate_validation_gate(case_id)`
  - 读取 `self_evolving_queue.v1`。
  - 输出 `candidate_validation_gate.v1`。
  - 检查每个候选项是否具备：
    - `item_id`
    - `source_warning_code`
    - `proposal`
    - `evidence`
    - `validation_status`
    - `formal_update_allowed`
  - 对未审核候选项默认给出：
    - `promotion_decision.status=blocked`
    - `promotion_decision.reason=candidate_items_require_review_or_validation`
    - `promotion_decision.formal_update_allowed=false`
  - 写入 `output/fake/candidate_validation_gate/<case_id>_candidate_validation_gate.json`。
- `api/service.py`
  - response 增加 `candidate_validation_gate` 和 `candidate_validation_gate_path`。
- `web/app.js`
  - Memory Audit 增加 `Candidate Validation Gate` 区块。
  - 展示 promotion decision、item validations、review requirements 和 runtime safety。
- 文档同步：
  - `docs/DUAL_PATH_AGENT_FRAMEWORK.md`
  - `docs/architecture/boundaries.md`
  - `output/fake/medscope_demo_runbook.md`
  - `output/fake/standard_demo_walkthrough.md`

当前 Runtime / Gateway 链路：

```text
runtime_manifest
  -> stop_hook_gate
  -> self_evolving_queue
  -> candidate_validation_gate
  -> blocked unless reviewed / validated
```

当前边界：

- validation gate 是只读验证门。
- 不自动改 `skills/`。
- 不自动改 guideline source。
- 不自动改诊断报告。
- 未经人工、指南来源或数据集验证的候选项不会升级为正式 skill。

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_candidate_validation_gate_blocks_unreviewed_queue_items -v
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_adds_evidence_bundle_and_memory_audit_from_case_memory -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
python -m unittest tests.test_memory_manager tests.test_service_entrypoint tests.test_http_entrypoint -v
node --check web/app.js
python -m unittest discover -v
```

结果：新增红测已按 TDD 转绿；MemoryManager、Service、HTTP 入口目标测试共 `57` 个通过；JS 语法检查通过；全量 `297` 个 unittest 通过。

### 2026-05-26 Runtime Gateway Trace 汇总入口

本轮目标：前面已经有 `runtime_manifest -> stop_hook_gate -> self_evolving_queue -> candidate_validation_gate` 四段 artifact，但组会和前端演示时需要一个总览入口，避免听起来像又拆了更多 Agent。新增 `runtime_gateway_trace` 作为底层 gateway 的汇总视图，不是新的诊断 Agent。

新增/调整：

- `MemoryManager.build_runtime_gateway_trace(case_id)`
  - 汇总四段 runtime artifact：
    - `runtime_manifest`
    - `stop_hook_gate`
    - `self_evolving_queue`
    - `candidate_validation_gate`
  - 输出 `runtime_gateway_trace.v1`。
  - 记录：
    - `stages`
    - `promotion_status`
    - `formal_update_allowed`
    - `safety_invariants`
    - `presentation_summary`
  - 写入 `output/fake/runtime_gateway_trace/<case_id>_runtime_gateway_trace.json`。
- `api/service.py`
  - response 增加 `runtime_gateway_trace` 和 `runtime_gateway_trace_path`。
- `web/app.js`
  - Memory Audit 增加 `Runtime Gateway Trace` 区块。
  - 用它作为四段 gateway artifact 的演示入口。
- 文档同步：
  - `docs/DUAL_PATH_AGENT_FRAMEWORK.md`
  - `docs/architecture/boundaries.md`
  - `output/fake/medscope_demo_runbook.md`
  - `output/fake/standard_demo_walkthrough.md`

当前讲法：

```text
Clinical Evidence Pipeline
  上层：临床编排、视觉证据、诊断推理

Runtime Gateway Trace
  下层：skill 分发、artifact、contract、stop hook、candidate queue、validation gate
```

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_runtime_gateway_trace_summarizes_all_runtime_stages -v
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_adds_evidence_bundle_and_memory_audit_from_case_memory -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
python -m unittest tests.test_memory_manager tests.test_service_entrypoint tests.test_http_entrypoint -v
node --check web/app.js
python -m unittest discover -v
```

结果：新增红测已按 TDD 转绿；MemoryManager、Service、HTTP 入口目标测试共 `58` 个通过；JS 语法检查通过；全量 `298` 个 unittest 通过。

### 2026-05-26 Runtime Gateway Trace Consistency

本轮目标：`runtime_gateway_trace` 已经能汇总四段 gateway artifact，但还需要证明这条轨迹本身可审计，而不是只显示四个名字。因此新增 `trace_consistency`。

新增/调整：

- `MemoryManager.build_runtime_gateway_trace(case_id)`
  - 增加 `trace_consistency`：
    - `stage_count`
    - `all_stage_artifacts_available`
    - `all_stage_schemas_present`
    - `missing_artifact_paths`
    - `missing_schema_stages`
    - `stage_order`
  - 通过 artifact path 是否存在、schema_version 是否存在来判断当前 gateway trace 是否完整。
- `web/app.js`
  - `Runtime Gateway Trace` 区块增加 `Trace Consistency` 展示。
- 文档同步：
  - `docs/DUAL_PATH_AGENT_FRAMEWORK.md`
  - `docs/architecture/boundaries.md`
  - `output/fake/medscope_demo_runbook.md`
  - `output/fake/standard_demo_walkthrough.md`

当前意义：

- `runtime_gateway_trace` 不只是汇报文案，而是能机器检查四段 gateway artifact 是否都存在。
- 前端可直接展示 `all_stage_artifacts_available` 和 `all_stage_schemas_present`。
- 这有助于把架构表达从“多个 Agent 名称”转为“可审计 runtime 执行轨迹”。

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_runtime_gateway_trace_summarizes_all_runtime_stages -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
python -m unittest tests.test_memory_manager tests.test_service_entrypoint tests.test_http_entrypoint -v
node --check web/app.js
python -m unittest discover -v
```

结果：新增红测已按 TDD 转绿；MemoryManager、Service、HTTP 入口目标测试共 `58` 个通过；JS 语法检查通过；全量 `298` 个 unittest 通过。

### 2026-05-26 组会答辩话术补强

本轮目标：上一轮已经把架构表述从“五个并列 Agent”收敛为“临床证据流水线”，但演示材料还需要更直接回答老师的质疑：为什么这不是为了分 Agent 而分。

新增/调整：

- `output/fake/medscope_demo_runbook.md`
  - 新增“先用 30 秒回应架构质疑”。
  - 明确回答：拆分依据是医疗安全边界，不是 Agent 数量。
  - 增加“为什么不是为了分 Agent 而分？”现场问答。
  - 将风险控制点拆成入口路由风险、图像理解风险、诊断幻觉风险、指南来源风险、追溯审计风险。
- `output/fake/standard_demo_walkthrough.md`
  - 新增建议开场 30 秒。
  - 新增“为什么不能合成一个大 Agent”的回答。
  - 强调一个大 Agent 会混淆视觉定位、指南 skill、证据使用和追问记忆错误来源。

当前组会讲法：

- 不讲“五个并列 Agent”。
- 讲 guideline-aware clinical evidence pipeline。
- 重点说明三条主线：
  - Vision Evidence Agent 负责“看到什么”。
  - Diagnosis Reasoning Agent 负责“这些证据能支持什么”。
  - Memory / Audit Layer 负责“每一步证据如何被保存、采用、排除和追问复用”。

### 2026-05-26 Agentic Runtime / Evidence Gateway 叙事补充

本轮目标：用户指出还可以参考 Claude Code / Codex 这类新式 agent 系统，把底层 gateway、skill 系统、文件共享、stop hooks、自我反思和 self-evolving 讲出来。这样架构不只是“几个医疗 Agent”，而是“临床证据流水线 + 受约束的 agentic runtime”。

新增/调整：

- `docs/DUAL_PATH_AGENT_FRAMEWORK.md`
  - 新增 `Agentic Runtime / Evidence Gateway` 章节。
  - 明确底层 gateway 管理 Skill Registry、Shared File Workspace、Contract & Policy Guards、Tool Router、Stop Hooks / Reflection Hooks、Memory & Audit Store。
  - 明确 self-evolving 不能自动改写正式医疗指南，只能生成 candidate memory / candidate rule / candidate skill patch。
- `docs/architecture/boundaries.md`
  - 增加底层 gateway 边界。
  - 明确 Gateway 不产生医学结论，只负责权限、文件、skill、工具路由、hooks 和审计。
  - Stop hooks / reflection hooks 不能直接修改正式 `guideline_based` skill。
- `docs/goal.md`
  - 在临床证据流水线之后补充底层 `Agentic Runtime / Evidence Gateway`。
  - 解释 Skill Gateway、Shared File Workspace、Contract Guards、Tool Router、Stop Hooks、Self-evolving Queue。
- `output/fake/medscope_demo_runbook.md`
  - 现场答辩加入 gateway / hooks 讲法。
  - 区分当前已落地：`output/` 文件 artifact、`skills/`、evidence bundle、memory audit/replay、contracts/alignment/completeness/safety gate。
  - 区分后续扩展：显式 stop hook 框架、candidate skill patch、常用诊疗规则记忆、候选规则验证和版本化升级。
- `output/fake/standard_demo_walkthrough.md`
  - 开场和答辩部分加入 agentic runtime 讲法。

当前对外两层架构：

```text
上层：Guideline-aware Clinical Evidence Pipeline
  - Clinical Orchestrator
  - Vision Evidence Agent
  - Diagnosis Reasoning Agent
  - conditional Skill Builder / Guideline Component
  - Memory / Audit Layer

底层：Agentic Runtime / Evidence Gateway
  - Skill Gateway
  - Shared File Workspace
  - Contract Guards
  - Tool Router
  - Stop Hooks / Reflection Hooks
  - Self-evolving Queue
```

安全边界：

- 当前可以说系统具备部分 gateway 雏形：skill 文件、共享 artifact、contract、evidence bundle、memory audit/replay。
- 不应说系统已经具备完整自动 self-evolving 医疗规则能力。
- 更准确的说法是：后续会让 hooks 把经验沉淀为候选规则，经过验证后再升级为正式 skill。

### 2026-05-26 Runtime Gateway 最小落地路线图

本轮目标：上一轮已经补充 Agentic Runtime / Evidence Gateway 叙事，但还需要明确最小实现顺序，避免概念过大导致后续重构。

新增/调整：

- `docs/DUAL_PATH_AGENT_FRAMEWORK.md`
  - 新增 `Runtime 落地路线`。
  - 拆成三阶段：
    - Phase 1：Runtime Manifest
    - Phase 2：Stop Hook Gate
    - Phase 3：Self-evolving Queue
  - 每阶段补最小字段和验收口径。
- `docs/architecture/boundaries.md`
  - 新增 `接 Runtime Gateway / Stop Hooks`。
  - 明确第一版只做审计和建议，不自动执行、不改正式 skill。
- `output/fake/medscope_demo_runbook.md`
  - 新增“Gateway 下一步怎么落地？”。
  - 组会口径：当前已有 gateway 雏形，下一步先加 runtime manifest 和 stop hook。
- `output/fake/standard_demo_walkthrough.md`
  - 新增 runtime manifest -> stop hook gate -> self-evolving queue 的讲解顺序。

最小落地顺序：

1. `runtime_manifest`
   - 记录 case_id、skill、artifact、tool call、contract check、memory 写入和证据缺口。
2. `stop_hook_gate`
   - 检查 excluded fact、missing 证据、四类 memory、补充影像建议。
3. `self_evolving_queue`
   - 生成低证据候选规则或 candidate skill patch，等待验证，不直接修改正式指南。

当前边界：

- 这是架构路线图和演示口径，不是已完成实现。
- 后续实现时应优先加 manifest 和 hook 的只读审计，不先做自动改 skill。

### 2026-05-26 Runtime Manifest Phase 1 最小实现

本轮目标：把上一轮路线图里的 Phase 1 `runtime_manifest` 真正接入系统，保持只读审计，不做 stop hook 自动改报告或 skill。

新增/调整：

- `MemoryManager.build_runtime_manifest(case_id)`
  - 从 case memory 生成 `runtime_manifest.v1`。
  - 记录 `case_id`、`selected_skill`、`skill_version`、`skill_type`。
  - 记录 input artifacts：患者输入是否存在、image_path、modality、body_part。
  - 记录 generated artifacts：image_outputs、lesion_gallery_summary、case_memory_path、memory_audit_path。
  - 记录 tool_calls：SkillBuilderTool、视觉工具、MemoryManager。
  - 记录 contracts_checked：memory_v1、patient_case_input、skill_routing_decision、alignment_plan、visual_analysis_result、evidence_bundle、safety_gate。
  - 记录 memory_written：patient/image/skill/reasoning 四类 memory。
  - 记录 blocked_or_missing_evidence：analysis_status、missing_or_unassessed、quality_warnings、required_next_images、blocked_scopes。
  - 记录 runtime_safety：`manifest_only=true`、`stop_hook_executed=false`、`formal_skill_updated=false`、`self_evolving_action=candidate_only_no_formal_skill_update`。
  - 写入 `output/fake/runtime_manifest/<case_id>_runtime_manifest.json`。
- `MedScopeService._attach_memory_trace(...)`
  - response 增加 `runtime_manifest` 和 `runtime_manifest_path`。
- 前端 `web/app.js`
  - Evidence Pipeline Trace 增加 `Runtime Manifest` 区块。
  - 展示 Evidence Gateway 的 skill、artifact、tool calls、contract guards、memory_written 和 runtime safety。
- 文档状态同步：
  - `docs/DUAL_PATH_AGENT_FRAMEWORK.md`
  - `docs/architecture/boundaries.md`
  - `output/fake/medscope_demo_runbook.md`
  - `output/fake/standard_demo_walkthrough.md`

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_runtime_manifest_records_gateway_execution_facts -v
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_adds_evidence_bundle_and_memory_audit_from_case_memory -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
python -m unittest tests.test_memory_manager tests.test_service_entrypoint tests.test_http_entrypoint -v
node --check web/app.js
```

结果：新增红绿测试通过，memory/service/http 相关 `54` 个测试通过，JS 语法检查通过。

当前边界：

- Phase 1 Runtime Manifest 已落地。
- Phase 2 Stop Hook Gate 当轮尚未实现；后续已完成最小只读 gate。
- Phase 3 Self-evolving Queue 当轮尚未实现；后续已完成最小候选队列。
- 当前不会自动修改正式 skill、指南、诊断报告。

### 2026-05-26 Stop Hook Gate Phase 2 最小只读实现

本轮目标：把 Phase 2 `stop_hook_gate` 做成只读审计 gate。它可以发现风险、输出 next actions 和候选状态，但不能修改诊断报告、正式 skill 或指南。

新增/调整：

- `MemoryManager.build_stop_hook_gate(case_id)`
  - 读取 `runtime_manifest`、`evidence_bundle` 和 case memory。
  - 输出 `stop_hook_gate.v1`。
  - 记录 `runtime_warnings`：
    - `missing_or_unassessed_evidence`
    - `blocked_diagnosis_scope`
    - `quality_warnings_present`
    - `memory_incomplete`
    - `excluded_visual_facts_present`
  - 记录 `next_actions`，例如补充关键影像、不要把 missing/unassessed 当阴性、QA 不得复用 excluded facts。
  - 记录 `candidate_memory` 和 `candidate_skill_patch`，当前均为 `not_generated / read_only_gate`。
  - 记录 `runtime_safety`：
    - `stop_hook_executed=true`
    - `read_only=true`
    - `formal_skill_updated=false`
    - `diagnosis_report_updated=false`
    - `self_evolving_queue_updated=false`
  - 写入 `output/fake/stop_hook_gate/<case_id>_stop_hook_gate.json`。
- `MedScopeService._attach_memory_trace(...)`
  - response 增加 `stop_hook_gate` 和 `stop_hook_gate_path`。
- 前端 `web/app.js`
  - Evidence Pipeline Trace 增加 `Stop Hook Gate` 区块。
  - 展示 runtime warnings、next actions、candidate skill patch 和 runtime safety。
- 文档状态同步：
  - `docs/DUAL_PATH_AGENT_FRAMEWORK.md`
  - `docs/architecture/boundaries.md`
  - `output/fake/medscope_demo_runbook.md`
  - `output/fake/standard_demo_walkthrough.md`

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_stop_hook_gate_reports_read_only_runtime_warnings -v
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_adds_evidence_bundle_and_memory_audit_from_case_memory -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
```

结果：新增红绿测试已通过。

当前边界：

- Phase 1 Runtime Manifest 已落地。
- Phase 2 Stop Hook Gate 已落地为只读 gate。
- Phase 3 Self-evolving Queue 当轮尚未实现；后续已完成最小候选队列。
- 当前不会自动修改正式 skill、指南、诊断报告。

### 2026-05-26 组会反馈后的架构口径二次收敛

背景：老师反馈“五个 agent”容易被理解成为了分 agent 而分。上一轮已经改了前端和主要 runbook，本轮继续把会被组会看到的入口文档和旧 PPT 产物收敛到同一口径。

当前推荐表达：

- 系统主叙事是“临床证据流水线”，不是“五个并列 Agent”。
- 三个核心 Agent：
  - Clinical Orchestrator
  - Vision Evidence Agent
  - Diagnosis Reasoning Agent
- 一个条件触发组件：
  - Skill Builder / Guideline Component
- 一个基础设施层：
  - Memory / Audit Layer

本轮修改：

- `docs/goal.md`
  - 文件开头改成当前推荐架构，先讲临床证据流水线。
  - 明确 Skill Builder 不是永远参与诊断的并列 Agent，而是在缺少合适 skill 或需要指南构建时触发。
  - 明确 Memory / Audit 是基础设施层，不参与医学判断。
- `docs/architecture/boundaries.md`
  - 增加当前对外推荐表述。
  - 把 `GaoDoctorAgent / VisionAgent / DiagnosisDoctorAgent / MemoryManager` 解释为工程实现节点，不作为对外并列 Agent 数量叙事。
- `output/fake/five_agent_virtual_mainline_ppt/`
  - README 和讲稿标记为历史材料，不建议继续作为组会主叙事。
  - delivery manifest 增加 `current_status` 和 `recommended_narrative`，content spine 改成临床证据流水线。
- `output/fake/mvp_status_by_agents.md`
  - MVP 冻结项从“五 Agent 主链路”改成“临床证据流水线主链路”。
- `output/fake/medscope_demo_runbook.md`
  - 展示面板名称统一为 `Evidence Pipeline Trace`。

当前边界：

- 没有做大工程重构。
- 代码类名和 audit trace 仍可保留 `GaoDoctorAgent` 等实现名，便于调试和审计。
- 对外汇报不再强调 agent 数量，而强调医疗安全边界、证据充分性、视觉证据约束诊断和 memory audit。

### 2026-05-26 架构表述从“五 Agent”收敛为临床证据流水线

背景：组会反馈“五个 Agent”容易被理解为为了分 Agent 而分。当前代码主线可以继续保留实现节点 trace，但对外汇报需要改成按医疗安全边界拆分的证据流水线。

本轮目标：不做大工程重构，先修正前端和演示文档的架构叙事。

新增/调整：

- 前端 `Memory Trace` 面板标题改为 `Evidence Pipeline Trace`
- 前端原 `五 Agent 主线` 改为 `临床证据流水线`
- 前端流水线说明新增：
  - 3 个核心 Agent
  - 1 个条件 Skill 组件
  - 1 个 Memory/Audit 基础设施层
  - 实现节点 trace 保留内部类名用于审计
- 前端阶段命名调整：
  - `GaoDoctorAgent` 展示为 `临床编排 / 入口分诊`
  - `SkillBuilderAgent` 展示为 `条件 Skill 构建 / 加载`
  - `VisionAgent` 展示为 `视觉证据提取`
  - `DiagnosisDoctorAgent` 展示为 `证据约束诊断推理`
  - `MemoryManager` 展示为 `Memory / Audit Layer`
- `docs/DUAL_PATH_AGENT_FRAMEWORK.md`
  - 将“五个 Agent 的通用职责”改为“临床证据流水线职责边界”
  - 明确 `MemoryManager` 是基础设施层，不是诊断 Agent
  - 明确 `SkillBuilderAgent` 是条件触发组件，有现成 skill 时只加载/校验
- `output/fake/medscope_demo_runbook.md`
  - 从“五个正式 Agent + 虚拟主线”改为“临床证据流水线”
  - 移除旧 PPT 作为主叙事入口
  - 将现场讲解改成 Clinical Orchestrator / Vision Evidence / Diagnosis Reasoning / Memory-Audit Layer
- `output/fake/standard_demo_walkthrough.md`
  - 将“五个 Agent 的演示讲解”改为“临床证据流水线的演示讲解”
- `output/fake/mvp_status_by_agents.md`
  - 将状态盘点改为临床证据流水线视角

当前语义：

- 内部仍保留 `agents_traced` 和 `agent_io_summary` 的实现类名，便于代码审计和 replay
- 对外不再把 `MemoryManager` 讲成和诊断医生并列的 Agent
- 对外不再把 `SkillBuilderAgent` 讲成每次都主动参与推理的 Agent
- 核心创新点改为：以 `evidence_bundle` 为中心的 guideline-aware clinical evidence pipeline

验证：

```bash
python -m unittest tests.test_http_entrypoint -v
node --check web/app.js
```

结果：HTTP 前端入口测试和 JS 语法检查已通过。

### 2026-05-25 Lesion Gallery 标准契约收敛

本轮目标：上一阶段前端已经能从 `visual_evidence_bundle.findings[].regions[]` 和 `visual_fact_usage` 拼出“候选病灶证据”图库，但这仍然偏前端启发式。为了减少后续重构风险，本轮将多候选病灶展示收敛为后端标准响应字段。

新增/调整：

- 新增 `tools/lesion_gallery_builder.py`
  - 输入：`visual_evidence_bundle` + `visual_fact_usage`
  - 输出：`lesion_gallery.v1`
  - 每个 item 包含：
    - `finding_id`
    - `region_id`
    - `target`
    - `display_name`
    - `usage.status`：`used` / `excluded` / `candidate`
    - `usage.reason`
    - `image_paths.comparison_path`
    - `image_paths.overlay_path`
    - `image_paths.mask_path`
    - `measurements`
    - `quality`
- `MemoryManager.get_evidence_bundle()`
  - 新增顶层 `evidence_bundle.lesion_gallery`
  - gallery 由 memory 中的视觉证据和诊断采用/排除审计统一生成
- `MedScopeService._attach_case_outputs()`
  - 将 `evidence_bundle.lesion_gallery` 提升为响应顶层 `lesion_gallery`
- `web/app.js`
  - `renderCandidateLesionGallery()` 优先读取 `payload.lesion_gallery.items`
  - 如果旧 artifact 没有该字段，再回退到 `visual_evidence_bundle + visual_fact_usage` 兼容路径
- 测试覆盖：
  - `tests/test_memory_manager.py`
  - `tests/test_service_entrypoint.py`
  - `tests/test_http_entrypoint.py`

当前标准 demo artifact 已刷新：

```json
{
  "case_id": "case_20260525_193950_965250",
  "lesion_gallery": {
    "schema_version": "lesion_gallery.v1",
    "items": 4,
    "used_count": 2,
    "excluded_count": 2
  },
  "comparison_path": "output/fake/gaodoctor_fhn_no_mask/case_20260525_193950_965250/finding_segmentation/medsam2_1_sclerotic_band_comparison.png"
}
```

运行态验证：

- 新服务：`http://127.0.0.1:8028`
- `/health` 返回 `{"status":"ok"}`
- `/v1/demo/standard/cases/fhn_no_mask_multifinding/response`
  - `lesion_gallery.schema_version == lesion_gallery.v1`
  - `items == 4`
  - `used_count == 2`
  - `excluded_count == 2`
  - 顶层 `lesion_gallery` 与 `evidence_bundle.lesion_gallery` 一致
  - 首个 `comparison_path` 文件存在

验证：

```bash
python -m unittest tests.test_memory_manager tests.test_service_entrypoint tests.test_http_entrypoint -v
node --check web/app.js
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask_qc
python -m unittest discover -v
```

结果：相关测试通过；标准 demo artifact 刷新成功；全量 `292` 个 unittest 全部通过。

### 2026-05-25 Lesion Gallery Contract 化

本轮目标：上一阶段已经生成 `lesion_gallery.v1`，但 schema 只存在于 builder 约定中。为了避免后续前端、memory、service 或 demo 各自隐式依赖字段，本轮把它正式纳入 `contracts/medical_contracts.py`。

新增/调整：

- `contracts/medical_contracts.py`
  - `ImageOutputs` 新增可选 `comparison_path`
  - 新增 `LesionGallery` contract
  - `LesionGallery` 固定 `schema_version=lesion_gallery.v1`
  - 校验每个 item 必须有 `finding_id`
  - 校验 `usage.status` 只能是：
    - `used`
    - `excluded`
    - `candidate`
  - `to_dict()` 统一计算：
    - `used_count`
    - `excluded_count`
    - `candidate_count`
- `tools/lesion_gallery_builder.py`
  - 不再手写 schema 和计数
  - 改为通过 `LesionGallery(items=items).to_dict()` 输出
- `tests/test_contracts.py`
  - 增加 `LesionGallery` contract 测试
  - 增加 `ImageOutputs.comparison_path` 保留测试

当前语义：

- `comparison_path` 是正式 image output 的可选展示 artifact
- `lesion_gallery.v1` 是正式展示契约，不再只是前端临时结构
- DiagnosisAgent 的采用/排除审计继续通过 `visual_fact_usage` 决定，gallery 只做展示层标准化，不改变诊断逻辑

验证：

```bash
python -m unittest tests.test_contracts tests.test_memory_manager tests.test_service_entrypoint tests.test_http_entrypoint -v
node --check web/app.js
python -m unittest discover -v
```

结果：相关 contract/memory/service/http 测试通过；全量 `293` 个 unittest 全部通过。

### 2026-05-25 前端多候选病灶采用 / 排除展示

本轮目标：上一阶段已经让 VisionAgent 输出 `comparison_path`，但前端主要展示首个原图 + 分割对照图；对于多候选病灶场景，用户仍不容易看出哪些候选视觉证据被诊断 Agent 采用，哪些因为重叠、证据不足或质量问题被排除。

新增/调整：

- `web/app.js`
  - 新增 `renderCandidateLesionGallery(payload)`
  - 新增 `buildCandidateLesionItems(payload)`
  - 新增 `buildVisualFactUsageMap(payload)`
  - 新增 `visualFactUsageLabel(kind)`
  - 从 `visual_evidence_bundle.findings[].regions[]` 读取 `comparison_path` / `overlay_path` / `mask_path`
  - 从 `visual_fact_usage.used/excluded` 映射每个 `finding_id` 的采用状态
  - 在图像输出区域显示“候选病灶证据”图库，标记为：
    - `诊断采用`
    - `排除`
    - `候选`
- `web/app.css`
  - 新增候选病灶图库布局
  - 采用证据使用绿色边框
  - 排除证据使用黄色边框
  - 移动端自动改为单列
- `tests/test_http_entrypoint.py`
  - 静态前端测试约束必须保留：
    - `renderCandidateLesionGallery`
    - `候选病灶证据`
    - `诊断采用`
    - `排除`

当前语义：

- VisionAgent 仍只输出候选视觉证据和测量值，不做最终诊断
- DiagnosisAgent 根据 `visual_fact_usage` 决定哪些视觉事实进入推理
- 前端把“候选病灶图”和“诊断采用 / 排除状态”放在同一个视图里，便于演示多病灶、多征象和排除逻辑

验证：

```bash
node --check web/app.js
python -m unittest tests.test_http_entrypoint -v
curl -s http://127.0.0.1:8027/static/app.js
```

结果：JS 语法检查通过，HTTP 前端测试 `23` 个全部通过；运行态静态文件确认包含 `renderCandidateLesionGallery`、`候选病灶证据`、`诊断采用`、`排除`。

### 2026-05-25 Memory Replay 增加 Replay Consistency

本轮目标：让 `memory_replay` 不只是展示五 Agent 步骤，还能自检这条回放链是否具备完整事件、完整 memory_scope，以及是否包含追问扩展节点。

新增/调整：

- `MemoryManager.build_case_replay()` 输出 `replay_consistency`
- HTTP 真实 VLM + MedSAM2 demo 输出 `replay_consistency`
- 标准 demo QA 追加追问节点后会重新计算 `replay_consistency`
- 对旧 demo artifact 中缺少 `memory_scope` 的 replay 步骤，按 event 补齐默认 memory 归属
- 前端 `Memory Replay` 增加 `Replay Consistency` 展示区

当前语义：

- `required_events_present`：主线必需事件是否齐全
- `memory_scope_complete`：每个 replay step 是否都标明归属哪一类 memory
- `qa_extension_present`：当前 replay 是否已经扩展出追问 QA 节点
- `steps_missing_memory_scope`：如果有缺失，可以定位到具体 step index

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_case_replay_returns_agent_step_timeline -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle tests.test_http_entrypoint.HttpEntrypointTest.test_demo_case_qa_answers_from_artifact_visual_fact_usage -v
python -m unittest tests.test_http_entrypoint -v
python -m unittest tests.test_memory_manager tests.test_service_entrypoint -v
node --check web/app.js
python -m unittest discover -v
```

结果：目标回归测试、HTTP 入口测试、MemoryManager/Service 测试、JS 语法检查与全量 `291` 个 unittest 均通过。

运行态验证：

```bash
python -m api.http_server --host 127.0.0.1 --port 8026
```

结果：

- `/health` 返回 `{"status": "ok"}`
- `/static/app.js` 包含 `replay_consistency` 与 `memory_scope_complete`
- `/v1/demo/real-vlm-medsam2/response` 的 `memory_replay.replay_consistency` 为：
  - `required_events_present: true`
  - `memory_scope_complete: true`
  - `missing_required_events: []`
  - `step_count: 7`
- 刷新前，标准 demo QA 的旧 artifact 会诚实暴露 `missing_required_events: ["skill_loading"]`，但 `memory_scope_complete: true`，说明 replay scope 已补齐，事件完整性仍按真实 artifact 审计。

补充收敛：已使用真实 DMX `gemini-3.5-flash` 路由和 MedSAM2 默认 runner 刷新固定标准演示目录：

```bash
python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask_qc
```

刷新后运行态验证：

- `/v1/demo/standard/cases/fhn_no_mask_multifinding/response`
  - `required_events_present: true`
  - `memory_scope_complete: true`
  - `missing_required_events: []`
  - replay 顺序：`patient_intake -> skill_routing -> skill_loading -> visual_evidence -> diagnosis_report -> memory_audit`
- `/v1/demo/standard/cases/fhn_no_mask_multifinding/qa`
  - `required_events_present: true`
  - `memory_scope_complete: true`
  - `qa_extension_present: true`
  - 追问节点：`GaoDoctorAgent QA / follow_up_qa / patient_memory.qa_history`

### 2026-05-25 五 Agent + 虚拟主线 PPT

本轮目标：把当前五 Agent 架构、虚拟主线、Evidence Bundle、Memory Replay/Audit 和 FHN no-mask 标准 demo 整理成一份可汇报的 PPT。

产物：

- PPTX：`output/fake/five_agent_virtual_mainline_ppt/medscope_five_agent_virtual_mainline.pptx`
- 讲稿：`output/fake/five_agent_virtual_mainline_ppt/medscope_five_agent_virtual_mainline_notes.md`
- README：`output/fake/five_agent_virtual_mainline_ppt/README.md`
- Manifest：`output/fake/five_agent_virtual_mainline_ppt/delivery_manifest.json`
- ZIP：`output/fake/five_agent_virtual_mainline_ppt/medscope_five_agent_virtual_mainline_package.zip`

PPT 结构：

1. MedScope 五 Agent + 虚拟主线
2. 为什么要有虚拟主线
3. 五个 Agent 职责地图
4. 虚拟主线怎么跑
5. Skill 如何自动选择
6. VisionAgent 如何圈病灶
7. 诊断医生为什么不看原图
8. 四类 Memory 与审计
9. 标准 Demo 当前效果
10. 当前 MVP 与下一步

验证：

- `python-pptx` 可成功读取 PPTX
- 页数：10
- 文件中包含关键术语：`GaoDoctorAgent`、`SkillBuilderAgent`、`VisionAgent`、`DiagnosisDoctorAgent`、`MemoryManager`、`Replay Consistency`、`Evidence Bundle`
- PPT 引用了当前 FHN no-mask 标准 demo 的原图和分割 overlay
- ZIP 交付包包含 PPTX、讲稿、README、Manifest 共 4 个文件
- 当前环境缺少 `soffice/libreoffice`，未自动导出 PDF 或逐页缩略图

### 2026-05-25 MVP 演示 Runbook

本轮目标：把前端 demo、标准 FHN no-mask artifact、五 Agent PPT 和讲稿串成一份现场演示总控文档，避免演示时不知道先讲哪一层、如何解释视觉/诊断边界、如何回答追问。

产物：

- Runbook：`output/fake/medscope_demo_runbook.md`

内容覆盖：

- 演示入口和前端服务命令
- PPT 开场讲法
- FHN no-mask 样例展示顺序
- 五个 Agent 分工讲解
- 追问 QA 演示问题：`为什么囊性变没有算作独立依据？`
- 常见现场问题答法
- MVP 边界说明
- 演示检查清单
- 当前 artifact 验证记录

验证：

- Runbook 引用的 PPTX、讲稿、PPT zip、FHN response 均存在
- Runbook 中记录的 `case_id=case_20260525_183524_417247`
- 当前 FHN response 的 `selected_skill=femoral_head_necrosis`
- 当前 FHN response 的 `selected_vision_mode=no_mask_skill`
- 当前 FHN response 的 `replay_consistency.required_events_present=true`
- 当前 FHN response 的 `replay_consistency.memory_scope_complete=true`
- 当前 FHN response 的 `trace_consistency.required_agents_present=true`

### 2026-05-25 VisionAgent 输出原图 + 分割对比图

本轮目标：回到视觉 Agent 主线，不继续 PPT。补齐之前待办里的“最终展示的病灶图应该是原图和分割出来的病灶放在一起的比较图”，让视觉输出不仅有 `mask_path` 和 `overlay_path`，还生成一张单独可展示的 `comparison_path`。

新增/调整：

- `scripts/no_mask_medsam2_segmentation_demo.py`
  - 每个 MedSAM2 candidate segmentation 生成横向拼接图：
    - 左侧：原图
    - 右侧：overlay
  - 顶层 summary 新增 `comparison_path`
  - `segmentation_result` 新增 `comparison_path`
  - finding region 新增 `comparison_path`
- `scripts/no_mask_candidate_diagnosis_demo.py`
  - `build_candidate_visual_analysis_result()` 将 `comparison_path` 透传到 `image_outputs`
  - fallback structured finding region 也保留 `comparison_path`
- `web/app.js`
  - 前端病灶图展示区优先显示 `原图+分割对照`
  - 继续保留原图、mask、overlay 三类分项预览
- `tests`
  - no-mask MedSAM2 segmentation 测试约束 comparison PNG 真实存在，尺寸为原图宽度的 2 倍
  - candidate diagnosis 测试约束 `image_outputs.comparison_path`
  - MVP 主线测试约束 FHN no-mask comparison path 写入 image memory 和 visual evidence bundle
  - HTTP 静态前端测试约束 `comparison_path` 前端处理逻辑存在

刷新标准 demo：

```bash
DMX_API_KEY=... python -m scripts.end_to_end_demo --suite --include-fhn-no-mask --output-dir output/fake/standard_demo_with_fhn_no_mask_qc
```

刷新后当前 FHN case：

- `case_id=case_20260525_185238_428216`
- `image_outputs.comparison_path=output/fake/gaodoctor_fhn_no_mask/case_20260525_185238_428216/finding_segmentation/medsam2_1_sclerotic_band_comparison.png`
- comparison 图已存在，尺寸为 `640 x 235`
- `replay_consistency.required_events_present=true`
- `replay_consistency.memory_scope_complete=true`

验证：

```bash
python -m unittest tests.test_no_mask_medsam2_segmentation_demo tests.test_no_mask_candidate_diagnosis_demo tests.test_mvp_flow.MedScopeMvpFlowTest.test_gaodoctor_runs_fhn_no_mask_skill_pipeline_when_requested -v
python -m unittest tests.test_http_entrypoint -v
python -m unittest tests.test_service_entrypoint tests.test_memory_manager -v
node --check web/app.js
```

结果：上述目标测试、HTTP 入口测试、Service/Memory 测试与前端 JS 语法检查均通过。

### 2026-05-25 Demo Artifact QA Safety 补齐 Evidence Bundle 使用计数

本轮目标：追问 QA 已经作为 `GaoDoctorAgent QA` 出现在 audit/replay 中，但 demo artifact QA 和前端本地 fallback 的 `qa_safety` 字段形状需要继续对齐，避免前端显示和后端真实 QA response 不一致。

新增/调整：

- 真实 VLM+MedSAM2 demo QA 的 `memory_audit.qa_safety.evidence_bundle_used_count` 返回 `1`
- 标准 demo artifact QA 的 `memory_audit.qa_safety.evidence_bundle_used_count` 返回 `1`
- 真实 VLM+MedSAM2 demo QA 的 `agent_io_summary["GaoDoctorAgent QA"].output.evidence_bundle_used` 显式返回 `true`
- 前端本地 fallback diagnosis payload 初始化：
  - `evidence_bundle_used: false`
  - `evidence_bundle_used_count: 0`

当前语义：

- 初始诊断：没有追问时，QA 使用计数为 `0`
- 追问回答：只要回答基于已有 evidence bundle，QA 使用计数至少为 `1`
- 前端 `QA Safety` 可以同时展示“是否要求 evidence bundle”和“实际用了几条 evidence bundle 约束追问”

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_demo_case_qa_answers_from_artifact_visual_fact_usage -v
node --check web/app.js
```

结果：前端静态资源、真实 VLM+MedSAM2 demo QA、标准 demo artifact QA 和 JS 语法检查均通过。

### 2026-05-25 Demo QA Replay 追问 Agent 命名对齐

本轮目标：标准 MemoryManager 和 Service QA replay 已经把追问步骤命名为 `GaoDoctorAgent QA`，但两个 demo artifact 构造器仍在 `memory_replay.steps[-1]` 中使用旧的 `GaoDoctorAgent`，导致同一条追问在 `memory_audit` 和 `memory_replay` 里 agent 名称不一致。

新增/调整：

- 标准 demo artifact QA replay 的 `follow_up_qa.agent` 改为 `GaoDoctorAgent QA`
- 真实 VLM+MedSAM2 demo QA replay 的 `follow_up_qa.agent` 改为 `GaoDoctorAgent QA`
- HTTP 测试补齐两个 demo QA response 的 replay agent 命名断言

当前语义：

- 初始病例仍是标准五 Agent 主线
- 追问不重新跑视觉/诊断全链路，而是作为 `GaoDoctorAgent QA` 扩展节点基于已有 evidence bundle 回答
- `memory_audit.agents_traced`、`agent_io_summary` 和 `memory_replay.steps` 对追问节点命名保持一致

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_demo_case_qa_answers_from_artifact_visual_fact_usage -v
```

结果：真实 VLM+MedSAM2 demo QA 和标准 demo artifact QA replay 命名对齐测试均通过。

### 2026-05-25 Memory Replay 补齐 Memory Scope

本轮目标：`memory_replay.steps` 已经能展示五 Agent 和追问 QA 的顺序，但每一步缺少机器可读的 memory 归属。前端和审计工具只能从 agent/event 文案推断这一步对应四类 memory 中的哪一类，不利于解释 `patient_memory / image_memory / skill_memory / reasoning_memory` 的协作边界。

新增/调整：

- 标准 `MemoryManager.build_case_replay()` 每个 step 补充 `memory_scope`
- 真实 VLM+MedSAM2 demo replay 同步补充 `memory_scope`
- 标准 demo artifact QA 追加的 `follow_up_qa` step 补充 `memory_scope=patient_memory.qa_history`
- 前端真实样例 fallback replay 同步补充 `memory_scope`
- `renderMemoryReplay()` 的 step 摘要展示 `memory_scope`

当前语义：

- `patient_intake -> patient_memory`
- `skill_routing / skill_loading -> skill_memory`
- `vlm_prompt_generation / visual_evidence -> image_memory`
- `diagnosis_report -> reasoning_memory`
- `memory_audit -> patient_memory,image_memory,skill_memory,reasoning_memory`
- `follow_up_qa -> patient_memory.qa_history`

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_case_replay_returns_agent_step_timeline -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle tests.test_http_entrypoint.HttpEntrypointTest.test_demo_case_qa_answers_from_artifact_visual_fact_usage -v
```

结果：标准 MemoryManager replay、真实 VLM+MedSAM2 demo replay、真实/标准 demo QA replay 和前端静态展示测试均已通过。

### 2026-05-25 Memory Audit 增加 Trace Consistency

本轮目标：`agents_traced`、`agent_io_summary` 和 `memory_replay.steps` 已经逐步对齐，但 audit 中还缺一个机器可读的 trace 一致性摘要。演示或调试时只能靠人工检查 key 顺序和 QA 扩展节点是否存在，不够直观。

新增/调整：

- 标准 `MemoryManager.build_audit_summary()` 增加 `trace_consistency`
- 真实 VLM+MedSAM2 demo audit 增加 `trace_consistency`
- 标准 demo artifact QA audit 追加 QA 节点后重新计算 `trace_consistency`
- 前端 fallback audit 增加同字段
- 前端 `Memory Trace` 增加 `Trace Consistency` 展示区

`trace_consistency` 字段包含：

- `agent_io_matches_trace`
- `required_agents_present`
- `missing_required_agents`
- `qa_extension_present`
- `agent_count`
- `agent_io_count`

当前语义：

- 初始病例应满足五个正式 Agent 全部存在、`agent_io_summary` key 与 `agents_traced` 完全一致
- 追问后 `qa_extension_present=true`，且 `GaoDoctorAgent QA` 作为扩展节点追加在 trace 末尾
- 如果后续某个 demo artifact 漏掉 Agent I/O 或错用旧 Agent 名，可以直接从 audit 中发现

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_audit_summary_writes_fake_output_report -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_qa_answers_from_evidence_bundle tests.test_http_entrypoint.HttpEntrypointTest.test_demo_case_qa_answers_from_artifact_visual_fact_usage -v
```

结果：标准 memory audit、真实 demo audit、真实/标准 demo QA audit 和前端静态展示测试均已通过。

### 2026-06-05 Current Goal Closure Scope 调整

本轮目标边界重新固定：真实 FHN 数据、真实 reference mask、真实 metric-ready benchmark manifest 由用户后续获取，本轮不再把这些内容作为整轮 goal 的收敛条件。

新增/调整：

- 新增 `docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md`
  - 明确 current goal 包含：五 Agent 证据链、FHN evidence protocol 样板、visual execution strategy、structured evidence bundle、bounded diagnosis report、QA、memory audit、segmentation benchmark 基础设施。
  - 明确 current goal 不包含：真实 FHN 标注数据、真实 mask、metric-ready 真实 benchmark、临床可靠分割质量宣称。
  - 明确真实数据到位后的下一阶段接入方式：放入 `benchmarks/segmentation/`，使用 `evaluator_type: binary_mask`、`reference_mask_path`、`prediction_mask_path` 和 `metric_gates`。
- README / 中文 README 的推荐下一步从“真实 FHN benchmark case 是当前紧邻工程项”改为“先收敛当前 MVP；等真实数据到位后再接入 benchmark”。
- 新增 `tests/test_goal_closure_scope.py`，防止 README 或 scope 文档再次把 deferred real-data validation 写成本轮必需项。

当前口径：

- 可以说：MedScope Agent MVP 的 evidence-bounded 架构、FHN evidence protocol 样板和 benchmark 基础设施已经具备可汇报基础。
- 不能说：已经完成真实 FHN benchmark、已经完成 metric-ready 真实 benchmark、X 光病灶分割质量已经临床验证。

验证：

```bash
python -m unittest tests.test_goal_closure_scope -v
```

结果：目标边界测试 `2` 个通过。

全量回归：

```bash
python -m unittest discover -v
```

结果：`423` 个测试通过，耗时 `66.161s`。

### 2026-06-05 Current MVP Demo Runbook 补齐

本轮目标：真实 FHN 数据和 mask 已明确后置后，需要补一个不依赖真实 FHN 标注数据的当前 MVP 演示 runbook，让组会或 fresh clone 使用者知道如何展示“上传/输入 -> 自动 skill routing -> 视觉证据 -> 诊断报告 -> evidence bundle -> memory audit -> follow-up QA”的主线。

新增/调整：

- 新增 `docs/CURRENT_MVP_DEMO_RUNBOOK_20260605.md`
  - 固定当前可演示链路：patient input + image upload -> automatic skill routing -> visual evidence -> diagnosis report -> evidence bundle -> memory audit -> follow-up QA。
  - 说明 `python -m scripts.prepare_public_demo_fixture` 生成公开安全合成输入，不是临床图像或 benchmark。
  - 说明 `python -m scripts.end_to_end_demo --suite` 用于展示当前 MVP 主线，而不是宣称视觉模型质量。
  - 说明 optional FHN no-mask demo 仍是 candidate evidence，不是 validated segmentation。
  - 明确 real FHN data and masks are deferred。
- README / 中文 README 增加 current MVP demo runbook 入口。
- 新增 `tests/test_current_mvp_demo_runbook.py`，确保 runbook 覆盖 upload、automatic skill routing、visual evidence、diagnosis report、evidence bundle、memory audit、follow-up QA 和 deferred data boundary。

验证：

```bash
python -m unittest tests.test_current_mvp_demo_runbook -v
```

结果：runbook 文档测试 `2` 个通过。

全量回归：

```bash
python -m unittest discover -v
```

结果：`425` 个测试通过，耗时 `63.011s`。

### 2026-06-05 Public-safe MVP Suite 补齐

本轮目标：README 已把下一步收敛到公开安全 fixture 覆盖上传、QA 和 memory audit。上一阶段只有 `prepare_public_demo_fixture()` 生成合成图和 payload，还没有一条可执行 suite 产出 service response、evidence bundle、memory audit 和 follow-up QA artifact。

新增/调整：

- `scripts/prepare_public_demo_fixture.py`
  - 新增 `run_public_safe_demo_suite()`
  - 新增 CLI 参数 `--suite`
  - suite 会生成公开安全合成图，运行 `MedScopeService`，写出：
    - `public_safe_response.json`
    - `public_safe_evidence_bundle.json`
    - `public_safe_memory_audit.json`
    - `public_safe_qa_response.json`
    - `public_safe_demo_summary.json`
    - `public_safe_demo_summary.md`
  - 内置 `PublicSafeNoMaskVisualRunner`，只生成 deterministic candidate evidence，不调用真实 VLM/API/MedSAM2，不使用真实 FHN 数据或 mask。
- `docs/CURRENT_MVP_DEMO_RUNBOOK_20260605.md`
  - 增加首选演示命令：
    `python -m scripts.prepare_public_demo_fixture --suite --output-dir output/fake/public_safe_demo_suite`
- README / 中文 README
  - 将公开安全 demo 从“只生成 fixture”升级为“public-safe MVP suite”，明确产出 response、evidence bundle、memory audit 和 follow-up QA。
- `tests/test_public_demo_fixture.py`
  - 覆盖 suite 函数和 CLI。

验证：

```bash
python -m unittest tests.test_public_demo_fixture tests.test_current_mvp_demo_runbook -v
```

结果：相关测试通过；public fixture 测试 `3` 个通过，runbook 测试 `2` 个通过。

全量回归：

```bash
python -m unittest discover -v
```

结果：`427` 个测试通过，耗时 `62.401s`。

### 2026-06-05 Runtime Environment Check 补齐

本轮目标：服务器部署时如果直接用 Python 3.7/3.8 运行 `python -m api.http_server`，会先遇到 `typing.Protocol`、`str.removeprefix` 或新语法相关错误，容易误判成 API 或路由 bug。项目本身已经在 `pyproject.toml` 声明 Python `>=3.10`，但需要一个启动前可执行的检查入口。

新增/调整：

- 新增 `scripts/check_runtime_environment.py`
  - 输出 `runtime_environment_readiness.v1` JSON。
  - 明确当前 Python 版本、解释器路径、是否满足 `>=3.10`。
  - 旧版本时返回 `ready=false` 和可执行 action items。
- README / 中文 README / current MVP demo runbook
  - 在启动 HTTP 服务前增加：
    `python -m scripts.check_runtime_environment`
- `tests/test_runtime_environment.py`
  - 覆盖 Python 3.10 ready、Python 3.8 not_ready、CLI JSON 输出。
- `tests/test_current_mvp_demo_runbook.py`
  - 确认 runbook 保留 runtime check 命令。

验证：

```bash
python -m unittest tests.test_runtime_environment tests.test_current_mvp_demo_runbook -v
```

结果：runtime environment 和 runbook 测试通过。

全量回归：

```bash
python -m unittest discover -v
```

结果：`431` 个测试通过，耗时 `91.676s`。

### 2026-06-05 Public-safe Demo HTTP Endpoint 补齐

本轮目标：public-safe MVP suite 已经能通过 CLI 跑通，但服务器/前端演示时还需要一个 HTTP 入口，避免部署后必须手动进入 shell 先跑脚本。

新增/调整：

- `api/http_server.py`
  - 新增 `GET /v1/demo/public-safe`
  - 调用 `run_public_safe_demo_suite(output_dir=<output_root>/fake/public_safe_demo_suite)`
  - 返回 suite summary，并生成 response、evidence bundle、memory audit 和 follow-up QA artifact。
- `web/app.js`
  - 新增 `fetchPublicSafeDemo()`，让前端静态资源中显式保留 public-safe demo route。
- README / 中文 README / current MVP runbook
  - 记录 `GET /v1/demo/public-safe`。
- `tests/test_http_entrypoint.py`
  - 覆盖 endpoint 生成 suite 且不需要真实 FHN 数据。
  - 覆盖前端静态资源包含 `/v1/demo/public-safe`。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_public_safe_demo_endpoint_generates_suite_without_real_data tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
```

补充验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_public_safe_demo_endpoint_generates_suite_without_real_data tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_current_mvp_demo_runbook tests.test_goal_closure_scope -v
python -m unittest discover -v
node --check web/app.js
git diff --check
```

结果：Public-safe HTTP endpoint 定向测试、前端静态资源检查、runbook/scope 文档守卫、JS 语法检查、diff 空白检查与全量 `431` 个 unittest 通过。本轮不需要真实 FHN 数据、真实 mask 或 benchmark manifest；这些保持为后续数据到位后的验证项。

### 2026-06-05 Public-safe Demo 前端入口补齐

本轮目标：上一阶段已经有 `GET /v1/demo/public-safe`，但前端只能通过未使用的 `fetchPublicSafeDemo()` 引用该 route；演示时仍需要手动 curl，不够直接。

新增/调整：

- `web/index.html`
  - 在病例输入样例区新增 `运行 Public-safe MVP 样例` 按钮。
  - 前端 cache buster 更新到 `frontend-demo-20260605`，避免浏览器继续使用旧 JS。
- `web/app.js`
  - 新增 `publicSafeDemoButton` 元素引用。
  - 新增 `runPublicSafeDemo()`，点击后直接调用 `/v1/demo/public-safe`，并用现有 `renderPayload()` 展示病例 response。
  - 将按钮纳入 `setCasePending()`，运行中不能重复点击。
- `api/http_server.py`
  - `GET /v1/demo/public-safe` 现在返回可直接渲染的病例 payload，同时保留 `public_safe_demo_summary`、artifact paths、safety、evidence bundle、memory audit 和 demo QA response。
- README / 中文 README / current MVP runbook
  - 记录前端按钮和 HTTP endpoint 的关系。
- `tests/test_http_entrypoint.py`
  - 覆盖前端按钮存在、JS 事件入口存在、cache buster 更新、endpoint 返回可渲染 payload。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_public_safe_demo_endpoint_generates_suite_without_real_data tests.test_http_entrypoint.HttpEntrypointTest.test_root_serves_interactive_frontend tests.test_http_entrypoint.HttpEntrypointTest.test_root_frontend_assets_use_current_cache_buster tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest discover -v
```

结果：public-safe endpoint、前端按钮、cache buster、JS 语法检查和全量 `431` 个 unittest 通过；完整回归耗时 `62.560s`。

### 2026-06-05 Public-safe Demo QA Artifact 路由补齐

本轮目标：`运行 Public-safe MVP 样例` 已能在前端展示病例，但该病例由 suite 私有 memory 目录生成；如果追问继续走普通 `/v1/medscope`，默认服务 memory 查不到这个 case，演示时 QA 会失败。

新增/调整：

- `api/http_server.py`
  - 新增 `POST /v1/demo/public-safe/qa`。
  - QA 优先读取已有 `output/fake/public_safe_demo_suite/public_safe_demo_summary.json`，没有时才生成 suite，避免追问时 case_id 被刷新。
  - 返回 `demo_source=public_safe_demo_suite`、`qa_source=public_safe_demo_artifact`、`evidence_bundle`、`memory_audit`、`memory_replay`。
- `web/app.js`
  - 新增 `publicSafeDemoMode`。
  - public-safe payload 渲染后打开该模式。
  - 追问时优先调用 `postPublicSafeDemoQa()`，走 `/v1/demo/public-safe/qa`，不再误走实时病例 memory。
- README / 中文 README / current MVP runbook
  - 记录 public-safe demo QA 的 artifact-bound 路由。
- `tests/test_http_entrypoint.py`
  - 覆盖 public-safe demo QA 使用已有 demo artifact、case_id 不变化、追加 `GaoDoctorAgent QA` replay/audit 节点。
  - 覆盖前端静态 JS 包含 public-safe QA mode 和 `/v1/demo/public-safe/qa`。

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_public_safe_demo_qa_answers_from_demo_artifact_not_live_memory tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
```

补充验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_public_safe_demo_endpoint_generates_suite_without_real_data tests.test_http_entrypoint.HttpEntrypointTest.test_public_safe_demo_qa_answers_from_demo_artifact_not_live_memory tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_current_mvp_demo_runbook tests.test_goal_closure_scope -v
node --check web/app.js
git diff --check
python -m unittest discover -v
```

结果：public-safe demo artifact-bound QA 后端、前端静态路由、文档守卫、JS 语法检查、diff 空白检查和全量 `432` 个 unittest 通过；完整回归耗时 `62.291s`。

### 2026-06-05 Public-safe README API / Next Step 守卫补齐

本轮目标：`POST /v1/demo/public-safe/qa` 已经成为当前演示 API，但 README 的常用接口列表还只列 `GET /v1/demo/public-safe`；同时 README/中文 README 的建议下一步仍把已经完成的 public-safe suite 扩展写成待办，容易误导后续收敛判断。

新增/调整：

- README / 中文 README
  - 常用接口列表新增 `POST /v1/demo/public-safe/qa`。
  - 建议下一步把 public-safe suite 扩展从待办改为：保持 public-safe HTTP/前端 demo 作为后续报告、QA 和 memory audit UI 改动的 smoke gate。
- `tests/test_current_mvp_demo_runbook.py`
  - 新增 README 守卫，确认 public-safe QA route 出现在 API 列表里。
  - 确认已完成的 public-safe fixture 扩展不再作为推荐下一步出现。

RED：

```bash
python -m unittest tests.test_current_mvp_demo_runbook.CurrentMvpDemoRunbookTest.test_readmes_document_public_safe_qa_route_as_current_api -v
```

结果：测试按预期失败，README API 列表缺少 `POST /v1/demo/public-safe/qa`。

GREEN / 补充验证：

```bash
python -m unittest tests.test_current_mvp_demo_runbook -v
git diff --check
python -m unittest discover -v
```

结果：README/runbook 文档守卫、diff 空白检查和全量 `433` 个 unittest 通过；完整回归耗时 `61.359s`。

### 2026-06-05 Public-safe Runbook 前端 Smoke 顺序守卫补齐

本轮目标：current MVP runbook 已经说明前端有 `运行 Public-safe MVP 样例` 按钮，但 `Recommended demonstration order` 仍写成先上传 public-safe image、输入症状、再运行分析。这和当前最稳的 public-safe HTTP/frontend smoke path 不一致，容易让演示者绕开 artifact-bound QA 路由。

新增/调整：

- `docs/CURRENT_MVP_DEMO_RUNBOOK_20260605.md`
  - 推荐演示顺序改为先点击 `运行 Public-safe MVP 样例`。
  - 明确确认 `demo_source=public_safe_demo_suite`。
  - 追问步骤明确应走 `POST /v1/demo/public-safe/qa` artifact-bound QA route。
  - 说明 generic upload/run-analysis path 只用于刻意测试上传；public-safe smoke demo 优先用专用按钮。
- `tests/test_current_mvp_demo_runbook.py`
  - 新增 runbook 守卫，确认推荐顺序包含前端按钮、QA route 和 `artifact-bound`。
  - 确认推荐顺序不再以 `Load or upload a public-safe image.` 开头。

RED：

```bash
python -m unittest tests.test_current_mvp_demo_runbook.CurrentMvpDemoRunbookTest.test_runbook_recommends_frontend_public_safe_button_for_smoke_demo -v
```

结果：测试按预期失败，推荐顺序缺少 `运行 Public-safe MVP 样例`。

GREEN / 补充验证：

```bash
python -m unittest tests.test_current_mvp_demo_runbook -v
git diff --check
python -m unittest discover -v
```

结果：runbook 文档守卫、diff 空白检查和全量 `434` 个 unittest 通过；完整回归耗时 `60.900s`。

### 2026-06-05 中文 README Readiness Route 守卫补齐

本轮目标：英文 README 的常用接口列表已经包含 `GET /v1/readiness`，但中文 README 的常用接口列表漏掉该 route；这会让中文演示/部署说明少一个 HTTP readiness 入口。

新增/调整：

- `README.zh-CN.md`
  - 常用接口列表新增 `GET /v1/readiness`。
- `tests/test_current_mvp_demo_runbook.py`
  - README API 守卫同时检查英文和中文 API 列表都包含 `GET /v1/readiness`。

RED：

```bash
python -m unittest tests.test_current_mvp_demo_runbook.CurrentMvpDemoRunbookTest.test_readmes_document_public_safe_qa_route_as_current_api -v
```

结果：测试按预期失败，中文 README 常用接口列表缺少 `GET /v1/readiness`。

GREEN / 补充验证：

```bash
python -m unittest tests.test_current_mvp_demo_runbook -v
git diff --check
python -m unittest discover -v
```

结果：README/runbook 文档守卫、diff 空白检查和全量 `434` 个 unittest 通过；完整回归耗时 `63.539s`。

### 2026-06-05 Public-safe 前端 Demo Source 可见性补齐

本轮目标：runbook 推荐演示顺序要求确认 `demo_source=public_safe_demo_suite`，但前端此前只把 `demo_source` 用于内部 QA route 状态切换，演示者没有一个直接可见的位置确认当前病例来自 public-safe demo artifact。

新增/调整：

- `web/app.js`
  - 新增 `renderDemoSourceSummary()`。
  - `renderVisualOutput()` 在患者可见影像摘要上方显示 `Demo / Artifact Source`，包含 `demo_source`、`qa_source` 和 `case_id` 中存在的字段。
  - 普通实时病例没有这些字段时不额外显示该区块。
- `tests/test_http_entrypoint.py`
  - 前端静态资源守卫新增 `renderDemoSourceSummary` 和 `demo_source: payload.demo_source`，防止 runbook 的确认步骤失去 UI 依据。

RED：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
```

结果：测试按预期失败，前端静态 JS 中缺少 `renderDemoSourceSummary`。

GREEN / 补充验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_public_safe_demo_endpoint_generates_suite_without_real_data tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_current_mvp_demo_runbook tests.test_goal_closure_scope -v
git diff --check
python -m unittest discover -v
```

结果：前端静态守卫、JS 语法检查、public-safe HTTP/doc targeted 测试、diff 空白检查和全量 `434` 个 unittest 通过；完整回归耗时 `59.517s`。

### 2026-06-05 Public-safe 前端 QA Source 可见性补齐

本轮目标：`Demo / Artifact Source` 已能在初始 public-safe demo payload 中显示 `demo_source=public_safe_demo_suite`，但 follow-up QA 返回的 `qa_source=public_safe_demo_artifact` 只存在于 QA payload 里；前端没有把它合并回视觉摘要状态，演示者追问后无法直接确认 QA 来自 artifact-bound route。

新增/调整：

- `web/app.js`
  - `renderQaPayload()` 将 `demo_source` 和 `qa_source` 合并进 `state.lastPayload`。
  - 当 QA payload 带有 source 字段时重新调用 `renderVisualOutput(state.lastPayload)`，让 `Demo / Artifact Source` 在追问后展示 `qa_source`。
  - 普通 QA 不带 source 字段时保持原来的 memory audit 渲染路径。
- `tests/test_http_entrypoint.py`
  - 前端静态资源守卫新增 `qa_source: payload.qa_source || state.lastPayload.qa_source`。
  - 同一守卫确认 QA source 存在时会调用 `renderVisualOutput(state.lastPayload)`。

RED：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
```

结果：测试按预期失败，前端静态 JS 中缺少 `qa_source: payload.qa_source || state.lastPayload.qa_source`。

GREEN / 补充验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_public_safe_demo_endpoint_generates_suite_without_real_data tests.test_http_entrypoint.HttpEntrypointTest.test_public_safe_demo_qa_answers_from_demo_artifact_not_live_memory tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist tests.test_current_mvp_demo_runbook tests.test_goal_closure_scope -v
git diff --check
python -m unittest discover -v
```

结果：前端静态守卫、JS 语法检查、public-safe HTTP/QA/doc targeted 测试、diff 空白检查和全量 `434` 个 unittest 通过；完整回归耗时 `60.658s`。

### 2026-06-05 Public-safe Fixture 质量边界 README 守卫补齐

本轮目标：回到当前 MVP closure 主线，避免把上一轮 QA 可见性小补丁误当作整轮目标。public-safe suite 的核心用途是 smoke/readiness 和证据链演示，不是证明病灶检测质量；runbook 已有 meeting-safe/avoid 表述，但 README 英/中文段落还没有被测试守住这条边界。

新增/调整：

- `README.md`
  - public-safe suite 段落新增 `It does not prove lesion detection quality.`。
- `README.zh-CN.md`
  - 对齐新增 `它不证明病灶检测质量。`。
- `tests/test_current_mvp_demo_runbook.py`
  - README public-safe 段落守卫新增英文/中文“不证明病灶检测质量”断言。

RED：

```bash
python -m unittest tests.test_current_mvp_demo_runbook.CurrentMvpDemoRunbookTest.test_readmes_document_public_safe_qa_route_as_current_api -v
```

结果：测试按预期失败，英文 README public-safe 段落缺少 `does not prove lesion detection quality`。

GREEN / 补充验证：

```bash
python -m unittest tests.test_current_mvp_demo_runbook tests.test_goal_closure_scope -v
git diff --check
python -m unittest discover -v
```

结果：current MVP runbook/scope 文档守卫、diff 空白检查和全量 `434` 个 unittest 通过；完整回归耗时 `59.537s`。

### 2026-06-05 Benchmark 结果隔离 README 守卫补齐

本轮目标：继续 current closure audit。scope 已要求 benchmark 结果不能进入临床诊断、正式 skill promotion 或 self-evolving guideline updates；代码层面已有 segmentation benchmark 行为测试守住 `diagnosis_allowed=false` 和 `formal_skill_update_allowed=false`，但 README 的 Current Review 面向使用者段落还没有明确写出这个隔离边界。

新增/调整：

- `README.md`
  - Important limitations 增加：`Benchmark results do not update clinical diagnosis or formal skills; they only report validation metrics and quality-gate status.`。
- `README.zh-CN.md`
  - 项目 Review 风险段增加：`benchmark 结果不会更新临床诊断或正式 skill，只报告验证指标和质量门状态。`。
- `tests/test_current_mvp_demo_runbook.py`
  - 新增 README 英/中文守卫，确认 benchmark 结果隔离边界留在 Current Review 段。

RED：

```bash
python -m unittest tests.test_current_mvp_demo_runbook.CurrentMvpDemoRunbookTest.test_readmes_document_benchmark_results_do_not_update_diagnosis_or_skills -v
```

结果：测试按预期失败，英文 README Current Review 段缺少 `Benchmark results do not update clinical diagnosis or formal skills`。

GREEN / 补充验证：

```bash
python -m unittest tests.test_current_mvp_demo_runbook.CurrentMvpDemoRunbookTest.test_readmes_document_benchmark_results_do_not_update_diagnosis_or_skills tests.test_current_mvp_demo_runbook tests.test_goal_closure_scope tests.test_segmentation_benchmark.SegmentationBenchmarkTest.test_metric_ready_case_applies_manifest_quality_gate_without_diagnosis_upgrade -v
git diff --check
python -m unittest discover -v
```

结果：README benchmark 隔离守卫、current MVP runbook/scope 守卫、segmentation benchmark 质量门行为测试、diff 空白检查和全量 `435` 个 unittest 通过；完整回归耗时 `76.104s`。

### 2026-06-05 Current Goal Completion Audit 补齐

本轮目标：继续 current closure audit，把 `CURRENT_GOAL_CLOSURE_SCOPE_20260605.md` 中的 included/deferred 要求映射到当前代码、文档和测试证据，避免只靠 scope 文案判断目标是否收敛。

新增/调整：

- `docs/CURRENT_GOAL_COMPLETION_AUDIT_20260605.md`
  - 新增 requirement-to-evidence 表，覆盖五代理临床证据流水线、FHN evidence-protocol sample path、segmentation benchmark infrastructure、benchmark 结果隔离、README/中文 README 对齐。
  - 明确 deferred evidence：真实 FHN 数据、真实 mask、metric-ready real benchmark manifest、临床可靠 FHN X-ray lesion segmentation 均未完成且不属于当前 closure。
  - 记录 full regression 和 focused guard 命令。
- `docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md`
  - 链接 completion audit 文档。
- `README.md` / `README.zh-CN.md`
  - 文档入口链接 completion audit。
- `tests/test_goal_closure_scope.py`
  - 新增 audit 文档存在性、scope-to-evidence 关键短语、deferred 边界和 README 链接守卫。

RED：

```bash
python -m unittest tests.test_goal_closure_scope.GoalClosureScopeTest.test_current_goal_completion_audit_maps_scope_to_evidence tests.test_goal_closure_scope.GoalClosureScopeTest.test_project_readmes_link_current_goal_completion_audit -v
```

结果：测试按预期失败，completion audit 文档不存在，README 英/中文也没有链接。

GREEN / 补充验证：

```bash
python -m unittest tests.test_goal_closure_scope tests.test_current_mvp_demo_runbook -v
git diff --check
python -m unittest discover -v
```

结果：goal scope/completion audit/runbook 文档守卫、diff 空白检查和全量 `437` 个 unittest 通过；完整回归耗时 `78.189s`。

### 2026-06-05 Scope Verification Guard 列表对齐

本轮目标：completion audit 已加入后，`CURRENT_GOAL_CLOSURE_SCOPE_20260605.md` 的 full regression 说明仍只列到 `demo/QA-source visibility guard`，没有把后续新增的 public-safe fixture 质量边界、benchmark 结果隔离和 completion audit 守卫写进去。该文档是当前 goal closure 的边界说明，验证来源列表不能滞后。

新增/调整：

- `tests/test_goal_closure_scope.py`
  - scope 文档守卫新增 `public-safe fixture quality boundary guard`、`benchmark result isolation guard` 和 `completion audit guard` 断言。
- `docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md`
  - Current Verification Baseline 段补齐上述三个 guard，保持 `437 tests passed` 的来源说明与当前测试集一致。
- `README.md`、`README.zh-CN.md`、`docs/CURRENT_GOAL_COMPLETION_AUDIT_20260605.md`、`goalnew.md`
  - 同步本轮实际 full regression 结果：`437 tests in 76.867s`。

RED：

```bash
python -m unittest tests.test_goal_closure_scope.GoalClosureScopeTest.test_current_goal_scope_defers_real_fhn_data_without_claiming_real_benchmark -v
```

结果：测试按预期失败，scope 文档缺少 `public-safe fixture quality boundary guard`。

GREEN / 补充验证：

```bash
python -m unittest tests.test_goal_closure_scope tests.test_current_mvp_demo_runbook -v
git diff --check
python -m unittest discover -v
```

结果：goal scope/completion audit/runbook 文档守卫、diff 空白检查和全量 `437` 个 unittest 通过；完整回归耗时 `76.867s`。

### 2026-05-25 QA Safety 补充 Evidence Bundle 使用计数

本轮目标：追问链路已经能通过 `GaoDoctorAgent QA` 展示为 evidence bundle 约束下的后续回答，但 `QA Safety` 区块只展示 `evidence_bundle_required` 和 QA 数量，没有明确显示有多少条追问实际使用了 evidence bundle。

新增/调整：

- `MemoryManager.build_audit_summary()` 的 `qa_safety` 新增：
  - `evidence_bundle_used_count`
- 计数来源为 `patient_memory.qa_history[*].evidence_bundle_used`
- 前端 `renderQaSafety()` 新增展示：
  - `evidence_bundle_used`
  - `evidence_bundle_used_count`
- 保留原有：
  - `qa_history_count`
  - `llm_used_count`
  - `fallback_count`
  - `missing_or_unassessed_count`
  - blocked scopes

当前语义：

- `evidence_bundle_required` 表示系统要求 QA 必须受 evidence bundle 约束
- `evidence_bundle_used_count` 表示已有多少条追问记录实际声明使用了 evidence bundle
- demo artifact 的布尔 `evidence_bundle_used` 与真实病例 memory 的计数字段都能被前端展示

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_audit_summary_includes_follow_up_qa_agent_after_qa -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
```

结果：MemoryManager QA audit、前端静态资源测试与 JS 语法检查已通过。

补充验证：

```bash
python -m unittest tests.test_memory_manager -v
python -m unittest tests.test_http_entrypoint -v
python -m unittest tests.test_service_entrypoint -v
python -m unittest discover -v
curl -s http://127.0.0.1:8022/static/app.js | rg "evidence_bundle_used_count|evidence_bundle_used"
```

结果：MemoryManager、HTTP、Service 相关测试与全量 `291` 个 unittest 均通过；8022 演示服务已能读取包含 `evidence_bundle_used_count` 的新前端文件。

### 2026-05-25 真实 Demo Memory Type Details 补齐四类 Memory

本轮目标：真实 VLM+MedSAM2 demo 的 `memory_audit.memory_type_details` 需要和前端“四类 Memory”说明一致，并且 `image_memory` 必须承接同一份 enriched `image_outputs`，避免主响应能显示三联图、审计链却缺少 preview 路径。

新增/调整：

- 真实 VLM+MedSAM2 response / QA 构建 `memory_audit` 时传入 enriched `image_outputs`
- `patient_memory`、`image_memory`、`skill_memory`、`reasoning_memory` 四类 detail 保持固定顺序输出
- `image_memory` 新增：
  - `original_preview_path`
  - `localization_overlay_path`
  - `mask_preview_path`
- 前端 fallback 构建真实 VLM+MedSAM2 payload 时，从 VLM prompt artifact 补齐：
  - `slice_png_path -> original_preview_path`
  - `bbox_overlay_path -> localization_overlay_path`
- 前端 fallback 的 `memory_type_details.image_memory` 同步展示 preview 字段

当前语义：

- `patient_memory` 记录病例输入与 intent
- `image_memory` 记录原图/定位/分割/叠加图和视觉质量
- `skill_memory` 记录选择的 skill、vision mode、指南型 skill 状态和证据不足要求
- `reasoning_memory` 记录诊断报告使用的模型、fallback 与诊断倾向

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_real_vlm_medsam2_demo_artifacts_are_served_from_output_fake -v
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
```

结果：目标 API 行为测试、前端静态资源测试与 JS 语法检查已通过。

### 2026-05-25 前端 Memory Trace 增加五 Agent 主线展示

本轮目标：用户希望按五个 Agent 解释“信息输入高医生之后主线怎么协作”。之前系统已经有 `agents_traced` 和 `agent_io_summary`，但前端主要以列表/字段形式展示，不够像一条可演示主线。

新增/调整：

- `Memory Trace` 新增 `五 Agent 主线` 区块
- 新增 `renderAgentFlowSummary(audit)`，按固定五阶段展示：
  - `GaoDoctorAgent`：入口分诊
  - `SkillBuilderAgent`：指南 / Skill
  - `VisionAgent`：视觉分割
  - `DiagnosisDoctorAgent`：诊断推理
  - `MemoryManager`：记忆审计
- 每个阶段展示：
  - agent 名称
  - 对应 memory 类型
  - 当前职责说明
  - 从 `agent_io_summary` 抽取的关键指标
- 新增 `.agent-flow-list` / `.agent-flow-item` 样式，保持紧凑、可扫描、不替代原始 Agent I/O 明细

当前语义：

- `Agent Trace` 仍保留原始 agent 列表
- `Agent I/O` 仍保留结构化输入输出明细
- `五 Agent 主线` 用于演示时快速说明“患者输入 -> skill 路由 -> 视觉分割 -> 诊断推理 -> memory audit”的协作链

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
python -m unittest tests.test_http_entrypoint -v
```

结果：目标前端静态测试、JS 语法检查与 HTTP 入口测试已通过。

### 2026-05-25 MemoryManager 追问 QA 纳入 Agent Audit

本轮目标：`append_qa_memory` 已经能把追问保存到 `patient_memory.qa_history` 和 `qa_memory`，但 `build_audit_summary` 的 `agents_traced / agent_io_summary` 仍然只显示初始五个 Agent，追问链路在审计中不够显式。

新增/调整：

- 当 `patient_memory.qa_history` 非空时，`build_audit_summary` 自动追加 `GaoDoctorAgent QA`
- `agent_io_summary["GaoDoctorAgent QA"]` 记录最后一条追问：
  - question
  - answer
  - evidence_bundle_used
  - llm_used
  - llm_fallback_reason
- `agent_io_summary` 的 key 顺序继续严格跟随 `agents_traced`
- `qa_safety` 和 `memory_type_details.patient_memory.qa_history_count` 继续使用同一份 qa history 计数

当前语义：

- 初始诊断仍是五 Agent 主线
- 发生追问后，审计链显式变成：
  - `GaoDoctorAgent`
  - `SkillBuilderAgent`
  - `VisionAgent`
  - `DiagnosisDoctorAgent`
  - `MemoryManager`
  - `GaoDoctorAgent QA`
- 追问回答仍必须声明使用 evidence bundle，不能脱离病例证据自由发挥

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_audit_summary_includes_follow_up_qa_agent_after_qa -v
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_audit_summary_writes_fake_output_report -v
```

结果：新增 QA agent audit 测试和原五 Agent audit 回归测试已通过。

补充验证：

```bash
python -m unittest tests.test_memory_manager -v
python -m unittest tests.test_http_entrypoint -v
node --check web/app.js
python -m unittest discover -v
```

结果：MemoryManager 测试、HTTP 入口测试、JS 语法检查与全量 `290` 个 unittest 均通过。8020 已有旧服务占用，已在 `http://127.0.0.1:8021` 启动加载最新代码的演示服务。

### 2026-05-25 Memory Replay 追问节点与 Agent Audit 命名对齐

本轮目标：上一阶段 `memory_audit.agents_traced` 已经在追问后追加 `GaoDoctorAgent QA`，但 `memory_replay.steps` 中的追问步骤仍显示为 `GaoDoctorAgent`，导致前端 `Agent Trace` 和 `Memory Replay` 对同一条追问的命名不一致。

新增/调整：

- `MemoryManager.build_case_replay()` 中 `follow_up_qa` 步骤的 `agent` 改为 `GaoDoctorAgent QA`
- 保持 `event: follow_up_qa`、question、answer、evidence_bundle_used、llm_used、llm_fallback_reason 字段不变
- 新增 Service 前门测试，确认 QA 响应返回的：
  - `memory_audit.agents_traced[-1] == "GaoDoctorAgent QA"`
  - `memory_replay.steps[-1].agent == "GaoDoctorAgent QA"`
  - `memory_replay.steps[-1].event == "follow_up_qa"`

当前语义：

- 初始病例仍是五 Agent 主线
- 追问不是重新跑视觉/诊断全链路，而是作为 `GaoDoctorAgent QA` 节点基于已有 evidence bundle 回答
- 前端 `Agent Trace`、`Agent I/O`、`Memory Replay` 对追问节点的命名保持一致

验证：

```bash
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_case_replay_returns_agent_step_timeline -v
python -m unittest tests.test_memory_manager.MemoryManagerQueryTest.test_build_audit_summary_includes_follow_up_qa_agent_after_qa -v
python -m unittest tests.test_service_entrypoint.MedScopeServiceEntrypointTest.test_service_qa_response_attaches_follow_up_agent_memory_trace -v
```

结果：Memory replay、Memory audit 和 Service 前门 QA memory trace 测试已通过。

补充验证：

```bash
python -m unittest tests.test_memory_manager -v
python -m unittest tests.test_service_entrypoint -v
python -m unittest tests.test_http_entrypoint -v
python -m unittest discover -v
```

结果：MemoryManager、Service、HTTP 入口测试与全量 `291` 个 unittest 均通过。8021 旧服务仍在运行且当前会话无法停止，已在 `http://127.0.0.1:8022` 启动加载最新代码的演示服务。

### 2026-05-25 前端五 Agent 主线支持 QA 扩展节点

本轮目标：底层 `memory_audit` 和 `memory_replay` 已经把追问统一命名为 `GaoDoctorAgent QA`，但前端 `五 Agent 主线` 区块仍固定显示初始五段，追问场景下看不出 QA 是基于已有 memory/evidence bundle 的后续节点。

新增/调整：

- `renderAgentFlowSummary(audit)` 在检测到 `agent_io_summary["GaoDoctorAgent QA"]` 时动态追加第六个展示节点
- 追加节点标题为 `追问回答`
- 追加节点 memory 标注为 `patient_memory.qa_history`
- 追加节点说明：基于已有 evidence bundle 回答追问，不重新解释缺失证据，也不脱离病例记忆
- 节点指标展示：
  - question
  - evidence_bundle_used
  - llm_used
  - llm_fallback_reason
  - qa_source

当前语义：

- 没有追问时，前端仍显示标准五 Agent 主线
- 有追问时，前端显示“标准五 Agent 主线 + GaoDoctorAgent QA 扩展节点”
- QA 不被误解为重新跑视觉/诊断全链路，而是明确展示为基于已有 evidence bundle 的后续回答

验证：

```bash
python -m unittest tests.test_http_entrypoint.HttpEntrypointTest.test_static_frontend_assets_are_served_from_allowlist -v
node --check web/app.js
```

结果：前端静态资源测试与 JS 语法检查已通过。
