# BraTS / 成人弥漫性胶质瘤测试线

## 推荐原因

`BraTS + 成人弥漫性胶质瘤` 适合作为 MedScope Agent 的第一条真实测试线：

- 有公开 MRI 数据和专家分割标注，可验证视觉 Agent 的 mask / overlay 输出。
- 有 EANO 成人弥漫性胶质瘤指南和 ESTRO-EANO 胶质母细胞瘤放疗靶区勾画指南，可构建 guideline-based skill。
- 视觉任务和诊断任务边界清楚：视觉 Agent 负责肿瘤区域分割和影像证据提取；诊断医生 Agent 负责结合指南、症状、影像证据生成辅助报告。

## 数据集候选

### 首选：BraTS 系列

用途：

- 多模态脑 MRI：T1、T1ce、T2、FLAIR。
- 肿瘤分割标签：whole tumor、tumor core、enhancing tumor 等。
- 可用于生成 mask 和 overlay，也可用于量化肿瘤体积。

注意：

- BraTS 数据通常需要按挑战或平台规则申请/下载。
- 第一阶段不训练模型，可先读取 ground truth mask 作为视觉 Agent 输出，验证系统流程。

当前已落地的真实样本：

- 样本：BraTS2021 `BraTS2021_00030`、`BraTS2021_00392`。
- 本地路径：`data/external/brats2021_00030/`、`data/external/brats2021_00392/`。
- 已下载文件：每例均包含 `*_flair.nii.gz` 和 `*_seg.nii.gz`。
- 用途：先用 ground truth segmentation 验证视觉 Agent 同时输出 overlay 图像和结构化文本/JSON 证据。
- 确认可查看 overlay：`output/real/brats2021_00030_flair_overlay.png`。

### 备选：GBM-Reservoir

用途：

- 面向胶质母细胞瘤 MRI，含 ground truth segmentation masks。
- 可用于教育和流程验证。

## 指南来源

- EANO guidelines on the diagnosis and treatment of diffuse gliomas of adulthood
- ESTRO-EANO guideline on target delineation and radiotherapy details for glioblastoma

## 视觉 Agent 输出定义

视觉 Agent 必须同时输出两类结果：

### 1. 图像产物

```json
{
  "image_outputs": {
    "original_image_path": "data/images/case_001_flair.nii.gz",
    "mask_path": "data/masks/case_001_tumor_mask.nii.gz",
    "overlay_path": "data/overlays/case_001_overlay.png"
  }
}
```

### 2. 结构化视觉证据

```json
{
  "visual_evidence": {
    "lesion_detected": true,
    "lesion_location": "left temporal lobe",
    "segmentation_quality": "good",
    "whole_tumor_volume_ml": 35.7,
    "tumor_core_volume_ml": 12.4,
    "enhancing_tumor_volume_ml": 4.2,
    "edema_present": true,
    "mass_effect": "mild",
    "confidence": 0.82,
    "suspected_visual_findings": [
      "左颞叶异常信号区",
      "可见肿瘤核心区",
      "周围水肿明显"
    ]
  }
}
```

## 分阶段落地

### Phase A：Ground Truth Mask Reader

不训练模型，只读取公开数据集自带 mask。

目标：

- 输入 MRI 路径和 mask 路径。
- 输出 `image_outputs` 和 `visual_evidence`。
- 生成 overlay PNG。

当前状态：

- 已支持 2D PNG demo mask。
- 已提供 NIfTI reader：`tools/nifti_mask_reader_tool.py`。
- 已提供 NIfTI overlay generator：`tools/nifti_overlay_generation_tool.py`。
- 本地已安装 `nibabel`，真实 `.nii.gz` 样本已通过读取和 overlay 生成验证。
- 已提供可执行测试线入口：`python -m scripts.brats_vision_test_line`，默认读取 `data/external/brats2021_00030/`，输出 JSON 证据和 overlay 到 `output/fake/brats_vision_test_line/`。
- 已提供数据集 manifest：`data/external/brats_manifest.json`。当前包含 `brats2021_00030` 和 `brats2021_00392` 两例。可用 `--manifest data/external/brats_manifest.json --case-id brats2021_00030` 选择病例运行，后续新增病例只需追加 manifest 条目。
- 已支持 manifest 前置校验：`python -m scripts.brats_vision_test_line --validate-manifest --manifest data/external/brats_manifest.json`，在运行视觉 Agent 前检查 `cases` 非空，且 `case_id`、`image_path`、`mask_path`、`reference_mask_path` 是否齐全且路径存在。
- 已支持 MedSAM2 运行前 readiness 检查：`python -m scripts.brats_vision_test_line --check-medsam2 --manifest data/external/brats_manifest.json`，同时检查 BraTS manifest、`MEDSAM2_COMMAND_TEMPLATE` 必要占位符、`MEDSAM2_REPO_PATH` 和 `MEDSAM2_TIMEOUT_SECONDS`，不会调用真实推理。
- `MedSAM2CommandRunner.from_env()` 也会在真实 runner 创建前执行同一组硬校验；缺少 `{image_path}`、`{output_mask_path}`、`{prompt_json}`、timeout 非法或 repo 路径不存在时，会直接抛出 `MissingMedSAM2BackendError`。
- 已支持从 BraTS reference mask 生成 MedSAM2 测试 prompt：`--prompt-from-reference-mask` 会生成最大病灶 slice 的 2D box 和全 3D tumor bbox，并写入结果 JSON 的 `segmentation_prompt` 便于审计。
- 已支持 prompt-only 批量审计：`python -m scripts.brats_vision_test_line --generate-prompts --manifest data/external/brats_manifest.json`，生成每例 `*_prompt.json`、`*_prompt_overlay.png`、`prompts_summary.json` 和 `prompts_summary.md`，不运行模型。
- 已支持批量运行 manifest：`python -m scripts.brats_vision_test_line --manifest data/external/brats_manifest.json --all-cases`，输出每例 JSON/overlay，并写入 `summary.json` 和 `summary.md`。
- `summary.json` 包含 `aggregate.mean_*_dice` 和 `failed_case_ids`，用于快速查看整体分割表现和失败病例。
- `summary.md` 用表格列出每例状态、Dice、overlay 和 result 路径，便于人工快速检查。
- 批量模式会捕获单例异常并继续写 `partial_error` summary；例如 MedSAM2 未配置时会记录失败病例，而不是直接中断整批运行。

### Phase B：Feature Extraction

从 mask 提取体积和质量指标。

目标：

- whole tumor volume
- tumor core volume
- enhancing tumor volume
- segmentation quality

当前状态：

- 2D demo 使用手动 `voxel_volume_ml`。
- NIfTI reader 会从 header zooms 计算体素体积，并传给 feature extractor。
- BraTS2021 `BraTS2021_00030` 当前验证输出：whole tumor `117.996 ml`，tumor core `39.404 ml`，enhancing tumor `27.185 ml`，`edema_present=true`。
- BraTS2021 `BraTS2021_00392` 当前验证输出：whole tumor `47.590 ml`，tumor core `38.665 ml`，enhancing tumor `31.896 ml`，`edema_present=true`。

### Phase C：真实模型替换

接 nnU-Net / MONAI / MedSAM 等分割模型。

目标：

- 不改诊断医生 Agent。
- 只替换视觉 Agent 内部工具。

当前状态：

- `python -m scripts.brats_vision_test_line --mode medsam2` 已接入 MedSAM2 runner 路径。
- `python -m scripts.brats_vision_test_line --check-medsam2 --manifest data/external/brats_manifest.json` 可在真实推理前做 dry readiness check；该命令会检查 `{image_path}`、`{output_mask_path}`、`{prompt_json}` 三个命令占位符，不生成 mask，也不代表真实 MedSAM2 权重已经完成推理验证。
- 真实 `MedSAM2CommandRunner.from_env()` 与 dry readiness check 共用配置检查语义，避免 dry-run 显示不合格但真实运行继续进入外部命令。
- 已新增 `scripts/medsam2_brats_wrapper.py`，用于把 MedScope 的单例 BraTS NIfTI、`prompt_json` 和期望输出 mask 路径桥接到官方 MedSAM2 predictor 调用。wrapper 支持 `--dry-run` 检查图像、repo、checkpoint、cfg 和 prompt，也支持 `--print-command-template` 生成 `MEDSAM2_COMMAND_TEMPLATE`。
- 已用真实 `MedSAM2_latest.pt` 在 CPU 上跑通 BraTS2021 `BraTS2021_00030` 单例推理，生成模型 mask、overlay、结构化视觉证据和 Dice：whole tumor `0.9394868934746236`，tumor core `0.4929657650363098`，enhancing tumor `0.0`。输出仍在 `output/fake/brats_vision_test_line/`，待人工确认后再归档到 `output/real/`。
- 已用真实 `MedSAM2_latest.pt` 在 CPU 上跑通两例 BraTS2021 批量推理，输出到 `output/fake/brats_vision_medsam2_two_cases/`：`case_count=2`，`ok_count=2`，平均 whole tumor Dice `0.9429948832342406`，平均 tumor core Dice `0.699260558571914`，平均 enhancing tumor Dice `0.0`。
- 已修复 manifest + MedSAM2 模式的路径风险：manifest 的 ground-truth `mask_path` 只在 `ground_truth` 模式默认使用，`medsam2` 模式默认写入 `output/fake/brats_vision_test_line/*_medsam2_mask.nii.gz`，避免覆盖真实标注。
- MedSAM2 模式默认把模型生成 mask 写入 `output/fake/brats_vision_test_line/*_medsam2_mask.nii.gz`，不会覆盖 ground-truth mask。
- 传入 `--reference-mask` 后会输出 BraTS 区域 Dice：whole tumor、tumor core、enhancing tumor。
- 传入 `--prompt-from-reference-mask` 后，会使用 `--reference-mask` 生成 promptable segmentation 所需 bbox；这是测试/评估模式，不代表无标注自动分割。
- 使用 `--generate-prompts` 可先批量检查每个 case 的 prompt JSON、bbox overlay PNG 和人工可读 Markdown 汇总；默认输出仍在 `output/fake/brats_vision_test_line/`，未人工确认前不进入 `output/real/`。
- 单元测试仍使用 fake MedSAM2 runner 复制真实 BraTS mask 来稳定验证模型模式的 mask、overlay、JSON 证据链和 Dice 评估；真实 MedSAM2 已通过外部 `MEDSAM2_COMMAND_TEMPLATE` 做过单例 CPU 验证。

## 当前不做

- 不直接训练新视觉模型。
- 不把视觉 Agent 变成诊断 Agent。
- 不让 LLM 根据 MRI 原图自由描述病灶。
