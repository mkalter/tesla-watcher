"""Optional temporary HTTPS access through Cloudflare's official quick tunnel client."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import urllib.request

class QuickTunnel:
    def __init__(self,directory,port):
        self.directory=Path(directory);self.port=port;self.process=None
        self.stop_event=threading.Event();self.thread=None
    def binary(self):
        folder=self.directory/'bin';folder.mkdir(parents=True,exist_ok=True)
        target=folder/'cloudflared'
        metadata=folder/'cloudflared.json'
        if target.exists() and metadata.exists():
            expected=json.loads(metadata.read_text())['sha256']
            with target.open('rb') as handle:actual=hashlib.file_digest(handle,'sha256').hexdigest()
            if actual==expected:return target
        request=urllib.request.Request('https://api.github.com/repos/cloudflare/cloudflared/releases/latest',headers={'User-Agent':'TeslaWatcher/2'})
        with urllib.request.urlopen(request,timeout=30) as response:release=json.load(response)
        asset=next(a for a in release['assets'] if a['name']=='cloudflared-linux-amd64')
        digest=asset.get('digest','')
        if not re.fullmatch('sha256:[0-9a-f]{64}',digest):raise ValueError('Missing vendor SHA256 digest')
        expected=digest[7:];url=asset['browser_download_url']
        if not url.startswith('https://github.com/cloudflare/cloudflared/releases/download/'):raise ValueError('Unexpected vendor URL')
        temporary=target.with_suffix('.download');hasher=hashlib.sha256();size=0
        with urllib.request.urlopen(url,timeout=60) as response,temporary.open('wb') as output:
            while True:
                block=response.read(1024*1024)
                if not block:break
                size+=len(block)
                if size>100*1024*1024:raise ValueError('Unexpected binary size')
                output.write(block);hasher.update(block)
        if hasher.hexdigest()!=expected:raise ValueError('Cloudflared checksum mismatch')
        temporary.chmod(0o700);temporary.replace(target)
        metadata.write_text(json.dumps({'version':release['tag_name'],'sha256':expected}))
        return target
    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True,name='https-tunnel');self.thread.start()
    def run(self):
        while not self.stop_event.is_set():
            try:
                binary=self.binary()
                if self.stop_event.is_set():return
                env=dict(os.environ,GOMEMLIMIT='32MiB',GOGC='50')
                self.process=subprocess.Popen([str(binary.resolve()),'tunnel','--no-autoupdate','--protocol','http2','--url',f'http://127.0.0.1:{self.port}'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env)
                if self.stop_event.is_set():self.process.terminate()
                for line in self.process.stdout:
                    match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com\b',line)
                    if match:
                        url=match.group(0)
                        (self.directory/'dashboard-url.txt').write_text(url+'\n')
                        print('Dashboard HTTPS (tijdelijke link): '+url,flush=True)
                self.process.wait();self.process.stdout.close()
            except Exception as exc:print('HTTPS-tunnel niet beschikbaar: '+type(exc).__name__,flush=True)
            if self.stop_event.wait(20):return
    def stop(self):
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill()
