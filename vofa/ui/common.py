"""通用布局助手与小型控件。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import CHANNEL_COLORS

ICON_NEUTRAL = "#7C8CA0"

SHORTCUT_DEFAULTS = {
    "pause": "Space",
    "connect": "F5",
    "screenshot": "Ctrl+S",
    "export_csv": "Ctrl+E",
    "clear_plot": "Ctrl+L",
}
SHORTCUT_LABELS = {
    "pause": "暂停 / 继续波形",
    "connect": "连接 / 断开",
    "screenshot": "导出截图 PNG",
    "export_csv": "导出数据 CSV",
    "clear_plot": "清空波形",
}


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
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    if align is not None:
        widget.setAlignment(align)
    return widget


def make_hr() -> QFrame:
    widget = QFrame()
    widget.setObjectName("hr")
    widget.setFixedHeight(1)
    return widget


def make_vline(height: int = 22) -> QFrame:
    widget = QFrame()
    widget.setObjectName("vline")
    widget.setFixedSize(1, height)
    return widget


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

        self.setObjectName("channelRow")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)

        self.eye = QCheckBox()
        self.eye.setChecked(True)
        self.eye.setFixedWidth(22)
        self.eye.setCursor(Qt.PointingHandCursor)
        self.eye.toggled.connect(lambda on: self.toggled.emit(self.index, on))

        self.name = QLabel(f"I{index}")
        self.name.setStyleSheet(f"font-weight:800;color:{color};")

        self.value = QLabel("0.000")
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value.setStyleSheet(
            f"font-family:Consolas;font-weight:700;color:{color};"
        )
        for lab in (self.name, self.value):
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        lay = hbox((8, 3, 8, 3), 8)
        lay.addWidget(self.eye)
        lay.addWidget(self.name)
        lay.addStretch(1)
        lay.addWidget(self.value)
        self.setLayout(lay)
        self._apply_style()

    def _apply_style(self) -> None:
        if self._selected:
            bg = "rgba(45,126,241,32)"
            border = "1px solid rgba(45,126,241,120)"
            hover = "rgba(45,126,241,52)"
        else:
            bg = "transparent"
            border = "1px solid transparent"
            hover = "rgba(120,140,165,28)"
        self.setStyleSheet(
            "QWidget#channelRow{"
            f"background:{bg};border:{border};border-radius:7px;}}"
            f"QWidget#channelRow:hover{{background:{hover};"
            f"border:1px solid rgba(45,126,241,90);}}"
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

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.selected.emit(self.index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.selected.emit(self.index)
        self.editRequested.emit(self.index)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.selected.emit(self.index)
        self.contextMenuRequested.emit(self.index, event.globalPos())
        event.accept()


class _ThemeCard(QToolButton):
    """设置里的外观选项卡片：缩略图 + 名称，点一下即切换。"""

    def __init__(self, title: str, window_bg: str, panel_bg: str, accent: str, parent=None):
        super().__init__(parent)
        self.setObjectName("themeCard")
        self.setText(title)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(112, 67))
        self.setIcon(QIcon(self._preview(window_bg, panel_bg, accent)))
        self.setMinimumHeight(104)

    @staticmethod
    def _preview(window_bg: str, panel_bg: str, accent: str) -> QPixmap:
        pix = QPixmap(224, 134)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(window_bg))
        painter.drawRoundedRect(0, 0, 224, 134, 14, 14)

        painter.setBrush(QColor(panel_bg))
        painter.setPen(QPen(QColor(120, 140, 165, 60), 1))
        painter.drawRoundedRect(14, 14, 196, 106, 10, 10)

        painter.setPen(QPen(QColor(120, 140, 165, 55), 1))
        for i in range(1, 4):
            y = 14 + 106 * i / 4
            painter.drawLine(20, int(y), 204, int(y))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent))
        painter.drawRoundedRect(26, 24, 40, 6, 3, 3)

        path = QPainterPath()
        path.moveTo(24, 100)
        path.cubicTo(60, 52, 92, 112, 122, 70)
        path.cubicTo(146, 36, 172, 78, 200, 48)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(accent), 2.6))
        painter.drawPath(path)
        painter.end()

        pix.setDevicePixelRatio(2.0)
        return pix


class _NumberCombo(QComboBox):
    """可编辑的数值下拉：预设值可选，双击整段全选后可直接输入其它值。"""

    def __init__(self, items, current: str = "", parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.addItems([str(item) for item in items])
        if current:
            self.setCurrentText(str(current))
        editor = self.lineEdit()
        if editor is not None:
            editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
            editor.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.lineEdit() and event.type() == QEvent.Type.MouseButtonDblClick:
            obj.selectAll()
            return True
        return super().eventFilter(obj, event)

    def int_value(self, default: int = 500, low: int = 1, high: int = 2000) -> int:
        try:
            value = int(float(self.currentText().strip()))
        except (TypeError, ValueError):
            return default
        return max(low, min(value, high))


class LogTextEdit(QPlainTextEdit):
    """日志区：Ctrl + 滚轮缩放字号，不影响正常滚动。"""

    fontZoomRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if (
            obj is self.viewport()
            and event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.ControlModifier
        ):
            delta = event.angleDelta().y()
            if delta:
                self.fontZoomRequested.emit(1 if delta > 0 else -1)
            return True
        return super().eventFilter(obj, event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.fontZoomRequested.emit(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)
