# MemoryGraph

家庭私有记忆系统：照片 → 标准 JSON，长期保存在家用 Mac 上。

## 架构

```
iPhone（采集）                    家用 Mac（记忆中枢）
     │                                  │
     │  原图 + JSON（局域网）            │  Python 批量处理已有照片
     └──────── POST /import ──────────►│
                                        ├── data/photos/   原图
                                        └── data/memory/   JSON
```

- **不上云端**：数据只在家庭网络内流转，Mac 为唯一存储中枢
- **双路径入库**：iOS 同步新照片；Mac 批量处理已有图库
- **协议统一**：`schemas/photo.v1.json`

## 目录结构

```
MemoryGraph/
├── schemas/              # JSON 协议（单一事实来源）
├── apps/ios/             # iPhone 采集 App（待建）
├── hub/
│   ├── shared/           # Schema、分析器、工具（Python 共享）
│   └── mac_server/       # 本地 HTTP 服务，接收 iOS 上传
├── tools/photo2json/     # Mac 批量：photos → memory
├── data/
│   ├── photos/           # 原图（运行时，不进 git）
│   └── memory/           # JSON（运行时，不进 git）
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

- Mac 批量流水线：`tools/photo2json`（Analyzer 为 Mock，待接本地模型）
- Mac Hub：`hub/mac_server`（接收 iOS 上传并落盘）
- iOS App：待开发（见 `apps/ios/README.md`）
