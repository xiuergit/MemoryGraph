# 运行时数据目录（不进 git）

将原图放入 `photos/`，JSON 输出到 `memory/`。

`location` 字段：优先从照片 EXIF GPS 读取坐标，若设置了环境变量 `AMAP_KEY` 会调用高德逆地理编码转为中文地址；未配置 Key 时保留坐标（如 `31.294597,121.314231`）。相同坐标会缓存在 `.geocode_cache.json`，避免重复请求。

```bash
export AMAP_KEY=你的Key   # 或写入项目根目录 .env
python tools/photo2json/main.py --force
```
