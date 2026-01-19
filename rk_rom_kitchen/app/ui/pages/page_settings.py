"""
Settings Page - Trang cài đặt
"""
import json
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QComboBox, QMessageBox, QScrollArea
)

from ...i18n import t, set_language, get_language
from ...core.settings_store import get_settings_store
from ...core.logbus import get_log_bus
from ...tools.registry import get_tool_registry
from ..widgets.file_picker import FolderPicker
from ..widgets.kv_table import ToolsStatusTable


class PageSettings(QWidget):
    """
    Settings page:
    - Language selection
    - Tool directory
    - Tools status table
    - Download tools (Phase 2 stub)
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = get_settings_store()
        self._log = get_log_bus()
        self._registry = get_tool_registry()
        
        self._setup_ui()
        self._load_settings()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Title
        title = QLabel(t("page_settings_title"))
        title.setProperty("heading", True)
        layout.addWidget(title)
        
        # Language section
        lang_group = QGroupBox(t("settings_language"))
        lang_layout = QHBoxLayout(lang_group)
        
        self._lang_combo = QComboBox()
        self._lang_combo.addItem("Tiếng Việt", "vi")
        self._lang_combo.addItem("English", "en")
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_layout.addWidget(self._lang_combo)
        lang_layout.addStretch()
        
        layout.addWidget(lang_group)
        
        # Tool directory section
        tool_group = QGroupBox(t("settings_tool_dir"))
        tool_layout = QVBoxLayout(tool_group)
        
        self._tool_picker = FolderPicker(placeholder="Đường dẫn thư mục chứa tools")
        self._tool_picker.folder_selected.connect(self._on_tool_dir_changed)
        tool_layout.addWidget(self._tool_picker)
        
        layout.addWidget(tool_group)
        
        # Tools status section
        tools_group = QGroupBox(t("settings_tools_table"))
        tools_layout = QVBoxLayout(tools_group)
        
        self._tools_table = ToolsStatusTable()
        tools_layout.addWidget(self._tools_table)
        
        # Buttons row
        btn_row = QHBoxLayout()
        
        self._btn_check = QPushButton(t("btn_check_tools"))
        self._btn_check.clicked.connect(self._on_check_tools)
        btn_row.addWidget(self._btn_check)
        
        self._btn_download = QPushButton(t("btn_download_tools"))
        self._btn_download.clicked.connect(self._on_download_tools)
        btn_row.addWidget(self._btn_download)
        
        btn_row.addStretch()
        tools_layout.addLayout(btn_row)
        
        layout.addWidget(tools_group)
        
        # Stretch
        layout.addStretch()
    
    def _load_settings(self):
        """Load settings vào UI"""
        # Language
        lang = self._settings.get('language', 'vi')
        index = self._lang_combo.findData(lang)
        if index >= 0:
            self._lang_combo.setCurrentIndex(index)
        
        # Tool dir
        tool_dir = self._settings.get('tool_dir', '')
        if tool_dir:
            self._tool_picker.set_path(tool_dir)
        
        # Refresh tools table
        self._refresh_tools_table()
    
    def _refresh_tools_table(self):
        """Refresh tools status table"""
        tools = self._registry.get_all_tools()
        self._tools_table.set_tools(tools)
    
    def _on_language_changed(self, index: int):
        """Handle language change"""
        lang = self._lang_combo.itemData(index)
        if lang:
            set_language(lang)
            self._settings.set('language', lang)
            self._log.info(f"Đã đổi ngôn ngữ sang: {lang}")
            
            # Show restart message
            QMessageBox.information(
                self,
                t("dialog_info"),
                "Một số thay đổi ngôn ngữ sẽ được áp dụng khi khởi động lại ứng dụng."
            )
    
    def _on_tool_dir_changed(self, path: str):
        """Handle tool directory change"""
        self._settings.set('tool_dir', path)
        self._registry.set_custom_tool_dir(Path(path))
        self._refresh_tools_table()
        self._log.info(f"Đã set tool directory: {path}")
    
    def _on_check_tools(self):
        """Check all tools"""
        self._log.info("Đang kiểm tra tools...")
        self._registry.detect_all()
        self._refresh_tools_table()
        
        missing = self._registry.get_missing_tools()
        if missing:
            self._log.warning(f"Thiếu {len(missing)} tools: {', '.join(missing)}")
        else:
            self._log.success("Tất cả tools đã sẵn sàng!")
    
    def _on_download_tools(self):
        """
        Danh sách tools (tham khảo)
        Đọc manifest và hiển thị, KHÔNG download thật
        """
        self._log.info("=== DANH SÁCH TOOLS (THAM KHẢO) ===")
        
        # Read manifest
        manifest_file = Path(__file__).parent.parent.parent.parent / 'tools_manifest' / 'manifest.json'
        
        if manifest_file.exists():
            try:
                with open(manifest_file, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                
                tools = manifest.get('tools', [])
                download_note = manifest.get('download_note', 'Đặt tools vào tools/win64/')
                
                self._log.info(f"Manifest chứa {len(tools)} tools:")
                self._log.info(f"Gợi ý: {download_note}")
                self._log.info("")
                
                for tool in tools:
                    tool_id = tool.get('id', 'unknown')
                    name = tool.get('name', tool_id)
                    aliases = tool.get('aliases', [])
                    required = tool.get('required', False)
                    note = tool.get('note', '')
                    
                    req_text = "Required" if required else "Optional"
                    aliases_text = ', '.join(aliases[:2]) if aliases else ''
                    
                    self._log.info(f"  [{req_text}] {name}")
                    if aliases_text:
                        self._log.info(f"      Aliases: {aliases_text}")
                    if note:
                        self._log.info(f"      Note: {note}")
                
                self._log.info("")
                self._log.info("Đặt file tools vào: tools/win64/")
                
            except Exception as e:
                self._log.error(f"Lỗi đọc manifest: {e}")
        else:
            self._log.warning(f"Không tìm thấy manifest: {manifest_file}")
        
        # Show info dialog
        QMessageBox.information(
            self,
            t("dialog_info"),
            "Danh sách tools đã được log.\nĐặt tools vào: tools/win64/"
        )
        
        self._log.info("=== KẾT THÚC ===")
    
    def update_translations(self):
        """Update UI khi đổi ngôn ngữ"""
        self._btn_check.setText(t("btn_check_tools"))
        self._btn_download.setText(t("btn_download_tools"))
