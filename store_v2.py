import json, sqlite3, io, base64
import uuid
from datetime import datetime, timezone
from pathlib import Path
from core import Store
from profile_v2 import from_legacy, clean_profile, missing, empty_profile
from word_v2 import render_profile

class V2Store(Store):
    def __init__(self,path):
        super().__init__(path)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,candidate_id INTEGER,created TEXT,action TEXT,data TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS word_templates(id INTEGER PRIMARY KEY,name TEXT,created TEXT,data BLOB)')
    def snapshot(self):
        s=super().snapshot()
        for c in s['candidates']:
            c['structured']=from_legacy(c);c['missing']=missing(c['structured'])
        with self.db() as db:s['word_templates']=[{'id':0,'name':'阿迪门店模板 v1'}]+[{'id':i,'name':n,'created':t} for i,n,t in db.execute('SELECT id,name,created FROM word_templates')]
        s['version']='2.0';return s
    def prep(self,c,job):
        if not c.get('structured'):return super().prep(c,job)
        p=from_legacy(c)
        result=super().prep(c,job)
        result.update({'job':job['title'],'questions':[x for x in job.get('questions','').splitlines() if x.strip()]+[x['question'] for x in missing(p)],'missing':[x['label'] for x in missing(p)]})
        return result
    def v2(self,action,p):
        if action=='template-upload':
            name=str(p.get('name','')).strip()
            if not name:raise ValueError('请填写模板名称与版本')
            blob=base64.b64decode(p['data'],validate=True)
            if len(blob)>10*1024*1024:raise ValueError('模板过大')
            blank=empty_profile();blank['personal']['姓名']='候选人姓名'
            cleaned=render_profile(io.BytesIO(blob),blank)
            with self.db() as db:return {'id':db.execute('INSERT INTO word_templates(name,created,data) VALUES(?,?,?)',(name,datetime.now(timezone.utc).isoformat(),cleaned)).lastrowid}
        if action=='job-template':
            job=self.job(int(p['job_id']));tid=int(p['template_id'])
            with self.db() as db:
                if tid and not db.execute('SELECT id FROM word_templates WHERE id=?',(tid,)).fetchone():raise ValueError('模板不存在')
                job['doc_template_id']=tid
                db.execute('UPDATE jobs SET data=? WHERE id=?',(json.dumps(job,ensure_ascii=False),p['job_id']))
            return {'ok':True}
        if action=='history':
            with self.db() as db:return {'history':[{'time':t,'action':a,'data':json.loads(d)} for t,a,d in db.execute('SELECT created,action,data FROM audit WHERE candidate_id=? ORDER BY id DESC LIMIT 30',(int(p['id']),))]}
        if action=='candidate':
            r=super().action('candidate',p);j,c=self.candidate(r['id']);c['structured']=from_legacy(c);c['status']='Screening';c['person_id']=str(uuid.uuid4());self.save(r['id'],c);return r
        if action=='link-job':
            source_job,c=self.candidate(int(p['id']));target=int(p['job_id']);self.job(target)
            person=c.get('person_id') or str(uuid.uuid4());c['person_id']=person;self.save(int(p['id']),c)
            for other in self.snapshot()['candidates']:
                if other.get('person_id')==person and other['job_id']==target:raise ValueError('该候选人已有此岗位记录')
            r=super().action('candidate',{'job_id':target,'name':c['name'],'resume':c['resume'],'filename':c.get('filename','')})
            _,new=self.candidate(r['id']);new.update(person_id=person,structured=from_legacy(c),status='Need Info');self.save(r['id'],new);return r
        ident=int(p['id']);j,c=self.candidate(ident)
        if p.get('revision',0)!=c.get('revision',0):raise ValueError('记录已在其他页面更新，请刷新后重试。当前输入仍保留在页面。')
        before=json.dumps(c,ensure_ascii=False)
        if c.get('archived') and action!='reopen':raise ValueError('请先重新打开归档记录再编辑')
        if action=='profile':
            c['structured']=clean_profile(p['profile'])
            if c['status'] in ['New','Screening']:c['status']='Need Info'
        elif action=='schedule':
            dt=datetime.fromisoformat(p['time'])
            if dt.tzinfo is None or dt<=datetime.now(timezone.utc):raise ValueError('请选择未来的面试时间')
            c.update(interview=dt.isoformat(),status='Interview Scheduled',reminders=[])
            c['prep']=self.prep(c,self.job(j))
        elif action=='cancel':c.update(interview=None,status='Need Info',reminders=[])
        elif action=='no-answer':c.update(interview=None,status='Need Info',reminders=[],call_outcome='未接通，待重新安排')
        elif action=='debrief':
            c['debrief']={k:str(p.get(k,'')) for k in ['objective','signals','judgment']}
            if p.get('complete'):
                if not c['debrief']['objective'].strip():raise ValueError('请先填写客观电话记录')
                c['status']='Interviewed';c['debrief_complete']=True
        elif action=='decision':
            if not c.get('debrief_complete') and c['status']!='Interviewed':raise ValueError('请先完成电话复盘')
            choice=p.get('decision')
            if choice not in ['推荐','不推荐']:raise ValueError('请选择推荐结果')
            if choice=='不推荐' and not p.get('reason','').strip():raise ValueError('请填写不推荐原因')
            c.update(decision=choice,reason=p.get('reason',''),archived=True,status='Draft Profile' if choice=='推荐' else 'Not Recommended')
        elif action=='reopen':c.update(archived=False,decision=None,status='Interviewed' if c.get('debrief_complete') else 'Need Info')
        else:raise ValueError('未知操作')
        c['revision']=c.get('revision',0)+1;c['updated_at']=datetime.now(timezone.utc).isoformat()
        with self.db() as db:
            db.execute('INSERT INTO audit(candidate_id,created,action,data) VALUES(?,?,?,?)',(ident,c['updated_at'],action,before))
            db.execute('UPDATE candidates SET data=? WHERE id=?',(json.dumps(c,ensure_ascii=False),ident))
        return {'ok':True,'revision':c['revision']}
    def word(self,ident):
        j,c=self.candidate(ident)
        if c.get('decision')!='推荐':raise ValueError('请先人工选择推荐')
        template=Path(__file__).parent/'assets'/'adidas-store-v1.docx'
        tid=self.job(j).get('doc_template_id',0)
        if tid:
            with self.db() as db:row=db.execute('SELECT data FROM word_templates WHERE id=?',(tid,)).fetchone()
            if not row:raise ValueError('岗位模板不存在')
            template=io.BytesIO(row[0])
        return render_profile(template,from_legacy(c))
    def backup(self):
        target=sqlite3.connect(':memory:')
        with self.db() as db:db.backup(target)
        data=target.serialize();target.close();return data
    def daily_backup(self):
        folder=Path(self.path).parent/'backups';folder.mkdir(exist_ok=True)
        dest=folder/('daily-'+datetime.now().strftime('%Y%m%d')+'.sqlite3')
        if not dest.exists():dest.write_bytes(self.backup())
    def restore(self,p):
        if p.get('confirmed') is not True:raise ValueError('请确认恢复备份')
        data=base64.b64decode(p['data'],validate=True)
        if not data.startswith(b'SQLite format 3\x00'):raise ValueError('不是有效的数据库备份')
        source=sqlite3.connect(':memory:')
        try:
            source.deserialize(data)
            if source.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('备份完整性检查失败')
            for table in ['jobs','candidates']:
                for row in source.execute('SELECT data FROM '+table):
                    if not isinstance(json.loads(row[0]),dict):raise ValueError('备份内容无效')
            backup_dir=Path(self.path).parent/'backups';backup_dir.mkdir(exist_ok=True)
            (backup_dir/('before-restore-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')).write_bytes(self.backup())
            with self.db() as db:source.backup(db)
        finally:source.close()
        self.__init__(self.path)
        return {'ok':True}
