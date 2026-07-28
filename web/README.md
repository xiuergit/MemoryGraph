# MemoryGraph Inspector（Vue）

本地 Web 前端，连接 **MemoryGraph Desk** API，用于浏览/校验 `data/memory/*.json` 和管理 `.geocode_cache.json` 地址缓存。

## 前置

1. Python 虚拟环境与 Desk API 已就绪（见项目根 [README.md](../README.md)）
2. Node.js 18+（用于 Vite）

## 启动

```bash
# 终端 1：Desk API
cd /path/to/MemoryGraph
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)
python tools/memory_desk/main.py --auto-port

# 终端 2：Vue 开发服务器
cd web
npm install
npm run dev
```

浏览器打开 Vite 提示的地址（通常 `http://127.0.0.1:5173`）。

Vite 将 `/api` 和 `/photos` 代理到 Desk。端口优先级：

1. `data/.memory_desk_port`（Desk `--auto-port` 写入）
2. 环境变量 `MEMORY_DESK_PORT` 或 `VITE_DESK_PORT`
3. 默认 `8766`

## 功能标签

| 标签 | 说明 |
|------|------|
| 列表 | 分页浏览 memory JSON |
| 详情 | 单条 JSON 树形查看；**检测人脸 → 加入人脸库** |
| 批量改地址 | 按日期聚合，无 GPS 照片手工填 location |
| 地址缓存 | 编辑 `.geocode_cache.json`，含坐标样本图 |
| **维护工具** | 改完缓存/人脸后：regeocode、backfill faces、sync 索引 |
| 验证 | Schema 校验 |
| 健康报告 | vision / faces 覆盖率等 |

改完地址缓存后，在终端执行：

```bash
python tools/photo2json/main.py --regeocode-locations --no-normalize-after
python tools/memory_index/main.py sync
```

详见 [docs/operations.md](../docs/operations.md) 第八节。

## 构建（可选）

```bash
npm run build
npm run preview
```

生产构建仍需要 Desk API 在本地运行。

## 技术栈

- Vue 3 + Vite
- Element Plus
