# MemoryGraph Project Charter

## 项目名称

MemoryGraph — 家庭私有记忆系统（Personal Memory System）

---

## 愿景（Vision）

MemoryGraph 不是成长记录 App，也不是 AI Demo。

它是一个**长期运行在自家 Mac 上的个人记忆系统**：把照片（未来还有视频等）变成 AI 可理解的结构化 JSON，几十年可追溯、可导出、不依赖云端。

北极星：十年后，孩子可以通过 AI 回顾自己的成长，而不依赖人工整理相册。

---

## 为什么做（Why）

照片越来越多，记忆却在沉没。几年以后很难回答「第一次去动物园是哪一天」「去年国庆去了哪里」。信息都在，但没有形成知识。MemoryGraph 让这些数据自动变成记忆。

---

## 不做什么（What NOT）

- 不是图库 / 相册替代品
- 不是云端 AI 产品（照片不上传公有云）
- 不是通用聊天机器人
- 不是为了学 AI 而做的 Demo

AI 是工具，Memory 才是目的。

---

## 核心理念

### 1. 数据永远属于用户

原图与 JSON 都在自家 Mac 上，可随时导出。Schema 长期稳定，不绑定某一模型。

### 2. 双路径，单存储

- **Mac 路径（当前主路径）**：相册导出原图 → Python 批量 → JSON
- **iPhone 路径（可选）**：新照片 → Swift 采集 → 同步到 Mac → JSON

两端共用 `schemas/photo.v1.json`，Mac 的 `data/photos/` 与 `data/memory/` 是唯一记忆库。

### 3. 本地优先

视觉理解与人脸识别在 Mac 上用本地模型（Ollama、InsightFace 等）。iPhone 负责采集与同步，不跑大模型。

### 4. 永远先做最小闭环

**当前闭环**：原图 → JSON → SQLite 索引 → CLI 问答。  
下一阶段重点：跑满图库、补全 vision backfill、提升问答质量；再考虑 Web 时间线与 Event。

---

## 阶段目标

### 阶段 0：Photo → JSON @ Mac ✅

- Mac：`data/photos/` 有原图，`tools/photo2json` 产出 `data/memory/*.json`
- Mac Hub：`hub/mac_server` 可接收 iOS 上传（骨架）

**完成标准**：任选一张照片，Mac 上同时存在原图与 JSON。

### 阶段 1：本地视觉与人脸 ✅

- `analyze_image()` 接入 Ollama + Qwen2.5-VL（或同类）
- InsightFace 人脸库 + CLIP 衣着兜底
- 高德逆地理、`location` / `location_coords` 分离
- 支持 `--backfill` 增量补全

### 阶段 2：日常采集 ⏸

- iOS 批量同步、去重、失败重试（App 待开发）
- 当前替代方案：定期从 iPhone 导出原图到 Mac

### 阶段 3：记忆库 ⚠️ 进行中

- ✅ SQLite 索引（`memory_index sync`）
- ✅ CLI 关键词搜索与自然语言问答（`memory_ask`）
- 🔜 时间线 Web 浏览

### 阶段 4+：Event / 体验 🔜

- 事件聚合（同日同地 → outing）
- 语音 / 玩偶 / Web GUI（在有稳定 JSON 库之后）
- 视频 / 音频 JSON（photo  pipeline 稳定后再做）

---

## 项目结构

```
MemoryGraph/
├── schemas/              # JSON 协议
├── apps/ios/             # iPhone 采集（待开发）
├── hub/                  # Mac 中枢（shared + mac_server）
├── tools/
│   ├── photo2json/       # 批量 Photo → JSON
│   ├── face_enroll/      # 人脸库注册
│   ├── memory_index/     # SQLite 同步与搜索
│   └── memory_ask/       # CLI 问答
├── data/                 # 运行时：photos、memory、faces、db
└── docs/
```

详细架构见 [architecture.md](architecture.md)。日常命令见 [operations.md](operations.md)。

---

## 技术原则

- Mac 用 Python；iOS 用 Swift
- 任何模型、框架可替换
- Schema 是合同，变更须升版本（当前 photo v1.1，含 `location_coords`）
- JSON 为唯一数据源；SQLite 可随时 `sync` 重建
- Agent 已有 CLI 基础版；Event 与富交互仍为远期

---

## 隐私原则

- 照片与 AI 推理均在本地 Mac
- 逆地理仅发送 GPS 坐标至高德，不上传图片
- 数据只在家庭网络内流转；Mac 不做公网暴露
