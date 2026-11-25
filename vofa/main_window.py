"""VOFA+ Flash 主窗口：状态编排、数据流与业务入口。"""

from __future__ import annotations

import csv
import json
import math
import re
import struct
import sys
import time
from typing import TYPE_CHECKING

import serial.tools.list_ports
from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QPoint,
    QPointF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__ as VERSION
from .command_panel import CommandDialog, CommandItem, parse_frame_bytes
from .icons import app_icon, icon
from .plot_widget import FFT_SCALES, FFT_WINDOWS, MAX_CHANNELS, PlotPage
from .protocol import JustFloatParser
from .serial_worker import SerialWorker
from .theme import CHANNEL_COLORS, GROUP_COLORS, app_style
from .transport import (
    BaseTransport,
    TcpClientTransport,
    TcpServerTransport,
    UdpTransport,
)
from .ui.common import (
    ICON_NEUTRAL,
    SHORTCUT_DEFAULTS,
    SHORTCUT_LABELS,
    ChannelRow,
    LogTextEdit,
    _NumberCombo,
    hbox,
    make_hr,
    make_label,
    make_vline,
    vbox,
)
from .ui.dialogs import SettingsDialog, VariableDialog
from .ui.display import DisplayWidgetsPanel
from .ui.measure import MeasureDialog

if TYPE_CHECKING:
    from .splash import SplashScreen

ENGINES = ["JustFloat", "RawData"]
INTERFACES = ["串口", "UDP", "TCP客户端", "TCP服务端", "模拟模式"]

SETTINGS_ORG = "VOFAFlash"
SETTINGS_APP = "VOFAFlash"
DEMO_CHANNELS = 3  # 模拟模式的通道数：JustFloat 本身不限通道，不占用顶栏


def load_dark_setting() -> bool:
    """读取上次选择的外观；没有记录时默认浅色。"""
    return bool(QSettings(SETTINGS_ORG, SETTINGS_APP).value("appearance/dark", False, type=bool))


def save_dark_setting(dark: bool) -> None:
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("appearance/dark", bool(dark))


def load_setting(key: str, default, value_type=None):
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    if value_type is None:
        return settings.value(key, default)
    return settings.value(key, default, type=value_type)


def save_setting(key: str, value) -> None:
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(key, value)


def apply_dark_titlebar(window: QWidget, dark: bool) -> bool:
    """Windows 10/11：把系统标题栏切成深色 / 浅色，其它平台直接忽略。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = wintypes.HWND(int(window.winId()))
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # 20: Win10 1903+，19: 更早的版本
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break
        else:
            return False
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0, 0x0027  # FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER
        )
        return True
    except Exception:
        return False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"VOFA+ Flash {VERSION}")
        self._app_icon = app_icon()
        self.setWindowIcon(self._app_icon)
        self.resize(1480, 900)
        self.setMinimumSize(1280, 760)

        # ---- 运行时状态 ----
        self.dark = load_dark_setting()
        self.engine_name = "JustFloat"
        self.interface_name = "串口"
        self.worker: SerialWorker | BaseTransport | None = None
        self.connected = False
        self.demo_enabled = False
        self.sim_mode = str(load_setting("demo/mode", "sine", str))
        if self.sim_mode not in ("sine", "step", "pid"):
            self.sim_mode = "sine"
        self.measure_dialog: MeasureDialog | None = None
        self._demo_step_period_ms = 4000.0
        self._demo_last_step_ms = 0.0
        self.record_unlimited = False
        self.channel_names = [f"I{i}" for i in range(MAX_CHANNELS)]
        self.channel_colors = list(CHANNEL_COLORS)
        self.channel_decimals = [3] * MAX_CHANNELS
        self.total_frames = 0
        self.total_tx = 0
        self.sample_index = 0
        self.dt_ms = 1.0
        self.channel_count = 0
        self.last_values = [0.0] * MAX_CHANNELS
        self.gains = [1.0] * MAX_CHANNELS
        self.offsets = [0.0] * MAX_CHANNELS
        self.selected_channel = 0
        self.plot_paused = False
        self.plot_layout_mode = 1
        self.active_page: PlotPage | None = None
        self.page_mode_locked = [False, False, False]
        self.rx_hex_mode = True
        self.hex_mode = True
        self.filter_rx = False
        self.filter_tx = False
        self.stamp_log = False
        self.log_lines: list[tuple[str, str]] = []
        self.justfloat = JustFloatParser()
        self.rx_line_buffer = bytearray()
        self.raw_frame_bytes = bytearray()
        self._last_value_log = 0.0
        self._last_demo_value_log = 0.0
        self._last_raw_log = 0.0
        self._last_rx_hex_log = 0.0
        self._log_font_size = 16
        self._demo_acc = 0.0
        self.encoding = "utf-8"
        self.serial_bits = 8
        self.serial_parity = "None"
        self.serial_stopbits = 1
        self.serial_flow = "None"
        self.auto_reconnect = bool(load_setting("serial/auto_reconnect", True, bool))
        self._last_serial_port = str(load_setting("serial/last_port", "", str))
        self._last_serial_baud = str(load_setting("serial/last_baud", "115200", str))
        self._manual_disconnect = False
        self._reconnect_armed = False
        self._auto_connecting = False
        self.shortcuts = self._load_shortcuts()
        self.bytes_total = 0
        self._rate_bytes = 0
        self._rate_frames = 0
        self._rate_start = time.monotonic()
        self._data_collapsed = False
        self._right_width = 250
        self._group_colors: dict[str, str] = {}

        self.build_ui()
        self._sync_record_limit()
        self._sync_tx_mode_ui()
        self._sync_rx_mode_ui()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.apply_theme(self.dark, remember=False)
        self.refresh_ports()
        self._restore_serial_selection()
        self.iface_combo.setCurrentIndex(INTERFACES.index("模拟模式"))
        self.on_iface_changed("模拟模式")
        self._select_channel(0)
        self._update_channel_rows()

        self.statusBar().showMessage(
            "就绪 · 点击「连接」运行数据；空格暂停/继续波形，暂停后移动鼠标查看数值"
        )

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(30)

        self.port_timer = QTimer(self)
        self.port_timer.timeout.connect(lambda: self.refresh_ports(silent=True))
        self.port_timer.start(3000)

        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setSingleShot(True)
        self.reconnect_timer.timeout.connect(self._auto_reconnect_attempt)

    # ================= UI =================
    def build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        root_l = vbox(spacing=0)
        root.setLayout(root_l)
        self.setCentralWidget(root)

        root_l.addWidget(self.build_topbar())

        center_right = QSplitter(Qt.Horizontal)
        center_right.setChildrenCollapsible(False)
        center_right.setHandleWidth(4)
        center_area = self.build_center_area()
        rightbar = self.build_rightbar()
        # 中间区域保留最小可视空间，其余宽度让给两侧面板自由拖动
        center_area.setMinimumWidth(320)
        center_area.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        rightbar.setMinimumWidth(140)
        rightbar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        center_right.addWidget(center_area)
        center_right.addWidget(rightbar)
        center_right.setSizes([1100, 250])
        center_right.setStretchFactor(0, 1)
        center_right.setStretchFactor(1, 0)
        self.center_splitter = center_right

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(4)
        body.addWidget(self.build_rail())
        self.display_panel = self.build_display_panel()
        body.addWidget(self.display_panel)
        self.display_panel.hide()
        self.drawer = self.build_command_drawer()
        body.addWidget(self.drawer)
        body.addWidget(center_right)
        body.setSizes([48, 0, 280, 1152])
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 0)
        body.setStretchFactor(2, 0)
        body.setStretchFactor(3, 1)
        body.splitterMoved.connect(self._remember_panel_widths)
        self.body_splitter = body

        root_l.addWidget(body, 1)

        for btn in self.findChildren(QToolButton):
            if btn.objectName() != "railBtn":
                btn.setIconSize(QSize(18, 18))

        # 所有可点控件统一用手型光标，鼠标移上去就能感知到"这里能点"
        for widget in self.findChildren(QPushButton) + self.findChildren(QToolButton):
            if widget.isEnabled():
                widget.setCursor(Qt.PointingHandCursor)

    @staticmethod
    def _field(text: str, widget: QWidget) -> QHBoxLayout:
        """顶栏字段：小号灰标签 + 控件，基线对齐。"""
        row = hbox(spacing=8)
        row.addWidget(make_label(text, "muted"))
        row.addWidget(widget)
        return row

    def build_topbar(self) -> QWidget:
        top = QFrame()
        top.setObjectName("topbar")
        top.setFixedHeight(64)
        lay = hbox((14, 0, 10, 0), 10)

        # ---- 品牌 + 设置 ----
        brand_row = hbox(spacing=8)
        brand_row.addWidget(make_label("VOFA+ Flash", "brand"))
        version = make_label(VERSION, "versionPill")
        version.setFixedHeight(20)
        brand_row.addWidget(version, 0, Qt.AlignmentFlag.AlignVCenter)
        self.settings_btn = QToolButton()
        self.settings_btn.setObjectName("iconBtn")
        self.settings_btn.setIcon(icon("wrench", 18, ICON_NEUTRAL))
        self.settings_btn.setIconSize(QSize(18, 18))
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setToolTip("设置：外观（浅色 / 深色）与语言")
        self.settings_btn.clicked.connect(self.open_settings)
        brand_row.addWidget(self.settings_btn)
        lay.addLayout(brand_row)

        lay.addWidget(make_vline())

        # ---- 数据引擎 / 接口 ----
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(ENGINES)
        self.engine_combo.setFixedWidth(108)
        self.engine_combo.currentTextChanged.connect(self.on_engine_changed)
        lay.addLayout(self._field("引擎", self.engine_combo))

        self.iface_combo = QComboBox()
        self.iface_combo.addItems(INTERFACES)
        self.iface_combo.setFixedWidth(102)
        self.iface_combo.currentTextChanged.connect(self.on_iface_changed)
        lay.addLayout(self._field("接口", self.iface_combo))

        lay.addWidget(make_vline())

        # ---- 串口参数 ----
        serial_page = QWidget()
        sp = hbox(spacing=12)
        self.port_combo = QComboBox()
        self.port_combo.setFixedWidth(96)
        self.port_combo.setToolTip("串口列表每 3 秒自动刷新，插拔设备无需手动操作")
        sp.addLayout(self._field("端口", self.port_combo))
        self.baud_combo = _NumberCombo(
            ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"],
            "115200",
        )
        self.baud_combo.setFixedWidth(88)
        self.baud_combo.setToolTip("波特率：可从下拉选择，也可双击直接输入")
        sp.addLayout(self._field("波特率", self.baud_combo))

        self.serial_fmt_btn = QToolButton()
        self.serial_fmt_btn.setObjectName("flatTool")
        self.serial_fmt_btn.setText("8N1")
        self.serial_fmt_btn.setToolTip("数据位 / 校验位 / 停止位 / 流控")
        self.serial_fmt_btn.setPopupMode(QToolButton.InstantPopup)
        self.serial_fmt_menu = QMenu(self.serial_fmt_btn)
        self.serial_fmt_btn.setMenu(self.serial_fmt_menu)
        self._build_serial_fmt_menu()
        sp.addWidget(self.serial_fmt_btn)

        serial_page.setLayout(sp)

        # ---- 网络参数 ----
        net_page = QWidget()
        np_lay = hbox(spacing=12)
        self.net_host_edit = QLineEdit("127.0.0.1")
        self.net_host_edit.setPlaceholderText("0.0.0.0")
        self.net_host_edit.setFixedWidth(124)
        np_lay.addLayout(self._field("地址", self.net_host_edit))
        self.net_port_spin = QSpinBox()
        self.net_port_spin.setRange(1, 65535)
        self.net_port_spin.setValue(8886)
        self.net_port_spin.setFixedWidth(84)
        self.net_port_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        np_lay.addLayout(self._field("端口", self.net_port_spin))
        net_page.setLayout(np_lay)

        # ---- 模拟数据：采样率（预设可选，也可双击手输，单位 Hz 放在框外） ----
        demo_page = QWidget()
        dp = hbox(spacing=6)
        self.demo_rate_combo = _NumberCombo(
            ["100", "200", "500", "1000", "2000"], "500"
        )
        self.demo_rate_combo.setFixedWidth(70)
        self.demo_rate_combo.setToolTip("模拟数据采样率：下拉选择，或双击直接输入")
        dp.addWidget(make_label("采样率", "muted"))
        dp.addWidget(self.demo_rate_combo)
        dp.addWidget(make_label("Hz", "muted"))
        demo_page.setLayout(dp)

        self.param_stack = QStackedWidget()
        self.param_stack.addWidget(serial_page)
        self.param_stack.addWidget(net_page)
        self.param_stack.addWidget(demo_page)
        lay.addWidget(self.param_stack)

        self.link_btn = QPushButton("连接")
        self.link_btn.setObjectName("primary")
        self.link_btn.setFixedWidth(82)
        self.link_btn.setFixedHeight(34)
        self.link_btn.setToolTip("连接 / 断开；模拟模式下控制模拟数据流。空格只暂停波形")
        self.link_btn.clicked.connect(self.toggle_link)
        lay.addWidget(self.link_btn)

        lay.addStretch(1)

        self.view2_btn = QToolButton()
        self.view2_btn.setText("二")
        self.view2_btn.setObjectName("viewBtn")
        self.view2_btn.setProperty("viewSegment", "first")
        self.view2_btn.setCheckable(True)
        self.view2_btn.setFixedSize(32, 30)
        self.view2_btn.setToolTip("二窗口显示；再次点击恢复单窗口")
        self.view2_btn.clicked.connect(
            lambda: self.set_plot_layout(2 if self.plot_layout_mode != 2 else 1)
        )
        lay.addWidget(self.view2_btn)

        self.view3_btn = QToolButton()
        self.view3_btn.setText("三")
        self.view3_btn.setObjectName("viewBtn")
        self.view3_btn.setProperty("viewSegment", "last")
        self.view3_btn.setCheckable(True)
        self.view3_btn.setFixedSize(32, 30)
        self.view3_btn.setToolTip("三窗口显示；再次点击恢复单窗口")
        self.view3_btn.clicked.connect(
            lambda: self.set_plot_layout(3 if self.plot_layout_mode != 3 else 1)
        )
        lay.addWidget(self.view3_btn)
        lay.addSpacing(4)

        self.mode_tag = QPushButton("● 模拟模式")
        self.mode_tag.setObjectName("primary")
        self.mode_tag.setMinimumWidth(104)
        self.mode_tag.setFixedHeight(34)
        self.mode_tag.setToolTip("点击开始 / 暂停模拟数据流")
        self.mode_tag.clicked.connect(self.toggle_demo)
        lay.addWidget(self.mode_tag)

        # 截图 / 清空在波形卡片的统计栏里有图标入口，这里不再重复放，避免顶栏过挤

        top.setLayout(lay)
        return top

    # ================= 设置 / 主题 =================
    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.themeChanged.connect(self.apply_theme)
        dialog.shortcutsChanged.connect(self.apply_shortcuts)
        dialog.simModeChanged.connect(self.apply_sim_mode)
        dialog.recordModeChanged.connect(self.apply_record_mode)
        dialog.exec()

    @staticmethod
    def _load_shortcuts() -> dict[str, QKeySequence]:
        result: dict[str, QKeySequence] = {}
        for key, default in SHORTCUT_DEFAULTS.items():
            text = str(load_setting(f"shortcuts/{key}", default, str))
            sequence = QKeySequence(text)
            result[key] = sequence if not sequence.isEmpty() else QKeySequence(default)
        return result

    def apply_shortcuts(self, mapping: dict[str, str]) -> None:
        for key, text in mapping.items():
            sequence = QKeySequence(text)
            if sequence.isEmpty() or key not in SHORTCUT_DEFAULTS:
                continue
            self.shortcuts[key] = sequence
            save_setting(f"shortcuts/{key}", text)
        self.statusBar().showMessage("快捷键已更新", 2500)

    def apply_theme(self, dark: bool, remember: bool = True) -> None:
        """浅色 / 深色切换：全局样式表、波形页与状态栏提示一起更新。"""
        dark = bool(dark)
        changed = dark != getattr(self, "dark", None)
        self.dark = dark
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(app_style(dark))
        for page in getattr(self, "pages", []):
            page.set_dark(dark)
        if hasattr(self, "display_panel"):
            self.display_panel.set_dark(dark)
        apply_dark_titlebar(self, dark)
        if remember:
            save_dark_setting(dark)
        if changed and hasattr(self, "statusBar"):
            self.statusBar().showMessage(
                "已切换到深色模式" if dark else "已切换到浅色模式", 1500
            )

    def build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(48)
        lay = vbox((5, 8, 5, 8), 8)

        self.btn_cmd = QPushButton()
        self.btn_cmd.setObjectName("railBtn")
        self.btn_cmd.setIcon(icon("docs", 24, "#2D7EF1"))
        self.btn_cmd.setIconSize(QSize(24, 24))
        self.btn_cmd.setCheckable(True)
        self.btn_cmd.setChecked(True)
        self.btn_cmd.setToolTip("命令面板")
        self.btn_cmd.clicked.connect(self.toggle_command_drawer)
        lay.addWidget(self.btn_cmd, 0, Qt.AlignHCenter)

        self.btn_widgets = QPushButton()
        self.btn_widgets.setObjectName("railBtn")
        self.btn_widgets.setIcon(icon("cube", 24, "#2D7EF1"))
        self.btn_widgets.setIconSize(QSize(24, 24))
        self.btn_widgets.setCheckable(True)
        self.btn_widgets.setChecked(False)
        self.btn_widgets.setToolTip("显示控件")
        self.btn_widgets.clicked.connect(self.toggle_display_panel)
        lay.addWidget(self.btn_widgets, 0, Qt.AlignHCenter)

        lay.addStretch(1)

        rail.setLayout(lay)
        return rail

    def build_display_panel(self) -> QWidget:
        panel = DisplayWidgetsPanel()
        panel.set_provider(self._display_data)
        return panel

    def _display_data(self):
        return self.channel_count, self.channel_names, self.last_values

    def build_command_drawer(self) -> QWidget:
        drawer = QFrame()
        drawer.setObjectName("drawer")
        drawer.setMinimumWidth(200)

        main = vbox((14, 12, 14, 12), 10)
        head = hbox(spacing=8)
        head.addWidget(make_label("命令", "titleBlue"))
        head.addStretch(1)
        add_btn = QToolButton()
        add_btn.setObjectName("addCmd")
        add_btn.setIcon(icon("plus", 18, ICON_NEUTRAL))
        add_btn.setFixedSize(30, 30)
        add_btn.setIconSize(QSize(18, 18))
        add_btn.setToolTip("新增固定命令 / 滑动条 / 滑块组")
        add_btn.setPopupMode(QToolButton.InstantPopup)
        add_btn.setMenu(self._build_add_menu(add_btn))
        head.addWidget(add_btn)
        main.addLayout(head)
        main.addWidget(make_hr())

        self.cmd_scroll = QScrollArea()
        self.cmd_scroll.setWidgetResizable(True)
        self.cmd_scroll.setFrameShape(QFrame.NoFrame)
        self.cmd_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cmd_scroll.viewport().setAutoFillBackground(False)
        self.cmd_inner = QWidget()
        self.cmd_layout = vbox((0, 0, 0, 0), 10)
        self.cmd_empty = make_label(
            "暂无命令\n点击右上角 + 新增固定命令或滑动条", "emptyHint"
        )
        self.cmd_empty.setAlignment(Qt.AlignCenter)
        self.cmd_empty.setWordWrap(True)
        self.cmd_empty.setContentsMargins(0, 18, 0, 0)
        self.cmd_layout.addWidget(self.cmd_empty)
        self.cmd_layout.addStretch(1)
        self.cmd_inner.setLayout(self.cmd_layout)
        self.cmd_inner.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cmd_inner.customContextMenuRequested.connect(
            lambda pos: self.show_add_command_menu(self.cmd_inner.mapToGlobal(pos))
        )
        self.cmd_scroll.setWidget(self.cmd_inner)
        main.addWidget(self.cmd_scroll, 1)

        drawer.setLayout(main)
        return drawer

    def build_center_area(self) -> QWidget:
        center = QWidget()
        outer = vbox((10, 10, 10, 10), 10)
        center.setLayout(outer)

        self.plot_card = QFrame()
        self.plot_card.setObjectName("plotCard")
        self.plot_card.setMinimumHeight(240)
        plot_l = vbox((8, 8, 8, 8), 0)

        self.plot_splitter = QSplitter(Qt.Orientation.Vertical)
        self.plot_splitter.setChildrenCollapsible(False)
        self.plot_splitter.setHandleWidth(4)
        self.plot_splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        plot_l.addWidget(self.plot_splitter, 1)

        self.pages: list[PlotPage] = []

        # 信息栏
        self.info_bar = QWidget()
        info_l = hbox((10, 12, 10, 8), 8)
        self.dt_spin = QDoubleSpinBox()
        self.dt_spin.setRange(0.01, 10000)
        self.dt_spin.setDecimals(2)
        self.dt_spin.setValue(1.0)
        self.dt_spin.setFixedWidth(78)
        self.dt_spin.valueChanged.connect(self.on_dt_changed)

        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(1000, 500000)
        self.buffer_spin.setSingleStep(1000)
        self.buffer_spin.setValue(50000)
        self.buffer_spin.setFixedWidth(88)
        self.buffer_spin.valueChanged.connect(self.on_buffer_changed)

        self.align_spin = QSpinBox()
        self.align_spin.setRange(100, 10000)
        self.align_spin.setValue(1200)
        self.align_spin.setFixedWidth(80)
        self.align_spin.valueChanged.connect(self.on_align_changed)
        for spin in (self.dt_spin, self.buffer_spin, self.align_spin):
            spin.setButtonSymbols(QAbstractSpinBox.NoButtons)

        info_l.addWidget(make_label("Δt:", "sectionBlue"))
        info_l.addWidget(self.dt_spin)
        info_l.addWidget(make_label("ms"))
        info_l.addSpacing(10)
        info_l.addWidget(make_label("缓冲:", "sectionBlue"))
        info_l.addWidget(self.buffer_spin)
        info_l.addWidget(make_label("/ch"))
        info_l.addSpacing(10)
        info_l.addWidget(make_label("点数:", "sectionBlue"))
        info_l.addWidget(self.align_spin)
        info_l.addStretch(1)

        self.auto_label = QPushButton("Auto")
        self.auto_label.setObjectName("autoBtn")
        self.auto_label.setFixedSize(84, 32)
        self.auto_label.setCheckable(True)
        self.auto_label.setChecked(True)
        self.auto_label.setToolTip(
            "Auto：自动适配 X/Y 轴范围（滚轮缩放或拖动会自动关闭，双击波形恢复）"
        )
        self.auto_label.toggled.connect(self.toggle_auto_scale)
        info_l.addWidget(self.auto_label)
        self.info_bar.setLayout(info_l)
        plot_l.addWidget(self.info_bar)

        # 统计栏
        self.stat_bar = QWidget()
        stat_l = hbox((10, 2, 10, 6), 14)
        del_btn = QToolButton()
        del_btn.setObjectName("flatTool")
        del_btn.setIcon(icon("trash", 18, ICON_NEUTRAL))
        del_btn.setToolTip("清空波形")
        del_btn.clicked.connect(self.clear_plot)
        stat_l.addWidget(del_btn)

        stat_l.addWidget(make_label("RX", "sectionBlue"))
        self.rx_count_label = make_label("0", "statValue")
        stat_l.addWidget(self.rx_count_label)
        stat_l.addWidget(make_label("/ TX", "muted"))
        self.tx_count_label = make_label("0", "statTx")
        stat_l.addWidget(self.tx_count_label)
        stat_l.addWidget(make_vline(14))

        stat_l.addWidget(make_label("索引", "muted"))
        self.cur_index_label = QLabel("0")
        self.cur_index_label.setStyleSheet(
            "color:#11B6BF;font-family:Consolas;font-size:13px;font-weight:700;"
        )
        stat_l.addWidget(self.cur_index_label)
        stat_l.addWidget(make_vline(14))

        self.scale_label = QLabel("0ms/格")
        self.scale_label.setMinimumWidth(82)
        self.scale_label.setStyleSheet(
            "color:#3F86EA;font-family:Consolas;font-size:13px;font-weight:700;"
        )
        stat_l.addWidget(self.scale_label)

        self.rate_label = QLabel("0 KB/s")
        self.rate_label.setStyleSheet(
            "color:#7E8FA6;font-family:Consolas;font-size:12px;"
        )
        self.rate_label.setToolTip("接收吞吐与帧率")
        stat_l.addWidget(self.rate_label)
        stat_l.addStretch(1)

        self.measure_btn = QToolButton()
        self.measure_btn.setObjectName("flatTool")
        self.measure_btn.setIcon(icon("measure", 18, ICON_NEUTRAL))
        self.measure_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.measure_btn.setCursor(Qt.PointingHandCursor)
        self.measure_btn.setToolTip(
            "游标测量：暂停后点击波形设 A（开始）/ B（结束），可拖动微调；点击这里计算性能指标"
        )
        self.measure_btn.clicked.connect(self.open_measure_dialog)
        stat_l.addWidget(self.measure_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.record_btn = QToolButton()
        self.record_btn.setObjectName("flatTool")
        self.record_btn.setIcon(icon("record", 18, ICON_NEUTRAL))
        self.record_btn.setCheckable(True)
        self.record_btn.setChecked(self.record_unlimited)
        self.record_btn.setToolTip("连续记录模式：不限缓冲长度一直记录，关闭软件自动清除")
        self.record_btn.toggled.connect(self.apply_record_mode)
        stat_l.addWidget(self.record_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.replay_btn = QToolButton()
        self.replay_btn.setObjectName("flatTool")
        self.replay_btn.setIcon(icon("rewind", 18, ICON_NEUTRAL))
        self.replay_btn.setToolTip("导入 CSV 回放曲线")
        self.replay_btn.clicked.connect(self.import_csv_replay)
        stat_l.addWidget(self.replay_btn)

        self.csv_btn = QToolButton()
        self.csv_btn.setObjectName("flatTool")
        self.csv_btn.setIcon(icon("docs", 18, ICON_NEUTRAL))
        self.csv_btn.setToolTip("导出曲线数据（CSV）")
        self.csv_btn.clicked.connect(self.export_csv)
        stat_l.addWidget(self.csv_btn)

        self.img_btn = QToolButton()
        self.img_btn.setObjectName("flatTool")
        self.img_btn.setIcon(icon("layers", 18, ICON_NEUTRAL))
        self.img_btn.setToolTip("导出曲线图片（PNG）")
        self.img_btn.clicked.connect(self.save_screenshot)
        stat_l.addWidget(self.img_btn)

        self.stat_bar.setLayout(stat_l)
        plot_l.addWidget(self.stat_bar)

        # Auto 按钮就绪后再建波形页，保证页面的 Auto 状态与之同步
        for _ in range(3):
            self._create_page()
        self.set_plot_layout(1, message=False)

        self.plot_card.setLayout(plot_l)

        v_split = QSplitter(Qt.Vertical)
        v_split.setChildrenCollapsible(False)
        v_split.setHandleWidth(4)
        v_split.addWidget(self.plot_card)
        self.bottom_card = self.build_bottom_card()
        v_split.addWidget(self.bottom_card)
        v_split.setSizes([620, 200])
        v_split.setStretchFactor(0, 1)
        v_split.setStretchFactor(1, 0)
        self.center_vsplit = v_split
        outer.addWidget(v_split, 1)
        return center

    def build_bottom_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("bottomCard")
        card.setMinimumHeight(170)
        lay = vbox((10, 8, 10, 8), 8)

        tools = hbox(spacing=8)
        self.rx_mode_btn = QPushButton("Hex")
        self.rx_mode_btn.setObjectName("rxModeBtn")
        self.rx_mode_btn.setCheckable(True)
        self.rx_mode_btn.setChecked(True)
        self.rx_mode_btn.setFixedHeight(28)
        self.rx_mode_btn.setMinimumWidth(54)
        self.rx_mode_btn.setToolTip("切换接收日志显示：Hex / Abc")
        self.rx_mode_btn.toggled.connect(self.on_rx_mode_toggled)
        tools.addWidget(self.rx_mode_btn)

        clear_log_btn = QToolButton()
        clear_log_btn.setObjectName("flatTool")
        clear_log_btn.setIcon(icon("trash", 20, ICON_NEUTRAL))
        clear_log_btn.setIconSize(QSize(20, 20))
        clear_log_btn.setToolTip("清空接收日志")
        clear_log_btn.clicked.connect(self.clear_log)
        tools.addWidget(clear_log_btn)

        self.btn_rx = QPushButton("Rx")
        self.btn_rx.setObjectName("flatTool")
        self.btn_rx.setCheckable(True)
        self.btn_rx.setToolTip("只看接收")
        self.btn_rx.toggled.connect(self.on_filter_rx)
        tools.addWidget(self.btn_rx)

        self.btn_tx = QPushButton("Tx")
        self.btn_tx.setObjectName("flatTool")
        self.btn_tx.setCheckable(True)
        self.btn_tx.setToolTip("只看发送")
        self.btn_tx.toggled.connect(self.on_filter_tx)
        tools.addWidget(self.btn_tx)

        self.btn_stamp = QPushButton("T:")
        self.btn_stamp.setObjectName("flatTool")
        self.btn_stamp.setCheckable(True)
        self.btn_stamp.setToolTip("日志加时间戳")
        self.btn_stamp.toggled.connect(self.on_toggle_stamp)
        tools.addWidget(self.btn_stamp)

        font_up = QPushButton("+")
        font_up.setObjectName("flatTool")
        font_up.setToolTip("放大日志字体")
        font_up.clicked.connect(lambda: self.bump_log_font(1))
        tools.addWidget(font_up)
        font_down = QPushButton("−")
        font_down.setObjectName("flatTool")
        font_down.setToolTip("缩小日志字体")
        font_down.clicked.connect(lambda: self.bump_log_font(-1))
        tools.addWidget(font_down)

        # 这几个文字按钮偏窄时会被 QSS 的内边距吃掉，留出余量，高 DPI 下也不会裁字
        for btn, min_width in (
            (self.btn_rx, 44),
            (self.btn_tx, 44),
            (self.btn_stamp, 44),
            (font_up, 34),
            (font_down, 34),
        ):
            btn.setMinimumWidth(min_width)

        self.encoding_btn = QToolButton()
        self.encoding_btn.setObjectName("flatTool")
        self.encoding_btn.setText("⌁ UTF-8")
        self.encoding_btn.setMinimumWidth(108)
        self.encoding_btn.setToolTip("发送文本使用的编码")
        self.encoding_btn.setPopupMode(QToolButton.InstantPopup)
        enc_menu = QMenu(self.encoding_btn)
        for label, codec in (("UTF-8", "utf-8"), ("GBK", "gbk"), ("ASCII", "ascii")):
            act = enc_menu.addAction(label)
            act.triggered.connect(
                lambda _=False, lbl=label, c=codec: self.set_encoding(lbl, c)
            )
        self.encoding_btn.setMenu(enc_menu)
        tools.addWidget(self.encoding_btn)
        tools.addStretch(1)

        save_log_btn = QToolButton()
        save_log_btn.setObjectName("flatTool")
        save_log_btn.setIcon(icon("docs", 20, ICON_NEUTRAL))
        save_log_btn.setIconSize(QSize(20, 20))
        save_log_btn.setToolTip("保存接收日志")
        save_log_btn.clicked.connect(self.save_log)
        tools.addWidget(save_log_btn)

        focus_btn = QToolButton()
        focus_btn.setObjectName("flatTool")
        focus_btn.setIcon(icon("settings", 20, ICON_NEUTRAL))
        focus_btn.setIconSize(QSize(20, 20))
        focus_btn.setToolTip("聚焦发送框")
        focus_btn.clicked.connect(lambda: self.tx_edit.setFocus())
        tools.addWidget(focus_btn)
        lay.addLayout(tools)

        self.rx_text = LogTextEdit()
        self.rx_text.setReadOnly(True)
        self.rx_text.setPlaceholderText("这里显示接收日志 / 解析结果 / RawData 十六进制数据……")
        self.rx_text.setMinimumHeight(118)
        self.rx_text.setMaximumBlockCount(4000)
        self.rx_text.setToolTip("Ctrl + 滚轮调整日志字号")
        self.rx_text.fontZoomRequested.connect(self.bump_log_font)
        self._apply_log_font()
        lay.addWidget(self.rx_text, 1)

        tx_line = hbox(spacing=8)
        self.tx_mode_btn = QPushButton("Hex")
        self.tx_mode_btn.setObjectName("hexMode")
        self.tx_mode_btn.setCheckable(True)
        self.tx_mode_btn.setChecked(True)
        self.tx_mode_btn.setToolTip("Hex / 文本发送切换")
        self.tx_mode_btn.toggled.connect(self.on_tx_mode_toggled)
        tx_line.addWidget(self.tx_mode_btn)
        tx_line.addWidget(make_label("➜"))

        self.tx_edit = QLineEdit("01 03 00 00 00 01 84 0A")
        self.tx_edit.setPlaceholderText("输入要发送的数据，回车发送")
        self.tx_edit.returnPressed.connect(self.send_from_edit)
        tx_line.addWidget(self.tx_edit, 1)

        self.ending_combo = QComboBox()
        self.ending_combo.addItems(["无追加", "追加换行", "追加回车换行"])
        self.ending_combo.setFixedWidth(126)
        tx_line.addWidget(self.ending_combo)

        send_btn = QPushButton("发送(S)")
        send_btn.setObjectName("primary")
        send_btn.clicked.connect(self.send_from_edit)
        tx_line.addWidget(send_btn)
        lay.addLayout(tx_line)

        card.setLayout(lay)
        return card

    def build_rightbar(self) -> QWidget:
        right = QFrame()
        right.setObjectName("rightbar")
        right.setMinimumWidth(190)
        right.setMaximumWidth(400)
        outer = vbox((0, 0, 0, 0), 0)

        self.right_body = QWidget()
        lay = vbox((14, 10, 14, 10), 8)

        head = hbox(spacing=8)
        head.addWidget(make_label("◔", "muted"))
        head.addWidget(make_label("数据", "titleBlue"))
        head.addStretch(1)

        self.right_collapse = QToolButton()
        self.right_collapse.setObjectName("panelBtn")
        self.right_collapse.setIcon(icon("curve", 18, "#2D7EF1"))
        self.right_collapse.setIconSize(QSize(18, 18))
        self.right_collapse.setToolTip("收起数据栏")
        self.right_collapse.clicked.connect(lambda: self.set_data_panel_collapsed(True))
        head.addWidget(self.right_collapse)
        lay.addLayout(head)
        lay.addWidget(make_hr())

        self.channel_rows_by_page: list[list[ChannelRow]] = []
        self.page_groups: list[QFrame] = []
        self.page_group_titles: list[QLabel] = []
        for page_index in range(3):
            group = QFrame()
            group.setObjectName("windowVarGroup")
            group.setStyleSheet(
                "#windowVarGroup {"
                " border: 1px solid rgba(120,150,190,48);"
                " border-radius: 8px;"
                " background: rgba(255,255,255,96);"
                "}"
            )
            group_lay = vbox((8, 8, 8, 8), 4)
            title = make_label(f"窗口 {page_index + 1}", "sectionBlue")
            self.page_group_titles.append(title)
            group_lay.addWidget(title)

            rows: list[ChannelRow] = []
            for i in range(MAX_CHANNELS):
                row = ChannelRow(i, CHANNEL_COLORS[i])
                row.toggled.connect(
                    lambda idx, on, pi=page_index: self.on_channel_toggled(pi, idx, on)
                )
                row.selected.connect(
                    lambda idx, pi=page_index: self._select_channel(idx, pi)
                )
                row.editRequested.connect(lambda idx: self.edit_variable(idx))
                row.contextMenuRequested.connect(
                    lambda idx, pos, pi=page_index: self._show_variable_menu_at(idx, pos, pi)
                )
                row.setVisible(False)
                rows.append(row)
                group_lay.addWidget(row)
            group.setLayout(group_lay)
            self.channel_rows_by_page.append(rows)
            self.page_groups.append(group)
            lay.addWidget(group)

        self.empty_hint = make_label(
            "暂无变量\n接收到数据后会自动显示变量", "emptyHint"
        )
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        lay.addWidget(self.empty_hint)
        lay.addStretch(1)
        self.right_body.setLayout(lay)

        self.right_scroll = QScrollArea()
        self.right_scroll.setObjectName("rightScroll")
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.right_scroll.setWidget(self.right_body)
        outer.addWidget(self.right_scroll, 1)

        self.right_strip = QFrame()
        self.right_strip.setObjectName("railRight")
        self.right_strip.setFixedWidth(48)
        strip_lay = vbox((5, 8, 5, 8), 8)
        expand_btn = QToolButton()
        expand_btn.setObjectName("railBtn")
        expand_btn.setIcon(icon("curve", 24, "#2D7EF1"))
        expand_btn.setIconSize(QSize(24, 24))
        expand_btn.setCheckable(True)
        expand_btn.setChecked(True)
        expand_btn.setToolTip("展开数据栏")
        expand_btn.clicked.connect(lambda: self.set_data_panel_collapsed(False))
        strip_lay.addWidget(expand_btn, 0, Qt.AlignHCenter)
        strip_lay.addStretch(1)
        self.right_strip.setLayout(strip_lay)
        self.right_strip.setVisible(False)
        outer.addWidget(self.right_strip, 1)

        right.setLayout(outer)
        self.right_panel = right
        return right

    def set_data_panel_collapsed(self, collapsed: bool) -> None:
        """收起 / 展开右侧数据栏，收起后只留一条可点击的窄条。"""
        if self._data_collapsed == collapsed:
            return
        self._data_collapsed = collapsed
        splitter = self.center_splitter
        sizes = splitter.sizes()
        total = sum(sizes) or self.width()
        if collapsed:
            if len(sizes) > 1 and sizes[1] > 120:
                self._right_width = sizes[1]
            self.right_scroll.setVisible(False)
            self.right_strip.setVisible(True)
            self.right_panel.setMinimumWidth(48)
            self.right_panel.setMaximumWidth(48)
            splitter.setSizes([max(200, total - 48), 48])
        else:
            self.right_strip.setVisible(False)
            self.right_scroll.setVisible(True)
            self.right_panel.setMinimumWidth(190)
            self.right_panel.setMaximumWidth(400)
            width = max(190, min(400, self._right_width))
            splitter.setSizes([max(200, total - width), width])

    # ================= 波形页 =================
    def current_page(self) -> PlotPage:
        pages = getattr(self, "pages", [])
        if pages and self.active_page in pages:
            return self.active_page
        return pages[0] if pages else None  # type: ignore[return-value]

    def _page_index(self, page: PlotPage | None) -> int:
        pages = getattr(self, "pages", [])
        if page in pages:
            return pages.index(page)
        return 0

    @property
    def channel_rows(self) -> list[ChannelRow]:
        groups = getattr(self, "channel_rows_by_page", [])
        if not groups:
            return []
        index = min(self._page_index(self.current_page()), len(groups) - 1)
        return groups[index]

    def _set_active_page(self, page: PlotPage) -> None:
        if page not in self.pages:
            return
        self.active_page = page
        if hasattr(self, "rx_count_label"):
            self.update_stats(page)
        self._sync_auto_label_from_page(page)
        self._sync_variable_groups()

    def _sync_auto_label_from_page(self, page: PlotPage | None = None) -> None:
        if not hasattr(self, "auto_label"):
            return
        page = page or self.current_page()
        if page is None:
            return
        self.auto_label.blockSignals(True)
        self.auto_label.setChecked(bool(page.auto_scale))
        self.auto_label.blockSignals(False)

    def _sync_variable_groups(self) -> None:
        groups = getattr(self, "page_groups", [])
        if not groups:
            return
        active = self._page_index(self.current_page())
        for index, group in enumerate(groups):
            group.setVisible(index < self.plot_layout_mode)
            if index < len(self.page_group_titles):
                title = self.page_group_titles[index]
                if index == active:
                    title.setText(f"窗口 {index + 1} · 当前")
                    title.setStyleSheet("color:#0A84E8;font-weight:bold;")
                else:
                    title.setText(f"窗口 {index + 1}")
                    title.setStyleSheet("color:#5C7189;")
        self._update_empty_hint()

    def _apply_smart_modes(self, mode: int) -> None:
        plans = {1: ("time", "time", "time"), 2: ("fft", "time", "time"), 3: ("fft", "time", "time")}
        for index, page in enumerate(self.pages):
            if index >= mode or self.page_mode_locked[index]:
                continue
            target = plans[mode][index]
            if page.plot_mode != target:
                page.set_plot_mode(target)
        if mode >= 3 and not self.page_mode_locked[2] and len(self.pages) > 2:
            detail = self.pages[2]
            detail.set_display_points(min(400, detail.display_points or 400))
            show_count = min(4, self.channel_count)
            for index in range(MAX_CHANNELS):
                detail.set_visible(index, index < show_count)

    def _set_page_mode_lock(self, index: int, locked: bool) -> None:
        if 0 <= index < len(self.page_mode_locked):
            self.page_mode_locked[index] = bool(locked)

    def _set_page_mode(self, page: PlotPage, mode: str) -> None:
        page.set_plot_mode(mode)
        self._set_page_mode_lock(self._page_index(page), True)
        page.refresh()

    def set_plot_layout(self, mode: int, message: bool = True) -> None:
        mode = max(1, min(3, int(mode)))
        self.plot_layout_mode = mode
        self._apply_smart_modes(mode)
        height = self.plot_splitter.height() or 600
        weights = {1: (1,), 2: (1, 1), 3: (3, 4, 3)}[mode]
        total = sum(weights)
        sizes: list[int] = []
        for index, page in enumerate(self.pages):
            visible = index < mode
            page.setVisible(visible)
            sizes.append(height * weights[index] // total if visible else 0)
        remaining = height - sum(sizes)
        for index in range(mode - 1, -1, -1):
            if remaining <= 0:
                break
            sizes[index] += 1
            remaining -= 1
        self.plot_splitter.setSizes(sizes)
        self.view2_btn.setChecked(mode == 2)
        self.view3_btn.setChecked(mode == 3)
        if self.active_page is None or not self.active_page.isVisible():
            self.active_page = self.pages[0]
        for page in self.pages:
            if page.isVisible():
                page.refresh()
        self._sync_variable_groups()
        self._update_channel_rows()
        if message:
            self.statusBar().showMessage(f"波形窗口：{mode} 窗显示", 2000)

    def _create_page(self) -> None:
        page = PlotPage(dark=self.dark)
        page.set_channel_count(self.channel_count)
        page.set_auto_scale(True)
        for index in range(MAX_CHANNELS):
            page.set_visible(index, True)
        page.set_inspect_mode(self.plot_paused)
        page.autoScaleRequested.connect(
            lambda enabled, target=page: self._on_page_auto_requested(target, enabled)
        )
        page.activated.connect(self._set_active_page)
        page.contextMenuRequested.connect(
            lambda pos, target=page: self._show_plot_menu_at(target, pos)
        )
        for i in range(MAX_CHANNELS):
            page.set_channel_color(i, self.channel_colors[i])
            page.set_channel_name(i, self.channel_names[i])
        self.pages.append(page)
        self.plot_splitter.addWidget(page)
        if self.active_page is None:
            self.active_page = page

    def _show_plot_menu_at(self, page: PlotPage, global_pos) -> None:
        """波形区右键菜单：所有操作只作用于被右键的窗口。"""
        self._set_active_page(page)
        page_index = self._page_index(page)
        menu = self._build_variable_menu(page=page)

        display_menu = QMenu("显示模式", menu)
        time_act = display_menu.addAction("时域波形")
        fft_act = display_menu.addAction("频域分析（FFT）")
        for action, checked in (
            (time_act, page.plot_mode == "time"),
            (fft_act, page.plot_mode == "fft"),
        ):
            action.setCheckable(True)
            action.setChecked(checked)
        time_act.triggered.connect(lambda _=False, p=page: self._set_page_mode(p, "time"))
        fft_act.triggered.connect(lambda _=False, p=page: self._set_page_mode(p, "fft"))
        smart_act = display_menu.addAction("跟随布局自动切换")
        smart_act.setCheckable(True)
        smart_act.setChecked(not self.page_mode_locked[page_index])
        smart_act.triggered.connect(
            lambda _=False, idx=page_index: self._set_page_mode_lock(idx, False)
        )
        menu.addMenu(display_menu)

        window_menu = QMenu("FFT 窗函数", menu)
        for key, label in FFT_WINDOWS.items():
            act = window_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(page.fft_settings.get("window") == key)
            act.triggered.connect(lambda _=False, p=page, k=key: p.set_fft_window(k))
        menu.addMenu(window_menu)

        scale_menu = QMenu("FFT 纵轴", menu)
        for key, label in FFT_SCALES.items():
            act = scale_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(page.fft_settings.get("scale") == key)
            act.triggered.connect(lambda _=False, p=page, k=key: p.set_fft_scale(k))
        menu.addMenu(scale_menu)

        diff_act = menu.addAction("游标测量 A/B")
        diff_act.setCheckable(True)
        diff_act.setChecked(page.diff_mode)
        diff_act.setToolTip("暂停后可拖动 A / B 游标；运行时开启会自动暂停，取消勾选即隐藏游标")
        diff_act.toggled.connect(
            lambda on=False, target=page: self._toggle_page_cursor(target, on)
        )

        menu.addSeparator()
        auto_act = menu.addAction("Auto 自动量程")
        auto_act.setCheckable(True)
        auto_act.setChecked(page.auto_scale)
        auto_act.toggled.connect(
            lambda on=False, p=page: (p.set_auto_scale(on), p.refresh())
        )
        menu.exec(global_pos)

    def _toggle_page_cursor(self, page: PlotPage, enabled: bool) -> None:
        if enabled and not self.plot_paused:
            self.set_plot_paused(True, message=False)
        page.set_inspect_mode(bool(enabled))

    def add_variable(self) -> None:
        """新增一个波形变量槽位，可自定义名称、颜色与参数。"""
        if self.channel_count >= MAX_CHANNELS:
            QMessageBox.information(
                self, "变量已满", f"最多支持 {MAX_CHANNELS} 个变量"
            )
            return
        index = self.channel_count
        dialog = VariableDialog(
            "添加变量",
            f"I{index}",
            self.channel_colors[index],
            self.gains[index],
            self.offsets[index],
            self.channel_decimals[index],
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        name, color, gain, offset, decimals = dialog.values()
        self.channel_count = max(self.channel_count, index + 1)
        self._apply_variable(index, name or f"I{index}", color, gain, offset, decimals)
        for page in self.pages:
            page.set_channel_count(self.channel_count)
        self._update_channel_rows()
        self._select_channel(index)
        self.statusBar().showMessage(
            f"已添加变量 {self.channel_names[index]}", 3000
        )

    def edit_variable(self, index: int) -> None:
        """编辑已有变量的名称、颜色与参数。"""
        if index < 0 or index >= self.channel_count:
            return
        dialog = VariableDialog(
            "变量设置",
            self.channel_names[index],
            self.channel_colors[index],
            self.gains[index],
            self.offsets[index],
            self.channel_decimals[index],
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        name, color, gain, offset, decimals = dialog.values()
        self._apply_variable(index, name or f"I{index}", color, gain, offset, decimals)
        self._update_channel_rows()
        self.statusBar().showMessage(
            f"变量 {self.channel_names[index]} 已更新", 3000
        )

    def _apply_variable(
        self,
        index: int,
        name: str,
        color: str,
        gain: float,
        offset: float,
        decimals: int,
    ) -> None:
        self.channel_names[index] = name
        self.channel_colors[index] = color
        self.gains[index] = float(gain)
        self.offsets[index] = float(offset)
        self.channel_decimals[index] = int(decimals)
        for page in self.pages:
            page.set_channel_color(index, color)
            page.set_channel_name(index, name)
        for page_index, rows in enumerate(getattr(self, "channel_rows_by_page", [])):
            row = rows[index]
            row.set_name(name)
            row.set_color(color)
            if index < self.channel_count:
                page = self.pages[page_index] if page_index < len(self.pages) else None
                row.eye.blockSignals(True)
                row.eye.setChecked(bool(page.visible[index]) if page else True)
                row.eye.blockSignals(False)

    def _show_variable_menu_at(self, index: int, global_pos, page_index: int | None = None) -> None:
        self._select_channel(index, page_index)
        page = self.pages[page_index] if page_index is not None and page_index < len(self.pages) else None
        self._build_variable_menu(index, page).exec(global_pos)

    def _build_variable_menu(self, index: int | None = None, page: PlotPage | None = None) -> QMenu:
        page = page or self.current_page()
        page_index = self._page_index(page)
        menu = QMenu(self)
        vis_menu = QMenu("显示变量", menu)
        menu.addMenu(vis_menu)
        for i in range(self.channel_count):
            act = vis_menu.addAction(self.channel_names[i])
            act.setCheckable(True)
            act.setChecked(bool(page.visible[i]) if page is not None else True)
            act.toggled.connect(
                lambda on, idx=i, pi=page_index, p=page: self._set_page_variable_visible(pi, p, idx, on)
            )
        vis_menu.setEnabled(self.channel_count > 0)

        target = self.selected_channel if index is None else index
        edit_act = menu.addAction("变量设置…", lambda: self.edit_variable(target))
        edit_act.setEnabled(0 <= target < self.channel_count)

        menu.addSeparator()
        menu.addAction("导入 CSV 回放…", self.import_csv_replay)
        menu.addAction(
            "导出数据 CSV…",
            lambda _=False, p=page: self.export_csv(page=p),
        )
        menu.addAction(
            "导出图片 PNG…",
            lambda _=False, p=page: self.save_screenshot(page=p),
        )
        menu.addAction(
            "清空本窗口",
            lambda _=False, p=page: self.clear_page(p),
        )
        return menu

    def _set_page_variable_visible(self, page_index: int, page: PlotPage | None, index: int, visible: bool) -> None:
        if page is None:
            return
        page.set_visible(index, visible)
        page.refresh()
        rows = getattr(self, "channel_rows_by_page", [])
        if 0 <= page_index < len(rows) and index < len(rows[page_index]):
            eye = rows[page_index][index].eye
            eye.blockSignals(True)
            eye.setChecked(visible)
            eye.blockSignals(False)

    def open_measure_dialog(self) -> None:
        """打开专用测量面板：非模态，便于边拖游标边看结果。"""
        page = self.current_page()
        if self.measure_dialog is None:
            self.measure_dialog = MeasureDialog(page, self.dark, self)
        else:
            self.measure_dialog.set_page(page)
            self.measure_dialog.raise_()
            self.measure_dialog.activateWindow()
        self.measure_dialog.show()

    def apply_sim_mode(self, index: int) -> None:
        modes = ("sine", "step", "pid")
        mode = modes[max(0, min(int(index), len(modes) - 1))]
        if mode == self.sim_mode:
            return
        self.sim_mode = mode
        save_setting("demo/mode", mode)
        self._demo_last_step_ms = 0.0
        self.clear_plot()
        for target in self.pages:
            target.clear_data()
            target.refresh()
        self.statusBar().showMessage(
            {
                "sine": "模拟模式：正弦扫描",
                "step": "模拟模式：阶跃响应",
                "pid": "模拟模式：PID 响应",
            }[mode],
            2500,
        )

    def _sync_record_limit(self) -> None:
        limit = 0 if self.record_unlimited else int(self.buffer_spin.value())
        for page in self.pages:
            page.set_buffer_limit(limit)
        self.buffer_spin.setEnabled(not self.record_unlimited)

    def apply_record_mode(self, enabled: bool) -> None:
        self.record_unlimited = bool(enabled)
        if hasattr(self, "record_btn"):
            self.record_btn.blockSignals(True)
            self.record_btn.setChecked(self.record_unlimited)
            self.record_btn.blockSignals(False)
        self._sync_record_limit()
        self.statusBar().showMessage(
            "连续记录模式已开启：一直记录，关闭软件自动清除"
            if self.record_unlimited
            else "连续记录模式已关闭：恢复缓冲长度限制",
            3500,
        )

    # ================= 数据源 =================
    def on_tick(self) -> None:
        if self.demo_enabled:
            self.generate_demo_data()
        self.update_plot()

    def update_plot(self) -> None:
        page = self.current_page()
        if not self.plot_paused:
            for target in self.pages:
                if target.isVisible():
                    target.refresh()
        self.update_stats(page)
        self._refresh_channel_values()
        if hasattr(self, "display_panel"):
            self.display_panel.refresh_from_data()
        self._update_throughput()

    def _update_throughput(self) -> None:
        now = time.monotonic()
        elapsed = now - self._rate_start
        if elapsed < 1.0:
            return
        kbps = self._rate_bytes / elapsed / 1024.0
        fps = self._rate_frames / elapsed
        if hasattr(self, "rate_label"):
            self.rate_label.setText(f"{kbps:.1f} KB/s · {fps:.0f} fps")
        self._rate_bytes = 0
        self._rate_frames = 0
        self._rate_start = now

    def update_stats(self, page: PlotPage) -> None:
        if not hasattr(self, "rx_count_label"):
            return
        self.rx_count_label.setText(str(self.total_frames))
        self.tx_count_label.setText(str(self.total_tx))
        self.cur_index_label.setText(str(self.sample_index))
        span = page.time_span_ms()
        per_div = max(1.0, span / 8.0)
        self.scale_label.setText(f"{per_div:.0f}ms/格")

    def generate_demo_data(self) -> None:
        rate = self.demo_rate_combo.int_value()
        channels = DEMO_CHANNELS
        per_frame = rate / 30.0
        frames = int(per_frame) + (1 if self._demo_remainder_add(per_frame) else 0)
        if frames <= 0:
            return
        t0 = self.sample_index * self.dt_ms / 1000.0
        step = self.dt_ms / 1000.0
        for k in range(frames):
            t = t0 + k * step
            t_ms = (self.sample_index + k) * self.dt_ms
            if t_ms % self._demo_step_period_ms < self.dt_ms:
                self._demo_last_step_ms = t_ms
            local_t = (t_ms - self._demo_last_step_ms) / 1000.0
            values = []
            for ch in range(channels):
                if self.sim_mode == "sine":
                    freq = 0.8 + ch * 0.5
                    phase = ch * 0.9
                    value = (
                        2.0 * math.sin(2 * math.pi * freq * t + phase)
                        + 0.18 * math.sin(2 * math.pi * 9.0 * t)
                        + ch * 0.6
                    )
                else:
                    value = self._demo_response(local_t, ch)
                values.append(value)
            self.append_values(values, from_demo=True)

    def _demo_response(self, t: float, ch: int) -> float:
        """阶跃 / PID 模拟：带超调与衰减振荡的二阶响应，便于直接测量性能指标。"""
        delay = 0.02 + ch * 0.01
        x = t - delay
        amp = 1.2 + ch * 0.45
        if x <= 0.0:
            return 0.0
        if self.sim_mode == "step":
            wn = 2 * math.pi * (1.6 + ch * 0.15)
            zeta = 0.42
        else:
            wn = 2 * math.pi * (2.2 + ch * 0.2)
            zeta = 0.26
        wd = wn * math.sqrt(1.0 - zeta * zeta)
        response = 1.0 - math.exp(-zeta * wn * x) * (
            math.cos(wd * x) + (zeta * wn / wd) * math.sin(wd * x)
        )
        return amp * response + 0.012 * math.sin(2 * math.pi * 12.0 * x + ch)

    def _demo_remainder_add(self, per_frame: float) -> bool:
        self._demo_acc = getattr(self, "_demo_acc", 0.0) + (per_frame - int(per_frame))
        if self._demo_acc >= 1.0:
            self._demo_acc -= 1.0
            return True
        return False

    def append_values(self, values: list[float], from_demo: bool = False) -> None:
        if not values:
            return
        count = min(len(values), MAX_CHANNELS)
        new_count = max(1, min(max(count, self.channel_count), MAX_CHANNELS))
        if new_count != self.channel_count:
            self.channel_count = new_count
            self._update_channel_rows()
        processed = []
        for i in range(count):
            value = float(values[i]) * self.gains[i] + self.offsets[i]
            processed.append(value)
            self.last_values[i] = value
        for page in self.pages:
            page.set_channel_count(self.channel_count)
            page.append_sample(processed)
        self.total_frames += 1
        self.sample_index += 1
        self._rate_frames += 1
        if from_demo:
            demo_bytes = len(processed) * 4 + 4
            self._rate_bytes += demo_bytes
            self.bytes_total += demo_bytes
            # 模拟模式也让日志里有 RX 反馈：每 200ms 一行，不按帧刷屏
            now = time.monotonic()
            if now - self._last_demo_value_log >= 0.2:
                self._last_demo_value_log = now
                cells = []
                for i, value in enumerate(processed):
                    name = self.channel_names[i] if i < len(self.channel_names) else f"I{i}"
                    cells.append(f"{name}={value:+.3f}")
                self.log_rx("[模拟RX] " + "  ".join(cells), kind="rx")
        if not from_demo and not self.rx_hex_mode and self.engine_name == "JustFloat":
            now = time.monotonic()
            if now - self._last_value_log >= 0.15:
                self._last_value_log = now
                text = ", ".join(f"{v:.4f}" for v in processed)
                self.log_rx(text, kind="rx")

    # ================= 接收解析 =================
    @Slot(bytes)
    def on_raw(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.bytes_total += len(chunk)
        self._rate_bytes += len(chunk)
        try:
            self._handle_chunk(chunk)
        except Exception as exc:  # 单帧异常不应中断接收
            self.log_rx(f"[parse error] {exc}", kind="tx")

    def _handle_chunk(self, chunk: bytes) -> None:
        if self.engine_name == "RawData":
            now = time.monotonic()
            if now - self._last_raw_log >= 0.15:
                self._last_raw_log = now
                preview = chunk[:512]
                suffix = " …" if len(chunk) > len(preview) else ""
                self.log_rx(
                    "[raw] " + self._format_rx_payload(preview) + suffix, kind="rx"
                )
            self.parse_rawdata(chunk)
            return
        if self.looks_like_ascii(chunk):
            self.rx_line_buffer.extend(chunk)
            while b"\n" in self.rx_line_buffer:
                line, _, rest = self.rx_line_buffer.partition(b"\n")
                self.rx_line_buffer = bytearray(rest)
                raw_line = bytes(line)
                text = raw_line.decode(errors="ignore").strip().replace("\r", "")
                if not text:
                    continue
                values = self.parse_ascii_float_line(text)
                if values:
                    if self.rx_hex_mode:
                        self.log_rx("[rx] " + raw_line.hex(" ").upper(), kind="rx")
                    else:
                        self.log_rx(text, kind="rx")
                    self.append_values(values)
        else:
            if self.rx_hex_mode:
                now = time.monotonic()
                if now - self._last_rx_hex_log >= 0.15:
                    self._last_rx_hex_log = now
                    preview = chunk[:512]
                    suffix = " …" if len(chunk) > len(preview) else ""
                    self.log_rx(
                        "[rx] " + preview.hex(" ").upper() + suffix, kind="rx"
                    )
            for frame in self.justfloat.feed(chunk):
                self.append_values(frame)

    @staticmethod
    def looks_like_ascii(chunk: bytes) -> bool:
        probe = chunk[:512]
        if not probe:
            return False
        printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in probe)
        return printable >= len(probe) * 0.95

    def parse_rawdata(self, chunk: bytes) -> None:
        self.raw_frame_bytes.extend(chunk)
        while b"\n" in self.raw_frame_bytes:
            line, _, rest = self.raw_frame_bytes.partition(b"\n")
            self.raw_frame_bytes = bytearray(rest)
            packet = bytes(line).strip().replace(b"\r", b"")
            if not packet:
                continue
            values = self.try_parse_raw_packet(packet)
            if values:
                self.append_values(values)

        if b"\n" not in self.raw_frame_bytes:
            buffered = self.raw_frame_bytes
            if 0 < len(buffered) <= 32 and len(buffered) % 4 == 0:
                values = self.try_parse_raw_packet(bytes(buffered))
                if values:
                    self.append_values(values)
                    self.raw_frame_bytes.clear()

    def try_parse_raw_packet(self, packet: bytes) -> list[float] | None:
        try:
            text = packet.decode("ascii").strip()
            if text and re.fullmatch(r"[0-9A-Fa-f\s]+", text):
                raw = bytes.fromhex(text)
                if len(raw) >= 4 and len(raw) % 4 == 0:
                    return list(struct.unpack("<" + "f" * (len(raw) // 4), raw))
        except (UnicodeDecodeError, ValueError):
            pass

        try:
            text = packet.decode("utf-8").strip()
            values = self.parse_ascii_float_line(text)
            if values:
                return values
        except UnicodeDecodeError:
            pass

        if len(packet) >= 4 and len(packet) % 4 == 0:
            try:
                return list(struct.unpack("<" + "f" * (len(packet) // 4), packet))
            except struct.error:
                return None
        return None

    @staticmethod
    def parse_ascii_float_line(text: str) -> list[float] | None:
        parts = [p for p in re.split(r"[\s,;]+", text.strip()) if p]
        values = []
        for part in parts:
            try:
                values.append(float(part))
            except ValueError:
                return None
        return values or None

    # ================= 日志 =================
    def log_rx(self, text: str, kind: str = "rx") -> None:
        line = text
        if self.stamp_log:
            line = f"{time.strftime('%H:%M:%S')} {text}"
        self.log_lines.append((kind, line))
        if len(self.log_lines) > 2000:
            del self.log_lines[: len(self.log_lines) - 2000]
        if self._log_visible(kind):
            self._append_log_text(line)

    def _format_rx_payload(self, data: bytes) -> str:
        if self.rx_hex_mode:
            return data.hex(" ").upper()
        return (
            data.decode(self.encoding, errors="replace")
            .replace("\r", "")
            .replace("\n", " ⏎ ")
        )

    def _log_visible(self, kind: str) -> bool:
        if kind == "rx" and self.filter_tx:
            return False
        if kind == "tx" and self.filter_rx:
            return False
        return True

    def _append_log_text(self, line: str) -> None:
        self.rx_text.appendPlainText(line)
        bar = self.rx_text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _rebuild_log_view(self) -> None:
        self.rx_text.clear()
        for kind, line in self.log_lines:
            if self._log_visible(kind):
                self.rx_text.appendPlainText(line)
        bar = self.rx_text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_log(self) -> None:
        self.log_lines.clear()
        self.rx_text.clear()
        self.statusBar().showMessage("接收日志已清空", 2000)

    def save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存接收日志", "vofa_log.txt", "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.rx_text.toPlainText())
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.statusBar().showMessage(f"日志已保存：{path}", 4000)

    def _apply_log_font(self) -> None:
        # 只覆盖字号，配色交给全局样式表，这样深色模式才能跟着变
        size = self._log_font_size
        self.rx_text.setStyleSheet(
            "QPlainTextEdit{"
            f"font-family:Consolas,'Microsoft YaHei UI';font-size:{size}px;}}"
        )

    def bump_log_font(self, delta: int) -> None:
        self._log_font_size = max(9, min(24, self._log_font_size + delta))
        self._apply_log_font()
        self.statusBar().showMessage(f"日志字号 {self._log_font_size}", 1500)

    def on_filter_rx(self, checked: bool) -> None:
        self.filter_rx = checked
        if checked:
            self.btn_tx.setChecked(False)
        self._rebuild_log_view()
        self.statusBar().showMessage(
            "日志仅显示接收" if checked else "日志显示全部", 2000
        )

    def on_filter_tx(self, checked: bool) -> None:
        self.filter_tx = checked
        if checked:
            self.btn_rx.setChecked(False)
        self._rebuild_log_view()
        self.statusBar().showMessage(
            "日志仅显示发送" if checked else "日志显示全部", 2000
        )

    def on_toggle_stamp(self, checked: bool) -> None:
        self.stamp_log = checked
        self.statusBar().showMessage(
            "日志时间戳已开启" if checked else "日志时间戳已关闭", 2000
        )

    # ================= 引擎 / 接口 =================
    def on_engine_changed(self, name: str) -> None:
        self.engine_name = name
        self.justfloat.reset()
        self.rx_line_buffer.clear()
        self.raw_frame_bytes.clear()
        self.log_rx(f"[engine] {name}", kind="tx")
        self.statusBar().showMessage(f"数据引擎切换为 {name}", 3000)

    def on_iface_changed(self, name: str) -> None:
        if self.worker is not None or self.connected:
            self._manual_disconnect = True
            self._reconnect_armed = False
            self.reconnect_timer.stop()
            self._disconnect()
        self.interface_name = name
        self.set_plot_paused(False, message=False)
        self._reset_variables(reset_style=True)
        self._sync_param_panel(name)
        if name == "模拟模式":
            self.demo_enabled = False
            self._set_link_state(False)
            self.mode_tag.setText("● 模拟模式")
            self.mode_tag.setObjectName("primary")
            self.statusBar().showMessage(
                "已进入模拟模式：点击右上角「模拟模式」或顶栏「连接」开始输出模拟数据", 4000
            )
        else:
            self.demo_enabled = False
            self._set_link_state(False)
            self.mode_tag.setText("● 模拟模式")
            self.mode_tag.setObjectName("primary")
            self.statusBar().showMessage(f"接口切换为 {name}", 3000)
        self.mode_tag.style().polish(self.mode_tag)

    def _sync_param_panel(self, name: str) -> None:
        if name == "串口":
            self.param_stack.setCurrentIndex(0)
        elif name == "模拟模式":
            self.param_stack.setCurrentIndex(2)
        else:
            self.param_stack.setCurrentIndex(1)
            hints = {
                "UDP": ("127.0.0.1", 8886),
                "TCP客户端": ("127.0.0.1", 8886),
                "TCP服务端": ("0.0.0.0", 8886),
            }
            host, port = hints.get(name, ("127.0.0.1", 8886))
            self.net_host_edit.setText(host)
            self.net_port_spin.setValue(port)

        # QStackedWidget 默认取所有页里最宽的那个，切换到模拟模式时会留下大片空白。
        # 只按当前页给宽度，后面的连接按钮就能紧跟着参数。
        page = self.param_stack.currentWidget()
        if page is not None:
            self.param_stack.setFixedWidth(page.sizeHint().width())

    def toggle_demo(self) -> None:
        """右上角按钮：只在「模拟模式 / 模拟中」之间切换，始终不显示串口。"""
        if self.interface_name != "模拟模式":
            self.iface_combo.setCurrentText("模拟模式")
            if not self.demo_enabled:
                self._toggle_demo_stream()
            return
        self._toggle_demo_stream()

    def _remember_panel_widths(self) -> None:
        if not hasattr(self, "body_splitter"):
            return
        if self.display_panel.isVisible():
            self._display_width = max(200, self.display_panel.width())
        if self.drawer.isVisible():
            self._drawer_width = max(200, self.drawer.width())

    def toggle_command_drawer(self) -> None:
        if self.drawer.isVisible():
            self._drawer_width = max(200, self.drawer.width())
            self.drawer.setVisible(False)
            self.btn_cmd.setChecked(False)
        else:
            self.drawer.setVisible(True)
            width = getattr(self, "_drawer_width", 280)
            display_width = self.display_panel.width() if self.display_panel.isVisible() else 0
            total = max(self.body_splitter.width(), 48 + display_width + width + 400)
            self.body_splitter.setSizes(
                [48, display_width, width, total - 48 - display_width - width]
            )
            self.btn_cmd.setChecked(True)

    def toggle_display_panel(self) -> None:
        if self.display_panel.isVisible():
            self._display_width = max(200, self.display_panel.width())
            self.display_panel.setVisible(False)
            self.btn_widgets.setChecked(False)
        else:
            self.display_panel.setVisible(True)
            width = getattr(self, "_display_width", 235)
            drawer_width = self.drawer.width() if self.drawer.isVisible() else 0
            total = max(self.body_splitter.width(), 48 + width + drawer_width + 400)
            self.body_splitter.setSizes(
                [48, width, drawer_width, total - 48 - width - drawer_width]
            )
            self.btn_widgets.setChecked(True)

    # ================= 串口 / 网络连接 =================
    def _build_serial_fmt_menu(self) -> None:
        menu = self.serial_fmt_menu
        menu.clear()
        for title, attr, options in (
            ("数据位", "serial_bits", [8, 7]),
            ("校验位", "serial_parity", ["None", "Even", "Odd"]),
            ("停止位", "serial_stopbits", [1, 2]),
            ("流控", "serial_flow", ["None", "Hardware", "Software"]),
        ):
            sub = QMenu(title, menu)
            menu.addMenu(sub)
            current = getattr(self, attr)
            for option in options:
                act = sub.addAction(str(option))
                act.setCheckable(True)
                act.setChecked(option == current)
                act.triggered.connect(
                    lambda _=False, a=attr, o=option: self._set_serial_param(a, o)
                )
        menu.addSeparator()
        reconnect_act = menu.addAction("串口自动重连")
        reconnect_act.setCheckable(True)
        reconnect_act.setChecked(self.auto_reconnect)
        reconnect_act.setToolTip("端口意外断开后自动重连上次端口（手动断开不会重连）")
        reconnect_act.toggled.connect(self._set_auto_reconnect)
        menu.addAction("恢复默认 8N1", self._reset_serial_fmt)

    def _set_auto_reconnect(self, enabled: bool) -> None:
        self.auto_reconnect = bool(enabled)
        save_setting("serial/auto_reconnect", self.auto_reconnect)
        if not self.auto_reconnect:
            self.reconnect_timer.stop()
        self.statusBar().showMessage(
            "串口自动重连已开启" if enabled else "串口自动重连已关闭", 2000
        )

    def _set_serial_param(self, attr: str, value) -> None:
        setattr(self, attr, value)
        self._update_serial_fmt_text()
        self._build_serial_fmt_menu()

    def _reset_serial_fmt(self) -> None:
        self.serial_bits = 8
        self.serial_parity = "None"
        self.serial_stopbits = 1
        self.serial_flow = "None"
        self._update_serial_fmt_text()
        self._build_serial_fmt_menu()

    def _update_serial_fmt_text(self) -> None:
        parity = {"None": "N", "Even": "E", "Odd": "O"}.get(
            self.serial_parity, "N"
        )
        text = f"{self.serial_bits}{parity}{self.serial_stopbits}"
        if self.serial_flow == "Hardware":
            text += " RTS"
        elif self.serial_flow == "Software":
            text += " XON"
        self.serial_fmt_btn.setText(text)
        self.statusBar().showMessage(f"串口格式：{text}", 3000)

    @staticmethod
    def _real_ports() -> list[str]:
        """只返回真实存在的串口，不使用 refresh_ports 的演示占位端口。"""
        try:
            return [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return []

    def _restore_serial_selection(self) -> None:
        if self._last_serial_baud:
            self.baud_combo.setCurrentText(self._last_serial_baud)
        ports = self._real_ports()
        if self._last_serial_port and self._last_serial_port in ports:
            self.port_combo.setCurrentText(self._last_serial_port)

    def _should_auto_reconnect(self) -> bool:
        return (
            self.auto_reconnect
            and self.interface_name == "串口"
            and self._reconnect_armed
            and not self._manual_disconnect
            and self.worker is None
            and not self.connected
        )

    def _schedule_reconnect(self) -> None:
        if self.reconnect_timer.isActive() or not self._should_auto_reconnect():
            return
        self.mode_tag.setText("● 等待重连")
        self.mode_tag.setObjectName("primary")
        self.mode_tag.style().polish(self.mode_tag)
        self.statusBar().showMessage("串口已断开，1.5 秒后自动重连…", 3000)
        self.reconnect_timer.start(1500)

    def _auto_reconnect_attempt(self) -> None:
        if not self._should_auto_reconnect():
            self.reconnect_timer.stop()
            return
        port = self._last_serial_port or self.port_combo.currentText().strip()
        if not port or port not in self._real_ports():
            # 设备还没插回来：保持定时检查，不弹窗打扰
            self.reconnect_timer.start(1500)
            return
        self.port_combo.setCurrentText(port)
        if self._last_serial_baud:
            self.baud_combo.setCurrentText(self._last_serial_baud)
        self._manual_disconnect = False
        self._auto_connecting = True
        self.statusBar().showMessage(f"正在自动重连 {port} …", 2000)
        self._connect()

    def refresh_ports(self, silent: bool = False) -> None:
        """刷新串口列表；silent 为定时自动刷新，不打断下拉与状态栏。"""
        if silent and self.port_combo.view().isVisible():
            return
        current = self.port_combo.currentText()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if not ports:
            ports = ["COM4", "COM3", "COM1"]
        existing = [self.port_combo.itemText(i) for i in range(self.port_combo.count())]
        if silent and ports == existing:
            return
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        if current in ports:
            self.port_combo.setCurrentText(current)
        if not silent:
            self.statusBar().showMessage(f"已刷新串口：{len(ports)} 个", 2000)

    def toggle_link(self) -> None:
        if self.interface_name == "模拟模式":
            self._toggle_demo_stream()
            return
        if self.worker is not None or self.connected:
            self._manual_disconnect = True
            self._reconnect_armed = False
            self.reconnect_timer.stop()
            self._disconnect()
            self.statusBar().showMessage("已断开连接", 3000)
            return
        self._manual_disconnect = False
        self._reconnect_armed = True
        self.reconnect_timer.stop()
        self._connect()

    def _toggle_demo_stream(self) -> None:
        """模拟模式：连接按钮控制模拟数据流连接 / 断开，断开后可移动鼠标看波形数值。"""
        self.demo_enabled = not self.demo_enabled
        self._set_link_state(self.demo_enabled)
        self.set_plot_paused(not self.demo_enabled, message=False)
        if self.demo_enabled:
            self.mode_tag.setText("● 模拟中")
            self.mode_tag.setObjectName("green")
            self.statusBar().showMessage("模拟数据流已连接，可发送命令", 3000)
        else:
            self.mode_tag.setText("● 模拟模式")
            self.mode_tag.setObjectName("primary")
            self.statusBar().showMessage(
                "模拟数据流已断开：移动鼠标查看数值，按空格恢复波形刷新", 4000
            )
        self.mode_tag.style().polish(self.mode_tag)

    def _set_link_state(self, connected: bool) -> None:
        self.connected = bool(connected)
        if connected:
            self.link_btn.setText("断开")
            self.link_btn.setObjectName("danger")
        else:
            self.link_btn.setText("连接")
            self.link_btn.setObjectName("primary")
        # objectName 变了要重新 polish，否则旧的背景 / 文字色会残留
        self.link_btn.style().unpolish(self.link_btn)
        self.link_btn.style().polish(self.link_btn)

    def _connect(self) -> None:
        self.reconnect_timer.stop()
        name = self.interface_name
        worker: SerialWorker | BaseTransport
        if name == "串口":
            port = self.port_combo.currentText().strip()
            if not port:
                if not self._auto_connecting:
                    QMessageBox.warning(self, "参数错误", "请选择串口端口")
                return
            try:
                baud = int(self.baud_combo.currentText().strip())
            except ValueError:
                if not self._auto_connecting:
                    QMessageBox.warning(self, "参数错误", "波特率必须是整数")
                return
            worker = SerialWorker(
                port,
                baud,
                bytesize=self.serial_bits,
                parity=self.serial_parity,
                stopbits=self.serial_stopbits,
                flow=self.serial_flow,
                parent=self,
            )
        elif name == "UDP":
            worker = UdpTransport(
                self.net_host_edit.text().strip(), self.net_port_spin.value(), parent=self
            )
        elif name == "TCP客户端":
            host = self.net_host_edit.text().strip()
            if not host:
                QMessageBox.warning(self, "参数错误", "请填写服务端 IP 地址")
                return
            worker = TcpClientTransport(host, self.net_port_spin.value(), parent=self)
        elif name == "TCP服务端":
            host = self.net_host_edit.text().strip() or "0.0.0.0"
            worker = TcpServerTransport(host, self.net_port_spin.value(), parent=self)
        else:
            self.statusBar().showMessage("模拟模式无需连接，仍可发送命令", 3000)
            return

        self.worker = worker
        worker.raw_received.connect(self.on_raw)
        worker.error_occurred.connect(self.on_error)
        worker.connected.connect(self.on_connected)
        worker.disconnected.connect(self.on_disconnected)
        worker.start()
        self.link_btn.setText("连接中…")
        self.statusBar().showMessage(f"正在打开 {name} …", 3000)

    def _disconnect(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.stop()
        self.on_disconnected()

    @Slot()
    def on_connected(self) -> None:
        self._set_link_state(True)
        self.demo_enabled = False
        self._auto_connecting = False
        self._manual_disconnect = False
        self._reconnect_armed = True
        self.justfloat.reset()
        self.rx_line_buffer.clear()
        self.raw_frame_bytes.clear()
        if self.interface_name == "串口":
            port = self.port_combo.currentText().strip()
            baud = self.baud_combo.currentText().strip()
            if port:
                self._last_serial_port = port
                save_setting("serial/last_port", port)
            if baud:
                self._last_serial_baud = baud
                save_setting("serial/last_baud", baud)
        self.mode_tag.setText("● 已连接")
        self.mode_tag.setObjectName("primary")
        self.mode_tag.style().polish(self.mode_tag)
        self.log_rx(f"[link] {self.interface_name} 已连接", kind="tx")
        self.statusBar().showMessage(f"{self.interface_name} 已连接", 4000)

    @Slot()
    def on_disconnected(self) -> None:
        if self.sender() is self.worker and self.worker is not None:
            # 后台线程主动掉线：清掉失效 worker，才能进入自动重连流程
            self.worker = None
        self._set_link_state(False)
        if self.interface_name == "模拟模式":
            running = self.demo_enabled
            self.mode_tag.setText("● 模拟中" if running else "● 模拟模式")
            self.mode_tag.setObjectName("green" if running else "primary")
        else:
            self.mode_tag.setText("● 模拟模式")
            self.mode_tag.setObjectName("primary")
        self.mode_tag.setObjectName("green" if self.demo_enabled else "primary")
        self.mode_tag.style().polish(self.mode_tag)
        self._reset_variables(reset_style=True)
        self.statusBar().showMessage("已断开连接", 3000)
        self._auto_connecting = False
        if self._should_auto_reconnect():
            self._schedule_reconnect()

    @Slot(str)
    def on_error(self, message: str) -> None:
        auto_retry = self._auto_connecting
        self.log_rx(f"[error] {message}", kind="tx")
        if not auto_retry:
            QMessageBox.warning(self, "接口错误", message)
        self._disconnect()

    # ================= 发送 / 接收显示 =================
    def _sync_tx_mode_ui(self) -> None:
        self._syncing_tx_mode = True
        self.tx_mode_btn.setChecked(self.hex_mode)
        self.tx_mode_btn.setText("Hex" if self.hex_mode else "Abc")
        self._syncing_tx_mode = False

    def on_tx_mode_toggled(self, checked: bool) -> None:
        if getattr(self, "_syncing_tx_mode", False):
            return
        self.set_hex_mode(checked)

    def set_hex_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        changed = enabled != self.hex_mode
        self.hex_mode = enabled
        self._sync_tx_mode_ui()
        if changed:
            self.statusBar().showMessage(
                "发送格式：Hex" if enabled else "发送格式：文本(Abc)", 2000
            )

    def _sync_rx_mode_ui(self) -> None:
        self._syncing_rx_mode = True
        self.rx_mode_btn.setChecked(self.rx_hex_mode)
        self.rx_mode_btn.setText("Hex" if self.rx_hex_mode else "Abc")
        self.rx_mode_btn.setToolTip(
            "接收显示：Hex（点击切换为 Abc）"
            if self.rx_hex_mode
            else "接收显示：Abc（点击切换为 Hex）"
        )
        self._syncing_rx_mode = False

    def on_rx_mode_toggled(self, checked: bool) -> None:
        if getattr(self, "_syncing_rx_mode", False):
            return
        self.set_rx_hex_mode(checked)

    def set_rx_hex_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        changed = enabled != self.rx_hex_mode
        self.rx_hex_mode = enabled
        self._sync_rx_mode_ui()
        if changed:
            self.statusBar().showMessage(
                "接收显示：Hex 原始字节" if enabled else "接收显示：Abc 文本", 2000
            )

    def set_encoding(self, label: str, codec: str) -> None:
        self.encoding = codec
        self.encoding_btn.setText(f"⌁ {label}")
        self.statusBar().showMessage(f"发送编码切换为 {label}", 2500)

    def send_from_edit(self) -> None:
        self.send_text(self.tx_edit.text())

    def send_text(self, text: str) -> None:
        if not text.strip():
            return
        try:
            if self.hex_mode:
                payload = bytes.fromhex(text.replace(" ", "").replace(",", ""))
            else:
                payload = text.encode(self.encoding, errors="replace")
        except ValueError:
            QMessageBox.warning(
                self, "发送格式错误", "当前为 Hex 模式，请输入正确的十六进制字节串。"
            )
            return

        mode = self.ending_combo.currentIndex()
        if mode == 1:
            payload += b"\n"
        elif mode == 2:
            payload += b"\r\n"

        if self.worker is not None:
            if not self.worker.send(payload):
                QMessageBox.information(self, "发送失败", "接口尚未就绪，请检查连接")
                return
            shown = payload.hex(" ").upper() if self.hex_mode else text
            self.log_rx("[tx] " + shown, kind="tx")
            self.statusBar().showMessage(f"已发送 {len(payload)} 字节", 3000)
        else:
            shown = payload.hex(" ").upper() if self.hex_mode else text
            self.log_rx("[tx] " + shown, kind="tx")
            self.statusBar().showMessage(
                f"模拟模式已发出 {len(payload)} 字节（仅回显，接串口后真实下发）", 3000
            )
        self._mark_tx_sent()

    def send_payload(self, payload: bytes) -> None:
        """直接发送已组好的字节帧（命令面板使用）。"""
        if not payload:
            return
        shown = payload.hex(" ").upper()
        if self.worker is not None:
            if not self.worker.send(payload):
                QMessageBox.information(self, "发送失败", "接口尚未就绪，请检查连接")
                return
            self.log_rx("[tx] " + shown, kind="tx")
            self.statusBar().showMessage(f"已发送 {len(payload)} 字节", 2000)
        else:
            self.log_rx("[tx] " + shown, kind="tx")
            self.statusBar().showMessage(
                f"模拟模式已发出 {len(payload)} 字节（仅回显，接串口后真实下发）", 2000
            )
        self._mark_tx_sent()

    def _mark_tx_sent(self) -> None:
        self.total_tx += 1
        if hasattr(self, "tx_count_label"):
            self.update_stats(self.current_page())

    # ================= 波形 / 通道 =================
    def clear_page(self, page: PlotPage | None = None) -> None:
        page = page or self.current_page()
        page.clear_data()
        page.refresh()
        self.update_stats(page)
        self.statusBar().showMessage(
            f"窗口 {self._page_index(page) + 1} 波形已清空", 3000
        )

    def clear_plot(self) -> None:
        self.total_frames = 0
        self.total_tx = 0
        self.sample_index = 0
        self.raw_frame_bytes.clear()
        self.rx_line_buffer.clear()
        self._demo_acc = 0.0
        self._reset_variables()
        self.update_stats(self.current_page())
        self.statusBar().showMessage("波形已清空", 3000)

    def save_screenshot(
        self, path: str | bool | None = None, page: PlotPage | None = None
    ) -> None:
        page = page or self.current_page()
        if not isinstance(path, str):
            path, _ = QFileDialog.getSaveFileName(
                self, "导出曲线图片", "waveform.png", "PNG 图片 (*.png)"
            )
        if not path:
            return
        if page.grab().save(path):
            self.statusBar().showMessage(f"图片已保存：{path}", 4000)

    def export_csv(
        self, path: str | bool | None = None, page: PlotPage | None = None
    ) -> None:
        """把指定波形页的缓冲数据导出为 CSV。"""
        page = page or self.current_page()
        if page.total_points() == 0:
            QMessageBox.information(self, "没有数据", "当前波形没有可导出的数据")
            return
        if not isinstance(path, str):
            path, _ = QFileDialog.getSaveFileName(
                self, "导出曲线数据", "waveform.csv", "CSV 文件 (*.csv)"
            )
        if not path:
            return

        count = max(1, min(page.channel_count, len(page.buffers)))
        digits = [self.channel_decimals[i] for i in range(count)]
        names = [self.channel_names[i] for i in range(count)]
        times = list(page.times)
        columns = [list(page.buffers[i]) for i in range(count)]
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["time_ms", *names])
                for row, t_ms in enumerate(times):
                    values = [
                        f"{columns[i][row]:.{digits[i]}f}" for i in range(count)
                    ]
                    writer.writerow([f"{t_ms:.3f}", *values])
        except (OSError, IndexError) as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.statusBar().showMessage(f"已导出 {len(times)} 行数据：{path}", 4000)

    def import_csv_replay(self, path: str | bool | None = None) -> None:
        """把本程序导出的 CSV（time_ms + 各通道）重新画成波形。"""
        if not isinstance(path, str):
            path, _ = QFileDialog.getOpenFileName(
                self, "导入 CSV 回放", "waveform.csv", "CSV 文件 (*.csv)"
            )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                rows = [row for row in csv.reader(fh) if row and any(c.strip() for c in row)]
        except (OSError, UnicodeError, csv.Error) as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        if not rows:
            QMessageBox.information(self, "没有数据", "CSV 文件是空的")
            return

        header = [cell.strip() for cell in rows[0]]
        data_rows = rows
        names: list[str] = []
        if header and header[0].lower() in ("time_ms", "time", "t", "时间", "时间/ms"):
            names = [name or f"I{i}" for i, name in enumerate(header[1 : MAX_CHANNELS + 1])]
            data_rows = rows[1:]

        parsed: list[tuple[float, list[float]]] = []
        for row in data_rows:
            try:
                t_ms = float(row[0])
            except (ValueError, IndexError):
                continue
            values: list[float] = []
            for cell in row[1 : MAX_CHANNELS + 1]:
                try:
                    values.append(float(cell))
                except ValueError:
                    values.append(0.0)
            while len(values) < MAX_CHANNELS:
                values.append(values[-1] if values else 0.0)
            parsed.append((t_ms, values[:MAX_CHANNELS]))
        if not parsed:
            QMessageBox.information(self, "没有数据", "CSV 中没有可回放的数值行")
            return

        # 回放时暂停真实数据源，避免新数据混进历史曲线；也不触发自动重连
        self.demo_enabled = False
        self._manual_disconnect = True
        self._reconnect_armed = False
        self.reconnect_timer.stop()
        if self.worker is not None or self.connected:
            self._disconnect()

        page_states = [
            (
                page.plot_mode,
                list(page.visible[:MAX_CHANNELS]),
                bool(page.auto_scale),
                dict(page.fft_settings),
                bool(page.diff_mode),
            )
            for page in self.pages
        ]
        data_columns = max((len(row) - 1 for row in data_rows), default=0)
        count = max(1, min(max(len(names), data_columns), MAX_CHANNELS))
        self.channel_count = count
        for i, name in enumerate(names[:MAX_CHANNELS]):
            self.channel_names[i] = name
        self._update_channel_rows()
        for page in self.pages:
            page.set_channel_count(0)
            page.clear_data()
            page.set_channel_count(count)
            for i in range(MAX_CHANNELS):
                page.set_channel_name(i, self.channel_names[i])
                page.set_channel_color(i, self.channel_colors[i])

        self.total_frames = 0
        self.sample_index = 0
        self.set_plot_paused(False, message=False)
        for t_ms, values in parsed:
            for page in self.pages:
                page.append_sample(values, t_ms=t_ms)
            self.total_frames += 1
            self.sample_index += 1
            self.last_values[:count] = values[:count]
        for page, (mode, visible, auto_scale, fft_settings, diff_mode) in zip(
            self.pages, page_states
        ):
            page.set_plot_mode(mode)
            for i in range(MAX_CHANNELS):
                page.set_visible(i, visible[i])
            page.set_auto_scale(auto_scale)
            page.set_diff_mode(diff_mode)
            page.set_fft_window(fft_settings.get("window", "hann"))
            page.set_fft_scale(fft_settings.get("scale", "percent"))
            page.set_fft_size(fft_settings.get("fft_size", 0))
        self._refresh_channel_values()
        self.update_plot()
        self.statusBar().showMessage(f"已回放 {len(parsed)} 行数据：{path}", 4000)

    def export_layout(self, path: str | bool | None = None) -> None:
        """把当前布局导出为 JSON，便于下次一键恢复。"""
        if not isinstance(path, str):
            path, _ = QFileDialog.getSaveFileName(
                self, "导出当前布局", "vofa_flash_layout.json", "JSON 文件 (*.json)"
            )
        if not path:
            return
        channels = {
            "count": self.channel_count,
            "names": list(self.channel_names[:MAX_CHANNELS]),
            "colors": list(self.channel_colors[:MAX_CHANNELS]),
            "gains": list(self.gains[:MAX_CHANNELS]),
            "offsets": list(self.offsets[:MAX_CHANNELS]),
            "decimals": list(self.channel_decimals[:MAX_CHANNELS]),
            "visible": [
                self.channel_rows[i].eye.isChecked() for i in range(MAX_CHANNELS)
            ],
        }
        pages = [
            {
                "visible": list(page.visible[:MAX_CHANNELS]),
                "auto_scale": bool(page.auto_scale),
                "plot_mode": page.plot_mode,
                "fft_settings": dict(page.fft_settings),
                "diff_mode": bool(page.diff_mode),
                "mode_locked": bool(self.page_mode_locked[index]),
            }
            for index, page in enumerate(self.pages)
        ]
        payload = {
            "format": "vofa-flash-layout",
            "version": 2,
            "window": {"geometry": bytes(self.saveGeometry()).hex()},
            "appearance": {"dark": self.dark},
            "plot": {
                "layout": self.plot_layout_mode,
                "auto_scale": bool(self.current_page().auto_scale),
                "dt_ms": self.dt_spin.value(),
                "buffer": self.buffer_spin.value(),
                "align": self.align_spin.value(),
                "splitter": list(self.plot_splitter.sizes()),
            },
            "pages": pages,
            "panels": {
                "body": list(self.body_splitter.sizes()),
                "center": list(self.center_splitter.sizes()),
                "vertical": list(self.center_vsplit.sizes()),
                "display_visible": self.display_panel.isVisible(),
                "drawer_visible": self.drawer.isVisible(),
                "data_collapsed": self._data_collapsed,
            },
            "channels": channels,
        }
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.statusBar().showMessage(f"布局已导出：{path}", 4000)

    def import_layout(self, path: str | bool | None = None) -> None:
        """导入布局 JSON：窗口位置、面板宽度、显示模式与变量样式一起恢复。"""
        if not isinstance(path, str):
            path, _ = QFileDialog.getOpenFileName(
                self, "导入布局 JSON", "", "JSON 文件 (*.json)"
            )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        if not isinstance(data, dict) or data.get("format") != "vofa-flash-layout":
            QMessageBox.warning(self, "导入失败", "不是 VOFA+ Flash 布局 JSON 文件")
            return

        def pick(items, index: int, default):
            if isinstance(items, list) and index < len(items):
                return items[index]
            return default

        try:
            geometry_hex = str(data.get("window", {}).get("geometry", ""))
            if geometry_hex:
                self.restoreGeometry(QByteArray.fromHex(geometry_hex.encode("ascii")))

            dark = bool(data.get("appearance", {}).get("dark", self.dark))
            if dark != self.dark:
                self.apply_theme(dark)

            plot = data.get("plot", {})
            for spin, key, cast in (
                (self.dt_spin, "dt_ms", float),
                (self.buffer_spin, "buffer", int),
                (self.align_spin, "align", int),
            ):
                spin.blockSignals(True)
                try:
                    spin.setValue(cast(plot.get(key, spin.value())))
                finally:
                    spin.blockSignals(False)
            self.dt_ms = float(self.dt_spin.value())
            for page in self.pages:
                page.set_dt(self.dt_ms)
                page.set_buffer_limit(
                    0 if self.record_unlimited else int(self.buffer_spin.value())
                )
                page.set_display_points(int(self.align_spin.value()))

            channels = data.get("channels", {})
            count = max(0, min(int(channels.get("count", self.channel_count)), MAX_CHANNELS))
            self.channel_count = count
            for i in range(MAX_CHANNELS):
                self.channel_names[i] = str(pick(channels.get("names"), i, self.channel_names[i]))
                self.channel_colors[i] = str(pick(channels.get("colors"), i, self.channel_colors[i]))
                try:
                    self.gains[i] = float(pick(channels.get("gains"), i, self.gains[i]))
                    self.offsets[i] = float(pick(channels.get("offsets"), i, self.offsets[i]))
                except (TypeError, ValueError):
                    pass
                try:
                    self.channel_decimals[i] = int(
                        pick(channels.get("decimals"), i, self.channel_decimals[i])
                    )
                except (TypeError, ValueError):
                    pass
            visible = [bool(value) for value in channels.get("visible", [])]
            pages_cfg = data.get("pages", [])
            auto_scale = bool(plot.get("auto_scale", True))
            for index, page in enumerate(self.pages):
                cfg = pages_cfg[index] if index < len(pages_cfg) else {}
                page_visible = [bool(v) for v in cfg.get("visible", visible)]
                page.set_channel_count(count)
                for i in range(MAX_CHANNELS):
                    page.set_channel_color(i, self.channel_colors[i])
                    page.set_channel_name(i, self.channel_names[i])
                    page.set_visible(i, page_visible[i] if i < len(page_visible) else True)
                page.set_auto_scale(bool(cfg.get("auto_scale", auto_scale)))
                page.set_plot_mode(str(cfg.get("plot_mode", "time")))
                page.set_diff_mode(bool(cfg.get("diff_mode", False)))
                fft_cfg = cfg.get("fft_settings", {})
                if isinstance(fft_cfg, dict):
                    if "window" in fft_cfg:
                        page.set_fft_window(str(fft_cfg["window"]))
                    if "scale" in fft_cfg:
                        page.set_fft_scale(str(fft_cfg["scale"]))
                    if "fft_size" in fft_cfg:
                        page.set_fft_size(int(fft_cfg["fft_size"]))
                self.page_mode_locked[index] = bool(cfg.get("mode_locked", False))

            panels = data.get("panels", {})
            self.set_data_panel_collapsed(
                bool(panels.get("data_collapsed", self._data_collapsed))
            )
            show_display = bool(panels.get("display_visible", self.display_panel.isVisible()))
            self.display_panel.setVisible(show_display)
            self.btn_widgets.setChecked(show_display)
            show_drawer = bool(panels.get("drawer_visible", self.drawer.isVisible()))
            self.drawer.setVisible(show_drawer)
            self.btn_cmd.setChecked(show_drawer)

            self.set_plot_layout(int(plot.get("layout", self.plot_layout_mode)), message=False)
            self._sync_auto_label_from_page(self.current_page())
            self._sync_variable_groups()
            self._update_channel_rows()

            def apply_sizes(splitter, sizes) -> None:
                if not isinstance(sizes, list) or len(sizes) != len(splitter.sizes()):
                    return
                splitter.setSizes([max(0, int(value)) for value in sizes])

            apply_sizes(self.body_splitter, panels.get("body"))
            apply_sizes(self.center_splitter, panels.get("center"))
            apply_sizes(self.center_vsplit, panels.get("vertical"))
            apply_sizes(self.plot_splitter, plot.get("splitter"))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            QMessageBox.warning(self, "导入失败", f"布局文件无法解析：{exc}")
            return

        self.update_plot()
        self.statusBar().showMessage(f"布局已恢复：{path}", 4000)

    def on_dt_changed(self, value: float) -> None:
        self.dt_ms = float(value)
        for page in self.pages:
            page.set_dt(self.dt_ms)

    def on_buffer_changed(self, value: int) -> None:
        for page in self.pages:
            page.set_buffer_limit(value)
        self.statusBar().showMessage(f"缓冲区上限 {value}/ch", 2000)

    def on_align_changed(self, value: int) -> None:
        for page in self.pages:
            page.set_display_points(value)

    def _on_page_auto_requested(self, page: PlotPage, enabled: bool) -> None:
        self._sync_auto_label_from_page(page)

    def toggle_auto_scale(self, checked: bool) -> None:
        page = self.current_page()
        if page is None:
            return
        page.set_auto_scale(bool(checked))
        page.refresh()

    def on_channel_toggled(self, page_index: int, index: int, visible: bool) -> None:
        if 0 <= page_index < len(self.pages):
            page = self.pages[page_index]
            page.set_visible(index, visible)
            page.refresh()
            rows = getattr(self, "channel_rows_by_page", [])
            if 0 <= page_index < len(rows) and index < len(rows[page_index]):
                eye = rows[page_index][index].eye
                eye.blockSignals(True)
                eye.setChecked(visible)
                eye.blockSignals(False)
        self.update_stats(self.current_page())

    def _select_channel(self, index: int, page_index: int | None = None) -> None:
        if index < 0 or index >= MAX_CHANNELS:
            return
        if page_index is not None and 0 <= page_index < len(self.pages):
            self._set_active_page(self.pages[page_index])
        self.selected_channel = index
        for rows in getattr(self, "channel_rows_by_page", []):
            for row in rows:
                row.set_selected(row.index == index and index < self.channel_count)

    def set_plot_paused(self, paused: bool, message: bool = True) -> None:
        paused = bool(paused)
        if self.plot_paused == paused:
            return
        self.plot_paused = paused
        for page in self.pages:
            page.set_inspect_mode(paused)
        if paused and self.sim_mode in ("step", "pid") and self.sample_index > 0:
            start_ms = max(0.0, self._demo_last_step_ms - 30.0)
            end_ms = self.sample_index * self.dt_ms
            inset = (end_ms - start_ms) * 0.03
            for page in self.pages:
                page.set_inspect_range(start_ms + inset, end_ms - inset)
        if message:
            self.statusBar().showMessage(
                "波形已暂停：移动鼠标查看数值，按空格继续"
                if paused
                else "波形已继续",
                4000 if paused else 2000,
            )

    def toggle_plot_pause(self) -> None:
        self.set_plot_paused(not self.plot_paused)

    @staticmethod
    def _is_text_input(widget) -> bool:
        return isinstance(
            widget, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)
        ) or (isinstance(widget, QComboBox) and widget.isEditable())

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.KeyPress
            and not self._is_text_input(obj)
            and QApplication.activePopupWidget() is None
        ):
            modal = QApplication.activeModalWidget()
            if modal is None or modal is self:
                modifiers = event.modifiers()
                mods_value = modifiers.value if hasattr(modifiers, "value") else int(modifiers)
                key = event.key()
                key_value = key.value if hasattr(key, "value") else int(key)
                pressed = QKeySequence(mods_value | key_value)
                for action, sequence in self.shortcuts.items():
                    if sequence.isEmpty() or pressed != sequence:
                        continue
                    if action == "pause":
                        self.toggle_plot_pause()
                    elif action == "connect":
                        self.toggle_link()
                    elif action == "screenshot":
                        self.save_screenshot()
                    elif action == "export_csv":
                        self.export_csv()
                    elif action == "clear_plot":
                        self.clear_plot()
                    return True
        return super().eventFilter(obj, event)

    def _target_channel(self) -> int:
        if self.channel_count == 0:
            return -1
        return min(self.selected_channel, self.channel_count - 1)

    def _format_value(self, value: float, index: int = 0) -> str:
        digits = (
            self.channel_decimals[index]
            if 0 <= index < len(self.channel_decimals)
            else 3
        )
        return f"{value:.{digits}f}"

    def _update_channel_rows(self) -> None:
        groups = getattr(self, "channel_rows_by_page", [])
        for page_index, rows in enumerate(groups):
            page = self.pages[page_index] if page_index < len(self.pages) else None
            for i, row in enumerate(rows):
                visible = i < self.channel_count
                row.setVisible(visible)
                if not visible:
                    continue
                row.set_name(self.channel_names[i])
                row.set_color(self.channel_colors[i])
                row.set_value(self._format_value(self.last_values[i], i))
                row.eye.blockSignals(True)
                row.eye.setChecked(bool(page.visible[i]) if page is not None else True)
                row.eye.blockSignals(False)
        self._update_empty_hint()

    def _refresh_channel_values(self) -> None:
        for rows in getattr(self, "channel_rows_by_page", []):
            for i in range(min(self.channel_count, len(rows))):
                rows[i].set_value(self._format_value(self.last_values[i], i))

    def _update_empty_hint(self) -> None:
        if not hasattr(self, "empty_hint"):
            return
        self.empty_hint.setVisible(self.channel_count == 0)

    def _reset_variables(self, reset_style: bool = False) -> None:
        """无数据源时清空变量显示：断开、切接口或清空波形。

        reset_style=True 时连同名称、颜色、增益、偏置、小数位一起恢复默认，
        用于断开或切换接口后重新开始。
        """
        self.channel_count = 0
        self.selected_channel = 0
        self.total_frames = 0
        self.sample_index = 0
        if reset_style:
            self.channel_names = [f"I{i}" for i in range(MAX_CHANNELS)]
            self.channel_colors = list(CHANNEL_COLORS)
            self.channel_decimals = [3] * MAX_CHANNELS
            self.gains = [1.0] * MAX_CHANNELS
            self.offsets = [0.0] * MAX_CHANNELS
        for page in self.pages:
            page.set_channel_count(0)
            page.clear_data()
            for i in range(MAX_CHANNELS):
                page.set_channel_color(i, self.channel_colors[i])
                page.set_channel_name(i, self.channel_names[i])
        for rows in getattr(self, "channel_rows_by_page", []):
            for i, row in enumerate(rows):
                row.setVisible(False)
                row.set_selected(False)
                row.set_value("--")
                row.set_name(self.channel_names[i])
                row.set_color(self.channel_colors[i])
        self._update_empty_hint()

    # ================= 命令抽屉 =================
    def _command_widgets(self) -> list[CommandItem]:
        widgets: list[CommandItem] = []
        for i in range(self.cmd_layout.count()):
            widget = self.cmd_layout.itemAt(i).widget()
            if isinstance(widget, CommandItem):
                widgets.append(widget)
        return widgets

    def _command_groups(self) -> list[str]:
        groups: list[str] = []
        for item in self._command_widgets():
            if item.kind == "slider" and item.group and item.group not in groups:
                groups.append(item.group)
        return groups

    def _group_color(self, name: str) -> str:
        """组配色：优先用手动选择的颜色，否则按调色板自动分配一个没用过的。"""
        if name not in self._group_colors:
            used = set(self._group_colors.values())
            color = GROUP_COLORS[len(self._group_colors) % len(GROUP_COLORS)]
            for candidate in GROUP_COLORS:
                if candidate not in used:
                    color = candidate
                    break
            self._group_colors[name] = color
        return self._group_colors[name]

    def _apply_group_styles(self) -> None:
        """同组滑块使用统一配色的卡片与滑轨，便于区分不同组。"""
        for item in self._command_widgets():
            grouped = item.kind == "slider" and bool(item.group)
            item.set_group_color(self._group_color(item.group) if grouped else None)

    def _group_members(self, item: CommandItem) -> list[CommandItem]:
        """同一组的滑动条，按界面添加顺序打包。"""
        if item.kind != "slider" or not item.group:
            return [item]
        members = [
            w
            for w in self._command_widgets()
            if w.kind == "slider" and w.group == item.group
        ]
        return members or [item]

    def _build_add_menu(self, parent=None) -> QMenu:
        menu = QMenu(parent or self)
        menu.addAction("新增固定命令", lambda: self.add_command("fixed"))
        menu.addAction("新增滑动条", lambda: self.add_command("slider"))
        menu.addSeparator()
        for count in (2, 3, 4):
            menu.addAction(
                f"新增滑块组（{count} 个）",
                lambda _=False, n=count: self.add_slider_group(count=n),
            )
        return menu

    def show_add_command_menu(self, pos=None) -> None:
        """命令区空白处右键：在鼠标位置弹出新增菜单。"""
        menu = self._build_add_menu(self)
        if not isinstance(pos, QPoint):
            pos = self.cmd_inner.mapToGlobal(QPoint(0, 0))
        menu.exec(pos)
        menu.deleteLater()

    def _update_command_hint(self) -> None:
        self.cmd_empty.setVisible(not self._command_widgets())

    def _next_auto_number(self, prefix: str, names: list[str] | None = None) -> int:
        """自动编号：优先补上被删掉留下的最小空号，避免「删了再加数字一直涨」。"""
        used: set[int] = set()
        pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
        source = names if names is not None else [
            item.title for item in self._command_widgets()
        ]
        for name in source:
            match = pattern.match((name or "").strip())
            if match:
                used.add(int(match.group(1)))
        index = 1
        while index in used:
            index += 1
        return index

    def add_command(
        self,
        kind: str = "fixed",
        content: str = "",
        title: str | None = None,
    ) -> CommandItem:
        """新增一条命令；名称留空时自动编号（补空号，不复用已占用的编号）。"""
        if kind == "slider":
            item = CommandItem("slider", title or f"滑块{self._next_auto_number('滑块')}", "")
        else:
            item = CommandItem("fixed", title or f"命令{self._next_auto_number('命令')}", content)
        item.send_requested.connect(self._on_command_send)
        item.remove_requested.connect(self._remove_command)
        item.edit_requested.connect(self._edit_command)
        item.groupRenameRequested.connect(self._rename_command_group)
        item.groupColorRequested.connect(self._set_command_group_color)
        self.cmd_layout.insertWidget(self.cmd_layout.indexOf(self.cmd_empty), item)
        self._update_command_hint()
        self._apply_group_styles()
        self._refresh_command_previews()
        return item

    def add_slider_group(
        self,
        count: int = 3,
        head_text: str = "",
        tail_text: str = "",
        group: str | None = None,
    ) -> None:
        """一次创建 N 个绑定到同一组的滑动条。"""
        if not group:
            existing = [
                item.group
                for item in self._command_widgets()
                if item.kind == "slider" and item.group
            ]
            group = f"组{self._next_auto_number('组', existing)}"
        for _ in range(count):
            item = self.add_command("slider")
            data = item.settings()
            data.update(
                {
                    "group": group,
                    "head_enabled": bool(head_text),
                    "head_text": head_text,
                    "tail_enabled": bool(tail_text),
                    "tail_text": tail_text,
                }
            )
            item.apply_settings(data)
        self._apply_group_styles()
        self._refresh_command_previews()
        self.statusBar().showMessage(f"已新增滑块组 {group}（{count} 个滑块）", 3000)

    def _edit_command(self, item: CommandItem) -> None:
        dialog = CommandDialog(
            item.settings(), self._command_groups(), self.hex_mode, self
        )
        if dialog.exec() != QDialog.Accepted:
            return
        item.apply_settings(dialog.values())
        if item.kind == "slider" and item.group:
            for member in self._group_members(item):
                if member is item:
                    continue
                data = member.settings()
                data.update(
                    {
                        "head_enabled": item.head_enabled,
                        "head_text": item.head_text,
                        "tail_enabled": item.tail_enabled,
                        "tail_text": item.tail_text,
                    }
                )
                member.apply_settings(data)
        self._apply_group_styles()
        self._refresh_command_previews()

    def _rename_command_group(self, item: CommandItem, name: str) -> None:
        """双击组徽标改名：同组所有滑块一起换成新组名。"""
        old = item.group
        name = name.strip()
        if not name or name == old:
            return
        for member in self._group_members(item):
            member.group = name
            member.refresh()
        self._apply_group_styles()
        self._refresh_command_previews()
        self.statusBar().showMessage(f"滑块组 {old} 已重命名为 {name}", 2500)

    def _set_command_group_color(self, item: CommandItem, color: str) -> None:
        """右键组徽标换色：整组滑块统一换色，空字符串表示恢复自动配色。"""
        name = item.group
        if not name:
            return
        if color:
            self._group_colors[name] = color
        else:
            self._group_colors.pop(name, None)
        self._apply_group_styles()
        self.statusBar().showMessage(
            f"滑块组 {name} " + ("已恢复自动配色" if not color else "配色已更新"), 2000
        )

    def _remove_command(self, item: CommandItem) -> None:
        """删除命令；属于滑块组时整组一起删除。"""
        targets = (
            self._group_members(item)
            if item.kind == "slider" and item.group
            else [item]
        )
        for member in targets:
            member.setParent(None)
            member.deleteLater()
        self._update_command_hint()
        QTimer.singleShot(0, self._after_command_change)
        if len(targets) > 1:
            self.statusBar().showMessage(
                f"已删除滑块组 {item.group}（{len(targets)} 个滑块）", 2500
            )

    def _after_command_change(self) -> None:
        self._apply_group_styles()
        self._refresh_command_previews()

    def _on_command_send(self, item: CommandItem) -> None:
        payload = self._command_frame(item)
        if not payload:
            return
        self.send_payload(payload)
        self._refresh_command_previews()

    def _command_frame(self, item: CommandItem, silent: bool = False) -> bytes:
        """按“头帧 + 数据 + 尾帧”拼出一帧；滑动条按组一起打包。"""
        try:
            if item.kind == "fixed":
                body = self._encode_command_content(item.content, silent)
                if body is None:
                    return b""
                return (
                    item.head_bytes(self.encoding)
                    + body
                    + item.tail_bytes(self.encoding)
                )
            members = self._group_members(item)
            head = members[0].head_bytes(self.encoding)
            tail = members[0].tail_bytes(self.encoding)
            body = b"".join(member.pack_payload() for member in members)
            return head + body + tail
        except ValueError:
            if not silent:
                QMessageBox.warning(
                    self,
                    "帧格式错误",
                    "头帧 / 尾帧或命令内容无法解析：请检查 hex: 写法的十六进制位数是否为偶数。",
                )
            return b""

    def _encode_command_content(self, text: str, silent: bool = False) -> bytes | None:
        if not text.strip():
            return b""
        stripped = text.strip()
        forced_hex = stripped.lower().startswith(("hex:", "x:"))
        try:
            if self.hex_mode or forced_hex:
                # Hex 模式也支持直接写文本：出现非十六进制字符时按文本编码发送
                return parse_frame_bytes(stripped, self.encoding)
            return text.encode(self.encoding, errors="replace")
        except ValueError:
            if not silent:
                QMessageBox.warning(
                    self,
                    "命令格式错误",
                    "hex: 前缀的十六进制位数需为偶数；普通内容可直接写 Hex（AA 55）或文本。",
                )
            return None

    def _refresh_command_previews(self) -> None:
        for item in self._command_widgets():
            item.set_preview(self._command_frame(item, silent=True).hex(" ").upper())

    # ================= 其它 =================
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if hasattr(self, "page_groups"):
            QTimer.singleShot(0, self._sync_variable_groups)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        if self.record_unlimited:
            for page in self.pages:
                page.clear_data()
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.stop()
        if hasattr(self, "display_panel"):
            self.display_panel.close_all_float_windows()
        super().closeEvent(event)


def main(
    app: QApplication | None = None,
    splash: "SplashScreen | None" = None,
    run_loop: bool = True,
) -> None:
    """启动主窗口；splash 由轻量入口创建并传入，构造完成后淡出。"""
    own_app = app is None
    if own_app:
        app = QApplication(sys.argv)
    app.setApplicationName("VOFA+ Flash")
    app.setWindowIcon(app_icon())
    base_font = QFont("Microsoft YaHei UI")
    base_font.setPointSize(9)
    app.setFont(base_font)
    app.setStyleSheet(app_style(load_dark_setting()))
    window = MainWindow()
    window.show()
    if splash is not None:
        splash.finish(window)
    if own_app or run_loop:
        sys.exit(app.exec())
