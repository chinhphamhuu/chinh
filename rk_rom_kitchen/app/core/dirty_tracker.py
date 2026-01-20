"""
Dirty Tracker - Track partition modification state
Mục tiêu: If partition CLEAN -> copy-through (no-op build) để giảm bootloop
"""
import json
from pathlib import Path
from typing import Dict, Optional
from .logbus import get_log_bus


def get_dirty_path(project) -> Path:
    """Get path to dirty.json"""
    return project.extract_dir / "dirty.json"


def load_dirty(project) -> Dict[str, bool]:
    """
    Load dirty flags from project
    
    Returns:
        Dict[partition_name, is_dirty]
        Default: {} nếu file không tồn tại
    """
    dirty_path = get_dirty_path(project)
    if not dirty_path.exists():
        return {}
    
    try:
        return json.loads(dirty_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_dirty(project, dirty_flags: Dict[str, bool]) -> None:
    """Save dirty flags to project"""
    dirty_path = get_dirty_path(project)
    dirty_path.parent.mkdir(parents=True, exist_ok=True)
    dirty_path.write_text(json.dumps(dirty_flags, indent=2), encoding="utf-8")


def set_dirty(project, partition_name: str, is_dirty: bool = True) -> None:
    """
    Set dirty flag for a partition
    
    Args:
        project: Project instance
        partition_name: Tên partition (e.g., "system_a")
        is_dirty: True = partition đã bị sửa, cần rebuild
    """
    log = get_log_bus()
    flags = load_dirty(project)
    flags[partition_name] = is_dirty
    save_dirty(project, flags)
    
    status = "DIRTY" if is_dirty else "CLEAN"
    log.debug(f"[DIRTY] {partition_name} -> {status}")


def is_dirty(project, partition_name: str) -> bool:
    """
    Check if partition is dirty (needs rebuild)
    
    Returns:
        True if dirty or unknown (safe default)
        False if explicitly marked clean
    """
    flags = load_dirty(project)
    # Default: True (safe) nếu không có trong file
    return flags.get(partition_name, True)


def mark_all_clean(project, partition_names: list) -> None:
    """Mark all partitions as clean (after extract)"""
    flags = load_dirty(project)
    for name in partition_names:
        flags[name] = False
    save_dirty(project, flags)


def mark_all_dirty(project) -> None:
    """Mark all tracked partitions as dirty"""
    flags = load_dirty(project)
    for name in flags:
        flags[name] = True
    save_dirty(project, flags)


def get_dirty_summary(project) -> str:
    """Get summary string for UI/log"""
    flags = load_dirty(project)
    if not flags:
        return "Không có partition nào được track"
    
    clean = [k for k, v in flags.items() if not v]
    dirty = [k for k, v in flags.items() if v]
    
    parts = []
    if clean:
        parts.append(f"CLEAN: {', '.join(clean)}")
    if dirty:
        parts.append(f"DIRTY: {', '.join(dirty)}")
    
    return " | ".join(parts)
