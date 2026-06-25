"""Application settings tab - battery configuration and other app preferences."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QComboBox, QCheckBox,
    QSpinBox, QFormLayout, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Signal


class SettingsWidget(QWidget):
    """Application settings - battery configuration and preferences."""

    # Signals for settings changes
    battery_cell_count_changed = Signal(int)
    battery_hv_changed = Signal(bool)
    current_thresholds_changed = Signal(float, float)  # green, red
    speed_thresholds_changed = Signal(float, float, float)  # min, target, max
    theme_changed = Signal(str)  # "light", "dark", or "system"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._battery_cells = 8
        self._battery_hv = False
        self._current_green = 50
        self._current_red = 100
        self._speed_min = 16
        self._speed_target = 20
        self._speed_max = 24

        layout = QVBoxLayout(self)

        # Theme selection
        theme_group = QGroupBox("Тема приложения")
        theme_layout = QFormLayout(theme_group)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Светлая", "light")
        self.theme_combo.addItem("Темная", "dark")
        self.theme_combo.addItem("Системная", "system")
        self.theme_combo.setCurrentIndex(2)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_layout.addRow("Тема:", self.theme_combo)
        layout.addWidget(theme_group)

        # Battery Configuration
        battery_group = QGroupBox("Battery Configuration")
        battery_layout = QFormLayout(battery_group)

        # Cell count selector
        self.cell_count_combo = QComboBox()
        self.cell_count_combo.addItems(["4S", "6S", "8S", "10S", "12S"])
        self.cell_count_combo.setCurrentText("8S")
        self.cell_count_combo.currentTextChanged.connect(self._on_cell_count_changed)
        battery_layout.addRow("Cell Count:", self.cell_count_combo)

        # HV checkbox for LiHV batteries
        self.hv_checkbox = QCheckBox("LiHV (High Voltage)")
        self.hv_checkbox.setToolTip(
            "Enable for LiHV batteries\n"
            "Standard LiPo: 4.20V/cell (full) / 3.60V/cell (empty)\n"
            "LiHV: 4.35V/cell (full) / 3.60V/cell (empty)"
        )
        self.hv_checkbox.stateChanged.connect(self._on_hv_changed)
        battery_layout.addRow("Battery Type:", self.hv_checkbox)

        # Voltage thresholds info
        self.threshold_label = QLabel()
        self._update_threshold_label()
        battery_layout.addRow("Voltage Range:", self.threshold_label)

        layout.addWidget(battery_group)

        # Color configuration
        color_group = QGroupBox("Цветовая настройка")
        color_layout = QFormLayout(color_group)

        current_row = QHBoxLayout()
        self.current_green_spin = QSpinBox()
        self.current_green_spin.setRange(0, 1000)
        self.current_green_spin.setSuffix(" A")
        self.current_green_spin.setValue(self._current_green)
        self.current_green_spin.valueChanged.connect(self._on_current_thresholds_changed)
        self.current_red_spin = QSpinBox()
        self.current_red_spin.setRange(0, 1000)
        self.current_red_spin.setSuffix(" A")
        self.current_red_spin.setValue(self._current_red)
        self.current_red_spin.valueChanged.connect(self._on_current_thresholds_changed)

        current_row.addWidget(QLabel("Зеленый:"))
        current_row.addWidget(self.current_green_spin)
        current_row.addWidget(QLabel("Красный:"))
        current_row.addWidget(self.current_red_spin)
        color_layout.addRow("Сила тока:", current_row)

        speed_row = QHBoxLayout()
        self.speed_min_spin = QSpinBox()
        self.speed_min_spin.setRange(0, 200)
        self.speed_min_spin.setSuffix(" m/s")
        self.speed_min_spin.setValue(self._speed_min)
        self.speed_min_spin.valueChanged.connect(self._on_speed_thresholds_changed)
        self.speed_target_spin = QSpinBox()
        self.speed_target_spin.setRange(0, 200)
        self.speed_target_spin.setSuffix(" m/s")
        self.speed_target_spin.setValue(self._speed_target)
        self.speed_target_spin.valueChanged.connect(self._on_speed_thresholds_changed)
        self.speed_max_spin = QSpinBox()
        self.speed_max_spin.setRange(0, 200)
        self.speed_max_spin.setSuffix(" m/s")
        self.speed_max_spin.setValue(self._speed_max)
        self.speed_max_spin.valueChanged.connect(self._on_speed_thresholds_changed)

        speed_row.addWidget(QLabel("Минимальная:"))
        speed_row.addWidget(self.speed_min_spin)
        speed_row.addWidget(QLabel("Целевая:"))
        speed_row.addWidget(self.speed_target_spin)
        speed_row.addWidget(QLabel("Максимальная:"))
        speed_row.addWidget(self.speed_max_spin)
        color_layout.addRow("Скорость:", speed_row)

        layout.addWidget(color_group)

        # Info section
        info_group = QGroupBox("Battery Voltage Info")
        info_layout = QVBoxLayout(info_group)

        info_layout.addWidget(QLabel("LiPo / Li-ion:"))
        info_layout.addWidget(QLabel("  • Full charge: 4.20V per cell"))
        info_layout.addWidget(QLabel("  • Safe minimum: 3.60V per cell"))
        info_layout.addWidget(QLabel(""))
        info_layout.addWidget(QLabel("LiHV (High Voltage):"))
        info_layout.addWidget(QLabel("  • Full charge: 4.35V per cell"))
        info_layout.addWidget(QLabel("  • Safe minimum: 3.60V per cell"))

        layout.addWidget(info_group)
        layout.addStretch()

    def _on_theme_changed(self, index: int):
        """Handle theme selection change."""
        self.theme_changed.emit(self.theme_combo.itemData(index))

    def current_theme(self) -> str:
        """Return the currently selected theme ('light', 'dark', or 'system')."""
        return self.theme_combo.currentData()

    def _on_cell_count_changed(self, text: str):
        """Handle battery cell count change."""
        self._battery_cells = int(text.replace("S", ""))
        self.battery_cell_count_changed.emit(self._battery_cells)

    def _on_hv_changed(self, state: int):
        """Handle HV checkbox change."""
        self._battery_hv = (state == 2)  # Qt.Checked = 2
        self.battery_hv_changed.emit(self._battery_hv)
        self._update_threshold_label()

    def _update_threshold_label(self):
        """Update the voltage threshold display."""
        if self._battery_hv:
            self.threshold_label.setText(
                f"<span style='color: #3cb44b;'>4.35V</span> / "
                f"<span style='color: #e6194b;'>3.60V</span> per cell"
            )
        else:
            self.threshold_label.setText(
                f"<span style='color: #3cb44b;'>4.20V</span> / "
                f"<span style='color: #e6194b;'>3.60V</span> per cell"
            )

    def _on_current_thresholds_changed(self):
        """Handle current color threshold change, keeping red >= green."""
        self._current_green = self.current_green_spin.value()
        self._current_red = self.current_red_spin.value()
        if self.current_red_spin.value() < self.current_green_spin.value():
            self.current_red_spin.setValue(self.current_green_spin.value())
            return  # setValue triggers this slot again with the corrected value
        self.current_thresholds_changed.emit(float(self._current_green), float(self._current_red))

    def _on_speed_thresholds_changed(self):
        """Handle speed color threshold change, keeping min <= target <= max."""
        min_v = self.speed_min_spin.value()
        target_v = self.speed_target_spin.value()
        max_v = self.speed_max_spin.value()
        if target_v < min_v:
            self.speed_target_spin.setValue(min_v)
            return  # setValue triggers this slot again with the corrected value
        if max_v < target_v:
            self.speed_max_spin.setValue(target_v)
            return
        self._speed_min, self._speed_target, self._speed_max = min_v, target_v, max_v
        self.speed_thresholds_changed.emit(float(min_v), float(target_v), float(max_v))

    def get_battery_cell_count(self) -> int:
        """Return the currently selected battery cell count."""
        return self._battery_cells

    def is_hv_battery(self) -> bool:
        """Return whether LiHV mode is enabled."""
        return self._battery_hv

    def get_current_thresholds(self) -> tuple[float, float]:
        """Return the (green, red) current coloring thresholds."""
        return float(self._current_green), float(self._current_red)

    def get_speed_thresholds(self) -> tuple[float, float, float]:
        """Return the (min, target, max) speed coloring thresholds."""
        return float(self._speed_min), float(self._speed_target), float(self._speed_max)
