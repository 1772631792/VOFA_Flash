"""波形页与变量：布局、变量编辑、游标、通道显示与事件过滤。"""
from __future__ import annotations


from PySide6.QtWidgets import QAbstractSpinBox
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QComboBox
from PySide6.QtWidgets import QDialog
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QFileDialog
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLineEdit
from PySide6.QtWidgets import QMenu
from PySide6.QtWidgets import QMessageBox
from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtWidgets import QTextEdit
from PySide6.QtCore import QTimer

from ..theme import CHANNEL_COLORS
from ..ui.common import ChannelRow
from ..plot_widget import FFT_SCALES
from ..plot_widget import FFT_WINDOWS
from ..plot_widget import MAX_CHANNELS
from ..ui.measure import MeasureDialog
from ..plot_widget import PlotPage
from ..ui.dialogs import VariableDialog


class PlotsMixin:
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
        page.set_diff_mode(bool(enabled))

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

    @staticmethod
    def _is_text_input(widget) -> bool:
        return isinstance(
            widget, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)
        ) or (isinstance(widget, QComboBox) and widget.isEditable())

    def _handle_cursor_shortcut(self, action: str) -> None:
        """仅在已暂停、且鼠标位于波形显示区内时有效。"""
        if not self.plot_paused:
            return
        # 找到鼠标实际所在的波形页（多窗口时可能不是当前选中页）
        page, abs_ms = None, None
        for candidate in self.pages:
            t = candidate.cursor_time_at_mouse()
            if t is not None:
                page, abs_ms = candidate, t
                break
        if page is None or abs_ms is None:  # 鼠标不在任何波形显示区内
            return
        if action == "cursor_toggle":
            if not page.diff_mode and all(t is None for t in page._diff_times):
                page.set_cursor_defaults()
                self.statusBar().showMessage("游标已显示（A 左 / B 右，可拖动微调）", 2500)
            else:
                page.set_diff_mode(not page.diff_mode)
                self.statusBar().showMessage(
                    "游标已显示" if page.diff_mode else "游标已隐藏", 2500
                )
            return
        index = 0 if action == "cursor_a" else 1
        page.begin_cursor_placement(index)
        self.statusBar().showMessage(
            f"请点击波形设置游标 {'AB'[index]}", 2500
        )

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
                    elif action in ("cursor_a", "cursor_b", "cursor_toggle"):
                        self._handle_cursor_shortcut(action)
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
