"""配置与数据文件：布局 JSON、CSV 导入导出与回放。"""
from __future__ import annotations

import csv
import json

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QFileDialog
from PySide6.QtWidgets import QMessageBox

from ..constants import ENGINES
from ..plot_widget import MAX_CHANNELS
from ..plot_widget import PlotPage


class ProfileMixin:
    def export_csv(
        self, path: str | bool | None = None, page: PlotPage | None = None
    ) -> None:
        """把指定波形页的缓冲数据导出为 CSV。"""
        page = page or self.current_page()
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

    def import_csv_replay(self, path: str | bool | None = None) -> None:
        """把本程序导出的 CSV（time_ms + 各通道）重新画成波形。"""
        if not isinstance(path, str):
            path, _ = QFileDialog.getOpenFileName(
                self, "导入 CSV 回放", "waveform.csv", "CSV 文件 (*.csv)"
            )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                rows = [row for row in csv.reader(fh) if row and any(c.strip() for c in row)]
        except (OSError, UnicodeError, csv.Error) as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        if not rows:
            QMessageBox.information(self, "没有数据", "CSV 文件是空的")
            return

        header = [cell.strip() for cell in rows[0]]
        data_rows = rows
        names: list[str] = []
        if header and header[0].lower() in ("time_ms", "time", "t", "时间", "时间/ms"):
            names = [name or f"I{i}" for i, name in enumerate(header[1 : MAX_CHANNELS + 1])]
            data_rows = rows[1:]

        parsed: list[tuple[float, list[float]]] = []
        for row in data_rows:
            try:
                t_ms = float(row[0])
            except (ValueError, IndexError):
                continue
            values: list[float] = []
            for cell in row[1 : MAX_CHANNELS + 1]:
                try:
                    values.append(float(cell))
                except ValueError:
                    values.append(0.0)
            while len(values) < MAX_CHANNELS:
                values.append(values[-1] if values else 0.0)
            parsed.append((t_ms, values[:MAX_CHANNELS]))
        if not parsed:
            QMessageBox.information(self, "没有数据", "CSV 中没有可回放的数值行")
            return

        # 回放时暂停真实数据源，避免新数据混进历史曲线；也不触发自动重连
        self.demo_enabled = False
        self._manual_disconnect = True
        self._reconnect_armed = False
        self.reconnect_timer.stop()
        if self.worker is not None or self.connected:
            self._disconnect()

        page_states = [
            (
                page.plot_mode,
                list(page.visible[:MAX_CHANNELS]),
                bool(page.auto_scale),
                dict(page.fft_settings),
                bool(page.diff_mode),
            )
            for page in self.pages
        ]
        data_columns = max((len(row) - 1 for row in data_rows), default=0)
        count = max(1, min(max(len(names), data_columns), MAX_CHANNELS))
        self.channel_count = count
        for i, name in enumerate(names[:MAX_CHANNELS]):
            self.channel_names[i] = name
        self._update_channel_rows()
        for page in self.pages:
            page.set_channel_count(0)
            page.clear_data()
            page.set_channel_count(count)
            for i in range(MAX_CHANNELS):
                page.set_channel_name(i, self.channel_names[i])
                page.set_channel_color(i, self.channel_colors[i])

        self.total_frames = 0
        self.sample_index = 0
        self.set_plot_paused(False, message=False)
        for t_ms, values in parsed:
            for page in self.pages:
                page.append_sample(values, t_ms=t_ms)
            self.total_frames += 1
            self.sample_index += 1
            self.last_values[:count] = values[:count]
        for page, (mode, visible, auto_scale, fft_settings, diff_mode) in zip(
            self.pages, page_states
        ):
            page.set_plot_mode(mode)
            for i in range(MAX_CHANNELS):
                page.set_visible(i, visible[i])
            page.set_auto_scale(auto_scale)
            page.set_diff_mode(diff_mode)
            page.set_fft_window(fft_settings.get("window", "hann"))
            page.set_fft_scale(fft_settings.get("scale", "percent"))
            page.set_fft_size(fft_settings.get("fft_size", 0))
        self._refresh_channel_values()
        self.update_plot()
        self.statusBar().showMessage(f"已回放 {len(parsed)} 行数据：{path}", 4000)

    def export_layout(self, path: str | bool | None = None) -> None:
        """把当前布局导出为 JSON，便于下次一键恢复。"""
        if not isinstance(path, str):
            path, _ = QFileDialog.getSaveFileName(
                self, "导出当前布局", "vofa_flash_layout.json", "JSON 文件 (*.json)"
            )
        if not path:
            return
        channels = {
            "count": self.channel_count,
            "names": list(self.channel_names[:MAX_CHANNELS]),
            "colors": list(self.channel_colors[:MAX_CHANNELS]),
            "gains": list(self.gains[:MAX_CHANNELS]),
            "offsets": list(self.offsets[:MAX_CHANNELS]),
            "decimals": list(self.channel_decimals[:MAX_CHANNELS]),
            "visible": [
                self.channel_rows[i].eye.isChecked() for i in range(MAX_CHANNELS)
            ],
        }
        pages = [
            {
                "visible": list(page.visible[:MAX_CHANNELS]),
                "auto_scale": bool(page.auto_scale),
                "plot_mode": page.plot_mode,
                "fft_settings": dict(page.fft_settings),
                "diff_mode": bool(page.diff_mode),
                "mode_locked": bool(self.page_mode_locked[index]),
            }
            for index, page in enumerate(self.pages)
        ]
        payload = {
            "format": "vofa-flash-layout",
            "version": 3,
            "window": {"geometry": bytes(self.saveGeometry()).hex()},
            "appearance": {"dark": self.dark},
            "plot": {
                "layout": self.plot_layout_mode,
                "auto_scale": bool(self.current_page().auto_scale),
                "dt_ms": self.dt_ms,
                "align": self.display_points,
                "splitter": list(self.plot_splitter.sizes()),
            },
            "pages": pages,
            "panels": {
                "body": list(self.body_splitter.sizes()),
                "center": list(self.center_splitter.sizes()),
                "vertical": list(self.center_vsplit.sizes()),
                "display_visible": self.display_panel.isVisible(),
                "drawer_visible": self.drawer.isVisible(),
                "data_collapsed": self._data_collapsed,
            },
            "channels": channels,
            "debug": {
                "engine": self.engine_name,
                "commands": [item.settings() for item in self._command_widgets()],
                "group_colors": dict(self._group_colors),
                "serial": {
                    "bits": self.serial_bits,
                    "parity": self.serial_parity,
                    "stopbits": self.serial_stopbits,
                    "flow": self.serial_flow,
                    "auto_reconnect": self.auto_reconnect,
                    "baud": self.baud_combo.currentText(),
                },
                "network": {
                    "host": self.net_host_edit.text(),
                    "port": self.net_port_spin.value(),
                },
                "encoding": self.encoding,
                "hex_mode": self.hex_mode,
                "rx_hex_mode": self.rx_hex_mode,
                "ending": self.ending_combo.currentIndex(),
                "sim_mode": self.sim_mode,
            },
        }
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.statusBar().showMessage(f"布局已导出：{path}", 4000)

    def import_layout(self, path: str | bool | None = None) -> None:
        """导入布局 JSON：窗口位置、面板宽度、显示模式与变量样式一起恢复。"""
        if not isinstance(path, str):
            path, _ = QFileDialog.getOpenFileName(
                self, "导入布局 JSON", "", "JSON 文件 (*.json)"
            )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        if not isinstance(data, dict) or data.get("format") != "vofa-flash-layout":
            QMessageBox.warning(self, "导入失败", "不是 VOFA+ Flash 布局 JSON 文件")
            return

        def pick(items, index: int, default):
            if isinstance(items, list) and index < len(items):
                return items[index]
            return default

        try:
            geometry_hex = str(data.get("window", {}).get("geometry", ""))
            if geometry_hex:
                self.restoreGeometry(QByteArray.fromHex(geometry_hex.encode("ascii")))

            dark = bool(data.get("appearance", {}).get("dark", self.dark))
            if dark != self.dark:
                self.apply_theme(dark)

            plot = data.get("plot", {})
            self.apply_wave_settings(
                float(plot.get("dt_ms", self.dt_ms)),
                int(plot.get("align", self.display_points)),
            )

            channels = data.get("channels", {})
            count = max(0, min(int(channels.get("count", self.channel_count)), MAX_CHANNELS))
            self.channel_count = count
            for i in range(MAX_CHANNELS):
                self.channel_names[i] = str(pick(channels.get("names"), i, self.channel_names[i]))
                self.channel_colors[i] = str(pick(channels.get("colors"), i, self.channel_colors[i]))
                try:
                    self.gains[i] = float(pick(channels.get("gains"), i, self.gains[i]))
                    self.offsets[i] = float(pick(channels.get("offsets"), i, self.offsets[i]))
                except (TypeError, ValueError):
                    pass
                try:
                    self.channel_decimals[i] = int(
                        pick(channels.get("decimals"), i, self.channel_decimals[i])
                    )
                except (TypeError, ValueError):
                    pass
            visible = [bool(value) for value in channels.get("visible", [])]
            pages_cfg = data.get("pages", [])
            auto_scale = bool(plot.get("auto_scale", True))
            for index, page in enumerate(self.pages):
                cfg = pages_cfg[index] if index < len(pages_cfg) else {}
                page_visible = [bool(v) for v in cfg.get("visible", visible)]
                page.set_channel_count(count)
                for i in range(MAX_CHANNELS):
                    page.set_channel_color(i, self.channel_colors[i])
                    page.set_channel_name(i, self.channel_names[i])
                    page.set_visible(i, page_visible[i] if i < len(page_visible) else True)
                page.set_auto_scale(bool(cfg.get("auto_scale", auto_scale)))
                page.set_plot_mode(str(cfg.get("plot_mode", "time")))
                page.set_diff_mode(bool(cfg.get("diff_mode", False)))
                fft_cfg = cfg.get("fft_settings", {})
                if isinstance(fft_cfg, dict):
                    if "window" in fft_cfg:
                        page.set_fft_window(str(fft_cfg["window"]))
                    if "scale" in fft_cfg:
                        page.set_fft_scale(str(fft_cfg["scale"]))
                    if "fft_size" in fft_cfg:
                        page.set_fft_size(int(fft_cfg["fft_size"]))
                self.page_mode_locked[index] = bool(cfg.get("mode_locked", False))

            panels = data.get("panels", {})
            self.set_data_panel_collapsed(
                bool(panels.get("data_collapsed", self._data_collapsed))
            )
            show_display = bool(panels.get("display_visible", self.display_panel.isVisible()))
            self.display_panel.setVisible(show_display)
            self.btn_widgets.setChecked(show_display)
            show_drawer = bool(panels.get("drawer_visible", self.drawer.isVisible()))
            self.drawer.setVisible(show_drawer)
            self.btn_cmd.setChecked(show_drawer)

            self.set_plot_layout(int(plot.get("layout", self.plot_layout_mode)), message=False)
            self._sync_auto_label_from_page(self.current_page())
            self._sync_variable_groups()
            self._update_channel_rows()

            def apply_sizes(splitter, sizes) -> None:
                if not isinstance(sizes, list) or len(sizes) != len(splitter.sizes()):
                    return
                splitter.setSizes([max(0, int(value)) for value in sizes])

            apply_sizes(self.body_splitter, panels.get("body"))
            apply_sizes(self.center_splitter, panels.get("center"))
            apply_sizes(self.center_vsplit, panels.get("vertical"))
            apply_sizes(self.plot_splitter, plot.get("splitter"))

            debug = data.get("debug", {})
            if isinstance(debug, dict):
                engine = str(debug.get("engine", self.engine_name))
                if engine in ENGINES:
                    self.engine_combo.setCurrentText(engine)
                serial_cfg = debug.get("serial", {})
                if isinstance(serial_cfg, dict):
                    self.serial_bits = int(serial_cfg.get("bits", self.serial_bits))
                    self.serial_parity = str(serial_cfg.get("parity", self.serial_parity))
                    self.serial_stopbits = int(serial_cfg.get("stopbits", self.serial_stopbits))
                    self.serial_flow = str(serial_cfg.get("flow", self.serial_flow))
                    self.auto_reconnect = bool(
                        serial_cfg.get("auto_reconnect", self.auto_reconnect)
                    )
                    baud = str(serial_cfg.get("baud", ""))
                    if baud:
                        self.baud_combo.setCurrentText(baud)
                    self._update_serial_fmt_text()
                    self._build_serial_fmt_menu()
                net_cfg = debug.get("network", {})
                if isinstance(net_cfg, dict):
                    self.net_host_edit.setText(
                        str(net_cfg.get("host", self.net_host_edit.text()))
                    )
                    self.net_port_spin.setValue(
                        int(net_cfg.get("port", self.net_port_spin.value()))
                    )
                codec = str(debug.get("encoding", self.encoding))
                if codec in ("utf-8", "gbk", "ascii"):
                    self.encoding = codec
                    label = {"utf-8": "UTF-8", "gbk": "GBK", "ascii": "ASCII"}[codec]
                    self.encoding_btn.setText(f"⌁ {label}")
                self.hex_mode = bool(debug.get("hex_mode", self.hex_mode))
                self._sync_tx_mode_ui()
                self.rx_hex_mode = bool(debug.get("rx_hex_mode", self.rx_hex_mode))
                self._sync_rx_mode_ui()
                self.ending_combo.setCurrentIndex(
                    max(0, min(2, int(debug.get("ending", self.ending_combo.currentIndex()))))
                )
                sim_mode = str(debug.get("sim_mode", self.sim_mode))
                if sim_mode in ("sine", "step", "pid"):
                    self.sim_mode = sim_mode
                colors = debug.get("group_colors", {})
                if isinstance(colors, dict):
                    self._group_colors = {
                        str(key): str(value) for key, value in colors.items()
                    }
                commands = debug.get("commands", [])
                if isinstance(commands, list):
                    for widget in self._command_widgets():
                        widget.setParent(None)
                        widget.deleteLater()
                    for cfg in commands:
                        if not isinstance(cfg, dict) or cfg.get("kind") not in (
                            "fixed",
                            "slider",
                        ):
                            continue
                        try:
                            item = self.add_command(
                                str(cfg["kind"]),
                                str(cfg.get("content", "")),
                                str(cfg.get("title") or ""),
                            )
                            item.apply_settings(cfg)
                        except (TypeError, ValueError):
                            continue
                    self._update_command_hint()
                    self._apply_group_styles()
                    self._refresh_command_previews()
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            QMessageBox.warning(self, "导入失败", f"布局文件无法解析：{exc}")
            return

        self.update_plot()
        self.statusBar().showMessage(f"布局已恢复：{path}", 4000)
