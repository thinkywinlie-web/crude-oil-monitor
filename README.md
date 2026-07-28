# Crude Oil News Monitor

Scant continu meerdere nieuwsbronnen — olie-specifiek (OilPrice, Rigzone, EIA,
Investing.com, Google News-zoekopdrachten voor crude/WTI/Brent/OPEC) én
algemeen wereldnieuws (BBC, Al Jazeera, CNBC, Guardian, NPR, Reuters via
Google News) dat wordt gefilterd op olie-relevante trefwoorden. Crude oil
nieuws krijgt altijd topprioriteit op het dashboard, met een aparte "URGENT"
markering voor woorden die vaak samengaan met plotselinge prijsschokken
(aanvallen, sancties, OPEC-besluiten, blokkades, etc).

Het resultaat is een statisch dashboard (`index.html`) met klikbare kaarten
die direct naar het originele artikel openen in een nieuw tabblad.

## Cruciale tijdsvensters die worden bijgehouden

| Event | Wanneer (ET) | Waarom belangrijk |
|---|---|---|
| EIA Weekly Petroleum Status Report | Woensdag 10:30 | Belangrijkste wekelijkse Amerikaanse voorraadcijfers — beweegt de prijs het meest |
| API Weekly Statistical Bulletin | Dinsdag 16:30 | Voorlopige cijfers, vaak indicator voor de EIA-cijfers een dag later |
| Baker Hughes Rig Count | Vrijdag 13:00 | Indicator voor toekomstige Amerikaanse productie |
| NYMEX WTI dagelijkse settlement | 14:30, pauze 17:00–18:00 | Officiële dagafsluiting van de future-prijs |
| OPEC+ vergaderingen | Onregelmatig | Grootste directe invloed op aanbod — **moet je handmatig invullen**, zie hieronder |

OPEC+ heeft geen vaste vergadercyclus. Vul bevestigde/verwachte data in bij
`OPEC_MEETING_DATES` bovenin `oil_monitor.py`, bijvoorbeeld:

```python
OPEC_MEETING_DATES = [
    ("2026-08-03", "OPEC+ maandelijks productie-overleg (verwacht)"),
]
```

Check regelmatig <https://www.opec.org/opec_web/en/press_room/28.htm> voor de
actuele kalender.

## Belangrijk: over "elke minuut updaten"

Een écht elke-minuut-schema kan **niet betrouwbaar gratis via GitHub
Actions** — GitHub voert cron-jobs met een interval van 1 minuut niet
gegarandeerd op tijd uit (vaak 5–15 min vertraging bij drukte, en zeer
frequente crons worden door GitHub soms automatisch teruggeschroefd). Nieuws
zelf verandert bovendien zelden echt elke minuut — nieuwe artikelen komen in
de praktijk om de paar minuten binnen. Daarom staat de workflow op **elke 5
minuten**, wat in de praktijk vrijwel altijd nieuwe crude-oil headlines
binnen enkele minuten na publicatie oppikt.

Wil je toch een echte 1-minuut-cyclus? Draai het script dan lokaal op je
eigen PC (die moet dan wel aan blijven staan) met dit commando in een lus:

```bash
# Linux/Mac
while true; do python3 oil_monitor.py; sleep 60; done

# Windows (PowerShell)
while ($true) { python oil_monitor.py; Start-Sleep -Seconds 60 }
```

Of zet het als Windows Taakplanner-taak / cron-job (`* * * * *`) die elke
minuut draait.

## Setup (gratis, 24/7, via GitHub Actions)

1. Maak een nieuwe GitHub-repo (publiek of privé), bijv. `crude-oil-monitor`.
2. Upload deze bestanden, met behoud van de mapstructuur:
   - `oil_monitor.py`
   - `requirements.txt`
   - `.github/workflows/monitor.yml`
3. Commit & push naar de `main`-branch.
4. Ga naar **Settings → Pages** in je repo, en zet "Deploy from a branch" op
   `main` / root. Na een paar minuten is je dashboard live op
   `https://<gebruikersnaam>.github.io/<repo-naam>/`.
5. Ga naar het **Actions**-tabblad → klik één keer op **Run workflow** om
   het meteen te testen.
6. Daarna draait het automatisch elke 5 minuten, 24/7, gratis.

## Lokaal testen

```bash
pip install -r requirements.txt
python3 oil_monitor.py
# open index.html in je browser
```

## Bestanden die worden aangemaakt

- `index.html` — het dashboard zelf
- `oil_news_log.csv` — volledige geschiedenis van alle gevonden artikelen
- `seen_links.json` — bijhoudt welke links al gezien zijn (voorkomt dubbele meldingen)

## Uitbreiden

- **Telegram/e-mail meldingen bij URGENT nieuws**: kan erbij, laat het weten.
- **Extra bronnen**: voeg toe aan `OIL_FEEDS` of `GENERAL_FEEDS` bovenin
  `oil_monitor.py` — elke geldige RSS/Atom-feed werkt.
- **Extra trefwoorden**: pas `OIL_KEYWORDS` / `URGENT_KEYWORDS` aan.
