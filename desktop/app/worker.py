"""Runs blocking API calls off the UI thread so windows stay responsive."""

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Signals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    progress = Signal(object)


class _Relay(QObject):
    """Lives in the UI thread, so worker signals reach callbacks through queued connections."""

    def __init__(self, task: "Task", on_success, on_error, on_progress):
        super().__init__()
        self.task = task
        self.on_success, self.on_error, self.on_progress = on_success, on_error, on_progress

    @Slot(object)
    def succeeded(self, value):
        _running.discard(self.task)
        if self.on_success:
            self.on_success(value)

    @Slot(object)
    def failed(self, exc):
        _running.discard(self.task)
        if self.on_error:
            self.on_error(exc)

    @Slot(object)
    def progress(self, value):
        if self.on_progress:
            self.on_progress(value)


class Task(QRunnable):

    def __init__(self, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()
        self.relay: _Relay | None = None

    def run(self) -> None:
        try:
            try:
                result = self.fn(*self.args, **self.kwargs)
            except Exception as exc:
                self.signals.failed.emit(exc)
            else:
                self.signals.succeeded.emit(result)
        except RuntimeError:
            pass  # the application quit while the task was running; nobody is waiting for the result


_running: set[Task] = set()


def run_task(
    fn: Callable[..., Any],
    *args,
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    on_progress: Callable[[Any], None] | None = None,
    **kwargs,
) -> Task:
    """Run fn(*args, **kwargs) in the thread pool.

    With on_progress, fn also receives report=<callable> to send progress
    values back to the UI thread.
    """
    task = Task(fn, *args, **kwargs)
    if on_progress:
        task.kwargs["report"] = task.signals.progress.emit
    task.setAutoDelete(False)

    task.relay = _Relay(task, on_success, on_error, on_progress)
    task.signals.succeeded.connect(task.relay.succeeded)
    task.signals.failed.connect(task.relay.failed)
    task.signals.progress.connect(task.relay.progress)

    _running.add(task)
    QThreadPool.globalInstance().start(task)
    return task
