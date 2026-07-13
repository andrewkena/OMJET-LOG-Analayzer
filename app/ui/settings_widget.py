"""Application settings tab - battery configuration and other app preferences."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QComboBox, QCheckBox,
    QSpinBox, QDoubleSpinBox, QFormLayout, QListWidget, QListWidgetItem, QPushButton, QMessageBox
)
from PySide6.QtCore import Signal

from app.core import tile_cache, i18n
from app.core.paths import get_user_data_dir

_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
_SETTINGS_FILE = get_user_data_dir() / "user_settings.json"

_ICON_VEHICLE_TYPES = [
    ("VTOL 4+1",        "vtol41_icon.svg"),
    ("VTOL 2+1 vector", "vtol31_icon.svg"),
    ("Коптер",          "copter_icon.svg"),
    ("По умолчанию",    "def_icon.svg"),
]

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
    battery_chemistry_changed = Signal(int, str)  # (instance 1|2, chemistry)
    current_thresholds_changed = Signal(float, float)
    speed_thresholds_changed = Signal(float, float, float)
    max_wind_changed = Signal(float)
    efficiency_thresholds_changed = Signal(float, float, float)
    hover_thrust_thresholds_changed = Signal(float, float)
    theme_changed = Signal(str)
    timezone_changed = Signal(float)
    language_changed = Signal(str)
    icon_mapping_changed = Signal(dict)
    cog_thresholds_changed = Signal(float, float, float, float)
    callout_style_changed = Signal(str)
    callout_fields_changed = Signal(bool, bool, bool)
    snr_range_changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._utc_offset = 0.0
        self._language = i18n.get_language()
        self._battery_cells = 8
        self._bat_chemistry = {1: "lipo", 2: "lipo"}
        self._current_green = 50
        self._current_red = 100
        self._speed_min = 16
        self._speed_target = 20
        self._speed_max = 24
        self._max_wind = 12
        self._eff_green = 200
        self._eff_yellow = 300
        self._eff_red = 400
        self._hover_thrust_green = 0.5
        self._hover_thrust_red = 1.0
        self._cog_neutral_min = -3.0
        self._cog_neutral_max = 3.0
        self._cog_front_red = 10.0
        self._cog_rear_red = -10.0
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

        # ── Icon mapping ─────────────────────────────────────────────────────
        self.icon_group = QGroupBox()
        icon_layout = QFormLayout(self.icon_group)
        self._icon_combos: dict[str, QComboBox] = {}
        svg_files = sorted(p.name for p in _ASSETS_DIR.glob("*.svg")) if _ASSETS_DIR.exists() else []
        saved_mapping = self._load_icon_mapping()
        for vtype, default_svg in _ICON_VEHICLE_TYPES:
            combo = QComboBox()
            for name in svg_files:
                combo.addItem(name)
            current_svg = saved_mapping.get(vtype, default_svg)
            if current_svg in svg_files:
                combo.setCurrentText(current_svg)
            combo.currentTextChanged.connect(self._on_icon_mapping_changed)
            self._icon_combos[vtype] = combo
            lbl = QLabel(vtype)
            icon_layout.addRow(lbl, combo)
        layout.addWidget(self.icon_group)

        # ── Map callout ──────────────────────────────────────────────────────────
        self.callout_group = QGroupBox()
        callout_layout = QVBoxLayout(self.callout_group)

        style_row = QHBoxLayout()
        self.callout_style_label = QLabel()
        style_row.addWidget(self.callout_style_label)
        self.callout_style_combo = QComboBox()
        self.callout_style_combo.addItem("", "standard")
        self.callout_style_combo.addItem("", "shelf")
        self.callout_style_combo.addItem("", "none")
        self.callout_style_combo.currentIndexChanged.connect(self._on_callout_changed)
        style_row.addWidget(self.callout_style_combo)
        style_row.addStretch()
        callout_layout.addLayout(style_row)

        fields_row = QHBoxLayout()
        self.callout_time_cb = QCheckBox()
        self.callout_time_cb.setChecked(True)
        self.callout_time_cb.stateChanged.connect(self._on_callout_changed)
        self.callout_speed_cb = QCheckBox()
        self.callout_speed_cb.stateChanged.connect(self._on_callout_changed)
        self.callout_dist_cb = QCheckBox()
        self.callout_dist_cb.stateChanged.connect(self._on_callout_changed)
        fields_row.addWidget(self.callout_time_cb)
        fields_row.addWidget(self.callout_speed_cb)
        fields_row.addWidget(self.callout_dist_cb)
        fields_row.addStretch()
        callout_layout.addLayout(fields_row)

        layout.addWidget(self.callout_group)
        self._load_callout_settings()


        layout = right_layout

        # ── Battery ──────────────────────────────────────────────────────────
        self.battery_group = QGroupBox()
        battery_outer = QHBoxLayout(self.battery_group)

        # Left: settings
        battery_layout = QFormLayout()
        self.cell_count_combo = QComboBox()
        self.cell_count_combo.addItems(["4S", "6S", "8S", "10S", "12S"])
        self.cell_count_combo.setCurrentText("8S")
        self.cell_count_combo.currentTextChanged.connect(self._on_cell_count_changed)
        self.cell_count_label = QLabel()
        battery_layout.addRow(self.cell_count_label, self.cell_count_combo)

        _chem = [("LiPo (4.20В)", "lipo"), ("LiHV (4.35В)", "lihv"), ("LiUHV (4.40В)", "liuhv")]
        self.bat1_chem_label = QLabel()
        self.bat1_chem_combo = QComboBox()
        for txt, data in _chem:
            self.bat1_chem_combo.addItem(txt, data)
        self.bat1_chem_combo.currentIndexChanged.connect(lambda _: self._on_bat_chemistry_changed(1))
        battery_layout.addRow(self.bat1_chem_label, self.bat1_chem_combo)

        self.bat2_chem_label = QLabel()
        self.bat2_chem_combo = QComboBox()
        for txt, data in _chem:
            self.bat2_chem_combo.addItem(txt, data)
        self.bat2_chem_combo.currentIndexChanged.connect(lambda _: self._on_bat_chemistry_changed(2))
        battery_layout.addRow(self.bat2_chem_label, self.bat2_chem_combo)

        battery_outer.addLayout(battery_layout)

        # Right: voltage info
        info_layout = QVBoxLayout()
        self.info_lipo_title = QLabel()
        self.info_lipo_full = QLabel()
        self.info_lihv_title = QLabel()
        self.info_lihv_full = QLabel()
        self.info_liuhv_title = QLabel()
        self.info_liuhv_full = QLabel()
        self.info_volt_min = QLabel()
        for lbl in (self.info_lipo_title, self.info_lipo_full,
                    self.info_lihv_title, self.info_lihv_full,
                    self.info_liuhv_title, self.info_liuhv_full,
                    self.info_volt_min):
            info_layout.addWidget(lbl)
        info_layout.addStretch()
        battery_outer.addLayout(info_layout)
        self._load_battery_chemistry()

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

        hover_thrust_row = QHBoxLayout()
        hover_thrust_row.addWidget(self._make_dot("#3cb44b"))
        self.hover_thrust_green_spin = QDoubleSpinBox()
        self.hover_thrust_green_spin.setRange(0.0, 2.0)
        self.hover_thrust_green_spin.setDecimals(2)
        self.hover_thrust_green_spin.setSingleStep(0.05)
        self.hover_thrust_green_spin.setValue(self._hover_thrust_green)
        self.hover_thrust_green_spin.valueChanged.connect(self._on_hover_thrust_thresholds_changed)
        hover_thrust_row.addWidget(self.hover_thrust_green_spin)
        hover_thrust_row.addWidget(self._make_dot("#e6194b"))
        self.hover_thrust_red_spin = QDoubleSpinBox()
        self.hover_thrust_red_spin.setRange(0.0, 2.0)
        self.hover_thrust_red_spin.setDecimals(2)
        self.hover_thrust_red_spin.setSingleStep(0.05)
        self.hover_thrust_red_spin.setValue(self._hover_thrust_red)
        self.hover_thrust_red_spin.valueChanged.connect(self._on_hover_thrust_thresholds_changed)
        hover_thrust_row.addWidget(self.hover_thrust_red_spin)
        hover_thrust_row.addStretch()
        self.hover_thrust_row_label = QLabel()
        efficiency_layout.addRow(self.hover_thrust_row_label, hover_thrust_row)

        layout.addWidget(self.efficiency_group)

        # ── Center of Gravity thresholds ─────────────────────────────────────
        self.cog_group = QGroupBox()
        cog_layout = QFormLayout(self.cog_group)

        neutral_row = QHBoxLayout()
        neutral_row.addWidget(self._make_dot("#3cb44b"))
        self.cog_neutral_min_spin = QDoubleSpinBox()
        self.cog_neutral_min_spin.setRange(-100.0, 0.0)
        self.cog_neutral_min_spin.setDecimals(1)
        self.cog_neutral_min_spin.setSingleStep(0.5)
        self.cog_neutral_min_spin.setValue(-3.0)
        self.cog_neutral_min_spin.valueChanged.connect(self._on_cog_thresholds_changed)
        neutral_row.addWidget(self.cog_neutral_min_spin)
        self.cog_neutral_to_label = QLabel()
        neutral_row.addWidget(self.cog_neutral_to_label)
        self.cog_neutral_max_spin = QDoubleSpinBox()
        self.cog_neutral_max_spin.setRange(0.0, 100.0)
        self.cog_neutral_max_spin.setDecimals(1)
        self.cog_neutral_max_spin.setSingleStep(0.5)
        self.cog_neutral_max_spin.setValue(3.0)
        self.cog_neutral_max_spin.valueChanged.connect(self._on_cog_thresholds_changed)
        neutral_row.addWidget(self.cog_neutral_max_spin)
        neutral_row.addStretch()
        self.cog_neutral_label = QLabel()
        cog_layout.addRow(self.cog_neutral_label, neutral_row)

        front_row = QHBoxLayout()
        front_row.addWidget(self._make_dot("#e6194b"))
        self.cog_front_spin = QDoubleSpinBox()
        self.cog_front_spin.setRange(0.0, 100.0)
        self.cog_front_spin.setDecimals(1)
        self.cog_front_spin.setSingleStep(0.5)
        self.cog_front_spin.setValue(10.0)
        self.cog_front_spin.valueChanged.connect(self._on_cog_thresholds_changed)
        front_row.addWidget(self.cog_front_spin)
        front_row.addStretch()
        self.cog_front_label = QLabel()
        cog_layout.addRow(self.cog_front_label, front_row)

        rear_row = QHBoxLayout()
        rear_row.addWidget(self._make_dot("#e6194b"))
        self.cog_rear_spin = QDoubleSpinBox()
        self.cog_rear_spin.setRange(-100.0, 0.0)
        self.cog_rear_spin.setDecimals(1)
        self.cog_rear_spin.setSingleStep(0.5)
        self.cog_rear_spin.setValue(-10.0)
        self.cog_rear_spin.valueChanged.connect(self._on_cog_thresholds_changed)
        rear_row.addWidget(self.cog_rear_spin)
        rear_row.addStretch()
        self.cog_rear_label = QLabel()
        cog_layout.addRow(self.cog_rear_label, rear_row)

        layout.addWidget(self.cog_group)

        # ── SNR range ─────────────────────────────────────────────────────────
        self.snr_group = QGroupBox()
        snr_layout = QFormLayout(self.snr_group)

        self.snr_min_spin = QDoubleSpinBox()
        self.snr_min_spin.setRange(-50.0, 200.0)
        self.snr_min_spin.setDecimals(1)
        self.snr_min_spin.setSingleStep(1.0)
        self.snr_min_spin.setValue(0.0)
        self.snr_min_spin.valueChanged.connect(self._on_snr_range_changed)
        snr_min_row = QHBoxLayout()
        snr_min_row.addWidget(self._make_dot("#e6194b"))
        snr_min_row.addWidget(self.snr_min_spin)
        snr_min_row.addStretch()
        self.snr_min_label = QLabel()
        snr_layout.addRow(self.snr_min_label, snr_min_row)

        self.snr_max_spin = QDoubleSpinBox()
        self.snr_max_spin.setRange(-50.0, 200.0)
        self.snr_max_spin.setDecimals(1)
        self.snr_max_spin.setSingleStep(1.0)
        self.snr_max_spin.setValue(60.0)
        self.snr_max_spin.valueChanged.connect(self._on_snr_range_changed)
        snr_max_row = QHBoxLayout()
        snr_max_row.addWidget(self._make_dot("#3cb44b"))
        snr_max_row.addWidget(self.snr_max_spin)
        snr_max_row.addStretch()
        self.snr_max_label = QLabel()
        snr_layout.addRow(self.snr_max_label, snr_max_row)

        layout.addWidget(self.snr_group)

        # ── Update check ────────────────────────────────────────────────────
        update_group = QGroupBox()
        update_layout = QVBoxLayout(update_group)
        self._check_update_btn = QPushButton()
        self._check_update_btn.clicked.connect(self._on_check_update)
        update_layout.addWidget(self._check_update_btn)
        self.update_group = update_group
        right_layout.addWidget(self.update_group)

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

        self.icon_group.setTitle(tr("Иконки типов ВС"))

        self.notifications_group.setTitle(tr("Уведомления"))
        self.sound_alerts_checkbox.setText(tr("Звуковые оповещения"))

        self.cache_group.setTitle(tr("Кэш картографических данных"))
        self.max_cache_label.setText(tr("Максимальный объём:"))
        self.clear_cache_button.setText(tr("Очистить кэш картографических данных"))
        self._update_cache_size_label()

        self.battery_group.setTitle(tr("Настройка аккумулятора"))
        self.cell_count_label.setText(tr("Количество ячеек:"))
        self.bat1_chem_label.setText(tr("Батарея 1:"))
        self.bat2_chem_label.setText(tr("Батарея 2:"))

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
        self.hover_thrust_row_label.setText(tr("Вертикальная тяга Q_M_THST_HOVER:"))

        self.cog_group.setTitle(tr("Центровка"))
        self.cog_neutral_label.setText(tr("Нейтральная:"))
        self.cog_neutral_to_label.setText(tr("до"))
        self.cog_front_label.setText(tr("Передняя (красный порог):"))
        self.cog_rear_label.setText(tr("Задняя (красный порог):"))

        self.snr_group.setTitle(tr("Качество связи (SNR)"))
        self.snr_min_label.setText(tr("Минимальный SNR:"))
        self.snr_max_label.setText(tr("Максимальный SNR:"))

        self.info_lipo_title.setText("LiPo / Li-ion:")
        self.info_lipo_full.setText(tr("  • Заряжен: 4.20В/ячейку"))
        self.info_lihv_title.setText("LiHV:")
        self.info_lihv_full.setText(tr("  • Заряжен: 4.35В/ячейку"))
        self.info_liuhv_title.setText("LiUHV:")
        self.info_liuhv_full.setText(tr("  • Заряжен: 4.40В/ячейку"))
        self.info_volt_min.setText(tr("  • Мин: 3.60В/ячейку (все типы)"))

        self.callout_group.setTitle(tr("Информационная сноска на карте"))
        self.callout_style_label.setText(tr("Стиль:"))
        self.callout_style_combo.setItemText(0, tr("Стандарт"))
        self.callout_style_combo.setItemText(1, tr("На полке"))
        self.callout_style_combo.setItemText(2, tr("Без данных"))
        self.callout_time_cb.setText(tr("Время"))
        self.callout_speed_cb.setText(tr("Скорость"))
        self.callout_dist_cb.setText(tr("Расстояние"))

        self.update_group.setTitle(tr("Обновления"))
        self._check_update_btn.setText(tr("Проверить обновления"))

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

    def _on_bat_chemistry_changed(self, instance: int):
        combo = self.bat1_chem_combo if instance == 1 else self.bat2_chem_combo
        chemistry = combo.currentData() or "lipo"
        self._bat_chemistry[instance] = chemistry
        self.battery_chemistry_changed.emit(instance, chemistry)
        self._save_battery_chemistry()

    def _save_battery_chemistry(self):
        try:
            try:
                data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                data = {}
            data["bat_chemistry"] = self._bat_chemistry
            _SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load_battery_chemistry(self):
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            saved = data.get("bat_chemistry", {})
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        for instance, combo in ((1, self.bat1_chem_combo), (2, self.bat2_chem_combo)):
            chem = saved.get(str(instance), saved.get(instance, "lipo"))
            idx = combo.findData(chem)
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)
                self._bat_chemistry[instance] = chem

    def get_battery_chemistry(self, instance: int) -> str:
        return self._bat_chemistry.get(instance, "lipo")

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

    def _on_hover_thrust_thresholds_changed(self):
        green_v = self.hover_thrust_green_spin.value()
        red_v = self.hover_thrust_red_spin.value()
        if red_v < green_v:
            self.hover_thrust_red_spin.setValue(green_v)
            return
        self._hover_thrust_green, self._hover_thrust_red = green_v, red_v
        self.hover_thrust_thresholds_changed.emit(green_v, red_v)

    def get_hover_thrust_thresholds(self) -> tuple[float, float]:
        return self._hover_thrust_green, self._hover_thrust_red

    def _on_cog_thresholds_changed(self):
        neutral_min = self.cog_neutral_min_spin.value()
        neutral_max = self.cog_neutral_max_spin.value()
        front_red = self.cog_front_spin.value()
        rear_red = self.cog_rear_spin.value()
        self._cog_neutral_min = neutral_min
        self._cog_neutral_max = neutral_max
        self._cog_front_red = front_red
        self._cog_rear_red = rear_red
        self.cog_thresholds_changed.emit(neutral_min, neutral_max, front_red, rear_red)

    def get_cog_thresholds(self) -> tuple[float, float, float, float]:
        return self._cog_neutral_min, self._cog_neutral_max, self._cog_front_red, self._cog_rear_red

    def _on_check_update(self):
        from app.core.update_checker import UpdateChecker, _parse_version
        from app.core.version import APP_VERSION
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        self._check_update_btn.setEnabled(False)
        self._check_update_btn.setText(i18n.tr("Проверка..."))

        self._upd_checker = UpdateChecker(self)

        def on_update(tag: str, url: str):
            box = QMessageBox(self)
            box.setWindowTitle(i18n.tr("Доступно обновление"))
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(
                f"<b>{i18n.tr('Доступна новая версия')}: {tag}</b><br>"
                f"{i18n.tr('Текущая версия')}: {APP_VERSION}"
            )
            box.setInformativeText(i18n.tr("Перейти на страницу загрузки?"))
            open_btn = box.addButton(i18n.tr("Перейти на GitHub"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(i18n.tr("Закрыть"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is open_btn:
                QDesktopServices.openUrl(QUrl(url))

        def on_done():
            self._check_update_btn.setEnabled(True)
            self._retranslateUi()
            if not self._upd_checker.receivers(self._upd_checker.update_available):
                # No update signal was emitted → already up to date
                pass

        def on_no_update():
            QMessageBox.information(
                self,
                i18n.tr("Обновления"),
                f"{i18n.tr('У вас установлена последняя версия')}: {APP_VERSION}",
            )

        # Track whether update was found
        self._upd_found = False

        def on_update_tracked(tag: str, url: str):
            self._upd_found = True
            on_update(tag, url)

        def on_done_tracked():
            self._check_update_btn.setEnabled(True)
            self._retranslateUi()
            if not self._upd_found:
                on_no_update()

        self._upd_checker.update_available.connect(on_update_tracked)
        self._upd_checker.check_done.connect(on_done_tracked)
        self._upd_checker.start()

    def _on_snr_range_changed(self):
        snr_min = self.snr_min_spin.value()
        snr_max = self.snr_max_spin.value()
        if snr_max <= snr_min:
            self.snr_max_spin.setValue(snr_min + 1.0)
            return
        self.snr_range_changed.emit(snr_min, snr_max)

    def get_snr_range(self) -> tuple[float, float]:
        return self.snr_min_spin.value(), self.snr_max_spin.value()

    def set_snr_range(self, snr_min: float, snr_max: float) -> None:
        for spin, val in ((self.snr_min_spin, snr_min), (self.snr_max_spin, snr_max)):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)

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

    def get_icon_mapping(self) -> dict[str, str]:
        return {vtype: combo.currentText() for vtype, combo in self._icon_combos.items()}

    def _on_icon_mapping_changed(self):
        mapping = self.get_icon_mapping()
        self._save_icon_mapping(mapping)
        self.icon_mapping_changed.emit(mapping)

    def _save_icon_mapping(self, mapping: dict[str, str]):
        try:
            try:
                data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                data = {}
            data["icon_mapping"] = mapping
            _SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load_icon_mapping(self) -> dict[str, str]:
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            return data.get("icon_mapping", {})
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _on_callout_changed(self):
        style = self.callout_style_combo.currentData() or "standard"
        self.callout_style_changed.emit(style)
        self.callout_fields_changed.emit(
            self.callout_time_cb.isChecked(),
            self.callout_speed_cb.isChecked(),
            self.callout_dist_cb.isChecked(),
        )
        self._save_callout_settings()

    def _save_callout_settings(self):
        try:
            try:
                data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                data = {}
            data.update({
                "callout_style": self.callout_style_combo.currentData() or "standard",
                "callout_time": self.callout_time_cb.isChecked(),
                "callout_speed": self.callout_speed_cb.isChecked(),
                "callout_distance": self.callout_dist_cb.isChecked(),
            })
            _SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load_callout_settings(self):
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        style = data.get("callout_style", "standard")
        idx = self.callout_style_combo.findData(style)
        if idx >= 0:
            self.callout_style_combo.blockSignals(True)
            self.callout_style_combo.setCurrentIndex(idx)
            self.callout_style_combo.blockSignals(False)
        for cb, key, default in (
            (self.callout_time_cb, "callout_time", True),
            (self.callout_speed_cb, "callout_speed", False),
            (self.callout_dist_cb, "callout_distance", False),
        ):
            cb.blockSignals(True)
            cb.setChecked(data.get(key, default))
            cb.blockSignals(False)

    def get_callout_settings(self) -> tuple[str, bool, bool, bool]:
        return (
            self.callout_style_combo.currentData() or "standard",
            self.callout_time_cb.isChecked(),
            self.callout_speed_cb.isChecked(),
            self.callout_dist_cb.isChecked(),
        )

    def _save_setting(self, key: str, value):
        try:
            try:
                data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                data = {}
            data[key] = value
            _SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._update_cache_size_label()
