# W01 · Python 读代码 + 自己写 FastAPI

> **你已会的（本周跳过）**  
> - 怎么跑：sync / Desk `--auto-port` / `npm run dev`  
> - JSON 是真源、schema 是你定的、sync 是 JSON → SQLite  
> - 模块分工：`photo2json`、`memory_desk`、`web` 各干什么  
>  
> **本周真正要补的**：AI 写的 Python **你能顺着读下去**，并 **自己加一段** Desk API + Vue 展示（不靠 AI 一键生成）。

**预计**：6～8h

---

## Day 1 · 跟一条「查库」代码链（2h）

从你已经会用的能力入手，反查实现（只读，不改）：

- [ ] 打开 `tools/memory_desk/app.py`，找 `GET /api/memory/list`：请求参数有哪些、返回什么结构
- [ ] 它调了哪个 `hub/shared/*` 函数？点进去读那个函数（ likely `index_db` 或 list 相关）
- [ ] 打开 `hub/shared/index_db.py`，找 `sync` 或建表 SQL：JSON 哪些字段进了哪张表
- [ ] 笔记 3 条（写给自己）：  
  - list 接口 → 函数名 → 读的表  
  - `people` 在 SQLite 里怎么存  
  - 若 sync 没跑，list 会怎样

**验证**：能口头说「点列表 Tab → 打到哪个 URL → 后端哪几行查库」，不必背命令。

---

## Day 2 · Python 语法对照读（1.5h）

用 Swift/Java 对照，只抠 **本项目里常见写法**（不必重学 Python 全书）：

- [ ] 在 `index_db.py` 或 `query.py` 里找 3 处：`dict`、`list`、`for`、`if`、`with`、类型标注 `str | None`
- [ ] 在 `schema.py` 找 `TypedDict` / dataclass（对照 Swift struct / Java record）
- [ ] 在 `app.py` 找 `Pydantic` 请求体（对照 Kotlin data class）

**小练习（可选，10 分钟）**：在项目根用 `-c` 调已有模块，例如统计 memory 目录 json 数量（练习 import 路径）：

```bash
python -c "from pathlib import Path; print(len(list(Path('data/memory').glob('*.json'))))"
```

---

## Day 3 · 自己写 `GET /api/stats/summary`（2.5h）

**这是本周核心**，要求 **你先手写一版**，卡住再让 AI 补；不要反过来。

- [ ] 定接口契约（你先写死在注释里）：
  ```json
  { "total_photos": 0, "with_people": 0, "with_location": 0 }
  ```
- [ ] 在 `tools/memory_desk/app.py` 加路由
- [ ] 统计逻辑 **二选一**（推荐 A，练 SQL）：
  - **A**：查 `memorygraph.db`（复用 `connect()`，写 COUNT）
  - **B**：扫 `data/memory/*.json`（快但绕开索引，仅练 Python）
- [ ] 启动 Desk，curl 或浏览器测：`/api/stats/summary`
- [ ] 和 `/api/events/stats` 对比：别人怎么组织返回、有没有复用函数

**完成标准**：git diff 里 **有你写的** 路由 + 查询，且数字和列表 Tab 大致对得上。

---

## Day 4 · Vue 接上（1.5h）

Vue 你会，只做「接自己的 API」：

- [ ] `web/src/` 搜一个现有 `axios.get('/api/...')` 照抄模式
- [ ] 在维护页或列表页顶栏显示 Day 3 三个 stats 数字
- [ ] Network 确认打的是你的新路径

---

## Day 5 · Review 与复盘（1h）

- [ ] 用自己的话写 `docs/ai-study/notes/W01.md`（200 字）：  
  - 今天 **自己写** 的是哪段  
  - 哪段是读 AI 以前写的、现在才看懂  
  - 下周 W02 想改 vision 还是 agent
- [ ] [总目标.md](./总目标.md) 里 W01 打勾

---

## 本周完成 ✓

- [ ] 不是「会跑命令」，而是 **跟通过一条 list → db 代码链**
- [ ] **stats API 是你写的**（或你写 70% + AI 补 30%）
- [ ] Vue 能显示 stats

**下一周** → [W02-LLM与Prompt.md](./W02-LLM与Prompt.md)
