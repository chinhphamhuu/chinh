"""
Workspace Manager (Global)
Quản lý Global Workspace: Projects/, tools/, logs/
"""
import os
import shutil
from pathlib import Path
from typing import List, Optional

from .utils import ensure_dir
from .errors import WorkspaceNotConfiguredError

# Lazy import storage loop avoidance
def _get_settings():
    from .settings_store import get_settings_store
    return get_settings_store()

def get_workspace_root() -> Path:
    """
    Lấy đường dẫn workspace root từ Settings.
    Raise WorkspaceNotConfiguredError nếu chưa setup.
    """
    s = _get_settings()
    path_str = s.get("workspace_root")
    if not path_str:
        raise WorkspaceNotConfiguredError("Workspace chưa được cấu hình")
    return Path(path_str)

def set_workspace_root(path: Path):
    """Lưu workspace root và khởi tạo layout"""
    s = _get_settings()
    s.set("workspace_root", str(path))
    s.save()
    # Auto ensure layout
    Workspace(path)


class Workspace:
    """Quản lý Global Workspace"""
    
    def __init__(self, root: Optional[Path] = None):
        """
        Args:
            root: Custom root. Nếu None sẽ lấy từ settings (có thể raise Error).
        """
        if root:
            self._root = root
        else:
            self._root = get_workspace_root()
            
        self._ensure_layout()
    
    @property
    def root(self) -> Path:
        return self._root
    
    @property
    def projects_dir(self) -> Path:
        return self._root / "Projects"
    
    @property
    def tools_dir(self) -> Path:
        return self._root / "tools" / "win64"
    
    @property
    def logs_dir(self) -> Path:
        return self._root / "logs"

    def _ensure_layout(self):
        """Tạo các folder bắt buộc"""
        ensure_dir(self.projects_dir)
        ensure_dir(self.tools_dir)
        ensure_dir(self.logs_dir)
    
    def list_projects(self) -> List[str]:
        """Liệt kê projects trong folder Projects"""
        if not self.projects_dir.exists():
            return []
        
        projects = []
        for item in self.projects_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                # Basic check: config or in folder exists?
                if (item / 'config').exists() or (item / 'in').exists():
                    projects.append(item.name)
        
        return sorted(projects)
    
    def project_exists(self, name: str) -> bool:
        return (self.projects_dir / name).is_dir()
    
    def get_project_path(self, name: str) -> Path:
        return self.projects_dir / name
    
    def create_project_structure(self, name: str) -> Path:
        """Tạo project mới trong Projects/"""
        project_path = self.projects_dir / name
        
        dirs = [
            project_path / 'in',
            project_path / 'out' / 'Source',
            project_path / 'out' / 'Image',
            project_path / 'temp',
            project_path / 'logs',
            project_path / 'config',
        ]
        
        for d in dirs:
            ensure_dir(d)
        
        return project_path
    
    def delete_project(self, name: str) -> bool:
        project_path = self.projects_dir / name
        if not project_path.exists():
            return False
        try:
            shutil.rmtree(project_path)
            return True
        except OSError:
            return False
    
    def get_project_size(self, name: str) -> int:
        project_path = self.projects_dir / name
        if not project_path.exists():
            return 0
        total = 0
        for p in project_path.rglob('*'):
            if p.is_file():
                total += p.stat().st_size
        return total

# Singleton instance
_workspace: Optional[Workspace] = None

def migrate_workspace(old_root: Path, new_root: Path, mode: str):
    """
    Di chuyển dữ liệu sang workspace mới.
    Mode: 'MOVE', 'COPY', 'SKIP'
    """
    if mode == 'SKIP':
        return

    # Ensure dest layout
    Workspace(new_root) 
    
    dirs_to_sync = ['Projects', os.path.join('tools', 'win64')]
    
    for relative in dirs_to_sync:
        src = old_root / relative
        dst = new_root / relative
        
        if not src.exists():
            continue
            
        if not dst.parent.exists():
            dst.parent.mkdir(parents=True)
            
        # If dest exists, we have collision?
        # Simple strategy: Copy tree (merge)
        try:
            if mode == 'COPY':
                _copy_tree_merge(src, dst)
            elif mode == 'MOVE':
                _copy_tree_merge(src, dst)
                shutil.rmtree(src)
        except Exception as e:
            raise RuntimeError(f"Lỗi khi migrate ({mode}) {relative}: {e}")

def _copy_tree_merge(src: Path, dst: Path):
    """Copy recursive, merge if exists"""
    if not dst.exists():
        shutil.copytree(src, dst)
        return

    for item in src.iterdir():
        d = dst / item.name
        if item.is_dir():
            _copy_tree_merge(item, d)
        else:
            if not d.exists(): # Don't overwrite existing
                shutil.copy2(item, d)

def get_workspace(root: Optional[Path] = None) -> Workspace:
    """Lấy singleton (hoặc tạo mới nếu root thay đổi/chưa có)"""
    global _workspace
    if _workspace is None:
        _workspace = Workspace(root)
    elif root and _workspace.root != root:
        _workspace = Workspace(root)
    return _workspace

