"""Timeline scrubber: movable playhead to scrub through the track, plus a
draggable range region to select an interval that gets reflected in the
graphs and on the map."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal, Qt, QEvent, QPointF
from PySide6.QtWidgets import QWidget, QVBoxLayout

from app.core.time_format import format_mmss
from app.ui.time_axis import TimeAxisItem


class TimelineWidget(QWidget):
    cursor_changed = Signal(float)
    range_changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.time_axis = TimeAxisItem(orientation="bottom")
        self.plot_widget = pg.PlotWidget(axisItems={"bottom": self.time_axis})
        self.plot_widget.setFixedHeight(100)
        self.plot_widget.showGrid(x=True, y=False, alpha=0.3)
        self.plot_widget.getPlotItem().hideAxis("left")
        self.plot_widget.setLabel("bottom", "Время (мм:сс)")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot_widget)

        self.terrain_curve = self.plot_widget.plot(
            [], [], pen=pg.mkPen("#8b5a2b", width=1), fillLevel=0, brush=pg.mkBrush(139, 90, 43, 110)
        )
        self.backdrop_curve = self.plot_widget.plot([], [], pen=pg.mkPen("#888", width=1))

        self.region = pg.LinearRegionItem(brush=pg.mkBrush(255, 255, 255, 40))
        self.region.setZValue(10)
        self.plot_widget.addItem(self.region)
        self.region.sigRegionChanged.connect(self._on_region_changed)

        self.playhead = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#e6194b", width=2))
        self.playhead.setZValue(20)
        self.plot_widget.addItem(self.playhead)
        self.playhead.sigPositionChanged.connect(self._on_playhead_changed)

        self.time_label = pg.TextItem(anchor=(0.5, 1.2), color="#e6194b")
        self.time_label.setZValue(30)
        self.plot_widget.addItem(self.time_label)

        self._t0 = 0.0
        self._t1 = 0.0
        self._suppress = False

        self.plot_widget.viewport().installEventFilter(self)

    def _timeline_t_from_event(self, event):
        vb = self.plot_widget.getViewBox()
        try:
            pt = event.position()
        except AttributeError:
            pt = QPointF(event.pos())
        data_pt = vb.mapSceneToView(pt)
        return max(self._t0, min(self._t1, data_pt.x()))

    def eventFilter(self, obj, event):
        if obj is self.plot_widget.viewport() and self._t1 > self._t0:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                t = self._timeline_t_from_event(event)
                self.set_cursor_time(t)
                self.cursor_changed.emit(t)
            elif event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
                t = self._timeline_t_from_event(event)
                self.set_cursor_time(t)
                self.cursor_changed.emit(t)
        return False

    def set_range(self, t0: float, t1: float, backdrop_t: np.ndarray | None = None,
                  backdrop_y: np.ndarray | None = None, terrain_t: np.ndarray | None = None,
                  terrain_y: np.ndarray | None = None):
        self._t0, self._t1 = t0, t1
        self.time_axis.set_origin(t0)
        self._suppress = True
        self.region.setBounds((t0, t1))
        self.region.setRegion((t0, t1))
        self.playhead.setBounds((t0, t1))
        self.playhead.setPos(t0)
        self.plot_widget.setXRange(t0, t1, padding=0.02)
        self._suppress = False
        if backdrop_t is not None and backdrop_y is not None and len(backdrop_t):
            self.backdrop_curve.setData(backdrop_t, backdrop_y)
        else:
            self.backdrop_curve.setData([], [])
        if terrain_t is not None and terrain_y is not None and len(terrain_t):
            self.terrain_curve.setData(terrain_t, terrain_y)
        else:
            self.terrain_curve.setData([], [])
        self._update_time_label(t0)

    def set_cursor_time(self, t: float):
        self._suppress = True
        self.playhead.setPos(t)
        self._suppress = False
        self._update_time_label(t)

    def _update_time_label(self, t: float):
        self.time_label.setText(format_mmss(t - self._t0))
        top_y = self.plot_widget.viewRange()[1][1]
        self.time_label.setPos(t, top_y)

    def _on_playhead_changed(self):
        t = self.playhead.value()
        self._update_time_label(t)
        if self._suppress:
            return
        self.cursor_changed.emit(t)

    def _on_region_changed(self):
        if self._suppress:
            return
        t0, t1 = self.region.getRegion()
        self.range_changed.emit(t0, t1)
