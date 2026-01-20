"""
RK ROM Kitchen - Entry Point
Công cụ mod ROM cho thiết bị Rockchip
"""
import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QMessageBox, QFileDialog
from PyQt5.QtCore import Qt

from app.core.crash_guard import setup_global_exception_hooks
from app.core.errors import WorkspaceNotConfiguredError
from app.core.workspace import get_workspace_root, set_workspace_root
from app.i18n import set_language
from app.core.settings_store import get_settings_store
from app.core.logbus import get_log_bus
from app.ui.main_window import MainWindow


def main():
    """Main entry point"""
    # Create Qt application first (needed for Dialogs)
    app = QApplication(sys.argv)
    app.setApplicationName("RK ROM Kitchen")
    app.setApplicationVersion("1.0.0")

    # Install crash guard
    setup_global_exception_hooks(log_to_file=True)
    
    # Check Workspace
    try:
        get_workspace_root()
    except WorkspaceNotConfiguredError:
        # Show Explanation
        msg = QMessageBox()
        msg.setWindowTitle("Cấu hình Workspace")
        msg.setText("Chào mừng đến với RK ROM Kitchen!\n\nVui lòng chọn thư mục Workspace để lưu trữ Projects, Tools và Logs.\n\nKhuyến nghị: Documents/RK_Kitchen_Data")
        msg.setIcon(QMessageBox.Information)
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        if msg.exec_() != QMessageBox.Ok:
            sys.exit(0)
            
        # Select Folder
        path = QFileDialog.getExistingDirectory(None, "Chọn thư mục Workspace")
        if not path:
            QMessageBox.critical(None, "Lỗi", "Bạn phải chọn Workspace để sử dụng phần mềm.")
            sys.exit(1)
            
        # Save & Initialize
        try:
            from pathlib import Path
            set_workspace_root(Path(path))
        except Exception as e:
            QMessageBox.critical(None, "Lỗi", f"Không thể khởi tạo Workspace:\n{e}")
            sys.exit(1)
            
    # Load settings (now safe)
    settings = get_settings_store()
    
    # Set language from settings
    lang = settings.get('language', 'vi')
    set_language(lang)
    
    # Enable high DPI
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    # Setup log bus
    log = get_log_bus()
    from app.core.settings_store import get_appdata_dir
    log_file = get_appdata_dir() / 'app.log'
    log.set_log_file(log_file)
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Run event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
