"""Table of mission waypoints/commands extracted from the log (CMD / MISSION_ITEM).

Each command id is decoded against the ArduPilot/MAVLink MAV_CMD enum so the
purpose of every mission point is shown in plain text. The mission can also
be exported as a standard ArduPilot/Mission Planner ".waypoints" file
(QGC WPL 110 format).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QFileDialog, QMessageBox
)
from pymavlink import mavutil

from app.core.log_loader import LogData

_LAT_FIELDS = ["Lat", "lat", "x"]
_LON_FIELDS = ["Lng", "Lon", "lon", "y"]
_COLUMNS = ["Seq", "Cmd ID", "Command", "Description", "Lat", "Lng", "Alt", "Frame", "Params"]

_MAV_CMD = mavutil.mavlink.enums.get("MAV_CMD", {})


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
    description = (entry.description or "").split("\n")[0].strip()
    return name, description


class MissionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._waypoints: list[tuple[float, float]] = []
        self._export_rows: list[dict] = []

        self.download_button = QPushButton("Download Mission (.waypoints)")
        self.download_button.clicked.connect(self._on_download_clicked)

        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.download_button)
        layout.addWidget(self.table)

    def load(self, log_data: LogData):
        rows = log_data.mission()
        self.table.setRowCount(len(rows))
        self._waypoints = []
        self._export_rows = []

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

            self.table.setItem(i, 0, QTableWidgetItem(str(seq)))
            self.table.setItem(i, 1, QTableWidgetItem(str(int(cmd_id)) if cmd_id != "" else ""))
            self.table.setItem(i, 2, QTableWidgetItem(name))
            self.table.setItem(i, 3, QTableWidgetItem(description))
            self.table.setItem(i, 4, QTableWidgetItem(f"{lat_deg:.6f}"))
            self.table.setItem(i, 5, QTableWidgetItem(f"{lon_deg:.6f}"))
            self.table.setItem(i, 6, QTableWidgetItem(f"{alt:g}" if isinstance(alt, float) else str(alt)))
            self.table.setItem(i, 7, QTableWidgetItem(str(frame)))
            self.table.setItem(i, 8, QTableWidgetItem(params))

        self.table.resizeColumnsToContents()

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
