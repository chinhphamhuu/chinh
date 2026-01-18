"""
Task Manager - QThreadPool wrapper để chạy tasks nền
"""
import time
import inspect
import traceback
from typing import Callable, Optional, Any
from threading import Event

try:
    from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot
    HAS_QT = True
except ImportError:
    HAS_QT = False

from .task_defs import TaskResult, TaskStatus
from .state_machine import get_state_machine, TaskType
from .logbus import get_log_bus


if HAS_QT:
    class WorkerSignals(QObject):
        """Signals cho Worker"""
        started = pyqtSignal()
        finished = pyqtSignal(object)  # TaskResult
        progress = pyqtSignal(int, str)  # percent, message
        error = pyqtSignal(str)
        log = pyqtSignal(str)


    class Worker(QRunnable):
        """
        Worker runnable để chạy task trong thread pool
        """
        def __init__(self, fn: Callable, *args, **kwargs):
            super().__init__()
            self.fn = fn
            self.args = args
            self.kwargs = kwargs
            self.signals = WorkerSignals()
            self._cancelled = Event()
        
        def cancel(self):
            """Đặt flag cancel"""
            self._cancelled.set()
        
        @property
        def is_cancelled(self) -> bool:
            return self._cancelled.is_set()
        
        @pyqtSlot()
        def run(self):
            """Chạy task"""
            self.signals.started.emit()
            start_time = time.time()
            
            try:
                # Inject cancel token vào kwargs chỉ nếu fn có param đó
                sig = inspect.signature(self.fn)
                if '_cancel_token' in sig.parameters:
                    self.kwargs['_cancel_token'] = self._cancelled
                
                result = self.fn(*self.args, **self.kwargs)
                
                if not isinstance(result, TaskResult):
                    result = TaskResult.success(str(result))
                
                result.elapsed_ms = int((time.time() - start_time) * 1000)
                
            except Exception as e:
                tb = traceback.format_exc()
                get_log_bus().error(f"Task error: {e}\n{tb}")
                result = TaskResult.error(
                    str(e),
                    elapsed_ms=int((time.time() - start_time) * 1000)
                )
                self.signals.error.emit(str(e))
            
            self.signals.finished.emit(result)


    class TaskManager(QObject):
        """
        Singleton Task Manager
        Quản lý thread pool và task execution
        """
        # Signals
        task_started = pyqtSignal(str)  # task_id
        task_finished = pyqtSignal(str, object)  # task_id, TaskResult
        task_progress = pyqtSignal(str, int, str)  # task_id, percent, message
        
        _instance = None
        
        def __new__(cls):
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
        
        def __init__(self):
            if self._initialized:
                return
            super().__init__()
            self._initialized = True
            
            self._pool = QThreadPool.globalInstance()
            self._pool.setMaxThreadCount(4)
            self._workers: dict[str, Worker] = {}
            self._task_counter = 0
        
        def _generate_task_id(self) -> str:
            self._task_counter += 1
            return f"task_{self._task_counter}"
        
        def submit(self, 
                   fn: Callable,
                   task_type: TaskType = TaskType.OTHER,
                   on_finished: Callable[[TaskResult], None] = None,
                   on_progress: Callable[[int, str], None] = None,
                   *args, **kwargs) -> Optional[str]:
            """
            Submit một task để chạy nền
            
            Args:
                fn: Function to execute
                task_type: Loại task
                on_finished: Callback khi hoàn thành
                on_progress: Callback cho progress updates
                *args, **kwargs: Arguments cho fn
                
            Returns:
                task_id hoặc None nếu không thể start
            """
            state = get_state_machine()
            log = get_log_bus()
            
            # Check state
            if not state.can_start_task():
                log.warning("Đang chạy task khác, vui lòng chờ...")
                return None
            
            # Start task
            if not state.start_task(task_type):
                log.warning("Không thể bắt đầu task")
                return None
            
            task_id = self._generate_task_id()
            log.info(f"Bắt đầu task: {task_type.value} (ID: {task_id})")
            
            worker = Worker(fn, *args, **kwargs)
            
            # Connect signals
            def handle_finished(result: TaskResult):
                log.info(f"Task {task_id} hoàn thành: {'OK' if result.ok else 'FAILED'}")
                state.finish_task(result.ok, result.message)
                self.task_finished.emit(task_id, result)
                if on_finished:
                    on_finished(result)
                # Cleanup
                if task_id in self._workers:
                    del self._workers[task_id]
            
            def handle_progress(percent: int, message: str):
                self.task_progress.emit(task_id, percent, message)
                if on_progress:
                    on_progress(percent, message)
            
            worker.signals.finished.connect(handle_finished)
            worker.signals.progress.connect(handle_progress)
            worker.signals.log.connect(log.info)
            
            self._workers[task_id] = worker
            self._pool.start(worker)
            self.task_started.emit(task_id)
            
            return task_id
        
        def cancel(self, task_id: str) -> bool:
            """Hủy task đang chạy"""
            if task_id in self._workers:
                self._workers[task_id].cancel()
                return True
            return False
        
        def cancel_all(self):
            """Hủy tất cả tasks"""
            for worker in self._workers.values():
                worker.cancel()

else:
    # Fallback cho non-Qt (testing)
    class TaskManager:
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
            self._task_counter = 0
        
        def _generate_task_id(self) -> str:
            self._task_counter += 1
            return f"task_{self._task_counter}"
        
        def submit(self, fn: Callable, task_type: TaskType = TaskType.OTHER,
                   on_finished: Callable = None, on_progress: Callable = None,
                   *args, **kwargs) -> Optional[str]:
            """Synchronous execution cho testing"""
            state = get_state_machine()
            log = get_log_bus()
            
            if not state.can_start_task():
                log.warning("Đang chạy task khác")
                return None
            
            if not state.start_task(task_type):
                return None
            
            task_id = self._generate_task_id()
            log.info(f"Bắt đầu task: {task_type.value}")
            
            start_time = time.time()
            try:
                # Inject cancel token chỉ nếu fn có param đó
                sig = inspect.signature(fn)
                if '_cancel_token' in sig.parameters:
                    kwargs['_cancel_token'] = Event()
                result = fn(*args, **kwargs)
                if not isinstance(result, TaskResult):
                    result = TaskResult.success(str(result))
                result.elapsed_ms = int((time.time() - start_time) * 1000)
            except Exception as e:
                result = TaskResult.error(str(e))
            
            log.info(f"Task hoàn thành: {'OK' if result.ok else 'FAILED'}")
            state.finish_task(result.ok, result.message)
            
            if on_finished:
                on_finished(result)
            
            return task_id
        
        def cancel(self, task_id: str) -> bool:
            return False
        
        def cancel_all(self):
            pass


def get_task_manager() -> TaskManager:
    """Lấy singleton TaskManager instance"""
    return TaskManager()
