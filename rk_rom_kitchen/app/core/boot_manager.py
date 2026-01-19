"""
Boot Manager - Unpack/Repack boot images
REAL Implementation sử dụng magiskboot hoặc unpackbootimg/mkbootimg
"""
import os
import sys
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List
from threading import Event

from .task_defs import TaskResult
from .project_store import Project
from .logbus import get_log_bus
from .utils import ensure_dir, timestamp


BOOT_IMAGE_NAMES = [
    "boot.img", "boot_a.img",
    "vendor_boot.img", "vendor_boot_a.img",
    "init_boot.img", "init_boot_a.img",
]


def find_boot_images(project: Project) -> List[Path]:
    """Tìm boot images trong project"""
    found = []
    search_dirs = [project.in_dir, project.out_dir, project.image_dir]
    
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for name in BOOT_IMAGE_NAMES:
            path = search_dir / name
            if path.exists():
                found.append(path)
    
    return list(set(found))


def run_tool(args: List[str], cwd: Path = None, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run tool with proper handling"""
    log = get_log_bus()
    log.debug(f"[TOOL] {' '.join(args[:3])}...")
    
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    )


def unpack_with_magiskboot(
    boot_image: Path,
    output_dir: Path,
    _cancel_token: Event = None
) -> TaskResult:
    """Unpack boot image using magiskboot"""
    log = get_log_bus()
    start = time.time()
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        magiskboot = registry.get_tool_path("magiskboot")
        if not magiskboot:
            return TaskResult.error("magiskboot not found")
        
        # Copy boot to output dir first
        ensure_dir(output_dir)
        work_boot = output_dir / boot_image.name
        shutil.copy2(boot_image, work_boot)
        
        # Run magiskboot unpack
        args = [str(magiskboot), "unpack", work_boot.name]
        result = run_tool(args, cwd=output_dir)
        
        if result.returncode != 0:
            log.error(f"[BOOT] magiskboot error: {result.stderr}")
            return TaskResult.error(f"magiskboot failed: {result.stderr[:200]}")
        
        # Clean up copied boot
        work_boot.unlink(missing_ok=True)
        
        elapsed = int((time.time() - start) * 1000)
        log.success(f"[BOOT] Unpacked with magiskboot: {output_dir}")
        
        return TaskResult.success(
            message=f"Unpacked {boot_image.name}",
            artifacts=[str(output_dir)],
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        log.error(f"[BOOT] Error: {e}")
        return TaskResult.error(str(e))


def unpack_with_unpackbootimg(
    boot_image: Path,
    output_dir: Path,
    _cancel_token: Event = None
) -> TaskResult:
    """Unpack boot image using unpackbootimg"""
    log = get_log_bus()
    start = time.time()
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        unpackbootimg = registry.get_tool_path("unpackbootimg")
        if not unpackbootimg:
            return TaskResult.error("unpackbootimg not found")
        
        ensure_dir(output_dir)
        
        # Build command
        if str(unpackbootimg).lower().endswith('.py'):
            args = [sys.executable, str(unpackbootimg)]
        else:
            args = [str(unpackbootimg)]
        
        args.extend([
            "--boot_img", str(boot_image),
            "--out", str(output_dir),
        ])
        
        result = run_tool(args)
        
        if result.returncode != 0:
            return TaskResult.error(f"unpackbootimg failed: {result.stderr[:200]}")
        
        elapsed = int((time.time() - start) * 1000)
        log.success(f"[BOOT] Unpacked with unpackbootimg")
        
        return TaskResult.success(
            message=f"Unpacked {boot_image.name}",
            artifacts=[str(output_dir)],
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        return TaskResult.error(str(e))


def unpack_boot_image(
    project: Project,
    boot_image: Path,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Unpack boot image (auto-select tool)
    Output: out/Source/boot/<image_name>/
    """
    log = get_log_bus()
    start = time.time()
    
    log.info(f"[BOOT] Unpacking: {boot_image.name}")
    
    # Output directory
    output_name = boot_image.stem  # e.g., "boot", "vendor_boot"
    output_dir = project.source_dir / "boot" / output_name
    ensure_dir(output_dir)
    
    # Try magiskboot first
    from ..tools.registry import get_tool_registry
    registry = get_tool_registry()
    
    if registry.is_available("magiskboot"):
        result = unpack_with_magiskboot(boot_image, output_dir, _cancel_token)
        if result.ok:
            return result
        log.warning("[BOOT] magiskboot failed, trying unpackbootimg")
    
    # Try unpackbootimg
    if registry.is_available("unpackbootimg"):
        result = unpack_with_unpackbootimg(boot_image, output_dir, _cancel_token)
        if result.ok:
            return result
    
    return TaskResult.error("No boot unpack tool available. Install magiskboot or unpackbootimg.")


def repack_with_magiskboot(
    unpacked_dir: Path,
    output_path: Path,
    _cancel_token: Event = None
) -> TaskResult:
    """Repack boot image using magiskboot"""
    log = get_log_bus()
    start = time.time()
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        magiskboot = registry.get_tool_path("magiskboot")
        if not magiskboot:
            return TaskResult.error("magiskboot not found")
        
        # Run magiskboot repack
        args = [str(magiskboot), "repack", "boot.img"]  # Uses original in cwd
        result = run_tool(args, cwd=unpacked_dir)
        
        if result.returncode != 0:
            return TaskResult.error(f"magiskboot repack failed: {result.stderr[:200]}")
        
        # magiskboot creates new-boot.img
        new_boot = unpacked_dir / "new-boot.img"
        if new_boot.exists():
            shutil.move(str(new_boot), str(output_path))
        else:
            return TaskResult.error("new-boot.img not created")
        
        elapsed = int((time.time() - start) * 1000)
        log.success(f"[BOOT] Repacked: {output_path}")
        
        return TaskResult.success(
            message=f"Repacked to {output_path.name}",
            artifacts=[str(output_path)],
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        return TaskResult.error(str(e))


def repack_with_mkbootimg(
    unpacked_dir: Path,
    output_path: Path,
    _cancel_token: Event = None
) -> TaskResult:
    """Repack boot image using mkbootimg"""
    log = get_log_bus()
    start = time.time()
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        mkbootimg = registry.get_tool_path("mkbootimg")
        if not mkbootimg:
            return TaskResult.error("mkbootimg not found")
        
        # Find components
        kernel = unpacked_dir / "kernel"
        ramdisk = unpacked_dir / "ramdisk.cpio"
        
        if not kernel.exists():
            kernel = list(unpacked_dir.glob("*kernel*"))
            kernel = kernel[0] if kernel else None
        
        if not ramdisk.exists():
            ramdisk = list(unpacked_dir.glob("*ramdisk*"))
            ramdisk = ramdisk[0] if ramdisk else None
        
        if not kernel:
            return TaskResult.error("Kernel not found in unpacked dir")
        
        # Build command
        if str(mkbootimg).lower().endswith('.py'):
            args = [sys.executable, str(mkbootimg)]
        else:
            args = [str(mkbootimg)]
        
        args.extend(["--kernel", str(kernel)])
        if ramdisk:
            args.extend(["--ramdisk", str(ramdisk)])
        args.extend(["--output", str(output_path)])
        
        result = run_tool(args)
        
        if result.returncode != 0:
            return TaskResult.error(f"mkbootimg failed: {result.stderr[:200]}")
        
        elapsed = int((time.time() - start) * 1000)
        log.success(f"[BOOT] Repacked with mkbootimg")
        
        return TaskResult.success(
            message=f"Repacked to {output_path.name}",
            artifacts=[str(output_path)],
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        return TaskResult.error(str(e))


def repack_boot_image(
    project: Project,
    unpacked_dir: Path,
    output_name: str = None,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Repack boot image (auto-select tool)
    Output: out/Image/<name>_repacked.img
    """
    log = get_log_bus()
    
    log.info(f"[BOOT] Repacking: {unpacked_dir.name}")
    
    if not output_name:
        output_name = unpacked_dir.name + "_repacked.img"
    
    output_path = project.image_dir / output_name
    ensure_dir(project.image_dir)
    
    # Try magiskboot first
    from ..tools.registry import get_tool_registry
    registry = get_tool_registry()
    
    if registry.is_available("magiskboot"):
        result = repack_with_magiskboot(unpacked_dir, output_path, _cancel_token)
        if result.ok:
            return result
    
    # Try mkbootimg
    if registry.is_available("mkbootimg"):
        result = repack_with_mkbootimg(unpacked_dir, output_path, _cancel_token)
        if result.ok:
            return result
    
    return TaskResult.error("No boot repack tool available. Install magiskboot or mkbootimg.")
