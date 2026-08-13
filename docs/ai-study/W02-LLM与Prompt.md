# W02 · Ollama + Prompt（MemoryGraph）

**本周目标**：搞懂 vision / chat 怎么调 Ollama；改 prompt 并用 backfill 验证。  
**预计**：6～8h

---

## Day 1 · 视觉链（1.5h）

- [ ] 读 `hub/shared/vision.py`：`_VISION_PROMPT`、base64、JSON 解析
- [ ] 读 `hub/shared/config.py`：`OLLAMA_VISION_MODEL`、`OLLAMA_BASE_URL`
- [ ] 读 `.env.example` / 本地 `.env`（勿提交密钥）
- [ ] 确认 Ollama 在跑：`ollama list`

---

## Day 2 · 改 Prompt（2h）

- [ ] 在 `_VISION_PROMPT` 加 **1 条** 可验证规则（例：泳池场景 `tags` 含「游泳」）
- [ ] 挑 1 个已有 `photo_id`，backfill vision：
  ```bash
  python tools/photo2json/main.py --backfill vision --refill --year 2025
  ```
  （参数以 `--help` 为准；可先 `--limit 1` 若支持）
- [ ] 对比该 JSON 改前改后（git diff 或备份）
- [ ] `python tools/memory_index/main.py sync` 同步索引

---

## Day 3 · Chat 链（1.5h）

- [ ] 读 `hub/shared/agent.py` 里 Ollama chat 调用（搜 `OLLAMA_CHAT`）
- [ ] CLI 测 3 问：
  ```bash
  python tools/memory_ask/main.py "一共有多少张照片"
  python tools/memory_ask/main.py "面面最近去哪了"
  python tools/memory_ask/main.py "最近有什么开心的事"
  ```
- [ ] Vue「问答」Tab 问同一题，对比输出

---

## Day 4 · Structured Output（1h）

- [ ] 笔记 4 点：角色约束、只要 JSON、解析失败兜底、超时
- [ ] 找 `empty_analysis()` / agent 模板兜底代码
- [ ] 故意把 vision prompt 改坏一次，看失败时 JSON 长什么样

---

## Day 5 · 可选云端 API（1h）

- [ ] 仅在 `hub/shared/config.py` 层面理解：换 base_url/model 即可对接 DeepSeek 等
- [ ] 不必改生产路径；笔记「MemoryGraph 为何默认 Ollama（local-first）」

---

## 本周完成 ✓

- [ ] 独立改过 vision prompt + backfill 验证
- [ ] 说清 vision 与 agent chat 两条 Ollama 路径

**下一周** → [W03-Agent与问答.md](./W03-Agent与问答.md)
