"""
Super Image Engine - REAL implementation cho super.img (dynamic partitions)
OUTPUT CONTRACT:
- Partitions extracted → project.out_image_dir/super/partitions/*.img
- Metadata → project.out_image_dir/super/super_metadata.json
- Super output → project.out_image_dir/super/super_patched.img
MUST: preserve metadata/layout, lpdump bắt buộc, resize mode hybrid
"""
import os
import sys
import re
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
from .utils import ensure_dir, human_size, resolve_relative_path
from .dirty_tracker import is_dirty
from .partition_image_engine import SPARSE_MAGIC
from ..tools.registry import get_tool_registry
import shutil


@dataclass
class PartitionInfo:
    """Thông tin một partition trong super"""
    name: str
    group: str
    size: int
    attributes: str = ""  # readonly, etc.
    extents: List[Dict] = field(default_factory=list)


@dataclass
class SuperMetadata:
    """Metadata của super.img từ lpdump"""
    block_size: int = 4096
    alignment: int = 1048576  # 1MB
    alignment_offset: int = 0
    capacity: int = 0  # Total super capacity
    groups: Dict[str, int] = field(default_factory=dict)  # group_name -> max_size
    partitions: List[PartitionInfo] = field(default_factory=list)
    slot_suffix: str = ""  # _a, _b, or empty
    raw_output: str = ""  # Raw lpdump output for debugging
    
    def to_dict(self) -> dict:
        return {
            "block_size": self.block_size,
            "alignment": self.alignment,
            "capacity": self.capacity,
            "groups": self.groups,
            "partitions": [
                {"name": p.name, "group": p.group, "size": p.size, "attributes": p.attributes}
                for p in self.partitions
            ]
        }


def run_tool(args: List[str], cwd: Path = None, timeout: int = 600) -> Tuple[int, str, str]:
    """Run tool, return (returncode, stdout, stderr)"""
    log = get_log_bus()
    log.debug(f"[TOOL] {' '.join(str(a) for a in args[:4])}...")
    
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


def parse_lpdump_output(output: str) -> SuperMetadata:
    """Parse output của lpdump thành SuperMetadata"""
    meta = SuperMetadata()
    meta.raw_output = output
    
    lines = output.splitlines()
    current_partition = None
    
    for line in lines:
        line = line.strip()
        
        # Block size: 4096
        if line.startswith("Block device"):
            match = re.search(r'size:\s*(\d+)', line)
            if match:
                meta.capacity = int(match.group(1))
        
        # Metadata version / alignment
        if "alignment:" in line.lower():
            match = re.search(r'alignment:\s*(\d+)', line)
            if match:
                meta.alignment = int(match.group(1))
        
        if "block size:" in line.lower():
            match = re.search(r'block size:\s*(\d+)', line, re.IGNORECASE)
            if match:
                meta.block_size = int(match.group(1))
        
        # Group: default max_size: 123456789
        if line.startswith("Group:") or line.startswith("  Group:"):
            match = re.match(r'.*Group:\s*(\w+).*max.*?:\s*(\d+)', line)
            if match:
                meta.groups[match.group(1)] = int(match.group(2))
        
        # Partition: system_a
        if line.startswith("Name:") or "Partition name:" in line:
            match = re.search(r'(?:Name:|Partition name:)\s*(\S+)', line)
            if match:
                name = match.group(1)
                current_partition = PartitionInfo(name=name, group="", size=0)
                meta.partitions.append(current_partition)
        
        # Group: default
        if current_partition and "Group:" in line and "max" not in line.lower():
            match = re.search(r'Group:\s*(\w+)', line)
            if match:
                current_partition.group = match.group(1)
        
        # Size: 123456789
        if current_partition and line.startswith("Size:"):
            match = re.search(r'Size:\s*(\d+)', line)
            if match:
                current_partition.size = int(match.group(1))
        
        # Attributes: readonly
        if current_partition and "Attributes:" in line:
            current_partition.attributes = line.split(":", 1)[-1].strip()
    
    return meta


def dump_super_metadata(
    super_path: Path,
    _cancel_token: Event = None
) -> Tuple[Optional[SuperMetadata], str]:
    """
    Lấy metadata từ super.img bằng lpdump
    Returns: (metadata, error_message)
    """
    log = get_log_bus()
    registry = get_tool_registry()
    
    lpdump = registry.get_tool_path("lpdump")
    if not lpdump:
        return None, "Tool lpdump không tìm thấy. PHẢI có lpdump để thao tác super.img."
    
    args = [lpdump, super_path]
    code, stdout, stderr = run_tool(args, timeout=120)
    
    if code != 0:
        log.error(f"[SUPER] lpdump failed: {stderr}")
        return None, f"lpdump failed: {stderr[:200]}"
    
    if not stdout.strip():
        return None, "lpdump không trả về output"
    
    log.info("[SUPER] Parsing metadata...")
    meta = parse_lpdump_output(stdout)
    
    log.info(f"[SUPER] Capacity: {human_size(meta.capacity)}")
    log.info(f"[SUPER] Groups: {list(meta.groups.keys())}")
    log.info(f"[SUPER] Partitions: {[p.name for p in meta.partitions]}")
    
    return meta, ""


def unpack_super_img(
    project: Project,
    super_path: Path = None,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Unpack super.img với lpunpack
    Output: project.root_dir / extract / partitions / *.img
    """
    log = get_log_bus()
    start = time.time()
    
    registry = get_tool_registry()
    
    # Find super.img
    if super_path is None:
        candidates = list(project.in_dir.glob("super*.img"))
        if not candidates:
            # Check in extracted partitions (from update.img)
            extract_dir = project.root_dir / "extract" / "partitions"
            candidates = list(extract_dir.glob("super*.img"))
        if not candidates:
            return TaskResult.error("Không tìm thấy super.img")
        super_path = candidates[0]
    
    log.info(f"[SUPER] Unpack: {super_path.name}")
    
    # Check tools
    lpunpack = registry.get_tool_path("lpunpack")
    if not lpunpack:
        return TaskResult.error("Tool lpunpack không tìm thấy. Chạy Tools Doctor.")
    
    simg2img = registry.get_tool_path("simg2img")
    
    # Dump metadata first (REQUIRED)
    meta, err = dump_super_metadata(super_path, _cancel_token)
    if not meta:
        return TaskResult.error(f"Lấy metadata thất bại: {err}")
    
    # OUTPUT CONTRACT: out/Image/super/
    super_out_dir = project.out_image_dir / "super"
    partitions_out_dir = super_out_dir / "partitions"
    ensure_dir(partitions_out_dir)
    
    # Save metadata DUAL-WRITE (compatibility)
    meta_dict = meta.to_dict()
    
    # Add original path for copy-through
    try:
        orig_rel = str(super_path.relative_to(project.root_dir))
    except ValueError:
        orig_rel = str(super_path)
    meta_dict["original_super"] = orig_rel
    
    # Path 1: out/Image/super/super_metadata.json (primary)
    meta_file1 = super_out_dir / "super_metadata.json"
    meta_file1.write_text(json.dumps(meta_dict, indent=2), encoding='utf-8')
    log.info(f"[SUPER] Saved metadata: {meta_file1}")
    
    # Path 2: extract/super_metadata.json (legacy/compat)
    extract_dir = project.extract_dir
    ensure_dir(extract_dir)
    meta_file2 = extract_dir / "super_metadata.json"
    meta_file2.write_text(json.dumps(meta_dict, indent=2), encoding='utf-8')
    log.debug(f"[SUPER] Compat metadata: {meta_file2}")
    
    # Check if sparse
    is_sparse = False
    try:
        with open(super_path, 'rb') as f:
            magic = f.read(4)
            is_sparse = magic == b'\x3a\xff\x26\xed'  # Sparse magic
    except Exception:
        pass
    
    # Convert sparse to raw if needed
    work_super = super_path
    if is_sparse and simg2img:
        log.info("[SUPER] Converting sparse to raw...")
        raw_super = project.root_dir / "temp" / "super_raw.img"
        ensure_dir(raw_super.parent)
        
        args = [simg2img, super_path, raw_super]
        code, _, stderr = run_tool(args, timeout=600)
        if code == 0 and raw_super.exists():
            work_super = raw_super
            log.info("[SUPER] Converted to raw")
        else:
            log.warning(f"[SUPER] simg2img failed, trying direct lpunpack: {stderr}")
    
    # Unpack with lpunpack → out/Image/super/partitions/
    args = [lpunpack, work_super, partitions_out_dir]
    log.info("[SUPER] Running lpunpack...")
    code, stdout, stderr = run_tool(args, timeout=1800)
    
    if code != 0:
        log.error(f"[SUPER] lpunpack failed: {stderr}")
        return TaskResult.error(f"lpunpack failed: {stderr[:200]}")
    
    # Validate output THẬT
    extracted = list(partitions_out_dir.glob("*.img"))
    if not extracted:
        return TaskResult.error("lpunpack không tạo partition images")
    
    elapsed = int((time.time() - start) * 1000)
    
    log.success(f"[SUPER] Hoàn tất Unpack. Output: {partitions_out_dir}")
    log.info(f"[SUPER] → out/Image/super/partitions/ ({len(extracted)} partitions)")
    
    return TaskResult.success(
        message=f"Unpacked {len(extracted)} partitions → out/Image/super/partitions/",
        artifacts=[str(f) for f in extracted],
        elapsed_ms=elapsed
    )


def align_size(size: int, alignment: int) -> int:
    """Align size lên alignment boundary"""
    if alignment <= 0:
        return size
    return ((size + alignment - 1) // alignment) * alignment


def validate_resize_strict(
    new_sizes: Dict[str, int],
    meta: SuperMetadata
) -> Tuple[bool, str]:
    """Validate strict mode: new_size <= original size"""
    for part in meta.partitions:
        new_size = new_sizes.get(part.name, part.size)
        if new_size > part.size:
            delta = new_size - part.size
            return False, f"Partition {part.name} vượt {human_size(delta)}. Mode STRICT không cho phép tăng size."
    return True, ""


def validate_resize_auto(
    new_sizes: Dict[str, int],
    meta: SuperMetadata
) -> Tuple[bool, str]:
    """Validate auto mode: total group <= max_size, total <= capacity"""
    # Check by group
    group_totals: Dict[str, int] = {}
    
    for part in meta.partitions:
        new_size = new_sizes.get(part.name, part.size)
        group = part.group or "default"
        group_totals[group] = group_totals.get(group, 0) + new_size
    
    for group, total in group_totals.items():
        max_size = meta.groups.get(group, meta.capacity)
        if total > max_size:
            delta = total - max_size
            return False, f"Group '{group}' vượt {human_size(delta)}. Cần giảm size partitions trong group này."
    
    # Check total capacity
    total_all = sum(group_totals.values())
    if total_all > meta.capacity:
        delta = total_all - meta.capacity
        return False, f"Tổng size vượt capacity {human_size(delta)}. Cần debloat hoặc giảm mod."
    
    return True, ""


def build_super_img(
    project: Project,
    resize_mode: str = "auto",  # "auto" or "strict"
    output_sparse: bool = False,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Build super.img từ partitions đã extract/modify
    MUST: preserve metadata, convert to raw trước khi lpmake
    """
    log = get_log_bus()
    start = time.time()
    
    registry = get_tool_registry()
    
    # Check tools
    lpmake = registry.get_tool_path("lpmake")
    if not lpmake:
        return TaskResult.error("Tool lpmake không tìm thấy")
    
    simg2img = registry.get_tool_path("simg2img")
    img2simg = registry.get_tool_path("img2simg")
    
    # OUTPUT CONTRACT: out/Image/super/
    super_out_dir = project.out_image_dir / "super"
    
    # Load saved metadata from out/Image/super/
    meta_file = super_out_dir / "super_metadata.json"
    if not meta_file.exists():
        # Fallback: try extract dir (legacy)
        meta_file = project.extract_dir / "super_metadata.json"
    
    if not meta_file.exists():
        return TaskResult.error("Không tìm thấy super_metadata.json. Hãy unpack super.img trước.")
    
    try:
        meta_dict = json.loads(meta_file.read_text(encoding='utf-8'))
        meta = SuperMetadata(
            block_size=meta_dict.get("block_size", 4096),
            alignment=meta_dict.get("alignment", 1048576),
            capacity=meta_dict.get("capacity", 0),
            groups=meta_dict.get("groups", {}),
        )
        for p in meta_dict.get("partitions", []):
            meta.partitions.append(PartitionInfo(
                name=p["name"],
                group=p.get("group", "default"),
                size=p.get("size", 0),
                attributes=p.get("attributes", "")
            ))
    except Exception as e:
        return TaskResult.error(f"Lỗi đọc metadata: {e}")

    # =================================================================
    # COPY-THROUGH LOGIC (Anti-Bootloop Phase 2)
    # Check if ALL partitions are CLEAN -> Copy original super
    # =================================================================
    all_clean = True
    for p in meta.partitions:
        if is_dirty(project, p.name):
            all_clean = False
            break
            
    if all_clean:
        orig_rel = meta_dict.get("original_super")
        if orig_rel:
            orig_path = resolve_relative_path(project.root_dir, orig_rel)
            if orig_path.exists():
                log.success(f"[SUPER] Tất cả partitions CLEAN. Thực hiện copy-through super.")
                
                # Check sparse status
                is_orig_sparse = False
                try:
                    with open(orig_path, 'rb') as f:
                        is_orig_sparse = f.read(4) == SPARSE_MAGIC
                except: pass
                
                copy_success = False
                final_artifact = None
                
                if output_sparse:
                    # Requested SPARSE
                    if is_orig_sparse:
                         final_artifact = super_out_dir / "super_patched.img"
                         shutil.copy2(orig_path, final_artifact)
                         copy_success = True
                    else:
                        # Raw -> Sparse (img2simg)
                        if img2simg:
                            tmp_raw = super_out_dir / "super_patched.raw.img"
                            shutil.copy2(orig_path, tmp_raw)
                            final_artifact = super_out_dir / "super_patched.img"
                            code, _, _ = run_tool([img2simg, tmp_raw, final_artifact])
                            if code==0 and final_artifact.exists():
                                tmp_raw.unlink()
                                copy_success = True
                            else:
                                final_artifact = tmp_raw # Fallback raw
                                copy_success = True
                        else:
                            final_artifact = super_out_dir / "super_patched.raw.img"
                            shutil.copy2(orig_path, final_artifact)
                            copy_success = True
                else:
                    # Requested RAW
                    if not is_orig_sparse:
                        final_artifact = super_out_dir / "super_patched.raw.img"
                        shutil.copy2(orig_path, final_artifact)
                        copy_success = True
                    else:
                        # Sparse -> Raw (simg2img)
                        if simg2img:
                            final_artifact = super_out_dir / "super_patched.raw.img"
                            code, _, stderr = run_tool([simg2img, orig_path, final_artifact])
                            if code==0 and final_artifact.exists():
                                copy_success = True
                            else:
                                 return TaskResult.error(f"Lỗi convert sparse->raw super: {stderr}")
                        else:
                            return TaskResult.error("Thiếu simg2img, không thể convert sparse -> raw output cho Super image.")
                
                if copy_success and final_artifact and final_artifact.exists():
                     return TaskResult.success(
                         message=f"Super copy-through: {final_artifact.name}",
                         artifacts=[str(final_artifact)],
                         elapsed_ms=0
                     )
    
    # Needs rebuild if dirty or missing original
    log.info("[SUPER] Rebuilding super image (DIRTY or no original)...")
    # =================================================================
    
    # Partitions from out/Image/super/partitions/
    partitions_dir = super_out_dir / "partitions"
    if not partitions_dir.exists():
        # Fallback: try legacy path
        partitions_dir = project.extract_dir / "partitions"
    
    temp_dir = project.temp_dir / "super_build"
    ensure_dir(temp_dir)
    
    # Prepare partitions (convert to raw if sparse)
    new_sizes: Dict[str, int] = {}
    partition_paths: Dict[str, Path] = {}
    
    for part in meta.partitions:
        img_path = partitions_dir / f"{part.name}.img"
        if not img_path.exists():
            log.warning(f"[SUPER] Partition không tồn tại: {part.name}")
            continue
        
        # Check if sparse
        is_sparse = False
        try:
            with open(img_path, 'rb') as f:
                is_sparse = f.read(4) == b'\x3a\xff\x26\xed'
        except Exception:
            pass
        
        work_path = img_path
        if is_sparse and simg2img:
            log.info(f"[SUPER] Converting {part.name} to raw...")
            raw_path = temp_dir / f"{part.name}.img"
            args = [simg2img, img_path, raw_path]
            code, _, stderr = run_tool(args, timeout=300)
            if code == 0 and raw_path.exists():
                work_path = raw_path
        
        partition_paths[part.name] = work_path
        new_sizes[part.name] = align_size(work_path.stat().st_size, meta.block_size)
    
    # Validate resize
    if resize_mode == "strict":
        ok, err = validate_resize_strict(new_sizes, meta)
    else:
        ok, err = validate_resize_auto(new_sizes, meta)
    
    if not ok:
        return TaskResult.error(err)
    
    # Naming convention:
    # RAW    : super_patched.raw.img
    # SPARSE : super_patched.img
    raw_path = super_out_dir / "super_patched.raw.img"
    sparse_path = super_out_dir / "super_patched.img"
    
    # lpmake always creates RAW output
    ensure_dir(raw_path.parent)
    
    args = [
        lpmake,
        "--metadata-size", "65536",
        "--super-name", "super",
        "--block-size", str(meta.block_size),
        "--device-size", str(meta.capacity),
        "--output", str(raw_path),
    ]
    
    # Add groups
    for group, max_size in meta.groups.items():
        args.extend(["--group", f"{group}:{max_size}"])
    
    # Add partitions
    for part in meta.partitions:
        if part.name not in partition_paths:
            continue
        
        part_path = partition_paths[part.name]
        part_size = new_sizes.get(part.name, part.size)
        attrs = "readonly" if "readonly" in part.attributes.lower() else ""
        
        # --partition name:readonly:size:group --image name=path
        group = part.group or "default"
        args.extend([
            "--partition", f"{part.name}:{attrs}:{part_size}:{group}",
            "--image", f"{part.name}={part_path}"
        ])
    
    log.info(f"[SUPER] Running lpmake ({len(partition_paths)} partitions)...")
    code, stdout, stderr = run_tool(args, timeout=1800)
    
    if code != 0:
        log.error(f"[SUPER] lpmake failed: {stderr}")
        return TaskResult.error(f"lpmake failed: {stderr[:200]}")
    
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        return TaskResult.error("lpmake không tạo output file hợp lệ")
    
    log.debug(f"[SUPER] Raw image: {human_size(raw_path.stat().st_size)}")
    
    # Convert to sparse if requested
    final_path = raw_path
    if output_sparse:
        if img2simg:
            log.info("[SUPER] Converting to sparse...")
            conv_args = [str(img2simg), str(raw_path), str(sparse_path)]
            code, _, conv_stderr = run_tool(conv_args, timeout=300)
            
            if code == 0 and sparse_path.exists() and sparse_path.stat().st_size > 0:
                raw_path.unlink()  # Remove raw after successful convert
                final_path = sparse_path
                log.info(f"[SUPER] Converted to sparse: {human_size(sparse_path.stat().st_size)}")
            else:
                log.warning(f"[SUPER] img2simg failed, giữ RAW: {conv_stderr[:100]}")
                final_path = raw_path
        else:
            log.warning("[SUPER] img2simg không có, giữ RAW image")
            final_path = raw_path
    
    # Final validation
    if not final_path.exists() or final_path.stat().st_size == 0:
        return TaskResult.error("Build super thất bại: output không hợp lệ")
    
    elapsed = int((time.time() - start) * 1000)
    size = final_path.stat().st_size
    
    log.success(f"[SUPER] Built: {final_path.name} ({human_size(size)})")
    
    return TaskResult.success(
        message=f"Built super.img ({human_size(size)})",
        artifacts=[str(final_path)],
        elapsed_ms=elapsed
    )

