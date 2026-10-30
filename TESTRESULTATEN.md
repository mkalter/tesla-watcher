# Testresultaten Tesla Watcher

Bouwdatum: 30 oktober 2026. De live scan gebruikt gewone websitepagina’s, geen CarAPIS-API.

## Live scan

| Bron | Volledige scan | Pagina’s | Uitgelezen advertenties | Passend vanaf 2022 |
|---|---|---:|---:|---:|
| carapis | ok | 11 | 263 | 263 |
| autoscout_nl | ok | 1 | 7 | 7 |
| autoscout_be | ok | 1 | 11 | 10 |
| autoscout_de | ok | 3 | 55 | 55 |
| marktplaats | ok | 4 | 118 | 6 |
| gaspedaal | ok | 1 | 95 | 7 |
| mobile | ok | 8 | 80 | 74 |
| 2dehands | ok | 2 | 39 | 10 |
| kleinanzeigen | ok | 4 | 73 | 4 |

Totaal: 741 advertentiewaarnemingen. Dit zijn geen unieke auto’s: hetzelfde voertuig kan op meerdere websites staan.

mobile.de gaf bij de eerste brede zoekopdracht op pagina vier een 403. De uiteindelijke configuratie verdeelt de zoekopdracht per registratiejaar; alle partities zijn vervolgens geslaagd. De oorspronkelijke fout staat ter controle in het logbestand.

De eerste volledige inventaris is stil als beginstand opgeslagen. De gebouwde code bevat daarna herkenning van nieuwe advertenties, blijvende opslag en een verzendwachtrij. De live-database en ruwe pagina’s zijn niet in het downloadpakket opgenomen: jouw installatie legt zelf een actuele beginstand vast.

## Automatische tests

- 35 Python-tests geslaagd, inclusief een echte lokale HTTP-integratie tussen Python en de Node-helper. Eén regressietest controleert zeven verkleinde bronstructuren afzonderlijk.
- 8 Node-tests geslaagd: authenticatie, inputcontrole, dubbele/concurrente verzoeken, opgeslagen verzendlogboek, herstarts, niet-verbonden toestand, onzekere uitkomsten en handmatige herbeoordeling.
- `npm ci` uitgevoerd met vastgezette dependencies; whatsapp-web.js 1.34.7 en LocalAuth zijn succesvol geladen.
- Python-bestanden gecompileerd en Node-syntax gecontroleerd.

## Dertigdagensimulatie — geen historische marktbacktest

- 4321 tijdstappen op een interval van tien minuten.
- 8642 gesimuleerde bronsnapshots; 78908 advertentiewaarnemingen.
- 40 verwachte nieuwe passende auto’s; 40 events aangemaakt.
- 0 onterechte events, 0 gemiste verwachte auto’s en 0 dubbele events binnen dit scenario.
- 30 gesimuleerde bronstoringen en 8 herstarts.
- Onder meer oude bouwjaren, verkeerd model, gezochte advertenties, Plaid, prijsfilter, herplaatsingen en gedeelde VIN’s meegenomen.

De precision/recall van 100% geldt alleen binnen dit vooraf gelabelde, gegenereerde scenario. Het bewijst geen marktdekking. De gemeten tijdsverschillen in dit scenario zijn gesimuleerde scandetectie, geen WhatsApp-bezorgtijden.

Voor een echte historische replay verzamelt de tool vanaf installatie snapshots. Je kunt die chronologisch terugspelen met `python tools/run.py replay data/snapshots --output reports/mijn-replay.json`.

## Nog niet live bewezen

- WhatsApp-login, daadwerkelijke verzending en telefoon-pushmeldingen: hiervoor moet je zelf een account koppelen en de testmelding controleren.
- Docker-imagebuild en uitvoering op een hostingprovider: hier was geen Docker-runtime beschikbaar. Compose YAML is wel syntactisch gelezen. De lokale HTTP-scanner en lokale Node-testservice zijn daadwerkelijk uitgevoerd.
- De Playwright-browserfallback: niet nodig geweest voor de geslaagde scans, en hier niet uitgevoerd.
- Ononderbroken 24/7-werking: de livecontrole is een momentopname. Pagina’s, toegang en WhatsApp Web kunnen wijzigen.
- Betrouwbare deduplicatie zonder VIN/kenteken: zonder een sterke identiteit kunnen twee sites alsnog afzonderlijke meldingen voor dezelfde auto geven.

Zie de JSON-rapporten en testlogs in `reports/` voor de onderliggende resultaten.
