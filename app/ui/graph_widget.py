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
        self._curve_t: dict[str, np.ndarray] = {}
        self._curve_y: dict[str, np.ndarray] = {}
        self._minmax_items: dict[str, tuple] = {}
        self._hover_items: dict[str, tuple[pg.ScatterPlotItem, pg.TextItem]] = {}
        self._color_idx = 0
        self._last_cursor_t = 0.0

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
        color = self._next_color()
        pen = pg.mkPen(color, width=1.5)
        curve = self.plot_widget.plot(t, y, pen=pen, name=label)
        self._curves[key] = curve
        self._curve_t[key] = np.asarray(t, dtype=float)
        self._curve_y[key] = np.asarray(y, dtype=float)
        self._add_minmax_markers(key, color)
        self._add_hover_marker(key, color)
        self._update_hover(self._last_cursor_t)
        self._update_stats()
        return True

    def remove_curve(self, key: str):
        curve = self._curves.pop(key, None)
        if curve is not None:
            self.plot_widget.removeItem(curve)
            self.legend.removeItem(curve.name())
        self._curve_t.pop(key, None)
        self._curve_y.pop(key, None)
        for item in self._minmax_items.pop(key, ()):
            self.plot_widget.removeItem(item)
        for item in self._hover_items.pop(key, ()):
            self.plot_widget.removeItem(item)
        self._update_stats()

    def clear_all(self):
        for key in list(self._curves):
            self.remove_curve(key)
        self._color_idx = 0

    def _add_minmax_markers(self, key: str, color: str):
        t = self._curve_t[key]
        y = self._curve_y[key]
        if len(y) == 0 or np.all(np.isnan(y)):
            return
        imin = int(np.nanargmin(y))
        imax = int(np.nanargmax(y))
        min_dot = pg.ScatterPlotItem(x=[t[imin]], y=[y[imin]], pen=pg.mkPen(color), brush=pg.mkBrush(color), size=9)
        max_dot = pg.ScatterPlotItem(x=[t[imax]], y=[y[imax]], pen=pg.mkPen(color), brush=pg.mkBrush(color), size=9)
        min_label = pg.TextItem(f"min {y[imin]:.3g}", color=color, anchor=(0.5, 0))
        min_label.setPos(t[imin], y[imin])
        max_label = pg.TextItem(f"max {y[imax]:.3g}", color=color, anchor=(0.5, 1))
        max_label.setPos(t[imax], y[imax])
        items = (min_dot, max_dot, min_label, max_label)
        for item in items:
            self.plot_widget.addItem(item, ignoreBounds=True)
        self._minmax_items[key] = items

    def _add_hover_marker(self, key: str, color: str):
        dot = pg.ScatterPlotItem(x=[], y=[], pen=pg.mkPen(color), brush=pg.mkBrush(color), size=8)
        dot.setZValue(10)
        label = pg.TextItem("", color=color, anchor=(0, 1))
        label.setZValue(10)
        self.plot_widget.addItem(dot, ignoreBounds=True)
        self.plot_widget.addItem(label, ignoreBounds=True)
        dot.hide()
        label.hide()
        self._hover_items[key] = (dot, label)

    def _update_hover(self, t: float):
        for key, (dot, label) in self._hover_items.items():
            tarr = self._curve_t.get(key)
            yarr = self._curve_y.get(key)
            if tarr is None or len(tarr) == 0:
                dot.hide()
                label.hide()
                continue
            idx = int(np.searchsorted(tarr, t))
            idx = min(max(idx, 0), len(tarr) - 1)
            if idx > 0 and abs(tarr[idx - 1] - t) < abs(tarr[idx] - t):
                idx -= 1
            yv = yarr[idx]
            if np.isnan(yv):
                dot.hide()
                label.hide()
                continue
            dot.setData(x=[tarr[idx]], y=[yv])
            dot.show()
            label.setPos(tarr[idx], yv)
            label.setText(f"{yv:.3g}")
            label.show()

    def set_cursor_time(self, t: float):
        self.vline.setPos(t)
        self._last_cursor_t = t
        self._update_hover(t)

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
