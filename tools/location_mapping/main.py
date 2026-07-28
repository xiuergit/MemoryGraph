"""地址映射管理工具：管理 .geocode_cache.json 中的坐标→地址映射。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.config import DATA_DIR, MEMORY_DIR
from hub.shared.geocode import (
    cache_version,
    delete_geocode_cache_without_formatted_address,
    geocode_cache_key,
    migrate_geocode_cache,
)
from hub.shared.location_cluster import clear_manual_location_flags
from hub.shared.location_canonical import (
    CANONICAL_FILE,
    apply_canonical_to_cache,
    delete_geocode_cache_by_locations,
)

GEOCODE_CACHE_FILE = DATA_DIR / ".geocode_cache.json"


def load_cache() -> dict[str, dict[str, Any]]:
    if not GEOCODE_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(GEOCODE_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"读取缓存失败: {exc}", file=sys.stderr)
        return {}


def save_cache(cache: dict[str, dict[str, Any]]) -> None:
    GEOCODE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    GEOCODE_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def print_mapping(key: str, value: dict[str, Any]) -> None:
    coords = key.split("|", maxsplit=1)[-1] if "|" in key else key
    loc = value.get("location", "")
    admin = value.get("location_admin", {})
    formatted = admin.get("formatted_address", "")
    province = admin.get("province", "")
    city = admin.get("city", "")
    district = admin.get("district", "")
    
    print(f"坐标: {coords}")
    print(f"  location:      {loc}")
    print(f"  formatted:     {formatted}")
    print(f"  省/市/区:      {province}/{city}/{district}")
    print()


def cmd_list(args: list[str]) -> None:
    cache = load_cache()
    if not cache:
        print("暂无映射")
        return
    
    items = sorted(cache.items(), key=lambda x: x[0])
    print(f"共 {len(items)} 条映射")
    print("-" * 60)
    
    for key, value in items:
        print_mapping(key, value)


def cmd_search(args: list[str]) -> None:
    if not args:
        print("用法: python tools/location_mapping/main.py search <关键词>")
        return
    
    keyword = " ".join(args)
    cache = load_cache()
    
    found = []
    for key, value in cache.items():
        loc = value.get("location", "")
        admin = value.get("location_admin", {})
        formatted = admin.get("formatted_address", "")
        
        if keyword in loc or keyword in formatted:
            found.append((key, value))
    
    if not found:
        print(f"未找到包含 '{keyword}' 的映射")
        return
    
    print(f"找到 {len(found)} 条匹配的映射")
    print("-" * 60)
    
    for key, value in found:
        print_mapping(key, value)


def cmd_update(args: list[str]) -> None:
    if len(args) < 2:
        print("用法: python tools/location_mapping/main.py update <坐标> <新地址>")
        print("示例: python tools/location_mapping/main.py update 31.238897,121.360144 金沙雅苑")
        return
    
    coords = args[0]
    new_location = " ".join(args[1:])
    
    cache = load_cache()
    
    matching_keys = [k for k in cache.keys() if k.endswith(f"|{coords}") or k == geocode_cache_key(coords)]
    if not matching_keys:
        print(f"未找到坐标 '{coords}' 的映射")
        return
    
    key = matching_keys[0]
    old_loc = cache[key].get("location", "")
    cache[key]["location"] = new_location
    
    save_cache(cache)
    print(f"更新成功:")
    print(f"  坐标: {coords}")
    print(f"  旧地址: {old_loc}")
    print(f"  新地址: {new_location}")


def cmd_delete(args: list[str]) -> None:
    if not args:
        print("用法: python tools/location_mapping/main.py delete <坐标>")
        return
    
    coords = args[0]
    cache = load_cache()
    
    matching_keys = [k for k in cache.keys() if k.endswith(f"|{coords}") or k == geocode_cache_key(coords)]
    if not matching_keys:
        print(f"未找到坐标 '{coords}' 的映射")
        return
    
    key = matching_keys[0]
    del cache[key]
    save_cache(cache)
    
    print(f"已删除坐标 '{coords}' 的映射")


def cmd_add(args: list[str]) -> None:
    if len(args) < 2:
        print("用法: python tools/location_mapping/main.py add <坐标> <地址>")
        print("示例: python tools/location_mapping/main.py add 31.238897,121.360144 金沙雅苑")
        return
    
    coords = args[0]
    location = " ".join(args[1:])
    
    cache = load_cache()
    
    key = geocode_cache_key(coords)
    if key in cache:
        print(f"坐标 '{coords}' 已存在映射，使用 update 命令修改")
        return
    
    cache[key] = {
        "location": location,
        "location_admin": {
            "province": "",
            "city": "",
            "district": "",
            "formatted_address": "",
        },
    }
    
    save_cache(cache)
    print(f"添加成功:")
    print(f"  坐标: {coords}")
    print(f"  地址: {location}")


def cmd_export(args: list[str]) -> None:
    cache = load_cache()
    
    mappings = []
    for key, value in cache.items():
        coords = key.split("|", maxsplit=1)[-1] if "|" in key else key
        admin = value.get("location_admin", {})
        mappings.append({
            "coords": coords,
            "location": value.get("location", ""),
            "formatted_address": admin.get("formatted_address", ""),
            "province": admin.get("province", ""),
            "city": admin.get("city", ""),
            "district": admin.get("district", ""),
        })
    
    output_file = DATA_DIR / "location_mapping_export.json"
    output_file.write_text(
        json.dumps(mappings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    
    print(f"已导出 {len(mappings)} 条映射到 {output_file}")


def cmd_import(args: list[str]) -> None:
    if not args:
        print("用法: python tools/location_mapping/main.py import <文件路径>")
        return
    
    import_file = Path(args[0])
    if not import_file.exists():
        print(f"文件不存在: {import_file}")
        return
    
    try:
        data = json.loads(import_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"读取文件失败: {exc}", file=sys.stderr)
        return
    
    if not isinstance(data, list):
        print("导入文件格式错误，应为数组", file=sys.stderr)
        return
    
    cache = load_cache()
    added = 0
    updated = 0
    
    for item in data:
        coords = item.get("coords", "")
        location = item.get("location", "")
        if not coords or not location:
            continue
        
        key = geocode_cache_key(coords)
        existing = cache.get(key)
        
        if existing:
            existing["location"] = location
            updated += 1
        else:
            cache[key] = {
                "location": location,
                "location_admin": {
                    "province": item.get("province", ""),
                    "city": item.get("city", ""),
                    "district": item.get("district", ""),
                    "formatted_address": item.get("formatted_address", ""),
                },
            }
            added += 1
    
    save_cache(cache)
    print(f"导入完成: 添加 {added} 条，更新 {updated} 条")


def cmd_delete_incomplete(args: list[str]) -> None:
    dry_run = "--dry-run" in args
    deleted = delete_geocode_cache_without_formatted_address(dry_run=dry_run)
    label = "将删除" if dry_run else "已删除"
    print(f"{label} {deleted} 条无 formatted_address 的缓存")
    if deleted and not dry_run:
        print("下一步: 重新请求高德并写 JSON（不要跑 normalize，以免又合并）:")
        print("  python tools/photo2json/main.py --regeocode-locations --no-normalize-after")
        print("  python tools/memory_index/main.py sync")


def cmd_delete_by_location(args: list[str]) -> None:
    if not args:
        print("用法: python tools/location_mapping/main.py delete-by-location <短地名> [更多...]")
        print("示例: python tools/location_mapping/main.py delete-by-location 香景园 河滨香景园 馨越公寓")
        return
    deleted = delete_geocode_cache_by_locations(*args)
    print(f"已从缓存删除 {deleted} 条（location 匹配: {', '.join(args)}）")
    if deleted:
        print("下一步: 重新请求高德并写 JSON（不要跑 normalize，以免又合并）:")
        print("  python tools/photo2json/main.py --regeocode-locations --no-normalize-after")


def cmd_apply_canonical(args: list[str]) -> None:
    dry_run = "--dry-run" in args
    if not CANONICAL_FILE.is_file():
        print(f"请先创建配置文件: {CANONICAL_FILE}")
        print(f"  cp data/location_canonical.example.json data/location_canonical.json")
        return
    stats = apply_canonical_to_cache(dry_run=dry_run)
    print(
        f"canonical 应用: 更新 {stats.cache_updated} 条，跳过 {stats.cache_skipped} 条"
        + (" (dry-run)" if dry_run else "")
    )
    if stats.cache_updated and not dry_run:
        print("下一步建议:")
        print("  python tools/photo2json/main.py --regeocode-locations")
        print("  python tools/memory_index/main.py sync")


def cmd_migrate(args: list[str]) -> None:
    dry_run = "--dry-run" in args
    keep_bad = "--keep-bad" in args
    stats = migrate_geocode_cache(dry_run=dry_run, purge_bad=not keep_bad)
    print(
        f"缓存共 {stats.total_keys} 条 → 重建后约 "
        f"{stats.migrated + stats.skipped_existing} 条有效 v{cache_version()} 条目"
    )
    print(
        f"迁入 {stats.migrated}，已有跳过 {stats.skipped_existing}，"
        f"丢弃坏项 {stats.dropped_bad}，删旧 key {stats.removed_legacy}，"
        f"清 v{cache_version()} 坏项 {stats.purged_current}"
        + (" (dry-run)" if dry_run else "")
    )
    if not dry_run and (stats.migrated or stats.purged_current or stats.dropped_bad):
        print("下一步建议:")
        print("  python tools/photo2json/main.py --regeocode-locations")
        print("  python tools/memory_index/main.py sync")


def cmd_clear_manual(args: list[str]) -> None:
    dry_run = "--dry-run" in args
    memory_dir = MEMORY_DIR
    filtered = [a for a in args if a != "--dry-run"]
    if filtered:
        memory_dir = Path(filtered[0])
    stats = clear_manual_location_flags(memory_dir, dry_run=dry_run)
    print(
        f"扫描 {stats.total} 条，清除 {stats.cleared} 条，"
        f"跳过 {stats.skipped} 条，失败 {stats.failed} 条"
        + (" (dry-run，未写文件)" if dry_run else "")
    )
    if stats.cleared and not dry_run:
        print("下一步建议:")
        print("  python tools/photo2json/main.py --regeocode-locations")
        print("  python tools/memory_index/main.py sync")


def print_help() -> None:
    print("地址映射管理工具")
    print("用法: python tools/location_mapping/main.py <命令> [参数]")
    print()
    print("命令:")
    print("  list                 列出所有映射")
    print("  search <关键词>       搜索映射（按 location 或 formatted_address）")
    print("  update <坐标> <地址>  修改映射的 location")
    print("  delete <坐标>         删除映射")
    print("  add <坐标> <地址>     添加新映射")
    print("  export               导出映射到 location_mapping_export.json")
    print("  import <文件>         从文件导入映射")
    print("  migrate [--dry-run] [--keep-bad]")
    print("                       v3 等旧缓存 → 当前版本，并清理含「公司」等坏项")
    print("  apply-canonical [--dry-run]")
    print("                       合并场景：按 location_canonical.json 统一别名")
    print("  delete-by-location <名>…")
    print("                       拆开场景：删缓存里这些短地名，再 regeocode 重拉高德")
    print("  delete-incomplete [--dry-run]")
    print("                       删除所有无 formatted_address 的缓存条目")
    print("  clear-manual [--dry-run] [memory目录]")
    print("                       清除 JSON 的 manual_location 标记")
    print("  help                 显示帮助")
    print()
    print("示例:")
    print("  python tools/location_mapping/main.py search 花园")
    print("  python tools/location_mapping/main.py update 31.238897,121.360144 金沙雅苑")


def main() -> None:
    if len(sys.argv) < 2:
        print_help()
        return
    
    cmd = sys.argv[1]
    args = sys.argv[2:]
    
    commands = {
        "list": cmd_list,
        "search": cmd_search,
        "update": cmd_update,
        "delete": cmd_delete,
        "add": cmd_add,
        "export": cmd_export,
        "import": cmd_import,
        "migrate": cmd_migrate,
        "apply-canonical": cmd_apply_canonical,
        "delete-by-location": cmd_delete_by_location,
        "delete-incomplete": cmd_delete_incomplete,
        "clear-manual": cmd_clear_manual,
        "help": print_help,
    }
    
    if cmd not in commands:
        print(f"未知命令: {cmd}", file=sys.stderr)
        print_help()
        return
    
    commands[cmd](args)


if __name__ == "__main__":
    main()