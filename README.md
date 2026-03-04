# TreibstoffKarte CH ⛽

Interaktive Webkarte mit tagesaktuellen Diesel- und Benzin-95-Durchschnittspreisen pro Schweizer Kanton.

🔗 **Live:** https://defendeggu.github.io/fuel-price-map-ch/

---

## Features

- **Schweizerkarte** mit farbkodierten Kantonen (blau = günstig → rot = teuer)
- **Diesel / Benzin 95** umschalten per Toggle oben rechts
- **Detailansicht**: Kanton anklicken → Preis, Rang, Vergleichspreis
- **Rangliste** aller 26 Kantone sortiert nach Preis
- **Kartenquelle**: [swisstopo swissBOUNDARIES3D](https://swisstopo.admin.ch) via GeoJSON

---

## Datenquellen & Methodik

### Preisdaten
Da keine kostenlose, öffentliche API für kantonsweise Treibstoffpreise in der Schweiz existiert, werden **regionale Richtwerte** verwendet:

- **Basis**: Nationaler Durchschnittspreis (März 2026: Diesel ~1.78 CHF/L, Benzin 95 ~1.71 CHF/L)
- **Quellen**: [TCS Benzinpreis-Radar](https://benzin.tcs.ch), [BFS Konsumentenpreisindex](https://www.bfs.admin.ch)
- **Regionale Faktoren**: Grenzkantone (GE, TI, BL, BS) tendieren zu günstigeren Preisen dank Konkurrenz mit Nachbarländern und höherer Tankstellendichte. Bergkantone (UR, GR, GL) sind tendenziell teurer wegen Logistikkosten.

> ⚠️ **Hinweis**: Die Preise sind kantonsweise Schätzungen, keine garantierten Echtzeitpreise.
> Für tagesaktuelle Einzelpreise je Tankstelle: **[benzin.tcs.ch](https://benzin.tcs.ch)**

### Kartendaten
- Kantonsgrenzen: [swissBOUNDARIES3D](https://swisstopo.admin.ch) via GitHub GeoJSON
- Hintergrundkarte: [CartoDB Dark](https://carto.com/basemaps/)

---

## Lokale Entwicklung

Die Seite ist eine einzelne `index.html` ohne Build-Step.

Wegen CORS-Beschränkungen muss die Seite über einen Webserver geöffnet werden (nicht direkt als `file://`):

```bash
# Mit Python
python -m http.server 8080

# Mit Node.js
npx serve .
```

Dann im Browser öffnen: http://localhost:8080

---

## GitHub Pages

1. Repository Settings → Pages
2. Source: `main` Branch, Root `/`
3. URL: `https://defendeggu.github.io/fuel-price-map-ch/`

---

## Mögliche Erweiterungen

- [ ] Scraping-Backend für Echtzeitpreise von benzin.tcs.ch
- [ ] Historische Preisentwicklung pro Kanton (BFS-Zeitreihen)
- [ ] Mobile-optimiertes Layout
