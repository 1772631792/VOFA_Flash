"""基于 pyqtgraph 的波形页，外观参考 vofa_demo。"""

from __future__ import annotations

import math
from collections import deque
from itertools import islice

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from .theme import CHANNEL_COLORS, Theme

MAX_CHANNELS = 8


class PlotPage(pg.PlotWidget):
    """单个波形标签页：曲线、游标、水印、通道可见性与鼠标调参。"""

    gainChanged = Signal(int)
    offsetChanged = Signal(int)
    contextMenuRequested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setBackground(Theme.plot_bg)
        plot = self.getPlotItem()
        plot.setClipToView(True)
        plot.showGrid(x=True, y=True, alpha=0.22)
        plot.hideButtons()
        plot.setMenuEnabled(False)
        plot.getViewBox().setMouseEnabled(x=True, y=True)
        plot.setContentsMargins(8, 8, 8, 8)

        for axis_name in ("bottom", "left"):
            axis = plot.getAxis(axis_name)
            axis.setTextPen(pg.mkPen("#75869D"))
            axis.setPen(pg.mkPen("#7B8798"))
            axis.setTickFont(QFont("Consolas", 9))
        plot.getViewBox().setBorder(pg.mkPen("#E7EDF5"))
        plot.setLabel("bottom", "ms")
        plot.setYRange(-5, 5)
        plot.setXRange(-1000, 300)

        self.cursor = pg.InfiniteLine(
            angle=90, movable=True, pen=pg.mkPen(Theme.cursor, width=1)
        )
        self.addItem(self.cursor)
        self.cursor.setPos(0)

        self.watermark = pg.TextItem(
            "VOFA", anchor=(0.5, 0.5), color=(180, 208, 246, 70)
        )
        self.watermark.setFont(QFont("Segoe UI", 46, QFont.Weight.Bold))
        self.addItem(self.watermark)

        self.curves = [
            self.plot([], [], pen=pg.mkPen(CHANNEL_COLORS[i], width=1.7))
            for i in range(MAX_CHANNELS)
        ]

        self.channel_count = 3
        self.visible = [True] * MAX_CHANNELS
        self.buffers: list[deque[float]] = [
            deque(maxlen=50000) for _ in range(MAX_CHANNELS)
        ]
        self.times: deque[float] = deque(maxlen=50000)
        self.buffer_limit = 50000
        self.display_points = 1200
        self.dt_ms = 1.0
        self.sample_index = 0
        self.has_data = False
        self.auto_scale = True
        self.adjust_mode = False
        self._drag_last = None

    # ---------- 数据 ----------
    def append_sample(self, values: list[float]) -> None:
        t_ms = self.sample_index * self.dt_ms
        self.sample_index += 1
        self.times.append(float(t_ms))

        count = min(len(values), MAX_CHANNELS)
        self.channel_count = max(1, min(max(count, self.channel_count), MAX_CHANNELS))
        for i in range(MAX_CHANNELS):
            if i < count:
                value = float(values[i])
            else:
                value = self.buffers[i][-1] if self.buffers[i] else 0.0
            self.buffers[i].append(value)
        self.has_data = True

    def clear_data(self) -> None:
        self.times.clear()
        for buf in self.buffers:
            buf.clear()
        self.sample_index = 0
        self.has_data = False
        for curve in self.curves:
            curve.setData([], [])
        self.cursor.setPos(0)

    def set_dt(self, dt_ms: float) -> None:
        self.dt_ms = max(0.001, float(dt_ms))

    def set_buffer_limit(self, limit: int) -> None:
        limit = max(1000, int(limit))
        self.buffer_limit = limit
        self.times = deque(self.times, maxlen=limit)
        for i in range(MAX_CHANNELS):
            self.buffers[i] = deque(self.buffers[i], maxlen=limit)

    def set_display_points(self, points: int) -> None:
        self.display_points = max(100, int(points))

    def set_visible(self, index: int, visible: bool) -> None:
        if 0 <= index < MAX_CHANNELS:
            self.visible[index] = visible

    def set_channel_count(self, count: int) -> None:
        self.channel_count = max(0, min(int(count), MAX_CHANNELS))

    def set_channel_color(self, index: int, color: str) -> None:
        if 0 <= index < len(self.curves):
            self.curves[index].setPen(pg.mkPen(color, width=1.7))

    def set_adjust_mode(self, enabled: bool) -> None:
        self.adjust_mode = enabled
        self._drag_last = None
        self.setCursor(Qt.SizeAllCursor if enabled else Qt.ArrowCursor)

    # ---------- 绘制 ----------
    def refresh(self) -> None:
        n = len(self.times)
        if n == 0:
            for curve in self.curves:
                curve.setData([], [])
            return

        shown = min(self.display_points, n)
        x = np.fromiter(islice(self.times, n - shown, n), dtype=float, count=shown)
        x = x - x[-1]

        visible_arrays = []
        for i, curve in enumerate(self.curves):
            if i < self.channel_count and self.visible[i]:
                y = np.fromiter(
                    islice(self.buffers[i], n - shown, n), dtype=float, count=shown
                )
                curve.setData(x, y)
                visible_arrays.append(y)
            else:
                curve.setData([], [])

        if self.auto_scale and visible_arrays:
            ymin = float(min(arr.min() for arr in visible_arrays))
            ymax = float(max(arr.max() for arr in visible_arrays))
            if math.isclose(ymin, ymax, rel_tol=1e-6, abs_tol=1e-6):
                ymin -= 1.0
                ymax += 1.0
            margin = max(0.2, (ymax - ymin) * 0.15)
            self.setYRange(ymin - margin, ymax + margin, padding=0)

    def time_span_ms(self) -> float:
        n = len(self.times)
        if n < 2:
            return 0.0
        return abs(self.times[-1] - self.times[0])

    def total_points(self) -> int:
        return len(self.times)

    # ---------- 事件 ----------
    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        item = self.getPlotItem()
        if item is None or not hasattr(self, "watermark"):
            return
        rect = item.getViewBox().viewRect()
        self.watermark.setPos(rect.center().x(), rect.center().y())

    def mousePressEvent(self, ev) -> None:
        if self.adjust_mode and ev.button() == Qt.LeftButton:
            self._drag_last = ev.position()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        if self.adjust_mode and self._drag_last is not None and ev.buttons() & Qt.LeftButton:
            pos = ev.position()
            dx = pos.x() - self._drag_last.x()
            dy = pos.y() - self._drag_last.y()
            if abs(dy) >= 6:
                self.gainChanged.emit(1 if dy < 0 else -1)
                self._drag_last = pos
                ev.accept()
                return
            if abs(dx) >= 8:
                self.offsetChanged.emit(1 if dx > 0 else -1)
                self._drag_last = pos
                ev.accept()
                return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        self._drag_last = None
        super().mouseReleaseEvent(ev)

    def contextMenuEvent(self, ev) -> None:
        self.contextMenuRequested.emit(ev.globalPos())
        ev.accept()
