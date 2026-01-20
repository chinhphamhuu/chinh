"""
Main Window - Cửa sổ chính của ứng dụng
Layout giống CRB: Icon sidebar trái, Project sidebar, Main canvas, Log panel dưới
"""
import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QSplitter, QLabel, QMessageBox
)
from PyQt5.QtCore import Qt

from ..i18n import t, get_language
from ..core.app_context import get_app_context
from ..core.logbus import get_log_bus
from ..core.settings_store import get_settings_store
from .qss import get_stylesheet
from .widgets.icon_sidebar import IconSidebar
from .widgets.project_sidebar import ProjectSidebar
from .widgets.log_panel import LogPanel
from .widgets.status_panel import StatusPanel
from .pages.page_project import PageProject
from .pages.page_folders import PageFolders
from .pages.page_extractor import PageExtractor
from .pages.page_patches import PagePatches
from .pages.page_build import PageBuild
from .pages.page_settings import PageSettings
from .pages.page_build_image import BuildImagePage
from .pages.page_avb import PageAVB
from .pages.page_magisk import PageMagisk
from .pages.page_boot_unpack import PageBootUnpack
# DebloaterDialog is lazy-imported when needed to avoid crash if send2trash missing


class AboutPage(QWidget):
    """Simple About page"""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        
        from .. import __version__
        
        title = QLabel("RK ROM Kitchen")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)
        
        version = QLabel(f"Version {__version__}")
        layout.addWidget(version)
        
        desc = QLabel(t("about_description"))
        desc.setStyleSheet("color: #969696;")
        layout.addWidget(desc)
        
        layout.addSpacing(20)
        
        info = QLabel(
            "Công cụ mod ROM dành riêng cho thiết bị Rockchip.\n\n"
            "Hỗ trợ: update.img, release_update.img, super.img\n\n"
            "© 2024 RK Kitchen Team"
        )
        info.setAlignment(Qt.AlignCenter)
        info.setStyleSheet("color: #808080;")
        layout.addWidget(info)
    
    def update_translations(self):
        pass
    
    def refresh(self):
        pass


class WorkspaceBar(QWidget):
    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setStyleSheet("background-color: #2d2d2d; border-bottom: 1px solid #3d3d3d;")
        
        from PyQt5.QtWidgets import QPushButton
        
        lbl = QLabel(f"Workspace: <b>{workspace.root}</b>")
        lbl.setStyleSheet("color: #cccccc;")
        layout.addWidget(lbl)
        
        layout.addStretch()
        
        btn_open = QPushButton("Mở Folder")
        btn_open.clicked.connect(lambda: os.startfile(str(workspace.root)))
        layout.addWidget(btn_open)
        
        btn_tools = QPushButton("Mở Tools")
        btn_tools.clicked.connect(lambda: os.startfile(str(workspace.tools_dir)))
        layout.addWidget(btn_tools)
        
        btn_change = QPushButton("Đổi Workspace...")
        btn_change.clicked.connect(parent._change_workspace if parent else None)
        layout.addWidget(btn_change)

class MainWindow(QMainWindow):
    """
    Main application window
    """
    
    def __init__(self):
        super().__init__()
        self._ctx = get_app_context()
        self._log = get_log_bus()
        self._settings = get_settings_store()
        
        self._pages: dict = {}
        
        self._setup_window()
        self._setup_ui()
        self._connect_signals()
        
        # Initial page
        self._on_page_changed("project")
        
        # Log startup
        self._log.info("RK ROM Kitchen đã khởi động")
        self._log.info(f"Workspace: {self._ctx.workspace.root}")
    
    def _setup_window(self):
        """Setup window properties"""
        self.setWindowTitle(t("app_title"))
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        # Apply stylesheet
        self.setStyleSheet(get_stylesheet())
    
    def _setup_ui(self):
        """Setup UI components"""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Workspace Bar
        self._ws_bar = WorkspaceBar(self._ctx.workspace, self)
        main_layout.addWidget(self._ws_bar)
        
        # Top area (sidebars + canvas)
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        
        # Icon Sidebar
        self._icon_sidebar = IconSidebar()
        top_layout.addWidget(self._icon_sidebar)
        
        # Project Sidebar
        self._project_sidebar = ProjectSidebar()
        top_layout.addWidget(self._project_sidebar)
        
        # Main Canvas (stacked pages)
        self._page_stack = QStackedWidget()
        top_layout.addWidget(self._page_stack, 1)
        
        # Create pages
        self._create_pages()
        
        # Splitter for top + log
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(top_widget)
        
        # Log Panel
        self._log_panel = LogPanel()
        splitter.addWidget(self._log_panel)
        
        # Set splitter sizes
        splitter.setSizes([600, 180])
        splitter.setCollapsible(1, False)  # Log panel không collapse
        
        main_layout.addWidget(splitter, 1)
        
        # Status Panel
        self._status_panel = StatusPanel()
        main_layout.addWidget(self._status_panel)
    
    def _create_pages(self):
        """Create and add all pages"""
        pages = [
            ("project", PageProject),
            ("folders", PageFolders),
            ("extractor", PageExtractor),
            ("patches", PagePatches),
            ("build", PageBuild),
            ("settings", PageSettings),
            ("about", AboutPage),
            # Phase 2 pages
            ("build_image", BuildImagePage),
            ("avb_page", PageAVB),
            ("magisk_patch", PageMagisk),
            ("boot_unpack", PageBootUnpack),
        ]
        
        for page_id, PageClass in pages:
            page = PageClass()
            self._pages[page_id] = page
            self._page_stack.addWidget(page)
    
    def _connect_signals(self):
        """Connect signals"""
        # Icon sidebar
        self._icon_sidebar.page_changed.connect(self._on_page_changed)
        
        # Project sidebar
        self._project_sidebar.project_changed.connect(self._on_project_changed)
        self._project_sidebar.action_triggered.connect(self._on_sidebar_action)
    
    def _change_workspace(self):
        """Handle workspace change request"""
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        
        new_path = QFileDialog.getExistingDirectory(self, "Chọn Workspace Mới")
        if not new_path:
            return
            
        from pathlib import Path
        new_root = Path(new_path)
        old_root = self._ctx.workspace.root
        
        if new_root == old_root:
            return

        from .dialogs.workspace_migration_dialog import WorkspaceMigrationDialog
        dlg = WorkspaceMigrationDialog(old_root, new_root, self)
        if dlg.exec_():
            mode = dlg.mode
            try:
                from ..core.workspace import migrate_workspace, set_workspace_root
                
                # Show loading?
                self._log.info(f"Đang chuyển workspace ({mode})...")
                migrate_workspace(old_root, new_root, mode)
                set_workspace_root(new_root)
                
                QMessageBox.information(self, "Thành công", "Đã chuyển Workspace. Ứng dụng sẽ đóng để khởi động lại.")
                self.close()
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Lỗi khi chuyển workspace: {e}")
                
    
    def _on_page_changed(self, page_id: str):
        """Handle page navigation"""
        if page_id in self._pages:
            page = self._pages[page_id]
            self._page_stack.setCurrentWidget(page)
            
            # Refresh page
            if hasattr(page, 'refresh'):
                page.refresh()
    
    def _on_project_changed(self, project_name: str):
        """Handle project selection change"""
        self._log.info(f"Đã chọn project: {project_name}")
        
        # Refresh current page
        current_index = self._page_stack.currentIndex()
        current_page = self._page_stack.currentWidget()
        if hasattr(current_page, 'refresh'):
            current_page.refresh()
    
    def _on_sidebar_action(self, action_id: str):
        """Handle sidebar context actions"""
        self._log.debug(f"Sidebar action: {action_id}")
        
        project = self._ctx.current_project
        
        # Folder actions
        folder_actions = {
            "open_rom": lambda p: p.in_dir,
            "open_build": lambda p: p.out_dir,
            "open_source": lambda p: p.source_dir,
            "open_output": lambda p: p.out_dir,
            "open_config": lambda p: p.config_dir,
            "open_log": lambda p: p.logs_dir,
        }
        
        if action_id in folder_actions and project:
            folder = folder_actions[action_id](project)
            folder.mkdir(parents=True, exist_ok=True)
            if os.name == 'nt':
                os.startfile(str(folder))
            self._log.info(f"Mở thư mục: {folder}")
            return
        
        # Navigate to pages
        if action_id in self._pages:
            self._on_page_changed(action_id)
            return
        
        # Debloater dialog (lazy import)
        if action_id == "debloater":
            try:
                from .dialogs.debloater_dialog import DebloaterDialog
                dialog = DebloaterDialog(self)
                dialog.exec_()
            except ImportError as e:
                QMessageBox.warning(
                    self, "Missing Dependency",
                    f"Debloater cần cài đặt 'send2trash'.\n"
                    f"Chạy: pip install send2trash\n\nLỗi: {e}"
                )
                self._log.error(f"[DEBLOATER] Import error: {e}")
            return
        
        # Build actions
        if action_id == "build_image":
            self._on_page_changed("build_image")
            return
        if action_id in ["build_bulk", "build_super", "make_vbmeta_disabled", "force_encryption", "boot_editor", "patch_boot"]:
            QMessageBox.information(self, "Info", "Coming soon - Phase 2")
            return
        
        # Other actions
        if action_id == "project_created":
            self._project_sidebar.refresh()
        elif action_id == "project_deleted":
            self._project_sidebar.refresh()
    
    def closeEvent(self, event):
        """Handle window close"""
        self._log.info("Đóng ứng dụng...")
        event.accept()
