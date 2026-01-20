"""
Utility functions cho RK ROM Kitchen
"""
import os
import shutil
import time
from pathlib import Path
from datetime import datetime
from typing import Union


def ensure_dir(path: Union[str, Path]) -> Path:
    """Tạo thư mục nếu chưa tồn tại, trả về Path object"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_copy(src: Union[str, Path], dst: Union[str, Path], overwrite: bool = False) -> Path:
    """
    Copy file an toàn với kiểm tra
    
    Args:
        src: Đường dẫn nguồn
        dst: Đường dẫn đích (có thể là folder hoặc file path)
        overwrite: Cho phép ghi đè nếu đích đã tồn tại
        
    Returns:
        Path đến file đích
    """
    src_path = Path(src)
    dst_path = Path(dst)
    
    if not src_path.exists():
        raise FileNotFoundError(f"File nguồn không tồn tại: {src}")
    
    # Nếu dst là folder, giữ nguyên tên file
    if dst_path.is_dir():
        dst_path = dst_path / src_path.name
    
    # Tạo folder cha nếu cần
    ensure_dir(dst_path.parent)
    
    if dst_path.exists() and not overwrite:
        raise FileExistsError(f"File đích đã tồn tại: {dst_path}")
    
    shutil.copy2(src_path, dst_path)
    return dst_path


def human_size(size_bytes: int) -> str:
    """Chuyển đổi bytes sang human-readable format"""
    if size_bytes < 0:
        return "0 B"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    size = float(size_bytes)
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"


def timestamp(fmt: str = "%Y%m%d_%H%M%S") -> str:
    """Trả về timestamp string hiện tại"""
    return datetime.now().strftime(fmt)


def timestamp_iso() -> str:
    """Trả về ISO format timestamp"""
    return datetime.now().isoformat()


def elapsed_ms(start_time: float) -> int:
    """Tính thời gian đã trôi qua tính bằng milliseconds"""
    return int((time.time() - start_time) * 1000)


def sanitize_filename(name: str) -> str:
    """Loại bỏ các ký tự không hợp lệ trong tên file"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name.strip()


def get_file_info(path: Union[str, Path]) -> dict:
    """Lấy thông tin cơ bản của file"""
    p = Path(path)
    if not p.exists():
        return {"exists": False}
    
    stat = p.stat()
    return {
        "exists": True,
        "name": p.name,
        "size": stat.st_size,
        "size_human": human_size(stat.st_size),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "is_file": p.is_file(),
        "is_dir": p.is_dir(),
        "extension": p.suffix.lower() if p.is_file() else None
    }


def list_files(folder: Union[str, Path], pattern: str = "*") -> list:
    """Liệt kê files trong folder theo pattern"""
    p = Path(folder)
    if not p.is_dir():
        return []
    return list(p.glob(pattern))


def clean_folder(folder: Union[str, Path], keep_folder: bool = True):
    """Xóa nội dung trong folder"""
    p = Path(folder)
    if not p.exists():
        return
    
    if keep_folder:
        for item in p.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
    else:
        shutil.rmtree(p)


def resolve_relative_path(project_root: Path, path_str: str) -> Path:
    """
    Resolve path relative to project root safely.
    Nếu path_str là absolute -> return path_str
    Nếu path_str là relative -> return project_root / path_str
    
    Args:
        project_root: Path đến thư mục gốc project
        path_str: Đường dẫn cần resolve (str)
        
    Returns:
        Path đã resolve absolute
    """
    p = Path(path_str)
    if p.is_absolute():
        return p
    return project_root / p
