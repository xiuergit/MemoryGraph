# 手机 Outbox 实施计划（新窗口用）

> 设计合同：[mobile-outbox.md](mobile-outbox.md)  
> 原则：**先协议与 Mac 收件，再 iOS/iPad UI**；每阶段可单独合并、可停。

---

## 新窗口开场白（可复制）

```
按 docs/mobile-outbox.md + docs/mobile-outbox-plan.md 推进。
本窗口只做【阶段 X】：……
不要扩大范围；改 schema 须同步 schema.py / schemas/README；隐私不读 data/photos 原图。
```

建议：**一个窗口只做一个阶段**（尤其 S1 与 A 分开更清晰）。

---

## 总顺序（不要倒）

```
S1 协议字段          ← 现在就可以开窗口
  → A  Mac ingest（原图落盘 + hash + 回执）
  → B  describe API + Vue 能写旁白（验证合同）
  → C  story upsert 幂等（Desk 已有 CRUD，补 mutation/幂等若需要）
  → E  iOS/iPad Outbox UI（最后）
```

手机端依赖 A/B（至少能收图 + 写 `user_note`）；故事可与 B 并行，但 **E 必须在 A 之后**。

---

## 阶段 S1 — 协议：`user_note`（先做）

**目标：** 正式合同落地，旧 JSON 仍可读。

| 做 | 不做 |
|----|------|
| `photo.v1` 枚举加 `1.4`；`user_note` + `manual_note` | 不改 iOS |
| `video.v1` → `1.1`、`audio.v1` → `1.1` 同构字段 | 不实现上传 |
| `hub/shared/schema.py` 读写 + `manual_note` 计入 `manual_edit` 汇总 | |
| `schemas/README.md`、示例可选更新 | |
| index sync：`user_note` 进可检索（或明确 TODO 下一小步） | |

**完成标准：** 手工改一条 memory JSON 写入旁白 → sync 后检索/详情能读到（若检索留待 B，至少 JSON 合法且 schema 校验过）。

**新窗口提示词：**

```
只做阶段 S1（docs/mobile-outbox-plan.md）：
给 photo/video/audio schema 加可选 user_note + manual_note，
同步 schema.py 与 schemas/README。不要做 Desk/iOS。
```

---

## 阶段 A — Mac：回家收原图（ingest）

**目标：** 局域网上传原图 → `data/photos/YYYY/MM/ob_<8>_<stem>.ext` → 回执 `local_id→photo_id`；hash 去重。

| 做 | 不做 |
|----|------|
| Desk（或吸收 mac_server）`POST` ingest：multipart 文件 + `local_id` | 不做 iOS UI |
| 落盘规则见 mobile-outbox §5 | 不阻塞等 Ollama（分析异步/队列） |
| SHA-256：已存在则 `duplicate`，复用 `photo_id`，可不留第二份文件 | |
| 触发或排队 `photo2json`/analyze + 后续可手动 sync | |

**完成标准：** `curl`/脚本上传一张图 → 文件出现在约定目录 → 回执带 `photo_id`；再传同一字节 → `duplicate` 且同一 `photo_id`。

**实现（已落地）：**

- `POST /api/media/ingest`（`tools/memory_desk/app.py`）
- 核心：`hub/shared/media_ingest.py`；hash 旁路表 `data/ingest_registry.json`
- 表单：`file` + `local_id`（必填）；可选 `mutation_id` / `device_id` / `captured_at` / `queue_analyze`
- 默认异步排队 `process_one_image`（不阻塞 HTTP）；可用 `queue_analyze=false` 只落盘
- **ingest 后立刻写 memory stub JSON**（空语义），故 `media.describe` 不必等 AI；后台 analyze **merge** 保留 `user_note` / `manual_*`

```bash
curl -sS -X POST "http://127.0.0.1:8765/api/media/ingest" \
  -F "file=@/path/to/shot.jpg" \
  -F "local_id=demo_local_001" \
  -F "mutation_id=$(uuidgen)" \
  -F "device_id=iphone" \
  -F "captured_at=2026-09-15T12:00:00" \
  -F "queue_analyze=false"
```

**新窗口提示词：**

```
按 docs/mobile-outbox.md + docs/mobile-outbox-plan.md 推进。
本窗口只做【阶段 A】：Desk media.ingest（multipart 原图 + local_id →
落盘 data/photos/YYYY/MM/ob_<8>_<stem>.ext；SHA-256 去重；回执 local_id→photo_id；
accepted|duplicate|conflict）。合同见 mobile-outbox.md §5–§6。
分析可异步/排队，不要阻塞等 Ollama。不要做 describe / 故事 / iOS。隐私不读 data/photos 原图做试验。
```

---

## 阶段 B — 描述写入

**目标：** `media.describe` 或等价 API：按 `photo_id` 写 `user_note` + `manual_note: true`；Vue 详情可编辑（先验证真源）。

| 做 | 不做 |
|----|------|
| API 幂等（可带 `mutation_id`） | 不做完整 Outbox 队列 UI |
| Vue MemoryDetail（或列表）编辑旁白 | 不做 iOS；不做 ingest 重做 |
| 写入后 `schema_version` 建议升到 1.4；`refresh_manual_edit_flag` | |
| backfill vision **不得**覆盖 `manual_note` 的 `user_note` | |

**完成标准：** Desk/Vue 改旁白 → JSON 落盘 → 刷新仍在；backfill vision **不冲掉** `user_note`。  
可选：`user_note` 进 keyword_search / index 投影（合同开放问题；建议做）。

**实现（已落地）：**

- `POST /api/media/describe`（`tools/memory_desk/app.py`）
- 核心：`hub/shared/media_describe.py` → `apply_user_note`（`memory_edit.py`）
- 幂等旁路表：`data/describe_registry.json`（按 `mutation_id`）
- Vue `MemoryDetail` 旁白框 → `PUT /api/memory/update`（`user_note`）
- index：`user_note` 进 `photo_terms`（`term_type=user_note`），参与 keyword_search
- vision `_merge_vision` **不写** `user_note` / `manual_note`

```bash
curl -sS -X POST "http://127.0.0.1:8765/api/media/describe" \
  -H "Content-Type: application/json" \
  -d '{"photo_id":"EXISTING_PHOTO_ID","user_note":"今天第一次自己吃饭","mutation_id":"'"$(uuidgen)"'","device_id":"iphone"}'
```

**新窗口提示词：**

```
按 docs/mobile-outbox.md + docs/mobile-outbox-plan.md 推进。
本窗口只做【阶段 B】：media.describe（或等价 Desk API）按 photo_id 写
user_note + manual_note:true（幂等，可带 mutation_id）；Vue MemoryDetail 可编辑旁白；
确认 vision backfill 不冲掉旁白。S1 schema 已就绪；阶段 A 可已有可未有（改库内已有图即可验证）。
不要做 ingest 重做、故事 upsert、iOS。隐私不读 data/photos 原图。
```

---

## 阶段 C — 故事（手机可写的后端准备）

**目标：** 确认/补齐「空 links 建故事 + 后挂 photo」的 API 合同；可选 `mutation_id` 幂等 `story.upsert`。

现有 `POST/PUT /api/stories` 已大半可用；本阶段主要是：

- 文档与客户端约定：稳定 `story_id`、禁止把未解析 `local_id` 写入长期 links  
- 若缺：按 `story_id` 的 upsert、回执格式与 ingest 对齐  

**完成标准：** 无图建故事 → 再 PUT links 挂上 A 产生的 `photo_id` → annotations 文件正确。

**实现（已落地）：**

- `POST /api/stories/upsert`（`tools/memory_desk/app.py`）
- 核心：`hub/shared/story_upsert.py`；幂等旁路表 `data/story_upsert_registry.json`
- 空 `links: []` 可建草稿；后挂 `{link_type:photo, link_id:<已落地 photo_id>}`
- `link_type=photo` 须 memory JSON / 索引 / ingest 旁路表已登记，否则 400（禁止未解析 local_id）
- 现有 `POST/PUT /api/stories` 同样走 links 校验；Vue 事件链 `link_type=event` 仍可用

```bash
# 无图先写
curl -sS -X POST "http://127.0.0.1:8765/api/stories/upsert" \
  -H "Content-Type: application/json" \
  -d '{"story_id":"sty_demo001","title":"暑假小记","body":"先写字","links":[],"mutation_id":"'"$(uuidgen)"'"}'

# 后挂已落地 photo_id
curl -sS -X POST "http://127.0.0.1:8765/api/stories/upsert" \
  -H "Content-Type: application/json" \
  -d '{"story_id":"sty_demo001","title":"暑假小记","body":"先写字","links":[{"link_type":"photo","link_id":"EXISTING_PHOTO_ID","sort_order":0}],"mutation_id":"'"$(uuidgen)"'"}'
```

**新窗口提示词：**

```
按 docs/mobile-outbox.md + docs/mobile-outbox-plan.md 推进。
本窗口只做【阶段 C】：故事侧合同落地——空 links 可建故事；后挂已落地 photo_id；
稳定 story_id 幂等 upsert（可用现有 /api/stories，缺则补 mutation_id/回执与 ingest 对齐）；
禁止把未解析 local_id 写入 annotations 长期 links。合同见 mobile-outbox.md §4。
不要做 iOS Outbox UI、不要重做 ingest/describe（除非为联调缺接口）。隐私不读原图。
```

---

## 阶段 E — iOS / iPad 客户端（最后）

**目标：** 现有 `apps/ios` 加**家长模式**（iPhone + iPad 同一工程）。

| Tab/能力 | 说明 |
|----------|------|
| Outbox | 选图拷贝进沙盒；可选写 `user_note`；队列状态 |
| 故事 | 离线草稿；`links` 待回执再补；可先无图 |
| 同步 | Desk 可达时推 ingest → describe → story；展示回执 |
| 问问/谁 | 保持现有消费端 |

**不做：** 删系统相册；公网；手机 AI。

**完成标准：** 真机/模拟器选图 → 写旁白 →（模拟或真）同步 → Mac `photos/` + JSON 旁白可见；无图故事同步后 Vue 能打开。

**实现（已落地）：**

- 设置开关 **家长模式** → Tab「待上传」「故事」
- 本地队列：`Documents/Outbox/` + `manifest.json`（`OutboxStore`）
- 同步：`OutboxSyncService` → ingest → describe → story.upsert；links 仅 `photo_id`
- API：`DeskAPIClient` 扩展 multipart ingest / describe / stories upsert
- 详见 `apps/ios/README.md`

**新窗口提示词：**

```
按 docs/mobile-outbox.md + docs/mobile-outbox-plan.md 推进。
本窗口只做【阶段 E】：iOS/iPad Outbox（选图拷贝、旁白、故事草稿、回家同步队列）。
后端 A/B/C 已完成；合同 docs/mobile-outbox.md。儿童问问/谁 Tab 勿破坏。
不做删系统相册、公网、手机 AI。
```

---

## 依赖与风险（短）

| 风险 | 应对 |
|------|------|
| 未做 S1 就写旁白进野字段 | **禁止**；先 S1 |
| E 先于 A | 手机队列无处可推；**禁止** |
| hash 未做就双路径入库 | A 必须带 exact hash |
| 故事链 `local_id` 进 annotations | 合同禁止；只链落地 `photo_id` |

---

## 建议你怎么开窗口

1. **窗口 1（今天）：** 只 S1  
2. **窗口 2：** 只 A（可与问答打磨并行）  
3. **窗口 3：** B（+ 可选 C）  
4. **窗口 4：** E（平板/手机 UI）

每窗标题建议：`Outbox S1 schema` / `Outbox A ingest` / …
