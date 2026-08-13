# MemoryGraph iOS（家庭消费端）

小朋友 / 家人用的 **问答 + 按人物看照片** 客户端。连家里 Mac 上的 Memory Desk，**不做**上传、改地址、标人物等工具能力（那些继续用 Vue Inspector）。

## 功能（壳 / P0）

| Tab | 能力 |
|-----|------|
| **问问** | **点圆钮说话，说完再点一下**；或点彩色快捷句；答案大字 + 再听一遍；照片横滑大图 |
| **谁** | `GET /api/face/registry` 选人 → `GET /api/memory/list?person=` 翻照片 → 大图详情 |
| **设置** | Mac IP / 端口、连通检测、儿童友好字号、自动朗读 |

**未做（下一版，非上传）：** 出门事件 Tab、画作集、Bonjour 发现；证据面板向 Web 对齐（排行 / 出门 / 故事等）。

语音：`Speech` + `AVSpeechSynthesizer`，设备端完成；首次会要麦克风与语音识别权限。

> **采集**：本 App **不做**上传。原图继续「导出到 Mac」+ `photo2json`。项目 **阶段 2** 焦点是修问答（后端 Agent），不是 iOS 采集。

## 打开工程

```bash
open apps/ios/MemoryGraph.xcodeproj
```

- 最低系统：**iOS 17**
- 设备：**iPhone + iPad**（`TARGETED_DEVICE_FAMILY = 1,2`）
- 依赖：**零第三方**（`URLSession` + SwiftUI + `AsyncImage`）
- 可选：装 [XcodeGen](https://github.com/yonaskolb/XcodeGen) 后可用同目录 `project.yml` 重新生成工程

真机调试：Signing 选自己的 Team；模拟器可直接跑（Desk 若在本机，设置里填 `127.0.0.1`）。

## 连 Mac Desk

```bash
# Mac：局域网可访问（手机不是本机回环）
python tools/memory_desk/main.py --host 0.0.0.0 --auto-port
```

App 设置里填 Mac 的局域网 IP + 端口（默认 **8766**）。同一 Wi‑Fi；Info.plist 已开 `NSAllowsLocalNetworking`。

| 客户端 | Desk API |
|--------|----------|
| 连通探测 | `GET /api/memory/years` |
| 问答 | `POST /api/ask` |
| 人物 | `GET /api/face/registry` |
| 按人照片 | `GET /api/memory/list?person=&page=` |
| 缩略图 / 大图 | `GET /api/preview?path=&size=` |

## 目录

```
apps/ios/
├── MemoryGraph.xcodeproj/
├── project.yml                 # XcodeGen 可选
├── README.md
└── MemoryGraph/
    ├── MemoryGraphApp.swift
    ├── RootTabView.swift
    ├── Info.plist
    ├── Assets.xcassets/
    ├── Models/
    ├── Services/               # AppSettings, DeskAPIClient
    └── Views/
        ├── Ask/
        ├── People/
        └── Shared/             # 网格、详情、设置、连接条
```

## 与采集上传的关系

本壳 **intentionally 不包含** 上传。采集用「导出到 Mac」；`hub/mac_server` 骨架暂不推进。管理 / 纠错继续用 Vue Inspector。
