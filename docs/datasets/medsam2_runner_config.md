# MedSAM2 Runner 配置

本文档记录 MedScope 当前如何接入 MedSAM2。项目内不直接下载 MedSAM2 代码或权重，而是通过 runner 适配层调用外部 MedSAM2 推理命令。

## 当前接入边界

- MedScope 侧入口：`tools/medsam2_segmentation_tool.py`
- 核心接口：`MedSAM2CommandRunner.predict_mask(image_path, output_mask_path, prompt)`
- 视觉链路：`VisionAgent -> SegmentationTool.segment_with_model() -> MedSAM2SegmentationTool`
- 输出仍保持 `image_outputs` + `visual_evidence`

## 官方 MedSAM2 准备

官方仓库建议流程：

```bash
git clone https://github.com/bowang-lab/MedSAM2.git
cd MedSAM2
pip install -e ".[dev]"
bash download.sh
```

官方 README 中的 3D 推理入口示例是：

```bash
python medsam2_infer_3D_CT.py -i CT_DeepLesion/images -o CT_DeepLesion/segmentation
```

由于官方脚本按数据集目录组织输出，MedScope 推荐先写一个薄封装脚本，把输入图像、prompt 和输出 mask path 统一成下面的命令格式。

## 环境变量

`MedSAM2CommandRunner.from_env()` 读取：

```bash
export MEDSAM2_REPO_PATH="/path/to/MedSAM2"
export MEDSAM2_COMMAND_TEMPLATE='python /path/to/run_medsam2_mask.py --image {image_path} --output {output_mask_path} --prompt-json {prompt_json}'
export MEDSAM2_TIMEOUT_SECONDS=600
```

占位符：

- `{image_path}`：输入图像路径
- `{output_mask_path}`：MedScope 期望生成的 mask 路径
- `{prompt_json}`：JSON 字符串，例如 `{"boxes": [[1, 1, 5, 5]]}`

`python -m scripts.medsam2_smoke_test` 和 `python -m scripts.brats_vision_test_line --check-medsam2` 会检查这三个占位符是否齐全；缺少任何一个时 `real_call_ready=false`。`MedSAM2CommandRunner.from_env()` 也会在真实运行前硬校验占位符、`MEDSAM2_TIMEOUT_SECONDS` 和 `MEDSAM2_REPO_PATH`，配置不合格时直接抛出 `MissingMedSAM2BackendError`。

命令执行前会自动对路径和 prompt JSON 做 shell-safe quote。

## 配置检查

默认 dry-run 不会调用真实 MedSAM2，只检查环境变量和 repo 路径：

```bash
python -m scripts.medsam2_smoke_test
```

## BraTS Wrapper

官方 MedSAM2 当前主要提供 CT_DeepLesion 目录推理和 RECIST/NPZ 推理脚本；MedScope 的 BraTS 测试线使用的是单例 NIfTI + `prompt_json`。为避免把官方脚本细节扩散到 Agent 内，仓库内新增了薄封装：

```bash
python -m scripts.medsam2_brats_wrapper \
  --image data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz \
  --output output/fake/brats_vision_test_line/brats2021_00030_medsam2_mask.nii.gz \
  --prompt-json '{"slice_index": 100, "boxes": [[60, 133, 124, 193]], "label_ids": [1, 2, 4]}' \
  --medsam2-repo /path/to/MedSAM2 \
  --checkpoint /path/to/MedSAM2/checkpoints/MedSAM2_latest.pt \
  --cfg /path/to/MedSAM2/sam2/configs/sam2.1_hiera_t512.yaml \
  --dry-run
```

`--dry-run` 只检查输入图像、repo、checkpoint、cfg 和 prompt，不加载模型。真实运行时去掉 `--dry-run`，wrapper 会把 BraTS NIfTI 和 bbox prompt 转成 MedSAM2 predictor 调用，并把输出保存为 MedScope 期望的单个 NIfTI mask。

本机已验证的最小真实运行条件：

- 临时官方仓库：`/private/tmp/medscope_medsam2_probe`
- checkpoint：`/private/tmp/medscope_medsam2_probe/checkpoints/MedSAM2_latest.pt`
- Python 依赖：`torch`、`torchvision`、`hydra-core`、`iopath`、`nibabel`
- 当前设备：CPU；无 CUDA/MPS，因此单例 BraTS 推理大约需要 1 分钟以上。
- 已知警告：macOS/CPU 下缺少可用的 SAM2 CUDA extension，官方代码会跳过部分 post-processing；当前测试线仍可生成 mask。

已验证真实输出：

- mask：`output/fake/brats_vision_test_line/brats2021_00030_medsam2_mask.nii.gz`
- overlay：`output/fake/brats_vision_test_line/brats2021_00030_medsam2_overlay.png`
- result：`output/fake/brats_vision_test_line/brats2021_00030_medsam2_vision_result.json`
- Dice：whole tumor `0.9394868934746236`，tumor core `0.4929657650363098`，enhancing tumor `0.0`

两例真实 BraTS CPU 批量验证输出：

- summary：`output/fake/brats_vision_medsam2_two_cases/summary.json`
- case_count：`2`
- ok_count：`2`
- mean whole tumor Dice：`0.9429948832342406`
- mean tumor core Dice：`0.699260558571914`
- mean enhancing tumor Dice：`0.0`
- `brats2021_00030`：whole tumor `0.9394868934746236`，tumor core `0.4929657650363098`，enhancing tumor `0.0`
- `brats2021_00392`：whole tumor `0.9465028729938577`，tumor core `0.9055553521075183`，enhancing tumor `0.0`

可用下面命令生成 `MEDSAM2_COMMAND_TEMPLATE`：

```bash
python -m scripts.medsam2_brats_wrapper \
  --print-command-template \
  --medsam2-repo /path/to/MedSAM2 \
  --checkpoint /path/to/MedSAM2/checkpoints/MedSAM2_latest.pt \
  --cfg /path/to/MedSAM2/sam2/configs/sam2.1_hiera_t512.yaml
```

然后设置：

```bash
export MEDSAM2_REPO_PATH="/path/to/MedSAM2"
export MEDSAM2_COMMAND_TEMPLATE='python /abs/path/to/MedScope_Agent/scripts/medsam2_brats_wrapper.py --image {image_path} --output {output_mask_path} --prompt-json {prompt_json} --medsam2-repo /path/to/MedSAM2 --device cuda --checkpoint /path/to/MedSAM2/checkpoints/MedSAM2_latest.pt --cfg /path/to/MedSAM2/sam2/configs/sam2.1_hiera_t512.yaml'
```

BraTS 测试线也提供运行前 readiness 检查。它会同时检查 `data/external/brats_manifest.json` 中的病例路径和 MedSAM2 runner 配置，但不会调用真实推理：

```bash
python -m scripts.brats_vision_test_line \
  --check-medsam2 \
  --manifest data/external/brats_manifest.json
```

真实调用需要显式加 `--real`，并传入测试图像。默认 mask 输出放在 `output/fake/medsam2_smoke_mask.png`：

```bash
python -m scripts.medsam2_smoke_test \
  --real \
  --image data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz \
  --mask output/fake/medsam2_smoke_mask.png \
  --prompt-json '{"boxes": [[1, 1, 5, 5]]}'
```

BraTS 视觉测试线也可以走 MedSAM2 模式：

```bash
python -m scripts.brats_vision_test_line \
  --mode medsam2 \
  --image data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz \
  --reference-mask data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz \
  --prompt-json '{"boxes": [[1, 1, 5, 5]]}'
```

如果要用 BraTS 标注生成 promptable segmentation 的测试 prompt，可以显式加入 `--prompt-from-reference-mask`：

```bash
python -m scripts.brats_vision_test_line \
  --mode medsam2 \
  --image data/external/brats2021_00030/BraTS2021_00030_flair.nii.gz \
  --reference-mask data/external/brats2021_00030/BraTS2021_00030_seg.nii.gz \
  --prompt-from-reference-mask
```

真实 runner 配好前，也可以只批量生成 prompt JSON、bbox overlay PNG 和 Markdown 表格做人工审计：

```bash
python -m scripts.brats_vision_test_line \
  --generate-prompts \
  --manifest data/external/brats_manifest.json
```

在 `--mode medsam2` 下，`--mask` 表示模型输出 mask 路径；如果不传，默认写入 `output/fake/brats_vision_test_line/*_medsam2_mask.nii.gz`，不会覆盖 BraTS ground-truth mask。
传入 `--reference-mask` 后，结果 JSON 会包含 whole tumor、tumor core、enhancing tumor 的 Dice 评估。
传入 `--prompt-from-reference-mask` 后，结果 JSON 会包含 `segmentation_prompt`，其中包括最大病灶 slice 的 2D bbox、全 3D bbox、label ids 和 reference mask 路径。该模式用于测试和评估，不代表无标注自动分割。
`--generate-prompts` 会输出每例 `*_prompt.json`、`*_prompt_overlay.png`、`prompts_summary.json` 和 `prompts_summary.md`，默认目录为 `output/fake/brats_vision_test_line/`。

## 2D 无 mask 图像 wrapper

无 mask 2D 医疗图像链路使用：

```bash
python -m scripts.no_mask_vision_prompt_demo \
  --image output/fake/no_mask_vision_source_pneumonia_xray.jpg \
  --output-dir output/fake/no_mask_vision_prompt_demo
```

该步骤调用视觉模型生成：

```json
{
  "segmentation_prompt": {
    "source": "vision_model_bbox",
    "boxes": [[10, 480, 150, 590]]
  }
}
```

然后用 2D MedSAM2 wrapper 执行真实分割：

```bash
python -m scripts.no_mask_medsam2_segmentation_demo \
  --prompt-result output/fake/no_mask_vision_prompt_demo/vision_prompt_result.json \
  --output-dir output/fake/no_mask_medsam2_segmentation_demo
```

2D wrapper 可单独使用：

```bash
python -m scripts.medsam2_2d_wrapper \
  --image output/fake/no_mask_vision_source_pneumonia_xray.jpg \
  --output output/fake/no_mask_medsam2_segmentation_demo/medsam2_mask.png \
  --prompt-json '{"boxes": [[10, 480, 150, 590]]}' \
  --medsam2-repo /private/tmp/medscope_medsam2_probe \
  --device cpu \
  --checkpoint /private/tmp/medscope_medsam2_probe/checkpoints/MedSAM2_latest.pt \
  --cfg /private/tmp/medscope_medsam2_probe/sam2/configs/sam2.1_hiera_t512.yaml
```

本机 2026-05-25 验证配置：

- repo：`/private/tmp/medscope_medsam2_probe`
- checkpoint：`/private/tmp/medscope_medsam2_probe/checkpoints/MedSAM2_latest.pt`
- cfg：`/private/tmp/medscope_medsam2_probe/sam2/configs/sam2.1_hiera_t512.yaml`
- device：`cpu`

`.env.local` 中可配置：

```bash
MEDSAM2_REPO_PATH=/private/tmp/medscope_medsam2_probe
MEDSAM2_TIMEOUT_SECONDS=600
MEDSAM2_COMMAND_TEMPLATE='python /Users/houshaohua/Desktop/code/aidoctor/MedScope_Agent/scripts/medsam2_2d_wrapper.py --image {image_path} --output {output_mask_path} --prompt-json {prompt_json} --medsam2-repo /private/tmp/medscope_medsam2_probe --device cpu --checkpoint /private/tmp/medscope_medsam2_probe/checkpoints/MedSAM2_latest.pt --cfg /private/tmp/medscope_medsam2_probe/sam2/configs/sam2.1_hiera_t512.yaml'
```

真实输出：

- mask：`output/fake/no_mask_medsam2_segmentation_demo/medsam2_mask.png`
- overlay：`output/fake/no_mask_medsam2_segmentation_demo/medsam2_overlay.png`
- summary：`output/fake/no_mask_medsam2_segmentation_demo/summary.json`
- lesion area：`9278 px`
- lesion area ratio：`0.043194`

## MedScope 中的使用方式

```python
from tools.medsam2_segmentation_tool import MedSAM2CommandRunner, MedSAM2SegmentationTool
from tools.segmentation_tool import SegmentationTool
from agents.vision_agent import VisionAgent

runner = MedSAM2CommandRunner.from_env()
medsam2_backend = MedSAM2SegmentationTool(runner=runner)
segmentation_tool = SegmentationTool(model_backend=medsam2_backend)
vision_agent = VisionAgent(segmentation_tool=segmentation_tool)

result = vision_agent.analyze_brats_with_segmentation_model(
    image_path="data/images/case_flair.png",
    prompt={"boxes": [[1, 1, 5, 5]]},
    mask_path="output/real/case_medsam2_mask.png",
    overlay_path="output/real/case_medsam2_overlay.png",
    disease_skill={"disease_name": "成人弥漫性胶质瘤"},
)
```

## 当前限制

- 当前仓库只提供 MedSAM2 runner 适配层，不包含 MedSAM2 权重。
- 真实推理需要外部 MedSAM2 环境、checkpoint 和 GPU/CPU 运行条件。
- 如果官方脚本输出的是目录而不是单个 mask 文件，需要封装脚本负责复制或转换到 `{output_mask_path}`。
