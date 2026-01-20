"""
AVB Manager - Quản lý Android Verified Boot
REAL Implementation:
- Tạo vbmeta_disabled.img bằng avbtool
- Patch fstab (dm-verity, AVB, forceencrypt, fileencryption)
"""
import os
import sys
import re
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple
from threading import Event

from .task_defs import TaskResult
from .project_store import Project
from .logbus import get_log_bus
from .utils import ensure_dir, timestamp


# Fstab patterns to patch (B2 rules)
FSTAB_PATTERNS = {
    # dm-verity related
    "verify": (r'\bverify\b', ''),
    "avb": (r'\bavb[=,]?[^,\s]*', ''),
    "avb_keys": (r'\bavb_keys=[^,\s]*', ''),
    
    # Verity related
    "verity": (r'\bverity\b', ''),
    "support_scfs": (r'\bsupport_scfs\b', ''),
    
    # Force encryption (B2: disable completely)
    "forceencrypt": (r'\bforceencrypt=[^,\s]*', 'encryptable=footer'),
    "forcefdeorfbe": (r'\bforcefdeorfbe=[^,\s]*', 'encryptable=footer'),
    "fileencryption": (r'\bfileencryption=[^,\s]*', ''),
    "metadata_encryption": (r'\bmetadata_encryption=[^,\s]*', ''),
    
    # Quota (may cause issues if removed, keep but log)
    # "quota": (r'\bquota\b', ''),
}


def scan_vbmeta_targets(project: Project) -> List[Path]:
    """
    Scanner tìm vbmeta targets dựa trên slot_mode.
    Priority: out/Image/update/partitions > in/
    Returns: List output/target paths (để patch).
    """
    input_dirs = [
        project.out_image_dir / "update" / "partitions",
        project.in_dir,
    ]
    
    # 1. Collect all candidates
    candidates = {}  # filename -> Path (full path found)
    
    for d in input_dirs:
        if not d.exists():
            continue
        # Scan vbmeta*.img
        for p in d.glob("vbmeta*.img"):
            if p.name == "vbmeta_disabled.img":
                continue
            if p.name not in candidates:
                candidates[p.name] = p
                
    # 2. Filter by slot_mode
    slot_mode = getattr(project.config, "slot_mode", "auto")
    final_files = []
    
    # helper: group by base (system, vendor, etc) ignoring _a/_b/suffix
    # But vbmeta naming is weird: vbmeta.img, vbmeta_system.img, vbmeta_a.img
    # Let's verify presence based on rules.
    
    all_names = set(candidates.keys())
    
    # If explicit A or B, filter
    if slot_mode == "A":
        # Keep *_a.img, keep no suffix if corresponding _a missing? 
        # User rule: "A: chỉ *_a, fallback base nếu thiếu *_a"
        # Base here implies: vbmeta_system.img vs vbmeta_system_a.img
        
        # We process logical groups.
        # "vbmeta" -> vbmeta.img, vbmeta_a.img
        # "vbmeta_system" -> vbmeta_system.img, vbmeta_system_a.img
        
        # Regex to split base and slot
        # patterns: NAME_a.img, NAME.img
        pass 
        
    # Simplified logic: Just Process ALL, but Filter output list?
    # No, user wants scanner to adhere to rules.
    
    # Grouping
    groups = {} # base -> { 'a': path, 'b': path, 'base': path }
    
    for name, path in candidates.items():
        base = name
        slot = "base"
        
        if name.endswith("_a.img"):
            base = name[:-6] + ".img" # vbmeta_system_a.img -> vbmeta_system.img
            slot = "a"
        elif name.endswith("_b.img"):
            base = name[:-6] + ".img"
            slot = "b"
        
        if base not in groups:
            groups[base] = {}
        groups[base][slot] = path
        
    # Apply Rules
    results = []
    
    for base, variants in groups.items():
        has_a = "a" in variants
        has_b = "b" in variants
        has_base = "base" in variants
        
        if slot_mode == "auto":
            # prefer _a > _b > base (standard logic?) or user said:
            # "auto: prefer *_a nếu tồn tại, fallback *_b, nếu không có suffix thì dùng base"
            if has_a: results.append(variants["a"])
            elif has_b: results.append(variants["b"])
            elif has_base: results.append(variants["base"])
            
        elif slot_mode == "A":
            # Only _a, fallback base
            if has_a: results.append(variants["a"])
            elif has_base: results.append(variants["base"])
            
        elif slot_mode == "B":
            if has_b: results.append(variants["b"])
            elif has_base: results.append(variants["base"])
            
        elif slot_mode == "both":
            # *_a + *_b. Remove base if *_a/_b exists
            if has_a: results.append(variants["a"])
            if has_b: results.append(variants["b"])
            if has_base and not (has_a or has_b):
                 results.append(variants["base"])
                 
    return results


def find_fstab_files(project: Project) -> List[Path]:
    """Tìm fstab files theo ưu tiên"""
    found = []
    
    # Priority: vendor_a > system_a > product_a
    search_configs = [
        (project.source_dir / "vendor_a" / "etc", ["fstab.*", "*fstab*"]),
        (project.source_dir / "system_a" / "etc", ["fstab.*", "*fstab*"]),
        (project.source_dir / "system_a" / "vendor" / "etc", ["fstab.*"]),
        (project.source_dir / "product_a" / "etc", ["fstab.*"]),
    ]
    
    for search_dir, patterns in search_configs:
        if not search_dir.exists():
            continue
        for pattern in patterns:
            for path in search_dir.glob(pattern):
                if path.is_file() and path not in found:
                    # Skip backup files
                    if not path.suffix == '.bak':
                        found.append(path)
    
    return found


def patch_all_vbmeta(
    project: Project,
    _cancel_token: Event = None
) -> TaskResult:
    """Implement Patch Phase 3: Auto-size-preserve vbmeta patching"""
    log = get_log_bus()
    start = time.time()
    
    targets = scan_vbmeta_targets(project)
    if not targets:
        return TaskResult.error("Không tìm thấy vbmeta targets để patch")
        
    log.info(f"[AVB] Found {len(targets)} targets: {[t.name for t in targets]}")
    
    patched_count = 0
    artifacts = []
    
    registry = None
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
    except: pass
    
    avbtool = registry.get_tool_path("avbtool") if registry else None
    
    ensure_dir(project.out_image_dir / "update" / "partitions")
    
    for target in targets:
        if _cancel_token and _cancel_token.is_set():
            break
            
        # Determine output path
        # Nếu target nằm trong out/.../partitions -> overwrite
        # Nếu target nằm trong in/ -> copy to out/.../partitions and overwrite
        
        is_in_out = str(project.out_image_dir) in str(target)
        if is_in_out:
            out_path = target
        else:
            out_path = project.out_image_dir / "update" / "partitions" / target.name
            
        # 1. Get orig size
        orig_size = target.stat().st_size
        
        # 2. Create temp disabled
        temp_path = out_path.with_name(f"temp_{target.name}")
        
        args = []
        if avbtool:
            if str(avbtool).lower().endswith('.py'):
                args = [sys.executable, str(avbtool)]
            else:
                args = [str(avbtool)]
            args.extend([
                "make_vbmeta_image", "--flags", "2",
                "--padding_size", "4096", "--output", str(temp_path)
            ])
            subprocess.run(args, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        
        if not temp_path.exists():
            # Fallback manual creation
            create_minimal_vbmeta(temp_path)
            
        # 3. Size check & Padding
        if temp_path.exists():
            temp_size = temp_path.stat().st_size
            if temp_size > orig_size:
                log.error(f"[AVB] {target.name}: New size ({temp_size}) > Original ({orig_size}). Skipping.")
                temp_path.unlink()
                continue
                
            # Pad
            if temp_size < orig_size:
                padding = orig_size - temp_size
                with open(temp_path, "ab") as f:
                    f.write(b'\x00' * padding)
            
            # 4. Overwrite output safely
            ensure_dir(out_path.parent)
            shutil.move(str(temp_path), str(out_path))
            
            log.info(f"[AVB] Patched: {out_path.name} (size {orig_size})")
            artifacts.append(str(out_path))
            patched_count += 1
            
    if patched_count == 0:
        return TaskResult.error("AVB Patch Failed: No files patched")
        
    log.success(f"[AVB] Patched {patched_count} files successfully")
    return TaskResult.success(
        message=f"Patched {patched_count} vbmeta files",
        artifacts=artifacts,
        elapsed_ms=int((time.time()-start)*1000)
    )


def create_minimal_vbmeta(output_path: Path):
    """Helper create minimal 4k vbmeta (flags=2) for fallback"""
    data = bytearray(4096)
    
    # Magic: "AVB0"
    data[0:4] = b'AVB0'
    
    # Required libavb version major: 1
    data[4:8] = (1).to_bytes(4, 'big')
    # Required libavb version minor: 0
    data[8:12] = (0).to_bytes(4, 'big')
    
    # Authentication data block size: 0
    data[12:20] = (0).to_bytes(8, 'big')
    # Aux data block size: 0
    data[20:28] = (0).to_bytes(8, 'big')
    
    # Algorithm type: 0 (NONE)
    data[28:32] = (0).to_bytes(4, 'big')
    
    # Offset and size fields (all zeros for minimal)
    # Hash offset, size, auth offset, size, aux offset, size
    for i in range(6):
        data[32 + i*8 : 40 + i*8] = (0).to_bytes(8, 'big')
    
    # Descriptors offset/size
    data[80:88] = (0).to_bytes(8, 'big')
    data[88:96] = (0).to_bytes(8, 'big')
    
    # Rollback index: 0
    data[96:104] = (0).to_bytes(8, 'big')
    
    # Flags: 2 (VERIFICATION_DISABLED)
    data[120:124] = (2).to_bytes(4, 'big')
    
    # Release string (optional, pad with zeros)
    release_str = b"RK_Kitchen_disabled"
    data[128:128+len(release_str)] = release_str
    
    output_path.write_bytes(data)


def disable_avb_only(project: Project, _cancel_token: Event=None) -> TaskResult:
    """Redirect to new implementation"""
    return patch_all_vbmeta(project, _cancel_token)


def patch_fstab_line(line: str) -> Tuple[str, List[str]]:
    """Patch một dòng fstab, return (patched_line, list_of_changes)"""
    changes = []
    result = line
    
    for name, (pattern, replacement) in FSTAB_PATTERNS.items():
        if re.search(pattern, result):
            result = re.sub(pattern, replacement, result)
            changes.append(name)
    
    # Clean up multiple commas and trailing commas
    result = re.sub(r',{2,}', ',', result)
    result = re.sub(r',(\s|$)', r'\1', result)
    result = re.sub(r'\s+', ' ', result).strip()
    
    return result, changes


def patch_fstab_file(
    fstab_path: Path,
    backup: bool = True,
    _cancel_token: Event = None
) -> TaskResult:
    """Patch fstab file để disable dm-verity, AVB, forceencrypt"""
    log = get_log_bus()
    start = time.time()
    
    log.info(f"[FSTAB] Patching: {fstab_path}")
    
    try:
        # Read original
        content = fstab_path.read_text(encoding='utf-8', errors='replace')
        lines = content.splitlines()
        
        # Backup
        if backup:
            backup_path = fstab_path.with_suffix(fstab_path.suffix + '.bak')
            if not backup_path.exists():
                shutil.copy2(fstab_path, backup_path)
                log.info(f"[FSTAB] Backup: {backup_path.name}")
        
        # Patch lines
        patched_lines = []
        all_changes = []
        
        for i, line in enumerate(lines):
            # Skip comments and empty lines
            stripped = line.strip()
            if stripped.startswith('#') or not stripped:
                patched_lines.append(line)
                continue
            
            patched, changes = patch_fstab_line(line)
            patched_lines.append(patched)
            
            if changes:
                all_changes.append(f"Line {i+1}: removed {', '.join(changes)}")
        
        # Write patched
        fstab_path.write_text('\n'.join(patched_lines) + '\n', encoding='utf-8')
        
        elapsed = int((time.time() - start) * 1000)
        
        if all_changes:
            log.success(f"[FSTAB] Patched {len(all_changes)} lines")
            for change in all_changes[:5]:
                log.info(f"[FSTAB]   {change}")
            if len(all_changes) > 5:
                log.info(f"[FSTAB]   ... and {len(all_changes)-5} more")
        else:
            log.info("[FSTAB] No changes needed")
        
        return TaskResult.success(
            message=f"Patched {fstab_path.name} ({len(all_changes)} changes)",
            artifacts=[str(fstab_path)],
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.error(f"[FSTAB] Error: {e}")
        return TaskResult.error(str(e), elapsed_ms=elapsed)


def disable_avb_only(
    project: Project,
    _cancel_token: Event = None
) -> TaskResult:
    """Part A only: Create vbmeta_disabled.img"""
    log = get_log_bus()
    
    ensure_dir(project.image_dir)
    output_path = project.image_dir / "vbmeta_disabled.img"
    
    return create_disabled_vbmeta(output_path, _cancel_token)


def disable_fstab_only(
    project: Project,
    _cancel_token: Event = None
) -> TaskResult:
    """Part B only: Patch all fstab files"""
    log = get_log_bus()
    start = time.time()
    
    fstab_list = find_fstab_files(project)
    
    if not fstab_list:
        return TaskResult.error("No fstab files found in extracted tree")
    
    log.info(f"[FSTAB] Found {len(fstab_list)} fstab files")
    
    results = []
    for fstab in fstab_list:
        if _cancel_token and _cancel_token.is_set():
            break
        result = patch_fstab_file(fstab, backup=True, _cancel_token=_cancel_token)
        results.append(result)
    
    elapsed = int((time.time() - start) * 1000)
    ok_count = sum(1 for r in results if r.ok)
    
    if ok_count == 0:
        return TaskResult.error("All fstab patches failed", elapsed_ms=elapsed)
    
    return TaskResult.success(
        message=f"Patched {ok_count}/{len(results)} fstab files",
        elapsed_ms=elapsed
    )


def disable_dm_verity_full(
    project: Project,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Full dm-verity disable (A+B):
    A) Create vbmeta_disabled.img
    B) Patch all fstab files
    """
    log = get_log_bus()
    start = time.time()
    
    log.info("[DM-VERITY] Starting full disable (A+B)")
    
    results = []
    
    try:
        # Part A: vbmeta
        log.info("[DM-VERITY] Part A: Creating vbmeta_disabled.img")
        vbmeta_result = disable_avb_only(project, _cancel_token)
        results.append(("vbmeta", vbmeta_result))
        
        if _cancel_token and _cancel_token.is_set():
            return TaskResult.cancelled()
        
        # Part B: fstab
        log.info("[DM-VERITY] Part B: Patching fstab files")
        fstab_result = disable_fstab_only(project, _cancel_token)
        results.append(("fstab", fstab_result))
        
        elapsed = int((time.time() - start) * 1000)
        
        # Summary
        ok_count = sum(1 for _, r in results if r.ok)
        fail_count = sum(1 for _, r in results if not r.ok)
        
        if fail_count > 0 and ok_count == 0:
            return TaskResult.error("Both A and B failed", elapsed_ms=elapsed)
        
        msg_parts = []
        for name, r in results:
            status = "OK" if r.ok else "FAIL"
            msg_parts.append(f"{name}: {status}")
        
        log.success(f"[DM-VERITY] Completed: {', '.join(msg_parts)}")
        
        return TaskResult.success(
            message=f"Disabled dm-verity: {', '.join(msg_parts)}",
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.error(f"[DM-VERITY] Error: {e}")
        return TaskResult.error(str(e), elapsed_ms=elapsed)


# Compatibility alias (deprecated - use disable_dm_verity_full)
def disable_dm_verity_demo(project: Project, _cancel_token: Event = None) -> TaskResult:
    """Alias for disable_dm_verity_full for backward compatibility"""
    return disable_dm_verity_full(project, _cancel_token)
