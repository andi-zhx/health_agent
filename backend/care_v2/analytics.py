"""Shared statistics for pages, reports and exports. No population medical averages."""
from collections import Counter,defaultdict
from contextlib import closing
from datetime import date,datetime,timedelta
import json
import re
from backend import core
from .schema import PROJECTS,PROJECT_BY_CODE
from .validation import VALID_STATUS,STATUS,day

UNKNOWN={'','不详','未知','未记录','未填写','未回答','未检测','未监测','未评估','无有效数据'}
EMPTY={'无','无既往病史','无症状','无需求','没有'}


def tags(value):
    if isinstance(value,list): return sorted({str(v).strip() for v in value if str(v).strip() not in UNKNOWN|EMPTY})
    raw=str(value or '').strip()
    try:
        decoded=json.loads(raw)
        if isinstance(decoded,list): return tags(decoded)
    except (ValueError,TypeError): pass
    return sorted({t.strip() for t in re.split(r'[、,，;；\n]',raw) if t.strip() not in UNKNOWN|EMPTY})


def answered(value):
    return str(value or '').strip() not in UNKNOWN


def ratio(n,d): return round(100*n/d,1) if d else None


def age(person,asof):
    try:
        birth=date.fromisoformat(person.get('birth_date') or '')
        end=date.fromisoformat(asof)
        years=end.year-birth.year-((end.month,end.day)<(birth.month,birth.day))
        return years if 0<=years<=130 else None
    except (ValueError,TypeError):
        value=person.get('age')
        return int(value) if value is not None and str(value).isdigit() and 0<=int(value)<=130 else None


def age_band(value):
    if value is None:return '未知'
    if value<60:return '60岁以下'
    if value<70:return '60–69岁'
    if value<80:return '70–79岁'
    if value<90:return '80–89岁'
    return '90岁及以上'


def filters(args):
    today=core.now_local().date()
    end=day(args.get('end')) or today.isoformat()
    start=day(args.get('start')) or today.replace(day=1).isoformat()
    if start>end: raise ValueError('开始日期不能晚于结束日期')
    if (date.fromisoformat(end)-date.fromisoformat(start)).days>3660:raise ValueError('单次查询范围请控制在十年内')
    if end>today.isoformat():raise ValueError('统计结束日期不能晚于今天')
    gender=args.get('gender') or ''
    if gender not in ('','男','女','未知'):raise ValueError('性别筛选无效')
    band=args.get('age') or ''
    if band not in ('','60岁以下','60–69岁','70–79岁','80–89岁','90岁及以上','未知'):raise ValueError('年龄筛选无效')
    project=args.get('project') or ''
    if project and project not in PROJECT_BY_CODE:raise ValueError('项目筛选仅支持六项正式项目')
    return {'start':start,'end':end,'gender':gender,'age':band,'project':project}


def date_in(value,f):return bool(value and f['start']<=str(value)[:10]<=f['end'])


def rows(conn,sql,params=()):return [dict(r) for r in conn.execute(sql,params)]


def dataset():
    with closing(core.get_db()) as conn:
        data={}
        for name,table in [('people','customers'),('assessments','health_assessments'),('risks','v2_risks'),('measurements','v2_measurements'),('reviews','v2_reviews'),('screenings','v2_screenings'),('surveys','v2_surveys'),('tasks','v2_tasks'),('maintenance','v2_maintenance'),('capacity','v2_capacity')]:
            data[name]=rows(conn,'SELECT * FROM '+table)
        data['equipment']=rows(conn,'SELECT v.*,e.name,e.status,e.location FROM v2_equipment v JOIN equipment e ON e.id=v.equipment_id')
        links={r['legacy_project_id']:r for r in rows(conn,'SELECT * FROM v2_project_links')}
        data['settings']=dict(conn.execute('SELECT setting_key,setting_value FROM system_settings'))
        data['pending_projects']=conn.execute("SELECT COUNT(*) FROM v2_project_links WHERE state='pending'").fetchone()[0]
        data['migration']=dict(conn.execute('SELECT * FROM v2_migrations ORDER BY id DESC LIMIT 1').fetchone() or {})
        project_names={r['id']:r['name'] for r in rows(conn,'SELECT id,name FROM therapy_projects')}
        services=[]
        for table,prefix,channel in [('appointments','appointment','onsite'),('home_appointments','home','home')]:
            for r in rows(conn,'SELECT * FROM '+table):
                link=links.get(r.get('project_id'),{})
                code=link.get('proposed_code') if link.get('state')=='confirmed' else None
                historical=not code and not (channel=='home' and link.get('state')=='home')
                stamp=(r.get('appointment_date') or '')+' '+(r.get('start_time') or '00:00')
                end_stamp=(r.get('appointment_date') or '')+' '+(r.get('end_time') or '00:00')
                duration=None
                try:duration=max(0,int((datetime.fromisoformat(end_stamp)-datetime.fromisoformat(stamp)).total_seconds()/60))
                except ValueError:pass
                # Older records lack a completion timestamp: disclose the scheduled-date proxy.
                services.append({'ref':prefix+':'+str(r['id']),'customer_id':r['customer_id'],'project_code':code,'channel':channel,
                    'status':r['status'],'scheduled_at':stamp,'completed_at':end_stamp if r['status']=='completed' else None,
                    'duration_minutes':duration,'equipment_id':r.get('equipment_id'),'notes':r.get('notes'),
                    'recorded_by':'历史记录','date_source':'历史预约日期（未记录实际完成时间）','historical':historical,'concern':'','project_name':project_names.get(r.get('project_id'),'历史项目')})
        for r in rows(conn,'SELECT * FROM v2_services'):
            services.append({**r,'ref':'service:'+str(r['id']),'historical':False,'date_source':'实际完成时间'})
        data['services']=services
        data['legacy_reviews']=rows(conn,'SELECT * FROM service_improvement_records ORDER BY updated_at DESC,id DESC')
    return data


def cohort(data,f):
    people=[]
    selected_ids={s['customer_id'] for s in data['services'] if not s['historical'] and s['project_code']==f['project'] and date_in(s['completed_at'] or s['scheduled_at'],f)} if f['project'] else None
    for person in data['people']:
        if person.get('is_deleted') or (person.get('created_at') and str(person['created_at'])[:10]>f['end']):continue
        gender=person.get('gender') if person.get('gender') in ('男','女') else '未知'
        years=age(person,f['end'])
        if f['gender'] and gender!=f['gender']:continue
        if f['age'] and age_band(years)!=f['age']:continue
        if selected_ids is not None and person['id'] not in selected_ids:continue
        people.append({**person,'current_age':years,'gender_group':gender,'age_band':age_band(years)})
    return people


def latest(records,key,date_key,end):
    result={}
    for r in sorted(records,key=lambda x:(str(x.get(date_key) or ''),x['id']),reverse=True):
        if r.get(date_key) and str(r[date_key])[:10]<=end:result.setdefault(r[key],r)
    return result


def ranking(counter,denominator=None):
    return [{'name':name,'count':count,'denominator':denominator,'percent':ratio(count,denominator) if denominator is not None else None} for name,count in counter.most_common()]


def health(data,people,f):
    assessments=latest(data['assessments'],'customer_id','assessment_date',f['end'])
    risks=latest(data['risks'],'customer_id','assessed_at',f['end'])
    population=len(people);ids={p['id'] for p in people}
    records={cid:a for cid,a in assessments.items() if cid in ids}
    diseases=Counter();symptoms=Counter();needs=Counter();exercise=Counter();smoke=Counter();drink=Counter();sleep=Counter();risk=Counter();coexist=Counter()
    disease_den=symptom_den=need_den=exercise_den=0
    complete=Counter();demographic=Counter();age_disease=defaultdict(Counter);age_valid=Counter();cooccurrence=Counter()
    detection={k:{'name':label,'valid':0,'abnormal':0} for k,label in [('blood_pressure_test','血压检测'),('blood_sugar_test','血糖检测'),('blood_lipid_test','血脂检测')]}
    person_tags={}
    for person in people:
        cid=person['id'];a=records.get(cid,{})
        demographic[(person['age_band'],person['gender_group'])]+=1
        risk[risks[cid]['level'] if cid in risks else '未评估']+=1
        for key in ('past_medical_history','recent_symptoms','sleep_quality','exercise_methods','health_needs'):
            complete[key]+=int(answered(a.get(key)))
        hist=tags(a.get('past_medical_history'));sym=tags(a.get('recent_symptoms'))
        person_tags[cid]={'diseases':hist,'symptoms':sym,'risk':risks[cid]['level'] if cid in risks else '未评估','missing':not a}
        if answered(a.get('past_medical_history')):
            disease_den+=1;diseases.update(hist);coexist[str(len(hist)) if len(hist)<3 else '3项及以上']+=1;age_valid[person['age_band']]+=1
            age_disease[person['age_band']].update(hist)
            for left in hist:
                for right in hist:cooccurrence[(left,right)]+=1
        else:coexist['未知']+=1
        if answered(a.get('recent_symptoms')):symptom_den+=1;symptoms.update(sym)
        if answered(a.get('health_needs')):need_den+=1;needs.update(tags(a['health_needs']))
        if answered(a.get('exercise_methods')):exercise_den+=1;exercise.update(tags(a['exercise_methods']))
        for field,counter in [('smoking_status',smoke),('drinking_status',drink),('sleep_quality',sleep)]:
            counter[str(a.get(field)) if answered(a.get(field)) else '未知']+=1
        for key,stat in detection.items():
            value=a.get(key)
            if value in ('正常','偏高','偏低','监测：正常','监测：偏高','监测：偏低'):
                stat['valid']+=1;stat['abnormal']+=int('偏' in value)
    for stat in detection.values():stat.update(rate=ratio(stat['abnormal'],stat['valid']),missing=population-stat['valid'])
    bands=('60岁以下','60–69岁','70–79岁','80–89岁','90岁及以上','未知');top=[x for x,_ in diseases.most_common(8)]
    return {'population':population,'assessed':len(records),'assessment_coverage':ratio(len(records),population),
        'demographics':[{'age':b,'male':demographic[(b,'男')],'female':demographic[(b,'女')],'unknown':demographic[(b,'未知')],'total':sum(demographic[(b,g)] for g in ('男','女','未知'))} for b in bands],
        'diseases':ranking(diseases,disease_den),'symptoms':ranking(symptoms,symptom_den),'disease_denominator':disease_den,'symptom_denominator':symptom_den,
        'risk':[{'name':r,'count':risk[r]} for r in ('常规管理','重点关注','紧急跟进','未评估')],
        'coexist':[{'name':k,'count':coexist[k]} for k in ('0','1','2','3项及以上','未知')],
        'cooccurrence':{'labels':top,'matrix':[[cooccurrence[(a,b)] for b in top] for a in top]},
        'age_health':{'labels':top,'rows':[{'age':b,'n':sum(demographic[(b,g)] for g in ('男','女','未知')),'valid':age_valid[b],'counts':[age_disease[b][label] for label in top]} for b in bands]},
        'behaviors':{'smoking':ranking(smoke,population),'drinking':ranking(drink,population),'sleep':ranking(sleep,population),'exercise':ranking(exercise,exercise_den),'exercise_unknown':population-exercise_den},
        'needs':ranking(needs,need_den),'detection':list(detection.values()),
        'completeness':[{'name':label,'valid':complete[k],'expected':population,'percent':ratio(complete[k],population)} for k,label in [('past_medical_history','病史'),('recent_symptoms','近期症状'),('sleep_quality','睡眠回答'),('exercise_methods','运动方式'),('health_needs','健康需求')]],
        'sampling_note':'截至期末每人最新评估；风险仅采用专业人员确认结果。未检测、未回答与正常分别处理。',
        '_person_tags':person_tags}


def month_keys(f):
    current=date.fromisoformat(f['start']).replace(day=1);end=date.fromisoformat(f['end'])
    result=[]
    while current<=end:
        result.append(current.strftime('%Y-%m'));current=(current.replace(day=28)+timedelta(days=4)).replace(day=1)
    return result


def union_minutes(intervals):
    merged=[]
    for start,end in sorted(intervals):
        if end<=start:continue
        if merged and start<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],end)
        else:merged.append([start,end])
    return sum((e-s).total_seconds()/60 for s,e in merged)


def capacity_stats(data,completed,f):
    low=datetime.fromisoformat(f['start']);high=datetime.fromisoformat(f['end'])+timedelta(days=1)
    shifts=defaultdict(list);downs=defaultdict(list);busy=defaultdict(list)
    equipment={e['equipment_id']:e for e in data['equipment'] if not f['project'] or e['project_code']==f['project']}
    for r in data['capacity']:
        if r['equipment_id'] in equipment:shifts[r['equipment_id']].append((max(low,datetime.fromisoformat(r['start_at'])),min(high,datetime.fromisoformat(r['end_at']))))
    for r in data['maintenance']:
        if r['down_at']:
            end=datetime.fromisoformat(r['restored_at']) if r['restored_at'] else min(high,core.now_local().replace(tzinfo=None))
            downs[r['equipment_id']].append((datetime.fromisoformat(r['down_at']),end))
    for s in completed:
        if s['equipment_id'] and s['duration_minutes']:
            end=datetime.fromisoformat(s['completed_at']);start=end-timedelta(minutes=s['duration_minutes'])
            busy[s['equipment_id']].append((start,end))
    planned=down=used=0
    for eid,windows in shifts.items():
        planned+=union_minutes(windows)
        down+=union_minutes([(max(a,c),min(b,d)) for a,b in windows for c,d in downs[eid]])
        used+=union_minutes([(max(a,c),min(b,d)) for a,b in windows for c,d in busy[eid]])
    available=max(0,planned-down)
    return {'planned_minutes':round(planned,1),'downtime_minutes':round(down,1),'used_minutes':round(used,1),
            'availability':ratio(available,planned),'utilization':ratio(used,available) if available and used<=available else None,
            'note':'仅计算有排班时长台账的设备；使用时长与停机时长按区间去重。不具备分母时显示—。'}


def service_scope(data,people,f):
    ids={p['id'] for p in people}
    eligible=[s for s in data['services'] if s['customer_id'] in ids and not s['historical'] and (not f['project'] or s['project_code']==f['project'])]
    completed=[s for s in eligible if s['status']=='completed' and date_in(s['completed_at'],f)]
    booked=[s for s in eligible if date_in(s['scheduled_at'],f)]
    return completed,booked


def operations(data,people,f):
    completed,booked=service_scope(data,people,f)
    active_booked=[s for s in booked if s['status']!='cancelled']
    person_counts=Counter(s['customer_id'] for s in completed)
    codes=[p[0] for p in PROJECTS];months=month_keys(f)
    equipment_ids={e['equipment_id'] for e in data['equipment'] if not f['project'] or e['project_code']==f['project']}
    maintenance=[r for r in data['maintenance'] if r['equipment_id'] in equipment_ids and date_in(r['reported_at'],f)]
    home=[s for s in completed if s['channel']=='home']
    cap=capacity_stats(data,completed,f)
    return {'summary':{'bookings':len(booked),'booking_eligible':len(active_booked),'booking_completed':sum(s['status']=='completed' and str(s['completed_at'] or '')[:10]<=f['end'] for s in active_booked),
        'people':len(person_counts),'services':len(completed),'fulfillment':ratio(sum(s['status']=='completed' and str(s['completed_at'] or '')[:10]<=f['end'] for s in active_booked),len(active_booked)),
        'per_person':round(len(completed)/len(person_counts),2) if person_counts else None,'repeat_people':sum(n>=2 for n in person_counts.values()),'repeat_rate':ratio(sum(n>=2 for n in person_counts.values()),len(person_counts)),
        'home_services':len(home),'home_people':len({s['customer_id'] for s in home}),'availability':cap['availability'],'utilization':cap['utilization']},
        'projects':[{'code':code,'name':PROJECT_BY_CODE[code]['name'],'category':PROJECT_BY_CODE[code]['category'],'services':sum(s['project_code']==code for s in completed),'people':len({s['customer_id'] for s in completed if s['project_code']==code})} for code in codes],
        'months':[{'month':m,'projects':{code:sum(s['project_code']==code and s['completed_at'].startswith(m) for s in completed) for code in codes}} for m in months],
        'maintenance':maintenance,'faults':ranking(Counter(r['fault_type'] for r in maintenance)),
        'home_months':[{'month':m,'services':sum(s['completed_at'].startswith(m) for s in home),'people':len({s['customer_id'] for s in home if s['completed_at'].startswith(m)})} for m in months],
        'home_records':home,'service_records':completed,'capacity':cap,
        'legacy_date_count':sum(s['date_source'].startswith('历史') for s in completed),
        'sampling_note':'完成人次按实际完成日期；历史未记录完成时间时使用预约结束日期并单列。人数跨项目去重，上门是渠道，同一服务只计一次。履约率分母排除已取消预约。'}


def effects(data,people,f):
    completed,_=service_scope(data,people,f)
    ids={p['id'] for p in people};service_map={s['ref']:s for s in completed}
    single={r['service_ref']:r for r in data['reviews'] if r['evaluation_type']=='single' and (not r.get('evaluated_at') or str(r['evaluated_at'])[:10]<=f['end'])}
    screening={r['service_ref']:r for r in data['screenings'] if str(r['recorded_at'])[:10]<=f['end']}
    legacy={}
    for r in data['legacy_reviews']:
        kind='home' if r['service_type'] in ('home','home_appointments') else 'appointment'
        if r['service_id']:legacy.setdefault(kind+':'+str(r['service_id']),r)
    result=[];entries=[];screening_rows=[];use_buckets=defaultdict(Counter);use_n=Counter()
    cumulative=Counter();service_order=sorted([s for s in data['services'] if not s['historical'] and s['status']=='completed' and s['customer_id'] in ids and s['completed_at'] and s['completed_at'][:10]<=f['end']],key=lambda x:(x['completed_at'],x['ref']))
    use_number={}
    for s in service_order:
        cumulative[(s['customer_id'],s['project_code'])]+=1;use_number[s['ref']]=cumulative[(s['customer_id'],s['project_code'])]
    for code,name,category in PROJECTS:
        subset=[s for s in completed if s['project_code']==code]
        dist=Counter();rated=[]
        for s in subset:
            r=single.get(s['ref'],{})
            legacy_row=legacy.get(s['ref'])
            status=r.get('status','未评价') if category!='screening' else '不适用'
            dist[status]+=1
            entry={**s,**r,'service_ref':s['ref'],'project_code':code,'customer_id':s['customer_id'],'status':status,'legacy_unverified':bool(legacy_row and not r),'legacy_status':legacy_row['improvement_status'] if legacy_row else None,'record_id':r.get('id'),'evaluation_type':'single'}
            entries.append(entry)
            if status in VALID_STATUS:
                rated.append(entry);num=use_number[s['ref']];bucket='1次' if num==1 else '2–3次' if num<=3 else '4–6次' if num<=6 else '7次及以上'
                use_buckets[bucket][status]+=1;use_n[bucket]+=1
            if category=='screening':
                screen=screening.get(s['ref'],{})
                screening_rows.append({**s,**screen,'service_ref':s['ref'],'screening_id':screen.get('id')})
        improved=sum(r['status'] in ('明显改善','部分改善') for r in rated)
        applicable=len(subset)-dist['不适用']
        result.append({'code':code,'name':name,'category':category,'services':len(subset),'valid':len(rated),'applicable':applicable,'improved':improved,'rate':ratio(improved,len(rated)) if category!='screening' else None,'coverage':ratio(len(rated),applicable),'distribution':{status:dist[status] for status in STATUS},'small_sample':len(rated)<5})
    stages=[r for r in data['reviews'] if r['evaluation_type']=='stage' and r['customer_id'] in ids and (not f['project'] or r['project_code']==f['project']) and date_in(r['window_end'],f)]
    # Unique database constraint: one person/project/evaluation window, never mixed with single-service reviews.
    stage_months=[]
    for m in month_keys(f):
        scope=[r for r in stages if r['window_end'].startswith(m)]
        latest_person_project={}
        for r in sorted(scope,key=lambda r:(r['window_end'],r['id'])):latest_person_project[(r['customer_id'],r['project_code'])]=r
        current=list(latest_person_project.values());c=Counter('未复评' if not r['evaluated_at'] or r['evaluated_at'][:10]>f['end'] or r['status'] not in VALID_STATUS else '改善' if r['status'] in ('明显改善','部分改善') else '稳定' if r['status']=='无变化' else '加重' for r in current)
        stage_months.append({'month':m,'improved':c['改善'],'stable':c['稳定'],'worse':c['加重'],'not_reviewed':c['未复评'],'n':len(current)})
    valid=sum(p['valid'] for p in result);applicable=sum(p['applicable'] for p in result);improved=sum(p['improved'] for p in result)
    return {'projects':result,'records':entries,'stage_records':stages,'stage_months':stage_months,'usage_groups':[{'name':k,'valid':use_n[k],'distribution':{s:use_buckets[k][s] for s in VALID_STATUS}} for k in ('1次','2–3次','4–6次','7次及以上')],
        'screenings':screening_rows,'screening_summary':[{'code':code,'name':PROJECT_BY_CODE[code]['name'],'services':sum(r['project_code']==code for r in screening_rows),'completed':sum(r['project_code']==code and r.get('completed')==1 for r in screening_rows),'valid_reports':sum(r['project_code']==code and r.get('valid_report')==1 for r in screening_rows),'abnormal':sum(r['project_code']==code and r.get('abnormal')=='异常' for r in screening_rows),'followed':sum(r['project_code']==code and r.get('abnormal')=='异常' and r.get('followup_status')=='已跟进' for r in screening_rows)} for code in ('HEARING','IMMUNO')],
        'summary':{'valid':valid,'applicable':applicable,'improved':improved,'rate':ratio(improved,valid),'coverage':ratio(valid,applicable),'legacy_unverified':sum(e['legacy_unverified'] for e in entries)},
        'sampling_note':'单次评价按服务去重；阶段评价按人/项目/窗口去重。同月同人同项目取期末窗口。检测类不参与改善率。历史反馈先核验，不将旧默认“无改善”计为有效评价。'}


def satisfaction(data,people,f):
    ids={p['id'] for p in people};service_refs={s['ref'] for s in data['services'] if not s['historical'] and (not f['project'] or s['project_code']==f['project'])}
    records=[r for r in data['surveys'] if r['customer_id'] in ids and date_in(r['answered_at'],f) and (not f['project'] or r['service_ref'] in service_refs)]
    valid=[r for r in records if r['overall'] is not None];needs=Counter()
    latest_needs={}
    for r in sorted(records,key=lambda r:(r['answered_at'],r['id'])):
        if r['needs_answered']:latest_needs[r['customer_id']]=r
    for r in latest_needs.values():needs.update(set(tags(r['needs_json'])))
    need_n=len(latest_needs)
    completed,_=service_scope(data,people,f);eligible={s['customer_id'] for s in completed};responders={r['customer_id'] for r in valid}
    dimensions=[]
    for key,label in [('attitude','服务态度'),('guidance','专业指导'),('device','设备体验'),('booking','预约便利性'),('environment','环境舒适度')]:
        scores=[r[key] for r in records if r[key] is not None]
        dimensions.append({'name':label,'valid':len(scores),'score':round(sum(scores)/len(scores),2) if scores else None})
    tasks=[t for t in data['tasks'] if (not t['customer_id'] or t['customer_id'] in ids) and date_in(t['created_at'],f)]
    return {'summary':{'valid':len(valid),'satisfied':sum(r['overall']>=4 for r in valid),'rate':ratio(sum(r['overall']>=4 for r in valid),len(valid)),'eligible_people':len(eligible),'responded_people':len(eligible&responders),'coverage':ratio(len(eligible&responders),len(eligible)),'not_responded':len(eligible-responders),'needs_answered':need_n},
        'distribution':[{'name':label,'count':sum(r['overall']==score for r in valid)} for score,label in [(5,'很满意'),(4,'满意'),(3,'一般'),(2,'不满意'),(1,'很不满意')]],
        'dimensions':dimensions,'needs':ranking(needs,need_n),'tasks':tasks,'records':records,
        'sampling_note':'按问卷回答日期统计；总体及各维度按有效回答计算。需求取每人期间最近一次有效答题，分母按人去重。覆盖率为期间服务人群中已答总体问题人数/服务人数；无关联问卷可参与问卷分布，不增加无服务对象的覆盖率。'}


def overview(data,people,f,health_data,ops,effect,survey):
    ids={p['id'] for p in people};todo=[]
    adverse=sum((r.get('adverse')=='有不适' or r['status']=='加重') and r.get('followup_status','待复评')=='待复评' for r in effect['records'])
    if adverse:todo.append({'kind':'adverse','name':'异常体验待核实','count':adverse,'page':'v2-effects'})
    follow=[r for r in data['reviews'] if r['customer_id'] in ids and r.get('due_date') and r['due_date']<=f['end'] and r['followup_status']=='待复评']
    if follow:todo.append({'kind':'followup','name':'到期复评','count':len(follow),'page':'v2-effects'})
    screen=sum(r.get('abnormal')=='异常' and r.get('followup_status')!='已跟进' for r in effect['screenings'])
    if screen:todo.append({'kind':'screening','name':'检测异常待跟进','count':screen,'page':'v2-effects'})
    repairs=sum(not r['restored_at'] for r in ops['maintenance'])
    if repairs:todo.append({'kind':'repair','name':'设备待维修','count':repairs,'page':'v2-operations'})
    missing=health_data['population']-health_data['assessed']
    if missing:todo.append({'kind':'missing','name':'健康评估待补齐','count':missing,'page':'health'})
    pending=sum(t['status'] not in ('已完成','已反馈') for t in survey['tasks'])
    if pending:todo.append({'kind':'opinion','name':'意见待处理','count':pending,'page':'v2-satisfaction'})
    previous=dict(f);span=(date.fromisoformat(f['end'])-date.fromisoformat(f['start'])).days+1
    previous['end']=(date.fromisoformat(f['start'])-timedelta(days=1)).isoformat();previous['start']=(date.fromisoformat(f['start'])-timedelta(days=span)).isoformat()
    pp=cohort(data,previous);po=operations(data,pp,previous);pe=effects(data,pp,previous);ps=satisfaction(data,pp,previous)
    return {'summary':{'assessed':health_data['assessed'],'priority':sum(r['count'] for r in health_data['risk'] if r['name'] in ('重点关注','紧急跟进')),
        'services':ops['summary']['services'],'people':ops['summary']['people'],'improvement_rate':effect['summary']['rate'],'valid_reviews':effect['summary']['valid'],'satisfaction_rate':survey['summary']['rate'],'valid_surveys':survey['summary']['valid']},
        'previous':{'start':previous['start'],'end':previous['end'],'services':po['summary']['services'],'people':po['summary']['people'],'improvement_rate':pe['summary']['rate'],'satisfaction_rate':ps['summary']['rate']},'todos':todo}


def snapshot(f,data=None):
    data=data or dataset();people=cohort(data,f)
    h=health(data,people,f);o=operations(data,people,f);e=effects(data,people,f);s=satisfaction(data,people,f)
    d=overview(data,people,f,h,o,e,s)
    return {'filters':f,'health':h,'operations':o,'effects':e,'satisfaction':s,'dashboard':d,'demo':data['settings'].get('demo_mode')=='true','unit_name':data['settings'].get('unit_name','军休所智慧康养'),
            'pending_projects':data['pending_projects'],'cohort_note':'按干部建档日期截至期末纳入；年龄按期末计算。项目筛选限定期间使用该项目的人群，个人档案不受本筛选限制。','_people':people,'_data':data}
