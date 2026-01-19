"""
Folders Page - Trang quản lý thư mục project
OUTPUT CONTRACT:
- in/ (Input)
- out/Source/ (Filesystem extracted)
- out/Image/ (Images output)
- extract/ (Intermediate)
- temp/, logs/, config/
"""
import os
import subprocess
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QGroupBox
)
from PyQt5.QtCore import Qt

from ...i18n import t
from ...core.project_store import get_project_store
from ...core.logbus import get_log_bus


class PageFolders(QWidget):
    """
    Folders page:
    - Navigate project folders
    - Quick open buttons for common paths
    - Open in explorer
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._projects = get_project_store()
        self._log = get_log_bus()
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Title
        title = QLabel(t("page_folders_title"))
        title.setProperty("heading", True)
        layout.addWidget(title)
        
        # Quick access buttons
        quick_group = QGroupBox("Mở nhanh")
        quick_layout = QHBoxLayout(quick_group)
        
        self._btn_open_source = QPushButton("out/Source")
        self._btn_open_source.clicked.connect(lambda: self._open_quick("source"))
        quick_layout.addWidget(self._btn_open_source)
        
        self._btn_open_image = QPushButton("out/Image")
        self._btn_open_image.clicked.connect(lambda: self._open_quick("image"))
        quick_layout.addWidget(self._btn_open_image)
        
        self._btn_open_update = QPushButton("out/Image/update")
        self._btn_open_update.clicked.connect(lambda: self._open_quick("update"))
        quick_layout.addWidget(self._btn_open_update)
        
        self._btn_open_super = QPushButton("out/Image/super")
        self._btn_open_super.clicked.connect(lambda: self._open_quick("super"))
        quick_layout.addWidget(self._btn_open_super)
        
        quick_layout.addStretch()
        layout.addWidget(quick_group)
        
        # Folder list
        self._folder_list = QListWidget()
        self._folder_list.itemDoubleClicked.connect(self._on_folder_double_clicked)
        layout.addWidget(self._folder_list)
        
        # Buttons
        btn_row = QHBoxLayout()
        
        self._btn_open = QPushButton(t("btn_open"))
        self._btn_open.clicked.connect(self._on_open_folder)
        btn_row.addWidget(self._btn_open)
        
        self._btn_refresh = QPushButton(t("btn_refresh"))
        self._btn_refresh.clicked.connect(self.refresh)
        btn_row.addWidget(self._btn_refresh)
        
        btn_row.addStretch()
        layout.addLayout(btn_row)
        
        self.refresh()
    
    def _open_quick(self, folder_type: str):
        """Open quick access folder"""
        project = self._projects.current
        if not project:
            QMessageBox.warning(self, t("dialog_warning"), "Chưa chọn project")
            return
        
        if folder_type == "source":
            path = project.out_source_dir
        elif folder_type == "image":
            path = project.out_image_dir
        elif folder_type == "update":
            path = project.out_image_dir / "update"
        elif folder_type == "super":
            path = project.out_image_dir / "super"
        else:
            return
        
        self._open_folder_path(path)
    
    def _open_folder_path(self, path: Path):
        """Open path in file explorer"""
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            self._log.info(f"Đã tạo thư mục: {path}")
        
        if os.name == 'nt':
            os.startfile(str(path))
        else:
            subprocess.run(['xdg-open', str(path)])
        
        self._log.info(f"Mở thư mục: {path}")
    
    def refresh(self):
        """Refresh folder list"""
        self._folder_list.clear()
        
        project = self._projects.current
        if not project:
            self._folder_list.addItem("Chưa có project được chọn")
            return
        
        # Add folder items - OUTPUT CONTRACT
        folders = [
            ("📁 in/ (Input ROM)", project.in_dir),
            ("📁 out/ (Output)", project.out_dir),
            ("  📁 out/Source/ (Filesystem)", project.out_source_dir),
            ("  📁 out/Image/ (Images)", project.out_image_dir),
            ("    📁 out/Image/update/", project.out_image_dir / "update"),
            ("    📁 out/Image/super/", project.out_image_dir / "super"),
            ("📁 extract/ (Intermediate)", project.extract_dir),
            ("📁 temp/ (Working)", project.temp_dir),
            ("📁 logs/", project.logs_dir),
            ("📁 config/", project.config_dir),
        ]
        
        for label, path in folders:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, str(path))
            
            # Color based on exists + has content
            if not path.exists():
                item.setForeground(Qt.gray)
            elif path.is_dir() and any(path.iterdir()):
                item.setForeground(Qt.green)
            
            self._folder_list.addItem(item)
    
    def _on_folder_double_clicked(self, item: QListWidgetItem):
        """Open folder on double click"""
        self._open_path(item)
    
    def _on_open_folder(self):
        """Open selected folder"""
        item = self._folder_list.currentItem()
        if item:
            self._open_path(item)
    
    def _open_path(self, item: QListWidgetItem):
        """Open path in file explorer"""
        path_str = item.data(Qt.UserRole)
        if not path_str:
            return
        
        path = Path(path_str)
        self._open_folder_path(path)
    
    def update_translations(self):
        """Update UI khi đổi ngôn ngữ"""
        self._btn_open.setText(t("btn_open"))
        self._btn_refresh.setText(t("btn_refresh"))
