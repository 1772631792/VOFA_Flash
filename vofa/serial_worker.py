"""后台串口接收线程：批量读取 + 合并上报，面向高吞吐场景。"""

from __future__ import annotations

import time

import serial
from PySide6.QtCore import QMutex, QThread, Signal

_PARITY = {
    "None": serial.PARITY_NONE,
    "Even": serial.PARITY_EVEN,
    "Odd": serial.PARITY_ODD,
}
_STOPBITS = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}
_BYTESIZE = {8: serial.EIGHTBITS, 7: serial.SEVENBITS}

READ_BATCH = 256 * 1024
EMIT_INTERVAL = 0.01


class SerialWorker(QThread):
    raw_received = Signal(bytes)
    error_occurred = Signal(str)
    connected = Signal()
    disconnected = Signal()

    def __init__(
        self,
        port: str,
        baudrate: int,
        bytesize: int = 8,
        parity: str = "None",
        stopbits: int = 1,
        flow: str = "None",
        parent=None,
    ):
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.flow = flow
        self.bytes_received = 0
        self._running = True
        self._mutex = QMutex()
        self._serial: serial.Serial | None = None

    def send(self, data: bytes) -> bool:
        self._mutex.lock()
        try:
            if self._serial is None or not self._serial.is_open:
                return False
            self._serial.write(data)
            self._serial.flush()
            return True
        except Exception as exc:
            self.error_occurred.emit(str(exc))
            return False
        finally:
            self._mutex.unlock()

    def stop(self) -> None:
        self._running = False
        self.requestInterruption()
        serial_obj = self._serial
        if serial_obj is not None:
            try:
                serial_obj.cancel_read()
            except Exception:
                pass
        self.wait(3000)

    def run(self) -> None:
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=_BYTESIZE.get(self.bytesize, serial.EIGHTBITS),
                parity=_PARITY.get(self.parity, serial.PARITY_NONE),
                stopbits=_STOPBITS.get(self.stopbits, serial.STOPBITS_ONE),
                rtscts=self.flow == "Hardware",
                xonxoff=self.flow == "Software",
                timeout=0,
                write_timeout=1,
            )
        except Exception as exc:
            self.error_occurred.emit(str(exc))
            return

        self.connected.emit()
        pending = bytearray()
        last_emit = 0.0

        while self._running and not self.isInterruptionRequested():
            serial_obj = self._serial
            if serial_obj is None or not serial_obj.is_open:
                break
            chunk = b""
            waiting = 0
            try:
                waiting = serial_obj.in_waiting
                if waiting > 0:
                    chunk = serial_obj.read(min(waiting, READ_BATCH))
            except Exception as exc:
                if self._running:
                    self.error_occurred.emit(str(exc))
                break

            if chunk:
                pending.extend(chunk)
                self.bytes_received += len(chunk)

            now = time.monotonic()
            if pending and now - last_emit >= EMIT_INTERVAL:
                self.raw_received.emit(bytes(pending))
                pending.clear()
                last_emit = now
            elif waiting == 0:
                self.msleep(2)

        if pending:
            self.raw_received.emit(bytes(pending))

        serial_obj = self._serial
        self._serial = None
        if serial_obj is not None:
            try:
                serial_obj.close()
            except Exception:
                pass
        if self._running:
            self.disconnected.emit()
