import io
from email.header import decode_header
import json
import tempfile
from pathlib import Path
import urllib.error
import unittest
from unittest.mock import patch
from watcher.models import message
from watcher.ntfy import Ntfy,deliver_ntfy
from watcher.lite_app import LiteApp,render
from watcher.store import Store
from test_watcher import car,FILTERS,T0,T1

class Response(io.BytesIO):
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

class NtfyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.photo_patch=patch("watcher.ntfy.fetch_photo",return_value=b"jpeg");self.photo_patch.start()
        self.driver=Ntfy(self.root)
        self.store=Store(str(self.root/'watcher.sqlite'),FILTERS)
    def tearDown(self):self.photo_patch.stop();self.store.close();self.temp.cleanup()
    def queue(self,photo=True):
        self.store.ingest('test',[],T0)
        self.store.ingest('test',[car(source='test',image_url='https://img.classistatic.de/car.jpg' if photo else '')],T1)
    def test_topic_is_private_and_persists(self):
        self.assertEqual(self.driver.topic,Ntfy(self.root).topic)
        self.assertGreater(len(self.driver.topic),30)
        self.assertEqual((self.root/'ntfy-topic.txt').stat().st_mode&0o777,0o600)
    def test_post_json_contains_standard_fields_photo_and_action(self):
        self.queue();seen=[]
        def publish(request,timeout):
            seen.append(request)
            return Response(json.dumps({'event':'message','id':'ntfy-id'}).encode())
        with patch('urllib.request.urlopen',side_effect=publish):
            self.assertEqual(deliver_ntfy(self.store,self.driver,pause=0),1)
            self.assertEqual(deliver_ntfy(self.store,self.driver,pause=0),0)
        self.assertEqual(seen[0].full_url,self.driver.url)
        self.assertEqual(seen[0].get_method(),'PUT');self.assertEqual(seen[0].data,b'jpeg')
        title=decode_header(seen[0].get_header('Title'))[0][0].decode('utf-8')
        body=decode_header(seen[0].get_header('Message'))[0][0].decode('utf-8')
        self.assertIn('€ 52.000',title);self.assertNotIn('*',title)
        self.assertIn('Kilometerstand: 60.000 km',body)
        self.assertEqual(seen[0].get_header('Filename'),'tesla-model-s.jpg')
        self.assertEqual(json.loads(seen[0].get_header('Actions'))[0]['action'],'view')
        self.assertEqual(len(seen),1)
    def test_rate_limit_safe_retry(self):
        self.queue()
        error=urllib.error.HTTPError('https://ntfy.sh/',429,'rate limit',{'Retry-After':'120'},None)
        with patch('urllib.request.urlopen',side_effect=error):self.assertEqual(deliver_ntfy(self.store,self.driver,clock=100,pause=0),0)
        event=self.store.events()[0];self.assertEqual(event['state'],'queued');self.assertEqual(event['next_attempt'],220)
    def test_timeout_needs_review_without_blind_retry(self):
        self.queue()
        with patch('urllib.request.urlopen',side_effect=TimeoutError):deliver_ntfy(self.store,self.driver,pause=0)
        self.assertEqual(self.store.events()[0]['state'],'uncertain')
        with patch('urllib.request.urlopen') as publish:deliver_ntfy(self.store,self.driver,pause=0);publish.assert_not_called()
    def test_ntfy_default_never_constructs_whatsapp(self):
        with tempfile.TemporaryDirectory() as directory,patch('watcher.lite_app.NativeWhatsApp',side_effect=AssertionError('WhatsApp must stay off')):
            app=LiteApp({'notifications':{'transport':'ntfy'},'filters':FILTERS,'sources':[]},directory,'password-for-tests','')
            self.assertEqual(app.driver.status()['driver'],'ntfy')
            html=render(app.status())
            self.assertIn('ntfy instellen',html);self.assertNotIn('WhatsApp koppelen',html)
            self.assertNotIn('/whatsapp/relink',html)
    def test_test_message_uses_no_car_fields(self):
        payload=self.driver.body({'kind':'test','payload':'{}','text':'Testmelding'})
        self.assertEqual(payload['message'],'Testmelding');self.assertNotIn('attach',payload)
