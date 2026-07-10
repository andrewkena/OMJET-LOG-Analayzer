"""Bottom panel showing an artificial horizon (roll/pitch) and a heading
compass (yaw), synced to the playback cursor."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QPainterPath, QPolygonF, QFont
from PySide6.QtSvg import QSvgRenderer
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
# Motor positions for VTOL 4+1 icon (center-relative, ±7 units)
_VTOL41_MOTOR_POS = [(-7, -7), (7, -7), (-7, 7), (7, 7)]

_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
_SVG_ICON_FILES = {
    "VTOL 4+1":        "vtol41_icon.svg",
    "Коптер":          "copter_icon.svg",
    "VTOL 2+1 vector": "vtol31_icon.svg",
    "default":         "def_icon.svg",
}
_svg_renderers: dict[str, QSvgRenderer] = {}


def _get_renderer(vehicle_type: str) -> QSvgRenderer | None:
    if vehicle_type not in _SVG_ICON_FILES:
        return None
    if vehicle_type not in _svg_renderers:
        p = _ASSETS_DIR / _SVG_ICON_FILES[vehicle_type]
        if p.exists():
            _svg_renderers[vehicle_type] = QSvgRenderer(str(p))
    return _svg_renderers.get(vehicle_type)


def apply_icon_mapping(mapping: dict[str, str]) -> None:
    """Update the vehicle-type → SVG filename mapping and clear the renderer cache."""
    _SVG_ICON_FILES.update(mapping)
    _svg_renderers.clear()


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

        # ── Rotating sky / ground background ──────────────────────────────
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
        painter.setBrush(QColor("#1e6eb5"))          # sky blue
        painter.drawRect(QRectF(-big, -big, big * 2, big))
        painter.setBrush(QColor("#7a4a1e"))          # earth brown
        painter.drawRect(QRectF(-big, 0, big * 2, big))
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawLine(QPointF(-big, 0), QPointF(big, 0))

        # Pitch ladder: minor ticks at 5°, major ticks + labels at 10/20/30°
        font = QFont(painter.font())
        font.setPointSize(7)
        painter.setFont(font)
        gap = 8
        for deg in (5, 10, 20, 30):
            major = (deg % 10 == 0)
            half_len = 18 if major else 8
            for sign in (-1, 1):
                y = -sign * deg * px_per_degree
                painter.setPen(QPen(QColor("white"), 1.5))
                painter.drawLine(QPointF(-gap - half_len, y), QPointF(-gap, y))
                painter.drawLine(QPointF(gap, y), QPointF(gap + half_len, y))
                if major:
                    painter.drawText(QRectF(-gap - half_len - 22, y - 7, 20, 14),
                                     Qt.AlignRight | Qt.AlignVCenter, str(deg))
                    painter.drawText(QRectF(gap + half_len + 2, y - 7, 20, 14),
                                     Qt.AlignLeft | Qt.AlignVCenter, str(deg))

        # Bank-angle pointer: undo pitch so it stays fixed at the rim
        painter.translate(0, -pitch_offset)
        ptr_r = radius - 3
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffd000"))
        painter.drawPolygon(QPolygonF([
            QPointF(0,  -ptr_r),
            QPointF(-5, -ptr_r + 11),
            QPointF(5,  -ptr_r + 11),
        ]))

        painter.restore()   # removes clip + all rolling transforms

        # ── Fixed aircraft symbol (yellow wings + centre dot) ──────────────
        painter.setPen(QPen(QColor("#ffd000"), 3))
        painter.drawLine(QPointF(cx - radius * 0.45, cy), QPointF(cx - radius * 0.13, cy))
        painter.drawLine(QPointF(cx + radius * 0.13, cy), QPointF(cx + radius * 0.45, cy))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffd000"))
        painter.drawEllipse(QPointF(cx, cy), 3.5, 3.5)

        # ── Bank-angle scale: tick marks at ±10 ±20 ±30 ±45 ±60 ──────────
        painter.save()
        painter.translate(cx, cy)
        for deg, tick_len, tick_w in [
            (-60, 11, 2.0), (-45,  7, 1.5), (-30, 11, 2.0),
            (-20,  7, 1.5), (-10,  5, 1.5),
            ( 10,  5, 1.5), ( 20,  7, 1.5),
            ( 30, 11, 2.0), ( 45,  7, 1.5), ( 60, 11, 2.0),
        ]:
            painter.save()
            painter.rotate(deg)
            painter.setPen(QPen(QColor("white"), tick_w))
            painter.drawLine(QPointF(0, -(radius - 2)),
                             QPointF(0, -(radius - 2) + tick_len))
            painter.restore()
        painter.restore()

        # ── Fixed 0° reference: white ∇ just above the circle rim ─────────
        painter.save()
        painter.translate(cx, cy)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("white"))
        ref_r = radius + 2
        painter.drawPolygon(QPolygonF([
            QPointF(-5, -ref_r),
            QPointF(5,  -ref_r),
            QPointF(0,  -ref_r + 11),
        ]))
        painter.restore()

        # ── Outer ring ────────────────────────────────────────────────────
        painter.setPen(QPen(QColor("#555555"), 2))
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
        self._vehicle_type = ""

    def set_vehicle_type(self, type_str: str):
        self._vehicle_type = type_str
        self.update()

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

        # Fixed aircraft symbol mounted in the center, pointing up.
        painter.save()
        painter.translate(cx, cy)
        s = radius * 0.06
        painter.setPen(QPen(QColor("#1a1a1a"), 1))
        painter.setBrush(QColor("#ffd000"))
        renderer = _get_renderer(self._vehicle_type)
        is_default = renderer is None
        if is_default:
            renderer = _get_renderer("default")
        if renderer and renderer.isValid():
            if is_default or self._vehicle_type == "Коптер":
                scale = 1.31
            else:
                scale = 1.75
            icon_size = radius * scale
            renderer.render(painter, QRectF(-icon_size / 2, -icon_size / 2, icon_size, icon_size))
        else:
            plane = QPolygonF([QPointF(x * s, y * s) for x, y in _PLANE_POINTS])
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
        self.alt_gauge = TapeGauge("", "м", unit_inline=True, bar_height=150)
        self.bat1_volt_gauge = BatteryGauge("", "V", bar_height=150)
        self.bat1_curr_gauge = TapeGauge("", "A", current_warning=True, unit_inline=True, bar_height=150)
        self.bat2_volt_gauge = BatteryGauge("", "V", bar_height=150)
        self.bat2_curr_gauge = TapeGauge("", "A", current_warning=True, unit_inline=True, bar_height=150)

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
        self.vehicle_type_label = QLabel("Тип: Неизвестен")
        self.vehicle_type_label.setStyleSheet("font-weight: bold;")
        for label in (self.roll_label, self.pitch_label, self.vehicle_type_label):
            label.setAlignment(Qt.AlignHCenter)

        horizon_box = QVBoxLayout()
        horizon_box.addWidget(self.horizon, alignment=Qt.AlignHCenter)
        horizon_box.addWidget(self.roll_label, alignment=Qt.AlignHCenter)
        horizon_box.addWidget(self.pitch_label, alignment=Qt.AlignHCenter)
        horizon_box.addWidget(self.vehicle_type_label, alignment=Qt.AlignHCenter)
        horizon_box.addStretch()

        self.heading_label = QLabel("Курс: --")
        self.bearing_label = QLabel("Курс на точку: --")
        self.wind_speed_label = QLabel("Скорость ветра: --")
        self.wind_dir_label = QLabel("Направление ветра: --")
        for label in (self.heading_label, self.bearing_label, self.wind_speed_label, self.wind_dir_label):
            label.setAlignment(Qt.AlignHCenter)

        compass_box = QVBoxLayout()
        compass_box.addWidget(self.compass, alignment=Qt.AlignHCenter)
        compass_box.addWidget(self.heading_label, alignment=Qt.AlignHCenter)
        compass_box.addWidget(self.bearing_label, alignment=Qt.AlignHCenter)
        compass_box.addWidget(self.wind_speed_label, alignment=Qt.AlignHCenter)
        compass_box.addWidget(self.wind_dir_label, alignment=Qt.AlignHCenter)
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

        self._cmd_wp_t = np.array([])
        self._cmd_wp_lat = np.array([])
        self._cmd_wp_lon = np.array([])

    def set_battery_cell_count(self, cell_count: int):
        """Update the battery cell count for voltage-per-cell calculation."""
        self._cell_count = cell_count
        self.bat1_volt_gauge.set_cell_count(cell_count)
        self.bat2_volt_gauge.set_cell_count(cell_count)

    def set_battery_chemistry(self, instance: int, chemistry: str):
        """Set cell chemistry ('lipo'/'lihv'/'liuhv') for battery instance 1 or 2."""
        gauge = self._bat_volt_gauges.get(instance)
        if gauge is not None:
            gauge.set_chemistry(chemistry)

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

    def set_vehicle_type(self, type_str: str):
        self.vehicle_type_label.setText(f"Тип: {type_str}")
        self.compass.set_vehicle_type(type_str)

    def set_icon_mapping(self, mapping: dict[str, str]):
        apply_icon_mapping(mapping)
        self.compass.update()

    def clear_data(self):
        self._t = np.array([])
        self.horizon.set_attitude(0.0, 0.0)
        self.compass.set_heading(0.0)
        self.roll_label.setText("Крен: --")
        self.pitch_label.setText("Тангаж: --")
        self.heading_label.setText("Курс: --")
        self.bearing_label.setText("Курс на точку: --")
        self.vehicle_type_label.setText("Тип: Неизвестен")
        self.clear_wind_data()

    def set_position_data(self, t: np.ndarray, lat: np.ndarray, lon: np.ndarray):
        self._pos_t, self._pos_lat, self._pos_lon = t, lat, lon
        self._update_target_indices()

    def clear_position_data(self):
        self._pos_t = np.array([])
        self._target_idx = np.array([], dtype=int)
        self._cmd_wp_t = np.array([])
        self._cmd_wp_lat = np.array([])
        self._cmd_wp_lon = np.array([])
        self.bearing_label.setText("Курс на точку: --")

    def set_mission_waypoints(self, waypoints: list[tuple[float, float]]):
        self._waypoints = waypoints
        self._update_target_indices()

    def set_cmd_waypoint_timeline(self, t: np.ndarray, lat: np.ndarray, lon: np.ndarray):
        self._cmd_wp_t = t
        self._cmd_wp_lat = lat
        self._cmd_wp_lon = lon

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
            self.wind_dir_label.setText(f"Направление ветра: {direction_deg[0]:.0f}°")

    def clear_wind_data(self):
        self._wind_t = np.array([])
        self.compass.set_wind_direction(None)
        self.wind_speed_label.setText("Скорость ветра: --")
        self.wind_dir_label.setText("Направление ветра: --")

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
            self.heading_label.setText(f"Курс: {self._yaw[idx]:.0f}°")
        if len(self._pos_t):
            idx = int(np.searchsorted(self._pos_t, t))
            idx = max(0, min(idx, len(self._pos_t) - 1))
            pos_lat = float(self._pos_lat[idx])
            pos_lon = float(self._pos_lon[idx])
            if len(self._cmd_wp_t):
                wp_idx = int(np.searchsorted(self._cmd_wp_t, t, side='right')) - 1
                wp_idx = max(0, min(wp_idx, len(self._cmd_wp_t) - 1))
                bearing = _initial_bearing(pos_lat, pos_lon,
                                           float(self._cmd_wp_lat[wp_idx]),
                                           float(self._cmd_wp_lon[wp_idx]))
                self.bearing_label.setText(f"Курс на точку: {bearing:.0f}°")
            elif len(self._target_idx):
                wp_lat, wp_lon = self._waypoints[int(self._target_idx[idx])]
                bearing = _initial_bearing(pos_lat, pos_lon, wp_lat, wp_lon)
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
            self.wind_dir_label.setText(f"Направление ветра: {float(self._wind_dir[idx]):.0f}°")
        for index in (1, 2):
            bt = self._bat_t[index]
            if len(bt):
                idx = int(np.searchsorted(bt, t))
                idx = max(0, min(idx, len(bt) - 1))
                self._bat_volt_gauges[index].set_value(float(self._bat_volt[index][idx]))
                self._bat_curr_gauges[index].set_value(float(self._bat_curr[index][idx]))
