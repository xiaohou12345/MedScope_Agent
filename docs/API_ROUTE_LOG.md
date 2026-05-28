# API Route Log

本文件记录 MedScope Agent 当前默认模型 API 路由。Agent 代码不得直接判断 DMX/KY；只能通过 `llm.model_client.ApiRouteLog` 读取本文件，再由统一 `ModelClient` 调用。

active_route: dmx
dmx_model: gemini-3.5-flash
ky_model: ky-self-hosted-medical
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

## 最近一次检查

检查时间：2026-05-24

```text
active_route: dmx
model: gemini-3.5-flash
api_key_env: DMX_API_KEY
api_key_present: true
external_script_path: /Users/4paradigm/Documents/project/cloudgpt_client_example.py
external_script_found: false
real_call_ready: true
```

离线检查结论：当前 `dmx_base_url` 和 `dmx_model` 已更新为可用路由配置。API key 不写入可提交代码文件；本机运行时从 `.env.local` 或环境变量读取。

真实 smoke 结论：使用用户提供的 DMX key 临时注入后，`gemini-3.5-flash` 已通过 `https://anyaigc.com/v1/chat/completions` 完成图像输入 smoke，模型能读取 PNG 图像并返回 JSON 描述。该模型可作为 Vision Agent 的 lesion prompt generator 候选，不直接替代像素级分割模型。

## 修改规则

- 切换 DMX/KY 时，只改本文件的 `active_route`。
- 替换模型名时，只改 `dmx_model` 或 `ky_model`。
- API key 只通过环境变量注入，不写入本文件。
- 不要在 `agents/` 中写 provider-specific API 逻辑。
