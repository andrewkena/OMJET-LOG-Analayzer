"""Link-quality / SNR / RSSI visualisation tab.

Two Leaflet maps side by side:
  Left  — SNR_local  = RSSI    - Noise     (aircraft hears ground)
  Right — SNR_remote = RemRSSI - RemNoise  (ground hears aircraft)

Track colour = SNR, track width = RSSI magnitude.
Bidirectional cursor: hover on graph ↔ yellow dot on maps; hover on map ↔ cursor on graph.
"""
from __future__ import annotations

import json

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QUrl, Qt, QObject, Signal, Slot, QEvent, QPointF
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QSpinBox, QDoubleSpinBox, QSlider, QCheckBox, QPushButton, QMessageBox,
)

from app.ui.time_axis import TimeAxisItem

_THRESHOLDS = [
    (0.00, "#e6194b"),
    (0.30, "#ff8c00"),
    (0.55, "#ffe119"),
    (0.75, "#a8d800"),
    (0.90, "#3cb44b"),
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
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
html,body{height:100%;margin:0;padding:0;background:#222;overflow:hidden;}
#map_local {position:absolute;top:0;left:0;width:50%;height:100%;}
#map_remote{position:absolute;top:0;left:50%;width:50%;height:100%;}
.map-label{
  position:absolute;top:8px;left:50%;transform:translateX(-50%);
  background:rgba(20,20,20,0.78);color:#fff;font:bold 12px sans-serif;
  padding:3px 10px;border-radius:4px;z-index:1000;white-space:nowrap;pointer-events:none;
}
</style>
</head><body>
<div id="map_local">
  <div class="map-label">SNR local — самолёт слышит землю</div>
</div>
<div id="map_remote">
  <div class="map-label">SNR remote — земля слышит самолёт</div>
</div>
<script>
var mapL=L.map('map_local', {zoomControl:true, attributionControl:false,zoomSnap:0}).setView([0,0],2);
var mapR=L.map('map_remote',{zoomControl:false,attributionControl:false,zoomSnap:0}).setView([0,0],2);
L.tileLayer('tilecache://tile/s/{z}/{x}/{y}',{maxZoom:21}).addTo(mapL);
L.tileLayer('tilecache://tile/s/{z}/{x}/{y}',{maxZoom:21}).addTo(mapR);
var baseL=L.layerGroup().addTo(mapL);
var baseR=L.layerGroup().addTo(mapR);
var linesL=L.layerGroup().addTo(mapL);
var linesR=L.layerGroup().addTo(mapR);

setTimeout(function(){mapL.invalidateSize();mapR.invalidateSize();},200);

// ── sync zoom/pan ──────────────────────────────────────────────────────────
var _syncing=false;
function _syncPair(src,dst){
  src.on('moveend',function(){
    if(_syncing)return;_syncing=true;
    dst.setView(src.getCenter(),src.getZoom(),{animate:false});
    _syncing=false;
  });
}
_syncPair(mapL,mapR);_syncPair(mapR,mapL);

// ── track segments ─────────────────────────────────────────────────────────
var _opacity=0.9;
function _applyBase(base,segs){
  base.clearLayers();
  if(!segs.length)return;
  var all=[];segs.forEach(function(s){s.coords.forEach(function(c){all.push(c);});});
  L.polyline(all,{color:'#ffffff',weight:2,opacity:0.4,lineJoin:'round'}).addTo(base);
}
function _applySegs(layer,segs){
  layer.clearLayers();
  segs.forEach(function(s){
    L.polyline(s.coords,{color:s.color,weight:s.weight,opacity:_opacity,lineJoin:'round'}).addTo(layer);
  });
}
function setOpacity(v){
  _opacity=v;
  [linesL,linesR].forEach(function(lg){lg.eachLayer(function(l){l.setStyle({opacity:v});});});
}

var _lastBounds=null;
function _fitBoth(bounds){
  mapL.invalidateSize(false);mapR.invalidateSize(false);
  mapL.fitBounds(bounds,{padding:[10,10]});mapR.fitBounds(bounds,{padding:[10,10]});
}
function setLocalTrack(segs,bounds){
  _applyBase(baseL,segs);_applySegs(linesL,segs);
  if(bounds){_lastBounds=bounds;setTimeout(function(){_fitBoth(bounds);},150);}
}
function setRemoteTrack(segs){
  _applyBase(baseR,segs);_applySegs(linesR,segs);
  if(_lastBounds)setTimeout(function(){mapR.invalidateSize(false);mapR.fitBounds(_lastBounds,{padding:[10,10]});},150);
}
function clearTracks(){
  baseL.clearLayers();baseR.clearLayers();
  linesL.clearLayers();linesR.clearLayers();
  trackCoords=[];trackTimes=[];
  if(cursorL){cursorL.remove();cursorL=null;}
  if(cursorR){cursorR.remove();cursorR=null;}
}

// ── cursor: map ↔ graph ────────────────────────────────────────────────────
var trackCoords=[], trackTimes=[];
var cursorL=null, cursorR=null;
var _bridge=null;
new QWebChannel(qt.webChannelTransport,function(ch){_bridge=ch.objects.lqBridge;});

function setTrackData(coords,times){trackCoords=coords;trackTimes=times;}

function setMapCursor(t){
  if(!trackTimes.length)return;
  var best=0,minD=Infinity;
  for(var i=0;i<trackTimes.length;i++){
    var d=Math.abs(trackTimes[i]-t);if(d<minD){minD=d;best=i;}
  }
  var lat=trackCoords[best][0],lng=trackCoords[best][1];
  var opt={radius:7,color:'#fff',weight:2,fillColor:'#ffff00',fillOpacity:0.9};
  if(!cursorL){cursorL=L.circleMarker([lat,lng],opt).addTo(mapL);}else{cursorL.setLatLng([lat,lng]);}
  if(!cursorR){cursorR=L.circleMarker([lat,lng],opt).addTo(mapR);}else{cursorR.setLatLng([lat,lng]);}
}

var _lastNotify=0;
function _onMapMove(e){
  if(!trackCoords.length||!_bridge)return;
  var now=Date.now();if(now-_lastNotify<80)return;_lastNotify=now;
  var best=0,minD=Infinity;
  for(var i=0;i<trackCoords.length;i++){
    var d=Math.pow(e.latlng.lat-trackCoords[i][0],2)+Math.pow(e.latlng.lng-trackCoords[i][1],2);
    if(d<minD){minD=d;best=i;}
  }
  _bridge.cursorMoved(trackTimes[best]);
}
mapL.on('mousemove',_onMapMove);
mapR.on('mousemove',_onMapMove);
</script>
</body></html>
"""

_MAX_CURSOR_PTS = 2000


class _LQBridge(QObject):
    cursor_moved = Signal(float)

    @Slot(float)
    def cursorMoved(self, t: float):
        self.cursor_moved.emit(t)


class LinkQualityWidget(QWidget):
    snr_range_changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._max_weight = 30
        self._opacity = 0.9
        self._snr_min = 0.0
        self._snr_max = 60.0
        self._cache: dict | None = None

        self._source_label = QLabel("Нет данных о качестве связи")
        self._source_label.setStyleSheet("color: #aaa; padding: 4px 6px;")

        legend = self._build_legend()

        weight_label = QLabel("Толщина:")
        weight_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self._weight_spin = QSpinBox()
        self._weight_spin.setRange(5, 50)
        self._weight_spin.setValue(self._max_weight)
        self._weight_spin.setFixedWidth(52)
        self._weight_spin.setToolTip("Максимальная толщина линии (при максимальном RSSI)")
        self._weight_spin.valueChanged.connect(self._on_weight_changed)

        opacity_label = QLabel("Прозрачность:")
        opacity_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(10, 100)
        self._opacity_slider.setValue(90)
        self._opacity_slider.setFixedWidth(100)
        self._opacity_slider.setToolTip("Прозрачность линии трека")
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)

        self._fullscreen_cb = QCheckBox("Во весь экран")
        self._fullscreen_cb.toggled.connect(self._on_fullscreen_toggled)

        # Top strip — always visible (source label + fullscreen toggle)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(self._source_label)
        top_row.addStretch()
        top_row.addWidget(self._fullscreen_cb)
        self._top_widget = QWidget()
        self._top_widget.setLayout(top_row)

        self._snr_min_spin = QDoubleSpinBox()
        self._snr_min_spin.setRange(-50.0, 200.0)
        self._snr_min_spin.setDecimals(1)
        self._snr_min_spin.setSingleStep(1.0)
        self._snr_min_spin.setValue(self._snr_min)
        self._snr_min_spin.setFixedWidth(62)
        self._snr_min_spin.setToolTip("SNR, при котором трек красный (слабый сигнал)")
        self._snr_min_spin.valueChanged.connect(self._on_local_snr_changed)

        self._snr_max_spin = QDoubleSpinBox()
        self._snr_max_spin.setRange(-50.0, 200.0)
        self._snr_max_spin.setDecimals(1)
        self._snr_max_spin.setSingleStep(1.0)
        self._snr_max_spin.setValue(self._snr_max)
        self._snr_max_spin.setFixedWidth(62)
        self._snr_max_spin.setToolTip("SNR, при котором трек зелёный (сильный сигнал)")
        self._snr_max_spin.valueChanged.connect(self._on_local_snr_changed)

        help_btn = QPushButton("?")
        help_btn.setFixedSize(22, 22)
        help_btn.setStyleSheet(
            "QPushButton { border-radius: 11px; border: 1px solid #888; font-weight: bold; }"
            "QPushButton:hover { background: #555; }"
        )
        help_btn.setToolTip("Методика расчёта SNR")
        help_btn.clicked.connect(self._show_snr_help)

        # Controls row — hidden when fullscreen
        ctrl_row = QHBoxLayout()
        ctrl_row.setContentsMargins(0, 0, 0, 0)
        ctrl_row.addWidget(opacity_label)
        ctrl_row.addWidget(self._opacity_slider)
        ctrl_row.addSpacing(10)
        ctrl_row.addWidget(weight_label)
        ctrl_row.addWidget(self._weight_spin)
        ctrl_row.addSpacing(14)
        ctrl_row.addWidget(QLabel("SNR слабый"))
        ctrl_row.addWidget(self._snr_min_spin)
        ctrl_row.addWidget(legend)
        ctrl_row.addWidget(self._snr_max_spin)
        ctrl_row.addWidget(QLabel("SNR сильный"))
        ctrl_row.addSpacing(6)
        ctrl_row.addWidget(help_btn)
        ctrl_row.addStretch()

        self._header_widget = QWidget()
        self._header_widget.setLayout(ctrl_row)

        # WebEngine + bridge
        self._bridge = _LQBridge()
        self._bridge.cursor_moved.connect(self._on_map_cursor_moved)
        self._view = QWebEngineView()
        channel = QWebChannel(self._view.page())
        channel.registerObject("lqBridge", self._bridge)
        self._view.page().setWebChannel(channel)
        self._ready = False
        self._pending_js: list[str] = []
        self._view.loadFinished.connect(self._on_load_finished)
        self._view.setHtml(_MAP_HTML, QUrl("https://maps.google.com/"))

        # Graph
        self._time_axis = TimeAxisItem(orientation="bottom")
        self._graph = pg.PlotWidget(axisItems={"bottom": self._time_axis})
        self._graph.setFixedHeight(130)
        self._graph.showGrid(x=True, y=True, alpha=0.25)
        self._graph.setLabel("bottom", "Время (мм:сс)")
        self._graph.setLabel("left", "SNR (ед.)")
        self._curve_local  = self._graph.plot([], [], pen=pg.mkPen("#3cb44b", width=2), name="SNR local")
        self._curve_remote = self._graph.plot([], [], pen=pg.mkPen("#4363d8", width=2), name="SNR remote")
        self._graph.addLegend(offset=(10, 10))
        self._graph.getPlotItem().getAxis("left").setWidth(42)
        self._cursor_line = pg.InfiniteLine(angle=90, movable=False,
                                            pen=pg.mkPen("#ffff00", width=1, style=Qt.PenStyle.DashLine))
        self._graph.addItem(self._cursor_line)

        # Graph hover → map
        self._graph.viewport().installEventFilter(self)
        self._graph.viewport().setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(self._top_widget)
        layout.addWidget(self._header_widget)
        layout.addWidget(self._view, stretch=1)
        layout.addWidget(self._graph)

    # ── event filter: graph hover → map cursor ─────────────────────────────
    def eventFilter(self, obj, event):
        if obj is self._graph.viewport() and event.type() == QEvent.Type.MouseMove:
            if event.buttons() == Qt.MouseButton.NoButton:
                vb = self._graph.getViewBox()
                try:
                    pt = event.position()
                except AttributeError:
                    pt = QPointF(event.pos())
                data_pt = vb.mapSceneToView(pt)
                self._run_js(f"setMapCursor({data_pt.x()});")
        return False

    # ── map cursor → graph cursor ──────────────────────────────────────────
    def _on_map_cursor_moved(self, t: float):
        self._cursor_line.setValue(t)

    # ── helpers ────────────────────────────────────────────────────────────
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

    def _on_weight_changed(self, value: int):
        self._max_weight = value
        if self._cache is not None:
            self._send_segments()

    def _on_opacity_changed(self, value: int):
        self._opacity = value / 100.0
        self._run_js(f"setOpacity({self._opacity});")

    def _on_fullscreen_toggled(self, checked: bool):
        self._header_widget.setVisible(not checked)
        if self._cache is not None:
            b = json.dumps(self._cache["bounds"])
            self._run_js(
                f"setTimeout(function(){{mapL.invalidateSize(false);mapR.invalidateSize(false);"
                f"mapL.fitBounds({b},{{padding:[10,10]}});mapR.fitBounds({b},{{padding:[10,10]}});}},150);"
            )

    def set_snr_range(self, snr_min: float, snr_max: float) -> None:
        self._snr_min = snr_min
        self._snr_max = snr_max
        for spin, val in ((self._snr_min_spin, snr_min), (self._snr_max_spin, snr_max)):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)
        if self._cache is not None:
            self._send_segments()

    def _on_local_snr_changed(self):
        snr_min = self._snr_min_spin.value()
        snr_max = self._snr_max_spin.value()
        if snr_max <= snr_min:
            self._snr_max_spin.blockSignals(True)
            self._snr_max_spin.setValue(snr_min + 1.0)
            self._snr_max_spin.blockSignals(False)
            snr_max = snr_min + 1.0
        self._snr_min = snr_min
        self._snr_max = snr_max
        self.snr_range_changed.emit(snr_min, snr_max)
        if self._cache is not None:
            self._send_segments()

    def _show_snr_help(self):
        QMessageBox.information(
            self, "Методика расчёта SNR",
            "<b>SNR (Signal-to-Noise Ratio)</b> — отношение сигнала к шуму.<br><br>"
            "<b>Формулы:</b><br>"
            "&nbsp;&nbsp;SNR_local&nbsp; = RSSI − Noise<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;(самолёт слышит землю)<br><br>"
            "&nbsp;&nbsp;SNR_remote = RemRSSI − RemNoise<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;(земля слышит самолёт)<br><br>"
            "<b>Источник данных:</b> сообщения <code>RADIO</code> в лог-файле ArduPilot.<br><br>"
            "<b>Цвет трека:</b><br>"
            "&nbsp;&nbsp;🔴 Красный — SNR ≤ порог «слабый»<br>"
            "&nbsp;&nbsp;🟡 Жёлтый — средний SNR<br>"
            "&nbsp;&nbsp;🟢 Зелёный — SNR ≥ порог «сильный»<br><br>"
            "<b>Ориентировочные значения SNR:</b><br>"
            "<table cellspacing='4'>"
            "<tr><th align='left'>SNR</th><th align='left'>Качество</th></tr>"
            "<tr><td>&gt; 100</td><td>Отличное — надёжная связь</td></tr>"
            "<tr><td>60–100</td><td>Хорошее</td></tr>"
            "<tr><td>30–60</td><td>Удовлетворительное</td></tr>"
            "<tr><td>10–30</td><td>Слабое, возможны потери пакетов</td></tr>"
            "<tr><td>&lt; 10</td><td>Критическое, связь нестабильна</td></tr>"
            "</table>",
        )

    # ── segment building ───────────────────────────────────────────────────
    def _build_segments(self, snr_norm: np.ndarray, rssi_norm: np.ndarray,
                        lat: np.ndarray, lon: np.ndarray) -> list[dict]:
        n = len(lat)
        segments: list[dict] = []
        i = 0
        while i < n - 1:
            color = _norm_color(float(snr_norm[i]))
            w = max(1, round(self._max_weight * float(rssi_norm[i])))
            j = i + 1
            while j < n:
                if (_norm_color(float(snr_norm[j])) != color or
                        max(1, round(self._max_weight * float(rssi_norm[j]))) != w):
                    break
                j += 1
            coords = list(zip(lat[i:j + 1].tolist(), lon[i:j + 1].tolist()))
            segments.append({"coords": coords, "color": color, "weight": w})
            i = j
        return segments

    def _send_segments(self):
        c = self._cache
        snr_range = max(self._snr_max - self._snr_min, 1.0)
        snr_local_n  = np.clip((c["snr_local"]  - self._snr_min) / snr_range, 0.0, 1.0)
        snr_remote_n = np.clip((c["snr_remote"] - self._snr_min) / snr_range, 0.0, 1.0)
        segs_l = self._build_segments(snr_local_n,  c["rssi_local_n"],  c["lat"], c["lon"])
        segs_r = self._build_segments(snr_remote_n, c["rssi_remote_n"], c["lat"], c["lon"])
        self._run_js(f"setLocalTrack({json.dumps(segs_l)},{json.dumps(c['bounds'])});")
        self._run_js(f"setRemoteTrack({json.dumps(segs_r)});")
        self._run_js(f"setOpacity({self._opacity});")
        # Send subsampled GPS data for cursor interpolation
        gps_t = c["gps_t"]
        lat, lon = c["lat"], c["lon"]
        n = len(gps_t)
        if n > _MAX_CURSOR_PTS:
            idx = np.linspace(0, n - 1, _MAX_CURSOR_PTS, dtype=int)
            coords = list(zip(lat[idx].tolist(), lon[idx].tolist()))
            times  = gps_t[idx].tolist()
        else:
            coords = list(zip(lat.tolist(), lon.tolist()))
            times  = gps_t.tolist()
        self._run_js(f"setTrackData({json.dumps(coords)},{json.dumps(times)});")

    # ── public load API ────────────────────────────────────────────────────
    def load(self, gps_t: np.ndarray, lat: np.ndarray, lon: np.ndarray,
             rssi_t: np.ndarray, rssi_v: np.ndarray,
             noise_v: np.ndarray | None,
             remrssi_v: np.ndarray | None,
             remnoise_v: np.ndarray | None,
             rssi_max: float, source_label: str):

        self._source_label.setText(source_label)
        has_snr = (noise_v is not None and remrssi_v is not None and remnoise_v is not None)

        if not has_snr:
            self._load_legacy(gps_t, lat, lon, rssi_t, rssi_v, rssi_max)
            return

        if len(gps_t) < 2 or len(rssi_t) < 2:
            self._run_js("clearTracks();")
            return

        rssi_i     = np.interp(gps_t, rssi_t, rssi_v)
        noise_i    = np.interp(gps_t, rssi_t, noise_v)
        remrssi_i  = np.interp(gps_t, rssi_t, remrssi_v)
        remnoise_i = np.interp(gps_t, rssi_t, remnoise_v)

        snr_local  = rssi_i    - noise_i
        snr_remote = remrssi_i - remnoise_i

        rssi_local_n  = np.clip(rssi_i    / rssi_max, 0.0, 1.0)
        rssi_remote_n = np.clip(remrssi_i / rssi_max, 0.0, 1.0)

        bounds = [
            [float(lat.min()), float(lon.min())],
            [float(lat.max()), float(lon.max())],
        ]
        self._cache = {
            "lat": lat, "lon": lon, "bounds": bounds, "gps_t": gps_t,
            "snr_local": snr_local, "snr_remote": snr_remote,
            "rssi_local_n": rssi_local_n, "rssi_remote_n": rssi_remote_n,
        }
        self._send_segments()

        snr_local_raw  = np.asarray(rssi_v,    dtype=float) - np.asarray(noise_v,    dtype=float)
        snr_remote_raw = np.asarray(remrssi_v, dtype=float) - np.asarray(remnoise_v, dtype=float)
        t0 = float(rssi_t[0])
        self._time_axis.set_origin(t0)
        self._curve_local.setData(rssi_t, snr_local_raw)
        self._curve_remote.setData(rssi_t, snr_remote_raw)
        all_vals = np.concatenate([snr_local_raw, snr_remote_raw])
        self._graph.setXRange(float(rssi_t[0]), float(rssi_t[-1]), padding=0.02)
        self._graph.setYRange(float(all_vals.min()), float(all_vals.max()), padding=0.05)

    def _load_legacy(self, gps_t: np.ndarray, lat: np.ndarray, lon: np.ndarray,
                     rssi_t: np.ndarray, rssi_v: np.ndarray, rssi_max: float):
        self._cache = None
        self._curve_remote.setData([], [])
        if len(rssi_t):
            t0 = float(rssi_t[0])
            self._time_axis.set_origin(t0)
            self._curve_local.setData(rssi_t, rssi_v)
            self._graph.setXRange(float(rssi_t[0]), float(rssi_t[-1]), padding=0.02)
            self._graph.setYRange(0, rssi_max * 1.05, padding=0)
        else:
            self._curve_local.setData([], [])

        if len(gps_t) < 2 or len(rssi_t) < 2:
            self._run_js("clearTracks();")
            return

        rssi_n = np.clip(np.interp(gps_t, rssi_t, rssi_v) / rssi_max, 0.0, 1.0)
        bounds = [
            [float(lat.min()), float(lon.min())],
            [float(lat.max()), float(lon.max())],
        ]
        segs = self._build_segments(rssi_n, rssi_n, lat, lon)
        self._run_js(f"setLocalTrack({json.dumps(segs)},{json.dumps(bounds)});")
        self._run_js("setRemoteTrack([]);")

    def clear(self):
        self._source_label.setText("Нет данных о качестве связи")
        self._curve_local.setData([], [])
        self._curve_remote.setData([], [])
        self._cache = None
        self._run_js("clearTracks();")
