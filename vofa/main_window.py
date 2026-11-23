"""VOFA+ Flash 1.0 外观复刻：波形主界面（参考 vofa_demo 布局）。"""

from __future__ import annotations

import csv
import math
import re
import struct
import time

import serial.tools.list_ports
from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .command_panel import CommandDialog, CommandItem, parse_hex_bytes
from .icons import app_icon, icon
from .plot_widget import MAX_CHANNELS, PlotPage
from .protocol import JustFloatParser
from .serial_worker import SerialWorker
from .theme import APP_STYLE, CHANNEL_COLORS, GROUP_COLORS
from .transport import (
    BaseTransport,
    TcpClientTransport,
    TcpServerTransport,
    UdpTransport,
)

ENGINES = ["JustFloat", "RawData"]
INTERFACES = ["模拟模式", "串口", "UDP", "TCP客户端", "TCP服务端"]


def vbox(margins=(0, 0, 0, 0), spacing=8):
    lay = QVBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def hbox(margins=(0, 0, 0, 0), spacing=8):
    lay = QHBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def make_label(text: str, name: str | None = None, align=None) -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    if align is not None:
        w.setAlignment(align)
    return w


def make_hr() -> QFrame:
    w = QFrame()
    w.setFixedHeight(1)
    w.setStyleSheet("background:#e8edf4;border:0px;")
    return w


class ChannelRow(QWidget):
    """右侧通道行：可见性勾选 + 名称 + 实时值。"""

    toggled = Signal(int, bool)
    selected = Signal(int)
    editRequested = Signal(int)
    contextMenuRequested = Signal(int, object)

    def __init__(self, index: int, color: str, parent=None):
        super().__init__(parent)
        self.index = index
        self.color = color
        self._selected = False

        self.eye = QCheckBox()
        self.eye.setChecked(True)
        self.eye.setFixedWidth(22)
        self.eye.toggled.connect(lambda on: self.toggled.emit(self.index, on))

        self.name = QLabel(f"I{index}")
        self.name.setStyleSheet(f"font-weight:800;color:{color};")

        self.value = QLabel("0.000")
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value.setStyleSheet(
            f"font-family:Consolas;font-weight:700;color:{color};"
        )

        lay = hbox((8, 3, 8, 3), 8)
        lay.addWidget(self.eye)
        lay.addWidget(self.name)
        lay.addStretch(1)
        lay.addWidget(self.value)
        self.setLayout(lay)
        self._apply_style()

    def _apply_style(self) -> None:
        bg = "#F1F6FF" if self._selected else "transparent"
        border = "1px solid #CFE0F8" if self._selected else "1px solid transparent"
        self.setStyleSheet(
            f"QWidget{{background:{bg};border:{border};border-radius:7px;}}"
        )

    def set_value(self, text: str) -> None:
        self.value.setText(text)

    def set_name(self, name: str) -> None:
        self.name.setText(name)

    def set_color(self, color: str) -> None:
        self.color = color
        self.name.setStyleSheet(f"font-weight:800;color:{color};")
        self.value.setStyleSheet(
            f"font-family:Consolas;font-weight:700;color:{color};"
        )

    def set_selected(self, on: bool) -> None:
        if self._selected == on:
            return
        self._selected = on
        self._apply_style()

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.selected.emit(self.index)
        self.editRequested.emit(self.index)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.selected.emit(self.index)
        self.contextMenuRequested.emit(self.index, event.globalPos())
        event.accept()


class VariableDialog(QDialog):
    """添加/编辑变量：名称 + 曲线颜色。"""

    def __init__(
        self,
        title: str,
        name: str,
        color: str,
        gain: float = 1.0,
        offset: float = 0.0,
        decimals: int = 3,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        self._color = color

        lay = vbox((18, 16, 18, 16), 12)
        lay.addWidget(make_label("变量名称", "sectionBlue"))
        self.name_edit = QLineEdit(name)
        self.name_edit.selectAll()
        lay.addWidget(self.name_edit)

        lay.addWidget(make_label("曲线颜色", "sectionBlue"))
        colors = hbox(spacing=6)
        self.color_buttons: list[QPushButton] = []
        for item in CHANNEL_COLORS:
            btn = QPushButton()
            btn.setFixedSize(26, 26)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, c=item: self.select_color(c))
            self.color_buttons.append(btn)
            colors.addWidget(btn)
        colors.addStretch(1)
        lay.addLayout(colors)
        self.select_color(color)

        lay.addWidget(make_hr())
        lay.addWidget(make_label("变量参数", "sectionBlue"))

        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(-1000, 1000)
        self.gain_spin.setDecimals(3)
        self.gain_spin.setSingleStep(0.1)
        self.gain_spin.setValue(gain)
        self.gain_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)

        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-100000, 100000)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setSingleStep(0.1)
        self.offset_spin.setValue(offset)
        self.offset_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)

        self.decimals_spin = QSpinBox()
        self.decimals_spin.setRange(0, 6)
        self.decimals_spin.setValue(decimals)
        self.decimals_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)

        for text, widget in (
            ("增益", self.gain_spin),
            ("偏置", self.offset_spin),
            ("小数位", self.decimals_spin),
        ):
            row = hbox(spacing=10)
            lab = make_label(text)
            lab.setFixedWidth(56)
            row.addWidget(lab)
            row.addWidget(widget, 1)
            lay.addLayout(row)

        buttons = hbox(spacing=8)
        buttons.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("确定")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self.accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)
        lay.addLayout(buttons)
        self.setLayout(lay)

    def select_color(self, color: str) -> None:
        self._color = color
        for btn, item in zip(self.color_buttons, CHANNEL_COLORS):
            border = "#1F67C7" if item == color else "transparent"
            btn.setStyleSheet(
                f"QPushButton{{background:{item};border:2px solid {border};"
                "border-radius:6px;padding:0px;}}"
            )

    def values(self) -> tuple[str, str, float, float, int]:
        return (
            self.name_edit.text().strip(),
            self._color,
            self.gain_spin.value(),
            self.offset_spin.value(),
            self.decimals_spin.value(),
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VOFA+ Flash 1.0")
        self.setWindowIcon(app_icon())
        self.resize(1480, 900)
        self.setMinimumSize(1180, 760)

        # ---- 运行时状态 ----
        self.engine_name = "JustFloat"
        self.interface_name = "串口"
        self.worker: SerialWorker | BaseTransport | None = None
        self.connected = False
        self.demo_enabled = False
        self.channel_names = [f"I{i}" for i in range(MAX_CHANNELS)]
        self.channel_colors = list(CHANNEL_COLORS)
        self.channel_decimals = [3] * MAX_CHANNELS
        self.total_frames = 0
        self.sample_index = 0
        self.dt_ms = 1.0
        self.channel_count = 0
        self.last_values = [0.0] * MAX_CHANNELS
        self.gains = [1.0] * MAX_CHANNELS
        self.offsets = [0.0] * MAX_CHANNELS
        self.selected_channel = 0
        self.mouse_adjust = False
        self.hex_mode = True
        self.filter_rx = False
        self.filter_tx = False
        self.stamp_log = False
        self.log_lines: list[tuple[str, str]] = []
        self.justfloat = JustFloatParser()
        self.rx_line_buffer = bytearray()
        self.raw_frame_bytes = bytearray()
        self._last_value_log = 0.0
        self._last_raw_log = 0.0
        self._log_font_size = 13
        self._demo_acc = 0.0
        self.encoding = "utf-8"
        self.serial_bits = 8
        self.serial_parity = "None"
        self.serial_stopbits = 1
        self.serial_flow = "None"
        self.bytes_total = 0
        self._rate_bytes = 0
        self._rate_frames = 0
        self._rate_start = time.monotonic()
        self._cmd_seq = 0
        self._slider_seq = 0
        self._group_seq = 0
        self._data_collapsed = False
        self._right_width = 250
        self._group_colors: dict[str, str] = {}

        self.build_ui()
        self.refresh_ports()
        self.iface_combo.setCurrentIndex(INTERFACES.index("模拟模式"))
        self.on_iface_changed("模拟模式")
        self._select_channel(0)
        self._update_channel_rows()

        self.statusBar().showMessage(
            "就绪 · 已进入模拟模式，点击右上角「模拟模式」运行模拟数据，命令随时可发"
        )

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(30)

        self.port_timer = QTimer(self)
        self.port_timer.timeout.connect(lambda: self.refresh_ports(silent=True))
        self.port_timer.start(3000)

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
        center_right.addWidget(self.build_center_area())
        center_right.addWidget(self.build_rightbar())
        center_right.setSizes([1100, 250])
        center_right.setStretchFactor(0, 1)
        center_right.setStretchFactor(1, 0)
        self.center_splitter = center_right

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(4)
        body.addWidget(self.build_rail())
        self.drawer = self.build_command_drawer()
        body.addWidget(self.drawer)
        body.addWidget(center_right)
        body.setSizes([48, 300, 1130])
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 0)
        body.setStretchFactor(2, 1)
        self.body_splitter = body

        root_l.addWidget(body, 1)

        for btn in self.findChildren(QToolButton):
            if btn.objectName() != "railBtn":
                btn.setIconSize(QSize(18, 18))

    def build_topbar(self) -> QWidget:
        top = QFrame()
        top.setObjectName("topbar")
        top.setFixedHeight(62)
        lay = hbox((14, 0, 12, 0), 10)

        lay.addWidget(make_label("VOFA+ Flash 1.0", "brand"))
        lay.addWidget(make_label("|", "muted"))

        lay.addWidget(make_label("数据引擎", "muted"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(ENGINES)
        self.engine_combo.setFixedWidth(122)
        self.engine_combo.currentTextChanged.connect(self.on_engine_changed)
        lay.addWidget(self.engine_combo)

        lay.addWidget(make_label("接口", "muted"))
        self.iface_combo = QComboBox()
        self.iface_combo.addItems(INTERFACES)
        self.iface_combo.setFixedWidth(112)
        self.iface_combo.currentTextChanged.connect(self.on_iface_changed)
        lay.addWidget(self.iface_combo)

        # 串口参数
        serial_page = QWidget()
        sp = hbox(spacing=8)
        self.port_combo = QComboBox()
        self.port_combo.setFixedWidth(128)
        sp.addWidget(self.port_combo)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedWidth(64)
        self.refresh_btn.setToolTip("刷新串口列表（也会每 3 秒自动检测）")
        self.refresh_btn.clicked.connect(lambda: self.refresh_ports())
        sp.addWidget(self.refresh_btn)
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(
            ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]
        )
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setFixedWidth(108)
        sp.addWidget(self.baud_combo)

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

        # 网络参数
        net_page = QWidget()
        np_lay = hbox(spacing=8)
        self.net_host_edit = QLineEdit("127.0.0.1")
        self.net_host_edit.setPlaceholderText("0.0.0.0")
        self.net_host_edit.setFixedWidth(140)
        np_lay.addWidget(self.net_host_edit)
        self.net_port_spin = QSpinBox()
        self.net_port_spin.setRange(1, 65535)
        self.net_port_spin.setValue(8886)
        self.net_port_spin.setFixedWidth(96)
        np_lay.addWidget(self.net_port_spin)
        net_page.setLayout(np_lay)

        # 模拟数据
        demo_page = QWidget()
        dp = hbox(spacing=8)
        self.demo_rate_spin = QSpinBox()
        self.demo_rate_spin.setRange(1, 2000)
        self.demo_rate_spin.setValue(500)
        self.demo_rate_spin.setSuffix(" Hz")
        self.demo_rate_spin.setFixedWidth(104)
        dp.addWidget(self.demo_rate_spin)
        self.demo_channels_spin = QSpinBox()
        self.demo_channels_spin.setRange(1, MAX_CHANNELS)
        self.demo_channels_spin.setValue(3)
        self.demo_channels_spin.setFixedWidth(72)
        dp.addWidget(self.demo_channels_spin)
        demo_page.setLayout(dp)

        for spin in (self.net_port_spin, self.demo_rate_spin, self.demo_channels_spin):
            spin.setButtonSymbols(QAbstractSpinBox.NoButtons)

        self.param_stack = QStackedWidget()
        self.param_stack.addWidget(serial_page)
        self.param_stack.addWidget(net_page)
        self.param_stack.addWidget(demo_page)
        lay.addWidget(self.param_stack)

        self.link_btn = QPushButton("连接")
        self.link_btn.setObjectName("primary")
        self.link_btn.setFixedWidth(76)
        self.link_btn.setToolTip("连接 / 断开接口；模拟模式下用于开始 / 暂停模拟数据流")
        self.link_btn.clicked.connect(self.toggle_link)
        lay.addWidget(self.link_btn)

        lay.addStretch(1)

        self.mode_tag = QPushButton("● 模拟模式")
        self.mode_tag.setObjectName("primary")
        self.mode_tag.setFixedWidth(112)
        self.mode_tag.setToolTip("点击开始 / 暂停模拟数据流")
        self.mode_tag.clicked.connect(self.toggle_demo)
        lay.addWidget(self.mode_tag)

        shot_btn = QPushButton("截图")
        shot_btn.clicked.connect(self.save_screenshot)
        lay.addWidget(shot_btn)

        clear_btn = QPushButton("清空波形")
        clear_btn.clicked.connect(self.clear_plot)
        lay.addWidget(clear_btn)

        top.setLayout(lay)
        return top

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

        lay.addStretch(1)

        rail.setLayout(lay)
        return rail

    def build_command_drawer(self) -> QWidget:
        drawer = QFrame()
        drawer.setObjectName("drawer")
        drawer.setMinimumWidth(236)
        drawer.setMaximumWidth(430)

        main = vbox((14, 12, 14, 12), 10)
        head = hbox(spacing=8)
        head.addWidget(make_label("命令", "titleBlue"))
        head.addStretch(1)
        add_btn = QToolButton()
        add_btn.setObjectName("addCmd")
        add_btn.setIcon(icon("plus", 18, "#4B6078"))
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

        self.plot_stack = QStackedWidget()
        self.plot_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        plot_l.addWidget(self.plot_stack, 1)

        self.pages: list[PlotPage] = []

        # 信息栏
        self.info_bar = QWidget()
        info_l = hbox((10, 8, 10, 8), 12)
        self.dt_spin = QDoubleSpinBox()
        self.dt_spin.setRange(0.01, 10000)
        self.dt_spin.setDecimals(2)
        self.dt_spin.setValue(1.0)
        self.dt_spin.setFixedWidth(96)
        self.dt_spin.valueChanged.connect(self.on_dt_changed)

        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(1000, 500000)
        self.buffer_spin.setSingleStep(1000)
        self.buffer_spin.setValue(50000)
        self.buffer_spin.setFixedWidth(110)
        self.buffer_spin.valueChanged.connect(self.on_buffer_changed)

        self.align_spin = QSpinBox()
        self.align_spin.setRange(100, 10000)
        self.align_spin.setValue(1200)
        self.align_spin.setFixedWidth(96)
        self.align_spin.valueChanged.connect(self.on_align_changed)
        for spin in (self.dt_spin, self.buffer_spin, self.align_spin):
            spin.setButtonSymbols(QAbstractSpinBox.NoButtons)

        info_l.addWidget(make_label("Δt:", "sectionBlue"))
        info_l.addWidget(self.dt_spin)
        info_l.addWidget(make_label("ms"))
        info_l.addSpacing(10)
        info_l.addWidget(make_label("缓冲区上限:", "sectionBlue"))
        info_l.addWidget(self.buffer_spin)
        info_l.addWidget(make_label("/ch"))
        info_l.addSpacing(10)
        info_l.addWidget(make_label("Auto点数对齐:", "sectionBlue"))
        info_l.addWidget(self.align_spin)
        info_l.addStretch(1)

        self.auto_label = QPushButton("Auto")
        self.auto_label.setObjectName("autoBtn")
        self.auto_label.setStyleSheet(
            "QPushButton#autoBtn {"
            "  font-size:17px; font-style:italic; font-weight:800;"
            "  color:#9AA8B8; background:transparent; border:1px solid transparent;"
            "  border-radius:7px; padding:2px 12px;"
            "}"
            "QPushButton#autoBtn:hover { color:#2D7EF1; background:#EEF5FF; }"
            "QPushButton#autoBtn:checked {"
            "  color:#2D7EF1; background:#E8F1FF; border-color:#CFE0F8;"
            "}"
        )
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
        del_btn.setIcon(icon("trash", 18, "#7B8798"))
        del_btn.setToolTip("清空波形")
        del_btn.clicked.connect(self.clear_plot)
        stat_l.addWidget(del_btn)

        self.rx_count_label = make_label("0", "muted")
        self.cur_index_label = QLabel("0")
        self.cur_index_label.setStyleSheet(
            "color:#11B6BF;font-family:Consolas;font-size:13px;font-weight:700;"
        )
        self.scale_label = QLabel("0ms/X-div")
        self.scale_label.setStyleSheet(
            "color:#276DD7;font-family:Consolas;font-size:13px;font-weight:700;"
        )
        stat_l.addWidget(self.rx_count_label)
        stat_l.addWidget(make_label("/ 0", "muted"))
        stat_l.addWidget(make_label("|", "muted"))
        stat_l.addWidget(self.cur_index_label)
        stat_l.addWidget(self.scale_label)

        self.rate_label = QLabel("0 KB/s")
        self.rate_label.setStyleSheet(
            "color:#7B8798;font-family:Consolas;font-size:12px;"
        )
        self.rate_label.setToolTip("接收吞吐与帧率")
        stat_l.addWidget(self.rate_label)
        stat_l.addStretch(1)

        self.csv_btn = QToolButton()
        self.csv_btn.setObjectName("flatTool")
        self.csv_btn.setIcon(icon("docs", 18, "#4B6078"))
        self.csv_btn.setToolTip("导出曲线数据（CSV）")
        self.csv_btn.clicked.connect(self.export_csv)
        stat_l.addWidget(self.csv_btn)

        self.img_btn = QToolButton()
        self.img_btn.setObjectName("flatTool")
        self.img_btn.setIcon(icon("layers", 18, "#4B6078"))
        self.img_btn.setToolTip("导出曲线图片（PNG）")
        self.img_btn.clicked.connect(self.save_screenshot)
        stat_l.addWidget(self.img_btn)

        self.more_btn = QToolButton()
        self.more_btn.setObjectName("flatTool")
        self.more_btn.setIcon(icon("more", 18, "#4B6078"))
        self.more_btn.setToolTip("更多")
        self.more_btn.clicked.connect(self.show_variable_menu)
        stat_l.addWidget(self.more_btn)

        self.stat_bar.setLayout(stat_l)
        plot_l.addWidget(self.stat_bar)

        # Auto 按钮就绪后再建波形页，保证页面的 Auto 状态与之同步
        self._create_page()

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
        self.btn_ascii = QPushButton("Abc")
        self.btn_ascii.setObjectName("flatTool")
        self.btn_ascii.setCheckable(True)
        self.btn_ascii.setToolTip("文本发送模式")
        self.btn_ascii.clicked.connect(lambda: self.set_hex_mode(False))
        tools.addWidget(self.btn_ascii)

        clear_log_btn = QToolButton()
        clear_log_btn.setObjectName("flatTool")
        clear_log_btn.setIcon(icon("trash", 20, "#4B6078"))
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
        save_log_btn.setIcon(icon("docs", 20, "#4B6078"))
        save_log_btn.setIconSize(QSize(20, 20))
        save_log_btn.setToolTip("保存接收日志")
        save_log_btn.clicked.connect(self.save_log)
        tools.addWidget(save_log_btn)

        focus_btn = QToolButton()
        focus_btn.setObjectName("flatTool")
        focus_btn.setIcon(icon("settings", 20, "#4B6078"))
        focus_btn.setIconSize(QSize(20, 20))
        focus_btn.setToolTip("聚焦发送框")
        focus_btn.clicked.connect(lambda: self.tx_edit.setFocus())
        tools.addWidget(focus_btn)
        lay.addLayout(tools)

        self.rx_text = QPlainTextEdit()
        self.rx_text.setReadOnly(True)
        self.rx_text.setPlaceholderText("这里显示接收日志 / 解析结果 / RawData 十六进制数据……")
        self.rx_text.setMinimumHeight(118)
        self.rx_text.setMaximumBlockCount(4000)
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
        lay = vbox((14, 14, 14, 14), 8)

        head = hbox(spacing=8)
        head.addWidget(make_label("◔", "muted"))
        head.addWidget(make_label("数据", "titleBlue"))
        head.addStretch(1)
        self.right_more = QToolButton()
        self.right_more.setObjectName("flatTool")
        self.right_more.setIcon(icon("more", 18, "#7B8798"))
        self.right_more.setToolTip("变量与显示设置")
        self.right_more.clicked.connect(self.show_variable_menu)
        head.addWidget(self.right_more)

        self.right_collapse = QToolButton()
        self.right_collapse.setObjectName("panelBtn")
        self.right_collapse.setIcon(icon("curve", 18, "#2D7EF1"))
        self.right_collapse.setIconSize(QSize(18, 18))
        self.right_collapse.setToolTip("收起数据栏")
        self.right_collapse.clicked.connect(lambda: self.set_data_panel_collapsed(True))
        head.addWidget(self.right_collapse)
        lay.addLayout(head)
        lay.addWidget(make_hr())

        self.channel_rows: list[ChannelRow] = []
        for i in range(MAX_CHANNELS):
            row = ChannelRow(i, CHANNEL_COLORS[i])
            row.toggled.connect(self.on_channel_toggled)
            row.selected.connect(self._select_channel)
            row.editRequested.connect(self.edit_variable)
            row.contextMenuRequested.connect(self._show_variable_menu_at)
            row.setVisible(False)
            self.channel_rows.append(row)
            lay.addWidget(row)

        self.empty_hint = make_label(
            "暂无变量\n接收到数据后会自动显示变量", "emptyHint"
        )
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        lay.addWidget(self.empty_hint)
        lay.addStretch(1)
        self.right_body.setLayout(lay)
        outer.addWidget(self.right_body, 1)

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
            self.right_body.setVisible(False)
            self.right_strip.setVisible(True)
            self.right_panel.setMinimumWidth(48)
            self.right_panel.setMaximumWidth(48)
            splitter.setSizes([max(200, total - 48), 48])
        else:
            self.right_strip.setVisible(False)
            self.right_body.setVisible(True)
            self.right_panel.setMinimumWidth(190)
            self.right_panel.setMaximumWidth(400)
            width = max(190, min(400, self._right_width))
            splitter.setSizes([max(200, total - width), width])

    # ================= 波形页 =================
    def current_page(self) -> PlotPage:
        widget = self.plot_stack.currentWidget()
        if isinstance(widget, PlotPage):
            return widget
        return self.pages[0]

    def _create_page(self) -> None:
        page = PlotPage()
        page.set_adjust_mode(self.mouse_adjust)
        page.set_channel_count(self.channel_count)
        page.set_auto_scale(
            self.auto_label.isChecked() if hasattr(self, "auto_label") else True
        )
        page.gainChanged.connect(self._on_drag_gain)
        page.offsetChanged.connect(self._on_drag_offset)
        page.autoScaleRequested.connect(self.auto_label.setChecked)
        page.contextMenuRequested.connect(
            lambda pos, target=page: self._show_plot_menu_at(target, pos)
        )
        for i in range(MAX_CHANNELS):
            page.set_channel_color(i, self.channel_colors[i])
            page.set_channel_name(i, self.channel_names[i])
        self.pages.append(page)
        self.plot_stack.addWidget(page)
        self.plot_stack.setCurrentWidget(page)

    def _show_plot_menu_at(self, page: PlotPage, global_pos) -> None:
        """波形区右键菜单：添加变量、变量设置、显示曲线、Auto、导出、清空。"""
        menu = self._build_variable_menu()
        menu.addSeparator()
        auto_act = menu.addAction("Auto 自动量程")
        auto_act.setCheckable(True)
        auto_act.setChecked(self.auto_label.isChecked())
        auto_act.toggled.connect(self.auto_label.setChecked)
        menu.exec(global_pos)

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
            page.set_visible(index, True)
        row = self.channel_rows[index]
        row.set_name(name)
        row.set_color(color)
        row.eye.setChecked(True)

    def show_variable_menu(self) -> None:
        pos = self.right_more.mapToGlobal(QPoint(0, self.right_more.height()))
        self._build_variable_menu().exec(pos)

    def _show_variable_menu_at(self, index: int, global_pos) -> None:
        self._select_channel(index)
        self._build_variable_menu(index).exec(global_pos)

    def _build_variable_menu(self, index: int | None = None) -> QMenu:
        menu = QMenu(self)
        vis_menu = QMenu("显示变量", menu)
        menu.addMenu(vis_menu)
        for i in range(self.channel_count):
            act = vis_menu.addAction(self.channel_names[i])
            act.setCheckable(True)
            act.setChecked(self.channel_rows[i].eye.isChecked())
            act.toggled.connect(
                lambda on, idx=i: self.channel_rows[idx].eye.setChecked(on)
            )
        vis_menu.setEnabled(self.channel_count > 0)

        target = self.selected_channel if index is None else index
        edit_act = menu.addAction("变量设置…", lambda: self.edit_variable(target))
        edit_act.setEnabled(0 <= target < self.channel_count)

        adjust_act = menu.addAction("鼠标调整模式")
        adjust_act.setCheckable(True)
        adjust_act.setChecked(self.mouse_adjust)
        adjust_act.toggled.connect(self.set_mouse_adjust)

        menu.addSeparator()
        menu.addAction("导出数据 CSV…", self.export_csv)
        menu.addAction("导出图片 PNG…", self.save_screenshot)
        menu.addAction("清空波形", self.clear_plot)
        return menu

    # ================= 数据源 =================
    def on_tick(self) -> None:
        if self.demo_enabled:
            self.generate_demo_data()
        self.update_plot()

    def update_plot(self) -> None:
        page = self.current_page()
        page.refresh()
        self.update_stats(page)
        self._refresh_channel_values()
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
        self.cur_index_label.setText(str(self.sample_index))
        span = page.time_span_ms()
        per_div = max(1.0, span / 8.0)
        self.scale_label.setText(f"{per_div:.0f}ms/X-div")

    def generate_demo_data(self) -> None:
        rate = max(1, self.demo_rate_spin.value())
        channels = max(1, min(self.demo_channels_spin.value(), MAX_CHANNELS))
        per_frame = rate / 30.0
        frames = int(per_frame) + (1 if self._demo_remainder_add(per_frame) else 0)
        if frames <= 0:
            return
        t0 = self.sample_index * self.dt_ms / 1000.0
        step = self.dt_ms / 1000.0
        for k in range(frames):
            t = t0 + k * step
            values = []
            for ch in range(channels):
                freq = 0.8 + ch * 0.5
                phase = ch * 0.9
                values.append(
                    2.0 * math.sin(2 * math.pi * freq * t + phase)
                    + 0.18 * math.sin(2 * math.pi * 9.0 * t)
                    + ch * 0.6
                )
            self.append_values(values, from_demo=True)

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
        if not from_demo and self.engine_name == "JustFloat":
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
                    "[raw] " + preview.hex(" ").upper() + suffix, kind="rx"
                )
            self.parse_rawdata(chunk)
            return
        if self.looks_like_ascii(chunk):
            self.rx_line_buffer.extend(chunk)
            while b"\n" in self.rx_line_buffer:
                line, _, rest = self.rx_line_buffer.partition(b"\n")
                self.rx_line_buffer = bytearray(rest)
                text = line.decode(errors="ignore").strip().replace("\r", "")
                if not text:
                    continue
                values = self.parse_ascii_float_line(text)
                if values:
                    self.log_rx(text, kind="rx")
                    self.append_values(values)
        else:
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
        size = self._log_font_size
        self.rx_text.setStyleSheet(
            "QPlainTextEdit{background:#FFFFFF;color:#364A61;border:0px;"
            "selection-background-color:#C6DCFF;"
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
        if self.worker is not None:
            self._disconnect()
        self.interface_name = name
        self._reset_variables(reset_style=True)
        self._sync_param_panel(name)
        if name == "模拟模式":
            self.demo_enabled = False
            self._set_link_state(False)
            self.mode_tag.setText("● 模拟模式")
            self.mode_tag.setObjectName("primary")
            self.statusBar().showMessage(
                "已进入模拟模式：点击右上角「模拟模式」或顶栏「开始」运行模拟数据", 4000
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

    def toggle_demo(self) -> None:
        """右上角按钮：只在「模拟模式 / 模拟中」之间切换，始终不显示串口。"""
        if self.interface_name != "模拟模式":
            self.iface_combo.setCurrentText("模拟模式")
            if not self.demo_enabled:
                self._toggle_demo_stream()
            return
        self._toggle_demo_stream()

    def toggle_command_drawer(self) -> None:
        if self.drawer.isVisible():
            self._drawer_width = max(220, self.drawer.width())
            self.drawer.setVisible(False)
            self.btn_cmd.setChecked(False)
        else:
            self.drawer.setVisible(True)
            width = getattr(self, "_drawer_width", 300)
            total = max(self.body_splitter.width(), 48 + width + 400)
            self.body_splitter.setSizes([48, width, total - 48 - width])
            self.btn_cmd.setChecked(True)

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
        menu.addAction("恢复默认 8N1", self._reset_serial_fmt)

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
            self._disconnect()
            self.statusBar().showMessage("已断开连接", 3000)
            return
        self._connect()

    def _toggle_demo_stream(self) -> None:
        """模拟模式：连接按钮控制模拟数据流启停，发送命令不受影响。"""
        self.demo_enabled = not self.demo_enabled
        self._set_link_state(self.demo_enabled)
        if self.demo_enabled:
            self.mode_tag.setText("● 模拟中")
            self.mode_tag.setObjectName("green")
            self.statusBar().showMessage("模拟模式运行中，可发送命令", 3000)
        else:
            self.mode_tag.setText("● 模拟模式")
            self.mode_tag.setObjectName("primary")
            self._reset_variables(reset_style=True)
            self.statusBar().showMessage("模拟模式数据流已暂停，仍可发送命令", 3000)
        self.mode_tag.style().polish(self.mode_tag)

    def _set_link_state(self, connected: bool) -> None:
        self.connected = bool(connected)
        demo = self.interface_name == "模拟模式"
        if connected:
            self.link_btn.setText("暂停" if demo else "断开")
            self.link_btn.setObjectName("danger")
            self.link_btn.setStyleSheet("QPushButton{color:#C74B5C;font-weight:700;}")
        else:
            self.link_btn.setText("开始" if demo else "连接")
            self.link_btn.setObjectName("primary")
            self.link_btn.setStyleSheet("")

    def _connect(self) -> None:
        name = self.interface_name
        worker: SerialWorker | BaseTransport
        if name == "串口":
            port = self.port_combo.currentText().strip()
            if not port:
                QMessageBox.warning(self, "参数错误", "请选择串口端口")
                return
            try:
                baud = int(self.baud_combo.currentText().strip())
            except ValueError:
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
        self.justfloat.reset()
        self.rx_line_buffer.clear()
        self.raw_frame_bytes.clear()
        self.mode_tag.setText("● 已连接")
        self.mode_tag.setObjectName("primary")
        self.mode_tag.style().polish(self.mode_tag)
        self.log_rx(f"[link] {self.interface_name} 已连接", kind="tx")
        self.statusBar().showMessage(f"{self.interface_name} 已连接", 4000)

    @Slot()
    def on_disconnected(self) -> None:
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

    @Slot(str)
    def on_error(self, message: str) -> None:
        self.log_rx(f"[error] {message}", kind="tx")
        QMessageBox.warning(self, "接口错误", message)
        self._disconnect()

    # ================= 发送 =================
    def on_tx_mode_toggled(self, checked: bool) -> None:
        self.hex_mode = checked
        self.tx_mode_btn.setText("Hex" if checked else "Ascii")
        self.btn_ascii.setChecked(not checked)
        self.statusBar().showMessage(
            "发送格式：Hex" if checked else "发送格式：文本(Abc)", 2000
        )

    def set_hex_mode(self, enabled: bool) -> None:
        self.tx_mode_btn.setChecked(enabled)

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

    # ================= 波形 / 通道 =================
    def clear_plot(self) -> None:
        self.total_frames = 0
        self.sample_index = 0
        self.raw_frame_bytes.clear()
        self.rx_line_buffer.clear()
        self._demo_acc = 0.0
        self._reset_variables()
        self.update_stats(self.current_page())
        self.statusBar().showMessage("波形已清空", 3000)

    def save_screenshot(self, path: str | bool | None = None) -> None:
        if not isinstance(path, str):
            path, _ = QFileDialog.getSaveFileName(
                self, "导出曲线图片", "waveform.png", "PNG 图片 (*.png)"
            )
        if not path:
            return
        if self.current_page().grab().save(path):
            self.statusBar().showMessage(f"图片已保存：{path}", 4000)

    def export_csv(self, path: str | bool | None = None) -> None:
        """把当前波形页的缓冲数据导出为 CSV。"""
        page = self.current_page()
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

    def toggle_auto_scale(self, checked: bool) -> None:
        for page in self.pages:
            page.set_auto_scale(checked)
            page.refresh()

    def on_channel_toggled(self, index: int, visible: bool) -> None:
        for page in self.pages:
            page.set_visible(index, visible)
        self.update_plot()

    def _select_channel(self, index: int) -> None:
        if index < 0 or index >= MAX_CHANNELS:
            return
        self.selected_channel = index
        for row in self.channel_rows:
            row.set_selected(row.index == index and index < self.channel_count)

    def set_mouse_adjust(self, enabled: bool) -> None:
        self.mouse_adjust = bool(enabled)
        for page in self.pages:
            page.set_adjust_mode(self.mouse_adjust)
        self.statusBar().showMessage(
            "鼠标调整已开启：上下拖改增益，左右拖改偏置"
            if self.mouse_adjust
            else "鼠标调整已关闭",
            2500,
        )

    def toggle_mouse_adjust(self) -> None:
        self.set_mouse_adjust(not self.mouse_adjust)

    def _target_channel(self) -> int:
        if self.channel_count == 0:
            return -1
        return min(self.selected_channel, self.channel_count - 1)

    def _on_drag_gain(self, delta: int) -> None:
        index = self._target_channel()
        if index < 0:
            return
        self.gains[index] = round(self.gains[index] + delta * 0.05, 4)
        self.statusBar().showMessage(
            f"{self.channel_names[index]} 增益 {self.gains[index]:.2f}", 1200
        )

    def _on_drag_offset(self, delta: int) -> None:
        index = self._target_channel()
        if index < 0:
            return
        self.offsets[index] = round(self.offsets[index] + delta * 0.05, 4)
        self.statusBar().showMessage(
            f"{self.channel_names[index]} 偏置 {self.offsets[index]:.2f}", 1200
        )

    def _format_value(self, value: float, index: int = 0) -> str:
        digits = (
            self.channel_decimals[index]
            if 0 <= index < len(self.channel_decimals)
            else 3
        )
        return f"{value:.{digits}f}"

    def _update_channel_rows(self) -> None:
        for i, row in enumerate(self.channel_rows):
            visible = i < self.channel_count
            row.setVisible(visible)
            if visible:
                row.set_name(self.channel_names[i])
                row.set_color(self.channel_colors[i])
                row.set_value(self._format_value(self.last_values[i], i))
        self._update_empty_hint()

    def _refresh_channel_values(self) -> None:
        if not hasattr(self, "channel_rows"):
            return
        for i in range(min(self.channel_count, len(self.channel_rows))):
            self.channel_rows[i].set_value(self._format_value(self.last_values[i], i))

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
        if hasattr(self, "channel_rows"):
            for i, row in enumerate(self.channel_rows):
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

    def add_command(
        self,
        kind: str = "fixed",
        content: str = "",
        title: str | None = None,
    ) -> CommandItem:
        """新增一条命令；名称留空时自动编号。"""
        if kind == "slider":
            self._slider_seq += 1
            item = CommandItem("slider", title or f"滑块{self._slider_seq}", "")
        else:
            self._cmd_seq += 1
            item = CommandItem("fixed", title or f"命令{self._cmd_seq}", content)
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
        self._group_seq += 1
        group = group or f"组{self._group_seq}"
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
                return item.head_bytes() + body + item.tail_bytes()
            members = self._group_members(item)
            head = members[0].head_bytes()
            tail = members[0].tail_bytes()
            body = b"".join(member.pack_payload() for member in members)
            return head + body + tail
        except ValueError:
            if not silent:
                QMessageBox.warning(
                    self,
                    "帧格式错误",
                    "头帧 / 尾帧或命令内容不是合法的十六进制字节串。",
                )
            return b""

    def _encode_command_content(self, text: str, silent: bool = False) -> bytes | None:
        if not text.strip():
            return b""
        try:
            if self.hex_mode:
                return parse_hex_bytes(text)
            return text.encode(self.encoding, errors="replace")
        except ValueError:
            if not silent:
                QMessageBox.warning(
                    self,
                    "命令格式错误",
                    "当前为 Hex 模式，请输入正确的十六进制字节串。",
                )
            return None

    def _refresh_command_previews(self) -> None:
        for item in self._command_widgets():
            item.set_preview(self._command_frame(item, silent=True).hex(" ").upper())

    # ================= 其它 =================
    def closeEvent(self, event) -> None:
        self.timer.stop()
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.stop()
        super().closeEvent(event)


def main() -> None:
    import sys

    app = QApplication(sys.argv)
    app.setApplicationName("VOFA+ Flash")
    app.setWindowIcon(app_icon())
    app.setStyleSheet(APP_STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
