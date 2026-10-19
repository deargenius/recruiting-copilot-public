import copy
import io
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import deepseek_jd as jd
from core import Store

TEXT = '【虚构测试】星河运动在上海招店长，负责排班和库存管理，需要两年门店经验，薪资还没定。'


def draft():
    result = copy.deepcopy(jd.SCHEMA)
    result.update(brand='星河运动', title='店长', location='上海',
                  responsibilities=['排班', '库存管理'], requirements=['两年门店经验'])
    return result


def completion(data=None):
    return {'choices': [{'finish_reason':'stop', 'message':{'content':json.dumps(draft() if data is None else data)}}]}


class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ, {'DEEPSEEK_API_KEY':'fictional-test-key-not-real'})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_exact_endpoint_and_request_shape(self):
        response = io.BytesIO(json.dumps(completion()).encode())
        with patch('deepseek_jd.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=response
            result=jd.generate_jd(TEXT)
        request=opener.return_value.open.call_args.args[0]
        body=json.loads(request.data)
        self.assertEqual(request.full_url,'https://api.deepseek.com/chat/completions')
        self.assertEqual(request.get_header('Authorization'),'Bearer fictional-test-key-not-real')
        self.assertEqual(body['model'],'deepseek-flash')
        self.assertEqual(body['response_format'],{'type':'json_object'})
        self.assertEqual(body['thinking'],{'type':'disabled'})
        self.assertEqual(json.loads(body['messages'][1]['content']),{'jd_input':TEXT})
        self.assertNotIn('fictional-test-key-not-real',json.dumps(result))
        self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],30)

    def test_missing_values_stay_empty(self):
        with patch('deepseek_jd.request_completion',return_value=completion()):
            result=jd.generate_jd(TEXT)['draft']
        self.assertEqual(result['salary'],'')
        self.assertEqual(result['working_hours'],'')
        self.assertIn('薪资',result['pending_items'])
        self.assertIn('工作时间',result['pending_items'])

    def test_unsubstantiated_facts_are_removed(self):
        data=draft(); data['salary']='12000元'; data['requirements'].append('本科及以上')
        result=jd.validate_result(data,TEXT)
        self.assertEqual(result['draft']['salary'],'')
        self.assertEqual(result['draft']['requirements'],['两年门店经验'])
        self.assertEqual(len(result['warnings']),2)

    def test_no_key_or_bad_input_never_calls_network(self):
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':''}), patch('deepseek_jd.request_completion') as call:
            for text in ['',None,[], 'x'*12001,TEXT]:
                with self.subTest(text_type=type(text).__name__), self.assertRaises(jd.JDError): jd.generate_jd(text)
            call.assert_not_called()

    def test_bad_json_schema_empty_and_truncated(self):
        bad=[{}, {'choices':[]}, completion([]), completion({'brand':'test'}),
             {'choices':[{'finish_reason':'length','message':{'content':'{}'}}]},
             {'choices':[{'finish_reason':'stop','message':{'content':''}}]},
             {'choices':[{'finish_reason':'stop','message':{'content':'```json\n{}\n```'}}]}]
        wrong=draft(); wrong['salary']=123; bad.append(completion(wrong))
        wrong=draft(); wrong['responsibilities']='not a list'; bad.append(completion(wrong))
        for data in bad:
            with self.subTest(data=data), patch('deepseek_jd.request_completion',return_value=data):
                with self.assertRaises(jd.JDError): jd.generate_jd(TEXT)

    def test_upstream_errors_never_leak_secret_or_body(self):
        for status in (400,401,402,403,404,429,500):
            error=urllib.error.HTTPError('https://api.deepseek.com',status,'fictional-test-key-not-real',{},io.BytesIO(b'private upstream body'))
            with self.subTest(status=status), patch('deepseek_jd.request_completion',side_effect=error):
                with self.assertRaises(jd.JDError) as caught: jd.generate_jd(TEXT)
                self.assertNotIn('fictional-test-key-not-real',str(caught.exception))
                self.assertNotIn('private upstream body',str(caught.exception))

    def test_timeout_network_and_unexpected_error(self):
        for error,expected in [(socket.timeout(),504),(urllib.error.URLError(socket.timeout()),504),
                                (urllib.error.URLError('secret network details'),502),(RuntimeError('secret'),502)]:
            with self.subTest(error=type(error).__name__),patch('deepseek_jd.request_completion',side_effect=error):
                with self.assertRaises(jd.JDError) as caught: jd.generate_jd(TEXT)
                self.assertEqual(caught.exception.status,expected)
                self.assertNotIn('secret',str(caught.exception))

    def test_redirect_not_followed(self):
        self.assertIsNone(jd.NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.invalid'))

    def test_confirmation_and_existing_schema(self):
        with self.assertRaises(jd.JDError): jd.confirmed_job({'confirmed':False,'job':{}})
        with self.assertRaises(jd.JDError): jd.confirmed_job({'confirmed':'true','job':{}})
        clean=jd.confirmed_job({'confirmed':True,'job':{'title':'虚构岗位','jd':'虚构要求','api_key':'must not persist'}})
        self.assertEqual(set(clean),{'title','jd','brand','city','store','salary','hours','mentor','faq','questions','template'})


class JDHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import the actual backend against a temporary DB, never the user's data.
        cls.tmp=tempfile.TemporaryDirectory()
        with patch.dict(os.environ,{'COPILOT_DB_PATH':str(Path(cls.tmp.name)/'http.sqlite3')}):
            import server
        cls.server=server
        cls.original_store=server.STORE
        server.STORE=Store(Path(cls.tmp.name)/'http.sqlite3')
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.original_port=server.PORT
        server.PORT=cls.http.server_address[1]
        cls.base=f'http://127.0.0.1:{server.PORT}'
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.thread.join()
        cls.server.PORT=cls.original_port; cls.server.STORE=cls.original_store
        cls.tmp.cleanup()

    def post(self,path,p,token=True):
        headers={'Content-Type':'application/json'}
        if token: headers['X-Copilot-Token']=self.server.TOKEN
        req=urllib.request.Request(self.base+path,data=json.dumps(p).encode(),headers=headers)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req,timeout=5) as response: return response.status,json.load(response)
        except urllib.error.HTTPError as e: return e.code,json.load(e)

    def test_generate_no_write_and_confirmed_save(self):
        with self.server.STORE.db() as db: before=db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'fictional-test-key-not-real'}),patch('deepseek_jd.request_completion',return_value=completion()):
            code,result=self.post('/api/jd-draft',{'text':TEXT,'candidate':'should never be sent'})
        self.assertEqual(code,200)
        with self.server.STORE.db() as db: self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],before)
        code,_=self.post('/api/job-from-jd',{'confirmed':False,'job':{'title':'测试','jd':'测试'}})
        self.assertEqual(code,400)
        code,result=self.post('/api/job-from-jd',{'confirmed':True,'job':{'title':'人工修改后的虚构岗位','jd':'岗位职责：排班\n待确认事项：薪资'}})
        self.assertEqual(code,200)
        saved=self.server.STORE.job(result['id'])
        self.assertEqual(saved['title'],'人工修改后的虚构岗位')
        self.assertNotIn('confirmed',saved)

    def test_existing_manual_save_and_request_token(self):
        self.assertEqual(self.post('/api/job',{'title':'原手动岗位','jd':'原流程'})[0],200)
        self.assertEqual(self.post('/api/jd-draft',{'text':TEXT},token=False)[0],403)

    def test_external_call_does_not_hold_database_lock(self):
        entered,release=threading.Event(),threading.Event()
        def slow(_):
            entered.set(); release.wait(4); return {'draft':draft(),'warnings':[]}
        with patch('server.generate_jd',side_effect=slow):
            worker=threading.Thread(target=lambda:self.post('/api/jd-draft',{'text':TEXT})); worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.post('/api/job',{'title':'并行虚构岗位','jd':'仍能保存'})[0],200)
            finally: release.set(); worker.join()

    def test_missing_key_and_rate_limit(self):
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':''}):
            self.assertEqual(self.post('/api/jd-draft',{'text':TEXT})[0],503)
        self.server.JD_SLOTS.acquire(); self.server.JD_SLOTS.acquire()
        try: self.assertEqual(self.post('/api/jd-draft',{'text':TEXT})[0],429)
        finally: self.server.JD_SLOTS.release(); self.server.JD_SLOTS.release()


if __name__=='__main__': unittest.main(verbosity=2)
