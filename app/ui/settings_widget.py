"""Application settings tab - battery configuration and other app preferences."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QComboBox, QCheckBox,
    QSpinBox, QFormLayout, QListWidget, QListWidgetItem, QPushButton, QMessageBox
)
from PySide6.QtCore import Signal

from app.core import tile_cache, i18n

_CACHE_SIZE_OPTIONS = [
    ("250 МБ", 250 * 1024 * 1024),
    ("500 МБ", 500 * 1024 * 1024),
    ("750 МБ", 750 * 1024 * 1024),
    ("1 ГБ", 1024 * 1024 * 1024),
    ("1.5 ГБ", int(1.5 * 1024 ** 3)),
    ("2 ГБ", 2 * 1024 ** 3),
    ("3 ГБ", 3 * 1024 ** 3),
    ("4 ГБ", 4 * 1024 ** 3),
    ("5 ГБ", 5 * 1024 ** 3),
]


class SettingsWidget(QWidget):
    battery_cell_count_changed = Signal(int)
    battery_hv_changed = Signal(bool)
    current_thresholds_changed = Signal(float, float)
    speed_thresholds_changed = Signal(float, float, float)
    max_wind_changed = Signal(float)
    efficiency_thresholds_changed = Signal(float, float, float)
    theme_changed = Signal(str)
    timezone_changed = Signal(float)
    language_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._utc_offset = 0.0
        self._language = i18n.get_language()
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
        self._tile_handler = None

        outer_layout = QVBoxLayout(self)
        columns_layout = QHBoxLayout()
        outer_layout.addLayout(columns_layout)
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()
        columns_layout.addLayout(left_layout, 1)
        columns_layout.addLayout(right_layout, 1)
        layout = left_layout

        # ── Theme ────────────────────────────────────────────────────────────
        self.theme_group = QGroupBox()
        theme_layout = QFormLayout(self.theme_group)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("", "light")
        self.theme_combo.addItem("", "dark")
        self.theme_combo.addItem("", "system")
        self.theme_combo.setCurrentIndex(2)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.theme_label = QLabel()
        theme_layout.addRow(self.theme_label, self.theme_combo)

        self.timezone_combo = QComboBox()
        for offset in range(-12, 15):
            lbl = "UTC" if offset == 0 else f"UTC{offset:+d}"
            self.timezone_combo.addItem(lbl, float(offset))
        self.timezone_combo.setCurrentIndex(self.timezone_combo.findData(0.0))
        self.timezone_combo.currentIndexChanged.connect(self._on_timezone_changed)
        self.timezone_label = QLabel()
        theme_layout.addRow(self.timezone_label, self.timezone_combo)

        self.language_combo = QComboBox()
        self.language_combo.addItem("Русский", "ru")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(self.language_combo.findData(i18n.get_language()))
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self.language_label = QLabel()
        theme_layout.addRow(self.language_label, self.language_combo)
        layout.addWidget(self.theme_group)

        # ── Notifications ────────────────────────────────────────────────────
        self.notifications_group = QGroupBox()
        notifications_layout = QVBoxLayout(self.notifications_group)
        self.sound_alerts_checkbox = QCheckBox()
        self.sound_alerts_checkbox.setChecked(True)
        notifications_layout.addWidget(self.sound_alerts_checkbox)
        layout.addWidget(self.notifications_group)

        # ── Map tile cache ───────────────────────────────────────────────────
        self.cache_group = QGroupBox()
        cache_layout = QVBoxLayout(self.cache_group)
        self.cache_size_label = QLabel()
        self._update_cache_size_label()
        cache_layout.addWidget(self.cache_size_label)

        max_cache_row = QHBoxLayout()
        self.max_cache_label = QLabel()
        max_cache_row.addWidget(self.max_cache_label)
        self.max_cache_size_combo = QComboBox()
        for lbl, value in _CACHE_SIZE_OPTIONS:
            self.max_cache_size_combo.addItem(lbl, value)
        self.max_cache_size_combo.setCurrentIndex(
            self.max_cache_size_combo.findData(tile_cache.DEFAULT_MAX_CACHE_BYTES))
        self.max_cache_size_combo.currentIndexChanged.connect(self._on_max_cache_size_changed)
        max_cache_row.addWidget(self.max_cache_size_combo)
        max_cache_row.addStretch()
        cache_layout.addLayout(max_cache_row)

        self.clear_cache_button = QPushButton()
        self.clear_cache_button.clicked.connect(self._on_clear_cache_clicked)
        cache_layout.addWidget(self.clear_cache_button)
        layout.addWidget(self.cache_group)

        layout = right_layout

        # ── Battery ──────────────────────────────────────────────────────────
        self.battery_group = QGroupBox()
        battery_layout = QFormLayout(self.battery_group)

        self.cell_count_combo = QComboBox()
        self.cell_count_combo.addItems(["4S", "6S", "8S", "10S", "12S"])
        self.cell_count_combo.setCurrentText("8S")
        self.cell_count_combo.currentTextChanged.connect(self._on_cell_count_changed)
        self.cell_count_label = QLabel()
        battery_layout.addRow(self.cell_count_label, self.cell_count_combo)

        self.hv_checkbox = QCheckBox()
        self.hv_checkbox.stateChanged.connect(self._on_hv_changed)
        self.battery_type_label = QLabel()
        battery_layout.addRow(self.battery_type_label, self.hv_checkbox)

        self.threshold_label = QLabel()
        self._update_threshold_label()
        self.voltage_range_label = QLabel()
        battery_layout.addRow(self.voltage_range_label, self.threshold_label)

        layout.addWidget(self.battery_group)

        # ── Color settings ───────────────────────────────────────────────────
        self.color_group = QGroupBox()
        color_layout = QFormLayout(self.color_group)

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
        self.current_green_label = QLabel()
        self.current_red_label = QLabel()
        current_row.addWidget(self.current_green_label)
        current_row.addWidget(self.current_green_spin)
        current_row.addWidget(self.current_red_label)
        current_row.addWidget(self.current_red_spin)
        self.current_row_label = QLabel()
        color_layout.addRow(self.current_row_label, current_row)

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
        self.speed_min_label = QLabel()
        self.speed_target_label = QLabel()
        self.speed_max_label = QLabel()
        speed_row.addWidget(self.speed_min_label)
        speed_row.addWidget(self.speed_min_spin)
        speed_row.addWidget(self.speed_target_label)
        speed_row.addWidget(self.speed_target_spin)
        speed_row.addWidget(self.speed_max_label)
        speed_row.addWidget(self.speed_max_spin)
        self.speed_row_label = QLabel()
        color_layout.addRow(self.speed_row_label, speed_row)

        self.max_wind_spin = QSpinBox()
        self.max_wind_spin.setRange(0, 100)
        self.max_wind_spin.setSuffix(" м/с")
        self.max_wind_spin.setValue(self._max_wind)
        self.max_wind_spin.valueChanged.connect(self._on_max_wind_changed)
        self.max_wind_label = QLabel()
        color_layout.addRow(self.max_wind_label, self.max_wind_spin)

        layout.addWidget(self.color_group)

        # ── Efficiency thresholds ────────────────────────────────────────────
        self.efficiency_group = QGroupBox()
        efficiency_layout = QFormLayout(self.efficiency_group)

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
        self.eff_row_label = QLabel()
        efficiency_layout.addRow(self.eff_row_label, eff_row)
        layout.addWidget(self.efficiency_group)

        # ── Battery info ─────────────────────────────────────────────────────
        self.info_group = QGroupBox()
        info_layout = QVBoxLayout(self.info_group)
        self.info_lipo_title = QLabel("LiPo / Li-ion:")
        self.info_lipo_full = QLabel()
        self.info_lipo_min = QLabel()
        self.info_lihv_title = QLabel()
        self.info_lihv_full = QLabel()
        self.info_lihv_min = QLabel()
        for lbl in (self.info_lipo_title, self.info_lipo_full, self.info_lipo_min,
                    self.info_lihv_title, self.info_lihv_full, self.info_lihv_min):
            info_layout.addWidget(lbl)
        layout.addWidget(self.info_group)

        left_layout.addStretch()
        right_layout.addStretch()

        i18n.register(self._retranslateUi)
        self._retranslateUi()

    def _retranslateUi(self):
        tr = i18n.tr
        self.theme_group.setTitle(tr("Тема приложения"))
        self.theme_label.setText(tr("Тема:"))
        self.theme_combo.setItemText(0, tr("Светлая"))
        self.theme_combo.setItemText(1, tr("Темная"))
        self.theme_combo.setItemText(2, tr("Системная"))
        self.timezone_label.setText(tr("Часовой пояс:"))
        self.language_label.setText(tr("Язык:"))
        self.language_combo.setItemText(0, tr("Русский"))

        self.notifications_group.setTitle(tr("Уведомления"))
        self.sound_alerts_checkbox.setText(tr("Звуковые оповещения"))

        self.cache_group.setTitle(tr("Кэш картографических данных"))
        self.max_cache_label.setText(tr("Максимальный объём:"))
        self.clear_cache_button.setText(tr("Очистить кэш картографических данных"))
        self._update_cache_size_label()

        self.battery_group.setTitle(tr("Настройка аккумулятора"))
        self.cell_count_label.setText(tr("Количество ячеек:"))
        self.hv_checkbox.setText(tr("LiHV (повышенное напряжение)"))
        self.hv_checkbox.setToolTip(tr(
            "Включить для LiHV аккумуляторов\n"
            "Стандартный LiPo: 4.20В/ячейку (заряжен) / 3.60В/ячейку (разряжен)\n"
            "LiHV: 4.35В/ячейку (заряжен) / 3.60В/ячейку (разряжен)"
        ))
        self.battery_type_label.setText(tr("Тип аккумулятора:"))
        self.voltage_range_label.setText(tr("Диапазон напряжения:"))
        self._update_threshold_label()

        self.color_group.setTitle(tr("Цветовая настройка"))
        self.current_row_label.setText(tr("Сила тока:"))
        self.current_green_label.setText(tr("Зеленый:"))
        self.current_red_label.setText(tr("Красный:"))
        self.speed_row_label.setText(tr("Скорость:"))
        self.speed_min_label.setText(tr("Минимальная:"))
        self.speed_target_label.setText(tr("Целевая:"))
        self.speed_max_label.setText(tr("Максимальная:"))
        self.max_wind_label.setText(tr("Максимальный ветер:"))

        self.efficiency_group.setTitle(tr("Пороги эффективности"))
        self.eff_row_label.setText(tr("Расход (мА·ч):"))

        self.info_group.setTitle(tr("Информация о напряжении"))
        self.info_lipo_full.setText(tr("  • Полный заряд: 4.20В/ячейку"))
        self.info_lipo_min.setText(tr("  • Минимум: 3.60В/ячейку"))
        self.info_lihv_title.setText(tr("LiHV (повышенное напряжение):"))
        self.info_lihv_full.setText(tr("  • Полный заряд: 4.35В/ячейку"))
        self.info_lihv_min.setText(tr("  • Минимум: 3.60В/ячейку"))

    @staticmethod
    def _make_dot(color: str) -> QLabel:
        dot = QLabel()
        dot.setFixedSize(12, 12)
        dot.setStyleSheet(f"background-color: {color}; border-radius: 6px;")
        return dot

    def _on_theme_changed(self, index: int):
        self.theme_changed.emit(self.theme_combo.itemData(index))

    def current_theme(self) -> str:
        return self.theme_combo.currentData()

    def _on_timezone_changed(self, index: int):
        self._utc_offset = self.timezone_combo.itemData(index)
        self.timezone_changed.emit(self._utc_offset)

    def get_utc_offset(self) -> float:
        return self._utc_offset

    def _on_language_changed(self, index: int):
        lang = self.language_combo.itemData(index)
        self._language = lang
        i18n.set_language(lang)
        self.language_changed.emit(lang)

    def get_language(self) -> str:
        return self._language

    def _on_cell_count_changed(self, text: str):
        self._battery_cells = int(text.replace("S", ""))
        self.battery_cell_count_changed.emit(self._battery_cells)

    def _on_hv_changed(self, state: int):
        self._battery_hv = (state == 2)
        self.battery_hv_changed.emit(self._battery_hv)
        self._update_threshold_label()

    def _update_threshold_label(self):
        per = i18n.tr("на ячейку")
        if self._battery_hv:
            self.threshold_label.setText(
                f"<span style='color: #3cb44b;'>4.35В</span> / "
                f"<span style='color: #e6194b;'>3.60В</span> {per}"
            )
        else:
            self.threshold_label.setText(
                f"<span style='color: #3cb44b;'>4.20В</span> / "
                f"<span style='color: #e6194b;'>3.60В</span> {per}"
            )

    def _on_current_thresholds_changed(self):
        self._current_green = self.current_green_spin.value()
        self._current_red = self.current_red_spin.value()
        if self.current_red_spin.value() < self.current_green_spin.value():
            self.current_red_spin.setValue(self.current_green_spin.value())
            return
        self.current_thresholds_changed.emit(float(self._current_green), float(self._current_red))

    def _on_speed_thresholds_changed(self):
        min_v = self.speed_min_spin.value()
        target_v = self.speed_target_spin.value()
        max_v = self.speed_max_spin.value()
        if target_v < min_v:
            self.speed_target_spin.setValue(min_v)
            return
        if max_v < target_v:
            self.speed_max_spin.setValue(target_v)
            return
        self._speed_min, self._speed_target, self._speed_max = min_v, target_v, max_v
        self.speed_thresholds_changed.emit(float(min_v), float(target_v), float(max_v))

    def get_battery_cell_count(self) -> int:
        return self._battery_cells

    def is_hv_battery(self) -> bool:
        return self._battery_hv

    def get_current_thresholds(self) -> tuple[float, float]:
        return float(self._current_green), float(self._current_red)

    def get_speed_thresholds(self) -> tuple[float, float, float]:
        return float(self._speed_min), float(self._speed_target), float(self._speed_max)

    def _on_efficiency_thresholds_changed(self):
        green_v = self.eff_green_spin.value()
        yellow_v = self.eff_yellow_spin.value()
        red_v = self.eff_red_spin.value()
        if yellow_v < green_v:
            self.eff_yellow_spin.setValue(green_v)
            return
        if red_v < yellow_v:
            self.eff_red_spin.setValue(yellow_v)
            return
        self._eff_green, self._eff_yellow, self._eff_red = green_v, yellow_v, red_v
        self.efficiency_thresholds_changed.emit(float(green_v), float(yellow_v), float(red_v))

    def get_efficiency_thresholds(self) -> tuple[float, float, float]:
        return float(self._eff_green), float(self._eff_yellow), float(self._eff_red)

    def _on_max_wind_changed(self, value: int):
        self._max_wind = value
        self.max_wind_changed.emit(float(self._max_wind))

    def get_max_wind(self) -> float:
        return float(self._max_wind)

    def is_sound_alerts_enabled(self) -> bool:
        return self.sound_alerts_checkbox.isChecked()

    def _update_cache_size_label(self):
        size = tile_cache.get_cache_size_bytes()
        self.cache_size_label.setText(
            f"{i18n.tr('Объём картографических данных: ')}{tile_cache.format_size(size)}"
        )

    def refresh_cache_size_label(self):
        self._update_cache_size_label()

    def set_tile_handler(self, tile_handler):
        self._tile_handler = tile_handler

    def _on_max_cache_size_changed(self, index: int):
        value = self.max_cache_size_combo.itemData(index)
        tile_cache.set_max_cache_size_bytes(value)
        if self._tile_handler is not None:
            self._tile_handler.recheck_cache_limit()

    def _on_clear_cache_clicked(self):
        tile_cache.clear_cache()
        self._update_cache_size_label()
        QMessageBox.information(self, i18n.tr("Кэш карты"),
                                i18n.tr("Кэш картографических данных очищен."))

    def showEvent(self, event):
        super().showEvent(event)
        self._update_cache_size_label()
