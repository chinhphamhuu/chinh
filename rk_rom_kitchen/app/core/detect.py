"""
ROM Detection - Detect loại ROM dựa trên HEADER (ưu tiên) và filename (fallback)
Priority: Header magic > filename pattern
"""
from pathlib import Path
from typing import Optional, Tuple
from enum import Enum

from .errors import RomDetectError


class RomType(Enum):
    """Các loại ROM được hỗ trợ"""
    UPDATE_IMG = "update.img"           # Rockchip update image
    RELEASE_UPDATE_IMG = "release_update.img"
    SUPER_IMG = "super.img"             # Android dynamic partitions
    SPARSE_IMG = "sparse.img"           # Android sparse image
    RAW_IMG = "raw.img"                 # Raw partition image
    UNKNOWN = "unknown"


# Magic bytes for header detection
ROCKCHIP_MAGICS = [b'RKFW', b'RKAF', b'RKIM']
SPARSE_MAGIC = b'\x3a\xff\x26\xed'  # 0xED26FF3A little-endian
EXT4_MAGIC_OFFSET = 0x438
EXT4_MAGIC = b'\x53\xef'  # Little-endian 0xEF53


def read_file_header(file_path: Path, size: int = 16) -> bytes:
    """Read file header bytes safely"""
    try:
        with open(file_path, 'rb') as f:
            return f.read(size)
    except Exception:
        return b''


def is_rockchip_header(header: bytes) -> bool:
    """Check if header contains Rockchip magic"""
    if len(header) < 4:
        return False
    magic = header[:4]
    return magic in ROCKCHIP_MAGICS


def is_sparse_header(header: bytes) -> bool:
    """Check if header contains Android sparse magic"""
    if len(header) < 4:
        return False
    return header[:4] == SPARSE_MAGIC


def is_ext4_image(file_path: Path) -> bool:
    """Check if file is ext4 filesystem image"""
    try:
        with open(file_path, 'rb') as f:
            f.seek(EXT4_MAGIC_OFFSET)
            magic = f.read(2)
            return magic == EXT4_MAGIC
    except Exception:
        return False


def detect_rom_type(file_path: Path) -> RomType:
    """
    Detect loại ROM từ file path
    Priority:
    1. Header magic (Rockchip, Sparse)
    2. Filename contains "super"
    3. Default: RAW_IMG for .img files, UNKNOWN otherwise
    
    Args:
        file_path: Đường dẫn đến ROM file
        
    Returns:
        RomType enum
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        return RomType.UNKNOWN
    
    # 1. Read header and check magic bytes
    header = read_file_header(file_path, 16)
    
    # Check Rockchip magic first (highest priority)
    if is_rockchip_header(header):
        return RomType.UPDATE_IMG
    
    # Check Android sparse magic
    if is_sparse_header(header):
        return RomType.SPARSE_IMG
    
    # 2. Filename-based detection for specific cases
    filename = file_path.name.lower()
    
    # Explicit update/release pattern in filename
    if 'release_update' in filename or 'release-update' in filename:
        return RomType.RELEASE_UPDATE_IMG
    
    if 'update' in filename and filename.endswith('.img'):
        # Could be Rockchip without proper magic, treat as update
        return RomType.UPDATE_IMG
    
    # Super image detection
    if 'super' in filename and filename.endswith('.img'):
        return RomType.SUPER_IMG
    
    # 3. Default for .img files: treat as raw partition image
    if filename.endswith('.img'):
        return RomType.RAW_IMG
    
    return RomType.UNKNOWN


def detect_rom_in_folder(folder: Path) -> Optional[Tuple[Path, RomType]]:
    """
    Tìm ROM file trong folder theo priority
    
    Args:
        folder: Folder để search
        
    Returns:
        Tuple (file_path, rom_type) hoặc None
    """
    if not folder.is_dir():
        return None
    
    # Priority search order
    priority_patterns = [
        "update.img",
        "release_update.img",
        "super.img",
    ]
    
    # Check exact matches first
    for pattern in priority_patterns:
        matches = list(folder.glob(pattern))
        if matches:
            return (matches[0], detect_rom_type(matches[0]))
    
    # Fallback: search all .img files and detect
    best_match = None
    best_type = RomType.UNKNOWN
    
    for img_file in folder.glob("*.img"):
        rom_type = detect_rom_type(img_file)
        # Prefer more specific types
        if rom_type == RomType.UPDATE_IMG:
            return (img_file, rom_type)
        elif rom_type == RomType.SUPER_IMG and best_type not in [RomType.UPDATE_IMG]:
            best_match = img_file
            best_type = rom_type
        elif rom_type != RomType.UNKNOWN and best_match is None:
            best_match = img_file
            best_type = rom_type
    
    if best_match:
        return (best_match, best_type)
    
    return None


def get_rom_info(file_path: Path) -> dict:
    """
    Lấy thông tin cơ bản của ROM file
    
    Returns:
        Dict với các keys: path, name, size, type, is_sparse, is_rockchip
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        return {"exists": False}
    
    stat = file_path.stat()
    rom_type = detect_rom_type(file_path)
    header = read_file_header(file_path, 16)
    
    return {
        "exists": True,
        "path": str(file_path),
        "name": file_path.name,
        "size": stat.st_size,
        "type": rom_type.value,
        "type_enum": rom_type,
        "is_sparse": is_sparse_header(header),
        "is_rockchip": is_rockchip_header(header),
    }


def is_rockchip_rom(file_path: Path) -> bool:
    """
    Kiểm tra xem có phải Rockchip ROM không (dựa trên header)
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return False
    
    header = read_file_header(file_path, 16)
    if is_rockchip_header(header):
        return True
    
    # Fallback: filename pattern
    rom_type = detect_rom_type(file_path)
    return rom_type in [RomType.UPDATE_IMG, RomType.RELEASE_UPDATE_IMG]


def map_rom_type_to_input_type(rom_type: RomType) -> str:
    """
    Map RomType enum to input_type string for pipeline
    """
    if rom_type in [RomType.UPDATE_IMG, RomType.RELEASE_UPDATE_IMG]:
        return "rockchip_update"
    elif rom_type == RomType.SUPER_IMG:
        return "android_super"
    elif rom_type in [RomType.SPARSE_IMG, RomType.RAW_IMG]:
        return "partition_image"
    else:
        return "partition_image"  # Default policy: treat unknown as partition
