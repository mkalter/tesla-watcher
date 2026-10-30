import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from watcher.media import check_image_url,jpeg_photo
from watcher.models import message
from watcher.native_whatsapp import NativeWhatsApp,deliver_native
from watcher.parsing import from_record
from watcher.store import Store
from test_watcher import car,FILTERS,T0,T1

class PhotoMessageTests(unittest.TestCase):
    def test_consistent_price_and_metadata_caption(self):
        text=message(car(price=49950,mileage=48000,country='DE',source='mobile',location='München'),kind='example')
        self.assertTrue(text.startswith('*Tesla Model S Long Range*\n*€ 49.950*\n\n'))
        for part in ['Jaar: 2023','Kilometerstand: 48.000 km','Locatie: München · Duitsland','Bron: mobile.de','Bekijk advertentie:','_Voorbeeldbericht']:
            self.assertIn(part,text)
        self.assertNotIn('build_year',text);self.assertNotIn('Gezien:',text)
        self.assertLessEqual(len(text),1024)
    def test_foreign_currency_not_mislabelled_euros(self):
        self.assertIn('*USD 52.000*',message(car(currency='USD')))
    def test_image_extraction_supports_real_source_fields(self):
        source={'name':'marktplaats','url':'https://www.marktplaats.nl/','link_pattern':r'^https://www.marktplaats.nl/v/'}
        item=from_record({'url':'/v/car','title':'Tesla Model S','year':2023,'imageUrls':['//images.marktplaats.com/car.jpg']},source,T0)
        self.assertEqual(item.image_url,'https://images.marktplaats.com/car.jpg')
    def test_disallow_private_and_unrelated_image_urls(self):
        for url in ['http://img.classistatic.de/a.jpg','https://127.0.0.1/secret','https://img.classistatic.de.evil.test/a.jpg','https://user:password@img.classistatic.de/a.jpg']:
            with self.subTest(url=url),self.assertRaises(ValueError):check_image_url(url)
    def test_prepared_image_is_bounded_jpeg(self):
        from PIL import Image
        source=io.BytesIO();Image.new('RGB',(2000,1500),'red').save(source,format='PNG')
        photo=jpeg_photo(source.getvalue())
        with Image.open(io.BytesIO(photo)) as result:
            self.assertEqual(result.format,'JPEG');self.assertLessEqual(result.width,1600);self.assertLessEqual(result.height,1200)
    def test_native_image_caption_uses_fixed_recipient(self):
        with tempfile.TemporaryDirectory() as directory:
            driver=NativeWhatsApp(directory,'31612345678');driver._ready=True;calls=[]
            driver._client=SimpleNamespace(send_image=lambda *a,**kw:(calls.append((a,kw)) or SimpleNamespace(ID='photo-id')))
            self.assertEqual(driver.send_photo('caption',b'jpeg'),'photo-id')
            self.assertEqual(calls,[(('31612345678',b'jpeg'),{'caption':'caption'})])
    def test_download_failure_is_safe_retry_before_send(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(str(Path(directory)/'store.sqlite'),FILTERS)
            try:
                store.ingest('test',[],T0);store.ingest('test',[car(image_url='https://img.classistatic.de/car.jpg')],T1)
                driver=SimpleNamespace(ready=lambda:True,send_photo=lambda *a:self.fail('Must not send'))
                with patch('watcher.media.fetch_photo',side_effect=TimeoutError):self.assertEqual(deliver_native(store,driver,clock=100,pause=0),0)
                event=store.events()[0];self.assertEqual(event['state'],'queued');self.assertEqual(event['next_attempt'],400)
            finally:store.close()
    def test_photo_delivery_once_with_caption(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(str(Path(directory)/'store.sqlite'),FILTERS);calls=[]
            try:
                store.ingest('test',[],T0);store.ingest('test',[car(image_url='https://img.classistatic.de/car.jpg')],T1)
                driver=SimpleNamespace(ready=lambda:True,send_photo=lambda text,data:calls.append((text,data)))
                with patch('watcher.media.fetch_photo',return_value=b'jpeg'):
                    self.assertEqual(deliver_native(store,driver,pause=0),1)
                    self.assertEqual(deliver_native(store,driver,pause=0),0)
                self.assertEqual(calls[0][1],b'jpeg');self.assertIn('*Tesla Model S',calls[0][0])
            finally:store.close()

class CarapisPriceTests(unittest.TestCase):
    def test_price_with_nonbreaking_thousands_separator(self):
        from watcher.parsing import parse_page
        source={'name':'carapis','kind':'carapis','url':'https://carapis.com/catalog/','link_pattern':r'^https://carapis.com/catalog/tesla/model-s/'}
        html='<a class="vehicle-card" href="/catalog/tesla/model-s/car"><h3 class="vehicle-card-title">Tesla Model S</h3><p class="vehicle-card-subtitle">Long Range · 2023</p><ul class="vehicle-card-specs">88.099 km Electric</ul><span class="vehicle-card-price">€12\u00a0000</span><span class="vehicle-card-verdict">61% below market</span></a>'
        items,_,_=parse_page(html,source,T0)
        self.assertEqual(items[0].price,12000)
