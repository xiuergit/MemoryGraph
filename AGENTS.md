# MemoryGraph — AI 协作说明

> 家庭私有记忆系统 · 当前阶段：Photo → JSON → SQLite 索引 → 事件聚合 → CLI / Web 问答

## 项目目标

```
照片 → AI 识别 → JSON → SQLite 索引 → 事件聚合 → 检索 → CLI / Web 问答
```

**当前闭环**：Mac 批量产出 JSON，同步 SQLite，CLI 问答可用；**MemoryGraph Desk**（FastAPI）+ **Vue Inspector**（`web/`）管理 JSON/地址缓存/问答/事件；CLI 仍可用于批处理与问答。  
**暂不做**：全库相册式时间轴（交给系统相册）、向量 RAG、视频/音频 pipeline。  
**远期可选**：筛选结果时间轴（人物/物体/场景检索命中后，按时间分组展示）。

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
│   ├── face_enroll/         # 人脸库注册 / cluster
│   ├── memory_index/        # SQLite sync / search
│   ├── memory_events/       # Outing 事件聚合
│   ├── memory_ask/          # CLI 问答
│   ├── memory_desk/         # FastAPI：搜文件、问答、memory/geocode API
│   ├── location_mapping/    # .geocode_cache.json CLI（migrate / delete-by-location 等）
│   ├── memory_stats/        # 数据健康报告
│   └── find/                # 按文件名搜索 CLI
├── web/                     # Vue Inspector（连 Desk API）
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

# 同步索引 + 事件 + 问答
python tools/memory_index/main.py sync
python tools/memory_events/main.py sync
python tools/memory_ask/main.py "面面最近去哪了"

# 本地 Web API + Vue Inspector
python tools/memory_desk/main.py --auto-port
cd web && npm install && npm run dev

# Mac Hub（iOS 上传，可选）
python hub/mac_server/main.py
```

日常分批、backfill、环境变量见 `docs/operations.md`。

## 架构约束（必须遵守）

### 0. AI 协作隐私（`.cursorignore`）

根目录 `.cursorignore` 限制 Cursor AI **不得读取**以下路径：

| 路径 | 原因 |
|------|------|
| `data/photos/**` | 家庭原图，禁止 AI 读取或分析 |
| `data/faces/**/*` | 人脸参考照（`README.md`、`registry.example.json` 除外） |
| `data/.trash/**` | 已删除的原图 / JSON |
| `.env` | 本地密钥 |

**协作约定：**

- 理解照片内容 → 只看 `data/memory/*.json` 或 SQLite 索引，**不**打开原图
- 改图像分析逻辑 → 读 `hub/shared/analyzer.py` 等代码，**不**用样本原图做试验
- 本地批处理（`photo2json`、`face_enroll`）仍在本机读 `data/photos/`，与 Cursor 无关
- 增删 `.cursorignore` 条目时，同步更新本节表格

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
| `location` | 可读地名（逆地理 + 可选同日归一；**纠错真源**为 `.geocode_cache.json`） |
| `location_coords` | EXIF GPS 原始坐标 `"纬度,经度"`，不覆盖 |
| `location_admin` | 可选；`province` / `city` / `district` / `formatted_address`（逆地理原文） |
| `manual_location` | 可选；为 `true` 时 `--regeocode-locations` / 地址归一跳过 |
| `manual_people` | 可选；为 `true` 时 `--backfill faces` 不覆盖 people |
| `manual_vision` | 可选；为 `true` 时 `--backfill vision` 不覆盖场景等字段 |
| `source` | 真实 path / width / height |
| `people`, `scene`, `objects`, `actions`, `emotion`, `tags`, `quality` | 由 `analyze_image()` 等返回 |
| `manual_edit` | 兼容汇总：任一分项手改时可同步为 `true`；跳过逻辑以分项为准 |
| 识别不到 | 字符串 `""`，数组 `[]`，对象保持结构 |

**禁止**随意增删改正式字段名；大改须新建 `photo.v2.json`。

### 3. 模块职责

| 模块 | 职责 | 不应做 |
|------|------|--------|
| `tools/photo2json/processor.py` | 批量遍历、写 JSON | 直接调用具体 AI 模型 |
| `hub/shared/analyzer.py` | 返回 AI 分析字段 | 读 EXIF、写文件 |
| `hub/shared/backfill.py` | 增量补全 vision/faces | 替代 processor 首次入库 |
| `hub/shared/events.py` | Outing 聚类、overlay 重挂、stories | 改 photo JSON 语义 |
| `hub/shared/index_db.py` | SQLite 同步 | 修改 JSON 真源语义 |
| `hub/shared/agent.py` | 问答组织回答 | 图像推理 |
| `hub/shared/photo_delete.py` | 删除照片（移入 `.trash` + 清索引） | 替代 JSON 真源 |
| `hub/shared/utils.py` | 元数据、格式过滤 | AI 推理 |
| `hub/shared/geocode.py` | 逆地理、`.geocode_cache.json` CRUD | 改 JSON 语义 |
| `hub/shared/location_cluster.py` | 同日归一、regeocode、`manual_location` 清理 | 替代 geocode 缓存纠错 |
| `hub/shared/location_canonical.py` | 缓存别名合并（可选） | 日常家附近 POI 拆分 |
| `tools/location_mapping/` | 地址缓存 CLI | 直接改 memory JSON |
| `tools/memory_desk/app.py` | Desk REST API | 重复 analyze_image |
| `web/` | Vue Inspector UI | 直连 SQLite / 绕过 JSON |
| `hub/mac_server/server.py` | 接收上传、落盘 | 重复实现分析逻辑 |
| `apps/ios/` | 选图、EXIF、上传 | 跑视觉大模型 |

### 4. 错误处理

- 单张图片失败**不中断**整批处理
- 记录失败日志，最终输出统计

## 改代码前必读

1. 改 AI 逻辑 → `hub/shared/analyzer.py`、`vision.py`、`face.py`、`outfit.py`
2. 改输出格式 → `schemas/`、`hub/shared/schema.py`
3. 改 EXIF/时间/地点 → `hub/shared/utils.py`、`geocode.py`、`location_cluster.py`、`location_canonical.py`
4. 改地址缓存 / 批量 regeocode → `tools/location_mapping/`、`photo2json --regeocode-locations`
5. 改索引/问答 → `hub/shared/index_db.py`、`query.py`、`agent.py`
5b. 改事件聚合 / 故事 → `hub/shared/events.py`、`tools/memory_events/`、Vue「事件」Tab
6. 改路径 → `hub/shared/config.py`
7. 改 Desk / Vue → `tools/memory_desk/app.py`、`web/src/`
8. 改 iOS 上传协议 → `hub/mac_server/server.py`、`docs/architecture.md`

## 当前状态

- ✅ `analyze_image()`：Ollama 视觉 + InsightFace + CLIP 衣着兜底
- ✅ 高德逆地理 + `.geocode_cache.json` 纠错层 + `location_coords` / `location_admin`
- ✅ `tools/photo2json` + `--regeocode-locations` / `--backfill vision|faces|all`（`--refill` / `--year` / `--has-people` / `--needs-faces`）
- ✅ `tools/location_mapping` + Vue「地址缓存」
- ✅ `tools/memory_index` + `tools/memory_ask`（默认带 file:// 链接，`--no-links` 关闭）
- ✅ `tools/memory_events` + Vue「事件」Tab（outing / 家事件；overlay 重挂、stories 表结构）
- ✅ `tools/memory_desk` + **`web/` Vue Inspector**：列表（含批量标人物）、问答、事件、详情、批量改地址、地址缓存、人脸库、维护工具、验证、健康报告
- ✅ `tools/memory_stats` / `tools/find`
- ⏸ Mac Hub：`hub/mac_server`（`POST /import`）；iOS App 待开发
- 🔜 详情页改 `people[]`、筛选结果时间轴视图、向量 RAG、video/audio pipeline

## 未来扩展（未做或仅规划）

- 详情页单条改人物（列表批量标人物已有）
- **筛选结果时间轴**（见下；**不是**全库照片墙式相册时间轴）
- overlay / stories 日常录入与展示增强
- 视频 / 音频 JSON pipeline
- 向量语义检索（若需要再上）

### 筛选结果时间轴（远期，非相册）

MemoryGraph **不是相册**。以下**明确不做**：

- 全库按年/月/日无限滚动的照片墙（iPhone 相册已足够）

若未来做时间向可视化，应是 **检索 → 时间分组展示**：

1. 先筛：人物 / 关键词（物体、场景、tags）/ 地点 / 年份（列表 Tab、问答已支持检索）
2. 再排：命中结果按时间分组，看「第一次出现」「频次变化」「阶段对比」
3. 轻量即可：例如在列表 Tab 增加「时间分组」视图，不必复刻完整相册 App

当前替代：列表（分页+筛选）、事件 Tab（出门粒度）、问答（文字+证据缩略图）、CLI `memory_index timeline`。
