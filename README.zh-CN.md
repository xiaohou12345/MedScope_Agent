# MedScope Agent 中文说明

MedScope Agent 是一个实验性的医疗多 Agent / Agentic Runtime 项目，目标是把“患者描述 + 医疗图像 + 医学指南 Skill”组织成一条可追踪、可审计、受证据约束的临床证据流水线。

本项目是科研原型，不是医疗器械，不能用于真实临床诊断或治疗决策。

英文说明见 [README.md](README.md)。

## 项目定位

MedScope 不是简单把系统拆成很多 Agent。更准确的说法是：

```text
上层：Clinical Evidence Pipeline 临床证据流水线
  Clinical Orchestrator
    -> Skill Gateway / Skill Builder
    -> Vision Evidence Agent
    -> Diagnosis Reasoning Agent
    -> Memory / Audit Layer

下层：Agentic Runtime / Evidence Gateway
  Skill 分发
  共享 artifact 工作区
  工具路由
  契约和安全守卫
  stop hooks / reflection hooks
  candidate queue / validation gate
```

一句话概括：

> MedScope 把医疗诊断拆成一条受指南和证据约束的执行链路：视觉 Agent 只负责观察、定位、分割和测量；诊断 Agent 只消费结构化 evidence bundle；Memory/Audit 记录证据链；Gateway 负责 skill、文件、工具、契约和候选更新的统一管理。

## 当前已经实现的能力

- 支持 `skills/` 中的正式 guideline skill。
- 支持根据患者描述、症状、图像路径线索自动选择 skill。
- 支持 Vision Agent 根据 skill 的 `visual_protocol` 输出结构化视觉证据。
- 支持参考 mask、VLM-only、VLM+MedSAM2 候选分割、MedSAM2 runner 等多种视觉路径。
- 支持诊断 Agent 只读取 evidence bundle，不直接读取原始图像。
- 支持缺失证据安全边界：缺失 T1ce、MRI、mask 等不能被写成阴性或 0。
- 支持四类 memory：`patient_memory`、`image_memory`、`skill_memory`、`reasoning_memory`。
- 支持 follow-up QA 基于 evidence bundle 回答，避免脱离当前病例证据。
- 支持前端上传、Thinking 状态、影像发现、诊断报告、evidence bundle、memory audit 展示。
- 支持 prompt baseline，用于比较普通 LLM/Codex 式提示词和 evidence-bounded pipeline 的差异。

## 五个实现模块应该怎么讲

代码里仍然有几个实现类，但对外汇报时不建议讲成“五个平铺 Agent”。

更建议这样讲：

- `Clinical Orchestrator`：对应 `agents/gaodoctor_agent.py`，负责患者入口、意图识别、skill 路由、流程调度和 QA。
- `Vision Evidence Agent`：对应 `agents/vision_agent.py` 和视觉工具，只输出视觉证据、mask、overlay、数值测量和证据充分性。
- `Diagnosis Reasoning Agent`：对应 `agents/diagnosis_agent.py`，只根据 skill 和 evidence bundle 生成报告。
- `Skill Builder / Guideline Component`：条件触发组件。已有 skill 时加载和校验；缺 skill 时才检索指南、抽取规则、生成候选或正式 skill。
- `Memory / Audit Layer`：基础设施，不参与医学判断，只保存四类 memory、evidence bundle、runtime trace、audit 和 replay。

底层的 `Evidence Gateway` 才是系统扩展性的核心：

- 管理 skill 和 visual protocol。
- 管理上传图片、mask、overlay、报告和 audit artifact。
- 根据 skill 和图像模态选择视觉工具。
- 用 contract guard 限制 Agent 输入输出。
- 用 stop hook 检查证据缺口和越界诊断。
- 用 candidate queue 保存候选经验，但不自动改写正式医学指南。

详细说明：

- [docs/architecture/boundaries.md](docs/architecture/boundaries.md)
- [docs/CURRENT_MVP_DEMO_RUNBOOK_20260605.md](docs/CURRENT_MVP_DEMO_RUNBOOK_20260605.md)
- [docs/FHN_REAL_VLM_VALIDATION_20260604.md](docs/FHN_REAL_VLM_VALIDATION_20260604.md)
- [docs/DUAL_PATH_AGENT_FRAMEWORK.md](docs/DUAL_PATH_AGENT_FRAMEWORK.md)
- [docs/AGENT_FLOW.zh-CN.md](docs/AGENT_FLOW.zh-CN.md)

## 目录结构

```text
agents/       高医生/视觉/诊断/报告等实现
api/          HTTP API 和统一 service 入口
contracts/    Agent、Tool、Memory、Report 之间的数据契约
docs/         架构说明、API 路由、数据集和 MedSAM2 配置文档
llm/          OpenAI-compatible 模型调用封装
memory/       JSON memory、evidence bundle、audit、runtime trace
prompts/      诊断、高医生和 baseline prompt
scripts/      demo、评测脚本、数据集探针、MedSAM2 wrapper
skills/       疾病 skill、指南来源、visual protocol
tests/        单元测试和集成测试
tools/        指南、视觉、分割、测量、路由工具
web/          静态前端
```

以下内容默认不上传 GitHub：

- `output/`、`outputs/`
- `data/external/`、`data/cases/`、`data/images/`、`data/masks/`、`data/overlays/`
- DICOM/NIfTI 文件、模型权重
- `.env.local` 等本地密钥文件

## 当前 Skill

正式 skill 文件：

- `skills/femoral_head_necrosis.yaml`：股骨头坏死
- `skills/diffuse_glioma_brats.yaml`：成人弥漫性胶质瘤 / BraTS
- `skills/idiopathic_pulmonary_fibrosis_hrct.yaml`：特发性肺纤维化 HRCT
- `skills/pneumonia_chest_xray.yaml`：肺炎胸片

注意：这些文件扩展名是 `.yaml`，但当前内容是 JSON-compatible 格式，代码用 Python 标准库 `json` 加载。

## 环境要求

建议环境：

- Python 3.10+
- 核心安装：Pillow
- 可选视觉流程：NumPy 和 nibabel
- 可选真实分割：PyTorch + 外部 MedSAM2 仓库

本地开发建议用 editable install：

```bash
python -m pip install -e .
```

如果要运行 NIfTI/BraTS、图像指标和视觉 demo，安装 vision 依赖：

```bash
python -m pip install -e ".[vision]"
```

如果要运行完整本地测试和 demo：

```bash
python -m pip install -e ".[dev]"
```

## 模型 API 配置

模型路由统一放在 [docs/API_ROUTE_LOG.md](docs/API_ROUTE_LOG.md)。

真实模型调用需要环境变量：

```bash
export DMX_API_KEY="..."
# 或
export KY_API_KEY="..."
```

Agent 代码不应直接写 provider-specific 逻辑，只通过 `llm/` 中的统一接口调用。

## MedSAM2 配置

MedSAM2 是可选外部分割后端。需要真实调用时配置：

```bash
export MEDSAM2_REPO_PATH="/path/to/MedSAM2"
export MEDSAM2_COMMAND_TEMPLATE='python /path/to/runner.py --image {image_path} --output {output_mask_path} --prompt-json {prompt_json}'
export MEDSAM2_TIMEOUT_SECONDS=600
```

说明见：

- [docs/datasets/medsam2_runner_config.md](docs/datasets/medsam2_runner_config.md)

## 启动前端

先检查运行环境。MedScope 要求 Python 3.10+：

```bash
python -m scripts.check_runtime_environment
```

```bash
python -m api.http_server --host 127.0.0.1 --port 8000
```

浏览器打开：

```text
http://127.0.0.1:8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## 命令行使用

默认入口：

```bash
python app.py \
  --image /path/to/image.png \
  --message "左髋疼痛三个月，请结合影像分析" \
  --symptom "髋关节疼痛" \
  --risk-factor "饮酒史"
```

显式指定 skill：

```bash
python app.py \
  --image /path/to/image.png \
  --message "请评估这张骨盆正位 X 光是否支持股骨头坏死" \
  --disease-key femoral_head_necrosis
```

## HTTP API

主诊断接口：

```bash
curl -X POST http://127.0.0.1:8000/v1/medscope \
  -H "Content-Type: application/json" \
  -d '{
    "patient_message": "请评估这张髋关节 X 光。",
    "image_path": "/path/to/image.png",
    "patient_info": {
      "age": 45,
      "sex": "male",
      "symptoms": ["髋关节疼痛"]
    }
  }'
```

常用接口：

- `GET /health`
- `POST /v1/upload?filename=image.png`
- `GET /v1/skills`
- `GET /v1/skills/{skill_key}`
- `POST /v1/skills/{skill_key}/review-draft`
- `GET /v1/memory/cases`
- `GET /v1/memory/cases/{case_id}`
- `GET /v1/memory/cases/{case_id}/evidence-bundle`
- `GET /v1/memory/cases/{case_id}/audit`
- `GET /v1/demo/public-safe`
- `GET /v1/demo/standard`
- `POST /v1/baseline/image-prompt-skill`

## 常用 Demo

标准端到端 demo：

```bash
python -m scripts.end_to_end_demo --suite
```

API 连通性检查：

```bash
python -m scripts.api_smoke_test
```

证据约束推理评测：

```bash
python -m scripts.evidence_bounded_reasoning_eval
```

三层 prompt baseline：

```bash
python -m scripts.baseline_reasoning_eval
```

图像 + prompt + skill baseline：

```bash
python -m scripts.image_prompt_skill_baseline \
  --image /path/to/image.png \
  --message "请分析这张图像" \
  --disease-key femoral_head_necrosis \
  --output-dir output/real/Codex工作流基线/my_case
```

这是可复用的三层 Codex/VLM 工作流。它会在同一张图、同一个患者描述、
同一个 disease skill 上依次运行：

- `simple_prompt`
- `workflow_prompt`
- `fewshot_prompt`

并在输出目录中生成：

- `image_prompt_skill_baseline.json`：三层原始输出和指标。
- `image_prompt_skill_baseline.md`：三层对比表。
- `中文结论.md`：中文结论、三个层次说明，以及它和 MedScope Agent 主流程的区别。

fresh clone 可用的公开安全 MVP suite：

```bash
python -m scripts.prepare_public_demo_fixture --suite \
  --output-dir output/fake/public_safe_demo_suite
```

只生成公开安全合成图片和 manifest：

```bash
python -m scripts.prepare_public_demo_fixture \
  --output-dir output/fake/public_demo_fixture
```

suite 会生成一张合成的、非患者数据的髋关节 X-ray-like PNG，并运行确定性
service demo，写出 response、evidence bundle、memory audit 和 follow-up QA
artifact。它用于测试上传、路由和 FHN skill 主线，不是临床图像，也不是分割 benchmark。
启动 HTTP 服务后，也可以通过 `GET /v1/demo/public-safe` 直接运行同一条 suite。
交互前端也提供 `运行 Public-safe MVP 样例` 按钮，会调用这个 endpoint 并直接渲染
诊断报告、视觉证据、evidence bundle 和 memory audit。
该样例的追问走 `POST /v1/demo/public-safe/qa`，只绑定到生成的 demo artifact，
不会误用实时病例 memory。

无 mask 视觉流水线：

```bash
python -m scripts.no_mask_skill_visual_pipeline_demo \
  --image /path/to/xray.png \
  --message "请评估股骨头坏死相关征象"
```

BraTS 视觉测试线：

```bash
python -m scripts.brats_vision_test_line
```

## 测试

运行全量测试：

```bash
python -m unittest discover -v
```

最近一次本地验证：

```text
Ran 432 tests in 62.291s
OK
```

前端 JS 语法检查：

```bash
node --check web/app.js
```

## 项目 Review

当前做得比较扎实的部分：

- 临床职责边界比较清楚：诊断 Agent 不直接读原图，避免大模型凭空脑补像素证据。
- `guideline_based` 和 `data_mined_hypothesis` 的边界已经写进 skill contract。
- Memory 不只是保存结论，而是保存 patient/image/skill/reasoning 四类证据链。
- Vision Agent 已经支持“只用 VLM 观察”和“VLM 定位 + MedSAM2 候选分割”两种模式。
- 测试覆盖较广，包含契约、路由、HTTP、Memory、视觉协议、安全门、baseline 和 demo。

当前主要风险和不足：

- 视觉分割质量还没有真正收敛。框架能路由和审计 MedSAM2/VLM，但病灶是否准确仍需要疾病数据集和模型验证。
- 真实数据和生成结果大量在 `output/`、`data/external/`，这些不会随 GitHub 同步，新环境复现实验还不够方便。
- 依赖分组已经写入 `pyproject.toml`；但还没有锁文件，所以跨机器精确复现还没有 pin 到版本级别。
- 视觉后端接口已声明 VLM-only、VLM+segmenter、specialist segmenter 三类 contract，但仍需要真实 benchmark 验证质量。
- `benchmarks/segmentation/` 已经把专病分割验证入口和 web demo 分离，支持通用二值病灶 mask 的 Dice/IoU，并能对 metric-ready case 输出质量门通过/失败统计。
- Skill 自动升级被正确阻断，但后续如果要做 self-evolving，需要严格保留人工审核和 validation gate。
- 当前系统是科研 demo，不是临床验证系统。
- 当前 goal 收敛范围已经明确：真实 FHN 数据、真实 mask、metric-ready 真实 benchmark 后置，等数据到位后再接入。见 [docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md](docs/CURRENT_GOAL_CLOSURE_SCOPE_20260605.md)。

建议下一步：

1. 先把当前 MVP goal 收敛到架构说明、患者端报告/QA、evidence bundle 审计和 benchmark 基础设施。
2. 把公开安全 fixture 扩展成覆盖上传、QA、memory audit 的小型脚本 demo suite。
3. 等真实 FHN 标注数据和 mask 到位后，再向 `benchmarks/segmentation/` 增加 `evaluator_type: binary_mask` 和 `metric_gates`。
4. 如果进入固定部署，再增加锁文件或 pinned environment export。
5. 专病模型接入必须继续走 visual backend contract 和 quality gate。
6. 保持 clinical skill 更新必须经过人工审核和验证门。

## 医疗安全和隐私

- 不要提交 API key、`.env.local`、DICOM、NIfTI、模型权重或真实患者 case trace。
- 系统输出是科研审计 artifact，不是医疗建议。
- 缺失证据必须显示为 missing / unassessed，不能写成阴性。
- VLM 或分割模型给出的病灶只能作为候选证据，未经验证不能当成确定诊断依据。
