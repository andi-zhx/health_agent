"""Regression tests use disposable data; never open the user's working database."""
from contextlib import closing
import io
import logging
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch
from zoneinfo import ZoneInfo, reset_tzpath

TEST_DATA = tempfile.TemporaryDirectory(prefix='health-agent-tests-')
os.environ['HEALTH_AGENT_DATA_DIR'] = TEST_DATA.name
os.environ.pop('SECRET_KEY', None)
from app import app
from backend import core
from backend.runtime import load_secret_key
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def login(self):
        response = self.client.post('/api/auth/login', json={'username': 'admin', 'password': '123456'})
        self.assertEqual(response.status_code, 200)

    def test_fresh_start_without_secret(self):
        with self.client.get('/') as response:
            self.assertEqual(response.status_code, 200)
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['data']['status'], 'ready')
        for path in ('/app.js', '/images/login-bg.svg'):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)

    def test_secret_survives_restart_and_environment_wins(self):
        key = load_secret_key()
        self.assertGreaterEqual(len(key), 32)
        result = subprocess.check_output([sys.executable, '-c', 'from backend.runtime import load_secret_key; print(load_secret_key())'], cwd=ROOT, text=True)
        self.assertEqual(result.strip(), key)
        with patch.dict(os.environ, {'SECRET_KEY': 'configured-test-key'}):
            self.assertEqual(load_secret_key(), 'configured-test-key')
        self.assertEqual(load_secret_key(), key)

    def test_windows_timezone_fallback(self):
        # Windows does not provide a system IANA zoneinfo directory.
        try:
            reset_tzpath([])
            ZoneInfo.clear_cache()
            self.assertEqual(core.now_local().utcoffset().total_seconds(), 8 * 3600)
        finally:
            reset_tzpath()
            ZoneInfo.clear_cache()

    def test_startup_with_legacy_windows_console_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', 'from app import app; assert app.test_client().get("/").status_code == 200'],
                                    cwd=ROOT, env={**os.environ, 'HEALTH_AGENT_DATA_DIR': directory,
                                                   'PYTHONIOENCODING': 'cp1252'}, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('数据库初始化完成', (Path(directory) / 'logs' / 'app.log').read_text(encoding='utf-8'))

    def test_login_session_logout_and_protected_data(self):
        self.assertEqual(self.client.get('/api/customers').status_code, 401)
        self.assertEqual(self.client.post('/api/auth/login', json={'username': 'admin', 'password': 'wrong'}).status_code, 401)
        self.login()
        self.assertEqual(self.client.get('/api/customers').status_code, 200)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.assertEqual(self.client.get('/api/customers').status_code, 401)

    def test_all_main_pages_api(self):
        self.login()
        urls = ['/api/dashboard/stats', '/api/dashboard/analytics', '/api/dashboard/health-portrait',
                '/api/dashboard/health-portrait/trends', '/api/customers/integrated-view', '/api/customers',
                '/api/health-assessments', '/api/appointments', '/api/home-appointments',
                '/api/improvement-records/all', '/api/improvement-records/meta',
                '/api/device-management/appointment-items', '/api/device-management/home-items',
                '/api/audit-logs', '/api/query-export/no-show-top10', '/api/system/backup-path',
                '/api/system/backups']
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, response.json)
                self.assertTrue(response.json['success'])

    def test_customer_roundtrip_and_excel_download(self):
        self.login()
        payload = {'name': '回归测试客户', 'phone': '13800000000', 'gender': '男', 'birth_date': '1960-01-01',
                   'identity_type': '本人', 'record_creator': '测试员'}
        created = self.client.post('/api/customers', json=payload)
        self.assertEqual(created.status_code, 201, created.json)
        customer_id = created.json['data']['id']
        self.assertEqual(self.client.get('/api/customers/%s' % customer_id).json['data']['name'], payload['name'])
        payload['address'] = '测试地址'
        self.assertEqual(self.client.put('/api/customers/%s' % customer_id, json=payload).status_code, 200)
        for url in ['/api/export/customers', '/api/export/appointments', '/api/export/query-download?scope=all',
                    '/api/export/customer-integrated-all?scope=all'] + [
                    '/api/export/customer-integrated-form?form=' + form for form in ('basic', 'health', 'appointments', 'home_appointments', 'improvement')]:
            with self.subTest(url=url):
                exported = self.client.get(url)
                self.assertEqual(exported.status_code, 200, exported.json)
                download = self.client.get(exported.json['data']['download_url'])
                self.assertEqual(download.status_code, 200)
                book = load_workbook(io.BytesIO(download.data))
                self.assertTrue(book.sheetnames)
                book.close()
                download.close()
        self.assertEqual(self.client.delete('/api/customers/%s' % customer_id).status_code, 200)

    def test_backup_contains_valid_database(self):
        result = core.create_db_backup('test')
        self.assertEqual(result['status'], 'success', result)
        with closing(sqlite3.connect(result['backup_file'])) as conn:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertGreater(conn.execute('SELECT COUNT(*) FROM system_settings').fetchone()[0], 0)

    def test_existing_database_migrates_without_losing_customers(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'medical_system.db'
            shutil.copy2(ROOT / 'medical_system.db', target)
            with closing(sqlite3.connect(target)) as conn:
                original = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
            result = subprocess.run([sys.executable, '-c', 'from app import app; assert app.test_client().get("/").status_code == 200'],
                                    cwd=ROOT, env={**os.environ, 'HEALTH_AGENT_DATA_DIR': directory}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with closing(sqlite3.connect(target)) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0], original)
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')


class LauncherTests(unittest.TestCase):
    def test_busy_port_reports_failure(self):
        with socket.socket() as listener, tempfile.TemporaryDirectory() as directory:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            result = subprocess.run([sys.executable, str(ROOT / 'launch.py'), '--no-gui', '--no-browser', '--port', str(port)],
                                    cwd=directory, env={**os.environ, 'HEALTH_AGENT_DATA_DIR': directory}, capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b'READY ', result.stdout)
            self.assertIn('端口', (Path(directory) / 'error_log.txt').read_text(encoding='utf-8'))

    def test_server_works_from_other_directory_without_display(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, 'HEALTH_AGENT_DATA_DIR': directory, 'DISPLAY': ''}
            # On Linux this also tests the automatic Tk fallback. Windows CI avoids a GUI.
            args = ['--no-browser', '--port', str(port)]
            if sys.platform == 'win32':
                args.append('--no-gui')
            with open(Path(directory) / 'process.log', 'w', encoding='utf-8') as log:
                process = subprocess.Popen([sys.executable, str(ROOT / 'launch.py'), *args], cwd=directory,
                                           env=env, stdout=log, stderr=log)
                try:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    deadline = time.monotonic() + 15
                    ready = False
                    while time.monotonic() < deadline and process.poll() is None:
                        try:
                            with opener.open('http://127.0.0.1:%s/api/health' % port, timeout=1) as response:
                                ready = json.load(response)['data']['status'] == 'ready'
                            if ready:
                                break
                        except OSError:
                            time.sleep(.1)
                    self.assertTrue(ready, (Path(directory) / 'process.log').read_text(encoding='utf-8'))
                    time.sleep(.5)
                    self.assertIsNone(process.poll(), 'Server exited when the desktop was unavailable')
                finally:
                    process.terminate()
                    process.wait(timeout=10)


def tearDownModule():
    logging.shutdown()
    TEST_DATA.cleanup()


if __name__ == '__main__':
    unittest.main()
