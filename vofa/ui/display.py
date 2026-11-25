"""显示控件栏：轻量三轴姿态视图、卡片及其悬浮窗口。"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from ..icons import icon
from .common import ICON_NEUTRAL, hbox, make_label, vbox

AXIS_COLORS = ("#E05252", "#1F9D67", "#2D7EF1")


class TriAxisWidget(QWidget):
    """轻量三轴姿态视图：根据三个角度旋转 XYZ 轴，不依赖 OpenGL。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.angles = [0.0, 0.0, 0.0]
        self.unit = "deg"
        self._dark = False
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_dark(self, dark: bool) -> None:
        self._dark = bool(dark)
        self.update()

    def set_angles(self, angles: list[float]) -> None:
        self.angles = list(angles) + [0.0] * (3 - len(angles))
        self.update()

    @staticmethod
    def _rotate_x(vec, angle: float):
        x, y, z = vec
        c, s = math.cos(angle), math.sin(angle)
        return x, y * c - z * s, y * s + z * c

    @staticmethod
    def _rotate_y(vec, angle: float):
        x, y, z = vec
        c, s = math.cos(angle), math.sin(angle)
        return x * c + z * s, y, -x * s + z * c

    @staticmethod
    def _rotate_z(vec, angle: float):
        x, y, z = vec
        c, s = math.cos(angle), math.sin(angle)
        return x * c - y * s, x * s + y * c, z

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        cx, cy = width / 2.0, height / 2.0 + 4.0
        scale = max(42.0, min(width, height) * 0.31)

        grid = QColor("#DCE4EF" if not self._dark else "#3C3C3C")
        painter.setPen(QPen(grid, 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy + scale * 0.16), scale * 1.06, scale * 0.46)

        angles = [
            math.radians(a) if self.unit == "deg" else a for a in self.angles[:3]
        ]
        basis = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        projected = []
        for index, vec in enumerate(basis):
            rotated = self._rotate_x(vec, angles[0])
            rotated = self._rotate_y(rotated, angles[1])
            rotated = self._rotate_z(rotated, angles[2])
            rotated = self._rotate_x(rotated, -0.34)
            rotated = self._rotate_y(rotated, 0.62)
            projected.append((rotated[2], index, rotated))

        label_font = QFont("Consolas")
        label_font.setPointSize(10)
        label_font.setBold(True)
        painter.setFont(label_font)
        for _, index, vec in sorted(projected):
            px = cx + vec[0] * scale
            py = cy - vec[1] * scale
            color = QColor(AXIS_COLORS[index])
            painter.setPen(QPen(color, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(cx, cy), QPointF(px, py))
            direction = math.atan2(py - cy, px - cx)
            for delta in (-0.42, 0.42):
                hx = px - math.cos(direction + delta) * 9.0
                hy = py - math.sin(direction + delta) * 9.0
                painter.drawLine(QPointF(px, py), QPointF(hx, hy))
            painter.setPen(color)
            painter.drawText(
                QPointF(
                    px + math.cos(direction) * 11.0,
                    py + math.sin(direction) * 11.0,
                ),
                "XYZ"[index],
            )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#6B7A90" if not self._dark else "#B8C5D6"))
        painter.drawEllipse(QPointF(cx, cy), 3.2, 3.2)


class TriAxisCard(QFrame):
    """显示控件卡片：三轴视图 + X/Y/Z 独立通道绑定。"""

    closed = Signal(object)
    floatRequested = Signal(object)

    def __init__(self, unit: str = "deg", parent=None):
        super().__init__(parent)
        self.setObjectName("displayCard")
        self.unit = unit
        self.bindings: list[int | None] = [None, None, None]
        self._channel_key: tuple | None = None
        self._last_values = [0.0, 0.0, 0.0]
        self._has_value = [False, False, False]

        lay = vbox((10, 8, 10, 10), 8)
        head = hbox(spacing=6)
        head.addWidget(make_label("三轴坐标系", "displayTitle"))
        head.addStretch(1)
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("displayClose")
        self.close_btn.setIcon(icon("close", 12, ICON_NEUTRAL))
        self.close_btn.setToolTip("移除控件")
        self.close_btn.clicked.connect(lambda _=False: self.closed.emit(self))
        head.addWidget(self.close_btn)
        lay.addLayout(head)

        self.axis = TriAxisWidget()
        lay.addWidget(self.axis, 1)

        self.combos: list[QComboBox] = []
        self.value_labels: list[QLabel] = []
        for index, (letter, color) in enumerate(zip("XYZ", AXIS_COLORS)):
            row = hbox(spacing=6)
            letter_label = QLabel(letter)
            letter_label.setObjectName("axisLetter")
            letter_label.setStyleSheet(f"color: {color};")
            letter_label.setFixedWidth(14)
            combo = QComboBox()
            combo.setObjectName("axisBind")
            combo.addItem("不绑定", None)
            combo.currentIndexChanged.connect(
                lambda _=0, idx=index, box=combo: self._on_bind_changed(idx, box)
            )
            value_label = QLabel("--")
            value_label.setObjectName("axisValue")
            value_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            value_label.setMinimumWidth(62)
            row.addWidget(letter_label)
            row.addWidget(combo, 1)
            row.addWidget(value_label)
            lay.addLayout(row)
            self.combos.append(combo)
            self.value_labels.append(value_label)

        self.setLayout(lay)

    def _on_bind_changed(self, index: int, combo: QComboBox) -> None:
        self.bindings[index] = combo.currentData()
        self._refresh_text()

    def set_channels(self, count: int, names: list[str]) -> None:
        key = (count, tuple(names[:count]))
        if key == self._channel_key:
            return
        self._channel_key = key
        for index, combo in enumerate(self.combos):
            current = self.bindings[index]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("不绑定", None)
            for channel in range(count):
                combo.addItem(f"{channel} · {names[channel]}", channel)
            position = combo.findData(current) if current is not None else 0
            combo.setCurrentIndex(max(0, position))
            combo.blockSignals(False)
            if current is not None and current >= count:
                self.bindings[index] = None

    def update_data(self, count: int, names: list[str], values: list[float]) -> None:
        self.set_channels(count, names)
        for index, binding in enumerate(self.bindings):
            if binding is not None and binding < count:
                raw = float(values[binding])
                self._last_values[index] = raw
                self._has_value[index] = True
            else:
                self._has_value[index] = False
        self._refresh_axis()
        self._refresh_text()

    def _refresh_axis(self) -> None:
        angles = [
            (
                math.radians(value)
                if self.unit == "deg"
                else value
            )
            if self._has_value[index]
            else 0.0
            for index, value in enumerate(self._last_values)
        ]
        self.axis.set_angles(angles)

    def _refresh_text(self) -> None:
        for index, label in enumerate(self.value_labels):
            if not self._has_value[index] or self.bindings[index] is None:
                label.setText("--")
                continue
            value = self._last_values[index]
            label.setText(
                f"{value:+.2f}°" if self.unit == "deg" else f"{value:+.4f} rad"
            )

    def set_unit(self, unit: str) -> None:
        self.unit = unit
        self._refresh_axis()
        self._refresh_text()

    def set_dark(self, dark: bool) -> None:
        self.axis.set_dark(dark)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        child = self.childAt(event.position().toPoint())
        if isinstance(child, (QComboBox, QToolButton, QPushButton)):
            event.ignore()
            return
        self.floatRequested.emit(self)
        event.accept()


class FloatingCardWindow(QWidget):
    """三轴卡片的临时悬浮宿主；Esc 或关闭时把卡片放回原位置。"""

    restoreRequested = Signal(object)

    def __init__(self, card: TriAxisCard, parent=None):
        super().__init__(parent)
        self.card = card
        self.setObjectName("floatingCardWindow")
        self.setWindowTitle("三轴坐标系 · 悬浮显示")
        self.setWindowFlags(Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(520, 620)
        lay = vbox((16, 12, 16, 16), 10)
        lay.addWidget(make_label("双击卡片空白处可放大，按 Esc 返回", "tinyMuted"))
        lay.addWidget(card, 1)
        self.setLayout(lay)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.restoreRequested.emit(self)
        super().closeEvent(event)


class DisplayWidgetsPanel(QFrame):
    """左侧显示控件栏：可添加多个三轴坐标系并独立绑定数据。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("displayPanel")
        self.setMinimumWidth(200)
        self.unit = "deg"
        self._dark = False
        self._provider = None
        self.cards: list[TriAxisCard] = []
        self._floats: dict[TriAxisCard, FloatingCardWindow] = {}
        self._anchors: dict[TriAxisCard, tuple[int, QWidget]] = {}

        lay = vbox((12, 12, 12, 12), 10)
        head = hbox(spacing=6)
        head.addWidget(make_label("显示控件", "titleBlue"))
        head.addStretch(1)

        self.unit_deg = QPushButton("角度")
        self.unit_deg.setObjectName("unitBtn")
        self.unit_deg.setProperty("unitSegment", "first")
        self.unit_deg.setCheckable(True)
        self.unit_deg.setChecked(True)
        self.unit_deg.setFixedSize(44, 24)
        self.unit_deg.setToolTip("按角度制解释 Rx 数据")
        self.unit_deg.clicked.connect(lambda _=False: self.set_unit("deg"))
        head.addWidget(self.unit_deg)

        self.unit_rad = QPushButton("弧度")
        self.unit_rad.setObjectName("unitBtn")
        self.unit_rad.setProperty("unitSegment", "last")
        self.unit_rad.setCheckable(True)
        self.unit_rad.setFixedSize(44, 24)
        self.unit_rad.setToolTip("按弧度制解释 Rx 数据")
        self.unit_rad.clicked.connect(lambda _=False: self.set_unit("rad"))
        head.addWidget(self.unit_rad)

        self.add_btn = QToolButton()
        self.add_btn.setObjectName("displayAdd")
        self.add_btn.setIcon(icon("plus", 16, "#2D7EF1"))
        self.add_btn.setFixedSize(28, 28)
        self.add_btn.setToolTip("添加显示控件")
        self.add_btn.clicked.connect(self._show_add_menu)
        head.addWidget(self.add_btn)
        lay.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("displayScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.list_widget = QWidget()
        self.list_widget.setObjectName("displayList")
        self.list_layout = vbox((0, 0, 0, 0), 8)
        self.empty_hint = make_label(
            "暂无显示控件\n点击右上角 + 添加三轴坐标系", "tinyMuted"
        )
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setContentsMargins(0, 28, 0, 0)
        self.list_layout.addWidget(self.empty_hint)
        self.list_layout.addStretch(1)
        self.list_widget.setLayout(self.list_layout)
        self.scroll.setWidget(self.list_widget)
        lay.addWidget(self.scroll, 1)
        self.setLayout(lay)

    def set_provider(self, provider) -> None:
        self._provider = provider

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        action = menu.addAction("三轴坐标系")
        action.triggered.connect(self.add_tri_axis)
        menu.exec(self.add_btn.mapToGlobal(QPoint(0, self.add_btn.height())))

    def add_tri_axis(self) -> None:
        card = TriAxisCard(unit=self.unit)
        card.closed.connect(self.remove_card)
        card.floatRequested.connect(self.float_card)
        card.set_dark(self._dark)
        self.cards.append(card)
        self.list_layout.insertWidget(self.list_layout.count() - 1, card)
        self.empty_hint.hide()
        self.refresh_from_data()
        self.scroll.ensureWidgetVisible(card)

    def float_card(self, card: TriAxisCard) -> None:
        if card in self._floats or card not in self.cards:
            return
        index = self.list_layout.indexOf(card)
        if index < 0:
            return
        placeholder = QWidget(self.list_widget)
        placeholder.setFixedHeight(card.height())
        self.list_layout.removeWidget(card)
        self.list_layout.insertWidget(index, placeholder)
        window = FloatingCardWindow(card, self)
        window.restoreRequested.connect(self._restore_float)
        self._floats[card] = window
        self._anchors[card] = (index, placeholder)
        window.show()
        window.raise_()
        window.activateWindow()

    def _restore_float(self, window: FloatingCardWindow) -> None:
        card = window.card
        if card not in self._floats:
            return
        index, placeholder = self._anchors.pop(card)
        self._floats.pop(card, None)
        window.layout().removeWidget(card)
        placeholder.setParent(None)
        self.list_layout.insertWidget(index, card)
        card.show()
        self.scroll.ensureWidgetVisible(card)

    def remove_card(self, card: TriAxisCard) -> None:
        if card in self._floats:
            window = self._floats[card]
            self._restore_float(window)
            window.close()
        if card in self.cards:
            self.cards.remove(card)
        card.deleteLater()
        if not self.cards:
            self.empty_hint.show()

    def close_all_float_windows(self) -> None:
        for window in list(self._floats.values()):
            window.close()

    def refresh_from_data(self) -> None:
        if self._provider is None or not self.cards:
            return
        count, names, values = self._provider()
        for card in self.cards:
            card.update_data(count, names, values)

    def set_unit(self, unit: str) -> None:
        self.unit = "rad" if unit == "rad" else "deg"
        self.unit_deg.setChecked(self.unit == "deg")
        self.unit_rad.setChecked(self.unit == "rad")
        for card in self.cards:
            card.set_unit(self.unit)

    def set_dark(self, dark: bool) -> None:
        self._dark = bool(dark)
        for card in self.cards:
            card.set_dark(dark)
