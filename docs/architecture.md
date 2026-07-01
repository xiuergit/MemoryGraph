# MemoryGraph 架构说明

## 定位

**家庭私有记忆基础设施** — 不是相册，不是云端 AI 产品。

| 组件 | 角色 |
|------|------|
| **iPhone / 导出** | 采集端：相册导出或（可选）App 同步到 Mac |
| **Mac（Python）** | 记忆中枢：本地 AI 分析、索引、问答 |
| **JSON** | 记忆原子（唯一数据源），协议见 `schemas/photo.v1.json` |
| **SQLite** | 检索索引（可由 JSON 重建，非真源） |

## 主流程（Mac 导出路径，当前常用）

```
data/photos/*.{jpg,heic,...}
        │
        ▼
tools/photo2json/main.py
        │
        ├── hub/shared/utils.py        EXIF、尺寸、GPS
        ├── hub/shared/geocode.py      逆地理 → location（仅发坐标，不上传照片）
        ├── hub/shared/analyzer.py     唯一 AI 入口 analyze_image()
        │      ├── vision.py           Ollama 视觉（scene/tags/objects…）
        │      ├── face.py             InsightFace 人脸识别
        │      └── outfit.py           CLIP 衣着兜底
        └── location_cluster.py        同日相近 GPS 归一 location
        │
        ▼
data/memory/{photo_id}.json     ← 唯一数据源
        │
        ▼
tools/memory_index/main.py sync
        │
        ▼
data/memorygraph.db             ← 可删重建
        │
        ▼
tools/memory_ask/main.py      CLI 自然语言问答
```

**增量补全**（不重新扫原图目录）：`photo2json --backfill vision|faces|all`（见 `hub/shared/backfill.py`）。

### 路径 B：iPhone App 上传（可选，骨架已有）

```
相册选图 → Swift EXIF + JSON 骨架
    │
    ▼
POST /import（局域网，默认 8765）
    │
    ▼
hub/mac_server/server.py
    ├── 原图 → data/photos/
    └── JSON → data/memory/（Mac 可补全 AI 字段）
```

两条路径最终落到**同一目录、同一 Schema**。当前主路径为 **Mac 批量处理已导出原图**，iOS App 待开发。

## 存储布局

```
data/
├── photos/                  # 原图
├── memory/                  # 一图一 JSON，与 photo_id 一一对应
├── faces/                   # 人脸参考照 + registry.json
├── memorygraph.db           # SQLite 索引（sync 重建）
├── .geocode_cache.json      # 高德逆地理缓存
└── cache/outfit/            # CLIP 当日穿搭向量缓存
```

`photo_id` = 文件名（不含扩展名），如 `2025_IMG_3830`。

## 隐私边界

| 规则 | 实现 |
|------|------|
| 照片不上传公有云 | 视觉/人脸均在 Mac 本地（Ollama、InsightFace、CLIP） |
| 逆地理 | 仅向高德发送 GPS 坐标，不上传图片；结果缓存于本地 |
| 手机 → 家 | 仅局域网 HTTP（默认端口 8765） |
| Mac 数据不外泄 | 不做公网端口转发 |
| 可导出 | JSON 纯文本 + 原图文件夹，随时拷贝 |

## 模块职责

| 模块 | 职责 |
|------|------|
| `schemas/` | 协议定义 |
| `hub/shared/schema.py` | Python 侧 Schema 实现 |
| `hub/shared/analyzer.py` | **唯一 AI 入口** `analyze_image()` |
| `hub/shared/vision.py` | Ollama 视觉模型 |
| `hub/shared/face.py` | InsightFace 人脸库匹配 |
| `hub/shared/outfit.py` | CLIP 衣着兜底 |
| `hub/shared/geocode.py` | 高德逆地理编码 |
| `hub/shared/location_cluster.py` | 同日 GPS 聚类、统一 location |
| `hub/shared/backfill.py` | 增量补全 vision / faces |
| `hub/shared/index_db.py` | SQLite 同步与查询 |
| `hub/shared/query.py` | 问答事实收集 |
| `hub/shared/agent.py` | 问答 Agent（Ollama 润色 + 模板兜底） |
| `hub/shared/utils.py` | EXIF、尺寸、格式过滤 |
| `tools/photo2json/` | Mac 批量处理与 backfill |
| `tools/face_enroll/` | 人脸库注册 |
| `tools/memory_index/` | 索引 sync / stats / search |
| `tools/memory_ask/` | CLI 问答 |
| `hub/mac_server/` | iOS 上传接收（可选） |
| `apps/ios/` | iPhone 采集 App（待开发） |

## 阶段规划

| 阶段 | 目标 | 状态 |
|------|------|------|
| **0** | Mac 批量 Photo→JSON | ✅ 完成 |
| **1** | 本地视觉 + 人脸识别 | ✅ Ollama + InsightFace + CLIP |
| **2** | iOS 上传 / 日常同步 | ⏸ 骨架有；当前用「导出到 Mac」 |
| **3** | 记忆库索引与检索 | ⚠️ SQLite + CLI 搜索/问答已有；Web 时间线未做 |
| **4+** | Event 聚合、语音/Web | 🔜 Event 未做；CLI Agent 已有基础版 |

日常操作详见 [operations.md](operations.md)。

## 技术选型

- **Mac 分析**：Python + Ollama（Qwen2.5-VL 等）+ InsightFace + open-clip
- **Mac 问答**：Ollama 文本模型（`OLLAMA_CHAT_MODEL`）+ 规则路由
- **Mac 服务**：FastAPI + uvicorn
- **索引**：SQLite（`memorygraph.db`，JSON 为真源）
- **iOS**：SwiftUI + PhotosUI（远期，能用即可）
