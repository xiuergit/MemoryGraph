"""Read and write project markdown under docs/.

Inspector「知识」菜单的文件范围：只允许 docs/ 里的 .md，不跟随符号链接。
"""

from __future__ import annotations

import re
from pathlib import Path

from hub.shared.config import PROJECT_ROOT

DOCS_DIR = PROJECT_ROOT / "docs"
MAX_BYTES = 1_000_000

# 侧栏固定分组。路径相对 docs/。学习笔记另行扫描 docs/ai-study/。
CURATED: list[tuple[str, str, list[str]]] = [
    (
        "architecture",
        "架构",
        ["architecture.md", "media-memory.md"],
    ),
    (
        "progress",
        "进度",
        ["Project Charter.md", "agent-intents.md", "ask-checklist.md"],
    ),
    (
        "config",
        "配置",
        ["operations.md", "ai-setup/README.md"],
    ),
]

_HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$")


class ProjectDocError(ValueError):
    """调用方把消息直接返回给管理页。"""


def list_doc_groups() -> list[dict]:
    claimed: set[str] = set()
    groups: list[dict] = []
    for group_id, label, rels in CURATED:
        files: list[dict] = []
        for rel in rels:
            path = _existing_file(rel)
            if path is None:
                continue
            files.append(_entry(path))
            claimed.add(rel)
        groups.append({"id": group_id, "label": label, "files": files})

    study: list[dict] = []
    study_root = DOCS_DIR / "ai-study"
    if study_root.is_dir() and not study_root.is_symlink():
        for path in study_root.glob("*.md"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(DOCS_DIR).as_posix()
            study.append(_entry(path))
            claimed.add(rel)
    study.sort(key=lambda item: _study_sort_key(item["name"]))
    groups.append({"id": "study", "label": "学习", "files": study})

    other: list[dict] = []
    if DOCS_DIR.is_dir():
        for path in DOCS_DIR.rglob("*.md"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(DOCS_DIR).as_posix()
            if rel in claimed or _chain_has_symlink(rel):
                continue
            other.append(_entry(path))
    other.sort(key=lambda item: item["path"])
    if other:
        groups.append({"id": "other", "label": "其他", "files": other})
    return groups


def read_project_doc(path_str: str) -> dict:
    path = resolve_doc(path_str, must_exist=True)
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectDocError("文件不是 UTF-8 文本") from exc
    rel = _public_path(path)
    return {"path": rel, "content": content, "title": _title_from_text(content, path.stem)}


def write_project_doc(path_str: str, content: str) -> dict:
    if not isinstance(content, str):
        raise ProjectDocError("内容无效")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ProjectDocError("文件超过 1MB，请在编辑器里改")
    path = resolve_doc(path_str, must_exist=True)
    path.write_text(content, encoding="utf-8")
    return {"path": _public_path(path), "bytes": len(encoded)}


def create_study_note(name: str) -> dict:
    stem = _note_stem(name)
    rel = f"ai-study/{stem}.md"
    path = resolve_doc(rel, must_exist=False)
    if path.exists():
        raise ProjectDocError("同名笔记已存在")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"# {stem}\n\n"
    path.write_text(content, encoding="utf-8")
    return {"path": f"docs/{rel}", "content": content, "title": stem}


def resolve_doc(path_str: str, *, must_exist: bool) -> Path:
    rel = _docs_relative(path_str)
    if _chain_has_symlink(rel):
        raise ProjectDocError("不跟随符号链接")
    path = DOCS_DIR.joinpath(*Path(rel).parts)
    if must_exist and not path.is_file():
        raise ProjectDocError("文件不存在")
    return path


def _docs_relative(path_str: str) -> str:
    raw = (path_str or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/"):
        raise ProjectDocError("路径无效")
    if raw.startswith("docs/"):
        raw = raw[len("docs/") :]
    parts = Path(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ProjectDocError("路径无效")
    rel = "/".join(parts)
    if not rel.lower().endswith(".md"):
        raise ProjectDocError("只能读写 Markdown")
    return rel


def _chain_has_symlink(rel: str) -> bool:
    current = DOCS_DIR
    if current.is_symlink():
        return True
    for part in Path(rel).parts:
        current = current / part
        if current.is_symlink():
            return True
    try:
        current.resolve().relative_to(DOCS_DIR.resolve())
    except ValueError:
        return True
    return False


def _existing_file(rel: str) -> Path | None:
    if _chain_has_symlink(rel):
        return None
    path = DOCS_DIR.joinpath(*Path(rel).parts)
    if path.is_file():
        return path
    return None


def _entry(path: Path) -> dict:
    rel = path.relative_to(DOCS_DIR).as_posix()
    return {
        "path": f"docs/{rel}",
        "name": path.name,
        "title": _title_from_file(path),
    }


def _public_path(path: Path) -> str:
    return f"docs/{path.relative_to(DOCS_DIR).as_posix()}"


def _title_from_file(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as handle:
            chunk = handle.read(4096)
    except (OSError, UnicodeDecodeError):
        return path.stem
    return _title_from_text(chunk, path.stem)


def _title_from_text(text: str, fallback: str) -> str:
    for line in text.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match:
            return match.group(1).strip()
    return fallback


def _study_sort_key(name: str) -> tuple:
    if name == "README.md":
        return (0, name)
    if name.startswith("总目标"):
        return (1, name)
    return (2, name)


def _note_stem(name: str) -> str:
    stem = (name or "").strip()
    if stem.lower().endswith(".md"):
        stem = stem[:-3].strip()
    if (
        not stem
        or stem.startswith(".")
        or ".." in stem
        or len(stem) > 80
        or any(ch in stem for ch in "/\\")
        or any(ord(ch) < 32 for ch in stem)
    ):
        raise ProjectDocError("笔记名只能用中文、字母、数字和空格，不能包含路径")
    return stem
