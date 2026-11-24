# -*- coding: utf-8 -*-
"""Use the same environment and visible setup diagnostics as the .bat launcher."""
import ctypes
from pathlib import Path
import subprocess
import sys

try:
    root = Path(__file__).resolve().parent
    python = Path(sys.executable).with_name('python.exe')
    subprocess.Popen([str(python), str(root / 'bootstrap.py')], cwd=root,
                     creationflags=subprocess.CREATE_NEW_CONSOLE)
except Exception as error:
    ctypes.windll.user32.MessageBoxW(0, str(error) + '\n请尝试双击启动医疗系统.bat。', '启动失败', 0x10)
