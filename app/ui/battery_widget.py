"""Battery tab - per-instance stats: mAh consumed, max/average current."""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel

from app.core import i18n
from app.core.log_loader import LogData


def _battery_instance_table(bat_table, bat2_table, instance: int):
    if bat_table:
        instance_field = "Instance" if "Instance" in bat_table else ("Inst" if "Inst" in bat_table else None)
        if instance_field:
            mask = bat_table[instance_field] == float(instance)
            if np.any(mask):
                return {k: v[mask] for k, v in bat_table.items()}
        elif instance == 0:
            return bat_table
    if instance == 1 and bat2_table:
        return bat2_table
    return None


class BatteryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.bat1_group = QGroupBox()
        self.bat1_form = QFormLayout(self.bat1_group)
        self.bat1_mah_label = QLabel("—")
        self.bat1_max_curr_label = QLabel("—")
        self.bat1_avg_curr_label = QLabel("—")
        self.bat1_form.addRow(" ", self.bat1_mah_label)
        self.bat1_form.addRow(" ", self.bat1_max_curr_label)
        self.bat1_form.addRow(" ", self.bat1_avg_curr_label)
        layout.addWidget(self.bat1_group)

        self.bat2_group = QGroupBox()
        self.bat2_form = QFormLayout(self.bat2_group)
        self.bat2_mah_label = QLabel("—")
        self.bat2_max_curr_label = QLabel("—")
        self.bat2_avg_curr_label = QLabel("—")
        self.bat2_form.addRow(" ", self.bat2_mah_label)
        self.bat2_form.addRow(" ", self.bat2_max_curr_label)
        self.bat2_form.addRow(" ", self.bat2_avg_curr_label)
        layout.addWidget(self.bat2_group)

        layout.addStretch()
        i18n.register(self._retranslateUi)
        self._retranslateUi()

    def _retranslateUi(self):
        tr = i18n.tr
        self.bat1_group.setTitle(tr("Батарея 1"))
        self.bat1_form.labelForField(self.bat1_mah_label).setText(tr("Потрачено мА·ч:"))
        self.bat1_form.labelForField(self.bat1_max_curr_label).setText(tr("Максимальный ток:"))
        self.bat1_form.labelForField(self.bat1_avg_curr_label).setText(tr("Средний ток:"))
        self.bat2_group.setTitle(tr("Батарея 2"))
        self.bat2_form.labelForField(self.bat2_mah_label).setText(tr("Потрачено мА·ч:"))
        self.bat2_form.labelForField(self.bat2_max_curr_label).setText(tr("Максимальный ток:"))
        self.bat2_form.labelForField(self.bat2_avg_curr_label).setText(tr("Средний ток:"))

    def load(self, log_data: LogData):
        bat_table = log_data.messages.get("BAT")
        bat2_table = log_data.messages.get("BAT2")

        for instance, mah_label, max_label, avg_label in (
            (0, self.bat1_mah_label, self.bat1_max_curr_label, self.bat1_avg_curr_label),
            (1, self.bat2_mah_label, self.bat2_max_curr_label, self.bat2_avg_curr_label),
        ):
            sub = _battery_instance_table(bat_table, bat2_table, instance)
            mah, max_curr, avg_curr = self._stats(sub)
            mah_label.setText(f"{mah:.0f} мА·ч" if mah is not None else "—")
            max_label.setText(f"{max_curr:.1f} А" if max_curr is not None else "—")
            avg_label.setText(f"{avg_curr:.1f} А" if avg_curr is not None else "—")

    def clear(self):
        for label in (
            self.bat1_mah_label, self.bat1_max_curr_label, self.bat1_avg_curr_label,
            self.bat2_mah_label, self.bat2_max_curr_label, self.bat2_avg_curr_label,
        ):
            label.setText("—")

    def _stats(self, sub) -> tuple[float | None, float | None, float | None]:
        if not sub:
            return None, None, None

        mah = None
        if "CurrTot" in sub and len(sub["CurrTot"]):
            mah = float(sub["CurrTot"][-1])
        elif "Curr" in sub and len(sub["Curr"]) > 1:
            t = sub["timestamp"]
            curr = sub["Curr"]
            dt_hours = np.diff(t) / 3600.0
            mah = float(np.sum(curr[:-1] * dt_hours) * 1000.0)

        max_curr = avg_curr = None
        if "Curr" in sub and len(sub["Curr"]):
            curr = sub["Curr"]
            max_curr = float(np.max(curr))
            avg_curr = float(np.mean(curr))

        return mah, max_curr, avg_curr
