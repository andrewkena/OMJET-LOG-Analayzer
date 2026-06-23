"""Time-series plot widget, multi-curve, with a synced cursor (like plot.ardupilot.org)."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from app.ui.time_axis import TimeAxisItem

_COLORS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
           "#42d4f4", "#f032e6", "#bfef45", "#469990", "#9a6324"]

MAX_CURVES = 4


class GraphWidget(QWidget):
    cursor_moved = Signal(float)  # emits timestamp under cursor

    def __init__(self, parent=None):
        super().__init__(parent)
        self.time_axis = TimeAxisItem(orientation="bottom")
        self.plot_widget = pg.PlotWidget(axisItems={"bottom": self.time_axis})
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.addLegend()
        self.legend = self.plot_widget.plotItem.legend

        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet("font-size: 11px; color: #aaaaaa;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot_widget)
        layout.addWidget(self.stats_label)

        self._curves: dict[str, pg.PlotDataItem] = {}
        self._curve_y: dict[str, np.ndarray] = {}
        self._color_idx = 0

        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("w", width=1))
        self.plot_widget.addItem(self.vline, ignoreBounds=True)
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)

        self.selection_region = pg.LinearRegionItem(
            brush=pg.mkBrush(255, 255, 0, 30), movable=False
        )
        self.selection_region.setZValue(-10)
        self.plot_widget.addItem(self.selection_region, ignoreBounds=True)
        self.selection_region.hide()

    def set_time_origin(self, t0: float):
        self.time_axis.set_origin(t0)

    def _next_color(self) -> str:
        c = _COLORS[self._color_idx % len(_COLORS)]
        self._color_idx += 1
        return c

    def curve_count(self) -> int:
        return len(self._curves)

    def add_curve(self, key: str, t, y, label: str) -> bool:
        if key in self._curves:
            return True
        if len(self._curves) >= MAX_CURVES:
            return False
        pen = pg.mkPen(self._next_color(), width=1.5)
        curve = self.plot_widget.plot(t, y, pen=pen, name=label)
        self._curves[key] = curve
        self._curve_y[key] = np.asarray(y, dtype=float)
        self._update_stats()
        return True

    def remove_curve(self, key: str):
        curve = self._curves.pop(key, None)
        if curve is not None:
            self.plot_widget.removeItem(curve)
            self.legend.removeItem(curve.name())
        self._curve_y.pop(key, None)
        self._update_stats()

    def clear_all(self):
        for key in list(self._curves):
            self.remove_curve(key)
        self._color_idx = 0

    def set_cursor_time(self, t: float):
        self.vline.setPos(t)

    def set_selected_range(self, t0: float, t1: float):
        self.selection_region.setRegion((t0, t1))
        self.selection_region.show()

    def clear_selected_range(self):
        self.selection_region.hide()

    def _update_stats(self):
        if not self._curve_y:
            self.stats_label.setText("")
            return
        parts = []
        for key, y in self._curve_y.items():
            if len(y) == 0:
                continue
            parts.append(
                f"{key}  min={np.nanmin(y):.3g}  max={np.nanmax(y):.3g}  mean={np.nanmean(y):.3g}"
            )
        self.stats_label.setText("    ".join(parts))

    def _on_mouse_moved(self, scene_pos):
        view_pos = self.plot_widget.plotItem.vb.mapSceneToView(scene_pos)
        self.cursor_moved.emit(view_pos.x())
