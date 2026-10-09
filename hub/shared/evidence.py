"""问答证据合同：answer → media / event / story ids → JSON / 原片。

facts 仍按意图自由拼装；本模块从 facts 抽出统一 evidence，供 Desk / Vue / iOS
与「依据是什么」追问使用。不写库、不改 JSON 真源。
"""

from __future__ import annotations

from typing import Any


def infer_media_type(media_id: str, explicit: str = "") -> str:
    """优先用显式 media_type；否则按 id 后缀猜测（video=_v，audio=_a）。"""
    mt = str(explicit or "").strip().lower()
    if mt in ("photo", "video", "audio"):
        return mt
    pid = str(media_id or "").strip()
    if pid.endswith("_v"):
        return "video"
    if pid.endswith("_a"):
        return "audio"
    return "photo"


def media_noun(media_type: str = "", *, count: int = 1) -> str:
    """口语量词：照片 / 视频 / 音频 / 条记忆。"""
    mt = str(media_type or "").strip().lower()
    if mt == "video":
        return "个视频" if count != 1 else "视频"
    if mt == "audio":
        return "段音频" if count != 1 else "音频"
    if mt == "photo":
        return "张照片" if count != 1 else "照片"
    if count == 1:
        return "条记忆"
    return "条记忆"


def media_noun_for_mix(by_type: dict[str, int] | None, total: int) -> str:
    """混合媒体时的口语：「3 条记忆（照片 2、视频 1）」或「5 张照片」。"""
    counts = {k: int(v) for k, v in (by_type or {}).items() if int(v or 0) > 0}
    if not counts:
        return f"{total} 条记忆" if total else "0 条记忆"
    if len(counts) == 1:
        mt, n = next(iter(counts.items()))
        if mt == "photo":
            return f"{n} 张照片"
        if mt == "video":
            return f"{n} 个视频"
        if mt == "audio":
            return f"{n} 段音频"
        return f"{n} 条记忆"
    parts = []
    for mt in ("photo", "video", "audio"):
        n = counts.get(mt, 0)
        if not n:
            continue
        if mt == "photo":
            parts.append(f"照片 {n}")
        elif mt == "video":
            parts.append(f"视频 {n}")
        else:
            parts.append(f"音频 {n}")
    detail = "、".join(parts)
    return f"{total} 条记忆（{detail}）"


def _push_media(
    out: list[dict[str, Any]],
    seen: set[str],
    item: dict[str, Any] | None,
    *,
    cap: int,
) -> None:
    if not isinstance(item, dict) or len(out) >= cap:
        return
    mid = str(item.get("photo_id") or item.get("id") or "").strip()
    if not mid or mid in seen:
        return
    seen.add(mid)
    out.append(
        {
            "id": mid,
            "media_type": infer_media_type(mid, str(item.get("media_type") or "")),
            "timestamp": str(item.get("timestamp") or ""),
            "location": str(item.get("location") or ""),
            "scene": str(item.get("scene") or ""),
            "source_path": str(item.get("source_path") or ""),
        }
    )


def build_evidence(facts: dict[str, Any], *, media_cap: int = 200) -> dict[str, Any]:
    """从意图相关 facts 抽出统一证据结构。

    形状::

        {
          "media": [{id, media_type, timestamp, location, scene, source_path}],
          "events": [{id, day, location, photo_count}],
          "stories": [{id, title}],
          "counts": {
            "media": N, "events": N, "stories": N,
            "by_media_type": {"photo": n, "video": n, "audio": n}
          }
        }
    """
    media: list[dict[str, Any]] = []
    seen_media: set[str] = set()

    for key in ("photos", "sample_photos"):
        items = facts.get(key)
        if isinstance(items, list):
            for p in items:
                _push_media(media, seen_media, p, cap=media_cap)

    for key in ("photo", "first_visit", "last_visit"):
        _push_media(media, seen_media, facts.get(key), cap=media_cap)

    places = facts.get("places")
    if isinstance(places, list):
        for p in places:
            if isinstance(p, dict) and (p.get("photo_id") or p.get("id")):
                _push_media(media, seen_media, p, cap=media_cap)

    events_out: list[dict[str, Any]] = []
    seen_events: set[str] = set()
    for ev in facts.get("events") or []:
        if not isinstance(ev, dict):
            continue
        eid = str(ev.get("event_id") or ev.get("id") or "").strip()
        if not eid or eid in seen_events:
            continue
        seen_events.add(eid)
        events_out.append(
            {
                "id": eid,
                "day": str(ev.get("day") or ""),
                "location": str(ev.get("location") or ev.get("display_title") or ""),
                "photo_count": int(ev.get("photo_count") or 0),
            }
        )

    stories_out: list[dict[str, Any]] = []
    seen_stories: set[str] = set()
    for st in facts.get("stories") or []:
        if not isinstance(st, dict):
            continue
        sid = str(st.get("story_id") or st.get("id") or "").strip()
        if not sid or sid in seen_stories:
            continue
        seen_stories.add(sid)
        stories_out.append(
            {
                "id": sid,
                "title": str(st.get("title") or ""),
            }
        )

    by_type = {"photo": 0, "video": 0, "audio": 0}
    for m in media:
        mt = m.get("media_type") or "photo"
        if mt in by_type:
            by_type[mt] += 1
        else:
            by_type["photo"] += 1

    return {
        "media": media,
        "events": events_out,
        "stories": stories_out,
        "counts": {
            "media": len(media),
            "events": len(events_out),
            "stories": len(stories_out),
            "by_media_type": by_type,
        },
    }


def evidence_basis_bits(evidence: dict[str, Any] | None) -> list[str]:
    """供 explain_basis / basis_summary 的短句片段。"""
    if not isinstance(evidence, dict):
        return []
    counts = evidence.get("counts") or {}
    bits: list[str] = []
    media_n = int(counts.get("media") or 0)
    if media_n:
        bits.append(media_noun_for_mix(counts.get("by_media_type"), media_n))
    event_n = int(counts.get("events") or 0)
    if event_n:
        bits.append(f"出门事件 {event_n} 趟")
    story_n = int(counts.get("stories") or 0)
    if story_n:
        bits.append(f"故事 {story_n} 条")
    return bits


def evidence_id_samples(evidence: dict[str, Any] | None, *, limit: int = 5) -> dict[str, list[str]]:
    """抽样 id，便于 context 回传与「依据」展示。"""
    if not isinstance(evidence, dict):
        return {"media_ids": [], "event_ids": [], "story_ids": []}
    return {
        "media_ids": [str(m.get("id")) for m in (evidence.get("media") or [])[:limit] if m.get("id")],
        "event_ids": [str(e.get("id")) for e in (evidence.get("events") or [])[:limit] if e.get("id")],
        "story_ids": [str(s.get("id")) for s in (evidence.get("stories") or [])[:limit] if s.get("id")],
    }
