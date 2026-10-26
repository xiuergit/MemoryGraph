# MemoryGraph 回家操作手册

> 适用场景：隔一段时间把 iPhone 照片导出到 Mac，批量分析 → 建索引 → 问答。也可以用 iOS 家长模式回家上传。  
> 家用 Mac + Ollama 完成分析。导出这条不依赖手机 App。  
> iOS：问问 / 谁，以及家长模式回家同步；见 `apps/ios/README.md`。  
> **当前阶段（阶段 2）**：结构化问答打磨，见 [agent-intents.md](agent-intents.md)。

---

## 一、整体流程（每次导照片后）

```
导出原图 → data/photos/
    ↓
photo2json（AI 分析，写 JSON）
    ↓
data/memory/*.json
    ↓
memory_index sync（同步 SQLite 索引）
    ↓
memory_events sync（聚合出门/家事件，可选但推荐）
    ↓
memory_ask / Vue 问答（自然语言问答）
```

**数据分工（重要）：**

| 路径 | 是什么 | 能否删了重建 |
|------|--------|--------------|
| `data/photos/` | 原图 | ❌ 核心资产，别删 |
| `data/memory/*.json` | 结构化记忆（唯一数据源） | ⚠️ 删了要重跑 photo2json |
| `data/memorygraph.db` | 检索索引 | ✅ 随时 `sync` 重建 |
| `data/memory_annotations.json` | 事件意义 / 故事 | ⚠️ 跨机必拷；`memory_events sync` 灌库 |
| `data/ask_checklist.json` | 问答错题本（Vue「问答」） | ✅ 可删会按种子重建；跨机可拷 |
| `data/.geocode_cache.json` | 高德地址缓存（**纠错真源**，v6 key） | ✅ 可删重建；日常在 Vue/CLI 改 |
| `data/location_canonical.json` | 可选；合并别名（家附近「拆开 POI」时通常留空） | ✅ |
| `data/.trash/` | Desk 删除的照片/JSON | ✅ 可恢复；彻底清空 `rm -rf data/.trash/` |

---

## 二、首次环境准备（回家做一次）

### 1. 进入项目、激活虚拟环境

```bash
cd /path/to/MemoryGraph
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

国内若慢，PyPI 可加镜像：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 用编辑器打开 .env，填入 AMAP_KEY、Ollama 模型名等
export $(grep -v '^#' .env | xargs)
```

**建议每次开新终端后都执行一次 `export $(grep -v '^#' .env | xargs)`**，或写进 shell 配置。

### 3. 启动 Ollama

```bash
# 确认 Ollama 在跑（菜单栏有图标，或）
ollama serve

# 查看已有模型
ollama list
```

**需要两类模型：**

| 用途 | .env 变量 | 示例 |
|------|-----------|------|
| 照片视觉分析（scene/tags） | `OLLAMA_VISION_MODEL` | `qwen2.5vl:7b` |
| Agent 问答润色 | `OLLAMA_CHAT_MODEL` | `qwen2.5:7b` |

没有视觉模型时：

```bash
ollama pull qwen2.5vl:7b
```

没有 chat 模型时：

```bash
ollama pull qwen2.5:7b
```

把 `ollama list` 里**实际存在的模型名**填进 `.env`，名字必须一致。

### 4. 人脸库（首次或换参考照时）

```bash
# 参考照目录：data/faces/baby/ 等，每人 10～20 张清晰正脸
cp data/faces/registry.example.json data/faces/registry.json
# 编辑 registry.json：姓名、birth_date、role

python tools/face_enroll/main.py build
```

`registry.json` 示例：

```json
{
  "baby": {
    "name": "面面",
    "birth_date": "2020-09-04",
    "role": "child"
  }
}
```

### 5. 申请高德 Key（坐标 → 中文地址）

1. 打开控制台：https://console.amap.com/
2. 注册/登录 → **应用管理** → **创建新应用**
3. 在该应用下 **添加 Key**，服务平台选 **Web 服务**
4. 复制 Key 到 `.env`：`AMAP_KEY=你的Key`

API 文档（逆地理编码）：https://lbs.amap.com/api/webservice/guide/api/georegeo

---

## 三、日常操作（每次导照片）

### 一键脚本（推荐）

原图放进 `data/photos/` 后，**默认不跑 Ollama**；vision 另开、每次一批：

```bash
# ① 新图快出 JSON（人脸 + 地点；跳过已有）
#    --input 只缩小扫描范围，photo_id 仍相对 data/photos/（不会因为子目录变 id）
./import_photos.sh --input data/photos/2026

# ② 补 scene/tags：默认每次 1000 张（有人物优先）；反复执行直到补完
./import_photos.sh --vision
./import_photos.sh --vision --limit 500          # 或改每批张数
./import_photos.sh --vision --year 2026          # 或只补某年

# 若要坚持入库时就跑 Ollama（慢）：
./import_photos.sh --full --input data/photos/2026

./import_photos.sh --stats                       # 可选：健康报告
./import_photos.sh --index-only                  # 只 sync 索引+事件（JSON 已改时）
```

`--vision` = `photo2json --backfill vision --has-people --limit 1000` + 索引/事件 sync。详细参数见 `./import_photos.sh --help`。

### 步骤 1：放入原图

把从 iPhone 导出的照片放进 `data/photos/`。  
**新约定（向前）**：按**年/月**归位，便于批处理，也减少与日后手机 Outbox 上传撞名（见 [mobile-outbox.md](mobile-outbox.md) §5）：

```
data/photos/2026/09/IMG_3832.HEIC
```

历史习惯（仍有效、不强制迁移）按年即可，例如：

```
data/photos/2025/IMG_3832.HEIC
data/photos/2026/IMG_3855.HEIC
```

手机回家上传落盘时文件名会带 `ob_` 前缀，与导出的 `IMG_*` 区分；`photo_id` 始终相对 `data/photos/` 整棵路径。

支持格式（当前 `photo2json`）：`.jpg` `.jpeg` `.png` `.heic` `.heif`  

视频（`.mov` / `.mp4` 等）可与照片同放在 `data/photos/`。协议见 `schemas/video.v1.json`；入库：

```bash
# 指定文件（示例）
python tools/video2json/main.py data/photos/2026/5-8/IMG_4602.MOV

# 扫目录；--limit=本次成功写入条数（跳过已有并续补）；--no-ai 只写元数据；--force 覆盖
python tools/video2json/main.py --input data/photos/2026/5-8 --limit 5
```

写出 `data/memory/{video_id}.json`（id 为路径 stem + `_v`）。跑完后执行 `python tools/memory_index/main.py sync`，Vue 列表才能看到新视频。约定见 [media-memory.md](media-memory.md)。

### 步骤 2：批量生成 JSON

```bash
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)

python tools/photo2json/main.py
```

**常用参数：**

```bash
# 只处理某个子目录
python tools/photo2json/main.py --input data/photos/2026

# 强制重跑已有 JSON（默认会跳过已存在的）
python tools/photo2json/main.py --force
```

**输出：** 每张图对应 `data/memory/{photo_id}.json`

批处理结束后会自动做 **同日地点归一**（相近 GPS + 当天相邻照片投票，统一成「古猗园」这类简短地名）。也可单独执行：

```bash
python tools/photo2json/main.py --normalize-locations
python tools/memory_index/main.py sync
```

**地点名不合理时（不需原图）**：优先改 **地址缓存**（见第八节），再按 JSON 里的 `location_coords` 重算 `location` / `location_admin`：

```bash
# 先试 5 条
python tools/photo2json/main.py --regeocode-locations --limit 5

# 全库重算（有坐标才会调高德；命中 .geocode_cache.json 则不请求 API）
python tools/photo2json/main.py --regeocode-locations --no-normalize-after

python tools/memory_index/main.py sync
```

**家附近 / 已手工拆 POI 时**：务必加 `--no-normalize-after`，**不要**再跑 `--normalize-locations`（会把「馨越公寓」「河滨香景园」等又合并成一条）。

`location_coords` 不变；已有 `location` 但缺 `location_admin` 的也会补全；`manual_edit: true` 或 `manual_location: true` 的 JSON 会跳过。

**无 GPS 的老照片**（约 37% 无 `location_coords`；约 18% 仍无可读 `location`）：只能靠 Vue「批量改地址」按日手工填；连拍多的日子优先改，≤4 张/天可跳过。

**耗时说明：** 全量模式每张图要跑 Ollama 视觉 + 人脸 +（可选）CLIP。可分两阶段，见下文「快出 JSON + 后续补全」。

#### 推荐：先快出 JSON，再按需补 Ollama

**第 1 阶段 — 全库快速出 JSON（不跑 Ollama，可选关 CLIP）：**

```bash
export OLLAMA_VISION_ENABLED=false
export CLIP_ENABLED=false   # 可选，进一步加速
python tools/photo2json/main.py
python tools/memory_index/main.py sync
```

此时 JSON 里会有：`timestamp`、`location` / `location_coords`、人脸 `people` 等；`scene`、`tags` 为空。

**第 2 阶段 — 只补 Ollama 视觉（已有 JSON 不会被整份重写）：**

> **当前库况（约）：** `scene` / `tags` / `objects` 已约 **90%+** 有值；剩余待补多在 2021、2023。`emotion` 仍约四成，不必为补 emotion 单独重跑全库。用 `python tools/memory_stats/main.py` 看最新数字。

```bash
export OLLAMA_VISION_ENABLED=true
# 只补 scene/tags/objects 仍全空的照片
python tools/photo2json/main.py --backfill vision

# 只补「已识别到人物」的照片（推荐，省时间）
python tools/photo2json/main.py --backfill vision --has-people

# 强制重跑视觉（即使已有 scene）
python tools/photo2json/main.py --backfill vision --refill

python tools/memory_index/main.py sync
```

**其他补全：**

```bash
# 只补人脸/people（例如后来更新了人脸库）
python tools/photo2json/main.py --backfill faces

# 人脸库新增成员后：重跑所有人脸（即使 people 非空也会更新）
python tools/face_enroll/main.py build
python tools/photo2json/main.py --backfill faces --refill

# 只补「检测到脸但 people 为空」的照片（新人脸库维护后常用）
python tools/photo2json/main.py --backfill faces --needs-faces

# 补全部 AI 字段（等同对选中 JSON 重跑 analyze_image）
python tools/photo2json/main.py --backfill all --has-people
```

### 补全天气（Open-Meteo，日粒度）

需 JSON 里已有 `timestamp` + `location_coords`；**不读原图**。同日近距离坐标共享 `data/.weather_cache.json`。

```bash
# 试跑 20 张
python tools/photo2json/main.py --backfill weather --limit 20

# 按年补全（已有 weather 会跳过）
python tools/photo2json/main.py --backfill weather --year 2024

# 强制重拉
python tools/photo2json/main.py --backfill weather --refill --year 2024 --limit 100

python tools/memory_index/main.py sync
```

最近约 5 天的日期可能因再分析延迟查不到（计失败）；无 GPS / 无时间的照片会跳过。

**人脸 `--refill` 注意：** 全库约 2 万张，InsightFace 占内存大，可能被系统 `killed`（OOM）。建议按年或限量分批：

```bash
python tools/photo2json/main.py --backfill faces --refill --year 2024 --limit 500
python tools/photo2json/main.py --backfill faces --refill --year 2023 --limit 500
# 中断后反复执行即可续跑（已写入的 JSON 会保留）
python tools/memory_index/main.py sync
```

**哪些照片值得跑 Ollama？**

| 类型 | 建议 |
|------|------|
| 有面面/家人（`people` 非空） | ✅ 优先 `--backfill vision --has-people` |
| 纯风景、路人、文档截图 | ⏭ 可不跑，问答价值低 |
| 连拍重复 | 可先快出 JSON，以后用 `python tools/memory_dedup/main.py` 出候选再人工删 |

默认 `--backfill` **只补空字段**（`scene`/`tags`/`objects` 都空才跑），中断后可反复执行，已补过的会跳过。主库已基本齐时，续补优先 `--year 2021` / `2023`。

**温和模式（保护电脑、分批跑 Ollama）：**

风扇响是 Mac 正常散热，不会因此「烧坏」；但可持续跑很多天。建议：

```bash
# 每次只补 5 张有人脸的照片，每张间隔 15 秒，跑完就停
export OLLAMA_VISION_ENABLED=true
python tools/photo2json/main.py --backfill vision --has-people \
  --limit 5 --sleep 15

# 每 3 张额外休息 2 分钟（适合睡前跑几轮）
python tools/photo2json/main.py --backfill vision --has-people \
  --limit 9 --batch-size 3 --batch-rest 120 --sleep 10
```

同一命令**反复执行**即可续补：已成功的会跳过，永远从「还没 scene 的有效 JSON」接着跑。

| 参数 | 作用 |
|------|------|
| `--has-people` | 只补 JSON 里已识别到人物/人脸的（推荐） |
| `--limit 5` | 本次最多更新 5 张就停 |
| `--sleep 15` | 每张之间歇 15 秒 |
| `--batch-size 3 --batch-rest 120` | 每 3 张多歇 2 分钟 |
| `--year 2025` | 只补 2025 年的 JSON |
| `--needs-faces` | 只补「有脸未识别」（`face_detected` 且 `people` 空） |
| `--refill` | 与 `--backfill` 联用：强制重跑（faces/vision），即使字段已有值 |
| `--resume` | 显式续跑：跳过已有 scene/tags（默认行为，与 `--refill` 互斥） |

**按年分批补 vision：**

```bash
# 看各年待补数量 + 续跑命令
python tools/memory_stats/main.py --year 2025

# 只补 2025 年、有人脸、每次 20 张，中断后反复执行即可续跑
python tools/photo2json/main.py --backfill vision --year 2025 --has-people --resume --limit 20 --sleep 10
python tools/memory_index/main.py sync
```

**数据健康报告：**

```bash
python tools/memory_stats/main.py
python tools/memory_stats/main.py --year 2025
```

### 步骤 3：同步 SQLite 索引

```bash
python tools/memory_index/main.py sync
```

看到 `新增 N` 或 `跳过 N` 即正常。JSON 有改动时会自动更新对应条目。

**辅助命令：**

```bash
python tools/memory_index/main.py stats
python tools/memory_index/main.py search --person 面面
python tools/memory_index/main.py timeline --limit 10
```

### 步骤 4：问答

支持的自然语言意图（路由规则、示例、数据依赖）见 **[agent-intents.md](agent-intents.md)**。

```bash
python tools/memory_ask/main.py "一共多少张照片"
python tools/memory_ask/main.py "表情里没有哭吗"
python tools/memory_ask/main.py "第一次哭是什么时候"
python tools/memory_ask/main.py "面面4岁时在哪个地方待的时间最长"
python tools/memory_ask/main.py "面面几岁了"
python tools/memory_ask/main.py "面面最近在哪里玩"
python tools/memory_ask/main.py "面面最近去哪里了，列出最后10张"
```

默认回答里带 **file:// 可点击链接**（Cursor / 终端支持时）；不需要链接时加 `--no-links`。

**调试（看内部查到了什么）：**

```bash
python tools/memory_ask/main.py "面面几岁了" --debug
```

---

## 四、两台 Mac 怎么协作

| 机器 | 适合做什么 |
|------|------------|
| **有 Ollama 的家用 Mac** | `photo2json`（重活）、`memory_index sync`、`memory_ask` |
| **另一台（如外出用的）** | 改代码、轻量查询；没有 Ollama 也能 `sync` 和模板问答 |

**同步数据：** 拷贝 `data/photos/` + `data/memory/` + `data/.geocode_cache.json` + **`data/memory_annotations.json`**（若有；事件「补意义」与故事）。  
到任一台 Mac 上执行：

```bash
python tools/memory_index/main.py sync
python tools/memory_events/main.py sync   # 会从 memory_annotations.json 灌标注并重挂
```

`memorygraph.db` 可以不拷，到了再 sync。**不要只靠拷 db 传意义**——意义真源是 `memory_annotations.json`。

公司机若已有 overlay 但还没有该文件，先导出再同步：

```bash
python tools/memory_events/main.py export-annotations
# 或直接 sync 一次也会 bootstrap 写出文件
```

---

## 五、注意事项

### 必须遵守

1. **JSON 是照片唯一数据源** — SQLite 丢了不怕，`sync` 能重建照片索引。  
   事件「补意义」/ 故事的真源是 `data/memory_annotations.json`（与 `.geocode_cache.json` 同级，跨机必拷）。
2. **单张失败不中断整批** — photo2json 会继续处理下一张，留意终端 WARNING。
3. **Ollama 要先启动** — 否则 scene/tags 为空，Agent 会走模板兜底，答案偏干。
4. **`.env` 不要提交 git** — 已在 `.gitignore` 里；Key 只放本地。
5. **手改 JSON 请加标记** — 在 JSON 里加 `"manual_edit": true`，批处理默认不会覆盖。

### 性能与可选开关

| 情况 | 处理 |
|------|------|
| CLIP 首次下载很慢（~300MB） | 等它下完；或 `CLIP_ENABLED=false` 先跳过着衣兜底 |
| 只想测人脸 + Ollama，不要 CLIP | `.env` 设 `CLIP_ENABLED=false` |
| Ollama 视觉太慢 | 可先 `OLLAMA_VISION_ENABLED=false`，之后 `--force` 重跑 |
| 无 AMAP_KEY | location 保留坐标，问答仍可用，只是没有中文地址 |

### 怎么判断 JSON 质量 OK

打开任意 `data/memory/*.json` 检查：

| 字段 | 正常时应有什么 |
|------|----------------|
| `people` | 识别到的人有 `name`、`confidence` |
| `scene` | 一句话场景（Ollama 成功时有内容） |
| `tags` / `objects` | 数组里有词（Ollama 成功时） |
| `location` | 可读地名（如 古猗园）；逆地理 + 同日归一，**会随业务修正** |
| `location_coords` | EXIF 原始 GPS（`纬度,经度`），**不改动，留作聚合/地图** |
| `timestamp` | EXIF 拍摄时间 |

若 `scene`、`tags` 全空但 `people` 有值 → **多半是 Ollama 没连上**，不是人脸模块的问题。

---

## 六、常见问题

### `Connection refused` / Ollama 请求失败

```bash
ollama serve          # 或确认菜单栏 Ollama 已运行
ollama list           # 模型名与 .env 一致？
curl http://127.0.0.1:11434/api/tags
```

### photo2json 很慢

正常现象。视觉模型逐张推理，可以先 `--input` 小目录试跑。

### memory_ask 回答里是坐标不是地址

1. `.env` 里 `AMAP_KEY` 是否已填并 export  
2. 重新跑 `photo2json --force` 让 location 写入 JSON，或问答时会临时调高德（有缓存）

### 面面几岁了不对

检查 `data/faces/registry.json` 里 `birth_date` 格式：`YYYY-MM-DD`。

### 想完全重来索引

```bash
rm data/memorygraph.db
python tools/memory_index/main.py sync
```

JSON 和原图不受影响。

---

## 七、命令速查

```bash
# 新导入照片一键（默认关 Ollama → 再用 --vision 分批）
./import_photos.sh --input data/photos/2026
./import_photos.sh --vision                  # 默认每次 1000 张，可反复跑

# 环境
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)

# 人脸库
python tools/face_enroll/main.py build

# 分析
python tools/photo2json/main.py
python tools/photo2json/main.py --force

# 索引
python tools/memory_index/main.py sync
python tools/memory_index/main.py stats

# 事件聚合（outing / 家 / 无时间按地点）
# 有时间：同日 + GPS≤800m；无 GPS 按同地名；manual_location 同日同名强制合并
# 无时间有地址：按 exact location 聚成 source=untimed_loc（不写假时间）；Vue 可筛「无时间地点」
python tools/memory_events/main.py sync
python tools/memory_events/main.py stats
python tools/memory_events/main.py list --limit 20

# 去重候选（只报告不删除）
# 字节重复 + 有时间连拍 + 无时间近哈希（dHash）；无时间列表按近哈希相邻便于补时间
python tools/memory_dedup/main.py --year 2024
python tools/memory_dedup/main.py --hash-only -o /tmp/dedup.txt
python tools/memory_dedup/main.py --burst-only --burst-seconds 3 --limit 50
python tools/memory_dedup/main.py --near-hamming 10   # 无时间近相似阈值（默认 10）
python tools/memory_dedup/main.py --no-near           # 跳过近哈希（更快）

# 问答（意图说明见 docs/agent-intents.md）
python tools/memory_ask/main.py "有多少张有表情的"
python tools/memory_ask/main.py "面面几岁了"
python tools/memory_ask/main.py "第一次哭是什么时候"
python tools/memory_ask/main.py "最近出去玩了哪些"

# 地址缓存 CLI
python tools/location_mapping/main.py help

# Vue Inspector（需先起 Desk API）
cd web && npm install && npm run dev
```

---

## 八、Vue Inspector 与地址纠错

**MemoryGraph Desk** 提供 FastAPI（`tools/memory_desk/main.py`）；**Vue Inspector**（`web/`）通过 Vite 代理连 Desk，用于浏览/改 JSON 与地址缓存。

### 启动

```bash
# 终端 1：Desk API（默认 8766；--auto-port 若端口占用）
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)
python tools/memory_desk/main.py --auto-port

# 终端 2：Vue 前端
cd web && npm install && npm run dev
# 浏览器打开 Vite 提示的地址（通常 http://127.0.0.1:5173）
```

Vite 会读 `data/.memory_desk_port` 或环境变量 `MEMORY_DESK_PORT` / `VITE_DESK_PORT` 决定代理目标。

### Vue 标签页

| 标签 | 作用 |
|------|------|
| 列表 | 浏览 memory JSON，进详情；**批量标人物**（写 JSON `people` 并 sync 索引） |
| 问答 | 左右布局：左提问/短答，右证据（缩略图/排行/到访日/出门事件）+ facts；点图进详情（**阶段 2** 打磨后端意图，见 [agent-intents.md](agent-intents.md)） |
| 事件 | 顶栏筛选 + 宽表 + 右侧详情（备注/照片）；故事为子视图 |
| 去重 | 字节重复 / 连拍 / 无时间近相似；无时间按近哈希相邻便于补时间；确认后删进 `.trash` |
| 详情 | 单条 JSON 树形查看；检测人脸 → 加入人脸库 |
| 批量改地址 | 按日期聚合，无 GPS 老照片手工填 location |
| 地址缓存 | 浏览/编辑 `.geocode_cache.json`，编辑时可看该坐标样本图 |
| 人脸库 | 注册成员、管理参考照、`face_enroll build` |
| 维护工具 | regeocode、backfill faces、sync 索引、**重建事件聚合** |
| 验证 | Schema 校验 |
| 健康报告 | 等同 `memory_stats` 摘要 |

🔜 尚未做：详情页单条改 `people[]`（列表批量标人物已有）。

### 地址纠错推荐流程

**有 GPS、地名不对**（家附近已拆 POI 时尤其适用）：

```
1. Vue「地址缓存」或 location_mapping CLI 改 .geocode_cache.json
2. python tools/photo2json/main.py --regeocode-locations --no-normalize-after
3. python tools/memory_index/main.py sync
4. python tools/memory_events/main.py sync   # 地点变更后推荐
```

**拆开合并过的短地名**（让同一坐标重新走高德）：

```bash
python tools/location_mapping/main.py delete-by-location 河滨香景园 馨越公寓
python tools/photo2json/main.py --regeocode-locations --no-normalize-after
python tools/memory_index/main.py sync
python tools/memory_events/main.py sync
```

**清理坏缓存 / 迁移旧版：**

```bash
python tools/location_mapping/main.py migrate --dry-run
python tools/location_mapping/main.py delete-incomplete --dry-run   # 无 formatted_address 的条目
python tools/location_mapping/main.py clear-manual --dry-run         # 清除 JSON 的 manual_location
```

`location_mapping` 其它命令：`list`、`search`、`update`、`delete`、`add`、`export`、`import`、`apply-canonical`。详见：

```bash
python tools/location_mapping/main.py help
```

**无坐标**：在 Vue「批量改地址」按日填写；写入后 JSON 带 `manual_location: true`，regeocode 会跳过。

---

## 九、Desk 与辅助工具

### MemoryGraph Desk（API + 简易 HTML）

Desk 除供 Vue 代理外，也自带简易页面（搜文件、按人物、问答、删除）：

```bash
python tools/memory_desk/main.py
# 默认 http://127.0.0.1:8766/（Mac Hub 占 8765）
# 端口被占用时：--auto-port 或直接用已运行的地址
```

| 功能 | 说明 |
|------|------|
| REST API | `/api/memory/*`、`/api/geocode/cache/*`、`/api/ask` 等，供 Vue Inspector |
| 按人物搜照片 | 查 JSON `people`，需 `memory_index sync` |
| 文件搜索 | 按文件名搜 `photos` / `memory` / `faces` |
| 记忆问答 | 等同 `memory_ask`；Vue「问答」Tab 展示短答 + facts 证据 |
| 删除 | 原图 + JSON → `data/.trash/`，索引即时清除；**不删** `faces/` 参考照 |

### 其他 CLI

```bash
# 数据健康（vision / faces 覆盖率、按年待补数量）
python tools/memory_stats/main.py
python tools/memory_stats/main.py --year 2025

# 按文件名搜索 + 打开（Desk 的 CLI 版）
python tools/find/main.py IMG_3844 --open
python tools/find/main.py IMG_3844 -i    # 交互模式
```

人脸库 cluster / `from-photo` 等见 [data/faces/README.md](../data/faces/README.md)。

---

## 十、相关文档

- [README.md](../README.md) — 项目概览
- [AGENTS.md](../AGENTS.md) — 架构约束与模块职责
- [architecture.md](architecture.md) — 双端分工与隐私边界
- [data/README.md](../data/README.md) — CLIP 衣着兜底说明
