"""Application settings tab - battery configuration and other app preferences."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QComboBox, QCheckBox,
    QSpinBox, QFormLayout, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Signal


class SettingsWidget(QWidget):
    """Application settings - battery configuration and preferences."""

    # Signals for settings changes
    battery_cell_count_changed = Signal(int)
    battery_hv_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._battery_cells = 4
        self._battery_hv = False

        layout = QVBoxLayout(self)

        # Battery Configuration
        battery_group = QGroupBox("Battery Configuration")
        battery_layout = QFormLayout(battery_group)

        # Cell count selector
        self.cell_count_combo = QComboBox()
        self.cell_count_combo.addItems(["4S", "6S", "8S", "10S", "12S"])
        self.cell_count_combo.setCurrentText("4S")
        self.cell_count_combo.currentTextChanged.connect(self._on_cell_count_changed)
        battery_layout.addRow("Cell Count:", self.cell_count_combo)

        # HV checkbox for LiHV batteries
        self.hv_checkbox = QCheckBox("LiHV (High Voltage)")
        self.hv_checkbox.setToolTip(
            "Enable for LiHV batteries\n"
            "Standard LiPo: 4.20V/cell (full) / 3.60V/cell (empty)\n"
            "LiHV: 4.35V/cell (full) / 3.60V/cell (empty)"
        )
        self.hv_checkbox.stateChanged.connect(self._on_hv_changed)
        battery_layout.addRow("Battery Type:", self.hv_checkbox)

        # Voltage thresholds info
        self.threshold_label = QLabel()
        self._update_threshold_label()
        battery_layout.addRow("Voltage Range:", self.threshold_label)

        layout.addWidget(battery_group)

        # Info section
        info_group = QGroupBox("Battery Voltage Info")
        info_layout = QVBoxLayout(info_group)

        info_layout.addWidget(QLabel("LiPo / Li-ion:"))
        info_layout.addWidget(QLabel("  • Full charge: 4.20V per cell"))
        info_layout.addWidget(QLabel("  • Safe minimum: 3.60V per cell"))
        info_layout.addWidget(QLabel(""))
        info_layout.addWidget(QLabel("LiHV (High Voltage):"))
        info_layout.addWidget(QLabel("  • Full charge: 4.35V per cell"))
        info_layout.addWidget(QLabel("  • Safe minimum: 3.60V per cell"))

        layout.addWidget(info_group)
        layout.addStretch()

    def _on_cell_count_changed(self, text: str):
        """Handle battery cell count change."""
        self._battery_cells = int(text.replace("S", ""))
        self.battery_cell_count_changed.emit(self._battery_cells)

    def _on_hv_changed(self, state: int):
        """Handle HV checkbox change."""
        self._battery_hv = (state == 2)  # Qt.Checked = 2
        self.battery_hv_changed.emit(self._battery_hv)
        self._update_threshold_label()

    def _update_threshold_label(self):
        """Update the voltage threshold display."""
        if self._battery_hv:
            self.threshold_label.setText(
                f"<span style='color: #3cb44b;'>4.35V</span> / "
                f"<span style='color: #e6194b;'>3.60V</span> per cell"
            )
        else:
            self.threshold_label.setText(
                f"<span style='color: #3cb44b;'>4.20V</span> / "
                f"<span style='color: #e6194b;'>3.60V</span> per cell"
            )

    def get_battery_cell_count(self) -> int:
        """Return the currently selected battery cell count."""
        return self._battery_cells

    def is_hv_battery(self) -> bool:
        """Return whether LiHV mode is enabled."""
        return self._battery_hv
