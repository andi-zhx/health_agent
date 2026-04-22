"""
医疗客户与健康档案管理系统 - 单机版
仅需 Python：运行后浏览器访问 http://localhost:5000
数据存于 medical_system.db，无 Node/npm 依赖
"""

from flask import request, jsonify, send_from_directory, session
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
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

def ensure_secret_key_configured(app):
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


def register_core_hooks(app):
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
        ensure_secret_key_configured(app)

    app.before_request(require_login)
    app.after_request(normalize_api_response)
    app.register_error_handler(RequestEntityTooLarge, handle_file_too_large)


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


def ensure_query_indexes(cursor):
    """为核心查询场景补充必要索引，并清理已知历史重复索引。"""
    # 历史版本可能存在命名不规范但列相同的索引，先做幂等清理。
    legacy_indexes = [
        'idx_ha_customer_date',
        'idx_appointments_customer_date',
        'idx_appointments_equipment_date',
        'idx_home_appointments_customer_date',
        'idx_home_appointments_staff_date',
        'idx_improvement_customer_time',
        'idx_improvement_project_status',
        'idx_audit_created_at',
        'idx_audit_operator_time',
    ]
    for index_name in legacy_indexes:
        cursor.execute(f'DROP INDEX IF EXISTS {index_name}')

    # 1) 健康评估：按 customer_id + assessment_date 取最新。
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_health_assessments_customer_date_id
        ON health_assessments(customer_id, assessment_date DESC, id DESC)
        '''
    )

    # 2) 门店预约：冲突校验（客户/设备 + 日期 + 状态 + 时间重叠）。
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_appointments_conflict_customer
        ON appointments(customer_id, appointment_date, status, start_time, end_time)
        '''
    )
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_appointments_conflict_equipment
        ON appointments(equipment_id, appointment_date, status, start_time, end_time)
        WHERE equipment_id IS NOT NULL
        '''
    )

    # 3) 门店预约：列表分页与日期筛选（含按时间倒序）。
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_appointments_list_date_time
        ON appointments(appointment_date DESC, start_time DESC, id DESC)
        '''
    )
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_appointments_status_customer
        ON appointments(status, customer_id)
        '''
    )
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_appointments_checkin_customer
        ON appointments(checkin_status, customer_id)
        '''
    )

    # 4) 上门预约：冲突校验（客户/人员 + 日期 + 状态 + 时间重叠）。
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_home_appointments_conflict_customer
        ON home_appointments(customer_id, appointment_date, status, start_time, end_time)
        '''
    )
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_home_appointments_conflict_staff
        ON home_appointments(staff_id, appointment_date, status, start_time, end_time)
        WHERE staff_id IS NOT NULL
        '''
    )

    # 5) 上门预约：列表分页与日期筛选。
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_home_appointments_list_date_time
        ON home_appointments(appointment_date DESC, start_time DESC, id DESC)
        '''
    )
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_home_appointments_status_customer
        ON home_appointments(status, customer_id)
        '''
    )
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_home_appointments_checkin_customer
        ON home_appointments(checkin_status, customer_id)
        '''
    )

    # 6) 改善记录：按客户、项目、状态、服务时间查询与列表排序。
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_improvement_records_customer_time
        ON service_improvement_records(customer_id, service_time DESC, id DESC)
        '''
    )
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_improvement_records_project_status_time
        ON service_improvement_records(service_project, improvement_status, service_time DESC, id DESC)
        '''
    )
    # pending-fill 的 NOT EXISTS 关联键。
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_improvement_records_service_ref
        ON service_improvement_records(service_type, service_id)
        WHERE service_id IS NOT NULL
        '''
    )

    # 7) 审计日志：时间范围、操作人筛选 + 时间倒序分页。
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_audit_logs_created_id
        ON audit_logs(created_at DESC, id DESC)
        '''
    )
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_audit_logs_username_created
        ON audit_logs(username, created_at DESC, id DESC)
        '''
    )


def normalize_appointment_status_data(cursor, table_name):
    cursor.execute(f"UPDATE {table_name} SET status='scheduled' WHERE LOWER(COALESCE(status,'')) NOT IN ('scheduled','cancelled','completed')")
    cursor.execute(f"UPDATE {table_name} SET checkin_status='pending' WHERE LOWER(COALESCE(status,''))='scheduled' AND LOWER(COALESCE(checkin_status,'')) IN ('', 'none')")
    cursor.execute(f"UPDATE {table_name} SET checkin_status='none' WHERE LOWER(COALESCE(status,''))='cancelled'")
    cursor.execute(
        f"""
        UPDATE {table_name}
        SET status='scheduled'
        WHERE LOWER(COALESCE(status,''))='completed'
          AND LOWER(COALESCE(checkin_status,''))='no_show'
        """
    )
    cursor.execute(
        f"""
        UPDATE {table_name}
        SET checkin_status='checked_in'
        WHERE LOWER(COALESCE(status,''))='completed'
          AND LOWER(COALESCE(checkin_status,'')) IN ('', 'pending', 'none')
        """
    )
    cursor.execute(
        f"""
        UPDATE {table_name}
        SET checkin_status='pending'
        WHERE LOWER(COALESCE(checkin_status,'')) NOT IN ('pending','checked_in','no_show','none')
          AND LOWER(COALESCE(status,'')) IN ('scheduled','completed')
        """
    )


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


def migrate_service_improvement_service_type_values(cursor):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='service_improvement_records'")
    if not cursor.fetchone():
        return
    cursor.execute(
        '''
        UPDATE service_improvement_records
        SET service_type = CASE
            WHEN LOWER(TRIM(COALESCE(service_type, ''))) IN ('appointments', 'appointment') THEN 'appointments'
            WHEN LOWER(TRIM(COALESCE(service_type, ''))) IN ('home_appointments', 'home') THEN 'home_appointments'
            ELSE 'appointments'
        END
        '''
    )


def migrate_customers_drop_email(cursor):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customers'")
    if not cursor.fetchone():
        return
    cursor.execute('PRAGMA table_info(customers)')
    columns = [row[1] for row in cursor.fetchall()]
    column_set = set(columns)
    if 'email' not in columns:
        return
    try:
        cursor.execute('ALTER TABLE customers DROP COLUMN email')
        return
    except sqlite3.OperationalError:
        # 兼容不支持 DROP COLUMN 的 SQLite 版本，回退为重建表方案
        pass
    cursor.execute('DROP TABLE IF EXISTS customers_new')
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS customers_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            id_card TEXT UNIQUE,
            phone TEXT NOT NULL,
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
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now','localtime')),
            is_deleted INTEGER DEFAULT 0
        )
        '''
    )
    def _value_or_default(column_name, default_sql='NULL'):
        return column_name if column_name in column_set else default_sql

    cursor.execute('PRAGMA foreign_keys')
    foreign_keys_enabled = cursor.fetchone()[0]
    try:
        if foreign_keys_enabled:
            cursor.execute('PRAGMA foreign_keys=OFF')
        cursor.execute(
            f'''
            INSERT INTO customers_new (
                id, name, id_card, phone, address, gender, age, birth_date, identity_type, military_rank,
                record_creator, medical_history, allergies, diet_habits, chronic_diseases, health_status,
                therapy_contraindications, created_at, updated_at, is_deleted
            )
            SELECT
                id,
                name,
                id_card,
                phone,
                {_value_or_default('address')},
                {_value_or_default('gender')},
                {_value_or_default('age')},
                {_value_or_default('birth_date')},
                {_value_or_default('identity_type')},
                {_value_or_default('military_rank')},
                {_value_or_default('record_creator')},
                {_value_or_default('medical_history')},
                {_value_or_default('allergies')},
                {_value_or_default('diet_habits')},
                {_value_or_default('chronic_diseases')},
                {_value_or_default('health_status')},
                {_value_or_default('therapy_contraindications')},
                {_value_or_default('created_at', "strftime('%Y-%m-%d %H:%M:%S','now','localtime')")},
                {_value_or_default('updated_at', "strftime('%Y-%m-%d %H:%M:%S','now','localtime')")},
                {_value_or_default('is_deleted', '0')}
            FROM customers
            '''
        )
        cursor.execute('DROP TABLE customers')
        cursor.execute('ALTER TABLE customers_new RENAME TO customers')
    finally:
        if foreign_keys_enabled:
            cursor.execute('PRAGMA foreign_keys=ON')


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
    cursor.execute('DROP TABLE IF EXISTS appointments_new')

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


def require_login():
    if not request.path.startswith('/api/'):
        return None
    if request.path in PUBLIC_API_PATHS:
        return None
    if not session.get('logged_in'):
        return jsonify({'error': '未登录或登录已失效'}), 401
    return None


def infer_error_code_by_status(status_code):
    if status_code == 400:
        return 'VALIDATION_ERROR'
    if status_code == 401:
        return 'UNAUTHORIZED'
    if status_code == 403:
        return 'FORBIDDEN'
    if status_code == 404:
        return 'NOT_FOUND'
    if status_code == 413:
        return 'FILE_TOO_LARGE'
    if status_code >= 500:
        return 'SERVER_ERROR'
    return 'REQUEST_FAILED'


def normalize_api_response(response):
    if not request.path.startswith('/api/'):
        return response
    if response.direct_passthrough or not response.is_json:
        return response

    payload = response.get_json(silent=True)
    if payload is None:
        return response

    status_code = response.status_code or 200

    if status_code >= 400:
        if isinstance(payload, dict) and payload.get('success') is False:
            normalized = dict(payload)
            normalized.setdefault('message', '请求失败')
            normalized.setdefault('error_code', infer_error_code_by_status(status_code))
        else:
            message = '请求失败'
            error_code = infer_error_code_by_status(status_code)
            if isinstance(payload, dict):
                message = str(payload.get('message') or payload.get('error') or message)
                error_code = str(payload.get('error_code') or error_code)
            elif isinstance(payload, str) and payload.strip():
                message = payload.strip()
            normalized = {'success': False, 'message': message, 'error_code': error_code}
        response = jsonify(normalized)
        response.status_code = status_code
        return response

    if isinstance(payload, dict) and payload.get('success') is True:
        normalized = dict(payload)
        if 'data' not in normalized:
            normalized['data'] = {}
        response = jsonify(normalized)
        response.status_code = status_code
        return response

    message = '操作成功'
    data = payload
    if isinstance(payload, dict):
        message = str(payload.get('message') or message)
        data = {k: v for k, v in payload.items() if k != 'message'}
    normalized = {'success': True, 'message': message, 'data': data if data is not None else {}}
    response = jsonify(normalized)
    response.status_code = status_code
    return response


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
IMPROVEMENT_SERVICE_TYPE_OPTIONS = ('appointments', 'home_appointments')
IMPROVEMENT_SERVICE_TYPE_ALIASES = {
    'appointment': 'appointments',
    'appointments': 'appointments',
    'home': 'home_appointments',
    'home_appointments': 'home_appointments',
}
ALLOWED_IMPROVEMENT_FILE_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
ALLOWED_IMPROVEMENT_MIME_TYPES = {
    'pdf': {'application/pdf', 'application/x-pdf'},
    'png': {'image/png', 'image/x-png'},
    'jpg': {'image/jpeg', 'image/pjpeg', 'image/jpg'},
    'jpeg': {'image/jpeg', 'image/pjpeg', 'image/jpg'},
}


def normalize_improvement_service_type(service_type, default='appointments'):
    raw = str(service_type or '').strip().lower()
    if not raw:
        raw = default
    normalized = IMPROVEMENT_SERVICE_TYPE_ALIASES.get(raw)
    return normalized if normalized in IMPROVEMENT_SERVICE_TYPE_OPTIONS else None


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


def fetch_latest_health_assessments(cursor, date_from='', date_to=''):
    date_from = str(date_from or '').strip()
    date_to = str(date_to or '').strip()
    filter_clause = '''
        WHERE (? = '' OR h.assessment_date >= ?)
          AND (? = '' OR h.assessment_date <= ?)
    '''
    params = [date_from, date_from, date_to, date_to]
    window_sql = '''
        SELECT latest_h.*
        FROM (
            SELECT h.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY h.customer_id
                       ORDER BY h.assessment_date DESC, h.id DESC
                   ) AS row_no
            FROM health_assessments h
            {filter_clause}
        ) latest_h
        WHERE latest_h.row_no = 1
        ORDER BY latest_h.customer_id ASC
    '''.format(filter_clause=filter_clause)
    fallback_sql = '''
        SELECT h.*
        FROM health_assessments h
        {filter_clause}
          AND NOT EXISTS (
            SELECT 1
            FROM health_assessments newer
            WHERE newer.customer_id = h.customer_id
              AND (? = '' OR newer.assessment_date >= ?)
              AND (? = '' OR newer.assessment_date <= ?)
              AND (
                    newer.assessment_date > h.assessment_date
                 OR (newer.assessment_date = h.assessment_date AND newer.id > h.id)
              )
        )
        ORDER BY h.customer_id ASC
    '''.format(filter_clause=filter_clause)
    try:
        cursor.execute(window_sql, params)
    except sqlite3.OperationalError:
        cursor.execute(fallback_sql, params + params)
    return row_list(cursor.fetchall())


def build_health_portrait_sample_records(cursor, date_from='', date_to=''):
    latest_rows = fetch_latest_health_assessments(cursor, date_from=date_from, date_to=date_to)
    records = []
    customer_ids = [safe_int(row.get('customer_id')) for row in latest_rows if safe_int(row.get('customer_id')) is not None]
    customer_map = {}
    if customer_ids:
        placeholders = ','.join('?' for _ in customer_ids)
        cursor.execute(
            f'''
            SELECT id, name, gender, birth_date, phone, chronic_diseases, medical_history
            FROM customers
            WHERE id IN ({placeholders})
            ''',
            customer_ids,
        )
        customer_map = {safe_int(item['id']): dict(item) for item in cursor.fetchall()}
    for row in latest_rows:
        customer_id = safe_int(row.get('customer_id'))
        if customer_id is None or customer_id not in customer_map:
            continue
        customer_row = customer_map[customer_id]
        merged = dict(row)
        merged.update({
            'customer_name': customer_row.get('name'),
            'name': customer_row.get('name'),
            'gender': customer_row.get('gender'),
            'birth_date': customer_row.get('birth_date'),
            'phone': customer_row.get('phone'),
            'chronic_diseases': customer_row.get('chronic_diseases'),
            'medical_history': customer_row.get('medical_history'),
            'latest_assessment_date': row.get('assessment_date'),
        })
        records.append(merged)
    records.sort(key=lambda r: (safe_int(r.get('customer_id')) or 0, safe_int(r.get('id')) or 0), reverse=True)
    return records


def resolve_portrait_trend_period(period, date_from='', date_to=''):
    mode = str(period or '').strip().lower()
    if mode in ('week', 'month'):
        return mode, False
    if date_from and date_to:
        try:
            start = datetime.strptime(date_from, '%Y-%m-%d').date()
            end = datetime.strptime(date_to, '%Y-%m-%d').date()
            span_days = (end - start).days + 1
            return ('week' if span_days <= 120 else 'month'), True
        except ValueError:
            pass
    return 'month', True


def compute_period_key_and_label(date_text, period_mode):
    raw = str(date_text or '').strip()
    if not raw:
        return None, None
    try:
        day = datetime.strptime(raw[:10], '%Y-%m-%d').date()
    except ValueError:
        return None, None
    if period_mode == 'week':
        week_start = day - timedelta(days=day.weekday())
        week_end = week_start + timedelta(days=6)
        return week_start.strftime('%Y-%m-%d'), f'{week_start.strftime("%Y-%m-%d")}~{week_end.strftime("%Y-%m-%d")}'
    month_key = day.strftime('%Y-%m')
    return month_key, month_key


def build_health_portrait_trends(cursor, date_from='', date_to='', period='auto'):
    period_mode, period_auto_selected = resolve_portrait_trend_period(period, date_from=date_from, date_to=date_to)
    where_clauses = []
    params = []
    if date_from:
        where_clauses.append('assessment_date >= ?')
        params.append(date_from)
    if date_to:
        where_clauses.append('assessment_date <= ?')
        params.append(date_to)
    where_sql = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''
    cursor.execute(
        f'''
        SELECT *
        FROM health_assessments
        {where_sql}
        ORDER BY assessment_date DESC, id DESC
        ''',
        params,
    )
    assessment_rows = row_list(cursor.fetchall())
    dedup_rows = {}
    for row in assessment_rows:
        customer_id = safe_int(row.get('customer_id'))
        period_key, period_label = compute_period_key_and_label(row.get('assessment_date'), period_mode)
        if customer_id is None or not period_key:
            continue
        dedup_key = (period_key, customer_id)
        if dedup_key in dedup_rows:
            continue
        copied = dict(row)
        copied['period_key'] = period_key
        copied['period_label'] = period_label
        dedup_rows[dedup_key] = copied

    period_buckets = {}
    need_counters = {}
    for row in dedup_rows.values():
        period_key = row.get('period_key')
        period_label = row.get('period_label')
        bucket = period_buckets.setdefault(period_key, {
            'period_key': period_key,
            'period_label': period_label,
            'sample_size': 0,
            'high_risk_people': 0,
            'blood_pressure_abnormal_people': 0,
            'blood_sugar_abnormal_people': 0,
            'sleep_abnormal_people': 0,
        })
        bucket['sample_size'] += 1
        blood_pressure_test = str(row.get('blood_pressure_test') or '')
        blood_sugar_test = str(row.get('blood_sugar_test') or '')
        sleep_hours_text = str(row.get('sleep_hours') or '')
        sleep_quality_text = str(row.get('sleep_quality') or '')
        if ('偏高' in blood_pressure_test) or ('偏低' in blood_pressure_test):
            bucket['blood_pressure_abnormal_people'] += 1
        if ('偏高' in blood_sugar_test) or ('偏低' in blood_sugar_test):
            bucket['blood_sugar_abnormal_people'] += 1
        if (sleep_hours_text in ('<6小时', '>10小时')) or (sleep_quality_text in ('很差', '差')):
            bucket['sleep_abnormal_people'] += 1
        if (calculate_lightweight_risk(row) or {}).get('risk_level') == '高风险':
            bucket['high_risk_people'] += 1
        counter = need_counters.setdefault(period_key, Counter())
        for tag in normalize_multi_text(row.get('health_needs')):
            if tag != '无':
                counter[tag] += 1

    sorted_periods = sorted(period_buckets.values(), key=lambda item: item.get('period_key') or '')
    period_keys = [item.get('period_key') for item in sorted_periods]
    needs_total_counter = Counter()
    for period_key in period_keys:
        needs_total_counter.update(need_counters.get(period_key, Counter()))
    top_need_tags = [name for name, _count in needs_total_counter.most_common(5)]

    def build_metric_series(metric_key):
        return [{
            'period_key': item['period_key'],
            'period_label': item['period_label'],
            'value': safe_int(item.get(metric_key)) or 0,
            'sample_size': safe_int(item.get('sample_size')) or 0,
        } for item in sorted_periods]

    health_need_top_trends = []
    for tag in top_need_tags:
        series = []
        for item in sorted_periods:
            period_key = item['period_key']
            period_counter = need_counters.get(period_key, Counter())
            series.append({
                'period_key': period_key,
                'period_label': item['period_label'],
                'count': safe_int(period_counter.get(tag)) or 0,
            })
        health_need_top_trends.append({'tag': tag, 'series': series})

    where_clauses = []
    improvement_params = []
    if date_from:
        where_clauses.append("date(r.service_time) >= ?")
        improvement_params.append(date_from)
    if date_to:
        where_clauses.append("date(r.service_time) <= ?")
        improvement_params.append(date_to)
    where_sql = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''
    cursor.execute(
        f'''
        SELECT r.service_project, r.service_time, r.improvement_status
        FROM service_improvement_records r
        {where_sql}
        ORDER BY r.service_time ASC, r.id ASC
        ''',
        improvement_params,
    )
    improvement_rows = row_list(cursor.fetchall())
    improvement_counter = {}
    project_total_counter = Counter()
    for row in improvement_rows:
        period_key, period_label = compute_period_key_and_label(row.get('service_time'), period_mode)
        if not period_key:
            continue
        project = str(row.get('service_project') or '').strip() or '未标注项目'
        project_total_counter[project] += 1
        project_bucket = improvement_counter.setdefault((period_key, project), {
            'period_key': period_key,
            'period_label': period_label,
            'service_project': project,
            'total_services': 0,
            'improved_services': 0,
        })
        project_bucket['total_services'] += 1
        if str(row.get('improvement_status') or '').strip() in ('明显改善', '部分改善'):
            project_bucket['improved_services'] += 1

    top_projects = [name for name, _count in project_total_counter.most_common(5)]
    improvement_rate_trends = []
    for project in top_projects:
        series = []
        for item in sorted_periods:
            period_key = item['period_key']
            stat = improvement_counter.get((period_key, project), {})
            total_services = safe_int(stat.get('total_services')) or 0
            improved_services = safe_int(stat.get('improved_services')) or 0
            rate = round((improved_services * 100.0 / total_services), 1) if total_services else 0
            series.append({
                'period_key': period_key,
                'period_label': item['period_label'],
                'total_services': total_services,
                'improved_services': improved_services,
                'improvement_rate_percent': rate,
            })
        improvement_rate_trends.append({'service_project': project, 'series': series})

    sample_sizes = [safe_int(item.get('sample_size')) or 0 for item in sorted_periods]
    insufficient_data = len(sorted_periods) < 2 or max(sample_sizes or [0]) < 5
    return {
        'period': period_mode,
        'period_auto_selected': period_auto_selected,
        'sampling_note': '同一客户在同一统计周期仅取最新一条健康评估记录。',
        'period_points': [{'period_key': item['period_key'], 'period_label': item['period_label']} for item in sorted_periods],
        'sample_size_series': [
            {'period_key': item['period_key'], 'period_label': item['period_label'], 'sample_size': safe_int(item.get('sample_size')) or 0}
            for item in sorted_periods
        ],
        'metrics': {
            'high_risk_people_trend': build_metric_series('high_risk_people'),
            'blood_pressure_abnormal_people_trend': build_metric_series('blood_pressure_abnormal_people'),
            'blood_sugar_abnormal_people_trend': build_metric_series('blood_sugar_abnormal_people'),
            'sleep_abnormal_people_trend': build_metric_series('sleep_abnormal_people'),
            'health_need_top_tag_trends': health_need_top_trends,
            'service_improvement_rate_trends': improvement_rate_trends,
        },
        'insufficient_data': insufficient_data,
        'insufficient_data_message': '当前样本不足以形成趋势' if insufficient_data else '',
    }


def validate_improvement_payload(d, cursor=None):
    required_fields = ('customer_id', 'service_time', 'service_project', 'improvement_status')
    if not all(str(d.get(k) or '').strip() for k in required_fields):
        return '缺少必填字段'
    if normalize_improvement_service_type(d.get('service_type') or 'appointments') is None:
        return 'service_type 不合法'
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


LIGHTWEIGHT_RISK_CONFIG = {
    'thresholds': {
        'high': 9,
        'medium': 5,
    },
    'defaults': {
        'symptom_count_threshold': 2,
    },
    'weights': {
        'age': 1,
        'vital_signs': 1,
        'behavior': 1,
        'symptoms': 1,
        'family_history': 1,
    },
    'rules': {
        'age': [
            {'id': 'age_over_70', 'label': '年龄≥70', 'weight': 2},
        ],
        'vital_signs': [
            {'id': 'bmi_obesity', 'label': 'BMI肥胖', 'weight': 3},
            {'id': 'bmi_overweight', 'label': 'BMI超重', 'weight': 2},
            {'id': 'blood_pressure_abnormal', 'label': '血压异常', 'weight': 3},
            {'id': 'blood_sugar_abnormal', 'label': '血糖异常', 'weight': 3},
            {'id': 'blood_lipid_abnormal', 'label': '血脂异常', 'weight': 2},
        ],
        'behavior': [
            {'id': 'sleep_poor', 'label': '睡眠差', 'weight': 2},
            {'id': 'smoking', 'label': '吸烟', 'weight': 2},
            {'id': 'drinking', 'label': '饮酒', 'weight': 1},
        ],
        'symptoms': [
            {'id': 'recent_symptoms_many', 'label': '近期症状较多', 'weight': 2},
        ],
        'family_history': [
            {'id': 'family_history_positive', 'label': '家族史阳性', 'weight': 2},
        ],
    },
}


LIGHTWEIGHT_RISK_INTERVENTIONS = {
    'age_over_70': '提升老年综合健康管理频次',
    'bmi_obesity': '营养+运动联合体重管理',
    'bmi_overweight': '开展饮食与运动减重指导',
    'blood_pressure_abnormal': '优先血压复测与慢病随访',
    'blood_sugar_abnormal': '尽快进行血糖复测与代谢评估',
    'blood_lipid_abnormal': '安排血脂复检与饮食干预',
    'sleep_poor': '开展睡眠评估与作息干预',
    'smoking': '启动戒烟干预与行为随访',
    'drinking': '建议限酒并进行生活方式指导',
    'recent_symptoms_many': '安排综合评估与重点症状排查',
    'family_history_positive': '强化家族史相关专项筛查',
}


def build_lightweight_risk_items(row, age, bmi_level, recent_symptom_items, family_history_items):
    config = LIGHTWEIGHT_RISK_CONFIG
    grouped_items = []

    if age is not None and age >= 70:
        grouped_items.append({'group': 'age', **config['rules']['age'][0]})

    if bmi_level == '肥胖':
        grouped_items.append({'group': 'vital_signs', **config['rules']['vital_signs'][0]})
    elif bmi_level == '超重':
        grouped_items.append({'group': 'vital_signs', **config['rules']['vital_signs'][1]})

    blood_pressure_test = str(row.get('blood_pressure_test') or '')
    if is_indicator_abnormal(blood_pressure_test):
        grouped_items.append({'group': 'vital_signs', **config['rules']['vital_signs'][2]})

    blood_sugar_test = str(row.get('blood_sugar_test') or '')
    if is_indicator_abnormal(blood_sugar_test):
        grouped_items.append({'group': 'vital_signs', **config['rules']['vital_signs'][3]})

    blood_lipid_test = str(row.get('blood_lipid_test') or '')
    if '偏高' in blood_lipid_test:
        grouped_items.append({'group': 'vital_signs', **config['rules']['vital_signs'][4]})

    if str(row.get('sleep_quality') or '') in ('很差', '差'):
        grouped_items.append({'group': 'behavior', **config['rules']['behavior'][0]})
    if row.get('smoking_status') == '有':
        grouped_items.append({'group': 'behavior', **config['rules']['behavior'][1]})
    if row.get('drinking_status') == '有':
        grouped_items.append({'group': 'behavior', **config['rules']['behavior'][2]})

    if len(recent_symptom_items) >= config['defaults']['symptom_count_threshold']:
        grouped_items.append({'group': 'symptoms', **config['rules']['symptoms'][0]})

    if family_history_items:
        grouped_items.append({'group': 'family_history', **config['rules']['family_history'][0]})

    return grouped_items


def calculate_lightweight_risk(row):
    age = safe_int(row.get('age'))
    if age is None and row.get('birth_date'):
        try:
            birth = datetime.strptime(str(row.get('birth_date'))[:10], '%Y-%m-%d').date()
            today = now_local().date()
            age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        except Exception:
            age = None

    bmi_value, bmi_level = classify_bmi(row.get('height_cm'), row.get('weight_kg'))

    family_history_items = normalize_multi_text(row.get('family_history'))
    recent_symptom_items = normalize_multi_text(row.get('recent_symptoms'))
    risk_items = build_lightweight_risk_items(
        row=row,
        age=age,
        bmi_level=bmi_level,
        recent_symptom_items=recent_symptom_items,
        family_history_items=family_history_items,
    )

    group_weights = LIGHTWEIGHT_RISK_CONFIG['weights']
    score = sum(item['weight'] * group_weights.get(item['group'], 1) for item in risk_items)
    reasons = [item['label'] for item in risk_items]

    high_threshold = LIGHTWEIGHT_RISK_CONFIG['thresholds']['high']
    medium_threshold = LIGHTWEIGHT_RISK_CONFIG['thresholds']['medium']
    if score >= high_threshold:
        level = '高风险'
    elif score >= medium_threshold:
        level = '中风险'
    else:
        level = '低风险'

    ranked_items = sorted(
        risk_items,
        key=lambda item: (
            -(item['weight'] * group_weights.get(item['group'], 1)),
            str(item.get('label') or '')
        )
    )
    intervention_suggestions = []
    seen_suggestions = set()
    for item in ranked_items:
        suggestion = LIGHTWEIGHT_RISK_INTERVENTIONS.get(item['id'])
        if suggestion and suggestion not in seen_suggestions:
            seen_suggestions.add(suggestion)
            intervention_suggestions.append(suggestion)
    if not intervention_suggestions:
        intervention_suggestions.append('保持常规健康随访')

    return {
        'risk_score': score,
        'risk_level': level,
        'risk_reasons': reasons,
        'recommended_intervention': '；'.join(intervention_suggestions[:3]),
        'risk_reason_count': len(risk_items),
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
    migrate_customers_drop_email(c)

    c.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            id_card TEXT UNIQUE,
            phone TEXT NOT NULL,
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
    normalize_appointment_status_data(c, 'appointments')

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
    normalize_appointment_status_data(c, 'home_appointments')

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
    migrate_service_improvement_service_type_values(c)

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
    ensure_query_indexes(c)

    conn.commit()
    conn.close()
    print('数据库初始化完成，数据文件: %s' % DB_PATH)


# ========== 静态页面 ==========
