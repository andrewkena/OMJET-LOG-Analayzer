"""Bottom panel showing forward/cruise motor load, the 4 VTOL lift motors,
and aileron/elevator/rudder deflection, synced to the playback cursor.

Output channels are resolved from RCOU using each log's SERVOx_FUNCTION
parameters, since the physical channel assigned to a given function varies
by airframe/parameter setup.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame

from app.ui.gauge_widget import TapeGauge, DeflectionGauge

_NEUTRAL_PWM = 1500.0
_MOTOR_KEYS = ["Motor1", "Motor2", "Motor3", "Motor4"]
_SURFACE_KEYS = ["Aileron", "Elevator", "Rudder"]


def _vline() -> QFrame:
    frame = QFrame()
    frame.setFrameShape(QFrame.VLine)
    frame.setFrameShadow(QFrame.Sunken)
    return frame


class MotorServoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(160)

        self.throttle_gauge = TapeGauge("Main Motor", "%")
        self.motor_gauges = {key: TapeGauge(f"M{i + 1}", "%") for i, key in enumerate(_MOTOR_KEYS)}
        self.aileron_gauge = DeflectionGauge("Aileron")
        self.elevator_gauge = DeflectionGauge("Elevator")
        self.rudder_gauge = DeflectionGauge("Rudder")

        self._gauges = {"Throttle": self.throttle_gauge, **self.motor_gauges,
                         "Aileron": self.aileron_gauge, "Elevator": self.elevator_gauge,
                         "Rudder": self.rudder_gauge}

        fwd_box = QVBoxLayout()
        fwd_box.addStretch()
        fwd_box.addWidget(self.throttle_gauge)
        fwd_box.addStretch()

        motors_box = QVBoxLayout()
        motors_box.addWidget(QLabel("Quad Motors"), alignment=Qt.AlignHCenter)
        motors_row = QHBoxLayout()
        for key in _MOTOR_KEYS:
            motors_row.addWidget(self.motor_gauges[key])
        motors_box.addLayout(motors_row)

        surfaces_box = QVBoxLayout()
        surfaces_box.addWidget(QLabel("Control Surfaces"), alignment=Qt.AlignHCenter)
        surfaces_row = QHBoxLayout()
        surfaces_row.addWidget(self.aileron_gauge)
        surfaces_row.addWidget(self.elevator_gauge)
        surfaces_row.addWidget(self.rudder_gauge)
        surfaces_box.addLayout(surfaces_row)

        layout = QHBoxLayout(self)
        layout.addLayout(fwd_box)
        layout.addWidget(_vline())
        layout.addLayout(motors_box)
        layout.addWidget(_vline())
        layout.addLayout(surfaces_box)
        layout.addStretch()

        self._series: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    def set_pwm_series(self, key: str, t: np.ndarray, pwm: np.ndarray):
        self._series[key] = (t, pwm)
        if len(t):
            self._update_gauge(key, float(pwm[0]))

    def clear_series(self, key: str):
        self._series.pop(key, None)
        self._update_gauge(key, _NEUTRAL_PWM)

    def _update_gauge(self, key: str, pwm_value: float):
        gauge = self._gauges.get(key)
        if gauge is None:
            return
        if isinstance(gauge, DeflectionGauge):
            gauge.set_value((pwm_value - _NEUTRAL_PWM) / 500.0)
        else:
            gauge.set_range(0.0, 100.0)
            gauge.set_value(max(0.0, min(100.0, (pwm_value - 1000.0) / 1000.0 * 100.0)))

    def set_cursor_time(self, t: float):
        for key, (tarr, values) in self._series.items():
            if len(tarr) == 0:
                continue
            idx = int(np.searchsorted(tarr, t))
            idx = max(0, min(idx, len(tarr) - 1))
            self._update_gauge(key, float(values[idx]))
