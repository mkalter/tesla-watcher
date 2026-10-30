# Tesla Watcher

Python-tool voor nieuwe **Tesla Model S-advertenties vanaf 2022**, met gratis meldingen via je gekoppelde **WhatsApp Web**. CarAPIS wordt als gewone website gescrapet. Geen CarAPIS-account, betaalde voertuig-API of WhatsApp Business-account nodig.

De scanner, database, HTML-parsers, WhatsApp-helper, installatiebestanden, regressietests, replay-tool en testrapporten zitten in dit pakket. Je koppelt zelf WhatsApp met een QR-code. Er is nog geen hosting aangemaakt en er zijn geen echte WhatsApp-berichten verstuurd tijdens het bouwen.

## Wat is er getest?

Zie **[TESTRESULTATEN.md](TESTRESULTATEN.md)** voor de concrete live scan en beperkingen. De volledige inventaris is uitgelezen voor negen koppelingen: CarAPIS, AutoScout24 NL/BE/DE, Marktplaats, Gaspedaal, mobile.de, 2dehands en Kleinanzeigen. Dit is een momentopname, geen garantie dat hun pagina's blijven werken.

De tests bevatten echte, verkleinde paginastructuren en een Python → HTTP → Node-integratietest met een nep-WhatsApp-driver. De dertigdagensimulatie test nieuwe advertenties, dubbele VIN's, herplaatsingen, 30 bronstoringen en acht herstarts. **Dat is geen historische marktbacktest.** Er was vooraf geen historisch advertentiearchief beschikbaar.

## Snel starten met Docker

Benodigd: Docker met Compose, plus Python 3.12 of nieuwer voor de setup. Op Windows kan dit met Docker Desktop. Op een Linux-server werken dezelfde Docker-commando's. Reken voor gelijktijdige browsers op minimaal 2 GB RAM; 4 GB geeft meer ruimte.

1. Pak het zipbestand uit en open een terminal in de map `tesla-watcher`.
2. Genereer de instellingen:

   ```bash
   python tools/setup.py
   ```

   Vul **je ontvangende nummer** in met landcode, bijvoorbeeld `31612345678`. Dit maakt `.env` en `config.docker.json`. Bewaar `.env` privé: daarin staat het wachtwoord voor de koppeling.

3. Pas de zoekfilters in `config.docker.json` aan, vóór de eerste scan. Standaard: alle uitvoeringen vanaf 2022, zonder prijs- of kilometerlimiet. De CarAPIS-website bevat ook andere landen dan NL/BE/DE; standaard is daarvoor geen extra landenfilter ingesteld.
4. Start alleen de WhatsApp-service:

   ```bash
   docker compose up -d --build whatsapp
   ```

5. Open **http://localhost:3000**. Gebruikersnaam: `admin`. Wachtwoord: de waarde van `BRIDGE_TOKEN` in `.env`. Scan de QR met WhatsApp → Instellingen → Gekoppelde apparaten → Apparaat koppelen.
6. Klik op **Stuur een testmelding**. Controleer in WhatsApp én op je telefoon of die aankomt. Bij dezelfde afzender en ontvanger kan de chat wel bijwerken zonder pushmelding. Gebruik dan een tweede WhatsApp-account als gekoppelde afzender, met je eigen nummer als `WHATSAPP_TO`.
7. Start de scanner met verzenden nog uit:

   ```bash
   docker compose up -d --build scanner
   docker compose logs -f scanner
   ```

   Wacht tot iedere gewenste bron een regel met `"status": "ok"` toont. De eerste volledige scan legt de bestaande voorraad vast en verstuurt geen advertenties.
8. Zet daarna in `config.docker.json` onder `notifications` de instelling `"enabled": true`, en herstart:

   ```bash
   docker compose restart scanner
   ```

De scanner start iedere 600 seconden een ronde, met maximaal drie onafhankelijke bronnen tegelijk. De WhatsApp-service blijft verbonden. Een langlopende scan kan het interval overschrijden; er worden geen overlappende rondes gestart. Niet iedere tien minuten een WhatsApp-bericht: alleen bij een nieuw passend aanbod.

## Op een externe server koppelen

De QR-pagina is uitsluitend op localhost gepubliceerd. Maak vanaf je eigen computer een tunnel:

```bash
ssh -L 3000:127.0.0.1:3000 jouwgebruiker@jouwserver
```

Open daarna lokaal http://localhost:3000. Zet de QR-pagina niet onbeveiligd op internet. Sessies en database staan op blijvende Docker-volumes. `docker compose down` bewaart deze; `docker compose down -v` wist ze.

Hosting en eventueel een extra telefoonnummer kosten afzonderlijk geld. Software en WhatsApp-berichten hebben bij deze opzet geen abonnement of vergoeding per bericht. Een eigen computer die aan blijft kan ook als host dienen.

## Lokaal zonder Docker

Benodigd: **Python 3.12+ en Node.js 20+**. De HTTP-scanner gebruikt alleen de Python-standaardbibliotheek.

```bash
python tools/setup.py
npm --prefix bridge ci
python tools/run.py bridge
```

Laat die terminal open, koppel op http://localhost:3000 en stuur de testmelding. Het npm-commando downloadt de browser die Puppeteer gebruikt. Voor een reeds geïnstalleerde Chromium kun je `CHROMIUM_PATH` toevoegen aan `.env`.

In een tweede terminal:

```bash
python tools/run.py scan --mode http --no-send
python tools/run.py status
```

Na de eerste geslaagde scans zet je **in `config.json`** `notifications.enabled` op `true` en start je:

```bash
python tools/run.py run --mode auto
```

Voor de extra browserfallback van de **autowebsites**:

```bash
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
```

Op Linux kunnen daarvoor extra systeembibliotheken nodig zijn: `python -m playwright install --with-deps chromium`. Deze browser is gescheiden van de WhatsApp-browser. De Dockerfile installeert dit al. Browserfallback gebruikt een normale browser, zonder CAPTCHA-oplossers of stealthplugins.

De twee systemd-servicevoorbeelden in `deploy/` zijn voor een Linux-installatie op `/opt/tesla-watcher`. Maak eerst de gebruiker, Python-omgeving en schrijfbare datamap aan en installeer de dependencies. Pas de paden aan jouw server aan; deze units zijn voorbeelden en zijn niet op een server geactiveerd.

## Filters

| Instelling | Voorbeeld | Betekenis |
|---|---|---|
| `min_year` | `2022` | Ondergrens op het opgegeven jaar |
| `allow_first_registration` | `true` | Ook eerste toelating als jaarbasis toestaan |
| `max_price` | `55000` of `null` | Maximaal bedrag in EUR; `null` is onbeperkt |
| `max_mileage` | `100000` of `null` | Maximale kilometerstand |
| `countries` | `["NL","BE","DE","SE"]` of `[]` | Leeg betekent geen extra landenfilter |
| `variant` | `"any"` of `"long_range"` | Long Range moet dan expliciet in de titel staan |
| `exclude_plaid` | `true` | Plaid uitsluiten |
| `include_damaged` | `false` | Herkende schadeadvertenties uitsluiten |

Bij een verandering van de **filters** kies je een nieuwe `database`-bestandsnaam. De software weigert anders de gewijzigde filters om onbedoelde meldingen over oud aanbod te voorkomen. Bij een bredere zoek-URL is eveneens een nieuwe database of een nieuwe bronnaam verstandig. Het veranderen van meldingsinstellingen vereist alleen een herstart.

Bouwjaar, opgegeven catalogusjaar en eerste toelating worden onderscheiden in `year_basis`. Een jaar zoals "nieuwe accu in 2024" telt niet zelfstandig als bouwjaar. Er wordt geen RDW/VIN-dienst gebruikt om het bouwjaar onafhankelijk te bewijzen. Zet `allow_first_registration` op `false` als je alleen bronnen met expliciet bouwjaar wilt toestaan.

CarAPIS toont in de uitgevoerde scan USD-prijzen. De tool bewaart die valuta; hij verzint geen EUR-omrekening. Bij een EUR-prijsmaximum worden advertenties in andere valuta uitgesloten. Zonder prijsmaximum kunnen ze gewoon een melding geven.

## Welke websites en hoe?

- **CarAPIS:** HTML-voertuigkaarten, met behoud van merk/model/jaarfilters bij paginering. Geen API-aanroepen.
- **AutoScout24 NL/BE/DE:** de inventaris die de website zelf in de HTML meestuurt.
- **Marktplaats en 2dehands:** ingebedde `__NEXT_DATA__`, inclusief prijs in centen, bouwjaar en kilometerstand; alle voorraadpagina's.
- **Gaspedaal:** JSON-data in de HTML/React Flight, inclusief bouwjaar en de kliklink naar de oorspronkelijke aanbieder. Een `api.gaspedaal.nl/redirect/...` in een melding is hun gewone advertentie-redirect, geen betaalde data-API.
- **mobile.de:** HTML-kaarten en reguliere zoekopdrachten per registratiejaar. De brede zoekopdracht kreeg tijdens de test een 403 op pagina vier; de opdeling per jaar is vervolgens volledig geslaagd. Alle jaarpartities moeten lukken voordat de beginstand wordt bevestigd.
- **Kleinanzeigen:** advertentiekaarten, gezochte advertenties herkennen en paginering.

Aanbevolen eerste controle na installatie: open enkele links, vergelijk prijs/jaar/kilometers en controleer elke bronstatus. Onbekende layouts, blokkades, herhaalde pagina's en een te laag paginalimiet worden als fout geregistreerd, niet als nul resultaten. Een 403 wordt in `auto` desgewenst eenmaal met een gewone browser geprobeerd. Blijvende blokkades vereisen aanpassing of het tijdelijk uitschakelen van die bron.

De code bezoekt de gefilterde websites, niet iedere advertentiedetailpagina. Daarom zijn VIN, kenteken en plaats niet overal beschikbaar. Er is geen automatische login op autosites.

## Dubbelen en verzending

Nieuw betekent: voor deze scanner voor het eerst als passend waargenomen. Een portal kan later ook een oudere advertentie toevoegen; de scanner kan zonder betrouwbare publicatiedatum niet bewijzen dat de advertentie ook op de oorspronkelijke website pas net is geplaatst.

- Per bron: advertentie-ID en opgeschoonde URL.
- Over bronnen heen: dezelfde canonieke URL, een geldige VIN of een kenteken met landcode.
- **Geen VIN of kenteken beschikbaar? Dan zijn dubbele meldingen voor dezelfde auto mogelijk.** Twee auto's met hetzelfde jaar/prijs/km worden bewust niet automatisch samengevoegd.
- De beginstand is per bron. Een bron die eerst faalt, heeft pas na een volledige geslaagde scan een beginstand.
- Een herplaatsing met hetzelfde bekende VIN/kenteken geeft geen nieuwe melding.
- Prijsdalingen staan standaard uit. Zet `price_alerts` op `true`; `min_price_drop` bepaalt de minimumdaling per advertentie. Dit is geen voorspeller van een goede aankoopprijs.

Een melding gaat eerst naar een blijvende verzendwachtrij. De WhatsApp-service onthoudt event-ID's op schijf. De Python-service kan daardoor na een verloren HTTP-antwoord hetzelfde event opvragen zonder nogmaals te versturen.

**Een onzekere uitkomst krijgt `uncertain`.** Bij een crash precies rond het verzenden is mathematisch perfecte exactly-once-bezorging niet te garanderen. De tool verstuurt dan niet blind opnieuw. Controleer eerst je WhatsApp-chat en bekijk `events`:

```bash
python tools/run.py events
python tools/run.py resolve-event EVENT_ID sent
python tools/run.py resolve-event EVENT_ID retry
python tools/run.py resolve-event EVENT_ID discard
```

Gebruik alleen de passende beslissing, niet alle drie. `retry` stemt ook het bridge-logboek af en vereist dat de bridge bereikbaar is. In Docker:

```bash
docker compose exec scanner python -m watcher.cli events
docker compose exec scanner python -m watcher.cli resolve-event EVENT_ID retry
```

`sent` betekent dat de WhatsApp-server de melding heeft bevestigd. Het betekent niet dat de ontvanger de melding heeft gelezen of dat de telefoon een geluid heeft gemaakt. WhatsApp Web-automatisering is onofficieel en kan door wijzigingen of accountbeperkingen uitvallen.

## Status en onderhoud

```bash
docker compose logs --tail=100 scanner
docker compose logs --tail=100 whatsapp
docker compose exec scanner python -m watcher.cli status
```

`data/status.json` bevat de laatste scanresultaten; SQLite houdt per bron de laatste geslaagde controle en fouten bij. Status en logs zijn de foutsignalering; er is geen aparte automatische storingsmelding via WhatsApp geïmplementeerd. De QR-pagina toont de WhatsApp-verbindingsstatus.

Tijdens een actieve scan kan het CLI-statuscommando melden dat de scanner bezig is. Gebruik dan de logs of het laatste statusbestand. De scheduler leest config bij starten; na een configuratiewijziging herstart je de scanner.

Een bron uitschakelen: zet in de bijbehorende `sources`-regel `"enabled": false`. Verwijder een blokkade nooit door de database te wissen: daarmee verlies je de historiek en beginstand.

## Tests zelf uitvoeren

```bash
python -m unittest discover -s tests -v
node --test bridge/test.js
python tools/backtest.py
```

De Python/Node-tests hebben geen WhatsApp-account nodig en sturen geen echte berichten. De Python-integratietest wordt overgeslagen als Node niet is geïnstalleerd. Het backtestscript genereert zelf een reproduceerbaar scenario met vaste seed en schrijft `reports/backtest.json`.

## Echt historisch terugspelen

Elke volledige of mislukte scan wordt als JSON-snapshot opgeslagen in `data/snapshots/JJJJ-MM-DD/`. Die bestanden maken een echte replay van je eigen verzamelde waarnemingen mogelijk:

```bash
python tools/run.py replay data/snapshots --output reports/mijn-replay.json
```

De replay gebruikt een tijdelijke database, verstuurt geen berichten en wijzigt de live-database niet. Input moet chronologisch zijn, met tijdzone in iedere timestamp. Het rapport telt de events die de huidige filters en detectielogica zouden produceren. Zonder een onafhankelijke waarheid over alle marktadvertenties meet je daarmee geen echte markt-recall.

HTML-debugging kun je expliciet aanzetten met `scan --capture-html`. Die ruwe pagina's kunnen verkopersgegevens bevatten. De normale snapshots bewaren alleen de genormaliseerde advertentiegegevens. Er is nog geen automatische retentie: ruim oude snapshots zelf op of archiveer ze periodiek.

## Back-ups

```bash
docker compose exec scanner python -m watcher.cli backup data/backup.sqlite
```

Maak daarnaast een back-up van beide Docker-volumes. Kopieer bij een draaiende SQLite-database niet alleen het `.sqlite`-bestand: gebruik het backup-commando. WhatsApp-sessies en `.env` zijn geheim en horen niet in GitHub of gedeelde zipbestanden.

## Projectindeling

- `watcher/`: scanner, parsers, filters, SQLite, outbox, CLI en replay.
- `bridge/`: Node-helper met whatsapp-web.js, QR-pagina, authenticatie en verzendlogboek.
- `tools/`: setup, cross-platform launcher en dertigdagensimulatie.
- `tests/`, `fixtures/`: regressie- en integratietests; verkleinde bronstructuren van de bouwdatum.
- `reports/`: uitgevoerde tests en live-validatie, zonder echte WhatsApp-sessie.
- `compose.yaml`, Dockerfiles, `deploy/`: hosting- en servicebestanden.
- `.github/workflows/tests.yml`: tests bij push/PR; geen scanner op GitHub Actions en geen automatische deploy.

Upstreamdocumentatie: [whatsapp-web.js](https://github.com/wwebjs/whatsapp-web.js), [LocalAuth](https://wwebjs.dev/guide/creating-your-bot/authentication), [Playwright Python](https://playwright.dev/python/).
