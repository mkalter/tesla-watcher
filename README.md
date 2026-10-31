# Tesla Watcher — ntfy

Elke tien minuten zoeken naar nieuwe Tesla Model S-advertenties vanaf 2022. Meldingen gaan via **ntfy**, met een echte advertentiefoto, een vaste opbouw en een knop naar de advertentie. De standaardversie gebruikt geen WhatsApp-account, Chrome, Node of Docker.

Bronnen: CarAPIS-website (geen CarAPIS-API), AutoScout24 NL/BE/DE, Marktplaats, Gaspedaal, mobile.de, 2dehands.be en Kleinanzeigen.

## Starten

```sh
pip install -r requirements.txt
python main.py --check
python tools/setup.py
python main.py
```

Open je webscherm op de toegewezen hostingpoort (standaard 8080). Login: `admin`, met je bestaande `ADMIN_PASSWORD` of het automatisch gemaakte wachtwoord in `data/admin-password.txt`. Gebruik HTTPS voor een publiek bereikbare installatie.

## ntfy op je telefoon

1. Installeer de [ntfy-app voor Android of iOS](https://docs.ntfy.sh/subscribe/phone/).
2. Open het Tesla Watcher-webscherm. Onder **ntfy instellen** staan de server (`https://ntfy.sh`) en jouw automatisch gemaakte topicnaam.
3. Kies in de ntfy-app **Abonneren / Subscribe**, vul de server en topic in en sta telefoonmeldingen toe.
4. Klik in het webscherm op **Stuur testmelding**. Met **Stuur één Tesla per bron** ontvang je echte passende voorbeelden, met foto, uit je opgeslagen scans.

Een account of betaalkaart is voor deze opzet niet nodig. Op de gratis publieke ntfy-server is de onvoorspelbare topicnaam je toegang: iedereen die hem kent kan lezen en publiceren. De topic wordt privé opgeslagen in `data/ntfy-topic.txt` en staat nooit in de repository. Er gelden ntfy-limieten; bij HTTP 429 blijft een melding in de wachtrij voor later.

De server bevestigt dat een melding is aangenomen. Of jouw telefoon een push laat zien, hangt ook af van het app-abonnement, toestemming en telefooninstellingen. De eerste scan van iedere bron vormt een stille beginstand; alleen latere nieuwe advertenties geven gewone meldingen.

## Vast meldingsformaat

Titel: **Tesla Model S Long Range · € 49.950**

Bericht:

```text
Jaar: 2023
Kilometerstand: 48.000 km
Locatie: München · Duitsland
Bron: mobile.de
```

Bijlage: de foto uit precies die advertentie. Actie: **Bekijk advertentie**. Voorbeelden zijn als voorbeeld gemarkeerd. Prijs en foto worden niet verzonnen; onbekende gegevens blijven herkenbaar onbekend. De weergave van de fotobijlage verschilt per ntfy-app en telefoon. De gratis ntfy-attachmentcache bewaart uploads standaard drie uur; de advertentielink blijft in het bericht.

## Hosting en instellingen

Dezelfde code draait op een Python-host, eigen pc of mini-pc. Startcommando: `python main.py`. `PORT` en `SERVER_PORT` worden automatisch gelezen. Op KataBump moet je het gratis abonnement [elke vier dagen handmatig verlengen](https://docs.katabump.com/hosting/renew-your-server/).

| Variabele | Betekenis |
| --- | --- |
| `ADMIN_PASSWORD` | Wachtwoord webscherm, minstens 16 tekens |
| `NTFY_TOPIC` | Optioneel een eigen lange willekeurige topicnaam; anders automatisch gemaakt |
| `NTFY_SERVER` | `https://ntfy.sh` |
| `PORT` / `SERVER_PORT` | Hostingpoort, standaard 8080 |
| `HOST` | HTTP-bindadres, standaard 0.0.0.0 |
| `DATA_DIR` | Blijvende opslag, standaard `data/` naast de code |
| `CONFIG_FILE` | Standaard `config.light.json` |
| `ENABLE_HTTPS_TUNNEL` | Optioneel `1` voor een tijdelijke Cloudflare Quick Tunnel |

Bewaar `data/` op blijvende schijf. Deze map bevat de database, wachtrij, topic en scanarchieven. Eén actieve instantie per map. Je kunt meldingen in het webscherm pauzeren; de wachtrij blijft behouden. Gecomprimeerde snapshots blijven standaard zeven dagen bewaard.

Een optionele Quick Tunnel geeft een tijdelijke HTTPS-link zonder Cloudflare-account. De link staat in de console en `data/dashboard-url.txt`, verandert na herstart en heeft geen uptimegarantie. Zie de [Cloudflare-documentatie](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Websitefouten en dekking

Een 403, captcha, timeout of onbekende HTML wordt als bronfout opgeslagen en geldt niet als lege zoeklijst. Fouten staan in het webscherm. Er wordt geen captcha omzeild. Een scan die langer dan tien minuten duurt, overlapt niet met een volgende scan.

**mobile.de — controle 31 oktober 2026:** directe HTTP/1.1- en HTTP/2-aanvragen worden op KataBump geweigerd. Chromium headless is op de host geïnstalleerd en gestart nadat de eigenaar expliciet toestemming gaf de Chromium-sandbox voor die test uit te zetten. De browser bereikte mobile.de, maar kreeg HTTP 403 met de paginatitel `Zugriff verweigert / Access denied`. Nul pagina’s met advertenties zijn verwerkt. De testbrowser is gesloten; er is geen werkende directe monitoring op deze host bevestigd en er is geen aggregator geactiveerd. Zie `reports/mobile-host-browser-test.json`.

Bouwjaar wordt gebruikt waar beschikbaar, anders eerste toelating. `allow_first_registration=false` vereist bevestigd bouwjaar. Wijzig je filters, gebruik dan een nieuwe database voor een schone beginstand. Deduplicatie tussen websites gebruikt sterke identifiers zoals VIN of kenteken; zonder zulke identifiers kan dezelfde auto via twee bronnen worden gemeld.

Bij een expliciete ntfy-afwijzing blijft een melding in de wachtrij. Bij een netwerktimeout is de uitkomst mogelijk onzeker: de app probeert dat event niet blind opnieuw. Controleer ntfy en beoordeel het event in het webscherm.

## Tests

```sh
# Optionele oude WhatsApp-SDK is alleen nodig voor de bestaande regressietests.
pip install -r requirements-whatsapp.txt
python -m unittest discover -s tests -v
python tools/backtest.py
```

De dertigdaagse backtest is een synthetische simulatie, geen historische marktbacktest. Zie [TESTRESULTATEN.md](TESTRESULTATEN.md). Oude WhatsApp-/Docker-code blijft beschikbaar voor compatibiliteit, maar de standaardconfiguratie start die niet. Bestaande WhatsApp-sessiebestanden worden niet automatisch verwijderd.
