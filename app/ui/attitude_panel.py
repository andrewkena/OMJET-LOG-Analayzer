"""Bottom panel showing an artificial horizon (roll/pitch) and a heading
compass (yaw), synced to the playback cursor."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QPainterPath, QPolygonF
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QGraphicsOpacityEffect

from app.ui.gauge_widget import TapeGauge, BatteryGauge


class AttitudeIndicator(QWidget):
    """Artificial horizon: rolling/pitching sky-ground disc with a fixed aircraft symbol."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(110, 110)
        self._roll = 0.0
        self._pitch = 0.0

    def set_attitude(self, roll: float, pitch: float):
        self._roll = roll
        self._pitch = pitch
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        side = min(rect.width(), rect.height()) - 8
        cx, cy = rect.center().x(), rect.center().y()
        radius = side / 2

        painter.save()
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), radius, radius)
        painter.setClipPath(clip)

        painter.translate(cx, cy)
        painter.rotate(-self._roll)
        pitch_offset = max(-radius, min(radius, self._pitch * (radius / 45.0)))
        painter.translate(0, pitch_offset)

        big = radius * 3
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2266cc"))
        painter.drawRect(QRectF(-big, -big, big * 2, big))
        painter.setBrush(QColor("#8b5a2b"))
        painter.drawRect(QRectF(-big, 0, big * 2, big))
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawLine(QPointF(-big, 0), QPointF(big, 0))

        painter.restore()

        painter.setPen(QPen(QColor("#ffd000"), 3))
        painter.drawLine(QPointF(cx - radius * 0.45, cy), QPointF(cx - radius * 0.15, cy))
        painter.drawLine(QPointF(cx + radius * 0.15, cy), QPointF(cx + radius * 0.45, cy))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffd000"))
        painter.drawEllipse(QPointF(cx, cy), 3, 3)

        painter.setPen(QPen(QColor("#444444"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)


class HeadingIndicator(QWidget):
    """Compass card that rotates under a fixed heading pointer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(110, 110)
        self._heading = 0.0

    def set_heading(self, heading: float):
        self._heading = heading % 360.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        side = min(rect.width(), rect.height()) - 8
        cx, cy = rect.center().x(), rect.center().y()
        radius = side / 2

        painter.setPen(QPen(QColor("#888888"), 2))
        painter.setBrush(QColor(20, 20, 20))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(-self._heading)
        painter.setPen(QPen(QColor("white"), 1))
        for deg in range(0, 360, 30):
            painter.save()
            painter.rotate(deg)
            painter.drawLine(QPointF(0, -radius + 2), QPointF(0, -radius + 10))
            painter.restore()
        for deg, label in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            painter.save()
            painter.rotate(deg)
            painter.drawText(QRectF(-10, -radius + 10, 20, 16), Qt.AlignCenter, label)
            painter.restore()
        painter.restore()

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#e6194b"))
        painter.drawPolygon(QPolygonF([
            QPointF(cx, cy - radius + 12),
            QPointF(cx - 6, cy - radius + 24),
            QPointF(cx + 6, cy - radius + 24),
        ]))

        painter.setPen(QColor("white"))
        painter.drawText(self.rect(), Qt.AlignCenter, f"{int(self._heading):03d}°")


class AttitudePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(160)

        self.horizon = AttitudeIndicator()
        self.compass = HeadingIndicator()
        self.speed_gauge = TapeGauge("Speed", "m/s")
        self.alt_gauge = TapeGauge("Altitude", "m")
        self.bat1_volt_gauge = BatteryGauge("Bat1 V", "V")
        self.bat1_curr_gauge = TapeGauge("Bat1 A", "A", current_warning=True)
        self.bat2_volt_gauge = BatteryGauge("Bat2 V", "V")
        self.bat2_curr_gauge = TapeGauge("Bat2 A", "A", current_warning=True)

        speed_box = QVBoxLayout()
        speed_box.addStretch()
        speed_box.addWidget(self.speed_gauge)
        speed_box.addStretch()

        horizon_box = QVBoxLayout()
        horizon_box.addWidget(QLabel("Attitude (Roll/Pitch)"), alignment=Qt.AlignHCenter)
        horizon_box.addWidget(self.horizon)

        compass_box = QVBoxLayout()
        compass_box.addWidget(QLabel("Heading (Yaw)"), alignment=Qt.AlignHCenter)
        compass_box.addWidget(self.compass)

        alt_box = QVBoxLayout()
        alt_box.addStretch()
        alt_box.addWidget(self.alt_gauge)
        alt_box.addStretch()

        bat1_box = QVBoxLayout()
        bat1_box.addWidget(QLabel("Battery 1"), alignment=Qt.AlignHCenter)
        bat1_row = QHBoxLayout()
        bat1_row.addWidget(self.bat1_volt_gauge)
        bat1_row.addWidget(self.bat1_curr_gauge)
        bat1_box.addLayout(bat1_row)
        self.bat1_container = QWidget()
        self.bat1_container.setLayout(bat1_box)

        bat2_box = QVBoxLayout()
        bat2_box.addWidget(QLabel("Battery 2"), alignment=Qt.AlignHCenter)
        bat2_row = QHBoxLayout()
        bat2_row.addWidget(self.bat2_volt_gauge)
        bat2_row.addWidget(self.bat2_curr_gauge)
        bat2_box.addLayout(bat2_row)
        self.bat2_container = QWidget()
        self.bat2_container.setLayout(bat2_box)
        self._bat2_opacity = QGraphicsOpacityEffect(self.bat2_container)
        self._bat2_opacity.setOpacity(1.0)
        self.bat2_container.setGraphicsEffect(self._bat2_opacity)

        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)

        layout = QHBoxLayout(self)
        layout.addLayout(speed_box)
        layout.addLayout(horizon_box)
        layout.addLayout(compass_box)
        layout.addLayout(alt_box)
        layout.addWidget(separator)
        layout.addWidget(self.bat1_container)
        layout.addWidget(self.bat2_container)
        layout.addStretch()

        self._t = np.array([])
        self._roll = np.array([])
        self._pitch = np.array([])
        self._yaw = np.array([])
        self._speed_t = np.array([])
        self._speed_v = np.array([])
        self._alt_t = np.array([])
        self._alt_v = np.array([])
        self._bat_t = {1: np.array([]), 2: np.array([])}
        self._bat_volt = {1: np.array([]), 2: np.array([])}
        self._bat_curr = {1: np.array([]), 2: np.array([])}
        self._bat_volt_gauges = {1: self.bat1_volt_gauge, 2: self.bat2_volt_gauge}
        self._bat_curr_gauges = {1: self.bat1_curr_gauge, 2: self.bat2_curr_gauge}
        self._cell_count = 8  # Default 8S

    def set_battery_cell_count(self, cell_count: int):
        """Update the battery cell count for voltage-per-cell calculation."""
        self._cell_count = cell_count
        self.bat1_volt_gauge.set_cell_count(cell_count)
        self.bat2_volt_gauge.set_cell_count(cell_count)

    def set_battery_hv_mode(self, is_hv: bool):
        """Enable/disable LiHV high voltage mode."""
        self.bat1_volt_gauge.set_hv_mode(is_hv)
        self.bat2_volt_gauge.set_hv_mode(is_hv)

    def set_current_thresholds(self, green: float, red: float):
        """Update the green/red coloring thresholds for the current gauges."""
        self.bat1_curr_gauge.set_current_thresholds(green, red)
        self.bat2_curr_gauge.set_current_thresholds(green, red)

    def set_speed_thresholds(self, min_v: float, target_v: float, max_v: float):
        """Update the red(min)/green(target)/red(max) coloring thresholds for the speed gauge."""
        self.speed_gauge.set_speed_thresholds(min_v, target_v, max_v)

    def set_data(self, t: np.ndarray, roll: np.ndarray, pitch: np.ndarray, yaw: np.ndarray):
        self._t, self._roll, self._pitch, self._yaw = t, roll, pitch, yaw
        if len(t):
            self.set_cursor_time(t[0])

    def clear_data(self):
        self._t = np.array([])
        self.horizon.set_attitude(0.0, 0.0)
        self.compass.set_heading(0.0)

    def set_speed_data(self, t: np.ndarray, speed: np.ndarray):
        self._speed_t, self._speed_v = t, speed
        if len(speed):
            self.speed_gauge.set_range(0.0, float(np.nanmax(speed)) * 1.1)
        if len(t):
            self.speed_gauge.set_value(float(speed[0]))

    def clear_speed_data(self):
        self._speed_t = np.array([])
        self.speed_gauge.set_value(0.0)

    def set_altitude_data(self, t: np.ndarray, alt: np.ndarray):
        self._alt_t, self._alt_v = t, alt
        if len(alt):
            self.alt_gauge.set_range(float(np.nanmin(alt)), float(np.nanmax(alt)) * 1.1)
        if len(t):
            self.alt_gauge.set_value(float(alt[0]))

    def clear_altitude_data(self):
        self._alt_t = np.array([])
        self.alt_gauge.set_value(0.0)

    def set_battery_data(self, index: int, t: np.ndarray, volt: np.ndarray, curr: np.ndarray):
        self._bat_t[index], self._bat_volt[index], self._bat_curr[index] = t, volt, curr
        if len(volt):
            self._bat_volt_gauges[index].set_range(float(np.nanmin(volt)) * 0.95, float(np.nanmax(volt)) * 1.05)
        if len(curr):
            self._bat_curr_gauges[index].set_range(0.0, float(np.nanmax(curr)) * 1.1)
        if len(t):
            self._bat_volt_gauges[index].set_value(float(volt[0]))
            self._bat_curr_gauges[index].set_value(float(curr[0]))
        if index == 2:
            self._bat2_opacity.setOpacity(1.0)

    def clear_battery_data(self, index: int):
        self._bat_t[index] = np.array([])
        self._bat_volt_gauges[index].set_value(0.0)
        self._bat_curr_gauges[index].set_value(0.0)
        if index == 2:
            self._bat2_opacity.setOpacity(0.35)

    def set_cursor_time(self, t: float):
        if len(self._t):
            idx = int(np.searchsorted(self._t, t))
            idx = max(0, min(idx, len(self._t) - 1))
            self.horizon.set_attitude(self._roll[idx], self._pitch[idx])
            self.compass.set_heading(self._yaw[idx])
        if len(self._speed_t):
            idx = int(np.searchsorted(self._speed_t, t))
            idx = max(0, min(idx, len(self._speed_t) - 1))
            self.speed_gauge.set_value(float(self._speed_v[idx]))
        if len(self._alt_t):
            idx = int(np.searchsorted(self._alt_t, t))
            idx = max(0, min(idx, len(self._alt_t) - 1))
            self.alt_gauge.set_value(float(self._alt_v[idx]))
        for index in (1, 2):
            bt = self._bat_t[index]
            if len(bt):
                idx = int(np.searchsorted(bt, t))
                idx = max(0, min(idx, len(bt) - 1))
                self._bat_volt_gauges[index].set_value(float(self._bat_volt[index][idx]))
                self._bat_curr_gauges[index].set_value(float(self._bat_curr[index][idx]))
