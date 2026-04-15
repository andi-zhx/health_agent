#!/usr/bin/env python3
"""清理旧业务数据并生成50位客户全链路样本数据。"""

import random
import sqlite3
from datetime import datetime, timedelta

from app import DB_PATH, init_db

SAMPLE_CUSTOMER_COUNT = 50
RANDOM_SEED = 20260415


LAST_NAMES = [
    '赵', '钱', '孙', '李', '周', '吴', '郑', '王', '冯', '陈',
    '褚', '卫', '蒋', '沈', '韩', '杨', '朱', '秦', '尤', '许',
]
FIRST_NAMES = [
    '建国', '丽华', '文静', '国强', '海燕', '志远', '秀兰', '晨曦', '明辉', '嘉怡',
    '宇航', '欣妍', '振华', '思敏', '天宇', '若琳', '东升', '可心', '宏伟', '雅雯',
]


def fmt_day(offset_days: int) -> str:
    return (datetime.now() - timedelta(days=offset_days)).strftime('%Y-%m-%d')


def fmt_ts(offset_days: int, hour: int, minute: int) -> str:
    dt = datetime.now() - timedelta(days=offset_days)
    return dt.replace(hour=hour, minute=minute, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')


def clear_legacy_data(cursor: sqlite3.Cursor) -> None:
    # 先清理存在外键依赖的明细，再清理主业务表。
    tables_in_order = [
        'improvement_record_files',
        'service_improvement_records',
        'business_history_logs',
        'home_appointments',
        'appointments',
        'visit_checkins',
        'health_records',
        'health_assessments',
        'audit_logs',
        'task_execution_logs',
        'customers',
    ]
    for table_name in tables_in_order:
        cursor.execute(f'DELETE FROM {table_name}')


def pick_project(cursor: sqlite3.Cursor):
    cursor.execute(
        "SELECT id, name, duration_minutes FROM therapy_projects WHERE status='enabled' ORDER BY id"
    )
    return cursor.fetchall()


def pick_equipment(cursor: sqlite3.Cursor):
    cursor.execute("SELECT id, name FROM equipment WHERE status='available' ORDER BY id")
    return cursor.fetchall()


def pick_staff(cursor: sqlite3.Cursor):
    cursor.execute("SELECT id, name FROM staff ORDER BY id")
    return cursor.fetchall()


def seed_samples() -> dict:
    random.seed(RANDOM_SEED)
    init_db()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON;')
    c = conn.cursor()

    projects = pick_project(c)
    equipment = pick_equipment(c)
    staff_list = pick_staff(c)
    if not projects or not equipment or not staff_list:
        raise RuntimeError('基础主数据不足：请确认therapy_projects/equipment/staff已初始化。')

    conn.execute('BEGIN')
    clear_legacy_data(c)

    for idx in range(1, SAMPLE_CUSTOMER_COUNT + 1):
        name = random.choice(LAST_NAMES) + random.choice(FIRST_NAMES)
        gender = '男' if idx % 2 else '女'
        age = random.randint(28, 76)
        birth_year = datetime.now().year - age
        birth_date = f'{birth_year}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}'
        id_card = f'11010119{random.randint(60, 99):02d}{random.randint(1, 12):02d}{random.randint(1, 28):02d}{idx:04d}'
        phone = f'13{random.randint(100000000, 999999999)}'
        email = f'customer{idx:02d}@example.com'
        address = f'北京市朝阳区康复路{idx}号'

        c.execute(
            '''
            INSERT INTO customers (
                name, id_card, phone, email, address, gender, age, birth_date,
                identity_type, military_rank, record_creator, medical_history, allergies,
                diet_habits, chronic_diseases, health_status, therapy_contraindications,
                created_at, updated_at, is_deleted
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
            ''',
            (
                name,
                id_card,
                phone,
                email,
                address,
                gender,
                age,
                birth_date,
                '地方人员',
                '无',
                '系统样本脚本',
                '无重大手术史',
                '无',
                '清淡饮食',
                random.choice(['高血压', '无', '糖耐量异常']),
                random.choice(['稳定', '需关注']),
                random.choice(['无', '急性炎症期禁做强刺激理疗']),
                fmt_ts(60 - idx, 9, 0),
                fmt_ts(1, 10, idx % 60),
            ),
        )
        customer_id = c.lastrowid

        assessment_date = fmt_day(random.randint(1, 45))
        height_cm = round(random.uniform(152, 183), 1)
        weight_kg = round(random.uniform(48, 86), 1)

        c.execute(
            '''
            INSERT INTO health_assessments (
                customer_id, assessment_date, assessor, age, height_cm, weight_kg, address,
                past_medical_history, family_history, allergy_history, allergy_details,
                smoking_status, smoking_years, cigarettes_per_day, drinking_status, drinking_years,
                sleep_quality, sleep_hours, recent_symptoms, recent_symptom_detail,
                life_impact_issues, blood_pressure_test, blood_lipid_test, blood_sugar_test,
                chronic_pain, pain_details, exercise_methods, health_needs, notes, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                customer_id,
                assessment_date,
                random.choice(['王医生', '李医生', '赵医生']),
                age,
                height_cm,
                weight_kg,
                address,
                random.choice(['颈椎不适', '腰肌劳损', '无']),
                random.choice(['父亲高血压', '母亲糖尿病', '无明显家族史']),
                random.choice(['无', '有']),
                random.choice(['青霉素轻度过敏', '无']),
                random.choice(['从不', '已戒烟', '偶尔']),
                random.randint(0, 15),
                random.randint(0, 12),
                random.choice(['从不', '偶尔', '每周']),
                random.randint(0, 10),
                random.choice(['良好', '一般']),
                random.choice(['6-7小时', '7-8小时']),
                random.choice(['颈肩酸痛', '腰背紧张', '睡眠不稳']),
                '活动后加重，休息后可缓解',
                random.choice(['久坐办公影响工作效率', '晨起僵硬影响活动']),
                random.choice(['正常', '偏高']),
                random.choice(['正常', '边缘偏高']),
                random.choice(['正常', '轻度偏高']),
                random.choice(['有', '无']),
                random.choice(['颈肩部肌肉紧张', '腰骶部压痛', '无明显痛点']),
                random.choice(['快走', '拉伸训练', '核心训练']),
                random.choice(['缓解疼痛', '改善睡眠', '提高活动能力']),
                '建议继续阶段性理疗与家庭训练',
                fmt_ts(50 - idx, 14, 0),
            ),
        )

        c.execute(
            '''
            INSERT INTO health_records (
                customer_id, record_date, height_cm, weight_kg, blood_pressure, symptoms, diagnosis, notes, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ''',
            (
                customer_id,
                assessment_date,
                height_cm,
                weight_kg,
                random.choice(['118/76', '126/82', '132/86']),
                random.choice(['肩颈紧张', '腰背酸痛', '睡眠浅']),
                random.choice(['肌筋膜劳损', '颈椎退行性改变', '功能性疲劳']),
                '建议每周2次理疗并配合居家拉伸',
                fmt_ts(48 - idx, 15, 30),
            ),
        )

        c.execute(
            '''
            INSERT INTO visit_checkins (customer_id, checkin_time, purpose, notes, created_at)
            VALUES (?,?,?,?,?)
            ''',
            (
                customer_id,
                fmt_ts(random.randint(1, 20), 9 + idx % 8, 10),
                random.choice(['复诊', '初诊评估', '理疗复查']),
                '前台签到样本记录',
                fmt_ts(random.randint(1, 20), 9 + idx % 8, 12),
            ),
        )

        project = random.choice(projects)
        equip = random.choice(equipment)
        staff = random.choice(staff_list)
        app_date = fmt_day(random.randint(0, 20))
        start_hour = 9 + (idx % 8)
        start_time = f'{start_hour:02d}:00'
        end_time = f'{(start_hour + 1):02d}:00'

        c.execute(
            '''
            INSERT INTO appointments (
                customer_id, equipment_id, project_id, staff_id, appointment_date, start_time, end_time,
                status, checkin_status, has_companion, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                customer_id,
                equip['id'],
                project['id'],
                staff['id'],
                app_date,
                start_time,
                end_time,
                random.choice(['scheduled', 'completed']),
                random.choice(['pending', 'checked_in']),
                random.choice(['有', '无']),
                f'{project["name"]}门店预约样本',
                fmt_ts(random.randint(5, 30), start_hour, 0),
                fmt_ts(random.randint(1, 4), start_hour + 1, 0),
            ),
        )
        appointment_id = c.lastrowid

        home_project = random.choice(projects)
        home_staff = random.choice(staff_list)
        home_date = fmt_day(random.randint(0, 25))
        home_start = 10 + (idx % 6)

        c.execute(
            '''
            INSERT INTO home_appointments (
                customer_id, project_id, staff_id, customer_name, phone, home_time, home_address,
                service_project, staff_name, appointment_date, start_time, end_time, location,
                contact_person, contact_phone, has_companion, notes, status, checkin_status,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                customer_id,
                home_project['id'],
                home_staff['id'],
                name,
                phone,
                f'{home_start:02d}:00-{home_start+1:02d}:00',
                address,
                home_project['name'],
                home_staff['name'],
                home_date,
                f'{home_start:02d}:00',
                f'{home_start + 1:02d}:00',
                address,
                random.choice(['家属', '本人']),
                f'13{random.randint(100000000, 999999999)}',
                random.choice(['有', '无']),
                f'{home_project["name"]}上门服务样本',
                random.choice(['scheduled', 'completed']),
                random.choice(['pending', 'checked_in']),
                fmt_ts(random.randint(3, 25), home_start, 5),
                fmt_ts(random.randint(1, 3), home_start + 1, 5),
            ),
        )

        c.execute(
            '''
            INSERT INTO service_improvement_records (
                service_id, service_type, customer_id, service_time, service_project,
                pre_service_status, service_content, post_service_evaluation,
                improvement_status, followup_time, followup_date, followup_method,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                appointment_id,
                'appointments',
                customer_id,
                fmt_ts(random.randint(0, 20), 16, 0),
                project['name'],
                random.choice(['疼痛评分6分', '活动受限明显', '睡眠质量一般']),
                random.choice(['热疗+筋膜放松', '超声理疗+牵伸', '电刺激+康复训练']),
                random.choice(['疼痛下降至3分', '关节活动度改善', '睡眠改善']),
                random.choice(['持续改善', '需持续跟进']),
                random.choice(['24小时后电话回访', '3天后到店复查']),
                fmt_day(random.randint(1, 10)),
                random.choice(['电话', '微信', '门店复诊']),
                fmt_ts(random.randint(0, 15), 17, 20),
                fmt_ts(random.randint(0, 2), 18, 0),
            ),
        )
        improvement_id = c.lastrowid

        c.execute(
            '''
            INSERT INTO improvement_record_files (
                customer_id, improvement_record_id, file_name, file_ext, file_path, file_size, uploaded_at
            ) VALUES (?,?,?,?,?,?,?)
            ''',
            (
                customer_id,
                improvement_id,
                f'improvement_{customer_id:03d}.pdf',
                '.pdf',
                f'uploads/improvement_{customer_id:03d}.pdf',
                random.randint(80_000, 300_000),
                fmt_ts(random.randint(0, 10), 19, 10),
            ),
        )

    conn.commit()

    table_counts = {}
    for table_name in [
        'customers',
        'health_assessments',
        'health_records',
        'visit_checkins',
        'appointments',
        'home_appointments',
        'service_improvement_records',
        'improvement_record_files',
    ]:
        c.execute(f'SELECT COUNT(*) AS n FROM {table_name}')
        table_counts[table_name] = c.fetchone()['n']

    conn.close()
    return table_counts


if __name__ == '__main__':
    counts = seed_samples()
    print('样本数据生成完成：')
    for table, count in counts.items():
        print(f'  - {table}: {count}')
