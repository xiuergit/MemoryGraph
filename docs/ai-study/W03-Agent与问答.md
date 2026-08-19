# W03 · Agent 问答链（MemoryGraph）

**本周目标**：读懂 `agent.py` → `query.py` → SQLite；自己加 1 条意图或改进回答。  
**预计**：6～8h

---

## Day 1 · 索引层（1.5h）

- [ ] 读 `hub/shared/index_db.py`：`sync` 写什么表
- [ ] 读 `hub/shared/query.py`：`gather_facts()` 输入输出
- [ ] `python tools/memory_index/main.py sync` 后再问 CLI 一题

---

## Day 2 · Agent 路由（2h）

- [ ] 读 `hub/shared/agent.py`：正则 `_STATS_RE`、`_PLACE_RE`、`_LLM_SKIP_INTENTS`
- [ ] 画 3 分支：统计 / 地点 / 走 LLM 润色
- [ ] 读 `tools/memory_desk/app.py` 的 `POST /api/ask`

---

## Day 3 · 跟踪一题（1.5h）

- [ ] 选问题：「有多少张 tag 含游泳的照片」（没有游泳就换你库里有的词）
- [ ] grep `agent.py` / `query.py` 看走哪条路径
- [ ] 记录：若不支持，Day 4 在哪加

---

## Day 4 · 改代码（2h）

**二选一**：

- [ ] **A**：新意图 — 按 `tags`/`scene` 关键词统计或列 photo_id
- [ ] **B**：改进现有意图的模板文案（`agent.py` 里对应 answer 组装）

验证：

- [ ] CLI `memory_ask` + Vue `/api/ask` 各测 1 次

---

## Day 5 · 与 JD 对照（1h）

- [ ] 写表（放 `docs/ai-study/notes/agent对比.md` 可选）：

| JD 词 | MemoryGraph 现状 | W07 要补 |
|-------|------------------|----------|
| Agent | 规则 + 查库 + LLM | Tool Calling |
| RAG | SQLite 结构化 | W04 语义向量 |
| Memory | 无多轮会话 | 可选 |

---

## 本周完成 ✓

- [ ] 能口述 ask 的 5 步
- [ ] 至少有 1 处自己改的 `agent.py` / `query.py`

**下一周** → [W04-语义检索入门.md](./W04-语义检索入门.md)
