# MemoryGraph iOS App

iPhone 采集端：从相册选图、读取 EXIF、组装 JSON、通过局域网同步到 Mac。

## 职责

- 选照片（PhotosUI / PHPicker）
- 读取元数据：拍摄时间、尺寸
- 可选：Vision 检测人脸 → `quality.face_detected`
- 组装符合 `schemas/photo.v1.json` 的 JSON
- 通过 HTTP 上传到 Mac Hub：`POST http://<mac-ip>:8765/import`

## 不做

- 不跑视觉大模型（scene / objects 等由 Mac Python 补全）
- 不上传云端
- 不做复杂 UI（能用即可）

## Mac Hub 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 检查 Mac 服务是否在线 |
| POST | `/import` | multipart：`file`（原图）、可选 `json_payload`、`device_id` |

## 工程创建

在 Xcode 中新建 SwiftUI App，目标路径设为 `apps/ios/MemoryGraph/`。

`PhotoJson` 模型字段须与 `schemas/photo.v1.json` 一致。
