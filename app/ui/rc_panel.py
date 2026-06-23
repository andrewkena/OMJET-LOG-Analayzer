"""Bottom panel showing symbolic RC transmitter joysticks for RC1-RC4,
synced to the playback cursor (Mode-2 layout: left stick = throttle/yaw,
right stick = roll/pitch)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel

_CENTER_PWM = 1500.0
_RANGE_PWM = 500.0


def _normalize(pwm: float) -> float:
    return max(-1.0, min(1.0, (pwm - _CENTER_PWM) / _RANGE_PWM))


class JoystickWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(100, 100)
        self._x = 0.0
        self._y = 0.0

    def set_position(self, x: float, y: float):
        self._x = max(-1.0, min(1.0, x))
        self._y = max(-1.0, min(1.0, y))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(6, 6, -6, -6)
        side = min(rect.width(), rect.height())
        cx0, cy0 = rect.center().x(), rect.center().y()
        square = QRectF(cx0 - side / 2, cy0 - side / 2, side, side)

        painter.setPen(QPen(QColor("#888888"), 1))
        painter.setBrush(QColor(25, 25, 25))
        painter.drawRect(square)

        painter.setPen(QPen(QColor("#555555"), 1, Qt.DashLine))
        painter.drawLine(QPointF(square.left(), cy0), QPointF(square.right(), cy0))
        painter.drawLine(QPointF(cx0, square.top()), QPointF(cx0, square.bottom()))

        radius = side / 2 - 8
        dot_x = cx0 + self._x * radius
        dot_y = cy0 - self._y * radius
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#e6194b"))
        painter.drawEllipse(QPointF(dot_x, dot_y), 7, 7)


class RCPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(150)

        self.left_stick = JoystickWidget()
        self.right_stick = JoystickWidget()

        left_box = QVBoxLayout()
        left_box.addWidget(QLabel("Throttle / Yaw (RC3 / RC4)"), alignment=Qt.AlignHCenter)
        left_box.addWidget(self.left_stick)

        right_box = QVBoxLayout()
        right_box.addWidget(QLabel("Roll / Pitch (RC1 / RC2)"), alignment=Qt.AlignHCenter)
        right_box.addWidget(self.right_stick)

        self.value_labels = {ch: QLabel(f"RC{ch}: --") for ch in (1, 2, 3, 4)}
        values_box = QVBoxLayout()
        for ch in (1, 2, 3, 4):
            values_box.addWidget(self.value_labels[ch])
        values_box.addStretch()

        layout = QHBoxLayout(self)
        layout.addLayout(left_box)
        layout.addLayout(right_box)
        layout.addLayout(values_box)
        layout.addStretch()

        self._t = np.array([])
        self._c1 = np.array([])
        self._c2 = np.array([])
        self._c3 = np.array([])
        self._c4 = np.array([])

    def set_data(self, t: np.ndarray, c1: np.ndarray, c2: np.ndarray, c3: np.ndarray, c4: np.ndarray):
        self._t, self._c1, self._c2, self._c3, self._c4 = t, c1, c2, c3, c4
        if len(t):
            self.set_cursor_time(t[0])

    def clear_data(self):
        self._t = np.array([])
        self.left_stick.set_position(0.0, 0.0)
        self.right_stick.set_position(0.0, 0.0)
        for label in self.value_labels.values():
            label.setText(label.text().split(":")[0] + ": --")

    def set_cursor_time(self, t: float):
        if len(self._t) == 0:
            return
        idx = int(np.searchsorted(self._t, t))
        idx = max(0, min(idx, len(self._t) - 1))
        c1, c2, c3, c4 = self._c1[idx], self._c2[idx], self._c3[idx], self._c4[idx]

        self.right_stick.set_position(_normalize(c1), _normalize(c2))
        self.left_stick.set_position(_normalize(c4), _normalize(c3))

        for ch, v in zip((1, 2, 3, 4), (c1, c2, c3, c4)):
            self.value_labels[ch].setText(f"RC{ch}: {int(v)}")
