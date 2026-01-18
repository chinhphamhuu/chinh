"""
Debloater - Scan và xóa APK bloatware
REAL Implementation với:
- Phase 1: List APK + size + partition
- Phase 2: Parse metadata với aapt2 hoặc androguard
- Delete to Recycle Bin với send2trash
"""
import os
import time
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from threading import Event

from .task_defs import TaskResult
from .project_store import Project
from .logbus import get_log_bus
from .utils import human_size, ensure_dir

# Try import send2trash for Recycle Bin support
try:
    from send2trash import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False


@dataclass
class ApkInfo:
    """Thông tin một APK file"""
    filename: str
    path: Path
    size: int
    partition: str
    # Metadata (Phase 2)
    package_name: str = ""
    app_name: str = ""
    version_code: str = ""
    version_name: str = ""
    min_sdk: str = ""
    target_sdk: str = ""
    permissions: List[str] = field(default_factory=list)
    
    @property
    def size_str(self) -> str:
        return human_size(self.size)
    
    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "path": str(self.path),
            "size": self.size,
            "partition": self.partition,
            "package_name": self.package_name,
            "app_name": self.app_name,
            "version_code": self.version_code,
            "version_name": self.version_name,
        }


def scan_apks(project: Project, _cancel_token: Event = None) -> List[ApkInfo]:
    """
    Scan tất cả APK files trong extracted tree
    """
    log = get_log_bus()
    log.info("[DEBLOAT] Scanning APK files...")
    
    apks = []
    
    # Search paths
    partitions = ["system_a", "system", "product_a", "product", "vendor_a", "vendor", "odm_a", "odm"]
    app_dirs = ["app", "priv-app"]
    
    for partition in partitions:
        if _cancel_token and _cancel_token.is_set():
            break
        
        partition_dir = project.source_dir / partition
        if not partition_dir.exists():
            continue
        
        for app_dir in app_dirs:
            search_dir = partition_dir / app_dir
            if not search_dir.exists():
                continue
            
            for apk_path in search_dir.rglob("*.apk"):
                if _cancel_token and _cancel_token.is_set():
                    break
                
                try:
                    stat = apk_path.stat()
                    
                    apk_info = ApkInfo(
                        filename=apk_path.name,
                        path=apk_path,
                        size=stat.st_size,
                        partition=f"{partition}/{app_dir}",
                    )
                    apks.append(apk_info)
                    
                except Exception as e:
                    log.warning(f"[DEBLOAT] Error scanning {apk_path.name}: {e}")
    
    log.info(f"[DEBLOAT] Found {len(apks)} APK files")
    return apks


def parse_apk_metadata_aapt2(apk_path: Path) -> Dict[str, Any]:
    """Parse APK metadata using aapt2"""
    log = get_log_bus()
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        aapt2 = registry.get_tool_path("aapt2")
        if not aapt2:
            return {}
        
        result = subprocess.run(
            [str(aapt2), "dump", "badging", str(apk_path)],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        if result.returncode != 0:
            return {}
        
        output = result.stdout
        metadata = {}
        
        # Parse package line
        import re
        pkg_match = re.search(r"package: name='([^']+)' versionCode='([^']+)' versionName='([^']*)'", output)
        if pkg_match:
            metadata["package_name"] = pkg_match.group(1)
            metadata["version_code"] = pkg_match.group(2)
            metadata["version_name"] = pkg_match.group(3)
        
        # Parse application label
        label_match = re.search(r"application-label:'([^']*)'", output)
        if label_match:
            metadata["app_name"] = label_match.group(1)
        
        # Parse SDK versions
        sdk_match = re.search(r"sdkVersion:'([^']+)'", output)
        if sdk_match:
            metadata["min_sdk"] = sdk_match.group(1)
        
        target_match = re.search(r"targetSdkVersion:'([^']+)'", output)
        if target_match:
            metadata["target_sdk"] = target_match.group(1)
        
        # Parse permissions
        permissions = re.findall(r"uses-permission: name='([^']+)'", output)
        metadata["permissions"] = permissions[:20]  # Limit to 20
        
        return metadata
        
    except Exception as e:
        log.debug(f"[DEBLOAT] aapt2 parse error: {e}")
        return {}


def parse_apk_metadata_androguard(apk_path: Path) -> Dict[str, Any]:
    """Parse APK metadata using androguard (Python library)"""
    try:
        from androguard.core.bytecodes.apk import APK
        
        apk = APK(str(apk_path))
        
        return {
            "package_name": apk.get_package() or "",
            "app_name": apk.get_app_name() or "",
            "version_code": apk.get_androidversion_code() or "",
            "version_name": apk.get_androidversion_name() or "",
            "min_sdk": apk.get_min_sdk_version() or "",
            "target_sdk": apk.get_target_sdk_version() or "",
            "permissions": list(apk.get_permissions())[:20],
        }
    except ImportError:
        return {}
    except Exception:
        return {}


def parse_apk_metadata(apk_path: Path) -> Dict[str, Any]:
    """Parse APK metadata (try aapt2 first, then androguard)"""
    # Try aapt2
    metadata = parse_apk_metadata_aapt2(apk_path)
    if metadata:
        return metadata
    
    # Try androguard
    return parse_apk_metadata_androguard(apk_path)


def enrich_apk_info(apks: List[ApkInfo], _cancel_token: Event = None) -> List[ApkInfo]:
    """Enrich APK list with metadata (Phase 2)"""
    log = get_log_bus()
    log.info(f"[DEBLOAT] Parsing metadata for {len(apks)} APKs...")
    
    for i, apk in enumerate(apks):
        if _cancel_token and _cancel_token.is_set():
            break
        
        if i % 10 == 0:
            log.info(f"[DEBLOAT] Progress: {i}/{len(apks)}")
        
        try:
            metadata = parse_apk_metadata(apk.path)
            if metadata:
                apk.package_name = metadata.get("package_name", "")
                apk.app_name = metadata.get("app_name", "")
                apk.version_code = metadata.get("version_code", "")
                apk.version_name = metadata.get("version_name", "")
                apk.min_sdk = metadata.get("min_sdk", "")
                apk.target_sdk = metadata.get("target_sdk", "")
                apk.permissions = metadata.get("permissions", [])
        except Exception as e:
            log.debug(f"[DEBLOAT] Metadata error for {apk.filename}: {e}")
    
    log.info("[DEBLOAT] Metadata parsing complete")
    return apks


def delete_to_recycle_bin(path: Path) -> bool:
    """Move file to Recycle Bin"""
    if HAS_SEND2TRASH:
        try:
            send2trash(str(path))
            return True
        except Exception:
            pass
    return False


def delete_file(path: Path, use_recycle_bin: bool = True) -> bool:
    """Delete file - try Recycle Bin first, then permanent"""
    if use_recycle_bin and delete_to_recycle_bin(path):
        return True
    
    # Permanent delete
    try:
        if path.is_dir():
            import shutil
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except Exception:
        return False


def delete_apks(
    project: Project,
    apks: List[ApkInfo],
    use_recycle_bin: bool = True,
    _cancel_token: Event = None
) -> TaskResult:
    """Delete selected APK files"""
    log = get_log_bus()
    start = time.time()
    
    log.info(f"[DEBLOAT] Deleting {len(apks)} APK files")
    
    deleted = []
    failed = []
    
    for apk in apks:
        if _cancel_token and _cancel_token.is_set():
            log.warning("[DEBLOAT] Cancelled")
            break
        
        try:
            if delete_file(apk.path, use_recycle_bin):
                deleted.append(apk.filename)
                log.info(f"[DEBLOAT] Deleted: {apk.filename}")
                
                # Try to delete empty parent folder
                parent = apk.path.parent
                if parent.exists() and parent != project.source_dir:
                    try:
                        if not any(parent.iterdir()):
                            parent.rmdir()
                    except Exception:
                        pass
            else:
                failed.append(apk.filename)
                log.error(f"[DEBLOAT] Failed: {apk.filename}")
                
        except Exception as e:
            failed.append(apk.filename)
            log.error(f"[DEBLOAT] Error: {apk.filename}: {e}")
    
    # Log to file
    try:
        ensure_dir(project.logs_dir)
        log_file = project.logs_dir / "debloat_removed.txt"
        with open(log_file, 'a', encoding='utf-8') as f:
            from .utils import timestamp
            f.write(f"\n--- {timestamp()} ---\n")
            for name in deleted:
                f.write(f"DELETED: {name}\n")
            for name in failed:
                f.write(f"FAILED: {name}\n")
    except Exception:
        pass
    
    # Update project config
    try:
        current_list = project.config.debloated_apps or []
        project.update_config(debloated_apps=current_list + deleted)
    except Exception:
        pass
    
    elapsed = int((time.time() - start) * 1000)
    
    if failed:
        log.warning(f"[DEBLOAT] Deleted {len(deleted)}, Failed {len(failed)}")
        return TaskResult.error(
            f"Deleted {len(deleted)}, Failed {len(failed)}",
            elapsed_ms=elapsed
        )
    
    log.success(f"[DEBLOAT] Deleted {len(deleted)} APKs in {elapsed}ms")
    return TaskResult.success(
        message=f"Deleted {len(deleted)} APKs",
        elapsed_ms=elapsed
    )
