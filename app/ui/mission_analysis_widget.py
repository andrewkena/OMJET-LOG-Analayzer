"""Mission Analysis tab - summary stats computed from the loaded log:
start/end/duration, distance flown, motor run times, max attitude,
photo count and per-battery mAh consumed.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QLabel, QPushButton,
)

from app.core import i18n
from app.core.log_loader import LogData
from app.core.time_format import format_mmss, format_gps_time
from app.ui.battery_widget import BatteryWidget, _battery_instance_table

# Same candidate lists used elsewhere in the app (main_window.py) for
# resolving fields across different log dialects/firmware versions.
_GPS_LAT_CANDIDATES = [("GPS", "Lat", "Lng"), ("GPS", "Lat", "Lon"), ("GLOBAL_POSITION_INT", "lat", "lon")]
_ATTITUDE_CANDIDATES = [
    ("ATT", "Roll", "Pitch", "Yaw", False),
    ("ATTITUDE", "roll", "pitch", "yaw", True),
]
_SERVO_FUNCTION_IDS = {
    "Aileron": 4, "Elevator": 19, "Rudder": 21, "Throttle": 70,
    "Motor1": 33, "Motor2": 34, "Motor3": 35, "Motor4": 36,
}
_VERTICAL_MOTOR_KEYS = ["Motor1", "Motor2", "Motor3", "Motor4"]
_FORWARD_MOTOR_KEY = "Throttle"
_WIND_CANDIDATES = [("XKF2", "VWN", "VWE"), ("NKF2", "VWN", "VWE")]
_ARM_EVENT_ID = 10
_DISARM_EVENT_ID = 11
_RUNNING_PWM = 1050.0  # above idle (1000us) -> motor considered spinning
_EARTH_RADIUS_M = 6371000.0

_EFF_GREEN_RGB = (60, 180, 75)
_EFF_YELLOW_RGB = (241, 196, 15)
_EFF_RED_RGB = (230, 25, 75)


def _haversine_distance_m(lat: np.ndarray, lon: np.ndarray) -> float:
    if len(lat) < 2:
        return 0.0
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    dlat = np.diff(lat_r)
    dlon = np.diff(lon_r)
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat_r[:-1]) * np.cos(lat_r[1:]) * np.sin(dlon / 2.0) ** 2
    seg = 2 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return float(np.sum(seg))


def _running_time_s(t: np.ndarray, pwm: np.ndarray) -> float:
    if len(t) < 2:
        return 0.0
    dt = np.diff(t)
    running = pwm[:-1] > _RUNNING_PWM
    return float(np.sum(dt[running]))


def _distance_while_running_m(lat: np.ndarray, lon: np.ndarray, t: np.ndarray,
                               motor_t: np.ndarray, motor_pwm: np.ndarray) -> float:
    """Like _haversine_distance_m, but only counts segments where the motor
    (sampled on its own RCOU timestamp grid, interpolated onto `t`) is running.
    """
    if len(lat) < 2:
        return 0.0
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    dlat = np.diff(lat_r)
    dlon = np.diff(lon_r)
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat_r[:-1]) * np.cos(lat_r[1:]) * np.sin(dlon / 2.0) ** 2
    seg = 2 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    pwm_at = np.interp(t[:-1], motor_t, motor_pwm)
    running = pwm_at > _RUNNING_PWM
    return float(np.sum(seg[running]))


def _mah_while_running(t: np.ndarray, curr: np.ndarray, motor_t: np.ndarray, motor_pwm: np.ndarray) -> float:
    """Integrates Curr*dt (in mA*h) over only the intervals where the motor is running,
    aligning the battery's timestamp grid with the motor's RCOU timestamp grid via interpolation.
    """
    if len(t) < 2:
        return 0.0
    dt_hours = np.diff(t) / 3600.0
    pwm_at = np.interp(t[:-1], motor_t, motor_pwm)
    running = pwm_at > _RUNNING_PWM
    return float(np.sum(curr[:-1][running] * dt_hours[running]) * 1000.0)


def _lerp_rgb(c0: tuple[int, int, int], c1: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))


class MissionAnalysisWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._eff_green = 200.0
        self._eff_yellow = 300.0
        self._eff_red = 400.0
        self._eff_values: dict[str, float | None] = {
            "overall_km": None, "overall_min": None, "forward_km": None, "forward_min": None,
        }
        self._log_path: str | None = None
        self._last_log_data: object = None
        self._start_t: float = 0.0
        self._end_t: float = 0.0
        layout = QVBoxLayout(self)

        self.time_group = QGroupBox()
        self.time_layout = QFormLayout(self.time_group)
        self.start_label = QLabel("—")
        self.end_label = QLabel("—")
        self.duration_label = QLabel("—")
        self.time_layout.addRow(" ", self.start_label)
        self.time_layout.addRow(" ", self.end_label)
        self.time_layout.addRow(" ", self.duration_label)

        self.flight_group = QGroupBox()
        self.flight_layout = QFormLayout(self.flight_group)
        self.distance_label = QLabel("—")
        self.vertical_motor_time_label = QLabel("—")
        self.forward_motor_time_label = QLabel("—")
        self.planning_time_label = QLabel("—")
        self.flight_layout.addRow(" ", self.distance_label)
        self.flight_layout.addRow(" ", self.vertical_motor_time_label)
        self.flight_layout.addRow(" ", self.forward_motor_time_label)
        self.flight_layout.addRow(" ", self.planning_time_label)

        self.wind_group = QGroupBox()
        self.wind_layout = QFormLayout(self.wind_group)
        self.avg_wind_label = QLabel("—")
        self.max_wind_label = QLabel("—")
        self.wind_dir_label = QLabel("—")
        self.wind_layout.addRow(" ", self.avg_wind_label)
        self.wind_layout.addRow(" ", self.max_wind_label)
        self.wind_layout.addRow(" ", self.wind_dir_label)

        self.attitude_group = QGroupBox()
        self.attitude_layout = QFormLayout(self.attitude_group)
        self.max_roll_label = QLabel("—")
        self.max_pitch_label = QLabel("—")
        self.attitude_layout.addRow(" ", self.max_roll_label)
        self.attitude_layout.addRow(" ", self.max_pitch_label)

        self.photo_group = QGroupBox()
        self.photo_layout = QFormLayout(self.photo_group)
        self.cam_count_label = QLabel("—")
        self.trig_count_label = QLabel("—")
        self.avg_photo_time_label = QLabel("—")
        self.avg_photo_distance_label = QLabel("—")
        self.photo_layout.addRow(" ", self.cam_count_label)
        self.photo_layout.addRow(" ", self.trig_count_label)
        self.photo_layout.addRow(" ", self.avg_photo_time_label)
        self.photo_layout.addRow(" ", self.avg_photo_distance_label)

        self.efficiency_group = QGroupBox()
        self.efficiency_layout = QFormLayout(self.efficiency_group)
        self.overall_mah_per_km_label, self.overall_mah_per_km_dot, overall_km_row = self._make_efficiency_row()
        self.overall_mah_per_min_label, self.overall_mah_per_min_dot, overall_min_row = self._make_efficiency_row()
        self.forward_mah_per_km_label, self.forward_mah_per_km_dot, forward_km_row = self._make_efficiency_row()
        self.forward_mah_per_min_label, self.forward_mah_per_min_dot, forward_min_row = self._make_efficiency_row()
        self.efficiency_layout.addRow(" ", overall_km_row)
        self.efficiency_layout.addRow(" ", overall_min_row)
        self.efficiency_layout.addRow(" ", forward_km_row)
        self.efficiency_layout.addRow(" ", forward_min_row)

        self.battery_widget = BatteryWidget()

        self.report_button = QPushButton()
        self.report_button.setEnabled(False)
        self.report_button.clicked.connect(self._open_report_dialog)

        i18n.register(self._retranslateUi)
        self._retranslateUi()

        columns_layout = QHBoxLayout()
        left_column = QVBoxLayout()
        left_column.addWidget(self.time_group)
        left_column.addWidget(self.flight_group)
        left_column.addWidget(self.wind_group)
        left_column.addWidget(self.attitude_group)
        left_column.addWidget(self.photo_group)
        left_column.addStretch()

        right_column = QVBoxLayout()
        right_column.addWidget(self.efficiency_group)
        right_column.addWidget(self.battery_widget)
        right_column.addStretch()

        columns_layout.addLayout(left_column)
        columns_layout.addLayout(right_column)
        layout.addLayout(columns_layout)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self.report_button)
        layout.addLayout(btn_row)

    def _retranslateUi(self):
        tr = i18n.tr
        self.time_group.setTitle(tr("Время"))
        self.time_layout.labelForField(self.start_label).setText(tr("Время начала миссии:"))
        self.time_layout.labelForField(self.end_label).setText(tr("Время окончания:"))
        self.time_layout.labelForField(self.duration_label).setText(tr("Продолжительность:"))

        self.flight_group.setTitle(tr("Полет"))
        self.flight_layout.labelForField(self.distance_label).setText(tr("Пройденное расстояние:"))
        self.flight_layout.labelForField(self.vertical_motor_time_label).setText(tr("Время работы вертикальных моторов:"))
        self.flight_layout.labelForField(self.forward_motor_time_label).setText(tr("Время работы ходового мотора:"))
        self.flight_layout.labelForField(self.planning_time_label).setText(tr("Время планирования (без моторов):"))

        self.wind_group.setTitle(tr("Ветер"))
        self.wind_layout.labelForField(self.avg_wind_label).setText(tr("Средний ветер:"))
        self.wind_layout.labelForField(self.max_wind_label).setText(tr("Максимальный ветер:"))
        self.wind_layout.labelForField(self.wind_dir_label).setText(tr("Преобладающее направление ветра:"))

        self.attitude_group.setTitle(tr("Углы"))
        self.attitude_layout.labelForField(self.max_roll_label).setText(tr("Максимальный крен:"))
        self.attitude_layout.labelForField(self.max_pitch_label).setText(tr("Максимальный тангаж:"))

        self.photo_group.setTitle(tr("Фотосъемка"))
        self.photo_layout.labelForField(self.cam_count_label).setText(tr("Количество фотоимпульсов отправленных в камеры:"))
        self.photo_layout.labelForField(self.trig_count_label).setText(tr("Количество фотоимпульсов полученных от камеры:"))
        self.photo_layout.labelForField(self.avg_photo_time_label).setText(tr("Среднее время между фотоснимками:"))
        self.photo_layout.labelForField(self.avg_photo_distance_label).setText(tr("Среднее расстояние между фотоснимками:"))

        self.efficiency_group.setTitle(tr("Эффективность"))
        self.efficiency_layout.labelForField(self.overall_mah_per_km_label.parent()).setText(tr("Общий расход на километр:"))
        self.efficiency_layout.labelForField(self.overall_mah_per_min_label.parent()).setText(tr("Общий расход на минуту:"))
        self.efficiency_layout.labelForField(self.forward_mah_per_km_label.parent()).setText(tr("Горизонтальный расход на километр:"))
        self.efficiency_layout.labelForField(self.forward_mah_per_min_label.parent()).setText(tr("Горизонтальный расход на минуту:"))

        self.report_button.setText(tr("Сформировать отчёт"))

    @staticmethod
    def _make_efficiency_row() -> tuple[QLabel, QLabel, QWidget]:
        """Build a "value label + colored dot" row for an efficiency stat."""
        value_label = QLabel("—")
        dot_label = QLabel()
        dot_label.setFixedSize(12, 12)
        dot_label.setStyleSheet("background-color: #555555; border-radius: 6px;")
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(value_label)
        row_layout.addWidget(dot_label)
        row_layout.addStretch()
        return value_label, dot_label, row

    def set_efficiency_thresholds(self, green: float, yellow: float, red: float):
        """Set the mAh-consumption thresholds for the efficiency dot coloring
        (lower is better: <= green -> green, >= red -> red)."""
        self._eff_green = green
        self._eff_yellow = yellow
        self._eff_red = red
        self._update_efficiency_dots()

    def _efficiency_rgb(self, value: float) -> tuple[int, int, int]:
        g, y, r = self._eff_green, self._eff_yellow, self._eff_red
        if value <= g:
            return _EFF_GREEN_RGB
        if value >= r:
            return _EFF_RED_RGB
        if value <= y:
            ratio = (value - g) / (y - g) if y > g else 1.0
            return _lerp_rgb(_EFF_GREEN_RGB, _EFF_YELLOW_RGB, ratio)
        ratio = (value - y) / (r - y) if r > y else 1.0
        return _lerp_rgb(_EFF_YELLOW_RGB, _EFF_RED_RGB, ratio)

    def _update_efficiency_dots(self):
        dots = {
            "overall_km": self.overall_mah_per_km_dot, "overall_min": self.overall_mah_per_min_dot,
            "forward_km": self.forward_mah_per_km_dot, "forward_min": self.forward_mah_per_min_dot,
        }
        for key, dot in dots.items():
            value = self._eff_values.get(key)
            if value is None:
                dot.setStyleSheet("background-color: #555555; border-radius: 6px;")
                continue
            rgb = self._efficiency_rgb(value)
            dot.setStyleSheet(f"background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]}); border-radius: 6px;")

    def set_log_path(self, path: str) -> None:
        self._log_path = path

    def load(self, log_data: LogData):
        self._last_log_data = log_data
        self.report_button.setEnabled(True)
        start_t, end_t = self._mission_bounds(log_data)
        self._start_t = start_t
        self._end_t = end_t
        self.start_label.setText(format_gps_time(start_t))
        self.end_label.setText(format_gps_time(end_t))
        self.duration_label.setText(format_mmss(end_t - start_t))

        self.distance_label.setText(f"{self._distance_m(log_data):.0f} м")

        vert_t, fwd_t = self._motor_times(log_data)
        duration = max(end_t - start_t, 0.0)
        planning_t = max(duration - max(vert_t, fwd_t), 0.0)
        self.vertical_motor_time_label.setText(format_mmss(vert_t))
        self.forward_motor_time_label.setText(format_mmss(fwd_t))
        self.planning_time_label.setText(format_mmss(planning_t))

        avg_wind, max_wind = self._wind_stats(log_data)
        self.avg_wind_label.setText(f"{avg_wind:.1f} м/с" if avg_wind is not None else "—")
        self.max_wind_label.setText(f"{max_wind:.1f} м/с" if max_wind is not None else "—")
        wind_dir = self._prevailing_wind_direction(log_data)
        self.wind_dir_label.setText(wind_dir if wind_dir is not None else "—")

        max_roll, max_pitch = self._max_attitude(log_data)
        self.max_roll_label.setText(f"{max_roll:.1f}°")
        self.max_pitch_label.setText(f"{max_pitch:.1f}°")

        cam_count, trig_count, avg_photo_time, avg_photo_distance = self._photo_stats(log_data)
        self.cam_count_label.setText(str(cam_count))
        self.trig_count_label.setText(str(trig_count))
        self.avg_photo_time_label.setText(f"{avg_photo_time:.1f} с" if avg_photo_time is not None else "—")
        self.avg_photo_distance_label.setText(
            f"{avg_photo_distance:.1f} м" if avg_photo_distance is not None else "—"
        )

        overall_per_km, overall_per_min, fwd_per_km, fwd_per_min = self._efficiency_stats(
            log_data, duration, self._distance_m(log_data)
        )
        self.overall_mah_per_km_label.setText(f"{overall_per_km:.0f} мА·ч/км" if overall_per_km is not None else "—")
        self.overall_mah_per_min_label.setText(f"{overall_per_min:.0f} мА·ч/мин" if overall_per_min is not None else "—")
        self.forward_mah_per_km_label.setText(f"{fwd_per_km:.0f} мА·ч/км" if fwd_per_km is not None else "—")
        self.forward_mah_per_min_label.setText(f"{fwd_per_min:.0f} мА·ч/мин" if fwd_per_min is not None else "—")
        self._eff_values = {
            "overall_km": overall_per_km, "overall_min": overall_per_min,
            "forward_km": fwd_per_km, "forward_min": fwd_per_min,
        }
        self._update_efficiency_dots()

        self.battery_widget.load(log_data)

    def _mission_bounds(self, log_data: LogData) -> tuple[float, float]:
        ev_table = log_data.messages.get("EV")
        if ev_table and "Id" in ev_table:
            ids = ev_table["Id"]
            times = ev_table["timestamp"]
            arm_times = times[ids == _ARM_EVENT_ID]
            disarm_times = times[ids == _DISARM_EVENT_ID]
            if len(arm_times):
                start_t = float(arm_times[0])
                later_disarms = disarm_times[disarm_times >= start_t]
                end_t = float(later_disarms[-1]) if len(later_disarms) else float(log_data.end_time)
                return start_t, end_t
        return float(log_data.start_time), float(log_data.end_time)

    def _distance_m(self, log_data: LogData, motor: tuple[np.ndarray, np.ndarray] | None = None) -> float:
        for msg_type, lat_f, lon_f in _GPS_LAT_CANDIDATES:
            table = log_data.messages.get(msg_type)
            if table and lat_f in table and lon_f in table:
                lat = table[lat_f]
                lon = table[lon_f]
                if msg_type == "GLOBAL_POSITION_INT":
                    lat = lat / 1e7
                    lon = lon / 1e7
                if motor is None:
                    return _haversine_distance_m(lat, lon)
                motor_t, motor_pwm = motor
                return _distance_while_running_m(lat, lon, table["timestamp"], motor_t, motor_pwm)
        return 0.0

    def _channel_for_function(self, log_data: LogData) -> dict[str, int]:
        param_map = {p["name"]: p["value"] for p in log_data.parameters()}
        channel_for_function: dict[str, int] = {}
        for ch in range(1, 15):
            func_val = param_map.get(f"SERVO{ch}_FUNCTION")
            if func_val is None:
                continue
            for label, fid in _SERVO_FUNCTION_IDS.items():
                if label not in channel_for_function and int(func_val) == fid:
                    channel_for_function[label] = ch
        return channel_for_function

    def _motor_times(self, log_data: LogData) -> tuple[float, float]:
        rcou_table = log_data.messages.get("RCOU")
        if not rcou_table:
            return 0.0, 0.0
        channel_for_function = self._channel_for_function(log_data)

        def total_running_time(keys: list[str]) -> float:
            total = 0.0
            for key in keys:
                ch = channel_for_function.get(key)
                field = f"C{ch}" if ch else None
                if field and field in rcou_table:
                    total = max(total, _running_time_s(rcou_table["timestamp"], rcou_table[field]))
            return total

        vert_t = total_running_time(_VERTICAL_MOTOR_KEYS)
        fwd_t = total_running_time([_FORWARD_MOTOR_KEY])
        return vert_t, fwd_t

    def _forward_motor_series(self, log_data: LogData) -> tuple[np.ndarray, np.ndarray] | None:
        rcou_table = log_data.messages.get("RCOU")
        if not rcou_table:
            return None
        ch = self._channel_for_function(log_data).get(_FORWARD_MOTOR_KEY)
        field = f"C{ch}" if ch else None
        if not field or field not in rcou_table:
            return None
        return rcou_table["timestamp"], rcou_table[field]

    def _battery_mah(self, log_data: LogData, motor: tuple[np.ndarray, np.ndarray] | None = None) -> float:
        """Total mA*h consumed across both battery instances. When `motor` is
        given (RCOU timestamp/pwm of the forward motor), only counts mA*h
        accrued while that motor is running; otherwise uses the logged
        cumulative CurrTot when available, falling back to integrating Curr.
        """
        bat_table = log_data.messages.get("BAT")
        bat2_table = log_data.messages.get("BAT2")
        total = 0.0
        for instance in (0, 1):
            sub = _battery_instance_table(bat_table, bat2_table, instance)
            if not sub or "Curr" not in sub or len(sub["Curr"]) < 2:
                continue
            t = sub["timestamp"]
            curr = sub["Curr"]
            if motor is not None:
                motor_t, motor_pwm = motor
                total += _mah_while_running(t, curr, motor_t, motor_pwm)
            elif "CurrTot" in sub and len(sub["CurrTot"]):
                total += float(sub["CurrTot"][-1])
            else:
                dt_hours = np.diff(t) / 3600.0
                total += float(np.sum(curr[:-1] * dt_hours) * 1000.0)
        return total

    def _efficiency_stats(
        self, log_data: LogData, duration_s: float, distance_m: float
    ) -> tuple[float | None, float | None, float | None, float | None]:
        total_mah = self._battery_mah(log_data)
        overall_per_km = total_mah / (distance_m / 1000.0) if distance_m > 0 else None
        overall_per_min = total_mah / (duration_s / 60.0) if duration_s > 0 else None

        forward = self._forward_motor_series(log_data)
        if forward is None:
            return overall_per_km, overall_per_min, None, None

        motor_t, motor_pwm = forward
        fwd_time_s = _running_time_s(motor_t, motor_pwm)
        fwd_mah = self._battery_mah(log_data, motor=forward)
        fwd_distance_m = self._distance_m(log_data, motor=forward)
        fwd_per_km = fwd_mah / (fwd_distance_m / 1000.0) if fwd_distance_m > 0 else None
        fwd_per_min = fwd_mah / (fwd_time_s / 60.0) if fwd_time_s > 0 else None
        return overall_per_km, overall_per_min, fwd_per_km, fwd_per_min

    def _wind_series(self, log_data: LogData) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        for msg_type, north_f, east_f in _WIND_CANDIDATES:
            table = log_data.messages.get(msg_type)
            if table and north_f in table and east_f in table:
                return table["timestamp"], table[north_f], table[east_f]
        return None

    def _wind_stats(self, log_data: LogData) -> tuple[float | None, float | None]:
        wind = self._wind_series(log_data)
        if wind is None:
            return None, None
        _, vwn, vwe = wind
        speed = np.hypot(vwn, vwe)
        if len(speed) == 0:
            return None, None
        return float(np.mean(speed)), float(np.max(speed))

    def _prevailing_wind_direction(self, log_data: LogData) -> str | None:
        """Classify the dominant wind-vs-heading relationship over the flight as
        headwind/crosswind/tailwind, weighted by the time spent in each sector
        (sector boundaries at 45 deg and 135 deg from dead-ahead).
        """
        wind = self._wind_series(log_data)
        if wind is None:
            return None
        wind_t, vwn, vwe = wind
        if len(wind_t) < 2:
            return None
        # Bearing the wind blows towards (0=N), same convention as main_window.py.
        wind_dir = (np.degrees(np.arctan2(vwe, vwn)) + 180.0) % 360.0

        att_t = att_yaw = None
        for msg_type, roll_f, pitch_f, yaw_f, is_radians in _ATTITUDE_CANDIDATES:
            table = log_data.messages.get(msg_type)
            if table and yaw_f in table:
                yaw = np.degrees(table[yaw_f]) if is_radians else table[yaw_f]
                att_t, att_yaw = table["timestamp"], np.mod(yaw, 360.0)
                break
        if att_t is None or len(att_t) < 2:
            return None

        yaw_rad = np.radians(att_yaw)
        sin_at = np.interp(wind_t, att_t, np.sin(yaw_rad))
        cos_at = np.interp(wind_t, att_t, np.cos(yaw_rad))
        heading_at = np.degrees(np.arctan2(sin_at, cos_at)) % 360.0

        diff = np.abs(((wind_dir - heading_at + 180.0) % 360.0) - 180.0)[:-1]
        dt = np.diff(wind_t)

        tail_t = float(np.sum(dt[diff <= 45.0]))
        head_t = float(np.sum(dt[diff >= 135.0]))
        cross_t = float(np.sum(dt[(diff > 45.0) & (diff < 135.0)]))
        if tail_t == 0.0 and head_t == 0.0 and cross_t == 0.0:
            return None

        _, label = max((tail_t, "попутный"), (head_t, "встречный"), (cross_t, "боковой"))
        return label

    def _max_attitude(self, log_data: LogData) -> tuple[float, float]:
        for msg_type, roll_f, pitch_f, yaw_f, is_radians in _ATTITUDE_CANDIDATES:
            table = log_data.messages.get(msg_type)
            if table and roll_f in table and pitch_f in table:
                roll, pitch = table[roll_f], table[pitch_f]
                if is_radians:
                    roll, pitch = np.degrees(roll), np.degrees(pitch)
                if len(roll) == 0:
                    return 0.0, 0.0
                return float(np.max(np.abs(roll))), float(np.max(np.abs(pitch)))
        return 0.0, 0.0

    def _photo_positions(self, msg_type: str, log_data: LogData) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        table = log_data.messages.get(msg_type)
        if not table:
            return None
        t = table["timestamp"]
        if "Lat" in table and "Lng" in table:
            return t, np.asarray(table["Lat"], dtype=float), np.asarray(table["Lng"], dtype=float)
        for gmsg, lat_f, lon_f in _GPS_LAT_CANDIDATES:
            gtable = log_data.messages.get(gmsg)
            if gtable and lat_f in gtable and lon_f in gtable:
                glat, glon = gtable[lat_f], gtable[lon_f]
                if gmsg == "GLOBAL_POSITION_INT":
                    glat, glon = glat / 1e7, glon / 1e7
                lat = np.interp(t, gtable["timestamp"], glat)
                lon = np.interp(t, gtable["timestamp"], glon)
                return t, lat, lon
        return None

    def _photo_stats(self, log_data: LogData) -> tuple[int, int, float | None, float | None]:
        """Return (CAM count, TRIG count, avg seconds between photos, avg meters
        between photos) - the time/distance averages prefer CAM positions, falling
        back to TRIG when CAM isn't present in the log.
        """
        cam_table = log_data.messages.get("CAM")
        trig_table = log_data.messages.get("TRIG")
        cam_count = len(cam_table["timestamp"]) if cam_table else 0
        trig_count = len(trig_table["timestamp"]) if trig_table else 0

        positions = self._photo_positions("CAM", log_data) or self._photo_positions("TRIG", log_data)
        if positions is None or len(positions[0]) < 2:
            return cam_count, trig_count, None, None
        t, lat, lon = positions
        avg_time = float(np.mean(np.diff(t)))
        avg_distance = _haversine_distance_m(lat, lon) / (len(t) - 1)
        return cam_count, trig_count, avg_time, avg_distance

    def _collect_stats(self) -> dict:
        """Snapshot of all currently displayed stats for the report dialog."""
        bw = self.battery_widget
        batteries = []
        for idx, (mah_lbl, max_lbl, avg_lbl) in enumerate(
            (
                (bw.bat1_mah_label, bw.bat1_max_curr_label, bw.bat1_avg_curr_label),
                (bw.bat2_mah_label, bw.bat2_max_curr_label, bw.bat2_avg_curr_label),
            ),
            start=1,
        ):
            if mah_lbl.text() != "—":
                batteries.append(
                    {"index": idx, "mah": mah_lbl.text(),
                     "max_curr": max_lbl.text(), "avg_curr": avg_lbl.text()}
                )
        return {
            "start_time": self.start_label.text(),
            "end_time": self.end_label.text(),
            "start_epoch": self._start_t,
            "end_epoch": self._end_t,
            "duration": self.duration_label.text(),
            "distance": self.distance_label.text(),
            "vertical_motor_time": self.vertical_motor_time_label.text(),
            "forward_motor_time": self.forward_motor_time_label.text(),
            "planning_time": self.planning_time_label.text(),
            "avg_wind": self.avg_wind_label.text(),
            "max_wind": self.max_wind_label.text(),
            "wind_dir": self.wind_dir_label.text(),
            "max_roll": self.max_roll_label.text(),
            "max_pitch": self.max_pitch_label.text(),
            "cam_count": self.cam_count_label.text(),
            "trig_count": self.trig_count_label.text(),
            "avg_photo_time": self.avg_photo_time_label.text(),
            "avg_photo_distance": self.avg_photo_distance_label.text(),
            "overall_mah_per_km": self.overall_mah_per_km_label.text(),
            "overall_mah_per_min": self.overall_mah_per_min_label.text(),
            "forward_mah_per_km": self.forward_mah_per_km_label.text(),
            "forward_mah_per_min": self.forward_mah_per_min_label.text(),
            "batteries": batteries,
        }

    def _open_report_dialog(self):
        from app.ui.report_dialog import ReportDialog
        dlg = ReportDialog(
            self._last_log_data,
            self._log_path or "",
            self._collect_stats(),
            self,
        )
        dlg.exec()
