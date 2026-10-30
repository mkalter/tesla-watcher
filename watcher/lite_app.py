"""One-process Python hosting: scanner + linked WhatsApp device + small web UI."""
import argparse
import base64
from datetime import datetime,timedelta,timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sqlite3
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
from html import escape
from .cli import load_config,scan
from .models import now
from .store import Store
from .native_whatsapp import NativeWhatsApp,deliver_native,recover_inflight


def load_env(path):
    """Only known settings; never execute a shell or overwrite panel variables."""
    if not path.exists():return
    allowed={'WHATSAPP_TO','ADMIN_PASSWORD','BRIDGE_TOKEN','PORT','SERVER_PORT','HOST',
             'DATA_DIR','CONFIG_FILE','TERMINAL_QR','SEND_NOTIFICATIONS','ENABLE_HTTPS_TUNNEL'}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:continue
        key,value=line.split('=',1)
        if key in allowed:os.environ.setdefault(key,value.strip().strip('"').strip("'"))


def password_for(directory,configured=None):
    if configured:
        if len(configured)<16:raise ValueError('ADMIN_PASSWORD must contain at least 16 characters')
        return configured
    target=directory/'admin-password.txt'
    if not target.exists():
        with target.open('x',encoding='utf-8') as handle:handle.write(secrets.token_urlsafe(24)+'\n')
        target.chmod(0o600)
    print('Web-login: admin. Het automatisch gemaakte wachtwoord staat in data/admin-password.txt; stel ADMIN_PASSWORD in voor een eigen wachtwoord.',flush=True)
    return target.read_text(encoding='utf-8').strip()


class LiteApp:
    def __init__(self,config,directory,password,recipient,driver=None,scan_fn=scan):
        self.directory=Path(directory).resolve()
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.config=json.loads(json.dumps(config))
        self.config.update(database=str(self.directory/'watcher.sqlite'),archive_dir=str(self.directory/'snapshots'),
                           status_file=str(self.directory/'status.json'))
        self.password=password
        recipient_file=self.directory/'recipient.txt'
        if recipient_file.exists():recipient=recipient_file.read_text(encoding='utf-8').strip()
        self.driver=driver or NativeWhatsApp(self.directory/'whatsapp',recipient,os.environ.get('TERMINAL_QR')=='1')
        self.scan_fn=scan_fn
        self.stop_event=threading.Event()
        self.scan_event=threading.Event()
        self._lock=threading.RLock()
        self._thread=None
        self._delivery_thread=None
        self._active=False
        self._next_scan=0
        self._last_scan=None
        self._notice=''
        self._enabled=os.environ.get('SEND_NOTIFICATIONS','true').lower() not in ('0','false','no')
        self._last_test=0
        runtime=self.directory/'runtime.json'
        if runtime.exists():self._enabled=bool(json.loads(runtime.read_text(encoding='utf-8')).get('notifications',self._enabled))
        store=Store(self.config['database'],self.config['filters'])
        try:recover_inflight(store)
        finally:store.close()

    def start(self):
        self.driver.start()
        self.scan_event.set()
        self._thread=threading.Thread(target=self._run,name='scanner-scheduler',daemon=True)
        self._thread.start()
        self._delivery_thread=threading.Thread(target=self._delivery_loop,name='outbox-delivery',daemon=True)
        self._delivery_thread.start()

    def stop(self):
        self.stop_event.set()
        self.scan_event.set()
        self.driver.stop()
        if self._thread:self._thread.join(timeout=5)
        if self._delivery_thread:self._delivery_thread.join(timeout=5)

    def request_scan(self):
        with self._lock:
            if self._active:return False
            self.scan_event.set();self._notice='Scan aangevraagd.'
            return True

    def set_notifications(self,enabled):
        with self._lock:
            self._enabled=enabled
            target=self.directory/'runtime.json';temp=target.with_suffix('.tmp')
            temp.write_text(json.dumps({'notifications':enabled}),encoding='utf-8');temp.replace(target)
            self._notice='Meldingen ingeschakeld.' if enabled else 'Meldingen gepauzeerd; nieuwe events blijven in de wachtrij.'

    def queue_test(self):
        with self._lock:
            if not self._enabled:raise ValueError('Zet meldingen eerst aan om een test te versturen.')
            if not self.driver.ready():raise ValueError('Koppel WhatsApp eerst.')
            if time.monotonic()-self._last_test<15:raise ValueError('Wacht vijftien seconden tussen testmeldingen.')
            with sqlite3.connect(self.config['database'],timeout=5) as connection:
                if connection.execute("SELECT COUNT(*) FROM events WHERE kind='test' AND state='queued'").fetchone()[0]:
                    raise ValueError('Er staat al een testmelding klaar.')
                event_id=hashlib.sha256(secrets.token_bytes(32)).hexdigest()
                text='Tesla Watcher: de lichte Python-versie is verbonden. Controleer of je telefoon een melding geeft.'
                connection.execute("INSERT INTO events(id,kind,payload,text,created_at) VALUES (?,'test','{}',?,?)",(event_id,text,now()))
            self._last_test=time.monotonic();self._notice='Testmelding toegevoegd. Controleer je WhatsApp-chat en de telefoonmelding.'

    def relink_whatsapp(self):
        with self._lock:
            self.driver.relink()
            self._notice='Nieuwe WhatsApp-koppeling aangevraagd.'

    def set_recipient(self,number):
        number=number.strip().lstrip('+').replace(' ','')
        if not re.fullmatch(r'\d{8,15}',number):raise ValueError('Gebruik je eigen ontvangernummer met landcode, alleen cijfers.')
        with self._lock:
            target=self.directory/'recipient.txt';temp=target.with_suffix('.tmp')
            temp.write_text(number,encoding='utf-8');temp.replace(target)
            self.driver.set_recipient(number)
            self._notice='Ontvangernummer opgeslagen. Stuur nu een testmelding.'

    def resolve(self,event_id,decision):
        if not re.fullmatch(r'[a-f0-9]{64}',event_id) or decision not in ('retry','sent','discard'):
            raise ValueError('Ongeldige eventkeuze.')
        with sqlite3.connect(self.config['database'],timeout=5) as connection:
            row=connection.execute('SELECT state FROM events WHERE id=?',(event_id,)).fetchone()
            if not row or row[0]!='uncertain':raise ValueError('Alleen onzekere events kunnen worden beoordeeld.')
            state={'retry':'queued','sent':'sent','discard':'discarded'}[decision]
            connection.execute('UPDATE events SET state=?,last_error=?,next_attempt=0,sent_at=? WHERE id=?',
                               (state,'Manually reviewed',now() if state=='sent' else None,event_id))
        with self._lock:self._notice='Event beoordeeld.'

    def flush(self,store):
        with self._lock:enabled=self._enabled
        if not enabled:return 0
        return deliver_native(store,self.driver)

    def _flush_pending(self):
        if not self.driver.ready():return
        with self._lock:enabled=self._enabled
        if not enabled:return
        store=Store(self.config['database'],self.config['filters'])
        try:deliver_native(store,self.driver)
        finally:store.close()

    def _delivery_loop(self):
        while not self.stop_event.is_set():
            try:self._flush_pending()
            except Exception as exc:print('Wachtrijfout: '+type(exc).__name__,flush=True)
            self.stop_event.wait(3)

    def prune_snapshots(self):
        retention=int(self.config.get('snapshot_retention_days',7))
        if retention<1:return
        cutoff=(datetime.now(timezone.utc)-timedelta(days=retention)).date().isoformat()
        root=Path(self.config['archive_dir'])
        if not root.exists():return
        for folder in root.iterdir():
            if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',folder.name) or folder.name>=cutoff:continue
            for file in folder.iterdir():
                if not file.is_symlink() and file.is_file() and (file.name.endswith('.json') or file.name.endswith('.json.gz')):
                    file.unlink()
            try:folder.rmdir()
            except OSError:pass

    def _run(self):
        args=SimpleNamespace(mode='http',headed=False,source=None,capture_html=False,no_send=False)
        while not self.stop_event.is_set():
            try:
                if self.scan_event.is_set() or time.monotonic()>=self._next_scan:
                    self.scan_event.clear()
                    with self._lock:self._active=True
                    began=time.monotonic()
                    try:
                        # A separate worker delivers even during a lengthy source scan.
                        result=self.scan_fn(self.config,args,notifier=lambda store:0)
                        with self._lock:
                            self._last_scan=now();self._notice='Scan afgerond.' if result==0 else 'Scan afgerond met fouten; zie bronstatus.'
                        self.prune_snapshots()
                    finally:
                        with self._lock:
                            self._active=False
                            self._next_scan=max(began+self.config.get('interval_seconds',600),time.monotonic()+5)
            except Exception as exc:
                with self._lock:self._notice='Controle mislukt: '+type(exc).__name__
                print('Scannerfout: '+type(exc).__name__,flush=True)
                self._next_scan=time.monotonic()+60
            self.stop_event.wait(3)

    def status(self):
        with self._lock:
            result={'active':self._active,'next_scan_in':max(0,round(self._next_scan-time.monotonic())),
                    'last_scan':self._last_scan,'notice':self._notice,'notifications':self._enabled}
        with sqlite3.connect(self.config['database'],timeout=5) as connection:
            connection.row_factory=sqlite3.Row
            result['sources']=[dict(r) for r in connection.execute('SELECT * FROM sources ORDER BY name')]
            result['events']={r[0]:r[1] for r in connection.execute('SELECT state,COUNT(*) FROM events GROUP BY state')}
            result['uncertain']=[dict(r) for r in connection.execute("SELECT id,text,last_error FROM events WHERE state='uncertain' ORDER BY created_at DESC LIMIT 20")]
        result['whatsapp']=self.driver.status()
        return result

    def handler(self):
        app=self
        class Handler(BaseHTTPRequestHandler):
            server_version='TeslaWatcher/2'
            def log_message(self,*args):pass
            def authorized(self):
                header=self.headers.get('Authorization','')
                if not header.startswith('Basic '):return False
                try:user,secret=base64.b64decode(header[6:],validate=True).decode('utf-8').split(':',1)
                except (ValueError,UnicodeError):return False
                return user=='admin' and hmac.compare_digest(secret.encode(),app.password.encode())
            def respond(self,status,body,content_type='application/json; charset=utf-8',extra=None):
                self.send_response(status)
                self.send_header('Content-Type',content_type);self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Security-Policy',"default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
                for k,v in (extra or {}).items():self.send_header(k,v)
                data=body if isinstance(body,bytes) else body.encode('utf-8')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def guard(self):
                if self.authorized():return True
                self.respond(401,'{"error":"Login required"}',extra={'WWW-Authenticate':'Basic realm="Tesla Watcher"'})
                return False
            def do_GET(self):
                if self.path=='/healthz':return self.respond(200,'{"alive":true}')
                if not self.guard():return
                try:
                    if self.path=='/status':return self.respond(200,json.dumps(app.status(),ensure_ascii=False))
                    if self.path=='/qr':
                        image=app.driver.qr()
                        return self.respond(200,image,'image/png') if image else self.respond(409,'{"error":"No current QR"}')
                    if self.path=='/':return self.respond(200,render(app.status()),'text/html; charset=utf-8')
                    return self.respond(404,'{"error":"Not found"}')
                except Exception:return self.respond(503,'{"error":"Status temporarily unavailable"}')
            def do_POST(self):
                if not self.guard():return
                origin=self.headers.get('Origin')
                if origin:
                    parsed=urlsplit(origin)
                    if parsed.scheme not in ('http','https') or parsed.netloc!=self.headers.get('Host'):
                        return self.respond(403,'{"error":"Origin rejected"}')
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if size<0 or size>2048:return self.respond(413,'{"error":"Request too large"}')
                    body=self.rfile.read(size)
                    if self.path=='/scan':app.request_scan()
                    elif self.path=='/test':app.queue_test()
                    elif self.path=='/notifications/on':app.set_notifications(True)
                    elif self.path=='/notifications/off':app.set_notifications(False)
                    elif self.path=='/whatsapp/relink':app.relink_whatsapp()
                    elif self.path=='/recipient':
                        from urllib.parse import parse_qs
                        form=parse_qs(body.decode('utf-8'))
                        app.set_recipient(form.get('number',[''])[0])
                    elif self.path=='/resolve':
                        from urllib.parse import parse_qs
                        form=parse_qs(body.decode('utf-8'))
                        app.resolve(form.get('id',[''])[0],form.get('decision',[''])[0])
                    else:return self.respond(404,'{"error":"Not found"}')
                    return self.respond(303,'',extra={'Location':'/'})
                except (ValueError,sqlite3.Error) as exc:
                    return self.respond(400,json.dumps({'error':str(exc)},ensure_ascii=False))
        return Handler


def render(status):
    w=status['whatsapp']
    rows=''.join('<tr><td>'+escape(str(r['name']))+'</td><td>'+escape('fout' if r['error'] else 'ok')+'</td><td>'+str(r['count'])+'</td><td>'+escape(str(r['last_success'] or 'nog niet'))+'</td><td>'+escape(str(r['error'] or ''))+'</td></tr>' for r in status['sources'])
    pairing='<p>Verbonden met WhatsApp.</p>' if w['ready'] else '<img class="qr" src="/qr" alt="QR wordt geladen">' if w['qr_available'] else '<p>WhatsApp-status: '+escape(w.get('phase','starten'))+'. Wacht op de QR of bekijk de fout hieronder.</p>'
    pairing+='<p class="muted">Fase: '+escape(w.get('phase','onbekend'))+'</p>'
    pairing+='<form method="post" action="/whatsapp/relink"><button>Opnieuw koppelen (bestaande sessie wissen)</button></form>'
    recipient_form='<p>Ontvangernummer opgeslagen.</p>' if w.get('recipient_configured',False) else '<p>Vul je eigen ontvangernummer met landcode in om meldingen te ontvangen.</p>'
    recipient_form+='<form method="post" action="/recipient"><label>Jouw ontvangernummer <input name="number" type="tel" placeholder="31612345678" pattern="[+0-9 ]{8,20}" required autocomplete="tel"></label><button>Nummer opslaan</button></form>'
    reviews=''
    for event in status['uncertain']:
        reviews+='<details><summary>Onzekere verzending — controleer je WhatsApp-chat</summary><pre>'+escape(event['text'])+'</pre><form method="post" action="/resolve"><input type="hidden" name="id" value="'+escape(event['id'])+'"><button name="decision" value="sent">Staat al in mijn chat</button><button name="decision" value="retry">Niet verzonden: opnieuw proberen</button><button name="decision" value="discard">Overslaan</button></form></details>'
    toggle='off' if status['notifications'] else 'on'
    label='Meldingen pauzeren' if status['notifications'] else 'Meldingen aanzetten'
    return '''<!doctype html><html lang="nl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="5"><title>Tesla Watcher</title><style>body{font:16px system-ui;color:#161616;background:#f5f5f7;max-width:1080px;margin:32px auto;padding:16px}section{background:white;padding:24px;border-radius:20px;margin:16px 0}h1{font-size:36px;margin:0}.qr{max-width:280px;width:100%}button{border:0;background:#0071e3;color:white;border-radius:10px;padding:10px 16px;cursor:pointer;margin:4px}form{display:inline}table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:10px 6px;border-bottom:1px solid #eee}pre{white-space:pre-wrap;overflow-wrap:anywhere}.scroll{overflow-x:auto}.muted{color:#666}</style><h1>Tesla Watcher</h1><p class="muted">Nieuwe Tesla Model S-advertenties vanaf 2022 · elke tien minuten</p><section><h2>WhatsApp koppelen</h2><p>WhatsApp → Instellingen → Gekoppelde apparaten → Apparaat koppelen.</p>'''+pairing+recipient_form+'<p>'+escape(w.get('error',''))+'''</p><form method="post" action="/test"><button>Stuur testmelding</button></form><p class="muted">Controleer ook of je telefoon een pushmelding geeft. Berichten aan jezelf geven mogelijk geen geluid.</p></section><section><h2>Scanner</h2><p>'''+escape(status['notice'])+'</p><p>'+('Scan loopt.' if status['active'] else 'Volgende scan over '+str(status['next_scan_in'])+' seconden.')+'</p><form method="post" action="/scan"><button>Nu scannen</button></form><form method="post" action="/notifications/'+toggle+'"><button>'+label+'</button></form><p>Wachtrij: '+escape(json.dumps(status['events']))+'</p><div class="scroll"><table><tr><th>Bron</th><th>Status</th><th>Advertenties</th><th>Laatste succes (UTC)</th><th>Fout</th></tr>'+rows+'</table></div>'+reviews+'</section></html>'


def main():
    parser=argparse.ArgumentParser(description='Lightweight Tesla Watcher: Python only')
    parser.add_argument('--check',action='store_true',help='Validate native dependency and config without connecting to WhatsApp')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    load_env(root/'.env')
    os.umask(0o077)
    config_path=Path(os.environ.get('CONFIG_FILE',str(root/'config.light.json')))
    config=load_config(config_path)
    directory=Path(os.environ.get('DATA_DIR',str(root/'data'))).resolve()
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if args.check:
        from neonize.client import NewClient
        import importlib.metadata
        print(json.dumps({'python_config':'ok','whatsapp_driver':'neonize','neonize_version':importlib.metadata.version('neonize'),
                          'browser_required':False,'node_required':False,'sources':len(config['sources']),'max_workers':config.get('max_workers')}))
        return
    recipient=os.environ.get('WHATSAPP_TO','').strip()
    if recipient and not re.fullmatch(r'\+?\d{8,15}',recipient):raise SystemExit('WHATSAPP_TO: gebruik je ontvangernummer inclusief landcode, alleen cijfers.')
    password=password_for(directory,os.environ.get('ADMIN_PASSWORD') or os.environ.get('BRIDGE_TOKEN'))
    app=LiteApp(config,directory,password,recipient)
    port=int(os.environ.get('PORT') or os.environ.get('SERVER_PORT') or '8080')
    if not 0<port<65536:raise SystemExit('PORT moet tussen 1 en 65535 liggen.')
    server=ThreadingHTTPServer((os.environ.get('HOST','0.0.0.0'),port),app.handler())
    # Binding before starting prevents an orphan scheduler if the hosting port is wrong.
    app.start()
    tunnel=None
    if os.environ.get('ENABLE_HTTPS_TUNNEL')=='1':
        from .tunnel import QuickTunnel
        tunnel=QuickTunnel(directory,port);tunnel.start()
    def stop(_signal,_frame):
        threading.Thread(target=server.shutdown,daemon=True).start()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop)
    print(f'Tesla Watcher gestart op poort {port}. Web-login: admin. Koppel WhatsApp via de beveiligde webpagina.',flush=True)
    try:server.serve_forever(poll_interval=.5)
    finally:
        server.server_close();app.stop()
        if tunnel:tunnel.stop()
