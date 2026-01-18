"""
Build Image - Build ext4/erofs images từ source folder
REAL Implementation (không demo)
Hỗ trợ output: raw / sparse / both
"""
import os
import time
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from threading import Event
from enum import Enum

from .task_defs import TaskResult
from .project_store import Project
from .logbus import get_log_bus
from .utils import ensure_dir, timestamp, human_size


class OutputType(Enum):
    RAW = "raw"
    SPARSE = "sparse"
    BOTH = "both"


@dataclass
class BuildImageConfig:
    """Cấu hình build image"""
    # Make Settings
    block_size: int = 4096
    hash_algorithm: str = "half_md4"
    hash_seed: str = ""
    has_journal: bool = True
    image_size: int = 0  # bytes, 0 = auto
    inode_size: int = 256
    number_of_inodes: int = 0  # 0 = auto
    reserved_blocks_percentage: int = 0
    uuid: str = ""
    volume_label: str = ""
    
    # Android Settings
    ext4_share_duplicated_blocks: bool = True
    file_contexts: str = ""  # path to file_contexts
    fs_config: str = ""  # path to fs_config
    mount_point: str = ""  # e.g., /system, /vendor
    source_dir: str = ""
    
    # Common Settings
    filesystem: str = "ext4"  # ext4 or erofs
    output_filename: str = ""
    output_type: str = "both"  # raw, sparse, both
    timestamp_value: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
    
    @classmethod
    def from_dict(cls, data: dict) -> "BuildImageConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# Default configs for partitions
DEFAULT_PARTITION_CONFIGS = {
    "system_a": BuildImageConfig(mount_point="/system", volume_label="system", output_filename="system_a.img"),
    "vendor_a": BuildImageConfig(mount_point="/vendor", volume_label="vendor", output_filename="vendor_a.img"),
    "product_a": BuildImageConfig(mount_point="/product", volume_label="product", output_filename="product_a.img"),
    "odm_a": BuildImageConfig(mount_point="/odm", volume_label="odm", output_filename="odm_a.img"),
    "system_ext_a": BuildImageConfig(mount_point="/system_ext", volume_label="system_ext", output_filename="system_ext_a.img"),
}


def get_folder_size(path: Path) -> int:
    """Tính tổng size folder (bytes)"""
    total = 0
    try:
        for entry in path.rglob('*'):
            if entry.is_file():
                total += entry.stat().st_size
    except Exception:
        pass
    return total


def estimate_image_size(folder_size: int, overhead: float = 1.15) -> int:
    """Ước tính image size từ folder size (thêm overhead)"""
    estimated = int(folder_size * overhead)
    # Align to 4MB
    aligned = ((estimated + 4*1024*1024 - 1) // (4*1024*1024)) * (4*1024*1024)
    return max(aligned, 64*1024*1024)  # Minimum 64MB


def find_file_contexts(project: Project, partition: str) -> Optional[Path]:
    """Tìm file_contexts cho partition"""
    config_dir = project.config_dir
    patterns = [
        f"{partition}_file_contexts.txt",
        f"file_contexts_{partition}.txt",
        "file_contexts.txt",
    ]
    
    for pattern in patterns:
        path = config_dir / pattern
        if path.exists():
            return path
    
    # Check source folder
    source_dir = project.source_dir / partition
    etc_paths = [
        source_dir / "etc" / "selinux" / "plat_file_contexts",
        source_dir / "etc" / "selinux" / "file_contexts",
    ]
    
    for path in etc_paths:
        if path.exists():
            return path
    
    return None


def find_fs_config(project: Project, partition: str) -> Optional[Path]:
    """Tìm fs_config cho partition"""
    config_dir = project.config_dir
    patterns = [
        f"{partition}_filesystem_config.txt",
        f"{partition}_fs_config.txt",
        f"fs_config_{partition}.txt",
    ]
    
    for pattern in patterns:
        path = config_dir / pattern
        if path.exists():
            return path
    
    return None


def run_tool(args: List[str], timeout: int = 600, _cancel_token: Event = None) -> subprocess.CompletedProcess:
    """Run tool với proper handling"""
    log = get_log_bus()
    log.debug(f"[TOOL] Running: {' '.join(args)}")
    
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        return result
    except subprocess.TimeoutExpired:
        log.error(f"[TOOL] Timeout after {timeout}s")
        raise
    except Exception as e:
        log.error(f"[TOOL] Error: {e}")
        raise


def build_ext4_image(
    config: BuildImageConfig,
    output_path: Path,
    _cancel_token: Event = None
) -> TaskResult:
    """Build ext4 image using make_ext4fs"""
    log = get_log_bus()
    start = time.time()
    
    log.info(f"[BUILD_EXT4] Building {output_path.name}")
    log.info(f"[BUILD_EXT4] Source: {config.source_dir}")
    log.info(f"[BUILD_EXT4] Size: {human_size(config.image_size)}")
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        make_ext4fs = registry.get_tool_path("make_ext4fs")
        if not make_ext4fs:
            return TaskResult.error("Tool make_ext4fs not found. Run Tools Doctor.")
        
        # Build command
        args = [str(make_ext4fs)]
        
        # Size
        args.extend(["-l", str(config.image_size)])
        
        # Mount point
        if config.mount_point:
            args.extend(["-a", config.mount_point.lstrip('/')])
        
        # SELinux contexts
        if config.file_contexts and Path(config.file_contexts).exists():
            args.extend(["-S", config.file_contexts])
            log.info(f"[BUILD_EXT4] Using file_contexts: {config.file_contexts}")
        
        # FS config
        if config.fs_config and Path(config.fs_config).exists():
            args.extend(["-C", config.fs_config])
            log.info(f"[BUILD_EXT4] Using fs_config: {config.fs_config}")
        
        # Options
        if config.ext4_share_duplicated_blocks:
            args.append("-c")
        
        if config.has_journal:
            args.append("-J")
        
        if config.timestamp_value:
            args.extend(["-T", str(config.timestamp_value)])
        
        # Output and source
        args.extend([str(output_path), config.source_dir])
        
        log.info(f"[BUILD_EXT4] Command: {' '.join(args[:5])}...")
        
        result = run_tool(args, timeout=1800)  # 30 min timeout
        
        if result.returncode != 0:
            log.error(f"[BUILD_EXT4] stderr: {result.stderr[:500]}")
            return TaskResult.error(f"make_ext4fs failed: {result.stderr[:200]}")
        
        if not output_path.exists():
            return TaskResult.error("Output file not created")
        
        elapsed = int((time.time() - start) * 1000)
        size = output_path.stat().st_size
        log.success(f"[BUILD_EXT4] Done: {human_size(size)} in {elapsed}ms")
        
        return TaskResult.success(
            message=f"Built {output_path.name} ({human_size(size)})",
            artifacts=[str(output_path)],
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.error(f"[BUILD_EXT4] Error: {e}")
        return TaskResult.error(str(e), elapsed_ms=elapsed)


def build_erofs_image(
    config: BuildImageConfig,
    output_path: Path,
    _cancel_token: Event = None
) -> TaskResult:
    """Build erofs image using mkfs.erofs"""
    log = get_log_bus()
    start = time.time()
    
    log.info(f"[BUILD_EROFS] Building {output_path.name}")
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        mkfs_erofs = registry.get_tool_path("mkfs_erofs")
        if not mkfs_erofs:
            return TaskResult.error("Tool mkfs.erofs not found")
        
        # Build command
        args = [str(mkfs_erofs)]
        
        # Compression
        args.extend(["-z", "lz4hc"])
        
        if config.file_contexts:
            args.extend(["--file-contexts", config.file_contexts])
        
        if config.mount_point:
            args.extend(["--mount-point", config.mount_point])
        
        args.extend([str(output_path), config.source_dir])
        
        result = run_tool(args, timeout=1800)
        
        if result.returncode != 0:
            return TaskResult.error(f"mkfs.erofs failed: {result.stderr[:200]}")
        
        elapsed = int((time.time() - start) * 1000)
        size = output_path.stat().st_size
        log.success(f"[BUILD_EROFS] Done: {human_size(size)}")
        
        return TaskResult.success(
            message=f"Built {output_path.name}",
            artifacts=[str(output_path)],
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        log.error(f"[BUILD_EROFS] Error: {e}")
        return TaskResult.error(str(e))


def convert_to_sparse(
    raw_image: Path,
    sparse_image: Path,
    _cancel_token: Event = None
) -> TaskResult:
    """Convert raw image to sparse using img2simg"""
    log = get_log_bus()
    start = time.time()
    
    log.info(f"[SPARSE] Converting {raw_image.name} to sparse")
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        img2simg = registry.get_tool_path("img2simg")
        if not img2simg:
            return TaskResult.error("Tool img2simg not found")
        
        args = [str(img2simg), str(raw_image), str(sparse_image)]
        result = run_tool(args, timeout=600)
        
        if result.returncode != 0:
            return TaskResult.error(f"img2simg failed: {result.stderr[:200]}")
        
        elapsed = int((time.time() - start) * 1000)
        log.success(f"[SPARSE] Created {sparse_image.name}")
        
        return TaskResult.success(
            message=f"Converted to {sparse_image.name}",
            artifacts=[str(sparse_image)],
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        log.error(f"[SPARSE] Error: {e}")
        return TaskResult.error(str(e))


def build_image(
    project: Project,
    partition: str,
    config: BuildImageConfig,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Main function to build image (ext4 or erofs, raw/sparse/both)
    """
    log = get_log_bus()
    start = time.time()
    
    log.info(f"[BUILD] Building {partition}")
    log.info(f"[BUILD] Filesystem: {config.filesystem}")
    log.info(f"[BUILD] Output type: {config.output_type}")
    
    try:
        # Validate source dir
        source_dir = Path(config.source_dir)
        if not source_dir.exists():
            return TaskResult.error(f"Source folder not found: {source_dir}")
        
        # Prepare output dir
        output_dir = project.image_dir
        ensure_dir(output_dir)
        
        raw_filename = config.output_filename or f"{partition}.img"
        raw_path = output_dir / raw_filename
        
        # Auto-calculate image size
        if config.image_size <= 0:
            folder_size = get_folder_size(source_dir)
            config.image_size = estimate_image_size(folder_size)
            log.info(f"[BUILD] Auto size: {human_size(config.image_size)}")
        
        # Build raw image
        if config.filesystem == "ext4":
            result = build_ext4_image(config, raw_path, _cancel_token)
        elif config.filesystem == "erofs":
            result = build_erofs_image(config, raw_path, _cancel_token)
        else:
            return TaskResult.error(f"Unknown filesystem: {config.filesystem}")
        
        if not result.ok:
            return result
        
        artifacts = [str(raw_path)]
        
        # Handle output type
        output_type = config.output_type.lower()
        
        if output_type in ["sparse", "both"]:
            sparse_filename = raw_filename.replace(".img", "_sparse.img")
            sparse_path = output_dir / sparse_filename
            
            sparse_result = convert_to_sparse(raw_path, sparse_path, _cancel_token)
            if sparse_result.ok:
                artifacts.append(str(sparse_path))
                
                # If sparse only, delete raw
                if output_type == "sparse":
                    raw_path.unlink(missing_ok=True)
                    artifacts = [str(sparse_path)]
            else:
                log.warning(f"[BUILD] Sparse conversion failed: {sparse_result.message}")
        
        # Save config to project
        try:
            presets = project.config.build_presets or {}
            presets[partition] = config.to_dict()
            project.update_config(build_presets=presets)
        except Exception as e:
            log.warning(f"[BUILD] Could not save preset: {e}")
        
        elapsed = int((time.time() - start) * 1000)
        log.success(f"[BUILD] Completed {partition} in {elapsed}ms")
        
        return TaskResult.success(
            message=f"Built {partition}: {', '.join([Path(a).name for a in artifacts])}",
            artifacts=artifacts,
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.error(f"[BUILD] Error: {e}")
        return TaskResult.error(str(e), elapsed_ms=elapsed)


def build_image_bulk(
    project: Project,
    partitions: List[str] = None,
    output_type: str = "both",
    filesystem: str = "ext4",
    _cancel_token: Event = None
) -> TaskResult:
    """Build multiple partition images in sequence"""
    log = get_log_bus()
    start = time.time()
    
    partitions = partitions or ["system_a", "vendor_a", "product_a"]
    
    log.info(f"[BUILD_BULK] Building {len(partitions)} partitions")
    log.info(f"[BUILD_BULK] Output type: {output_type}")
    
    results = []
    failed = []
    
    for i, partition in enumerate(partitions):
        if _cancel_token and _cancel_token.is_set():
            log.warning("[BUILD_BULK] Cancelled by user")
            break
        
        log.info(f"[BUILD_BULK] [{i+1}/{len(partitions)}] {partition}")
        
        # Get default config
        if partition in DEFAULT_PARTITION_CONFIGS:
            config = DEFAULT_PARTITION_CONFIGS[partition]
        else:
            config = BuildImageConfig()
            config.mount_point = f"/{partition.replace('_a', '')}"
            config.output_filename = f"{partition}.img"
        
        # Set common options
        config.output_type = output_type
        config.filesystem = filesystem
        
        # Set source dir
        source_dir = project.source_dir / partition
        if not source_dir.exists():
            log.warning(f"[BUILD_BULK] Skip {partition}: source not found")
            continue
        config.source_dir = str(source_dir)
        
        # Auto-detect file_contexts and fs_config
        fc = find_file_contexts(project, partition)
        if fc:
            config.file_contexts = str(fc)
        
        fsc = find_fs_config(project, partition)
        if fsc:
            config.fs_config = str(fsc)
        
        # Build
        result = build_image(project, partition, config, _cancel_token)
        results.append((partition, result))
        
        if not result.ok:
            failed.append(partition)
    
    elapsed = int((time.time() - start) * 1000)
    
    if failed:
        log.error(f"[BUILD_BULK] Failed: {', '.join(failed)}")
        return TaskResult.error(f"Failed: {', '.join(failed)}", elapsed_ms=elapsed)
    
    built_count = sum(1 for _, r in results if r.ok)
    log.success(f"[BUILD_BULK] Built {built_count} partitions in {elapsed}ms")
    
    return TaskResult.success(
        message=f"Built {built_count} partitions",
        elapsed_ms=elapsed
    )
