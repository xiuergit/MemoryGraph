# 运行时数据目录（不进 git）

将原图放入 `photos/`，JSON 输出到 `memory/`。

## 目录说明

| 路径 | 说明 | 能否删了重建 |
|------|------|--------------|
| `photos/` | 原图 | ❌ 核心资产 |
| `memory/*.json` | 结构化记忆（唯一数据源） | ⚠️ 删了要重跑 photo2json |
| `faces/` | 人脸参考照 + registry | ⚠️ 删了要重注册 |
| `memorygraph.db` | SQLite 检索索引 | ✅ `memory_index sync` 重建 |
| `.geocode_cache.json` | 高德逆地理缓存 | ✅ 可删，会重新请求 |
| `cache/outfit/` | CLIP 当日穿搭向量 | ✅ 可删，会重新计算 |

## 衣着兜底（CLIP）

同一天内：
1. **脸认出**某人 → 缓存当日穿搭向量到 `data/cache/outfit/YYYY-MM-DD.json`
2. **脸不清** → 与当日缓存比对，命中则 `match_method: "outfit"`（置信度低于人脸）

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

同步索引与问答：

```bash
python tools/memory_index/main.py sync
python tools/memory_ask/main.py "最近的照片"
```

详细流程见 [docs/operations.md](../docs/operations.md)。
