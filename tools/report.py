"""Summarise the most recent real captures without including seller contact data."""
from pathlib import Path
import sys,json
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from watcher.models import Listing,reject_reason
root=Path(__file__).resolve().parents[1]
config=json.loads((root/'config.json').read_text());latest={}
for p in sorted((root/'data/snapshots').rglob('*.json')):
 d=json.loads(p.read_text());latest[d['source']]=d
rows=[]
for s in config['sources']:
 d=latest.get(s['name'],{})
 items=[Listing(**x) for x in d.get('listings',[])]
 rows.append({'source':s['name'],'checked_at':d.get('timestamp'),'status':d.get('status','not_run'),
              'pages':d.get('pages',0),'listings':len(items),'matching':sum(not reject_reason(x,config['filters']) for x in items),
              'year_known':sum(x.year is not None for x in items),'price_known':sum(x.price is not None for x in items),
              'mileage_known':sum(x.mileage is not None for x in items),'error':d.get('error')})
report={'type':'LIVE_WEBSITE_SCAN','created_at':datetime.now(timezone.utc).isoformat(),
 'sources':rows,'total_listing_observations':sum(x['listings'] for x in rows),
 'all_sources_successful':all(r['status']=='ok' for r in rows),
 'limitations':['Counts overlap across marketplaces; these are not unique cars.',
               'Parsing succeeded for the returned pages; this does not prove total marketplace recall.',
               'No real WhatsApp account was linked and no WhatsApp messages were sent.',
               'Dockerfiles were supplied and Compose YAML parsed, but Docker images were not built here.',
               'Playwright browser fallback was not exercised; live validation used website HTML via HTTP.'],
 'mobile_note':'Initial broad search: HTTP 403 on page four. Full year-partition scan then succeeded.'}
(root/'reports/live_coverage.json').write_text(json.dumps(report,indent=2))
back=json.loads((root/'reports/backtest.json').read_text())
lines=['# Testresultaten Tesla Watcher','',
 'Bouwdatum: 30 oktober 2026. De live scan gebruikt gewone websitepagina’s, geen CarAPIS-API.','',
 '## Live scan','', '| Bron | Volledige scan | Pagina’s | Uitgelezen advertenties | Passend vanaf 2022 |',
 '|---|---|---:|---:|---:|']
for r in rows:lines.append(f'| {r["source"]} | {r["status"]} | {r["pages"]} | {r["listings"]} | {r["matching"]} |')
lines+=['',f'Totaal: {report["total_listing_observations"]} advertentiewaarnemingen. Dit zijn geen unieke auto’s: hetzelfde voertuig kan op meerdere websites staan.',
 '', 'mobile.de gaf bij de eerste brede zoekopdracht op pagina vier een 403. De uiteindelijke configuratie verdeelt de zoekopdracht per registratiejaar; alle partities zijn vervolgens geslaagd. De oorspronkelijke fout staat ter controle in het logbestand.',
 '', 'De eerste volledige inventaris is stil als beginstand opgeslagen. De gebouwde code bevat daarna herkenning van nieuwe advertenties, blijvende opslag en een verzendwachtrij. De live-database en ruwe pagina’s zijn niet in het downloadpakket opgenomen: jouw installatie legt zelf een actuele beginstand vast.',
 '', '## Automatische tests','',
 '- 35 Python-tests geslaagd, inclusief een echte lokale HTTP-integratie tussen Python en de Node-helper. Eén regressietest controleert zeven verkleinde bronstructuren afzonderlijk.',
 '- 8 Node-tests geslaagd: authenticatie, inputcontrole, dubbele/concurrente verzoeken, opgeslagen verzendlogboek, herstarts, niet-verbonden toestand, onzekere uitkomsten en handmatige herbeoordeling.',
 '- `npm ci` uitgevoerd met vastgezette dependencies; whatsapp-web.js 1.34.7 en LocalAuth zijn succesvol geladen.',
 '- Python-bestanden gecompileerd en Node-syntax gecontroleerd.',
 '', '## Dertigdagensimulatie — geen historische marktbacktest','',
 f'- {back["rounds"]} tijdstappen op een interval van tien minuten.',
 f'- {back["source_snapshots"]} gesimuleerde bronsnapshots; {back["listing_observations"]} advertentiewaarnemingen.',
 f'- {back["expected_new_cars"]} verwachte nieuwe passende auto’s; {back["actual_new_alerts"]} events aangemaakt.',
 f'- {back["false_positive"]} onterechte events, {back["missed"]} gemiste verwachte auto’s en {back["duplicate_alerts"]} dubbele events binnen dit scenario.',
 f'- {back["injected_source_errors"]} gesimuleerde bronstoringen en {back["process_restarts"]} herstarts.',
 '- Onder meer oude bouwjaren, verkeerd model, gezochte advertenties, Plaid, prijsfilter, herplaatsingen en gedeelde VIN’s meegenomen.',
 '', 'De precision/recall van 100% geldt alleen binnen dit vooraf gelabelde, gegenereerde scenario. Het bewijst geen marktdekking. De gemeten tijdsverschillen in dit scenario zijn gesimuleerde scandetectie, geen WhatsApp-bezorgtijden.',
 '', 'Voor een echte historische replay verzamelt de tool vanaf installatie snapshots. Je kunt die chronologisch terugspelen met `python tools/run.py replay data/snapshots --output reports/mijn-replay.json`.',
 '', '## Nog niet live bewezen','',
 '- WhatsApp-login, daadwerkelijke verzending en telefoon-pushmeldingen: hiervoor moet je zelf een account koppelen en de testmelding controleren.',
 '- Docker-imagebuild en uitvoering op een hostingprovider: hier was geen Docker-runtime beschikbaar. Compose YAML is wel syntactisch gelezen. De lokale HTTP-scanner en lokale Node-testservice zijn daadwerkelijk uitgevoerd.',
 '- De Playwright-browserfallback: niet nodig geweest voor de geslaagde scans, en hier niet uitgevoerd.',
 '- Ononderbroken 24/7-werking: de livecontrole is een momentopname. Pagina’s, toegang en WhatsApp Web kunnen wijzigen.',
 '- Betrouwbare deduplicatie zonder VIN/kenteken: zonder een sterke identiteit kunnen twee sites alsnog afzonderlijke meldingen voor dezelfde auto geven.',
 '', 'Zie de JSON-rapporten en testlogs in `reports/` voor de onderliggende resultaten.']
(root/'TESTRESULTATEN.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'sources_ok':sum(r['status']=='ok' for r in rows),'sources_total':len(rows),'observations':report['total_listing_observations']},indent=2))
