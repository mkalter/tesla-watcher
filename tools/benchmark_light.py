"""Offline resource smoke test. Does not pair or contact WhatsApp."""
import os
os.environ.setdefault('GOMEMLIMIT','96MiB')
os.environ.setdefault('GOGC','50')
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import gc,json,resource,tempfile,time
from watcher.cli import load_config
from watcher.native_whatsapp import NativeWhatsApp
from watcher.parsing import parse_page

root=Path(__file__).resolve().parents[1]
config=load_config(root/'config.light.json')
began=time.monotonic();counts={}
with tempfile.TemporaryDirectory() as directory:
    client=NativeWhatsApp(Path(directory)/'whatsapp','31612345678')._make_client()
    for source in config['sources']:
        # Optional local full captures, otherwise the committed reduced fixtures.
        path=root/'reports'/(source['name']+'.html')
        if not path.exists():path=root/'fixtures'/(source['name']+'.html')
        if not path.exists():continue
        items,_,_=parse_page(path.read_text(encoding='utf-8'),source,'2026-10-30T00:00:00+00:00')
        counts[source['name']]={'listings':len(items),'capture_bytes':path.stat().st_size}
        del items;gc.collect()
report={'type':'offline_resource_smoke','neonize_constructed':True,'whatsapp_connected':False,
        'max_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1),
        'elapsed_seconds':round(time.monotonic()-began,2),'sources':counts,
        'limitations':'Unpaired client and sequential stored HTML. Not a connected-session memory guarantee or live host test.'}
print(json.dumps(report,indent=2))
