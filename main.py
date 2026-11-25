"""启动入口：python main.py。先弹启动画面，再导入 numpy / pyqtgraph 等重模块。"""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from vofa.splash import SplashScreen


def main() -> None:
    app = QApplication(sys.argv)
    splash = SplashScreen()
    splash.start()

    def boot() -> None:
        from vofa.main_window import main as run_main

        run_main(app, splash, run_loop=False)

    # 给淡入动画留出一点时间；真正的重导入发生在事件循环回调里
    QTimer.singleShot(80, boot)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
