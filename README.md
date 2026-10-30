# Tesla Watcher — Python

Elke tien minuten zoeken naar nieuwe Tesla Model S-advertenties vanaf 2022, met WhatsApp via een gekoppeld apparaat. De standaardinstallatie gebruikt één Python-proces: geen Chrome, Node.js, Docker of betaalde WhatsApp-API.

Bronnen: **CarAPIS-website**, AutoScout24 NL/BE/DE, Marktplaats, Gaspedaal, mobile.de, 2dehands.be en Kleinanzeigen. CarAPIS wordt als website gelezen; er wordt geen CarAPIS-API gebruikt.

## Snel starten

Python **3.12 op Linux x86_64** is getest. Maak lokaal desgewenst een virtualenv en voer uit:

```sh
pip install -r requirements.txt
python main.py --check
python tools/setup.py
python main.py
```

`setup.py` vraagt je ontvangernummer en maakt een lokaal `.env`-bestand. Open `http://localhost:8080`, log in als `admin` met het wachtwoord uit `.env`, en scan de QR via **WhatsApp → Instellingen → Gekoppelde apparaten**. Klik daarna op **Stuur testmelding**. Gebruik voor een openbaar bereikbare installatie de HTTPS-link van je host; Basic Auth en de QR moeten via HTTPS worden geopend.

Je telefoon moet WhatsApp kunnen koppelen. Neonize gebruikt het onofficiële linked-device-protocol; WhatsApp kan de verbinding verbreken of wijzigingen doorvoeren. De code gebruikt geen browser. Een apart verzendnummer is handig: berichten aan je eigen account geven mogelijk geen pushmelding. Test dit op je telefoon.

## Gratis hosting zonder betaalkaart

Dezelfde code kan bij een Python-host of op een computer thuis draaien. Er is geen speciale hosting-API nodig.

| Optie | Volgens aanbieder | Aandachtspunt |
| --- | --- | --- |
| [Enzonic Python](https://www.enzonic.com/python) | Gratis, zonder kaart, 512 MB RAM, 10 GB SSD, continu actief | Gratis capaciteit is beperkt; controleer het aanbod bij aanmaken |
| [KataBump](https://katabump.com/) | Gratis Python, zonder kaart | [Elke vier dagen handmatig verlengen](https://docs.katabump.com/hosting/renew-your-server/); anders opschorting en een dag later verwijdering |
| Eigen pc / mini-pc | Geen hostingabonnement of kaart | Computer moet aanblijven; stroom en internet zijn voor eigen rekening |

Aanbod gecontroleerd op 30 oktober 2026. Dit project is nog **niet bij deze providers gedeployed**; capaciteit, toegang tot autosites, het koppelen van WhatsApp en beschikbaarheid moeten daar worden gecontroleerd. Gratis hosting geeft geen gegarandeerde scanfrequentie of uptime.

### Instellingen in het hostingpaneel

1. Maak een **Python 3.12**-server en importeer deze GitHub-repository. Kies geen Docker-template voor de lichte versie.
2. Installatiecommando: `pip install -r requirements.txt` (bij automatische installatie van requirements is dit al geregeld).
3. Startcommando: `python main.py`.
4. Stel `WHATSAPP_TO` in op je **eigen** ontvangernummer met landcode, alleen cijfers, bijvoorbeeld `31612345678`.
5. Stel `ADMIN_PASSWORD` in op een zelfgekozen wachtwoord van minstens zestien tekens. De webgebruikersnaam is `admin`.
6. Gebruik de toegewezen `PORT` of `SERVER_PORT`. Beide worden automatisch gelezen; standaard is 8080. Open de HTTPS-webpagina en koppel WhatsApp met de QR.
7. Klik **Stuur testmelding** en controleer de chat én een pushmelding. De eerste succesvolle scan van elke bron wordt stil als beginstand opgeslagen. Alleen latere nieuwe advertenties geven meldingen.

Als de host alleen een privéconsole heeft, zet `TERMINAL_QR=1` om de QR daar te tonen. Dit werkt voor tekst-QR's; het webscherm blijft de standaard. Toon de console en QR niet publiek.

Bewaar de map **`data/` op blijvende schijf**. Daar staan de WhatsApp-sessie, database, wachtrij en scanarchieven. Zonder deze map moet je opnieuw koppelen en wordt opnieuw een beginstand opgebouwd. Maak een privébackup, en zet deze map of `.env` nooit op GitHub. Eén actieve instantie per data-map; geen automatische horizontale schaalvergroting.

## Configuratie en werking

`main.py` gebruikt `config.light.json`: één bron tegelijk, HTTP-verzoeken, tienminuteninterval, gecomprimeerde snapshots en zeven dagen snapshotbewaring. Er is geen browserfallback in deze modus. Een 403, captcha, timeout of gewijzigde HTML wordt als bronfout opgeslagen; een mislukte scan geldt niet als lege zoeklijst. Bekijk de bronstatus in het webscherm.

Instelbare omgevingsvariabelen:

| Naam | Betekenis |
| --- | --- |
| `WHATSAPP_TO` | Vast ontvangernummer inclusief landcode |
| `ADMIN_PASSWORD` | Wachtwoord webscherm, minstens zestien tekens |
| `PORT` / `SERVER_PORT` | HTTP-poort van de host |
| `DATA_DIR` | Blijvende opslagmap, standaard `data/` naast de code |
| `CONFIG_FILE` | Alternatieve configuratie, standaard `config.light.json` |
| `SEND_NOTIFICATIONS` | `false` om verzending bij een verse installatie te pauzeren; daarna blijft de webkeuze opgeslagen |
| `TERMINAL_QR` | Alleen `1` als je QR in een privéconsole wilt |

De scanner loopt zonder overlappende scans. Als een scan langer dan tien minuten duurt, volgt de volgende scan na voltooiing; er is geen garantie op precies tien minuten. De verzendworker werkt onafhankelijk van de scanner.

Bouwjaar wordt gebruikt waar beschikbaar, anders eerste registratie. Wil je alleen bevestigd bouwjaar, zet `allow_first_registration` op `false` en begin met een nieuwe data-map. Wijzigingen aan filters vereisen een nieuwe database om een betrouwbare beginstand te leggen.

Advertenties blijven over herstarts heen bekend. Dezelfde auto wordt tussen bronnen alleen samengevoegd bij sterke identifiers zoals VIN of kenteken. Een auto zonder zulke identifiers kan op meerdere websites een melding geven. Prijsveranderingen geven standaard geen melding.

Meldingen blijven bij een verbroken verbinding in de wachtrij. Bij een onderbroken of onduidelijke verzending krijgt het event de status **uncertain**, zodat geen automatische dubbele melding ontstaat. Controleer je chat en kies in het webscherm of de melding al is verstuurd, opnieuw mag worden geprobeerd of moet worden overgeslagen. Een bevestigde server-ID bewijst geen pushmelding op je telefoon.

RAM hangt af van paginaformaat en de gekoppelde WhatsApp-sessie. De Go-runtime heeft een zachte geheugenrichtwaarde van 96 MiB, geen harde limiet voor het hele proces. Test het werkelijke gebruik op je host na koppelen. Beschikbaarheid en websitevoorwaarden verschillen per bron; de code probeert geen captcha te omzeilen.

## Tests en backtest

```sh
python -m unittest discover -s tests -v
python tools/backtest.py
```

De 30-daagse backtest is een **synthetische simulatie**, geen historische marktbacktest. Voor een echte replay van je eigen opgeslagen snapshots:

```sh
python -m watcher.cli replay data/snapshots --output reports/my-replay.json
```

Zie [TESTRESULTATEN.md](TESTRESULTATEN.md) voor eerdere live bronmetingen en de beperkingen daarvan. Automatische tests bewijzen de scanner, wachtrij, herstarts, webauthenticatie en SDK-initialisatie; echte WhatsApp-aflevering vereist jouw koppeling en telefooncontrole.

De eerdere installatie met Chrome/Node en Docker blijft als alternatief beschikbaar in [docs/LEGACY_DOCKER.md](docs/LEGACY_DOCKER.md). Die is zwaarder en wordt niet gestart door `python main.py`.
