# Photo JSON Schema

MemoryGraph 的记忆原子协议。正式定义见 `photo.v1.json`。

- **Python 实现**：`hub/shared/schema.py`（须与此文件保持一致）
- **iOS 实现**：`apps/ios/` 中的 `PhotoJson` 模型（须与此文件保持一致）
- **版本升级**：新增 `photo.v2.json`，旧版 JSON 保留可读

## 字段分工

| 字段 | iOS 可填 | Mac Python 可填 |
|------|----------|-----------------|
| `schema_version`, `photo_id`, `device_id` | ✅ | ✅ |
| `timestamp`, `source.*` | ✅（EXIF） | ✅ |
| `quality.face_detected` | ✅（Vision） | 可选 |
| `people`, `scene`, `location`, `objects`, `actions`, `emotion`, `tags` | 可先空 | ✅（本地模型） |
