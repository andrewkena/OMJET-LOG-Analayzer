"""Bottom panel showing an artificial horizon (roll/pitch) and a heading
compass (yaw), synced to the playback cursor."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QPainterPath, QPolygonF, QFont
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QGraphicsOpacityEffect

from app.ui.gauge_widget import TapeGauge, BatteryGauge

_BANK_SCALE_DEGREES = (-60, -45, -30, -15, 15, 30, 45, 60)
_PITCH_LADDER_DEGREES = (10, 20, 30)

_EARTH_RADIUS_M = 6371000.0

# Center-relative outline of the map's aircraft icon (from its 24x24 SVG path, minus (12, 12)).
_PLANE_POINTS = [
    (0, -10), (1.2, -2.8), (9, 3), (9, 4.8), (1, 2.3), (1.6, 7.2), (4, 9), (4, 10),
    (0, 9), (-4, 10), (-4, 9), (-1.6, 7.2), (-1, 2.3), (-9, 4.8), (-9, 3), (-1.2, -2.8),
]


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return math.degrees(math.atan2(y, x)) % 360.0


class AttitudeIndicator(QWidget):
    """Artificial horizon: rolling/pitching sky-ground disc with a fixed aircraft
    symbol, a pitch ladder, and a bank-angle scale with a rotating pointer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 150)
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
        px_per_degree = radius / 45.0

        painter.save()
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), radius, radius)
        painter.setClipPath(clip)

        painter.translate(cx, cy)
        painter.rotate(-self._roll)
        pitch_offset = max(-radius, min(radius, self._pitch * px_per_degree))
        painter.translate(0, pitch_offset)

        big = radius * 3
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2266cc"))
        painter.drawRect(QRectF(-big, -big, big * 2, big))
        painter.setBrush(QColor("#8b5a2b"))
        painter.drawRect(QRectF(-big, 0, big * 2, big))
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawLine(QPointF(-big, 0), QPointF(big, 0))

        # Pitch ladder: short tick lines + labels every 10 degrees, above and below horizon.
        font = QFont(painter.font())
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QPen(QColor("white"), 1.5))
        gap = 6
        for deg in _PITCH_LADDER_DEGREES:
            half_len = 16 - (deg // 10 - 1) * 3
            for sign in (-1, 1):
                y = -sign * deg * px_per_degree
                painter.drawLine(QPointF(-gap - half_len, y), QPointF(-gap, y))
                painter.drawLine(QPointF(gap, y), QPointF(gap + half_len, y))
                painter.drawText(QRectF(-gap - half_len - 20, y - 7, 18, 14),
                                  Qt.AlignRight | Qt.AlignVCenter, str(deg))
                painter.drawText(QRectF(gap + half_len + 2, y - 7, 18, 14),
                                  Qt.AlignLeft | Qt.AlignVCenter, str(deg))

        painter.restore()

        # Fixed aircraft symbol (yellow wings + center dot).
        painter.setPen(QPen(QColor("#ffd000"), 3))
        painter.drawLine(QPointF(cx - radius * 0.45, cy), QPointF(cx - radius * 0.15, cy))
        painter.drawLine(QPointF(cx + radius * 0.15, cy), QPointF(cx + radius * 0.45, cy))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffd000"))
        painter.drawEllipse(QPointF(cx, cy), 3, 3)

        # Bank-angle scale: fixed white dots around the rim, with a rotating pointer.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("white"))
        dot_r = radius - 6
        for deg in _BANK_SCALE_DEGREES:
            angle_rad = math.radians(deg)
            x = cx + dot_r * math.sin(angle_rad)
            y = cy - dot_r * math.cos(angle_rad)
            painter.drawEllipse(QPointF(x, y), 2, 2)

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(-self._roll)
        tri_r = radius - 4
        painter.setBrush(QColor("#ffd000"))
        painter.drawPolygon(QPolygonF([
            QPointF(0, -tri_r),
            QPointF(-5, -tri_r + 8),
            QPointF(5, -tri_r + 8),
        ]))
        painter.restore()

        painter.setPen(QPen(QColor("#444444"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)


_CARDINAL_LABELS = {0: "N", 90: "E", 180: "S", 270: "W"}


class HeadingIndicator(QWidget):
    """Compass card that rotates under a fixed center-mounted aircraft symbol."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 150)
        self._heading = 0.0
        self._wind_dir = None

    def set_heading(self, heading: float):
        self._heading = heading % 360.0
        self.update()

    def set_wind_direction(self, wind_dir: float | None):
        """wind_dir: absolute true bearing the wind blows towards (0=N), or None to hide."""
        self._wind_dir = None if wind_dir is None else wind_dir % 360.0
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
        font = QFont(painter.font())
        font.setPointSize(8)
        painter.setFont(font)
        for deg in range(0, 360, 5):
            painter.save()
            painter.rotate(deg)
            if deg % 30 == 0:
                painter.setPen(QPen(QColor("white"), 1.5))
                painter.drawLine(QPointF(0, -radius + 2), QPointF(0, -radius + 14))
                label = _CARDINAL_LABELS.get(deg)
                if label:
                    painter.setPen(QColor("#ffd000"))
                    painter.drawText(QRectF(-10, -radius + 14, 20, 16), Qt.AlignCenter, label)
                else:
                    painter.setPen(QColor("white"))
                    painter.drawText(QRectF(-10, -radius + 14, 20, 16), Qt.AlignCenter, str(deg // 10))
            elif deg % 10 == 0:
                painter.setPen(QPen(QColor("white"), 1))
                painter.drawLine(QPointF(0, -radius + 2), QPointF(0, -radius + 9))
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("white"))
                painter.drawEllipse(QPointF(0, -radius + 6), 1.2, 1.2)
            painter.restore()

        if self._wind_dir is not None:
            painter.save()
            painter.rotate(self._wind_dir)
            tri_r = radius - 4
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#e6194b"))
            painter.drawPolygon(QPolygonF([
                QPointF(0, -(tri_r - 9)),
                QPointF(-5, -tri_r),
                QPointF(5, -tri_r),
            ]))
            painter.restore()

        painter.restore()

        # Fixed lubber line at the top, marking the current heading reading point.
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawLine(QPointF(cx, cy - radius + 1), QPointF(cx, cy - radius + 8))

        # Fixed aircraft symbol mounted in the center, pointing up (same silhouette as the map icon).
        painter.save()
        painter.translate(cx, cy)
        s = radius * 0.06
        plane = QPolygonF([QPointF(x * s, y * s) for x, y in _PLANE_POINTS])
        painter.setPen(QPen(QColor("#1a1a1a"), 1))
        painter.setBrush(QColor("#ffd000"))
        painter.drawPolygon(plane)
        painter.restore()


def _column_container(height: int, header_widgets, row_item) -> QWidget:
    """Wrap an optional header + a gauge/row in a fixed-height widget so the
    gauge is anchored to the bottom, aligning gauge bottoms across columns."""
    container = QWidget()
    vbox = QVBoxLayout(container)
    vbox.setContentsMargins(0, 0, 0, 0)
    for widget in header_widgets:
        vbox.addWidget(widget, alignment=Qt.AlignHCenter)
    vbox.addStretch()
    if isinstance(row_item, QWidget):
        vbox.addWidget(row_item, alignment=Qt.AlignHCenter)
    else:
        vbox.addLayout(row_item)
    container.setFixedHeight(height)
    return container


class AttitudePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(260)

        self.horizon = AttitudeIndicator()
        self.compass = HeadingIndicator()
        self.speed_gauge = TapeGauge("", "м/с", extra_label=None, unit_inline=True, bar_height=150)
        self.alt_gauge = TapeGauge("", "m", bar_height=150)
        self.bat1_volt_gauge = BatteryGauge("", "V", bar_height=150)
        self.bat1_curr_gauge = TapeGauge("", "A", current_warning=True, bar_height=150)
        self.bat2_volt_gauge = BatteryGauge("", "V", bar_height=150)
        self.bat2_curr_gauge = TapeGauge("", "A", current_warning=True, bar_height=150)

        _BOLD_STYLE = "font-weight: bold;"
        speed_label = QLabel("Воздушная\nскорость")
        speed_label.setAlignment(Qt.AlignHCenter)
        speed_label.setStyleSheet(_BOLD_STYLE)
        alt_label = QLabel("Высота")
        alt_label.setAlignment(Qt.AlignHCenter)
        alt_label.setStyleSheet(_BOLD_STYLE)

        speed_container = _column_container(260, [speed_label], self.speed_gauge)

        self.roll_label = QLabel("Крен: --")
        self.pitch_label = QLabel("Тангаж: --")
        for label in (self.roll_label, self.pitch_label):
            label.setAlignment(Qt.AlignHCenter)

        horizon_box = QVBoxLayout()
        horizon_box.addStretch()
        horizon_box.addWidget(self.horizon, alignment=Qt.AlignHCenter)
        horizon_box.addWidget(self.roll_label, alignment=Qt.AlignHCenter)
        horizon_box.addWidget(self.pitch_label, alignment=Qt.AlignHCenter)
        horizon_box.addStretch()

        self.heading_label = QLabel("Курс истинный: --")
        self.bearing_label = QLabel("Курс на точку: --")
        self.wind_speed_label = QLabel("Скорость ветра: --")
        for label in (self.heading_label, self.bearing_label, self.wind_speed_label):
            label.setAlignment(Qt.AlignHCenter)

        compass_box = QVBoxLayout()
        compass_box.addStretch()
        compass_box.addWidget(self.compass, alignment=Qt.AlignHCenter)
        compass_box.addWidget(self.heading_label, alignment=Qt.AlignHCenter)
        compass_box.addWidget(self.bearing_label, alignment=Qt.AlignHCenter)
        compass_box.addWidget(self.wind_speed_label, alignment=Qt.AlignHCenter)
        compass_box.addStretch()

        alt_container = _column_container(260, [alt_label], self.alt_gauge)

        def _bat_column(gauge, label_text: str) -> QVBoxLayout:
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignHCenter)
            col = QVBoxLayout()
            col.addWidget(label, alignment=Qt.AlignHCenter)
            col.addWidget(gauge, alignment=Qt.AlignHCenter)
            return col

        bat1_label = QLabel("Батарея 1")
        bat1_label.setStyleSheet("font-weight: bold;")
        bat1_row = QHBoxLayout()
        bat1_row.addLayout(_bat_column(self.bat1_volt_gauge, "Напряжение"))
        bat1_row.addLayout(_bat_column(self.bat1_curr_gauge, "Ток"))
        self.bat1_container = _column_container(260, [bat1_label], bat1_row)

        bat2_label = QLabel("Батарея 2")
        bat2_label.setStyleSheet("font-weight: bold;")
        bat2_row = QHBoxLayout()
        bat2_row.addLayout(_bat_column(self.bat2_volt_gauge, "Напряжение"))
        bat2_row.addLayout(_bat_column(self.bat2_curr_gauge, "Ток"))
        self.bat2_container = _column_container(260, [bat2_label], bat2_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)

        layout = QHBoxLayout(self)
        layout.addWidget(speed_container, alignment=Qt.AlignTop)
        layout.addLayout(horizon_box)
        layout.addLayout(compass_box)
        layout.addWidget(alt_container, alignment=Qt.AlignTop)
        layout.addWidget(separator)
        layout.addWidget(self.bat1_container, alignment=Qt.AlignTop)
        layout.addWidget(self.bat2_container, alignment=Qt.AlignTop)
        layout.addStretch()

        self._t = np.array([])
        self._roll = np.array([])
        self._pitch = np.array([])
        self._yaw = np.array([])
        self._speed_t = np.array([])
        self._speed_v = np.array([])
        self._gs_t = np.array([])
        self._gs_v = np.array([])
        self._alt_t = np.array([])
        self._alt_v = np.array([])
        self._bat_t = {1: np.array([]), 2: np.array([])}
        self._bat_volt = {1: np.array([]), 2: np.array([])}
        self._bat_curr = {1: np.array([]), 2: np.array([])}
        self._bat_volt_gauges = {1: self.bat1_volt_gauge, 2: self.bat2_volt_gauge}
        self._bat_curr_gauges = {1: self.bat1_curr_gauge, 2: self.bat2_curr_gauge}
        self._cell_count = 8  # Default 8S

        self._wind_t = np.array([])
        self._wind_dir = np.array([])
        self._wind_speed = np.array([])

        self._pos_t = np.array([])
        self._pos_lat = np.array([])
        self._pos_lon = np.array([])
        self._waypoints: list[tuple[float, float]] = []
        self._target_idx = np.array([], dtype=int)

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
        self.roll_label.setText("Крен: --")
        self.pitch_label.setText("Тангаж: --")
        self.heading_label.setText("Курс истинный: --")
        self.bearing_label.setText("Курс на точку: --")
        self.clear_wind_data()

    def set_position_data(self, t: np.ndarray, lat: np.ndarray, lon: np.ndarray):
        self._pos_t, self._pos_lat, self._pos_lon = t, lat, lon
        self._update_target_indices()

    def clear_position_data(self):
        self._pos_t = np.array([])
        self._target_idx = np.array([], dtype=int)
        self.bearing_label.setText("Курс на точку: --")

    def set_mission_waypoints(self, waypoints: list[tuple[float, float]]):
        self._waypoints = waypoints
        self._update_target_indices()

    def _update_target_indices(self):
        """Pick, for every position sample, the next not-yet-reached waypoint
        (the target only ever advances forward, switching once within 15 m)."""
        if len(self._pos_t) == 0 or not self._waypoints:
            self._target_idx = np.array([], dtype=int)
            return
        n_wp = len(self._waypoints)
        target = np.zeros(len(self._pos_t), dtype=int)
        wp_idx = 0
        for i in range(len(self._pos_t)):
            lat_i, lon_i = float(self._pos_lat[i]), float(self._pos_lon[i])
            while wp_idx < n_wp - 1 and _haversine_m(lat_i, lon_i, *self._waypoints[wp_idx]) < 15.0:
                wp_idx += 1
            target[i] = wp_idx
        self._target_idx = target

    def set_speed_data(self, t: np.ndarray, speed: np.ndarray):
        self._speed_t, self._speed_v = t, speed
        if len(speed):
            self.speed_gauge.set_range(0.0, float(np.nanmax(speed)) * 1.1)
        if len(t):
            self.speed_gauge.set_value(float(speed[0]))

    def clear_speed_data(self):
        self._speed_t = np.array([])
        self.speed_gauge.set_value(0.0)

    def set_ground_speed_data(self, t: np.ndarray, speed: np.ndarray):
        self._gs_t, self._gs_v = t, speed
        if len(t):
            self.speed_gauge.set_extra_text(f"{speed[0]:.1f} м/с")

    def clear_ground_speed_data(self):
        self._gs_t = np.array([])
        self.speed_gauge.set_extra_text("")

    def set_altitude_data(self, t: np.ndarray, alt: np.ndarray):
        self._alt_t, self._alt_v = t, alt
        if len(alt):
            self.alt_gauge.set_range(float(np.nanmin(alt)), float(np.nanmax(alt)) * 1.1)
        if len(t):
            self.alt_gauge.set_value(float(alt[0]))

    def clear_altitude_data(self):
        self._alt_t = np.array([])
        self.alt_gauge.set_value(0.0)

    def set_wind_data(self, t: np.ndarray, direction_deg: np.ndarray, speed: np.ndarray):
        self._wind_t, self._wind_dir, self._wind_speed = t, direction_deg, speed
        if len(t):
            self.compass.set_wind_direction(float(direction_deg[0]))
            self.wind_speed_label.setText(f"Скорость ветра: {speed[0]:.1f} м/с")

    def clear_wind_data(self):
        self._wind_t = np.array([])
        self.compass.set_wind_direction(None)
        self.wind_speed_label.setText("Скорость ветра: --")

    def set_battery_data(self, index: int, t: np.ndarray, volt: np.ndarray, curr: np.ndarray):
        self._bat_t[index], self._bat_volt[index], self._bat_curr[index] = t, volt, curr
        if len(volt):
            self._bat_volt_gauges[index].set_range(float(np.nanmin(volt)) * 0.95, float(np.nanmax(volt)) * 1.05)
        if len(curr):
            self._bat_curr_gauges[index].set_range(0.0, float(np.nanmax(curr)) * 1.1)
        if len(t):
            self._bat_volt_gauges[index].set_value(float(volt[0]))
            self._bat_curr_gauges[index].set_value(float(curr[0]))

    def clear_battery_data(self, index: int):
        self._bat_t[index] = np.array([])
        self._bat_volt_gauges[index].set_value(0.0)
        self._bat_curr_gauges[index].set_value(0.0)

    def set_cursor_time(self, t: float):
        if len(self._t):
            idx = int(np.searchsorted(self._t, t))
            idx = max(0, min(idx, len(self._t) - 1))
            self.horizon.set_attitude(self._roll[idx], self._pitch[idx])
            self.compass.set_heading(self._yaw[idx])
            self.roll_label.setText(f"Крен: {self._roll[idx]:.0f}°")
            self.pitch_label.setText(f"Тангаж: {self._pitch[idx]:.0f}°")
            self.heading_label.setText(f"Курс истинный: {self._yaw[idx]:.0f}°")
        if len(self._pos_t):
            idx = int(np.searchsorted(self._pos_t, t))
            idx = max(0, min(idx, len(self._pos_t) - 1))
            if len(self._target_idx):
                wp_lat, wp_lon = self._waypoints[int(self._target_idx[idx])]
                bearing = _initial_bearing(float(self._pos_lat[idx]), float(self._pos_lon[idx]), wp_lat, wp_lon)
                self.bearing_label.setText(f"Курс на точку: {bearing:.0f}°")
            else:
                self.bearing_label.setText("Курс на точку: --")
        if len(self._speed_t):
            idx = int(np.searchsorted(self._speed_t, t))
            idx = max(0, min(idx, len(self._speed_t) - 1))
            self.speed_gauge.set_value(float(self._speed_v[idx]))
        if len(self._gs_t):
            idx = int(np.searchsorted(self._gs_t, t))
            idx = max(0, min(idx, len(self._gs_t) - 1))
            self.speed_gauge.set_extra_text(f"{float(self._gs_v[idx]):.1f} м/с")
        if len(self._alt_t):
            idx = int(np.searchsorted(self._alt_t, t))
            idx = max(0, min(idx, len(self._alt_t) - 1))
            self.alt_gauge.set_value(float(self._alt_v[idx]))
        if len(self._wind_t):
            idx = int(np.searchsorted(self._wind_t, t))
            idx = max(0, min(idx, len(self._wind_t) - 1))
            self.compass.set_wind_direction(float(self._wind_dir[idx]))
            self.wind_speed_label.setText(f"Скорость ветра: {float(self._wind_speed[idx]):.1f} м/с")
        for index in (1, 2):
            bt = self._bat_t[index]
            if len(bt):
                idx = int(np.searchsorted(bt, t))
                idx = max(0, min(idx, len(bt) - 1))
                self._bat_volt_gauges[index].set_value(float(self._bat_volt[index][idx]))
                self._bat_curr_gauges[index].set_value(float(self._bat_curr[index][idx]))
