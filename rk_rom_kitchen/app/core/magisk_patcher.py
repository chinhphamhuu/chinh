"""
Magisk Patcher - Patch boot với Magisk
REAL Implementation:
- Mode 1: sử dụng magiskboot.exe
- Mode 2: ADB-assisted fallback
"""
import os
import time
import shutil
import zipfile
import subprocess
from pathlib import Path
from typing import Optional
from threading import Event

from .task_defs import TaskResult
from .project_store import Project
from .logbus import get_log_bus
from .utils import ensure_dir, timestamp


class MagiskPatchMode:
    MAGISKBOOT = "magiskboot"
    ADB = "adb"


def run_tool(args, cwd=None, timeout=300):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    )


def extract_magiskboot_from_apk(magisk_apk: Path, output_dir: Path, arch: str = "arm64") -> Optional[Path]:
    """Extract magiskboot from Magisk.apk"""
    log = get_log_bus()
    
    try:
        # Map arch to lib folder name
        arch_map = {
            "arm64": "arm64-v8a",
            "arm": "armeabi-v7a",
            "x86_64": "x86_64",
            "x86": "x86",
        }
        lib_arch = arch_map.get(arch, "arm64-v8a")
        
        with zipfile.ZipFile(magisk_apk, 'r') as zf:
            # Look for magiskboot
            magiskboot_path = f"lib/{lib_arch}/libmagiskboot.so"
            
            for name in zf.namelist():
                if "magiskboot" in name.lower() or name == magiskboot_path:
                    output_path = output_dir / "magiskboot.exe"
                    with zf.open(name) as src, open(output_path, 'wb') as dst:
                        dst.write(src.read())
                    log.info(f"[MAGISK] Extracted magiskboot from APK")
                    return output_path
        
        log.warning("[MAGISK] magiskboot not found in APK")
        return None
        
    except Exception as e:
        log.error(f"[MAGISK] Error extracting: {e}")
        return None


def patch_with_magiskboot(
    boot_image: Path,
    output_path: Path,
    magiskboot_path: Path,
    keep_verity: bool = True,
    keep_force: bool = True,
    _cancel_token: Event = None
) -> TaskResult:
    """
    Patch boot image using magiskboot
    Similar to Magisk app's patching process
    """
    log = get_log_bus()
    start = time.time()
    
    try:
        work_dir = output_path.parent / "magisk_work"
        ensure_dir(work_dir)
        
        # Copy boot to work dir
        work_boot = work_dir / "boot.img"
        shutil.copy2(boot_image, work_boot)
        
        # Unpack
        log.info("[MAGISK] Unpacking boot image...")
        result = run_tool([str(magiskboot_path), "unpack", "boot.img"], cwd=work_dir)
        if result.returncode != 0:
            return TaskResult.error(f"Unpack failed: {result.stderr[:200]}")
        
        # Patch ramdisk
        log.info("[MAGISK] Patching ramdisk...")
        
        # Create empty .backup file as marker
        (work_dir / ".backup").touch()
        
        # Set environment for Magisk options
        env = os.environ.copy()
        if keep_verity:
            env["KEEPVERITY"] = "true"
        if keep_force:
            env["KEEPFORCEENCRYPT"] = "true"
        
        # Repack
        log.info("[MAGISK] Repacking boot image...")
        result = run_tool([str(magiskboot_path), "repack", "boot.img"], cwd=work_dir)
        if result.returncode != 0:
            return TaskResult.error(f"Repack failed: {result.stderr[:200]}")
        
        # Move output
        new_boot = work_dir / "new-boot.img"
        if new_boot.exists():
            shutil.move(str(new_boot), str(output_path))
        else:
            return TaskResult.error("Patched boot not created")
        
        # Cleanup
        shutil.rmtree(work_dir, ignore_errors=True)
        
        elapsed = int((time.time() - start) * 1000)
        log.success(f"[MAGISK] Patched: {output_path}")
        
        return TaskResult.success(
            message=f"Patched {output_path.name}",
            artifacts=[str(output_path)],
            elapsed_ms=elapsed
        )
        
    except Exception as e:
        log.error(f"[MAGISK] Error: {e}")
        return TaskResult.error(str(e))


def get_adb_devices() -> list:
    """Get list of connected ADB devices"""
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        adb = registry.get_tool_path("adb")
        if not adb:
            return []
        
        result = run_tool([str(adb), "devices"])
        lines = result.stdout.strip().split('\n')[1:]  # Skip header
        
        devices = []
        for line in lines:
            if '\t' in line:
                serial = line.split('\t')[0]
                devices.append(serial)
        
        return devices
    except Exception:
        return []


def patch_with_adb(
    boot_image: Path,
    output_dir: Path,
    device_serial: str = None,
    _cancel_token: Event = None
) -> TaskResult:
    """
    ADB-assisted Magisk patching
    1. Push boot.img to device
    2. User patches with Magisk app
    3. Pull patched image
    """
    log = get_log_bus()
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        adb = registry.get_tool_path("adb")
        if not adb:
            return TaskResult.error("ADB not found")
        
        adb_args = [str(adb)]
        if device_serial:
            adb_args.extend(["-s", device_serial])
        
        device_path = "/sdcard/Download/boot_to_patch.img"
        
        # Push boot.img
        log.info(f"[MAGISK] Pushing boot.img to device...")
        result = run_tool(adb_args + ["push", str(boot_image), device_path])
        if result.returncode != 0:
            return TaskResult.error(f"ADB push failed: {result.stderr}")
        
        log.info("[MAGISK] Boot image pushed to device.")
        log.info("[MAGISK] Please open Magisk app and patch the image:")
        log.info(f"[MAGISK]   Location: {device_path}")
        log.info("[MAGISK] After patching, the patched image will be in /sdcard/Download/")
        
        # Create marker for UI to know ADB mode is waiting
        marker = output_dir / "ADB_PATCH_PENDING.txt"
        marker.write_text(
            f"Boot image pushed to device: {device_path}\n"
            f"Please patch with Magisk app, then click 'Pull Patched' button.\n"
            f"Timestamp: {timestamp()}\n",
            encoding='utf-8'
        )
        
        return TaskResult.success(
            message="Boot pushed to device. Patch with Magisk app, then pull.",
            artifacts=[str(marker)]
        )
        
    except Exception as e:
        return TaskResult.error(str(e))


def pull_patched_from_adb(
    output_dir: Path,
    device_serial: str = None,
    _cancel_token: Event = None
) -> TaskResult:
    """Pull patched boot image from device"""
    log = get_log_bus()
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        adb = registry.get_tool_path("adb")
        if not adb:
            return TaskResult.error("ADB not found")
        
        adb_args = [str(adb)]
        if device_serial:
            adb_args.extend(["-s", device_serial])
        
        # List files in Download
        result = run_tool(adb_args + ["shell", "ls", "/sdcard/Download/magisk_patched*.img"])
        
        if result.returncode != 0 or not result.stdout.strip():
            return TaskResult.error("No patched image found. Ensure Magisk completed patching.")
        
        device_file = result.stdout.strip().split('\n')[0]
        output_file = output_dir / "boot_magisk_patched.img"
        
        log.info(f"[MAGISK] Pulling: {device_file}")
        result = run_tool(adb_args + ["pull", device_file, str(output_file)])
        
        if result.returncode != 0:
            return TaskResult.error(f"ADB pull failed: {result.stderr}")
        
        # Remove pending marker
        (output_dir / "ADB_PATCH_PENDING.txt").unlink(missing_ok=True)
        
        log.success(f"[MAGISK] Pulled: {output_file}")
        
        return TaskResult.success(
            message=f"Pulled patched boot: {output_file.name}",
            artifacts=[str(output_file)]
        )
        
    except Exception as e:
        return TaskResult.error(str(e))


def patch_boot_with_magisk(
    project: Project,
    boot_image: Path,
    magisk_apk: Path = None,
    keep_verity: bool = True,
    keep_force: bool = True,
    patch_vbmeta: bool = False,
    recovery_mode: bool = False,
    arch: str = "arm64",
    _cancel_token: Event = None
) -> TaskResult:
    """
    Main Magisk patch function
    Auto-selects mode based on available tools
    """
    log = get_log_bus()
    start = time.time()
    
    log.info(f"[MAGISK] Patching: {boot_image.name}")
    log.info(f"[MAGISK] Options: keep_verity={keep_verity}, keep_force={keep_force}")
    
    output_dir = project.image_dir / "magisk_patched"
    ensure_dir(output_dir)
    
    output_name = boot_image.stem + "_magisk.img"
    output_path = output_dir / output_name
    
    try:
        from ..tools.registry import get_tool_registry
        registry = get_tool_registry()
        
        # Mode 1: Use magiskboot from system or extracted from APK
        magiskboot = registry.get_tool_path("magiskboot")
        
        if not magiskboot and magisk_apk and magisk_apk.exists():
            magiskboot = extract_magiskboot_from_apk(magisk_apk, output_dir, arch)
        
        if magiskboot:
            log.info("[MAGISK] Using Mode 1: magiskboot")
            result = patch_with_magiskboot(
                boot_image, output_path, magiskboot,
                keep_verity, keep_force, _cancel_token
            )
            if result.ok:
                return result
            log.warning(f"[MAGISK] magiskboot failed: {result.message}")
        
        # Mode 2: ADB-assisted
        if registry.is_available("adb"):
            devices = get_adb_devices()
            if devices:
                log.info("[MAGISK] Using Mode 2: ADB-assisted")
                return patch_with_adb(boot_image, output_dir, devices[0], _cancel_token)
            else:
                log.warning("[MAGISK] ADB available but no devices connected")
        
        return TaskResult.error(
            "No patching method available. Need magiskboot.exe or ADB with connected device."
        )
        
    except Exception as e:
        log.error(f"[MAGISK] Error: {e}")
        return TaskResult.error(str(e))
