"""网络与演示数据接口。

所有接口对外暴露统一的信号与 send/stop 方法，便于主窗口无差别切换：
    raw_received(bytes) / error_occurred(str) / connected() / disconnected()
"""

from __future__ import annotations

import math
import socket
import struct

from PySide6.QtCore import QMutex, QThread, Signal

JUSTFLOAT_TAIL = b"\x00\x00\x80\x7f"


class BaseTransport(QThread):
    raw_received = Signal(bytes)
    error_occurred = Signal(str)
    connected = Signal()
    disconnected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._mutex = QMutex()
        self._sock: socket.socket | None = None

    # ---------- 共用接口 ----------
    def send(self, data: bytes) -> bool:
        return False

    def stop(self) -> None:
        self._running = False
        self.requestInterruption()
        self._close_socket()
        self.wait(2000)

    def _close_socket(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _fail(self, message: str) -> None:
        if self._running:
            self.error_occurred.emit(message)


class UdpTransport(BaseTransport):
    """绑定本地端口接收 UDP 数据，可向远端地址回发。"""

    def __init__(self, host: str, port: int, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port

    def send(self, data: bytes) -> bool:
        if self._sock is None or not self.host:
            return False
        try:
            self._sock.sendto(data, (self.host, self.port))
            return True
        except OSError as exc:
            self._fail(str(exc))
            return False

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.2)
        try:
            sock.bind(("0.0.0.0", self.port))
        except OSError as exc:
            sock.close()
            self._fail(f"UDP 端口 {self.port} 绑定失败：{exc}")
            return
        self._sock = sock
        self.connected.emit()
        while self._running and not self.isInterruptionRequested():
            try:
                chunk, _addr = sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            if chunk:
                self.raw_received.emit(chunk)
        self._close_socket()
        self.disconnected.emit()


class TcpClientTransport(BaseTransport):
    """作为客户端连接远端 TCP 服务。"""

    def __init__(self, host: str, port: int, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port

    def send(self, data: bytes) -> bool:
        if self._sock is None:
            return False
        try:
            self._sock.sendall(data)
            return True
        except OSError as exc:
            self._fail(str(exc))
            return False

    def run(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=3.0)
        except OSError as exc:
            self._fail(f"连接 {self.host}:{self.port} 失败：{exc}")
            return
        sock.settimeout(0.2)
        self._sock = sock
        self.connected.emit()
        while self._running and not self.isInterruptionRequested():
            try:
                chunk = sock.recv(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            self.raw_received.emit(chunk)
        self._close_socket()
        self.disconnected.emit()


class TcpServerTransport(BaseTransport):
    """监听本地端口，接受一个 TCP 客户端连接后收发数据。"""

    def __init__(self, host: str, port: int, parent=None):
        super().__init__(parent)
        self.host = host or "0.0.0.0"
        self.port = port
        self._client: socket.socket | None = None

    def send(self, data: bytes) -> bool:
        if self._client is None:
            return False
        try:
            self._client.sendall(data)
            return True
        except OSError as exc:
            self._fail(str(exc))
            return False

    def run(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.settimeout(0.2)
        try:
            server.bind((self.host, self.port))
            server.listen(1)
        except OSError as exc:
            server.close()
            self._fail(f"TCP 端口 {self.port} 监听失败：{exc}")
            return
        self._sock = server
        self.connected.emit()

        while self._running and not self.isInterruptionRequested():
            try:
                client, _addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client.settimeout(0.2)
            self._client = client
            while self._running and not self.isInterruptionRequested():
                try:
                    chunk = client.recv(8192)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                self.raw_received.emit(chunk)
            self._client = None
            try:
                client.close()
            except OSError:
                pass

        self._close_socket()
        self.disconnected.emit()


class DemoTransport(BaseTransport):
    """本地生成 JustFloat 测试数据，无需硬件即可预览波形。"""

    def __init__(self, channels: int = 3, rate_hz: int = 100, parent=None):
        super().__init__(parent)
        self.channels = max(1, channels)
        self.rate_hz = max(1, rate_hz)

    def run(self) -> None:
        self.connected.emit()
        interval = 1.0 / self.rate_hz
        step = 0
        template = "<%df" % self.channels
        while self._running and not self.isInterruptionRequested():
            t = step * interval
            values = []
            for ch in range(self.channels):
                freq = 1.0 + ch * 0.4
                phase = ch * math.pi / 3
                values.append(math.sin(2 * math.pi * freq * t + phase) * 10.0)
            payload = struct.pack(template, *values) + JUSTFLOAT_TAIL
            self.raw_received.emit(payload)
            step += 1
            self.msleep(max(1, int(interval * 1000)))
        self.disconnected.emit()
