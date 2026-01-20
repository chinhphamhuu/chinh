"""
AVB/DM-Verity Page - Disable dm-verity + patch fstab
Phase 2.1: Separate actions for vbmeta-only and fstab-only
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QListWidget, QListWidgetItem, QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt
from pathlib import Path

from ...i18n import t
from ...core.project_store import get_project_store
from ...core.logbus import get_log_bus
from ...core.state_machine import get_state_machine, TaskType
from ...core.task_manager import get_task_manager
from ...core.avb_manager import (
    scan_vbmeta_targets, find_fstab_files,
    disable_dm_verity_full, disable_avb_only, disable_fstab_only
)


class PageAVB(QWidget):
    """AVB/dm-verity disable page"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._projects = get_project_store()
        self._log = get_log_bus()
        self._state = get_state_machine()
        self._tasks = get_task_manager()
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        
        title = QLabel("AVB / DM-Verity / Forceencrypt")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        
        desc = QLabel("Disable Android Verified Boot, dm-verity và forceencrypt.")
        desc.setStyleSheet("color: #888;")
        layout.addWidget(desc)
        
        # vbmeta section
        vbmeta_group = QGroupBox("A) vbmeta Files")
        vbmeta_layout = QVBoxLayout(vbmeta_group)
        
        self._vbmeta_list = QListWidget()
        self._vbmeta_list.setMaximumHeight(120)
        vbmeta_layout.addWidget(self._vbmeta_list)
        
        vbmeta_btn = QHBoxLayout()
        self._btn_scan_vbmeta = QPushButton("Scan")
        self._btn_scan_vbmeta.clicked.connect(self._scan_vbmeta)
        vbmeta_btn.addWidget(self._btn_scan_vbmeta)
        
        self._btn_add_vbmeta = QPushButton("Browse...")
        self._btn_add_vbmeta.clicked.connect(self._browse_vbmeta)
        vbmeta_btn.addWidget(self._btn_add_vbmeta)
        
        self._btn_clear_vbmeta = QPushButton("Clear")
        self._btn_clear_vbmeta.clicked.connect(lambda: self._vbmeta_list.clear())
        vbmeta_btn.addWidget(self._btn_clear_vbmeta)
        
        vbmeta_btn.addStretch()
        vbmeta_layout.addLayout(vbmeta_btn)
        layout.addWidget(vbmeta_group)
        
        # fstab section
        fstab_group = QGroupBox("B) fstab Files")
        fstab_layout = QVBoxLayout(fstab_group)
        
        self._fstab_list = QListWidget()
        self._fstab_list.setMaximumHeight(120)
        fstab_layout.addWidget(self._fstab_list)
        
        fstab_btn = QHBoxLayout()
        self._btn_scan_fstab = QPushButton("Scan")
        self._btn_scan_fstab.clicked.connect(self._scan_fstab)
        fstab_btn.addWidget(self._btn_scan_fstab)
        
        self._btn_add_fstab = QPushButton("Browse...")
        self._btn_add_fstab.clicked.connect(self._browse_fstab)
        fstab_btn.addWidget(self._btn_add_fstab)
        
        fstab_btn.addStretch()
        fstab_layout.addLayout(fstab_btn)
        layout.addWidget(fstab_group)
        
        # Actions
        action_layout = QHBoxLayout()
        
        self._btn_disable_all = QPushButton("Disable All (A+B)")
        self._btn_disable_all.clicked.connect(self._on_disable_all)
        self._btn_disable_all.setStyleSheet("background: #c62828; padding: 8px 16px;")
        action_layout.addWidget(self._btn_disable_all)
        
        self._btn_vbmeta_only = QPushButton("vbmeta Only (A)")
        self._btn_vbmeta_only.clicked.connect(self._on_vbmeta_only)
        self._btn_vbmeta_only.setStyleSheet("padding: 8px 16px;")
        action_layout.addWidget(self._btn_vbmeta_only)
        
        self._btn_fstab_only = QPushButton("fstab Only (B)")
        self._btn_fstab_only.clicked.connect(self._on_fstab_only)
        self._btn_fstab_only.setStyleSheet("padding: 8px 16px;")
        action_layout.addWidget(self._btn_fstab_only)
        
        action_layout.addStretch()
        layout.addLayout(action_layout)
        
        layout.addStretch()
    
    def _check_project(self) -> bool:
        """Check if project is selected, show warning if not"""
        project = self._projects.current
        if not project:
            QMessageBox.warning(
                self, "Warning",
                "Chưa chọn project.\nHãy tạo hoặc mở project trước."
            )
            self._log.error("[AVB] No project selected")
            return False
        return True
    
    def _scan_vbmeta(self):
        if not self._check_project():
            return
        
        project = self._projects.current
        self._vbmeta_list.clear()
        files = scan_vbmeta_targets(project)
        for f in files:
            self._vbmeta_list.addItem(str(f))
        self._log.info(f"[AVB] Found {len(files)} vbmeta files")
    
    def _browse_vbmeta(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select vbmeta", "", "Image Files (*.img)")
        if path:
            # Check not already in list
            for i in range(self._vbmeta_list.count()):
                if self._vbmeta_list.item(i).text() == path:
                    return
            self._vbmeta_list.addItem(path)
            self._log.info(f"[AVB] Added vbmeta: {path}")
    
    def _scan_fstab(self):
        if not self._check_project():
            return
        
        project = self._projects.current
        self._fstab_list.clear()
        files = find_fstab_files(project)
        for f in files:
            self._fstab_list.addItem(str(f))
        self._log.info(f"[AVB] Found {len(files)} fstab files")
    
    def _browse_fstab(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select fstab", "", "All Files (*)")
        if path:
            self._fstab_list.addItem(path)
            self._log.info(f"[AVB] Added fstab: {path}")
    
    def _on_task_finished(self, result, action_name: str):
        """Common handler for task completion"""
        if result.ok:
            self._log.success(f"[AVB] {action_name} completed: {result.message}")
            QMessageBox.information(self, "Success", f"{action_name} hoàn thành!\n{result.message}")
        else:
            self._log.error(f"[AVB] {action_name} failed: {result.message}")
            QMessageBox.critical(self, "Error", f"{action_name} thất bại:\n{result.message}")
    
    def _on_disable_all(self):
        """Disable All (A+B): Create vbmeta_disabled + patch fstab"""
        if not self._state.can_start_task():
            QMessageBox.warning(self, "Warning", "Đang chạy task khác")
            return
        
        if not self._check_project():
            return
        
        project = self._projects.current
        self._log.info("[AVB] Disabling dm-verity (A+B)...")
        
        self._tasks.submit(
            disable_dm_verity_full,
            task_type=TaskType.PATCH,
            on_finished=lambda r: self._on_task_finished(r, "Disable All"),
            project=project
        )
    
    def _on_vbmeta_only(self):
        """vbmeta Only (A): Create vbmeta_disabled.img only"""
        if not self._state.can_start_task():
            QMessageBox.warning(self, "Warning", "Đang chạy task khác")
            return
        
        if not self._check_project():
            return
        
        project = self._projects.current
        self._log.info("[AVB] Creating vbmeta_disabled.img...")
        
        self._tasks.submit(
            disable_avb_only,
            task_type=TaskType.PATCH,
            on_finished=lambda r: self._on_task_finished(r, "vbmeta Only"),
            project=project
        )
    
    def _on_fstab_only(self):
        """fstab Only (B): Patch fstab files only"""
        if not self._state.can_start_task():
            QMessageBox.warning(self, "Warning", "Đang chạy task khác")
            return
        
        if not self._check_project():
            return
        
        project = self._projects.current
        self._log.info("[AVB] Patching fstab files...")
        
        self._tasks.submit(
            disable_fstab_only,
            task_type=TaskType.PATCH,
            on_finished=lambda r: self._on_task_finished(r, "fstab Only"),
            project=project
        )
    
    def refresh(self):
        """Refresh page when shown"""
        if self._projects.current:
            self._scan_vbmeta()
            self._scan_fstab()
    
    def update_translations(self):
        pass
