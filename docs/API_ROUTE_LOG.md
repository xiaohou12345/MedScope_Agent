# API Route Log

本文件记录 MedScope Agent 当前默认模型 API 路由。Agent 代码不得直接判断 DMX/KY；只能通过 `llm.model_client.ApiRouteLog` 读取本文件，再由统一 `ModelClient` 调用。

active_route: dmx
dmx_model: gemini-3.5-flash
dmx_vision_model: gpt-5.5
ky_model: ky-self-hosted-medical
ky_vision_model: ky-self-hosted-medical
dmx_base_url: https://anyaigc.com
ky_base_url: http://127.0.0.1:8000/v1/chat/completions

## 路由含义

- `active_route: dmx`：默认走 DMX。
- `active_route: ky`：走自部署 KY。
- 真实联网调用前，需要在环境变量中配置：
  - DMX：`DMX_API_KEY`
  - KY：`KY_API_KEY`

## 连通性测试

项目记忆中指定的默认 API 连通性测试脚本：

```bash
python /Users/4paradigm/Documents/project/cloudgpt_client_example.py
```

仓库内离线检查脚本：

```bash
python -m scripts.api_smoke_test
```

显式真实调用：

```bash
python -m scripts.api_smoke_test --real
```

当前仓库测试不会触发真实网络请求。`tests/test_llm_routing.py` 使用 `RecordingModelClient` 验证 Agent 是否走统一模型接口。

## Responses API 与调用日志

`DMX_API_ENDPOINT` / `KY_API_ENDPOINT` 支持两种值：

- `chat_completions`：默认 OpenAI-compatible chat completions 路径。
- `responses`：OpenAI-compatible Responses API 路径。

某些中转网关要求 Responses API 使用 SSE 流式返回。此时不要改业务代码，改环境变量：

```bash
MEDSCOPE_RESPONSES_STREAM=1
MEDSCOPE_VISION_RESPONSES_STREAM=1
```

真实模型调用默认写入本地审计日志：

```text
output/fake/model_call_logs/model_calls.jsonl
output/fake/model_call_logs/<task>_<call_id>.json
```

相关环境变量：

- `MEDSCOPE_MODEL_CALL_LOG_DIR`：覆盖日志目录。
- `MEDSCOPE_DISABLE_MODEL_CALL_LOG=1`：关闭模型调用日志。

日志会脱敏 `api_key`、`authorization`、`token` 等字段，并把 base64 图像 data URL
替换成 mime、字节数和 sha256 摘要，避免把完整图像编码写进日志。

## 最近一次检查

检查时间：2026-05-24

```text
active_route: dmx
model: gemini-3.5-flash
vision_model: gpt-5.5
api_key_env: DMX_API_KEY
api_key_present: true
external_script_path: /Users/4paradigm/Documents/project/cloudgpt_client_example.py
external_script_found: false
real_call_ready: true
```

离线检查结论：当前 `dmx_base_url`、`dmx_model` 和 `dmx_vision_model` 已更新为可用路由配置。API key 不写入可提交代码文件；本机运行时从 `.env.local` 或环境变量读取。

真实 smoke 结论：使用用户提供的 DMX key 临时注入后，旧路由 `gemini-3.5-flash` 已通过 `https://anyaigc.com/v1/chat/completions` 完成图像输入 smoke，模型能读取 PNG 图像并返回 JSON 描述。当前 Vision Agent lesion prompt generator 已切到 `dmx_vision_model: gpt-5.5`；该模型仍不直接替代像素级分割模型。

## 修改规则

- 切换 DMX/KY 时，只改本文件的 `active_route`。
- 替换诊断/文本模型名时，只改 `dmx_model` 或 `ky_model`。
- 替换 Vision/VLM 模型名时，只改 `dmx_vision_model` 或 `ky_vision_model`。
- API key 只通过环境变量注入，不写入本文件。
- 不要在 `agents/` 中写 provider-specific API 逻辑。
