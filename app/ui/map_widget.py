"""GPS track view on a Google satellite basemap (Leaflet inside QWebEngineView).

Requires internet access to fetch the Leaflet library and Google map tiles.
"""
from __future__ import annotations

import json

import numpy as np
from PySide6.QtCore import Qt, QUrl, Signal, QObject, Slot
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QComboBox, QLabel

from app.core.time_format import format_mmss


_MODE_COLOR_PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#46f0f0", "#f032e6", "#bcf60c", "#fabebe",
    "#008080", "#e6beff", "#9a6324", "#fffac8", "#800000",
]


class MapBridge(QObject):
    """JavaScript bridge to receive cursor drag events from the map."""
    cursor_dragged = Signal(float)

    @Slot(float)
    def onCursorDragged(self, time_val: float):
        self.cursor_dragged.emit(time_val)

_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
html,body,#map{height:100%;margin:0;padding:0;background:#222;}
.time-tooltip{background:#e6194b;color:#fff;border:none;font-weight:bold;font-size:12px;}
.time-tooltip::before{border-top-color:#e6194b;}
.vtol-icon{pointer-events:none;}
.vtol-icon svg{transform-origin:50% 50%;transition:transform 0.05s linear;}
</style>
</head>
<body>
<div id="map"></div>
<script>
var map = L.map('map', {
    zoomControl: true,
    dragging: true,
    scrollWheelZoom: true,
    doubleClickZoom: true,
    touchZoom: true,
    boxZoom: true,
    zoomSnap: 0,
    attributionControl: false
}).setView([0, 0], 2);
function googleLayer(lyrs, maxZoom) {
    return L.tileLayer('tilecache://tile/' + lyrs + '/{z}/{x}/{y}', {
        maxZoom: maxZoom,
        attribution: 'Imagery &copy; Google'
    });
}
var basemapLayers = {
    s: googleLayer('s', 21),
    y: googleLayer('y', 21),
    m: googleLayer('m', 21),
    p: googleLayer('p', 20)
};
var currentBasemap = 's';
var basemapVisible = true;
basemapLayers[currentBasemap].addTo(map);

function setBasemapType(type) {
    if (!(type in basemapLayers)) return;
    if (basemapVisible) basemapLayers[currentBasemap].remove();
    currentBasemap = type;
    if (basemapVisible) basemapLayers[currentBasemap].addTo(map);
}
function setBasemapVisible(visible) {
    basemapVisible = visible;
    var layer = basemapLayers[currentBasemap];
    if (visible && !map.hasLayer(layer)) {
        layer.addTo(map);
    } else if (!visible && map.hasLayer(layer)) {
        layer.remove();
    }
}

var windHighlightOuter = L.layerGroup().addTo(map);
var windHighlightInner = L.layerGroup().addTo(map);
var trackLine = L.polyline([], {color: '#ff0000', weight: 3}).addTo(map);
var followEnabled = false;
var highlightLine = L.polyline([], {color: '#ffeb3b', weight: 6, opacity: 0.9}).addTo(map);
var missionLine = L.polyline([], {color: '#00e5ff', weight: 2, dashArray: '6,6'}).addTo(map);
var modeLines = L.layerGroup().addTo(map);
var missionMarkers = L.layerGroup().addTo(map);
var camMarkers = L.layerGroup().addTo(map);
var trigMarkers = L.layerGroup().addTo(map);
var errorMarkers = L.layerGroup().addTo(map);
var assistMarkers = L.layerGroup().addTo(map);
var failsafeMarkers = L.layerGroup().addTo(map);
function squareIcon(color, size) {
    var half = size / 2;
    return L.divIcon({
        className: 'square-marker-icon',
        html: '<div style="width:' + size + 'px;height:' + size + 'px;background:' + color + ';border:1px solid #222;"></div>',
        iconSize: [size, size],
        iconAnchor: [half, half]
    });
}
var errorIcon = L.divIcon({
    className: 'error-marker-icon',
    html: '<div style="width:18px;height:18px;border-radius:50%;background:#e6194b;' +
        'border:2px solid #fff;color:#fff;font-weight:bold;font-size:13px;' +
        'line-height:16px;text-align:center;">!</div>',
    iconSize: [18, 18],
    iconAnchor: [9, 9]
});
var assistIcon = L.divIcon({
    className: 'assist-marker-icon',
    html: '<div style="width:18px;height:18px;border-radius:50%;background:#ff8c00;' +
        'border:2px solid #fff;color:#fff;font-weight:bold;font-size:13px;' +
        'line-height:16px;text-align:center;">!</div>',
    iconSize: [18, 18],
    iconAnchor: [9, 9]
});
var failsafeIcon = L.divIcon({
    className: 'failsafe-marker-icon',
    html: '<div style="width:18px;height:18px;border-radius:50%;background:#000000;' +
        'border:2px solid #fff;color:#fff;font-weight:bold;font-size:13px;' +
        'line-height:16px;text-align:center;">!</div>',
    iconSize: [18, 18],
    iconAnchor: [9, 9]
});
function buildVtolIcon(scale) {
    var size = 32 * scale;
    var half = size / 2;
    var html = '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24">' +
        '<g transform="rotate(0 12 12)">' +
        '<path d="M12 2 L13.2 9.2 L21 15 L21 16.8 L13 14.3 L13.6 19.2 L16 21 L16 22 L12 21 L8 22 L8 21 L10.4 19.2 L11 14.3 L3 16.8 L3 15 L10.8 9.2 Z" ' +
        'fill="#e6194b" fill-opacity="0.35" stroke="#ffffff" stroke-width="1"/>' +
        '</g></svg>';
    return L.divIcon({
        html: html,
        className: 'vtol-icon',
        iconSize: [size, size],
        iconAnchor: [half, half]
    });
}
var iconScale = 1;
var lastHeading = 0;
var vtolIcon = buildVtolIcon(iconScale);
var marker = L.marker([0, 0], {icon: vtolIcon, draggable: true}).addTo(map);
marker.bindTooltip('00:00', {permanent: true, direction: 'top', offset: [0, -10], className: 'time-tooltip'});
function setIconScale(scale) {
    iconScale = scale;
    vtolIcon = buildVtolIcon(iconScale);
    marker.setIcon(vtolIcon);
    var el = marker.getElement();
    var g = el ? el.querySelector('g') : null;
    if (g) g.setAttribute('transform', 'rotate(' + lastHeading + ' 12 12)');
}

var pybridge = null;
if (typeof QWebChannel !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function(channel) {
        pybridge = channel.objects.pybridge;
    });
}

function notifyCursorDragged(timeVal) {
    if (pybridge) {
        pybridge.onCursorDragged(timeVal);
    }
}

var trackCoords = [];
var trackTimes = [];

function setTrackWithTimes(coords, times) {
    trackCoords = coords;
    trackTimes = times;
    trackLine.setLatLngs(coords);
    if (coords.length > 0) {
        marker.setLatLng(coords[0]);
        map.fitBounds(trackLine.getBounds(), {padding: [20, 20]});
    }
}

marker.on('drag', function(e) {
    if (trackCoords.length === 0) return;
    var pos = e.target.getLatLng();
    var minDist = Infinity;
    var bestIdx = 0;
    for (var i = 0; i < trackCoords.length; i++) {
        var d = Math.pow(pos.lat - trackCoords[i][0], 2) + Math.pow(pos.lng - trackCoords[i][1], 2);
        if (d < minDist) {
            minDist = d;
            bestIdx = i;
        }
    }
    var nearestLat = trackCoords[bestIdx][0];
    var nearestLng = trackCoords[bestIdx][1];
    marker.setLatLng([nearestLat, nearestLng]);
    if (trackTimes.length > bestIdx) {
        var clickedTime = trackTimes[bestIdx];
        notifyCursorDragged(clickedTime);
    }
});

marker.on('dragend', function(e) {
    if (trackCoords.length === 0) return;
    var pos = e.target.getLatLng();
    var minDist = Infinity;
    var bestIdx = 0;
    for (var i = 0; i < trackCoords.length; i++) {
        var d = Math.pow(pos.lat - trackCoords[i][0], 2) + Math.pow(pos.lng - trackCoords[i][1], 2);
        if (d < minDist) {
            minDist = d;
            bestIdx = i;
        }
    }
    var nearestLat = trackCoords[bestIdx][0];
    var nearestLng = trackCoords[bestIdx][1];
    marker.setLatLng([nearestLat, nearestLng]);
    if (trackTimes.length > bestIdx) {
        var clickedTime = trackTimes[bestIdx];
        notifyCursorDragged(clickedTime);
    }
});

function setTrack(coords) {
    trackCoords = coords;
    trackTimes = [];
    trackLine.setLatLngs(coords);
    if (coords.length > 0) {
        marker.setLatLng(coords[0]);
        map.fitBounds(trackLine.getBounds(), {padding: [20, 20]});
    }
}
function setCursor(lat, lon, timeLabel, heading) {
    marker.setLatLng([lat, lon]);
    if (timeLabel !== undefined) {
        marker.setTooltipContent(timeLabel);
    }
    if (heading !== undefined) {
        lastHeading = heading;
        var el = marker.getElement();
        var g = el ? el.querySelector('g') : null;
        if (g) g.setAttribute('transform', 'rotate(' + heading + ' 12 12)');
    }
    if (followEnabled) {
        map.panTo([lat, lon], {animate: false});
    }
}
function setFollow(enabled) {
    followEnabled = enabled;
    if (enabled) {
        map.panTo(marker.getLatLng(), {animate: false});
    }
}
function setHighlight(coords) {
    highlightLine.setLatLngs(coords);
}
function setCamMarkers(coords) {
    camMarkers.clearLayers();
    coords.forEach(function(c) {
        L.marker(c, {icon: squareIcon('#ffeb3b', 5)}).addTo(camMarkers);
    });
}
function setCamMarkersVisible(visible) {
    if (visible && !map.hasLayer(camMarkers)) {
        camMarkers.addTo(map);
    } else if (!visible && map.hasLayer(camMarkers)) {
        camMarkers.remove();
    }
}
function setTrigMarkers(coords) {
    trigMarkers.clearLayers();
    coords.forEach(function(c) {
        L.marker(c, {icon: squareIcon('#3cb44b', 10)}).addTo(trigMarkers);
    });
}
function setTrigMarkersVisible(visible) {
    if (visible && !map.hasLayer(trigMarkers)) {
        trigMarkers.addTo(map);
    } else if (!visible && map.hasLayer(trigMarkers)) {
        trigMarkers.remove();
    }
}
function setErrorMarkers(items) {
    errorMarkers.clearLayers();
    items.forEach(function(item) {
        L.marker([item.lat, item.lon], {icon: errorIcon})
            .bindTooltip(item.text)
            .addTo(errorMarkers);
    });
}
function setAssistMarkers(items) {
    assistMarkers.clearLayers();
    items.forEach(function(item) {
        L.marker([item.lat, item.lon], {icon: assistIcon})
            .bindTooltip(item.text)
            .addTo(assistMarkers);
    });
}
function setFailsafeMarkers(items) {
    failsafeMarkers.clearLayers();
    items.forEach(function(item) {
        L.marker([item.lat, item.lon], {icon: failsafeIcon})
            .bindTooltip(item.text)
            .addTo(failsafeMarkers);
    });
}
function setErrorMarkersVisible(visible) {
    [errorMarkers, assistMarkers, failsafeMarkers].forEach(function(group) {
        if (visible && !map.hasLayer(group)) {
            group.addTo(map);
        } else if (!visible && map.hasLayer(group)) {
            group.remove();
        }
    });
}
function setWindHighlight(segments) {
    windHighlightOuter.clearLayers();
    windHighlightInner.clearLayers();
    segments.forEach(function(coords) {
        L.polyline(coords, {color: '#ffffff', weight: 12, opacity: 0.35}).addTo(windHighlightOuter);
        L.polyline(coords, {color: '#ffffff', weight: 5, opacity: 0.8}).addTo(windHighlightInner);
    });
}
function setModeSegments(segments) {
    modeLines.clearLayers();
    segments.forEach(function(seg) {
        L.polyline(seg.coords, {color: seg.color, weight: 3}).addTo(modeLines);
    });
    trackLine.setStyle({opacity: segments.length > 0 ? 0 : 1});
}
function setMission(coords) {
    missionLine.setLatLngs(coords);
    missionMarkers.clearLayers();
    coords.forEach(function(c, i) {
        L.circleMarker(c, {radius: 5, color: '#00e5ff', weight: 2, fillColor: '#003344', fillOpacity: 1})
            .bindTooltip('WP ' + i)
            .addTo(missionMarkers);
    });
    if (coords.length > 0) {
        map.fitBounds(missionLine.getBounds(), {padding: [30, 30]});
    }
}
</script>
</body></html>
"""


class MapWidget(QWidget):
    cursor_time_changed = Signal(float)
    _BASEMAP_TYPES = [("Спутник", "s"), ("Гибрид", "y"), ("Карта", "m"), ("Рельеф", "p")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWebEngineView()
        self._ready = False
        self._pending_js: list[str] = []

        # Setup JavaScript bridge
        self._bridge = MapBridge()
        self._bridge.cursor_dragged.connect(self._on_map_cursor_dragged)

        channel = QWebChannel(self.view.page())
        channel.registerObject("pybridge", self._bridge)
        self.view.page().setWebChannel(channel)

        self.view.loadFinished.connect(self._on_load_finished)
        self.view.setHtml(_HTML, QUrl("https://maps.google.com/"))

        self.basemap_checkbox = QCheckBox("Подложка")
        self.basemap_checkbox.setChecked(True)
        self.basemap_checkbox.toggled.connect(self.set_basemap_visible)

        self.basemap_combo = QComboBox()
        for label, code in self._BASEMAP_TYPES:
            self.basemap_combo.addItem(label, code)
        self.basemap_combo.currentIndexChanged.connect(self._on_basemap_combo_changed)

        self.follow_checkbox = QCheckBox("Центрировать")
        self.follow_checkbox.toggled.connect(self.set_follow)

        self.show_photos_checkbox = QCheckBox("Отобразить фотографии")
        self.show_photos_checkbox.setChecked(True)
        self.show_photos_checkbox.toggled.connect(self.set_photo_markers_visible)

        self.photo_count_label = QLabel("Количество фотографий нет")
        self.photo_count_label.setStyleSheet("color: white;")

        self.photo_count_help_label = QLabel("?")
        self.photo_count_help_label.setToolTip(
            "<span style='color:#ffeb3b;'>&#9632;</span> &mdash; количество отправленных фотоимпульсов в камеру<br>"
            "<span style='color:#3cb44b;'>&#9632;</span> &mdash; количество полученных фотоимпульсов от камеры"
        )
        self.photo_count_help_label.setStyleSheet(
            "QLabel { border: 1px solid gray; border-radius: 8px; padding: 0px 5px; color: white; }"
        )

        self.icon_size_label = QLabel("Размер иконки:")
        self.icon_size_label.setStyleSheet("color: white;")
        self.icon_size_combo = QComboBox()
        self.icon_size_combo.addItems(["x0.5", "x1", "x2", "x5"])
        self.icon_size_combo.setCurrentText("x1")
        self.icon_size_combo.currentTextChanged.connect(self._on_icon_size_changed)

        self.show_errors_checkbox = QCheckBox("Ошибки")
        self.show_errors_checkbox.setChecked(True)
        self.show_errors_checkbox.toggled.connect(self.set_error_markers_visible)
        self.show_errors_checkbox.toggled.connect(self._on_show_errors_toggled)

        self.show_wind_checkbox = QCheckBox("Ветер")
        self.show_wind_checkbox.setChecked(True)
        self.show_wind_checkbox.toggled.connect(self.set_wind_panel_visible)

        self._max_wind = 12.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.mode_legend = QWidget(self.view)
        self.mode_legend.setStyleSheet(
            "background-color: rgba(20, 20, 20, 190); border-radius: 6px;"
        )
        self._mode_legend_layout = QVBoxLayout(self.mode_legend)
        self._mode_legend_layout.setContentsMargins(8, 6, 8, 6)
        self._mode_legend_layout.setSpacing(4)
        self.mode_legend.hide()

        self.error_legend = QWidget(self.view)
        self.error_legend.setStyleSheet(
            "background-color: rgba(20, 20, 20, 190); border-radius: 6px;"
        )
        error_legend_layout = QVBoxLayout(self.error_legend)
        error_legend_layout.setContentsMargins(8, 6, 8, 6)
        error_legend_layout.setSpacing(4)
        title = QLabel("Ошибки и сбои")
        title.setStyleSheet("color: white; font-weight: bold;")
        error_legend_layout.addWidget(title)
        for color, text in (("#000000", "Фэйлсейф"), ("#ff8c00", "Ассистент"), ("#e6194b", "Ошибка")):
            row = QHBoxLayout()
            row.setSpacing(6)
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(
                f"background-color: {color}; border: 1px solid #fff; border-radius: 7px; "
                f"color: #fff; font-weight: bold; font-size: 10px;"
            )
            swatch.setAlignment(Qt.AlignCenter)
            swatch.setText("!")
            label = QLabel(text)
            label.setStyleSheet("color: white;")
            row.addWidget(swatch)
            row.addWidget(label)
            row.addStretch()
            error_legend_layout.addLayout(row)
        self.error_legend.adjustSize()
        self.error_legend.setVisible(self.show_errors_checkbox.isChecked())

        self.wind_panel = QWidget(self.view)
        self.wind_panel.setStyleSheet(
            "background-color: rgba(20, 20, 20, 190); border-radius: 6px;"
        )
        wind_panel_layout = QVBoxLayout(self.wind_panel)
        wind_panel_layout.setContentsMargins(8, 6, 8, 6)
        wind_panel_layout.setSpacing(2)
        wind_title = QLabel("Допустимый ветер")
        wind_title.setStyleSheet("color: white; font-weight: bold;")
        self.wind_value_label = QLabel(f"{self._max_wind:.0f} м/с")
        self.wind_value_label.setStyleSheet("color: white;")
        wind_panel_layout.addWidget(wind_title)
        wind_panel_layout.addWidget(self.wind_value_label)
        self.wind_panel.adjustSize()
        self.wind_panel.setVisible(self.show_wind_checkbox.isChecked())

        self._t = np.array([])
        self._lat = np.array([])
        self._lon = np.array([])
        self._t0 = 0.0
        self._heading_t = np.array([])
        self._heading_v = np.array([])
        self._mode_events: list[tuple[float, str]] = []
        self._mode_colors: dict[str, str] = {}
        self._wind_t = np.array([])
        self._wind_speed = np.array([])

        self._position_error_legend()
        self._position_wind_panel()
        self.error_legend.raise_()
        self.wind_panel.raise_()

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

    def set_time_origin(self, t0: float):
        self._t0 = t0

    def set_track(self, t: np.ndarray, lat: np.ndarray, lon: np.ndarray):
        self._t, self._lat, self._lon = t, lat, lon
        coords = list(zip(lat.tolist(), lon.tolist()))
        self._run_js(f"setTrackWithTimes({json.dumps(coords)}, {t.tolist()});")
        self._update_mode_segments()
        self._update_wind_highlight()

    def set_wind_speed_data(self, t: np.ndarray, speed: np.ndarray):
        self._wind_t, self._wind_speed = t, speed
        self._update_wind_highlight()

    def set_wind_panel_visible(self, visible: bool):
        self.wind_panel.setVisible(visible)

    def set_max_wind(self, max_wind: float):
        self._max_wind = max_wind
        self.wind_value_label.setText(f"{self._max_wind:.0f} м/с")
        self.wind_panel.adjustSize()
        self._position_wind_panel()
        self._update_wind_highlight()

    def _on_show_errors_toggled(self, checked: bool):
        self.error_legend.setVisible(checked)

    def _update_wind_highlight(self):
        if len(self._t) == 0 or len(self._wind_t) == 0:
            self._run_js("setWindHighlight([]);")
            return

        interp_speed = np.interp(self._t, self._wind_t, self._wind_speed)
        mask = interp_speed > self._max_wind
        segments_js = []
        i = 0
        n = len(mask)
        while i < n:
            if mask[i]:
                lo = max(0, i - 1)
                j = i
                while j < n and mask[j]:
                    j += 1
                hi = min(n - 1, j)
                coords = list(zip(self._lat[lo:hi + 1].tolist(), self._lon[lo:hi + 1].tolist()))
                segments_js.append(coords)
                i = j
            else:
                i += 1

        self._run_js(f"setWindHighlight({json.dumps(segments_js)});")

    def set_flight_modes(self, mode_events: list[tuple[float, str]]):
        self._mode_events = mode_events
        self._update_mode_segments()

    def _update_mode_segments(self):
        if len(self._t) == 0 or not self._mode_events:
            self._mode_colors = {}
            self._update_mode_legend()
            self._run_js("setModeSegments([]);")
            return

        events = sorted(self._mode_events, key=lambda e: e[0])
        self._mode_colors = {}
        for _, name in events:
            if name not in self._mode_colors:
                self._mode_colors[name] = _MODE_COLOR_PALETTE[len(self._mode_colors) % len(_MODE_COLOR_PALETTE)]

        end_time = float(self._t[-1])
        segments_js = []
        for i, (t_start, name) in enumerate(events):
            t_end = events[i + 1][0] if i + 1 < len(events) else end_time
            lo = int(np.searchsorted(self._t, t_start))
            hi = int(np.searchsorted(self._t, t_end))
            lo = max(0, min(lo, len(self._t) - 1))
            hi = max(0, min(hi, len(self._t) - 1))
            if hi <= lo:
                continue
            coords = list(zip(self._lat[lo:hi + 1].tolist(), self._lon[lo:hi + 1].tolist()))
            segments_js.append({"coords": coords, "color": self._mode_colors[name]})

        self._run_js(f"setModeSegments({json.dumps(segments_js)});")
        self._update_mode_legend()

    def _update_mode_legend(self):
        while self._mode_legend_layout.count():
            item = self._mode_legend_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            else:
                sub_layout = item.layout()
                if sub_layout:
                    while sub_layout.count():
                        sub_item = sub_layout.takeAt(0)
                        if sub_item.widget():
                            sub_item.widget().deleteLater()

        if not self._mode_colors:
            self.mode_legend.hide()
            return

        title = QLabel("Режимы полёта")
        title.setStyleSheet("color: white; font-weight: bold;")
        self._mode_legend_layout.addWidget(title)
        for name, color in self._mode_colors.items():
            row = QHBoxLayout()
            row.setSpacing(6)
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background-color: {color}; border: 1px solid #222;")
            label = QLabel(name)
            label.setStyleSheet("color: white;")
            row.addWidget(swatch)
            row.addWidget(label)
            row.addStretch()
            self._mode_legend_layout.addLayout(row)

        self.mode_legend.adjustSize()
        self._position_mode_legend()
        self.mode_legend.show()
        self.mode_legend.raise_()

    def _position_mode_legend(self):
        margin = 10
        x = margin
        y = self.view.height() - self.mode_legend.height() - margin
        self.mode_legend.move(x, y)

    def _position_error_legend(self):
        margin = 10
        x = self.view.width() - self.error_legend.width() - margin
        y = self.view.height() - self.error_legend.height() - margin
        self.error_legend.move(x, y)

    def _position_wind_panel(self):
        margin = 10
        x = self.view.width() - self.wind_panel.width() - margin
        y = margin
        self.wind_panel.move(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_mode_legend()
        self._position_error_legend()
        self._position_wind_panel()

    def set_heading_data(self, t: np.ndarray, heading: np.ndarray):
        self._heading_t, self._heading_v = t, heading

    def clear_heading_data(self):
        self._heading_t = np.array([])

    def set_cursor_time(self, t: float):
        if len(self._t) == 0:
            return
        idx = int(np.searchsorted(self._t, t))
        idx = max(0, min(idx, len(self._t) - 1))
        label = format_mmss(t - self._t0)
        heading = None
        if len(self._heading_t):
            hidx = int(np.searchsorted(self._heading_t, t))
            hidx = max(0, min(hidx, len(self._heading_t) - 1))
            heading = float(self._heading_v[hidx])
        heading_arg = f"{heading}" if heading is not None else "undefined"
        self._run_js(f"setCursor({self._lat[idx]}, {self._lon[idx]}, '{label}', {heading_arg});")

    def highlight_range(self, t0: float, t1: float):
        if len(self._t) == 0:
            return
        lo = int(np.searchsorted(self._t, t0))
        hi = int(np.searchsorted(self._t, t1))
        lo = max(0, min(lo, len(self._t) - 1))
        hi = max(0, min(hi, len(self._t) - 1))
        if hi <= lo:
            self._run_js("setHighlight([]);")
            return
        coords = list(zip(self._lat[lo:hi + 1].tolist(), self._lon[lo:hi + 1].tolist()))
        self._run_js(f"setHighlight({json.dumps(coords)});")

    def clear_highlight(self):
        self._run_js("setHighlight([]);")

    def set_photo_counts(self, cam_count: int | None, trig_count: int | None):
        if not cam_count and not trig_count:
            self.photo_count_label.setText("Количество фотографий нет")
            return
        parts = []
        if cam_count:
            parts.append(f"<span style='color:#ffeb3b;'>&#9632;</span> {cam_count}")
        if trig_count:
            parts.append(f"<span style='color:#3cb44b;'>&#9632;</span> {trig_count}")
        self.photo_count_label.setText("Количество фотографий " + "&nbsp;&nbsp;&nbsp;".join(parts))

    def _on_icon_size_changed(self, text: str):
        scale = float(text.lstrip("x"))
        self.set_icon_scale(scale)

    def set_icon_scale(self, scale: float):
        self._run_js(f"setIconScale({scale});")

    def set_mission(self, waypoints: list[tuple[float, float]]):
        self._run_js(f"setMission({json.dumps(waypoints)});")

    def set_cam_markers(self, coords: list[tuple[float, float]]):
        self._run_js(f"setCamMarkers({json.dumps(coords)});")

    def set_cam_markers_visible(self, visible: bool):
        self._run_js(f"setCamMarkersVisible({'true' if visible else 'false'});")

    def set_trig_markers(self, coords: list[tuple[float, float]]):
        self._run_js(f"setTrigMarkers({json.dumps(coords)});")

    def set_trig_markers_visible(self, visible: bool):
        self._run_js(f"setTrigMarkersVisible({'true' if visible else 'false'});")

    def set_photo_markers_visible(self, visible: bool):
        self.set_cam_markers_visible(visible)
        self.set_trig_markers_visible(visible)

    def set_error_markers(self, items: list[dict]):
        """items: list of {"lat": float, "lon": float, "text": str}."""
        self._run_js(f"setErrorMarkers({json.dumps(items)});")

    def set_error_markers_visible(self, visible: bool):
        self._run_js(f"setErrorMarkersVisible({'true' if visible else 'false'});")

    def set_assist_markers(self, items: list[dict]):
        """items: list of {"lat": float, "lon": float, "text": str}."""
        self._run_js(f"setAssistMarkers({json.dumps(items)});")

    def set_failsafe_markers(self, items: list[dict]):
        """items: list of {"lat": float, "lon": float, "text": str}."""
        self._run_js(f"setFailsafeMarkers({json.dumps(items)});")

    def positions_at_times(self, t: np.ndarray) -> list[tuple[float, float]]:
        """Interpolate lat/lon along the loaded track for the given timestamps."""
        if len(self._t) == 0 or len(t) == 0:
            return []
        lat = np.interp(t, self._t, self._lat)
        lon = np.interp(t, self._t, self._lon)
        return list(zip(lat.tolist(), lon.tolist()))

    def set_basemap_visible(self, visible: bool):
        self._run_js(f"setBasemapVisible({'true' if visible else 'false'});")

    def _on_basemap_combo_changed(self, index: int):
        code = self.basemap_combo.itemData(index)
        self._run_js(f"setBasemapType('{code}');")

    def set_follow(self, enabled: bool):
        self._run_js(f"setFollow({'true' if enabled else 'false'});")

    def _on_map_cursor_dragged(self, time_val: float):
        """Called when user drags the marker on the map."""
        self.cursor_time_changed.emit(time_val)
