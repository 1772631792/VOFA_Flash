"""变量编辑对话框与设置对话框。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QKeySequenceEdit,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QWidget,
)

from ..theme import CHANNEL_COLORS
from .common import (
    SHORTCUT_DEFAULTS,
    SHORTCUT_LABELS,
    _ThemeCard,
    hbox,
    make_hr,
    make_label,
    vbox,
)

if TYPE_CHECKING:
    from ..main_window import MainWindow


class VariableDialog(QDialog):
    """添加/编辑变量：名称 + 曲线颜色 + 增益/偏置/小数位。"""

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


class _JsonDropArea(QFrame):
    """设置里的空白投放区：点击选文件，或直接把 .json 拖进来。"""

    clicked = Signal()
    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("jsonDrop")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(92)
        self.setStyleSheet(
            "#jsonDrop {"
            " border: 2px dashed #B9CCE3;"
            " border-radius: 10px;"
            " background: rgba(240,247,255,160);"
            "}"
            "#jsonDrop QLabel { color: #5C7189; }"
        )
        lay = vbox((8, 8, 8, 8), 2)
        title = make_label("点击导入布局 JSON", "sectionBlue", Qt.AlignmentFlag.AlignHCenter)
        hint = make_label("或把 .json 文件直接拖到这里", "tinyMuted", Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(title)
        lay.addWidget(hint)
        self.setLayout(lay)
        for label in (title, hint):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith(".json"):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".json"):
                self.fileDropped.emit(path)
                event.acceptProposedAction()
                return


class SettingsDialog(QDialog):
    """设置：外观、快捷键、布局 JSON 导出 / 导入。"""

    themeChanged = Signal(bool)
    shortcutsChanged = Signal(dict)
    simModeChanged = Signal(int)
    recordModeChanged = Signal(bool)

    def __init__(self, window: "MainWindow", parent=None):
        super().__init__(parent)
        self._window = window
        self.setWindowTitle("设置")
        self.setMinimumSize(520, 500)
        self._shortcut_edits: dict[str, QKeySequenceEdit] = {}

        root = vbox((18, 14, 18, 14), 10)
        root.addWidget(make_label("设置", "sectionBlue"))
        tabs = QTabWidget()
        tabs.addTab(self._appearance_tab(window.dark), "外观")
        tabs.addTab(self._shortcut_tab(window), "快捷键")
        tabs.addTab(self._layout_tab(), "布局")
        tabs.addTab(self._sim_tab(window.sim_mode), "模拟")
        tabs.addTab(self._record_tab(window.record_unlimited), "记录")
        root.addWidget(tabs, 1)

        buttons = hbox(spacing=8)
        buttons.addStretch(1)
        done_btn = QPushButton("完成")
        done_btn.setObjectName("primary")
        done_btn.setFixedWidth(88)
        done_btn.clicked.connect(self._on_done)
        buttons.addWidget(done_btn)
        root.addLayout(buttons)
        self.setLayout(root)

    def _sim_tab(self, mode: str) -> QWidget:
        page = QWidget()
        lay = vbox((18, 18, 18, 14), 10)
        lay.addWidget(make_label("模拟数据模式", "sectionBlue"))
        self.sim_combo = QComboBox()
        self.sim_combo.addItems(
            ["正弦扫描（当前）", "阶跃响应（自动控制）", "PID 响应（自动控制）"]
        )
        self.sim_combo.setCurrentIndex({"sine": 0, "step": 1, "pid": 2}.get(mode, 0))
        self.sim_combo.setToolTip("切换后波形数据从零重新开始")
        lay.addWidget(self.sim_combo)
        lay.addWidget(
            make_label(
                "阶跃 / PID 模式输出带超调的二阶阶跃曲线；\n"
                "暂停波形后可拖动 A / B 游标，再用「测量」按钮计算性能指标。",
                "tinyMuted",
            )
        )
        lay.addStretch(1)
        page.setLayout(lay)
        return page

    def _record_tab(self, enabled: bool) -> QWidget:
        page = QWidget()
        lay = vbox((18, 18, 18, 14), 10)
        lay.addWidget(make_label("连续记录模式", "sectionBlue"))
        self.record_check = QCheckBox("不限缓冲长度，一直记录全部数据")
        self.record_check.setChecked(bool(enabled))
        self.record_check.setToolTip("开启后不再按缓冲长度覆盖旧数据")
        lay.addWidget(self.record_check)
        lay.addWidget(
            make_label(
                "适合长时间观察曲线变化，历史数据不会被覆盖；\n"
                "关闭软件时会自动清除这些记录，不会保存到磁盘。",
                "tinyMuted",
            )
        )
        lay.addStretch(1)
        page.setLayout(lay)
        return page

    def _appearance_tab(self, dark: bool) -> QWidget:
        page = QWidget()
        lay = vbox((18, 18, 18, 14), 12)
        cards = hbox(spacing=14)
        self.light_card = _ThemeCard("浅色", "#F1F4F9", "#FFFFFF", "#2D7EF1")
        self.dark_card = _ThemeCard("深色", "#1E1E1E", "#252526", "#0E7ACC")
        self.light_card.setChecked(not dark)
        self.dark_card.setChecked(dark)
        cards.addWidget(self.light_card, 1)
        cards.addWidget(self.dark_card, 1)
        lay.addWidget(make_label("外观", "sectionBlue"))
        lay.addLayout(cards)

        lay.addWidget(make_label("语言", "sectionBlue"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("简体中文")
        self.lang_combo.addItem("English (coming soon)")
        item = self.lang_combo.model().item(1)
        if item is not None:
            item.setEnabled(False)
        lay.addWidget(self.lang_combo)
        lay.addWidget(make_label("语言切换入口已预留，后续版本开放。", "tinyMuted"))
        lay.addStretch(1)
        page.setLayout(lay)

        self.light_card.clicked.connect(lambda: self._choose(False))
        self.dark_card.clicked.connect(lambda: self._choose(True))
        return page

    def _shortcut_tab(self, window: "MainWindow") -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(18, 18, 18, 14)
        form.setSpacing(10)
        form.addRow(make_label("点击输入框后直接按组合键", "tinyMuted"))
        for key, label in SHORTCUT_LABELS.items():
            edit = QKeySequenceEdit(window.shortcuts.get(key, QKeySequence()), page)
            self._shortcut_edits[key] = edit
            form.addRow(label, edit)
        reset_btn = QPushButton("恢复默认快捷键")
        reset_btn.clicked.connect(self._reset_shortcuts)
        form.addRow("", reset_btn)
        return page

    def _layout_tab(self) -> QWidget:
        page = QWidget()
        lay = vbox((18, 18, 18, 14), 10)
        lay.addWidget(make_label("布局配置", "sectionBlue"))
        lay.addWidget(
            make_label("导出当前窗口布局为 JSON，下次可导入恢复。", "tinyMuted")
        )
        buttons = hbox(spacing=8)
        export_btn = QPushButton("导出当前布局…")
        export_btn.clicked.connect(self._export_layout_dialog)
        import_btn = QPushButton("导入布局…")
        import_btn.clicked.connect(self._import_layout_dialog)
        buttons.addWidget(export_btn)
        buttons.addWidget(import_btn)
        buttons.addStretch(1)
        lay.addLayout(buttons)

        drop = _JsonDropArea()
        drop.clicked.connect(self._import_layout_dialog)
        drop.fileDropped.connect(self._import_layout_path)
        lay.addWidget(drop, 1)
        self.layout_hint = make_label("", "tinyMuted")
        lay.addWidget(self.layout_hint)
        page.setLayout(lay)
        return page

    def _choose(self, dark: bool) -> None:
        self.light_card.setChecked(not dark)
        self.dark_card.setChecked(dark)
        self.themeChanged.emit(dark)

    def _reset_shortcuts(self) -> None:
        for key, text in SHORTCUT_DEFAULTS.items():
            edit = self._shortcut_edits.get(key)
            if edit is not None:
                edit.setKeySequence(QKeySequence(text))

    def _collect_shortcuts(self) -> dict[str, str] | None:
        mapping: dict[str, str] = {}
        used: dict[str, str] = {}
        for key, edit in self._shortcut_edits.items():
            sequence = edit.keySequence()
            if sequence.isEmpty():
                continue
            text = sequence.toString()
            if text in used:
                QMessageBox.warning(
                    self,
                    "快捷键冲突",
                    f"「{SHORTCUT_LABELS[key]}」与「{SHORTCUT_LABELS[used[text]]}」"
                    f"都使用了 {text}，请修改其中一个。",
                )
                return None
            used[text] = key
            mapping[key] = text
        return mapping

    def _on_done(self) -> None:
        mapping = self._collect_shortcuts()
        if mapping is None:
            return
        self.shortcutsChanged.emit(mapping)
        self.simModeChanged.emit(self.sim_combo.currentIndex())
        self.recordModeChanged.emit(self.record_check.isChecked())
        self.accept()

    def _export_layout_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出当前布局", "vofa_flash_layout.json", "JSON 文件 (*.json)"
        )
        if not path:
            return
        self._window.export_layout(path)
        self.layout_hint.setText(f"已导出：{path}")

    def _import_layout_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入布局 JSON", "", "JSON 文件 (*.json)"
        )
        if path:
            self._import_layout_path(path)

    def _import_layout_path(self, path: str) -> None:
        self._window.import_layout(path)
        self.layout_hint.setText(f"已导入：{path}")
