"""
Dialog for Workspace Migration
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QRadioButton, QButtonGroup, 
    QDialogButtonBox, QMessageBox
)

class WorkspaceMigrationDialog(QDialog):
    def __init__(self, old_path, new_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Chuyển đổi Workspace")
        self.resize(400, 200)
        
        self.mode = "SKIP"
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel(f"<b>Workspace cũ:</b> {old_path}"))
        layout.addWidget(QLabel(f"<b>Workspace mới:</b> {new_path}"))
        layout.addWidget(QLabel("Bạn muốn làm gì với dữ liệu cũ (Projects, Tools)?"))
        
        self.group = QButtonGroup(self)
        
        self.rb_move = QRadioButton("Di chuyển (MOVE) - Xóa ở cũ, chuyển sang mới")
        self.rb_copy = QRadioButton("Sao chép (COPY) - Giữ ở cũ, copy sang mới")
        self.rb_skip = QRadioButton("Bỏ qua (SKIP) - Không làm gì, dùng workspace mới trống")
        self.rb_skip.setChecked(True)
        
        layout.addWidget(self.rb_move)
        layout.addWidget(self.rb_copy)
        layout.addWidget(self.rb_skip)
        
        self.group.addButton(self.rb_move)
        self.group.addButton(self.rb_copy)
        self.group.addButton(self.rb_skip)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def accept(self):
        if self.rb_move.isChecked(): self.mode = "MOVE"
        elif self.rb_copy.isChecked(): self.mode = "COPY"
        else: self.mode = "SKIP"
        super().accept()
