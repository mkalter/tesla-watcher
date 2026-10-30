"""Free ntfy.sh notifications; no WhatsApp account or linked device."""
import io
import base64
import json
import os
from pathlib import Path
import re
import secrets
import time
import urllib.error
import urllib.request
from .models import Listing,message
from .media import check_image_url,fetch_photo

class Ntfy:
    def __init__(self,directory):
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.server=os.environ.get('NTFY_SERVER','https://ntfy.sh').rstrip('/')
        if self.server!='https://ntfy.sh':raise ValueError('This setup uses https://ntfy.sh')
        target=directory/'ntfy-topic.txt'
        topic=os.environ.get('NTFY_TOPIC','').strip()
        if not topic:
            if target.exists():topic=target.read_text(encoding='utf-8').strip()
            else:
                topic='tesla-'+secrets.token_hex(16)
                with target.open('x',encoding='utf-8') as handle:handle.write(topic+'\n')
                target.chmod(0o600)
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',topic):raise ValueError('NTFY_TOPIC must contain 8–64 letters, digits, hyphens or underscores')
        self.topic=topic
        self.url=self.server+'/'+topic
        (directory/'ntfy-subscribe.txt').write_text(self.url+'\n',encoding='utf-8')
        self.error=''
    def start(self):pass
    def stop(self):pass
    def ready(self):return True
    def status(self):
        return {'driver':'ntfy','ready':True,'qr_available':True,'error':self.error,
                'server':self.server,'topic':self.topic,'subscribe_url':self.url,'phase':'ready','recipient_configured':True}
    def qr(self):
        import segno
        output=io.BytesIO();segno.make('ntfy://ntfy.sh/'+self.topic,micro=False).save(output,kind='png',scale=5)
        return output.getvalue()
    def relink(self):raise ValueError('WhatsApp is uitgeschakeld; meldingen gaan via ntfy.')
    def set_recipient(self,*args):raise ValueError('Stel je abonnement in de ntfy-app in.')
    def body(self,event):
        try:record=json.loads(event['payload'] or '{}')
        except (TypeError,json.JSONDecodeError):record={}
        if record.get('url') and record.get('source'):
            listing=Listing(**record)
            formatted=message(listing,kind=event['kind'])
            lines=formatted.splitlines()
            title=lines[0].strip('*')+' · '+lines[1].strip('*')
            # The native click action carries the advert URL; keep the body concise.
            body='\n'.join(lines[3:]).split('\n\nBekijk advertentie:')[0]
            if event['kind']=='example':body+='\n\nVoorbeeldbericht · geen nieuwe advertentie'
            if 'Eenmalig lokaal opgehaald' in event['text']:body+='\nEenmalig lokaal opgehaald; scan op host niet beschikbaar.'
            result={'topic':self.topic,'title':title,'message':body,'priority':3,'tags':['car'],
                    'click':listing.url,'actions':[{'action':'view','label':'Bekijk advertentie','url':listing.url}]}
            if listing.image_url:
                result['attach']=check_image_url(listing.image_url)
            return result
        return {'topic':self.topic,'title':'Tesla Watcher · Testmelding','message':event['text'],'priority':3,'tags':['car']}
    def prepare(self,event):
        payload=self.body(event)
        return fetch_photo(payload['attach']) if payload.get('attach') else None

    def publish(self,event,photo=None):
        payload=self.body(event)
        if payload.get('attach'):
            if photo is None:photo=self.prepare(event)
            encoded=lambda value:'=?utf-8?b?'+base64.b64encode(value.encode('utf-8')).decode('ascii')+'?='
            headers={'Content-Type':'image/jpeg','Filename':'tesla-model-s.jpg','Title':encoded(payload['title']),
                     'Message':encoded(payload['message']),'Priority':'3','Tags':'car',
                     'Click':encoded(payload['click']),'Actions':json.dumps(payload['actions'],ensure_ascii=True),'User-Agent':'TeslaWatcher/2.0'}
            request=urllib.request.Request(self.url,data=photo,headers=headers,method='PUT')
        else:
            request=urllib.request.Request(self.server+'/',data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),
                                           headers={'Content-Type':'application/json','User-Agent':'TeslaWatcher/2.0'},method='POST')
        with urllib.request.urlopen(request,timeout=30) as response:
            result=json.loads(response.read(16384))
        if result.get('event')!='message' or not result.get('id'):raise ValueError('ntfy returned no message acknowledgement')
        self.error=''
        return result['id']


def deliver_ntfy(store,driver,clock=None,max_batch=20,pause=.5):
    clock=time.time() if clock is None else clock
    count=0
    for event in store.pending(clock)[:max_batch]:
        # Validate before claiming. Bad input has never crossed the network.
        try:driver.body(event)
        except (ValueError,TypeError) as exc:
            store.set_event(event['id'],'queued','Invalid ntfy payload: '+type(exc).__name__,clock+3600);continue
        try:photo=driver.prepare(event)
        except Exception as exc:
            store.set_event(event['id'],'queued','Photo download failed: '+type(exc).__name__,clock+300)
            driver.error='Advertentiefoto nog niet beschikbaar; melding blijft in de wachtrij.'
            continue
        with store.db:
            claimed=store.db.execute("UPDATE events SET state='sending',attempts=attempts+1 WHERE id=? AND state='queued'",(event['id'],)).rowcount
        if not claimed:continue
        try:
            driver.publish(event,photo=photo)
            store.set_event(event['id'],'sent')
            count+=1
            try:source=json.loads(event['payload'] or '{}').get('source','test')
            except (ValueError,TypeError):source='test'
            print(json.dumps({'ntfy':'server_acknowledged','kind':event['kind'],'source':source,'event':event['id'][:12]}),flush=True)
        except urllib.error.HTTPError as exc:
            if exc.code not in (400,401,403,413,429):
                store.set_event(event['id'],'uncertain',f'ntfy HTTP {exc.code}: controleer vóór opnieuw proberen')
                driver.error='Onzekere verzending; controleer ntfy.'
                break
            # Explicit validation/auth/rate rejection: safe to retry.
            retry=exc.headers.get('Retry-After','') if exc.headers else ''
            delay=min(3600,max(60,int(retry))) if retry.isdigit() else 300
            store.set_event(event['id'],'queued',f'ntfy HTTP {exc.code}',clock+delay)
            driver.error=f'ntfy geeft HTTP {exc.code}; melding blijft in de wachtrij.'
            break
        except Exception as exc:
            store.set_event(event['id'],'uncertain',type(exc).__name__+': controleer ntfy vóór opnieuw proberen')
            driver.error='Onzekere verzending; controleer ntfy en beoordeel het event.'
            break
        if pause:time.sleep(pause)
    return count
