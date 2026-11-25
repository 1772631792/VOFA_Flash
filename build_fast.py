"""打包为分开的 Windows 程序目录：python build_fast.py

产物：
  dist/VOFA_Flash/VOFA_Flash.exe      启动快，不解压临时目录
  dist/VOFA_Flash/Create_Desktop_Shortcut.cmd  双击后在桌面建立快捷方式
  dist/VOFA_Flash_v{VERSION}_win64_onedir.zip  发布包

依赖：pip install -r config/requirements.txt（其中包含 pyinstaller）
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from vofa import __version__ as VERSION

ROOT = Path(__file__).resolve().parent
APP_NAME = "VOFA_Flash"
APP_TITLE = "VOFA+ Flash"
ENTRY = ROOT / "main.py"
ASSETS = ROOT / "assets"
ICON = ASSETS / "app.ico"
DIST = ROOT / "dist"
APP_DIR = DIST / APP_NAME
WORK = ROOT / "build_fast"
VERSION_FILE = WORK / "version_info.txt"
SHORTCUT_NAME = "Create_Desktop_Shortcut.cmd"
RELEASE_ZIP = DIST / f"{APP_NAME}_v{VERSION}_win64_onedir.zip"

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

# 用 CMD + PowerShell 建快捷方式，不含 VBS，避免杀毒软件误报
SHORTCUT_SCRIPT = """@echo off
setlocal
set "VOFA_FLASH_DIR=%~dp0"

if not exist "%VOFA_FLASH_DIR%VOFA_Flash.exe" (
    echo VOFA_Flash.exe was not found beside this script.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$app = Join-Path $env:VOFA_FLASH_DIR 'VOFA_Flash.exe';" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$link = Join-Path $desktop 'VOFA+ Flash.lnk';" ^
  "$shell = New-Object -ComObject WScript.Shell;" ^
  "$shortcut = $shell.CreateShortcut($link);" ^
  "$shortcut.TargetPath = $app;" ^
  "$shortcut.WorkingDirectory = $env:VOFA_FLASH_DIR.TrimEnd('\\');" ^
  "$shortcut.IconLocation = $app + ',0';" ^
  "$shortcut.Description = 'VOFA+ Flash serial waveform debugger';" ^
  "$shortcut.Save()"

if errorlevel 1 (
    echo Failed to create the desktop shortcut.
    pause
    exit /b 1
)

echo Desktop shortcut created: VOFA+ Flash
pause
"""


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
        StringStruct('CompanyName', '{APP_TITLE}'),
        StringStruct('FileDescription', 'VOFA+ Flash serial waveform debugger'),
        StringStruct('FileVersion', '{VERSION}'),
        StringStruct('InternalName', '{APP_NAME}'),
        StringStruct('OriginalFilename', '{APP_NAME}.exe'),
        StringStruct('ProductName', '{APP_TITLE}'),
        StringStruct('ProductVersion', '{VERSION}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def write_shortcut_script() -> Path:
    """把快捷方式脚本放进打包目录，双击即可在桌面建快捷方式。"""
    path = APP_DIR / SHORTCUT_NAME
    path.write_text(SHORTCUT_SCRIPT, encoding="ascii")
    return path


def build_command() -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
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


def package_release() -> tuple[Path, str]:
    """把整个目录打进 zip，并生成校验值。"""
    RELEASE_ZIP.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE_ZIP, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(APP_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=f"{APP_NAME}/{path.relative_to(APP_DIR).as_posix()}")
        readme = ROOT / "README.md"
        if readme.exists():
            archive.write(readme, arcname="README.md")
        screenshots = ROOT / "docs" / "screenshots"
        if screenshots.is_dir():
            for image in sorted(screenshots.glob("*.png")):
                archive.write(image, arcname=f"docs/screenshots/{image.name}")

    digest = hashlib.sha256(RELEASE_ZIP.read_bytes()).hexdigest()
    return RELEASE_ZIP, digest


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
    print(f"开始打包分开版 {APP_NAME}.exe（v{VERSION}）...")
    subprocess.run(build_command(), cwd=ROOT, check=True)

    exe = APP_DIR / f"{APP_NAME}.exe"
    if not exe.exists():
        print("打包结束但未找到产物，请检查 PyInstaller 输出。")
        sys.exit(1)

    shortcut = write_shortcut_script()
    total_bytes = sum(path.stat().st_size for path in APP_DIR.rglob("*") if path.is_file())
    release_zip, digest = package_release()
    print(f"\n完成：{exe}（目录共 {total_bytes / (1024 * 1024):.1f} MB）")
    print(f"快捷方式脚本：{shortcut}")
    print(f"发布包：{release_zip}")
    print(f"SHA256：{digest}")
    print("把整个 VOFA_Flash 文件夹拷到目标电脑；双击 cmd 脚本即可创建桌面快捷方式。")


if __name__ == "__main__":
    main()
