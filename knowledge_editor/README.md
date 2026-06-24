# MedScope Knowledge Editor

独立的医生可视化编辑入口，用于维护当前仓库内的：

- `knowledge/*.yaml`
- `prompts/*.md`

启动 MedScope HTTP 服务后访问：

```bash
python3 -m api.http_server --host 0.0.0.0 --port 8000
```

```text
http://服务器地址:8000/knowledge-editor/
```

医生在页面里保存后，编辑器会直接写回本仓库的 `knowledge/` 或 `prompts/` 文件。版本快照保存在：

```text
output/knowledge_editor_versions/
```

注意：当前 MedScope 的 knowledge 文件扩展名是 `.yaml`，但运行时代码使用 `json.loads()` 读取，所以编辑器保存时会继续写入 JSON 兼容格式，避免破坏现有 Agent 读取逻辑。
