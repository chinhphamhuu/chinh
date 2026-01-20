"""
Định nghĩa các exception class cho RK ROM Kitchen
"""


class KitchenError(Exception):
    """Base exception cho tất cả lỗi trong Kitchen"""
    pass


class WorkspaceNotConfiguredError(KitchenError):
    """Workspace chưa được cấu hình (Lần đầu chạy)"""
    pass


class ToolNotFoundError(KitchenError):
    """Tool không tìm thấy hoặc không khả dụng"""
    def __init__(self, tool_name: str, searched_paths: list = None):
        self.tool_name = tool_name
        self.searched_paths = searched_paths or []
        msg = f"Tool '{tool_name}' không tìm thấy"
        if searched_paths:
            msg += f" trong: {', '.join(searched_paths)}"
        super().__init__(msg)


class ProjectError(KitchenError):
    """Lỗi liên quan đến project"""
    pass


class ProjectNotFoundError(ProjectError):
    """Project không tồn tại"""
    def __init__(self, project_name: str):
        self.project_name = project_name
        super().__init__(f"Project '{project_name}' không tồn tại")


class ProjectExistsError(ProjectError):
    """Project đã tồn tại"""
    def __init__(self, project_name: str):
        self.project_name = project_name
        super().__init__(f"Project '{project_name}' đã tồn tại")


class PipelineError(KitchenError):
    """Lỗi trong quá trình chạy pipeline"""
    def __init__(self, step_name: str, message: str):
        self.step_name = step_name
        super().__init__(f"[{step_name}] {message}")


class StateError(KitchenError):
    """Lỗi trạng thái không hợp lệ"""
    pass


class TaskCancelledError(KitchenError):
    """Task bị hủy bởi user"""
    pass


class RomDetectError(KitchenError):
    """Không thể detect loại ROM"""
    def __init__(self, path: str):
        self.path = path
        super().__init__(f"Không thể xác định loại ROM: {path}")
