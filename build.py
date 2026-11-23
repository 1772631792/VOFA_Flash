"""打包为单文件 exe：python build.py

依赖：pip install -r config/requirements.txt
图标直接使用 assets/app.ico。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller，请先运行: pip install -r config/requirements.txt")
        sys.exit(1)

    ico_path = ROOT / "assets" / "app.ico"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--specpath",
        str(ROOT / "build"),
        "--name",
        "vofa",
        "--hidden-import",
        "PySide6.QtSvg",
        "--hidden-import",
        "serial.tools.list_ports",
    ]
    if ico_path.exists():
        cmd += ["--add-data", f"{ico_path};assets"]
    cmd.append(str(ROOT / "main.py"))
    if ico_path.exists():
        cmd += ["--icon", str(ico_path)]

    subprocess.run(cmd, cwd=ROOT, check=True)
    print("\n完成：dist/vofa.exe")


if __name__ == "__main__":
    main()
