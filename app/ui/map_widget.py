"""GPS track view on a Google satellite basemap (Leaflet inside QWebEngineView).

Requires internet access to fetch the Leaflet library and Google map tiles.
"""
from __future__ import annotations

import json

import numpy as np
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QComboBox

from app.core.time_format import format_mmss

_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
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
    zoomSnap: 0
}).setView([0, 0], 2);
function googleLayer(lyrs, maxZoom) {
    return L.tileLayer('https://{s}.google.com/vt/lyrs=' + lyrs + '&x={x}&y={y}&z={z}', {
        subdomains: ['mt0', 'mt1', 'mt2', 'mt3'],
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

var trackLine = L.polyline([], {color: '#ff0000', weight: 3}).addTo(map);
var followEnabled = false;
var highlightLine = L.polyline([], {color: '#ffeb3b', weight: 6, opacity: 0.9}).addTo(map);
var missionLine = L.polyline([], {color: '#00e5ff', weight: 2, dashArray: '6,6'}).addTo(map);
var missionMarkers = L.layerGroup().addTo(map);
var vtolIconHtml = '<svg width="32" height="32" viewBox="0 0 24 24">' +
    '<g transform="rotate(0 12 12)">' +
    '<path d="M12 2 L13.2 9.2 L21 15 L21 16.8 L13 14.3 L13.6 19.2 L16 21 L16 22 L12 21 L8 22 L8 21 L10.4 19.2 L11 14.3 L3 16.8 L3 15 L10.8 9.2 Z" ' +
    'fill="#e6194b" fill-opacity="0.35" stroke="#ffffff" stroke-width="1"/>' +
    '</g></svg>';
var vtolIcon = L.divIcon({
    html: vtolIconHtml,
    className: 'vtol-icon',
    iconSize: [32, 32],
    iconAnchor: [16, 16]
});
var marker = L.marker([0, 0], {icon: vtolIcon}).addTo(map);
marker.bindTooltip('00:00', {permanent: true, direction: 'top', offset: [0, -10], className: 'time-tooltip'});

function setTrack(coords) {
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
    _BASEMAP_TYPES = [("Satellite", "s"), ("Hybrid", "y"), ("Roadmap", "m"), ("Terrain", "p")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWebEngineView()
        self._ready = False
        self._pending_js: list[str] = []
        self.view.loadFinished.connect(self._on_load_finished)
        self.view.setHtml(_HTML, QUrl("https://maps.google.com/"))

        self.basemap_checkbox = QCheckBox("Basemap")
        self.basemap_checkbox.setChecked(True)
        self.basemap_checkbox.toggled.connect(self.set_basemap_visible)

        self.basemap_combo = QComboBox()
        for label, code in self._BASEMAP_TYPES:
            self.basemap_combo.addItem(label, code)
        self.basemap_combo.currentIndexChanged.connect(self._on_basemap_combo_changed)

        self.follow_checkbox = QCheckBox("Follow aircraft")
        self.follow_checkbox.toggled.connect(self.set_follow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self._t = np.array([])
        self._lat = np.array([])
        self._lon = np.array([])
        self._t0 = 0.0
        self._heading_t = np.array([])
        self._heading_v = np.array([])

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
        self._run_js(f"setTrack({json.dumps(coords)});")

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

    def set_mission(self, waypoints: list[tuple[float, float]]):
        self._run_js(f"setMission({json.dumps(waypoints)});")

    def set_basemap_visible(self, visible: bool):
        self._run_js(f"setBasemapVisible({'true' if visible else 'false'});")

    def _on_basemap_combo_changed(self, index: int):
        code = self.basemap_combo.itemData(index)
        self._run_js(f"setBasemapType('{code}');")

    def set_follow(self, enabled: bool):
        self._run_js(f"setFollow({'true' if enabled else 'false'});")
