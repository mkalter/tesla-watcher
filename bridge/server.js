'use strict';
const http=require('node:http'), fs=require('node:fs'), path=require('node:path'), crypto=require('node:crypto');
function createBridge({driver,token,recipient,directory,minInterval=2000}) {
  if(!token || token.length<24) throw Error('BRIDGE_TOKEN requires at least 24 characters');
  if(!/^\d{8,15}$/.test(recipient||'')) throw Error('WHATSAPP_TO must be your receiving number with country code, digits only');
  fs.mkdirSync(directory,{recursive:true,mode:0o700});
  const filename=path.join(directory,'ledger.json');
  const ledger=fs.existsSync(filename)?JSON.parse(fs.readFileSync(filename,'utf8')):{};
  let queue=Promise.resolve(),lastSend=0;
  const active=new Set();
  function persist() {
    const fd=fs.openSync(filename+'.tmp','w',0o600);
    try {fs.writeFileSync(fd,JSON.stringify(ledger));fs.fsyncSync(fd);} finally {fs.closeSync(fd);}
    fs.renameSync(filename+'.tmp',filename);
  }
  function authorized(req) {
    const header=req.headers.authorization||'';
    let candidate=header.startsWith('Bearer ')?header.slice(7):'';
    if(header.startsWith('Basic ')) {
      const decoded=Buffer.from(header.slice(6),'base64').toString();
      if(decoded.startsWith('admin:')) candidate=decoded.slice(6);
    }
    const a=Buffer.from(candidate),b=Buffer.from(token);
    return a.length===b.length && crypto.timingSafeEqual(a,b);
  }
  function reply(res,status,data) {
    res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
    res.end(JSON.stringify(data));
  }
  async function send(id,text) {
    let release; const before=queue;queue=new Promise(resolve=>{release=resolve;});await before;
    try {
      const hash=crypto.createHash('sha256').update(text).digest('hex');
      if(ledger[id]) {
        if(ledger[id].hash!==hash) return [409,{state:'conflict'}];
        return ledger[id].state==='sent'?[200,{state:'sent',duplicate:true}]:[409,{state:'uncertain',review:true}];
      }
      if(!driver.ready()) return [503,{state:'not_ready'}];
      const wait=Math.max(0,lastSend+minInterval-Date.now());
      if(wait) await new Promise(resolve=>setTimeout(resolve,wait));
      // A persisted pending intent prevents blind resends after crashes.
      ledger[id]={state:'pending',hash,created_at:new Date().toISOString()};persist();
      active.add(id);
      try {
        const result=await driver.send(recipient,text);
        ledger[id]={...ledger[id],state:'sent',message_id:result.id,sent_at:new Date().toISOString()};
        persist();lastSend=Date.now();return [200,{state:'sent'}];
      } catch(error) {ledger[id].state='uncertain';persist();return [409,{state:'uncertain',review:true}];}
    } finally {active.delete(id);release();}
  }
  const server=http.createServer(async(req,res)=>{
    try {
      if(req.url==='/healthz' && req.method==='GET') return reply(res,200,{alive:true});
      if(!authorized(req)) {res.setHeader('WWW-Authenticate','Basic realm="Tesla Watcher"');return reply(res,401,{error:'Authentication required'});}
      if(req.url==='/status' && req.method==='GET') return reply(res,200,{ready:driver.ready(),qrAvailable:Boolean(driver.qr()),driver:driver.name});
      if(req.url==='/events' && req.method==='GET') return reply(res,200,ledger);
      if(req.url==='/' && req.method==='GET') {
        res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'none'; frame-ancestors 'none'"});
        res.end('<!doctype html><html lang="nl"><meta charset="utf-8"><meta http-equiv="refresh" content="15"><title>Tesla Watcher · WhatsApp</title><style>body{background:#f5f5f7;color:#171717;font:17px system-ui;max-width:640px;margin:60px auto;padding:24px}section{background:white;border-radius:24px;padding:32px}img{width:280px;max-width:100%}a{color:#06c}</style><section><h1>WhatsApp koppelen</h1><p>WhatsApp → Instellingen → Gekoppelde apparaten → Apparaat koppelen.</p>'+(driver.ready()?'<p>✓ Verbonden. Controleer met de testmelding of je telefoon een notificatie krijgt.</p>':'<img src="/qr" alt="QR verschijnt zodra WhatsApp Web gereed is">')+'<p><a href="/status">Verbindingsstatus</a></p><form method="post" action="/test"><button>Stuur een testmelding naar ingesteld nummer</button></form><p>Alleen je ingestelde ontvangernummer kan berichten ontvangen.</p></section></html>');return;
      }
      if(req.url==='/qr' && req.method==='GET') {
        if(!driver.qr()) return reply(res,409,{error:'No QR currently available'});
        const png=await require('qrcode').toBuffer(driver.qr());
        res.writeHead(200,{'Content-Type':'image/png','Cache-Control':'no-store'});res.end(png);return;
      }
      if(req.url==='/test' && req.method==='POST') {
        const origin=req.headers.origin;
        if(origin && origin!==`http://${req.headers.host}` && origin!==`https://${req.headers.host}`) return reply(res,403,{error:'Origin rejected'});
        const [status,data]=await send('manual-'+crypto.randomUUID(),'Tesla Watcher: WhatsApp-test. Controleer of je telefoon een melding laat zien.');return reply(res,status,data);
      }
      if(req.url==='/send' && req.method==='POST') {
        let body='';
        for await(const chunk of req) {body+=chunk;if(Buffer.byteLength(body)>20000)return reply(res,413,{error:'Request too large'});}
        let data;try {data=JSON.parse(body);}catch {return reply(res,400,{error:'Invalid JSON'});}
        if(!/^[a-zA-Z0-9_-]{8,100}$/.test(data.event_id||'') || typeof data.text!=='string' || !data.text.trim() || data.text.length>6000) return reply(res,400,{error:'Invalid event_id or text'});
        const [status,result]=await send(data.event_id,data.text);return reply(res,status,result);
      }
      if(req.url==='/resolve' && req.method==='POST') {
        let body='';
        for await(const chunk of req) {body+=chunk;if(body.length>1000)return reply(res,413,{error:'Request too large'});}
        let data;try {data=JSON.parse(body);}catch{return reply(res,400,{error:'Invalid JSON'});}
        if(!/^[a-zA-Z0-9_-]{8,100}$/.test(data.event_id||'') || data.decision!=='retry') return reply(res,400,{error:'Invalid resolution'});
        if(active.has(data.event_id)) return reply(res,409,{error:'Send is still in progress'});
        // Manual review only. A confirmed sent event always remains deduplicated.
        if(ledger[data.event_id] && ledger[data.event_id].state!=='sent') {
          delete ledger[data.event_id];persist();
        }
        return reply(res,200,{resolved:true});
      }
      return reply(res,404,{error:'Not found'});
    } catch(error) {return reply(res,500,{error:'Bridge failure; review event before retry'});}
  });
  server.requestTimeout=100000;server.headersTimeout=10000;
  return {server,ledger,send};
}
function whatsappDriver(directory) {
  const {Client,LocalAuth}=require('whatsapp-web.js');
  let ready=false,qr=null;
  const args=process.env.CHROME_NO_SANDBOX==='1'?['--no-sandbox','--disable-setuid-sandbox']:[];
  const client=new Client({authStrategy:new LocalAuth({dataPath:path.join(directory,'session')}),
    puppeteer:{headless:true,args,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})}});
  client.on('qr',value=>{qr=value;ready=false;console.log('QR available on authenticated pairing page');});
  client.on('ready',()=>{ready=true;qr=null;console.log('WhatsApp Web connected');});
  client.on('disconnected',()=>{ready=false;console.error('Disconnected; restart required');setTimeout(()=>process.exit(1),500);});
  client.on('auth_failure',()=>{ready=false;qr=null;console.error('Authentication failed; review linked device');});
  return {name:'whatsapp-web.js',ready:()=>ready,qr:()=>qr,
    async send(number,text) {
      const contact=await client.getNumberId(number);
      if(!contact) throw Error('Recipient not registered');
      const msg=await client.sendMessage(contact._serialized,text,{sendSeen:false});
      if(!msg?.id?._serialized) throw Error('No message ID');
      for(let i=0;i<20;i++) {
        const current=await client.getMessageById(msg.id._serialized);
        if(current && current.ack>=1) return {id:msg.id._serialized};
        await new Promise(resolve=>setTimeout(resolve,1000));
      }
      throw Error('No server acknowledgement; outcome uncertain');
    },start:()=>client.initialize(),stop:()=>client.destroy()};
}
if(require.main===module) {
  const directory=process.env.BRIDGE_DATA||path.resolve('data');
  const driver=whatsappDriver(directory);
  const {server}=createBridge({driver,token:process.env.BRIDGE_TOKEN,recipient:process.env.WHATSAPP_TO,directory});
  server.listen(Number(process.env.PORT||3000),process.env.HOST||'127.0.0.1',()=>console.log('Pairing server started'));
  driver.start().catch(()=>{console.error('WhatsApp startup failed');server.close();process.exitCode=1;});
  for(const sig of ['SIGINT','SIGTERM']) process.on(sig,async()=>{server.close();await driver.stop();process.exit(0);});
}
module.exports={createBridge};
