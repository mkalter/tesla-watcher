"""Text-only WhatsApp linked device. No browser, Node.js or paid API."""
import io
import logging
import os
from pathlib import Path
import re
import threading
import time


class NativeWhatsApp:
    def __init__(self, directory, recipient, terminal_qr=False):
        recipient=recipient.strip().lstrip('+').replace(' ','')
        if recipient and not re.fullmatch(r'\d{8,15}',recipient):
            raise ValueError('WHATSAPP_TO: use your receiving number with country code, digits only')
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.recipient=recipient
        self.terminal_qr=terminal_qr
        self._ready=False
        self._qr=None
        self._qr_time=0
        self._error=''
        self._stop=threading.Event()
        self._thread=None
        self._client=None
        self._state_lock=threading.Lock()
        self._send_lock=threading.Lock()

    def status(self):
        with self._state_lock:
            return {'ready':self._ready,'qr_available':self._qr is not None and time.monotonic()-self._qr_time<120,
                    'error':self._error,'driver':'neonize','browser_required':False,'recipient_configured':bool(self.recipient)}

    def ready(self):
        with self._state_lock:return self._ready and bool(self.recipient)

    def set_recipient(self,recipient):
        if not re.fullmatch(r'\d{8,15}',recipient):raise ValueError('Gebruik een nummer met landcode, alleen cijfers.')
        with self._state_lock:self.recipient=recipient

    def qr(self):
        with self._state_lock:
            return self._qr if time.monotonic()-self._qr_time<120 else None

    def _receive_qr(self, _client, raw):
        raw=bytes(raw)
        if raw.startswith(b'\x89PNG\r\n\x1a\n'):
            png=raw
        else:
            import segno
            code=segno.make(raw.decode('utf-8'),micro=False)
            buffer=io.BytesIO();code.save(buffer,kind='png',scale=5,border=4)
            png=buffer.getvalue()
            if self.terminal_qr:
                # Only opt in on a private hosting console; never log QR payloads.
                code.terminal(compact=True)
        with self._state_lock:
            self._qr=png;self._qr_time=time.monotonic();self._ready=False;self._error=''
        print('WhatsApp: nieuwe QR beschikbaar op de beveiligde webpagina.',flush=True)

    def _make_client(self):
        # Set before loading the Go runtime. This is a soft GC target, not a RAM guarantee.
        os.environ.setdefault('GOMEMLIMIT','96MiB')
        os.environ.setdefault('GOGC','50')
        from neonize.client import NewClient
        from neonize.events import ConnectedEv,DisconnectedEv,LoggedOutEv
        logging.getLogger('Neonize').setLevel(logging.WARNING)
        logging.getLogger('neonize').setLevel(logging.WARNING)
        client=NewClient(str((self.directory/'session.sqlite').resolve()))
        client.qr(self._receive_qr)
        @client.event(ConnectedEv)
        def connected(_client,_event):
            with self._state_lock:
                self._ready=True;self._qr=None;self._error=''
            print('WhatsApp: gekoppeld apparaat verbonden.',flush=True)
        @client.event(DisconnectedEv)
        def disconnected(_client,_event):
            with self._state_lock:
                self._ready=False;self._error='Verbinding verbroken; de client probeert opnieuw te verbinden.'
        @client.event(LoggedOutEv)
        def logged_out(_client,_event):
            with self._state_lock:
                self._ready=False;self._qr=None;self._error='WhatsApp heeft het apparaat uitgelogd. Opnieuw koppelen vereist.'
        return client

    def start(self):
        if self._thread and self._thread.is_alive():return
        self._stop.clear()
        self._thread=threading.Thread(target=self._run,name='whatsapp-linked-device',daemon=True)
        self._thread.start()

    def _run(self):
        delay=5
        while not self._stop.is_set():
            try:
                self._client=self._make_client()
                self._client.connect()
                delay=5
            except Exception as exc:
                # No credentials or QR bytes are included in diagnostics.
                with self._state_lock:self._error=f'WhatsApp-start mislukt ({type(exc).__name__}). Controleer dependencies en hostingconsole.'
                logging.error('WhatsApp client setup failed: %s',type(exc).__name__)
            finally:
                with self._state_lock:self._ready=False
                if self._client:
                    try:self._client.stop()
                    except Exception:pass
                self._client=None
            if self._stop.wait(delay):break
            delay=min(delay*2,120)

    def send(self,text):
        if not isinstance(text,str) or not text.strip() or len(text)>6000:
            raise ValueError('WhatsApp text must contain 1–6000 characters')
        with self._send_lock:
            if not self.ready() or self._client is None:
                raise RuntimeError('WhatsApp is not connected')
            response=self._client.send_message(self.recipient,text,link_preview=False)
            message_id=getattr(response,'ID','')
            if not message_id:
                raise RuntimeError('WhatsApp returned no server message ID')
            return str(message_id)

    def stop(self):
        self._stop.set()
        client=self._client
        if client:
            try:client.stop()
            except Exception:pass
        if self._thread:self._thread.join(timeout=5)


def recover_inflight(store):
    """The outcome of a send interrupted by process death needs manual review."""
    with store.db:
        store.db.execute("UPDATE events SET state='uncertain',last_error='Interrupted send; inspect WhatsApp before retry' WHERE state='sending'")


def deliver_native(store,driver,clock=None,max_batch=20,pause=2):
    clock=time.time() if clock is None else clock
    sent=0
    for event in store.pending(clock)[:max_batch]:
        if not driver.ready():break
        # Persist the attempt BEFORE crossing the network. Never automatically retry
        # an outcome that might already have reached the WhatsApp server.
        with store.db:
            claimed=store.db.execute("UPDATE events SET state='sending',attempts=attempts+1 WHERE id=? AND state='queued'",(event['id'],)).rowcount
        if not claimed:continue
        try:
            driver.send(event['text'])
            store.set_event(event['id'],'sent')
            sent+=1
        except Exception as exc:
            store.set_event(event['id'],'uncertain',f'{type(exc).__name__}: inspect WhatsApp before retry')
            break
        if pause and sent<max_batch:time.sleep(pause)
    return sent
