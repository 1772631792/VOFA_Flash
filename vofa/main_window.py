"""VOFA+ Flash 主窗口：状态编排、数据流与业务入口。"""
from __future__ import annotations
import sys
if __package__ in (None, ""):
    print("请用项目根目录的 main.py 启动：python main.py（不要直接运行子模块）")
    sys.exit(1)
import csv
import json
import math
import random
import re
import struct
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
from .constants import DEMO_CHANNELS, ENGINES, INTERFACES, apply_dark_titlebar
from .settings import (
    load_dark_setting, load_setting, save_dark_setting, save_setting,
)
from . import __version__ as VERSION
from .command_panel import (
    CRC_MODES,
    CommandDialog,
    CommandItem,
    CustomGroupDialog,
    crc_bytes,
    dtype_limits,
    parse_frame_bytes,
)
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
from .mixins import (
    CommandsMixin,
    PlotsMixin,
    ProfileMixin,
    SignalsMixin,
    SimulationMixin,
    TransportMixin,
)

if TYPE_CHECKING:
    from .splash import SplashScreen


class MainWindow(
    SimulationMixin,
    CommandsMixin,
    ProfileMixin,
    SignalsMixin,
    TransportMixin,
    PlotsMixin,
    QMainWindow,
):
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
        self.sim_mode = "sine"  # 每次启动固定从正弦（三角函数）开始，PID 需手动设定
        self.measure_dialog: MeasureDialog | None = None
        self._demo_step_period_ms = 4000.0
        self._demo_last_step_ms = 0.0
        self._pid_gains = (2.5, 0.3, 0.25)  # P / I / D：默认留可见超调，D 调大可压掉
        self._last_pid_gains = self._pid_gains
        self._pid_target = 1.0  # 设定值，由 PID 组的“目标”滑块驱动
        self._last_pid_target: float | None = None
        self._pid_group = "PID"
        self._pid_states = [self._new_pid_state(ch) for ch in range(DEMO_CHANNELS)]
        self.record_unlimited = True  # 默认一直记录，视图只跟随最新窗口
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
        add_btn.setToolTip("新增固定命令 / 滑动条 / 滑块组 / 自建滑动组（含 CRC）")
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
            "暂无命令\n点击右上角 + 新增固定命令、滑动条或自建滑动组", "emptyHint"
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
            "Auto：自动适配 X/Y 轴范围（滚轮缩放只改宽度仍跟随，拖动冻结，双击波形恢复）"
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
