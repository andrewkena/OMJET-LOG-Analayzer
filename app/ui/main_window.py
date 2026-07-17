from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pymavlink import mavutil
from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QSplitter, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QMessageBox, QStatusBar, QProgressBar, QComboBox, QLabel, QPushButton, QFrame, QScrollArea
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QApplication

_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"

from app.core import tile_cache, i18n
from app.core.paths import get_user_data_dir
_SETTINGS_FILE = get_user_data_dir() / "user_settings.json"
from app.core.version import APP_VERSION
from app.core.log_loader import LogData
from app.core.log_load_worker import LogLoadWorker
from app.ui.message_tree import MessageTree
from app.ui.graph_widget import GraphWidget, MAX_CURVES
from app.ui.map_widget import MapWidget
from app.ui.events_widget import EventsWidget
from app.ui.timeline_widget import TimelineWidget
from app.ui.params_widget import ParamsWidget
from app.ui.mission_widget import MissionWidget
from app.ui.mission_analysis_widget import MissionAnalysisWidget
from app.ui.photo_geotag_widget import PhotoGeotagWidget
from app.ui.rc_panel import RCPanel
from app.ui.attitude_panel import AttitudePanel
from app.ui.motor_servo_panel import MotorServoPanel
from app.ui.settings_widget import SettingsWidget
from app.ui.link_quality_widget import LinkQualityWidget
from app.ui.theme import apply_dark_theme, apply_light_theme, apply_system_theme
from app.core.time_format import set_utc_offset_hours, format_mmss
from app.core.event_decoder import decode_event, decode_error
from app.core.update_checker import UpdateChecker
from app.core.changelog import CHANGELOG

GPS_LAT_CANDIDATES = [("GPS", "Lat", "Lng"), ("GPS", "Lat", "Lon"), ("GLOBAL_POSITION_INT", "lat", "lon")]
ALT_CANDIDATES = [("BARO", "Alt"), ("CTUN", "Alt"), ("GPS", "Alt"), ("GLOBAL_POSITION_INT", "relative_alt")]
RC_CANDIDATES = [
    ("RCIN", "C1", "C2", "C3", "C4"),
    ("RC_CHANNELS", "chan1_raw", "chan2_raw", "chan3_raw", "chan4_raw"),
    ("RC_CHANNELS_RAW", "chan1_raw", "chan2_raw", "chan3_raw", "chan4_raw"),
]
# (msg_type, roll_field, pitch_field, yaw_field, values_are_radians)
ATTITUDE_CANDIDATES = [
    ("ATT", "Roll", "Pitch", "Yaw", False),
    ("ATTITUDE", "roll", "pitch", "yaw", True),
]
# (msg_type, field, divisor) -> value in m/s
AIRSPEED_CANDIDATES = [("ARSP", "Airspeed", 1.0), ("VFR_HUD", "airspeed", 1.0)]
# (msg_type, rssi_field, label)  – ordered by preference
RSSI_CANDIDATES = [
    ("RSSI",        "RSSI",   "RSSI (встроенный приёмник)"),
    ("RC_CHANNELS", "rssi",   "RSSI (RC_CHANNELS)"),
    ("RAD",         "RSSI",   "RSSI (радиомодем SiK)"),
    ("RADIO",       "rssi",   "RSSI (радиомодем SiK, local)"),
    ("RADIO_STATUS","rssi",   "RSSI (RADIO_STATUS)"),
]
# (msg_type, field, divisor) -> value in m/s
GROUND_SPEED_CANDIDATES = [("GPS", "Spd", 1.0), ("VFR_HUD", "groundspeed", 1.0)]
# (msg_type, field, divisor) -> value in meters
ALT_GAUGE_CANDIDATES = [
    ("BARO", "Alt", 1.0), ("CTUN", "Alt", 1.0), ("GPS", "Alt", 1.0),
    ("GLOBAL_POSITION_INT", "relative_alt", 1000.0),
]
# (msg_type, north_field, east_field) -> EKF-estimated wind velocity components, m/s
WIND_CANDIDATES = [("XKF2", "VWN", "VWE"), ("NKF2", "VWN", "VWE")]
# (msg_type, field, invert) -> vertical speed in m/s, positive = climb
VSPEED_CANDIDATES = [("CTUN", "VSpd", False), ("NKF1", "VD", True), ("GPS", "VZ", False)]
# (msg_type, field) used by the "Baro vs GPS Altitude" graph preset
BARO_GPS_ALT_CANDIDATES = [("BARO", "Alt"), ("GPS", "Alt")]


def _battery_by_instance(table, instance: int):
    """Splits a combined BAT table (multi-instance, distinguished by "Inst") into one battery's Volt/Curr series."""
    if not table or "Volt" not in table or "Curr" not in table:
        return None
    if "Inst" in table:
        mask = table["Inst"] == float(instance)
        if not np.any(mask):
            return None
        return table["timestamp"][mask], table["Volt"][mask], table["Curr"][mask]
    return (table["timestamp"], table["Volt"], table["Curr"]) if instance == 0 else None


def _gps_by_instance(table, instance: int):
    """Splits GPS table (multi-instance via field 'I') into one receiver's NSats/HDop series."""
    if not table or "NSats" not in table or "HDop" not in table:
        return None
    if "I" in table:
        mask = table["I"] == float(instance)
        if not np.any(mask):
            return None
        return table["timestamp"][mask], table["NSats"][mask], table["HDop"][mask]
    return (table["timestamp"], table["NSats"], table["HDop"]) if instance == 0 else None
# ArduPilot SRV_Channel::Function ids for SERVOx_FUNCTION parameters
SERVO_FUNCTION_IDS = {
    "Aileron": 4, "Elevator": 19, "Rudder": 21, "Throttle": 70,
    "Motor1": 33, "Motor2": 34, "Motor3": 35, "Motor4": 36,
    "VTailLeft": 79, "VTailRight": 80,
}


class MainWindow(QMainWindow):
    def __init__(self, tile_handler=None):
        super().__init__()
        self._tile_handler = tile_handler
        self.setWindowTitle(f"ОМДЖЕТ ЛОГ Анализатор  v{APP_VERSION}")
        self.setWindowIcon(QIcon(str(_ASSETS_DIR / "logo.ico")))
        self.resize(1900, 1000)
        self.setMinimumWidth(800)

        self.log_data: LogData | None = None
        self._worker: LogLoadWorker | None = None
        self._field_graph_assignment: dict[str, int] = {}
        self._current_time = 0.0
        self._playback_speed = 1.0
        self._playback_reverse = False

        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(50)
        self.playback_timer.timeout.connect(self._on_playback_tick)

        self._load_done_sound = QSoundEffect(self)
        self._load_done_sound.setSource(QUrl.fromLocalFile(str(_ASSETS_DIR / "done.wav")))

        self._build_layout()
        self._build_status_bar()
        self._connect_settings_signals()
        QTimer.singleShot(0, lambda: self._main_splitter.setSizes([850, 1050]))

    def _build_status_bar(self):
        status = QStatusBar()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedWidth(220)
        self.progress_bar.hide()
        status.addPermanentWidget(self.progress_bar)
        self.setStatusBar(status)

    def _connect_settings_signals(self):
        """Connect settings signals to attitude panel."""
        self.settings_widget.battery_cell_count_changed.connect(self.attitude_panel.set_battery_cell_count)
        self.settings_widget.battery_chemistry_changed.connect(self.attitude_panel.set_battery_chemistry)
        self.settings_widget.current_thresholds_changed.connect(self.attitude_panel.set_current_thresholds)
        self.settings_widget.speed_thresholds_changed.connect(self.attitude_panel.set_speed_thresholds)
        self.settings_widget.max_wind_changed.connect(self.map_widget.set_max_wind)
        self.settings_widget.icon_mapping_changed.connect(self.attitude_panel.set_icon_mapping)
        self.settings_widget.icon_mapping_changed.connect(self.map_widget.set_icon_mapping)
        initial_mapping = self.settings_widget.get_icon_mapping()
        self.attitude_panel.set_icon_mapping(initial_mapping)
        self.map_widget.set_icon_mapping(initial_mapping)
        self.settings_widget.efficiency_thresholds_changed.connect(self.mission_analysis_widget.set_efficiency_thresholds)
        self.mission_analysis_widget.set_efficiency_thresholds(*self.settings_widget.get_efficiency_thresholds())
        self.settings_widget.hover_thrust_thresholds_changed.connect(self.mission_analysis_widget.set_hover_thrust_thresholds)
        self.mission_analysis_widget.set_hover_thrust_thresholds(*self.settings_widget.get_hover_thrust_thresholds())
        self.settings_widget.cog_thresholds_changed.connect(self.mission_analysis_widget.set_cog_thresholds)
        self.mission_analysis_widget.set_cog_thresholds(*self.settings_widget.get_cog_thresholds())
        self.settings_widget.snr_range_changed.connect(self.link_quality_widget.set_snr_range)
        self.link_quality_widget.snr_range_changed.connect(self.settings_widget.set_snr_range)
        self.link_quality_widget.set_snr_range(*self.settings_widget.get_snr_range())
        self.settings_widget.callout_style_changed.connect(self.map_widget.set_callout_style)
        self.settings_widget.callout_fields_changed.connect(self.map_widget.set_callout_fields)
        style, show_t, show_s, show_d = self.settings_widget.get_callout_settings()
        self.map_widget.set_callout_style(style)
        self.map_widget.set_callout_fields(show_t, show_s, show_d)
        self.settings_widget.theme_changed.connect(self._on_theme_changed)
        self._on_theme_changed(self.settings_widget.current_theme())
        self.settings_widget.timezone_changed.connect(self._on_timezone_changed)
        self._on_timezone_changed(self.settings_widget.get_utc_offset())
        self.attitude_panel.set_battery_cell_count(self.settings_widget.get_battery_cell_count())
        self.attitude_panel.set_current_thresholds(*self.settings_widget.get_current_thresholds())
        self.attitude_panel.set_speed_thresholds(*self.settings_widget.get_speed_thresholds())
        self.attitude_panel.set_battery_chemistry(1, self.settings_widget.get_battery_chemistry(1))
        self.attitude_panel.set_battery_chemistry(2, self.settings_widget.get_battery_chemistry(2))

        if self._tile_handler is not None:
            self._tile_handler.cache_limit_exceeded.connect(self._on_cache_limit_exceeded)
            self.settings_widget.set_tile_handler(self._tile_handler)

        # ── Statistics ──────────────────────────────────────────────────────
        self._stat_runtime_s, self._stat_logs, self._stat_photos = self.settings_widget.load_stats()
        self._stat_session_start = __import__("time").monotonic()
        self.settings_widget.update_stats(self._stat_runtime_s, self._stat_logs, self._stat_photos)

        self._stat_timer = QTimer(self)
        self._stat_timer.setInterval(60_000)
        self._stat_timer.timeout.connect(self._on_stat_tick)
        self._stat_timer.start()

        self.photo_geotag_widget.geotagging_done.connect(self._on_geotagging_done)

        # Show changelog on first launch after update, then check for newer version
        QTimer.singleShot(500, self._check_changelog)
        QTimer.singleShot(2000, self._start_update_check)

    def _check_changelog(self):
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}
        last_seen = data.get("last_seen_version", "")
        if last_seen == APP_VERSION:
            return
        # Save current version so dialog won't show again
        data["last_seen_version"] = APP_VERSION
        try:
            _SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        # Only show if we have changelog entries for this version
        entries = CHANGELOG.get(APP_VERSION)
        if not entries:
            return
        self._show_changelog_dialog(APP_VERSION, entries)

    def _show_changelog_dialog(self, version: str, entries: list[str]):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea, QWidget, QDialogButtonBox
        from PySide6.QtCore import Qt

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Что нового в версии {version}")
        dlg.setMinimumWidth(520)

        outer = QVBoxLayout(dlg)
        outer.setSpacing(12)

        title = QLabel(f"<b style='font-size:14px'>Версия {version}</b>")
        outer.addWidget(title)

        # Build HTML list
        items_html = ""
        for entry in entries:
            # Replace **text** with <b>text</b>
            import re
            formatted = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", entry)
            items_html += f"<li style='margin-bottom:6px'>{formatted}</li>"
        html = f"<ul style='margin:0; padding-left:18px'>{items_html}</ul>"

        content = QLabel(html)
        content.setWordWrap(True)
        content.setTextFormat(Qt.TextFormat.RichText)
        content.setContentsMargins(4, 0, 4, 0)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setMaximumHeight(360)
        outer.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dlg.accept)
        outer.addWidget(buttons)

        dlg.exec()

    def _start_update_check(self):
        self._update_checker = UpdateChecker(self)
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.start()

    def _on_update_available(self, remote_tag: str, url: str):
        from app.core.version import APP_VERSION
        box = QMessageBox(self)
        box.setWindowTitle("Доступно обновление")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            f"<b>Доступна новая версия: {remote_tag}</b><br>"
            f"Текущая версия: {APP_VERSION}"
        )
        box.setInformativeText("Перейти на страницу загрузки?")
        open_btn = box.addButton("Перейти на GitHub", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Позже", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(url))

    def _on_cache_limit_exceeded(self):
        tr = i18n.tr
        box = QMessageBox(self)
        box.setWindowTitle(tr("Кэш карты"))
        box.setText(tr("Объём картографических данных превышен"))
        delete_button = box.addButton(tr("Удалить данные"), QMessageBox.AcceptRole)
        box.addButton(tr("Закрыть"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == delete_button:
            tile_cache.clear_cache()
            self.settings_widget.refresh_cache_size_label()

    def _build_layout(self):
        self.message_tree = MessageTree()
        self.message_tree.field_toggled.connect(self._on_field_toggled)
        self.message_tree.preset_activated.connect(self._on_preset_activated)

        self.open_log_button = QPushButton()
        self.open_log_button.clicked.connect(self.open_log_dialog)
        self.open_log_help_label = QLabel("?")
        self.open_log_help_label.setToolTip("")
        self.open_log_help_label.setStyleSheet(
            "QLabel { border: 1px solid gray; border-radius: 8px; padding: 0px 5px; }"
        )

        open_log_row = QHBoxLayout()
        open_log_row.addWidget(self.open_log_button)
        open_log_row.addWidget(self.open_log_help_label)
        open_log_row.addStretch()

        message_tree_panel = QWidget()
        message_tree_layout = QVBoxLayout(message_tree_panel)
        message_tree_layout.setContentsMargins(0, 0, 0, 0)
        message_tree_layout.addLayout(open_log_row)
        message_tree_layout.addWidget(self.message_tree)

        self.graphs = [GraphWidget(), GraphWidget(), GraphWidget()]
        for graph in self.graphs:
            graph.cursor_moved.connect(self._on_cursor_moved)
        self.graphs[1].plot_widget.setXLink(self.graphs[0].plot_widget)
        self.graphs[2].plot_widget.setXLink(self.graphs[0].plot_widget)

        self.target_graph_combo = QComboBox()

        graph_tab = QWidget()
        graph_tab_layout = QVBoxLayout(graph_tab)
        graph_tab_layout.setContentsMargins(4, 4, 4, 4)
        target_row = QHBoxLayout()
        self.add_param_label = QLabel()
        target_row.addWidget(self.add_param_label)
        target_row.addWidget(self.target_graph_combo)
        target_row.addStretch()
        graph_tab_layout.addLayout(target_row)
        graph_splitter = QSplitter(Qt.Vertical)
        self.graph_labels: list[QLabel] = []
        self.graph_clear_btns: list[QPushButton] = []
        self.graph_save_btns: list[QPushButton] = []
        self.graph_expand_btns: list[QPushButton] = []
        for i, graph in enumerate(self.graphs):
            wrapper = QWidget()
            wrapper_layout = QVBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            wrapper_layout.setSpacing(0)
            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel()
            self.graph_labels.append(lbl)
            header_row.addWidget(lbl)
            header_row.addStretch()
            expand_btn = QPushButton("⛶")
            expand_btn.setFixedWidth(32)
            expand_btn.setToolTip("Развернуть график в отдельном окне")
            expand_btn.clicked.connect(lambda _=False, idx=i: self._expand_graph(idx))
            self.graph_expand_btns.append(expand_btn)
            header_row.addWidget(expand_btn)
            save_btn = QPushButton("💾")
            save_btn.setFixedWidth(32)
            save_btn.setToolTip("Сохранить график как изображение")
            save_btn.clicked.connect(lambda _=False, idx=i: self._save_graph_image(idx))
            self.graph_save_btns.append(save_btn)
            header_row.addWidget(save_btn)
            clear_btn = QPushButton()
            clear_btn.setFixedWidth(110)
            clear_btn.clicked.connect(lambda _=False, idx=i: self._clear_graph(idx))
            self.graph_clear_btns.append(clear_btn)
            header_row.addWidget(clear_btn)
            wrapper_layout.addLayout(header_row)
            wrapper_layout.addWidget(graph)
            graph_splitter.addWidget(wrapper)
        graph_tab_layout.addWidget(graph_splitter)

        self.map_widget = MapWidget()
        self.map_widget.cursor_time_changed.connect(self._on_cursor_moved)

        self.timeline_widget = TimelineWidget()
        self.timeline_widget.cursor_changed.connect(self._on_cursor_moved)
        self.timeline_widget.range_changed.connect(self._on_range_changed)

        self.backplay_button = QPushButton()
        self.backplay_button.clicked.connect(self._on_backplay_clicked)
        self.play_button = QPushButton()
        self.play_button.clicked.connect(self._on_play_clicked)
        self.pause_button = QPushButton()
        self.pause_button.clicked.connect(self._on_pause_clicked)
        self.stop_button = QPushButton()
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["x0.25", "x0.5", "x1", "x2", "x4", "x10", "x20"])
        self.speed_combo.setCurrentText("x1")
        self.speed_combo.currentTextChanged.connect(self._on_speed_changed)

        self.speed_label = QLabel()
        self.basemap_type_label = QLabel()

        playback_row = QHBoxLayout()
        playback_row.addStretch()
        playback_row.addWidget(self.map_widget.show_errors_checkbox)
        playback_row.addWidget(self.map_widget.show_wind_checkbox)
        playback_row.addWidget(self.map_widget.show_photos_checkbox)
        errors_separator = QFrame()
        errors_separator.setFrameShape(QFrame.VLine)
        errors_separator.setFrameShadow(QFrame.Sunken)
        playback_row.addWidget(errors_separator)
        playback_row.addWidget(self.backplay_button)
        playback_row.addWidget(self.play_button)
        playback_row.addWidget(self.pause_button)
        playback_row.addWidget(self.stop_button)
        playback_row.addWidget(self.speed_label)
        playback_row.addWidget(self.speed_combo)
        playback_row.addSpacing(20)
        basemap_separator = QFrame()
        basemap_separator.setFrameShape(QFrame.VLine)
        basemap_separator.setFrameShadow(QFrame.Sunken)
        playback_row.addWidget(basemap_separator)
        playback_row.addWidget(self.map_widget.basemap_checkbox)
        playback_row.addWidget(self.basemap_type_label)
        playback_row.addWidget(self.map_widget.basemap_combo)
        playback_row.addSpacing(20)
        follow_separator = QFrame()
        follow_separator.setFrameShape(QFrame.VLine)
        follow_separator.setFrameShadow(QFrame.Sunken)
        playback_row.addWidget(follow_separator)
        playback_row.addWidget(self.map_widget.follow_checkbox)
        playback_row.addSpacing(20)
        photo_count_separator = QFrame()
        photo_count_separator.setFrameShape(QFrame.VLine)
        photo_count_separator.setFrameShadow(QFrame.Sunken)
        playback_row.addWidget(photo_count_separator)
        playback_row.addWidget(self.map_widget.photo_count_label)
        playback_row.addWidget(self.map_widget.photo_count_help_label)
        playback_row.addSpacing(20)
        icon_size_separator = QFrame()
        icon_size_separator.setFrameShape(QFrame.VLine)
        icon_size_separator.setFrameShadow(QFrame.Sunken)
        playback_row.addWidget(icon_size_separator)
        playback_row.addWidget(self.map_widget.icon_size_label)
        playback_row.addWidget(self.map_widget.icon_size_combo)
        playback_row.addSpacing(12)
        playback_row.addWidget(self.map_widget.measure_btn)
        playback_row.addStretch()

        map_tab = QWidget()
        map_tab_layout = QVBoxLayout(map_tab)
        map_tab_layout.setContentsMargins(0, 0, 0, 0)
        map_tab_layout.addWidget(self.map_widget, 1)
        map_tab_layout.addLayout(playback_row)
        map_tab_layout.addWidget(self.timeline_widget, 0)

        self.events_widget = EventsWidget()
        self.events_widget.time_selected.connect(self._on_cursor_moved)

        self.params_widget = ParamsWidget()
        self.settings_widget = SettingsWidget()
        self.mission_widget = MissionWidget()
        self.mission_analysis_widget = MissionAnalysisWidget()
        self.photo_geotag_widget = PhotoGeotagWidget()

        def _scroll_wrap(widget: QWidget) -> QScrollArea:
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setWidget(widget)
            return sa

        self.link_quality_widget = LinkQualityWidget()

        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(map_tab, "")
        self.right_tabs.addTab(graph_tab, "")
        self.right_tabs.addTab(_scroll_wrap(self.mission_analysis_widget), "")
        self.right_tabs.addTab(self.link_quality_widget, "")
        self.right_tabs.addTab(self.events_widget, "")
        self.right_tabs.addTab(self.params_widget, "")
        self.right_tabs.addTab(self.mission_widget, "")
        self.right_tabs.addTab(_scroll_wrap(self.photo_geotag_widget), "")
        self.right_tabs.addTab(_scroll_wrap(self.settings_widget), "")
        self.right_tabs.setCurrentIndex(0)

        i18n.register(self._retranslateUi)
        self._retranslateUi()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(message_tree_panel)
        splitter.addWidget(self.right_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self._main_splitter = splitter

        self.rc_panel = RCPanel()
        self.motor_servo_panel = MotorServoPanel()
        self.attitude_panel = AttitudePanel()

        def bottom_separator():
            frame = QFrame()
            frame.setFrameShape(QFrame.VLine)
            frame.setFrameShadow(QFrame.Sunken)
            return frame

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self.rc_panel, alignment=Qt.AlignTop)
        bottom_row.addWidget(bottom_separator())
        bottom_row.addWidget(self.motor_servo_panel, alignment=Qt.AlignTop)
        bottom_row.addWidget(bottom_separator())
        bottom_row.addWidget(self.attitude_panel, alignment=Qt.AlignTop)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        layout.addLayout(bottom_row)
        self.setCentralWidget(container)

    def _retranslateUi(self):
        tr = i18n.tr
        self.open_log_button.setText(tr("Открыть лог-файл"))
        self.open_log_help_label.setToolTip(tr("Поддерживаемые файлы: ArduPilot dataflash (*.bin, *.log), телеметрия (*.tlog)"))
        self.add_param_label.setText(
            tr("Добавить параметр в поле графика (до {n} параметров на один график):").replace("{n}", str(MAX_CURVES))
        )
        for i, lbl in enumerate(self.graph_labels):
            lbl.setText(f"{tr('График')} {i + 1}")
        for btn in self.graph_clear_btns:
            btn.setText(tr("Очистить график"))
        self.target_graph_combo.blockSignals(True)
        current_idx = self.target_graph_combo.currentIndex()
        self.target_graph_combo.clear()
        self.target_graph_combo.addItems([f"{tr('График')} {i + 1}" for i in range(len(self.graphs))])
        self.target_graph_combo.setCurrentIndex(max(0, current_idx))
        self.target_graph_combo.blockSignals(False)
        self.backplay_button.setText(tr("◀ Назад"))
        self.play_button.setText(tr("▶ Воспроизвести"))
        self.pause_button.setText(tr("⏸ Пауза"))
        self.stop_button.setText(tr("⏹ Стоп"))
        self.speed_label.setText(tr("Скорость:"))
        self.basemap_type_label.setText(tr("Тип:"))
        _tab_titles = [
            "Карта", "Графики", "Анализ миссии", "Качество связи", "События",
            "Параметры полетного контроллера", "Полетное задание",
            "Геотегирование фотографий", "Настройки",
        ]
        for i, title in enumerate(_tab_titles):
            self.right_tabs.setTabText(i, tr(title))

    def open_log_dialog(self):
        start_dir = self._load_last_log_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "Open ArduPilot Log", start_dir,
            "ArduPilot Logs (*.bin *.log *.tlog);;All Files (*)"
        )
        if path:
            self.load_log_file(path)

    def load_log_file(self, path: str):
        if self._worker is not None and self._worker.isRunning():
            return
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.statusBar().showMessage(f"Loading {path}...")

        self._worker = LogLoadWorker(path)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.finished_ok.connect(lambda log_data: self._on_log_loaded(path, log_data))
        self._worker.failed.connect(self._on_log_load_failed)
        self._worker.start()

    def _load_last_log_dir(self) -> str:
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            return data.get("last_log_dir", "")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return ""

    def _save_last_log_dir(self, path: str):
        try:
            try:
                data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                data = {}
            data["last_log_dir"] = str(Path(path).parent)
            _SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _on_log_load_failed(self, message: str):
        self.progress_bar.hide()
        self.statusBar().clearMessage()
        QMessageBox.critical(self, "Error loading log", message)

    def _on_log_loaded(self, path: str, log_data: LogData):
        self.progress_bar.hide()
        self.playback_timer.stop()
        self._save_last_log_dir(path)
        self.log_data = log_data
        self._current_time = log_data.start_time

        self.message_tree.load(self.log_data)
        self._field_graph_assignment.clear()
        for graph in self.graphs:
            graph.clear_all()
            graph.clear_selected_range()
            graph.set_time_origin(log_data.start_time)
        self.map_widget.set_time_origin(log_data.start_time)
        self.events_widget.load(self.log_data)
        self.params_widget.load(self.log_data)
        self.mission_widget.load(self.log_data)
        self.mission_analysis_widget.set_log_path(path)
        self.mission_analysis_widget.load(self.log_data)
        self.photo_geotag_widget.load(self.log_data)
        self._load_gps_track()
        self._load_flight_modes()
        self._load_error_markers()
        self._load_timeline()
        self._load_rc_panel()
        self._load_rc_graph()
        self._load_attitude_panel()
        self._load_speed_alt_gauges()
        self._load_battery_gauges()
        self._load_motor_servo_panel()
        self._load_photo_counts()
        self._load_link_quality()
        self.map_widget.set_mission(self.mission_widget.waypoints())
        self.attitude_panel.set_mission_waypoints(self.mission_widget.waypoints())
        self._load_cmd_waypoint_timeline()

        self.statusBar().showMessage(
            f"Loaded {path} — {len(self.log_data.message_types)} message types, "
            f"duration {self.log_data.end_time - self.log_data.start_time:.1f}s"
        )

        if self.settings_widget.is_sound_alerts_enabled():
            self._load_done_sound.play()

        self._stat_logs += 1
        self._on_stat_tick()

    def _load_cmd_waypoint_timeline(self):
        if self.log_data is None:
            return
        cmd = self.log_data.messages.get("CMD")
        if not cmd:
            return
        lat_key = next((k for k in ["Lat", "lat"] if k in cmd), None)
        lon_key = next((k for k in ["Lng", "Lon", "lon"] if k in cmd), None)
        if lat_key is None or lon_key is None:
            return

        # Find ARM time to skip mission-definition CMDs logged before flight
        t_arm = None
        ev = self.log_data.messages.get("EV")
        if ev and "Id" in ev:
            for i, v in enumerate(ev["Id"]):
                if int(v) == 10:
                    t_arm = ev["timestamp"][i]
                    break

        t_arr, lat_arr, lon_arr = [], [], []
        for i in range(len(cmd["timestamp"])):
            ct = cmd["timestamp"][i]
            if t_arm is not None and ct <= t_arm:
                continue
            lat = cmd[lat_key][i]
            lon = cmd[lon_key][i]
            if lat == 0 and lon == 0:
                continue
            lat_deg = lat / 1e7 if abs(lat) > 1000 else float(lat)
            lon_deg = lon / 1e7 if abs(lon) > 1000 else float(lon)
            t_arr.append(ct)
            lat_arr.append(lat_deg)
            lon_arr.append(lon_deg)

        if t_arr:
            self.attitude_panel.set_cmd_waypoint_timeline(
                np.array(t_arr), np.array(lat_arr), np.array(lon_arr)
            )

    def _load_gps_track(self):
        if self.log_data is None:
            return
        for msg_type, lat_f, lon_f in GPS_LAT_CANDIDATES:
            table = self.log_data.messages.get(msg_type)
            if table and lat_f in table and lon_f in table:
                lat = table[lat_f]
                lon = table[lon_f]
                if msg_type == "GLOBAL_POSITION_INT":
                    lat = lat / 1e7
                    lon = lon / 1e7
                spd_key = next((k for k in ("Spd", "speed", "groundspeed") if k in table), None)
                if spd_key is not None:
                    spd = table[spd_key]
                    t_gps = table["timestamp"]
                    dt = np.diff(t_gps)
                    cum_dist = np.concatenate([[0.0], np.cumsum(spd[:-1] * dt)])
                else:
                    cum_dist = None
                self.map_widget.set_track(table["timestamp"], lat, lon, cum_dist=cum_dist)
                self.attitude_panel.set_position_data(table["timestamp"], lat, lon)
                if spd_key is not None:
                    self.map_widget.set_map_speed_data(table["timestamp"], table[spd_key])
                else:
                    self.map_widget.clear_map_speed_data()
                for _msg, _fld, _div in AIRSPEED_CANDIDATES:
                    _at = self.log_data.messages.get(_msg)
                    if _at and _fld in _at and len(_at[_fld]):
                        self.map_widget.set_map_airspeed_data(_at["timestamp"], np.asarray(_at[_fld]) / _div)
                        break
                else:
                    self.map_widget.clear_map_airspeed_data()
                return

    def _load_flight_modes(self):
        if self.log_data is None:
            return
        mode_table = self.log_data.messages.get("MODE")
        if not mode_table or "Mode" not in mode_table:
            self.map_widget.set_flight_modes([])
            return
        mapping = mavutil.mode_mapping_apm or {}
        events = [
            (float(t), mapping.get(int(mode_num), f"Mode {int(mode_num)}"))
            for t, mode_num in zip(mode_table["timestamp"], mode_table["Mode"])
        ]
        self.map_widget.set_flight_modes(events)

    def _load_error_markers(self):
        if self.log_data is None:
            return
        entries: list[tuple[float, str]] = []

        ev_table = self.log_data.messages.get("EV")
        if ev_table and "Id" in ev_table:
            for t, event_id in zip(ev_table["timestamp"], ev_table["Id"]):
                entries.append((float(t), decode_event(event_id)))

        err_table = self.log_data.messages.get("ERR")
        if err_table and "Subsys" in err_table and "ECode" in err_table:
            for t, subsys, ecode in zip(err_table["timestamp"], err_table["Subsys"], err_table["ECode"]):
                entries.append((float(t), decode_error(subsys, ecode)))

        if entries:
            entries.sort(key=lambda e: e[0])
            times = np.array([t for t, _ in entries])
            positions = self.map_widget.positions_at_times(times)
            items = [
                {"lat": lat, "lon": lon, "text": f"{format_mmss(t - self.log_data.start_time)} — {text}"}
                for (t, text), (lat, lon) in zip(entries, positions)
            ]
            self.map_widget.set_error_markers(items)
        else:
            self.map_widget.set_error_markers([])

        assist_entries: list[tuple[float, str]] = []
        msg_table = self.log_data.messages.get("MSG")
        if msg_table and "Message" in msg_table:
            for t, message in zip(msg_table["timestamp"], msg_table["Message"]):
                if "assist" in str(message).lower():
                    assist_entries.append((float(t), str(message)))

        if not assist_entries:
            self.map_widget.set_assist_markers([])
            return

        assist_entries.sort(key=lambda e: e[0])
        assist_times = np.array([t for t, _ in assist_entries])
        assist_positions = self.map_widget.positions_at_times(assist_times)
        assist_items = [
            {"lat": lat, "lon": lon, "text": f"{format_mmss(t - self.log_data.start_time)} — {text}"}
            for (t, text), (lat, lon) in zip(assist_entries, assist_positions)
        ]
        self.map_widget.set_assist_markers(assist_items)

        failsafe_entries: list[tuple[float, str]] = []
        if msg_table and "Message" in msg_table:
            for t, message in zip(msg_table["timestamp"], msg_table["Message"]):
                if "failsafe" in str(message).lower():
                    failsafe_entries.append((float(t), str(message)))

        if not failsafe_entries:
            self.map_widget.set_failsafe_markers([])
            return

        failsafe_entries.sort(key=lambda e: e[0])
        failsafe_times = np.array([t for t, _ in failsafe_entries])
        failsafe_positions = self.map_widget.positions_at_times(failsafe_times)
        failsafe_items = [
            {"lat": lat, "lon": lon, "text": f"{format_mmss(t - self.log_data.start_time)} — {text}"}
            for (t, text), (lat, lon) in zip(failsafe_entries, failsafe_positions)
        ]
        self.map_widget.set_failsafe_markers(failsafe_items)

    def _load_photo_counts(self):
        if self.log_data is None:
            return
        cam_table = self.log_data.messages.get("CAM")
        trig_table = self.log_data.messages.get("TRIG")
        cam_count = len(cam_table["timestamp"]) if cam_table else 0
        trig_count = len(trig_table["timestamp"]) if trig_table else 0
        self.map_widget.set_photo_counts(cam_count, trig_count)
        self.map_widget.set_cam_markers(self._marker_positions(cam_table))
        self.map_widget.set_trig_markers(self._marker_positions(trig_table))

    def _marker_positions(self, table: dict[str, np.ndarray] | None) -> list[tuple[float, float]]:
        if not table:
            return []
        if "Lat" in table and "Lng" in table:
            return list(zip(table["Lat"].tolist(), table["Lng"].tolist()))
        return self.map_widget.positions_at_times(table["timestamp"])

    def _load_timeline(self):
        if self.log_data is None:
            return
        backdrop_t = backdrop_y = None
        for msg_type, field_name in ALT_CANDIDATES:
            table = self.log_data.messages.get(msg_type)
            if table and field_name in table:
                backdrop_t = table["timestamp"]
                backdrop_y = table[field_name]
                break

        terrain_t = terrain_y = None
        terr_table = self.log_data.messages.get("TERR")
        if terr_table and "TerrH" in terr_table and backdrop_t is not None and len(backdrop_t):
            terr_interp = np.interp(backdrop_t, terr_table["timestamp"], terr_table["TerrH"])
            offset = float(backdrop_y[0]) - float(terr_interp[0])
            terrain_t = backdrop_t
            terrain_y = terr_interp + offset

        self.timeline_widget.set_range(
            self.log_data.start_time, self.log_data.end_time, backdrop_t, backdrop_y, terrain_t, terrain_y
        )

    def _load_link_quality(self):
        if self.log_data is None:
            self.link_quality_widget.clear()
            return

        # Find GPS track
        gps_t = gps_lat = gps_lon = None
        for msg_type, lat_f, lon_f in GPS_LAT_CANDIDATES:
            table = self.log_data.messages.get(msg_type)
            if table and lat_f in table and lon_f in table:
                lat = np.asarray(table[lat_f], dtype=float)
                lon = np.asarray(table[lon_f], dtype=float)
                if msg_type == "GLOBAL_POSITION_INT":
                    lat /= 1e7
                    lon /= 1e7
                gps_t = np.asarray(table["timestamp"], dtype=float)
                gps_lat, gps_lon = lat, lon
                break

        if gps_t is None or len(gps_t) < 2:
            self.link_quality_widget.clear()
            return

        # Prefer RAD/RADIO message — contains noise fields for SNR calculation
        radio = self.log_data.messages.get("RAD") or self.log_data.messages.get("RADIO")
        if radio and all(f in radio for f in ("RSSI", "Noise", "RemRSSI", "RemNoise")):
            rssi_v = np.asarray(radio["RSSI"], dtype=float)
            if len(rssi_v):
                rssi_t     = np.asarray(radio["timestamp"], dtype=float)
                noise_v    = np.asarray(radio["Noise"],    dtype=float)
                remrssi_v  = np.asarray(radio["RemRSSI"],  dtype=float)
                remnoise_v = np.asarray(radio["RemNoise"], dtype=float)
                raw_max = float(rssi_v.max())
                rssi_max = 100.0 if raw_max <= 100.0 else 255.0
                self.link_quality_widget.load(
                    gps_t, gps_lat, gps_lon,
                    rssi_t, rssi_v, noise_v, remrssi_v, remnoise_v,
                    rssi_max, "RSSI (радиомодем SiK)"
                )
                return

        # Fallback: other RSSI sources without noise data
        for msg_type, rssi_field, label in RSSI_CANDIDATES:
            if msg_type in ("RADIO", "RAD"):
                continue
            table = self.log_data.messages.get(msg_type)
            if table and rssi_field in table:
                rssi_v = np.asarray(table[rssi_field], dtype=float)
                if not len(rssi_v):
                    continue
                rssi_t = np.asarray(table["timestamp"], dtype=float)
                raw_max = float(rssi_v.max())
                rssi_max = 100.0 if raw_max <= 100.0 else 255.0
                self.link_quality_widget.load(
                    gps_t, gps_lat, gps_lon,
                    rssi_t, rssi_v, None, None, None,
                    rssi_max, label
                )
                return

        self.link_quality_widget.clear()

    def _load_rc_panel(self):
        if self.log_data is None:
            return
        for msg_type, c1_f, c2_f, c3_f, c4_f in RC_CANDIDATES:
            table = self.log_data.messages.get(msg_type)
            if table and all(f in table for f in (c1_f, c2_f, c3_f, c4_f)):
                self.rc_panel.set_data(
                    table["timestamp"], table[c1_f], table[c2_f], table[c3_f], table[c4_f]
                )
                return
        self.rc_panel.clear_data()

    def _load_rc_graph(self):
        if self.log_data is None:
            return
        for msg_type, c1_f, c2_f, c3_f, c4_f in RC_CANDIDATES:
            table = self.log_data.messages.get(msg_type)
            if table and all(f in table for f in (c1_f, c2_f, c3_f, c4_f)):
                prev_idx = self.target_graph_combo.currentIndex()
                self.target_graph_combo.setCurrentIndex(len(self.graphs) - 1)
                for field_name in (c1_f, c2_f, c3_f, c4_f):
                    self.message_tree.set_field_checked(msg_type, field_name, True)
                self.target_graph_combo.setCurrentIndex(prev_idx)
                return

    def _load_attitude_panel(self):
        if self.log_data is None:
            return
        for msg_type, roll_f, pitch_f, yaw_f, is_radians in ATTITUDE_CANDIDATES:
            table = self.log_data.messages.get(msg_type)
            if table and all(f in table for f in (roll_f, pitch_f, yaw_f)):
                roll, pitch, yaw = table[roll_f], table[pitch_f], table[yaw_f]
                if is_radians:
                    roll, pitch, yaw = np.degrees(roll), np.degrees(pitch), np.degrees(yaw)
                yaw = np.mod(yaw, 360.0)
                self.attitude_panel.set_data(table["timestamp"], roll, pitch, yaw)
                self.map_widget.set_heading_data(table["timestamp"], yaw)
                return
        self.attitude_panel.clear_data()
        self.map_widget.clear_heading_data()

    def _load_speed_alt_gauges(self):
        if self.log_data is None:
            return
        for msg_type, field, divisor in AIRSPEED_CANDIDATES:
            table = self.log_data.messages.get(msg_type)
            if table and field in table:
                self.attitude_panel.set_speed_data(table["timestamp"], table[field] / divisor)
                break
        else:
            self.attitude_panel.clear_speed_data()

        for msg_type, field, divisor in GROUND_SPEED_CANDIDATES:
            table = self.log_data.messages.get(msg_type)
            if table and field in table:
                self.attitude_panel.set_ground_speed_data(table["timestamp"], table[field] / divisor)
                break
        else:
            self.attitude_panel.clear_ground_speed_data()

        for msg_type, field, divisor in ALT_GAUGE_CANDIDATES:
            table = self.log_data.messages.get(msg_type)
            if table and field in table:
                self.attitude_panel.set_altitude_data(table["timestamp"], table[field] / divisor)
                break
        else:
            self.attitude_panel.clear_altitude_data()

        for msg_type, field, invert in VSPEED_CANDIDATES:
            table = self.log_data.messages.get(msg_type)
            if table and field in table:
                vals = np.asarray(table[field], dtype=float)
                if invert:
                    vals = -vals
                self.attitude_panel.set_vspeed_data(np.asarray(table["timestamp"], dtype=float), vals)
                break
        else:
            self.attitude_panel.clear_vspeed_data()

        for msg_type, north_f, east_f in WIND_CANDIDATES:
            table = self.log_data.messages.get(msg_type)
            if table and north_f in table and east_f in table:
                vwn, vwe = table[north_f], table[east_f]
                direction = (np.degrees(np.arctan2(vwe, vwn)) + 180.0) % 360.0
                speed = np.hypot(vwn, vwe)
                self.attitude_panel.set_wind_data(table["timestamp"], direction, speed)
                self.map_widget.set_wind_data(table["timestamp"], speed, direction)
                break
        else:
            self.attitude_panel.clear_wind_data()
            self.map_widget.set_wind_speed_data(np.array([]), np.array([]))

    def _load_battery_gauges(self):
        if self.log_data is None:
            return
        bat_table = self.log_data.messages.get("BAT")
        bat2_table = self.log_data.messages.get("BAT2")

        bat1 = _battery_by_instance(bat_table, 0)
        if bat1 is not None:
            self.attitude_panel.set_battery_data(1, *bat1)
        else:
            self.attitude_panel.clear_battery_data(1)

        bat2 = _battery_by_instance(bat_table, 1)
        if bat2 is None and bat2_table and "Volt" in bat2_table and "Curr" in bat2_table:
            bat2 = (bat2_table["timestamp"], bat2_table["Volt"], bat2_table["Curr"])
        if bat2 is not None:
            self.attitude_panel.set_battery_data(2, *bat2)
        else:
            self.attitude_panel.clear_battery_data(2)

    def _load_motor_servo_panel(self):
        if self.log_data is None:
            return
        rcou_table = self.log_data.messages.get("RCOU")
        param_map = {p["name"]: p["value"] for p in self.log_data.parameters()}

        channel_for_function: dict[str, int] = {}
        for ch in range(1, 15):
            func_val = param_map.get(f"SERVO{ch}_FUNCTION")
            if func_val is None:
                continue
            for label, fid in SERVO_FUNCTION_IDS.items():
                if label not in channel_for_function and int(func_val) == fid:
                    channel_for_function[label] = ch

        for label in ("Aileron", "Elevator", "Rudder", "Throttle", "Motor1", "Motor2", "Motor3", "Motor4"):
            ch = channel_for_function.get(label)
            field = f"C{ch}" if ch else None
            if rcou_table and field and field in rcou_table:
                self.motor_servo_panel.set_pwm_series(label, rcou_table["timestamp"], rcou_table[field])
            else:
                self.motor_servo_panel.clear_series(label)

        # A-tail (V-tail) airframe: elevator/rudder are mixed across two ruddervator
        # channels. On this airframe the SERVOx_FUNCTION labels are mounted swapped
        # (VTailLeft is physically on the right and vice versa), so the physically-left
        # surface is the channel labeled VTailRight, and physically-right is VTailLeft.
        vleft_ch = channel_for_function.get("VTailRight")
        vright_ch = channel_for_function.get("VTailLeft")
        if rcou_table and vleft_ch and vright_ch:
            left_field, right_field = f"C{vleft_ch}", f"C{vright_ch}"
            if left_field in rcou_table and right_field in rcou_table and "Elevator" not in channel_for_function \
                    and "Rudder" not in channel_for_function:
                t = rcou_table["timestamp"]
                left_pwm = rcou_table[left_field]
                right_pwm = rcou_table[right_field]
                elevator_pwm = 1500.0 + ((left_pwm - 1500.0) + (right_pwm - 1500.0)) / 2.0
                rudder_pwm = 1500.0 + ((left_pwm - 1500.0) - (right_pwm - 1500.0)) / 2.0
                self.motor_servo_panel.set_pwm_series("Elevator", t, elevator_pwm)
                self.motor_servo_panel.set_pwm_series("Rudder", t, rudder_pwm)
                self.motor_servo_panel.set_surface_calibration(
                    "Elevator", 1500.0, float(np.min(elevator_pwm)), float(np.max(elevator_pwm))
                )
                self.motor_servo_panel.set_surface_calibration(
                    "Rudder", 1500.0, float(np.min(rudder_pwm)), float(np.max(rudder_pwm))
                )

        for label in ("Aileron", "Elevator", "Rudder"):
            ch = channel_for_function.get(label)
            if ch and rcou_table and f"C{ch}" in rcou_table:
                trim = float(param_map.get(f"SERVO{ch}_TRIM", 1500.0))
                pwm_arr = rcou_table[f"C{ch}"]
                self.motor_servo_panel.set_surface_calibration(
                    label, trim, float(np.min(pwm_arr)), float(np.max(pwm_arr))
                )

        has_4_motors = all(k in channel_for_function for k in ("Motor1", "Motor2", "Motor3", "Motor4"))
        has_2_motors = (
            "Motor1" in channel_for_function and "Motor2" in channel_for_function
            and "Motor3" not in channel_for_function and "Motor4" not in channel_for_function
        )
        has_throttle = "Throttle" in channel_for_function
        has_vtail = "VTailLeft" in channel_for_function and "VTailRight" in channel_for_function
        if has_4_motors and has_throttle and has_vtail:
            vehicle_type = "VTOL 4+1"
        elif has_2_motors and has_throttle:
            vehicle_type = "VTOL 2+1 vector"
        elif has_4_motors:
            vehicle_type = "Коптер"
        else:
            vehicle_type = "Неизвестен"
        self.attitude_panel.set_vehicle_type(vehicle_type)
        self.map_widget.set_vehicle_type(vehicle_type)

    def _expand_graph(self, graph_idx: int):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QSizePolicy, QPushButton
        from app.ui.graph_widget import GraphWidget

        src = self.graphs[graph_idx]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"График {graph_idx + 1}")
        dlg.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Toolbar: save button + hint
        toolbar = QHBoxLayout()
        hint = QLabel("ЛКМ — закрепить значение  |  ПКМ — удалить метки")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        toolbar.addWidget(hint)
        toolbar.addStretch()
        save_btn = QPushButton("💾 Сохранить")
        save_btn.setFixedWidth(120)

        def _save_popup():
            path, _ = QFileDialog.getSaveFileName(
                dlg, "Сохранить график", "", "PNG (*.png);;JPEG (*.jpg *.jpeg)"
            )
            if path:
                popup_graph.grab().save(path)

        save_btn.clicked.connect(_save_popup)
        toolbar.addWidget(save_btn)
        layout.addLayout(toolbar)

        popup_graph = GraphWidget()
        popup_graph.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Correct time origin for mm:ss axis
        if hasattr(src, "time_axis"):
            popup_graph.set_time_origin(src.time_axis.t0)

        for key, t_arr in src._curve_t.items():
            y_arr = src._curve_y[key]
            label = src._curve_label.get(key, key)
            popup_graph.add_curve(key, t_arr, y_arr, label)

        if hasattr(src, "_last_cursor_t") and src._last_cursor_t:
            popup_graph.set_cursor_time(src._last_cursor_t)

        popup_graph.enable_pin_mode()
        popup_graph.cursor_moved.connect(self._on_cursor_moved)

        layout.addWidget(popup_graph)
        dlg.showMaximized()
        dlg.exec()

    def _save_graph_image(self, graph_idx: int):
        from PySide6.QtGui import QPixmap
        path, _ = QFileDialog.getSaveFileName(
            self, f"Сохранить график {graph_idx + 1}",
            f"graph_{graph_idx + 1}.png",
            "PNG изображение (*.png);;JPEG (*.jpg *.jpeg);;Все файлы (*)",
        )
        if not path:
            return
        graph = self.graphs[graph_idx]
        pixmap = graph.grab()
        if not pixmap.save(path):
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить файл:\n{path}")

    def _clear_graph(self, graph_idx: int):
        keys = [k for k, v in list(self._field_graph_assignment.items()) if v == graph_idx]
        for key in keys:
            msg_type, field_name = key.split(".", 1)
            self.message_tree.set_field_checked(msg_type, field_name, False)
        self.graphs[graph_idx].clear_all()

    def _on_field_toggled(self, msg_type: str, field_name: str, checked: bool):
        key = f"{msg_type}.{field_name}"
        if checked:
            if self.log_data is None:
                return
            idx = self.target_graph_combo.currentIndex()
            graph = self.graphs[idx]
            t, y = self.log_data.series(msg_type, field_name)
            if graph.add_curve(key, t, y, key):
                self._field_graph_assignment[key] = idx
            else:
                QMessageBox.warning(
                    self, "График заполнен",
                    f"В графике {idx + 1} уже максимум параметров ({MAX_CURVES}). "
                    f"Удалите один из них или выберите другой график."
                )
                self.message_tree.set_field_checked(msg_type, field_name, False)
        else:
            idx = self._field_graph_assignment.pop(key, None)
            if idx is not None:
                self.graphs[idx].remove_curve(key)

    def _on_preset_activated(self, preset_id: str):
        if self.log_data is None:
            return
        if preset_id == "airspeed_ground_speed":
            for candidates in (AIRSPEED_CANDIDATES, GROUND_SPEED_CANDIDATES):
                for msg_type, field, _ in candidates:
                    table = self.log_data.messages.get(msg_type)
                    if table and field in table:
                        self.message_tree.set_field_checked(msg_type, field, True)
                        break
        elif preset_id == "baro_vs_gps_altitude":
            for msg_type, field in BARO_GPS_ALT_CANDIDATES:
                table = self.log_data.messages.get(msg_type)
                if table and field in table:
                    self.message_tree.set_field_checked(msg_type, field, True)
        elif preset_id == "battery1_vs_battery2":
            self._apply_battery_preset()
        elif preset_id == "center_of_gravity":
            table = self.log_data.messages.get("PIDP")
            if table and "I" in table:
                self.message_tree.set_field_checked("PIDP", "I", True)
        elif preset_id == "ctun_qtun_tho":
            self._apply_ctun_qtun_tho_preset()
        elif preset_id == "gps1_vs_gps2":
            self._apply_gps_preset()

    def _apply_gps_preset(self):
        gps_table = self.log_data.messages.get("GPS")
        gps2_table = self.log_data.messages.get("GPS2")

        gps1 = _gps_by_instance(gps_table, 0)
        gps2 = _gps_by_instance(gps_table, 1)
        if gps2 is None and gps2_table and "NSats" in gps2_table and "HDop" in gps2_table:
            gps2 = (gps2_table["timestamp"], gps2_table["NSats"], gps2_table["HDop"])

        curves = []
        if gps1 is not None:
            t, nsats, hdop = gps1
            curves.append(("GPS1.NSats", t, nsats, "GPS 1: спутники"))
            curves.append(("GPS1.HDop", t, hdop, "GPS 1: HDOP"))
        if gps2 is not None:
            t, nsats, hdop = gps2
            curves.append(("GPS2.NSats", t, nsats, "GPS 2: спутники"))
            curves.append(("GPS2.HDop", t, hdop, "GPS 2: HDOP"))
        if not curves:
            return

        idx = self.target_graph_combo.currentIndex()
        graph = self.graphs[idx]
        for key, t, y, label in curves:
            if graph.add_curve(key, t, y, label):
                self._field_graph_assignment[key] = idx
            else:
                QMessageBox.warning(
                    self, "График заполнен",
                    f"В графике {idx + 1} уже максимум параметров ({MAX_CURVES}). "
                    f"Удалите один из них или выберите другой график."
                )
                break

    def _apply_battery_preset(self):
        bat_table = self.log_data.messages.get("BAT")
        bat2_table = self.log_data.messages.get("BAT2")

        bat1 = _battery_by_instance(bat_table, 0)
        bat2 = _battery_by_instance(bat_table, 1)
        if bat2 is None and bat2_table and "Volt" in bat2_table and "Curr" in bat2_table:
            bat2 = (bat2_table["timestamp"], bat2_table["Volt"], bat2_table["Curr"])

        curves = []
        if bat1 is not None:
            t, volt, curr = bat1
            curves.append(("BAT1.Volt", t, volt, "Батарея 1: напряжение"))
            curves.append(("BAT1.Curr", t, curr, "Батарея 1: ток"))
        if bat2 is not None:
            t, volt, curr = bat2
            curves.append(("BAT2.Volt", t, volt, "Батарея 2: напряжение"))
            curves.append(("BAT2.Curr", t, curr, "Батарея 2: ток"))
        if not curves:
            return

        idx = self.target_graph_combo.currentIndex()
        graph = self.graphs[idx]
        for key, t, y, label in curves:
            if graph.add_curve(key, t, y, label):
                self._field_graph_assignment[key] = idx
            else:
                QMessageBox.warning(
                    self, "График заполнен",
                    f"В графике {idx + 1} уже максимум параметров ({MAX_CURVES}). "
                    f"Удалите один из них или выберите другой график."
                )
                break

    def _apply_ctun_qtun_tho_preset(self):
        curves = []
        for msg_type, field, label in (
            ("CTUN", "ThO", "CTUN.ThO"),
            ("QTUN", "ThO", "QTUN.ThO"),
        ):
            table = self.log_data.messages.get(msg_type)
            if table and field in table:
                curves.append((
                    f"{msg_type}.{field}",
                    np.asarray(table["timestamp"], dtype=float),
                    np.asarray(table[field], dtype=float),
                    label,
                ))
        if not curves:
            QMessageBox.information(self, "Пресет", "Данные CTUN.ThO / QTUN.ThO не найдены в логе.")
            return
        idx = self.target_graph_combo.currentIndex()
        graph = self.graphs[idx]
        for key, t, y, label in curves:
            if graph.add_curve(key, t, y, label):
                self._field_graph_assignment[key] = idx
            else:
                QMessageBox.warning(
                    self, "График заполнен",
                    f"В графике {idx + 1} уже максимум параметров ({MAX_CURVES}). "
                    f"Удалите один из них или выберите другой график."
                )
                break

    def _on_stat_tick(self):
        import time as _time
        elapsed = _time.monotonic() - self._stat_session_start
        current_total = self._stat_runtime_s + elapsed
        self.settings_widget.update_stats(current_total, self._stat_logs, self._stat_photos)
        self.settings_widget.save_stats(current_total, self._stat_logs, self._stat_photos)

    def _on_geotagging_done(self, count: int):
        self._stat_photos += count
        self._on_stat_tick()

    def closeEvent(self, event):
        self._on_stat_tick()
        super().closeEvent(event)

    def _on_cursor_moved(self, t: float):
        self._current_time = t
        for graph in self.graphs:
            graph.set_cursor_time(t)
        self.map_widget.set_cursor_time(t)
        self.timeline_widget.set_cursor_time(t)
        self.rc_panel.set_cursor_time(t)
        self.attitude_panel.set_cursor_time(t)
        self.motor_servo_panel.set_cursor_time(t)

    def _on_play_clicked(self):
        if self.log_data is None:
            return
        self._playback_reverse = False
        if self._current_time >= self.log_data.end_time:
            self._current_time = self.log_data.start_time
        self.playback_timer.start()

    def _on_backplay_clicked(self):
        if self.log_data is None:
            return
        self._playback_reverse = True
        if self._current_time <= self.log_data.start_time:
            self._current_time = self.log_data.end_time
        self.playback_timer.start()

    def _on_pause_clicked(self):
        self.playback_timer.stop()

    def _on_stop_clicked(self):
        self.playback_timer.stop()
        if self.log_data is not None:
            self._current_time = self.log_data.start_time
            self._on_cursor_moved(self._current_time)
            self.timeline_widget.set_cursor_time(self._current_time)

    def _on_speed_changed(self, text: str):
        self._playback_speed = float(text.lstrip("x"))

    def _on_playback_tick(self):
        if self.log_data is None:
            self.playback_timer.stop()
            return
        dt = (self.playback_timer.interval() / 1000.0) * self._playback_speed
        if self._playback_reverse:
            self._current_time -= dt
            if self._current_time <= self.log_data.start_time:
                self._current_time = self.log_data.start_time
                self.playback_timer.stop()
        else:
            self._current_time += dt
            if self._current_time >= self.log_data.end_time:
                self._current_time = self.log_data.end_time
                self.playback_timer.stop()
        self._on_cursor_moved(self._current_time)
        self.timeline_widget.set_cursor_time(self._current_time)

    def _on_range_changed(self, t0: float, t1: float):
        for graph in self.graphs:
            graph.set_selected_range(t0, t1)
        self.map_widget.highlight_range(t0, t1)

    def _on_timezone_changed(self, offset_hours: float):
        set_utc_offset_hours(offset_hours)
        if self.log_data is not None:
            self.events_widget.load(self.log_data)
            self.mission_analysis_widget.load(self.log_data)
            self.photo_geotag_widget.load(self.log_data)

    def _on_theme_changed(self, theme: str):
        app = QApplication.instance()
        if theme == "dark":
            apply_dark_theme(app)
        elif theme == "light":
            apply_light_theme(app)
        else:
            apply_system_theme(app)
