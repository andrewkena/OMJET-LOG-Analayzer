"""pyqtgraph AxisItem that renders ticks as MM:SS relative to a settable origin."""
from __future__ import annotations

import pyqtgraph as pg

from app.core.time_format import format_mmss


class TimeAxisItem(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.t0 = 0.0
        self.enableAutoSIPrefix(False)

    def set_origin(self, t0: float):
        self.t0 = t0
        self.update()

    def tickStrings(self, values, scale, spacing):
        return [format_mmss(v - self.t0) for v in values]
