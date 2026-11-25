"""游标测量面板：阶跃响应与稳态性能计算。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .common import hbox, make_label, vbox

CURSOR_A_COLOR = "#F5A524"
CURSOR_B_COLOR = "#7B61FF"

if TYPE_CHECKING:
    from ..plot_widget import PlotPage


def _fmt(value: float, unit: str = "") -> str:
    if value == 0:
        return f"0{unit}"
    magnitude = abs(value)
    if magnitude >= 1000 or magnitude < 0.001:
        return f"{value:.3e}{unit}"
    return f"{value:.3f}{unit}"


def _cross_time(times: np.ndarray, norm: np.ndarray, level: float) -> float | None:
    index = np.nonzero(norm >= level)[0]
    if index.size == 0:
        return None
    i = int(index[0])
    if i == 0:
        return float(times[0])
    y0, y1 = float(norm[i - 1]), float(norm[i])
    if y1 <= y0:
        return float(times[i])
    ratio = (level - y0) / (y1 - y0)
    return float(times[i - 1] + ratio * (times[i] - times[i - 1]))


def _step_metrics(
    times: np.ndarray,
    values: np.ndarray,
    band_pct: float,
    target: float,
    initial: float | None = None,
) -> dict:
    n = max(3, min(30, len(values) // 100))
    y0 = float(initial) if initial is not None else float(np.mean(values[:n]))
    y_final = float(np.mean(values[-n:]))
    delta = y_final - y0
    direction = 1.0 if delta >= 0 else -1.0
    norm = direction * (values - y0)
    final_norm = direction * delta

    if final_norm > max(1e-9, abs(delta) * 1e-6):
        peak_index = int(np.argmax(norm))
        overshoot_abs = max(0.0, float(norm[peak_index] - final_norm))
        overshoot_pct = overshoot_abs / abs(delta) * 100.0
        t10 = _cross_time(times, norm, 0.1 * final_norm)
        t90 = _cross_time(times, norm, 0.9 * final_norm)
        rise_time = max(0.0, t90 - t10) if t10 is not None and t90 is not None else 0.0
    else:
        peak_index = int(np.argmax(np.abs(values - y0)))
        overshoot_abs = 0.0
        overshoot_pct = 0.0
        rise_time = 0.0

    band = abs(delta) * band_pct / 100.0
    outside = np.nonzero(np.abs(values - y_final) > band)[0]
    settle_time = (
        float(times[min(int(outside[-1]) + 1, len(times) - 1)] - times[0])
        if outside.size
        else 0.0
    )

    return {
        "initial": y0,
        "final": y_final,
        "delta": delta,
        "peak": float(values[peak_index]),
        "overshoot_pct": overshoot_pct,
        "overshoot_abs": overshoot_abs,
        "peak_time": float(times[peak_index] - times[0]),
        "rise_time": rise_time,
        "settle_time": settle_time,
        "target": target,
        "error": target - y_final,
        "max_dev": float(np.max(np.abs(values - target))),
        "rms": float(np.sqrt(np.mean((values - target) ** 2))),
    }


class _MetricCard(QFrame):
    def __init__(self, title: str, dark: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(4)
        self.title = QLabel(title)
        self.title.setObjectName("metricTitle")
        self.value = QLabel("--")
        self.value.setObjectName("metricValue")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        bg = "#2A3A4D" if dark else "#FFFFFF"
        border = "#3A4D63" if dark else "#E2E8F0"
        text_color = "#E2E8F0" if dark else "#334155"
        title_color = "#94A3B8" if dark else "#64748B"
        self.setStyleSheet(
            "#metricCard {"
            f" border: 1px solid {border};"
            " border-radius: 10px;"
            f" background: {bg};"
            "}"
            f"#metricTitle {{ color:{title_color}; font-size:11px; }}"
            f"#metricValue {{ color:{text_color}; font-size:21px; font-weight:700;"
            " font-family:Consolas; }"
        )

    def set_value(self, text: str) -> None:
        self.value.setText(text)


class MeasureDialog(QDialog):
    """暂停游标的专用测量窗口，多通道统一计算控制性能指标。"""

    def __init__(self, page: "PlotPage", dark: bool = False, parent=None):
        super().__init__(parent)
        self.dark = dark
        self.page: PlotPage | None = None
        self.data: dict | None = None
        self.names: list[str] = []
        self._values_edited = False
        self._ready = False
        self._signal_bound = False

        self.setWindowTitle("游标测量 · 自动控制性能")
        self.setMinimumSize(880, 460)
        self.setModal(False)
        self._build()
        self._ready = True
        self.set_page(page)
        self.refresh()

    def _build(self) -> None:
        root = vbox((18, 16, 18, 16), 12)
        header = QFrame()
        header.setObjectName("measureHeader")
        header_bg = "#26364A" if self.dark else "#F1F5F9"
        border_color = "#3A4D63" if self.dark else "#E2E8F0"
        title_color = "#E2E8F0" if self.dark else "#334155"
        sub_color = "#94A3B8" if self.dark else "#64748B"
        header.setStyleSheet(
            f"#measureHeader {{ border:1px solid {border_color};"
            f" border-radius:10px; background:{header_bg}; }}"
        )
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(18, 14, 18, 14)
        title = QLabel("游标测量")
        title.setStyleSheet(f"color:{title_color};font-size:20px;font-weight:800;")
        sub = QLabel("暂停后点击波形设 A（开始）、B（结束），也可直接拖动游标")
        sub.setStyleSheet(f"color:{sub_color};font-size:12px;")
        self.range_label = QLabel("游标范围：--")
        self.range_label.setStyleSheet(f"color:{sub_color};font-size:11px;")
        self.range_label.setTextFormat(Qt.TextFormat.RichText)
        text = QVBoxLayout()
        text.addWidget(title)
        text.addWidget(sub)
        text.addWidget(self.range_label)
        hlay.addLayout(text)
        hlay.addStretch(1)
        root.addWidget(header)

        controls = hbox(spacing=10)
        controls.addWidget(make_label("通道", "tinyMuted"))
        self.channel_combo = QComboBox()
        self.channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        controls.addWidget(self.channel_combo, 1)

        controls.addWidget(make_label("调节带", "tinyMuted"))
        self.band_combo = QComboBox()
        self.band_combo.addItems(["±2%", "±5%"])
        self.band_combo.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.band_combo)

        initial_label = make_label("初始值", "tinyMuted")
        initial_label.setStyleSheet(
            f"color:{CURSOR_A_COLOR};font-size:11px;font-weight:700;"
        )
        controls.addWidget(initial_label)
        self.initial_spin = QDoubleSpinBox()
        self.initial_spin.setRange(-1e6, 1e6)
        self.initial_spin.setDecimals(4)
        self.initial_spin.setToolTip("开始游标 A 对应的值（阶跃前），可手动填写")
        self.initial_spin.valueChanged.connect(self._on_value_edited)
        controls.addWidget(self.initial_spin)

        target_label = make_label("设定值", "tinyMuted")
        target_label.setStyleSheet(
            f"color:{CURSOR_B_COLOR};font-size:11px;font-weight:700;"
        )
        controls.addWidget(target_label)
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(-1e6, 1e6)
        self.target_spin.setDecimals(4)
        self.target_spin.setToolTip("结束游标 B 对应的值（期望稳态值），可手动填写")
        self.target_spin.valueChanged.connect(self._on_value_edited)
        controls.addWidget(self.target_spin)

        refresh_btn = QPushButton("重新计算")
        refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(refresh_btn)
        root.addLayout(controls)

        cards = hbox(spacing=12)
        self.card_overshoot = _MetricCard("超调量 % / 绝对值", self.dark)
        self.card_settle = _MetricCard("调节时间", self.dark)
        self.card_error = _MetricCard("稳态误差", self.dark)
        for card in (self.card_overshoot, self.card_settle, self.card_error):
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            cards.addWidget(card, 1)
        root.addLayout(cards)

        self.tabs = QTabWidget()
        self.step_table = self._make_table(
            ["通道", "初始值", "设定值", "超调%", "超调值", "峰值时间", "上升时间", "调节时间"]
        )
        self.steady_table = self._make_table(
            ["通道", "初始值", "设定值", "稳态误差", "最大偏差", "RMS 误差"]
        )
        self.tabs.addTab(self.step_table, "阶跃响应")
        self.tabs.addTab(self.steady_table, "稳态计算")
        self.tabs.setMinimumHeight(300)
        root.addWidget(self.tabs, 1)

        buttons = hbox(spacing=8)
        buttons.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(96)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)
        self.setLayout(root)

    def _make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header_bg = "#2A3A4D" if self.dark else "#F1F5F9"
        header_fg = "#E2E8F0" if self.dark else "#334155"
        border_color = "#3A4D63" if self.dark else "#E2E8F0"
        table.setStyleSheet(
            f"QTableWidget {{ border:1px solid {border_color}; border-radius:10px;"
            " gridline-color:rgba(120,150,190,30); }"
            f"QHeaderView::section {{ background:{header_bg}; color:{header_fg};"
            " padding:6px; border:none; font-weight:700; }"
        )
        return table

    # ---------- 页面 / 游标联动 ----------
    def set_page(self, page: "PlotPage") -> None:
        self._unbind_page()
        self.page = page
        self._bind_data()

    def _bind_data(self) -> None:
        if self.page is None:
            return
        if self._signal_bound:
            try:
                self.page.diffMeasured.disconnect(self._on_diff_measured)
            except (RuntimeError, TypeError):
                pass
            self._signal_bound = False
        self.data = self.page.measurement_data()
        self.names = [
            self.page.channel_names[i] for i in range(self.page.channel_count)
        ]
        self._values_edited = False
        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        self.channel_combo.addItems(self.names)
        self.channel_combo.blockSignals(False)
        if self.data:
            start, end = float(self.data["a"]), float(self.data["b"])
            self.range_label.setText(
                f'<span style="color:{CURSOR_A_COLOR};">● 开始 A {start:.1f} ms</span>'
                f'　→　<span style="color:{CURSOR_B_COLOR};">● 结束 B {end:.1f} ms</span>'
                f'　·　跨度 {end - start:.1f} ms'
            )
        else:
            self.range_label.setText(
                '<span style="color:#64748B;">暂停后点击波形设 A / B 游标</span>'
            )
        try:
            self.page.diffMeasured.connect(self._on_diff_measured)
            self._signal_bound = True
        except (RuntimeError, TypeError):
            pass

    def _unbind_page(self) -> None:
        if self._signal_bound:
            try:
                self.page.diffMeasured.disconnect(self._on_diff_measured)
            except (RuntimeError, TypeError):
                pass
            self._signal_bound = False
        self.page = None

    def _on_diff_measured(self, _info: dict) -> None:
        if not self._ready or not self.isVisible():
            return
        self._bind_data()
        self.refresh()

    def closeEvent(self, event) -> None:
        self._unbind_page()
        super().closeEvent(event)

    # ---------- 计算 / 绘制 ----------
    def _on_value_edited(self, _value: float = 0.0) -> None:
        self._values_edited = True
        self.refresh()

    def _on_channel_changed(self, _index: int) -> None:
        self._values_edited = False
        self.refresh()

    def refresh(self) -> None:
        if not self._ready:
            return
        self.initial_spin.blockSignals(True)
        self.target_spin.blockSignals(True)
        if self.data and self.names and not self._values_edited:
            name = self.names[max(0, self.channel_combo.currentIndex())]
            values = self.data["values"][name]
            n = max(3, min(30, len(values) // 100))
            self.initial_spin.setValue(float(np.mean(values[:n])))
            self.target_spin.setValue(float(np.mean(values[-n:])))
        self.initial_spin.blockSignals(False)
        self.target_spin.blockSignals(False)

        self.step_table.setRowCount(0)
        self.steady_table.setRowCount(0)
        if not self.data:
            for table in (self.step_table, self.steady_table):
                table.setRowCount(1)
                table.setItem(0, 0, QTableWidgetItem("暂停后拖动 A / B 游标即可测量"))
            self.card_overshoot.set_value("--")
            self.card_settle.set_value("--")
            self.card_error.set_value("--")
            return

        band = 5.0 if self.band_combo.currentIndex() == 1 else 2.0
        target = float(self.target_spin.value())
        initial = float(self.initial_spin.value())
        all_metrics = [
            self._metrics_for_name(name, band, target, initial) for name in self.names
        ]

        for row, (name, metric) in enumerate(zip(self.names, all_metrics)):
            self._append_row(
                self.step_table,
                row,
                [
                    name,
                    _fmt(metric["initial"]),
                    _fmt(metric["target"]),
                    f"{metric['overshoot_pct']:.2f}%",
                    _fmt(metric["overshoot_abs"]),
                    _fmt(metric["peak_time"], " ms"),
                    _fmt(metric["rise_time"], " ms"),
                    _fmt(metric["settle_time"], " ms"),
                ],
            )
            self._append_row(
                self.steady_table,
                row,
                [
                    name,
                    _fmt(metric["initial"]),
                    _fmt(metric["target"]),
                    _fmt(metric["error"]),
                    _fmt(metric["max_dev"]),
                    _fmt(metric["rms"]),
                ],
            )

        selected = all_metrics[max(0, self.channel_combo.currentIndex())]
        self.card_overshoot.set_value(
            f"{selected['overshoot_pct']:.1f}%  /  {_fmt(selected['overshoot_abs'])}"
        )
        self.card_settle.set_value(_fmt(selected["settle_time"], " ms"))
        self.card_error.set_value(_fmt(selected["error"]))

    def _metrics_for_index(
        self,
        index: int,
        band: float | None = None,
        target: float | None = None,
        initial: float | None = None,
    ) -> dict | None:
        if not self.data or index >= len(self.names):
            return None
        return self._metrics_for_name(
            self.names[index],
            band if band is not None else (5.0 if self.band_combo.currentIndex() == 1 else 2.0),
            target if target is not None else float(self.target_spin.value()),
            initial if initial is not None else float(self.initial_spin.value()),
        )

    def _metrics_for_name(
        self, name: str, band: float, target: float, initial: float | None = None
    ) -> dict:
        return _step_metrics(
            self.data["times"], self.data["values"][name], band, target, initial
        )

    @staticmethod
    def _append_row(table: QTableWidget, row: int, values: list[str]) -> None:
        table.insertRow(row)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, column, item)
        table.setRowHeight(row, 34)

