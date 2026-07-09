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

_DEFAULT_TRIM = 1500.0
_MOTOR_PWM_MIN = 1100.0
_MOTOR_PWM_MAX = 2000.0
_MOTOR_KEYS = ["Motor3", "Motor1", "Motor2", "Motor4"]
_MOTOR_LABELS = {
    "Motor1": "Передний\nправый",
    "Motor2": "Задний\nлевый",
    "Motor3": "Передний\nлевый",
    "Motor4": "Задний\nправый",
}
_SURFACE_KEYS = ["Aileron", "Elevator", "Rudder"]
_SURFACE_LABELS = {
    "Aileron": "Элероны",
    "Elevator": "Руль\nвысоты",
    "Rudder": "Руль\nнаправления",
}


def _vline() -> QFrame:
    frame = QFrame()
    frame.setFrameShape(QFrame.VLine)
    frame.setFrameShadow(QFrame.Sunken)
    return frame


def _column_container(height: int, header_widgets, row_layout) -> QWidget:
    """Wrap a header (labels/separator) + row of gauges in a fixed-height widget
    so the row is anchored to the bottom, aligning gauge bottoms across columns."""
    container = QWidget()
    vbox = QVBoxLayout(container)
    vbox.setContentsMargins(0, 0, 0, 0)
    for widget in header_widgets:
        if isinstance(widget, QFrame):
            vbox.addWidget(widget)
        else:
            vbox.addWidget(widget, alignment=Qt.AlignHCenter)
    vbox.addStretch()
    vbox.addLayout(row_layout)
    container.setFixedHeight(height)
    return container


class MotorServoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(260)

        self.throttle_gauge = TapeGauge("", "%", bar_height=150)
        self.motor_gauges = {key: TapeGauge("", "%") for key in _MOTOR_KEYS}
        self.aileron_gauge = DeflectionGauge("")
        self.elevator_gauge = DeflectionGauge("")
        self.rudder_gauge = DeflectionGauge("")

        self._gauges = {"Throttle": self.throttle_gauge, **self.motor_gauges,
                         "Aileron": self.aileron_gauge, "Elevator": self.elevator_gauge,
                         "Rudder": self.rudder_gauge}

        _BOLD_STYLE = "font-weight: bold;"

        fwd_label = QLabel("Ходовой\nмотор")
        fwd_label.setAlignment(Qt.AlignHCenter)
        fwd_label.setStyleSheet(_BOLD_STYLE)

        fwd_gauge_row = QHBoxLayout()
        fwd_gauge_row.addStretch()
        fwd_gauge_row.addWidget(self.throttle_gauge)
        fwd_gauge_row.addStretch()

        fwd_container = _column_container(260, [fwd_label], fwd_gauge_row)

        motors_label = QLabel("Вертикальные моторы")
        motors_label.setAlignment(Qt.AlignCenter)
        motors_label.setStyleSheet(_BOLD_STYLE)
        motors_separator = QFrame()
        motors_separator.setFrameShape(QFrame.HLine)
        motors_separator.setFrameShadow(QFrame.Sunken)
        motors_row = QHBoxLayout()
        for key in _MOTOR_KEYS:
            motor_label = QLabel(_MOTOR_LABELS[key])
            motor_label.setAlignment(Qt.AlignHCenter)
            motor_col = QVBoxLayout()
            motor_col.addWidget(motor_label, alignment=Qt.AlignHCenter)
            motor_col.addWidget(self.motor_gauges[key], alignment=Qt.AlignHCenter)
            motors_row.addLayout(motor_col)
        motors_container = _column_container(260, [motors_label, motors_separator], motors_row)

        surfaces_label = QLabel("Управляющие поверхности")
        surfaces_label.setAlignment(Qt.AlignCenter)
        surfaces_label.setStyleSheet(_BOLD_STYLE)
        surfaces_separator = QFrame()
        surfaces_separator.setFrameShape(QFrame.HLine)
        surfaces_separator.setFrameShadow(QFrame.Sunken)
        surfaces_row = QHBoxLayout()
        surface_gauges = {"Aileron": self.aileron_gauge, "Elevator": self.elevator_gauge, "Rudder": self.rudder_gauge}
        for key in _SURFACE_KEYS:
            surface_label = QLabel(_SURFACE_LABELS[key])
            surface_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            surface_label.setFixedHeight(32)
            surface_col = QVBoxLayout()
            surface_col.addWidget(surface_label, alignment=Qt.AlignHCenter)
            surface_col.addWidget(surface_gauges[key], alignment=Qt.AlignHCenter)
            surfaces_row.addLayout(surface_col)
        surfaces_container = _column_container(260, [surfaces_label, surfaces_separator], surfaces_row)

        layout = QHBoxLayout(self)
        layout.addWidget(fwd_container, alignment=Qt.AlignTop)
        layout.addWidget(_vline())
        layout.addWidget(motors_container, alignment=Qt.AlignTop)
        layout.addWidget(_vline())
        layout.addWidget(surfaces_container, alignment=Qt.AlignTop)

        self._series: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._surface_trim: dict[str, float] = {}
        self._surface_range: dict[str, float] = {}

    def set_surface_calibration(self, key: str, trim: float, min_pwm: float, max_pwm: float) -> None:
        """Set neutral trim and observed min/max PWM for a control surface gauge."""
        self._surface_trim[key] = trim
        self._surface_range[key] = max(trim - min_pwm, max_pwm - trim, 1.0)

    def set_pwm_series(self, key: str, t: np.ndarray, pwm: np.ndarray):
        self._series[key] = (t, pwm)
        if len(t):
            self._update_gauge(key, float(pwm[0]))

    def clear_series(self, key: str):
        self._series.pop(key, None)
        self._update_gauge(key, self._surface_trim.get(key, _DEFAULT_TRIM))

    def _update_gauge(self, key: str, pwm_value: float):
        gauge = self._gauges.get(key)
        if gauge is None:
            return
        gauge.set_extra_text(f"{pwm_value:.0f}")
        if isinstance(gauge, DeflectionGauge):
            trim = self._surface_trim.get(key, _DEFAULT_TRIM)
            rng = self._surface_range.get(key, 500.0)
            gauge.set_value((pwm_value - trim) / rng)
        else:
            gauge.set_range(0.0, 100.0)
            pct = (pwm_value - _MOTOR_PWM_MIN) / (_MOTOR_PWM_MAX - _MOTOR_PWM_MIN) * 100.0
            gauge.set_value(max(0.0, min(100.0, pct)))

    def set_cursor_time(self, t: float):
        for key, (tarr, values) in self._series.items():
            if len(tarr) == 0:
                continue
            idx = int(np.searchsorted(tarr, t))
            idx = max(0, min(idx, len(tarr) - 1))
            self._update_gauge(key, float(values[idx]))
