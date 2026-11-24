"""命令面板：固定命令、滑动条命令与多滑块组帧。

每条命令是一个 CommandItem，类型分两种：
* fixed  —— 发送一段固定内容（Hex 或文本）；
* slider —— 拖动滑动条发送数值，默认按 float32 小端打包。

多个滑动条填写相同的“组”名称后即绑定为一组，发送时按添加顺序
把各自数值连续打包，再拼上头帧 / 尾帧，得到下位机容易解析的一帧。
"""

from __future__ import annotations

import math
import re
import struct
import time

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import icon
from .theme import GROUP_COLOR_LABELS, GROUP_COLORS

# 数据类型 -> (struct 字符, 字节数)
_FMT: dict[str, tuple[str, int]] = {
    "float32": ("f", 4),
    "int32": ("i", 4),
    "uint32": ("I", 4),
    "int16": ("h", 2),
    "uint16": ("H", 2),
    "int8": ("b", 1),
    "uint8": ("B", 1),
}
DTYPE_NAMES = list(_FMT)


def dtype_size(dtype: str) -> int:
    return _FMT.get(dtype, _FMT["float32"])[1]


def dtype_limits(dtype: str) -> tuple[float, float]:
    fmt, size = _FMT.get(dtype, _FMT["float32"])
    if fmt == "f":
        return -1e9, 1e9
    bits = size * 8
    if fmt.isupper():
        return 0.0, float(2**bits - 1)
    return float(-(2 ** (bits - 1))), float(2 ** (bits - 1) - 1)


def parse_hex_bytes(text: str) -> bytes:
    """把 'AA 55'、'0xAA,0x55' 之类的写法解析为字节串。"""
    cleaned = re.sub(r"0[xX]", " ", text or "")
    cleaned = re.sub(r"[\s,,;;:_-]+", "", cleaned)
    if not cleaned:
        return b""
    if len(cleaned) % 2:
        raise ValueError("十六进制字节串长度必须为偶数")
    return bytes.fromhex(cleaned)


_ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "0": "\0",
    "\\": "\\",
    '"': '"',
    "'": "'",
}
_TEXT_PREFIXES = ("text:", "str:", "t:", "文本:")
_HEX_PREFIXES = ("hex:", "x:")


def _unescape(text: str) -> str:
    """把 '\\r\\n' 这类转义写法还原成真实字符，其它反斜杠保持原样。"""
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _strip_quotes(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def looks_like_hex(text: str) -> bool:
    """判断是否只由十六进制字符（可带分隔符）组成，且位数为偶数。"""
    cleaned = re.sub(r"0[xX]", " ", text or "")
    cleaned = re.sub(r"[\s,,;;:_-]+", "", cleaned)
    if not cleaned or len(cleaned) % 2:
        return False
    return re.fullmatch(r"[0-9a-fA-F]+", cleaned) is not None


def parse_frame_bytes(text: str, encoding: str = "utf-8") -> bytes:
    """头帧 / 尾帧 / 固定内容的通用解析，Hex 与文本都直接支持。

    * 十六进制：`AA 55`、`0xAA,0x55`、`AA55`
    * 文本：`text:AT+RESET\\r\\n`，或给内容加引号 `"hello"`
    * 自动：全是十六进制字符按 Hex 解析，出现其它字符（如字母 G~Z）按文本编码
    """
    raw = (text or "").strip()
    if not raw:
        return b""
    lowered = raw.lower()
    for prefix in _HEX_PREFIXES:
        if lowered.startswith(prefix):
            return parse_hex_bytes(raw[len(prefix):])
    for prefix in _TEXT_PREFIXES:
        if lowered.startswith(prefix):
            body = _strip_quotes(raw[len(prefix):])
            return _unescape(body).encode(encoding, errors="replace")
    if raw[0] in "\"'":
        return _unescape(_strip_quotes(raw)).encode(encoding, errors="replace")
    if looks_like_hex(raw):
        return parse_hex_bytes(raw)
    return _unescape(raw).encode(encoding, errors="replace")


def pack_number(value: float, dtype: str = "float32", big_endian: bool = False) -> bytes:
    """按数据类型与字节序打包单个数值。"""
    fmt, size = _FMT.get(dtype, _FMT["float32"])
    endian = ">" if big_endian else "<"
    if fmt == "f":
        return struct.pack(endian + fmt, float(value))
    lo, hi = dtype_limits(dtype)
    integer = int(round(float(value)))
    integer = max(int(lo), min(int(hi), integer))
    return struct.pack(endian + fmt, integer)


def nice_ceil(value: float) -> float:
    """把边界向上取整到 1 / 2 / 2.5 / 3 / 5 × 10^n，滑块两端的读数更整齐。"""
    value = abs(float(value))
    if value <= 0:
        return 1.0
    base = 10.0 ** math.floor(math.log10(value))
    for factor in (1.0, 2.0, 2.5, 3.0, 5.0):
        if value <= factor * base * (1.0 + 1e-9):
            return factor * base
    return 10.0 * base


def _label(text: str, name: str | None = None) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    return lab


class AdaptiveSlider(QSlider):
    """浮点映射滑块：滑到端点后继续滚轮 / 按键可突破上下限（自适应量程）。"""

    floatValueChanged = Signal(float)
    floatRangeChanged = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setFixedHeight(22)
        self.setRange(0, 1000)
        self._steps = 1000
        self._lo = 0.0
        self._hi = 100.0
        self._step = 1.0
        self._decimals = 2
        self._guard = False
        self._drag_ts = 0.0
        self.setToolTip("拖到两端后继续滚轮 / 方向键可突破当前上下限")
        self.valueChanged.connect(self._on_position)

    # ---- 范围与数值 ----
    def span(self) -> float:
        return self._hi - self._lo

    def floatRange(self) -> tuple[float, float]:
        return self._lo, self._hi

    def _recalc_steps(self) -> None:
        span = max(self.span(), 1e-9)
        fine = 10 ** (-self._decimals) if self._decimals > 0 else 1.0
        unit = max(min(abs(self._step), fine), 1e-6)
        self._steps = int(min(4000, max(200, span / unit)))
        self.setRange(0, self._steps)

    def setDecimals(self, decimals: int) -> None:
        self._decimals = max(0, int(decimals))
        self._recalc_steps()

    def setFloatRange(self, lo: float, hi: float, keep_value: bool = True) -> None:
        current = self.floatValue()
        self._lo = float(lo)
        self._hi = float(hi)
        if self._hi <= self._lo:
            self._hi = self._lo + max(abs(self._step), 1e-6)
        self._recalc_steps()
        self.setFloatValue(current if keep_value else self._lo)

    def setStep(self, step: float) -> None:
        self._step = abs(float(step)) or 1.0
        self._recalc_steps()

    def floatValue(self) -> float:
        return self._lo + self.span() * self.value() / max(self._steps, 1)

    def setFloatValue(self, value: float, emit: bool = False) -> None:
        value = min(max(float(value), self._lo), self._hi)
        ratio = (value - self._lo) / max(self.span(), 1e-12)
        pos = int(round(ratio * self._steps))
        self._guard = True
        self.setValue(max(0, min(self._steps, pos)))
        self._guard = False
        if emit:
            self.floatValueChanged.emit(self.floatValue())

    def _on_position(self, _pos: int) -> None:
        if not self._guard:
            self.floatValueChanged.emit(self.floatValue())

    # ---- 越界自适应 ----
    def _extend(self, up: bool) -> None:
        delta = max(self.span() * 0.1, abs(self._step), 1e-3)
        if up:
            self._hi = round(self._hi + delta, 6)
        else:
            self._lo = round(self._lo - delta, 6)
        self._recalc_steps()
        self.setFloatValue(self._hi if up else self._lo, emit=True)
        self.floatRangeChanged.emit(self._lo, self._hi)

    def wheelEvent(self, event) -> None:
        dy = event.angleDelta().y()
        if dy > 0 and self.value() == self.maximum():
            self._extend(True)
            event.accept()
            return
        if dy < 0 and self.value() == self.minimum():
            self._extend(False)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        grow = key in (Qt.Key_Right, Qt.Key_Up, Qt.Key_PageUp)
        shrink = key in (Qt.Key_Left, Qt.Key_Down, Qt.Key_PageDown)
        if grow and self.value() == self.maximum():
            self._extend(True)
            return
        if shrink and self.value() == self.minimum():
            self._extend(False)
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if not (event.buttons() & Qt.LeftButton):
            return
        now = time.monotonic()
        if now - self._drag_ts < 0.15:
            return
        x = event.position().x()
        if x >= self.width() - 2 and self.value() == self.maximum():
            self._drag_ts = now
            self._extend(True)
        elif x <= 2 and self.value() == self.minimum():
            self._drag_ts = now
            self._extend(False)


class _TitleLabel(QLabel):
    """可双击 / 可右键的标题标签。"""

    doubleClicked = Signal()
    rightClicked = Signal(object)

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseDoubleClickEvent(self, event) -> None:
        self.doubleClicked.emit()
        event.accept()

    def contextMenuEvent(self, event) -> None:
        self.rightClicked.emit(event.globalPos())
        event.accept()


class _RenameEdit(QLineEdit):
    """就地改名输入框：回车 / 失焦提交，Esc 取消。"""

    cancelled = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _SelectAllSpin(QDoubleSpinBox):
    """双击即全选整段文字的数值框。

    QDoubleSpinBox 默认只选中被双击到的那一小段（例如小数点后的位数），
    这里直接吞掉编辑框的双击事件再 selectAll()，保证整段数字一次性选中。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        editor = self.lineEdit()
        if editor is not None:
            editor.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.lineEdit() and event.type() == QEvent.Type.MouseButtonDblClick:
            obj.selectAll()
            return True
        return super().eventFilter(obj, event)


class ValueSpin(_SelectAllSpin):
    """滑动条数值框：双击全选，输入后量程自动适配。"""


class CommandItem(QFrame):
    """命令抽屉中的一条命令（固定命令或滑动条）。"""

    send_requested = Signal(object)
    remove_requested = Signal(object)
    edit_requested = Signal(object)
    groupRenameRequested = Signal(object, str)
    groupColorRequested = Signal(object, str)

    def __init__(
        self,
        kind: str = "fixed",
        title: str = "命令1",
        content: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("infoCard")

        self.kind = kind
        self.title = title
        self.content = content
        self.dtype = "float32"
        self.big_endian = False
        self.vmin = -100.0
        self.vmax = 100.0
        self.step = 1.0
        self.decimals = 2
        self.value = 0.0
        self.group = ""
        self.head_enabled = False
        self.head_text = ""
        self.tail_enabled = False
        self.tail_text = ""
        self.auto_send = True

        self.slider: AdaptiveSlider | None = None
        self.value_spin: QDoubleSpinBox | None = None
        self.edit: QLineEdit | None = None
        self.preview: QLabel | None = None
        self.badge: QLabel | None = None
        self._group_color: str | None = None
        self._syncing = False
        self._spin_dirty = False
        self._renaming = False
        self._rename_target = "title"
        self._rename_edit: _RenameEdit | None = None
        self._rename_widget: QWidget | None = None
        self.top_row: QHBoxLayout | None = None
        self.title_label: QLabel | None = None
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.setInterval(40)
        self._send_timer.timeout.connect(lambda: self.send_requested.emit(self))

        self.main = QVBoxLayout(self)
        self.main.setContentsMargins(10, 8, 10, 10)
        self.main.setSpacing(6)
        self._rebuild()

    # ---- 数据 ----
    def settings(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "content": self.content,
            "dtype": self.dtype,
            "big_endian": self.big_endian,
            "vmin": self.vmin,
            "vmax": self.vmax,
            "step": self.step,
            "decimals": self.decimals,
            "value": self.value,
            "group": self.group,
            "head_enabled": self.head_enabled,
            "head_text": self.head_text,
            "tail_enabled": self.tail_enabled,
            "tail_text": self.tail_text,
            "auto_send": self.auto_send,
        }

    def apply_settings(self, data: dict) -> None:
        self.kind = data.get("kind", self.kind)
        self.title = (data.get("title") or self.title).strip()
        self.content = data.get("content", self.content)
        self.dtype = data.get("dtype", self.dtype)
        self.big_endian = bool(data.get("big_endian", self.big_endian))
        self.vmin = float(data.get("vmin", self.vmin))
        self.vmax = float(data.get("vmax", self.vmax))
        self.step = float(data.get("step", self.step))
        self.decimals = int(data.get("decimals", self.decimals))
        self.value = float(data.get("value", self.value))
        self.group = (data.get("group") or "").strip()
        self.head_enabled = bool(data.get("head_enabled", self.head_enabled))
        self.head_text = data.get("head_text", self.head_text)
        self.tail_enabled = bool(data.get("tail_enabled", self.tail_enabled))
        self.tail_text = data.get("tail_text", self.tail_text)
        self.auto_send = bool(data.get("auto_send", self.auto_send))
        self.refresh()

    def refresh(self) -> None:
        self._rebuild()

    def head_bytes(self, encoding: str = "utf-8") -> bytes:
        return parse_frame_bytes(self.head_text, encoding) if self.head_enabled else b""

    def tail_bytes(self, encoding: str = "utf-8") -> bytes:
        return parse_frame_bytes(self.tail_text, encoding) if self.tail_enabled else b""

    def pack_payload(self) -> bytes:
        return pack_number(self.value, self.dtype, self.big_endian)

    def numeric_value(self) -> float:
        return self.value

    def set_preview(self, text: str) -> None:
        if self.preview is None:
            return
        if len(text) > 96:
            text = text[:93] + "…"
        self.preview.setText(text)

    # ---- 界面 ----
    def _clear(self) -> None:
        while self.main.count():
            item = self.main.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                continue
            layout = item.layout()
            if layout is not None:
                while layout.count():
                    sub = layout.takeAt(0)
                    child = sub.widget()
                    if child is not None:
                        child.setParent(None)
                        child.deleteLater()
                layout.deleteLater()
        self._renaming = False
        if self._rename_edit is not None:
            self._rename_edit.hide()
        self.slider = None
        self.value_spin = None
        self.edit = None
        self.badge = None
        self.title_label = None
        self.top_row = None
        self._rename_widget = None

    def _rebuild(self) -> None:
        self._clear()

        title_label = _TitleLabel(self.title)
        title_label.setObjectName("sectionBlue")
        title_label.setToolTip("双击修改名称")
        title_label.doubleClicked.connect(self._begin_rename)
        self.title_label = title_label
        top = QHBoxLayout()
        top.setSpacing(4)
        self.top_row = top
        top.addWidget(title_label)
        top.addStretch(1)
        if self.kind == "slider" and self.group:
            self.badge = _TitleLabel(f"● {self.group}")
            self.badge.setObjectName("tinyMuted")
            self.badge.setToolTip("双击改组名 · 右键一键换整组配色")
            self.badge.doubleClicked.connect(self._begin_group_rename)
            self.badge.rightClicked.connect(self._show_group_color_menu)
            top.addWidget(self.badge)
            top.addSpacing(4)

        send_btn = QPushButton("发送")
        send_btn.setObjectName("primary")
        send_btn.setFixedSize(56, 26)
        send_btn.setCursor(Qt.PointingHandCursor)
        send_btn.setToolTip("立即发送该命令")
        send_btn.clicked.connect(lambda: self.send_requested.emit(self))
        top.addWidget(send_btn)

        close_btn = QToolButton()
        close_btn.setObjectName("cmdClose")
        # 不要沿用 #flatTool 的 10px 内边距，否则 24px 按钮里图标会被压成一个点
        close_btn.setStyleSheet(
            "QToolButton#cmdClose{background:transparent;border:0px;"
            "border-radius:6px;padding:0px;}"
            "QToolButton#cmdClose:hover{background:rgba(199,75,92,0.12);}"
        )
        close_btn.setIcon(icon("close", 18, "#7C8CA0"))
        close_btn.setIconSize(QSize(16, 16))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(24, 24)
        close_btn.setToolTip("删除整个滑块组" if self.group else "删除该命令")
        close_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        top.addWidget(close_btn)
        self.main.addLayout(top)

        if self.kind == "fixed":
            self.edit = QLineEdit(self.content)
            self.edit.setObjectName("mono")
            self.edit.setFixedHeight(28)
            self.edit.setPlaceholderText("Hex: 01 03 00 00 00 01 84 0A")
            self.edit.textChanged.connect(self._on_content_changed)
            self.main.addWidget(self.edit)
        else:
            row = QHBoxLayout()
            row.setSpacing(8)
            self.slider = AdaptiveSlider()
            self.slider.setDecimals(self.decimals)
            self.slider.setStep(self.step)
            self.slider.setFloatRange(self.vmin, self.vmax)
            self.slider.setFloatValue(self.value)
            self.slider.floatValueChanged.connect(self._on_slider_value)
            self.slider.floatRangeChanged.connect(self._on_range_changed)
            row.addWidget(self.slider, 1)

            self.value_spin = ValueSpin()
            self.value_spin.setDecimals(self.decimals)
            limit_lo, limit_hi = dtype_limits(self.dtype)
            self.value_spin.setRange(limit_lo, limit_hi)
            self.value_spin.setSingleStep(self.step)
            self.value_spin.setValue(self.value)
            self.value_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
            self.value_spin.setFixedHeight(28)
            self.value_spin.setFixedWidth(90)
            self.value_spin.setToolTip("双击全选，输入后量程会自动适配")
            self.value_spin.valueChanged.connect(self._on_spin_value)
            self.value_spin.editingFinished.connect(self._on_value_committed)
            self.value_spin.lineEdit().textEdited.connect(self._mark_spin_dirty)
            row.addWidget(self.value_spin)
            self.main.addLayout(row)

        self.preview = _label("", "tinyMuted")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(
            "color:#9AA8B8;font-family:Consolas;font-size:11px;"
        )
        self.main.addWidget(self.preview)
        self._style_group(self._group_color)

    def set_group_color(self, color: str | None) -> None:
        """同组滑块统一配色：浅色底 + 左侧色条 + 同色滑轨。"""
        self._group_color = color
        self._style_group(color)

    def _style_group(self, color: str | None) -> None:
        if not color:
            self.setStyleSheet("")
            if self.slider is not None:
                self.slider.setStyleSheet("")
            if self.badge is not None:
                self.badge.setStyleSheet("")
            return
        rgb = QColor(color)
        r, g, b = rgb.red(), rgb.green(), rgb.blue()
        self.setStyleSheet(
            f"QFrame#infoCard{{background:rgba({r},{g},{b},0.13);"
            f"border:1px solid rgba({r},{g},{b},0.45);"
            f"border-left:4px solid {color};"
            "border-radius:10px;}}"
        )
        if self.slider is not None:
            self.slider.setStyleSheet(
                f"QSlider::sub-page:horizontal{{background:{color};}}"
                f"QSlider::handle:horizontal{{border:2px solid {color};background:#ffffff;}}"
            )
        if self.badge is not None:
            self.badge.setStyleSheet(f"color:{color};font-weight:700;")

    def _on_content_changed(self, text: str) -> None:
        self.content = text

    def _on_slider_value(self, value: float) -> None:
        if self._syncing:
            return
        self.value = value
        if self.value_spin is not None:
            self._syncing = True
            self.value_spin.setValue(value)
            self._syncing = False
        self._schedule_send()

    def _on_spin_value(self, value: float) -> None:
        if self._syncing:
            return
        self.value = value
        if self.slider is not None:
            self._syncing = True
            self.slider.setFloatValue(value)
            self._syncing = False
        self._schedule_send()

    def _on_range_changed(self, lo: float, hi: float) -> None:
        self.vmin, self.vmax = lo, hi
        self._schedule_send()

    def _mark_spin_dirty(self, _text: str) -> None:
        self._spin_dirty = True

    def _auto_fit_range(self, value: float) -> tuple[float, float]:
        """按输入值推算合适的量程：数值大就放大，数值小就收紧。

        保持原有量程的正负习惯（对称 / 仅正 / 仅负），边界取整到好看的数字，
        并限制在数据类型能表示的范围内。
        """
        lo, hi = self.slider.floatRange()
        quantum = 10.0 ** (-self.decimals) * 10.0
        need = max(abs(value) * 1.5, abs(self.step) * 4.0, quantum, 1e-6)
        limit = nice_ceil(need)
        if lo < 0 < hi:
            new_lo, new_hi = -limit, limit
        elif hi <= 0:
            new_lo, new_hi = -limit, 0.0
        else:
            new_lo, new_hi = 0.0, limit
        dtype_lo, dtype_hi = dtype_limits(self.dtype)
        new_lo = max(new_lo, dtype_lo)
        new_hi = min(new_hi, dtype_hi)
        if new_hi <= new_lo:
            new_lo, new_hi = dtype_lo, dtype_hi
        digits = max(self.decimals, 0)
        return round(new_lo, digits), round(new_hi, digits)

    def _on_value_committed(self) -> None:
        """手动输入数值后自动适配滑块量程，不必再打开设置改范围。"""
        if not self._spin_dirty or self.slider is None:
            return
        self._spin_dirty = False
        value = float(self.value_spin.value())
        self.value = value
        lo, hi = self.slider.floatRange()
        new_lo, new_hi = self._auto_fit_range(value)
        span = hi - lo
        new_span = new_hi - new_lo
        # 超出量程就放大；量程远超数值所需才收紧，小幅差异保持不动
        needs_fit = value < lo or value > hi or span > new_span * 6.0
        if needs_fit and (new_lo != lo or new_hi != hi):
            self.vmin, self.vmax = new_lo, new_hi
            self._syncing = True
            self.slider.setFloatRange(new_lo, new_hi)
            self.slider.setFloatValue(value)
            self._syncing = False
        self._schedule_send()

    def _schedule_send(self) -> None:
        if self.kind == "slider" and self.auto_send:
            self._send_timer.start()

    def set_auto_send(self, on: bool) -> None:
        self.auto_send = on

    # ---- 就地改名 ----
    def _begin_rename(self) -> None:
        self._begin_inline_edit("title")

    def _begin_group_rename(self) -> None:
        self._begin_inline_edit("group")

    def _begin_inline_edit(self, target: str) -> None:
        if self._renaming or self.top_row is None:
            return
        widget = self.badge if target == "group" else self.title_label
        if widget is None:
            return
        self._rename_target = target
        self._rename_widget = widget
        self._renaming = True
        if self._rename_edit is None:
            self._rename_edit = _RenameEdit(self)
            self._rename_edit.setFixedHeight(24)
            self._rename_edit.cancelled.connect(self._cancel_rename)
            self._rename_edit.editingFinished.connect(self._finish_rename)
        index = max(0, self.top_row.indexOf(widget))
        self.top_row.insertWidget(index, self._rename_edit)
        self._rename_edit.setText(self.group if target == "group" else self.title)
        self._rename_edit.setFixedWidth(110 if target == "title" else 90)
        widget.hide()
        self._rename_edit.show()
        self._rename_edit.setFocus()
        self._rename_edit.selectAll()

    def _finish_rename(self) -> None:
        if not self._renaming or self._rename_edit is None:
            return
        self._renaming = False
        text = self._rename_edit.text().strip()
        target = self._rename_target
        self._end_inline_edit()
        if target == "group":
            if text and text != self.group:
                self.groupRenameRequested.emit(self, text)
            return
        if text:
            self.title = text
            if self.title_label is not None:
                self.title_label.setText(text)

    def _cancel_rename(self) -> None:
        if not self._renaming:
            return
        self._renaming = False
        self._end_inline_edit()

    def _end_inline_edit(self) -> None:
        edit = self._rename_edit
        if edit is not None:
            edit.hide()
            if self.top_row is not None:
                self.top_row.removeWidget(edit)
        widget = getattr(self, "_rename_widget", None)
        if widget is not None:
            widget.show()
        self._rename_widget = None

    # ---- 组配色 ----
    def group_color_menu(self) -> QMenu:
        """整组配色调色板：自动配色 + 6 个预设色，点一下即生效。"""
        menu = QMenu(self)
        menu.addAction("自动配色", lambda: self.groupColorRequested.emit(self, ""))
        menu.addSeparator()
        current = (self._group_color or "").upper()
        for label, color in zip(GROUP_COLOR_LABELS, GROUP_COLORS):
            act = menu.addAction(self._color_icon(color), label)
            act.setCheckable(True)
            act.setChecked(current == color.upper())
            act.triggered.connect(
                lambda _=False, value=color: self.groupColorRequested.emit(self, value)
            )
        return menu

    def _show_group_color_menu(self, global_pos: QPoint) -> None:
        if self.kind != "slider" or not self.group:
            return
        self.group_color_menu().exec(global_pos)

    @staticmethod
    def _color_icon(color: str) -> QIcon:
        pix = QPixmap(12, 12)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(0, 0, 12, 12, 3, 3)
        painter.end()
        return QIcon(pix)

    # ---- 交互 ----
    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction("发送一次", lambda: self.send_requested.emit(self))
        menu.addAction("设置…", lambda: self.edit_requested.emit(self))
        live = menu.addAction("拖动时实时发送")
        live.setCheckable(True)
        live.setChecked(self.auto_send)
        live.setEnabled(self.kind == "slider")
        live.toggled.connect(self.set_auto_send)
        menu.addSeparator()
        menu.addAction("删除", lambda: self.remove_requested.emit(self))
        menu.exec(event.globalPos())
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self.edit_requested.emit(self)
        event.accept()


class CommandDialog(QDialog):
    """命令设置：类型、数据格式、滑动条量程、头帧 / 尾帧。"""

    def __init__(
        self,
        settings: dict,
        groups: list[str],
        hex_mode: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("命令设置")
        self.setMinimumWidth(430)
        self._groups = groups

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)

        lay.addWidget(_label("命令设置", "sectionBlue"))

        self.name_edit = QLineEdit(settings.get("title", ""))
        self.name_edit.setPlaceholderText("留空自动命名")
        self.name_edit.selectAll()
        lay.addLayout(self._row("名称", self.name_edit))

        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["固定命令", "滑动条"])
        self.kind_combo.setCurrentIndex(0 if settings.get("kind") == "fixed" else 1)
        lay.addLayout(self._row("类型", self.kind_combo))

        # ---- 固定命令 ----
        self.fixed_box = QWidget()
        fixed_lay = QVBoxLayout(self.fixed_box)
        fixed_lay.setContentsMargins(0, 0, 0, 0)
        fixed_lay.setSpacing(6)
        self.content_edit = QLineEdit(settings.get("content", ""))
        self.content_edit.setObjectName("mono")
        self.content_edit.setPlaceholderText('01 03 00 00 00 01 84 0A  或  text:AT+RESET\\r\\n')
        fixed_lay.addLayout(self._row("内容", self.content_edit))
        hint = _label(
            "内容可以直接写 Hex（AA 55），也可以直接写文本（text:AT+RESET\\r\\n 或 "
            '加引号 "hello"）：全是十六进制字符按 Hex 发送，其它按当前编码发送。'
            if hex_mode
            else "当前为文本模式，内容按所选编码发送；也可以写 hex: 前缀强制按十六进制发送。",
            "tinyMuted",
        )
        hint.setWordWrap(True)
        fixed_lay.addWidget(hint)
        lay.addWidget(self.fixed_box)

        # ---- 滑动条 ----
        self.slider_box = QWidget()
        slider_lay = QVBoxLayout(self.slider_box)
        slider_lay.setContentsMargins(0, 0, 0, 0)
        slider_lay.setSpacing(6)

        self.dtype_combo = QComboBox()
        self.dtype_combo.addItems(DTYPE_NAMES)
        self.dtype_combo.setCurrentText(settings.get("dtype", "float32"))
        slider_lay.addLayout(self._row("数据格式", self.dtype_combo))

        self.endian_combo = QComboBox()
        self.endian_combo.addItems(["小端 (LE)", "大端 (BE)"])
        self.endian_combo.setCurrentIndex(1 if settings.get("big_endian") else 0)
        slider_lay.addLayout(self._row("字节序", self.endian_combo))

        self.min_spin = self._dspin(settings.get("vmin", -100.0))
        self.max_spin = self._dspin(settings.get("vmax", 100.0))
        self.step_spin = self._dspin(settings.get("step", 1.0))
        self.step_spin.setMinimum(0.001)
        self.decimals_spin = QSpinBox()
        self.decimals_spin.setRange(0, 6)
        self.decimals_spin.setValue(int(settings.get("decimals", 2)))
        self.decimals_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.value_spin = self._dspin(settings.get("value", 0.0))

        range_row = QHBoxLayout()
        range_row.setSpacing(6)
        range_label = _label("范围")
        range_label.setFixedWidth(64)
        range_row.addWidget(range_label)
        range_row.addWidget(self.min_spin, 1)
        range_row.addWidget(_label("~"))
        range_row.addWidget(self.max_spin, 1)
        slider_lay.addLayout(range_row)

        step_row = QHBoxLayout()
        step_row.setSpacing(6)
        step_label = _label("步长/小数")
        step_label.setFixedWidth(64)
        step_row.addWidget(step_label)
        step_row.addWidget(self.step_spin, 1)
        self.decimals_spin.setFixedWidth(64)
        step_row.addWidget(self.decimals_spin)
        slider_lay.addLayout(step_row)

        slider_lay.addLayout(self._row("当前值", self.value_spin))

        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)
        self.group_combo.addItem("")
        for name in groups:
            self.group_combo.addItem(name)
        self.group_combo.setCurrentText(settings.get("group", ""))
        slider_lay.addLayout(self._row("绑定组", self.group_combo))
        group_hint = _label(
            "同组名的滑动条会按添加顺序打包成一帧，例如 3 个 float32 滑块 = 12 字节数据。",
            "tinyMuted",
        )
        group_hint.setWordWrap(True)
        slider_lay.addWidget(group_hint)

        self.auto_send_check = QCheckBox("拖动时实时发送")
        self.auto_send_check.setChecked(bool(settings.get("auto_send", True)))
        slider_lay.addWidget(self.auto_send_check)
        lay.addWidget(self.slider_box)

        # ---- 头帧 / 尾帧 ----
        lay.addWidget(_label("帧组合", "sectionBlue"))
        frame_row = QHBoxLayout()
        frame_row.setSpacing(6)
        self.head_check = QCheckBox("头帧")
        self.head_check.setChecked(bool(settings.get("head_enabled", False)))
        self.head_edit = QLineEdit(settings.get("head_text", ""))
        self.head_edit.setObjectName("mono")
        self.head_edit.setPlaceholderText('AA 55  或  text:AT+RESET\\r\\n')
        self.head_edit.setEnabled(self.head_check.isChecked())
        self.head_check.toggled.connect(self.head_edit.setEnabled)
        frame_row.addWidget(self.head_check)
        frame_row.addWidget(self.head_edit, 1)
        lay.addLayout(frame_row)

        tail_row = QHBoxLayout()
        tail_row.setSpacing(6)
        self.tail_check = QCheckBox("尾帧")
        self.tail_check.setChecked(bool(settings.get("tail_enabled", False)))
        self.tail_edit = QLineEdit(settings.get("tail_text", ""))
        self.tail_edit.setObjectName("mono")
        self.tail_edit.setPlaceholderText('00 00 80 7F  或  text:\\r\\n')
        self.tail_edit.setEnabled(self.tail_check.isChecked())
        self.tail_check.toggled.connect(self.tail_edit.setEnabled)
        tail_row.addWidget(self.tail_check)
        tail_row.addWidget(self.tail_edit, 1)
        lay.addLayout(tail_row)

        frame_hint = _label(
            "头帧 / 尾帧可以直接写 Hex（AA 55、0xAA），也可以直接写文本"
            "（text:AT+RESET\\r\\n，或给内容加英文引号）：全是十六进制字符按 Hex 解析，"
            "出现其它字符按当前编码发送，支持 \\r \\n \\t 转义。"
            "可单独启用或组合使用；绑定组时以组内第一个滑块的帧配置为准。",
            "tinyMuted",
        )
        frame_hint.setWordWrap(True)
        lay.addWidget(frame_hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("确定")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self._on_accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)
        lay.addLayout(buttons)

        self.kind_combo.currentIndexChanged.connect(self._sync_kind)
        self._sync_kind()

    # ---- 小工具 ----
    @staticmethod
    def _row(text: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        lab = _label(text)
        lab.setFixedWidth(64)
        row.addWidget(lab)
        row.addWidget(widget, 1)
        return row

    @staticmethod
    def _dspin(value: float) -> _SelectAllSpin:
        spin = _SelectAllSpin()
        spin.setDecimals(3)
        spin.setRange(-1e9, 1e9)
        spin.setSingleStep(1.0)
        spin.setValue(float(value))
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        return spin

    def _sync_kind(self) -> None:
        slider = self.kind_combo.currentIndex() == 1
        self.fixed_box.setVisible(not slider)
        self.slider_box.setVisible(slider)

    def _on_accept(self) -> None:
        for check, edit, name in (
            (self.head_check, self.head_edit, "头帧"),
            (self.tail_check, self.tail_edit, "尾帧"),
        ):
            if check.isChecked():
                try:
                    parse_frame_bytes(edit.text(), "utf-8")
                except ValueError:
                    self._warn(f"{name}的 hex: 写法不合法，请检查十六进制位数（需为偶数）。")
                    return
        if self.kind_combo.currentIndex() == 1:
            if self.max_spin.value() <= self.min_spin.value():
                self._warn("上限必须大于下限。")
                return
        self.accept()

    def _warn(self, text: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(self, "设置无效", text)

    def values(self) -> dict:
        slider = self.kind_combo.currentIndex() == 1
        return {
            "kind": "slider" if slider else "fixed",
            "title": self.name_edit.text().strip(),
            "content": self.content_edit.text(),
            "dtype": self.dtype_combo.currentText(),
            "big_endian": self.endian_combo.currentIndex() == 1,
            "vmin": self.min_spin.value(),
            "vmax": self.max_spin.value(),
            "step": self.step_spin.value(),
            "decimals": self.decimals_spin.value(),
            "value": self.value_spin.value(),
            "group": self.group_combo.currentText().strip(),
            "head_enabled": self.head_check.isChecked(),
            "head_text": self.head_edit.text(),
            "tail_enabled": self.tail_check.isChecked(),
            "tail_text": self.tail_edit.text(),
            "auto_send": self.auto_send_check.isChecked(),
        }
