"""轻量启动画面：只依赖 PySide6，先于 numpy / pyqtgraph 显示。"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Property,
)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .icons import app_icon


class _LoadingBar(QWidget):
    """一条循环扫过的细进度条，用 QPropertyAnimation 驱动。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self._phase = 0.0
        self._anim = QPropertyAnimation(self, b"loadingPhase")
        self._anim.setDuration(900)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)

    def get_loadingPhase(self) -> float:  # noqa: N802
        return self._phase

    def set_loadingPhase(self, value: float) -> None:  # noqa: N802
        self._phase = float(value)
        self.update()

    loadingPhase = Property(float, get_loadingPhase, set_loadingPhase)

    def start(self) -> None:
        self._anim.start()

    def stop(self) -> None:
        self._anim.stop()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        track = QPainterPath()
        track.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.fillPath(track, QColor("#DCEAF9"))

        width = max(28.0, self.width() * 0.32)
        travel = self.width() + width
        x = -width + self._phase * travel
        highlight = QRectF(x, 0, width, rect.height())
        gradient = QLinearGradient(highlight.left(), 0, highlight.right(), 0)
        gradient.setColorAt(0.0, QColor("#0A84E8"))
        gradient.setColorAt(0.5, QColor("#3FA9FF"))
        gradient.setColorAt(1.0, QColor("#0A84E8"))
        pen = QPen()
        pen.setWidthF(0)
        painter.setPen(pen)
        painter.setBrush(gradient)
        path = QPainterPath()
        path.addRoundedRect(highlight, rect.height() / 2, rect.height() / 2)
        painter.drawPath(path)


class SplashScreen(QWidget):
    """毛玻璃圆角卡片：大号 V 标志 + 名称 + 版本 + 快速扫光。"""

    def __init__(self, version: str = __version__):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(420, 268)
        self.setWindowOpacity(0.0)

        shadow_host = QFrame(self)
        shadow_host.setObjectName("splashCard")
        shadow_host.setGeometry(14, 14, 392, 240)
        shadow_host.setStyleSheet(
            "#splashCard {"
            " background: rgba(255,255,255,232);"
            " border: none;"
            " border-radius: 22px;"
            "}"
        )
        shadow = QGraphicsDropShadowEffect(shadow_host)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 54, 96, 46))
        shadow_host.setGraphicsEffect(shadow)

        lay = QVBoxLayout(shadow_host)
        lay.setContentsMargins(24, 18, 24, 20)
        lay.setSpacing(0)

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        icon_label.setPixmap(app_icon().pixmap(104, 104))
        lay.addWidget(icon_label)

        title = QLabel("VOFA+ Flash")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title_font = QFont("Microsoft YaHei UI")
        title_font.setPointSize(21)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color:#17324F;")
        lay.addSpacing(4)
        lay.addWidget(title)

        version_row = QHBoxLayout()
        version_row.setContentsMargins(0, 0, 0, 0)
        version_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        version_label = QLabel(f"v{version}")
        version_label.setStyleSheet(
            "color:#5C7189;font-family:Consolas;font-size:12px;"
            "background:rgba(10,132,232,12);border-radius:9px;padding:2px 10px;"
        )
        version_row.addWidget(version_label)
        lay.addLayout(version_row)
        lay.addSpacing(16)

        self._bar = _LoadingBar(shadow_host)
        lay.addWidget(self._bar)

        screen = QApplication.primaryScreen()
        if screen is not None:
            center = screen.availableGeometry().center()
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setDuration(180)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_out = QPropertyAnimation(self, b"windowOpacity")
        self._fade_out.setDuration(220)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self._on_fade_out_done)
        self._on_done = None

    def start(self) -> None:
        self.show()
        self.raise_()
        QApplication.processEvents()
        self._fade_in.start()
        self._bar.start()

    def finish(self, window: QWidget | None = None, on_done=None) -> None:
        self._on_done = on_done
        self._bar.stop()
        if window is not None:
            window.raise_()
            window.activateWindow()
        self._fade_out.start()

    def _on_fade_out_done(self) -> None:
        self.close()
        if self._on_done is not None:
            callback, self._on_done = self._on_done, None
            QTimer.singleShot(0, callback)
