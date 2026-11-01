import unittest
import tempfile
from pathlib import Path
import json
import os
import urllib.error
from unittest.mock import patch
from watcher.models import Listing,reject_reason
from watcher.store import Store
from watcher.parsing import parse_page,amount,canonical_url,ParseError
from watcher.cli import replay,process_lock
from watcher.notify import deliver
from watcher.sources import scan_source

FILTERS={'min_year':2022,'allow_first_registration':True}
T0='2026-10-01T00:00:00+00:00'
T1='2026-10-01T00:10:00+00:00'
T2='2026-10-01T00:20:00+00:00'
def car(id='a',source='test',**kwargs):
 values=dict(source=source,source_id=id,url='https://example.test/car/'+id,title='Tesla Model S Long Range',year=2023,year_basis='build_year',price=52000,mileage=60000,country='NL')
 values.update(kwargs);return Listing(**values)

class StoreTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=str(Path(self.temp.name)/'test.db');self.store=Store(self.path,FILTERS)
 def tearDown(self):self.store.close();self.temp.cleanup()
 def test_baseline_is_quiet(self):
  self.assertEqual(self.store.ingest('test',[car()],T0),[])
 def test_new_once_after_repeat_restart(self):
  self.store.ingest('test',[car()],T0);self.assertEqual(len(self.store.ingest('test',[car(),car('b')],T1)),1)
  self.store.close();self.store=Store(self.path,FILTERS)
  self.assertEqual(self.store.ingest('test',[car('b'),car()],T2),[])
 def test_failed_first_scan_not_baseline(self):
  self.store.fail('test','blocked',T0);self.assertEqual(self.store.ingest('test',[car()],T1),[])
  self.assertEqual(len(self.store.ingest('test',[car('b')],T2)),1)
 def test_reappearance_not_new(self):
  self.store.ingest('test',[car()],T0);self.store.ingest('test',[],T1);self.assertEqual(self.store.ingest('test',[car()],T2),[])
 def test_updated_unknown_year_can_become_eligible(self):
  self.store.ingest('test',[car(year=None)],T0);self.assertEqual(len(self.store.ingest('test',[car()],T1)),1)
 def test_strong_vin_duplicate(self):
  vin='5YJSA1E26PF123456'
  self.store.ingest('test',[],T0);self.store.ingest('other',[],T0)
  self.assertEqual(len(self.store.ingest('test',[car(vin=vin)],T1)),1)
  self.assertEqual(self.store.ingest('other',[car('z','other',vin=vin)],T2),[])
 def test_plate_country_duplicate(self):
  self.store.ingest('test',[],T0);self.store.ingest('other',[],T0)
  self.store.ingest('test',[car(plate='G-123-AB')],T1)
  self.assertEqual(self.store.ingest('other',[car('z','other',plate='G123AB')],T2),[])
 def test_similar_cars_not_silently_merged(self):
  self.store.ingest('test',[],T0);self.assertEqual(len(self.store.ingest('test',[car(),car('b')],T1)),2)
 def test_price_change_optional(self):
  self.store.ingest('test',[car()],T0)
  self.assertEqual(self.store.ingest('test',[car(price=51000)],T1),[])
  self.assertEqual(len(self.store.ingest('test',[car(price=49000)],T2,True)),1)
 def test_scope_change_requires_new_database(self):
  with self.assertRaises(ValueError):Store(self.path,{'min_year':2024})
 def test_ingest_is_transactional(self):
  with self.assertRaises(ValueError):self.store.ingest('test',[car(source='wrong')],T0)
  self.assertEqual(self.store.status()['listings'],0)
 def test_old_year_rejected(self):self.assertEqual(reject_reason(car(year=2020),FILTERS),'too_old')
 def test_wrong_model_rejected(self):self.assertEqual(reject_reason(car(title='Tesla Model 3'),FILTERS),'not_model_s')
 def test_marketplace_model_s_without_brand_in_title(self):
  x=car(source='2dehands',url='https://www.2dehands.be/v/auto-s/tesla/m2456538912-model-s',title='Model S Long Range HW4.0')
  self.assertEqual(reject_reason(x,FILTERS),'')
  self.assertEqual(reject_reason(car(source='2dehands',url='https://example.test/v/auto-s/tesla/1',title='Model S'),FILTERS),'not_model_s')
  self.assertEqual(reject_reason(car(source='2dehands',url=x.url,title='Model 3'),FILTERS),'not_model_s')
 def test_legacy_baseline_brandless_ad_remains_quiet(self):
  x=car(source='2dehands',url='https://www.2dehands.be/v/auto-s/tesla/m1-model-s',title='Model S Long Range')
  with patch('watcher.store.reject_reason',return_value='not_model_s'):
   self.store.ingest('2dehands',[x],T0)
  self.assertEqual(self.store.ingest('2dehands',[x],T1),[])
  self.assertEqual(len(self.store.ingest('2dehands',[x,car('b','2dehands',url='https://www.2dehands.be/v/auto-s/tesla/m2-model-s',title='Model S Plaid')],T2)),1)
 def test_legacy_new_brandless_ad_is_recovered(self):
  x=car(source='2dehands',url='https://www.2dehands.be/v/auto-s/tesla/m1-model-s',title='Model S Long Range')
  self.store.ingest('2dehands',[car('baseline','2dehands')],T0)
  with patch('watcher.store.reject_reason',return_value='not_model_s'):
   self.store.ingest('2dehands',[x],T1)
  self.assertEqual(len(self.store.ingest('2dehands',[x],T2)),1)
 def test_wanted_rejected(self):self.assertEqual(reject_reason(car(is_wanted=True),FILTERS),'wanted_ad')
 def test_foreign_currency_with_eur_cap_rejected(self):
  self.assertEqual(reject_reason(car(currency='USD'),{**FILTERS,'max_price':55000}),'non_eur_price')
 def test_foreign_currency_without_cap_allowed(self):self.assertEqual(reject_reason(car(currency='USD'),FILTERS),'')
 def test_strict_build_year(self):self.assertEqual(reject_reason(car(year_basis='first_registration'),{'min_year':2022,'allow_first_registration':False}),'build_year_unconfirmed')
 def test_outbox_retry_not_ready(self):
  self.store.ingest('test',[],T0);self.store.ingest('test',[car()],T1)
  def fail(*a,**k):raise urllib.error.HTTPError('http://bridge',503,'not ready',{},None)
  with patch.dict(os.environ,{'BRIDGE_TOKEN':'x'*30}):deliver(self.store,{'bridge_url':'http://bridge'},fail,100)
  event=self.store.events()[0];self.assertEqual(event['state'],'queued');self.assertEqual(event['next_attempt'],130)
 def test_outbox_timeout_is_uncertain(self):
  self.store.ingest('test',[],T0);self.store.ingest('test',[car()],T1)
  def fail(*a,**k):raise TimeoutError('unknown send outcome')
  with patch.dict(os.environ,{'BRIDGE_TOKEN':'x'*30}):deliver(self.store,{'bridge_url':'http://bridge'},fail,100)
  self.assertEqual(self.store.events()[0]['state'],'uncertain')
 def test_process_lock(self):
  with process_lock(self.path):
   with self.assertRaises(RuntimeError):
    with process_lock(self.path):pass

class ParserTests(unittest.TestCase):
 def setUp(self):
  self.source={'name':'test','url':'https://example.test/search','country':'NL','link_pattern':r'^https://example\.test/car/'}
 def test_prices(self):
  for value,expected in [('54.950',54950),('54,950',54950),('54.950,00',54950),('54950.00',54950),('54 950',54950),('Bieden',None)]:
   with self.subTest(value=value):self.assertEqual(amount(value),expected)
 def test_mobile_url_identity(self):
  self.assertEqual(canonical_url('https://suchen.mobile.de/fahrzeuge/details.html?id=123&ref=srp&fr=2022&ms=135'), 'https://suchen.mobile.de/fahrzeuge/details.html?id=123')
 def test_jsonld(self):
  html='<script type="application/ld+json">'+json.dumps({'@type':'Car','name':'Tesla Model S','url':'/car/1','vehicleModelDate':2023,'offers':{'price':54950,'priceCurrency':'EUR'}})+'</script>'
  xs,_,_=parse_page(html,self.source,T0);self.assertEqual(xs[0].year,2023);self.assertEqual(xs[0].price,54950)
 def test_unknown_layout_fail_closed(self):
  with self.assertRaises(ParseError):parse_page('<html>No ads extracted</html>',self.source,T0)
 def test_captcha_not_empty(self):
  with self.assertRaises(ParseError):parse_page('<title>Just a moment</title>',self.source,T0)
 def test_battery_year_is_not_build_year(self):
  html='<article><a href="/car/1"><h3>Tesla Model S new battery 2024</h3></a><p>€ 24.000</p></article>'
  xs,_,_=parse_page(html,self.source,T0);self.assertIsNone(xs[0].year)
 def test_german_price_is_not_mileage(self):
  s={**self.source,'country':'DE','year_pattern':r'EZ\s+\d{2}/(20\d{2})','year_basis':'first_registration'}
  h='<article><a href="/car/1"><h3>Tesla Model S</h3></a><p>29.990 €</p><p>266.000 km EZ 04/2020</p></article>'
  x=parse_page(h,s,T0)[0][0];self.assertEqual(x.price,29990);self.assertEqual(x.mileage,266000);self.assertEqual(x.year,2020)
 def test_explicit_zero_is_valid(self):
  s={**self.source,'empty_patterns':['0 resultaten']};self.assertEqual(parse_page('0 resultaten',s,T0),([],None,True))
 def test_carapis_pagination_preserves_filters(self):
  s={'name':'carapis','kind':'carapis','url':'https://carapis.com/catalog/?brand=tesla&model=model-s&minYear=2022','link_pattern':r'^https://carapis.com/catalog/tesla/model-s/'}
  h='<a class="vehicle-card" href="/catalog/tesla/model-s/abc/"><h3 class="vehicle-card-title">Tesla Model S</h3><p class="vehicle-card-subtitle">Long Range · 2023</p><ul class="vehicle-card-specs">12,000 km</ul><p>$55,000</p></a><a href="/?page=2"></a>'
  xs,url,_=parse_page(h,s,T0);self.assertIn('minYear=2022',url);self.assertIn('page=2',url);self.assertEqual(xs[0].currency,'USD')
 def test_page_limit_is_failure(self):
  class F:
   def page(self,*args):return ([car()], 'https://example.test/search?page=2',False),'html'
  with self.assertRaises(ParseError):scan_source(F(),{**self.source,'max_pages':1,'request_delay':0},T0)
 def test_repeated_page_is_failure(self):
  class F:
   calls=0
   def page(self,*args):
    self.calls+=1;return ([car()],f'https://example.test/search?page={self.calls+1}',False),'html'
  with self.assertRaises(ParseError):scan_source(F(),{**self.source,'max_pages':5,'request_delay':0},T0)
 def test_offsite_pagination_is_failure(self):
  class F:
   def page(self,*args):return ([car()], 'https://other.test/page2',False),'html'
  with self.assertRaises(ParseError):scan_source(F(),{**self.source,'request_delay':0},T0)
 def test_replay_out_of_order_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'input.json';p.write_text(json.dumps([{'timestamp':T1,'source':'test','listings':[]},{'timestamp':T0,'source':'test','listings':[]}]))
   with self.assertRaises(ValueError):replay([str(p)],FILTERS,str(Path(t)/'out.json'))

if __name__=='__main__':unittest.main()
