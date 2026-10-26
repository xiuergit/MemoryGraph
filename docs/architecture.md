# MemoryGraph 架构说明

## 定位

**家庭私有记忆基础设施** — 不是相册，不是云端 AI 产品。

| 组件 | 角色 |
|------|------|
| **iPhone** | 采集两条：系统相册导出到 Mac；家长模式回家上传（Outbox → Desk） |
| **Mac（Python）** | 记忆中枢：本地 AI 分析、索引、问答 API |
| **Vue / iOS 消费端** | 问 / 筛 / 看：连 Desk；iOS 不跑大模型 |
| **JSON** | 记忆原子（唯一数据源）；协议按形态分：`photo.v1` / `video.v1` / `audio.v1`（见 [media-memory.md](media-memory.md)） |
| **SQLite** | 检索索引（可由 JSON 重建，非真源）；投影含 `media_type`（规划） |

## 主流程（Mac 导出路径）

```
data/photos/*.{jpg,heic,...}   （同目录可有 .mov/.mp4；视频入库见 media-memory）
        │
        ▼
tools/photo2json/main.py       （视频/音频 pipeline 另议，协议已定）
        │
        ├── hub/shared/utils.py        EXIF、尺寸、GPS
        ├── hub/shared/geocode.py      逆地理 → location（仅发坐标，不上传照片）
        ├── hub/shared/analyzer.py     图像 AI 入口 analyze_image()
        │      ├── vision.py           Ollama 视觉（scene/tags/objects…）
        │      ├── face.py             InsightFace 人脸识别
        │      └── outfit.py           CLIP 衣着兜底
        └── location_cluster.py        同日相近 GPS 归一 location
        │
        ▼
data/memory/{id}.json           ← 唯一数据源（photo_id / video_id / audio_id）
        │
        ▼
tools/memory_index/main.py sync
        │
        ▼
data/memorygraph.db             ← 可删重建
        │
        ▼
tools/memory_events/main.py sync   ← 可选；出门/家事件聚合
        │
        ▼
tools/memory_ask / Desk API
        │
        ├── web/ Vue Inspector
        └── apps/ios/ 问问 / 谁；家长模式回家上传
```

**地址纠错**（有 GPS）：改 `data/.geocode_cache.json`（Vue 或 `tools/location_mapping`）→ `--regeocode-locations --no-normalize-after` → `sync`。家附近已拆 POI 时勿再跑 `--normalize-locations`。

**事件意义 / 故事**：真源 `data/memory_annotations.json`；Desk/Vue 保存或 `memory_events sync` 会读写该文件，SQLite 仅作索引。

**增量补全**（不重新扫原图目录）：`photo2json --backfill vision|faces|all`（见 `hub/shared/backfill.py`）；人脸库变更后用 `--backfill faces --refill`。

### 路径 B：回家上传 ✅ 已做

家长在 iOS 打开家长模式，选图、写旁白、写故事，回家连上局域网 Desk 后同步。系统相册导出到 Mac、再跑 `photo2json` 仍然可用。

- 原图进 `data/photos/YYYY/MM/ob_<8>_<stem>.ext`（`POST /api/media/ingest`）
- 旁白进 memory JSON 的 `user_note`（`POST /api/media/describe`）
- 故事进 `memory_annotations.json`（`POST /api/stories/upsert`）
- `hub/mac_server` 的 `POST /import` 骨架不走这条路

目录、防撞名和回执见 [mobile-outbox.md](mobile-outbox.md)。

## 存储布局

```
data/
├── photos/                  # 原媒体（图/视频等；gitignore）
├── memory/                  # 一条媒体一 JSON（id = photo_id | video_id | audio_id）
├── faces/                   # 人脸参考照 + registry.json
├── memorygraph.db           # SQLite 索引（sync 重建）
├── memory_annotations.json  # 事件意义 / 故事真源（跨机必拷）
├── .geocode_cache.json      # 高德逆地理缓存（地址纠错真源，v6 key）
├── .weather_cache.json      # Open-Meteo 日天气缓存（日+粗格点）
├── location_canonical.json  # 可选；合并别名用（家附近「拆开 POI」时通常留空）
├── .trash/                  # Desk 删除回收（photos/ + memory/）
└── cache/outfit/            # CLIP 当日穿搭向量缓存
```

id 规则见 [media-memory.md](media-memory.md)：照片为路径 stem；视频 stem+`_v`；音频 stem+`_a`。Live Photo = photo + video + `related_ids`。

## 隐私边界

| 规则 | 实现 |
|------|------|
| 照片不上传公有云 | 视觉/人脸均在 Mac 本地（Ollama、InsightFace、CLIP） |
| 逆地理 | 仅向高德发送 GPS 坐标，不上传图片；结果缓存于本地 |
| 手机 → 家 | 仅局域网 HTTP（Desk，默认 8766）；**不做**公网暴露 |
| Mac 数据不外泄 | 不做公网端口转发 |
| 可导出 | JSON 纯文本 + 原图文件夹，随时拷贝 |

## 模块职责

| 模块 | 职责 |
|------|------|
| `schemas/` | 协议定义（photo / video / audio.v1） |
| `hub/shared/schema.py` | Python 侧照片 Schema 实现（video/audio 随 pipeline） |
| `hub/shared/analyzer.py` | **唯一 AI 入口** `analyze_image()` |
| `hub/shared/vision.py` | Ollama 视觉模型 |
| `hub/shared/face.py` | InsightFace 人脸库匹配 |
| `hub/shared/outfit.py` | CLIP 衣着兜底 |
| `hub/shared/geocode.py` | 高德逆地理、`.geocode_cache.json` CRUD |
| `hub/shared/weather.py` | 日天气（Open-Meteo）、`.weather_cache.json`；`photo2json --backfill weather` |
| `hub/shared/location_cluster.py` | 同日 GPS 聚类、regeocode、`manual_location` 清理 |
| `hub/shared/location_canonical.py` | 缓存别名合并（可选）；按地名删缓存 |
| `hub/shared/backfill.py` | 增量补全 vision / faces |
| `hub/shared/index_db.py` | SQLite 同步与查询 |
| `hub/shared/query.py` | 问答事实收集 |
| `hub/shared/agent.py` | 问答 Agent（规则路由 + Ollama 润色 + 模板兜底），意图见 [agent-intents.md](agent-intents.md) |
| `hub/shared/utils.py` | EXIF、尺寸、格式过滤 |
| `tools/photo2json/` | Mac 批量处理与 backfill |
| `tools/face_enroll/` | 人脸库注册 |
| `tools/memory_index/` | 索引 sync / stats / search |
| `tools/memory_events/` | Outing 事件聚合 sync / stats / list；annotations 导入导出 |
| `tools/memory_ask/` | CLI 问答 |
| `tools/memory_desk/` | FastAPI：搜文件、问答 API、memory/geocode 缓存 API |
| `web/` | Vue Inspector：列表（含批量标人物）、问答、事件、详情、批量改地址、地址缓存、人脸库、维护工具、验证、健康报告 |
| `tools/location_mapping/` | 地址缓存 CLI（migrate / delete-by-location / delete-incomplete） |
| `tools/memory_stats/` | 数据健康报告 |
| `tools/find/` | 按文件名搜索 CLI |
| `hub/shared/photo_delete.py` | 删除照片（`.trash` + 清索引） |
| `hub/mac_server/` | 早期 `POST /import` 骨架；回家上传走 Desk ingest，不推进这里 |
| `apps/ios/` | 问问 / 谁；家长模式待上传、故事、回家同步（连 Desk） |

## 阶段规划

| 阶段 | 目标 | 状态 |
|------|------|------|
| **0** | Mac 批量 Photo→JSON | ✅ 完成 |
| **1** | 本地视觉 + 人脸识别 | ✅ Ollama + InsightFace + CLIP |
| **2** | 结构化问答打磨 | 🚧 **当前**（复合口语 / 轻量追问 / 叙事润色，见 [agent-intents.md](agent-intents.md)） |
| **3** | 记忆库索引与检索 | ✅ SQLite + CLI + Desk + Vue + iOS 消费端；筛选结果时间轴 🔜 |
| **4** | Event 聚合 v1 | ✅ `memory_events sync` + Vue「事件」Tab + 相关问答意图 |
| — | iOS 回家上传 | ✅ 家长模式 Outbox（原图 / 旁白 / 故事），见 [mobile-outbox.md](mobile-outbox.md) |
| **5+** | 向量 RAG、筛选时间轴、记忆智能体层 C | 🔜；**不做**全库相册式时间轴、公网闲聊 Bot |
| **并行** | video/audio JSON pipeline | 协议 ✅；实现可与阶段 2 并行，见 [media-memory.md](media-memory.md) |

> 原「阶段 2 = iOS 上传」的编号已改用于问答打磨。回家上传后来按 Outbox 做完，不占阶段 2。阶段 3/4 核心功能已完成。

### 问答演进（有据记忆智能体）

| 层 | 做什么 | 不做什么 |
|----|--------|----------|
| A/B（当前） | 一句多问拆解、`follow_ups` 芯片、`context` 追问（依据/开心/见人）、叙事类 LLM 锁 facts | 完整会话库、自由闲聊 |
| C（远期） | 人物画像（常去地/同框/故事摘要）、短会话、查库工具化；旁白/故事抬升「开心吗」 | 模型假装认识娃、无证据编造 |

Mac 问答入口：`hub/shared/agent.py` → Desk `POST /api/ask`（可选 `context`）→ Vue / iOS。

### 证据合同（Evidence）

`POST /api/ask` 除 `facts`（意图相关自由结构）外，返回统一 **`evidence`**：

```json
{
  "media": [{"id", "media_type", "timestamp", "location", "scene", "source_path"}],
  "events": [{"id", "day", "location", "photo_count"}],
  "stories": [{"id", "title"}],
  "counts": {"media", "events", "stories", "by_media_type": {"photo", "video", "audio"}}
}
```

追溯链：`answer` → `evidence.*.id` → `data/memory/{id}.json` / 原片 / 事件详情。LLM 只组句，不得创造不在 facts/evidence 里的事实。实现：`hub/shared/evidence.py`。

### DaySlice ≠ Outing

| 概念 | 含义 | API / 函数 |
|------|------|------------|
| **DaySlice** | 日历日上的全部记忆（含单张日、视频、音频、`user_note`、相关故事） | `GET /api/day-slice?day=YYYY-MM-DD` · `query.get_day_slice()` |
| **Outing / Event** | 同日 GPS/地名聚类的出门/回家事件（通常 ≥2 张；`event_id` 随成员集变化） | `GET /api/events?day=` · `memory_events sync` |

**时间旅行应建在 DaySlice 上**，不要把 outing 列表当成「这一天的全部记忆」。故事/overlay 长期挂靠用 **已落地 photo_id**（`anchor_photo_ids` / `story.links`）；Desk 若传入 `link_type=event` 会展开为 photo anchors，手机 Outbox **禁止** event link。

## 浏览与时间轴（产品边界）

| 类型 | 做不做 | 说明 |
|------|--------|------|
| **全库相册式时间轴** | ❌ 不做 | 按年/月/日滚全部缩略图 ≈ 重做 Photos App，与「记忆系统」定位冲突；日常翻图用 iPhone 相册 |
| **日历日切片 DaySlice** | ✅ 查询底座 | 按日聚合媒体+旁白+事件+故事；UI 可后做 |
| **筛选结果时间轴** | 🔜 远期可选 | 先检索（人物/物体/scene/tags/地点）→ 命中结果按时间分组，看「第一次」「变化趋势」 |
| **当前替代** | ✅ 已有 | 列表 Tab（分页+人物/关键词/年份筛选）、事件 Tab（出门粒度）、问答（证据缩略图）、CLI `memory_index timeline` |

若实现筛选时间轴，建议轻量：例如在列表 Tab 增加「时间分组」视图，而非独立相册模块。

## 记忆智能体层 C（远期，未实现）

在 A/B（复合拆解 + last_turn 追问）稳定后，再考虑：

| 能力 | 真源 | 说明 |
|------|------|------|
| 人物画像聚合 | SQLite + annotations | 常去地、常同框、年龄阶段、故事摘要；可导出审计 |
| 短会话 | 内存 / 可选 annotations | 一次「聊聊国庆」；结束可丢；不做公网多用户 session |
| 工具化查库 | `query.py` 函数作 tool | LLM 只拆问与组句；禁止无 facts 编童年 |
| 旁白/故事抬升 | Outbox `user_note` + stories | 「开心吗 / 那次怎样」优先用人话，其次 emotion 标注 |

**不做**：无限闲聊 Bot、手机跑大模型、公网 Agent 框架。

日常操作详见 [operations.md](operations.md)。

## 技术选型

- **Mac 分析**：Python + Ollama（Qwen2.5-VL 等）+ InsightFace + open-clip
- **Mac 问答**：Ollama 文本模型（`OLLAMA_CHAT_MODEL`）+ 规则路由（阶段 2 打磨中）
- **Mac 服务**：FastAPI + uvicorn（Desk）
- **索引**：SQLite（`memorygraph.db`，JSON 为真源）
- **iOS**：SwiftUI。儿童问问 / 谁；家长模式回家上传（连 Desk，手机不跑大模型）
