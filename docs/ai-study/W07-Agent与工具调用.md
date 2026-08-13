# W07 · Tool Calling Agent（MemoryGraph）

**本周目标**：在 `agent.py`（或 `hub/shared/agent_tools.py`）里，LLM 可选工具完成问答。  
**预计**：6～8h

---

## Day 1 · 工具清单（1h）

在 MemoryGraph 内定义 3 个 Tool（输入/输出 JSON schema 写注释即可）：

| Tool | 实现复用 |
|------|----------|
| `search_structured` | `query.gather_facts` / index_db SQL |
| `search_semantic` | W05 `semantic_search_facts` |
| `search_events` | events 表 / `hub/shared/events.py` |

- [ ] 每个 Tool 单独 Python 调用测通

---

## Day 2 · 执行器（2h）

- [ ] 写 `run_tool(name, args) -> str`
- [ ] LLM 返回 JSON：`{"tool":"...", "args":{...}}` 或 OpenAI function calling 格式
- [ ] max_steps=5，防循环

---

## Day 3 · 接入 ask（2h）

- [ ] 新路径：复杂/模糊问题走 Tool Agent；简单统计仍走原规则（保留 `_LLM_SKIP_INTENTS` 思路）
- [ ] 或：仅 `/api/ask?mode=agent` 试验开关，不影响默认
- [ ] 测：「面面去年去了哪些地方，有没有类似游乐园的记忆」— 需 events + semantic

---

## Day 4 · Vue / CLI（1h）

- [ ] CLI 加 `--agent-tools` 可选 flag（`tools/memory_ask/main.py`）
- [ ] Vue 问答可选勾选「工具模式」（可选 UI）

---

## Day 5 · MCP 概念（1h）

- [ ] 笔记：Tool schema ≈ MCP 要标准化的东西
- [ ] 不必接 MCP 服务器；面试能讲即可

---

## 本周完成 ✓

- [ ] 至少 1 题必须调 2 个 Tool 才能答
- [ ] 能画 ReAct 循环对照原规则 Agent

**下一周** → [W08-评测与调试.md](./W08-评测与调试.md)
