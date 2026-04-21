"""
医疗客户与健康档案管理系统 - 单机版
仅需 Python：运行后浏览器访问 http://localhost:5000
数据存于 medical_system.db，无 Node/npm 依赖
"""

from flask import Flask, request, jsonify, send_from_directory, session
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import os
import pandas as pd
import json
import logging
import re
import hmac
import uuid
from collections import Counter
from datetime import datetime
from datetime import timedelta
import time
from zoneinfo import ZoneInfo

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    tk = None
    filedialog = None

# 项目根目录（app.py 所在目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 统一进程时区（服务器/程序）与数据库时间语义，默认使用北京时间
APP_TIMEZONE = os.environ.get('APP_TIMEZONE', 'Asia/Shanghai')
os.environ['TZ'] = APP_TIMEZONE
if hasattr(time, 'tzset'):
    time.tzset()


def now_local():
    return datetime.now(ZoneInfo(APP_TIMEZONE))


def now_local_str():
    return now_local().strftime('%Y-%m-%d %H:%M:%S')


def now_local_date_str():
    return now_local().strftime('%Y-%m-%d')


def generate_booking_group_id():
    """生成预约分组ID：用于将同一次连续多时间段预约归为一组。"""
    return uuid.uuid4().hex


def calculate_age_by_birth_year(birth_date):
    text = str(birth_date or '').strip()
    if not text:
        return None
    try:
        birth = datetime.strptime(text[:10], '%Y-%m-%d')
    except ValueError:
        return None
    return now_local().year - birth.year


def hydrate_customer_age(record):
    if not record:
        return record
    derived_age = calculate_age_by_birth_year(record.get('birth_date'))
    if derived_age is not None:
        record['age'] = derived_age
    return record

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'))
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')


def ensure_secret_key_configured():
    if app.config.get('SECRET_KEY'):
        return
    raise RuntimeError('未配置环境变量 SECRET_KEY，应用禁止启动。')

DB_PATH = os.path.join(BASE_DIR, 'medical_system.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'exports')
LOCAL_FILE_UPLOAD_ROOT = os.path.join(BASE_DIR, 'uploads')
BACKUP_FOLDER = os.path.join(BASE_DIR, 'database_backups')
LOG_FOLDER = os.path.join(BASE_DIR, 'logs')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(LOCAL_FILE_UPLOAD_ROOT, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(LOG_FOLDER, 'app.log'),
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)


@app.errorhandler(Exception)
def handle_api_exception(err):
    if not request.path.startswith('/api/'):
        if isinstance(err, HTTPException):
            return err
        logging.exception('非API异常: %s', err)
        return '服务端发生异常', 500
    status_code = 500
    message = '服务端发生异常，请稍后重试'
    if isinstance(err, HTTPException):
        status_code = err.code or 500
        message = err.description or message
    logging.exception('API异常: %s %s', request.path, err)
    return jsonify({'success': False, 'message': message, 'error_code': 'SERVER_ERROR'}), status_code


@app.before_request
def validate_secret_key_before_request():
    ensure_secret_key_configured()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON;')
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn


def row_list(rows):
    return [dict(r) for r in rows]


def get_request_ip():
    header = request.headers.get('X-Forwarded-For', '')
    if header:
        return header.split(',')[0].strip()
    return request.remote_addr or ''


def audit_log(action, module, target_id='', details=''):
    conn = get_db()
    c = conn.cursor()
    insert_audit_log(c, action, module, target_id, details)
    conn.commit()
    conn.close()


def insert_audit_log(cursor, action, module, target_id='', details=''):
    cursor.execute(
        '''
        INSERT INTO audit_logs (username, action, module, target_id, details)
        VALUES (?,?,?,?,?)
        ''',
        (
            session.get('username', 'anonymous'),
            action,
            module,
            str(target_id or ''),
            str(details or ''),
        ),
    )


def build_appointment_change_text(record, module):
    if not record:
        return '-'
    date_text = str(record.get('appointment_date') or '')
    start_time = str(record.get('start_time') or '')
    end_time = str(record.get('end_time') or '')
    time_text = (start_time + '-' + end_time).strip('-')
    project_name = str(record.get('project_name') or record.get('service_project') or '')
    customer_name = str(record.get('customer_name') or '')
    has_companion = str(record.get('has_companion') or '无')
    if module == 'home_appointments':
        staff_name = str(record.get('staff_name') or '')
        location = str(record.get('location') or record.get('home_address') or '')
        return f"客户:{customer_name or '-'}；项目:{project_name or '-'}；时间:{date_text} {time_text or '-'}；地点:{location or '-'}；人员:{staff_name or '-'}；家属陪同:{has_companion or '无'}"
    equipment_name = str(record.get('equipment_name') or '')
    return f"客户:{customer_name or '-'}；项目:{project_name or '-'}；时间:{date_text} {time_text or '-'}；设备:{equipment_name or '-'}；家属陪同:{has_companion or '无'}"


def insert_business_history_log(cursor, module, target_id, action_type, before_text='', after_text=''):
    cursor.execute(
        '''
        INSERT INTO business_history_logs
        (module, target_id, action_type, operator, operator_ip, before_content, after_content)
        VALUES (?,?,?,?,?,?,?)
        ''',
        (
            module,
            int(target_id),
            action_type,
            session.get('username', 'anonymous'),
            get_request_ip(),
            str(before_text or ''),
            str(after_text or ''),
        ),
    )


def ensure_columns(cursor, table_name, columns):
    cursor.execute(f'PRAGMA table_info({table_name})')
    exists = {row[1] for row in cursor.fetchall()}
    for col, col_type in columns.items():
        if col not in exists:
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {col} {col_type}')


def migrate_service_improvement_records_drop_followup_result(cursor):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='service_improvement_records'")
    if not cursor.fetchone():
        return
    cursor.execute('PRAGMA table_info(service_improvement_records)')
    columns = [row[1] for row in cursor.fetchall()]
    if 'followup_result' not in columns:
        return
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS service_improvement_records_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER,
            service_type TEXT DEFAULT 'appointments',
            customer_id INTEGER NOT NULL,
            service_time TEXT NOT NULL,
            service_project TEXT NOT NULL,
            pre_service_status TEXT,
            service_content TEXT,
            post_service_evaluation TEXT,
            improvement_status TEXT NOT NULL,
            followup_time TEXT,
            followup_date TEXT,
            followup_method TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
        '''
    )
    cursor.execute(
        '''
        INSERT INTO service_improvement_records_new (
            id, service_id, service_type, customer_id, service_time, service_project,
            pre_service_status, service_content, post_service_evaluation, improvement_status,
            followup_time, followup_date, followup_method, created_at, updated_at
        )
        SELECT
            id, service_id, service_type, customer_id, service_time, service_project,
            pre_service_status, service_content, post_service_evaluation, improvement_status,
            followup_time, followup_date, followup_method, created_at, updated_at
        FROM service_improvement_records
        '''
    )
    cursor.execute('DROP TABLE service_improvement_records')
    cursor.execute('ALTER TABLE service_improvement_records_new RENAME TO service_improvement_records')


def table_exists(cursor, table_name):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None


LEGACY_EQUIPMENT_MODELS_TO_PURGE = (
    'IR-2024-A',
    'US-2024-B',
    'ES-2024-C',
    'MT-2024-D',
    'TB-2024-E',
    'HC-2024-F',
    'HT-001',
    'HBOT-001',
    'MOXA-001',
    'MASS-001',
)


def purge_legacy_equipment_and_store_massage(cursor):
    cursor.execute(
        f"SELECT id FROM equipment WHERE model IN ({','.join('?' * len(LEGACY_EQUIPMENT_MODELS_TO_PURGE))})",
        LEGACY_EQUIPMENT_MODELS_TO_PURGE,
    )
    legacy_equipment_ids = [row['id'] for row in cursor.fetchall()]
    if legacy_equipment_ids:
        id_placeholders = ','.join('?' * len(legacy_equipment_ids))
        cursor.execute(
            f"UPDATE appointments SET equipment_id=NULL WHERE equipment_id IN ({id_placeholders})",
            legacy_equipment_ids,
        )

    placeholders = ','.join('?' * len(LEGACY_EQUIPMENT_MODELS_TO_PURGE))
    cursor.execute(
        f"DELETE FROM equipment WHERE model IN ({placeholders})",
        LEGACY_EQUIPMENT_MODELS_TO_PURGE,
    )
    if table_exists(cursor, 'project_equipment_mapping'):
        cursor.execute("DELETE FROM project_equipment_mapping WHERE project_name='按摩'")


def migrate_appointments_equipment_nullable(cursor):
    if not table_exists(cursor, 'appointments'):
        return
    cursor.execute('PRAGMA table_info(appointments)')
    cols = cursor.fetchall()
    if not cols:
        return
    col_map = {row[1]: row for row in cols}
    equipment_col = col_map.get('equipment_id')
    if not equipment_col:
        return
    # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
    if equipment_col[3] == 0:
        return

    cursor.execute(
        '''
        CREATE TABLE appointments_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            equipment_id INTEGER,
            project_id INTEGER,
            staff_id INTEGER,
            appointment_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT DEFAULT 'scheduled',
            checkin_status TEXT DEFAULT 'pending',
            checkin_updated_at TEXT,
            checkin_updated_by TEXT,
            checkin_updated_ip TEXT,
            has_companion TEXT DEFAULT '无',
            notes TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            source_record_id INTEGER,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (equipment_id) REFERENCES equipment(id)
        )
        '''
    )

    target_cols = [
        ('id', 'id'),
        ('customer_id', 'customer_id'),
        ('equipment_id', 'equipment_id'),
        ('project_id', 'project_id'),
        ('staff_id', 'staff_id'),
        ('appointment_date', 'appointment_date'),
        ('start_time', 'start_time'),
        ('end_time', 'end_time'),
        ('status', "'scheduled'"),
        ('checkin_status', "'pending'"),
        ('checkin_updated_at', 'NULL'),
        ('checkin_updated_by', 'NULL'),
        ('checkin_updated_ip', 'NULL'),
        ('has_companion', "'无'"),
        ('notes', 'NULL'),
        ('created_at', "(strftime('%Y-%m-%d %H:%M:%S','now','localtime'))"),
        ('updated_at', "(strftime('%Y-%m-%d %H:%M:%S','now','localtime'))"),
        ('source_record_id', 'NULL'),
    ]
    existing = {row[1] for row in cols}
    insert_columns = ', '.join([name for name, _ in target_cols])
    select_exprs = ', '.join([name if name in existing else default for name, default in target_cols])
    cursor.execute(
        f'''
        INSERT INTO appointments_new ({insert_columns})
        SELECT {select_exprs}
        FROM appointments
        '''
    )
    cursor.execute('DROP TABLE appointments')
    cursor.execute('ALTER TABLE appointments_new RENAME TO appointments')


def load_projects_with_parallel_strategy(cursor, enabled_only=False, scene=None):
    sql = 'SELECT * FROM therapy_projects'
    clauses = []
    if enabled_only:
        clauses.append("status='enabled'")
    if scene == 'home' and table_exists(cursor, 'project_rules'):
        clauses.append(
            "name IN (SELECT project_name FROM project_rules WHERE allow_home=1 AND status='enabled')"
        )
    if scene == 'store' and table_exists(cursor, 'project_rules'):
        clauses.append(
            "name NOT IN (SELECT project_name FROM project_rules WHERE allow_home=1 AND status='enabled')"
        )
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    sql += ' ORDER BY id DESC'
    cursor.execute(sql)
    projects = row_list(cursor.fetchall())

    return projects


def create_db_backup(backup_type='manual', notes=''):
    backup_dir = get_backup_directory()
    os.makedirs(backup_dir, exist_ok=True)

    ts = now_local().strftime('%Y%m%d_%H%M%S')
    fn = f'medical_system_{ts}.db'
    fp = os.path.join(backup_dir, fn)
    src = None
    dst = None
    try:
        if os.path.exists(DB_PATH):
            src = sqlite3.connect(DB_PATH)
            src.execute('PRAGMA wal_checkpoint(FULL);')
            dst = sqlite3.connect(fp)
            src.backup(dst)
            status = 'success'
            msg = '备份成功'
        else:
            status = 'failed'
            msg = '数据库文件不存在'
        conn = get_db()
        c = conn.cursor()
        c.execute('INSERT INTO db_backups (backup_file, backup_time, backup_type, status, notes) VALUES (?,?,?,?,?)',
                  (fp, now_local_str(), backup_type, status, notes or msg))
        conn.commit()
        conn.close()
        return {'filename': fn, 'backup_file': fp, 'status': status, 'message': msg}
    except Exception as e:
        logging.exception('backup failed')
        return {'filename': fn, 'status': 'failed', 'message': str(e)}
    finally:
        if dst is not None:
            dst.close()
        if src is not None:
            src.close()


def restore_db_from_backup(backup_file):
    backup_path = os.path.abspath(os.path.expanduser(backup_file or ''))
    if not backup_path:
        return {'status': 'failed', 'message': '请选择要恢复的备份文件'}
    if not os.path.exists(backup_path):
        return {'status': 'failed', 'message': '备份文件不存在'}
    if not backup_path.lower().endswith('.db'):
        return {'status': 'failed', 'message': '仅支持 .db 备份文件'}

    src = None
    dst = None
    try:
        src = sqlite3.connect(backup_path)
        dst = sqlite3.connect(DB_PATH)
        src.execute('PRAGMA wal_checkpoint(FULL);')
        src.backup(dst)
        dst.execute('PRAGMA wal_checkpoint(FULL);')
        dst.commit()
        return {'status': 'success', 'message': '数据库恢复成功'}
    except Exception as e:
        logging.exception('restore failed')
        return {'status': 'failed', 'message': f'数据库恢复失败: {e}'}
    finally:
        if dst is not None:
            dst.close()
        if src is not None:
            src.close()


def overlap_condition():
    return '(start_time < ?) AND (end_time > ?)'


def get_setting_value(key, default_value=''):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT setting_value FROM system_settings WHERE setting_key=?', (key,))
    row = c.fetchone()
    conn.close()
    return row['setting_value'] if row else default_value


def set_setting_value(key, value):
    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()
    c.execute('''
        INSERT INTO system_settings (setting_key, setting_value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value=excluded.setting_value,
            updated_at=excluded.updated_at
    ''', (key, value, now_ts))
    conn.commit()
    conn.close()


def verify_legacy_plaintext_and_migrate(username, password):
    """
    兼容历史库中的明文密码配置：
    - 支持 legacy key：admin_password / login_password
    - 首次登录成功后立刻升级为 password_hash
    - 升级后清空旧明文配置，避免后续继续走明文校验
    """
    config_user = get_setting_value('login_username', 'admin')
    legacy_plaintext = get_setting_value('admin_password', '')
    if not legacy_plaintext:
        legacy_plaintext = get_setting_value('login_password', '')
    if not legacy_plaintext:
        return False
    if username != config_user:
        return False

    # 仅用于迁移阶段的兼容校验，避免直接使用 `password == stored_password` 写法。
    if not hmac.compare_digest(password, legacy_plaintext):
        return False

    set_setting_value('password_hash', generate_password_hash(password))
    # 明文密码字段置空，阻断继续明文存储/校验。
    set_setting_value('admin_password', '')
    set_setting_value('login_password', '')
    return True


def get_backup_directory():
    return get_setting_value('backup_directory', BACKUP_FOLDER)


def parse_multi_value(value):
    if value is None:
        return json.dumps([], ensure_ascii=False)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps([x.strip() for x in str(value).split(',') if x.strip()], ensure_ascii=False)


def decode_multi_value(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


PUBLIC_API_PATHS = {
    '/api/auth/login',
}


@app.before_request
def require_login():
    if not request.path.startswith('/api/'):
        return None
    if request.path in PUBLIC_API_PATHS:
        return None
    if not session.get('logged_in'):
        return jsonify({'error': '未登录或登录已失效'}), 401
    return None



DEFAULT_PROJECT_EQUIPMENT_MAP = {}

APPOINTMENT_PROJECT_DEVICE_CONFIG = {
    '高压氧仓': ['高压氧仓01', '高压氧仓02'],
    '毫米波理疗仪': ['毫米波理疗仪01', '毫米波理疗仪02'],
    '疼痛治疗仪': ['疼痛治疗仪01', '疼痛治疗仪02'],
    '听力检测仪': ['听力检测仪01', '听力检测仪02'],
    '太空针灸按摩仪': ['太空针灸按摩仪01', '太空针灸按摩仪02'],
    '艾灸机器人': ['艾灸机器人01', '艾灸机器人02'],
    'AI健康检测机器人': ['AI健康检测机器人01', 'AI健康检测机器人02'],
    '手持式干式荧光免疫分析仪': ['手持式干式荧光免疫分析仪01', '手持式干式荧光免疫分析仪02'],
    '健康随诊箱': ['健康随诊箱01', '健康随诊箱02'],
}

DEFAULT_ALLOWED_HOME_PROJECTS = {'上门康复护理', '中医养生咨询', '康复训练指导', '血糖测试', '按摩'}

IMPROVEMENT_SERVICE_PROJECTS = [
    '高压氧仓',
    '毫米波理疗仪',
    '疼痛治疗仪',
    '听力检测仪',
    '太空针灸按摩仪',
    '艾灸机器人',
    'AI健康检测机器人',
    '手持式干式荧光免疫分析仪',
    '健康随诊箱',
]

IMPROVEMENT_STATUS_OPTIONS = ['明显改善', '部分改善', '无改善', '加重']
FOLLOWUP_METHOD_OPTIONS = ['电话', '到店']
FOLLOWUP_PRESET_OPTIONS = ['1个月', '3个月', '半年', '1年']
ALLOWED_IMPROVEMENT_FILE_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
ALLOWED_IMPROVEMENT_MIME_TYPES = {
    'pdf': {'application/pdf', 'application/x-pdf'},
    'png': {'image/png', 'image/x-png'},
    'jpg': {'image/jpeg', 'image/pjpeg', 'image/jpg'},
    'jpeg': {'image/jpeg', 'image/pjpeg', 'image/jpg'},
}


def get_improvement_service_projects(cursor=None):
    own_conn = None
    c = cursor
    projects = []
    seen = set()

    def add_project(name):
        text = str(name or '').strip()
        if not text or text in seen:
            return
        seen.add(text)
        projects.append(text)

    try:
        if c is None:
            own_conn = get_db()
            c = own_conn.cursor()

        for item in IMPROVEMENT_SERVICE_PROJECTS:
            add_project(item)

        c.execute("SELECT name FROM therapy_projects WHERE COALESCE(status, 'enabled')='enabled' ORDER BY id ASC")
        for row in c.fetchall():
            add_project(row['name'])

        c.execute("SELECT project_name FROM project_staff_mapping WHERE COALESCE(status, 'enabled')='enabled' ORDER BY id ASC")
        for row in c.fetchall():
            add_project(row['project_name'])

        c.execute("SELECT project_name FROM project_rules WHERE allow_home=1 AND COALESCE(status, 'enabled')='enabled' ORDER BY id ASC")
        for row in c.fetchall():
            add_project(row['project_name'])

        c.execute("SELECT DISTINCT service_project FROM home_appointments WHERE COALESCE(service_project, '')<>'' ORDER BY service_project ASC")
        for row in c.fetchall():
            add_project(row['service_project'])
        return projects
    finally:
        if own_conn:
            own_conn.close()


def get_customer_privacy_folder(customer_name, customer_phone, customer_id):
    name_text = str(customer_name or '').strip()
    surname = sanitize_folder_part(name_text[:1], f'user_{customer_id}')
    phone_digits = re.sub(r'\D', '', str(customer_phone or ''))
    phone_last4 = phone_digits[-4:] if len(phone_digits) >= 4 else 'no_phone'
    return f'{surname}_{phone_last4}'


def sanitize_folder_part(value, fallback):
    text = str(value or '').strip()
    if not text:
        return fallback
    text = re.sub(r'[\\/:*?"<>|]+', '_', text)
    text = re.sub(r'\s+', '_', text)
    text = text.strip('._')
    return text[:80] or fallback


def generate_time_slots(start='08:30', end='16:00', interval_minutes=30):
    slots = []
    t = datetime.strptime(start, '%H:%M')
    end_t = datetime.strptime(end, '%H:%M')
    while t < end_t:
        nxt = t + timedelta(minutes=interval_minutes)
        slots.append((t.strftime('%H:%M'), nxt.strftime('%H:%M')))
        t = nxt
    return slots

def is_valid_home_time_range(start_time, end_time):
    if not start_time or not end_time:
        return False
    return '08:30' <= start_time < end_time <= '16:00'


def is_half_hour_slot(start_time, end_time):
    if not is_valid_time(start_time) or not is_valid_time(end_time):
        return False
    st = datetime.strptime(start_time, '%H:%M')
    et = datetime.strptime(end_time, '%H:%M')
    if et <= st:
        return False
    diff = int((et - st).total_seconds() / 60)
    return diff == 30 and st.minute in (0, 30) and et.minute in (0, 30)


def is_today_or_future(date_str):
    if not date_str:
        return False
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date() >= now_local().date()
    except ValueError:
        return False


def validate_customer_payload(d):
    name = str(d.get('name') or '').strip()
    id_card = str(d.get('id_card') or '').strip().upper()
    phone = str(d.get('phone') or '').strip()
    address = str(d.get('address') or '').strip()
    gender = str(d.get('gender') or '').strip()
    birth_date = str(d.get('birth_date') or '').strip()
    identity_type = d.get('identity_type')
    record_creator = str(d.get('record_creator') or '').strip()

    if not name:
        return '姓名为必填项'
    if id_card and not re.fullmatch(r'^\d{17}[\dX]$', id_card):
        return '身份证格式不正确'
    if not re.fullmatch(r'^1\d{10}$', phone):
        return '手机号格式不正确'
    if not gender:
        return '性别为必填项'
    if gender not in {'男', '女'}:
        return '性别仅支持：男/女'
    if birth_date:
        try:
            datetime.strptime(birth_date, '%Y-%m-%d')
        except ValueError:
            return '出生日期格式必须为 YYYY-MM-DD'
    else:
        return '出生日期为必填项'
    if isinstance(identity_type, list):
        identities = [str(x).strip() for x in identity_type if str(x).strip()]
    else:
        identities = [x for x in str(identity_type or '').split('、') if x]
    if not identities:
        return '身份至少选择一项'
    allowed_identities = {'本人', '家属'}
    if any(x not in allowed_identities for x in identities):
        return '身份仅支持：本人/家属'
    if not record_creator:
        return '建档人为必填项'
    return None


def is_valid_date(value):
    try:
        datetime.strptime(str(value or '').strip(), '%Y-%m-%d')
        return True
    except ValueError:
        return False


def is_valid_time(value):
    try:
        datetime.strptime(str(value or '').strip(), '%H:%M')
        return True
    except ValueError:
        return False


def validate_appointment_payload(d):
    required_fields = ('customer_id', 'project_id', 'appointment_date', 'start_time', 'end_time')
    if not all(d.get(k) for k in required_fields):
        return '缺少必填字段'
    if not is_valid_date(d.get('appointment_date')):
        return '预约日期格式必须为 YYYY-MM-DD'
    if not is_valid_time(d.get('start_time')) or not is_valid_time(d.get('end_time')):
        return '预约时间格式必须为 HH:MM'
    if d.get('start_time') >= d.get('end_time'):
        return '结束时间必须晚于开始时间'
    status = str(d.get('status') or 'scheduled').strip().lower()
    if status not in {'scheduled', 'cancelled'}:
        return '预约状态不合法'
    return None


def validate_home_appointment_payload(d):
    required_fields = ('customer_id', 'project_id', 'appointment_date', 'start_time', 'end_time', 'location', 'contact_phone')
    if not all(d.get(k) for k in required_fields):
        return '缺少必填字段'
    if not is_valid_date(d.get('appointment_date')):
        return '预约日期格式必须为 YYYY-MM-DD'
    if not is_valid_time(d.get('start_time')) or not is_valid_time(d.get('end_time')):
        return '预约时间格式必须为 HH:MM'
    if not is_valid_home_time_range(d.get('start_time'), d.get('end_time')):
        return '上门预约时间需在08:30-16:00且结束时间晚于开始时间'
    if not is_half_hour_slot(d.get('start_time'), d.get('end_time')):
        return '上门预约时间段需按30分钟选择'
    contact_phone = str(d.get('contact_phone') or '').strip()
    if contact_phone and not re.fullmatch(r'^1\d{10}$', contact_phone):
        return '联系人手机号格式不正确'
    status = str(d.get('status') or 'scheduled').strip().lower()
    if status not in {'scheduled', 'cancelled'}:
        return '预约状态不合法'
    return None


def get_latest_assessment_summary(cursor, customer_id):
    cursor.execute(
        '''
        SELECT *
        FROM health_assessments
        WHERE customer_id=?
        ORDER BY assessment_date DESC, id DESC
        LIMIT 1
        ''',
        (customer_id,),
    )
    row = cursor.fetchone()
    if not row:
        return ''
    data = dict(row)
    summary_parts = []
    for label, key in (
        ('既往病史', 'past_medical_history'),
        ('近期症状', 'recent_symptoms'),
        ('睡眠', 'sleep_quality'),
        ('血压', 'blood_pressure_test'),
        ('血脂', 'blood_lipid_test'),
        ('血糖', 'blood_sugar_test'),
        ('最影响生活问题', 'life_impact_issues'),
    ):
        value = str(data.get(key) or '').strip()
        if value:
            summary_parts.append(f'{label}:{value}')
    return '；'.join(summary_parts)


def validate_improvement_payload(d, cursor=None):
    required_fields = ('customer_id', 'service_time', 'service_project', 'improvement_status')
    if not all(str(d.get(k) or '').strip() for k in required_fields):
        return '缺少必填字段'
    allowed_projects = get_improvement_service_projects(cursor)
    if str(d.get('service_project') or '').strip() not in allowed_projects:
        return '服务项目不合法'
    if str(d.get('improvement_status') or '').strip() not in IMPROVEMENT_STATUS_OPTIONS:
        return '改善情况不合法'
    followup_method = str(d.get('followup_method') or '').strip()
    if followup_method and followup_method not in FOLLOWUP_METHOD_OPTIONS:
        return '随访方式不合法'
    return None


def success_response(data=None, message='操作成功', status=200):
    return jsonify({'success': True, 'message': message, 'data': data if data is not None else {}}), status


def error_response(message, status=400, error_code='VALIDATION_ERROR'):
    return jsonify({'success': False, 'message': message, 'error_code': error_code}), status


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_err):
    return error_response('上传文件过大，单个文件不能超过 10MB', 413, 'FILE_TOO_LARGE')


def parse_list_params(default_page_size=20, max_page_size=100):
    page = request.args.get('page', default=1, type=int) or 1
    page_size = request.args.get('page_size', default=default_page_size, type=int) or default_page_size
    page = max(page, 1)
    page_size = min(max(page_size, 1), max_page_size)
    offset = (page - 1) * page_size
    return page, page_size, offset


def paginate_result(items, total, page, page_size):
    return {
        'items': items,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': (total + page_size - 1) // page_size if page_size else 0,
        }
    }


def get_project_required_equipment_name(project_name, cursor=None):
    own_conn = None
    c = cursor
    try:
        if c is None:
            own_conn = get_db()
            c = own_conn.cursor()
        c.execute(
            "SELECT equipment_name FROM project_equipment_mapping WHERE project_name=? AND status='enabled' LIMIT 1",
            (project_name,),
        )
        row = c.fetchone()
        return row['equipment_name'] if row else None
    finally:
        if own_conn is not None:
            own_conn.close()


def get_project_required_equipment_names(project_name, cursor=None):
    own_conn = None
    c = cursor
    try:
        if c is None:
            own_conn = get_db()
            c = own_conn.cursor()
        c.execute(
            "SELECT equipment_name FROM project_equipment_mapping WHERE project_name=? AND status='enabled' ORDER BY id ASC",
            (project_name,),
        )
        rows = [r['equipment_name'] for r in c.fetchall() if r['equipment_name']]
        if rows:
            return rows
        single = get_project_required_equipment_name(project_name, c)
        return [single] if single else []
    finally:
        if own_conn is not None:
            own_conn.close()


def get_project_available_equipment(project_name, cursor):
    names = get_project_required_equipment_names(project_name, cursor)
    if names:
        for idx, equipment_name in enumerate(names, start=1):
            cursor.execute(
                "SELECT id, status FROM equipment WHERE name=? LIMIT 1",
                (equipment_name,),
            )
            existing_equipment = cursor.fetchone()
            if not existing_equipment:
                cursor.execute(
                    '''
                    INSERT INTO equipment (name, type, model, location, status, description)
                    VALUES (?,?,?,?,?,?)
                    ''',
                    (
                        equipment_name,
                        '专用设备',
                        f'{idx:02d}',
                        '',
                        'available',
                        f'{project_name}预约设备',
                    ),
                )
        ph = ','.join('?' * len(names))
        cursor.execute(
            f"SELECT id, name, location, model, status FROM equipment WHERE name IN ({ph}) ORDER BY name ASC, id ASC",
            tuple(names),
        )
    else:
        cursor.execute(
            "SELECT id, name, location, model, status FROM equipment ORDER BY name ASC, id ASC"
        )
    return row_list(cursor.fetchall())


def is_project_home_allowed(project_name, cursor=None):
    own_conn = None
    c = cursor
    try:
        if c is None:
            own_conn = get_db()
            c = own_conn.cursor()
        c.execute(
            "SELECT allow_home FROM project_rules WHERE project_name=? AND status='enabled' LIMIT 1",
            (project_name,),
        )
        row = c.fetchone()
        return bool(row and row['allow_home'] == 1)
    finally:
        if own_conn is not None:
            own_conn.close()



HEALTH_ASSESSMENT_ALLOWED_VALUES = {
    'allergy_history': {'无', '有'},
    'smoking_status': {'无', '有'},
    'drinking_status': {'无', '有'},
    'sleep_quality': {'很差', '差', '一般', '良好'},
    'sleep_hours': {'<6小时', '6-8小时', '9-10小时', '>10小时'},
    'blood_pressure_test': {'未监测', '监测：正常', '监测：偏低', '监测：偏高'},
    'blood_lipid_test': {'未监测', '监测：正常', '监测：偏高'},
    'blood_sugar_test': {'未监测', '监测：正常', '监测：偏低', '监测：偏高'},
    'chronic_pain': {'无', '有'},
}

HEALTH_PORTRAIT_DISEASE_MAP = {
    '循环系统': [
        ('高血压', ['高血压', '血压偏高', '血压高']),
        ('冠心病', ['冠心病']),
        ('心衰', ['心衰', '心力衰竭']),
        ('脑梗', ['脑梗', '脑梗死', '脑卒中']),
    ],
    '内分泌代谢': [
        ('糖尿病', ['糖尿病', '血糖高']),
        ('高血脂', ['高血脂', '血脂偏高', '血脂高']),
        ('肥胖', ['肥胖']),
        ('甲状腺疾病', ['甲状腺', '甲亢', '甲减']),
    ],
    '运动系统': [
        ('颈椎病', ['颈椎病', '颈椎']),
        ('腰椎病', ['腰椎病', '腰椎']),
        ('关节炎', ['关节炎', '关节痛']),
        ('骨质疏松', ['骨质疏松']),
    ],
    '消化系统': [
        ('胃炎', ['胃炎']),
        ('脂肪肝', ['脂肪肝']),
        ('便秘', ['便秘']),
    ],
    '呼吸系统': [
        ('慢阻肺', ['慢阻肺', 'copd']),
        ('哮喘', ['哮喘']),
    ],
    '神经系统': [
        ('头痛', ['头痛', '偏头痛']),
        ('失眠', ['失眠', '睡眠差', '睡眠很差']),
        ('脑梗后遗症', ['脑梗后遗症']),
    ],
    '妇科 / 男科 / 儿科': [
        ('妇科问题', ['妇科', '月经', '宫颈', '卵巢']),
        ('男科问题', ['男科', '前列腺']),
        ('儿科问题', ['儿科']),
    ],
    '肿瘤 / 恶性疾病': [
        ('肿瘤', ['肿瘤', '癌', '恶性']),
    ],
    '其他疾病': [
        ('其他疾病', ['疾病', '病史']),
    ],
}


def validate_health_assessment_enums(data):
    for field, allowed in HEALTH_ASSESSMENT_ALLOWED_VALUES.items():
        value = data.get(field)
        if value in (None, ''):
            continue
        if value not in allowed:
            return f'{field} 的值非法: {value}'
    return None


def extract_health_portrait(record):
    text_fields = [
        record.get('past_medical_history'),
        record.get('family_history'),
        record.get('pain_details'),
        record.get('notes'),
        record.get('chronic_diseases'),
        record.get('medical_history'),
        record.get('allergy_details'),
        record.get('blood_pressure_test'),
        record.get('blood_lipid_test'),
        record.get('blood_sugar_test'),
        record.get('recent_symptoms'),
        record.get('life_impact_issues'),
    ]
    source_text = ' '.join([str(v or '').lower() for v in text_fields])
    normalized_text = re.sub(r'\s+', '', source_text)
    diseases = []
    disease_categories = set()
    for category, pairs in HEALTH_PORTRAIT_DISEASE_MAP.items():
        for disease_name, keywords in pairs:
            if any(keyword.lower().replace(' ', '') in normalized_text for keyword in keywords):
                diseases.append({'name': disease_name, 'category': category})
                disease_categories.add(category)

    if record.get('chronic_pain') == '有':
        diseases.append({'name': '慢性疼痛', 'category': '运动系统'})
        disease_categories.add('运动系统')
    if record.get('sleep_quality') in ('很差', '差'):
        diseases.append({'name': '睡眠质量差', 'category': '神经系统'})
        disease_categories.add('神经系统')
    if record.get('blood_pressure_test') == '监测：偏高':
        diseases.append({'name': '血压偏高', 'category': '循环系统'})
        disease_categories.add('循环系统')
    if record.get('blood_lipid_test') == '监测：偏高':
        diseases.append({'name': '血脂偏高', 'category': '内分泌代谢'})
        disease_categories.add('内分泌代谢')

    unique = {}
    for item in diseases:
        unique[item['name']] = item
    disease_list = list(unique.values())
    disease_count = len(disease_list)

    age = record.get('age')
    try:
        age = int(age) if age is not None else None
    except Exception:
        age = None
    smoking = record.get('smoking_status') == '有'
    drinking = record.get('drinking_status') == '有'
    weak_sleep = record.get('sleep_quality') in ('很差', '差')
    risk_score = disease_count + (1 if smoking else 0) + (1 if drinking else 0) + (1 if weak_sleep else 0)
    if age and age >= 65:
        risk_score += 1

    risk_level = '低风险'
    if risk_score >= 5:
        risk_level = '高风险'
    elif risk_score >= 3:
        risk_level = '中风险'

    return {
        'risk_level': risk_level,
        'diseases': disease_list,
        'categories': list(disease_categories),
    }


def safe_int(value):
    try:
        if value in (None, ''):
            return None
        return int(float(value))
    except Exception:
        return None


def safe_float(value):
    try:
        if value in (None, ''):
            return None
        return float(value)
    except Exception:
        return None


def normalize_multi_text(value):
    if value in (None, ''):
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
    except Exception:
        pass
    raw = str(value).replace('；', ',').replace('、', ',').replace('/', ',').replace('|', ',')
    return [x.strip() for x in raw.split(',') if x.strip()]


def classify_bmi(height_cm, weight_kg):
    h = safe_float(height_cm)
    w = safe_float(weight_kg)
    if not h or not w or h <= 0:
        return None, None
    h_m = h / 100.0
    bmi = round(w / (h_m * h_m), 1)
    if bmi < 18.5:
        level = '偏瘦'
    elif bmi < 24:
        level = '正常'
    elif bmi < 28:
        level = '超重'
    else:
        level = '肥胖'
    return bmi, level


def is_indicator_abnormal(value):
    text = str(value or '')
    return ('偏高' in text) or ('偏低' in text)


def calculate_lightweight_risk(row):
    reasons = []

    age = safe_int(row.get('age'))
    if age is None and row.get('birth_date'):
        try:
            birth = datetime.strptime(str(row.get('birth_date'))[:10], '%Y-%m-%d').date()
            today = now_local().date()
            age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        except Exception:
            age = None
    if age is not None and age >= 70:
        reasons.append('年龄≥70')

    bmi_value, bmi_level = classify_bmi(row.get('height_cm'), row.get('weight_kg'))
    if bmi_level and bmi_level != '正常':
        reasons.append(f'BMI异常（{bmi_level}）')

    blood_pressure_test = str(row.get('blood_pressure_test') or '')
    if is_indicator_abnormal(blood_pressure_test):
        reasons.append('血压异常')

    blood_sugar_test = str(row.get('blood_sugar_test') or '')
    if is_indicator_abnormal(blood_sugar_test):
        reasons.append('血糖异常')

    blood_lipid_test = str(row.get('blood_lipid_test') or '')
    if '偏高' in blood_lipid_test:
        reasons.append('血脂异常')

    family_history_items = normalize_multi_text(row.get('family_history'))
    if family_history_items:
        reasons.append('家族史阳性')

    if str(row.get('sleep_quality') or '') in ('很差', '差'):
        reasons.append('睡眠差')

    recent_symptom_items = normalize_multi_text(row.get('recent_symptoms'))
    if len(recent_symptom_items) >= 2:
        reasons.append('近期症状≥2项')

    score = len(reasons)
    if score >= 4:
        level = '高风险'
    elif score >= 2:
        level = '中风险'
    else:
        level = '低风险'

    intervention_suggestions = []
    if any(item in ('血压异常', '血糖异常', '血脂异常') for item in reasons):
        intervention_suggestions.append('优先慢病指标复测与医生随访')
    if any(item.startswith('BMI异常') for item in reasons):
        intervention_suggestions.append('营养+运动联合体重管理')
    if '睡眠差' in reasons:
        intervention_suggestions.append('开展睡眠评估与作息干预')
    if '近期症状≥2项' in reasons:
        intervention_suggestions.append('安排综合评估与重点症状排查')
    if '家族史阳性' in reasons:
        intervention_suggestions.append('强化家族史相关专项筛查')
    if '年龄≥70' in reasons:
        intervention_suggestions.append('提升老年综合健康管理频次')
    if not intervention_suggestions:
        intervention_suggestions.append('保持常规健康随访')

    return {
        'risk_score': score,
        'risk_level': level,
        'risk_reasons': reasons,
        'recommended_intervention': '；'.join(intervention_suggestions[:3]),
        'age': age,
        'bmi': bmi_value,
    }


def classify_age_segment(age):
    if age is None:
        return None
    if age < 50:
        return '<50岁'
    if age <= 60:
        return '50-60岁'
    if age <= 65:
        return '61-65岁'
    if age <= 70:
        return '66-70岁'
    if age <= 75:
        return '71-75岁'
    if age <= 80:
        return '76-80岁'
    return '>80岁'


def init_db():
    conn = get_db()
    c = conn.cursor()
    migrate_appointments_equipment_nullable(c)

    c.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            id_card TEXT UNIQUE,
            phone TEXT NOT NULL,
            email TEXT,
            address TEXT,
            gender TEXT,
            age INTEGER,
            birth_date TEXT,
            identity_type TEXT,
            military_rank TEXT,
            record_creator TEXT,
            medical_history TEXT,
            allergies TEXT,
            diet_habits TEXT,
            chronic_diseases TEXT,
            health_status TEXT,
            therapy_contraindications TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
        )
    ''')

    # 历史数据库兼容：缺失字段时自动补齐
    c.execute('PRAGMA table_info(customers)')
    customer_columns = {row[1] for row in c.fetchall()}
    extra_customer_columns = {
        'age': 'INTEGER',
        'identity_type': 'TEXT',
        'military_rank': 'TEXT',
        'record_creator': 'TEXT',
        'diet_habits': 'TEXT',
        'chronic_diseases': 'TEXT',
        'health_status': 'TEXT',
        'therapy_contraindications': 'TEXT',
        'is_deleted': 'INTEGER DEFAULT 0',
    }
    for col, col_type in extra_customer_columns.items():
        if col not in customer_columns:
            c.execute(f'ALTER TABLE customers ADD COLUMN {col} {col_type}')

    c.execute('''
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            model TEXT,
            location TEXT,
            status TEXT DEFAULT 'available',
            description TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
        )
    ''')

    ensure_columns(c, 'equipment', {
        'model': 'TEXT',
        'location': 'TEXT',
        'status': "TEXT DEFAULT 'available'",
        'description': 'TEXT',
        'created_at': "TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))",
    })

    c.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_group_id TEXT,
            customer_id INTEGER NOT NULL,
            equipment_id INTEGER,
            project_id INTEGER,
            staff_id INTEGER,
            appointment_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT DEFAULT 'scheduled',
            checkin_status TEXT DEFAULT 'pending',
            checkin_updated_at TEXT,
            checkin_updated_by TEXT,
            checkin_updated_ip TEXT,
            has_companion TEXT DEFAULT '无',
            notes TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            source_record_id INTEGER,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (equipment_id) REFERENCES equipment(id)
        )
    ''')

    ensure_columns(c, 'appointments', {
        'booking_group_id': 'TEXT',
        'equipment_id': 'INTEGER',
        'project_id': 'INTEGER',
        'staff_id': 'INTEGER',
        'appointment_date': 'TEXT',
        'start_time': 'TEXT',
        'end_time': 'TEXT',
        'status': "TEXT DEFAULT 'scheduled'",
        'notes': 'TEXT',
        'has_companion': "TEXT DEFAULT '无'",
        'created_at': "TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))",
        'updated_at': "TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))",
        'source_record_id': 'INTEGER',
        'checkin_status': "TEXT DEFAULT 'pending'",
        'checkin_updated_at': 'TEXT',
        'checkin_updated_by': 'TEXT',
        'checkin_updated_ip': 'TEXT',
    })

    c.execute('DROP TABLE IF EXISTS equipment_usage')

    c.execute('''
        CREATE TABLE IF NOT EXISTS health_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            assessment_date TEXT NOT NULL,
            assessor TEXT,
            age INTEGER,
            height_cm REAL,
            weight_kg REAL,
            address TEXT,
            past_medical_history TEXT,
            family_history TEXT,
            allergy_history TEXT,
            allergy_details TEXT,
            smoking_status TEXT,
            smoking_years INTEGER,
            cigarettes_per_day INTEGER,
            drinking_status TEXT,
            drinking_years INTEGER,
            sleep_quality TEXT,
            sleep_hours TEXT,
            recent_symptoms TEXT,
            recent_symptom_detail TEXT,
            life_impact_issues TEXT,
            blood_pressure_test TEXT,
            blood_lipid_test TEXT,
            blood_sugar_test TEXT,
            chronic_pain TEXT,
            pain_details TEXT,
            exercise_methods TEXT,
            health_needs TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    ''')
    ensure_columns(c, 'health_assessments', {
        'recent_symptoms': 'TEXT',
        'recent_symptom_detail': 'TEXT',
        'life_impact_issues': 'TEXT',
        'blood_sugar_test': 'TEXT',
    })
    c.execute('PRAGMA table_info(health_assessments)')
    health_assessment_columns = {row[1] for row in c.fetchall()}
    if 'fatigue_last_month' in health_assessment_columns or 'weekly_exercise_freq' in health_assessment_columns:
        c.execute('ALTER TABLE health_assessments RENAME TO health_assessments_old')
        c.execute('''
            CREATE TABLE health_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                assessment_date TEXT NOT NULL,
                assessor TEXT,
                age INTEGER,
                height_cm REAL,
                weight_kg REAL,
                address TEXT,
                past_medical_history TEXT,
                family_history TEXT,
                allergy_history TEXT,
                allergy_details TEXT,
                smoking_status TEXT,
                smoking_years INTEGER,
                cigarettes_per_day INTEGER,
                drinking_status TEXT,
                drinking_years INTEGER,
                sleep_quality TEXT,
                sleep_hours TEXT,
                recent_symptoms TEXT,
                recent_symptom_detail TEXT,
                life_impact_issues TEXT,
                blood_pressure_test TEXT,
                blood_lipid_test TEXT,
                blood_sugar_test TEXT,
                chronic_pain TEXT,
                pain_details TEXT,
                exercise_methods TEXT,
                health_needs TEXT,
                notes TEXT,
                created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )
        ''')
        c.execute('''
            INSERT INTO health_assessments (
                id, customer_id, assessment_date, assessor, age, height_cm, weight_kg, address, past_medical_history, family_history,
                allergy_history, allergy_details, smoking_status, smoking_years, cigarettes_per_day, drinking_status, drinking_years,
                sleep_quality, sleep_hours, recent_symptoms, recent_symptom_detail, life_impact_issues, blood_pressure_test, blood_lipid_test,
                blood_sugar_test, chronic_pain, pain_details, exercise_methods, health_needs, notes, created_at
            )
            SELECT
                id, customer_id, assessment_date, assessor, age, height_cm, weight_kg, address, past_medical_history, family_history,
                allergy_history, allergy_details, smoking_status, smoking_years, cigarettes_per_day, drinking_status, drinking_years,
                sleep_quality, sleep_hours, recent_symptoms, recent_symptom_detail, life_impact_issues, blood_pressure_test, blood_lipid_test,
                blood_sugar_test, chronic_pain, pain_details, exercise_methods, health_needs, notes, created_at
            FROM health_assessments_old
        ''')
        c.execute('DROP TABLE health_assessments_old')

    c.execute('''
        CREATE TABLE IF NOT EXISTS therapy_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            duration_minutes INTEGER,
            need_equipment INTEGER DEFAULT 0,
            equipment_type TEXT,
            price REAL,
            status TEXT DEFAULT 'enabled',
            description TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
        )
    ''')

    ensure_columns(c, 'therapy_projects', {
        'category': 'TEXT',
        'duration_minutes': 'INTEGER',
        'need_equipment': 'INTEGER DEFAULT 0',
        'equipment_type': 'TEXT',
        'price': 'REAL',
        'status': "TEXT DEFAULT 'enabled'",
        'description': 'TEXT',
        'created_at': "TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))",
    })

    c.execute('DROP TABLE IF EXISTS service_projects')

    c.execute('''
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT,
            phone TEXT,
            status TEXT DEFAULT 'available',
            notes TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
        )
    ''')

    ensure_columns(c, 'staff', {
        'role': 'TEXT',
        'phone': 'TEXT',
        'status': "TEXT DEFAULT 'available'",
        'notes': 'TEXT',
        'created_at': "TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))",
    })

    c.execute('''
        CREATE TABLE IF NOT EXISTS home_appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_group_id TEXT,
            customer_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            staff_id INTEGER,
            customer_name TEXT,
            phone TEXT,
            home_time TEXT,
            home_address TEXT,
            service_project TEXT,
            staff_name TEXT,
            appointment_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            location TEXT NOT NULL,
            contact_person TEXT,
            contact_phone TEXT,
            has_companion TEXT DEFAULT '无',
            notes TEXT,
            status TEXT DEFAULT 'scheduled',
            checkin_status TEXT DEFAULT 'pending',
            checkin_updated_at TEXT,
            checkin_updated_by TEXT,
            checkin_updated_ip TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            source_record_id INTEGER,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (project_id) REFERENCES therapy_projects(id),
            FOREIGN KEY (staff_id) REFERENCES staff(id)
        )
    ''')

    ensure_columns(c, 'home_appointments', {
        'booking_group_id': 'TEXT',
        'project_id': 'INTEGER',
        'staff_id': 'INTEGER',
        'customer_name': 'TEXT',
        'phone': 'TEXT',
        'home_time': 'TEXT',
        'home_address': 'TEXT',
        'service_project': 'TEXT',
        'staff_name': 'TEXT',
        'appointment_date': 'TEXT',
        'start_time': 'TEXT',
        'end_time': 'TEXT',
        'location': 'TEXT',
        'contact_person': 'TEXT',
        'contact_phone': 'TEXT',
        'has_companion': "TEXT DEFAULT '无'",
        'notes': 'TEXT',
        'status': "TEXT DEFAULT 'scheduled'",
        'updated_at': "TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))",
        'created_at': "TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))",
        'source_record_id': 'INTEGER',
        'checkin_status': "TEXT DEFAULT 'pending'",
        'checkin_updated_at': 'TEXT',
        'checkin_updated_by': 'TEXT',
        'checkin_updated_ip': 'TEXT',
    })

    c.execute('''
        CREATE TABLE IF NOT EXISTS db_backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_file TEXT,
            backup_time TEXT,
            backup_type TEXT,
            status TEXT,
            notes TEXT
        )
    ''')


    c.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT,
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            action TEXT,
            module TEXT,
            target_id TEXT,
            details TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS business_history_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            operator TEXT,
            operator_ip TEXT,
            before_content TEXT,
            after_content TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
        )
    ''')
    ensure_columns(c, 'business_history_logs', {
        'operator_ip': 'TEXT',
    })

    c.execute('''
        CREATE TABLE IF NOT EXISTS task_execution_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT NOT NULL,
            task_date TEXT,
            affected_rows INTEGER DEFAULT 0,
            details TEXT,
            executed_by TEXT,
            executed_ip TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
        )
    ''')

    c.execute('INSERT OR IGNORE INTO system_settings (setting_key, setting_value) VALUES (?, ?)',
              ('backup_directory', BACKUP_FOLDER))
    c.execute('INSERT OR IGNORE INTO system_settings (setting_key, setting_value) VALUES (?, ?)',
              ('login_username', 'admin'))
    c.execute('INSERT OR IGNORE INTO system_settings (setting_key, setting_value) VALUES (?, ?)',
              ('password_hash', generate_password_hash('123456')))

    # 启动时兼容迁移：
    # 1) 若存在旧版明文 admin_password/login_password，则转为 password_hash
    # 2) 迁移后清空明文字段，确保不再明文存储
    c.execute(
        '''
        SELECT setting_key, setting_value
        FROM system_settings
        WHERE setting_key IN ('admin_password', 'login_password')
        ORDER BY CASE WHEN setting_key='admin_password' THEN 0 ELSE 1 END
        '''
    )
    legacy_rows = c.fetchall()
    legacy_plaintext = ''
    for item in legacy_rows:
        value = str(item['setting_value'] or '').strip()
        if value:
            legacy_plaintext = value
            break
    if legacy_plaintext:
        now_ts = now_local_str()
        c.execute(
            '''
            INSERT INTO system_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value=excluded.setting_value,
                updated_at=excluded.updated_at
            ''',
            ('password_hash', generate_password_hash(legacy_plaintext), now_ts),
        )
        c.execute(
            '''
            INSERT INTO system_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value=excluded.setting_value,
                updated_at=excluded.updated_at
            ''',
            ('admin_password', '', now_ts),
        )
        c.execute(
            '''
            INSERT INTO system_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value=excluded.setting_value,
                updated_at=excluded.updated_at
            ''',
            ('login_password', '', now_ts),
        )

    c.execute('''
        CREATE TABLE IF NOT EXISTS project_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL UNIQUE,
            allow_home INTEGER DEFAULT 0,
            project_category TEXT,
            status TEXT DEFAULT 'enabled',
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS project_staff_mapping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            staff_id INTEGER NOT NULL,
            status TEXT DEFAULT 'enabled',
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            UNIQUE(project_name, staff_id),
            FOREIGN KEY (staff_id) REFERENCES staff(id)
        )
    ''')

    # 统一启用新结构：单项目可绑定多设备。
    # 为避免旧唯一索引逻辑混杂，这里直接重建映射表结构。
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='project_equipment_mapping'")
    has_mapping_table = c.fetchone() is not None
    legacy_mappings = []
    if has_mapping_table:
        c.execute(
            '''
            SELECT project_name, equipment_name, status, created_at, updated_at
              FROM project_equipment_mapping
            '''
        )
        legacy_mappings = row_list(c.fetchall())
        c.execute('DROP TABLE project_equipment_mapping')

    c.execute('''
        CREATE TABLE project_equipment_mapping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            equipment_name TEXT NOT NULL,
            status TEXT DEFAULT 'enabled',
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            UNIQUE(project_name, equipment_name)
        )
    ''')

    if legacy_mappings:
        c.executemany(
            '''
            INSERT OR IGNORE INTO project_equipment_mapping
                (project_name, equipment_name, status, created_at, updated_at)
            VALUES (?,?,?,?,?)
            ''',
            [
                (
                    row.get('project_name'),
                    row.get('equipment_name'),
                    row.get('status') or 'enabled',
                    row.get('created_at'),
                    row.get('updated_at'),
                )
                for row in legacy_mappings
                if row.get('project_name') and row.get('equipment_name')
            ],
        )

    c.execute('DROP TABLE IF EXISTS satisfaction_surveys')

    c.execute('''
        CREATE TABLE IF NOT EXISTS health_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            record_date TEXT NOT NULL,
            height_cm REAL,
            weight_kg REAL,
            blood_pressure TEXT,
            symptoms TEXT,
            diagnosis TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS visit_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            checkin_time TEXT NOT NULL,
            purpose TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    ''')

    ensure_columns(c, 'visit_checkins', {
        'purpose': 'TEXT',
        'notes': 'TEXT',
        'created_at': "TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))",
    })

    c.execute('''
        CREATE TABLE IF NOT EXISTS service_improvement_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER,
            service_type TEXT DEFAULT 'appointments',
            customer_id INTEGER NOT NULL,
            service_time TEXT NOT NULL,
            service_project TEXT NOT NULL,
            pre_service_status TEXT,
            service_content TEXT,
            post_service_evaluation TEXT,
            improvement_status TEXT NOT NULL,
            followup_time TEXT,
            followup_date TEXT,
            followup_method TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    ''')
    ensure_columns(c, 'service_improvement_records', {
        'service_id': 'INTEGER',
        'service_type': "TEXT DEFAULT 'appointments'",
        'customer_id': 'INTEGER',
        'service_time': 'TEXT',
        'service_project': 'TEXT',
        'pre_service_status': 'TEXT',
        'service_content': 'TEXT',
        'post_service_evaluation': 'TEXT',
        'improvement_status': 'TEXT',
        'followup_time': 'TEXT',
        'followup_date': 'TEXT',
        'followup_method': 'TEXT',
        'updated_at': "TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))",
    })
    migrate_service_improvement_records_drop_followup_result(c)

    c.execute('''
        CREATE TABLE IF NOT EXISTS improvement_record_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            improvement_record_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            file_ext TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            uploaded_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (improvement_record_id) REFERENCES service_improvement_records(id)
        )
    ''')
    ensure_columns(c, 'improvement_record_files', {
        'customer_id': 'INTEGER',
        'improvement_record_id': 'INTEGER',
        'file_name': 'TEXT',
        'file_ext': 'TEXT',
        'file_path': 'TEXT',
        'file_size': 'INTEGER DEFAULT 0',
        'uploaded_at': "TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime'))",
    })

    c.execute("SELECT COUNT(*) FROM equipment")
    if c.fetchone()[0] == 0:
        pass

    c.execute("SELECT COUNT(*) FROM therapy_projects")
    if c.fetchone()[0] == 0:
        for row in [
            ('红外理疗', '理疗', 60, 1, '理疗设备', 0, 'enabled', '红外热疗项目'),
            ('超声理疗', '理疗', 45, 1, '理疗设备', 0, 'enabled', '超声理疗项目'),
            ('电刺激治疗', '康复', 45, 1, '康复设备', 0, 'enabled', '电刺激治疗项目'),
            ('磁疗', '理疗', 40, 1, '理疗设备', 0, 'enabled', '磁疗项目'),
            ('牵引治疗', '康复', 60, 1, '康复设备', 0, 'enabled', '颈腰椎牵引'),
            ('中药熏蒸', '中医', 50, 1, '中医设备', 0, 'enabled', '中药熏蒸项目'),
            ('康复训练指导', '康复', 60, 0, None, 0, 'enabled', '康复训练与指导'),
            ('中医养生咨询', '中医', 30, 0, None, 0, 'enabled', '中医养生咨询'),
            ('上门康复护理', '上门', 60, 0, None, 0, 'enabled', '上门康复护理服务'),
        ]:
            c.execute('''
                INSERT INTO therapy_projects (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
                VALUES (?,?,?,?,?,?,?,?)
            ''', row)

    required_equipment_seeds = []
    for project_name, equipment_names in APPOINTMENT_PROJECT_DEVICE_CONFIG.items():
        for idx, equipment_name in enumerate(equipment_names, start=1):
            required_equipment_seeds.append(
                (equipment_name, '专用设备', f'{idx:02d}', '', 'available', f'{project_name}预约设备')
            )
    for row in required_equipment_seeds:
        c.execute('SELECT id FROM equipment WHERE name=?', (row[0],))
        if not c.fetchone():
            c.execute(
                'INSERT INTO equipment (name, type, model, location, status, description) VALUES (?,?,?,?,?,?)',
                row,
            )

    required_project_seeds = [
        ('听力测试', '理疗', 30, 1, '专用设备', 0, 'enabled', '听力测试服务项目'),
        ('高压氧仓', '理疗', 60, 1, '专用设备', 0, 'enabled', '高压氧仓服务项目'),
        ('艾灸', '中医', 45, 1, '专用设备', 0, 'enabled', '艾灸服务项目'),
    ]
    for row in required_project_seeds:
        c.execute('SELECT id FROM therapy_projects WHERE name=?', (row[0],))
        if not c.fetchone():
            c.execute(
                '''
                INSERT INTO therapy_projects (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
                VALUES (?,?,?,?,?,?,?,?)
                ''',
                row,
            )

    for project_name in APPOINTMENT_PROJECT_DEVICE_CONFIG.keys():
        c.execute('SELECT id FROM therapy_projects WHERE name=?', (project_name,))
        existing = c.fetchone()
        if not existing:
            c.execute(
                '''
                INSERT INTO therapy_projects (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
                VALUES (?,?,?,?,?,?,?,?)
                ''',
                (project_name, '理疗', 30, 1, '专用设备', 0, 'enabled', f'{project_name}服务项目'),
            )
        else:
            c.execute(
                '''UPDATE therapy_projects
                   SET need_equipment=1, equipment_type='专用设备', status='enabled'
                   WHERE id=?''',
                (existing['id'],),
            )

    for project_name, equipment_name in DEFAULT_PROJECT_EQUIPMENT_MAP.items():
        c.execute('''
            INSERT OR IGNORE INTO project_equipment_mapping (project_name, equipment_name, status)
            VALUES (?,?,?)
        ''', (project_name, equipment_name, 'enabled'))
    for project_name, equipment_names in APPOINTMENT_PROJECT_DEVICE_CONFIG.items():
        for equipment_name in equipment_names:
            c.execute('''
                INSERT OR IGNORE INTO project_equipment_mapping (project_name, equipment_name, status)
                VALUES (?,?,?)
            ''', (project_name, equipment_name, 'enabled'))
    for project_name, equipment_names in APPOINTMENT_PROJECT_DEVICE_CONFIG.items():
        placeholders = ','.join('?' * len(equipment_names))
        c.execute(
            f'''
            UPDATE project_equipment_mapping
               SET status='disabled'
             WHERE project_name=?
               AND equipment_name NOT IN ({placeholders})
            ''',
            (project_name, *equipment_names),
        )

    c.execute('SELECT name, category FROM therapy_projects')
    all_projects = row_list(c.fetchall())
    for project in all_projects:
        allow_home = 1 if project['name'] in DEFAULT_ALLOWED_HOME_PROJECTS else 0
        c.execute('''
            INSERT OR IGNORE INTO project_rules (project_name, allow_home, project_category, status)
            VALUES (?,?,?,?)
        ''', (project['name'], allow_home, project.get('category'), 'enabled'))

    c.execute("SELECT COUNT(*) FROM staff")
    if c.fetchone()[0] == 0:
        for row in [
            ('张理疗', '理疗师', '13800000001', 'available', '擅长理疗'),
            ('李康复', '康复师', '13800000002', 'available', '擅长康复训练'),
            ('王护理', '护士', '13800000003', 'available', '可上门服务'),
        ]:
            c.execute('INSERT INTO staff (name, role, phone, status, notes) VALUES (?,?,?,?,?)', row)

    project_staff_seed_map = {
        '上门康复护理': ['王护理', '李康复'],
        '中医养生咨询': ['张理疗', '王护理'],
        '康复训练指导': ['李康复', '张理疗'],
        '血糖测试': ['王护理'],
        '按摩': ['张理疗', '李康复'],
    }
    for project_name, staff_names in project_staff_seed_map.items():
        for staff_name in staff_names:
            c.execute("SELECT id FROM staff WHERE name=?", (staff_name,))
            staff_row = c.fetchone()
            if not staff_row:
                continue
            c.execute(
                '''
                INSERT OR IGNORE INTO project_staff_mapping (project_name, staff_id, status)
                VALUES (?,?,?)
                ''',
                (project_name, staff_row['id'], 'enabled'),
            )

    purge_legacy_equipment_and_store_massage(c)

    conn.commit()
    conn.close()
    print('数据库初始化完成，数据文件: %s' % DB_PATH)


# ========== 静态页面 ==========
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/<path:path>')
def static_file(path):
    return send_from_directory(app.static_folder, path)


# ========== 客户 ==========
@app.route('/api/customers', methods=['GET'])
def api_customers_list():
    q = (request.args.get('search', '') or '').strip()
    status = (request.args.get('status', '') or '').strip().lower()
    date_from = (request.args.get('date_from', '') or '').strip()
    date_to = (request.args.get('date_to', '') or '').strip()
    sort_by = (request.args.get('sort_by', '') or 'created_desc').strip()
    page, page_size, offset = parse_list_params()
    sort_map = {
        'created_desc': 'created_at DESC, id DESC',
        'created_asc': 'created_at ASC, id ASC',
        'name_asc': 'name COLLATE NOCASE ASC, id DESC',
        'name_desc': 'name COLLATE NOCASE DESC, id DESC',
    }
    order_sql = sort_map.get(sort_by, sort_map['created_desc'])
    conn = get_db()
    c = conn.cursor()
    conditions = ['is_deleted=0']
    params = []
    if q:
        conditions.append('(name LIKE ? OR id_card LIKE ? OR phone LIKE ?)')
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%'])
    if status == 'deleted':
        conditions = ['is_deleted=1']
    elif status == 'active':
        conditions.append('is_deleted=0')
    if date_from:
        conditions.append('date(created_at) >= date(?)')
        params.append(date_from)
    if date_to:
        conditions.append('date(created_at) <= date(?)')
        params.append(date_to)
    where_sql = ' AND '.join(conditions)
    c.execute(f'SELECT COUNT(*) as n FROM customers WHERE {where_sql}', params)
    total = c.fetchone()['n']
    c.execute(f"SELECT c.* FROM customers c WHERE {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?", params + [page_size, offset])
    rows = row_list(c.fetchall())
    rows = [hydrate_customer_age(row) for row in rows]
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


@app.route('/api/customers/history-view', methods=['GET'])
def api_customers_history_view():
    q = (request.args.get('search', '') or '').strip()
    page, page_size, offset = parse_list_params()
    conn = get_db()
    c = conn.cursor()
    where_sql = '''
        c.is_deleted=0
        AND EXISTS (SELECT 1 FROM health_assessments h WHERE h.customer_id = c.id)
    '''
    params = []
    if q:
        where_sql += ' AND (c.name LIKE ? OR c.phone LIKE ? OR c.id_card LIKE ?)'
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%'])
    c.execute(f'SELECT COUNT(*) as n FROM customers c WHERE {where_sql}', params)
    total = c.fetchone()['n']
    c.execute(
        f'''
        SELECT c.id, c.name, c.age, c.birth_date, c.identity_type, c.phone, c.created_at
        FROM customers c
        WHERE {where_sql}
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT ? OFFSET ?
        ''',
        params + [page_size, offset]
    )
    rows = row_list(c.fetchall())
    rows = [hydrate_customer_age(row) for row in rows]
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


@app.route('/api/customers/<int:cid>', methods=['GET'])
def api_customer_get(cid):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM customers WHERE id = ? AND is_deleted=0', (cid,))
    row = c.fetchone()
    if not row:
        conn.close()
        return error_response('客户不存在', 404, 'NOT_FOUND')
    cust = dict(row)
    hydrate_customer_age(cust)
    c.execute(
        'SELECT a.*, e.name as equipment_name FROM appointments a LEFT JOIN equipment e ON a.equipment_id=e.id WHERE a.customer_id=? ORDER BY a.appointment_date DESC, a.start_time DESC',
        (cid,)
    )
    cust['appointments'] = row_list(c.fetchall())
    cust['usage_records'] = []
    c.execute('SELECT * FROM health_records WHERE customer_id=? ORDER BY record_date DESC', (cid,))
    cust['health_records'] = row_list(c.fetchall())
    c.execute('SELECT * FROM visit_checkins WHERE customer_id=? ORDER BY checkin_time DESC', (cid,))
    cust['visit_checkins'] = row_list(c.fetchall())
    conn.close()
    return success_response(cust)


@app.route('/api/customers', methods=['POST'])
def api_customer_create():
    d = request.json or {}
    customer_error = validate_customer_payload(d)
    if customer_error:
        return error_response(customer_error)
    identity_type = d.get('identity_type')
    if isinstance(identity_type, list):
        identity_type = '、'.join([str(x).strip() for x in identity_type if str(x).strip()])
    else:
        identity_type = str(identity_type or '').strip()
    conn = get_db()
    c = conn.cursor()
    try:
        age = calculate_age_by_birth_year(d.get('birth_date'))
        ts = now_local_str()
        c.execute('''
            INSERT INTO customers (name, id_card, phone, email, address, gender, age, birth_date, identity_type, military_rank, record_creator, medical_history, allergies, diet_habits, chronic_diseases, health_status, therapy_contraindications, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            d.get('name'), (str(d.get('id_card') or '').strip().upper() or None), d.get('phone'), d.get('email'), d.get('address'),
            d.get('gender'), age, d.get('birth_date'), identity_type, d.get('military_rank'), d.get('record_creator'),
            d.get('medical_history'), d.get('allergies'), d.get('diet_habits'), d.get('chronic_diseases'),
            d.get('health_status'), d.get('therapy_contraindications'), ts, ts
        ))
        conn.commit()
        id = c.lastrowid
        conn.close()
        audit_log('创建客户', 'customers', id, d.get('name') or '')
        return success_response({'id': id}, '客户创建成功', 201)
    except sqlite3.IntegrityError:
        conn.close()
        return error_response('身份证号已存在')


@app.route('/api/customers/<int:cid>', methods=['PUT'])
def api_customer_update(cid):
    d = request.json or {}
    customer_error = validate_customer_payload(d)
    if customer_error:
        return error_response(customer_error)
    identity_type = d.get('identity_type')
    if isinstance(identity_type, list):
        identity_type = '、'.join([str(x).strip() for x in identity_type if str(x).strip()])
    else:
        identity_type = str(identity_type or '').strip()
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM customers WHERE id=? AND is_deleted=0', (cid,))
    if not c.fetchone():
        conn.close()
        return error_response('客户不存在', 404, 'NOT_FOUND')
    c.execute('''
        UPDATE customers SET name=?, id_card=?, phone=?, email=?, address=?, gender=?, age=?, birth_date=?, identity_type=?, military_rank=?, record_creator=?, medical_history=?, allergies=?, diet_habits=?, chronic_diseases=?, health_status=?, therapy_contraindications=?, updated_at=? WHERE id=?
    ''', (
        d.get('name'), (str(d.get('id_card') or '').strip().upper() or None), d.get('phone'), d.get('email'), d.get('address'),
        d.get('gender'), calculate_age_by_birth_year(d.get('birth_date')), d.get('birth_date'), identity_type, d.get('military_rank'), d.get('record_creator'),
        d.get('medical_history'), d.get('allergies'), d.get('diet_habits'), d.get('chronic_diseases'),
        d.get('health_status'), d.get('therapy_contraindications'), now_local_str(), cid
    ))
    conn.commit()
    conn.close()
    audit_log('修改客户', 'customers', cid, d.get('name') or '')
    return success_response({'id': cid}, '更新成功')


@app.route('/api/customers/<int:cid>', methods=['DELETE'])
def api_customer_delete(cid):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM customers WHERE id=? AND is_deleted=0', (cid,))
    if not c.fetchone():
        conn.close()
        return error_response('客户不存在', 404, 'NOT_FOUND')

    c.execute("UPDATE customers SET is_deleted=1, updated_at=? WHERE id=?", (now_local_str(), cid))
    conn.commit()
    conn.close()
    audit_log('删除客户', 'customers', cid, '软删除客户')
    return success_response({'id': cid}, '已删除')


# ========== 健康档案 ==========
@app.route('/api/health-records', methods=['GET'])
def api_health_records_list():
    customer_id = request.args.get('customer_id', type=int)
    conn = get_db()
    c = conn.cursor()
    if customer_id:
        c.execute('SELECT h.*, c.name as customer_name FROM health_records h JOIN customers c ON h.customer_id=c.id WHERE h.customer_id=? ORDER BY h.record_date DESC', (customer_id,))
    else:
        c.execute('SELECT h.*, c.name as customer_name FROM health_records h JOIN customers c ON h.customer_id=c.id ORDER BY h.record_date DESC')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/health-records', methods=['POST'])
def api_health_record_create():
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO health_records (customer_id, record_date, height_cm, weight_kg, blood_pressure, symptoms, diagnosis, notes)
        VALUES (?,?,?,?,?,?,?,?)
    ''', (
        d.get('customer_id'), d.get('record_date'), d.get('height_cm'), d.get('weight_kg'),
        d.get('blood_pressure'), d.get('symptoms'), d.get('diagnosis'), d.get('notes')
    ))
    conn.commit()
    id = c.lastrowid
    conn.close()
    return jsonify({'id': id, 'message': '健康档案已添加'}), 201


# ========== 来访签到 ==========
@app.route('/api/visit-checkins', methods=['GET'])
def api_visit_checkins_list():
    customer_id = request.args.get('customer_id', type=int)
    conn = get_db()
    c = conn.cursor()
    if customer_id:
        c.execute('SELECT v.*, c.name as customer_name FROM visit_checkins v JOIN customers c ON v.customer_id=c.id WHERE v.customer_id=? ORDER BY v.checkin_time DESC', (customer_id,))
    else:
        c.execute('SELECT v.*, c.name as customer_name FROM visit_checkins v JOIN customers c ON v.customer_id=c.id ORDER BY v.checkin_time DESC')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/visit-checkins', methods=['POST'])
def api_visit_checkin_create():
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO visit_checkins (customer_id, checkin_time, purpose, notes)
        VALUES (?,?,?,?)
    ''', (d.get('customer_id'), d.get('checkin_time') or now_local().strftime('%Y-%m-%d %H:%M'), d.get('purpose'), d.get('notes')))
    conn.commit()
    id = c.lastrowid
    conn.close()
    return jsonify({'id': id, 'message': '签到成功'}), 201


# ========== 设备 ==========
@app.route('/api/equipment', methods=['GET'])
def api_equipment_list():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM equipment ORDER BY name')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/equipment', methods=['POST'])
def api_equipment_create():
    d = request.json or {}
    name = str(d.get('name') or '').strip()
    if not name:
        return error_response('设备名称为必填项')
    status = str(d.get('status') or 'available').strip()
    if status not in {'available', 'maintenance'}:
        return error_response('设备状态不合法')
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO equipment (name, type, model, location, status, description)
        VALUES (?,?,?,?,?,?)
        ''',
        (
            name,
            d.get('type') or '专用设备',
            d.get('model'),
            d.get('location'),
            status,
            d.get('description'),
        ),
    )
    conn.commit()
    equipment_id = c.lastrowid
    conn.close()
    return success_response({'id': equipment_id}, '设备创建成功', 201)


@app.route('/api/equipment/<int:eid>', methods=['PUT'])
def api_equipment_update(eid):
    d = request.json or {}
    name = str(d.get('name') or '').strip()
    if not name:
        return error_response('设备名称为必填项')
    status = str(d.get('status') or 'available').strip()
    if status not in {'available', 'maintenance'}:
        return error_response('设备状态不合法')
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM equipment WHERE id=?', (eid,))
    if not c.fetchone():
        conn.close()
        return error_response('设备不存在', 404, 'NOT_FOUND')
    c.execute(
        '''
        UPDATE equipment
        SET name=?, type=?, model=?, location=?, status=?, description=?
        WHERE id=?
        ''',
        (
            name,
            d.get('type') or '专用设备',
            d.get('model'),
            d.get('location'),
            status,
            d.get('description'),
            eid,
        ),
    )
    conn.commit()
    conn.close()
    return success_response({'id': eid}, '设备更新成功')


@app.route('/api/equipment/available', methods=['GET'])
def api_equipment_available():
    date = request.args.get('date')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    if not all([date, start_time, end_time]):
        return jsonify({'error': '缺少 date, start_time, end_time'}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT DISTINCT equipment_id FROM appointments
        WHERE appointment_date=? AND status='scheduled'
        AND ((start_time<=? AND end_time>?) OR (start_time<? AND end_time>=?) OR (start_time>=? AND end_time<=?))
    ''', (date, start_time, start_time, end_time, end_time, start_time, end_time))
    booked = [r['equipment_id'] for r in c.fetchall()]
    if booked:
        ph = ','.join('?' * len(booked))
        c.execute(f"SELECT * FROM equipment WHERE status='available' AND id NOT IN ({ph}) ORDER BY name", booked)
    else:
        c.execute("SELECT * FROM equipment WHERE status='available' ORDER BY name")
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/equipment/availability-summary', methods=['GET'])
def api_equipment_availability_summary():
    date = request.args.get('date')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    if not all([date, start_time, end_time]):
        return jsonify({'error': '缺少 date, start_time, end_time'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name FROM equipment WHERE status='available' ORDER BY name")
    all_equipment = row_list(c.fetchall())
    c.execute('''
        SELECT DISTINCT equipment_id FROM appointments
        WHERE appointment_date=? AND status='scheduled'
        AND ((start_time<=? AND end_time>?) OR (start_time<? AND end_time>=?) OR (start_time>=? AND end_time<=?))
    ''', (date, start_time, start_time, end_time, end_time, start_time, end_time))
    booked_ids = {r['equipment_id'] for r in c.fetchall()}
    conn.close()

    available_equipment = [e for e in all_equipment if e['id'] not in booked_ids]
    return jsonify({
        'date': date,
        'start_time': start_time,
        'end_time': end_time,
        'total_equipment': len(all_equipment),
        'available_count': len(available_equipment),
        'booked_count': len(booked_ids),
        'available_equipment': available_equipment,
    })


# ========== 服务项目与人员 ==========
@app.route('/api/projects', methods=['GET'])
@app.route('/api/service-projects', methods=['GET'])
def api_projects_list():
    scene = request.args.get('scene')
    conn = get_db()
    c = conn.cursor()
    rows = load_projects_with_parallel_strategy(c, enabled_only=False, scene=scene)
    conn.close()
    return jsonify(rows)


@app.route('/api/projects/enabled', methods=['GET'])
@app.route('/api/service-projects/enabled', methods=['GET'])
def api_projects_enabled():
    scene = request.args.get('scene')
    conn = get_db()
    c = conn.cursor()
    rows = load_projects_with_parallel_strategy(c, enabled_only=True, scene=scene)
    conn.close()
    return jsonify(rows)


@app.route('/api/projects', methods=['POST'])
@app.route('/api/service-projects', methods=['POST'])
def api_projects_create():
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO therapy_projects (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
        VALUES (?,?,?,?,?,?,?,?)
    ''', (d.get('name'), d.get('category'), d.get('duration_minutes'), d.get('need_equipment', 0), d.get('equipment_type'), d.get('price'), d.get('status', 'enabled'), d.get('description')))
    conn.commit()
    pid = c.lastrowid
    conn.close()
    return jsonify({'id': pid, 'message': '项目创建成功'}), 201


@app.route('/api/projects/<int:pid>', methods=['PUT'])
@app.route('/api/service-projects/<int:pid>', methods=['PUT'])
def api_projects_update(pid):
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE therapy_projects
        SET name=?, category=?, duration_minutes=?, need_equipment=?, equipment_type=?, price=?, status=?, description=?
        WHERE id=?
    ''', (d.get('name'), d.get('category'), d.get('duration_minutes'), d.get('need_equipment', 0), d.get('equipment_type'), d.get('price'), d.get('status', 'enabled'), d.get('description'), pid))
    conn.commit()
    conn.close()
    return jsonify({'message': '项目更新成功'})


@app.route('/api/staff', methods=['GET'])
def api_staff_list():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM staff ORDER BY id DESC')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/staff/available', methods=['GET'])
def api_staff_available():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM staff WHERE status='available' ORDER BY name")
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/staff', methods=['POST'])
def api_staff_create():
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO staff (name, role, phone, status, notes) VALUES (?,?,?,?,?)',
              (d.get('name'), d.get('role'), d.get('phone'), d.get('status', 'available'), d.get('notes')))
    conn.commit()
    sid = c.lastrowid
    conn.close()
    return jsonify({'id': sid, 'message': '服务人员创建成功'}), 201


@app.route('/api/staff/<int:sid>', methods=['PUT'])
def api_staff_update(sid):
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE staff SET name=?, role=?, phone=?, status=?, notes=? WHERE id=?',
              (d.get('name'), d.get('role'), d.get('phone'), d.get('status', 'available'), d.get('notes'), sid))
    conn.commit()
    conn.close()
    return jsonify({'message': '服务人员更新成功'})


@app.route('/api/device-management/appointment-items', methods=['GET'])
def api_device_management_appointment_items():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT pem.id,
               pem.project_name,
               pem.equipment_name,
               COALESCE(e.status, 'available') AS equipment_status,
               COALESCE(e.location, '') AS equipment_location,
               COALESCE(e.description, '') AS equipment_description,
               COALESCE(pem.created_at, e.created_at) AS created_at
          FROM project_equipment_mapping pem
          LEFT JOIN equipment e ON e.name = pem.equipment_name
         WHERE pem.status='enabled'
         ORDER BY pem.id DESC
        '''
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(rows)


@app.route('/api/device-management/appointment-items', methods=['POST'])
def api_device_management_appointment_items_create():
    d = request.json or {}
    project_name = str(d.get('project_name') or '').strip()
    equipment_name = str(d.get('equipment_name') or '').strip()
    equipment_status = str(d.get('equipment_status') or 'available').strip()
    equipment_location = str(d.get('equipment_location') or '').strip()
    equipment_description = str(d.get('equipment_description') or '').strip()
    if not project_name or not equipment_name:
        return error_response('项目名称和设备名称为必填项')
    if equipment_status not in {'available', 'maintenance'}:
        return error_response('设备状态不合法')

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM therapy_projects WHERE name=?", (project_name,))
    project_row = c.fetchone()
    if not project_row:
        c.execute(
            '''
            INSERT INTO therapy_projects
            (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
            VALUES (?,?,?,?,?,?,?,?)
            ''',
            (project_name, '理疗', 30, 1, '专用设备', 0, 'enabled', f'{project_name}服务项目'),
        )
        project_id = c.lastrowid
    else:
        project_id = project_row['id']
        c.execute(
            '''
            UPDATE therapy_projects
               SET need_equipment=1, equipment_type='专用设备', status='enabled'
             WHERE id=?
            ''',
            (project_id,),
        )
    c.execute('''
        INSERT OR IGNORE INTO project_rules (project_name, allow_home, project_category, status)
        VALUES (?,?,?,?)
    ''', (project_name, 0, '理疗', 'enabled'))

    c.execute("SELECT id FROM equipment WHERE name=?", (equipment_name,))
    equipment_row = c.fetchone()
    if equipment_row:
        c.execute(
            "UPDATE equipment SET status=?, type='专用设备', location=?, description=? WHERE id=?",
            (equipment_status, equipment_location, equipment_description, equipment_row['id']),
        )
    else:
        c.execute(
            '''
            INSERT INTO equipment (name, type, model, location, status, description)
            VALUES (?,?,?,?,?,?)
            ''',
            (
                equipment_name,
                '专用设备',
                '',
                equipment_location,
                equipment_status,
                equipment_description or f'{project_name}预约设备',
            ),
        )
    c.execute(
        '''
        INSERT OR IGNORE INTO project_equipment_mapping (project_name, equipment_name, status)
        VALUES (?,?,?)
        ''',
        (project_name, equipment_name, 'enabled'),
    )
    conn.commit()
    conn.close()
    return success_response({'project_id': project_id}, '预约服务项目已保存', 201)


@app.route('/api/device-management/appointment-items/<int:item_id>', methods=['PUT'])
def api_device_management_appointment_items_update(item_id):
    d = request.json or {}
    project_name = str(d.get('project_name') or '').strip()
    equipment_name = str(d.get('equipment_name') or '').strip()
    equipment_status = str(d.get('equipment_status') or 'available').strip()
    equipment_location = str(d.get('equipment_location') or '').strip()
    equipment_description = str(d.get('equipment_description') or '').strip()
    if not project_name or not equipment_name:
        return error_response('项目名称和设备名称为必填项')
    if equipment_status not in {'available', 'maintenance'}:
        return error_response('设备状态不合法')

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM project_equipment_mapping WHERE id=?', (item_id,))
    old_mapping = c.fetchone()
    if not old_mapping:
        conn.close()
        return error_response('记录不存在', 404, 'NOT_FOUND')

    c.execute("SELECT id FROM therapy_projects WHERE name=?", (project_name,))
    if not c.fetchone():
        c.execute(
            '''
            INSERT INTO therapy_projects
            (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
            VALUES (?,?,?,?,?,?,?,?)
            ''',
            (project_name, '理疗', 30, 1, '专用设备', 0, 'enabled', f'{project_name}服务项目'),
        )
    c.execute(
        '''
        UPDATE therapy_projects
           SET need_equipment=1, equipment_type='专用设备', status='enabled'
         WHERE name=?
        ''',
        (project_name,),
    )
    c.execute('''
        INSERT OR IGNORE INTO project_rules (project_name, allow_home, project_category, status)
        VALUES (?,?,?,?)
    ''', (project_name, 0, '理疗', 'enabled'))

    c.execute("SELECT id FROM equipment WHERE name=?", (old_mapping['equipment_name'],))
    old_equipment = c.fetchone()
    if old_equipment:
        c.execute(
            "UPDATE equipment SET name=?, status=?, type='专用设备', location=?, description=? WHERE id=?",
            (equipment_name, equipment_status, equipment_location, equipment_description, old_equipment['id']),
        )
    else:
        c.execute(
            '''
            INSERT INTO equipment (name, type, model, location, status, description)
            VALUES (?,?,?,?,?,?)
            ''',
            (
                equipment_name,
                '专用设备',
                '',
                equipment_location,
                equipment_status,
                equipment_description or f'{project_name}预约设备',
            ),
        )

    c.execute(
        '''
        UPDATE project_equipment_mapping
           SET project_name=?, equipment_name=?, status='enabled', updated_at=?
         WHERE id=?
        ''',
        (project_name, equipment_name, now_local_str(), item_id),
    )
    conn.commit()
    conn.close()
    return success_response({'id': item_id}, '预约服务项目已更新')


@app.route('/api/device-management/home-items', methods=['GET'])
def api_device_management_home_items():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT psm.id,
               psm.project_name,
               s.name AS staff_name,
               psm.created_at
          FROM project_staff_mapping psm
          LEFT JOIN staff s ON s.id = psm.staff_id
         WHERE psm.status='enabled'
         ORDER BY psm.id DESC
        '''
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(rows)


@app.route('/api/device-management/home-items', methods=['POST'])
def api_device_management_home_items_create():
    d = request.json or {}
    project_name = str(d.get('project_name') or '').strip()
    staff_name = str(d.get('staff_name') or '').strip()
    if not project_name or not staff_name:
        return error_response('项目名称和项目服务人员为必填项')
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM therapy_projects WHERE name=?", (project_name,))
    if not c.fetchone():
        c.execute(
            '''
            INSERT INTO therapy_projects
            (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
            VALUES (?,?,?,?,?,?,?,?)
            ''',
            (project_name, '上门', 30, 0, None, 0, 'enabled', f'{project_name}上门项目'),
        )
    c.execute('''
        INSERT OR REPLACE INTO project_rules (project_name, allow_home, project_category, status, updated_at)
        VALUES (?,?,?,?,?)
    ''', (project_name, 1, '上门', 'enabled', now_local_str()))

    c.execute("SELECT id FROM staff WHERE name=?", (staff_name,))
    staff = c.fetchone()
    if staff:
        staff_id = staff['id']
        c.execute("UPDATE staff SET status='available' WHERE id=?", (staff_id,))
    else:
        c.execute(
            "INSERT INTO staff (name, role, phone, status, notes) VALUES (?,?,?,?,?)",
            (staff_name, '上门服务人员', '', 'available', ''),
        )
        staff_id = c.lastrowid
    c.execute(
        '''
        INSERT OR IGNORE INTO project_staff_mapping (project_name, staff_id, status)
        VALUES (?,?,?)
        ''',
        (project_name, staff_id, 'enabled'),
    )
    conn.commit()
    conn.close()
    return success_response({'staff_id': staff_id}, '上门项目已保存', 201)


@app.route('/api/device-management/home-items/<int:item_id>', methods=['PUT'])
def api_device_management_home_items_update(item_id):
    d = request.json or {}
    project_name = str(d.get('project_name') or '').strip()
    staff_name = str(d.get('staff_name') or '').strip()
    if not project_name or not staff_name:
        return error_response('项目名称和项目服务人员为必填项')
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM project_staff_mapping WHERE id=?', (item_id,))
    old = c.fetchone()
    if not old:
        conn.close()
        return error_response('记录不存在', 404, 'NOT_FOUND')
    c.execute("SELECT id FROM staff WHERE name=?", (staff_name,))
    staff = c.fetchone()
    if staff:
        staff_id = staff['id']
    else:
        c.execute(
            "INSERT INTO staff (name, role, phone, status, notes) VALUES (?,?,?,?,?)",
            (staff_name, '上门服务人员', '', 'available', ''),
        )
        staff_id = c.lastrowid

    c.execute(
        '''
        UPDATE project_staff_mapping
           SET project_name=?, staff_id=?, status='enabled', updated_at=?
         WHERE id=?
        ''',
        (project_name, staff_id, now_local_str(), item_id),
    )
    c.execute(
        '''
        INSERT OR IGNORE INTO therapy_projects
        (name, category, duration_minutes, need_equipment, equipment_type, price, status, description)
        VALUES (?,?,?,?,?,?,?,?)
        ''',
        (project_name, '上门', 30, 0, None, 0, 'enabled', f'{project_name}上门项目'),
    )
    c.execute('''
        INSERT OR REPLACE INTO project_rules (project_name, allow_home, project_category, status, updated_at)
        VALUES (?,?,?,?,?)
    ''', (project_name, 1, '上门', 'enabled', now_local_str()))
    conn.commit()
    conn.close()
    return success_response({'id': item_id}, '上门项目已更新')


# ========== 健康评估 ==========
@app.route('/api/health-assessments', methods=['GET'])
def api_health_assessments_list():
    customer_id = request.args.get('customer_id', type=int)
    search = (request.args.get('search', '') or '').strip()
    date_from = (request.args.get('date_from', '') or '').strip()
    date_to = (request.args.get('date_to', '') or '').strip()
    sort_by = (request.args.get('sort_by', '') or 'date_desc').strip()
    page, page_size, offset = parse_list_params()
    sort_map = {
        'date_desc': 'h.assessment_date DESC, h.id DESC',
        'date_asc': 'h.assessment_date ASC, h.id ASC',
        'name_asc': 'c.name COLLATE NOCASE ASC, h.assessment_date DESC, h.id DESC',
    }
    order_sql = sort_map.get(sort_by, sort_map['date_desc'])
    conn = get_db()
    c = conn.cursor()
    sql = 'FROM health_assessments h JOIN customers c ON h.customer_id=c.id WHERE 1=1'
    params = []
    if customer_id:
        sql += ' AND h.customer_id=?'
        params.append(customer_id)
    if search:
        sql += ' AND (c.name LIKE ? OR c.phone LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    if date_from:
        sql += ' AND date(h.assessment_date) >= date(?)'
        params.append(date_from)
    if date_to:
        sql += ' AND date(h.assessment_date) <= date(?)'
        params.append(date_to)
    c.execute(f'SELECT COUNT(*) as n {sql}', params)
    total = c.fetchone()['n']
    c.execute(f'SELECT h.*, c.name as customer_name {sql} ORDER BY {order_sql} LIMIT ? OFFSET ?', params + [page_size, offset])
    rows = row_list(c.fetchall())
    conn.close()
    for r in rows:
        r['exercise_methods'] = decode_multi_value(r.get('exercise_methods'))
        r['health_needs'] = decode_multi_value(r.get('health_needs'))
    return success_response(paginate_result(rows, total, page, page_size))


@app.route('/api/health-assessments', methods=['POST'])
def api_health_assessment_create():
    d = request.json or {}
    invalid_msg = validate_health_assessment_enums(d)
    if invalid_msg:
        return jsonify({'error': invalid_msg}), 400
    conn = get_db()
    c = conn.cursor()
    customer_id = d.get('customer_id')

    c.execute('''
        INSERT INTO health_assessments (customer_id, assessment_date, assessor, age, height_cm, weight_kg, address, past_medical_history, family_history,
         allergy_history, allergy_details, smoking_status, smoking_years, cigarettes_per_day, drinking_status, drinking_years,
         sleep_quality, sleep_hours, recent_symptoms, recent_symptom_detail, life_impact_issues, blood_pressure_test, blood_lipid_test, blood_sugar_test, chronic_pain, pain_details,
         exercise_methods, health_needs, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        customer_id, d.get('assessment_date'), d.get('assessor'), d.get('age'), d.get('height_cm'), d.get('weight_kg'),
        d.get('address'), d.get('past_medical_history'), d.get('family_history'), d.get('allergy_history'), d.get('allergy_details'),
        d.get('smoking_status'), d.get('smoking_years'), d.get('cigarettes_per_day'), d.get('drinking_status'), d.get('drinking_years'),
        d.get('sleep_quality'), d.get('sleep_hours'), d.get('recent_symptoms'), d.get('recent_symptom_detail'), d.get('life_impact_issues'),
        d.get('blood_pressure_test'), d.get('blood_lipid_test'), d.get('blood_sugar_test'), d.get('chronic_pain'), d.get('pain_details'),
        parse_multi_value(d.get('exercise_methods')), parse_multi_value(d.get('health_needs')), d.get('notes')
    ))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    audit_log('创建健康评估', 'health_assessments', rid, f"customer_id={customer_id}")
    return jsonify({'id': rid, 'message': '健康评估已添加'}), 201


@app.route('/api/health-assessments/<int:hid>', methods=['GET'])
def api_health_assessment_get(hid):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT
            h.*,
            c.name as customer_name,
            c.phone as phone,
            c.id_card as id_card,
            c.gender as gender,
            c.birth_date as birth_date,
            c.identity_type as identity_type,
            c.military_rank as military_rank,
            c.record_creator as record_creator
        FROM health_assessments h
        JOIN customers c ON h.customer_id=c.id
        WHERE h.id=?
        ''',
        (hid,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return jsonify({'error': '记录不存在'}), 404
    data = dict(row)
    data['exercise_methods'] = decode_multi_value(data.get('exercise_methods'))
    data['health_needs'] = decode_multi_value(data.get('health_needs'))
    return jsonify(data)


@app.route('/api/health-assessments/<int:hid>', methods=['PUT'])
def api_health_assessment_update(hid):
    d = request.json or {}
    invalid_msg = validate_health_assessment_enums(d)
    if invalid_msg:
        return jsonify({'error': invalid_msg}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE health_assessments
        SET customer_id=?, assessment_date=?, assessor=?, age=?, height_cm=?, weight_kg=?, address=?, past_medical_history=?, family_history=?,
            allergy_history=?, allergy_details=?, smoking_status=?, smoking_years=?, cigarettes_per_day=?, drinking_status=?, drinking_years=?,
            sleep_quality=?, sleep_hours=?, recent_symptoms=?, recent_symptom_detail=?, life_impact_issues=?, blood_pressure_test=?, blood_lipid_test=?,
            blood_sugar_test=?, chronic_pain=?, pain_details=?, exercise_methods=?, health_needs=?, notes=?
        WHERE id=?
    ''', (
        d.get('customer_id'), d.get('assessment_date'), d.get('assessor'), d.get('age'), d.get('height_cm'), d.get('weight_kg'),
        d.get('address'), d.get('past_medical_history'), d.get('family_history'), d.get('allergy_history'), d.get('allergy_details'),
        d.get('smoking_status'), d.get('smoking_years'), d.get('cigarettes_per_day'), d.get('drinking_status'), d.get('drinking_years'),
        d.get('sleep_quality'), d.get('sleep_hours'), d.get('recent_symptoms'), d.get('recent_symptom_detail'), d.get('life_impact_issues'),
        d.get('blood_pressure_test'), d.get('blood_lipid_test'), d.get('blood_sugar_test'), d.get('chronic_pain'), d.get('pain_details'),
        parse_multi_value(d.get('exercise_methods')), parse_multi_value(d.get('health_needs')), d.get('notes'), hid
    ))
    conn.commit()
    conn.close()
    audit_log('修改健康评估', 'health_assessments', hid, f"customer_id={d.get('customer_id')}")
    return jsonify({'message': '健康评估更新成功'})


@app.route('/api/health-assessments/<int:hid>', methods=['DELETE'])
def api_health_assessment_delete(hid):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT customer_id FROM health_assessments WHERE id=?', (hid,))
    row = c.fetchone()
    c.execute('DELETE FROM health_assessments WHERE id=?', (hid,))
    conn.commit()
    conn.close()
    customer_id = row['customer_id'] if row else ''
    audit_log('删除健康评估', 'health_assessments', hid, f"customer_id={customer_id}")
    return jsonify({'message': '已删除'})


# ========== 健康改善追踪 ==========
@app.route('/api/improvement-records/meta', methods=['GET'])
def api_improvement_records_meta():
    conn = get_db()
    c = conn.cursor()
    projects = get_improvement_service_projects(c)
    conn.close()
    return success_response({
        'service_projects': projects,
        'improvement_status_options': IMPROVEMENT_STATUS_OPTIONS,
        'followup_method_options': FOLLOWUP_METHOD_OPTIONS,
        'followup_time_options': FOLLOWUP_PRESET_OPTIONS,
    })


@app.route('/api/improvement-records', methods=['GET'])
def api_improvement_records_by_customer():
    customer_id = request.args.get('customer_id', type=int)
    if not customer_id:
        return error_response('customer_id 必填')
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT r.*, c.name as customer_name
        FROM service_improvement_records r
        JOIN customers c ON r.customer_id=c.id
        WHERE r.customer_id=?
        ORDER BY r.service_time DESC, r.id DESC
        ''',
        (customer_id,),
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(rows)


@app.route('/api/improvement-records/all', methods=['GET'])
def api_improvement_records_all():
    page, page_size, offset = parse_list_params(default_page_size=10, max_page_size=100)
    conn = get_db()
    c = conn.cursor()
    sql = '''
        FROM service_improvement_records r
        JOIN customers c ON r.customer_id=c.id
        WHERE 1=1
    '''
    params = []
    customer_keyword = (request.args.get('customer_keyword') or request.args.get('customer_name') or '').strip()
    service_project = (request.args.get('service_project') or '').strip()
    improvement_status = (request.args.get('improvement_status') or '').strip()
    service_start = (request.args.get('service_start') or '').strip()
    service_end = (request.args.get('service_end') or '').strip()
    customer_id = request.args.get('customer_id', type=int)

    if customer_id:
        sql += ' AND r.customer_id=?'
        params.append(customer_id)
    if customer_keyword:
        sql += ' AND (c.name LIKE ? OR c.phone LIKE ?)'
        keyword_like = f'%{customer_keyword}%'
        params.extend([keyword_like, keyword_like])
    if service_project:
        sql += ' AND r.service_project=?'
        params.append(service_project)
    if improvement_status:
        sql += ' AND r.improvement_status=?'
        params.append(improvement_status)
    if service_start:
        sql += ' AND date(substr(r.service_time, 1, 10)) >= date(?)'
        params.append(service_start)
    if service_end:
        sql += ' AND date(substr(r.service_time, 1, 10)) <= date(?)'
        params.append(service_end)
    c.execute(f'SELECT COUNT(1) as cnt {sql}', params)
    count_row = c.fetchone()
    total = int(count_row['cnt']) if count_row and count_row['cnt'] is not None else 0
    c.execute(
        f'''
        SELECT r.*, c.name as customer_name, c.phone as customer_phone
        {sql}
        ORDER BY r.service_time DESC, r.id DESC
        LIMIT ? OFFSET ?
        '''
        ,
        params + [page_size, offset],
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


@app.route('/api/improvement-records/pending-fill', methods=['GET'])
def api_improvement_records_pending_fill():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT
            'appointments' as service_type,
            a.id as service_id,
            c.name as customer_name,
            c.phone as customer_phone,
            COALESCE(p.name, '') as service_project,
            (a.appointment_date || ' ' || a.start_time) as service_time,
            a.appointment_date,
            a.start_time
        FROM appointments a
        JOIN customers c ON a.customer_id=c.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE LOWER(COALESCE(a.status, ''))='scheduled'
          AND LOWER(COALESCE(a.checkin_status, ''))='checked_in'
          AND NOT EXISTS (
                SELECT 1
                FROM service_improvement_records r
                WHERE r.service_type='appointments'
                  AND r.service_id=a.id
          )
        UNION ALL
        SELECT
            'home_appointments' as service_type,
            h.id as service_id,
            c.name as customer_name,
            c.phone as customer_phone,
            COALESCE(p.name, h.service_project, '') as service_project,
            (h.appointment_date || ' ' || h.start_time) as service_time,
            h.appointment_date,
            h.start_time
        FROM home_appointments h
        JOIN customers c ON h.customer_id=c.id
        LEFT JOIN therapy_projects p ON h.project_id=p.id
        WHERE LOWER(COALESCE(h.status, ''))='scheduled'
          AND LOWER(COALESCE(h.checkin_status, ''))='checked_in'
          AND NOT EXISTS (
                SELECT 1
                FROM service_improvement_records r
                WHERE r.service_type='home_appointments'
                  AND r.service_id=h.id
          )
        ORDER BY appointment_date DESC, start_time DESC, service_id DESC
        '''
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(rows)


@app.route('/api/improvement-records/<int:rid>', methods=['GET'])
def api_improvement_record_get(rid):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT r.*, c.name as customer_name, c.phone as customer_phone, c.health_status
        FROM service_improvement_records r
        JOIN customers c ON r.customer_id=c.id
        WHERE r.id=?
        ''',
        (rid,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return error_response('记录不存在', 404, 'NOT_FOUND')
    return success_response(dict(row))


@app.route('/api/improvement-records', methods=['POST'])
def api_improvement_record_create():
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    err = validate_improvement_payload(d, c)
    if err:
        conn.close()
        return error_response(err)
    now_ts = now_local_str()
    c.execute('SELECT id FROM customers WHERE id=? AND is_deleted=0', (d.get('customer_id'),))
    if not c.fetchone():
        conn.close()
        return error_response('客户不存在')
    try:
        c.execute(
            '''
            INSERT INTO service_improvement_records
            (service_id, service_type, customer_id, service_time, service_project, pre_service_status, service_content,
             post_service_evaluation, improvement_status, followup_time, followup_date, followup_method, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                d.get('service_id'),
                d.get('service_type') or 'appointments',
                d.get('customer_id'),
                d.get('service_time'),
                d.get('service_project'),
                d.get('pre_service_status'),
                d.get('service_content'),
                d.get('post_service_evaluation'),
                d.get('improvement_status'),
                d.get('followup_time'),
                d.get('followup_date'),
                d.get('followup_method'),
                now_ts,
            ),
        )
        rid = c.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return error_response('保存失败：关联数据不存在或已失效')
    conn.close()
    audit_log('新增改善记录', 'service_improvement_records', rid, f"customer_id={d.get('customer_id')}")
    return success_response({'id': rid}, '改善记录已添加', 201)


@app.route('/api/improvement-records/<int:rid>', methods=['PUT'])
def api_improvement_record_update(rid):
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    err = validate_improvement_payload(d, c)
    if err:
        conn.close()
        return error_response(err)
    now_ts = now_local_str()
    c.execute('SELECT id FROM service_improvement_records WHERE id=?', (rid,))
    if not c.fetchone():
        conn.close()
        return error_response('记录不存在', 404, 'NOT_FOUND')
    c.execute('SELECT id FROM customers WHERE id=? AND is_deleted=0', (d.get('customer_id'),))
    if not c.fetchone():
        conn.close()
        return error_response('客户不存在')
    try:
        c.execute(
            '''
            UPDATE service_improvement_records
            SET service_id=?, service_type=?, customer_id=?, service_time=?, service_project=?, pre_service_status=?, service_content=?,
                post_service_evaluation=?, improvement_status=?, followup_time=?, followup_date=?, followup_method=?,
                updated_at=?
            WHERE id=?
            ''',
            (
                d.get('service_id'),
                d.get('service_type') or 'appointments',
                d.get('customer_id'),
                d.get('service_time'),
                d.get('service_project'),
                d.get('pre_service_status'),
                d.get('service_content'),
                d.get('post_service_evaluation'),
                d.get('improvement_status'),
                d.get('followup_time'),
                d.get('followup_date'),
                d.get('followup_method'),
                now_ts,
                rid,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return error_response('保存失败：关联数据不存在或已失效')
    conn.close()
    audit_log('修改改善记录', 'service_improvement_records', rid, f"customer_id={d.get('customer_id')}")
    return success_response({'id': rid}, '改善记录已更新')


@app.route('/api/improvement-records/<int:rid>', methods=['DELETE'])
def api_improvement_record_delete(rid):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM service_improvement_records WHERE id=?', (rid,))
    if not c.fetchone():
        conn.close()
        return error_response('记录不存在', 404, 'NOT_FOUND')
    c.execute('SELECT file_path FROM improvement_record_files WHERE improvement_record_id=?', (rid,))
    attached_paths = [str(row['file_path'] or '').strip() for row in c.fetchall() if str(row['file_path'] or '').strip()]
    try:
        c.execute('DELETE FROM improvement_record_files WHERE improvement_record_id=?', (rid,))
        c.execute('DELETE FROM service_improvement_records WHERE id=?', (rid,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return error_response('删除失败：该记录存在关联数据，无法删除')
    conn.close()
    for rel_path in attached_paths:
        abs_path = os.path.join(BASE_DIR, rel_path)
        if os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
            except OSError:
                logging.exception('删除理疗附件失败: %s', abs_path)
    audit_log('删除改善记录', 'service_improvement_records', rid, '')
    return success_response({}, '已删除')


@app.route('/api/improvement-records/<int:rid>/files', methods=['POST'])
def api_improvement_record_file_upload(rid):
    uploaded_file = request.files.get('file')
    if uploaded_file is None:
        return error_response('请先选择要上传的文件')
    original_name = str(uploaded_file.filename or '').strip()
    if not original_name:
        return error_response('文件名不能为空')
    ext = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''
    if ext not in ALLOWED_IMPROVEMENT_FILE_EXTENSIONS:
        return error_response('文件扩展名不合法，仅支持 pdf/png/jpg/jpeg')
    mimetype = str(uploaded_file.mimetype or '').lower().strip()
    allowed_mime_types = ALLOWED_IMPROVEMENT_MIME_TYPES.get(ext, set())
    if mimetype not in allowed_mime_types:
        return error_response(
            f'文件 MIME type 不合法，当前为 {mimetype or "未知"}，仅支持 pdf/png/jpg/jpeg',
            400,
            'INVALID_FILE_TYPE',
        )

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, customer_id FROM service_improvement_records WHERE id=?', (rid,))
    record = c.fetchone()
    if not record:
        conn.close()
        return error_response('理疗记录不存在，请先保存理疗记录', 404, 'NOT_FOUND')
    customer_id = int(record['customer_id'])

    c.execute('SELECT name, phone FROM customers WHERE id=? AND is_deleted=0', (customer_id,))
    customer = c.fetchone()
    if not customer:
        conn.close()
        return error_response('关联客户不存在', 404, 'NOT_FOUND')

    folder_name = get_customer_privacy_folder(customer['name'], customer['phone'], customer_id)
    target_dir = os.path.join(LOCAL_FILE_UPLOAD_ROOT, folder_name)
    os.makedirs(target_dir, exist_ok=True)

    safe_base_name = secure_filename(os.path.splitext(original_name)[0]) or 'record_file'
    timestamp = now_local().strftime('%Y%m%d_%H%M%S')
    save_filename = f'{timestamp}_{safe_base_name}.{ext}'
    absolute_path = os.path.join(target_dir, save_filename)
    uploaded_file.save(absolute_path)
    file_size = os.path.getsize(absolute_path)
    relative_path = os.path.relpath(absolute_path, BASE_DIR).replace('\\', '/')

    c.execute(
        '''
        INSERT INTO improvement_record_files
        (customer_id, improvement_record_id, file_name, file_ext, file_path, file_size)
        VALUES (?,?,?,?,?,?)
        ''',
        (
            customer_id,
            rid,
            original_name,
            ext,
            relative_path,
            file_size,
        ),
    )
    file_id = c.lastrowid
    conn.commit()
    conn.close()
    audit_log('上传理疗附件', 'improvement_record_files', file_id, f'improvement_record_id={rid}')
    return success_response(
        {
            'id': file_id,
            'improvement_record_id': rid,
            'customer_id': customer_id,
            'file_name': original_name,
            'file_ext': ext,
            'file_path': relative_path,
            'file_size': file_size,
        },
        '文件上传成功',
        201,
    )


@app.route('/api/improvement-records/latest', methods=['GET'])
def api_improvement_record_latest():
    customer_id = request.args.get('customer_id', type=int)
    if not customer_id:
        return error_response('customer_id 必填')
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT r.*, c.name as customer_name
        FROM service_improvement_records r
        JOIN customers c ON r.customer_id=c.id
        WHERE r.customer_id=?
        ORDER BY r.service_time DESC, r.id DESC
        LIMIT 1
        ''',
        (customer_id,),
    )
    row = c.fetchone()
    conn.close()
    return success_response(dict(row) if row else {})


@app.route('/api/improvement-records/from-appointment', methods=['GET'])
def api_improvement_record_from_appointment():
    service_id = request.args.get('service_id', type=int)
    service_type = (request.args.get('service_type') or 'appointments').strip()
    if not service_id:
        return error_response('service_id 必填')
    if service_type not in ('appointments', 'home_appointments'):
        return error_response('service_type 不合法')
    conn = get_db()
    c = conn.cursor()
    if service_type == 'home_appointments':
        c.execute(
            '''
            SELECT h.id as service_id, h.customer_id, c.name as customer_name, c.phone as customer_phone,
                   COALESCE(p.name, h.service_project, '') as service_project,
                   h.appointment_date, h.start_time, h.end_time
            FROM home_appointments h
            JOIN customers c ON h.customer_id=c.id
            LEFT JOIN therapy_projects p ON h.project_id=p.id
            WHERE h.id=?
            ''',
            (service_id,),
        )
    else:
        c.execute(
            '''
            SELECT a.id as service_id, a.customer_id, c.name as customer_name, c.phone as customer_phone,
                   COALESCE(p.name, '') as service_project,
                   a.appointment_date, a.start_time, a.end_time
            FROM appointments a
            JOIN customers c ON a.customer_id=c.id
            LEFT JOIN therapy_projects p ON a.project_id=p.id
            WHERE a.id=?
            ''',
            (service_id,),
        )
    appt = c.fetchone()
    if not appt:
        conn.close()
        return error_response('预约记录不存在', 404, 'NOT_FOUND')
    appt_dict = dict(appt)
    summary = get_latest_assessment_summary(c, appt_dict['customer_id'])
    conn.close()
    service_time = f"{appt_dict.get('appointment_date') or ''} {appt_dict.get('start_time') or ''}".strip()
    return success_response({
        'service_id': appt_dict.get('service_id'),
        'service_type': service_type,
        'customer_id': appt_dict.get('customer_id'),
        'customer_name': appt_dict.get('customer_name'),
        'customer_phone': appt_dict.get('customer_phone'),
        'service_project': appt_dict.get('service_project'),
        'service_time': service_time,
        'pre_service_status': summary,
    })


# ========== 预约 ==========
@app.route('/api/appointments', methods=['GET'])
def api_appointments_list():
    sort_by = (request.args.get('sort_by') or 'time_desc').strip()
    status = (request.args.get('status', '') or '').strip().lower()
    search = (request.args.get('search', '') or '').strip()
    date_from = (request.args.get('date_from', '') or '').strip()
    date_to = (request.args.get('date_to', '') or '').strip()
    page, page_size, offset = parse_list_params()
    order_sql = {
        'time_desc': 'a.appointment_date DESC, a.start_time DESC, a.id DESC',
        'time_asc': 'a.appointment_date ASC, a.start_time ASC, a.id ASC',
        'name_asc': 'c.name COLLATE NOCASE ASC, a.appointment_date DESC, a.start_time DESC, a.id DESC',
    }.get(sort_by, 'a.appointment_date DESC, a.start_time DESC, a.id DESC')

    conn = get_db()
    c = conn.cursor()
    base_sql = '''
        FROM appointments a
        JOIN customers c ON a.customer_id=c.id
        LEFT JOIN equipment e ON a.equipment_id=e.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE 1=1
    '''
    params = []
    if status:
        base_sql += ' AND LOWER(COALESCE(a.status, ""))=?'
        params.append(status)
    if search:
        like = f'%{search}%'
        base_sql += ' AND (c.name LIKE ? OR c.phone LIKE ?)'
        params.extend([like, like])
    if date_from:
        base_sql += ' AND date(a.appointment_date) >= date(?)'
        params.append(date_from)
    if date_to:
        base_sql += ' AND date(a.appointment_date) <= date(?)'
        params.append(date_to)
    c.execute(f'SELECT COUNT(*) as n {base_sql}', params)
    total = c.fetchone()['n']
    c.execute(f'''
        SELECT a.*, c.name as customer_name, c.phone as customer_phone, e.name as equipment_name,
               p.name as project_name
        {base_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    ''', params + [page_size, offset])
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


@app.route('/api/appointments', methods=['POST'])
def api_appointment_create():
    d = request.json or {}
    validation_error = validate_appointment_payload(d)
    if validation_error:
        return error_response(validation_error)
    if not is_today_or_future(d.get('appointment_date')):
        return error_response('预约时间仅可选择当天及以后日期')
    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()
    # 前端未传时由后端自动生成，保证单条/多条都具备分组ID
    booking_group_id = str(d.get('booking_group_id') or '').strip() or generate_booking_group_id()
    c.execute('SELECT * FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('项目不存在')
    required_equipment_names = get_project_required_equipment_names(project['name'], c)
    if required_equipment_names and not d.get('equipment_id'):
        conn.close()
        return error_response('该项目需要指定设备')

    if d.get('equipment_id'):
        c.execute('SELECT id, name, status FROM equipment WHERE id=?', (d.get('equipment_id'),))
        equipment = c.fetchone()
        if not equipment:
            conn.close()
            return error_response('设备不存在')
        if equipment['status'] == 'maintenance':
            conn.close()
            return error_response('正在维修，不可预约')
        if equipment['status'] != 'available':
            conn.close()
            return error_response('设备不可用')
        if required_equipment_names and equipment['name'] not in required_equipment_names:
            conn.close()
            return error_response('所选设备与项目不匹配')

    c.execute(f"SELECT COUNT(*) as n FROM appointments WHERE customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
              (d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
    if c.fetchone()['n'] > 0:
        conn.close()
        return error_response('同一客户同一时段不能重复预约')

    if d.get('equipment_id'):
        c.execute(f"SELECT COUNT(*) as n FROM appointments WHERE equipment_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
                  (d.get('equipment_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
        if c.fetchone()['n'] > 0:
            conn.close()
            return error_response('该时段设备已被预约')

    checkin_status = 'none' if str(d.get('status') or 'scheduled').strip().lower() == 'cancelled' else 'pending'
    c.execute('''
        INSERT INTO appointments (
            booking_group_id, customer_id, project_id, equipment_id, staff_id,
            appointment_date, start_time, end_time, status, checkin_status,
            has_companion, notes, updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        booking_group_id, d.get('customer_id'), d.get('project_id'), d.get('equipment_id'), None,
        d.get('appointment_date'), d.get('start_time'), d.get('end_time'), d.get('status', 'scheduled'), checkin_status,
        d.get('has_companion', '无'), d.get('notes'), now_ts,
    ))
    rid = c.lastrowid
    c.execute(
        '''
        SELECT a.*, c.name as customer_name, e.name as equipment_name, p.name as project_name
        FROM appointments a
        LEFT JOIN customers c ON a.customer_id=c.id
        LEFT JOIN equipment e ON a.equipment_id=e.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE a.id=?
        ''',
        (rid,),
    )
    created_record = c.fetchone()
    insert_business_history_log(
        c,
        'appointments',
        rid,
        'create',
        '',
        build_appointment_change_text(dict(created_record) if created_record else {}, 'appointments'),
    )
    conn.commit()
    conn.close()
    audit_log('创建预约', 'appointments', rid, d.get('appointment_date'))
    return success_response({'id': rid, 'booking_group_id': booking_group_id}, '预约成功', 201)


@app.route('/api/appointments/slot-panel', methods=['GET'])
def api_appointments_slot_panel():
    date = request.args.get('date')
    project_id = request.args.get('project_id', type=int)
    exclude_appointment_id = request.args.get('exclude_appointment_id', type=int)
    if not date:
        return error_response('缺少 date')
    if not project_id:
        return error_response('缺少 project_id')

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (project_id,))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('项目不存在', 404, 'NOT_FOUND')

    available_equipment = get_project_available_equipment(project['name'], c)

    slots = generate_time_slots('08:30', '16:00', 15)
    slot_items = []
    for st, et in slots:
        free_equipment = []
        maintenance_equipment = []
        if available_equipment:
            for equipment in available_equipment:
                equipment_status = str(equipment.get('status') or 'available')
                if equipment_status != 'available':
                    maintenance_equipment.append({
                        'id': equipment['id'],
                        'name': equipment['name'],
                        'location': equipment.get('location'),
                        'model': equipment.get('model'),
                        'status': equipment_status,
                    })
                    continue
                c.execute(
                    f"SELECT COUNT(*) as n FROM appointments WHERE appointment_date=? AND status='scheduled' AND equipment_id=? "
                    f"AND (? IS NULL OR id<>?) AND {overlap_condition()}",
                    (date, equipment['id'], exclude_appointment_id, exclude_appointment_id, et, st),
                )
                if c.fetchone()['n'] == 0:
                    free_equipment.append({
                        'id': equipment['id'],
                        'name': equipment['name'],
                        'location': equipment.get('location'),
                        'model': equipment.get('model'),
                        'status': equipment_status,
                    })

        slot_items.append({
            'start_time': st,
            'end_time': et,
            'status': 'available' if free_equipment else ('maintenance' if maintenance_equipment else 'full'),
            'available_equipment_count': len(free_equipment),
            'available_equipment': free_equipment,
            'maintenance_equipment': maintenance_equipment,
        })

    conn.close()
    return success_response({
        'date': date,
        'project_id': project_id,
        'slots': slot_items,
    })


@app.route('/api/appointments/free-slots', methods=['GET'])
def api_appointments_free_slots():
    """兼容旧接口：返回结构与 slot-panel 保持同语义。"""
    panel_resp, status = api_appointments_slot_panel()
    if status != 200:
        return panel_resp, status
    data = panel_resp.get_json().get('data') or {}
    return success_response(data.get('slots', []))


@app.route('/api/appointments/available-options', methods=['GET'])
def api_appointments_available_options():
    date = request.args.get('date')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    project_id = request.args.get('project_id', type=int)
    if not all([date, start_time, end_time, project_id]):
        return error_response('缺少必要参数')
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM therapy_projects WHERE id=?', (project_id,))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('项目不存在', 404, 'NOT_FOUND')
    c.execute(f"SELECT equipment_id FROM appointments WHERE appointment_date=? AND status='scheduled' AND {overlap_condition()} AND equipment_id IS NOT NULL", (date, end_time, start_time))
    busy_eq = [r['equipment_id'] for r in c.fetchall()]
    if busy_eq:
        ph = ','.join('?' * len(busy_eq))
        c.execute(f"SELECT * FROM equipment WHERE status='available' AND id NOT IN ({ph}) ORDER BY name", busy_eq)
    else:
        c.execute("SELECT * FROM equipment WHERE status='available' ORDER BY name")
    avail_equipment = row_list(c.fetchall())
    conn.close()
    return success_response({'project': dict(project), 'available_equipment': avail_equipment})




@app.route('/api/appointments/<int:aid>', methods=['PUT'])
def api_appointment_update(aid):
    d = request.json or {}
    validation_error = validate_appointment_payload(d)
    if validation_error:
        return error_response(validation_error)
    if not is_today_or_future(d.get('appointment_date')):
        return error_response('预约时间仅可选择当天及以后日期')

    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()
    c.execute(
        '''
        SELECT a.*, c.name as customer_name, e.name as equipment_name, p.name as project_name
        FROM appointments a
        LEFT JOIN customers c ON a.customer_id=c.id
        LEFT JOIN equipment e ON a.equipment_id=e.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE a.id=?
        ''',
        (aid,),
    )
    old_row = c.fetchone()
    if not old_row:
        conn.close()
        return error_response('预约记录不存在', 404, 'NOT_FOUND')

    c.execute('SELECT * FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('项目不存在')

    required_equipment_names = get_project_required_equipment_names(project['name'], c)
    if required_equipment_names and not d.get('equipment_id'):
        conn.close()
        return error_response('该项目需要指定设备')

    if d.get('equipment_id'):
        c.execute('SELECT id, name, status FROM equipment WHERE id=?', (d.get('equipment_id'),))
        equipment = c.fetchone()
        if not equipment:
            conn.close()
            return error_response('设备不存在')
        if equipment['status'] == 'maintenance':
            conn.close()
            return error_response('正在维修，不可预约')
        if equipment['status'] != 'available':
            conn.close()
            return error_response('设备不可用')
        if required_equipment_names and equipment['name'] not in required_equipment_names:
            conn.close()
            return error_response('所选设备与项目不匹配')

    c.execute(
        f"SELECT COUNT(*) as n FROM appointments WHERE id<>? AND customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
        (aid, d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')),
    )
    if c.fetchone()['n'] > 0:
        conn.close()
        return error_response('同一客户同一时段不能重复预约')

    if d.get('equipment_id'):
        c.execute(
            f"SELECT COUNT(*) as n FROM appointments WHERE id<>? AND equipment_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
            (aid, d.get('equipment_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')),
        )
        if c.fetchone()['n'] > 0:
            conn.close()
            return error_response('该时段设备已被预约')

    new_status = str(d.get('status', 'scheduled') or 'scheduled').strip().lower()
    old_checkin_status = str(old_row['checkin_status'] or 'pending').strip().lower()
    next_checkin_status = 'none' if new_status == 'cancelled' else ('pending' if old_checkin_status == 'none' else old_checkin_status)

    c.execute(
        '''
        UPDATE appointments
        SET customer_id=?, project_id=?, equipment_id=?, staff_id=?, appointment_date=?, start_time=?, end_time=?, status=?, checkin_status=?, has_companion=?, notes=?, updated_at=?
        WHERE id=?
        ''',
        (
            d.get('customer_id'), d.get('project_id'), d.get('equipment_id'), None,
            d.get('appointment_date'), d.get('start_time'), d.get('end_time'), new_status, next_checkin_status, d.get('has_companion', '无'), d.get('notes'),
            now_ts,
            aid,
        ),
    )
    before_text = build_appointment_change_text(dict(old_row), 'appointments')
    c.execute(
        '''
        SELECT a.*, c.name as customer_name, e.name as equipment_name, p.name as project_name
        FROM appointments a
        LEFT JOIN customers c ON a.customer_id=c.id
        LEFT JOIN equipment e ON a.equipment_id=e.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE a.id=?
        ''',
        (aid,),
    )
    new_row = c.fetchone()
    insert_business_history_log(
        c,
        'appointments',
        aid,
        'update',
        before_text,
        build_appointment_change_text(dict(new_row) if new_row else {}, 'appointments'),
    )
    conn.commit()
    conn.close()
    audit_log('修改预约', 'appointments', aid, d.get('appointment_date'))
    return success_response({'id': aid}, '预约修改成功')

@app.route('/api/appointments/<int:aid>/cancel', methods=['POST'])
def api_appointment_cancel(aid):
    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()
    c.execute(
        '''
        SELECT a.*, c.name as customer_name, e.name as equipment_name, p.name as project_name
        FROM appointments a
        LEFT JOIN customers c ON a.customer_id=c.id
        LEFT JOIN equipment e ON a.equipment_id=e.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        WHERE a.id=?
        ''',
        (aid,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return error_response('预约记录不存在', 404, 'NOT_FOUND')
    if (row['status'] or '').strip().lower() == 'cancelled':
        conn.close()
        return error_response('已经提交过取消预约，请勿再次提交')
    c.execute(
        "UPDATE appointments SET status='cancelled', checkin_status='none', checkin_updated_at=?, checkin_updated_by=?, checkin_updated_ip=?, updated_at=? WHERE id=?",
        (now_ts, session.get('username', 'anonymous'), get_request_ip(), now_ts, aid),
    )
    insert_business_history_log(
        c,
        'appointments',
        aid,
        'cancel',
        build_appointment_change_text(dict(row), 'appointments'),
        '状态:取消预约',
    )
    conn.commit()
    conn.close()
    audit_log('取消预约', 'appointments', aid, '门店预约取消')
    return success_response({'id': aid}, '已取消')


def update_checkin_status(cursor, table_name, module_name, record_id, target_status):
    cursor.execute(f'SELECT * FROM {table_name} WHERE id=?', (record_id,))
    row = cursor.fetchone()
    if not row:
        return None, '预约记录不存在'
    booking_status = str(row['status'] or '').strip().lower()
    current_checkin = str(row['checkin_status'] or 'pending').strip().lower()
    appointment_date = str(row['appointment_date'] or '').strip()

    if booking_status != 'scheduled':
        return None, '仅预约成功状态可操作签到'
    if not is_valid_date(appointment_date):
        return None, '预约日期异常，无法签到'
    now_ts = now_local_str()
    today_text = now_ts[:10]
    if appointment_date != today_text:
        return None, '仅预约当日允许操作签到状态'
    if current_checkin == 'no_show':
        return None, '爽约状态不可修改'
    if current_checkin != 'pending':
        return None, '当前签到状态不可修改'
    if target_status not in {'checked_in', 'no_show'}:
        return None, '签到状态不合法'

    before_text = f"预约状态:预约成功；签到状态:{'待签到' if current_checkin == 'pending' else current_checkin}"
    after_text = f"预约状态:预约成功；签到状态:{'已签到' if target_status == 'checked_in' else '爽约'}"
    cursor.execute(
        f'''
        UPDATE {table_name}
        SET checkin_status=?, checkin_updated_at=?, checkin_updated_by=?, checkin_updated_ip=?, updated_at=?
        WHERE id=?
        ''',
        (target_status, now_ts, session.get('username', 'anonymous'), get_request_ip(), now_ts, record_id),
    )
    insert_business_history_log(cursor, module_name, record_id, 'checkin_status_update', before_text, after_text)
    insert_audit_log(cursor, '更新签到状态', module_name, record_id, f'{current_checkin}->{target_status}')
    return dict(row), None


@app.route('/api/appointments/<int:aid>/checkin-status', methods=['POST'])
def api_appointment_checkin_status(aid):
    payload = request.json or {}
    target_status = str(payload.get('checkin_status') or '').strip().lower()
    conn = get_db()
    c = conn.cursor()
    _, err = update_checkin_status(c, 'appointments', 'appointments', aid, target_status)
    if err:
        conn.close()
        return error_response(err)
    conn.commit()
    conn.close()
    return success_response({'id': aid, 'checkin_status': target_status}, '签到状态更新成功')


# ========== 上门预约 ==========
@app.route('/api/home-appointments', methods=['GET'])
def api_home_appointments_list():
    sort_by = (request.args.get('sort_by') or 'time_desc').strip()
    status = (request.args.get('status', '') or '').strip().lower()
    search = (request.args.get('search', '') or '').strip()
    date_from = (request.args.get('date_from', '') or '').strip()
    date_to = (request.args.get('date_to', '') or '').strip()
    page, page_size, offset = parse_list_params()
    order_sql = {
        'time_desc': 'h.appointment_date DESC, h.start_time DESC, h.id DESC',
        'time_asc': 'h.appointment_date ASC, h.start_time ASC, h.id ASC',
        'name_asc': 'COALESCE(h.customer_name, c.name) COLLATE NOCASE ASC, h.appointment_date DESC, h.start_time DESC, h.id DESC',
    }.get(sort_by, 'h.appointment_date DESC, h.start_time DESC, h.id DESC')

    conn = get_db()
    c = conn.cursor()
    base_sql = '''
        FROM home_appointments h
        LEFT JOIN customers c ON h.customer_id=c.id
        LEFT JOIN therapy_projects p ON h.project_id=p.id
        LEFT JOIN staff s ON h.staff_id=s.id
        WHERE 1=1
    '''
    params = []
    if status:
        base_sql += ' AND LOWER(COALESCE(h.status, ""))=?'
        params.append(status)
    if search:
        like = f'%{search}%'
        base_sql += ' AND (COALESCE(h.customer_name, c.name) LIKE ? OR COALESCE(h.phone, c.phone) LIKE ?)'
        params.extend([like, like])
    if date_from:
        base_sql += ' AND date(h.appointment_date) >= date(?)'
        params.append(date_from)
    if date_to:
        base_sql += ' AND date(h.appointment_date) <= date(?)'
        params.append(date_to)
    c.execute(f'SELECT COUNT(*) as n {base_sql}', params)
    total = c.fetchone()['n']
    c.execute(f'''
        SELECT
            h.*,
            COALESCE(h.customer_name, c.name) AS customer_name,
            COALESCE(h.service_project, p.name) AS project_name,
            COALESCE(h.staff_name, s.name) AS staff_name,
            COALESCE(h.phone, c.phone) AS phone,
            COALESCE(h.home_address, h.location) AS home_address,
            COALESCE(h.home_time, h.start_time || '-' || h.end_time) AS home_time
        {base_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    ''', params + [page_size, offset])
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


@app.route('/api/home-appointments/slot-panel', methods=['GET'])
def api_home_appointments_slot_panel():
    date = (request.args.get('date') or '').strip()
    project_id = (request.args.get('project_id') or '').strip()
    if not date or not project_id:
        return error_response('缺少参数：date/project_id')
    if not is_valid_date(date):
        return error_response('预约日期格式必须为 YYYY-MM-DD')

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (project_id,))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('上门项目不存在', 404, 'NOT_FOUND')

    c.execute(
        '''
        SELECT COUNT(*) AS n
        FROM project_staff_mapping m
        JOIN staff s ON s.id = m.staff_id
        WHERE m.project_name=?
          AND COALESCE(m.status, 'enabled')='enabled'
          AND COALESCE(s.status, 'available')='available'
        ''',
        (project['name'],),
    )
    mapped_total = c.fetchone()['n'] or 0
    if mapped_total <= 0:
        c.execute("SELECT COUNT(*) AS n FROM staff WHERE status='available'")
        mapped_total = c.fetchone()['n'] or 0

    slots = []
    for st, et in generate_time_slots('08:30', '16:00', 30):
        c.execute(
            '''
            SELECT COUNT(DISTINCT h.staff_id) AS n
            FROM home_appointments h
            WHERE h.appointment_date=?
              AND h.status='scheduled'
              AND h.staff_id IS NOT NULL
              AND (h.start_time < ?) AND (h.end_time > ?)
            ''',
            (date, et, st),
        )
        busy_count = c.fetchone()['n'] or 0
        available_count = max(0, mapped_total - busy_count)
        slots.append({
            'start_time': st,
            'end_time': et,
            'available_count': available_count,
            'status': 'available' if available_count > 0 else 'full',
        })
    conn.close()
    return success_response({
        'project_id': int(project_id),
        'project_name': project['name'],
        'appointment_date': date,
        'slots': slots,
    })


@app.route('/api/home-appointments/staff-panel', methods=['GET'])
def api_home_appointments_staff_panel():
    date = (request.args.get('date') or '').strip()
    project_id = (request.args.get('project_id') or '').strip()
    start_time = (request.args.get('start_time') or '').strip()
    end_time = (request.args.get('end_time') or '').strip()

    if not date or not project_id or not start_time or not end_time:
        return error_response('缺少参数：date/project_id/start_time/end_time')
    if not is_valid_date(date):
        return error_response('预约日期格式必须为 YYYY-MM-DD')
    if not is_valid_home_time_range(start_time, end_time):
        return error_response('上门预约时间需在08:30-16:00且结束时间晚于开始时间')
    if not is_half_hour_slot(start_time, end_time):
        return error_response('上门预约时间段需按30分钟选择')

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (project_id,))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('上门项目不存在', 404, 'NOT_FOUND')

    c.execute(
        '''
        SELECT s.id, s.name, s.role, s.status
        FROM project_staff_mapping m
        JOIN staff s ON s.id = m.staff_id
        WHERE m.project_name=?
          AND COALESCE(m.status, 'enabled')='enabled'
        ORDER BY s.name ASC
        ''',
        (project['name'],),
    )
    mapped = row_list(c.fetchall())
    if not mapped:
        c.execute("SELECT id, name, role, status FROM staff WHERE status='available' ORDER BY name ASC")
        mapped = row_list(c.fetchall())

    items = []
    available_count = 0
    for staff in mapped:
        is_active = (staff.get('status') or 'available') == 'available'
        has_conflict = False
        if is_active:
            c.execute(
                f'''
                SELECT COUNT(*) AS n
                FROM home_appointments
                WHERE staff_id=?
                  AND appointment_date=?
                  AND status='scheduled'
                  AND {overlap_condition()}
                ''',
                (staff['id'], date, end_time, start_time),
            )
            has_conflict = (c.fetchone()['n'] or 0) > 0
        state = 'available' if (is_active and not has_conflict) else 'full'
        if state == 'available':
            available_count += 1
        items.append({
            'staff_id': staff['id'],
            'staff_name': staff.get('name') or '',
            'role': staff.get('role') or '',
            'status': state,
            'display': '可预约' if state == 'available' else '已约满',
        })
    conn.close()
    return success_response({
        'project_id': int(project_id),
        'project_name': project['name'],
        'appointment_date': date,
        'start_time': start_time,
        'end_time': end_time,
        'available_count': available_count,
        'staff': items,
    })


@app.route('/api/home-appointments', methods=['POST'])
def api_home_appointments_create():
    d = request.json or {}
    validation_error = validate_home_appointment_payload(d)
    if validation_error:
        return error_response(validation_error)
    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()
    # 前端未传时由后端自动生成，保证单条/多条都具备分组ID
    booking_group_id = str(d.get('booking_group_id') or '').strip() or generate_booking_group_id()

    c.execute('SELECT id, name, phone FROM customers WHERE id=? AND is_deleted=0', (d.get('customer_id'),))
    customer = c.fetchone()
    if not customer:
        conn.close()
        return error_response('客户不存在', 404, 'NOT_FOUND')

    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('上门项目不存在', 404, 'NOT_FOUND')
    if not is_project_home_allowed(project['name'], c):
        conn.close()
        return error_response('该项目不支持上门预约')

    staff = None
    if d.get('staff_id'):
        c.execute('SELECT id, name FROM staff WHERE id=?', (d.get('staff_id'),))
        staff = c.fetchone()
        if not staff:
            conn.close()
            return error_response('服务人员不存在', 404, 'NOT_FOUND')
        c.execute(
            '''
            SELECT COUNT(*) AS n
            FROM project_staff_mapping
            WHERE project_name=? AND staff_id=? AND COALESCE(status, 'enabled')='enabled'
            ''',
            (project['name'], d.get('staff_id')),
        )
        mapped = c.fetchone()['n'] or 0
        if mapped <= 0:
            c.execute(
                "SELECT COUNT(*) AS n FROM project_staff_mapping WHERE project_name=? AND COALESCE(status, 'enabled')='enabled'",
                (project['name'],),
            )
            has_mapping = c.fetchone()['n'] or 0
            if has_mapping > 0:
                conn.close()
                return error_response('所选服务人员不在该项目服务名单中')

    c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
    if c.fetchone()['n'] > 0:
        conn.close()
        return error_response('同一客户同一时段不能重复上门预约')
    if d.get('staff_id'):
        c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE staff_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (d.get('staff_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
        if c.fetchone()['n'] > 0:
            conn.close()
            return error_response('该服务人员该时段已有上门预约')

    home_address = d.get('home_address') or d.get('location')
    home_time = d.get('home_time') or f"{d.get('start_time')}-{d.get('end_time')}"

    checkin_status = 'none' if str(d.get('status') or 'scheduled').strip().lower() == 'cancelled' else 'pending'
    c.execute('''
        INSERT INTO home_appointments (
            booking_group_id, customer_id, project_id, staff_id,
            customer_name, phone, home_time, home_address, service_project, staff_name,
            appointment_date, start_time, end_time, location, contact_person, contact_phone, has_companion, notes, status, checkin_status, updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        booking_group_id, d.get('customer_id'), d.get('project_id'), d.get('staff_id'),
        customer['name'], customer['phone'], home_time, home_address, project['name'], staff['name'] if staff else None,
        d.get('appointment_date'), d.get('start_time'), d.get('end_time'), d.get('location'), d.get('contact_person'), d.get('contact_phone'), d.get('has_companion', '无'), d.get('notes'), d.get('status', 'scheduled'), checkin_status, now_ts
    ))
    rid = c.lastrowid
    c.execute(
        '''
        SELECT *
        FROM home_appointments
        WHERE id=?
        ''',
        (rid,),
    )
    created_row = c.fetchone()
    insert_business_history_log(
        c,
        'home_appointments',
        rid,
        'create',
        '',
        build_appointment_change_text(dict(created_row) if created_row else {}, 'home_appointments'),
    )
    conn.commit()
    conn.close()
    audit_log('创建上门预约', 'home_appointments', rid, d.get('appointment_date'))
    return success_response({'id': rid, 'booking_group_id': booking_group_id}, '上门预约成功', 201)


@app.route('/api/home-appointments/<int:hid>/cancel', methods=['POST'])
def api_home_appointments_cancel(hid):
    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()
    c.execute('SELECT * FROM home_appointments WHERE id=?', (hid,))
    row = c.fetchone()
    if not row:
        conn.close()
        return error_response('上门预约不存在', 404, 'NOT_FOUND')
    if (row['status'] or '').strip().lower() == 'cancelled':
        conn.close()
        return error_response('已经提交过取消预约，请勿再次提交')
    c.execute(
        "UPDATE home_appointments SET status='cancelled', checkin_status='none', checkin_updated_at=?, checkin_updated_by=?, checkin_updated_ip=?, updated_at=? WHERE id=?",
        (now_ts, session.get('username', 'anonymous'), get_request_ip(), now_ts, hid),
    )
    insert_business_history_log(
        c,
        'home_appointments',
        hid,
        'cancel',
        build_appointment_change_text(dict(row), 'home_appointments'),
        '状态:取消预约',
    )
    conn.commit()
    conn.close()
    audit_log('取消预约', 'home_appointments', hid, '上门预约取消')
    return success_response({'id': hid}, '已取消')


@app.route('/api/home-appointments/<int:hid>/checkin-status', methods=['POST'])
def api_home_appointments_checkin_status(hid):
    payload = request.json or {}
    target_status = str(payload.get('checkin_status') or '').strip().lower()
    conn = get_db()
    c = conn.cursor()
    _, err = update_checkin_status(c, 'home_appointments', 'home_appointments', hid, target_status)
    if err:
        conn.close()
        return error_response(err)
    conn.commit()
    conn.close()
    return success_response({'id': hid, 'checkin_status': target_status}, '签到状态更新成功')


@app.route('/api/home-appointments/<int:hid>', methods=['PUT'])
def api_home_appointments_update(hid):
    d = request.json or {}
    validation_error = validate_home_appointment_payload(d)
    if validation_error:
        return error_response(validation_error)
    conn = get_db()
    c = conn.cursor()
    now_ts = now_local_str()

    c.execute('SELECT * FROM home_appointments WHERE id=?', (hid,))
    old_row = c.fetchone()
    if not old_row:
        conn.close()
        return error_response('上门预约不存在', 404, 'NOT_FOUND')

    c.execute('SELECT id, name, phone FROM customers WHERE id=? AND is_deleted=0', (d.get('customer_id'),))
    customer = c.fetchone()
    if not customer:
        conn.close()
        return error_response('客户不存在', 404, 'NOT_FOUND')

    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return error_response('上门项目不存在', 404, 'NOT_FOUND')
    if not is_project_home_allowed(project['name'], c):
        conn.close()
        return error_response('该项目不支持上门预约')

    staff = None
    if d.get('staff_id'):
        c.execute('SELECT id, name FROM staff WHERE id=?', (d.get('staff_id'),))
        staff = c.fetchone()
        if not staff:
            conn.close()
            return error_response('服务人员不存在', 404, 'NOT_FOUND')
        c.execute(
            '''
            SELECT COUNT(*) AS n
            FROM project_staff_mapping
            WHERE project_name=? AND staff_id=? AND COALESCE(status, 'enabled')='enabled'
            ''',
            (project['name'], d.get('staff_id')),
        )
        mapped = c.fetchone()['n'] or 0
        if mapped <= 0:
            c.execute(
                "SELECT COUNT(*) AS n FROM project_staff_mapping WHERE project_name=? AND COALESCE(status, 'enabled')='enabled'",
                (project['name'],),
            )
            has_mapping = c.fetchone()['n'] or 0
            if has_mapping > 0:
                conn.close()
                return error_response('所选服务人员不在该项目服务名单中')

    c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE id<>? AND customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (hid, d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
    if c.fetchone()['n'] > 0:
        conn.close()
        return error_response('同一客户同一时段不能重复上门预约')
    if d.get('staff_id'):
        c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE id<>? AND staff_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (hid, d.get('staff_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
        if c.fetchone()['n'] > 0:
            conn.close()
            return error_response('该服务人员该时段已有上门预约')

    home_address = d.get('home_address') or d.get('location')
    home_time = d.get('home_time') or f"{d.get('start_time')}-{d.get('end_time')}"

    new_status = str(d.get('status', 'scheduled') or 'scheduled').strip().lower()
    old_checkin_status = str(old_row['checkin_status'] or 'pending').strip().lower()
    next_checkin_status = 'none' if new_status == 'cancelled' else ('pending' if old_checkin_status == 'none' else old_checkin_status)

    c.execute('''
        UPDATE home_appointments
        SET customer_id=?, project_id=?, staff_id=?,
            customer_name=?, phone=?, home_time=?, home_address=?, service_project=?, staff_name=?,
            appointment_date=?, start_time=?, end_time=?, location=?,
            contact_person=?, contact_phone=?, has_companion=?, notes=?, status=?, checkin_status=?, updated_at=?
        WHERE id=?
    ''', (
        d.get('customer_id'), d.get('project_id'), d.get('staff_id'),
        customer['name'], customer['phone'], home_time, home_address, project['name'], staff['name'] if staff else None,
        d.get('appointment_date'), d.get('start_time'), d.get('end_time'), d.get('location'),
        d.get('contact_person'), d.get('contact_phone'), d.get('has_companion', '无'), d.get('notes'), new_status, next_checkin_status, now_ts,
        hid,
    ))
    before_text = build_appointment_change_text(dict(old_row), 'home_appointments')
    c.execute('SELECT * FROM home_appointments WHERE id=?', (hid,))
    new_row = c.fetchone()
    insert_business_history_log(
        c,
        'home_appointments',
        hid,
        'update',
        before_text,
        build_appointment_change_text(dict(new_row) if new_row else {}, 'home_appointments'),
    )
    conn.commit()
    conn.close()
    audit_log('修改上门预约', 'home_appointments', hid, d.get('appointment_date'))
    return success_response({'id': hid}, '更新成功')


@app.route('/api/tasks/checkin-auto-no-show', methods=['POST'])
def api_task_checkin_auto_no_show():
    payload = request.json or {}
    now_ts = now_local_str()
    task_date = str(payload.get('task_date') or now_ts[:10]).strip()
    if not is_valid_date(task_date):
        return error_response('task_date 格式必须为 YYYY-MM-DD')
    operator = session.get('username', 'system')
    operator_ip = get_request_ip()

    conn = get_db()
    c = conn.cursor()
    affected_total = 0
    detail_rows = []
    for table_name, module_name in (('appointments', 'appointments'), ('home_appointments', 'home_appointments')):
        c.execute(
            f'''
            SELECT id
            FROM {table_name}
            WHERE appointment_date=?
              AND status='scheduled'
              AND COALESCE(checkin_status, 'pending')='pending'
            ''',
            (task_date,),
        )
        ids = [r['id'] for r in c.fetchall()]
        if not ids:
            detail_rows.append(f'{module_name}:0')
            continue
        ph = ','.join('?' * len(ids))
        c.execute(
            f'''
            UPDATE {table_name}
            SET checkin_status='no_show', checkin_updated_at=?, checkin_updated_by=?, checkin_updated_ip=?, updated_at=?
            WHERE id IN ({ph})
            ''',
            [now_ts, operator, operator_ip, now_ts] + ids,
        )
        for rid in ids:
            insert_business_history_log(
                c,
                module_name,
                rid,
                'checkin_auto_no_show',
                '签到状态:待签到',
                '签到状态:爽约（系统自动流转）',
            )
        affected_total += len(ids)
        detail_rows.append(f'{module_name}:{len(ids)}')

    c.execute(
        '''
        INSERT INTO task_execution_logs (task_name, task_date, affected_rows, details, executed_by, executed_ip)
        VALUES (?,?,?,?,?,?)
        ''',
        ('checkin_auto_no_show', task_date, affected_total, '；'.join(detail_rows), operator, operator_ip),
    )
    conn.commit()
    conn.close()
    return success_response({'task_date': task_date, 'affected_rows': affected_total, 'details': detail_rows}, '自动流转执行完成')


@app.route('/api/business-history/<module>/<int:target_id>', methods=['GET'])
def api_business_history(module, target_id):
    if module not in ('appointments', 'home_appointments'):
        return error_response('不支持的业务模块', 400, 'INVALID_MODULE')
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT
            l.*,
            MAX(CASE WHEN l2.action_type='update' THEN l2.created_at END) AS modified_time,
            MAX(CASE WHEN l2.action_type='cancel' THEN l2.created_at END) AS cancelled_time
        FROM business_history_logs l
        LEFT JOIN business_history_logs l2
          ON l.module=l2.module AND l.target_id=l2.target_id
        WHERE l.module=? AND l.target_id=?
        GROUP BY l.id
        ORDER BY l.created_at DESC, l.id DESC
        ''',
        (module, target_id),
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(rows)


@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    data = request.json or {}
    username = str(data.get('username') or '').strip()
    password = str(data.get('password') or '').strip()
    config_user = get_setting_value('login_username', 'admin')
    password_hash = get_setting_value('password_hash', '')

    login_ok = False
    if username == config_user and password_hash:
        login_ok = check_password_hash(password_hash, password)
    elif verify_legacy_plaintext_and_migrate(username, password):
        # 兼容旧库明文配置：首次成功后自动转为 hash，后续统一走 hash 校验。
        login_ok = True

    if login_ok:
        session['logged_in'] = True
        session['username'] = username
        audit_log('登录', 'auth', username, '登录成功')
        return jsonify({'message': '登录成功'})
    return jsonify({'error': '账号或密码错误'}), 401


@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    username = session.get('username', 'anonymous')
    audit_log('退出登录', 'auth', username, 'logout')
    session.clear()
    return jsonify({'message': '已退出登录'})


@app.route('/api/audit-logs', methods=['GET'])
def api_audit_logs():
    page, page_size, offset = parse_list_params(default_page_size=20, max_page_size=200)
    start_time = (request.args.get('start_time') or '').strip()
    end_time = (request.args.get('end_time') or '').strip()
    operator = (request.args.get('operator') or '').strip()
    module = (request.args.get('module') or '').strip()
    action = (request.args.get('action') or '').strip()
    keyword = (request.args.get('keyword') or '').strip()

    conditions = ['1=1']
    params = []
    if start_time:
        conditions.append('created_at >= ?')
        params.append(start_time + ' 00:00:00')
    if end_time:
        conditions.append('created_at <= ?')
        params.append(end_time + ' 23:59:59')
    if operator:
        conditions.append('username LIKE ?')
        params.append(f'%{operator}%')
    if module:
        conditions.append('module LIKE ?')
        params.append(f'%{module}%')
    if action:
        conditions.append('action LIKE ?')
        params.append(f'%{action}%')
    if keyword:
        conditions.append('(target_id LIKE ? OR details LIKE ?)')
        params.extend([f'%{keyword}%', f'%{keyword}%'])

    where_sql = ' WHERE ' + ' AND '.join(conditions)
    conn = get_db()
    c = conn.cursor()
    c.execute(f'SELECT COUNT(*) AS n FROM audit_logs {where_sql}', params)
    total = c.fetchone()['n']
    c.execute(
        f'''
        SELECT id, created_at, username, module, action, target_id, details
        FROM audit_logs
        {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        ''',
        params + [page_size, offset],
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response(paginate_result(rows, total, page, page_size))


# ========== 综合查询 ==========
@app.route('/api/search', methods=['GET'])
def api_search():
    q = (request.args.get('q') or '').strip()
    kind = request.args.get('type', 'all')
    if not q and kind == 'all':
        return jsonify({'customers': [], 'health_records': [], 'appointments': [], 'visit_checkins': []})

    conn = get_db()
    c = conn.cursor()
    like = f'%{q}%'
    result = {}

    if kind in ('all', 'customers'):
        c.execute('SELECT * FROM customers WHERE is_deleted=0 AND (name LIKE ? OR id_card LIKE ? OR phone LIKE ? OR email LIKE ? OR address LIKE ?) ORDER BY created_at DESC LIMIT 100',
                  (like, like, like, like, like))
        result['customers'] = row_list(c.fetchall())

    if kind in ('all', 'health'):
        c.execute('SELECT h.*, c.name as customer_name FROM health_assessments h JOIN customers c ON h.customer_id=c.id WHERE c.name LIKE ? OR c.id_card LIKE ? OR c.phone LIKE ? OR h.notes LIKE ? ORDER BY h.assessment_date DESC LIMIT 100',
                  (like, like, like, like))
        result['health_records'] = row_list(c.fetchall())

    if kind in ('all', 'appointments'):
        c.execute('''SELECT a.*, c.name as customer_name, c.phone as customer_phone, e.name as equipment_name
            FROM appointments a JOIN customers c ON a.customer_id=c.id LEFT JOIN equipment e ON a.equipment_id=e.id
            WHERE c.name LIKE ? OR c.id_card LIKE ? OR c.phone LIKE ? OR a.notes LIKE ?
            ORDER BY a.appointment_date DESC, a.start_time DESC LIMIT 100''', (like, like, like, like))
        result['appointments'] = row_list(c.fetchall())

    if kind in ('all', 'checkins'):
        c.execute('SELECT v.*, c.name as customer_name FROM visit_checkins v JOIN customers c ON v.customer_id=c.id WHERE c.name LIKE ? OR c.id_card LIKE ? OR c.phone LIKE ? OR v.purpose LIKE ? OR v.notes LIKE ? ORDER BY v.checkin_time DESC LIMIT 100',
                  (like, like, like, like, like))
        result['visit_checkins'] = row_list(c.fetchall())

    for key in ('customers', 'health_records', 'appointments', 'visit_checkins'):
        if key not in result:
            result[key] = []

    conn.close()
    return jsonify(result)


@app.route('/api/query-export/no-show-top10', methods=['GET'])
def api_query_export_no_show_top10():
    start_date = (request.args.get('start_date') or '').strip()
    end_date = (request.args.get('end_date') or '').strip()
    if start_date and not is_valid_date(start_date):
        return error_response('开始日期格式必须为 YYYY-MM-DD')
    if end_date and not is_valid_date(end_date):
        return error_response('结束日期格式必须为 YYYY-MM-DD')
    if start_date and end_date and start_date > end_date:
        return error_response('开始日期不能晚于结束日期')

    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        SELECT customer_name, SUM(no_show_count) AS no_show_count
        FROM (
            SELECT COALESCE(NULLIF(TRIM(c.name), ''), '未命名客户') AS customer_name,
                   COUNT(*) AS no_show_count
            FROM appointments a
            LEFT JOIN customers c ON c.id = a.customer_id
            WHERE LOWER(COALESCE(a.checkin_status, '')) = 'no_show'
              AND (? = '' OR a.appointment_date >= ?)
              AND (? = '' OR a.appointment_date <= ?)
            GROUP BY customer_name
            UNION ALL
            SELECT COALESCE(NULLIF(TRIM(c.name), ''), NULLIF(TRIM(h.customer_name), ''), '未命名客户') AS customer_name,
                   COUNT(*) AS no_show_count
            FROM home_appointments h
            LEFT JOIN customers c ON c.id = h.customer_id
            WHERE LOWER(COALESCE(h.checkin_status, '')) = 'no_show'
              AND (? = '' OR h.appointment_date >= ?)
              AND (? = '' OR h.appointment_date <= ?)
            GROUP BY customer_name
        ) merged
        GROUP BY customer_name
        ORDER BY no_show_count DESC, customer_name COLLATE NOCASE ASC
        LIMIT 10
        ''',
        (start_date, start_date, end_date, end_date, start_date, start_date, end_date, end_date),
    )
    rows = row_list(c.fetchall())
    conn.close()
    return success_response({
        'items': [{'name': row.get('customer_name') or '-', 'count': int((row.get('no_show_count') or 0))} for row in rows],
        'start_date': start_date,
        'end_date': end_date,
    })


# ========== 仪表盘 ==========
@app.route('/api/dashboard/stats', methods=['GET'])
def api_dashboard_stats():
    conn = get_db()
    c = conn.cursor()
    today_str = now_local_date_str()
    c.execute("SELECT COUNT(*) as n FROM appointments WHERE status='completed'")
    completed_appointments = c.fetchone()['n']
    c.execute("SELECT COUNT(*) as n FROM home_appointments WHERE status='completed'")
    completed_home_appointments = c.fetchone()['n']
    cumulative_service_count = completed_appointments + completed_home_appointments

    c.execute('''
        SELECT ROUND(AVG(month_total), 1) as avg_count
        FROM (
            SELECT month_key, SUM(month_total) as month_total
            FROM (
                SELECT strftime('%Y-%m', appointment_date) as month_key, COUNT(*) as month_total
                FROM appointments
                WHERE status='completed'
                GROUP BY month_key
                UNION ALL
                SELECT strftime('%Y-%m', appointment_date) as month_key, COUNT(*) as month_total
                FROM home_appointments
                WHERE status='completed'
                GROUP BY month_key
            ) raw_monthly
            GROUP BY month_key
        ) monthly
    ''')
    month_avg_row = c.fetchone()
    monthly_avg_service_count = month_avg_row['avg_count'] if month_avg_row and month_avg_row['avg_count'] is not None else 0

    c.execute('''
        SELECT COUNT(*) as n
        FROM appointments
        WHERE appointment_date=?
          AND LOWER(COALESCE(checkin_status, ''))='checked_in'
    ''', (today_str,))
    today_checked_appointments = c.fetchone()['n']
    c.execute('''
        SELECT COUNT(*) as n
        FROM home_appointments
        WHERE appointment_date=?
          AND LOWER(COALESCE(checkin_status, ''))='checked_in'
    ''', (today_str,))
    today_checked_home_appointments = c.fetchone()['n']
    today_service_count = (today_checked_appointments or 0) + (today_checked_home_appointments or 0)
    c.execute('''
        SELECT
            SUM(CASE WHEN c.gender='男' THEN 1 ELSE 0 END) as male_service_count,
            SUM(CASE WHEN c.gender='女' THEN 1 ELSE 0 END) as female_service_count
        FROM (
            SELECT customer_id FROM appointments WHERE status='completed'
            UNION ALL
            SELECT customer_id FROM home_appointments WHERE status='completed'
        ) svc
        JOIN customers c ON c.id = svc.customer_id
        WHERE c.is_deleted=0
    ''')
    gender_row = c.fetchone()
    conn.close()
    return jsonify({
        'cumulative_service_count': cumulative_service_count,
        'male_service_count': int((gender_row['male_service_count'] if gender_row else 0) or 0),
        'female_service_count': int((gender_row['female_service_count'] if gender_row else 0) or 0),
        'monthly_avg_service_count': monthly_avg_service_count,
        'today_service_count': int(today_service_count),
    })


@app.route('/api/dashboard/analytics', methods=['GET'])
def api_dashboard_analytics():
    conn = get_db()
    c = conn.cursor()
    equipment_start_date = (request.args.get('equipment_start_date') or '').strip()
    equipment_end_date = (request.args.get('equipment_end_date') or '').strip()

    # 最近 7 天预约趋势（包含 0 值日期）
    today = now_local().date()
    start_day = today - timedelta(days=6)
    c.execute('''
        SELECT appointment_date, SUM(n) as n
        FROM (
            SELECT appointment_date, COUNT(*) as n
            FROM appointments
            WHERE status <> 'cancelled' AND appointment_date BETWEEN ? AND ?
            GROUP BY appointment_date
            UNION ALL
            SELECT appointment_date, COUNT(*) as n
            FROM home_appointments
            WHERE status <> 'cancelled' AND appointment_date BETWEEN ? AND ?
            GROUP BY appointment_date
        ) merged
        GROUP BY appointment_date
        ORDER BY appointment_date
    ''', (
        start_day.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'),
        start_day.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')
    ))
    appt_map = {row['appointment_date']: row['n'] for row in c.fetchall()}
    appointment_trend = []
    for i in range(7):
        day = start_day + timedelta(days=i)
        key = day.strftime('%Y-%m-%d')
        appointment_trend.append({'date': key, 'count': appt_map.get(key, 0)})

    # 预约状态分布
    c.execute('''
        SELECT status, COUNT(*) as n
        FROM appointments
        GROUP BY status
        ORDER BY n DESC
    ''')
    appointment_status = row_list(c.fetchall())

    # 设备使用统计（按预约服务历史记录汇总总时长 + 次数）
    equipment_join_conditions = ["a.status = 'completed'"]
    equipment_params = []
    if equipment_start_date:
        equipment_join_conditions.append('a.appointment_date >= ?')
        equipment_params.append(equipment_start_date)
    if equipment_end_date:
        equipment_join_conditions.append('a.appointment_date <= ?')
        equipment_params.append(equipment_end_date)
    equipment_join_sql = ' AND '.join(equipment_join_conditions)
    if equipment_join_sql:
        equipment_join_sql = ' AND ' + equipment_join_sql
    c.execute(f'''
        SELECT project_category as equipment_name,
               SUM(usage_count) as usage_count,
               SUM(total_duration_minutes) as total_duration_minutes
        FROM (
            SELECT
                   CASE
                       WHEN COALESCE(TRIM(p.name), '') <> '' THEN TRIM(p.name)
                       WHEN COALESCE(TRIM(e.name), '') = '' THEN '未配置设备'
                       WHEN TRIM(e.name) GLOB '*[0-9][0-9]' THEN SUBSTR(TRIM(e.name), 1, LENGTH(TRIM(e.name)) - 2)
                       WHEN TRIM(e.name) GLOB '*[0-9]' THEN SUBSTR(TRIM(e.name), 1, LENGTH(TRIM(e.name)) - 1)
                       ELSE TRIM(e.name)
                   END as project_category,
                   COUNT(a.id) as usage_count,
                   COALESCE(SUM(
                       CASE
                           WHEN a.start_time IS NOT NULL AND a.end_time IS NOT NULL
                                AND a.end_time > a.start_time
                           THEN (strftime('%s', '2000-01-01 ' || a.end_time) - strftime('%s', '2000-01-01 ' || a.start_time)) / 60
                           ELSE 0
                       END
                   ), 0) as total_duration_minutes
            FROM appointments a
            LEFT JOIN equipment e ON e.id = a.equipment_id
            LEFT JOIN therapy_projects p ON p.id = a.project_id
            WHERE 1=1{equipment_join_sql}
            GROUP BY project_category
            UNION ALL
            SELECT COALESCE(NULLIF(TRIM(p.name), ''), NULLIF(TRIM(h.service_project), ''), '未配置设备') as project_category,
                   COUNT(h.id) as usage_count,
                   COALESCE(SUM(
                       CASE
                           WHEN h.start_time IS NOT NULL AND h.end_time IS NOT NULL
                                AND h.end_time > h.start_time
                           THEN (strftime('%s', '2000-01-01 ' || h.end_time) - strftime('%s', '2000-01-01 ' || h.start_time)) / 60
                           ELSE 0
                       END
                   ), 0) as total_duration_minutes
            FROM home_appointments h
            LEFT JOIN therapy_projects p ON p.id = h.project_id
            WHERE h.status = 'completed'
              AND (? = '' OR h.appointment_date >= ?)
              AND (? = '' OR h.appointment_date <= ?)
            GROUP BY project_category
        ) merged
        GROUP BY project_category
        ORDER BY usage_count DESC, total_duration_minutes DESC
        LIMIT 10
    ''', equipment_params + [equipment_start_date, equipment_start_date, equipment_end_date, equipment_end_date])
    equipment_usage_top = row_list(c.fetchall())

    # 客户活跃度：有预约或有健康档案的客户
    c.execute('''
        SELECT COUNT(DISTINCT customer_id) as n FROM (
            SELECT customer_id FROM appointments
            UNION ALL
            SELECT customer_id FROM health_assessments
        )
    ''')
    active_customers = c.fetchone()['n']
    c.execute('SELECT COUNT(*) as n FROM customers WHERE is_deleted=0')
    total_customers = c.fetchone()['n']

    conn.close()
    return jsonify({
        'appointment_trend': appointment_trend,
        'appointment_status': appointment_status,
        'equipment_usage_top': equipment_usage_top,
        'customer_activity': {
            'active_customers': active_customers,
            'total_customers': total_customers,
        }
    })


@app.route('/api/dashboard/health-portrait', methods=['GET'])
def api_dashboard_health_portrait():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT latest_h.*, c.name as customer_name, c.gender, c.birth_date, c.chronic_diseases, c.medical_history
        FROM (
            SELECT h.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY h.customer_id
                       ORDER BY h.assessment_date DESC, h.id DESC
                   ) AS row_no
            FROM health_assessments h
        ) latest_h
        JOIN customers c ON latest_h.customer_id = c.id
        WHERE latest_h.row_no = 1
        ORDER BY latest_h.customer_id DESC, latest_h.id DESC
    ''')
    rows = row_list(c.fetchall())
    conn.close()

    dedup = {}
    for row in rows:
        dedup[row['customer_id']] = row
    records = list(dedup.values())

    age_segments = ['<50岁', '50-60岁', '61-65岁', '66-70岁', '71-75岁', '76-80岁', '>80岁']
    age_distribution = {k: 0 for k in age_segments}
    genders = {'男': 0, '女': 0, '未知': 0}
    age_gender_buckets = ['50-60岁', '60-70岁', '70-80岁', '80岁以上']
    age_gender_distribution = {
        '50-60岁': {'男': 0, '女': 0},
        '60-70岁': {'男': 0, '女': 0},
        '70-80岁': {'男': 0, '女': 0},
        '80岁以上': {'男': 0, '女': 0},
    }
    bmi_levels = {'偏瘦': 0, '正常': 0, '超重': 0, '肥胖': 0}
    risks = {'低风险': 0, '中风险': 0, '高风险': 0}
    high_risk_customers = []

    past_disease_counter = Counter()
    family_disease_counter = Counter()
    allergy_counter = Counter()
    pain_counter = Counter()
    recent_symptom_counter = Counter()
    behavior_tag_counter = Counter()
    exercise_counter = Counter()
    demand_counter = Counter()

    smoking_people = 0
    drinking_people = 0
    smoking_drinking_people = 0
    sleep_abnormal_people = 0
    poor_sleep_people = 0
    family_history_people = 0
    allergy_people = 0
    chronic_pain_people = 0
    dual_history_high_risk_people = 0
    history_plus_bp_abnormal_people = 0
    low_exercise_bad_habit_people = 0
    bmi_abnormal = 0
    blood_pressure_abnormal_people = 0
    blood_lipid_abnormal_people = 0
    blood_sugar_abnormal_people = 0
    sleep_issue_people = 0


    for row in records:
        age = safe_int(row.get('age'))
        if age is None and row.get('birth_date'):
            try:
                birth = datetime.strptime(row.get('birth_date')[:10], '%Y-%m-%d').date()
                today = now_local().date()
                age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
            except Exception:
                age = None
        age_seg = classify_age_segment(age)
        if age_seg:
            age_distribution[age_seg] += 1

        gender = (row.get('gender') or '').strip()
        genders[gender if gender in ('男', '女') else '未知'] += 1
        if gender in ('男', '女') and age:
            if 50 <= age < 60:
                age_gender_distribution['50-60岁'][gender] += 1
            elif 60 <= age < 70:
                age_gender_distribution['60-70岁'][gender] += 1
            elif 70 <= age < 80:
                age_gender_distribution['70-80岁'][gender] += 1
            elif age >= 80:
                age_gender_distribution['80岁以上'][gender] += 1

        _, bmi_level = classify_bmi(row.get('height_cm'), row.get('weight_kg'))
        if bmi_level:
            bmi_levels[bmi_level] += 1
            if bmi_level != '正常':
                bmi_abnormal += 1

        blood_pressure_test = str(row.get('blood_pressure_test') or '')
        blood_lipid_test = str(row.get('blood_lipid_test') or '')
        blood_sugar_test = str(row.get('blood_sugar_test') or '')
        sleep_hours_text = str(row.get('sleep_hours') or '')
        sleep_quality_text = str(row.get('sleep_quality') or '')

        bp_abnormal = ('偏高' in blood_pressure_test) or ('偏低' in blood_pressure_test)
        lipid_abnormal = '偏高' in blood_lipid_test
        sugar_abnormal = ('偏高' in blood_sugar_test) or ('偏低' in blood_sugar_test)
        sleep_hours_abnormal = sleep_hours_text in ('<6小时', '>10小时')
        sleep_quality_abnormal = sleep_quality_text in ('很差', '差')
        sleep_abnormal = sleep_quality_abnormal or sleep_hours_abnormal

        if bp_abnormal:
            blood_pressure_abnormal_people += 1
        if lipid_abnormal:
            blood_lipid_abnormal_people += 1
        if sugar_abnormal:
            blood_sugar_abnormal_people += 1
        if sleep_abnormal:
            sleep_issue_people += 1

        risk_info = calculate_lightweight_risk(row)
        risk_level = risk_info['risk_level']
        risks[risk_level] += 1
        if risk_level == '高风险':
            high_risk_customers.append({
                'customer_id': row.get('customer_id'),
                'customer_name': row.get('name') or row.get('customer_name') or '-',
                'age': risk_info.get('age'),
                'risk_level': risk_level,
                'risk_score': risk_info.get('risk_score', 0),
                'risk_reasons': risk_info.get('risk_reasons', []),
                'recommended_intervention': risk_info.get('recommended_intervention', ''),
            })

        past_history_items = normalize_multi_text(row.get('past_medical_history'))
        family_history_items = normalize_multi_text(row.get('family_history'))
        allergy_items = normalize_multi_text(row.get('allergy_details'))
        pain_items = normalize_multi_text(row.get('pain_details'))
        recent_symptom_items = normalize_multi_text(row.get('recent_symptoms'))
        exercise_items = normalize_multi_text(row.get('exercise_methods'))
        demand_items = normalize_multi_text(row.get('health_needs'))

        for item in past_history_items:
            past_disease_counter[item] += 1
        for item in family_history_items:
            family_disease_counter[item] += 1
        for item in allergy_items:
            allergy_counter[item] += 1
        for item in pain_items:
            pain_counter[item] += 1
        for item in recent_symptom_items:
            recent_symptom_counter[item] += 1
        for item in exercise_items:
            exercise_counter[item] += 1
        for item in demand_items:
            demand_counter[item] += 1

        smoking = row.get('smoking_status') == '有'
        drinking = row.get('drinking_status') == '有'
        low_exercise = not exercise_items or any(item in ('无', '不运动', '很少运动', '偶尔运动') for item in exercise_items)
        poor_sleep = sleep_quality_abnormal
        has_past_history = bool(past_history_items)
        has_family_history = bool(family_history_items)

        if smoking:
            smoking_people += 1
            behavior_tag_counter['烟民'] += 1
        if drinking:
            drinking_people += 1
        if smoking and drinking:
            smoking_drinking_people += 1
        if sleep_abnormal:
            sleep_abnormal_people += 1
        if poor_sleep:
            poor_sleep_people += 1
            behavior_tag_counter['熬夜族'] += 1
        if low_exercise:
            behavior_tag_counter['久坐不动族'] += 1
        if has_family_history:
            family_history_people += 1
        if row.get('allergy_history') == '有' or allergy_items:
            allergy_people += 1
        if row.get('chronic_pain') == '有':
            chronic_pain_people += 1

        if has_family_history and has_past_history:
            dual_history_high_risk_people += 1
        if has_past_history and row.get('blood_pressure_test') == '监测：偏高':
            history_plus_bp_abnormal_people += 1
        if low_exercise and (smoking or drinking or poor_sleep):
            low_exercise_bad_habit_people += 1
        if bmi_level == '肥胖' and age and age >= 60:
            behavior_tag_counter['老年肥胖人群'] += 1
        if age and 50 <= age <= 60 and row.get('blood_pressure_test') == '监测：偏高':
            behavior_tag_counter['中年高血压风险人群'] += 1

    high_risk_customers.sort(
        key=lambda item: (
            -safe_int(item.get('risk_score') or 0),
            -safe_int(item.get('age') or 0),
            str(item.get('customer_name') or '')
        )
    )
    high_risk_top = high_risk_customers[:10]

    total = len(records)
    senior_count = age_distribution['66-70岁'] + age_distribution['71-75岁'] + age_distribution['76-80岁'] + age_distribution['>80岁']

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT r.service_project, r.service_content, r.improvement_status,
               a.status AS appointment_status, ha.status AS home_appointment_status
        FROM service_improvement_records r
        LEFT JOIN appointments a ON r.service_type='appointment' AND r.service_id=a.id
        LEFT JOIN home_appointments ha ON r.service_type='home' AND r.service_id=ha.id
    ''')
    improvement_rows = row_list(c.fetchall())

    heatmap = {}
    improvement_project_stats = {}
    status_order = ['无改善', '部分改善', '明显改善', '加重']
    for row in improvement_rows:
        appt_status = (row.get('appointment_status') or '').strip().lower()
        home_status = (row.get('home_appointment_status') or '').strip().lower()
        if appt_status == 'cancelled' or home_status == 'cancelled':
            continue
        project = (row.get('service_project') or '未标注项目').strip() or '未标注项目'
        content = (row.get('service_content') or '').strip()
        parts = normalize_multi_text(content) or ['未标注部位']
        status = (row.get('improvement_status') or '').strip()
        if status not in status_order:
            status = '无改善'
        project_bucket = improvement_project_stats.setdefault(
            project,
            {'total_services': 0, '明显改善': 0, '部分改善': 0, '无改善': 0, '加重': 0}
        )
        project_bucket['total_services'] += 1
        project_bucket[status] += 1
        project_bucket = heatmap.setdefault(project, {})
        for part in parts:
            part_name = part.strip() or '未标注部位'
            cell = project_bucket.setdefault(part_name, {'count': 0, 'statuses': {s: 0 for s in status_order}})
            cell['count'] += 1
            cell['statuses'][status] += 1

    heatmap_rows = []
    for project, cols in heatmap.items():
        for part, cell in cols.items():
            status_summary = ' / '.join([f'{k}{cell["statuses"].get(k, 0)}' for k in status_order if cell["statuses"].get(k, 0)])
            heatmap_rows.append({
                'service_project': project,
                'therapy_part': part,
                'count': cell['count'],
                'status_summary': status_summary or '无改善0',
            })

    improvement_project_ranking = []
    for project, stat in improvement_project_stats.items():
        total_services = safe_int(stat.get('total_services')) or 0
        obvious_improved_count = safe_int(stat.get('明显改善')) or 0
        partial_improved_count = safe_int(stat.get('部分改善')) or 0
        no_improved_count = safe_int(stat.get('无改善')) or 0
        worsen_count = safe_int(stat.get('加重')) or 0
        improvement_rate = ((obvious_improved_count + partial_improved_count) / total_services) if total_services else 0
        improvement_project_ranking.append({
            'service_project': project,
            'total_services': total_services,
            'obvious_improved_count': obvious_improved_count,
            'partial_improved_count': partial_improved_count,
            'no_improved_count': no_improved_count,
            'worsen_count': worsen_count,
            'improvement_rate': round(improvement_rate, 4),
            'improvement_rate_percent': round(improvement_rate * 100, 1),
        })
    improvement_project_ranking.sort(
        key=lambda item: (
            -float(item.get('improvement_rate') or 0),
            -safe_int(item.get('total_services') or 0),
            str(item.get('service_project') or '')
        )
    )

    archived_customer_ids = {safe_int(row.get('customer_id')) for row in records if safe_int(row.get('customer_id')) is not None}
    health_need_customer_ids = set()
    for row in records:
        customer_id = safe_int(row.get('customer_id'))
        if customer_id is None:
            continue
        need_items = normalize_multi_text(row.get('health_needs'))
        if need_items and not all(item == '无' for item in need_items):
            health_need_customer_ids.add(customer_id)
    health_need_customer_ids &= archived_customer_ids

    c.execute(
        '''
        SELECT DISTINCT customer_id
        FROM appointments
        WHERE LOWER(COALESCE(status, '')) <> 'cancelled'
        UNION
        SELECT DISTINCT customer_id
        FROM home_appointments
        WHERE LOWER(COALESCE(status, '')) <> 'cancelled'
        '''
    )
    booked_customer_ids = {safe_int(row['customer_id']) for row in c.fetchall() if safe_int(row['customer_id']) is not None}
    booked_customer_ids &= health_need_customer_ids

    c.execute(
        '''
        SELECT DISTINCT customer_id
        FROM appointments
        WHERE LOWER(COALESCE(checkin_status, ''))='checked_in'
        UNION
        SELECT DISTINCT customer_id
        FROM home_appointments
        WHERE LOWER(COALESCE(checkin_status, ''))='checked_in'
        '''
    )
    checked_in_customer_ids = {safe_int(row['customer_id']) for row in c.fetchall() if safe_int(row['customer_id']) is not None}
    checked_in_customer_ids &= booked_customer_ids

    c.execute('SELECT DISTINCT customer_id, improvement_status FROM service_improvement_records')
    improvement_customers = row_list(c.fetchall())
    filled_improvement_customer_ids = {
        safe_int(row.get('customer_id'))
        for row in improvement_customers
        if safe_int(row.get('customer_id')) is not None
    }
    filled_improvement_customer_ids &= checked_in_customer_ids

    improved_customer_ids = {
        safe_int(row.get('customer_id'))
        for row in improvement_customers
        if safe_int(row.get('customer_id')) is not None
        and str(row.get('improvement_status') or '').strip() in ('明显改善', '部分改善')
    }
    improved_customer_ids &= filled_improvement_customer_ids

    obvious_improved_customer_ids = {
        safe_int(row.get('customer_id'))
        for row in improvement_customers
        if safe_int(row.get('customer_id')) is not None
        and str(row.get('improvement_status') or '').strip() == '明显改善'
    }
    obvious_improved_customer_ids &= improved_customer_ids
    conn.close()

    return jsonify({
        'total_customers': total,
        'abnormal_indicators': [
            {
                'name': '血压异常人数',
                'count': blood_pressure_abnormal_people,
                'ratio': round((blood_pressure_abnormal_people * 100.0 / total), 1) if total else 0,
            },
            {
                'name': '血脂异常人数',
                'count': blood_lipid_abnormal_people,
                'ratio': round((blood_lipid_abnormal_people * 100.0 / total), 1) if total else 0,
            },
            {
                'name': '血糖异常人数',
                'count': blood_sugar_abnormal_people,
                'ratio': round((blood_sugar_abnormal_people * 100.0 / total), 1) if total else 0,
            },
            {
                'name': 'BMI异常人数',
                'count': bmi_abnormal,
                'ratio': round((bmi_abnormal * 100.0 / total), 1) if total else 0,
            },
            {
                'name': '睡眠异常人数',
                'count': sleep_issue_people,
                'ratio': round((sleep_issue_people * 100.0 / total), 1) if total else 0,
            },
        ],
        'dimension1': {
            'cards': {
                'total_people': total,
                'bmi_abnormal_rate': round((bmi_abnormal * 100.0 / total), 1) if total else 0,
                'senior_ratio': round((senior_count * 100.0 / total), 1) if total else 0,
            },
            'gender_distribution': [{'name': k, 'count': v} for k, v in genders.items()],
            'age_distribution': [{'name': k, 'count': age_distribution[k]} for k in age_segments],
            'age_gender_distribution': [
                {
                    'name': bucket,
                    'male': age_gender_distribution[bucket]['男'],
                    'female': age_gender_distribution[bucket]['女'],
                } for bucket in age_gender_buckets
            ],
            'bmi_distribution': [{'name': k, 'count': v} for k, v in bmi_levels.items()],
        },
        'dimension2': {
            'risk_distribution': [{'name': k, 'count': v} for k, v in risks.items()],
            'past_disease_distribution': [{'name': k, 'count': v} for k, v in past_disease_counter.most_common()],
            'family_history_distribution': [{'name': k, 'count': v} for k, v in family_disease_counter.most_common()],
            'recent_symptom_distribution': [{'name': k, 'count': v} for k, v in recent_symptom_counter.most_common()],
            'allergy_top10': [{'name': k, 'count': v} for k, v in allergy_counter.most_common(10)],
            'pain_top10': [{'name': k, 'count': v} for k, v in pain_counter.most_common(10)],
            'family_history_ratio': round((family_history_people * 100.0 / total), 1) if total else 0,
            'allergy_ratio': round((allergy_people * 100.0 / total), 1) if total else 0,
            'chronic_pain_ratio': round((chronic_pain_people * 100.0 / total), 1) if total else 0,
            'dual_history_high_risk_people': dual_history_high_risk_people,
            'history_plus_bp_abnormal_people': history_plus_bp_abnormal_people,
        },
        'high_risk_summary': {
            'low': risks.get('低风险', 0),
            'medium': risks.get('中风险', 0),
            'high': risks.get('高风险', 0),
        },
        'high_risk_customers_top': high_risk_top,
        'dimension3': {
            'smoking_ratio': round((smoking_people * 100.0 / total), 1) if total else 0,
            'drinking_ratio': round((drinking_people * 100.0 / total), 1) if total else 0,
            'smoking_drinking_ratio': round((smoking_drinking_people * 100.0 / total), 1) if total else 0,
            'sleep_abnormal_ratio': round((sleep_abnormal_people * 100.0 / total), 1) if total else 0,
            'poor_sleep_quality_ratio': round((poor_sleep_people * 100.0 / total), 1) if total else 0,
            'low_exercise_bad_habit_people': low_exercise_bad_habit_people,
            'exercise_top10': [{'name': k, 'count': v} for k, v in exercise_counter.most_common(10)],
            'health_needs_top10': [{'name': k, 'count': v} for k, v in demand_counter.most_common(10)],
            'fatigue_distribution': [],
            'behavior_tags': [{'name': k, 'count': v} for k, v in behavior_tag_counter.most_common(20)],
        },
        'dimension4': {
            'improvement_matrix': heatmap_rows,
            'improvement_project_ranking': improvement_project_ranking,
            'service_funnel': [
                {'key': 'archived', 'label': '已建档人数', 'count': len(archived_customer_ids)},
                {'key': 'health_needs', 'label': '有健康需求人数', 'count': len(health_need_customer_ids)},
                {'key': 'booked', 'label': '已预约人数', 'count': len(booked_customer_ids)},
                {'key': 'checked_in', 'label': '已签到人数', 'count': len(checked_in_customer_ids)},
                {'key': 'improvement_filled', 'label': '已填写改善记录人数', 'count': len(filled_improvement_customer_ids)},
                {'key': 'improved', 'label': '有改善人数', 'count': len(improved_customer_ids)},
                {'key': 'significant_improved', 'label': '明显改善人数', 'count': len(obvious_improved_customer_ids)},
            ],
        }
    })


# ========== 导出与下载 ==========
@app.route('/api/export/query-download', methods=['GET'])
def api_export_query_download():
    scope = (request.args.get('scope') or 'single').strip()
    dataset = (request.args.get('dataset') or 'all').strip()
    customer_id = request.args.get('customer_id')

    allowed_datasets = {'all', 'customers', 'health', 'appointments'}
    if scope not in {'single', 'all'}:
        return jsonify({'error': '下载范围参数不合法'}), 400
    if dataset not in allowed_datasets:
        return jsonify({'error': '下载内容参数不合法'}), 400
    if scope == 'single' and not customer_id:
        return jsonify({'error': '请选择客户后下载'}), 400

    conn = get_db()
    try:
        if scope == 'single':
            c = conn.cursor()
            c.execute('SELECT id, name FROM customers WHERE id=? AND is_deleted=0', (customer_id,))
            customer = c.fetchone()
            if not customer:
                return jsonify({'error': '客户不存在'}), 404
            customer_name = customer['name']
            name_prefix = f'single_{customer_name}_{customer_id}'
        else:
            name_prefix = 'all_customers'

        queries = {
            'customers': ('客户档案', 'SELECT * FROM customers {where_clause} ORDER BY created_at DESC'),
            'health': ('健康档案', '''SELECT h.*, c.name as customer_name, c.phone as customer_phone
                FROM health_assessments h JOIN customers c ON h.customer_id=c.id
                {where_clause} ORDER BY h.assessment_date DESC'''),
            'appointments': ('预约记录', '''SELECT a.*, c.name as customer_name, c.phone as customer_phone, e.name as equipment_name
                FROM appointments a JOIN customers c ON a.customer_id=c.id LEFT JOIN equipment e ON a.equipment_id=e.id
                {where_clause} ORDER BY a.appointment_date DESC, a.start_time DESC'''),
        }

        target_keys = list(queries.keys()) if dataset == 'all' else [dataset]
        ts = now_local().strftime('%Y%m%d_%H%M%S')
        fn = f'{name_prefix}_{dataset}_{ts}.xlsx'
        fp = os.path.join(UPLOAD_FOLDER, fn)

        with pd.ExcelWriter(fp, engine='openpyxl') as writer:
            _init_export_workbook(writer)
            for key in target_keys:
                sheet_name, sql_tpl = queries[key]
                if scope == 'single':
                    where_clause = 'WHERE c.id = ?' if key != 'customers' else 'WHERE id = ?'
                    df = pd.read_sql_query(sql_tpl.format(where_clause=where_clause), conn, params=(customer_id,))
                else:
                    where_clause = 'WHERE is_deleted=0' if key == 'customers' else ''
                    df = pd.read_sql_query(sql_tpl.format(where_clause=where_clause), conn)
                cols = EXPORT_COLUMNS_BY_KEY.get('customers' if key == 'customers' else key)
                _write_bilingual_dataframe(writer, sheet_name, df, cols)
    finally:
        conn.close()

    audit_log('导出数据', 'export', customer_id or 'all', f'scope={scope}, dataset={dataset}, file={fn}')
    return jsonify({'filename': fn, 'download_url': '/api/download/' + fn})


def _build_customer_integrated_filter(search_text):
    keyword = (search_text or '').strip()
    where_sql = 'WHERE c.is_deleted=0'
    params = []
    if keyword:
        where_sql += ' AND (c.name LIKE ? OR c.phone LIKE ?)'
        keyword_like = f'%{keyword}%'
        params.extend([keyword_like, keyword_like])
    return where_sql, params


EXPORT_FIELD_ZH = {
    'id': 'ID',
    'name': '姓名',
    'id_card': '身份证号',
    'phone': '手机号',
    'email': '邮箱',
    'address': '地址',
    'gender': '性别',
    'birth_date': '出生日期',
    'medical_history': '病史',
    'allergies': '过敏史',
    'created_at': '创建时间',
    'updated_at': '更新时间',
    'diet_habits': '饮食习惯',
    'chronic_diseases': '慢性疾病',
    'health_status': '健康状态',
    'therapy_contraindications': '理疗禁忌',
    'customer_id': '客户ID',
    'assessment_date': '评估日期',
    'assessor': '评估人',
    'age': '年龄',
    'height_cm': '身高(cm)',
    'weight_kg': '体重(kg)',
    'past_medical_history': '既往病史',
    'family_history': '家族病史',
    'allergy_history': '过敏历史',
    'allergy_details': '过敏详情',
    'smoking_status': '吸烟情况',
    'smoking_years': '吸烟年限',
    'cigarettes_per_day': '日均吸烟量',
    'drinking_status': '饮酒情况',
    'drinking_years': '饮酒年限',
    'fatigue_last_month': '近一个月疲劳',
    'sleep_quality': '睡眠质量',
    'sleep_hours': '睡眠时长',
    'blood_pressure_test': '血压检测',
    'blood_lipid_test': '血脂检测',
    'chronic_pain': '慢性疼痛',
    'pain_details': '疼痛详情',
    'exercise_methods': '锻炼方式',
    'weekly_exercise_freq': '每周锻炼频次',
    'health_needs': '健康需求',
    'notes': '备注',
    'customer_name': '客户姓名',
    'customer_phone': '客户手机号',
    'equipment_id': '设备ID',
    'equipment_name': '设备名称',
    'appointment_date': '预约日期',
    'start_time': '开始时间',
    'end_time': '结束时间',
    'status': '状态',
    'project_id': '项目ID',
    'project_name': '项目名称',
    'staff_id': '人员ID',
    'home_time': '上门时间',
    'home_address': '上门地址',
    'service_project': '服务项目',
    'staff_name': '服务人员',
    'location': '地点',
    'contact_person': '联系人',
    'contact_phone': '联系人电话',
    'has_companion': '是否有家属陪同',
    'service_time': '服务时间',
    'improvement_summary': '改善情况',
    'followup_time': '随访时间',
    'followup_method': '随访方式',
}

EXPORT_COLUMNS_BY_KEY = {
    'basic': ['id', 'name', 'id_card', 'phone', 'email', 'address', 'gender', 'birth_date', 'medical_history', 'allergies', 'created_at', 'updated_at', 'diet_habits', 'chronic_diseases', 'health_status', 'therapy_contraindications'],
    'health': ['id', 'customer_id', 'assessment_date', 'assessor', 'age', 'height_cm', 'weight_kg', 'address', 'past_medical_history', 'family_history', 'allergy_history', 'allergy_details', 'smoking_status', 'smoking_years', 'cigarettes_per_day', 'drinking_status', 'drinking_years', 'fatigue_last_month', 'sleep_quality', 'sleep_hours', 'blood_pressure_test', 'blood_lipid_test', 'chronic_pain', 'pain_details', 'exercise_methods', 'weekly_exercise_freq', 'health_needs', 'notes', 'created_at', 'customer_name', 'customer_phone'],
    'appointments': ['id', 'customer_id', 'equipment_id', 'appointment_date', 'start_time', 'end_time', 'status', 'has_companion', 'notes', 'created_at', 'project_id', 'staff_id', 'updated_at', 'customer_name', 'customer_phone', 'equipment_name', 'project_name'],
    'home_appointments': ['id', 'customer_id', 'project_id', 'staff_id', 'customer_name', 'phone', 'home_time', 'home_address', 'service_project', 'staff_name', 'appointment_date', 'start_time', 'end_time', 'location', 'contact_person', 'contact_phone', 'has_companion', 'notes', 'status', 'created_at', 'updated_at', 'project_name'],
    'improvement': ['id', 'customer_id', 'service_project', 'service_time', 'improvement_summary', 'followup_time', 'followup_method', 'notes', 'created_at', 'updated_at', 'customer_name', 'customer_phone'],
    'customers': ['id', 'name', 'id_card', 'phone', 'email', 'address', 'gender', 'birth_date', 'medical_history', 'allergies', 'created_at', 'updated_at', 'diet_habits', 'chronic_diseases', 'health_status', 'therapy_contraindications'],
}


def _write_bilingual_sheet(writer, sheet_name, rows=None, columns=None):
    data_rows = rows or []
    if columns is None:
        columns = list(data_rows[0].keys()) if data_rows else []
    else:
        merged_columns = list(columns)
        seen = set(merged_columns)
        for row in data_rows:
            for key in row.keys():
                if key not in seen:
                    merged_columns.append(key)
                    seen.add(key)
        columns = merged_columns
    ws = writer.book.create_sheet(title=sheet_name[:31])
    if not columns:
        return
    ws.append(columns)
    ws.append([EXPORT_FIELD_ZH.get(col, col) for col in columns])
    for row in data_rows:
        ws.append([row.get(col) for col in columns])


def _write_bilingual_dataframe(writer, sheet_name, df, columns=None):
    if columns:
        output_columns = list(columns) + [col for col in df.columns if col not in set(columns)]
    else:
        output_columns = list(df.columns)
    if output_columns:
        missing_cols = [col for col in output_columns if col not in df.columns]
        for col in missing_cols:
            df[col] = None
        df = df[output_columns]
    _write_bilingual_sheet(
        writer,
        sheet_name,
        rows=df.to_dict(orient='records'),
        columns=output_columns,
    )


def _init_export_workbook(writer):
    wb = writer.book
    if len(wb.sheetnames) == 1 and wb.sheetnames[0] == 'Sheet':
        std = wb['Sheet']
        wb.remove(std)


def _query_customer_integrated_dataset(cursor, dataset_key, where_sql, params, page, page_size, keyword='', customer_id=None):
    offset = (page - 1) * page_size
    query_map = {
        'basic': {
            'count_sql': f'SELECT COUNT(*) as n FROM customers c {where_sql}',
            'data_sql': f'''
                SELECT c.*
                FROM customers c
                {where_sql}
                ORDER BY c.created_at DESC, c.id DESC
                LIMIT ? OFFSET ?
            ''',
        },
        'health': {
            'count_sql': f'''
                SELECT COUNT(*) as n
                FROM health_assessments h
                JOIN customers c ON h.customer_id=c.id
                {where_sql}
            ''',
            'data_sql': f'''
                SELECT h.*, c.name as customer_name, c.phone as customer_phone
                FROM health_assessments h
                JOIN customers c ON h.customer_id=c.id
                {where_sql}
                ORDER BY h.assessment_date DESC, h.id DESC
                LIMIT ? OFFSET ?
            ''',
        },
        'appointments': {
            'count_sql': f'''
                SELECT COUNT(*) as n
                FROM appointments a
                JOIN customers c ON a.customer_id=c.id
                {where_sql}
            ''',
            'data_sql': f'''
                SELECT a.*, c.name as customer_name, c.phone as customer_phone, e.name as equipment_name, p.name as project_name
                FROM appointments a
                JOIN customers c ON a.customer_id=c.id
                LEFT JOIN equipment e ON a.equipment_id=e.id
                LEFT JOIN therapy_projects p ON a.project_id=p.id
                {where_sql}
                ORDER BY a.appointment_date DESC, a.start_time DESC, a.id DESC
                LIMIT ? OFFSET ?
            ''',
        },
        'home_appointments': {
            'count_sql': '''
                SELECT COUNT(*) as n
                FROM home_appointments h
                LEFT JOIN customers c ON h.customer_id=c.id
                WHERE c.is_deleted=0 {keyword_clause} {customer_clause}
            ''',
            'data_sql': '''
                SELECT
                    h.*,
                    COALESCE(h.customer_name, c.name) AS customer_name,
                    COALESCE(h.service_project, p.name) AS project_name,
                    COALESCE(h.staff_name, s.name) AS staff_name,
                    COALESCE(h.phone, c.phone) AS phone,
                    COALESCE(h.home_address, h.location) AS home_address
                FROM home_appointments h
                LEFT JOIN customers c ON h.customer_id=c.id
                LEFT JOIN therapy_projects p ON h.project_id=p.id
                LEFT JOIN staff s ON h.staff_id=s.id
                WHERE c.is_deleted=0 {keyword_clause} {customer_clause}
                ORDER BY h.appointment_date DESC, h.start_time DESC, h.id DESC
                LIMIT ? OFFSET ?
            ''',
        },
        'improvement': {
            'count_sql': f'''
                SELECT COUNT(*) as n
                FROM service_improvement_records r
                JOIN customers c ON r.customer_id=c.id
                {where_sql}
            ''',
            'data_sql': f'''
                SELECT r.*, c.name as customer_name, c.phone as customer_phone
                FROM service_improvement_records r
                JOIN customers c ON r.customer_id=c.id
                {where_sql}
                ORDER BY r.service_time DESC, r.id DESC
                LIMIT ? OFFSET ?
            ''',
        },
    }
    conf = query_map[dataset_key]
    keyword = (keyword or '').strip()
    if dataset_key == 'home_appointments':
        keyword_clause = ' AND (c.name LIKE ? OR c.phone LIKE ?)' if keyword else ''
        customer_clause = ' AND h.customer_id=?' if customer_id else ''
        home_params = []
        if keyword:
            home_params.extend([f'%{keyword}%', f'%{keyword}%'])
        if customer_id:
            home_params.append(customer_id)
        count_sql = conf['count_sql'].format(keyword_clause=keyword_clause, customer_clause=customer_clause)
        data_sql = conf['data_sql'].format(keyword_clause=keyword_clause, customer_clause=customer_clause)
        cursor.execute(count_sql, home_params)
        total = int(cursor.fetchone()['n'])
        cursor.execute(data_sql, home_params + [page_size, offset])
        rows = row_list(cursor.fetchall())
        return paginate_result(rows, total, page, page_size)

    count_sql = conf['count_sql']
    data_sql = conf['data_sql']
    cursor.execute(count_sql, params)
    total = int(cursor.fetchone()['n'])
    cursor.execute(data_sql, params + [page_size, offset])
    rows = row_list(cursor.fetchall())
    if dataset_key == 'basic':
        rows = [hydrate_customer_age(row) for row in rows]
    return paginate_result(rows, total, page, page_size)


@app.route('/api/customers/integrated-view', methods=['GET'])
def api_customers_integrated_view():
    keyword = (request.args.get('search') or '').strip()
    section_keys = ['basic', 'health', 'appointments', 'home_appointments', 'improvement']
    conn = get_db()
    c = conn.cursor()
    where_sql, params = _build_customer_integrated_filter(keyword)
    data = {'search': keyword}
    for key in section_keys:
        page = max(1, int(request.args.get(f'{key}_page', 1) or 1))
        page_size = min(max(int(request.args.get(f'{key}_page_size', 5) or 5), 1), 100)
        data[key] = _query_customer_integrated_dataset(c, key, where_sql, params, page, page_size, keyword=keyword)
    conn.close()
    return success_response(data)


@app.route('/api/export/customer-integrated-form', methods=['GET'])
def api_export_customer_integrated_form():
    form_key = (request.args.get('form') or 'basic').strip()
    search = (request.args.get('search') or '').strip()
    limit = request.args.get('limit', type=int)
    if form_key not in {'basic', 'health', 'appointments', 'home_appointments', 'improvement'}:
        return error_response('表单类型不合法')
    conn = get_db()
    c = conn.cursor()
    where_sql, params = _build_customer_integrated_filter(search)
    page_size = min(max(limit or 10000, 1), 10000)
    rows = _query_customer_integrated_dataset(c, form_key, where_sql, params, 1, page_size, keyword=search).get('items') or []
    conn.close()
    fn = f'customer_{form_key}_{now_local().strftime("%Y%m%d_%H%M%S")}.xlsx'
    fp = os.path.join(UPLOAD_FOLDER, fn)
    with pd.ExcelWriter(fp, engine='openpyxl') as writer:
        _init_export_workbook(writer)
        _write_bilingual_sheet(writer, '数据导出', rows, EXPORT_COLUMNS_BY_KEY.get(form_key))
    return success_response({'filename': fn, 'download_url': '/api/download/' + fn})


@app.route('/api/export/customer-integrated-all', methods=['GET'])
def api_export_customer_integrated_all():
    scope = (request.args.get('scope') or 'all').strip().lower()
    search = (request.args.get('search') or '').strip()
    if scope not in {'all', 'personal'}:
        return error_response('下载范围不合法')
    if scope == 'personal' and not search:
        return error_response('个人下载时请输入姓名或手机号')

    conn = get_db()
    c = conn.cursor()
    where_sql, params = _build_customer_integrated_filter(search)
    selected_customer_id = None
    if scope == 'personal':
        c.execute(f'SELECT c.id FROM customers c {where_sql} ORDER BY c.id ASC LIMIT 1', params)
        selected = c.fetchone()
        if not selected:
            conn.close()
            return error_response('未找到对应客户')
        selected_customer_id = selected['id']
        where_sql = 'WHERE c.is_deleted=0 AND c.id=?'
        params = [selected_customer_id]

    fn = f'customer_integrated_{scope}_{now_local().strftime("%Y%m%d_%H%M%S")}.xlsx'
    fp = os.path.join(UPLOAD_FOLDER, fn)
    with pd.ExcelWriter(fp, engine='openpyxl') as writer:
        _init_export_workbook(writer)
        for key, sheet_name in [
            ('basic', '基础信息'),
            ('health', '健康档案'),
            ('appointments', '预约服务记录'),
            ('home_appointments', '上门预约记录'),
            ('improvement', '健康改善记录'),
        ]:
            rows = _query_customer_integrated_dataset(
                c,
                key,
                where_sql,
                params,
                1,
                10000,
                keyword=search if scope == 'all' else '',
                customer_id=selected_customer_id,
            ).get('items') or []
            _write_bilingual_sheet(writer, sheet_name, rows, EXPORT_COLUMNS_BY_KEY.get(key))
    conn.close()
    return success_response({'filename': fn, 'download_url': '/api/download/' + fn})


@app.route('/api/export/customers', methods=['GET'])
def api_export_customers():
    conn = get_db()
    df = pd.read_sql_query('SELECT * FROM customers WHERE is_deleted=0 ORDER BY created_at DESC', conn)
    conn.close()
    fn = 'customers_%s.xlsx' % now_local().strftime('%Y%m%d_%H%M%S')
    fp = os.path.join(UPLOAD_FOLDER, fn)
    with pd.ExcelWriter(fp, engine='openpyxl') as writer:
        _init_export_workbook(writer)
        _write_bilingual_dataframe(writer, '客户列表', df, EXPORT_COLUMNS_BY_KEY.get('customers'))
    audit_log('导出数据', 'export', 'customers', f'file={fn}')
    return jsonify({'filename': fn, 'download_url': '/api/download/' + fn})


@app.route('/api/export/appointments', methods=['GET'])
def api_export_appointments():
    conn = get_db()
    df = pd.read_sql_query('''SELECT a.id, c.name as customer_name, c.phone, e.name as equipment_name, a.appointment_date, a.start_time, a.end_time, a.status, a.notes
        FROM appointments a JOIN customers c ON a.customer_id=c.id LEFT JOIN equipment e ON a.equipment_id=e.id ORDER BY a.appointment_date DESC''', conn)
    conn.close()
    fn = 'appointments_%s.xlsx' % now_local().strftime('%Y%m%d_%H%M%S')
    fp = os.path.join(UPLOAD_FOLDER, fn)
    with pd.ExcelWriter(fp, engine='openpyxl') as writer:
        _init_export_workbook(writer)
        _write_bilingual_dataframe(writer, '预约记录', df, list(df.columns))
    audit_log('导出数据', 'export', 'appointments', f'file={fn}')
    return jsonify({'filename': fn, 'download_url': '/api/download/' + fn})


@app.route('/api/system/backup-path', methods=['GET'])
def api_system_backup_path_get():
    path = get_backup_directory()
    return jsonify({'backup_directory': path})


@app.route('/api/system/backup-path', methods=['POST'])
def api_system_backup_path_set():
    body = request.get_json(silent=True) or {}
    backup_directory = (body.get('backup_directory') or '').strip()
    if not backup_directory:
        return jsonify({'error': '请先选择备份路径'}), 400

    backup_directory = os.path.abspath(os.path.expanduser(backup_directory))
    try:
        os.makedirs(backup_directory, exist_ok=True)
    except Exception as e:
        return jsonify({'error': f'备份路径不可用: {e}'}), 400

    set_setting_value('backup_directory', backup_directory)
    return jsonify({'message': '备份路径已保存', 'backup_directory': backup_directory})


@app.route('/api/system/backup-path/select', methods=['POST'])
def api_system_backup_path_select():
    if tk is None or filedialog is None:
        return jsonify({'error': '当前环境不支持本地路径选择框，请手动输入路径'}), 400
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        selected = filedialog.askdirectory(title='请选择数据库备份路径')
        root.destroy()
    except Exception as e:
        return jsonify({'error': f'打开路径选择框失败: {e}'}), 500

    if not selected:
        return jsonify({'error': '未选择路径'}), 400

    backup_directory = os.path.abspath(os.path.expanduser(selected))
    try:
        os.makedirs(backup_directory, exist_ok=True)
    except Exception as e:
        return jsonify({'error': f'备份路径不可用: {e}'}), 400

    set_setting_value('backup_directory', backup_directory)
    return jsonify({'message': '备份路径已更新', 'backup_directory': backup_directory})


@app.route('/api/system/backup', methods=['POST'])
def api_system_backup():
    body = request.get_json(silent=True) or {}
    backup_directory = (body.get('backup_directory') or '').strip()
    if backup_directory:
        backup_directory = os.path.abspath(os.path.expanduser(backup_directory))
        try:
            os.makedirs(backup_directory, exist_ok=True)
        except Exception as e:
            return jsonify({'error': f'备份路径不可用: {e}'}), 400
        set_setting_value('backup_directory', backup_directory)

    result = create_db_backup(backup_type='manual')
    if result.get('status') == 'success':
        audit_log('备份数据库', 'system', result.get('filename'), result.get('backup_file'))
    code = 200 if result.get('status') == 'success' else 500
    return jsonify(result), code


@app.route('/api/system/backups', methods=['GET'])
def api_system_backups():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM db_backups ORDER BY backup_time DESC, id DESC LIMIT 200')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/system/restore', methods=['POST'])
def api_system_restore():
    body = request.get_json(silent=True) or {}
    backup_file = (body.get('backup_file') or '').strip()
    if not backup_file:
        return jsonify({'error': '请选择要恢复的备份文件'}), 400

    result = restore_db_from_backup(backup_file)
    if result.get('status') == 'success':
        audit_log('恢复数据库', 'system', backup_file, 'restore success')
        return jsonify({
            'status': 'success',
            'message': '恢复成功，请重启系统以确保所有模块使用最新数据',
            'need_restart': True,
        })
    return jsonify(result), 500


@app.route('/api/download/<filename>', methods=['GET'])
def api_download(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)


if __name__ == '__main__':
    ensure_secret_key_configured()
    init_db()
    print('请在浏览器打开: http://localhost:5000')
    app.run(host='127.0.0.1', port=5000, debug=False)
