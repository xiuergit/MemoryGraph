# Memory JSON Schemas

MemoryGraph 的记忆原子协议。按**媒体形态**分文件定义，**不做**统一的 `media.v1`，也**不**为 Live Photo 单开第三套协议。

| 协议 | 文件 | 状态 |
|------|------|------|
| 照片 | [`photo.v1.json`](photo.v1.json) | ✅ 生产中（当前写入 `1.2`；`1.3` 增加可选 `related_ids`） |
| 视频 | [`video.v1.json`](video.v1.json) | ✅ 协议已定；pipeline 未实现 |
| 音频 | [`audio.v1.json`](audio.v1.json) | ✅ 协议已定；pipeline 未实现 |

设计说明见 [docs/media-memory.md](../docs/media-memory.md)。

- **Python（照片）**：`hub/shared/schema.py`（须与 `photo.v1.json` 一致；video/audio 实现随 pipeline 补齐）
- **写入**：Mac 批处理；iOS 消费端**不写** JSON
- **落盘**：一律 `data/memory/{id}.json`，`id` 在 photo / video / audio 间**全库唯一**
- **版本**：各协议独立编号；大改新建 `*.v2.json`，旧版保留可读

## 总原则

1. **一条媒体一条 JSON**（一张照片 / 一段视频 / 一段音频）
2. **核心语义字段同构**：`people`、`scene`、`location*`、`objects`、`actions`、`emotion`、`tags`、`weather`、`manual_*` 含义一致，便于索引与问答共用逻辑
3. **形态差异放在 `source` / `quality`（及音频 `transcript`）**
4. **Live Photo** = 一条 `photo` + 一条 `video`，用双方 `related_ids`（`relation: live_photo`）互链
5. **SQLite 可重建**：索引层用 `media_type`（`photo` \| `video` \| `audio`）区分；不要求磁盘上合并成单一 schema

## 识别类型

读 `data/memory/*.json` 时按主键区分（恰好一种）：

| 主键 | media_type |
|------|------------|
| `photo_id` | `photo` |
| `video_id` | `video` |
| `audio_id` | `audio` |

## ID 规则

| 类型 | 字段 | 建议生成规则 |
|------|------|----------------|
| 照片 | `photo_id` | 相对 `data/photos/` 路径 stem（现有 `get_photo_id`） |
| 视频 | `video_id` | 同上规则得到 stem 后加后缀 **`_v`**（避免与 Live Photo 静图同 stem 撞车） |
| 音频 | `audio_id` | 同上规则得到 stem 后加后缀 **`_a`** |

示例：`IMG_8079.JPEG` + `IMG_8079.MOV` →  
`photo_id=…_IMG_8079`，`video_id=…_IMG_8079_v`，并互写 `related_ids`。

## photo.v1

当前生产写入 **1.2**（可选 `weather`）。**1.3** 起可选 `related_ids`（Live Photo 等关联）；未写该字段的 `1.0`–`1.2` 仍可读。

示例：[`examples/sample.json`](examples/sample.json)

### 字段分工（照片）

| 字段 | 导出/批处理（Mac） | 说明 |
|------|-------------------|------|
| `schema_version`, `photo_id`, `device_id` | ✅ | |
| `timestamp`, `source.*` | ✅（EXIF） | |
| `location_coords` | ✅（EXIF GPS） | |
| `location` | ✅（逆地理 + 同日归一） | |
| `weather` | ✅（可选；需 timestamp + GPS） | |
| `quality.face_detected` | 可选 | |
| `people`, `scene`, `objects`, `actions`, `emotion`, `tags` | ✅（本地模型） | |
| `related_ids` | 可选（1.3+） | Live Photo 等 |
| `manual_edit` / 分项 `manual_*` | ✅（手改时设 true） | |

### location / weather

- **`location_coords`**：原始 GPS（`"纬度,经度"`），写入后不被文本覆盖
- **`location`**：可读地名（逆地理 + 同日聚类）
- **weather**：日气温/降水 + 拍摄时刻小时天气码；缓存 `data/.weather_cache.json`；补全见 `photo2json --backfill weather`

## video.v1（1.0）

与 photo 同构的语义字段；`source` 必含 `duration_s`；可选 `fps` / `container`。  
语义可先空，后续关键帧分析 / backfill 再填。

示例：[`examples/sample_video.json`](examples/sample_video.json)

## audio.v1（1.0）

与 photo/video 同构的语义字段；`source` 必含 `duration_s`（无宽高）；`quality` 为 `silent` / `speech_detected`；可选 `transcript`、`manual_transcript`。  
pipeline 未实现前仅作协议占位。

示例：[`examples/sample_audio.json`](examples/sample_audio.json)

## 索引层（约定，实现随 pipeline）

JSON 为真源。Sync 到 SQLite 时建议：

- 记忆主表带 **`media_type`**：`photo` \| `video` \| `audio`
- 主键用各 JSON 的 `*_id`（全库唯一，可与现 `photo_id` 列兼容扩展为 `memory_id`）
- `related_ids` 可投影为关联表或 JSON 列；库可随时丢弃重建
