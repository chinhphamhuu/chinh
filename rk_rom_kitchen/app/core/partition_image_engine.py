"""
Partition Image Engine - REAL implementation cho partition images (system/vendor/product)
OUTPUT CONTRACT:
- Filesystem extracted → project.out_source_dir/<partition_name>/
- Image output → project.out_image_dir/<partition_name>_patched.img
KHÔNG PLACEHOLDER. Chỉ OK khi output thật tồn tại.
"""
import os
import sys
import time
import json
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, List
from threading import Event
from dataclasses import dataclass

from .task_defs import TaskResult
from .project_store import Project
from .logbus import get_log_bus
from .utils import ensure_dir, human_size
from ..tools.registry import get_tool_registry


# Magic bytes
SPARSE_MAGIC = b'\x3a\xff\x26\xed'
EXT4_MAGIC_OFFSET = 0x438
EXT4_MAGIC = b'\x53\xef'


def run_tool(args: list, cwd: Path = None, timeout: int = 600) -> Tuple[int, str, str]:
    """Run tool, return (returncode, stdout, stderr)"""
    log = get_log_bus()
    cmd_str = ' '.join(str(a) for a in args[:5])
    log.debug(f"[TOOL] {cmd_str}...")
    
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
        return -1, "", f"Timeout after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def read_file_header(file_path: Path, size: int = 16) -> bytes:
    """Read file header bytes safely"""
    try:
        with open(file_path, 'rb') as f:
            return f.read(size)
    except Exception:
        return b''


def is_sparse_image(file_path: Path) -> bool:
    """Check if file is Android sparse image"""
    header = read_file_header(file_path, 4)
    return header == SPARSE_MAGIC


def is_ext4_image(file_path: Path) -> bool:
    """Check if file is ext4 filesystem image"""
    try:
        with open(file_path, 'rb') as f:
            f.seek(EXT4_MAGIC_OFFSET)
            magic = f.read(2)
            return magic == EXT4_MAGIC
    except Exception:
        return False


def is_erofs_image(file_path: Path) -> bool:
    """Check if file is EROFS filesystem image"""
    try:
        with open(file_path, 'rb') as f:
            f.seek(1024)
            magic = f.read(4)
            return magic == b'\xe2\xe1\xf5\xe0'  # EROFS magic
    except Exception:
        return False


def detect_fs_type(img_path: Path) -> str:
    """Detect filesystem type of a raw image"""
    if is_ext4_image(img_path):
        return "ext4"
    if is_erofs_image(img_path):
        return "erofs"
    return "unknown"


def normalize_mount_point(partition_name: str) -> str:
    """
    Normalize mount point to reduce bootloop on Android 10/11/12
    system_a -> system (not /system_a)
    vendor_b -> vendor
    product_a -> product
    
    Returns base name WITHOUT leading slash (for make_ext4fs -a)
    """
    base = partition_name.lower()
    if base.endswith("_a") or base.endswith("_b"):
        base = base[:-2]
    return base


def find_file_contexts(project: Project, partition_name: str, source_root: Path) -> Optional[Path]:
    """
    Find file_contexts for SELinux labeling
    Priority:
    1. project extract/<partition>_file_contexts
    2. source_root/etc/selinux/plat_file_contexts (for system)
    3. source_root/etc/selinux/vendor_file_contexts (for vendor)
    4. source_root/etc/selinux/file_contexts*
    5. source_root/config/file_contexts*
    """
    log = get_log_bus()
    base_name = normalize_mount_point(partition_name)
    
    candidates = [
        # Project extract metadata
        project.extract_dir / f"{partition_name}_file_contexts",
        project.extract_dir / f"{base_name}_file_contexts",
        # Source root selinux
        source_root / "etc" / "selinux" / "plat_file_contexts",
        source_root / "etc" / "selinux" / "vendor_file_contexts",
        source_root / "etc" / "selinux" / "file_contexts",
        source_root / "etc" / "selinux" / "file_contexts.bin",
        # Config folder
        source_root / "config" / "file_contexts",
    ]
    
    # Prefer partition-specific
    if base_name == "vendor":
        # Vendor prefers vendor_file_contexts
        candidates.insert(0, source_root / "etc" / "selinux" / "vendor_file_contexts")
    
    for path in candidates:
        if path.exists() and path.is_file():
            log.debug(f"[METADATA] Found file_contexts: {path}")
            return path
    
    log.debug(f"[METADATA] file_contexts not found for {partition_name}")
    return None


def find_fs_config(project: Project, partition_name: str, source_root: Path) -> Optional[Path]:
    """
    Find fs_config for filesystem permissions
    Priority:
    1. project extract/<partition>_fs_config
    2. source_root/config/fs_config
    3. source_root/etc/fs_config*
    """
    log = get_log_bus()
    base_name = normalize_mount_point(partition_name)
    
    candidates = [
        # Project extract metadata
        project.extract_dir / f"{partition_name}_fs_config",
        project.extract_dir / f"{base_name}_fs_config",
        project.extract_dir / "partition_metadata" / f"{partition_name}_fs_config",
        # Source root
        source_root / "config" / "fs_config",
        source_root / "etc" / "fs_config",
    ]
    
    for path in candidates:
        if path.exists() and path.is_file():
            log.debug(f"[METADATA] Found fs_config: {path}")
            return path
    
    log.debug(f"[METADATA] fs_config not found for {partition_name}")
    return None


def build_ext4_image_best_effort(
    project: Project,
    partition_name: str,
    source_dir: Path,
    output_path: Path,
    output_sparse: bool = False
) -> TaskResult:
    """
    Build ext4 image với best-effort metadata preservation
    
    Priority:
    1. e2fsdroid (khi có file_contexts + tool available)
       - STRICT: nếu fail -> fallback make_ext4fs
    2. make_ext4fs fallback
    
    Naming convention:
    - Raw output: <partition>_patched.raw.img
    - Sparse output: <partition>_patched.img
    
    Returns:
        TaskResult with artifacts = [final_output_path]
    """
    log = get_log_bus()
    registry = get_tool_registry()
    start = time.time()
    
    mount_point = normalize_mount_point(partition_name)
    log.info(f"[EXT4] Rebuild: {partition_name} (mount: /{mount_point})")
    
    # Find metadata
    file_contexts = find_file_contexts(project, partition_name, source_dir)
    fs_config = find_fs_config(project, partition_name, source_dir)
    
    # Log metadata status
    if file_contexts:
        log.info(f"[EXT4] file_contexts: {file_contexts.name}")
    else:
        log.warning("[EXT4] file_contexts: không tìm thấy")
    
    if fs_config:
        log.info(f"[EXT4] fs_config: {fs_config.name} (sẽ áp dụng nếu e2fsdroid hỗ trợ)")
    else:
        log.info("[EXT4] fs_config: không tìm thấy")
    
    # Get tools
    e2fsdroid = registry.get_tool_path("e2fsdroid")
    make_ext4fs = registry.get_tool_path("make_ext4fs")
    
    if not make_ext4fs and not e2fsdroid:
        return TaskResult.error("Thiếu cả e2fsdroid và make_ext4fs. Vui lòng kiểm tra Tools Doctor.")
    
    # Estimate size
    total_size = sum(f.stat().st_size for f in source_dir.rglob("*") if f.is_file())
    # Add 15% overhead + 64MB buffer + 256MB minimum + 4K alignment
    img_size = max(int(total_size * 1.15) + 64 * 1024 * 1024, 256 * 1024 * 1024)
    img_size = (img_size + 4095) & ~4095  # 4K align
    
    # Ensure output dir
    ensure_dir(output_path.parent)
    
    # Naming convention
    base_name = output_path.stem.replace("_patched", "").replace(".raw", "")
    raw_path = output_path.parent / f"{base_name}_patched.raw.img"
    sparse_path = output_path.parent / f"{base_name}_patched.img"
    
    build_success = False
    used_engine = ""
    
    # Try e2fsdroid first if conditions met
    if e2fsdroid and file_contexts and make_ext4fs:
        log.info("[EXT4] Engine: e2fsdroid (với SELinux contexts)")
        used_engine = "e2fsdroid"
        
        # Step 1: Create base ext4 image with make_ext4fs
        # make_ext4fs creates the initial image, e2fsdroid populates metadata
        args_base = [
            make_ext4fs, 
            "-l", str(img_size), 
            "-a", mount_point,  # mount point without slash
            str(raw_path), 
            str(source_dir)
        ]
        log.debug(f"[EXT4] Step 1: Creating base image with make_ext4fs...")
        code, stdout, stderr = run_tool(args_base, timeout=1800)
        
        if code != 0:
            log.error(f"[EXT4] make_ext4fs failed (step 1): {stderr[:300]}")
            # Don't fail yet, will try fallback
        else:
            # Step 2: Apply e2fsdroid for SELinux contexts
            # e2fsdroid args: -e (no journal) -a mount_point -S file_contexts -f source_dir <image>
            args_e2fs = [
                str(e2fsdroid),
                "-e",                           # no journal mode
                "-a", f"/{mount_point}",        # android mount point WITH slash
                "-S", str(file_contexts),       # SELinux file_contexts
                "-f", str(source_dir),          # source directory (REQUIRED!)
            ]
            
            # Add fs_config if available
            if fs_config:
                args_e2fs.extend(["-C", str(fs_config)])
            
            args_e2fs.append(str(raw_path))  # target image
            
            log.debug(f"[EXT4] Step 2: Applying e2fsdroid SELinux contexts...")
            code, stdout, stderr = run_tool(args_e2fs, timeout=1800)
            
            if code != 0:
                # e2fsdroid FAILED - this is an ERROR, not warning
                log.error(f"[EXT4] e2fsdroid FAILED (code={code}): {stderr[:300]}")
                log.warning("[EXT4] Fallback sang make_ext4fs only...")
                # Remove failed output and try fallback
                if raw_path.exists():
                    raw_path.unlink()
            else:
                build_success = True
                log.debug("[EXT4] e2fsdroid completed successfully")
    
    # Fallback to make_ext4fs only if e2fsdroid failed or unavailable
    if not build_success:
        if not make_ext4fs:
            return TaskResult.error("e2fsdroid thất bại và make_ext4fs không có. Không thể build ext4.")
        
        log.info("[EXT4] Engine: make_ext4fs (fallback)")
        used_engine = "make_ext4fs"
        
        if not file_contexts:
            log.warning(
                "[EXT4] Thiếu file_contexts → SELinux contexts có thể sai. "
                "Có thể gây bootloop trên Android 10/11/12."
            )
        
        # make_ext4fs args
        args = [
            str(make_ext4fs),
            "-l", str(img_size),
            "-a", mount_point,  # mount point without slash
        ]
        
        # Add file_contexts if available
        if file_contexts:
            args.extend(["-S", str(file_contexts)])
        
        args.extend([str(raw_path), str(source_dir)])
        
        log.debug(f"[EXT4] Running make_ext4fs...")
        code, stdout, stderr = run_tool(args, timeout=1800)
        
        if code != 0:
            return TaskResult.error(f"make_ext4fs failed: {stderr[:300]}")
        
        build_success = True
    
    # Validate raw output
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        return TaskResult.error(f"Build ext4 thất bại: {raw_path.name} không tồn tại hoặc rỗng")
    
    raw_size = raw_path.stat().st_size
    log.debug(f"[EXT4] Raw image: {human_size(raw_size)}")
    
    # Convert to sparse if requested
    final_path = raw_path
    if output_sparse:
        img2simg = registry.get_tool_path("img2simg")
        if img2simg:
            args = [str(img2simg), str(raw_path), str(sparse_path)]
            code, _, stderr = run_tool(args, timeout=600)
            
            if code == 0 and sparse_path.exists() and sparse_path.stat().st_size > 0:
                raw_path.unlink()  # Remove raw after successful conversion
                final_path = sparse_path
                log.info(f"[EXT4] Converted to sparse: {human_size(sparse_path.stat().st_size)}")
            else:
                log.warning(f"[EXT4] img2simg failed, giữ RAW: {stderr[:100]}")
                final_path = raw_path
        else:
            log.warning("[EXT4] img2simg không có, giữ RAW image")
            final_path = raw_path
    
    # Final validation
    if not final_path.exists() or final_path.stat().st_size == 0:
        return TaskResult.error(f"Build ext4 thất bại: output final không hợp lệ")
    
    elapsed = int((time.time() - start) * 1000)
    final_size = final_path.stat().st_size
    
    log.success(f"[EXT4] Hoàn tất ({used_engine}): {final_path.name} ({human_size(final_size)})")
    
    return TaskResult.success(
        message=f"Built ext4 ({used_engine}): {final_path.name}",
        artifacts=[str(final_path)],
        elapsed_ms=elapsed
    )


def convert_sparse_to_raw(sparse_path: Path, raw_path: Path) -> TaskResult:
    """Convert sparse image to raw using simg2img"""
    log = get_log_bus()
    registry = get_tool_registry()
    
    simg2img = registry.get_tool_path("simg2img")
    if not simg2img:
        return TaskResult.error("Thiếu tool simg2img.exe. Vui lòng kiểm tra Tools Doctor.")
    
    ensure_dir(raw_path.parent)
    
    args = [simg2img, sparse_path, raw_path]
    log.info(f"[PARTITION] Converting sparse → raw: {sparse_path.name}")
    
    code, stdout, stderr = run_tool(args, timeout=600)
    
    if code != 0:
        return TaskResult.error(f"simg2img failed: {stderr[:200]}")
    
    if not raw_path.exists():
        return TaskResult.error("simg2img không tạo output file")
    
    log.success(f"[PARTITION] Converted to raw: {human_size(raw_path.stat().st_size)}")
    return TaskResult.success("Converted sparse to raw")


def extract_ext4_real(img_path: Path, output_dir: Path) -> TaskResult:
    """
    Extract ext4 filesystem using debugfs rdump
    OUTPUT THẬT, không placeholder
    """
    log = get_log_bus()
    registry = get_tool_registry()
    
    # Check debugfs
    debugfs = registry.get_tool_path("debugfs")
    if not debugfs:
        return TaskResult.error(
            "Thiếu tool debugfs.exe để extract ext4. "
            "Vui lòng thêm debugfs.exe vào tools/win64 và kiểm tra Tools Doctor."
        )
    
    ensure_dir(output_dir)
    
    # debugfs -R "rdump / <output_dir>" <image>
    rdump_cmd = f'rdump / "{output_dir}"'
    args = [debugfs, "-R", rdump_cmd, img_path]
    
    log.info(f"[PARTITION] Extracting ext4 với debugfs...")
    code, stdout, stderr = run_tool(args, timeout=1800)
    
    # debugfs có thể return 0 nhưng vẫn có warning trong stderr
    # Check output thật sự có file không
    files = list(output_dir.rglob("*"))
    if not files:
        err_msg = stderr[:300] if stderr else "Không có output"
        return TaskResult.error(f"debugfs rdump không tạo file. Error: {err_msg}")
    
    file_count = len([f for f in files if f.is_file()])
    log.success(f"[PARTITION] ext4 extracted: {file_count} files")
    
    return TaskResult.success(f"Extracted {file_count} files from ext4")


def extract_erofs_real(img_path: Path, output_dir: Path) -> TaskResult:
    """
    Extract EROFS filesystem using extract.erofs
    OUTPUT THẬT, không placeholder
    """
    log = get_log_bus()
    registry = get_tool_registry()
    
    # Use ToolRegistry to find extract_erofs
    erofs_tool = registry.get_tool_path("extract_erofs")
    if not erofs_tool:
        return TaskResult.error(
            "Thiếu tool extract.erofs.exe để extract erofs. "
            "Vui lòng thêm extract.erofs.exe vào tools/win64 và chạy Tools Doctor."
        )
    
    ensure_dir(output_dir)
    
    # extract.erofs -x -i <image> -o <output_dir>
    # Syntax varies by version, try common patterns
    args = [erofs_tool, "-x", "-i", img_path, "-o", output_dir]
    
    log.info(f"[PARTITION] Extracting erofs...")
    code, stdout, stderr = run_tool(args, timeout=1800)
    
    # Check output
    files = list(output_dir.rglob("*"))
    if not files:
        # Try alternative syntax
        args2 = [erofs_tool, img_path, output_dir]
        code, stdout, stderr = run_tool(args2, timeout=1800)
        files = list(output_dir.rglob("*"))
    
    if not files:
        err_msg = stderr[:300] if stderr else "Không có output"
        return TaskResult.error(f"extract.erofs không tạo file. Error: {err_msg}")
    
    file_count = len([f for f in files if f.is_file()])
    log.success(f"[PARTITION] erofs extracted: {file_count} files")
    
    return TaskResult.success(f"Extracted {file_count} files from erofs")


def validate_extract_output(output_dir: Path, partition_name: str) -> Tuple[bool, str]:
    """Validate extraction output thật sự có file"""
    if not output_dir.exists():
        return False, f"Folder không tồn tại: {output_dir}"
    
    files = list(output_dir.rglob("*"))
    file_count = len([f for f in files if f.is_file()])
    
    if file_count == 0:
        return False, f"Folder rỗng: {output_dir}"
    
    return True, f"{file_count} files"


def extract_partition_image(
    project: Project,
    img_path: Path = None,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Extract partition image (system/vendor/product/...)
    OUTPUT CONTRACT:
    - Filesystem → project.out_source_dir/<partition_name>/
    
    Flow:
    1. Convert sparse to raw if needed (intermediate)
    2. Detect fs type (ext4/erofs)
    3. Extract to out/Source/<partition>/
    4. Validate output thật tồn tại
    """
    log = get_log_bus()
    start = time.time()
    
    # Find image
    if img_path is None:
        input_file = project.config.input_file
        if input_file:
            img_path = Path(input_file)
        else:
            candidates = list(project.in_dir.glob("*.img"))
            if not candidates:
                return TaskResult.error("Không tìm thấy partition image trong input folder")
            img_path = candidates[0]
    
    img_path = Path(img_path)
    if not img_path.exists():
        return TaskResult.error(f"Image không tồn tại: {img_path}")
    
    partition_name = img_path.stem
    log.info(f"[PARTITION] Processing: {partition_name} ({human_size(img_path.stat().st_size)})")
    
    # Setup directories
    temp_dir = project.temp_dir
    ensure_dir(temp_dir)
    
    # OUTPUT CONTRACT: filesystem goes to out/Source/<partition>/
    output_dir = project.out_source_dir / partition_name
    ensure_dir(output_dir)
    
    work_img = img_path
    was_sparse = False
    
    # Step 1: Convert sparse to raw if needed
    if is_sparse_image(img_path):
        log.info("[PARTITION] Detected sparse image")
        was_sparse = True
        raw_img = temp_dir / f"{partition_name}_raw.img"
        
        result = convert_sparse_to_raw(img_path, raw_img)
        if not result.ok:
            return result
        work_img = raw_img
    
    # Step 2: Detect filesystem type
    fs_type = detect_fs_type(work_img)
    log.info(f"[PARTITION] Filesystem type: {fs_type}")
    
    # Step 3: Extract based on fs type
    if fs_type == "ext4":
        result = extract_ext4_real(work_img, output_dir)
    elif fs_type == "erofs":
        result = extract_erofs_real(work_img, output_dir)
    else:
        return TaskResult.error(
            f"Không xác định được filesystem type của {partition_name}. "
            "Chỉ hỗ trợ ext4 và erofs."
        )
    
    if not result.ok:
        return result
    
    # Step 4: Validate output THẬT
    valid, msg = validate_extract_output(output_dir, partition_name)
    if not valid:
        return TaskResult.error(f"Extract failed validation: {msg}")
    
    # Save per-partition metadata
    meta_dir = project.extract_dir / "partition_metadata"
    ensure_dir(meta_dir)
    
    metadata = {
        "partition_name": partition_name,
        "original_path": str(img_path),
        "was_sparse": was_sparse,
        "fs_type": fs_type,
        "raw_image_path": str(work_img),
        "out_source_path": str(output_dir),
        "file_count": len(list(output_dir.rglob("*")))
    }
    
    # Save individual partition metadata
    meta_file = meta_dir / f"{partition_name}.json"
    meta_file.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    
    # Update partition index
    index_file = project.extract_dir / "partition_index.json"
    if index_file.exists():
        try:
            index = json.loads(index_file.read_text(encoding='utf-8'))
        except:
            index = {"partitions": []}
    else:
        index = {"partitions": []}
    
    # Add/update this partition in index
    existing = [p for p in index["partitions"] if p.get("partition_name") != partition_name]
    existing.append({
        "partition_name": partition_name,
        "fs_type": fs_type,
        "was_sparse": was_sparse,
        "out_source_path": str(output_dir)
    })
    index["partitions"] = existing
    index_file.write_text(json.dumps(index, indent=2), encoding='utf-8')
    
    elapsed = int((time.time() - start) * 1000)
    
    log.success(f"[PARTITION] Hoàn tất Extract. Output: {output_dir}")
    log.info(f"[PARTITION] → out/Source/{partition_name}/ ({msg})")
    
    return TaskResult.success(
        message=f"Extracted {partition_name} ({fs_type}) → out/Source/{partition_name}/",
        artifacts=[str(output_dir)],
        elapsed_ms=elapsed
    )


def get_partition_list(project: Project) -> list:
    """Get list of extracted partitions from index"""
    index_file = project.extract_dir / "partition_index.json"
    if not index_file.exists():
        return []
    
    try:
        index = json.loads(index_file.read_text(encoding='utf-8'))
        return index.get("partitions", [])
    except:
        return []


def repack_partition_image(
    project: Project,
    partition_name: str,
    output_sparse: bool = False,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Repack partition image from extracted folder
    OUTPUT CONTRACT:
    - Image → project.out_image_dir/<partition_name>_patched.img
    
    MUST provide partition_name. Không chấp nhận None.
    """
    log = get_log_bus()
    start = time.time()
    
    # Validate partition_name
    if not partition_name:
        return TaskResult.error(
            "Chưa chọn partition. Vui lòng chọn trong dropdown hoặc dùng Repack All."
        )
    
    # Load per-partition metadata
    meta_file = project.extract_dir / "partition_metadata" / f"{partition_name}.json"
    if not meta_file.exists():
        # Fallback: legacy path
        legacy_meta = project.extract_dir / "partition_metadata.json"
        if legacy_meta.exists():
            meta_file = legacy_meta
        else:
            return TaskResult.error(
                f"Không tìm thấy metadata cho partition '{partition_name}'. "
                "Hãy Extract partition này trước."
            )
    
    try:
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
    except Exception as e:
        return TaskResult.error(f"Lỗi đọc metadata: {e}")
    
    fs_type = meta.get("fs_type", "unknown")
    
    log.info(f"[PARTITION] Repacking: {partition_name} ({fs_type})")
    
    # Input: out/Source/<partition>/
    source_dir = project.out_source_dir / partition_name
    if not source_dir.exists():
        return TaskResult.error(f"Source không tồn tại: {source_dir}")
    
    # OUTPUT CONTRACT: out/Image/<partition>_patched.img
    out_img_dir = project.out_image_dir
    ensure_dir(out_img_dir)
    output_path = out_img_dir / f"{partition_name}_patched.img"
    
    registry = get_tool_registry()
    
    if fs_type == "ext4":
        # Use best-effort builder với e2fsdroid / make_ext4fs
        result = build_ext4_image_best_effort(
            project=project,
            partition_name=partition_name,
            source_dir=source_dir,
            output_path=output_path,
            output_sparse=output_sparse
        )
        
        if not result.ok:
            return result
        
        # Continue with validation and sparse handling below
        final_path = Path(result.artifacts[0]) if result.artifacts else output_path
            
    elif fs_type == "erofs":
        mkfs_erofs = registry.get_tool_path("mkfs_erofs")
        if not mkfs_erofs:
            return TaskResult.error("Thiếu tool mkfs.erofs.exe. Vui lòng kiểm tra Tools Doctor.")
        
        args = [mkfs_erofs, output_path, source_dir]
        log.info("[PARTITION] Running mkfs.erofs...")
        code, stdout, stderr = run_tool(args, timeout=1800)
        
        if code != 0:
            return TaskResult.error(f"mkfs.erofs failed: {stderr[:200]}")
    else:
        return TaskResult.error(f"Không hỗ trợ repack fs_type: {fs_type}")
    
    # Validate output
    if not output_path.exists():
        return TaskResult.error("Repack không tạo output image")
    
    if output_path.stat().st_size == 0:
        return TaskResult.error("Repack tạo file rỗng")
    
    # Convert to sparse if requested
    final_path = output_path
    if output_sparse:
        img2simg = registry.get_tool_path("img2simg")
        if img2simg:
            sparse_path = out_img_dir / f"{partition_name}_patched_sparse.img"
            args = [img2simg, output_path, sparse_path]
            code, _, _ = run_tool(args)
            if code == 0 and sparse_path.exists():
                output_path.unlink()  # Remove raw
                final_path = sparse_path
    
    elapsed = int((time.time() - start) * 1000)
    size = final_path.stat().st_size
    
    log.success(f"[PARTITION] Hoàn tất Repack. Output: {final_path}")
    log.info(f"[PARTITION] → out/Image/{final_path.name} ({human_size(size)})")
    
    return TaskResult.success(
        message=f"Repacked {partition_name} → out/Image/{final_path.name}",
        artifacts=[str(final_path)],
        elapsed_ms=elapsed
    )


def repack_all_partitions(
    project: Project,
    output_sparse: bool = False,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Repack ALL extracted partitions
    """
    log = get_log_bus()
    start = time.time()
    
    partitions = get_partition_list(project)
    if not partitions:
        return TaskResult.error(
            "Không tìm thấy partition nào. Hãy Extract trước."
        )
    
    log.info(f"[PARTITION] Repack All: {len(partitions)} partitions")
    
    results = []
    for p in partitions:
        pname = p.get("partition_name")
        if not pname:
            continue
        
        result = repack_partition_image(project, pname, output_sparse, _cancel_token)
        results.append((pname, result))
        
        if not result.ok:
            log.warning(f"[PARTITION] Failed: {pname} - {result.message}")
    
    succeeded = [name for name, r in results if r.ok]
    failed = [name for name, r in results if not r.ok]
    
    # Collect artifacts from successful repacks
    artifacts = []
    for name, r in results:
        if r.ok and r.artifacts:
            artifacts.extend(r.artifacts)
    
    # Always include out/Image dir
    if not artifacts:
        artifacts = [str(project.out_image_dir)]
    
    elapsed = int((time.time() - start) * 1000)
    
    if failed:
        log.warning(f"[PARTITION] Repack All: {len(succeeded)} OK, {len(failed)} FAILED")
        return TaskResult.error(
            f"Repack All: {len(succeeded)} succeeded, {len(failed)} failed ({', '.join(failed)})",
            elapsed_ms=elapsed
        )
    
    log.success(f"[PARTITION] Repack All: {len(succeeded)} partitions → out/Image/")
    
    return TaskResult.success(
        message=f"Repacked {len(succeeded)} partitions → out/Image/",
        artifacts=artifacts,
        elapsed_ms=elapsed
    )
