# MemoryGraph iOS（家庭消费端 + 家长 Outbox）

小朋友：**问问 + 看谁**。家长（设置里开「家长模式」）：**选图 / 旁白 / 故事 / 回家同步**到 Mac Desk。  
**不删系统相册**；不做公网、不做手机 AI。

## Tab

| Tab | 谁用 | 能力 |
|-----|------|------|
| **问问** | 小孩 | 语音/快捷句问答；答案朗读；证据图 |
| **看谁** | 小孩 | 人脸库选人 → 翻照片 |
| **待上传** | 家长模式 | 相册选图拷贝进沙盒；写旁白；同步队列 |
| **故事** | 家长模式 | 离线草稿（可无图）；挂 Outbox 图；同步 |
| **设置** | 共用 | Mac IP/端口、儿童字号、家长模式开关 |

同步顺序（Desk 可达时）：`media.ingest` → `media.describe` → `story.upsert`（links **只含已落地 photo_id**）。

## 打开工程

```bash
open apps/ios/MemoryGraph.xcodeproj
```

- 最低系统：**iOS 17**
- 设备：**iPhone + iPad**
- 依赖：零第三方（`URLSession` + SwiftUI + PhotosUI）
- 可选：装 [XcodeGen](https://github.com/yonaskolb/XcodeGen) 后用 `project.yml` 重生工程

真机：Signing 选 Team；相册权限文案已写在 Info.plist。

## 连 Mac Desk

```bash
python tools/memory_desk/main.py --host 0.0.0.0 --port 8766 --no-browser
```

设置里填 Mac 局域网 IP + 端口（默认 **8766**）。同一 Wi‑Fi；`NSAllowsLocalNetworking` 已开。

| 客户端 | Desk API |
|--------|----------|
| 连通探测 | `GET /api/memory/years` |
| 问答 / 人物 / 预览 | `/api/ask`、`/api/face/registry`、`/api/memory/list`、`/api/preview` |
| 回家上传 | `POST /api/media/ingest` |
| 旁白 | `POST /api/media/describe` |
| 故事 | `POST /api/stories/upsert` |

合同与后端阶段：[`docs/mobile-outbox.md`](../../docs/mobile-outbox.md)、[`docs/mobile-outbox-plan.md`](../../docs/mobile-outbox-plan.md)。

## 目录

```
apps/ios/
├── MemoryGraph.xcodeproj/
├── project.yml
├── README.md
└── MemoryGraph/
    ├── MemoryGraphApp.swift
    ├── RootTabView.swift
    ├── Info.plist
    ├── Models/          # Ask + OutboxModels
    ├── Services/        # DeskAPI、OutboxStore、OutboxSyncService…
    └── Views/
        ├── Ask/
        ├── People/
        ├── Outbox/      # 待上传、故事
        └── Shared/
```

## 家长怎么用（阶段 E）

1. 设置 → 打开 **家长模式**
2. **待上传**：选图（拷进 App）→ 点进写旁白（可选）
3. **故事**：可先无图写标题正文；需要配图就勾选 Outbox 里的图
4. 回家同一 Wi‑Fi，点 **回家同步到 Mac**
5. Mac 上 Vue / `data/photos` + `data/memory` 旁白 / 事件里的故事应可见

本地队列在 App 沙盒 `Documents/Outbox/`（manifest + 每图子目录），未解析的 `local_id` **不会**写入 Mac annotations links。
