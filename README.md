# TreibstoffKarte CH ⛽

Interaktive Schweizerkarte mit kantonsweisen Durchschnittspreisen für Diesel und Benzin 95 – inkl. historischer Preisentwicklung und Zeitreise-Funktion.

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
- Im Detailbereich: «Preisverlauf 3 Monate →» anklicken
- Modal mit Linienchart: Diesel (orange) und Benzin 95 (blau)
- 13 Wochen Wochendurchschnitte (Dez 2025 – März 2026)
- Interaktiver Tooltip beim Hovern
- Schliessen: ✕, Klick ausserhalb oder ESC

### Zeitreise-Datepicker
- Datumsfeld oben rechts («Stand: …») anklicken
- Kalender mit verfügbaren Tagen (weiss) und Tagen ohne Daten (grau)
- Datenbereich: 03.12.2025 – 04.03.2026
- Datum auswählen → Karte, Rangliste und Detailansicht zeigen interpolierte Preise für diesen Tag

---

## Datenquellen & Methodik

### Preisdaten

Da keine kostenlose öffentliche API für kantonsweise Treibstoffpreise in der Schweiz existiert, werden **regionale Richtwerte** auf Basis bekannter Muster verwendet:

| | Wert |
|---|---|
| Nationaler Ø Diesel (März 2026) | ~1.78 CHF/L |
| Nationaler Ø Benzin 95 (März 2026) | ~1.71 CHF/L |
| Günstigste Kantone | BL, AG, SH, BS (Grenzkantone, hohe Tankstellendichte) |
| Teuerste Kantone | UR, GR, GL, AI (Bergregionen, höhere Logistikkosten) |

Der historische Wochenverlauf basiert auf einem nationalen Trendmodell (leicht sinkende Preise Dez 2025 → März 2026) mit kantonsüblicher Abweichung und deterministischem Rauschen pro Kanton.

> ⚠️ **Hinweis**: Alle Preise sind Schätzungen, keine garantierten Echtzeitpreise.
> Für tagesaktuelle Einzelpreise pro Tankstelle: **[benzin.tcs.ch](https://benzin.tcs.ch)**

Referenzquellen: [TCS Benzinpreis-Radar](https://benzin.tcs.ch) · [BFS Konsumentenpreisindex](https://www.bfs.admin.ch)

### Kartendaten
- Kantonsgrenzen: [swissBOUNDARIES3D](https://swisstopo.admin.ch) (TopoJSON via cmutel/gist, Fallback: idris-maps)
- Hintergrundkarte: [CartoDB Dark Matter](https://carto.com/basemaps/)

### Bibliotheken
- [Leaflet](https://leafletjs.com/) – interaktive Karte
- [topojson-client](https://github.com/topojson/topojson-client) – TopoJSON → GeoJSON Konvertierung
- [Chart.js](https://www.chartjs.org/) – Preisverlauf-Chart

---

## Lokale Entwicklung

Einzel-Datei-App, kein Build-Step nötig. Wegen CORS muss ein lokaler Webserver verwendet werden (direktes Öffnen als `file://` schlägt fehl):

```bash
# Python
python -m http.server 8080

# Node.js
npx serve .
```

→ http://localhost:8080

---

## Deployment (GitHub Pages)

Settings → Pages → Source: `main` / Root `/`

→ https://defendeggu.github.io/fuel-price-map-ch/
