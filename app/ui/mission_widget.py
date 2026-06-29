"""Table of mission waypoints/commands extracted from the log (CMD / MISSION_ITEM).

Each command id is decoded against the ArduPilot/MAVLink MAV_CMD enum so the
purpose of every mission point is shown in plain text. The mission can also
be exported as a standard ArduPilot/Mission Planner ".waypoints" file
(QGC WPL 110 format).

The tab is split into a small map on the left (showing the mission route)
and the points table on the right; hovering a row highlights the matching
marker on the map and vice versa.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal, QObject, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QFileDialog, QMessageBox, QSplitter, QCheckBox
)
from pymavlink import mavutil

from app.core.log_loader import LogData

_LAT_FIELDS = ["Lat", "lat", "x"]
_LON_FIELDS = ["Lng", "Lon", "lon", "y"]
_COLUMNS = ["Command", "Lat", "Lng", "Alt", "Frame", "Params", "Seq", "Cmd ID", "Description"]

_MAV_CMD = mavutil.mavlink.enums.get("MAV_CMD", {})

_CMD_DESCRIPTIONS_RU = {
    "NAV_WAYPOINT": "Лететь к путевой точке.",
    "NAV_LOITER_UNLIM": "Кружить в точке неограниченное время.",
    "NAV_LOITER_TURNS": "Кружить в точке заданное число витков.",
    "NAV_LOITER_TIME": "Кружить в точке заданное время.",
    "NAV_RETURN_TO_LAUNCH": "Вернуться на точку старта (RTL).",
    "NAV_LAND": "Посадка в указанной точке.",
    "NAV_TAKEOFF": "Взлёт с текущей позиции.",
    "NAV_LAND_LOCAL": "Посадка в локальных координатах.",
    "NAV_TAKEOFF_LOCAL": "Взлёт в локальных координатах.",
    "NAV_FOLLOW": "Следовать за целью.",
    "NAV_CONTINUE_AND_CHANGE_ALT": "Продолжить полёт с изменением высоты.",
    "NAV_LOITER_TO_ALT": "Кружить в точке до набора заданной высоты.",
    "DO_FOLLOW": "Следовать за другим аппаратом.",
    "DO_FOLLOW_REPOSITION": "Изменить смещение при следовании.",
    "NAV_ROI": "Удерживать точку интереса (ROI).",
    "NAV_PATHPLANNING": "Построение маршрута.",
    "NAV_SPLINE_WAYPOINT": "Лететь к путевой точке по сплайну.",
    "NAV_VTOL_TAKEOFF": "Взлёт VTOL с переходом в самолётный режим.",
    "NAV_VTOL_LAND": "Посадка в режиме VTOL.",
    "NAV_GUIDED_ENABLE": "Включить управляемый режим (Guided).",
    "NAV_DELAY": "Задержка перед продолжением миссии.",
    "NAV_PAYLOAD_PLACE": "Доставить груз в указанной точке.",
    "NAV_LAST": "Последняя команда навигации (маркер).",
    "DO_LAND_START": "Маркер начала последовательности посадки.",
    "DO_JUMP": "Перейти к другому пункту миссии.",
    "DO_CHANGE_SPEED": "Изменить скорость полёта.",
    "DO_SET_HOME": "Установить точку дома.",
    "DO_SET_PARAMETER": "Установить значение параметра.",
    "DO_SET_RELAY": "Установить состояние реле.",
    "DO_REPEAT_RELAY": "Циклически переключать реле.",
    "DO_SET_SERVO": "Установить положение сервопривода.",
    "DO_REPEAT_SERVO": "Циклически двигать сервопривод.",
    "DO_FLIGHTTERMINATION": "Аварийное завершение полёта.",
    "DO_CHANGE_ALTITUDE": "Изменить высоту полёта.",
    "DO_SET_ACTUATOR": "Установить значение актуатора.",
    "DO_RETURN_PATH_START": "Маркер начала обратного маршрута.",
    "DO_GO_AROUND": "Прервать посадку, уйти на второй круг.",
    "DO_REPOSITION": "Перелететь в новую позицию.",
    "DO_PAUSE_CONTINUE": "Приостановить/продолжить миссию.",
    "DO_SET_REVERSE": "Включить/выключить реверс.",
    "DO_SET_ROI_LOCATION": "Указать точку интереса по координатам.",
    "DO_SET_ROI_WPNEXT_OFFSET": "Указать точку интереса со смещением от следующей точки.",
    "DO_SET_ROI_NONE": "Отключить точку интереса.",
    "DO_SET_ROI_SYSID": "Указать точку интереса по ID системы.",
    "DO_CONTROL_VIDEO": "Управление видеозаписью.",
    "DO_SET_ROI": "Установить точку интереса.",
    "DO_DIGICAM_CONFIGURE": "Настроить параметры фотокамеры.",
    "DO_DIGICAM_CONTROL": "Управление фотокамерой (спуск затвора).",
    "DO_MOUNT_CONFIGURE": "Настроить подвес камеры.",
    "DO_MOUNT_CONTROL": "Управление подвесом камеры.",
    "DO_SET_CAM_TRIGG_DIST": "Установить дистанцию между фотографиями.",
    "DO_FENCE_ENABLE": "Включить/выключить геозону (Fence).",
    "DO_PARACHUTE": "Управление парашютом.",
    "DO_MOTOR_TEST": "Тест мотора.",
    "DO_INVERTED_FLIGHT": "Включить/выключить полёт вверх ногами.",
    "DO_GRIPPER": "Управление захватом (Gripper).",
    "DO_AUTOTUNE_ENABLE": "Включить/выключить автонастройку.",
    "DO_VTOL_TRANSITION": "Переход VTOL между режимами полёта.",
    "DO_ENGINE_CONTROL": "Управление двигателем.",
    "DO_SET_MISSION_CURRENT": "Установить текущий пункт миссии.",
    "DO_LAST": "Маркер конца команд DO.",
    "DO_WINCH": "Управление лебёдкой.",
    "DO_AUX_FUNCTION": "Выполнить вспомогательную функцию.",
    "CONDITION_DELAY": "Условие: задержка по времени.",
    "CONDITION_CHANGE_ALT": "Условие: изменение высоты.",
    "CONDITION_DISTANCE": "Условие: дистанция до точки.",
    "CONDITION_YAW": "Условие: целевой курс (yaw).",
    "CONDITION_LAST": "Маркер конца условных команд.",
}


_ROW_HIGHLIGHT_COLORS = {
    "NAV_VTOL_TAKEOFF": (QColor("#1f7a1f"), QColor("#ffffff")),
    "NAV_VTOL_LAND": (QColor("#1f7a1f"), QColor("#ffffff")),
    "DO_SET_CAM_TRIGG_DIST": (QColor("#7a7a1f"), QColor("#ffffff")),
    "DO_LAND_START": (QColor("#7a1f1f"), QColor("#ffffff")),
    "NAV_LOITER_TO_ALT": (QColor("#b35900"), QColor("#ffffff")),
}


def _first_present(row: dict, names: list[str], default=None):
    for n in names:
        if n in row:
            return row[n]
    return default


def describe_command(cmd_id) -> tuple[str, str]:
    try:
        entry = _MAV_CMD[int(cmd_id)]
    except (KeyError, ValueError, TypeError):
        return "Unknown", ""
    name = entry.name.replace("MAV_CMD_", "")
    description = _CMD_DESCRIPTIONS_RU.get(name)
    if description is None:
        description = (entry.description or "").split("\n")[0].strip()
    return name, description


class _MissionMapBridge(QObject):
    """JavaScript bridge to receive marker hover events from the mini map."""
    marker_hovered = Signal(int)

    @Slot(int)
    def onMarkerHovered(self, index: int):
        self.marker_hovered.emit(index)


_MISSION_MAP_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
html,body,#map{height:100%;margin:0;padding:0;background:#222;}
</style>
</head>
<body>
<div id="map"></div>
<script>
var map = L.map('map', {zoomSnap: 0, attributionControl: false}).setView([0, 0], 2);
L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', {
    subdomains: ['mt0', 'mt1', 'mt2', 'mt3'],
    maxZoom: 21
}).addTo(map);

var missionLine = L.polyline([], {color: '#00e5ff', weight: 2, dashArray: '6,6'}).addTo(map);
var markers = [];
var highlightedIndex = -1;
var followEnabled = false;

var pybridge = null;
if (typeof QWebChannel !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function(channel) {
        pybridge = channel.objects.pybridge;
    });
}
function notifyHover(idx) {
    if (pybridge) pybridge.onMarkerHovered(idx);
}

function setMission(coords) {
    missionLine.setLatLngs(coords);
    markers.forEach(function(m) { m.remove(); });
    markers = [];
    highlightedIndex = -1;
    coords.forEach(function(c, i) {
        var m = L.circleMarker(c, {radius: 6, color: '#00e5ff', weight: 2, fillColor: '#003344', fillOpacity: 1})
            .bindTooltip('WP ' + i)
            .addTo(map);
        m.on('mouseover', function() { notifyHover(i); });
        m.on('mouseout', function() { notifyHover(-1); });
        markers.push(m);
    });
    if (coords.length > 0) {
        map.fitBounds(missionLine.getBounds(), {padding: [30, 30]});
    }
}

function fitAll() {
    if (markers.length > 0) {
        map.fitBounds(missionLine.getBounds(), {padding: [30, 30]});
    }
}

function setFollow(enabled) {
    followEnabled = enabled;
}

function highlightPoint(idx) {
    if (highlightedIndex >= 0 && highlightedIndex < markers.length) {
        markers[highlightedIndex].setStyle({radius: 6, color: '#00e5ff', fillColor: '#003344'});
    }
    highlightedIndex = idx;
    if (idx >= 0 && idx < markers.length) {
        markers[idx].setStyle({radius: 10, color: '#ffeb3b', fillColor: '#ffeb3b'});
        markers[idx].bringToFront();
        if (followEnabled) {
            map.panTo(markers[idx].getLatLng(), {animate: true});
        }
    }
}
</script>
</body></html>
"""


class _MissionMapWidget(QWidget):
    marker_hovered = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWebEngineView()
        self._ready = False
        self._pending_js: list[str] = []

        self._bridge = _MissionMapBridge()
        self._bridge.marker_hovered.connect(self.marker_hovered)

        channel = QWebChannel(self.view.page())
        channel.registerObject("pybridge", self._bridge)
        self.view.page().setWebChannel(channel)

        self.view.loadFinished.connect(self._on_load_finished)
        self.view.setHtml(_MISSION_MAP_HTML, QUrl("https://maps.google.com/"))

        self.center_checkbox = QCheckBox("Центрировать")
        self.center_checkbox.toggled.connect(self.set_follow)
        self.center_checkbox.setChecked(True)

        self.fit_checkbox = QCheckBox("Показать весь трек")
        self.fit_checkbox.setChecked(True)
        self.fit_checkbox.toggled.connect(self._on_fit_toggled)

        controls = QHBoxLayout()
        controls.addWidget(self.center_checkbox)
        controls.addWidget(self.fit_checkbox)
        controls.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        layout.addLayout(controls)

    def _on_load_finished(self, ok: bool):
        self._ready = ok
        for script in self._pending_js:
            self.view.page().runJavaScript(script)
        self._pending_js.clear()

    def _run_js(self, script: str):
        if self._ready:
            self.view.page().runJavaScript(script)
        else:
            self._pending_js.append(script)

    def set_mission(self, coords: list[tuple[float, float]]):
        self._run_js(f"setMission({json.dumps(coords)});")
        if self.fit_checkbox.isChecked():
            self._run_js("fitAll();")

    def highlight_point(self, index: int):
        self._run_js(f"highlightPoint({index});")

    def set_follow(self, enabled: bool):
        self._run_js(f"setFollow({'true' if enabled else 'false'});")

    def _on_fit_toggled(self, checked: bool):
        if checked:
            self._run_js("fitAll();")


class MissionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._waypoints: list[tuple[float, float]] = []
        self._export_rows: list[dict] = []
        self._row_to_marker: dict[int, int] = {}
        self._marker_to_row: dict[int, int] = {}
        self._highlighted_row = -1

        self.download_button = QPushButton("Download Mission (.waypoints)")
        self.download_button.clicked.connect(self._on_download_clicked)

        self.map = _MissionMapWidget()
        self.map.marker_hovered.connect(self._on_marker_hovered)

        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(True)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.cellEntered.connect(self._on_table_cell_entered)
        self.table.viewport().installEventFilter(self)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.map)
        splitter.addWidget(self.table)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.download_button)
        layout.addWidget(splitter)

    def eventFilter(self, watched, event):
        if watched is self.table.viewport() and event.type() == event.Type.Leave:
            self._clear_table_highlight()
        return super().eventFilter(watched, event)

    def load(self, log_data: LogData):
        rows = log_data.mission()
        self.table.setRowCount(len(rows))
        self._waypoints = []
        self._export_rows = []
        self._row_to_marker = {}
        self._marker_to_row = {}
        default_bg = self.table.palette().color(QPalette.Base)
        default_fg = self.table.palette().color(QPalette.Text)

        for i, row in enumerate(rows):
            seq = row.get("CNum", row.get("seq", i))
            cmd_id = row.get("CId", row.get("command", 0))
            name, description = describe_command(cmd_id)
            lat = _first_present(row, _LAT_FIELDS)
            lon = _first_present(row, _LON_FIELDS)
            alt = row.get("Alt", row.get("alt", 0.0))
            frame = row.get("Frame", row.get("frame", 0))

            lat_deg = lon_deg = 0.0
            if lat is not None and lon is not None:
                lat_deg = lat / 1e7 if abs(lat) > 1000 else lat
                lon_deg = lon / 1e7 if abs(lon) > 1000 else lon
                if lat_deg != 0 or lon_deg != 0:
                    marker_idx = len(self._waypoints)
                    self._row_to_marker[i] = marker_idx
                    self._marker_to_row[marker_idx] = i
                    self._waypoints.append((lat_deg, lon_deg))

            p1 = _first_present(row, ["Prm1", "param1"], 0.0)
            p2 = _first_present(row, ["Prm2", "param2"], 0.0)
            p3 = _first_present(row, ["Prm3", "param3"], 0.0)
            p4 = _first_present(row, ["Prm4", "param4"], 0.0)

            self._export_rows.append({
                "seq": int(seq), "current": 1 if i == 0 else 0,
                "frame": int(frame), "command": int(cmd_id),
                "p1": float(p1), "p2": float(p2), "p3": float(p3), "p4": float(p4),
                "lat": lat_deg, "lon": lon_deg, "alt": float(alt),
            })

            params = ", ".join(
                f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}"
                for k, v in row.items()
                if k.startswith("Prm") or k.startswith("param")
            )

            items = [
                QTableWidgetItem(name),
                QTableWidgetItem(f"{lat_deg:.6f}"),
                QTableWidgetItem(f"{lon_deg:.6f}"),
                QTableWidgetItem(f"{alt:g}" if isinstance(alt, float) else str(alt)),
                QTableWidgetItem(str(frame)),
                QTableWidgetItem(params),
                QTableWidgetItem(str(seq)),
                QTableWidgetItem(str(int(cmd_id)) if cmd_id != "" else ""),
                QTableWidgetItem(description),
            ]
            bg, fg = _ROW_HIGHLIGHT_COLORS.get(name, (default_bg, default_fg))
            for col, item in enumerate(items):
                item.setBackground(bg)
                item.setForeground(fg)
                self.table.setItem(i, col, item)

        self.table.resizeColumnsToContents()
        self.map.set_mission(self._waypoints)

    def _on_table_cell_entered(self, row: int, column: int):
        if row == self._highlighted_row:
            return
        self._highlighted_row = row
        self.map.highlight_point(self._row_to_marker.get(row, -1))

    def _clear_table_highlight(self):
        if self._highlighted_row == -1:
            return
        self._highlighted_row = -1
        self.map.highlight_point(-1)

    def _on_marker_hovered(self, marker_idx: int):
        row = self._marker_to_row.get(marker_idx, -1) if marker_idx >= 0 else -1
        if row == -1:
            self.table.clearSelection()
        else:
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, 0))

    def waypoints(self) -> list[tuple[float, float]]:
        return self._waypoints

    def _on_download_clicked(self):
        if not self._export_rows:
            QMessageBox.information(self, "No mission", "No mission waypoints loaded.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Mission", "mission.waypoints",
            "Waypoint files (*.waypoints);;All Files (*)"
        )
        if not path:
            return
        self._export_qgc_wpl(Path(path))

    def _export_qgc_wpl(self, path: Path):
        lines = ["QGC WPL 110"]
        for r in self._export_rows:
            lines.append(
                f"{r['seq']}\t{r['current']}\t{r['frame']}\t{r['command']}\t"
                f"{r['p1']:.8f}\t{r['p2']:.8f}\t{r['p3']:.8f}\t{r['p4']:.8f}\t"
                f"{r['lat']:.8f}\t{r['lon']:.8f}\t{r['alt']:.6f}\t1"
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
