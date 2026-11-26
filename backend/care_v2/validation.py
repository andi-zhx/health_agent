from datetime import datetime,date
import math
from backend import core
from .schema import PROJECT_BY_CODE

METRICS={
 'systolic':('收缩压','mmHg',30,300),'diastolic':('舒张压','mmHg',20,200),
 'glucose':('血糖','mmol/L',0.1,60),'cholesterol':('总胆固醇','mmol/L',0.1,30),
 'triglycerides':('甘油三酯','mmol/L',0.1,50),'hdl':('高密度脂蛋白','mmol/L',0.1,10),
 'ldl':('低密度脂蛋白','mmol/L',0.1,20),'spo2':('血氧饱和度','%',1,100),
 'pain':('疼痛评分','分（0无痛，10最痛）',0,10),
}
STATUS=('明显改善','部分改善','无变化','加重','未评价','不适用')
VALID_STATUS=STATUS[:4]
DIMENSIONS=('疼痛影响','局部不适','疲劳感','睡眠困扰','活动不便','主观不舒适度','专业目标困扰程度')
NEEDS=('增加康养设备','健康讲座','医师指导','定期健康检测','上门服务','其他')


def text(value,maximum=2000,required=False):
    result=str(value or '').strip()
    if required and not result: raise ValueError('必填内容不能为空')
    if len(result)>maximum: raise ValueError(f'文字不能超过 {maximum} 字')
    return result


def number(value,minimum,maximum,required=False,integer=False):
    if value in ('',None):
        if required: raise ValueError('请填写必填数值')
        return None
    try: result=float(value)
    except (TypeError,ValueError): raise ValueError('数值格式不正确')
    if isinstance(value,bool) or not math.isfinite(result) or not minimum<=result<=maximum or (integer and not result.is_integer()):
        raise ValueError(f'数值须在 {minimum}–{maximum} 之间'+('且为整数' if integer else ''))
    return int(result) if integer else result


def choice(value,choices,default=None):
    value=value or default
    if value not in choices: raise ValueError('选项不合法：'+str(value))
    return value


def timestamp(value,required=True,future=False):
    if not value:
        if required: raise ValueError('请填写日期时间')
        return None
    try:
        parsed=datetime.fromisoformat(str(value))
    except (ValueError,TypeError): raise ValueError('日期时间格式不正确')
    now=core.now_local()
    if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=now.tzinfo)
    parsed=parsed.astimezone(now.tzinfo)
    if not future and parsed>now: raise ValueError('实际发生时间不能晚于当前时间')
    return parsed.strftime('%Y-%m-%d %H:%M:%S')


def day(value,required=False):
    if not value:
        if required: raise ValueError('请填写日期')
        return None
    try: return date.fromisoformat(str(value)).isoformat()
    except (ValueError,TypeError): raise ValueError('日期格式不正确')


def customer(conn,value):
    cid=number(value,1,2147483647,True,True)
    if not conn.execute('SELECT id FROM customers WHERE id=? AND is_deleted=0',(cid,)).fetchone():
        raise ValueError('干部档案不存在')
    return cid


def project(code,optional=False):
    if optional and not code: return None
    if code not in PROJECT_BY_CODE: raise ValueError('请选择六项正式项目之一')
    return code
