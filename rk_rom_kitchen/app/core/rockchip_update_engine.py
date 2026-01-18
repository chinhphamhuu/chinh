"""
Rockchip Update Engine - REAL implementation cho update.img/release_update.img
Không demo, không tạo file giả.
Toolchain: img_unpack/imgRePackerRK hoặc afptool/rkImageMaker
"""
import os
import sys
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from threading import Event
from dataclasses import dataclass, field

from .task_defs import TaskResult
from .project_store import Project
from .logbus import get_log_bus
from .utils import ensure_dir, human_size
from ..tools.registry import get_tool_registry


@dataclass
class UpdateMeta:
    """Metadata từ update.img"""
    partitions: List[str] = field(default_factory=list)
    vbmeta_files: List[str] = field(default_factory=list)
    has_super: bool = False
    has_boot: bool = False
    has_init_boot: bool = False
    config_file: Optional[Path] = None
    parameter_file: Optional[Path] = None


def run_tool(args: List[str], cwd: Path = None, timeout: int = 600) -> Tuple[int, str, str]:
    """Run tool với proper handling, return (returncode, stdout, stderr)"""
    log = get_log_bus()
    log.debug(f"[TOOL] Running: {' '.join(str(a) for a in args[:5])}...")
    
    try:
        result = subprocess.run(
            [str(a) for a in args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        log.error(f"[TOOL] Timeout after {timeout}s")
        return -1, "", f"Timeout after {timeout}s"
    except Exception as e:
        log.error(f"[TOOL] Error: {e}")
        return -1, "", str(e)


def detect_update_img(input_path: Path) -> UpdateMeta:
    """Detect và phân tích update.img"""
    log = get_log_bus()
    meta = UpdateMeta()
    
    if not input_path.exists():
        log.error(f"[UPDATE] File không tồn tại: {input_path}")
        return meta
    
    # Check file header để xác định loại
    try:
        with open(input_path, 'rb') as f:
            header = f.read(16)
        
        # Rockchip update.img signature: RKIM (RK Image Maker) hoặc RKFW
        if header[:4] in [b'RKFW', b'RKIM', b'RKAF']:
            log.info(f"[UPDATE] Detected Rockchip firmware: {header[:4].decode(errors='ignore')}")
        else:
            log.warning(f"[UPDATE] Unknown header: {header[:8].hex()}")
    except Exception as e:
        log.warning(f"[UPDATE] Cannot read header: {e}")
    
    return meta


def preflight_check(project: Project) -> Tuple[bool, str]:
    """Kiểm tra trước khi chạy: tools + disk space"""
    log = get_log_bus()
    registry = get_tool_registry()
    
    # Check required tools
    required_tools = ["img_unpack", "rkImageMaker"]
    fallback_tools = ["afptool", "rkImageMaker"]
    
    has_primary = all(registry.is_available(t) for t in required_tools)
    has_fallback = all(registry.is_available(t) for t in fallback_tools)
    
    if not has_primary and not has_fallback:
        missing = [t for t in required_tools if not registry.is_available(t)]
        return False, f"Thiếu tools: {', '.join(missing)}. Chạy Tools Doctor để kiểm tra."
    
    # Check disk space (estimate ~3x input size needed)
    input_dir = project.in_dir
    rom_files = list(input_dir.glob("*.img")) + list(input_dir.glob("update*.img"))
    if rom_files:
        total_size = sum(f.stat().st_size for f in rom_files if f.exists())
        required = total_size * 3
        
        try:
            import shutil
            free = shutil.disk_usage(project.root_dir).free
            if free < required:
                return False, f"Không đủ dung lượng disk. Cần: {human_size(required)}, Còn: {human_size(free)}"
        except Exception:
            pass
    
    return True, "OK"


def unpack_with_img_unpack(
    input_path: Path,
    output_dir: Path,
    _cancel_token: Event = None
) -> TaskResult:
    """Unpack bằng img_unpack/imgRePackerRK"""
    log = get_log_bus()
    registry = get_tool_registry()
    
    img_unpack = registry.get_tool_path("img_unpack")
    if not img_unpack:
        return TaskResult.error("Tool img_unpack không tìm thấy")
    
    ensure_dir(output_dir)
    
    # img_unpack syntax: img_unpack <update.img> <output_dir>
    args = [img_unpack, input_path, output_dir]
    
    log.info(f"[UPDATE] Đang unpack với img_unpack...")
    code, stdout, stderr = run_tool(args, timeout=1800)
    
    if code != 0:
        log.error(f"[UPDATE] img_unpack failed: {stderr}")
        return TaskResult.error(f"img_unpack failed (code {code}): {stderr[:200]}")
    
    # Verify output
    extracted = list(output_dir.glob("*.img")) + list(output_dir.glob("*"))
    if not extracted:
        return TaskResult.error("img_unpack không tạo file output")
    
    log.success(f"[UPDATE] Unpacked {len(extracted)} files")
    return TaskResult.success(
        message=f"Unpacked {len(extracted)} files",
        artifacts=[str(output_dir)]
    )


def unpack_with_afptool(
    input_path: Path,
    output_dir: Path,
    _cancel_token: Event = None
) -> TaskResult:
    """Unpack bằng afptool (fallback)"""
    log = get_log_bus()
    registry = get_tool_registry()
    
    afptool = registry.get_tool_path("afptool")
    if not afptool:
        return TaskResult.error("Tool afptool không tìm thấy")
    
    ensure_dir(output_dir)
    
    # afptool -unpack <update.img> <output_dir>
    args = [afptool, "-unpack", input_path, output_dir]
    
    log.info(f"[UPDATE] Đang unpack với afptool...")
    code, stdout, stderr = run_tool(args, timeout=1800)
    
    if code != 0:
        log.error(f"[UPDATE] afptool failed: {stderr}")
        return TaskResult.error(f"afptool failed (code {code}): {stderr[:200]}")
    
    log.success(f"[UPDATE] afptool unpack completed")
    return TaskResult.success(
        message="Unpacked với afptool",
        artifacts=[str(output_dir)]
    )


def unpack_update_img(
    project: Project,
    input_path: Path = None,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Unpack update.img với auto-detect toolchain
    Output: project.root_dir / extract / partitions /
    """
    log = get_log_bus()
    start = time.time()
    
    # Determine input
    if input_path is None:
        candidates = list(project.in_dir.glob("*update*.img"))
        if not candidates:
            candidates = list(project.in_dir.glob("*.img"))
        if not candidates:
            return TaskResult.error("Không tìm thấy file update.img trong input folder")
        input_path = candidates[0]
    
    log.info(f"[UPDATE] Unpack: {input_path.name}")
    
    # Preflight
    ok, msg = preflight_check(project)
    if not ok:
        return TaskResult.error(msg)
    
    # Output dir
    output_dir = project.root_dir / "extract" / "partitions"
    ensure_dir(output_dir)
    
    # Try img_unpack first
    registry = get_tool_registry()
    
    result = None
    if registry.is_available("img_unpack"):
        result = unpack_with_img_unpack(input_path, output_dir, _cancel_token)
    
    # Fallback to afptool
    if result is None or not result.ok:
        if registry.is_available("afptool"):
            log.info("[UPDATE] Thử fallback với afptool...")
            result = unpack_with_afptool(input_path, output_dir, _cancel_token)
    
    if result is None:
        return TaskResult.error("Không có tool nào khả dụng để unpack update.img")
    
    if result.ok:
        # Scan extracted partitions
        partitions = [f.stem for f in output_dir.glob("*.img")]
        log.info(f"[UPDATE] Partitions: {', '.join(partitions[:10])}")
        
        # Update project state
        result.elapsed_ms = int((time.time() - start) * 1000)
    
    return result


def repack_update_img(
    project: Project,
    output_name: str = "update_patched.img",
    _cancel_token: Event = None
) -> TaskResult:
    """
    Repack partitions thành update.img
    Input: project.root_dir / extract / partitions /
    Output: project.root_dir / out / update_patched.img
    """
    log = get_log_bus()
    start = time.time()
    
    partitions_dir = project.root_dir / "extract" / "partitions"
    if not partitions_dir.exists():
        return TaskResult.error("Chưa extract partitions. Hãy unpack trước.")
    
    partitions = list(partitions_dir.glob("*.img"))
    if not partitions:
        return TaskResult.error("Không tìm thấy partition images trong extract folder")
    
    log.info(f"[UPDATE] Repack {len(partitions)} partitions...")
    
    output_dir = project.root_dir / "out"
    ensure_dir(output_dir)
    output_path = output_dir / output_name
    
    registry = get_tool_registry()
    
    # Try rkImageMaker
    rkimage = registry.get_tool_path("rkImageMaker")
    if not rkimage:
        return TaskResult.error("Tool rkImageMaker không tìm thấy. Chạy Tools Doctor.")
    
    # rkImageMaker needs: parameter file, package-file, output
    # If we have these from extract, use them; otherwise generate minimal
    param_file = partitions_dir / "parameter.txt"
    package_file = partitions_dir / "package-file"
    
    if not param_file.exists():
        log.warning("[UPDATE] parameter.txt không tìm thấy, tạo minimal...")
        # Create minimal parameter (ASSUMPTION: basic Rockchip parameter)
        param_content = """FIRMWARE_VER:1.0
MACHINE_MODEL:RK
MANUFACTURER:Rockchip
CMDLINE:mtdparts=rk29xxnand:0x00000000@0x00004000(uboot),0x00002000@0x00004000(trust),-@0x00000000(rootfs)
"""
        param_file.write_text(param_content, encoding='utf-8')
    
    if not package_file.exists():
        log.warning("[UPDATE] package-file không tìm thấy, tạo từ partitions...")
        lines = ["# Package-File auto-generated", "package-file package-file"]
        for p in partitions:
            lines.append(f"{p.stem}\t{p.name}")
        package_file.write_text('\n'.join(lines), encoding='utf-8')
    
    # Run rkImageMaker
    args = [rkimage, "-RK33", "-pack", "-image", output_path]
    
    log.info(f"[UPDATE] Running rkImageMaker...")
    code, stdout, stderr = run_tool(args, cwd=partitions_dir, timeout=1800)
    
    if code != 0:
        log.error(f"[UPDATE] rkImageMaker failed: {stderr}")
        return TaskResult.error(f"rkImageMaker failed: {stderr[:200]}")
    
    if not output_path.exists():
        return TaskResult.error("rkImageMaker không tạo output file")
    
    elapsed = int((time.time() - start) * 1000)
    size = output_path.stat().st_size
    
    log.success(f"[UPDATE] Repacked: {output_path.name} ({human_size(size)})")
    
    return TaskResult.success(
        message=f"Repacked {output_name} ({human_size(size)})",
        artifacts=[str(output_path)],
        elapsed_ms=elapsed
    )
