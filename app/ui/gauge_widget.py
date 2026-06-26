"""Simple vertical tape gauge (used for speed and altitude readouts)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QColor, QLinearGradient
from PySide6.QtWidgets import QWidget


class TapeGauge(QWidget):
    """Vertical tape gauge for speed, altitude, and current displays."""

    _GREEN = (60, 180, 75)
    _YELLOW = (241, 196, 15)
    _RED = (230, 25, 75)

    def __init__(self, title: str, unit: str, current_warning: bool = False, bold_title: bool = False,
                 extra_label: str | None = "PWM", unit_inline: bool = False, parent=None):
        super().__init__(parent)
        self.title = title
        self.unit = unit
        self._bold_title = bold_title
        self._extra_label = extra_label
        self._unit_inline = unit_inline
        self._title_offset = 14 * title.count("\n")
        self.setFixedSize(70, 170 + self._title_offset)
        self._value = 0.0
        self._min = 0.0
        self._max = 1.0
        self._color_mode = "current" if current_warning else None
        self._green_threshold = 50.0
        self._red_threshold = 100.0
        self._speed_min = 16.0
        self._speed_target = 20.0
        self._speed_max = 24.0
        self._extra_text = ""

    def set_range(self, vmin: float, vmax: float):
        self._min = vmin
        self._max = max(vmax, vmin + 0.1)
        self.update()

    def set_value(self, value: float):
        self._value = value
        self.update()

    def set_extra_text(self, text: str):
        """Set extra text (e.g. raw PWM) shown in parentheses below the value."""
        self._extra_text = text
        self.update()

    def set_current_thresholds(self, green: float, red: float):
        """Set the value at which the fill is fully green, and fully red."""
        self._green_threshold = green
        self._red_threshold = max(red, green + 0.1)
        self.update()

    def set_speed_thresholds(self, min_v: float, target_v: float, max_v: float):
        """Set red(min) -> green(target) -> red(max) speed coloring thresholds."""
        self._color_mode = "speed"
        self._speed_min = min_v
        self._speed_target = max(target_v, min_v + 0.1)
        self._speed_max = max(max_v, self._speed_target + 0.1)
        self.update()

    @staticmethod
    def _lerp_color(c0, c1, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        rgb = tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
        return QColor(*rgb)

    def _fill_color(self) -> QColor:
        if self._color_mode == "current":
            green_v, red_v = self._green_threshold, self._red_threshold
            if self._value <= green_v:
                return QColor("#3cb44b")  # Green
            if self._value >= red_v:
                return QColor("#e6194b")  # Red
            ratio = (self._value - green_v) / (red_v - green_v)
            if ratio < 0.5:
                return self._lerp_color(self._GREEN, self._YELLOW, ratio * 2)
            return self._lerp_color(self._YELLOW, self._RED, (ratio - 0.5) * 2)

        if self._color_mode == "speed":
            min_v, target_v, max_v = self._speed_min, self._speed_target, self._speed_max
            if self._value <= min_v:
                return QColor("#e6194b")  # Red
            if self._value <= target_v:
                return self._lerp_color(self._RED, self._GREEN, (self._value - min_v) / (target_v - min_v))
            if self._value <= max_v:
                return self._lerp_color(self._GREEN, self._RED, (self._value - target_v) / (max_v - target_v))
            return QColor("#e6194b")  # Red

        return QColor("#3cb44b")  # Green - normal

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        title_rect_height = 14 + self._title_offset
        painter.setPen(QColor("white"))
        if self._bold_title:
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRectF(0, 0, rect.width(), title_rect_height), Qt.AlignCenter, self.title)
            font.setBold(False)
            painter.setFont(font)
        else:
            painter.drawText(QRectF(0, 0, rect.width(), title_rect_height), Qt.AlignCenter, self.title)

        bar_rect = QRectF(rect.width() / 2 - 10, 15 + self._title_offset, 20, 100)
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
        painter.setBrush(self._fill_color())
        painter.drawRect(fill_rect)

        painter.setPen(QColor("white"))
        value_y = 120 + self._title_offset
        if self.unit == "%":
            painter.drawText(QRectF(0, value_y, rect.width(), 16), Qt.AlignCenter, f"{self._value:.1f}{self.unit}")
        elif self._unit_inline:
            painter.drawText(QRectF(0, value_y, rect.width(), 16), Qt.AlignCenter, f"{self._value:.1f} {self.unit}")
        else:
            painter.drawText(QRectF(0, value_y, rect.width(), 16), Qt.AlignCenter, f"{self._value:.1f}")
            painter.drawText(QRectF(0, value_y + 16, rect.width(), 14), Qt.AlignCenter, self.unit)
        if self._extra_text:
            extra = f"{self._extra_label}: {self._extra_text}" if self._extra_label else f"({self._extra_text})"
            extra_y = value_y + 16 if (self.unit == "%" or self._unit_inline) else value_y + 30
            painter.drawText(QRectF(0, extra_y, rect.width(), 16), Qt.AlignCenter, extra)


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
        self._is_hv = False  # LiHV mode

    def set_hv_mode(self, is_hv: bool):
        """Enable/disable LiHV high voltage mode."""
        self._is_hv = is_hv
        self.update()

    @property
    def _full_voltage(self) -> float:
        """Return full charge voltage per cell."""
        return 4.35 if self._is_hv else 4.2

    @property
    def _empty_voltage(self) -> float:
        """Return empty voltage per cell (same for both types)."""
        return 3.6

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
        full_v = self._full_voltage
        empty_v = self._empty_voltage

        # Color gradient: red (empty) -> yellow (mid) -> green (full)
        if voltage_per_cell >= full_v:
            return QColor("#3cb44b")  # Green - full
        elif voltage_per_cell <= empty_v:
            return QColor("#e6194b")  # Red - empty
        else:
            # Interpolate between red and green through yellow
            ratio = (voltage_per_cell - empty_v) / (full_v - empty_v)
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
        self.setFixedSize(60, 170)
        self.title = title
        self._value = 0.0
        self._extra_text = ""

    def set_value(self, value: float):
        self._value = max(-1.0, min(1.0, value))
        self.update()

    def set_extra_text(self, text: str):
        """Set extra text (e.g. raw PWM) shown in parentheses below the value."""
        self._extra_text = text
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        painter.setPen(QColor("white"))
        if self.title:
            painter.drawText(QRectF(0, 0, rect.width(), 14), Qt.AlignCenter, self.title)

        bar_rect = QRectF(rect.width() / 2 - 10, 15, 20, 100)
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
        painter.drawText(QRectF(0, 120, rect.width(), 16), Qt.AlignCenter, f"{self._value * 100:.0f}%")
        if self._extra_text:
            painter.drawText(QRectF(0, 136, rect.width(), 16), Qt.AlignCenter, f"PWM: {self._extra_text}")
