"""Table of ERR/EV/MSG/MODE events: №, Flight time, GPS time, Message, Расшифровка.

Rows are colored by severity: red for critical (errors, crashes, unresolved
failsafes), orange for warnings (GPS loss, autotune failures, etc.), default
for informational events. Clicking a row jumps the shared cursor to that time.
"""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QAbstractItemView

from app.core.log_loader import LogData
from app.core.time_format import format_mmss, format_gps_time
from app.core.event_decoder import decode_event, decode_error

_SEVERITY_COLORS = {
    "critical": (QColor("#7a1f1f"), QColor("#ffffff")),
    "warning": (QColor("#7a5a1f"), QColor("#ffffff")),
    "event": (QColor("#7a1f1f"), QColor("#ffffff")),
    "mode": (QColor("#1f3a7a"), QColor("#ffffff")),
}

_RESOLVED_WORDS = ("off", "cleared", "resolved", "restored")
_CRITICAL_MSG_WORDS = ("crash", "abort", "emergency", "lost link", "fatal", "parachute")
_WARNING_MSG_WORDS = ("fail", "bad ", "unhealthy", "low batt", "warn", "ekf", "prearm", "glitch")

# Substring -> Russian translation for common ArduPilot STATUSTEXT (MSG) prefixes.
_MSG_TRANSLATIONS = [
    ("prearm:", "Предполётная проверка не пройдена:"),
    ("arming checks", "Проверка перед взлётом"),
    ("disarming motors", "Разоружение моторов (disarming)"),
    ("arming motors", "Взведение моторов (arming)"),
    ("throttle disarmed", "Газ заблокирован, моторы разоружены"),
    ("ekf3", "Подсистема навигации EKF3:"),
    ("ekf2", "Подсистема навигации EKF2:"),
    ("ekf primary changed", "Смена основного источника навигации EKF"),
    ("gps glitch", "Сбой GPS (выброс координат)"),
    ("gps ", "GPS:"),
    ("compass", "Компас:"),
    ("barometer", "Барометр:"),
    ("calibrating", "Калибровка:"),
    ("rc failsafe", "Отказоустойчивость по радиосвязи (RC failsafe)"),
    ("battery failsafe", "Отказоустойчивость по батарее"),
    ("failsafe", "Отказоустойчивость (failsafe):"),
    ("crash detected", "Обнаружена авария (crash)"),
    ("init ardu", "Инициализация прошивки:"),
    ("frame:", "Тип рамы:"),
    ("simple mode", "Простой режим (Simple mode):"),
]


def _translate_msg(text: str) -> str:
    text_lower = text.lower()
    for prefix, translation in _MSG_TRANSLATIONS:
        if prefix in text_lower:
            return f"{translation} {text}"
    return f"Сообщение автопилота: {text}"


def _format_message(row: dict) -> str:
    msg_type = row["type"]
    if msg_type == "MSG":
        return str(row.get("Message", ""))
    if msg_type == "ERR":
        return f"ERR Subsys={row.get('Subsys')} ECode={row.get('ECode')}"
    if msg_type == "EV":
        return f"EV #{row.get('Id')}"
    if msg_type == "MODE":
        return f"MODE -> {row.get('Mode', row.get('ModeNum'))}"
    return ", ".join(f"{k}={v}" for k, v in row.items() if k not in ("type", "timestamp"))


def _decode_message(row: dict) -> str:
    msg_type = row["type"]
    if msg_type == "MSG":
        return _translate_msg(str(row.get("Message", "")))
    if msg_type == "ERR":
        return decode_error(row.get("Subsys"), row.get("ECode"))
    if msg_type == "EV":
        return decode_event(row.get("Id"))
    if msg_type == "MODE":
        return f"Смена режима полёта на «{row.get('Mode', row.get('ModeNum'))}»"
    return "—"


def _severity(row: dict, decoded: str) -> str:
    msg_type = row["type"]
    decoded_lower = decoded.lower()
    if msg_type == "EV":
        return "event"
    if msg_type == "MODE":
        return "mode"
    if msg_type == "ERR":
        try:
            ecode = int(row.get("ECode", 1))
        except (TypeError, ValueError):
            ecode = 1
        return "info" if ecode == 0 else "critical"
    if msg_type == "MSG":
        if "failsafe" in decoded_lower or "fail safe" in decoded_lower:
            return "info" if any(w in decoded_lower for w in _RESOLVED_WORDS) else "critical"
        if any(w in decoded_lower for w in _CRITICAL_MSG_WORDS):
            return "critical"
        if any(w in decoded_lower for w in _WARNING_MSG_WORDS):
            return "warning"
        return "info"
    return "info"


class EventsWidget(QTableWidget):
    time_selected = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels(["№", "Flight time", "GPS time", "Сообщение", "Расшифровка"])
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.cellClicked.connect(self._on_cell_clicked)
        self._rows: list[dict] = []

    def load(self, log_data: LogData):
        self._rows = log_data.events()
        t0 = log_data.start_time
        default_bg = self.palette().color(QPalette.Base)
        default_fg = self.palette().color(QPalette.Text)
        self.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            rel_t = row["timestamp"] - t0
            message = _format_message(row)
            decoded = _decode_message(row)
            severity = _severity(row, decoded)
            bg, fg = _SEVERITY_COLORS.get(severity, (default_bg, default_fg))

            items = [
                QTableWidgetItem(str(i + 1)),
                QTableWidgetItem(format_mmss(rel_t)),
                QTableWidgetItem(format_gps_time(row["timestamp"])),
                QTableWidgetItem(f"[{row['type']}] {message}"),
                QTableWidgetItem(decoded),
            ]
            for col, item in enumerate(items):
                item.setBackground(bg)
                item.setForeground(fg)
                self.setItem(i, col, item)
        self.resizeColumnsToContents()

    def _on_cell_clicked(self, row: int, column: int):
        if 0 <= row < len(self._rows):
            self.time_selected.emit(self._rows[row]["timestamp"])
