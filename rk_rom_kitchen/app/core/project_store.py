"""
Project Store - CRUD operations cho projects
"""
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from datetime import datetime

from .workspace import get_workspace, Workspace
from .errors import ProjectNotFoundError, ProjectExistsError
from .utils import ensure_dir, timestamp_iso


@dataclass
class ProjectConfig:
    """Project configuration data"""
    name: str = ""
    created_at: str = ""
    updated_at: str = ""
    
    # ROM info (populated after detect/extract)
    rom_type: str = ""  # update.img, release_update.img, super.img
    android_version: str = ""
    brand: str = ""
    model: str = ""
    product: str = ""
    build_id: str = ""
    
    # State
    imported: bool = False
    extracted: bool = False
    patched: bool = False
    built: bool = False
    
    # Patches applied
    patches: Dict[str, bool] = field(default_factory=dict)
    
    # Input file
    input_file: str = ""
    
    # Input type: rockchip_update / android_super / partition_image
    input_type: str = ""
    
    # Build presets per partition (Phase 2)
    build_presets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Debloated apps list
    debloated_apps: List[str] = field(default_factory=list)
    
    # Extra metadata (flexible storage)
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ProjectConfig':
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


class Project:
    """Represents một project instance"""
    
    def __init__(self, name: str, workspace: Optional[Workspace] = None):
        self._workspace = workspace or get_workspace()
        self._name = name
        self._path = self._workspace.get_project_path(name)
        self._config: Optional[ProjectConfig] = None
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def path(self) -> Path:
        return self._path
    
    @property
    def exists(self) -> bool:
        return self._path.exists()
    
    @property
    def root_dir(self) -> Path:
        """Alias for path - compatibility with engines"""
        return self._path
    
    @property
    def config(self) -> ProjectConfig:
        if self._config is None:
            self._config = self.load_config()
        return self._config
    
    # Paths
    @property
    def in_dir(self) -> Path:
        return self._path / 'in'
    
    @property
    def out_dir(self) -> Path:
        return self._path / 'out'
    
    @property
    def source_dir(self) -> Path:
        return self._path / 'out' / 'Source'
    
    @property
    def image_dir(self) -> Path:
        return self._path / 'out' / 'Image'
    
    @property
    def temp_dir(self) -> Path:
        return self._path / 'temp'
    
    @property
    def logs_dir(self) -> Path:
        return self._path / 'logs'
    
    @property
    def config_dir(self) -> Path:
        return self._path / 'config'
    
    @property
    def config_file(self) -> Path:
        return self._path / 'config' / 'project.json'
    
    def load_config(self) -> ProjectConfig:
        """Load project config từ file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return ProjectConfig.from_dict(data)
            except (json.JSONDecodeError, IOError):
                pass
        return ProjectConfig(name=self._name)
    
    def save_config(self) -> bool:
        """Save project config"""
        try:
            self._config.updated_at = timestamp_iso()
            ensure_dir(self.config_dir)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except IOError:
            return False
    
    def update_config(self, **kwargs):
        """Update config fields và save"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self._config, key, value)
        self.save_config()
    
    def get_log_file(self) -> Path:
        """Lấy đường dẫn log file cho project"""
        ensure_dir(self.logs_dir)
        return self.logs_dir / 'project.log'


class ProjectStore:
    """Singleton store quản lý projects"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._workspace = get_workspace()
        self._current: Optional[Project] = None
    
    @property
    def workspace(self) -> Workspace:
        return self._workspace
    
    @property
    def current(self) -> Optional[Project]:
        return self._current
    
    def set_workspace(self, root: Path):
        """Set custom workspace root (cho testing)"""
        from .workspace import get_workspace
        self._workspace = get_workspace(root)
    
    def list_projects(self) -> List[str]:
        """Liệt kê tất cả projects"""
        return self._workspace.list_projects()
    
    def create(self, name: str) -> Project:
        """
        Tạo project mới
        
        Raises:
            ProjectExistsError: Nếu project đã tồn tại
        """
        if self._workspace.project_exists(name):
            raise ProjectExistsError(name)
        
        # Tạo structure
        self._workspace.create_project_structure(name)
        
        # Tạo config
        project = Project(name, self._workspace)
        project._config = ProjectConfig(
            name=name,
            created_at=timestamp_iso(),
            updated_at=timestamp_iso()
        )
        project.save_config()
        
        return project
    
    def open(self, name: str) -> Project:
        """
        Mở project đã có
        
        Raises:
            ProjectNotFoundError: Nếu project không tồn tại
        """
        if not self._workspace.project_exists(name):
            raise ProjectNotFoundError(name)
        
        project = Project(name, self._workspace)
        self._current = project
        return project
    
    def delete(self, name: str) -> bool:
        """
        Xóa project
        
        Returns:
            True nếu xóa thành công
        """
        if self._current and self._current.name == name:
            self._current = None
        return self._workspace.delete_project(name)
    
    def get(self, name: str) -> Optional[Project]:
        """Lấy project by name, trả về None nếu không tồn tại"""
        if not self._workspace.project_exists(name):
            return None
        return Project(name, self._workspace)
    
    def set_current(self, name: str) -> Optional[Project]:
        """Set current project"""
        project = self.get(name)
        self._current = project
        return project


def get_project_store() -> ProjectStore:
    return ProjectStore()
