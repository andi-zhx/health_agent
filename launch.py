# -*- coding: utf-8 -*-
"""Start the local server, verify readiness, then open the desktop UI."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser

from backend.runtime import BASE_DIR, DATA_DIR

ERROR_LOG = DATA_DIR / 'error_log.txt'
START_LOG = DATA_DIR / 'logs' / 'startup.log'


def write_start_log(message):
    START_LOG.parent.mkdir(parents=True, exist_ok=True)
    with START_LOG.open('a', encoding='utf-8') as stream:
        stream.write('[%s] %s\n' % (datetime.now().isoformat(timespec='seconds'), message))


def show_error(title, message, gui=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ERROR_LOG.write_text(message, encoding='utf-8')
    full_message = message + '\n\n详细日志：' + str(ERROR_LOG)
    if gui:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(title, full_message, parent=root)
            root.destroy()
            return
        except Exception:
            if sys.platform == 'win32':
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, full_message, title, 0x10)
                return
    if sys.stderr is not None:
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(errors='backslashreplace')
        print(full_message, file=sys.stderr)


def wait_until_ready(url, thread, timeout=10):
    # Loopback requests must not go through a configured HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        try:
            with opener.open(url + '/api/health', timeout=1) as response:
                payload = json.load(response)
            if payload.get('data', {}).get('application') == 'health-agent' and payload['data'].get('status') == 'ready':
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise RuntimeError('服务未能就绪，请查看 logs/app.log。浏览器尚未打开。')


def run_desktop(url, thread):
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception:
        write_start_log('桌面窗口不可用，保持命令行服务运行。')
        print('Open %s in your browser. Press Ctrl+C to stop.' % url, flush=True)
        while thread.is_alive():
            thread.join(0.5)
        return
    root.title('健康管理系统')
    root.geometry('460x210')
    root.resizable(False, False)
    frame = tk.Frame(root, padx=24, pady=22)
    frame.pack(fill=tk.BOTH, expand=True)
    tk.Label(frame, text='健康管理系统已启动', font=('Microsoft YaHei', 14, 'bold'), fg='#087f72').pack(anchor='w')
    tk.Label(frame, text=url + '\n关闭此窗口将停止服务。', justify=tk.LEFT,
             font=('Microsoft YaHei', 10)).pack(anchor='w', pady=16)
    tk.Button(frame, text='打开系统首页', command=lambda: webbrowser.open(url),
              font=('Microsoft YaHei', 10), width=18).pack(anchor='w')
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description='健康管理系统本地启动器')
    parser.add_argument('--no-gui', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=os.environ.get('APP_PORT', '5000'))
    args = parser.parse_args(argv)
    server = None
    thread = None
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError('端口必须在 1–65535 之间。')
        write_start_log('启动流程开始，Python %s。' % sys.version.split()[0])
        from app import app, create_db_backup
        from werkzeug.serving import make_server
        # Bind synchronously. A busy port must fail before we open a browser.
        try:
            server = make_server('127.0.0.1', args.port, app, threaded=True)
        except (OSError, SystemExit) as error:
            raise RuntimeError('端口 %s 无法使用。请关闭已运行的本系统，或设置 APP_PORT 为其他端口。' % args.port) from error
        backup = create_db_backup('startup', notes='启动时自动备份')
        write_start_log('启动备份：%s' % backup.get('status'))
        if backup.get('status') != 'success':
            write_start_log('备份失败：%s' % backup.get('message'))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = 'http://127.0.0.1:%s' % args.port
        wait_until_ready(url, thread)
        write_start_log('服务已就绪：' + url)
        print('READY ' + url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        if args.no_gui:
            while thread.is_alive():
                thread.join(0.5)
        else:
            run_desktop(url, thread)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        show_error('健康管理系统启动失败', traceback.format_exc(), gui=not args.no_gui)
        return 1
    finally:
        if server is not None:
            if thread is not None and thread.is_alive():
                server.shutdown()
                thread.join(timeout=3)
            server.server_close()


if __name__ == '__main__':
    sys.exit(main())
