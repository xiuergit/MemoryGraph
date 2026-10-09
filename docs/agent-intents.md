# CLI 问答 Agent 意图说明

> 实现：`hub/shared/agent.py`（路由 + 模板） · `hub/shared/query.py`（查库）  
> 入口：`python tools/memory_ask/main.py "你的问题"` · Desk `POST /api/ask` · Vue / iOS  
> **阶段 2（当前）**：打磨路由与检索，少答非所问；清单见文末「阶段 2 目标」  
> **日常打勾**：Vue「问答」→ **错题本**（`data/ask_checklist.json`；说明见 [ask-checklist.md](ask-checklist.md)）

## 设计原则

意图不是「理解每一句自然语言」，而是 **问题类型 → 查哪几列 → 返回事实 JSON → 模板或 Ollama 组织回答**。

| 数据层 | 典型字段 | 当前状态（约） | 适合问的 |
|--------|----------|----------------|----------|
| **A. 档案/索引** | 计数、`birth_date`、`age_label` | 完整 | 几岁、多少张、某岁排行 |
| **B. 时间线** | `timestamp`、`location`、`photo_terms` | 人物/地点较强；`location` ~82%；`scene`/`tags`/`objects` ~90%+ | 最近去哪、第一次、有没有某标签 |
| **C. 语义/感受** | `scene`、`emotion`、`tags` | scene/tags 已基本齐；`emotion` 仍偏稀（~40%） | 场景/标签可依赖；细腻表情类仍宜作补充 |

新增意图时：先列自己常问的句子 → 标 A/B/C → 确认 SQLite 有字段 → 再加路由。未匹配时走 `unknown` + 可问示例（**不要**默认「最近照片」）。

## 处理流程

```
用户问题
    → route_intent()        正则路由，提取 person / age / term 等参数
    → gather_facts()        查 memorygraph.db，组装 facts JSON
    → build_evidence()      从 facts 抽出统一 evidence（media/event/story + media_type）
    → _template_answer()    模板回答（默认；关键词/最近认媒体类型）
    → _llm_answer()         可选：Ollama 润色（失败则仍用模板；锁 facts）
```

Desk `POST /api/ask` 返回：`intent` / `answer` / `facts` / **`evidence`** / `follow_ups` / `context`。
「依据是什么」读上一轮 `basis_summary`（含 media/event/story 样例 id）。见 [architecture.md](architecture.md) 证据合同。

人物名从 `data/faces/registry.json` 读取。问句未写人名时：若档案里 **恰好一名 `role=child`**（当前为面面），或有效成员仅一人，则默认该人；全库统计（「一共多少张」）不默认。

## 路由优先级

高 → 低（先匹配先生效）：

0. `recent_photos` — **优先**：「列出最后 N 张 / 最近 N 张」（含「去哪了，列出10张」类复合问句）
0b. `story_lookup` — 含「故事」
0c. `person_artwork` — 画作 / 作品集
0d. `person_home_timeline` — 住过哪 / 呆最久（家事件跨度）
0d2. **追问（有 `context`）** — `explain_basis` / `period_emotion` / `period_companions`（依据、开心吗、见了谁）
0e. `recent_outings` / `outings_at_place` / `outings_by_period` / **`period_recap`** — 出门；`period_recap` = 时段出门 + 开心吗 + 见了谁
1. `person_age_place_rank` — N 岁 + 去哪最多 / 待最久
2. `library_stats` — 多少张 / 一共 / 统计
3. `group_photos` — X和Y合影 / 合照有哪些
3b. `person_companion_rank` — 和谁合影最多 / 哪个人合照最多（同框排行）
4. `term_first` — 第一次 / 最早 / 什么时候 + 表情词
4b. `person_at_place` — **去某地是什么时候** / 第一次去某地（须先于 `keyword_first`）
5. `term_lookup` — 有没有 / 表情里 / **人名+表情短句**（面面哭）+ 表情词
6. `person_age` — 几岁 / 多大
7. `person_peak_day` — 哪天的照片最多 / 在什么地方
8. `person_emotion_place_rank` — 表情 + 哪个地方最多（如「笑的最多」）
9. `person_place_rank` — 常去 / **哪个地方**去最多（口语「去哪里了」不算排名；「呆最久」走家时间线）
10. `person_cities_visited` — 哪些城市 / 哪些省（结构化地址）
11. `person_places_visited` — 去过哪些地方（POI 列表）
12. `companions_at_place` — 哪些人 / 和谁 去过某地（同框人物）
12b. `person_at_place` — 去某地几次 / 去过吗（无「什么时候」时）
13. `person_recent_places` — 最近在哪 / 去过（时间序）
14. `recent_photos` — 最近 + 照片；或「人名的照片」（全量，非默认 10 张）
14b. `keyword_search` — 有没有X / 搜X / X的照片 / **人名+活动短句**（面面骑车、面面坐船）
14c. `keyword_first` — 第一次 / 最早 / 什么时候 + 活动词（面面第一次轮滑；**不含**「去某地是什么时候」）
15. **`unknown`** — 未匹配时提示可问示例（不再落到 `recent_photos`）

---

### `recent_outings` — 最近出门（事件）

| 项 | 说明 |
|----|------|
| **触发** | 「出去玩」「出门玩了哪些」「最近出门」等 |
| **参数** | `person`（可选）、`limit` |
| **查库** | `events` 表（`is_home=0`），优先显示 `overlay.title` |
| **回答** | 口语按天汇总（同 `outings_by_period`）；细节看证据区 |

```bash
python tools/memory_events/main.py sync   # 需先聚合
python tools/memory_ask/main.py "最近出去玩了哪些"
```

### `person_home_timeline` — 住过哪（家事件时间线）

| 项 | 说明 |
|----|------|
| **触发** | 「住过哪」「搬过」「呆的时间最长」「哪个地方呆最久」等 |
| **查库** | `events` 且 `is_home=1`，按地点聚合 `MIN(day)–MAX(day)` |
| **回答** | 长期住址迁居时间线 + 年龄跨度；开场标明「家、不含出门酒店」；点出住得最久的一处 |

```bash
python tools/memory_ask/main.py "面面在哪个地方呆的时间最长"
python tools/memory_ask/main.py "面面住过哪些地方"
```

### `outings_by_period` — 按年 / 季 / 节假日列出门

| 项 | 说明 |
|----|------|
| **触发** | ① 年（2024年 / 去年 / 今年）或季（春夏秋冬）+ 出门/出去玩；② **节假日**（国庆/春节/五一/中秋/端午/清明/元旦 等）+ 去哪/出去玩/出门，或「去年国庆」裸问 |
| **查库** | outing 事件：年/季用 `day` 前缀 + 可选月份；假日用 `day_from`～`day_to`（国务院放假窗，前后各扩 1 天） |
| **回答** | 口语按天汇总地点（不去堆每趟张数/人名）；点出照片最多的一处；细节看证据区 |
| **注意** | 「春节」不会误当成「春」季；「国庆的照片 / 2023年国庆节相关照片」走 `keyword_search`，但按放假日期窗搜图，不靠 tags 里写「国庆」 |

```bash
python tools/memory_ask/main.py "面面2024年出去玩了哪些"
python tools/memory_ask/main.py "去年春天出门"
python tools/memory_ask/main.py "去年国庆去哪里玩了"
python tools/memory_ask/main.py "2024年春节出门"
```

### `period_recap` — 时段出门 + 开心吗 + 见了谁（复合口语）

| 项 | 说明 |
|----|------|
| **触发** | 同 `outings_by_period` / 最近出门，且句中还问 **开心/高兴** 或 **见了谁/哪些人** |
| **查库** | 出门事件 + 同日窗内 emotion 词频 + 同框人物；证据图附时段样例 |
| **回答** | 先讲去哪，再据标注说开不开心（不足则明说看不太出），再列同行人 |
| **示例** | 「去年国庆去哪里玩了？开心吗？见了哪些人？」 |

```bash
python tools/memory_ask/main.py "去年国庆去哪里玩了？开心吗？见了哪些人？"
```

### 轻量追问（`POST /api/ask` + `context`）

| 意图 | 触发（须带上一轮 context） | 行为 |
|------|---------------------------|------|
| `explain_basis` | 依据是什么 / 怎么知道 / 证据 | 用上一轮 `basis_summary` 说明查了什么，不编造 |
| `period_emotion` | 开心吗 / 高兴吗 | 同一 `day_from`～`day_to` 看 emotion |
| `period_companions` | 见了谁 / 哪些人 | 同一时段同框人物 |
| （复用） | 还有吗 | 用 `last_params` 再查上一意图 |

响应另含 `follow_ups`（芯片文案）与 `context`（供下一轮）。Vue / iOS 点芯片时自动带 context。

### `outings_at_place` — 某地几趟出门

| 项 | 说明 |
|----|------|
| **触发** | 地名 +「几趟 / 几次出门 / 几次活动 / 去过几次」 |
| **查库** | `events.location` 模糊匹配 |

### `story_lookup` — 跨天故事

| 项 | 说明 |
|----|------|
| **触发** | 问句含「故事」 |
| **查库** | `stories` 标题/正文；Vue「事件」Tab 创建 |

### `person_artwork` — 画作 / 作品集

| 项 | 说明 |
|----|------|
| **触发** | 「画作」「作品集」「画画」等 |
| **参数** | `person`（可选）、`limit` |
| **查库** | `get_person_artwork()` — vision 标签 + 同场事件关联（不要求画上标人物） |
| **回答** | 相关照片列表；区分同场关联 / 画面含本人 |

```bash
python tools/memory_ask/main.py "面面的画作"
```

### `keyword_search` — 关键词检索（场景 / 地点 / 标签）

| 项 | 说明 |
|----|------|
| **触发** | 「有没有X」「搜X」「X的照片」「关于X」等（X **不是**已知人名） |
| **参数** | `query`（关键词）、`person`（可选）、`limit`；节假日照片另带 `day_from` / `day_to` |
| **查库** | 默认 `search_photos(query=…)` — `scene` / `location` / `photo_terms` LIKE；**节假日+照片** 改为拍摄日闭区间 |
| **回答** | 命中总数口语短答；`photos` 返回全部命中（上限内），Web 证据区分页展示 |

```bash
python tools/memory_ask/main.py "面面骑车的照片"
python tools/memory_ask/main.py "蛋糕的照片"
python tools/memory_ask/main.py "面面 搜公园"
python tools/memory_ask/main.py "有关山西的照片"
python tools/memory_ask/main.py "老家的照片"
```

表情类「面面哭 / 有没有哭」走 `term_lookup`（优先级更高）。  
「骑车 / 坐船 / 游泳 / 玩水 / 爬山…」等人名+活动短句走 `keyword_search`（多数按 **actions** 匹配，减少背景误伤）。  
「过生日 / 生日 / 庆生」走别名（索引多为「生日」而非「过生日」）；**带人名时**再并入 registry `birth_date` 的周年日（±1 天）照片并排在前面。  
地名「山西 / 忻州 / 老家」走 **省市区字段**（`location_province/city`）；`老家` 默认映射为 **忻州**（见 `query._PLACE_ALIASES`）。  
**人名**「抱补的照片 / 面面的照片」走 `recent_photos`（`list_all`，返回该人全部照片，不是默认 10 张）。

```bash
python tools/memory_ask/main.py "面面过生日"
python tools/memory_ask/main.py "面面生日"
python tools/memory_ask/main.py "2023年的国庆节相关照片"
```

节假日名一般不会写进 tags。问「国庆的照片」按国务院放假窗（前后各扩 1 天）列该时段照片；「去年国庆去哪里玩了」仍走出门事件。

### `unknown` — 未识别

| 项 | 说明 |
|----|------|
| **触发** | 未匹配任何意图（含裸「最近」且无人名） |
| **查库** | 无 |
| **回答** | 「暂时无法理解」+ 可问示例 |

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

### `companions_at_place` — 哪些人去过某地（同框）

| 项 | 说明 |
|----|------|
| **触发** | 「哪些人 / 和谁 / 有谁」+ 去过 + 地名；可带锚点人名（如面面）；可带「什么时候 / 分别」 |
| **参数** | `person`（可选）、`place`、`limit`（证据图默认全量）、`focus=when`（问分别何时） |
| **查库** | `get_companions_at_place()` — 该地（且含锚点时）照片上的同框人物；每人含 `visit_days` / `day_count` |
| **回答** | 同框人物 + 到访日期（有则列出）+ 相关证据图 |

```bash
python tools/memory_ask/main.py "面面哪些人去过动物园"
python tools/memory_ask/main.py "面面和谁去过迪士尼"
python tools/memory_ask/main.py "面面和谁去过动物园，分别是什么时候"
```

与 `person_at_place`（只问某人何时去某地、不拆同框）区分：含「和谁/哪些人」时优先本意图，即使句中有「什么时候」。

---

### `person_companion_rank` — 和谁合影最多

| 项 | 说明 |
|----|------|
| **触发** | 「和哪个人 / 和谁」+「合影/合照/同框」+「最多 / 比较多」；或「合影最多的人」 |
| **参数** | `person`、`limit`（排行人数，默认 12）、`photo_limit`（与第一名同框的证据图）；可选 `since` + `period_label`（「最近3个月 / 近半年 / 最近两周」） |
| **查库** | `get_person_companion_rank()` — `photo_people` 同框计数，排除 `unk_*`；有 `since` 时按 `timestamp` 过滤 |
| **回答** | 第一名 + 同框排行 + 与第一名的合影证据图（有时间窗时回答里带「最近N…」） |

与 `group_photos`（指定两人列合影）、`companions_at_place`（某地同框）、`person_place_rank`（地点排行，勿因「最多」误入）区分。

```bash
python tools/memory_ask/main.py "面面和哪个人的合影最多"
python tools/memory_ask/main.py "面面和谁合照最多"
python tools/memory_ask/main.py "面面最近3个月和谁合影比较多"
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
| **触发** | 「哪些地方 / 什么地方 / 去过哪些 / 去了哪些地方」（不含「城市」）；也可「A和B去了哪些地方」 |
| **参数** | `person`、`limit`（默认 20）；可选 `companions`（同框同伴）、`since` + `period_label`（最近 N 月/天） |
| **查库** | `get_person_place_rank()` — `location` 去重聚合；有同伴时须同框；有 `since` 时按 `timestamp` 过滤 |
| **回答** | 总地点数 + 按照片数列出前 N 个 POI |

示例：

```bash
python tools/memory_ask/main.py "妈妈去过哪些地方"
python tools/memory_ask/main.py "面面最近三个月和抱补去了哪些地方"
```

与 `person_place_rank`（「常去/最多」语义）、`group_photos`（合影清单）、`person_cities_visited`（省/市级）区分。

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

**依赖**：`photo_terms`（vision backfill 写入 emotion）；`emotion` 仍约四成有值，未标注时可能查不到。

---

### `term_lookup` — 有没有某表情 / 多少张

| 项 | 说明 |
|----|------|
| **触发** | 表情词 +（「表情 / 情绪」或「有…吗 / 有没有」或「照片」）；或 **人名+表情短句**（`面面哭` / `面面笑`）；或「为什么/为啥哭」 |
| **参数** | `person`（可选）、`term`、`term_type`（`emotion`）、`focus`（`why` 可选） |
| **查库** | `get_term_photo_stats()` — 仅 `photo_terms` 的 emotion 匹配 |
| **回答** | 张数、细分词条；`focus=why` 时说明原因未标注并附场景摘要。证据图用模板（不经 LLM 砍数量） |

示例：

```bash
python tools/memory_ask/main.py "面面哭"
python tools/memory_ask/main.py "面面为什么哭"
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
| **参数** | `persons`（按问句出现顺序）、`limit`（默认全量；写「N张」才截断） |
| **查库** | `get_group_photos()` — `photo_people` 同时包含所有指定成员 |
| **回答** | 合影总数 + 全部证据图（Web 分页） |

示例：

```bash
python tools/memory_ask/main.py "妈妈和面面的合影有哪些"
python tools/memory_ask/main.py "爸爸和妈妈合照"
```

仅当照片中**同时**识别到所有指定成员才计入；人脸未识别到的合影不会出现。

---

### `recent_photos` — 最近照片 / 某人全部照片

| 项 | 说明 |
|----|------|
| **触发** | 「最近」+「照片」；「列出 N 张」；或「人名的照片」（无「最近」） |
| **参数** | `person`（可选）、`limit`（「最近」默认 10；「人名的照片」默认全量/`list_all`） |
| **查库** | `get_recent_photos()` — `list_timeline` 或 `search_photos(person=…)`；`list_all` 时附 `photo_count` |
| **回答** | 最近：口语「最近有 N 张」；某人全量：「一共找到 N 张」+ 证据图（Web 分页） |

示例：

```bash
python tools/memory_ask/main.py "最近的照片"
python tools/memory_ask/main.py "抱补的照片"
python tools/memory_ask/main.py "面面最近10张照片"
```

---

## 调试

```bash
python tools/memory_ask/main.py "你的问题" --debug
```

输出 `intent`、完整 `facts` JSON，便于核对路由与查库结果。

Ollama 文本模型（`OLLAMA_CHAT_MODEL`）可用时会在事实基础上润色；连接失败则仅用模板，不影响查库。

---

| 处理流程 | 说明 |
|----------|------|
| `route_intent` | 正则路由 |
| `gather_facts` | 查库 → 意图相关 facts |
| `_template_answer` / `_llm_answer` | 组句（LLM 锁 facts） |
| `build_evidence` | 从 facts 抽出统一 **evidence**（media/event/story ids + `media_type`） |

Desk `POST /api/ask` 返回：`intent` / `answer` / `facts` / **`evidence`** / `follow_ups` / `context`。
「依据是什么」读上一轮 `basis_summary`（含 media/event/story 样例 id）。

---

## 已知限制

| 问题 | 说明 |
|------|------|
| 说法变体 | 正则无法覆盖所有中文；高频句式靠迭代补充 |
| emotion / scene | `scene`/`tags`/`objects` 已约九成有值；`emotion` 仍约四成，表情类统计可能偏少 |
| 复合条件 | 人名×地点×同框时间已通（`companions_at_place`+when）；年龄×地点×表情等仍待做 |
| 关键词边界 | `keyword_search` 靠句式抽取；过短/停用词会落到 `unknown` |
| Day ≠ Outing | 日历日切片见 `GET /api/day-slice`；出门事件见 `/api/events`，二者不可互换 |

---

## 阶段 2 目标

| 优先级 | 项 | 状态 |
|--------|----|------|
| P0 | `unknown` 意图 | ✅ 已替换 fallback |
| P0 | `keyword_search` | ✅ 已接线 `search_photos`；话术认 `media_type` |
| P1 | 复合过滤（先做 2 维） | 🚧 人名×活动/表情、同框×地点×时间已通；合影排行×最近N月/天已通；**两人×时间窗×地点列表**已通；年龄×地点、地点×表情仍待做 |
| P1 | 单人默认人物 | ✅ 唯一 `child`（面面）或唯一成员时默认 |
| P1 | 复合口语拆解 `period_recap` | ✅ 时段出门 + 开心吗 + 见了谁 → 一次查库合成（国庆样例） |
| P1 | 叙事类 LLM 润色 | ✅ 出门回顾 / 追问等放开；统计与排行仍模板 |
| P1 | 答后「可继续问」芯片 | ✅ `follow_ups` + Vue / iOS |
| P1 | 轻量追问 `context` | ✅ `POST /api/ask` 可选上一轮；依据 / 开心吗 / 见了谁 |
| P1 | 统一 **evidence** 合同 | ✅ `hub/shared/evidence.py`；Desk/Vue/iOS；依据可列 media id |
| P1 | 答案与证据对齐 | ✅ 关键词/最近话术用 media 量词；`explain_basis` 引 evidence |
| P2 | 端上证据 | ✅ iOS 读 `evidence.media`；示例芯片覆盖更多意图 |
| — | 暂不做 | 向量 RAG、**完整多轮会话库**、流式输出、闲聊 Bot |

可选：`person_age_emotion`（「N 岁时常什么表情」）。

---

## 长期形态：有据记忆智能体（非闲聊）

北极星：**听懂口语 → 拆成可查事实 → 用照片/事件/故事回答 → 允许追问；不编造。**

| 层 | 内容 | 状态 |
|----|------|------|
| **A** | 一句多问拆解、叙事润色（锁 facts）、继续问芯片 | ✅ 本阶段 |
| **B** | `last_turn` 上下文：依据 / 开心吗 / 见了谁 | ✅ 本阶段（无长期 session 落盘） |
| **C（远期）** | 人物画像聚合、短会话、工具化查库；依赖旁白/故事录入 | 🔜 见 [architecture.md](architecture.md) |

产品隐喻：记忆图书管理员 + 温和讲述者。人格来自 registry / 事件 / 故事 / `user_note`，不是模型装熟。

---

## 相关文件

| 文件 | 职责 |
|------|------|
| `hub/shared/agent.py` | `route_intent`、`_template_answer`、Ollama 调用 |
| `hub/shared/query.py` | `gather_facts` 与各 `get_*` 查询 |
| `hub/shared/index_db.py` | `search_photos`、`list_timeline`、表结构 |
| `tools/memory_ask/main.py` | CLI 入口 |
| `tools/memory_desk/app.py` | `POST /api/ask` |
| `web/src/components/MemoryAsk.vue` | Web 问答 UI |
| `apps/ios/MemoryGraph/Views/Ask/` | iOS 问问 |
| `data/faces/registry.json` | 家庭成员姓名、birth_date |
| [`ask-checklist.md`](ask-checklist.md) | 错题本说明；UI 在 Vue「问答」 |

日常操作见 [operations.md](operations.md)；整体架构见 [architecture.md](architecture.md)；阶段划分见 [Project Charter](Project%20Charter.md)。
