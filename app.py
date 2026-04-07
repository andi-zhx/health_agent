"""
医疗客户与健康档案管理系统 - 单机版
仅需 Python：运行后浏览器访问 http://localhost:5000
数据存于 medical_system.db，无 Node/npm 依赖
"""

from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import os
import pandas as pd
import json
import shutil
import logging
from datetime import datetime
from datetime import timedelta

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    tk = None
    filedialog = None

# 项目根目录（app.py 所在目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'))

DB_PATH = os.path.join(BASE_DIR, 'medical_system.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'exports')
BACKUP_FOLDER = os.path.join(BASE_DIR, 'database_backups')
LOG_FOLDER = os.path.join(BASE_DIR, 'logs')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(LOG_FOLDER, 'app.log'),
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn


def row_list(rows):
    return [dict(r) for r in rows]


def ensure_columns(cursor, table_name, columns):
    cursor.execute(f'PRAGMA table_info({table_name})')
    exists = {row[1] for row in cursor.fetchall()}
    for col, col_type in columns.items():
        if col not in exists:
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {col} {col_type}')


def table_exists(cursor, table_name):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None


def load_projects_with_parallel_strategy(cursor, enabled_only=False, scene=None):
    if scene != 'home' or not table_exists(cursor, 'service_projects'):
        if enabled_only:
            cursor.execute("SELECT * FROM therapy_projects WHERE status='enabled' ORDER BY name")
        else:
            cursor.execute('SELECT * FROM therapy_projects ORDER BY id DESC')
        return row_list(cursor.fetchall())

    therapy_sql = 'SELECT id, name, category, status, description, created_at FROM therapy_projects'
    if enabled_only:
        therapy_sql += " WHERE status='enabled'"
    therapy_sql += ' ORDER BY id DESC'
    cursor.execute(therapy_sql)
    projects = row_list(cursor.fetchall())

    service_sql = 'SELECT id, name, category, status, description, created_at FROM service_projects'
    if enabled_only:
        service_sql += " WHERE status='enabled'"
    service_sql += ' ORDER BY id DESC'
    cursor.execute(service_sql)
    service_projects = row_list(cursor.fetchall())

    by_name = {p['name']: p for p in projects}
    for sp in service_projects:
        if sp['name'] in by_name:
            by_name[sp['name']].update({
                'category': sp.get('category') or by_name[sp['name']].get('category'),
                'status': sp.get('status') or by_name[sp['name']].get('status'),
                'description': sp.get('description') or by_name[sp['name']].get('description'),
            })
        else:
            projects.append(sp)
            by_name[sp['name']] = sp

    projects.sort(key=lambda x: x.get('id') or 0, reverse=True)
    return projects


def create_db_backup(backup_type='manual', notes=''):
    backup_dir = get_backup_directory()
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    fn = f'medical_system_{ts}.db'
    fp = os.path.join(backup_dir, fn)
    try:
        if os.path.exists(DB_PATH):
            shutil.copy2(DB_PATH, fp)
            status = 'success'
            msg = '备份成功'
        else:
            status = 'failed'
            msg = '数据库文件不存在'
        conn = get_db()
        c = conn.cursor()
        c.execute('INSERT INTO db_backups (backup_file, backup_time, backup_type, status, notes) VALUES (?,?,?,?,?)',
                  (fp, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), backup_type, status, notes or msg))
        conn.commit()
        conn.close()
        return {'filename': fn, 'backup_file': fp, 'status': status, 'message': msg}
    except Exception as e:
        logging.exception('backup failed')
        return {'filename': fn, 'status': 'failed', 'message': str(e)}


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
    c.execute('''
        INSERT INTO system_settings (setting_key, setting_value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value=excluded.setting_value,
            updated_at=CURRENT_TIMESTAMP
    ''', (key, value))
    conn.commit()
    conn.close()


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



PROJECT_EQUIPMENT_MAP = {
    '听力测试': '听力耳机',
    '高压氧仓': '高压氧仓',
    '艾灸': '艾灸',
    '按摩': '按摩机',
}


def generate_time_slots(start='08:30', end='16:00', interval_minutes=15):
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


def is_today_or_future(date_str):
    if not date_str:
        return False
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date() >= datetime.now().date()
    except ValueError:
        return False


def validate_customer_payload(d):
    id_card = (d.get('id_card') or '').strip()
    phone = (d.get('phone') or '').strip()
    address = (d.get('address') or '').strip()
    if len(id_card) != 18:
        return '身份证号必须为18位'
    if len(phone) != 11 or not phone.isdigit():
        return '手机号必须为11位数字'
    if not address:
        return '地址为必填项'
    return None



def get_project_required_equipment_name(project_name):
    return PROJECT_EQUIPMENT_MAP.get(project_name)

HEALTH_ASSESSMENT_ALLOWED_VALUES = {
    'allergy_history': {'无', '有'},
    'smoking_status': {'无', '有'},
    'drinking_status': {'无', '有'},
    'fatigue_last_month': {'无', '稍微疲劳', '比较疲劳'},
    'sleep_quality': {'很差', '差', '一般'},
    'sleep_hours': {'<6小时', '6-8小时', '9-10小时'},
    'blood_pressure_test': {'未监测', '监测：正常', '监测：偏低', '监测：偏高'},
    'blood_lipid_test': {'未监测', '监测：正常', '监测：偏高'},
    'chronic_pain': {'无', '有'},
    'weekly_exercise_freq': {'<3次', '3-4次', '5-7次', '>7次'},
}


def validate_health_assessment_enums(data):
    for field, allowed in HEALTH_ASSESSMENT_ALLOWED_VALUES.items():
        value = data.get(field)
        if value in (None, ''):
            continue
        if value not in allowed:
            return f'{field} 的值非法: {value}'
    return None


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            id_card TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            address TEXT,
            gender TEXT,
            birth_date TEXT,
            medical_history TEXT,
            allergies TEXT,
            diet_habits TEXT,
            chronic_diseases TEXT,
            health_status TEXT,
            therapy_contraindications TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 历史数据库兼容：缺失字段时自动补齐
    c.execute('PRAGMA table_info(customers)')
    customer_columns = {row[1] for row in c.fetchall()}
    extra_customer_columns = {
        'diet_habits': 'TEXT',
        'chronic_diseases': 'TEXT',
        'health_status': 'TEXT',
        'therapy_contraindications': 'TEXT',
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    ensure_columns(c, 'equipment', {
        'model': 'TEXT',
        'location': 'TEXT',
        'status': "TEXT DEFAULT 'available'",
        'description': 'TEXT',
        'created_at': 'TEXT DEFAULT CURRENT_TIMESTAMP',
    })

    c.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            equipment_id INTEGER,
            project_id INTEGER,
            staff_id INTEGER,
            appointment_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT DEFAULT 'scheduled',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (equipment_id) REFERENCES equipment(id)
        )
    ''')

    ensure_columns(c, 'appointments', {
        'equipment_id': 'INTEGER',
        'project_id': 'INTEGER',
        'staff_id': 'INTEGER',
        'appointment_date': 'TEXT',
        'start_time': 'TEXT',
        'end_time': 'TEXT',
        'status': "TEXT DEFAULT 'scheduled'",
        'notes': 'TEXT',
        'created_at': 'TEXT DEFAULT CURRENT_TIMESTAMP',
        'updated_at': "TEXT DEFAULT CURRENT_TIMESTAMP",
    })

    c.execute('''
        CREATE TABLE IF NOT EXISTS equipment_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            equipment_id INTEGER NOT NULL,
            appointment_id INTEGER,
            project_id INTEGER,
            staff_id INTEGER,
            usage_date TEXT NOT NULL,
            duration_minutes INTEGER,
            parameters TEXT,
            notes TEXT,
            operator TEXT,
            usage_status TEXT,
            usage_result TEXT,
            customer_feedback TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (equipment_id) REFERENCES equipment(id),
            FOREIGN KEY (appointment_id) REFERENCES appointments(id)
        )
    ''')

    ensure_columns(c, 'equipment_usage', {
        'appointment_id': 'INTEGER',
        'project_id': 'INTEGER',
        'staff_id': 'INTEGER',
        'parameters': 'TEXT',
        'notes': 'TEXT',
        'operator': 'TEXT',
        'usage_status': 'TEXT',
        'usage_result': 'TEXT',
        'customer_feedback': 'TEXT',
        'created_at': 'TEXT DEFAULT CURRENT_TIMESTAMP',
    })

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
            fatigue_last_month TEXT,
            sleep_quality TEXT,
            sleep_hours TEXT,
            blood_pressure_test TEXT,
            blood_lipid_test TEXT,
            chronic_pain TEXT,
            pain_details TEXT,
            exercise_methods TEXT,
            weekly_exercise_freq TEXT,
            health_needs TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    ''')

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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
        'created_at': 'TEXT DEFAULT CURRENT_TIMESTAMP',
    })

    c.execute('''
        CREATE TABLE IF NOT EXISTS service_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            status TEXT DEFAULT 'enabled',
            description TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    ensure_columns(c, 'service_projects', {
        'name': 'TEXT',
        'category': 'TEXT',
        'status': "TEXT DEFAULT 'enabled'",
        'description': 'TEXT',
        'created_at': 'TEXT DEFAULT CURRENT_TIMESTAMP',
    })

    c.execute('''
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT,
            phone TEXT,
            status TEXT DEFAULT 'available',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    ensure_columns(c, 'staff', {
        'role': 'TEXT',
        'phone': 'TEXT',
        'status': "TEXT DEFAULT 'available'",
        'notes': 'TEXT',
        'created_at': 'TEXT DEFAULT CURRENT_TIMESTAMP',
    })

    c.execute('''
        CREATE TABLE IF NOT EXISTS home_appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            notes TEXT,
            status TEXT DEFAULT 'scheduled',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (project_id) REFERENCES therapy_projects(id),
            FOREIGN KEY (staff_id) REFERENCES staff(id)
        )
    ''')

    ensure_columns(c, 'home_appointments', {
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
        'notes': 'TEXT',
        'status': "TEXT DEFAULT 'scheduled'",
        'updated_at': 'TEXT DEFAULT CURRENT_TIMESTAMP',
        'created_at': 'TEXT DEFAULT CURRENT_TIMESTAMP',
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
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('INSERT OR IGNORE INTO system_settings (setting_key, setting_value) VALUES (?, ?)',
              ('backup_directory', BACKUP_FOLDER))

    c.execute('''
        CREATE TABLE IF NOT EXISTS satisfaction_surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            appointment_id INTEGER,
            service_rating INTEGER,
            equipment_rating INTEGER,
            environment_rating INTEGER,
            staff_rating INTEGER,
            overall_rating INTEGER,
            feedback TEXT,
            suggestions TEXT,
            survey_date TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (appointment_id) REFERENCES appointments(id)
        )
    ''')

    ensure_columns(c, 'satisfaction_surveys', {
        'appointment_id': 'INTEGER',
        'service_rating': 'INTEGER',
        'equipment_rating': 'INTEGER',
        'environment_rating': 'INTEGER',
        'staff_rating': 'INTEGER',
        'overall_rating': 'INTEGER',
        'feedback': 'TEXT',
        'suggestions': 'TEXT',
        'survey_date': 'TEXT DEFAULT CURRENT_TIMESTAMP',
    })

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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    ''')

    ensure_columns(c, 'visit_checkins', {
        'purpose': 'TEXT',
        'notes': 'TEXT',
        'created_at': 'TEXT DEFAULT CURRENT_TIMESTAMP',
    })

    c.execute("SELECT COUNT(*) FROM equipment")
    if c.fetchone()[0] == 0:
        for row in [
            ('红外理疗仪', '理疗设备', 'IR-2024-A', 'A区101室', 'available', '用于肌肉放松'),
            ('超声波治疗仪', '理疗设备', 'US-2024-B', 'A区102室', 'available', '深层组织治疗'),
            ('电刺激治疗仪', '康复设备', 'ES-2024-C', 'B区201室', 'available', '神经肌肉电刺激'),
            ('磁疗仪', '理疗设备', 'MT-2024-D', 'B区202室', 'available', '磁场疗法'),
            ('牵引床', '康复设备', 'TB-2024-E', 'C区301室', 'available', '颈椎腰椎牵引'),
            ('中药熏蒸舱', '中医设备', 'HC-2024-F', 'C区302室', 'available', '中药熏蒸'),
        ]:
            c.execute(
                'INSERT INTO equipment (name, type, model, location, status, description) VALUES (?,?,?,?,?,?)',
                row
            )

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

    service_project_seeds = [
        ('高压氧仓', '上门', 'enabled', '高压氧仓服务项目'),
        ('艾灸', '上门', 'enabled', '艾灸服务项目'),
        ('读书室', '上门', 'enabled', '读书室服务项目'),
        ('棋牌室', '上门', 'enabled', '棋牌室服务项目'),
        ('听力测试', '上门', 'enabled', '听力测试服务项目'),
        ('乒乓球', '上门', 'enabled', '乒乓球服务项目'),
        ('台球', '上门', 'enabled', '台球服务项目'),
    ]
    for row in service_project_seeds:
        c.execute('SELECT id FROM service_projects WHERE name=?', (row[0],))
        if not c.fetchone():
            c.execute(
                'INSERT INTO service_projects (name, category, status, description) VALUES (?,?,?,?)',
                row,
            )


    required_equipment_seeds = [
        ('听力耳机', '专用设备', 'HT-001', 'D区101室', 'available', '听力测试专用设备'),
        ('高压氧仓', '专用设备', 'HBOT-001', 'D区102室', 'available', '高压氧服务设备'),
        ('艾灸', '专用设备', 'MOXA-001', 'D区103室', 'available', '艾灸服务设备'),
        ('按摩机', '专用设备', 'MASS-001', 'D区104室', 'available', '按摩服务设备'),
    ]
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
        ('按摩', '理疗', 45, 1, '专用设备', 0, 'enabled', '按摩服务项目'),
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

    c.execute("SELECT COUNT(*) FROM staff")
    if c.fetchone()[0] == 0:
        for row in [
            ('张理疗', '理疗师', '13800000001', 'available', '擅长理疗'),
            ('李康复', '康复师', '13800000002', 'available', '擅长康复训练'),
            ('王护理', '护士', '13800000003', 'available', '可上门服务'),
        ]:
            c.execute('INSERT INTO staff (name, role, phone, status, notes) VALUES (?,?,?,?,?)', row)

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
    q = request.args.get('search', '')
    conn = get_db()
    c = conn.cursor()
    if q:
        c.execute(
            'SELECT * FROM customers WHERE name LIKE ? OR id_card LIKE ? OR phone LIKE ? ORDER BY created_at DESC',
            (f'%{q}%', f'%{q}%', f'%{q}%')
        )
    else:
        c.execute('SELECT * FROM customers ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/customers/<int:cid>', methods=['GET'])
def api_customer_get(cid):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM customers WHERE id = ?', (cid,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '客户不存在'}), 404
    cust = dict(row)
    c.execute(
        'SELECT a.*, e.name as equipment_name FROM appointments a LEFT JOIN equipment e ON a.equipment_id=e.id WHERE a.customer_id=? ORDER BY a.appointment_date DESC, a.start_time DESC',
        (cid,)
    )
    cust['appointments'] = row_list(c.fetchall())
    c.execute(
        'SELECT eu.*, e.name as equipment_name FROM equipment_usage eu JOIN equipment e ON eu.equipment_id=e.id WHERE eu.customer_id=? ORDER BY eu.usage_date DESC',
        (cid,)
    )
    cust['usage_records'] = row_list(c.fetchall())
    c.execute('SELECT * FROM health_records WHERE customer_id=? ORDER BY record_date DESC', (cid,))
    cust['health_records'] = row_list(c.fetchall())
    c.execute('SELECT * FROM visit_checkins WHERE customer_id=? ORDER BY checkin_time DESC', (cid,))
    cust['visit_checkins'] = row_list(c.fetchall())
    conn.close()
    return jsonify(cust)


@app.route('/api/customers', methods=['POST'])
def api_customer_create():
    d = request.json or {}
    customer_error = validate_customer_payload(d)
    if customer_error:
        return jsonify({'error': customer_error}), 400
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('''
            INSERT INTO customers (name, id_card, phone, email, address, gender, birth_date, medical_history, allergies, diet_habits, chronic_diseases, health_status, therapy_contraindications)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            d.get('name'), d.get('id_card'), d.get('phone'), d.get('email'), d.get('address'),
            d.get('gender'), d.get('birth_date'), d.get('medical_history'), d.get('allergies'),
            d.get('diet_habits'), d.get('chronic_diseases'), d.get('health_status'), d.get('therapy_contraindications')
        ))
        conn.commit()
        id = c.lastrowid
        conn.close()
        return jsonify({'id': id, 'message': '客户创建成功'}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': '身份证号已存在'}), 400


@app.route('/api/customers/<int:cid>', methods=['PUT'])
def api_customer_update(cid):
    d = request.json or {}
    customer_error = validate_customer_payload(d)
    if customer_error:
        return jsonify({'error': customer_error}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM customers WHERE id=?', (cid,))
    if not c.fetchone():
        conn.close()
        return jsonify({'error': '客户不存在'}), 404
    c.execute('''
        UPDATE customers SET name=?, id_card=?, phone=?, email=?, address=?, gender=?, birth_date=?, medical_history=?, allergies=?, diet_habits=?, chronic_diseases=?, health_status=?, therapy_contraindications=?, updated_at=CURRENT_TIMESTAMP WHERE id=?
    ''', (
        d.get('name'), d.get('id_card'), d.get('phone'), d.get('email'), d.get('address'),
        d.get('gender'), d.get('birth_date'), d.get('medical_history'), d.get('allergies'),
        d.get('diet_habits'), d.get('chronic_diseases'), d.get('health_status'), d.get('therapy_contraindications'), cid
    ))
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/customers/<int:cid>', methods=['DELETE'])
def api_customer_delete(cid):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM customers WHERE id=?', (cid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '已删除'})


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
    ''', (d.get('customer_id'), d.get('checkin_time') or datetime.now().strftime('%Y-%m-%d %H:%M'), d.get('purpose'), d.get('notes')))
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


# ========== 健康评估 ==========
@app.route('/api/health-assessments', methods=['GET'])
def api_health_assessments_list():
    customer_id = request.args.get('customer_id', type=int)
    search = (request.args.get('search', '') or '').strip()
    conn = get_db()
    c = conn.cursor()
    sql = 'SELECT h.*, c.name as customer_name FROM health_assessments h JOIN customers c ON h.customer_id=c.id WHERE 1=1'
    params = []
    if customer_id:
        sql += ' AND h.customer_id=?'
        params.append(customer_id)
    if search:
        sql += ' AND c.name LIKE ?'
        params.append(f'%{search}%')
    sql += ' ORDER BY h.assessment_date DESC, h.id DESC'
    c.execute(sql, params)
    rows = row_list(c.fetchall())
    conn.close()
    for r in rows:
        r['exercise_methods'] = decode_multi_value(r.get('exercise_methods'))
        r['health_needs'] = decode_multi_value(r.get('health_needs'))
    return jsonify(rows)


@app.route('/api/health-assessments', methods=['POST'])
def api_health_assessment_create():
    d = request.json or {}
    invalid_msg = validate_health_assessment_enums(d)
    if invalid_msg:
        return jsonify({'error': invalid_msg}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO health_assessments (customer_id, assessment_date, assessor, age, height_cm, weight_kg, address, past_medical_history, family_history,
         allergy_history, allergy_details, smoking_status, smoking_years, cigarettes_per_day, drinking_status, drinking_years, fatigue_last_month,
         sleep_quality, sleep_hours, blood_pressure_test, blood_lipid_test, chronic_pain, pain_details, exercise_methods, weekly_exercise_freq,
         health_needs, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        d.get('customer_id'), d.get('assessment_date'), d.get('assessor'), d.get('age'), d.get('height_cm'), d.get('weight_kg'),
        d.get('address'), d.get('past_medical_history'), d.get('family_history'), d.get('allergy_history'), d.get('allergy_details'),
        d.get('smoking_status'), d.get('smoking_years'), d.get('cigarettes_per_day'), d.get('drinking_status'), d.get('drinking_years'),
        d.get('fatigue_last_month'), d.get('sleep_quality'), d.get('sleep_hours'), d.get('blood_pressure_test'), d.get('blood_lipid_test'),
        d.get('chronic_pain'), d.get('pain_details'), parse_multi_value(d.get('exercise_methods')), d.get('weekly_exercise_freq'),
        parse_multi_value(d.get('health_needs')), d.get('notes')
    ))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return jsonify({'id': rid, 'message': '健康评估已添加'}), 201


@app.route('/api/health-assessments/<int:hid>', methods=['GET'])
def api_health_assessment_get(hid):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT h.*, c.name as customer_name FROM health_assessments h JOIN customers c ON h.customer_id=c.id WHERE h.id=?', (hid,))
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
            fatigue_last_month=?, sleep_quality=?, sleep_hours=?, blood_pressure_test=?, blood_lipid_test=?, chronic_pain=?, pain_details=?,
            exercise_methods=?, weekly_exercise_freq=?, health_needs=?, notes=?
        WHERE id=?
    ''', (
        d.get('customer_id'), d.get('assessment_date'), d.get('assessor'), d.get('age'), d.get('height_cm'), d.get('weight_kg'),
        d.get('address'), d.get('past_medical_history'), d.get('family_history'), d.get('allergy_history'), d.get('allergy_details'),
        d.get('smoking_status'), d.get('smoking_years'), d.get('cigarettes_per_day'), d.get('drinking_status'), d.get('drinking_years'),
        d.get('fatigue_last_month'), d.get('sleep_quality'), d.get('sleep_hours'), d.get('blood_pressure_test'), d.get('blood_lipid_test'),
        d.get('chronic_pain'), d.get('pain_details'), parse_multi_value(d.get('exercise_methods')), d.get('weekly_exercise_freq'),
        parse_multi_value(d.get('health_needs')), d.get('notes'), hid
    ))
    conn.commit()
    conn.close()
    return jsonify({'message': '健康评估更新成功'})


@app.route('/api/health-assessments/<int:hid>', methods=['DELETE'])
def api_health_assessment_delete(hid):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM health_assessments WHERE id=?', (hid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '已删除'})


# ========== 预约 ==========
@app.route('/api/appointments', methods=['GET'])
def api_appointments_list():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT a.*, c.name as customer_name, c.phone as customer_phone, e.name as equipment_name,
               p.name as project_name, s.name as staff_name
        FROM appointments a
        JOIN customers c ON a.customer_id=c.id
        LEFT JOIN equipment e ON a.equipment_id=e.id
        LEFT JOIN therapy_projects p ON a.project_id=p.id
        LEFT JOIN staff s ON a.staff_id=s.id
        ORDER BY a.appointment_date DESC, a.start_time DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/appointments', methods=['POST'])
def api_appointment_create():
    d = request.json or {}
    if not all(d.get(k) for k in ('customer_id', 'project_id', 'appointment_date', 'start_time', 'end_time')):
        return jsonify({'error': '缺少必填字段'}), 400
    if not is_today_or_future(d.get('appointment_date')):
        return jsonify({'error': '预约时间仅可选择当天及以后日期'}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return jsonify({'error': '项目不存在'}), 400
    required_equipment_name = get_project_required_equipment_name(project['name'])
    if required_equipment_name and not d.get('equipment_id'):
        conn.close()
        return jsonify({'error': '该项目需要指定设备'}), 400

    if d.get('equipment_id'):
        c.execute('SELECT id, name, status FROM equipment WHERE id=?', (d.get('equipment_id'),))
        equipment = c.fetchone()
        if not equipment or equipment['status'] != 'available':
            conn.close()
            return jsonify({'error': '设备不可用'}), 400
        if required_equipment_name and equipment['name'] != required_equipment_name:
            conn.close()
            return jsonify({'error': '所选设备与项目不匹配'}), 400

    c.execute(f"SELECT COUNT(*) as n FROM appointments WHERE customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
              (d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
    if c.fetchone()['n'] > 0:
        conn.close()
        return jsonify({'error': '同一客户同一时段不能重复预约'}), 400

    if d.get('equipment_id'):
        c.execute(f"SELECT COUNT(*) as n FROM appointments WHERE equipment_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
                  (d.get('equipment_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
        if c.fetchone()['n'] > 0:
            conn.close()
            return jsonify({'error': '该时段设备已被预约'}), 400

    if d.get('staff_id'):
        c.execute(f"SELECT COUNT(*) as n FROM appointments WHERE staff_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
                  (d.get('staff_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
        if c.fetchone()['n'] > 0:
            conn.close()
            return jsonify({'error': '该服务人员该时段已被预约'}), 400

    c.execute('''
        INSERT INTO appointments (customer_id, project_id, equipment_id, staff_id, appointment_date, start_time, end_time, status, notes, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
    ''', (d.get('customer_id'), d.get('project_id'), d.get('equipment_id'), d.get('staff_id'), d.get('appointment_date'), d.get('start_time'), d.get('end_time'), d.get('status', 'scheduled'), d.get('notes')))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return jsonify({'id': rid, 'message': '预约成功'}), 201


@app.route('/api/appointments/free-slots', methods=['GET'])
def api_appointments_free_slots():
    date = request.args.get('date')
    project_id = request.args.get('project_id', type=int)
    if not date:
        return jsonify({'error': '缺少 date'}), 400
    if not project_id:
        return jsonify({'error': '缺少 project_id'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (project_id,))
    project = c.fetchone()
    if not project:
        conn.close()
        return jsonify({'error': '项目不存在'}), 404

    required_equipment_name = get_project_required_equipment_name(project['name'])
    available_equipment = []
    if required_equipment_name:
        c.execute("SELECT id, name FROM equipment WHERE status='available' AND name=? ORDER BY name", (required_equipment_name,))
        available_equipment = row_list(c.fetchall())

    slots = generate_time_slots('08:30', '16:00', 15)
    result = []
    for st, et in slots:
        free_equipment = []
        if available_equipment:
            for equipment in available_equipment:
                c.execute(
                    f"SELECT COUNT(*) as n FROM appointments WHERE appointment_date=? AND status='scheduled' AND equipment_id=? AND {overlap_condition()}",
                    (date, equipment['id'], et, st),
                )
                if c.fetchone()['n'] == 0:
                    free_equipment.append({'id': equipment['id'], 'name': equipment['name']})

        c.execute(
            f"SELECT staff_id FROM appointments WHERE appointment_date=? AND status='scheduled' AND staff_id IS NOT NULL AND {overlap_condition()}",
            (date, et, st),
        )
        busy_staff_ids = {r['staff_id'] for r in c.fetchall()}

        if busy_staff_ids:
            ph = ','.join('?' * len(busy_staff_ids))
            c.execute(f"SELECT COUNT(*) as n FROM staff WHERE status='available' AND id NOT IN ({ph})", tuple(busy_staff_ids))
        else:
            c.execute("SELECT COUNT(*) as n FROM staff WHERE status='available'")
        available_staff_count = c.fetchone()['n']

        result.append({
            'start_time': st,
            'end_time': et,
            'available_staff_count': max(available_staff_count, 0),
            'available_equipment': free_equipment,
        })

    conn.close()
    return jsonify(result)


@app.route('/api/appointments/available-options', methods=['GET'])
def api_appointments_available_options():
    date = request.args.get('date')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    project_id = request.args.get('project_id', type=int)
    if not all([date, start_time, end_time, project_id]):
        return jsonify({'error': '缺少必要参数'}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM therapy_projects WHERE id=?', (project_id,))
    project = c.fetchone()
    if not project:
        conn.close()
        return jsonify({'error': '项目不存在'}), 404
    c.execute(f"SELECT equipment_id FROM appointments WHERE appointment_date=? AND status='scheduled' AND {overlap_condition()} AND equipment_id IS NOT NULL", (date, end_time, start_time))
    busy_eq = [r['equipment_id'] for r in c.fetchall()]
    if busy_eq:
        ph = ','.join('?' * len(busy_eq))
        c.execute(f"SELECT * FROM equipment WHERE status='available' AND id NOT IN ({ph}) ORDER BY name", busy_eq)
    else:
        c.execute("SELECT * FROM equipment WHERE status='available' ORDER BY name")
    avail_equipment = row_list(c.fetchall())
    c.execute(f"SELECT staff_id FROM appointments WHERE appointment_date=? AND status='scheduled' AND {overlap_condition()} AND staff_id IS NOT NULL", (date, end_time, start_time))
    busy_staff = [r['staff_id'] for r in c.fetchall()]
    if busy_staff:
        ph = ','.join('?' * len(busy_staff))
        c.execute(f"SELECT * FROM staff WHERE status='available' AND id NOT IN ({ph}) ORDER BY name", busy_staff)
    else:
        c.execute("SELECT * FROM staff WHERE status='available' ORDER BY name")
    avail_staff = row_list(c.fetchall())
    conn.close()
    return jsonify({'project': dict(project), 'available_equipment': avail_equipment, 'available_staff': avail_staff})




@app.route('/api/appointments/<int:aid>', methods=['PUT'])
def api_appointment_update(aid):
    d = request.json or {}
    if not all(d.get(k) for k in ('customer_id', 'project_id', 'appointment_date', 'start_time', 'end_time')):
        return jsonify({'error': '缺少必填字段'}), 400
    if not is_today_or_future(d.get('appointment_date')):
        return jsonify({'error': '预约时间仅可选择当天及以后日期'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM appointments WHERE id=?', (aid,))
    if not c.fetchone():
        conn.close()
        return jsonify({'error': '预约记录不存在'}), 404

    c.execute('SELECT * FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return jsonify({'error': '项目不存在'}), 400

    required_equipment_name = get_project_required_equipment_name(project['name'])
    if required_equipment_name and not d.get('equipment_id'):
        conn.close()
        return jsonify({'error': '该项目需要指定设备'}), 400

    if d.get('equipment_id'):
        c.execute('SELECT id, name, status FROM equipment WHERE id=?', (d.get('equipment_id'),))
        equipment = c.fetchone()
        if not equipment or equipment['status'] != 'available':
            conn.close()
            return jsonify({'error': '设备不可用'}), 400
        if required_equipment_name and equipment['name'] != required_equipment_name:
            conn.close()
            return jsonify({'error': '所选设备与项目不匹配'}), 400

    c.execute(
        f"SELECT COUNT(*) as n FROM appointments WHERE id<>? AND customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
        (aid, d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')),
    )
    if c.fetchone()['n'] > 0:
        conn.close()
        return jsonify({'error': '同一客户同一时段不能重复预约'}), 400

    if d.get('equipment_id'):
        c.execute(
            f"SELECT COUNT(*) as n FROM appointments WHERE id<>? AND equipment_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
            (aid, d.get('equipment_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')),
        )
        if c.fetchone()['n'] > 0:
            conn.close()
            return jsonify({'error': '该时段设备已被预约'}), 400

    if d.get('staff_id'):
        c.execute(
            f"SELECT COUNT(*) as n FROM appointments WHERE id<>? AND staff_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}",
            (aid, d.get('staff_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')),
        )
        if c.fetchone()['n'] > 0:
            conn.close()
            return jsonify({'error': '该服务人员该时段已被预约'}), 400

    c.execute(
        '''
        UPDATE appointments
        SET customer_id=?, project_id=?, equipment_id=?, staff_id=?, appointment_date=?, start_time=?, end_time=?, status=?, notes=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        ''',
        (
            d.get('customer_id'), d.get('project_id'), d.get('equipment_id'), d.get('staff_id'),
            d.get('appointment_date'), d.get('start_time'), d.get('end_time'), d.get('status', 'scheduled'), d.get('notes'), aid,
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({'message': '预约修改成功'})

@app.route('/api/appointments/<int:aid>/cancel', methods=['POST'])
def api_appointment_cancel(aid):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE appointments SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '已取消'})


# ========== 上门预约 ==========
@app.route('/api/home-appointments', methods=['GET'])
def api_home_appointments_list():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT
            h.*,
            COALESCE(h.customer_name, c.name) AS customer_name,
            COALESCE(h.service_project, p.name) AS project_name,
            COALESCE(h.staff_name, s.name) AS staff_name,
            COALESCE(h.phone, c.phone) AS phone,
            COALESCE(h.home_address, h.location) AS home_address,
            COALESCE(h.home_time, h.start_time || '-' || h.end_time) AS home_time
        FROM home_appointments h
        LEFT JOIN customers c ON h.customer_id=c.id
        LEFT JOIN therapy_projects p ON h.project_id=p.id
        LEFT JOIN staff s ON h.staff_id=s.id
        ORDER BY h.appointment_date DESC, h.start_time DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/home-appointments', methods=['POST'])
def api_home_appointments_create():
    d = request.json or {}
    if not all(d.get(k) for k in ('customer_id', 'project_id', 'appointment_date', 'start_time', 'end_time', 'location')):
        return jsonify({'error': '缺少必填字段'}), 400
    if not is_valid_home_time_range(d.get('start_time'), d.get('end_time')):
        return jsonify({'error': '上门预约时间需在08:30-16:00且结束时间晚于开始时间'}), 400
    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT id, name, phone FROM customers WHERE id=?', (d.get('customer_id'),))
    customer = c.fetchone()
    if not customer:
        conn.close()
        return jsonify({'error': '客户不存在'}), 404

    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return jsonify({'error': '上门项目不存在'}), 404
    allowed_home_projects = {'上门康复护理', '中医养生咨询', '康复训练指导', '血糖测试', '按摩'}
    if project['name'] not in allowed_home_projects:
        conn.close()
        return jsonify({'error': '该项目不支持上门预约'}), 400

    staff = None
    if d.get('staff_id'):
        c.execute('SELECT id, name FROM staff WHERE id=?', (d.get('staff_id'),))
        staff = c.fetchone()
        if not staff:
            conn.close()
            return jsonify({'error': '服务人员不存在'}), 404

    c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
    if c.fetchone()['n'] > 0:
        conn.close()
        return jsonify({'error': '同一客户同一时段不能重复上门预约'}), 400
    if d.get('staff_id'):
        c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE staff_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (d.get('staff_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
        if c.fetchone()['n'] > 0:
            conn.close()
            return jsonify({'error': '该服务人员该时段已有上门预约'}), 400

    home_address = d.get('home_address') or d.get('location')
    home_time = d.get('home_time') or f"{d.get('start_time')}-{d.get('end_time')}"

    c.execute('''
        INSERT INTO home_appointments (
            customer_id, project_id, staff_id,
            customer_name, phone, home_time, home_address, service_project, staff_name,
            appointment_date, start_time, end_time, location, contact_person, contact_phone, notes, status, updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
    ''', (
        d.get('customer_id'), d.get('project_id'), d.get('staff_id'),
        customer['name'], customer['phone'], home_time, home_address, project['name'], staff['name'] if staff else None,
        d.get('appointment_date'), d.get('start_time'), d.get('end_time'), d.get('location'), d.get('contact_person'), d.get('contact_phone'), d.get('notes'), d.get('status', 'scheduled')
    ))
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return jsonify({'id': rid, 'message': '上门预约成功'}), 201


@app.route('/api/home-appointments/<int:hid>/cancel', methods=['POST'])
def api_home_appointments_cancel(hid):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE home_appointments SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE id=?", (hid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '已取消'})


@app.route('/api/home-appointments/<int:hid>', methods=['PUT'])
def api_home_appointments_update(hid):
    d = request.json or {}
    if not all(d.get(k) for k in ('customer_id', 'project_id', 'appointment_date', 'start_time', 'end_time', 'location')):
        return jsonify({'error': '缺少必填字段'}), 400
    if not is_valid_home_time_range(d.get('start_time'), d.get('end_time')):
        return jsonify({'error': '上门预约时间需在08:30-16:00且结束时间晚于开始时间'}), 400
    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT id FROM home_appointments WHERE id=?', (hid,))
    if not c.fetchone():
        conn.close()
        return jsonify({'error': '上门预约不存在'}), 404

    c.execute('SELECT id, name, phone FROM customers WHERE id=?', (d.get('customer_id'),))
    customer = c.fetchone()
    if not customer:
        conn.close()
        return jsonify({'error': '客户不存在'}), 404

    c.execute('SELECT id, name FROM therapy_projects WHERE id=?', (d.get('project_id'),))
    project = c.fetchone()
    if not project:
        conn.close()
        return jsonify({'error': '上门项目不存在'}), 404
    allowed_home_projects = {'上门康复护理', '中医养生咨询', '康复训练指导', '血糖测试', '按摩'}
    if project['name'] not in allowed_home_projects:
        conn.close()
        return jsonify({'error': '该项目不支持上门预约'}), 400

    staff = None
    if d.get('staff_id'):
        c.execute('SELECT id, name FROM staff WHERE id=?', (d.get('staff_id'),))
        staff = c.fetchone()
        if not staff:
            conn.close()
            return jsonify({'error': '服务人员不存在'}), 404

    c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE id<>? AND customer_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (hid, d.get('customer_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
    if c.fetchone()['n'] > 0:
        conn.close()
        return jsonify({'error': '同一客户同一时段不能重复上门预约'}), 400
    if d.get('staff_id'):
        c.execute(f"SELECT COUNT(*) as n FROM home_appointments WHERE id<>? AND staff_id=? AND appointment_date=? AND status='scheduled' AND {overlap_condition()}", (hid, d.get('staff_id'), d.get('appointment_date'), d.get('end_time'), d.get('start_time')))
        if c.fetchone()['n'] > 0:
            conn.close()
            return jsonify({'error': '该服务人员该时段已有上门预约'}), 400

    home_address = d.get('home_address') or d.get('location')
    home_time = d.get('home_time') or f"{d.get('start_time')}-{d.get('end_time')}"

    c.execute('''
        UPDATE home_appointments
        SET customer_id=?, project_id=?, staff_id=?,
            customer_name=?, phone=?, home_time=?, home_address=?, service_project=?, staff_name=?,
            appointment_date=?, start_time=?, end_time=?, location=?,
            contact_person=?, contact_phone=?, notes=?, status=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
    ''', (
        d.get('customer_id'), d.get('project_id'), d.get('staff_id'),
        customer['name'], customer['phone'], home_time, home_address, project['name'], staff['name'] if staff else None,
        d.get('appointment_date'), d.get('start_time'), d.get('end_time'), d.get('location'),
        d.get('contact_person'), d.get('contact_phone'), d.get('notes'), d.get('status', 'scheduled'), hid
    ))
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


# ========== 设备使用 ==========
@app.route('/api/equipment-usage', methods=['GET'])
def api_equipment_usage_list():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT eu.*, c.name as customer_name, e.name as equipment_name, p.name as project_name, s.name as staff_name
        FROM equipment_usage eu
        JOIN customers c ON eu.customer_id=c.id
        LEFT JOIN equipment e ON eu.equipment_id=e.id
        LEFT JOIN therapy_projects p ON eu.project_id=p.id
        LEFT JOIN staff s ON eu.staff_id=s.id
        ORDER BY eu.usage_date DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/equipment-usage', methods=['POST'])
def api_equipment_usage_create():
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO equipment_usage (customer_id, equipment_id, appointment_id, project_id, staff_id, usage_date, duration_minutes, parameters, notes, operator, usage_status, usage_result, customer_feedback)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (d.get('customer_id'), d.get('equipment_id'), d.get('appointment_id'), d.get('project_id'), d.get('staff_id'), d.get('usage_date'), d.get('duration_minutes'), d.get('parameters'), d.get('notes'), d.get('operator'), d.get('usage_status'), d.get('usage_result'), d.get('customer_feedback')))
    conn.commit()
    id = c.lastrowid
    conn.close()
    return jsonify({'id': id, 'message': '记录已添加'}), 201


@app.route('/api/equipment-usage/summary', methods=['GET'])
def api_equipment_usage_summary():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT e.id as equipment_id,
               e.name as equipment_name,
               COUNT(eu.id) as usage_count,
               COALESCE(SUM(eu.duration_minutes), 0) as total_duration_minutes,
               COUNT(DISTINCT eu.customer_id) as customer_count
        FROM equipment e
        LEFT JOIN equipment_usage eu ON e.id = eu.equipment_id
        GROUP BY e.id, e.name
        ORDER BY usage_count DESC, total_duration_minutes DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/equipment-usage/by-project', methods=['GET'])
def api_equipment_usage_by_project():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT p.id as project_id, p.name as project_name,
               COUNT(eu.id) as usage_count,
               COALESCE(SUM(eu.duration_minutes), 0) as total_duration_minutes
        FROM therapy_projects p
        LEFT JOIN equipment_usage eu ON p.id = eu.project_id
        GROUP BY p.id, p.name
        ORDER BY usage_count DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/equipment-usage/by-customer', methods=['GET'])
def api_equipment_usage_by_customer():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT c.id as customer_id, c.name as customer_name,
               COUNT(eu.id) as usage_count,
               COALESCE(SUM(eu.duration_minutes), 0) as total_duration_minutes
        FROM customers c
        LEFT JOIN equipment_usage eu ON c.id = eu.customer_id
        GROUP BY c.id, c.name
        ORDER BY usage_count DESC, total_duration_minutes DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/equipment-usage/service-stats', methods=['GET'])
def api_equipment_usage_service_stats():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT COALESCE(p.name, '未分类项目') as project_name,
               COUNT(a.id) as appointment_count
        FROM appointments a
        LEFT JOIN therapy_projects p ON a.project_id = p.id
        WHERE a.status='scheduled'
        GROUP BY COALESCE(p.name, '未分类项目')
        ORDER BY appointment_count DESC, project_name ASC
    ''')
    items = row_list(c.fetchall())
    conn.close()
    total = sum((x.get('appointment_count') or 0) for x in items)
    return jsonify({'items': items, 'total': total})


# ========== 满意度 ==========
@app.route('/api/satisfaction-surveys', methods=['GET'])
def api_surveys_list():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT s.*, c.name as customer_name FROM satisfaction_surveys s JOIN customers c ON s.customer_id=c.id ORDER BY s.survey_date DESC')
    rows = c.fetchall()
    conn.close()
    return jsonify(row_list(rows))


@app.route('/api/satisfaction-surveys', methods=['POST'])
def api_survey_create():
    d = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO satisfaction_surveys (customer_id, appointment_id, service_rating, equipment_rating, environment_rating, staff_rating, overall_rating, feedback, suggestions)
        VALUES (?,?,?,?,?,?,?,?,?)
    ''', (d.get('customer_id'), d.get('appointment_id'), d.get('service_rating'), d.get('equipment_rating'), d.get('environment_rating'), d.get('staff_rating'), d.get('overall_rating'), d.get('feedback'), d.get('suggestions')))
    conn.commit()
    id = c.lastrowid
    conn.close()
    return jsonify({'id': id, 'message': '提交成功'}), 201


# ========== 综合查询 ==========
@app.route('/api/search', methods=['GET'])
def api_search():
    q = (request.args.get('q') or '').strip()
    kind = request.args.get('type', 'all')
    if not q and kind == 'all':
        return jsonify({'customers': [], 'health_records': [], 'appointments': [], 'visit_checkins': [], 'equipment_usage': [], 'surveys': []})

    conn = get_db()
    c = conn.cursor()
    like = f'%{q}%'
    result = {}

    if kind in ('all', 'customers'):
        c.execute('SELECT * FROM customers WHERE name LIKE ? OR id_card LIKE ? OR phone LIKE ? OR email LIKE ? OR address LIKE ? ORDER BY created_at DESC LIMIT 100',
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

    if kind in ('all', 'usage'):
        c.execute('''SELECT eu.*, c.name as customer_name, e.name as equipment_name
            FROM equipment_usage eu JOIN customers c ON eu.customer_id=c.id JOIN equipment e ON eu.equipment_id=e.id
            WHERE c.name LIKE ? OR c.id_card LIKE ? OR c.phone LIKE ? OR eu.notes LIKE ? OR eu.operator LIKE ?
            ORDER BY eu.usage_date DESC LIMIT 100''', (like, like, like, like, like))
        result['equipment_usage'] = row_list(c.fetchall())

    if kind in ('all', 'surveys'):
        c.execute('SELECT s.*, c.name as customer_name FROM satisfaction_surveys s JOIN customers c ON s.customer_id=c.id WHERE c.name LIKE ? OR c.id_card LIKE ? OR c.phone LIKE ? OR s.feedback LIKE ? OR s.suggestions LIKE ? ORDER BY s.survey_date DESC LIMIT 100',
                  (like, like, like, like, like))
        result['surveys'] = row_list(c.fetchall())

    for key in ('customers', 'health_records', 'appointments', 'visit_checkins', 'equipment_usage', 'surveys'):
        if key not in result:
            result[key] = []

    conn.close()
    return jsonify(result)


# ========== 仪表盘 ==========
@app.route('/api/dashboard/stats', methods=['GET'])
def api_dashboard_stats():
    conn = get_db()
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute('SELECT COUNT(*) as n FROM customers')
    total_customers = c.fetchone()['n']
    c.execute("SELECT COUNT(*) as n FROM appointments WHERE appointment_date=? AND status='scheduled'", (today,))
    today_appointments = c.fetchone()['n']
    c.execute("SELECT COUNT(*) as n FROM appointments WHERE appointment_date>=? AND status='scheduled'", (today,))
    pending = c.fetchone()['n']
    c.execute('SELECT COUNT(*) as n FROM equipment')
    total_equipment = c.fetchone()['n']
    c.execute("SELECT COUNT(*) as n FROM equipment WHERE status='available'")
    available = c.fetchone()['n']
    conn.close()
    return jsonify({
        'total_customers': total_customers,
        'today_appointments': today_appointments,
        'pending_appointments': pending,
        'total_equipment': total_equipment,
        'available_equipment': available,
    })


@app.route('/api/dashboard/analytics', methods=['GET'])
def api_dashboard_analytics():
    conn = get_db()
    c = conn.cursor()
    equipment_start_date = (request.args.get('equipment_start_date') or '').strip()
    equipment_end_date = (request.args.get('equipment_end_date') or '').strip()

    # 最近 7 天预约趋势（包含 0 值日期）
    today = datetime.now().date()
    start_day = today - timedelta(days=6)
    c.execute('''
        SELECT appointment_date, COUNT(*) as n
        FROM appointments
        WHERE appointment_date BETWEEN ? AND ?
        GROUP BY appointment_date
        ORDER BY appointment_date
    ''', (start_day.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')))
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

    # 设备使用统计（总时长 + 次数）
    equipment_join_conditions = []
    equipment_params = []
    if equipment_start_date:
        equipment_join_conditions.append('eu.usage_date >= ?')
        equipment_params.append(equipment_start_date)
    if equipment_end_date:
        equipment_join_conditions.append('eu.usage_date <= ?')
        equipment_params.append(equipment_end_date)
    equipment_join_sql = ' AND '.join(equipment_join_conditions)
    if equipment_join_sql:
        equipment_join_sql = ' AND ' + equipment_join_sql
    c.execute(f'''
        SELECT e.name as equipment_name,
               COUNT(eu.id) as usage_count,
               COALESCE(SUM(eu.duration_minutes), 0) as total_duration_minutes
        FROM equipment e
        LEFT JOIN equipment_usage eu ON e.id = eu.equipment_id{equipment_join_sql}
        GROUP BY e.id, e.name
        ORDER BY total_duration_minutes DESC, usage_count DESC
        LIMIT 10
    ''', equipment_params)
    equipment_usage_top = row_list(c.fetchall())

    # 满意度分析
    c.execute('''
        SELECT
            ROUND(AVG(service_rating), 2) as avg_service,
            ROUND(AVG(equipment_rating), 2) as avg_equipment,
            ROUND(AVG(environment_rating), 2) as avg_environment,
            ROUND(AVG(staff_rating), 2) as avg_staff,
            ROUND(AVG(overall_rating), 2) as avg_overall,
            COUNT(*) as survey_count
        FROM satisfaction_surveys
    ''')
    satisfaction = dict(c.fetchone())

    # 客户活跃度：有预约或有健康档案的客户
    c.execute('''
        SELECT COUNT(DISTINCT customer_id) as n FROM (
            SELECT customer_id FROM appointments
            UNION ALL
            SELECT customer_id FROM health_assessments
        )
    ''')
    active_customers = c.fetchone()['n']
    c.execute('SELECT COUNT(*) as n FROM customers')
    total_customers = c.fetchone()['n']

    conn.close()
    return jsonify({
        'appointment_trend': appointment_trend,
        'appointment_status': appointment_status,
        'equipment_usage_top': equipment_usage_top,
        'satisfaction': satisfaction,
        'customer_activity': {
            'active_customers': active_customers,
            'total_customers': total_customers,
        }
    })


# ========== 导出与下载 ==========
@app.route('/api/export/query-download', methods=['GET'])
def api_export_query_download():
    scope = (request.args.get('scope') or 'single').strip()
    dataset = (request.args.get('dataset') or 'all').strip()
    customer_id = request.args.get('customer_id')

    allowed_datasets = {'all', 'customers', 'health', 'appointments', 'usage', 'surveys'}
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
            c.execute('SELECT id, name FROM customers WHERE id=?', (customer_id,))
            customer = c.fetchone()
            if not customer:
                return jsonify({'error': '客户不存在'}), 404
            customer_name = customer['name']
            name_prefix = f'single_{customer_name}_{customer_id}'
        else:
            name_prefix = 'all_customers'

        queries = {
            'customers': ('客户档案', 'SELECT * FROM customers {where_clause} ORDER BY created_at DESC'),
            'health': ('健康档案', '''SELECT h.*, c.name as customer_name, c.phone
                FROM health_assessments h JOIN customers c ON h.customer_id=c.id
                {where_clause} ORDER BY h.assessment_date DESC'''),
            'appointments': ('预约记录', '''SELECT a.*, c.name as customer_name, c.phone as customer_phone, e.name as equipment_name
                FROM appointments a JOIN customers c ON a.customer_id=c.id LEFT JOIN equipment e ON a.equipment_id=e.id
                {where_clause} ORDER BY a.appointment_date DESC, a.start_time DESC'''),
            'usage': ('仪器使用', '''SELECT eu.*, c.name as customer_name, c.phone, e.name as equipment_name
                FROM equipment_usage eu JOIN customers c ON eu.customer_id=c.id LEFT JOIN equipment e ON eu.equipment_id=e.id
                {where_clause} ORDER BY eu.usage_date DESC'''),
            'surveys': ('满意度', '''SELECT s.*, c.name as customer_name, c.phone
                FROM satisfaction_surveys s JOIN customers c ON s.customer_id=c.id
                {where_clause} ORDER BY s.survey_date DESC'''),
        }

        target_keys = list(queries.keys()) if dataset == 'all' else [dataset]
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        fn = f'{name_prefix}_{dataset}_{ts}.xlsx'
        fp = os.path.join(UPLOAD_FOLDER, fn)

        with pd.ExcelWriter(fp, engine='openpyxl') as writer:
            for key in target_keys:
                sheet_name, sql_tpl = queries[key]
                if scope == 'single':
                    where_clause = 'WHERE c.id = ?' if key != 'customers' else 'WHERE id = ?'
                    df = pd.read_sql_query(sql_tpl.format(where_clause=where_clause), conn, params=(customer_id,))
                else:
                    where_clause = ''
                    df = pd.read_sql_query(sql_tpl.format(where_clause=where_clause), conn)
                df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    finally:
        conn.close()

    return jsonify({'filename': fn, 'download_url': '/api/download/' + fn})


@app.route('/api/export/customers', methods=['GET'])
def api_export_customers():
    conn = get_db()
    df = pd.read_sql_query('SELECT * FROM customers ORDER BY created_at DESC', conn)
    conn.close()
    fn = 'customers_%s.xlsx' % datetime.now().strftime('%Y%m%d_%H%M%S')
    fp = os.path.join(UPLOAD_FOLDER, fn)
    df.to_excel(fp, index=False, engine='openpyxl')
    return jsonify({'filename': fn, 'download_url': '/api/download/' + fn})


@app.route('/api/export/appointments', methods=['GET'])
def api_export_appointments():
    conn = get_db()
    df = pd.read_sql_query('''SELECT a.id, c.name as customer_name, c.phone, e.name as equipment_name, a.appointment_date, a.start_time, a.end_time, a.status, a.notes
        FROM appointments a JOIN customers c ON a.customer_id=c.id LEFT JOIN equipment e ON a.equipment_id=e.id ORDER BY a.appointment_date DESC''', conn)
    conn.close()
    fn = 'appointments_%s.xlsx' % datetime.now().strftime('%Y%m%d_%H%M%S')
    fp = os.path.join(UPLOAD_FOLDER, fn)
    df.to_excel(fp, index=False, engine='openpyxl')
    return jsonify({'filename': fn, 'download_url': '/api/download/' + fn})


@app.route('/api/export/equipment-usage', methods=['GET'])
def api_export_usage():
    conn = get_db()
    df = pd.read_sql_query('''SELECT eu.id, c.name as customer_name, e.name as equipment_name, eu.usage_date, eu.duration_minutes, eu.parameters, eu.notes, eu.operator
        FROM equipment_usage eu JOIN customers c ON eu.customer_id=c.id LEFT JOIN equipment e ON eu.equipment_id=e.id ORDER BY eu.usage_date DESC''', conn)
    conn.close()
    fn = 'equipment_usage_%s.xlsx' % datetime.now().strftime('%Y%m%d_%H%M%S')
    fp = os.path.join(UPLOAD_FOLDER, fn)
    df.to_excel(fp, index=False, engine='openpyxl')
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


@app.route('/api/download/<filename>', methods=['GET'])
def api_download(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)


if __name__ == '__main__':
    init_db()
    print('请在浏览器打开: http://localhost:5000')
    app.run(host='127.0.0.1', port=5000, debug=True)
