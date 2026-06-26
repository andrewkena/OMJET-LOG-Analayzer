"""Photo Geotagging tab: a table listing every photo trigger (CAM/TRIG)
with its position, altitude, attitude, and ground speed at capture time —
the inputs typically needed to assemble an orthophoto plan."""
from __future__ import annotations

import csv

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QFileDialog, QAbstractItemView,
)

from app.core.log_loader import LogData
from app.core.time_format import format_mmss, format_gps_time

_GPS_LAT_CANDIDATES = [("GPS", "Lat", "Lng"), ("GPS", "Lat", "Lon"), ("GLOBAL_POSITION_INT", "lat", "lon")]
# (msg_type, field, divisor) -> meters
_ALT_AMSL_CANDIDATES = [("GPS", "Alt", 1.0), ("BARO", "Alt", 1.0)]
_ALT_AGL_CANDIDATES = [("CTUN", "Alt", 1.0), ("RFND", "Dist", 100.0)]
_GROUND_SPEED_CANDIDATES = [("GPS", "Spd", 1.0), ("VFR_HUD", "groundspeed", 1.0)]
# (msg_type, roll_field, pitch_field, yaw_field, values_are_radians)
_ATTITUDE_CANDIDATES = [
    ("ATT", "Roll", "Pitch", "Yaw", False),
    ("ATTITUDE", "roll", "pitch", "yaw", True),
]

_COLUMNS = [
    "№", "Время полета", "Время GPS", "Широта", "Долгота",
    "Высота AMSL (м)", "Высота AGL (м)", "Крен (°)", "Тангаж (°)", "Курс (°)",
    "Путевая скорость (м/с)", "Интервал (с)", "Расстояние (м)",
]

_EARTH_RADIUS_M = 6371000.0


def _haversine_m(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


class PhotoGeotagWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.summary_label = QLabel("Фотографии не найдены")
        self.export_button = QPushButton("Экспорт в CSV")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_csv)
        top_row.addWidget(self.summary_label)
        top_row.addStretch()
        top_row.addWidget(self.export_button)
        layout.addLayout(top_row)

        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

        self._rows: list[list[str]] = []

    def load(self, log_data: LogData):
        photo_table, t, lat, lon = self._photo_positions(log_data)
        self.table.setRowCount(0)
        self._rows = []
        if photo_table is None or len(t) == 0:
            self.summary_label.setText("Фотографии не найдены (нет сообщений CAM/TRIG в логе)")
            self.export_button.setEnabled(False)
            return

        amsl = self._resolve_series(photo_table, t, "Alt", _ALT_AMSL_CANDIDATES, log_data)
        agl = self._resolve_series(photo_table, t, "RelAlt", _ALT_AGL_CANDIDATES, log_data)
        roll, pitch, yaw = self._resolve_attitude(photo_table, t, log_data)
        speed = self._resolve_series(photo_table, t, None, _GROUND_SPEED_CANDIDATES, log_data)

        n = len(t)
        dist = _haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:]) if n > 1 else np.array([])
        interval = np.diff(t) if n > 1 else np.array([])

        rows = []
        for i in range(n):
            rows.append([
                str(i + 1),
                format_mmss(float(t[i]) - log_data.start_time),
                format_gps_time(float(t[i])),
                f"{lat[i]:.6f}",
                f"{lon[i]:.6f}",
                f"{amsl[i]:.1f}" if amsl is not None else "—",
                f"{agl[i]:.1f}" if agl is not None else "—",
                f"{roll[i]:.1f}" if roll is not None else "—",
                f"{pitch[i]:.1f}" if pitch is not None else "—",
                f"{yaw[i]:.1f}" if yaw is not None else "—",
                f"{speed[i]:.1f}" if speed is not None else "—",
                f"{interval[i - 1]:.1f}" if i > 0 else "—",
                f"{dist[i - 1]:.1f}" if i > 0 else "—",
            ])

        self._rows = rows
        self.table.setRowCount(n)
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)

        self.summary_label.setText(f"Найдено фотографий: {n}")
        self.export_button.setEnabled(True)

    def clear(self):
        self.table.setRowCount(0)
        self._rows = []
        self.summary_label.setText("Фотографии не найдены")
        self.export_button.setEnabled(False)

    def _photo_positions(self, log_data: LogData):
        for msg_type in ("CAM", "TRIG"):
            table = log_data.messages.get(msg_type)
            if not table:
                continue
            t = table["timestamp"]
            if "Lat" in table and "Lng" in table:
                return table, t, np.asarray(table["Lat"], dtype=float), np.asarray(table["Lng"], dtype=float)
            for gmsg, lat_f, lon_f in _GPS_LAT_CANDIDATES:
                gtable = log_data.messages.get(gmsg)
                if gtable and lat_f in gtable and lon_f in gtable:
                    glat, glon = gtable[lat_f], gtable[lon_f]
                    if gmsg == "GLOBAL_POSITION_INT":
                        glat, glon = glat / 1e7, glon / 1e7
                    lat = np.interp(t, gtable["timestamp"], glat)
                    lon = np.interp(t, gtable["timestamp"], glon)
                    return table, t, lat, lon
        return None, np.array([]), np.array([]), np.array([])

    def _resolve_series(self, photo_table, t, own_field, ext_candidates, log_data) -> np.ndarray | None:
        if own_field and own_field in photo_table and len(photo_table[own_field]) == len(t):
            return np.asarray(photo_table[own_field], dtype=float)
        for msg_type, field, divisor in ext_candidates:
            table = log_data.messages.get(msg_type)
            if table and field in table and len(table[field]):
                return np.interp(t, table["timestamp"], table[field]) / divisor
        return None

    def _resolve_attitude(self, photo_table, t, log_data):
        if all(f in photo_table and len(photo_table[f]) == len(t) for f in ("Roll", "Pitch", "Yaw")):
            roll = np.asarray(photo_table["Roll"], dtype=float)
            pitch = np.asarray(photo_table["Pitch"], dtype=float)
            yaw = np.mod(np.asarray(photo_table["Yaw"], dtype=float), 360.0)
            return roll, pitch, yaw
        for msg_type, roll_f, pitch_f, yaw_f, is_radians in _ATTITUDE_CANDIDATES:
            table = log_data.messages.get(msg_type)
            if table and roll_f in table and pitch_f in table and yaw_f in table:
                roll = np.interp(t, table["timestamp"], table[roll_f])
                pitch = np.interp(t, table["timestamp"], table[pitch_f])
                yaw = np.interp(t, table["timestamp"], table[yaw_f])
                if is_radians:
                    roll, pitch, yaw = np.degrees(roll), np.degrees(pitch), np.degrees(yaw)
                return roll, pitch, np.mod(yaw, 360.0)
        return None, None, None

    def _export_csv(self):
        if not self._rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт геотегов фотографий", "", "CSV files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(_COLUMNS)
            writer.writerows(self._rows)
