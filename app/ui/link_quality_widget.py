"""Link-quality / RSSI visualisation tab.

Shows a satellite map with the GPS track coloured by RSSI signal strength
(green = strong, red = weak), plus a pyqtgraph timeline of the raw signal.
"""
from __future__ import annotations

import json

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame

from app.ui.time_axis import TimeAxisItem

# Colour thresholds: (min_norm_value, hex_color)
_THRESHOLDS = [
    (0.00, "#e6194b"),  # 0-30 %  – red
    (0.30, "#ff8c00"),  # 30-55 % – orange
    (0.55, "#ffe119"),  # 55-75 % – yellow
    (0.75, "#a8d800"),  # 75-90 % – lime
    (0.90, "#3cb44b"),  # 90-100 %– green
]


def _norm_color(norm: float) -> str:
    color = _THRESHOLDS[0][1]
    for th, col in _THRESHOLDS:
        if norm >= th:
            color = col
    return color


_MAP_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
html,body,#map{height:100%;margin:0;padding:0;background:#222;}
</style>
</head><body>
<div id="map"></div>
<script>
var map = L.map('map', {zoomControl:true, attributionControl:false, zoomSnap:0}).setView([0,0],2);
L.tileLayer('tilecache://tile/s/{z}/{x}/{y}', {maxZoom:21}).addTo(map);
var rssiLines = L.layerGroup().addTo(map);

function setRssiTrack(segments, bounds) {
    rssiLines.clearLayers();
    segments.forEach(function(seg) {
        L.polyline(seg.coords, {color: seg.color, weight: 5, opacity: 0.9}).addTo(rssiLines);
    });
    if (bounds) map.fitBounds(bounds, {padding: [20, 20]});
}
function clearTrack() { rssiLines.clearLayers(); }
</script>
</body></html>
"""


class LinkQualityWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._source_label = QLabel("Нет данных о качестве связи")
        self._source_label.setStyleSheet("color: #aaa; padding: 4px 6px;")

        legend = self._build_legend()

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._source_label)
        header.addStretch()
        header.addWidget(QLabel("Слабый"))
        header.addWidget(legend)
        header.addWidget(QLabel("Сильный"))

        self._view = QWebEngineView()
        self._ready = False
        self._pending_js: list[str] = []
        self._view.loadFinished.connect(self._on_load_finished)
        self._view.setHtml(_MAP_HTML, QUrl("https://maps.google.com/"))

        self._time_axis = TimeAxisItem(orientation="bottom")
        self._graph = pg.PlotWidget(axisItems={"bottom": self._time_axis})
        self._graph.setFixedHeight(130)
        self._graph.showGrid(x=True, y=True, alpha=0.25)
        self._graph.setLabel("bottom", "Время (мм:сс)")
        self._graph.setLabel("left", "RSSI")
        self._rssi_curve = self._graph.plot([], [], pen=pg.mkPen("#3cb44b", width=2))
        self._graph.getPlotItem().getAxis("left").setWidth(42)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addLayout(header)
        layout.addWidget(self._view, stretch=1)
        layout.addWidget(self._graph)

    @staticmethod
    def _build_legend() -> QFrame:
        frame = QFrame()
        frame.setFixedHeight(18)
        frame.setFixedWidth(180)
        frame.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #e6194b, stop:0.3 #ff8c00, stop:0.55 #ffe119,"
            "stop:0.75 #a8d800, stop:1 #3cb44b); border-radius:3px; }"
        )
        return frame

    def _on_load_finished(self, _ok: bool):
        self._ready = True
        for js in self._pending_js:
            self._view.page().runJavaScript(js)
        self._pending_js.clear()

    def _run_js(self, js: str):
        if self._ready:
            self._view.page().runJavaScript(js)
        else:
            self._pending_js.append(js)

    def load(self, gps_t: np.ndarray, lat: np.ndarray, lon: np.ndarray,
             rssi_t: np.ndarray, rssi_v: np.ndarray,
             rssi_max: float, source_label: str):
        self._source_label.setText(source_label)

        if len(rssi_t):
            t0 = float(rssi_t[0])
            self._time_axis.set_origin(t0)
            self._rssi_curve.setData(rssi_t, rssi_v)
            self._graph.setXRange(float(rssi_t[0]), float(rssi_t[-1]), padding=0.02)
            self._graph.setYRange(0, rssi_max * 1.05, padding=0)
        else:
            self._rssi_curve.setData([], [])

        if len(gps_t) < 2 or len(rssi_t) < 2:
            self._run_js("clearTrack();")
            return

        # Interpolate RSSI onto GPS timestamps
        interp = np.interp(gps_t, rssi_t, rssi_v)
        norm = interp / rssi_max

        # Build colour-run segments (each run shares an endpoint with the next)
        n = len(lat)
        segments_js = []
        i = 0
        while i < n - 1:
            color = _norm_color(float(norm[i]))
            j = i + 1
            while j < n and _norm_color(float(norm[j])) == color:
                j += 1
            coords = list(zip(lat[i:j + 1].tolist(), lon[i:j + 1].tolist()))
            segments_js.append({"coords": coords, "color": color})
            i = j

        bounds = [
            [float(lat.min()), float(lon.min())],
            [float(lat.max()), float(lon.max())],
        ]
        self._run_js(f"setRssiTrack({json.dumps(segments_js)},{json.dumps(bounds)});")

    def clear(self):
        self._source_label.setText("Нет данных о качестве связи")
        self._rssi_curve.setData([], [])
        self._run_js("clearTrack();")
