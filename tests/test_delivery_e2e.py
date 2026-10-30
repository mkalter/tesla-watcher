"""Actual Python -> local HTTP -> Node bridge -> fake WhatsApp driver integration."""
import json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from watcher.store import Store
from watcher.models import Listing
from watcher.notify import deliver
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('node'),'Node.js required for bridge integration')
class DeliveryIntegration(unittest.TestCase):
 def test_python_to_bridge_is_idempotent(self):
  with tempfile.TemporaryDirectory() as directory:
   code=r'''
const fs=require('node:fs'),path=require('node:path');
const {createBridge}=require(process.argv[1]);let calls=0;
const driver={name:'fake',ready:()=>true,qr:()=>null,send:async()=>{calls++;fs.writeFileSync(path.join(process.argv[2],'calls'),String(calls));return{id:'fake-id'};}};
const {server}=createBridge({driver,token:'integration-test-token-0123456789',recipient:'31600000000',directory:process.argv[2],minInterval:0});
server.listen(0,'127.0.0.1',()=>console.log(server.address().port));
'''
   process=subprocess.Popen(['node','-e',code,str(ROOT/'bridge/server.js'),directory],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
   store=None
   try:
    port=int(process.stdout.readline().strip())
    store=Store(str(Path(directory)/'store.db'),{'min_year':2022})
    store.ingest('demo',[],'2026-10-01T00:00:00+00:00')
    item=Listing('demo','one','https://example.invalid/car/one','Tesla Model S',2023,'build_year',50000,'EUR',60000,'NL')
    store.ingest('demo',[item],'2026-10-01T00:10:00+00:00')
    config={'bridge_url':f'http://127.0.0.1:{port}'}
    with patch.dict(os.environ,{'BRIDGE_TOKEN':'integration-test-token-0123456789'}):
     self.assertEqual(deliver(store,config),1)
     event=store.events()[0];self.assertEqual(event['state'],'sent')
     # Simulate Python losing its acknowledgement after the bridge committed it.
     store.set_event(event['id'],'queued')
     self.assertEqual(deliver(store,config),1)
    self.assertEqual((Path(directory)/'calls').read_text(),'1')
   finally:
    if store:store.close()
    process.terminate()
    try:process.communicate(timeout=5)
    except subprocess.TimeoutExpired:process.kill();process.communicate()
