"""数据链路：接收解析、日志与数值灌入波形。"""
from __future__ import annotations

import re
import struct
import time

from PySide6.QtWidgets import QFileDialog
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Slot

from ..plot_widget import MAX_CHANNELS
from ..plot_widget import PlotPage


class SignalsMixin:
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
            # 模拟模式也让日志里有 RX 反馈：每 200ms 一行，不按帧刷屏
            now = time.monotonic()
            if now - self._last_demo_value_log >= 0.2:
                self._last_demo_value_log = now
                cells = []
                for i, value in enumerate(processed):
                    name = self.channel_names[i] if i < len(self.channel_names) else f"I{i}"
                    cells.append(f"{name}={value:+.3f}")
                self.log_rx("[模拟RX] " + "  ".join(cells), kind="rx")
        if not from_demo and not self.rx_hex_mode and self.engine_name == "JustFloat":
            now = time.monotonic()
            if now - self._last_value_log >= 0.15:
                self._last_value_log = now
                text = ", ".join(f"{v:.4f}" for v in processed)
                self.log_rx(text, kind="rx")

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
                    "[raw] " + self._format_rx_payload(preview) + suffix, kind="rx"
                )
            self.parse_rawdata(chunk)
            return
        if self.looks_like_ascii(chunk):
            self.rx_line_buffer.extend(chunk)
            while b"\n" in self.rx_line_buffer:
                line, _, rest = self.rx_line_buffer.partition(b"\n")
                self.rx_line_buffer = bytearray(rest)
                raw_line = bytes(line)
                text = raw_line.decode(errors="ignore").strip().replace("\r", "")
                if not text:
                    continue
                values = self.parse_ascii_float_line(text)
                if values:
                    if self.rx_hex_mode:
                        self.log_rx("[rx] " + raw_line.hex(" ").upper(), kind="rx")
                    else:
                        self.log_rx(text, kind="rx")
                    self.append_values(values)
        else:
            if self.rx_hex_mode:
                now = time.monotonic()
                if now - self._last_rx_hex_log >= 0.15:
                    self._last_rx_hex_log = now
                    preview = chunk[:512]
                    suffix = " …" if len(chunk) > len(preview) else ""
                    self.log_rx(
                        "[rx] " + preview.hex(" ").upper() + suffix, kind="rx"
                    )
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

    def log_rx(self, text: str, kind: str = "rx") -> None:
        line = text
        if self.stamp_log:
            line = f"{time.strftime('%H:%M:%S')} {text}"
        self.log_lines.append((kind, line))
        if len(self.log_lines) > 2000:
            del self.log_lines[: len(self.log_lines) - 2000]
        if self._log_visible(kind):
            self._append_log_text(line)

    def _format_rx_payload(self, data: bytes) -> str:
        if self.rx_hex_mode:
            return data.hex(" ").upper()
        return (
            data.decode(self.encoding, errors="replace")
            .replace("\r", "")
            .replace("\n", " ⏎ ")
        )

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
        # 只覆盖字号，配色交给全局样式表，这样深色模式才能跟着变
        size = self._log_font_size
        self.rx_text.setStyleSheet(
            "QPlainTextEdit{"
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

    def on_tick(self) -> None:
        if self.demo_enabled:
            self.generate_demo_data()
        self.update_plot()

    def update_plot(self) -> None:
        page = self.current_page()
        if not self.plot_paused:
            for target in self.pages:
                if target.isVisible():
                    target.refresh()
        self.update_stats(page)
        self._refresh_channel_values()
        if hasattr(self, "display_panel"):
            self.display_panel.refresh_from_data()
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
        self.tx_count_label.setText(str(self.total_tx))
        self.cur_index_label.setText(str(self.sample_index))
        span = page.time_span_ms()
        per_div = max(1.0, span / 8.0)
        self.scale_label.setText(f"{per_div:.0f}ms/格")
