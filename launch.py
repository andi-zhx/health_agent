# -*- coding: utf-8 -*-
"""
医疗档案管理 - 桌面启动器
双击运行后：弹出提示窗口，自动打开浏览器进行操作。关闭窗口即停止服务。
"""
from __future__ import print_function

import os
import sys
import traceback
import subprocess
from datetime import datetime

# 先切换到本脚本所在目录，保证数据库和 static 路径正确
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

ERROR_LOG = os.path.join(SCRIPT_DIR, 'error_log.txt')
START_LOG = os.path.join(SCRIPT_DIR, 'logs', 'startup.log')


def write_start_log(msg):
    os.makedirs(os.path.join(SCRIPT_DIR, 'logs'), exist_ok=True)
    with open(START_LOG, 'a', encoding='utf-8') as f:
        f.write('[%s] %s\n' % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg))


def install_requirements_auto():
    """尝试自动安装 requirements.txt 依赖"""
    req = os.path.join(SCRIPT_DIR, 'requirements.txt')
    if not os.path.exists(req):
        return False, '未找到 requirements.txt，无法自动安装依赖。'

    cmd = [sys.executable, '-m', 'pip', 'install', '-r', req]
    try:
        proc = subprocess.run(cmd, cwd=SCRIPT_DIR, capture_output=True, text=True)
    except Exception as e:
        return False, '执行依赖安装命令失败：%s' % e

    if proc.returncode == 0:
        return True, '依赖安装成功。'

    detail = (proc.stdout or '') + '\n' + (proc.stderr or '')
    return False, '自动安装依赖失败。\n命令：%s\n\n%s' % (' '.join(cmd), detail.strip())


def show_error(title, msg):
    """显示错误信息：先尝试弹窗，失败则写入日志"""
    full_msg = msg + '\n\n详细已写入: %s' % ERROR_LOG
    try:
        with open(ERROR_LOG, 'w', encoding='utf-8') as f:
            f.write(msg)
    except Exception:
        pass
    # 优先用 tkinter 弹窗
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, full_msg)
        root.destroy()
        return
    except Exception:
        pass
    # Windows 下用系统消息框，避免无控制台时完全看不到错误
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, full_msg, title, 0x10)
            return
        except Exception:
            pass
    print(full_msg)


def main():
    if not sys.executable:
        show_error('医疗系统启动失败', '未检测到 Python 解释器。')
        sys.exit(1)

    os.makedirs(os.path.join(SCRIPT_DIR, 'exports'), exist_ok=True)
    os.makedirs(os.path.join(SCRIPT_DIR, 'backups'), exist_ok=True)
    write_start_log('启动流程开始。')

    # 延迟导入，便于在 import 失败时也能弹窗报错
    try:
        from app import app, init_db
    except ModuleNotFoundError as e:
        ok, info = install_requirements_auto()
        if ok:
            try:
                from app import app, init_db
            except Exception as e2:
                show_error('医疗系统启动失败', '已自动安装依赖，但重新导入仍失败：%s\n\n%s' % (e2, traceback.format_exc()))
                sys.exit(1)
        else:
            tip = (
                '缺少 Python 依赖包（%s）。\n\n'
                '已尝试自动安装但失败，请手动处理：\n'
                '1. 双击运行「安装依赖.bat」，或\n'
                '2. 在命令行执行："%s" -m pip install -r requirements.txt\n\n'
                '%s'
            ) % (e, sys.executable, info)
            show_error('医疗系统启动失败', tip)
            sys.exit(1)
    except Exception as e:
        show_error('医疗系统启动失败', '导入失败：%s\n\n%s' % (e, traceback.format_exc()))
        sys.exit(1)

    import threading
    import time
    import webbrowser

    URL = 'http://127.0.0.1:5000'

    def run_flask():
        try:
            app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False, threaded=True)
        except Exception as e:
            with open(ERROR_LOG, 'w', encoding='utf-8') as f:
                f.write(traceback.format_exc())

    try:
        init_db()
        try:
            from app import create_db_backup
            create_db_backup('startup', notes='启动时自动备份')
            write_start_log('启动时自动备份成功。')
        except Exception:
            write_start_log('启动时自动备份失败。')
    except Exception as e:
        show_error('医疗系统启动失败', '数据库初始化失败：%s\n\n%s' % (e, traceback.format_exc()))
        sys.exit(1)

    # 在后台线程启动 Flask
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

    # 等待服务就绪
    for _ in range(25):
        time.sleep(0.2)
        try:
            import urllib.request
            urllib.request.urlopen(URL, timeout=1)
            break
        except Exception:
            pass
    else:
        time.sleep(1)

    # 自动打开浏览器
    try:
        webbrowser.open(URL)
    except Exception:
        pass

    # 弹出桌面窗口
    try:
        import tkinter as tk
    except ImportError:
        show_error('医疗系统启动', '系统已启动，请在浏览器打开: %s\n\n未安装 tkinter，无法显示提示窗口。' % URL)
        return

    try:
        root = tk.Tk()
        root.title('医疗档案管理')
        root.resizable(False, False)

        w, h = 420, 160
        x = (root.winfo_screenwidth() // 2) - (w // 2)
        y = (root.winfo_screenheight() // 2) - (h // 2)
        root.geometry('%dx%d+%d+%d' % (w, h, x, y))

        frame = tk.Frame(root, padx=24, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text='医疗档案管理系统已启动', font=('Microsoft YaHei', 12, 'bold')).pack(anchor='w')
        tk.Label(
            frame,
            text='浏览器已自动打开，可在页面中操作。\n关闭本窗口将停止服务。',
            font=('Microsoft YaHei', 10),
            justify=tk.LEFT,
            fg='#333'
        ).pack(anchor='w', pady=(8, 16))

        def open_browser():
            webbrowser.open(URL)

        tk.Button(
            frame,
            text='再次打开首页',
            command=open_browser,
            font=('Microsoft YaHei', 10),
            width=14,
            cursor='hand2'
        ).pack(anchor='w')

        def on_closing():
            root.destroy()
            sys.exit(0)

        root.protocol('WM_DELETE_WINDOW', on_closing)
        root.mainloop()
    except Exception as e:
        show_error('医疗系统启动失败', str(e) + '\n\n' + traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        show_error('医疗系统启动失败', str(e) + '\n\n' + traceback.format_exc())
        sys.exit(1)
