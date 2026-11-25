"""打包为单文件 Windows 程序：python build.py

产物：dist/VOFA_Flash.exe（双击即用，目标机器不需要 Python 环境）
依赖：pip install -r config/requirements.txt（其中包含 pyinstaller）
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from vofa import __version__ as VERSION

ROOT = Path(__file__).resolve().parent
APP_NAME = "VOFA_Flash"
ENTRY = ROOT / "main.py"
ASSETS = ROOT / "assets"
ICON = ASSETS / "app.ico"
DIST = ROOT / "dist"
WORK = ROOT / "build"
VERSION_FILE = WORK / "version_info.txt"

# 运行期动态导入 / 按名称加载的模块，PyInstaller 静态分析看不到
HIDDEN_IMPORTS = [
    "PySide6.QtSvg",
    "serial.tools.list_ports",
]

# 完全不用的重型依赖，排除后体积更小
EXCLUDES = [
    "tkinter",
    "PyQt5",
    "PyQt6",
    "matplotlib",
    "scipy",
    "IPython",
    "pytest",
    "OpenGL",
    "pyqtgraph.opengl",
]


def write_version_file() -> None:
    """写入 Windows exe 文件属性：版本、产品名、版权。"""
    parts = [int(part) for part in VERSION.split(".") if part.isdigit()]
    parts = (parts + [0, 0, 0, 0])[:4]
    version_tuple = tuple(parts)
    WORK.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'VOFA+ Flash'),
        StringStruct('FileDescription', 'VOFA+ Flash serial waveform debugger'),
        StringStruct('FileVersion', '{VERSION}'),
        StringStruct('InternalName', '{APP_NAME}'),
        StringStruct('OriginalFilename', '{APP_NAME}.exe'),
        StringStruct('ProductName', 'VOFA+ Flash'),
        StringStruct('ProductVersion', '{VERSION}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def sha256_of(path: Path) -> str:
    """只计算校验值打印到控制台，不生成 txt 文件。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_command() -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(WORK),
    ]
    for name in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", name]
    for name in EXCLUDES:
        cmd += ["--exclude-module", name]
    if ASSETS.is_dir():
        cmd += ["--add-data", f"{ASSETS}{os.pathsep}assets"]
    if ICON.exists():
        cmd += ["--icon", str(ICON)]
    if VERSION_FILE.exists():
        cmd += ["--version-file", str(VERSION_FILE)]
    cmd.append(str(ENTRY))
    return cmd


def main() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller，请先运行: pip install -r config/requirements.txt")
        sys.exit(1)

    if not ENTRY.exists():
        print(f"找不到入口文件: {ENTRY}")
        sys.exit(1)

    write_version_file()
    print(f"开始打包 {APP_NAME}.exe（v{VERSION}）...")
    subprocess.run(build_command(), cwd=ROOT, check=True)

    exe = DIST / f"{APP_NAME}.exe"
    if not exe.exists():
        print("打包结束但未找到产物，请检查 PyInstaller 输出。")
        sys.exit(1)
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"\n完成：{exe}（{size_mb:.1f} MB）")
    print(f"SHA256：{sha256_of(exe)}")
    print("直接上传这个 exe 即可；不生成 zip / txt。")
    print("双击即可运行，串口驱动由系统提供，无需额外安装 Python。")


if __name__ == "__main__":
    main()
