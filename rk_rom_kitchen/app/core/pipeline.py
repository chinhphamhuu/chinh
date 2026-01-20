"""
Pipeline - REAL Pipeline cho Import, Extract, Patch, Build
Không demo, không tạo file giả.
Gọi engines thật: rockchip_update_engine, super_image_engine, partition_image_engine
"""
import time
from pathlib import Path
from typing import Optional
from threading import Event

from .task_defs import TaskResult
from .project_store import Project
from .logbus import get_log_bus
from .utils import ensure_dir, safe_copy, timestamp
from .detect import detect_rom_type, RomType, map_rom_type_to_input_type


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
    
    source_file = Path(source_file)
    log.info(f"[IMPORT] Bắt đầu import: {source_file.name}")
    
    if _check_cancel(_cancel_token, "IMPORT"):
        return TaskResult.cancelled()
    
    try:
        if not source_file.exists():
            return TaskResult.error(f"File không tồn tại: {source_file}")
        
        # Detect ROM type from header
        rom_type = detect_rom_type(source_file)
        log.info(f"[IMPORT] Loại ROM: {rom_type.value}")
        
        # Map to input_type for pipeline
        input_type = map_rom_type_to_input_type(rom_type)
        log.info(f"[IMPORT] Input type: {input_type}")
        
        # Copy to in/
        ensure_dir(project.in_dir)
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
        
        # Update ProjectConfig fields DIRECTLY (không dùng extra)
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
    Gọi đúng engine dựa trên input_type (from config fields, NOT extra)
    """
    log = get_log_bus()
    start = time.time()
    
    log.info("[EXTRACT] Bắt đầu Extract ROM")
    
    if _check_cancel(_cancel_token, "EXTRACT"):
        return TaskResult.cancelled()
    
    try:
        # Get input type from ProjectConfig fields DIRECTLY
        input_type = project.config.input_type or ""
        rom_type = project.config.rom_type or ""
        input_file = project.config.input_file or ""
        
        log.info(f"[EXTRACT] Input type: {input_type}, ROM type: {rom_type}")
        
        # Find input file
        if input_file:
            input_path = Path(input_file)
        else:
            # Auto-detect
            candidates = list(project.in_dir.glob("*.img"))
            if not candidates:
                return TaskResult.error("Không tìm thấy ROM file trong input folder")
            input_path = candidates[0]
        
        if not input_path.exists():
            return TaskResult.error(f"Input file không tồn tại: {input_path}")
        
        # Route to appropriate engine
        result = None
        
        if input_type == "rockchip_update":
            from .rockchip_update_engine import unpack_update_img
            result = unpack_update_img(project, input_path, _cancel_token)
            
        elif input_type == "android_super":
            from .super_image_engine import unpack_super_img
            result = unpack_super_img(project, input_path, _cancel_token)
            
        elif input_type == "partition_image":
            from .partition_image_engine import extract_partition_image
            result = extract_partition_image(project, input_path, _cancel_token)
            
        else:
            # Fallback: try to detect and route
            log.warning(f"[EXTRACT] Unknown input_type '{input_type}', auto-detecting...")
            rom_type_enum = detect_rom_type(input_path)
            new_input_type = map_rom_type_to_input_type(rom_type_enum)
            
            if new_input_type == "rockchip_update":
                from .rockchip_update_engine import unpack_update_img
                result = unpack_update_img(project, input_path, _cancel_token)
            elif new_input_type == "android_super":
                from .super_image_engine import unpack_super_img
                result = unpack_super_img(project, input_path, _cancel_token)
            else:
                from .partition_image_engine import extract_partition_image
                result = extract_partition_image(project, input_path, _cancel_token)
        
        if result and result.ok:
            # Update project state
            project.update_config(extracted=True)
            
            # Create marker for verification
            marker_dir = project.root_dir / "extract"
            ensure_dir(marker_dir)
            marker = marker_dir / "EXTRACTED_OK.txt"
            marker.write_text(f"Extracted at {timestamp()}\n", encoding='utf-8')
        
        return result or TaskResult.error("No engine matched")
        
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
        
        # known_patches definitions to validate against
        SUPPORTED_PATCHES = {"disable_avb", "magisk", "debloat", "disable_dm_verity"}
        
        # Check for unsupported patches
        for patch_name, enabled in patches.items():
            if enabled and patch_name not in SUPPORTED_PATCHES:
                return TaskResult.error(f"Patch '{patch_name}' chưa được hỗ trợ trong phiên bản này")
        
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
        
        # Check results
        failed = [name for name, r in results if not r.ok]
        if failed:
            return TaskResult.error(f"Patch failed: {', '.join(failed)}")
        
        # Update state
        project.update_config(patched=True)
        
        # Create marker
        marker_dir = project.root_dir / "extract"
        ensure_dir(marker_dir)
        marker = marker_dir / "PATCHED_OK.txt"
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
                   selected_partition: str = None,
                   _cancel_token: Event = None) -> TaskResult:
    """
    Step 4: Build output ROM
    Gọi engine phù hợp để repack
    
    selected_partition: nếu partition_image mode, chỉ định partition cần build (optional)
    """
    log = get_log_bus()
    start = time.time()
    
    log.info("[BUILD] Bắt đầu build output ROM")
    
    if _check_cancel(_cancel_token, "BUILD"):
        return TaskResult.cancelled()
    
    try:
        # Get from ProjectConfig fields DIRECTLY
        input_type = project.config.input_type or ""
        rom_type = project.config.rom_type or ""
        output_sparse = getattr(project.config, 'output_sparse', False)
        
        log.info(f"[BUILD] Input type: {input_type}")
        
        # Check super metadata (dual path support)
        super_meta_paths = [
            project.out_image_dir / "super" / "super_metadata.json",
            project.extract_dir / "super_metadata.json",
            project.out_image_dir / "update" / "metadata" / "super_metadata.json",
        ]
        has_super = any(p.exists() for p in super_meta_paths)
        
        result = None
        
        if has_super:
            log.info("[BUILD] Có super.img, rebuild super trước...")
            from .super_image_engine import build_super_img
            
            resize_mode = getattr(project.config, 'super_resize_mode', 'auto')
            result = build_super_img(project, resize_mode=resize_mode, output_sparse=output_sparse, _cancel_token=_cancel_token)
            if not result.ok:
                return result
            log.info("[BUILD] Super rebuilt OK")
        
        # Build based on input type
        if input_type == "rockchip_update":
            from .rockchip_update_engine import repack_update_img
            result = repack_update_img(project, _cancel_token=_cancel_token)
            
        elif input_type == "android_super":
            # Super already built above
            if not has_super:
                from .super_image_engine import build_super_img
                result = build_super_img(project, _cancel_token=_cancel_token)
            else:
                result = TaskResult.success("Super.img đã build ở trên")
                
        elif input_type == "partition_image":
            from .partition_image_engine import repack_partition_image, repack_all_partitions, get_partition_list
            
            if selected_partition:
                # Build specific partition
                log.info(f"[BUILD] Repack Partition: {selected_partition}")
                result = repack_partition_image(project, selected_partition, output_sparse, _cancel_token)
            else:
                # Build all extracted partitions
                partitions = get_partition_list(project)
                if not partitions:
                    return TaskResult.error(
                        "Chưa có dữ liệu extract. Hãy Extract partition trước."
                    )
                
                log.info(f"[BUILD] Repack All: {len(partitions)} partitions")
                result = repack_all_partitions(project, output_sparse, _cancel_token)
            
        else:
            result = TaskResult.error(f"Không hỗ trợ build cho input_type: {input_type}")
        
        if result and result.ok:
            # Validate output exists
            output_imgs = list(project.out_image_dir.rglob("*.img"))
            if not output_imgs:
                return TaskResult.error("Build không tạo output image nào trong out/Image")
            
            project.update_config(built=True)
            
            # Create marker
            out_dir = project.root_dir / "out"
            ensure_dir(out_dir)
            marker = out_dir / "BUILD_OK.txt"
            marker.write_text(f"Built at {timestamp()}\n", encoding='utf-8')
            
            log.success(f"[BUILD] Hoàn tất. Output: out/Image/ ({len(output_imgs)} files)")
        
        return result or TaskResult.error("Build failed")
        
    except Exception as e:
        log.error(f"[BUILD] Lỗi: {e}")
        import traceback
        log.debug(traceback.format_exc())
        return TaskResult.error(str(e))

