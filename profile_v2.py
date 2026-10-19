"""Structured resume model, conservative local extraction and missing-field rules."""
import copy
import re

PERSONAL = ['姓名','年龄','性别','城市','出生年月','手机号','邮箱','身高','体重','婚育','当前薪资','期望薪资','到岗时间']
EDUCATION = ['时间','学校','专业','学历']
EXPERIENCE = ['任职时间','公司','职位','工作职责','业绩','拥有技能','离职原因']
STORE_FIELDS = ['门店','商圈','销售业绩','统计时期','完成率','团队人数','人员架构','本人主要工作']
BLANK_EXPORT = ['期望薪资','个人照片','离职原因','主观评价']

def empty_profile(name=''):
    return {'personal':dict.fromkeys(PERSONAL,''),'education':[], 'experience':[], 'unavailable':{}, 'name':name}

def clean_profile(p):
    if not isinstance(p,dict): raise ValueError('履历格式无效')
    result=empty_profile()
    def clean(obj,fields):
        if not isinstance(obj,dict): raise ValueError('字段格式无效')
        out={}
        for k in fields:
            value=obj.get(k,'')
            if not isinstance(value,str) or len(value)>20000: raise ValueError('字段内容无效或过长')
            out[k]=value.strip()
        return out
    result['personal']=clean(p.get('personal',{}),PERSONAL)
    for collection,fields in [('education',EDUCATION),('experience',EXPERIENCE)]:
        values=p.get(collection,[])
        if not isinstance(values,list) or len(values)>50: raise ValueError('最多支持50段经历')
        for obj in values:
            item=clean(obj,fields)
            if collection=='experience':
                stores=obj.get('stores',[])
                if not isinstance(stores,list) or len(stores)>30: raise ValueError('门店数量无效')
                item['stores']=[clean(s,STORE_FIELDS) for s in stores]
            result[collection].append(item)
    unavailable=p.get('unavailable',{})
    if not isinstance(unavailable,dict) or len(unavailable)>1000: raise ValueError('缺项状态无效')
    result['unavailable']={str(k):v for k,v in unavailable.items() if v in ['未提供','不适用']}
    return result

def from_legacy(c):
    if c.get('structured'): return clean_profile(c['structured'])
    p=local_extract(c.get('resume',''),c.get('name',''))
    mapping={'姓名或代号':'姓名','意向城市':'城市','期望薪资':'期望薪资','到岗时间':'到岗时间'}
    for old,new in mapping.items():
        fact=c.get('facts',{}).get(old,{})
        if fact.get('value'):p['personal'][new]=fact['value']
    if not p['experience'] and c.get('facts',{}).get('职业经历',{}).get('value'):
        e=dict.fromkeys(EXPERIENCE,'');e['工作职责']=c['facts']['职业经历']['value'];e['stores']=[];p['experience']=[e]
    return p

def local_extract(text,name=''):
    p=empty_profile(name);p['personal']['姓名']=name
    aliases={'姓名或代号':'姓名','婚育情况':'婚育','意向城市':'城市','电话':'手机号','工作经历':'工作职责','职业经历':'工作职责','业务业绩':'业绩','专业技能':'拥有技能'}
    current=None; section=''; education_line=False
    date_pattern=r'(?:19|20)\d{2}[.年/-]?\d{0,2}\s*[-—–~至]\s*(?:(?:19|20)\d{2}[.年/-]?\d{0,2}|至今|今)'
    for raw in text.splitlines():
        line=raw.strip()
        if not line: continue
        if line.startswith('教育背景') or line.startswith('学历背景'): section='education';continue
        if line in ['工作经历','工作经历：','工作经历:','工作经验：']: section='experience';continue
        if section=='education':
            parts=re.split(r'\s*\|\s*|\t+',line)
            if len(parts)>=4 and re.search(date_pattern,parts[0]):p['education'].append(dict(zip(EDUCATION,parts[:4])));continue
        match=re.match(r'^('+date_pattern+r')\s*(?:\||\t|\s{2,})\s*(.+)',line)
        if match and section!='education':
            parts=re.split(r'\s*\|\s*|\t+',match.group(2))
            current=dict.fromkeys(EXPERIENCE,'');current.update({'任职时间':match.group(1),'公司':parts[0],'职位':parts[1] if len(parts)>1 else '', 'stores':[]})
            p['experience'].append(current);section='experience';continue
        match=re.match(r'^([^:：]{1,14})[:：]\s*(.*)$',line)
        if match:
            label,value=match.groups();label=aliases.get(label.strip(),label.strip())
            if label in PERSONAL:p['personal'][label]=value;continue
            if label=='身高体重':
                h=re.search(r'\d+(?:\.\d+)?\s*cm',value,re.I);w=re.search(r'\d+(?:\.\d+)?\s*kg',value,re.I)
                if h:p['personal']['身高']=h.group()
                if w:p['personal']['体重']=w.group()
                continue
            if label in EXPERIENCE:
                if current is None:
                    current=dict.fromkeys(EXPERIENCE,'');current['stores']=[];p['experience'].append(current)
                current[label]=value;section=label;continue
        if current and section in ['工作职责','业绩','拥有技能']:
            current[section]+=('\n' if current[section] else '')+line
    return clean_profile(p)

def missing(p):
    items=[]
    def add(path,label,value,question=None):
        if not str(value).strip() and path not in p.get('unavailable',{}):
            items.append({'path':path,'label':label,'question':question or '请确认'+label+'。'})
    for k in PERSONAL:add('personal.'+k,k,p['personal'].get(k,''))
    for i,e in enumerate(p['education']):
        for k in EDUCATION:add(f'education.{i}.{k}',f'教育{i+1} · {k}',e.get(k,''))
    for i,e in enumerate(p['experience']):
        for k in ['任职时间','公司','职位','工作职责','业绩','离职原因']:
            add(f'experience.{i}.{k}',f'经历{i+1} · {k}',e.get(k,''))
        for s,store in enumerate(e.get('stores',[])):
            for k in STORE_FIELDS:
                add(f'experience.{i}.stores.{s}.{k}',f'经历{i+1} / 门店{s+1} · {k}',store.get(k,''))
    if not p['education']:items.append({'path':'education','label':'教育背景','question':'请补充教育经历。','collection':True})
    if not p['experience']:items.append({'path':'experience','label':'工作经历','question':'请补充工作经历及对应门店。','collection':True})
    for i,e in enumerate(p['experience']):
        if not e.get('stores'):items.append({'path':f'experience.{i}.stores','label':f'经历{i+1} · 门店情况','question':'请补充门店、商圈、业绩、完成率、架构和本人职责。','collection':True})
    return items

def leaf_values(p,prefix=''):
    out={}
    if isinstance(p,dict):
        for k,v in p.items():
            if k!='unavailable':out.update(leaf_values(v,(prefix+'.' if prefix else '')+k))
    elif isinstance(p,list):
        for i,v in enumerate(p):out.update(leaf_values(v,prefix+'.'+str(i)))
    elif isinstance(p,str):out[prefix]=p
    return out

def set_path(p,path,value):
    keys=path.split('.');cur=p
    for key in keys[:-1]:cur=cur[int(key)] if isinstance(cur,list) else cur[key]
    if isinstance(cur,list):cur[int(keys[-1])]=value
    else:cur[keys[-1]]=value
