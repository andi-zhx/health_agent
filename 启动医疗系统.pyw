# -*- coding: utf-8 -*-
"""双击此文件即可启动医疗档案管理（无黑框）。"""
import os
import sys
import traceback

_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_dir)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

ERROR_LOG = os.path.join(_dir, 'error_log.txt')


def show_error(title, msg):
    try:
        with open(ERROR_LOG, 'w', encoding='utf-8') as f:
            f.write(msg)
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, msg + '\n\n详细已写入: ' + ERROR_LOG)
        root.destroy()
        return
    except Exception:
        pass
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg + '\n\n详细已写入: ' + ERROR_LOG, title, 0x10)
        except Exception:
            pass


try:
    import launch
    launch.main()
except Exception as e:
    show_error('医疗系统启动失败', str(e) + '\n\n' + traceback.format_exc())
    sys.exit(1)
