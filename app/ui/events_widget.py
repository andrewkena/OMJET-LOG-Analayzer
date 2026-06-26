"""Table of ERR/EV/MSG/MODE events: №, Flight time, GPS time, Message.

Critical entries (errors and failsafe/crash-type messages) are highlighted
in red. Clicking a row jumps the shared cursor to that time.
"""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QAbstractItemView

from app.core.log_loader import LogData
from app.core.time_format import format_mmss, format_gps_time
from app.core.event_decoder import decode_event, decode_error

_CRITICAL_COLOR = QColor("#ff5555")
_RESOLVED_WORDS = ("off", "cleared", "resolved", "restored")
_CRITICAL_WORDS = ("crash", "error", "abort", "emergency", "bad ", "lost")


def _format_message(row: dict) -> str:
    msg_type = row["type"]
    if msg_type == "MSG":
        return str(row.get("Message", ""))
    if msg_type == "ERR":
        return decode_error(row.get("Subsys"), row.get("ECode"))
    if msg_type == "EV":
        return decode_event(row.get("Id"))
    if msg_type == "MODE":
        return f"Mode change -> {row.get('Mode', row.get('ModeNum'))}"
    return ", ".join(f"{k}={v}" for k, v in row.items() if k not in ("type", "timestamp"))


def _is_critical(msg_type: str, message: str) -> bool:
    if msg_type == "ERR":
        return True
    msg_lower = message.lower()
    if "failsafe" in msg_lower or "fail safe" in msg_lower:
        return not any(w in msg_lower for w in _RESOLVED_WORDS)
    return any(w in msg_lower for w in _CRITICAL_WORDS)


class EventsWidget(QTableWidget):
    time_selected = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["№", "Flight time", "GPS time", "Message"])
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cellClicked.connect(self._on_cell_clicked)
        self._rows: list[dict] = []

    def load(self, log_data: LogData):
        self._rows = log_data.events()
        t0 = log_data.start_time
        self.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            rel_t = row["timestamp"] - t0
            message = _format_message(row)
            critical = _is_critical(row["type"], message)

            items = [
                QTableWidgetItem(str(i + 1)),
                QTableWidgetItem(format_mmss(rel_t)),
                QTableWidgetItem(format_gps_time(row["timestamp"])),
                QTableWidgetItem(f"[{row['type']}] {message}"),
            ]
            for col, item in enumerate(items):
                if critical:
                    item.setForeground(_CRITICAL_COLOR)
                self.setItem(i, col, item)
        self.resizeColumnsToContents()

    def _on_cell_clicked(self, row: int, column: int):
        if 0 <= row < len(self._rows):
            self.time_selected.emit(self._rows[row]["timestamp"])
