"""基于 pyqtgraph 的波形页：外观与交互参考 VOFA+ / 示波器。

设计要点：
- 纯白画布 + 极浅网格 + 细描边 + Consolas 刻度，摆脱 pyqtgraph 默认的灰黑配色。
- 右上角半透明图例，随通道名称 / 颜色 / 可见性实时刷新。
- 鼠标移入显示十字游标和数值读数面板（含相对时间）。
- Auto 打开时同时自适应 X（跟随最新数据窗口）与 Y（可见数据加边距）；
  手动滚轮缩放或拖动会自动关闭 Auto，避免"Auto 抢拖动"，也让 Auto 按钮确实有反馈。
"""

from __future__ import annotations

import math
from collections import deque
from itertools import islice

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QLabel

from .theme import CHANNEL_COLORS

MAX_CHANNELS = 8
Y_SMOOTH = 0.45

PLOT_THEMES = {
    "light": {
        "bg": "#FFFFFF",
        "border": "#D5DEEA",
        "tick": "#8A99AC",
        "grid_alpha": 0.5,
        "legend_brush": (255, 255, 255, 232),
        "legend_text": "#5B6B80",
        "watermark": (160, 186, 220, 34),
        "hint": (150, 168, 190, 190),
        "cursor": (96, 140, 196, 120),
        "readout_bg": "rgba(255, 255, 255, 244)",
        "readout_border": "#E2E9F2",
        "readout_text": "#4A5B70",
    },
    "dark": {
        "bg": "#1E1E1E",
        "border": "#3C3C3C",
        "tick": "#9D9D9D",
        "grid_alpha": 0.5,
        "legend_brush": (37, 37, 38, 236),
        "legend_text": "#CCCCCC",
        "watermark": (255, 255, 255, 14),
        "hint": (140, 140, 140, 190),
        "cursor": (120, 170, 255, 120),
        "readout_bg": "rgba(37, 37, 38, 246)",
        "readout_border": "#3C3C3C",
        "readout_text": "#D4D4D4",
    },
}

pg.setConfigOptions(antialias=True)


class PlotPage(pg.PlotWidget):
    """单个波形标签页：曲线、图例、十字游标、通道可见性与鼠标调参。"""

    gainChanged = Signal(int)
    offsetChanged = Signal(int)
    contextMenuRequested = Signal(object)
    autoScaleRequested = Signal(bool)

    def __init__(self, parent=None, dark: bool = False):
        pal = PLOT_THEMES["dark" if dark else "light"]
        self._palette = pal
        self._dark = bool(dark)
        super().__init__(parent=parent, background=pal["bg"])
        self.setMouseTracking(True)
        self.setMinimumHeight(180)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        plot = self.getPlotItem()
        plot.setClipToView(True)
        plot.hideButtons()
        plot.setMenuEnabled(False)
        plot.setContentsMargins(4, 6, 14, 4)
        plot.getViewBox().setBorder(pg.mkPen(pal["border"]))
        plot.getViewBox().setMouseEnabled(x=True, y=True)
        plot.getViewBox().setDefaultPadding(0.01)

        for axis_name in ("left", "bottom"):
            axis = plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(pal["border"]))
            axis.setTextPen(pg.mkPen(pal["tick"]))
            axis.setTickFont(QFont("Consolas", 9))
            axis.setStyle(tickLength=-4, tickTextOffset=8, autoExpandTextSpace=False)
        plot.showGrid(x=True, y=True, alpha=pal["grid_alpha"])
        plot.hideAxis("top")
        plot.hideAxis("right")
        plot.setLabel("bottom", "时间 / ms")
        if hasattr(plot.getAxis("bottom"), "label"):
            plot.getAxis("bottom").label.setDefaultTextColor(QColor(pal["tick"]))
        plot.setXRange(0, 1200, padding=0)
        plot.setYRange(-5, 5, padding=0)

        # ---- 水印（挂在 ViewBox 上，使用像素坐标居中） ----
        self.watermark = pg.TextItem("VOFA", anchor=(0.5, 0.5), color=pal["watermark"])
        self.watermark.setFont(QFont("Segoe UI", 44, QFont.Weight.Bold))
        self.watermark.setZValue(-20)
        # 直接挂到 ViewBox 上：这样坐标是像素坐标，可以稳定居中且不随数据平移
        self.watermark.setParentItem(plot.getViewBox())

        self.hint = pg.TextItem("等待数据…", anchor=(0.5, 0.5), color=pal["hint"])
        self.hint.setFont(QFont("Microsoft YaHei UI", 12))
        self.hint.setZValue(-19)
        self.hint.setParentItem(plot.getViewBox())

        # ---- 曲线 ----
        self.curves: list[pg.PlotDataItem] = []
        self._colors: list[str] = list(CHANNEL_COLORS)
        for i in range(MAX_CHANNELS):
            curve = pg.PlotDataItem(pen=pg.mkPen(self._colors[i], width=1.6))
            curve.setClipToView(True)
            curve.setDownsampling(auto=True, method="peak")
            try:
                curve.setSkipFiniteCheck(True)
            except AttributeError:  # 旧版本 pyqtgraph
                pass
            plot.addItem(curve)
            self.curves.append(curve)

        # ---- 图例 ----
        self.legend = pg.LegendItem(
            offset=(-12, 12),
            brush=pg.mkBrush(*pal["legend_brush"]),
            pen=pg.mkPen(pal["border"]),
            labelTextColor=pal["legend_text"],
            labelTextSize="8pt",
            horSpacing=10,
            verSpacing=1,
        )
        self.legend.setParentItem(plot.getViewBox())
        self.legend.anchor((1, 0), (1, 0), offset=(-12, 12))
        self.legend.setZValue(60)
        self.legend.setVisible(False)
        self._legend_key: tuple | None = None

        # ---- 十字游标 ----
        self._vline = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen(pal["cursor"], width=1, style=Qt.PenStyle.DashLine),
        )
        self._hline = pg.InfiniteLine(
            angle=0,
            movable=False,
            pen=pg.mkPen(pal["cursor"], width=1, style=Qt.PenStyle.DashLine),
        )
        for line in (self._vline, self._hline):
            line.setZValue(40)
            line.setVisible(False)
            plot.addItem(line, ignoreBounds=True)

        self._readout = QLabel(self.viewport())
        self._readout.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._readout.setTextFormat(Qt.TextFormat.RichText)
        self._readout.setStyleSheet(self._readout_qss(pal))
        self._readout.hide()

        # ---- 数据 ----
        self.channel_count = 0
        self.channel_names = [f"I{i}" for i in range(MAX_CHANNELS)]
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
        self._drag_last: QPointF | None = None
        self._x: np.ndarray | None = None
        self._ys: list[np.ndarray | None] = [None] * MAX_CHANNELS
        self._filled = [False] * MAX_CHANNELS
        self._drawn = False
        self._y_range: tuple[float, float] | None = None
        self._last_mouse: QPointF | None = None

        plot.getViewBox().sigRangeChangedManually.connect(self._on_manual_range)

    # ---------- 主题 ----------
    @staticmethod
    def _readout_qss(pal: dict) -> str:
        return (
            "QLabel {"
            f" background: {pal['readout_bg']};"
            f" border: 1px solid {pal['readout_border']};"
            " border-radius: 8px;"
            " padding: 6px 10px;"
            f" color: {pal['readout_text']};"
            " font-family: Consolas, 'Microsoft YaHei UI';"
            " font-size: 12px;"
            "}"
        )

    def is_dark(self) -> bool:
        return self._dark

    def set_dark(self, dark: bool) -> None:
        """切换深浅配色：画布、坐标轴、网格、图例、游标与读数面板一起变。"""
        dark = bool(dark)
        if dark == self._dark:
            return
        self._dark = dark
        pal = PLOT_THEMES["dark" if dark else "light"]
        self._palette = pal
        self.setBackground(pal["bg"])

        plot = self.getPlotItem()
        plot.getViewBox().setBorder(pg.mkPen(pal["border"]))
        for axis_name in ("left", "bottom"):
            axis = plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(pal["border"]))
            axis.setTextPen(pg.mkPen(pal["tick"]))
            if hasattr(axis, "label"):
                axis.label.setDefaultTextColor(QColor(pal["tick"]))
        plot.showGrid(x=True, y=True, alpha=pal["grid_alpha"])

        self.legend.setBrush(pg.mkBrush(*pal["legend_brush"]))
        self.legend.setPen(pg.mkPen(pal["border"]))
        self.legend.setLabelTextColor(pal["legend_text"])
        self.watermark.setColor(pal["watermark"])
        self.hint.setColor(pal["hint"])
        cursor_pen = pg.mkPen(pal["cursor"], width=1, style=Qt.PenStyle.DashLine)
        self._vline.setPen(cursor_pen)
        self._hline.setPen(cursor_pen)
        self._readout.setStyleSheet(self._readout_qss(pal))
        self.update()

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
        self._x = None
        self._ys = [None] * MAX_CHANNELS
        self._y_range = None
        for curve in self.curves:
            curve.setData([], [])
        self._filled = [False] * MAX_CHANNELS
        self._drawn = False
        self._hide_cursor_readout()
        self._place_watermark()

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

    # ---------- 通道 ----------
    def set_visible(self, index: int, visible: bool) -> None:
        if 0 <= index < MAX_CHANNELS:
            self.visible[index] = bool(visible)
            self._legend_key = None

    def set_channel_count(self, count: int) -> None:
        count = max(0, min(int(count), MAX_CHANNELS))
        if count != self.channel_count:
            self.channel_count = count
            self._legend_key = None

    def set_channel_color(self, index: int, color: str) -> None:
        if 0 <= index < MAX_CHANNELS:
            self._colors[index] = color
            self.curves[index].setPen(pg.mkPen(color, width=1.6))
            self._legend_key = None

    def set_channel_name(self, index: int, name: str) -> None:
        if 0 <= index < MAX_CHANNELS and self.channel_names[index] != name:
            self.channel_names[index] = name
            self._legend_key = None

    def set_adjust_mode(self, enabled: bool) -> None:
        self.adjust_mode = enabled
        self._drag_last = None
        self.setCursor(Qt.SizeAllCursor if enabled else Qt.ArrowCursor)

    # ---------- Auto ----------
    def set_auto_scale(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.auto_scale:
            return
        self.auto_scale = enabled
        self._y_range = None
        if enabled:
            self.refresh()

    def _on_manual_range(self, *_args) -> None:
        """用户滚轮缩放 / 拖动后自动退出 Auto，把视图控制权交回用户。"""
        if self.auto_scale:
            self.auto_scale = False
            self._y_range = None
            self.autoScaleRequested.emit(False)

    # ---------- 绘制 ----------
    def refresh(self) -> None:
        n = len(self.times)
        if n == 0:
            if self._drawn:
                for curve in self.curves:
                    curve.setData([], [])
                self._filled = [False] * MAX_CHANNELS
                self._drawn = False
                self.legend.setVisible(False)
            self._x = None
            self._hide_cursor_readout()
            self._place_watermark()
            return

        shown = min(self.display_points, n)
        # deque 从右端反向迭代时只需走过窗口内的元素，缓冲区很大时比正向切片快得多
        times = np.fromiter(
            islice(reversed(self.times), 0, shown), dtype=float, count=shown
        )[::-1]
        x = times - times[0]
        self._x = x

        arrays: list[np.ndarray | None] = [None] * MAX_CHANNELS
        drawn = False
        for i, curve in enumerate(self.curves):
            buf = self.buffers[i]
            if (
                i < self.channel_count
                and self.visible[i]
                and len(buf) >= shown
                and shown > 0
            ):
                y = np.fromiter(
                    islice(reversed(buf), 0, shown), dtype=float, count=shown
                )[::-1]
                curve.setData(x, y)
                self._filled[i] = True
                arrays[i] = y
                drawn = True
            elif self._filled[i]:
                curve.setData([], [])
                self._filled[i] = False
        self._ys = arrays
        self._drawn = drawn

        if self.auto_scale:
            self._fit_view(x, [a for a in arrays if a is not None])

        self._rebuild_legend()
        self._place_watermark()

        # 数据滚动时让十字游标跟随鼠标所指位置重新取值
        if self._last_mouse is not None and self._readout.isVisible():
            self._update_cursor_readout(self._last_mouse)

    def _fit_view(self, x: np.ndarray, arrays: list[np.ndarray]) -> None:
        """Auto：X 跟随最新窗口，Y 贴合可见数据并留 8% 边距（带轻微平滑）。"""
        x0 = float(x[0])
        x1 = float(x[-1])
        if not math.isfinite(x0) or not math.isfinite(x1) or x1 - x0 <= 1e-9:
            x0, x1 = x0 - 1.0, x1 + 1.0
        self.setXRange(x0, x1, padding=0.0)

        if not arrays:
            return
        ymin = min(float(np.min(a)) for a in arrays)
        ymax = max(float(np.max(a)) for a in arrays)
        if not math.isfinite(ymin) or not math.isfinite(ymax):
            return
        if ymax - ymin <= 1e-9:
            pad = max(abs(ymax) * 0.1, 1.0)
            ymin, ymax = ymin - pad, ymax + pad
        pad = (ymax - ymin) * 0.08
        target = (ymin - pad, ymax + pad)

        if self._y_range is None:
            self._y_range = target
        else:
            lo = self._y_range[0] + (target[0] - self._y_range[0]) * Y_SMOOTH
            hi = self._y_range[1] + (target[1] - self._y_range[1]) * Y_SMOOTH
            self._y_range = (lo, hi)
        self.setYRange(self._y_range[0], self._y_range[1], padding=0.0)

    def _rebuild_legend(self) -> None:
        key = (
            self.channel_count,
            tuple(self.visible),
            tuple(self.channel_names[: self.channel_count]),
        )
        if key == self._legend_key:
            return
        self._legend_key = key
        self.legend.clear()
        for i in range(self.channel_count):
            if self.visible[i]:
                self.legend.addItem(self.curves[i], self.channel_names[i])
        self.legend.setVisible(self.channel_count > 0)

    def _place_watermark(self) -> None:
        vb = self.getPlotItem().getViewBox()
        center = vb.boundingRect().center()
        self.watermark.setPos(center)
        if hasattr(self, "hint"):
            self.hint.setPos(center.x(), center.y() + 44)
            self.hint.setVisible(not self.has_data)

    def time_span_ms(self) -> float:
        """可见窗口的时间跨度（只统计当前显示的点数）。"""
        n = len(self.times)
        if n < 2:
            return 0.0
        shown = min(self.display_points, n)
        return abs(self.times[-1] - self.times[n - shown])

    def total_points(self) -> int:
        return len(self.times)

    # ---------- 十字游标 ----------
    def _update_cursor_readout(self, pos: QPointF) -> None:
        x = self._x
        if x is None or len(x) == 0 or self.channel_count == 0:
            self._hide_cursor_readout()
            return
        plot = self.getPlotItem()
        vb = plot.getViewBox()
        scene_pos = self.mapToScene(pos.toPoint())
        if not vb.sceneBoundingRect().contains(scene_pos):
            self._hide_cursor_readout()
            return

        view_pt = vb.mapSceneToView(scene_pos)
        index = int(np.searchsorted(x, view_pt.x()))
        index = max(0, min(index, len(x) - 1))
        if index > 0 and abs(x[index - 1] - view_pt.x()) < abs(x[index] - view_pt.x()):
            index -= 1

        rows: list[str] = []
        for ch in range(self.channel_count):
            ys = self._ys[ch]
            if ys is None or index >= len(ys):
                continue
            value = float(ys[index])
            rows.append(
                "<tr>"
                f"<td style='color:{self._colors[ch]}'>\u25cf</td>"
                f"<td style='padding-left:5px'>{self.channel_names[ch]}</td>"
                "<td align='right' style='padding-left:14px'>"
                f"{value:.6g}</td>"
                "</tr>"
            )
        if not rows:
            self._hide_cursor_readout()
            return

        self._vline.setPos(float(x[index]))
        self._hline.setPos(view_pt.y())
        self._vline.setVisible(True)
        self._hline.setVisible(True)

        self._readout.setText(
            "<div style='color:#93A2B5'>t = "
            f"{float(x[index]):.1f} ms</div>"
            "<table cellspacing='0' cellpadding='1'>"
            + "".join(rows)
            + "</table>"
        )
        self._readout.adjustSize()
        width = self._readout.width()
        height = self._readout.height()
        px = pos.x() + 16
        if px + width > self.viewport().width() - 6:
            px = max(6.0, pos.x() - width - 16)
        py = pos.y() + 14
        if py + height > self.viewport().height() - 6:
            py = max(6.0, pos.y() - height - 14)
        self._readout.move(int(px), int(py))
        self._readout.show()

    def _hide_cursor_readout(self) -> None:
        if not hasattr(self, "_readout"):
            return
        self._readout.hide()
        self._vline.setVisible(False)
        self._hline.setVisible(False)

    # ---------- 事件 ----------
    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if not hasattr(self, "watermark"):
            return  # 基类 __init__ 期间就会触发一次 resizeEvent
        self._place_watermark()
        self._hide_cursor_readout()

    def mousePressEvent(self, ev) -> None:
        if self.adjust_mode and ev.button() == Qt.LeftButton:
            self._drag_last = ev.position()
            self._last_mouse = None
            self._hide_cursor_readout()
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
        self._last_mouse = ev.position()
        self._update_cursor_readout(self._last_mouse)

    def mouseReleaseEvent(self, ev) -> None:
        self._drag_last = None
        super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev) -> None:
        self._last_mouse = None
        self._hide_cursor_readout()
        super().leaveEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._y_range = None
            self.auto_scale = True
            self.autoScaleRequested.emit(True)
            self.refresh()
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def contextMenuEvent(self, ev) -> None:
        self._hide_cursor_readout()
        self.contextMenuRequested.emit(ev.globalPos())
        ev.accept()
