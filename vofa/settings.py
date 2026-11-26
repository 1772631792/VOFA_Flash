"""QSettings 读写封装。"""
from __future__ import annotations

from PySide6.QtCore import QSettings

SETTINGS_ORG = "VOFAFlash"
SETTINGS_APP = "VOFAFlash"

__all__ = [
    "SETTINGS_ORG", "SETTINGS_APP",
    "load_dark_setting", "save_dark_setting", "load_setting", "save_setting",
]


def _qsettings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def load_dark_setting() -> bool:
    return bool(_qsettings().value("appearance/dark", False, type=bool))


def save_dark_setting(dark: bool) -> None:
    _qsettings().setValue("appearance/dark", bool(dark))


def load_setting(key, default, value_type=None):
    q = _qsettings()
    if value_type is None:
        return q.value(key, default)
    return q.value(key, default, type=value_type)


def save_setting(key, value) -> None:
    _qsettings().setValue(key, value)
