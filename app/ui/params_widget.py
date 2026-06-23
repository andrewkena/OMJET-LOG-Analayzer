"""Parameter list extracted from the log (PARM / PARAM_VALUE), laid out as
three side-by-side columns so long parameter lists don't require excessive
vertical scrolling."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QPushButton, QFileDialog, QMessageBox, QComboBox, QLabel, QGroupBox
)
from PySide6.QtCore import Signal

from app.core.log_loader import LogData

_COLUMN_COUNT = 3


class ParamsWidget(QWidget):
    battery_cell_count_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._battery_cells = 4  # Default 4S

        # Battery settings group
        battery_group = QGroupBox("Battery Settings")
        battery_layout = QHBoxLayout(battery_group)

        battery_layout.addWidget(QLabel("Battery Cell Count:"))

        self.cell_combo = QComboBox()
        self.cell_combo.addItems(["4S", "6S", "8S", "10S", "12S"])
        self.cell_combo.setCurrentText("4S")
        self.cell_combo.currentTextChanged.connect(self._on_cell_count_changed)
        battery_layout.addWidget(self.cell_combo)
        battery_layout.addStretch()

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter parameters...")
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.download_button = QPushButton("Download Parameters (.param)")
        self.download_button.clicked.connect(self._on_download_clicked)

        top_row = QHBoxLayout()
        top_row.addWidget(self.filter_edit)
        top_row.addWidget(self.download_button)

        self.tables: list[QTableWidget] = []
        columns_layout = QHBoxLayout()
        for _ in range(_COLUMN_COUNT):
            table = QTableWidget()
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels(["Parameter", "Value"])
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setSortingEnabled(True)
            self.tables.append(table)
            columns_layout.addWidget(table)

        layout = QVBoxLayout(self)
        layout.addWidget(battery_group)
        layout.addLayout(top_row)
        layout.addLayout(columns_layout)

    def get_battery_cell_count(self) -> int:
        """Return the currently selected battery cell count."""
        return self._battery_cells

    def _on_cell_count_changed(self, text: str):
        """Handle battery cell count change."""
        self._battery_cells = int(text.replace("S", ""))
        self.battery_cell_count_changed.emit(self._battery_cells)

    def load(self, log_data: LogData):
        self._rows = log_data.parameters()
        self._populate(self._rows)

    def _populate(self, rows: list[dict]):
        chunk_size = max(1, -(-len(rows) // _COLUMN_COUNT))  # ceil division
        chunks = [rows[i:i + chunk_size] for i in range(0, len(rows), chunk_size)]
        chunks += [[]] * (_COLUMN_COUNT - len(chunks))

        for table, chunk in zip(self.tables, chunks):
            table.setSortingEnabled(False)
            table.setRowCount(len(chunk))
            for i, row in enumerate(chunk):
                table.setItem(i, 0, QTableWidgetItem(row["name"]))
                table.setItem(i, 1, QTableWidgetItem(f"{row['value']:g}"))
            table.setSortingEnabled(True)
            table.resizeColumnsToContents()

    def _apply_filter(self, text: str):
        text = text.strip().lower()
        if not text:
            self._populate(self._rows)
            return
        filtered = [r for r in self._rows if text in r["name"].lower()]
        self._populate(filtered)

    def _on_download_clicked(self):
        if not self._rows:
            QMessageBox.information(self, "No parameters", "No parameters loaded.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Parameters", "parameters.param",
            "ArduPilot parameter files (*.param *.parm);;All Files (*)"
        )
        if not path:
            return
        self._export_param_file(Path(path))

    def _export_param_file(self, path: Path):
        lines = [f"{row['name']},{row['value']:.6f}" for row in sorted(self._rows, key=lambda r: r["name"])]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
