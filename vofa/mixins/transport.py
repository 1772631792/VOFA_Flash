"""传输与接口：串口/网络/模拟模式的连接管理与收发。"""
from __future__ import annotations


from PySide6.QtWidgets import QMenu
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Slot
import serial.tools.list_ports

from ..transport import BaseTransport
from ..serial_worker import SerialWorker
from ..transport import TcpClientTransport
from ..transport import TcpServerTransport
from ..transport import UdpTransport
from ..settings import save_setting


class TransportMixin:
    def on_engine_changed(self, name: str) -> None:
        self.engine_name = name
        self.justfloat.reset()
        self.rx_line_buffer.clear()
        self.raw_frame_bytes.clear()
        self.log_rx(f"[engine] {name}", kind="tx")
        self.statusBar().showMessage(f"数据引擎切换为 {name}", 3000)

    def on_iface_changed(self, name: str) -> None:
        if self.worker is not None or self.connected:
            self._manual_disconnect = True
            self._reconnect_armed = False
            self.reconnect_timer.stop()
            self._disconnect()
        self.interface_name = name
        self.set_plot_paused(False, message=False)
        self._reset_variables(reset_style=True)
        self._sync_param_panel(name)
        self._sync_pid_group()
        if name == "模拟模式":
            self.demo_enabled = False
            self._set_link_state(False)
            self.mode_tag.setText("● 模拟模式")
            self.mode_tag.setObjectName("primary")
            self.statusBar().showMessage(
                "已进入模拟模式：点击右上角「模拟模式」或顶栏「连接」开始输出模拟数据", 4000
            )
        else:
            self.demo_enabled = False
            self._set_link_state(False)
            self.mode_tag.setText("● 模拟模式")
            self.mode_tag.setObjectName("primary")
            self.statusBar().showMessage(f"接口切换为 {name}", 3000)
        self.mode_tag.style().polish(self.mode_tag)

    def _sync_param_panel(self, name: str) -> None:
        if name == "串口":
            self.param_stack.setCurrentIndex(0)
        elif name == "模拟模式":
            self.param_stack.setCurrentIndex(2)
        else:
            self.param_stack.setCurrentIndex(1)
            hints = {
                "UDP": ("127.0.0.1", 8886),
                "TCP客户端": ("127.0.0.1", 8886),
                "TCP服务端": ("0.0.0.0", 8886),
            }
            host, port = hints.get(name, ("127.0.0.1", 8886))
            self.net_host_edit.setText(host)
            self.net_port_spin.setValue(port)

        # QStackedWidget 默认取所有页里最宽的那个，切换到模拟模式时会留下大片空白。
        # 只按当前页给宽度，后面的连接按钮就能紧跟着参数。
        page = self.param_stack.currentWidget()
        if page is not None:
            self.param_stack.setFixedWidth(page.sizeHint().width())

    def toggle_demo(self) -> None:
        """右上角按钮：只在「模拟模式 / 模拟中」之间切换，始终不显示串口。"""
        if self.interface_name != "模拟模式":
            self.iface_combo.setCurrentText("模拟模式")
            if not self.demo_enabled:
                self._toggle_demo_stream()
            return
        self._toggle_demo_stream()

    def _build_serial_fmt_menu(self) -> None:
        menu = self.serial_fmt_menu
        menu.clear()
        for title, attr, options in (
            ("数据位", "serial_bits", [8, 7]),
            ("校验位", "serial_parity", ["None", "Even", "Odd"]),
            ("停止位", "serial_stopbits", [1, 2]),
            ("流控", "serial_flow", ["None", "Hardware", "Software"]),
        ):
            sub = QMenu(title, menu)
            menu.addMenu(sub)
            current = getattr(self, attr)
            for option in options:
                act = sub.addAction(str(option))
                act.setCheckable(True)
                act.setChecked(option == current)
                act.triggered.connect(
                    lambda _=False, a=attr, o=option: self._set_serial_param(a, o)
                )
        menu.addSeparator()
        reconnect_act = menu.addAction("串口自动重连")
        reconnect_act.setCheckable(True)
        reconnect_act.setChecked(self.auto_reconnect)
        reconnect_act.setToolTip("端口意外断开后自动重连上次端口（手动断开不会重连）")
        reconnect_act.toggled.connect(self._set_auto_reconnect)
        menu.addAction("恢复默认 8N1", self._reset_serial_fmt)

    def _set_auto_reconnect(self, enabled: bool) -> None:
        self.auto_reconnect = bool(enabled)
        save_setting("serial/auto_reconnect", self.auto_reconnect)
        if not self.auto_reconnect:
            self.reconnect_timer.stop()
        self.statusBar().showMessage(
            "串口自动重连已开启" if enabled else "串口自动重连已关闭", 2000
        )

    def _set_serial_param(self, attr: str, value) -> None:
        setattr(self, attr, value)
        self._update_serial_fmt_text()
        self._build_serial_fmt_menu()

    def _reset_serial_fmt(self) -> None:
        self.serial_bits = 8
        self.serial_parity = "None"
        self.serial_stopbits = 1
        self.serial_flow = "None"
        self._update_serial_fmt_text()
        self._build_serial_fmt_menu()

    def _update_serial_fmt_text(self) -> None:
        parity = {"None": "N", "Even": "E", "Odd": "O"}.get(
            self.serial_parity, "N"
        )
        text = f"{self.serial_bits}{parity}{self.serial_stopbits}"
        if self.serial_flow == "Hardware":
            text += " RTS"
        elif self.serial_flow == "Software":
            text += " XON"
        self.serial_fmt_btn.setText(text)
        self.statusBar().showMessage(f"串口格式：{text}", 3000)

    @staticmethod
    def _real_ports() -> list[str]:
        """只返回真实存在的串口，不使用 refresh_ports 的演示占位端口。"""
        try:
            return [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return []

    def _restore_serial_selection(self) -> None:
        if self._last_serial_baud:
            self.baud_combo.setCurrentText(self._last_serial_baud)
        ports = self._real_ports()
        if self._last_serial_port and self._last_serial_port in ports:
            self.port_combo.setCurrentText(self._last_serial_port)

    def _should_auto_reconnect(self) -> bool:
        return (
            self.auto_reconnect
            and self.interface_name == "串口"
            and self._reconnect_armed
            and not self._manual_disconnect
            and self.worker is None
            and not self.connected
        )

    def _schedule_reconnect(self) -> None:
        if self.reconnect_timer.isActive() or not self._should_auto_reconnect():
            return
        self.mode_tag.setText("● 等待重连")
        self.mode_tag.setObjectName("primary")
        self.mode_tag.style().polish(self.mode_tag)
        self.statusBar().showMessage("串口已断开，1.5 秒后自动重连…", 3000)
        self.reconnect_timer.start(1500)

    def _auto_reconnect_attempt(self) -> None:
        if not self._should_auto_reconnect():
            self.reconnect_timer.stop()
            return
        port = self._last_serial_port or self.port_combo.currentText().strip()
        if not port or port not in self._real_ports():
            # 设备还没插回来：保持定时检查，不弹窗打扰
            self.reconnect_timer.start(1500)
            return
        self.port_combo.setCurrentText(port)
        if self._last_serial_baud:
            self.baud_combo.setCurrentText(self._last_serial_baud)
        self._manual_disconnect = False
        self._auto_connecting = True
        self.statusBar().showMessage(f"正在自动重连 {port} …", 2000)
        self._connect()

    def refresh_ports(self, silent: bool = False) -> None:
        """刷新串口列表；silent 为定时自动刷新，不打断下拉与状态栏。"""
        if silent and self.port_combo.view().isVisible():
            return
        current = self.port_combo.currentText()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if not ports:
            ports = ["COM4", "COM3", "COM1"]
        existing = [self.port_combo.itemText(i) for i in range(self.port_combo.count())]
        if silent and ports == existing:
            return
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        if current in ports:
            self.port_combo.setCurrentText(current)
        if not silent:
            self.statusBar().showMessage(f"已刷新串口：{len(ports)} 个", 2000)

    def toggle_link(self) -> None:
        if self.interface_name == "模拟模式":
            self._toggle_demo_stream()
            return
        if self.worker is not None or self.connected:
            self._manual_disconnect = True
            self._reconnect_armed = False
            self.reconnect_timer.stop()
            self._disconnect()
            self.statusBar().showMessage("已断开连接", 3000)
            return
        self._manual_disconnect = False
        self._reconnect_armed = True
        self.reconnect_timer.stop()
        self._connect()

    def _toggle_demo_stream(self) -> None:
        """模拟模式：连接按钮控制模拟数据流连接 / 断开，断开后可移动鼠标看波形数值。"""
        self.demo_enabled = not self.demo_enabled
        self._set_link_state(self.demo_enabled)
        self.set_plot_paused(not self.demo_enabled, message=False)
        if self.demo_enabled:
            self.mode_tag.setText("● 模拟中")
            self.mode_tag.setObjectName("green")
            self.statusBar().showMessage("模拟数据流已连接，可发送命令", 3000)
        else:
            self.mode_tag.setText("● 模拟模式")
            self.mode_tag.setObjectName("primary")
            self.statusBar().showMessage(
                "模拟数据流已断开：移动鼠标查看数值，按空格恢复波形刷新", 4000
            )
        self.mode_tag.style().polish(self.mode_tag)

    def _set_link_state(self, connected: bool) -> None:
        self.connected = bool(connected)
        if connected:
            self.link_btn.setText("断开")
            self.link_btn.setObjectName("danger")
        else:
            self.link_btn.setText("连接")
            self.link_btn.setObjectName("primary")
        # objectName 变了要重新 polish，否则旧的背景 / 文字色会残留
        self.link_btn.style().unpolish(self.link_btn)
        self.link_btn.style().polish(self.link_btn)

    def _connect(self) -> None:
        self.reconnect_timer.stop()
        name = self.interface_name
        worker: SerialWorker | BaseTransport
        if name == "串口":
            port = self.port_combo.currentText().strip()
            if not port:
                if not self._auto_connecting:
                    QMessageBox.warning(self, "参数错误", "请选择串口端口")
                return
            try:
                baud = int(self.baud_combo.currentText().strip())
            except ValueError:
                if not self._auto_connecting:
                    QMessageBox.warning(self, "参数错误", "波特率必须是整数")
                return
            worker = SerialWorker(
                port,
                baud,
                bytesize=self.serial_bits,
                parity=self.serial_parity,
                stopbits=self.serial_stopbits,
                flow=self.serial_flow,
                parent=self,
            )
        elif name == "UDP":
            worker = UdpTransport(
                self.net_host_edit.text().strip(), self.net_port_spin.value(), parent=self
            )
        elif name == "TCP客户端":
            host = self.net_host_edit.text().strip()
            if not host:
                QMessageBox.warning(self, "参数错误", "请填写服务端 IP 地址")
                return
            worker = TcpClientTransport(host, self.net_port_spin.value(), parent=self)
        elif name == "TCP服务端":
            host = self.net_host_edit.text().strip() or "0.0.0.0"
            worker = TcpServerTransport(host, self.net_port_spin.value(), parent=self)
        else:
            self.statusBar().showMessage("模拟模式无需连接，仍可发送命令", 3000)
            return

        self.worker = worker
        worker.raw_received.connect(self.on_raw)
        worker.error_occurred.connect(self.on_error)
        worker.connected.connect(self.on_connected)
        worker.disconnected.connect(self.on_disconnected)
        worker.start()
        self.link_btn.setText("连接中…")
        self.statusBar().showMessage(f"正在打开 {name} …", 3000)

    def _disconnect(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.stop()
        self.on_disconnected()

    @Slot()
    def on_connected(self) -> None:
        self._set_link_state(True)
        self.demo_enabled = False
        self._auto_connecting = False
        self._manual_disconnect = False
        self._reconnect_armed = True
        self.justfloat.reset()
        self.rx_line_buffer.clear()
        self.raw_frame_bytes.clear()
        if self.interface_name == "串口":
            port = self.port_combo.currentText().strip()
            baud = self.baud_combo.currentText().strip()
            if port:
                self._last_serial_port = port
                save_setting("serial/last_port", port)
            if baud:
                self._last_serial_baud = baud
                save_setting("serial/last_baud", baud)
        self.mode_tag.setText("● 已连接")
        self.mode_tag.setObjectName("primary")
        self.mode_tag.style().polish(self.mode_tag)
        self.log_rx(f"[link] {self.interface_name} 已连接", kind="tx")
        self.statusBar().showMessage(f"{self.interface_name} 已连接", 4000)

    @Slot()
    def on_disconnected(self) -> None:
        if self.sender() is self.worker and self.worker is not None:
            # 后台线程主动掉线：清掉失效 worker，才能进入自动重连流程
            self.worker = None
        self._set_link_state(False)
        if self.interface_name == "模拟模式":
            running = self.demo_enabled
            self.mode_tag.setText("● 模拟中" if running else "● 模拟模式")
            self.mode_tag.setObjectName("green" if running else "primary")
        else:
            self.mode_tag.setText("● 模拟模式")
            self.mode_tag.setObjectName("primary")
        self.mode_tag.setObjectName("green" if self.demo_enabled else "primary")
        self.mode_tag.style().polish(self.mode_tag)
        self._reset_variables(reset_style=True)
        self.statusBar().showMessage("已断开连接", 3000)
        self._auto_connecting = False
        if self._should_auto_reconnect():
            self._schedule_reconnect()

    @Slot(str)
    def on_error(self, message: str) -> None:
        auto_retry = self._auto_connecting
        self.log_rx(f"[error] {message}", kind="tx")
        if not auto_retry:
            QMessageBox.warning(self, "接口错误", message)
        self._disconnect()

    def _sync_tx_mode_ui(self) -> None:
        self._syncing_tx_mode = True
        self.tx_mode_btn.setChecked(self.hex_mode)
        self.tx_mode_btn.setText("Hex" if self.hex_mode else "Abc")
        self._syncing_tx_mode = False

    def on_tx_mode_toggled(self, checked: bool) -> None:
        if getattr(self, "_syncing_tx_mode", False):
            return
        self.set_hex_mode(checked)

    def set_hex_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        changed = enabled != self.hex_mode
        self.hex_mode = enabled
        self._sync_tx_mode_ui()
        if changed:
            self.statusBar().showMessage(
                "发送格式：Hex" if enabled else "发送格式：文本(Abc)", 2000
            )

    def _sync_rx_mode_ui(self) -> None:
        self._syncing_rx_mode = True
        self.rx_mode_btn.setChecked(self.rx_hex_mode)
        self.rx_mode_btn.setText("Hex" if self.rx_hex_mode else "Abc")
        self.rx_mode_btn.setToolTip(
            "接收显示：Hex（点击切换为 Abc）"
            if self.rx_hex_mode
            else "接收显示：Abc（点击切换为 Hex）"
        )
        self._syncing_rx_mode = False

    def on_rx_mode_toggled(self, checked: bool) -> None:
        if getattr(self, "_syncing_rx_mode", False):
            return
        self.set_rx_hex_mode(checked)

    def set_rx_hex_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        changed = enabled != self.rx_hex_mode
        self.rx_hex_mode = enabled
        self._sync_rx_mode_ui()
        if changed:
            self.statusBar().showMessage(
                "接收显示：Hex 原始字节" if enabled else "接收显示：Abc 文本", 2000
            )

    def set_encoding(self, label: str, codec: str) -> None:
        self.encoding = codec
        self.encoding_btn.setText(f"⌁ {label}")
        self.statusBar().showMessage(f"发送编码切换为 {label}", 2500)

    def send_from_edit(self) -> None:
        self.send_text(self.tx_edit.text())

    def send_text(self, text: str) -> None:
        if not text.strip():
            return
        try:
            if self.hex_mode:
                payload = bytes.fromhex(text.replace(" ", "").replace(",", ""))
            else:
                payload = text.encode(self.encoding, errors="replace")
        except ValueError:
            QMessageBox.warning(
                self, "发送格式错误", "当前为 Hex 模式，请输入正确的十六进制字节串。"
            )
            return

        mode = self.ending_combo.currentIndex()
        if mode == 1:
            payload += b"\n"
        elif mode == 2:
            payload += b"\r\n"

        if self.worker is not None:
            if not self.worker.send(payload):
                QMessageBox.information(self, "发送失败", "接口尚未就绪，请检查连接")
                return
            shown = payload.hex(" ").upper() if self.hex_mode else text
            self.log_rx("[tx] " + shown, kind="tx")
            self.statusBar().showMessage(f"已发送 {len(payload)} 字节", 3000)
        else:
            shown = payload.hex(" ").upper() if self.hex_mode else text
            self.log_rx("[tx] " + shown, kind="tx")
            self.statusBar().showMessage(
                f"模拟模式已发出 {len(payload)} 字节（仅回显，接串口后真实下发）", 3000
            )
        self._mark_tx_sent()

    def send_payload(self, payload: bytes) -> None:
        """直接发送已组好的字节帧（命令面板使用）。"""
        if not payload:
            return
        shown = payload.hex(" ").upper()
        if self.worker is not None:
            if not self.worker.send(payload):
                QMessageBox.information(self, "发送失败", "接口尚未就绪，请检查连接")
                return
            self.log_rx("[tx] " + shown, kind="tx")
            self.statusBar().showMessage(f"已发送 {len(payload)} 字节", 2000)
        else:
            self.log_rx("[tx] " + shown, kind="tx")
            self.statusBar().showMessage(
                f"模拟模式已发出 {len(payload)} 字节（仅回显，接串口后真实下发）", 2000
            )
        self._mark_tx_sent()

    def _mark_tx_sent(self) -> None:
        self.total_tx += 1
        if hasattr(self, "tx_count_label"):
            self.update_stats(self.current_page())
