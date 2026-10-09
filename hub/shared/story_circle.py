"""暑期「分享页」：自选照片 → A4 蛇形大图 + 箭头（有起终点）。

默认蛇形排版（少格、图大）；也支持旧的圆环布局。
"""

from __future__ import annotations

import html
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from hub.shared.config import DATA_DIR, MEMORY_DB, MEMORY_DIR, SUPPORTED_EXTENSIONS
from hub.shared.photo_links import resolve_photo_path

LayoutKind = Literal["snake", "circle"]

# 试稿预设：少而清楚（约 6 格，蛇形才看得清）
# 短标题给人念：骑车 / 玩水 / 包饺子 / 图书馆 / 看画展 / 看非遗变脸
SUMMER_2026_STORY_CIRCLE: list[str] = [
    "evt_c2f27ba2ad67b470",  # 07-01 骑车
    "evt_4bdde43916b011bd",  # 07-04 图书馆
    "evt_df9856bb806d86e9",  # 07-05 玩水（汤连得）
    "evt_809831f9169c1f9f",  # 07-27 包饺子（库里备注是包寿司 party）
    "evt_76071efc74974988",  # 08-08 看画展
    "evt_503935f1daf222e5",  # 08-15 看非遗变脸
]

SUMMER_2026_STORY_TITLES: dict[str, str] = {
    "evt_c2f27ba2ad67b470": "骑车",
    "evt_4bdde43916b011bd": "图书馆",
    "evt_df9856bb806d86e9": "玩水",
    "evt_809831f9169c1f9f": "包饺子",
    "evt_76071efc74974988": "看画展",
    "evt_503935f1daf222e5": "看非遗变脸",
}

# 自选图时的讲述顺序（标题固定，照片由你勾选填入）
SUMMER_SHARE_SLOT_TITLES: list[str] = [
    "骑车",
    "玩水",
    "包饺子",
    "图书馆",
    "看画展",
    "看非遗变脸",
]

_MAX_NODES = 8
_JOB_DIR = DATA_DIR / "cache" / "story_circle_jobs"


@dataclass
class StoryCircleNode:
    event_id: str
    day: str
    title: str
    location: str
    photo_id: str
    source_path: str
    index: int  # 1-based


def _is_videoish(photo_id: str) -> bool:
    pid = photo_id.lower()
    return pid.endswith("_v") or "_v." in pid


def _pick_cover_photo(conn: sqlite3.Connection, event_id: str) -> tuple[str, str]:
    rows = conn.execute(
        "SELECT photo_id FROM event_photos WHERE event_id = ? ORDER BY sort_ts",
        (event_id,),
    ).fetchall()
    candidates: list[str] = [str(r[0]) for r in rows]
    ordered = [pid for pid in candidates if not _is_videoish(pid)] + [
        pid for pid in candidates if _is_videoish(pid)
    ]
    for pid in ordered:
        path = resolve_photo_path(pid)
        if path is None or not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS and path.suffix.lower() not in {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }:
            continue
        return pid, str(path)
    return "", ""


def _event_title(conn: sqlite3.Connection, event_id: str, location: str) -> str:
    row = conn.execute(
        """
        SELECT title FROM event_overlays
        WHERE event_id = ? AND TRIM(title) != ''
        ORDER BY manual DESC, updated_at DESC
        LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    if row and row[0]:
        return str(row[0]).strip()
    return (location or "未命名出门").strip()


def _load_memory(photo_id: str) -> dict[str, Any]:
    path = MEMORY_DIR / f"{photo_id}.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _default_photo_title(photo_id: str, data: dict[str, Any]) -> str:
    loc = str(data.get("location") or "").strip()
    ts = str(data.get("timestamp") or "").strip()
    day = ts[5:10] if len(ts) >= 10 else ""
    if loc and day:
        return f"{day} {loc}"
    return loc or day or photo_id


def build_story_circle_nodes(
    event_ids: list[str] | None = None,
    *,
    titles: dict[str, str] | None = None,
    db_path: Path | None = None,
) -> list[StoryCircleNode]:
    ids = [eid.strip() for eid in (event_ids or SUMMER_2026_STORY_CIRCLE) if eid.strip()]
    if not ids:
        raise ValueError("请至少提供一个 event_id")
    if len(ids) > _MAX_NODES:
        raise ValueError(f"一页最多 {_MAX_NODES} 格，请减少事件")

    title_map = {str(k).strip(): str(v).strip() for k, v in (titles or {}).items()}
    # 默认暑假短标题
    if event_ids is None and not title_map:
        title_map = dict(SUMMER_2026_STORY_TITLES)
    elif set(ids) <= set(SUMMER_2026_STORY_TITLES) and not title_map:
        title_map = {eid: SUMMER_2026_STORY_TITLES[eid] for eid in ids if eid in SUMMER_2026_STORY_TITLES}

    conn = sqlite3.connect(str(db_path or MEMORY_DB))
    try:
        nodes: list[StoryCircleNode] = []
        for i, eid in enumerate(ids, start=1):
            ev = conn.execute(
                "SELECT day, location FROM events WHERE event_id = ?",
                (eid,),
            ).fetchone()
            if not ev:
                continue
            day, location = str(ev[0] or ""), str(ev[1] or "")
            title = title_map.get(eid) or _event_title(conn, eid, location)
            photo_id, source_path = _pick_cover_photo(conn, eid)
            nodes.append(
                StoryCircleNode(
                    event_id=eid,
                    day=day,
                    title=title,
                    location=location,
                    photo_id=photo_id,
                    source_path=source_path,
                    index=i,
                )
            )
    finally:
        conn.close()

    if not nodes:
        raise ValueError("没有找到可用事件")
    return nodes


def build_nodes_from_photos(
    photo_ids: list[str],
    *,
    titles: dict[str, str] | None = None,
) -> list[StoryCircleNode]:
    """按用户勾选的照片顺序建节点（合照、同学都可以）。"""
    ids = [str(pid).strip() for pid in photo_ids if str(pid).strip()]
    seen: set[str] = set()
    ordered: list[str] = []
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        ordered.append(pid)
    if not ordered:
        raise ValueError("请至少选择一张照片")
    if len(ordered) > _MAX_NODES:
        raise ValueError(f"一页最多 {_MAX_NODES} 张，现在选了 {len(ordered)} 张")

    title_map = {str(k).strip(): str(v).strip() for k, v in (titles or {}).items()}
    nodes: list[StoryCircleNode] = []
    for i, pid in enumerate(ordered, start=1):
        data = _load_memory(pid)
        path = resolve_photo_path(pid)
        if path is None or not path.is_file():
            raise ValueError(f"找不到原图：{pid}")
        ts = str(data.get("timestamp") or "")
        day = ts[:10] if len(ts) >= 10 else ""
        loc = str(data.get("location") or "")
        title = title_map.get(pid) or _default_photo_title(pid, data)
        nodes.append(
            StoryCircleNode(
                event_id="",
                day=day,
                title=title,
                location=loc,
                photo_id=pid,
                source_path=str(path),
                index=i,
            )
        )
    return nodes


def save_story_job(
    nodes: list[StoryCircleNode],
    *,
    page_title: str,
    subtitle: str,
    layout: LayoutKind = "snake",
) -> str:
    """写入临时 job，返回 job_id（供 /story-circle?job= 打开）。"""
    from datetime import datetime

    _JOB_DIR.mkdir(parents=True, exist_ok=True)
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "job_id": job_id,
        "title": page_title,
        "subtitle": subtitle,
        "layout": layout,
        "photo_ids": [n.photo_id for n in nodes],
        "titles": {n.photo_id: n.title for n in nodes},
    }
    (_JOB_DIR / f"{job_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return job_id


def load_story_job(job_id: str) -> tuple[list[StoryCircleNode], str, str, LayoutKind]:
    path = _JOB_DIR / f"{job_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"分享页作业不存在：{job_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    titles = data.get("titles") or {}
    nodes = build_nodes_from_photos(list(data.get("photo_ids") or []), titles=titles)
    layout = data.get("layout") or "snake"
    if layout not in ("snake", "circle"):
        layout = "snake"
    return (
        nodes,
        str(data.get("title") or "面面的开心暑假"),
        str(data.get("subtitle") or ""),
        layout,  # type: ignore[return-value]
    )


def _preview_url(source_path: str, size: int = 720) -> str:
    if not source_path:
        return ""
    return f"/api/preview?path={quote(source_path)}&size={size}"


def _snake_rows(n: int) -> list[list[int]]:
    """把 0..n-1 拆成蛇形行：偶行左→右，奇行右→左。

    ≤6 张用每行 2 格（图更大、空白更少）；更多才用每行 3 格。
    """
    if n <= 2:
        cols = n
    elif n <= 6:
        cols = 2
    else:
        cols = 3
    rows: list[list[int]] = []
    i = 0
    while i < n:
        chunk = list(range(i, min(i + cols, n)))
        if len(rows) % 2 == 1:
            chunk.reverse()
        rows.append(chunk)
        i += cols
    return rows


def _render_snake_body(nodes: list[StoryCircleNode]) -> str:
    n = len(nodes)
    rows = _snake_rows(n)
    ncols = max((len(r) for r in rows), default=1)
    nrows = len(rows)
    parts: list[str] = [
        f'<div class="snake cols-{ncols} rows-{nrows}" '
        f'style="--cols:{ncols};--rows:{nrows};">'
    ]
    for ri, row in enumerate(rows):
        direction = "ltr" if ri % 2 == 0 else "rtl"
        parts.append(f'<div class="row {direction}">')
        for j, idx in enumerate(row):
            node = nodes[idx]
            badge = ""
            if node.index == 1:
                badge = '<span class="badge start">开始</span>'
            elif node.index == n:
                badge = '<span class="badge end">结束</span>'
            day_short = node.day[5:] if len(node.day) >= 10 else node.day
            if node.source_path:
                src = _preview_url(node.source_path, size=960)
                img = (
                    f'<img src="{html.escape(src)}" alt="{html.escape(node.title)}" '
                    f'loading="lazy" />'
                )
            else:
                img = '<div class="ph">无图</div>'
            parts.append(
                f"""
                <figure class="card">
                  {badge}
                  <div class="photo">{img}</div>
                  <figcaption>
                    <span class="idx">{node.index}</span>
                    <span class="title">{html.escape(node.title)}</span>
                    <span class="day">{html.escape(day_short)}</span>
                  </figcaption>
                </figure>
                """
            )
            if j < len(row) - 1:
                arrow = "→" if direction == "ltr" else "←"
                parts.append(f'<span class="arr h" aria-hidden="true">{arrow}</span>')
        parts.append("</div>")
        if ri < len(rows) - 1:
            side = "right" if ri % 2 == 0 else "left"
            parts.append(
                f'<div class="row-turn {side}" aria-hidden="true"><span class="arr v">↓</span></div>'
            )
    parts.append("</div>")
    return "\n".join(parts)


def _render_circle_body(nodes: list[StoryCircleNode]) -> str:
    n = len(nodes)
    cx, cy, radius = 50.0, 54.0, 34.0
    positions: list[tuple[float, float]] = []
    for i in range(n):
        angle = -math.pi / 2 + (2 * math.pi * i / n)
        positions.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    arrow_paths: list[str] = []
    for i in range(n - 1):
        x1, y1 = positions[i]
        x2, y2 = positions[i + 1]
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy) or 1.0
        shrink = 8.0
        sx, sy = x1 + dx / dist * shrink, y1 + dy / dist * shrink
        ex, ey = x2 - dx / dist * shrink, y2 - dy / dist * shrink
        arrow_paths.append(
            f'<line x1="{sx:.2f}" y1="{sy:.2f}" x2="{ex:.2f}" y2="{ey:.2f}" '
            f'class="arrow-line" marker-end="url(#arrowhead)" />'
        )

    cards: list[str] = []
    for node, (x, y) in zip(nodes, positions):
        badge = ""
        if node.index == 1:
            badge = '<span class="badge start">开始</span>'
        elif node.index == n:
            badge = '<span class="badge end">结束</span>'
        day_short = node.day[5:] if len(node.day) >= 10 else node.day
        if node.source_path:
            src = _preview_url(node.source_path)
            img = (
                f'<img src="{html.escape(src)}" alt="{html.escape(node.title)}" '
                f'loading="lazy" />'
            )
        else:
            img = '<div class="ph">无图</div>'
        cards.append(
            f"""
            <figure class="node" style="left:{x:.2f}%;top:{y:.2f}%;">
              {badge}
              <div class="thumb">{img}</div>
              <figcaption>
                <span class="idx">{node.index}</span>
                <span class="title">{html.escape(node.title)}</span>
                <span class="day">{html.escape(day_short)}</span>
              </figcaption>
            </figure>
            """
        )

    return f"""
    <div class="ring">
      <svg class="arrows" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <marker id="arrowhead" markerWidth="3" markerHeight="3" refX="2.2" refY="1.5" orient="auto">
            <path d="M0,0 L3,1.5 L0,3 Z" fill="#2f6fed" />
          </marker>
        </defs>
        {''.join(arrow_paths)}
      </svg>
      {''.join(cards)}
    </div>
    """


def render_story_circle_html(
    nodes: list[StoryCircleNode],
    *,
    page_title: str = "面面的开心暑假",
    subtitle: str = "和同学一起交的暑假快乐事 · 顺着箭头讲",
    layout: LayoutKind = "snake",
) -> str:
    """生成 A4 竖版可打印 HTML（需 Desk 提供 /api/preview）。"""
    n = len(nodes)
    body = _render_snake_body(nodes) if layout == "snake" else _render_circle_body(nodes)
    layout_hint = "蛇形大图" if layout == "snake" else "圆环"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(page_title)}</title>
  <style>
    :root {{
      --ink: #1a1a1a;
      --muted: #5a5a5a;
      --line: #2f6fed;
      --paper: #fffef8;
      --start: #1b7f4a;
      --end: #b45309;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background: #e8e8e8;
    }}
    .toolbar {{
      max-width: 210mm;
      margin: 12px auto;
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      font-size: 14px;
    }}
    .toolbar button {{
      padding: 8px 14px;
      border: none;
      border-radius: 8px;
      background: var(--line);
      color: #fff;
      cursor: pointer;
      font-size: 14px;
    }}
    .sheet {{
      width: 210mm;
      height: 297mm;
      margin: 0 auto 24px;
      padding: 5mm 6mm 5mm;
      background: var(--paper);
      position: relative;
      overflow: hidden;
      box-shadow: 0 4px 24px rgba(0,0,0,.12);
      display: flex;
      flex-direction: column;
    }}
    .head {{
      text-align: center;
      flex: 0 0 auto;
      margin-bottom: 2mm;
    }}
    .head h1 {{
      margin: 0;
      font-size: 16pt;
      letter-spacing: 0.03em;
    }}
    .head p {{
      margin: 1px 0 0;
      font-size: 9pt;
      color: var(--muted);
    }}
    .snake {{
      flex: 1 1 auto;
      display: flex;
      flex-direction: column;
      justify-content: stretch;
      gap: 0;
      min-height: 0;
    }}
    .row {{
      flex: 1 1 0;
      display: flex;
      align-items: stretch;
      justify-content: stretch;
      gap: 2mm;
      min-height: 0;
    }}
    .row.rtl {{
      flex-direction: row;
    }}
    .row-turn {{
      flex: 0 0 5mm;
      display: flex;
      padding: 0 4mm;
      align-items: center;
    }}
    .row-turn.right {{ justify-content: flex-end; }}
    .row-turn.left {{ justify-content: flex-start; }}
    .arr {{
      color: var(--line);
      font-weight: 700;
      font-size: 14pt;
      line-height: 1;
      user-select: none;
    }}
    .arr.h {{
      flex: 0 0 6mm;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0;
    }}
    .arr.v {{ font-size: 12pt; }}
    .card {{
      position: relative;
      margin: 0;
      flex: 1 1 0;
      min-width: 0;
      min-height: 0;
      text-align: center;
      display: flex;
      flex-direction: column;
    }}
    .photo {{
      flex: 1 1 auto;
      width: 100%;
      min-height: 0;
      margin: 0;
      border-radius: 2mm;
      overflow: hidden;
      border: 1.1pt solid #222;
      background: #ddd;
    }}
    .photo img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}
    .photo .ph {{
      width: 100%; height: 100%;
      display: grid; place-items: center;
      font-size: 10pt; color: #666;
    }}
    figcaption {{
      flex: 0 0 auto;
      margin-top: 1mm;
      line-height: 1.2;
      padding: 0 1mm;
    }}
    figcaption .idx {{
      display: inline-block;
      font-weight: 700;
      font-size: 9.5pt;
      color: var(--line);
      margin-right: 2px;
    }}
    figcaption .title {{
      display: inline;
      font-size: 9.5pt;
      font-weight: 650;
    }}
    figcaption .day {{
      display: block;
      font-size: 8pt;
      color: var(--muted);
    }}
    .badge {{
      position: absolute;
      top: 1.5mm;
      left: 1.5mm;
      transform: none;
      font-size: 8pt;
      font-weight: 700;
      padding: 1px 6px;
      border-radius: 999px;
      color: #fff;
      white-space: nowrap;
      z-index: 4;
      box-shadow: 0 1px 3px rgba(0,0,0,.25);
    }}
    .badge.start {{ background: var(--start); }}
    .badge.end {{ background: var(--end); left: auto; right: 1.5mm; }}
    .foot {{
      flex: 0 0 auto;
      text-align: center;
      font-size: 8pt;
      color: var(--muted);
      margin-top: 1.5mm;
    }}
    /* 圆环（备用） */
    .ring {{ position: relative; flex: 1; min-height: 220mm; }}
    .ring svg.arrows {{
      position: absolute; inset: 0; width: 100%; height: 100%;
      pointer-events: none; z-index: 1;
    }}
    .arrow-line {{
      stroke: var(--line); stroke-width: 0.55; stroke-linecap: round;
      fill: none; opacity: 0.85;
    }}
    .node {{
      position: absolute; width: 36mm; transform: translate(-50%, -50%);
      margin: 0; z-index: 3; text-align: center;
    }}
    .thumb {{
      width: 32mm; height: 32mm; margin: 0 auto; border-radius: 4mm;
      overflow: hidden; border: 1.2pt solid #222; background: #ddd;
    }}
    .thumb img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    @media print {{
      body {{ background: #fff; }}
      .toolbar {{ display: none !important; }}
      .sheet {{
        margin: 0;
        box-shadow: none;
        page-break-after: avoid;
      }}
      @page {{ size: A4 portrait; margin: 0; }}
    }}
  </style>
</head>
<body>
  <div class="toolbar no-print">
    <button type="button" onclick="window.print()">打印 / 另存 PDF</button>
    <span>共 {n} 张 · {layout_hint} · 建议勾选「背景图形」</span>
  </div>
  <article class="sheet">
    <header class="head">
      <h1>{html.escape(page_title)}</h1>
      <p>{html.escape(subtitle)}</p>
    </header>
    {body}
    <p class="foot">顺着箭头讲 · 从「开始」到「结束」· 和同学一起交作业</p>
  </article>
</body>
</html>
"""


def nodes_as_dicts(nodes: list[StoryCircleNode]) -> list[dict[str, Any]]:
    return [
        {
            "index": n.index,
            "event_id": n.event_id,
            "day": n.day,
            "title": n.title,
            "location": n.location,
            "photo_id": n.photo_id,
            "source_path": n.source_path,
            "preview_url": _preview_url(n.source_path) if n.source_path else "",
        }
        for n in nodes
    ]
