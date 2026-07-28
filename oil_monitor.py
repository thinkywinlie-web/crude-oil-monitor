#!/usr/bin/env python3
"""
Crude Oil News Monitor
=======================
Scant meerdere nieuwsbronnen (olie-specifiek + algemeen wereldnieuws),
geeft crude oil nieuws topprioriteit, en houdt de cruciale tijdsvensters
van de olie-markt (EIA, API, OPEC+, beursuren) bij.

Output: een statische HTML-dashboard (index.html) met klikbare links
die direct naar de originele bron gaan.
"""

import feedparser
import json
import os
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

SEEN_FILE = "seen_links.json"
OUTPUT_HTML = "index.html"
LOG_CSV = "oil_news_log.csv"
MAX_AGE_HOURS = 48          # hoe lang een item op het dashboard blijft
MAX_ITEMS_PER_SECTION = 60

# --- Tier 1: olie-specifieke bronnen (alles hierin telt als hoge prioriteit)
OIL_FEEDS = {
    "OilPrice.com": "https://oilprice.com/rss/main",
    "Rigzone": "https://www.rigzone.com/news/rss/rigzone_latest.aspx",
    "EIA Today in Energy": "https://www.eia.gov/rss/todayinenergy.xml",
    "Investing.com Commodities": "https://www.investing.com/rss/news_301.rss",
    "Google News: Crude Oil": "https://news.google.com/rss/search?q=%22crude%20oil%22%20OR%20WTI%20OR%20Brent%20OR%20OPEC&hl=en-US&gl=US&ceid=US:en",
    "Google News: OPEC": "https://news.google.com/rss/search?q=OPEC%2B%20oil%20production&hl=en-US&gl=US&ceid=US:en",
}

# --- Tier 2: algemeen nieuws, wordt gefilterd op olie-gerelateerde keywords
GENERAL_FEEDS = {
    "BBC World": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "CNBC World": "https://www.cnbc.com/id/100727362/device/rss/rss.html",
    "Guardian World": "https://www.theguardian.com/world/rss",
    "NPR News": "https://feeds.npr.org/1004/rss.xml",
    "Reuters (via Google News)": "https://news.google.com/rss/search?q=site:reuters.com%20oil&hl=en-US&gl=US&ceid=US:en",
}

# Keywords die een algemeen artikel alsnog naar de crude-oil sectie promoten
OIL_KEYWORDS = [
    "crude oil", "crude", "wti", "brent", "opec", "opec+", "barrel", "barrels",
    "oil price", "oil market", "oil field", "oilfield", "pipeline", "refinery",
    "petroleum", "oil export", "oil import", "oil sanctions", "strait of hormuz",
    "saudi aramco", "rosneft", "oil rig", "eia inventory", "api inventory",
    "oil inventories", "oil production", "oil supply", "oil demand",
    "energy sanctions", "iran oil", "russia oil", "venezuela oil", "shale",
    "nymex", "ice brent", "oil tanker", "gulf of mexico oil",
]

# Extra-hoge urgentie: dit zijn de woorden die vaak samengaan met plotselinge
# prijsschokken (aanvallen, sancties, OPEC-besluiten, geopolitiek)
URGENT_KEYWORDS = [
    "attack", "strike", "drone", "missile", "explosion", "sanction", "embargo",
    "opec+ decision", "opec meeting", "output cut", "production cut",
    "supply disruption", "outage", "blockade", "war", "ceasefire",
    "strait of hormuz", "houthi", "tanker seized", "pipeline attack",
]

# ---------------------------------------------------------------------------
# CRUCIALE TIJDSVENSTERS VOOR DE CRUDE OIL MARKT (alle tijden in ET)
# ---------------------------------------------------------------------------

def next_weekday_time(weekday, hour, minute):
    """Volgende datum/tijd (ET) voor een gegeven weekday (0=maandag) en tijd."""
    now = datetime.now(ET)
    days_ahead = (weekday - now.weekday()) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def get_critical_windows():
    """
    Geeft een lijst van de belangrijkste, regelmatig terugkerende momenten
    voor de crude oil markt. OPEC+ vergaderingen hebben geen vaste cyclus
    en moeten handmatig worden aangevuld in OPEC_MEETING_DATES hieronder.
    """
    windows = [
        {
            "name": "EIA Weekly Petroleum Status Report",
            "note": "Belangrijkste wekelijkse voorraadcijfers (VS). Normaal woensdag 10:30 ET "
                    "(donderdag 11:00 ET bij een maandag-feestdag).",
            "when": next_weekday_time(2, 10, 30),  # woensdag
        },
        {
            "name": "API Weekly Statistical Bulletin",
            "note": "Voorlopige voorraadcijfers, vaak vooraf-indicator voor de EIA-cijfers de volgende dag.",
            "when": next_weekday_time(1, 16, 30),  # dinsdag 16:30 ET
        },
        {
            "name": "Baker Hughes Rig Count",
            "note": "Wekelijks Amerikaans booreiland-aantal, indicator voor toekomstige productie.",
            "when": next_weekday_time(4, 13, 0),  # vrijdag 13:00 ET
        },
        {
            "name": "CME/NYMEX WTI dagelijkse sluiting",
            "note": "Dagelijkse handelsonderbreking 17:00-18:00 ET (zon t/m vrij), settlement rond 14:30 ET.",
            "when": _next_daily(14, 30),
        },
    ]
    windows.extend(get_opec_windows())
    windows.sort(key=lambda w: w["when"])
    return windows


def _next_daily(hour, minute):
    now = datetime.now(ET)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


# Vul hier handmatig bevestigde/verwachte OPEC(+) vergaderdata in (ET, 12:00 als placeholder-tijd).
# Check regelmatig https://www.opec.org/opec_web/en/press_room/28.htm voor updates.
OPEC_MEETING_DATES = [
    # ("2026-08-03", "OPEC+ maandelijks productie-overleg (verwacht)"),
]


def get_opec_windows():
    out = []
    now = datetime.now(ET)
    for date_str, label in OPEC_MEETING_DATES:
        when = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=12, minute=0, tzinfo=ET
        )
        if when > now:
            out.append({"name": label, "note": "Handmatig ingevoerde OPEC+ datum.", "when": when})
    return out


def is_market_open_now():
    """Ruwe indicatie of de NYMEX WTI-markt nu open is (zon 18:00 ET t/m vrij 17:00 ET,
    met dagelijkse pauze 17:00-18:00 ET)."""
    now = datetime.now(ET)
    wd, h = now.weekday(), now.hour  # 0=maandag ... 6=zondag
    if wd == 5:  # zaterdag: altijd dicht
        return False
    if wd == 6 and h < 18:  # zondag voor 18:00: dicht
        return False
    if wd == 4 and h >= 17:  # vrijdag na 17:00: dicht
        return False
    if h == 17:  # dagelijkse pauze 17:00-18:00
        return False
    return True


# ---------------------------------------------------------------------------
# NIEUWS OPHALEN & SCOREN
# ---------------------------------------------------------------------------

def clean_html(raw):
    return re.sub("<[^<]+?>", "", raw or "").strip()


def parse_entry_time(entry):
    for key in ("published", "updated"):
        val = entry.get(key)
        if val:
            try:
                return parsedate_to_datetime(val).astimezone(UTC)
            except Exception:
                pass
    return datetime.now(UTC)


def score_text(text):
    text_l = text.lower()
    is_oil = any(kw in text_l for kw in OIL_KEYWORDS)
    is_urgent = any(kw in text_l for kw in URGENT_KEYWORDS)
    return is_oil, is_urgent


def fetch_feed(source_name, url, force_oil_tier):
    items = []
    try:
        parsed = feedparser.parse(url)
    except Exception as e:
        print(f"  [FOUT] {source_name}: {e}")
        return items

    for entry in parsed.entries:
        title = clean_html(entry.get("title", ""))
        summary = clean_html(entry.get("summary", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue

        is_oil, is_urgent = score_text(title + " " + summary)
        is_oil = is_oil or force_oil_tier

        items.append({
            "title": title,
            "summary": summary[:220],
            "link": link,
            "source": source_name,
            "published_utc": parse_entry_time(entry).isoformat(),
            "is_oil": is_oil,
            "is_urgent": is_urgent,
        })
    return items


def collect_all_items():
    all_items = []
    print("Ophalen olie-specifieke bronnen...")
    for name, url in OIL_FEEDS.items():
        found = fetch_feed(name, url, force_oil_tier=True)
        print(f"  {name}: {len(found)} items")
        all_items.extend(found)

    print("Ophalen algemene nieuwsbronnen (gefilterd op olie-relevantie)...")
    for name, url in GENERAL_FEEDS.items():
        found = fetch_feed(name, url, force_oil_tier=False)
        print(f"  {name}: {len(found)} items")
        all_items.extend(found)

    return all_items


# ---------------------------------------------------------------------------
# DEDUP / PERSISTENTIE
# ---------------------------------------------------------------------------

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f)


def append_log(new_items):
    is_new_file = not os.path.exists(LOG_CSV)
    with open(LOG_CSV, "a", encoding="utf-8") as f:
        if is_new_file:
            f.write("published_utc,source,is_oil,is_urgent,title,link\n")
        for it in new_items:
            title = it["title"].replace(",", ";").replace("\n", " ")
            f.write(f'{it["published_utc"]},{it["source"]},{it["is_oil"]},{it["is_urgent"]},"{title}",{it["link"]}\n')


# ---------------------------------------------------------------------------
# HTML DASHBOARD
# ---------------------------------------------------------------------------

def fmt_dt(iso_str):
    dt = datetime.fromisoformat(iso_str).astimezone(ET)
    return dt.strftime("%a %d %b, %H:%M ET")


def render_card(item):
    badge = ""
    if item["is_urgent"]:
        badge = '<span class="badge urgent">URGENT</span>'
    elif item["is_oil"]:
        badge = '<span class="badge oil">CRUDE OIL</span>'
    return f"""
    <a class="card" href="{item['link']}" target="_blank" rel="noopener noreferrer">
      <div class="card-top">{badge}<span class="source">{item['source']}</span></div>
      <div class="card-title">{item['title']}</div>
      <div class="card-summary">{item['summary']}</div>
      <div class="card-time">{fmt_dt(item['published_utc'])}</div>
    </a>"""


def render_window_row(w):
    now = datetime.now(ET)
    delta = w["when"] - now
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    countdown = f"{hours}u {minutes}m" if hours < 48 else f"{delta.days}d"
    return f"""
    <tr>
      <td>{w['name']}</td>
      <td>{w['when'].strftime('%a %d %b, %H:%M ET')}</td>
      <td class="countdown">over {countdown}</td>
      <td class="note">{w['note']}</td>
    </tr>"""


def build_html(oil_items, general_items, windows, generated_at):
    market_status = "OPEN" if is_market_open_now() else "GESLOTEN"
    market_class = "market-open" if is_market_open_now() else "market-closed"

    oil_cards = "\n".join(render_card(it) for it in oil_items[:MAX_ITEMS_PER_SECTION]) or "<p class='empty'>Nog geen recente crude oil items.</p>"
    general_cards = "\n".join(render_card(it) for it in general_items[:MAX_ITEMS_PER_SECTION]) or "<p class='empty'>Nog geen recente algemene items.</p>"
    window_rows = "\n".join(render_window_row(w) for w in windows)

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="60">
<title>Crude Oil News Monitor</title>
<style>
  :root {{
    --bg: #0b0e11;
    --panel: #14181d;
    --border: #262c33;
    --text: #e8ecef;
    --muted: #8a939c;
    --oil: #d99a3c;
    --urgent: #d9483c;
    --open: #3cd97e;
    --closed: #6b7280;
    --link: #5aa9e6;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0;
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  header {{
    padding: 20px 28px; border-bottom: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
  }}
  header h1 {{ margin: 0; font-size: 22px; }}
  header .meta {{ color: var(--muted); font-size: 13px; }}
  .status-pill {{
    padding: 6px 14px; border-radius: 20px; font-weight: 600; font-size: 13px;
  }}
  .market-open {{ background: rgba(60,217,126,0.15); color: var(--open); border: 1px solid var(--open); }}
  .market-closed {{ background: rgba(107,114,128,0.15); color: var(--closed); border: 1px solid var(--closed); }}

  .windows {{
    margin: 24px 28px; background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px 20px; overflow-x: auto;
  }}
  .windows h2 {{ margin-top: 0; font-size: 16px; color: var(--oil); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; color: var(--muted); font-weight: 600; padding: 6px 8px; border-bottom: 1px solid var(--border); }}
  td {{ padding: 8px; border-bottom: 1px solid var(--border); vertical-align: top; }}
  .countdown {{ color: var(--oil); font-weight: 600; white-space: nowrap; }}
  .note {{ color: var(--muted); }}

  .columns {{ display: grid; grid-template-columns: 1.3fr 1fr; gap: 20px; margin: 0 28px 28px; }}
  @media (max-width: 900px) {{ .columns {{ grid-template-columns: 1fr; }} }}

  .section h2 {{ font-size: 16px; margin: 0 0 12px; }}
  .section.oil h2 {{ color: var(--oil); }}

  .card {{
    display: block; background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px; margin-bottom: 10px;
    text-decoration: none; color: var(--text); transition: border-color .15s;
  }}
  .card:hover {{ border-color: var(--link); }}
  .card-top {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
  .source {{ color: var(--muted); font-size: 12px; }}
  .badge {{ font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }}
  .badge.oil {{ background: rgba(217,154,60,0.15); color: var(--oil); }}
  .badge.urgent {{ background: rgba(217,72,60,0.15); color: var(--urgent); }}
  .card-title {{ font-size: 15px; font-weight: 600; margin-bottom: 4px; }}
  .card-summary {{ font-size: 13px; color: var(--muted); margin-bottom: 6px; }}
  .card-time {{ font-size: 11px; color: var(--muted); }}
  .empty {{ color: var(--muted); font-size: 13px; }}
  footer {{ text-align: center; color: var(--muted); font-size: 12px; padding: 20px; }}
</style>
</head>
<body>

<header>
  <div>
    <h1>&#128293; Crude Oil News Monitor</h1>
    <div class="meta">Laatste update: {generated_at.astimezone(ET).strftime('%a %d %b %Y, %H:%M:%S ET')} &middot; ververst elke minuut</div>
  </div>
  <div class="status-pill {market_class}">NYMEX WTI markt: {market_status}</div>
</header>

<div class="windows">
  <h2>&#9200; Cruciale tijdsvensters crude oil markt</h2>
  <table>
    <tr><th>Event</th><th>Wanneer (ET)</th><th>Countdown</th><th>Waarom belangrijk</th></tr>
    {window_rows}
  </table>
</div>

<div class="columns">
  <div class="section oil">
    <h2>&#128176; Crude Oil &mdash; topprioriteit ({len(oil_items)})</h2>
    {oil_cards}
  </div>
  <div class="section">
    <h2>&#127760; Algemeen wereldnieuws ({len(general_items)})</h2>
    {general_cards}
  </div>
</div>

<footer>Klik op een kaart om direct naar de bron te gaan &middot; automatisch gegenereerd</footer>

</body>
</html>"""


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    seen = load_seen()
    now_utc = datetime.now(UTC)
    cutoff = now_utc - timedelta(hours=MAX_AGE_HOURS)

    raw_items = collect_all_items()

    new_items = []
    for it in raw_items:
        if it["link"] not in seen:
            seen[it["link"]] = it["published_utc"]
            new_items.append(it)

    if new_items:
        append_log(new_items)
    save_seen(seen)

    # Bouw dashboard uit de items die we deze run hebben opgehaald (dedup binnen run)
    dedup_by_link = {}
    for it in raw_items:
        dedup_by_link[it["link"]] = it
    all_current = [
        it for it in dedup_by_link.values()
        if datetime.fromisoformat(it["published_utc"]) >= cutoff
    ]
    all_current.sort(key=lambda x: x["published_utc"], reverse=True)

    oil_items = [it for it in all_current if it["is_oil"]]
    oil_items.sort(key=lambda x: (not x["is_urgent"], x["published_utc"]), reverse=False)
    oil_items.sort(key=lambda x: x["is_urgent"], reverse=True)  # urgent eerst
    general_items = [it for it in all_current if not it["is_oil"]]

    windows = get_critical_windows()
    html = build_html(oil_items, general_items, windows, now_utc)

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nKlaar. {len(new_items)} nieuwe items dit run, {len(oil_items)} crude-oil items en "
          f"{len(general_items)} algemene items op het dashboard.")


if __name__ == "__main__":
    main()
