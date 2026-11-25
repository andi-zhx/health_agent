import json
import sqlite3
from contextlib import closing
from pathlib import Path
from backend import core

PROJECTS = (
    ('MOXA', '艾灸', 'care'), ('OXYGEN', '高压氧仓', 'professional'),
    ('HEARING', '听力测试', 'screening'), ('INFRARED', '红外理疗', 'care'),
    ('IMMUNO', '荧光免疫分析仪', 'screening'), ('MASSAGE', '按摩机器人', 'care'),
)
PROJECT_BY_CODE = {p[0]: {'code':p[0], 'name':p[1], 'category':p[2]} for p in PROJECTS}
ALIASES = {'艾灸机器人':'MOXA','高压氧舱':'OXYGEN','听力检测仪':'HEARING','听力检测':'HEARING',
           '太空针灸按摩仪':'MASSAGE','手持式干式荧光免疫分析仪':'IMMUNO'}
HOME_NAMES = {'上门康复护理','中医养生咨询','康复训练指导','血糖测试','按摩','非设备上门服务'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS v2_projects(code TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,category TEXT NOT NULL,project_id INTEGER REFERENCES therapy_projects(id));
CREATE TABLE IF NOT EXISTS v2_project_links(legacy_project_id INTEGER PRIMARY KEY REFERENCES therapy_projects(id),proposed_code TEXT REFERENCES v2_projects(code),state TEXT NOT NULL,verified_by TEXT,verified_at TEXT);
CREATE TABLE IF NOT EXISTS v2_archive(table_name TEXT NOT NULL,row_id INTEGER NOT NULL,reason TEXT NOT NULL,original_json TEXT NOT NULL,archived_at TEXT NOT NULL,PRIMARY KEY(table_name,row_id));
CREATE TABLE IF NOT EXISTS v2_migrations(id INTEGER PRIMARY KEY,version TEXT NOT NULL,created_at TEXT NOT NULL,backup_path TEXT,before_counts TEXT,after_counts TEXT,notes TEXT);
CREATE TABLE IF NOT EXISTS v2_accounts(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,role TEXT NOT NULL,customer_id INTEGER REFERENCES customers(id),can_view_personal INTEGER NOT NULL DEFAULT 0,can_export INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_equipment(equipment_id INTEGER PRIMARY KEY REFERENCES equipment(id),project_code TEXT NOT NULL REFERENCES v2_projects(code),asset_code TEXT NOT NULL UNIQUE,maintenance_days INTEGER,registered_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_risks(id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL REFERENCES customers(id),level TEXT NOT NULL,assessed_at TEXT NOT NULL,professional TEXT NOT NULL,notes TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_measurements(id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL REFERENCES customers(id),measured_at TEXT NOT NULL,metric TEXT NOT NULL,value REAL NOT NULL,unit TEXT NOT NULL,source TEXT,report TEXT,opinion TEXT,reference_low REAL,reference_high REAL,target_low REAL,target_high REAL,recorded_by TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_services(id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL REFERENCES customers(id),project_code TEXT REFERENCES v2_projects(code),channel TEXT NOT NULL,status TEXT NOT NULL,scheduled_at TEXT NOT NULL,completed_at TEXT,duration_minutes INTEGER,equipment_id INTEGER REFERENCES equipment(id),concern TEXT,notes TEXT,recorded_by TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_reviews(id INTEGER PRIMARY KEY,service_ref TEXT UNIQUE,customer_id INTEGER NOT NULL REFERENCES customers(id),project_code TEXT NOT NULL REFERENCES v2_projects(code),evaluation_type TEXT NOT NULL,window_start TEXT,window_end TEXT,baseline_at TEXT,evaluated_at TEXT,dimension TEXT,before_score REAL,after_score REAL,status TEXT NOT NULL DEFAULT '未评价',adverse TEXT NOT NULL DEFAULT '未询问',adverse_notes TEXT,notes TEXT,due_date TEXT,followup_status TEXT NOT NULL DEFAULT '待复评',recorded_by TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(customer_id,project_code,evaluation_type,window_start,window_end));
CREATE TABLE IF NOT EXISTS v2_screenings(id INTEGER PRIMARY KEY,service_ref TEXT NOT NULL UNIQUE,customer_id INTEGER NOT NULL REFERENCES customers(id),project_code TEXT NOT NULL REFERENCES v2_projects(code),completed INTEGER NOT NULL DEFAULT 0,valid_report INTEGER NOT NULL DEFAULT 0,abnormal TEXT NOT NULL DEFAULT '未知',report TEXT,professional_opinion TEXT,followup_status TEXT NOT NULL DEFAULT '待跟进',due_date TEXT,followup_result TEXT,recorded_by TEXT NOT NULL,recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_surveys(id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL REFERENCES customers(id),service_ref TEXT,answered_at TEXT NOT NULL,overall INTEGER,attitude INTEGER,guidance INTEGER,device INTEGER,booking INTEGER,environment INTEGER,needs_answered INTEGER NOT NULL DEFAULT 0,needs_json TEXT NOT NULL DEFAULT '[]',comment TEXT,recorded_by TEXT NOT NULL,UNIQUE(service_ref));
CREATE TABLE IF NOT EXISTS v2_tasks(id INTEGER PRIMARY KEY,customer_id INTEGER REFERENCES customers(id),survey_id INTEGER REFERENCES v2_surveys(id),category TEXT NOT NULL,title TEXT NOT NULL,status TEXT NOT NULL DEFAULT '待处理',owner TEXT,due_date TEXT,result TEXT,feedback_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_maintenance(id INTEGER PRIMARY KEY,equipment_id INTEGER NOT NULL REFERENCES equipment(id),fault_type TEXT NOT NULL,reported_at TEXT NOT NULL,down_at TEXT,repair_started_at TEXT,repair_finished_at TEXT,restored_at TEXT,status TEXT NOT NULL,solution TEXT,recorded_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_capacity(id INTEGER PRIMARY KEY,equipment_id INTEGER NOT NULL REFERENCES equipment(id),start_at TEXT NOT NULL,end_at TEXT NOT NULL,UNIQUE(equipment_id,start_at));
CREATE INDEX IF NOT EXISTS v2_measurements_person_date ON v2_measurements(customer_id,measured_at);
CREATE INDEX IF NOT EXISTS v2_services_dates ON v2_services(completed_at,scheduled_at);
CREATE INDEX IF NOT EXISTS v2_reviews_person_date ON v2_reviews(customer_id,evaluated_at);
'''


def counts(conn):
    tables = ('customers','health_assessments','appointments','home_appointments','service_improvement_records','equipment','therapy_projects')
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {table:conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in tables if table in existing}


def before_upgrade():
    """Back up the actual DB before any legacy initializer or catalog migration runs."""
    path = Path(core.DB_PATH)
    if not path.exists():
        return {'path':None,'counts':{}}
    with closing(sqlite3.connect(path)) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='v2_migrations'").fetchone()
        if exists and conn.execute("SELECT 1 FROM v2_migrations WHERE version='2.0'").fetchone():
            return None
        previous = counts(conn)
        folder = path.parent/'database_backups';folder.mkdir(parents=True,exist_ok=True)
        backup = folder/('before_care_v2_'+core.now_local().strftime('%Y%m%d_%H%M%S_%f')+'.db')
        with closing(sqlite3.connect(backup)) as target:
            conn.backup(target)
    return {'path':str(backup),'counts':previous}


def archive(conn,table,row,reason):
    conn.execute('INSERT OR IGNORE INTO v2_archive VALUES (?,?,?,?,?)',
                 (table,row['id'],reason,json.dumps(dict(row),ensure_ascii=False),core.now_local_str()))


def initialize(previous=None):
    with closing(core.get_db()) as conn:
        conn.executescript(SCHEMA)
        for code,name,category in PROJECTS:
            row=conn.execute('SELECT id FROM therapy_projects WHERE name=? ORDER BY id LIMIT 1',(name,)).fetchone()
            if not row:
                pid=conn.execute("INSERT INTO therapy_projects(name,category,duration_minutes,need_equipment,status) VALUES (?,?,30,1,'enabled')",(name,category)).lastrowid
            else:
                pid=row[0]
            conn.execute('INSERT OR IGNORE INTO v2_projects VALUES (?,?,?,?)',(code,name,category,pid))
            conn.execute("INSERT OR IGNORE INTO v2_project_links VALUES (?,?,'confirmed','标准名称',?)",(pid,code,core.now_local_str()))
            conn.execute("UPDATE therapy_projects SET status='enabled' WHERE id=?",(pid,))
            conn.execute("INSERT OR IGNORE INTO project_rules(project_name,allow_home,project_category,status) VALUES (?,1,?,'enabled')",(name,category))
            conn.execute("UPDATE project_rules SET allow_home=1,status='enabled' WHERE project_name=?",(name,))
            for staff in conn.execute('SELECT id FROM staff'):
                conn.execute("INSERT OR IGNORE INTO project_staff_mapping(project_name,staff_id,status) VALUES (?,?,'enabled')",(name,staff[0]))
        canonical={r['project_id']:r['code'] for r in conn.execute('SELECT * FROM v2_projects')}
        for row in conn.execute('SELECT * FROM therapy_projects').fetchall():
            if row['id'] in canonical:
                continue
            proposal=ALIASES.get(row['name'])
            state='pending' if proposal else 'home' if row['name'] in HOME_NAMES else 'archived'
            conn.execute('INSERT OR IGNORE INTO v2_project_links VALUES (?,?,?,NULL,NULL)',(row['id'],proposal,state))
            archive(conn,'therapy_projects',row,'同义项待核验' if proposal else '非正式设备项目，保留历史')
            conn.execute("UPDATE therapy_projects SET status='disabled' WHERE id=?",(row['id'],))
            conn.execute("UPDATE project_equipment_mapping SET status='disabled' WHERE project_name=?",(row['name'],))
            conn.execute("UPDATE project_staff_mapping SET status='disabled' WHERE project_name=?",(row['name'],))
            conn.execute("UPDATE project_rules SET status='disabled' WHERE project_name=?",(row['name'],))
        for code,name,_ in PROJECTS:
            for row in conn.execute('SELECT e.* FROM equipment e JOIN project_equipment_mapping m ON m.equipment_name=e.name WHERE m.project_name=? AND m.status=\'enabled\'',(name,)).fetchall():
                conn.execute('INSERT OR IGNORE INTO v2_equipment VALUES (?,?,?,NULL,?)',(row['id'],code,'EQ-'+str(row['id']).zfill(5),core.now_local_str()))
        activate_confirmed_links(conn)
        if not conn.execute("SELECT 1 FROM v2_migrations WHERE version='2.0'").fetchone():
            previous=previous or {'path':None,'counts':{}}
            after=counts(conn)
            for table in ('customers','health_assessments','appointments','home_appointments','service_improvement_records'):
                if table in previous['counts'] and previous['counts'][table]!=after.get(table):
                    raise RuntimeError('V2 migration count mismatch: '+table)
            conn.execute('INSERT INTO v2_migrations(version,created_at,backup_path,before_counts,after_counts,notes) VALUES (?,?,?,?,?,?)',
                         ('2.0',core.now_local_str(),previous['path'],json.dumps(previous['counts']),json.dumps(after),'非白名单项目逻辑归档；旧名称未自动归并；未物理删除历史记录'))
        conn.commit()


def activate_confirmed_links(conn):
    """Link confirmed aliases without renaming/deleting any historical row."""
    for link in conn.execute("SELECT l.*,p.name AS old_name FROM v2_project_links l JOIN therapy_projects p ON p.id=l.legacy_project_id WHERE l.state='confirmed'").fetchall():
        code=link['proposed_code'];standard=PROJECT_BY_CODE[code]['name']
        devices=conn.execute('SELECT DISTINCT e.* FROM equipment e JOIN project_equipment_mapping m ON m.equipment_name=e.name WHERE m.project_name=?',(link['old_name'],)).fetchall()
        for e in devices:
            existing=conn.execute('SELECT project_code FROM v2_equipment WHERE equipment_id=?',(e['id'],)).fetchone()
            if existing and existing[0]!=code:raise ValueError('设备已经归属另一项目，需先核验台账')
            conn.execute('INSERT OR IGNORE INTO v2_equipment VALUES (?,?,?,NULL,?)',(e['id'],code,'EQ-'+str(e['id']).zfill(5),core.now_local_str()))
            conn.execute("INSERT OR IGNORE INTO project_equipment_mapping(project_name,equipment_name,status) VALUES (?,?,'enabled')",(standard,e['name']))
            conn.execute("UPDATE project_equipment_mapping SET status='enabled' WHERE project_name=? AND equipment_name=?",(standard,e['name']))
