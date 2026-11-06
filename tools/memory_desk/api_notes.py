"""Desk 接口说明：查什么、现在谁在调。

写在路由登记之后，盖到 Swagger / ReDoc 上。
新增路由要在这里补一行，否则启动时会报缺说明。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

# 不给 FastAPI 自己的文档路由写说明。
_SKIP = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}

TAG_ORDER: list[dict[str, str]] = [
    {"name": "问答", "description": "问记忆。Vue 问答页、iOS 问问。"},
    {"name": "浏览", "description": "列表、详情、缩略图、原片。"},
    {"name": "回家上传", "description": "iOS 家长模式把原图、旁白、故事、课表同步回 Mac。"},
    {"name": "事件与故事", "description": "出门事件、意义、故事。主要是 Vue 事件页。"},
    {"name": "分享", "description": "剪纸排版、暑假分享页。"},
    {"name": "整理", "description": "删除、去重、改地址 / 人物 / 时间、校验、健康报告。"},
    {"name": "地址缓存", "description": "逆地理缓存。Vue 地址缓存页。"},
    {"name": "人脸", "description": "人脸库。Vue 人脸库；名单也给 iOS「谁」。"},
    {"name": "维护", "description": "入库、补全、同步索引。Vue 维护工具。"},
    {"name": "知识", "description": "Inspector 知识页读写 docs/。"},
    {"name": "Desk 页", "description": "Desk 自带的简易网页，不是 Vue，也不是 iOS。"},
]

# (方法, 路径) -> (分组, 这一条做什么, 现在谁在调)
NOTES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("GET", "/"): (
        "Desk 页",
        "简易搜索页",
        "浏览器打开 Desk 根地址时的那一页",
    ),
    ("GET", "/api/search"): (
        "Desk 页",
        "按文件名搜原图、memory JSON、人脸参考照",
        "Desk 简易页",
    ),
    ("GET", "/api/search-person"): (
        "Desk 页",
        "按人物名搜照片（走索引）",
        "Desk 简易页",
    ),
    ("POST", "/api/delete"): (
        "Desk 页",
        "按 photo_id 或路径删除一条（进回收站）",
        "Desk 简易页。Vue 删多条走 /api/delete/batch",
    ),
    ("POST", "/api/ask"): (
        "问答",
        "记忆问答：短答、事实、证据、追问",
        "Vue 问答、iOS 问问",
    ),
    ("GET", "/api/ask/checklist"): (
        "问答",
        "读问答错题本",
        "Vue 问答",
    ),
    ("PATCH", "/api/ask/checklist/{item_id}"): (
        "问答",
        "改错题状态或备注",
        "Vue 问答",
    ),
    ("POST", "/api/ask/checklist"): (
        "问答",
        "加一条错题",
        "Vue 问答",
    ),
    ("DELETE", "/api/ask/checklist/{item_id}"): (
        "问答",
        "删一条错题",
        "接口已留，问答页还没有删除按钮",
    ),
    ("GET", "/api/preview"): (
        "浏览",
        "缩略图或按边长压缩的 JPEG",
        "Vue 各页缩略图、iOS 照片",
    ),
    ("GET", "/api/media"): (
        "浏览",
        "原图 / 原视频流，可拖进度",
        "Vue 详情页播放",
    ),
    ("GET", "/api/memory/list"): (
        "浏览",
        "分页查记忆：人物、年份、地点、文件夹、媒体类型",
        "Vue 列表、批量改地址；iOS 谁 / 逛图",
    ),
    ("GET", "/api/memory/detail"): (
        "浏览",
        "读一条 memory JSON",
        "Vue 详情",
    ),
    ("GET", "/api/memory/years"): (
        "浏览",
        "有数据的年份",
        "Vue 列表、去重；iOS 用它探测 Desk 是否在线",
    ),
    ("GET", "/api/memory/folders"): (
        "浏览",
        "photos/ 下出现过的文件夹",
        "Vue 列表",
    ),
    ("GET", "/api/memory/locations"): (
        "浏览",
        "库里的地名，按张数排序",
        "Vue 列表、详情、批量改地址、事件",
    ),
    ("GET", "/api/memory/dates"): (
        "浏览",
        "有照片的日期列表",
        "页面还没接",
    ),
    ("GET", "/api/memory/artwork"): (
        "浏览",
        "某人相关画作（按事件关联，不要求画面上标了这个人）",
        "Vue / iOS 还没接",
    ),
    ("GET", "/api/on-this-day"): (
        "浏览",
        "往年今天：同月同日的代表照片",
        "iOS 问问",
    ),
    ("GET", "/api/day-slice"): (
        "浏览",
        "某一天的全部记忆（含单张、视频、旁白、故事）",
        "Vue / iOS 还没接",
    ),
    ("POST", "/api/open"): (
        "浏览",
        "在 Mac 上用系统打开原文件",
        "Vue 详情",
    ),
    ("POST", "/api/media/ingest"): (
        "回家上传",
        "收一张原图，写入 photos/ 并建 JSON",
        "iOS 家长模式",
    ),
    ("POST", "/api/media/describe"): (
        "回家上传",
        "按 photo_id 写入旁白 user_note",
        "iOS 家长模式",
    ),
    ("POST", "/api/stories/upsert"): (
        "回家上传",
        "按 story_id 创建或更新故事（可先空着链接）",
        "iOS 家长模式",
    ),
    ("GET", "/api/mobile/plan"): (
        "回家上传",
        "读 Mac 上备份的课表和日记",
        "iOS 家长模式",
    ),
    ("PUT", "/api/mobile/plan"): (
        "回家上传",
        "用手机上的课表和日记替换 Mac 备份",
        "iOS 家长模式",
    ),
    ("POST", "/api/events/sync"): (
        "事件与故事",
        "按照片重新聚合出门 / 在家事件",
        "Vue 事件、维护工具",
    ),
    ("GET", "/api/events/stats"): (
        "事件与故事",
        "事件数量统计",
        "Vue 事件",
    ),
    ("GET", "/api/events"): (
        "事件与故事",
        "事件列表：日、地点、人物、关键词",
        "Vue 事件",
    ),
    ("GET", "/api/events/locations"): (
        "事件与故事",
        "事件里出现过的地点",
        "Vue 事件筛选",
    ),
    ("GET", "/api/events/years"): (
        "事件与故事",
        "事件覆盖的年份",
        "Vue 事件筛选",
    ),
    ("GET", "/api/events/{event_id}"): (
        "事件与故事",
        "一条事件的成员照片和意义",
        "Vue 事件、问答里点开事件",
    ),
    ("GET", "/api/events/{event_id}/overlay"): (
        "事件与故事",
        "只读这条事件的意义",
        "页面改意义用 PUT / DELETE，这条目前没有单独调用",
    ),
    ("PUT", "/api/events/{event_id}/overlay"): (
        "事件与故事",
        "写事件意义（标题、正文、标签）",
        "Vue 事件",
    ),
    ("DELETE", "/api/events/{event_id}/overlay"): (
        "事件与故事",
        "清掉事件意义",
        "Vue 事件",
    ),
    ("GET", "/api/stories"): (
        "事件与故事",
        "故事列表",
        "Vue 事件",
    ),
    ("POST", "/api/stories"): (
        "事件与故事",
        "新建故事",
        "Vue 事件",
    ),
    ("GET", "/api/stories/{story_id}"): (
        "事件与故事",
        "读一条故事",
        "Vue 事件",
    ),
    ("PUT", "/api/stories/{story_id}"): (
        "事件与故事",
        "改一条故事",
        "Vue 事件",
    ),
    ("DELETE", "/api/stories/{story_id}"): (
        "事件与故事",
        "删一条故事",
        "Vue 事件",
    ),
    ("POST", "/api/print-outbox"): (
        "分享",
        "把选中的照片拷进剪纸目录，返回排版链接",
        "Vue 列表、事件",
    ),
    ("GET", "/api/story-circle/slots"): (
        "分享",
        "暑假分享页六格的短标题",
        "页面还没单独调；勾选照片走 from-photos",
    ),
    ("GET", "/api/story-circle"): (
        "分享",
        "分享页节点数据（标题、顺序、张数）",
        "页面还没单独调；打开的是 /story-circle",
    ),
    ("GET", "/story-circle"): (
        "分享",
        "A4 分享页（浏览器里打印）",
        "Vue 列表、事件生成后用浏览器打开",
    ),
    ("POST", "/api/story-circle/from-photos"): (
        "分享",
        "用勾选的照片生成分享页",
        "Vue 列表、事件",
    ),
    ("POST", "/api/story-circle/open"): (
        "分享",
        "按事件或照片生成分享页并返回地址",
        "接口已留，Vue 目前走 from-photos",
    ),
    ("POST", "/api/delete/batch"): (
        "整理",
        "按 photo_id 批量删除（进回收站）",
        "Vue 列表、事件、去重",
    ),
    ("GET", "/api/dedup/report"): (
        "整理",
        "重复候选：相同文件、连拍、近相似。只报告，不删除",
        "Vue 去重",
    ),
    ("POST", "/api/memory/batch-update-location"): (
        "整理",
        "按日期范围或旧地名，批量改 location",
        "Vue 批量改地址",
    ),
    ("POST", "/api/memory/batch-update-people"): (
        "整理",
        "给选中的照片追加或替换人物",
        "Vue 列表",
    ),
    ("POST", "/api/memory/batch-update-location-by-ids"): (
        "整理",
        "给选中的照片改地名",
        "Vue 列表、事件",
    ),
    ("POST", "/api/memory/batch-update-timestamp"): (
        "整理",
        "给选中的照片改拍摄时间",
        "Vue 列表",
    ),
    ("PUT", "/api/memory/update"): (
        "整理",
        "改一条的地点、人物、场景等手改字段",
        "Vue 详情",
    ),
    ("PUT", "/api/memory/transcript"): (
        "整理",
        "保存视频字幕草稿，或确认后让问答能用到",
        "Vue 详情",
    ),
    ("GET", "/api/memory/validate"): (
        "整理",
        "用 JSON Schema 校验一条或全部 memory",
        "Vue 验证",
    ),
    ("GET", "/api/memory/stats"): (
        "整理",
        "库健康：张数、缺字段、人脸库、索引",
        "Vue 健康报告",
    ),
    ("GET", "/api/geocode/cache/stats"): (
        "地址缓存",
        "逆地理缓存条数和版本",
        "Vue 地址缓存",
    ),
    ("GET", "/api/geocode/cache/regions"): (
        "地址缓存",
        "缓存里的省市区",
        "Vue 地址缓存",
    ),
    ("GET", "/api/geocode/cache"): (
        "地址缓存",
        "缓存列表，可按地名或坐标搜",
        "Vue 地址缓存",
    ),
    ("GET", "/api/geocode/cache/samples"): (
        "地址缓存",
        "某条缓存对应的样例照片",
        "Vue 地址缓存",
    ),
    ("PUT", "/api/geocode/cache/coords"): (
        "地址缓存",
        "按坐标改正地名",
        "Vue 地址缓存",
    ),
    ("PUT", "/api/geocode/cache/location"): (
        "地址缓存",
        "按现有地名批量改正",
        "Vue 地址缓存",
    ),
    ("DELETE", "/api/geocode/cache/coords"): (
        "地址缓存",
        "删一条坐标缓存",
        "Vue 地址缓存",
    ),
    ("GET", "/api/face/registry"): (
        "人脸",
        "家庭成员名单（中文名、id、出现次数）",
        "Vue 选人、iOS 谁",
    ),
    ("GET", "/api/face/detect"): (
        "人脸",
        "检测一张照片里的脸，并标出是否已在库里",
        "Vue 人脸登记",
    ),
    ("POST", "/api/face/enroll"): (
        "人脸",
        "从照片裁一张脸写入人脸库并重建索引",
        "Vue 人脸登记",
    ),
    ("GET", "/api/face/people"): (
        "人脸",
        "成员列表：参考照数量、识别阈值",
        "Vue 人脸库",
    ),
    ("GET", "/api/face/people/{person_id}"): (
        "人脸",
        "一个成员的资料和参考照",
        "Vue 人脸库",
    ),
    ("PUT", "/api/face/people/{person_id}"): (
        "人脸",
        "改成员资料并重建索引",
        "Vue 人脸库",
    ),
    ("DELETE", "/api/face/people/{person_id}/refs"): (
        "人脸",
        "删一张参考照并重建索引",
        "Vue 人脸库",
    ),
    ("POST", "/api/face/rebuild-index"): (
        "人脸",
        "按现有参考照重建 index.json",
        "Vue 人脸库",
    ),
    ("GET", "/api/tools/config"): (
        "维护",
        "当前阈值和模型开关，用来确认 .env",
        "Vue 维护工具",
    ),
    ("POST", "/api/tools/sync-index"): (
        "维护",
        "memory JSON 同步进 SQLite",
        "Vue 维护工具",
    ),
    ("POST", "/api/tools/regeocode-locations"): (
        "维护",
        "把地址缓存写回 JSON 的 location",
        "Vue 维护工具",
    ),
    ("POST", "/api/tools/rebuild-face-index"): (
        "维护",
        "扫描 data/faces/ 重建人脸索引",
        "Vue 维护工具",
    ),
    ("POST", "/api/tools/backfill-faces"): (
        "维护",
        "按原图重跑人脸，写回 people",
        "Vue 维护工具",
    ),
    ("GET", "/api/tools/media-pending"): (
        "维护",
        "某年还有多少照片 / 视频没有 JSON",
        "Vue 维护工具",
    ),
    ("GET", "/api/tools/job-status"): (
        "维护",
        "当前入库或补全任务的进度",
        "Vue 维护工具",
    ),
    ("POST", "/api/tools/job-cancel"): (
        "维护",
        "让当前任务在这一条做完后停下",
        "Vue 维护工具",
    ),
    ("POST", "/api/tools/process-photos"): (
        "维护",
        "为还没有 JSON 的新照片入库",
        "Vue 维护工具",
    ),
    ("POST", "/api/tools/process-videos"): (
        "维护",
        "为还没有 JSON 的新视频入库",
        "Vue 维护工具",
    ),
    ("POST", "/api/tools/backfill-transcript"): (
        "维护",
        "给已有视频补字幕",
        "Vue 维护工具",
    ),
    ("GET", "/api/docs"): (
        "知识",
        "知识菜单：docs/ 下的 Markdown 分组",
        "Vue 知识",
    ),
    ("GET", "/api/docs/file"): (
        "知识",
        "读一篇 docs/ 里的 Markdown",
        "Vue 知识",
    ),
    ("PUT", "/api/docs/file"): (
        "知识",
        "保存一篇已有 Markdown",
        "Vue 知识",
    ),
    ("POST", "/api/docs/file"): (
        "知识",
        "在 docs/ai-study/ 新建一篇笔记",
        "Vue 知识",
    ),
}


def apply_api_notes(app: FastAPI) -> None:
    """把 NOTES 写到路由上。缺一条或多一条都直接失败，避免文档悄悄过期。"""
    app.openapi_tags = TAG_ORDER
    app.description = (
        "本机记忆服务。Vue Inspector 和 iOS 打的都是这些接口。\n\n"
        "顶部搜索框按路径和摘要过滤，例如 `iOS`、`错题`、`/api/ask`。\n"
        "摘要里的「用在」是当前调用方。展开后是原来的接口说明。\n"
        "另一份带左侧搜索的阅读页在 /redoc。"
    )

    seen: set[tuple[str, str]] = set()
    missing: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in _SKIP:
            continue
        methods = sorted(m for m in (route.methods or set()) if m != "HEAD")
        if len(methods) != 1:
            missing.append(f"{','.join(methods) or '?'} {route.path}")
            continue
        key = (methods[0], route.path)
        seen.add(key)
        note = NOTES.get(key)
        if note is None:
            missing.append(f"{key[0]} {key[1]}")
            continue
        tag, summary, used = note
        old_summary = (route.summary or "").strip()
        old_desc = (route.description or "").strip()
        route.tags = [tag]
        route.summary = f"{summary}。用在：{used}"
        parts: list[str] = []
        if old_summary and old_summary not in summary:
            parts.append(old_summary)
        if old_desc:
            parts.append(old_desc)
        parts.append(f"用在：{used}")
        route.description = "\n\n".join(parts)

    extra = [f"{method} {path}" for method, path in NOTES if (method, path) not in seen]
    if missing or extra:
        lines = []
        if missing:
            lines.append("缺说明: " + "; ".join(missing))
        if extra:
            lines.append("说明没有对应路由: " + "; ".join(extra))
        raise RuntimeError("；".join(lines))
