# MemoryGraph

家庭私有记忆系统：照片 / 视频 / 音频 → 标准 JSON → 索引 → 问答，长期保存在家用 Mac 上。

## 架构

```
iPhone 导出原图                    家用 Mac（记忆中枢）
        │                                  │
        └────────► data/photos/            │
                     │                     │
                     ▼                     │
              tools/photo2json             │  Ollama + InsightFace
                     │                     │
                     ▼                     │
              data/memory/*.json           │
                     │                     │
                     ▼                     │
              memory_index sync            │
                     │                     │
                     ▼                     │
              memory_events sync（可选）   │
                     │                     │
                     ▼                     │
        memory_ask / Desk API
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
   Vue Inspector   CLI ask    iOS 消费端
```

- **不上云端**：照片与 AI 推理均在 Mac 本地；逆地理仅发送 GPS 坐标
- **采集**：系统相册导出到 Mac，或 iOS 家长模式回家上传（见 [mobile-outbox.md](docs/mobile-outbox.md)）
- **消费**：Vue Inspector + iOS「问问 / 谁」连 Desk
- **协议**：`photo.v1`（生产）+ `video.v1` / `audio.v1`（协议已定）；索引用 `media_type`；见 [media-memory.md](docs/media-memory.md)
- **当前阶段（阶段 2）**：结构化问答打磨（见 [Project Charter](docs/Project%20Charter.md)、[agent-intents.md](docs/agent-intents.md)）；视频入库可并行

## 目录结构

```
MemoryGraph/
├── schemas/              # JSON 协议（photo / video / audio.v1）
├── apps/ios/             # 问问 / 谁；家长模式回家上传
├── hub/
│   ├── shared/           # Schema、分析器、索引、Agent
│   └── mac_server/       # 上传骨架（暂不推进）
├── tools/
│   ├── photo2json/       # Mac 批量：photos → memory
│   ├── face_enroll/      # 人脸库注册
│   ├── location_mapping/ # 高德地址缓存 CLI（迁移 / 删 / 补）
│   ├── memory_index/     # SQLite 同步与搜索
│   ├── memory_events/    # Outing 事件聚合 sync / stats / list
│   ├── memory_ask/       # CLI 自然语言问答
│   ├── memory_desk/      # 本地 Web API：搜文件、问答、事件、JSON/缓存 API
│   ├── memory_stats/     # 数据健康报告
│   ├── memory_dedup/     # 去重候选报告（不删除）
│   └── find/             # 按文件名搜索 CLI
├── web/                  # Vue Inspector（连 Desk API：列表/问答/事件/维护等）
├── data/
│   ├── photos/           # 原图（运行时，不进 git）
│   ├── memory/           # JSON（运行时，不进 git）
│   ├── faces/            # 人脸参考照
│   ├── memory_annotations.json  # 事件意义/故事真源（跨机必拷）
│   └── memorygraph.db    # 检索索引（可 sync 重建）
└── docs/                 # 项目说明
```

## 快速开始

```bash
# 1. 环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 把原图放进 data/photos/

# 2b.（可选）人脸识别：参考照放进 data/faces/baby/ 等目录
cp data/faces/registry.example.json data/faces/registry.json
python tools/face_enroll/main.py

# 2c.（可选）配置环境变量
cp .env.example .env
# 编辑 .env：OLLAMA_VISION_MODEL、AMAP_KEY 等
export $(grep -v '^#' .env | xargs)

# 回家首次使用 Ollama 视觉模型：
# ollama pull qwen2.5vl:7b          # 或你机器上已有的 VL 模型
# ollama list                       # 查看模型名，填入 .env 的 OLLAMA_VISION_MODEL

# 3. 批量生成 JSON
python tools/photo2json/main.py

# 3b. 同步索引 + 事件 + 问答（见 docs/operations.md）
python tools/memory_index/main.py sync
python tools/memory_events/main.py sync
python tools/memory_ask/main.py "最近出去玩了哪些"

# 3c. 本地 Web（Vue / iOS 消费端都连 Desk）
python tools/memory_desk/main.py --host 0.0.0.0 --auto-port   # API，默认 8766

# Vue Inspector（列表 / 问答 / 事件 / 详情 / 地址缓存 / 人脸库 / 维护工具）
cd web && npm install && npm run dev           # 浏览器打开 Vite 提示的地址

# iOS 消费端：open apps/ios/MemoryGraph.xcodeproj（见 apps/ios/README.md）
```

Desk + Vue 用法见 [operations.md](docs/operations.md) 第八、九节。

## 文档

- **[回家操作手册](docs/operations.md)** — 执行流程、环境配置、命令速查、注意事项
- [项目章程](docs/Project%20Charter.md) — 愿景与阶段目标（**阶段 2 = 修问答**）
- [架构说明](docs/architecture.md) — 采集 / 消费分工、隐私边界、入库流程
- [问答意图](docs/agent-intents.md) — Agent 路由与阶段 2 打磨清单
- [多媒体记忆协议](docs/media-memory.md) — photo / video / audio 与 Live Photo 约定
- [AGENTS.md](AGENTS.md) — AI 协作约束

## 当前状态

- ✅ `tools/photo2json`：Ollama 视觉 + InsightFace + CLIP + 高德逆地理；`--regeocode-locations` / `--backfill`
- ✅ `tools/location_mapping` + Vue「地址缓存」：`.geocode_cache.json` 纠错（真源），改完 `regeocode-locations` 写 JSON
- ✅ `tools/memory_index`：SQLite 索引（JSON 为真源）
- ✅ `tools/memory_events`：同日同地 outing / 家事件聚合；`memory_annotations.json` 真源 + overlay 重挂、stories
- ✅ `tools/memory_ask`：CLI 问答（20+ 意图；默认 file:// 链接）
- ✅ `tools/memory_desk` + **`web/` Vue Inspector**：列表（含批量标人物）、问答、事件、详情、批量改地址、地址缓存、人脸库、维护工具、验证、健康报告
- ✅ `apps/ios/`：问问 / 谁；家长模式待上传、故事、回家同步
- ✅ 回家上传：Desk `POST /api/media/ingest` + 旁白 + 故事（`mac_server` 的 `/import` 骨架仍不推进）
- ✅ `tools/memory_stats` / `tools/find` / `tools/memory_dedup`
- 🚧 **阶段 2**：结构化问答打磨（`unknown` fallback、关键词意图、复合条件等）
- ✅ 多媒体协议：`schemas/video.v1.json` / `audio.v1.json`（pipeline 未做）
- 🔜 详情页改 `people[]`、筛选结果时间轴、向量 RAG、video/audio 入库
