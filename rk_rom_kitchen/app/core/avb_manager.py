"""
AVB Manager - Quản lý Android Verified Boot
REAL Implementation:
- Tạo vbmeta_disabled.img bằng avbtool
- Patch fstab (dm-verity, AVB, forceencrypt, fileencryption)
"""
import os
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


def find_vbmeta_files(project: Project) -> List[Path]:
    """Tìm tất cả vbmeta files trong project"""
    vbmeta_names = [
        "vbmeta.img",
        "vbmeta_a.img",
        "vbmeta_system.img", 
        "vbmeta_vendor.img",
    ]
    
    found = []
    search_dirs = [project.in_dir, project.out_dir, project.image_dir]
    
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for name in vbmeta_names:
            path = search_dir / name
            if path.exists():
                found.append(path)
    
    return list(set(found))


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


def create_disabled_vbmeta(
    output_path: Path,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Tạo vbmeta_disabled.img bằng avbtool
    Command: avbtool make_vbmeta_image --flags 2 --padding_size 4096 --output <output>
    """
    log = get_log_bus()
    start = time.time()
    
    log.info(f"[AVB] Creating disabled vbmeta: {output_path.name}")
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        avbtool = registry.get_tool_path("avbtool")
        
        if avbtool:
            # Determine if Python script
            if str(avbtool).endswith('.py'):
                args = ["python", str(avbtool)]
            else:
                args = [str(avbtool)]
            
            args.extend([
                "make_vbmeta_image",
                "--flags", "2",  # AVB_VBMETA_IMAGE_FLAGS_VERIFICATION_DISABLED
                "--padding_size", "4096",
                "--output", str(output_path),
            ])
            
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            if result.returncode == 0 and output_path.exists():
                elapsed = int((time.time() - start) * 1000)
                log.success(f"[AVB] Created via avbtool: {output_path}")
                return TaskResult.success(
                    message=f"Created {output_path.name}",
                    artifacts=[str(output_path)],
                    elapsed_ms=elapsed
                )
            else:
                log.warning(f"[AVB] avbtool failed: {result.stderr[:200]}")
        
        # Fallback: create minimal disabled vbmeta manually
        log.info("[AVB] Creating minimal disabled vbmeta (fallback)")
        
        # AVB vbmeta header format (minimal with flags=2)
        vbmeta_data = bytearray(4096)
        
        # Magic: "AVB0"
        vbmeta_data[0:4] = b'AVB0'
        
        # Required libavb version major: 1
        vbmeta_data[4:8] = (1).to_bytes(4, 'big')
        # Required libavb version minor: 0
        vbmeta_data[8:12] = (0).to_bytes(4, 'big')
        
        # Authentication data block size: 0
        vbmeta_data[12:20] = (0).to_bytes(8, 'big')
        # Aux data block size: 0
        vbmeta_data[20:28] = (0).to_bytes(8, 'big')
        
        # Algorithm type: 0 (NONE)
        vbmeta_data[28:32] = (0).to_bytes(4, 'big')
        
        # Offset and size fields (all zeros for minimal)
        # Hash offset, size, auth offset, size, aux offset, size
        for i in range(6):
            vbmeta_data[32 + i*8 : 40 + i*8] = (0).to_bytes(8, 'big')
        
        # Descriptors offset/size
        vbmeta_data[80:88] = (0).to_bytes(8, 'big')
        vbmeta_data[88:96] = (0).to_bytes(8, 'big')
        
        # Rollback index: 0
        vbmeta_data[96:104] = (0).to_bytes(8, 'big')
        
        # Flags: 2 (VERIFICATION_DISABLED)
        vbmeta_data[120:124] = (2).to_bytes(4, 'big')
        
        # Release string (optional, pad with zeros)
        release_str = b"RK_Kitchen_disabled"
        vbmeta_data[128:128+len(release_str)] = release_str
        
        output_path.write_bytes(vbmeta_data)
        
        elapsed = int((time.time() - start) * 1000)
        log.success(f"[AVB] Created (fallback): {output_path}")
        
        return TaskResult.success(
            message=f"Created {output_path.name} (fallback mode)",
            artifacts=[str(output_path)],
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.error(f"[AVB] Error: {e}")
        return TaskResult.error(str(e), elapsed_ms=elapsed)


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
