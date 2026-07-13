"""Photo Geotagging tab: a table listing every photo trigger (CAM/TRIG)
with its position, altitude, attitude, and ground speed at capture time —
the inputs typically needed to assemble an orthophoto plan.

The tab is split into a small map on the left (showing every photo position)
and the table on the right; hovering a row highlights the matching point on
the map and vice versa.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
from PIL.ExifTags import IFD
from PIL.TiffImagePlugin import IFDRational
from PySide6.QtCore import Qt, QUrl, QSize, QRect, Signal, QObject, Slot, QThread
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPalette
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QFileDialog, QAbstractItemView, QSplitter, QMessageBox, QCheckBox,
    QListWidget, QListWidgetItem, QListView, QComboBox, QMenu, QDialog, QDialogButtonBox,
    QApplication, QProgressDialog, QSlider, QSpinBox, QFormLayout,
)

from app.core import i18n
from app.core.log_loader import LogData
from app.core.time_format import format_mmss, format_gps_time

_GPS_LAT_CANDIDATES = [("GPS", "Lat", "Lng"), ("GPS", "Lat", "Lon"), ("GLOBAL_POSITION_INT", "lat", "lon")]
# (msg_type, field, divisor) -> meters
_ALT_AMSL_CANDIDATES = [("GPS", "Alt", 1.0), ("BARO", "Alt", 1.0)]
_ALT_AGL_CANDIDATES = [("CTUN", "Alt", 1.0), ("RFND", "Dist", 100.0)]
_GROUND_SPEED_CANDIDATES = [("GPS", "Spd", 1.0), ("VFR_HUD", "groundspeed", 1.0)]
# (msg_type, roll_field, pitch_field, yaw_field, values_are_radians)
_ATTITUDE_CANDIDATES = [
    ("ATT", "Roll", "Pitch", "Yaw", False),
    ("ATTITUDE", "roll", "pitch", "yaw", True),
]

_COLUMNS = [
    "№", "Время полета", "Время GPS", "Широта", "Долгота",
    "Высота AMSL (м)", "Высота AGL (м)", "Крен (°)", "Тангаж (°)", "Курс (°)",
    "Путевая скорость (м/с)", "Интервал (с)", "Расстояние (м)",
]

_GNSS_LAT_CANDIDATES = ["lat", "latitude", "y"]
_GNSS_LON_CANDIDATES = ["lon", "lng", "longitude", "x"]
_GNSS_ALT_CANDIDATES = ["alt", "altitude", "height", "h", "z"]
_GNSS_NAME_CANDIDATES = ["name", "file", "filename", "photo", "id", "point", "label"]

_GNSS_COLUMNS = ["№", "Файл/имя", "Широта", "Долгота", "Высота (м)"]

_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

_EARTH_RADIUS_M = 6371000.0


def _haversine_m(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _decimal_to_dms_rational(value: float):
    value = abs(value)
    degrees = int(value)
    minutes_full = (value - degrees) * 60
    minutes = int(minutes_full)
    seconds = round((minutes_full - minutes) * 60 * 1000)
    return (IFDRational(degrees, 1), IFDRational(minutes, 1), IFDRational(seconds, 1000))


def _write_gps_exif(path: Path, lat: float, lon: float, alt: float | None, jpeg_quality=None):
    """Write GPS coordinates into a photo's EXIF GPS IFD, preserving image data.
    jpeg_quality: None = keep original quality, int = re-encode at given quality (1-95)."""
    data = path.read_bytes()
    img = Image.open(io.BytesIO(data))
    img.load()
    fmt = img.format

    exif = img.getexif()
    gps_ifd = exif.get_ifd(IFD.GPSInfo)
    gps_ifd[1] = "N" if lat >= 0 else "S"
    gps_ifd[2] = _decimal_to_dms_rational(lat)
    gps_ifd[3] = "E" if lon >= 0 else "W"
    gps_ifd[4] = _decimal_to_dms_rational(lon)
    if alt is not None:
        gps_ifd[5] = 0
        gps_ifd[6] = IFDRational(int(round(abs(alt) * 100)), 100)

    save_kwargs = {"exif": exif}
    if fmt == "JPEG":
        save_kwargs["quality"] = jpeg_quality if isinstance(jpeg_quality, int) else "keep"
    img.save(path, format=fmt, **save_kwargs)
    img.close()


def _strip_gps_exif(path: Path):
    """Remove GPS coordinates/altitude from a photo's EXIF, preserving image data."""
    data = path.read_bytes()
    img = Image.open(io.BytesIO(data))
    img.load()
    fmt = img.format

    exif = img.getexif()
    if int(IFD.GPSInfo) not in exif:
        img.close()
        return
    del exif[int(IFD.GPSInfo)]

    save_kwargs = {"exif": exif}
    if fmt == "JPEG":
        save_kwargs["quality"] = "keep"
    img.save(path, format=fmt, **save_kwargs)
    img.close()


def _read_gps_exif(path: Path) -> tuple[float, float, float | None] | None:
    """Read GPS coordinates (and altitude, if present) from a photo's EXIF, if any."""
    def dms_to_dec(dms, ref) -> float:
        d, m, s = dms
        val = float(d) + float(m) / 60 + float(s) / 3600
        return -val if ref in ("S", "W") else val

    try:
        img = Image.open(path)
        gps = img.getexif().get_ifd(IFD.GPSInfo)
    except Exception:
        return None
    if not gps or 2 not in gps or 4 not in gps:
        return None
    try:
        lat = dms_to_dec(gps[2], gps.get(1, "N"))
        lon = dms_to_dec(gps[4], gps.get(3, "E"))
    except Exception:
        return None
    alt = None
    if 6 in gps:
        try:
            alt = float(gps[6])
            if gps.get(5) == 1:
                alt = -alt
        except Exception:
            alt = None
    return lat, lon, alt


def _format_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / 1024 / 1024:.1f} МБ"
    return f"{num_bytes / 1024:.0f} КБ"


def _photo_info_lines(path: Path) -> list[str]:
    """Build a human-readable list of properties for a photo: dimensions, file size,
    camera, capture date, and GPS coordinates (for the large-preview overlay)."""
    lines = [path.name]
    img = None
    try:
        img = Image.open(path)
        w, h = img.size
        lines.append(f"{w}×{h} px")
    except Exception:
        pass
    try:
        lines.append(_format_size(path.stat().st_size))
    except OSError:
        pass
    if img is not None:
        try:
            exif = img.getexif()
            make = exif.get(271, "")
            model = exif.get(272, "")
            camera = " ".join(s for s in (str(make).strip(), str(model).strip()) if s)
            if camera:
                lines.append(camera)
            dt = exif.get(36867) or exif.get(306)
            if dt:
                lines.append(f"Снято: {dt}")
        except Exception:
            pass
    gps = _read_gps_exif(path)
    if gps:
        lat, lon, alt = gps
        alt_text = f", высота {alt:.1f} м" if alt is not None else ""
        lines.append(f"GPS: {lat:.6f}, {lon:.6f}{alt_text}")
    else:
        lines.append("GPS: координаты не записаны")
    return lines


class _PhotoViewerDialog(QDialog):
    """Large preview of a single photo with its properties overlaid at the bottom."""

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(path.name)

        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        max_w = int(avail.width() * 0.8) if avail else 1000
        max_h = int(avail.height() * 0.8) if avail else 800

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            pixmap = QPixmap(400, 300)
            pixmap.fill(Qt.darkGray)
        else:
            pixmap = pixmap.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        lines = _photo_info_lines(path)
        line_height = 20
        panel_height = line_height * len(lines) + 14

        canvas = QPixmap(pixmap.width(), pixmap.height() + panel_height)
        canvas.fill(Qt.black)
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, pixmap)
        panel_rect = QRect(0, pixmap.height(), canvas.width(), panel_height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.drawRect(panel_rect)
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor("white"))
        y = panel_rect.top() + 7
        for line in lines:
            painter.drawText(QRect(10, y, canvas.width() - 20, line_height), Qt.AlignVCenter | Qt.AlignLeft, line)
            y += line_height
        painter.end()

        label = QLabel()
        label.setPixmap(canvas)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        self.setFixedSize(canvas.size())


class _GeotagPreviewDialog(QDialog):
    """Shows the filename -> coordinates mapping before writing GPS EXIF tags."""

    def __init__(self, files: list[Path], points: list[dict], parent=None):
        super().__init__(parent)
        tr = i18n.tr
        self.setWindowTitle(tr("Предпросмотр геотегирования"))
        self.resize(520, 400)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{tr('Будет геотегировано фотографий')}: {len(files)}. {tr('Проверьте соответствие:')}"))

        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels([tr("Файл"), tr("Широта"), tr("Долгота"), tr("Высота (м)")])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setRowCount(len(files))
        for r, (f, p) in enumerate(zip(files, points)):
            values = [
                f.name, f"{p['lat']:.6f}", f"{p['lon']:.6f}",
                f"{p['alt']:.1f}" if p.get("alt") is not None else "—",
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(r, c, item)
        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("Геотегировать изображения"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Отмена"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def _thumbnail_icon(path: Path, size: int, has_gps: bool, excluded: bool = False) -> QIcon:
    """Build a thumbnail icon, with a globe/exclamation badge if the photo already has GPS EXIF.
    Excluded photos are rendered dimmed/grayed out."""
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.darkGray)
    else:
        pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    if not has_gps and not excluded:
        return QIcon(pixmap)

    canvas = QPixmap(pixmap.size())
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, pixmap)
    if has_gps:
        badge_size = max(18, size // 4)
        badge_rect = QRect(canvas.width() - badge_size - 2, 2, badge_size, badge_size)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawEllipse(badge_rect)
        painter.setFont(QFont("Segoe UI Emoji", int(badge_size * 0.55)))
        painter.setPen(QColor("#ffd54f"))
        painter.drawText(badge_rect, Qt.AlignCenter, "🌐❗")
    if excluded:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(60, 60, 60, 160))
        painter.drawRect(canvas.rect())
    painter.end()
    return QIcon(canvas)


def _thumbnail_icon_from_bytes(thumb_bytes: bytes, has_gps: bool, excluded: bool, size: int = 96) -> QIcon:
    """Build thumbnail icon from pre-loaded JPEG bytes (fast path, no file I/O)."""
    pixmap = QPixmap()
    if thumb_bytes:
        pixmap.loadFromData(thumb_bytes)
        pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if pixmap.isNull():
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor("#333333"))

    if not has_gps and not excluded:
        return QIcon(pixmap)

    canvas = QPixmap(pixmap.size())
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, pixmap)
    if has_gps:
        badge_size = max(18, size // 4)
        badge_rect = QRect(canvas.width() - badge_size - 2, 2, badge_size, badge_size)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawEllipse(badge_rect)
        painter.setFont(QFont("Segoe UI Emoji", int(badge_size * 0.55)))
        painter.setPen(QColor("#ffd54f"))
        painter.drawText(badge_rect, Qt.AlignCenter, "🌐❗")
    if excluded:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(60, 60, 60, 160))
        painter.drawRect(canvas.rect())
    painter.end()
    return QIcon(canvas)


class _PhotoLoader(QThread):
    """Background thread: reads GPS EXIF and generates thumbnails using PIL.
    Opens each file once — much faster than QPixmap for large folders."""
    photo_ready = Signal(int, object, bytes)  # row, gps_tuple|None, jpeg_bytes

    def __init__(self, files: list[Path], thumb_size: int = 96, parent=None):
        super().__init__(parent)
        self._files = files
        self._thumb_size = thumb_size
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for row, path in enumerate(self._files):
            if self._stop:
                break
            gps, thumb_bytes = self._load_one(path)
            self.photo_ready.emit(row, gps, thumb_bytes)

    def _load_one(self, path: Path):
        gps = None
        thumb_bytes = b''
        try:
            img = Image.open(path)
            try:
                gps_ifd = img.getexif().get_ifd(IFD.GPSInfo)
                if gps_ifd and 2 in gps_ifd and 4 in gps_ifd:
                    def _dms(dms, ref):
                        d, m, s = dms
                        v = float(d) + float(m) / 60 + float(s) / 3600
                        return -v if ref in ("S", "W") else v
                    lat = _dms(gps_ifd[2], gps_ifd.get(1, "N"))
                    lon = _dms(gps_ifd[4], gps_ifd.get(3, "E"))
                    alt = None
                    if 6 in gps_ifd:
                        alt = float(gps_ifd[6])
                        if gps_ifd.get(5) == 1:
                            alt = -alt
                    gps = (lat, lon, alt)
            except Exception:
                pass
            img.thumbnail((self._thumb_size, self._thumb_size), Image.LANCZOS)
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=75)
            thumb_bytes = buf.getvalue()
        except Exception:
            pass
        return gps, thumb_bytes


class _PhotoMapBridge(QObject):
    """JavaScript bridge to receive marker hover events from the mini map."""
    marker_hovered = Signal(int)

    @Slot(int)
    def onMarkerHovered(self, index: int):
        self.marker_hovered.emit(index)


_PHOTO_MAP_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
html,body,#map{height:100%;margin:0;padding:0;background:#222;}
.gnss-triangle{width:0;height:0;border-left:7px solid transparent;border-right:7px solid transparent;
    border-bottom:14px solid #e6194b;filter:drop-shadow(0 0 1px #fff);}
.gnss-triangle-excluded{width:0;height:0;border-left:7px solid transparent;border-right:7px solid transparent;
    border-bottom:14px solid #888888;filter:drop-shadow(0 0 1px #fff);opacity:0.7;}
.gnss-triangle-highlighted{width:0;height:0;border-left:10px solid transparent;border-right:10px solid transparent;
    border-bottom:20px solid #ffeb3b;filter:drop-shadow(0 0 3px #fff);}
.map-legend{background:rgba(0,0,0,0.7);color:#fff;padding:6px 8px;border-radius:4px;
    font:11px "Segoe UI",sans-serif;line-height:1.7;}
.legend-row{display:flex;align-items:center;gap:6px;white-space:nowrap;}
.legend-swatch{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;flex-shrink:0;}
.legend-circle-green{border-radius:50%;background:#0b3d0b;border:2px solid #3cb44b;width:9px;height:9px;}
.legend-circle-yellow{border-radius:50%;background:#ffeb3b;border:2px solid #ffeb3b;width:9px;height:9px;}
.legend-circle-gray{border-radius:50%;background:#555555;border:2px solid #888888;width:9px;height:9px;}
.legend-triangle-red{width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;
    border-bottom:11px solid #e6194b;}
.legend-triangle-gray{width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;
    border-bottom:11px solid #888888;opacity:0.7;}
.legend-line{width:14px;height:0;border-top:2px dashed #ffeb3b;}
</style>
</head>
<body>
<div id="map"></div>
<script>
var map = L.map('map', {zoomSnap: 0, attributionControl: false}).setView([0, 0], 2);
L.tileLayer('tilecache://tile/s/{z}/{x}/{y}', {
    maxZoom: 21
}).addTo(map);

var pathLine = L.polyline([], {color: '#ffeb3b', weight: 1, opacity: 0.6}).addTo(map);
var markers = [];
var highlightedIndex = -1;
var excludedPointIndices = [];
var gnssIcon = L.divIcon({
    className: 'gnss-triangle-icon',
    html: '<div class="gnss-triangle"></div>',
    iconSize: [14, 14],
    iconAnchor: [7, 14]
});
var gnssIconExcluded = L.divIcon({
    className: 'gnss-triangle-icon',
    html: '<div class="gnss-triangle-excluded"></div>',
    iconSize: [14, 14],
    iconAnchor: [7, 14]
});
var gnssIconHighlighted = L.divIcon({
    className: 'gnss-triangle-icon',
    html: '<div class="gnss-triangle-highlighted"></div>',
    iconSize: [20, 20],
    iconAnchor: [10, 20]
});
var gnssMarkers = [];
var gnssExcludedSet = [];
var highlightedGnssIndex = -1;
var followEnabled = false;

var legend = L.control({position: 'bottomright'});
legend.onAdd = function() {
    var div = L.DomUtil.create('div', 'map-legend');
    div.innerHTML =
        '<div class="legend-row"><span class="legend-swatch"><span class="legend-circle-green"></span></span>Фотография</div>' +
        '<div class="legend-row"><span class="legend-swatch"><span class="legend-circle-yellow"></span></span>Выделенная фотография</div>' +
        '<div class="legend-row"><span class="legend-swatch"><span class="legend-circle-gray"></span></span>Исключенная фотография</div>' +
        '<div class="legend-row"><span class="legend-swatch"><span class="legend-triangle-red"></span></span>Геометка GNSS</div>' +
        '<div class="legend-row"><span class="legend-swatch"><span class="legend-triangle-gray"></span></span>Исключенная Геометка GNSS</div>' +
        '<div class="legend-row"><span class="legend-swatch"><span class="legend-line"></span></span>Маршрут</div>';
    L.DomEvent.disableClickPropagation(div);
    return div;
};
legend.addTo(map);

var pybridge = null;
if (typeof QWebChannel !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function(channel) {
        pybridge = channel.objects.pybridge;
    });
}
function notifyHover(idx) {
    if (pybridge) pybridge.onMarkerHovered(idx);
}

function setPoints(coords) {
    pathLine.setLatLngs(coords);
    markers.forEach(function(m) { m.remove(); });
    markers = [];
    highlightedIndex = -1;
    excludedPointIndices = [];
    coords.forEach(function(c, i) {
        var m = L.circleMarker(c, {radius: 5, color: '#3cb44b', weight: 2, fillColor: '#0b3d0b', fillOpacity: 1})
            .bindTooltip('#' + (i + 1))
            .addTo(map);
        m.on('mouseover', function() { notifyHover(i); });
        m.on('mouseout', function() { notifyHover(-1); });
        markers.push(m);
    });
    if (coords.length > 0) {
        map.fitBounds(pathLine.getBounds(), {padding: [30, 30]});
    }
}

function setPointsExcluded(excludedIndices) {
    excludedPointIndices = excludedIndices;
    markers.forEach(function(m, i) {
        if (i === highlightedIndex) return;
        var excluded = excludedIndices.includes(i);
        m.setStyle({radius: 5, color: excluded ? '#888888' : '#3cb44b', fillColor: excluded ? '#555555' : '#0b3d0b'});
    });
}

function fitAll() {
    if (markers.length > 0) {
        map.fitBounds(pathLine.getBounds(), {padding: [30, 30]});
    }
}

function setFollow(enabled) {
    followEnabled = enabled;
}

function highlightPoint(idx) {
    if (highlightedIndex >= 0 && highlightedIndex < markers.length) {
        var wasExcluded = excludedPointIndices.includes(highlightedIndex);
        markers[highlightedIndex].setStyle({
            radius: 5,
            color: wasExcluded ? '#888888' : '#3cb44b',
            fillColor: wasExcluded ? '#555555' : '#0b3d0b'
        });
    }
    highlightedIndex = idx;
    if (idx >= 0 && idx < markers.length) {
        markers[idx].setStyle({radius: 9, color: '#ffeb3b', fillColor: '#ffeb3b'});
        markers[idx].bringToFront();
        if (followEnabled) {
            map.panTo(markers[idx].getLatLng(), {animate: true});
        }
    }
}

function setGnssPoints(coords) {
    gnssMarkers.forEach(function(m) { m.remove(); });
    gnssMarkers = [];
    coords.forEach(function(c, i) {
        var m = L.marker(c, {icon: gnssIcon}).bindTooltip('GNSS #' + (i + 1)).addTo(map);
        gnssMarkers.push(m);
    });
}

function setGnssExcluded(excludedIndices) {
    gnssExcludedSet = excludedIndices;
    gnssMarkers.forEach(function(m, i) {
        if (i === highlightedGnssIndex) return;
        m.setIcon(excludedIndices.includes(i) ? gnssIconExcluded : gnssIcon);
    });
}
function highlightGnssPoint(idx) {
    if (highlightedGnssIndex >= 0 && highlightedGnssIndex < gnssMarkers.length) {
        gnssMarkers[highlightedGnssIndex].setIcon(
            gnssExcludedSet.includes(highlightedGnssIndex) ? gnssIconExcluded : gnssIcon
        );
    }
    highlightedGnssIndex = idx;
    if (idx >= 0 && idx < gnssMarkers.length) {
        gnssMarkers[idx].setIcon(gnssIconHighlighted);
        gnssMarkers[idx].bringToFront();
    }
}
</script>
</body></html>
"""


class _PhotoMapWidget(QWidget):
    marker_hovered = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWebEngineView()
        self._ready = False
        self._pending_js: list[str] = []

        self._bridge = _PhotoMapBridge()
        self._bridge.marker_hovered.connect(self.marker_hovered)

        channel = QWebChannel(self.view.page())
        channel.registerObject("pybridge", self._bridge)
        self.view.page().setWebChannel(channel)

        self.view.loadFinished.connect(self._on_load_finished)
        self.view.setHtml(_PHOTO_MAP_HTML, QUrl("https://maps.google.com/"))

        self.center_checkbox = QCheckBox()
        self.center_checkbox.toggled.connect(self.set_follow)
        self.center_checkbox.setChecked(True)

        self.fit_checkbox = QCheckBox()
        self.fit_checkbox.toggled.connect(self._on_fit_toggled)
        self.fit_checkbox.setChecked(True)

        controls = QHBoxLayout()
        controls.addWidget(self.center_checkbox)
        controls.addWidget(self.fit_checkbox)
        controls.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        layout.addLayout(controls)
        i18n.register(self._retranslateUi)
        self._retranslateUi()

    def _retranslateUi(self):
        tr = i18n.tr
        self.center_checkbox.setText(tr("Центрировать"))
        self.fit_checkbox.setText(tr("Показать весь трек"))

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

    def set_points(self, coords: list[tuple[float, float]]):
        self._run_js(f"setPoints({json.dumps(coords)});")
        if self.fit_checkbox.isChecked():
            self._run_js("fitAll();")

    def highlight_point(self, index: int):
        self._run_js(f"highlightPoint({index});")

    def set_points_excluded(self, excluded_indices: list[int]):
        self._run_js(f"setPointsExcluded({json.dumps(excluded_indices)});")

    def set_gnss_points(self, coords: list[tuple[float, float]]):
        self._run_js(f"setGnssPoints({json.dumps(coords)});")

    def set_gnss_excluded(self, excluded_indices: list[int]):
        self._run_js(f"setGnssExcluded({json.dumps(excluded_indices)});")

    def highlight_gnss_point(self, index: int):
        self._run_js(f"highlightGnssPoint({index});")

    def set_follow(self, enabled: bool):
        self._run_js(f"setFollow({'true' if enabled else 'false'});")

    def _on_fit_toggled(self, checked: bool):
        if checked:
            self._run_js("fitAll();")


_DELIMITERS = [
    ("Авто",            None),
    ("Запятая (,)",     ","),
    ("Точка с зап. (;)", ";"),
    ("Табуляция",       "\t"),
    ("Пробел",          " "),
    ("Вертикальная черта (|)", "|"),
]
_NONE_COL = "— нет —"


class _GnssImportDialog(QDialog):
    """Диалог настроек импорта GNSS-файла: разделитель, пропуск строк, назначение колонок."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Параметры импорта: {Path(path).name}")
        mw = parent.window() if parent else None
        w = mw.width() if mw else 900
        self.resize(w, 540)
        self.setMinimumWidth(w)
        self._path = path
        self._result: list[dict] | None = None

        with open(path, encoding="utf-8-sig", errors="ignore") as fh:
            self._all_lines = fh.readlines()

        # ── Controls ──────────────────────────────────────────────────────────
        self.delim_combo = QComboBox()
        for label, _ in _DELIMITERS:
            self.delim_combo.addItem(label)

        self.comment_edit = QLabel()  # placeholder; replaced by real widget below
        from PySide6.QtWidgets import QLineEdit
        self.comment_edit = QLineEdit("#%")
        self.comment_edit.setMaximumWidth(60)
        self.comment_edit.setPlaceholderText("#%")

        self.skip_slider = QSlider(Qt.Horizontal)
        self.skip_slider.setRange(0, 30)
        self.skip_slider.setValue(0)
        self.skip_spin = QSpinBox()
        self.skip_spin.setRange(0, 30)
        self.skip_spin.setValue(0)
        self.skip_spin.setMaximumWidth(60)

        # ── Settings row ─────────────────────────────────────────────────────
        settings = QHBoxLayout()
        settings.addWidget(QLabel("Разделитель:"))
        settings.addWidget(self.delim_combo)
        settings.addSpacing(16)
        settings.addWidget(QLabel("Ком. символы:"))
        settings.addWidget(self.comment_edit)
        settings.addSpacing(16)
        settings.addWidget(QLabel("Пропустить строк:"))
        settings.addWidget(self.skip_slider)
        settings.addWidget(self.skip_spin)
        settings.addStretch()

        # ── Preview table ─────────────────────────────────────────────────────
        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.verticalHeader().setVisible(True)
        self.preview_table.setMinimumHeight(160)
        self.preview_table.setMaximumHeight(220)

        # ── Column assignment ─────────────────────────────────────────────────
        self.lat_combo  = QComboBox()
        self.lon_combo  = QComboBox()
        self.alt_combo  = QComboBox()
        self.name_combo = QComboBox()

        col_form = QFormLayout()
        col_form.setHorizontalSpacing(12)
        col_form.setVerticalSpacing(4)
        col_row1 = QHBoxLayout()
        col_row1.addWidget(QLabel("Широта:"))
        col_row1.addWidget(self.lat_combo)
        col_row1.addSpacing(20)
        col_row1.addWidget(QLabel("Долгота:"))
        col_row1.addWidget(self.lon_combo)
        col_row1.addSpacing(20)
        col_row1.addWidget(QLabel("Высота:"))
        col_row1.addWidget(self.alt_combo)
        col_row1.addSpacing(20)
        col_row1.addWidget(QLabel("Имя / файл:"))
        col_row1.addWidget(self.name_combo)
        col_row1.addStretch()

        self.row_count_label = QLabel()

        # ── Buttons ───────────────────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok_btn = buttons.button(QDialogButtonBox.Ok)
        self._ok_btn.setText("Импортировать")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self._on_accepted)
        buttons.rejected.connect(self.reject)

        # ── Layout ────────────────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>Файл:</b> {path}"))
        layout.addLayout(settings)
        layout.addWidget(QLabel("Предпросмотр данных:"))
        layout.addWidget(self.preview_table)
        layout.addLayout(col_row1)
        layout.addWidget(self.row_count_label)
        layout.addWidget(buttons)

        # ── Signals ───────────────────────────────────────────────────────────
        self.delim_combo.currentIndexChanged.connect(self._refresh)
        self.comment_edit.textChanged.connect(self._refresh)
        self.skip_slider.valueChanged.connect(self.skip_spin.setValue)
        self.skip_spin.valueChanged.connect(self.skip_slider.setValue)
        self.skip_spin.valueChanged.connect(self._refresh)

        self._refresh()

    # ── Parsing helpers ───────────────────────────────────────────────────────

    def _comment_chars(self) -> str:
        return self.comment_edit.text().strip()

    def _delimiter(self) -> str | None:
        return _DELIMITERS[self.delim_combo.currentIndex()][1]

    def _effective_lines(self) -> list[str]:
        skip = self.skip_spin.value()
        cc = self._comment_chars()
        result = []
        for line in self._all_lines[skip:]:
            stripped = line.strip()
            if not stripped:
                continue
            if cc and stripped[0] in cc:
                continue
            result.append(stripped)
        return result

    def _parse_to_rows(self) -> tuple[list[str], list[list[str]]]:
        """Returns (headers, data_rows) as raw string lists."""
        lines = self._effective_lines()
        if not lines:
            return [], []

        delim = self._delimiter()
        if delim is None:
            try:
                dialect = csv.Sniffer().sniff("\n".join(lines[:5]), delimiters=",;\t |")
                reader = list(csv.reader(lines, dialect))
            except csv.Error:
                reader = list(csv.reader(lines))
        elif delim == " ":
            reader = [l.split() for l in lines]
        else:
            reader = list(csv.reader(lines, delimiter=delim))

        if not reader:
            return [], []
        headers = [h.strip() for h in reader[0]]
        data = reader[1:]
        return headers, data

    # ── UI update ─────────────────────────────────────────────────────────────

    def _refresh(self):
        headers, data = self._parse_to_rows()

        # Preview table
        self.preview_table.setColumnCount(len(headers))
        self.preview_table.setHorizontalHeaderLabels(headers)
        show = min(10, len(data))
        self.preview_table.setRowCount(show)
        for r in range(show):
            row = data[r]
            for c in range(len(headers)):
                val = row[c].strip() if c < len(row) else ""
                self.preview_table.setItem(r, c, QTableWidgetItem(val))
        self.preview_table.resizeColumnsToContents()

        self._update_col_combos(headers)
        total = len(data)
        self.row_count_label.setText(f"Строк данных: {total}")
        self._ok_btn.setEnabled(total > 0 and bool(headers))

    def _update_col_combos(self, headers: list[str]):
        hl = [h.lower() for h in headers]

        def best(candidates) -> int:
            for cand in candidates:
                for i, h in enumerate(hl):
                    if cand == h:
                        return i
            for cand in candidates:
                for i, h in enumerate(hl):
                    if cand in h:
                        return i
            return -1

        lat_i  = best(_GNSS_LAT_CANDIDATES)
        lon_i  = best(_GNSS_LON_CANDIDATES)
        alt_i  = best(_GNSS_ALT_CANDIDATES)
        name_i = best(_GNSS_NAME_CANDIDATES)

        for combo in (self.lat_combo, self.lon_combo, self.alt_combo, self.name_combo):
            combo.blockSignals(True)
            prev = combo.currentText()
            combo.clear()

        self.alt_combo.addItem(_NONE_COL)
        self.name_combo.addItem(_NONE_COL)

        for h in headers:
            for combo in (self.lat_combo, self.lon_combo, self.alt_combo, self.name_combo):
                combo.addItem(h)

        # Restore or auto-select
        def try_restore(combo, prev_text, auto_idx, offset=0):
            idx = combo.findText(prev_text)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            elif auto_idx >= 0:
                combo.setCurrentIndex(auto_idx + offset)

        try_restore(self.lat_combo,  self.lat_combo.currentText(),  lat_i)
        try_restore(self.lon_combo,  self.lon_combo.currentText(),  lon_i)
        try_restore(self.alt_combo,  self.alt_combo.currentText(),  alt_i,  1)
        try_restore(self.name_combo, self.name_combo.currentText(), name_i, 1)

        for combo in (self.lat_combo, self.lon_combo, self.alt_combo, self.name_combo):
            combo.blockSignals(False)

    # ── Accept ────────────────────────────────────────────────────────────────

    def _on_accepted(self):
        headers, data = self._parse_to_rows()
        if not headers or not data:
            QMessageBox.warning(self, "Ошибка", "Файл не удалось разобрать. Измените настройки разделителя или пропуска строк.")
            return

        h_idx = {h: i for i, h in enumerate(headers)}
        lat_col  = self.lat_combo.currentText()
        lon_col  = self.lon_combo.currentText()
        alt_col  = self.alt_combo.currentText()
        name_col = self.name_combo.currentText()

        lat_i  = h_idx.get(lat_col)
        lon_i  = h_idx.get(lon_col)
        alt_i  = h_idx.get(alt_col) if alt_col != _NONE_COL else None
        name_i = h_idx.get(name_col) if name_col != _NONE_COL else None

        if lat_i is None or lon_i is None:
            QMessageBox.warning(self, "Ошибка", "Не найдены колонки широты или долготы.")
            return

        points: list[dict] = []
        for idx, row in enumerate(data):
            try:
                lat = float(row[lat_i])
                lon = float(row[lon_i])
            except (IndexError, ValueError):
                continue
            alt = None
            if alt_i is not None:
                try:
                    alt = float(row[alt_i])
                except (IndexError, ValueError):
                    pass
            name = (row[name_i].strip() if name_i is not None and name_i < len(row) else "") or f"#{idx + 1}"
            points.append({"name": name, "lat": lat, "lon": lon, "alt": alt})

        if not points:
            QMessageBox.warning(self, "Ошибка", "Не удалось извлечь ни одной точки. Проверьте назначение колонок.")
            return

        self._result = points
        self.accept()

    def result_points(self) -> list[dict] | None:
        return self._result


class _PhotoFolderPanel(QWidget):
    """Lets the user pick a local folder of photos to associate with the geotags."""
    folder_loaded = Signal(list)  # list[Path]
    geotag_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder_path: Path | None = None
        self.photo_files: list[Path] = []
        self._photo_gps: list[tuple | None] = []
        self._photo_thumbs: list[bytes] = []
        self._excluded: set[int] = set()
        self._loader: _PhotoLoader | None = None

        self.choose_button = QPushButton()
        self.choose_button.clicked.connect(self._on_choose_clicked)
        self.geotag_source_combo = QComboBox()
        self.geotag_button = QPushButton()
        self.geotag_button.clicked.connect(self.geotag_requested.emit)
        self.remove_geotags_button = QPushButton()
        self.remove_geotags_button.clicked.connect(self._on_remove_all_geotags_clicked)
        self.clear_photos_button = QPushButton()
        self.clear_photos_button.clicked.connect(self._on_clear_photos_clicked)
        self.clear_photos_button.setEnabled(False)
        self.count_label = QLabel("")

        self.path_label = QLabel()
        self.path_label.setWordWrap(True)
        self.loading_label = QLabel("")

        self.view_combo = QComboBox()
        self.view_combo.currentIndexChanged.connect(self._on_view_mode_changed)

        self.file_list = QListWidget()
        self.file_list.setViewMode(QListView.ListMode)
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._on_photo_context_menu)
        self.file_list.itemDoubleClicked.connect(self._on_photo_double_clicked)

        header_row = QHBoxLayout()
        header_row.addWidget(self.choose_button)
        header_row.addWidget(self.view_combo)
        header_row.addStretch()
        header_row.addWidget(self.count_label)
        header_row.addWidget(self.remove_geotags_button)

        footer_row = QHBoxLayout()
        footer_row.addWidget(self.clear_photos_button)
        footer_row.addStretch()
        footer_row.addWidget(self.geotag_source_combo)
        footer_row.addWidget(self.geotag_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(header_row)
        layout.addWidget(self.path_label)
        layout.addWidget(self.loading_label)
        layout.addWidget(self.file_list)
        layout.addLayout(footer_row)

        i18n.register(self._retranslateUi)
        self._retranslateUi()
        self.view_combo.setCurrentIndex(0)  # default to list

    def _retranslateUi(self):
        tr = i18n.tr
        self.choose_button.setText(tr("Выбрать папку с фотографиями..."))
        self.geotag_button.setText(tr("Геотегировать изображения"))
        self.remove_geotags_button.setText(tr("Удалить все геопривязки"))
        self.clear_photos_button.setText(tr("Очистить фотографии"))
        if not self.photo_files:
            self.path_label.setText(tr("Папка не выбрана"))
        current_idx = self.view_combo.currentIndex()
        self.view_combo.blockSignals(True)
        self.view_combo.clear()
        self.view_combo.addItems([tr("Список"), tr("Миниатюры")])
        self.view_combo.setCurrentIndex(max(0, current_idx))
        self.view_combo.blockSignals(False)
        current_src = self.geotag_source_combo.currentIndex()
        self.geotag_source_combo.blockSignals(True)
        self.geotag_source_combo.clear()
        self.geotag_source_combo.addItems([tr("Геометки GNSS"), tr("Геометки с лога")])
        self.geotag_source_combo.setCurrentIndex(max(0, current_src))
        self.geotag_source_combo.blockSignals(False)

    def active_photo_files(self) -> list[Path]:
        return [f for i, f in enumerate(self.photo_files) if i not in self._excluded]

    def geotag_source(self) -> str:
        return "gnss" if self.geotag_source_combo.currentIndex() == 0 else "log"

    def _on_choose_clicked(self):
        directory = QFileDialog.getExistingDirectory(self, i18n.tr("Выберите папку с фотографиями"))
        if not directory:
            return
        self.set_folder(directory)

    def _on_clear_photos_clicked(self):
        self._stop_loader()
        self.loading_label.setText("")
        self.folder_path = None
        self.photo_files = []
        self._photo_gps = []
        self._photo_thumbs = []
        self._excluded = set()
        self.file_list.clear()
        self.path_label.setText(i18n.tr("Папка не выбрана"))
        self.count_label.setText("")
        self.clear_photos_button.setEnabled(False)
        self.folder_loaded.emit([])

    def set_folder(self, directory: str):
        self._stop_loader()
        folder = Path(directory)
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in _PHOTO_EXTENSIONS)
        self.folder_path = folder
        self.photo_files = files
        self._excluded = set()
        self._photo_gps = [None] * len(files)
        self._photo_thumbs = [b''] * len(files)

        self.path_label.setText(str(folder))
        self._update_count_label()
        self._populate_list()
        self.clear_photos_button.setEnabled(True)
        self.folder_loaded.emit(files)

        if files:
            n = len(files)
            self.loading_label.setText(f"Загрузка: 0 / {n}")
            self._loader = _PhotoLoader(files, parent=self)
            self._loader.photo_ready.connect(self._on_photo_ready)
            self._loader.finished.connect(self._on_loader_finished)
            self._loader.start()

    def _stop_loader(self):
        if self._loader is not None:
            self._loader.stop()
            self._loader.wait(2000)
            self._loader = None

    def _on_photo_ready(self, row: int, gps, thumb_bytes: bytes):
        if row >= len(self.photo_files):
            return
        self._photo_gps[row] = gps
        self._photo_thumbs[row] = thumb_bytes
        item = self.file_list.item(row)
        if item is not None:
            excluded = row in self._excluded
            if self.view_combo.currentIndex() == 1:
                item.setIcon(_thumbnail_icon_from_bytes(thumb_bytes, gps is not None, excluded, size=96))
            if gps:
                lat, lon, alt = gps
                alt_text = f"{alt:.1f} м" if alt is not None else "—"
                item.setToolTip(
                    f"{self.photo_files[row].name}\nШирота: {lat:.6f}\nДолгота: {lon:.6f}\nВысота: {alt_text}"
                )
        loaded = sum(1 for t in self._photo_thumbs if t)
        self.loading_label.setText(f"Загрузка: {loaded} / {len(self.photo_files)}")

    def _on_loader_finished(self):
        self._loader = None
        self.loading_label.setText("")
        self._update_count_label()

    def _on_remove_all_geotags_clicked(self):
        tr = i18n.tr
        if not self.photo_files:
            QMessageBox.information(self, tr("Удаление геопривязок"), tr("Сначала выберите папку с фотографиями."))
            return

        reply = QMessageBox.warning(
            self, tr("Удаление геопривязок"),
            f"Координаты и высота будут безвозвратно удалены из EXIF всех {len(self.photo_files)} "
            f"открытых фотографий. Это действие нельзя отменить.\n\nПродолжить?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        progress = QProgressDialog(tr("Удаление геопривязок..."), tr("Отмена"), 0, len(self.photo_files), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        errors = []
        for i, f in enumerate(self.photo_files):
            if progress.wasCanceled():
                break
            progress.setLabelText(tr("Обработка: ") + f.name)
            progress.setValue(i)
            QApplication.processEvents()
            try:
                _strip_gps_exif(f)
            except Exception as e:
                errors.append(f"{f.name}: {e}")
            else:
                self._photo_gps[i] = None
        progress.setValue(len(self.photo_files))

        self._update_count_label()
        self._populate_list()

        if errors:
            QMessageBox.warning(
                self, tr("Удаление завершено с ошибками"),
                f"Обработано: {len(self.photo_files) - len(errors)} из {len(self.photo_files)}.\n"
                + "\n".join(errors[:10])
            )
        else:
            QMessageBox.information(self, tr("Удаление завершено"), tr("Геопривязка удалена из всех фотографий."))

    def _update_count_label(self):
        tr = i18n.tr
        total = len(self.photo_files)
        excluded = len(self._excluded)
        geotagged = sum(1 for g in self._photo_gps if g is not None)
        if excluded:
            self.count_label.setText(
                f"{tr('Фотографий')}: {total - excluded} {tr('из')} {total} "
                f"({tr('исключено')}: {excluded}, {tr('геопривязанных')}: {geotagged})"
            )
        else:
            self.count_label.setText(f"{tr('Фотографий')}: {total} ({tr('геопривязанных')}: {geotagged})")

    def _on_view_mode_changed(self, _index: int):
        self._populate_list()

    def _on_photo_context_menu(self, pos):
        item = self.file_list.itemAt(pos)
        if item is None:
            return
        row = self.file_list.row(item)
        menu = QMenu(self)
        action_text = i18n.tr("Включить фотографию") if row in self._excluded else i18n.tr("Исключить фотографию")
        action = menu.addAction(action_text)
        chosen = menu.exec(self.file_list.viewport().mapToGlobal(pos))
        if chosen == action:
            self._toggle_excluded(row)

    def _on_photo_double_clicked(self, item):
        row = self.file_list.row(item)
        if row < 0 or row >= len(self.photo_files):
            return
        dlg = _PhotoViewerDialog(self.photo_files[row], self)
        dlg.exec()

    def _toggle_excluded(self, row: int):
        if row in self._excluded:
            self._excluded.discard(row)
        else:
            self._excluded.add(row)
        self._update_count_label()
        self._apply_item_style(row)

    def _apply_item_style(self, row: int):
        item = self.file_list.item(row)
        if item is None:
            return
        excluded = row in self._excluded
        has_gps = self._photo_gps[row] is not None if row < len(self._photo_gps) else False
        if self.view_combo.currentIndex() == 1:
            thumb = self._photo_thumbs[row] if row < len(self._photo_thumbs) else b''
            if thumb:
                item.setIcon(_thumbnail_icon_from_bytes(thumb, has_gps, excluded))
            else:
                item.setIcon(_thumbnail_icon(self.photo_files[row], 96, has_gps, excluded))
        default_fg = self.file_list.palette().color(QPalette.Text)
        item.setForeground(QColor("#888888") if excluded else default_fg)

    def _populate_list(self):
        self.file_list.clear()
        if self.view_combo.currentIndex() == 1:
            self.file_list.setViewMode(QListView.IconMode)
            self.file_list.setIconSize(QSize(96, 96))
            self.file_list.setGridSize(QSize(112, 120))
            self.file_list.setResizeMode(QListView.Adjust)
            self.file_list.setSpacing(6)
            self.file_list.setWordWrap(True)
            self.file_list.setFlow(QListView.LeftToRight)
            placeholder = QPixmap(96, 96)
            placeholder.fill(QColor("#333333"))
            placeholder_icon = QIcon(placeholder)
            for row, f in enumerate(self.photo_files):
                gps = self._photo_gps[row] if row < len(self._photo_gps) else None
                excluded = row in self._excluded
                thumb = self._photo_thumbs[row] if row < len(self._photo_thumbs) else b''
                icon = _thumbnail_icon_from_bytes(thumb, gps is not None, excluded) if thumb else placeholder_icon
                item = QListWidgetItem(icon, f.name)
                item.setTextAlignment(Qt.AlignHCenter)
                if gps:
                    lat, lon, alt = gps
                    alt_text = f"{alt:.1f} м" if alt is not None else "—"
                    item.setToolTip(f"{f.name}\nШирота: {lat:.6f}\nДолгота: {lon:.6f}\nВысота: {alt_text}")
                else:
                    item.setToolTip(f.name)
                if excluded:
                    item.setForeground(QColor("#888888"))
                self.file_list.addItem(item)
        else:
            self.file_list.setViewMode(QListView.ListMode)
            self.file_list.setFlow(QListView.TopToBottom)
            self.file_list.setGridSize(QSize())
            self.file_list.setIconSize(QSize())
            self.file_list.setSpacing(0)
            for row, f in enumerate(self.photo_files):
                item = QListWidgetItem(f.name)
                if row in self._excluded:
                    item.setForeground(QColor("#888888"))
                self.file_list.addItem(item)


class PhotoGeotagWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.summary_label = QLabel()
        self.import_gnss_button = QPushButton()
        self.import_gnss_button.clicked.connect(self._on_import_gnss_clicked)
        self.clear_gnss_button = QPushButton()
        self.clear_gnss_button.clicked.connect(self._on_clear_gnss_clicked)
        self.clear_gnss_button.setEnabled(False)
        self.export_button = QPushButton()
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_csv)
        top_row.addWidget(self.summary_label)
        top_row.addStretch()
        top_row.addWidget(self.export_button)
        layout.addLayout(top_row)

        self.map = _PhotoMapWidget()
        self.map.marker_hovered.connect(self._on_marker_hovered)

        self.photo_folder_panel = _PhotoFolderPanel()
        self.photo_folder_panel.geotag_requested.connect(self._on_geotag_clicked)

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(self.map)
        left_splitter.addWidget(self.photo_folder_panel)
        left_splitter.setStretchFactor(0, 2)
        left_splitter.setStretchFactor(1, 1)

        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.cellEntered.connect(self._on_table_cell_entered)
        self.table.viewport().installEventFilter(self)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_log_context_menu)

        self.gnss_label = QLabel()
        self.gnss_table = QTableWidget()
        self.gnss_table.setColumnCount(len(_GNSS_COLUMNS))
        self.gnss_table.setHorizontalHeaderLabels(_GNSS_COLUMNS)
        self.gnss_table.horizontalHeader().setStretchLastSection(True)
        self.gnss_table.verticalHeader().setVisible(False)
        self.gnss_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.gnss_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.gnss_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.gnss_table.setMouseTracking(True)
        self.gnss_table.viewport().setMouseTracking(True)
        self.gnss_table.cellEntered.connect(self._on_gnss_cell_entered)
        self.gnss_table.viewport().installEventFilter(self)
        self.gnss_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.gnss_table.customContextMenuRequested.connect(self._on_gnss_context_menu)

        self.log_count_label = QLabel()

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.log_count_label)
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.addWidget(self.table)
        gnss_panel = QWidget()
        gnss_layout = QVBoxLayout(gnss_panel)
        gnss_layout.setContentsMargins(0, 0, 0, 0)
        gnss_header_row = QHBoxLayout()
        gnss_header_row.addWidget(self.gnss_label)
        gnss_header_row.addStretch()
        gnss_header_row.addWidget(self.clear_gnss_button)
        gnss_header_row.addWidget(self.import_gnss_button)
        gnss_layout.addLayout(gnss_header_row)
        gnss_layout.addWidget(self.gnss_table)
        right_splitter.addWidget(gnss_panel)
        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 1)
        right_layout.addWidget(right_splitter)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_splitter)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([10000, 10000])
        layout.addWidget(splitter)

        self._rows: list[list[str]] = []
        self._points: list[tuple[float, float]] = []
        self._gnss_points: list[tuple[float, float]] = []
        self._log_geotags: list[dict] = []
        self._log_excluded: set[int] = set()
        self._gnss_geotags: list[dict] = []
        self._gnss_outliers: list[bool] = []
        self._gnss_excluded: set[int] = set()
        self._highlighted_row = -1
        self._jpeg_quality = None  # None = keep original
        i18n.register(self._retranslateUi)
        self._retranslateUi()

    def set_jpeg_quality(self, quality):
        self._jpeg_quality = quality

    def _retranslateUi(self):
        tr = i18n.tr
        self.import_gnss_button.setText(tr("Открыть файл геометок GNSS..."))
        self.clear_gnss_button.setText(tr("Очистить геометки GNSS"))
        self.export_button.setText(tr("Экспорт в CSV"))
        if not self._rows:
            self.summary_label.setText(tr("Фотографии не найдены"))
        if not self._gnss_geotags:
            self.gnss_label.setText(tr("Геометки GNSS не загружены"))
        if not self._rows:
            self.log_count_label.setText(f"{tr('Геометок с лога')}: 0")
        self.table.setHorizontalHeaderLabels([tr(c) for c in _COLUMNS])
        self.gnss_table.setHorizontalHeaderLabels([tr(c) for c in _GNSS_COLUMNS])

    def eventFilter(self, watched, event):
        if event.type() == event.Type.Leave:
            if watched is self.table.viewport():
                self._clear_table_highlight()
            elif watched is self.gnss_table.viewport():
                self._clear_gnss_highlight()
        return super().eventFilter(watched, event)

    def _on_table_cell_entered(self, row: int, column: int):
        if row == self._highlighted_row:
            return
        self._highlighted_row = row
        self.map.highlight_point(row)

    def _clear_table_highlight(self):
        if self._highlighted_row == -1:
            return
        self._highlighted_row = -1
        self.map.highlight_point(-1)

    def _on_gnss_cell_entered(self, row: int, _col: int):
        self.map.highlight_gnss_point(row)

    def _clear_gnss_highlight(self):
        self.map.highlight_gnss_point(-1)

    def _on_marker_hovered(self, index: int):
        if index < 0 or index >= self.table.rowCount():
            self.table.clearSelection()
        else:
            self.table.selectRow(index)
            self.table.scrollToItem(self.table.item(index, 0))

    def load(self, log_data: LogData):
        photo_table, t, lat, lon = self._photo_positions(log_data)
        self.table.setRowCount(0)
        self._rows = []
        self._points = []
        self._log_excluded = set()
        if photo_table is None or len(t) == 0:
            tr = i18n.tr
            self.summary_label.setText(tr("Фотографии не найдены (нет сообщений CAM/TRIG в логе)"))
            self.export_button.setEnabled(False)
            self.log_count_label.setText(f"{tr('Геометок с лога')}: 0")
            self.map.set_points([])
            return

        amsl = self._resolve_series(photo_table, t, "Alt", _ALT_AMSL_CANDIDATES, log_data)
        agl = self._resolve_series(photo_table, t, "RelAlt", _ALT_AGL_CANDIDATES, log_data)
        roll, pitch, yaw = self._resolve_attitude(photo_table, t, log_data)
        speed = self._resolve_series(photo_table, t, None, _GROUND_SPEED_CANDIDATES, log_data)

        n = len(t)
        dist = _haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:]) if n > 1 else np.array([])
        interval = np.diff(t) if n > 1 else np.array([])

        rows = []
        for i in range(n):
            rows.append([
                str(i + 1),
                format_mmss(float(t[i]) - log_data.start_time),
                format_gps_time(float(t[i])),
                f"{lat[i]:.6f}",
                f"{lon[i]:.6f}",
                f"{amsl[i]:.1f}" if amsl is not None else "—",
                f"{agl[i]:.1f}" if agl is not None else "—",
                f"{roll[i]:.1f}" if roll is not None else "—",
                f"{pitch[i]:.1f}" if pitch is not None else "—",
                f"{yaw[i]:.1f}" if yaw is not None else "—",
                f"{speed[i]:.1f}" if speed is not None else "—",
                f"{interval[i - 1]:.1f}" if i > 0 else "—",
                f"{dist[i - 1]:.1f}" if i > 0 else "—",
            ])

        self._rows = rows
        self._points = list(zip(lat.tolist(), lon.tolist()))
        self._log_geotags = [
            {"lat": float(lat[i]), "lon": float(lon[i]), "alt": float(amsl[i]) if amsl is not None else None}
            for i in range(n)
        ]
        self.table.setRowCount(n)
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)

        self.summary_label.setText(f"{i18n.tr('Найдено фотографий')}: {n}")
        self._update_log_count_label()
        self.export_button.setEnabled(True)
        self.map.set_points(self._points)

    def clear(self):
        tr = i18n.tr
        self.table.setRowCount(0)
        self._rows = []
        self._points = []
        self._log_geotags = []
        self._log_excluded = set()
        self.summary_label.setText(tr("Фотографии не найдены"))
        self.log_count_label.setText(f"{tr('Геометок с лога')}: 0")
        self.export_button.setEnabled(False)
        self.map.set_points([])

    def _update_log_count_label(self):
        tr = i18n.tr
        total = len(self._rows)
        excluded = len(self._log_excluded)
        if excluded:
            self.log_count_label.setText(
                f"{tr('Геометок с лога')}: {total - excluded} {tr('из')} {total} ({tr('исключено')}: {excluded})"
            )
        else:
            self.log_count_label.setText(f"{tr('Геометок с лога')}: {total}")

    def _active_log_geotags(self) -> list[dict]:
        return [p for i, p in enumerate(self._log_geotags) if i not in self._log_excluded]

    def _apply_log_row_style(self, row: int):
        excluded = row in self._log_excluded
        palette = self.table.palette()
        default_bg = palette.color(QPalette.Base)
        default_fg = palette.color(QPalette.Text)
        for c in range(self.table.columnCount()):
            item = self.table.item(row, c)
            if item is None:
                continue
            if excluded:
                item.setBackground(QColor("#777777"))
                item.setForeground(QColor("#dddddd"))
            else:
                item.setBackground(default_bg)
                item.setForeground(default_fg)

    def _on_log_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        menu = QMenu(self)
        action_text = i18n.tr("Включить точку") if row in self._log_excluded else i18n.tr("Исключить точку")
        action = menu.addAction(action_text)
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == action:
            if row in self._log_excluded:
                self._log_excluded.discard(row)
            else:
                self._log_excluded.add(row)
            self._apply_log_row_style(row)
            self._update_log_count_label()
            self.map.set_points_excluded(sorted(self._log_excluded))

    def _photo_positions(self, log_data: LogData):
        for msg_type in ("CAM", "TRIG"):
            table = log_data.messages.get(msg_type)
            if not table:
                continue
            t = table["timestamp"]
            if "Lat" in table and "Lng" in table:
                return table, t, np.asarray(table["Lat"], dtype=float), np.asarray(table["Lng"], dtype=float)
            for gmsg, lat_f, lon_f in _GPS_LAT_CANDIDATES:
                gtable = log_data.messages.get(gmsg)
                if gtable and lat_f in gtable and lon_f in gtable:
                    glat, glon = gtable[lat_f], gtable[lon_f]
                    if gmsg == "GLOBAL_POSITION_INT":
                        glat, glon = glat / 1e7, glon / 1e7
                    lat = np.interp(t, gtable["timestamp"], glat)
                    lon = np.interp(t, gtable["timestamp"], glon)
                    return table, t, lat, lon
        return None, np.array([]), np.array([]), np.array([])

    def _resolve_series(self, photo_table, t, own_field, ext_candidates, log_data) -> np.ndarray | None:
        if own_field and own_field in photo_table and len(photo_table[own_field]) == len(t):
            return np.asarray(photo_table[own_field], dtype=float)
        for msg_type, field, divisor in ext_candidates:
            table = log_data.messages.get(msg_type)
            if table and field in table and len(table[field]):
                return np.interp(t, table["timestamp"], table[field]) / divisor
        return None

    def _resolve_attitude(self, photo_table, t, log_data):
        if all(f in photo_table and len(photo_table[f]) == len(t) for f in ("Roll", "Pitch", "Yaw")):
            roll = np.asarray(photo_table["Roll"], dtype=float)
            pitch = np.asarray(photo_table["Pitch"], dtype=float)
            yaw = np.mod(np.asarray(photo_table["Yaw"], dtype=float), 360.0)
            return roll, pitch, yaw
        for msg_type, roll_f, pitch_f, yaw_f, is_radians in _ATTITUDE_CANDIDATES:
            table = log_data.messages.get(msg_type)
            if table and roll_f in table and pitch_f in table and yaw_f in table:
                roll = np.interp(t, table["timestamp"], table[roll_f])
                pitch = np.interp(t, table["timestamp"], table[pitch_f])
                yaw = np.interp(t, table["timestamp"], table[yaw_f])
                if is_radians:
                    roll, pitch, yaw = np.degrees(roll), np.degrees(pitch), np.degrees(yaw)
                return roll, pitch, np.mod(yaw, 360.0)
        return None, None, None

    def _on_import_gnss_clicked(self):
        tr = i18n.tr
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Открыть файл геометок GNSS..."), "",
            tr("Файлы геометок (*.csv *.pos *.txt);;All files (*.*)")
        )
        if not path:
            return
        try:
            dlg = _GnssImportDialog(path, self)
        except OSError as e:
            QMessageBox.warning(self, tr("Ошибка чтения файла"), str(e))
            return
        if dlg.exec() != QDialog.Accepted:
            return
        points = dlg.result_points()
        if not points:
            return

        self._gnss_points = [(p["lat"], p["lon"]) for p in points]
        self._gnss_geotags = points
        self._gnss_excluded = set()

        alts = [p["alt"] for p in points if p["alt"] is not None]
        mean_alt = sum(alts) / len(alts) if alts else None
        self._gnss_outliers = [
            bool(mean_alt and p["alt"] is not None and abs(p["alt"] - mean_alt) / abs(mean_alt) > 0.10)
            for p in points
        ]

        self.gnss_table.setRowCount(len(points))
        for r, p in enumerate(points):
            values = [str(r + 1), p["name"], f"{p['lat']:.6f}", f"{p['lon']:.6f}",
                      f"{p['alt']:.1f}" if p["alt"] is not None else "—"]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                self.gnss_table.setItem(r, c, item)
            self._apply_gnss_row_style(r)

        self._update_gnss_label()
        self.clear_gnss_button.setEnabled(True)
        self.map.set_gnss_points(self._gnss_points)

    def _on_clear_gnss_clicked(self):
        self._gnss_geotags = []
        self._gnss_points = []
        self._gnss_excluded = set()
        self._gnss_outliers = []
        self.gnss_table.setRowCount(0)
        self.map.set_gnss_points([])
        self.map.set_gnss_excluded([])
        self.clear_gnss_button.setEnabled(False)
        self.gnss_label.setText(i18n.tr("Геометки GNSS не загружены"))

    def _active_gnss_geotags(self) -> list[dict]:
        return [p for i, p in enumerate(self._gnss_geotags) if i not in self._gnss_excluded]

    def _update_gnss_label(self):
        tr = i18n.tr
        total = len(self._gnss_geotags)
        excluded = len(self._gnss_excluded)
        if excluded:
            self.gnss_label.setText(
                f"{tr('Геометки GNSS')}: {total - excluded} {tr('из')} {total} ({tr('исключено')}: {excluded})"
            )
        else:
            self.gnss_label.setText(f"{tr('Геометки GNSS')}: {total}")

    def _apply_gnss_row_style(self, row: int):
        excluded = row in self._gnss_excluded
        outlier = row < len(self._gnss_outliers) and self._gnss_outliers[row]
        palette = self.gnss_table.palette()
        default_bg = palette.color(QPalette.Base)
        default_fg = palette.color(QPalette.Text)
        for c in range(self.gnss_table.columnCount()):
            item = self.gnss_table.item(row, c)
            if item is None:
                continue
            if excluded:
                item.setBackground(QColor("#777777"))
                item.setForeground(QColor("#dddddd"))
            elif outlier:
                item.setBackground(QColor("#c0392b"))
                item.setForeground(QColor("white"))
            else:
                item.setBackground(default_bg)
                item.setForeground(default_fg)

    def _on_gnss_context_menu(self, pos):
        row = self.gnss_table.rowAt(pos.y())
        if row < 0:
            return
        selected = {idx.row() for idx in self.gnss_table.selectedIndexes()}
        target = selected if row in selected and len(selected) > 1 else {row}
        any_included = any(r not in self._gnss_excluded for r in target)
        tr = i18n.tr
        if len(target) > 1:
            action_text = tr("Исключить выбранные точки") if any_included else tr("Включить выбранные точки")
        else:
            action_text = tr("Включить точку") if row in self._gnss_excluded else tr("Исключить точку")
        menu = QMenu(self)
        action = menu.addAction(action_text)
        chosen = menu.exec(self.gnss_table.viewport().mapToGlobal(pos))
        if chosen == action:
            for r in target:
                if any_included:
                    self._gnss_excluded.add(r)
                else:
                    self._gnss_excluded.discard(r)
                self._apply_gnss_row_style(r)
            self._update_gnss_label()
            self.map.set_gnss_excluded(sorted(self._gnss_excluded))

    def _parse_gnss_csv(self, path: str) -> list[dict]:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return []
            header_lower = {h.strip().lower(): h for h in reader.fieldnames}

            def find_column(candidates):
                for cand in candidates:
                    if cand in header_lower:
                        return header_lower[cand]
                return None

            lat_col = find_column(_GNSS_LAT_CANDIDATES)
            lon_col = find_column(_GNSS_LON_CANDIDATES)
            if lat_col is None or lon_col is None:
                return []
            alt_col = find_column(_GNSS_ALT_CANDIDATES)
            name_col = find_column(_GNSS_NAME_CANDIDATES)

            points = []
            for i, row in enumerate(reader):
                try:
                    lat = float(row[lat_col])
                    lon = float(row[lon_col])
                except (TypeError, ValueError):
                    continue
                alt = None
                if alt_col is not None:
                    try:
                        alt = float(row[alt_col])
                    except (TypeError, ValueError):
                        alt = None
                name = row.get(name_col, "").strip() if name_col else f"#{i + 1}"
                points.append({"name": name or f"#{i + 1}", "lat": lat, "lon": lon, "alt": alt})
            return points

    def _parse_rtklib_pos(self, path: str) -> list[dict]:
        """Parse RTKLIB/Emlid .pos output: comment lines start with '%', data
        lines are whitespace-separated as 'date time lat lon height Q ns ...'."""
        points = []
        with open(path, encoding="utf-8-sig", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("%"):
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                try:
                    lat = float(parts[2])
                    lon = float(parts[3])
                    alt = float(parts[4])
                except (IndexError, ValueError):
                    continue
                points.append({"name": f"{parts[0]} {parts[1]}", "lat": lat, "lon": lon, "alt": alt})
        return points

    def _on_geotag_clicked(self):
        tr = i18n.tr
        files = self.photo_folder_panel.active_photo_files()
        if not files:
            QMessageBox.information(self, tr("Геотегирование"), tr("Сначала выберите папку с фотографиями."))
            return

        source = self.photo_folder_panel.geotag_source()
        source_label = tr("Геометки GNSS") if source == "gnss" else tr("Геометки с лога")
        points = self._active_gnss_geotags() if source == "gnss" else self._active_log_geotags()
        if not points:
            QMessageBox.warning(
                self, tr("Геотегирование"),
                tr("Нет точек привязки: откройте файл геометок GNSS или лог с фотографиями (CAM/TRIG).")
            )
            return

        reply = QMessageBox.warning(
            self, tr("Геотегирование"),
            f"Источник координат: {source_label}.\n\n"
            "Координаты и высота будут записаны в EXIF выбранных фотографий по порядку их следования, "
            "соответствующему порядку точек привязки. Существующие GPS-данные в фотографиях будут "
            "перезаписаны. Перед записью будет показан предпросмотр соответствия файлов и координат.\n\n"
            "Продолжить?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        n = min(len(files), len(points))
        if len(files) != len(points):
            reply = QMessageBox.question(
                self, tr("Количество не совпадает"),
                f"Фотографий: {len(files)}, точек привязки: {len(points)}.\n"
                f"Будут обработаны первые {n} по порядку. Продолжить?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        preview = _GeotagPreviewDialog(files[:n], points[:n], self)
        if preview.exec() != QDialog.Accepted:
            return

        progress = QProgressDialog(tr("Геотегирование") + "...", tr("Отмена"), 0, n, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        errors = []
        for i in range(n):
            if progress.wasCanceled():
                break
            f = files[i]
            progress.setLabelText(tr("Обработка: ") + f.name)
            progress.setValue(i)
            QApplication.processEvents()
            p = points[i]
            try:
                _write_gps_exif(f, p["lat"], p["lon"], p.get("alt"), self._jpeg_quality)
            except Exception as e:
                errors.append(f"{f.name}: {e}")
        progress.setValue(n)

        if errors:
            QMessageBox.warning(
                self, tr("Геотегирование завершено с ошибками"),
                f"Обработано: {n - len(errors)} из {n}.\n" + "\n".join(errors[:10])
            )
        else:
            QMessageBox.information(self, tr("Геотегирование завершено"), f"Координаты записаны в {n} фотографий.")

    def _export_csv(self):
        if not self._rows:
            return
        tr = i18n.tr
        path, _ = QFileDialog.getSaveFileName(self, tr("Экспорт геотегов фотографий"), "", tr("CSV files (*.csv)"))
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(_COLUMNS)
            writer.writerows(self._rows)
