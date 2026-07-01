# Photo JSON Schema

MemoryGraph 的记忆原子协议。正式定义见 `photo.v1.json`。

- **Python 实现**：`hub/shared/schema.py`（须与此文件保持一致）
- **iOS 实现**：`apps/ios/` 中的 `PhotoJson` 模型（须与此文件保持一致）
- **版本升级**：新增 `photo.v2.json`，旧版 JSON 保留可读

当前版本 **1.1**：在 1.0 基础上增加可选字段 `location_coords`（EXIF GPS 原始坐标）。

## 字段分工

| 字段 | iOS 可填 | Mac Python 可填 |
|------|----------|-----------------|
| `schema_version`, `photo_id`, `device_id` | ✅ | ✅ |
| `timestamp`, `source.*` | ✅（EXIF） | ✅ |
| `location_coords` | ✅（EXIF GPS） | ✅ |
| `location` | 可先空 | ✅（逆地理 + 同日归一） |
| `quality.face_detected` | ✅（Vision） | 可选 |
| `people`, `scene`, `objects`, `actions`, `emotion`, `tags` | 可先空 | ✅（本地模型） |
| `manual_edit` | ✅ | ✅（手改 JSON 时设为 true，批处理跳过） |

## location 与 location_coords

- **`location_coords`**：EXIF 原始 GPS（`"纬度,经度"`），写入后不再被文本覆盖
- **`location`**：人类可读地名（如「古猗园」），由高德逆地理 + 同日 GPS 聚类得出
