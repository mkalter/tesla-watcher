const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {createBridge}=require('./server');
const token='test-only-token-abcdefghijklmnopqrstuvwxyz';
function fixture(options={}) {
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'tesla-bridge-'));
 let calls=0,ready=true;
 const driver={name:'mock',ready:()=>ready,qr:()=>null,send:async()=>{calls++;if(options.fail)throw Error('unknown outcome');return {id:'message-1'};}};
 const bridge=createBridge({driver,token,recipient:'31600000000',directory,minInterval:0});
 return {...bridge,directory,calls:()=>calls,setReady:x=>{ready=x;},cleanup:()=>fs.rmSync(directory,{recursive:true,force:true})};
}
test('duplicate and concurrent event IDs send once',async()=>{
 const x=fixture();try {
  const responses=await Promise.all([x.send('event-0001','hello'),x.send('event-0001','hello')]);
  assert.equal(x.calls(),1);assert.equal(responses[0][0],200);assert.equal(responses[1][1].duplicate,true);
 }finally{x.cleanup();}
});
test('ledger survives restart',async()=>{
 const x=fixture();try {
  await x.send('event-0001','hello');
  const y=createBridge({driver:{ready:()=>true,send:async()=>{throw Error('must not call');}},token,recipient:'31600000000',directory:x.directory});
  assert.equal((await y.send('event-0001','hello'))[1].duplicate,true);
 }finally{x.cleanup();}
});
test('failed send becomes uncertain, never blindly retried',async()=>{
 const x=fixture({fail:true});try {
  assert.equal((await x.send('event-0001','hello'))[0],409);
  assert.equal((await x.send('event-0001','hello'))[0],409);assert.equal(x.calls(),1);
 }finally{x.cleanup();}
});
test('not connected is retryable before send',async()=>{
 const x=fixture();try {
  x.setReady(false);assert.equal((await x.send('event-0001','hello'))[0],503);assert.equal(x.calls(),0);
  x.setReady(true);assert.equal((await x.send('event-0001','hello'))[0],200);
 }finally{x.cleanup();}
});
test('same event with different body is rejected',async()=>{
 const x=fixture();try {await x.send('event-0001','hello');assert.equal((await x.send('event-0001','other'))[0],409);assert.equal(x.calls(),1);}finally{x.cleanup();}
});
test('HTTP authentication, recipient restriction, payload validation',async()=>{
 const x=fixture();x.server.listen(0,'127.0.0.1');await new Promise(r=>x.server.once('listening',r));
 const url='http://127.0.0.1:'+x.server.address().port;
 try {
  assert.equal((await fetch(url+'/status')).status,401);
  assert.equal((await fetch(url+'/healthz')).status,200);
  const headers={Authorization:'Bearer '+token,'Content-Type':'application/json'};
  assert.equal((await fetch(url+'/send',{method:'POST',headers,body:'bad json'})).status,400);
  const response=await fetch(url+'/send',{method:'POST',headers,body:JSON.stringify({event_id:'event-0001',text:'hello',recipient:'not-used'})});
  assert.equal(response.status,200);assert.equal(x.calls(),1);
  assert.equal((await fetch(url+'/status',{headers})).status,200);
 }finally{await new Promise(r=>x.server.close(r));x.cleanup();}
});
test('pending ledger after crash requires review',async()=>{
 const x=fixture();try {
  fs.writeFileSync(path.join(x.directory,'ledger.json'),JSON.stringify({'event-0001':{state:'pending',hash:require('node:crypto').createHash('sha256').update('hello').digest('hex')}}));
  const y=createBridge({driver:{ready:()=>true,send:async()=>{throw Error('must not call');}},token,recipient:'31600000000',directory:x.directory});
  assert.equal((await y.send('event-0001','hello'))[0],409);
 }finally{x.cleanup();}
});
test('manual review can clear an uncertain event through authenticated HTTP',async()=>{
 const x=fixture({fail:true});x.server.listen(0,'127.0.0.1');await new Promise(r=>x.server.once('listening',r));
 try {
  await x.send('event-0001','hello');assert.equal(x.ledger['event-0001'].state,'uncertain');
  const response=await fetch('http://127.0.0.1:'+x.server.address().port+'/resolve',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({event_id:'event-0001',decision:'retry'})});
  assert.equal(response.status,200);assert.equal(x.ledger['event-0001'],undefined);
 }finally{await new Promise(r=>x.server.close(r));x.cleanup();}
});
