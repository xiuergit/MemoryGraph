# 运行时数据目录（不进 git）

将原图放入 `photos/`，JSON 输出到 `memory/`。

## 目录说明

| 路径 | 说明 | 能否删了重建 |
|------|------|--------------|
| `photos/` | 原图 | ❌ 核心资产 |
| `memory/*.json` | 结构化记忆（唯一数据源） | ⚠️ 删了要重跑 photo2json |
| `faces/` | 人脸参考照 + registry | ⚠️ 删了要重注册 |
| `memorygraph.db` | SQLite 检索索引（含 events 表） | ✅ `memory_index sync` + `memory_events sync` 重建 |
| `memory_annotations.json` | 事件意义 / 故事真源 | ⚠️ 手写；丢了意义没了（可从有标注的机器拷回） |
| `.geocode_cache.json` | 高德逆地理缓存 | ✅ 可删，会重新请求 |
| `cache/outfit/` | CLIP 当日穿搭向量 | ✅ 可删，会重新计算 |

## 衣着兜底（CLIP，默认关闭「猜人」）

同一天内，**仅在高置信人脸（≥0.55）认出后**可选缓存衣着向量到 `data/cache/outfit/YYYY-MM-DD.json`。

**未匹配人脸 → 衣着比对** 极易误识别（背影、动物园等同款衣服），默认 **关闭**（`OUTFIT_FALLBACK_ENABLED=false`）。JSON 里 `match_method: "outfit"` 即此类结果，应批量清理。

```bash
# 预览将清理多少
python tools/photo2json/main.py --strip-outfit-matches --dry-run

# 执行清理 + 删衣着缓存
python tools/photo2json/main.py --strip-outfit-matches
python tools/memory_index/main.py sync
```

若确需开启衣着猜人（不推荐）：

```bash
export OUTFIT_FALLBACK_ENABLED=true
export OUTFIT_MATCH_THRESHOLD=0.90
```

安装依赖：

```bash
pip install open-clip-torch torch torchvision -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**卡在 `Loaded built-in ViT-B-32 model config`？**  
这是在**下载 CLIP 权重（约 300MB）**，不是死机。可：

```bash
# 国内镜像（写入 .env 或 export）
export HF_ENDPOINT=https://hf-mirror.com
python tools/photo2json/main.py

# 或先关掉衣着兜底，人脸/Ollama 照常
export CLIP_ENABLED=false
python tools/photo2json/main.py
```

下完后会显示 `CLIP 权重就绪，耗时 XXs`，以后不再下载。

手改过的 JSON 请加 `"manual_edit": true`，批处理不会覆盖。

```bash
export AMAP_KEY=你的Key   # 或写入项目根目录 .env
python tools/photo2json/main.py --force
```

同步索引、事件与问答：

```bash
python tools/memory_index/main.py sync
python tools/memory_events/main.py sync
python tools/memory_ask/main.py "最近出去玩了哪些"
```

详细流程见 [docs/operations.md](../docs/operations.md)。
