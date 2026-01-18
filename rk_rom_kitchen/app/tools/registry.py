"""
Tool Registry - Quản lý và auto-detect các tools cần thiết
Hỗ trợ alias filenames cho mỗi tool_id
"""
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from ..core.logbus import get_log_bus
from ..core.settings_store import get_settings_store


# Tool definitions với logical tool_id và alias filenames
TOOL_DEFINITIONS = {
    # Rockchip tools
    "img_unpack": {
        "aliases": ["img_unpack.exe", "img_unpack", "imgRePackerRK.exe"],
        "description": "Rockchip image unpacker",
        "version_arg": None,  # No version support
    },
    "afptool": {
        "aliases": ["afptool.exe", "afptool"],
        "description": "Rockchip AFPTool",
        "version_arg": None,
    },
    "rkImageMaker": {
        "aliases": ["rkImageMaker.exe", "rkImageMaker"],
        "description": "Rockchip image maker",
        "version_arg": None,
    },
    
    # Super partition tools
    "lpunpack": {
        "aliases": ["lpunpack.exe", "lpunpack"],
        "description": "Super partition unpacker",
        "version_arg": None,
    },
    "lpmake": {
        "aliases": ["lpmake.exe", "lpmake"],
        "description": "Super partition maker",
        "version_arg": None,
    },
    "lpdump": {
        "aliases": ["lpdump.exe", "lpdump"],
        "description": "Super partition info dumper",
        "version_arg": None,
    },
    
    # Sparse image tools
    "simg2img": {
        "aliases": ["simg2img.exe", "simg2img"],
        "description": "Sparse image to raw converter",
        "version_arg": None,
    },
    "img2simg": {
        "aliases": ["img2simg.exe", "img2simg"],
        "description": "Raw to sparse image converter",
        "version_arg": None,
    },
    
    # AVB tools
    "avbtool": {
        "aliases": ["avbtool.exe", "avbtool.py", "avbtool"],
        "description": "Android Verified Boot tool",
        "version_arg": "version",
        "is_python": True,  # May need python interpreter
    },
    
    # Filesystem tools
    "make_ext4fs": {
        "aliases": ["make_ext4fs.exe", "make_ext4fs"],
        "description": "Build ext4 filesystem image",
        "version_arg": None,
    },
    "mkfs_erofs": {
        "aliases": ["mkfs.erofs.exe", "mkfs.erofs", "mkfs_erofs.exe", "mkfs_erofs"],
        "description": "Build erofs filesystem image",
        "version_arg": "--version",
    },
    "e2fsdroid": {
        "aliases": ["e2fsdroid.exe", "e2fsdroid"],
        "description": "ext4 Android fs config tool",
        "version_arg": None,
    },
    
    # Boot image tools
    "magiskboot": {
        "aliases": ["magiskboot.exe", "magiskboot"],
        "description": "Magisk boot image tool",
        "version_arg": None,
    },
    "unpackbootimg": {
        "aliases": ["unpackbootimg.exe", "unpackbootimg", "unpack_bootimg.py"],
        "description": "Unpack boot image",
        "version_arg": None,
    },
    "mkbootimg": {
        "aliases": ["mkbootimg.exe", "mkbootimg", "mkbootimg.py"],
        "description": "Make boot image",
        "version_arg": None,
    },
    
    # Android tools
    "aapt2": {
        "aliases": ["aapt2.exe", "aapt2"],
        "description": "Android Asset Packaging Tool 2",
        "version_arg": "version",
    },
    "adb": {
        "aliases": ["adb.exe", "adb"],
        "description": "Android Debug Bridge",
        "version_arg": "version",
    },
}


@dataclass
class ToolInfo:
    """Thông tin về một tool"""
    tool_id: str
    name: str  # Display name
    description: str = ""
    path: Optional[Path] = None
    available: bool = False
    version: str = ""
    error: str = ""
    aliases: List[str] = field(default_factory=list)


class ToolRegistry:
    """
    Registry để quản lý tools
    Hỗ trợ alias resolution cho mỗi tool_id
    """
    
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
        
        self._tools: Dict[str, ToolInfo] = {}
        self._log = get_log_bus()
        self._settings = get_settings_store()
        
        # Initialize tool info từ definitions
        for tool_id, defn in TOOL_DEFINITIONS.items():
            self._tools[tool_id] = ToolInfo(
                tool_id=tool_id,
                name=tool_id,
                description=defn.get("description", ""),
                aliases=defn.get("aliases", []),
            )
    
    def _get_search_paths(self) -> List[Path]:
        """Lấy danh sách paths để search tools"""
        paths = []
        
        # 1. Custom tool_dir từ settings
        custom_dir = self._settings.get('tool_dir', '')
        if custom_dir and Path(custom_dir).is_dir():
            paths.append(Path(custom_dir))
        
        # 2. third_party/tools/win64 (relative to app)
        app_root = Path(__file__).parent.parent.parent  # rk_rom_kitchen/
        third_party = app_root / 'third_party' / 'tools' / 'win64'
        if third_party.is_dir():
            paths.append(third_party)
        
        # 3. Current directory
        paths.append(Path.cwd())
        
        # 4. PATH environment
        env_path = os.environ.get('PATH', '')
        for p in env_path.split(os.pathsep):
            if p and Path(p).is_dir():
                paths.append(Path(p))
        
        return paths
    
    def detect_all(self) -> Dict[str, ToolInfo]:
        """
        Detect tất cả tools
        Returns: Dict mapping tool_id -> ToolInfo
        """
        self._log.info("[REGISTRY] Scanning tools...")
        
        search_paths = self._get_search_paths()
        
        for tool_id, defn in TOOL_DEFINITIONS.items():
            aliases = defn.get("aliases", [])
            version_arg = defn.get("version_arg")
            is_python = defn.get("is_python", False)
            
            self._tools[tool_id] = self._detect_tool(
                tool_id, aliases, search_paths, version_arg, is_python
            )
        
        # Summary
        available = sum(1 for t in self._tools.values() if t.available)
        total = len(self._tools)
        self._log.info(f"[REGISTRY] Found {available}/{total} tools")
        
        return self._tools.copy()
    
    def _detect_tool(
        self, 
        tool_id: str, 
        aliases: List[str], 
        search_paths: List[Path],
        version_arg: Optional[str] = None,
        is_python: bool = False
    ) -> ToolInfo:
        """Detect một tool với alias resolution"""
        for search_path in search_paths:
            for alias in aliases:
                tool_path = search_path / alias
                if tool_path.exists() and tool_path.is_file():
                    # Found! Try to get version
                    version = ""
                    if version_arg:
                        version = self._get_version(tool_path, version_arg, is_python)
                    
                    return ToolInfo(
                        tool_id=tool_id,
                        name=alias,
                        description=TOOL_DEFINITIONS[tool_id].get("description", ""),
                        path=tool_path,
                        available=True,
                        version=version,
                        aliases=aliases,
                    )
        
        # Not found
        return ToolInfo(
            tool_id=tool_id,
            name=tool_id,
            description=TOOL_DEFINITIONS[tool_id].get("description", ""),
            available=False,
            error="Not found",
            aliases=aliases,
        )
    
    def _get_version(self, tool_path: Path, version_arg: str, is_python: bool = False) -> str:
        """Try to get tool version"""
        try:
            if is_python and tool_path.suffix == '.py':
                cmd = ["python", str(tool_path), version_arg]
            else:
                cmd = [str(tool_path), version_arg]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            output = result.stdout.strip() or result.stderr.strip()
            # Extract first line
            return output.split('\n')[0][:50] if output else ""
        except Exception:
            return ""
    
    def get_tool(self, tool_id: str) -> Optional[ToolInfo]:
        """Lấy tool info by tool_id"""
        return self._tools.get(tool_id)
    
    def get_tool_path(self, tool_id: str) -> Optional[Path]:
        """Lấy path của tool, None nếu không available"""
        tool = self._tools.get(tool_id)
        if tool and tool.available:
            return tool.path
        return None
    
    def is_available(self, tool_id: str) -> bool:
        """Check tool có available không"""
        tool = self._tools.get(tool_id)
        return tool.available if tool else False
    
    def get_all_tools(self) -> List[ToolInfo]:
        """Lấy list tất cả tools"""
        return list(self._tools.values())
    
    def get_missing_tools(self) -> List[str]:
        """Lấy list tools đang thiếu"""
        return [t.tool_id for t in self._tools.values() if not t.available]
    
    def get_available_tools(self) -> List[str]:
        """Lấy list tools có sẵn"""
        return [t.tool_id for t in self._tools.values() if t.available]
    
    def set_custom_tool_dir(self, path: Path):
        """Set custom tool directory và re-detect"""
        if path.is_dir():
            self._settings.set('tool_dir', str(path))
            self.detect_all()
    
    def run_doctor(self) -> str:
        """
        Tools Doctor - scan và report trạng thái tools
        Returns: report text
        """
        self.detect_all()
        
        lines = [
            "=" * 50,
            "        TOOLS DOCTOR REPORT",
            "=" * 50,
            "",
            f"Search paths:",
        ]
        
        for p in self._get_search_paths():
            lines.append(f"  - {p}")
        
        lines.append("")
        lines.append("Tools Status:")
        lines.append("-" * 50)
        
        available_count = 0
        for tool_id, info in sorted(self._tools.items()):
            if info.available:
                status = f"[OK] {info.path}"
                if info.version:
                    status += f" ({info.version})"
                available_count += 1
            else:
                status = "[MISSING]"
            lines.append(f"  {tool_id:20} {status}")
        
        lines.append("")
        lines.append("-" * 50)
        lines.append(f"Summary: {available_count}/{len(self._tools)} tools available")
        
        missing = self.get_missing_tools()
        if missing:
            lines.append("")
            lines.append("Missing tools (download and place in third_party/tools/win64/):")
            for t in missing:
                aliases = TOOL_DEFINITIONS.get(t, {}).get("aliases", [])
                lines.append(f"  - {t}: {', '.join(aliases[:2])}")
        
        lines.append("=" * 50)
        
        return "\n".join(lines)


def get_tool_registry() -> ToolRegistry:
    """Lấy singleton ToolRegistry"""
    return ToolRegistry()


# CLI interface for Tools Doctor
def main():
    """CLI entry point for tools doctor"""
    registry = get_tool_registry()
    print(registry.run_doctor())


if __name__ == "__main__":
    main()
