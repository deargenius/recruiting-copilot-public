import base64
import io
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
from pathlib import Path
from core import Store
from documents import extract

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s=Store(Path(self.tmp.name)/'test.db')
        self.j=self.s.action('job',{'title':'演示店长','jd':'具备门店管理经验','template':['职业经历','期望薪资']})['id']
        self.c=self.s.action('candidate',{'job_id':self.j,'name':'演示A','resume':'门店管理三年'})['id']
    def act(self,a,**kw): return self.s.action(a,dict(id=self.c,**kw))
    def test_01_jobs_and_persistence(self):
        self.assertEqual(Store(self.s.path).snapshot()['jobs'][0]['title'],'演示店长')
    def test_02_screening_and_evidence(self):
        self.act('screen')
        with self.assertRaises(ValueError): self.act('facts',facts={'职业经历':{'value':'虚构五年','source':'简历原文'}})
        self.act('facts',facts={'职业经历':{'value':'门店管理三年','source':'简历原文'}})
        self.assertEqual(self.s.candidate(self.c)[1]['status'],'Need Info')
    def test_03_missing_fields(self):
        self.act('screen'); self.act('facts',facts={})
        self.assertEqual(self.s.candidate(self.c)[1]['prep']['missing'],['职业经历','期望薪资'])
    def test_04_reminders(self):
        self.act('screen'); self.act('facts',facts={})
        start=datetime.now(timezone.utc)+timedelta(hours=2)
        self.act('schedule',time=start.isoformat())
        self.s.tick(start-timedelta(minutes=59)); self.s.tick(start-timedelta(minutes=9)); self.s.tick(start)
        c=self.s.candidate(self.c)[1]
        self.assertEqual(c['reminders'],['T-60','T-10']); self.assertIn('questions',c['prep'])
        self.act('schedule',time=(start+timedelta(days=1)).isoformat())
        self.assertEqual(self.s.candidate(self.c)[1]['reminders'],[])
    def test_05_06_full_workflow_and_confirmation(self):
        with self.assertRaises(ValueError): self.act('ready')
        self.act('screen'); self.act('facts',facts={'职业经历':{'value':'门店管理三年','source':'简历原文'}})
        self.act('schedule',time=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        self.act('debrief',objective='管理团队5人（演示）',signals='愿意了解',judgment='待核实业绩')
        self.act('generate'); self.act('review')
        with self.assertRaises(ValueError): self.act('confirm',evidence='')
        self.act('confirm',evidence='演示确认记录'); self.act('ready')
        self.assertEqual(self.s.candidate(self.c)[1]['status'],'Ready to Submit')
        self.act('reopen')
        self.assertIsNone(self.s.candidate(self.c)[1]['confirmation'])
        self.act('generate'); self.assertEqual(self.s.candidate(self.c)[1]['profile']['version'],2)
    def test_docx_pdf(self):
        from docx import Document
        from reportlab.pdfgen import canvas
        buf=io.BytesIO(); doc=Document(); doc.add_paragraph('Demo resume'); doc.save(buf)
        self.assertIn('Demo resume',extract('demo.docx',base64.b64encode(buf.getvalue()).decode()))
        buf=io.BytesIO(); pdf=canvas.Canvas(buf); pdf.drawString(50,700,'Demo resume'); pdf.save()
        self.assertIn('Demo resume',extract('demo.pdf',base64.b64encode(buf.getvalue()).decode()))
    def test_ai_evidence_filter(self):
        import ai
        with patch.dict('os.environ',{'AI_API_KEY':'test','AI_BASE_URL':'https://example.invalid/v1','AI_MODEL':'test'}), patch('ai.analyze',return_value={'text':'{"职业经历":"门店管理三年","业务业绩":"销售增长100%","年龄":"30"}'}):
            result=ai.extract_fields('门店管理三年',['职业经历','业务业绩'])
        self.assertEqual(result,{'职业经历':{'value':'门店管理三年','source':'待确认'}})

if __name__=='__main__': unittest.main(verbosity=2)
