"""
Dirty Tracker - Track partition modification state
Mục tiêu: If partition CLEAN -> copy-through (no-op build) để giảm bootloop
"""
import json
import os
from pathlib import Path
from typing import Dict, Optional
from .logbus import get_log_bus


def get_dirty_path(project) -> Path:
    """Get path to dirty.json"""
    return project.extract_dir / "dirty.json"


def get_snapshot_path(project) -> Path:
    """Get path to source_snapshot.json"""
    return project.extract_dir / "source_snapshot.json"


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


# ============ SNAPSHOT DETECTION ============

def compute_source_snapshot(source_dir: Path) -> Dict:
    """
    Compute fast snapshot of source directory
    
    Returns:
        {file_count, total_size, newest_mtime}
    """
    if not source_dir.exists():
        return {"file_count": 0, "total_size": 0, "newest_mtime": 0}
    
    file_count = 0
    total_size = 0
    newest_mtime = 0
    
    try:
        for f in source_dir.rglob("*"):
            if f.is_file():
                file_count += 1
                stat = f.stat()
                total_size += stat.st_size
                newest_mtime = max(newest_mtime, stat.st_mtime)
    except Exception:
        pass
    
    return {
        "file_count": file_count,
        "total_size": total_size,
        "newest_mtime": newest_mtime
    }


def load_snapshots(project) -> Dict[str, Dict]:
    """Load saved snapshots"""
    snapshot_path = get_snapshot_path(project)
    if not snapshot_path.exists():
        return {}
    
    try:
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_snapshots(project, snapshots: Dict[str, Dict]) -> None:
    """Save snapshots"""
    snapshot_path = get_snapshot_path(project)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshots, indent=2), encoding="utf-8")


def save_partition_snapshot(project, partition_name: str) -> None:
    """Save snapshot for a partition after extract"""
    source_dir = project.out_source_dir / partition_name
    snapshot = compute_source_snapshot(source_dir)
    
    snapshots = load_snapshots(project)
    snapshots[partition_name] = snapshot
    save_snapshots(project, snapshots)


def check_partition_changed(project, partition_name: str) -> bool:
    """
    Check if partition source has changed since snapshot
    
    Returns:
        True if changed or no snapshot (safe default)
        False if unchanged
    """
    snapshots = load_snapshots(project)
    saved = snapshots.get(partition_name)
    
    if not saved:
        return True  # No snapshot = assume changed (safe)
    
    source_dir = project.out_source_dir / partition_name
    current = compute_source_snapshot(source_dir)
    
    # Compare
    changed = (
        current["file_count"] != saved.get("file_count", 0) or
        current["total_size"] != saved.get("total_size", 0) or
        current["newest_mtime"] != saved.get("newest_mtime", 0)
    )
    
    return changed


def auto_detect_dirty(project, partition_name: str) -> bool:
    """
    Auto-detect if partition is dirty by comparing snapshots
    Updates dirty flag if changed detected
    
    Returns:
        True if dirty (changed or unknown)
        False if clean (unchanged)
    """
    log = get_log_bus()
    
    if check_partition_changed(project, partition_name):
        set_dirty(project, partition_name, True)
        log.debug(f"[DIRTY] Auto-detect: {partition_name} CHANGED -> DIRTY")
        return True
    else:
        # Keep existing flag (don't override if already dirty)
        current = is_dirty(project, partition_name)
        if current:
            log.debug(f"[DIRTY] {partition_name} unchanged but was marked DIRTY")
        return current
