# RK ROM Kitchen

Công cụ mod ROM dành riêng cho thiết bị **Rockchip** với giao diện hiện đại.

![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows-orange.svg)

> Giao diện clone workflow CRB Android Kitchen.

## Tính năng

### Phase 2 (Real Implementation)
- 🔧 **Extract ROM**: update.img, release_update.img, super.img
- 🏗️ **Build Image**: ext4/erofs từ source folder (raw/sparse/both)
- 🔓 **Disable AVB/dm-verity**: vbmeta_disabled.img + fstab patch B2
- 🗑️ **Debloater**: Scan APK, parse metadata (aapt2), delete to Recycle Bin
- 🔧 **Magisk Patch**: Mode 1 (magiskboot) + Mode 2 (ADB-assisted)
- 📦 **Boot Unpack/Repack**: magiskboot hoặc unpackbootimg/mkbootimg

## Yêu cầu hệ thống

- **OS**: Windows 10/11 (64-bit)
- **Python**: 3.10+
- **RAM**: 4GB+ (khuyến nghị 8GB)

## Cài đặt

```bash
git clone https://github.com/chinhphamhuu/chinh.git
cd chinh/rk_rom_kitchen
pip install -r requirements.txt
run.bat
```

## Tools Required

### Scan tools với Tools Doctor:
```bash
python -m app.tools.registry
```

### Đặt tools vào: `tools/win64/` (bundled trong repo)

#### Required Tools:
| Tool ID | Aliases | Purpose |
|---------|---------|---------|
| `img_unpack` | img_unpack.exe, imgRePackerRK.exe | Rockchip unpack |
| `afptool` | afptool.exe | Rockchip firmware |
| `rkImageMaker` | rkImageMaker.exe | Rockchip image maker |
| `lpunpack` | lpunpack.exe | Super partition unpack |
| `lpmake` | lpmake.exe | Super partition build |
| `lpdump` | lpdump.exe | Super partition dump |
| `simg2img` | simg2img.exe | Sparse to raw |
| `img2simg` | img2simg.exe | Raw to sparse |
| `avbtool` | avbtool.exe, avbtool.py | AVB disable |
| `make_ext4fs` | make_ext4fs.exe | Build ext4 image |
| `extract_erofs` | extract.erofs.exe | Extract erofs partition |
| `mkfs_erofs` | mkfs.erofs.exe | Build erofs image |

#### Optional Tools:
| Tool ID | Aliases | Purpose |
|---------|---------|---------|
| `debugfs` | debugfs.exe | Extract ext4 filesystem (nếu thiếu: ext4 extraction bị giới hạn) |
| `e2fsdroid` | e2fsdroid.exe | Preserve fs_config/SELinux contexts (giảm bootloop A10/11/12) |
| `magiskboot` | magiskboot.exe | Boot unpack/patch |
| `unpackbootimg` | unpackbootimg.exe | Boot unpack alt |
| `mkbootimg` | mkbootimg.exe | Boot repack alt |
| `aapt2` | aapt2.exe | APK metadata |
| `adb` | adb.exe | ADB Magisk mode |

## Workspace Structure

```
%USERPROFILE%\Documents\RK_Kitchen\Projects\
└── project_name/
    ├── in/                    # Input ROM files
    ├── out/
    │   ├── Source/            # Extracted source tree
    │   │   ├── system_a/
    │   │   ├── vendor_a/
    │   │   └── boot/          # Unpacked boot images
    │   └── Image/             # Built images
    ├── temp/
    ├── logs/
    └── config/project.json
```

## ROM Support

| Priority | File | Description |
|----------|------|-------------|
| 1 | `update.img` | Rockchip full firmware |
| 2 | `release_update.img` | Rockchip release firmware |
| 3 | `super.img` | Android super partition |

## Usage Examples

### Build Image
1. Extract ROM → out/Source/
2. Menu: Other → Build Image
3. Chọn partition, filesystem (ext4/erofs), output type (raw/sparse/both)
4. Click Build

### Disable dm-verity
1. Extract ROM
2. Menu: Other → AVB/DM-Verity/Forceencrypt
3. Click "Disable All (A+B)"
4. Output: out/Image/vbmeta_disabled.img + patched fstab

### Magisk Patch
1. Menu: Kernel/Decrypt/Boot → Magisk Patch
2. Select boot.img và Magisk.apk
3. Mode 1: auto với magiskboot
4. Mode 2: ADB-assisted nếu không có magiskboot

### Debloater
1. Menu: Other → Debloater
2. Scan APK
3. Search/filter, select apps
4. Delete to Recycle Bin

## Dev Commands

```bash
# Run app
python -m app.main

# Smoke test
python -m app.tests.smoke_test

# Tools doctor
python -m app.tools.registry

# Build EXE
cd build && build.bat
```

## License
MIT
