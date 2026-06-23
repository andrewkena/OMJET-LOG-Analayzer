"""Simple vertical tape gauge (used for speed and altitude readouts)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QColor, QLinearGradient
from PySide6.QtWidgets import QWidget


class TapeGauge(QWidget):
    """Vertical tape gauge for speed, altitude, and current displays."""

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


class BatteryGauge(QWidget):
    """Vertical battery gauge with color gradient based on voltage per cell."""

    def __init__(self, title: str, unit: str, cell_count: int = 4, parent=None):
        super().__init__(parent)
        self.setFixedSize(70, 120)
        self.title = title
        self.unit = unit
        self._value = 0.0
        self._min = 0.0
        self._max = 1.0
        self._cell_count = cell_count
        # Thresholds per cell (in volts)
        self._full_voltage = 4.2  # 100% - green
        self._empty_voltage = 3.6  # 0% - red

    def set_cell_count(self, cell_count: int):
        """Update the number of cells for voltage calculation."""
        self._cell_count = cell_count
        self.update()

    def set_range(self, vmin: float, vmax: float):
        self._min = vmin
        self._max = max(vmax, vmin + 0.1)
        self.update()

    def set_value(self, value: float):
        self._value = value
        self.update()

    def _get_fill_color(self, fraction: float) -> QColor:
        """Get color based on voltage per cell (0=empty/red, 1=full/green)."""
        voltage_per_cell = self._value / max(1, self._cell_count)

        # Color gradient: red (empty) -> yellow (mid) -> green (full)
        if voltage_per_cell >= self._full_voltage:
            return QColor("#3cb44b")  # Green - full
        elif voltage_per_cell <= self._empty_voltage:
            return QColor("#e6194b")  # Red - empty
        else:
            # Interpolate between red and green through yellow
            ratio = (voltage_per_cell - self._empty_voltage) / (self._full_voltage - self._empty_voltage)
            if ratio < 0.5:
                # Red to yellow
                r = 230
                g = int(25 + (220 - 25) * (ratio * 2))
                b = int(75 * (1 - ratio * 2))
            else:
                # Yellow to green
                r = int(230 - 230 * ((ratio - 0.5) * 2))
                g = int(220 - (220 - 100) * ((ratio - 0.5) * 2))
                b = int(75 * (1 - (ratio - 0.5) * 2))
            return QColor(r, g, b)

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

        # Use gradient fill based on battery level
        fill_color = self._get_fill_color(frac)
        gradient = QLinearGradient(fill_rect.topLeft(), fill_rect.bottomLeft())
        gradient.setColorAt(0, fill_color.darker(120))
        gradient.setColorAt(1, fill_color)

        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawRect(fill_rect)

        # Draw voltage per cell indicator
        voltage_per_cell = self._value / max(1, self._cell_count)

        painter.setPen(QColor("white"))
        painter.drawText(QRectF(0, 70, rect.width(), 16), Qt.AlignCenter, f"{self._value:.1f}")
        painter.drawText(QRectF(0, 86, rect.width(), 14), Qt.AlignCenter, f"{voltage_per_cell:.1f}V/c")


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
