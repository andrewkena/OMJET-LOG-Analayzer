"""Time-series plot widget, multi-curve, independent Y axis per curve."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal, QEvent
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

        pi = self.plot_widget.plotItem
        pi.addLegend()
        self.legend = pi.legend

        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet("font-size: 11px; color: #aaaaaa;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot_widget)
        layout.addWidget(self.stats_label)

        # slot 0  → main ViewBox (pi.vb) with existing left Y axis
        # slots 1‥MAX_CURVES-1 → secondary ViewBoxes with right Y axes
        self._all_vbs: list[pg.ViewBox] = [pi.vb]
        self._right_axes: list[pg.AxisItem] = []
        for i in range(MAX_CURVES - 1):
            vb = pg.ViewBox()
            pi.scene().addItem(vb)
            ax = pg.AxisItem("right")
            pi.layout.addItem(ax, 2, 3 + i)
            ax.linkToView(vb)
            vb.setXLink(pi)
            vb.setVisible(False)
            ax.setVisible(False)
            self._all_vbs.append(vb)
            self._right_axes.append(ax)

        pi.vb.sigResized.connect(self._sync_vb_geometry)

        self._curves: dict[str, pg.PlotDataItem] = {}
        self._curve_t: dict[str, np.ndarray] = {}
        self._curve_y: dict[str, np.ndarray] = {}
        self._curve_slot: dict[str, int] = {}   # key → slot index (0 = main VB)
        self._curve_label: dict[str, str] = {}
        self._minmax_items: dict[str, tuple] = {}
        self._hover_items: dict[str, tuple[pg.ScatterPlotItem, pg.TextItem]] = {}
        self._color_idx = 0
        self._last_cursor_t = 0.0

        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("w", width=1))
        self.plot_widget.addItem(self.vline, ignoreBounds=True)
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.plot_widget.viewport().installEventFilter(self)

        self.selection_region = pg.LinearRegionItem(
            brush=pg.mkBrush(255, 255, 0, 30), movable=False
        )
        self.selection_region.setZValue(-10)
        self.plot_widget.addItem(self.selection_region, ignoreBounds=True)
        self.selection_region.hide()

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _sync_vb_geometry(self):
        rect = self.plot_widget.plotItem.vb.sceneBoundingRect()
        for vb in self._all_vbs[1:]:
            if vb.isVisible():
                vb.setGeometry(rect)

    def _free_slot(self) -> int:
        used = set(self._curve_slot.values())
        for i in range(MAX_CURVES):
            if i not in used:
                return i
        return 0

    def _next_color(self) -> str:
        c = _COLORS[self._color_idx % len(_COLORS)]
        self._color_idx += 1
        return c

    # ------------------------------------------------------------------ #
    #  Wheel zoom – per-axis                                               #
    # ------------------------------------------------------------------ #

    def eventFilter(self, obj, event):
        if obj is self.plot_widget.viewport() and event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            if delta == 0:
                return False
            factor = 0.85 if delta > 0 else 1.0 / 0.85

            pi = self.plot_widget.plotItem
            main_vb = pi.vb
            try:
                vp_pos = event.position().toPoint()
            except AttributeError:
                vp_pos = event.pos()
            scene_pos = self.plot_widget.mapToScene(vp_pos)
            scene_rect = main_vb.sceneBoundingRect()

            if scene_pos.x() < scene_rect.left():
                # Left Y axis → zoom main VB Y only
                data_pt = main_vb.mapSceneToView(scene_pos)
                main_vb.scaleBy((1.0, factor), pg.Point(data_pt.x(), data_pt.y()))
                return True
            if scene_pos.y() > scene_rect.bottom():
                # X axis → zoom X (shared; all linked VBs follow)
                data_pt = main_vb.mapSceneToView(
                    pg.Point(scene_pos.x(), scene_rect.center().y())
                )
                main_vb.scaleBy((factor, 1.0), pg.Point(data_pt.x(), data_pt.y()))
                return True
            if scene_pos.x() > scene_rect.right():
                # Right Y axes → zoom the matching secondary VB only
                for i, ax in enumerate(self._right_axes):
                    if ax.isVisible() and ax.sceneBoundingRect().contains(scene_pos):
                        sec_vb = self._all_vbs[i + 1]
                        data_pt = sec_vb.mapSceneToView(scene_pos)
                        sec_vb.scaleBy((1.0, factor), pg.Point(data_pt.x(), data_pt.y()))
                        return True
        return False

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def set_time_origin(self, t0: float):
        self.time_axis.set_origin(t0)

    def curve_count(self) -> int:
        return len(self._curves)

    def add_curve(self, key: str, t, y, label: str) -> bool:
        if key in self._curves:
            return True
        if len(self._curves) >= MAX_CURVES:
            return False

        color = self._next_color()
        pen = pg.mkPen(color, width=1.5)
        slot = self._free_slot()
        vb = self._all_vbs[slot]

        if slot > 0:
            ax = self._right_axes[slot - 1]
            ax.setPen(pg.mkPen(color))
            ax.setTextPen(pg.mkPen(color))
            vb.setVisible(True)
            ax.setVisible(True)
            vb.setGeometry(self.plot_widget.plotItem.vb.sceneBoundingRect())

        t_arr = np.asarray(t, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        curve = pg.PlotDataItem(t_arr, y_arr, pen=pen, name=label)
        vb.addItem(curve)
        self.legend.addItem(curve, label)

        self._curves[key] = curve
        self._curve_t[key] = t_arr
        self._curve_y[key] = y_arr
        self._curve_slot[key] = slot
        self._curve_label[key] = label

        self._add_minmax_markers(key, color, vb)
        self._add_hover_marker(key, color, vb)
        self._update_hover(self._last_cursor_t)
        self._update_stats()
        return True

    def remove_curve(self, key: str):
        slot = self._curve_slot.pop(key, None)
        if slot is None:
            return
        vb = self._all_vbs[slot]

        curve = self._curves.pop(key, None)
        lbl = self._curve_label.pop(key, None)
        if curve is not None:
            vb.removeItem(curve)
            try:
                self.legend.removeItem(lbl or curve.name())
            except Exception:
                pass

        for item in self._minmax_items.pop(key, ()):
            try:
                vb.removeItem(item)
            except Exception:
                pass

        pair = self._hover_items.pop(key, None)
        if pair:
            for item in pair:
                try:
                    vb.removeItem(item)
                except Exception:
                    pass

        self._curve_t.pop(key, None)
        self._curve_y.pop(key, None)

        if slot > 0:
            self._all_vbs[slot].setVisible(False)
            self._right_axes[slot - 1].setVisible(False)

        self._update_stats()

    def clear_all(self):
        for key in list(self._curves):
            self.remove_curve(key)
        self._color_idx = 0

    # ------------------------------------------------------------------ #
    #  Markers                                                             #
    # ------------------------------------------------------------------ #

    def _add_minmax_markers(self, key: str, color: str, vb: pg.ViewBox):
        t = self._curve_t[key]
        y = self._curve_y[key]
        if len(y) == 0 or np.all(np.isnan(y)):
            return
        imin = int(np.nanargmin(y))
        imax = int(np.nanargmax(y))
        min_dot = pg.ScatterPlotItem(
            x=[t[imin]], y=[y[imin]], pen=pg.mkPen(color), brush=pg.mkBrush(color), size=9
        )
        max_dot = pg.ScatterPlotItem(
            x=[t[imax]], y=[y[imax]], pen=pg.mkPen(color), brush=pg.mkBrush(color), size=9
        )
        min_label = pg.TextItem(f"min {y[imin]:.3g}", color=color, anchor=(0.5, 0))
        min_label.setPos(t[imin], y[imin])
        max_label = pg.TextItem(f"max {y[imax]:.3g}", color=color, anchor=(0.5, 1))
        max_label.setPos(t[imax], y[imax])
        items = (min_dot, max_dot, min_label, max_label)
        for item in items:
            vb.addItem(item, ignoreBounds=True)
        self._minmax_items[key] = items

    def _add_hover_marker(self, key: str, color: str, vb: pg.ViewBox):
        dot = pg.ScatterPlotItem(
            x=[], y=[], pen=pg.mkPen(color), brush=pg.mkBrush(color), size=8
        )
        dot.setZValue(10)
        label = pg.TextItem("", color=color, anchor=(0, 1))
        label.setZValue(10)
        vb.addItem(dot, ignoreBounds=True)
        vb.addItem(label, ignoreBounds=True)
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

    # ------------------------------------------------------------------ #
    #  Cursor / selection                                                  #
    # ------------------------------------------------------------------ #

    def set_cursor_time(self, t: float):
        self.vline.setPos(t)
        self._last_cursor_t = t
        self._update_hover(t)

    def set_selected_range(self, t0: float, t1: float):
        self.selection_region.setRegion((t0, t1))
        self.selection_region.show()

    def clear_selected_range(self):
        self.selection_region.hide()

    # ------------------------------------------------------------------ #
    #  Stats bar                                                           #
    # ------------------------------------------------------------------ #

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
