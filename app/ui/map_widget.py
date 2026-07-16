"""GPS track view on a Google satellite basemap (Leaflet inside QWebEngineView).

Requires internet access to fetch the Leaflet library and Google map tiles.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QUrl, Signal, QObject, Slot
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QComboBox, QLabel, QPushButton, QFrame

from app.core import i18n
from app.core.time_format import format_mmss


_MODE_COLOR_PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#46f0f0", "#f032e6", "#bcf60c", "#fabebe",
    "#008080", "#e6beff", "#9a6324", "#fffac8", "#800000",
]


class _WindHighlightSample(QWidget):
    """Small fixed-size widget painting a wind-exceeded track segment preview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 14)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        y = h // 2

        # Outer glow (white, wide, semi-transparent) — drawn first (bottom layer)
        pen = QPen(QColor(255, 255, 255, 90), 12)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(4, y, w - 4, y)

        # Inner bright line (white, narrower)
        pen = QPen(QColor(255, 255, 255, 200), 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(4, y, w - 4, y)

        # Track on top (red)
        pen = QPen(QColor("#ff0000"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(4, y, w - 4, y)

        p.end()


import math as _math

class _WindArrowWidget(QWidget):
    """Compass-style arrow showing current wind direction (where wind comes FROM)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 52)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._direction = None  # degrees meteorological (where wind blows FROM)

    def set_direction(self, deg: float | None):
        self._direction = deg
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 2

        # Circle background
        p.setPen(QPen(QColor(255, 255, 255, 140), 2))
        p.setBrush(QColor(0, 0, 0, 100))
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        if self._direction is not None:
            # Arrow points INTO wind (where it comes from). 0°=N, clockwise.
            angle_rad = _math.radians(self._direction)
            # Arrow tip (into wind)
            tip_x = cx + r * 0.72 * _math.sin(angle_rad)
            tip_y = cy - r * 0.72 * _math.cos(angle_rad)
            # Arrow tail
            tail_x = cx - r * 0.50 * _math.sin(angle_rad)
            tail_y = cy + r * 0.50 * _math.cos(angle_rad)
            # Arrowhead wings
            wing_r = r * 0.32
            left_x = tip_x + wing_r * _math.sin(angle_rad - _math.pi * 0.75)
            left_y = tip_y - wing_r * _math.cos(angle_rad - _math.pi * 0.75)
            right_x = tip_x + wing_r * _math.sin(angle_rad + _math.pi * 0.75)
            right_y = tip_y - wing_r * _math.cos(angle_rad + _math.pi * 0.75)

            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            pen = QPen(QColor(255, 255, 255, 240), 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(int(tail_x), int(tail_y), int(tip_x), int(tip_y))
            head = QPolygonF([
                QPointF(tip_x, tip_y),
                QPointF(left_x, left_y),
                QPointF(right_x, right_y),
            ])
            p.setBrush(QColor(255, 255, 255, 240))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(head)
        else:
            # No data — draw a small dash
            p.setPen(QPen(QColor(255, 255, 255, 140), 3))
            p.drawLine(int(cx - 8), int(cy), int(cx + 8), int(cy))

        p.end()


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
.time-tooltip-shelf{background:#e6194b;color:#fff;border:none;font-weight:bold;font-size:12px;}
.time-tooltip-shelf.leaflet-tooltip-right::before{border:none;width:36px;height:2px;background:#e6194b;left:-36px;top:50%;margin-top:-1px;margin-left:0;}
.vtol-icon{pointer-events:none;}
.vtol-icon svg{transform-origin:50% 50%;transition:transform 0.05s linear;}
.msr-tip{background:rgba(255,140,0,0.92);color:#fff;border:none;font-size:11px;font-weight:bold;padding:2px 6px;border-radius:3px;white-space:nowrap;}
.msr-tip::before{border-top-color:rgba(255,140,0,0.92);}
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
    var size = 48 * scale;
    var half = size / 2;
    var html = '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24">' +
        '<g transform="rotate(0 12 12)">' +
        '<image href="' + defDataUri + '" x="0" y="0" width="24" height="24"/>' +
        '</g></svg>';
    return L.divIcon({
        html: html,
        className: 'vtol-icon',
        iconSize: [size, size],
        iconAnchor: [half, half]
    });
}
function buildVtol41Icon(scale) {
    var size = 48 * scale;
    var half = size / 2;
    var html = '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24">' +
        '<g transform="rotate(0 12 12)">' +
        '<image href="' + vtol41DataUri + '" x="0" y="0" width="24" height="24"/>' +
        '</g></svg>';
    return L.divIcon({
        html: html,
        className: 'vtol-icon',
        iconSize: [size, size],
        iconAnchor: [half, half]
    });
}
function buildCopterIcon(scale) {
    var size = 48 * scale;
    var half = size / 2;
    var html = '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24">' +
        '<g transform="rotate(0 12 12)">' +
        '<image href="' + copterDataUri + '" x="0" y="0" width="24" height="24"/>' +
        '</g></svg>';
    return L.divIcon({html: html, className: 'vtol-icon', iconSize: [size, size], iconAnchor: [half, half]});
}
function buildVtol31Icon(scale) {
    var size = 48 * scale;
    var half = size / 2;
    var html = '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24">' +
        '<g transform="rotate(0 12 12)">' +
        '<image href="' + vtol31DataUri + '" x="0" y="0" width="24" height="24"/>' +
        '</g></svg>';
    return L.divIcon({html: html, className: 'vtol-icon', iconSize: [size, size], iconAnchor: [half, half]});
}
var vtol41DataUri = '';
var copterDataUri = '';
var vtol31DataUri = '';
var defDataUri = '';
var iconScale = 1;
var lastHeading = 0;
var currentVehicleType = 'plane';
function _buildCurrentIcon(scale) {
    if (currentVehicleType === 'vtol41') return buildVtol41Icon(scale);
    if (currentVehicleType === 'copter') return buildCopterIcon(scale);
    if (currentVehicleType === 'vtol31') return buildVtol31Icon(scale);
    return buildVtolIcon(scale);
}
var vtolIcon = _buildCurrentIcon(iconScale);
var marker = L.marker([0, 0], {icon: vtolIcon, draggable: true}).addTo(map);
marker.bindTooltip('00:00', {permanent: true, direction: 'top', offset: [0, -10], className: 'time-tooltip'});
// ── Callout / info-box state ──────────────────────────────────────────────
var _calloutStyle = 'standard';
var _calloutFields = {time: true, speed: false, distance: false};
var _calloutSpeed = null, _calloutAirspeed = null, _calloutDist = null, _calloutTime = '00:00';
function _calloutHtml() {
    var parts = [];
    if (_calloutFields.time && _calloutTime) parts.push(_calloutTime);
    if (_calloutFields.speed) {
        if (_calloutSpeed !== null && _calloutAirspeed !== null) {
            parts.push('GS: ' + _calloutSpeed + ' м/с');
            parts.push('AS: ' + _calloutAirspeed + ' м/с');
        } else if (_calloutSpeed !== null) {
            parts.push(_calloutSpeed + ' м/с');
        } else if (_calloutAirspeed !== null) {
            parts.push('AS: ' + _calloutAirspeed + ' м/с');
        }
    }
    if (_calloutFields.distance && _calloutDist !== null) parts.push(_calloutDist);
    return parts.join('<br>') || '&nbsp;';
}
function _rebindTooltip(direction, offset, cls) {
    if (marker.getTooltip()) marker.unbindTooltip();
    marker.bindTooltip(_calloutHtml(), {permanent: true, direction: direction, offset: offset, className: cls || 'time-tooltip'});
}
function setIconScale(scale) {
    iconScale = scale;
    vtolIcon = _buildCurrentIcon(iconScale);
    marker.setIcon(vtolIcon);
    var el = marker.getElement();
    var g = el ? el.querySelector('g') : null;
    if (g) g.setAttribute('transform', 'rotate(' + lastHeading + ' 12 12)');
}
function setVehicleType(type) {
    currentVehicleType = type;
    vtolIcon = _buildCurrentIcon(iconScale);
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
var _lastTrackNotifiedTime = null;

trackLine.on('mousemove', function(e) {
    if (trackCoords.length === 0 || trackTimes.length === 0) return;
    var pos = e.latlng;
    var minDist = Infinity;
    var bestIdx = 0;
    for (var i = 0; i < trackCoords.length; i++) {
        var d = Math.pow(pos.lat - trackCoords[i][0], 2) + Math.pow(pos.lng - trackCoords[i][1], 2);
        if (d < minDist) { minDist = d; bestIdx = i; }
    }
    var t = trackTimes[bestIdx];
    if (_lastTrackNotifiedTime === null || Math.abs(t - _lastTrackNotifiedTime) > 0.5) {
        _lastTrackNotifiedTime = t;
        notifyCursorDragged(t);
    }
});

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
function setCursor(lat, lon, timeLabel, heading, speed, distance, airspeed) {
    if (timeLabel !== undefined && timeLabel !== null) _calloutTime = timeLabel;
    if (speed !== undefined && speed !== null) _calloutSpeed = speed;
    if (distance !== undefined && distance !== null) _calloutDist = distance;
    _calloutAirspeed = (airspeed !== undefined) ? airspeed : null;
    marker.setLatLng([lat, lon]);
    if (marker.getTooltip()) {
        marker.setTooltipContent(_calloutHtml());
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

// ── Distance measurement tool ─────────────────────────────────────────────
var measureMode = false;
var measurePoints = [];
var measureLayer = L.layerGroup().addTo(map);
var measureLine = L.polyline([], {color:'#ffcc00', weight:2, dashArray:'5,4', opacity:0.9}).addTo(map);
var measureClickPending = null;

function _haversineM(lat1,lon1,lat2,lon2){
    var R=6371000, dLat=(lat2-lat1)*Math.PI/180, dLon=(lon2-lon1)*Math.PI/180;
    var a=Math.sin(dLat/2)*Math.sin(dLat/2)+
          Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*
          Math.sin(dLon/2)*Math.sin(dLon/2);
    return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}
function _fmtDist(m){
    return m>=1000?(m/1000).toFixed(2)+' км':Math.round(m)+' м';
}
function _measureTotal(){
    var d=0;
    for(var i=1;i<measurePoints.length;i++)
        d+=_haversineM(measurePoints[i-1].lat,measurePoints[i-1].lng,
                       measurePoints[i].lat,measurePoints[i].lng);
    return d;
}
function _redrawMeasure(){
    measureLayer.clearLayers();
    measureLine.setLatLngs(measurePoints);
    if(!measurePoints.length) return;
    var cum=0;
    measurePoints.forEach(function(pt,i){
        if(i>0) cum+=_haversineM(measurePoints[i-1].lat,measurePoints[i-1].lng,pt.lat,pt.lng);
        var txt = i===0 ? '▶ Старт' : _fmtDist(cum);
        L.circleMarker(pt,{radius:5,color:'#ffcc00',fillColor:'#ff6600',fillOpacity:1,weight:2})
         .bindTooltip(txt,{permanent:true,direction:'top',offset:[0,-8],className:'msr-tip'})
         .addTo(measureLayer);
        // segment midpoint label
        if(i>0){
            var mLat=(measurePoints[i-1].lat+pt.lat)/2;
            var mLon=(measurePoints[i-1].lng+pt.lng)/2;
            var seg=_haversineM(measurePoints[i-1].lat,measurePoints[i-1].lng,pt.lat,pt.lng);
            L.marker([mLat,mLon],{icon:L.divIcon({
                className:'',
                html:'<div style="background:rgba(0,0,0,0.7);color:#fff;padding:1px 5px;'+
                     'border-radius:3px;font-size:11px;white-space:nowrap;">'+_fmtDist(seg)+'</div>',
                iconSize:null,iconAnchor:[0,8]
            }),interactive:false}).addTo(measureLayer);
        }
    });
}
function setMeasureMode(active){
    measureMode=active;
    measurePoints=[];
    measureLayer.clearLayers();
    measureLine.setLatLngs([]);
    if(measureClickPending){clearTimeout(measureClickPending);measureClickPending=null;}
    if(active){
        map.doubleClickZoom.disable();
        map.getContainer().style.cursor='crosshair';
    } else {
        map.doubleClickZoom.enable();
        map.getContainer().style.cursor='';
    }
}
map.on('click',function(e){
    if(!measureMode) return;
    if(measureClickPending) return; // swallow click that is part of dblclick
    measureClickPending=setTimeout(function(){
        measureClickPending=null;
        measurePoints.push(e.latlng);
        _redrawMeasure();
    },230);
});
map.on('dblclick',function(e){
    if(!measureMode) return;
    L.DomEvent.stop(e);
    if(measureClickPending){clearTimeout(measureClickPending);measureClickPending=null;}
    if(measurePoints.length>1){
        var total=_measureTotal();
        L.popup({offset:[0,-6],className:'msr-popup'})
         .setLatLng(e.latlng)
         .setContent('<b>Итого: '+_fmtDist(total)+'</b><br><small style="color:#888">Клик — продолжить &nbsp;|&nbsp; ПКМ — сбросить</small>')
         .openOn(map);
    }
    // reset points but stay in measure mode so user can measure again
    measurePoints=[];
    measureLayer.clearLayers();
    measureLine.setLatLngs([]);
});
map.on('contextmenu',function(e){
    if(!measureMode) return;
    L.DomEvent.stop(e);
    measurePoints=[];
    measureLayer.clearLayers();
    measureLine.setLatLngs([]);
    map.closePopup();
});
function setCalloutStyle(style) {
    _calloutStyle = style;
    if (style === 'standard') {
        _rebindTooltip('top', [0, -10]);
    } else if (style === 'shelf') {
        _rebindTooltip('right', [42, 0], 'time-tooltip-shelf');
    } else {
        if (marker.getTooltip()) marker.unbindTooltip();
    }
}
function setCalloutFields(showTime, showSpeed, showDist) {
    _calloutFields = {time: showTime, speed: showSpeed, distance: showDist};
    if (marker.getTooltip()) {
        marker.setTooltipContent(_calloutHtml());
    }
}
</script>
</body></html>
"""


class MapWidget(QWidget):
    cursor_time_changed = Signal(float)
    _BASEMAP_TYPES = [("Спутник", "s"), ("Гибрид", "y"), ("Карта ГШ", "m"), ("Рельеф", "p")]

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

        self.basemap_checkbox = QCheckBox()
        self.basemap_checkbox.setChecked(True)
        self.basemap_checkbox.toggled.connect(self.set_basemap_visible)

        self.basemap_combo = QComboBox()
        for lbl, code in self._BASEMAP_TYPES:
            self.basemap_combo.addItem(lbl, code)
        self.basemap_combo.currentIndexChanged.connect(self._on_basemap_combo_changed)

        self.follow_checkbox = QCheckBox()
        self.follow_checkbox.toggled.connect(self.set_follow)

        self.show_photos_checkbox = QCheckBox()
        self.show_photos_checkbox.setChecked(True)
        self.show_photos_checkbox.toggled.connect(self.set_photo_markers_visible)

        self.photo_count_label = QLabel()
        self.photo_count_label.setStyleSheet("color: white;")
        self._photo_count_cam: int | None = None
        self._photo_count_trig: int | None = None

        self.photo_count_help_label = QLabel("?")
        self.photo_count_help_label.setStyleSheet(
            "QLabel { border: 1px solid gray; border-radius: 8px; padding: 0px 5px; color: white; }"
        )

        self.icon_size_label = QLabel()
        self.icon_size_label.setStyleSheet("color: white;")
        self.icon_size_combo = QComboBox()
        self.icon_size_combo.addItems(["x0.5", "x1", "x2", "x5"])
        self.icon_size_combo.setCurrentText("x1")
        self.icon_size_combo.currentTextChanged.connect(self._on_icon_size_changed)

        self.show_errors_checkbox = QCheckBox()
        self.show_errors_checkbox.setChecked(True)
        self.show_errors_checkbox.toggled.connect(self.set_error_markers_visible)
        self.show_errors_checkbox.toggled.connect(self._on_show_errors_toggled)

        self.show_wind_checkbox = QCheckBox()
        self.show_wind_checkbox.setChecked(True)
        self.show_wind_checkbox.toggled.connect(self.set_wind_panel_visible)

        self.measure_btn = QPushButton("📏")
        self.measure_btn.setCheckable(True)
        self.measure_btn.setFixedWidth(36)
        self.measure_btn.setFixedHeight(24)
        self.measure_btn.toggled.connect(self._on_measure_toggled)

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
        self._error_legend_title = QLabel()
        self._error_legend_title.setStyleSheet("color: white; font-weight: bold;")
        error_legend_layout.addWidget(self._error_legend_title)
        self._error_legend_labels = []
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
            label = QLabel()
            label.setStyleSheet("color: white;")
            row.addWidget(swatch)
            row.addWidget(label)
            row.addStretch()
            error_legend_layout.addLayout(row)
            self._error_legend_labels.append((text, label))
        self.error_legend.adjustSize()
        self.error_legend.setVisible(self.show_errors_checkbox.isChecked())

        self.wind_panel = QWidget(self.view)
        self.wind_panel.setStyleSheet(
            "background-color: rgba(20, 20, 20, 190); border-radius: 6px;"
        )
        wind_panel_layout = QVBoxLayout(self.wind_panel)
        wind_panel_layout.setContentsMargins(8, 6, 8, 6)
        wind_panel_layout.setSpacing(2)
        self._wind_title_label = QLabel()
        self._wind_title_label.setStyleSheet("color: white; font-weight: bold;")
        self.wind_value_label = QLabel(f"{self._max_wind:.0f} м/с")
        self.wind_value_label.setStyleSheet("color: white;")
        wind_value_row = QHBoxLayout()
        wind_value_row.setSpacing(6)
        wind_value_row.addWidget(self.wind_value_label)
        wind_value_row.addWidget(_WindHighlightSample())
        wind_value_row.addStretch()
        wind_panel_layout.addWidget(self._wind_title_label)
        wind_panel_layout.addLayout(wind_value_row)

        # Separator + "Текущий ветер" header
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgba(255,255,255,80);")
        wind_panel_layout.addWidget(sep)
        self._wind_current_title = QLabel()
        self._wind_current_title.setStyleSheet("color: white; font-weight: bold;")
        wind_panel_layout.addWidget(self._wind_current_title)

        # Current wind: arrow + speed centered in panel
        self._wind_arrow = _WindArrowWidget()
        self._wind_current_label = QLabel("—")
        self._wind_current_label.setStyleSheet("color: white;")
        self._wind_current_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wind_current_center = QHBoxLayout()
        wind_current_center.setSpacing(8)
        wind_current_center.addStretch()
        wind_current_center.addWidget(self._wind_arrow)
        wind_current_center.addWidget(self._wind_current_label)
        wind_current_center.addStretch()
        wind_panel_layout.addLayout(wind_current_center)

        self.wind_panel.adjustSize()
        self.wind_panel.setVisible(self.show_wind_checkbox.isChecked())

        self._t = np.array([])
        self._lat = np.array([])
        self._lon = np.array([])
        # Subsampled versions used for JS segment calls (mode colours, wind highlight)
        self._js_t = np.array([])
        self._js_lat = np.array([])
        self._js_lon = np.array([])
        self._t0 = 0.0
        self._heading_t = np.array([])
        self._heading_v = np.array([])
        self._mode_events: list[tuple[float, str]] = []
        self._mode_colors: dict[str, str] = {}
        self._wind_t = np.array([])
        self._wind_speed = np.array([])
        self._wind_dir = np.array([])
        self._gnd_speed_t = np.array([])
        self._gnd_speed_v = np.array([])
        self._airspeed_t = np.array([])
        self._airspeed_v = np.array([])
        self._cum_dist = np.array([])

        self._position_error_legend()
        self._position_wind_panel()
        self.error_legend.raise_()
        self.wind_panel.raise_()

        i18n.register(self._retranslateUi)
        self._retranslateUi()

    def _retranslateUi(self):
        tr = i18n.tr
        self.basemap_checkbox.setText(tr("Подложка"))
        for i, (lbl, _) in enumerate(self._BASEMAP_TYPES):
            self.basemap_combo.setItemText(i, tr(lbl))
        self.follow_checkbox.setText(tr("Центрировать"))
        self.show_photos_checkbox.setText(tr("Фотографии"))
        self.icon_size_label.setText(tr("Иконка:"))
        self.show_errors_checkbox.setText(tr("Ошибки"))
        self.show_wind_checkbox.setText(tr("Ветер"))
        self._error_legend_title.setText(tr("Ошибки и сбои"))
        for ru_text, label in self._error_legend_labels:
            label.setText(tr(ru_text))
        self._wind_title_label.setText(tr("Допустимый ветер"))
        self._wind_current_title.setText(tr("Текущий ветер"))
        self.photo_count_help_label.setToolTip(
            f"<span style='color:#ffeb3b;'>&#9632;</span> &mdash; "
            f"{tr('количество отправленных фотоимпульсов в камеру')}<br>"
            f"<span style='color:#3cb44b;'>&#9632;</span> &mdash; "
            f"{tr('количество полученных фотоимпульсов от камеры')}"
        )
        self.set_photo_counts(self._photo_count_cam, self._photo_count_trig)
        self.error_legend.adjustSize()
        self.wind_panel.adjustSize()

    def _on_load_finished(self, ok: bool):
        self._ready = ok
        if ok:
            assets = Path(__file__).resolve().parent.parent.parent / "assets"
            for js_var, filename in (
                ("vtol41DataUri", "vtol41_icon.svg"),
                ("copterDataUri", "copter_icon.svg"),
                ("vtol31DataUri", "vtol31_icon.svg"),
                ("defDataUri",    "def_icon.svg"),
            ):
                try:
                    uri = "data:image/svg+xml;base64," + base64.b64encode((assets / filename).read_bytes()).decode()
                except Exception:
                    uri = ""
                self.view.page().runJavaScript(f"var {js_var} = '{uri}';")
            self.view.page().runJavaScript(
                "vtolIcon = _buildCurrentIcon(iconScale); marker.setIcon(vtolIcon);"
            )
        for script in self._pending_js:
            self.view.page().runJavaScript(script)
        self._pending_js.clear()

    def _run_js(self, script: str):
        if self._ready:
            self.view.page().runJavaScript(script)
        else:
            self._pending_js.append(script)

    def set_vehicle_type(self, type_str: str):
        js_type = {
            "VTOL 4+1":        "vtol41",
            "Коптер":          "copter",
            "VTOL 2+1 vector": "vtol31",
        }.get(type_str, "plane")
        self._run_js(f"setVehicleType('{js_type}');")

    def set_icon_mapping(self, mapping: dict[str, str]):
        assets = Path(__file__).resolve().parent.parent.parent / "assets"
        js_var_map = {
            "VTOL 4+1":        "vtol41DataUri",
            "Коптер":          "copterDataUri",
            "VTOL 2+1 vector": "vtol31DataUri",
            "По умолчанию":    "defDataUri",
        }
        for vtype, js_var in js_var_map.items():
            filename = mapping.get(vtype)
            if not filename:
                continue
            try:
                import base64 as _b64
                uri = "data:image/svg+xml;base64," + _b64.b64encode((assets / filename).read_bytes()).decode()
            except Exception:
                uri = ""
            self._run_js(f"var {js_var} = '{uri}';")
        self._run_js("vtolIcon = _buildCurrentIcon(iconScale); marker.setIcon(vtolIcon);")

    def set_time_origin(self, t0: float):
        self._t0 = t0

    def set_track(self, t: np.ndarray, lat: np.ndarray, lon: np.ndarray,
                  cum_dist: np.ndarray | None = None):
        self._t, self._lat, self._lon = t, lat, lon
        if cum_dist is not None and len(cum_dist) == len(t):
            self._cum_dist = cum_dist
        elif len(lat) >= 2:
            lat_r = np.radians(lat)
            lon_r = np.radians(lon)
            dlat = np.diff(lat_r)
            dlon = np.diff(lon_r)
            a = np.sin(dlat / 2) ** 2 + np.cos(lat_r[:-1]) * np.cos(lat_r[1:]) * np.sin(dlon / 2) ** 2
            segs = 2 * 6371000.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
            self._cum_dist = np.concatenate([[0.0], np.cumsum(segs)])
        else:
            self._cum_dist = np.zeros(len(lat))
        # Subsample to ≤6000 points for JS; full arrays kept for Python interpolation.
        # The subsampled arrays are also reused for mode-segment and wind-highlight
        # JS calls so those never exceed the same size limit.
        _MAX = 6000
        if len(t) > _MAX:
            idx = np.round(np.linspace(0, len(t) - 1, _MAX)).astype(int)
            self._js_lat, self._js_lon, self._js_t = lat[idx], lon[idx], t[idx]
        else:
            self._js_lat, self._js_lon, self._js_t = lat, lon, t
        coords = list(zip(self._js_lat.tolist(), self._js_lon.tolist()))
        self._run_js(f"setTrackWithTimes({json.dumps(coords)}, {json.dumps(self._js_t.tolist())});")
        self._update_mode_segments()
        self._update_wind_highlight()

    def set_wind_speed_data(self, t: np.ndarray, speed: np.ndarray):
        self._wind_t, self._wind_speed = t, speed
        self._wind_dir = np.array([])
        self._wind_arrow.set_direction(None)
        self._wind_current_label.setText("—")
        self._update_wind_highlight()

    def set_wind_data(self, t: np.ndarray, speed: np.ndarray, direction: np.ndarray):
        self._wind_t, self._wind_speed, self._wind_dir = t, speed, direction
        self._wind_arrow.set_direction(None)
        self._wind_current_label.setText("—")
        self._update_wind_highlight()

    def set_wind_panel_visible(self, visible: bool):
        self.wind_panel.setVisible(visible)
        if visible:
            self._update_wind_highlight()
        else:
            self._run_js("setWindHighlight([]);")

    def set_max_wind(self, max_wind: float):
        self._max_wind = max_wind
        self.wind_value_label.setText(f"{self._max_wind:.0f} м/с")
        self.wind_panel.adjustSize()
        self._position_wind_panel()
        self._update_wind_highlight()

    def _on_show_errors_toggled(self, checked: bool):
        self.error_legend.setVisible(checked)

    def _update_wind_highlight(self):
        if len(self._js_t) == 0 or len(self._wind_t) == 0:
            self._run_js("setWindHighlight([]);")
            return

        # Interpolate wind speed onto the JS-subsampled track timestamps
        interp_speed = np.interp(self._js_t, self._wind_t, self._wind_speed)
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
                segments_js.append(list(zip(
                    self._js_lat[lo:hi + 1].tolist(),
                    self._js_lon[lo:hi + 1].tolist(),
                )))
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

        end_time = float(self._js_t[-1]) if len(self._js_t) else 0.0
        segments_js = []
        for i, (t_start, name) in enumerate(events):
            t_end = events[i + 1][0] if i + 1 < len(events) else end_time
            lo = int(np.searchsorted(self._js_t, t_start))
            hi = int(np.searchsorted(self._js_t, t_end))
            lo = max(0, min(lo, len(self._js_t) - 1))
            hi = max(0, min(hi, len(self._js_t) - 1))
            if hi <= lo:
                continue
            coords = list(zip(self._js_lat[lo:hi + 1].tolist(), self._js_lon[lo:hi + 1].tolist()))
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

    def set_map_speed_data(self, t: np.ndarray, speed: np.ndarray):
        self._gnd_speed_t, self._gnd_speed_v = t, speed

    def clear_map_speed_data(self):
        self._gnd_speed_t = np.array([])
        self._gnd_speed_v = np.array([])

    def set_map_airspeed_data(self, t: np.ndarray, speed: np.ndarray):
        self._airspeed_t, self._airspeed_v = t, speed

    def clear_map_airspeed_data(self):
        self._airspeed_t = np.array([])
        self._airspeed_v = np.array([])

    def set_callout_style(self, style: str):
        self._run_js(f"setCalloutStyle('{style}');")

    def set_callout_fields(self, show_time: bool, show_speed: bool, show_dist: bool):
        t = 'true' if show_time else 'false'
        s = 'true' if show_speed else 'false'
        d = 'true' if show_dist else 'false'
        self._run_js(f"setCalloutFields({t},{s},{d});")

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

        speed_arg = "null"
        if len(self._gnd_speed_t):
            sidx = int(np.searchsorted(self._gnd_speed_t, t))
            sidx = max(0, min(sidx, len(self._gnd_speed_t) - 1))
            speed_arg = f'"{float(self._gnd_speed_v[sidx]):.1f}"'

        airspeed_arg = "null"
        if len(self._airspeed_t):
            aidx = int(np.searchsorted(self._airspeed_t, t))
            aidx = max(0, min(aidx, len(self._airspeed_t) - 1))
            airspeed_arg = f'"{float(self._airspeed_v[aidx]):.1f}"'

        dist_arg = "null"
        if len(self._cum_dist) > idx:
            d_m = float(self._cum_dist[idx])
            dist_arg = f'"{d_m / 1000:.2f} км"' if d_m >= 1000 else f'"{d_m:.0f} м"'

        self._run_js(
            f"setCursor({self._lat[idx]}, {self._lon[idx]}, '{label}', "
            f"{heading_arg}, {speed_arg}, {dist_arg}, {airspeed_arg});"
        )

        # Update wind arrow + current speed label
        if len(self._wind_t) > 0:
            widx = int(np.searchsorted(self._wind_t, t))
            widx = max(0, min(widx, len(self._wind_t) - 1))
            w_speed = float(self._wind_speed[widx])
            self._wind_current_label.setText(f"{w_speed:.1f} м/с")
            if len(self._wind_dir) == len(self._wind_speed):
                w_dir = float(self._wind_dir[widx])
                self._wind_arrow.set_direction(w_dir)
            else:
                self._wind_arrow.set_direction(None)

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
        self._photo_count_cam = cam_count
        self._photo_count_trig = trig_count
        tr = i18n.tr
        if not cam_count and not trig_count:
            self.photo_count_label.setText(tr("Количество фото: нет"))
            return
        parts = []
        if cam_count:
            parts.append(f"<span style='color:#ffeb3b;'>&#9632;</span> {cam_count}")
        if trig_count:
            parts.append(f"<span style='color:#3cb44b;'>&#9632;</span> {trig_count}")
        self.photo_count_label.setText(tr("Количество фото: ") + "&nbsp;&nbsp;&nbsp;".join(parts))

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

    def _on_measure_toggled(self, checked: bool):
        self._run_js(f"setMeasureMode({'true' if checked else 'false'});")

    def _on_map_cursor_dragged(self, time_val: float):
        """Called when user drags the marker on the map."""
        self.cursor_time_changed.emit(time_val)
