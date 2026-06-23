"""Background thread that parses a log file and reports progress to the GUI."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.core.log_loader import load_log


class LogLoadWorker(QThread):
    progress = Signal(int)
    finished_ok = Signal(object)  # LogData
    failed = Signal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            log_data = load_log(self.path, progress_callback=self.progress.emit)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(log_data)
