# MemoryGraph — AI 协作说明

> 家庭私有记忆系统 · 当前阶段：Photo → JSON（Mac 中枢 + iOS 采集）

## 项目目标

```
照片 → AI 识别 → JSON → (未来) SQLite → 检索 → Agent
```

**当前阶段**：打通「原图 + JSON」入库到 Mac 的 `data/` 目录。  
不做 SQLite、向量库、RAG、Agent、Web GUI。

## 目录结构

```
MemoryGraph/
├── schemas/                 # JSON 协议（photo.v1.json）
├── apps/ios/                # iPhone 采集 App
├── hub/
│   ├── shared/              # schema.py, analyzer.py, utils.py, config.py
│   └── mac_server/          # 本地 HTTP，接收 iOS 上传
├── tools/photo2json/        # Mac 批量处理
├── data/
│   ├── photos/              # 原图（gitignore）
│   └── memory/              # JSON（gitignore）
└── docs/
```

## 运行方式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Mac 批量处理 data/photos/ → data/memory/
python tools/photo2json/main.py

# Mac Hub（iOS 上传）
python hub/mac_server/main.py
```

## 架构约束（必须遵守）

### 1. 唯一 AI 入口

```python
# hub/shared/analyzer.py
def analyze_image(image_path: str) -> dict:
    ...
```

- 人脸识别逻辑在 `hub/shared/face.py`，由 `analyze_image()` 调用
- 场景语义在 `hub/shared/vision.py`（Ollama 视觉模型），由 `analyze_image()` 调用
- 换模型：改环境变量 `OLLAMA_VISION_MODEL`（见 `.env.example`）
- `tools/photo2json` 与 `hub/mac_server` 均通过 `analyze_image()` 调用
- 其它模块不得 import 或依赖具体模型 SDK

### 1b. 人脸库

| 路径 | 说明 |
|------|------|
| `data/faces/{id}/` | 参考照目录，如 `baby/` |
| `data/faces/registry.json` | id → 中文名 |
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
| `schema_version` | 当前 `"1.0"` |
| `photo_id` | 文件名（不含扩展名） |
| `timestamp` | 优先 EXIF，无则 `""` |
| `device_id` | 来源设备，如 `iphone` / `mac` |
| `source` | 真实 path / width / height |
| `people`, `scene`, `location`, `objects`, `actions`, `emotion`, `tags`, `quality` | 由 `analyze_image()` 返回（iOS 可先留空） |
| 识别不到 | 字符串 `""`，数组 `[]`，对象保持结构 |

**禁止**随意增删改字段名；版本升级须新建 `photo.v2.json`。

### 3. 模块职责

| 模块 | 职责 | 不应做 |
|------|------|--------|
| `tools/photo2json/processor.py` | 批量遍历、写 JSON | 调用具体 AI 模型 |
| `hub/shared/analyzer.py` | 返回 AI 分析字段 | 读 EXIF、写文件 |
| `hub/shared/utils.py` | 元数据、格式过滤 | AI 推理 |
| `hub/mac_server/server.py` | 接收上传、落盘 | 重复实现分析逻辑 |
| `apps/ios/` | 选图、EXIF、上传 | 跑视觉大模型 |

### 4. 错误处理

- 单张图片失败**不中断**整批处理
- 记录失败日志，最终输出统计

## 改代码前必读

1. 改 AI 逻辑 → 读 `hub/shared/analyzer.py`、`hub/shared/vision.py`、`hub/shared/face.py`
2. 改输出格式 → 读 `schemas/`、`hub/shared/schema.py`
3. 改 EXIF/时间 → 读 `hub/shared/utils.py`
4. 改路径 → 读 `hub/shared/config.py`
5. 改 iOS 上传协议 → 读 `hub/mac_server/server.py`、`docs/architecture.md`

## 当前状态（V0.2）

- 目录重组：Mac 中枢 + 双路径入库
- `analyze_image()` 已接入 Ollama 视觉模型 + InsightFace 人脸识别
- Mac 批量工具：`tools/photo2json`
- Mac Hub 骨架：`hub/mac_server`（`POST /import`）
- iOS App：待开发（`apps/ios/README.md`）

## 未来扩展（现在不要做）

- SQLite 存储
- InsightFace 人脸识别
- Event 聚合、时间线、问答 Agent
