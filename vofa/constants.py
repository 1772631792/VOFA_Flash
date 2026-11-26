"""全局常量与窗口帮助函数。"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QWidget

ENGINES = ["JustFloat", "RawData"]
INTERFACES = ["串口", "UDP", "TCP客户端", "TCP服务端", "模拟模式"]
DEMO_CHANNELS = 3


def apply_dark_titlebar(window: QWidget, dark: bool) -> bool:
    """Windows 10/11：把系统标题栏切成深色 / 浅色，其它平台直接忽略。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = wintypes.HWND(int(window.winId()))
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break
        else:
            return False
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0, 0, 0x0027
        )
        return True
    except Exception:
        return False
