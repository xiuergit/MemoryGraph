# CLI 问答 Agent 意图说明

> 实现：`hub/shared/agent.py`（路由 + 模板） · `hub/shared/query.py`（查库）  
> 入口：`python tools/memory_ask/main.py "你的问题"`

## 设计原则

意图不是「理解每一句自然语言」，而是 **问题类型 → 查哪几列 → 返回事实 JSON → 模板或 Ollama 组织回答**。

| 数据层 | 典型字段 | 当前状态（约） | 适合问的 |
|--------|----------|----------------|----------|
| **A. 档案/索引** | 计数、`birth_date`、`age_label` | 完整 | 几岁、多少张、某岁排行 |
| **B. 时间线** | `timestamp`、`location`、`photo_terms` | 人物/时间/地点强，表情弱 | 最近去哪、第一次、有没有某标签 |
| **C. 语义/感受** | `scene`、`emotion`、`tags` | vision 补全中（~5–15%） | 细腻感受类，暂不宜作为主路径 |

新增意图时：先列自己常问的句子 → 标 A/B/C → 确认 SQLite 有字段 → 再加路由。**不要**在未匹配时默认返回「最近照片」（待改进）。

## 处理流程

```
用户问题
    → route_intent()        正则路由，提取 person / age / term 等参数
    → gather_facts()        查 memorygraph.db，组装 facts JSON
    → _template_answer()    模板回答（默认）
    → _llm_answer()         可选：Ollama 润色（失败则仍用模板）
```

人物名从 `data/faces/registry.json` 读取；问句里未写人名且档案里只有一名成员时，默认该成员。

## 路由优先级

高 → 低（先匹配先生效）：

1. `person_age_place_rank` — N 岁 + 去哪最多 / 待最久
2. `library_stats` — 多少张 / 一共 / 统计
3. `group_photos` — X和Y合影 / 合照有哪些
4. `term_first` — 第一次 / 最早 / 什么时候 + 表情词
5. `term_lookup` — 有没有 / 表情里 + 表情词
6. `person_age` — 几岁 / 多大
7. `person_peak_day` — 哪天的照片最多 / 在什么地方
8. `person_emotion_place_rank` — 表情 + 哪个地方最多（如「笑的最多」）
9. `person_place_rank` — 常去 / 去哪最多（不限表情）
10. `person_cities_visited` — 哪些城市 / 哪些省（结构化地址）
11. `person_places_visited` — 去过哪些地方（POI 列表）
12. `person_at_place` — 去某地什么时候 / 去过几次
13. `person_recent_places` — 最近在哪 / 去过（时间序）
14. `recent_photos` — 最近 + 照片，或仅「照片」
15. **fallback** — 当前仍落到 `recent_photos`（已知问题）

---

### `person_peak_day` — 哪天照片最多

| 项 | 说明 |
|----|------|
| **触发** | 「哪天的照片最多」「哪一天拍最多」+ 含「照片」 |
| **参数** | `person`、`limit`（默认 10，用于并列峰值检测） |
| **查库** | `get_person_peak_day()` — 按日聚合，取峰值及当天地点 |
| **回答** | 日期、张数、主要地点、当时年龄（`age_label` 有则显示） |

示例：

```bash
python tools/memory_ask/main.py "面面哪天的照片最多，在什么地方"
```

---

### `person_at_place` — 在某地什么时候 / 几次

| 项 | 说明 |
|----|------|
| **触发** | 句中含具体地名 +「去/在」+「什么时候 / 几次 / 玩过 / 是几岁 / 去过吗」等 |
| **参数** | `person`、`place`（从问句抽取，如「动物园」）、`focus`：`age` \| `yesno`（问「…吗」） |
| **查库** | `get_person_at_place()` — `location` + `location_province/city/district` 模糊匹配 |
| **回答** | 照片数/天数、首末到访、各次到访按日列表（含当时 `age_label`）；支持省/市如「四川」 |

示例：

```bash
python tools/memory_ask/main.py "面面去动物园是什么时候？去过几次"
python tools/memory_ask/main.py "面面去四川玩过几次"
python tools/memory_ask/main.py "面面去山东是几岁"
python tools/memory_ask/main.py "面面在共青森林公园玩过几次"
python tools/memory_ask/main.py "爸爸去过迪士尼吗"
```

地名用模糊匹配（「动物园」→「上海动物园」）。

---

### `person_place_rank` — 常去哪里（全时期）

| 项 | 说明 |
|----|------|
| **触发** | 「常去 / 最多 / 去哪 / 待最久」等，且**未**指定几岁 |
| **参数** | `person`、`limit`（默认 10） |
| **查库** | `get_person_place_rank()` — 全时期 `location` 聚合 |
| **回答** | 按地点列出照片张数、天数 |

示例：

```bash
python tools/memory_ask/main.py "面面常去的地方是哪里"
```

与 `person_recent_places`（按时间列最近几个地点）和 `person_age_place_rank`（限定某岁）区分。

---

### `person_emotion_place_rank` — 哪个地方某表情最多

| 项 | 说明 |
|----|------|
| **触发** | 含表情词（笑/哭/开心…）+「地方/地点」+「最多/常去」 |
| **参数** | `person`、`term`、`term_type`（默认 emotion）、`limit` |
| **查库** | `get_person_emotion_place_rank()` — 有该 `photo_terms` 标注且 `location` 非空的照片按地点聚合 |
| **回答** | 地点排名 + 匹配到的表情词分布 |

示例：

```bash
python tools/memory_ask/main.py "面面在哪个地方笑的最多"
```

依赖 vision backfill 的 `emotion` 字段；无地点的表情照片不计入地点排名。

---

### `person_places_visited` — 去过哪些地方（POI）

| 项 | 说明 |
|----|------|
| **触发** | 「哪些地方 / 什么地方 / 去过哪些」（不含「城市」） |
| **参数** | `person`、`limit`（默认 20） |
| **查库** | `get_person_place_rank()` — 全时期 `location` 去重聚合 |
| **回答** | 总地点数 + 按照片数列出前 N 个 POI |

示例：

```bash
python tools/memory_ask/main.py "妈妈去过哪些地方"
```

与 `person_place_rank`（「常去/最多」语义）和 `person_cities_visited`（省/市级）区分。

---

### `person_cities_visited` — 去过哪些城市/省

| 项 | 说明 |
|----|------|
| **触发** | 「哪些城市 / 什么城市 / 去过哪些城市」；「哪些省 / 什么省」→ `group_by=province` |
| **参数** | `person`、`limit`（默认 20）、`group_by`：`city` \| `province` |
| **查库** | `get_person_cities_visited()` — 按 `location_city`（直辖市用 `location_province`）聚合 |
| **回答** | 城市/省列表 + 每处照片张数、天数 |

示例：

```bash
python tools/memory_ask/main.py "面面去过哪些城市"
python tools/memory_ask/main.py "面面去过哪些省"
```

与 `person_place_rank`（POI 级 `location`）和 `person_recent_places`（时间序最近地点）区分。

---

## 已实现意图

### `library_stats` — 库内数量统计

| 项 | 说明 |
|----|------|
| **触发** | 含「多少 / 几张 / 一共 / 总共 / 统计」等；含「字段 / 分布 / 每个」时 `focus=fields` 输出全字段 |
| **参数** | `person`（可选）、`focus`：`all` \| `fields` \| `emotion` \| `scene` \| `face` \| `location` |
| **查库** | `get_library_stats()` — 各字段覆盖数 + emotion/tags/objects/actions/device 分布 |
| **回答** | 默认：总张数 + 四项占比；`fields` 模式：12 个字段全覆盖 + Top 分布 |

示例：

```bash
python tools/memory_ask/main.py "有多少张有表情的"
python tools/memory_ask/main.py "统计下数据每个字段对应的有几条数据，以及分布情况"
python tools/memory_ask/main.py "面面有多少张照片"
python tools/memory_ask/main.py "一共多少张照片"
```

---

### `person_age_place_rank` — 某岁常去哪里

| 项 | 说明 |
|----|------|
| **触发** | `4岁` / `四岁` +「最多 / 常去 / 待最久 / 去哪 / 哪个地方」等 |
| **参数** | `person`、`age_years`、`limit`（默认 10） |
| **查库** | `get_person_age_place_rank()` — `photo_people.age_label` + `photos.location` 聚合 |
| **回答** | 按地点列出照片张数、天数；注明「待最久」以张数/天数估算 |

示例：

```bash
python tools/memory_ask/main.py "面面4岁时在哪个地方待的时间最长"
python tools/memory_ask/main.py "面面四岁时去哪最多"
```

**依赖**：`age_label`（人脸入库时写入）、`location`（逆地理 + 同日归一）。

---

### `term_first` — 某表情/词条最早何时

| 项 | 说明 |
|----|------|
| **触发** | 表情词（哭、微笑…）+「第一次 / 首次 / 最早 / 什么时候 / 何时」 |
| **参数** | `person`（可选）、`term`、`term_type`（固定 `emotion`） |
| **查库** | `get_term_first_photo()` — `photo_terms` + `timestamp` 升序取 1 条 |
| **回答** | 最早时间、`age_label`、地点、`photo_id` |

示例：

```bash
python tools/memory_ask/main.py "第一次哭是什么时候"
python tools/memory_ask/main.py "面面第一次哭是什么时候"
```

**依赖**：`photo_terms`（vision backfill 写入 emotion）；覆盖率不足时可能查不到。

---

### `term_lookup` — 有没有某表情 / 多少张

| 项 | 说明 |
|----|------|
| **触发** | 表情词 +（「表情 / 情绪」或「有…吗 / 有没有」或「照片」） |
| **参数** | `person`（可选）、`term`、`term_type`（`emotion`） |
| **查库** | `get_term_photo_stats()` — `photo_terms` LIKE 匹配 + `search_photos` 抽样 |
| **回答** | 张数、细分词条（哭泣/哭/哭闹…）、最近几张列表 |

示例：

```bash
python tools/memory_ask/main.py "表情里没有哭吗"
python tools/memory_ask/main.py "面面有哭的照片吗"
```

支持的表情关键词见 `agent.py` 中 `_EMOTION_TERM_HINTS`（哭、微笑、开心、平静等）。

---

### `person_age` — 当前几岁

| 项 | 说明 |
|----|------|
| **触发** | 「几岁 / 多大 / 年龄 / 年岁」 |
| **参数** | `person` |
| **查库** | `get_person_age()`（registry `birth_date`）+ `get_person_age_from_latest_photo()` |
| **回答** | 今天年龄；最近一张照片里的 `age_label` |

示例：

```bash
python tools/memory_ask/main.py "面面几岁了"
```

---

### `person_recent_places` — 最近去过哪

| 项 | 说明 |
|----|------|
| **触发** | 「在哪 / 哪里 / 去过 / 地方」；或仅「最近」且能解析出人名 |
| **参数** | `person`、`limit` |
| **查库** | `get_person_recent_places()` — 按时间倒序，去重 `location` |
| **回答** | 时间 + 地点（+ scene 若有） |

示例：

```bash
python tools/memory_ask/main.py "面面最近在哪里玩"
```

---

### `group_photos` — 多人合影

| 项 | 说明 |
|----|------|
| **触发** | 句中含 ≥2 位家庭成员 +「合影/合照/同框」；或「A和B」+「照片/有哪些」 |
| **参数** | `persons`（按问句出现顺序）、`limit`（默认 20） |
| **查库** | `get_group_photos()` — `photo_people` 同时包含所有指定成员 |
| **回答** | 合影总数 + 最近若干张列表 |

示例：

```bash
python tools/memory_ask/main.py "妈妈和面面的合影有哪些"
python tools/memory_ask/main.py "爸爸和妈妈合照"
```

仅当照片中**同时**识别到所有指定成员才计入；人脸未识别到的合影不会出现。

---

### `recent_photos` — 最近照片列表

| 项 | 说明 |
|----|------|
| **触发** | 「最近」+「照片」；或句中只有「照片」；**或未匹配任何意图时的 fallback** |
| **参数** | `person`（可选）、`limit` |
| **查库** | `get_recent_photos()` — `list_timeline` 或 `search_photos(person=…)` |
| **回答** | `photo_id`、时间、人物、地点、场景 |

示例：

```bash
python tools/memory_ask/main.py "最近的照片"
```

---

## 调试

```bash
python tools/memory_ask/main.py "你的问题" --debug
```

输出 `intent`、完整 `facts` JSON，便于核对路由与查库结果。

Ollama 文本模型（`OLLAMA_CHAT_MODEL`）可用时会在事实基础上润色；连接失败则仅用模板，不影响查库。

---

## 已知限制

| 问题 | 说明 |
|------|------|
| 未识别问题 | 仍默认 `recent_photos`，易答非所问 → 计划改为 `unknown` + 示例提示 |
| 说法变体 | 正则无法覆盖所有中文；高频句式靠迭代补充 |
| emotion / scene | 仅 vision 已 backfill 的照片有值；统计类问题需接受「补全中」 |
| 复合条件 | 如「4岁在公园哭过几次」= 年龄 × 地点 × 表情，尚未实现 |
| 地点搜索 | `person_at_place` 已支持按地名模糊查；`search_photos` 通用搜索仍仅在 index 层 |

---

## 规划中的意图（未实现）

| 意图 | 触发设想 | 前置条件 |
|------|----------|----------|
| `person_age_emotion` | 「4岁时常什么表情」 | emotion 覆盖率 > ~30% |
| `unknown` | 无法路由 | 替换 fallback 行为 |

---

## 相关文件

| 文件 | 职责 |
|------|------|
| `hub/shared/agent.py` | `route_intent`、`_template_answer`、Ollama 调用 |
| `hub/shared/query.py` | `gather_facts` 与各 `get_*` 查询 |
| `hub/shared/index_db.py` | `search_photos`、`list_timeline`、表结构 |
| `tools/memory_ask/main.py` | CLI 入口 |
| `data/faces/registry.json` | 家庭成员姓名、birth_date |

日常操作见 [operations.md](operations.md)；整体架构见 [architecture.md](architecture.md)。
