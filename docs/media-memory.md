# 多媒体记忆协议（photo / video / audio）

> 决策：按形态分协议，索引用 `media_type` 统一；不做 `media.v1` 整库合并，不为 Live Photo 单开协议。

## 结论

| 层级 | 做法 |
|------|------|
| **JSON 真源** | `photo.v1` + `video.v1` + `audio.v1` 三套协议，各一份文件一份记忆 |
| **Live Photo** | 静图走 photo、短视频走 video，双方 `related_ids`（`relation: live_photo`）互链 |
| **SQLite** | 可随时由 JSON 重建；用 **`media_type`**（`photo` \| `video` \| `audio`）区分形态 |
| **统一 media schema** | **不做**为必经迁移；读路径/索引按「记忆条目」处理即可 |

正式字段定义：

- [`schemas/photo.v1.json`](../schemas/photo.v1.json)
- [`schemas/video.v1.json`](../schemas/video.v1.json)
- [`schemas/audio.v1.json`](../schemas/audio.v1.json)
- 概要：[schemas/README.md](../schemas/README.md)

## 为何这样拆

- 照片已有约 1.9 万条生产 JSON，不宜为视频强行改写成单一 `media` 文件格式
- 视频/音频的 `source`、`quality`（及音频转写）与静图不同，分协议更干净（`additionalProperties: false`）
- 核心语义字段**同构**，问答与事件只需在索引层认 `media_type`，不必维护三套业务逻辑
- 库本来就可重建 → 类型字段放在 DB 投影上最合适

## ID 与落盘

所有记忆 JSON 落在 `data/memory/{id}.json`，**id 全库唯一**（跨 photo/video/audio）。

| media_type | JSON 主键 | 建议 id 规则 |
|------------|-----------|----------------|
| `photo` | `photo_id` | 相对 `data/photos/` 的路径 stem（现有逻辑） |
| `video` | `video_id` | 同上 stem + **`_v`** |
| `audio` | `audio_id` | 同上 stem + **`_a`** |

读文件时看存在哪个 `*_id` 即知类型（勿依赖扩展名 alone）。

原文件仍可与照片一起放在 `data/photos/`（当前库内已有大量 `.mov` / `.mp4`）；音频根目录若日后拆分，只影响 `source.path`，不影响 id 规则精神。

## Live Photo

```
IMG_8079.JPEG  →  photo  JSON  (photo_id = …_IMG_8079)
IMG_8079.MOV   →  video  JSON  (video_id = …_IMG_8079_v)
                 ↕ related_ids relation=live_photo
```

- **没有** `livephoto.v1`
- 删除/手改按两条记忆处理；UI 可将 `live_photo` 对展示为一条
- 事件聚类可同时挂两条，或按产品需要去重展示

## 与流水线的关系

| 能力 | 状态 |
|------|------|
| photo → JSON（`photo2json`） | ✅ 已有 |
| video → JSON | ✅ `python tools/video2json/main.py`（OpenCV 元数据 + 关键帧 → `analyze_image`） |
| 索引 `media_type` | ✅ sync 写入 `photo` / `video` / `audio`；Vue 列表可筛「视频」 |
| Desk 预览 | ✅ `/api/preview` 对视频走关键帧封面 |
| audio → JSON | 🔜 协议占位；工具未做 |
| 索引 `media_type` | 🔜 随 video/audio sync 扩展 |
| 问答 / 事件纳入视频 | 🔜 有 JSON + 索引后即可并行推进 |

视频建议分层变厚（均可 backfill）：元数据与时长 → 封面/关键帧语义 →（可选）多帧/ASR。音频同理：元数据 → 可选 `transcript`。

## 明确不做

- 为 Live Photo 单独第三套记忆协议
- 必须把全部 photo JSON 迁成统一 `media.v1` 才算「支持视频」
- 全库视频/音频相册墙（产品仍是记忆系统，不是相册）

改协议字段时：只改对应 `schemas/*.json`，并同步 [schemas/README.md](../schemas/README.md) 与（照片）`hub/shared/schema.py`。
