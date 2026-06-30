"""Application settings tab - battery configuration and other app preferences."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QComboBox, QCheckBox,
    QSpinBox, QFormLayout, QListWidget, QListWidgetItem, QPushButton, QMessageBox
)
from PySide6.QtCore import Signal

from app.core import tile_cache


class SettingsWidget(QWidget):
    """Application settings - battery configuration and preferences."""

    # Signals for settings changes
    battery_cell_count_changed = Signal(int)
    battery_hv_changed = Signal(bool)
    current_thresholds_changed = Signal(float, float)  # green, red
    speed_thresholds_changed = Signal(float, float, float)  # min, target, max
    max_wind_changed = Signal(float)  # max wind speed, m/s
    efficiency_thresholds_changed = Signal(float, float, float)  # green, yellow, red (mAh)
    theme_changed = Signal(str)  # "light", "dark", or "system"
    timezone_changed = Signal(float)  # UTC offset in hours
    language_changed = Signal(str)  # "ru" or "en"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._utc_offset = 0.0
        self._language = "ru"
        self._battery_cells = 8
        self._battery_hv = False
        self._current_green = 50
        self._current_red = 100
        self._speed_min = 16
        self._speed_target = 20
        self._speed_max = 24
        self._max_wind = 12
        self._eff_green = 200
        self._eff_yellow = 300
        self._eff_red = 400

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

        self.timezone_combo = QComboBox()
        for offset in range(-12, 15):
            label = "UTC" if offset == 0 else f"UTC{offset:+d}"
            self.timezone_combo.addItem(label, float(offset))
        self.timezone_combo.setCurrentIndex(self.timezone_combo.findData(0.0))
        self.timezone_combo.currentIndexChanged.connect(self._on_timezone_changed)
        theme_layout.addRow("Часовой пояс:", self.timezone_combo)

        self.language_combo = QComboBox()
        self.language_combo.addItem("Русский", "ru")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(self.language_combo.findData("ru"))
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        theme_layout.addRow("Язык:", self.language_combo)

        layout.addWidget(theme_group)

        # Notifications
        notifications_group = QGroupBox("Уведомления")
        notifications_layout = QVBoxLayout(notifications_group)
        self.sound_alerts_checkbox = QCheckBox("Звуковые оповещения")
        self.sound_alerts_checkbox.setChecked(True)
        notifications_layout.addWidget(self.sound_alerts_checkbox)
        layout.addWidget(notifications_group)

        # Map tile cache
        cache_group = QGroupBox("Кэш картографических данных")
        cache_layout = QVBoxLayout(cache_group)
        self.cache_size_label = QLabel()
        self._update_cache_size_label()
        cache_layout.addWidget(self.cache_size_label)
        self.clear_cache_button = QPushButton("Очистить кэш картографических данных")
        self.clear_cache_button.clicked.connect(self._on_clear_cache_clicked)
        cache_layout.addWidget(self.clear_cache_button)
        layout.addWidget(cache_group)

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

        self.max_wind_spin = QSpinBox()
        self.max_wind_spin.setRange(0, 100)
        self.max_wind_spin.setSuffix(" м/с")
        self.max_wind_spin.setValue(self._max_wind)
        self.max_wind_spin.valueChanged.connect(self._on_max_wind_changed)
        color_layout.addRow("Максимальный ветер:", self.max_wind_spin)

        layout.addWidget(color_group)

        # Efficiency thresholds (mAh consumption coloring in Mission Analysis)
        efficiency_group = QGroupBox("Пороги эффективности")
        efficiency_layout = QFormLayout(efficiency_group)

        eff_row = QHBoxLayout()
        eff_row.addWidget(self._make_dot("#3cb44b"))
        self.eff_green_spin = QSpinBox()
        self.eff_green_spin.setRange(0, 5000)
        self.eff_green_spin.setSuffix(" мА·ч")
        self.eff_green_spin.setValue(self._eff_green)
        self.eff_green_spin.valueChanged.connect(self._on_efficiency_thresholds_changed)
        eff_row.addWidget(self.eff_green_spin)

        eff_row.addWidget(self._make_dot("#f1c40f"))
        self.eff_yellow_spin = QSpinBox()
        self.eff_yellow_spin.setRange(0, 5000)
        self.eff_yellow_spin.setSuffix(" мА·ч")
        self.eff_yellow_spin.setValue(self._eff_yellow)
        self.eff_yellow_spin.valueChanged.connect(self._on_efficiency_thresholds_changed)
        eff_row.addWidget(self.eff_yellow_spin)

        eff_row.addWidget(self._make_dot("#e6194b"))
        self.eff_red_spin = QSpinBox()
        self.eff_red_spin.setRange(0, 5000)
        self.eff_red_spin.setSuffix(" мА·ч")
        self.eff_red_spin.setValue(self._eff_red)
        self.eff_red_spin.valueChanged.connect(self._on_efficiency_thresholds_changed)
        eff_row.addWidget(self.eff_red_spin)

        efficiency_layout.addRow("Расход (мА·ч):", eff_row)
        layout.addWidget(efficiency_group)

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

    @staticmethod
    def _make_dot(color: str) -> QLabel:
        """Create a small colored circle label (used to mark threshold inputs)."""
        dot = QLabel()
        dot.setFixedSize(12, 12)
        dot.setStyleSheet(f"background-color: {color}; border-radius: 6px;")
        return dot

    def _on_theme_changed(self, index: int):
        """Handle theme selection change."""
        self.theme_changed.emit(self.theme_combo.itemData(index))

    def current_theme(self) -> str:
        """Return the currently selected theme ('light', 'dark', or 'system')."""
        return self.theme_combo.currentData()

    def _on_timezone_changed(self, index: int):
        """Handle timezone selection change."""
        self._utc_offset = self.timezone_combo.itemData(index)
        self.timezone_changed.emit(self._utc_offset)

    def get_utc_offset(self) -> float:
        """Return the currently selected UTC offset in hours."""
        return self._utc_offset

    def _on_language_changed(self, index: int):
        """Handle language selection change."""
        self._language = self.language_combo.itemData(index)
        self.language_changed.emit(self._language)

    def get_language(self) -> str:
        """Return the currently selected language code ('ru' or 'en')."""
        return self._language

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

    def _on_efficiency_thresholds_changed(self):
        """Handle efficiency (mAh consumption) threshold change, keeping green <= yellow <= red."""
        green_v = self.eff_green_spin.value()
        yellow_v = self.eff_yellow_spin.value()
        red_v = self.eff_red_spin.value()
        if yellow_v < green_v:
            self.eff_yellow_spin.setValue(green_v)
            return  # setValue triggers this slot again with the corrected value
        if red_v < yellow_v:
            self.eff_red_spin.setValue(yellow_v)
            return
        self._eff_green, self._eff_yellow, self._eff_red = green_v, yellow_v, red_v
        self.efficiency_thresholds_changed.emit(float(green_v), float(yellow_v), float(red_v))

    def get_efficiency_thresholds(self) -> tuple[float, float, float]:
        """Return the (green, yellow, red) efficiency (mAh consumption) thresholds."""
        return float(self._eff_green), float(self._eff_yellow), float(self._eff_red)

    def _on_max_wind_changed(self, value: int):
        """Handle max wind threshold change."""
        self._max_wind = value
        self.max_wind_changed.emit(float(self._max_wind))

    def get_max_wind(self) -> float:
        """Return the max wind speed threshold (m/s) for map highlighting."""
        return float(self._max_wind)

    def is_sound_alerts_enabled(self) -> bool:
        """Return whether sound alerts (e.g. on log load finished) are enabled."""
        return self.sound_alerts_checkbox.isChecked()

    def _update_cache_size_label(self):
        """Refresh the displayed map tile cache size."""
        size = tile_cache.get_cache_size_bytes()
        self.cache_size_label.setText(f"Объём картографических данных: {tile_cache.format_size(size)}")

    def _on_clear_cache_clicked(self):
        """Handle the 'clear map cache' button click."""
        tile_cache.clear_cache()
        self._update_cache_size_label()
        QMessageBox.information(self, "Кэш карты", "Кэш картографических данных очищен.")

    def showEvent(self, event):
        """Refresh the cache size display every time the Settings tab is shown."""
        super().showEvent(event)
        self._update_cache_size_label()
