"""
Rockchip Update Engine - REAL implementation cho update.img/release_update.img
OUTPUT CONTRACT:
- Partitions images → project.out_image_dir/update/partitions/*.img
- Metadata (parameter.txt, package-file) → project.out_image_dir/update/metadata/
- Filesystem extracted → project.out_source_dir/<partition>/ (auto mode B)
Toolchain: img_unpack/imgRePackerRK hoặc afptool/rkImageMaker
"""
import os
import sys
import time
import json
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


# Partitions that should have filesystem extracted
FS_PARTITIONS = [
    "system", "vendor", "product", "odm", "system_ext",
    "system_a", "vendor_a", "product_a", "odm_a", "system_ext_a",
    "system_b", "vendor_b", "product_b", "odm_b", "system_ext_b",
]


@dataclass
class UpdateMeta:
    """Metadata từ update.img"""
    partitions: List[str] = field(default_factory=list)
    vbmeta_files: List[str] = field(default_factory=list)
    has_super: bool = False
    has_boot: bool = False
    has_init_boot: bool = False
    parameter_found: bool = False
    package_file_found: bool = False
    slot_mode: str = "auto"  # auto/A/B/both


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
    
    try:
        with open(input_path, 'rb') as f:
            header = f.read(16)
        
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
    
    required_tools = ["img_unpack", "rkImageMaker"]
    fallback_tools = ["afptool", "rkImageMaker"]
    
    has_primary = all(registry.is_available(t) for t in required_tools)
    has_fallback = all(registry.is_available(t) for t in fallback_tools)
    
    if not has_primary and not has_fallback:
        missing = [t for t in required_tools if not registry.is_available(t)]
        return False, f"Thiếu tools: {', '.join(missing)}. Vui lòng thêm vào tools/win64/."
    
    # Check disk space
    input_dir = project.in_dir
    rom_files = list(input_dir.glob("*.img"))
    if rom_files:
        total_size = sum(f.stat().st_size for f in rom_files if f.exists())
        required = total_size * 3
        
        try:
            free = shutil.disk_usage(project.root_dir).free
            if free < required:
                return False, f"Không đủ dung lượng disk. Cần: {human_size(required)}, Còn: {human_size(free)}"
        except Exception:
            pass
    
    return True, "OK"


def get_base_name(name: str) -> str:
    """Extract base name from partition (system_a -> system)"""
    lower = name.lower()
    if lower.endswith("_a"):
        return lower[:-2]
    elif lower.endswith("_b"):
        return lower[:-2]
    return lower


def filter_partitions_by_slot(partitions: List[str], slot_mode: str) -> List[str]:
    """
    Filter partitions dựa trên slot_mode
    
    auto: ưu tiên *_a; nếu không có *_a thì lấy *_b; nếu không có cả hai thì lấy base
    A: chỉ *_a (fallback base nếu không có *_a)
    B: chỉ *_b (fallback base nếu không có *_b)
    both: lấy cả *_a và *_b; nếu chỉ có base thì lấy base
    """
    # Build sets of base names that have slot variants
    has_slot_a = set()
    has_slot_b = set()
    base_names = set()
    
    for p in partitions:
        lower = p.lower()
        if lower.endswith("_a"):
            has_slot_a.add(lower[:-2])
        elif lower.endswith("_b"):
            has_slot_b.add(lower[:-2])
        else:
            base_names.add(lower)
    
    result = []
    
    for p in partitions:
        name = p.lower()
        base = get_base_name(name)
        
        if slot_mode == "both":
            # Include *_a and *_b; skip base if any slot variant exists
            if name.endswith("_a") or name.endswith("_b"):
                result.append(p)
            elif base not in has_slot_a and base not in has_slot_b:
                result.append(p)
                
        elif slot_mode == "A":
            # Only *_a; fallback to base if no *_a
            if name.endswith("_a"):
                result.append(p)
            elif not name.endswith("_b"):
                # Include base only if no *_a variant exists
                if base not in has_slot_a:
                    result.append(p)
                    
        elif slot_mode == "B":
            # Only *_b; fallback to base if no *_b
            if name.endswith("_b"):
                result.append(p)
            elif not name.endswith("_a"):
                # Include base only if no *_b variant exists
                if base not in has_slot_b:
                    result.append(p)
                    
        else:  # auto
            # Prefer *_a; if no *_a then *_b; if no slot then base
            if name.endswith("_a"):
                result.append(p)
            elif name.endswith("_b"):
                # Include *_b only if no *_a variant exists
                if base not in has_slot_a:
                    result.append(p)
            else:
                # Include base only if no slot variants exist
                if base not in has_slot_a and base not in has_slot_b:
                    result.append(p)
    
    return result


def preflight_read_file(path: Path, size: int) -> None:
    """Check file readability to catch WinError 1392 (Disk Corrupt)"""
    if not path.exists():
        return
    try:
        with open(path, 'rb') as f:
            f.read(size)
    except OSError as e:
        # 1392 = The file or directory is corrupted and unreadable.
        if getattr(e, 'winerror', 0) == 1392:
            raise RuntimeError(f"LỖI Ổ CỨNG (Corrupt File): {path.name}\nFile bị hỏng vật lý hoặc lỗi file system (WinError 1392).\nVui lòng copy ROM sang ổ đĩa khác và chạy 'chkdsk /f'.")
        raise e

def unpack_with_img_unpack(input_path: Path, output_dir: Path) -> TaskResult:
    """Unpack bằng img_unpack/imgRePackerRK"""
    log = get_log_bus()
    registry = get_tool_registry()
    
    img_unpack = registry.get_tool_path("img_unpack")
    if not img_unpack:
        return TaskResult.error("Tool img_unpack không tìm thấy")
    
    ensure_dir(output_dir)
    
    # HARDENING: Preflight check input + tool
    try:
        preflight_read_file(input_path, 1024 * 1024)  # 1MB
        preflight_read_file(img_unpack, 64 * 1024)    # 64KB
    except RuntimeError as e:
        return TaskResult.error(str(e))
    except Exception as e:
        return TaskResult.error(f"Cannot read file: {e}")
    
    # CWD must be output_dir for safety (some tools write relative)
    # img_unpack usage: tool <input> <output>
    args = [img_unpack, input_path, output_dir]
    log.info(f"[UPDATE] Đang unpack với img_unpack...")
    
    # Check output folder writeability?
    # run_tool
    code, stdout, stderr = run_tool(args, cwd=output_dir, timeout=1800)
    
    if code != 0:
        return TaskResult.error(f"img_unpack failed (code {code}): {stderr[:200]}")
    
    extracted = list(output_dir.glob("*.img")) + list(output_dir.glob("*.bin"))
    if not extracted:
        # Check WinError 1392 pattern in stderr if tool caught it
        if "1392" in stderr or "corrupt" in stderr.lower():
             return TaskResult.error(f"LỖI Ổ CỨNG: Tool báo lỗi corrupt ({stderr[:100]})")
        return TaskResult.error("img_unpack không tạo file output")
    
    log.success(f"[UPDATE] Unpacked {len(extracted)} files")
    return TaskResult.success(message=f"Unpacked {len(extracted)} files")


def unpack_with_afptool(input_path: Path, output_dir: Path) -> TaskResult:
    """Unpack bằng afptool (fallback)"""
    log = get_log_bus()
    registry = get_tool_registry()
    
    afptool = registry.get_tool_path("afptool")
    if not afptool:
        return TaskResult.error("Tool afptool không tìm thấy")
    
    ensure_dir(output_dir)
    
    # HARDENING
    try:
        preflight_read_file(input_path, 1024 * 1024)
        preflight_read_file(afptool, 64 * 1024)
    except RuntimeError as e:
        return TaskResult.error(str(e))
    except Exception as e:
        return TaskResult.error(f"Cannot read file: {e}")
    
    args = [afptool, "-unpack", input_path, output_dir]
    log.info(f"[UPDATE] Đang unpack với afptool...")
    
    code, stdout, stderr = run_tool(args, cwd=output_dir, timeout=1800)
    
    if code != 0:
        return TaskResult.error(f"afptool failed (code {code}): {stderr[:200]}")
    
    # Validate output?
    extracted = list(output_dir.glob("*"))
    if not extracted:
        return TaskResult.error("afptool không tạo output")
        
    log.success(f"[UPDATE] afptool unpack completed")
    return TaskResult.success(message="Unpacked với afptool")


def unpack_update_img(
    project: Project,
    input_path: Path = None,
    auto_extract_fs: bool = True,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Unpack update.img với auto-detect toolchain + auto filesystem extraction
    OUTPUT CONTRACT:
    - Partitions → out/Image/update/partitions/*.img
    - Metadata → out/Image/update/metadata/
    - Filesystem (mode B) → out/Source/<partition>/
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
    
    log.info(f"[UPDATE] Unpack: {input_path.name} ({human_size(input_path.stat().st_size)})")
    
    # Preflight
    ok, msg = preflight_check(project)
    if not ok:
        return TaskResult.error(msg)
    
    # OUTPUT CONTRACT: out/Image/update/partitions
    update_out_dir = project.out_image_dir / "update"
    partitions_dir = update_out_dir / "partitions"
    metadata_dir = update_out_dir / "metadata"
    ensure_dir(partitions_dir)
    ensure_dir(metadata_dir)
    
    # Try img_unpack first
    registry = get_tool_registry()
    
    result = None
    if registry.is_available("img_unpack"):
        result = unpack_with_img_unpack(input_path, partitions_dir)
    
    # Fallback to afptool
    if result is None or not result.ok:
        if registry.is_available("afptool"):
            log.info("[UPDATE] Thử fallback với afptool...")
            result = unpack_with_afptool(input_path, partitions_dir)
    
    if result is None:
        return TaskResult.error("Không có tool nào khả dụng để unpack update.img")
    
    if not result.ok:
        return result
    
    # Scan extracted partitions
    all_partitions = [f.stem for f in partitions_dir.glob("*.img")]
    log.info(f"[UPDATE] Extracted partitions: {', '.join(all_partitions[:15])}")
    
    # Move metadata files
    for meta_file in ["parameter.txt", "parameter", "package-file", "PACKAGE-FILE"]:
        src = partitions_dir / meta_file
        if src.exists():
            dst = metadata_dir / meta_file
            shutil.copy2(src, dst)
            log.info(f"[UPDATE] Saved metadata: {meta_file}")
    
    # Detect vbmeta files
    vbmeta_files = [p for p in all_partitions if "vbmeta" in p.lower()]
    if vbmeta_files:
        log.info(f"[UPDATE] Detected vbmeta: {vbmeta_files}")
    
    # Check for super.img inside update
    has_super = any("super" in p.lower() for p in all_partitions)
    
    # Get slot_mode from project config
    slot_mode = getattr(project.config, 'slot_mode', 'auto')
    
    # Filter partitions by slot
    partitions_to_process = filter_partitions_by_slot(all_partitions, slot_mode)
    
    # Save update metadata
    update_meta = {
        "all_partitions": all_partitions,
        "processed_partitions": partitions_to_process,
        "vbmeta_files": vbmeta_files,
        "has_super": has_super,
        "slot_mode": slot_mode,
        "source_file": str(input_path),
    }
    meta_json = metadata_dir / "update_manifest.json"
    meta_json.write_text(json.dumps(update_meta, indent=2), encoding='utf-8')
    
    # Auto filesystem extraction (mode B)
    fs_extracted = []
    if auto_extract_fs:
        log.info("[UPDATE] Bắt đầu extract filesystem (mode B)...")
        
        # If super.img exists, unpack super first
        super_img = partitions_dir / "super.img"
        if super_img.exists():
            log.info("[UPDATE] Detected super.img, unpacking super partitions...")
            from .super_image_engine import unpack_super_img
            
            # Super output goes to out/Image/super/partitions
            super_result = unpack_super_img(project, super_img, _cancel_token)
            if super_result.ok:
                # Get super partitions and extract their filesystems
                super_partitions_dir = project.out_image_dir / "super" / "partitions"
                if super_partitions_dir.exists():
                    for pimg in super_partitions_dir.glob("*.img"):
                        pname = pimg.stem.lower()
                        # Slot suffix strip: chỉ cắt _a/_b ở cuối
                        base_name = pname[:-2] if pname.endswith("_a") or pname.endswith("_b") else pname
                        if base_name in ["system", "vendor", "product", "odm", "system_ext"]:
                            log.info(f"[UPDATE] Extracting filesystem: {pimg.name}")
                            try:
                                from .partition_image_engine import extract_partition_image
                                fs_result = extract_partition_image(project, pimg, _cancel_token)
                                if fs_result.ok:
                                    fs_extracted.append(pname)
                            except Exception as e:
                                log.warning(f"[UPDATE] Cannot extract {pname}: {e}")
        else:
            # No super, extract directly from update partitions
            for pname in partitions_to_process:
                # Slot suffix strip: chỉ cắt _a/_b ở cuối
                pname_lower = pname.lower()
                base_name = pname_lower[:-2] if pname_lower.endswith("_a") or pname_lower.endswith("_b") else pname_lower
                if base_name in ["system", "vendor", "product", "odm", "system_ext"]:
                    pimg = partitions_dir / f"{pname}.img"
                    if pimg.exists():
                        log.info(f"[UPDATE] Extracting filesystem: {pimg.name}")
                        try:
                            from .partition_image_engine import extract_partition_image
                            fs_result = extract_partition_image(project, pimg, _cancel_token)
                            if fs_result.ok:
                                fs_extracted.append(pname)
                        except Exception as e:
                            log.warning(f"[UPDATE] Cannot extract {pname}: {e}")
    
    elapsed = int((time.time() - start) * 1000)
    
    log.success(f"[UPDATE] Hoàn tất Unpack. Output: {update_out_dir}")
    log.info(f"[UPDATE] → Partitions: out/Image/update/partitions/ ({len(all_partitions)} files)")
    if fs_extracted:
        log.info(f"[UPDATE] → Filesystem: out/Source/ ({', '.join(fs_extracted)})")
    
    return TaskResult.success(
        message=f"Unpacked {len(all_partitions)} partitions, extracted {len(fs_extracted)} filesystems",
        artifacts=[str(partitions_dir)],
        elapsed_ms=elapsed
    )


def repack_update_img(
    project: Project,
    output_name: str = "update_patched.img",
    _cancel_token: Event = None
) -> TaskResult:
    """
    Repack partitions thành update.img
    INPUT: out/Image/update/partitions/
    OUTPUT: out/Image/update/update_patched.img
    """
    log = get_log_bus()
    start = time.time()
    
    # INPUT: out/Image/update/partitions
    partitions_dir = project.out_image_dir / "update" / "partitions"
    metadata_dir = project.out_image_dir / "update" / "metadata"
    
    # Fallback to legacy path
    if not partitions_dir.exists():
        partitions_dir = project.extract_dir / "partitions"
    
    if not partitions_dir.exists():
        return TaskResult.error("Chưa extract partitions. Hãy unpack trước.")
    
    partitions = list(partitions_dir.glob("*.img"))
    if not partitions:
        return TaskResult.error("Không tìm thấy partition images trong extract folder")
    
    log.info(f"[UPDATE] Repack {len(partitions)} partitions...")
    
    # OUTPUT: out/Image/update/update_patched.img
    output_dir = project.out_image_dir / "update"
    ensure_dir(output_dir)
    output_path = output_dir / output_name
    
    registry = get_tool_registry()
    
    rkimage = registry.get_tool_path("rkImageMaker")
    if not rkimage:
        return TaskResult.error("Tool rkImageMaker không tìm thấy. Vui lòng thêm vào tools/win64/.")
    
    # Get parameter and package-file from metadata or generate
    param_file = metadata_dir / "parameter.txt" if metadata_dir.exists() else partitions_dir / "parameter.txt"
    package_file = metadata_dir / "package-file" if metadata_dir.exists() else partitions_dir / "package-file"
    
    if not param_file.exists():
        log.warning("[UPDATE] parameter.txt không tìm thấy, tạo minimal...")
        param_content = """FIRMWARE_VER:1.0
MACHINE_MODEL:RK
MANUFACTURER:Rockchip
CMDLINE:mtdparts=rk29xxnand:0x00000000@0x00004000(uboot),0x00002000@0x00004000(trust),-@0x00000000(rootfs)
"""
        param_file = partitions_dir / "parameter.txt"
        param_file.write_text(param_content, encoding='utf-8')
    
    if not package_file.exists():
        log.warning("[UPDATE] package-file không tìm thấy, tạo từ partitions...")
        lines = ["# Package-File auto-generated", "package-file package-file"]
        for p in partitions:
            lines.append(f"{p.stem}\t{p.name}")
        package_file = partitions_dir / "package-file"
        package_file.write_text('\n'.join(lines), encoding='utf-8')
    
    # Run rkImageMaker
    args = [rkimage, "-RK33", "-pack", "-image", output_path]
    
    log.info(f"[UPDATE] Running rkImageMaker...")
    code, stdout, stderr = run_tool(args, cwd=partitions_dir, timeout=1800)
    
    if code != 0:
        return TaskResult.error(f"rkImageMaker failed: {stderr[:200]}")
    
    if not output_path.exists():
        return TaskResult.error("rkImageMaker không tạo output file")
    
    elapsed = int((time.time() - start) * 1000)
    size = output_path.stat().st_size
    
    log.success(f"[UPDATE] Hoàn tất Repack. Output: {output_path}")
    log.info(f"[UPDATE] → out/Image/update/{output_name} ({human_size(size)})")
    
    return TaskResult.success(
        message=f"Repacked → out/Image/update/{output_name} ({human_size(size)})",
        artifacts=[str(output_path)],
        elapsed_ms=elapsed
    )
