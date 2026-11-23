"""VOFA+ 风格的颜色、尺寸、字体与全局样式表。"""

from PySide6.QtGui import QColor, QFont


class Theme:
    bg = "#F5F7FB"
    panel = "#FFFFFF"
    border = "#E6EBF2"
    border_light = "#EEF2F7"
    accent_blue = "#2D7EF1"
    accent_blue_dark = "#1F6FE0"
    accent_red = "#C74B5C"
    accent_green = "#17B283"
    text = "#24374A"
    text_dim = "#7B8798"
    plot_bg = "#FAFBFE"
    grid = "#7B8798"
    cursor = "#C857E5"
    toolbar = "#FFFFFF"
    tab_bar = "#FFFFFF"

    font_family = "Microsoft YaHei UI"
    font_size = 13

    @staticmethod
    def font(size: int | None = None, bold: bool = False) -> QFont:
        f = QFont(Theme.font_family, size or Theme.font_size)
        f.setBold(bold)
        return f

    @staticmethod
    def grid_color(alpha: int = 90) -> QColor:
        c = QColor(Theme.grid)
        c.setAlpha(alpha)
        return c


CHANNEL_COLORS = [
    "#FF78BB",
    "#13B24F",
    "#408CFF",
    "#9B6DFF",
    "#FF9C3D",
    "#00B9C7",
    "#EF5350",
    "#7A7CF5",
]

APP_STYLE = """
QMainWindow, QWidget#root {
    background: #f5f7fb;
    color: #24374a;
}
QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}
QFrame#topbar {
    background: #ffffff;
    border-bottom: 1px solid #e6ebf2;
}
QFrame#rail {
    background: #eef2f7;
    border-right: 1px solid #e2e8f0;
}
QFrame#railRight {
    background: #eef2f7;
    border-left: 1px solid #e2e8f0;
}
QFrame#drawer, QFrame#rightbar, QFrame#plotCard, QFrame#bottomCard, QFrame#infoCard {
    background: #ffffff;
    border: 1px solid #e6ebf2;
    border-radius: 10px;
}
QFrame#rightbar {
    border-radius: 0px;
    border-left: 1px solid #e6ebf2;
    border-top: 0px;
    border-right: 0px;
    border-bottom: 0px;
}
QLabel#brand {
    color: #2672db;
    font-size: 19px;
    font-weight: 800;
}
QLabel#titleBlue, QLabel#sectionBlue {
    color: #1f67c7;
    font-weight: 800;
}
QLabel#titleBlue { font-size: 15px; }
QLabel#sectionBlue { font-size: 14px; }
QLabel#muted {
    color: #90a0b3;
    font-size: 12px;
}
QLabel#tinyMuted {
    color: #9aa8b8;
    font-size: 11px;
}
QLabel#mono {
    font-family: Consolas, "Microsoft YaHei UI";
}
QPushButton, QToolButton {
    background: #ffffff;
    color: #40556f;
    border: 1px solid #dde5ef;
    border-radius: 7px;
    padding: 6px 12px;
}
QPushButton:hover, QToolButton:hover {
    background: #eef5ff;
    border-color: #9fc3ff;
}
QPushButton:pressed, QToolButton:pressed {
    background: #dfeeff;
}
QPushButton#primary {
    color: white;
    background: #2d7ef1;
    border: 1px solid #2d7ef1;
    font-weight: 700;
}
QPushButton#primary:hover {
    background: #1f6fe0;
}
QPushButton#green {
    color: white;
    background: #17b283;
    border: 1px solid #17b283;
    font-weight: 700;
}
QPushButton#green:hover {
    background: #099b6e;
}
QPushButton#danger {
    color: #c74b5c;
    font-weight: 700;
}
QPushButton#flatTool, QToolButton#flatTool {
    background: transparent;
    border: 0px;
    color: #4b6078;
    padding: 5px 8px;
    font-size: 14px;
}
QPushButton#flatTool:hover, QToolButton#flatTool:hover {
    background: #edf4ff;
    border-radius: 7px;
}
QPushButton#flatTool:checked, QToolButton#flatTool:checked {
    background: #e8f1ff;
    color: #1f67c7;
    border: 1px solid #cfe0f8;
    border-radius: 7px;
    font-weight: 700;
}
QPushButton#hexMode {
    font-size: 14px;
    font-weight: 700;
    min-width: 46px;
}
QPushButton#hexMode:checked {
    background: #e8f1ff;
    color: #1f67c7;
    border-color: #9fc3ff;
    font-weight: 700;
}
QToolButton#addCmd {
    background: transparent;
    border: 0px;
    color: #4b6078;
    padding: 5px 8px;
    font-size: 14px;
}
QToolButton#addCmd:hover {
    background: #edf4ff;
    border-radius: 7px;
}
QToolButton#addCmd::menu-indicator {
    image: none;
    width: 0px;
    height: 0px;
}
QToolButton#panelBtn {
    min-width: 26px;
    min-height: 26px;
    max-width: 26px;
    max-height: 26px;
    border-radius: 8px;
    background: transparent;
    border: 1px solid transparent;
    padding: 0px;
}
QToolButton#panelBtn:hover {
    background: #ffffff;
    border-color: #d6e1ef;
}
QToolButton#panelBtn:pressed {
    background: #eef5ff;
    border-color: #cfe0f8;
}
QPushButton#railBtn, QToolButton#railBtn {
    min-width: 38px;
    min-height: 38px;
    max-width: 38px;
    max-height: 38px;
    border-radius: 11px;
    background: transparent;
    border: 0px;
    padding: 0px;
}
QPushButton#railBtn:hover, QToolButton#railBtn:hover {
    background: #ffffff;
    border: 1px solid #d6e1ef;
}
QPushButton#railBtn:checked, QToolButton#railBtn:checked {
    background: #ffffff;
    border: 1px solid #cfe0f8;
}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background: #ffffff;
    border: 1px solid #d8e1ec;
    border-radius: 7px;
    min-height: 30px;
    padding: 1px 8px;
    color: #23364b;
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
    border-color: #69a2f2;
}
QComboBox::drop-down {
    border: 0px;
    width: 20px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d8e1ec;
    selection-background-color: #2d7ef1;
    selection-color: #ffffff;
    outline: 0px;
}
QPlainTextEdit {
    background: #ffffff;
    color: #364a61;
    border: 0px;
    selection-background-color: #c6dcff;
    font-family: Consolas, "Microsoft YaHei UI";
    font-size: 12px;
}
QScrollArea {
    border: 0px;
    background: transparent;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QDialog {
    background: #ffffff;
}
QMenu {
    background: #ffffff;
    border: 1px solid #e1e8f2;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    padding: 7px 26px 7px 20px;
    border-radius: 6px;
    color: #364a61;
}
QMenu::item:selected {
    background: #eef5ff;
    color: #1f67c7;
}
QMenu::item:disabled {
    color: #b6c0cc;
}
QMenu::separator {
    height: 1px;
    background: #eef2f7;
    margin: 5px 8px;
}
QMenu::indicator {
    subcontrol-origin: padding;
    subcontrol-position: center left;
    left: 8px;
    width: 14px;
    height: 14px;
    border: 1px solid #c3cedd;
    border-radius: 4px;
    background: #ffffff;
}
QMenu::indicator:hover {
    border-color: #9fc3ff;
}
QMenu::indicator:checked {
    background: #2d7ef1;
    border-color: #2d7ef1;
}
QCheckBox {
    spacing: 4px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1.5px solid #c3cedd;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #9fc3ff;
}
QCheckBox::indicator:checked {
    background: #2d7ef1;
    border-color: #2d7ef1;
}
QSlider {
    min-height: 22px;
    background: transparent;
}
QSlider::groove:horizontal {
    height: 6px;
    border-radius: 3px;
    background: #e8eef7;
}
QSlider::sub-page:horizontal {
    background: #2d7ef1;
    border-radius: 3px;
}
QSlider::add-page:horizontal {
    background: #e8eef7;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -5px 0px;
    border-radius: 7px;
    border: 2px solid #2d7ef1;
    background: #ffffff;
}
QSlider::handle:horizontal:hover {
    background: #eef5ff;
}
QSlider::handle:horizontal:disabled {
    border-color: #c3cedd;
}
QLabel#emptyHint {
    color: #aab6c6;
    font-size: 12px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 0px;
    border: 0px;
}
QSplitter::handle {
    background: #e8edf4;
}
QTabBar::tab {
    background: #eef2f8;
    color: #40556f;
    border: 1px solid #e6ebf2;
    border-bottom: 0px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 7px 16px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #1f67c7;
    font-weight: 700;
}
QStatusBar {
    background: #ffffff;
    color: #7b8798;
    border-top: 1px solid #e6ebf2;
}
"""
