import base64
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from watcher.cli import load_config,replay
from watcher.lite_app import LiteApp,password_for
from watcher.native_whatsapp import NativeWhatsApp,deliver_native,recover_inflight
from watcher.sources import archive_snapshot
from watcher.store import Store
from test_watcher import car,FILTERS,T0,T1,T2

ROOT=Path(__file__).resolve().parents[1]

class Driver:
    connected=True
    error=False
    def __init__(self):self.sent=[]
    def ready(self):return self.connected
    def send(self,text):
        if self.error:raise TimeoutError('test failure')
        self.sent.append(text);return 'message-id'
    def status(self):return {'ready':self.connected,'qr_available':False,'error':''}
    def qr(self):return None
    def start(self):pass
    def stop(self):pass
    def set_recipient(self,number):self.recipient=number
    def relink(self):self.relink_called=True

class LightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=Store(str(self.root/'events.sqlite'),FILTERS)
        self.driver=Driver()
    def tearDown(self):self.store.close();self.temp.cleanup()
    def queue(self):
        self.store.ingest('test',[],T0);self.store.ingest('test',[car()],T1)
    def test_delivery_once_persists(self):
        self.queue();self.assertEqual(deliver_native(self.store,self.driver,pause=0),1)
        self.store.close();self.store=Store(str(self.root/'events.sqlite'),FILTERS)
        self.assertEqual(deliver_native(self.store,self.driver,pause=0),0)
        self.assertEqual(len(self.driver.sent),1)
    def test_offline_keeps_queue(self):
        self.queue();self.driver.connected=False
        self.assertEqual(deliver_native(self.store,self.driver,pause=0),0)
        self.assertEqual(self.store.events()[0]['state'],'queued')
    def test_ambiguous_failure_never_blind_retry(self):
        self.queue();self.driver.error=True
        self.assertEqual(deliver_native(self.store,self.driver,pause=0),0)
        self.driver.error=False
        self.assertEqual(deliver_native(self.store,self.driver,pause=0),0)
        self.assertEqual(self.store.events()[0]['state'],'uncertain')
    def test_process_death_needs_review(self):
        self.queue();self.store.set_event(self.store.events()[0]['id'],'sending')
        recover_inflight(self.store)
        self.assertEqual(self.store.events()[0]['state'],'uncertain')
    def test_price_history_only_changes(self):
        self.store.ingest('test',[car()],T0);self.store.ingest('test',[car()],T1)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM prices').fetchone()[0],1)
        self.store.ingest('test',[car(price=45000)],T2)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM prices').fetchone()[0],2)
    def test_compressed_replay(self):
        folder=self.root/'snapshots'
        archive_snapshot(folder,'test',T0,[],compress=True)
        archive_snapshot(folder,'test',T1,[car()],compress=True)
        self.assertEqual(len(list(folder.rglob('*.json.gz'))),2)
        report=replay([str(folder)],FILTERS,str(self.root/'report.json'))
        self.assertEqual(report['new_listing_ids'],['a'])
    def test_real_sdk_constructs_without_network(self):
        driver=NativeWhatsApp(self.root/'auth','31612345678')
        client=driver._make_client()
        self.assertIsNotNone(client)
        self.assertFalse(driver.ready())
    def test_real_sdk_qr_and_fixed_recipient(self):
        driver=NativeWhatsApp(self.root/'auth','31612345678')
        driver._receive_qr(None,b'synthetic-test-pairing-code')
        self.assertTrue(driver.qr().startswith(b'\x89PNG'))
        self.assertTrue(driver.status()['qr_available'])
        calls=[]
        driver._client=SimpleNamespace(send_message=lambda *a,**kw:(calls.append((a,kw)) or SimpleNamespace(ID='abc')))
        driver._ready=True
        self.assertEqual(driver.send('test'),'abc')
        self.assertEqual(calls[0][0],('31612345678','test'))
        self.assertEqual(calls[0][1],{'link_preview':False})
    def test_password_creation_private_and_stable(self):
        first=password_for(self.root)
        self.assertEqual(first,password_for(self.root))
        self.assertGreaterEqual(len(first),16)
        self.assertEqual((self.root/'admin-password.txt').stat().st_mode&0o777,0o600)
        with self.assertRaises(ValueError):password_for(self.root,'short')
    def test_unconfigured_recipient_can_pair_but_cannot_send(self):
        driver=NativeWhatsApp(self.root/'auth','')
        driver._ready=True
        self.assertFalse(driver.ready())
        driver.set_recipient('31612345678');self.assertTrue(driver.ready())
        with self.assertRaises(ValueError):driver.set_recipient('wrong')
    def test_native_relink_clears_current_qr_and_requests_restart(self):
        driver=NativeWhatsApp(self.root/'auth','')
        driver._receive_qr(None,b'test-pairing')
        driver.relink()
        self.assertIsNone(driver.qr())
        self.assertEqual(driver.status()['phase'],'restarting')
        self.assertTrue(driver._relink.is_set())

    def test_expired_pairing_qr_is_restarted_without_touching_connected_client(self):
        driver=NativeWhatsApp(self.root/'auth','')
        driver._qr=b'png';driver._qr_time=10
        self.assertFalse(driver._expired_qr(100))
        self.assertTrue(driver._expired_qr(131));self.assertIsNone(driver._qr)
        driver._ready=True;driver._qr=b'png'
        self.assertFalse(driver._expired_qr(500))

class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.driver=Driver()
        self.app=LiteApp(load_config(ROOT/'config.light.json'),self.temp.name,'test-password-long-enough','31612345678',driver=self.driver)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),self.app.handler())
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
        self.auth='Basic '+base64.b64encode(b'admin:test-password-long-enough').decode()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.worker.join();self.temp.cleanup()
    def request(self,path='/',method='GET',auth=True,origin=None,body=''):
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={'Authorization':self.auth} if auth else {}
        if origin:headers['Origin']=origin
        connection.request(method,path,body=body,headers=headers)
        response=connection.getresponse();result=(response.status,response.read());connection.close();return result
    def test_auth_and_public_health(self):
        self.assertEqual(self.request(auth=False)[0],401)
        self.assertEqual(self.request('/healthz',auth=False)[0],200)
        self.assertEqual(self.request('/status')[0],200)
        self.assertEqual(self.request('/qr',auth=False)[0],401)
    def test_relink_requires_login_and_calls_driver(self):
        self.assertEqual(self.request('/whatsapp/relink','POST',auth=False)[0],401)
        self.assertEqual(self.request('/whatsapp/relink','POST')[0],303)
        self.assertTrue(self.driver.relink_called)

    def test_cross_origin_post_rejected(self):
        self.assertEqual(self.request('/test','POST',origin='https://evil.test')[0],403)
        self.assertEqual(len(self.driver.sent),0)
    def test_recipient_setup_requires_auth_and_persists(self):
        self.assertEqual(self.request('/recipient','POST',auth=False,body='number=31612345678')[0],401)
        self.assertEqual(self.request('/recipient','POST',body='number=invalid')[0],400)
        self.assertEqual(self.request('/recipient','POST',body='number=31612345678')[0],303)
        self.assertEqual((Path(self.temp.name)/'recipient.txt').read_text(),'31612345678')
        self.assertEqual(self.driver.recipient,'31612345678')
    def test_test_message_queued_and_sent(self):
        self.assertEqual(self.request('/test','POST')[0],303)
        self.app._flush_pending()
        self.assertEqual(len(self.driver.sent),1)
        self.app._flush_pending();self.assertEqual(len(self.driver.sent),1)
    def test_pause_persists_and_blocks_test(self):
        self.app.set_notifications(False)
        self.assertEqual(self.request('/test','POST')[0],400)
        clone=LiteApp(self.app.config,self.temp.name,'test-password-long-enough','31612345678',driver=self.driver)
        self.assertFalse(clone.status()['notifications'])
    def test_manual_uncertain_resolution(self):
        store=Store(self.app.config['database'],self.app.config['filters'])
        try:
            store.ingest('test',[],T0);store.ingest('test',[car()],T1)
            event=store.events()[0];store.set_event(event['id'],'uncertain')
        finally:store.close()
        self.app.resolve(event['id'],'retry');self.app._flush_pending()
        self.assertEqual(len(self.driver.sent),1)
    def test_html_escaped(self):
        self.app._notice='<script>alert(1)</script>'
        body=self.request()[1].decode()
        self.assertIn('&lt;script&gt;',body)
        self.assertNotIn('<script>',body)
    def test_delivery_during_blocked_scan(self):
        scanning=threading.Event();release=threading.Event()
        def scan(config,args,notifier):scanning.set();release.wait(8);return 0
        self.app.scan_fn=scan
        self.app.start()
        try:
            self.assertTrue(scanning.wait(2));self.app.queue_test()
            deadline=time.monotonic()+5
            while not self.driver.sent and time.monotonic()<deadline:time.sleep(.05)
            self.assertEqual(len(self.driver.sent),1)
            self.assertTrue(self.app.status()['active'])
        finally:release.set();self.app.stop()

if __name__=='__main__':unittest.main()
