"""通用小控件：无边框下拉、 Pine 风格按钮等。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QSizePolicy, QToolButton, QWidget

from .theme import Theme


class FlatCombo(QComboBox):
    """接近原图的灰色描边、白色背景、右侧箭头的下拉框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(Theme.font())
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setStyleSheet(
            """
            QComboBox {
                background: #FFFFFF;
                border: 1px solid #C8C8C8;
                border-radius: 5px;
                padding: 2px 22px 2px 7px;
                color: #222222;
            }
            QComboBox:hover { border: 1px solid #999999; }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 18px;
                border: 0;
                background: transparent;
            }
            QComboBox::down-arrow {
                image: none;
                width: 0; height: 0;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #555555;
            }
            QComboBox QAbstractItemView {
                background: #FFFFFF;
                border: 1px solid #AAAAAA;
                selection-background-color: #CCE4FF;
                selection-color: #222222;
            }
            """
        )


class SectionLabel(QFrame):
    """左侧蓝色加粗分组标题。"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("sectionLabel")
        self.setStyleSheet(
            "QFrame#sectionLabel { color: #0078D7; font-weight: bold; "
            "font-family: 'Microsoft YaHei UI'; font-size: 11pt; }"
        )
        from PySide6.QtWidgets import QHBoxLayout, QLabel

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 9, 0, 3)
        layout.setSpacing(0)
        label = QLabel(text)
        label.setFont(Theme.font(bold=True))
        label.setStyleSheet("color:#0078D7;")
        layout.addWidget(label)


class KeyValueRow(QWidget):
    """参数面板中的一行：标签 + 控件。"""

    def __init__(self, label: str, widget: QWidget, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout, QLabel

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)
        lab = QLabel(label)
        lab.setFont(Theme.font())
        lab.setFixedWidth(72)
        lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(lab)
        layout.addWidget(widget, 1)


class TinyToolButton(QToolButton):
    def __init__(self, icon, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.setIcon(icon)
        self.setToolTip(tooltip)
        self.setFixedSize(26, 26)
        self.setStyleSheet(
            "QToolButton { border: 1px solid transparent; background: transparent; border-radius: 5px; }"
            "QToolButton:hover { border: 1px solid #C8C8C8; background: #EAF3FB; }"
        )
