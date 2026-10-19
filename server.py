import json
import os
import secrets
import threading
import time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
from store_v2 import V2Store as Store
from documents import extract
from deepseek_jd import generate_jd, confirmed_job, JDError
import ai_v2
from profile_v2 import from_legacy

ROOT=Path(__file__).parent
STORE=Store(os.getenv('COPILOT_DB_PATH', str(ROOT/'data'/'copilot.sqlite3')))
TOKEN=secrets.token_urlsafe(32)
PORT=int(os.getenv('COPILOT_PORT','8765'))
LOCK=threading.RLock()
JD_SLOTS=threading.BoundedSemaphore(2)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def reply(self,status,data,kind='application/json; charset=utf-8'):
        body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type',kind); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def valid_host(self):
        return self.headers.get('Host') in [f'127.0.0.1:{PORT}',f'localhost:{PORT}']
    def do_GET(self):
        if not self.valid_host(): return self.reply(403,{'error':'Invalid host'})
        if self.path in ['/','/v1']: return self.reply(200,(ROOT/'static'/('v2.html' if self.path=='/' else 'index.html')).read_bytes().replace(b'__TOKEN__',TOKEN.encode()),'text/html; charset=utf-8')
        if self.path=='/api/backup':
            with LOCK: return self.reply(200,STORE.backup(),'application/octet-stream')
        if self.path.startswith('/api/word/'):
            try:
                with LOCK: return self.reply(200,STORE.word(int(self.path.split('/')[-1])),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            except ValueError as e:return self.reply(400,{'error':str(e)})
        if self.path=='/api/state':
            with LOCK: return self.reply(200,STORE.snapshot())
        if self.path in ['/app.js','/job-form.js','/style.css','/v2.js','/v2.css']:
            return self.reply(200,(ROOT/'static'/self.path[1:]).read_bytes(),'text/javascript; charset=utf-8' if self.path.endswith('.js') else 'text/css; charset=utf-8')
        return self.reply(404,{'error':'Not found'})
    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Copilot-Token')!=TOKEN: return self.reply(403,{'error':'请刷新本地页面'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>15*1024*1024: raise ValueError('请求过大')
            p=json.loads(self.rfile.read(size))
            if not isinstance(p,dict): raise ValueError('请求必须是 JSON 对象')
            if self.path=='/api/jd-draft':
                # External calls must not hold the DB lock or block interview reminders.
                if not JD_SLOTS.acquire(blocking=False):
                    raise JDError('正在处理其他 JD，请稍后重试。',429)
                try: result=generate_jd(p.get('text'))
                finally: JD_SLOTS.release()
            elif self.path=='/api/job-from-jd':
                job=confirmed_job(p)
                with LOCK: result=STORE.action('job',job)
            elif self.path=='/api/extract': result={'text':extract(p['filename'],p['data'])}
            elif self.path=='/api/v2/ai':
                with LOCK:
                    job_id,c=STORE.candidate(int(p['id']));job=STORE.job(job_id)
                if not JD_SLOTS.acquire(blocking=False):raise ValueError('模型正在处理其他请求，请稍后重试')
                try:
                    if p.get('kind')=='resume':result={'profile':ai_v2.parse_resume(c['resume'])}
                    elif p.get('kind')=='debrief':result={'updates':ai_v2.debrief_updates(from_legacy(c),c.get('debrief',{}).get('objective',''))}
                    elif p.get('kind')=='summary':result={'summary':ai_v2.summarize({'title':job['title'],'jd':job['jd']},from_legacy(c),c.get('debrief',{}))}
                    else:raise ValueError('未知 AI 操作')
                finally:JD_SLOTS.release()
                result['revision']=c.get('revision',0)
            elif self.path=='/api/v2/restore':
                with LOCK:result=STORE.restore(p)
            elif self.path.startswith('/api/v2/'):
                with LOCK: result=STORE.v2(self.path[8:],p)
            elif self.path.startswith('/api/'):
                with LOCK: result=STORE.action(self.path[5:],p)
            else: return self.reply(404,{'error':'Not found'})
            self.reply(200,result)
        except JDError as e: self.reply(e.status,{'error':str(e)})
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass
        except (ValueError,KeyError,TypeError) as e: self.reply(400,{'error':str(e)})
        except Exception: self.reply(400,{'error':'操作失败，请检查文件格式或输入内容'})

def scheduler():
    while True:
        try:
            with LOCK:
                STORE.tick()
                STORE.daily_backup()
        except Exception: pass
        time.sleep(15)

if __name__=='__main__':
    threading.Thread(target=scheduler,daemon=True).start()
    print(f'Recruiting Copilot: http://127.0.0.1:{PORT}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
