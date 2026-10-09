# 手机 Outbox：描述 · 故事 · 回家上传（设计合同）

> 状态：**阶段 A–C + E（iOS Outbox）已落地**；儿童问问/谁保持；家长模式待上传/故事/回家同步。  
> **实施清单：** [`mobile-outbox-plan.md`](mobile-outbox-plan.md)  
> 相关：[`architecture.md`](architecture.md)、[`operations.md`](operations.md)、[`media-memory.md`](media-memory.md)、[`schemas/README.md`](../schemas/README.md)、[`apps/ios/README.md`](../apps/ios/README.md)

---

## 0. 下一阶段要做什么（合同范围）

手机端（实现后）要能：

| # | 能力 | 回家同步时发生什么 |
|---|------|-------------------|
| 1 | **给照片写描述（旁白）** | 字进 `memory/{photo_id}.json` 的 `user_note` |
| 2 | **写故事**（可无图先写，后配图） | 进 `memory_annotations.json` → `stories` |
| 3 | **回家上传** | **原图像素文件**写入 Mac `data/photos/`（再异步分析出 JSON） |

**是的：回家上传包含把原图落到原图文件夹**，不是只传文字。文字（描述/故事）与原图走同一趟局域网同步，但落盘到不同真源。

不在本阶段：事件 overlay 精修 UI、公网上传、删系统相册、手机跑 AI。

---

## 1. 同步时到底传什么、落到哪

```
手机 Outbox                         Mac（唯一记忆库）
─────────────                       ────────────────
① 原图拷贝（HEIC/JPEG…）    ──►    data/photos/<约定目录>/…
② media.describe（旁白等）  ──►    data/memory/{photo_id}.json → user_note
③ story.upsert（故事）      ──►    data/memory_annotations.json → stories
                                  （异步）analyze → 补 scene/people/…
                                  ← 回执 local_id → photo_id
```

| 载荷 | 必传？ | Mac 落点 |
|------|--------|----------|
| 原图字节 | 有图入库时 **是** | `data/photos/…` |
| `user_note` / tags 等 | 写了才传 | 对应 memory JSON |
| 故事 title/body/links | 写了才传 | annotations |
| AI 字段（scene 等） | **不传** | Mac 本地算 |

系统相册里的原图：**不删**。App 沙盒拷贝在 Mac 签收后可删大图腾空间。

---

## 2. 三层写作（合同：不要混字段）

| 用户说法 | 真源 | 稳定挂靠 |
|----------|------|----------|
| 这张图的描述 | `data/memory/*.json` → **`user_note`** | `photo_id` |
| 跨天 / 可先写的故事 | `memory_annotations.json` → **stories** | `story_id`；配图用 `links`（**仅 photo**，可先 `[]`）；**禁止**裸 `event`（手机 Outbox）；Desk 若传 event 会展开为 photo anchors |
| 某次出门备注 | 同文件 → overlays | **`anchor_photo_ids`**（稳定）；`event_id` 仅缓存，聚类后 rematch |

旁白 ≠ 故事：故事正文**不要**复制进每张图的 `user_note`。

---

## 3. 合同怎么改：媒体 JSON（描述）

### 3.1 现状缺口

`photo.v1` / `video.v1` / `audio.v1` 无旁白字段；`additionalProperties: false`，不能偷加键。

### 3.2 正式改法（实现描述能力前必须改 schema）

| 文件 | 版本枚举增加 | 新增可选字段 |
|------|--------------|--------------|
| `schemas/photo.v1.json` | `"1.4"` | 见下 |
| `schemas/video.v1.json` | `"1.1"` | 同构 |
| `schemas/audio.v1.json` | `"1.1"` | 同构 |

```json
"user_note": {
  "type": "string",
  "description": "用户旁白/配文；非 AI 的 scene。无则 \"\" 或省略"
},
"manual_note": {
  "type": "boolean",
  "description": "已手写旁白；禁止自动 backfill 覆盖 user_note"
}
```

配套（实现时）：`hub/shared/schema.py`、`refresh_manual_edit_flag` 计入 `manual_note`、index sync 投影进检索、Desk/Vue/iOS 编辑入口。

**禁止：** 用 `scene` / `tags` 长期冒充旁白。

---

## 4. 合同怎么改：故事（基本不改形状）

### 4.1 已够用的

- `links: []` 合法 → **无图先写**
- 后配图 = `update` links：`{ "link_type": "photo", "link_id": "<photo_id>", "sort_order": n }`
- Desk 已有 stories CRUD；手机只是新客户端 + 离线 Mutation

### 4.2 手机写入规则（合同）

1. 客户端生成稳定 `story_id`（如 `sty_` + uuid），`story.upsert` **幂等**
2. 长期 annotations 里的 `link_id` **只允许已落地的 `photo_id`**
3. 图还在 Outbox、只有 `local_id` 时：pending 映射留在手机 / Mutation 载荷，**回执后再写 links**
4. **禁止**手机传 `link_type=event`（`event_id` 随聚类成员变化）；Desk 若收到 event 会展开为成员 photo anchors 再落盘

### 4.3 可选（非阻塞）

annotations `schema_version: "2"`：`device_id`、`status: draft|linked`（也可用 `links.length===0` 推断草稿）。

---

## 5. 原图落盘与目录约定（防导出打架）

### 5.1 现状

- 根目录：`data/photos/`
- 已有习惯：按**年**分子目录，也有 `2026/5-8/` 这类更细目录（见 `operations.md`）
- `photo_id` = 相对 `photos/` 的路径 stem 拼接  
  - `2026/IMG_1.HEIC` → `2026_IMG_1`  
  - `2026/09/IMG_1.HEIC` → `2026_09_IMG_1`  
  - **根必须始终是 `data/photos/`**，勿用子目录当 root（否则同图两套 id）

同名 `IMG_1234.HEIC` 若落在**同一目录**，后写覆盖或冲突；若在**不同子目录**，是两条记忆（id 不同）。导出与手机若都丢进同一目录且文件名相同 → **易打架**。

### 5.2 决策：向前统一「年/月」+ 通道前缀

**新进库原图（导出与手机）建议目录：**

```
data/photos/
  YYYY/
    MM/                    # 日历月，两位，如 09
      IMG_3832.HEIC        # 导出 / 手工放入（保持相机文件名）
      ob_<short>_<stem>.HEIC   # 手机 Outbox 入库（见下）
```

| 来源 | 路径示例 | 说明 |
|------|----------|------|
| 导出到 Mac | `photos/2026/09/IMG_3832.HEIC` | 按拍摄日（无 EXIF 则用导入日）归月 |
| 手机回家上传 | `photos/2026/09/ob_a1b2c3d4_IMG_3832.HEIC` | **`ob_` + local_id 前 8 位 + 原 stem**，避免与导出同名覆盖 |
| 历史数据 | `photos/2025/…`、`photos/2026/5-8/…` | **不强制迁移**；新约定只约束新写入 |

年月取自：优先 EXIF/拍摄日；否则同步日。时区默认 `Asia/Shanghai`（与 weather 一致）。

### 5.3 为什么不用「纯按月、文件名照旧」？

可以，但导出与手机常会碰到**同一张** `IMG_xxxx`：

- 只靠目录按月：仍可能同月同名覆盖  
- 只靠 hash 去重：要先读完整文件，实现更重  

**`ob_` 前缀 + hash 去重** 双保险：

1. 路径/文件名几乎不撞导出  
2. 若字节相同（同图两条路径进来）→ ingest 判 `duplicate`，复用已有 `photo_id`，旁白/故事挂到已有 id  

### 5.4 要不要「一个月一个文件夹」？

**要（作为新约定）。** 好处：

- `photo2json --input data/photos/2026/09` 好扫  
- `photo_id` 带 `YYYY_MM_`，全年同名 IMG 不撞  
- 手机与导出都按拍摄月归位，心智简单  

**不要**再拆「每天一个文件夹」（过碎）。  
**不要**手机单独永久目录如 `photos/outbox_only/` 与年月脱节（难按时间批处理）；`ob_` 前缀已区分通道。

### 5.5 与「只传字、不传图」

若故事无图、或只给**库里已有** `photo_id` 写旁白：可只推 Mutation，**不传原图**。  
新图进记忆库：**必须传原图** → `data/photos/YYYY/MM/ob_…`。

---

## 6. Outbox / Mutation（投递合同）

### 6.1 手机一条队列项

```
Outbox/{local_id}/
  media.heic       # 有图时
  sidecar.json
  thumb.jpg        # 可选
```

sidecar 要点：`local_id`, `device_id`, `captured_at`, `note`→将来的 `user_note`, `status`, `photo_id`(回执后), `content_hash`

### 6.2 Mutation 类型（本阶段用到的）

| type | 作用 |
|------|------|
| `media.ingest` | 上传原图 → `photos/YYYY/MM/ob_…`；回执 `photo_id`；排队 analyze |
| `media.describe` | 写/改 `user_note`（+ 可选 tags/人地 hint）；幂等 |
| `story.upsert` | 建/改故事；`links` 仅含已解析 `photo_id`，或空 |

每条：`mutation_id`（UUID，幂等键）、`device_id`、`created_at`。

顺序建议：先 `media.ingest`（若有图）→ `media.describe` → `story.upsert`（links 已能解析时）。

**时序（已实现）：** ingest 落原图后立刻写 **memory stub JSON**（空 scene/people），故 describe **不必等** Ollama；后台 analyze 对 stub **merge** 写入 AI 字段，保留已有 `user_note` / `manual_*`。

### 6.3 回执

`accepted` | `duplicate` | `conflict` + `local_id`→`photo_id` + 落盘相对路径。

---

## 7. 目标架构（简图）

```
iPhone（家长模式）
  选图拷贝 → 写描述 / 写故事（可无图）
  待同步队列
        │ 回家 · 局域网 Desk
        ▼
Mac Ingest
  原图 → data/photos/YYYY/MM/ob_…
  描述 → memory JSON user_note
  故事 → annotations stories
  异步 AI / index / events
```

Vue 继续重管理；与 iOS **共用** ingest + mutation API（实现时）。

---

## 8. 实施顺序（无排期）

| 阶段 | 内容 | 改正式 schema？ |
|------|------|-----------------|
| **D0** | 本文（合同） | 否 |
| **S1** | photo/video/audio 加 `user_note` + `manual_note`；README / schema.py | **是** |
| **A** | Desk：`media.ingest`（按 §5 落盘 + hash 去重 + 回执） | 否 |
| **B** | `media.describe` + Vue/详情可写旁白 | 否（字段已在 S1） |
| **C** | `story.upsert`；iOS 写故事（含空 links） | 否 |
| **E** | iOS Outbox UI、队列、连通回家同步 | 否 |

导出路径保留；新导出也建议归入 `YYYY/MM/`（可手工，后可脚本）。

---

## 9. 决策记录

| 决策 | 选择 |
|------|------|
| 回家上传含不含原图 | **含**；新图必须进 `data/photos/` |
| 引用 vs 拷贝 | 手机 **拷贝**进沙盒再传 |
| 删系统相册 | **否** |
| 旁白字段 | `user_note` + `manual_note`（photo 1.4 等） |
| 无图故事 | 现有 `links: []`，不新开协议 |
| 目录 | 新图 **`photos/YYYY/MM/`**；手机文件名 **`ob_<8>_<stem>`** |
| 与导出防打架 | 分前缀 + content hash 去重 |
| 真源 | 仍仅 Mac |

---

## 10. 开放问题

1. `user_note` 是否进 `keyword_search`？（建议：是）  
2. hash 是否写入 JSON（可选 `ingest.content_hash`）还是仅 ingest 旁路表？  
3. Live Photo 是否强制成对上传 JPEG+MOV？  
4. 历史 `photos/2026/5-8/` 是否提供「迁入 YYYY/MM」可选工具？（非必须）  
5. 旁白字数软限制？

---

## 11. 一句话

> **回家同步 = 原图进 `photos/YYYY/MM/`（手机用 `ob_` 前缀）+ 描述进 `user_note` + 故事进 annotations；先改旁白 schema，故事形状已够；用目录约定和 hash 避免与导出打架。**
