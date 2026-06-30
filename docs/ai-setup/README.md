# MemoryGraph — 本地 AI 开发环境配置

适用于：**Mac M4 + 128GB** · **Ollama** · **VSCode + Continue** · **Qwen Coder 30B/32B**

## 1. Ollama 模型（推荐 Q8）

```bash
# 拉取基础模型（按你 ollama list 里实际名称调整）
ollama pull qwen2.5-coder:32b

# 用项目 Modelfile 创建专用模型
cd /path/to/MemoryGraph
ollama create memorygraph-coder -f docs/ai-setup/Modelfile

# 验证
ollama run memorygraph-coder "读 AGENTS.md，简述 analyze_image 的职责"
```

若显存/内存充足，可改用更高精度量化版本（Q8 优于 Q4，工具调用更稳）。

### 更新系统提示里的日期

Modelfile 的 `SYSTEM` 不含动态日期。日期上下文由 Continue `rules` 或 `.continuerules` 提供；需要时在 Modelfile 里手动改一行后重新 `ollama create`。

## 2. Continue 配置

### 项目级（已就绪，Continue 会自动读取）

- `AGENTS.md` — 完整架构说明
- `.continuerules` — 精简规则

### 用户级（合并到 `~/.continue/config.yaml`）

1. 打开 Continue 配置：`Cmd+Shift+P` → `Continue: Open config.yaml`
2. 将 `docs/ai-setup/continue-config.yaml` 中的内容合并进去
3. 确认 `model: memorygraph-coder` 与 `ollama create` 名称一致
4. 重启 VSCode 或 Reload Continue

### 推荐用法

| 场景 | 做法 |
|------|------|
| 改单个函数 | Edit / Apply 模式 + `@analyzer.py` |
| 理解架构 | Chat + `@AGENTS.md` |
| 跨文件改动 | 拆步：先 `@schema.py` 再改目标文件 |
| 复杂重构 | 切换云端模型或改用 Cursor |

## 3. 两台电脑同步

```bash
git pull
# 规则与 AGENTS.md 随仓库同步，Ollama/Continue 用户配置需各机器单独 setup 一次
```

## 4. 文件说明

| 文件 | 作用 |
|------|------|
| `AGENTS.md` | Cursor / Continue 通用项目说明 |
| `.continuerules` | Continue 项目规则 |
| `docs/ai-setup/Modelfile` | Ollama 专用模型定义 |
| `docs/ai-setup/continue-config.yaml` | Continue 配置模板 |
