"""VOFA+ 风格的颜色、尺寸、字体与全局样式表（浅色 / 深色两套）。"""

import re

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

# 滑块组配色：自动分配，也用于右键一键换色
GROUP_COLORS = [
    "#2D7EF1",
    "#17B283",
    "#9B6DFF",
    "#FF9C3D",
    "#00B9C7",
    "#EF5350",
]
GROUP_COLOR_LABELS = ["蓝", "绿", "紫", "橙", "青", "红"]

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
QFrame#drawer, QFrame#rightbar, QFrame#plotCard, QFrame#bottomCard, QFrame#infoCard, QFrame#displayPanel {
    background: #ffffff;
    border: 1px solid #e6ebf2;
    border-radius: 10px;
}
QFrame#displayCard {
    background: #f7f9fc;
    border: 1px solid #e6ebf2;
    border-radius: 10px;
}
QLabel#displayTitle {
    color: #24374a;
    font-size: 13px;
    font-weight: 700;
}
QToolButton#displayAdd {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 0px;
}
QToolButton#displayAdd:hover {
    background: #e8f1ff;
    border-color: #cfe0f8;
}
QToolButton#displayClose {
    background: transparent;
    border: 0px;
    padding: 0px;
}
QToolButton#displayClose:hover {
    background: #fdf3f5;
    border-radius: 6px;
}
QPushButton#unitBtn {
    background: #eef2f7;
    border: 1px solid #dde5ef;
    border-radius: 7px;
    color: #4b6078;
    font-family: Consolas, "Microsoft YaHei UI";
    font-size: 12px;
    font-weight: 700;
    padding: 0px;
}
QPushButton#unitBtn[unitSegment="first"] {
    border-top-right-radius: 0px;
    border-bottom-right-radius: 0px;
}
QPushButton#unitBtn[unitSegment="last"] {
    border-top-left-radius: 0px;
    border-bottom-left-radius: 0px;
    border-left: 0px;
}
QPushButton#unitBtn:hover {
    background: #edf4ff;
    border-color: #9fc3ff;
    color: #1f67c7;
}
QPushButton#unitBtn:checked {
    background: #2d7ef1;
    border-color: #2d7ef1;
    color: #fdfdfd;
}
QComboBox#axisBind {
    min-height: 26px;
    padding: 1px 6px;
    font-size: 12px;
}
QLabel#axisValue {
    color: #4b6078;
    font-family: Consolas, "Microsoft YaHei UI";
    font-size: 12px;
}
QScrollArea#displayScroll, QWidget#displayList {
    background: transparent;
    border: 0px;
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
    background: #ffffff;
    border: 1px solid #f0d2d8;
}
QPushButton#danger:hover {
    background: #fdf3f5;
}
QPushButton#flatTool, QToolButton#flatTool {
    background: transparent;
    border: 0px;
    color: #4b6078;
    padding: 6px 10px;
    min-height: 26px;
    font-size: 14px;
}
QPushButton#flatTool:hover, QToolButton#flatTool:hover {
    background: #edf4ff;
    border-radius: 7px;
}
QToolButton#flatTool::menu-indicator {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    right: 6px;
    width: 8px;
    height: 8px;
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
QPushButton#rxModeBtn {
    background: #eef2f7;
    border: 1px solid #dde5ef;
    border-radius: 8px;
    padding: 5px 12px;
    color: #4b6078;
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
    font-weight: 700;
}
QPushButton#rxModeBtn:hover {
    background: #edf4ff;
    border-color: #9fc3ff;
    color: #1f67c7;
}
QPushButton#rxModeBtn:checked {
    background: #2d7ef1;
    border-color: #2d7ef1;
    color: #fdfdfd;
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
    width: 18px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #7b8798;
    width: 0px;
    height: 0px;
    margin-right: 5px;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {
    border-color: #9fc3ff;
}
QComboBox QLineEdit {
    background: transparent;
    border: 0px;
    padding: 0px 2px;
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
    background: #eceff4;
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
    background: #fdfdfd;
}
QSlider::handle:horizontal:hover {
    background: #eef5ff;
}
QSlider::handle:horizontal:disabled {
    border-color: #c3cedd;
}
QLabel#statValue {
    color: #24374a;
    font-family: Consolas, "Microsoft YaHei UI";
    font-size: 13px;
    font-weight: 800;
}
QLabel#statTx {
    color: #7b8798;
    font-family: Consolas, "Microsoft YaHei UI";
    font-size: 13px;
    font-weight: 700;
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
QTabBar::tab:hover {
    background: #eef5ff;
    color: #1f67c7;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #1f67c7;
    font-weight: 700;
}
QCheckBox:hover {
    color: #1f67c7;
}
QStatusBar {
    background: #ffffff;
    color: #7b8798;
    border-top: 1px solid #e6ebf2;
}
QFrame#vline, QFrame#hr {
    background: #e6ebf2;
    border: 0px;
}
QLabel#versionPill {
    color: #1f67c7;
    background: rgba(45, 126, 241, 0.10);
    border-radius: 9px;
    padding: 1px 8px;
    font-size: 11px;
    font-weight: 800;
}
QToolButton#iconBtn {
    min-width: 26px;
    min-height: 26px;
    max-width: 26px;
    max-height: 26px;
    border-radius: 8px;
    background: transparent;
    border: 1px solid transparent;
    padding: 0px;
}
QToolButton#iconBtn:hover {
    background: #eef5ff;
    border-color: #d6e1ef;
}
QToolButton#iconBtn:checked {
    background: #e8f1ff;
    border-color: #cfe0f8;
}
QPushButton#autoBtn {
    font-size: 18px;
    font-style: italic;
    font-weight: 800;
    color: #9aa8b8;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 2px 4px;
}
QPushButton#autoBtn:hover {
    color: #1f67c7;
    background: #eef5ff;
}
QPushButton#autoBtn:checked {
    color: #1f67c7;
    background: #e8f1ff;
    border-color: #cfe0f8;
}
QToolButton#viewBtn {
    min-width: 0px;
    background: #eef2f7;
    border: 1px solid #dde5ef;
    border-radius: 8px;
    color: #4b6078;
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
    font-weight: 800;
    padding: 0px;
}
QToolButton#viewBtn[viewSegment="first"] {
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
}
QToolButton#viewBtn[viewSegment="last"] {
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
    border-left: 0;
}
QToolButton#viewBtn:hover {
    background: #edf4ff;
    border-color: #9fc3ff;
    color: #1f67c7;
}
QToolButton#viewBtn:checked {
    background: #2d7ef1;
    border-color: #2d7ef1;
    color: #fdfdfd;
}
QToolButton#themeCard {
    background: #ffffff;
    border: 1px solid #e6ebf2;
    border-radius: 12px;
    padding: 10px 6px 8px 6px;
    color: #4b6078;
    font-size: 12px;
    font-weight: 700;
}
QToolButton#themeCard:hover {
    border-color: #9fc3ff;
    background: #f7fbff;
}
QToolButton#themeCard:checked {
    border: 2px solid #2d7ef1;
    background: #eef5ff;
    color: #1f67c7;
}
"""

# 深色主题：参考 VS Code Dark+ 的中性灰底 + 蓝色强调
# 仍采用「对浅色样式表做颜色映射」的做法，保证两套主题选择器完全一致
_DARK_MAP = {
    # 画布 / 面板
    "#f5f7fb": "#1e1e1e",  # 窗口底
    "#ffffff": "#252526",  # 卡片 / 输入框 / 菜单
    "#f7f9fc": "#2d2d2d",
    "#eef2f7": "#252526",  # 侧栏
    "#eef2f8": "#252526",  # 标签栏
    # 描边
    "#e6ebf2": "#3c3c3c",
    "#e9eef6": "#3c3c3c",
    "#e1e8f2": "#3c3c3c",
    "#e2e8f0": "#3c3c3c",
    "#e8edf4": "#3c3c3c",
    "#e8eef7": "#3c3c3c",
    "#eceff4": "#3c3c3c",
    "#f0d2d8": "#5a1d1d",
    "#dde5ef": "#3c3c3c",
    "#d8e1ec": "#3c3c3c",
    "#d6e1ef": "#454545",
    "#c3cedd": "#6b6b6b",
    "#fdfdfd": "#d4d4d4",  # 滑块手柄
    # 交互底色
    "#eef5ff": "#2a2d2e",
    "#edf4ff": "#2a2d2e",
    "#f7fbff": "#2a2d2e",
    "#dfeeff": "#0a4d78",
    "#e8f1ff": "#094771",
    "#cfe0f8": "#007acc",
    "#9fc3ff": "#007acc",
    "#69a2f2": "#007acc",
    "#c6dcff": "#264f78",
    "#fdf3f5": "#2a1a1d",
    # 文字
    "#24374a": "#d4d4d4",
    "#23364b": "#d4d4d4",
    "#364a61": "#cccccc",
    "#40556f": "#cccccc",
    "#4b6078": "#cccccc",
    "#7b8798": "#9d9d9d",
    "#90a0b3": "#8b8b8b",
    "#9aa8b8": "#858585",
    "#aab6c6": "#7a7a7a",
    "#b6c0cc": "#656565",
    # 强调色
    "#2d7ef1": "#0e639c",
    "#1f6fe0": "#1177bb",
    "#1f67c7": "#3794ff",
    "#2672db": "#4daafc",
    "#c74b5c": "#f48771",
}


def _build_dark_style() -> str:
    return re.sub(
        r"#[0-9a-fA-F]{6}",
        lambda m: _DARK_MAP.get(m.group(0).lower(), m.group(0)),
        APP_STYLE,
    )


DARK_STYLE = _build_dark_style()


def app_style(dark: bool = False) -> str:
    """返回全局样式表：dark=True 为深色主题。"""
    return DARK_STYLE if dark else APP_STYLE
