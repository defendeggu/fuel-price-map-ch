# TreibstoffKarte CH ⛽

Interaktive Schweizerkarte mit kantonsweisen Durchschnittspreisen für Diesel und Benzin 95 – basierend auf echten Stationspreisen von benzin.tcs.ch, mit historischer Preisentwicklung, Zeitreise-Funktion und täglichen Updates.

🔗 **Live:** https://defendeggu.github.io/fuel-price-map-ch/

---

## Features

### Karte
- Alle 26 Kantone farbkodiert: **blau** = günstig → **rot** = teuer
- Hover-Tooltip mit Preis und Kantonsname
- Kanton anklicken für Detailansicht in der Sidebar

### Sidebar
- Aktueller Preis, Rang unter allen Kantonen, Vergleichspreis der anderen Kraftstoffsorte
- Scrollbare Rangliste aller 26 Kantone, sortiert nach Preis

### Kraftstoffwahl
- Toggle oben rechts: **Diesel** / **Benzin 95**
- Karte, Farben und Rangliste aktualisieren sich sofort

### Preisverlauf-Chart
- Im Detailbereich: «Preisverlauf →» anklicken
- Modal mit Linienchart: Diesel (orange) und Benzin 95 (blau)
- Zeitraum wählbar: **1M / 2M / 3M / 6M / 12M**
- Echte TCS-Tagesdaten (durchgezogene Linie) vs. geschätzte Werte (gestrichelte Linie) klar deklariert
- Disclaimer zeigt grün «Echte TCS-Daten» oder amber «Teils geschätzt» je nach Datenlage
- Interaktiver Tooltip beim Hovern
- Schliessen: ✕, Klick ausserhalb oder ESC

### Zeitreise-Datepicker
- Datumsfeld oben rechts («Stand: …») anklicken
- Kalender mit verfügbaren Tagen
- Datum auswählen → Karte, Rangliste und Detailansicht zeigen interpolierte Preise für diesen Tag

### Responsives Design
- Vollständig bedienbar auf Handy und Tablet
- Auf Mobile: Sidebar als Slide-up Bottom Sheet (Griff antippen zum Öffnen/Schliessen)
- Kanton antippen → Sidebar öffnet sich automatisch mit Detailansicht
- Chart-Modal als Bottom Sheet auf Mobile

---

## Daten-Pipeline (Live-Preise)

Täglich um **01:00 Uhr CET** läuft ein GitHub Actions Workflow:

1. Python-Scraper (`scripts/scrape.py`) loggt sich auf [benzin.tcs.ch](https://benzin.tcs.ch) ein (Azure B2C → Firebase)
2. Firebase ID-Token wird aus dem Netzwerk-Traffic abgegriffen
3. Alle ~3900 Stationen werden aus der Firestore-Datenbank geladen
4. PLZ aus Stationsadresse → Kanton (Swiss PLZ-Mapping)
5. Kantonspreise = Ø aller Stationspreise pro Kanton
6. Ergebnis wird als `data/canton-prices.json` committed
7. Eintrag für den heutigen Tag wird in `data/price-history.json` geschrieben (max. 400 Tage, für Charts)
8. Commit & Push; die Webseite lädt beim Start automatisch die aktuellsten Daten

```
.github/workflows/scrape.yml   ← Cron-Job (täglich 01:00 CET)
scripts/scrape.py              ← Playwright-Login + Firestore-Abfrage
data/canton-prices.json        ← Aktuelle Preise (täglich generiert)
data/price-history.json        ← Verlaufsdaten pro Kanton (täglich akkumuliert)
```

**Fallback**: Falls der TCS-Login nicht verfügbar ist, wird automatisch auf den nationalen Durchschnitt von [GlobalPetrolPrices.com](https://www.globalpetrolprices.com/Switzerland/) + BFS-Kantonsoffsets zurückgegriffen.

---

## Datenquellen

| Quelle | Verwendung |
|---|---|
| [benzin.tcs.ch](https://benzin.tcs.ch) | Stationspreise (~3900 Stationen, Ø pro Kanton) |
| [swisstopo](https://swisstopo.admin.ch) | Kantonsgrenzen (TopoJSON) |
| [CartoDB Dark Matter](https://carto.com/basemaps/) | Hintergrundkarte |

### Preisverlauf (Chart)
Seit März 2026 werden täglich echte TCS-Kantonspreise in `data/price-history.json` akkumuliert. Der Chart zeigt:
- **Echte Daten** (durchgezogene Linie): Tage mit einem TCS-Scraper-Eintrag
- **Geschätzte Daten** (gestrichelte Linie): Lücken werden mit einer nationalen Trendkurve + kantonstypischem Offset interpoliert

Je mehr Tage gesammelt sind, desto mehr der Kurve basiert auf Echtwerten. Bei ausreichend Daten im gewählten Zeitraum wechselt der Disclaimer auf grün.

### Bibliotheken
- [Leaflet](https://leafletjs.com/) – interaktive Karte
- [topojson-client](https://github.com/topojson/topojson-client) – TopoJSON → GeoJSON
- [Chart.js](https://www.chartjs.org/) – Preisverlauf-Chart

---

## Lokale Entwicklung

Einzel-Datei-App, kein Build-Step nötig. Wegen CORS muss ein lokaler Webserver verwendet werden:

```bash
python -m http.server 8080
# oder
npx serve .
```

→ http://localhost:8080

### Scraper lokal ausführen

```bash
pip install playwright aiohttp
playwright install chromium
TCS_EMAIL=xxx TCS_PASSWORD=yyy python scripts/scrape.py
```

---

## Deployment (GitHub Pages)

Settings → Pages → Source: `main` / Root `/`

→ https://defendeggu.github.io/fuel-price-map-ch/

**GitHub Secrets** (für den Scraper-Workflow):
- `TCS_EMAIL` – E-Mail-Adresse des TCS-Accounts
- `TCS_PASSWORD` – Passwort des TCS-Accounts
