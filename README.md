# MemoryGraph

家庭私有记忆系统：照片 → 标准 JSON → 索引 → 问答，长期保存在家用 Mac 上。

## 架构

```
导出原图 / iPhone 上传              家用 Mac（记忆中枢）
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
              memory_ask（CLI 问答）        │
```

- **不上云端**：照片与 AI 推理均在 Mac 本地；逆地理仅发送 GPS 坐标
- **主路径**：iPhone 导出原图 → Mac 批量处理（iOS App 可选）
- **协议统一**：`schemas/photo.v1.json`（当前 v1.1，含 `location_coords`）

## 目录结构

```
MemoryGraph/
├── schemas/              # JSON 协议（单一事实来源）
├── apps/ios/             # iPhone 采集 App（待建）
├── hub/
│   ├── shared/           # Schema、分析器、索引、Agent
│   └── mac_server/       # 本地 HTTP 服务，接收 iOS 上传
├── tools/
│   ├── photo2json/       # Mac 批量：photos → memory
│   ├── face_enroll/      # 人脸库注册
│   ├── memory_index/     # SQLite 同步与搜索
│   └── memory_ask/       # CLI 自然语言问答
├── data/
│   ├── photos/           # 原图（运行时，不进 git）
│   ├── memory/           # JSON（运行时，不进 git）
│   ├── faces/            # 人脸参考照
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

# 3b. 同步索引 + 问答（见 docs/operations.md）
python tools/memory_index/main.py sync
python tools/memory_ask/main.py "最近的照片"

# 4. 启动 Mac Hub（可选，iOS 上传用）
python hub/mac_server/main.py
# 服务地址: http://0.0.0.0:8765
```

## 文档

- **[回家操作手册](docs/operations.md)** — 执行流程、环境配置、命令速查、注意事项
- [项目章程](docs/Project%20Charter.md) — 愿景与阶段目标
- [架构说明](docs/architecture.md) — 双端分工、隐私边界、入库流程
- [AGENTS.md](AGENTS.md) — AI 协作约束

## 当前状态

- ✅ `tools/photo2json`：Ollama 视觉 + InsightFace + CLIP 衣着兜底 + 高德逆地理
- ✅ `--backfill`：增量补全 vision / faces
- ✅ `tools/memory_index`：SQLite 索引（JSON 为真源）
- ✅ `tools/memory_ask`：CLI 自然语言问答（基础版）
- ⏸ Mac Hub：`hub/mac_server`（接收 iOS 上传，骨架可用）
- 🔜 iOS App、Web 时间线、Event 聚合
