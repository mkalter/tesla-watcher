import json
from pathlib import Path
import tempfile
import unittest
from test_light import Driver
from test_watcher import car,T0
from watcher.lite_app import LiteApp
from watcher.store import Store

class ExampleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.config={'sources':[{'name':'a'},{'name':'b'},{'name':'empty'}], 'filters':{'min_year':2022}}
        self.driver=Driver()
        self.app=LiteApp(self.config,self.temp.name,'password-for-testing','31612345678',driver=self.driver)
        store=Store(self.app.config['database'],self.config['filters'])
        try:
            store.ingest('a',[car('old',source='a',year=2018),car('new',source='a')],T0)
            store.ingest('b',[car('b',source='b')],T0)
        finally:store.close()
    def tearDown(self):self.temp.cleanup()
    def test_one_real_eligible_example_per_source(self):
        result=self.app.queue_examples('example_batch_1')
        self.assertEqual(result['queued'],['a','b']);self.assertEqual(result['missing'],['empty'])
        store=Store(self.app.config['database'],self.config['filters'])
        try:
            events=store.events();self.assertEqual(len(events),2)
            self.assertTrue(all(e['kind']=='example' and e['text'].startswith('VOORBEELD') for e in events))
            self.assertTrue(all(json.loads(e['payload'])['year']>=2022 for e in events))
        finally:store.close()
    def test_same_batch_does_not_resend_after_restart(self):
        self.app.queue_examples('example_batch_1')
        self.app=LiteApp(self.config,self.temp.name,'password-for-testing','31612345678',driver=self.driver)
        self.assertEqual(self.app.queue_examples('example_batch_1')['queued'],[])
    def test_double_click_refused_while_pending(self):
        self.app.queue_examples()
        with self.assertRaises(ValueError):self.app.queue_examples()
    def test_offline_batch_remains_queued_until_connected(self):
        self.driver.connected=False
        with self.assertRaises(ValueError):self.app.queue_examples()
        self.assertEqual(len(self.app.queue_examples('startup_batch',require_ready=False)['queued']),2)
    def test_paused_does_not_queue(self):
        self.app.set_notifications(False)
        with self.assertRaises(ValueError):self.app.queue_examples()
