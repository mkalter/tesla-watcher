import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import urllib.request
import gzip
from concurrent.futures import ThreadPoolExecutor,as_completed
from .models import Listing, now, reject_reason
from .store import Store
from .sources import Fetcher,scan_source,archive_snapshot
from .notify import deliver


def load_config(path):
    c=json.loads(Path(path).read_text())
    if c.get('interval_seconds',600)<600:
        raise ValueError('interval_seconds must be at least 600')
    sources=c.get('sources',[])
    names=[x['name'] for x in sources]
    if len(set(names))!=len(names):
        raise ValueError('Duplicate source names')
    if c.get('notifications',{}).get('enabled',False) and c['notifications'].get('transport')!='native' and not c['notifications'].get('bridge_url'):
        raise ValueError('notifications.bridge_url is required')
    if not isinstance(c.get('max_workers',3),int) or not 1<=c.get('max_workers',3)<=3:
        raise ValueError('max_workers must be between 1 and 3')
    c.setdefault('database','data/watcher.sqlite')
    c.setdefault('archive_dir','data/snapshots')
    c.setdefault('filters',{'min_year':2022})
    return c


@contextmanager
def process_lock(database):
    """OS-managed SQLite lock: automatically released even on an abrupt crash."""
    Path(database).parent.mkdir(parents=True,exist_ok=True)
    connection=sqlite3.connect(str(database)+'.lock',timeout=0)
    try:
        connection.execute('CREATE TABLE IF NOT EXISTS guard (id INTEGER)')
        connection.execute('BEGIN EXCLUSIVE')
    except sqlite3.OperationalError as exc:
        connection.close()
        raise RuntimeError('Another scan/replay is already running') from exc
    try:
        yield
    finally:
        connection.rollback(); connection.close()


def scan(c,args,notifier=None):
    timestamp=now()
    db=c['database']
    with process_lock(db):
        store=Store(db,c['filters'])
        summary=[]
        def collect(source):
            fetcher=Fetcher(args.mode,args.headed)
            try:
                items,pages=scan_source(fetcher,source,timestamp,c['archive_dir'],args.capture_html)
                return items,pages,now()
            finally:
                fetcher.close()
        try:
          selected=[s for s in c['sources'] if s.get('enabled',True) and (not args.source or s['name'] in args.source)]
          with ThreadPoolExecutor(max_workers=min(c.get('max_workers',3),len(selected) or 1)) as pool:
            futures={pool.submit(collect,s):s for s in selected}
            for future in as_completed(futures):
                source=futures[future]
                try:
                    items,pages,observed_at=future.result()
                    archive_snapshot(c['archive_dir'],source['name'],observed_at,items,pages=pages,compress=c.get('compress_snapshots',False))
                    events=store.ingest(source['name'],items,observed_at,c.get('price_alerts',False),c.get('min_price_drop',500))
                    row={'source':source['name'],'status':'ok','pages':pages,'parsed':len(items),
                         'matching':sum(not reject_reason(x,c['filters']) for x in items),'events':len(events)}
                except Exception as exc:
                    # Never bootstrap/advance a source from a failed or incomplete result.
                    store.fail(source['name'],str(exc),timestamp)
                    archive_snapshot(c['archive_dir'],source['name'],timestamp,error=str(exc),compress=c.get('compress_snapshots',False))
                    row={'source':source['name'],'status':'error','error':str(exc)[:400]}
                summary.append(row)
                print(json.dumps(row,ensure_ascii=False),flush=True)
          notification_error=False
          if c.get('notifications',{}).get('enabled') and not args.no_send:
                try:
                    sent=notifier(store) if notifier else deliver(store,c['notifications'])
                    print(json.dumps({'sent':sent}),flush=True)
                except Exception as exc:
                    notification_error=True
                    print(json.dumps({'notification_error':str(exc)}),file=sys.stderr,flush=True)
          report={'timestamp':timestamp,'sources':summary,'database':store.status(),
                    'note':'ok means this complete scan parsed successfully, not guaranteed future availability'}
          Path(c.get('status_file','data/status.json')).parent.mkdir(parents=True,exist_ok=True)
          temp=Path(c.get('status_file','data/status.json')+'.tmp')
          temp.write_text(json.dumps(report,ensure_ascii=False,indent=2))
          temp.replace(c.get('status_file','data/status.json'))
          return 0 if summary and all(x['status']=='ok' for x in summary) and not notification_error else 2
        finally:
            store.close()


def replay(paths,filters,output):
    snapshots=[]
    for raw in paths:
        p=Path(raw)
        files=sorted([*p.rglob('*.json'),*p.rglob('*.json.gz')]) if p.is_dir() else [p]
        for file in files:
            if file.name.endswith('.json.gz'):
                with gzip.open(file,'rt',encoding='utf-8') as handle:obj=json.load(handle)
            else:obj=json.loads(file.read_text(encoding='utf-8'))
            if isinstance(obj,list):snapshots.extend(obj)
            elif 'snapshots' in obj:snapshots.extend(obj['snapshots'])
            elif 'source' in obj and 'timestamp' in obj:snapshots.append(obj)
    # Input must be chronological: do not silently repair invalid replay data.
    previous=None
    for s in snapshots:
        dt=datetime.fromisoformat(s['timestamp'].replace('Z','+00:00'))
        if dt.tzinfo is None:raise ValueError('Replay timestamps must contain a timezone')
        if previous and dt<previous:raise ValueError('Replay input is not chronological')
        previous=dt
    with tempfile.TemporaryDirectory() as directory:
        store=Store(str(Path(directory)/'replay.sqlite'),filters)
        for s in snapshots:
            if s.get('status','ok')!='ok':
                store.fail(s['source'],s.get('error','simulated failure'),s['timestamp'])
                continue
            items=[Listing(**r) for r in s['listings']]
            store.ingest(s['source'],items,s['timestamp'],False)
        events=store.events()
        report={'type':'snapshot_replay','snapshots':len(snapshots),'events':len(events),
                'new_listing_ids':[json.loads(e['payload'])['source_id'] for e in events],
                'status':store.status(), 'data_origin':'User-supplied captures; see input metadata. No invented historical market coverage.'}
        store.close()
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description='Tesla Model S website scanner + WhatsApp Web notifications')
    parser.add_argument('--config',default='config.json')
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('scan','run'):
        p=sub.add_parser(command)
        p.add_argument('--source',action='append',help='source name; repeat to select several')
        p.add_argument('--mode',choices=('http','auto','browser'),default='auto')
        p.add_argument('--headed',action='store_true')
        p.add_argument('--no-send',action='store_true',help='still record events in the durable outbox')
        p.add_argument('--capture-html',action='store_true',help='also save raw HTML for debugging; may contain seller data')
    sub.add_parser('status')
    sub.add_parser('events')
    p=sub.add_parser('resolve-event')
    p.add_argument('id');p.add_argument('decision',choices=('sent','retry','discard'))
    p=sub.add_parser('replay');p.add_argument('paths',nargs='+');p.add_argument('--output',default='reports/replay.json')
    p=sub.add_parser('backup');p.add_argument('output')
    args=parser.parse_args(argv)
    c=load_config(args.config)
    if args.command in ('scan','run'):
        while True:
            started=time.monotonic()
            code=scan(c,args)
            if args.command=='scan':return code
            delay=max(0,c.get('interval_seconds',600)-(time.monotonic()-started))
            print(json.dumps({'next_scan_in_seconds':round(delay)}),flush=True)
            time.sleep(delay)
    if args.command=='replay':
        print(json.dumps(replay(args.paths,c['filters'],args.output),ensure_ascii=False,indent=2));return 0
    with process_lock(c['database']):
        store=Store(c['database'],c['filters'])
        try:
            if args.command=='status':print(json.dumps(store.status(),indent=2))
            if args.command=='events':print(json.dumps(store.events(),ensure_ascii=False,indent=2))
            if args.command=='resolve-event':
                state={'sent':'sent','retry':'queued','discard':'discarded'}[args.decision]
                if not store.db.execute('SELECT id FROM events WHERE id=?',(args.id,)).fetchone():
                    raise ValueError('Unknown event ID')
                if args.decision=='retry' and c['notifications'].get('transport')!='native':
                    token=os.environ.get('BRIDGE_TOKEN','')
                    if not token:raise ValueError('BRIDGE_TOKEN required to reconcile the bridge ledger')
                    req=urllib.request.Request(c['notifications']['bridge_url'].rstrip('/')+'/resolve',
                        data=json.dumps({'event_id':args.id,'decision':'retry'}).encode(),
                        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
                    with urllib.request.urlopen(req,timeout=15) as response:
                        if not json.loads(response.read()).get('resolved'):raise ValueError('Bridge resolution failed')
                store.set_event(args.id,state,'manually reviewed')
            if args.command=='backup':
                Path(args.output).parent.mkdir(parents=True,exist_ok=True)
                dest=sqlite3.connect(args.output)
                try:store.db.backup(dest)
                finally:dest.close()
        finally:store.close()
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}',file=sys.stderr)
        sys.exit(1)
