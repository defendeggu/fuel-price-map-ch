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
- Veränderung gegenüber Vortag und Vorwoche in Rappen (nur zwischen Tagen mit derselben Berechnungsmethode)
- Spanne günstigste–teuerste Station im Kanton (aktueller Stand)
- Scrollbare Rangliste aller 26 Kantone, sortiert nach Preis, mit Veränderung zum Vortag

### Kraftstoffwahl
- Toggle oben rechts: **Diesel** / **Benzin 95**
- Karte, Farben und Rangliste aktualisieren sich sofort

### Preisverlauf-Chart
- Im Detailbereich: «Preisverlauf →» anklicken
- Modal mit Linienchart: Diesel (orange) und Benzin 95 (blau)
- Zeitraum wählbar: **1M / 2M / 3M / 6M / 12M**
- **Vergleich mit** einem anderen Kanton oder dem CH-Wert (Median der Kantone) für die gewählte Sorte
- Nur echte Tageswerte; gestrichelt = ältere Werte mit PLZ-Zuordnung (ungenau)
- Interaktiver Tooltip beim Hovern
- Schliessen: ✕, Klick ausserhalb oder ESC

### Zeitreise-Datepicker
- Datumsfeld oben rechts («Stand: …») anklicken
- Kalender mit verfügbaren Tagen
- Nur Tage mit Daten sind wählbar → Karte, Rangliste und Detailansicht zeigen die echten Preise dieses Tages

### Deeplinks
- Die Adresse hält Kanton, Sorte und Datum fest, z. B. `#GE/benzin/2026-11-01` (alle Teile optional, ohne Datum = aktueller Stand)
- Links lassen sich teilen; Zurück/Vor im Browser und manuelle Änderungen am `#…` werden übernommen

### Bedienung per Tastatur
- Sortenwahl, Datum, Kalendertage, Rangliste und Chart sind Buttons und per Tab erreichbar
- Rangliste: Enter wählt den Kanton und zoomt die Karte hin
- Chart und Kalender: Escape schliesst, der Fokus springt zurück; im Chart bleibt der Fokus im Dialog

### Responsives Design
- Vollständig bedienbar auf Handy und Tablet
- Auf Mobile: Sidebar als Slide-up Bottom Sheet (Griff antippen zum Öffnen/Schliessen)
- Kanton antippen → Sidebar öffnet sich automatisch mit Detailansicht
- Chart-Modal als Bottom Sheet auf Mobile

---

## Daten-Pipeline (Live-Preise)

Täglich um **01:00 Uhr CET** läuft ein GitHub Actions Workflow:

1. Unit-Tests (`tests/test_scrape.py`) laufen zuerst
2. `scripts/scrape.py` ruft alle Stationen (Diesel, Benzin 95) von der öffentlichen TCS-Cloud-Function ab (Zoom 18, damit keine Cluster entstehen, rund 3900 Stationen)
3. Jede Station wird per **Koordinate** dem Kanton zugeordnet (Point-in-Polygon gegen `data/cantons.topo.json`); Ausland (FL, Euro-Airport) fällt weg, Samnaun (zollfrei) wird ausgeschlossen
4. Ausreisserpreise (±40 % vom Landesmedian) werden verworfen; Kantonswert = **getrimmter Mittelwert** (günstigste/teuerste 10 % weggelassen) der Stationspreise, mit Stationszahl. Kein Median, weil viele Stationen denselben Listenpreis haben und der Median dann fast überall identisch wäre
5. Plausibilitätsprüfung: alle 26 Kantone belegt, genug Stationen, kein Sprung > 15 % zum letzten Stand. Sonst endet der Lauf mit Fehler (Workflow rot, Mail von GitHub) und es wird **nichts** committet. Es gibt keine geschätzten oder erfundenen Werte
6. `data/canton-prices.json` (aktueller Stand) und `data/price-history.json` (Tagesverlauf, max. 400 Tage) werden committet

`canton-prices.json` enthält pro Kanton `diesel`/`benzin` (Kantonswert), `n_*` (Stationszahl) und `min_*`/`max_*` (günstigste/teuerste Station). Verlaufseinträge tragen `method` (aktuell `trim10`); das Frontend vergleicht nur Tage mit gleicher Methode.

```
.github/workflows/scrape.yml   ← Cron-Job (täglich 01:00 CET)
scripts/scrape.py              ← Abruf, Aggregation, Plausibilitätsprüfung
scripts/cantons.py             ← Koordinate → Kanton (nur Standardbibliothek)
data/cantons.topo.json         ← Kantonsgrenzen (TopoJSON)
vendor/                        ← Leaflet, topojson-client, Chart.js, Schriften (selbst gehostet)
data/canton-prices.json        ← Aktuelle Preise inkl. Stationszahl
data/price-history.json        ← Verlauf pro Kanton (täglich akkumuliert)
tests/test_scrape.py           ← Unit-Tests (unittest)
tests/app.spec.js              ← E2E-Tests der Karte (Playwright)
index.html                     ← nur Markup und Content-Security-Policy
css/app.css, js/app.js         ← Styles und Logik (kein Inline-Skript, keine onclick-Attribute)
.github/dependabot.yml         ← wöchentliche Updates für Actions (auf SHA gepinnt) und npm
```

**Sicherheit:** Die Seite setzt eine strenge Content-Security-Policy (`script-src 'self'`, keine Fremd-Hosts ausser den OSM-Kacheln). Inhalte werden per DOM aufgebaut, nicht per `innerHTML`; ein E2E-Test schlägt bei CSP-Verstössen und Anfragen an fremde Server an.

**Hinweis zur Historie:** Einträge bis 13.11.2026 ordneten Stationen noch per PLZ-Tabelle den Kantonen zu (ungenau, Genf hatte keine eigenen Daten). Im Chart sind sie gestrichelt markiert. Ab `geo: true` gilt die Koordinaten-Zuordnung.

---

## Datenquellen

| Quelle | Verwendung |
|---|---|
| [benzin.tcs.ch](https://benzin.tcs.ch) | CH-Stationspreise (~3900 Stationen, getrimmter Mittelwert pro Kanton) |
| [swisstopo](https://swisstopo.admin.ch) | Kantonsgrenzen (TopoJSON) |
| [OpenStreetMap](https://www.openstreetmap.org/) | Hintergrundkarte |

### Preisverlauf (Chart)
Seit März 2026 werden täglich Kantonspreise in `data/price-history.json` akkumuliert. Der Chart zeigt ausschliesslich diese echten Tageswerte (bei langen Zeiträumen jeder n. Tag). Es gibt keine Schätzkurve mehr.

### Bibliotheken und Schriften
Alle liegen im Repo unter `vendor/` (feste Versionen, Lizenzen in `vendor/licenses/`); die Seite lädt nichts von Fremd-CDNs. Einzige externe Quelle sind die OpenStreetMap-Kartenkacheln.
- [Leaflet](https://leafletjs.com/) 1.9.4 – interaktive Karte
- [topojson-client](https://github.com/topojson/topojson-client) 3.1.0 – TopoJSON → GeoJSON
- [Chart.js](https://www.chartjs.org/) 4.6.1 – Preisverlauf-Chart
- Schriften Barlow Condensed und DM Mono (via [Fontsource](https://fontsource.org/) 5.3.0, SIL Open Font License)

Zum Aktualisieren: neue Version mit `npm pack <paket>@<version>` holen, die Datei unter `vendor/` ersetzen (Versionsnummer im Dateinamen) und den Verweis in `index.html` anpassen.

---

## Lokale Entwicklung

Statische Seite ohne Build-Step. Wegen CORS muss ein lokaler Webserver verwendet werden:

```bash
python -m http.server 8080
# oder
npx serve .
```

→ http://localhost:8080

### Scraper lokal ausführen

```bash
python3 scripts/scrape.py          # keine Abhängigkeiten, keine Zugangsdaten
python3 -m unittest discover -s tests -p 'test_*.py'
npm ci && npx playwright test      # E2E-Tests (starten einen lokalen Server auf Port 8099)
```

---

## Deployment (GitHub Pages)

Settings → Pages → Source: `main` / Root `/`

→ https://defendeggu.github.io/fuel-price-map-ch/

Der Scraper-Workflow braucht keine Secrets.
