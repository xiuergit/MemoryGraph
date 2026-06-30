# MemoryGraph 架构说明

## 定位

**家庭私有记忆基础设施** — 不是相册，不是云端 AI 产品。

| 组件 | 角色 |
|------|------|
| **iPhone App** | 采集端：选图、读 EXIF、同步到 Mac |
| **Mac（Python）** | 记忆中枢：本地 AI 分析、存储原图 + JSON |
| **JSON** | 记忆原子，协议见 `schemas/photo.v1.json` |

## 数据流

### 路径 A：Mac 已有原图（优先打通）

```
data/photos/*.jpg
        │
        ▼
tools/photo2json/main.py
        │
        ▼
hub/shared/analyzer.py  （本地模型，当前 Mock）
        │
        ▼
data/memory/{photo_id}.json
```

### 路径 B：iPhone 新照片

```
相册选图
    │
    ▼
Swift：EXIF + JSON 骨架
    │
    ▼
POST /import（局域网，仅家庭 Wi‑Fi）
    │
    ▼
hub/mac_server/server.py
    ├── 原图 → data/photos/
    └── JSON → data/memory/（Mac 可补全 AI 字段）
```

两条路径最终落到**同一目录、同一 Schema**。

## 存储布局

```
data/
├── photos/
│   └── IMG_0001.jpg      # 原图
└── memory/
    └── IMG_0001.json     # 与 photo_id 一一对应
```

`photo_id` = 文件名（不含扩展名）。

## 隐私边界

| 规则 | 实现 |
|------|------|
| 不上传公有云 | 禁止调用第三方 AI API；仅用 Mac 本地 Ollama 等 |
| 手机 → 家 | 仅局域网 HTTP（默认端口 8765） |
| Mac 数据不外泄 | 不做公网端口转发；服务 bind 局域网 |
| 可导出 | JSON 纯文本 + 原图文件夹，随时拷贝 |

## 模块职责

| 模块 | 职责 |
|------|------|
| `schemas/` | 协议定义，iOS 与 Python 共同遵守 |
| `hub/shared/schema.py` | Python 侧 Schema 实现 |
| `hub/shared/analyzer.py` | **唯一 AI 入口** `analyze_image()` |
| `hub/shared/utils.py` | EXIF、尺寸、文件过滤 |
| `tools/photo2json/` | Mac 批量处理 |
| `hub/mac_server/` | iOS 上传接收服务 |
| `apps/ios/` | iPhone 采集 App |

## 阶段规划

| 阶段 | 目标 | 完成标准 |
|------|------|----------|
| **0（现在）** | Mac 批量 Photo→JSON | `data/photos` 有图，能产出 JSON 文件 |
| **1** | 接入本地视觉模型 | JSON 中 scene/objects 有真实内容 |
| **2** | iOS 上传打通 | 手机选 1 张图，Mac 出现成对文件 |
| **3** | 索引与时间线 | SQLite + 按时间浏览 |
| **4+** | Event / Agent | 有稳定 JSON 库之后再做 |

## 技术选型

- **Mac 分析**：Python + Ollama（Qwen2.5-VL 等）
- **Mac 服务**：FastAPI + uvicorn
- **iOS**：SwiftUI + PhotosUI（够用即可）
- **存储**：先纯 JSON 文件，阶段 3 再加 SQLite
