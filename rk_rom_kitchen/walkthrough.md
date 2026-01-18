# RK ROM Kitchen - Walkthrough

## Quick Start

### 1. Clone & Install
```bash
git clone https://github.com/chinhphamhuu/chinh.git
cd chinh/rk_rom_kitchen
pip install -r requirements.txt
```

### 2. Download Tools
Download và đặt vào `third_party/tools/win64/`:
- **Required**: img_unpack.exe, afptool.exe, lpunpack.exe, lpmake.exe, simg2img.exe, img2simg.exe, avbtool.py, make_ext4fs.exe
- **Optional**: magiskboot.exe, mkfs.erofs.exe, aapt2.exe

Kiểm tra tools:
```bash
python -m app.tools.registry
```

### 3. Run
```bash
run.bat
```
hoặc
```bash
python -m app.main
```

---

## Workflow Chuẩn

### Bước 1: Tạo Project
- Click "Create Project"
- Nhập tên project
- Workspace: `%USERPROFILE%\Documents\RK_Kitchen\Projects\<name>`

### Bước 2: Import ROM
- Copy ROM vào project/in/
- Hoặc dùng nút Import

### Bước 3: Extract ROM
- Chọn ROM type (update.img / super.img)
- Click Extract
- Output: out/Source/<partition>/

### Bước 4: Mod ROM

#### Build Image (ext4/erofs)
```
Menu: Build → Build Image
- Partition: system_a, vendor_a, product_a
- Filesystem: ext4 (mặc định) hoặc erofs
- Output: raw, sparse, hoặc both
- Auto-detect: file_contexts, fs_config, image size
```

#### Disable dm-verity (A+B)
```
Menu: Other → AVB/DM-Verity/Forceencrypt
A) vbmeta_disabled.img → out/Image/
B) Patch fstab → vendor/etc/fstab.* (backup .bak)
```

#### Debloater
```
Menu: Other → Debloater
1. Scan
2. Search/filter
3. Select apps
4. Delete to Recycle Bin
Log: logs/debloat_removed.txt
```

#### Magisk Patch
```
Menu: Kernel/Decrypt/Boot → Magisk Patch
- Mode 1: magiskboot.exe (tự động)
- Mode 2: ADB-assisted (push boot → user patch → pull)
Output: out/Image/magisk_patched/
```

#### Boot Unpack/Repack
```
Menu: Other → Unpack/Repack boot
- Unpack: out/Source/boot/<name>/
- Repack: out/Image/<name>_repacked.img
```

### Bước 5: Build Output
- Build Image cho từng partition
- Build Super nếu cần (lpmake)
- Flash bằng RKDevTool

---

## File Structure

```
rk_rom_kitchen/
├── app/
│   ├── main.py              # Entry
│   ├── core/
│   │   ├── build_image.py   # ext4/erofs build
│   │   ├── avb_manager.py   # vbmeta + fstab
│   │   ├── boot_manager.py  # unpack/repack
│   │   ├── magisk_patcher.py
│   │   └── debloater.py
│   ├── tools/
│   │   └── registry.py      # Tool detection
│   └── ui/
├── third_party/tools/win64/ # CLI tools
└── requirements.txt
```

---

## Troubleshooting

### Tool not found
```bash
python -m app.tools.registry
```
Download missing tools, đặt vào third_party/tools/win64/

### Build Image failed
- Check source folder tồn tại: out/Source/<partition>/
- Check make_ext4fs.exe hoạt động
- Check image size đủ lớn

### fstab patch không hoạt động
- Kiểm tra vendor_a/etc/fstab.*
- Check file .bak được tạo
- Manual fix nếu cần

### Magisk patch failed
- Mode 1: cần magiskboot.exe
- Mode 2: kết nối device qua ADB, mở Magisk app
