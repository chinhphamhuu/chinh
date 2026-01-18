"""
Pipeline - REAL Pipeline cho Import, Extract, Patch, Build
Không demo, không tạo file giả.
Gọi engines thật: rockchip_update_engine, super_image_engine
"""
import time
from pathlib import Path
from typing import Optional
from threading import Event

from .task_defs import TaskResult
from .project_store import Project
from .logbus import get_log_bus
from .utils import ensure_dir, safe_copy, timestamp
from .detect import detect_rom_type, RomType


def _check_cancel(cancel_token: Optional[Event], step: str) -> bool:
    """Check if cancelled, return True if should stop"""
    if cancel_token and cancel_token.is_set():
        get_log_bus().warning(f"[{step}] Đã hủy bởi user")
        return True
    return False


def pipeline_import(project: Project, 
                    source_file: Path,
                    _cancel_token: Event = None) -> TaskResult:
    """
    Step 1: Import ROM file vào project
    Copy source_file -> project/in/
    """
    log = get_log_bus()
    start = time.time()
    
    log.info(f"[IMPORT] Bắt đầu import: {source_file.name}")
    
    if _check_cancel(_cancel_token, "IMPORT"):
        return TaskResult.cancelled()
    
    try:
        if not source_file.exists():
            return TaskResult.error(f"File không tồn tại: {source_file}")
        
        # Detect ROM type
        rom_type = detect_rom_type(source_file)
        log.info(f"[IMPORT] Loại ROM: {rom_type.value}")
        
        if rom_type == RomType.UNKNOWN:
            log.warning("[IMPORT] Không xác định được loại ROM, tiếp tục import...")
        
        # Copy to in/
        dest = project.in_dir / source_file.name
        log.info(f"[IMPORT] Copying to: {dest}")
        
        # Copy with progress logging
        file_size = source_file.stat().st_size
        copied = 0
        chunk_size = 1024 * 1024 * 10  # 10MB chunks
        
        with open(source_file, 'rb') as src, open(dest, 'wb') as dst:
            while True:
                if _check_cancel(_cancel_token, "IMPORT"):
                    dest.unlink(missing_ok=True)
                    return TaskResult.cancelled()
                
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                dst.write(chunk)
                copied += len(chunk)
                
                progress = int(copied * 100 / file_size) if file_size else 100
                if progress % 20 == 0:
                    log.info(f"[IMPORT] Progress: {progress}%")
        
        # Determine input_type for project
        input_type = "unknown"
        if rom_type in [RomType.UPDATE_IMG, RomType.RELEASE_UPDATE_IMG]:
            input_type = "rockchip_update"
        elif rom_type == RomType.SUPER_IMG:
            input_type = "android_super"
        elif rom_type in [RomType.SPARSE_IMG, RomType.RAW_IMG]:
            input_type = "partition_image"
        
        # Update project config
        project.update_config(
            imported=True,
            input_file=str(dest),
            rom_type=rom_type.value,
            input_type=input_type
        )
        
        elapsed = int((time.time() - start) * 1000)
        log.success(f"[IMPORT] Hoàn thành trong {elapsed}ms")
        
        return TaskResult.success(
            message="Import thành công",
            artifacts=[str(dest)],
            elapsed_ms=elapsed
        )
    
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.error(f"[IMPORT] Lỗi: {e}")
        return TaskResult.error(str(e), elapsed_ms=elapsed)


def pipeline_extract(project: Project,
                     _cancel_token: Event = None) -> TaskResult:
    """
    Step 2: Extract ROM - REAL implementation
    Gọi đúng engine dựa trên input_type
    """
    log = get_log_bus()
    start = time.time()
    
    log.info("[EXTRACT] Bắt đầu Extract ROM")
    
    if _check_cancel(_cancel_token, "EXTRACT"):
        return TaskResult.cancelled()
    
    try:
        # Get input type from project config
        input_type = project.config.extra.get("input_type", "")
        rom_type = project.config.extra.get("rom_type", "")
        
        log.info(f"[EXTRACT] Input type: {input_type}")
        
        # Find input file
        input_file = project.config.extra.get("input_file", "")
        if input_file:
            input_path = Path(input_file)
        else:
            # Auto-detect
            candidates = list(project.in_dir.glob("*.img"))
            if not candidates:
                return TaskResult.error("Không tìm thấy ROM file trong input folder")
            input_path = candidates[0]
        
        # Route to appropriate engine
        if input_type == "rockchip_update" or rom_type in ["update.img", "release_update.img"]:
            from .rockchip_update_engine import unpack_update_img
            result = unpack_update_img(project, input_path, _cancel_token)
            
        elif input_type == "android_super" or rom_type == "super.img":
            from .super_image_engine import unpack_super_img
            result = unpack_super_img(project, input_path, _cancel_token)
            
        elif input_type == "partition_image":
            # TODO: implement partition_image_engine
            log.warning("[EXTRACT] Partition image mode chưa implement")
            result = TaskResult.error("Partition image mode chưa hỗ trợ. Coming soon.")
            
        else:
            # Try auto-detect based on filename
            filename = input_path.name.lower()
            if "update" in filename:
                from .rockchip_update_engine import unpack_update_img
                result = unpack_update_img(project, input_path, _cancel_token)
            elif "super" in filename:
                from .super_image_engine import unpack_super_img
                result = unpack_super_img(project, input_path, _cancel_token)
            else:
                result = TaskResult.error(
                    f"Không xác định được loại ROM: {input_path.name}. "
                    "Hỗ trợ: update.img, super.img"
                )
        
        if result.ok:
            # Update project state
            project.update_config(extracted=True)
            
            # Create marker for verification
            marker = project.root_dir / "extract" / "EXTRACTED_OK.txt"
            ensure_dir(marker.parent)
            marker.write_text(f"Extracted at {timestamp()}\n", encoding='utf-8')
        
        return result
        
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.error(f"[EXTRACT] Lỗi: {e}")
        import traceback
        log.debug(traceback.format_exc())
        return TaskResult.error(str(e), elapsed_ms=elapsed)


def pipeline_patch(project: Project,
                   patches: dict = None,
                   _cancel_token: Event = None) -> TaskResult:
    """
    Step 3: Apply patches
    patches: dict với keys như 'disable_avb', 'debloat', 'magisk'
    """
    log = get_log_bus()
    start = time.time()
    
    patches = patches or {}
    log.info(f"[PATCH] Bắt đầu apply patches: {list(patches.keys())}")
    
    if _check_cancel(_cancel_token, "PATCH"):
        return TaskResult.cancelled()
    
    try:
        results = []
        
        # AVB patch (vbmeta only)
        if patches.get("disable_avb"):
            from .avb_manager import disable_avb_only
            log.info("[PATCH] Patching vbmeta...")
            result = disable_avb_only(project, _cancel_token)
            results.append(("avb", result))
        
        # Magisk patch
        if patches.get("magisk"):
            from .magisk_patcher import patch_boot_with_magisk
            log.info("[PATCH] Patching boot với Magisk...")
            result = patch_boot_with_magisk(
                project,
                patch_init_boot=True,  # Patch cả init_boot nếu có
                _cancel_token=_cancel_token
            )
            results.append(("magisk", result))
        
        # Debloat không apply ở đây, user chọn trong Debloater UI
        
        # Check results
        failed = [name for name, r in results if not r.ok]
        if failed:
            return TaskResult.error(f"Patch failed: {', '.join(failed)}")
        
        # Update state
        project.update_config(patched=True)
        
        # Create marker
        marker = project.root_dir / "extract" / "PATCHED_OK.txt"
        marker.write_text(f"Patched at {timestamp()}\n", encoding='utf-8')
        
        elapsed = int((time.time() - start) * 1000)
        log.success("[PATCH] Patches applied successfully")
        
        return TaskResult.success(
            message=f"Applied {len(results)} patches",
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        log.error(f"[PATCH] Lỗi: {e}")
        return TaskResult.error(str(e))


def pipeline_build(project: Project,
                   _cancel_token: Event = None) -> TaskResult:
    """
    Step 4: Build output ROM
    Gọi engine phù hợp để repack
    """
    log = get_log_bus()
    start = time.time()
    
    log.info("[BUILD] Bắt đầu build output ROM")
    
    if _check_cancel(_cancel_token, "BUILD"):
        return TaskResult.cancelled()
    
    try:
        input_type = project.config.extra.get("input_type", "")
        rom_type = project.config.extra.get("rom_type", "")
        
        # Check if super needs rebuild first
        super_metadata = project.root_dir / "extract" / "super_metadata.json"
        has_super = super_metadata.exists()
        
        if has_super:
            log.info("[BUILD] Có super.img, rebuild super trước...")
            from .super_image_engine import build_super_img
            
            result = build_super_img(project, resize_mode="auto", _cancel_token=_cancel_token)
            if not result.ok:
                return result
            log.info("[BUILD] Super rebuilt OK")
        
        # Build based on input type
        if input_type == "rockchip_update" or rom_type in ["update.img", "release_update.img"]:
            from .rockchip_update_engine import repack_update_img
            result = repack_update_img(project, _cancel_token=_cancel_token)
            
        elif input_type == "android_super" or rom_type == "super.img":
            # Super already built above
            if not has_super:
                from .super_image_engine import build_super_img
                result = build_super_img(project, _cancel_token=_cancel_token)
            else:
                result = TaskResult.success("Super.img đã build ở trên")
                
        else:
            result = TaskResult.error(f"Không hỗ trợ build cho input_type: {input_type}")
        
        if result.ok:
            project.update_config(built=True)
            
            # Create marker
            marker = project.root_dir / "out" / "BUILD_OK.txt"
            ensure_dir(marker.parent)
            marker.write_text(f"Built at {timestamp()}\n", encoding='utf-8')
        
        return result
        
    except Exception as e:
        log.error(f"[BUILD] Lỗi: {e}")
        import traceback
        log.debug(traceback.format_exc())
        return TaskResult.error(str(e))
