"""Simple vertical tape gauge (used for speed and altitude readouts)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import QWidget


class TapeGauge(QWidget):
    def __init__(self, title: str, unit: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(70, 120)
        self.title = title
        self.unit = unit
        self._value = 0.0
        self._min = 0.0
        self._max = 1.0

    def set_range(self, vmin: float, vmax: float):
        self._min = vmin
        self._max = max(vmax, vmin + 0.1)
        self.update()

    def set_value(self, value: float):
        self._value = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        painter.setPen(QColor("white"))
        painter.drawText(QRectF(0, 0, rect.width(), 14), Qt.AlignCenter, self.title)

        bar_rect = QRectF(rect.width() / 2 - 10, 15, 20, 50)
        painter.setPen(QPen(QColor("#888888"), 1))
        painter.setBrush(QColor(25, 25, 25))
        painter.drawRect(bar_rect)

        frac = 0.0
        if self._max > self._min:
            frac = (self._value - self._min) / (self._max - self._min)
        frac = max(0.0, min(1.0, frac))
        fill_height = bar_rect.height() * frac
        fill_rect = QRectF(bar_rect.left(), bar_rect.bottom() - fill_height, bar_rect.width(), fill_height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#3cb44b"))
        painter.drawRect(fill_rect)

        painter.setPen(QColor("white"))
        painter.drawText(QRectF(0, 70, rect.width(), 16), Qt.AlignCenter, f"{self._value:.1f}")
        painter.drawText(QRectF(0, 86, rect.width(), 14), Qt.AlignCenter, self.unit)


class DeflectionGauge(QWidget):
    """Vertical scale with a marker showing deflection from center (-1..1), e.g. for control surfaces."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 120)
        self.title = title
        self._value = 0.0

    def set_value(self, value: float):
        self._value = max(-1.0, min(1.0, value))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        painter.setPen(QColor("white"))
        painter.drawText(QRectF(0, 0, rect.width(), 14), Qt.AlignCenter, self.title)

        bar_rect = QRectF(rect.width() / 2 - 10, 16, 20, 64)
        painter.setPen(QPen(QColor("#888888"), 1))
        painter.setBrush(QColor(25, 25, 25))
        painter.drawRect(bar_rect)

        mid_y = bar_rect.center().y()
        painter.setPen(QPen(QColor("#555555"), 1, Qt.DashLine))
        painter.drawLine(QPointF(bar_rect.left(), mid_y), QPointF(bar_rect.right(), mid_y))

        marker_y = mid_y - self._value * (bar_rect.height() / 2 - 4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#3cb44b"))
        painter.drawRect(QRectF(bar_rect.left() - 2, marker_y - 3, bar_rect.width() + 4, 6))

        painter.setPen(QColor("white"))
        painter.drawText(QRectF(0, 86, rect.width(), 16), Qt.AlignCenter, f"{self._value * 100:.0f}%")
