"""Mission Analysis tab - summary stats computed from the loaded log:
start/end/duration, distance flown, motor run times, max attitude,
photo count and per-battery mAh consumed.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel

from app.core.log_loader import LogData
from app.core.time_format import format_mmss, format_gps_time
from app.ui.battery_widget import BatteryWidget

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


class MissionAnalysisWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        time_group = QGroupBox("Время")
        time_layout = QFormLayout(time_group)
        self.start_label = QLabel("—")
        self.end_label = QLabel("—")
        self.duration_label = QLabel("—")
        time_layout.addRow("Время начала миссии:", self.start_label)
        time_layout.addRow("Время окончания:", self.end_label)
        time_layout.addRow("Продолжительность:", self.duration_label)
        layout.addWidget(time_group)

        flight_group = QGroupBox("Полет")
        flight_layout = QFormLayout(flight_group)
        self.distance_label = QLabel("—")
        self.vertical_motor_time_label = QLabel("—")
        self.forward_motor_time_label = QLabel("—")
        self.planning_time_label = QLabel("—")
        flight_layout.addRow("Пройденное расстояние:", self.distance_label)
        flight_layout.addRow("Время работы вертикальных моторов:", self.vertical_motor_time_label)
        flight_layout.addRow("Время работы ходового мотора:", self.forward_motor_time_label)
        flight_layout.addRow("Время планирования (без моторов):", self.planning_time_label)
        self.avg_wind_label = QLabel("—")
        self.max_wind_label = QLabel("—")
        flight_layout.addRow("Средний ветер:", self.avg_wind_label)
        flight_layout.addRow("Максимальный ветер:", self.max_wind_label)
        layout.addWidget(flight_group)

        attitude_group = QGroupBox("Углы")
        attitude_layout = QFormLayout(attitude_group)
        self.max_roll_label = QLabel("—")
        self.max_pitch_label = QLabel("—")
        attitude_layout.addRow("Максимальный крен:", self.max_roll_label)
        attitude_layout.addRow("Максимальный тангаж:", self.max_pitch_label)
        layout.addWidget(attitude_group)

        misc_group = QGroupBox("Прочее")
        misc_layout = QFormLayout(misc_group)
        self.photo_count_label = QLabel("—")
        misc_layout.addRow("Количество фотографий:", self.photo_count_label)
        layout.addWidget(misc_group)

        self.battery_widget = BatteryWidget()
        layout.addWidget(self.battery_widget)

        layout.addStretch()

    def load(self, log_data: LogData):
        start_t, end_t = self._mission_bounds(log_data)
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

        max_roll, max_pitch = self._max_attitude(log_data)
        self.max_roll_label.setText(f"{max_roll:.1f}°")
        self.max_pitch_label.setText(f"{max_pitch:.1f}°")

        self.photo_count_label.setText(str(self._photo_count(log_data)))

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

    def _distance_m(self, log_data: LogData) -> float:
        for msg_type, lat_f, lon_f in _GPS_LAT_CANDIDATES:
            table = log_data.messages.get(msg_type)
            if table and lat_f in table and lon_f in table:
                lat = table[lat_f]
                lon = table[lon_f]
                if msg_type == "GLOBAL_POSITION_INT":
                    lat = lat / 1e7
                    lon = lon / 1e7
                return _haversine_distance_m(lat, lon)
        return 0.0

    def _motor_times(self, log_data: LogData) -> tuple[float, float]:
        rcou_table = log_data.messages.get("RCOU")
        if not rcou_table:
            return 0.0, 0.0
        param_map = {p["name"]: p["value"] for p in log_data.parameters()}

        channel_for_function: dict[str, int] = {}
        for ch in range(1, 15):
            func_val = param_map.get(f"SERVO{ch}_FUNCTION")
            if func_val is None:
                continue
            for label, fid in _SERVO_FUNCTION_IDS.items():
                if label not in channel_for_function and int(func_val) == fid:
                    channel_for_function[label] = ch

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

    def _wind_stats(self, log_data: LogData) -> tuple[float | None, float | None]:
        for msg_type, north_f, east_f in _WIND_CANDIDATES:
            table = log_data.messages.get(msg_type)
            if table and north_f in table and east_f in table:
                speed = np.hypot(table[north_f], table[east_f])
                if len(speed) == 0:
                    return None, None
                return float(np.mean(speed)), float(np.max(speed))
        return None, None

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

    def _photo_count(self, log_data: LogData) -> int:
        cam_table = log_data.messages.get("CAM")
        return len(cam_table["timestamp"]) if cam_table else 0
