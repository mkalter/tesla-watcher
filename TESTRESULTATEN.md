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

## Lichte Python-installatie

Aanvulling van 30 oktober 2026. `python main.py` gebruikt Neonize 0.5.2, zonder Chrome, Node of Docker. De bestaande Docker-variant blijft als alternatief aanwezig.

- 56 Python-tests geslaagd, waaronder SDK-initialisatie zonder netwerk, QR-generatie, verzending via een testclient, vaste ontvanger, wachtrij, herstarts, onzekere uitkomsten, authenticatie, Origin-controle, pauzeren en verzending tijdens een langlopende scan.
- De 8 tests voor de oude Node-helper blijven slagen.
- De synthetische 30-daagsimulatie opnieuw geslaagd: 40 verwachte meldingen, nul gemist en nul dubbel. Dit test geen echte WhatsApp-aflevering.
- `python main.py --check` laadt de geïnstalleerde WhatsApp-dependency en alle negen bronconfiguraties.
- `tools/benchmark_light.py` meet de ongekoppelde SDK plus achtereenvolgens opgeslagen HTML-pagina’s. Zie `reports/light-resources.json`. De gemeten piek is geen garantie voor een gekoppelde WhatsApp-sessie of een host met weinig RAM.
- Geen WhatsApp-account gekoppeld tijdens deze tests. Geen echte telefoonmelding getest. Dit moet na koppelen met de testknop worden gecontroleerd.

Ruwe websitecaptures, WhatsApp-sessies en lokale databases zijn niet meegeüpload. De resourceproef gebruikt lokale captures als die aanwezig zijn, anders de verkleinde fixtures; uitkomsten verschillen daardoor per omgeving.

### KataBump-installatie

De lichte versie is op KataBump met Python 3.12 geïnstalleerd en gestart. In de serverconsole zijn CarAPIS-pagina’s succesvol uitgelezen en is QR-generatie door de echte ongekoppelde WhatsApp-client gemeld. Geobserveerd geheugengebruik circa 78 MiB zonder HTTPS-tunnel en circa 109 MiB tijdens starten met tunnel; dit zijn momentopnames, geen piek- of duurmeting en geen gekoppelde sessie.

De directe IP-verbinding gaf bij de gebruiker `ERR_CONNECTION_REFUSED`. Er is daarom een optionele Cloudflare Quick Tunnel voor HTTPS toegevoegd, met uitsluitend lokale HTTP-binding. De tunnel genereerde een publieke HTTPS-link. De externe healthcheck in onze cloudbrowser kreeg echter `Your request was blocked`; externe bereikbaarheid en de interactieve web-login zijn daardoor nog niet bevestigd. De WhatsApp-QR is niet gescand en er is geen echt bericht verstuurd.

## Overstap naar ntfy met foto's

Standaardtransport is ntfy; WhatsApp wordt niet gestart. 82 Python-tests slagen, inclusief echte foto-extractievelden, veilige CDN-validatie, JPEG-verkleining, vaste berichtopbouw, ntfy-upload, wachtrij, rate limits en onzekere uitkomsten. De echte ntfy.sh-service heeft een testbericht met advertentiefoto geaccepteerd; zie `reports/ntfy-live-validation.json`. Dit bevestigt geen push op een telefoon die nog niet is geabonneerd.

Een ntfy-topic wordt privé gemaakt en niet op GitHub gezet. Foto's worden als verkleinde JPEG geüpload zodat de ontvanger niet afhankelijk is van een extern afbeeldingsformaat of een afbeeldingslink zonder extensie.

De mobiele.de-zoekopdracht is lokaal verbeterd en volledig uitgelezen (73 passende auto's, vier pagina's). Op de KataBump-host gaf die bron nog HTTP 403. Een afzonderlijk actueel voorbeeld kan buiten de host zijn opgehaald; dat is expliciet als eenmalig voorbeeld gemarkeerd en verandert de bronstatus of beginstand niet.
