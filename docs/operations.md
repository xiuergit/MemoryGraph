# MemoryGraph 回家操作手册

> 适用场景：隔一段时间把 iPhone 照片导出到 Mac，批量分析 → 建索引 → 问答。  
> iOS App **不是必须**；家用 Mac + Ollama 即可完成主流程。

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
memory_ask（自然语言问答）
```

**数据分工（重要）：**

| 路径 | 是什么 | 能否删了重建 |
|------|--------|--------------|
| `data/photos/` | 原图 | ❌ 核心资产，别删 |
| `data/memory/*.json` | 结构化记忆（唯一数据源） | ⚠️ 删了要重跑 photo2json |
| `data/memorygraph.db` | 检索索引 | ✅ 随时 `sync` 重建 |
| `data/.geocode_cache.json` | 高德地址缓存 | ✅ 可删，会重新请求 |

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
# 参考照目录：data/faces/baby/ 等，放 1～3 张清晰正脸
cp data/faces/registry.example.json data/faces/registry.json
# 编辑 registry.json：姓名、birth_date、role

python tools/face_enroll/main.py
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

### 步骤 1：放入原图

把从 iPhone 导出的照片放进 `data/photos/`，可按年分子目录，例如：

```
data/photos/2025/IMG_3832.HEIC
data/photos/2026/IMG_3855.HEIC
```

支持格式：`.jpg` `.jpeg` `.png` `.heic` `.heif`

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

**耗时说明：** 每张图要跑 Ollama 视觉 + 人脸 +（可选）CLIP，几十秒到几分钟都正常，批量请耐心等。

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

```bash
python tools/memory_ask/main.py "最近的照片"
python tools/memory_ask/main.py "面面几岁了"
python tools/memory_ask/main.py "面面最近在哪里玩"
```

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

**同步数据：** 拷贝整个 `data/photos/` + `data/memory/` 即可（U 盘、AirDrop、网盘都行）。  
到任一台 Mac 上执行 `python tools/memory_index/main.py sync` 重建索引。

`memorygraph.db` 可以不拷，到了再 sync。

---

## 五、注意事项

### 必须遵守

1. **JSON 是唯一数据源** — SQLite 丢了不怕，`sync` 能重建。
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
# 环境
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)

# 人脸库
python tools/face_enroll/main.py

# 分析
python tools/photo2json/main.py
python tools/photo2json/main.py --force

# 索引
python tools/memory_index/main.py sync
python tools/memory_index/main.py stats

# 问答
python tools/memory_ask/main.py "最近的照片"
python tools/memory_ask/main.py "面面几岁了"
python tools/memory_ask/main.py "面面最近在哪里玩"
```

---

## 八、相关文档

- [README.md](../README.md) — 项目概览
- [AGENTS.md](../AGENTS.md) — 架构约束与模块职责
- [architecture.md](architecture.md) — 双端分工与隐私边界
- [data/README.md](../data/README.md) — CLIP 衣着兜底说明
