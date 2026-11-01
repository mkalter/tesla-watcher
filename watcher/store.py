import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path
from .models import Listing, reject_reason, message, now


class Store:
    def __init__(self, path, filters):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.filters = filters
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources(name TEXT PRIMARY KEY, baseline INTEGER DEFAULT 0,
                last_success TEXT, last_attempt TEXT, error TEXT, failures INTEGER DEFAULT 0, count INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS cars(id INTEGER PRIMARY KEY, eligible_seen INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS identities(key TEXT PRIMARY KEY, car_id INTEGER REFERENCES cars(id));
            CREATE TABLE IF NOT EXISTS listings(source TEXT, source_id TEXT, car_id INTEGER REFERENCES cars(id),
                payload TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                PRIMARY KEY(source,source_id));
            CREATE TABLE IF NOT EXISTS prices(source TEXT, source_id TEXT, observed_at TEXT, price INTEGER,
                PRIMARY KEY(source,source_id,observed_at,price));
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, car_id INTEGER, kind TEXT,
                payload TEXT, text TEXT, state TEXT DEFAULT 'queued', attempts INTEGER DEFAULT 0,
                next_attempt REAL DEFAULT 0, last_error TEXT, created_at TEXT, sent_at TEXT);
        ''')
        signature = hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()
        row = self.db.execute("SELECT value FROM meta WHERE key='filters'").fetchone()
        if row and row[0] != signature:
            raise ValueError('Filters changed: choose a new database path to establish a clean baseline.')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('filters',?)", (signature,))
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('namespace',?)", (str(uuid.uuid4()),))
        self.namespace = self.db.execute("SELECT value FROM meta WHERE key='namespace'").fetchone()[0]

    def close(self):
        self.db.close()

    def fail(self, source, error, timestamp=None):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO sources(name) VALUES (?)', (source,))
            self.db.execute('UPDATE sources SET error=?, failures=failures+1, last_attempt=? WHERE name=?',
                            (str(error)[:500], timestamp or now(), source))

    def identities(self, x):
        keys = [f'url:{x.url}']
        vin = re.sub(r'\s', '', x.vin.upper())
        if re.fullmatch(r'[A-HJ-NPR-Z0-9]{17}', vin):
            keys.append('vin:' + vin)
        plate = re.sub(r'[^A-Z0-9]', '', x.plate.upper())
        if x.country and 5 <= len(plate) <= 12:
            keys.append('plate:' + x.country + ':' + plate)
        return keys

    def _entity(self, x, existing):
        keys = self.identities(x)
        ids = {r[0] for k in keys for r in self.db.execute('SELECT car_id FROM identities WHERE key=?', (k,))}
        if existing:
            ids.add(existing['car_id'])
        if not ids:
            car_id = self.db.execute('INSERT INTO cars DEFAULT VALUES').lastrowid
        else:
            car_id = min(ids)
            # A VIN revealed later can connect previously separate listings.
            for other in ids - {car_id}:
                seen = self.db.execute('SELECT eligible_seen FROM cars WHERE id=?', (other,)).fetchone()[0]
                self.db.execute('UPDATE cars SET eligible_seen=MAX(eligible_seen,?) WHERE id=?', (seen, car_id))
                self.db.execute('UPDATE listings SET car_id=? WHERE car_id=?', (car_id, other))
                self.db.execute('UPDATE identities SET car_id=? WHERE car_id=?', (car_id, other))
                self.db.execute('UPDATE events SET car_id=? WHERE car_id=?', (car_id, other))
                self.db.execute('DELETE FROM cars WHERE id=?', (other,))
        for key in keys:
            self.db.execute('INSERT OR IGNORE INTO identities VALUES (?,?)', (key, car_id))
        return car_id

    def ingest(self, source, listings, timestamp=None, price_alerts=False, min_drop=500):
        timestamp = timestamp or now()
        if any(x.source != source for x in listings):
            raise ValueError('Snapshot source does not match listing source')
        created = []
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO sources(name) VALUES (?)', (source,))
            baseline = not self.db.execute('SELECT baseline FROM sources WHERE name=?', (source,)).fetchone()[0]
            for x in listings:
                x.observed_at = timestamp
                old = self.db.execute('SELECT * FROM listings WHERE source=? AND source_id=?', (source, x.source_id)).fetchone()
                previous = json.loads(old['payload']) if old else {}
                car_id = self._entity(x, old)
                seen = self.db.execute('SELECT eligible_seen FROM cars WHERE id=?', (car_id,)).fetchone()[0]
                reason = reject_reason(x, self.filters)
                eligible = not reason
                old_price = previous.get('price')
                kind = None
                if eligible and not seen:
                    # Ads from the original baseline that were excluded only
                    # because their title omitted the brand remain baseline ads.
                    # Later previously missed ads may still trigger an alert.
                    original_baseline = False
                    if old and previous.get('title') == x.title and not re.search(r'\btesla\b', x.title, re.I):
                        first = self.db.execute('SELECT MIN(first_seen) FROM listings WHERE source=?', (source,)).fetchone()[0]
                        original_baseline = old['first_seen'] == first
                    if not baseline and not original_baseline:
                        kind = 'new'
                    self.db.execute('UPDATE cars SET eligible_seen=1 WHERE id=?', (car_id,))
                elif eligible and not baseline and price_alerts and old_price is not None and x.price is not None and old_price - x.price >= min_drop:
                    kind = 'price_drop'
                payload = json.dumps(x.to_dict(), ensure_ascii=False)
                self.db.execute('''INSERT INTO listings VALUES (?,?,?,?,?,?) ON CONFLICT(source,source_id)
                    DO UPDATE SET car_id=excluded.car_id,payload=excluded.payload,last_seen=excluded.last_seen''',
                    (source, x.source_id, car_id, payload, timestamp, timestamp))
                if x.price is not None and (old is None or old_price!=x.price):
                    self.db.execute('INSERT OR IGNORE INTO prices VALUES (?,?,?,?)', (source,x.source_id,timestamp,x.price))
                if kind:
                    seed = f'new:{car_id}' if kind == 'new' else f'drop:{source}:{x.source_id}:{old_price}:{x.price}'
                    event_id = hashlib.sha256((self.namespace + ':' + seed).encode()).hexdigest()
                    text = message(x, kind, old_price if kind == 'price_drop' else None)
                    result = self.db.execute('''INSERT OR IGNORE INTO events(id,car_id,kind,payload,text,created_at)
                        VALUES (?,?,?,?,?,?)''', (event_id,car_id,kind,payload,text,timestamp))
                    if result.rowcount:
                        created.append(event_id)
            self.db.execute('''UPDATE sources SET baseline=1,last_success=?,last_attempt=?,error=NULL,
                failures=0,count=? WHERE name=?''', (timestamp,timestamp,len(listings),source))
        return created

    def pending(self, clock):
        return self.db.execute("SELECT * FROM events WHERE state='queued' AND next_attempt<=? ORDER BY created_at,id", (clock,)).fetchall()

    def set_event(self, event_id, state, error='', retry_at=0):
        with self.db:
            self.db.execute('''UPDATE events SET state=?,attempts=attempts+1,last_error=?,next_attempt=?,sent_at=?
                WHERE id=?''', (state,error[:500],retry_at,now() if state=='sent' else None,event_id))

    def status(self):
        return {'sources': [dict(r) for r in self.db.execute('SELECT * FROM sources ORDER BY name')],
                'events': {r[0]:r[1] for r in self.db.execute('SELECT state,COUNT(*) FROM events GROUP BY state')},
                'listings': self.db.execute('SELECT COUNT(*) FROM listings').fetchone()[0]}

    def events(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM events ORDER BY created_at,id')]
