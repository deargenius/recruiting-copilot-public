import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import ai

STATES = ['New', 'Screening', 'Need Info', 'Interview Scheduled', 'Interviewed', 'Draft Profile', 'Candidate Confirmation', 'Confirmed', 'Ready to Submit']
FIELDS = ['姓名或代号', '职业经历', '业务业绩', '专业技能', '求职动机', '意向城市', '期望薪资', '到岗时间']
SOURCES = ['简历原文', '电话确认', '微信确认', '待确认']

class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, data TEXT NOT NULL); CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), data TEXT NOT NULL);')
    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()
    def snapshot(self):
        self.tick()
        with self.db() as db:
            return {'jobs': [dict(json.loads(d), id=i) for i,d in db.execute('SELECT id,data FROM jobs')], 'candidates': [dict(json.loads(d), id=i, job_id=j) for i,j,d in db.execute('SELECT id,job_id,data FROM candidates')], 'fields': FIELDS, 'states': STATES}
    def job(self, ident):
        with self.db() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=?', (ident,)).fetchone()
        if not row: raise ValueError('岗位不存在')
        return json.loads(row[0])
    def candidate(self, ident):
        with self.db() as db:
            row = db.execute('SELECT job_id,data FROM candidates WHERE id=?', (ident,)).fetchone()
        if not row: raise ValueError('候选人不存在')
        return row[0], json.loads(row[1])
    def save(self, ident, c):
        with self.db() as db:
            db.execute('UPDATE candidates SET data=? WHERE id=?', (json.dumps(c, ensure_ascii=False), ident))
    def invalidate(self, c):
        if c.get('profile'):
            c['history'].append(c.pop('profile'))
        c['reviewed'] = False
        c['confirmation'] = None
    def prep(self, c, job):
        missing = [f for f in job['template'] if not c['facts'].get(f, {}).get('value') or c['facts'][f]['source']=='待确认']
        return {'summary': c['facts'], 'job': job['title'], 'requirements':job['jd'], 'mentor':job.get('mentor',''), 'missing': missing, 'questions': ['请说明与岗位要求相关的工作经历及职责。', '请举例说明业务成果、统计口径及个人贡献。', '求职动机、顾虑和对岗位的疑问是什么？'] + [q for q in job.get('questions','').splitlines() if q.strip()] + ['请确认：' + f for f in missing] + ['请详细说明这项经历的职责、时间与成果：'+v['value'] for f,v in c['facts'].items() if f=='职业经历' and v.get('value')], 'notice': '以上为待核实问题，不代表已存在风险。'}
    def tick(self, now=None):
        now = now or datetime.now(timezone.utc)
        with self.db() as db:
            rows = db.execute('SELECT id,job_id,data FROM candidates').fetchall()
        for ident,j,d in rows:
            c=json.loads(d)
            if c['status'] != 'Interview Scheduled' or not c.get('interview'): continue
            minutes=(datetime.fromisoformat(c['interview'])-now).total_seconds()/60
            changed=False
            for threshold in (60,10):
                tag='T-'+str(threshold)
                if minutes <= threshold and tag not in c['reminders']:
                    c['reminders'].append(tag); changed=True
                    if threshold==10: c['prep']=self.prep(c,self.job(j))
            if changed: self.save(ident,c)
    def action(self, action, p):
        if action=='job':
            if not p.get('title','').strip() or not p.get('jd','').strip(): raise ValueError('请填写岗位名称和 JD')
            template = p.get('template') or FIELDS
            if not isinstance(template,list) or not all(isinstance(x,str) and x.strip() for x in template): raise ValueError('模板字段无效')
            p['template']=list(dict.fromkeys(template))
            with self.db() as db:
                return {'id': db.execute('INSERT INTO jobs(data) VALUES(?)',(json.dumps(p,ensure_ascii=False),)).lastrowid}
        if action=='candidate':
            self.job(p['job_id'])
            if not p.get('name','').strip() or not p.get('resume','').strip(): raise ValueError('请填写代号并导入简历')
            c={'name':p['name'], 'resume':p['resume'], 'filename':p.get('filename','粘贴文本'), 'status':'New','facts':{},'reminders':[], 'history':[], 'reviewed':False,'confirmation':None}
            with self.db() as db:
                return {'id':db.execute('INSERT INTO candidates(job_id,data) VALUES(?,?)',(p['job_id'],json.dumps(c,ensure_ascii=False))).lastrowid}
        ident=p['id']; j,c=self.candidate(ident); job=self.job(j)
        if action=='screen':
            if c['status']!='New': raise ValueError('初筛已开始')
            c['status']='Screening'
            # Extract literal field-labelled values only; the recruiter reviews these before saving.
            c['extracted']={}
            for line in c['resume'].splitlines():
                for f in job['template']:
                    for sep in ('：', ':'):
                        if line.strip().startswith(f+sep):
                            value=line.strip()[len(f)+1:].strip()
                            if value: c['extracted'][f]={'value':value,'source':'待确认'}
        elif action=='extract_ai':
            if c['status'] not in ['Screening','Need Info']: raise ValueError('请先开始初筛')
            c['extracted']=ai.extract_fields(c['resume'],[f for f in job['template'] if f in FIELDS])
        elif action=='facts':
            if c['status'] not in ['Screening','Need Info','Interview Scheduled','Interviewed']: raise ValueError('请先开始初筛；已生成材料需先重新打开')
            facts=p['facts']
            for field,v in facts.items():
                if field not in job['template']: raise ValueError('字段不在模板中')
                if v.get('source') not in SOURCES: raise ValueError('信息来源无效')
                if v.get('value') and v['source']=='简历原文' and v['value'] not in c['resume']: raise ValueError('简历事实必须是原文片段；改写请先核实')
            c['facts']=facts
            if c['status']=='Screening': c['status']='Need Info'
            c['prep']=self.prep(c,job)
        elif action=='analyze':
            safe={k:v for k,v in c['facts'].items() if k in FIELDS[1:] and v['source']!='待确认'}
            c['analysis']=ai.analyze({'title':job['title'],'jd':job['jd']},safe,'岗位匹配与电话准备')
        elif action=='analyze_debrief':
            if not c.get('debrief'): raise ValueError('请先保存复盘')
            safe={k:v for k,v in c['facts'].items() if k in FIELDS[1:] and v['source']!='待确认'}
            safe['电话复盘（区分客观记录、观察和主观判断）']=c['debrief']
            c['analysis']=ai.analyze({'title':job['title'],'jd':job['jd']},safe,'复盘匹配点、待核实风险、信息缺失及推进建议')
        elif action=='schedule':
            if c['status'] not in ['Need Info','Interview Scheduled']: raise ValueError('请先完成初筛信息整理')
            dt=datetime.fromisoformat(p['time'])
            if dt.tzinfo is None: raise ValueError('时间必须包含时区')
            if dt<=datetime.now(timezone.utc): raise ValueError('请选择未来面试时间')
            c.update(interview=dt.isoformat(),status='Interview Scheduled',reminders=[],prep=self.prep(c,job))
        elif action=='debrief':
            if c['status'] not in ['Interview Scheduled','Interviewed']: raise ValueError('请先安排面试')
            if not all(p.get(k,'').strip() for k in ['objective','signals','judgment']): raise ValueError('请填写客观数据、沟通信号和猎头判断')
            c['debrief']={k:p[k] for k in ['objective','signals','judgment']}
            c['status']='Interviewed'
            c['debrief_summary']={'客观数据（用户记录）':p['objective'],'沟通信号（用户观察）':p['signals'],'猎头判断（主观）':p['judgment'],'推进建议（规则辅助）':'逐项核对岗位要求；将电话确认的事实补录到信息字段，再生成推荐材料。','待确认':self.prep(c,job)['missing']}
        elif action=='generate':
            if c['status']!='Interviewed': raise ValueError('请先完成复盘')
            self.invalidate(c)
            lines=['候选人推荐材料', '候选人：'+c['name'],'岗位：'+job['title'],'版本：'+str(len(c['history'])+1),'']
            for f in job['template']:
                v=c['facts'].get(f,{})
                lines.append(f+': '+(v.get('value','') if v.get('source')!='待确认' and v.get('value') else '待候选人确认')+' 【'+v.get('source','待确认')+'】')
            lines+=['','电话复盘（猎头记录，需候选人核对）','客观数据：'+c['debrief']['objective'],'沟通信号（观察）：'+c['debrief']['signals'],'猎头判断（主观）：'+c['debrief']['judgment']]
            c['profile']={'version':len(c['history'])+1,'text':'\n'.join(lines)}; c['status']='Draft Profile'
        elif action=='review':
            if c['status']!='Draft Profile': raise ValueError('请先生成草稿')
            c['reviewed']=True; c['status']='Candidate Confirmation'
        elif action=='confirm':
            if c['status']!='Candidate Confirmation' or not c['reviewed']: raise ValueError('请先完成猎头审核')
            if not p.get('evidence','').strip(): raise ValueError('请记录候选人确认渠道、时间及反馈')
            c['confirmation']={'evidence':p['evidence'],'version':c['profile']['version'],'time':datetime.now(timezone.utc).isoformat()}; c['status']='Confirmed'
        elif action=='ready':
            if c['status']!='Confirmed' or c['confirmation']['version']!=c['profile']['version']: raise ValueError('当前版本尚未确认')
            c['status']='Ready to Submit'
        elif action=='reopen':
            if not c.get('profile'): raise ValueError('尚无推荐材料')
            self.invalidate(c); c['status']='Interviewed'
        else: raise ValueError('未知操作')
        self.save(ident,c)
        return {'ok':True}
