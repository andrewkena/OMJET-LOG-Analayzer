"""Report generation: PDF report (+ optional KML track file)."""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QMarginsF, QUrl
from PySide6.QtGui import QImage, QPdfWriter, QTextDocument, QPageLayout, QPageSize
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QCheckBox, QLineEdit, QPushButton, QLabel, QFileDialog, QMessageBox,
)

from app.core.log_loader import LogData
from app.core.time_format import format_gps_datetime

# ──────────────────────────────────────────────────────────────────────────────
# GPS / wind extraction helpers
# ──────────────────────────────────────────────────────────────────────────────

_GPS_CANDIDATES = [
    ("GPS", "Lat", "Lng", "Alt"),
    ("GPS", "Lat", "Lon", "Alt"),
    ("GLOBAL_POSITION_INT", "lat", "lon", "relative_alt"),
]
_WIND_CANDIDATES = [("XKF2", "VWN", "VWE"), ("NKF2", "VWN", "VWE")]
_ARM_EVENT_ID   = 10
_DISARM_EVENT_ID = 11


def _extract_gps_track(log_data: LogData) -> list[tuple[float, float, float]]:
    """Return list of (lat, lon, alt_m) from the best GPS source available."""
    for msg, lat_f, lon_f, alt_f in _GPS_CANDIDATES:
        table = log_data.messages.get(msg)
        if table and lat_f in table and lon_f in table:
            lat = np.asarray(table[lat_f], dtype=float)
            lon = np.asarray(table[lon_f], dtype=float)
            alt_raw = table.get(alt_f)
            alt = np.asarray(alt_raw if alt_raw is not None else np.zeros(len(lat)), dtype=float)
            if msg == "GLOBAL_POSITION_INT":
                lat /= 1e7; lon /= 1e7; alt /= 1000.0
            valid = ~((lat == 0.0) & (lon == 0.0))
            return list(zip(lat[valid].tolist(), lon[valid].tolist(), alt[valid].tolist()))
    return []


def _extract_photo_positions(log_data: LogData) -> list[tuple[float, float, float, str]]:
    """Return (lat, lon, alt, label) for CAM positions (falls back to TRIG)."""
    for msg_type, prefix in (("CAM", "CAM"), ("TRIG", "TRIG")):
        table = log_data.messages.get(msg_type)
        if not table:
            continue
        t = table["timestamp"]
        if "Lat" in table and "Lng" in table:
            lat = np.asarray(table["Lat"], dtype=float)
            lon = np.asarray(table["Lng"], dtype=float)
            alt = np.asarray(table.get("Alt", np.zeros(len(lat))), dtype=float)
        else:
            for gmsg, lat_f, lon_f, alt_f in _GPS_CANDIDATES:
                gt = log_data.messages.get(gmsg)
                if gt and lat_f in gt and lon_f in gt:
                    glat = np.asarray(gt[lat_f], dtype=float)
                    glon = np.asarray(gt[lon_f], dtype=float)
                    galt_raw = gt.get(alt_f)
                    galt = np.asarray(
                        galt_raw if galt_raw is not None else np.zeros(len(glat)), dtype=float
                    )
                    if gmsg == "GLOBAL_POSITION_INT":
                        glat /= 1e7; glon /= 1e7; galt /= 1000.0
                    gts = gt["timestamp"]
                    lat = np.interp(t, gts, glat)
                    lon = np.interp(t, gts, glon)
                    alt = np.interp(t, gts, galt)
                    break
            else:
                continue
        return [
            (float(la), float(lo), float(al), f"{prefix} {i + 1}")
            for i, (la, lo, al) in enumerate(zip(lat, lon, alt))
        ]
    return []


def _flight_bounds(log_data: LogData) -> tuple[float, float]:
    """Return (takeoff_t, landing_t) from ARM/DISARM events or log bounds."""
    ev = log_data.messages.get("EV")
    if ev and "Id" in ev:
        ids = ev["Id"]
        times = ev["timestamp"]
        arm_t = times[ids == _ARM_EVENT_ID]
        disarm_t = times[ids == _DISARM_EVENT_ID]
        if len(arm_t):
            start = float(arm_t[0])
            later = disarm_t[disarm_t >= start]
            end = float(later[-1]) if len(later) else float(log_data.end_time)
            return start, end
    return float(log_data.start_time), float(log_data.end_time)


def _wind_at(log_data: LogData, t: float) -> Optional[tuple[float, float]]:
    """Interpolated (vwn, vwe) wind vector at time t, or None."""
    for msg, nf, ef in _WIND_CANDIDATES:
        table = log_data.messages.get(msg)
        if table and nf in table and ef in table:
            ts = table["timestamp"]
            return (
                float(np.interp(t, ts, table[nf])),
                float(np.interp(t, ts, table[ef])),
            )
    return None


def _gps_pos_at(log_data: LogData, t: float) -> Optional[tuple[float, float]]:
    """Interpolated (lat, lon) at time t from the best GPS source."""
    for msg, lat_f, lon_f, _alt_f in _GPS_CANDIDATES:
        table = log_data.messages.get(msg)
        if table and lat_f in table and lon_f in table:
            ts = table["timestamp"]
            lat = np.asarray(table[lat_f], dtype=float)
            lon = np.asarray(table[lon_f], dtype=float)
            if msg == "GLOBAL_POSITION_INT":
                lat /= 1e7; lon /= 1e7
            return float(np.interp(t, ts, lat)), float(np.interp(t, ts, lon))
    return None


# ──────────────────────────────────────────────────────────────────────────────
# KML generation
# ──────────────────────────────────────────────────────────────────────────────

def generate_kml(log_data: LogData, output_path: str) -> None:
    """Write a KML file with GPS track and photo markers."""
    track = _extract_gps_track(log_data)
    photos = _extract_photo_positions(log_data)

    kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc_el = ET.SubElement(kml, "Document")
    ET.SubElement(doc_el, "name").text = Path(output_path).stem

    ts = ET.SubElement(doc_el, "Style", id="trackStyle")
    ls_el = ET.SubElement(ts, "LineStyle")
    ET.SubElement(ls_el, "color").text = "ff1e78ff"
    ET.SubElement(ls_el, "width").text = "3"

    ps = ET.SubElement(doc_el, "Style", id="photoStyle")
    ic = ET.SubElement(ps, "IconStyle")
    ET.SubElement(ic, "scale").text = "0.8"
    icon_el = ET.SubElement(ic, "Icon")
    ET.SubElement(icon_el, "href").text = (
        "http://maps.google.com/mapfiles/kml/paddle/ylw-circle.png"
    )

    if track:
        pm = ET.SubElement(doc_el, "Placemark")
        ET.SubElement(pm, "name").text = "GPS Track"
        ET.SubElement(pm, "styleUrl").text = "#trackStyle"
        line = ET.SubElement(pm, "LineString")
        ET.SubElement(line, "altitudeMode").text = "absolute"
        ET.SubElement(line, "coordinates").text = "\n".join(
            f"{lo:.8f},{la:.8f},{al:.1f}" for la, lo, al in track
        )

    if photos:
        folder = ET.SubElement(doc_el, "Folder")
        ET.SubElement(folder, "name").text = "Фотографии"
        for la, lo, al, label in photos:
            pm = ET.SubElement(folder, "Placemark")
            ET.SubElement(pm, "name").text = label
            ET.SubElement(pm, "styleUrl").text = "#photoStyle"
            pt = ET.SubElement(pm, "Point")
            ET.SubElement(pt, "altitudeMode").text = "absolute"
            ET.SubElement(pt, "coordinates").text = f"{lo:.8f},{la:.8f},{al:.1f}"

    tree = ET.ElementTree(kml)
    ET.indent(tree, space="  ")
    tree.write(output_path, xml_declaration=True, encoding="UTF-8")


# ──────────────────────────────────────────────────────────────────────────────
# Map image generation
# ──────────────────────────────────────────────────────────────────────────────

def _pil_to_qimage(pil_img) -> QImage:
    buf = BytesIO()
    pil_img.save(buf, "PNG")
    q = QImage()
    q.loadFromData(bytes(buf.getvalue()))
    return q


def _build_map_images(
    log_data: LogData,
    want_full: bool,
    want_zoom: bool,
    include_photos: bool = False,
) -> dict[str, "PIL.Image.Image"]:
    """
    Generate the requested map images and return a dict keyed by resource name.
    Keys: 'map_full', 'map_takeoff', 'map_landing'
    """
    from app.core.map_image import render_map  # lazy – avoid startup cost

    images: dict = {}
    if not (want_full or want_zoom):
        return images

    track = _extract_gps_track(log_data)
    if len(track) < 2:
        return images

    photos = _extract_photo_positions(log_data) if include_photos else []
    t_start, t_end = _flight_bounds(log_data)

    wind_takeoff = _wind_at(log_data, t_start)
    wind_landing = _wind_at(log_data, t_end)
    pos_takeoff  = _gps_pos_at(log_data, t_start)
    pos_landing  = _gps_pos_at(log_data, t_end)

    # Wind arrows for the full-track map
    wind_pts: list = []
    if pos_takeoff and wind_takeoff:
        wind_pts.append((*pos_takeoff, *wind_takeoff, "Взлёт"))
    if pos_landing and wind_landing:
        wind_pts.append((*pos_landing, *wind_landing, "Посадка"))

    if want_full:
        img = render_map(
            track,
            photos=photos or None,
            wind_points=wind_pts or None,
            target_px=1600,
        )
        if img:
            images["map_full"] = img

    if want_zoom:
        # Close-up: first / last 10 % of track, minimum 80 points
        n = len(track)
        slice_n = max(80, n // 10)

        # Takeoff close-up
        takeoff_track = track[:slice_n]
        to_wp: list = []
        if pos_takeoff and wind_takeoff:
            to_wp.append((*pos_takeoff, *wind_takeoff, "Взлёт"))
        img_to = render_map(takeoff_track,
                            photos=photos or None,
                            wind_points=to_wp or None,
                            target_px=1600, padding_frac=0.25)
        if img_to:
            images["map_takeoff"] = img_to

        # Landing close-up
        landing_track = track[-slice_n:]
        la_wp: list = []
        if pos_landing and wind_landing:
            la_wp.append((*pos_landing, *wind_landing, "Посадка"))
        img_la = render_map(landing_track,
                            photos=photos or None,
                            wind_points=la_wp or None,
                            target_px=1600, padding_frac=0.25)
        if img_la:
            images["map_landing"] = img_la

    return images


# ──────────────────────────────────────────────────────────────────────────────
# HTML / PDF generation
# ──────────────────────────────────────────────────────────────────────────────

def _build_html(
    title: str,
    stats: dict,
    sections: set[str],
    log_filename: str,
    image_keys: set[str],   # which image resources are available
) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    css = (
        "body{font-family:Arial,sans-serif;font-size:10pt;color:#111;margin:0;padding:0;}"
        "h1{text-align:center;color:#1a237e;font-size:15pt;margin-bottom:2px;}"
        ".sub{text-align:center;color:#777;font-size:9pt;margin-bottom:18px;}"
        "h2{color:#1565c0;font-size:11pt;border-bottom:1px solid #90caf9;"
        "   padding-bottom:2px;margin-top:18px;margin-bottom:6px;}"
        "h3{color:#1976d2;font-size:10pt;margin:8px 0 2px 0;}"
        "table{width:100%;border-collapse:collapse;margin-bottom:8px;}"
        "td{padding:3px 6px;vertical-align:top;}"
        "td:first-child{color:#555;width:60%;}"
        "td:last-child{font-weight:bold;}"
        "tr:nth-child(even){background:#f0f4ff;}"
        ".cap{text-align:center;font-size:9pt;color:#666;margin-top:2px;}"
    )
    parts = [
        f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>",
        f"<h1>{title}</h1>",
        f"<p class='sub'>Файл: {log_filename}&nbsp;&nbsp;|&nbsp;&nbsp;Сформирован: {now}</p>",
    ]

    def row(label: str, value: str) -> str:
        return f"<tr><td>{label}</td><td>{value}</td></tr>"

    _PB = "page-break-before: always;"   # CSS page-break shorthand

    # ── общая карта сразу под заголовком (без переноса страницы) ─────────────

    if "map_full" in image_keys:
        parts += [
            "<h2>Карта трека</h2>",
            "<img src='img://map_full' width='500'/>",
            "<p class='cap'>&#9679; Взлёт (зелёный) &nbsp; &#9679; Посадка (красный)"
            " &nbsp; &#9658; Ветер при взлёте/посадке</p>",
        ]

    # ── text data sections ────────────────────────────────────────────────────

    if "time" in sections:
        parts += [
            "<h2>Время</h2><table>",
            row("Время начала миссии:", format_gps_datetime(stats.get("start_epoch", 0))),
            row("Время окончания:", format_gps_datetime(stats.get("end_epoch", 0))),
            row("Продолжительность:", stats.get("duration", "—")),
            "</table>",
        ]

    if "flight" in sections:
        parts += [
            "<h2>Параметры полёта</h2><table>",
            row("Пройденное расстояние:", stats.get("distance", "—")),
            row("Время работы вертикальных моторов:", stats.get("vertical_motor_time", "—")),
            row("Время работы ходового мотора:", stats.get("forward_motor_time", "—")),
            row("Время планирования (без моторов):", stats.get("planning_time", "—")),
            "</table>",
        ]

    if "wind" in sections:
        parts += [
            "<h2>Ветер</h2><table>",
            row("Средний ветер:", stats.get("avg_wind", "—")),
            row("Максимальный ветер:", stats.get("max_wind", "—")),
            row("Преобладающее направление ветра:", stats.get("wind_dir", "—")),
            "</table>",
        ]

    if "attitude" in sections:
        parts += [
            "<h2>Углы крена и тангажа</h2><table>",
            row("Максимальный крен:", stats.get("max_roll", "—")),
            row("Максимальный тангаж:", stats.get("max_pitch", "—")),
            "</table>",
        ]

    if "photos" in sections:
        parts += [
            "<h2>Фотосъёмка</h2><table>",
            row("Кол-во фотоимпульсов в камеры:", stats.get("cam_count", "—")),
            row("Кол-во фотоимпульсов от камеры:", stats.get("trig_count", "—")),
            row("Среднее время между снимками:", stats.get("avg_photo_time", "—")),
            row("Среднее расстояние между снимками:", stats.get("avg_photo_distance", "—")),
            "</table>",
        ]

    if "efficiency" in sections:
        parts += [
            "<h2>Эффективность</h2><table>",
            row("Общий расход на километр:", stats.get("overall_mah_per_km", "—")),
            row("Общий расход на минуту:", stats.get("overall_mah_per_min", "—")),
            row("Горизонтальный расход на километр:", stats.get("forward_mah_per_km", "—")),
            row("Горизонтальный расход на минуту:", stats.get("forward_mah_per_min", "—")),
            "</table>",
        ]

    if "battery" in sections:
        batteries = stats.get("batteries", [])
        if batteries:
            parts.append("<h2>Батарея</h2>")
            for bat in batteries:
                parts += [
                    f"<h3>Батарея {bat['index']}</h3><table>",
                    row("Потрачено мА·ч:", bat.get("mah", "—")),
                    row("Максимальный ток:", bat.get("max_curr", "—")),
                    row("Средний ток:", bat.get("avg_curr", "—")),
                    "</table>",
                ]

    # ── zoom-карты после текста (каждая на новой странице) ───────────────────

    if "map_takeoff" in image_keys:
        parts += [
            f"<h2 style='{_PB}'>Взлёт (крупно)</h2>",
            "<img src='img://map_takeoff' width='500'/>",
            "<p class='cap'>&#9679; Взлёт (зелёный) &nbsp; &#9658; Ветер при взлёте</p>",
        ]

    if "map_landing" in image_keys:
        parts += [
            f"<h2 style='{_PB}'>Посадка (крупно)</h2>",
            "<img src='img://map_landing' width='500'/>",
            "<p class='cap'>&#9679; Посадка (красный) &nbsp; &#9658; Ветер при посадке</p>",
        ]

    # ── footer ────────────────────────────────────────────────────────────────

    parts += [
        "<hr style='border:none;border-top:1px solid #e0e0e0;margin-top:28px;'/>",
        f"<p style='text-align:center;font-size:8pt;color:#bbb;margin-top:4px;'>"
        f"Отчёт сформирован: OMJET LOG Analyzer &nbsp;|&nbsp; {now}"
        f"</p>",
        "</body></html>",
    ]
    return "".join(parts)


def generate_pdf(
    output_path: str,
    title: str,
    stats: dict,
    sections: set[str],
    log_filename: str,
    images: Optional[dict] = None,
) -> None:
    """Render the report as a PDF file at *output_path*."""
    image_keys: set[str] = set(images.keys()) if images else set()
    html = _build_html(title, stats, sections, log_filename, image_keys)

    writer = QPdfWriter(output_path)
    layout = QPageLayout(
        QPageSize(QPageSize.PageSizeId.A4),
        QPageLayout.Orientation.Portrait,
        QMarginsF(15.0, 15.0, 15.0, 15.0),
        QPageLayout.Unit.Millimeter,
    )
    writer.setPageLayout(layout)
    writer.setTitle(title)

    doc = QTextDocument()

    # Register images before setHtml so they're available synchronously
    if images:
        for key, pil_img in images.items():
            q_img = _pil_to_qimage(pil_img)
            doc.addResource(
                QTextDocument.ResourceType.ImageResource,
                QUrl(f"img://{key}"),
                q_img,
            )

    doc.setHtml(html)
    doc.print_(writer)


# ──────────────────────────────────────────────────────────────────────────────
# Dialog
# ──────────────────────────────────────────────────────────────────────────────

class ReportDialog(QDialog):
    def __init__(self, log_data: LogData, log_path: str, stats: dict, parent=None):
        super().__init__(parent)
        self._log_data = log_data
        self._log_path = log_path
        self._stats = stats
        self._out_dir = str(Path(log_path).parent)

        self.setWindowTitle("Настройки отчёта")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        # Flight title
        form = QFormLayout()
        self._title_edit = QLineEdit(Path(log_path).stem)
        form.addRow("Название полёта:", self._title_edit)
        layout.addLayout(form)

        # ── Data sections ─────────────────────────────────────────────────────
        data_grp = QGroupBox("Разделы отчёта")
        data_layout = QVBoxLayout(data_grp)
        self._cb_time     = QCheckBox("Время")
        self._cb_flight   = QCheckBox("Параметры полёта")
        self._cb_wind     = QCheckBox("Ветер")
        self._cb_attitude = QCheckBox("Углы")
        self._cb_photos   = QCheckBox("Фотосъёмка")
        self._cb_eff      = QCheckBox("Эффективность")
        self._cb_bat      = QCheckBox("Батарея")
        for cb in (self._cb_time, self._cb_flight, self._cb_wind,
                   self._cb_attitude, self._cb_photos, self._cb_eff, self._cb_bat):
            cb.setChecked(True)
            data_layout.addWidget(cb)
        layout.addWidget(data_grp)

        # ── Map sections ──────────────────────────────────────────────────────
        map_grp = QGroupBox("Картографические материалы")
        map_layout = QVBoxLayout(map_grp)
        self._cb_map_full = QCheckBox(
            "Карта трека на спутниковой подложке (с ветром при взлёте/посадке)"
        )
        self._cb_map_zoom = QCheckBox("Крупно взлёт и посадка")
        self._cb_map_photos = QCheckBox("    Отобразить точки съёмки на карте")
        self._cb_map_full.setChecked(True)
        self._cb_map_zoom.setChecked(True)
        self._cb_map_photos.setChecked(True)
        # disable sub-option when both map checkboxes are off
        def _update_photos_enabled():
            self._cb_map_photos.setEnabled(
                self._cb_map_full.isChecked() or self._cb_map_zoom.isChecked()
            )
        self._cb_map_full.toggled.connect(_update_photos_enabled)
        self._cb_map_zoom.toggled.connect(_update_photos_enabled)
        map_layout.addWidget(self._cb_map_full)
        map_layout.addWidget(self._cb_map_zoom)
        map_layout.addWidget(self._cb_map_photos)
        layout.addWidget(map_grp)

        # ── Attachments ───────────────────────────────────────────────────────
        self._cb_kml = QCheckBox("Добавить KML-файл трека")
        self._cb_kml.setChecked(True)
        layout.addWidget(self._cb_kml)

        # ── Output directory ──────────────────────────────────────────────────
        path_grp = QGroupBox("Папка для сохранения")
        path_layout = QHBoxLayout(path_grp)
        self._path_label = QLabel(self._out_dir)
        self._path_label.setWordWrap(True)
        browse_btn = QPushButton("Обзор...")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse)
        path_layout.addWidget(self._path_label, 1)
        path_layout.addWidget(browse_btn)
        layout.addWidget(path_grp)

        # ── Buttons ───────────────────────────────────────────────────────────
        btns = QHBoxLayout()
        ok_btn = QPushButton("Сформировать")
        cancel_btn = QPushButton("Отмена")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_generate)
        cancel_btn.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(
            self, "Выберите папку для сохранения", self._out_dir
        )
        if path:
            self._out_dir = path
            self._path_label.setText(path)

    def _sections(self) -> set[str]:
        s: set[str] = set()
        if self._cb_time.isChecked():     s.add("time")
        if self._cb_flight.isChecked():   s.add("flight")
        if self._cb_wind.isChecked():     s.add("wind")
        if self._cb_attitude.isChecked(): s.add("attitude")
        if self._cb_photos.isChecked():   s.add("photos")
        if self._cb_eff.isChecked():      s.add("efficiency")
        if self._cb_bat.isChecked():      s.add("battery")
        return s

    def _on_generate(self):
        title        = self._title_edit.text().strip() or Path(self._log_path).stem
        stem         = Path(self._log_path).stem
        log_filename = Path(self._log_path).name
        sections     = self._sections()
        want_full       = self._cb_map_full.isChecked()
        want_zoom       = self._cb_map_zoom.isChecked()
        include_photos  = self._cb_map_photos.isChecked() and self._cb_map_photos.isEnabled()

        # ── Build map images ──────────────────────────────────────────────────
        images: dict = {}
        if want_full or want_zoom:
            try:
                images = _build_map_images(self._log_data, want_full, want_zoom, include_photos)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(
                    self, "Предупреждение",
                    f"Не удалось создать карту (карта будет пропущена):\n{exc}"
                )

        # ── Generate PDF ──────────────────────────────────────────────────────
        pdf_path = os.path.join(self._out_dir, f"{stem}_отчет.pdf")
        try:
            generate_pdf(pdf_path, title, self._stats, sections, log_filename, images)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать PDF:\n{exc}")
            return

        # ── Generate KML ──────────────────────────────────────────────────────
        kml_path = None
        if self._cb_kml.isChecked():
            kml_path = os.path.join(self._out_dir, f"{stem}.kml")
            try:
                generate_kml(self._log_data, kml_path)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Ошибка", f"Не удалось создать KML:\n{exc}")
                return

        msg = f"PDF отчёт сохранён:\n{pdf_path}"
        if kml_path:
            msg += f"\n\nKML трек:\n{kml_path}"
        QMessageBox.information(self, "Отчёт сформирован", msg)
        self.accept()
