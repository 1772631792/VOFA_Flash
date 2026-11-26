"""基于 pyqtgraph 的波形页：外观与交互参考 VOFA+ / 示波器。

设计要点：
- 纯白画布 + 极浅网格 + 细描边 + Consolas 刻度，摆脱 pyqtgraph 默认的灰黑配色。
- 右上角半透明图例，随通道名称 / 颜色 / 可见性实时刷新。
- 暂停后鼠标移入显示十字游标和数值读数面板（含相对时间），运行中保持画布干净。
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


def _font(family: str, size: int, bold: bool = False) -> QFont:
    font = QFont(family)
    if size > 0:
        font.setPointSize(size)
    font.setBold(bold)
    return font


MAX_CHANNELS = 8
Y_SMOOTH = 0.45

FFT_WINDOWS = {
    "hann": "Hann（通用）",
    "hamming": "Hamming",
    "blackman": "Blackman",
    "flattop": "Flat Top（幅值优先）",
    "rectangular": "矩形窗（整周期）",
}
FFT_SCALES = {
    "percent": "相对基波 (%)",
    "amplitude": "幅值",
    "dbc": "相对基波 (dBc)",
}
DEFAULT_FFT_SETTINGS = {
    "window": "hann",
    "fft_size": 0,
    "remove_dc": True,
    "scale": "percent",
    "db_floor": -100.0,
    "fundamental_min_hz": 0.5,
}


def _fft_window(name: str, n: int) -> np.ndarray:
    k = np.arange(n, dtype=float)
    phase = 2.0 * np.pi * k / n
    if name == "rectangular":
        return np.ones(n)
    if name == "hamming":
        return 0.54 - 0.46 * np.cos(phase)
    if name == "blackman":
        return 0.42 - 0.5 * np.cos(phase) + 0.08 * np.cos(2.0 * phase)
    if name == "flattop":
        return (
            0.21557895
            - 0.41663158 * np.cos(phase)
            + 0.27726316 * np.cos(2.0 * phase)
            - 0.083578947 * np.cos(3.0 * phase)
            + 0.006947368 * np.cos(4.0 * phase)
        )
    return 0.5 - 0.5 * np.cos(phase)


def _analyze_spectrum(times_ms: np.ndarray, samples: np.ndarray, settings: dict) -> dict | None:
    """参考 McuStdio：去均值 + 周期窗 + 单边谱 + 相干增益校正。"""
    n = min(int(settings.get("fft_size") or 4096), len(samples))
    while n > 8 and n & (n - 1):
        n -= 1
    if n < 8 or len(times_ms) < n:
        return None

    t = np.asarray(times_ms[-n:], dtype=float)
    y = np.asarray(samples[-n:], dtype=float)
    duration = (float(t[-1]) - float(t[0])) / 1000.0
    if duration <= 0 or not math.isfinite(duration):
        return None
    sample_rate = (n - 1) / duration

    uniform_t = np.linspace(float(t[0]), float(t[-1]), n)
    y = np.interp(uniform_t, t, y)
    if settings.get("remove_dc", True):
        y = y - float(np.mean(y))

    window = _fft_window(str(settings.get("window", "hann")), n)
    coherent = abs(float(np.sum(window))) or 1.0
    spectrum = np.fft.rfft(y * window)
    amplitudes = 2.0 * np.abs(spectrum) / coherent
    amplitudes[0] *= 0.5
    if n % 2 == 0 and amplitudes.size > 1:
        amplitudes[-1] *= 0.5
    frequencies = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    resolution = sample_rate / n

    min_hz = float(settings.get("fundamental_min_hz", 0.5))
    min_idx = max(1, int(min_hz / max(resolution, 1e-9)))
    min_idx = min(min_idx, amplitudes.size - 1)
    fundamental_idx = min_idx + int(np.argmax(amplitudes[min_idx:]))
    reference = max(float(amplitudes[fundamental_idx]), 1e-12)

    scale = str(settings.get("scale", "percent"))
    if scale == "amplitude":
        values = amplitudes
    elif scale == "dbc":
        floor = float(settings.get("db_floor", -100.0))
        values = np.maximum(
            20.0 * np.log10(np.maximum(amplitudes / reference, 1e-300)), floor
        )
    else:
        values = amplitudes / reference * 100.0

    return {
        "frequencies": frequencies,
        "values": values,
        "sample_rate": sample_rate,
        "resolution": resolution,
        "nyquist": sample_rate * 0.5,
        "fundamental_hz": float(frequencies[fundamental_idx]),
        "fft_size": n,
    }


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
        "diff_a": (245, 165, 36, 230),
        "diff_b": (123, 97, 255, 230),
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
        "diff_a": (255, 183, 77, 230),
        "diff_b": (167, 139, 250, 230),
        "readout_bg": "rgba(37, 37, 38, 246)",
        "readout_border": "#3C3C3C",
        "readout_text": "#D4D4D4",
    },
}

pg.setConfigOptions(antialias=True)


class PlotPage(pg.PlotWidget):
    """单个波形标签页：曲线、图例、暂停读数、通道可见性。"""

    contextMenuRequested = Signal(object)
    autoScaleRequested = Signal(bool)
    activated = Signal(object)
    diffMeasured = Signal(object)

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
        plot.setContentsMargins(12, 6, 14, 4)
        plot.getViewBox().setBorder(pg.mkPen(pal["border"]))
        plot.getViewBox().setMouseEnabled(x=True, y=True)
        plot.getViewBox().setDefaultPadding(0.01)

        for axis_name in ("left", "bottom"):
            axis = plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(pal["border"]))
            axis.setTextPen(pg.mkPen(pal["tick"]))
            tick_font = QFont("Consolas")
            tick_font.setPointSize(9)
            axis.setTickFont(tick_font)
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
        self.watermark.setFont(_font("Segoe UI", 44, True))
        self.watermark.setZValue(-20)
        # 直接挂到 ViewBox 上：这样坐标是像素坐标，可以稳定居中且不随数据平移
        self.watermark.setParentItem(plot.getViewBox())

        self.hint = pg.TextItem("等待数据…", anchor=(0.5, 0.5), color=pal["hint"])
        self.hint.setFont(_font("Microsoft YaHei UI", 12))
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

        self.fft_summary = pg.TextItem("", anchor=(0, 0), color=pal["legend_text"])
        self.fft_summary.setFont(_font("Consolas", 9))
        self.fft_summary.setParentItem(plot.getViewBox())
        self.fft_summary.setZValue(55)
        self.fft_summary.hide()

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

        # ---- 测量游标 A / B：暂停后显示，可直接拖动 ----
        self._syncing_diff_lines = False
        self._diff_a_line = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=pg.mkPen(pal["diff_a"], width=2.4),
            label="A",
            labelOpts={"position": 0.03},
        )
        self._diff_b_line = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=pg.mkPen(pal["diff_b"], width=2.4, style=Qt.PenStyle.DashLine),
            label="B",
            labelOpts={"position": 0.03},
        )
        for index, line in enumerate((self._diff_a_line, self._diff_b_line)):
            line.setZValue(41)
            line.setVisible(False)
            line.sigPositionChanged.connect(
                lambda _line, idx=index: self._on_diff_line_dragged(idx, _line)
            )
            plot.addItem(line, ignoreBounds=True)
        self.diff_mode = False
        self._diff_times: list[float | None] = [None, None]
        self._x_base_ms = 0.0

        self._readout = QLabel(self.viewport())
        self._readout.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._readout.setTextFormat(Qt.TextFormat.RichText)
        self._readout.setStyleSheet(self._readout_qss(pal))
        self._readout.hide()

        # 暂停提示不画在画布内：由主窗口统一放在波形卡片外（统计栏），避免遮挡曲线

        # ---- 数据 ----
        self.channel_count = 0
        self.channel_names = [f"I{i}" for i in range(MAX_CHANNELS)]
        self.visible = [True] * MAX_CHANNELS
        self.buffers: list[deque[float]] = [
            deque(maxlen=50000) for _ in range(MAX_CHANNELS)
        ]
        self.times: deque[float] = deque(maxlen=50000)
        self.buffer_limit = 50000
        self.unlimited = False
        self.display_points = 1200
        self.dt_ms = 1.0
        self.sample_index = 0
        self.has_data = False
        self.auto_scale = True
        self.inspect_mode = False
        self._next_cursor = 0
        self.plot_mode = "time"
        self.fft_settings = dict(DEFAULT_FFT_SETTINGS)
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
        self.fft_summary.setColor(QColor(pal["legend_text"]))
        cursor_pen = pg.mkPen(pal["cursor"], width=1, style=Qt.PenStyle.DashLine)
        self._vline.setPen(cursor_pen)
        self._hline.setPen(cursor_pen)
        self._diff_a_line.setPen(pg.mkPen(pal["diff_a"], width=1.5))
        self._diff_b_line.setPen(
            pg.mkPen(pal["diff_b"], width=1.5, style=Qt.PenStyle.DashLine)
        )
        self._readout.setStyleSheet(self._readout_qss(pal))
        self.update()

    # ---------- 数据 ----------
    def append_sample(self, values: list[float], t_ms: float | None = None) -> None:
        """追加一帧；t_ms 用于 CSV 回放保留原始时间，实时数据仍按索引推导。"""
        if t_ms is None:
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
        self._diff_times = [None, None]
        self._hide_diff_lines()
        self.diffMeasured.emit({"active": self.diff_mode, "a": None, "b": None})
        self.fft_summary.hide()
        self._place_watermark()

    def set_dt(self, dt_ms: float) -> None:
        self.dt_ms = max(0.001, float(dt_ms))

    def set_buffer_limit(self, limit: int) -> None:
        """limit <= 0 表示不限长度（连续记录模式）。"""
        limit = int(limit)
        maxlen = None if limit <= 0 else max(1000, limit)
        self.buffer_limit = limit
        self.unlimited = limit <= 0
        self.times = deque(self.times, maxlen=maxlen)
        for i in range(MAX_CHANNELS):
            self.buffers[i] = deque(self.buffers[i], maxlen=maxlen)

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

    def set_inspect_mode(self, enabled: bool) -> None:
        """暂停即进入测量模式：显示两条可拖动游标；运行时彻底隐藏。"""
        enabled = bool(enabled)
        if self.inspect_mode == enabled:
            return
        self.inspect_mode = enabled
        if enabled:
            self._readout.raise_()
            self.diff_mode = True
            if self._diff_times[0] is None or self._diff_times[1] is None:
                first, last = self._visible_time_bounds()
                self._diff_times = [first, last]
            self.refresh()
        else:
            self.set_diff_mode(False)

    def set_inspect_range(self, start_ms: float, end_ms: float) -> None:
        """直接指定 A / B 游标范围（模拟阶跃模式自动对准最近一次阶跃）。"""
        if not self.inspect_mode:
            return
        self._diff_times = [float(start_ms), float(end_ms)]
        self._update_diff_readout()

    # ---------- 时域 / FFT ----------
    def _fft_y_label(self) -> str:
        return FFT_SCALES.get(str(self.fft_settings.get("scale", "percent")), "相对基波 (%)")

    def set_plot_mode(self, mode: str) -> None:
        mode = "fft" if mode == "fft" else "time"
        if mode == self.plot_mode:
            return
        self.plot_mode = mode
        self._y_range = None
        self._x = None
        self._ys = [None] * MAX_CHANNELS
        self._hide_cursor_readout()
        plot = self.getPlotItem()
        plot.setLabel("bottom", "频率 / Hz" if mode == "fft" else "时间 / ms")
        plot.setLabel("left", self._fft_y_label() if mode == "fft" else "")
        for axis_name in ("left", "bottom"):
            axis = plot.getAxis(axis_name)
            if hasattr(axis, "label"):
                axis.label.setDefaultTextColor(QColor(self._palette["tick"]))
        self.fft_summary.setVisible(mode == "fft")
        self.refresh()

    def set_fft_window(self, window: str) -> None:
        if window not in FFT_WINDOWS:
            return
        self.fft_settings["window"] = window
        if self.plot_mode == "fft":
            self.refresh()

    def set_fft_scale(self, scale: str) -> None:
        if scale not in FFT_SCALES:
            return
        self.fft_settings["scale"] = scale
        self._y_range = None
        if self.plot_mode == "fft":
            self.getPlotItem().setLabel("left", self._fft_y_label())
            self.refresh()

    def set_fft_size(self, size: int) -> None:
        self.fft_settings["fft_size"] = max(0, int(size))
        if self.plot_mode == "fft":
            self.refresh()

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
            self._hide_diff_lines()
            self.fft_summary.hide()
            self._place_watermark()
            return

        if self.unlimited and n > self.display_points:
            # 连续记录：画完整历史，点数过多时等间隔抽样保证流畅
            max_points = max(20000, self.display_points * 4)
            stride = max(1, n // max_points)
            all_times = np.fromiter(self.times, dtype=float, count=n)
            times = all_times[::stride]
            if times[-1] != all_times[-1]:
                times = np.append(times, all_times[-1])
        else:
            shown = min(self.display_points, n)
            times = np.fromiter(
                islice(reversed(self.times), 0, shown), dtype=float, count=shown
            )[::-1]
        x = times - times[0]
        self._x_base_ms = float(times[0])

        arrays: list[np.ndarray | None] = [None] * MAX_CHANNELS
        for i in range(MAX_CHANNELS):
            buf = self.buffers[i]
            if i < self.channel_count and self.visible[i] and len(buf) >= n:
                if self.unlimited and n > self.display_points:
                    all_values = np.fromiter(buf, dtype=float, count=n)
                    values = all_values[::stride]
                    if len(values) < len(times):
                        values = np.append(values, all_values[-1])
                    arrays[i] = values
                else:
                    shown = min(self.display_points, n)
                    arrays[i] = np.fromiter(
                        islice(reversed(buf), 0, shown), dtype=float, count=shown
                    )[::-1]
                self._filled[i] = True
            else:
                self._filled[i] = False

        if self.plot_mode == "fft":
            self._draw_fft(times, arrays)
            self._hide_diff_lines()
        else:
            drawn = False
            for i, y in enumerate(arrays):
                if y is None:
                    self.curves[i].setData([], [])
                    continue
                self.curves[i].setData(x, y)
                drawn = True
            self._x = x
            self._ys = arrays
            self._drawn = drawn
            self.fft_summary.hide()
            if self.auto_scale:
                self._fit_view(x, [a for a in arrays if a is not None])
            if self.diff_mode:
                self._update_diff_readout()

        self._rebuild_legend()
        self._place_watermark()

        # 数据刷新时同步更新鼠标所指位置的读数
        if self._last_mouse is not None and self._readout.isVisible():
            self._update_cursor_readout(self._last_mouse)

    def _draw_fft(self, times: np.ndarray, arrays: list[np.ndarray | None]) -> None:
        results: list[tuple[np.ndarray, np.ndarray, dict, float]] = []
        limit = float(self.fft_settings.get("display_max_hz", 0.0) or 0.0)
        for i, samples in enumerate(arrays):
            if samples is None:
                self.curves[i].setData([], [])
                arrays[i] = None
                continue
            result = _analyze_spectrum(times, samples, self.fft_settings)
            if result is None:
                self.curves[i].setData([], [])
                arrays[i] = None
                continue
            max_hz = limit or float(result["nyquist"])
            freqs = result["frequencies"]
            values = result["values"]
            visible = freqs <= max_hz
            fx, fy = freqs[visible], values[visible]
            self.curves[i].setData(fx, fy)
            arrays[i] = fy
            results.append((fx, fy, result, max_hz))

        self._ys = arrays
        if not results:
            self._x = None
            self._drawn = False
            self.fft_summary.hide()
            return

        self._x = results[0][0]
        self._drawn = True
        max_hz = max(item[3] for item in results)
        scale = str(self.fft_settings.get("scale", "percent"))
        if self.auto_scale:
            self.setXRange(0.0, max(max_hz, 1.0), padding=0.0)
            if scale == "dbc":
                self.setYRange(float(self.fft_settings.get("db_floor", -100.0)), 5.0, padding=0.0)
            else:
                finite = [float(np.max(item[1])) for item in results if item[1].size]
                top = max(finite) if finite else 1.0
                self.setYRange(0.0, max(top * 1.08, 1.0), padding=0.0)

        first = results[0][2]
        self.fft_summary.setText(
            f"FFT · {FFT_WINDOWS.get(str(self.fft_settings.get('window', 'hann')), 'Hann')} · "
            f"N={first['fft_size']} · Fs={first['sample_rate']:.0f}Hz · "
            f"Δf={first['resolution']:.2f}Hz · f0={first['fundamental_hz']:.2f}Hz"
        )
        self.fft_summary.setPos(10, 8)
        self.fft_summary.show()

    def _fit_view(self, x: np.ndarray, arrays: list[np.ndarray]) -> None:
        """Auto：X 跟随最近一个显示窗口，Y 贴合可见数据并留 8% 边距。

        连续记录模式仍保留/绘制完整历史，但视图只跟随最近 display_points
        个采样点对应的时间窗（类似 VOFA+ 的滚动跟随），不会把全部历史塞进视野。
        """
        if self.unlimited and x.size > self.display_points:
            x0 = float(x[-self.display_points])
        else:
            x0 = float(x[0])
        x1 = float(x[-1])
        if not math.isfinite(x0) or not math.isfinite(x1) or x1 - x0 <= 1e-9:
            x0, x1 = x0 - 1.0, x1 + 1.0
        self.setXRange(x0, x1, padding=0.0)

        if not arrays:
            return
        # Y 也只按可见窗口计算，避免很早以前的大范围把当前曲线压扁
        arrs = [a[-self.display_points:] for a in arrays]
        ymin = min(float(np.min(a)) for a in arrs)
        ymax = max(float(np.max(a)) for a in arrs)
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

        axis_name = "f" if self.plot_mode == "fft" else "t"
        unit = "Hz" if self.plot_mode == "fft" else "ms"
        digits = ".2f" if self.plot_mode == "fft" else ".1f"
        self._readout.setText(
            f"<div style='color:#93A2B5'>{axis_name} = "
            f"{float(x[index]):{digits}} {unit}</div>"
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

    # ---------- 测量游标 ----------
    def set_diff_mode(self, enabled: bool) -> None:
        self.diff_mode = bool(enabled)
        if self.diff_mode:
            self._hide_cursor_readout()
            if self._diff_times[0] is None or self._diff_times[1] is None:
                first, last = self._visible_time_bounds()
                self._diff_times = [first, last]
            self._update_diff_readout()
        else:
            self._diff_times = [None, None]
            self._hide_diff_lines()
            self.diffMeasured.emit({"active": False, "a": None, "b": None})
        self.update()

    def _hide_diff_lines(self) -> None:
        if not hasattr(self, "_diff_a_line"):
            return
        self._syncing_diff_lines = True
        try:
            self._diff_a_line.setVisible(False)
            self._diff_b_line.setVisible(False)
        finally:
            self._syncing_diff_lines = False

    def _visible_time_bounds(self) -> tuple[float | None, float | None]:
        if not self.times:
            return None, None
        # 连续记录虽存完整历史，但游标/测量只对可见窗口操作
        shown = min(self.display_points, len(self.times))
        values = list(self.times)[-shown:]
        if len(values) < 3:
            return float(values[0]), float(values[-1])
        margin = max(1, len(values) // 12)
        return float(values[margin]), float(values[-margin - 1])

    def _on_diff_line_dragged(self, index: int, line) -> None:
        if self._syncing_diff_lines or not self.diff_mode or self.plot_mode != "time":
            return
        self._diff_times[index] = float(line.value()) + self._x_base_ms
        self._update_diff_readout()

    def _index_for_time(self, abs_ms: float) -> int | None:
        x = self._x
        if x is None or len(x) == 0:
            return None
        target = float(abs_ms) - self._x_base_ms
        index = int(np.searchsorted(x, target))
        index = max(0, min(index, len(x) - 1))
        if index > 0 and abs(x[index - 1] - target) < abs(x[index] - target):
            index -= 1
        return index

    def measurement_data(self) -> dict | None:
        """供测量面板使用：返回 A/B 之间的原始时间与各通道数据。"""
        if self.plot_mode != "time" or not self.times:
            return None
        if self._diff_times[0] is None or self._diff_times[1] is None:
            return None
        times = np.asarray(list(self.times), dtype=float)
        start, end = sorted((float(self._diff_times[0]), float(self._diff_times[1])))
        indices = np.nonzero((times >= start) & (times <= end))[0]
        if indices.size < 2:
            return None
        values: dict[str, np.ndarray] = {}
        for ch in range(self.channel_count):
            values[self.channel_names[ch]] = np.asarray(self.buffers[ch], dtype=float)[indices]
        return {
            "times": times[indices],
            "values": values,
            "a": start,
            "b": end,
        }

    def _update_diff_readout(self) -> None:
        info: dict = {
            "active": self.diff_mode,
            "a": self._diff_times[0],
            "b": self._diff_times[1],
            "dt_ms": 0.0,
            "names": [],
            "dvalues": [],
        }
        if not self.diff_mode or self.plot_mode != "time" or self._x is None:
            self._hide_diff_lines()
            self.diffMeasured.emit(info)
            return

        i0 = self._index_for_time(self._diff_times[0]) if self._diff_times[0] is not None else None
        i1 = self._index_for_time(self._diff_times[1]) if self._diff_times[1] is not None else None
        self._syncing_diff_lines = True
        try:
            if i0 is not None:
                self._diff_a_line.setPos(float(self._x[i0]))
                self._diff_a_line.setVisible(True)
                info["a"] = float(self._x[i0]) + self._x_base_ms
            else:
                self._diff_a_line.setVisible(False)
                info["a"] = None
            if i1 is not None:
                self._diff_b_line.setPos(float(self._x[i1]))
                self._diff_b_line.setVisible(True)
                info["b"] = float(self._x[i1]) + self._x_base_ms
            else:
                self._diff_b_line.setVisible(False)
                info["b"] = None
        finally:
            self._syncing_diff_lines = False

        if i0 is not None and i1 is not None:
            info["dt_ms"] = float(self._x[i1]) - float(self._x[i0])
            for ch in range(self.channel_count):
                ys = self._ys[ch]
                if ys is None or i0 >= len(ys) or i1 >= len(ys):
                    continue
                info["names"].append(self.channel_names[ch])
                info["dvalues"].append(float(ys[i1]) - float(ys[i0]))
        self.diffMeasured.emit(info)

    # ---------- 事件 ----------
    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if not hasattr(self, "watermark"):
            return  # 基类 __init__ 期间就会触发一次 resizeEvent
        self._place_watermark()
        self._hide_cursor_readout()

    def _near_diff_line(self, ev) -> bool:
        if self._x is None or not self.diff_mode:
            return False
        vb = self.getPlotItem().getViewBox()
        click_scene = self.mapToScene(ev.position().toPoint())
        for line in (self._diff_a_line, self._diff_b_line):
            if not line.isVisible():
                continue
            line_scene = vb.mapViewToScene(QPointF(float(line.value()), 0.0))
            if abs(line_scene.x() - click_scene.x()) <= 10:
                return True
        return False

    def mousePressEvent(self, ev) -> None:
        self.activated.emit(self)
        if (
            ev.button() == Qt.LeftButton
            and self.diff_mode
            and self.plot_mode == "time"
            and not self._near_diff_line(ev)
        ):
            try:
                vb = self.getPlotItem().getViewBox()
                scene_pos = self.mapToScene(ev.position().toPoint())
                view_pos = vb.mapSceneToView(scene_pos)
                abs_ms = float(view_pos.x()) + self._x_base_ms
                self._diff_times[self._next_cursor] = abs_ms
                self._next_cursor = 1 - self._next_cursor
                self._update_diff_readout()
            except (AttributeError, TypeError, ValueError):
                pass
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        super().mouseMoveEvent(ev)
        pos = ev.position()
        self._last_mouse = pos
        if self.diff_mode:
            # 测量模式下由统计栏按钮和测量面板统一展示，不在画布上叠字
            return
        self._update_cursor_readout(pos)

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
