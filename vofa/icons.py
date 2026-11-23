"""小型矢量图标（接近 VOFA+ 官方视觉风格）。"""

import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def _svg_pixmap(svg: str, size: int, color: str = "#555555") -> QPixmap:
    svg = svg.replace("{color}", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return pixmap


def _svg_icon(svg: str, size: int = 16, color: str = "#555555") -> QIcon:
    return QIcon(_svg_pixmap(svg, size, color))


def _asset_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    else:
        base = Path(__file__).resolve().parents[1]
    return base / "assets" / name


def app_icon() -> QIcon:
    """白色圆角底 + 大号蓝色 V，按多档尺寸渲染，窗口与任务栏都清晰。"""
    svg = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
    <rect x='1' y='1' width='62' height='62' rx='14' fill='#FFFFFF'/>
    <rect x='1' y='1' width='62' height='62' rx='14' fill='none'
          stroke='#D9E3EF' stroke-width='2'/>
    <path fill='#0A84E8' d='M10 10 H23 L32 31 L41 10 H54 L32 54 Z'/>
    </svg>"""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_svg_pixmap(svg, size))
    return icon


def icon(name: str, size: int = 16, color: str = "#555555") -> QIcon:
    shapes = {
        "plus": "<path d='M8 3v10M3 8h10' stroke='{color}' stroke-width='1.6' stroke-linecap='round'/>",
        "close": "<path d='M4 4l8 8M12 4l-8 8' stroke='{color}' stroke-width='1.5' stroke-linecap='round'/>",
        "chevron_left": "<path d='M10 3L5 8l5 5' fill='none' stroke='{color}' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/>",
        "chevron_right": "<path d='M6 3l5 5-5 5' fill='none' stroke='{color}' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/>",
        "chevron_down": "<path d='M3 6l5 5 5-5' fill='none' stroke='{color}' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/>",
        "more": "<circle cx='3' cy='8' r='1.3' fill='{color}'/><circle cx='8' cy='8' r='1.3' fill='{color}'/><circle cx='13' cy='8' r='1.3' fill='{color}'/>",
        "wifi": "<path d='M2 6a9 9 0 0112 0M4.5 8.8a5.5 5.5 0 017 0M7 11.6a1.7 1.7 0 012 0' fill='none' stroke='{color}' stroke-width='1.3' stroke-linecap='round'/>",
        "pin": "<path d='M8 2v9M5 2h6M6 11h4' stroke='{color}' stroke-width='1.3' stroke-linecap='round'/>",
        "settings": "<circle cx='8' cy='8' r='2.2' fill='none' stroke='{color}' stroke-width='1.3'/><path d='M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4' stroke='{color}' stroke-width='1.1' stroke-linecap='round'/>",
        "undo": "<path d='M5 5L2 8l3 3M2 8h7a4 4 0 010 8' fill='none' stroke='{color}' stroke-width='1.4' stroke-linecap='round' stroke-linejoin='round'/>",
        "trash": "<path d='M3 4h10M6 4V2.5h4V4M4.5 4l.6 10h5.8l.6-10' fill='none' stroke='{color}' stroke-width='1.2' stroke-linejoin='round'/>",
        "pencil": "<path d='M3 13l1-3.5L10.5 3 13 5.5 5.5 12 2 13z' fill='none' stroke='{color}' stroke-width='1.2' stroke-linejoin='round'/>",
        "save": "<path d='M3 2h8l2 2v10H3z' fill='none' stroke='{color}' stroke-width='1.2'/><path d='M5 2v5h6V2M5 14V9h6v5' fill='none' stroke='{color}' stroke-width='1.1'/>",
        "copy": "<path d='M5 2h8v10H5zM2 5h8v10H2z' fill='none' stroke='{color}' stroke-width='1.1'/>",
        "wrench": "<path d='M11 2a4 4 0 00-5 5L2 11l3 3 4-4a4 4 0 005-5l-2 2-2-2z' fill='none' stroke='{color}' stroke-width='1.2' stroke-linejoin='round'/>",
        "bug": "<rect x='5' y='5' width='6' height='8' rx='3' fill='none' stroke='{color}' stroke-width='1.1'/><path d='M5 7H2M14 7h-3M5 10H2.5M13.5 10H11M6 5L4.5 3M10 5l1.5-2' stroke='{color}' stroke-width='1.1' stroke-linecap='round'/>",
        "headset": "<path d='M3 9V7a5 5 0 0110 0v2M3 9h2v4H4a1 1 0 01-1-1V9zm10 0h-2v4h1a1 1 0 001-1V9z' fill='none' stroke='{color}' stroke-width='1.2' stroke-linejoin='round'/>",
        "rewind": "<path d='M3 8l5-4v8zM9 8l5-4v8z' fill='none' stroke='{color}' stroke-width='1.2' stroke-linejoin='round'/>",
        "plug": "<path d='M6 2v4M10 2v4M4 6h8v2a4 4 0 01-8 0V6zM8 12v2' fill='none' stroke='{color}' stroke-width='1.2' stroke-linejoin='round'/>",
        "keyboard": "<rect x='1.5' y='3' width='13' height='10' rx='1' fill='none' stroke='{color}' stroke-width='1'/><path d='M3.5 5.5h1M6 5.5h1M8.5 5.5h1M11 5.5h1M3.5 8h1M6 8h1M8.5 8h1M11 8h1M5 10.5h6' stroke='{color}' stroke-width='1' stroke-linecap='round'/>",
        "clipboard": "<path d='M5 2h6v2H5zM3 4h10v10H3z' fill='none' stroke='{color}' stroke-width='1.1'/><path d='M5.5 7h5M5.5 9.5h5' stroke='{color}' stroke-width='1'/>",
        "curve": "<path d='M1 12c3 0 3-8 6-8s3 8 8 8' fill='none' stroke='{color}' stroke-width='1.3' stroke-linecap='round'/>",
        "align": "<path d='M2 3v10M6 5v6M10 2v12M14 5v6' stroke='{color}' stroke-width='1.2' stroke-linecap='round'/>",
        "minimize": "<path d='M3 8h10' stroke='{color}' stroke-width='1.2' stroke-linecap='round'/>",
        "maximize": "<rect x='3.5' y='3.5' width='9' height='9' fill='none' stroke='{color}' stroke-width='1.1'/>",
        "restore": "<path d='M5 5h8v8H5zM3 3h8v2M11 3v2' fill='none' stroke='{color}' stroke-width='1.1'/>",
        "wave": "<path d='M1 11c2 0 2-7 4-7s2 9 4 9 2-9 4-9 2 7 4 7' fill='none' stroke='{color}' stroke-width='1.3' stroke-linecap='round'/>",
        "button": "<rect x='2' y='5' width='12' height='6' rx='2' fill='none' stroke='{color}' stroke-width='1.2'/><path d='M5 8h6' stroke='{color}' stroke-width='1.2' stroke-linecap='round'/>",
        "slider": "<path d='M2 8h12' stroke='{color}' stroke-width='1.2'/><rect x='6' y='5' width='4' height='6' rx='1' fill='{color}'/>",
        "led": "<circle cx='8' cy='8' r='4' fill='none' stroke='{color}' stroke-width='1.2'/><circle cx='8' cy='8' r='1.8' fill='{color}'/>",
        "text": "<path d='M3 4h10M8 4v8M5.5 12h5' stroke='{color}' stroke-width='1.3' stroke-linecap='round'/>",
        "cube": "<path d='M8 1.5L14 5v6L8 14.5 2 11V5z' fill='none' stroke='{color}' stroke-width='1.1'/><path d='M2 5l6 3.5L14 5M8 8.5v6' fill='none' stroke='{color}' stroke-width='1.1'/>",
        "image": "<rect x='2' y='3' width='12' height='10' rx='1' fill='none' stroke='{color}' stroke-width='1.1'/><circle cx='6' cy='6.5' r='1.2' fill='{color}'/><path d='M3 12l4-4 3 3 2-2 3 3' fill='none' stroke='{color}' stroke-width='1.1'/>",
        "orb": "<circle cx='8' cy='8' r='7' fill='{color}'/><circle cx='6' cy='5.5' r='2' fill='#FFFFFF' opacity='0.45'/>",
        "record": "<circle cx='8' cy='8' r='5.6' fill='none' stroke='{color}' stroke-width='2.6'/><circle cx='8' cy='8' r='1.6' fill='{color}'/>",
        "layers": "<rect x='2' y='3' width='12' height='2.8' rx='1.4' fill='{color}'/><rect x='2' y='7' width='9' height='2.8' rx='1.4' fill='{color}'/><rect x='2' y='11' width='6' height='2.4' rx='1.2' fill='{color}'/>",
        "docs": "<rect x='5' y='2' width='8' height='10' rx='1' fill='none' stroke='{color}' stroke-width='1.4'/><rect x='2' y='5' width='8' height='10' rx='1' fill='none' stroke='{color}' stroke-width='1.4'/>",
    }
    return _svg_icon(f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>{shapes[name]}</svg>", size, color)


def vofa_watermark() -> QPixmap:
    svg = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 300'>
    <defs><linearGradient id='g' x1='0' y1='0' x2='0' y2='1'>
      <stop offset='0' stop-color='#7FB4E3' stop-opacity='.55'/><stop offset='1' stop-color='#BBD8F0' stop-opacity='.35'/>
    </linearGradient></defs>
    <path fill-rule='evenodd' fill='url(#g)' d='
      M50 80 L72 80 L90 122 L108 80 L130 80 L103 138 L77 138 Z
      M150 80 A28 28 0 1 1 150 136 A28 28 0 1 1 150 80 Z
      M150 92 A16 16 0 1 0 150 124 A16 16 0 1 0 150 92 Z
      M180 80 H212 V89 H190 V101 H208 V110 H190 V138 H180 Z
      M232 138 L252 80 H264 L284 138 H273 L269 124 H247 L243 138 Z
      M250 115 H266 L258 92 Z'/>
    <path d='M85 188L150 288L215 188L188 188L150 258L112 188Z' fill='url(#g)'/>
    <path d='M132 170L150 140L168 170L150 200Z' fill='url(#g)'/>
    </svg>"""
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pixmap = QPixmap(300, 300)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap
