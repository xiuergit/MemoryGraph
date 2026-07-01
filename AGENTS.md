# MemoryGraph — AI 协作说明

> 家庭私有记忆系统 · 当前阶段：Photo → JSON → SQLite 索引 → CLI 问答

## 项目目标

```
照片 → AI 识别 → JSON → SQLite 索引 → 检索 → CLI 问答
```

**当前闭环**：Mac 批量产出 JSON，同步 SQLite，CLI 问答可用。  
**暂不做**：Web GUI、Event 聚合、向量 RAG、视频/音频 pipeline。

## 目录结构

```
MemoryGraph/
├── schemas/                 # JSON 协议（photo.v1.json）
├── apps/ios/                # iPhone 采集 App（待开发）
├── hub/
│   ├── shared/              # schema, analyzer, index_db, agent, …
│   └── mac_server/          # 本地 HTTP，接收 iOS 上传
├── tools/
│   ├── photo2json/          # Mac 批量处理 + backfill
│   ├── face_enroll/         # 人脸库注册
│   ├── memory_index/        # SQLite sync / search
│   └── memory_ask/          # CLI 问答
├── data/
│   ├── photos/              # 原图（gitignore）
│   ├── memory/              # JSON（gitignore，唯一数据源）
│   ├── faces/               # 人脸参考照
│   └── memorygraph.db       # 索引（可 sync 重建）
└── docs/
```

## 运行方式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Mac 批量处理 data/photos/ → data/memory/
python tools/photo2json/main.py

# 同步索引 + 问答
python tools/memory_index/main.py sync
python tools/memory_ask/main.py "面面最近去哪了"

# Mac Hub（iOS 上传，可选）
python hub/mac_server/main.py
```

日常分批、backfill、环境变量见 `docs/operations.md`。

## 架构约束（必须遵守）

### 1. 唯一 AI 入口（图像）

```python
# hub/shared/analyzer.py
def analyze_image(image_path: str, *, timestamp: str = "", photo_id: str = "") -> dict:
    ...
```

- 场景语义：`hub/shared/vision.py`（Ollama 视觉模型）
- 人脸识别：`hub/shared/face.py`（InsightFace）
- 衣着兜底：`hub/shared/outfit.py`（CLIP）
- 换模型：改环境变量 `OLLAMA_VISION_MODEL`（见 `.env.example`）
- `tools/photo2json` 与 `hub/mac_server` 均通过 `analyze_image()` 调用
- 其它模块不得 import 或依赖具体模型 SDK

问答 Agent 使用 `hub/shared/agent.py`（Ollama 文本模型 + 规则路由），与图像分析分离。

### 1b. 人脸库

| 路径 | 说明 |
|------|------|
| `data/faces/{id}/` | 参考照目录，如 `baby/` |
| `data/faces/registry.json` | id → 中文名、birth_date、role |
| `data/faces/index.json` | `python tools/face_enroll/main.py` 自动生成 |

```bash
python tools/face_enroll/main.py   # 注册/更新人脸库
python tools/photo2json/main.py    # 识别并写入 people 字段
```

### 2. JSON Schema 不可变

正式定义：`schemas/photo.v1.json`  
Python 实现：`hub/shared/schema.py`

| 字段 | 规则 |
|------|------|
| `schema_version` | 当前 `"1.1"`（1.0 仍可读） |
| `photo_id` | 文件名（不含扩展名） |
| `timestamp` | 优先 EXIF，无则 `""` |
| `device_id` | 来源设备，如 `iphone` / `mac` |
| `location` | 可读地名（逆地理 + 同日归一） |
| `location_coords` | EXIF GPS 原始坐标 `"纬度,经度"`，不覆盖 |
| `source` | 真实 path / width / height |
| `people`, `scene`, `objects`, `actions`, `emotion`, `tags`, `quality` | 由 `analyze_image()` 等返回 |
| `manual_edit` | 可选；为 `true` 时批处理/backfill 不覆盖 |
| 识别不到 | 字符串 `""`，数组 `[]`，对象保持结构 |

**禁止**随意增删改正式字段名；大改须新建 `photo.v2.json`。

### 3. 模块职责

| 模块 | 职责 | 不应做 |
|------|------|--------|
| `tools/photo2json/processor.py` | 批量遍历、写 JSON | 直接调用具体 AI 模型 |
| `hub/shared/analyzer.py` | 返回 AI 分析字段 | 读 EXIF、写文件 |
| `hub/shared/backfill.py` | 增量补全 vision/faces | 替代 processor 首次入库 |
| `hub/shared/index_db.py` | SQLite 同步 | 修改 JSON 真源语义 |
| `hub/shared/agent.py` | 问答组织回答 | 图像推理 |
| `hub/shared/utils.py` | 元数据、格式过滤 | AI 推理 |
| `hub/mac_server/server.py` | 接收上传、落盘 | 重复实现分析逻辑 |
| `apps/ios/` | 选图、EXIF、上传 | 跑视觉大模型 |

### 4. 错误处理

- 单张图片失败**不中断**整批处理
- 记录失败日志，最终输出统计

## 改代码前必读

1. 改 AI 逻辑 → `hub/shared/analyzer.py`、`vision.py`、`face.py`、`outfit.py`
2. 改输出格式 → `schemas/`、`hub/shared/schema.py`
3. 改 EXIF/时间/地点 → `hub/shared/utils.py`、`geocode.py`、`location_cluster.py`
4. 改索引/问答 → `hub/shared/index_db.py`、`query.py`、`agent.py`
5. 改路径 → `hub/shared/config.py`
6. 改 iOS 上传协议 → `hub/mac_server/server.py`、`docs/architecture.md`

## 当前状态

- ✅ `analyze_image()`：Ollama 视觉 + InsightFace + CLIP 衣着兜底
- ✅ 高德逆地理 + 同日 location 归一 + `location_coords`
- ✅ `tools/photo2json` + `--backfill vision|faces|all`
- ✅ `tools/memory_index` + `tools/memory_ask`
- ⏸ Mac Hub：`hub/mac_server`（`POST /import`）
- 🔜 iOS App、Web 时间线、Event 聚合、video/audio

## 未来扩展（未做或仅规划）

- Event 聚合（同日同地 outing）
- Web 时间线 GUI
- 视频 / 音频 JSON pipeline
- 向量语义检索（若需要再上）
