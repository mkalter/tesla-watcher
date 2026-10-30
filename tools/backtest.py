"""Deterministic 30-day synthetic replay. This is NOT historical market evidence."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from watcher.models import Listing
from watcher.store import Store
from datetime import datetime,timedelta,timezone
import tempfile,random,json,time


def run(output='reports/backtest.json'):
 rng=random.Random(421022);start=datetime(2026,9,1,tzinfo=timezone.utc)
 records=[];expected=set()
 for i in range(78):
  kind='baseline' if i<8 else 'eligible' if i<48 else 'old' if i<58 else 'wanted' if i<63 else 'wrong_model' if i<68 else 'plaid' if i<73 else 'over_budget'
  published=start-timedelta(days=1) if kind=='baseline' else start+timedelta(seconds=rng.randrange(1,29*86400))
  vin='5YJSA1E26PF'+f'{i:06d}'
  if kind=='eligible':expected.add(vin)
  records.append({'i':i,'kind':kind,'published':published,'vin':vin})
 filters={'min_year':2022,'max_price':55000,'exclude_plaid':True}
 failures=0;restarts=0;snapshots=0;observations=0
 began=time.perf_counter()
 with tempfile.TemporaryDirectory() as directory:
  db=str(Path(directory)/'backtest.sqlite');store=Store(db,filters)
  for tick in range(30*144+1):
   timestamp=start+timedelta(minutes=10*tick)
   for source in ['market_a','market_b']:
    snapshots+=1
    outage=(source=='market_a' and 500<=tick<520) or (source=='market_b' and 1000<=tick<1010)
    if outage:
     failures+=1;store.fail(source,'synthetic source outage',timestamp.isoformat());continue
    items=[]
    for r in records:
     visible=r['kind']=='baseline' or r['published']<=timestamp<r['published']+timedelta(hours=12)
     # Previously seen cars reappear after a simulated relisting, with a new ID.
     relisted=r['kind']=='baseline' and 4000<=tick<4010
     if not visible and not relisted:continue
     title='Tesla Model 3' if r['kind']=='wrong_model' else 'Tesla Model S Plaid' if r['kind']=='plaid' else 'Tesla Model S Long Range'
     ad_id=f'{source}-{r["i"]}'+('-relist' if relisted else '')
     items.append(Listing(source=source,source_id=ad_id,url=f'https://example.invalid/{ad_id}',title=title,
       year=2018 if r['kind']=='old' else 2023,year_basis='build_year',price=65000 if r['kind']=='over_budget' else 52000,
       mileage=40000+r['i']*111,country='NL',vin=r['vin'],is_wanted=r['kind']=='wanted',published_at=r['published'].isoformat()))
    rng.shuffle(items);observations+=len(items)
    store.ingest(source,items,timestamp.isoformat())
   if tick and tick%500==0:
    store.close();store=Store(db,filters);restarts+=1
  events=store.events();actual=[json.loads(e['payload'])['vin'] for e in events]
  true_positive=len(expected & set(actual));false_positive=len(set(actual)-expected)
  missed=sorted(expected-set(actual));duplicates=len(actual)-len(set(actual))
  latency=[]
  for event in events:
   item=json.loads(event['payload'])
   latency.append((datetime.fromisoformat(item['observed_at'])-datetime.fromisoformat(item['published_at'])).total_seconds())
  report={'test_type':'SYNTHETIC_30_DAY_REPLAY','seed':421022,'historical_market_backtest':False,
    'duration_days':30,'scan_interval_seconds':600,'rounds':4321,'source_snapshots':snapshots,
    'listing_observations':observations,'injected_source_errors':failures,'process_restarts':restarts,
    'expected_new_cars':len(expected),'actual_new_alerts':len(actual),'true_positive':true_positive,
    'false_positive':false_positive,'missed':len(missed),'duplicate_alerts':duplicates,
    'precision':true_positive/(true_positive+false_positive) if actual else None,
    'recall':true_positive/len(expected),
    'latency_seconds':{'min':min(latency),'max':max(latency),'mean':round(sum(latency)/len(latency),1)},
    'runtime_seconds':round(time.perf_counter()-began,3),
    'limitations':['Generated scenarios, not archived car advertisements.','Latency is simulated scan latency, not measured WhatsApp delivery time.',
                  'This does not establish recall on real sites or guarantee WhatsApp account availability.'],
    'passed':false_positive==0 and not missed and duplicates==0}
  store.close()
 Path(output).parent.mkdir(parents=True,exist_ok=True)
 Path(output).write_text(json.dumps(report,indent=2))
 print(json.dumps(report,indent=2))
 return report
if __name__=='__main__':sys.exit(0 if run()['passed'] else 1)
